# Iteration 19: required certs per staff group, cert reminder preview, admin starter progress view,
# check-in booking (private events), completion alert link, Pronathi removal.
# NEVER calls /compliance/remind-certificates without preview=true (would email real staff).
# Run serially: pytest -n 0 (module fixture shares DB state; xdist workers would tear it down mid-run).
import asyncio
import io
import os
import sys
import uuid
from datetime import datetime, timedelta, timezone
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
OTHER_ID = "user_TEST_other19"
OTHER_TOKEN = "test_session_TEST_other19"
OTHER = {"Authorization": f"Bearer {OTHER_TOKEN}"}
mdb = MongoClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]
START = datetime.now(timezone.utc).isoformat()


@pytest.fixture(scope="module", autouse=True)
def state():
    reqs0 = mdb.meta.find_one({"key": "cert_requirements"}, {"_id": 0})
    grp0 = mdb.users.find_one({"user_id": EMP_ID})["staff_group"]
    mdb.users.update_one({"user_id": OTHER_ID}, {"$set": {"user_id": OTHER_ID, "email": "test.other19@example.com",
                                                        "name": "TEST Other", "role": "employee", "hidden": True,
                                                        "staff_group": None}}, upsert=True)
    mdb.user_sessions.update_one({"session_token": OTHER_TOKEN}, {"$set": {
        "user_id": OTHER_ID, "session_token": OTHER_TOKEN,
        "expires_at": datetime.now(timezone.utc) + timedelta(days=1)}}, upsert=True)
    yield
    if reqs0:
        mdb.meta.update_one({"key": "cert_requirements"}, {"$set": {"groups": reqs0["groups"]}})
    else:
        mdb.meta.delete_one({"key": "cert_requirements"})
    mdb.users.update_one({"user_id": EMP_ID}, {"$set": {"staff_group": grp0}, "$unset": {"starter_completed_at": ""}})
    mdb.events.delete_many({"checkin_for": EMP_ID})
    mdb.notifications.delete_many({"user_id": EMP_ID, "created_at": {"$gte": START}})
    mdb.notifications.delete_many({"user_id": ADMIN_ID, "created_at": {"$gte": START}})
    mdb.user_sessions.delete_many({"user_id": OTHER_ID})
    mdb.users.delete_one({"user_id": OTHER_ID})


def put_req(group, names, h=ADMIN):
    return requests.put(f"{BASE_URL}/api/cert-requirements", headers=h, json={"staff_group": group, "names": names},
                        timeout=30)


def set_group(group):
    r = requests.patch(f"{BASE_URL}/api/users/{EMP_ID}/group", headers=ADMIN, json={"staff_group": group}, timeout=30)
    assert r.status_code == 200, r.text


# ---------- Cert requirements CRUD ----------
class TestCertRequirements:
    def test_get_admin(self):
        r = requests.get(f"{BASE_URL}/api/cert-requirements", headers=ADMIN, timeout=30)
        assert r.status_code == 200 and isinstance(r.json()["groups"], dict)

    def test_employee_forbidden(self):
        assert requests.get(f"{BASE_URL}/api/cert-requirements", headers=EMP, timeout=30).status_code == 403
        assert put_req("support_office", ["X"], EMP).status_code == 403

    def test_bad_group(self):
        assert put_req("nope_group", ["X"]).status_code == 400

    def test_put_dedupes_and_persists(self):
        r = put_req("new_starter_employee", ["First Aid", " first aid ", "  ", "NDIS Worker Screening", "ndis worker screening"])
        assert r.status_code == 200
        assert r.json()["groups"]["new_starter_employee"] == ["First Aid", "NDIS Worker Screening"]
        g = requests.get(f"{BASE_URL}/api/cert-requirements", headers=ADMIN, timeout=30).json()["groups"]
        assert g["new_starter_employee"] == ["First Aid", "NDIS Worker Screening"]


def test_missing_required_unit():
    from routes.compliance import missing_required
    certs = [{"title": "Provide First AID Certificate", "expiry_date": "2099-01-01"},
             {"title": "NDIS Worker Screening", "expiry_date": "2000-01-01"}]
    assert missing_required(certs, ["first aid", "NDIS Worker Screening", "CPR"]) == ["NDIS Worker Screening", "CPR"]


# ---------- Admin starter progress + certificate requirement ----------
class TestStarterProgress:
    def test_cert_item_missing_and_done(self):
        set_group("new_starter_employee")
        put_req("new_starter_employee", ["first aid", "NDIS Worker Screening"])
        d = requests.get(f"{BASE_URL}/api/starter-checklist/user/{EMP_ID}", headers=ADMIN, timeout=30).json()
        for k in ("user", "items", "done", "total", "completed_at", "checkins"):
            assert k in d
        assert d["user"]["user_id"] == EMP_ID and d["total"] == len(d["items"])
        cert = [i for i in d["items"] if i["key"] == "certificates"][0]
        assert cert["missing"] == ["NDIS Worker Screening"] and cert["done"] is False
        put_req("new_starter_employee", ["FIRST AID"])
        d = requests.get(f"{BASE_URL}/api/starter-checklist/user/{EMP_ID}", headers=ADMIN, timeout=30).json()
        cert = [i for i in d["items"] if i["key"] == "certificates"][0]
        assert cert["missing"] == [] and cert["done"] is True

    def test_employee_forbidden(self):
        assert requests.get(f"{BASE_URL}/api/starter-checklist/user/{EMP_ID}", headers=EMP, timeout=30).status_code == 403

    def test_unknown_user_404(self):
        assert requests.get(f"{BASE_URL}/api/starter-checklist/user/user_nope_x", headers=ADMIN, timeout=30).status_code == 404


# ---------- Check-in booking ----------
class TestCheckin:
    def test_bad_date_and_forbidden(self):
        url = f"{BASE_URL}/api/starter-checklist/user/{EMP_ID}/checkin"
        assert requests.post(url, headers=ADMIN, json={"date": "15-07-2026"}, timeout=30).status_code == 400
        assert requests.post(url, headers=EMP, json={"date": "2026-12-15"}, timeout=30).status_code == 403
        assert requests.post(f"{BASE_URL}/api/starter-checklist/user/user_nope_x/checkin", headers=ADMIN,
                             json={"date": "2026-12-15"}, timeout=30).status_code == 404

    def test_book_and_visibility(self):
        r = requests.post(f"{BASE_URL}/api/starter-checklist/user/{EMP_ID}/checkin", headers=ADMIN,
                          json={"date": "2026-12-15", "time": " 10:00am ", "location": "TEST Office", "note": "TEST note"},
                          timeout=30)
        assert r.status_code == 200, r.text
        ev = r.json()
        assert ev["checkin_for"] == EMP_ID and set(ev["private_for"]) == {EMP_ID, ADMIN_ID}
        assert ev["time"] == "10:00am" and ev["location"] == "TEST Office" and "attendees" not in ev
        d = requests.get(f"{BASE_URL}/api/starter-checklist/user/{EMP_ID}", headers=ADMIN, timeout=30).json()
        assert ev["event_id"] in [c["event_id"] for c in d["checkins"]]
        # starter notified in-app
        notes = requests.get(f"{BASE_URL}/api/notifications", headers=EMP, timeout=30).json()
        notes = notes.get("items", notes) if isinstance(notes, dict) else notes
        assert any(n["title"] == "Check-in booked" and "15-12-2026" in n["body"] for n in notes), notes[:3]
        # employee sees own private + public; other user doesn't see it
        emp_ev = requests.get(f"{BASE_URL}/api/events", headers=EMP, timeout=30).json()
        assert ev["event_id"] in [e["event_id"] for e in emp_ev]
        assert all(("private_for" not in e) or (EMP_ID in e["private_for"]) for e in emp_ev)
        mine = [e for e in emp_ev if e["event_id"] == ev["event_id"]][0]
        assert mine["going"] is True
        oth = requests.get(f"{BASE_URL}/api/events", headers=OTHER, timeout=30)
        assert oth.status_code == 200
        assert ev["event_id"] not in [e["event_id"] for e in oth.json()]
        assert all("private_for" not in e for e in oth.json())
        adm = requests.get(f"{BASE_URL}/api/events", headers=ADMIN, timeout=30).json()
        assert ev["event_id"] in [e["event_id"] for e in adm]


# ---------- Compliance + export + reminder preview ----------
class TestComplianceRequired:
    def test_rows_flag_missing(self):
        put_req("support_office", ["TEST_ZZZ_Required"])
        d = requests.get(f"{BASE_URL}/api/compliance", headers=ADMIN, timeout=60).json()
        so = [r for r in d["rows"] if r.get("staff_group") == "support_office"]
        assert so, "no support office staff"
        for r in d["rows"]:
            assert isinstance(r["missing_required"], list)
            if r["missing_required"]:
                assert r["needs_attention"] is True
        assert all("TEST_ZZZ_Required" in r["missing_required"] for r in so)
        assert d["summary"]["missing_required"] == sum(1 for r in d["rows"] if r["missing_required"])
        assert d["summary"]["missing_required"] >= len(so)

    def test_export_column_and_summary(self):
        from openpyxl import load_workbook
        r = requests.get(f"{BASE_URL}/api/compliance/export", headers=ADMIN, timeout=60)
        assert r.status_code == 200
        wb = load_workbook(io.BytesIO(r.content))
        ws = wb["Staff compliance"]
        head = [c.value for c in ws[1]]
        assert "Missing required certificates" in head
        col = head.index("Missing required certificates")
        vals = [row[col].value for row in ws.iter_rows(min_row=2)]
        assert any(v and "TEST_ZZZ_Required" in v for v in vals)
        labels = [row[0].value for row in wb["Summary"].iter_rows()]
        assert "Staff missing required certificates" in labels

    def test_remind_preview_no_send(self):
        before = mdb.notifications.count_documents({"title": "Please upload your certificates"})
        r = requests.post(f"{BASE_URL}/api/compliance/remind-certificates?preview=true", headers=ADMIN, timeout=60)
        assert r.status_code == 200
        d = requests.get(f"{BASE_URL}/api/compliance", headers=ADMIN, timeout=60).json()
        exp = sum(1 for x in d["rows"] if x["no_certs"] or x["missing_required"])
        assert r.json() == {"reminded": 0, "would_remind": exp}
        assert mdb.notifications.count_documents({"title": "Please upload your certificates"}) == before

    def test_remind_employee_forbidden(self):
        assert requests.post(f"{BASE_URL}/api/compliance/remind-certificates?preview=true", headers=EMP,
                             timeout=30).status_code == 403


def test_pronathi_absent():
    users = requests.get(f"{BASE_URL}/api/users", headers=ADMIN, timeout=30).json()
    assert not any("pronathi" in (u.get("email") or "").lower() or "pronathi" in (u.get("name") or "").lower()
                   for u in users)


# ---------- Completion alert (in-process, notify/send_email MOCKED) ----------
def test_completion_alert_link():
    import routes.compliance as rc
    from motor.motor_asyncio import AsyncIOMotorClient
    notes, sent = [], []

    async def fake_notify(uids, ntype, title, body, link=""):
        notes.append((tuple(uids), ntype, title, link))

    async def fake_email(**kw):
        sent.append(kw["to"])

    async def run():
        # fresh motor client bound to this loop (avoids 'Event loop is closed' when run after other asyncio.run tests)
        db = AsyncIOMotorClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]
        orig = rc.notify, rc.send_email, rc.starter_checklist, rc.db
        rc.notify, rc.send_email, rc.db = fake_notify, fake_email, db

        async def all_done(u):
            return [{"done": True}]
        rc.starter_checklist = all_done
        try:
            await db.users.update_one({"user_id": EMP_ID}, {"$set": {"staff_group": "new_starter_employee"},
                                                            "$unset": {"starter_completed_at": ""}})
            await rc.check_starter_complete({"user_id": EMP_ID})
        finally:
            rc.notify, rc.send_email, rc.starter_checklist, rc.db = orig
            await db.users.update_one({"user_id": EMP_ID}, {"$unset": {"starter_completed_at": ""}})

    asyncio.run(run())
    assert len(notes) == 1 and notes[0][3] == f"/starter/{EMP_ID}", notes
    assert sent == []
