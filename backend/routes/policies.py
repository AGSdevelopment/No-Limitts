"""Policies & procedures, versions, acknowledgements and reminders."""
from datetime import datetime
from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import Response
from html import escape
from pydantic import BaseModel
from typing import Optional
import asyncio
import re
import uuid
from core import spawn, DIGEST_TZ, HIDDEN_TEST_USERS, MAX_UPLOAD_BYTES, P, admin_user, all_user_ids, bearer, current_user, db, logger, new_id, notify, now_iso, user_from_token
from routes.drive import clean_pdf_text, drive_svc_or_409
from email_service import send_email
from storage import APP_NAME, get_object, put_object
import google_services as gs

router = APIRouter(prefix="/api")


class PolicyIn(BaseModel):
    title: str
    category: str = "Policy"
    content: str
    drive_file_id: Optional[str] = None


@router.get("/policies")
async def list_policies(user=Depends(current_user)):
    docs = await db.policies.find({}, P).sort("created_at", -1).to_list(500)
    hidden = set(HIDDEN_TEST_USERS)
    for d in docs:
        d["acknowledged"] = user["user_id"] in d.get("acknowledged_by", [])
        d["ack_count"] = len([u for u in d.get("acknowledged_by", []) if u not in hidden])
        d.pop("acknowledged_by", None)
        d["version"] = d.get("version", 1)
        d["version_history"] = [{"version": v["version"], "updated_at": v.get("updated_at"),
                                 "change_note": v.get("change_note", "")} for v in d.pop("versions", [])]
        if d.get("file"):
            d["attachment_name"] = d["file"]["name"]
            d.pop("file")
        elif d.get("drive_file"):
            d["attachment_name"] = d["drive_file"].get("name")
    return docs


@router.post("/policies")
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


@router.post("/policies/{policy_id}/version")
async def new_policy_version(policy_id: str, change_note: str = Form(""), title: str = Form(""),
                             content: str = Form(""), file: Optional[UploadFile] = File(None),
                             admin=Depends(admin_user)):
    """Replace a policy with a new version; everyone (except the admin) must re-acknowledge it."""
    p = await db.policies.find_one({"policy_id": policy_id}, P)
    if not p:
        raise HTTPException(404, "Policy not found")
    upd = {"title": title.strip() or p["title"], "content": content.strip() or p["content"]}
    if file is not None and file.filename:
        data = await file.read()
        ctype = file.content_type or "application/octet-stream"
        if not data or len(data) > MAX_UPLOAD_BYTES:
            raise HTTPException(400, "File is empty or too large (max 15 MB)")
        ext = file.filename.rsplit(".", 1)[-1].lower() if "." in file.filename else "bin"
        try:
            stored = await run_in_threadpool(put_object, f"{APP_NAME}/policies/{uuid.uuid4().hex}.{ext}", data, ctype)
        except Exception as e:
            logger.error(f"Policy upload failed: {e}")
            raise HTTPException(502, "Could not store the file, please try again")
        upd["file"] = {"storage_path": stored["path"], "name": file.filename, "content_type": ctype}
        upd["drive_file"] = None
        if not content.strip() and "pdf" in ctype:
            def pdf_text(b):
                import pymupdf
                return "\n".join(pg.get_text() for pg in pymupdf.open(stream=b, filetype="pdf"))
            try:
                text = clean_pdf_text(await run_in_threadpool(pdf_text, data))
                upd["content"] = text[:60000] if len(text) > 100 else \
                    "This document is a scanned file. Open the attached document to read it."
            except Exception as e:
                logger.warning(f"Policy PDF text failed: {e}")
    elif upd["content"] == p["content"] and upd["title"] == p["title"]:
        raise HTTPException(400, "Upload a new file or change the text for the new version")
    else:  # text-only version: the old document would be out of date
        upd["file"] = None
        upd["drive_file"] = None
    version = p.get("version", 1)
    prev = {"version": version, "title": p["title"], "content": p["content"], "drive_file": p.get("drive_file"),
            "file": p.get("file"), "change_note": p.get("change_note", ""),
            "updated_at": p.get("updated_at") or p["created_at"], "author_name": p.get("author_name")}
    upd.update({"version": version + 1, "change_note": change_note.strip()[:500], "updated_at": now_iso(),
                "author_name": admin["name"], "acknowledged_by": [admin["user_id"]], "last_reminded_at": None})
    await db.policies.update_one({"policy_id": policy_id}, {"$set": upd, "$push": {"versions": prev}})
    note = f" · {change_note.strip()[:120]}" if change_note.strip() else ""
    await notify(await all_user_ids(admin["user_id"]), "policy", "Updated policy: please re-acknowledge",
                 f"{upd['title']} (version {version + 1}){note}", f"/policy/{policy_id}")
    return {"ok": True, "version": version + 1}


@router.get("/policies/{policy_id}/acks")
async def policy_acks(policy_id: str, admin=Depends(admin_user)):
    p = await db.policies.find_one({"policy_id": policy_id}, P)
    if not p:
        raise HTTPException(404, "Policy not found")
    acked = set(p.get("acknowledged_by", []))
    users = await db.users.find({"hidden": {"$ne": True}}, {"_id": 0, "user_id": 1, "name": 1, "picture": 1,
                                                            "staff_group": 1}).sort("name", 1).to_list(2000)
    return {"acknowledged": [u for u in users if u["user_id"] in acked],
            "pending": [u for u in users if u["user_id"] not in acked],
            "version": p.get("version", 1), "last_reminded_at": p.get("last_reminded_at")}


@router.post("/policies/{policy_id}/remind")
async def remind_policy(policy_id: str, admin=Depends(admin_user)):
    p = await db.policies.find_one({"policy_id": policy_id}, P)
    if not p:
        raise HTTPException(404, "Policy not found")
    acked = set(p.get("acknowledged_by", []))
    pending = await db.users.find({"hidden": {"$ne": True}, "user_id": {"$nin": list(acked)}}, P).to_list(2000)
    if not pending:
        raise HTTPException(400, "Everyone has acknowledged this already")
    await notify([u["user_id"] for u in pending], "policy", "Reminder: please acknowledge", p["title"],
                 f"/policy/{policy_id}")
    for u in pending:
        if u.get("email") and not u["email"].endswith("@example.com"):
            await send_email(to=u["email"], subject=f"Reminder: please read and acknowledge {p['title']}", html=(
                "<div style='font-family:Arial,sans-serif;max-width:520px;margin:0 auto;padding:24px'>"
                f"<h2 style='color:#205890'>Please acknowledge a policy</h2><p>Hi {escape(u['name'].split(' ')[0])},</p>"
                f"<p>{escape(admin['name'])} has asked you to read and acknowledge <b>{escape(p['title'])}</b>.</p>"
                "<p>Open StaffHub → Library → Policies &amp; procedures, read it and tap the acknowledge button at the bottom.</p></div>"))
    await db.policies.update_one({"policy_id": policy_id}, {"$set": {"last_reminded_at": now_iso()}})
    return {"reminded": len(pending)}


async def policy_reminder_loop():
    """Every Monday 9am Perth: one reminder per person listing the policies they still haven't acknowledged."""
    while True:
        try:
            local = datetime.now(DIGEST_TZ)
            if local.weekday() == 0 and local.hour >= 9:
                year, week, _ = local.isocalendar()
                key = f"policy_remind_{year}_{week}"
                if not await db.meta.find_one({"key": key}):
                    await db.meta.insert_one({"key": key, "created_at": now_iso()})
                    policies = await db.policies.find({}, {"_id": 0, "title": 1, "acknowledged_by": 1}).to_list(1000)
                    sent = 0
                    async for u in db.users.find({"hidden": {"$ne": True}}, P):
                        pending = [p["title"] for p in policies if u["user_id"] not in (p.get("acknowledged_by") or [])]
                        if not pending:
                            continue
                        n = len(pending)
                        await notify([u["user_id"]], "policy", "Weekly reminder: policies to acknowledge",
                                     f"{n} polic{'y' if n == 1 else 'ies'} still need your acknowledgement", "/policies")
                        if u.get("email") and not u["email"].endswith("@example.com"):
                            items = "".join(f"<li>{escape(t)}</li>" for t in pending[:30])
                            more = f"<p>…and {n - 30} more.</p>" if n > 30 else ""
                            await send_email(to=u["email"], subject=f"Reminder: {n} polic{'y' if n == 1 else 'ies'} to acknowledge", html=(
                                "<div style='font-family:Arial,sans-serif;max-width:560px;margin:0 auto;padding:24px'>"
                                f"<h2 style='color:#205890'>Policies waiting for you</h2><p>Hi {escape(u['name'].split(' ')[0])},</p>"
                                f"<p>Please read and acknowledge these in StaffHub → Library → Policies &amp; procedures:</p>"
                                f"<ul>{items}</ul>{more}</div>"))
                        sent += 1
                    await db.meta.update_one({"key": key}, {"$set": {"reminded": sent}})
                    logger.info(f"Weekly policy reminders sent to {sent} staff")
        except Exception as e:
            logger.error(f"Policy reminder loop error: {e}")
        await asyncio.sleep(600)


@router.get("/policies/{policy_id}/file")
async def policy_file(policy_id: str, request: Request, token: Optional[str] = None):
    user = await user_from_token(bearer(request) or token)
    if not user:
        raise HTTPException(401, "Not authenticated")
    p = await db.policies.find_one({"policy_id": policy_id}, P)
    if p and p.get("file"):
        data, ctype = await run_in_threadpool(get_object, p["file"]["storage_path"])
        safe = re.sub(r'[^A-Za-z0-9 ._()-]', "_", p["file"]["name"])
        return Response(content=data, media_type=p["file"].get("content_type") or ctype,
                        headers={"Content-Disposition": f'inline; filename="{safe}"'})
    if not p or not p.get("drive_file"):
        raise HTTPException(404, "File not found")
    svc = await drive_svc_or_409()
    try:
        name, mime, data = await run_in_threadpool(gs.drive_download, svc, p["drive_file"]["id"])
    except Exception as e:
        logger.error(f"Policy file download failed: {e}")
        raise HTTPException(502, "Could not open this file")
    safe = re.sub(r'[^A-Za-z0-9 ._()-]', "_", name)
    return Response(content=data, media_type=mime, headers={"Content-Disposition": f'inline; filename="{safe}"'})


@router.post("/policies/{policy_id}/acknowledge")
async def acknowledge_policy(policy_id: str, user=Depends(current_user)):
    res = await db.policies.update_one({"policy_id": policy_id}, {"$addToSet": {"acknowledged_by": user["user_id"]}})
    if not res.matched_count:
        raise HTTPException(404, "Policy not found")
    from routes.compliance import check_starter_complete  # local import avoids a circular import
    spawn(check_starter_complete(user))
    return {"ok": True}
