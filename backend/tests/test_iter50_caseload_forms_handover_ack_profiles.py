# Iteration 50: caseload forms picker, handover acknowledgement, participant profiles, route order
import os
import time
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
SUB_ID = "TEST_sub_iter50"


@pytest.fixture(scope="module")
def parts():
    made = {}
    for n in ("TEST_Profile Person", "TEST_Unassigned Person"):
        r = requests.post(f"{API}/participants", json={"name": n}, headers=ADMIN, timeout=30)
        assert r.status_code == 200, r.text
        made[n] = r.json()
    pid = made["TEST_Profile Person"]["participant_id"]
    r = requests.put(f"{API}/participants/{pid}/assign", json={"user_ids": [EMP_ID]}, headers=ADMIN, timeout=30)
    assert r.status_code == 200 and r.json()["assigned_ids"] == [EMP_ID]
    yield made
    for p in made.values():
        requests.delete(f"{API}/participants/{p['participant_id']}", headers=ADMIN, timeout=30)
    mdb.handover_acks.delete_many({"submission_id": {"$regex": "^TEST_"}})


# --- Caseload forms picker
class TestCaseloadForms:
    def test_admin_forms_sorted_with_prefilled_flag(self, parts):
        r = requests.get(f"{API}/caseload/forms", params={"participant": "TEST_Profile Person"}, headers=ADMIN, timeout=90)
        assert r.status_code == 200, r.text
        forms = r.json()
        assert isinstance(forms, list) and len(forms) > 0
        for f in forms:
            assert isinstance(f["prefilled"], bool) and f["url"] and f["title"]
        kinds = [f["kind"] for f in forms]
        if "coordinator" in kinds:
            assert kinds[0] == "coordinator"
        day = [f["title"].lower() for f in forms if f["kind"] == "day"]
        assert day == sorted(day)
        # every Day-to-Day form in db is listed (by title)
        db_titles = {f["title"] for f in mdb.forms.find({"category": "Day-to-Day"}, {"title": 1})}
        assert db_titles <= {f["title"] for f in forms}, db_titles - {f["title"] for f in forms}
        print("ADMIN FORMS:", [(f["title"], f["kind"], f["prefilled"]) for f in forms])

    def test_worker_assigned_gets_day_only(self, parts):
        r = requests.get(f"{API}/caseload/forms", params={"participant": "test_profile  person"}, headers=EMP, timeout=90)
        assert r.status_code == 200, r.text
        forms = r.json()
        assert forms and all(f["kind"] == "day" for f in forms)
        print("WORKER FORMS:", [(f["title"], f["prefilled"]) for f in forms])

    def test_worker_unassigned_403(self, parts):
        r = requests.get(f"{API}/caseload/forms", params={"participant": "TEST_Unassigned Person"}, headers=EMP, timeout=30)
        assert r.status_code == 403


# --- Handover acknowledgement
class TestHandoverAck:
    def test_worker_ack_idempotent(self, parts):
        for _ in range(2):
            r = requests.post(f"{API}/caseload/handover/ack", json={"submission_id": SUB_ID, "participant": "TEST_Profile Person"}, headers=EMP, timeout=30)
            assert r.status_code == 200 and r.json() == {"ok": True}
        recs = list(mdb.handover_acks.find({"submission_id": SUB_ID, "user_id": EMP_ID}, {"_id": 0}))
        assert len(recs) == 1
        assert recs[0]["participant"] == "test_profile person" and recs[0]["name"] and recs[0]["at"]

    def test_worker_ack_unassigned_403(self, parts):
        r = requests.post(f"{API}/caseload/handover/ack", json={"submission_id": "TEST_sub_x", "participant": "TEST_Unassigned Person"}, headers=EMP, timeout=30)
        assert r.status_code == 403
        assert mdb.handover_acks.count_documents({"submission_id": "TEST_sub_x"}) == 0

    def test_admin_ack(self, parts):
        r = requests.post(f"{API}/caseload/handover/ack", json={"submission_id": SUB_ID, "participant": "TEST_Profile Person"}, headers=ADMIN, timeout=30)
        assert r.status_code == 200
        assert mdb.handover_acks.count_documents({"submission_id": SUB_ID}) == 2

    def test_ack_validation_422(self, parts):
        r = requests.post(f"{API}/caseload/handover/ack", json={"participant": "x"}, headers=ADMIN, timeout=30)
        assert r.status_code == 422


# --- Participant profiles
class TestParticipantProfile:
    def test_get_admin_can_edit(self, parts):
        pid = parts["TEST_Profile Person"]["participant_id"]
        r = requests.get(f"{API}/participants/{pid}", headers=ADMIN, timeout=30)
        assert r.status_code == 200
        d = r.json()
        assert d["can_edit"] is True and d["name"] == "TEST_Profile Person" and d["assigned"] == ["Emp Test"]
        assert d["profile"]["contacts"] == [] and d["profile"]["goals"] == ""

    def test_get_assigned_worker_read_only(self, parts):
        pid = parts["TEST_Profile Person"]["participant_id"]
        r = requests.get(f"{API}/participants/{pid}", headers=EMP, timeout=30)
        assert r.status_code == 200 and r.json()["can_edit"] is False

    def test_get_unassigned_worker_403(self, parts):
        pid = parts["TEST_Unassigned Person"]["participant_id"]
        assert requests.get(f"{API}/participants/{pid}", headers=EMP, timeout=30).status_code == 403

    def test_get_unknown_404(self):
        assert requests.get(f"{API}/participants/par_doesnotexist", headers=ADMIN, timeout=30).status_code == 404

    def test_put_worker_403(self, parts):
        pid = parts["TEST_Profile Person"]["participant_id"]
        r = requests.put(f"{API}/participants/{pid}/profile", json={"goals": "x"}, headers=EMP, timeout=30)
        assert r.status_code == 403

    def test_put_admin_saves_and_drops_blank_contacts(self, parts):
        pid = parts["TEST_Profile Person"]["participant_id"]
        body = {"about": " Likes music ", "goals": "Catch the bus alone", "support_needs": "Morning routine",
                "communication": "Short sentences", "health_alerts": "Peanut allergy",
                "contacts": [{"name": "Mum Smith", "relationship": "Mum", "phone": "0400 000 000", "email": "mum@example.com"},
                             {"name": "   ", "relationship": "blank"}]}
        r = requests.put(f"{API}/participants/{pid}/profile", json=body, headers=ADMIN, timeout=30)
        assert r.status_code == 200, r.text
        g = requests.get(f"{API}/participants/{pid}", headers=EMP, timeout=30).json()["profile"]
        assert g["about"] == "Likes music" and g["goals"] == "Catch the bus alone" and g["health_alerts"] == "Peanut allergy"
        assert g["support_needs"] == "Morning routine" and g["communication"] == "Short sentences"
        assert len(g["contacts"]) == 1 and g["contacts"][0]["name"] == "Mum Smith" and g["contacts"][0]["phone"] == "0400 000 000"
        assert g["updated_by"] == "Alex Admin" and g["updated_at"]

    def test_put_unknown_404(self):
        r = requests.put(f"{API}/participants/par_doesnotexist/profile", json={"goals": "x"}, headers=ADMIN, timeout=30)
        assert r.status_code == 404


# --- Route order: export/template not captured by /participants/{id}
class TestRouteOrder:
    @pytest.mark.parametrize("path", ["export", "import-template"])
    def test_xlsx_routes(self, path):
        r = requests.get(f"{API}/participants/{path}", headers=ADMIN, timeout=30)
        assert r.status_code == 200, r.text[:200]
        assert "spreadsheetml" in r.headers["content-type"] and r.content[:2] == b"PK"

    def test_export_worker_403(self):
        assert requests.get(f"{API}/participants/export", headers=EMP, timeout=30).status_code == 403


# --- In-process: handover appears in GET /api/caseload with read_by_me / acks / waiting
def test_caseload_handover_in_process(parts):
    import sys
    import asyncio
    import httpx
    sys.path.insert(0, "/app/backend")
    os.chdir("/app/backend")
    import server  # noqa
    from routes import caseload as cl

    row = {"id": SUB_ID, "created_at": "2099-01-01 08:00:00", "kind": "day", "source": "No Limitts Shift Handover",
           "participant": "TEST_Profile Person", "coordinator": "Someone", "email": "", "date": "2099-01-01",
           "fields": [{"label": "Notes", "value": "All good"}]}

    async def run():
        cl._cache.update(rows=[row], at=time.time() + 10_000)
        tr = httpx.ASGITransport(app=server.app)
        async with httpx.AsyncClient(transport=tr, base_url="http://t") as c:
            # remove admin ack so worker is the only reader, then check coordinator view
            await cl.db.handover_acks.delete_many({"submission_id": SUB_ID, "user_id": "user_testadmin01"})
            a = (await c.get("/api/caseload", headers=ADMIN)).json()
            w = (await c.get("/api/caseload", headers=EMP)).json()
        return a, w

    a, w = asyncio.new_event_loop().run_until_complete(run())
    pa = next(p for p in a["participants"] if p["name"] == "TEST_Profile Person")
    pw = next(p for p in w["participants"] if p["name"] == "TEST_Profile Person")
    assert pa["handover"]["id"] == SUB_ID
    assert pa["handover"]["read_by_me"] is False
    assert [x["name"] for x in pa["handover"]["acks"]] == ["Emp Test"] and pa["handover"]["waiting"] == []
    assert pw["handover"]["read_by_me"] is True
    assert "acks" not in pw["handover"] and "waiting" not in pw["handover"]
