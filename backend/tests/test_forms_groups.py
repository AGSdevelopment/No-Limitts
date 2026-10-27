# Jotform staff-group access levels + form sections (category/audiences) + migration checks
import os

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
EVERYONE_TITLES = {"Leave Request & Absence Notification", "Conflict of Interest Reporting", "Request for Support",
                   "Asset Register Submission", "CPD Certificate Submission", "Two Week Check-in",
                   "Authority to Deduct Wages", "Secondary Employment Declaration"}
CATS = {"Day-to-Day", "New Starter", "HR", "Compliance", "Referral Triage", "Therapy Triage", "Support Office"}
GROUPS = {"support_office", "therapist_employee", "therapist_contractor", "support_worker_employee",
          "support_worker_contractor"}


def get_forms(h):
    r = requests.get(f"{API}/forms", headers=h)
    assert r.status_code == 200, r.text
    return r.json()


@pytest.fixture(scope="module", autouse=True)
def restore_state():
    emp_before = db.users.find_one({"user_id": EMP_ID}, {"_id": 0, "staff_group": 1})
    forms_before = list(db.forms.find({}, {"_id": 0}))
    yield
    # restore employee group, all original forms, delete test forms + their notifications
    if emp_before and "staff_group" in emp_before:
        db.users.update_one({"user_id": EMP_ID}, {"$set": {"staff_group": emp_before["staff_group"]}})
    else:
        db.users.update_one({"user_id": EMP_ID}, {"$unset": {"staff_group": ""}})
    for f in forms_before:
        db.forms.replace_one({"form_id": f["form_id"]}, f)
    db.forms.delete_many({"title": {"$regex": "^TEST_"}})
    db.notifications.delete_many({"type": "form", "body": {"$regex": "^TEST_"}})


# --- listing / visibility
class TestFormsList:
    def test_admin_sees_all_16_with_fields(self):
        forms = get_forms(ADMIN)
        real = [f for f in forms if not f["title"].startswith("TEST_")]
        assert len(real) == 16
        for f in real:
            assert f["category"] in CATS, f
            assert isinstance(f["audiences"], list) and set(f["audiences"]) <= GROUPS, f
            assert "audience" not in f and "_id" not in f

    def test_employee_no_group_sees_only_everyone(self):
        db.users.update_one({"user_id": EMP_ID}, {"$unset": {"staff_group": ""}})
        forms = get_forms(EMP)
        assert {f["title"] for f in forms} == EVERYONE_TITLES
        assert all(f["audiences"] == [] for f in forms)


# --- staff group assignment
class TestStaffGroup:
    def test_employee_forbidden(self):
        r = requests.patch(f"{API}/users/{EMP_ID}/group", headers=EMP, json={"staff_group": "support_office"})
        assert r.status_code == 403

    def test_invalid_group_400(self):
        r = requests.patch(f"{API}/users/{EMP_ID}/group", headers=ADMIN, json={"staff_group": "bogus"})
        assert r.status_code == 400

    def test_unknown_user_404(self):
        r = requests.patch(f"{API}/users/user_nope_xyz/group", headers=ADMIN, json={"staff_group": "support_office"})
        assert r.status_code == 404

    def test_set_then_clear(self):
        r = requests.patch(f"{API}/users/{EMP_ID}/group", headers=ADMIN, json={"staff_group": "therapist_employee"})
        assert r.status_code == 200 and r.json()["staff_group"] == "therapist_employee"
        assert db.users.find_one({"user_id": EMP_ID})["staff_group"] == "therapist_employee"
        r = requests.patch(f"{API}/users/{EMP_ID}/group", headers=ADMIN, json={"staff_group": None})
        assert r.status_code == 200 and r.json()["staff_group"] is None


# --- form PATCH/POST with category + audiences
class TestFormEdit:
    def test_patch_validation(self):
        fid = get_forms(ADMIN)[0]["form_id"]
        assert requests.patch(f"{API}/forms/{fid}", headers=ADMIN, json={"category": "Nope"}).status_code == 400
        assert requests.patch(f"{API}/forms/{fid}", headers=ADMIN, json={"audiences": ["bogus"]}).status_code == 400
        assert requests.patch(f"{API}/forms/{fid}", headers=EMP, json={"category": "HR"}).status_code == 403
        assert requests.patch(f"{API}/forms/form_nope", headers=ADMIN, json={"category": "HR"}).status_code == 404

    def test_post_validation(self):
        base = {"title": "TEST_bad", "url": "https://form.jotform.com/123"}
        assert requests.post(f"{API}/forms", headers=ADMIN, json={**base, "category": "Nope"}).status_code == 400
        assert requests.post(f"{API}/forms", headers=ADMIN, json={**base, "audiences": ["x"]}).status_code == 400
        assert requests.post(f"{API}/forms", headers=EMP, json=base).status_code == 403
        assert db.forms.count_documents({"title": "TEST_bad"}) == 0

    def test_create_patch_visibility_delete(self):
        r = requests.post(f"{API}/forms", headers=ADMIN, json={
            "title": "TEST_Therapist Form", "url": "https://form.jotform.com/999000111", "description": "d",
            "category": "Compliance", "audiences": ["therapist_employee"]})
        assert r.status_code == 200, r.text
        f = r.json()
        assert f["category"] == "Compliance" and f["audiences"] == ["therapist_employee"]
        fid = f["form_id"]
        # hidden for no-group employee, visible once group set
        db.users.update_one({"user_id": EMP_ID}, {"$unset": {"staff_group": ""}})
        assert fid not in {x["form_id"] for x in get_forms(EMP)}
        requests.patch(f"{API}/users/{EMP_ID}/group", headers=ADMIN, json={"staff_group": "therapist_employee"})
        assert fid in {x["form_id"] for x in get_forms(EMP)}
        # wrong group -> hidden
        requests.patch(f"{API}/users/{EMP_ID}/group", headers=ADMIN, json={"staff_group": "support_office"})
        assert fid not in {x["form_id"] for x in get_forms(EMP)}
        # full PATCH
        r = requests.patch(f"{API}/forms/{fid}", headers=ADMIN, json={
            "title": "TEST_Renamed", "url": "999000222", "description": "new", "category": "HR",
            "audiences": ["support_office", "support_office", "therapist_contractor"]})
        assert r.status_code == 200, r.text
        g = r.json()
        assert g["title"] == "TEST_Renamed" and g["url"] == "https://form.jotform.com/999000222"
        assert g["category"] == "HR" and g["audiences"] == ["support_office", "therapist_contractor"]
        assert fid in {x["form_id"] for x in get_forms(EMP)}
        # audiences [] -> everyone
        requests.patch(f"{API}/forms/{fid}", headers=ADMIN, json={"audiences": []})
        requests.patch(f"{API}/users/{EMP_ID}/group", headers=ADMIN, json={"staff_group": None})
        assert fid in {x["form_id"] for x in get_forms(EMP)}
        assert requests.delete(f"{API}/forms/{fid}", headers=ADMIN).status_code == 200
        assert fid not in {x["form_id"] for x in get_forms(ADMIN)}


# --- migration
class TestMigration:
    def test_support_office_users(self):
        for e in ("johanna", "clair", "sienna"):
            u = db.users.find_one({"email": f"{e}@aspireandgrow.com.au"}, {"_id": 0})
            assert u is not None, e
            assert u.get("staff_group") == "support_office", u

    def test_no_legacy_fields(self):
        assert db.users.count_documents({"support_office": {"$exists": True}}) == 0
        assert db.forms.count_documents({"audience": {"$exists": True}}) == 0
        assert db.forms.count_documents({"audiences": {"$exists": False}}) == 0
        assert db.forms.count_documents({"category": {"$exists": False}}) == 0
