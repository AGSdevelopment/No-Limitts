"""Iter54 UI seed: `seed` unhides user_testemp001 and adds 2 TEST certs (expiring 45d + expired); `clean` restores."""
import sys
from datetime import date, timedelta

from pymongo import MongoClient


def _env(key):
    for line in open("/app/backend/.env"):
        if line.startswith(key + "="):
            return line.split("=", 1)[1].strip().strip('"')


db = MongoClient(_env("MONGO_URL"))[_env("DB_NAME")]
IDS = ["cert_TESTUI_45", "cert_TESTUI_exp"]
if sys.argv[1] == "seed":
    t = date.today()
    db.certificates.insert_many([
        {"cert_id": IDS[0], "owner_id": "user_testemp001", "owner_name": "Erin Employee", "title": "TEST Manual Handling",
         "expiry_date": (t + timedelta(days=45)).isoformat(), "is_deleted": False, "storage_path": "x", "created_at": t.isoformat()},
        {"cert_id": IDS[1], "owner_id": "user_testemp001", "owner_name": "Erin Employee", "title": "TEST CPR",
         "expiry_date": (t - timedelta(days=3)).isoformat(), "is_deleted": False, "storage_path": "x", "created_at": t.isoformat()}])
    db.users.update_one({"user_id": "user_testemp001"}, {"$set": {"hidden": False}})
else:
    db.certificates.delete_many({"cert_id": {"$in": IDS}})
    db.users.update_one({"user_id": "user_testemp001"}, {"$set": {"hidden": True}})
print(sys.argv[1], "done")
