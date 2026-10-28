# Iteration 20: check-in notes & outcome, Google Calendar connection (no OAuth completion), calendar helpers,
# monthly cert reminder loop, "required for your role" expiry warning, Pronathi restore.
# NEVER calls /compliance/remind-certificates without preview=true (would email real staff).
# Run serially: pytest -n 0
import asyncio
import os
import sys
import uuid
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import parse_qs, urlparse

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
def state():
    reqs0 = mdb.meta.find_one({"key": "cert_requirements"}, {"_id": 0})
    yield
    mdb.meta.update_one({"key": "cert_requirements"}, {"$set": {"groups": (reqs0 or {}).get("groups", {})}},
                        upsert=True)
    mdb.users.update_one({"user_id": EMP_ID}, {"$set": {"hidden": True, "staff_group": None}})
    mdb.events.delete_many({"checkin_for": EMP_ID})
    mdb.certificates.delete_many({"owner_id": EMP_ID, "title": {"$regex": "^TEST_"}})
    mdb.notifications.delete_many({"user_id": {"$in": [EMP_ID, ADMIN_ID]}, "created_at": {"$gte": START}})
    mdb.oauth_states.delete_many({"user_id": ADMIN_ID, "kind": "google-calendar"})


def book(h=ADMIN, **kw):
    body = {"date": TOMORROW, "time": "10am", "location": "TEST room", "note": "TEST note", **kw}
    return requests.post(f"{BASE_URL}/api/starter-checklist/user/{EMP_ID}/checkin", headers=h, json=body, timeout=30)


def put_notes(eid, body, h=ADMIN, uid=EMP_ID):
    return requests.put(f"{BASE_URL}/api/starter-checklist/user/{uid}/checkin/{eid}/notes", headers=h, json=body,
                        timeout=30)


# ---------- Check-in booking + notes ----------
class TestCheckinNotes:
    def test_book_not_connected_and_organizer(self):
        r = book()
        assert r.status_code == 200, r.text
        d = r.json()
        assert d["calendar"] == "not_connected"
        assert d["organizer_id"] == ADMIN_ID and d["notes"] == "" and d["outcome"] == ""
        ev = mdb.events.find_one({"event_id": d["event_id"]})
        assert ev["organizer_id"] == ADMIN_ID and ev["calendar"] == "not_connected"
        TestCheckinNotes.eid = d["event_id"]

    def test_notes_save_and_persist(self):
        r = put_notes(self.eid, {"notes": "  TEST discussed goals  ", "outcome": "Needs support"})
        assert r.status_code == 200, r.text
        d = r.json()
        assert d["notes"] == "TEST discussed goals" and d["outcome"] == "Needs support"
        assert d["notes_by"] and d["notes_at"] and "_id" not in d and "attendees" not in d
        g = requests.get(f"{BASE_URL}/api/starter-checklist/user/{EMP_ID}", headers=ADMIN, timeout=30).json()
        c = next(c for c in g["checkins"] if c["event_id"] == self.eid)
        assert c["notes"] == "TEST discussed goals" and c["outcome"] == "Needs support"
        assert c["notes_by"] == d["notes_by"] and c["notes_at"] == d["notes_at"]

    @pytest.mark.parametrize("outcome", ["", "On track", "Follow-up needed"])
    def test_valid_outcomes(self, outcome):
        r = put_notes(self.eid, {"notes": "TEST n", "outcome": outcome})
        assert r.status_code == 200 and r.json()["outcome"] == outcome

    def test_bad_outcome_400(self):
        assert put_notes(self.eid, {"notes": "x", "outcome": "Great"}).status_code == 400

    def test_employee_403(self):
        assert put_notes(self.eid, {"notes": "x", "outcome": ""}, h=EMP).status_code == 403

    def test_unknown_event_404(self):
        assert put_notes("evt_nope_" + uuid.uuid4().hex[:6], {"notes": "x", "outcome": ""}).status_code == 404

    def test_wrong_user_404(self):
        assert put_notes(self.eid, {"notes": "x", "outcome": ""}, uid=ADMIN_ID).status_code == 404

    def test_notes_not_leaked_to_employee_events(self):
        """Notes are 'only admins see these' - the staff member's GET /api/events must not include them."""
        put_notes(self.eid, {"notes": "TEST private admin note", "outcome": "Needs support"})
        evs = requests.get(f"{BASE_URL}/api/events", headers=EMP, timeout=30).json()
        ev = next((e for e in evs if e["event_id"] == self.eid), None)
        assert ev is not None, "employee should see their own check-in"
        leaked = {k: ev.get(k) for k in ("notes", "outcome", "notes_by") if ev.get(k)}
        assert not leaked, f"Admin-only check-in notes leaked to employee via /api/events: {leaked}"

    def test_delete_still_works(self):
        r = requests.delete(f"{BASE_URL}/api/starter-checklist/user/{EMP_ID}/checkin/{self.eid}", headers=ADMIN,
                            timeout=30)
        assert r.status_code == 200 and r.json()["ok"] is True
        assert mdb.events.find_one({"event_id": self.eid}) is None
        assert put_notes(self.eid, {"notes": "x", "outcome": ""}).status_code == 404


# ---------- Google Calendar integration (do NOT complete OAuth) ----------
class TestGoogleCalendar:
    def test_status_admin(self):
        r = requests.get(f"{BASE_URL}/api/integrations/google-calendar/status", headers=ADMIN, timeout=30)
        assert r.status_code == 200, r.text
        d = r.json()
        assert d["configured"] is True and d["connected"] is False
        assert d["redirect_uri"].endswith("/api/integrations/google-calendar/callback")

    def test_status_employee_403(self):
        r = requests.get(f"{BASE_URL}/api/integrations/google-calendar/status", headers=EMP, timeout=30)
        assert r.status_code == 403

    def test_start_returns_google_url(self):
        r = requests.post(f"{BASE_URL}/api/integrations/google-calendar/start", headers=ADMIN, timeout=30)
        assert r.status_code == 200, r.text  # socials /integrations/{kind}/start would 404 "Unknown integration"
        url = r.json()["authorization_url"]
        u = urlparse(url)
        q = parse_qs(u.query)
        assert u.netloc == "accounts.google.com"
        assert "https://www.googleapis.com/auth/calendar.events" in q["scope"][0]
        assert q["redirect_uri"][0].endswith("/api/integrations/google-calendar/callback")
        assert q["access_type"][0] == "offline"
        assert mdb.oauth_states.find_one({"state": q["state"][0], "kind": "google-calendar"})

    def test_start_employee_403(self):
        assert requests.post(f"{BASE_URL}/api/integrations/google-calendar/start", headers=EMP,
                             timeout=30).status_code == 403

    def test_callback_bad_state(self):
        r = requests.get(f"{BASE_URL}/api/integrations/google-calendar/callback",
                         params={"state": "bad", "code": "x"}, timeout=30)
        assert r.status_code == 200 and "Google Calendar not connected" in r.text


# ---------- Calendar helpers (unit) ----------
def test_parse_time():
    from routes.calendar import parse_time
    assert parse_time("10am") == (10, 0)
    assert parse_time("2:30 pm") == (14, 30)
    assert parse_time("noon") is None
    assert parse_time("12pm") == (12, 0) and parse_time("12am") == (0, 0)
    assert parse_time("14:00") == (14, 0) and parse_time("") is None


def test_event_body():
    from routes.calendar import event_body
    ev = {"title": "Check-in", "date": "2026-03-02", "time": "2:30 pm", "description": "d", "location": "l"}
    b = event_body(ev, "a@b.com")
    assert b["start"]["timeZone"] == "Australia/Perth"
    assert b["start"]["dateTime"].startswith("2026-03-02T14:30:00+08:00")
    assert b["end"]["dateTime"].startswith("2026-03-02T15:00:00+08:00")
    assert b["attendees"] == [{"email": "a@b.com"}]
    b2 = event_body({**ev, "time": "sometime"}, "a@b.com")
    assert b2["start"] == {"date": "2026-03-02"} and b2["end"] == {"date": "2026-03-03"}


# ---------- Monthly cert reminders ----------
def test_cert_reminder_loop_registered():
    import inspect
    import routes.compliance as rc
    assert inspect.iscoroutinefunction(rc.cert_reminder_loop)
    src = Path("/app/backend/server.py").read_text()
    assert "asyncio.create_task(cert_reminder_loop())" in src


def test_remind_preview_only():
    r = requests.post(f"{BASE_URL}/api/compliance/remind-certificates", params={"preview": "true"}, headers=ADMIN,
                      timeout=60)
    assert r.status_code == 200 and r.json()["reminded"] == 0 and isinstance(r.json()["would_remind"], int)


# ---------- Required-for-your-role expiry warning ----------
def _run_check(cert_title, req_names):
    import routes.certificates as rcert
    from motor.motor_asyncio import AsyncIOMotorClient
    notes, sent = [], []

    async def fake_notify(uids, ntype, title, body, link=""):
        notes.append(body)

    async def fake_email(**kw):
        sent.append(kw)

    async def run():
        db = AsyncIOMotorClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]
        orig = rcert.notify, rcert.send_email, rcert.db
        rcert.notify, rcert.send_email, rcert.db = fake_notify, fake_email, db
        cert = {"cert_id": "cert_TEST_" + uuid.uuid4().hex[:8], "owner_id": EMP_ID, "title": cert_title,
                "expiry_date": (date.today() + timedelta(days=10)).isoformat(), "is_deleted": False,
                "created_at": START}
        try:
            await db.users.update_one({"user_id": EMP_ID}, {"$set": {"staff_group": "support_office"}})
            await db.meta.update_one({"key": "cert_requirements"},
                                     {"$set": {"groups": {"support_office": req_names}}}, upsert=True)
            await db.certificates.insert_one(dict(cert))
            await rcert.check_certificate(cert)
        finally:
            rcert.notify, rcert.send_email, rcert.db = orig
            await db.certificates.delete_one({"cert_id": cert["cert_id"]})
            await db.users.update_one({"user_id": EMP_ID}, {"$set": {"staff_group": None, "hidden": True}})

    asyncio.run(run())
    return notes, sent


def test_required_cert_expiry_message():
    notes, sent = _run_check("TEST_First Aid Level 2", ["test_first aid"])
    assert len(notes) == 1 and "required for your role" in notes[0], notes
    assert "expires in 10 days" in notes[0]
    assert len(sent) == 1 and sent[0]["to"] == "emp.test@example.com"  # mocked


def test_non_required_cert_expiry_message():
    notes, _ = _run_check("TEST_Forklift", ["test_first aid"])
    assert len(notes) == 1 and "required for your role" not in notes[0], notes


# ---------- Pronathi restored ----------
def test_pronathi_admin_support_office():
    users = requests.get(f"{BASE_URL}/api/users", headers=ADMIN, timeout=30).json()
    p = next((u for u in users if u.get("email") == "pronathi@aspireandgrow.com.au"), None)
    assert p is not None
    assert p["role"] == "admin" and p["staff_group"] == "support_office"
