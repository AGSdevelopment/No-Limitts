# Iteration 15: imported policies + policy file, CPD report PDF (with evidence), CPD edit, Drive spaces empty
import io
import os

import pymupdf
import pytest
import requests


def _base():
    url = os.environ.get("EXPO_PUBLIC_BACKEND_URL") or os.environ.get("EXPO_BACKEND_URL")
    if not url:
        for line in open("/app/frontend/.env"):
            if line.startswith("EXPO_PUBLIC_BACKEND_URL="):
                url = line.split("=", 1)[1].strip().strip('"')
    return url.rstrip("/")


BASE_URL = _base()
EMP = {"Authorization": "Bearer test_session_employee"}
ADMIN = {"Authorization": "Bearer test_session_admin"}


# Policies: imported list + attached file served to employee
class TestPolicies:
    def test_policies_list_contains_imported(self):
        r = requests.get(f"{BASE_URL}/api/policies", headers=EMP, timeout=30)
        assert r.status_code == 200
        data = r.json()
        titles = [p["title"] for p in data]
        with_file = [p for p in data if p.get("drive_file")]
        print(f"total={len(data)} with_file={len(with_file)}")
        assert len(with_file) >= 27
        assert any("Access to Office" in t for t in titles)
        assert any("Referral Process" in t for t in titles)
        assert all("_id" not in p for p in data)
        cats = {p.get("category") for p in data}
        print("categories:", cats)

    def test_policy_file_pdf_for_employee(self):
        data = requests.get(f"{BASE_URL}/api/policies", headers=EMP, timeout=30).json()
        p = next(p for p in data if p.get("drive_file") and "Referral" in p["title"])
        r = requests.get(f"{BASE_URL}/api/policies/{p['policy_id']}/file?token=test_session_employee", timeout=60)
        assert r.status_code == 200
        assert "application/pdf" in r.headers.get("content-type", "")
        assert r.content[:4] == b"%PDF"

    def test_policy_file_requires_auth(self):
        data = requests.get(f"{BASE_URL}/api/policies", headers=EMP, timeout=30).json()
        p = next(p for p in data if p.get("drive_file"))
        r = requests.get(f"{BASE_URL}/api/policies/{p['policy_id']}/file", timeout=30)
        assert r.status_code == 401


# CPD report with evidence + edit
class TestCpdReport:
    @pytest.fixture(scope="class")
    def log(self):
        r = requests.post(f"{BASE_URL}/api/cpd", headers=EMP, json={
            "title": "TEST_Report evidence", "provider": "TEST", "date": "2026-03-10",
            "hours": 1.25, "category": "Course", "notes": ""}, timeout=30)
        assert r.status_code in (200, 201), r.text
        lg = r.json()
        with open("/tmp/cpd.png", "rb") as f:
            up = requests.post(f"{BASE_URL}/api/cpd/{lg['log_id']}/file", headers=EMP,
                               files={"file": ("cpd.png", f, "image/png")}, timeout=60)
        assert up.status_code == 200, up.text
        yield lg
        requests.delete(f"{BASE_URL}/api/cpd/{lg['log_id']}", headers=EMP, timeout=30)

    def test_report_pdf_with_evidence(self, log):
        r = requests.get(f"{BASE_URL}/api/cpd/report?year=2026&token=test_session_employee", timeout=90)
        assert r.status_code == 200
        assert "application/pdf" in r.headers["content-type"]
        doc = pymupdf.open("pdf", r.content)
        print("pages:", doc.page_count, "disposition:", r.headers.get("content-disposition"))
        assert doc.page_count >= 2
        text = doc[0].get_text()
        assert "CPD Report 2026" in text
        assert "TEST_Report evidence" in text

    def test_report_requires_auth(self):
        r = requests.get(f"{BASE_URL}/api/cpd/report?year=2026", timeout=30)
        assert r.status_code == 401

    def test_patch_cpd_updates_hours(self, log):
        r = requests.patch(f"{BASE_URL}/api/cpd/{log['log_id']}", headers=EMP, json={
            "title": "TEST_Report evidence", "provider": "TEST", "date": "2026-03-10",
            "hours": 2.75, "category": "Course", "notes": ""}, timeout=30)
        assert r.status_code == 200, r.text
        g = requests.get(f"{BASE_URL}/api/cpd?scope=mine", headers=EMP, timeout=30).json()
        mine = next(lg for lg in g["logs"] if lg["log_id"] == log["log_id"])
        assert mine["hours"] == 2.75

    def test_patch_other_users_log_404(self, log):
        r = requests.patch(f"{BASE_URL}/api/cpd/{log['log_id']}", headers=ADMIN, json={
            "title": "x", "provider": "", "date": "2026-03-10", "hours": 1, "category": "", "notes": ""}, timeout=30)
        assert r.status_code == 404


# Drive spaces configured but empty
class TestDriveSpaces:
    @pytest.mark.parametrize("space", ["therapist", "participant"])
    def test_space_empty_not_409(self, space):
        r = requests.get(f"{BASE_URL}/api/drive/shared?space={space}&folder=&q=", headers=EMP, timeout=60)
        print(space, r.status_code, r.text[:200])
        assert r.status_code == 200
        assert r.json()["items"] == []
