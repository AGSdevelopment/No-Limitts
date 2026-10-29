"""Admin compliance dashboard, Excel export and New Starter checklist."""
import io
from datetime import date, datetime, timedelta
import asyncio
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import Response
from pydantic import BaseModel
from typing import List, Optional
from html import escape
from core import DIGEST_TZ, P, admin_user, new_id, bearer, current_user, db, dmy, logger, notify, now_iso, spawn, user_from_token
from email_service import send_email
from routes.certificates import REQ_KEY, cert_status, missing_required, requirements
from routes.forms import forms_query
from routes.cpd import cpd_year_start
from routes.calendar import cancel_invite, send_invite

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
        c.fill = PatternFill("solid", fgColor="673E8D")
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
                    headers={"Content-Disposition": f'attachment; filename="No Limitts_Compliance_{date.today().isoformat()}.xlsx"'})


STAFF_GROUP_LABELS = {"support_office": "Support Office", "support_coordinator": "Service & Support Coordinator",
                      "support_worker": "Support Worker"}


STARTER_DAYS = 30


def is_new_starter(u: dict) -> bool:
    """Support Workers in their first 30 days (from start date, or from when they were added)."""
    if not u or u.get("user_type") != "support_worker":
        return False
    try:
        start = date.fromisoformat((u.get("start_date") or u.get("created_at") or "")[:10])
    except ValueError:
        return False
    return start >= datetime.now(DIGEST_TZ).date() - timedelta(days=STARTER_DAYS)


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
            "is_new_starter": is_new_starter(user)}


@router.post("/starter-checklist/{item_key}")
async def toggle_starter_item(item_key: str, user=Depends(current_user)):
    if not is_new_starter(user):
        raise HTTPException(403, "Only new Support Workers can tick checklist steps")
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
        if not is_new_starter(user) or user.get("starter_completed_at"):
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
                    f"<h2 style='color:#673E8D'>New Starter checklist complete</h2><p>Hi {escape(a['name'].split(' ')[0])},</p>"
                    f"<p><b>{escape(user['name'])}</b> has completed all {len(items)} steps of their New Starter "
                    "checklist (forms, policies and certificates).</p><p>Now's a good time to book their next check-in.</p></div>"))
    except Exception as e:
        logger.error(f"Starter completion check failed: {e}")


async def compliance_data():
    """Per-staff policy acknowledgement, certificate status and CPD hours (this year)."""
    users = await db.users.find({"hidden": {"$ne": True}}, {"_id": 0, "user_id": 1, "name": 1, "picture": 1, "email": 1,
                                                            "staff_group": 1, "role": 1, "user_type": 1, "start_date": 1, "created_at": 1}).sort("name", 1).to_list(2000)
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
        if is_new_starter(u):
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
    return {"reminded": await send_cert_reminders(rows, "manual", admin["name"])}


async def send_cert_reminders(rows: list, trigger: str, by: str = "") -> int:
    await db.cert_reminder_log.insert_one({
        "log_id": new_id("rem"), "sent_at": now_iso(), "trigger": trigger, "by": by,
        "recipients": [{"user_id": r["user_id"], "name": r["name"], "email": r.get("email", ""),
                        "missing": r["missing_required"], "no_certs": r["no_certs"]} for r in rows]})
    for r in rows:
        need = ", ".join(r["missing_required"]) or "your training certificates"
        await notify([r["user_id"]], "certificate", "Please upload your certificates", f"Still needed: {need}",
                     "/upload-certificate")
        if r.get("email") and not r["email"].endswith("@example.com"):
            items = "".join(f"<li>{escape(n)}</li>" for n in r["missing_required"])
            await send_email(to=r["email"], subject="Reminder: please upload your training certificates", html=(
                "<div style='font-family:Arial,sans-serif;max-width:520px;margin:0 auto;padding:24px'>"
                f"<h2 style='color:#673E8D'>Certificates needed</h2><p>Hi {escape(r['name'].split(' ')[0])},</p>"
                + (f"<p>We don't have these certificates on file for you yet:</p><ul>{items}</ul>" if items else
                   "<p>We don't have any of your training certificates on file yet.</p>")
                + "<p>Open No Limitts → Certificates → Upload certificate and snap a photo or attach the file. "
                  "It only takes a minute.</p></div>"))
    return len(rows)


async def cert_reminder_loop():
    """First Monday of each month, 9am Perth: remind everyone with no or missing required certificates."""
    while True:
        try:
            local = datetime.now(DIGEST_TZ)
            if local.weekday() == 0 and local.day <= 7 and local.hour >= 9:
                key = f"cert_remind_{local.year}_{local.month:02d}"
                claim = await db.meta.update_one({"key": key}, {"$setOnInsert": {"created_at": now_iso()}}, upsert=True)
                if claim.upserted_id:  # only the first backend to claim this month sends
                    rows = [r for r in (await compliance_data())["rows"] if r["no_certs"] or r["missing_required"]]
                    n = await send_cert_reminders(rows, "monthly")
                    await db.meta.update_one({"key": key}, {"$set": {"reminded": n}})
                    logger.info(f"Monthly certificate reminders sent to {n} staff")
        except Exception as e:
            logger.error(f"Certificate reminder loop failed: {e}")
        await asyncio.sleep(1800)


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
           "organizer_id": admin["user_id"], "notes": "", "outcome": "",
           "created_by": admin["name"], "created_at": now_iso()}
    invite = {"calendar": "not_connected"}
    if u.get("email") and not u.get("hidden"):
        invite = await send_invite(admin["user_id"], doc, u["email"])
    doc.update(invite)
    await db.events.insert_one(dict(doc))
    await notify([user_id], "event", "Check-in booked", f"{admin['name']} booked a check-in with you on {when}",
                 "/events")
    if invite["calendar"] != "sent" and u.get("email") and not u["email"].endswith("@example.com") and not u.get("hidden"):
        await send_email(to=u["email"], subject=f"Your check-in with {admin['name']} on {when}", html=(
            "<div style='font-family:Arial,sans-serif;max-width:520px;margin:0 auto;padding:24px'>"
            f"<h2 style='color:#673E8D'>Check-in booked</h2><p>Hi {escape(u['name'].split(' ')[0])},</p>"
            f"<p>{escape(admin['name'])} has booked a check-in with you on <b>{escape(when)}</b>"
            + (f" at {escape(doc['location'])}" if doc["location"] else "") + ".</p>"
            + (f"<p>{escape(doc['description'])}</p>" if doc["description"] else "")
            + "<p>You'll find it under Events in No Limitts.</p></div>"))
    doc.pop("attendees")
    return doc


@router.delete("/starter-checklist/user/{user_id}/checkin/{event_id}")
async def cancel_checkin(user_id: str, event_id: str, admin=Depends(admin_user)):
    ev = await db.events.find_one({"event_id": event_id, "checkin_for": user_id}, P)
    if not ev:
        raise HTTPException(404, "Check-in not found")
    await db.events.delete_one({"event_id": event_id})
    if ev.get("outlook_event_id"):
        await cancel_invite(ev.get("organizer_id") or admin["user_id"], ev["outlook_event_id"])
    when = dmy(ev["date"]) + (f" at {ev['time']}" if ev.get("time") else "")
    await notify([user_id], "event", "Check-in cancelled", f"Your check-in on {when} has been cancelled", "/events")
    return {"ok": True}


CHECKIN_OUTCOMES = ("", "On track", "Needs support", "Follow-up needed")


class CheckinNotesIn(BaseModel):
    notes: str = ""
    outcome: str = ""


@router.put("/starter-checklist/user/{user_id}/checkin/{event_id}/notes")
async def checkin_notes(user_id: str, event_id: str, body: CheckinNotesIn, admin=Depends(admin_user)):
    """Admin-only notes and outcome after a check-in; never shown to the staff member."""
    if body.outcome not in CHECKIN_OUTCOMES:
        raise HTTPException(400, "Unknown outcome")
    res = await db.events.update_one({"event_id": event_id, "checkin_for": user_id}, {"$set": {
        "notes": body.notes.strip()[:4000], "outcome": body.outcome, "notes_by": admin["name"],
        "notes_at": now_iso()}})
    if not res.matched_count:
        raise HTTPException(404, "Check-in not found")
    ev = await db.events.find_one({"event_id": event_id}, {"_id": 0, "attendees": 0})
    if await create_followup(ev, admin):
        ev = await db.events.find_one({"event_id": event_id}, {"_id": 0, "attendees": 0})
        ev["followup_created"] = True
    return ev



@router.get("/compliance/reminder-history")
async def reminder_history(admin=Depends(admin_user)):
    return await db.cert_reminder_log.find({}, P).sort("sent_at", -1).to_list(100)


# ---- Follow-up tasks from check-ins
async def create_followup(ev: dict, admin: dict) -> Optional[str]:
    """'Follow-up needed' -> one shared task for the starter and the admin, due in 7 days (created once)."""
    if ev.get("outcome") != "Follow-up needed" or ev.get("followup_group_id"):
        return None
    claim = await db.events.update_one({"event_id": ev["event_id"], "followup_group_id": {"$exists": False}},
                                       {"$set": {"followup_group_id": "pending"}})
    if not claim.modified_count:
        return None
    from routes.tasks import TaskIn, create_task  # local import: tasks is a sibling module
    starter = await db.users.find_one({"user_id": ev["checkin_for"]}, P)
    if not starter:
        return None
    ids = list(dict.fromkeys([ev["checkin_for"], admin["user_id"]]))
    body = TaskIn(title=f"Follow up: check-in with {starter['name']}",
                  description=(ev.get("notes") or "Follow-up agreed at the check-in.")[:2000],
                  due_date=(datetime.now(DIGEST_TZ).date() + timedelta(days=7)).isoformat(), assignee_ids=ids)
    res = await create_task(body, admin)
    gid = res.get("group_id") or res.get("task_id")
    await db.events.update_one({"event_id": ev["event_id"]}, {"$set": {"followup_group_id": gid}})
    return gid


async def starter_reminder_loop():
    """Hourly (9am–5pm Perth): a one-time friendly nudge to Support Workers whose first-week checklist
    is still unfinished 5+ days after they started."""
    while True:
        try:
            now_p = datetime.now(DIGEST_TZ)
            if 9 <= now_p.hour < 17:
                cutoff = (now_p.date() - timedelta(days=5)).isoformat()
                async for u in db.users.find({"user_type": "support_worker", "hidden": {"$ne": True},
                                              "starter_completed_at": {"$exists": False},
                                              "starter_reminder_sent_at": {"$exists": False}}, P):
                    start = (u.get("start_date") or u.get("created_at") or "")[:10]
                    if not is_new_starter(u) or not start or start > cutoff:
                        continue
                    await send_starter_nudge(u)
                month_ago = (now_p.date() - timedelta(days=30)).isoformat()
                two_months = (now_p.date() - timedelta(days=60)).isoformat()  # long-serving staff get the monthly reminder instead
                async for u in db.users.find({"user_type": "support_worker", "hidden": {"$ne": True},
                                              "cert_month_nudge_at": {"$exists": False}}, P):
                    start = (u.get("start_date") or u.get("created_at") or "")[:10]
                    if start and two_months <= start <= month_ago:
                        await send_cert_month_nudge(u)
        except Exception as e:
            logger.error(f"Starter reminder loop failed: {e}")
        await asyncio.sleep(3600)


async def send_starter_nudge(u: dict) -> bool:
    """Claim, then notify + email the remaining steps. Returns False if already sent or nothing left."""
    items = await starter_checklist(u)
    left = [i for i in items if not i["done"]]
    if not left:
        return False
    claim = await db.users.update_one({"user_id": u["user_id"], "starter_reminder_sent_at": {"$exists": False}},
                                      {"$set": {"starter_reminder_sent_at": now_iso()}})
    if not claim.modified_count:
        return False
    await notify([u["user_id"]], "starter", "A few steps left on your checklist",
                 f"{len(left)} of {len(items)} first-week steps still to go. You're nearly there!", "/starter-checklist")
    if u.get("email") and not u["email"].endswith("@example.com"):
        steps = "".join(f"<li>{escape(i['title'])}</li>" for i in left)
        await send_email(to=u["email"], subject="A friendly nudge: your No Limitts first-week checklist", html=(
            "<div style='font-family:Arial,sans-serif;max-width:520px;margin:0 auto;padding:24px'>"
            f"<h2 style='color:#673E8D'>You're doing great, {escape(u['name'].split(' ')[0])}!</h2>"
            f"<p>Just a friendly reminder that a few steps of your first-week checklist are still open "
            f"({len(items) - len(left)} of {len(items)} done):</p><ul>{steps}</ul>"
            "<p>Open the No Limitts app and tap <b>Your first-week checklist</b> on the Home screen to finish up. "
            "If anything's unclear, message your admin in the app. We're happy to help!</p></div>"))
    return True


async def send_cert_month_nudge(u: dict) -> bool:
    """One month in: a one-time reminder listing required certificates a Support Worker still hasn't uploaded."""
    reqs = (await requirements()).get(u.get("staff_group") or "", [])
    if not reqs:
        return False  # nothing required yet: don't mark them, so they're nudged if requirements are added later
    mine = await db.certificates.find({"owner_id": u["user_id"], "is_deleted": {"$ne": True}},
                                      {"_id": 0, "title": 1, "expiry_date": 1}).to_list(500)
    missing = missing_required(mine, reqs)
    claim = await db.users.update_one({"user_id": u["user_id"], "cert_month_nudge_at": {"$exists": False}},
                                      {"$set": {"cert_month_nudge_at": now_iso()}})
    if not claim.modified_count or not missing:
        return False
    await notify([u["user_id"]], "certificate", "Training certificates still needed",
                 f"Please upload: {', '.join(missing)[:160]}", "/upload-certificate")
    if u.get("email") and not u["email"].endswith("@example.com"):
        items = "".join(f"<li>{escape(m)}</li>" for m in missing)
        await send_email(to=u["email"], subject="Reminder: training certificates needed for No Limitts", html=(
            "<div style='font-family:Arial,sans-serif;max-width:520px;margin:0 auto;padding:24px'>"
            f"<h2 style='color:#673E8D'>Hi {escape(u['name'].split(' ')[0])}, one month in!</h2>"
            "<p>Thanks for your first month with No Limitts. To stay compliant we still need these training "
            f"certificates from you:</p><ul>{items}</ul>"
            "<p>Open the No Limitts app, go to <b>Certificates</b> and tap <b>Upload</b>. A photo of the certificate is fine. "
            "If you're still waiting on one, let your admin know.</p></div>"))
    return True


# ---- In-app welcome + probation for a new Support Worker (the welcome email is sent from routes/users.py)
async def send_starter_welcome(user_id: str):
    try:
        u = await db.users.find_one({"user_id": user_id}, P)
        if not is_new_starter(u):
            return
        from routes.profile import default_probation  # local import: profile imports this module
        await default_probation(user_id)
        claim = await db.users.update_one({"user_id": user_id, "welcome_sent_at": {"$exists": False}},
                                          {"$set": {"welcome_sent_at": now_iso()}})
        if not claim.modified_count:
            return
        items = await starter_checklist(u)
        await notify([user_id], "starter", "Welcome to No Limitts!",
                     f"Your first-week checklist has {len(items)} steps to get you set up.", "/starter-checklist")
    except Exception as e:
        logger.error(f"Starter welcome failed: {e}")
