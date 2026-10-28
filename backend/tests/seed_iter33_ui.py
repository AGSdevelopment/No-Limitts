# Seed / cleanup UI data for iteration 33 (python seed_iter33_ui.py [clean])
import os
import sys
import time
import requests
from dotenv import load_dotenv
from pymongo import MongoClient

load_dotenv("/app/frontend/.env")
load_dotenv("/app/backend/.env")
API = os.environ.get("EXPO_PUBLIC_BACKEND_URL").rstrip("/") + "/api"
db = MongoClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]
ADMIN = {"Authorization": "Bearer test_session_admin"}
EMP = {"Authorization": "Bearer test_session_employee"}
REF = "Trusted Referral Partner Organisations"

if len(sys.argv) > 1 and sys.argv[1] == "clean":
    print(db.directory.delete_many({"name": {"$regex": "^TEST_"}}).deleted_count, "dir")
    print(db.events.delete_many({"title": {"$regex": "^TEST_"}}).deleted_count, "events")
    print(db.notifications.delete_many({"$or": [{"title": {"$regex": "TEST_"}}, {"body": {"$regex": "TEST_"}}]}).deleted_count, "notifs")
    sys.exit()

for n, a in [("TEST_Joondalup Therapy", "Joondalup WA 6027"), ("TEST_Fremantle Allied", "Fremantle WA 6160")]:
    r = requests.post(f"{API}/directory", json={"space": "therapist", "category": REF, "name": n, "address": a,
                                                "services": "OT", "phone": "08 9000 0000"}, headers=ADMIN)
    print(r.status_code, r.json()["entry_id"])
r = requests.post(f"{API}/directory", json={"space": "participant", "category": "Activities", "name": "TEST_Pending Activity",
                                            "address": "1 Beach Rd WA"}, headers=EMP)
print("pending act", r.status_code, r.json()["entry_id"], r.json()["status"])
time.sleep(3)
