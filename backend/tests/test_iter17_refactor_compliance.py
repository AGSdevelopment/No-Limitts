# Iteration 17: regression smoke tests after server.py -> core.py + routes/* split,
# plus compliance dashboard/export and New Starter checklist.
import io
import os
import pytest
import requests
from pathlib import Path


def _base():
    url = os.environ.get("EXPO_PUBLIC_BACKEND_URL") or os.environ.get("EXPO_BACKEND_URL")
    if not url:
        for line in Path("/app/frontend/.env").read_text().splitlines():
            if line.startswith("EXPO_PUBLIC_BACKEND_URL=") or line.startswith("EXPO_BACKEND_URL="):
                url = line.split("=", 1)[1].strip().strip('"')
                break
    return url.rstrip("/")


BASE_URL = _base()
ADMIN = {"Authorization": "Bearer test_session_admin"}
EMP = {"Authorization": "Bearer test_session_employee"}
EMP_ID = "user_testemp001"
ADMIN_ID = "user_testadmin01"


def g(path, h=ADMIN, **kw):
    return requests.get(f"{BASE_URL}{path}", headers=h, timeout=60, **kw)


# ---------- Smoke: every module ----------
class TestSmoke:
    def test_auth_me(self):
        r = g("/api/auth/me")
        assert r.status_code == 200 and r.json()["user_id"] == ADMIN_ID and r.json()["role"] == "admin"
        assert "_id" not in r.json()

    def test_auth_me_unauth(self):
        assert requests.get(f"{BASE_URL}/api/auth/me", timeout=30).status_code == 401

    @pytest.mark.parametrize("path", ["/api/users", "/api/notifications", "/api/certificates", "/api/conversations",
                                      "/api/updates", "/api/policies", "/api/events", "/api/tasks",
                                      "/api/forms", "/api/cpd", "/api/cpd/resources", "/api/ai/history",
                                      "/api/socials", "/api/dashboard", "/api/drive/shared",
                                      "/api/integrations/google-drive/status"])
    def test_get_ok(self, path):
        r = g(path)
        # /api/drive/shared returns 409 while the Therapist Resources folder is not configured (expected)
        ok = r.status_code == 200 or (path == "/api/drive/shared" and r.status_code == 409)
        assert ok, f"{path}: {r.status_code} {r.text[:200]}"
        assert '"_id"' not in r.text

    def test_dashboard_shape(self):
        d = g("/api/dashboard").json()
        assert isinstance(d, dict) and len(d) > 0

    def test_cpd_report_pdf(self):
        r = requests.get(f"{BASE_URL}/api/cpd/report?token=test_session_employee", timeout=60)
        assert r.status_code == 200 and r.content[:4] == b"%PDF"

    def test_policy_acknowledge(self):
        pols = g("/api/policies", EMP).json()
        assert pols
        pid = next((p["policy_id"] for p in pols if p["policy_id"] == "pol_TESTVER"), pols[0]["policy_id"])
        r = requests.post(f"{BASE_URL}/api/policies/{pid}/acknowledge", headers=EMP, timeout=30)
        assert r.status_code == 200 and r.json()["ok"] is True
        assert requests.post(f"{BASE_URL}/api/policies/nope/acknowledge", headers=EMP,
                             timeout=30).status_code == 404


# ---------- Chat: DM send message ----------
class TestChat:
    def test_dm_send_and_list(self):
        conv = requests.post(f"{BASE_URL}/api/dms", headers=ADMIN, json={"user_id": EMP_ID}, timeout=30)
        assert conv.status_code == 200
        cid = conv.json()["conversation_id"]
        m = requests.post(f"{BASE_URL}/api/conversations/{cid}/messages", headers=ADMIN,
                          json={"text": "TEST_refactor msg"}, timeout=30)
        assert m.status_code == 200 and m.json()["text"] == "TEST_refactor msg"
        msgs = g(f"/api/conversations/{cid}/messages", EMP).json()
        items = msgs if isinstance(msgs, list) else msgs.get("messages", [])
        assert any(x["message_id"] == m.json()["message_id"] for x in items)
        assert requests.post(f"{BASE_URL}/api/conversations/{cid}/messages", headers=ADMIN, json={"text": "  "},
                             timeout=30).status_code == 400


# ---------- Tasks CRUD ----------
class TestTasks:
    def test_task_create_patch_delete(self):
        r = requests.post(f"{BASE_URL}/api/tasks", headers=EMP,
                          json={"title": "TEST_refactor task", "due_date": "2026-02-01"}, timeout=30)
        assert r.status_code == 200, r.text
        t = r.json()
        assert t["assignee_id"] == EMP_ID and t["private"] is True and t["status"] == "open"
        p = requests.patch(f"{BASE_URL}/api/tasks/{t['task_id']}", headers=EMP, json={"status": "done"}, timeout=30)
        assert p.status_code == 200 and p.json()["status"] == "done"
        mine = g("/api/tasks", EMP).json()
        assert any(x["task_id"] == t["task_id"] and x["status"] == "done" for x in mine)
        # admin cannot see/delete the private task
        assert requests.delete(f"{BASE_URL}/api/tasks/{t['task_id']}", headers=ADMIN, timeout=30).status_code == 404
        d = requests.delete(f"{BASE_URL}/api/tasks/{t['task_id']}", headers=EMP, timeout=30)
        assert d.status_code == 200
        assert not any(x["task_id"] == t["task_id"] for x in g("/api/tasks", EMP).json())

    def test_task_validation(self):
        r = requests.post(f"{BASE_URL}/api/tasks", headers=EMP, json={"title": "TEST_x", "due_date": "01-02-2026"},
                          timeout=30)
        assert r.status_code == 400
        r = requests.post(f"{BASE_URL}/api/tasks", headers=EMP, json={"title": "TEST_x", "assignee_id": ADMIN_ID},
                          timeout=30)
        assert r.status_code == 403


# ---------- Compliance dashboard + export ----------
class TestCompliance:
    def test_compliance_admin(self):
        r = g("/api/compliance")
        assert r.status_code == 200
        d = r.json()
        assert set(d) >= {"rows", "year", "summary"}
        s = d["summary"]
        assert s["staff"] == len(d["rows"]) and 0 <= s["policy_pct"] <= 100
        assert all(r_["user_id"] not in (ADMIN_ID, EMP_ID) for r_ in d["rows"])  # hidden users excluded
        for row in d["rows"]:
            assert {"policies_pending", "certs_expired", "certs_expiring", "cpd_hours", "needs_attention"} <= set(row)
            assert "_id" not in row

    def test_compliance_employee_forbidden(self):
        assert g("/api/compliance", EMP).status_code == 403

    def test_export_xlsx(self):
        r = requests.get(f"{BASE_URL}/api/compliance/export?token=test_session_admin", timeout=60)
        assert r.status_code == 200
        assert "spreadsheetml" in r.headers["content-type"]
        assert "attachment" in r.headers.get("content-disposition", "")
        from openpyxl import load_workbook
        wb = load_workbook(io.BytesIO(r.content))
        assert wb.sheetnames == ["Staff compliance", "Summary"]
        ws = wb["Staff compliance"]
        assert ws.cell(1, 1).value == "Name"
        assert ws.max_row - 1 == g("/api/compliance").json()["summary"]["staff"]

    def test_export_employee_forbidden(self):
        assert requests.get(f"{BASE_URL}/api/compliance/export?token=test_session_employee",
                            timeout=30).status_code == 403
        assert requests.get(f"{BASE_URL}/api/compliance/export", timeout=30).status_code == 403
        assert requests.get(f"{BASE_URL}/api/compliance/export", headers=ADMIN, timeout=60).status_code == 200


# ---------- New Starter checklist ----------
@pytest.fixture
def emp_new_starter():
    orig = g("/api/auth/me", EMP).json().get("staff_group")
    r = requests.patch(f"{BASE_URL}/api/users/{EMP_ID}/group", headers=ADMIN,
                       json={"staff_group": "new_starter_employee"}, timeout=30)
    assert r.status_code == 200 and r.json()["staff_group"] == "new_starter_employee"
    yield orig
    requests.patch(f"{BASE_URL}/api/users/{EMP_ID}/group", headers=ADMIN, json={"staff_group": orig}, timeout=30)
    assert g("/api/auth/me", EMP).json().get("staff_group") == orig


class TestStarterChecklist:
    def test_employee_cannot_set_group(self):
        assert requests.patch(f"{BASE_URL}/api/users/{EMP_ID}/group", headers=EMP,
                              json={"staff_group": "new_starter_employee"}, timeout=30).status_code == 403

    def test_bad_group(self):
        assert requests.patch(f"{BASE_URL}/api/users/{EMP_ID}/group", headers=ADMIN,
                              json={"staff_group": "bogus"}, timeout=30).status_code == 400

    def test_checklist_flow(self, emp_new_starter):
        d = g("/api/starter-checklist", EMP).json()
        assert d["is_new_starter"] is True
        assert d["total"] == len(d["items"]) and d["done"] == sum(1 for i in d["items"] if i["done"])
        keys = [i["key"] for i in d["items"]]
        assert "policies" in keys and "certificates" in keys
        forms = [i for i in d["items"] if i["type"] == "form"]
        assert forms, "No New Starter forms visible to new_starter_employee"
        k = forms[0]["key"]
        before = forms[0]["done"]
        r1 = requests.post(f"{BASE_URL}/api/starter-checklist/{k}", headers=EMP, timeout=30)
        assert r1.status_code == 200 and r1.json()["done"] is (not before)
        d2 = g("/api/starter-checklist", EMP).json()
        item = next(i for i in d2["items"] if i["key"] == k)
        assert item["done"] is (not before) and d2["done"] == d["done"] + (1 if not before else -1)
        # compliance shows starter progress for this user? (hidden users excluded -> not expected)
        r2 = requests.post(f"{BASE_URL}/api/starter-checklist/{k}", headers=EMP, timeout=30)
        assert r2.status_code == 200 and r2.json()["done"] is before
        assert requests.post(f"{BASE_URL}/api/starter-checklist/policies", headers=EMP,
                             timeout=30).status_code == 400
        assert requests.post(f"{BASE_URL}/api/starter-checklist/form:nope", headers=EMP,
                             timeout=30).status_code == 404
