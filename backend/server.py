from fastapi import FastAPI
from fastapi.concurrency import run_in_threadpool
from starlette.middleware.cors import CORSMiddleware
import asyncio
import json
from core import HIDDEN_TEST_USERS, P, ROOT_DIR, SEED_USERS, client, db, logger, new_id, now_iso, type_fields
from storage import init_storage
from routes import (auth, users, notifications, certificates, chat, updates, policies, compliance, events, tasks,
                    dashboard, drive, teams, calendar, forms, socials, cpd, ai, digest, profile, places, pathway, directory, referral_map,
                    celebrations, caseload, caseload_extras, participant_mgmt, roster_extras, privacy)
from routes.caseload_extras import caseload_extras_loop
from routes.roster_extras import budget_alert_loop
from routes.celebrations import celebration_reminder_loop
from routes.caseload import case_note_reminder_loop, handover_alert_loop
from routes.compliance import starter_reminder_loop
from routes.teams import weekly_wrap_loop
from routes.places import migrate_place_kinds
from routes.directory import ensure_share_channel
from routes.certificates import expiry_loop
from routes.policies import policy_reminder_loop
from routes.compliance import cert_reminder_loop
from routes.profile import probation_reminder_loop
from routes.events import event_reminder_loop, poll_close_loop
from routes.tasks import task_reminder_loop
from routes.drive import drive_index_loop
from routes.socials import socials_loop
from routes.digest import digest_loop, resource_digest_loop

app = FastAPI()


@app.get("/health", include_in_schema=False)
@app.head("/health", include_in_schema=False)
async def health():
    return {"status": "ok"}


for module in (auth, users, notifications, certificates, chat, updates, policies, compliance, events, tasks,
               dashboard, drive, teams, calendar, forms, socials, cpd, ai, digest, profile, places, pathway, directory, referral_map,
               celebrations, caseload, caseload_extras, participant_mgmt, roster_extras, privacy):
    app.include_router(module.router)


app.add_middleware(CORSMiddleware, allow_credentials=True, allow_origins=["*"], allow_methods=["*"],
                   allow_headers=["*"])


async def seed_company_data():
    """One-time import of the company's forms and staff (admins, staff groups) into a fresh database,
    e.g. the first time the published app starts. Never re-runs, so later edits/deletes stick."""
    if await db.meta.find_one({"key": "company_seed_v1"}):
        return
    path = ROOT_DIR / "company_seed.json"
    if path.exists():
        data = json.loads(path.read_text())
        for f in data.get("forms", []):
            if not await db.forms.find_one({"url": f["url"]}):
                await db.forms.insert_one({"form_id": new_id("form"), **f, "created_by": "Andrew Thomas",
                                           "created_at": now_iso()})
        for u in data.get("users", []):
            existing = await db.users.find_one({"email": u["email"]})
            if existing:
                await db.users.update_one({"email": u["email"]}, {"$set": {"role": u["role"],
                                                                         "staff_group": u.get("staff_group")}})
            else:
                await db.users.insert_one({"user_id": new_id("user"), "email": u["email"], "name": u["name"],
                                           "picture": None, "role": u["role"], "staff_group": u.get("staff_group"),
                                           "job_title": "", "created_at": now_iso()})
    await db.meta.insert_one({"key": "company_seed_v1", "created_at": now_iso()})


async def migrate_forms_v3():
    """One-time: 6 Week Check-in + 3/6/12 Month Review open to everyone; add Task Creation & Management form."""
    if await db.meta.find_one({"key": "forms_v3"}):
        return
    await db.forms.update_many({"title": {"$in": ["6 Week Check-in", "3/6/12 Month Review"]}},
                               {"$set": {"audiences": []}})
    url = "https://form.jotform.com/team/261958881415065/task-creation--management-form"
    if not await db.forms.find_one({"url": url}):
        await db.forms.insert_one({"form_id": new_id("form"), "title": "Task Creation & Management", "url": url,
                                   "description": "Create and allocate tasks for the Support Office team",
                                   "category": "Support Office", "audiences": ["support_office"],
                                   "created_by": "Andrew Thomas", "created_at": now_iso()})
    await db.meta.insert_one({"key": "forms_v3", "created_at": now_iso()})


NO_LIMITTS_FORMS = [  # (category, audiences, title, url); empty audiences = all user types
    ("Operations", ["support_office"], "Equipment Checkout", "https://nolimitts.jotform.com/262568518621968"),
    ("Operations", ["support_office"], "Submit a Support Ticket", "https://nolimitts.jotform.com/262568232121956"),
    ("Day-to-Day", [], "Event Attendance Register – Halloween", "https://nolimitts.jotform.com/form/halloween-event-attendance-register"),
    ("Day-to-Day", [], "Incident Report", "https://nolimitts.jotform.com/262771812661056"),
    ("Day-to-Day", [], "Daily Client Forms – Active Night Log", "https://nolimitts.jotform.com/262641051646050"),
    ("Day-to-Day", [], "No Limitts Shift Handover", "https://nolimitts.jotform.com/262641250044043"),
    ("Day-to-Day", [], "Contractor DSW Expression of Interest Form", "https://nolimitts.jotform.com/form/expression-of-interest-form"),
    ("Day-to-Day", [], "Conflict Of Interest Form", "https://nolimitts.jotform.com/262778212923058"),
    ("Day-to-Day", [], "Incident Report Form - 51 Stafford Way", "https://nolimitts.jotform.com/262661878219065"),
    ("Day-to-Day", [], "Implementation of Restrictive Practices Checklist", "https://nolimitts.jotform.com/262641720389057"),
    ("Day-to-Day", [], "Participant Money Event", "https://nolimitts.jotform.com/262641740900048"),
    ("Day-to-Day", [], "Personal Domestic Activities", "https://nolimitts.jotform.com/262641883172057"),
    ("Day-to-Day", [], "Appointment Follow Up Case Note", "https://nolimitts.jotform.com/262642055038050"),
    ("New Starter", [], "Vehicle Checklist", "https://nolimitts.jotform.com/262852316614053"),
    ("New Starter", [], "VIVO Checks", "https://nolimitts.jotform.com/262852065506054"),
    ("HR", [], "Leave Request & Absence Notification", "https://nolimitts.jotform.com/262771962802059"),
    ("HR", [], "Training / Shadowing Record", "https://nolimitts.jotform.com/262641955099065"),
    *[("Participant Management & Onboarding", ["support_coordinator"], t, u) for t, u in (
        ("Coordinator Case Note Form", "https://nolimitts.jotform.com/262772090420048"),
        ("No Limitts Client Onboarding Checklist", "https://nolimitts.jotform.com/262769397433068"),
        ("SIL Service Agreement", "https://nolimitts.jotform.com/262851214285053"),
        ("Emergency Plan", "https://nolimitts.jotform.com/262741008246049"),
        ("Risk Assessment", "https://nolimitts.jotform.com/262732092621049"),
        ("No Limitts Participant Consent Form", "https://nolimitts.jotform.com/262731018804049"),
        ("No Limitts Service Agreement", "https://nolimitts.jotform.com/262728205556057"))],
]


async def seed_no_limitts_forms_v1():
    if await db.meta.find_one({"key": "nolimitts_forms_v1"}):
        return
    for cat, aud, title, url in NO_LIMITTS_FORMS:
        if not await db.forms.find_one({"url": url}):
            await db.forms.insert_one({"form_id": new_id("form"), "title": title, "url": url, "description": "",
                                       "audiences": aud, "category": cat, "created_by": "No Limitts", "created_at": now_iso()})
    await db.meta.insert_one({"key": "nolimitts_forms_v1", "created_at": now_iso()})


async def seed_cert_requirements_v1():
    """Standard NDIS certificate requirements per user type (only fills groups that are still empty)."""
    if await db.meta.find_one({"key": "nolimitts_cert_reqs_v1"}):
        return
    office = ["NDIS Worker Screening", "NDIS Worker Orientation"]
    std = {"support_worker": office + ["First Aid", "CPR", "Manual Handling", "Medication Administration", "Driver's Licence"],
           "support_coordinator": office, "support_office": office}
    doc = await db.meta.find_one({"key": "cert_requirements"}) or {}
    groups = {**std, **{k: v for k, v in (doc.get("groups") or {}).items() if v}}
    await db.meta.update_one({"key": "cert_requirements"}, {"$set": {"key": "cert_requirements", "groups": groups}}, upsert=True)
    await db.meta.insert_one({"key": "nolimitts_cert_reqs_v1", "created_at": now_iso()})


async def seed_hr_coordinator_v1():
    """HR type: add Toni (HR) and Brooke (Service Coordinator), and give HR the office certificate list."""
    if await db.meta.find_one({"key": "nolimitts_hr_v1"}):
        return
    for email, name, t in (("tonib@nolimitts.com.au", "Toni", "hr"), ("brookep@nolimitts.com.au", "Brooke", "support_coordinator")):
        if not await db.users.find_one({"email": email}):
            await db.users.insert_one({"user_id": new_id("user"), "email": email, "name": name, "picture": None,
                                       "job_title": "HR" if t == "hr" else "Service Coordinator", "created_at": now_iso(), **type_fields(t)})
    await db.meta.update_one({"key": "cert_requirements", "groups.hr": {"$exists": False}},
                             {"$set": {"groups.hr": ["NDIS Worker Screening", "NDIS Worker Orientation"]}})
    await db.meta.insert_one({"key": "nolimitts_hr_v1", "created_at": now_iso()})


async def seed_staff_v2():
    """One-time import of the team directory (contacts.csv): adds missing staff, sets full names and groups."""
    if await db.meta.find_one({"key": "company_staff_v2"}):
        return
    path = ROOT_DIR / "company_seed.json"
    data = json.loads(path.read_text()) if path.exists() else {}
    for u in data.get("staff_v2", []):
        existing = await db.users.find_one({"email": u["email"]})
        if existing:
            await db.users.update_one({"email": u["email"]}, {"$set": {"name": u["name"],
                                                                     "staff_group": u.get("staff_group")}})
        else:
            await db.users.insert_one({"user_id": new_id("user"), "email": u["email"], "name": u["name"],
                                       "picture": None, "role": u["role"], "staff_group": u.get("staff_group"),
                                       "job_title": "", "created_at": now_iso()})
    await db.meta.insert_one({"key": "company_staff_v2", "created_at": now_iso()})


RESTORED_STAFF = [{"email": "pronathi@aspireandgrow.com.au", "name": "Pronathi", "role": "admin",
                   "staff_group": "support_office"}]


async def restore_staff():
    """One-time: make sure these staff exist with the given role and group (also runs on the published database)."""
    if await db.meta.find_one({"key": "restore_staff_v1"}):
        return
    for u in RESTORED_STAFF:
        if await db.users.find_one({"email": u["email"]}):
            await db.users.update_one({"email": u["email"]}, {"$set": {"role": u["role"], "staff_group": u["staff_group"]}})
        else:
            await db.users.insert_one({"user_id": new_id("user"), **u, "picture": None, "job_title": "",
                                       "created_at": now_iso()})
        logger.info(f"Restored staff member {u['email']}")
    await db.meta.insert_one({"key": "restore_staff_v1", "created_at": now_iso()})


async def migrate_no_limitts():
    """One-time switch to No Limitts: remove the old Aspire & Grow staff and their data, set user types,
    add the named Executives, fold old staff groups into Support Worker, drop Google/LinkedIn leftovers."""
    if await db.meta.find_one({"key": "no_limitts_v1"}):
        return
    old = [u["user_id"] async for u in db.users.find({"email": {"$regex": "@aspireandgrow\\.com\\.au$"},
                                                       "hidden": {"$ne": True}}, {"user_id": 1})]
    if old:
        # Retire (never delete) the old staff: hide them from the app and sign them out
        ids = {"$in": old}
        await db.users.update_many({"user_id": ids}, {"$set": {"hidden": True, "retired_at": now_iso()}})
        await db.user_sessions.delete_many({"user_id": ids})
        await db.conversations.update_many({}, {"$pull": {"member_ids": ids}})
    for email, (name, t) in SEED_USERS.items():
        if not await db.users.find_one({"email": email}):
            await db.users.insert_one({"user_id": new_id("user"), "email": email, "name": name, "picture": None,
                                       "job_title": "", "created_at": now_iso(), **type_fields(t)})
    async for u in db.users.find({"user_type": {"$exists": False}}, P):
        t = ("executive" if u.get("executive") else "admin" if u.get("role") == "admin"
             else "support_office" if u.get("staff_group") == "support_office" else "support_worker")
        await db.users.update_one({"user_id": u["user_id"]}, {"$set": type_fields(t)})
    async for f in db.forms.find({"audiences": {"$elemMatch": {"$nin": ["support_office", "support_worker"]}}}):
        new = sorted({a if a == "support_office" else "support_worker" for a in f["audiences"]})
        await db.forms.update_one({"_id": f["_id"]}, {"$set": {"audiences": new}})
    req = await db.meta.find_one({"key": "cert_requirements"})
    if req:
        groups = req.get("groups", {})
        sw = sorted({n for k, v in groups.items() if k != "support_office" for n in v})
        await db.meta.update_one({"_id": req["_id"]}, {"$set": {"groups": {"support_office": groups.get("support_office", []),
                                                                          "support_worker": sw}}})
    await db.updates.update_many({"source": "linkedin"}, {"$set": {"archived": True}})
    await db.conversations.update_many({}, {"$unset": {"gchat_webhook": "", "gchat_space": "", "gchat_two_way": "", "gchat_cursor": ""}})
    await db.meta.insert_one({"key": "no_limitts_v1", "created_at": now_iso()})
    logger.info(f"No Limitts migration: retired {len(old)} old staff")


async def seed():
    for name, desc in (("general", "Company-wide chat for everyone"),
                       ("announcements", "Important news and notices")):
        if not await db.conversations.find_one({"type": "channel", "$or": [{"seed_key": name}, {"name": name}]}):
            await db.conversations.insert_one({"conversation_id": new_id("conv"), "type": "channel", "name": name,
                                               "seed_key": name,
                                               "description": desc, "member_ids": [], "last_message": "",
                                               "last_at": "", "created_at": now_iso()})
    if await db.updates.count_documents({}) == 0:
        await db.updates.insert_one({"update_id": new_id("upd"), "title": "Welcome to No Limitts",
                                     "body": "This is a sample update. Admins can post company news here and "
                                             "everyone gets notified.", "pinned": True, "author_id": "system",
                                     "author_name": "No Limitts", "created_at": now_iso()})
    if await db.policies.count_documents({}) == 0:
        await db.policies.insert_one({"policy_id": new_id("pol"), "title": "Sample: Health & Safety Policy",
                                      "category": "Policy",
                                      "content": "This is sample policy text. Admins can replace it with your "
                                                 "real policies and procedures. Employees tap 'Acknowledge' once "
                                                 "they have read it.", "author_name": "No Limitts",
                                      "acknowledged_by": [], "created_at": now_iso()})


@app.on_event("startup")
async def startup():
    await db.users.create_index("email", unique=True)
    await db.users.create_index("user_id", unique=True)
    await db.user_sessions.create_index("session_token", unique=True)
    await db.user_sessions.create_index("user_id")
    await db.user_sessions.create_index("expires_at", expireAfterSeconds=0)
    await db.messages.create_index([("conversation_id", 1), ("created_at", -1)])
    await db.notifications.create_index([("user_id", 1), ("created_at", -1)])
    await db.messages.create_index("gchat_name", sparse=True)
    await db.meta.create_index("key")
    await db.certificates.create_index("owner_id")
    await db.tasks.create_index("assignee_id")
    await db.events.create_index("date")
    await db.participants.create_index("key")
    await db.participants.create_index("participant_id")
    await db.participants.create_index("assigned_ids")

    await seed()
    await seed_company_data()
    await seed_staff_v2()
    await migrate_forms_v3()
    await restore_staff()
    await migrate_no_limitts()
    await seed_no_limitts_forms_v1()
    if not await db.meta.find_one({"key": "forms_new_starter_v1"}):  # Vehicle Checklist + VIVO Checks live under New Starter
        await db.forms.update_many({"url": {"$in": ["https://nolimitts.jotform.com/262852316614053",
                                                     "https://nolimitts.jotform.com/262852065506054"]}},
                                   {"$set": {"category": "New Starter"}})
        await db.meta.insert_one({"key": "forms_new_starter_v1", "created_at": now_iso()})
    await seed_cert_requirements_v1()
    await seed_hr_coordinator_v1()
    await db.conversations.update_many({"type": "channel", "name": {"$regex": "^allied[- ]health$", "$options": "i"}},
                                       {"$set": {"name": "No Limitts"}})
    await migrate_place_kinds()
    await ensure_share_channel()
    # internal test accounts stay usable but are hidden from staff everywhere
    await db.users.update_many({"user_id": {"$in": HIDDEN_TEST_USERS}}, {"$set": {"hidden": True}})
    # migrate the old single Support Office flag / audience to staff groups
    await db.users.update_many({"support_office": True}, {"$set": {"staff_group": "support_office"},
                                                          "$unset": {"support_office": ""}})
    await db.users.update_many({"support_office": {"$exists": True}}, {"$unset": {"support_office": ""}})
    await db.forms.update_many({"audience": "support_office"}, {"$set": {"audiences": ["support_office"]},
                                                                "$unset": {"audience": ""}})
    await db.forms.update_many({"audience": {"$exists": True}}, {"$set": {"audiences": []},
                                                                 "$unset": {"audience": ""}})
    await db.forms.update_many({"category": {"$exists": False}}, {"$set": {"category": "Day-to-Day"}})
    try:
        await run_in_threadpool(init_storage)
    except Exception as e:
        logger.error(f"Storage init failed: {e}")
    asyncio.create_task(expiry_loop())
    asyncio.create_task(drive_index_loop())
    asyncio.create_task(digest_loop())
    asyncio.create_task(resource_digest_loop())
    asyncio.create_task(socials_loop())
    asyncio.create_task(task_reminder_loop())
    asyncio.create_task(policy_reminder_loop())
    asyncio.create_task(cert_reminder_loop())
    asyncio.create_task(starter_reminder_loop())
    asyncio.create_task(weekly_wrap_loop())
    asyncio.create_task(probation_reminder_loop())
    asyncio.create_task(event_reminder_loop())
    asyncio.create_task(poll_close_loop())
    asyncio.create_task(celebration_reminder_loop())
    asyncio.create_task(handover_alert_loop())
    asyncio.create_task(case_note_reminder_loop())
    asyncio.create_task(caseload_extras_loop())
    asyncio.create_task(budget_alert_loop())


@app.on_event("shutdown")
async def shutdown_db_client():
    client.close()
