"""Tasks, attachments and due-date reminders."""
from datetime import date, datetime, timedelta
from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import Response
from html import escape
from pydantic import BaseModel
from typing import List, Optional
import asyncio
import re
import uuid
from core import DIGEST_TZ, MAX_UPLOAD_BYTES, P, admin_user, bearer, current_user, db, dmy, logger, new_id, notify, now_iso, user_from_token
from email_service import send_email
from storage import APP_NAME, get_object, put_object

router = APIRouter(prefix="/api")


class TaskIn(BaseModel):
    title: str
    description: str = ""
    due_date: str = ""
    assignee_id: str = ""  # user id, "all" (admins: everyone), or empty / own id for a private task
    attachment_id: Optional[str] = None
    assignee_ids: List[str] = []  # admins: several people share one task (each gets their own copy)


@router.post("/tasks/attachments")
async def upload_task_attachment(file: UploadFile = File(...), user=Depends(current_user)):
    data = await file.read()
    if not data:
        raise HTTPException(400, "Empty file")
    if len(data) > MAX_UPLOAD_BYTES:
        raise HTTPException(413, "File too large (max 15 MB)")
    ext = (file.filename or "file").rsplit(".", 1)[-1].lower() if "." in (file.filename or "") else "bin"
    ctype = file.content_type or "application/octet-stream"
    try:
        result = await run_in_threadpool(put_object, f"{APP_NAME}/tasks/{user['user_id']}/{uuid.uuid4().hex}.{ext}",
                                         data, ctype)
    except Exception as e:
        logger.error(f"Task file upload failed: {e}")
        raise HTTPException(502, "Could not store the file, please try again")
    doc = {"file_id": new_id("tfile"), "storage_path": result["path"], "file_name": file.filename or "file",
           "content_type": ctype, "size": len(data), "uploaded_by": user["user_id"], "created_at": now_iso()}
    await db.task_files.insert_one(dict(doc))
    return {"file_id": doc["file_id"], "file_name": doc["file_name"]}


@router.get("/tasks/files/{file_id}")
async def task_file(file_id: str, request: Request, token: Optional[str] = None):
    user = await user_from_token(bearer(request) or token)
    if not user:
        raise HTTPException(401, "Not authenticated")
    f = await db.task_files.find_one({"file_id": file_id}, P)
    allowed = f and (user["role"] == "admin" or f["uploaded_by"] == user["user_id"] or await db.tasks.find_one(
        {"attachment.file_id": file_id, "assignee_id": user["user_id"]}))
    if not allowed:
        raise HTTPException(404, "File not found")
    data, ctype = await run_in_threadpool(get_object, f["storage_path"])
    safe = re.sub(r'[^A-Za-z0-9 ._()-]', "_", f["file_name"])
    return Response(content=data, media_type=f.get("content_type") or ctype,
                    headers={"Content-Disposition": f'inline; filename="{safe}"'})


class TaskPatch(BaseModel):
    status: str


@router.get("/tasks")
async def list_tasks(scope: str = "mine", user=Depends(current_user)):
    if scope == "all" and user["role"] == "admin":
        q = {"$or": [{"private": {"$ne": True}}, {"assignee_id": user["user_id"]}]}
    else:
        q = {"assignee_id": user["user_id"]}
    docs = await db.tasks.find(q, P).to_list(3000)
    docs.sort(key=lambda t: (t["status"] == "done", t.get("due_date") or "9999"))
    if scope == "all" and user["role"] == "admin":
        # one row per shared task, with each assignee's progress
        groups, out = {}, []
        for t in docs:
            gid = t.get("group_id")
            if not gid:
                out.append(t)
                continue
            if gid not in groups:
                groups[gid] = {**t, "progress": []}
                out.append(groups[gid])
            groups[gid]["progress"].append({"task_id": t["task_id"], "name": t["assignee_name"], "status": t["status"],
                                            "completed_at": t.get("completed_at")})
        for g in groups.values():
            g["progress"].sort(key=lambda p: (p["status"] != "done", p["name"]))
            g["done_count"] = sum(p["status"] == "done" for p in g["progress"])
            g["status"] = "done" if g["done_count"] == len(g["progress"]) else "open"
        out.sort(key=lambda t: (t["status"] == "done", t.get("due_date") or "9999"))
        return out
    return docs


@router.post("/tasks")
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
    ids = list(dict.fromkeys(body.assignee_ids))
    if ids and not is_admin:
        raise HTTPException(403, "You can only create tasks for yourself")
    if not is_admin and target != user["user_id"]:
        raise HTTPException(403, "You can only create tasks for yourself")
    if ids:
        assignees = await db.users.find({"user_id": {"$in": ids}}, P).to_list(500)
        if len(assignees) != len(ids):
            raise HTTPException(404, "Assignee not found")
        target = ids[0] if len(ids) == 1 else "group"
    elif target == "all":
        assignees = await db.users.find({"hidden": {"$ne": True}}, P).to_list(2000)
    else:
        a = await db.users.find_one({"user_id": target}, P)
        if not a:
            raise HTTPException(404, "Assignee not found")
        assignees = [a]
    private = target == user["user_id"]
    group_id = new_id("tgrp") if target in ("all", "group") else None
    collaborators = [{"user_id": a["user_id"], "name": a["name"]} for a in assignees] if target == "group" else []
    attachment = None
    if body.attachment_id:
        f = await db.task_files.find_one({"file_id": body.attachment_id, "uploaded_by": user["user_id"]}, P)
        if not f:
            raise HTTPException(404, "Attachment not found")
        attachment = {"file_id": f["file_id"], "file_name": f["file_name"], "content_type": f["content_type"]}
    docs = []
    for a in assignees:
        doc = {"task_id": new_id("task"), "title": body.title.strip(), "description": body.description.strip(),
               "due_date": body.due_date, "assignee_id": a["user_id"], "assignee_name": a["name"],
               "status": "open", "created_by": user["name"], "created_by_id": user["user_id"],
               "private": private, "group_id": group_id, "attachment": attachment, "for_everyone": target == "all",
               "collaborators": [c for c in collaborators if c["user_id"] != a["user_id"]], "created_at": now_iso()}
        await db.tasks.insert_one(dict(doc))
        docs.append(doc)
    for d in docs:
        if d["assignee_id"] == user["user_id"]:
            continue
        names = ", ".join(c["name"] for c in d["collaborators"])
        msg = f"{body.title.strip()} · with {names}" if names else body.title.strip()
        await notify([d["assignee_id"]], "task", "New shared task" if names else "New task assigned", msg, "/tasks")
    return docs[0] if len(docs) == 1 else {"created": len(docs), "group_id": group_id}


@router.delete("/tasks/group/{group_id}")
async def delete_task_group(group_id: str, admin=Depends(admin_user)):
    if not (await db.tasks.delete_many({"group_id": group_id})).deleted_count:
        raise HTTPException(404, "Task not found")
    return {"ok": True}


@router.delete("/tasks/{task_id}")
async def delete_task(task_id: str, user=Depends(current_user)):
    t = await db.tasks.find_one({"task_id": task_id}, P)
    if not t or not (t.get("created_by_id") == user["user_id"] or
                     (user["role"] == "admin" and not t.get("private"))):
        raise HTTPException(404, "Task not found")
    await db.tasks.delete_one({"task_id": task_id})
    return {"ok": True}


@router.patch("/tasks/{task_id}")
async def update_task(task_id: str, body: TaskPatch, user=Depends(current_user)):
    if body.status not in ("open", "done"):
        raise HTTPException(400, "Invalid status")
    q = {"task_id": task_id}
    t = await db.tasks.find_one(q, {"_id": 0, "participant_group_id": 1})
    if user["role"] != "admin" or (t and t.get("participant_group_id")):
        q["assignee_id"] = user["user_id"]  # group tasks: every member actions / acknowledges their own
    else:
        q["$or"] = [{"private": {"$ne": True}}, {"assignee_id": user["user_id"]}]
    res = await db.tasks.update_one(q, {"$set": {"status": body.status,
                                                 "completed_at": now_iso() if body.status == "done" else None}})
    if not res.matched_count:
        raise HTTPException(404, "Task not found")
    return await db.tasks.find_one({"task_id": task_id}, P)


async def task_reminder_loop():
    """Hourly: one day before a shared task is due, remind each assignee who hasn't ticked it off."""
    while True:
        try:
            tomorrow = (datetime.now(DIGEST_TZ).date() + timedelta(days=1)).isoformat()
            async for t in db.tasks.find({"group_id": {"$ne": None}, "status": "open", "due_date": tomorrow,
                                          "reminder_sent": {"$ne": True}}, P):
                await db.tasks.update_one({"task_id": t["task_id"]}, {"$set": {"reminder_sent": True}})
                others = ", ".join(c["name"] for c in t.get("collaborators") or [])
                body = f"{t['title']} is due tomorrow ({dmy(t['due_date'])})" + (f" · with {others}" if others else "")
                await notify([t["assignee_id"]], "task", "Task due tomorrow", body, "/tasks")
                owner = await db.users.find_one({"user_id": t["assignee_id"]}, P)
                if owner and owner.get("email") and not owner["email"].endswith("@example.com"):
                    await send_email(to=owner["email"], subject=f"Reminder: {t['title']} is due tomorrow", html=(
                        "<div style='font-family:Arial,sans-serif;max-width:520px;margin:0 auto;padding:24px'>"
                        f"<h2 style='color:#673E8D'>Task due tomorrow</h2><p>Hi {escape(owner['name'].split(' ')[0])},</p>"
                        f"<p><b>{escape(t['title'])}</b> is due on {dmy(t['due_date'])} and isn't ticked off yet."
                        f"{' You are working on it with ' + escape(others) + '.' if others else ''}</p>"
                        "<p>Open No Limitts → My tasks to mark it done.</p></div>"))
        except Exception as e:
            logger.error(f"Task reminder loop error: {e}")
        await asyncio.sleep(3600)
