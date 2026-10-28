# Seed/cleanup helper for iteration 24 UI checks (test users only). Usage: python iter24_ui_seed.py seed|clean
import os
import sys
from datetime import date, timedelta
import requests
from dotenv import load_dotenv
from pymongo import MongoClient

load_dotenv("/app/backend/.env")
sys.path.insert(0, "/app/backend/tests")
from test_iter24_resources_reminders_photos_ics import BASE_URL, ADMIN, PNG  # noqa: E402

mdb = MongoClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]
if sys.argv[1] == "seed":
    fut = (date.today() + timedelta(days=10)).isoformat()
    a = requests.post(f"{BASE_URL}/api/events", headers=ADMIN, json={"title": "TEST_evt24 UI Upcoming", "date": fut,
                      "time": "5:30pm", "location": "Office"}).json()
    b = requests.post(f"{BASE_URL}/api/events", headers=ADMIN, json={"title": "TEST_evt24 UI Past", "date": fut,
                      "time": "", "location": "Park"}).json()
    requests.post(f"{BASE_URL}/api/events/{b['event_id']}/photos", headers=ADMIN, files={"file": ("p.png", PNG, "image/png")})
    mdb.events.update_one({"event_id": b["event_id"]}, {"$set": {"date": (date.today() - timedelta(days=3)).isoformat()}})
    print(a["event_id"], b["event_id"])
else:
    mdb.events.delete_many({"title": {"$regex": "^TEST_evt24"}})
    mdb.notifications.delete_many({"$or": [{"body": {"$regex": "TEST_(evt24|upload24)"}}, {"title": {"$regex": "TEST_(evt24|upload24)"}}]})
    mdb.cpd_resources.delete_many({"title": {"$regex": "^TEST_upload24"}})
    mdb.cpd_logs.delete_many({"title": {"$regex": "^TEST_upload24"}})
    print("cleaned")
