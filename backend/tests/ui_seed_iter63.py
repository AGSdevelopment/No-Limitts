# Seed for iter63 (shift directions/address, overdue invoices, email to payer). Usage: python ui_seed_iter63.py seed|clean
import asyncio
import sys
from datetime import datetime, timedelta

sys.path.insert(0, "/app/backend")
from core import DIGEST_TZ, db  # noqa: E402

PID, PID2 = "par_ui63", "par_ui63b"
FID, FID2 = "fund_ui63", "fund_ui63b"
PNAME, PNAME2 = "TEST_UI63 Participant", "TEST_UI63 NoAddr"
PAYER_A = {"name": "TEST Payer A", "company": "TEST_63 Plan Co", "email": "delivered@resend.dev"}
PAYER_B = {"name": "TEST_63 Solo Payer", "company": "", "email": "solo63@example.com"}
PAYER_NOEMAIL = {"name": "TEST_63 NoEmail", "company": "", "email": ""}
SELLER = {"business_name": "No Limitts Pty Ltd", "abn": "92 606 960 730", "address": "", "email": "", "phone": "",
          "account_name": "", "bsb": "", "account_number": "", "payment_terms_days": 14}


def sh(sid, date, status, pid=PID, pname=PNAME, start="09:00", end="11:00", **kw):
    return {"shift_id": sid, "date": date, "start": start, "end": end, "participant_id": pid, "participant_name": pname,
            "funding_id": FID if pid == PID else FID2, "funding_type": "NDIA", "unit_rate": 50.0, "worker_id": "user_testemp001",
            "worker_name": "Emp Test", "minutes": 120, "est_units": 2.0, "hourly": True, "est_cost": 100.0, "notes": "",
            "status": status, "auto_accepted": True, "created_by": "TEST", "created_at": datetime.now(DIGEST_TZ).isoformat(), **kw}


def inv(iid, num, payer, status, due, total, fid=FID, pname=PNAME):
    line = {"shift_id": "shf_x", "date": due, "description": "NDIA support 09:00-11:00 · Emp Test", "units": 2, "unit_type": "hours",
            "rate": 50.0, "amount": total}
    return {"invoice_id": iid, "number": num, "funding_id": fid, "participant_id": PID, "participant_name": pname,
            "management_type": "NDIA", "payer": payer, "period_from": due, "period_to": due, "issue_date": due, "due_date": due,
            "lines": [line], "total": total, "status": status, "seller": SELLER, "created_by": "TEST",
            "created_at": datetime.now(DIGEST_TZ).isoformat()}


async def seed():
    now = datetime.now(DIGEST_TZ)
    t = now.date()
    d = lambda n: (t + timedelta(days=n)).isoformat()  # noqa: E731
    # Block the real 8am digest today so real Finance users aren't emailed TEST data while testing
    key = f"overdue_invoices_{t.isoformat()}"
    if not await db.meta.find_one({"key": key}):
        await db.meta.insert_one({"key": key, "created_at": now.isoformat(), "test_guard": "iter63"})
    await db.participants.insert_many([
        {"participant_id": PID, "name": PNAME, "key": PNAME.casefold(), "assigned_ids": ["user_testemp001"], "profile": {},
         "address": "1 Hay Street, Perth WA 6000", "geo": {"lat": -31.9505, "lng": 115.8605}},
        {"participant_id": PID2, "name": PNAME2, "key": PNAME2.casefold(), "assigned_ids": ["user_testemp001"], "profile": {}}])
    base_f = {"participant_email": "", "management_type": "NDIA", "units": 500.0, "unit_type": "Hour", "unit_rate": 50.0,
              "budget": 25000.0, "start_date": d(-60), "end_date": d(90), "rate_history": [], "created_by": "TEST", "created_at": now.isoformat()}
    await db.fundings.insert_many([{**base_f, "funding_id": FID, "participant_id": PID, "participant_name": PNAME, "payer": PAYER_A},
                                   {**base_f, "funding_id": FID2, "participant_id": PID2, "participant_name": PNAME2, "payer": PAYER_NOEMAIL}])
    loc = {"checked": True, "flagged": False, "lat": -31.95, "lng": 115.86, "distance_m": 20, "note": ""}
    await db.shifts.insert_many([
        sh("shf_ui63a", d(1), "accepted"),
        sh("shf_ui63b", d(1), "accepted", pid=PID2, pname=PNAME2, start="13:00", end="14:00"),
        sh("shf_ui63c", d(-1), "awaiting_approval", start="15:00", end="16:00",
           clock_in={"at": "", "time": "15:00", "outside_window": False, "location": loc},
           clock_out={"at": "", "time": "16:00", "outside_window": False}),
        sh("shf_ui63d", d(2), "cancelled", start="10:00", end="11:00"),
    ])
    await db.invoices.insert_many([
        inv("inv_ui63_a1", "TEST63-001", PAYER_A, "unpaid", d(-10), 300.0),
        inv("inv_ui63_a2", "TEST63-002", PAYER_A, "unpaid", d(-3), 150.0),
        inv("inv_ui63_b1", "TEST63-003", PAYER_B, "unpaid", d(-5), 200.0),
        inv("inv_ui63_paid", "TEST63-004", PAYER_A, "paid", d(-20), 999.0),
        inv("inv_ui63_void", "TEST63-005", PAYER_A, "void", d(-20), 888.0),
        inv("inv_ui63_future", "TEST63-006", PAYER_A, "unpaid", d(5), 77.0),
        inv("inv_ui63_today", "TEST63-007", PAYER_A, "unpaid", d(0), 66.0),
        inv("inv_ui63_noemail", "TEST63-008", PAYER_NOEMAIL, "unpaid", d(3), 55.0, fid=FID2, pname=PNAME2),
    ])
    print("seeded", t.isoformat())


async def clean():
    ids = [i["invoice_id"] async for i in db.invoices.find({"invoice_id": {"$regex": "^inv_ui63_"}}, {"_id": 0, "invoice_id": 1})]
    print("invoices", ids)
    print("links", (await db.invoice_links.delete_many({"invoice_id": {"$in": ids}})).deleted_count)
    await db.invoices.delete_many({"invoice_id": {"$in": ids}})
    await db.shifts.delete_many({"shift_id": {"$in": ["shf_ui63a", "shf_ui63b", "shf_ui63c", "shf_ui63d"]}})
    await db.fundings.delete_many({"funding_id": {"$in": [FID, FID2]}})
    await db.participants.delete_many({"participant_id": {"$in": [PID, PID2]}})
    await db.meta.delete_many({"test_guard": "iter63"})


asyncio.run(seed() if sys.argv[1:] == ["seed"] else clean())
