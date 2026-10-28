# Iteration 25: recurring events (series), capacity + waitlist auto-promotion, event comments, dashboard photo highlights.
# ONLY touches hidden test users (user_testemp001, user_testadmin01 + a temp TEST_ user). Run serially: pytest -n 0
import os
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pytest
import requests
from dotenv import load_dotenv
from pymongo import MongoClient

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
C_TOKEN = "TEST_session_evt25c"
CUSR = {"Authorization": f"Bearer {C_TOKEN}"}
EMP_ID, ADMIN_ID, C_ID = "user_testemp001", "user_testadmin01", "TEST_user_evt25c"
mdb = MongoClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]
FUTURE = (date.today() + timedelta(days=20)).isoformat()
PNG = (b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15\xc4\x89"
       b"\x00\x00\x00\rIDATx\x9cc\xf8\x0f\x00\x00\x01\x01\x00\x05\x18\xd8N\x00\x00\x00\x00IEND\xaeB`\x82")


def _clean():
    mdb.events.delete_many({"title": {"$regex": "^TEST_evt25"}})
    mdb.notifications.delete_many({"$or": [{"body": {"$regex": "TEST_(evt25|cmt25)"}},
                                           {"title": {"$regex": "TEST_evt25"}}]})
    mdb.users.delete_many({"user_id": C_ID})
    mdb.user_sessions.delete_many({"session_token": C_TOKEN})


@pytest.fixture(scope="module", autouse=True)
def setup():
    _clean()
    mdb.users.insert_one({"user_id": C_ID, "name": "Testc Evt25", "email": "evt25c@example.com", "role": "employee",
                          "hidden": True, "created_at": datetime.now(timezone.utc).isoformat()})
    mdb.user_sessions.insert_one({"session_token": C_TOKEN, "user_id": C_ID,
                                  "expires_at": datetime.now(timezone.utc) + timedelta(days=1)})
    yield
    _clean()


def create(h, **kw):
    body = {"title": kw.pop("title", "TEST_evt25 event"), "date": kw.pop("date", FUTURE), **kw}
    return requests.post(f"{BASE_URL}/api/events", json=body, headers=h, timeout=30)


def rsvp(eid, h, status="going", comment=""):
    return requests.post(f"{BASE_URL}/api/events/{eid}/rsvp", json={"status": status, "comment": comment}, headers=h,
                         timeout=30)


def get(eid, h=ADMIN):
    return requests.get(f"{BASE_URL}/api/events/{eid}", headers=h, timeout=30)


def series_docs(sid):
    return list(mdb.events.find({"series_id": sid}, {"_id": 0}).sort("date", 1))


# ---- Recurring events
class TestSeries:
    def test_weekly_three(self):
        r = create(ADMIN, title="TEST_evt25 weekly", repeat="weekly", occurrences=3, capacity=5)
        assert r.status_code == 200, r.text
        d = r.json()
        assert d["created"] == 3 and d["series_id"] and d["capacity"] == 5 and d["repeat"] == "weekly"
        docs = series_docs(d["series_id"])
        assert [x["date"] for x in docs] == [(date.fromisoformat(FUTURE) + timedelta(days=7 * i)).isoformat()
                                            for i in range(3)]
        assert all(x["capacity"] == 5 for x in docs)

    def test_fortnightly(self):
        d = create(ADMIN, title="TEST_evt25 fortnight", repeat="fortnightly", occurrences=2).json()
        assert d["created"] == 2
        assert [x["date"] for x in series_docs(d["series_id"])] == [
            FUTURE, (date.fromisoformat(FUTURE) + timedelta(days=14)).isoformat()]

    def test_monthly_jan31(self):
        y = date.today().year + 1
        d = create(ADMIN, title="TEST_evt25 monthly", date=f"{y}-01-31", repeat="monthly", occurrences=3).json()
        assert d["created"] == 3
        assert [x["date"] for x in series_docs(d["series_id"])] == [f"{y}-01-31", f"{y}-02-28", f"{y}-03-31"]

    def test_single_no_series(self):
        d = create(ADMIN, title="TEST_evt25 single", occurrences=5).json()
        assert d["created"] == 1 and d["series_id"] is None

    def test_occurrences_clamped(self):
        d = create(ADMIN, title="TEST_evt25 clamp", repeat="weekly", occurrences=40).json()
        assert d["created"] == 12

    def test_validation(self):
        assert create(ADMIN, title="TEST_evt25 bad", repeat="daily").status_code == 400
        assert create(ADMIN, title="TEST_evt25 bad", capacity=0).status_code == 400
        assert mdb.events.count_documents({"title": "TEST_evt25 bad"}) == 0

    def test_one_notification_per_series(self):
        d = create(ADMIN, title="TEST_evt25 notifyonce", repeat="weekly", occurrences=4).json()
        n = list(mdb.notifications.find({"user_id": EMP_ID, "body": {"$regex": "TEST_evt25 notifyonce"}}, {"_id": 0}))
        assert len(n) == 1 and "3 more" in n[0]["body"] and n[0]["link"] == f"/event/{d['event_id']}"

    def test_delete_series_from_middle(self):
        d = create(EMP, title="TEST_evt25 delser", repeat="weekly", occurrences=4).json()
        docs = series_docs(d["series_id"])
        # other employee cannot delete
        assert requests.delete(f"{BASE_URL}/api/events/{docs[1]['event_id']}?series=true", headers=CUSR).status_code == 403
        r = requests.delete(f"{BASE_URL}/api/events/{docs[1]['event_id']}?series=true", headers=EMP)
        assert r.status_code == 200
        left = series_docs(d["series_id"])
        assert [x["event_id"] for x in left] == [docs[0]["event_id"]]
        # without series flag only one goes
        d2 = create(EMP, title="TEST_evt25 delone", repeat="weekly", occurrences=3).json()
        requests.delete(f"{BASE_URL}/api/events/{d2['event_id']}", headers=EMP)
        assert len(series_docs(d2["series_id"])) == 2


# ---- Waitlist
class TestWaitlist:
    def test_waitlist_and_promotion(self):
        eid = create(EMP, title="TEST_evt25 wl", capacity=1).json()["event_id"]
        a = rsvp(eid, EMP).json()
        assert a["going"] and a["my_rsvp"]["status"] == "going" and a["places_left"] == 0
        b = rsvp(eid, ADMIN).json()
        assert b["waitlisted"] is True and b["my_rsvp"]["status"] == "waitlist"
        assert b["counts"]["waitlist"] == 1 and b["places_left"] == 0 and b["counts"]["going"] == 1
        time.sleep(0.05)
        c = rsvp(eid, CUSR).json()
        assert c["waitlisted"] and c["counts"]["waitlist"] == 2
        # waitlisted admin re-sends going with a comment: keeps queue position
        at_before = b["my_rsvp"]["at"]
        b2 = rsvp(eid, ADMIN, "going", "TEST_evt25 lift pls").json()
        assert b2["my_rsvp"]["status"] == "waitlist" and b2["my_rsvp"]["at"] == at_before
        # A drops out -> admin (first in queue) promoted
        rsvp(eid, EMP, "not_going")
        ev = get(eid).json()
        st = {r["user_id"]: r["status"] for r in ev["rsvps"]}
        assert st[ADMIN_ID] == "going" and st[C_ID] == "waitlist" and st[EMP_ID] == "not_going"
        assert mdb.notifications.count_documents({"user_id": ADMIN_ID, "title": "You're off the waitlist!",
                                                  "link": f"/event/{eid}"}) == 1
        # admin withdraws -> C promoted
        rsvp(eid, ADMIN, None)
        ev = get(eid).json()
        st = {r["user_id"]: r["status"] for r in ev["rsvps"]}
        assert ADMIN_ID not in st and st[C_ID] == "going" and ev["counts"]["waitlist"] == 0
        assert mdb.notifications.count_documents({"user_id": C_ID, "title": "You're off the waitlist!"}) == 1

    def test_legacy_toggle_respects_capacity(self):
        eid = create(EMP, title="TEST_evt25 toggle", capacity=1).json()["event_id"]
        t = lambda h: requests.post(f"{BASE_URL}/api/events/{eid}/rsvp", headers=h, timeout=30).json()
        assert t(EMP)["going"] is True
        r = t(ADMIN)
        assert r["waitlisted"] is True and r["counts"]["going"] == 1
        assert t(EMP)["going"] is False  # toggle off frees place
        st = {r["user_id"]: r["status"] for r in get(eid).json()["rsvps"]}
        assert st == {ADMIN_ID: "going"}

    def test_legacy_toggle_can_leave_waitlist(self):
        """Toggling again while waitlisted should remove the reply (it currently re-adds to the waitlist)."""
        eid = create(EMP, title="TEST_evt25 toggle2", capacity=1).json()["event_id"]
        t = lambda h: requests.post(f"{BASE_URL}/api/events/{eid}/rsvp", headers=h, timeout=30).json()
        t(EMP)
        assert t(ADMIN)["waitlisted"] is True
        r = t(ADMIN)
        assert r["my_rsvp"] is None, f"toggle left user on waitlist: {r['my_rsvp']}"

    def test_maybe_then_going_does_not_jump_queue(self):
        """Someone who answered Maybe earlier then switches to Going on a full event should join the END of the queue."""
        eid = create(EMP, title="TEST_evt25 jump", capacity=1).json()["event_id"]
        rsvp(eid, ADMIN, "maybe")
        time.sleep(0.05)
        rsvp(eid, EMP, "going")
        time.sleep(0.05)
        assert rsvp(eid, CUSR, "going").json()["waitlisted"]
        time.sleep(0.05)
        assert rsvp(eid, ADMIN, "going").json()["waitlisted"]
        rsvp(eid, EMP, "not_going")
        st = {r["user_id"]: r["status"] for r in get(eid).json()["rsvps"]}
        assert st[C_ID] == "going", f"queue jumped: {st}"

    def test_waitlist_status_rejected_by_api(self):
        """Frontend sends status='waitlist' when a waitlisted user taps 'Update RSVP' without choosing a chip."""
        eid = create(EMP, title="TEST_evt25 wlupd", capacity=1).json()["event_id"]
        rsvp(eid, EMP)
        rsvp(eid, ADMIN)
        r = rsvp(eid, ADMIN, "waitlist", "TEST_evt25 new comment")
        assert r.status_code == 200, f"{r.status_code} {r.text}"


# ---- Comments
class TestComments:
    def test_comment_flow(self):
        eid = create(ADMIN, title="TEST_evt25 chat").json()["event_id"]
        rsvp(eid, CUSR, "going")
        assert requests.post(f"{BASE_URL}/api/events/{eid}/comments", json={"text": "   "}, headers=EMP).status_code == 400
        r = requests.post(f"{BASE_URL}/api/events/{eid}/comments", json={"text": "TEST_cmt25 who can drive?"}, headers=EMP)
        assert r.status_code == 200, r.text
        c = r.json()
        assert c["comment_id"] and c["user_id"] == EMP_ID and c["text"] == "TEST_cmt25 who can drive?"
        ev = get(eid, EMP).json()
        assert [x["comment_id"] for x in ev["comments"]] == [c["comment_id"]]
        to = {n["user_id"] for n in mdb.notifications.find({"body": "TEST_cmt25 who can drive?"}, {"_id": 0})}
        assert ADMIN_ID in to and C_ID in to and EMP_ID not in to
        # other employee cannot delete; owner can
        u = f"{BASE_URL}/api/events/{eid}/comments/{c['comment_id']}"
        assert requests.delete(u, headers=CUSR).status_code == 404
        assert requests.delete(u, headers=EMP).status_code == 200
        assert get(eid).json()["comments"] == []
        # admin can delete someone else's comment
        c2 = requests.post(f"{BASE_URL}/api/events/{eid}/comments", json={"text": "TEST_cmt25 second"}, headers=CUSR).json()
        assert requests.delete(f"{BASE_URL}/api/events/{eid}/comments/{c2['comment_id']}", headers=ADMIN).status_code == 200
        assert requests.delete(f"{BASE_URL}/api/events/{eid}/comments/{c2['comment_id']}", headers=ADMIN).status_code == 404

    def test_checkin_and_missing_404(self):
        mdb.events.insert_one({"event_id": "evt_TEST25chk", "title": "TEST_evt25 checkin", "date": FUTURE,
                               "checkin_for": EMP_ID, "private_for": [EMP_ID, ADMIN_ID], "rsvps": [], "attendees": []})
        assert requests.post(f"{BASE_URL}/api/events/evt_TEST25chk/comments", json={"text": "TEST_cmt25 x"},
                             headers=EMP).status_code == 404
        assert requests.post(f"{BASE_URL}/api/events/evt_nope25/comments", json={"text": "TEST_cmt25 x"},
                             headers=EMP).status_code == 404


# ---- Dashboard photo highlights
class TestHighlights:
    def test_photo_highlights(self):
        eid = create(EMP, title="TEST_evt25 photos").json()["event_id"]
        up = lambda: requests.post(f"{BASE_URL}/api/events/{eid}/photos", headers=EMP,
                                   files={"file": ("p.png", PNG, "image/png")}, timeout=60)
        p1 = up()
        assert p1.status_code == 200, p1.text
        time.sleep(0.05)
        p2 = up().json()
        # private check-in event with a photo, visible only to admin
        mdb.events.insert_one({"event_id": "evt_TEST25priv", "title": "TEST_evt25 private", "date": FUTURE,
                               "checkin_for": ADMIN_ID, "private_for": [ADMIN_ID], "rsvps": [], "attendees": [],
                               "photos": [{"photo_id": "pho_TEST25priv", "storage_path": "x", "name": "x",
                                           "user_id": ADMIN_ID, "created_at": "2999-01-01T00:00:00+00:00"}]})
        h = requests.get(f"{BASE_URL}/api/dashboard", headers=EMP).json()["photo_highlights"]
        assert h[0]["photo_id"] == p2["photo_id"] and h[1]["photo_id"] == p1.json()["photo_id"]
        assert h[0]["event_id"] == eid and h[0]["event_title"] == "TEST_evt25 photos"
        assert "storage_path" not in h[0] and len(h) <= 8
        assert all(x["photo_id"] != "pho_TEST25priv" for x in h)
        times = [x["created_at"] for x in h]
        assert times == sorted(times, reverse=True)
