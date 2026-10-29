# Iteration 47: import template, cert month nudge, Teams weekly wrap, staff details edit
import asyncio
import io
import os
import sys
import uuid
from datetime import date, datetime, timedelta, timezone

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
ADMIN2 = {"Authorization": "Bearer test_session_admin2"}
EMP = {"Authorization": "Bearer test_session_employee"}
mdb = MongoClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]
TAG = uuid.uuid4().hex[:6]


def em(n):
    return f"test_i47_{TAG}_{n}@example.com"


@pytest.fixture(scope="module", autouse=True)
def cleanup():
    yield
    ids = [u["user_id"] for u in mdb.users.find({"email": {"$regex": f"^test_i47_{TAG}"}}, {"user_id": 1})]
    ids += [u["user_id"] for u in mdb.users.find({"name": {"$regex": f"TEST.*{TAG}"}}, {"user_id": 1})]
    mdb.users.delete_many({"user_id": {"$in": ids}})
    mdb.user_sessions.delete_many({"user_id": {"$in": ids}})
    mdb.notifications.delete_many({"user_id": {"$in": ids}})
    mdb.probations.delete_many({"user_id": {"$in": ids}}) if "probations" in mdb.list_collection_names() else None
    mdb.updates.delete_many({"title": {"$regex": TAG}})
    mdb.events.delete_many({"title": {"$regex": TAG}})


def run_with_db(monkeypatch, coro_fn):
    from motor.motor_asyncio import AsyncIOMotorClient
    import core
    import routes.compliance as rc
    import routes.certificates as rcert
    import routes.teams as rt

    async def go():
        db = AsyncIOMotorClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]
        for m in (core, rc, rcert, rt):
            monkeypatch.setattr(m, "db", db, raising=False)
        return await coro_fn()
    return asyncio.run(go())


# ---- Import template
class TestTemplate:
    def test_admin_download(self):
        import openpyxl
        r = requests.get(f"{API}/users/import-template", params={"token": "test_session_admin"})
        assert r.status_code == 200
        assert "spreadsheetml" in r.headers["content-type"]
        assert "attachment" in r.headers.get("content-disposition", "")
        wb = openpyxl.load_workbook(io.BytesIO(r.content))
        assert wb.sheetnames == ["Staff", "How to fill this in"]
        rows = list(wb["Staff"].iter_rows(values_only=True))
        assert list(rows[0]) == ["Name", "Email", "User type", "Job title", "Start date", "Birthday"]
        assert len(rows) == 3

    def test_bearer_header_also_works(self):
        r = requests.get(f"{API}/users/import-template", headers=ADMIN)
        assert r.status_code == 200

    def test_employee_and_no_token_403(self):
        assert requests.get(f"{API}/users/import-template", params={"token": "test_session_employee"}).status_code == 403
        assert requests.get(f"{API}/users/import-template").status_code == 403
        assert requests.get(f"{API}/users/import-template", params={"token": "bogus"}).status_code == 403

    def test_template_roundtrip_import(self):
        """The sample file itself (with example rows) should be importable."""
        r = requests.get(f"{API}/users/import-template", headers=ADMIN)
        import openpyxl
        wb = openpyxl.load_workbook(io.BytesIO(r.content))
        ws = wb["Staff"]
        ws.delete_rows(2, 2)
        ws.append([f"TEST Tpl {TAG}", em("tpl"), "Support Worker", "Support Worker", "03/11/2026", "14/03"])
        b = io.BytesIO()
        wb.save(b)
        res = requests.post(f"{API}/users/import", headers=ADMIN,
                            files={"file": ("t.xlsx", b.getvalue(), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")})
        assert res.status_code == 200, res.text
        u = mdb.users.find_one({"email": em("tpl")})
        assert u and u["user_type"] == "support_worker"
        print("imported template row:", {k: u.get(k) for k in ("start_date", "birthday")})


# ---- Cert month nudge
class TestCertMonthNudge:
    def test_nudge_once(self, monkeypatch):
        import routes.compliance as rc
        sent = []

        async def fake_send(**kw):
            sent.append(kw)
        monkeypatch.setattr(rc, "send_email", fake_send)
        orig = mdb.meta.find_one({"key": "cert_requirements"}, {"_id": 0})
        uid, uid2 = f"user_testcm{TAG}", f"user_testcm2{TAG}"
        forty = (date.today() - timedelta(days=40)).isoformat()
        base = {"user_type": "support_worker", "role": "employee", "staff_group": "support_worker", "executive": False,
                "start_date": forty, "created_at": (datetime.now(timezone.utc) - timedelta(days=40)).isoformat()}
        mdb.users.insert_one({"user_id": uid, "email": em("cm"), "name": f"TEST CertNudge {TAG}", **base})
        mdb.users.insert_one({"user_id": uid2, "email": em("cm2"), "name": f"TEST CertNudge2 {TAG}", **base})
        mdb.certificates.insert_one({"certificate_id": f"cert_t{TAG}", "owner_id": uid2, "title": "First Aid HLTAID011",
                                     "expiry_date": (date.today() + timedelta(days=300)).isoformat()})
        try:
            mdb.meta.update_one({"key": "cert_requirements"}, {"$set": {"groups.support_worker": ["First Aid"]}}, upsert=True)

            async def go():
                u = await rc.db.users.find_one({"user_id": uid}, {"_id": 0})
                u2 = await rc.db.users.find_one({"user_id": uid2}, {"_id": 0})
                return (await rc.send_cert_month_nudge(u), await rc.send_cert_month_nudge(u),
                        await rc.send_cert_month_nudge(u2))
            first, second, has_cert = run_with_db(monkeypatch, go)
            assert first is True and second is False
            assert has_cert is False
            assert mdb.users.find_one({"user_id": uid}).get("cert_month_nudge_at")
            assert mdb.users.find_one({"user_id": uid2}).get("cert_month_nudge_at")  # still claimed
            n = list(mdb.notifications.find({"user_id": uid, "title": "Training certificates still needed"}))
            assert len(n) == 1 and "First Aid" in n[0]["body"] and n[0]["link"] == "/upload-certificate"
            assert mdb.notifications.count_documents({"user_id": uid2, "title": "Training certificates still needed"}) == 0
            assert sent == []  # @example.com skipped
        finally:
            mdb.certificates.delete_one({"certificate_id": f"cert_t{TAG}"})
            if orig:
                mdb.meta.replace_one({"key": "cert_requirements"}, orig)
            else:
                mdb.meta.delete_one({"key": "cert_requirements"})


# ---- Weekly wrap
class TestWeeklyWrap:
    def test_build_and_toggle(self, monkeypatch):
        import ms_services as ms
        import routes.teams as rt
        from core import DIGEST_TZ
        today = datetime.now(DIGEST_TZ).date()
        mdb.users.insert_one({"user_id": f"user_testww{TAG}", "email": em("ww"), "name": f"TEST WrapNew {TAG}",
                              "user_type": "support_worker", "role": "employee", "created_at": datetime.now(timezone.utc).isoformat()})
        mdb.users.insert_one({"user_id": f"user_testwwh{TAG}", "email": em("wwh"), "name": f"TEST WrapHidden {TAG}", "hidden": True,
                              "user_type": "support_worker", "role": "employee", "created_at": datetime.now(timezone.utc).isoformat()})
        mdb.updates.insert_one({"update_id": f"upd_t{TAG}", "title": f"TEST Update {TAG}", "created_at": datetime.now(timezone.utc).isoformat()})
        mdb.events.insert_one({"event_id": f"ev_t{TAG}", "title": f"TEST Event {TAG}", "date": (today + timedelta(days=3)).isoformat(), "time": "10:00"})
        mdb.events.insert_one({"event_id": f"ev_tc{TAG}", "title": f"TEST Checkin {TAG}", "date": (today + timedelta(days=3)).isoformat(), "checkin_for": "x"})
        mdb.events.insert_one({"event_id": f"ev_tf{TAG}", "title": f"TEST FarEvent {TAG}", "date": (today + timedelta(days=20)).isoformat()})
        text = run_with_db(monkeypatch, lambda: rt.build_weekly_wrap(today))
        print(text)
        assert "weekly wrap" in text
        assert f"TEST WrapNew {TAG}" in text and f"TEST WrapHidden {TAG}" not in text
        assert f"TEST Update {TAG}" in text
        assert f"TEST Event {TAG}" in text and "10:00" in text
        assert f"TEST Checkin {TAG}" not in text and f"TEST FarEvent {TAG}" not in text

        posts = []

        async def fake_post(url, text):
            posts.append((url, text))
            return True
        monkeypatch.setattr(ms, "post_to_teams", fake_post)
        orig = mdb.integrations.find_one({"key": "teams_announcements"}, {"_id": 0})
        url = "https://prod-11.australiasoutheast.logic.azure.com/workflows/abc"
        try:
            mdb.integrations.delete_one({"key": "teams_announcements"})
            mdb.integrations.insert_one({"key": "teams_announcements", "webhook": ms.encrypt(url), "updates": True,
                                         "events": True, "celebrations": True, "weekly_wrap": True})
            assert run_with_db(monkeypatch, lambda: rt.announce("weekly_wrap", text)) is True
            assert len(posts) == 1 and posts[0][0] == url
            posts.clear()
            mdb.integrations.update_one({"key": "teams_announcements"}, {"$set": {"weekly_wrap": False}})
            assert run_with_db(monkeypatch, lambda: rt.announce("weekly_wrap", text)) is True
            assert posts == []

            async def failing(url, text):
                return False
            monkeypatch.setattr(ms, "post_to_teams", failing)
            mdb.integrations.update_one({"key": "teams_announcements"}, {"$set": {"weekly_wrap": True}})
            assert run_with_db(monkeypatch, lambda: rt.announce("weekly_wrap", text)) is False
        finally:
            mdb.integrations.delete_one({"key": "teams_announcements"})
            if orig:
                mdb.integrations.insert_one(orig)

    def test_toggle_api(self, monkeypatch):
        import ms_services as ms
        orig = mdb.integrations.find_one({"key": "teams_announcements"}, {"_id": 0})
        try:
            mdb.integrations.delete_one({"key": "teams_announcements"})
            r = requests.get(f"{API}/integrations/teams-announcements", headers=ADMIN)
            assert r.status_code == 200 and r.json()["weekly_wrap"] is True and r.json()["linked"] is False
            mdb.integrations.insert_one({"key": "teams_announcements", "webhook": ms.encrypt("https://x.logic.azure.com/w")})
            r = requests.put(f"{API}/integrations/teams-announcements", headers=ADMIN,
                             json={"updates": True, "events": True, "celebrations": True, "weekly_wrap": False})
            assert r.status_code == 200 and r.json()["weekly_wrap"] is False
            assert requests.get(f"{API}/integrations/teams-announcements", headers=ADMIN).json()["weekly_wrap"] is False
            assert mdb.integrations.find_one({"key": "teams_announcements"})["weekly_wrap"] is False
            assert requests.get(f"{API}/integrations/teams-announcements", headers=EMP).status_code == 403
        finally:
            mdb.integrations.delete_one({"key": "teams_announcements"})
            if orig:
                mdb.integrations.insert_one(orig)


# ---- PATCH /api/users/{id}
@pytest.fixture(scope="class")
def worker():
    r = requests.post(f"{API}/users", headers=ADMIN, json={"name": f"TEST Edit {TAG}", "email": em("edit"),
                                                          "user_type": "support_worker", "job_title": "Support Worker"})
    assert r.status_code == 200, r.text
    return r.json()


class TestEditDetails:
    def test_save_and_persist(self, worker):
        uid = worker["user"]["user_id"]
        r = requests.patch(f"{API}/users/{uid}", headers=ADMIN, json={"name": f"  TEST Edited {TAG} ", "email": em("edit2").upper(),
                                                                       "job_title": "Team Leader"})
        assert r.status_code == 200, r.text
        d = r.json()
        assert d["name"] == f"TEST Edited {TAG}" and d["email"] == em("edit2") and d["job_title"] == "Team Leader"
        assert "_id" not in d and "password_hash" not in d
        g = [u for u in requests.get(f"{API}/users", headers=ADMIN).json() if u["user_id"] == uid][0]
        assert g["name"] == f"TEST Edited {TAG}" and g["email"] == em("edit2")

    def test_login_with_new_email(self, worker):
        pw = worker["temporary_password"]
        assert pw
        r = requests.post(f"{API}/auth/login", json={"email": em("edit2"), "password": pw})
        assert r.status_code == 200, r.text
        assert requests.post(f"{API}/auth/login", json={"email": em("edit"), "password": pw}).status_code == 401

    def test_invalid_email_400(self, worker):
        uid = worker["user"]["user_id"]
        for bad in ["nope", "a@b", "a b@c.com", ""]:
            r = requests.patch(f"{API}/users/{uid}", headers=ADMIN, json={"name": "X", "email": bad})
            assert r.status_code == 400, bad
        assert requests.patch(f"{API}/users/{uid}", headers=ADMIN, json={"name": "  ", "email": em("edit2")}).status_code == 400

    def test_duplicate_409(self, worker):
        uid = worker["user"]["user_id"]
        r = requests.patch(f"{API}/users/{uid}", headers=ADMIN, json={"name": "X", "email": "EMP.TEST@example.com"})
        assert r.status_code == 409
        # Keeping own email is fine
        r = requests.patch(f"{API}/users/{uid}", headers=ADMIN, json={"name": f"TEST Edited {TAG}", "email": em("edit2"), "job_title": "Team Leader"})
        assert r.status_code == 200

    def test_non_admin_403_and_404(self, worker):
        uid = worker["user"]["user_id"]
        assert requests.patch(f"{API}/users/{uid}", headers=EMP, json={"name": "X", "email": em("z")}).status_code == 403
        assert requests.patch(f"{API}/users/user_nope_{TAG}", headers=ADMIN, json={"name": "X", "email": em("z")}).status_code == 404
        assert requests.patch(f"{API}/users/{uid}", headers=ADMIN, json={"email": em("z")}).status_code == 422

    def test_executive_rule(self):
        r = requests.post(f"{API}/users", headers=ADMIN, json={"name": f"TEST Exec {TAG}", "email": em("exec"), "user_type": "executive"})
        assert r.status_code == 200, r.text
        eid = r.json()["user"]["user_id"]
        r = requests.patch(f"{API}/users/{eid}", headers=ADMIN2, json={"name": "Hacked", "email": em("exec")})
        print("non-exec admin editing exec:", r.status_code, r.text)
        assert r.status_code in (403, 404)
        r = requests.patch(f"{API}/users/{eid}", headers=ADMIN, json={"name": f"TEST Exec2 {TAG}", "email": em("exec")})
        assert r.status_code == 200 and r.json()["name"] == f"TEST Exec2 {TAG}"
