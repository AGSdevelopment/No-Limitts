"""Google Calendar connection per admin, used to send check-in invites."""
from datetime import datetime, timedelta, timezone
from fastapi import APIRouter, Depends, HTTPException
from fastapi.concurrency import run_in_threadpool
import re
import secrets
from core import DIGEST_TZ, P, admin_user, current_user, db, logger, now, now_iso, result_page
import google_services as gs

router = APIRouter(prefix="/api")

KIND = "google-calendar"


def cal_key(user_id: str) -> str:
    return f"google_calendar:{user_id}"


@router.get("/integrations/google-calendar/status")
async def calendar_status(admin=Depends(current_user)):
    conn = await db.integrations.find_one({"key": cal_key(admin["user_id"])}, P)
    return {"configured": bool(gs.drive_client_config()), "connected": bool(conn),
            "email": (conn or {}).get("email", ""), "redirect_uri": gs.redirect_uri(KIND)}


@router.post("/integrations/google-calendar/start")
async def calendar_start(admin=Depends(current_user)):
    if not gs.drive_client_config():
        raise HTTPException(409, "Google sign-in credentials are not set up yet")
    state = secrets.token_urlsafe(32)
    url, verifier = gs.oauth_auth_url(KIND, gs.CALENDAR_SCOPES, state, admin.get("email", ""))
    await db.oauth_states.insert_one({"state": state, "user_id": admin["user_id"], "code_verifier": verifier,
                                      "kind": KIND, "created_at": now()})
    return {"authorization_url": url}


@router.get("/integrations/google-calendar/callback")
async def calendar_callback(state: str = "", code: str = "", error: str = ""):
    st = await db.oauth_states.find_one_and_delete({"state": state, "kind": KIND})
    if error or not st or not code:
        return result_page("Google Calendar not connected", "The request was cancelled or expired.")
    created = st["created_at"].replace(tzinfo=timezone.utc) if st["created_at"].tzinfo is None else st["created_at"]
    if now() - created > timedelta(minutes=15):
        return result_page("Google Calendar not connected", "The request expired. Please try again.")
    key = cal_key(st["user_id"])
    try:
        refresh = await run_in_threadpool(gs.oauth_exchange, KIND, gs.CALENDAR_SCOPES, state, code,
                                          st.get("code_verifier"))
        old = await db.integrations.find_one({"key": key}, P)
        enc = gs.encrypt(refresh) if refresh else (old or {}).get("refresh_token")
        if not enc:
            return result_page("Google Calendar not connected", "Google did not grant offline access. Try again.")
        await run_in_threadpool(gs.calendar_service, enc)  # proves the token works
    except Exception as e:
        logger.error(f"Calendar OAuth failed: {e}")
        return result_page("Google Calendar not connected", "Something went wrong while connecting. "
                           "Check that the Google Calendar API is turned on for No Limitts's Google project.")
    admin = await db.users.find_one({"user_id": st["user_id"]}, P) or {}
    await db.integrations.update_one({"key": key}, {"$set": {
        "key": key, "refresh_token": enc, "email": admin.get("email", ""), "user_id": st["user_id"],
        "updated_at": now_iso()}}, upsert=True)
    return result_page("Google Calendar connected", "No Limitts can now add dates to your Google Calendar. You can close this page.")


@router.delete("/integrations/google-calendar")
async def calendar_disconnect(admin=Depends(current_user)):
    await db.integrations.delete_one({"key": cal_key(admin["user_id"])})
    await db.plan_cal_events.delete_many({"user_id": admin["user_id"]})
    return {"ok": True}


def parse_time(text: str):
    """'10am', '10:30 am', '14:00' -> (hour, minute) or None."""
    m = re.match(r"^\s*(\d{1,2})(?:[:.](\d{2}))?\s*([ap]\.?m\.?)?\s*$", text.lower())
    if not m:
        return None
    h, mins, ap = int(m.group(1)), int(m.group(2) or 0), (m.group(3) or "").replace(".", "")
    if ap == "pm" and h < 12:
        h += 12
    if ap == "am" and h == 12:
        h = 0
    return (h, mins) if h < 24 and mins < 60 else None


def event_body(ev: dict, attendee_email: str) -> dict:
    t = parse_time(ev.get("time") or "")
    if t:
        start = datetime.fromisoformat(ev["date"]).replace(hour=t[0], minute=t[1], tzinfo=DIGEST_TZ)
        when = {"start": {"dateTime": start.isoformat(), "timeZone": "Australia/Perth"},
                "end": {"dateTime": (start + timedelta(minutes=30)).isoformat(), "timeZone": "Australia/Perth"}}
    else:
        day = datetime.fromisoformat(ev["date"]).date()
        when = {"start": {"date": day.isoformat()}, "end": {"date": (day + timedelta(days=1)).isoformat()}}
    return {"summary": ev["title"], "description": ev.get("description") or "", "location": ev.get("location") or "",
            "attendees": [{"email": attendee_email}], **when}


async def admin_calendar(admin_id: str):
    conn = await db.integrations.find_one({"key": cal_key(admin_id)}, P)
    if not conn or not gs.drive_client_config():
        return None
    return await run_in_threadpool(gs.calendar_service, conn["refresh_token"])


async def send_invite(admin_id: str, ev: dict, attendee_email: str) -> dict:
    """Create the event on the admin's Google Calendar and invite the attendee. Returns status info."""
    try:
        svc = await admin_calendar(admin_id)
        if not svc:
            return {"calendar": "not_connected"}
        g = await run_in_threadpool(gs.calendar_insert, svc, event_body(ev, attendee_email))
        return {"calendar": "sent", "google_event_id": g["id"], "google_link": g.get("htmlLink")}
    except Exception as e:
        logger.error(f"Calendar invite failed: {e}")
        return {"calendar": "failed"}


async def cancel_invite(admin_id: str, google_event_id: str):
    try:
        svc = await admin_calendar(admin_id)
        if svc:
            await run_in_threadpool(gs.calendar_delete, svc, google_event_id)
    except Exception as e:
        logger.error(f"Calendar cancel failed: {e}")
