"""Outlook calendar invites for check-ins, sent from the booking admin's Microsoft 365 mailbox."""
from datetime import datetime, timedelta
from fastapi import APIRouter, Depends
from fastapi.concurrency import run_in_threadpool
import re
from core import DIGEST_TZ, current_user, db, logger
import ms_services as ms

router = APIRouter(prefix="/api")


@router.get("/integrations/outlook-calendar/status")
async def calendar_status(user=Depends(current_user)):
    return {"configured": ms.configured(), "connected": ms.configured()}


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
        start = datetime.fromisoformat(ev["date"]).replace(hour=t[0], minute=t[1])
        end = start + timedelta(minutes=30)
        when = {"isAllDay": False}
    else:
        start = datetime.fromisoformat(ev["date"]).replace(hour=0, minute=0)
        end = start + timedelta(days=1)
        when = {"isAllDay": True}
    fmt = "%Y-%m-%dT%H:%M:%S"
    return {"subject": ev["title"], "body": {"contentType": "text", "content": ev.get("description") or ""},
            "location": {"displayName": ev.get("location") or ""},
            "start": {"dateTime": start.strftime(fmt), "timeZone": "W. Australia Standard Time"},
            "end": {"dateTime": end.strftime(fmt), "timeZone": "W. Australia Standard Time"},
            "attendees": [{"emailAddress": {"address": attendee_email}, "type": "required"}], **when}


async def organizer_email(admin_id: str) -> str:
    u = await db.users.find_one({"user_id": admin_id}, {"_id": 0, "email": 1, "hidden": 1})
    return "" if not u or u.get("hidden") else u.get("email", "")


async def send_invite(admin_id: str, ev: dict, attendee_email: str) -> dict:
    """Create the event in the admin's Outlook calendar; Outlook emails the invite. Returns status info."""
    org = await organizer_email(admin_id)
    if not ms.configured() or not org:
        return {"calendar": "not_connected"}
    try:
        g = await run_in_threadpool(ms.calendar_insert, org, event_body(ev, attendee_email))
        return {"calendar": "sent", "outlook_event_id": g["id"], "outlook_link": g.get("webLink")}
    except Exception as e:
        logger.error(f"Outlook invite failed: {e}")
        return {"calendar": "failed"}


async def cancel_invite(admin_id: str, event_id: str):
    org = await organizer_email(admin_id)
    if not ms.configured() or not org:
        return
    try:
        await run_in_threadpool(ms.calendar_delete, org, event_id)
    except Exception as e:
        logger.error(f"Outlook cancel failed: {e}")
