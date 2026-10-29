# Iteration 49: in-app participants, Support Worker assignment, caseload scoping, plan-review email share links, forms categories
import os
import pytest
import requests
from pymongo import MongoClient
from dotenv import load_dotenv

load_dotenv("/app/frontend/.env")
load_dotenv("/app/backend/.env")
BASE_URL = (os.environ.get("EXPO_BACKEND_URL") or os.environ.get("EXPO_PUBLIC_BACKEND_URL")).rstrip("/")
ADMIN = {"Authorization": "Bearer test_session_admin"}
WORKER = {"Authorization": "Bearer test_session_employee"}
NAME = "Test Zed Participant"
T = 90

mdb = MongoClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]
state = {}


@pytest.fixture(scope="module", autouse=True)
def cleanup():
    mdb.participants.delete_many({"name": NAME})
    mdb.caseload_summaries.delete_many({"participant": NAME.casefold()})
    mdb.caseload_shares.delete_many({"participant": NAME.casefold()})
    yield
    mdb.participants.delete_many({"name": NAME})
    mdb.caseload_summaries.delete_many({"participant": NAME.casefold()})
    mdb.caseload_shares.delete_many({"participant": NAME.casefold()})


# Participants CRUD + permissions
class TestParticipants:
    def test_worker_cannot_add(self):
        r = requests.post(f"{BASE_URL}/api/participants", json={"name": NAME}, headers=WORKER, timeout=T)
        assert r.status_code == 403

    def test_short_name_400(self):
        r = requests.post(f"{BASE_URL}/api/participants", json={"name": " a "}, headers=ADMIN, timeout=T)
        assert r.status_code == 400

    def test_admin_add(self):
        r = requests.post(f"{BASE_URL}/api/participants", json={"name": "  test zed participant "}, headers=ADMIN, timeout=T)
        assert r.status_code == 200, r.text
        d = r.json()
        assert d["name"] == NAME and d["participant_id"].startswith("par_") and d["assigned_ids"] == []
        assert "_id" not in d
        state["pid"] = d["participant_id"]

    def test_duplicate_400(self):
        r = requests.post(f"{BASE_URL}/api/participants", json={"name": NAME.upper()}, headers=ADMIN, timeout=T)
        assert r.status_code == 400
        assert "already" in r.json()["detail"]

    def test_worker_forms_403_unassigned(self):
        r = requests.get(f"{BASE_URL}/api/caseload/forms", params={"participant": NAME}, headers=WORKER, timeout=T)
        assert r.status_code == 403

    def test_worker_cannot_assign(self):
        r = requests.put(f"{BASE_URL}/api/participants/{state['pid']}/assign", json={"user_ids": ["user_testemp001"]}, headers=WORKER, timeout=T)
        assert r.status_code == 403

    def test_assign_keeps_only_support_workers(self):
        r = requests.put(f"{BASE_URL}/api/participants/{state['pid']}/assign",
                         json={"user_ids": ["user_testemp001", "user_testadmin01", "user_bogus", "user_testemp001"]}, headers=ADMIN, timeout=T)
        assert r.status_code == 200, r.text
        assert r.json()["assigned_ids"] == ["user_testemp001"]
        assert mdb.participants.find_one({"participant_id": state["pid"]})["assigned_ids"] == ["user_testemp001"]

    def test_assign_404(self):
        r = requests.put(f"{BASE_URL}/api/participants/par_nope/assign", json={"user_ids": []}, headers=ADMIN, timeout=T)
        assert r.status_code == 404


# Caseload scoping
class TestCaseload:
    def test_admin_caseload(self):
        r = requests.get(f"{BASE_URL}/api/caseload", headers=ADMIN, timeout=T)
        assert r.status_code == 200, r.text
        d = r.json()
        assert d["can_manage"] is True and d["worker"] is False
        p = next((x for x in d["participants"] if x["name"] == NAME), None)
        assert p is not None
        assert p["participant_id"] == state["pid"]
        assert p["assigned"] == [{"user_id": "user_testemp001", "name": "Emp Test"}]

    def test_worker_caseload(self):
        r = requests.get(f"{BASE_URL}/api/caseload", headers=WORKER, timeout=T)
        assert r.status_code == 200, r.text
        d = r.json()
        assert d["worker"] is True and d["can_manage"] is False
        assigned = {p["name"] for p in mdb.participants.find({"assigned_ids": "user_testemp001"})}
        assert {p["name"] for p in d["participants"]} == assigned
        assert NAME in assigned
        for p in d["participants"]:
            assert all(n["kind"] == "day" for n in p["notes"])
            assert p["assigned"] == []

    def test_worker_forms_day_only_prefilled(self):
        r = requests.get(f"{BASE_URL}/api/caseload/forms", params={"participant": NAME.lower()}, headers=WORKER, timeout=T)
        assert r.status_code == 200, r.text
        forms = r.json()
        print("worker forms:", [(f["title"], f["url"]) for f in forms])
        assert len(forms) > 0
        assert all(f["kind"] == "day" for f in forms)
        # iter50: non-prefillable Day-to-Day forms are now listed too (prefilled=False)
        assert all("Zed" in f["url"] for f in forms if f["prefilled"]), "participant not prefilled"

    def test_admin_forms_include_coordinator(self):
        r = requests.get(f"{BASE_URL}/api/caseload/forms", params={"participant": NAME}, headers=ADMIN, timeout=T)
        assert r.status_code == 200, r.text
        forms = r.json()
        titles = [f["title"] for f in forms]
        print("admin forms:", titles)
        assert "Coordinator Case Note" in titles
        assert any(f["kind"] == "day" for f in forms)


# Summary / PDF / email share links
class TestSummaryEmail:
    def test_worker_blocked(self):
        h = WORKER
        assert requests.post(f"{BASE_URL}/api/caseload/summary", json={"name": NAME}, headers=h, timeout=T).status_code == 403
        assert requests.get(f"{BASE_URL}/api/caseload/summary/pdf", params={"name": NAME}, headers=h, timeout=T).status_code == 403
        assert requests.post(f"{BASE_URL}/api/caseload/summary/email", json={"name": NAME, "user_ids": ["user_testadmin01"]}, headers=h, timeout=T).status_code == 403

    def test_email_empty_ids_400(self):
        r = requests.post(f"{BASE_URL}/api/caseload/summary/email", json={"name": NAME, "user_ids": []}, headers=ADMIN, timeout=T)
        assert r.status_code == 400

    def test_email_no_summary_404(self):
        r = requests.post(f"{BASE_URL}/api/caseload/summary/email", json={"name": NAME, "user_ids": ["user_testadmin01"]}, headers=ADMIN, timeout=T)
        assert r.status_code == 404

    def test_email_send_and_shared_pdf(self):
        mdb.caseload_summaries.insert_one({"participant": NAME.casefold(), "display": NAME, "summary": "Overview: Test summary.\nFollow-ups: None noted",
                                           "note_count": 1, "by": "X"})
        r = requests.post(f"{BASE_URL}/api/caseload/summary/email", json={"name": NAME, "user_ids": ["user_testadmin01"]}, headers=ADMIN, timeout=T)
        assert r.status_code == 200, r.text
        assert r.json()["sent"] == ["Alex Admin"]
        share = mdb.caseload_shares.find_one({"participant": NAME.casefold(), "recipient_id": "user_testadmin01"})
        assert share and share["expires_at"]
        p = requests.get(f"{BASE_URL}/api/caseload/shared/{share['token']}", timeout=T)
        assert p.status_code == 200
        assert p.headers["content-type"].startswith("application/pdf")
        assert p.content[:4] == b"%PDF"

    def test_admin_pdf(self):
        r = requests.get(f"{BASE_URL}/api/caseload/summary/pdf", params={"name": NAME}, headers=ADMIN, timeout=T)
        assert r.status_code == 200 and r.content[:4] == b"%PDF"

    def test_bad_token_404(self):
        assert requests.get(f"{BASE_URL}/api/caseload/shared/badtoken123", timeout=T).status_code == 404


# Forms categories
class TestForms:
    def test_forms_list_and_therapy_triage_invalid(self):
        r = requests.get(f"{BASE_URL}/api/forms", headers=ADMIN, timeout=T)
        assert r.status_code == 200
        forms = r.json()
        assert all(f.get("category") != "Therapy Triage" for f in forms)
        bad = requests.post(f"{BASE_URL}/api/forms", json={"title": "TEST_tt", "url": "https://form.jotform.com/1", "category": "Therapy Triage"}, headers=ADMIN, timeout=T)
        assert bad.status_code == 400


# Delete participant -> worker loses access
class TestRemove:
    def test_delete_and_access_revoked(self):
        r = requests.delete(f"{BASE_URL}/api/participants/{state['pid']}", headers=WORKER, timeout=T)
        assert r.status_code == 403
        r = requests.delete(f"{BASE_URL}/api/participants/{state['pid']}", headers=ADMIN, timeout=T)
        assert r.status_code == 200 and r.json() == {"ok": True}
        assert requests.delete(f"{BASE_URL}/api/participants/{state['pid']}", headers=ADMIN, timeout=T).status_code == 404
        r = requests.get(f"{BASE_URL}/api/caseload/forms", params={"participant": NAME}, headers=WORKER, timeout=T)
        assert r.status_code == 403
