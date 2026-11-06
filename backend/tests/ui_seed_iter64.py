# UI seed for iter64 (My Shifts, week by participant, funding current/history + support item, groups). Usage: python ui_seed_iter64.py seed|clean
import asyncio
import sys
from datetime import datetime, timedelta

sys.path.insert(0, "/app/backend")
from core import DIGEST_TZ, db  # noqa: E402

ADMIN, W1 = "user_testadmin01", "user_t64uiw1"
PID, PNAME = "par_ui64", "TEST_UI64 Participant"
FID, FOLD = "fund_ui64", "fund_ui64old"


async def seed():
    now = datetime.now(DIGEST_TZ)
    t = now.date()
    d = lambda n: (t + timedelta(days=n)).isoformat()  # noqa: E731
    await db.users.insert_one({"user_id": W1, "name": "TEST_UI64 Worker", "email": "t64uiw1@example.com", "role": "employee",
                               "user_type": "support_worker", "created_at": now.isoformat()})
    await db.participants.insert_one({"participant_id": PID, "name": PNAME, "key": PNAME.casefold(), "assigned_ids": [ADMIN, W1], "profile": {}})
    base = {"participant_id": PID, "participant_name": PNAME, "participant_email": "", "units": 300.0, "unit_type": "Hour", "unit_rate": 60.0,
            "budget": 18000.0, "payer": {"name": "TEST Payer", "email": "p@example.com", "company": "TEST Co", "phone": "0400", "abn": ""},
            "representative": {"name": "TEST Rep", "email": "r@example.com", "phone": "0411", "relationship": "Mother"},
            "rate_history": [], "created_by": "TEST", "created_at": now.isoformat()}
    await db.fundings.insert_many([
        {**base, "funding_id": FID, "management_type": "NDIA", "start_date": d(-100), "end_date": d(200),
         "support_item_number": "01_011_0107_1_1", "support_item_name": "Self-Care Weekday"},
        {**base, "funding_id": FOLD, "management_type": "Plan Managed", "start_date": d(-500), "end_date": d(-120)}])
    sh = lambda sid, n, st: {"shift_id": sid, "date": d(n), "start": "09:00", "end": "11:00", "participant_id": PID, "participant_name": PNAME,  # noqa: E731
                             "funding_id": FID, "funding_type": "NDIA", "unit_rate": 60.0, "worker_id": ADMIN, "worker_name": "Admin Test",
                             "minutes": 120, "est_units": 2.0, "hourly": True, "est_cost": 120.0, "notes": "", "status": st,
                             "support_item_number": "01_011_0107_1_1", "support_item_name": "Self-Care Weekday",
                             "auto_accepted": True, "created_by": "TEST", "created_at": now.isoformat()}
    await db.shifts.insert_many([sh("shf_ui64past", -90, "completed"), sh("shf_ui64fut", 100, "scheduled"), sh("shf_ui64wk", 1, "scheduled")])
    print("seeded")


async def clean():
    for g in await db.participant_groups.find({"participant_id": PID}, {"_id": 0}).to_list(5):
        await db.conversations.delete_one({"conversation_id": g["conversation_id"]})
        await db.messages.delete_many({"conversation_id": g["conversation_id"]})
        await db.tasks.delete_many({"participant_group_id": g["group_id"]})
    await db.participant_groups.delete_many({"participant_id": PID})
    await db.shifts.delete_many({"participant_id": PID})
    await db.fundings.delete_many({"funding_id": {"$in": [FID, FOLD]}})
    await db.participants.delete_many({"participant_id": PID})
    await db.notifications.delete_many({"user_id": {"$in": [W1, "user_t64uiw2"]}})
    await db.tasks.delete_many({"assignee_id": {"$in": [W1, "user_t64uiw2"]}})
    await db.user_sessions.delete_many({"session_token": "tok_ui64w1"})
    await db.users.delete_many({"user_id": {"$in": [W1, "user_t64uiw2"]}})
    print("cleaned")


asyncio.run(seed() if sys.argv[1] == "seed" else clean())
