# Iteration 46: bulk staff import, starter checklist nudge, Teams celebrations, resend welcome
import asyncio
import csv
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
    return f"test_imp_{TAG}_{n}@example.com"


def xlsx_bytes(rows):
    import openpyxl
    wb = openpyxl.Workbook()
    ws = wb.active
    for r in rows:
        ws.append(r)
    b = io.BytesIO()
    wb.save(b)
    return b.getvalue()


def csv_bytes(rows):
    s = io.StringIO()
    csv.writer(s).writerows(rows)
    return s.getvalue().encode()


def upload(name, data, headers=ADMIN):
    return requests.post(f"{API}/users/import", headers=headers, files={"file": (name, data)}, timeout=60)


def db_user(email):
    return mdb.users.find_one({"email": email}, {"_id": 0})


@pytest.fixture(scope="module", autouse=True)
def cleanup_module():
    yield
    for u in mdb.users.find({"email": {"$regex": f"^test_imp_{TAG}_"}}, {"user_id": 1}):
        mdb.user_sessions.delete_many({"user_id": u["user_id"]})
        mdb.notifications.delete_many({"user_id": u["user_id"]})
        mdb.checklist_progress.delete_many({"user_id": u["user_id"]})
    mdb.users.delete_many({"email": {"$regex": f"^test_imp_{TAG}_"}})


# ---- Bulk import (xlsx)
class TestImportXlsx:
    def test_xlsx_added_and_skipped(self):
        start = date.today() - timedelta(days=10)
        rows = [["Name", "EMAIL", "User Type", "Job Title", "Start Date", "Birthday"],
                ["TEST Xl Worker", em("x1"), "Support Worker", "Carer", datetime(start.year, start.month, start.day), "15/03/1990"],
                ["TEST Xl Office", em("x2"), "support office", "Coordinator", start.strftime("%d/%m/%Y"), "1985-12-01"],
                ["TEST Xl Admin", em("x3"), "Admin", "", "", ""],
                ["TEST Xl NoType", em("x4"), None, None, None, None],
                ["", em("x5"), "", "", "", ""],
                ["TEST Bad Email", "not-an-email", "", "", "", ""],
                ["TEST Dup Row", em("x1"), "", "", "", ""],
                ["TEST Existing", "emp.test@example.com", "", "", "", ""]]
        r = upload("staff.xlsx", xlsx_bytes(rows))
        assert r.status_code == 200, r.text
        d = r.json()
        added = {a["email"]: a["user_type"] for a in d["added"]}
        assert added == {em("x1"): "support_worker", em("x2"): "support_office", em("x3"): "admin", em("x4"): "support_worker"}
        reasons = {s["row"]: s["reason"] for s in d["skipped"]}
        assert reasons[6] == "Missing name or invalid email" and reasons[7] == "Missing name or invalid email"
        assert reasons[8] == "Already in the app" and reasons[9] == "Already in the app"

        w = db_user(em("x1"))
        assert w["start_date"] == start.isoformat()
        assert w["birthday"] == "03-15"
        assert w["job_title"] == "Carer"
        assert w["must_change_password"] is True and w.get("password_hash")
        assert w["role"] == "employee" and w["staff_group"] == "support_worker"
        o = db_user(em("x2"))
        assert o["start_date"] == start.isoformat() and o["birthday"] == "12-01"
        assert not o.get("password_hash") and not o.get("must_change_password")
        a = db_user(em("x3"))
        assert a["role"] == "admin" and a["executive"] is False

    def test_probation_preserves_start_date(self):
        import time
        time.sleep(2)  # spawned send_starter_welcome
        w = db_user(em("x1"))
        start = date.fromisoformat(w["start_date"])
        assert start == date.today() - timedelta(days=10), "start_date overwritten by probation default"
        from routes.profile import add_months
        assert w.get("probation_end") == add_months(start, 12).isoformat()
        assert mdb.notifications.find_one({"user_id": w["user_id"], "title": "Welcome to No Limitts!"})
        nt = db_user(em("x4"))  # no start date -> today
        assert nt.get("probation_end"), "no-start-date worker got no probation"

    def test_imported_worker_cannot_login_without_pw_returned(self):
        # temp pw isn't returned by import (email only); added items must not leak it
        r = upload("s.csv", csv_bytes([["Name", "Email"], ["TEST Csv Leak", em("leak")]]))
        assert r.status_code == 200
        assert "temporary_password" not in str(r.json())


# ---- Bulk import (csv) + validations
class TestImportCsv:
    def test_csv_with_bom_and_exec_rules(self):
        data = "\ufeff".encode() + csv_bytes([["full name", "Email Address", "Role", "Position", "Started", "DOB"],
                                             ["TEST Csv Exec", em("c1"), "Executive", "CEO", "2024-02-29", "29/02/1992"],
                                             ["TEST Csv Worker", em("c2"), "worker", "Carer", "01/07/2025", ""]])
        r = upload("staff.csv", data, headers=ADMIN2)  # non-exec admin
        assert r.status_code == 200, r.text
        d = r.json()
        assert [a["email"] for a in d["added"]] == [em("c2")]
        assert d["skipped"][0]["reason"] == "Only Executives can add Executives"
        assert db_user(em("c2"))["start_date"] == "2025-07-01"
        r2 = upload("staff.csv", data, headers=ADMIN)  # exec admin
        d2 = r2.json()
        assert [a["email"] for a in d2["added"]] == [em("c1")]
        u = db_user(em("c1"))
        assert u["user_type"] == "executive" and u["executive"] is True and u["birthday"] == "02-29"

    def test_missing_columns_400(self):
        r = upload("x.csv", csv_bytes([["Name", "Phone"], ["A", "1"]]))
        assert r.status_code == 400 and "Name" in r.json()["detail"]

    def test_header_only_400(self):
        assert upload("x.csv", csv_bytes([["Name", "Email"]])).status_code == 400

    def test_bad_file_400(self):
        r = upload("x.xlsx", b"this is not a workbook")
        assert r.status_code == 400 and "Excel" in r.json()["detail"]

    def test_non_admin_403(self):
        assert upload("x.csv", csv_bytes([["Name", "Email"], ["A", em("na")]]), headers=EMP).status_code == 403
        assert db_user(em("na")) is None

    def test_too_many_rows_400(self):
        rows = [["Name", "Email"]] + [[f"N{i}", em(f"many{i}")] for i in range(501)]
        r = upload("x.csv", csv_bytes(rows))
        assert r.status_code == 400 and "500" in r.json()["detail"]

    def test_too_large_413(self):
        r = upload("x.csv", b"Name,Email\n" + b"a" * (5 * 1024 * 1024 + 10))
        assert r.status_code == 413


# ---- Resend welcome
class TestResendWelcome:
    def test_support_worker_new_pw(self):
        r = requests.post(f"{API}/users", headers=ADMIN, json={"name": "TEST Resend W", "email": em("rw"), "user_type": "support_worker"}, timeout=30)
        assert r.status_code == 200, r.text
        uid, old = r.json()["user"]["user_id"], r.json()["temporary_password"]
        s = requests.post(f"{API}/auth/login", json={"email": em("rw"), "password": old}, timeout=30)
        assert s.status_code == 200
        tok = s.json()["session_token"]
        rr = requests.post(f"{API}/users/{uid}/resend-welcome", headers=ADMIN, timeout=30)
        assert rr.status_code == 200, rr.text
        d = rr.json()
        assert d["emailed"] is False and d["temporary_password"] and d["temporary_password"] != old
        assert requests.get(f"{API}/auth/me", headers={"Authorization": f"Bearer {tok}"}, timeout=30).status_code == 401
        assert requests.post(f"{API}/auth/login", json={"email": em("rw"), "password": old}, timeout=30).status_code == 401
        n = requests.post(f"{API}/auth/login", json={"email": em("rw"), "password": d["temporary_password"]}, timeout=30)
        assert n.status_code == 200 and n.json()["user"]["must_change_password"] is True

    def test_office_no_pw(self):
        r = requests.post(f"{API}/users", headers=ADMIN, json={"name": "TEST Resend O", "email": em("ro"), "user_type": "support_office"}, timeout=30)
        uid = r.json()["user"]["user_id"]
        rr = requests.post(f"{API}/users/{uid}/resend-welcome", headers=ADMIN, timeout=30)
        assert rr.status_code == 200 and rr.json() == {"temporary_password": None, "emailed": False}

    def test_errors(self):
        assert requests.post(f"{API}/users/user_nope/resend-welcome", headers=ADMIN, timeout=30).status_code == 404
        assert requests.post(f"{API}/users/user_testemp001/resend-welcome", headers=EMP, timeout=30).status_code == 403
        # hidden user not visible to non-hidden admin? admin2 is hidden too, so expect allowed only for hidden callers


# ---- Teams announcements toggle 'celebrations'
class TestAnnouncementsToggle:
    def test_toggle_persist(self):
        orig = mdb.integrations.find_one({"key": "teams_announcements"}, {"_id": 0})
        try:
            r = requests.put(f"{API}/integrations/teams-announcements", headers=ADMIN, timeout=30,
                             json={"webhook_url": "https://prod-00.australiasoutheast.logic.azure.com/workflows/test", "celebrations": False})
            assert r.status_code == 200, r.text
            assert r.json()["celebrations"] is False and r.json()["linked"] is True
            g = requests.get(f"{API}/integrations/teams-announcements", headers=ADMIN, timeout=30).json()
            assert g["celebrations"] is False and g["updates"] is True
            r = requests.put(f"{API}/integrations/teams-announcements", headers=ADMIN, timeout=30, json={"celebrations": True})
            assert r.status_code == 200 and r.json()["celebrations"] is True
            assert requests.get(f"{API}/integrations/teams-announcements", headers=EMP, timeout=30).status_code == 403
        finally:
            mdb.integrations.delete_one({"key": "teams_announcements"})
            if orig:
                mdb.integrations.insert_one(orig)


# ---- Unit: send_starter_nudge and post_celebrations_to_teams (fresh motor client per loop)
def run_with_db(monkeypatch, coro_fn):
    from motor.motor_asyncio import AsyncIOMotorClient
    import core
    import routes.compliance as rc
    import routes.celebrations as rcel
    import routes.teams as rt

    async def go():
        db = AsyncIOMotorClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]
        for m in (core, rc, rcel, rt):
            monkeypatch.setattr(m, "db", db, raising=False)
        return await coro_fn()
    return asyncio.run(go())


class TestStarterNudge:
    def test_nudge_once(self, monkeypatch):
        import routes.compliance as rc
        sent = []

        async def fake_send(**kw):
            sent.append(kw)
        monkeypatch.setattr(rc, "send_email", fake_send)
        monkeypatch.setattr("core.send_push", lambda *a, **k: None, raising=False)
        uid = f"user_testnudge{TAG}"
        six = (date.today() - timedelta(days=6)).isoformat()
        mdb.users.insert_one({"user_id": uid, "email": em("nudge"), "name": "TEST Nudge Person", "user_type": "support_worker",
                              "role": "employee", "staff_group": "support_worker", "executive": False,
                              "start_date": six, "created_at": (datetime.now(timezone.utc) - timedelta(days=6)).isoformat()})

        async def go():
            u = await rc.db.users.find_one({"user_id": uid}, {"_id": 0})
            assert rc.is_new_starter(u)
            first = await rc.send_starter_nudge(u)
            second = await rc.send_starter_nudge(u)
            return first, second
        first, second = run_with_db(monkeypatch, go)
        assert first is True and second is False
        u = db_user(em("nudge"))
        assert u.get("starter_reminder_sent_at")
        n = list(mdb.notifications.find({"user_id": uid, "title": "A few steps left on your checklist"}))
        assert len(n) == 1 and n[0]["link"] == "/starter-checklist"
        assert sent == []  # @example.com skipped


class TestCelebrationsToTeams:
    def test_post_and_toggle(self, monkeypatch):
        import ms_services as ms
        from core import DIGEST_TZ
        import routes.celebrations as rcel
        posts = []

        async def fake_post(url, text):
            posts.append((url, text))
            return True
        monkeypatch.setattr(ms, "post_to_teams", fake_post)
        today = datetime.now(DIGEST_TZ).date()
        uid = f"user_testcel{TAG}"
        mdb.users.insert_one({"user_id": uid, "email": em("cel"), "name": f"TEST Celeb {TAG}", "user_type": "support_office",
                              "role": "employee", "birthday": today.strftime("%m-%d"), "created_at": datetime.now(timezone.utc).isoformat()})
        orig = mdb.integrations.find_one({"key": "teams_announcements"}, {"_id": 0})
        url = "https://prod-11.australiasoutheast.logic.azure.com/workflows/abc"
        try:
            mdb.integrations.delete_one({"key": "teams_announcements"})
            mdb.integrations.insert_one({"key": "teams_announcements", "webhook": ms.encrypt(url), "updates": True,
                                         "events": True, "celebrations": True})
            run_with_db(monkeypatch, lambda: rcel.post_celebrations_to_teams(today))
            mine = [p for p in posts if f"TEST Celeb {TAG}" in p[1]]
            assert len(mine) == 1 and mine[0][0] == url and "Happy birthday" in mine[0][1]
            posts.clear()
            mdb.integrations.update_one({"key": "teams_announcements"}, {"$set": {"celebrations": False}})
            run_with_db(monkeypatch, lambda: rcel.post_celebrations_to_teams(today))
            assert posts == []
        finally:
            mdb.integrations.delete_one({"key": "teams_announcements"})
            if orig:
                mdb.integrations.insert_one(orig)
            mdb.users.delete_one({"user_id": uid})
