# Seed/cleanup for iteration 26 UI tests. Usage: python seed_iter26_ui.py seed|clean
import os
import sys
from datetime import date, datetime, timedelta, timezone

import requests
from dotenv import load_dotenv
from pymongo import MongoClient

load_dotenv("/app/backend/.env")
mdb = MongoClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]
BASE = [l.split("=", 1)[1].strip().strip('"') for l in open("/app/frontend/.env") if l.startswith("EXPO_PUBLIC_BACKEND_URL=")][0]
C_ID, C_TOKEN, EMP_ID = "TEST_user_evt26c", "TEST_session_evt26c", "user_testemp001"
PNG = (b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15\xc4\x89"
       b"\x00\x00\x00\rIDATx\x9cc\xf8\x0f\x00\x00\x01\x01\x00\x05\x18\xd8N\x00\x00\x00\x00IEND\xaeB`\x82")


def clean():
    mdb.events.delete_many({"title": {"$regex": "^TEST_evt26"}})
    mdb.notifications.delete_many({"$or": [{"body": {"$regex": "TEST_evt26"}}, {"title": {"$regex": "TEST_evt26"}}]})
    mdb.places.delete_many({"name": {"$regex": "^TEST_plc26", "$options": "i"}})
    mdb.users.delete_many({"user_id": C_ID})
    mdb.user_sessions.delete_many({"session_token": C_TOKEN})


def ev(eid, title, day, rsvps):
    now = datetime.now(timezone.utc).isoformat()
    return {"event_id": eid, "title": title, "description": "UI test", "location": "Office", "date": day, "time": "5pm",
            "catering": "", "conditions": "", "capacity": None, "series_id": None, "repeat": "",
            "attendees": [r["user_id"] for r in rsvps if r["status"] == "going"], "rsvps": rsvps, "comments": [],
            "created_by": "Erin Employee", "created_by_id": EMP_ID, "created_at": now}


def seed():
    clean()
    now = datetime.now(timezone.utc)
    mdb.users.insert_one({"user_id": C_ID, "name": "Testc Evt26", "email": "evt26c@example.com", "role": "employee",
                          "hidden": True, "created_at": now.isoformat()})
    mdb.user_sessions.insert_one({"session_token": C_TOKEN, "user_id": C_ID, "expires_at": now + timedelta(days=1)})
    r = [{"user_id": C_ID, "name": "Testc Evt26", "picture": None, "status": "going", "comment": "", "at": now.isoformat()}]
    mdb.events.insert_one(ev("evt_test26fut", "TEST_evt26ui Future", (date.today() + timedelta(days=20)).isoformat(), r))
    mdb.events.insert_one(ev("evt_test26past", "TEST_evt26ui Past", (date.today() - timedelta(days=2)).isoformat(), r))
    up = requests.post(f"{BASE}/api/events/evt_test26fut/photos", headers={"Authorization": f"Bearer {C_TOKEN}"},
                       files={"file": ("p.png", PNG, "image/png")}, timeout=30)
    print("photo upload", up.status_code, up.text[:200])


if __name__ == "__main__":
    seed() if sys.argv[1] == "seed" else clean()
    print("done", sys.argv[1])
