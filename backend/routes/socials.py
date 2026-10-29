"""Facebook, Instagram and LinkedIn feeds."""
from datetime import timedelta, timezone
from fastapi import APIRouter, Depends, HTTPException
import asyncio
import secrets
import time
from core import P, admin_user, all_user_ids, current_user, db, logger, new_id, notify, now, now_iso, result_page, spawn
import google_services as gs
import social_service as ss

router = APIRouter(prefix="/api")


SOCIAL_LABELS = {"facebook": "Facebook", "instagram": "Instagram", "linkedin": "LinkedIn"}


async def social_conn(key: str):
    return await db.integrations.find_one({"key": key}, P)


async def oauth_state_for(admin: dict, kind: str) -> str:
    state = secrets.token_urlsafe(32)
    await db.oauth_states.insert_one({"state": state, "user_id": admin["user_id"], "kind": kind, "created_at": now()})
    return state


async def take_state(state: str, kind: str):
    st = await db.oauth_states.find_one_and_delete({"state": state, "kind": kind})
    if not st:
        return None
    created = st["created_at"].replace(tzinfo=timezone.utc) if st["created_at"].tzinfo is None else st["created_at"]
    return st if now() - created <= timedelta(minutes=15) else None


@router.get("/socials")
async def socials(user=Depends(current_user)):
    meta, li = await social_conn("meta"), await social_conn("linkedin")
    posts = await db.updates.find({"source": {"$in": list(SOCIAL_LABELS)}}, P).sort("created_at", -1).to_list(30)
    status = {"meta": {"configured": ss.meta_configured(), "connected": bool(meta),
                       "name": (meta or {}).get("page_name", ""), "instagram": (meta or {}).get("ig_username", ""),
                       "last_error": (meta or {}).get("last_error", "")},
              "linkedin": {"configured": ss.linkedin_configured(), "connected": bool(li),
                           "name": (li or {}).get("org_name", ""), "last_error": (li or {}).get("last_error", "")}}
    if user["role"] == "admin":
        status["redirect_uris"] = {"meta": ss.redirect_uri("meta"), "linkedin": ss.redirect_uri("linkedin")}
    return {"links": ss.SOCIAL_LINKS, "posts": posts, "status": status}


@router.post("/integrations/{kind}/start")
async def social_start(kind: str, admin=Depends(admin_user)):
    if kind == "meta":
        if not ss.meta_configured():
            raise HTTPException(409, "Facebook app credentials are not set up yet")
        return {"authorization_url": ss.meta_auth_url(await oauth_state_for(admin, "meta"))}
    if kind == "linkedin":
        if not ss.linkedin_configured():
            raise HTTPException(409, "LinkedIn app credentials are not set up yet")
        return {"authorization_url": ss.linkedin_auth_url(await oauth_state_for(admin, "linkedin"))}
    raise HTTPException(404, "Unknown integration")


@router.get("/integrations/meta/callback")
async def meta_callback(state: str = "", code: str = "", error: str = ""):
    st = await take_state(state, "meta")
    if error or not st or not code:
        return result_page("Facebook not connected", "The request was cancelled or expired.")
    try:
        info = await ss.meta_exchange(code)
    except Exception as e:
        logger.error(f"Meta OAuth failed: {e}")
        return result_page("Facebook not connected", "Couldn't read your Facebook Page. Make sure you manage the "
                                                     "Page and allow No Limitts to see it.")
    await db.integrations.update_one({"key": "meta"}, {"$set": {
        "key": "meta", "page_id": info["page_id"], "page_name": info["page_name"],
        "page_token": gs.encrypt(info["page_token"]), "ig_user_id": info["ig_user_id"],
        "ig_username": info["ig_username"], "connected_by": st["user_id"], "last_error": "",
        "initial_sync_done": False, "updated_at": now_iso()}}, upsert=True)
    spawn(sync_socials())
    extra = f" and Instagram @{info['ig_username']}" if info["ig_username"] else ""
    return result_page("Facebook connected", f"No Limitts will share new posts from {info['page_name']}{extra}.")


@router.get("/integrations/linkedin/callback")
async def linkedin_callback(state: str = "", code: str = "", error: str = ""):
    st = await take_state(state, "linkedin")
    if error or not st or not code:
        return result_page("LinkedIn not connected", "The request was cancelled or expired.")
    try:
        info = await ss.linkedin_exchange(code)
    except Exception as e:
        logger.error(f"LinkedIn OAuth failed: {e}")
        return result_page("LinkedIn not connected", "Couldn't read the company page. Make sure you're an admin of "
                                                     "the LinkedIn page.")
    await db.integrations.update_one({"key": "linkedin"}, {"$set": {
        "key": "linkedin", "access_token": gs.encrypt(info["access_token"]),
        "refresh_token": gs.encrypt(info["refresh_token"]) if info.get("refresh_token") else None,
        "expires_at": info["expires_at"], "org_urn": info["org_urn"], "org_name": info["org_name"],
        "connected_by": st["user_id"], "last_error": "", "initial_sync_done": False, "updated_at": now_iso()}},
        upsert=True)
    spawn(sync_socials())
    return result_page("LinkedIn connected", "No Limitts will share new LinkedIn company posts.")


@router.delete("/integrations/{kind}")
async def social_disconnect(kind: str, admin=Depends(admin_user)):
    if kind not in ("meta", "linkedin"):
        raise HTTPException(404, "Unknown integration")
    await db.integrations.delete_one({"key": kind})
    return {"ok": True}


@router.post("/socials/sync")
async def socials_sync_now(admin=Depends(admin_user)):
    return {"imported": await sync_socials()}


async def import_social_posts(posts: list, notify_new: bool) -> int:
    added = 0
    for p in posts:
        if not p.get("external_id") or await db.updates.find_one({"source": p["source"],
                                                                  "external_id": p["external_id"]}):
            continue
        label = SOCIAL_LABELS[p["source"]]
        text = (p.get("text") or "").strip()
        title = text.split("\n")[0][:90] if text else f"New {label} post"
        doc = {"update_id": new_id("upd"), "title": title, "body": text, "pinned": False,
               "author_id": "social", "author_name": f"Aspire & Grow on {label}", "source": p["source"],
               "external_id": p["external_id"], "link": p.get("link"), "image_url": p.get("image_url"),
               "created_at": p.get("published_at") or now_iso()}
        await db.updates.insert_one(dict(doc))
        added += 1
        if notify_new:
            await notify(await all_user_ids(), "update", f"New {label} post", title, "/updates")
    return added


async def sync_socials() -> int:
    total = 0
    meta = await social_conn("meta")
    if meta:
        try:
            posts = await ss.meta_posts(meta["page_id"], meta.get("ig_user_id"), gs.decrypt(meta["page_token"]))
            first = not meta.get("initial_sync_done")
            total += await import_social_posts(posts[:3] if first else posts, notify_new=not first)
            await db.integrations.update_one({"key": "meta"}, {"$set": {"initial_sync_done": True, "last_error": "",
                                                                       "last_sync": now_iso()}})
            if first:  # remember the rest without posting old content
                for p in posts[3:]:
                    await db.social_seen.update_one({"external_id": p["external_id"]}, {"$set": p}, upsert=True)
        except Exception as e:
            logger.error(f"Meta sync failed: {e}")
            await db.integrations.update_one({"key": "meta"}, {"$set": {
                "last_error": "Couldn't read Facebook/Instagram posts. An admin may need to reconnect."}})
    li = await social_conn("linkedin")
    if li:
        try:
            token = gs.decrypt(li["access_token"])
            if li.get("expires_at", 0) < time.time() + 3600 and li.get("refresh_token"):
                fresh = await ss.linkedin_refresh(gs.decrypt(li["refresh_token"]))
                token = fresh["access_token"]
                await db.integrations.update_one({"key": "linkedin"}, {"$set": {
                    "access_token": gs.encrypt(token), "refresh_token": gs.encrypt(fresh["refresh_token"]),
                    "expires_at": fresh["expires_at"]}})
            posts = await ss.linkedin_posts(token, li["org_urn"])
            first = not li.get("initial_sync_done")
            total += await import_social_posts(posts[:3] if first else posts, notify_new=not first)
            await db.integrations.update_one({"key": "linkedin"}, {"$set": {"initial_sync_done": True,
                                                                           "last_error": "", "last_sync": now_iso()}})
        except Exception as e:
            logger.error(f"LinkedIn sync failed: {e}")
            await db.integrations.update_one({"key": "linkedin"}, {"$set": {
                "last_error": "Couldn't read LinkedIn posts. An admin may need to reconnect."}})
    return total


async def socials_loop():
    while True:
        try:
            await sync_socials()
        except Exception as e:
            logger.error(f"Socials loop error: {e}")
        await asyncio.sleep(900)
