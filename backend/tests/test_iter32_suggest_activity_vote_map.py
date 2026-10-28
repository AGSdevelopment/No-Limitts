# Iteration 32: staff suggest Suppliers/Activities (pending), activity event poll, referral map (no key)
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
ADMIN = {"Authorization": "Bearer test_session_admin"}
EMP = {"Authorization": "Bearer test_session_employee"}
EMP2_TOKEN = "TEST_session_emp2_iter32"
EMP2 = {"Authorization": f"Bearer {EMP2_TOKEN}"}
STATE = {}


@pytest.fixture(scope="module", autouse=True)
def setup_module_data():
    now = datetime.now(timezone.utc)
    since = now.isoformat()
    db.users.insert_one({"user_id": "user_TEST_emp2_32", "email": "emp2.32@example.com", "name": "TEST Emp Two",
                         "role": "employee", "hidden": True, "created_at": since})
    db.user_sessions.insert_one({"session_token": EMP2_TOKEN, "user_id": "user_TEST_emp2_32",
                                 "created_at": now, "expires_at": now + timedelta(days=1)})
    yield
    db.directory.delete_many({"name": {"$regex": "^TEST_"}})
    db.events.delete_many({"event_id": {"$in": STATE.get("events", [])}})
    db.notifications.delete_many({"created_at": {"$gte": since}, "type": {"$in": ["directory", "event"]}})
    if STATE.get("share_conv"):
        db.messages.delete_many({"conversation_id": STATE["share_conv"], "text": {"$regex": "TEST_"}})
    db.users.delete_one({"user_id": "user_TEST_emp2_32"})
    db.user_sessions.delete_one({"session_token": EMP2_TOKEN})


def body(cat, name, space="participant", **kw):
    return {"space": space, "category": cat, "name": name, "address": "1 Test St Perth WA 6000", **kw}


@pytest.fixture(scope="module")
def acts():
    out = []
    for i in range(7):
        r = requests.post(f"{API}/directory", json=body("Activities", f"TEST_Act {i}", address=f"{i} Beach Rd WA"), headers=ADMIN)
        assert r.status_code == 200, r.text
        assert r.json()["status"] == "approved"
        out.append(r.json()["entry_id"])
    return out


# ---- Suggest Suppliers / Activities
class TestSuggest:
    def test_employee_supplier_pending_and_admin_notified(self):
        since = datetime.now(timezone.utc).isoformat()
        r = requests.post(f"{API}/directory", json=body("Suppliers", "TEST_Sugg Supplier"), headers=EMP)
        assert r.status_code == 200, r.text
        assert r.json()["status"] == "pending"
        STATE["sup"] = r.json()["entry_id"]
        n = db.notifications.find_one({"user_id": "user_testadmin01", "type": "directory", "created_at": {"$gte": since}})
        assert n and "supplier" in n["title"].lower()

    def test_employee_activity_pending(self):
        r = requests.post(f"{API}/directory", json=body("Activities", "TEST_Sugg Activity"), headers=EMP)
        assert r.status_code == 200 and r.json()["status"] == "pending"
        STATE["act"] = r.json()["entry_id"]

    def test_employee_therapist_supplier_pending(self):
        r = requests.post(f"{API}/directory", json=body("Suppliers", "TEST_Sugg TSupplier", space="therapist"), headers=EMP)
        assert r.status_code == 200 and r.json()["status"] == "pending"

    def test_templates_and_resources_forbidden(self):
        r = requests.post(f"{API}/directory", json=body("Templates", "TEST_Tpl", space="therapist"), headers=EMP)
        assert r.status_code == 403
        r = requests.post(f"{API}/directory", json=body("Resources", "TEST_Res"), headers=EMP)
        assert r.status_code == 403

    def test_other_employee_cannot_see_pending(self):
        r = requests.get(f"{API}/directory", params={"space": "participant", "category": "Suppliers"}, headers=EMP2)
        assert STATE["sup"] not in [d["entry_id"] for d in r.json()]
        assert requests.get(f"{API}/directory/{STATE['sup']}", headers=EMP2).status_code == 404
        mine = requests.get(f"{API}/directory", params={"space": "participant", "category": "Suppliers"}, headers=EMP).json()
        assert mine[0]["entry_id"] == STATE["sup"] and mine[0]["status"] == "pending"

    def test_pending_rate_and_share_blocked(self):
        r = requests.post(f"{API}/directory/{STATE['sup']}/rate", json={"stars": 4}, headers=EMP)
        assert r.status_code == 400 and "approved" in r.json()["detail"]
        r = requests.post(f"{API}/directory/{STATE['sup']}/share", headers=EMP)
        assert r.status_code == 400

    def test_pending_activity_not_voteable(self, acts):
        r = requests.post(f"{API}/events/activity-vote", json={"entry_ids": [acts[0], STATE["act"]]}, headers=EMP)
        assert r.status_code == 404

    def test_admin_approve_then_rate(self):
        assert requests.post(f"{API}/directory/{STATE['sup']}/approve", headers=EMP).status_code == 403
        r = requests.post(f"{API}/directory/{STATE['sup']}/approve", headers=ADMIN)
        assert r.status_code == 200 and r.json()["status"] == "approved"
        n = db.notifications.find_one({"user_id": "user_testemp001", "title": "Suggestion approved"}, sort=[("created_at", -1)])
        assert n
        assert requests.get(f"{API}/directory/{STATE['sup']}", headers=EMP2).status_code == 200
        r = requests.post(f"{API}/directory/{STATE['sup']}/rate", json={"stars": 5, "comment": "TEST_great"}, headers=EMP2)
        assert r.status_code == 200 and r.json()["avg_rating"] == 5
        assert requests.post(f"{API}/directory/{STATE['sup']}/approve", headers=ADMIN).status_code == 404

    def test_admin_reject_pending(self):
        r = requests.delete(f"{API}/directory/{STATE['act']}", headers=ADMIN)
        assert r.status_code == 200
        assert requests.get(f"{API}/directory/{STATE['act']}", headers=ADMIN).status_code == 404

    def test_single_share_to_channel(self):
        # Exactly one share; message deleted at teardown
        r = requests.post(f"{API}/directory/{STATE['sup']}/share", headers=EMP)
        assert r.status_code == 200, r.text
        STATE["share_conv"] = r.json()["conversation_id"]
        m = db.messages.find_one({"conversation_id": STATE["share_conv"], "text": {"$regex": "TEST_Sugg Supplier"}})
        assert m and m["text"].startswith("🛒 Supplier: TEST_Sugg Supplier")


# ---- Activity event poll
class TestActivityVote:
    def test_validation(self, acts):
        u = f"{API}/events/activity-vote"
        assert requests.post(u, json={"entry_ids": acts[:1]}, headers=EMP).status_code == 400
        assert requests.post(u, json={"entry_ids": acts[:7]}, headers=EMP).status_code == 400
        assert requests.post(u, json={"entry_ids": [acts[0], acts[0]]}, headers=EMP).status_code == 400
        assert requests.post(u, json={"entry_ids": [acts[0], STATE["sup"]]}, headers=EMP).status_code == 404
        assert requests.post(u, json={"entry_ids": [acts[0], "dir_nope"]}, headers=EMP).status_code == 404
        past = (datetime.now(timezone.utc) - timedelta(days=3)).date().isoformat()
        assert requests.post(u, json={"entry_ids": acts[:2], "date": past}, headers=EMP).status_code == 400
        assert requests.post(u, json={"entry_ids": acts[:2], "date": "31-12-2030"}, headers=EMP).status_code == 400
        assert requests.post(u, json={"entry_ids": acts[:2]}).status_code == 401

    def test_create_default(self, acts):
        since = datetime.now(timezone.utc).isoformat()
        r = requests.post(f"{API}/events/activity-vote", json={"entry_ids": acts[:3]}, headers=EMP)
        assert r.status_code == 200, r.text
        ev = r.json()
        STATE.setdefault("events", []).append(ev["event_id"])
        STATE["ev"] = ev
        assert ev["title"] == "Next team activity" and ev["date_tbd"] is True
        exp = datetime.now(timezone.utc).date() + timedelta(days=14)
        assert abs((datetime.fromisoformat(ev["date"]).date() - exp).days) <= 1
        assert ev["poll"]["kind"] == "activity" and not ev["poll"]["closed"]
        assert [o["label"] for o in ev["poll"]["options"]] == ["TEST_Act 0", "TEST_Act 1", "TEST_Act 2"]
        assert ev["poll"]["options"][1]["location"] == "1 Beach Rd WA"
        assert "_id" not in ev
        assert db.notifications.count_documents({"type": "event", "created_at": {"$gte": since}, "user_id": "user_testadmin01"}) >= 1

    def test_create_custom_title_date_and_get(self, acts):
        d = (datetime.now(timezone.utc) + timedelta(days=30)).date().isoformat()
        r = requests.post(f"{API}/events/activity-vote", json={"entry_ids": acts[4:6], "title": "TEST_Vote", "date": d}, headers=ADMIN)
        assert r.status_code == 200
        ev = r.json()
        STATE["events"].append(ev["event_id"])
        g = requests.get(f"{API}/events/{ev['event_id']}", headers=EMP2).json()
        assert g["title"] == "TEST_Vote" and g["date"] == d and g["date_tbd"] is True
        assert ev["event_id"] in [e["event_id"] for e in requests.get(f"{API}/events", headers=EMP).json()]

    def test_vote_and_lock_sets_title_location(self):
        ev = STATE["ev"]
        opt = ev["poll"]["options"][1]
        r = requests.post(f"{API}/events/{ev['event_id']}/poll/{opt['option_id']}/vote", headers=EMP2)
        assert r.status_code == 200 and [o for o in r.json()["poll"]["options"] if o["option_id"] == opt["option_id"]][0]["votes"] == 1
        assert requests.post(f"{API}/events/{ev['event_id']}/poll/{opt['option_id']}/lock", headers=EMP2).status_code == 403
        r = requests.post(f"{API}/events/{ev['event_id']}/poll/{opt['option_id']}/lock", headers=EMP)
        assert r.status_code == 200, r.text
        g = requests.get(f"{API}/events/{ev['event_id']}", headers=EMP).json()
        assert g["title"] == "TEST_Act 1" and g["location"] == "1 Beach Rd WA" and g["poll"]["closed"] is True
        assert g["date_tbd"] is True  # date still pencilled in
        assert requests.post(f"{API}/events/{ev['event_id']}/poll/{opt['option_id']}/lock", headers=EMP).status_code == 400

    def test_edit_date_clears_tbd(self):
        ev = STATE["ev"]
        d = (datetime.now(timezone.utc) + timedelta(days=20)).date().isoformat()
        r = requests.patch(f"{API}/events/{ev['event_id']}", json={"date": d}, headers=EMP)
        assert r.status_code == 200, r.text
        g = requests.get(f"{API}/events/{ev['event_id']}", headers=EMP).json()
        assert g["date"] == d and g["date_tbd"] is False

    def test_edit_same_date_clears_tbd(self):
        eid = STATE["events"][1]
        g = requests.get(f"{API}/events/{eid}", headers=ADMIN).json()
        r = requests.patch(f"{API}/events/{eid}", json={"date": g["date"]}, headers=ADMIN)
        assert r.status_code == 200
        assert requests.get(f"{API}/events/{eid}", headers=ADMIN).json()["date_tbd"] is False


# ---- Referral map without Google key
class TestReferralMap:
    def test_map_requires_token(self):
        assert requests.get(f"{API}/referral-map").status_code == 401
        assert requests.get(f"{API}/referral-map", params={"token": "bad"}).status_code == 401

    def test_map_not_set_up_message(self):
        r = requests.get(f"{API}/referral-map", params={"token": "test_session_employee", "postcode": "6027"})
        assert r.status_code == 200 and "text/html" in r.headers["content-type"]
        assert "The map isn't set up yet. An admin needs to add the Google Maps key." in r.text.replace("&#x27;", "'")
        r = requests.get(f"{API}/referral-map", headers=EMP)
        assert r.status_code == 200

    def test_summary(self):
        assert requests.get(f"{API}/referral-map/summary").status_code == 401
        r = requests.get(f"{API}/referral-map/summary", headers=EMP)
        assert r.status_code == 200
        d = r.json()
        assert d["configured"] is False and isinstance(d["total"], int)
