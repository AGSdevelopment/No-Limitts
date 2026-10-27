# Forms audience (Support Office vs Everyone) + Support Office membership tests
import os
from datetime import datetime, timezone, timedelta

import pytest
import requests
from dotenv import load_dotenv
from pymongo import MongoClient

load_dotenv("/app/frontend/.env")
load_dotenv("/app/backend/.env")
BASE_URL = (os.environ.get("EXPO_BACKEND_URL") or os.environ["EXPO_PUBLIC_BACKEND_URL"]).rstrip("/")
API = f"{BASE_URL}/api"
db = MongoClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]

ADMIN = {"Authorization": "Bearer test_session_admin"}
EMP = {"Authorization": "Bearer test_session_employee"}
EMP_ID = "user_testemp001"
JO_TOKEN = "test_session_johanna_tmp"
SO_TITLES = {"Worker Screening & Set Up", "3/6/12 Month Review", "6 Week Check-in", "Support Office New Starter Checklist"}
EVERYONE_TITLES = {"Leave Request & Absence Notification", "Conflict of Interest Reporting", "Request for Support"}


def titles(headers):
    r = requests.get(f"{API}/forms", headers=headers)
    assert r.status_code == 200, r.text
    return {f["title"] for f in r.json()}, r.json()


@pytest.fixture(scope="module")
def jo_headers():
    u = db.users.find_one({"email": "johanna@aspireandgrow.com.au"}, {"_id": 0})
    assert u, "Johanna user missing"
    db.user_sessions.delete_many({"session_token": JO_TOKEN})
    now = datetime.now(timezone.utc)
    db.user_sessions.insert_one({"session_token": JO_TOKEN, "user_id": u["user_id"],
                                 "expires_at": now + timedelta(hours=2), "created_at": now})
    yield {"Authorization": f"Bearer {JO_TOKEN}"}
    db.user_sessions.delete_many({"session_token": JO_TOKEN})


@pytest.fixture(autouse=True, scope="module")
def ensure_emp_off():
    yield
    db.users.update_one({"user_id": EMP_ID}, {"$set": {"support_office": False}})


# --- visibility
class TestVisibility:
    def test_admin_sees_all_7(self):
        t, data = titles(ADMIN)
        assert SO_TITLES | EVERYONE_TITLES <= t
        assert all(f.get("audience") in ("everyone", "support_office") for f in data)

    def test_employee_sees_only_everyone(self):
        t, data = titles(EMP)
        assert t == EVERYONE_TITLES, t
        assert all(f.get("audience") != "support_office" for f in data)

    def test_johanna_sees_all_7(self, jo_headers):
        me = requests.get(f"{API}/auth/me", headers=jo_headers)
        assert me.status_code == 200 and me.json()["email"] == "johanna@aspireandgrow.com.au"
        t, _ = titles(jo_headers)
        assert SO_TITLES | EVERYONE_TITLES <= t

    def test_johanna_cannot_patch_form(self, jo_headers):
        fid = db.forms.find_one({"title": "Request for Support"})["form_id"]
        r = requests.patch(f"{API}/forms/{fid}", json={"audience": "support_office"}, headers=jo_headers)
        assert r.status_code == 403


# --- support office toggle
class TestSupportOfficeToggle:
    def test_employee_forbidden(self):
        r = requests.patch(f"{API}/users/{EMP_ID}/support-office", json={"enabled": True}, headers=EMP)
        assert r.status_code == 403
        assert not db.users.find_one({"user_id": EMP_ID}).get("support_office")

    def test_unknown_user_404(self):
        r = requests.patch(f"{API}/users/user_doesnotexist/support-office", json={"enabled": True}, headers=ADMIN)
        assert r.status_code == 404

    def test_invalid_body_422(self):
        r = requests.patch(f"{API}/users/{EMP_ID}/support-office", json={"enabled": "maybe"}, headers=ADMIN)
        assert r.status_code == 422

    def test_toggle_on_then_off(self):
        r = requests.patch(f"{API}/users/{EMP_ID}/support-office", json={"enabled": True}, headers=ADMIN)
        assert r.status_code == 200 and r.json()["support_office"] is True and "_id" not in r.json()
        t, _ = titles(EMP)
        assert SO_TITLES | EVERYONE_TITLES <= t
        users = requests.get(f"{API}/users", headers=ADMIN).json()
        assert next(u for u in users if u["user_id"] == EMP_ID)["support_office"] is True
        r = requests.patch(f"{API}/users/{EMP_ID}/support-office", json={"enabled": False}, headers=ADMIN)
        assert r.status_code == 200 and r.json()["support_office"] is False
        t, _ = titles(EMP)
        assert t == EVERYONE_TITLES


# --- form audience patch
class TestFormAudiencePatch:
    def test_employee_forbidden(self):
        fid = db.forms.find_one({"title": "Request for Support"})["form_id"]
        r = requests.patch(f"{API}/forms/{fid}", json={"audience": "support_office"}, headers=EMP)
        assert r.status_code == 403

    def test_invalid_audience_400(self):
        fid = db.forms.find_one({"title": "Request for Support"})["form_id"]
        r = requests.patch(f"{API}/forms/{fid}", json={"audience": "managers"}, headers=ADMIN)
        assert r.status_code == 400
        assert db.forms.find_one({"form_id": fid})["audience"] == "everyone"

    def test_unknown_form_404(self):
        r = requests.patch(f"{API}/forms/form_nope", json={"audience": "everyone"}, headers=ADMIN)
        assert r.status_code == 404

    def test_patch_and_restore(self):
        fid = db.forms.find_one({"title": "Request for Support"})["form_id"]
        try:
            r = requests.patch(f"{API}/forms/{fid}", json={"audience": "support_office"}, headers=ADMIN)
            assert r.status_code == 200 and r.json()["audience"] == "support_office" and "_id" not in r.json()
            t, _ = titles(EMP)
            assert "Request for Support" not in t
        finally:
            r = requests.patch(f"{API}/forms/{fid}", json={"audience": "everyone"}, headers=ADMIN)
        assert r.status_code == 200 and r.json()["audience"] == "everyone"
        t, _ = titles(EMP)
        assert "Request for Support" in t


# --- create form w/ audience + notifications
class TestCreateFormAudience:
    def _cleanup(self, fid, title):
        if fid:
            requests.delete(f"{API}/forms/{fid}", headers=ADMIN)
        db.notifications.delete_many({"type": "form", "body": title})

    def test_invalid_audience_on_create(self):
        r = requests.post(f"{API}/forms", json={"title": "TEST_bad", "url": "https://form.jotform.com/1", "audience": "x"}, headers=ADMIN)
        assert r.status_code == 400
        assert db.forms.count_documents({"title": "TEST_bad"}) == 0

    def test_employee_cannot_create(self):
        r = requests.post(f"{API}/forms", json={"title": "TEST_emp", "url": "https://form.jotform.com/1"}, headers=EMP)
        assert r.status_code == 403

    def test_support_office_form_notifies_only_admins_and_so(self):
        title = "TEST_SO_form_audience"
        fid = None
        try:
            r = requests.post(f"{API}/forms", json={"title": title, "url": "https://form.jotform.com/123", "audience": "support_office"}, headers=ADMIN)
            assert r.status_code == 200, r.text
            fid = r.json()["form_id"]
            assert r.json()["audience"] == "support_office"
            recips = {n["user_id"] for n in db.notifications.find({"type": "form", "body": title})}
            expected = {u["user_id"] for u in db.users.find({"$or": [{"role": "admin"}, {"support_office": True}]})} - {"user_testadmin01"}
            assert recips == expected, (recips, expected)
            assert EMP_ID not in recips
            assert title not in titles(EMP)[0]
            assert title in titles(ADMIN)[0]
        finally:
            self._cleanup(fid, title)
        assert db.forms.count_documents({"title": title}) == 0

    def test_everyone_form_default_notifies_all(self):
        title = "TEST_EVERYONE_form_audience"
        fid = None
        try:
            r = requests.post(f"{API}/forms", json={"title": title, "url": "https://form.jotform.com/456"}, headers=ADMIN)
            assert r.status_code == 200 and r.json()["audience"] == "everyone"
            fid = r.json()["form_id"]
            recips = {n["user_id"] for n in db.notifications.find({"type": "form", "body": title})}
            assert EMP_ID in recips and "user_testadmin01" not in recips
            assert title in titles(EMP)[0]
        finally:
            self._cleanup(fid, title)
