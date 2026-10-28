# Iteration 21: staff profile, check-in follow-up tasks, certificate reminder history, starter welcome.
# NEVER calls /compliance/remind-certificates without preview=true (would email real staff).
# Run serially: pytest -n 0
import asyncio
import os
import sys
import time
import uuid
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pytest
import requests
from dotenv import load_dotenv
from pymongo import MongoClient

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
TOMORROW = (date.today() + timedelta(days=1)).isoformat()


@pytest.fixture(scope="module", autouse=True)
def cleanup():
    yield
    mdb.users.update_one({"user_id": EMP_ID}, {"$set": {"hidden": True, "staff_group": None},
                                              "$unset": {"welcome_sent_at": "", "starter_completed_at": ""}})
    mdb.events.delete_many({"checkin_for": EMP_ID})
    mdb.tasks.delete_many({"title": {"$regex": "^Follow up: check-in with"}, "created_at": {"$gte": START}})
    mdb.notifications.delete_many({"user_id": {"$in": [EMP_ID, ADMIN_ID]}, "created_at": {"$gte": START}})
    mdb.cert_reminder_log.delete_many({"by": {"$regex": "^TEST_"}})


def _book():
    r = requests.post(f"{BASE_URL}/api/starter-checklist/user/{EMP_ID}/checkin", headers=ADMIN,
                      json={"date": TOMORROW, "time": "10:00", "note": "TEST_ checkin"})
    assert r.status_code == 200, r.text
    return r.json()["event_id"]


def _notes(eid, outcome, notes="TEST_ follow-up notes"):
    return requests.put(f"{BASE_URL}/api/starter-checklist/user/{EMP_ID}/checkin/{eid}/notes", headers=ADMIN,
                        json={"notes": notes, "outcome": outcome})


# ---- Staff profile
class TestProfile:
    def test_employee_forbidden(self):
        assert requests.get(f"{BASE_URL}/api/staff/{EMP_ID}/profile", headers=EMP).status_code == 403

    def test_unknown_404(self):
        assert requests.get(f"{BASE_URL}/api/staff/user_nope_xyz/profile", headers=ADMIN).status_code == 404

    def test_shape_no_starter(self):
        r = requests.get(f"{BASE_URL}/api/staff/{EMP_ID}/profile", headers=ADMIN)
        assert r.status_code == 200, r.text
        d = r.json()
        assert d["user"]["user_id"] == EMP_ID and d["user"]["email"] == "emp.test@example.com"
        assert isinstance(d["certificates"], list) and isinstance(d["missing_required"], list)
        assert set(d["cpd"]) >= {"year_hours", "year", "logs", "total_logs"}
        assert isinstance(d["cpd"]["year"], int)
        assert all("acknowledged" in p and "policy_id" in p for p in d["policies"])
        assert isinstance(d["checkins"], list) and isinstance(d["open_tasks"], int)
        assert d["starter"] is None  # staff_group null

    def test_admin_profile_ok(self):
        r = requests.get(f"{BASE_URL}/api/staff/{ADMIN_ID}/profile", headers=ADMIN)
        assert r.status_code == 200 and r.json()["user"]["role"] == "admin"


# ---- Check-in follow-up tasks
class TestFollowup:
    def test_followup_created_once(self):
        mdb.users.update_one({"user_id": EMP_ID}, {"$set": {"staff_group": "new_starter_employee"}})
        eid = _book()
        r = _notes(eid, "Follow-up needed", "TEST_ agreed: buddy shift")
        assert r.status_code == 200, r.text
        ev = r.json()
        assert ev.get("followup_created") is True
        gid = ev.get("followup_group_id")
        assert gid
        tasks = list(mdb.tasks.find({"group_id": gid}, {"_id": 0}))
        assert sorted(t["assignee_id"] for t in tasks) == sorted([EMP_ID, ADMIN_ID])
        due = (date.today() + timedelta(days=7)).isoformat()
        assert all(t["due_date"] == due for t in tasks), [t["due_date"] for t in tasks]
        assert all(t["description"] == "TEST_ agreed: buddy shift" for t in tasks)
        assert all(t["title"] == "Follow up: check-in with Erin Employee" for t in tasks)
        assert all(t["status"] == "open" for t in tasks)
        # second save: no duplicate
        r2 = _notes(eid, "Follow-up needed", "TEST_ edited")
        assert r2.status_code == 200 and not r2.json().get("followup_created")
        assert mdb.tasks.count_documents({"group_id": gid, "title": "Follow up: check-in with Erin Employee",
                                          "created_at": {"$gte": START}}) == 2
        # switching outcome away and back does not re-create
        _notes(eid, "On track")
        r3 = _notes(eid, "Follow-up needed")
        assert not r3.json().get("followup_created")
        assert mdb.tasks.count_documents({"group_id": gid, "title": "Follow up: check-in with Erin Employee",
                                          "created_at": {"$gte": START}}) == 2
        # employee notified about the shared task; profile reflects open task + checkin notes
        n = mdb.notifications.find_one({"user_id": EMP_ID, "type": "task", "created_at": {"$gte": START}})
        assert n and "Follow up" in n["body"]
        p = requests.get(f"{BASE_URL}/api/staff/{EMP_ID}/profile", headers=ADMIN).json()
        assert p["open_tasks"] >= 1
        c = [x for x in p["checkins"] if x["event_id"] == eid][0]
        assert c["outcome"] == "Follow-up needed" and c["notes"] == "TEST_ follow-up notes"
        assert p["starter"] and p["starter"]["total"] >= 2

    @pytest.mark.parametrize("outcome", ["On track", "Needs support", ""])
    def test_other_outcomes_no_task(self, outcome):
        eid = _book()
        before = mdb.tasks.count_documents({})
        r = _notes(eid, outcome)
        assert r.status_code == 200 and not r.json().get("followup_created")
        assert not r.json().get("followup_group_id")
        assert mdb.tasks.count_documents({}) == before

    def test_bad_outcome_400(self):
        eid = _book()
        assert _notes(eid, "Whatever").status_code == 400


# ---- Reminder history
class TestReminderHistory:
    def test_admin_only(self):
        assert requests.get(f"{BASE_URL}/api/compliance/reminder-history", headers=EMP).status_code == 403
        r = requests.get(f"{BASE_URL}/api/compliance/reminder-history", headers=ADMIN)
        assert r.status_code == 200 and isinstance(r.json(), list)

    def test_preview_only(self):
        r = requests.post(f"{BASE_URL}/api/compliance/remind-certificates?preview=true", headers=ADMIN)
        assert r.status_code == 200 and r.json()["reminded"] == 0

    def test_send_cert_reminders_logs(self):
        import routes.compliance as rc
        from motor.motor_asyncio import AsyncIOMotorClient
        notes, sent = [], []

        async def fake_notify(uids, ntype, title, body, link=""):
            notes.append((uids, title, body))

        async def fake_email(**kw):
            sent.append(kw)

        row = {"user_id": EMP_ID, "name": "Erin Employee", "email": "erin.fake@realdomain.test",
               "missing_required": ["First Aid"], "no_certs": False}

        async def run():
            db = AsyncIOMotorClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]
            orig = rc.notify, rc.send_email, rc.db
            rc.notify, rc.send_email, rc.db = fake_notify, fake_email, db
            try:
                return await rc.send_cert_reminders([row], "manual", "TEST_Admin")
            finally:
                rc.notify, rc.send_email, rc.db = orig

        assert asyncio.run(run()) == 1
        log = mdb.cert_reminder_log.find_one({"by": "TEST_Admin"}, {"_id": 0})
        try:
            assert log and log["trigger"] == "manual" and log["log_id"].startswith("rem")
            assert log["sent_at"] >= START
            rec = log["recipients"]
            assert rec == [{"user_id": EMP_ID, "name": "Erin Employee", "email": "erin.fake@realdomain.test",
                            "missing": ["First Aid"], "no_certs": False}]
            assert len(notes) == 1 and notes[0][0] == [EMP_ID]
            assert len(sent) == 1 and "First Aid" in sent[0]["html"]
            h = requests.get(f"{BASE_URL}/api/compliance/reminder-history", headers=ADMIN).json()
            assert h[0]["log_id"] == log["log_id"]  # newest first
            assert "_id" not in h[0]
        finally:
            mdb.cert_reminder_log.delete_one({"log_id": log["log_id"]})


# ---- Starter welcome
class TestWelcome:
    def test_patch_group_sets_welcome_once(self):
        mdb.users.update_one({"user_id": EMP_ID}, {"$set": {"staff_group": None},
                                                  "$unset": {"welcome_sent_at": ""}})
        r = requests.patch(f"{BASE_URL}/api/users/{EMP_ID}/group", headers=ADMIN,
                           json={"staff_group": "new_starter_employee"})
        assert r.status_code == 200 and r.json()["staff_group"] == "new_starter_employee"
        time.sleep(2)
        u = mdb.users.find_one({"user_id": EMP_ID})
        assert u.get("welcome_sent_at")
        first = u["welcome_sent_at"]
        q = {"user_id": EMP_ID, "title": "Welcome to the team!", "created_at": {"$gte": START}}
        assert mdb.notifications.count_documents(q) == 1
        n = mdb.notifications.find_one(q)
        assert n["link"] == "/starter-checklist" and "steps" in n["body"]
        for g in ("new_starter_contractor", "support_office", "new_starter_employee"):
            assert requests.patch(f"{BASE_URL}/api/users/{EMP_ID}/group", headers=ADMIN,
                                  json={"staff_group": g}).status_code == 200
        time.sleep(2)
        assert mdb.notifications.count_documents(q) == 1
        assert mdb.users.find_one({"user_id": EMP_ID})["welcome_sent_at"] == first

    def test_non_starter_group_no_welcome(self):
        mdb.users.update_one({"user_id": EMP_ID}, {"$unset": {"welcome_sent_at": ""}})
        requests.patch(f"{BASE_URL}/api/users/{EMP_ID}/group", headers=ADMIN, json={"staff_group": "support_office"})
        time.sleep(1.5)
        assert not mdb.users.find_one({"user_id": EMP_ID}).get("welcome_sent_at")

    def test_bad_group_400(self):
        r = requests.patch(f"{BASE_URL}/api/users/{EMP_ID}/group", headers=ADMIN, json={"staff_group": "nope"})
        assert r.status_code == 400

    def test_welcome_email_inprocess(self):
        import routes.compliance as rc
        import routes.certificates as rcert
        from motor.motor_asyncio import AsyncIOMotorClient
        sent, notes = [], []
        uid = "user_TEST_" + uuid.uuid4().hex[:8]

        async def fake_email(**kw):
            sent.append(kw)

        async def fake_notify(uids, ntype, title, body, link=""):
            notes.append((uids, title))

        async def run():
            db = AsyncIOMotorClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]
            orig = rc.notify, rc.send_email, rc.db, rcert.db
            rc.notify, rc.send_email, rc.db, rcert.db = fake_notify, fake_email, db, db
            await db.users.insert_one({"user_id": uid, "name": "Tess <Tester>", "email": "tess.fake@realdomain.test",
                                       "role": "employee", "staff_group": "new_starter_contractor",
                                       "created_at": START})
            try:
                await rc.send_starter_welcome(uid)
                await rc.send_starter_welcome(uid)  # second call must be a no-op
            finally:
                rc.notify, rc.send_email, rc.db, rcert.db = orig
                await db.users.delete_one({"user_id": uid})

        asyncio.run(run())
        assert len(notes) == 1 and notes[0] == ([uid], "Welcome to the team!")
        assert len(sent) == 1
        e = sent[0]
        assert e["to"] == "tess.fake@realdomain.test"
        assert "Welcome" in e["subject"]
        assert "Welcome aboard, Tess" in e["html"] and "<Tester>" not in e["html"]
        assert "Read and acknowledge all policies" in e["html"] and "<ol>" in e["html"]
