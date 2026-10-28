# Iteration 34: Vote deadline (poll.closes_on + poll_close_loop auto-lock) and referral map radius filter
import os
import subprocess
import time
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest
import requests
from dotenv import load_dotenv
from pymongo import MongoClient

load_dotenv("/app/frontend/.env")
load_dotenv("/app/backend/.env")
BASE_URL = os.environ.get("EXPO_PUBLIC_BACKEND_URL").rstrip("/")
API = f"{BASE_URL}/api"
db = MongoClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]
ADMIN = {"Authorization": "Bearer test_session_admin"}
EMP = {"Authorization": "Bearer test_session_employee"}
REF = "Trusted Referral Partner Organisations"
TODAY = datetime.now(ZoneInfo("Australia/Perth")).date()
YESTERDAY = (TODAY - timedelta(days=1)).isoformat()
STATE = {"events": [], "ids": []}


@pytest.fixture(scope="module", autouse=True)
def cleanup():
    since = datetime.now(timezone.utc).isoformat()
    yield
    db.directory.delete_many({"name": {"$regex": "^TEST_"}})
    db.events.delete_many({"$or": [{"event_id": {"$in": STATE["events"]}}, {"title": {"$regex": "^TEST_"}}]})
    db.notifications.delete_many({"created_at": {"$gte": since}, "type": {"$in": ["directory", "event"]}})


def make_event(title):
    r = requests.post(f"{API}/events", json={"title": title, "date": (TODAY + timedelta(days=20)).isoformat()}, headers=ADMIN)
    assert r.status_code == 200, r.text
    STATE["events"].append(r.json()["event_id"])
    return r.json()["event_id"]


def make_poll(eid, closes_on="", kind="venue", options=("TEST_A1", "TEST_A2")):
    return requests.post(f"{API}/events/{eid}/poll", json={"kind": kind, "options": list(options), "closes_on": closes_on},
                         headers=ADMIN)


# ---- Poll closing-date validation
class TestPollDeadline:
    def test_past_closes_on_rejected(self):
        eid = make_event("TEST_Deadline Past")
        r = make_poll(eid, YESTERDAY)
        assert r.status_code == 400 and "today or a future" in r.json()["detail"], r.text

    def test_bad_format_rejected(self):
        eid = make_event("TEST_Deadline Bad")
        for bad in ("31-12-2026", "2026/12/31", "tomorrow"):
            r = make_poll(eid, bad)
            assert r.status_code == 400 and "YYYY-MM-DD" in r.json()["detail"], (bad, r.text)

    def test_valid_today_and_future_stored(self):
        eid = make_event("TEST_Deadline Ok")
        r = make_poll(eid, TODAY.isoformat())
        assert r.status_code == 200, r.text
        assert r.json()["poll"]["closes_on"] == TODAY.isoformat()
        g = requests.get(f"{API}/events/{eid}", headers=EMP).json()
        assert g["poll"]["closes_on"] == TODAY.isoformat() and g["poll"]["closed"] is False

    def test_no_closes_on_is_empty(self):
        eid = make_event("TEST_Deadline None")
        r = make_poll(eid)
        assert r.status_code == 200 and r.json()["poll"]["closes_on"] == ""


@pytest.fixture(scope="module")
def acts():
    out = []
    for i in range(2):
        r = requests.post(f"{API}/directory", json={"space": "participant", "category": "Activities", "name": f"TEST_VAct {i}",
                                                     "address": f"{i + 1} Beach Rd WA"}, headers=ADMIN)
        assert r.status_code == 200, r.text
        out.append(r.json()["entry_id"])
    return out


class TestActivityVoteDeadline:
    def test_activity_vote_closes_on(self, acts):
        future = (TODAY + timedelta(days=5)).isoformat()
        r = requests.post(f"{API}/events/activity-vote", json={"entry_ids": acts, "title": "TEST_ActVote", "closes_on": future},
                          headers=ADMIN)
        assert r.status_code == 200, r.text
        STATE["events"].append(r.json()["event_id"])
        assert r.json()["poll"]["closes_on"] == future
        assert db.events.find_one({"event_id": r.json()["event_id"]})["poll"]["closes_on"] == future

    def test_activity_vote_past_and_bad(self, acts):
        for bad, msg in ((YESTERDAY, "today or a future"), ("01-02-2027", "YYYY-MM-DD")):
            r = requests.post(f"{API}/events/activity-vote", json={"entry_ids": acts, "title": "TEST_ActBad", "closes_on": bad},
                              headers=ADMIN)
            assert r.status_code == 400 and msg in r.json()["detail"], r.text
        assert db.events.count_documents({"title": "TEST_ActBad"}) == 0


# ---- Auto-lock via poll_close_loop (runs at startup)
class TestAutoLock:
    def test_auto_lock_after_restart(self, acts):
        since = datetime.now(timezone.utc).isoformat()
        # leader: option 2 has 2 votes
        e1 = make_event("TEST_Auto Leader")
        o1 = make_poll(e1, TODAY.isoformat()).json()["poll"]["options"]
        for h in (ADMIN, EMP):
            assert requests.post(f"{API}/events/{e1}/poll/{o1[1]['option_id']}/vote", headers=h).status_code == 200
        # tie 1-1 -> first option
        e2 = make_event("TEST_Auto Tie")
        o2 = make_poll(e2, TODAY.isoformat(), options=("TEST_T1", "TEST_T2")).json()["poll"]["options"]
        requests.post(f"{API}/events/{e2}/poll/{o2[1]['option_id']}/vote", headers=ADMIN)
        requests.post(f"{API}/events/{e2}/poll/{o2[0]['option_id']}/vote", headers=EMP)
        # zero votes
        e3 = make_event("TEST_Auto Zero")
        make_poll(e3, TODAY.isoformat(), options=("TEST_Z1", "TEST_Z2"))
        # activity vote with a winner
        r = requests.post(f"{API}/events/activity-vote", json={"entry_ids": acts, "title": "TEST_Auto Act",
                                                                "closes_on": TODAY.isoformat()}, headers=ADMIN)
        e4 = r.json()["event_id"]
        STATE["events"].append(e4)
        o4 = r.json()["poll"]["options"]
        requests.post(f"{API}/events/{e4}/poll/{o4[1]['option_id']}/vote", headers=EMP)
        # date poll with a winner
        e5 = make_event("TEST_Auto Date")
        d1, d2 = (TODAY + timedelta(days=30)).isoformat(), (TODAY + timedelta(days=31)).isoformat()
        o5 = make_poll(e5, TODAY.isoformat(), kind="date", options=(d1, d2)).json()["poll"]["options"]
        requests.post(f"{API}/events/{e5}/poll/{o5[1]['option_id']}/vote", headers=EMP)
        # control: closes today -> must stay open
        e6 = make_event("TEST_Auto Today")
        o6 = make_poll(e6, TODAY.isoformat(), options=("TEST_C1", "TEST_C2")).json()["poll"]["options"]
        requests.post(f"{API}/events/{e6}/poll/{o6[0]['option_id']}/vote", headers=EMP)

        db.events.update_many({"event_id": {"$in": [e1, e2, e3, e4, e5]}}, {"$set": {"poll.closes_on": YESTERDAY}})
        subprocess.run(["sudo", "supervisorctl", "restart", "backend"], check=True, capture_output=True)
        deadline = time.time() + 30
        while time.time() < deadline:
            time.sleep(2)
            try:
                if requests.get(f"{API}/events/{e1}", headers=ADMIN, timeout=5).json()["poll"].get("closed"):
                    break
            except Exception:
                pass
        time.sleep(2)
        g = lambda e: requests.get(f"{API}/events/{e}", headers=ADMIN, timeout=10).json()
        a = g(e1)
        assert a["poll"]["closed"] is True and a["poll"]["auto_locked"] is True, a["poll"]
        assert a["poll"]["locked_option_id"] == o1[1]["option_id"] and a["location"] == "TEST_A2"
        t = g(e2)
        assert t["poll"]["closed"] is True and t["poll"]["locked_option_id"] == o2[0]["option_id"] and t["location"] == "TEST_T1"
        z = g(e3)
        assert z["poll"]["closed"] is False and z["poll"]["closes_on"] == "" and not z["poll"].get("auto_locked")
        n = db.notifications.find_one({"user_id": "user_testadmin01", "link": f"/event/{e3}", "title": {"$regex": "^No votes yet"}})
        assert n is not None
        ac = g(e4)
        assert ac["poll"]["closed"] is True and ac["title"] == "TEST_VAct 1" and ac["description"] == "The team voted for TEST_VAct 1."
        dt = g(e5)
        assert dt["poll"]["closed"] is True and dt["date"] == d2
        c = g(e6)
        assert c["poll"]["closed"] is False and c["poll"]["closes_on"] == TODAY.isoformat()
        # organiser gets auto-lock notification with "(N votes, voting closed)"
        ln = db.notifications.find_one({"user_id": "user_testadmin01", "link": f"/event/{e1}", "title": {"$regex": "^Locked in"},
                                        "created_at": {"$gte": since}})
        assert ln is not None and "2 votes, voting closed" in ln["body"], ln
        # voting after auto-lock rejected
        assert requests.post(f"{API}/events/{e1}/poll/{o1[0]['option_id']}/vote", headers=EMP).status_code == 400


# ---- Referral map radius
class TestMapRadius:
    def test_create_partners(self):
        for n, a in [("TEST_R6027", "Joondalup WA 6027"), ("TEST_R6030", "Quinns Rocks WA 6030"), ("TEST_R6100", "Burswood WA 6100")]:
            r = requests.post(f"{API}/directory", json={"space": "therapist", "category": REF, "name": n, "address": a,
                                                         "services": "OT"}, headers=ADMIN)
            assert r.status_code == 200, r.text
            STATE["ids"].append(r.json()["entry_id"])
        deadline = time.time() + 25
        while time.time() < deadline:
            docs = list(db.directory.find({"entry_id": {"$in": STATE["ids"]}}, {"_id": 0, "geo": 1}))
            if all((d.get("geo") or {}).get("lat") is not None for d in docs):
                break
            time.sleep(1.5)
        assert all((d.get("geo") or {}).get("lat") is not None for d in docs), docs

    @pytest.mark.parametrize("radius,expected", [(0, 1), (10, 2), (50, 2), (100, 3), (None, 3)])
    def test_radius(self, radius, expected):
        params = {"token": "test_session_admin", "postcode": "6027"}
        if radius is not None:
            params["radius"] = radius
        r = requests.get(f"{API}/referral-map", params=params, timeout=60)
        assert r.status_code == 200
        assert r.headers["X-Map-Pins"] == str(expected), (radius, r.headers["X-Map-Pins"])
        if radius == 0:
            assert "TEST_R6027" in r.text and "TEST_R6030" not in r.text

    def test_no_match_note(self):
        r = requests.get(f"{API}/referral-map", params={"token": "test_session_admin", "postcode": "6500", "radius": 10}, timeout=60)
        assert r.status_code == 200 and r.headers["X-Map-Pins"] == "0"
        assert "No referral partners in this range. Try Wider or All." in r.text

    def test_radius_without_postcode_shows_all(self):
        r = requests.get(f"{API}/referral-map", params={"token": "test_session_admin", "radius": 0}, timeout=60)
        assert r.status_code == 200 and r.headers["X-Map-Pins"] == "3"
