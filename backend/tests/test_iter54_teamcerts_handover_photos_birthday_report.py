"""Iter54: team certificate alerts (60d), handover photos, participant birthdays, monthly case note report + regression."""
import io
import os
import uuid
from datetime import date, datetime, timedelta, timezone

import pytest
import requests
from pymongo import MongoClient


def _env(path, key):
    for line in open(path):
        if line.startswith(key + "="):
            return line.split("=", 1)[1].strip().strip('"')


BASE_URL = (os.environ.get("EXPO_PUBLIC_BACKEND_URL") or _env("/app/frontend/.env", "EXPO_PUBLIC_BACKEND_URL")).rstrip("/")
MONGO_URL = _env("/app/backend/.env", "MONGO_URL")
DB_NAME = _env("/app/backend/.env", "DB_NAME")
ADMIN = {"Authorization": "Bearer test_session_admin"}
EMP = {"Authorization": "Bearer test_session_employee"}
PID = "par_960475e91169"
PNAME = "Test Birthday Person"
PNG = (b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15\xc4\x89"
       b"\x00\x00\x00\rIDATx\x9cc\xf8\x0f\x00\x00\x01\x01\x00\x05\x18\xd8N\x00\x00\x00\x00IEND\xaeB`\x82")


@pytest.fixture(scope="module")
def db():
    c = MongoClient(MONGO_URL)
    yield c[DB_NAME]
    c.close()


def perth_today():
    return (datetime.now(timezone.utc) + timedelta(hours=8)).date()


# ---- Team certificates ----
class TestTeamCerts:
    def test_employee_forbidden(self):
        r = requests.get(f"{BASE_URL}/api/certificates/team", headers=EMP)
        assert r.status_code == 403

    def test_admin_hidden_excluded(self):
        r = requests.get(f"{BASE_URL}/api/certificates/team", headers=ADMIN)
        assert r.status_code == 200
        d = r.json()
        assert d["warning_days"] == 60
        assert all(c["owner_id"] != "user_testemp001" for c in d["certificates"])  # hidden user

    def test_unhidden_user_with_certs(self, db):
        today = date.today()
        certs = [
            {"cert_id": "cert_TEST_45", "owner_id": "user_testemp001", "owner_name": "x", "title": "TEST_45d",
             "expiry_date": (today + timedelta(days=45)).isoformat(), "is_deleted": False, "storage_path": "x"},
            {"cert_id": "cert_TEST_75", "owner_id": "user_testemp001", "owner_name": "x", "title": "TEST_75d",
             "expiry_date": (today + timedelta(days=75)).isoformat(), "is_deleted": False, "storage_path": "x"},
            {"cert_id": "cert_TEST_exp", "owner_id": "user_testemp001", "owner_name": "x", "title": "TEST_exp",
             "expiry_date": (today - timedelta(days=3)).isoformat(), "is_deleted": False, "storage_path": "x"},
        ]
        db.certificates.insert_many([dict(c) for c in certs])
        db.users.update_one({"user_id": "user_testemp001"}, {"$set": {"hidden": False}})
        try:
            d = requests.get(f"{BASE_URL}/api/certificates/team", headers=ADMIN).json()
            mine = {c["cert_id"]: c for c in d["certificates"] if c["owner_id"] == "user_testemp001"}
            assert "cert_TEST_45" in mine and mine["cert_TEST_45"]["status"] == "expiring"
            assert mine["cert_TEST_45"]["days_left"] == 45
            assert mine["cert_TEST_45"]["owner_name"]
            assert "storage_path" not in mine["cert_TEST_45"]
            assert "cert_TEST_75" not in mine
            assert mine["cert_TEST_exp"]["status"] == "expired" and mine["cert_TEST_exp"]["days_left"] == -3
            exps = [c["expiry_date"] for c in d["certificates"]]
            assert exps == sorted(exps)
            dash = requests.get(f"{BASE_URL}/api/dashboard", headers=ADMIN).json()
            t = dash["team_cert_alerts"]
            assert t["expired"] >= 1 and t["expiring"] >= 2  # 45d + existing First Aid
            assert len(t["soonest"]) <= 3
        finally:
            db.certificates.delete_many({"cert_id": {"$in": [c["cert_id"] for c in certs]}})
            db.users.update_one({"user_id": "user_testemp001"}, {"$set": {"hidden": True}})

    def test_dashboard_null_for_employee(self):
        r = requests.get(f"{BASE_URL}/api/dashboard", headers=EMP)
        assert r.status_code == 200 and r.json()["team_cert_alerts"] is None

    def test_dashboard_admin_shape(self):
        t = requests.get(f"{BASE_URL}/api/dashboard", headers=ADMIN).json()["team_cert_alerts"]
        assert set(t) >= {"expired", "expiring", "soonest"}


# ---- Handover photos ----
class TestHandoverPhotos:
    sub = f"TEST_sub_{uuid.uuid4().hex[:6]}"

    def _post(self, headers, ctype="image/png", data=PNG, sub=None):
        return requests.post(f"{BASE_URL}/api/caseload/handover/photos", headers=headers,
                             data={"participant": PNAME, "submission_id": sub or self.sub, "caption": "TEST caption"},
                             files={"file": ("p.png", io.BytesIO(data), ctype)})

    def test_non_image_rejected(self):
        r = self._post(ADMIN, ctype="application/pdf", data=b"%PDF-1.4")
        assert r.status_code == 400

    def test_worker_not_assigned_403(self):
        assert self._post(EMP).status_code == 403

    def test_upload_get_delete(self, db):
        r = self._post(ADMIN)
        assert r.status_code == 200, r.text
        ph = r.json()
        assert ph["photo_id"].startswith("hph_") and ph["caption"] == "TEST caption"
        g = requests.get(f"{BASE_URL}/api/caseload/handover/photos/{ph['photo_id']}?token=test_session_admin")
        assert g.status_code == 200 and g.headers["content-type"].startswith("image/png") and g.content[:4] == b"\x89PNG"
        assert requests.get(f"{BASE_URL}/api/caseload/handover/photos/{ph['photo_id']}?token=test_session_employee").status_code == 403
        assert requests.get(f"{BASE_URL}/api/caseload/handover/photos/{ph['photo_id']}").status_code == 401
        assert requests.delete(f"{BASE_URL}/api/caseload/handover/photos/{ph['photo_id']}", headers=EMP).status_code == 403
        d = requests.delete(f"{BASE_URL}/api/caseload/handover/photos/{ph['photo_id']}", headers=ADMIN)
        assert d.status_code == 200 and d.json()["ok"] is True
        assert requests.get(f"{BASE_URL}/api/caseload/handover/photos/{ph['photo_id']}?token=test_session_admin").status_code == 404

    def test_assigned_worker_upload_and_delete_own(self, db):
        db.participants.update_one({"participant_id": PID}, {"$addToSet": {"assigned_ids": "user_testemp001"}})
        try:
            r = self._post(EMP)
            assert r.status_code == 200, r.text
            pid = r.json()["photo_id"]
            assert requests.get(f"{BASE_URL}/api/caseload/handover/photos/{pid}?token=test_session_employee").status_code == 200
            assert requests.delete(f"{BASE_URL}/api/caseload/handover/photos/{pid}", headers=EMP).status_code == 200
        finally:
            db.participants.update_one({"participant_id": PID}, {"$pull": {"assigned_ids": "user_testemp001"}})
            db.handover_photos.delete_many({"submission_id": self.sub})

    def test_limit_10(self, db):
        sub = f"TEST_lim_{uuid.uuid4().hex[:6]}"
        db.handover_photos.insert_many([{"photo_id": f"hph_TEST{i}", "submission_id": sub, "participant": "test birthday person",
                                         "caption": "", "storage_path": "x", "content_type": "image/png",
                                         "by_id": "x", "by_name": "x", "at": "2026"} for i in range(10)])
        try:
            assert self._post(ADMIN, sub=sub).status_code == 400
        finally:
            db.handover_photos.delete_many({"submission_id": sub})


# ---- Participant birthdays ----
class TestBirthday:
    def test_participant_birthday_today(self, db):
        t = perth_today()
        db.participants.update_one({"participant_id": PID}, {"$set": {"profile.date_of_birth": t.replace(year=t.year - 36).isoformat()}})
        d = requests.get(f"{BASE_URL}/api/participants/{PID}", headers=ADMIN).json()
        assert d["profile"]["date_of_birth"] == t.replace(year=t.year - 36).isoformat()
        assert d["birthday"]["in_days"] == 0 and d["birthday"]["turns"] == 36 and d["birthday"]["date"] == t.isoformat()

    @pytest.mark.parametrize("bad", ["2026-13-01", "abc", "03-11-1990", "1800-01-01", "2999-01-01"])
    def test_bad_dob_400(self, bad):
        r = requests.put(f"{BASE_URL}/api/participants/{PID}/profile", headers=ADMIN, json={"date_of_birth": bad})
        assert r.status_code == 400, f"{bad} -> {r.status_code}"

    def test_put_dob_in_5_days_and_caseload_badge(self):
        t = perth_today()
        orig = requests.get(f"{BASE_URL}/api/participants/{PID}", headers=ADMIN).json()["profile"]
        dob = (t + timedelta(days=5)).replace(year=t.year - 40).isoformat()
        body = {k: v for k, v in orig.items() if k not in ("updated_by", "updated_at")}
        r = requests.put(f"{BASE_URL}/api/participants/{PID}/profile", headers=ADMIN, json={**body, "date_of_birth": dob})
        assert r.status_code == 200 and r.json()["date_of_birth"] == dob
        try:
            g = requests.get(f"{BASE_URL}/api/participants/{PID}", headers=ADMIN).json()
            assert g["birthday"]["in_days"] == 5 and g["birthday"]["turns"] == 40
            cl = requests.get(f"{BASE_URL}/api/caseload", headers=ADMIN, timeout=90).json()
            rows = cl.get("participants") if isinstance(cl, dict) else cl
            row = next((p for p in rows if p["name"] == PNAME), None)
            if row is not None:
                assert row["birthday"] and row["birthday"]["in_days"] == 5
            # 10 days out -> no badge
            dob10 = (t + timedelta(days=10)).replace(year=t.year - 40).isoformat()
            requests.put(f"{BASE_URL}/api/participants/{PID}/profile", headers=ADMIN, json={**body, "date_of_birth": dob10})
            assert requests.get(f"{BASE_URL}/api/participants/{PID}", headers=ADMIN).json()["birthday"]["in_days"] == 10
        finally:
            requests.put(f"{BASE_URL}/api/participants/{PID}/profile", headers=ADMIN,
                         json={**body, "date_of_birth": t.replace(year=t.year - 36).isoformat()})

    def test_employee_cannot_edit(self):
        r = requests.put(f"{BASE_URL}/api/participants/{PID}/profile", headers=EMP, json={"date_of_birth": "1990-01-01"})
        assert r.status_code == 403


# ---- Monthly report ----
class TestMonthlyReport:
    def test_pdf_admin(self):
        r = requests.get(f"{BASE_URL}/api/caseload/monthly-report/pdf?token=test_session_admin", timeout=90)
        assert r.status_code == 200 and r.headers["content-type"] == "application/pdf" and r.content[:4] == b"%PDF"

    def test_pdf_bearer_month(self):
        r = requests.get(f"{BASE_URL}/api/caseload/monthly-report/pdf?month=2026-09", headers=ADMIN, timeout=90)
        assert r.status_code == 200 and r.content[:4] == b"%PDF"

    def test_pdf_employee_403(self):
        assert requests.get(f"{BASE_URL}/api/caseload/monthly-report/pdf?token=test_session_employee").status_code == 403

    def test_pdf_no_token_403(self):
        assert requests.get(f"{BASE_URL}/api/caseload/monthly-report/pdf").status_code == 403

    @pytest.mark.parametrize("bad", ["bad", "2026-13", "2099-01"])
    def test_pdf_bad_month(self, bad):
        assert requests.get(f"{BASE_URL}/api/caseload/monthly-report/pdf?month={bad}&token=test_session_admin").status_code == 400

    def test_email_and_shared_link(self, db):
        r = requests.post(f"{BASE_URL}/api/caseload/monthly-report/email", headers=ADMIN, timeout=90)
        assert r.status_code == 200, r.text
        assert r.json()["sent_to"] == "admin.test@example.com"
        link = db.monthly_report_links.find_one({"user_id": "user_testadmin01"}, sort=[("created_at", -1)])
        s = requests.get(f"{BASE_URL}/api/caseload/monthly-report/shared/{link['token']}", timeout=90)
        assert s.status_code == 200 and s.content[:4] == b"%PDF"
        assert requests.get(f"{BASE_URL}/api/caseload/monthly-report/shared/nope").status_code == 404

    def test_email_employee_403(self):
        assert requests.post(f"{BASE_URL}/api/caseload/monthly-report/email", headers=EMP).status_code == 403


# ---- Regression ----
@pytest.mark.parametrize("path,headers,code", [
    ("/api/caseload", ADMIN, 200), ("/api/caseload/streaks", ADMIN, 200), ("/api/caseload/missed", ADMIN, 200),
    ("/api/certificates", ADMIN, 200), ("/api/certificates", EMP, 200), ("/api/caseload", EMP, 200)])
def test_regression(path, headers, code):
    r = requests.get(f"{BASE_URL}{path}", headers=headers, timeout=90)
    assert r.status_code == code, f"{path}: {r.status_code} {r.text[:200]}"
