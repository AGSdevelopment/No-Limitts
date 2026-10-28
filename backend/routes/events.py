"""Company events and RSVPs."""
from datetime import date
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from core import P, admin_user, all_user_ids, current_user, db, dmy, new_id, notify, now_iso

router = APIRouter(prefix="/api")


class EventIn(BaseModel):
    title: str
    description: str = ""
    location: str = ""
    date: str
    time: str = ""


@router.get("/events")
async def list_events(user=Depends(current_user)):
    docs = await db.events.find({}, P).sort([("date", 1), ("time", 1)]).to_list(500)
    for d in docs:
        d["going"] = user["user_id"] in d.get("attendees", [])
        d["attendee_count"] = len(d.get("attendees", []))
        d.pop("attendees", None)
    return docs


@router.post("/events")
async def create_event(body: EventIn, admin=Depends(admin_user)):
    try:
        date.fromisoformat(body.date)
    except ValueError:
        raise HTTPException(400, "Date must be YYYY-MM-DD")
    if not body.title.strip():
        raise HTTPException(400, "Title is required")
    doc = {"event_id": new_id("evt"), "title": body.title.strip(), "description": body.description.strip(),
           "location": body.location.strip(), "date": body.date, "time": body.time.strip(), "attendees": [],
           "created_by": admin["name"], "created_at": now_iso()}
    await db.events.insert_one(dict(doc))
    await notify(await all_user_ids(admin["user_id"]), "event", "New event", f"{doc['title']} on {dmy(doc['date'])}",
                 "/events")
    doc.pop("attendees")
    return {**doc, "going": False, "attendee_count": 0}


@router.post("/events/{event_id}/rsvp")
async def rsvp(event_id: str, user=Depends(current_user)):
    ev = await db.events.find_one({"event_id": event_id}, P)
    if not ev:
        raise HTTPException(404, "Event not found")
    going = user["user_id"] in ev.get("attendees", [])
    op = "$pull" if going else "$addToSet"
    await db.events.update_one({"event_id": event_id}, {op: {"attendees": user["user_id"]}})
    return {"going": not going}
