"""Post chat channel messages to a Microsoft Teams channel (Teams 'Workflows' webhook)."""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from core import P, admin_user, db
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
