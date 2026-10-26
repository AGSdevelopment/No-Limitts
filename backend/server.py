from fastapi import FastAPI, APIRouter, Request, HTTPException, Depends, UploadFile, File, Form
from fastapi.responses import Response
from fastapi.concurrency import run_in_threadpool
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

ROOT_DIR = Path(__file__).parent
load_dotenv(ROOT_DIR / '.env')

from storage import init_storage, put_object, get_object, APP_NAME  # noqa: E402
from email_service import send_email, EMAIL_FROM_NAME  # noqa: E402

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
    email = data["email"]
    existing = await db.users.find_one({"email": email}, P)
    if existing:
        await db.users.update_one({"email": email}, {"$set": {"name": data.get("name") or existing["name"],
                                                              "picture": data.get("picture")}})
        user_id = existing["user_id"]
    else:
        is_first = await db.users.count_documents({}) == 0
        user_id = new_id("user")
        await db.users.insert_one({"user_id": user_id, "email": email, "name": data.get("name") or email,
                                   "picture": data.get("picture"), "role": "admin" if is_first else "employee",
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
@api.get("/users")
async def list_users(user=Depends(current_user)):
    return await db.users.find({}, P).sort("name", 1).to_list(1000)


class RoleIn(BaseModel):
    role: str


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
        out.append(c)
    out.sort(key=lambda c: c.get("last_at") or c.get("created_at"), reverse=True)
    return out


class ChannelIn(BaseModel):
    name: str
    description: str = ""


@api.post("/channels")
async def create_channel(body: ChannelIn, admin=Depends(admin_user)):
    name = body.name.strip().lower().replace(" ", "-").lstrip("#")
    if not name:
        raise HTTPException(400, "Name is required")
    if await db.conversations.find_one({"type": "channel", "name": name}):
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
           "created_at": now_iso()}
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
    assignee_id: str


class TaskPatch(BaseModel):
    status: str


@api.get("/tasks")
async def list_tasks(scope: str = "mine", user=Depends(current_user)):
    q = {}
    if scope != "all" or user["role"] != "admin":
        q["assignee_id"] = user["user_id"]
    docs = await db.tasks.find(q, P).to_list(1000)
    docs.sort(key=lambda t: (t["status"] == "done", t.get("due_date") or "9999"))
    return docs


@api.post("/tasks")
async def create_task(body: TaskIn, admin=Depends(admin_user)):
    assignee = await db.users.find_one({"user_id": body.assignee_id}, P)
    if not assignee:
        raise HTTPException(404, "Assignee not found")
    if body.due_date:
        try:
            date.fromisoformat(body.due_date)
        except ValueError:
            raise HTTPException(400, "Due date must be YYYY-MM-DD")
    if not body.title.strip():
        raise HTTPException(400, "Title is required")
    doc = {"task_id": new_id("task"), "title": body.title.strip(), "description": body.description.strip(),
           "due_date": body.due_date, "assignee_id": assignee["user_id"], "assignee_name": assignee["name"],
           "status": "open", "created_by": admin["name"], "created_at": now_iso()}
    await db.tasks.insert_one(dict(doc))
    if assignee["user_id"] != admin["user_id"]:
        await notify([assignee["user_id"]], "task", "New task assigned", doc["title"], "/tasks")
    return doc


@api.patch("/tasks/{task_id}")
async def update_task(task_id: str, body: TaskPatch, user=Depends(current_user)):
    if body.status not in ("open", "done"):
        raise HTTPException(400, "Invalid status")
    q = {"task_id": task_id}
    if user["role"] != "admin":
        q["assignee_id"] = user["user_id"]
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


app.include_router(api)

app.add_middleware(CORSMiddleware, allow_credentials=True, allow_origins=["*"], allow_methods=["*"],
                   allow_headers=["*"])


async def seed():
    for name, desc in (("general", "Company-wide chat for everyone"),
                       ("announcements", "Important news and notices")):
        if not await db.conversations.find_one({"type": "channel", "name": name}):
            await db.conversations.insert_one({"conversation_id": new_id("conv"), "type": "channel", "name": name,
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
    await seed()
    try:
        await run_in_threadpool(init_storage)
    except Exception as e:
        logger.error(f"Storage init failed: {e}")
    asyncio.create_task(expiry_loop())


@app.on_event("shutdown")
async def shutdown_db_client():
    client.close()
