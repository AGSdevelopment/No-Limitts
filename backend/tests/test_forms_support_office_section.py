# Iteration 6: 'Support Office' form section, new forms (Asset Register, CPD, Agenda Item), Request for Support -> Day-to-Day
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
EMP_EXPECTED = {"Request for Support", "Leave Request & Absence Notification", "Asset Register Submission",
                "CPD Certificate Submission", "Conflict of Interest Reporting", "Two Week Check-in",
                "Authority to Deduct Wages", "Secondary Employment Declaration"}


def forms(h):
    r = requests.get(f"{API}/forms", headers=h)
    assert r.status_code == 200, r.text
    return r.json()


def by_title(items):
    return {f["title"]: f for f in items}


@pytest.fixture(scope="module", autouse=True)
def restore():
    emp_before = db.users.find_one({"user_id": EMP_ID}, {"_id": 0, "staff_group": 1}) or {}
    forms_before = list(db.forms.find({}, {"_id": 0}))
    ids_before = {f["form_id"] for f in forms_before}
    yield
    if "staff_group" in emp_before:
        db.users.update_one({"user_id": EMP_ID}, {"$set": {"staff_group": emp_before["staff_group"]}})
    else:
        db.users.update_one({"user_id": EMP_ID}, {"$unset": {"staff_group": ""}})
    for f in forms_before:
        db.forms.replace_one({"form_id": f["form_id"]}, f)
    new_ids = [f["form_id"] for f in db.forms.find({}, {"form_id": 1}) if f["form_id"] not in ids_before]
    if new_ids:
        db.forms.delete_many({"form_id": {"$in": new_ids}})


class TestSeededForms:
    def test_admin_new_forms_and_categories(self):
        f = by_title(forms(ADMIN))
        assert f["Request for Support"]["category"] == "Day-to-Day" and f["Request for Support"]["audiences"] == []
        assert f["Asset Register Submission"]["category"] == "New Starter" and f["Asset Register Submission"]["audiences"] == []
        assert f["CPD Certificate Submission"]["category"] == "HR" and f["CPD Certificate Submission"]["audiences"] == []
        ag = f["Agenda Item Request Form"]
        assert ag["category"] == "Support Office" and ag["audiences"] == ["support_office"]
        assert all("_id" not in x for x in f.values())

    def test_no_duplicate_titles(self):
        titles = [x["title"] for x in forms(ADMIN)]
        assert len(titles) == len(set(titles)), titles

    def test_employee_no_group_visibility(self):
        db.users.update_one({"user_id": EMP_ID}, {"$unset": {"staff_group": ""}})
        titles = {x["title"] for x in forms(EMP)}
        assert titles == EMP_EXPECTED, titles

    def test_employee_support_office_sees_agenda(self):
        db.users.update_one({"user_id": EMP_ID}, {"$set": {"staff_group": "support_office"}})
        titles = {x["title"] for x in forms(EMP)}
        assert "Agenda Item Request Form" in titles and EMP_EXPECTED <= titles
        db.users.update_one({"user_id": EMP_ID}, {"$unset": {"staff_group": ""}})


class TestSupportOfficeCategory:
    def test_post_patch_support_office(self):
        r = requests.post(f"{API}/forms", headers=ADMIN, json={
            "title": "TEST_SO form", "url": "https://form.jotform.com/000000000", "category": "Support Office",
            "audiences": ["support_office"]})
        assert r.status_code in (200, 201), r.text
        fid = r.json()["form_id"]
        assert r.json()["category"] == "Support Office"
        try:
            r = requests.patch(f"{API}/forms/{fid}", headers=ADMIN, json={"category": "HR"})
            assert r.status_code == 200 and r.json()["category"] == "HR"
            r = requests.patch(f"{API}/forms/{fid}", headers=ADMIN, json={"category": "Support Office"})
            assert r.status_code == 200, r.text
            got = by_title(forms(ADMIN))["TEST_SO form"]
            assert got["category"] == "Support Office"
            # invalid section still rejected
            r = requests.patch(f"{API}/forms/{fid}", headers=ADMIN, json={"category": "support office"})
            assert r.status_code == 400
        finally:
            d = requests.delete(f"{API}/forms/{fid}", headers=ADMIN)
            assert d.status_code in (200, 204)
        assert "TEST_SO form" not in by_title(forms(ADMIN))

    def test_employee_cannot_create(self):
        r = requests.post(f"{API}/forms", headers=EMP, json={
            "title": "TEST_emp", "url": "https://form.jotform.com/1", "category": "Support Office"})
        assert r.status_code == 403
