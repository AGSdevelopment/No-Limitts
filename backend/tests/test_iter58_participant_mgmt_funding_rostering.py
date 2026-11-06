# Iteration 58: Participant Management - Funding (import/rate change), Support Team tags, Rostering (shifts, clock in/out, approvals, report)
import io
import os
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest
import requests
from openpyxl import Workbook, load_workbook
from pymongo import MongoClient


def _env(path, key):
    for line in open(path):
        if line.startswith(key + "="):
            return line.split("=", 1)[1].strip().strip('"')
    return None


BASE_URL = (os.environ.get("EXPO_BACKEND_URL") or _env("/app/frontend/.env", "EXPO_PUBLIC_BACKEND_URL")).rstrip("/")
API = f"{BASE_URL}/api"
ADMIN = {"Authorization": "Bearer test_session_admin"}
EMP = {"Authorization": "Bearer test_session_employee"}
W2_TOKEN = "TEST_session_pmw2_iter58"
W2 = {"Authorization": f"Bearer {W2_TOKEN}"}
W2_ID = "user_TEST_pmw2_iter58"
EMP_ID = "user_testemp001"
PERTH = ZoneInfo("Australia/Perth")
mdb = MongoClient(_env("/app/backend/.env", "MONGO_URL"))[_env("/app/backend/.env", "DB_NAME")]

CREATED = {"shifts": [], "fundings": [], "participants": [], "tags": []}
S = {}  # shared state


def dmy(d):
    return d.strftime("%d-%m-%Y")


def now():
    return datetime.now(PERTH)


def build_xlsx(rows):
    cols = ["Participant name", "Participant email", "Funding management type", "Units", "Unit type", "$ per unit",
            "Service start date", "Service end date", "Invoice payer name", "Invoice payer company", "Invoice payer email",
            "Invoice payer phone", "Invoice payer ABN", "Representative name", "Representative email",
            "Representative phone", "Representative relationship"]
    wb = Workbook()
    ws = wb.active
    ws.append(cols)
    for r in rows:
        ws.append(r)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


@pytest.fixture(scope="module", autouse=True)
def setup_module_data():
    mdb.users.insert_one({"user_id": W2_ID, "name": "TEST PM Worker Two", "email": "test.pmw2.iter58@example.com",
                          "role": "employee", "user_type": "support_worker", "hidden": True,
                          "created_at": datetime.now(timezone.utc).isoformat()})
    mdb.user_sessions.insert_one({"session_token": W2_TOKEN, "user_id": W2_ID,
                                  "expires_at": datetime.now(timezone.utc) + timedelta(days=1)})
    yield
    if CREATED["shifts"]:
        mdb.shifts.delete_many({"shift_id": {"$in": CREATED["shifts"]}})
    if CREATED["fundings"]:
        mdb.fundings.delete_many({"funding_id": {"$in": CREATED["fundings"]}})
    if CREATED["participants"]:
        mdb.participants.delete_many({"participant_id": {"$in": CREATED["participants"]}})
    if CREATED["tags"]:
        mdb.team_tag_requests.delete_many({"request_id": {"$in": CREATED["tags"]}})
    mdb.notifications.delete_many({"user_id": W2_ID})
    mdb.notifications.delete_many({"title": {"$regex": "TEST_PM", "$options": "i"}})
    mdb.user_sessions.delete_one({"session_token": W2_TOKEN})
    mdb.users.delete_one({"user_id": W2_ID})


def mk_shift(fid, pid, date, start, end, worker=EMP_ID):
    r = requests.post(f"{API}/shifts", headers=ADMIN, json={"participant_id": pid, "funding_id": fid, "worker_id": worker,
                                                             "date": date, "start": start, "end": end, "notes": "TEST_"})
    if r.status_code == 200:
        CREATED["shifts"].append(r.json()["shift_id"])
    return r


# ---- Permissions & access ----
class TestPermissions:
    def test_employee_cannot_set_permissions(self):
        r = requests.put(f"{API}/users/{W2_ID}/permissions", headers=EMP, json={"permissions": ["finance"]})
        assert r.status_code == 403

    def test_admin_sets_permissions_filters_unknown(self):
        r = requests.put(f"{API}/users/{W2_ID}/permissions", headers=ADMIN, json={"permissions": ["rosters", "finance", "boss"]})
        assert r.status_code == 200 and r.json()["permissions"] == ["finance", "rosters"]
        assert mdb.users.find_one({"user_id": W2_ID})["permissions"] == ["finance", "rosters"]
        r = requests.put(f"{API}/users/{W2_ID}/permissions", headers=ADMIN, json={"permissions": []})
        assert r.json()["permissions"] == []

    def test_admin_permissions_404(self):
        assert requests.put(f"{API}/users/nope_x/permissions", headers=ADMIN, json={"permissions": []}).status_code == 404

    def test_access(self):
        a = requests.get(f"{API}/pm/access", headers=ADMIN).json()
        assert a["finance"] and a["rosters"] and a["coordinator"]
        e = requests.get(f"{API}/pm/access", headers=EMP).json()
        assert e["finance"] is False and e["rosters"] is False and e["worker"] is True

    def test_worker_blocked_from_office(self):
        assert requests.get(f"{API}/funding", headers=EMP).status_code == 403
        assert requests.post(f"{API}/shifts", headers=EMP, json={"participant_id": "x", "funding_id": "x", "worker_id": "x",
                                                                 "date": "01-01-2027", "start": "10:00", "end": "11:00"}).status_code == 403


# ---- Funding template / import / list / rate ----
class TestFunding:
    def test_template_token_query(self):
        r = requests.get(f"{API}/funding/template", params={"token": "test_session_admin"})
        assert r.status_code == 200 and "spreadsheetml" in r.headers["content-type"]
        ws = load_workbook(io.BytesIO(r.content)).worksheets[0]
        assert ws.cell(1, 1).value == "Participant name"
        assert requests.get(f"{API}/funding/template", params={"token": "test_session_employee"}).status_code == 403
        assert requests.get(f"{API}/funding/template").status_code == 401

    def test_import_good_and_bad_rows(self):
        payer = ["", "TEST Plan Co", "inv@test.example", "0800000000"]
        rows = [
            ["TEST_PM Alpha", "alpha@test.example", "NDIA", 100, "Hour", 50, "01-07-2026", "30-06-2027", *payer, "12 345 678 901", "", "", "", ""],
            ["TEST_PM Beta", "beta@test.example", "private", 2, "Hour", 50, "01-07-2026", "30-06-2027", *payer, "", "Rep Person", "rep@test.example", "0400000000", "Mum"],
            ["TEST_PM Bad1", "", "Medicare", 10, "Hour", 50, "01-07-2026", "30-06-2027", *payer, "", "", "", "", ""],
            ["TEST_PM Bad2", "", "NDIA", 10, "Hour", 50, "01-07-2026", "30-06-2027", *payer, "1234", "", "", "", ""],
            ["TEST_PM Bad3", "", "NDIA", 10, "Hour", 50, "01-07-2026", "30-06-2027", "", "TEST Co", "noemail", "0800", "", "", "", "", ""],
            ["TEST_PM Bad4", "", "NDIA", 10, "Hour", 50, "01-07-2026", "30-06-2027", *payer, "", "Rep", "", "", ""],
            ["TEST_PM Bad5", "", "NDIA", -1, "Hour", 50, "30-06-2027", "01-07-2026", *payer, "", "", "", "", ""],
        ]
        r = requests.post(f"{API}/funding/import", headers=ADMIN,
                          files={"file": ("f.xlsx", build_xlsx(rows), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")})
        assert r.status_code == 200, r.text
        d = r.json()
        assert [a["row"] for a in d["added"]] == [2, 3]
        assert d["added"][0]["budget"] == 5000 and d["added"][1]["management_type"] == "Private"
        reasons = {s["row"]: s["reason"] for s in d["skipped"]}
        assert set(reasons) == {4, 5, 6, 7, 8}
        assert "management type" in reasons[4] and "ABN" in reasons[5] and "invoice payer" in reasons[6]
        assert "representative" in reasons[7] and "units" in reasons[8] and "dates" in reasons[8]
        funds = [f for f in requests.get(f"{API}/funding", headers=ADMIN).json() if f["participant_name"].upper().startswith("TEST_PM")]
        for f in funds:
            CREATED["fundings"].append(f["funding_id"])
            if f["participant_id"] not in CREATED["participants"]:
                CREATED["participants"].append(f["participant_id"])
        alpha = next(f for f in funds if "alpha" in f["participant_name"].lower())
        beta = next(f for f in funds if "beta" in f["participant_name"].lower())
        S.update(alpha=alpha, beta=beta)
        assert alpha["remaining"] == 5000 and alpha["units_left"] == 100 and alpha["active"] is True
        assert beta["payer_is_representative"] is False and beta["representative"]["name"] == "Rep Person"

    def test_import_missing_columns(self):
        wb = Workbook(); wb.active.append(["Participant name", "Units"]); buf = io.BytesIO(); wb.save(buf)
        r = requests.post(f"{API}/funding/import", headers=ADMIN, files={"file": ("f.xlsx", buf.getvalue())})
        assert r.status_code == 400 and "Missing columns" in r.json()["detail"]
        r = requests.post(f"{API}/funding/import", headers=ADMIN, files={"file": ("f.txt", b"hello")})
        assert r.status_code == 400

    def test_detail(self):
        r = requests.get(f"{API}/funding/{S['alpha']['funding_id']}", headers=ADMIN)
        assert r.status_code == 200 and r.json()["budget"] == 5000
        assert requests.get(f"{API}/funding/fund_nope", headers=ADMIN).status_code == 404


# ---- Support Team tags ----
class TestTags:
    def test_worker_self_request_pending_then_approve(self):
        pid = S["alpha"]["participant_id"]
        assert requests.post(f"{API}/support-team/tags", headers=EMP, json={"user_id": W2_ID, "participant_id": pid}).status_code == 403
        r = requests.post(f"{API}/support-team/tags", headers=EMP, json={"user_id": EMP_ID, "participant_id": pid})
        assert r.status_code == 200 and r.json()["status"] == "pending"
        rid = r.json()["request"]["request_id"]; CREATED["tags"].append(rid)
        dup = requests.post(f"{API}/support-team/tags", headers=EMP, json={"user_id": EMP_ID, "participant_id": pid})
        assert dup.status_code == 400
        t = requests.get(f"{API}/support-team/tags/{EMP_ID}", headers=EMP).json()
        assert any(x["request_id"] == rid for x in t["pending"]) and t["can_approve"] is False
        assert requests.get(f"{API}/support-team/requests", headers=EMP).status_code == 403
        assert any(x["request_id"] == rid for x in requests.get(f"{API}/support-team/requests", headers=ADMIN).json())
        assert requests.post(f"{API}/support-team/requests/{rid}", headers=ADMIN, json={"approve": True}).status_code == 200
        assert EMP_ID in mdb.participants.find_one({"participant_id": pid})["assigned_ids"]

    def test_admin_request_auto_approves(self):
        r = requests.post(f"{API}/support-team/tags", headers=ADMIN, json={"user_id": EMP_ID, "participant_id": S["beta"]["participant_id"]})
        assert r.status_code == 200 and r.json()["status"] == "approved"
        assert EMP_ID in mdb.participants.find_one({"participant_id": S["beta"]["participant_id"]})["assigned_ids"]

    def test_decline_notifies(self):
        pid = S["alpha"]["participant_id"]
        r = requests.post(f"{API}/support-team/tags", headers=W2, json={"user_id": W2_ID, "participant_id": pid})
        assert r.status_code == 200 and r.json()["status"] == "pending"
        rid = r.json()["request"]["request_id"]; CREATED["tags"].append(rid)
        assert requests.post(f"{API}/support-team/requests/{rid}", headers=ADMIN, json={"approve": False}).status_code == 200
        assert mdb.team_tag_requests.find_one({"request_id": rid})["status"] == "rejected"
        assert W2_ID not in mdb.participants.find_one({"participant_id": pid})["assigned_ids"]
        assert mdb.notifications.find_one({"user_id": W2_ID, "title": {"$regex": "not approved"}})


# ---- Shifts ----
class TestShifts:
    def test_create_validations(self):
        a = S["alpha"]; fut = dmy(now() + timedelta(days=20))
        r = mk_shift(a["funding_id"], a["participant_id"], fut, "10:00", "11:00", worker=W2_ID)
        assert r.status_code == 400 and "Support Team" in r.json()["detail"]
        assert mk_shift(a["funding_id"], a["participant_id"], "01-08-2027", "10:00", "11:00").status_code == 400
        assert mk_shift(a["funding_id"], a["participant_id"], fut, "9:00", "11:00").status_code == 400
        assert mk_shift(a["funding_id"], a["participant_id"], "2026/13/45", "10:00", "11:00").status_code == 400
        r = mk_shift(a["funding_id"], a["participant_id"], dmy(now() - timedelta(days=1)), "10:00", "11:00")
        assert r.status_code == 400 and "already started" in r.json()["detail"]
        b = S["beta"]
        r = mk_shift(b["funding_id"], b["participant_id"], fut, "15:00", "18:00")
        assert r.status_code == 400 and "Not enough funding" in r.json()["detail"]

    def test_auto_accept_and_clash(self):
        a, b = S["alpha"], S["beta"]; fut = dmy(now() + timedelta(days=22))
        r1 = mk_shift(a["funding_id"], a["participant_id"], fut, "10:00", "12:00")
        assert r1.status_code == 200 and r1.json()["status"] == "accepted" and r1.json()["auto_accepted"] is True
        assert r1.json()["funding_type"] == "NDIA" and r1.json()["est_cost"] == 100
        r2 = mk_shift(a["funding_id"], a["participant_id"], fut, "11:00", "12:30")
        assert r2.status_code == 200, "same participant overlap must be allowed"
        r3 = mk_shift(b["funding_id"], b["participant_id"], fut, "12:15", "12:45")
        assert r3.status_code == 409
        r4 = mk_shift(b["funding_id"], b["participant_id"], fut, "12:40", "13:00")
        assert r4.status_code == 409, "gap < 30 min"
        r5 = mk_shift(b["funding_id"], b["participant_id"], fut, "13:00", "13:30")
        assert r5.status_code == 200, r5.text
        S["future_shift"] = r1.json()["shift_id"]

    def test_pending_within_two_weeks_and_worker_view(self):
        a = S["alpha"]
        r = mk_shift(a["funding_id"], a["participant_id"], dmy(now() + timedelta(days=3)), "10:00", "11:00")
        assert r.status_code == 200 and r.json()["status"] == "pending_acceptance"
        sid = r.json()["shift_id"]; S["pending"] = sid
        lst = requests.get(f"{API}/shifts", headers=EMP).json()
        mine = [s for s in lst if s["shift_id"] in CREATED["shifts"]]
        assert mine and all(("funding_type" not in s and "est_cost" not in s and "cost" not in s and "unit_rate" not in s) for s in mine)
        det = requests.get(f"{API}/shifts/{sid}", headers=EMP).json()
        assert "plan" in det and "funding_type" not in det and "est_cost" not in det
        assert requests.get(f"{API}/shifts/{sid}", headers=ADMIN).json()["funding_type"] == "NDIA"
        assert requests.get(f"{API}/shifts/{sid}", headers=W2).status_code == 404
        r = requests.post(f"{API}/shifts/{sid}/clock-in", headers=EMP, json={})
        assert r.status_code == 400 and "Accept" in r.json()["detail"]
        assert requests.post(f"{API}/shifts/{sid}/accept", headers=EMP).json()["status"] == "accepted"
        assert requests.post(f"{API}/shifts/{sid}/accept", headers=EMP).status_code == 400
        assert requests.delete(f"{API}/shifts/{sid}", headers=ADMIN).status_code == 200

    def test_clock_outside_window_and_approval(self):
        a = S["alpha"]; st = now() + timedelta(minutes=11); en = st + timedelta(minutes=60)
        assert requests.post(f"{API}/support-team/tags", headers=ADMIN, json={"user_id": W2_ID, "participant_id": a["participant_id"]}).json()["status"] == "approved"
        r = mk_shift(a["funding_id"], a["participant_id"], dmy(st), st.strftime("%H:%M"), en.strftime("%H:%M"), worker=W2_ID)
        assert r.status_code == 200, r.text
        sid = r.json()["shift_id"]; S["approved_shift"] = sid
        requests.post(f"{API}/shifts/{sid}/accept", headers=W2)
        r = requests.post(f"{API}/shifts/{sid}/clock-in", headers=W2, json={})
        assert r.status_code == 422 and r.json()["detail"] == "outside_window"
        r = requests.post(f"{API}/shifts/{sid}/clock-in", headers=W2, json={"reason": "Unavoidable delay", "detail": ""})
        assert r.status_code == 400
        r = requests.post(f"{API}/shifts/{sid}/clock-in", headers=W2, json={"reason": "Unavoidable delay", "detail": "Car broke down"})
        assert r.status_code == 200 and r.json()["clock_in"]["outside_window"] is True
        r = requests.post(f"{API}/shifts/{sid}/clock-out", headers=W2, json={})
        assert r.status_code == 422
        r = requests.post(f"{API}/shifts/{sid}/clock-out", headers=W2, json={"reason": "Prior shift ran over"})
        assert r.status_code == 200 and r.json()["status"] == "awaiting_approval"
        aw = requests.get(f"{API}/shifts", headers=ADMIN, params={"status": "awaiting_approval"}).json()
        assert any(s["shift_id"] == sid for s in aw)
        assert requests.post(f"{API}/shifts/{sid}/approve", headers=EMP, json={"start": "10:00", "end": "11:00"}).status_code == 403
        assert requests.post(f"{API}/shifts/{sid}/approve", headers=ADMIN, json={"start": "1000", "end": "11:00"}).status_code == 400
        appr_start = st.strftime("%H:%M"); appr_end = (st + timedelta(minutes=90)).strftime("%H:%M")
        r = requests.post(f"{API}/shifts/{sid}/approve", headers=ADMIN, json={"start": appr_start, "end": appr_end, "comment": "TEST ok"})
        assert r.status_code == 200, r.text
        d = r.json()
        assert d["status"] == "completed" and d["approved_minutes"] == 90 and d["unbudgeted_minutes"] == 30 and d["cost"] == 75
        f = requests.get(f"{API}/funding/{a['funding_id']}", headers=ADMIN).json()
        assert f["spent"] == 75 and f["remaining"] == 4925 and f["units_left"] == 98.5
        assert requests.delete(f"{API}/shifts/{sid}", headers=ADMIN).status_code == 400

    def test_clock_inside_window_completes(self):
        a = S["alpha"]; st = now() + timedelta(minutes=12); en = st + timedelta(minutes=60)
        r = mk_shift(a["funding_id"], a["participant_id"], dmy(st), st.strftime("%H:%M"), en.strftime("%H:%M"), worker=W2_ID)
        assert r.status_code == 200, r.text
        sid = r.json()["shift_id"]
        requests.post(f"{API}/shifts/{sid}/accept", headers=W2)
        n = now()
        mdb.shifts.update_one({"shift_id": sid}, {"$set": {"start": n.strftime("%H:%M"), "end": (n + timedelta(minutes=60)).strftime("%H:%M"), "date": n.date().isoformat()}})
        r = requests.post(f"{API}/shifts/{sid}/clock-in", headers=W2, json={})
        assert r.status_code == 200 and r.json()["clock_in"]["outside_window"] is False
        mdb.shifts.update_one({"shift_id": sid}, {"$set": {"start": (now() - timedelta(minutes=60)).strftime("%H:%M"), "end": now().strftime("%H:%M")}})
        r = requests.post(f"{API}/shifts/{sid}/clock-out", headers=W2, json={})
        assert r.status_code == 200 and r.json()["status"] == "completed"

    def test_rate_change_modes(self):
        fid = S["alpha"]["funding_id"]
        f0 = requests.get(f"{API}/funding/{fid}", headers=ADMIN).json()
        assert requests.put(f"{API}/funding/{fid}/rate", headers=EMP, json={"unit_rate": 60, "mode": "keep_budget"}).status_code == 403
        assert requests.put(f"{API}/funding/{fid}/rate", headers=ADMIN, json={"unit_rate": 60, "mode": "x"}).status_code == 400
        f1 = requests.put(f"{API}/funding/{fid}/rate", headers=ADMIN, json={"unit_rate": 60, "mode": "keep_budget"}).json()
        assert f1["budget"] == f0["budget"] and f1["unit_rate"] == 60
        assert abs(f1["units"] - round(f0["units_used"] + f0["remaining"] / 60, 2)) < 0.011
        assert abs(f1["units_left"] - round(f0["remaining"] / 60, 2)) < 0.011
        f2 = requests.put(f"{API}/funding/{fid}/rate", headers=ADMIN, json={"unit_rate": 70, "mode": "increase_budget"}).json()
        assert f2["units"] == f1["units"] and abs(f2["units_left"] - f1["units_left"]) < 0.011
        assert abs(f2["budget"] - round(f1["spent"] + f1["units_left"] * 70, 2)) < 0.011 and f2["budget"] > f1["budget"]
        assert len(f2["rate_history"]) == 2

    def test_delete_blocked_with_active_shifts(self):
        r = requests.delete(f"{API}/funding/{S['alpha']['funding_id']}", headers=ADMIN)
        assert r.status_code == 400 and "Shifts" in r.json()["detail"]


# ---- Exceptions report ----
class TestReport:
    def test_report_xlsx(self):
        t = now().date()
        r = requests.get(f"{API}/roster/report", params={"date_from": dmy(t - timedelta(days=1)), "date_to": dmy(t), "token": "test_session_admin"})
        assert r.status_code == 200
        wb = load_workbook(io.BytesIO(r.content))
        assert wb.sheetnames == ["Summary", "Incidents"]
        summ = {row[0]: row[1] for row in wb["Summary"].iter_rows(values_only=True) if row and row[0]}
        assert summ["Clock in/out incidents needing approval"] >= 1 and summ["Unbudgeted time (minutes)"] >= 30
        inc = list(wb["Incidents"].iter_rows(values_only=True))
        assert any(row[9] == "Prior shift ran over" and "Car broke down" in (row[10] or "") for row in inc[1:])

    def test_report_limits(self):
        t = now().date()
        r = requests.get(f"{API}/roster/report", headers=ADMIN, params={"date_from": dmy(t - timedelta(days=90)), "date_to": dmy(t)})
        assert r.status_code == 400
        r = requests.get(f"{API}/roster/report", headers=ADMIN, params={"date_from": dmy(t - timedelta(days=89)), "date_to": dmy(t)})
        assert r.status_code == 200
        assert requests.get(f"{API}/roster/report", headers=EMP, params={"date_from": dmy(t), "date_to": dmy(t)}).status_code == 403
