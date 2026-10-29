"""Coordinator caseload: participants and recent case notes, read from the Jotform 'Coordinator Case Note Form'."""
import json
import os
import re
import time
from datetime import date
from html import escape
from typing import Optional
import httpx
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import Response
from pydantic import BaseModel
from core import bearer, current_user, db, dmy, logger, now_iso, user_from_token
from pdf_brand import FIRST_TOP, add_logo
import ai_service

router = APIRouter(prefix="/api")
FORM_ID = "262772090420048"
_cache: dict = {"at": 0.0, "rows": None}
SKIP_TYPES = ("control_head", "control_button", "control_text", "control_image", "control_divider", "control_pagebreak")


def configured() -> bool:
    return bool(os.environ.get("JOTFORM_API_KEY", "").strip())


def as_text(ans) -> str:
    if isinstance(ans, dict):
        if "first" in ans or "last" in ans:
            return " ".join(str(ans.get(k) or "").strip() for k in ("prefix", "first", "middle", "last", "suffix")).strip()
        if {"year", "month", "day"} <= set(ans):
            return f"{ans.get('year')}-{str(ans.get('month')).zfill(2)}-{str(ans.get('day')).zfill(2)}"
        return ", ".join(str(v) for v in ans.values() if v)
    if isinstance(ans, list):
        return ", ".join(str(v) for v in ans if v)
    return str(ans or "").strip()


def find(fields: list, *words) -> str:
    for f in fields:
        if any(w in f["label"].lower() for w in words) and f["value"]:
            return f["value"]
    return ""


async def team_header(c: httpx.AsyncClient, base: str) -> dict:
    """The case note form lives in a Jotform Team workspace; team forms are only readable with the jf-team-id header.
    Finds (and caches) the team that can read the form."""
    if "team" in _cache:
        return _cache["team"]
    candidates = [{}]
    r = await c.get(f"{base}/team/user/me")
    if r.status_code == 200:
        candidates += [{"jf-team-id": t["id"]} for t in (r.json().get("content") or []) if t.get("id")]
    for h in candidates:
        if (await c.get(f"{base}/form/{FORM_ID}", headers=h)).status_code == 200:
            _cache["team"] = h
            return h
    return {}


async def fetch_rows() -> list:
    """Last ~1000 submissions, cached for 5 minutes (Jotform has daily API limits)."""
    if _cache["rows"] is not None and time.time() - _cache["at"] < 300:
        return _cache["rows"]
    base = (os.environ.get("JOTFORM_BASE_URL") or "https://nolimitts.jotform.com/API").rstrip("/")  # No Limitts Enterprise API
    rows = []
    async with httpx.AsyncClient(timeout=20, headers={"APIKEY": os.environ["JOTFORM_API_KEY"].strip()}) as c:
        team = await team_header(c, base)
        for offset in range(0, 1000, 500):
            r = await c.get(f"{base}/form/{FORM_ID}/submissions", headers=team,
                            params={"offset": offset, "limit": 500, "orderby": "created_at",
                                    "filter": json.dumps({"status:ne": "DELETED"})})
            r.raise_for_status()
            content = r.json().get("content") or []
            rows += content
            if len(content) < 500:
                break
    out = []
    for s in rows:
        fields = sorted(({"order": int(a.get("order") or 0), "label": (a.get("text") or a.get("name") or "").strip(),
                          "value": as_text(a.get("answer"))}
                         for a in (s.get("answers") or {}).values() if a.get("type") not in SKIP_TYPES and "answer" in a),
                        key=lambda f: f["order"])
        participant = find(fields, "participant", "client") or "Unnamed participant"
        out.append({"id": s.get("id"), "created_at": s.get("created_at"), "participant": participant,
                    "coordinator": find(fields, "coordinator", "your name", "completed by", "staff"),
                    "email": find(fields, "email"),
                    "date": find(fields, "date of contact", "contact date", "date") or (s.get("created_at") or "")[:10],
                    "fields": [{"label": f["label"], "value": f["value"]} for f in fields if f["value"]]})
    _cache.update(at=time.time(), rows=out)
    return out


def check_access(user: dict):
    if user.get("role") != "admin" and user.get("user_type") not in ("hr", "support_coordinator"):
        raise HTTPException(403, "For Service & Support Coordinators and HR")


async def load_rows() -> list:
    try:
        return await fetch_rows()
    except httpx.HTTPStatusError as e:
        logger.error(f"Jotform case notes failed: HTTP {e.response.status_code}")
        if e.response.status_code in (401, 403):
            raise HTTPException(502, "The Jotform key can't read the Coordinator Case Note Form yet. Ask your admin to use a key from the account that owns that form.")
        raise HTTPException(502, "Couldn't load case notes from Jotform right now")
    except Exception as e:
        logger.error(f"Jotform case notes failed: {type(e).__name__}")
        raise HTTPException(502, "Couldn't load case notes from Jotform right now")


def participant_key(name: str) -> str:
    return name.strip().title()


@router.get("/caseload")
async def caseload(user=Depends(current_user), refresh: Optional[bool] = False):
    check_access(user)
    if not configured():
        return {"configured": False, "participants": []}
    if refresh:
        _cache["rows"] = None
        _cache.pop("team", None)
    rows = await load_rows()
    # Coordinators and HR have full access: everyone allowed here sees every participant
    people: dict = {}
    for r in rows:
        people.setdefault(participant_key(r["participant"]), []).append(r)
    out = [{"name": k, "count": len(v), "last_date": max(n["date"] for n in v),
            "notes": sorted(v, key=lambda n: (n["date"], n["created_at"] or ""), reverse=True)[:10]} for k, v in people.items()]
    return {"configured": True, "participants": sorted(out, key=lambda p: p["last_date"], reverse=True)}


SUMMARY_SYSTEM = (
    "You help NDIS Service & Support Coordinators at No Limitts catch up on a participant. From the case notes given, "
    "write a short plain-English summary (Australian English, no markdown, no asterisks) with these labelled lines: "
    "'Overview:' (2-3 sentences on where things stand), 'Recent activity:' (the latest few contacts, newest first), "
    "'Follow-ups:' (open actions, goals or risks to watch, or 'None noted'). Only use facts in the notes; never invent details."
)


class SummaryIn(BaseModel):
    name: str


@router.post("/caseload/summary")
async def caseload_summary(body: SummaryIn, user=Depends(current_user)):
    check_access(user)
    if not configured():
        raise HTTPException(400, "Jotform isn't connected yet")
    notes = [r for r in await load_rows() if participant_key(r["participant"]) == participant_key(body.name)]
    if not notes:
        raise HTTPException(404, "No case notes found for this participant")
    notes.sort(key=lambda n: (n["date"], n["created_at"] or ""), reverse=True)
    blocks, total = [], 0
    for n in notes[:20]:
        block = f"[{n['date']}] by {n['coordinator'] or 'unknown'}\n" + "\n".join(f"{f['label']}: {f['value']}" for f in n["fields"])
        total += len(block)
        if total > 40000:
            break
        blocks.append(block)
    try:
        summary = await ai_service.answer(SUMMARY_SYSTEM, f"Case notes for {participant_key(body.name)} (newest first):\n\n" + "\n\n".join(blocks))
    except Exception as e:
        logger.error(f"Caseload summary failed: {type(e).__name__}")
        raise HTTPException(502, "Couldn't summarise right now. Please try again.")
    summary = summary.replace("**", "").strip()
    await db.caseload_summaries.update_one(
        {"participant": participant_key(body.name)},
        {"$set": {"participant": participant_key(body.name), "summary": summary, "note_count": len(blocks),
                  "by": user.get("name") or "", "created_at": now_iso()}}, upsert=True)
    return {"summary": summary, "note_count": len(blocks)}


def build_summary_pdf(name: str, saved: dict, notes: list) -> bytes:
    import io
    import pymupdf
    paras = "".join(f"<p style='font-size:10px;margin:0 0 6px 0'>{escape(line)}</p>"
                    for line in saved["summary"].splitlines() if line.strip())
    rows = "".join(f"<tr><td>{dmy(n['date'])}</td><td>{escape(n['coordinator'] or '-')}</td>"
                   f"<td>{escape('; '.join(f['label'] + ': ' + f['value'] for f in n['fields'])[:400])}</td></tr>"
                   for n in notes[:10])
    html = (f"<h2 style='color:#673E8D;margin:0'>Participant summary: {escape(name)}</h2>"
            f"<p style='font-size:9px;color:#555'>Prepared for plan review · Generated {dmy(date.today().isoformat())}"
            f"{' by ' + escape(saved['by']) if saved.get('by') else ''} · based on {saved['note_count']} case note"
            f"{'s' if saved['note_count'] != 1 else ''}</p>"
            f"<h4 style='color:#673E8D'>AI summary</h4>{paras}"
            f"<p style='font-size:8px;color:#777'>Written by AI from case notes. Please check against the notes before relying on it.</p>"
            f"<h4 style='color:#673E8D'>Recent case notes</h4>"
            f"<table style='width:100%;border-collapse:collapse;font-size:8.5px' border='1' cellpadding='3'>"
            f"<tr style='background:#EFE8F5'><th>Date</th><th>Coordinator</th><th>Note</th></tr>"
            f"{rows or '<tr><td colspan=3>None</td></tr>'}</table>"
            f"<p style='font-size:8px;color:#777'>Confidential: contains participant information. No Limitts Pty Ltd.</p>")
    buf = io.BytesIO()
    writer = pymupdf.DocumentWriter(buf)
    story = pymupdf.Story(html=html)
    page, more = pymupdf.paper_rect("a4"), True
    first = True
    while more:
        dev = writer.begin_page(page)
        more, _ = story.place(page + (36, FIRST_TOP if first else 36, -36, -36))
        story.draw(dev)
        writer.end_page()
        first = False
    writer.close()
    return add_logo(buf.getvalue())


@router.get("/caseload/summary/pdf")
async def caseload_summary_pdf(name: str, request: Request, token: Optional[str] = None):
    user = await user_from_token(bearer(request) or token)
    if not user:
        raise HTTPException(401, "Please sign in again")
    check_access(user)
    key = participant_key(name)
    saved = await db.caseload_summaries.find_one({"participant": key}, {"_id": 0})
    if not saved:
        raise HTTPException(404, "Create an AI summary for this participant first")
    notes = sorted((r for r in await load_rows() if participant_key(r["participant"]) == key),
                   key=lambda n: (n["date"], n["created_at"] or ""), reverse=True)
    pdf = await run_in_threadpool(build_summary_pdf, key, saved, notes)
    fname = re.sub(r"[^A-Za-z0-9]+", "_", key).strip("_")
    return Response(content=pdf, media_type="application/pdf",
                    headers={"Content-Disposition": f'inline; filename="Participant_Summary_{fname}.pdf"'})
