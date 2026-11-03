"""Caseload extras: shift handover photos, participant birthdays and the monthly case note completion report."""
import asyncio
import os
import re
import secrets
import uuid
from calendar import monthrange
from datetime import date, datetime, timedelta, timezone
from html import escape
from typing import Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import Response

from core import DIGEST_TZ, MAX_UPLOAD_BYTES, bearer, current_user, db, dmy, logger, notify, now_iso, user_from_token
from email_service import send_email
from pdf_brand import FIRST_TOP, add_logo
from routes.caseload import can_manage, check_access, configured, is_worker, load_rows, note_day, participant_key
from storage import APP_NAME, get_object, put_object

router = APIRouter(prefix="/api")


# ---- Handover photos ----

async def can_see_participant(user: dict, key: str) -> dict:
    """Assigned Support Workers, plus Coordinators, HR and Admins."""
    p = await db.participants.find_one({"key": key}, {"_id": 0})
    if is_worker(user):
        if not p or user["user_id"] not in p.get("assigned_ids", []):
            raise HTTPException(403, "You're not assigned to this participant")
    else:
        check_access(user)
    return p or {}


def photo_out(ph: dict) -> dict:
    return {k: ph[k] for k in ("photo_id", "caption", "by_name", "by_id", "at")}


async def handover_photos(submission_ids: list) -> dict:
    out: dict = {}
    if submission_ids:
        async for ph in db.handover_photos.find({"submission_id": {"$in": submission_ids}}, {"_id": 0}).sort("at", 1):
            out.setdefault(ph["submission_id"], []).append(photo_out(ph))
    return out


@router.post("/caseload/handover/photos")
async def add_handover_photo(participant: str = Form(...), submission_id: str = Form(...), caption: str = Form(""),
                             file: UploadFile = File(...), user=Depends(current_user)):
    key = participant_key(participant)
    p = await can_see_participant(user, key)
    if not configured() or not any(r["id"] == submission_id and participant_key(r["participant"]) == key
                                   and "handover" in (r.get("source") or "").lower() for r in await load_rows()):
        raise HTTPException(400, "That shift handover wasn't found for this participant")
    if await db.handover_photos.count_documents({"submission_id": submission_id}) >= 10:
        raise HTTPException(400, "A handover can have up to 10 photos")
    ctype = file.content_type or ""
    if not ctype.startswith("image/"):
        raise HTTPException(400, "Choose a photo")
    data = await file.read()
    if not data:
        raise HTTPException(400, "Empty file")
    if len(data) > MAX_UPLOAD_BYTES:
        raise HTTPException(413, "Photo too large (max 15 MB)")
    ext = {"image/png": "png", "image/webp": "webp", "image/heic": "heic"}.get(ctype, "jpg")
    try:
        res = await run_in_threadpool(put_object, f"{APP_NAME}/handovers/{uuid.uuid4().hex}.{ext}", data, ctype)
    except Exception as e:
        logger.error(f"handover photo upload failed: {e}")
        raise HTTPException(502, "Couldn't save the photo, please try again")
    ph = {"photo_id": f"hph_{secrets.token_hex(6)}", "submission_id": submission_id, "participant": key,
          "caption": caption.strip()[:200], "storage_path": res["path"], "content_type": ctype,
          "by_id": user["user_id"], "by_name": user.get("name") or "", "at": now_iso()}
    await db.handover_photos.insert_one(dict(ph))
    others = [i for i in p.get("assigned_ids", []) if i != user["user_id"]]
    if others:
        await notify(others, "handover", f"Handover photo added: {p.get('name') or participant}",
                     f"{user.get('name') or 'A team member'} added a photo to the latest shift handover.", "/caseload")
    return photo_out(ph)


@router.get("/caseload/handover/photos/{photo_id}")
async def handover_photo_file(photo_id: str, request: Request, token: Optional[str] = None):
    user = await user_from_token(bearer(request) or token)
    if not user:
        raise HTTPException(401, "Please sign in again")
    ph = await db.handover_photos.find_one({"photo_id": photo_id}, {"_id": 0})
    if not ph:
        raise HTTPException(404, "Photo not found")
    await can_see_participant(user, ph["participant"])
    data, ctype = await run_in_threadpool(get_object, ph["storage_path"])
    return Response(content=data, media_type=ph.get("content_type") or ctype, headers={"Cache-Control": "private, max-age=3600"})


@router.delete("/caseload/handover/photos/{photo_id}")
async def delete_handover_photo(photo_id: str, user=Depends(current_user)):
    ph = await db.handover_photos.find_one({"photo_id": photo_id}, {"_id": 0})
    if not ph:
        raise HTTPException(404, "Photo not found")
    if ph["by_id"] != user["user_id"] and not can_manage(user):
        raise HTTPException(403, "Only the person who added it or a Coordinator can remove this photo")
    await db.handover_photos.delete_one({"photo_id": photo_id})
    return {"ok": True}


# ---- Participant birthdays ----

def next_birthday(dob: str, today: date) -> Optional[dict]:
    """Days until the next birthday (0 = today) and the age they turn. 29 Feb birthdays fall on 28 Feb in other years."""
    try:
        b = date.fromisoformat(dob)
    except (TypeError, ValueError):
        return None

    def on(year: int) -> date:
        return date(year, b.month, min(b.day, monthrange(year, b.month)[1]))
    nxt = on(today.year)
    if nxt < today:
        nxt = on(today.year + 1)
    return {"in_days": (nxt - today).days, "turns": nxt.year - b.year, "date": nxt.isoformat()}


def perth_today() -> date:
    return datetime.now(DIGEST_TZ).date()


async def birthday_reminders():
    today = perth_today()
    async for p in db.participants.find({"assigned_ids": {"$ne": []}, "profile.date_of_birth": {"$nin": [None, ""]}}, {"_id": 0}):
        nb = next_birthday(p["profile"]["date_of_birth"], today)
        if nb and nb["in_days"] == 0:
            await notify(p["assigned_ids"], "birthday", f"It's {p['name']}'s birthday today! 🎂",
                         f"{p['name']} turns {nb['turns']} today. Don't forget to wish them a happy birthday on your shift.",
                         f"/participant/{p['participant_id']}")


# ---- Monthly case note completion report ----

def prev_month(today: date) -> str:
    first = today.replace(day=1) - timedelta(days=1)
    return first.strftime("%Y-%m")


def month_days(month: str) -> list:
    y, m = (int(x) for x in month.split("-"))
    last = min(date(y, m, monthrange(y, m)[1]), perth_today() - timedelta(days=1))
    d, out = date(y, m, 1), []
    while d <= last:
        out.append(d.isoformat())
        d += timedelta(days=1)
    return out


async def coordinator_participants(user: dict) -> list:
    """A coordinator's own participants (they're in the assigned list); everyone if they have none."""
    mine = await db.participants.find({"assigned_ids": user["user_id"]}, {"_id": 0}).sort("name", 1).to_list(2000)
    return mine or await db.participants.find({}, {"_id": 0}).sort("name", 1).to_list(2000)


async def monthly_report(user: dict, month: str) -> dict:
    days = month_days(month)
    rows = await load_rows() if configured() else []
    have: dict = {}
    for r in rows:
        if r["kind"] == "day":
            have.setdefault(participant_key(r["participant"]), []).append(note_day(r))
    people = await coordinator_participants(user)
    ids = {i for p in people for i in p.get("assigned_ids", [])}
    names = {u["user_id"]: u["name"] async for u in db.users.find({"user_id": {"$in": list(ids)}, "user_type": "support_worker"},
                                                                  {"_id": 0, "user_id": 1, "name": 1})}
    out = []
    for p in people:
        created = p.get("created_at") or ""
        since = datetime.fromisoformat(created).astimezone(DIGEST_TZ).date().isoformat() if "T" in created else created[:10]
        window = [d for d in days if d >= since]
        noted = [d for d in have.get(p["key"], []) if d in window]
        done = len(set(noted))
        out.append({"name": p["name"], "days": len(window), "done": done, "notes": len(noted),
                    "pct": round(done * 100 / len(window)) if window else None,
                    "workers": [names[i] for i in p.get("assigned_ids", []) if i in names]})
    tracked = [x for x in out if x["days"]]
    total_days = sum(x["days"] for x in tracked)
    overall = round(sum(x["done"] for x in tracked) * 100 / total_days) if total_days else None
    return {"month": month, "participants": out, "overall": overall, "own": bool(await db.participants.count_documents({"assigned_ids": user["user_id"]}))}


def month_label(month: str) -> str:
    y, m = (int(x) for x in month.split("-"))
    return date(y, m, 1).strftime("%B %Y")


def build_report_pdf(rep: dict, for_name: str) -> bytes:
    import io
    import pymupdf

    def colour(pct):
        return "#1E7D3A" if pct is not None and pct >= 90 else "#B26A00" if pct is not None and pct >= 70 else "#B42318"
    rows = "".join(
        f"<tr><td>{escape(p['name'])}</td><td>{escape(', '.join(p['workers']) or '-')}</td>"
        f"<td style='text-align:center'>{p['done']} / {p['days']}</td><td style='text-align:center'>{p['notes']}</td>"
        f"<td style='text-align:center;color:{colour(p['pct'])};font-weight:bold'>{'-' if p['pct'] is None else str(p['pct']) + '%'}</td></tr>"
        for p in sorted(rep["participants"], key=lambda x: (x["pct"] if x["pct"] is not None else 101, x["name"])))
    scope = "your participants" if rep["own"] else "all participants"
    html = (f"<h2 style='color:#673E8D;margin:0'>Case note completion: {month_label(rep['month'])}</h2>"
            f"<p style='font-size:9px;color:#555'>Prepared for {escape(for_name)} · {scope} · Generated {dmy(perth_today().isoformat())} (Perth time)</p>"
            f"<p style='font-size:11px'><b>Overall completion: {'-' if rep['overall'] is None else str(rep['overall']) + '%'}</b> "
            f"of days had at least one Support Worker case note.</p>"
            f"<table style='width:100%;border-collapse:collapse;font-size:8.5px' border='1' cellpadding='3'>"
            f"<tr style='background:#EFE8F5'><th>Participant</th><th>Support Workers</th><th>Days with a note</th>"
            f"<th>Notes</th><th>Completion</th></tr>{rows or '<tr><td colspan=5>No participants</td></tr>'}</table>"
            f"<p style='font-size:8px;color:#777'>Counts Day-to-Day Support Worker case notes from Jotform. Days before a participant "
            f"was added aren't counted. Confidential: contains participant information. No Limitts Pty Ltd.</p>")
    buf = io.BytesIO()
    writer = pymupdf.DocumentWriter(buf)
    story = pymupdf.Story(html=html)
    page, more, first = pymupdf.paper_rect("a4"), True, True
    while more:
        dev = writer.begin_page(page)
        more, _ = story.place(page + (36, FIRST_TOP if first else 36, -36, -36))
        story.draw(dev)
        writer.end_page()
        first = False
    writer.close()
    return add_logo(buf.getvalue())


def valid_month(month: Optional[str]) -> str:
    if not month:
        return prev_month(perth_today())
    if not re.fullmatch(r"\d{4}-(0[1-9]|1[0-2])", month) or month > perth_today().strftime("%Y-%m"):
        raise HTTPException(400, "Choose a month like 2026-05")
    return month


async def pdf_response(user: dict, month: str) -> Response:
    rep = await monthly_report(user, month)
    pdf = await run_in_threadpool(build_report_pdf, rep, user.get("name") or "")
    return Response(content=pdf, media_type="application/pdf",
                    headers={"Content-Disposition": f'inline; filename="Case_note_completion_{month}.pdf"'})


@router.get("/caseload/monthly-report/pdf")
async def monthly_report_pdf(request: Request, month: Optional[str] = None, token: Optional[str] = None):
    user = await user_from_token(bearer(request) or token)
    if not user or not can_manage(user):
        raise HTTPException(403, "The monthly report is for Service & Support Coordinators and Admins")
    return await pdf_response(user, valid_month(month))


@router.get("/caseload/monthly-report/shared/{token}")
async def monthly_report_shared(token: str):
    share = await db.monthly_report_links.find_one({"token": token}, {"_id": 0})
    if not share or share["expires_at"] < datetime.now(timezone.utc).isoformat():
        raise HTTPException(404, "This link has expired. Open the report from the Caseload screen in the app instead.")
    user = await db.users.find_one({"user_id": share["user_id"]}, {"_id": 0})
    if not user or not can_manage(user):
        raise HTTPException(404, "This report is no longer available")
    return await pdf_response(user, share["month"])


async def email_report(user: dict, month: str) -> bool:
    rep = await monthly_report(user, month)
    token = secrets.token_urlsafe(24)
    await db.monthly_report_links.insert_one({"token": token, "user_id": user["user_id"], "month": month, "created_at": now_iso(),
                                              "expires_at": (datetime.now(timezone.utc) + timedelta(days=30)).isoformat()})
    link = f"{(os.environ.get('PUBLIC_BACKEND_URL') or '').rstrip('/')}/api/caseload/monthly-report/shared/{token}"
    low = [p for p in rep["participants"] if p["pct"] is not None and p["pct"] < 70]
    html = (f'<table role="presentation" width="100%"><tr><td style="padding:24px;font-family:Arial,sans-serif;color:#11181C">'
            f'<p>Hi {escape((user.get("name") or "there").split(" ")[0])},</p>'
            f'<p>Here is the case note completion report for <strong>{month_label(month)}</strong>'
            f'{"" if rep["own"] else " (all participants)"}.</p>'
            f'<p><strong>Overall: {"-" if rep["overall"] is None else str(rep["overall"]) + "%"}</strong> of days had a Support Worker case note'
            f'{f" · {len(low)} participant" + ("s" if len(low) != 1 else "") + " under 70%" if low else ""}.</p>'
            f'<p><a href="{escape(link)}" style="display:inline-block;background:#673E8D;color:#ffffff;padding:12px 20px;'
            f'border-radius:10px;text-decoration:none;font-weight:bold">Open the report (PDF)</a></p>'
            f'<p style="font-size:13px;color:#555">This private link works for 30 days. It contains participant information, '
            f'so please don\'t forward it.</p></td></tr></table>')
    return await send_email(to=user["email"], subject=f"Case note completion: {month_label(month)}", html=html)


@router.post("/caseload/monthly-report/email")
async def email_report_now(month: Optional[str] = None, user=Depends(current_user)):
    if not can_manage(user):
        raise HTTPException(403, "The monthly report is for Service & Support Coordinators and Admins")
    if not user.get("email"):
        raise HTTPException(400, "There's no email address on your profile")
    m = valid_month(month)
    if not await email_report(user, m):
        raise HTTPException(502, "Couldn't send the email right now. Please try again.")
    return {"sent_to": user["email"], "month": m}


async def send_monthly_reports(month: str):
    async for u in db.users.find({"user_type": "support_coordinator", "hidden": {"$ne": True}, "email": {"$nin": [None, ""]}}, {"_id": 0}):
        try:
            await email_report(u, month)
        except Exception as e:
            logger.error(f"Monthly report for {u.get('user_id')} failed: {type(e).__name__}: {e}")


async def caseload_extras_loop():
    """Daily participant birthday alerts (8am Perth) and the monthly report on the 1st."""
    await asyncio.sleep(120)
    while True:
        try:
            local = datetime.now(DIGEST_TZ)
            if local.hour >= 8:
                key = f"participant_birthdays_{local.date().isoformat()}"
                if not await db.meta.find_one({"key": key}):
                    await db.meta.insert_one({"key": key, "created_at": now_iso()})
                    await birthday_reminders()
                mk = f"monthly_report_{prev_month(local.date())}"
                if local.day == 1 and configured() and not await db.meta.find_one({"key": mk}):
                    await db.meta.insert_one({"key": mk, "created_at": now_iso()})
                    await send_monthly_reports(prev_month(local.date()))
        except Exception as e:
            logger.error(f"Caseload extras loop failed: {type(e).__name__}: {e}")
        await asyncio.sleep(600)
