"""Company events and RSVPs."""
from datetime import date
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from typing import Optional
from core import P, all_user_ids, current_user, db, dmy, new_id, notify, now_iso

router = APIRouter(prefix="/api")


CATERING = ("", "Food & drink provided", "BYO", "To be arranged")
RSVP_STATUSES = ("going", "maybe", "not_going")


class EventIn(BaseModel):
    title: str
    description: str = ""  # purpose
    location: str = ""
    date: str
    time: str = ""
    catering: str = ""
    conditions: str = ""


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
    d["my_rsvp"] = next((r for r in rsvps if r["user_id"] == user["user_id"]), None)
    d["counts"] = {k: sum(1 for r in rsvps if r["status"] == k) for k in RSVP_STATUSES}
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
    doc = {"event_id": new_id("evt"), "title": body.title.strip()[:200], "description": body.description.strip()[:3000],
           "location": body.location.strip()[:300], "date": body.date, "time": body.time.strip()[:60],
           "catering": body.catering, "conditions": body.conditions.strip()[:1000], "attendees": [], "rsvps": [],
           "created_by": user["name"], "created_by_id": user["user_id"], "created_at": now_iso()}
    await db.events.insert_one(dict(doc))
    await notify(await all_user_ids(user["user_id"]), "event", f"New event from {user['name'].split(' ')[0]}",
                 f"{doc['title']} on {dmy(doc['date'])}. Tap to RSVP.", f"/event/{doc['event_id']}")
    return shape(doc, user)


@router.delete("/events/{event_id}")
async def delete_event(event_id: str, user=Depends(current_user)):
    ev = await db.events.find_one({"event_id": event_id, "checkin_for": {"$exists": False}}, P)
    if not ev:
        raise HTTPException(404, "Event not found")
    if user["role"] != "admin" and ev.get("created_by_id") != user["user_id"]:
        raise HTTPException(403, "Only the organiser or an admin can delete this event")
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
        status = None if (mine and mine["status"] == "going") or (not mine and uid in ev.get("attendees", [])) \
            else "going"
        comment = (mine or {}).get("comment", "")
    else:
        status, comment = body.status or None, body.comment.strip()[:500]
        if status and status not in RSVP_STATUSES:
            raise HTTPException(400, "Unknown RSVP option")
    await db.events.update_one({"event_id": event_id}, {"$pull": {"rsvps": {"user_id": uid}, "attendees": uid}})
    if status:
        await db.events.update_one({"event_id": event_id}, {"$push": {"rsvps": {
            "user_id": uid, "name": user["name"], "picture": user.get("picture"), "status": status,
            "comment": comment, "at": now_iso()}}, **({"$addToSet": {"attendees": uid}} if status == "going" else {})})
    ev = await db.events.find_one({"event_id": event_id}, event_fields(user))
    return {"going": status == "going", **shape(ev, user)}
