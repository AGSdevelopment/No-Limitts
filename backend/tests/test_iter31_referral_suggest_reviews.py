# Iteration 31: staff-suggested referral partners (pending/approve), visibility, files, share block, latest reviews
import os
from datetime import datetime, timedelta, timezone

import pytest
import requests
from dotenv import load_dotenv
from pymongo import MongoClient

load_dotenv("/app/frontend/.env")
load_dotenv("/app/backend/.env")
BASE_URL = os.environ.get("EXPO_PUBLIC_BACKEND_URL").rstrip("/")
API = f"{BASE_URL}/api"
db = MongoClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]
REF = "Trusted Referral Partner Organisations"
ADMIN = {"Authorization": "Bearer test_session_admin"}
EMP = {"Authorization": "Bearer test_session_employee"}
EMP2_TOKEN = "TEST_session_emp2_iter31"
EMP2 = {"Authorization": f"Bearer {EMP2_TOKEN}"}


@pytest.fixture(scope="module", autouse=True)
def setup_module_data():
    now = datetime.now(timezone.utc)
    db.users.insert_one({"user_id": "user_TEST_emp2", "email": "emp2.test@example.com", "name": "TEST Emp Two",
                         "role": "employee", "hidden": True, "created_at": now.isoformat()})
    db.user_sessions.insert_one({"session_token": EMP2_TOKEN, "user_id": "user_TEST_emp2",
                                 "created_at": now, "expires_at": now + timedelta(days=1)})
    since = now.isoformat()
    yield
    db.directory.delete_many({"name": {"$regex": "^TEST_"}})
    db.notifications.delete_many({"created_at": {"$gte": since}, "type": "directory"})
    db.users.delete_one({"user_id": "user_TEST_emp2"})
    db.user_sessions.delete_one({"session_token": EMP2_TOKEN})


def ref_body(name, **kw):
    return {"space": "therapist", "category": REF, "name": name, "services": "Speech", "phone": "08 1",
            "address": "Joondalup WA 6027", **kw}


def list_ref(h):
    r = requests.get(f"{API}/directory", params={"space": "therapist", "category": REF}, headers=h)
    assert r.status_code == 200
    return r.json()


@pytest.fixture(scope="module")
def pending():
    since = datetime.now(timezone.utc).isoformat()
    r = requests.post(f"{API}/directory", json=ref_body("TEST_Pending Ref"), headers=EMP)
    assert r.status_code == 200, r.text
    d = r.json()
    d["_since"] = since
    return d


class TestSuggest:
    def test_employee_referral_is_pending(self, pending):
        assert pending["status"] == "pending"
        assert pending["created_by_id"] == "user_testemp001"
        assert pending["can_edit"] is False
        assert "_id" not in pending

    def test_admin_notified(self, pending):
        n = db.notifications.find_one({"user_id": "user_testadmin01", "type": "directory",
                                       "created_at": {"$gte": pending["_since"]}}, {"_id": 0})
        assert n and "TEST_Pending Ref" in n["body"]
        # admin sees it via API too
        r = requests.get(f"{API}/notifications", headers=ADMIN)
        assert r.status_code == 200

    @pytest.mark.parametrize("space,cat", [("therapist", "Templates"), ("participant", "Resources")])  # iter32: Suppliers/Activities now suggestable
    def test_employee_other_categories_403(self, space, cat):
        r = requests.post(f"{API}/directory", json={"space": space, "category": cat, "name": "TEST_x"}, headers=EMP)
        assert r.status_code == 403

    def test_admin_add_is_approved(self):
        r = requests.post(f"{API}/directory", json=ref_body("TEST_Admin Ref"), headers=ADMIN)
        assert r.status_code == 200 and r.json()["status"] == "approved"


class TestVisibility:
    def test_admin_and_suggester_see_pending_first(self, pending):
        for h in (ADMIN, EMP):
            lst = list_ref(h)
            ids = [e["entry_id"] for e in lst]
            assert pending["entry_id"] in ids
            assert lst[0]["status"] == "pending"

    def test_other_employee_hidden(self, pending):
        assert pending["entry_id"] not in [e["entry_id"] for e in list_ref(EMP2)]
        assert requests.get(f"{API}/directory/{pending['entry_id']}", headers=EMP2).status_code == 404
        assert requests.get(f"{API}/directory/{pending['entry_id']}", headers=EMP).status_code == 200

    def test_share_blocked_while_pending(self, pending):
        r = requests.post(f"{API}/directory/{pending['entry_id']}/share", headers=EMP)
        assert r.status_code == 400


class TestFiles:
    def test_suggester_can_upload_own_pending(self, pending):
        r = requests.post(f"{API}/directory/{pending['entry_id']}/files", headers=EMP,
                          files={"file": ("TEST_note.txt", b"hello", "text/plain")})
        assert r.status_code == 200, r.text
        assert r.json()["name"] == "TEST_note.txt"

    def test_other_employee_cannot_upload(self, pending):
        r = requests.post(f"{API}/directory/{pending['entry_id']}/files", headers=EMP2,
                          files={"file": ("x.txt", b"x", "text/plain")})
        assert r.status_code == 403


class TestApprove:
    def test_employee_cannot_approve(self, pending):
        assert requests.post(f"{API}/directory/{pending['entry_id']}/approve", headers=EMP).status_code == 403

    def test_admin_approve_notifies_and_visible(self, pending):
        since = datetime.now(timezone.utc).isoformat()
        r = requests.post(f"{API}/directory/{pending['entry_id']}/approve", headers=ADMIN)
        assert r.status_code == 200 and r.json()["status"] == "approved"
        n = db.notifications.find_one({"user_id": "user_testemp001", "type": "directory", "created_at": {"$gte": since}})
        assert n and "approved" in n["title"].lower()
        assert pending["entry_id"] in [e["entry_id"] for e in list_ref(EMP2)]

    def test_approve_again_404(self, pending):
        assert requests.post(f"{API}/directory/{pending['entry_id']}/approve", headers=ADMIN).status_code == 404

    def test_suggester_cannot_upload_after_approval(self, pending):
        r = requests.post(f"{API}/directory/{pending['entry_id']}/files", headers=EMP,
                          files={"file": ("x.txt", b"x", "text/plain")})
        assert r.status_code == 403


class TestLatestReviews:
    def test_latest_reviews_shape_and_limit(self):
        now = datetime.now(timezone.utc)
        ids = []
        for i in range(7):
            r = requests.post(f"{API}/directory", headers=ADMIN, json={"space": "participant", "category": "Suppliers",
                                                                       "name": f"TEST_Rev Sup {i}"})
            eid = r.json()["entry_id"]
            ids.append(eid)
            requests.post(f"{API}/directory/{eid}/rate", headers=EMP, json={"stars": 4, "comment": f"TEST review {i}"})
        # an old review should be excluded
        old = (now - timedelta(days=40)).isoformat()
        db.directory.update_one({"entry_id": ids[0]}, {"$set": {"comments.user_testemp001.at": old}})
        # stars-only (no text) should be excluded
        requests.post(f"{API}/directory/{ids[1]}/rate", headers=ADMIN, json={"stars": 2})
        r = requests.get(f"{API}/directory/reviews/latest", headers=EMP)
        assert r.status_code == 200
        data = r.json()
        assert len(data) <= 5
        for k in ("entry_id", "entry_name", "name", "text", "stars", "at", "space", "category"):
            assert k in data[0]
        ats = [x["at"] for x in data]
        assert ats == sorted(ats, reverse=True)
        assert data[0]["entry_name"] == "TEST_Rev Sup 6" and data[0]["stars"] == 4
        assert ids[0] not in [x["entry_id"] for x in data]
        assert all(x["text"] for x in data)

    def test_latest_reviews_requires_auth(self):
        assert requests.get(f"{API}/directory/reviews/latest").status_code == 401
