from fastapi import FastAPI
from fastapi.concurrency import run_in_threadpool
from starlette.middleware.cors import CORSMiddleware
import asyncio
import json
from core import HIDDEN_TEST_USERS, ROOT_DIR, client, db, logger, new_id, now_iso
from storage import init_storage
from routes import (auth, users, notifications, certificates, chat, updates, policies, compliance, events, tasks,
                    dashboard, drive, gchat, forms, socials, cpd, ai, digest)
from routes.certificates import expiry_loop
from routes.policies import policy_reminder_loop
from routes.tasks import task_reminder_loop
from routes.drive import drive_index_loop
from routes.gchat import gchat_loop
from routes.socials import socials_loop
from routes.digest import digest_loop

app = FastAPI()


@app.get("/health", include_in_schema=False)
@app.head("/health", include_in_schema=False)
async def health():
    return {"status": "ok"}


for module in (auth, users, notifications, certificates, chat, updates, policies, compliance, events, tasks,
               dashboard, drive, gchat, forms, socials, cpd, ai, digest):
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


async def seed():
    for name, desc in (("general", "Company-wide chat for everyone"),
                       ("announcements", "Important news and notices")):
        if not await db.conversations.find_one({"type": "channel", "$or": [{"seed_key": name}, {"name": name}]}):
            await db.conversations.insert_one({"conversation_id": new_id("conv"), "type": "channel", "name": name,
                                               "seed_key": name,
                                               "description": desc, "member_ids": [], "last_message": "",
                                               "last_at": "", "created_at": now_iso()})
    if await db.updates.count_documents({}) == 0:
        await db.updates.insert_one({"update_id": new_id("upd"), "title": "Welcome to StaffHub",
                                     "body": "This is a sample update. Admins can post company news here and "
                                             "everyone gets notified.", "pinned": True, "author_id": "system",
                                     "author_name": "StaffHub", "created_at": now_iso()})
    if await db.policies.count_documents({}) == 0:
        await db.policies.insert_one({"policy_id": new_id("pol"), "title": "Sample: Health & Safety Policy",
                                      "category": "Policy",
                                      "content": "This is sample policy text. Admins can replace it with your "
                                                 "real policies and procedures. Employees tap 'Acknowledge' once "
                                                 "they have read it.", "author_name": "StaffHub",
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
    asyncio.create_task(gchat_loop())
    asyncio.create_task(drive_index_loop())
    asyncio.create_task(digest_loop())
    asyncio.create_task(socials_loop())
    asyncio.create_task(task_reminder_loop())
    asyncio.create_task(policy_reminder_loop())


@app.on_event("shutdown")
async def shutdown_db_client():
    client.close()
