"""Google Chat webhooks and two-way sync."""
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel
from typing import Optional
import asyncio
import secrets
from core import P, admin_user, db, logger, new_id, now, now_iso, result_page
import google_services as gs

router = APIRouter(prefix="/api")


class WebhookIn(BaseModel):
    webhook_url: str


@router.put("/channels/{conv_id}/google-chat")
async def set_gchat(conv_id: str, body: WebhookIn, admin=Depends(admin_user)):
    url = body.webhook_url.strip()
    if not gs.valid_gchat_url(url):
        raise HTTPException(400, "That doesn't look like a Google Chat webhook link")
    res = await db.conversations.update_one({"conversation_id": conv_id, "type": "channel"},
                                            {"$set": {"gchat_webhook": gs.encrypt(url),
                                                      "gchat_space": gs.space_from_webhook(url)}})
    if not res.matched_count:
        raise HTTPException(404, "Channel not found")
    conv = await db.conversations.find_one({"conversation_id": conv_id}, P)
    ok = await gs.post_to_gchat(url, f"No Limitts is now connected to #{conv['name']}. "
                                     "Messages posted there will appear here.")
    return {"ok": True, "test_delivered": ok}


@router.delete("/channels/{conv_id}/google-chat")
async def remove_gchat(conv_id: str, admin=Depends(admin_user)):
    res = await db.conversations.update_one({"conversation_id": conv_id, "type": "channel"},
                                            {"$unset": {"gchat_webhook": "", "gchat_space": "", "gchat_two_way": "",
                                                        "gchat_cursor": ""}})
    if not res.matched_count:
        raise HTTPException(404, "Channel not found")
    return {"ok": True}


GCHAT_KEY = "google_chat_reader"


@router.get("/integrations/google-chat/status")
async def gchat_status(admin=Depends(admin_user)):
    conn = await db.integrations.find_one({"key": GCHAT_KEY}, P)
    return {"configured": bool(gs.drive_client_config()), "connected": bool(conn),
            "last_error": (conn or {}).get("last_error", ""), "redirect_uri": gs.redirect_uri("google-chat")}


class StartIn(BaseModel):
    login_hint: str = ""


@router.post("/integrations/google-chat/start")
async def gchat_start(body: Optional[StartIn] = None, admin=Depends(admin_user)):
    if not gs.drive_client_config():
        raise HTTPException(409, "Google sign-in credentials are not set up yet")
    state = secrets.token_urlsafe(32)
    url, verifier = gs.oauth_auth_url("google-chat", gs.CHAT_SCOPES, state, (body.login_hint if body else "")[:200])
    await db.oauth_states.insert_one({"state": state, "user_id": admin["user_id"], "code_verifier": verifier,
                                      "kind": "google-chat", "login_hint": (body.login_hint if body else ""),
                                      "created_at": now()})
    return {"authorization_url": url}


@router.get("/integrations/google-chat/callback")
async def gchat_callback(state: str = "", code: str = "", error: str = ""):
    st = await db.oauth_states.find_one_and_delete({"state": state, "kind": "google-chat"})
    if error or not st or not code:
        return result_page("Google Chat not connected", "The request was cancelled or expired.")
    try:
        refresh = await run_in_threadpool(gs.oauth_exchange, "google-chat", gs.CHAT_SCOPES, state, code,
                                          st.get("code_verifier"))
        old = await db.integrations.find_one({"key": GCHAT_KEY}, P)
        enc = gs.encrypt(refresh) if refresh else (old or {}).get("refresh_token")
        if not enc:
            return result_page("Google Chat not connected", "Google did not grant offline access. Try again.")
        await run_in_threadpool(gs.chat_service, enc)
    except Exception as e:
        logger.error(f"Google Chat OAuth failed: {e}")
        if "invalid_client" in str(e):
            return result_page("Google Chat not connected",
                               "Google rejected No Limitts's sign-in credentials (client ID or secret is wrong). "
                               "Please re-enter them and try again.")
        return result_page("Google Chat not connected", "Something went wrong while connecting.")
    await db.integrations.update_one({"key": GCHAT_KEY}, {"$set": {
        "key": GCHAT_KEY, "refresh_token": enc, "last_error": "", "connected_by": st["user_id"],
        "login_hint": st.get("login_hint", ""), "updated_at": now_iso()}}, upsert=True)
    # start syncing from the moment of connection for channels already switched on
    await db.conversations.update_many({"gchat_two_way": True},
                                       {"$set": {"gchat_cursor": now().strftime("%Y-%m-%dT%H:%M:%S.%fZ")}})
    return result_page("Google Chat connected", "Replies from your Google Chat spaces can now flow into No Limitts.")


@router.post("/integrations/google-chat/events")
async def gchat_events(request: Request):
    """Endpoint required by the Google Chat API app configuration. No Limitts reads space messages via the
    Chat API (two-way sync), so interaction events are simply acknowledged."""
    return {}


@router.delete("/integrations/google-chat")
async def gchat_disconnect(admin=Depends(admin_user)):
    await db.integrations.delete_one({"key": GCHAT_KEY})
    await db.conversations.update_many({}, {"$set": {"gchat_two_way": False}})
    return {"ok": True}


class TwoWayIn(BaseModel):
    enabled: bool


@router.put("/channels/{conv_id}/google-chat/two-way")
async def set_two_way(conv_id: str, body: TwoWayIn, admin=Depends(admin_user)):
    conv = await db.conversations.find_one({"conversation_id": conv_id, "type": "channel"}, P)
    if not conv:
        raise HTTPException(404, "Channel not found")
    if body.enabled:
        if not conv.get("gchat_webhook") or not conv.get("gchat_space"):
            raise HTTPException(400, "Link this channel to a Google Chat space first")
    update = {"gchat_two_way": body.enabled}
    if body.enabled and not conv.get("gchat_two_way"):
        update["gchat_cursor"] = now().strftime("%Y-%m-%dT%H:%M:%S.%fZ")
    await db.conversations.update_one({"conversation_id": conv_id}, {"$set": update})
    return {"ok": True, "two_way": body.enabled}


async def pull_gchat_once():
    conn = await db.integrations.find_one({"key": GCHAT_KEY}, P)
    if not conn or not gs.drive_client_config():
        return
    convs = await db.conversations.find({"type": "channel", "gchat_two_way": True,
                                         "gchat_space": {"$ne": None}}, P).to_list(50)
    if not convs:
        return
    try:
        svc = await run_in_threadpool(gs.chat_service, conn["refresh_token"])
    except Exception as e:
        logger.error(f"Google Chat auth failed: {e}")
        await db.integrations.update_one({"key": GCHAT_KEY}, {"$set": {"last_error": "Google sign-in expired. "
                                                                                    "Please reconnect."}})
        return
    for conv in convs:
        try:
            items = await run_in_threadpool(gs.chat_new_messages, svc, conv["gchat_space"], conv["gchat_cursor"])
        except Exception as e:
            logger.error(f"Google Chat read failed for {conv['conversation_id']}: {e}")
            await db.integrations.update_one({"key": GCHAT_KEY}, {"$set": {
                "last_error": "Couldn't read the Google Chat space. Make sure the connected account is a member."}})
            continue
        cursor = conv["gchat_cursor"]
        for m in items:
            cursor = max(cursor, m.get("createTime", cursor))
            sender = m.get("sender") or {}
            text = (m.get("text") or m.get("argumentText") or "").strip()
            if sender.get("type") == "BOT" or not text:
                continue  # skip our own webhook posts (bot) and non-text messages
            if await db.messages.find_one({"gchat_name": m["name"]}):
                continue
            doc = {"message_id": new_id("msg"), "conversation_id": conv["conversation_id"],
                   "sender_id": f"gchat:{sender.get('name', '')}",
                   "sender_name": sender.get("displayName") or "Google Chat member", "sender_picture": None,
                   "text": text[:4000], "source": "google_chat", "gchat_name": m["name"], "created_at": now_iso()}
            await db.messages.insert_one(doc)
            await db.conversations.update_one({"conversation_id": conv["conversation_id"]}, {"$set": {
                "last_message": f"{doc['sender_name'].split(' ')[0]}: {text[:80]}", "last_at": doc["created_at"]}})
        await db.conversations.update_one({"conversation_id": conv["conversation_id"]},
                                          {"$set": {"gchat_cursor": cursor}})
    await db.integrations.update_one({"key": GCHAT_KEY}, {"$set": {"last_error": ""}})


async def gchat_loop():
    while True:
        try:
            await pull_gchat_once()
        except Exception as e:
            logger.error(f"Google Chat sync loop error: {e}")
        await asyncio.sleep(10)
