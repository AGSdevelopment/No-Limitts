"""Post chat channel messages to a Microsoft Teams channel (Teams 'Workflows' webhook)."""
import asyncio
from datetime import datetime, timedelta
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from core import DIGEST_TZ, P, admin_user, db, logger, now_iso
import ms_services as ms

router = APIRouter(prefix="/api")


class WebhookIn(BaseModel):
    webhook_url: str


@router.put("/channels/{conv_id}/teams")
async def set_teams(conv_id: str, body: WebhookIn, admin=Depends(admin_user)):
    url = body.webhook_url.strip()
    if not ms.valid_teams_url(url):
        raise HTTPException(400, "That doesn't look like a Teams Workflows webhook link")
    res = await db.conversations.update_one({"conversation_id": conv_id, "type": "channel"},
                                            {"$set": {"teams_webhook": ms.encrypt(url)}})
    if not res.matched_count:
        raise HTTPException(404, "Channel not found")
    conv = await db.conversations.find_one({"conversation_id": conv_id}, P)
    ok = await ms.post_to_teams(url, f"No Limitts is now connected to #{conv['name']}. "
                                     "Messages posted there in the app will appear here.")
    return {"ok": True, "test_delivered": ok}


@router.delete("/channels/{conv_id}/teams")
async def remove_teams(conv_id: str, admin=Depends(admin_user)):
    res = await db.conversations.update_one({"conversation_id": conv_id, "type": "channel"},
                                            {"$unset": {"teams_webhook": ""}})
    if not res.matched_count:
        raise HTTPException(404, "Channel not found")
    return {"ok": True}


# ---- Announcements channel: company updates and new events are posted automatically
ANN_KEY = "teams_announcements"


@router.get("/integrations/teams-announcements")
async def announcements_status(admin=Depends(admin_user)):
    doc = await db.integrations.find_one({"key": ANN_KEY}, P)
    return {"linked": bool(doc and doc.get("webhook")), "updates": (doc or {}).get("updates", True),
            "events": (doc or {}).get("events", True), "celebrations": (doc or {}).get("celebrations", True),
            "weekly_wrap": (doc or {}).get("weekly_wrap", True)}


class AnnouncementsIn(BaseModel):
    webhook_url: Optional[str] = None  # empty keeps the current link
    updates: bool = True
    events: bool = True
    celebrations: bool = True
    weekly_wrap: bool = True


@router.put("/integrations/teams-announcements")
async def set_announcements(body: AnnouncementsIn, admin=Depends(admin_user)):
    upd = {"key": ANN_KEY, "updates": body.updates, "events": body.events, "celebrations": body.celebrations,
           "weekly_wrap": body.weekly_wrap}
    url = (body.webhook_url or "").strip()
    test = None
    if url:
        if not ms.valid_teams_url(url):
            raise HTTPException(400, "That doesn't look like a Teams Workflows webhook link")
        upd["webhook"] = ms.encrypt(url)
        test = await ms.post_to_teams(url, "📣 No Limitts announcements are now connected to this channel. "
                                           "New company updates and events will appear here.")
    elif not await db.integrations.find_one({"key": ANN_KEY, "webhook": {"$exists": True}}):
        raise HTTPException(400, "Paste the Teams channel's webhook link")
    await db.integrations.update_one({"key": ANN_KEY}, {"$set": upd}, upsert=True)
    return {**(await announcements_status(admin)), "test_delivered": test}


@router.delete("/integrations/teams-announcements")
async def remove_announcements(admin=Depends(admin_user)):
    await db.integrations.delete_one({"key": ANN_KEY})
    return {"ok": True}


async def build_weekly_wrap(today) -> str:
    """Friday summary text: new staff, updates and events created this week, plus next week's events."""
    week_ago = (today - timedelta(days=7)).isoformat()
    staff = [u async for u in db.users.find({"hidden": {"$ne": True}, "$or": [
        {"start_date": {"$gt": week_ago, "$lte": today.isoformat()}},
        {"start_date": {"$in": [None, ""]}, "created_at": {"$gte": week_ago}}]}, {"_id": 0, "name": 1})]
    ups = await db.updates.find({"created_at": {"$gte": week_ago}, "source": {"$exists": False}}, {"_id": 0, "title": 1}).to_list(50)
    nxt = await db.events.find({"date": {"$gt": today.isoformat(), "$lte": (today + timedelta(days=9)).isoformat()},
                                "checkin_for": {"$exists": False}}, {"_id": 0, "title": 1, "date": 1, "time": 1}).sort("date", 1).to_list(30)
    parts = [f"🗓️ **No Limitts weekly wrap · week ending {today.strftime('%d %B')}**"]
    if staff:
        parts.append("👋 **Welcome to our new team members:** " + ", ".join(s["name"] for s in staff))
    if ups:
        parts.append("📣 **Company updates this week:**\n" + "\n".join(f"- {u['title']}" for u in ups))
    if nxt:
        parts.append("📅 **Coming up:**\n" + "\n".join(
            f"- {e['title']} · {datetime.fromisoformat(e['date']).strftime('%a %d %b')}{' ' + e['time'] if e.get('time') else ''}" for e in nxt))
    if len(parts) == 1:
        parts.append("A quiet week! Thanks everyone for all you do. 💜")
    parts.append("Open the No Limitts app for details and to RSVP.")
    return "\n\n".join(parts)


async def weekly_wrap_loop():
    """Fridays from 3pm Perth: post the weekly wrap once (retries hourly if Teams fails)."""
    while True:
        try:
            now_p = datetime.now(DIGEST_TZ)
            key = f"teams_weekly_wrap_{now_p.date().isoformat()}"
            if now_p.weekday() == 4 and now_p.hour >= 15 and not await db.meta.find_one({"key": key}):
                if await announce("weekly_wrap", await build_weekly_wrap(now_p.date())):
                    await db.meta.insert_one({"key": key, "created_at": now_iso()})
        except Exception as e:
            logger.error(f"Weekly wrap failed: {e}")
        await asyncio.sleep(3600)


async def posted_keys() -> set:
    doc = await db.meta.find_one({"key": "teams_posted_celebrations"}, P)
    return set((doc or {}).get("keys", []))


async def announce(kind: str, text: str) -> bool:
    """kind: 'updates' | 'events' | 'celebrations'. Never raises (runs in the background).
    Returns False only when a linked, enabled channel failed to receive the post."""
    try:
        doc = await db.integrations.find_one({"key": ANN_KEY}, P)
        if doc and doc.get("webhook") and doc.get(kind, True):
            return await ms.post_to_teams(ms.decrypt(doc["webhook"]), text)
        return True
    except Exception as e:
        logger.error(f"Teams announcement failed: {e}")
        return False
