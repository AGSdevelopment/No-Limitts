# Iteration 14: multi-assignee tasks with collaborators + certificate CPD hours counting to year total
import os
import datetime
import requests
import pytest


def _base():
    url = os.environ.get("EXPO_PUBLIC_BACKEND_URL") or os.environ.get("EXPO_BACKEND_URL")
    if not url:
        for line in open("/app/frontend/.env"):
            if line.startswith("EXPO_PUBLIC_BACKEND_URL="):
                url = line.split("=", 1)[1].strip().strip('"')
    return url.rstrip("/") + "/api"


API = _base()
ADMIN = {"Authorization": "Bearer test_session_admin"}
EMP = {"Authorization": "Bearer test_session_employee"}


# Tasks: multi-assignee with collaborators
class TestCollabTasks:
    def test_admin_multi_assignee_collaborators(self):
        r = requests.post(f"{API}/tasks", headers=ADMIN, json={"title": "TEST collab api", "assignee_ids": ["user_testemp001", "user_testadmin01"]})
        assert r.status_code in (200, 201), r.text
        mine = requests.get(f"{API}/tasks", headers=EMP).json()
        t = [x for x in mine if x["title"] == "TEST collab api"]
        assert len(t) == 1
        assert [c["user_id"] for c in t[0]["collaborators"]] == ["user_testadmin01"]
        adm = [x for x in requests.get(f"{API}/tasks", headers=ADMIN).json() if x["title"] == "TEST collab api"]
        assert any(c["user_id"] == "user_testemp001" for x in adm for c in x.get("collaborators", []))
        # notification body mentions collaborator
        notes = requests.get(f"{API}/notifications", headers=EMP).json()
        notes = notes if isinstance(notes, list) else notes.get("items", notes.get("notifications", []))
        n = [x for x in notes if "TEST collab api" in (x.get("body", "") + x.get("title", ""))]
        assert n and " · with " in n[0].get("body", ""), n
        # cleanup
        for x in adm + t:
            requests.delete(f"{API}/tasks/{x['task_id']}", headers=ADMIN)

    def test_employee_assignee_ids_forbidden(self):
        r = requests.post(f"{API}/tasks", headers=EMP, json={"title": "TEST emp collab", "assignee_ids": ["user_testadmin01"]})
        assert r.status_code == 403


# Certificates: cpd_hours with an old issue date counts this year
class TestCertCpd:
    def test_old_cert_counts_this_year(self):
        before = requests.get(f"{API}/cpd", headers=EMP).json()
        y0 = before.get("year_hours", 0)
        files = {"file": ("TEST_cert_api.png", open("/tmp/cpd.png", "rb"), "image/png")}
        r = requests.post(f"{API}/certificates", headers=EMP, files=files,
                          data={"title": "TEST_cert_api", "issue_date": "2024-01-10", "expiry_date": "2027-01-10", "cpd_hours": "2"})
        assert r.status_code in (200, 201), r.text
        cert = r.json()
        after = requests.get(f"{API}/cpd", headers=EMP).json()
        assert round(after["year_hours"] - y0, 2) == 2
        # cleanup
        cid = cert.get("cert_id") or cert.get("certificate_id")
        requests.delete(f"{API}/certificates/{cid}", headers=EMP)
        for lg in after.get("logs", after.get("items", [])):
            if "TEST_cert_api" in lg.get("title", ""):
                requests.delete(f"{API}/cpd/{lg['log_id']}", headers=EMP)
