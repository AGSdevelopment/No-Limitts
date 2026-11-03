# Iteration 53: Reminder time setting, note streaks, missed notes report (caseload)
import asyncio
import os
import sys
from datetime import datetime, timedelta, timezone

import pytest
import requests
from dotenv import load_dotenv
from pymongo import MongoClient

load_dotenv("/app/backend/.env")
load_dotenv("/app/frontend/.env")
BASE_URL = (os.environ.get("EXPO_PUBLIC_BACKEND_URL") or os.environ.get("EXPO_BACKEND_URL")).rstrip("/")
ADMIN = {"Authorization": "Bearer test_session_admin"}
WORKER = {"Authorization": "Bearer test_session_employee"}
WORKER_ID = "user_testemp001"
mdb = MongoClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]
T = 90  # Jotform live, slow first load


@pytest.fixture(scope="module")
def participant():
    """TEST_ participant assigned to the support worker, created 10 days ago."""
    r = requests.post(f"{BASE_URL}/api/participants", headers=ADMIN, json={"name": "TEST_Missed Person"}, timeout=30)
    assert r.status_code == 200, r.text
    p = r.json()
    r = requests.put(f"{BASE_URL}/api/participants/{p['participant_id']}/assign", headers=ADMIN,
                     json={"user_ids": [WORKER_ID]}, timeout=30)
    assert r.status_code == 200 and r.json()["assigned_ids"] == [WORKER_ID], r.text
    past = (datetime.now(timezone.utc) - timedelta(days=10)).isoformat()
    mdb.participants.update_one({"participant_id": p["participant_id"]}, {"$set": {"created_at": past}})
    # a second one created today: should not appear (all days before created_at)
    r2 = requests.post(f"{BASE_URL}/api/participants", headers=ADMIN, json={"name": "TEST_New Today"}, timeout=30).json()
    requests.put(f"{BASE_URL}/api/participants/{r2['participant_id']}/assign", headers=ADMIN, json={"user_ids": [WORKER_ID]}, timeout=30)
    # an unassigned one: should not appear
    r3 = requests.post(f"{BASE_URL}/api/participants", headers=ADMIN, json={"name": "TEST_Unassigned Person"}, timeout=30).json()
    yield p
    for pid in (p["participant_id"], r2["participant_id"], r3["participant_id"]):
        requests.delete(f"{BASE_URL}/api/participants/{pid}", headers=ADMIN, timeout=30)
    mdb.notifications.delete_many({"user_id": WORKER_ID, "title": {"$regex": "TEST_"}})


# ---- Reminder time setting ----
class TestReminderSettings:
    def test_get_default(self):
        r = requests.get(f"{BASE_URL}/api/caseload/settings", headers=ADMIN, timeout=30)
        assert r.status_code == 200, r.text
        d = r.json()
        assert d["reminder_hour"] == 18 and isinstance(d["reminder_hour"], int)
        assert d["timezone"] == "Perth time"

    def test_worker_get_forbidden(self):
        assert requests.get(f"{BASE_URL}/api/caseload/settings", headers=WORKER, timeout=30).status_code == 403

    def test_worker_put_forbidden(self):
        assert requests.put(f"{BASE_URL}/api/caseload/settings", headers=WORKER, json={"hour": 20}, timeout=30).status_code == 403

    def test_invalid_hours(self):
        for h in (25, -1, 24):
            r = requests.put(f"{BASE_URL}/api/caseload/settings", headers=ADMIN, json={"hour": h}, timeout=30)
            assert r.status_code == 400, (h, r.status_code)
        assert requests.put(f"{BASE_URL}/api/caseload/settings", headers=ADMIN, json={"hour": "x"}, timeout=30).status_code == 422

    def test_put_persist_and_restore(self):
        r = requests.put(f"{BASE_URL}/api/caseload/settings", headers=ADMIN, json={"hour": 20}, timeout=30)
        assert r.status_code == 200 and r.json()["reminder_hour"] == 20
        assert requests.get(f"{BASE_URL}/api/caseload/settings", headers=ADMIN, timeout=30).json()["reminder_hour"] == 20
        doc = mdb.meta.find_one({"key": "casenote_reminder_hour"})
        assert doc["hour"] == 20 and doc.get("updated_by")
        r = requests.put(f"{BASE_URL}/api/caseload/settings", headers=ADMIN, json={"hour": 18}, timeout=30)
        assert r.status_code == 200
        assert requests.get(f"{BASE_URL}/api/caseload/settings", headers=ADMIN, timeout=30).json()["reminder_hour"] == 18

    def test_no_auth(self):
        assert requests.get(f"{BASE_URL}/api/caseload/settings", timeout=30).status_code == 401


# ---- Missed notes report ----
class TestMissed:
    def test_worker_forbidden(self):
        assert requests.get(f"{BASE_URL}/api/caseload/missed?days=7", headers=WORKER, timeout=T).status_code == 403

    @pytest.mark.parametrize("days", [7, 14, 30])
    def test_ranges(self, participant, days):
        r = requests.get(f"{BASE_URL}/api/caseload/missed?days={days}", headers=ADMIN, timeout=T)
        assert r.status_code == 200, r.text
        d = r.json()
        assert d["days"] == days
        names = [p["name"] for p in d["participants"]]
        assert "TEST_New Today" not in names and "TEST_Unassigned Person" not in names
        me = next(p for p in d["participants"] if p["participant_id"] == participant["participant_id"])
        perth = datetime.now(timezone(timedelta(hours=8))).date()
        today = perth.isoformat()
        assert today not in me["missing"]
        assert me["missing"] == sorted(me["missing"])
        # created 10 days ago (UTC date) -> at most min(days, 10/11) days
        assert 1 <= len(me["missing"]) <= min(days, 11)
        assert me["assigned"] == 1
        if days == 7:
            assert len(me["missing"]) == 7

    def test_clamped(self, participant):
        assert requests.get(f"{BASE_URL}/api/caseload/missed?days=99", headers=ADMIN, timeout=T).json()["days"] == 31
        assert requests.get(f"{BASE_URL}/api/caseload/missed?days=0", headers=ADMIN, timeout=T).json()["days"] == 1


# ---- Note streak ----
class TestStreak:
    def test_worker_streak(self, participant):
        r = requests.get(f"{BASE_URL}/api/caseload", headers=WORKER, timeout=T)
        assert r.status_code == 200, r.text
        s = r.json()["streak"]
        assert set(s) == {"current", "best", "today_done"}
        assert isinstance(s["current"], int) and isinstance(s["best"], int) and isinstance(s["today_done"], bool)
        assert s["best"] >= s["current"] >= 0

    def test_admin_streak_null(self):
        r = requests.get(f"{BASE_URL}/api/caseload", headers=ADMIN, timeout=T)
        assert r.status_code == 200 and r.json()["streak"] is None


# ---- Weekly missed report notification (direct function call) ----
class TestWeeklyReport:
    def test_weekly_notifies(self, participant):
        sys.path.insert(0, "/app/backend")
        os.chdir("/app/backend")
        from routes import caseload  # noqa

        coords = [u["user_id"] for u in mdb.users.find({"user_type": "support_coordinator", "hidden": {"$ne": True}}, {"user_id": 1})]
        admins = [u["user_id"] for u in mdb.users.find({"role": "admin", "hidden": {"$ne": True}}, {"user_id": 1})]
        expected = coords or admins
        start = datetime.now(timezone.utc).isoformat()
        asyncio.run(caseload.weekly_missed_report())
        got = list(mdb.notifications.find({"link": "/missed-notes", "created_at": {"$gte": start}}, {"_id": 0}))
        try:
            assert got, "no /missed-notes notification created"
            assert {n["user_id"] for n in got} == set(expected)
            assert got[0]["title"].startswith("Missed case notes last week:")
            assert got[0]["type"] == "casenote"
        finally:
            mdb.notifications.delete_many({"link": "/missed-notes", "created_at": {"$gte": start}})
