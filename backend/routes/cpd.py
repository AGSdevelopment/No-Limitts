"""CPD log, PDF report and shared resources."""
from datetime import date
from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import Response
from html import escape
from pydantic import BaseModel
from typing import Optional
import re
import uuid
from core import HIDDEN_TEST_USERS, MAX_UPLOAD_BYTES, P, admin_user, all_user_ids, bearer, current_user, db, dmy, logger, new_id, notify, now_iso, user_from_token
from storage import APP_NAME, get_object, put_object
import ai_service

router = APIRouter(prefix="/api")


class CpdIn(BaseModel):
    title: str
    provider: str = ""
    date: str
    hours: float
    category: str = ""
    notes: str = ""


def cpd_year_start() -> str:
    return f"{date.today().year}-01-01"


@router.get("/cpd")
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


@router.post("/cpd")
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


def build_cpd_report(user: dict, year: int, logs: list, evidence: dict) -> bytes:
    """Summary table + every attached certificate (PDF pages / images) appended as evidence."""
    import pymupdf
    doc = pymupdf.open()
    total = round(sum(lg["hours"] for lg in logs), 2)
    rows = "".join(
        f"<tr><td>{escape(dmy(lg['date']))}</td><td>{escape(lg['title'])}"
        f"{'<br/><i>' + escape(lg['provider']) + '</i>' if lg.get('provider') else ''}</td>"
        f"<td>{escape(lg.get('category') or '')}</td><td style='text-align:right'>{lg['hours']}</td>"
        f"<td>{'Attached' if lg['log_id'] in evidence else '-'}</td></tr>" for lg in logs)
    html = (f"<h2 style='color:#673E8D'>CPD Report {year}</h2>"
            f"<p><b>{escape(user['name'])}</b><br/>{escape(user.get('email', ''))}</p>"
            f"<p>Total CPD hours: <b>{total}</b> across {len(logs)} activit{'y' if len(logs) == 1 else 'ies'}.<br/>"
            f"Generated {dmy(date.today().isoformat())} by No Limitts (Aspire &amp; Grow).</p>"
            "<table style='width:100%;border-collapse:collapse;font-size:10px' border='1' cellpadding='4'>"
            "<tr style='background:#EFE8F5'><th>Date</th><th>Activity</th><th>Type</th><th>Hours</th><th>Evidence</th></tr>"
            f"{rows or '<tr><td colspan=5>No CPD logged this year.</td></tr>'}</table>")
    rect = pymupdf.paper_rect("a4") + (40, 40, -40, -40)
    story = pymupdf.Story(html=html)
    writer_buf = __import__("io").BytesIO()
    writer = pymupdf.DocumentWriter(writer_buf)
    more = True
    while more:
        dev = writer.begin_page(pymupdf.paper_rect("a4"))
        more, _ = story.place(rect)
        story.draw(dev)
        writer.end_page()
    writer.close()
    doc.insert_pdf(pymupdf.open("pdf", writer_buf.getvalue()))
    for lg in logs:
        ev = evidence.get(lg["log_id"])
        if not ev:
            continue
        data, ctype = ev
        try:
            if "pdf" in ctype:
                doc.insert_pdf(pymupdf.open("pdf", data))
            else:
                page = doc.new_page(width=595, height=842)
                page.insert_text((40, 50), f"Evidence: {lg['title']} ({dmy(lg['date'])}, {lg['hours']} h)",
                                 fontsize=11)
                page.insert_image(pymupdf.Rect(40, 70, 555, 800), stream=data, keep_proportion=True)
        except Exception as e:
            logger.warning(f"CPD report evidence skipped for {lg['log_id']}: {e}")
    out = doc.tobytes()
    doc.close()
    return out


@router.get("/cpd/report")
async def cpd_report(request: Request, year: int = 0, token: Optional[str] = None):
    user = await user_from_token(bearer(request) or token)
    if not user:
        raise HTTPException(401, "Not authenticated")
    year = year or date.today().year
    logs = await db.cpd_logs.find({"user_id": user["user_id"], "date": {"$gte": f"{year}-01-01",
                                                                       "$lte": f"{year}-12-31"}}, P
                                  ).sort("date", 1).to_list(500)
    evidence = {}
    for lg in logs:
        if lg.get("storage_path"):
            try:
                data, ctype = await run_in_threadpool(get_object, lg["storage_path"])
                evidence[lg["log_id"]] = (data, lg.get("content_type") or ctype)
            except Exception as e:
                logger.warning(f"CPD evidence fetch failed: {e}")
    pdf = await run_in_threadpool(build_cpd_report, user, year, logs, evidence)
    name = re.sub(r"[^A-Za-z0-9]+", "_", user["name"]).strip("_")
    return Response(content=pdf, media_type="application/pdf",
                    headers={"Content-Disposition": f'inline; filename="CPD_Report_{year}_{name}.pdf"'})


@router.patch("/cpd/{log_id}")
async def update_cpd(log_id: str, body: CpdIn, user=Depends(current_user)):
    if not body.title.strip():
        raise HTTPException(400, "Enter what you did")
    try:
        date.fromisoformat(body.date)
    except ValueError:
        raise HTTPException(400, "Date must be YYYY-MM-DD")
    if not (0 < body.hours <= 200):
        raise HTTPException(400, "Hours must be between 0 and 200")
    upd = {"title": body.title.strip()[:200], "provider": body.provider.strip()[:200], "date": body.date,
           "hours": round(body.hours, 2), "category": body.category.strip()[:60], "notes": body.notes.strip()[:2000],
           "updated_at": now_iso()}
    res = await db.cpd_logs.update_one({"log_id": log_id, "user_id": user["user_id"]}, {"$set": upd})
    if not res.matched_count:
        raise HTTPException(404, "Entry not found")
    return await db.cpd_logs.find_one({"log_id": log_id}, P)


@router.delete("/cpd/{log_id}")
async def delete_cpd(log_id: str, user=Depends(current_user)):
    q = {"log_id": log_id}
    if user["role"] != "admin":
        q["user_id"] = user["user_id"]
    if not (await db.cpd_logs.delete_one(q)).deleted_count:
        raise HTTPException(404, "Entry not found")
    return {"ok": True}


ALLOWED_DOC_TYPES = ("image/png", "image/jpeg", "image/jpg", "image/webp")


def check_doc(data: bytes, ctype: str):
    if not data or len(data) > MAX_UPLOAD_BYTES:
        raise HTTPException(400, "File is empty or too large (max 15 MB)")
    if not ("pdf" in ctype or ctype in ALLOWED_DOC_TYPES):
        raise HTTPException(415, "Use a PDF, JPG or PNG")


@router.post("/cpd/extract")
async def cpd_extract(file: UploadFile = File(...), user=Depends(current_user)):
    data = await file.read()
    ctype = file.content_type or ""
    check_doc(data, ctype)
    try:
        return await ai_service.extract_cpd(data, ctype)
    except Exception as e:
        logger.error(f"CPD extract failed: {e}")
        raise HTTPException(502, "Couldn't read the certificate. Please fill in the details manually.")


@router.post("/cpd/{log_id}/file")
async def cpd_attach(log_id: str, file: UploadFile = File(...), user=Depends(current_user)):
    log = await db.cpd_logs.find_one({"log_id": log_id, "user_id": user["user_id"]}, P)
    if not log:
        raise HTTPException(404, "Entry not found")
    data = await file.read()
    ctype = file.content_type or "application/octet-stream"
    check_doc(data, ctype)
    ext = (file.filename or "file").rsplit(".", 1)[-1].lower() if "." in (file.filename or "") else "bin"
    path = f"{APP_NAME}/cpd/{user['user_id']}/{uuid.uuid4().hex}.{ext}"
    try:
        result = await run_in_threadpool(put_object, path, data, ctype)
    except Exception as e:
        logger.error(f"CPD upload failed: {e}")
        raise HTTPException(502, "Could not store the file, please try again")
    upd = {"storage_path": result["path"], "file_name": file.filename or "certificate", "content_type": ctype}
    await db.cpd_logs.update_one({"log_id": log_id}, {"$set": upd})
    return {**log, **upd}


@router.get("/cpd/{log_id}/file")
async def cpd_file(log_id: str, request: Request, token: Optional[str] = None):
    user = await user_from_token(bearer(request) or token)
    if not user:
        raise HTTPException(401, "Not authenticated")
    log = await db.cpd_logs.find_one({"log_id": log_id}, P)
    if not log or not log.get("storage_path") or (log["user_id"] != user["user_id"] and user["role"] != "admin"):
        raise HTTPException(404, "File not found")
    data, ctype = await run_in_threadpool(get_object, log["storage_path"])
    safe = re.sub(r'[^A-Za-z0-9 ._()-]', "_", log["file_name"])
    return Response(content=data, media_type=log.get("content_type") or ctype,
                    headers={"Content-Disposition": f'inline; filename="{safe}"'})


CPD_SECTIONS = ("Courses", "Webinars", "Case Studies", "Resource Links")


def cpd_section(value: str) -> str:
    v = (value or "").strip().lower()
    if v.startswith("course"):
        return "Courses"
    if v.startswith("webinar"):
        return "Webinars"
    if v.startswith("case stud"):
        return "Case Studies"
    return "Resource Links"


class CpdResourceIn(BaseModel):
    title: str
    description: str = ""
    url: str = ""
    category: str = ""


class CpdShareIn(BaseModel):
    category: str = ""
    description: str = ""


@router.get("/cpd/resources")
async def list_cpd_resources(user=Depends(current_user)):
    docs = await db.cpd_resources.find({}, P).sort("created_at", -1).to_list(500)
    for d in docs:
        d["category"] = cpd_section(d.get("category", ""))
        d["has_file"] = bool(d.pop("storage_path", None))
    return docs


@router.post("/cpd/resources")
async def add_cpd_resource(body: CpdResourceIn, admin=Depends(admin_user)):
    if not body.title.strip():
        raise HTTPException(400, "Enter a title")
    url = body.url.strip()
    if url and not url.startswith(("https://", "http://")):
        url = "https://" + url
    doc = {"resource_id": new_id("cpdr"), "title": body.title.strip()[:200], "description": body.description.strip()[:2000],
           "url": url[:1000], "category": cpd_section(body.category), "created_by": admin["name"],
           "created_by_id": admin["user_id"], "created_at": now_iso()}
    await db.cpd_resources.insert_one(dict(doc))
    await notify(await all_user_ids(admin["user_id"]), "update", "New CPD resource", doc["title"], "/cpd")
    return doc


@router.post("/cpd/{log_id}/share")
async def share_cpd(log_id: str, body: CpdShareIn, user=Depends(current_user)):
    """Contribute a CPD entry (and its attached document) to the shared CPD Resource Library."""
    log = await db.cpd_logs.find_one({"log_id": log_id, "user_id": user["user_id"]}, P)
    if not log:
        raise HTTPException(404, "Entry not found")
    if await db.cpd_resources.find_one({"source_log_id": log_id}):
        raise HTTPException(409, "Already shared to the library")
    desc = body.description.strip() or " · ".join(x for x in (log.get("provider"), f"{log['hours']} hours") if x)
    doc = {"resource_id": new_id("cpdr"), "title": log["title"], "description": desc[:2000], "url": "",
           "category": cpd_section(body.category or log.get("category", "")), "created_by": user["name"],
           "created_by_id": user["user_id"], "source_log_id": log_id, "created_at": now_iso()}
    if log.get("storage_path"):
        doc.update({"storage_path": log["storage_path"], "file_name": log.get("file_name", "document"),
                    "content_type": log.get("content_type")})
    await db.cpd_resources.insert_one(dict(doc))
    await db.cpd_logs.update_one({"log_id": log_id}, {"$set": {"shared_resource_id": doc["resource_id"]}})
    await notify(await all_user_ids(user["user_id"]), "update", "New CPD resource", doc["title"], "/cpd")
    doc.pop("storage_path", None)
    return doc


@router.get("/cpd/resources/{resource_id}/file")
async def cpd_resource_file(resource_id: str, request: Request, token: Optional[str] = None):
    user = await user_from_token(bearer(request) or token)
    if not user:
        raise HTTPException(401, "Not authenticated")
    r = await db.cpd_resources.find_one({"resource_id": resource_id}, P)
    if not r or not r.get("storage_path"):
        raise HTTPException(404, "File not found")
    data, ctype = await run_in_threadpool(get_object, r["storage_path"])
    safe = re.sub(r'[^A-Za-z0-9 ._()-]', "_", r.get("file_name", "document"))
    return Response(content=data, media_type=r.get("content_type") or ctype,
                    headers={"Content-Disposition": f'inline; filename="{safe}"'})


@router.delete("/cpd/resources/{resource_id}")
async def delete_cpd_resource(resource_id: str, admin=Depends(admin_user)):
    q = {"resource_id": resource_id}
    if not (await db.cpd_resources.delete_one(q)).deleted_count:
        raise HTTPException(404, "Resource not found")
    await db.cpd_logs.update_many({"shared_resource_id": resource_id}, {"$unset": {"shared_resource_id": ""}})
    return {"ok": True}



LOG_CATEGORY = {"Courses": "Course", "Webinars": "Webinar", "Case Studies": "Case Study",
                "Resource Links": "Resource link"}


async def share_file_to_resources(cert: dict, category: str, user: dict) -> str:
    """Add an uploaded certificate/document to the shared CPD Resource Library."""
    desc = " · ".join(x for x in (cert.get("issuer"), f"Shared by {user['name']}") if x)
    doc = {"resource_id": new_id("cpdr"), "title": cert["title"], "description": desc[:2000], "url": "",
           "category": cpd_section(category), "created_by": user["name"], "created_by_id": user["user_id"],
           "storage_path": cert["storage_path"], "file_name": cert["file_name"], "content_type": cert["content_type"],
           "source_cert_id": cert.get("cert_id"), "created_at": now_iso()}
    await db.cpd_resources.insert_one(doc)
    if cert.get("cpd_log_id"):
        await db.cpd_logs.update_one({"log_id": cert["cpd_log_id"]}, {"$set": {
            "shared_resource_id": doc["resource_id"], "category": LOG_CATEGORY[doc["category"]]}})
    await notify(await all_user_ids(user["user_id"]), "update", "New CPD resource", doc["title"], "/cpd")
    return doc["resource_id"]
