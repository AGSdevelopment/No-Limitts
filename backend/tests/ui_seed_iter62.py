# UI seed for iter62 (timesheets / invoices / clock-in location / approve-location). Usage: python ui_seed_iter62.py seed|clean
import asyncio
import sys
from datetime import datetime, timedelta

sys.path.insert(0, "/app/backend")
from core import DIGEST_TZ, db  # noqa: E402

PID, FID = "par_ui62", "fund_ui62"
PNAME = "TEST_UI62 Participant"


def sh(sid, date, status, start="09:00", end="11:00", **kw):
    return {"shift_id": sid, "date": date, "start": start, "end": end, "participant_id": PID, "participant_name": PNAME,
            "funding_id": FID, "funding_type": "NDIA", "unit_rate": 50.0, "worker_id": "user_testemp001", "worker_name": "Emp Test",
            "minutes": 120, "est_units": 2.0, "hourly": True, "est_cost": 100.0, "notes": "", "status": status, "auto_accepted": True,
            "created_by": "TEST", "created_at": datetime.now(DIGEST_TZ).isoformat(), **kw}


async def seed():
    now = datetime.now(DIGEST_TZ)
    today = now.date()
    mon = today - timedelta(days=today.weekday() + 35)
    await db.participants.insert_one({"participant_id": PID, "name": PNAME, "key": PNAME.casefold(), "assigned_ids": ["user_testemp001"],
                                      "profile": {}, "address": "1 Hay Street, Perth WA 6000", "geo": {"lat": -31.9505, "lng": 115.8605}})
    await db.fundings.insert_one({"funding_id": FID, "participant_id": PID, "participant_name": PNAME, "participant_email": "",
                                  "management_type": "NDIA", "units": 500.0, "unit_type": "Hour", "unit_rate": 50.0, "budget": 25000.0,
                                  "payer": {"name": "TEST Payer", "company": "TEST Plan Co", "email": "payer@example.com"},
                                  "start_date": (mon - timedelta(days=30)).isoformat(), "end_date": (today + timedelta(days=90)).isoformat(),
                                  "rate_history": [], "created_by": "TEST", "created_at": now.isoformat()})
    done = {"clock_in": {"at": "", "time": "09:00", "outside_window": False}, "clock_out": {"at": "", "time": "11:00", "outside_window": False}}
    await db.shifts.insert_many([
        sh("shf_ui62a", mon.isoformat(), "completed", approved_minutes=120, units=2.0, cost=100.0, **done),
        sh("shf_ui62b", (mon + timedelta(days=8)).isoformat(), "completed", approved_minutes=90, units=1.5, cost=75.0, **done),
        sh("shf_ui62c", now.date().isoformat(), "accepted", start=now.strftime("%H:%M"), end=(now + timedelta(minutes=90)).strftime("%H:%M")),
        sh("shf_ui62d", (today - timedelta(days=1)).isoformat(), "awaiting_approval",
           clock_in={"at": "", "time": "09:01", "outside_window": False,
                     "location": {"checked": True, "flagged": True, "note": "Location wasn't shared at clock-in"}},
           clock_out={"at": "", "time": "11:00", "outside_window": False}),
    ])
    print("seeded", mon.isoformat())


async def clean():
    ids = [i["invoice_id"] async for i in db.invoices.find({"funding_id": FID}, {"_id": 0, "invoice_id": 1})]
    print("invoices", ids)
    await db.invoices.delete_many({"funding_id": FID})
    await db.shifts.delete_many({"participant_id": PID})
    await db.fundings.delete_many({"funding_id": FID})
    await db.participants.delete_many({"participant_id": PID})
    await db.notifications.delete_many({"body": {"$regex": "TEST_UI62"}})
    await db.notifications.delete_many({"title": {"$regex": "TEST_UI62"}})


asyncio.run(seed() if sys.argv[1:] == ["seed"] else clean())
