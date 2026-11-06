"""Funding (Finance): Excel import of funding lines, budgets depleting by approved shift time, unit rate changes."""
import io
import re
import secrets
from typing import Optional

from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel

from core import P, db, now_iso
from routes.caseload import display_name, participant_key
from routes.pm_common import finance_user, is_finance, money, now_perth, office_user, parse_dmy, token_user

router = APIRouter(prefix="/api")

MGMT_TYPES = ["NDIA", "Self", "Plan", "MyAged Care", "Private", "Insurance", "Charitable"]
TEMPLATE_COLS = ["Participant name", "Participant email", "Funding management type", "Units", "Unit type", "$ per unit",
                 "Service start date", "Service end date", "Invoice payer name", "Invoice payer company", "Invoice payer email",
                 "Invoice payer phone", "Invoice payer ABN", "Representative name", "Representative email",
                 "Representative phone", "Representative relationship", "Support item number", "Support item name"]


async def funding_usage(fids: list) -> dict:
    out = {f: {"spent": 0.0, "units_used": 0.0, "committed": 0.0} for f in fids}
    async for s in db.shifts.find({"funding_id": {"$in": fids}, "status": {"$nin": ["cancelled", "declined"]}}, P):
        u = out[s["funding_id"]]
        if s["status"] == "completed":
            u["spent"] += s.get("cost") or 0
            u["units_used"] += s.get("units") or 0
        else:
            u["committed"] += s.get("est_cost") or 0
    return {k: {kk: round(vv, 2) for kk, vv in v.items()} for k, v in out.items()}


def funding_out(f: dict, use: dict, show_money: bool = True) -> dict:
    remaining = round(f["budget"] - use["spent"], 2)
    units_left = round(f["units"] - use["units_used"], 2)
    out = {**f, **use, "remaining": remaining, "units_left": units_left,
           "available": round(remaining - use["committed"], 2), "active": f["start_date"] <= now_perth().date().isoformat() <= f["end_date"]}
    from routes.roster_extras import projection
    out["alert"] = projection(f, use)
    return out if show_money else {k: out[k] for k in ("funding_id", "participant_id", "management_type", "unit_type", "start_date", "end_date")}



@router.get("/funding/template")
async def funding_template(request: Request, token: Optional[str] = None):
    if not is_finance(await token_user(request, token)):
        raise HTTPException(403, "For Finance users")
    from openpyxl import Workbook
    wb = Workbook()
    ws = wb.active
    ws.title = "Funding"
    ws.append(TEMPLATE_COLS)
    ws.append(["Jane Citizen", "jane@example.com", "NDIA", 120, "Hour", 67.56, "01-07-2026", "30-06-2027", "", "Plan Partners Pty Ltd",
               "invoices@planpartners.example", "08 9000 0000", "12 345 678 901", "John Citizen", "john@example.com", "0400 000 000", "Father",
               "01_011_0107_1_1", "Assistance With Self-Care Activities - Standard - Weekday Daytime"])
    notes = wb.create_sheet("How to fill in")
    for line in ["One row per funding line. A participant can have several rows (e.g. different funding types).",
                 f"Funding management type must be one of: {', '.join(MGMT_TYPES)}.",
                 "Unit type: Hour (shifts deplete by approved hours) or another unit such as Each / Shift (1 unit per shift).",
                 "Dates as DD-MM-YYYY. Budget = Units x $ per unit.",
                 "Invoice payer: give a name or company name, an email and phone. ABN where applicable.",
                 "Representative: required when the invoice payer is not the participant's representative. "
                 "If the participant represents themselves, enter their own details.",
                 "Support item number / name (optional): the NDIS or Aged Care price guide item this funding pays for. "
                 "It's shown when rostering and printed on invoices."]:
        notes.append([line])
    for col, w in zip("ABCDEFGHIJKLMNOPQRS", [20, 24, 20, 8, 10, 10, 14, 14, 18, 24, 26, 14, 16, 18, 22, 14, 16, 18, 40]):
        ws.column_dimensions[col].width = w
    buf = io.BytesIO()
    wb.save(buf)
    return Response(content=buf.getvalue(), media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    headers={"Content-Disposition": 'attachment; filename="Funding_import_template.xlsx"'})


def cell(row: dict, k: str) -> str:
    v = row.get(k.lower())
    return "" if v is None else str(v).strip()


async def ensure_participant(name: str, email: str, user: dict) -> dict:
    key = participant_key(name)
    p = await db.participants.find_one({"key": key}, P)
    if not p:
        p = {"participant_id": f"par_{secrets.token_hex(6)}", "name": display_name(name), "key": key, "assigned_ids": [],
             "created_by": user.get("name") or "", "created_at": now_iso()}
        await db.participants.insert_one(dict(p))
    if email and p.get("email") != email:
        await db.participants.update_one({"key": key}, {"$set": {"email": email}})
    return p


@router.post("/funding/import")
async def import_funding(file: UploadFile = File(...), user=Depends(finance_user)):
    from openpyxl import load_workbook
    try:
        ws = load_workbook(io.BytesIO(await file.read()), data_only=True).worksheets[0]
    except Exception:
        raise HTTPException(400, "Upload the Funding template as an Excel (.xlsx) file")
    rows = list(ws.iter_rows(values_only=True))
    if not rows:
        raise HTTPException(400, "The spreadsheet is empty")
    head = [str(h or "").strip().lower() for h in rows[0]]
    missing = [c for c in TEMPLATE_COLS[:13] if c.lower() not in head]
    if missing:
        raise HTTPException(400, f"Missing columns: {', '.join(missing)}. Download the template and try again.")
    added, skipped = [], []
    for n, values in enumerate(rows[1:], start=2):
        r = dict(zip(head, values))
        if not any(v not in (None, "") for v in values):
            continue
        name, errs = cell(r, "Participant name"), []
        mt = next((m for m in MGMT_TYPES if m.lower() == cell(r, "Funding management type").lower()), None)
        try:
            units, rate = float(cell(r, "Units")), float(cell(r, "$ per unit").replace("$", "").replace(",", ""))
            if units <= 0 or rate <= 0:
                raise ValueError
        except ValueError:
            units = rate = 0
            errs.append("units and $ per unit must be numbers above 0")
        sd, ed = parse_dmy(r.get("service start date")), parse_dmy(r.get("service end date"))
        payer = {"name": cell(r, "Invoice payer name"), "company": cell(r, "Invoice payer company"),
                 "email": cell(r, "Invoice payer email").lower(), "phone": cell(r, "Invoice payer phone"), "abn": cell(r, "Invoice payer ABN")}
        rep = {"name": cell(r, "Representative name"), "email": cell(r, "Representative email").lower(),
               "phone": cell(r, "Representative phone"), "relationship": cell(r, "Representative relationship")}
        if len(name) < 2:
            errs.append("participant name is missing")
        if not mt:
            errs.append(f"funding management type must be one of {', '.join(MGMT_TYPES)}")
        if not cell(r, "Unit type"):
            errs.append("unit type is missing")
        if not sd or not ed or sd > ed:
            errs.append("service start and end dates are needed (DD-MM-YYYY, start before end)")
        if not (payer["name"] or payer["company"]) or "@" not in payer["email"] or not payer["phone"]:
            errs.append("invoice payer name or company, email and phone are required")
        if payer["abn"] and not re.fullmatch(r"\d{11}", re.sub(r"\s", "", payer["abn"])):
            errs.append("ABN must be 11 digits")
        payer_is_rep = not rep["name"]
        if not payer_is_rep and ("@" not in rep["email"] or not rep["phone"]):
            errs.append("representative needs an email and phone")
        if errs:
            skipped.append({"row": n, "name": name or "-", "reason": "; ".join(errs)})
            continue
        p = await ensure_participant(name, cell(r, "Participant email").lower(), user)
        item = {"support_item_number": cell(r, "Support item number")[:40], "support_item_name": cell(r, "Support item name")[:200]}
        if await db.fundings.find_one({"participant_id": p["participant_id"], "management_type": mt, "start_date": sd, "end_date": ed,
                                       "unit_type": cell(r, "Unit type"), "support_item_number": {"$in": [item["support_item_number"], None]}}):
            skipped.append({"row": n, "name": name, "reason": "this funding line was already imported (same type and dates)"})
            continue
        f = {"funding_id": f"fund_{secrets.token_hex(6)}", "participant_id": p["participant_id"], "participant_name": p["name"],
             "participant_email": cell(r, "Participant email").lower(), "management_type": mt, "units": units,
             "unit_type": cell(r, "Unit type"), "unit_rate": rate, "budget": money(units * rate), "start_date": sd, "end_date": ed,
             **item, "payer": payer, "representative": payer if payer_is_rep else rep, "payer_is_representative": payer_is_rep,
             "rate_history": [], "created_by": user.get("name") or "", "created_at": now_iso()}
        await db.fundings.insert_one(dict(f))
        added.append({"row": n, "name": p["name"], "management_type": mt, "budget": f["budget"]})
    return {"added": added, "skipped": skipped}


@router.get("/funding")
async def list_funding(participant_id: Optional[str] = None, user=Depends(office_user)):
    q = {"participant_id": participant_id} if participant_id else {}
    funds = await db.fundings.find(q, P).sort([("participant_name", 1), ("start_date", 1)]).to_list(5000)
    use = await funding_usage([f["funding_id"] for f in funds])
    return [funding_out(f, use[f["funding_id"]]) for f in funds]


@router.get("/funding/{funding_id}")
async def get_funding(funding_id: str, user=Depends(office_user)):
    f = await db.fundings.find_one({"funding_id": funding_id}, P)
    if not f:
        raise HTTPException(404, "Funding not found")
    return funding_out(f, (await funding_usage([funding_id]))[funding_id])


class RateIn(BaseModel):
    unit_rate: float
    mode: str  # keep_budget | increase_budget


@router.put("/funding/{funding_id}/rate")
async def change_rate(funding_id: str, body: RateIn, user=Depends(finance_user)):
    """NDIS / Aged Care price change. Keep the total budget (fewer units left), or grow the budget so the remaining units stay."""
    f = await db.fundings.find_one({"funding_id": funding_id}, P)
    if not f:
        raise HTTPException(404, "Funding not found")
    if body.unit_rate <= 0 or body.mode not in ("keep_budget", "increase_budget"):
        raise HTTPException(400, "Enter a new rate above 0 and choose how the budget changes")
    if now_perth().date().isoformat() > f["end_date"]:
        raise HTTPException(400, "This funding's service period has ended")
    use = (await funding_usage([funding_id]))[funding_id]
    remaining, units_left = f["budget"] - use["spent"], f["units"] - use["units_used"]
    if body.mode == "keep_budget":
        budget, units = f["budget"], round(use["units_used"] + max(remaining, 0) / body.unit_rate, 2)
    else:
        budget, units = money(use["spent"] + max(units_left, 0) * body.unit_rate), f["units"]
    hist = {"from_rate": f["unit_rate"], "to_rate": body.unit_rate, "mode": body.mode, "from_budget": f["budget"], "to_budget": budget,
            "effective": now_perth().date().isoformat(), "by": user.get("name") or "", "at": now_iso()}
    await db.fundings.update_one({"funding_id": funding_id}, {"$set": {"unit_rate": body.unit_rate, "budget": budget, "units": units},
                                                            "$push": {"rate_history": hist}})
    # Shifts not yet completed are re-priced at the new rate
    async for s in db.shifts.find({"funding_id": funding_id, "status": {"$nin": ["completed", "cancelled", "declined"]}}, P):
        await db.shifts.update_one({"shift_id": s["shift_id"]}, {"$set": {"unit_rate": body.unit_rate,
                                                                         "est_cost": money(s["est_units"] * body.unit_rate)}})
    return await get_funding(funding_id, user)


class ItemIn(BaseModel):
    support_item_number: str = ""
    support_item_name: str = ""


@router.put("/funding/{funding_id}/item")
async def set_item(funding_id: str, body: ItemIn, user=Depends(finance_user)):
    """Support item (price guide line) this funding pays for; copied onto shifts not yet invoiced."""
    item = {"support_item_number": body.support_item_number.strip()[:40], "support_item_name": body.support_item_name.strip()[:200]}
    res = await db.fundings.update_one({"funding_id": funding_id}, {"$set": item})
    if not res.matched_count:
        raise HTTPException(404, "Funding not found")
    await db.shifts.update_many({"funding_id": funding_id, "invoice_id": {"$in": [None, ""]}}, {"$set": item})
    return await get_funding(funding_id, user)


@router.delete("/funding/{funding_id}")
async def delete_funding(funding_id: str, user=Depends(finance_user)):
    if await db.shifts.count_documents({"funding_id": funding_id, "status": {"$nin": ["cancelled", "declined"]}}):
        raise HTTPException(400, "Shifts are rostered against this funding. Cancel them first.")
    await db.fundings.delete_one({"funding_id": funding_id})
    return {"ok": True}
