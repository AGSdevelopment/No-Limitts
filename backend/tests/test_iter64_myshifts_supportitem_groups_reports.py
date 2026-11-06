# Iter64: My Shifts (all dates), funding support item, Participant Groups (chat/announce/tasks/compliance), Reports files
import asyncio
import io
import os
import re
import secrets
import sys
from datetime import datetime, timedelta, timezone

import pytest
import requests

sys.path.insert(0, "/app/backend")
loop = asyncio.new_event_loop()
asyncio.set_event_loop(loop)
from core import db  # noqa: E402

BASE_URL = os.environ.get("EXPO_BACKEND_URL").rstrip("/")
API = f"{BASE_URL}/api"


def run(c):
    return loop.run_until_complete(c)


TAG = secrets.token_hex(3)
PERTH = timezone(timedelta(hours=8))
now = datetime.now(PERTH)
today = now.date()
iso = lambda n: (today + timedelta(days=n)).isoformat()  # noqa: E731
dmy = lambda s: f"{s[8:10]}-{s[5:7]}-{s[:4]}"  # noqa: E731
ADMIN = {"Authorization": "Bearer test_session_admin"}
U = {k: f"user_t64{k}{TAG}" for k in ("co", "w1", "w2", "w3", "fin", "ros", "hr")}
H = {k: {"Authorization": f"Bearer tok_t64{k}{TAG}"} for k in U}
TOK = {k: f"tok_t64{k}{TAG}" for k in U}
PID, PNAME, FA = f"par_t64{TAG}", f"TEST_T64 Participant {TAG}", f"fund_t64a{TAG}"
IMPORT_NAME = f"TEST_T64 Import {TAG}"
S = {}


def mkuser(k, **kw):
    return {"user_id": U[k], "name": f"TEST_T64 {k} {TAG}", "email": f"t64{k}{TAG}@example.com", "role": "employee",
            "created_at": now.isoformat(), **kw}


def shift(sid, date, worker, **kw):
    return {"shift_id": sid, "date": date, "start": "09:00", "end": "11:00", "participant_id": PID, "participant_name": PNAME,
            "funding_id": FA, "funding_type": "NDIA", "unit_rate": 50.0, "worker_id": worker, "worker_name": "TEST", "minutes": 120,
            "est_units": 2.0, "hourly": True, "est_cost": 100.0, "notes": "", "status": "scheduled", "auto_accepted": True,
            "created_by": "TEST", "created_at": now.isoformat(), **kw}


@pytest.fixture(scope="module", autouse=True)
def seed():
    run(db.users.insert_many([
        mkuser("co", user_type="support_coordinator", hidden=True), mkuser("w1", user_type="support_worker"),
        mkuser("w2", user_type="support_worker"), mkuser("w3", user_type="support_worker"),
        mkuser("fin", user_type="support_worker", permissions=["finance"], hidden=True),
        mkuser("ros", user_type="support_worker", permissions=["rosters"], hidden=True), mkuser("hr", user_type="hr", hidden=True)]))
    run(db.user_sessions.insert_many([{"session_token": TOK[k], "user_id": U[k], "created_at": datetime.now(timezone.utc),
                                       "expires_at": datetime.now(timezone.utc) + timedelta(days=1)} for k in U]))
    run(db.participants.insert_one({"participant_id": PID, "name": PNAME, "key": PNAME.casefold(), "assigned_ids": [U["w1"], U["w2"]],
                                    "profile": {}}))
    run(db.fundings.insert_one({"funding_id": FA, "participant_id": PID, "participant_name": PNAME, "participant_email": "",
                                "management_type": "NDIA", "units": 500.0, "unit_type": "Hour", "unit_rate": 50.0, "budget": 25000.0,
                                "payer": {"name": "TEST payer", "email": "payer@example.com", "company": "TEST Co", "abn": ""},
                                "start_date": iso(-400), "end_date": iso(400), "rate_history": [], "created_by": "TEST",
                                "created_at": now.isoformat()}))
    run(db.shifts.insert_many([shift(f"shf_t64old{TAG}", iso(-200), U["ros"]), shift(f"shf_t64far{TAG}", iso(200), U["ros"]),
                               shift(f"shf_t64inv{TAG}", iso(-10), U["w1"], status="completed", invoice_id="inv_TEST64")]))
    yield
    run(db.shifts.delete_many({"participant_id": PID}))
    pids = [p["participant_id"] for p in run(db.participants.find({"key": IMPORT_NAME.casefold()}, {"_id": 0}).to_list(5))] + [PID]
    run(db.fundings.delete_many({"participant_id": {"$in": pids}}))
    run(db.participants.delete_many({"participant_id": {"$in": pids}}))
    for g in run(db.participant_groups.find({"participant_id": PID}, {"_id": 0}).to_list(5)):
        run(db.conversations.delete_one({"conversation_id": g["conversation_id"]}))
        run(db.messages.delete_many({"conversation_id": g["conversation_id"]}))
    run(db.participant_groups.delete_many({"participant_id": PID}))
    run(db.tasks.delete_many({"assignee_id": {"$in": list(U.values())}}))
    run(db.report_files.delete_many({"uploaded_by": {"$in": list(U.values())}}))
    run(db.notifications.delete_many({"user_id": {"$in": list(U.values())}}))
    run(db.user_sessions.delete_many({"session_token": {"$in": list(TOK.values())}}))
    run(db.users.delete_many({"user_id": {"$in": list(U.values())}}))


# ---- My Shifts ----
class TestMyShifts:
    def test_mine_all_dates_for_rosters_user(self):
        r = requests.get(f"{API}/shifts", headers=H["ros"], params={"mine": "true"})
        assert r.status_code == 200, r.text
        ids = {s["shift_id"] for s in r.json()}
        assert {f"shf_t64old{TAG}", f"shf_t64far{TAG}"} <= ids
        assert all(s["worker_id"] == U["ros"] for s in r.json())

    def test_default_window_still_applies(self):
        ids = {s["shift_id"] for s in requests.get(f"{API}/shifts", headers=H["ros"]).json()}
        assert f"shf_t64old{TAG}" not in ids and f"shf_t64far{TAG}" not in ids

    def test_access_has_shifts(self):
        assert requests.get(f"{API}/pm/access", headers=H["ros"]).json()["has_shifts"] is True
        assert requests.get(f"{API}/pm/access", headers=H["hr"]).json()["has_shifts"] is False


# ---- Funding support item ----
def xlsx(cols, rows):
    from openpyxl import Workbook
    wb = Workbook()
    wb.active.append(cols)
    for r in rows:
        wb.active.append(r)
    b = io.BytesIO()
    wb.save(b)
    return b.getvalue()


class TestSupportItem:
    def test_template_columns(self):
        from openpyxl import load_workbook
        r = requests.get(f"{API}/funding/template", params={"token": "test_session_admin"})
        assert r.status_code == 200
        head = [c.value for c in load_workbook(io.BytesIO(r.content)).worksheets[0][1]]
        assert "Support item number" in head and "Support item name" in head
        S["cols"] = head

    def test_import_with_and_without_item(self):
        cols = S["cols"]
        base = [IMPORT_NAME, "", "NDIA", 100, "Hour", 60, dmy(iso(-30)), dmy(iso(300)), "", "TEST Co", "pay@example.com", "0400",
                "", "", "", "", ""]
        r = requests.post(f"{API}/funding/import", headers=ADMIN, files={"file": ("f.xlsx", xlsx(cols, [base + ["01_011_0107_1_1", "Self-Care"]]))})
        assert r.status_code == 200 and len(r.json()["added"]) == 1, r.text
        old_cols = [c for c in cols if not c.startswith("Support item")]
        r2 = requests.post(f"{API}/funding/import", headers=ADMIN,
                           files={"file": ("g.xlsx", xlsx(old_cols, [base[:4] + ["Each"] + base[5:]]))})
        assert r2.status_code == 200 and len(r2.json()["added"]) == 1, r2.text
        p = run(db.participants.find_one({"key": IMPORT_NAME.casefold()}, {"_id": 0}))
        fs = {f["unit_type"]: f for f in run(db.fundings.find({"participant_id": p["participant_id"]}, {"_id": 0}).to_list(5))}
        assert fs["Hour"]["support_item_number"] == "01_011_0107_1_1" and fs["Hour"]["support_item_name"] == "Self-Care"
        assert fs["Each"]["support_item_number"] == ""

    def test_set_item_forbidden(self):
        for k in ("w1", "ros", "co"):
            assert requests.put(f"{API}/funding/{FA}/item", headers=H[k], json={"support_item_number": "X"}).status_code == 403

    def test_set_item_copies_to_uninvoiced(self):
        r = requests.put(f"{API}/funding/{FA}/item", headers=H["fin"], json={"support_item_number": " 04_104_0125_6_1 ", "support_item_name": "Community Access"})
        assert r.status_code == 200, r.text
        f = run(db.fundings.find_one({"funding_id": FA}, {"_id": 0}))
        assert f["support_item_number"] == "04_104_0125_6_1" and f["support_item_name"] == "Community Access"
        assert run(db.shifts.find_one({"shift_id": f"shf_t64far{TAG}"}))["support_item_number"] == "04_104_0125_6_1"
        assert "support_item_number" not in run(db.shifts.find_one({"shift_id": f"shf_t64inv{TAG}"}))
        assert requests.put(f"{API}/funding/fund_nope{TAG}/item", headers=H["fin"], json={}).status_code == 404

    def test_new_shift_copies_item(self):
        r = requests.post(f"{API}/shifts", headers=ADMIN, json={"participant_id": PID, "funding_id": FA, "worker_id": U["w1"],
                                                               "date": dmy(iso(45)), "start": "13:00", "end": "14:00"})
        assert r.status_code == 200, r.text
        s = run(db.shifts.find_one({"participant_id": PID, "worker_id": U["w1"], "date": iso(45)}, {"_id": 0}))
        assert s["support_item_number"] == "04_104_0125_6_1" and s["support_item_name"] == "Community Access"

    def test_invoice_line_description(self):
        from routes.pm_invoices import line_for
        base = {"shift_id": "x", "date": iso(0), "worker_name": "W", "funding_type": "NDIA", "start": "09:00", "end": "10:00",
                "approved_minutes": 60, "clock_in": {"time": "09:00"}, "clock_out": {"time": "10:00"}}
        d = line_for({**base, "support_item_number": "04_104", "support_item_name": "Community Access"})["description"]
        assert d.startswith("04_104 Community Access ·"), d
        assert line_for(base)["description"].startswith("NDIA support ·")


# ---- Participant Groups ----
class TestGroups:
    def test_create_permissions(self):
        assert requests.post(f"{API}/participant-groups", headers=H["w1"], json={"participant_id": PID}).status_code == 403
        r = requests.post(f"{API}/participant-groups", headers=H["co"], json={"participant_id": PID})
        assert r.status_code == 200, r.text
        g = r.json()
        S["g"] = g
        assert {m["user_id"] for m in g["members"]} == {U["w1"], U["w2"]}
        assert all(m["from_team"] for m in g["members"])
        assert requests.post(f"{API}/participant-groups", headers=H["co"], json={"participant_id": PID}).status_code == 400
        assert run(db.notifications.count_documents({"user_id": U["w1"], "title": {"$regex": "added to"}})) == 1

    def test_edit_members(self):
        gid = S["g"]["group_id"]
        assert requests.put(f"{API}/participant-groups/{gid}/members", headers=H["w1"], json={"add_ids": [U["w3"]]}).status_code == 403
        r = requests.put(f"{API}/participant-groups/{gid}/members", headers=H["co"], json={"add_ids": [U["w3"]], "remove_ids": [U["w2"]]})
        assert r.status_code == 200, r.text
        assert {m["user_id"] for m in r.json()["members"]} == {U["w1"], U["w3"]}
        j = requests.get(f"{API}/participant-groups/{gid}", headers=H["co"]).json()
        assert {m["user_id"] for m in j["members"]} == {U["w1"], U["w3"]}

    def test_conversation_visibility(self):
        cid = S["g"]["conversation_id"]
        c1 = [c for c in requests.get(f"{API}/conversations", headers=H["w1"]).json() if c["conversation_id"] == cid]
        assert len(c1) == 1 and c1[0]["type"] == "group"
        assert cid not in {c["conversation_id"] for c in requests.get(f"{API}/conversations", headers=H["w2"]).json()}
        assert requests.get(f"{API}/conversations/{cid}/messages", headers=H["w2"]).status_code == 404
        assert requests.get(f"{API}/participant-groups/{S['g']['group_id']}", headers=H["w2"]).status_code == 404

    def test_message_notifies(self):
        cid = S["g"]["conversation_id"]
        r = requests.post(f"{API}/conversations/{cid}/messages", headers=H["w1"], json={"text": f"hello {TAG}"})
        assert r.status_code == 200, r.text
        assert run(db.notifications.count_documents({"user_id": U["w3"], "body": {"$regex": TAG}})) == 1
        assert run(db.notifications.count_documents({"user_id": U["co"], "body": {"$regex": TAG}})) == 1

    def test_announce(self):
        gid, cid = S["g"]["group_id"], S["g"]["conversation_id"]
        assert requests.post(f"{API}/participant-groups/{gid}/announce", headers=H["w1"], json={"text": "x yz"}).status_code == 403
        assert requests.post(f"{API}/participant-groups/{gid}/announce", headers=H["co"], json={"text": " "}).status_code == 400
        r = requests.post(f"{API}/participant-groups/{gid}/announce", headers=H["co"], json={"text": f"Team meeting {TAG}"})
        assert r.status_code == 200 and r.json()["sent_to"] == 2
        msgs = requests.get(f"{API}/conversations/{cid}/messages", headers=H["w3"]).json()
        assert any("Announcement" in m["text"] and TAG in m["text"] for m in (msgs if isinstance(msgs, list) else msgs.get("messages", [])))
        assert run(db.notifications.count_documents({"user_id": U["w1"], "title": {"$regex": "Announcement"}})) == 1

    def test_tasks_and_progress(self):
        gid = S["g"]["group_id"]
        assert requests.post(f"{API}/participant-groups/{gid}/tasks", headers=H["co"], json={"title": "x", "kind": "bad"}).status_code == 400
        assert requests.post(f"{API}/participant-groups/{gid}/tasks", headers=H["co"], json={"title": "x", "due_date": "1/2/26"}).status_code == 400
        r = requests.post(f"{API}/participant-groups/{gid}/tasks", headers=H["co"],
                          json={"title": f"Read BSP {TAG}", "kind": "acknowledge", "due_date": iso(-1)})
        assert r.status_code == 200 and r.json()["assigned"] == 2, r.text
        mine = [t for t in requests.get(f"{API}/tasks", headers=H["w1"]).json() if t.get("participant_group_id") == gid]
        assert len(mine) == 1 and mine[0]["kind"] == "acknowledge"
        S["w1_task"] = mine[0]["task_id"]
        S["w3_task"] = [t for t in requests.get(f"{API}/tasks", headers=H["w3"]).json() if t.get("participant_group_id") == gid][0]["task_id"]
        # someone else cannot tick w1's task
        assert requests.patch(f"{API}/tasks/{S['w1_task']}", headers=H["w3"], json={"status": "done"}).status_code == 404
        assert requests.patch(f"{API}/tasks/{S['w1_task']}", headers=H["w1"], json={"status": "done"}).status_code == 200
        co = requests.get(f"{API}/participant-groups/{gid}", headers=H["co"]).json()
        t = co["tasks"][0]
        assert [d["user_id"] for d in t["done"]] == [U["w1"]] and [o["user_id"] for o in t["outstanding"]] == [U["w3"]]
        assert t["overdue"] is True and co["overdue_tasks"] == 1 and co["open_tasks"] == 1
        m1 = requests.get(f"{API}/participant-groups/{gid}", headers=H["w1"]).json()["tasks"][0]
        assert m1["mine_done"] is True and m1["done"] == [] and m1["outstanding"] == []
        m3 = requests.get(f"{API}/participant-groups/{gid}", headers=H["w3"]).json()["tasks"][0]
        assert m3["mine_done"] is False

    def test_compliance(self):
        assert requests.get(f"{API}/participant-groups-compliance", headers=H["w1"]).status_code == 403
        j = requests.get(f"{API}/participant-groups-compliance", headers=H["co"]).json()
        g = [x for x in j["groups"] if x["group_id"] == S["g"]["group_id"]]
        assert len(g) == 1 and len(g[0]["tasks"][0]["outstanding"]) == 1
        assert j["outstanding"] >= 1 and j["overdue"] >= 1

    def test_admin_cannot_tick_member_task(self):
        """Group tasks must be actioned by the member themselves."""
        r = requests.patch(f"{API}/tasks/{S['w3_task']}", headers=ADMIN, json={"status": "done"})
        if r.status_code == 200:  # revert, then flag
            requests.patch(f"{API}/tasks/{S['w3_task']}", headers=ADMIN, json={"status": "open"})
        assert r.status_code == 404, "admin was able to tick another member's group task"

    def test_delete(self):
        gid, cid = S["g"]["group_id"], S["g"]["conversation_id"]
        assert requests.delete(f"{API}/participant-groups/{gid}", headers=H["w1"]).status_code == 403
        assert requests.delete(f"{API}/participant-groups/{gid}", headers=H["co"]).status_code == 200
        assert requests.get(f"{API}/participant-groups/{gid}", headers=H["co"]).status_code == 404
        assert run(db.conversations.find_one({"conversation_id": cid})) is None
        assert run(db.tasks.count_documents({"participant_group_id": gid, "status": "open"})) == 0


# ---- Reports files ----
class TestReports:
    def test_access(self):
        assert requests.get(f"{API}/reports/files", headers=H["w1"]).status_code == 403
        for k in ("fin", "hr", "co"):
            assert requests.get(f"{API}/reports/files", headers=H[k]).status_code == 200, k
        assert requests.get(f"{API}/reports/files", headers=ADMIN).status_code == 200

    def test_upload_open_delete(self):
        body = f"report {TAG}".encode()
        assert requests.post(f"{API}/reports/files", headers=H["w1"], files={"file": ("r.csv", body, "text/csv")}).status_code == 403
        r = requests.post(f"{API}/reports/files", headers=H["fin"], files={"file": ("r.csv", body, "text/csv")},
                          data={"category": "Finance", "title": f"TEST_T64 {TAG}"})
        assert r.status_code == 200, r.text
        f = r.json()
        assert f["category"] == "Finance" and f["title"] == f"TEST_T64 {TAG}" and "storage_path" not in f
        assert f["file_id"] in {x["file_id"] for x in requests.get(f"{API}/reports/files", headers=H["hr"]).json()}
        o = requests.get(f"{API}/reports/files/{f['file_id']}", params={"token": TOK["hr"]})
        assert o.status_code == 200 and o.content == body
        assert requests.get(f"{API}/reports/files/{f['file_id']}", params={"token": TOK["w1"]}).status_code == 403
        assert requests.delete(f"{API}/reports/files/{f['file_id']}", headers=H["hr"]).status_code == 404
        assert requests.delete(f"{API}/reports/files/{f['file_id']}", headers=H["fin"]).status_code == 200
        r2 = requests.post(f"{API}/reports/files", headers=H["co"], files={"file": ("x.pdf", b"%PDF-1", "application/pdf")},
                           data={"category": "Nope"})
        assert r2.status_code == 200 and r2.json()["category"] == "Other" and r2.json()["title"] == "x.pdf"
        assert requests.delete(f"{API}/reports/files/{r2.json()['file_id']}", headers=ADMIN).status_code == 200
        assert requests.post(f"{API}/reports/files", headers=H["co"], files={"file": ("e.txt", b"", "text/plain")}).status_code == 400
