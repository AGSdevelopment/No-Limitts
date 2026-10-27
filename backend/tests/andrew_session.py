# Helper: create/delete a temporary session for andrew@aspireandgrow.com.au (usage: python andrew_session.py create|delete)
import os
import sys
from datetime import datetime, timezone, timedelta
from dotenv import load_dotenv
from pymongo import MongoClient

load_dotenv("/app/backend/.env")
db = MongoClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]
TOKEN = "test_session_andrew_tmp"
u = db.users.find_one({"email": "andrew@aspireandgrow.com.au"}, {"_id": 0})
print("andrew user:", u)
if sys.argv[1] == "create":
    db.user_sessions.delete_many({"session_token": TOKEN})
    now = datetime.now(timezone.utc)
    db.user_sessions.insert_one({"session_token": TOKEN, "user_id": u["user_id"],
                                 "expires_at": now + timedelta(days=1), "created_at": now})
    print("created")
else:
    r = db.user_sessions.delete_many({"session_token": TOKEN})
    print("deleted", r.deleted_count)
print("remaining tmp sessions:", db.user_sessions.count_documents({"session_token": TOKEN}))
convs = list(db.conversations.find({"gchat_two_way": {"$exists": True}}, {"_id": 0, "name": 1, "gchat_two_way": 1, "gchat_space": 1}))
print("conversations w/ gchat:", convs)
print("integration exists:", db.integrations.count_documents({"key": {"$regex": "chat"}}))
