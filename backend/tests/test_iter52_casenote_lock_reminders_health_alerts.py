# Iteration 52: one-case-note-at-a-time lock, pending release, health alert notifications, end-of-day reminders
import asyncio
import os
import sys
from datetime import datetime, timezone
import pytest
import requests
from dotenv import load_dotenv
from pymongo import MongoClient

load_dotenv("/app/frontend/.env")
load_dotenv("/app/backend/.env")
BASE_URL = (os.environ.get("EXPO_PUBLIC_BACKEND_URL") or os.environ.get("EXPO_BACKEND_URL")).rstrip("/")
API = f"{BASE_URL}/api"
ADMIN = {"Authorization": "Bearer test_session_admin"}
EMP = {"Authorization": "Bearer test_session_employee"}
EMP_ID = "user_testemp001"
mdb = MongoClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]
P1, P2, P3 = "TEST_Lock Person", "TEST_Other Person", "TEST_Nobody Person"
STATE: dict = {}


@pytest.fixture(scope="module", autouse=True)
def parts():
    t0 = datetime.now(timezone.utc).isoformat()
    made = {}
    for n in (P1, P2, P3):
        r = requests.post(f"{API}/participants", json={"name": n}, headers=ADMIN, timeout=30)
        assert r.status_code == 200, r.text
        made[n] = r.json()
    for n in (P1, P2):
        r = requests.put(f"{API}/participants/{made[n]['participant_id']}/assign", json={"user_ids": [EMP_ID]}, headers=ADMIN, timeout=30)
        assert r.status_code == 200
    STATE["parts"] = made
    yield made
    for p in made.values():
        requests.delete(f"{API}/participants/{p['participant_id']}", headers=ADMIN, timeout=30)
    mdb.case_note_starts.delete_many({"participant": {"$regex": "^test_"}})
    mdb.notifications.delete_many({"user_id": EMP_ID, "created_at": {"$gte": t0}})


def trackable_form():
    r = requests.get(f"{API}/caseload/forms", params={"participant": P1}, headers=EMP, timeout=90)
    assert r.status_code == 200, r.text
    forms = r.json()
    tf = [f for f in forms if f.get("form_id")]
    if not tf:
        pytest.skip("No trackable Day-to-Day form from Jotform")
    return tf[0], [f for f in forms if not f.get("form_id")]


# --- One case note at a time
class TestCaseNoteLock:
    def test_pending_null_initially(self):
        r = requests.get(f"{API}/caseload/pending", headers=EMP, timeout=60)
        assert r.status_code == 200 and r.json() == {"pending": None}, r.text
        r = requests.get(f"{API}/caseload/pending", headers=ADMIN, timeout=60)
        assert r.json() == {"pending": None}

    def test_admin_open_not_tracked(self):
        f, _ = trackable_form()
        r = requests.post(f"{API}/caseload/forms/open", json={"participant": P1, "form_id": f["form_id"], "url": "https://x.test/a"}, headers=ADMIN, timeout=60)
        assert r.status_code == 200 and r.json() == {"url": "https://x.test/a"}
        assert mdb.case_note_starts.count_documents({"user_id": "user_testadmin01"}) == 0

    def test_unassigned_403(self):
        f, _ = trackable_form()
        r = requests.post(f"{API}/caseload/forms/open", json={"participant": P3, "form_id": f["form_id"], "url": f["url"]}, headers=EMP, timeout=60)
        assert r.status_code == 403, r.text

    def test_untracked_form_doesnt_lock(self):
        _, untracked = trackable_form()
        if not untracked:
            pytest.skip("no untracked form")
        r = requests.post(f"{API}/caseload/forms/open", json={"participant": P1, "form_id": "", "url": untracked[0]["url"]}, headers=EMP, timeout=60)
        assert r.status_code == 200 and r.json()["url"] == untracked[0]["url"]
        assert mdb.case_note_starts.count_documents({"user_id": EMP_ID, "status": "pending"}) == 0

    def test_open_trackable_creates_pending(self):
        f, _ = trackable_form()
        STATE["form"] = f
        r = requests.post(f"{API}/caseload/forms/open", json={"participant": P1, "form_id": f["form_id"], "url": "ignored"}, headers=EMP, timeout=90)
        assert r.status_code == 200, r.text
        url = r.json()["url"]
        assert url.startswith(f["url"].split("?")[0]) and "?" in url, url
        doc = mdb.case_note_starts.find_one({"user_id": EMP_ID, "status": "pending"})
        assert doc and doc["participant"] == "test_lock person" and doc["participant_name"] == P1 and doc["form_id"] == f["form_id"]
        assert isinstance(doc["baseline"], list)
        STATE["start_id"] = doc["start_id"]

    def test_pending_returned(self):
        r = requests.get(f"{API}/caseload/pending", headers=EMP, timeout=90)
        p = r.json()["pending"]
        assert p and p["form_title"] == STATE["form"]["title"] and p["participant_name"] == P1 and p["url"]
        assert "baseline" not in p

    def test_second_open_409(self):
        f = STATE["form"]
        for body in ({"participant": P2, "form_id": f["form_id"], "url": f["url"]}, {"participant": P2, "form_id": "", "url": "https://x.test/b"},
                     {"participant": P1, "form_id": f["form_id"], "url": f["url"]}):
            r = requests.post(f"{API}/caseload/forms/open", json=body, headers=EMP, timeout=90)
            assert r.status_code == 409, r.text
            assert r.json()["detail"].startswith("Finish your ") and P1 in r.json()["detail"]
        assert mdb.case_note_starts.count_documents({"user_id": EMP_ID, "status": "pending"}) == 1

    def test_admin_caseload_shows_pending(self):
        r = requests.get(f"{API}/caseload", headers=ADMIN, timeout=120)
        assert r.status_code == 200
        ps = {p["name"]: p for p in r.json()["participants"]}
        pend = ps[P1]["pending"]
        assert len(pend) == 1 and pend[0]["start_id"] == STATE["start_id"] and pend[0]["name"] == "Emp Test"
        assert pend[0]["form"] == STATE["form"]["title"] and pend[0]["started_at"]
        assert ps[P2]["pending"] == [] and ps[P3]["pending"] == []
        # worker caseload doesn't expose pending
        w = requests.get(f"{API}/caseload", headers=EMP, timeout=120).json()
        assert all("pending" not in p for p in w["participants"])

    def test_reminders_job(self):
        sys.path.insert(0, "/app/backend")
        from routes.caseload import case_note_reminders
        t = datetime.now(timezone.utc).isoformat()
        asyncio.run(case_note_reminders())
        titles = [n["title"] for n in mdb.notifications.find({"user_id": EMP_ID, "type": "casenote", "created_at": {"$gte": t}})]
        assert f"No case note yet today: {P1}" in titles and f"No case note yet today: {P2}" in titles, titles
        assert f"No case note yet today: {P3}" not in titles
        assert titles.count(f"Finish your case note: {P1}") == 1, titles
        n = mdb.notifications.find_one({"user_id": EMP_ID, "title": f"No case note yet today: {P1}"})
        assert n["link"] == "/caseload"

    def test_release_worker_403_admin_200_then_404(self):
        sid = STATE["start_id"]
        assert requests.delete(f"{API}/caseload/pending/{sid}", headers=EMP, timeout=30).status_code == 403
        r = requests.delete(f"{API}/caseload/pending/{sid}", headers=ADMIN, timeout=30)
        assert r.status_code == 200 and r.json() == {"ok": True}
        assert mdb.case_note_starts.find_one({"start_id": sid})["status"] == "cleared"
        assert requests.delete(f"{API}/caseload/pending/{sid}", headers=ADMIN, timeout=30).status_code == 404
        assert requests.get(f"{API}/caseload/pending", headers=EMP, timeout=60).json()["pending"] is None

    def test_can_open_again_after_release(self):
        f = STATE["form"]
        r = requests.post(f"{API}/caseload/forms/open", json={"participant": P2, "form_id": f["form_id"], "url": f["url"]}, headers=EMP, timeout=90)
        assert r.status_code == 200, r.text
        assert mdb.case_note_starts.count_documents({"user_id": EMP_ID, "status": "pending", "participant": "test_other person"}) == 1


# --- Health alert change notifications
class TestHealthAlerts:
    def _save(self, pid, ha):
        return requests.put(f"{API}/participants/{pid}/profile", json={"about": "a", "health_alerts": ha, "contacts": []}, headers=ADMIN, timeout=30)

    def _count(self, pid):
        return mdb.notifications.count_documents({"user_id": EMP_ID, "type": "health", "link": f"/participant/{pid}"})

    def test_health_alert_notifies_once(self):
        pid = STATE["parts"][P1]["participant_id"]
        assert self._save(pid, "").status_code == 200
        assert self._count(pid) == 0
        assert self._save(pid, "Peanut allergy").status_code == 200
        assert self._count(pid) == 1
        n = mdb.notifications.find_one({"user_id": EMP_ID, "type": "health", "link": f"/participant/{pid}"})
        assert n["title"] == f"Health alerts updated: {P1}"
        assert self._save(pid, "  Peanut allergy ").status_code == 200  # same after strip
        assert self._count(pid) == 1
        assert self._save(pid, "Peanut allergy; epilepsy").status_code == 200
        assert self._count(pid) == 2

    def test_unassigned_participant_no_notification(self):
        pid = STATE["parts"][P3]["participant_id"]
        assert self._save(pid, "Asthma").status_code == 200
        assert mdb.notifications.count_documents({"type": "health", "link": f"/participant/{pid}"}) == 0

    def test_worker_cannot_save_profile(self):
        pid = STATE["parts"][P1]["participant_id"]
        r = requests.put(f"{API}/participants/{pid}/profile", json={"health_alerts": "x", "contacts": []}, headers=EMP, timeout=30)
        assert r.status_code == 403
