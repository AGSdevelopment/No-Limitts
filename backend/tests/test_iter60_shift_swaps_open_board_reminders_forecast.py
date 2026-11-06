# Iteration 60: shift swaps (teammate offer -> accept -> Rosters approve), open shift board (post/claim), 1-hour shift
# reminders with goals, Finance budget forecast PDF (download + emailed shared link).
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
import routes.shift_market as sm  # noqa: E402
from core import db  # noqa: E402


def run(c):
    return loop.run_until_complete(c)


ADMIN = {"Authorization": "Bearer test_session_admin"}
EMP_ID = "user_testemp001"
EMP = {"Authorization": "Bearer test_session_employee"}
TAG = secrets.token_hex(3)
W2_ID, W3_ID = f"user_t60w2{TAG}", f"user_t60w3{TAG}"
W2_TOK, W3_TOK = f"test_sess_t60w2{TAG}", f"test_sess_t60w3{TAG}"
W2, W3 = {"Authorization": f"Bearer {W2_TOK}"}, {"Authorization": f"Bearer {W3_TOK}"}
PNAME, PNAME_B = f"TEST_Iter60 {TAG}", f"TEST_Iter60B {TAG}"
PID, PID_B = f"par_t60{TAG}", f"par_t60b{TAG}"
FA, FB = f"fund_t60a{TAG}", f"fund_t60b{TAG}"
PERTH = timezone(timedelta(hours=8))
now = datetime.now(PERTH)
today = now.date()
CREATED_LINKS = []


def dmy(d):
    return d.strftime("%d-%m-%Y")


def funding(fid, pid, pname):
    return {"funding_id": fid, "participant_id": pid, "participant_name": pname, "participant_email": "", "management_type": "NDIA",
            "units": 500.0, "unit_type": "Hour", "unit_rate": 50.0, "budget": 25000.0,
            "start_date": (today - timedelta(days=30)).isoformat(), "end_date": (today + timedelta(days=90)).isoformat(),
            "rate_history": [], "created_by": "TEST", "created_at": now.isoformat()}


@pytest.fixture(scope="module", autouse=True)
def seed():
    exp = datetime.now(timezone.utc) + timedelta(days=1)
    run(db.users.insert_many([
        {"user_id": W2_ID, "name": f"TEST_Iter60 Worker Two {TAG}", "email": f"t60w2{TAG}@example.com", "role": "employee",
         "user_type": "support_worker", "hidden": False, "created_at": now.isoformat()},
        {"user_id": W3_ID, "name": f"TEST_Iter60 Worker Three {TAG}", "email": f"t60w3{TAG}@example.com", "role": "employee",
         "user_type": "support_worker", "hidden": True, "created_at": now.isoformat()}]))
    run(db.user_sessions.insert_many([{"session_token": W2_TOK, "user_id": W2_ID, "expires_at": exp},
                                      {"session_token": W3_TOK, "user_id": W3_ID, "expires_at": exp}]))
    run(db.participants.insert_many([
        {"participant_id": PID, "name": PNAME, "key": PNAME.casefold(), "assigned_ids": [EMP_ID, W2_ID],
         "profile": {"goals": "TEST goal: build confidence catching the bus"}},
        {"participant_id": PID_B, "name": PNAME_B, "key": PNAME_B.casefold(), "assigned_ids": [W2_ID, EMP_ID], "profile": {}}]))
    run(db.fundings.insert_many([funding(FA, PID, PNAME), funding(FB, PID_B, PNAME_B)]))
    yield
    run(db.shifts.delete_many({"participant_id": {"$in": [PID, PID_B]}}))
    run(db.fundings.delete_many({"funding_id": {"$in": [FA, FB]}}))
    run(db.participants.delete_many({"participant_id": {"$in": [PID, PID_B]}}))
    run(db.notifications.delete_many({"$or": [{"user_id": {"$in": [W2_ID, W3_ID]}},
                                              {"title": {"$regex": re.escape(TAG)}}, {"body": {"$regex": re.escape(TAG)}}]}))
    if CREATED_LINKS:
        run(db.forecast_links.delete_many({"token": {"$in": CREATED_LINKS}}))
    run(db.user_sessions.delete_many({"session_token": {"$in": [W2_TOK, W3_TOK]}}))
    run(db.users.delete_many({"user_id": {"$in": [W2_ID, W3_ID]}}))


def mk_shift(days, start, end, worker=EMP_ID, pid=PID, fid=FA):
    r = requests.post(f"{API}/shifts", headers=ADMIN, json={"participant_id": pid, "funding_id": fid, "worker_id": worker,
                                                            "date": dmy(today + timedelta(days=days)), "start": start, "end": end})
    assert r.status_code == 200, r.text
    return r.json()


def get_shift(sid):
    return run(db.shifts.find_one({"shift_id": sid}, {"_id": 0}))


# ---- Swaps ----
class TestSwaps:
    def test_teammates_own_shift_only(self):
        s = mk_shift(3, "09:00", "10:00")
        r = requests.get(f"{API}/shifts/{s['shift_id']}/teammates", headers=EMP)
        assert r.status_code == 200
        ids = [t["user_id"] for t in r.json()]
        assert W2_ID in ids and EMP_ID not in ids
        assert requests.get(f"{API}/shifts/{s['shift_id']}/teammates", headers=W2).status_code == 404

    def test_swap_validation(self):
        s = mk_shift(3, "11:00", "12:00")
        sid = s["shift_id"]
        assert requests.post(f"{API}/shifts/{sid}/swap", headers=W2, json={"to_worker_id": EMP_ID}).status_code == 400  # not own
        assert requests.post(f"{API}/shifts/{sid}/swap", headers=EMP, json={"to_worker_id": EMP_ID}).status_code == 400  # self
        assert requests.post(f"{API}/shifts/{sid}/swap", headers=EMP, json={"to_worker_id": W3_ID}).status_code == 400  # not on team
        # clash: W2 has an overlapping shift for another participant
        mk_shift(4, "09:00", "11:00", worker=W2_ID, pid=PID_B, fid=FB)
        s2 = mk_shift(4, "10:00", "12:00")
        r = requests.post(f"{API}/shifts/{s2['shift_id']}/swap", headers=EMP, json={"to_worker_id": W2_ID})
        assert r.status_code == 409, r.text
        # past shift
        past = {**s, "shift_id": f"shf_t60past{TAG}", "date": (today - timedelta(days=1)).isoformat()}
        past.pop("swap", None)
        run(db.shifts.insert_one(dict(past)))
        assert requests.post(f"{API}/shifts/{past['shift_id']}/swap", headers=EMP, json={"to_worker_id": W2_ID}).status_code == 400

    def test_full_swap_flow_approved(self):
        s = mk_shift(5, "13:00", "14:00")
        sid = s["shift_id"]
        r = requests.post(f"{API}/shifts/{sid}/swap", headers=EMP, json={"to_worker_id": W2_ID, "note": "  TEST note  "})
        assert r.status_code == 200, r.text
        assert r.json()["swap"]["status"] == "pending_teammate" and r.json()["swap"]["note"] == "TEST note"
        dup = requests.post(f"{API}/shifts/{sid}/swap", headers=EMP, json={"to_worker_id": W2_ID})
        assert dup.status_code == 400
        offers = requests.get(f"{API}/shifts-offers", headers=W2).json()
        assert sid in [o["shift_id"] for o in offers["offers"]]
        assert "est_cost" not in offers["offers"][0]  # support worker shouldn't see cost
        assert requests.post(f"{API}/shifts/{sid}/swap/respond", headers=W3, json={"accept": True}).status_code == 404
        assert requests.post(f"{API}/shifts/{sid}/swap/decide", headers=ADMIN, json={"approve": True}).status_code == 404  # not yet
        r = requests.post(f"{API}/shifts/{sid}/swap/respond", headers=W2, json={"accept": True})
        assert r.status_code == 200 and r.json()["status"] == "pending_rosters"
        appr = requests.get(f"{API}/shifts-offers", headers=ADMIN).json()["approvals"]
        assert sid in [a["shift_id"] for a in appr]
        assert requests.get(f"{API}/shifts-offers", headers=EMP).json()["approvals"] == []
        assert requests.post(f"{API}/shifts/{sid}/swap/decide", headers=EMP, json={"approve": True}).status_code == 403
        r = requests.post(f"{API}/shifts/{sid}/swap/decide", headers=ADMIN, json={"approve": True})
        assert r.status_code == 200 and r.json()["approved"] is True
        d = get_shift(sid)
        assert d["worker_id"] == W2_ID and d["worker_name"].startswith("TEST_Iter60 Worker Two")
        assert d["status"] == "accepted" and d["swap"]["status"] == "approved" and d["previous_worker_id"] == EMP_ID
        n = run(db.notifications.count_documents({"user_id": W2_ID, "title": "Shift swap approved"}))
        assert n == 1
        assert run(db.notifications.count_documents({"user_id": W2_ID, "title": {"$regex": "^Shift offered to you"}})) >= 1

    def test_swap_declined_and_rejected(self):
        s = mk_shift(6, "13:00", "14:00")
        sid = s["shift_id"]
        assert requests.post(f"{API}/shifts/{sid}/swap", headers=EMP, json={"to_worker_id": W2_ID}).status_code == 200
        r = requests.post(f"{API}/shifts/{sid}/swap/respond", headers=W2, json={"accept": False})
        assert r.status_code == 200 and r.json()["status"] == "declined_by_teammate"
        assert get_shift(sid)["worker_id"] == EMP_ID
        # can re-offer after decline, then rosters reject
        assert requests.post(f"{API}/shifts/{sid}/swap", headers=EMP, json={"to_worker_id": W2_ID}).status_code == 200
        assert requests.post(f"{API}/shifts/{sid}/swap/respond", headers=W2, json={"accept": True}).status_code == 200
        r = requests.post(f"{API}/shifts/{sid}/swap/decide", headers=ADMIN, json={"approve": False})
        assert r.status_code == 200 and r.json()["approved"] is False
        d = get_shift(sid)
        assert d["worker_id"] == EMP_ID and d["swap"]["status"] == "rejected"


# ---- Open shift board ----
class TestOpenBoard:
    def _declined(self, days, start, end):
        s = mk_shift(days, start, end)
        r = requests.post(f"{API}/shifts/{s['shift_id']}/decline", headers=EMP, json={"reason": "TEST can't make it"})
        assert r.status_code == 200, r.text
        return s["shift_id"]

    def test_post_and_claim(self):
        sid = self._declined(7, "15:00", "16:00")
        assert requests.post(f"{API}/shifts/{sid}/open", headers=EMP).status_code == 403
        r = requests.post(f"{API}/shifts/{sid}/open", headers=ADMIN)
        assert r.status_code == 200 and r.json()["open"] is True and r.json()["notified"] == 1
        not_declined = mk_shift(7, "17:00", "18:00")
        assert requests.post(f"{API}/shifts/{not_declined['shift_id']}/open", headers=ADMIN).status_code == 400
        w2_open = requests.get(f"{API}/shifts-offers", headers=W2).json()["open"]
        assert any(o["shift_id"] == sid and o["can_claim"] for o in w2_open)
        assert sid not in [o["shift_id"] for o in requests.get(f"{API}/shifts-offers", headers=EMP).json()["open"]]  # decliner
        assert sid not in [o["shift_id"] for o in requests.get(f"{API}/shifts-offers", headers=W3).json()["open"]]  # not on team
        adm = [o for o in requests.get(f"{API}/shifts-offers", headers=ADMIN).json()["open"] if o["shift_id"] == sid]
        assert adm and adm[0]["can_claim"] is False
        assert requests.post(f"{API}/shifts/{sid}/claim", headers=W3).status_code == 400  # not on team
        assert requests.post(f"{API}/shifts/{sid}/claim", headers=EMP).status_code == 400  # decliner
        assert get_shift(sid)["open"] is True  # restored after failed claim
        r = requests.post(f"{API}/shifts/{sid}/claim", headers=W2)
        assert r.status_code == 200, r.text
        new = get_shift(r.json()["shift_id"])
        assert new["worker_id"] == W2_ID and new["status"] == "accepted" and new.get("claimed") is True
        old = get_shift(sid)
        assert old["rerostered"] == new["shift_id"] and old["open"] is False
        assert requests.post(f"{API}/shifts/{sid}/claim", headers=W2).status_code == 400
        assert requests.post(f"{API}/shifts/{sid}/open", headers=ADMIN).status_code == 400  # already re-rostered

    def test_open_then_manual_reroster_hides_from_board(self):
        """Edge: Rosters re-roster manually after posting; board should no longer offer it."""
        sid = self._declined(8, "15:00", "16:00")
        assert requests.post(f"{API}/shifts/{sid}/open", headers=ADMIN).status_code == 200
        r = requests.post(f"{API}/shifts", headers=ADMIN, json={"participant_id": PID, "funding_id": FA, "worker_id": W2_ID,
                                                                "date": dmy(today + timedelta(days=8)), "start": "15:00", "end": "16:00",
                                                                "replaces": sid})
        assert r.status_code == 200, r.text
        c = requests.post(f"{API}/shifts/{sid}/claim", headers=W2)
        print("claim after manual reroster:", c.status_code, c.text[:200])
        dup = run(db.shifts.count_documents({"participant_id": PID, "status": {"$ne": "declined"}, "date": (today + timedelta(days=8)).isoformat(),
                                             "start": "15:00"}))
        assert c.status_code == 400 and dup == 1, f"claim={c.status_code}, active replacement shifts={dup}"
        w2_open = [o["shift_id"] for o in requests.get(f"{API}/shifts-offers", headers=W2).json()["open"]]
        assert sid not in w2_open, "re-rostered shift still listed on open board"


class TestSwapAfterCancel:
    def test_cancelled_shift_swap_cannot_be_approved(self):
        """Edge: Rosters cancel a shift that has a pending swap; teammate/Rosters must not resurrect it."""
        s = mk_shift(9, "13:00", "14:00")
        sid = s["shift_id"]
        assert requests.post(f"{API}/shifts/{sid}/swap", headers=EMP, json={"to_worker_id": W2_ID}).status_code == 200
        cr = requests.delete(f"{API}/shifts/{sid}", headers=ADMIN)
        print("cancel:", cr.status_code, cr.text[:200])
        assert get_shift(sid)["status"] == "cancelled"
        listed = sid in [o["shift_id"] for o in requests.get(f"{API}/shifts-offers", headers=W2).json()["offers"]]
        requests.post(f"{API}/shifts/{sid}/swap/respond", headers=W2, json={"accept": True})
        requests.post(f"{API}/shifts/{sid}/swap/decide", headers=ADMIN, json={"approve": True})
        st = get_shift(sid)["status"]
        assert not listed and st == "cancelled", f"offer still listed={listed}, status after approve={st}"


# ---- Reminders ----
class TestReminders:
    def test_reminder_with_goals_once(self):
        start = now + timedelta(minutes=40)
        if start.date() != now.date() and start.date() != today + timedelta(days=1):
            pytest.skip("date edge")
        sid = f"shf_t60rem{TAG}"
        end = start + timedelta(hours=1)
        run(db.shifts.insert_one({"shift_id": sid, "date": start.date().isoformat(), "start": start.strftime("%H:%M"),
                                  "end": end.strftime("%H:%M") if end.date() == start.date() else "23:59",
                                  "participant_id": PID, "participant_name": PNAME, "funding_id": FA, "worker_id": W2_ID,
                                  "worker_name": "TEST W2", "status": "accepted", "minutes": 60}))
        far = f"shf_t60far{TAG}"
        fs = now + timedelta(hours=3)
        run(db.shifts.insert_one({"shift_id": far, "date": fs.date().isoformat(), "start": fs.strftime("%H:%M"), "end": "23:59",
                                  "participant_id": PID, "participant_name": PNAME, "funding_id": FA, "worker_id": W2_ID,
                                  "worker_name": "TEST W2", "status": "accepted", "minutes": 60}))
        run(sm.shift_reminders())
        run(sm.shift_reminders())
        notes = run(db.notifications.find({"user_id": W2_ID, "title": f"Shift in 1 hour: {PNAME}"}, {"_id": 0}).to_list(10))
        assert len(notes) == 1, notes
        assert "TEST goal: build confidence" in notes[0]["body"]
        assert get_shift(sid)["reminded"] is True
        assert not get_shift(far).get("reminded")


# ---- Budget forecast ----
class TestForecast:
    def test_forecast_pdf_access(self):
        r = requests.get(f"{API}/funding/forecast/pdf", params={"token": "test_session_admin"})
        assert r.status_code == 200 and r.headers["content-type"].startswith("application/pdf") and r.content[:4] == b"%PDF"
        assert requests.get(f"{API}/funding/forecast/pdf", params={"token": "test_session_employee"}).status_code == 403
        assert requests.get(f"{API}/funding/forecast/pdf").status_code in (401, 403)
        assert requests.get(f"{API}/funding/forecast/pdf", headers=ADMIN).status_code == 200

    def test_forecast_pdf_contains_participant(self):
        import pymupdf
        r = requests.get(f"{API}/funding/forecast/pdf", params={"token": "test_session_admin"})
        text = "".join(p.get_text() for p in pymupdf.open(stream=r.content, filetype="pdf"))
        assert PNAME in text and "Projected run-out" in text

    def test_email_forecasts_shared_link(self, monkeypatch):
        sent = []

        async def fake_send(to, subject, html, **kw):
            sent.append((to, subject, html))
        monkeypatch.setattr(sm, "send_email", fake_send)
        run(sm.email_forecasts())
        toks = [re.search(r"/forecast/shared/([\w-]+)", h).group(1) for _, _, h in sent]
        CREATED_LINKS.extend(toks)
        assert sent and all(s[1].startswith("Budget forecast:") for s in sent)
        assert run(db.forecast_links.count_documents({"token": {"$in": toks}})) == len(toks)
        assert BASE_URL in sent[0][2]
        r = requests.get(f"{API}/funding/forecast/shared/{toks[0]}")
        assert r.status_code == 200 and r.content[:4] == b"%PDF"
        assert requests.get(f"{API}/funding/forecast/shared/bad{TAG}").status_code == 404
