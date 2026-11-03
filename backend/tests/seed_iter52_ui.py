# Iteration 52 UI seed: one unassigned + one assigned participant with a pending case note for the test Support Worker.
# Run `python seed_iter52_ui.py` to seed and `python seed_iter52_ui.py clean` to clean up.
import os
import sys
import requests
from dotenv import load_dotenv
from pymongo import MongoClient

load_dotenv("/app/frontend/.env")
load_dotenv("/app/backend/.env")
API = (os.environ.get("EXPO_PUBLIC_BACKEND_URL") or os.environ.get("EXPO_BACKEND_URL")).rstrip("/") + "/api"
ADMIN = {"Authorization": "Bearer test_session_admin"}
EMP = {"Authorization": "Bearer test_session_employee"}
mdb = MongoClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]
NAMES = ("TEST_UI Lock", "TEST_UI Nobody", "TEST_UI Second")

if len(sys.argv) > 1 and sys.argv[1] == "clean":
    for p in mdb.participants.find({"key": {"$regex": "^test_ui"}}):
        requests.delete(f"{API}/participants/{p['participant_id']}", headers=ADMIN, timeout=30)
    print(mdb.case_note_starts.delete_many({"participant": {"$regex": "^test_ui"}}).deleted_count,
          mdb.notifications.delete_many({"title": {"$regex": "TEST_UI"}}).deleted_count)
    sys.exit()

ids = {}
for n in NAMES:
    r = requests.post(f"{API}/participants", json={"name": n}, headers=ADMIN, timeout=30)
    print(n, r.status_code)
    ids[n] = r.json().get("participant_id") or mdb.participants.find_one({"name": n})["participant_id"]
for n in ("TEST_UI Lock", "TEST_UI Second"):
    requests.put(f"{API}/participants/{ids[n]}/assign", json={"user_ids": ["user_testemp001"]}, headers=ADMIN, timeout=30)
mdb.participants.update_many({"key": {"$regex": "^test_ui"}}, {"$set": {"intro_seen_ids": ["user_testemp001"]}})
forms = requests.get(f"{API}/caseload/forms", params={"participant": "TEST_UI Lock"}, headers=EMP, timeout=90).json()
f = next(x for x in forms if x.get("form_id"))
r = requests.post(f"{API}/caseload/forms/open", json={"participant": "TEST_UI Lock", "form_id": f["form_id"], "url": f["url"]}, headers=EMP, timeout=90)
print("open", r.status_code, f["title"])
print("pending", requests.get(f"{API}/caseload/pending", headers=EMP, timeout=60).json())
