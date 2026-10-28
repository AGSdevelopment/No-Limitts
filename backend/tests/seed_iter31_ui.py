# Seed/cleanup for iteration 31 UI tests. Usage: python seed_iter31_ui.py seed|cleanup
import os, sys
from datetime import datetime, timezone
from dotenv import load_dotenv
from pymongo import MongoClient

load_dotenv("/app/backend/.env")
db = MongoClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]
now = datetime.now(timezone.utc).isoformat()
REF = "Trusted Referral Partner Organisations"
START = "2026-01-01"


def entry(eid, space, cat, name, address, **kw):
    return {"entry_id": eid, "space": space, "category": cat, "name": name, "services": kw.get("services", ""),
            "contact": "", "phone": "", "email": "", "address": address, "link": kw.get("link", ""),
            "note": kw.get("note", ""), "files": [], "status": "approved", "created_by": "Test Admin",
            "created_by_id": "user_testadmin01", "created_at": now, **{k: v for k, v in kw.items() if k in ("ratings", "comments")}}


mode = sys.argv[1]
if mode == "seed":
    db.directory.insert_many([
        entry("dir_TEST_r6027", "therapist", REF, "TEST_Ref Joondalup", "Joondalup WA 6027", services="Speech"),
        entry("dir_TEST_r6030", "therapist", REF, "TEST_Ref Clarkson", "Clarkson WA 6030", services="OT"),
        entry("dir_TEST_r6065", "therapist", REF, "TEST_Ref Wanneroo", "Wanneroo WA 6065", services="Physio"),
        entry("dir_TEST_r6000", "therapist", REF, "TEST_Ref Perth", "Perth WA 6000", services="Psych"),
        entry("dir_TEST_rnone", "therapist", REF, "TEST_Ref Online", "Online only", services="Telehealth"),
        entry("dir_TEST_act31", "participant", "Activities", "TEST_Act Rock Climbing", "Osborne Park",
              note="Indoor climbing fun", link="https://example.com/climb"),
        entry("dir_TEST_sup31", "participant", "Suppliers", "TEST_Sup Sensory", "Perth",
              ratings={"user_testemp001": 5},
              comments={"user_testemp001": {"text": "TEST great sensory tools", "name": "Erin Employee", "at": now}}),
    ])
elif mode == "cleanup":
    print("dir:", db.directory.delete_many({"name": {"$regex": "^TEST_"}}).deleted_count)
    print("ntf:", db.notifications.delete_many({"type": "directory", "body": {"$regex": "TEST_"}}).deleted_count)
    print("events:", list(db.events.find({"title": {"$regex": "^TEST_"}}, {"_id": 0, "event_id": 1})))
print("ok", mode)
