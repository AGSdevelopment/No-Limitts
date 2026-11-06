# Iteration 59: shift decline (14-day rule), re-roster link, clock-out case note gate (409), Finance budget alerts.
import asyncio
import os
import secrets
import time
from datetime import datetime, timedelta, timezone

import pytest
import requests
from dotenv import load_dotenv
from motor.motor_asyncio import AsyncIOMotorClient

load_dotenv("/app/backend/.env")
load_dotenv("/app/frontend/.env")
BASE_URL = (os.environ.get("EXPO_BACKEND_URL") or os.environ.get("EXPO_PUBLIC_BACKEND_URL")).rstrip("/")
API = f"{BASE_URL}/api"
ADMIN = {"Authorization": "Bearer test_session_admin"}
WORKER = {"Authorization": "Bearer test_session_employee"}
WORKER_ID = "user_testemp001"
PERTH = timezone(timedelta(hours=8))
TAG = secrets.token_hex(3)
PNAME = f"TEST_Iter59 {TAG}"
PNAME_B = f"TEST_Iter59B {TAG}"
PID, PID_B = f"par_t59{TAG}", f"par_t59b{TAG}"
FA, FB, FC = f"fund_t59a{TAG}", f"fund_t59b{TAG}", f"fund_t59c{TAG}"


def run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


loop = asyncio.new_event_loop()
asyncio.set_event_loop(loop)
db = AsyncIOMotorClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]
now = datetime.now(PERTH)
today = now.date()


def dmy(d):
    return d.strftime("%d-%m-%Y")


def funding(fid, pid, pname, budget_units, rate, start, end):
    return {"funding_id": fid, "participant_id": pid, "participant_name": pname, "participant_email": "", "management_type": "NDIA",
            "units": float(budget_units), "unit_type": "Hour", "unit_rate": rate, "budget": round(budget_units * rate, 2),
            "start_date": start.isoformat(), "end_date": end.isoformat(), "rate_history": [], "created_by": "TEST", "created_at": now.isoformat()}


@pytest.fixture(scope="module", autouse=True)
def seed():
    run(db.participants.insert_many([
        {"participant_id": PID, "name": PNAME, "key": PNAME.casefold(), "assigned_ids": [WORKER_ID], "profile": {}},
        {"participant_id": PID_B, "name": PNAME_B, "key": PNAME_B.casefold(), "assigned_ids": [WORKER_ID], "profile": {}}]))
    run(db.fundings.insert_many([
        funding(FA, PID, PNAME, 200, 50.0, today - timedelta(days=30), today + timedelta(days=60)),
        funding(FB, PID_B, PNAME_B, 20, 50.0, today - timedelta(days=30), today + timedelta(days=60)),
        funding(FC, PID_B, PNAME_B, 20, 50.0, today - timedelta(days=2), today + timedelta(days=60))]))
    yield
    run(db.shifts.delete_many({"participant_id": {"$in": [PID, PID_B]}}))
    run(db.fundings.delete_many({"funding_id": {"$in": [FA, FB, FC]}}))
    run(db.participants.delete_many({"participant_id": {"$in": [PID, PID_B]}}))
    run(db.notifications.delete_many({"title": {"$regex": f"TEST_Iter59B? {TAG}"}}))


def mk_shift(days_ahead, start="09:00", end="11:00"):
    r = requests.post(f"{API}/shifts", headers=ADMIN, json={"participant_id": PID, "funding_id": FA, "worker_id": WORKER_ID,
                                                            "date": dmy(today + timedelta(days=days_ahead)), "start": start, "end": end})
    assert r.status_code == 200, r.text
    return r.json()


# ---- Decline ----
class TestDecline:
    def test_decline_rules_and_notify(self):
        s = mk_shift(3, "13:00", "15:00")
        assert s["status"] == "pending_acceptance"
        sid = s["shift_id"]
        r = requests.post(f"{API}/shifts/{sid}/decline", headers=ADMIN, json={"reason": "not mine"})
        assert r.status_code == 400  # admin isn't the worker
        r = requests.post(f"{API}/shifts/{sid}/decline", headers=WORKER, json={"reason": "  a "})
        assert r.status_code == 400 and "why" in r.json()["detail"].lower()
        r = requests.post(f"{API}/shifts/{sid}/decline", headers=WORKER, json={"reason": "TEST_ sick child"})
        assert r.status_code == 200 and r.json()["status"] == "declined"
        d = requests.get(f"{API}/shifts/{sid}", headers=ADMIN).json()
        assert d["status"] == "declined" and d["decline_reason"] == "TEST_ sick child" and d.get("declined_at")
        n = run(db.notifications.find_one({"title": {"$regex": f"Shift declined: {PNAME}"}}))
        assert n and "sick child" in n["body"] and n["link"] == "/pm/rostering"
        hidden = run(db.notifications.find_one({"user_id": WORKER_ID, "title": {"$regex": f"Shift declined: {PNAME}"}}))
        assert hidden is None
        r = requests.post(f"{API}/shifts/{sid}/decline", headers=WORKER, json={"reason": "again please"})
        assert r.status_code == 400  # already declined
        # declined shift frees the slot + doesn't count against funding
        use = [f for f in requests.get(f"{API}/funding?participant_id={PID}", headers=ADMIN).json() if f["funding_id"] == FA][0]
        assert use["committed"] == 0
        # re-roster with replaces
        r = requests.post(f"{API}/shifts", headers=ADMIN, json={"participant_id": PID, "funding_id": FA, "worker_id": WORKER_ID,
                                                                "date": dmy(today + timedelta(days=3)), "start": "13:00", "end": "15:00", "replaces": sid})
        assert r.status_code == 200, r.text
        new_id = r.json()["shift_id"]
        assert requests.get(f"{API}/shifts/{sid}", headers=ADMIN).json().get("rerostered") == new_id

    def test_accepted_within_14_days_declinable(self):
        s = mk_shift(5, "13:00", "14:00")
        assert requests.post(f"{API}/shifts/{s['shift_id']}/accept", headers=WORKER).status_code == 200
        r = requests.post(f"{API}/shifts/{s['shift_id']}/decline", headers=WORKER, json={"reason": "TEST_ car broke"})
        assert r.status_code == 200

    def test_more_than_14_days_rejected(self):
        s = mk_shift(20)
        assert s["status"] == "accepted"
        r = requests.post(f"{API}/shifts/{s['shift_id']}/decline", headers=WORKER, json={"reason": "TEST_ holiday"})
        assert r.status_code == 400 and "14 days" in r.json()["detail"]
        assert requests.get(f"{API}/shifts/{s['shift_id']}", headers=ADMIN).json()["status"] == "accepted"

    def test_started_shift_rejected(self):
        s = mk_shift(2, "15:00", "16:00")
        past = now - timedelta(minutes=30)
        run(db.shifts.update_one({"shift_id": s["shift_id"]}, {"$set": {"date": past.date().isoformat(), "start": past.strftime("%H:%M"),
                                                                         "end": (past + timedelta(hours=3)).strftime("%H:%M")}}))
        r = requests.post(f"{API}/shifts/{s['shift_id']}/decline", headers=WORKER, json={"reason": "TEST_ too late"})
        assert r.status_code == 400 and "started" in r.json()["detail"]

    def test_unknown_shift(self):
        r = requests.post(f"{API}/shifts/shf_nope/decline", headers=WORKER, json={"reason": "TEST_ x yz"})
        assert r.status_code == 400


# ---- Clock-out case note gate ----
class TestCaseNoteGate:
    def test_clock_out_409_without_case_note(self):
        s = mk_shift(4, "06:00", "07:00")
        st = now - timedelta(hours=1)
        en = now + timedelta(minutes=2)
        clock_in = {"at": st.isoformat(), "time": st.strftime("%H:%M"), "outside_window": False}
        run(db.shifts.update_one({"shift_id": s["shift_id"]}, {"$set": {
            "date": st.date().isoformat(), "start": st.strftime("%H:%M"), "end": en.strftime("%H:%M"), "status": "in_progress", "clock_in": clock_in}}))
        t = time.time()
        r = requests.post(f"{API}/shifts/{s['shift_id']}/clock-out", headers=WORKER, json={}, timeout=60)
        print(f"clock-out took {time.time() - t:.1f}s")
        assert r.status_code == 409, r.text
        assert r.json()["detail"] == "case_note_required"
        d = run(db.shifts.find_one({"shift_id": s["shift_id"]}))
        assert d["status"] == "in_progress" and "clock_out" not in d and "cost" not in d
        # outside window with reason still gated first (409 before 422/any change)
        r = requests.post(f"{API}/shifts/{s['shift_id']}/clock-out", headers=WORKER, json={"reason": "Held up in traffic"}, timeout=60)
        assert r.status_code == 409
        # admin can't clock-out for the worker
        r = requests.post(f"{API}/shifts/{s['shift_id']}/clock-out", headers=ADMIN, json={}, timeout=60)
        assert r.status_code == 400


# ---- Budget alerts ----
def fund(fid, pid):
    return [f for f in requests.get(f"{API}/funding?participant_id={pid}", headers=ADMIN).json() if f["funding_id"] == fid][0]


def done_shift(fid, pid, pname, d, cost, status="completed", **extra):
    doc = {"shift_id": f"shf_t59{secrets.token_hex(5)}", "participant_id": pid, "participant_name": pname, "funding_id": fid,
           "funding_type": "NDIA", "unit_rate": 50.0, "worker_id": WORKER_ID, "worker_name": "Emp Test", "date": d.isoformat(),
           "start": "09:00", "end": "12:00", "minutes": 180, "est_units": 3, "hourly": True, "est_cost": 150, "status": status, **extra}
    if status == "completed":
        doc.update({"cost": cost, "units": cost / 50})
    run(db.shifts.insert_one(doc))
    return doc["shift_id"]


class TestBudgetAlerts:
    def test_alert_shape_no_spend(self):
        a = fund(FA, PID)["alert"]
        assert set(a) == {"low", "pct_left", "runout"} and a["low"] is False and a["runout"] is None and a["pct_left"] == 100

    def test_runout_then_low_via_approve(self):
        done_shift(FB, PID_B, PNAME_B, today - timedelta(days=20), 700.0)
        a = fund(FB, PID_B)["alert"]
        assert a["low"] is False and a["pct_left"] == 30
        assert a["runout"] and today.isoformat() <= a["runout"] < (today + timedelta(days=60)).isoformat()
        ci = {"at": now.isoformat(), "time": "09:20", "outside_window": True, "reason": "Held up in traffic", "detail": ""}
        sid = done_shift(FB, PID_B, PNAME_B, today - timedelta(days=1), 0, status="awaiting_approval", clock_in=ci, clock_out=ci)
        r = requests.post(f"{API}/shifts/{sid}/approve", headers=ADMIN, json={"start": "09:00", "end": "12:00"})
        assert r.status_code == 200 and r.json()["cost"] == 150
        a = fund(FB, PID_B)["alert"]
        assert a["low"] is True and a["pct_left"] == 15
        f = run(db.fundings.find_one({"funding_id": FB}))
        assert sorted(f.get("alerts_sent") or []) == ["low", "runout"]
        q = {"type": "funding"}
        recips = run(db.users.count_documents({"$or": [{"permissions": "finance"}, {"role": "admin"}], "hidden": {"$ne": True}}))
        low = run(db.notifications.count_documents({**q, "title": f"Low funding: {PNAME_B} (NDIA)"}))
        ro = run(db.notifications.count_documents({**q, "title": f"Funding running out early: {PNAME_B} (NDIA)"}))
        assert recips > 0 and low == recips and ro == recips
        assert run(db.notifications.count_documents({"user_id": WORKER_ID, "title": f"Low funding: {PNAME_B} (NDIA)"})) == 0
        # second approval -> no duplicate alerts
        sid2 = done_shift(FB, PID_B, PNAME_B, today - timedelta(days=1), 0, status="awaiting_approval", clock_in=ci, clock_out=ci)
        assert requests.post(f"{API}/shifts/{sid2}/approve", headers=ADMIN, json={"start": "09:00", "end": "09:30"}).status_code == 200
        assert run(db.notifications.count_documents({**q, "title": f"Low funding: {PNAME_B} (NDIA)"})) == recips

    def test_less_than_7_days_no_runout(self):
        done_shift(FC, PID_B, PNAME_B, today - timedelta(days=1), 900.0)
        a = fund(FC, PID_B)["alert"]
        assert a["low"] is True and a["pct_left"] == 10 and a["runout"] is None

    def test_worker_cannot_list_funding(self):
        assert requests.get(f"{API}/funding", headers=WORKER).status_code in (401, 403)
