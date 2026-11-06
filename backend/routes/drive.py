"""Company files on SharePoint (Microsoft 365): resource folders, pins, certificate copies and the AI index."""
from datetime import timedelta, timezone
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import Response
from pydantic import BaseModel
from typing import Optional
import asyncio
import re
import secrets
from core import P, admin_user, all_user_ids, bearer, current_user, db, logger, new_id, notify, now, now_iso, result_page, spawn, user_from_token
import ms_services as gs

router = APIRouter(prefix="/api")


DRIVE_KEY = "sharepoint"


async def drive_conn():
    """Saved SharePoint folders. Access itself comes from the Microsoft 365 app (no account to connect)."""
    return await db.integrations.find_one({"key": DRIVE_KEY}, P) or {}


async def drive_svc_or_409():
    if not gs.configured():
        raise HTTPException(409, "Microsoft 365 isn't set up yet")
    return gs.Graph()


async def copy_cert_to_drive(cert: dict, data: bytes):
    """Keep a copy of each certificate in 'No Limitts Certificates' inside the Staff Resources folder."""
    roots = await current_roots()
    if not gs.configured() or "therapist" not in roots:
        return
    try:
        svc = gs.Graph()
        conn = await drive_conn()
        folder = conn.get("cert_folder") if (conn.get("cert_folder_parent") == roots["therapist"]) else None
        if not folder:
            folder = await run_in_threadpool(gs.drive_ensure_folder, svc, roots["therapist"])
            await db.integrations.update_one({"key": DRIVE_KEY}, {"$set": {"key": DRIVE_KEY, "cert_folder": folder,
                                                                          "cert_folder_parent": roots["therapist"]}}, upsert=True)
        name = f"{cert['owner_name']} - {cert['title']} (expires {cert['expiry_date']})"
        ext = cert["file_name"].rsplit(".", 1)[-1] if "." in cert["file_name"] else ""
        f = await run_in_threadpool(gs.drive_upload, svc, folder, f"{name}.{ext}" if ext else name,
                                    data, cert["content_type"])
        await db.certificates.update_one({"cert_id": cert["cert_id"]},
                                         {"$set": {"drive_file_id": f["id"], "drive_link": f.get("webViewLink")}})
    except Exception as e:
        logger.error(f"SharePoint copy failed for {cert['cert_id']}: {e}")


@router.get("/integrations/sharepoint/status")
async def drive_status(user=Depends(current_user)):
    conn = await drive_conn()
    return {"configured": gs.configured(), "connected": gs.configured(), "folder_name": gs.DRIVE_FOLDER_NAME,
            "spaces": {k: {"label": label, "folder_id": (conn.get("spaces") or {}).get(k, {}).get("id"),
                           "folder_name": (conn.get("spaces") or {}).get(k, {}).get("name")}
                       for k, label in DRIVE_SPACES.items()}}


@router.get("/drive/files")
async def drive_files(q: str = "", admin=Depends(admin_user)):
    """Admin file picker (attach a SharePoint file to a policy): search the company folders."""
    svc = await drive_svc_or_409()
    roots = list((await current_roots()).values())
    try:
        items = []
        for root in roots:
            items += await run_in_threadpool(gs.drive_search_under, svc, root, q[:100]) if q.strip() \
                else await run_in_threadpool(gs.drive_children, svc, root)
    except Exception as e:
        logger.error(f"SharePoint list failed: {e}")
        raise HTTPException(502, "Could not list SharePoint files")
    return [f for f in items if f["mimeType"] != gs.FOLDER_MIME][:30]


DRIVE_SPACES = {"therapist": "Staff Resources", "participant": "Participant Resources"}


class SharedFolderIn(BaseModel):
    link: str
    space: str = "therapist"


def check_space(space: str) -> str:
    if space not in DRIVE_SPACES:
        raise HTTPException(400, "Unknown Drive section")
    return space


async def current_roots() -> dict:
    """space -> root folder id for every configured Company Drive section."""
    conn = await drive_conn()
    return {k: v["id"] for k, v in (conn.get("spaces") or {}).items() if v.get("id") and k in DRIVE_SPACES}


async def prune_drive_data():
    roots = list((await current_roots()).values())
    await db.drive_docs.delete_many({"root_id": {"$nin": roots}})
    await db.drive_pins.delete_many({"root_id": {"$nin": roots}})


@router.put("/integrations/sharepoint/shared-folder")
async def set_shared_folder(body: SharedFolderIn, admin=Depends(admin_user)):
    space = check_space(body.space)
    svc = await drive_svc_or_409()
    fid = await run_in_threadpool(gs.folder_id_from_link, body.link)
    if not fid:
        raise HTTPException(400, "Paste a SharePoint folder link (use Copy link on the folder)")
    try:
        meta = await run_in_threadpool(gs.drive_get, svc, fid)
    except Exception as e:
        logger.error(f"Drive folder lookup failed: {e}")
        raise HTTPException(400, "Couldn't open that folder. Check the app has access to the SharePoint site")
    if meta["mimeType"] != gs.FOLDER_MIME:
        raise HTTPException(400, "That link is a file, not a folder")
    await db.integrations.update_one({"key": DRIVE_KEY}, {"$set": {"key": DRIVE_KEY, f"spaces.{space}": {"id": fid, "name": meta["name"]}}},
                                     upsert=True)
    await prune_drive_data()
    spawn(index_drive())
    return {"space": space, "folder_id": fid, "folder_name": meta["name"]}


@router.delete("/integrations/sharepoint/shared-folder")
async def clear_shared_folder(space: str = "therapist", admin=Depends(admin_user)):
    await db.integrations.update_one({"key": DRIVE_KEY}, {"$unset": {f"spaces.{check_space(space)}": ""}})
    await prune_drive_data()
    return {"ok": True}


async def shared_root(space: str = "therapist"):
    roots = await current_roots()
    if check_space(space) not in roots:
        raise HTTPException(409, f"The {DRIVE_SPACES[space]} folder hasn't been set up yet")
    return roots[space], DRIVE_SPACES[space]


def drive_item(f: dict) -> dict:
    return {"id": f["id"], "name": f["name"], "mime_type": f["mimeType"],
            "is_folder": f["mimeType"] == gs.FOLDER_MIME, "modified": f.get("modifiedTime", ""),
            "size": int(f["size"]) if f.get("size") else None}


drive_index_lock = asyncio.Lock()


def clean_pdf_text(text: str) -> str:
    """Drop page footers like 'P a g e 1 | 4' / 'Page 2 of 5' and collapse blank runs."""
    text = re.sub(r"(?im)^\s*(p\s*a\s*g\s*e\s*\d+\s*(\|\s*\d+)?|page\s+\d+\s+of\s+\d+)\s*$", "", text)
    text = re.sub(r"[ \t]+\n", "\n", text)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


async def import_policies_from_drive(svc, folder_id: str, by_name: str = "No Limitts") -> int:
    """Create a policy for every readable document in the folder (skips ones already imported)."""
    files = await run_in_threadpool(gs.drive_walk, svc, folder_id)
    added = []
    for f in files:
        if not gs.readable(f["mimeType"]) and "word" not in f["mimeType"]:
            continue
        if f["name"].lower().startswith("all published"):  # compilations of the individual documents
            continue
        if await db.policies.find_one({"drive_file.id": f["id"]}):
            continue
        try:
            text = await run_in_threadpool(gs.drive_text, svc, f, 60000) if gs.readable(f["mimeType"]) else ""
        except Exception as e:
            logger.warning(f"Policy text failed for {f['name']}: {e}")
            text = ""
        text = clean_pdf_text(text)
        title = re.sub(r"\.(pdf|docx?|txt|md)$", "", f["name"], flags=re.I).replace("_", " ")
        title = re.sub(r"\s*-?\s*\bPDF\b", "", title).strip(" -")
        low = title.lower()
        cat = "Procedure" if any(k in low for k in ("procedure", "process", "sop", "guide", "faq", "tips",
                                                     "register", "calendar", "101")) and "policy" not in low \
            else "Policy"
        meta = await run_in_threadpool(gs.drive_get, svc, f["id"])
        doc = {"policy_id": new_id("pol"), "title": title, "category": cat,
               "content": text or "Open the attached document to read this policy.", "author_name": by_name,
               "acknowledged_by": [], "source": "drive_import",
               "drive_file": {"id": f["id"], "name": f["name"], "link": meta.get("webViewLink"),
                              "mime_type": f["mimeType"]}, "created_at": now_iso()}
        await db.policies.insert_one(doc)
        added.append(title)
    if added:
        await notify(await all_user_ids(), "policy", f"{len(added)} policies & procedures added",
                     "Please review and acknowledge them in Policies & procedures.", "/policies")
    return len(added)


class PolicyImportIn(BaseModel):
    link: str


@router.post("/policies/import-drive")
async def import_policies(body: PolicyImportIn, admin=Depends(admin_user)):
    svc = await drive_svc_or_409()
    fid = await run_in_threadpool(gs.folder_id_from_link, body.link)
    if not fid:
        raise HTTPException(400, "Paste a SharePoint folder link (use Copy link on the folder)")
    try:
        count = await import_policies_from_drive(svc, fid, admin["name"])
    except Exception as e:
        logger.error(f"Policy import failed: {e}")
        raise HTTPException(502, "Couldn't read that SharePoint folder")
    return {"imported": count}


async def index_drive():
    if drive_index_lock.locked() or not gs.configured():
        return
    async with drive_index_lock:
        roots = list((await current_roots()).values())
        if not roots:
            await db.drive_docs.update_many({}, {"$set": {"stale": True}})
            return
        try:
            svc = gs.Graph()
            files = []
            for root in roots:
                files += [(root, f) for f in await run_in_threadpool(gs.drive_walk, svc, root)
                          if gs.readable(f["mimeType"])]
        except Exception as e:
            logger.error(f"Drive index listing failed: {e}")
            return
        keep = []
        for root, f in files:
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
                "modified": f.get("modifiedTime"), "text": text, "indexed_at": now_iso(), "stale": False}}, upsert=True)
        # Files no longer in a connected folder are flagged stale (filtered out of search), not deleted
        await db.drive_docs.update_many({"$or": [{"root_id": {"$nin": roots}}, {"file_id": {"$nin": keep}}]}, {"$set": {"stale": True}})
        await db.drive_docs.update_many({"root_id": {"$in": roots}, "file_id": {"$in": keep}}, {"$set": {"stale": False}})
        await db.meta.update_one({"key": "drive_index"}, {"$set": {"key": "drive_index", "last_run": now_iso(),
                                                                  "count": len(keep)}}, upsert=True)


async def drive_index_loop():
    while True:
        try:
            await index_drive()
        except Exception as e:
            logger.error(f"Drive index failed: {e}")
        await asyncio.sleep(4 * 3600)


@router.get("/drive/index-status")
async def drive_index_status(admin=Depends(admin_user)):
    m = await db.meta.find_one({"key": "drive_index"}, P) or {}
    return {"last_run": m.get("last_run"), "count": await db.drive_docs.count_documents({"text": {"$ne": ""}, "stale": {"$ne": True}}),
            "running": drive_index_lock.locked()}


@router.post("/drive/reindex")
async def drive_reindex(admin=Depends(admin_user)):
    if not await current_roots():
        raise HTTPException(409, "No Company Drive folders have been set up yet")
    spawn(index_drive())
    return {"ok": True}


class PinIn(BaseModel):
    file_id: str
    space: str = "therapist"


@router.post("/drive/pins")
async def pin_file(body: PinIn, admin=Depends(admin_user)):
    root_id, _ = await shared_root(body.space)
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


@router.delete("/drive/pins/{file_id}")
async def unpin_file(file_id: str, admin=Depends(admin_user)):
    await db.drive_pins.delete_one({"file_id": file_id})
    return {"ok": True}


@router.get("/drive/shared")
async def shared_files(space: str = "therapist", folder: str = "", q: str = "", user=Depends(current_user)):
    root_id, root_name = await shared_root(space)
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
        raise HTTPException(502, "Could not load the SharePoint folder")
    pins = await db.drive_pins.find({"root_id": root_id}, P).sort("pinned_at", -1).to_list(50)
    pin_ids = {p["file_id"] for p in pins}
    out = [{**drive_item(f), "pinned": f["id"] in pin_ids} for f in items]
    pinned = [{"id": p["file_id"], "name": p["name"], "mime_type": p["mime_type"],
               "is_folder": p["mime_type"] == gs.FOLDER_MIME, "modified": "", "size": None, "pinned": True}
              for p in pins]
    return {"root_id": root_id, "root_name": root_name, "folder_id": folder_id, "items": out, "pinned": pinned}


@router.get("/drive/shared/file/{file_id}")
async def shared_file(file_id: str, request: Request, token: Optional[str] = None, space: str = "therapist"):
    user = await user_from_token(bearer(request) or token)
    if not user:
        raise HTTPException(401, "Not authenticated")
    root_id, _ = await shared_root(space)
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



async def upload_to_spaces(cert: dict, data: bytes, spaces: list, user: dict) -> dict:
    """Copy an uploaded file into Support Worker / Participants Resources. Returns space -> 'added' | reason."""
    out = {}
    roots = await current_roots()
    for space in spaces:
        if space not in DRIVE_SPACES:
            out[space] = "unknown"
            continue
        if not gs.configured() or space not in roots:
            out[space] = "not_set_up"
            continue
        try:
            svc = gs.Graph()
            ext = cert["file_name"].rsplit(".", 1)[-1] if "." in cert["file_name"] else ""
            name = f"{cert['title']}.{ext}" if ext else cert["title"]
            await run_in_threadpool(gs.drive_upload, svc, roots[space], name, data, cert["content_type"])
            out[space] = "added"
        except Exception as e:
            logger.error(f"Drive space upload failed ({space}): {e}")
            out[space] = "failed"
    if "added" in out.values():
        spawn(index_drive())
    return out
