"""Post chat channel messages to a Microsoft Teams channel (Teams 'Workflows' webhook)."""
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from core import P, admin_user, db, logger
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
            "events": (doc or {}).get("events", True)}


class AnnouncementsIn(BaseModel):
    webhook_url: Optional[str] = None  # empty keeps the current link
    updates: bool = True
    events: bool = True


@router.put("/integrations/teams-announcements")
async def set_announcements(body: AnnouncementsIn, admin=Depends(admin_user)):
    upd = {"key": ANN_KEY, "updates": body.updates, "events": body.events}
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


async def announce(kind: str, text: str):
    """kind: 'updates' | 'events'. Never raises (runs in the background)."""
    try:
        doc = await db.integrations.find_one({"key": ANN_KEY}, P)
        if doc and doc.get("webhook") and doc.get(kind, True):
            await ms.post_to_teams(ms.decrypt(doc["webhook"]), text)
    except Exception as e:
        logger.error(f"Teams announcement failed: {e}")
