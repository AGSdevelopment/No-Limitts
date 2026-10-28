# Iteration 22: profile PDF export, probation tracker (+reminder loop), starter buddy.
# ONLY touches hidden test users (user_testemp001, user_testadmin01). Run serially: pytest -n 0
import asyncio
import os
import sys
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
import requests
from dotenv import load_dotenv
from pymongo import MongoClient
from zoneinfo import ZoneInfo

sys.path.insert(0, "/app/backend")
load_dotenv("/app/backend/.env")


def _base():
    url = os.environ.get("EXPO_PUBLIC_BACKEND_URL") or os.environ.get("EXPO_BACKEND_URL")
    if not url:
        for line in Path("/app/frontend/.env").read_text().splitlines():
            if line.startswith("EXPO_PUBLIC_BACKEND_URL=") or line.startswith("EXPO_BACKEND_URL="):
                url = line.split("=", 1)[1].strip().strip('"')
                break
    return url.rstrip("/")


BASE_URL = _base()
ADMIN = {"Authorization": "Bearer test_session_admin"}
EMP = {"Authorization": "Bearer test_session_employee"}
EMP_ID = "user_testemp001"
ADMIN_ID = "user_testadmin01"
mdb = MongoClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]
START = datetime.now(timezone.utc).isoformat()
PERTH_TODAY = datetime.now(ZoneInfo("Australia/Perth")).date()
FIELDS = ["start_date", "probation_end", "probation_reminded_for", "buddy_id", "buddy_name", "welcome_sent_at"]


def _reset_users():
    mdb.users.update_many({"user_id": {"$in": [EMP_ID, ADMIN_ID]}}, {"$unset": {f: "" for f in FIELDS}})
    mdb.users.update_one({"user_id": EMP_ID}, {"$set": {"staff_group": None}})


@pytest.fixture(scope="module", autouse=True)
def cleanup():
    _reset_users()
    yield
    mdb.tasks.delete_many({"assignee_id": {"$in": [EMP_ID, ADMIN_ID]}, "created_at": {"$gte": START}})
    mdb.notifications.delete_many({"user_id": {"$in": [EMP_ID, ADMIN_ID]}, "created_at": {"$gte": START}})
    _reset_users()


def _add_months(d, n):
    from routes.profile import add_months
    return add_months(d, n)


# ---- add_months unit
class TestAddMonths:
    def test_add_months_edges(self):
        assert _add_months(date(2025, 11, 10), 12) == date(2026, 11, 10)
        assert _add_months(date(2024, 2, 29), 12) == date(2025, 2, 28)
        assert _add_months(date(2025, 1, 31), 1) == date(2025, 2, 28)
        assert _add_months(date(2024, 1, 31), 1) == date(2024, 2, 29)
        assert _add_months(date(2025, 12, 15), 1) == date(2026, 1, 15)


# ---- PDF + profile JSON
class TestProfilePdf:
    def test_pdf_admin_one_page(self):
        r = requests.get(f"{BASE_URL}/api/staff/{EMP_ID}/profile/pdf", params={"token": "test_session_admin"}, timeout=30)
        assert r.status_code == 200, r.text
        assert r.headers["content-type"].startswith("application/pdf")
        assert "Staff_Profile_Erin_Employee.pdf" in r.headers.get("content-disposition", "")
        import pymupdf
        doc = pymupdf.open(stream=r.content, filetype="pdf")
        assert doc.page_count == 1
        assert "Erin Employee" in doc[0].get_text()

    def test_pdf_bearer_header_works(self):
        r = requests.get(f"{BASE_URL}/api/staff/{EMP_ID}/profile/pdf", headers=ADMIN, timeout=30)
        assert r.status_code == 200 and r.content[:4] == b"%PDF"

    def test_pdf_employee_and_anon_403(self):
        r = requests.get(f"{BASE_URL}/api/staff/{EMP_ID}/profile/pdf", params={"token": "test_session_employee"}, timeout=30)
        assert r.status_code == 403
        r = requests.get(f"{BASE_URL}/api/staff/{EMP_ID}/profile/pdf", timeout=30)
        assert r.status_code == 403

    def test_pdf_unknown_user_404(self):
        r = requests.get(f"{BASE_URL}/api/staff/user_nope_xyz/profile/pdf", params={"token": "test_session_admin"}, timeout=30)
        assert r.status_code == 404

    def test_profile_json_has_new_fields(self):
        r = requests.get(f"{BASE_URL}/api/staff/{EMP_ID}/profile", headers=ADMIN, timeout=30)
        assert r.status_code == 200
        u = r.json()["user"]
        for k in ("start_date", "probation_end", "buddy_id", "buddy_name"):
            assert k in u


# ---- Probation PATCH
class TestProbation:
    url = f"{BASE_URL}/api/staff/{EMP_ID}/probation"

    def test_start_only_defaults_12_months(self):
        r = requests.patch(self.url, json={"start_date": "2025-11-10"}, headers=ADMIN, timeout=30)
        assert r.status_code == 200, r.text
        assert r.json() == {"start_date": "2025-11-10", "probation_end": "2026-11-10"}
        p = requests.get(f"{BASE_URL}/api/staff/{EMP_ID}/profile", headers=ADMIN, timeout=30).json()["user"]
        assert p["start_date"] == "2025-11-10" and p["probation_end"] == "2026-11-10"

    def test_leap_day(self):
        r = requests.patch(self.url, json={"start_date": "2024-02-29"}, headers=ADMIN, timeout=30)
        assert r.status_code == 200 and r.json()["probation_end"] == "2025-02-28"

    def test_explicit_end_overrides(self):
        r = requests.patch(self.url, json={"start_date": "2025-11-10", "probation_end": "2026-05-10"}, headers=ADMIN, timeout=30)
        assert r.status_code == 200 and r.json()["probation_end"] == "2026-05-10"
        assert mdb.users.find_one({"user_id": EMP_ID})["probation_end"] == "2026-05-10"

    def test_errors(self):
        assert requests.patch(self.url, json={"start_date": "10-11-2025"}, headers=ADMIN, timeout=30).status_code == 400
        assert requests.patch(self.url, json={"start_date": "2025-11-10", "probation_end": "2025-11-01"},
                              headers=ADMIN, timeout=30).status_code == 400
        assert requests.patch(self.url, json={}, headers=ADMIN, timeout=30).status_code == 400
        assert requests.patch(f"{BASE_URL}/api/staff/user_nope_xyz/probation", json={"start_date": "2025-11-10"},
                              headers=ADMIN, timeout=30).status_code == 404
        assert requests.patch(self.url, json={"start_date": "2025-11-10"}, headers=EMP, timeout=30).status_code == 403

    def test_end_only_before_existing_start(self):
        # existing start 2025-11-10; end-only update earlier than start - is it rejected?
        requests.patch(self.url, json={"start_date": "2025-11-10"}, headers=ADMIN, timeout=30)
        r = requests.patch(self.url, json={"probation_end": "2025-01-01"}, headers=ADMIN, timeout=30)
        print(f"END-ONLY BEFORE EXISTING START -> {r.status_code} {r.text}")
        assert r.status_code == 400, "end-only update earlier than the stored start_date was accepted"


# ---- New starter group defaults
class TestStarterGroupDefault:
    def test_group_sets_probation_then_keeps_existing(self):
        _reset_users()
        r = requests.patch(f"{BASE_URL}/api/users/{EMP_ID}/group", json={"staff_group": "new_starter_employee"},
                           headers=ADMIN, timeout=30)
        assert r.status_code == 200
        u = None
        for _ in range(10):
            time.sleep(0.5)
            u = mdb.users.find_one({"user_id": EMP_ID})
            if u.get("probation_end"):
                break
        assert u["start_date"] == PERTH_TODAY.isoformat()
        assert u["probation_end"] == _add_months(PERTH_TODAY, 12).isoformat()
        # existing values are kept
        mdb.users.update_one({"user_id": EMP_ID}, {"$set": {"start_date": "2025-01-01", "probation_end": "2026-01-01"}})
        requests.patch(f"{BASE_URL}/api/users/{EMP_ID}/group", json={"staff_group": None}, headers=ADMIN, timeout=30)
        requests.patch(f"{BASE_URL}/api/users/{EMP_ID}/group", json={"staff_group": "new_starter_contractor"},
                       headers=ADMIN, timeout=30)
        time.sleep(2)
        u = mdb.users.find_one({"user_id": EMP_ID})
        assert u["start_date"] == "2025-01-01" and u["probation_end"] == "2026-01-01"
        requests.patch(f"{BASE_URL}/api/users/{EMP_ID}/group", json={"staff_group": None}, headers=ADMIN, timeout=30)


# ---- Reminder loop (in-process, notify/send_email mocked, one iteration)
class TestReminderLoop:
    def test_reminder_once_hidden_only(self):
        # guard: never claim reminders on real staff
        cutoff = (PERTH_TODAY + timedelta(days=14)).isoformat()
        real = mdb.users.count_documents({"hidden": {"$ne": True}, "probation_end": {"$gte": PERTH_TODAY.isoformat(), "$lte": cutoff}})
        if real:
            pytest.skip("Real staff have probations in the window; not running the loop in-process")
        end = (PERTH_TODAY + timedelta(days=10)).isoformat()
        far = (PERTH_TODAY + timedelta(days=30)).isoformat()
        mdb.users.update_one({"user_id": EMP_ID}, {"$set": {"probation_end": end}, "$unset": {"probation_reminded_for": ""}})
        mdb.users.update_one({"user_id": ADMIN_ID}, {"$set": {"probation_end": far}, "$unset": {"probation_reminded_for": ""}})
        hidden_admins = {u["user_id"] for u in mdb.users.find({"role": "admin", "hidden": True})}

        class Stop(Exception):
            pass

        async def run():
            import routes.profile as prof
            calls = []
            for _ in range(2):
                n, e = AsyncMock(), AsyncMock()
                with patch.object(prof, "notify", n), patch.object(prof, "send_email", e), \
                        patch.object(prof.asyncio, "sleep", AsyncMock(side_effect=Stop)):
                    try:
                        await prof.probation_reminder_loop()
                    except Stop:
                        pass
                calls.append((n, e))
            return calls

        calls = asyncio.run(run())
        (n1, e1), (n2, e2) = calls
        assert n1.await_count == 1, n1.await_args_list
        ids, ntype, title, body, link = n1.await_args.args
        assert set(ids) == hidden_admins and ntype == "starter" and title == "Probation ending soon"
        assert "Erin Employee" in body and link == f"/staff/{EMP_ID}"
        e1.assert_not_awaited()
        assert n2.await_count == 0 and e2.await_count == 0  # claimed once
        assert mdb.users.find_one({"user_id": EMP_ID})["probation_reminded_for"] == end
        assert not mdb.users.find_one({"user_id": ADMIN_ID}).get("probation_reminded_for")  # outside window
        mdb.users.update_many({"user_id": {"$in": [EMP_ID, ADMIN_ID]}},
                              {"$unset": {"probation_end": "", "probation_reminded_for": ""}})

    def test_changing_end_resets_claim(self):
        mdb.users.update_one({"user_id": EMP_ID}, {"$set": {"probation_end": "2026-03-01", "probation_reminded_for": "2026-03-01"}})
        r = requests.patch(f"{BASE_URL}/api/staff/{EMP_ID}/probation", json={"probation_end": "2026-04-01"}, headers=ADMIN, timeout=30)
        assert r.status_code == 200
        assert mdb.users.find_one({"user_id": EMP_ID}).get("probation_reminded_for") is None


# ---- Buddy
class TestBuddy:
    url = f"{BASE_URL}/api/staff/{EMP_ID}/buddy"

    def test_assign_creates_three_tasks(self):
        r = requests.put(self.url, json={"buddy_id": ADMIN_ID}, headers=ADMIN, timeout=30)
        assert r.status_code == 200, r.text
        assert r.json() == {"buddy_id": ADMIN_ID, "buddy_name": "Alex Admin", "tasks_created": 3}
        tasks = list(mdb.tasks.find({"assignee_id": ADMIN_ID, "created_at": {"$gte": START}}, {"_id": 0}))
        got = {t["title"]: t["due_date"] for t in tasks}
        exp = {"Send Erin a welcome message": 1, "Coffee catch-up with Erin": 7, "30-day check-in with Erin": 30}
        for title, days in exp.items():
            assert got.get(title) == (PERTH_TODAY + timedelta(days=days)).isoformat(), got
        notes = {n["user_id"]: n["title"] for n in mdb.notifications.find({"created_at": {"$gte": START},
                                                                          "type": "starter"})}
        assert notes.get(ADMIN_ID) == "You're a new starter buddy!"
        assert notes.get(EMP_ID) == "Meet your buddy"
        p = requests.get(f"{BASE_URL}/api/staff/{EMP_ID}/profile", headers=ADMIN, timeout=30).json()["user"]
        assert p["buddy_id"] == ADMIN_ID and p["buddy_name"] == "Alex Admin"

    def test_same_buddy_no_new_tasks(self):
        before = mdb.tasks.count_documents({"assignee_id": ADMIN_ID, "created_at": {"$gte": START}})
        r = requests.put(self.url, json={"buddy_id": ADMIN_ID}, headers=ADMIN, timeout=30)
        assert r.status_code == 200 and r.json()["tasks_created"] == 0
        assert mdb.tasks.count_documents({"assignee_id": ADMIN_ID, "created_at": {"$gte": START}}) == before

    def test_errors(self):
        assert requests.put(self.url, json={"buddy_id": EMP_ID}, headers=ADMIN, timeout=30).status_code == 400
        assert requests.put(self.url, json={"buddy_id": "user_nope_xyz"}, headers=ADMIN, timeout=30).status_code == 404
        assert requests.put(f"{BASE_URL}/api/staff/user_nope_xyz/buddy", json={"buddy_id": ADMIN_ID},
                            headers=ADMIN, timeout=30).status_code == 404
        assert requests.put(self.url, json={"buddy_id": ADMIN_ID}, headers=EMP, timeout=30).status_code == 403

    def test_remove_buddy(self):
        r = requests.put(self.url, json={"buddy_id": None}, headers=ADMIN, timeout=30)
        assert r.status_code == 200 and r.json() == {"buddy_id": None, "buddy_name": None, "tasks_created": 0}
        u = mdb.users.find_one({"user_id": EMP_ID})
        assert u.get("buddy_id") is None and u.get("buddy_name") is None
