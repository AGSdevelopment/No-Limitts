# Iteration 57 seed/cleanup helper: renewal-board certs, calendar cert, handover photos, birthday contact.
# Usage: python iter57_seed.py seed|cleanup   (ids stored in /tmp/iter57_seed.json; cleanup deletes only by those ids)
import json
import os
import sys
import uuid
from datetime import datetime, timedelta, timezone

from dotenv import load_dotenv
from pymongo import MongoClient

load_dotenv("/app/backend/.env")
db = MongoClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]
STATE = "/tmp/iter57_seed.json"
EMP = "user_testemp001"
ADMIN = "user_testadmin01"
PID = "par_960475e91169"
FAMILY_EMAIL = "test.family57@example.com"


def _cert(title, expiry, created, renews=None):
    cid = f"cert_TEST57_{uuid.uuid4().hex[:8]}"
    doc = {"cert_id": cid, "owner_id": EMP, "owner_name": "Emp Test", "title": title, "issuer": "", "issue_date": "",
           "expiry_date": expiry, "storage_path": "bogus/test.pdf", "file_name": "t.pdf", "content_type": "application/pdf",
           "size": 1, "is_deleted": False, "notified_stage": "expired", "created_at": created}
    if renews:
        doc["renews"] = renews
    db.certificates.insert_one(doc)
    return cid


def seed():
    now = datetime.now(timezone.utc)
    month = now.strftime("%Y-%m")
    st = {"certs": {}, "photos": [], "orig_hidden": db.users.find_one({"user_id": EMP})["hidden"],
          "orig_contacts": (db.participants.find_one({"participant_id": PID}).get("profile") or {}).get("contacts", [])}
    c = st["certs"]
    # On-time renewal: renewed 2026-06-20 before old expiry 2026-06-30
    c["a_old"] = _cert("TEST57 Alpha Training", "2026-06-30", "2025-06-01T00:00:00+00:00")
    c["a_new"] = _cert("TEST57 Alpha Training", "2027-06-30", "2026-06-20T00:00:00+00:00", renews=c["a_old"])
    # Late renewal: renewed 2026-04-15 after old expiry 2026-03-31 (older than the on-time one)
    c["b_old"] = _cert("TEST57 Beta Screening", "2026-03-31", "2025-03-01T00:00:00+00:00")
    c["b_new"] = _cert("TEST57 Beta Screening", "2027-04-15", "2026-04-15T00:00:00+00:00", renews=c["b_old"])
    # Calendar cert expiring this month on the 20th
    c["cal"] = _cert("TEST57 Calendar Cert", f"{month}-20", "2026-01-01T00:00:00+00:00")
    # Handover photos: 2 workers, 3 dates
    for by_id, by_name, days in [(EMP, "Emp Test", 2), (ADMIN, "Alex Admin", 20), (EMP, "Emp Test", 60)]:
        ph = {"photo_id": f"hph_TEST57_{uuid.uuid4().hex[:8]}", "participant": "test birthday person",
              "submission_id": f"sub_TEST57_{uuid.uuid4().hex[:6]}", "caption": f"TEST_ caption {days}d",
              "by_id": by_id, "by_name": by_name, "at": (now - timedelta(days=days)).isoformat(),
              "storage_path": "bogus/photo.jpg", "content_type": "image/jpeg"}
        db.handover_photos.insert_one(ph)
        st["photos"].append({"photo_id": ph["photo_id"], "by_id": by_id, "days": days})
    db.users.update_one({"user_id": EMP}, {"$set": {"hidden": False}})
    db.participants.update_one({"participant_id": PID}, {"$set": {"profile.contacts": st["orig_contacts"] + [
        {"name": "TEST57 Family", "relationship": "Mum", "phone": "", "email": FAMILY_EMAIL}]}})
    json.dump(st, open(STATE, "w"))
    return st


def cleanup():
    if not os.path.exists(STATE):
        return
    st = json.load(open(STATE))
    db.certificates.delete_many({"cert_id": {"$in": list(st["certs"].values())}})
    db.handover_photos.delete_many({"photo_id": {"$in": [p["photo_id"] for p in st["photos"]]}})
    db.users.update_one({"user_id": EMP}, {"$set": {"hidden": True}})
    db.participants.update_one({"participant_id": PID}, {"$set": {"profile.contacts": st["orig_contacts"]}})
    # birthday messages / card links created by tests (tracked ids)
    db.birthday_messages.delete_many({"message_id": {"$in": st.get("messages", [])}})
    db.birthday_card_links.delete_many({"token": {"$in": st.get("tokens", [])}})
    os.remove(STATE)


def track(key, value):
    st = json.load(open(STATE))
    st.setdefault(key, []).append(value)
    json.dump(st, open(STATE, "w"))


if __name__ == "__main__":
    {"seed": seed, "cleanup": cleanup}[sys.argv[1]]()
    print("ok", sys.argv[1])
