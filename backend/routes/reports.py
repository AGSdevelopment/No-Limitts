"""Reports folder in Company Drive: private report files (PDF, Excel, Word...) for Admins, HR, Finance and Service Coordinators.
Stored in object storage. The built-in app reports are linked from the same screen in the app."""
import re
import uuid
from typing import Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import Response

from core import MAX_UPLOAD_BYTES, P, current_user, db, logger, new_id, now_iso
from routes.pm_common import is_finance, token_user
from storage import APP_NAME, get_object, put_object

router = APIRouter(prefix="/api")
CATEGORIES = ("Finance", "Compliance", "Rostering", "Participants", "HR", "Other")


def can_reports(u: dict) -> bool:
    return u.get("role") == "admin" or u.get("user_type") in ("admin", "hr", "support_coordinator") or is_finance(u)


async def reports_user(user=Depends(current_user)):
    if not can_reports(user):
        raise HTTPException(403, "Reports are for Admin, HR, Finance and Service Coordinators")
    return user


@router.get("/reports/files")
async def list_files(user=Depends(reports_user)):
    return await db.report_files.find({}, {"_id": 0, "storage_path": 0}).sort("created_at", -1).to_list(2000)


@router.post("/reports/files")
async def upload_file(file: UploadFile = File(...), category: str = Form("Other"), title: str = Form(""), user=Depends(reports_user)):
    data = await file.read()
    if not data:
        raise HTTPException(400, "Empty file")
    if len(data) > MAX_UPLOAD_BYTES:
        raise HTTPException(413, "File too large (max 15 MB)")
    name = file.filename or "report"
    ext = name.rsplit(".", 1)[-1].lower() if "." in name else "bin"
    ctype = file.content_type or "application/octet-stream"
    try:
        res = await run_in_threadpool(put_object, f"{APP_NAME}/reports/{uuid.uuid4().hex}.{ext}", data, ctype)
    except Exception as e:
        logger.error(f"Report upload failed: {e}")
        raise HTTPException(502, "Could not store the file, please try again")
    doc = {"file_id": new_id("rpt"), "title": (title.strip() or name)[:200], "file_name": name, "category": category if category in CATEGORIES else "Other",
           "storage_path": res["path"], "content_type": ctype, "size": len(data), "uploaded_by": user["user_id"],
           "uploaded_by_name": user.get("name") or "", "created_at": now_iso()}
    await db.report_files.insert_one(dict(doc))
    doc.pop("storage_path")
    return doc


@router.get("/reports/files/{file_id}")
async def open_file(file_id: str, request: Request, token: Optional[str] = None):
    if not can_reports(await token_user(request, token)):
        raise HTTPException(403, "Reports are for Admin, HR, Finance and Service Coordinators")
    f = await db.report_files.find_one({"file_id": file_id}, P)
    if not f:
        raise HTTPException(404, "File not found")
    data, ctype = await run_in_threadpool(get_object, f["storage_path"])
    safe = re.sub(r'[^A-Za-z0-9 ._()-]', "_", f["file_name"])
    return Response(content=data, media_type=f.get("content_type") or ctype, headers={"Content-Disposition": f'inline; filename="{safe}"'})


@router.delete("/reports/files/{file_id}")
async def delete_file(file_id: str, user=Depends(reports_user)):
    f = await db.report_files.find_one({"file_id": file_id}, P)
    if not f or not (f["uploaded_by"] == user["user_id"] or user.get("role") == "admin"):
        raise HTTPException(404, "File not found")
    await db.report_files.delete_one({"file_id": file_id})
    return {"ok": True}
