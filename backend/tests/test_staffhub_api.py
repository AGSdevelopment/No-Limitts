"""StaffHub backend regression tests (auth, users, chat, certificates, updates/policies/events/tasks, notifications)."""
import os
import uuid
from datetime import date, timedelta, datetime, timezone

import pytest
import requests
from pymongo import MongoClient
from pymongo.errors import DuplicateKeyError
from dotenv import load_dotenv

load_dotenv("/app/frontend/.env")
load_dotenv("/app/backend/.env")
BASE_URL = (os.environ.get("EXPO_PUBLIC_BACKEND_URL") or os.environ.get("EXPO_BACKEND_URL")).rstrip("/")
API = f"{BASE_URL}/api"
ADMIN = "test_session_admin"
EMP = "test_session_employee"
ADMIN_ID = "user_testadmin01"
EMP_ID = "user_testemp001"
THIRD = "test_session_third_TEST"
THIRD_ID = "user_TEST_third01"


def h(tok):
    return {"Authorization": f"Bearer {tok}"}


@pytest.fixture(scope="session", autouse=True)
def third_user():
    # Seed a 3rd user for DM privacy checks
    db = MongoClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]
    try:
        _seed_third(db)
    except DuplicateKeyError:
        pass  # concurrent xdist worker already seeded
    yield db
    # cleanup
    _cleanup(db)


def _seed_third(db):
    db.users.update_one({"user_id": THIRD_ID}, {"$set": {"user_id": THIRD_ID, "email": "TEST_third@example.com",
                        "name": "TEST Third", "role": "employee", "job_title": "", "created_at": "2026-01-01"}},
                        upsert=True)
    db.user_sessions.update_one({"session_token": THIRD}, {"$set": {"session_token": THIRD, "user_id": THIRD_ID,
                                "expires_at": datetime.now(timezone.utc) + timedelta(days=1)}}, upsert=True)


def _cleanup(db):
    # third user/session intentionally kept (shared across xdist workers); content cleanup only
    db.updates.delete_many({"title": {"$regex": "^TEST_"}})
    db.policies.delete_many({"title": {"$regex": "^TEST_"}})
    db.events.delete_many({"title": {"$regex": "^TEST_"}})
    db.tasks.delete_many({"title": {"$regex": "^TEST_"}})


# --- auth & users
class TestAuthUsers:
    def test_me_admin_employee_and_unauth(self):
        r = requests.get(f"{API}/auth/me", headers=h(ADMIN))
        assert r.status_code == 200 and r.json()["role"] == "admin" and "_id" not in r.json()
        r = requests.get(f"{API}/auth/me", headers=h(EMP))
        assert r.status_code == 200 and r.json()["user_id"] == EMP_ID
        assert requests.get(f"{API}/auth/me").status_code == 401
        assert requests.get(f"{API}/auth/me", headers=h("bogus")).status_code == 401

    def test_dashboard(self):
        r = requests.get(f"{API}/dashboard", headers=h(EMP))
        assert r.status_code == 200
        d = r.json()
        for k in ("cert_alerts", "cert_total", "events", "open_tasks", "open_task_count", "updates",
                  "unread_notifications", "pending_policies"):
            assert k in d

    def test_users_list(self):
        r = requests.get(f"{API}/users", headers=h(EMP))
        assert r.status_code == 200
        ids = [u["user_id"] for u in r.json()]
        assert ADMIN_ID in ids and EMP_ID in ids

    def test_role_change_rules(self):
        assert requests.patch(f"{API}/users/{EMP_ID}/role", json={"role": "admin"}, headers=h(EMP)).status_code == 403
        assert requests.patch(f"{API}/users/{ADMIN_ID}/role", json={"role": "employee"},
                              headers=h(ADMIN)).status_code == 400
        assert requests.patch(f"{API}/users/{THIRD_ID}/role", json={"role": "boss"}, headers=h(ADMIN)).status_code == 400
        assert requests.patch(f"{API}/users/nope/role", json={"role": "admin"}, headers=h(ADMIN)).status_code == 404
        r = requests.patch(f"{API}/users/{THIRD_ID}/role", json={"role": "admin"}, headers=h(ADMIN))
        assert r.status_code == 200 and r.json()["role"] == "admin"
        r = requests.patch(f"{API}/users/{THIRD_ID}/role", json={"role": "employee"}, headers=h(ADMIN))
        assert r.json()["role"] == "employee"


# --- chat
class TestChat:
    def test_seeded_channels(self):
        r = requests.get(f"{API}/conversations", headers=h(EMP))
        assert r.status_code == 200
        names = [c["name"] for c in r.json() if c["type"] == "channel"]
        assert "general" in names and "announcements" in names

    def test_channel_message_and_unread(self):
        convs = requests.get(f"{API}/conversations", headers=h(EMP)).json()
        gen = next(c for c in convs if c["type"] == "channel" and c["name"] == "general")
        cid = gen["conversation_id"]
        requests.post(f"{API}/conversations/{cid}/read", headers=h(EMP))
        r = requests.post(f"{API}/conversations/{cid}/messages", json={"text": "TEST_hello general"}, headers=h(ADMIN))
        assert r.status_code == 200 and r.json()["text"] == "TEST_hello general"
        assert requests.post(f"{API}/conversations/{cid}/messages", json={"text": "  "},
                             headers=h(ADMIN)).status_code == 400
        msgs = requests.get(f"{API}/conversations/{cid}/messages", headers=h(EMP)).json()
        assert any(m["message_id"] == r.json()["message_id"] for m in msgs)
        convs = requests.get(f"{API}/conversations", headers=h(EMP)).json()
        assert next(c for c in convs if c["conversation_id"] == cid)["unread"] >= 1
        assert requests.post(f"{API}/conversations/{cid}/read", headers=h(EMP)).status_code == 200
        convs = requests.get(f"{API}/conversations", headers=h(EMP)).json()
        assert next(c for c in convs if c["conversation_id"] == cid)["unread"] == 0

    def test_dm_flow_and_privacy(self):
        assert requests.post(f"{API}/dms", json={"user_id": EMP_ID}, headers=h(EMP)).status_code == 400
        assert requests.post(f"{API}/dms", json={"user_id": "nope"}, headers=h(EMP)).status_code == 404
        r = requests.post(f"{API}/dms", json={"user_id": EMP_ID}, headers=h(ADMIN))
        assert r.status_code == 200 and r.json()["type"] == "dm"
        cid = r.json()["conversation_id"]
        r2 = requests.post(f"{API}/dms", json={"user_id": ADMIN_ID}, headers=h(EMP))
        assert r2.json()["conversation_id"] == cid  # idempotent
        m = requests.post(f"{API}/conversations/{cid}/messages", json={"text": "TEST_dm hi"}, headers=h(ADMIN))
        assert m.status_code == 200
        notes = requests.get(f"{API}/notifications", headers=h(EMP)).json()
        assert any(n["type"] == "message" and n["body"] == "TEST_dm hi" for n in notes)
        # third user cannot read/post
        assert requests.get(f"{API}/conversations/{cid}/messages", headers=h(THIRD)).status_code == 404
        assert requests.post(f"{API}/conversations/{cid}/messages", json={"text": "x"},
                             headers=h(THIRD)).status_code == 404
        third_convs = requests.get(f"{API}/conversations", headers=h(THIRD)).json()
        assert all(c["conversation_id"] != cid for c in third_convs)

    def test_create_channel_admin_only(self, third_user):
        name = f"test-{uuid.uuid4().hex[:6]}"
        assert requests.post(f"{API}/channels", json={"name": name}, headers=h(EMP)).status_code == 403
        r = requests.post(f"{API}/channels", json={"name": f"#{name.upper()}"}, headers=h(ADMIN))
        assert r.status_code == 200 and r.json()["name"] == name
        assert requests.post(f"{API}/channels", json={"name": name}, headers=h(ADMIN)).status_code == 400
        third_user.conversations.delete_one({"conversation_id": r.json()["conversation_id"]})


# --- certificates
class TestCertificates:
    def _upload(self, tok, title, expiry, **extra):
        data = {"title": title, "expiry_date": expiry, **extra}
        return requests.post(f"{API}/certificates", data=data, headers=h(tok),
                             files={"file": ("cert.pdf", b"%PDF-1.4 TEST certificate", "application/pdf")})

    def test_upload_validation(self):
        assert self._upload(EMP, "  ", "2030-01-01").status_code == 400
        assert self._upload(EMP, "TEST_bad", "01/01/2030").status_code == 400
        r = requests.post(f"{API}/certificates", data={"title": "TEST_nofile", "expiry_date": "2030-01-01"},
                          headers=h(EMP))
        assert r.status_code == 422

    def test_upload_status_sort_download_delete(self):
        valid = self._upload(EMP, "TEST_valid", (date.today() + timedelta(days=200)).isoformat(),
                             issuer="TEST Org", issue_date="2025-01-01")
        assert valid.status_code == 200, valid.text
        v = valid.json()
        assert v["status"] == "valid" and "storage_path" not in v and v["issuer"] == "TEST Org"
        exp = self._upload(EMP, "TEST_expiring", (date.today() + timedelta(days=10)).isoformat())
        assert exp.status_code == 200 and exp.json()["status"] == "expiring" and exp.json()["days_left"] == 10
        # expiring cert -> notification
        notes = requests.get(f"{API}/notifications", headers=h(EMP)).json()
        assert any(n["type"] == "certificate" and "TEST_expiring" in n["body"] for n in notes)
        certs = requests.get(f"{API}/certificates", headers=h(EMP)).json()
        order = {"expired": 0, "expiring": 1, "valid": 2}
        assert [order[c["status"]] for c in certs] == sorted(order[c["status"]] for c in certs)
        # scope=all admin only
        assert requests.get(f"{API}/certificates?scope=all", headers=h(EMP)).status_code == 403
        all_c = requests.get(f"{API}/certificates?scope=all", headers=h(ADMIN)).json()
        assert any(c["cert_id"] == v["cert_id"] for c in all_c)
        # download
        cid = v["cert_id"]
        d = requests.get(f"{API}/files/{cid}?token={EMP}")
        assert d.status_code == 200 and d.content.startswith(b"%PDF")
        assert requests.get(f"{API}/files/{cid}?token={ADMIN}").status_code == 200
        assert requests.get(f"{API}/files/{cid}?token={THIRD}").status_code == 404
        assert requests.get(f"{API}/files/{cid}").status_code == 401
        # delete soft (third cannot)
        assert requests.delete(f"{API}/certificates/{cid}", headers=h(THIRD)).status_code == 404
        for c in (cid, exp.json()["cert_id"]):
            assert requests.delete(f"{API}/certificates/{c}", headers=h(EMP)).status_code == 200
        certs = requests.get(f"{API}/certificates", headers=h(EMP)).json()
        assert all(c["cert_id"] != cid for c in certs)
        assert requests.get(f"{API}/files/{cid}?token={EMP}").status_code == 404


# --- updates / policies / events / tasks
class TestContent:
    def test_updates(self):
        assert requests.post(f"{API}/updates", json={"title": "TEST_u", "body": "b"}, headers=h(EMP)).status_code == 403
        r = requests.post(f"{API}/updates", json={"title": "TEST_update", "body": "body"}, headers=h(ADMIN))
        assert r.status_code == 200
        assert any(u["update_id"] == r.json()["update_id"] for u in requests.get(f"{API}/updates", headers=h(EMP)).json())
        notes = requests.get(f"{API}/notifications", headers=h(EMP)).json()
        assert any(n["type"] == "update" and n["body"] == "TEST_update" for n in notes)

    def test_policies_ack(self):
        assert requests.post(f"{API}/policies", json={"title": "TEST_p", "content": "c"},
                             headers=h(EMP)).status_code == 403
        r = requests.post(f"{API}/policies", json={"title": "TEST_policy", "content": "c", "category": "Procedure"},
                          headers=h(ADMIN))
        assert r.status_code == 200 and r.json()["category"] == "Procedure" and r.json()["acknowledged"] is True  # author auto-acknowledged
        pid = r.json()["policy_id"]
        assert requests.post(f"{API}/policies/{pid}/acknowledge", headers=h(EMP)).status_code == 200
        p = next(x for x in requests.get(f"{API}/policies", headers=h(EMP)).json() if x["policy_id"] == pid)
        assert p["acknowledged"] is True and p["ack_count"] == 2  # author + employee
        assert requests.post(f"{API}/policies/nope/acknowledge", headers=h(EMP)).status_code == 404

    def test_events_rsvp(self):
        d = (date.today() + timedelta(days=5)).isoformat()
        assert requests.post(f"{API}/events", json={"title": "TEST_e", "date": d}, headers=h(EMP)).status_code == 403
        assert requests.post(f"{API}/events", json={"title": "TEST_e", "date": "bad"}, headers=h(ADMIN)).status_code == 400
        r = requests.post(f"{API}/events", json={"title": "TEST_event", "date": d, "time": "10:00"}, headers=h(ADMIN))
        assert r.status_code == 200
        eid = r.json()["event_id"]
        assert requests.post(f"{API}/events/{eid}/rsvp", headers=h(EMP)).json()["going"] is True
        e = next(x for x in requests.get(f"{API}/events", headers=h(EMP)).json() if x["event_id"] == eid)
        assert e["going"] and e["attendee_count"] == 1
        assert requests.post(f"{API}/events/{eid}/rsvp", headers=h(EMP)).json()["going"] is False

    def test_tasks(self):
        assert requests.post(f"{API}/tasks", json={"title": "TEST_t", "assignee_id": EMP_ID},
                             headers=h(EMP)).status_code == 403
        r = requests.post(f"{API}/tasks", json={"title": "TEST_task", "assignee_id": EMP_ID,
                                                "due_date": "2030-01-01"}, headers=h(ADMIN))
        assert r.status_code == 200 and r.json()["status"] == "open"
        tid = r.json()["task_id"]
        assert any(t["task_id"] == tid for t in requests.get(f"{API}/tasks", headers=h(EMP)).json())
        assert requests.patch(f"{API}/tasks/{tid}", json={"status": "done"}, headers=h(THIRD)).status_code == 404
        assert requests.patch(f"{API}/tasks/{tid}", json={"status": "bad"}, headers=h(EMP)).status_code == 400
        p = requests.patch(f"{API}/tasks/{tid}", json={"status": "done"}, headers=h(EMP))
        assert p.status_code == 200 and p.json()["status"] == "done"
        notes = requests.get(f"{API}/notifications", headers=h(EMP)).json()
        assert any(n["type"] == "task" and n["body"] == "TEST_task" for n in notes)


# --- notifications
class TestNotifications:
    def test_read_one_and_all(self):
        notes = requests.get(f"{API}/notifications", headers=h(THIRD)).json()
        assert len(notes) > 0  # from update/policy/event fan-out
        nid = notes[0]["notification_id"]
        requests.post(f"{API}/notifications/{nid}/read", headers=h(THIRD))
        n = next(x for x in requests.get(f"{API}/notifications", headers=h(THIRD)).json() if x["notification_id"] == nid)
        assert n["read"] is True
        assert requests.post(f"{API}/notifications/read-all", headers=h(THIRD)).status_code == 200
        assert all(x["read"] for x in requests.get(f"{API}/notifications", headers=h(THIRD)).json())
        assert requests.get(f"{API}/dashboard", headers=h(THIRD)).json()["unread_notifications"] == 0
