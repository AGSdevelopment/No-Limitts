# Iter63: shift address/directions data, overdue invoices (API + digest), email invoice to payer + shared link
# Requires: python ui_seed_iter63.py seed (run first), clean afterwards. Run with -n 0.
import asyncio
import os
import sys

import pytest
import requests


def _env(path, key):
    for line in open(path):
        if line.startswith(key + "="):
            return line.split("=", 1)[1].strip().strip('"')


BASE_URL = (os.environ.get("EXPO_BACKEND_URL") or _env("/app/frontend/.env", "EXPO_PUBLIC_BACKEND_URL")).rstrip("/")
ADMIN = {"Authorization": "Bearer test_session_admin"}
EMP = {"Authorization": "Bearer test_session_employee"}
LOOP = asyncio.new_event_loop()  # motor client binds to one loop


def get(path, h=ADMIN, **kw):
    return requests.get(f"{BASE_URL}/api{path}", headers=h, timeout=60, **kw)


def post(path, h=ADMIN, **kw):
    return requests.post(f"{BASE_URL}/api{path}", headers=h, timeout=60, **kw)


# ---- Shift address ----
class TestShiftAddress:
    def test_list_includes_address_for_employee(self):
        r = get("/shifts", EMP)
        assert r.status_code == 200
        by = {s["shift_id"]: s for s in r.json()}
        assert by["shf_ui63a"]["address"] == "1 Hay Street, Perth WA 6000"
        assert by["shf_ui63b"]["address"] == ""
        assert all("address" in s for s in r.json())

    def test_list_includes_address_for_admin(self):
        r = get("/shifts", params={"participant_id": "par_ui63"})
        assert r.status_code == 200
        assert {s["address"] for s in r.json()} == {"1 Hay Street, Perth WA 6000"}

    def test_detail_address(self):
        assert get("/shifts/shf_ui63a", EMP).json()["address"] == "1 Hay Street, Perth WA 6000"
        assert get("/shifts/shf_ui63b", EMP).json()["address"] == ""

    def test_latlng_hidden_from_employee(self):
        r = get("/shifts", EMP, params={"status": "awaiting_approval"})
        s = next(x for x in r.json() if x["shift_id"] == "shf_ui63c")
        loc = s["clock_in"]["location"]
        assert "lat" not in loc and "lng" not in loc and loc["checked"] is True
        d = get("/shifts/shf_ui63c", EMP).json()["clock_in"]["location"]
        assert "lat" not in d and "lng" not in d

    def test_latlng_visible_to_admin(self):
        loc = get("/shifts/shf_ui63c").json()["clock_in"]["location"]
        assert loc["lat"] == -31.95 and loc["lng"] == 115.86


# ---- Overdue invoices ----
class TestOverdue:
    def test_employee_forbidden(self):
        assert get("/invoices/overdue", EMP).status_code == 403

    def test_overdue_grouping(self):
        r = get("/invoices/overdue")
        assert r.status_code == 200
        o = r.json()
        groups = {g["payer"]: g for g in o["payers"]}
        a, b = groups["TEST_63 Plan Co"], groups["TEST_63 Solo Payer"]
        assert a["total"] == 450.0 and a["count"] == 2 and a["email"] == "delivered@resend.dev"
        assert b["total"] == 200.0 and b["count"] == 1
        nums = {x["number"] for g in o["payers"] for x in g["invoices"]}
        assert {"TEST63-001", "TEST63-002", "TEST63-003"} <= nums
        assert not nums & {"TEST63-004", "TEST63-005", "TEST63-006", "TEST63-007", "TEST63-008"}
        x = next(x for x in a["invoices"] if x["number"] == "TEST63-001")
        assert x["days_overdue"] == 10 and x["participant_name"] == "TEST_UI63 Participant" and x["total"] == 300.0
        totals = [g["total"] for g in o["payers"]]
        assert totals == sorted(totals, reverse=True)
        assert o["count"] >= 3 and o["total"] >= 650.0

    def test_list_overdue_flag(self):
        r = get("/invoices")
        by = {i["invoice_id"]: i for i in r.json()}
        assert by["inv_ui63_a1"]["overdue"] is True
        assert by["inv_ui63_b1"]["overdue"] is True
        for k in ("inv_ui63_paid", "inv_ui63_void", "inv_ui63_future", "inv_ui63_today"):
            assert by[k]["overdue"] is False, k
        assert "email_history" not in by["inv_ui63_a1"]

    def test_digest_function(self):
        sys.path.insert(0, "/app/backend")
        import routes.pm_invoices as m
        sent, notes = [], []

        async def fake_email(**kw):
            sent.append(kw)
            return True

        async def fake_notify(*a):
            notes.append(a)

        m.send_email, m.notify = fake_email, fake_notify  # avoid emailing real Finance users with TEST data
        LOOP.run_until_complete(m.send_overdue_digest())
        assert len(notes) == 1
        ids, ntype, title, body, link = notes[0]
        assert ntype == "invoice" and link == "/pm/invoices"
        assert "overdue invoice" in title and "TEST_63 Plan Co $450.00" in body
        assert "user_testadmin01" not in ids  # hidden users skipped
        assert len(sent) == len(ids) and all("Overdue invoices" in s["subject"] for s in sent)
        assert "TEST63-001" in sent[0]["html"]


# ---- Email to payer ----
class TestEmail:
    def test_employee_forbidden(self):
        assert post("/invoices/inv_ui63_a1/email", EMP).status_code == 403

    def test_not_found(self):
        assert post("/invoices/inv_nope_63/email").status_code == 404

    def test_void_rejected(self):
        r = post("/invoices/inv_ui63_void/email")
        assert r.status_code == 400 and "void" in r.json()["detail"]

    def test_no_email_rejected(self):
        r = post("/invoices/inv_ui63_noemail/email")
        assert r.status_code == 400 and "email" in r.json()["detail"]

    def test_send_and_shared_link(self):
        r = post("/invoices/inv_ui63_a1/email")
        print("email status", r.status_code, r.text[:300])
        assert r.status_code in (200, 502)
        sys.path.insert(0, "/app/backend")
        from core import db

        async def look():
            return (await db.invoice_links.find_one({"invoice_id": "inv_ui63_a1"}, {"_id": 0}, sort=[("created_at", -1)]),
                    await db.invoices.find_one({"invoice_id": "inv_ui63_a1"}, {"_id": 0}))
        link, inv = LOOP.run_until_complete(look())
        assert link and link["expires_at"] > link["created_at"]
        p = requests.get(f"{BASE_URL}/api/invoices/shared/{link['token']}", timeout=60)
        assert p.status_code == 200 and p.content[:4] == b"%PDF"
        if r.status_code == 200:
            e = r.json()["emailed"]
            assert e["to"] == "delivered@resend.dev" and e["at"] and e["by"]
            assert inv["emailed"]["to"] == "delivered@resend.dev" and len(inv["email_history"]) >= 1
            lst = {i["invoice_id"]: i for i in get("/invoices").json()}
            assert lst["inv_ui63_a1"]["emailed"]["to"] == "delivered@resend.dev"
        else:
            pytest.fail("Email service returned 502 in this environment")

    def test_bad_token_404(self):
        assert requests.get(f"{BASE_URL}/api/invoices/shared/nonsense-token-63", timeout=30).status_code == 404

    def test_expired_token_404(self):
        sys.path.insert(0, "/app/backend")
        from core import db

        async def ins():
            await db.invoice_links.insert_one({"token": "tok_ui63_expired", "invoice_id": "inv_ui63_a1",
                                               "created_at": "2020-01-01T00:00:00+00:00", "expires_at": "2020-03-01T00:00:00+00:00"})
        LOOP.run_until_complete(ins())
        assert requests.get(f"{BASE_URL}/api/invoices/shared/tok_ui63_expired", timeout=30).status_code == 404


# ---- Regression smoke ----
class TestSmoke:
    def test_invoice_pdf(self):
        r = get("/invoices/inv_ui63_a1/pdf")
        assert r.status_code == 200 and r.content[:4] == b"%PDF"

    def test_settings(self):
        assert get("/invoices/settings").status_code == 200
