# Iteration 30: Rating comments (reviews), share Suppliers/Activities/Referral to share channel,
# 'services' field, admin edit of AGTS places, weekly resource digest admin preview.
# NOTE: shares go to a temporary TEST_ channel; settings key restored to Allied Health afterwards.
import os
from datetime import datetime, timezone
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
ALLIED = "conv_ab9e05c17d16"
TEST_CONV = "conv_TEST_share30"
created, places = [], []


def mk(space, category, name, **kw):
    r = requests.post(f"{BASE}/directory", headers=ADMIN, json={"space": space, "category": category, "name": name, **kw})
    assert r.status_code == 200, r.text
    created.append(r.json()["entry_id"])
    return r.json()


@pytest.fixture(scope="module", autouse=True)
def setup_teardown():
    prev = mdb.settings.find_one({"key": "referral_share_channel"})
    mdb.conversations.insert_one({"conversation_id": TEST_CONV, "type": "channel", "name": "TEST_share30",
                                  "description": "", "member_ids": [], "last_message": "", "last_at": "",
                                  "created_at": datetime.now(timezone.utc).isoformat()})
    yield
    for eid in created:
        mdb.directory.delete_one({"entry_id": eid})
    mdb.directory.delete_many({"name": {"$regex": "^TEST_"}})
    for pid in places:
        mdb.places.delete_one({"place_id": pid})
    mdb.places.delete_many({"name": {"$regex": "^TEST_"}})
    mdb.messages.delete_many({"conversation_id": TEST_CONV})
    mdb.conv_reads.delete_many({"conversation_id": TEST_CONV})
    mdb.conversations.delete_one({"conversation_id": TEST_CONV})
    mdb.settings.update_one({"key": "referral_share_channel"},
                            {"$set": {"conversation_id": (prev or {}).get("conversation_id", ALLIED)}}, upsert=True)


# ---------- Resource digest (run first, while directory has nothing new) ----------
class TestResourceDigest:
    def test_digest_empty_400_and_employee_403(self):
        r = requests.post(f"{BASE}/digest/resources/test", headers=EMP)
        assert r.status_code == 403
        if mdb.directory.count_documents({}) == 0:
            r = requests.post(f"{BASE}/digest/resources/test", headers=ADMIN)
            assert r.status_code == 400, r.text
            assert "Nothing new" in r.json()["detail"]

    def test_digest_with_new_template(self):
        mk("therapist", "Templates", "TEST_Digest Template", note="hello")
        r = requests.post(f"{BASE}/digest/resources/test", headers=ADMIN, timeout=60)
        assert r.status_code == 200, r.text
        d = r.json()
        assert d["new"] >= 1 and d["email"] == "admin.test@example.com" and "sent" in d


# ---------- Rating comments ----------
class TestReviews:
    def test_comment_flow(self):
        e = mk("therapist", "Suppliers", "TEST_Sup Review")
        r = requests.post(f"{BASE}/directory/{e['entry_id']}/rate", headers=EMP, json={"stars": 4, "comment": "  Great service  "})
        assert r.status_code == 200, r.text
        d = r.json()
        assert d["my_comment"] == "Great service" and d["my_rating"] == 4
        assert "ratings" not in d and "comments" not in d
        assert len(d["reviews"]) == 1 and d["reviews"][0]["text"] == "Great service" and d["reviews"][0]["stars"] == 4
        assert set(d["reviews"][0].keys()) == {"name", "text", "at", "stars"}
        # admin adds newer review -> newest first
        r = requests.post(f"{BASE}/directory/{e['entry_id']}/rate", headers=ADMIN, json={"stars": 2, "comment": "Slow delivery"})
        d = r.json()
        assert [x["text"] for x in d["reviews"]] == ["Slow delivery", "Great service"]
        assert d["my_comment"] == "Slow delivery"
        # employee re-rates without comment -> keeps old comment, stars updated in review
        r = requests.post(f"{BASE}/directory/{e['entry_id']}/rate", headers=EMP, json={"stars": 5})
        d = r.json()
        assert d["my_comment"] == "Great service" and d["my_rating"] == 5
        emp_rev = [x for x in d["reviews"] if x["text"] == "Great service"][0]
        assert emp_rev["stars"] == 5
        # GET & list expose reviews but not raw dicts
        g = requests.get(f"{BASE}/directory/{e['entry_id']}", headers=EMP).json()
        assert g["my_comment"] == "Great service" and len(g["reviews"]) == 2 and "comments" not in g
        lst = requests.get(f"{BASE}/directory", headers=EMP, params={"space": "therapist", "category": "Suppliers"}).json()
        it = [x for x in lst if x["entry_id"] == e["entry_id"]][0]
        assert len(it["reviews"]) == 2 and "ratings" not in it and "comments" not in it

    def test_comment_truncated_and_cleared(self):
        e = mk("participant", "Activities", "TEST_Act Review")
        r = requests.post(f"{BASE}/directory/{e['entry_id']}/rate", headers=EMP, json={"stars": 3, "comment": "x" * 500})
        assert len(r.json()["my_comment"]) == 300
        r = requests.post(f"{BASE}/directory/{e['entry_id']}/rate", headers=EMP, json={"stars": 3, "comment": ""})
        assert r.json()["my_comment"] == "" and r.json()["reviews"] == []

    def test_comment_non_rateable(self):
        t = mk("participant", "Resources", "TEST_Res Review")
        r = requests.post(f"{BASE}/directory/{t['entry_id']}/rate", headers=EMP, json={"stars": 3, "comment": "hi"})
        assert r.status_code == 400
        assert "reviews" not in t


# ---------- Services field ----------
class TestServices:
    def test_services_crud(self):
        e = mk("therapist", "Trusted Referral Partner Organisations", "TEST_Ref Co", services="OT, Speech",
               phone="0400", email="a@b.com", link="example.com", address="6000")
        assert e["services"] == "OT, Speech" and e["link"] == "https://example.com"
        r = requests.put(f"{BASE}/directory/{e['entry_id']}", headers=ADMIN,
                         json={"space": "therapist", "category": "Trusted Referral Partner Organisations",
                               "name": "TEST_Ref Co", "services": "Physio", "address": "6000"})
        assert r.status_code == 200 and r.json()["services"] == "Physio"
        g = requests.get(f"{BASE}/directory/{e['entry_id']}", headers=EMP).json()
        assert g["services"] == "Physio"
        r = requests.post(f"{BASE}/directory", headers=EMP, json={"space": "therapist", "category": "Suppliers", "name": "TEST_x"})
        assert r.status_code == 403


# ---------- Share ----------
class TestShare:
    def test_default_share_channel_allied(self):
        r = requests.get(f"{BASE}/directory/share-channel", headers=EMP)
        assert r.status_code == 200
        assert r.json() == {"conversation_id": ALLIED, "name": "Allied Health"}

    def test_share_to_test_channel(self):
        r = requests.put(f"{BASE}/directory/share-channel", headers=EMP, json={"conversation_id": TEST_CONV})
        assert r.status_code == 403
        r = requests.put(f"{BASE}/directory/share-channel", headers=ADMIN, json={"conversation_id": TEST_CONV})
        assert r.status_code == 200 and r.json()["name"] == "TEST_share30"
        sup = mk("participant", "Suppliers", "TEST_Share Sup", phone="111")
        act = mk("participant", "Activities", "TEST_Share Act", note="Fun")
        ref = mk("therapist", "Trusted Referral Partner Organisations", "TEST_Share Ref", services="OT", email="r@x.com")
        tpl = mk("therapist", "Templates", "TEST_Share Tpl")
        res = mk("participant", "Resources", "TEST_Share Res")
        for e in (sup, act, ref):
            r = requests.post(f"{BASE}/directory/{e['entry_id']}/share", headers=EMP)
            assert r.status_code == 200, r.text
            assert r.json()["conversation_id"] == TEST_CONV
        for e in (tpl, res):
            r = requests.post(f"{BASE}/directory/{e['entry_id']}/share", headers=EMP)
            assert r.status_code == 400
        texts = [m["text"] for m in mdb.messages.find({"conversation_id": TEST_CONV})]
        assert any(t.startswith("🛒 Supplier: TEST_Share Sup") and "Phone: 111" in t for t in texts), texts
        assert any(t.startswith("🎯 Activity: TEST_Share Act") and "Notes: Fun" in t for t in texts), texts
        assert any(t.startswith("🤝 Referral partner: TEST_Share Ref") and "Services: OT" in t for t in texts), texts
        assert mdb.messages.count_documents({"conversation_id": ALLIED, "text": {"$regex": "TEST_"}}) == 0
        # restore
        r = requests.put(f"{BASE}/directory/share-channel", headers=ADMIN, json={"conversation_id": ALLIED})
        assert r.json()["name"] == "Allied Health"


# ---------- Places edit ----------
class TestPlacesEdit:
    def test_edit_place(self):
        a = requests.post(f"{BASE}/places", headers=ADMIN, json={"name": "TEST_Cafe A", "kind": "Coffee"}).json()
        b = requests.post(f"{BASE}/places", headers=ADMIN, json={"name": "TEST_Cafe B", "kind": "Coffee"}).json()
        places.extend([a["place_id"], b["place_id"]])
        body = {"name": "TEST_Cafe A2", "kind": "WiFi / Meet", "address": "1 St", "link": "x.com", "note": "n"}
        assert requests.put(f"{BASE}/places/{a['place_id']}", headers=EMP, json=body).status_code == 403
        r = requests.put(f"{BASE}/places/{a['place_id']}", headers=ADMIN, json=body)
        assert r.status_code == 200, r.text
        assert r.json()["link"] == "https://x.com"
        lst = requests.get(f"{BASE}/places", headers=EMP).json()
        p = [x for x in lst if x["place_id"] == a["place_id"]][0]
        assert p["name"] == "TEST_Cafe A2" and p["kind"] == "WiFi / Meet" and p["address"] == "1 St"
        # same name on itself ok (case change)
        r = requests.put(f"{BASE}/places/{a['place_id']}", headers=ADMIN, json={**body, "name": "test_cafe a2"})
        assert r.status_code == 200
        # duplicate of another place
        r = requests.put(f"{BASE}/places/{a['place_id']}", headers=ADMIN, json={**body, "name": "test_cafe b"})
        assert r.status_code == 409
        r = requests.put(f"{BASE}/places/{a['place_id']}", headers=ADMIN, json={**body, "kind": "Bar"})
        assert r.status_code == 400
        r = requests.put(f"{BASE}/places/plc_missing", headers=ADMIN, json={**body, "name": "TEST_zzz"})
        assert r.status_code == 404
