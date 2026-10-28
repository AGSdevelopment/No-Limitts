# Iteration 29 UI seed/cleanup: python seed_iter29_ui.py seed|clean
import sys
from datetime import datetime, timezone
from pymongo import MongoClient

mdb = MongoClient("mongodb://localhost:27017")["test_database"]
NOW = datetime.now(timezone.utc).isoformat()
CONV = "conv_TEST_refshare"


def seed():
    clean()
    mdb.conversations.insert_one({"conversation_id": CONV, "type": "channel", "name": "TEST_referrals", "description": "",
                                  "member_ids": [], "last_message": "", "last_at": "", "created_at": NOW})
    base = {"contact": "", "phone": "", "email": "", "address": "", "link": "", "note": "", "files": [],
            "created_by": "Test Admin", "created_by_id": "user_testadmin01", "created_at": NOW}
    mdb.directory.insert_many([
        {**base, "entry_id": "dir_test_ref1", "space": "therapist", "category": "Trusted Referral Partner Organisations",
         "name": "TEST_Ref Partner", "contact": "Jane", "phone": "0400 111 222"},
        {**base, "entry_id": "dir_test_act1", "space": "participant", "category": "Activities", "name": "TEST_Act Alpha"},
        {**base, "entry_id": "dir_test_act2", "space": "participant", "category": "Activities", "name": "TEST_Act Beta",
         "ratings": {"user_testadmin01": 3}},
        {**base, "entry_id": "dir_test_tpl1", "space": "therapist", "category": "Templates", "name": "TEST_Tpl Session Notes",
         "files": [{"file_id": "dfl_t1", "name": "a.pdf", "storage_path": "x", "content_type": "application/pdf", "size": 1}]},
    ])
    mdb.places.insert_one({"place_id": "plc_test_1", "name": "TEST_Place Cafe", "kind": "Coffee", "address": "Fremantle",
                           "link": "", "note": "", "likes": [], "created_by": "Test Admin", "created_by_id": "user_testadmin01",
                           "created_at": NOW})


def clean():
    mdb.directory.delete_many({"name": {"$regex": "^TEST_"}})
    mdb.places.delete_many({"name": {"$regex": "^TEST_"}})
    mdb.messages.delete_many({"conversation_id": CONV})
    mdb.conv_reads.delete_many({"conversation_id": CONV})
    mdb.conversations.delete_one({"conversation_id": CONV})
    mdb.settings.delete_one({"key": "referral_share_channel"})


if __name__ == "__main__":
    seed() if sys.argv[1] == "seed" else clean()
    print("ok", mdb.directory.count_documents({}), mdb.places.count_documents({}))
