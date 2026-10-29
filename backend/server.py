from fastapi import FastAPI
from fastapi.concurrency import run_in_threadpool
from starlette.middleware.cors import CORSMiddleware
import asyncio
import json
from core import HIDDEN_TEST_USERS, P, ROOT_DIR, SEED_USERS, client, db, logger, new_id, now_iso, type_fields
from storage import init_storage
from routes import (auth, users, notifications, certificates, chat, updates, policies, compliance, events, tasks,
                    dashboard, drive, teams, calendar, forms, socials, cpd, ai, digest, profile, places, pathway, directory, referral_map,
                    celebrations)
from routes.celebrations import celebration_reminder_loop
from routes.compliance import starter_reminder_loop
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
               celebrations):
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
        ids = {"$in": old}
        for col, field in (("user_sessions", "user_id"), ("notifications", "user_id"), ("certificates", "owner_id"),
                           ("cpd_logs", "user_id"), ("cpd_goals", "user_id"), ("checklist_progress", "user_id"),
                           ("conv_reads", "user_id"), ("ai_messages", "user_id"), ("pathways", "user_id"),
                           ("tasks", "assignee_id"), ("celebration_posts", "user_id"), ("messages", "sender_id")):
            await db[col].delete_many({field: ids})
        dms = [c["conversation_id"] async for c in db.conversations.find({"type": "dm", "member_ids": ids}, {"conversation_id": 1})]
        await db.messages.delete_many({"conversation_id": {"$in": dms}})
        await db.conversations.delete_many({"conversation_id": {"$in": dms}})
        await db.conversations.update_many({}, {"$pull": {"member_ids": ids}})
        await db.users.delete_many({"user_id": ids})
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
    await db.integrations.delete_many({"key": {"$regex": "^(google_|linkedin)"}})
    await db.updates.delete_many({"source": "linkedin"})
    await db.conversations.update_many({}, {"$unset": {"gchat_webhook": "", "gchat_space": "", "gchat_two_way": "", "gchat_cursor": ""}})
    await db.meta.insert_one({"key": "no_limitts_v1", "created_at": now_iso()})
    logger.info(f"No Limitts migration: removed {len(old)} old staff")


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
    await seed()
    await seed_company_data()
    await seed_staff_v2()
    await migrate_forms_v3()
    await restore_staff()
    await migrate_no_limitts()
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
    asyncio.create_task(probation_reminder_loop())
    asyncio.create_task(event_reminder_loop())
    asyncio.create_task(poll_close_loop())
    asyncio.create_task(celebration_reminder_loop())


@app.on_event("shutdown")
async def shutdown_db_client():
    client.close()
