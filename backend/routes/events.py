"""Company events, RSVPs, reminders, photos and calendar files."""
import asyncio
import uuid
from datetime import date, datetime, timedelta, timezone
from html import escape
from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import Response
from pydantic import BaseModel
from typing import Optional
from core import (DIGEST_TZ, MAX_UPLOAD_BYTES, P, all_user_ids, bearer, current_user, db, dmy, logger, new_id, notify,
                  now_iso, user_from_token)
from email_service import send_email
from storage import APP_NAME, get_object, put_object

router = APIRouter(prefix="/api")


CATERING = ("", "Food & drink provided", "BYO", "To be arranged")
RSVP_STATUSES = ("going", "maybe", "not_going")
REPEATS = {"": 0, "weekly": 7, "fortnightly": 14, "monthly": -1}


class EventIn(BaseModel):
    title: str
    description: str = ""  # purpose
    location: str = ""
    date: str
    time: str = ""
    catering: str = ""
    conditions: str = ""
    capacity: Optional[int] = None  # max places; extra "going" RSVPs join a waitlist
    repeat: str = ""  # "", weekly, fortnightly, monthly
    occurrences: int = 1


class CommentIn(BaseModel):
    text: str


class RsvpIn(BaseModel):
    status: Optional[str] = None  # going / maybe / not_going; None or "" removes the response
    comment: str = ""


def visible_events(user: dict) -> dict:
    """Private events (e.g. new starter check-ins) only show to the people involved; admins see all."""
    if user.get("role") == "admin":
        return {}
    return {"$or": [{"private_for": {"$exists": False}}, {"private_for": user["user_id"]}]}


def event_fields(user: dict) -> dict:
    """Check-in notes/outcomes are admin-only."""
    hidden = {"_id": 0}
    if user.get("role") != "admin":
        hidden.update({"notes": 0, "outcome": 0, "notes_by": 0, "notes_at": 0, "followup_group_id": 0})
    return hidden


@router.get("/events")
async def list_events(user=Depends(current_user)):
    docs = await db.events.find(visible_events(user), event_fields(user)).sort([("date", 1), ("time", 1)]).to_list(500)
    return [shape(d, user) for d in docs]


def shape(d: dict, user: dict) -> dict:
    rsvps = d.pop("rsvps", None) or []
    d["going"] = user["user_id"] in d.get("attendees", [])
    d["attendee_count"] = len(d.get("attendees", []))
    d.pop("attendees", None)
    d["rsvps"] = rsvps
    d["photos"] = [{k: v for k, v in p.items() if k != "storage_path"} for p in d.get("photos") or []]
    d["my_rsvp"] = next((r for r in rsvps if r["user_id"] == user["user_id"]), None)
    d["counts"] = {k: sum(1 for r in rsvps if r["status"] == k) for k in (*RSVP_STATUSES, "waitlist")}
    d["places_left"] = max(d["capacity"] - d["counts"]["going"], 0) if d.get("capacity") else None
    d["comments"] = d.get("comments") or []
    if not rsvps:
        d["counts"]["going"] = d["attendee_count"]
    d["can_delete"] = user["role"] == "admin" or d.get("created_by_id") == user["user_id"]
    return d


@router.get("/events/{event_id}")
async def get_event(event_id: str, user=Depends(current_user)):
    ev = await db.events.find_one({"event_id": event_id, **visible_events(user)}, event_fields(user))
    if not ev:
        raise HTTPException(404, "Event not found")
    return shape(ev, user)


@router.post("/events")
async def create_event(body: EventIn, user=Depends(current_user)):
    """Any staff member can create an event for the whole team."""
    try:
        if date.fromisoformat(body.date) < date.today():
            raise HTTPException(400, "Pick today or a future date")
    except ValueError:
        raise HTTPException(400, "Date must be YYYY-MM-DD")
    if not body.title.strip():
        raise HTTPException(400, "Title is required")
    if body.catering not in CATERING:
        raise HTTPException(400, "Unknown food & drink option")
    if body.repeat not in REPEATS:
        raise HTTPException(400, "Unknown repeat option")
    if body.capacity is not None and not (1 <= body.capacity <= 1000):
        raise HTTPException(400, "Places must be between 1 and 1000")
    count = max(1, min(body.occurrences, 12)) if body.repeat else 1
    first = date.fromisoformat(body.date)
    series_id = new_id("ser") if count > 1 else None
    docs = []
    for i in range(count):
        day = first + timedelta(days=REPEATS[body.repeat] * i) if REPEATS[body.repeat] > 0 else add_months(first, i)
        doc = {"event_id": new_id("evt"), "title": body.title.strip()[:200], "description": body.description.strip()[:3000],
               "location": body.location.strip()[:300], "date": day.isoformat(), "time": body.time.strip()[:60],
               "catering": body.catering, "conditions": body.conditions.strip()[:1000], "capacity": body.capacity,
               "series_id": series_id, "repeat": body.repeat if count > 1 else "", "attendees": [], "rsvps": [],
               "comments": [], "created_by": user["name"], "created_by_id": user["user_id"], "created_at": now_iso()}
        await db.events.insert_one(dict(doc))
        docs.append(doc)
    extra = f" (and {count - 1} more, repeating {body.repeat})" if count > 1 else ""
    await notify(await all_user_ids(user["user_id"]), "event", f"New event from {user['name'].split(' ')[0]}",
                 f"{docs[0]['title']} on {dmy(docs[0]['date'])}{extra}. Tap to RSVP.", f"/event/{docs[0]['event_id']}")
    return {**shape(docs[0], user), "created": count}


def add_months(d: date, months: int) -> date:
    y, m = divmod(d.month - 1 + months, 12)
    for day in (d.day, 30, 29, 28):
        try:
            return date(d.year + y, m + 1, day)
        except ValueError:
            continue


@router.delete("/events/{event_id}")
async def delete_event(event_id: str, series: bool = False, user=Depends(current_user)):
    ev = await db.events.find_one({"event_id": event_id, "checkin_for": {"$exists": False}}, P)
    if not ev:
        raise HTTPException(404, "Event not found")
    if user["role"] != "admin" and ev.get("created_by_id") != user["user_id"]:
        raise HTTPException(403, "Only the organiser or an admin can delete this event")
    if series and ev.get("series_id"):
        later = await db.events.find({"series_id": ev["series_id"], "date": {"$gte": ev["date"]}},
                                     {"_id": 0, "rsvps": 1}).to_list(50)
        ev["rsvps"] = [r for e in later for r in e.get("rsvps") or []]
        await db.events.delete_many({"series_id": ev["series_id"], "date": {"$gte": ev["date"]}})
    else:
        await db.events.delete_one({"event_id": event_id})
    ids = [r["user_id"] for r in ev.get("rsvps") or [] if r["status"] != "not_going" and r["user_id"] != user["user_id"]]
    if ids:
        await notify(ids, "event", "Event cancelled", f"{ev['title']} on {dmy(ev['date'])} has been cancelled", "/events")
    return {"ok": True}


@router.post("/events/{event_id}/rsvp")
async def rsvp(event_id: str, body: Optional[RsvpIn] = None, user=Depends(current_user)):
    """With a body: set going / maybe / not_going plus a comment (visible to everyone). Without: toggle going."""
    ev = await db.events.find_one({"event_id": event_id, **visible_events(user)}, P)
    if not ev:
        raise HTTPException(404, "Event not found")
    uid = user["user_id"]
    if body is None:
        mine = next((r for r in ev.get("rsvps") or [] if r["user_id"] == uid), None)
        status = None if (mine and mine["status"] in ("going", "waitlist")) or (not mine and uid in ev.get("attendees", [])) \
            else "going"
        comment = (mine or {}).get("comment", "")
    else:
        status, comment = body.status or None, body.comment.strip()[:500]
        if status == "waitlist":
            status = "going"  # joining the waitlist is decided by the server
        if status and status not in RSVP_STATUSES:
            raise HTTPException(400, "Unknown RSVP option")
    mine = next((r for r in ev.get("rsvps") or [] if r["user_id"] == uid), None)
    if status == "going" and ev.get("capacity") and (mine or {}).get("status") != "going":
        taken = sum(1 for r in ev.get("rsvps") or [] if r["status"] == "going")
        if taken >= ev["capacity"]:
            status = "waitlist"
    if mine and mine["status"] == "waitlist" and status == "going":
        status = "waitlist"  # keep their place in the queue
    await db.events.update_one({"event_id": event_id}, {"$pull": {"rsvps": {"user_id": uid}, "attendees": uid}})
    if status:
        await db.events.update_one({"event_id": event_id}, {"$push": {"rsvps": {
            "user_id": uid, "name": user["name"], "picture": user.get("picture"), "status": status,
            "comment": comment, "at": mine["at"] if status == "waitlist" and mine and mine["status"] == "waitlist"
            else now_iso()}},
            **({"$addToSet": {"attendees": uid}} if status == "going" else {})})
    await promote_waitlist(event_id)
    ev = await db.events.find_one({"event_id": event_id}, event_fields(user))
    return {"going": status == "going", "waitlisted": status == "waitlist", **shape(ev, user)}


async def promote_waitlist(event_id: str):
    """Move the earliest waitlisted people into free places and tell them."""
    ev = await db.events.find_one({"event_id": event_id}, P)
    if not ev or not ev.get("capacity"):
        return
    rsvps = ev.get("rsvps") or []
    free = ev["capacity"] - sum(1 for r in rsvps if r["status"] == "going")
    queue = sorted([r for r in rsvps if r["status"] == "waitlist"], key=lambda r: r["at"])[:max(free, 0)]
    for r in queue:
        res = await db.events.update_one({"event_id": event_id, "rsvps": {"$elemMatch": {
            "user_id": r["user_id"], "status": "waitlist"}}}, {"$set": {"rsvps.$.status": "going"},
                                                             "$addToSet": {"attendees": r["user_id"]}})
        if res.modified_count:
            await notify([r["user_id"]], "event", "You're off the waitlist!",
                         f"A place opened up: you're now going to {ev['title']} on {dmy(ev['date'])}",
                         f"/event/{event_id}")


# ---- Event reminders (day before, 9am Perth) to everyone Going or Maybe
async def event_reminder_loop():
    while True:
        try:
            local = datetime.now(DIGEST_TZ)
            if local.hour >= 9:
                tomorrow = (local.date() + timedelta(days=1)).isoformat()
                async for ev in db.events.find({"date": tomorrow, "checkin_for": {"$exists": False},
                                                "reminded_for": {"$ne": tomorrow}}, P):
                    claim = await db.events.update_one({"event_id": ev["event_id"], "reminded_for": {"$ne": tomorrow}},
                                                       {"$set": {"reminded_for": tomorrow}})
                    if not claim.modified_count:
                        continue
                    people = [r for r in ev.get("rsvps") or [] if r["status"] in ("going", "maybe")]
                    if not people:
                        continue
                    when = "tomorrow" + (f" at {ev['time']}" if ev.get("time") else "")
                    where = f" · {ev['location']}" if ev.get("location") else ""
                    await notify([r["user_id"] for r in people], "event", f"Reminder: {ev['title']}",
                                 f"{ev['title']} is {when}{where}", f"/event/{ev['event_id']}")
                    users = await db.users.find({"user_id": {"$in": [r["user_id"] for r in people]},
                                                 "hidden": {"$ne": True}}, P).to_list(500)
                    for u in users:
                        if u.get("email") and not u["email"].endswith("@example.com"):
                            await send_email(to=u["email"], subject=f"Reminder: {ev['title']} is {when}", html=(
                                "<div style='font-family:Arial,sans-serif;max-width:520px;margin:0 auto;padding:24px'>"
                                f"<h2 style='color:#205890'>See you tomorrow!</h2>"
                                f"<p>Hi {escape(u['name'].split(' ')[0])},</p><p>Just a reminder that "
                                f"<b>{escape(ev['title'])}</b> is on <b>{dmy(ev['date'])}"
                                f"{' at ' + escape(ev['time']) if ev.get('time') else ''}</b>"
                                f"{' at ' + escape(ev['location']) if ev.get('location') else ''}.</p>"
                                + (f"<p>Food &amp; drink: {escape(ev['catering'])}</p>" if ev.get("catering") else "")
                                + (f"<p>{escape(ev['conditions'])}</p>" if ev.get("conditions") else "")
                                + "<p>Can't make it any more? Update your RSVP in StaffHub → Events.</p></div>"))
                    logger.info(f"Event reminder sent for {ev['event_id']} to {len(people)} people")
        except Exception as e:
            logger.error(f"Event reminder loop failed: {e}")
        await asyncio.sleep(1800)


# ---- Event photos
@router.post("/events/{event_id}/photos")
async def add_event_photo(event_id: str, file: UploadFile = File(...), user=Depends(current_user)):
    ev = await db.events.find_one({"event_id": event_id, "checkin_for": {"$exists": False}, **visible_events(user)}, P)
    if not ev:
        raise HTTPException(404, "Event not found")
    attended = any(r["user_id"] == user["user_id"] and r["status"] in ("going", "maybe") for r in ev.get("rsvps") or [])
    if not (attended or user["user_id"] in ev.get("attendees", []) or ev.get("created_by_id") == user["user_id"]
            or user["role"] == "admin"):
        raise HTTPException(403, "Only people who went (or the organiser) can add photos")
    ctype = (file.content_type or "").lower()
    if ctype not in ("image/jpeg", "image/png", "image/heic", "image/heif", "image/webp", "image/gif"):
        raise HTTPException(400, "Photos only (JPG, PNG or HEIC)")
    data = await file.read()
    if not data:
        raise HTTPException(400, "Empty file")
    if len(data) > MAX_UPLOAD_BYTES:
        raise HTTPException(413, "Photo too large (max 15 MB)")
    if len(ev.get("photos") or []) >= 200:
        raise HTTPException(400, "This event already has 200 photos")
    ext = (file.filename or "photo.jpg").rsplit(".", 1)[-1].lower() if "." in (file.filename or "") else "jpg"
    path = f"{APP_NAME}/events/{event_id}/{uuid.uuid4().hex}.{ext}"
    try:
        await run_in_threadpool(put_object, path, data, ctype)
    except Exception as e:
        logger.error(f"event photo upload failed: {e}")
        raise HTTPException(502, "Could not store the photo, please try again")
    photo = {"photo_id": new_id("pho"), "storage_path": path, "content_type": ctype, "user_id": user["user_id"],
             "name": user["name"], "created_at": now_iso()}
    await db.events.update_one({"event_id": event_id}, {"$push": {"photos": photo}})
    photo.pop("storage_path")
    return photo


@router.get("/events/{event_id}/photos/{photo_id}")
async def event_photo(event_id: str, photo_id: str, request: Request, token: Optional[str] = None):
    user = await user_from_token(bearer(request) or token)
    if not user:
        raise HTTPException(401, "Not authenticated")
    ev = await db.events.find_one({"event_id": event_id, **visible_events(user)}, {"_id": 0, "photos": 1})
    photo = next((p for p in (ev or {}).get("photos") or [] if p["photo_id"] == photo_id), None)
    if not photo:
        raise HTTPException(404, "Photo not found")
    data, ctype = await run_in_threadpool(get_object, photo["storage_path"])
    return Response(content=data, media_type=photo.get("content_type") or ctype,
                    headers={"Cache-Control": "private, max-age=86400", "X-Content-Type-Options": "nosniff"})


@router.delete("/events/{event_id}/photos/{photo_id}")
async def delete_event_photo(event_id: str, photo_id: str, user=Depends(current_user)):
    q = {"photo_id": photo_id} if user["role"] == "admin" else {"photo_id": photo_id, "user_id": user["user_id"]}
    res = await db.events.update_one({"event_id": event_id}, {"$pull": {"photos": q}})
    if not res.modified_count:
        raise HTTPException(404, "Photo not found")
    return {"ok": True}


# ---- Add to calendar (.ics)
def ics_escape(v: str) -> str:
    return (v or "").replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,").replace("\n", "\\n")


@router.get("/events/{event_id}/ics")
async def event_ics(event_id: str, request: Request, token: Optional[str] = None):
    user = await user_from_token(bearer(request) or token)
    if not user:
        raise HTTPException(401, "Not authenticated")
    ev = await db.events.find_one({"event_id": event_id, **visible_events(user)}, P)
    if not ev:
        raise HTTPException(404, "Event not found")
    from routes.calendar import parse_time
    t = parse_time(ev.get("time") or "")
    day = date.fromisoformat(ev["date"])
    if t:
        start = datetime(day.year, day.month, day.day, t[0], t[1], tzinfo=DIGEST_TZ).astimezone(timezone.utc)
        fmt = "%Y%m%dT%H%M%SZ"
        when = f"DTSTART:{start.strftime(fmt)}\r\nDTEND:{(start + timedelta(hours=2)).strftime(fmt)}"
    else:
        when = f"DTSTART;VALUE=DATE:{day.strftime('%Y%m%d')}\r\nDTEND;VALUE=DATE:{(day + timedelta(days=1)).strftime('%Y%m%d')}"
    desc = "\n".join(x for x in (ev.get("description"), ev.get("catering") and f"Food & drink: {ev['catering']}",
                                 ev.get("conditions")) if x)
    body = ("BEGIN:VCALENDAR\r\nVERSION:2.0\r\nPRODID:-//StaffHub//Aspire & Grow//EN\r\nBEGIN:VEVENT\r\n"
            f"UID:{ev['event_id']}@staffhub\r\nDTSTAMP:{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}\r\n"
            f"{when}\r\nSUMMARY:{ics_escape(ev['title'])}\r\nLOCATION:{ics_escape(ev.get('location', ''))}\r\n"
            f"DESCRIPTION:{ics_escape(desc)}\r\nEND:VEVENT\r\nEND:VCALENDAR\r\n")
    return Response(content=body, media_type="text/calendar",
                    headers={"Content-Disposition": f'attachment; filename="{event_id}.ics"'})



# ---- Event comments (chat on the event page)
@router.post("/events/{event_id}/comments")
async def add_comment(event_id: str, body: CommentIn, user=Depends(current_user)):
    text = body.text.strip()[:1000]
    if not text:
        raise HTTPException(400, "Write a message")
    ev = await db.events.find_one({"event_id": event_id, "checkin_for": {"$exists": False}, **visible_events(user)}, P)
    if not ev:
        raise HTTPException(404, "Event not found")
    c = {"comment_id": new_id("cmt"), "user_id": user["user_id"], "name": user["name"], "picture": user.get("picture"),
         "text": text, "created_at": now_iso()}
    await db.events.update_one({"event_id": event_id}, {"$push": {"comments": c}})
    ids = {r["user_id"] for r in ev.get("rsvps") or [] if r["status"] in ("going", "maybe", "waitlist")}
    ids |= {x["user_id"] for x in ev.get("comments") or []}
    if ev.get("created_by_id"):
        ids.add(ev["created_by_id"])
    ids.discard(user["user_id"])
    if ids:
        await notify(list(ids), "event", f"{user['name'].split(' ')[0]} on {ev['title']}", text[:140],
                     f"/event/{event_id}")
    return c


@router.delete("/events/{event_id}/comments/{comment_id}")
async def delete_comment(event_id: str, comment_id: str, user=Depends(current_user)):
    q = {"comment_id": comment_id} if user["role"] == "admin" else {"comment_id": comment_id, "user_id": user["user_id"]}
    res = await db.events.update_one({"event_id": event_id}, {"$pull": {"comments": q}})
    if not res.modified_count:
        raise HTTPException(404, "Comment not found")
    return {"ok": True}


async def photo_highlights(user: dict, limit: int = 8) -> list:
    out = []
    async for ev in db.events.find({"photos.0": {"$exists": True}, "checkin_for": {"$exists": False},
                                    **visible_events(user)}, {"_id": 0, "event_id": 1, "title": 1, "photos": 1}):
        for p in ev["photos"]:
            out.append({"event_id": ev["event_id"], "event_title": ev["title"], "photo_id": p["photo_id"],
                        "name": p["name"], "created_at": p["created_at"]})
    return sorted(out, key=lambda x: x["created_at"], reverse=True)[:limit]
