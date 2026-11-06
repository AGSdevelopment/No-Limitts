"""Rostering extras: declining shifts, the case note gate at clock-out, and Finance budget alerts."""
import asyncio
from datetime import date, timedelta

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from core import P, current_user, db, dmy, logger, notify, now_iso
from routes import caseload as cl
from routes.participant_mgmt import AUTO_ACCEPT_DAYS
from routes.pm_common import now_perth, span
from routes.pm_funding import funding_usage

router = APIRouter(prefix="/api")

LOW_PCT = 0.20


# ---- Decline (only shifts starting within 14 days, before they start) ----

class DeclineIn(BaseModel):
    reason: str


@router.post("/shifts/{shift_id}/decline")
async def decline_shift(shift_id: str, body: DeclineIn, user=Depends(current_user)):
    s = await db.shifts.find_one({"shift_id": shift_id, "worker_id": user["user_id"]}, P)
    if not s or s["status"] not in ("pending_acceptance", "accepted"):
        raise HTTPException(400, "This shift can't be declined")
    start, _ = span(s)
    if start <= now_perth():
        raise HTTPException(400, "This shift has already started")
    if start > now_perth() + timedelta(days=AUTO_ACCEPT_DAYS):
        raise HTTPException(400, "Shifts more than 14 days away can't be declined in the app. Talk to Rosters.")
    reason = body.reason.strip()
    if len(reason) < 3:
        raise HTTPException(400, "Tell Rosters why you can't do this shift")
    await db.shifts.update_one({"shift_id": shift_id}, {"$set": {"status": "declined", "decline_reason": reason[:300], "declined_at": now_iso()}})
    from routes.shift_market import close_swap
    await close_swap(s, f"{s['worker_name']} declined the shift")
    rosters = [u["user_id"] async for u in db.users.find({"$or": [{"permissions": "rosters"}, {"role": "admin"}], "hidden": {"$ne": True}},
                                                         {"_id": 0, "user_id": 1})]
    await notify(rosters, "shift", f"Shift declined: {s['participant_name']} {dmy(s['date'])} {s['start']}-{s['end']}",
                 f"{s['worker_name']} can't do it: {reason[:200]}. Tap to re-roster.", "/pm/rostering")
    return {"status": "declined"}


# ---- Case note gate ----

async def has_case_note(s: dict, user: dict) -> bool:
    """A Day-to-Day case note by this worker for this participant, dated the shift day or today (fresh from Jotform)."""
    if not cl.configured():
        return True
    cl._cache["rows"] = None
    try:
        rows = await cl.load_rows()
    except Exception as e:
        logger.error(f"Case note check failed, letting clock-out through: {e}")
        return True
    key = cl.participant_key(s["participant_name"])
    days = {s["date"], now_perth().date().isoformat()}
    return any(r["kind"] == "day" and cl.participant_key(r["participant"]) == key and cl.written_by(r, user) and cl.note_day(r) in days
               for r in rows)


# ---- Budget alerts for Finance ----

def projection(f: dict, use: dict) -> dict:
    """Low (<20% left) and running-out-early (spend rate so far would use it up before the end date)."""
    today = now_perth().date()
    start, end = date.fromisoformat(f["start_date"]), date.fromisoformat(f["end_date"])
    remaining = f["budget"] - use["spent"]
    low = f["budget"] > 0 and remaining / f["budget"] < LOW_PCT
    runout = None
    elapsed = (min(today, end) - start).days + 1
    if start <= today <= end and use["spent"] > 0 and elapsed >= 7:
        daily = use["spent"] / elapsed
        left_days = remaining / daily if daily else None
        if left_days is not None and today + timedelta(days=int(left_days)) < end:
            runout = (today + timedelta(days=max(int(left_days), 0))).isoformat()
    return {"low": low, "pct_left": round(remaining / f["budget"] * 100) if f["budget"] else 0, "runout": runout}


async def check_budget(funding_id: str):
    f = await db.fundings.find_one({"funding_id": funding_id}, P)
    if not f:
        return
    pr = projection(f, (await funding_usage([funding_id]))[funding_id])
    sent = set(f.get("alerts_sent") or [])
    cleared = [k for k in ("low", "runout") if k in sent and not pr[k]]
    if cleared:  # e.g. topped up or price change: alert again if it runs low later
        await db.fundings.update_one({"funding_id": funding_id}, {"$pull": {"alerts_sent": {"$in": cleared}}})
        sent -= set(cleared)
    todo = []
    if pr["low"] and "low" not in sent:
        todo.append(("low", f"Low funding: {f['participant_name']} ({f['management_type']})",
                     f"Only {pr['pct_left']}% of the budget is left, with service until {dmy(f['end_date'])}."))
    if pr["runout"] and "runout" not in sent:
        todo.append(("runout", f"Funding running out early: {f['participant_name']} ({f['management_type']})",
                     f"At the current rate it runs out around {dmy(pr['runout'])}, before the end date {dmy(f['end_date'])}."))
    if not todo:
        return
    finance = [u["user_id"] async for u in db.users.find({"$or": [{"permissions": "finance"}, {"role": "admin"}], "hidden": {"$ne": True}},
                                                         {"_id": 0, "user_id": 1})]
    for kind, title, body in todo:
        await notify(finance, "funding", title, body, "/pm/funding")
    await db.fundings.update_one({"funding_id": funding_id}, {"$addToSet": {"alerts_sent": {"$each": [k for k, _, _ in todo]}}})


async def budget_alert_loop():
    await asyncio.sleep(180)
    while True:
        try:
            today = now_perth().date().isoformat()
            async for f in db.fundings.find({"end_date": {"$gte": today}}, {"_id": 0, "funding_id": 1}):
                await check_budget(f["funding_id"])
        except Exception as e:
            logger.error(f"Budget alert loop failed: {type(e).__name__}: {e}")
        await asyncio.sleep(6 * 3600)
