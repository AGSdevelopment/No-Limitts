"""Admin compliance dashboard, Excel export and New Starter checklist."""
import io
from datetime import date
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import Response
from pydantic import BaseModel
from typing import List, Optional
from html import escape
from core import P, admin_user, new_id, bearer, current_user, db, dmy, logger, notify, now_iso, spawn, user_from_token
from email_service import send_email
from routes.certificates import cert_status
from routes.forms import forms_query
from routes.cpd import cpd_year_start

router = APIRouter(prefix="/api")


@router.get("/compliance")
async def compliance(admin=Depends(admin_user)):
    return await compliance_data()


@router.get("/compliance/export")
async def compliance_export(request: Request, token: Optional[str] = None):
    user = await user_from_token(bearer(request) or token)
    if not user or user["role"] != "admin":
        raise HTTPException(403, "Admins only")
    d = await compliance_data()
    from openpyxl import Workbook
    from openpyxl.styles import Font, PatternFill
    wb = Workbook()
    ws = wb.active
    ws.title = "Staff compliance"
    head = ["Name", "Staff group", "Policies acknowledged", "Policies pending", "Pending policy titles",
            "Certificates", "Expired", "Expiring (30 days)", "Certificate issues", "Missing required certificates", f"CPD hours {d['year']}",
            "Starter checklist", "Needs attention"]
    ws.append(head)
    for c in ws[1]:
        c.font = Font(bold=True, color="FFFFFF")
        c.fill = PatternFill("solid", fgColor="205890")
    for r in d["rows"]:
        issues = "; ".join(f"{c['title']} ({'expired' if c['status'] == 'expired' else 'expires'} {dmy(c['expiry_date'])})"
                           for c in r["certs_expired"] + r["certs_expiring"]) or ("No certificates" if r["no_certs"] else "")
        ws.append([r["name"], STAFF_GROUP_LABELS.get(r.get("staff_group"), "Admin" if r.get("role") == "admin" else ""),
                   r["policies_total"] - len(r["policies_pending"]), len(r["policies_pending"]),
                   "; ".join(r["policies_pending"]), r["certs_total"], len(r["certs_expired"]),
                   len(r["certs_expiring"]), issues, "; ".join(r["missing_required"]), r["cpd_hours"],
                   f"{r['starter']['done']}/{r['starter']['total']}" if r.get("starter") else "",
                   "Yes" if r["needs_attention"] else "No"])
    for col, w in zip("ABCDEFGHIJKLM", (24, 22, 12, 12, 60, 12, 10, 12, 50, 40, 12, 14, 12)):
        ws.column_dimensions[col].width = w
    s = d["summary"]
    ws2 = wb.create_sheet("Summary")
    for row in (("Generated", dmy(date.today().isoformat())), ("Staff", s["staff"]),
                ("Policies acknowledged %", s["policy_pct"]), ("Staff fully up to date", s["fully_acknowledged"]),
                ("Expired certificates", s["expired_certs"]), ("Expiring certificates", s["expiring_certs"]),
                ("Staff with no certificates", s["no_certs"]),
                ("Staff missing required certificates", s["missing_required"]),
                (f"Average CPD hours {d['year']}", s["avg_cpd"]), ("Staff needing attention", s["needs_attention"])):
        ws2.append(row)
    ws2.column_dimensions["A"].width = 30
    buf = io.BytesIO()
    wb.save(buf)
    return Response(content=buf.getvalue(),
                    media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    headers={"Content-Disposition": f'attachment; filename="StaffHub_Compliance_{date.today().isoformat()}.xlsx"'})


STAFF_GROUP_LABELS = {"support_office": "Support Office", "therapist_employee": "Therapist Employee",
                      "therapist_contractor": "Therapist Contractor", "support_worker_employee": "Support Worker Employee",
                      "support_worker_contractor": "Support Worker Contractor",
                      "new_starter_employee": "New Starter Employee", "new_starter_contractor": "New Starter Contractor"}


NEW_STARTER_GROUPS = ("new_starter_employee", "new_starter_contractor")


async def starter_checklist(user: dict) -> list:
    forms = await db.forms.find({"category": "New Starter", **forms_query(user)}, P).sort("title", 1).to_list(100)
    done = {d["item_key"]: d["done_at"] async for d in db.checklist_progress.find({"user_id": user["user_id"]}, P)}
    items = [{"key": f"form:{f['form_id']}", "type": "form", "title": f["title"], "form_id": f["form_id"],
              "url": f["url"],
              "description": f.get("description", ""), "done": f"form:{f['form_id']}" in done,
              "done_at": done.get(f"form:{f['form_id']}")} for f in forms]
    pols = await db.policies.find({}, {"_id": 0, "acknowledged_by": 1}).to_list(1000)
    acked = sum(1 for p in pols if user["user_id"] in (p.get("acknowledged_by") or []))
    items.append({"key": "policies", "type": "policies", "title": "Read and acknowledge all policies & procedures",
                  "done": acked == len(pols), "progress": [acked, len(pols)]})
    mine = await db.certificates.find({"owner_id": user["user_id"], "is_deleted": {"$ne": True}},
                                      {"_id": 0, "title": 1, "expiry_date": 1}).to_list(500)
    missing = missing_required(mine, (await requirements()).get(user.get("staff_group") or "", []))
    items.append({"key": "certificates", "type": "certificate", "title": "Upload your training certificates",
                  "description": ("Still needed: " + ", ".join(missing)) if missing else
                  "e.g. NDIS Worker Screening, Working with Children Check, First Aid",
                  "done": bool(mine) and not missing, "progress": [len(mine), None], "missing": missing})
    return items


@router.get("/starter-checklist")
async def get_starter_checklist(user=Depends(current_user)):
    items = await starter_checklist(user)
    return {"items": items, "done": sum(i["done"] for i in items), "total": len(items),
            "is_new_starter": user.get("staff_group") in NEW_STARTER_GROUPS}


@router.post("/starter-checklist/{item_key}")
async def toggle_starter_item(item_key: str, user=Depends(current_user)):
    if user.get("staff_group") not in NEW_STARTER_GROUPS:
        raise HTTPException(403, "Only New Starter staff can tick checklist steps")
    if not item_key.startswith("form:"):
        raise HTTPException(400, "This item completes automatically")
    if not await db.forms.find_one({"form_id": item_key[5:], "category": "New Starter", **forms_query(user)}):
        raise HTTPException(404, "Form not found")
    q = {"user_id": user["user_id"], "item_key": item_key}
    if await db.checklist_progress.find_one(q):
        await db.checklist_progress.delete_one(q)
        return {"done": False}
    await db.checklist_progress.insert_one({**q, "done_at": now_iso()})
    spawn(check_starter_complete(user))
    return {"done": True}


async def check_starter_complete(user: dict):
    """Tell every admin (in-app + email) the first time a new starter has finished every checklist step."""
    try:
        user = await db.users.find_one({"user_id": user["user_id"]}, P)
        if not user or user.get("staff_group") not in NEW_STARTER_GROUPS or user.get("starter_completed_at"):
            return
        items = await starter_checklist(user)
        if not items or not all(i["done"] for i in items):
            return
        res = await db.users.update_one({"user_id": user["user_id"], "starter_completed_at": {"$exists": False}},
                                        {"$set": {"starter_completed_at": now_iso()}})
        if not res.modified_count:
            return
        test_user = bool(user.get("hidden"))  # internal test accounts only alert the hidden test admins, no email
        admins = await db.users.find({"role": "admin", "hidden": True if test_user else {"$ne": True}}, P).to_list(200)
        await notify([a["user_id"] for a in admins], "starter", "New Starter checklist complete",
                     f"{user['name']} has finished every step. Tap to book their next check-in.",
                     f"/starter/{user['user_id']}")
        for a in [] if test_user else admins:
            if a.get("email") and not a["email"].endswith("@example.com"):
                await send_email(to=a["email"], subject=f"{user['name']} has finished the New Starter checklist", html=(
                    "<div style='font-family:Arial,sans-serif;max-width:520px;margin:0 auto;padding:24px'>"
                    f"<h2 style='color:#205890'>New Starter checklist complete</h2><p>Hi {escape(a['name'].split(' ')[0])},</p>"
                    f"<p><b>{escape(user['name'])}</b> has completed all {len(items)} steps of their New Starter "
                    "checklist (forms, policies and certificates).</p><p>Now's a good time to book their next check-in.</p></div>"))
    except Exception as e:
        logger.error(f"Starter completion check failed: {e}")


async def compliance_data():
    """Per-staff policy acknowledgement, certificate status and CPD hours (this year)."""
    users = await db.users.find({"hidden": {"$ne": True}}, {"_id": 0, "user_id": 1, "name": 1, "picture": 1, "email": 1,
                                                            "staff_group": 1, "role": 1}).sort("name", 1).to_list(2000)
    reqs = await requirements()
    policies = await db.policies.find({}, {"_id": 0, "policy_id": 1, "title": 1, "acknowledged_by": 1}).to_list(1000)
    certs = await db.certificates.find({"is_deleted": {"$ne": True}}, {"_id": 0, "owner_id": 1, "title": 1,
                                                                      "expiry_date": 1}).to_list(10000)
    year_start = cpd_year_start()
    hours = {}
    async for lg in db.cpd_logs.find({"date": {"$gte": year_start}}, {"_id": 0, "user_id": 1, "hours": 1}):
        hours[lg["user_id"]] = hours.get(lg["user_id"], 0) + lg["hours"]
    rows = []
    for u in users:
        uid = u["user_id"]
        pending = [p["title"] for p in policies if uid not in (p.get("acknowledged_by") or [])]
        mine = [{"title": c["title"], "expiry_date": c["expiry_date"], **cert_status(c["expiry_date"])}
                for c in certs if c.get("owner_id") == uid]
        expired = [c for c in mine if c["status"] == "expired"]
        expiring = [c for c in mine if c["status"] == "expiring"]
        rows.append({**u, "policies_total": len(policies), "policies_pending": pending,
                     "certs_total": len(mine), "certs_expired": expired, "certs_expiring": expiring,
                     "cpd_hours": round(hours.get(uid, 0), 2),
                     "no_certs": not mine, "missing_required": missing_required(mine, reqs.get(u.get("staff_group") or "", [])),
                     "needs_attention": False})
        rows[-1]["needs_attention"] = bool(pending or expired or expiring or not mine or rows[-1]["missing_required"])
        if u.get("staff_group") in NEW_STARTER_GROUPS:
            items = await starter_checklist(u)
            rows[-1]["starter"] = {"done": sum(i["done"] for i in items), "total": len(items)}
    n = len(rows) or 1
    ack_total = sum(r["policies_total"] - len(r["policies_pending"]) for r in rows)
    return {"rows": rows, "year": date.today().year, "summary": {
        "staff": len(rows),
        "policy_pct": round(100 * ack_total / (n * len(policies))) if policies else 100,
        "fully_acknowledged": sum(1 for r in rows if not r["policies_pending"]),
        "expired_certs": sum(len(r["certs_expired"]) for r in rows),
        "expiring_certs": sum(len(r["certs_expiring"]) for r in rows),
        "no_certs": sum(1 for r in rows if r["no_certs"]),
        "missing_required": sum(1 for r in rows if r["missing_required"]),
        "avg_cpd": round(sum(r["cpd_hours"] for r in rows) / n, 1),
        "needs_attention": sum(1 for r in rows if r["needs_attention"])}}


# ---- Required certificates per staff group
REQ_KEY = "cert_requirements"


async def requirements() -> dict:
    doc = await db.meta.find_one({"key": REQ_KEY}, P)
    return (doc or {}).get("groups", {})


def missing_required(certs: list, names: list) -> list:
    """A requirement is met by any certificate (not expired) whose title contains the requirement's name."""
    valid = [c["title"].lower() for c in certs if cert_status(c["expiry_date"])["status"] != "expired"]
    return [n for n in names if not any(n.lower() in t for t in valid)]


class RequirementsIn(BaseModel):
    staff_group: str
    names: List[str]


@router.get("/cert-requirements")
async def get_requirements(admin=Depends(admin_user)):
    return {"groups": await requirements()}


@router.put("/cert-requirements")
async def set_requirements(body: RequirementsIn, admin=Depends(admin_user)):
    if body.staff_group not in STAFF_GROUP_LABELS:
        raise HTTPException(400, "Unknown staff group")
    names = []
    for n in body.names:
        n = n.strip()[:80]
        if n and n.lower() not in [x.lower() for x in names]:
            names.append(n)
    groups = await requirements()
    groups[body.staff_group] = names
    await db.meta.update_one({"key": REQ_KEY}, {"$set": {"groups": groups}}, upsert=True)
    return {"groups": groups}


# ---- Certificate reminder emails
@router.post("/compliance/remind-certificates")
async def remind_certificates(preview: bool = False, admin=Depends(admin_user)):
    """In-app + email nudge to every staff member with no certificates or missing required ones.
    preview=true only counts who would be reminded."""
    rows = [r for r in (await compliance_data())["rows"] if r["no_certs"] or r["missing_required"]]
    if preview:
        return {"reminded": 0, "would_remind": len(rows)}
    for r in rows:
        need = ", ".join(r["missing_required"]) or "your training certificates"
        await notify([r["user_id"]], "certificate", "Please upload your certificates", f"Still needed: {need}",
                     "/upload-certificate")
        if r.get("email") and not r["email"].endswith("@example.com"):
            items = "".join(f"<li>{escape(n)}</li>" for n in r["missing_required"])
            await send_email(to=r["email"], subject="Reminder: please upload your training certificates", html=(
                "<div style='font-family:Arial,sans-serif;max-width:520px;margin:0 auto;padding:24px'>"
                f"<h2 style='color:#205890'>Certificates needed</h2><p>Hi {escape(r['name'].split(' ')[0])},</p>"
                + (f"<p>We don't have these certificates on file for you yet:</p><ul>{items}</ul>" if items else
                   "<p>We don't have any of your training certificates on file yet.</p>")
                + "<p>Open StaffHub → Certificates → Upload certificate and snap a photo or attach the file. "
                  "It only takes a minute.</p></div>"))
    return {"reminded": len(rows)}


# ---- Starter progress for admins + check-in booking
@router.get("/starter-checklist/user/{user_id}")
async def staff_checklist(user_id: str, admin=Depends(admin_user)):
    u = await db.users.find_one({"user_id": user_id}, P)
    if not u:
        raise HTTPException(404, "Staff member not found")
    items = await starter_checklist(u)
    checkins = await db.events.find({"checkin_for": user_id}, {"_id": 0, "attendees": 0}).sort("date", 1).to_list(50)
    return {"user": {k: u.get(k) for k in ("user_id", "name", "email", "picture", "staff_group")},
            "items": items, "done": sum(i["done"] for i in items), "total": len(items),
            "completed_at": u.get("starter_completed_at"), "checkins": checkins}


class CheckinIn(BaseModel):
    date: str
    time: str = ""
    location: str = ""
    note: str = ""


@router.post("/starter-checklist/user/{user_id}/checkin")
async def book_checkin(user_id: str, body: CheckinIn, admin=Depends(admin_user)):
    u = await db.users.find_one({"user_id": user_id}, P)
    if not u:
        raise HTTPException(404, "Staff member not found")
    try:
        if date.fromisoformat(body.date) < date.today():
            raise HTTPException(400, "Pick today or a future date")
    except ValueError:
        raise HTTPException(400, "Date must be YYYY-MM-DD")
    when = dmy(body.date) + (f" at {body.time.strip()}" if body.time.strip() else "")
    doc = {"event_id": new_id("evt"), "title": f"Check-in: {u['name']} with {admin['name']}",
           "description": body.note.strip(), "location": body.location.strip(), "date": body.date,
           "time": body.time.strip(), "attendees": [user_id, admin["user_id"]],
           "private_for": [user_id, admin["user_id"]], "checkin_for": user_id,
           "created_by": admin["name"], "created_at": now_iso()}
    await db.events.insert_one(dict(doc))
    await notify([user_id], "event", "Check-in booked", f"{admin['name']} booked a check-in with you on {when}",
                 "/events")
    if u.get("email") and not u["email"].endswith("@example.com") and not u.get("hidden"):
        await send_email(to=u["email"], subject=f"Your check-in with {admin['name']} on {when}", html=(
            "<div style='font-family:Arial,sans-serif;max-width:520px;margin:0 auto;padding:24px'>"
            f"<h2 style='color:#205890'>Check-in booked</h2><p>Hi {escape(u['name'].split(' ')[0])},</p>"
            f"<p>{escape(admin['name'])} has booked a check-in with you on <b>{escape(when)}</b>"
            + (f" at {escape(doc['location'])}" if doc["location"] else "") + ".</p>"
            + (f"<p>{escape(doc['description'])}</p>" if doc["description"] else "")
            + "<p>You'll find it under Events in StaffHub.</p></div>"))
    doc.pop("attendees")
    return doc


@router.delete("/starter-checklist/user/{user_id}/checkin/{event_id}")
async def cancel_checkin(user_id: str, event_id: str, admin=Depends(admin_user)):
    ev = await db.events.find_one({"event_id": event_id, "checkin_for": user_id}, P)
    if not ev:
        raise HTTPException(404, "Check-in not found")
    await db.events.delete_one({"event_id": event_id})
    when = dmy(ev["date"]) + (f" at {ev['time']}" if ev.get("time") else "")
    await notify([user_id], "event", "Check-in cancelled", f"Your check-in on {when} has been cancelled", "/events")
    return {"ok": True}
