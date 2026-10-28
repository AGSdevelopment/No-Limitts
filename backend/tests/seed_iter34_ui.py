# Iteration 34 UI seed: events for poll deadline UI, activities for vote sheet, referral partners for map radius.
# Usage: python seed_iter34_ui.py   |   python seed_iter34_ui.py clean
import os
import sys
import time
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import requests
from dotenv import load_dotenv
from pymongo import MongoClient

load_dotenv("/app/frontend/.env")
load_dotenv("/app/backend/.env")
API = os.environ.get("EXPO_PUBLIC_BACKEND_URL").rstrip("/") + "/api"
db = MongoClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]
ADMIN = {"Authorization": "Bearer test_session_admin"}
REF = "Trusted Referral Partner Organisations"
TODAY = datetime.now(ZoneInfo("Australia/Perth")).date()


def clean():
    db.directory.delete_many({"name": {"$regex": "^TEST_"}})
    ids = [e["event_id"] for e in db.events.find({"title": {"$regex": "^TEST_"}}, {"event_id": 1})]
    ids += [e["event_id"] for e in db.events.find({"poll.options.label": {"$regex": "^TEST_"}}, {"event_id": 1})]
    db.events.delete_many({"event_id": {"$in": ids}})
    db.notifications.delete_many({"$or": [{"link": {"$in": [f"/event/{i}" for i in ids]}}, {"title": {"$regex": "TEST_"}},
                                          {"body": {"$regex": "TEST_"}}]})
    print("cleaned", len(ids), "events")


def seed():
    future = (TODAY + timedelta(days=20)).isoformat()
    e1 = requests.post(f"{API}/events", json={"title": "TEST_UI Open Poll", "date": future}, headers=ADMIN).json()["event_id"]
    e2 = requests.post(f"{API}/events", json={"title": "TEST_UI Auto Poll", "date": future}, headers=ADMIN).json()["event_id"]
    e3 = requests.post(f"{API}/events", json={"title": "TEST_UI New Poll", "date": future}, headers=ADMIN).json()["event_id"]
    requests.post(f"{API}/events/{e1}/poll", json={"kind": "venue", "options": ["TEST_V1", "TEST_V2"],
                                                   "closes_on": (TODAY + timedelta(days=3)).isoformat()}, headers=ADMIN)
    p = requests.post(f"{API}/events/{e2}/poll", json={"kind": "venue", "options": ["TEST_W1", "TEST_W2"]}, headers=ADMIN).json()
    opt = p["poll"]["options"][1]
    db.events.update_one({"event_id": e2}, {"$set": {"poll.closed": True, "poll.locked_option_id": opt["option_id"],
                                                     "poll.auto_locked": True, "location": opt["label"]}})
    for i in range(2):
        requests.post(f"{API}/directory", json={"space": "participant", "category": "Activities", "name": f"TEST_UIAct {i}",
                                                "address": f"{i + 1} Beach Rd WA"}, headers=ADMIN)
    for n, a in [("TEST_R6027", "Joondalup WA 6027"), ("TEST_R6030", "Quinns Rocks WA 6030"), ("TEST_R6100", "Burswood WA 6100")]:
        requests.post(f"{API}/directory", json={"space": "therapist", "category": REF, "name": n, "address": a, "services": "OT"},
                      headers=ADMIN)
    time.sleep(6)
    print("open", e1, "auto", e2, "new", e3)


if __name__ == "__main__":
    clean() if len(sys.argv) > 1 and sys.argv[1] == "clean" else seed()
