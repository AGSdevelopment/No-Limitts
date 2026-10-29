"""Birthdays & work anniversaries: today's list, a congratulations wall per celebration, and a week-ahead admin email."""
import asyncio
import calendar
import re
import uuid
from datetime import datetime, timedelta
from html import escape
from typing import Optional
from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import Response
from core import DIGEST_TZ, P, bearer, current_user, db, logger, new_id, notify, now_iso, user_from_token
from email_service import send_email
from storage import APP_NAME, get_object, put_object

router = APIRouter(prefix="/api")
KEY_RE = re.compile(r"^(birthday|anniversary)-([A-Za-z0-9_]+)-(\d{4})$")
PHOTO_TYPES = ("image/jpeg", "image/png", "image/heic", "image/heif", "image/webp", "image/gif")
MAX_PHOTO = 15 * 1024 * 1024


def day_keys(d) -> list:
    """MM-DD values celebrated on date d (29 Feb counts on 28 Feb in non-leap years)."""
    md = d.strftime("%m-%d")
    return [md] + (["02-29"] if md == "02-28" and not calendar.isleap(d.year) else [])


async def celebrations_on(d, include_hidden: bool) -> list:
    mds = day_keys(d)
    q = {} if include_hidden else {"hidden": {"$ne": True}}
    out = []
    async for u in db.users.find({**q, "$or": [{"birthday": {"$in": mds}}, {"start_date": {"$regex": f"-({'|'.join(mds)})$"}}]},
                                 {"_id": 0, "user_id": 1, "name": 1, "picture": 1, "birthday": 1, "start_date": 1}):
        base = {"user_id": u["user_id"], "name": u.get("name", ""), "picture": u.get("picture")}
        if u.get("birthday") in mds:
            out.append({**base, "type": "birthday", "key": f"birthday-{u['user_id']}-{d.year}"})
        sd = u.get("start_date") or ""
        if sd[5:] in mds and sd[:4].isdigit() and int(sd[:4]) < d.year:
            out.append({**base, "type": "anniversary", "years": d.year - int(sd[:4]), "key": f"anniversary-{u['user_id']}-{d.year}"})
    return out


async def celebrations(user: dict) -> list:
    """Today's celebrations (Perth time) with how many wall posts each has."""
    items = await celebrations_on(datetime.now(DIGEST_TZ).date(), bool(user.get("hidden")))
    for c in items:
        c["post_count"] = await db.celebration_posts.count_documents({"key": c["key"]})
    return items


async def celebrant(key: str, viewer: dict) -> dict:
    m = KEY_RE.match(key)
    if not m:
        raise HTTPException(404, "Celebration not found")
    u = await db.users.find_one({"user_id": m.group(2)}, {"_id": 0, "user_id": 1, "name": 1, "picture": 1, "start_date": 1, "hidden": 1})
    if not u or (u.get("hidden") and not viewer.get("hidden")):
        raise HTTPException(404, "Celebration not found")
    year = int(m.group(3))
    info = {"key": key, "type": m.group(1), "user_id": u["user_id"], "name": u.get("name", ""), "picture": u.get("picture"), "year": year}
    if m.group(1) == "anniversary" and (u.get("start_date") or "")[:4].isdigit():
        info["years"] = year - int(u["start_date"][:4])
    return info


def post_out(p: dict, viewer: dict) -> dict:
    p = {k: v for k, v in p.items() if k not in ("_id", "storage_path")}
    p["has_photo"] = bool(p.pop("content_type", None))
    p["can_delete"] = p["user_id"] == viewer["user_id"] or viewer.get("role") == "admin"
    return p


@router.get("/celebrations/{key}")
async def wall(key: str, user=Depends(current_user)):
    info = await celebrant(key, user)
    posts = await db.celebration_posts.find({"key": key}).sort("created_at", -1).to_list(300)
    return {**info, "posts": [post_out(p, user) for p in posts]}


@router.post("/celebrations/{key}/posts")
async def add_post(key: str, text: str = Form(""), file: Optional[UploadFile] = File(None), user=Depends(current_user)):
    info = await celebrant(key, user)
    text = text.strip()[:1000]
    data, ctype = b"", ""
    if file is not None:
        ctype = (file.content_type or "").lower()
        if ctype not in PHOTO_TYPES:
            raise HTTPException(400, "Photos only (JPG, PNG or HEIC)")
        data = await file.read()
        if len(data) > MAX_PHOTO:
            raise HTTPException(413, "Photo too large (max 15 MB)")
    if not text and not data:
        raise HTTPException(400, "Write a message or add a photo")
    post = {"post_id": new_id("cel"), "key": key, "user_id": user["user_id"], "name": user.get("name", ""),
            "picture": user.get("picture"), "text": text, "created_at": now_iso()}
    if data:
        ext = (file.filename or "").rsplit(".", 1)[-1].lower() if "." in (file.filename or "") else "jpg"
        path = f"{APP_NAME}/celebrations/{key}/{uuid.uuid4().hex}.{ext}"
        try:
            await run_in_threadpool(put_object, path, data, ctype)
        except Exception as e:
            logger.error(f"celebration photo upload failed: {e}")
            raise HTTPException(502, "Could not store the photo, please try again")
        post.update(storage_path=path, content_type=ctype)
    await db.celebration_posts.insert_one(dict(post))
    if info["user_id"] != user["user_id"]:
        what = "birthday" if info["type"] == "birthday" else "work anniversary"
        await notify([info["user_id"]], "celebration", f"{user.get('name', 'Someone')} left you a {what} message",
                     text[:120] or "They shared a photo on your celebration wall 🎉", f"/celebration/{key}")
    return post_out(post, user)


@router.get("/celebrations/{key}/posts/{post_id}/photo")
async def post_photo(key: str, post_id: str, request: Request, token: Optional[str] = None):
    user = await user_from_token(bearer(request) or token)
    if not user:
        raise HTTPException(401, "Not authenticated")
    await celebrant(key, user)
    post = await db.celebration_posts.find_one({"key": key, "post_id": post_id, "storage_path": {"$exists": True}})
    if not post:
        raise HTTPException(404, "Photo not found")
    data, ctype = await run_in_threadpool(get_object, post["storage_path"])
    return Response(content=data, media_type=post.get("content_type") or ctype,
                    headers={"Cache-Control": "private, max-age=86400", "X-Content-Type-Options": "nosniff"})


@router.delete("/celebrations/{key}/posts/{post_id}")
async def delete_post(key: str, post_id: str, user=Depends(current_user)):
    q = {"key": key, "post_id": post_id}
    if user.get("role") != "admin":
        q["user_id"] = user["user_id"]
    if not (await db.celebration_posts.delete_one(q)).deleted_count:
        raise HTTPException(404, "Message not found")
    return {"ok": True}


async def send_week_ahead(target) -> int:
    """Email (and notify) every admin about birthdays/anniversaries on `target`. Returns celebrations found."""
    items = await celebrations_on(target, include_hidden=False)
    if not items:
        return 0
    admins = await db.users.find({"role": "admin", "hidden": {"$ne": True}}, P).to_list(200)
    when = f"{target.strftime('%A')} {target.day} {target.strftime('%B')}"
    lines = [f"{c['name']}'s birthday" if c["type"] == "birthday"
             else f"{c['name']}'s {c['years']}-year work anniversary" for c in items]
    await notify([a["user_id"] for a in admins], "celebration", f"Coming up on {when}", "; ".join(lines)[:200], "/")
    rows = "".join(f"<li style='margin:6px 0'>{'🎂' if c['type'] == 'birthday' else '🎉'} <b>{escape(l)}</b></li>"
                   for c, l in zip(items, lines))
    for a in admins:
        if a.get("email") and not a["email"].endswith("@example.com"):
            await send_email(to=a["email"], subject=f"Celebrations coming up on {when}", html=(
                "<div style='font-family:Arial,sans-serif;max-width:520px;margin:0 auto;padding:24px'>"
                "<h2 style='color:#673E8D'>Celebrations next week</h2>"
                f"<p>Hi {escape(a['name'].split(' ')[0])},</p><p>One week from today, on <b>{when}</b>:</p>"
                f"<ul style='padding-left:18px'>{rows}</ul>"
                "<p>A great time to organise a card, cake or shout-out. On the day, everyone will see a banner "
                "on the No Limitts Home screen where they can leave messages and photos.</p></div>"))
    return len(items)


async def celebration_reminder_loop():
    """Hourly: one week-ahead email per date, and (from 8am Perth) today's celebrations posted to Teams.
    Both are claimed in meta so they never repeat."""
    while True:
        try:
            today = datetime.now(DIGEST_TZ)
            target = today.date() + timedelta(days=7)
            key = f"celebration_reminder_{target.isoformat()}"
            if not await db.meta.find_one({"key": key}):
                await db.meta.insert_one({"key": key, "created_at": now_iso()})
                n = await send_week_ahead(target)
                logger.info(f"Celebration reminder for {target}: {n} celebration(s)")
            tkey = f"celebration_teams_{today.date().isoformat()}"
            if today.hour >= 8 and not await db.meta.find_one({"key": tkey}):
                # claim only once everything posted, so a Teams outage retries next hour
                if await post_celebrations_to_teams(today.date()):
                    await db.meta.insert_one({"key": tkey, "created_at": now_iso()})
        except Exception as e:
            logger.error(f"Celebration reminder loop failed: {e}")
        await asyncio.sleep(3600)


async def post_celebrations_to_teams(d) -> bool:
    """Post each of the day's celebrations. True when done (or nothing to post / not linked)."""
    from routes.teams import announce, posted_keys  # local import keeps module load order simple
    items = await celebrations_on(d, include_hidden=False)
    ok = True
    for c in items:
        if c["key"] in await posted_keys():
            continue
        first = c["name"].split(" ")[0]
        text = (f"🎂 **Happy birthday, {c['name']}!**\n\nWishing {first} a wonderful day from all of us at No Limitts."
                if c["type"] == "birthday" else
                f"🎉 **{c['name']} celebrates {c['years']} year{'s' if c['years'] > 1 else ''} with No Limitts today!**\n\n"
                f"Thank you, {first}, for everything you do.")
        if await announce("celebrations", text + "\n\nLeave a message on their celebration wall in the No Limitts app."):
            await db.meta.update_one({"key": "teams_posted_celebrations"}, {"$addToSet": {"keys": c["key"]}}, upsert=True)
        else:
            ok = False
    return ok
