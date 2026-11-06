"""Training certificates and expiry reminders."""
from datetime import date, datetime, timedelta, timezone
import re
from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import Response
from html import escape
from typing import Optional
import asyncio
import uuid
from core import DIGEST_TZ, EXPIRY_WARNING_DAYS, MAX_UPLOAD_BYTES, P, bearer, current_user, db, dmy, logger, new_id, notify, now_iso, spawn, user_from_token
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
    if owner and not owner.get("hidden"):  # Service Coordinators, HR and Admins follow the team countdown
        team = [u["user_id"] async for u in db.users.find(
            {"$or": [{"role": "admin"}, {"user_type": {"$in": ["hr", "support_coordinator"]}}], "hidden": {"$ne": True},
             "user_id": {"$ne": cert["owner_id"]}}, {"_id": 0, "user_id": 1})]
        if team:
            await notify(team, "certificate", f"{owner['name']}: {title.lower()}", body.split(". It's required")[0], "/team-certificates")
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
    by_owner: dict = {}
    for c in certs:
        by_owner.setdefault(c["owner_id"], []).append(c)
    for c in certs:
        c["renewed"] = renewal_of(c, by_owner[c["owner_id"]]) if c["status"] != "valid" else None
    order = {"expired": 0, "expiring": 1, "valid": 2}
    certs.sort(key=lambda c: (order[c["status"]], c["expiry_date"]))
    return certs


def sees_team_certs(user: dict) -> bool:
    return user.get("role") == "admin" or user.get("user_type") in ("hr", "support_coordinator")


async def team_cert_alerts() -> list:
    """Every staff member's certificates that are expired or expire within the warning window, soonest first."""
    hidden = {u["user_id"] async for u in db.users.find({"hidden": True}, {"_id": 0, "user_id": 1})}
    certs = [with_status(c) for c in await db.certificates.find({"is_deleted": False}, P).to_list(10000)
             if c["owner_id"] not in hidden]
    alerts = [c for c in certs if c["status"] != "valid"]
    owners = {u["user_id"]: u async for u in db.users.find({"user_id": {"$in": list({c["owner_id"] for c in alerts})}},
                                                          {"_id": 0, "user_id": 1, "name": 1, "user_type": 1})}
    by_owner: dict = {}
    for c in certs:
        by_owner.setdefault(c["owner_id"], []).append(c)
    out = [{**c, "owner_name": owners.get(c["owner_id"], {}).get("name") or c.get("owner_name") or "",
            "owner_type": owners.get(c["owner_id"], {}).get("user_type") or "", "nudged_today": nudged_today(c),
            "renewed": renewal_of(c, by_owner.get(c["owner_id"], []))} for c in alerts if c["owner_id"] in owners]
    out.sort(key=lambda c: c["expiry_date"])
    return out


def norm_title(t: str) -> str:
    return re.sub(r"[^a-z0-9]", "", (t or "").lower())


def renewal_of(cert: dict, owner_certs: list) -> Optional[dict]:
    """A newer upload of the same certificate (matching title) with a later expiry date."""
    a = norm_title(cert["title"])
    # explicit "renews" links first (newest), then the earliest later upload with a matching title (the next renewal in the chain)
    ordered = sorted([c for c in owner_certs if c.get("renews") == cert["cert_id"]], key=lambda x: x.get("created_at") or "", reverse=True)
    ordered += sorted([c for c in owner_certs if c.get("renews") != cert["cert_id"]], key=lambda x: x.get("created_at") or "")
    for c in ordered:
        if c.get("renews") == cert["cert_id"]:
            return {"cert_id": c["cert_id"], "title": c["title"], "expiry_date": c["expiry_date"], "uploaded_at": c.get("created_at") or ""}
        b = norm_title(c["title"])
        if (c["cert_id"] != cert["cert_id"] and c["expiry_date"] > cert["expiry_date"]
                and (c.get("created_at") or "") > (cert.get("created_at") or "")
                and a and b and (a == b or (min(len(a), len(b)) >= 4 and (a in b or b in a)))):
            return {"cert_id": c["cert_id"], "title": c["title"], "expiry_date": c["expiry_date"], "uploaded_at": c.get("created_at") or ""}
    return None


async def thank_nudgers(owner: dict):
    """When a nudged worker uploads the renewal, tell whoever nudged them (once per nudged certificate)."""
    pending: dict = {}
    async for n in db.cert_nudges.find({"owner_id": owner["user_id"], "thanked": {"$ne": True}}, {"_id": 0}):
        pending.setdefault(n["cert_id"], []).append(n)
    if not pending:
        return
    mine = await db.certificates.find({"owner_id": owner["user_id"], "is_deleted": False}, P).to_list(1000)
    for cert_id, nudges in pending.items():
        orig = next((c for c in mine if c["cert_id"] == cert_id), None)
        ren = renewal_of(orig, mine) if orig else None
        if not ren or ren["uploaded_at"] < min(n["at"] for n in nudges):
            continue
        to = list({n["by_id"] for n in nudges if n["by_id"] != owner["user_id"]})
        await notify(to, "certificate", f"✓ {owner['name']} renewed {orig['title']}",
                     f"Thanks for the nudge! The new certificate expires {dmy(ren['expiry_date'])}.", "/team-certificates")
        await db.cert_nudges.update_many({"cert_id": cert_id}, {"$set": {"thanked": True}})


RENEWAL_BADGES = [(5, "🏆", "Compliance Champion"), (3, "⭐", "Always Ready"), (1, "✅", "On Time")]


def renewal_record(certs: list) -> dict:
    """On-time renewals: a renewal uploaded on or before the old certificate's expiry date. Streak counts back from the latest."""
    results = []
    for old in certs:
        ren = renewal_of(old, [c for c in certs if not c.get("is_deleted")] + [c for c in certs if c.get("is_deleted") and c.get("renews")])
        if ren:
            day = datetime.fromisoformat(ren["uploaded_at"]).astimezone(DIGEST_TZ).date().isoformat() if "T" in ren["uploaded_at"] else ren["uploaded_at"][:10]
            results.append((ren["uploaded_at"], day <= old["expiry_date"]))
    results.sort(reverse=True)
    on_time = sum(ok for _, ok in results)
    streak = 0
    for _, ok in results:
        if not ok:
            break
        streak += 1
    badge = next(({"emoji": e, "label": lbl} for n, e, lbl in RENEWAL_BADGES if streak >= n), None)
    return {"on_time": on_time, "renewals": len(results), "streak": streak, "badge": badge}


@router.get("/certificates/renewal-board")
async def renewal_board(user=Depends(current_user)):
    """Leaderboard of on-time certificate renewals, with badges for renewal streaks."""
    by_owner: dict = {}
    async for c in db.certificates.find({}, P):
        by_owner.setdefault(c["owner_id"], []).append(c)
    rows = []
    async for u in db.users.find({"user_id": {"$in": list(by_owner)}, "hidden": {"$ne": True}},
                                 {"_id": 0, "user_id": 1, "name": 1, "picture": 1}):
        rec = renewal_record(by_owner[u["user_id"]])
        if rec["renewals"]:
            rows.append({"user_id": u["user_id"], "name": u["name"], "picture": u.get("picture"), **rec, "me": u["user_id"] == user["user_id"]})
    rows.sort(key=lambda r: (-r["streak"], -r["on_time"], r["name"].lower()))
    return {"rows": rows[:50], "badges": [{"streak": n, "emoji": e, "label": lbl} for n, e, lbl in reversed(RENEWAL_BADGES)]}


@router.get("/certificates/team/calendar")
async def expiry_calendar(month: Optional[str] = None, user=Depends(current_user)):
    """Every team certificate expiring in a month (default this month), for the coordinators' calendar."""
    if not sees_team_certs(user):
        raise HTTPException(403, "For Service Coordinators, HR and Admins")
    month = month or datetime.now(DIGEST_TZ).strftime("%Y-%m")
    if not re.fullmatch(r"\d{4}-(0[1-9]|1[0-2])", month):
        raise HTTPException(400, "Choose a month like 2026-05")
    hidden = {u["user_id"] async for u in db.users.find({"hidden": True}, {"_id": 0, "user_id": 1})}
    certs = [with_status(c) for c in await db.certificates.find(
        {"is_deleted": False, "expiry_date": {"$regex": f"^{month}"}}, P).to_list(5000) if c["owner_id"] not in hidden]
    owners = {u["user_id"]: u["name"] async for u in db.users.find({"user_id": {"$in": list({c["owner_id"] for c in certs})}},
                                                                  {"_id": 0, "user_id": 1, "name": 1})}
    everyone = await db.certificates.find({"owner_id": {"$in": list(owners)}, "is_deleted": False}, P).to_list(10000)
    out = [{**c, "owner_name": owners[c["owner_id"]],
            "renewed": renewal_of(c, [x for x in everyone if x["owner_id"] == c["owner_id"]])}
           for c in certs if c["owner_id"] in owners]
    out.sort(key=lambda c: (c["expiry_date"], c["owner_name"].lower()))
    return {"month": month, "certificates": out}


@router.get("/certificates/team/renewals")
async def renewal_progress(user=Depends(current_user)):
    """Certificates nudged in the last 60 days and whether the worker has uploaded a renewal since."""
    if not sees_team_certs(user):
        raise HTTPException(403, "For Service Coordinators, HR and Admins")
    since = (datetime.now(timezone.utc) - timedelta(days=60)).isoformat()
    latest: dict = {}
    async for n in db.cert_nudges.find({"at": {"$gte": since}}, {"_id": 0}).sort("at", 1):
        latest[n["cert_id"]] = {**n, "count": latest.get(n["cert_id"], {}).get("count", 0) + 1}
    if not latest:
        return {"renewals": [], "renewed": 0, "waiting": 0}
    owner_ids = list({n["owner_id"] for n in latest.values()})
    owners = {u["user_id"]: u async for u in db.users.find({"user_id": {"$in": owner_ids}}, {"_id": 0, "user_id": 1, "name": 1, "hidden": 1})}
    by_owner: dict = {}
    async for c in db.certificates.find({"owner_id": {"$in": owner_ids}, "is_deleted": False}, P):
        by_owner.setdefault(c["owner_id"], []).append(c)
    out = []
    for n in latest.values():
        o = owners.get(n["owner_id"])
        if not o or o.get("hidden"):
            continue
        orig = next((c for c in by_owner.get(n["owner_id"], []) if c["cert_id"] == n["cert_id"]), None)
        ren = renewal_of(orig or {"cert_id": n["cert_id"], "title": n["title"], "expiry_date": n["expiry_date"], "created_at": ""},
                         by_owner.get(n["owner_id"], []))
        if ren and ren["uploaded_at"] < n["first_at"]:
            ren = {**ren, "before_nudge": True}
        out.append({"cert_id": n["cert_id"], "owner_id": n["owner_id"], "owner_name": o["name"], "title": n["title"],
                    "expiry_date": n["expiry_date"], "nudged_at": n["at"], "nudged_by_name": n["by_name"], "nudges": n["count"],
                    "deleted": orig is None, "renewed": ren})
    out.sort(key=lambda r: (bool(r["renewed"]), r["nudged_at"]))
    done = sum(bool(r["renewed"]) for r in out)
    return {"renewals": out, "renewed": done, "waiting": len(out) - done}


@router.get("/certificates/team")
async def team_certificates(user=Depends(current_user)):
    """Countdown of expiring training certificates across the team, for Service Coordinators, HR and Admins."""
    if not sees_team_certs(user):
        raise HTTPException(403, "For Service Coordinators, HR and Admins")
    return {"warning_days": EXPIRY_WARNING_DAYS, "certificates": await team_cert_alerts()}


def nudged_today(c: dict) -> bool:
    """Once-a-day nudge limit, using the Perth calendar day."""
    at = c.get("nudged_at")
    return bool(at) and datetime.fromisoformat(at).astimezone(DIGEST_TZ).date() == datetime.now(DIGEST_TZ).date()


@router.post("/certificates/{cert_id}/nudge")
async def nudge_renewal(cert_id: str, user=Depends(current_user)):
    """Coordinators, HR and Admins remind a worker to renew an expiring or expired certificate (once a day per certificate)."""
    if not sees_team_certs(user):
        raise HTTPException(403, "For Service Coordinators, HR and Admins")
    cert = await db.certificates.find_one({"cert_id": cert_id, "is_deleted": False}, P)
    if not cert:
        raise HTTPException(404, "Certificate not found")
    if cert_status(cert["expiry_date"])["status"] == "valid":
        raise HTTPException(400, "This certificate isn't due for renewal yet")
    if nudged_today(cert):
        raise HTTPException(400, f"{cert.get('nudged_by_name') or 'Someone'} already sent a reminder today")
    owner = await db.users.find_one({"user_id": cert["owner_id"]}, P)
    if not owner:
        raise HTTPException(404, "This staff member is no longer active")
    return await send_nudge([cert], owner, user)


@router.post("/certificates/team/nudge-expired")
async def nudge_all_expired(user=Depends(current_user)):
    """One tap: remind every worker with an expired certificate (one message per worker; skips any reminded today)."""
    if not sees_team_certs(user):
        raise HTTPException(403, "For Service Coordinators, HR and Admins")
    due = [c for c in await team_cert_alerts() if c["status"] == "expired" and c["owner_id"] != user["user_id"]
           and not nudged_today(c) and not c["renewed"]]
    by_owner: dict = {}
    for c in due:
        by_owner.setdefault(c["owner_id"], []).append(c)
    owners = {u["user_id"]: u async for u in db.users.find({"user_id": {"$in": list(by_owner)}}, P)}
    for oid, certs in by_owner.items():
        await send_nudge(certs, owners[oid], user)
    return {"nudged": len(due), "workers": len(by_owner)}


async def send_nudge(certs: list, owner: dict, user: dict) -> dict:
    """One notification and one email to the worker covering all the given certificates."""
    sender = user.get("name") or "Your coordinator"

    def line(c):
        st = cert_status(c["expiry_date"])
        when = "expired" if st["status"] == "expired" else f"expires in {st['days_left']} day{'s' if st['days_left'] != 1 else ''}"
        return f"{c['title']} ({when}, {dmy(c['expiry_date'])})"
    if len(certs) == 1:
        title, body = f"Please renew: {certs[0]['title']}", f"{sender} asked you to renew {line(certs[0])}. Upload the new one in Certificates."
    else:
        title = f"Please renew {len(certs)} certificates"
        body = f"{sender} asked you to renew: " + "; ".join(line(c) for c in certs) + ". Upload the new ones in Certificates."
    link = f"/upload-certificate?renew={certs[0]['cert_id']}" if len(certs) == 1 else "/(tabs)/certificates"
    await notify([owner["user_id"]], "certificate", title, body, link)
    if owner.get("email"):
        items = "".join(f"<li>{escape(line(c))}</li>" for c in certs)
        html = (f'<table role="presentation" width="100%"><tr><td style="padding:24px;font-family:Arial,sans-serif;color:#11181C">'
                f'<p>Hi {escape((owner.get("name") or "there").split(" ")[0])},</p>'
                f'<p>{escape(sender)} has asked you to renew {"this certificate" if len(certs) == 1 else "these certificates"}:</p>'
                f'<ul>{items}</ul><p>Please renew and upload the new certificate in the {escape(EMAIL_FROM_NAME)} app.</p>'
                f'<p style="font-size:12px;color:#888">Sent by {escape(EMAIL_FROM_NAME)}. We never ask for your password by email.</p>'
                f'</td></tr></table>')
        spawn(send_email(to=owner["email"], subject=title, html=html))
    at = now_iso()
    firsts = {n["cert_id"]: n["first_at"] async for n in db.cert_nudges.find(
        {"cert_id": {"$in": [c["cert_id"] for c in certs]}}, {"_id": 0, "cert_id": 1, "first_at": 1})}
    await db.cert_nudges.insert_many([{"nudge_id": new_id("nudge"), "cert_id": c["cert_id"], "owner_id": owner["user_id"],
                                       "title": c["title"], "expiry_date": c["expiry_date"], "by_id": user["user_id"],
                                       "by_name": sender, "at": at, "first_at": firsts.get(c["cert_id"], at)} for c in certs])
    await db.certificates.update_many({"cert_id": {"$in": [c["cert_id"] for c in certs]}},
                                      {"$set": {"nudged_at": at, "nudged_by_name": sender}})
    return {"nudged_at": at, "nudged_by_name": sender, "nudged_today": True}


@router.post("/certificates")
async def upload_certificate(title: str = Form(...), expiry_date: str = Form(...), issuer: str = Form(""),
                             issue_date: str = Form(""), cpd_hours: str = Form(""), file: UploadFile = File(...),
                             share_cpd: str = Form(""), drive_spaces: str = Form(""), renews: str = Form(""),
                             user=Depends(current_user)):
    title = title.strip()
    renews = renews.strip()
    if renews and not await db.certificates.find_one({"cert_id": renews, "owner_id": user["user_id"], "is_deleted": False}, {"_id": 0, "cert_id": 1}):
        raise HTTPException(400, "The certificate you're renewing wasn't found")
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
    if renews:
        cert["renews"] = renews
    await db.certificates.insert_one(dict(cert))
    spawn(thank_nudgers(user))
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


@router.post("/resources/upload")
async def upload_resource(title: str = Form(...), provider: str = Form(""), cpd_hours: str = Form(""),
                          share_cpd: str = Form(""), drive_spaces: str = Form(""), file: UploadFile = File(...),
                          user=Depends(current_user)):
    """Share a webinar, case study, course material or other resource (no expiry date): to CPD Resources,
    Company Drive folders and/or My CPD."""
    title = title.strip()
    if not title:
        raise HTTPException(400, "Title is required")
    share = share_cpd.strip()
    if share and share.lower() not in ("course", "webinar", "case study", "resource link"):
        raise HTTPException(400, "Choose Course, Webinar, Case Study or Resource link")
    spaces = [x.strip() for x in drive_spaces.split(",") if x.strip()]
    hours = None
    if cpd_hours.strip():
        try:
            hours = round(float(cpd_hours.replace(",", ".")), 2)
        except ValueError:
            raise HTTPException(400, "CPD hours must be a number")
        if not (0 < hours <= 200):
            raise HTTPException(400, "CPD hours must be between 0 and 200")
    if not (share or spaces or hours):
        raise HTTPException(400, "Choose where to share it")
    data = await file.read()
    if not data:
        raise HTTPException(400, "Empty file")
    if len(data) > MAX_UPLOAD_BYTES:
        raise HTTPException(413, "File too large (max 15 MB)")
    ext = (file.filename or "file").rsplit(".", 1)[-1].lower() if "." in (file.filename or "") else "bin"
    path = f"{APP_NAME}/resources/{user['user_id']}/{uuid.uuid4().hex}.{ext}"
    ctype = file.content_type or "application/octet-stream"
    try:
        result = await run_in_threadpool(put_object, path, data, ctype)
    except Exception as e:
        logger.error(f"resource upload failed: {e}")
        raise HTTPException(502, "Could not store the file, please try again")
    item = {"cert_id": None, "title": title, "issuer": provider.strip()[:200], "storage_path": result["path"],
            "file_name": file.filename or "document", "content_type": ctype}
    out = {"title": title}
    if hours:
        from routes.cpd import LOG_CATEGORY, cpd_section
        log = {"log_id": new_id("cpd"), "user_id": user["user_id"], "user_name": user["name"], "title": title,
               "provider": item["issuer"], "date": date.today().isoformat(), "hours": hours,
               "category": LOG_CATEGORY[cpd_section(share)] if share else "Course", "notes": "Added from an upload",
               "storage_path": item["storage_path"], "file_name": item["file_name"], "content_type": ctype,
               "created_at": now_iso()}
        await db.cpd_logs.insert_one(log)
        item["cpd_log_id"] = out["cpd_log_id"] = log["log_id"]
    if share:
        from routes.cpd import share_file_to_resources  # local import: cpd is a sibling module
        out["cpd_resource_id"] = await share_file_to_resources(item, share, user)
    if spaces:
        out["drive"] = await upload_to_spaces(item, data, spaces, user)
    return out
