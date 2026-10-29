"""Channels, direct messages and messages."""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
import re
from core import P, admin_user, current_user, db, logger, new_id, notify, now_iso, spawn
import ms_services as ms

router = APIRouter(prefix="/api")


async def conv_for_user(conv_id: str, user: dict):
    conv = await db.conversations.find_one({"conversation_id": conv_id}, P)
    if not conv or (conv["type"] == "dm" and user["user_id"] not in conv["member_ids"]):
        raise HTTPException(404, "Conversation not found")
    return conv


@router.get("/conversations")
async def list_conversations(user=Depends(current_user)):
    uid = user["user_id"]
    convs = await db.conversations.find({"$or": [{"type": "channel"}, {"member_ids": uid}]}, P).to_list(500)
    reads = {r["conversation_id"]: r["last_read_at"] for r in
             await db.conv_reads.find({"user_id": uid}, P).to_list(1000)}
    users = {u["user_id"]: u for u in await db.users.find({}, P).to_list(5000)}
    out = []
    for c in convs:
        last_read = reads.get(c["conversation_id"], "")
        unread = await db.messages.count_documents({"conversation_id": c["conversation_id"],
                                                    "created_at": {"$gt": last_read},
                                                    "sender_id": {"$ne": uid}})
        if c["type"] == "dm":
            other_id = next((m for m in c["member_ids"] if m != uid), uid)
            other = users.get(other_id, {})
            c["name"] = other.get("name", "Unknown")
            c["picture"] = other.get("picture")
            c["other_user_id"] = other_id
        c["unread"] = unread
        c["teams"] = bool(c.pop("teams_webhook", None))
        for k in ("gchat_webhook", "gchat_two_way", "gchat_space", "gchat_cursor"):
            c.pop(k, None)
        out.append(c)
    out.sort(key=lambda c: c.get("last_at") or c.get("created_at"), reverse=True)
    return out


class ChannelIn(BaseModel):
    name: str
    description: str = ""


@router.post("/channels")
async def create_channel(body: ChannelIn, admin=Depends(admin_user)):
    name = body.name.strip().lstrip("#").strip().replace(" ", "-")
    if not name:
        raise HTTPException(400, "Name is required")
    if await db.conversations.find_one({"type": "channel", "name": {"$regex": f"^{re.escape(name)}$", "$options": "i"}}):
        raise HTTPException(400, "Channel already exists")
    conv = {"conversation_id": new_id("conv"), "type": "channel", "name": name, "description": body.description,
            "member_ids": [], "last_message": "", "last_at": "", "created_at": now_iso()}
    await db.conversations.insert_one(dict(conv))
    return conv


class DMIn(BaseModel):
    user_id: str


@router.post("/dms")
async def open_dm(body: DMIn, user=Depends(current_user)):
    if body.user_id == user["user_id"]:
        raise HTTPException(400, "Cannot message yourself")
    other = await db.users.find_one({"user_id": body.user_id}, P)
    if not other:
        raise HTTPException(404, "User not found")
    members = sorted([user["user_id"], body.user_id])
    conv_id = "dm_" + "_".join(members)
    conv = await db.conversations.find_one({"conversation_id": conv_id}, P)
    if not conv:
        conv = {"conversation_id": conv_id, "type": "dm", "name": "", "description": "", "member_ids": members,
                "last_message": "", "last_at": "", "created_at": now_iso()}
        await db.conversations.insert_one(dict(conv))
    conv["name"] = other["name"]
    return conv


@router.get("/conversations/{conv_id}/messages")
async def get_messages(conv_id: str, after: str = "", user=Depends(current_user)):
    await conv_for_user(conv_id, user)
    q = {"conversation_id": conv_id}
    if after:
        q["created_at"] = {"$gt": after}
    msgs = await db.messages.find(q, P).sort("created_at", -1).to_list(200)
    return list(reversed(msgs))


class MessageIn(BaseModel):
    text: str


@router.post("/conversations/{conv_id}/messages")
async def send_message(conv_id: str, body: MessageIn, user=Depends(current_user)):
    conv = await conv_for_user(conv_id, user)
    text = body.text.strip()
    if not text:
        raise HTTPException(400, "Message is empty")
    msg = {"message_id": new_id("msg"), "conversation_id": conv_id, "sender_id": user["user_id"],
           "sender_name": user["name"], "sender_picture": user.get("picture"), "text": text[:4000],
           "created_at": now_iso()}
    await db.messages.insert_one(dict(msg))
    await db.conversations.update_one({"conversation_id": conv_id},
                                      {"$set": {"last_message": f"{user['name'].split(' ')[0]}: {text[:80]}",
                                                "last_at": msg["created_at"]}})
    await db.conv_reads.update_one({"user_id": user["user_id"], "conversation_id": conv_id},
                                   {"$set": {"last_read_at": msg["created_at"]}}, upsert=True)
    if conv["type"] == "channel" and conv.get("teams_webhook"):
        try:
            hook = ms.decrypt(conv["teams_webhook"])
            spawn(ms.post_to_teams(hook, f"**{user['name']}** in #{conv['name']} (No Limitts):\n\n{text[:4000]}"))
        except Exception as e:
            logger.error(f"Teams webhook unusable for {conv_id}: {e}")
    if conv["type"] == "dm":
        others = [m for m in conv["member_ids"] if m != user["user_id"]]
        await notify(others, "message", f"New message from {user['name']}", text[:120], f"/chat/{conv_id}")
    return msg


@router.post("/conversations/{conv_id}/read")
async def mark_read(conv_id: str, user=Depends(current_user)):
    await conv_for_user(conv_id, user)
    await db.conv_reads.update_one({"user_id": user["user_id"], "conversation_id": conv_id},
                                   {"$set": {"last_read_at": now_iso()}}, upsert=True)
    return {"ok": True}
