# Seed/cleanup for iteration 30 UI tests. Usage: python seed_iter30_ui.py seed|share_test|restore|cleanup
import os, sys
from datetime import datetime, timezone
from dotenv import load_dotenv
from pymongo import MongoClient

load_dotenv("/app/backend/.env")
db = MongoClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]
now = datetime.now(timezone.utc).isoformat()
ALLIED, TEST_CONV = "conv_ab9e05c17d16", "conv_TEST_ui30"
mode = sys.argv[1]
if mode == "seed":
    db.directory.insert_one({"entry_id": "dir_TEST_ui30sup", "space": "participant", "category": "Suppliers",
                             "name": "TEST_UI Supplier", "services": "", "contact": "", "phone": "0400 000 000",
                             "email": "", "address": "Osborne Park", "link": "", "note": "Sensory tools", "files": [],
                             "created_by": "Test Admin", "created_by_id": "user_testadmin01", "created_at": now})
    db.places.insert_one({"place_id": "plc_TEST_ui30", "name": "TEST_UI Cafe", "kind": "Coffee", "address": "Perth",
                          "link": "", "note": "Good coffee", "likes": [], "created_by": "Test Admin",
                          "created_by_id": "user_testadmin01", "created_at": now})
    db.conversations.insert_one({"conversation_id": TEST_CONV, "type": "channel", "name": "TEST_ui30",
                                 "description": "", "member_ids": [], "last_message": "", "last_at": "", "created_at": now})
elif mode == "share_test":
    db.settings.update_one({"key": "referral_share_channel"}, {"$set": {"conversation_id": TEST_CONV}})
elif mode == "restore":
    db.settings.update_one({"key": "referral_share_channel"}, {"$set": {"conversation_id": ALLIED}}, upsert=True)
elif mode == "cleanup":
    db.settings.update_one({"key": "referral_share_channel"}, {"$set": {"conversation_id": ALLIED}}, upsert=True)
    print("msgs in test conv:", [m["text"] for m in db.messages.find({"conversation_id": TEST_CONV})])
    db.directory.delete_many({"name": {"$regex": "^TEST_"}})
    db.places.delete_many({"name": {"$regex": "^TEST_"}})
    db.messages.delete_many({"conversation_id": TEST_CONV})
    db.conv_reads.delete_many({"conversation_id": TEST_CONV})
    db.conversations.delete_one({"conversation_id": TEST_CONV})
    print("allied TEST msgs:", db.messages.count_documents({"conversation_id": ALLIED, "text": {"$regex": "TEST_"}}))
print("ok", mode)
