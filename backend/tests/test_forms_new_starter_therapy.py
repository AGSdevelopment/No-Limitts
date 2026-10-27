# Iteration 7: New Starter + Therapy Triage sections, Continuous Improvement (Support Office), staff-group visibility
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
NEW_STARTER = {"Two Week Check-in", "Authority to Deduct Wages", "Secondary Employment Declaration",
               "Asset Register Submission"}
THERAPY = {"Rejection Record", "Pre-Referral / Enquiry Form"}
EMP_EXPECTED = NEW_STARTER | {"Request for Support", "Leave Request & Absence Notification",
                              "CPD Certificate Submission", "Conflict of Interest Reporting"}


def forms(h):
    r = requests.get(f"{API}/forms", headers=h)
    assert r.status_code == 200, r.text
    return r.json()


def cats(items):
    out = {}
    for f in items:
        out.setdefault(f["category"], set()).add(f["title"])
    return out


@pytest.fixture(scope="module", autouse=True)
def restore():
    before = db.users.find_one({"user_id": EMP_ID}, {"_id": 0, "staff_group": 1}) or {}
    yield
    if before.get("staff_group") is not None:
        db.users.update_one({"user_id": EMP_ID}, {"$set": {"staff_group": before["staff_group"]}})
    else:
        db.users.update_one({"user_id": EMP_ID}, {"$set": {"staff_group": None}})


class TestAdminForms:
    def test_admin_16_forms_no_dupes(self):
        f = forms(ADMIN)
        titles = [x["title"] for x in f]
        assert len(f) == 16 and len(set(titles)) == 16, titles
        assert all("_id" not in x for x in f)

    def test_new_starter_section(self):
        f = forms(ADMIN)
        c = cats(f)
        assert c.get("New Starter") == NEW_STARTER, c.get("New Starter")
        assert all(x["audiences"] == [] for x in f if x["category"] == "New Starter")
        # Asset Register moved, not duplicated
        assert "Asset Register Submission" not in c.get("HR", set())

    def test_therapy_triage_section(self):
        f = forms(ADMIN)
        assert cats(f).get("Therapy Triage") == THERAPY
        assert all(x["audiences"] == ["support_office"] for x in f if x["category"] == "Therapy Triage")

    def test_continuous_improvement(self):
        ci = [x for x in forms(ADMIN) if x["title"] == "Continuous Improvement"]
        assert len(ci) == 1
        assert ci[0]["category"] == "Support Office" and ci[0]["audiences"] == ["support_office"]

    def test_referral_triage_empty(self):
        assert "Referral Triage" not in cats(forms(ADMIN))


class TestEmployeeVisibility:
    def test_no_group(self):
        r = requests.patch(f"{API}/users/{EMP_ID}/group", headers=ADMIN, json={"staff_group": None})
        assert r.status_code == 200, r.text
        f = forms(EMP)
        assert {x["title"] for x in f} == EMP_EXPECTED
        c = cats(f)
        assert set(c) == {"Day-to-Day", "New Starter", "HR", "Compliance"}
        assert c["HR"] == {"Leave Request & Absence Notification", "CPD Certificate Submission"}
        assert all(x["audiences"] == [] for x in f)

    def test_support_office_group(self):
        r = requests.patch(f"{API}/users/{EMP_ID}/group", headers=ADMIN, json={"staff_group": "support_office"})
        assert r.status_code == 200, r.text
        try:
            f = forms(EMP)
            c = cats(f)
            assert c.get("Therapy Triage") == THERAPY
            assert "Continuous Improvement" in c.get("Support Office", set())
            assert EMP_EXPECTED <= {x["title"] for x in f}
            assert len(f) == 16
        finally:
            r = requests.patch(f"{API}/users/{EMP_ID}/group", headers=ADMIN, json={"staff_group": None})
            assert r.status_code == 200
        assert {x["title"] for x in forms(EMP)} == EMP_EXPECTED

    def test_other_group_no_therapy(self):
        r = requests.patch(f"{API}/users/{EMP_ID}/group", headers=ADMIN, json={"staff_group": "therapist_employee"})
        assert r.status_code == 200
        try:
            c = cats(forms(EMP))
            assert "Therapy Triage" not in c and "Support Office" not in c
        finally:
            requests.patch(f"{API}/users/{EMP_ID}/group", headers=ADMIN, json={"staff_group": None})

    def test_new_categories_accepted_on_patch_validation(self):
        r = requests.post(f"{API}/forms", headers=EMP, json={"title": "TEST_x", "url": "https://form.jotform.com/1",
                                                              "category": "New Starter"})
        assert r.status_code == 403
