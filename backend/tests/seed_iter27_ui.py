# Seed/cleanup for iteration 27 UI tests: places, organiser event, past events for leaderboard. Usage: python seed_iter27_ui.py [clean]
import os
import sys
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from dotenv import load_dotenv
from pymongo import MongoClient

load_dotenv("/app/backend/.env")
db = MongoClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]
now = datetime.now(timezone.utc).isoformat()
today = datetime.now(ZoneInfo("Australia/Perth")).date()


def clean():
    db.places.delete_many({"place_id": {"$regex": "^plc_test27"}})
    db.events.delete_many({"title": {"$regex": "^TEST_ui27"}})
    db.users.delete_many({"user_id": {"$in": ["TEST_user_ui27a", "TEST_user_ui27b"]}})
    db.cpd_goals.delete_many({"title": {"$regex": "^TEST_ui27"}})


clean()
if len(sys.argv) > 1 and sys.argv[1] == "clean":
    print("cleaned")
    sys.exit()

for pid, name, kind, addr in [("plc_test27eat1", "TEST_ui27 Noodle Bar", "Eat", "1 Hay St"),
                              ("plc_test27eat2", "TEST_ui27 Burger Co", "Eat & drink", ""),
                              ("plc_test27drk1", "TEST_ui27 Wine Cellar", "Drink", "9 Murray St")]:
    db.places.insert_one({"place_id": pid, "name": name, "kind": kind, "address": addr, "link": "", "note": "",
                          "likes": [], "created_by": "Test Admin", "created_by_id": "user_testadmin01", "created_at": now})
for uid, name in [("TEST_user_ui27a", "TEST_Ui Alpha"), ("TEST_user_ui27b", "TEST_Ui Bravo")]:
    db.users.insert_one({"user_id": uid, "name": name, "email": f"{uid.lower()}@example.com", "role": "employee", "created_at": now})
base = {"time": "", "location": "", "description": "", "attendees": [], "created_by": "Test Admin",
        "created_by_id": "user_testadmin01", "created_at": now, "comments": [], "photos": [], "catering": "none"}
past = (today - timedelta(days=2)).isoformat()
db.events.insert_one({**base, "event_id": "evt_test27past1", "title": "TEST_ui27 past 1", "date": past,
                      "attended": [{"user_id": "TEST_user_ui27a", "name": "TEST_Ui Alpha"}, {"user_id": "TEST_user_ui27b", "name": "TEST_Ui Bravo"}], "rsvps": []})
db.events.insert_one({**base, "event_id": "evt_test27past2", "title": "TEST_ui27 past 2", "date": past,
                      "rsvps": [{"user_id": "TEST_user_ui27a", "name": "TEST_Ui Alpha", "status": "going", "created_at": now}]})
db.events.insert_one({**base, "event_id": "evt_test27fut1", "title": "TEST_ui27 future", "date": (today + timedelta(days=14)).isoformat(), "rsvps": []})
print("seeded")
