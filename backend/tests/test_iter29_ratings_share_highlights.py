# Iteration 29: Directory star ratings (Suppliers/Activities), Referral Quick Share to fixed channel,
# Home highlights (new Templates/Resources within 14 days).
# NOTE: uses a temporary TEST_ channel (no Google Chat webhook) so no real team channel is touched.
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
import requests
from dotenv import load_dotenv
from pymongo import MongoClient

load_dotenv("/app/backend/.env")


def _base():
    url = os.environ.get("EXPO_PUBLIC_BACKEND_URL") or os.environ.get("EXPO_BACKEND_URL")
    if not url:
        for line in Path("/app/frontend/.env").read_text().splitlines():
            if line.startswith(("EXPO_PUBLIC_BACKEND_URL=", "EXPO_BACKEND_URL=")):
                url = line.split("=", 1)[1].strip().strip('"')
                break
    return url.rstrip("/")


BASE = _base() + "/api"
ADMIN = {"Authorization": "Bearer test_session_admin"}
EMP = {"Authorization": "Bearer test_session_employee"}
mdb = MongoClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]
TEST_CONV = "conv_TEST_refshare"
created = []


def mk(space, category, name, **kw):
    r = requests.post(f"{BASE}/directory", headers=ADMIN, json={"space": space, "category": category, "name": name, **kw})
    assert r.status_code == 200, r.text
    created.append(r.json()["entry_id"])
    return r.json()


@pytest.fixture(scope="module", autouse=True)
def setup_teardown():
    mdb.conversations.insert_one({"conversation_id": TEST_CONV, "type": "channel", "name": "TEST_referrals",
                                  "description": "", "member_ids": [], "last_message": "", "last_at": "",
                                  "created_at": datetime.now(timezone.utc).isoformat()})
    prev = mdb.settings.find_one({"key": "referral_share_channel"})
    mdb.settings.delete_one({"key": "referral_share_channel"})
    yield
    for eid in created:
        mdb.directory.delete_one({"entry_id": eid})
    mdb.directory.delete_many({"name": {"$regex": "^TEST_"}})
    mdb.messages.delete_many({"conversation_id": TEST_CONV})
    mdb.conv_reads.delete_many({"conversation_id": TEST_CONV})
    mdb.conversations.delete_one({"conversation_id": TEST_CONV})
    mdb.settings.delete_one({"key": "referral_share_channel"})
    if prev:
        prev.pop("_id", None)
        mdb.settings.insert_one(prev)


# ---------- Ratings ----------
class TestRatings:
    def test_rate_validation_and_replace(self):
        e = mk("participant", "Activities", "TEST_Act A")
        assert e["avg_rating"] == 0 and e["rating_count"] == 0 and e["my_rating"] == 0
        for bad in (0, 6, -1):
            r = requests.post(f"{BASE}/directory/{e['entry_id']}/rate", headers=EMP, json={"stars": bad})
            assert r.status_code == 400, (bad, r.text)
        r = requests.post(f"{BASE}/directory/{e['entry_id']}/rate", headers=EMP, json={"stars": 2})
        assert r.status_code == 200 and r.json()["my_rating"] == 2 and r.json()["rating_count"] == 1
        r = requests.post(f"{BASE}/directory/{e['entry_id']}/rate", headers=EMP, json={"stars": 4})
        d = r.json()
        assert d["my_rating"] == 4 and d["rating_count"] == 1 and d["avg_rating"] == 4
        assert "ratings" not in d
        r = requests.post(f"{BASE}/directory/{e['entry_id']}/rate", headers=ADMIN, json={"stars": 1})
        d = r.json()
        assert d["rating_count"] == 2 and d["avg_rating"] == 2.5 and d["my_rating"] == 1

    def test_rate_non_rateable_and_missing(self):
        t = mk("therapist", "Templates", "TEST_Tpl rate")
        r = requests.post(f"{BASE}/directory/{t['entry_id']}/rate", headers=ADMIN, json={"stars": 3})
        assert r.status_code == 400
        assert "avg_rating" not in t
        ref = mk("therapist", "Trusted Referral Partner Organisations", "TEST_Ref rate")
        assert requests.post(f"{BASE}/directory/{ref['entry_id']}/rate", headers=ADMIN, json={"stars": 3}).status_code == 400
        assert requests.post(f"{BASE}/directory/dir_nope/rate", headers=ADMIN, json={"stars": 3}).status_code == 404
        assert requests.post(f"{BASE}/directory/{t['entry_id']}/rate", json={"stars": 3}).status_code == 401

    def test_list_sorted_by_avg_and_no_raw(self):
        a = mk("therapist", "Suppliers", "TEST_Sup A")
        b = mk("therapist", "Suppliers", "TEST_Sup B")
        c = mk("therapist", "Suppliers", "TEST_Sup C")
        requests.post(f"{BASE}/directory/{a['entry_id']}/rate", headers=EMP, json={"stars": 2})
        requests.post(f"{BASE}/directory/{c['entry_id']}/rate", headers=EMP, json={"stars": 5})
        requests.post(f"{BASE}/directory/{c['entry_id']}/rate", headers=ADMIN, json={"stars": 4})
        lst = requests.get(f"{BASE}/directory", headers=EMP, params={"space": "therapist", "category": "Suppliers"}).json()
        ids = [x["entry_id"] for x in lst if x["name"].startswith("TEST_Sup")]
        assert ids == [c["entry_id"], a["entry_id"], b["entry_id"]], [(x["name"], x["avg_rating"]) for x in lst]
        for x in lst:
            assert "ratings" not in x
        cc = next(x for x in lst if x["entry_id"] == c["entry_id"])
        assert cc["avg_rating"] == 4.5 and cc["rating_count"] == 2 and cc["my_rating"] == 5
        # Edit by admin must keep ratings
        r = requests.put(f"{BASE}/directory/{c['entry_id']}", headers=ADMIN,
                         json={"space": "therapist", "category": "Suppliers", "name": "TEST_Sup C2"})
        assert r.status_code == 200 and r.json()["rating_count"] == 2


# ---------- Share channel ----------
class TestShare:
    def test_share_flow(self):
        r = requests.get(f"{BASE}/directory/share-channel", headers=EMP)
        assert r.status_code == 200 and r.json() is None
        ref = mk("therapist", "Trusted Referral Partner Organisations", "TEST_Ref Partner",
                 contact="Jane", phone="0400 000 000", email="j@x.com", link="example.org", note="Great OT")
        r = requests.post(f"{BASE}/directory/{ref['entry_id']}/share", headers=EMP)
        assert r.status_code == 400 and "channel" in r.json()["detail"].lower()
        # admin-only
        assert requests.put(f"{BASE}/directory/share-channel", headers=EMP, json={"conversation_id": TEST_CONV}).status_code == 403
        assert requests.put(f"{BASE}/directory/share-channel", headers=ADMIN, json={"conversation_id": "conv_nope"}).status_code == 404
        dm = mdb.conversations.find_one({"type": "dm"}, {"conversation_id": 1})
        if dm:
            assert requests.put(f"{BASE}/directory/share-channel", headers=ADMIN, json={"conversation_id": dm["conversation_id"]}).status_code == 404
        r = requests.put(f"{BASE}/directory/share-channel", headers=ADMIN, json={"conversation_id": TEST_CONV})
        assert r.status_code == 200 and r.json() == {"conversation_id": TEST_CONV, "name": "TEST_referrals"}
        assert requests.get(f"{BASE}/directory/share-channel", headers=EMP).json()["conversation_id"] == TEST_CONV
        # non-referral -> 400
        sup = mk("therapist", "Suppliers", "TEST_Sup share")
        assert requests.post(f"{BASE}/directory/{sup['entry_id']}/share", headers=EMP).status_code == 400
        assert requests.post(f"{BASE}/directory/dir_nope/share", headers=EMP).status_code == 404
        # employee shares
        r = requests.post(f"{BASE}/directory/{ref['entry_id']}/share", headers=EMP)
        assert r.status_code == 200 and r.json()["channel"] == "TEST_referrals" and r.json()["ok"] is True
        msgs = requests.get(f"{BASE}/conversations/{TEST_CONV}/messages", headers=EMP).json()
        msgs = msgs if isinstance(msgs, list) else msgs.get("messages", msgs)
        last = msgs[-1]["text"]
        assert last.startswith("🤝 Referral partner: TEST_Ref Partner"), last
        for frag in ("Contact: Jane", "Phone: 0400 000 000", "Email: j@x.com", "Website: https://example.org", "Notes: Great OT"):
            assert frag in last
        conv = mdb.conversations.find_one({"conversation_id": TEST_CONV})
        assert conv["last_message"].startswith(f"Test:") or "Referral partner" in conv["last_message"]


# ---------- Highlights ----------
class TestHighlights:
    def test_highlights_filters(self):
        t = mk("therapist", "Templates", "TEST_HL Template")
        r = mk("participant", "Resources", "TEST_HL Resource")
        s = mk("participant", "Suppliers", "TEST_HL Supplier")
        a = mk("participant", "Activities", "TEST_HL Activity")
        old = mk("therapist", "Templates", "TEST_HL Old")
        mdb.directory.update_one({"entry_id": old["entry_id"]},
                                 {"$set": {"created_at": (datetime.now(timezone.utc) - timedelta(days=15)).isoformat()}})
        mdb.directory.update_one({"entry_id": t["entry_id"]},
                                 {"$push": {"files": {"file_id": "dfl_x", "name": "a.pdf", "storage_path": "x"}}})
        h = requests.get(f"{BASE}/directory/highlights", headers=EMP)
        assert h.status_code == 200
        ids = {x["entry_id"]: x for x in h.json()}
        assert t["entry_id"] in ids and r["entry_id"] in ids
        assert s["entry_id"] not in ids and a["entry_id"] not in ids and old["entry_id"] not in ids
        assert ids[t["entry_id"]]["file_count"] == 1 and ids[r["entry_id"]]["file_count"] == 0
        assert "files" not in ids[t["entry_id"]] and "_id" not in ids[t["entry_id"]]
        assert ids[t["entry_id"]]["space"] == "therapist" and ids[t["entry_id"]]["category"] == "Templates"
        assert requests.get(f"{BASE}/directory/highlights").status_code == 401
