# Iteration 32 UI seed: 3 approved TEST_ activities (run with "clean" arg to remove TEST_ data + vote events)
import os
import sys
from datetime import datetime, timezone

from dotenv import load_dotenv
from pymongo import MongoClient

load_dotenv("/app/backend/.env")
db = MongoClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]

if len(sys.argv) > 1 and sys.argv[1] == "clean":
    since = sys.argv[2] if len(sys.argv) > 2 else "9999"
    db.directory.delete_many({"name": {"$regex": "^TEST_"}})
    r = db.events.delete_many({"poll.kind": "activity", "created_at": {"$gte": since}})
    db.notifications.delete_many({"created_at": {"$gte": since}, "type": {"$in": ["directory", "event"]}})
    print("cleaned events", r.deleted_count)
else:
    now = datetime.now(timezone.utc).isoformat()
    for i, (n, a) in enumerate([("TEST_UI Bowling", "Joondalup Bowl WA 6027"), ("TEST_UI Picnic", "Kings Park WA 6005"),
                                ("TEST_UI Zoo", "Perth Zoo WA 6151")]):
        db.directory.insert_one({"entry_id": f"dir_TEST_ui32_{i}", "space": "participant", "category": "Activities", "name": n,
                                 "services": "", "contact": "", "phone": "", "email": "", "address": a, "link": "", "note": "",
                                 "files": [], "status": "approved", "created_by": "Seed", "created_by_id": "user_testadmin01",
                                 "created_at": now})
    print("seeded", now)
