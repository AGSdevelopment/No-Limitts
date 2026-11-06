"""Shift swaps between Support Team teammates (approved by Rosters), the open shift board, shift reminders and the
monthly Finance budget forecast PDF."""
import asyncio
import io
import os
import secrets
from datetime import datetime, timedelta, timezone
from html import escape
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import Response
from pydantic import BaseModel

from core import P, current_user, db, dmy, logger, notify, now_iso
from email_service import send_email
from pdf_brand import FIRST_TOP, add_logo
from routes.participant_mgmt import ShiftIn, clash, create_shift, shift_view
from routes.pm_common import is_finance, is_rosters, now_perth, rosters_user, span, token_user
from routes.pm_funding import funding_out, funding_usage

router = APIRouter(prefix="/api")


async def rosters_ids() -> list:
    return [u["user_id"] async for u in db.users.find({"$or": [{"permissions": "rosters"}, {"role": "admin"}], "hidden": {"$ne": True}},
                                                      {"_id": 0, "user_id": 1})]


def label(s: dict) -> str:
    return f"{s['participant_name']} {dmy(s['date'])} {s['start']}-{s['end']}"


LIVE = ("pending_acceptance", "accepted")


async def close_swap(s: dict, why: str):
    """Withdraw a pending swap when its shift is cancelled or declined, and tell the teammate."""
    sw = s.get("swap") or {}
    if sw.get("status") in ("pending_teammate", "pending_rosters"):
        await db.shifts.update_one({"shift_id": s["shift_id"]}, {"$set": {"swap.status": "withdrawn"}})
        await notify([sw["to_id"]], "shift", f"Swap withdrawn: {label(s)}", f"This offer no longer stands: {why}.", "/pm/rostering")


def still_live(s: dict):
    if s["status"] not in LIVE or span(s)[0] <= now_perth():
        raise HTTPException(400, "This shift is no longer available to swap")


# ---- Swaps ----

@router.get("/shifts/{shift_id}/teammates")
async def teammates(shift_id: str, user=Depends(current_user)):
    s = await db.shifts.find_one({"shift_id": shift_id, "worker_id": user["user_id"]}, P)
    if not s:
        raise HTTPException(404, "Shift not found")
    p = await db.participants.find_one({"participant_id": s["participant_id"]}, P) or {}
    ids = [i for i in p.get("assigned_ids", []) if i != user["user_id"]]
    return [{"user_id": u["user_id"], "name": u["name"]}
            async for u in db.users.find({"user_id": {"$in": ids}, "hidden": {"$ne": True}}, {"_id": 0, "user_id": 1, "name": 1}).sort("name", 1)]


class SwapIn(BaseModel):
    to_worker_id: str
    note: str = ""


@router.post("/shifts/{shift_id}/swap")
async def offer_swap(shift_id: str, body: SwapIn, user=Depends(current_user)):
    s = await db.shifts.find_one({"shift_id": shift_id, "worker_id": user["user_id"]}, P)
    if not s or s["status"] not in ("pending_acceptance", "accepted"):
        raise HTTPException(400, "This shift can't be swapped")
    if span(s)[0] <= now_perth():
        raise HTTPException(400, "This shift has already started")
    if (s.get("swap") or {}).get("status") in ("pending_teammate", "pending_rosters"):
        raise HTTPException(400, "There's already a swap request on this shift")
    p = await db.participants.find_one({"participant_id": s["participant_id"]}, P) or {}
    to = await db.users.find_one({"user_id": body.to_worker_id}, P)
    if not to or to["user_id"] == user["user_id"] or to["user_id"] not in p.get("assigned_ids", []):
        raise HTTPException(400, "Choose a teammate on this participant's Support Team")
    why = await clash(to["user_id"], s)
    if why:
        raise HTTPException(409, why)
    swap = {"to_id": to["user_id"], "to_name": to["name"], "from_name": s["worker_name"], "note": body.note.strip()[:300],
            "status": "pending_teammate", "at": now_iso()}
    await db.shifts.update_one({"shift_id": shift_id}, {"$set": {"swap": swap}})
    await notify([to["user_id"]], "shift", f"Shift offered to you: {label(s)}",
                 f"{s['worker_name']} would like you to take this shift." + (f" “{swap['note']}”" if swap["note"] else ""), "/pm/rostering")
    return {"swap": swap}


@router.get("/shifts-offers")
async def my_offers(user=Depends(current_user)):
    """Swap offers made to me, swaps waiting for Rosters (Rosters only) and open shifts I can claim."""
    now = now_perth().date().isoformat()
    offers = [shift_view(s, user) async for s in db.shifts.find({"swap.to_id": user["user_id"], "swap.status": "pending_teammate",
                                                                "status": {"$in": list(LIVE)}, "date": {"$gte": now}}, P)]
    approvals = [shift_view(s, user) async for s in db.shifts.find({"swap.status": "pending_rosters", "status": {"$in": list(LIVE)}}, P)] if is_rosters(user) else []
    open_shifts = []
    async for s in db.shifts.find({"open": True, "status": "declined", "rerostered": {"$in": [None, ""]}, "date": {"$gte": now}}, P).sort([("date", 1), ("start", 1)]):
        if span(s)[0] <= now_perth():
            continue
        p = await db.participants.find_one({"participant_id": s["participant_id"]}, {"_id": 0, "assigned_ids": 1}) or {}
        mine = user["user_id"] in p.get("assigned_ids", []) and user["user_id"] != s["worker_id"]
        if is_rosters(user) or (mine and not await clash(user["user_id"], s)):
            open_shifts.append({**shift_view(s, user), "can_claim": mine})
    return {"offers": offers, "approvals": approvals, "open": open_shifts}


class YesNo(BaseModel):
    accept: bool


@router.post("/shifts/{shift_id}/swap/respond")
async def respond_swap(shift_id: str, body: YesNo, user=Depends(current_user)):
    s = await db.shifts.find_one({"shift_id": shift_id, "swap.to_id": user["user_id"], "swap.status": "pending_teammate"}, P)
    if not s:
        raise HTTPException(404, "Swap offer not found")
    still_live(s)
    if body.accept:
        why = await clash(user["user_id"], s)
        if why:
            raise HTTPException(409, why)
    status = "pending_rosters" if body.accept else "declined_by_teammate"
    await db.shifts.update_one({"shift_id": shift_id}, {"$set": {"swap.status": status, "swap.responded_at": now_iso()}})
    if body.accept:
        await notify(await rosters_ids(), "shift", f"Shift swap to approve: {label(s)}",
                     f"{s['worker_name']} → {user['name']}. Approve it in Rostering.", "/pm/rostering")
    await notify([s["worker_id"]], "shift", f"Swap {'accepted' if body.accept else 'declined'} by {user['name']}",
                 f"{label(s)}: " + ("waiting for Rosters to approve." if body.accept else "the shift stays with you."), "/pm/rostering")
    return {"status": status}


class ApproveSwap(BaseModel):
    approve: bool


@router.post("/shifts/{shift_id}/swap/decide")
async def decide_swap(shift_id: str, body: ApproveSwap, user=Depends(rosters_user)):
    s = await db.shifts.find_one({"shift_id": shift_id, "swap.status": "pending_rosters"}, P)
    if not s:
        raise HTTPException(404, "No swap waiting for approval on this shift")
    sw = s["swap"]
    if body.approve:
        still_live(s)
        why = await clash(sw["to_id"], s, ignore=shift_id)
        if why:
            raise HTTPException(409, why)
        await db.shifts.update_one({"shift_id": shift_id}, {"$set": {
            "worker_id": sw["to_id"], "worker_name": sw["to_name"], "status": "accepted", "swap.status": "approved",
            "swap.decided_by": user.get("name") or "", "swap.decided_at": now_iso(), "previous_worker_id": s["worker_id"]}})
    else:
        await db.shifts.update_one({"shift_id": shift_id}, {"$set": {"swap.status": "rejected", "swap.decided_by": user.get("name") or ""}})
    msg = f"{label(s)}: swap {'approved' if body.approve else 'not approved'} by {user.get('name') or 'Rosters'}."
    await notify([s["worker_id"], sw["to_id"]], "shift", f"Shift swap {'approved' if body.approve else 'not approved'}", msg, "/pm/rostering")
    return {"approved": body.approve}


# ---- Open shift board ----

@router.post("/shifts/{shift_id}/open")
async def post_open(shift_id: str, user=Depends(rosters_user)):
    s = await db.shifts.find_one({"shift_id": shift_id, "status": "declined"}, P)
    if not s or s.get("rerostered"):
        raise HTTPException(400, "Only declined shifts that haven't been re-rostered can go on the open board")
    if span(s)[0] <= now_perth():
        raise HTTPException(400, "This shift has already started")
    await db.shifts.update_one({"shift_id": shift_id}, {"$set": {"open": True, "opened_at": now_iso()}})
    p = await db.participants.find_one({"participant_id": s["participant_id"]}, P) or {}
    team = [i for i in p.get("assigned_ids", []) if i != s["worker_id"]]
    await notify(team, "shift", f"Open shift: {label(s)}", "Tap to claim it in Rostering. First in gets it.", "/pm/rostering")
    return {"open": True, "notified": len(team)}


@router.post("/shifts/{shift_id}/claim")
async def claim_shift(shift_id: str, user=Depends(current_user)):
    s = await db.shifts.find_one_and_update({"shift_id": shift_id, "open": True, "status": "declined", "rerostered": {"$in": [None, ""]}},
                                            {"$set": {"open": False}})
    if not s:
        raise HTTPException(400, "Someone has already claimed this shift")
    try:
        new = await create_shift(ShiftIn(participant_id=s["participant_id"], funding_id=s["funding_id"], worker_id=user["user_id"],
                                         date=dmy(s["date"]), start=s["start"], end=s["end"], notes=s.get("notes") or "",
                                         replaces=shift_id), user)
    except HTTPException:
        await db.shifts.update_one({"shift_id": shift_id}, {"$set": {"open": True}})
        raise
    await db.shifts.update_one({"shift_id": new["shift_id"]}, {"$set": {"status": "accepted", "claimed": True, "created_by": user.get("name") or ""}})
    await notify(await rosters_ids(), "shift", f"Open shift claimed: {label(s)}", f"{user['name']} has taken it.", "/pm/rostering")
    return {"shift_id": new["shift_id"], "status": "accepted"}


# ---- Shift reminders (1 hour before) ----

async def shift_reminders():
    now = now_perth()
    today = now.date().isoformat()
    tomorrow = (now.date() + timedelta(days=1)).isoformat()
    async for s in db.shifts.find({"status": {"$in": ["accepted", "pending_acceptance"]}, "reminded": {"$ne": True},
                                   "date": {"$in": [today, tomorrow]}}, P):
        mins = (span(s)[0] - now).total_seconds() / 60
        if 0 < mins <= 65:
            p = await db.participants.find_one({"participant_id": s["participant_id"]}, P) or {}
            goals = ((p.get("profile") or {}).get("goals") or "").strip()
            body = f"Starts at {s['start']}." + (f" Goals: {goals[:220]}{'…' if len(goals) > 220 else ''}" if goals else " Open the shift to see their Support Plan.")
            await notify([s["worker_id"]], "shift", f"Shift in 1 hour: {s['participant_name']}", body, "/pm/rostering")
            await db.shifts.update_one({"shift_id": s["shift_id"]}, {"$set": {"reminded": True}})


# ---- Budget forecast PDF (Finance) ----

def money(n: float) -> str:
    return f"${n:,.2f}"


def forecast_pdf(funds: list, month_label: str) -> bytes:
    import pymupdf
    rows = "".join(
        f"<tr><td>{escape(f['participant_name'])}</td><td>{escape(f['management_type'])}</td><td>{dmy(f['start_date'])} – {dmy(f['end_date'])}</td>"
        f"<td style='text-align:right'>{money(f['budget'])}</td><td style='text-align:right'>{money(f['spent'])}</td>"
        f"<td style='text-align:right'>{money(f['committed'])}</td><td style='text-align:right'>{money(f['remaining'])}</td>"
        f"<td style='text-align:center;color:{'#B42318' if f['alert']['low'] else '#11181C'}'>{f['alert']['pct_left']}%</td>"
        f"<td style='color:#B42318'>{dmy(f['alert']['runout']) if f['alert']['runout'] else 'On track'}</td></tr>" for f in funds)
    tot = lambda k: money(sum(f[k] for f in funds))  # noqa: E731
    html = (f"<h2 style='color:#f7a51d;margin:0'>Budget forecast: {escape(month_label)}</h2>"
            f"<p style='font-size:9px;color:#555'>Current funding lines · generated {dmy(now_perth().date().isoformat())} (Perth time)</p>"
            f"<p style='font-size:11px'><b>Total budget {tot('budget')} · spent {tot('spent')} · booked {tot('committed')} · remaining {tot('remaining')}</b></p>"
            f"<table style='width:100%;border-collapse:collapse;font-size:7.5px' border='1' cellpadding='3'>"
            f"<tr style='background:#FFF3DF'><th>Participant</th><th>Type</th><th>Service period</th><th>Budget</th><th>Spent</th>"
            f"<th>Booked</th><th>Remaining</th><th>Left</th><th>Projected run-out</th></tr>{rows or '<tr><td colspan=9>No current funding</td></tr>'}</table>"
            f"<p style='font-size:7.5px;color:#777'>Spent = completed shifts at approved times. Booked = upcoming rostered shifts. Run-out is projected "
            f"from the spending rate so far (after 7 days). Confidential: No Limitts Pty Ltd.</p>")
    buf = io.BytesIO()
    writer = pymupdf.DocumentWriter(buf)
    story = pymupdf.Story(html=html)
    page, more, first = pymupdf.paper_rect("a4-l"), True, True
    while more:
        dev = writer.begin_page(page)
        more, _ = story.place(page + (30, FIRST_TOP if first else 30, -30, -30))
        story.draw(dev)
        writer.end_page()
        first = False
    writer.close()
    return add_logo(buf.getvalue())


async def forecast_response() -> Response:
    funds = await db.fundings.find({"end_date": {"$gte": now_perth().date().isoformat()}}, P).sort("participant_name", 1).to_list(5000)
    use = await funding_usage([f["funding_id"] for f in funds])
    out = [funding_out(f, use[f["funding_id"]]) for f in funds]
    pdf = await run_in_threadpool(forecast_pdf, out, now_perth().strftime("%B %Y"))
    return Response(content=pdf, media_type="application/pdf", headers={"Content-Disposition": 'inline; filename="Budget_forecast.pdf"'})


@router.get("/funding/forecast/pdf")
async def forecast(request: Request, token: Optional[str] = None):
    if not is_finance(await token_user(request, token)):
        raise HTTPException(403, "For Finance users")
    return await forecast_response()


@router.get("/funding/forecast/shared/{token}")
async def forecast_shared(token: str):
    link = await db.forecast_links.find_one({"token": token}, P)
    if not link or link["expires_at"] < datetime.now(timezone.utc).isoformat():
        raise HTTPException(404, "This link has expired. Open the forecast from Funding in the app instead.")
    return await forecast_response()


async def email_forecasts():
    month = now_perth().strftime("%B %Y")
    base = (os.environ.get("PUBLIC_BACKEND_URL") or "").rstrip("/")
    async for u in db.users.find({"$or": [{"permissions": "finance"}, {"role": "admin"}], "hidden": {"$ne": True}, "email": {"$nin": [None, ""]}}, P):
        token = secrets.token_urlsafe(24)
        await db.forecast_links.insert_one({"token": token, "user_id": u["user_id"], "created_at": now_iso(),
                                            "expires_at": (datetime.now(timezone.utc) + timedelta(days=30)).isoformat()})
        html = (f'<p>Hi {escape((u.get("name") or "there").split(" ")[0])},</p><p>Here is the No Limitts budget forecast for <b>{month}</b>: '
                f'each participant\'s spend, remaining funds and projected run-out date.</p>'
                f'<p><a href="{base}/api/funding/forecast/shared/{token}" style="background:#f7a51d;color:#fff;padding:12px 20px;'
                f'border-radius:10px;text-decoration:none;font-weight:bold">Open the forecast (PDF)</a></p>'
                f'<p style="font-size:13px;color:#555">Private link, valid for 30 days. Please don\'t forward it.</p>')
        try:
            await send_email(to=u["email"], subject=f"Budget forecast: {month}", html=html)
        except Exception as e:
            logger.error(f"Forecast email to {u.get('user_id')} failed: {e}")


async def shift_market_loop():
    await asyncio.sleep(90)
    while True:
        try:
            await shift_reminders()
            local = now_perth()
            key = f"budget_forecast_{local.strftime('%Y-%m')}"
            if local.day == 1 and local.hour >= 8 and not await db.meta.find_one({"key": key}):
                await db.meta.insert_one({"key": key, "created_at": now_iso()})
                await email_forecasts()
        except Exception as e:
            logger.error(f"Shift market loop failed: {type(e).__name__}: {e}")
        await asyncio.sleep(300)
