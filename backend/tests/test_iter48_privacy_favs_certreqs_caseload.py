# Iteration 48: staff privacy, form favourites, NDIS cert requirements, team admin data, caseload permissions
import os
import uuid
import pytest
import requests

BASE_URL = os.environ.get("EXPO_PUBLIC_BACKEND_URL", os.environ.get("EXPO_BACKEND_URL", "")).rstrip("/")
ADMIN = {"Authorization": "Bearer test_session_admin"}
ADMIN2 = {"Authorization": "Bearer test_session_admin2"}
EMP = {"Authorization": "Bearer test_session_employee"}
NON_ADMIN_KEYS = {"user_id", "name", "picture", "job_title", "user_type", "role", "start_date", "staff_group"}


# ---- (1) Privacy on GET /api/users
class TestUsersPrivacy:
    def test_employee_users_no_contact(self):
        r = requests.get(f"{BASE_URL}/api/users", headers=EMP)
        assert r.status_code == 200
        data = r.json()
        assert isinstance(data, list) and len(data) > 0
        for u in data:
            assert set(u.keys()) == NON_ADMIN_KEYS, u.keys()
            assert "email" not in u and "phone" not in u and "missing_certs" not in u

    def test_admin_users_have_email_and_missing_certs(self):
        r = requests.get(f"{BASE_URL}/api/users", headers=ADMIN)
        assert r.status_code == 200
        data = r.json()
        assert len(data) > 0
        for u in data:
            assert "email" in u
            assert isinstance(u.get("missing_certs"), list)
            assert "password_hash" not in u and "_id" not in u

    def test_unauth_users(self):
        assert requests.get(f"{BASE_URL}/api/users").status_code == 401


# ---- (2) Form favourites
@pytest.fixture
def emp_form():
    forms = requests.get(f"{BASE_URL}/api/forms", headers=EMP).json()
    assert forms, "employee sees no forms"
    f = next(x for x in forms if not x["favourite"])
    yield f
    # leave un-toggled
    now = {x["form_id"]: x["favourite"] for x in requests.get(f"{BASE_URL}/api/forms", headers=EMP).json()}
    if now.get(f["form_id"]):
        requests.post(f"{BASE_URL}/api/forms/{f['form_id']}/favourite", headers=EMP)


class TestFormFavourites:
    def test_forms_have_favourite_bool(self):
        for h in (EMP, ADMIN):
            forms = requests.get(f"{BASE_URL}/api/forms", headers=h).json()
            assert all(isinstance(f.get("favourite"), bool) for f in forms)

    def test_toggle_on_off_employee(self, emp_form):
        fid = emp_form["form_id"]
        r = requests.post(f"{BASE_URL}/api/forms/{fid}/favourite", headers=EMP)
        assert r.status_code == 200 and r.json() == {"favourite": True}
        forms = {x["form_id"]: x for x in requests.get(f"{BASE_URL}/api/forms", headers=EMP).json()}
        assert forms[fid]["favourite"] is True
        # per-user: admin not affected
        adm = {x["form_id"]: x for x in requests.get(f"{BASE_URL}/api/forms", headers=ADMIN).json()}
        assert adm[fid]["favourite"] is False
        r = requests.post(f"{BASE_URL}/api/forms/{fid}/favourite", headers=EMP)
        assert r.json() == {"favourite": False}
        forms = {x["form_id"]: x for x in requests.get(f"{BASE_URL}/api/forms", headers=EMP).json()}
        assert forms[fid]["favourite"] is False

    def test_toggle_unknown_form_404(self):
        r = requests.post(f"{BASE_URL}/api/forms/form_nope_{uuid.uuid4().hex[:6]}/favourite", headers=EMP)
        assert r.status_code == 404

    def test_employee_cannot_fav_restricted_form(self):
        admin_forms = requests.get(f"{BASE_URL}/api/forms", headers=ADMIN).json()
        emp_ids = {x["form_id"] for x in requests.get(f"{BASE_URL}/api/forms", headers=EMP).json()}
        hidden = [f for f in admin_forms if f["form_id"] not in emp_ids]
        if not hidden:
            pytest.skip("no restricted form for employee")
        r = requests.post(f"{BASE_URL}/api/forms/{hidden[0]['form_id']}/favourite", headers=EMP)
        assert r.status_code == 404

    def test_fav_unauth(self):
        forms = requests.get(f"{BASE_URL}/api/forms", headers=ADMIN).json()
        assert requests.post(f"{BASE_URL}/api/forms/{forms[0]['form_id']}/favourite").status_code == 401


# ---- (3) Cert requirements seed
class TestCertRequirements:
    def test_seeded_groups(self):
        r = requests.get(f"{BASE_URL}/api/cert-requirements", headers=ADMIN)
        assert r.status_code == 200
        g = r.json()["groups"]
        print("groups:", g)
        assert len(g["support_worker"]) == 7
        assert {"NDIS Worker Screening", "NDIS Worker Orientation", "First Aid", "CPR", "Manual Handling",
                "Medication Administration", "Driver's Licence"} == set(g["support_worker"])
        assert set(g["support_coordinator"]) == {"NDIS Worker Screening", "NDIS Worker Orientation"}
        assert set(g["support_office"]) == {"NDIS Worker Screening", "NDIS Worker Orientation"}

    def test_employee_forbidden(self):
        assert requests.get(f"{BASE_URL}/api/cert-requirements", headers=EMP).status_code == 403


# ---- (5) Caseload
class TestCaseload:
    def test_admin_not_configured(self):
        r = requests.get(f"{BASE_URL}/api/caseload", headers=ADMIN)
        assert r.status_code == 200
        assert r.json() == {"configured": False, "participants": []}

    def test_admin2_ok(self):
        assert requests.get(f"{BASE_URL}/api/caseload", headers=ADMIN2).status_code == 200

    def test_support_worker_forbidden(self):
        assert requests.get(f"{BASE_URL}/api/caseload", headers=EMP).status_code == 403

    def test_unauth(self):
        assert requests.get(f"{BASE_URL}/api/caseload").status_code == 401


# ---- Coordinator access + missing_certs + regression add/type/reset/delete
class TestCoordinatorAndRegression:
    def test_coordinator_flow(self):
        email = f"test_coord_{uuid.uuid4().hex[:6]}@example.com"
        r = requests.post(f"{BASE_URL}/api/users", headers=ADMIN,
                          json={"name": "TEST_ Coord", "email": email, "user_type": "support_worker", "job_title": "TEST job"})
        assert r.status_code == 200, r.text
        uid = r.json()["user"]["user_id"]
        assert r.json()["temporary_password"]
        try:
            users = {u["user_id"]: u for u in requests.get(f"{BASE_URL}/api/users", headers=ADMIN).json()}
            assert len(users[uid]["missing_certs"]) == 7
            # employee sees job title but no email
            emp_view = {u["user_id"]: u for u in requests.get(f"{BASE_URL}/api/users", headers=EMP).json()}
            assert emp_view[uid]["job_title"] == "TEST job" and "email" not in emp_view[uid]
            # change to coordinator -> 2 missing
            r = requests.patch(f"{BASE_URL}/api/users/{uid}/type", headers=ADMIN, json={"user_type": "support_coordinator"})
            assert r.status_code == 200 and r.json()["user"]["staff_group"] == "support_coordinator"
            users = {u["user_id"]: u for u in requests.get(f"{BASE_URL}/api/users", headers=ADMIN).json()}
            assert set(users[uid]["missing_certs"]) == {"NDIS Worker Screening", "NDIS Worker Orientation"}
            # coordinator login via password is gone (MS only) -> create a session directly is not possible; back to SW
            r = requests.patch(f"{BASE_URL}/api/users/{uid}/type", headers=ADMIN, json={"user_type": "support_worker"})
            assert r.status_code == 200 and r.json()["temporary_password"]
            r = requests.post(f"{BASE_URL}/api/users/{uid}/reset-password", headers=ADMIN)
            assert r.status_code == 200 and r.json()["temporary_password"]
        finally:
            d = requests.delete(f"{BASE_URL}/api/users/{uid}", headers=ADMIN)
            assert d.status_code == 200
        users = {u["user_id"] for u in requests.get(f"{BASE_URL}/api/users", headers=ADMIN).json()}
        assert uid not in users
