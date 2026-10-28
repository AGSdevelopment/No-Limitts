"""Admin staff profile: certificates, CPD, policies, check-ins and starter progress on one page."""
import asyncio
import re
from datetime import date, datetime, timedelta
from html import escape
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import Response
from pydantic import BaseModel
from core import DIGEST_TZ, P, admin_user, bearer, db, dmy, logger, notify, user_from_token
from email_service import send_email
from routes.certificates import missing_required, requirements, with_status
from routes.compliance import NEW_STARTER_GROUPS, STAFF_GROUP_LABELS, starter_checklist
from routes.cpd import cpd_year_start
from routes.tasks import TaskIn, create_task

router = APIRouter(prefix="/api")


@router.get("/staff/{user_id}/profile")
async def staff_profile(user_id: str, admin=Depends(admin_user)):
    return await profile_data(user_id)


async def profile_data(user_id: str) -> dict:
    u = await db.users.find_one({"user_id": user_id}, P)
    if not u:
        raise HTTPException(404, "Staff member not found")
    certs = [with_status(c) for c in await db.certificates.find(
        {"owner_id": user_id, "is_deleted": {"$ne": True}}, P).sort("expiry_date", 1).to_list(500)]
    year_start = cpd_year_start()
    cpd = await db.cpd_logs.find({"user_id": user_id}, {"_id": 0, "log_id": 1, "title": 1, "type": 1, "hours": 1,
                                                        "date": 1}).sort("date", -1).to_list(500)
    policies = await db.policies.find({}, {"_id": 0, "policy_id": 1, "title": 1, "acknowledged_by": 1,
                                           "version": 1}).sort("title", 1).to_list(1000)
    checkins = await db.events.find({"checkin_for": user_id}, {"_id": 0, "attendees": 0}).sort("date", -1).to_list(100)
    starter = None
    if u.get("staff_group") in NEW_STARTER_GROUPS:
        items = await starter_checklist(u)
        starter = {"done": sum(i["done"] for i in items), "total": len(items)}
    return {
        "user": {k: u.get(k) for k in ("user_id", "name", "email", "picture", "role", "staff_group", "created_at",
                                        "start_date", "probation_end", "buddy_id", "buddy_name")},
        "certificates": certs,
        "missing_required": missing_required(certs, (await requirements()).get(u.get("staff_group") or "", [])),
        "cpd": {"year_hours": round(sum(c["hours"] for c in cpd if c["date"] >= year_start), 2),
                "year": int(year_start[:4]), "logs": cpd[:20], "total_logs": len(cpd)},
        "policies": [{"policy_id": p["policy_id"], "title": p["title"],
                      "acknowledged": user_id in (p.get("acknowledged_by") or [])} for p in policies],
        "checkins": checkins, "starter": starter,
        "open_tasks": await db.tasks.count_documents({"assignee_id": user_id, "status": "open"}),
    }


def add_months(d: date, months: int) -> date:
    y, m = divmod(d.month - 1 + months, 12)
    y, m = d.year + y, m + 1
    for day in (d.day, 30, 29, 28):
        try:
            return date(y, m, day)
        except ValueError:
            continue


PROBATION_MONTHS = 12


def perth_today() -> date:
    return datetime.now(DIGEST_TZ).date()


# ---- Probation
class ProbationIn(BaseModel):
    start_date: Optional[str] = None
    probation_end: Optional[str] = None


@router.patch("/staff/{user_id}/probation")
async def set_probation(user_id: str, body: ProbationIn, admin=Depends(admin_user)):
    u = await db.users.find_one({"user_id": user_id}, P)
    if not u:
        raise HTTPException(404, "Staff member not found")
    upd = {}
    try:
        if body.start_date:
            upd["start_date"] = date.fromisoformat(body.start_date).isoformat()
        if body.probation_end:
            upd["probation_end"] = date.fromisoformat(body.probation_end).isoformat()
        elif body.start_date:
            upd["probation_end"] = add_months(date.fromisoformat(body.start_date), PROBATION_MONTHS).isoformat()
    except ValueError:
        raise HTTPException(400, "Dates must be YYYY-MM-DD")
    if not upd:
        raise HTTPException(400, "Nothing to update")
    start = upd.get("start_date") or u.get("start_date")
    if start and upd.get("probation_end") and upd["probation_end"] <= start:
        raise HTTPException(400, "Probation must end after the start date")
    if upd.get("probation_end") != u.get("probation_end"):
        upd["probation_reminded_for"] = None
    await db.users.update_one({"user_id": user_id}, {"$set": upd})
    return {k: v for k, v in upd.items() if k != "probation_reminded_for"}


async def default_probation(user_id: str):
    """New starters get a start date of today and a 12-month probation unless one is already set."""
    start = perth_today()
    await db.users.update_one({"user_id": user_id, "probation_end": {"$in": [None, ""]}}, {"$set": {
        "start_date": start.isoformat(), "probation_end": add_months(start, PROBATION_MONTHS).isoformat()}})


async def probation_reminder_loop():
    """Daily: tell every admin (in-app + email) two weeks before a staff member's probation ends."""
    while True:
        try:
            cutoff = (perth_today() + timedelta(days=14)).isoformat()
            today = perth_today().isoformat()
            async for u in db.users.find({"probation_end": {"$gte": today, "$lte": cutoff}}, P):
                claim = await db.users.update_one(
                    {"user_id": u["user_id"], "probation_reminded_for": {"$ne": u["probation_end"]}},
                    {"$set": {"probation_reminded_for": u["probation_end"]}})
                if not claim.modified_count:
                    continue
                hidden = bool(u.get("hidden"))
                admins = await db.users.find({"role": "admin", "hidden": True if hidden else {"$ne": True}},
                                             P).to_list(200)
                when = dmy(u["probation_end"])
                await notify([a["user_id"] for a in admins], "starter", "Probation ending soon",
                             f"{u['name']}'s probation ends on {when}. Time to plan their review.",
                             f"/staff/{u['user_id']}")
                for a in [] if hidden else admins:
                    if a.get("email") and not a["email"].endswith("@example.com"):
                        await send_email(to=a["email"], subject=f"{u['name']}'s probation ends on {when}", html=(
                            "<div style='font-family:Arial,sans-serif;max-width:520px;margin:0 auto;padding:24px'>"
                            f"<h2 style='color:#205890'>Probation ending soon</h2>"
                            f"<p>Hi {escape(a['name'].split(' ')[0])},</p><p><b>{escape(u['name'])}</b>'s "
                            f"probation period ends on <b>{when}</b>, two weeks from now.</p>"
                            "<p>Open their staff profile in StaffHub to review certificates, CPD, policies and "
                            "check-in notes before their probation review.</p></div>"))
                logger.info(f"Probation reminder sent for {u['user_id']}")
        except Exception as e:
            logger.error(f"Probation reminder loop failed: {e}")
        await asyncio.sleep(3600)


# ---- Starter buddy
BUDDY_TASKS = [
    (1, "Send {first} a welcome message",
     "Say hello, introduce yourself as their buddy and let them know they can ask you anything."),
    (7, "Coffee catch-up with {first}",
     "Grab a coffee (or a video call) and see how their first week is going."),
    (30, "30-day check-in with {first}",
     "Check how they're settling in after a month and flag anything they need to the admin team."),
]


class BuddyIn(BaseModel):
    buddy_id: Optional[str] = None


@router.put("/staff/{user_id}/buddy")
async def set_buddy(user_id: str, body: BuddyIn, admin=Depends(admin_user)):
    u = await db.users.find_one({"user_id": user_id}, P)
    if not u:
        raise HTTPException(404, "Staff member not found")
    if not body.buddy_id:
        await db.users.update_one({"user_id": user_id}, {"$set": {"buddy_id": None, "buddy_name": None}})
        return {"buddy_id": None, "buddy_name": None, "tasks_created": 0}
    if body.buddy_id == user_id:
        raise HTTPException(400, "Someone can't be their own buddy")
    b = await db.users.find_one({"user_id": body.buddy_id}, P)
    if not b:
        raise HTTPException(404, "Buddy not found")
    if u.get("buddy_id") == b["user_id"]:
        return {"buddy_id": b["user_id"], "buddy_name": b["name"], "tasks_created": 0}
    await db.users.update_one({"user_id": user_id}, {"$set": {"buddy_id": b["user_id"], "buddy_name": b["name"]}})
    first = u["name"].split(" ")[0]
    today = perth_today()
    for days, title, desc in BUDDY_TASKS:
        await create_task(TaskIn(title=title.format(first=first), description=desc,
                                 due_date=(today + timedelta(days=days)).isoformat(), assignee_id=b["user_id"]), admin)
    await notify([b["user_id"]], "starter", "You're a new starter buddy!",
                 f"You've been paired with {u['name']}. We've added 3 buddy tasks for you.", "/tasks")
    await notify([user_id], "starter", "Meet your buddy",
                 f"{b['name']} is your buddy. Reach out to them with any questions.", "/team")
    return {"buddy_id": b["user_id"], "buddy_name": b["name"], "tasks_created": len(BUDDY_TASKS)}


# ---- One-page PDF
def build_profile_pdf(d: dict) -> bytes:
    import pymupdf
    u = d["user"]
    acked = [p for p in d["policies"] if p["acknowledged"]]
    pending = [p["title"] for p in d["policies"] if not p["acknowledged"]]
    certs = "".join(f"<tr><td>{escape(c['title'])}</td><td>{dmy(c['expiry_date'])}</td>"
                    f"<td>{escape(c['status'].title())}</td></tr>" for c in d["certificates"][:12])
    certs += "".join(f"<tr><td>{escape(n)}</td><td>-</td><td style='color:#B42318'>Required, missing</td></tr>"
                     for n in d["missing_required"])
    cpd = "".join(f"<tr><td>{dmy(c['date'])}</td><td>{escape(c['title'])}</td><td>{c['hours']}</td></tr>"
                  for c in d["cpd"]["logs"][:8])
    checks = "".join(f"<tr><td>{dmy(c['date'])}</td><td>{escape(c.get('outcome') or '-')}</td>"
                     f"<td>{escape((c.get('notes') or '')[:220])}</td></tr>" for c in d["checkins"][:4])
    meta = []
    if u.get("start_date"):
        meta.append(f"Started {dmy(u['start_date'])}")
    if u.get("probation_end"):
        meta.append(f"Probation ends {dmy(u['probation_end'])}")
    if u.get("buddy_name"):
        meta.append(f"Buddy: {escape(u['buddy_name'])}")
    if d["starter"]:
        meta.append(f"Starter checklist {d['starter']['done']}/{d['starter']['total']}")
    tbl = "<table style='width:100%;border-collapse:collapse;font-size:8.5px' border='1' cellpadding='3'>"
    html = (f"<h2 style='color:#205890;margin:0'>Staff profile: {escape(u['name'])}</h2>"
            f"<p style='font-size:9.5px'>{escape(u.get('email') or '')} · "
            f"{'Admin' if u.get('role') == 'admin' else 'Employee'}"
            f"{' · ' + escape(d.get('group_label') or '') if d.get('group_label') else ''}"
            f"{'<br/>' + ' · '.join(meta) if meta else ''}<br/>"
            f"Generated {dmy(date.today().isoformat())} by StaffHub (Aspire &amp; Grow)</p>"
            f"<p style='font-size:9.5px'><b>Summary:</b> {len(d['certificates'])} certificates · "
            f"{d['cpd']['year_hours']} CPD hours in {d['cpd']['year']} · {len(acked)}/{len(d['policies'])} policies "
            f"acknowledged · {d['open_tasks']} open tasks</p>"
            f"<h4 style='color:#205890'>Certificates</h4>{tbl}<tr style='background:#E3F1FE'><th>Certificate</th>"
            f"<th>Expiry</th><th>Status</th></tr>{certs or '<tr><td colspan=3>None on file</td></tr>'}</table>"
            f"<h4 style='color:#205890'>CPD {d['cpd']['year']} (latest)</h4>{tbl}<tr style='background:#E3F1FE'>"
            f"<th>Date</th><th>Activity</th><th>Hours</th></tr>{cpd or '<tr><td colspan=3>None logged</td></tr>'}</table>"
            f"<h4 style='color:#205890'>Policies not yet acknowledged ({len(pending)})</h4>"
            f"<p style='font-size:8.5px'>{escape(', '.join(pending[:25])) or 'All acknowledged'}"
            f"{' and ' + str(len(pending) - 25) + ' more' if len(pending) > 25 else ''}</p>"
            f"<h4 style='color:#205890'>Check-ins (latest)</h4>{tbl}<tr style='background:#E3F1FE'><th>Date</th>"
            f"<th>Outcome</th><th>Notes</th></tr>{checks or '<tr><td colspan=3>None yet</td></tr>'}</table>")
    import io
    buf = io.BytesIO()
    writer = pymupdf.DocumentWriter(buf)
    dev = writer.begin_page(pymupdf.paper_rect("a4"))
    story = pymupdf.Story(html=html)
    story.place(pymupdf.paper_rect("a4") + (36, 36, -36, -36))  # one page: anything beyond is cut
    story.draw(dev)
    writer.end_page()
    writer.close()
    return buf.getvalue()


@router.get("/staff/{user_id}/profile/pdf")
async def profile_pdf(user_id: str, request: Request, token: Optional[str] = None):
    admin = await user_from_token(bearer(request) or token)
    if not admin or admin["role"] != "admin":
        raise HTTPException(403, "Admins only")
    d = await profile_data(user_id)
    d["group_label"] = STAFF_GROUP_LABELS.get(d["user"].get("staff_group") or "", "")
    pdf = await run_in_threadpool(build_profile_pdf, d)
    name = re.sub(r"[^A-Za-z0-9]+", "_", d["user"]["name"]).strip("_")
    return Response(content=pdf, media_type="application/pdf",
                    headers={"Content-Disposition": f'inline; filename="Staff_Profile_{name}.pdf"'})
