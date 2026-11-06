# Iteration 62: Timesheets (hours only) + xlsx export, participant invoices (Finance, GST-free PDF, numbering, void releases),
# participant addresses + clock-in location check (warn & flag), roster report Location check column.
import asyncio
import io
import os
import re
import secrets
import sys
from datetime import datetime, timedelta, timezone

import pytest
import requests
from dotenv import load_dotenv

load_dotenv("/app/backend/.env")
load_dotenv("/app/frontend/.env")
sys.path.insert(0, "/app/backend")
BASE_URL = (os.environ.get("EXPO_BACKEND_URL") or os.environ.get("EXPO_PUBLIC_BACKEND_URL")).rstrip("/")
API = f"{BASE_URL}/api"

loop = asyncio.new_event_loop()
asyncio.set_event_loop(loop)
from core import db  # noqa: E402


def run(c):
    return loop.run_until_complete(c)


ADMIN = {"Authorization": "Bearer test_session_admin"}
EMP_ID = "user_testemp001"
EMP = {"Authorization": "Bearer test_session_employee"}
TAG = secrets.token_hex(3)
W2_ID = f"user_t62w2{TAG}"
PNAME, PID, PID2 = f"TEST_Iter62 {TAG}", f"par_t62{TAG}", f"par_t62b{TAG}"
FA, FB = f"fund_t62a{TAG}", f"fund_t62b{TAG}"
PERTH = timezone(timedelta(hours=8))
now = datetime.now(PERTH)
today = now.date()
# Past period well away from real data: 4 weeks starting on a Monday ~5 weeks ago
MON = today - timedelta(days=today.weekday() + 35)
D = lambda n: (MON + timedelta(days=n)).isoformat()  # noqa: E731
dmy = lambda iso: f"{iso[8:10]}-{iso[5:7]}-{iso[:4]}"  # noqa: E731
GEO = {"lat": -31.9505, "lng": 115.8605}
created_invoices = []
STATE = {}


def shift(sid, date, worker, wname, fund, status, mins=120, cost=100.0, **kw):
    return {"shift_id": sid, "date": date, "start": "09:00", "end": "11:00", "participant_id": PID, "participant_name": PNAME,
            "funding_id": fund, "funding_type": "NDIA", "unit_rate": 50.0, "worker_id": worker, "worker_name": wname, "minutes": 120,
            "est_units": 2.0, "hourly": True, "est_cost": 100.0, "notes": "", "status": status, "auto_accepted": True,
            "created_by": "TEST", "created_at": now.isoformat(),
            **({"approved_minutes": mins, "units": mins / 60, "cost": cost,
                "clock_in": {"at": "", "time": "09:00", "outside_window": False},
                "clock_out": {"at": "", "time": "11:00", "outside_window": False}} if status == "completed" else {}), **kw}


@pytest.fixture(scope="module", autouse=True)
def seed():
    STATE["seq"] = run(db.meta.find_one({"key": "invoice_seq"}, {"_id": 0}))
    STATE["settings"] = run(db.meta.find_one({"key": "invoice_settings"}, {"_id": 0}))
    emp = run(db.users.find_one({"user_id": EMP_ID}, {"_id": 0, "name": 1}))
    STATE["emp_name"] = emp["name"]
    run(db.users.insert_one({"user_id": W2_ID, "name": f"TEST_Iter62 Worker Two {TAG}", "email": f"t62w2{TAG}@example.com",
                             "role": "employee", "user_type": "support_worker", "hidden": True, "created_at": now.isoformat()}))
    run(db.participants.insert_many([
        {"participant_id": PID, "name": PNAME, "key": PNAME.casefold(), "assigned_ids": [EMP_ID, W2_ID], "profile": {}},
        {"participant_id": PID2, "name": PNAME + " B", "key": (PNAME + " B").casefold(), "assigned_ids": [EMP_ID], "profile": {}}]))
    for fid, typ in ((FA, "NDIA"), (FB, "Plan Managed")):
        run(db.fundings.insert_one({"funding_id": fid, "participant_id": PID, "participant_name": PNAME, "participant_email": "",
                                    "management_type": typ, "units": 500.0, "unit_type": "Hour", "unit_rate": 50.0, "budget": 25000.0,
                                    "payer": {"name": f"TEST payer {typ}", "email": "payer@example.com", "company": "TEST Co", "abn": "11 111 111 111"},
                                    "start_date": D(-60), "end_date": (today + timedelta(days=90)).isoformat(),
                                    "rate_history": [], "created_by": "TEST", "created_at": now.isoformat()}))
    en = STATE["emp_name"]
    run(db.shifts.insert_many([
        shift(f"shf_t62a{TAG}", D(0), EMP_ID, en, FA, "completed", 120, 100.0),   # wk1 Mon
        shift(f"shf_t62b{TAG}", D(2), EMP_ID, en, FA, "completed", 90, 75.0),     # wk1 Wed
        shift(f"shf_t62c{TAG}", D(3), EMP_ID, en, FA, "awaiting_approval"),       # wk1 pending
        shift(f"shf_t62d{TAG}", D(7), EMP_ID, en, FA, "completed", 60, 50.0),     # wk2 Mon
        shift(f"shf_t62e{TAG}", D(1), W2_ID, f"TEST_Iter62 Worker Two {TAG}", FB, "completed", 180, 150.0)]))
    yield
    run(db.shifts.delete_many({"participant_id": {"$in": [PID, PID2]}}))
    run(db.fundings.delete_many({"funding_id": {"$in": [FA, FB]}}))
    run(db.participants.delete_many({"participant_id": {"$in": [PID, PID2]}}))
    run(db.invoices.delete_many({"funding_id": {"$in": [FA, FB]}}))
    run(db.users.delete_many({"user_id": W2_ID}))
    run(db.notifications.delete_many({"$or": [{"title": {"$regex": re.escape(TAG)}}, {"body": {"$regex": re.escape(TAG)}}]}))
    # restore invoice counter + settings to their pre-test state
    if STATE["seq"] is None:
        run(db.meta.delete_one({"key": "invoice_seq"}))
    else:
        run(db.meta.replace_one({"key": "invoice_seq"}, STATE["seq"]))
    if STATE["settings"] is None:
        run(db.meta.delete_one({"key": "invoice_settings"}))
    else:
        run(db.meta.replace_one({"key": "invoice_settings"}, STATE["settings"]))


RANGE = {"date_from": dmy(D(0)), "date_to": dmy(D(13))}


# ---- Timesheets ----
class TestTimesheets:
    def test_default_current_week(self):
        r = requests.get(f"{API}/timesheets", headers=ADMIN)
        assert r.status_code == 200, r.text
        j = r.json()
        mon = today - timedelta(days=today.weekday())
        assert j["date_from"] == mon.isoformat() and j["date_to"] == (mon + timedelta(days=6)).isoformat()
        assert j["all_staff"] is True

    def test_office_sees_all_with_weeks(self):
        j = requests.get(f"{API}/timesheets", headers=ADMIN, params=RANGE).json()
        by = {w["worker_id"]: w for w in j["workers"]}
        assert EMP_ID in by and W2_ID in by
        e = by[EMP_ID]
        assert e["minutes"] == 270 and e["hours"] == 4.5 and e["shifts"] == 3 and e["pending"] == 1
        assert [(w["week_start"], w["minutes"], w["pending"]) for w in e["weeks"]] == [(D(0), 210, 1), (D(7), 60, 0)]
        assert by[W2_ID]["hours"] == 3.0
        assert "cost" not in str(j) and "rate" not in str(j)

    def test_worker_sees_only_own(self):
        j = requests.get(f"{API}/timesheets", headers=EMP, params={**RANGE, "worker_id": W2_ID}).json()
        assert j["all_staff"] is False
        assert [w["worker_id"] for w in j["workers"]] == [EMP_ID]

    def test_range_validation(self):
        assert requests.get(f"{API}/timesheets", headers=ADMIN, params={"date_from": "01-01-2026", "date_to": "30-06-2026"}).status_code == 400
        assert requests.get(f"{API}/timesheets", headers=ADMIN, params={"date_from": "bad", "date_to": "01-01-2026"}).status_code == 400

    def test_export_xlsx(self):
        from openpyxl import load_workbook
        r = requests.get(f"{API}/timesheets/export", params={**RANGE, "token": "test_session_admin"})
        assert r.status_code == 200, r.text
        wb = load_workbook(io.BytesIO(r.content))
        assert wb.sheetnames == ["Weekly hours", "Shifts"]
        rows = [c for c in wb["Shifts"].iter_rows(values_only=True)]
        assert any(PNAME in str(x) for x in rows)
        assert requests.get(f"{API}/timesheets/export", params={**RANGE, "token": "test_session_employee"}).status_code == 403


# ---- Invoices ----
class TestInvoices:
    def test_employee_forbidden(self):
        for m, path in (("get", "/invoices/settings"), ("get", "/invoices"), ("get", "/invoices/uninvoiced?date_from=01-01-2026&date_to=02-01-2026")):
            assert getattr(requests, m)(f"{API}{path}", headers=EMP).status_code == 403
        assert requests.post(f"{API}/invoices/generate", headers=EMP, json=RANGE).status_code == 403

    def test_settings_defaults_and_save(self):
        if STATE["settings"] is None:
            j = requests.get(f"{API}/invoices/settings", headers=ADMIN).json()
            assert j["business_name"] == "No Limitts Pty Ltd" and j["abn"] == "92 606 960 730" and j["payment_terms_days"] == 14
        r = requests.put(f"{API}/invoices/settings", headers=ADMIN, json={"business_name": "No Limitts Pty Ltd", "abn": "92 606 960 730",
                                                                          "bsb": "123-456", "account_number": "TEST123", "payment_terms_days": 7})
        assert r.status_code == 200 and r.json()["bsb"] == "123-456"
        assert requests.get(f"{API}/invoices/settings", headers=ADMIN).json()["payment_terms_days"] == 7
        assert requests.put(f"{API}/invoices/settings", headers=ADMIN, json={"business_name": "x"}).status_code == 400
        assert requests.put(f"{API}/invoices/settings", headers=ADMIN, json={"business_name": "No Limitts", "payment_terms_days": 500}).status_code == 400

    def test_uninvoiced(self):
        j = requests.get(f"{API}/invoices/uninvoiced", headers=ADMIN, params=RANGE).json()
        assert j == {"shifts": 4, "total": 375.0, "invoices": 2, "pending": 1}

    def test_generate_future_rejected(self):
        r = requests.post(f"{API}/invoices/generate", headers=ADMIN, json={"date_from": RANGE["date_from"],
                                                                           "date_to": dmy((today + timedelta(days=1)).isoformat())})
        assert r.status_code == 400

    def test_generate_and_no_double(self):
        r = requests.post(f"{API}/invoices/generate", headers=ADMIN, json=RANGE)
        assert r.status_code == 200, r.text
        j = r.json()
        assert j["count"] == 2
        nums = sorted(int(c["number"][3:]) for c in j["created"])
        assert all(c["number"].startswith("NL-") and len(c["number"]) == 9 for c in j["created"])
        assert nums[1] == nums[0] + 1
        created_invoices.extend(j["created"])
        tot = {c["management_type"]: c["total"] for c in j["created"]}
        assert tot == {"NDIA": 225.0, "Plan Managed": 150.0}
        assert run(db.shifts.count_documents({"participant_id": PID, "invoice_id": {"$nin": [None, ""]}})) == 4
        assert run(db.shifts.find_one({"shift_id": f"shf_t62c{TAG}"}, {"_id": 0})).get("invoice_id") is None
        assert requests.post(f"{API}/invoices/generate", headers=ADMIN, json=RANGE).json()["count"] == 0
        inv = run(db.invoices.find_one({"invoice_id": j["created"][0]["invoice_id"]}, {"_id": 0}))
        assert (datetime.fromisoformat(inv["due_date"]) - datetime.fromisoformat(inv["issue_date"])).days == 7

    def test_list_and_pdf(self):
        ids = {c["invoice_id"] for c in created_invoices}
        lst = requests.get(f"{API}/invoices", headers=ADMIN, params={"status": "unpaid"}).json()
        assert ids <= {i["invoice_id"] for i in lst}
        assert all("lines" not in i for i in lst)
        iid = created_invoices[0]["invoice_id"]
        r = requests.get(f"{API}/invoices/{iid}/pdf", params={"token": "test_session_admin"})
        assert r.status_code == 200 and r.headers["content-type"].startswith("application/pdf")
        import pymupdf
        text = "".join(p.get_text() for p in pymupdf.open(stream=r.content, filetype="pdf"))
        assert "No Limitts Pty Ltd" in text and "92 606 960 730" in text and "$0.00" in text and "GST" in text
        assert requests.get(f"{API}/invoices/{iid}/pdf", params={"token": "test_session_employee"}).status_code == 403
        assert requests.get(f"{API}/invoices/inv_nope/pdf", params={"token": "test_session_admin"}).status_code == 404

    def test_status_paid_void_release(self):
        a = next(c for c in created_invoices if c["management_type"] == "NDIA")["invoice_id"]
        r = requests.post(f"{API}/invoices/{a}/status", headers=ADMIN, json={"status": "paid"})
        assert r.status_code == 200 and r.json()["status"] == "paid" and r.json().get("paid_date")
        assert requests.post(f"{API}/invoices/{a}/status", headers=ADMIN, json={"status": "bogus"}).status_code == 400
        assert requests.post(f"{API}/invoices/{a}/status", headers=EMP, json={"status": "void"}).status_code == 403
        r = requests.post(f"{API}/invoices/{a}/status", headers=ADMIN, json={"status": "void"})
        assert r.status_code == 200 and r.json()["status"] == "void"
        assert run(db.shifts.count_documents({"funding_id": FA, "invoice_id": a})) == 0
        assert requests.post(f"{API}/invoices/{a}/status", headers=ADMIN, json={"status": "unpaid"}).status_code == 400
        assert a in {i["invoice_id"] for i in requests.get(f"{API}/invoices", headers=ADMIN, params={"status": "void"}).json()}
        j = requests.post(f"{API}/invoices/generate", headers=ADMIN, json=RANGE).json()
        assert j["count"] == 1 and j["created"][0]["total"] == 225.0
        created_invoices.extend(j["created"])


# ---- Addresses + location check ----
class TestLocation:
    def test_address_permissions_and_save(self):
        assert requests.get(f"{API}/pm/addresses", headers=EMP).status_code == 403
        assert requests.put(f"{API}/participants/{PID}/address", headers=EMP, json={"address": "x"}).status_code == 403
        assert requests.put(f"{API}/participants/par_nope/address", headers=ADMIN, json={"address": "x"}).status_code == 404
        r = requests.put(f"{API}/participants/{PID}/address", headers=ADMIN, json={"address": "  1 Hay   Street, Perth WA 6000 "}, timeout=60)
        assert r.status_code == 200, r.text
        assert r.json()["address"] == "1 Hay Street, Perth WA 6000"
        print("geocode found:", r.json()["found"])
        row = next(p for p in requests.get(f"{API}/pm/addresses", headers=ADMIN).json() if p["participant_id"] == PID)
        assert row["address"] == "1 Hay Street, Perth WA 6000" and row["found"] == r.json()["found"]
        run(db.participants.update_one({"participant_id": PID}, {"$set": {"geo": GEO}}))  # deterministic geo for clock-in tests

    def _live(self, n, pid=PID):
        st = datetime.now(PERTH)
        sid = f"shf_t62L{n}{TAG}"
        s = shift(sid, st.date().isoformat(), EMP_ID, STATE["emp_name"], FA, "accepted",
                  start=st.strftime("%H:%M"), end=(st + timedelta(minutes=2)).strftime("%H:%M"), participant_id=pid)
        run(db.shifts.insert_one(s))
        return sid

    def test_clock_in_no_coords_flagged_then_clockout_awaiting(self):
        sid = self._live(1)
        r = requests.post(f"{API}/shifts/{sid}/clock-in", headers=EMP, json={})
        assert r.status_code == 200, r.text
        loc = r.json()["clock_in"]["location"]
        assert loc["checked"] is True and loc["flagged"] is True and "wasn't shared" in loc["note"]
        r = requests.post(f"{API}/shifts/{sid}/clock-out", headers=EMP, json={}, timeout=60)
        if r.status_code == 409:
            pytest.skip("case note gate active (Jotform); can't verify clock-out status")
        assert r.status_code == 200, r.text
        assert r.json()["status"] == "awaiting_approval"

    def test_clock_in_far_flagged(self):
        sid = self._live(2)
        r = requests.post(f"{API}/shifts/{sid}/clock-in", headers=EMP, json={"lat": GEO["lat"] + 0.018, "lng": GEO["lng"], "accuracy": 50})
        loc = r.json()["clock_in"]["location"]
        assert loc["flagged"] is True and 1900 < loc["distance_m"] < 2100 and "km from 1 Hay Street" in loc["note"]

    def test_clock_in_near_and_accuracy_not_flagged(self):
        sid = self._live(3)
        # ~400 m away but accuracy 150 -> 250 effective, within 300 m
        r = requests.post(f"{API}/shifts/{sid}/clock-in", headers=EMP, json={"lat": GEO["lat"] + 0.0036, "lng": GEO["lng"], "accuracy": 150})
        loc = r.json()["clock_in"]["location"]
        assert loc["checked"] is True and loc["flagged"] is False and loc["note"] == ""
        r = requests.post(f"{API}/shifts/{sid}/clock-out", headers=EMP, json={}, timeout=60)
        if r.status_code != 409:
            assert r.json()["status"] == "completed"

    def test_accuracy_capped_200(self):
        sid = self._live(4)
        # ~600 m with accuracy 1000 (capped at 200) -> 400 > 300 flagged
        r = requests.post(f"{API}/shifts/{sid}/clock-in", headers=EMP, json={"lat": GEO["lat"] + 0.0054, "lng": GEO["lng"], "accuracy": 1000})
        loc = r.json()["clock_in"]["location"]
        assert loc["accuracy_m"] == 200 and loc["flagged"] is True

    def test_participant_without_geo_unchecked(self):
        sid = self._live(5, pid=PID2)
        r = requests.post(f"{API}/shifts/{sid}/clock-in", headers=EMP, json={})
        assert r.status_code == 200 and r.json()["clock_in"]["location"] == {"checked": False}

    def test_roster_report_location_column(self):
        from openpyxl import load_workbook
        r = requests.get(f"{API}/roster/report", params={"date_from": dmy(today.isoformat()), "date_to": dmy(today.isoformat()),
                                                         "token": "test_session_admin"})
        assert r.status_code == 200, r.text
        ws = load_workbook(io.BytesIO(r.content))["Incidents"]
        rows = list(ws.iter_rows(values_only=True))
        assert rows[0][-1] == "Location check"
        if run(db.shifts.find_one({"shift_id": f"shf_t62L1{TAG}"}, {"_id": 0, "status": 1}))["status"] == "awaiting_approval":
            assert any(PNAME == r[2] and "wasn't shared" in str(r[-1]) for r in rows[1:])
