# Iteration 61: retest of two HIGH bugs from iter 60.
# Bug 1: manual re-roster of an open-board shift closes the board entry (open=False), claim 400, board hides it,
#        second re-roster 400. Bug 2: cancel/decline withdraws a pending swap, notifies teammate; respond/decide on
#        non-live shifts 400/404; offers/approvals exclude cancelled/declined shifts.
import asyncio
import os
import re
import secrets
import sys
from datetime import datetime, timedelta, timezone

import pytest
import requests
from dotenv import load_dotenv

load_dotenv("/app/backend/.env")
load_dotenv("/app/frontend/.env")
sys.path.insert(0, "/app/backend")
BASE_URL = (os.environ.get("EXPO_BACKEND_URL") or os.environ.get("EXPO_PUBLIC_BACKEND_URL")).rstrip("/")
API = f"{BASE_URL}/api"

loop = asyncio.new_event_loop()
asyncio.set_event_loop(loop)
from core import db  # noqa: E402


def run(c):
    return loop.run_until_complete(c)


ADMIN = {"Authorization": "Bearer test_session_admin"}
EMP_ID = "user_testemp001"
EMP = {"Authorization": "Bearer test_session_employee"}
TAG = secrets.token_hex(3)
W2_ID, W3_ID = f"user_t61w2{TAG}", f"user_t61w3{TAG}"
W2_TOK, W3_TOK = f"test_sess_t61w2{TAG}", f"test_sess_t61w3{TAG}"
W2, W3 = {"Authorization": f"Bearer {W2_TOK}"}, {"Authorization": f"Bearer {W3_TOK}"}
PNAME, PID, FA = f"TEST_Iter61 {TAG}", f"par_t61{TAG}", f"fund_t61a{TAG}"
PERTH = timezone(timedelta(hours=8))
now = datetime.now(PERTH)
today = now.date()


def dmy(d):
    return d.strftime("%d-%m-%Y")


@pytest.fixture(scope="module", autouse=True)
def seed():
    exp = datetime.now(timezone.utc) + timedelta(days=1)
    run(db.users.insert_many([
        {"user_id": W2_ID, "name": f"TEST_Iter61 Worker Two {TAG}", "email": f"t61w2{TAG}@example.com", "role": "employee",
         "user_type": "support_worker", "hidden": True, "created_at": now.isoformat()},
        {"user_id": W3_ID, "name": f"TEST_Iter61 Worker Three {TAG}", "email": f"t61w3{TAG}@example.com", "role": "employee",
         "user_type": "support_worker", "hidden": True, "created_at": now.isoformat()}]))
    run(db.user_sessions.insert_many([{"session_token": W2_TOK, "user_id": W2_ID, "expires_at": exp},
                                      {"session_token": W3_TOK, "user_id": W3_ID, "expires_at": exp}]))
    run(db.participants.insert_one({"participant_id": PID, "name": PNAME, "key": PNAME.casefold(),
                                    "assigned_ids": [EMP_ID, W2_ID, W3_ID], "profile": {}}))
    run(db.fundings.insert_one({"funding_id": FA, "participant_id": PID, "participant_name": PNAME, "participant_email": "",
                                "management_type": "NDIA", "units": 500.0, "unit_type": "Hour", "unit_rate": 50.0, "budget": 25000.0,
                                "start_date": (today - timedelta(days=30)).isoformat(), "end_date": (today + timedelta(days=90)).isoformat(),
                                "rate_history": [], "created_by": "TEST", "created_at": now.isoformat()}))
    yield
    run(db.shifts.delete_many({"participant_id": PID}))
    run(db.fundings.delete_many({"funding_id": FA}))
    run(db.participants.delete_many({"participant_id": PID}))
    run(db.notifications.delete_many({"$or": [{"user_id": {"$in": [W2_ID, W3_ID]}},
                                              {"title": {"$regex": re.escape(TAG)}}, {"body": {"$regex": re.escape(TAG)}}]}))
    run(db.user_sessions.delete_many({"session_token": {"$in": [W2_TOK, W3_TOK]}}))
    run(db.users.delete_many({"user_id": {"$in": [W2_ID, W3_ID]}}))


def mk_shift(days, start, end, worker=EMP_ID, replaces=""):
    return requests.post(f"{API}/shifts", headers=ADMIN, json={"participant_id": PID, "funding_id": FA, "worker_id": worker,
                                                               "date": dmy(today + timedelta(days=days)), "start": start, "end": end,
                                                               "replaces": replaces})


def new_shift(days, start, end, worker=EMP_ID):
    r = mk_shift(days, start, end, worker)
    assert r.status_code == 200, r.text
    return r.json()["shift_id"]


def get_shift(sid):
    return run(db.shifts.find_one({"shift_id": sid}, {"_id": 0}))


def offers(h):
    return requests.get(f"{API}/shifts-offers", headers=h).json()


def ids(lst):
    return [o["shift_id"] for o in lst]


def declined(days, start, end):
    sid = new_shift(days, start, end)
    r = requests.post(f"{API}/shifts/{sid}/decline", headers=EMP, json={"reason": "TEST can't make it"})
    assert r.status_code == 200, r.text
    return sid


def withdrawn_notes(uid):
    return run(db.notifications.count_documents({"user_id": uid, "title": {"$regex": f"^Swap withdrawn.*{re.escape(TAG)}"}}))


# ---- Bug 1: open board + manual re-roster ----
class TestOpenBoardReroster:
    def test_manual_reroster_closes_board(self):
        sid = declined(3, "09:00", "10:00")
        assert requests.post(f"{API}/shifts/{sid}/open", headers=ADMIN).status_code == 200
        assert sid in ids(offers(W2)["open"])
        r = mk_shift(3, "09:00", "10:00", worker=W2_ID, replaces=sid)
        assert r.status_code == 200, r.text
        new_id = r.json()["shift_id"]
        old = get_shift(sid)
        assert old["open"] is False and old["rerostered"] == new_id
        c = requests.post(f"{API}/shifts/{sid}/claim", headers=W3)
        assert c.status_code == 400, c.text
        assert get_shift(sid)["open"] is False  # failed claim must not reopen
        active = run(db.shifts.count_documents({"participant_id": PID, "status": {"$nin": ["declined", "cancelled"]},
                                                "date": (today + timedelta(days=3)).isoformat(), "start": "09:00"}))
        assert active == 1
        for h in (W2, W3, ADMIN):
            assert sid not in ids(offers(h)["open"])
        # re-rostering again (to a non-clashing teammate) must be rejected
        r2 = mk_shift(3, "09:00", "10:00", worker=W3_ID, replaces=sid)
        assert r2.status_code == 400 and "already been re-rostered" in r2.text, r2.text
        assert get_shift(sid)["rerostered"] == new_id

    def test_reroster_after_claim_rejected(self):
        sid = declined(4, "09:00", "10:00")
        assert requests.post(f"{API}/shifts/{sid}/open", headers=ADMIN).status_code == 200
        c = requests.post(f"{API}/shifts/{sid}/claim", headers=W2)
        assert c.status_code == 200, c.text
        r = mk_shift(4, "09:00", "10:00", worker=W3_ID, replaces=sid)
        assert r.status_code == 400 and "already been re-rostered" in r.text, r.text
        assert requests.post(f"{API}/shifts/{sid}/claim", headers=W3).status_code == 400

    def test_legacy_open_and_rerostered_hidden_and_unclaimable(self):
        """Data written before the fix: open=True but rerostered set."""
        sid = declined(5, "09:00", "10:00")
        run(db.shifts.update_one({"shift_id": sid}, {"$set": {"open": True, "rerostered": "shf_TEST_legacy"}}))
        assert sid not in ids(offers(W2)["open"]) and sid not in ids(offers(ADMIN)["open"])
        assert requests.post(f"{API}/shifts/{sid}/claim", headers=W2).status_code == 400
        assert get_shift(sid)["open"] is True  # untouched (filter didn't match)
        assert run(db.shifts.count_documents({"participant_id": PID, "date": (today + timedelta(days=5)).isoformat(),
                                              "status": {"$ne": "declined"}})) == 0


# ---- Bug 2: swap withdrawn on cancel/decline ----
class TestSwapWithdraw:
    def _swap(self, days, accept=False):
        sid = new_shift(days, "13:00", "14:00")
        assert requests.post(f"{API}/shifts/{sid}/swap", headers=EMP, json={"to_worker_id": W2_ID}).status_code == 200
        if accept:
            r = requests.post(f"{API}/shifts/{sid}/swap/respond", headers=W2, json={"accept": True})
            assert r.status_code == 200 and r.json()["status"] == "pending_rosters"
        return sid

    def test_cancel_pending_teammate(self):
        before = withdrawn_notes(W2_ID)
        sid = self._swap(3)
        assert requests.delete(f"{API}/shifts/{sid}", headers=ADMIN).status_code == 200
        d = get_shift(sid)
        assert d["status"] == "cancelled" and d["swap"]["status"] == "withdrawn"
        assert withdrawn_notes(W2_ID) == before + 1
        n = run(db.notifications.find_one({"user_id": W2_ID, "title": {"$regex": f"^Swap withdrawn.*{re.escape(TAG)}"}}, {"_id": 0}))
        assert "cancelled" in n["body"]
        assert sid not in ids(offers(W2)["offers"])
        assert requests.post(f"{API}/shifts/{sid}/swap/respond", headers=W2, json={"accept": True}).status_code in (400, 404)
        assert requests.post(f"{API}/shifts/{sid}/swap/decide", headers=ADMIN, json={"approve": True}).status_code in (400, 404)
        assert get_shift(sid)["status"] == "cancelled" and get_shift(sid)["worker_id"] == EMP_ID

    def test_cancel_pending_rosters(self):
        sid = self._swap(4, accept=True)
        assert sid in ids(offers(ADMIN)["approvals"])
        before = withdrawn_notes(W2_ID)
        assert requests.delete(f"{API}/shifts/{sid}", headers=ADMIN).status_code == 200
        assert get_shift(sid)["swap"]["status"] == "withdrawn"
        assert withdrawn_notes(W2_ID) == before + 1
        assert sid not in ids(offers(ADMIN)["approvals"])
        assert requests.post(f"{API}/shifts/{sid}/swap/decide", headers=ADMIN, json={"approve": True}).status_code in (400, 404)
        d = get_shift(sid)
        assert d["status"] == "cancelled" and d["worker_id"] == EMP_ID

    def test_decline_pending_teammate_and_rosters(self):
        before = withdrawn_notes(W2_ID)
        a = self._swap(5)
        b = self._swap(6, accept=True)
        for sid in (a, b):
            r = requests.post(f"{API}/shifts/{sid}/decline", headers=EMP, json={"reason": "TEST sick"})
            assert r.status_code == 200, r.text
            d = get_shift(sid)
            assert d["status"] == "declined" and d["swap"]["status"] == "withdrawn"
        assert withdrawn_notes(W2_ID) == before + 2
        n = run(db.notifications.find_one({"user_id": W2_ID, "title": {"$regex": f"^Swap withdrawn.*{re.escape(TAG)}"}}, {"_id": 0},
                                          sort=[("created_at", -1)]))
        assert "declined" in n["body"]
        o = offers(W2)
        assert a not in ids(o["offers"])
        assert b not in ids(offers(ADMIN)["approvals"])
        assert requests.post(f"{API}/shifts/{a}/swap/respond", headers=W2, json={"accept": True}).status_code in (400, 404)
        assert requests.post(f"{API}/shifts/{b}/swap/decide", headers=ADMIN, json={"approve": True}).status_code in (400, 404)
        assert get_shift(b)["status"] == "declined" and get_shift(b)["worker_id"] == EMP_ID

    def test_no_withdraw_notification_without_live_swap(self):
        before = withdrawn_notes(W2_ID)
        sid = self._swap(7)
        assert requests.post(f"{API}/shifts/{sid}/swap/respond", headers=W2, json={"accept": False}).status_code == 200
        assert requests.delete(f"{API}/shifts/{sid}", headers=ADMIN).status_code == 200
        assert get_shift(sid)["swap"]["status"] == "declined_by_teammate"
        assert withdrawn_notes(W2_ID) == before

    def test_legacy_nonlive_shift_respond_decide_400(self):
        """Pre-fix data: shift cancelled/declined while swap still pending -> 400, not resurrected, not listed."""
        a = self._swap(8)
        b = self._swap(9, accept=True)
        run(db.shifts.update_one({"shift_id": a}, {"$set": {"status": "cancelled"}}))
        run(db.shifts.update_one({"shift_id": b}, {"$set": {"status": "declined"}}))
        assert a not in ids(offers(W2)["offers"])
        assert b not in ids(offers(ADMIN)["approvals"])
        ra = requests.post(f"{API}/shifts/{a}/swap/respond", headers=W2, json={"accept": True})
        assert ra.status_code == 400, ra.text
        rb = requests.post(f"{API}/shifts/{b}/swap/decide", headers=ADMIN, json={"approve": True})
        assert rb.status_code == 400, rb.text
        assert get_shift(a)["status"] == "cancelled" and get_shift(a)["swap"]["status"] == "pending_teammate"
        assert get_shift(b)["status"] == "declined" and get_shift(b)["worker_id"] == EMP_ID

    def test_started_shift_respond_400(self):
        sid = self._swap(10)
        run(db.shifts.update_one({"shift_id": sid}, {"$set": {"date": (today - timedelta(days=1)).isoformat()}}))
        r = requests.post(f"{API}/shifts/{sid}/swap/respond", headers=W2, json={"accept": True})
        assert r.status_code == 400, r.text
