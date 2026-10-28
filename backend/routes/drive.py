"""Google Drive connection, shared folders, pins and AI index."""
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
import google_services as gs

router = APIRouter(prefix="/api")


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


@router.get("/integrations/google-drive/status")
async def drive_status(user=Depends(current_user)):
    conn = await drive_conn()
    return {"configured": bool(gs.drive_client_config()), "connected": bool(conn),
            "email": (conn or {}).get("email", ""), "folder_name": gs.DRIVE_FOLDER_NAME,
            "spaces": {k: {"label": label, "folder_id": ((conn or {}).get("spaces") or {}).get(k, {}).get("id"),
                           "folder_name": ((conn or {}).get("spaces") or {}).get(k, {}).get("name")}
                       for k, label in DRIVE_SPACES.items()},
            "redirect_uri": gs.drive_redirect_uri() if user["role"] == "admin" else None}


@router.post("/integrations/google-drive/start")
async def drive_start(admin=Depends(admin_user)):
    if not gs.drive_client_config():
        raise HTTPException(409, "Google Drive credentials are not set up yet")
    state = secrets.token_urlsafe(32)
    url, verifier = gs.drive_auth_url(state)
    await db.oauth_states.insert_one({"state": state, "user_id": admin["user_id"], "code_verifier": verifier,
                                      "created_at": now()})
    return {"authorization_url": url}


@router.get("/integrations/google-drive/callback")
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


@router.delete("/integrations/google-drive")
async def drive_disconnect(admin=Depends(admin_user)):
    await db.integrations.delete_one({"key": DRIVE_KEY})
    return {"ok": True}


@router.get("/drive/files")
async def drive_files(q: str = "", admin=Depends(admin_user)):
    svc = await drive_svc_or_409()
    try:
        return await run_in_threadpool(gs.drive_list, svc, q[:100])
    except Exception as e:
        logger.error(f"Drive list failed: {e}")
        raise HTTPException(502, "Could not list Google Drive files")


DRIVE_SPACES = {"therapist": "Therapist Resources", "participant": "Participants Resources"}


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
    return {k: v["id"] for k, v in ((conn or {}).get("spaces") or {}).items() if v.get("id") and k in DRIVE_SPACES}


async def prune_drive_data():
    roots = list((await current_roots()).values())
    await db.drive_docs.delete_many({"root_id": {"$nin": roots}})
    await db.drive_pins.delete_many({"root_id": {"$nin": roots}})


@router.put("/integrations/google-drive/shared-folder")
async def set_shared_folder(body: SharedFolderIn, admin=Depends(admin_user)):
    space = check_space(body.space)
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
    await db.integrations.update_one({"key": DRIVE_KEY}, {"$set": {f"spaces.{space}": {"id": fid, "name": meta["name"]}},
                                                          "$unset": {"shared_folder_id": "", "shared_folder_name": ""}})
    await prune_drive_data()
    spawn(index_drive())
    return {"space": space, "folder_id": fid, "folder_name": meta["name"]}


@router.delete("/integrations/google-drive/shared-folder")
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


POLICY_FOLDER_ID = "1jfsRbzHfkZs976wP_-lJCjP5iJ9I3-1U"


DEFAULT_SPACES = {"therapist": "1AkYaS-Rc10d0XiBfVKKU9rdhGMBvBfPP", "participant": "1_Bu1oeJN9syuP8pI9EjBLH5we_WgZa7d"}


def clean_pdf_text(text: str) -> str:
    """Drop page footers like 'P a g e 1 | 4' / 'Page 2 of 5' and collapse blank runs."""
    text = re.sub(r"(?im)^\s*(p\s*a\s*g\s*e\s*\d+\s*(\|\s*\d+)?|page\s+\d+\s+of\s+\d+)\s*$", "", text)
    text = re.sub(r"[ \t]+\n", "\n", text)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


async def import_policies_from_drive(svc, folder_id: str, by_name: str = "StaffHub") -> int:
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


async def ensure_drive_setup():
    """One-time (per database, once Drive is connected): default resource folders + policy import."""
    conn = await drive_conn()
    if not conn or await db.meta.find_one({"key": "drive_setup_v1"}):
        return
    svc = await run_in_threadpool(gs.drive_service, conn["refresh_token"])
    for space, fid in DEFAULT_SPACES.items():
        if not ((conn.get("spaces") or {}).get(space) or {}).get("id"):
            meta = await run_in_threadpool(gs.drive_get, svc, fid)
            await db.integrations.update_one({"key": DRIVE_KEY}, {"$set": {f"spaces.{space}": {
                "id": fid, "name": meta["name"]}}})
    count = await import_policies_from_drive(svc, POLICY_FOLDER_ID)
    await db.meta.insert_one({"key": "drive_setup_v1", "policies_imported": count, "created_at": now_iso()})
    logger.info(f"Drive setup done: {count} policies imported")


class PolicyImportIn(BaseModel):
    link: str


@router.post("/policies/import-drive")
async def import_policies(body: PolicyImportIn, admin=Depends(admin_user)):
    fid = gs.folder_id_from_link(body.link)
    if not fid:
        raise HTTPException(400, "Paste a Google Drive folder link")
    svc = await drive_svc_or_409()
    try:
        count = await import_policies_from_drive(svc, fid, admin["name"])
    except Exception as e:
        logger.error(f"Policy import failed: {e}")
        raise HTTPException(502, "Couldn't read that Drive folder")
    return {"imported": count}


async def index_drive():
    try:
        await ensure_drive_setup()
    except Exception as e:
        logger.error(f"Drive setup failed: {e}")
    if drive_index_lock.locked():
        return
    async with drive_index_lock:
        conn = await drive_conn()
        roots = list((await current_roots()).values())
        if not roots:
            await db.drive_docs.delete_many({})
            return
        try:
            svc = await run_in_threadpool(gs.drive_service, conn["refresh_token"])
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
                "modified": f.get("modifiedTime"), "text": text, "indexed_at": now_iso()}}, upsert=True)
        await db.drive_docs.delete_many({"$or": [{"root_id": {"$nin": roots}}, {"file_id": {"$nin": keep}}]})
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
    return {"last_run": m.get("last_run"), "count": await db.drive_docs.count_documents({"text": {"$ne": ""}}),
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
        raise HTTPException(502, "Could not load the company Drive folder")
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
    """Copy an uploaded file into Therapist / Participants Resources. Returns space -> 'added' | reason."""
    out = {}
    roots = await current_roots()
    conn = await drive_conn()
    for space in spaces:
        if space not in DRIVE_SPACES:
            out[space] = "unknown"
            continue
        if not conn or space not in roots:
            out[space] = "not_set_up"
            continue
        try:
            svc = await run_in_threadpool(gs.drive_service, conn["refresh_token"])
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
