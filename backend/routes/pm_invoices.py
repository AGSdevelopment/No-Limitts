"""Participant invoices (Finance): one invoice per funding line (its invoice payer) for completed shifts in a period.
Amounts are the approved shift costs. GST-free. Finance downloads the PDF; nothing is emailed automatically.
Voiding an invoice releases its shifts so they can be invoiced again."""
import asyncio
import io
import os
import secrets
from datetime import date, datetime, timedelta, timezone
from html import escape
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import Response
from pydantic import BaseModel
from pymongo import ReturnDocument

from core import P, db, dmy, logger, notify, now_iso
from email_service import send_email
from pdf_brand import FIRST_TOP, add_logo
from routes.pm_common import finance_user, is_finance, money, now_perth, parse_dmy, token_user
from routes.pm_timesheets import approved

router = APIRouter(prefix="/api")

SETTINGS_KEY = "invoice_settings"
DEFAULTS = {"business_name": "No Limitts Pty Ltd", "abn": "92 606 960 730", "address": "", "email": "", "phone": "",
            "account_name": "", "bsb": "", "account_number": "", "payment_terms_days": 14}
STATUSES = ("unpaid", "paid", "void")


async def get_settings() -> dict:
    doc = await db.meta.find_one({"key": SETTINGS_KEY}, P) or {}
    return {k: doc.get(k, v) for k, v in DEFAULTS.items()}


class SettingsIn(BaseModel):
    business_name: str
    abn: str = ""
    address: str = ""
    email: str = ""
    phone: str = ""
    account_name: str = ""
    bsb: str = ""
    account_number: str = ""
    payment_terms_days: int = 14


@router.get("/invoices/settings")
async def read_settings(user=Depends(finance_user)):
    return await get_settings()


@router.put("/invoices/settings")
async def save_settings(body: SettingsIn, user=Depends(finance_user)):
    data = {k: (v.strip()[:300] if isinstance(v, str) else v) for k, v in body.model_dump().items()}
    if len(data["business_name"]) < 2:
        raise HTTPException(400, "Enter the business name")
    if not 0 <= data["payment_terms_days"] <= 120:
        raise HTTPException(400, "Payment terms must be 0 to 120 days")
    await db.meta.update_one({"key": SETTINGS_KEY}, {"$set": {**data, "updated_by": user.get("name") or "", "updated_at": now_iso()}}, upsert=True)
    return await get_settings()


def check_range(lo: str, hi: str):
    if hi > now_perth().date().isoformat():
        raise HTTPException(400, "Invoices can only cover days that have already happened")
    if (date.fromisoformat(hi) - date.fromisoformat(lo)).days + 1 > 93:
        raise HTTPException(400, "Choose a range of 1 to 93 days")


class GenerateIn(BaseModel):
    date_from: str  # DD-MM-YYYY
    date_to: str


async def next_number() -> str:
    doc = await db.meta.find_one_and_update({"key": "invoice_seq"}, {"$inc": {"value": 1}}, upsert=True, return_document=ReturnDocument.AFTER)
    return f"NL-{doc['value']:06d}"


def line_for(s: dict) -> dict:
    a, b = approved(s)
    return {"shift_id": s["shift_id"], "date": s["date"], "description": f"{s.get('funding_type') or ''} support {a}-{b} · {s['worker_name']}".strip(),
            "units": s.get("units") or 0, "unit_type": "hours" if s.get("hourly") else "units", "rate": s.get("unit_rate") or 0,
            "amount": money(s.get("cost"))}


@router.post("/invoices/generate")
async def generate(body: GenerateIn, user=Depends(finance_user)):
    lo, hi = parse_dmy(body.date_from), parse_dmy(body.date_to)
    if not lo or not hi or lo > hi:
        raise HTTPException(400, "Choose a start and end date (DD-MM-YYYY)")
    check_range(lo, hi)
    q = {"date": {"$gte": lo, "$lte": hi}, "status": "completed", "invoice_id": {"$in": [None, ""]}}
    by_fund: dict = {}
    async for s in db.shifts.find(q, {"_id": 0, "shift_id": 1, "funding_id": 1}):
        by_fund.setdefault(s["funding_id"], []).append(s["shift_id"])
    seller = await get_settings()
    issue = now_perth().date()
    created = []
    for fid, ids in by_fund.items():
        f = await db.fundings.find_one({"funding_id": fid}, P)
        if not f:
            continue
        inv_id = f"inv_{secrets.token_hex(6)}"
        # Claim the shifts first so two Finance users generating at once can't bill a shift twice
        await db.shifts.update_many({"shift_id": {"$in": ids}, "invoice_id": {"$in": [None, ""]}}, {"$set": {"invoice_id": inv_id}})
        shifts = await db.shifts.find({"invoice_id": inv_id}, P).sort([("date", 1), ("start", 1)]).to_list(5000)
        if not shifts:
            continue
        lines = [line_for(s) for s in shifts]
        inv = {"invoice_id": inv_id, "number": await next_number(), "funding_id": fid, "participant_id": f["participant_id"],
               "participant_name": f["participant_name"], "management_type": f["management_type"], "payer": f["payer"],
               "period_from": lo, "period_to": hi, "issue_date": issue.isoformat(),
               "due_date": (issue + timedelta(days=int(seller["payment_terms_days"]))).isoformat(), "lines": lines,
               "total": money(sum(x["amount"] for x in lines)), "status": "unpaid", "seller": seller,
               "created_by": user.get("name") or "", "created_at": now_iso()}
        await db.invoices.insert_one(dict(inv))
        created.append({k: inv[k] for k in ("invoice_id", "number", "participant_name", "management_type", "total")})
    return {"created": created, "count": len(created)}


def summary(inv: dict) -> dict:
    overdue = inv["status"] == "unpaid" and inv["due_date"] < now_perth().date().isoformat()
    return {k: v for k, v in inv.items() if k not in ("lines", "seller", "email_history")} | {"shifts": len(inv["lines"]), "overdue": overdue}


@router.get("/invoices")
async def list_invoices(status: str = "", user=Depends(finance_user)):
    q = {"status": status} if status in STATUSES else {}
    return [summary(i) for i in await db.invoices.find(q, P).sort("created_at", -1).to_list(2000)]


class StatusIn(BaseModel):
    status: str


@router.post("/invoices/{invoice_id}/status")
async def set_status(invoice_id: str, body: StatusIn, user=Depends(finance_user)):
    inv = await db.invoices.find_one({"invoice_id": invoice_id}, P)
    if not inv:
        raise HTTPException(404, "Invoice not found")
    if body.status not in STATUSES:
        raise HTTPException(400, "Choose unpaid, paid or void")
    if inv["status"] == "void":
        raise HTTPException(400, "This invoice was voided. Create a new one instead.")
    upd = {"status": body.status, "status_by": user.get("name") or "", "status_at": now_iso()}
    if body.status == "paid":
        upd["paid_date"] = now_perth().date().isoformat()
    await db.invoices.update_one({"invoice_id": invoice_id}, {"$set": upd})
    if body.status == "void":
        await db.shifts.update_many({"invoice_id": invoice_id}, {"$set": {"invoice_id": None}})
    return summary({**inv, **upd})


def invoice_pdf(inv: dict) -> bytes:
    import pymupdf
    s, p = inv["seller"], inv["payer"]
    rows = "".join(
        f"<tr><td>{dmy(x['date'])}</td><td>{escape(x['description'])}</td><td style='text-align:right'>{x['units']:g} {x['unit_type']}</td>"
        f"<td style='text-align:right'>${x['rate']:,.2f}</td><td style='text-align:right'>${x['amount']:,.2f}</td></tr>" for x in inv["lines"])
    bank = " · ".join(v for v in (f"Account name: {s['account_name']}" if s["account_name"] else "", f"BSB: {s['bsb']}" if s["bsb"] else "",
                                  f"Account: {s['account_number']}" if s["account_number"] else "") if v)
    abn = f" · ABN {escape(s['abn'])}" if s["abn"] else ""
    contact = " · ".join(v for v in (s["address"], s["phone"], s["email"]) if v)
    to = "<br/>".join(escape(v) for v in (p.get("company"), p.get("name"), p.get("email"), p.get("phone"),
                                         f"ABN {p['abn']}" if p.get("abn") else "") if v)
    paid = "<p style='color:#067647;font-size:14px'><b>PAID</b></p>" if inv["status"] == "paid" else (
        "<p style='color:#B42318;font-size:14px'><b>VOID</b></p>" if inv["status"] == "void" else "")
    html = (f"<h2 style='color:#f7a51d;margin:0'>Tax invoice {escape(inv['number'])}</h2>{paid}"
            f"<p style='font-size:10px'><b>{escape(s['business_name'])}</b>{abn}"
            f"{'<br/>' + escape(contact) if contact else ''}</p>"
            f"<table style='width:100%;font-size:10px'><tr><td style='vertical-align:top'><b>Bill to</b><br/>{to}</td>"
            f"<td style='vertical-align:top'><b>Participant</b><br/>{escape(inv['participant_name'])}<br/>{escape(inv['management_type'])} funding</td>"
            f"<td style='vertical-align:top'><b>Issued</b> {dmy(inv['issue_date'])}<br/><b>Due</b> {dmy(inv['due_date'])}<br/>"
            f"<b>Period</b> {dmy(inv['period_from'])} – {dmy(inv['period_to'])}</td></tr></table><br/>"
            f"<table style='width:100%;border-collapse:collapse;font-size:9px' border='1' cellpadding='4'>"
            f"<tr style='background:#FFF3DF'><th>Date</th><th>Support</th><th>Quantity</th><th>Rate</th><th>Amount</th></tr>{rows}"
            f"<tr><td colspan='4' style='text-align:right'>GST</td><td style='text-align:right'>$0.00</td></tr>"
            f"<tr><td colspan='4' style='text-align:right'><b>Total (GST-free)</b></td><td style='text-align:right'><b>${inv['total']:,.2f}</b></td></tr></table>"
            f"<p style='font-size:9px'>Supports are GST-free. {'Please pay by bank transfer: ' + escape(bank) + '. ' if bank else ''}"
            f"Use {escape(inv['number'])} as the payment reference.</p>")
    buf = io.BytesIO()
    writer = pymupdf.DocumentWriter(buf)
    story = pymupdf.Story(html=html)
    page, more, first = pymupdf.paper_rect("a4"), True, True
    while more:
        dev = writer.begin_page(page)
        more, _ = story.place(page + (36, FIRST_TOP if first else 36, -36, -36))
        story.draw(dev)
        writer.end_page()
        first = False
    writer.close()
    return add_logo(buf.getvalue())


@router.get("/invoices/{invoice_id}/pdf")
async def invoice_file(invoice_id: str, request: Request, token: Optional[str] = None):
    if not is_finance(await token_user(request, token)):
        raise HTTPException(403, "For Finance users")
    inv = await db.invoices.find_one({"invoice_id": invoice_id}, P)
    if not inv:
        raise HTTPException(404, "Invoice not found")
    pdf = await run_in_threadpool(invoice_pdf, inv)
    return Response(content=pdf, media_type="application/pdf", headers={"Content-Disposition": f'inline; filename="Invoice_{inv["number"]}.pdf"'})


@router.get("/invoices/uninvoiced")
async def uninvoiced(date_from: str, date_to: str, user=Depends(finance_user)):
    """How many completed shifts and dollars in a period haven't been invoiced yet (shown before generating)."""
    lo, hi = parse_dmy(date_from), parse_dmy(date_to)
    if not lo or not hi or lo > hi:
        raise HTTPException(400, "Choose a start and end date (DD-MM-YYYY)")
    check_range(lo, hi)
    n, total, funds = 0, 0.0, set()
    async for s in db.shifts.find({"date": {"$gte": lo, "$lte": hi}, "status": "completed", "invoice_id": {"$in": [None, ""]}},
                                  {"_id": 0, "cost": 1, "funding_id": 1}):
        n += 1
        total += s.get("cost") or 0
        funds.add(s["funding_id"])
    pending = await db.shifts.count_documents({"date": {"$gte": lo, "$lte": hi}, "status": "awaiting_approval"})
    return {"shifts": n, "total": money(total), "invoices": len(funds), "pending": pending}


# ---- Email to payer (private PDF link) ----

LINK_DAYS = 60


@router.post("/invoices/{invoice_id}/email")
async def email_invoice(invoice_id: str, user=Depends(finance_user)):
    inv = await db.invoices.find_one({"invoice_id": invoice_id}, P)
    if not inv:
        raise HTTPException(404, "Invoice not found")
    if inv["status"] == "void":
        raise HTTPException(400, "This invoice was voided")
    to = (inv["payer"].get("email") or "").strip()
    if "@" not in to:
        raise HTTPException(400, "This funding line has no invoice payer email. Update it in Funding first.")
    token = secrets.token_urlsafe(24)
    s = inv["seller"]
    base = (os.environ.get("PUBLIC_BACKEND_URL") or "").rstrip("/")
    who = inv["payer"].get("name") or inv["payer"].get("company") or "there"
    bank = " · ".join(v for v in (s["account_name"], f"BSB {s['bsb']}" if s["bsb"] else "",
                                  f"Account {s['account_number']}" if s["account_number"] else "") if v)
    html = (f"<p>Hi {escape(who)},</p><p>Please find invoice <b>{escape(inv['number'])}</b> from {escape(s['business_name'])} for supports provided to "
            f"<b>{escape(inv['participant_name'])}</b> from {dmy(inv['period_from'])} to {dmy(inv['period_to'])}.</p>"
            f"<p style='font-size:18px'><b>${inv['total']:,.2f}</b> (GST-free) due {dmy(inv['due_date'])}</p>"
            f'<p><a href="{base}/api/invoices/shared/{token}" style="background:#f7a51d;color:#fff;padding:12px 20px;'
            f'border-radius:10px;text-decoration:none;font-weight:bold">Open the invoice (PDF)</a></p>'
            + (f"<p style='font-size:14px'>Pay by bank transfer: {escape(bank)}. Reference: {escape(inv['number'])}.</p>" if bank else "")
            + f"<p style='font-size:13px;color:#555'>The link stays open for {LINK_DAYS} days. Questions? Reply to this email"
            + (f" or call {escape(s['phone'])}" if s["phone"] else "") + ".</p>")
    if not await send_email(to=to, subject=f"Invoice {inv['number']} from {s['business_name']}", html=html):
        raise HTTPException(422, f"The email to {to} couldn't be sent. Check the payer's email address in Funding, then try again.")
    await db.invoice_links.insert_one({"token": token, "invoice_id": invoice_id, "created_at": now_iso(),
                                       "expires_at": (datetime.now(timezone.utc) + timedelta(days=LINK_DAYS)).isoformat()})
    sent = {"to": to, "at": now_iso(), "date": now_perth().date().isoformat(), "by": user.get("name") or ""}
    await db.invoices.update_one({"invoice_id": invoice_id}, {"$set": {"emailed": sent}, "$push": {"email_history": sent}})
    return {"emailed": sent}


@router.get("/invoices/shared/{token}")
async def shared_invoice(token: str):
    link = await db.invoice_links.find_one({"token": token}, P)
    inv = await db.invoices.find_one({"invoice_id": link["invoice_id"]}, P) if link else None
    if not inv or link["expires_at"] < datetime.now(timezone.utc).isoformat():
        raise HTTPException(404, "This invoice link has expired. Please contact us for a copy.")
    pdf = await run_in_threadpool(invoice_pdf, inv)
    return Response(content=pdf, media_type="application/pdf", headers={"Content-Disposition": f'inline; filename="Invoice_{inv["number"]}.pdf"'})


# ---- Overdue invoices (daily list for Finance, 8am Perth) ----

def payer_label(p: dict) -> str:
    return p.get("company") or p.get("name") or p.get("email") or "Unknown payer"


async def overdue_summary() -> dict:
    today = now_perth().date()
    invs = await db.invoices.find({"status": "unpaid", "due_date": {"$lt": today.isoformat()}}, P).sort("due_date", 1).to_list(5000)
    payers: dict = {}
    for i in invs:
        key = payer_label(i["payer"])
        g = payers.setdefault(key, {"payer": key, "email": i["payer"].get("email", ""), "total": 0.0, "count": 0, "invoices": []})
        g["total"] = money(g["total"] + i["total"])
        g["count"] += 1
        g["invoices"].append({"invoice_id": i["invoice_id"], "number": i["number"], "participant_name": i["participant_name"],
                              "total": i["total"], "due_date": i["due_date"], "days_overdue": (today - date.fromisoformat(i["due_date"])).days})
    groups = sorted(payers.values(), key=lambda g: -g["total"])
    return {"total": money(sum(g["total"] for g in groups)), "count": len(invs), "payers": groups}


@router.get("/invoices/overdue")
async def overdue(user=Depends(finance_user)):
    return await overdue_summary()


async def send_overdue_digest():
    o = await overdue_summary()
    if not o["count"]:
        return
    users = [u async for u in db.users.find({"$or": [{"permissions": "finance"}, {"role": "admin"}], "hidden": {"$ne": True}}, P)]
    top = ", ".join(f"{g['payer']} ${g['total']:,.2f}" for g in o["payers"][:3])
    await notify([u["user_id"] for u in users], "invoice", f"{o['count']} overdue invoice{'s' if o['count'] != 1 else ''}: ${o['total']:,.2f}",
                 f"Biggest: {top}.", "/pm/invoices")
    rows = "".join(
        f"<tr><td style='padding:6px;border-bottom:1px solid #eee'><b>{escape(g['payer'])}</b><br/><span style='color:#555;font-size:12px'>"
        + escape(", ".join(f"{x['number']} ({x['participant_name']}, {x['days_overdue']} days)" for x in g["invoices"]))
        + f"</span></td><td style='padding:6px;border-bottom:1px solid #eee;text-align:right'><b>${g['total']:,.2f}</b></td></tr>" for g in o["payers"])
    html = (f"<p>Good morning,</p><p><b>{o['count']} unpaid invoice{'s are' if o['count'] != 1 else ' is'} past due</b>, totalling "
            f"<b>${o['total']:,.2f}</b>.</p><table style='width:100%;border-collapse:collapse;font-size:14px'>{rows}</table>"
            f"<p style='font-size:13px;color:#555'>Mark invoices as paid in Participant Management, Invoices to clear them from this list.</p>")
    n = len(o["payers"])
    for u in users:
        if u.get("email"):
            await send_email(to=u["email"], subject=f"Overdue invoices: ${o['total']:,.2f} across {n} payer{'s' if n != 1 else ''}", html=html)


async def overdue_loop():
    await asyncio.sleep(150)
    while True:
        try:
            local = now_perth()
            key = f"overdue_invoices_{local.date().isoformat()}"
            if local.hour >= 8 and not await db.meta.find_one({"key": key}):
                await db.meta.insert_one({"key": key, "created_at": now_iso()})
                await send_overdue_digest()
        except Exception as e:
            logger.error(f"Overdue invoice loop failed: {type(e).__name__}: {e}")
        await asyncio.sleep(1800)
