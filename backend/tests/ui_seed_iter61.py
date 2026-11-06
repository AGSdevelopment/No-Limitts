# UI seed/cleanup for iteration 61 rostering checks. Usage: python ui_seed_iter61.py seed|clean
import asyncio
import json
import os
import sys
from datetime import datetime, timedelta, timezone

import requests
from dotenv import load_dotenv

load_dotenv("/app/backend/.env")
load_dotenv("/app/frontend/.env")
sys.path.insert(0, "/app/backend")
from core import db  # noqa: E402

API = (os.environ.get("EXPO_BACKEND_URL") or os.environ.get("EXPO_PUBLIC_BACKEND_URL")).rstrip("/") + "/api"
ADMIN = {"Authorization": "Bearer test_session_admin"}
EMP = {"Authorization": "Bearer test_session_employee"}
EMP_ID, W2_ID, W2_TOK = "user_testemp001", "user_t61uiw2", "test_sess_t61uiw2"
W2 = {"Authorization": f"Bearer {W2_TOK}"}
PID, FID, PNAME = "par_t61ui", "fund_t61ui", "TEST_Iter61UI Pat"
PERTH = timezone(timedelta(hours=8))
today = datetime.now(PERTH).date()


def mk(days, start, end, worker):
    r = requests.post(f"{API}/shifts", headers=ADMIN, json={"participant_id": PID, "funding_id": FID, "worker_id": worker,
                                                            "date": (today + timedelta(days=days)).strftime("%d-%m-%Y"), "start": start, "end": end})
    assert r.status_code == 200, r.text
    return r.json()["shift_id"]


async def seed():
    now = datetime.now(PERTH).isoformat()
    await db.users.insert_one({"user_id": W2_ID, "name": "TEST_Iter61UI Worker Two", "email": "t61uiw2@example.com", "role": "employee",
                               "user_type": "support_worker", "hidden": False, "created_at": now})
    await db.user_sessions.insert_one({"session_token": W2_TOK, "user_id": W2_ID, "expires_at": datetime.now(timezone.utc) + timedelta(days=1)})
    await db.participants.insert_one({"participant_id": PID, "name": PNAME, "key": PNAME.casefold(), "assigned_ids": [EMP_ID, W2_ID], "profile": {}})
    await db.fundings.insert_one({"funding_id": FID, "participant_id": PID, "participant_name": PNAME, "participant_email": "",
                                  "management_type": "NDIA", "units": 500.0, "unit_type": "Hour", "unit_rate": 50.0, "budget": 25000.0,
                                  "start_date": (today - timedelta(days=30)).isoformat(), "end_date": (today + timedelta(days=90)).isoformat(),
                                  "rate_history": [], "created_by": "TEST", "created_at": now})


def flows():
    out = {}
    out["s1"] = mk(1, "07:00", "08:00", EMP_ID)  # declined by EMP, on open board
    assert requests.post(f"{API}/shifts/{out['s1']}/decline", headers=EMP, json={"reason": "TEST busy"}).status_code == 200
    assert requests.post(f"{API}/shifts/{out['s1']}/open", headers=ADMIN).status_code == 200
    out["s1b"] = mk(1, "05:00", "06:00", EMP_ID)  # declined, not open -> Re-roster visible
    assert requests.post(f"{API}/shifts/{out['s1b']}/decline", headers=EMP, json={"reason": "TEST busy"}).status_code == 200
    out["s2"] = mk(2, "12:00", "13:00", W2_ID)  # declined by W2, open -> EMP can claim
    assert requests.post(f"{API}/shifts/{out['s2']}/decline", headers=W2, json={"reason": "TEST busy"}).status_code == 200
    assert requests.post(f"{API}/shifts/{out['s2']}/open", headers=ADMIN).status_code == 200
    out["s3"] = mk(3, "09:00", "10:00", W2_ID)  # W2 offers to EMP
    assert requests.post(f"{API}/shifts/{out['s3']}/swap", headers=W2, json={"to_worker_id": EMP_ID}).status_code == 200
    out["s4"] = mk(3, "12:00", "13:00", EMP_ID)  # EMP offered to W2 (pending)
    assert requests.post(f"{API}/shifts/{out['s4']}/swap", headers=EMP, json={"to_worker_id": W2_ID}).status_code == 200
    out["s5"] = mk(4, "09:00", "10:00", EMP_ID)  # EMP offered then declined -> withdrawn
    assert requests.post(f"{API}/shifts/{out['s5']}/swap", headers=EMP, json={"to_worker_id": W2_ID}).status_code == 200
    assert requests.post(f"{API}/shifts/{out['s5']}/decline", headers=EMP, json={"reason": "TEST sick"}).status_code == 200
    out["s6"] = mk(4, "12:00", "13:00", EMP_ID)  # plain shift -> Offer link
    return out


async def clean():
    await db.shifts.delete_many({"participant_id": PID})
    await db.fundings.delete_many({"funding_id": FID})
    await db.participants.delete_many({"participant_id": PID})
    await db.notifications.delete_many({"$or": [{"user_id": W2_ID}, {"title": {"$regex": "TEST_Iter61UI"}}, {"body": {"$regex": "TEST_Iter61UI"}}]})
    await db.user_sessions.delete_many({"session_token": W2_TOK})
    await db.users.delete_many({"user_id": W2_ID})


if __name__ == "__main__":
    if sys.argv[1] == "seed":
        asyncio.run(seed())
        print(json.dumps(flows()))
    else:
        asyncio.run(clean())
        print("cleaned")
