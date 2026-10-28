"""Training certificates and expiry reminders."""
from datetime import date
from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import Response
from html import escape
from typing import Optional
import asyncio
import uuid
from core import EXPIRY_WARNING_DAYS, MAX_UPLOAD_BYTES, P, bearer, current_user, db, dmy, logger, new_id, notify, now_iso, spawn, user_from_token
from routes.drive import copy_cert_to_drive, upload_to_spaces
from email_service import EMAIL_FROM_NAME, send_email
from storage import APP_NAME, get_object, put_object

router = APIRouter(prefix="/api")


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


REQ_KEY = "cert_requirements"


async def requirements() -> dict:
    doc = await db.meta.find_one({"key": REQ_KEY}, P)
    return (doc or {}).get("groups", {})


def missing_required(certs: list, names: list) -> list:
    """A requirement is met by any certificate (not expired) whose title contains the requirement's name."""
    valid = [c["title"].lower() for c in certs if cert_status(c["expiry_date"])["status"] != "expired"]
    return [n for n in names if not any(n.lower() in t for t in valid)]


def required_match(title: str, names: list) -> str:
    return next((n for n in names if n.lower() in title.lower()), "")


def with_status(c: dict) -> dict:
    c = {k: v for k, v in c.items() if k != "storage_path"}
    c.update(cert_status(c["expiry_date"]))
    return c


def expiry_email_html(name: str, title: str, expiry: str, status: str, days: int, required: bool = False) -> str:
    if status == "expired":
        line = f"Your certificate <strong>{escape(title)}</strong> expired on {escape(expiry)}."
    else:
        line = (f"Your certificate <strong>{escape(title)}</strong> expires on {escape(expiry)} "
                f"({days} day{'s' if days != 1 else ''} left).")
    return (f'<table role="presentation" width="100%"><tr><td style="padding:24px;font-family:Arial,sans-serif;'
            f'color:#11181C"><p>Hi {escape(name)},</p><p>{line}</p>'
            + ('<p><strong>This certificate is required for your role.</strong></p>' if required else '')
            + f'<p>Please renew it and upload the new certificate in the {escape(EMAIL_FROM_NAME)} app.</p>'
            f'<p style="font-size:12px;color:#888">Sent by {escape(EMAIL_FROM_NAME)}. We never ask for your '
            f'password by email.</p></td></tr></table>')


async def check_certificate(cert: dict):
    st = cert_status(cert["expiry_date"])
    stage = st["status"]
    if stage == "valid" or cert.get("notified_stage") == stage:
        return
    await db.certificates.update_one({"cert_id": cert["cert_id"]}, {"$set": {"notified_stage": stage}})
    title = f"Certificate {'expired' if stage == 'expired' else 'expiring soon'}"
    body = (f"{cert['title']} expired on {dmy(cert['expiry_date'])}" if stage == "expired"
            else f"{cert['title']} expires in {st['days_left']} days ({dmy(cert['expiry_date'])})")
    owner = await db.users.find_one({"user_id": cert["owner_id"]}, P)
    required = required_match(cert["title"], (await requirements()).get((owner or {}).get("staff_group") or "", []))
    if required:
        body += ". It's required for your role, so please renew it" + (" now" if stage == "expired" else " before then")
    await notify([cert["owner_id"]], "certificate", title, body, "/(tabs)/certificates")
    if owner and owner.get("email"):
        subject = f"{title}: {cert['title']}"
        await send_email(to=owner["email"], subject=subject,
                         html=expiry_email_html(owner["name"], cert["title"], dmy(cert["expiry_date"]), stage,
                                                st["days_left"] or 0, bool(required)))


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


@router.get("/certificates")
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


@router.post("/certificates")
async def upload_certificate(title: str = Form(...), expiry_date: str = Form(...), issuer: str = Form(""),
                             issue_date: str = Form(""), cpd_hours: str = Form(""), file: UploadFile = File(...),
                             share_cpd: str = Form(""), drive_spaces: str = Form(""), user=Depends(current_user)):
    title = title.strip()
    if not title:
        raise HTTPException(400, "Title is required")
    if share_cpd.strip() and share_cpd.strip().lower() not in ("course", "webinar", "case study", "resource link"):
        raise HTTPException(400, "Choose Course, Webinar, Case Study or Resource link")
    hours = None
    if cpd_hours.strip():
        try:
            hours = round(float(cpd_hours.replace(",", ".")), 2)
        except ValueError:
            raise HTTPException(400, "CPD hours must be a number")
        if not (0 < hours <= 200):
            raise HTTPException(400, "CPD hours must be between 0 and 200")
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
    if hours:
        log = {"log_id": new_id("cpd"), "user_id": user["user_id"], "user_name": user["name"], "title": title,
               "provider": issuer.strip()[:200], "date": date.today().isoformat(), "hours": hours,
               "category": "Course", "notes": "Added from a training certificate", "cert_id": cert["cert_id"],
               "storage_path": cert["storage_path"], "file_name": cert["file_name"], "content_type": ctype,
               "created_at": now_iso()}
        await db.cpd_logs.insert_one(log)
        cert["cpd_log_id"] = log["log_id"]
        await db.certificates.update_one({"cert_id": cert["cert_id"]}, {"$set": {"cpd_log_id": log["log_id"],
                                                                                "cpd_hours": hours}})
        cert["cpd_hours"] = hours
    spawn(copy_cert_to_drive(cert, data))
    shared = {}
    if share_cpd.strip():
        from routes.cpd import share_file_to_resources  # local import: cpd is a sibling module
        shared["cpd_resource_id"] = await share_file_to_resources(cert, share_cpd, user)
    spaces = [x.strip() for x in drive_spaces.split(",") if x.strip()]
    if spaces:
        shared["drive"] = await upload_to_spaces(cert, data, spaces, user)
    await check_certificate(cert)
    cert["notified_stage"] = cert_status(expiry_date)["status"]
    from routes.compliance import check_starter_complete  # local import: compliance imports this module
    spawn(check_starter_complete(user))
    return {**with_status(cert), **shared}


@router.delete("/certificates/{cert_id}")
async def delete_certificate(cert_id: str, user=Depends(current_user)):
    q = {"cert_id": cert_id, "is_deleted": False}
    if user["role"] != "admin":
        q["owner_id"] = user["user_id"]
    res = await db.certificates.update_one(q, {"$set": {"is_deleted": True}})
    if not res.matched_count:
        raise HTTPException(404, "Certificate not found")
    await db.cpd_logs.delete_many({"cert_id": cert_id})
    return {"ok": True}


@router.get("/files/{cert_id}")
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
