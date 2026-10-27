from fastapi import FastAPI, APIRouter, Request, HTTPException, Depends, UploadFile, File, Form
from fastapi.responses import Response, StreamingResponse, HTMLResponse
from fastapi.concurrency import run_in_threadpool
import json
import re
import secrets
from dotenv import load_dotenv
from starlette.middleware.cors import CORSMiddleware
from motor.motor_asyncio import AsyncIOMotorClient
import os
import asyncio
import logging
from html import escape
from pathlib import Path
from pydantic import BaseModel
from typing import Optional, List
import uuid
import httpx
from datetime import datetime, timezone, timedelta, date
from zoneinfo import ZoneInfo

ROOT_DIR = Path(__file__).parent
load_dotenv(ROOT_DIR / '.env')

from storage import init_storage, put_object, get_object, APP_NAME  # noqa: E402
from email_service import send_email, EMAIL_FROM_NAME  # noqa: E402
import google_services as gs  # noqa: E402
import ai_service  # noqa: E402
import social_service as ss  # noqa: E402
import time  # noqa: E402

mongo_url = os.environ['MONGO_URL']
client = AsyncIOMotorClient(mongo_url)
db = client[os.environ['DB_NAME']]

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

app = FastAPI()
EXPIRY_WARNING_DAYS = 30
MAX_UPLOAD_BYTES = 15 * 1024 * 1024


@app.get("/health", include_in_schema=False)
@app.head("/health", include_in_schema=False)
async def health():
    return {"status": "ok"}


api = APIRouter(prefix="/api")
P = {"_id": 0}


def now():
    return datetime.now(timezone.utc)


def now_iso():
    return now().isoformat()


def new_id(prefix: str):
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


_bg_tasks = set()


def spawn(coro):
    t = asyncio.create_task(coro)
    _bg_tasks.add(t)
    t.add_done_callback(_bg_tasks.discard)


# ---------------------------------------------------------------- auth
async def user_from_token(token: Optional[str]):
    if not token:
        return None
    sess = await db.user_sessions.find_one({"session_token": token}, P)
    if not sess:
        return None
    exp = sess["expires_at"]
    if exp.tzinfo is None:
        exp = exp.replace(tzinfo=timezone.utc)
    if exp < now():
        return None
    return await db.users.find_one({"user_id": sess["user_id"]}, P)


def bearer(request: Request) -> Optional[str]:
    auth = request.headers.get("Authorization", "")
    return auth[7:] if auth.startswith("Bearer ") else None


async def current_user(request: Request):
    user = await user_from_token(bearer(request))
    if not user:
        raise HTTPException(status_code=401, detail="Not authenticated")
    return user


async def admin_user(user=Depends(current_user)):
    if user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="Admins only")
    return user


class SessionIn(BaseModel):
    session_id: str


@api.post("/auth/session")
async def auth_session(body: SessionIn):
    async with httpx.AsyncClient(timeout=20) as c:
        r = await c.get("https://demobackend.emergentagent.com/auth/v1/env/oauth/session-data",
                        headers={"X-Session-ID": body.session_id})
    if r.status_code != 200:
        raise HTTPException(status_code=401, detail="Invalid session")
    data = r.json()
    email = data["email"].strip().lower()
    admin_emails = {e.strip().lower() for e in os.environ.get("ADMIN_EMAILS", "").split(",") if e.strip()}
    existing = await db.users.find_one({"email": email}, P)
    if existing:
        upd = {"name": data.get("name") or existing["name"], "picture": data.get("picture")}
        if email.lower() in admin_emails:
            upd["role"] = "admin"
        await db.users.update_one({"email": email}, {"$set": upd})
        user_id = existing["user_id"]
    else:
        is_first = await db.users.count_documents({"email": {"$not": {"$regex": "@example\\.com$"}}}) == 0
        user_id = new_id("user")
        await db.users.insert_one({"user_id": user_id, "email": email, "name": data.get("name") or email,
                                   "picture": data.get("picture"),
                                   "role": "admin" if (is_first or email.lower() in admin_emails) else "employee",
                                   "job_title": "", "created_at": now_iso()})
    token = data["session_token"]
    await db.user_sessions.insert_one({"session_token": token, "user_id": user_id,
                                       "expires_at": now() + timedelta(days=7), "created_at": now()})
    user = await db.users.find_one({"user_id": user_id}, P)
    return {"session_token": token, "user": user}


@api.get("/auth/me")
async def auth_me(user=Depends(current_user)):
    return user


@api.post("/auth/logout")
async def logout(request: Request):
    token = bearer(request)
    if token:
        await db.user_sessions.delete_one({"session_token": token})
    return {"ok": True}


# ---------------------------------------------------------------- users
HIDDEN_TEST_USERS = ["user_testadmin01", "user_testemp001"]


@api.get("/users")
async def list_users(user=Depends(current_user)):
    return await db.users.find({"hidden": {"$ne": True}}, P).sort("name", 1).to_list(1000)


class RoleIn(BaseModel):
    role: str


class StaffGroupIn(BaseModel):
    staff_group: Optional[str] = None


@api.patch("/users/{user_id}/group")
async def set_staff_group(user_id: str, body: StaffGroupIn, admin=Depends(admin_user)):
    if body.staff_group is not None and body.staff_group not in STAFF_GROUPS:
        raise HTTPException(400, "Unknown staff group")
    res = await db.users.update_one({"user_id": user_id}, {"$set": {"staff_group": body.staff_group}})
    if not res.matched_count:
        raise HTTPException(404, "User not found")
    return await db.users.find_one({"user_id": user_id}, P)


@api.patch("/users/{user_id}/role")
async def set_role(user_id: str, body: RoleIn, admin=Depends(admin_user)):
    if body.role not in ("admin", "employee"):
        raise HTTPException(400, "Invalid role")
    if user_id == admin["user_id"] and body.role != "admin":
        raise HTTPException(400, "You cannot remove your own admin role")
    res = await db.users.update_one({"user_id": user_id}, {"$set": {"role": body.role}})
    if not res.matched_count:
        raise HTTPException(404, "User not found")
    return await db.users.find_one({"user_id": user_id}, P)


# ---------------------------------------------------------------- notifications
async def notify(user_ids: List[str], ntype: str, title: str, body: str, link: str = ""):
    if not user_ids:
        return
    docs = [{"notification_id": new_id("ntf"), "user_id": uid, "type": ntype, "title": title, "body": body,
             "link": link, "read": False, "created_at": now_iso()} for uid in user_ids]
    await db.notifications.insert_many(docs)


async def all_user_ids(exclude: Optional[str] = None):
    users = await db.users.find({}, {"_id": 0, "user_id": 1}).to_list(5000)
    return [u["user_id"] for u in users if u["user_id"] != exclude]


@api.get("/notifications")
async def list_notifications(user=Depends(current_user)):
    return await db.notifications.find({"user_id": user["user_id"]}, P).sort("created_at", -1).to_list(200)


@api.post("/notifications/read-all")
async def read_all(user=Depends(current_user)):
    await db.notifications.update_many({"user_id": user["user_id"], "read": False}, {"$set": {"read": True}})
    return {"ok": True}


@api.post("/notifications/{nid}/read")
async def read_one(nid: str, user=Depends(current_user)):
    await db.notifications.update_one({"notification_id": nid, "user_id": user["user_id"]}, {"$set": {"read": True}})
    return {"ok": True}


# ---------------------------------------------------------------- certificates
def cert_status(expiry: str) -> dict:
    try:
        d = date.fromisoformat(expiry)
    except ValueError:
        return {"status": "valid", "days_left": None}
    days = (d - date.today()).days
    if days < 0:
        s = "expired"
    elif days <= EXPIRY_WARNING_DAYS:
        s = "expiring"
    else:
        s = "valid"
    return {"status": s, "days_left": days}


def with_status(c: dict) -> dict:
    c = {k: v for k, v in c.items() if k != "storage_path"}
    c.update(cert_status(c["expiry_date"]))
    return c


def expiry_email_html(name: str, title: str, expiry: str, status: str, days: int) -> str:
    if status == "expired":
        line = f"Your certificate <strong>{escape(title)}</strong> expired on {escape(expiry)}."
    else:
        line = (f"Your certificate <strong>{escape(title)}</strong> expires on {escape(expiry)} "
                f"({days} day{'s' if days != 1 else ''} left).")
    return (f'<table role="presentation" width="100%"><tr><td style="padding:24px;font-family:Arial,sans-serif;'
            f'color:#11181C"><p>Hi {escape(name)},</p><p>{line}</p>'
            f'<p>Please renew it and upload the new certificate in the {escape(EMAIL_FROM_NAME)} app.</p>'
            f'<p style="font-size:12px;color:#888">Sent by {escape(EMAIL_FROM_NAME)}. We never ask for your '
            f'password by email.</p></td></tr></table>')


async def check_certificate(cert: dict):
    st = cert_status(cert["expiry_date"])
    stage = st["status"]
    if stage == "valid" or cert.get("notified_stage") == stage:
        return
    await db.certificates.update_one({"cert_id": cert["cert_id"]}, {"$set": {"notified_stage": stage}})
    title = f"Certificate {'expired' if stage == 'expired' else 'expiring soon'}"
    body = (f"{cert['title']} expired on {cert['expiry_date']}" if stage == "expired"
            else f"{cert['title']} expires in {st['days_left']} days ({cert['expiry_date']})")
    await notify([cert["owner_id"]], "certificate", title, body, "/(tabs)/certificates")
    owner = await db.users.find_one({"user_id": cert["owner_id"]}, P)
    if owner and owner.get("email"):
        subject = f"{title}: {cert['title']}"
        await send_email(to=owner["email"], subject=subject,
                         html=expiry_email_html(owner["name"], cert["title"], cert["expiry_date"], stage,
                                                st["days_left"] or 0))


async def check_all_certificates():
    certs = await db.certificates.find({"is_deleted": False}, P).to_list(10000)
    for c in certs:
        try:
            await check_certificate(c)
        except Exception as e:
            logger.error(f"expiry check failed for {c.get('cert_id')}: {e}")


async def expiry_loop():
    while True:
        await check_all_certificates()
        await asyncio.sleep(6 * 3600)


@api.get("/certificates")
async def list_certificates(scope: str = "mine", user=Depends(current_user)):
    q = {"is_deleted": False}
    if scope == "all":
        if user["role"] != "admin":
            raise HTTPException(403, "Admins only")
    else:
        q["owner_id"] = user["user_id"]
    certs = [with_status(c) for c in await db.certificates.find(q, P).to_list(5000)]
    order = {"expired": 0, "expiring": 1, "valid": 2}
    certs.sort(key=lambda c: (order[c["status"]], c["expiry_date"]))
    return certs


@api.post("/certificates")
async def upload_certificate(title: str = Form(...), expiry_date: str = Form(...), issuer: str = Form(""),
                             issue_date: str = Form(""), file: UploadFile = File(...),
                             user=Depends(current_user)):
    title = title.strip()
    if not title:
        raise HTTPException(400, "Title is required")
    try:
        date.fromisoformat(expiry_date)
        if issue_date:
            date.fromisoformat(issue_date)
    except ValueError:
        raise HTTPException(400, "Dates must be YYYY-MM-DD")
    data = await file.read()
    if not data:
        raise HTTPException(400, "Empty file")
    if len(data) > MAX_UPLOAD_BYTES:
        raise HTTPException(413, "File too large (max 15 MB)")
    ext = (file.filename or "file").rsplit(".", 1)[-1].lower() if "." in (file.filename or "") else "bin"
    path = f"{APP_NAME}/uploads/{user['user_id']}/{uuid.uuid4().hex}.{ext}"
    ctype = file.content_type or "application/octet-stream"
    try:
        result = await run_in_threadpool(put_object, path, data, ctype)
    except Exception as e:
        logger.error(f"upload failed: {e}")
        raise HTTPException(502, "Could not store the file, please try again")
    cert = {"cert_id": new_id("cert"), "owner_id": user["user_id"], "owner_name": user["name"], "title": title,
            "issuer": issuer.strip(), "issue_date": issue_date, "expiry_date": expiry_date,
            "storage_path": result["path"], "file_name": file.filename or "certificate", "content_type": ctype,
            "size": len(data), "is_deleted": False, "notified_stage": "valid", "created_at": now_iso()}
    await db.certificates.insert_one(dict(cert))
    spawn(copy_cert_to_drive(cert, data))
    await check_certificate(cert)
    cert["notified_stage"] = cert_status(expiry_date)["status"]
    return with_status(cert)


@api.delete("/certificates/{cert_id}")
async def delete_certificate(cert_id: str, user=Depends(current_user)):
    q = {"cert_id": cert_id, "is_deleted": False}
    if user["role"] != "admin":
        q["owner_id"] = user["user_id"]
    res = await db.certificates.update_one(q, {"$set": {"is_deleted": True}})
    if not res.matched_count:
        raise HTTPException(404, "Certificate not found")
    return {"ok": True}


@api.get("/files/{cert_id}")
async def download_certificate(cert_id: str, request: Request, token: Optional[str] = None):
    user = await user_from_token(bearer(request) or token)
    if not user:
        raise HTTPException(401, "Not authenticated")
    cert = await db.certificates.find_one({"cert_id": cert_id, "is_deleted": False}, P)
    if not cert or (cert["owner_id"] != user["user_id"] and user["role"] != "admin"):
        raise HTTPException(404, "File not found")
    data, ctype = await run_in_threadpool(get_object, cert["storage_path"])
    return Response(content=data, media_type=cert.get("content_type") or ctype,
                    headers={"Content-Disposition": f'inline; filename="{cert["file_name"]}"'})


# ---------------------------------------------------------------- chat
async def conv_for_user(conv_id: str, user: dict):
    conv = await db.conversations.find_one({"conversation_id": conv_id}, P)
    if not conv or (conv["type"] == "dm" and user["user_id"] not in conv["member_ids"]):
        raise HTTPException(404, "Conversation not found")
    return conv


@api.get("/conversations")
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
        c["google_chat"] = bool(c.pop("gchat_webhook", None))
        c["google_chat_two_way"] = bool(c.pop("gchat_two_way", False))
        c.pop("gchat_space", None)
        c.pop("gchat_cursor", None)
        out.append(c)
    out.sort(key=lambda c: c.get("last_at") or c.get("created_at"), reverse=True)
    return out


class ChannelIn(BaseModel):
    name: str
    description: str = ""


@api.post("/channels")
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


@api.post("/dms")
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


@api.get("/conversations/{conv_id}/messages")
async def get_messages(conv_id: str, after: str = "", user=Depends(current_user)):
    await conv_for_user(conv_id, user)
    q = {"conversation_id": conv_id}
    if after:
        q["created_at"] = {"$gt": after}
    msgs = await db.messages.find(q, P).sort("created_at", -1).to_list(200)
    return list(reversed(msgs))


class MessageIn(BaseModel):
    text: str


@api.post("/conversations/{conv_id}/messages")
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
    if conv["type"] == "channel" and conv.get("gchat_webhook"):
        try:
            hook = gs.decrypt(conv["gchat_webhook"])
            spawn(gs.post_to_gchat(hook, f"*{user['name']}* in #{conv['name']} (StaffHub):\n{text[:4000]}"))
        except Exception as e:
            logger.error(f"Google Chat webhook unusable for {conv_id}: {e}")
    if conv["type"] == "dm":
        others = [m for m in conv["member_ids"] if m != user["user_id"]]
        await notify(others, "message", f"New message from {user['name']}", text[:120], f"/chat/{conv_id}")
    return msg


@api.post("/conversations/{conv_id}/read")
async def mark_read(conv_id: str, user=Depends(current_user)):
    await conv_for_user(conv_id, user)
    await db.conv_reads.update_one({"user_id": user["user_id"], "conversation_id": conv_id},
                                   {"$set": {"last_read_at": now_iso()}}, upsert=True)
    return {"ok": True}


# ---------------------------------------------------------------- updates
class UpdateIn(BaseModel):
    title: str
    body: str
    pinned: bool = False


@api.get("/updates")
async def list_updates(user=Depends(current_user)):
    return await db.updates.find({}, P).sort([("pinned", -1), ("created_at", -1)]).to_list(200)


@api.post("/updates")
async def create_update(body: UpdateIn, admin=Depends(admin_user)):
    if not body.title.strip():
        raise HTTPException(400, "Title is required")
    doc = {"update_id": new_id("upd"), "title": body.title.strip(), "body": body.body.strip(),
           "pinned": body.pinned, "author_id": admin["user_id"], "author_name": admin["name"],
           "created_at": now_iso()}
    await db.updates.insert_one(dict(doc))
    await notify(await all_user_ids(admin["user_id"]), "update", "Company update", doc["title"], "/updates")
    return doc


@api.delete("/updates/{update_id}")
async def delete_update(update_id: str, admin=Depends(admin_user)):
    res = await db.updates.delete_one({"update_id": update_id})
    if not res.deleted_count:
        raise HTTPException(404, "Update not found")
    return {"ok": True}


# ---------------------------------------------------------------- policies
class PolicyIn(BaseModel):
    title: str
    category: str = "Policy"
    content: str
    drive_file_id: Optional[str] = None


@api.get("/policies")
async def list_policies(user=Depends(current_user)):
    docs = await db.policies.find({}, P).sort("created_at", -1).to_list(500)
    for d in docs:
        d["acknowledged"] = user["user_id"] in d.get("acknowledged_by", [])
        d["ack_count"] = len(d.get("acknowledged_by", []))
        d.pop("acknowledged_by", None)
    return docs


@api.post("/policies")
async def create_policy(body: PolicyIn, admin=Depends(admin_user)):
    if not body.title.strip() or not body.content.strip():
        raise HTTPException(400, "Title and content are required")
    cat = body.category if body.category in ("Policy", "Procedure") else "Policy"
    doc = {"policy_id": new_id("pol"), "title": body.title.strip(), "category": cat,
           "content": body.content.strip(), "author_name": admin["name"], "acknowledged_by": [admin["user_id"]],
           "drive_file": None, "created_at": now_iso()}
    if body.drive_file_id:
        svc = await drive_svc_or_409()
        try:
            f = await run_in_threadpool(gs.drive_get, svc, body.drive_file_id)
        except Exception:
            raise HTTPException(404, "Drive file not found or not accessible")
        doc["drive_file"] = {"id": f["id"], "name": f.get("name"), "link": f.get("webViewLink"),
                             "mime_type": f.get("mimeType")}
    await db.policies.insert_one(dict(doc))
    await notify(await all_user_ids(admin["user_id"]), "policy", f"New {cat.lower()}: please review",
                 doc["title"], "/policies")
    doc.pop("acknowledged_by")
    return {**doc, "acknowledged": True, "ack_count": 1}


@api.post("/policies/{policy_id}/acknowledge")
async def acknowledge_policy(policy_id: str, user=Depends(current_user)):
    res = await db.policies.update_one({"policy_id": policy_id}, {"$addToSet": {"acknowledged_by": user["user_id"]}})
    if not res.matched_count:
        raise HTTPException(404, "Policy not found")
    return {"ok": True}


# ---------------------------------------------------------------- events
class EventIn(BaseModel):
    title: str
    description: str = ""
    location: str = ""
    date: str
    time: str = ""


@api.get("/events")
async def list_events(user=Depends(current_user)):
    docs = await db.events.find({}, P).sort([("date", 1), ("time", 1)]).to_list(500)
    for d in docs:
        d["going"] = user["user_id"] in d.get("attendees", [])
        d["attendee_count"] = len(d.get("attendees", []))
        d.pop("attendees", None)
    return docs


@api.post("/events")
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
    await notify(await all_user_ids(admin["user_id"]), "event", "New event", f"{doc['title']} on {doc['date']}",
                 "/events")
    doc.pop("attendees")
    return {**doc, "going": False, "attendee_count": 0}


@api.post("/events/{event_id}/rsvp")
async def rsvp(event_id: str, user=Depends(current_user)):
    ev = await db.events.find_one({"event_id": event_id}, P)
    if not ev:
        raise HTTPException(404, "Event not found")
    going = user["user_id"] in ev.get("attendees", [])
    op = "$pull" if going else "$addToSet"
    await db.events.update_one({"event_id": event_id}, {op: {"attendees": user["user_id"]}})
    return {"going": not going}


# ---------------------------------------------------------------- tasks
class TaskIn(BaseModel):
    title: str
    description: str = ""
    due_date: str = ""
    assignee_id: str = ""  # user id, "all" (admins: everyone), or empty / own id for a private task


class TaskPatch(BaseModel):
    status: str


@api.get("/tasks")
async def list_tasks(scope: str = "mine", user=Depends(current_user)):
    if scope == "all" and user["role"] == "admin":
        q = {"$or": [{"private": {"$ne": True}}, {"assignee_id": user["user_id"]}]}
    else:
        q = {"assignee_id": user["user_id"]}
    docs = await db.tasks.find(q, P).to_list(3000)
    docs.sort(key=lambda t: (t["status"] == "done", t.get("due_date") or "9999"))
    return docs


@api.post("/tasks")
async def create_task(body: TaskIn, user=Depends(current_user)):
    if body.due_date:
        try:
            date.fromisoformat(body.due_date)
        except ValueError:
            raise HTTPException(400, "Due date must be YYYY-MM-DD")
    if not body.title.strip():
        raise HTTPException(400, "Title is required")
    is_admin = user["role"] == "admin"
    target = body.assignee_id or user["user_id"]
    if not is_admin and target != user["user_id"]:
        raise HTTPException(403, "You can only create tasks for yourself")
    if target == "all":
        assignees = await db.users.find({"hidden": {"$ne": True}}, P).to_list(2000)
    else:
        a = await db.users.find_one({"user_id": target}, P)
        if not a:
            raise HTTPException(404, "Assignee not found")
        assignees = [a]
    private = target == user["user_id"]
    group_id = new_id("tgrp") if target == "all" else None
    docs = []
    for a in assignees:
        doc = {"task_id": new_id("task"), "title": body.title.strip(), "description": body.description.strip(),
               "due_date": body.due_date, "assignee_id": a["user_id"], "assignee_name": a["name"],
               "status": "open", "created_by": user["name"], "created_by_id": user["user_id"],
               "private": private, "group_id": group_id, "created_at": now_iso()}
        await db.tasks.insert_one(dict(doc))
        docs.append(doc)
    others = [d["assignee_id"] for d in docs if d["assignee_id"] != user["user_id"]]
    if others:
        await notify(others, "task", "New task assigned", body.title.strip(), "/tasks")
    return docs[0] if len(docs) == 1 else {"created": len(docs), "group_id": group_id}


@api.delete("/tasks/{task_id}")
async def delete_task(task_id: str, user=Depends(current_user)):
    t = await db.tasks.find_one({"task_id": task_id}, P)
    if not t or not (t.get("created_by_id") == user["user_id"] or
                     (user["role"] == "admin" and not t.get("private"))):
        raise HTTPException(404, "Task not found")
    await db.tasks.delete_one({"task_id": task_id})
    return {"ok": True}


@api.patch("/tasks/{task_id}")
async def update_task(task_id: str, body: TaskPatch, user=Depends(current_user)):
    if body.status not in ("open", "done"):
        raise HTTPException(400, "Invalid status")
    q = {"task_id": task_id}
    if user["role"] != "admin":
        q["assignee_id"] = user["user_id"]
    else:
        q["$or"] = [{"private": {"$ne": True}}, {"assignee_id": user["user_id"]}]
    res = await db.tasks.update_one(q, {"$set": {"status": body.status}})
    if not res.matched_count:
        raise HTTPException(404, "Task not found")
    return await db.tasks.find_one({"task_id": task_id}, P)


# ---------------------------------------------------------------- dashboard
@api.get("/dashboard")
async def dashboard(user=Depends(current_user)):
    uid = user["user_id"]
    certs = [with_status(c) for c in await db.certificates.find({"owner_id": uid, "is_deleted": False}, P)
             .to_list(1000)]
    alerts = sorted([c for c in certs if c["status"] != "valid"], key=lambda c: c["expiry_date"])
    today = date.today().isoformat()
    events = await db.events.find({"date": {"$gte": today}}, {"_id": 0, "attendees": 0}).sort("date", 1).to_list(3)
    tasks = await db.tasks.find({"assignee_id": uid, "status": "open"}, P).to_list(100)
    tasks.sort(key=lambda t: t.get("due_date") or "9999")
    updates = await db.updates.find({}, P).sort([("pinned", -1), ("created_at", -1)]).to_list(3)
    unread = await db.notifications.count_documents({"user_id": uid, "read": False})
    pending_policies = await db.policies.count_documents({"acknowledged_by": {"$ne": uid}})
    return {"cert_alerts": alerts, "cert_total": len(certs), "events": events, "open_tasks": tasks[:5],
            "open_task_count": len(tasks), "updates": updates, "unread_notifications": unread,
            "pending_policies": pending_policies}


# ---------------------------------------------------------------- Google Drive integration
DRIVE_KEY = "google_drive"


async def drive_conn():
    return await db.integrations.find_one({"key": DRIVE_KEY}, P)


async def drive_svc_or_409():
    conn = await drive_conn()
    if not conn or not gs.drive_client_config():
        raise HTTPException(409, "Google Drive is not connected")
    try:
        return await run_in_threadpool(gs.drive_service, conn["refresh_token"])
    except Exception as e:
        logger.error(f"Drive auth failed: {e}")
        raise HTTPException(502, "Google Drive access failed. An admin may need to reconnect it.")


async def copy_cert_to_drive(cert: dict, data: bytes):
    conn = await drive_conn()
    if not conn or not gs.drive_client_config():
        return
    try:
        svc = await run_in_threadpool(gs.drive_service, conn["refresh_token"])
        name = f"{cert['owner_name']} - {cert['title']} (expires {cert['expiry_date']})"
        ext = cert["file_name"].rsplit(".", 1)[-1] if "." in cert["file_name"] else ""
        f = await run_in_threadpool(gs.drive_upload, svc, conn["folder_id"], f"{name}.{ext}" if ext else name,
                                    data, cert["content_type"])
        await db.certificates.update_one({"cert_id": cert["cert_id"]},
                                         {"$set": {"drive_file_id": f["id"], "drive_link": f.get("webViewLink")}})
    except Exception as e:
        logger.error(f"Drive copy failed for {cert['cert_id']}: {e}")


@api.get("/integrations/google-drive/status")
async def drive_status(user=Depends(current_user)):
    conn = await drive_conn()
    return {"configured": bool(gs.drive_client_config()), "connected": bool(conn),
            "email": (conn or {}).get("email", ""), "folder_name": gs.DRIVE_FOLDER_NAME,
            "shared_folder_id": (conn or {}).get("shared_folder_id"),
            "shared_folder_name": (conn or {}).get("shared_folder_name"),
            "redirect_uri": gs.drive_redirect_uri() if user["role"] == "admin" else None}


@api.post("/integrations/google-drive/start")
async def drive_start(admin=Depends(admin_user)):
    if not gs.drive_client_config():
        raise HTTPException(409, "Google Drive credentials are not set up yet")
    state = secrets.token_urlsafe(32)
    url, verifier = gs.drive_auth_url(state)
    await db.oauth_states.insert_one({"state": state, "user_id": admin["user_id"], "code_verifier": verifier,
                                      "created_at": now()})
    return {"authorization_url": url}


def result_page(title: str, msg: str) -> HTMLResponse:
    return HTMLResponse(f"<html><head><meta name='viewport' content='width=device-width,initial-scale=1'></head>"
                        f"<body style='font-family:Arial;padding:32px;text-align:center'><h2>{escape(title)}</h2>"
                        f"<p>{escape(msg)}</p><p>You can close this window and return to StaffHub.</p></body></html>")


@api.get("/integrations/google-drive/callback")
async def drive_callback(state: str = "", code: str = "", error: str = ""):
    st = await db.oauth_states.find_one_and_delete({"state": state})
    if error or not st or not code:
        return result_page("Google Drive not connected", "The request was cancelled or expired.")
    created = st["created_at"].replace(tzinfo=timezone.utc) if st["created_at"].tzinfo is None else st["created_at"]
    if now() - created > timedelta(minutes=15):
        return result_page("Google Drive not connected", "The request expired. Please try again.")
    try:
        refresh = await run_in_threadpool(gs.drive_exchange, state, code, st.get("code_verifier"))
        old = await drive_conn()
        enc = gs.encrypt(refresh) if refresh else (old or {}).get("refresh_token")
        if not enc:
            return result_page("Google Drive not connected", "Google did not grant offline access. Try again.")
        svc = await run_in_threadpool(gs.drive_service, enc)
        email = await run_in_threadpool(gs.drive_account_email, svc)
        folder_id = await run_in_threadpool(gs.drive_ensure_folder, svc)
    except Exception as e:
        logger.error(f"Drive OAuth failed: {e}")
        if "invalid_client" in str(e):
            return result_page("Google Drive not connected",
                               "Google rejected StaffHub's sign-in credentials (client ID or secret is wrong).")
        return result_page("Google Drive not connected", "Something went wrong while connecting.")
    await db.integrations.update_one({"key": DRIVE_KEY}, {"$set": {
        "key": DRIVE_KEY, "refresh_token": enc, "email": email, "folder_id": folder_id,
        "connected_by": st["user_id"], "updated_at": now_iso()}}, upsert=True)
    return result_page("Google Drive connected", f"StaffHub is now linked to {email}.")


@api.delete("/integrations/google-drive")
async def drive_disconnect(admin=Depends(admin_user)):
    await db.integrations.delete_one({"key": DRIVE_KEY})
    return {"ok": True}


@api.get("/drive/files")
async def drive_files(q: str = "", admin=Depends(admin_user)):
    svc = await drive_svc_or_409()
    try:
        return await run_in_threadpool(gs.drive_list, svc, q[:100])
    except Exception as e:
        logger.error(f"Drive list failed: {e}")
        raise HTTPException(502, "Could not list Google Drive files")


class SharedFolderIn(BaseModel):
    link: str


@api.put("/integrations/google-drive/shared-folder")
async def set_shared_folder(body: SharedFolderIn, admin=Depends(admin_user)):
    fid = gs.folder_id_from_link(body.link)
    if not fid:
        raise HTTPException(400, "Paste a Google Drive folder link")
    svc = await drive_svc_or_409()
    try:
        meta = await run_in_threadpool(gs.drive_get, svc, fid)
    except Exception as e:
        logger.error(f"Drive folder lookup failed: {e}")
        raise HTTPException(400, "Couldn't open that folder with the connected Google account")
    if meta["mimeType"] != gs.FOLDER_MIME:
        raise HTTPException(400, "That link is a file, not a folder")
    await db.integrations.update_one({"key": DRIVE_KEY}, {"$set": {"shared_folder_id": fid,
                                                                  "shared_folder_name": meta["name"]}})
    await db.drive_docs.delete_many({"root_id": {"$ne": fid}})
    await db.drive_pins.delete_many({"root_id": {"$ne": fid}})
    spawn(index_drive())
    return {"shared_folder_id": fid, "shared_folder_name": meta["name"]}


@api.delete("/integrations/google-drive/shared-folder")
async def clear_shared_folder(admin=Depends(admin_user)):
    await db.integrations.update_one({"key": DRIVE_KEY}, {"$unset": {"shared_folder_id": "",
                                                                    "shared_folder_name": ""}})
    await db.drive_docs.delete_many({})
    await db.drive_pins.delete_many({})
    return {"ok": True}


async def shared_root():
    conn = await drive_conn()
    if not conn or not conn.get("shared_folder_id"):
        raise HTTPException(409, "No company folder has been set up yet")
    return conn["shared_folder_id"], conn.get("shared_folder_name", "Company Drive")


def drive_item(f: dict) -> dict:
    return {"id": f["id"], "name": f["name"], "mime_type": f["mimeType"],
            "is_folder": f["mimeType"] == gs.FOLDER_MIME, "modified": f.get("modifiedTime", ""),
            "size": int(f["size"]) if f.get("size") else None}


# ---- Drive index for the AI assistant
drive_index_lock = asyncio.Lock()


async def index_drive():
    if drive_index_lock.locked():
        return
    async with drive_index_lock:
        conn = await drive_conn()
        root = (conn or {}).get("shared_folder_id")
        if not root:
            await db.drive_docs.delete_many({})
            return
        try:
            svc = await run_in_threadpool(gs.drive_service, conn["refresh_token"])
            files = [f for f in await run_in_threadpool(gs.drive_walk, svc, root) if gs.readable(f["mimeType"])]
        except Exception as e:
            logger.error(f"Drive index listing failed: {e}")
            return
        keep = []
        for f in files:
            keep.append(f["id"])
            old = await db.drive_docs.find_one({"file_id": f["id"], "root_id": root}, {"modified": 1})
            if old and old.get("modified") == f.get("modifiedTime"):
                continue
            try:
                text = await run_in_threadpool(gs.drive_text, svc, f)
            except Exception as e:
                logger.warning(f"Drive text failed for {f['name']}: {e}")
                text = ""
            await db.drive_docs.update_one({"file_id": f["id"]}, {"$set": {
                "file_id": f["id"], "root_id": root, "name": f["name"], "mime_type": f["mimeType"],
                "modified": f.get("modifiedTime"), "text": text, "indexed_at": now_iso()}}, upsert=True)
        await db.drive_docs.delete_many({"$or": [{"root_id": {"$ne": root}}, {"file_id": {"$nin": keep}}]})
        await db.meta.update_one({"key": "drive_index"}, {"$set": {"key": "drive_index", "last_run": now_iso(),
                                                                  "count": len(keep)}}, upsert=True)


async def drive_index_loop():
    while True:
        try:
            await index_drive()
        except Exception as e:
            logger.error(f"Drive index failed: {e}")
        await asyncio.sleep(4 * 3600)


@api.get("/drive/index-status")
async def drive_index_status(admin=Depends(admin_user)):
    m = await db.meta.find_one({"key": "drive_index"}, P) or {}
    return {"last_run": m.get("last_run"), "count": await db.drive_docs.count_documents({"text": {"$ne": ""}}),
            "running": drive_index_lock.locked()}


@api.post("/drive/reindex")
async def drive_reindex(admin=Depends(admin_user)):
    await shared_root()
    spawn(index_drive())
    return {"ok": True}


# ---- Pinned key files
class PinIn(BaseModel):
    file_id: str


@api.post("/drive/pins")
async def pin_file(body: PinIn, admin=Depends(admin_user)):
    root_id, _ = await shared_root()
    svc = await drive_svc_or_409()
    try:
        if not await run_in_threadpool(gs.drive_is_under, svc, body.file_id, root_id) or body.file_id == root_id:
            raise HTTPException(404, "File not found")
        meta = await run_in_threadpool(gs.drive_get, svc, body.file_id)
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(404, "File not found")
    await db.drive_pins.update_one({"file_id": body.file_id}, {"$set": {
        "file_id": body.file_id, "root_id": root_id, "name": meta["name"], "mime_type": meta["mimeType"],
        "pinned_by": admin["name"], "pinned_at": now_iso()}}, upsert=True)
    return {"ok": True}


@api.delete("/drive/pins/{file_id}")
async def unpin_file(file_id: str, admin=Depends(admin_user)):
    await db.drive_pins.delete_one({"file_id": file_id})
    return {"ok": True}


@api.get("/drive/shared")
async def shared_files(folder: str = "", q: str = "", user=Depends(current_user)):
    root_id, root_name = await shared_root()
    folder_id = folder or root_id
    svc = await drive_svc_or_409()
    try:
        if folder_id != root_id and not await run_in_threadpool(gs.drive_is_under, svc, folder_id, root_id):
            raise HTTPException(404, "Folder not found")
        q = q.strip()[:100]
        if q:
            items = await run_in_threadpool(gs.drive_search_under, svc, folder_id, q)
        else:
            items = await run_in_threadpool(gs.drive_children, svc, folder_id)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Shared drive list failed: {e}")
        raise HTTPException(502, "Could not load the company Drive folder")
    pins = await db.drive_pins.find({"root_id": root_id}, P).sort("pinned_at", -1).to_list(50)
    pin_ids = {p["file_id"] for p in pins}
    out = [{**drive_item(f), "pinned": f["id"] in pin_ids} for f in items]
    pinned = [{"id": p["file_id"], "name": p["name"], "mime_type": p["mime_type"],
               "is_folder": p["mime_type"] == gs.FOLDER_MIME, "modified": "", "size": None, "pinned": True}
              for p in pins]
    return {"root_id": root_id, "root_name": root_name, "folder_id": folder_id, "items": out, "pinned": pinned}


@api.get("/drive/shared/file/{file_id}")
async def shared_file(file_id: str, request: Request, token: Optional[str] = None):
    user = await user_from_token(bearer(request) or token)
    if not user:
        raise HTTPException(401, "Not authenticated")
    root_id, _ = await shared_root()
    svc = await drive_svc_or_409()
    try:
        if not await run_in_threadpool(gs.drive_is_under, svc, file_id, root_id):
            raise HTTPException(404, "File not found")
        name, mime, data = await run_in_threadpool(gs.drive_download, svc, file_id)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Shared drive download failed: {e}")
        raise HTTPException(502, "Could not open this file")
    safe = re.sub(r'[^A-Za-z0-9 ._()-]', "_", name)
    return Response(content=data, media_type=mime, headers={"Content-Disposition": f'inline; filename="{safe}"'})


# ---------------------------------------------------------------- Google Chat integration
class WebhookIn(BaseModel):
    webhook_url: str


@api.put("/channels/{conv_id}/google-chat")
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
    ok = await gs.post_to_gchat(url, f"StaffHub is now connected to #{conv['name']}. "
                                     "Messages posted there will appear here.")
    return {"ok": True, "test_delivered": ok}


@api.delete("/channels/{conv_id}/google-chat")
async def remove_gchat(conv_id: str, admin=Depends(admin_user)):
    res = await db.conversations.update_one({"conversation_id": conv_id, "type": "channel"},
                                            {"$unset": {"gchat_webhook": "", "gchat_space": "", "gchat_two_way": "",
                                                        "gchat_cursor": ""}})
    if not res.matched_count:
        raise HTTPException(404, "Channel not found")
    return {"ok": True}


# ---------------------------------------------------------------- Google Chat two-way (read via Chat API)
GCHAT_KEY = "google_chat_reader"


@api.get("/integrations/google-chat/status")
async def gchat_status(admin=Depends(admin_user)):
    conn = await db.integrations.find_one({"key": GCHAT_KEY}, P)
    return {"configured": bool(gs.drive_client_config()), "connected": bool(conn),
            "last_error": (conn or {}).get("last_error", ""), "redirect_uri": gs.redirect_uri("google-chat")}


class StartIn(BaseModel):
    login_hint: str = ""


@api.post("/integrations/google-chat/start")
async def gchat_start(body: Optional[StartIn] = None, admin=Depends(admin_user)):
    if not gs.drive_client_config():
        raise HTTPException(409, "Google sign-in credentials are not set up yet")
    state = secrets.token_urlsafe(32)
    url, verifier = gs.oauth_auth_url("google-chat", gs.CHAT_SCOPES, state, (body.login_hint if body else "")[:200])
    await db.oauth_states.insert_one({"state": state, "user_id": admin["user_id"], "code_verifier": verifier,
                                      "kind": "google-chat", "login_hint": (body.login_hint if body else ""),
                                      "created_at": now()})
    return {"authorization_url": url}


@api.get("/integrations/google-chat/callback")
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
                               "Google rejected StaffHub's sign-in credentials (client ID or secret is wrong). "
                               "Please re-enter them and try again.")
        return result_page("Google Chat not connected", "Something went wrong while connecting.")
    await db.integrations.update_one({"key": GCHAT_KEY}, {"$set": {
        "key": GCHAT_KEY, "refresh_token": enc, "last_error": "", "connected_by": st["user_id"],
        "login_hint": st.get("login_hint", ""), "updated_at": now_iso()}}, upsert=True)
    # start syncing from the moment of connection for channels already switched on
    await db.conversations.update_many({"gchat_two_way": True},
                                       {"$set": {"gchat_cursor": now().strftime("%Y-%m-%dT%H:%M:%S.%fZ")}})
    return result_page("Google Chat connected", "Replies from your Google Chat spaces can now flow into StaffHub.")


@api.post("/integrations/google-chat/events")
async def gchat_events(request: Request):
    """Endpoint required by the Google Chat API app configuration. StaffHub reads space messages via the
    Chat API (two-way sync), so interaction events are simply acknowledged."""
    return {}


@api.delete("/integrations/google-chat")
async def gchat_disconnect(admin=Depends(admin_user)):
    await db.integrations.delete_one({"key": GCHAT_KEY})
    await db.conversations.update_many({}, {"$set": {"gchat_two_way": False}})
    return {"ok": True}


class TwoWayIn(BaseModel):
    enabled: bool


@api.put("/channels/{conv_id}/google-chat/two-way")
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


# ---------------------------------------------------------------- Jotform forms
class FormIn(BaseModel):
    title: str
    url: str
    description: str = ""
    audiences: List[str] = []
    category: str = "Day-to-Day"


class FormPatch(BaseModel):
    title: Optional[str] = None
    url: Optional[str] = None
    description: Optional[str] = None
    audiences: Optional[List[str]] = None
    category: Optional[str] = None


FORM_CATEGORIES = ("Day-to-Day", "New Starter", "HR", "Compliance", "Referral Triage", "Therapy Triage",
                   "Support Office")


def clean_category(value: str) -> str:
    if value not in FORM_CATEGORIES:
        raise HTTPException(400, "Unknown form section")
    return value


STAFF_GROUPS = ("support_office", "therapist_employee", "therapist_contractor", "support_worker_employee",
                "support_worker_contractor")


def clean_audiences(values: List[str]) -> List[str]:
    if any(v not in STAFF_GROUPS for v in values):
        raise HTTPException(400, "Unknown staff group")
    return sorted(set(values))


def forms_query(user: dict) -> dict:
    if user.get("role") == "admin":
        return {}
    ors = [{"audiences": {"$size": 0}}, {"audiences": {"$exists": False}}]
    if user.get("staff_group"):
        ors.append({"audiences": user["staff_group"]})
    return {"$or": ors}


def normalize_jotform(url: str) -> Optional[str]:
    url = url.strip()
    if url.isdigit():
        return f"https://form.jotform.com/{url}"
    if not url.startswith("http"):
        url = "https://" + url
    host = (url.split("/")[2] if len(url.split("/")) > 2 else "").lower()
    if not url.startswith("https://") or not (host == "jotform.com" or host.endswith(".jotform.com")):
        return None
    return url


@api.get("/forms")
async def list_forms(user=Depends(current_user)):
    return await db.forms.find(forms_query(user), P).sort("created_at", -1).to_list(200)


@api.patch("/forms/{form_id}")
async def update_form(form_id: str, body: FormPatch, admin=Depends(admin_user)):
    upd = {}
    if body.title is not None:
        if not body.title.strip():
            raise HTTPException(400, "Title is required")
        upd["title"] = body.title.strip()
    if body.url is not None:
        url = normalize_jotform(body.url)
        if not url:
            raise HTTPException(400, "Paste a Jotform link (e.g. https://form.jotform.com/123...) or form ID")
        upd["url"] = url
    if body.description is not None:
        upd["description"] = body.description.strip()
    if body.audiences is not None:
        upd["audiences"] = clean_audiences(body.audiences)
    if body.category is not None:
        upd["category"] = clean_category(body.category)
    if not upd:
        raise HTTPException(400, "Nothing to update")
    res = await db.forms.update_one({"form_id": form_id}, {"$set": upd})
    if not res.matched_count:
        raise HTTPException(404, "Form not found")
    return await db.forms.find_one({"form_id": form_id}, P)


@api.post("/forms")
async def create_form(body: FormIn, admin=Depends(admin_user)):
    url = normalize_jotform(body.url)
    if not url:
        raise HTTPException(400, "Paste a Jotform link (e.g. https://form.jotform.com/123...) or form ID")
    if not body.title.strip():
        raise HTTPException(400, "Title is required")
    audiences = clean_audiences(body.audiences)
    doc = {"form_id": new_id("form"), "title": body.title.strip(), "description": body.description.strip(),
           "url": url, "audiences": audiences, "category": clean_category(body.category),
           "created_by": admin["name"], "created_at": now_iso()}
    await db.forms.insert_one(dict(doc))
    if audiences:
        users = await db.users.find({"$or": [{"role": "admin"}, {"staff_group": {"$in": audiences}}]},
                                    {"_id": 0, "user_id": 1}).to_list(5000)
        recipients = [u["user_id"] for u in users if u["user_id"] != admin["user_id"]]
    else:
        recipients = await all_user_ids(admin["user_id"])
    await notify(recipients, "form", "New form available", doc["title"], "/forms")
    return doc


@api.delete("/forms/{form_id}")
async def delete_form(form_id: str, admin=Depends(admin_user)):
    res = await db.forms.delete_one({"form_id": form_id})
    if not res.deleted_count:
        raise HTTPException(404, "Form not found")
    return {"ok": True}


# ---------------------------------------------------------------- Socials (Facebook, Instagram, LinkedIn)
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


@api.get("/socials")
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


@api.post("/integrations/{kind}/start")
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


@api.get("/integrations/meta/callback")
async def meta_callback(state: str = "", code: str = "", error: str = ""):
    st = await take_state(state, "meta")
    if error or not st or not code:
        return result_page("Facebook not connected", "The request was cancelled or expired.")
    try:
        info = await ss.meta_exchange(code)
    except Exception as e:
        logger.error(f"Meta OAuth failed: {e}")
        return result_page("Facebook not connected", "Couldn't read your Facebook Page. Make sure you manage the "
                                                     "Page and allow StaffHub to see it.")
    await db.integrations.update_one({"key": "meta"}, {"$set": {
        "key": "meta", "page_id": info["page_id"], "page_name": info["page_name"],
        "page_token": gs.encrypt(info["page_token"]), "ig_user_id": info["ig_user_id"],
        "ig_username": info["ig_username"], "connected_by": st["user_id"], "last_error": "",
        "initial_sync_done": False, "updated_at": now_iso()}}, upsert=True)
    spawn(sync_socials())
    extra = f" and Instagram @{info['ig_username']}" if info["ig_username"] else ""
    return result_page("Facebook connected", f"StaffHub will share new posts from {info['page_name']}{extra}.")


@api.get("/integrations/linkedin/callback")
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
    return result_page("LinkedIn connected", "StaffHub will share new LinkedIn company posts.")


@api.delete("/integrations/{kind}")
async def social_disconnect(kind: str, admin=Depends(admin_user)):
    if kind not in ("meta", "linkedin"):
        raise HTTPException(404, "Unknown integration")
    await db.integrations.delete_one({"key": kind})
    return {"ok": True}


@api.post("/socials/sync")
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


# ---------------------------------------------------------------- CPD
class CpdIn(BaseModel):
    title: str
    provider: str = ""
    date: str
    hours: float
    category: str = ""
    notes: str = ""


def cpd_year_start() -> str:
    return f"{date.today().year}-01-01"


@api.get("/cpd")
async def list_cpd(scope: str = "mine", user=Depends(current_user)):
    q = {} if scope == "all" and user["role"] == "admin" else {"user_id": user["user_id"]}
    logs = await db.cpd_logs.find(q, P).sort("date", -1).to_list(2000)
    year = cpd_year_start()
    mine_year = sum(lg["hours"] for lg in logs if lg["user_id"] == user["user_id"] and lg["date"] >= year)
    totals = {}
    if scope == "all" and user["role"] == "admin":
        for lg in logs:
            if lg["date"] >= year and lg["user_id"] not in HIDDEN_TEST_USERS:
                t = totals.setdefault(lg["user_id"], {"user_id": lg["user_id"], "user_name": lg["user_name"],
                                                      "hours": 0})
                t["hours"] += lg["hours"]
    return {"logs": logs, "year_hours": round(mine_year, 2), "year": date.today().year,
            "team_totals": sorted(totals.values(), key=lambda t: -t["hours"])}


@api.post("/cpd")
async def add_cpd(body: CpdIn, user=Depends(current_user)):
    if not body.title.strip():
        raise HTTPException(400, "Enter what you did")
    try:
        date.fromisoformat(body.date)
    except ValueError:
        raise HTTPException(400, "Date must be YYYY-MM-DD")
    if not (0 < body.hours <= 200):
        raise HTTPException(400, "Hours must be between 0 and 200")
    doc = {"log_id": new_id("cpd"), "user_id": user["user_id"], "user_name": user["name"],
           "title": body.title.strip()[:200], "provider": body.provider.strip()[:200], "date": body.date,
           "hours": round(body.hours, 2), "category": body.category.strip()[:60], "notes": body.notes.strip()[:2000],
           "created_at": now_iso()}
    await db.cpd_logs.insert_one(dict(doc))
    return doc


@api.delete("/cpd/{log_id}")
async def delete_cpd(log_id: str, user=Depends(current_user)):
    q = {"log_id": log_id}
    if user["role"] != "admin":
        q["user_id"] = user["user_id"]
    if not (await db.cpd_logs.delete_one(q)).deleted_count:
        raise HTTPException(404, "Entry not found")
    return {"ok": True}


class CpdResourceIn(BaseModel):
    title: str
    description: str = ""
    url: str = ""
    category: str = ""


@api.get("/cpd/resources")
async def list_cpd_resources(user=Depends(current_user)):
    return await db.cpd_resources.find({}, P).sort("created_at", -1).to_list(500)


@api.post("/cpd/resources")
async def add_cpd_resource(body: CpdResourceIn, admin=Depends(admin_user)):
    if not body.title.strip():
        raise HTTPException(400, "Enter a title")
    url = body.url.strip()
    if url and not url.startswith(("https://", "http://")):
        url = "https://" + url
    doc = {"resource_id": new_id("cpdr"), "title": body.title.strip()[:200], "description": body.description.strip()[:2000],
           "url": url[:1000], "category": body.category.strip()[:60], "created_by": admin["name"],
           "created_at": now_iso()}
    await db.cpd_resources.insert_one(dict(doc))
    await notify(await all_user_ids(admin["user_id"]), "update", "New CPD resource", doc["title"], "/cpd")
    return doc


@api.delete("/cpd/resources/{resource_id}")
async def delete_cpd_resource(resource_id: str, admin=Depends(admin_user)):
    await db.cpd_resources.delete_one({"resource_id": resource_id})
    return {"ok": True}


# ---------------------------------------------------------------- Claude AI
class AskIn(BaseModel):
    question: str


STOPWORDS = {"what", "when", "where", "which", "about", "should", "would", "could", "there", "their", "with",
             "from", "that", "this", "have", "does", "your", "what's", "how", "the", "and", "for", "are", "our"}


async def drive_context(question: str, budget: int = 50000) -> str:
    conn = await drive_conn()
    root = (conn or {}).get("shared_folder_id")
    if not root:
        return ""
    words = {w.rstrip("s") if len(w) > 4 else w
             for w in re.findall(r"[a-z0-9]{3,}", question.lower()) if w not in STOPWORDS}
    docs = await db.drive_docs.find({"root_id": root, "text": {"$ne": ""}},
                                    {"_id": 0, "name": 1, "text": 1}).to_list(400)
    if not docs:
        return ""
    names = "\n".join(f"- {d['name']}" for d in docs)

    def score(d):
        name, text = d["name"].lower(), d["text"].lower()
        return sum(name.count(w) * 5 + min(text.count(w), 20) for w in words)

    ranked = sorted(docs, key=score, reverse=True)
    out, total = [], 0
    for d in ranked:
        if words and score(d) == 0 and out:
            break
        chunk = f"### Drive file: {d['name']}\n{d['text'][:15000]}\n"
        if total + len(chunk) > budget:
            if out:
                break
            chunk = chunk[:budget]
        out.append(chunk)
        total += len(chunk)
    return f"All files in the folder ({len(docs)}):\n{names}\n\n" + "\n".join(out)


async def assistant_context(user: dict, question: str = "") -> str:
    pols = await db.policies.find({}, P).sort("created_at", -1).to_list(100)
    text, total = [], 0
    for p in pols:
        chunk = f"### {p['category']}: {p['title']}\n{p['content']}\n"
        total += len(chunk)
        if total > 60000:
            break
        text.append(chunk)
    certs = [with_status(c) for c in await db.certificates.find({"owner_id": user["user_id"], "is_deleted": False}, P)
             .to_list(100)]
    cert_lines = "\n".join(f"- {c['title']}: expires {c['expiry_date']} ({c['status']})" for c in certs) or "none"
    drive = await drive_context(question)
    return ("You are the StaffHub assistant for employees. Answer clearly and briefly using the company "
            "policies and procedures and the company Drive documents below. If the answer isn't in them, say so "
            "and suggest asking a manager. Name the policy or Drive file you used. Never invent policy rules.\n"
            f"Today's date: {date.today().isoformat()}. Employee: {user['name']}.\n"
            f"Employee's certificates:\n{cert_lines}\n\nCOMPANY POLICIES & PROCEDURES:\n" + "\n".join(text)
            + (f"\n\nCOMPANY DRIVE DOCUMENTS (most relevant):\n{drive}" if drive else ""))


@api.get("/ai/history")
async def ai_history(user=Depends(current_user)):
    return await db.ai_messages.find({"user_id": user["user_id"]}, P).sort("created_at", 1).to_list(200)


@api.delete("/ai/history")
async def ai_clear(user=Depends(current_user)):
    await db.ai_messages.delete_many({"user_id": user["user_id"]})
    return {"ok": True}


@api.post("/ai/ask")
async def ai_ask(body: AskIn, user=Depends(current_user)):
    q = body.question.strip()[:2000]
    if not q:
        raise HTTPException(400, "Ask a question")
    history = await db.ai_messages.find({"user_id": user["user_id"]}, P).sort("created_at", -1).to_list(8)
    convo = "\n".join(f"{'Employee' if m['role'] == 'user' else 'Assistant'}: {m['text']}" for m in reversed(history))
    prompt = (f"Earlier conversation:\n{convo}\n\n" if convo else "") + f"Employee question: {q}"
    system = await assistant_context(user, q)
    asked_at = now_iso()

    async def gen():
        parts = []
        try:
            async for delta in ai_service.stream_answer(system, prompt):
                parts.append(delta)
                yield f"data: {json.dumps({'delta': delta})}\n\n"
        except Exception as e:
            logger.error(f"AI stream failed: {e}")
            yield f"data: {json.dumps({'error': 'The assistant is unavailable right now. Please try again.'})}\n\n"
        answer = "".join(parts).strip()
        if answer:
            await db.ai_messages.insert_many([
                {"message_id": new_id("aim"), "user_id": user["user_id"], "role": "user", "text": q,
                 "created_at": asked_at},
                {"message_id": new_id("aim"), "user_id": user["user_id"], "role": "assistant", "text": answer,
                 "created_at": now_iso()}])
        yield f"data: {json.dumps({'done': True})}\n\n"

    return StreamingResponse(gen(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


SUMMARY_SYSTEM = ("You summarise workplace team chats for busy employees. Write a short summary in plain text "
                  "(no markdown symbols): start with 1-2 sentences on the main topics, then up to 6 bullet points "
                  "using '• ' covering key updates, decisions, and any action items with who owns them. "
                  "Be factual; never invent details. Do not mention clock times; refer to days only if useful.")


@api.post("/conversations/{conv_id}/summary")
async def summarise_conversation(conv_id: str, user=Depends(current_user)):
    conv = await conv_for_user(conv_id, user)
    msgs = await db.messages.find({"conversation_id": conv_id}, P).sort("created_at", -1).to_list(200)
    if len(msgs) < 2:
        raise HTTPException(400, "There aren't enough messages to summarise yet")
    msgs.reverse()
    lines, total = [], 0
    for m in reversed(msgs):
        line = f"[{m['created_at'][:10]}] {m.get('sender_name', 'Someone')}: {m['text']}"
        total += len(line)
        if total > 40000:
            break
        lines.append(line)
    lines.reverse()
    title = f"#{conv['name']}" if conv["type"] == "channel" else "a direct message"
    try:
        summary = await ai_service.answer(SUMMARY_SYSTEM, f"Summarise this chat from {title}:\n\n" + "\n".join(lines))
    except Exception as e:
        logger.error(f"Chat summary failed: {e}")
        raise HTTPException(502, "Couldn't summarise right now. Please try again.")
    return {"summary": summary.replace("**", "").strip(), "message_count": len(lines),
            "from": msgs[-len(lines)]["created_at"], "to": msgs[-1]["created_at"]}


# ---------------------------------------------------------------- Weekly chat digest (email)
DIGEST_TZ = ZoneInfo("Australia/Perth")
DIGEST_SYSTEM = ("You write a weekly recap of one workplace team chat channel for a Monday morning email. "
                 "Plain text only, no markdown symbols. Write 1 sentence overview, then up to 5 lines starting "
                 "with '• ' for key updates, wins, decisions and action items (with owners). Be factual and brief; "
                 "never invent details; do not mention clock times.")


async def build_digest() -> list:
    since = (now() - timedelta(days=7)).isoformat()
    out = []
    for ch in await db.conversations.find({"type": "channel"}, P).sort("name", 1).to_list(50):
        msgs = await db.messages.find({"conversation_id": ch["conversation_id"], "created_at": {"$gte": since}},
                                      P).sort("created_at", 1).to_list(400)
        if not msgs:
            continue
        lines = [f"{m.get('sender_name', 'Someone')}: {m['text'][:800]}" for m in msgs][-300:]
        try:
            summary = await ai_service.answer(DIGEST_SYSTEM, f"Channel #{ch['name']}, last 7 days:\n\n"
                                              + "\n".join(lines)[:40000])
        except Exception as e:
            logger.error(f"Digest summary failed for {ch['name']}: {e}")
            summary = f"{len(msgs)} new messages this week."
        out.append({"channel": ch["name"], "count": len(msgs), "summary": summary.replace("**", "").strip()})
    return out


def digest_email_html(name: str, sections: list) -> str:
    blocks = "".join(
        f"<div style='margin:0 0 20px;padding:16px;background:#E3F1FE;border-radius:12px'>"
        f"<h3 style='margin:0 0 4px;color:#205890'>#{escape(s['channel'])}</h3>"
        f"<p style='margin:0 0 8px;color:#6b7280;font-size:13px'>{s['count']} message{'s' if s['count'] != 1 else ''}</p>"
        f"<p style='margin:0;white-space:pre-line;color:#111827;line-height:1.5'>{escape(s['summary'])}</p></div>"
        for s in sections)
    return (f"<div style='font-family:Arial,sans-serif;max-width:560px;margin:0 auto;padding:24px'>"
            f"<h2 style='color:#205890;margin:0 0 8px'>Your weekly StaffHub recap</h2>"
            f"<p style='color:#374151'>Hi {escape(name.split(' ')[0] if name else 'there')}, here's what happened "
            f"in your team channels last week.</p>{blocks}"
            f"<p style='color:#6b7280;font-size:12px'>Summaries written by Claude AI. Open StaffHub for the full "
            f"conversations.</p></div>")


async def send_digest(only_user: Optional[dict] = None) -> dict:
    sections = await build_digest()
    if not sections:
        return {"sent": 0, "channels": 0}
    users = [only_user] if only_user else await db.users.find({"email": {"$regex": "@"}}, P).to_list(2000)
    sent = 0
    for u in users:
        if u["email"].endswith("@example.com"):
            continue
        if await send_email(to=u["email"], subject="Your weekly StaffHub recap",
                            html=digest_email_html(u.get("name", ""), sections)):
            sent += 1
    return {"sent": sent, "channels": len(sections)}


async def digest_loop():
    while True:
        try:
            local = datetime.now(DIGEST_TZ)
            if local.weekday() == 0 and local.hour >= 8:
                year, week, _ = local.isocalendar()
                key = f"digest_{year}_{week}"
                if not await db.meta.find_one({"key": key}):
                    await db.meta.insert_one({"key": key, "created_at": now_iso()})
                    res = await send_digest()
                    await db.meta.update_one({"key": key}, {"$set": res})
                    logger.info(f"Weekly digest sent: {res}")
        except Exception as e:
            logger.error(f"Digest loop error: {e}")
        await asyncio.sleep(600)


@api.post("/digest/test")
async def digest_test(admin=Depends(admin_user)):
    """Admin preview: builds this week's digest and emails it only to the requesting admin."""
    res = await send_digest(only_user=admin)
    if not res["channels"]:
        raise HTTPException(400, "No channel messages in the last 7 days to summarise")
    return {**res, "email": admin["email"]}


@api.post("/ai/extract-certificate")
async def ai_extract(file: UploadFile = File(...), user=Depends(current_user)):
    data = await file.read()
    if not data or len(data) > MAX_UPLOAD_BYTES:
        raise HTTPException(400, "File is empty or too large")
    ctype = file.content_type or ""
    if not ("pdf" in ctype or ctype in ("image/png", "image/jpeg", "image/jpg", "image/webp")):
        raise HTTPException(415, "Use a PDF, JPG or PNG")
    try:
        return await ai_service.extract_certificate(data, ctype)
    except Exception as e:
        logger.error(f"AI extract failed: {e}")
        raise HTTPException(502, "Couldn't read the certificate. Please fill in the details manually.")


app.include_router(api)

app.add_middleware(CORSMiddleware, allow_credentials=True, allow_origins=["*"], allow_methods=["*"],
                   allow_headers=["*"])


async def seed_company_data():
    """One-time import of the company's forms and staff (admins, staff groups) into a fresh database,
    e.g. the first time the published app starts. Never re-runs, so later edits/deletes stick."""
    if await db.meta.find_one({"key": "company_seed_v1"}):
        return
    path = ROOT_DIR / "company_seed.json"
    if path.exists():
        data = json.loads(path.read_text())
        for f in data.get("forms", []):
            if not await db.forms.find_one({"url": f["url"]}):
                await db.forms.insert_one({"form_id": new_id("form"), **f, "created_by": "Andrew Thomas",
                                           "created_at": now_iso()})
        for u in data.get("users", []):
            existing = await db.users.find_one({"email": u["email"]})
            if existing:
                await db.users.update_one({"email": u["email"]}, {"$set": {"role": u["role"],
                                                                         "staff_group": u.get("staff_group")}})
            else:
                await db.users.insert_one({"user_id": new_id("user"), "email": u["email"], "name": u["name"],
                                           "picture": None, "role": u["role"], "staff_group": u.get("staff_group"),
                                           "job_title": "", "created_at": now_iso()})
    await db.meta.insert_one({"key": "company_seed_v1", "created_at": now_iso()})


async def seed_staff_v2():
    """One-time import of the team directory (contacts.csv): adds missing staff, sets full names and groups."""
    if await db.meta.find_one({"key": "company_staff_v2"}):
        return
    path = ROOT_DIR / "company_seed.json"
    data = json.loads(path.read_text()) if path.exists() else {}
    for u in data.get("staff_v2", []):
        existing = await db.users.find_one({"email": u["email"]})
        if existing:
            await db.users.update_one({"email": u["email"]}, {"$set": {"name": u["name"],
                                                                     "staff_group": u.get("staff_group")}})
        else:
            await db.users.insert_one({"user_id": new_id("user"), "email": u["email"], "name": u["name"],
                                       "picture": None, "role": u["role"], "staff_group": u.get("staff_group"),
                                       "job_title": "", "created_at": now_iso()})
    await db.meta.insert_one({"key": "company_staff_v2", "created_at": now_iso()})


async def seed():
    for name, desc in (("general", "Company-wide chat for everyone"),
                       ("announcements", "Important news and notices")):
        if not await db.conversations.find_one({"type": "channel", "$or": [{"seed_key": name}, {"name": name}]}):
            await db.conversations.insert_one({"conversation_id": new_id("conv"), "type": "channel", "name": name,
                                               "seed_key": name,
                                               "description": desc, "member_ids": [], "last_message": "",
                                               "last_at": "", "created_at": now_iso()})
    if await db.updates.count_documents({}) == 0:
        await db.updates.insert_one({"update_id": new_id("upd"), "title": "Welcome to StaffHub",
                                     "body": "This is a sample update. Admins can post company news here and "
                                             "everyone gets notified.", "pinned": True, "author_id": "system",
                                     "author_name": "StaffHub", "created_at": now_iso()})
    if await db.policies.count_documents({}) == 0:
        await db.policies.insert_one({"policy_id": new_id("pol"), "title": "Sample: Health & Safety Policy",
                                      "category": "Policy",
                                      "content": "This is sample policy text. Admins can replace it with your "
                                                 "real policies and procedures. Employees tap 'Acknowledge' once "
                                                 "they have read it.", "author_name": "StaffHub",
                                      "acknowledged_by": [], "created_at": now_iso()})


@app.on_event("startup")
async def startup():
    await db.users.create_index("email", unique=True)
    await db.users.create_index("user_id", unique=True)
    await db.user_sessions.create_index("session_token", unique=True)
    await db.user_sessions.create_index("user_id")
    await db.user_sessions.create_index("expires_at", expireAfterSeconds=0)
    await db.messages.create_index([("conversation_id", 1), ("created_at", -1)])
    await db.notifications.create_index([("user_id", 1), ("created_at", -1)])
    await db.messages.create_index("gchat_name", sparse=True)
    await seed()
    await seed_company_data()
    await seed_staff_v2()
    # internal test accounts stay usable but are hidden from staff everywhere
    await db.users.update_many({"user_id": {"$in": HIDDEN_TEST_USERS}}, {"$set": {"hidden": True}})
    # migrate the old single Support Office flag / audience to staff groups
    await db.users.update_many({"support_office": True}, {"$set": {"staff_group": "support_office"},
                                                          "$unset": {"support_office": ""}})
    await db.users.update_many({"support_office": {"$exists": True}}, {"$unset": {"support_office": ""}})
    await db.forms.update_many({"audience": "support_office"}, {"$set": {"audiences": ["support_office"]},
                                                                "$unset": {"audience": ""}})
    await db.forms.update_many({"audience": {"$exists": True}}, {"$set": {"audiences": []},
                                                                 "$unset": {"audience": ""}})
    await db.forms.update_many({"category": {"$exists": False}}, {"$set": {"category": "Day-to-Day"}})
    try:
        await run_in_threadpool(init_storage)
    except Exception as e:
        logger.error(f"Storage init failed: {e}")
    asyncio.create_task(expiry_loop())
    asyncio.create_task(gchat_loop())
    asyncio.create_task(drive_index_loop())
    asyncio.create_task(digest_loop())
    asyncio.create_task(socials_loop())


@app.on_event("shutdown")
async def shutdown_db_client():
    client.close()
