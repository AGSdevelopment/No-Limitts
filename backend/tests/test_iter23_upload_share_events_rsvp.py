# Iteration 23: upload sharing (CPD Resources / Drive spaces), team social events + RSVP, probation end-only guard.
# ONLY touches hidden test users (user_testemp001, user_testadmin01). Run serially: pytest -n 0
# NOTE: Drive IS connected in preview. Every cert upload also copies to the company cert folder (existing behaviour),
# and drive_spaces writes to Participant Resources. All Drive files titled TEST_upload* are deleted in teardown.
import os
import sys
import time
from datetime import date, timedelta
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
FUTURE = (date.today() + timedelta(days=20)).isoformat()
PAST = (date.today() - timedelta(days=2)).isoformat()
PDF = b"%PDF-1.4\n% TEST_upload tiny file\n"
STATE = {"certs": [], "resources": [], "events": []}


def drive_cleanup():
    """Delete every Drive file named TEST_upload* created by these tests (cert copies + space uploads)."""
    import google_services as gs
    conn = mdb.integrations.find_one({"key": "google_drive"})
    if not conn or not gs.drive_client_config():
        return []
    svc = gs.drive_service(conn["refresh_token"])
    res = svc.files().list(q="name contains 'TEST_upload' and trashed = false", fields="files(id,name,parents)",
                           supportsAllDrives=True, includeItemsFromAllDrives=True, corpora="allDrives").execute()
    deleted = []
    for f in res.get("files", []):
        try:
            svc.files().delete(fileId=f["id"], supportsAllDrives=True).execute()
            deleted.append(f["name"])
        except Exception as e:  # report but don't fail
            print(f"DRIVE DELETE FAILED {f['name']}: {e}")
    print(f"DRIVE DELETED: {deleted}")
    return deleted


@pytest.fixture(scope="module", autouse=True)
def cleanup():
    emp = mdb.users.find_one({"user_id": EMP_ID}, {"_id": 0, "start_date": 1, "probation_end": 1,
                                                    "probation_reminded_for": 1})
    yield
    time.sleep(4)  # let spawned copy_cert_to_drive finish
    titles = []
    for cid in STATE["certs"]:
        c = mdb.certificates.find_one({"cert_id": cid})
        if c:
            titles.append(c["title"])
        mdb.certificates.delete_one({"cert_id": cid})
        mdb.cpd_logs.delete_many({"cert_id": cid})
    mdb.cpd_resources.delete_many({"title": {"$regex": "^TEST_upload"}})
    mdb.cpd_logs.delete_many({"title": {"$regex": "^TEST_upload"}})
    mdb.notifications.delete_many({"title": "New CPD resource", "body": {"$regex": "^TEST_upload"}})
    mdb.notifications.delete_many({"body": {"$regex": "^TEST_(evt|upload)"}})
    mdb.notifications.delete_many({"title": {"$regex": "^(Certificate|New event|Event cancelled)"},
                                   "body": {"$regex": "TEST_(evt|upload)"}})
    mdb.events.delete_many({"title": {"$regex": "^TEST_evt"}})
    mdb.users.update_one({"user_id": EMP_ID}, {"$set": {k: (emp or {}).get(k) for k in
                                                       ("start_date", "probation_end", "probation_reminded_for")}})
    try:
        drive_cleanup()
        time.sleep(3)  # index_drive() is spawned after a space upload; drop its stale entry
        mdb.drive_docs.delete_many({"name": {"$regex": "^TEST_upload"}})
    except Exception as e:
        print(f"DRIVE CLEANUP ERROR: {e}")


def upload(extra: dict, title: str):
    data = {"title": title, "expiry_date": (date.today() + timedelta(days=400)).isoformat(), "issuer": "TEST Org"}
    data.update(extra)
    r = requests.post(f"{BASE_URL}/api/certificates", headers=EMP, data=data,
                      files={"file": ("TEST_upload.pdf", PDF, "application/pdf")}, timeout=60)
    if r.status_code == 200:
        STATE["certs"].append(r.json()["cert_id"])
    return r


# ---- Upload -> CPD Resources
class TestUploadShareCpd:
    def test_share_webinar_with_hours(self):
        r = upload({"share_cpd": "Webinar", "cpd_hours": "1.5"}, "TEST_upload Webinar")
        assert r.status_code == 200, r.text
        d = r.json()
        assert d.get("cpd_resource_id", "").startswith("cpdr")
        assert d["cpd_hours"] == 1.5 and "drive" not in d
        STATE["web"] = d
        res = requests.get(f"{BASE_URL}/api/cpd/resources", headers=EMP).json()
        mine = next(x for x in res if x["resource_id"] == d["cpd_resource_id"])
        assert mine["category"] == "Webinars" and mine["has_file"] is True and "storage_path" not in mine
        f = requests.get(f"{BASE_URL}/api/cpd/resources/{d['cpd_resource_id']}/file", headers=ADMIN)
        assert f.status_code == 200 and f.content == PDF
        logs = requests.get(f"{BASE_URL}/api/cpd", headers=EMP).json()
        logs = logs.get("logs", logs) if isinstance(logs, dict) else logs
        log = next(x for x in logs if x.get("cert_id") == d["cert_id"])
        assert log["category"] == "Webinar" and log.get("shared_resource_id") == d["cpd_resource_id"]

    @pytest.mark.parametrize("label,section", [("Case Study", "Case Studies"), ("Resource link", "Resource Links")])
    def test_share_other_types_no_hours(self, label, section):
        r = upload({"share_cpd": label}, f"TEST_upload {label}")
        assert r.status_code == 200, r.text
        d = r.json()
        res = requests.get(f"{BASE_URL}/api/cpd/resources", headers=EMP).json()
        mine = next(x for x in res if x["resource_id"] == d["cpd_resource_id"])
        assert mine["category"] == section and mine["has_file"]
        assert not mdb.cpd_logs.find_one({"cert_id": d["cert_id"]})

    def test_no_share_returns_no_extra_keys(self):
        r = upload({}, "TEST_upload Plain")
        assert r.status_code == 200
        assert "cpd_resource_id" not in r.json() and "drive" not in r.json()


# ---- Upload -> Drive spaces (ONCE; writes a real file, deleted in teardown)
class TestUploadDriveSpaces:
    def test_drive_spaces_once(self):
        r = upload({"share_cpd": "Course", "drive_spaces": "therapist,participant"}, "TEST_upload")
        assert r.status_code == 200, r.text
        d = r.json()
        print("DRIVE RESULT:", d.get("drive"))
        assert set(d["drive"]) == {"therapist", "participant"}
        assert all(v in ("added", "not_set_up", "failed") for v in d["drive"].values())
        conn = mdb.integrations.find_one({"key": "google_drive"}) or {}
        spaces = conn.get("spaces") or {}
        for s in ("therapist", "participant"):
            if not spaces.get(s, {}).get("id"):
                assert d["drive"][s] == "not_set_up"
        assert d["drive"].get("participant") != "failed"
        res = requests.get(f"{BASE_URL}/api/cpd/resources", headers=EMP).json()
        assert next(x for x in res if x["resource_id"] == d["cpd_resource_id"])["category"] == "Courses"


# ---- Events
class TestEvents:
    def test_employee_creates_event(self):
        body = {"title": "TEST_evt Team picnic", "date": FUTURE, "time": "12:30", "location": "Kings Park",
                "description": "Celebrate the quarter", "catering": "BYO", "conditions": "Bring a hat"}
        r = requests.post(f"{BASE_URL}/api/events", headers=EMP, json=body)
        assert r.status_code == 200, r.text
        d = r.json()
        for k, v in body.items():
            assert d[k] == v
        assert d["created_by_id"] == EMP_ID and d["can_delete"] is True
        assert d["counts"] == {"going": 0, "maybe": 0, "not_going": 0} and d["my_rsvp"] is None
        STATE["evt"] = d["event_id"]
        g = requests.get(f"{BASE_URL}/api/events/{d['event_id']}", headers=ADMIN).json()
        assert g["title"] == body["title"] and g["catering"] == "BYO"
        n = mdb.notifications.find_one({"user_id": ADMIN_ID, "link": f"/event/{d['event_id']}"})
        assert n and n["title"].startswith("New event")
        assert not mdb.notifications.find_one({"user_id": EMP_ID, "link": f"/event/{d['event_id']}"})

    @pytest.mark.parametrize("patch,code", [({"catering": "Pizza"}, 400), ({"date": PAST}, 400),
                                            ({"date": "28-10-2026"}, 400), ({"title": "  "}, 400)])
    def test_create_validation(self, patch, code):
        body = {"title": "TEST_evt bad", "date": FUTURE, "catering": ""}
        body.update(patch)
        r = requests.post(f"{BASE_URL}/api/events", headers=EMP, json=body)
        assert r.status_code == code, r.text

    def test_rsvp_upsert_visible_to_all(self):
        eid = STATE["evt"]
        r = requests.post(f"{BASE_URL}/api/events/{eid}/rsvp", headers=EMP, json={"status": "maybe", "comment": "Late"})
        assert r.status_code == 200 and r.json()["my_rsvp"]["status"] == "maybe" and r.json()["going"] is False
        r = requests.post(f"{BASE_URL}/api/events/{eid}/rsvp", headers=EMP, json={"status": "going", "comment": "In!"})
        assert r.json()["counts"] == {"going": 1, "maybe": 0, "not_going": 0}
        assert len([x for x in r.json()["rsvps"] if x["user_id"] == EMP_ID]) == 1
        r = requests.post(f"{BASE_URL}/api/events/{eid}/rsvp", headers=ADMIN, json={"status": "not_going",
                                                                                   "comment": "Away"})
        a = r.json()
        assert a["counts"] == {"going": 1, "maybe": 0, "not_going": 1} and a["my_rsvp"]["status"] == "not_going"
        e = next(x for x in a["rsvps"] if x["user_id"] == EMP_ID)
        assert e["status"] == "going" and e["comment"] == "In!" and e["name"]
        lst = requests.get(f"{BASE_URL}/api/events", headers=EMP).json()
        ev = next(x for x in lst if x["event_id"] == eid)
        assert ev["going"] is True and ev["attendee_count"] == 1 and len(ev["rsvps"]) == 2

    def test_rsvp_bad_status_and_remove(self):
        eid = STATE["evt"]
        assert requests.post(f"{BASE_URL}/api/events/{eid}/rsvp", headers=EMP, json={"status": "yes"}).status_code == 400
        r = requests.post(f"{BASE_URL}/api/events/{eid}/rsvp", headers=EMP, json={"status": None})
        assert r.status_code == 200 and r.json()["my_rsvp"] is None and r.json()["counts"]["going"] == 0
        assert r.json()["attendee_count"] == 0

    def test_rsvp_legacy_toggle(self):
        eid = STATE["evt"]
        r = requests.post(f"{BASE_URL}/api/events/{eid}/rsvp", headers=EMP)
        assert r.status_code == 200 and r.json()["going"] is True and r.json()["my_rsvp"]["status"] == "going"
        r = requests.post(f"{BASE_URL}/api/events/{eid}/rsvp", headers=EMP)
        assert r.json()["going"] is False and r.json()["my_rsvp"] is None

    def test_delete_permissions(self):
        # admin-created event: employee cannot delete it
        r = requests.post(f"{BASE_URL}/api/events", headers=ADMIN, json={"title": "TEST_evt admin", "date": FUTURE})
        aid = r.json()["event_id"]
        assert r.json()["can_delete"] is True
        g = requests.get(f"{BASE_URL}/api/events/{aid}", headers=EMP).json()
        assert g["can_delete"] is False
        assert requests.delete(f"{BASE_URL}/api/events/{aid}", headers=EMP).status_code == 403
        assert requests.delete(f"{BASE_URL}/api/events/{aid}", headers=ADMIN).status_code == 200
        assert requests.get(f"{BASE_URL}/api/events/{aid}", headers=ADMIN).status_code == 404
        # organiser (employee) deletes own event
        eid = STATE["evt"]
        requests.post(f"{BASE_URL}/api/events/{eid}/rsvp", headers=ADMIN, json={"status": "going"})
        assert requests.delete(f"{BASE_URL}/api/events/{eid}", headers=EMP).status_code == 200
        assert requests.get(f"{BASE_URL}/api/events/{eid}", headers=EMP).status_code == 404
        assert mdb.notifications.find_one({"user_id": ADMIN_ID, "title": "Event cancelled",
                                           "body": {"$regex": "^TEST_evt Team picnic"}})


class TestPrivateCheckin:
    def test_private_checkin_hidden(self):
        eid = "evt_TESTcheckin01"
        mdb.events.insert_one({"event_id": eid, "title": "TEST_evt check-in", "date": FUTURE, "time": "",
                               "attendees": [], "private_for": ["user_other_x", ADMIN_ID],
                               "checkin_for": "user_other_x", "notes": "secret", "created_by_id": ADMIN_ID})
        lst = requests.get(f"{BASE_URL}/api/events", headers=EMP).json()
        assert eid not in [x["event_id"] for x in lst]
        assert requests.get(f"{BASE_URL}/api/events/{eid}", headers=EMP).status_code == 404
        assert requests.post(f"{BASE_URL}/api/events/{eid}/rsvp", headers=EMP, json={"status": "going"}).status_code == 404
        adm = requests.get(f"{BASE_URL}/api/events/{eid}", headers=ADMIN)
        assert adm.status_code == 200 and adm.json()["notes"] == "secret"
        assert requests.delete(f"{BASE_URL}/api/events/{eid}", headers=ADMIN).status_code == 404
        mdb.events.delete_one({"event_id": eid})


class TestProbationGuard:
    def test_end_only_before_saved_start(self):
        r = requests.patch(f"{BASE_URL}/api/staff/{EMP_ID}/probation", headers=ADMIN, json={"start_date": "2026-03-01"})
        assert r.status_code == 200 and r.json()["probation_end"] == "2027-03-01"
        r = requests.patch(f"{BASE_URL}/api/staff/{EMP_ID}/probation", headers=ADMIN, json={"probation_end": "2026-02-01"})
        assert r.status_code == 400, r.text
        r = requests.patch(f"{BASE_URL}/api/staff/{EMP_ID}/probation", headers=ADMIN, json={"probation_end": "2026-03-01"})
        assert r.status_code == 400
        r = requests.patch(f"{BASE_URL}/api/staff/{EMP_ID}/probation", headers=ADMIN, json={"probation_end": "2026-09-01"})
        assert r.status_code == 200 and r.json() == {"probation_end": "2026-09-01"}
