"""Company Drive directories (Suppliers, Templates, Referral Partners, Activities, Resources) with file attachments.
Everyone can view; admins add, edit and remove."""
import uuid
from typing import Optional
from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import Response
from pydantic import BaseModel
from core import MAX_UPLOAD_BYTES, P, admin_user, bearer, current_user, db, logger, new_id, now_iso, user_from_token
from storage import APP_NAME, get_object, put_object

router = APIRouter(prefix="/api")

CATEGORIES = {
    "therapist": ["Suppliers", "Templates", "Trusted Referral Partner Organisations"],
    "participant": ["Suppliers", "Activities", "Resources"],
}
FIELDS = ("name", "contact", "phone", "email", "address", "link", "note")


class EntryIn(BaseModel):
    space: str
    category: str
    name: str
    contact: str = ""
    phone: str = ""
    email: str = ""
    address: str = ""
    link: str = ""
    note: str = ""


def clean(body: EntryIn) -> dict:
    if body.category not in CATEGORIES.get(body.space, []):
        raise HTTPException(400, "Choose a section and category")
    d = {k: (getattr(body, k) or "").strip()[:1000 if k == "note" else 300] for k in FIELDS}
    if not d["name"]:
        raise HTTPException(400, "Add a name")
    if d["link"] and not d["link"].startswith(("http://", "https://")):
        d["link"] = "https://" + d["link"]
    return {"space": body.space, "category": body.category, **d}


def shape(d: dict, user: dict) -> dict:
    d["files"] = [{k: v for k, v in f.items() if k != "storage_path"} for f in d.get("files") or []]
    d["can_edit"] = user["role"] == "admin"
    return d


@router.get("/directory/categories")
async def categories(user=Depends(current_user)):
    return CATEGORIES


@router.get("/directory")
async def list_entries(space: str, category: str, user=Depends(current_user)):
    docs = await db.directory.find({"space": space, "category": category}, P).sort("name", 1).to_list(1000)
    return [shape(d, user) for d in docs]


@router.get("/directory/{entry_id}")
async def get_entry(entry_id: str, user=Depends(current_user)):
    d = await db.directory.find_one({"entry_id": entry_id}, P)
    if not d:
        raise HTTPException(404, "Entry not found")
    return shape(d, user)


@router.post("/directory")
async def add_entry(body: EntryIn, admin=Depends(admin_user)):
    doc = {"entry_id": new_id("dir"), **clean(body), "files": [], "created_by": admin["name"],
           "created_by_id": admin["user_id"], "created_at": now_iso()}
    await db.directory.insert_one(dict(doc))
    return shape(doc, admin)


@router.put("/directory/{entry_id}")
async def edit_entry(entry_id: str, body: EntryIn, admin=Depends(admin_user)):
    res = await db.directory.update_one({"entry_id": entry_id}, {"$set": {**clean(body), "updated_at": now_iso()}})
    if not res.matched_count:
        raise HTTPException(404, "Entry not found")
    return await get_entry(entry_id, admin)


@router.delete("/directory/{entry_id}")
async def delete_entry(entry_id: str, admin=Depends(admin_user)):
    if not (await db.directory.delete_one({"entry_id": entry_id})).deleted_count:
        raise HTTPException(404, "Entry not found")
    return {"ok": True}


@router.post("/directory/{entry_id}/files")
async def add_file(entry_id: str, file: UploadFile = File(...), admin=Depends(admin_user)):
    d = await db.directory.find_one({"entry_id": entry_id}, P)
    if not d:
        raise HTTPException(404, "Entry not found")
    if len(d.get("files") or []) >= 30:
        raise HTTPException(400, "Up to 30 files per entry")
    data = await file.read()
    if not data:
        raise HTTPException(400, "Empty file")
    if len(data) > MAX_UPLOAD_BYTES:
        raise HTTPException(413, "File too large (max 15 MB)")
    name = (file.filename or "file").split("/")[-1][:200]
    ext = name.rsplit(".", 1)[-1].lower()[:8] if "." in name else "bin"
    ctype = file.content_type or "application/octet-stream"
    path = f"{APP_NAME}/directory/{entry_id}/{uuid.uuid4().hex}.{ext}"
    try:
        await run_in_threadpool(put_object, path, data, ctype)
    except Exception as e:
        logger.error(f"directory file upload failed: {e}")
        raise HTTPException(502, "Could not store the file, please try again")
    f = {"file_id": new_id("dfl"), "name": name, "content_type": ctype, "size": len(data), "storage_path": path,
         "added_by": admin["name"], "created_at": now_iso()}
    await db.directory.update_one({"entry_id": entry_id}, {"$push": {"files": f}})
    f.pop("storage_path")
    return f


@router.get("/directory/{entry_id}/files/{file_id}")
async def get_file(entry_id: str, file_id: str, request: Request, token: Optional[str] = None):
    if not await user_from_token(bearer(request) or token):
        raise HTTPException(401, "Not authenticated")
    d = await db.directory.find_one({"entry_id": entry_id}, {"_id": 0, "files": 1})
    f = next((x for x in (d or {}).get("files") or [] if x["file_id"] == file_id), None)
    if not f:
        raise HTTPException(404, "File not found")
    data, ctype = await run_in_threadpool(get_object, f["storage_path"])
    safe = f["name"].replace('"', "")
    return Response(content=data, media_type=f.get("content_type") or ctype,
                    headers={"Content-Disposition": f'inline; filename="{safe}"', "X-Content-Type-Options": "nosniff"})


@router.delete("/directory/{entry_id}/files/{file_id}")
async def delete_file(entry_id: str, file_id: str, admin=Depends(admin_user)):
    res = await db.directory.update_one({"entry_id": entry_id}, {"$pull": {"files": {"file_id": file_id}}})
    if not res.modified_count:
        raise HTTPException(404, "File not found")
    return {"ok": True}
