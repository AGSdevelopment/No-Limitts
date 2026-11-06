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
from pydantic import BaseModel

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


class CaptionIn(BaseModel):
    caption: str = ""


@router.patch("/caseload/handover/photos/{photo_id}")
async def edit_handover_caption(photo_id: str, body: CaptionIn, user=Depends(current_user)):
    ph = await db.handover_photos.find_one({"photo_id": photo_id}, {"_id": 0})
    if not ph:
        raise HTTPException(404, "Photo not found")
    if ph["by_id"] != user["user_id"] and not can_manage(user):
        raise HTTPException(403, "Only the person who added it or a Coordinator can edit this caption")
    cap = body.caption.strip()[:200]
    await db.handover_photos.update_one({"photo_id": photo_id}, {"$set": {"caption": cap}})
    return {**photo_out(ph), "caption": cap}


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


# ---- Birthday card wall: open from 7 days before to 7 days after the birthday ----

WALL_DAYS = 7


async def wall_participant(participant_id: str, user: dict) -> dict:
    p = await db.participants.find_one({"participant_id": participant_id}, {"_id": 0})
    if not p:
        raise HTTPException(404, "Participant not found")
    await can_see_participant(user, p["key"])
    return p


def wall_window(p: dict) -> Optional[dict]:
    """The birthday the wall is for, if it's within the open window."""
    today = perth_today()
    nb = next_birthday((p.get("profile") or {}).get("date_of_birth"), today - timedelta(days=WALL_DAYS))
    if not nb or date.fromisoformat(nb["date"]) > today + timedelta(days=WALL_DAYS):
        return None
    return {**nb, "in_days": (date.fromisoformat(nb["date"]) - today).days}


def message_out(m: dict, user: dict) -> dict:
    return {"message_id": m["message_id"], "name": m["name"], "text": m["text"], "at": m["at"],
            "mine": m["user_id"] == user["user_id"], "can_remove": m["user_id"] == user["user_id"] or can_manage(user)}


@router.get("/participants/{participant_id}/birthday-wall")
async def birthday_wall(participant_id: str, user=Depends(current_user)):
    p = await wall_participant(participant_id, user)
    win = wall_window(p)
    if not win:
        return {"open": False, "messages": []}
    msgs = await db.birthday_messages.find({"participant_id": participant_id, "date": win["date"]}, {"_id": 0}).sort("at", 1).to_list(500)
    return {"open": True, "birthday": win, "messages": [message_out(m, user) for m in msgs]}


class WallIn(BaseModel):
    text: str


@router.post("/participants/{participant_id}/birthday-wall")
async def sign_birthday_wall(participant_id: str, body: WallIn, user=Depends(current_user)):
    """Sign (or update your message on) the participant's birthday card. One message per person per birthday."""
    p = await wall_participant(participant_id, user)
    win = wall_window(p)
    if not win:
        raise HTTPException(400, "The birthday card opens 7 days before their birthday")
    text = body.text.strip()
    if not text:
        raise HTTPException(400, "Write a message first")
    if len(text) > 300:
        raise HTTPException(400, "Keep it under 300 characters")
    q = {"participant_id": participant_id, "date": win["date"], "user_id": user["user_id"]}
    existing = await db.birthday_messages.find_one(q, {"_id": 0})
    doc = {**q, "message_id": (existing or {}).get("message_id") or f"bdm_{secrets.token_hex(6)}",
           "name": user.get("name") or "", "text": text, "at": now_iso()}
    await db.birthday_messages.update_one(q, {"$set": doc}, upsert=True)
    return message_out(doc, user)


@router.delete("/participants/{participant_id}/birthday-wall/{message_id}")
async def remove_birthday_message(participant_id: str, message_id: str, user=Depends(current_user)):
    await wall_participant(participant_id, user)
    m = await db.birthday_messages.find_one({"participant_id": participant_id, "message_id": message_id}, {"_id": 0})
    if not m:
        raise HTTPException(404, "Message not found")
    if m["user_id"] != user["user_id"] and not can_manage(user):
        raise HTTPException(403, "You can only remove your own message")
    await db.birthday_messages.delete_one({"message_id": message_id})
    return {"ok": True}


async def birthday_reminders():
    today = perth_today()
    async for p in db.participants.find({"assigned_ids": {"$ne": []}, "profile.date_of_birth": {"$nin": [None, ""]}}, {"_id": 0}):
        nb = next_birthday(p["profile"]["date_of_birth"], today)
        if nb and nb["in_days"] == 0:
            await notify(p["assigned_ids"], "birthday", f"It's {p['name']}'s birthday today! 🎂",
                         f"{p['name']} turns {nb['turns']} today. Sign their birthday card in the app and wish them a happy birthday on your shift.",
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
    first: dict = {}
    for r in rows:
        k = participant_key(r["participant"])
        if r["kind"] == "day":
            have.setdefault(k, []).append(note_day(r))
        d = note_day(r)
        if k and (k not in first or d < first[k][0]):
            first[k] = (d, r["participant"])
    people = await coordinator_participants(user)
    own = bool(await db.participants.count_documents({"assigned_ids": user["user_id"]}))
    if not own:  # everyone: include participants who only appear in Jotform case notes
        known = {p["key"] for p in people}
        people += sorted(({"key": k, "name": n, "created_at": d, "assigned_ids": [], "jotform_only": True}
                          for k, (d, n) in first.items() if k not in known), key=lambda p: p["name"].lower())
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
        out.append({"name": p["name"], "days": len(window), "done": done, "notes": len(noted), "jotform_only": p.get("jotform_only", False),
                    "pct": round(done * 100 / len(window)) if window else None,
                    "workers": [names[i] for i in p.get("assigned_ids", []) if i in names]})
    tracked = [x for x in out if x["days"]]
    total_days = sum(x["days"] for x in tracked)
    overall = round(sum(x["done"] for x in tracked) * 100 / total_days) if total_days else None
    return {"month": month, "participants": out, "overall": overall, "own": own}


def month_label(month: str) -> str:
    y, m = (int(x) for x in month.split("-"))
    return date(y, m, 1).strftime("%B %Y")


def build_report_pdf(rep: dict, for_name: str) -> bytes:
    import io
    import pymupdf

    def colour(pct):
        return "#1E7D3A" if pct is not None and pct >= 90 else "#B26A00" if pct is not None and pct >= 70 else "#B42318"
    rows = "".join(
        f"<tr><td>{escape(p['name'])}{' *' if p.get('jotform_only') else ''}</td><td>{escape(', '.join(p['workers']) or '-')}</td>"
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
            f"was added (or, for * participants not yet set up in the app, before their first Jotform case note) aren't counted. "
            f"Confidential: contains participant information. No Limitts Pty Ltd.</p>")
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
        raise HTTPException(503, "Couldn't send the email right now. Please try again in a minute.")
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


# ---- Printable birthday card ----

def build_card_pdf(first: str, turns: int, messages: list) -> bytes:
    import io
    import pymupdf
    notes = "".join(
        f"<div style='margin:0 0 10px 0;padding:10px;background:#FFF4DE;border-radius:8px'>"
        f"<p style='margin:0;font-size:12px;color:#11181C'>{escape(m['text'])}</p>"
        f"<p style='margin:4px 0 0 0;font-size:10px;color:#673E8D;font-weight:bold'>{escape(m['name'])}</p></div>"
        for m in messages)
    html = (f"<div style='text-align:center'>"
            f"<h1 style='color:#f7a51d;font-size:34px;margin:6px 0'>Happy Birthday, {escape(first)}!</h1>"
            f"<p style='font-size:14px;color:#673E8D;margin:0 0 18px 0'>Wishing you a wonderful {turns}{ordinal(turns)} birthday</p></div>"
            f"{notes}"
            f"<p style='text-align:center;font-size:11px;color:#673E8D;margin-top:14px'>With love from everyone at No Limitts</p>")
    buf = io.BytesIO()
    writer = pymupdf.DocumentWriter(buf)
    story = pymupdf.Story(html=html)
    page, more, first_page = pymupdf.paper_rect("a4"), True, True
    while more:
        dev = writer.begin_page(page)
        more, _ = story.place(page + (48, FIRST_TOP if first_page else 48, -48, -48))
        story.draw(dev)
        writer.end_page()
        first_page = False
    writer.close()
    return add_logo(buf.getvalue())


def ordinal(n: int) -> str:
    return "th" if 10 <= n % 100 <= 20 else {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")


@router.get("/participants/{participant_id}/birthday-wall/pdf")
async def birthday_card_pdf(participant_id: str, request: Request, token: Optional[str] = None):
    user = await user_from_token(bearer(request) or token)
    if not user:
        raise HTTPException(401, "Please sign in again")
    p = await wall_participant(participant_id, user)
    win = wall_window(p)
    if not win:
        raise HTTPException(400, "The birthday card opens 7 days before their birthday")
    msgs = await db.birthday_messages.find({"participant_id": participant_id, "date": win["date"]}, {"_id": 0}).sort("at", 1).to_list(500)
    pdf = await run_in_threadpool(build_card_pdf, p["name"].split(" ")[0], win["turns"], msgs)
    fname = re.sub(r"[^A-Za-z0-9]+", "_", p["name"]).strip("_")
    return Response(content=pdf, media_type="application/pdf",
                    headers={"Content-Disposition": f'inline; filename="Birthday_card_{fname}.pdf"'})


# ---- Handover photo timeline (Coordinators, HR and Admins) ----

def iso_or_400(v: Optional[str], label: str) -> Optional[str]:
    if not v:
        return None
    try:
        return date.fromisoformat(v).isoformat()
    except ValueError:
        raise HTTPException(400, f"Choose a valid {label} date")


@router.get("/participants/{participant_id}/handover-photos")
async def handover_photo_timeline(participant_id: str, worker: Optional[str] = None, date_from: Optional[str] = None,
                                  date_to: Optional[str] = None, user=Depends(current_user)):
    check_access(user)
    p = await db.participants.find_one({"participant_id": participant_id}, {"_id": 0})
    if not p:
        raise HTTPException(404, "Participant not found")
    lo, hi = iso_or_400(date_from, "start"), iso_or_400(date_to, "end")
    if lo and hi and lo > hi:
        raise HTTPException(400, "The start date must be before the end date")
    every = await db.handover_photos.find({"participant": p["key"]}, {"_id": 0}).sort("at", -1).to_list(2000)
    workers = sorted({ph["by_id"]: ph["by_name"] for ph in every}.items(), key=lambda w: w[1].lower())

    def local_day(ph):
        return datetime.fromisoformat(ph["at"]).astimezone(DIGEST_TZ).date().isoformat()
    photos = [ph for ph in every if (not worker or ph["by_id"] == worker)
              and (not lo or local_day(ph) >= lo) and (not hi or local_day(ph) <= hi)]
    rows = {r["id"]: r for r in (await load_rows() if configured() else []) if r["id"]}
    groups: dict = {}
    for ph in photos:
        g = groups.setdefault(ph["submission_id"], {"submission_id": ph["submission_id"], "photos": []})
        g["photos"].append(photo_out(ph))
    out = []
    for sid, g in groups.items():
        r = rows.get(sid) or {}
        out.append({**g, "date": r.get("date") or g["photos"][-1]["at"][:10], "author": r.get("email") or "",
                    "source": r.get("source") or "Shift handover"})
    out.sort(key=lambda g: (g["date"], g["photos"][0]["at"]), reverse=True)
    return {"name": p["name"], "total": len(photos), "all_total": len(every), "handovers": out,
            "workers": [{"user_id": i, "name": n} for i, n in workers]}


# ---- Email the birthday card to a family contact (Coordinators and Admins) ----

class CardEmailIn(BaseModel):
    email: str


@router.post("/participants/{participant_id}/birthday-wall/email")
async def email_birthday_card(participant_id: str, body: CardEmailIn, user=Depends(current_user)):
    if not can_manage(user):
        raise HTTPException(403, "Only Coordinators and Admins can email the birthday card")
    p = await wall_participant(participant_id, user)
    win = wall_window(p)
    if not win:
        raise HTTPException(400, "The birthday card opens 7 days before their birthday")
    to = body.email.strip().lower()
    contact = next((c for c in (p.get("profile") or {}).get("contacts", []) if (c.get("email") or "").strip().lower() == to and to), None)
    if not contact:
        raise HTTPException(400, "Choose one of the participant's key contacts with an email address")
    if not await db.birthday_messages.count_documents({"participant_id": participant_id, "date": win["date"]}):
        raise HTTPException(400, "Nobody has signed the card yet")
    token = secrets.token_urlsafe(24)
    await db.birthday_card_links.insert_one({"token": token, "participant_id": participant_id, "date": win["date"], "turns": win["turns"],
                                             "sent_to": to, "by_id": user["user_id"], "created_at": now_iso(),
                                             "expires_at": (datetime.now(timezone.utc) + timedelta(days=30)).isoformat()})
    first = p["name"].split(" ")[0]
    link = f"{(os.environ.get('PUBLIC_BACKEND_URL') or '').rstrip('/')}/api/birthday-card/shared/{token}"
    html = (f'<table role="presentation" width="100%"><tr><td style="padding:24px;font-family:Arial,sans-serif;color:#11181C">'
            f'<p>Hi {escape((contact.get("name") or "there").split(" ")[0])},</p>'
            f'<p>The No Limitts team has signed a birthday card for <strong>{escape(first)}</strong> 🎂 and we wanted to share it with you.</p>'
            f'<p><a href="{escape(link)}" style="display:inline-block;background:#f7a51d;color:#ffffff;padding:12px 20px;'
            f'border-radius:10px;text-decoration:none;font-weight:bold">Open {escape(first)}&#39;s birthday card</a></p>'
            f'<p style="font-size:13px;color:#555">You can print it out or show it to {escape(first)} on screen. The link works for 30 days.</p>'
            f'<p>Warm wishes,<br>{escape(user.get("name") or "The No Limitts team")}<br>No Limitts</p></td></tr></table>')
    if not await send_email(to=to, subject=f"A birthday card for {first} from the No Limitts team", html=html):
        await db.birthday_card_links.delete_one({"token": token})
        raise HTTPException(503, "Couldn't send the email right now. Please try again in a minute.")
    await db.birthday_card_links.update_one({"token": token}, {"$set": {"sent": True}})
    return {"sent_to": to, "name": contact.get("name") or ""}


@router.get("/birthday-card/shared/{token}")
async def shared_birthday_card(token: str):
    link = await db.birthday_card_links.find_one({"token": token}, {"_id": 0})
    if not link or link["expires_at"] < datetime.now(timezone.utc).isoformat():
        raise HTTPException(404, "This birthday card link has expired")
    p = await db.participants.find_one({"participant_id": link["participant_id"]}, {"_id": 0, "name": 1})
    if not p:
        raise HTTPException(404, "This birthday card is no longer available")
    msgs = await db.birthday_messages.find({"participant_id": link["participant_id"], "date": link["date"]}, {"_id": 0}).sort("at", 1).to_list(500)
    pdf = await run_in_threadpool(build_card_pdf, p["name"].split(" ")[0], link["turns"], msgs)
    return Response(content=pdf, media_type="application/pdf", headers={"Content-Disposition": 'inline; filename="Birthday_card.pdf"'})
