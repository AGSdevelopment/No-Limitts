"""StaffHub iteration_10: hidden test users, private tasks, CPD logs/resources, Socials, Drive shared-folder cleanup."""
import os
import time
import json

import pytest
import requests
from pymongo import MongoClient
from dotenv import load_dotenv

load_dotenv("/app/frontend/.env")
load_dotenv("/app/backend/.env")
BASE_URL = (os.environ.get("EXPO_PUBLIC_BACKEND_URL") or os.environ.get("EXPO_BACKEND_URL")).rstrip("/")
API = f"{BASE_URL}/api"
ADMIN = "test_session_admin"
EMP = "test_session_employee"
FOLDER = "https://drive.google.com/drive/folders/1d8-5EPvhUq943PVfHj5PR5VEYZfL0SNM"


def h(tok):
    return {"Authorization": f"Bearer {tok}"}


@pytest.fixture(scope="module")
def db():
    d = MongoClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]
    yield d
    d.tasks.delete_many({"title": {"$regex": "^TEST_"}})
    d.cpd_logs.delete_many({"title": {"$regex": "^TEST_"}})
    d.cpd_resources.delete_many({"title": {"$regex": "^TEST_"}})
    d.notifications.delete_many({"body": {"$regex": "^TEST"}})


# ---- Users (hidden test accounts)
class TestUsers:
    def test_users_hidden(self):
        r = requests.get(f"{API}/users", headers=h(EMP))
        assert r.status_code == 200
        names = [u["name"] for u in r.json()]
        assert "Alex Admin" not in names and "Erin Employee" not in names
        assert any("Ailis" in n for n in names) and any("Clair Vann" in n for n in names)
        assert all("_id" not in u for u in r.json())
        print("visible users:", len(names))

    def test_hidden_users_still_login(self):
        assert requests.get(f"{API}/auth/me", headers=h(ADMIN)).json()["role"] == "admin"
        assert requests.get(f"{API}/auth/me", headers=h(EMP)).status_code == 200


# ---- Tasks (private / assigned)
class TestTasks:
    def test_employee_private_task_flow(self, db):
        r = requests.post(f"{API}/tasks", headers=h(EMP), json={"title": "TEST_private emp"})
        assert r.status_code == 200, r.text
        t = r.json()
        assert t["private"] is True and t["assignee_id"] == "user_testemp001"
        mine = requests.get(f"{API}/tasks", headers=h(EMP)).json()
        assert any(x["task_id"] == t["task_id"] for x in mine)
        # admin scope=all must not see it
        alls = requests.get(f"{API}/tasks?scope=all", headers=h(ADMIN)).json()
        assert not any(x["task_id"] == t["task_id"] for x in alls)
        assert not any(x.get("private") and x["assignee_id"] != "user_testadmin01" for x in alls)
        # admin cannot delete it
        assert requests.delete(f"{API}/tasks/{t['task_id']}", headers=h(ADMIN)).status_code == 404
        # creator can delete
        assert requests.delete(f"{API}/tasks/{t['task_id']}", headers=h(EMP)).status_code == 200
        assert db.tasks.find_one({"task_id": t["task_id"]}) is None

    def test_employee_cannot_assign_all_or_others(self):
        assert requests.post(f"{API}/tasks", headers=h(EMP), json={"title": "TEST_x", "assignee_id": "all"}).status_code == 403
        assert requests.post(f"{API}/tasks", headers=h(EMP),
                             json={"title": "TEST_x", "assignee_id": "user_testadmin01"}).status_code == 403

    def test_admin_assigned_task_employee_cannot_delete(self, db):
        r = requests.post(f"{API}/tasks", headers=h(ADMIN),
                          json={"title": "TEST_assigned", "assignee_id": "user_testemp001", "due_date": "2026-03-01"})
        assert r.status_code == 200, r.text
        t = r.json()
        assert t["private"] is False and t["assignee_name"]
        assert requests.delete(f"{API}/tasks/{t['task_id']}", headers=h(EMP)).status_code == 404
        # employee can mark done
        p = requests.patch(f"{API}/tasks/{t['task_id']}", headers=h(EMP), json={"status": "done"})
        assert p.status_code == 200 and p.json()["status"] == "done"
        alls = requests.get(f"{API}/tasks?scope=all", headers=h(ADMIN)).json()
        assert any(x["task_id"] == t["task_id"] for x in alls)
        assert requests.delete(f"{API}/tasks/{t['task_id']}", headers=h(ADMIN)).status_code == 200

    def test_admin_private_task(self):
        r = requests.post(f"{API}/tasks", headers=h(ADMIN), json={"title": "TEST_admin me"})
        assert r.status_code == 200 and r.json()["private"] is True
        assert requests.delete(f"{API}/tasks/{r.json()['task_id']}", headers=h(ADMIN)).status_code == 200

    def test_task_validation(self):
        assert requests.post(f"{API}/tasks", headers=h(EMP), json={"title": "  "}).status_code == 400
        assert requests.post(f"{API}/tasks", headers=h(EMP), json={"title": "TEST_d", "due_date": "bad"}).status_code == 400


# ---- CPD logs + resources
class TestCpd:
    def test_cpd_log_crud(self, db):
        before = requests.get(f"{API}/cpd", headers=h(EMP)).json()["year_hours"]
        r = requests.post(f"{API}/cpd", headers=h(EMP), json={"title": "TEST_webinar", "date": "2026-01-10",
                                                               "hours": 1.5, "category": "Webinar"})
        assert r.status_code == 200, r.text
        log = r.json()
        g = requests.get(f"{API}/cpd", headers=h(EMP)).json()
        assert g["year_hours"] == round(before + 1.5, 2)
        assert any(x["log_id"] == log["log_id"] for x in g["logs"])
        a = requests.get(f"{API}/cpd?scope=all", headers=h(ADMIN)).json()
        tt = [t for t in a["team_totals"] if t["user_id"] == "user_testemp001"]
        assert tt and tt[0]["hours"] >= 1.5
        # employee scope=all falls back to own
        e = requests.get(f"{API}/cpd?scope=all", headers=h(EMP)).json()
        assert e["team_totals"] == [] and all(x["user_id"] == "user_testemp001" for x in e["logs"])
        assert requests.delete(f"{API}/cpd/{log['log_id']}", headers=h(EMP)).status_code == 200
        assert requests.delete(f"{API}/cpd/{log['log_id']}", headers=h(EMP)).status_code == 404

    def test_cpd_validation(self):
        assert requests.post(f"{API}/cpd", headers=h(EMP), json={"title": "TEST_v", "date": "x", "hours": 1}).status_code == 400
        assert requests.post(f"{API}/cpd", headers=h(EMP), json={"title": "TEST_v", "date": "2026-01-01", "hours": 0}).status_code == 400
        assert requests.post(f"{API}/cpd", headers=h(EMP), json={"title": "", "date": "2026-01-01", "hours": 1}).status_code == 400

    def test_cpd_resources(self, db):
        assert requests.post(f"{API}/cpd/resources", headers=h(EMP), json={"title": "TEST_r"}).status_code == 403
        r = requests.post(f"{API}/cpd/resources", headers=h(ADMIN), json={"title": "TEST_res", "url": "example.com/x"})
        assert r.status_code == 200, r.text
        res = r.json()
        assert res["url"] == "https://example.com/x"
        lst = requests.get(f"{API}/cpd/resources", headers=h(EMP)).json()
        assert any(x["resource_id"] == res["resource_id"] for x in lst)
        assert requests.delete(f"{API}/cpd/resources/{res['resource_id']}", headers=h(EMP)).status_code == 403
        assert requests.delete(f"{API}/cpd/resources/{res['resource_id']}", headers=h(ADMIN)).status_code == 200
        assert db.cpd_resources.find_one({"resource_id": res["resource_id"]}) is None
        db.notifications.delete_many({"body": "TEST_res"})


# ---- Socials
class TestSocials:
    def test_socials_get(self):
        r = requests.get(f"{API}/socials", headers=h(EMP))
        assert r.status_code == 200
        d = r.json()
        assert set(d["links"]) == {"instagram", "facebook", "linkedin"}
        assert d["links"]["instagram"]["url"] == "https://www.instagram.com/aspiregrowtherapy/"
        assert d["status"]["meta"]["configured"] is False and d["status"]["linkedin"]["configured"] is False
        assert d["posts"] == []
        assert "redirect_uris" not in d["status"]
        assert "redirect_uris" in requests.get(f"{API}/socials", headers=h(ADMIN)).json()["status"]

    @pytest.mark.parametrize("kind", ["meta", "linkedin"])
    def test_social_start(self, kind):
        assert requests.post(f"{API}/integrations/{kind}/start", headers=h(ADMIN)).status_code == 409
        assert requests.post(f"{API}/integrations/{kind}/start", headers=h(EMP)).status_code == 403


# ---- Drive shared folder cleanup (iteration_9 regression)
class TestDriveCleanup:
    def test_set_index_clear(self, db):
        st = requests.get(f"{API}/integrations/google-drive/status", headers=h(ADMIN)).json()
        if not st.get("connected"):
            pytest.skip("Drive not connected")
        r = requests.put(f"{API}/integrations/google-drive/shared-folder", headers=h(ADMIN), json={"link": FOLDER})
        assert r.status_code == 200, r.text
        count = 0
        for _ in range(12):
            time.sleep(5)
            count = db.drive_docs.count_documents({})
            s = requests.get(f"{API}/drive/index-status", headers=h(ADMIN)).json()
            if count and not s["running"]:
                break
        print("indexed docs:", count)
        assert count > 0
        files = requests.get(f"{API}/drive/shared", headers=h(ADMIN)).json()
        fid = next((f["id"] for f in files.get("files", []) if not f["is_folder"]), None)
        if fid:
            requests.post(f"{API}/drive/pins", headers=h(ADMIN), json={"file_id": fid})
        assert requests.delete(f"{API}/integrations/google-drive/shared-folder", headers=h(ADMIN)).status_code == 200
        assert db.drive_docs.count_documents({}) == 0
        assert db.drive_pins.count_documents({}) == 0
        assert requests.get(f"{API}/drive/shared", headers=h(ADMIN)).status_code == 409
        # Ask AI should not reference timesheets
        a = requests.post(f"{API}/ai/ask", headers=h(ADMIN), json={"question": "TEST What timesheets are in the Drive?"},
                          stream=True, timeout=90)
        text = ""
        for line in a.iter_lines(decode_unicode=True):
            if line and line.startswith("data:"):
                try:
                    text += json.loads(line[5:].strip()).get("delta", "") or ""
                except Exception:
                    text += line[5:]
        print("AI answer:", text[:400])
        assert "Armi" not in text and "Myers" not in text
