"""Timesheets: approved hours per Support Worker per week (Monday to Sunday, Perth time), in the app and as an Excel export.
Hours only (no pay amounts). Hours come from the approved clock-in to clock-out time of completed shifts."""
import io
from datetime import date, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import Response

from core import P, current_user, db, dmy
from routes.pm_common import is_finance, is_rosters, now_perth, parse_dmy, token_user

router = APIRouter(prefix="/api")
MAX_DAYS = 93


def week_start(iso: str) -> str:
    d = date.fromisoformat(iso)
    return (d - timedelta(days=d.weekday())).isoformat()


def approved(s: dict) -> tuple:
    ci, co = s.get("clock_in") or {}, s.get("clock_out") or {}
    return s.get("approved_start") or ci.get("time", ""), s.get("approved_end") or co.get("time", "")


def period(date_from: Optional[str], date_to: Optional[str]) -> tuple:
    if not date_from and not date_to:
        lo = date.fromisoformat(week_start(now_perth().date().isoformat()))
        return lo.isoformat(), (lo + timedelta(days=6)).isoformat()
    lo, hi = parse_dmy(date_from), parse_dmy(date_to)
    if not lo or not hi or lo > hi:
        raise HTTPException(400, "Choose a start and end date (DD-MM-YYYY)")
    if (date.fromisoformat(hi) - date.fromisoformat(lo)).days + 1 > MAX_DAYS:
        raise HTTPException(400, f"Choose a range of 1 to {MAX_DAYS} days")
    return lo, hi


async def worked_shifts(lo: str, hi: str, user: dict, worker_id: str = "") -> list:
    q: dict = {"date": {"$gte": lo, "$lte": hi}, "status": {"$in": ["completed", "awaiting_approval"]}}
    if not (is_rosters(user) or is_finance(user)):
        q["worker_id"] = user["user_id"]
    elif worker_id:
        q["worker_id"] = worker_id
    return await db.shifts.find(q, P).sort([("worker_name", 1), ("date", 1), ("start", 1)]).to_list(20000)


def summarise(shifts: list) -> list:
    per: dict = {}
    for s in shifts:
        w = per.setdefault(s["worker_id"], {"worker_id": s["worker_id"], "worker_name": s["worker_name"], "minutes": 0, "shifts": 0,
                                            "pending": 0, "weeks": {}})
        wk = w["weeks"].setdefault(week_start(s["date"]), {"week_start": week_start(s["date"]), "minutes": 0, "shifts": 0, "pending": 0})
        if s["status"] == "completed":
            m = s.get("approved_minutes") or 0
            w["minutes"] += m
            w["shifts"] += 1
            wk["minutes"] += m
            wk["shifts"] += 1
        else:
            w["pending"] += 1
            wk["pending"] += 1
    out = []
    for w in sorted(per.values(), key=lambda x: x["worker_name"].lower()):
        weeks = [{**k, "hours": round(k["minutes"] / 60, 2)} for k in sorted(w["weeks"].values(), key=lambda x: x["week_start"])]
        out.append({**w, "hours": round(w["minutes"] / 60, 2), "weeks": weeks})
    return out


@router.get("/timesheets")
async def timesheets(date_from: Optional[str] = None, date_to: Optional[str] = None, worker_id: str = "", user=Depends(current_user)):
    """Finance and Rosters see everyone; Support Workers see their own hours."""
    lo, hi = period(date_from, date_to)
    workers = summarise(await worked_shifts(lo, hi, user, worker_id))
    return {"date_from": lo, "date_to": hi, "all_staff": is_rosters(user) or is_finance(user), "workers": workers,
            "total_hours": round(sum(w["minutes"] for w in workers) / 60, 2), "pending": sum(w["pending"] for w in workers)}


@router.get("/timesheets/export")
async def export_timesheets(request: Request, date_from: str, date_to: str, token: Optional[str] = None):
    user = await token_user(request, token)
    if not (is_finance(user) or is_rosters(user)):
        raise HTTPException(403, "For Finance and Rosters users")
    lo, hi = period(date_from, date_to)
    shifts = await worked_shifts(lo, hi, user)
    from openpyxl import Workbook
    from openpyxl.styles import Font
    wb = Workbook()
    ws = wb.active
    ws.title = "Weekly hours"
    ws.append([f"Timesheets {dmy(lo)} to {dmy(hi)} (approved hours, Perth time)"])
    ws["A1"].font = Font(bold=True, size=14)
    ws.append([])
    ws.append(["Support Worker", "Week starting (Mon)", "Approved hours", "Shifts", "Awaiting approval"])
    for c in ws[3]:
        c.font = Font(bold=True)
    for w in summarise(shifts):
        for k in w["weeks"]:
            ws.append([w["worker_name"], dmy(k["week_start"]), k["hours"], k["shifts"], k["pending"]])
        ws.append([f"{w['worker_name']} total", "", w["hours"], w["shifts"], w["pending"]])
        ws.cell(ws.max_row, 1).font = Font(bold=True)
    det = wb.create_sheet("Shifts")
    det.append(["Date", "Support Worker", "Participant", "Funding type", "Rostered start", "Rostered finish", "Approved start",
                "Approved finish", "Approved hours", "Status"])
    for c in det[1]:
        c.font = Font(bold=True)
    for s in shifts:
        a, b = approved(s)
        done = s["status"] == "completed"
        det.append([dmy(s["date"]), s["worker_name"], s["participant_name"], s.get("funding_type", ""), s["start"], s["end"],
                    a if done else "", b if done else "", round((s.get("approved_minutes") or 0) / 60, 2) if done else "",
                    "Approved" if done else "Clock times awaiting approval"])
    for sheet, widths in ((ws, [28, 20, 16, 10, 18]), (det, [12, 24, 24, 14, 14, 14, 14, 14, 14, 28])):
        for i, wdt in enumerate(widths):
            sheet.column_dimensions[chr(65 + i)].width = wdt
    buf = io.BytesIO()
    wb.save(buf)
    return Response(content=buf.getvalue(), media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    headers={"Content-Disposition": f'attachment; filename="Timesheets_{lo}_to_{hi}.xlsx"'})
