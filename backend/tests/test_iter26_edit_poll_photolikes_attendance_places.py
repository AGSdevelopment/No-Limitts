# Iteration 26: event edit + notify, polls (date/venue) vote/lock, photo likes & comments, attendance, AGTS places.
# ONLY touches hidden test users (user_testemp001, user_testadmin01 + a temp TEST_ user). Run serially: pytest -n 0
import os
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
            if line.startswith(("EXPO_PUBLIC_BACKEND_URL=", "EXPO_BACKEND_URL=")):
                url = line.split("=", 1)[1].strip().strip('"')
                break
    return url.rstrip("/")


BASE_URL = _base()
ADMIN = {"Authorization": "Bearer test_session_admin"}
EMP = {"Authorization": "Bearer test_session_employee"}
C_TOKEN = "TEST_session_evt26c"
CUSR = {"Authorization": f"Bearer {C_TOKEN}"}
EMP_ID, ADMIN_ID, C_ID = "user_testemp001", "user_testadmin01", "TEST_user_evt26c"
mdb = MongoClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]
FUTURE = (date.today() + timedelta(days=20)).isoformat()
S = requests.Session()


def _clean():
    mdb.events.delete_many({"title": {"$regex": "^TEST_evt26"}})
    mdb.notifications.delete_many({"$or": [{"body": {"$regex": "TEST_evt26"}}, {"title": {"$regex": "TEST_evt26"}}]})
    mdb.places.delete_many({"name": {"$regex": "^TEST_plc26", "$options": "i"}})
    mdb.users.delete_many({"user_id": C_ID})
    mdb.user_sessions.delete_many({"session_token": C_TOKEN})


@pytest.fixture(scope="module", autouse=True)
def setup():
    _clean()
    mdb.users.insert_one({"user_id": C_ID, "name": "Testc Evt26", "email": "evt26c@example.com", "role": "employee",
                          "hidden": True, "created_at": datetime.now(timezone.utc).isoformat()})
    mdb.user_sessions.insert_one({"session_token": C_TOKEN, "user_id": C_ID,
                                  "expires_at": datetime.now(timezone.utc) + timedelta(days=1)})
    yield
    _clean()


def api(method, path, h, **kw):
    return S.request(method, f"{BASE_URL}/api{path}", headers=h, timeout=30, **kw)


def create(h, **kw):
    body = {"title": kw.pop("title", "TEST_evt26 event"), "date": kw.pop("date", FUTURE), **kw}
    r = api("POST", "/events", h, json=body)
    assert r.status_code == 200, r.text
    return r.json()


def rsvp(eid, h, status="going"):
    return api("POST", f"/events/{eid}/rsvp", h, json={"status": status, "comment": ""})


def notes(uid, text):
    return list(mdb.notifications.find({"user_id": uid, "title": {"$regex": text}}, {"_id": 0}))


# ---- Edit event
class TestEdit:
    def test_non_organiser_forbidden(self):
        ev = create(EMP, title="TEST_evt26 edit403")
        r = api("PATCH", f"/events/{ev['event_id']}", CUSR, json={"title": "TEST_evt26 hacked"})
        assert r.status_code == 403
        # admin can edit
        r = api("PATCH", f"/events/{ev['event_id']}", ADMIN, json={"location": "Admin place"})
        assert r.status_code == 200 and r.json()["location"] == "Admin place"

    def test_edit_notifies_responders_not_editor(self):
        ev = create(EMP, title="TEST_evt26 editnotify")
        eid = ev["event_id"]
        assert rsvp(eid, CUSR, "maybe").status_code == 200
        assert rsvp(eid, EMP, "going").status_code == 200
        r = api("PATCH", f"/events/{eid}", EMP, json={"title": "TEST_evt26 editnotify2", "location": "Kings Park"})
        assert r.status_code == 200, r.text
        d = r.json()
        assert d["title"] == "TEST_evt26 editnotify2" and d["location"] == "Kings Park"
        g = api("GET", f"/events/{eid}", EMP).json()
        assert g["title"] == "TEST_evt26 editnotify2" and g["location"] == "Kings Park"
        n = notes(C_ID, "TEST_evt26 editnotify2 has changed")
        assert len(n) == 1 and "name" in n[0]["body"] and "location" in n[0]["body"]
        assert notes(EMP_ID, "editnotify2 has changed") == []
        # no-op edit -> no extra notification
        api("PATCH", f"/events/{eid}", EMP, json={"location": "Kings Park"})
        assert len(notes(C_ID, "TEST_evt26 editnotify2 has changed")) == 1

    def test_validation(self):
        eid = create(EMP, title="TEST_evt26 editval")["event_id"]
        assert api("PATCH", f"/events/{eid}", EMP, json={"title": "  "}).status_code == 400
        assert api("PATCH", f"/events/{eid}", EMP, json={"date": "12-12-2026"}).status_code == 400
        assert api("PATCH", f"/events/{eid}", EMP, json={"capacity": 0}).status_code == 400
        assert api("PATCH", f"/events/{eid}", EMP, json={"catering": "Pizza"}).status_code == 400
        assert api("PATCH", "/events/evt_nope", EMP, json={"title": "x"}).status_code == 404

    def test_raise_capacity_promotes_waitlist(self):
        eid = create(EMP, title="TEST_evt26 cap", capacity=1)["event_id"]
        rsvp(eid, EMP, "going")
        assert rsvp(eid, CUSR, "going").json()["waitlisted"] is True
        d = api("PATCH", f"/events/{eid}", EMP, json={"capacity": 2}).json()
        assert d["capacity"] == 2 and d["counts"]["going"] == 2 and d["counts"]["waitlist"] == 0
        assert len(notes(C_ID, "off the waitlist")) >= 1

    def test_clear_capacity_promotes_all(self):
        eid = create(EMP, title="TEST_evt26 clearcap", capacity=1)["event_id"]
        rsvp(eid, EMP, "going")
        rsvp(eid, CUSR, "going")
        rsvp(eid, ADMIN, "going")
        assert api("GET", f"/events/{eid}", EMP).json()["counts"]["waitlist"] == 2
        d = api("PATCH", f"/events/{eid}", EMP, json={"clear_capacity": True}).json()
        assert d["capacity"] is None and d["counts"]["going"] == 3 and d["counts"]["waitlist"] == 0
        assert mdb.events.find_one({"event_id": eid})["capacity"] is None

    def test_date_change_resets_reminded_for(self):
        eid = create(EMP, title="TEST_evt26 remind")["event_id"]
        mdb.events.update_one({"event_id": eid}, {"$set": {"reminded_for": FUTURE}})
        new = (date.today() + timedelta(days=25)).isoformat()
        d = api("PATCH", f"/events/{eid}", EMP, json={"date": new}).json()
        assert d["date"] == new
        assert mdb.events.find_one({"event_id": eid}).get("reminded_for") is None


# ---- Polls
class TestPoll:
    def test_poll_validation_and_permissions(self):
        eid = create(EMP, title="TEST_evt26 pollval")["event_id"]
        assert api("POST", f"/events/{eid}/poll", CUSR, json={"kind": "venue", "options": ["A", "B"]}).status_code == 403
        assert api("POST", f"/events/{eid}/poll", EMP, json={"kind": "time", "options": ["A", "B"]}).status_code == 400
        assert api("POST", f"/events/{eid}/poll", EMP, json={"kind": "venue", "options": ["A"]}).status_code == 400
        assert api("POST", f"/events/{eid}/poll", EMP, json={"kind": "venue", "options": list("ABCDEFG")}).status_code == 400
        assert api("POST", f"/events/{eid}/poll", EMP,
                   json={"kind": "date", "options": ["12-12-2026", "13-12-2026"]}).status_code == 400

    def test_date_poll_vote_lock(self):
        eid = create(EMP, title="TEST_evt26 datepoll")["event_id"]
        d1, d2 = (date.today() + timedelta(days=30)).isoformat(), (date.today() + timedelta(days=31)).isoformat()
        r = api("POST", f"/events/{eid}/poll", EMP, json={"kind": "date", "options": [d1, d2]})
        assert r.status_code == 200, r.text
        p = r.json()["poll"]
        assert p["kind"] == "date" and not p["closed"] and [o["label"] for o in p["options"]] == [d1, d2]
        assert len(notes(C_ID, "Vote: TEST_evt26 datepoll")) == 1
        o1 = p["options"][1]["option_id"]
        v = api("POST", f"/events/{eid}/poll/{o1}/vote", CUSR).json()["poll"]["options"][1]
        assert v["votes"] == 1 and v["voted"] is True and v["voters"] == ["Testc Evt26"]
        # toggle off then on again
        v = api("POST", f"/events/{eid}/poll/{o1}/vote", CUSR).json()["poll"]["options"][1]
        assert v["votes"] == 0 and v["voted"] is False and v["voters"] == []
        api("POST", f"/events/{eid}/poll/{o1}/vote", CUSR)
        # voter sees voted=False from another user's view
        g = api("GET", f"/events/{eid}", EMP).json()["poll"]["options"][1]
        assert g["votes"] == 1 and g["voted"] is False
        assert api("POST", f"/events/{eid}/poll/{o1}/lock", CUSR).status_code == 403
        mdb.events.update_one({"event_id": eid}, {"$set": {"reminded_for": FUTURE}})
        lk = api("POST", f"/events/{eid}/poll/{o1}/lock", EMP)
        assert lk.status_code == 200, lk.text
        d = lk.json()
        assert d["date"] == d2 and d["poll"]["closed"] is True and d["poll"]["locked_option_id"] == o1
        assert mdb.events.find_one({"event_id": eid}).get("reminded_for") is None
        assert len(notes(C_ID, "Locked in: TEST_evt26 datepoll")) == 1
        assert api("POST", f"/events/{eid}/poll/{o1}/vote", CUSR).status_code == 400
        assert api("POST", f"/events/{eid}/poll/opt_nope/vote", CUSR).status_code == 404

    def test_venue_poll_lock_sets_location(self):
        eid = create(EMP, title="TEST_evt26 venuepoll", location="TBC")["event_id"]
        p = api("POST", f"/events/{eid}/poll", EMP, json={"kind": "venue", "options": ["The Royal", "The Royal", "Kings Park"]}).json()["poll"]
        assert [o["label"] for o in p["options"]] == ["The Royal", "Kings Park"]  # duplicates collapsed
        d = api("POST", f"/events/{eid}/poll/{p['options'][1]['option_id']}/lock", EMP).json()
        assert d["location"] == "Kings Park" and d["poll"]["closed"] is True
        assert api("GET", f"/events/{eid}", CUSR).json()["location"] == "Kings Park"


# ---- Photo likes & comments (photo inserted directly; upload path covered in iter 24)
class TestPhotoSocial:
    def test_like_and_comment(self):
        eid = create(EMP, title="TEST_evt26 photos")["event_id"]
        mdb.events.update_one({"event_id": eid}, {"$push": {"photos": {
            "photo_id": "pho_test26", "storage_path": "x/none.png", "content_type": "image/png", "user_id": EMP_ID,
            "name": "Erin Employee", "created_at": datetime.now(timezone.utc).isoformat()}}})
        g = api("GET", f"/events/{eid}", CUSR).json()["photos"][0]
        assert g["like_count"] == 0 and g["liked"] is False and g["comments"] == [] and "storage_path" not in g
        r = api("POST", f"/events/{eid}/photos/pho_test26/like", CUSR).json()
        assert r == {"liked": True, "like_count": 1}
        g = api("GET", f"/events/{eid}", CUSR).json()["photos"][0]
        assert g["like_count"] == 1 and g["liked"] is True and "likes" not in g
        assert api("GET", f"/events/{eid}", ADMIN).json()["photos"][0]["liked"] is False
        assert len(list(mdb.notifications.find({"user_id": EMP_ID, "title": {"$regex": "liked your photo"},
                                                "body": "TEST_evt26 photos"}))) == 1
        assert api("POST", f"/events/{eid}/photos/pho_test26/like", CUSR).json() == {"liked": False, "like_count": 0}
        c = api("POST", f"/events/{eid}/photos/pho_test26/comments", CUSR, json={"text": " Great TEST_evt26 shot "})
        assert c.status_code == 200 and c.json()["text"] == "Great TEST_evt26 shot"
        g = api("GET", f"/events/{eid}", EMP).json()["photos"][0]
        assert len(g["comments"]) == 1 and g["comments"][0]["name"] == "Testc Evt26"
        assert api("POST", f"/events/{eid}/photos/pho_test26/comments", CUSR, json={"text": "  "}).status_code == 400
        assert api("POST", f"/events/{eid}/photos/pho_nope/like", CUSR).status_code == 404


# ---- Attendance
class TestAttendance:
    def test_future_event_rejected(self):
        eid = create(EMP, title="TEST_evt26 attfuture")["event_id"]
        assert api("PUT", f"/events/{eid}/attendance", EMP, json={"user_ids": [EMP_ID]}).status_code == 400

    def test_past_event_attendance_and_profile(self):
        eid = create(EMP, title="TEST_evt26 attpast")["event_id"]
        rsvp(eid, CUSR, "going")
        yday = (date.today() - timedelta(days=2)).isoformat()
        assert api("PATCH", f"/events/{eid}", EMP, json={"date": yday}).status_code == 400  # past dates blocked
        mdb.events.update_one({"event_id": eid}, {"$set": {"date": yday}})
        assert api("PUT", f"/events/{eid}/attendance", CUSR, json={"user_ids": [C_ID]}).status_code == 403
        r = api("PUT", f"/events/{eid}/attendance", EMP, json={"user_ids": [C_ID, C_ID, "user_bogus"]})
        assert r.status_code == 200, r.text
        assert r.json()["attended"] == [{"user_id": C_ID, "name": "Testc Evt26"}]
        assert api("GET", f"/events/{eid}", CUSR).json()["attended"] == [{"user_id": C_ID, "name": "Testc Evt26"}]
        prof = api("GET", f"/staff/{C_ID}/profile", ADMIN)
        assert prof.status_code == 200, prof.text
        ea = prof.json()["events_attended"]
        assert any(e["event_id"] == eid and e["date"] == yday for e in ea)


# ---- AGTS favourite places
class TestPlaces:
    def test_crud_like_permissions(self):
        assert api("POST", "/places", CUSR, json={"name": "  "}).status_code == 400
        assert api("POST", "/places", CUSR, json={"name": "TEST_plc26 X", "kind": "Coffee"}).status_code == 400
        r = api("POST", "/places", CUSR, json={"name": "TEST_plc26 Cafe", "kind": "Eat", "link": "example.com/cafe",
                                               "address": "Fremantle", "note": "Good"})
        assert r.status_code == 200, r.text
        p = r.json()
        assert p["link"] == "https://example.com/cafe" and p["kind"] == "Eat" and p["like_count"] == 0 and "_id" not in p
        assert api("POST", "/places", EMP, json={"name": "test_plc26 cafe"}).status_code == 409
        lst = api("GET", "/places", EMP).json()
        mine = next(x for x in lst if x["place_id"] == p["place_id"])
        assert mine["can_delete"] is False and mine["liked"] is False and "likes" not in mine
        assert api("POST", f"/places/{p['place_id']}/like", EMP).json() == {"liked": True}
        mine = next(x for x in api("GET", "/places", EMP).json() if x["place_id"] == p["place_id"])
        assert mine["liked"] is True and mine["like_count"] == 1
        assert api("POST", f"/places/{p['place_id']}/like", EMP).json() == {"liked": False}
        assert api("DELETE", f"/places/{p['place_id']}", EMP).status_code == 404
        assert api("DELETE", f"/places/{p['place_id']}", CUSR).status_code == 200
        assert all(x["place_id"] != p["place_id"] for x in api("GET", "/places", EMP).json())

    def test_admin_can_delete_and_http_link_kept(self):
        p = api("POST", "/places", CUSR, json={"name": "TEST_plc26 Bar", "kind": "Drink", "link": "http://bar.au"}).json()
        assert p["link"] == "http://bar.au"
        assert api("DELETE", f"/places/{p['place_id']}", ADMIN).status_code == 200
        assert api("POST", "/places/plc_nope/like", EMP).status_code == 404
