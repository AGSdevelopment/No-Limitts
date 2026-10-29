# Iteration 45: welcome email, Support Worker first-week checklist, Teams announcements channel
import asyncio
import os
import sys
import uuid
from datetime import date, timedelta

import pytest
import requests
from pymongo import MongoClient
from dotenv import load_dotenv

load_dotenv("/app/frontend/.env")
load_dotenv("/app/backend/.env")
sys.path.insert(0, "/app/backend")
BASE_URL = (os.environ.get("EXPO_PUBLIC_BACKEND_URL") or os.environ.get("EXPO_BACKEND_URL")).rstrip("/")
API = f"{BASE_URL}/api"
ADMIN = {"Authorization": "Bearer test_session_admin"}
EMP = {"Authorization": "Bearer test_session_employee"}
mdb = MongoClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]
STARTER_FORM = "form:form_ec94f72dc6de"  # audience: everyone


def add_user(user_type, domain="example.com", name="TEST Starter Person"):
    email = f"test_{uuid.uuid4().hex[:8]}@{domain}"
    r = requests.post(f"{API}/users", headers=ADMIN, json={"name": name, "email": email, "user_type": user_type}, timeout=30)
    return r, email


@pytest.fixture
def cleanup():
    ids = []
    yield ids
    for uid in ids:
        requests.delete(f"{API}/users/{uid}", headers=ADMIN, timeout=30)
        mdb.users.delete_one({"user_id": uid})
        mdb.notifications.delete_many({"user_id": uid})
        mdb.checklist_progress.delete_many({"user_id": uid})


def session_for(uid):
    tok = f"test_sess_{uuid.uuid4().hex}"
    from datetime import datetime, timezone
    mdb.user_sessions.insert_one({"user_id": uid, "session_token": tok,
                                  "expires_at": datetime.now(timezone.utc) + timedelta(days=1),
                                  "created_at": datetime.now(timezone.utc)})
    return {"Authorization": f"Bearer {tok}"}


# ---- New Support Worker: temp password -> login -> change password -> new starter checklist
class TestSupportWorkerOnboarding:
    def test_full_flow(self, cleanup):
        r, email = add_user("support_worker")
        assert r.status_code == 200, r.text
        d = r.json()
        uid = d["user"]["user_id"]
        cleanup.append(uid)
        pw = d["temporary_password"]
        assert isinstance(pw, str) and len(pw) >= 8
        assert "password_hash" not in d["user"]
        lr = requests.post(f"{API}/auth/login", json={"email": email, "password": pw}, timeout=30)
        assert lr.status_code == 200, lr.text
        assert lr.json()["user"]["must_change_password"] is True
        h = {"Authorization": f"Bearer {lr.json()['session_token']}"}
        cr = requests.post(f"{API}/auth/change-password", headers=h, json={"new_password": "NewWorker#2026x"}, timeout=30)
        assert cr.status_code == 200, cr.text
        dash = requests.get(f"{API}/dashboard", headers=h, timeout=30)
        assert dash.status_code == 200, dash.text
        assert dash.json()["is_new_starter"] is True
        sc = requests.get(f"{API}/starter-checklist", headers=h, timeout=30).json()
        assert sc["is_new_starter"] is True and sc["total"] >= 3
        t = requests.post(f"{API}/starter-checklist/{STARTER_FORM}", headers=h, timeout=30)
        assert t.status_code == 200 and t.json()["done"] is True, t.text
        sc2 = requests.get(f"{API}/starter-checklist", headers=h, timeout=30).json()
        assert sc2["done"] == sc["done"] + 1
        t2 = requests.post(f"{API}/starter-checklist/{STARTER_FORM}", headers=h, timeout=30)
        assert t2.json()["done"] is False
        bad = requests.post(f"{API}/starter-checklist/policies", headers=h, timeout=30)
        assert bad.status_code == 400
        # in-app welcome notification
        import time
        time.sleep(2)
        n = mdb.notifications.find_one({"user_id": uid, "title": "Welcome to No Limitts!"})
        assert n is not None, "no in-app welcome notification"
        u = mdb.users.find_one({"user_id": uid})
        assert u.get("welcome_sent_at") and u.get("start_date"), u


class TestNewStarterRules:
    def test_office_user_not_new_starter(self, cleanup):
        r, _ = add_user("support_office")
        assert r.status_code == 200, r.text
        assert r.json()["temporary_password"] is None
        uid = r.json()["user"]["user_id"]
        cleanup.append(uid)
        h = session_for(uid)
        dash = requests.get(f"{API}/dashboard", headers=h, timeout=30)
        assert dash.status_code == 200, dash.text
        assert dash.json()["is_new_starter"] is False
        t = requests.post(f"{API}/starter-checklist/{STARTER_FORM}", headers=h, timeout=30)
        assert t.status_code == 403
        import time
        time.sleep(1)
        assert mdb.notifications.find_one({"user_id": uid, "title": "Welcome to No Limitts!"}) is None

    def test_old_start_date_support_worker_not_new_starter(self, cleanup):
        r, _ = add_user("support_worker")
        uid = r.json()["user"]["user_id"]
        cleanup.append(uid)
        import time
        time.sleep(1.5)  # let background starter welcome set default start_date first
        old = (date.today() - timedelta(days=45)).isoformat()
        mdb.users.update_one({"user_id": uid}, {"$set": {"start_date": old, "must_change_password": False}})
        h = session_for(uid)
        assert requests.get(f"{API}/dashboard", headers=h, timeout=30).json()["is_new_starter"] is False
        assert requests.post(f"{API}/starter-checklist/{STARTER_FORM}", headers=h, timeout=30).status_code == 403

    def test_is_new_starter_unit(self):
        from routes.compliance import is_new_starter
        today = date.today()
        assert is_new_starter({"user_type": "support_worker", "start_date": today.isoformat()})
        assert is_new_starter({"user_type": "support_worker", "start_date": None, "created_at": today.isoformat() + "T00:00:00"})
        assert not is_new_starter({"user_type": "support_worker", "start_date": (today - timedelta(days=31)).isoformat()})
        assert not is_new_starter({"user_type": "support_office", "start_date": today.isoformat()})
        assert not is_new_starter({"user_type": "support_worker", "start_date": "garbage"})
        assert not is_new_starter(None)


# ---- Welcome email HTML (send_email mocked; real safety checks applied)
class TestWelcomeEmail:
    def _run(self, monkeypatch, user, pw):
        import routes.users as ru
        from email_service import _assert_safe_email, brand_header
        sent = []

        async def fake_send(*, to, subject, html):
            _assert_safe_email(subject, brand_header(html))  # same checks send_email does
            sent.append((to, subject, html))
            return True
        monkeypatch.setattr(ru, "send_email", fake_send)
        asyncio.run(ru.send_welcome(user, pw))
        return sent

    def test_support_worker_email(self, monkeypatch):
        s = self._run(monkeypatch, {"email": "jo@nolimitts.com.au", "name": "Jo <b>Bloggs</b>", "user_type": "support_worker"}, "Abc#12345")
        assert len(s) == 1
        to, subj, html = s[0]
        assert to == "jo@nolimitts.com.au" and "Welcome" in subj
        assert "Abc#12345" in html and "first-week checklist" in html and "Support Workers" in html
        assert "<b>Bloggs</b>" not in html  # escaped name (only first name used)

    def test_office_email(self, monkeypatch):
        s = self._run(monkeypatch, {"email": "sam@nolimitts.com.au", "name": "Sam Lee", "user_type": "support_office"}, None)
        assert len(s) == 1
        html = s[0][2]
        assert "Sign in with Microsoft" in html and "Temporary password" not in html and "Support Office" in html

    def test_example_com_skipped(self, monkeypatch):
        assert self._run(monkeypatch, {"email": "x@example.com", "name": "X", "user_type": "support_worker"}, "pw") == []


# ---- Teams announcements endpoints
class TestTeamsAnnouncementsAPI:
    URL = "https://prod-00.australiasoutheast.logic.azure.com/workflows/abc/triggers/manual/paths/invoke?sig=test"

    @pytest.fixture(autouse=True)
    def _clean(self):
        mdb.integrations.delete_one({"key": "teams_announcements"})
        yield
        requests.delete(f"{API}/integrations/teams-announcements", headers=ADMIN, timeout=30)

    def test_non_admin_forbidden(self):
        for m in ("get", "put", "delete"):
            r = getattr(requests, m)(f"{API}/integrations/teams-announcements", headers=EMP, json={}, timeout=30)
            assert r.status_code == 403, (m, r.status_code)

    def test_status_unlinked(self):
        r = requests.get(f"{API}/integrations/teams-announcements", headers=ADMIN, timeout=30)
        assert r.status_code == 200 and r.json() == {"linked": False, "updates": True, "events": True}

    def test_invalid_url(self):
        for bad in ("https://evil.com/hook", "http://x.logic.azure.com/a", "https://logic.azure.com.evil.com/x"):
            r = requests.put(f"{API}/integrations/teams-announcements", headers=ADMIN, json={"webhook_url": bad}, timeout=30)
            assert r.status_code == 400, bad

    def test_toggle_without_link(self):
        r = requests.put(f"{API}/integrations/teams-announcements", headers=ADMIN, json={"updates": False}, timeout=30)
        assert r.status_code == 400

    def test_link_toggle_delete(self):
        r = requests.put(f"{API}/integrations/teams-announcements", headers=ADMIN, json={"webhook_url": self.URL}, timeout=60)
        assert r.status_code == 200, r.text
        assert r.json()["linked"] is True and r.json()["test_delivered"] in (False, True)
        doc = mdb.integrations.find_one({"key": "teams_announcements"})
        assert doc["webhook"] != self.URL  # stored encrypted
        r2 = requests.put(f"{API}/integrations/teams-announcements", headers=ADMIN, json={"updates": False, "events": True}, timeout=30)
        assert r2.status_code == 200 and r2.json()["updates"] is False and r2.json()["test_delivered"] is None
        g = requests.get(f"{API}/integrations/teams-announcements", headers=ADMIN, timeout=30).json()
        assert g == {"linked": True, "updates": False, "events": True}
        d = requests.delete(f"{API}/integrations/teams-announcements", headers=ADMIN, timeout=30)
        assert d.status_code == 200
        assert requests.get(f"{API}/integrations/teams-announcements", headers=ADMIN, timeout=30).json()["linked"] is False


# ---- announce() wiring (in-process, db + teams post faked)
class FakeColl:
    def __init__(self, doc=None):
        self.doc, self.inserted = doc, []

    async def find_one(self, *a, **k):
        return self.doc

    async def insert_one(self, d):
        self.inserted.append(d)


class FakeDB:
    def __init__(self, ann=None):
        self.integrations, self.updates, self.events = FakeColl(ann), FakeColl(), FakeColl()


class TestAnnounceWiring:
    def _patch_create(self, monkeypatch, mod):
        calls, tasks = [], []

        async def fake_announce(kind, text):
            calls.append((kind, text))

        async def noop(*a, **k):
            return []
        monkeypatch.setattr(mod, "announce", fake_announce)
        monkeypatch.setattr(mod, "spawn", lambda c: tasks.append(c))
        monkeypatch.setattr(mod, "notify", noop)
        monkeypatch.setattr(mod, "all_user_ids", noop)
        monkeypatch.setattr(mod, "db", FakeDB())
        return calls, tasks

    def _drain(self, tasks):
        async def go():
            for t in tasks:
                await t
        asyncio.run(go())

    def test_update_announced_only_for_visible_admin(self, monkeypatch):
        import routes.updates as ru
        calls, tasks = self._patch_create(monkeypatch, ru)
        body = ru.UpdateIn(title="Hello team", body="Big news")
        asyncio.run(ru.create_update(body, {"user_id": "u1", "name": "Real Admin", "role": "admin"}))
        self._drain(tasks)
        assert len(calls) == 1 and calls[0][0] == "updates" and "Hello team" in calls[0][1] and "Big news" in calls[0][1]
        tasks.clear(); calls.clear()
        asyncio.run(ru.create_update(body, {"user_id": "u2", "name": "Hidden", "role": "admin", "hidden": True}))
        self._drain(tasks)
        assert calls == []

    def test_event_announced_only_for_visible_user(self, monkeypatch):
        import routes.events as re_
        calls, tasks = self._patch_create(monkeypatch, re_)
        body = re_.EventIn(title="Team BBQ", date=(date.today() + timedelta(days=3)).isoformat(), location="Park", description="Fun")
        asyncio.run(re_.create_event(body, {"user_id": "u1", "name": "Real Person", "role": "employee"}))
        self._drain(tasks)
        assert len(calls) == 1 and calls[0][0] == "events" and "Team BBQ" in calls[0][1] and "Park" in calls[0][1]
        calls.clear(); tasks.clear()
        asyncio.run(re_.create_event(body, {"user_id": "u2", "name": "Hidden", "role": "employee", "hidden": True}))
        self._drain(tasks)
        assert calls == []

    def test_announce_respects_toggles(self, monkeypatch):
        import routes.teams as rt
        posted = []

        async def fake_post(url, text):
            posted.append((url, text))
            return True
        monkeypatch.setattr(rt.ms, "post_to_teams", fake_post)
        enc = rt.ms.encrypt("https://a.logic.azure.com/x")
        monkeypatch.setattr(rt, "db", FakeDB({"key": "teams_announcements", "webhook": enc, "updates": False, "events": True}))
        asyncio.run(rt.announce("updates", "u"))
        asyncio.run(rt.announce("events", "e"))
        assert posted == [("https://a.logic.azure.com/x", "e")]
        monkeypatch.setattr(rt, "db", FakeDB(None))
        asyncio.run(rt.announce("events", "e2"))
        assert len(posted) == 1

    def test_announce_never_raises(self, monkeypatch):
        import routes.teams as rt

        async def boom(*a):
            raise RuntimeError("down")
        monkeypatch.setattr(rt.ms, "post_to_teams", boom)
        monkeypatch.setattr(rt, "db", FakeDB({"webhook": rt.ms.encrypt("https://a.logic.azure.com/x")}))
        asyncio.run(rt.announce("events", "x"))
