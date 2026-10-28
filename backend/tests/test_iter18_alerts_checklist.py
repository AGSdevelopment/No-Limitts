# Iteration 18: missing-certificate alerts (compliance + export), New Starter checklist guard,
# and checklist-completion admin alerts (in-process with email/notify MOCKED to avoid real emails).
import asyncio
import io
import os
import sys
import pytest
import requests
from pathlib import Path

sys.path.insert(0, "/app/backend")


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


def set_group(group):
    r = requests.patch(f"{BASE_URL}/api/users/{EMP_ID}/group", headers=ADMIN, json={"staff_group": group}, timeout=30)
    assert r.status_code == 200, r.text
    return r.json()


# ---------- Missing certificate alerts ----------
class TestNoCerts:
    def test_compliance_no_certs_flags(self):
        r = requests.get(f"{BASE_URL}/api/compliance", headers=ADMIN, timeout=60)
        assert r.status_code == 200
        d = r.json()
        assert d["rows"], "no rows"
        for row in d["rows"]:
            assert isinstance(row["no_certs"], bool)
            assert row["no_certs"] == (row["certs_total"] == 0)
            if row["no_certs"]:
                assert row["needs_attention"] is True
        assert d["summary"]["no_certs"] == sum(1 for x in d["rows"] if x["no_certs"])
        assert d["summary"]["no_certs"] > 0

    def test_compliance_employee_forbidden(self):
        assert requests.get(f"{BASE_URL}/api/compliance", headers=EMP, timeout=30).status_code == 403

    def test_export_no_certs(self):
        from openpyxl import load_workbook
        d = requests.get(f"{BASE_URL}/api/compliance", headers=ADMIN, timeout=60).json()
        r = requests.get(f"{BASE_URL}/api/compliance/export", params={"token": "test_session_admin"}, timeout=60)
        assert r.status_code == 200
        wb = load_workbook(io.BytesIO(r.content))
        ws = wb["Staff compliance"]
        head = [c.value for c in ws[1]]
        ci = head.index("Certificate issues")
        cc = head.index("Certificates")
        rows = list(ws.iter_rows(min_row=2, values_only=True))
        assert len(rows) == len(d["rows"])
        for row in rows:
            if row[cc] == 0:
                assert row[ci] == "No certificates", row
        summary = {r[0]: r[1] for r in wb["Summary"].iter_rows(values_only=True)}
        assert summary["Staff with no certificates"] == d["summary"]["no_certs"]

    def test_export_employee_forbidden(self):
        r = requests.get(f"{BASE_URL}/api/compliance/export", params={"token": "test_session_employee"}, timeout=30)
        assert r.status_code == 403


# ---------- Starter checklist guard ----------
@pytest.fixture
def new_starter():
    set_group("new_starter_employee")
    yield
    # revert: untick any forms, group back to none
    items = requests.get(f"{BASE_URL}/api/starter-checklist", headers=EMP, timeout=30).json()["items"]
    for i in items:
        if i["type"] == "form" and i["done"]:
            requests.post(f"{BASE_URL}/api/starter-checklist/{i['key']}", headers=EMP, timeout=30)
    set_group(None)


class TestChecklistGuard:
    def test_employee_without_group_403(self):
        set_group(None)
        items = requests.get(f"{BASE_URL}/api/starter-checklist", headers=EMP, timeout=30).json()
        form = next(i for i in items["items"] if i["type"] == "form")
        assert items["is_new_starter"] is False
        r = requests.post(f"{BASE_URL}/api/starter-checklist/{form['key']}", headers=EMP, timeout=30)
        assert r.status_code == 403 and "New Starter" in r.json()["detail"]

    def test_admin_403(self):
        d = requests.get(f"{BASE_URL}/api/starter-checklist", headers=ADMIN, timeout=30).json()
        assert d["is_new_starter"] is False
        form = next(i for i in d["items"] if i["type"] == "form")
        r = requests.post(f"{BASE_URL}/api/starter-checklist/{form['key']}", headers=ADMIN, timeout=30)
        assert r.status_code == 403

    def test_other_group_403(self):
        set_group("therapist_employee")
        try:
            r = requests.post(f"{BASE_URL}/api/starter-checklist/form:x", headers=EMP, timeout=30)
            assert r.status_code == 403
        finally:
            set_group(None)

    def test_new_starter_toggle(self, new_starter):
        d = requests.get(f"{BASE_URL}/api/starter-checklist", headers=EMP, timeout=30).json()
        assert d["is_new_starter"] is True
        forms = [i for i in d["items"] if i["type"] == "form"]
        assert forms
        k = forms[0]["key"]
        r1 = requests.post(f"{BASE_URL}/api/starter-checklist/{k}", headers=EMP, timeout=30)
        assert r1.status_code == 200 and r1.json()["done"] is True
        d2 = requests.get(f"{BASE_URL}/api/starter-checklist", headers=EMP, timeout=30).json()
        assert next(i for i in d2["items"] if i["key"] == k)["done"] is True
        r2 = requests.post(f"{BASE_URL}/api/starter-checklist/{k}", headers=EMP, timeout=30)
        assert r2.status_code == 200 and r2.json()["done"] is False

    def test_new_starter_auto_items_400_and_unknown_404(self, new_starter):
        assert requests.post(f"{BASE_URL}/api/starter-checklist/policies", headers=EMP, timeout=30).status_code == 400
        assert requests.post(f"{BASE_URL}/api/starter-checklist/form:nope", headers=EMP, timeout=30).status_code == 404

    def test_new_starter_row_in_compliance_hidden(self, new_starter):
        # test users are hidden so they never appear on the dashboard
        rows = requests.get(f"{BASE_URL}/api/compliance", headers=ADMIN, timeout=60).json()["rows"]
        assert all(r["user_id"] not in (EMP_ID, ADMIN_ID) for r in rows)


# ---------- Completion alert (in-process, send_email + notify MOCKED) ----------
def test_completion_alert_once_only():
    import routes.compliance as rc
    from core import db

    sent, notes = [], []

    async def fake_email(**kw):
        sent.append(kw["to"])

    async def fake_notify(uids, ntype, title, body, link=""):
        notes.append((tuple(uids), ntype, title, link))

    async def run():
        orig_notify, orig_email = rc.notify, rc.send_email
        rc.notify, rc.send_email = fake_notify, fake_email
        pols_before = [p["policy_id"] async for p in db.policies.find({"acknowledged_by": EMP_ID}, {"_id": 0, "policy_id": 1})]
        forms = await db.forms.find({"category": "New Starter"}, {"_id": 0, "form_id": 1}).to_list(100)
        user0 = await db.users.find_one({"user_id": EMP_ID}, {"_id": 0})
        result = {}
        try:
            await db.users.update_one({"user_id": EMP_ID}, {"$set": {"staff_group": "new_starter_employee"},
                                                            "$unset": {"starter_completed_at": ""}})
            # not complete yet -> no alert
            await rc.check_starter_complete({"user_id": EMP_ID})
            result["early"] = (list(notes), list(sent))
            await db.policies.update_many({}, {"$addToSet": {"acknowledged_by": EMP_ID}})
            for f in forms:
                await db.checklist_progress.update_one({"user_id": EMP_ID, "item_key": f"form:{f['form_id']}"},
                                                       {"$set": {"done_at": "2026-01-01T00:00:00+00:00"}}, upsert=True)
            certs = await db.certificates.count_documents({"owner_id": EMP_ID, "is_deleted": {"$ne": True}})
            result["certs"] = certs
            # concurrent calls -> exactly one alert
            await asyncio.gather(*[rc.check_starter_complete({"user_id": EMP_ID}) for _ in range(4)])
            await rc.check_starter_complete({"user_id": EMP_ID})
            result["notes"], result["sent"] = list(notes), list(sent)
            u = await db.users.find_one({"user_id": EMP_ID}, {"_id": 0})
            result["completed_at"] = u.get("starter_completed_at")
            result["admins_visible"] = [a["user_id"] async for a in db.users.find({"role": "admin", "hidden": True}, {"_id": 0, "user_id": 1})]
        finally:
            rc.notify, rc.send_email = orig_notify, orig_email
            await db.policies.update_many({"policy_id": {"$nin": pols_before}}, {"$pull": {"acknowledged_by": EMP_ID}})
            await db.checklist_progress.delete_many({"user_id": EMP_ID})
            await db.users.update_one({"user_id": EMP_ID}, {"$set": {"staff_group": user0.get("staff_group")},
                                                            "$unset": {"starter_completed_at": ""}})
        return result

    res = asyncio.run(run())
    print("RESULT", res)
    assert res["early"] == ([], [])
    assert res["certs"] > 0
    assert res["completed_at"]
    assert len(res["notes"]) == 1, res["notes"]
    uids, ntype, title, link = res["notes"][0]
    assert ntype == "starter" and title == "New Starter checklist complete" and link == f"/starter/{EMP_ID}"
    assert set(uids) == set(res["admins_visible"])
    # hidden test user -> only hidden test admins alerted, no email (iter19 behaviour)
    print("test admin included:", ADMIN_ID in uids, "| emails would go to:", res["sent"])
    assert all(not e.endswith("@example.com") for e in res["sent"])
