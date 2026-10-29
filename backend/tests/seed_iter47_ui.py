# Iteration 47 UI seed: link / unlink Teams announcements so the Integrations toggles render
import os
import sys
from dotenv import load_dotenv
from pymongo import MongoClient

load_dotenv("/app/backend/.env")
sys.path.insert(0, "/app/backend")
import ms_services as ms  # noqa: E402

mdb = MongoClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]
if sys.argv[1:] == ["link"]:
    mdb.integrations.update_one({"key": "teams_announcements"}, {"$set": {
        "webhook": ms.encrypt("https://prod-11.australiasoutheast.logic.azure.com/workflows/abc"),
        "updates": True, "events": True, "celebrations": True, "weekly_wrap": True}}, upsert=True)
elif sys.argv[1:] == ["show"]:
    print(mdb.integrations.find_one({"key": "teams_announcements"}, {"_id": 0, "webhook": 0}))
else:
    mdb.integrations.delete_one({"key": "teams_announcements"})
print("ok")
