# Seed/cleanup helper for iter53 UI test: `python iter53_ui_seed.py seed|clean`
import os
import sys
from datetime import datetime, timedelta, timezone
import requests
from dotenv import load_dotenv
from pymongo import MongoClient

load_dotenv("/app/backend/.env")
load_dotenv("/app/frontend/.env")
BASE = os.environ["EXPO_PUBLIC_BACKEND_URL"].rstrip("/")
H = {"Authorization": "Bearer test_session_admin"}
d = MongoClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]
if sys.argv[1] == "seed":
    p = requests.post(f"{BASE}/api/participants", headers=H, json={"name": "TEST_UI Missed"}).json()
    requests.put(f"{BASE}/api/participants/{p['participant_id']}/assign", headers=H, json={"user_ids": ["user_testemp001"]})
    d.participants.update_one({"participant_id": p["participant_id"]},
                              {"$set": {"created_at": (datetime.now(timezone.utc) - timedelta(days=20)).isoformat()}})
    print(p["participant_id"])
else:
    for p in d.participants.find({"name": {"$regex": "^TEST_"}}):
        requests.delete(f"{BASE}/api/participants/{p['participant_id']}", headers=H)
    d.notifications.delete_many({"user_id": "user_testemp001", "title": {"$regex": "TEST_"}})
    requests.put(f"{BASE}/api/caseload/settings", headers=H, json={"hour": 18})
    print("cleaned", d.participants.count_documents({}), d.meta.find_one({"key": "casenote_reminder_hour"})["hour"])
