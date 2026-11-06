"""Participant Management: Rostering (Rosters), clock in/out, Support Team tags and the exceptions report.
All dates and times are Perth (AWST). Shifts deplete funding by the approved clock-in to clock-out time.
Funding lives in pm_funding.py; shared permission and time helpers in pm_common.py."""
import io
import math
import secrets
from datetime import date, datetime, timedelta
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import Response
from pydantic import BaseModel

from core import P, current_user, db, dmy, notify, now_iso
from routes.caseload import welcome_workers
from routes.pm_common import (fmt_hm, hhmm_ok, is_coordinator, is_finance, is_rosters, local_dt, money, now_perth, parse_dmy,
                              rosters_user, span, token_user)
from routes.pm_funding import funding_out, funding_usage

router = APIRouter(prefix="/api")

HOURLY = ("hour", "hours", "hr", "hrs", "hourly")
TOLERANCE_MIN = 5
GAP_MIN = 30
AUTO_ACCEPT_DAYS = 14
REASONS = ["Started late so finished late", "Held up in traffic", "Prior shift ran over", "Unavoidable delay"]


class PermsIn(BaseModel):
    permissions: List[str]


@router.put("/users/{user_id}/permissions")
async def set_permissions(user_id: str, body: PermsIn, user=Depends(current_user)):
    if user.get("role") != "admin":
        raise HTTPException(403, "Admins only")
    clean = sorted({p for p in body.permissions if p in ("finance", "rosters")})
    res = await db.users.update_one({"user_id": user_id}, {"$set": {"permissions": clean}})
    if not res.matched_count:
        raise HTTPException(404, "User not found")
    return {"permissions": clean}


@router.get("/pm/access")
async def pm_access(user=Depends(current_user)):
    pending = await db.team_tag_requests.count_documents({"status": "pending"}) if is_coordinator(user) else 0
    awaiting = await db.shifts.count_documents({"status": "awaiting_approval"}) if is_rosters(user) else 0
    has_shifts = bool(await db.shifts.find_one({"worker_id": user["user_id"], "status": {"$ne": "cancelled"}}, {"_id": 1}))
    return {"finance": is_finance(user), "rosters": is_rosters(user), "coordinator": is_coordinator(user),
            "worker": user.get("user_type") == "support_worker", "has_shifts": has_shifts, "pending_tags": pending, "awaiting_approval": awaiting}


# ---- Support Team tags (Team Directory) ----

class TagIn(BaseModel):
    user_id: str
    participant_id: str


async def approve_tag(user_id: str, participant_id: str):
    p = await db.participants.find_one({"participant_id": participant_id}, P)
    if p and user_id not in p.get("assigned_ids", []):
        await db.participants.update_one({"participant_id": participant_id}, {"$addToSet": {"assigned_ids": user_id}, "$set": {"updated_at": now_iso()}})
        await welcome_workers([user_id], p)


@router.get("/support-team/tags/{user_id}")
async def user_tags(user_id: str, user=Depends(current_user)):
    approved = [{"participant_id": p["participant_id"], "name": p["name"]}
                async for p in db.participants.find({"assigned_ids": user_id}, {"_id": 0, "participant_id": 1, "name": 1}).sort("name", 1)]
    pending = await db.team_tag_requests.find({"user_id": user_id, "status": "pending"}, P).to_list(200)
    can_request = user["user_id"] == user_id or is_coordinator(user) or is_rosters(user)
    return {"approved": approved, "pending": pending, "can_request": can_request, "can_approve": is_coordinator(user)}


@router.post("/support-team/tags")
async def request_tag(body: TagIn, user=Depends(current_user)):
    if not (user["user_id"] == body.user_id or is_coordinator(user) or is_rosters(user)):
        raise HTTPException(403, "You can only tag yourself")
    target = await db.users.find_one({"user_id": body.user_id, "user_type": "support_worker"}, P)
    p = await db.participants.find_one({"participant_id": body.participant_id}, P)
    if not target or not p:
        raise HTTPException(400, "Participant tags are for Support Workers and existing participants")
    if body.user_id in p.get("assigned_ids", []):
        raise HTTPException(400, f"{target['name']} is already on {p['name']}'s Support Team")
    if is_coordinator(user):
        await approve_tag(body.user_id, body.participant_id)
        return {"status": "approved"}
    if await db.team_tag_requests.find_one({"user_id": body.user_id, "participant_id": body.participant_id, "status": "pending"}):
        raise HTTPException(400, "That tag is already waiting for approval")
    req = {"request_id": f"tag_{secrets.token_hex(6)}", "user_id": body.user_id, "user_name": target["name"], "participant_id": p["participant_id"],
           "participant_name": p["name"], "requested_by": user.get("name") or "", "status": "pending", "created_at": now_iso()}
    await db.team_tag_requests.insert_one(dict(req))
    coords = [u["user_id"] async for u in db.users.find({"user_type": "support_coordinator", "hidden": {"$ne": True}}, {"_id": 0, "user_id": 1})]
    await notify(coords, "participant", f"Support Team tag to approve: {p['name']}",
                 f"{req['requested_by']} asked to add {target['name']} to {p['name']}'s Support Team.", "/pm")
    return {"status": "pending", "request": req}


@router.get("/support-team/requests")
async def tag_requests(user=Depends(current_user)):
    if not is_coordinator(user):
        raise HTTPException(403, "For Service Coordinators")
    return await db.team_tag_requests.find({"status": "pending"}, P).sort("created_at", 1).to_list(500)


class DecideIn(BaseModel):
    approve: bool


@router.post("/support-team/requests/{request_id}")
async def decide_tag(request_id: str, body: DecideIn, user=Depends(current_user)):
    if not is_coordinator(user):
        raise HTTPException(403, "For Service Coordinators")
    r = await db.team_tag_requests.find_one({"request_id": request_id, "status": "pending"}, P)
    if not r:
        raise HTTPException(404, "Request not found")
    await db.team_tag_requests.update_one({"request_id": request_id}, {"$set": {
        "status": "approved" if body.approve else "rejected", "decided_by": user.get("name") or "", "decided_at": now_iso()}})
    if body.approve:
        await approve_tag(r["user_id"], r["participant_id"])
    else:
        await notify([r["user_id"]], "participant", f"Support Team tag not approved: {r['participant_name']}",
                     f"{user.get('name') or 'A coordinator'} didn't approve the tag. Talk to them if you think this is a mistake.", "/team")
    return {"ok": True}


# ---- Rostering ----

class ShiftIn(BaseModel):
    participant_id: str
    funding_id: str
    worker_id: str
    date: str  # DD-MM-YYYY
    start: str  # HH:MM 24hr
    end: str
    notes: str = ""
    replaces: str = ""  # declined shift this one re-rosters


def est_units(f: dict, minutes: float) -> float:
    return round(minutes / 60, 2) if f["unit_type"].strip().lower() in HOURLY else 1.0


def shift_minutes(s: dict) -> int:
    a, b = span(s)
    return int((b - a).total_seconds() // 60)


async def clash(worker_id: str, s: dict, ignore: str = "") -> Optional[str]:
    a, b = span(s)
    lo = (a - timedelta(days=1)).date().isoformat()
    hi = (b + timedelta(days=1)).date().isoformat()
    async for o in db.shifts.find({"worker_id": worker_id, "status": {"$nin": ["cancelled", "declined"]}, "shift_id": {"$ne": ignore},
                                   "date": {"$gte": lo, "$lte": hi}}, P):
        oa, ob = span(o)
        if o["participant_id"] == s["participant_id"]:
            continue  # back-to-back or concurrent shifts for the same participant are fine
        gap = timedelta(minutes=GAP_MIN)
        if a < ob + gap and oa < b + gap:
            return (f"{o['worker_name']} is rostered with {o['participant_name']} {dmy(o['date'])} {o['start']}-{o['end']}. "
                    f"Shifts for different participants can't overlap and need {GAP_MIN} minutes between them.")
    return None


def shift_view(s: dict, user: dict, profile: Optional[dict] = None) -> dict:
    out = {k: v for k, v in s.items() if k not in ("est_cost", "cost", "funding_type", "unit_rate")}
    if is_rosters(user) or is_finance(user):
        out.update({"funding_type": s.get("funding_type"), "est_cost": s.get("est_cost"), "cost": s.get("cost")})
    elif (out.get("clock_in") or {}).get("location"):  # exact coordinates are for Rosters / Finance only
        out["clock_in"] = {**out["clock_in"], "location": {k: v for k, v in out["clock_in"]["location"].items() if k not in ("lat", "lng")}}
    if profile is not None:
        out["plan"] = {k: (profile.get(k) or "") for k in ("goals", "support_needs", "communication", "health_alerts")}
    return out


@router.post("/shifts")
async def create_shift(body: ShiftIn, user=Depends(rosters_user)):
    d = parse_dmy(body.date)
    if not d or not hhmm_ok(body.start) or not hhmm_ok(body.end) or body.start == body.end:
        raise HTTPException(400, "Enter the date as DD-MM-YYYY and start and finish times as 24-hour HH:MM")
    p = await db.participants.find_one({"participant_id": body.participant_id}, P)
    f = await db.fundings.find_one({"funding_id": body.funding_id, "participant_id": body.participant_id}, P)
    w = await db.users.find_one({"user_id": body.worker_id}, P)
    if not p or not f or not w:
        raise HTTPException(400, "Choose a participant, one of their funding lines and a staff member")
    if body.worker_id not in p.get("assigned_ids", []):
        raise HTTPException(400, f"{w['name']} isn't on {p['name']}'s approved Support Team")
    if not f["start_date"] <= d <= f["end_date"]:
        raise HTTPException(400, f"This funding covers {dmy(f['start_date'])} to {dmy(f['end_date'])} only")
    s = {"date": d, "start": body.start, "end": body.end, "participant_id": p["participant_id"]}
    a, _ = span(s)
    if a < now_perth():
        raise HTTPException(400, "That shift has already started")
    mins = shift_minutes(s)
    units = est_units(f, mins)
    est = money(units * f["unit_rate"])
    use = (await funding_usage([f["funding_id"]]))[f["funding_id"]]
    available = f["budget"] - use["spent"] - use["committed"]
    if est > available + 0.005:
        raise HTTPException(400, f"Not enough funding left: this shift needs ${est:,.2f} but ${max(available, 0):,.2f} is available")
    why = await clash(body.worker_id, s)
    if why:
        raise HTTPException(409, why)
    if body.replaces:
        old = await db.shifts.find_one({"shift_id": body.replaces, "status": "declined"}, P)
        if not old or old["participant_id"] != p["participant_id"]:
            raise HTTPException(400, "The declined shift you're re-rostering wasn't found for this participant")
        if old.get("rerostered"):
            raise HTTPException(400, "This declined shift has already been re-rostered")
        if old["worker_id"] == body.worker_id:
            raise HTTPException(400, f"{w['name']} declined this shift. Choose someone else.")
    auto = a >= now_perth() + timedelta(days=AUTO_ACCEPT_DAYS)
    doc = {"shift_id": f"shf_{secrets.token_hex(6)}", **s, "participant_name": p["name"], "funding_id": f["funding_id"],
           "funding_type": f["management_type"], "unit_rate": f["unit_rate"], "worker_id": w["user_id"], "worker_name": w["name"],
           "support_item_number": f.get("support_item_number") or "", "support_item_name": f.get("support_item_name") or "",
           "minutes": mins, "est_units": units, "hourly": f["unit_type"].strip().lower() in HOURLY, "est_cost": est, "notes": body.notes.strip()[:500],
           "status": "accepted" if auto else "pending_acceptance", "auto_accepted": auto,
           "created_by": user.get("name") or "", "created_at": now_iso()}
    await db.shifts.insert_one(dict(doc))
    if body.replaces:
        await db.shifts.update_one({"shift_id": body.replaces, "status": "declined"}, {"$set": {"rerostered": doc["shift_id"], "open": False}})
    when = f"{dmy(d)} {body.start}-{body.end}"
    await notify([w["user_id"]], "shift", f"New shift: {p['name']} {when}",
                 "It's been added to your roster." if auto else "Please accept it in the app (it's within the next 2 weeks).", "/pm/rostering")
    return shift_view(doc, user)


@router.get("/shifts")
async def list_shifts(date_from: Optional[str] = None, date_to: Optional[str] = None, participant_id: Optional[str] = None,
                      worker_id: Optional[str] = None, status: Optional[str] = None, mine: bool = False, user=Depends(current_user)):
    """mine=true: every shift the signed-in person is rostered on, any date (My Shifts)."""
    q: dict = {}
    if mine or not is_rosters(user):
        q["worker_id"] = user["user_id"]
    elif worker_id:
        q["worker_id"] = worker_id
    if participant_id:
        q["participant_id"] = participant_id
    if status:
        q["status"] = status
    lo = parse_dmy(date_from) or (now_perth().date() - timedelta(days=7)).isoformat()
    hi = parse_dmy(date_to) or (now_perth().date() + timedelta(days=60)).isoformat()
    q["date"] = {"$gte": lo, "$lte": hi}
    if status == "awaiting_approval" or mine:
        q.pop("date")
    shifts = await db.shifts.find(q, P).sort([("date", 1), ("start", 1)]).to_list(2000)
    addr = {p["participant_id"]: p.get("address") or "" async for p in db.participants.find(
        {"participant_id": {"$in": list({x["participant_id"] for x in shifts})}}, {"_id": 0, "participant_id": 1, "address": 1})}
    return [{**shift_view(s, user), "address": addr.get(s["participant_id"], "")} for s in shifts]


async def get_shift_for(shift_id: str, user: dict) -> dict:
    s = await db.shifts.find_one({"shift_id": shift_id}, P)
    if not s or (s["worker_id"] != user["user_id"] and not is_rosters(user)):
        raise HTTPException(404, "Shift not found")
    return s


@router.get("/shifts/{shift_id}")
async def shift_detail(shift_id: str, user=Depends(current_user)):
    s = await get_shift_for(shift_id, user)
    p = await db.participants.find_one({"participant_id": s["participant_id"]}, P) or {}
    return {**shift_view(s, user, p.get("profile") or {}), "address": p.get("address") or ""}


@router.post("/shifts/{shift_id}/accept")
async def accept_shift(shift_id: str, user=Depends(current_user)):
    s = await get_shift_for(shift_id, user)
    if s["worker_id"] != user["user_id"] or s["status"] != "pending_acceptance":
        raise HTTPException(400, "This shift doesn't need accepting")
    await db.shifts.update_one({"shift_id": shift_id}, {"$set": {"status": "accepted", "accepted_at": now_iso()}})
    return {"status": "accepted"}


@router.delete("/shifts/{shift_id}")
async def cancel_shift(shift_id: str, user=Depends(rosters_user)):
    s = await db.shifts.find_one({"shift_id": shift_id}, P)
    if not s or s["status"] in ("completed", "cancelled") or s.get("clock_in"):
        raise HTTPException(400, "Only shifts that haven't started can be cancelled")
    await db.shifts.update_one({"shift_id": shift_id}, {"$set": {"status": "cancelled", "cancelled_by": user.get("name") or "", "cancelled_at": now_iso()}})
    from routes.shift_market import close_swap
    await close_swap(s, "the shift was cancelled")
    await notify([s["worker_id"]], "shift", f"Shift cancelled: {s['participant_name']} {dmy(s['date'])} {s['start']}-{s['end']}",
                 "This shift has been removed from your roster.", "/pm/rostering")
    return {"ok": True}


class ClockIn(BaseModel):
    reason: str = ""
    detail: str = ""
    lat: Optional[float] = None  # phone location at clock-in (optional: no location means Rosters review the times)
    lng: Optional[float] = None
    accuracy: Optional[float] = None


# ---- Clock-in location check ----

LOCATION_RADIUS_M = 300


def metres(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    r1, r2 = math.radians(lat1), math.radians(lat2)
    a = math.sin((r2 - r1) / 2) ** 2 + math.cos(r1) * math.cos(r2) * math.sin(math.radians(lng2 - lng1) / 2) ** 2
    return 6371000 * 2 * math.asin(math.sqrt(a))


async def location_check(s: dict, body: ClockIn) -> dict:
    """Compare the phone's location with the participant's address. Far away or not shared = flagged for Rosters (never blocked)."""
    p = await db.participants.find_one({"participant_id": s["participant_id"]}, {"_id": 0, "address": 1, "geo": 1}) or {}
    g = p.get("geo") or {}
    if g.get("lat") is None:
        return {"checked": False}
    if body.lat is None or body.lng is None:
        return {"checked": True, "flagged": True, "note": "Location wasn't shared at clock-in"}
    d = round(metres(body.lat, body.lng, g["lat"], g["lng"]))
    acc = round(min(max(body.accuracy or 0, 0), 200))
    far = d - acc > LOCATION_RADIUS_M
    away = f"{d / 1000:.1f} km" if d >= 1000 else f"{d} m"
    return {"checked": True, "flagged": far, "distance_m": d, "accuracy_m": acc, "lat": body.lat, "lng": body.lng,
            "note": f"Clocked in {away} from {p.get('address') or 'the participant address'}" if far else ""}


class AddressIn(BaseModel):
    address: str


def can_set_address(u: dict) -> bool:
    return is_rosters(u) or is_coordinator(u)


@router.get("/pm/addresses")
async def addresses(user=Depends(current_user)):
    if not can_set_address(user):
        raise HTTPException(403, "For Rosters and Service Coordinators")
    return [{"participant_id": p["participant_id"], "name": p["name"], "address": p.get("address") or "",
             "found": (p.get("geo") or {}).get("lat") is not None}
            async for p in db.participants.find({}, {"_id": 0, "participant_id": 1, "name": 1, "address": 1, "geo": 1}).sort("name", 1)]


@router.put("/participants/{participant_id}/address")
async def set_address(participant_id: str, body: AddressIn, user=Depends(current_user)):
    if not can_set_address(user):
        raise HTTPException(403, "For Rosters and Service Coordinators")
    if not await db.participants.find_one({"participant_id": participant_id}, {"_id": 1}):
        raise HTTPException(404, "Participant not found")
    text = " ".join(body.address.split())[:300]
    geo = None
    if text:
        from routes.referral_map import geocode
        g = await geocode(text)
        geo = {"lat": g["lat"], "lng": g["lng"]} if g else None
    await db.participants.update_one({"participant_id": participant_id}, {"$set": {"address": text, "geo": geo, "updated_at": now_iso()}})
    return {"address": text, "found": geo is not None}


def check_reason(body: ClockIn) -> dict:
    if body.reason not in REASONS:
        raise HTTPException(422, "outside_window")
    if body.reason == "Unavoidable delay" and len(body.detail.strip()) < 3:
        raise HTTPException(400, "Tell us what the unavoidable delay was")
    return {"reason": body.reason, "detail": body.detail.strip()[:500] if body.reason == "Unavoidable delay" else ""}


def complete(s: dict, start: datetime, end: datetime) -> dict:
    mins = max(int((end - start).total_seconds() // 60), 0)
    units = round(mins / 60, 2) if s.get("hourly") else 1.0
    return {"approved_minutes": mins, "units": units, "cost": money(units * s["unit_rate"]),
            "unbudgeted_minutes": max(mins - s["minutes"], 0), "status": "completed"}


@router.post("/shifts/{shift_id}/clock-in")
async def clock_in(shift_id: str, body: ClockIn, user=Depends(current_user)):
    s = await get_shift_for(shift_id, user)
    if s["worker_id"] != user["user_id"]:
        raise HTTPException(403, "Only the rostered staff member can clock in")
    if s["status"] == "pending_acceptance":
        raise HTTPException(400, "Accept this shift first")
    if s["status"] != "accepted" or s.get("clock_in"):
        raise HTTPException(400, "You've already clocked in for this shift")
    start, end = span(s)
    now = now_perth()
    if now < start - timedelta(hours=2) or now > end:
        raise HTTPException(400, "You can clock in from 2 hours before the shift until it finishes")
    off = abs((now - start).total_seconds()) > TOLERANCE_MIN * 60
    entry = {"at": now.isoformat(), "time": fmt_hm(now), "outside_window": off, **(check_reason(body) if off else {}),
             "location": await location_check(s, body)}
    await db.shifts.update_one({"shift_id": shift_id}, {"$set": {"clock_in": entry, "status": "in_progress"}})
    return {"status": "in_progress", "clock_in": entry}


@router.post("/shifts/{shift_id}/clock-out")
async def clock_out(shift_id: str, body: ClockIn, user=Depends(current_user)):
    s = await get_shift_for(shift_id, user)
    if s["worker_id"] != user["user_id"] or s["status"] != "in_progress":
        raise HTTPException(400, "Clock in first")
    _, end = span(s)
    now = now_perth()
    from routes.roster_extras import has_case_note  # local import: roster_extras imports this module
    if not await has_case_note(s, user):
        raise HTTPException(409, "case_note_required")
    off = abs((now - end).total_seconds()) > TOLERANCE_MIN * 60
    entry = {"at": now.isoformat(), "time": fmt_hm(now), "outside_window": off, **(check_reason(body) if off else {})}
    upd = {"clock_out": entry}
    loc = s["clock_in"].get("location") or {}
    if off or s["clock_in"]["outside_window"] or loc.get("flagged"):
        upd["status"] = "awaiting_approval"
        rosters = [u["user_id"] async for u in db.users.find({"$or": [{"permissions": "rosters"}, {"role": "admin"}], "hidden": {"$ne": True}},
                                                             {"_id": 0, "user_id": 1})]
        await notify(rosters, "shift", f"Clock times to approve: {s['worker_name']}",
                     f"{s['participant_name']} {dmy(s['date'])}: rostered {s['start']}-{s['end']}, clocked {s['clock_in']['time']}-{entry['time']}."
                     + (f" {loc['note']}." if loc.get("flagged") else ""),
                     "/pm/rostering")
    else:
        upd.update(complete(s, datetime.fromisoformat(s["clock_in"]["at"]), now))
    await db.shifts.update_one({"shift_id": shift_id}, {"$set": upd})
    if upd["status"] == "completed":
        from routes.roster_extras import check_budget
        await check_budget(s["funding_id"])
    return {"status": upd["status"], "clock_out": entry}


class ApproveIn(BaseModel):
    start: str  # HH:MM approved start
    end: str
    comment: str = ""


@router.post("/shifts/{shift_id}/approve")
async def approve_times(shift_id: str, body: ApproveIn, user=Depends(rosters_user)):
    s = await db.shifts.find_one({"shift_id": shift_id, "status": "awaiting_approval"}, P)
    if not s:
        raise HTTPException(404, "No clock times waiting for approval on this shift")
    if not hhmm_ok(body.start) or not hhmm_ok(body.end):
        raise HTTPException(400, "Enter the approved start and finish as 24-hour HH:MM")
    a = local_dt(s["date"], body.start)
    b = local_dt(s["date"], body.end)
    if b <= a:
        b += timedelta(days=1)
    if (b - a) > timedelta(hours=24):
        raise HTTPException(400, "Approved times look wrong")
    res = complete(s, a, b)
    f = await db.fundings.find_one({"funding_id": s["funding_id"]}, P)
    use = (await funding_usage([s["funding_id"]]))[s["funding_id"]]
    over = res["cost"] > (f["budget"] - use["spent"]) + 0.005 if f else False
    await db.shifts.update_one({"shift_id": shift_id}, {"$set": {**res, "approved_start": body.start, "approved_end": body.end, "approval": {
        "by": user.get("name") or "", "at": now_iso(), "comment": body.comment.strip()[:500]}}})
    await notify([s["worker_id"]], "shift", f"Clock times approved: {s['participant_name']} {dmy(s['date'])}",
                 f"Approved {body.start}-{body.end}." + (f" {body.comment.strip()}" if body.comment.strip() else ""), "/pm/rostering")
    from routes.roster_extras import check_budget
    await check_budget(s["funding_id"])
    return {**res, "over_budget": over}


# ---- Exceptions report (Rosters & Finance) ----

@router.get("/roster/report")
async def roster_report(request: Request, date_from: str, date_to: str, token: Optional[str] = None):
    user = await token_user(request, token)
    if not (is_finance(user) or is_rosters(user)):
        raise HTTPException(403, "For Finance and Rosters users")
    lo, hi = parse_dmy(date_from), parse_dmy(date_to)
    if not lo or not hi or lo > hi:
        raise HTTPException(400, "Choose a start and end date (DD-MM-YYYY)")
    if (date.fromisoformat(hi) - date.fromisoformat(lo)).days + 1 > 90:
        raise HTTPException(400, "Choose a range of 1 to 90 days")
    from openpyxl import Workbook
    from openpyxl.styles import Font
    shifts = await db.shifts.find({"date": {"$gte": lo, "$lte": hi}, "status": {"$in": ["completed", "awaiting_approval"]}}, P).sort(
        [("date", 1), ("start", 1)]).to_list(10000)
    flagged = [s for s in shifts if (s.get("clock_in") or {}).get("outside_window") or (s.get("clock_out") or {}).get("outside_window")
               or ((s.get("clock_in") or {}).get("location") or {}).get("flagged")]
    unbudgeted = sum(s.get("unbudgeted_minutes") or 0 for s in shifts)
    wb = Workbook()
    ws = wb.active
    ws.title = "Summary"
    ws.append(["Clock in/out exceptions report"])
    ws["A1"].font = Font(bold=True, size=14)
    ws.append(["Period", f"{dmy(lo)} to {dmy(hi)}"])
    ws.append(["Shifts worked", len(shifts)])
    ws.append(["Clock in/out incidents needing approval", len(flagged)])
    ws.append(["Still awaiting approval", sum(s["status"] == "awaiting_approval" for s in flagged)])
    ws.append(["Unbudgeted time (minutes)", unbudgeted])
    ws.append(["Unbudgeted time (hours)", round(unbudgeted / 60, 2)])
    ws.append([])
    ws.append(["Support Worker", "Incidents", "Unbudgeted minutes"])
    per: dict = {}
    for s in shifts:
        w = per.setdefault(s["worker_name"], [0, 0])
        w[0] += s in flagged
        w[1] += s.get("unbudgeted_minutes") or 0
    for name, (n, m) in sorted(per.items()):
        if n or m:
            ws.append([name, n, m])
    det = wb.create_sheet("Incidents")
    det.append(["Date", "Support Worker", "Participant", "Funding type", "Rostered start", "Rostered finish", "Clock in", "Clock out",
                "Clock-in reason", "Clock-out reason", "Detail", "Status", "Approved start", "Approved finish", "Approved by",
                "Rosters comment", "Unbudgeted minutes", "Location check"])
    for s in flagged:
        ci, co, ap = s.get("clock_in") or {}, s.get("clock_out") or {}, s.get("approval") or {}
        det.append([dmy(s["date"]), s["worker_name"], s["participant_name"], s.get("funding_type", ""), s["start"], s["end"],
                    ci.get("time", ""), co.get("time", ""), ci.get("reason", ""), co.get("reason", ""),
                    "; ".join(x for x in (ci.get("detail"), co.get("detail")) if x), "Approved" if s["status"] == "completed" else "Awaiting approval",
                    s.get("approved_start", ""), s.get("approved_end", ""), ap.get("by", ""), ap.get("comment", ""), s.get("unbudgeted_minutes") or 0,
                    (ci.get("location") or {}).get("note", "")])
    ws.column_dimensions["A"].width = 40
    buf = io.BytesIO()
    wb.save(buf)
    return Response(content=buf.getvalue(), media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    headers={"Content-Disposition": f'attachment; filename="Clock_exceptions_{lo}_to_{hi}.xlsx"'})


@router.get("/pm/options")
async def roster_options(user=Depends(rosters_user)):
    """Participants with their approved Support Team and funding lines, for the New shift form."""
    funds = await db.fundings.find({"end_date": {"$gte": now_perth().date().isoformat()}}, P).to_list(5000)
    use = await funding_usage([f["funding_id"] for f in funds])
    by_p: dict = {}
    for f in funds:
        by_p.setdefault(f["participant_id"], []).append(funding_out(f, use[f["funding_id"]]))
    out = []
    async for p in db.participants.find({}, P).sort("name", 1):
        team = [{"user_id": u["user_id"], "name": u["name"]} async for u in db.users.find(
            {"user_id": {"$in": p.get("assigned_ids", [])}, "hidden": {"$ne": True}}, {"_id": 0, "user_id": 1, "name": 1}).sort("name", 1)]
        out.append({"participant_id": p["participant_id"], "name": p["name"], "team": team, "funding": by_p.get(p["participant_id"], [])})
    return out


@router.get("/pm/participants")
async def participant_names(user=Depends(current_user)):
    return [{"participant_id": p["participant_id"], "name": p["name"]}
            async for p in db.participants.find({}, {"_id": 0, "participant_id": 1, "name": 1}).sort("name", 1)]

