# Iteration 24: no-expiry resource upload, event reminder loop (in-process, mocked), event photos, .ics calendar file.
# ONLY touches hidden test users (user_testemp001, user_testadmin01). Run serially: pytest -n 0
# No drive_spaces are sent (no Drive writes). Reminder loop runs with notify/send_email mocked (no emails).
import asyncio
import os
import sys
from datetime import date, datetime, timedelta
from pathlib import Path
from unittest import mock

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
FUTURE = (date.today() + timedelta(days=20)).isoformat()
PDF = b"%PDF-1.4\n% TEST_upload24 tiny file\n"
PNG = (b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15\xc4\x89"
       b"\x00\x00\x00\rIDATx\x9cc\xf8\x0f\x00\x00\x01\x01\x00\x05\x18\xd8N\x00\x00\x00\x00IEND\xaeB`\x82")
STATE = {"events": []}


@pytest.fixture(scope="module", autouse=True)
def cleanup():
    yield
    mdb.cpd_resources.delete_many({"title": {"$regex": "^TEST_upload24"}})
    mdb.cpd_logs.delete_many({"title": {"$regex": "^TEST_upload24"}})
    mdb.events.delete_many({"event_id": {"$in": STATE["events"]}})
    mdb.events.delete_many({"title": {"$regex": "^TEST_evt24"}})
    mdb.notifications.delete_many({"body": {"$regex": "TEST_(evt24|upload24)"}})
    mdb.notifications.delete_many({"title": {"$regex": "TEST_(evt24|upload24)"}})


def upload(headers, **form):
    files = {"file": (form.pop("filename", "TEST_upload24.pdf"), PDF, form.pop("ctype", "application/pdf"))}
    return requests.post(f"{BASE_URL}/api/resources/upload", headers=headers, data=form, files=files, timeout=30)


def make_event(headers=EMP, **kw):
    body = {"title": "TEST_evt24 Party", "date": FUTURE, "time": "", "location": "Office", **kw}
    r = requests.post(f"{BASE_URL}/api/events", headers=headers, json=body, timeout=20)
    assert r.status_code == 200, r.text
    STATE["events"].append(r.json()["event_id"])
    return r.json()


# ---- POST /api/resources/upload
class TestResourceUpload:
    def test_no_destination_400(self):
        r = upload(EMP, title="TEST_upload24 none")
        assert r.status_code == 400 and r.json()["detail"] == "Choose where to share it"

    def test_bad_share_type_400(self):
        r = upload(EMP, title="TEST_upload24 bad", share_cpd="foo")
        assert r.status_code == 400 and "Course, Webinar" in r.json()["detail"]

    def test_bad_hours_400(self):
        assert upload(EMP, title="TEST_upload24 h", cpd_hours="abc").status_code == 400
        assert upload(EMP, title="TEST_upload24 h", cpd_hours="500").status_code == 400

    def test_blank_title_400(self):
        assert upload(EMP, title="   ", share_cpd="Webinar").status_code == 400

    @pytest.mark.parametrize("share,section,cat", [("Webinar", "Webinars", "Webinar"),
                                                   ("Case Study", "Case Studies", "Case Study"),
                                                   ("Resource link", "Resource Links", "Resource link"),
                                                   ("Course", "Courses", "Course")])
    def test_share_with_hours(self, share, section, cat):
        title = f"TEST_upload24 {share}"
        r = upload(EMP, title=title, provider="OT Aus", cpd_hours="1.5", share_cpd=share)
        assert r.status_code == 200, r.text
        d = r.json()
        assert d["title"] == title and d["cpd_resource_id"] and d["cpd_log_id"] and "drive" not in d
        res = mdb.cpd_resources.find_one({"resource_id": d["cpd_resource_id"]}, {"_id": 0})
        assert res["category"] == section and res["storage_path"] and res["source_cert_id"] is None
        log = mdb.cpd_logs.find_one({"log_id": d["cpd_log_id"]}, {"_id": 0})
        assert log["category"] == cat and log["hours"] == 1.5 and log["user_id"] == EMP_ID
        assert log["shared_resource_id"] == d["cpd_resource_id"] and log["provider"] == "OT Aus"
        # resource visible via API with a downloadable file
        lst = requests.get(f"{BASE_URL}/api/cpd/resources", headers=EMP, timeout=20)
        if lst.status_code == 200:
            items = lst.json() if isinstance(lst.json(), list) else lst.json().get("resources", [])
            mine = [x for x in items if x.get("resource_id") == d["cpd_resource_id"]]
            assert mine and "storage_path" not in mine[0]
        # no certificate created
        assert mdb.certificates.count_documents({"title": title}) == 0

    def test_hours_only_creates_log(self):
        r = upload(EMP, title="TEST_upload24 hoursonly", cpd_hours="2")
        assert r.status_code == 200, r.text
        d = r.json()
        assert d["cpd_log_id"] and "cpd_resource_id" not in d
        assert mdb.cpd_logs.find_one({"log_id": d["cpd_log_id"]})["category"] == "Course"

    def test_share_only_no_log(self):
        r = upload(EMP, title="TEST_upload24 shareonly", share_cpd="Webinar")
        assert r.status_code == 200 and r.json()["cpd_resource_id"] and "cpd_log_id" not in r.json()


# ---- event_reminder_loop (in-process)
class _Stop(BaseException):
    pass


def run_reminder_loop(fake_now):
    import routes.events as ev_mod

    class FakeDT(datetime):
        @classmethod
        def now(cls, tz=None):
            return fake_now

    notify_mock, email_mock = mock.AsyncMock(), mock.AsyncMock()

    async def stop(_):
        raise _Stop()

    async def go():
        from core import db
        with mock.patch.object(ev_mod, "datetime", FakeDT), mock.patch.object(ev_mod, "notify", notify_mock), \
                mock.patch.object(ev_mod, "send_email", email_mock), mock.patch.object(ev_mod.asyncio, "sleep", stop):
            try:
                await ev_mod.event_reminder_loop()
            except _Stop:
                pass

    asyncio.run(go())
    return notify_mock, email_mock


class TestReminderLoop:
    def test_reminds_going_maybe_once(self):
        from core import DIGEST_TZ
        # far-future date the real server loop won't reach; ensure no real events on that day
        day = date.today() + timedelta(days=300)
        while mdb.events.count_documents({"date": (day + timedelta(days=1)).isoformat()}):
            day += timedelta(days=1)
        tomorrow = (day + timedelta(days=1)).isoformat()
        fake_now = datetime(day.year, day.month, day.day, 10, 0, tzinfo=DIGEST_TZ)
        base = {"description": "", "catering": "", "conditions": "", "attendees": [], "created_by": "T",
                "created_by_id": ADMIN_ID, "created_at": "x", "date": tomorrow}
        mdb.events.insert_many([
            {**base, "event_id": "evt_test24_rem", "title": "TEST_evt24 Reminder", "time": "5:30pm",
             "location": "Park", "rsvps": [{"user_id": EMP_ID, "status": "going"},
                                           {"user_id": ADMIN_ID, "status": "maybe"},
                                           {"user_id": "user_nobody_test", "status": "not_going"}]},
            {**base, "event_id": "evt_test24_notgoing", "title": "TEST_evt24 NotGoing", "time": "", "location": "",
             "rsvps": [{"user_id": EMP_ID, "status": "not_going"}]},
            {**base, "event_id": "evt_test24_checkin", "title": "TEST_evt24 Checkin", "time": "", "location": "",
             "checkin_for": EMP_ID, "rsvps": [{"user_id": EMP_ID, "status": "going"}]},
        ])
        STATE["events"] += ["evt_test24_rem", "evt_test24_notgoing", "evt_test24_checkin"]
        n, e = run_reminder_loop(fake_now)
        assert n.await_count == 1, n.await_args_list
        ids, ntype, title, body, link = n.await_args.args
        assert sorted(ids) == sorted([EMP_ID, ADMIN_ID]) and "user_nobody_test" not in ids
        assert title == "Reminder: TEST_evt24 Reminder" and "tomorrow at 5:30pm" in body and "Park" in body
        assert link == "/event/evt_test24_rem"
        assert e.await_count == 0  # test users are @example.com -> no email
        assert mdb.events.find_one({"event_id": "evt_test24_rem"})["reminded_for"] == tomorrow
        assert mdb.events.find_one({"event_id": "evt_test24_notgoing"})["reminded_for"] == tomorrow
        assert "reminded_for" not in mdb.events.find_one({"event_id": "evt_test24_checkin"})
        # second run: no repeats
        n2, _ = run_reminder_loop(fake_now)
        assert n2.await_count == 0

    def test_before_9am_does_nothing(self):
        from core import DIGEST_TZ
        day = date.today() + timedelta(days=400)
        tomorrow = (day + timedelta(days=1)).isoformat()
        mdb.events.insert_one({"event_id": "evt_test24_early", "title": "TEST_evt24 Early", "date": tomorrow,
                               "time": "", "location": "", "rsvps": [{"user_id": EMP_ID, "status": "going"}]})
        STATE["events"].append("evt_test24_early")
        n, _ = run_reminder_loop(datetime(day.year, day.month, day.day, 8, 0, tzinfo=DIGEST_TZ))
        assert n.await_count == 0


# ---- Event photos
class TestEventPhotos:
    def test_photo_permissions_and_crud(self):
        ev = make_event(ADMIN)  # organised by admin
        eid = ev["event_id"]
        url = f"{BASE_URL}/api/events/{eid}/photos"
        png = lambda: {"file": ("TEST_p.png", PNG, "image/png")}
        # employee without RSVP -> 403
        r = requests.post(url, headers=EMP, files=png(), timeout=20)
        assert r.status_code == 403, r.text
        # not_going -> still 403
        requests.post(f"{BASE_URL}/api/events/{eid}/rsvp", headers=EMP, json={"status": "not_going"}, timeout=20)
        assert requests.post(url, headers=EMP, files=png(), timeout=20).status_code == 403
        # maybe -> allowed; non-image -> 400
        requests.post(f"{BASE_URL}/api/events/{eid}/rsvp", headers=EMP, json={"status": "maybe"}, timeout=20)
        bad = requests.post(url, headers=EMP, files={"file": ("x.pdf", PDF, "application/pdf")}, timeout=20)
        assert bad.status_code == 400 and "Photos only" in bad.json()["detail"]
        r = requests.post(url, headers=EMP, files=png(), timeout=30)
        assert r.status_code == 200, r.text
        p = r.json()
        assert p["photo_id"].startswith("pho") and p["user_id"] == EMP_ID and "storage_path" not in p
        # admin/organiser can add
        ra = requests.post(url, headers=ADMIN, files=png(), timeout=30)
        assert ra.status_code == 200
        pa = ra.json()
        # GET event lists photos without storage_path
        g = requests.get(f"{BASE_URL}/api/events/{eid}", headers=EMP, timeout=20).json()
        assert {x["photo_id"] for x in g["photos"]} == {p["photo_id"], pa["photo_id"]}
        assert all("storage_path" not in x for x in g["photos"])
        lst = [x for x in requests.get(f"{BASE_URL}/api/events", headers=EMP, timeout=20).json() if x["event_id"] == eid]
        assert all("storage_path" not in x for x in lst[0]["photos"])
        # serve image via ?token=
        img = requests.get(f"{url}/{p['photo_id']}?token=test_session_employee", timeout=20)
        assert img.status_code == 200 and img.headers["content-type"].startswith("image/png") and img.content == PNG
        assert requests.get(f"{url}/{p['photo_id']}", timeout=20).status_code == 401
        assert requests.get(f"{url}/pho_nope?token=test_session_employee", timeout=20).status_code == 404
        # employee can't delete admin's photo -> 404; admin can delete employee's; owner deletes own
        assert requests.delete(f"{url}/{pa['photo_id']}", headers=EMP, timeout=20).status_code == 404
        assert requests.delete(f"{url}/{p['photo_id']}", headers=ADMIN, timeout=20).status_code == 200
        assert requests.delete(f"{url}/{pa['photo_id']}", headers=ADMIN, timeout=20).status_code == 200
        g = requests.get(f"{BASE_URL}/api/events/{eid}", headers=EMP, timeout=20).json()
        assert g["photos"] == []

    def test_going_and_organiser_can_add(self):
        ev = make_event(EMP)  # organised by employee
        url = f"{BASE_URL}/api/events/{ev['event_id']}/photos"
        r = requests.post(url, headers=EMP, files={"file": ("a.png", PNG, "image/png")}, timeout=30)
        assert r.status_code == 200
        assert requests.delete(f"{url}/{r.json()['photo_id']}", headers=EMP, timeout=20).status_code == 200

    def test_missing_event_404(self):
        r = requests.post(f"{BASE_URL}/api/events/evt_nope/photos", headers=ADMIN,
                          files={"file": ("a.png", PNG, "image/png")}, timeout=20)
        assert r.status_code == 404


# ---- .ics calendar file
class TestIcs:
    def test_timed_event_utc(self):
        ev = make_event(EMP, time="5:30pm", title="TEST_evt24 ICS, timed")
        r = requests.get(f"{BASE_URL}/api/events/{ev['event_id']}/ics?token=test_session_employee", timeout=20)
        assert r.status_code == 200 and r.headers["content-type"].startswith("text/calendar")
        d = FUTURE.replace("-", "")
        assert f"DTSTART:{d}T093000Z" in r.text and f"DTEND:{d}T113000Z" in r.text
        assert "SUMMARY:TEST_evt24 ICS\\, timed" in r.text and "BEGIN:VCALENDAR" in r.text
        assert "attachment" in r.headers.get("content-disposition", "")

    def test_all_day_event(self):
        ev = make_event(EMP, time="")
        r = requests.get(f"{BASE_URL}/api/events/{ev['event_id']}/ics", headers=ADMIN, timeout=20)
        assert r.status_code == 200
        d = date.fromisoformat(FUTURE)
        assert f"DTSTART;VALUE=DATE:{d.strftime('%Y%m%d')}" in r.text
        assert f"DTEND;VALUE=DATE:{(d + timedelta(days=1)).strftime('%Y%m%d')}" in r.text

    def test_ics_auth(self):
        ev = make_event(EMP)
        assert requests.get(f"{BASE_URL}/api/events/{ev['event_id']}/ics", timeout=20).status_code == 401
        assert requests.get(f"{BASE_URL}/api/events/evt_nope/ics?token=test_session_admin", timeout=20).status_code == 404
