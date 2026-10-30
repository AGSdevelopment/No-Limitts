"""Caseload: participants and their case notes from Jotform (Coordinator Case Note Form + Day-to-Day Support Worker case notes)."""
import asyncio
import json
import os
import re
import secrets
import time
from datetime import date, datetime, timedelta, timezone
from html import escape
from typing import List, Optional
import httpx
from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import Response
from pydantic import BaseModel
from core import bearer, current_user, db, dmy, logger, notify, now_iso, user_from_token
from email_service import send_email
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


PNAME = re.compile(r"(participant|client)(['’]s)?( full)? name|participant\(s\) involved - name", re.I)
ANAME = re.compile(r"staff name|staff member|entered by|completed by|staff involved|your name", re.I)
NAME_TYPES = ("control_fullname", "control_textbox")


def jot_base() -> str:
    return (os.environ.get("JOTFORM_BASE_URL") or "https://nolimitts.jotform.com/API").rstrip("/")  # No Limitts Enterprise API


def pick(qs: list, rx, types=NAME_TYPES) -> dict:
    return next((q for q in qs if q.get("type") in types and rx.search(q.get("text") or "")), {})


async def case_forms(c: httpx.AsyncClient, team: dict) -> list:
    """The Coordinator Case Note Form plus every Day-to-Day form that asks for a participant/client name
    (the Support Worker case notes). Cached for 30 minutes."""
    if _cache.get("forms") is not None and time.time() - _cache.get("forms_at", 0) < 1800:
        return _cache["forms"]
    base = jot_base()
    wanted = [{"form_id": FORM_ID, "title": "Coordinator Case Note", "url": f"https://nolimitts.jotform.com/{FORM_ID}",
               "kind": "coordinator"}]
    slugs = None
    async for f in db.forms.find({"category": "Day-to-Day"}, {"_id": 0, "title": 1, "url": 1}).sort("title", 1):
        last = (f.get("url") or "").rstrip("/").split("/")[-1].split("?")[0]
        if not last.isdigit():
            if slugs is None:
                r = await c.get(f"{base}/user/forms", headers=team, params={"limit": 1000})
                slugs = {x["url"].rstrip("/").split("/")[-1]: x["id"] for x in (r.json().get("content") or [])} if r.status_code == 200 else {}
            last = slugs.get(last, "")
        if last:
            wanted.append({"form_id": last, "title": f["title"], "url": f["url"], "kind": "day"})
    out = []
    for w in wanted:
        r = await c.get(f"{base}/form/{w['form_id']}/questions", headers=team)
        if r.status_code != 200:
            continue
        qs = sorted((r.json().get("content") or {}).values(), key=lambda q: int(q.get("order") or 0))
        pq = pick(qs, PNAME)
        if not pq:
            continue
        aq = pick(qs, ANAME)
        eq = next((q for q in qs if q.get("type") == "control_email" and "staff" in ((q.get("text") or "") + (q.get("name") or "")).lower()), {})
        out.append({**w, "p_name": pq.get("name"), "p_type": pq.get("type"), "a_name": aq.get("name"), "a_type": aq.get("type"),
                    "e_name": eq.get("name")})
    _cache.update(forms=out, forms_at=time.time())
    return out


async def fetch_rows() -> list:
    """Recent submissions from every case note form, cached for 5 minutes (Jotform has daily API limits)."""
    if _cache["rows"] is not None and time.time() - _cache["at"] < 300:
        return _cache["rows"]
    base = jot_base()
    out = []
    async with httpx.AsyncClient(timeout=20, headers={"APIKEY": os.environ["JOTFORM_API_KEY"].strip()}) as c:
        team = await team_header(c, base)
        for form in await case_forms(c, team):
            rows = []
            for offset in range(0, 1000, 500):
                r = await c.get(f"{base}/form/{form['form_id']}/submissions", headers=team,
                                params={"offset": offset, "limit": 500, "orderby": "created_at",
                                        "filter": json.dumps({"status:ne": "DELETED"})})
                if form["kind"] == "coordinator":
                    r.raise_for_status()
                elif r.status_code != 200:
                    break
                content = r.json().get("content") or []
                rows += content
                if len(content) < 500:
                    break
            for s in rows:
                answers = [a for a in (s.get("answers") or {}).values() if a.get("type") not in SKIP_TYPES and "answer" in a]
                named = {a.get("name"): as_text(a.get("answer")) for a in answers}
                fields = sorted(({"order": int(a.get("order") or 0), "label": (a.get("text") or a.get("name") or "").strip(),
                                  "value": as_text(a.get("answer"))} for a in answers), key=lambda f: f["order"])
                out.append({"id": s.get("id"), "created_at": s.get("created_at"), "kind": form["kind"], "source": form["title"],
                            "participant": named.get(form["p_name"]) or find(fields, "participant", "client") or "Unnamed participant",
                            "coordinator": named.get(form["a_name"]) or (find(fields, "coordinator", "your name", "completed by") if form["kind"] == "coordinator" else ""),
                            "email": named.get(form["e_name"]) or find(fields, "email"),
                            "date": find(fields, "date of contact", "contact date", "date") or (s.get("created_at") or "")[:10],
                            "fields": [{"label": f["label"], "value": f["value"]} for f in fields if f["value"]]})
    _cache.update(at=time.time(), rows=out)
    return out


def prefill(form: dict, participant: str, user: dict) -> str:
    """Form link with the participant and staff member filled in (Jotform URL prefill by field unique name)."""
    from urllib.parse import urlencode
    params: dict = {}

    def put(name, typ, value):
        if not name or not value:
            return
        if typ == "control_fullname":
            first, _, last = value.partition(" ")
            params[f"{name}[first]"], params[f"{name}[last]"] = first, last
        else:
            params[name] = value
    put(form.get("p_name"), form.get("p_type"), participant)
    put(form.get("a_name"), form.get("a_type"), user.get("name") or "")
    put(form.get("e_name"), "control_email", user.get("email") or "")
    url = form["url"]
    return f"{url}{'&' if '?' in url else '?'}{urlencode(params)}" if params else url


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
    """Match key: ignores extra spaces and capitals, so 'Pronathi  Nair' and 'pronathi nair' are the same person."""
    return " ".join((name or "").split()).casefold()


def display_name(name: str) -> str:
    n = " ".join((name or "").split())
    return n.title() if n.islower() or n.isupper() else n


def can_manage(user: dict) -> bool:
    """Service & Support Coordinators and Admins add participants and assign Support Workers."""
    return user.get("role") == "admin" or user.get("user_type") == "support_coordinator"


def is_worker(user: dict) -> bool:
    return user.get("role") != "admin" and user.get("user_type") == "support_worker"


@router.get("/caseload/forms")
async def caseload_forms(participant: str, user=Depends(current_user)):
    """Case note forms to write a note for this participant, with the participant and staff member pre-filled.
    Support Workers get the Day-to-Day case notes, and only for participants assigned to them."""
    worker = is_worker(user)
    key = participant_key(participant)
    if worker:
        if not await db.participants.find_one({"key": key, "assigned_ids": user["user_id"]}):
            raise HTTPException(403, "You're not assigned to this participant")
    else:
        check_access(user)
    if not configured():
        raise HTTPException(400, "Jotform isn't connected yet")
    async with httpx.AsyncClient(timeout=20, headers={"APIKEY": os.environ["JOTFORM_API_KEY"].strip()}) as c:
        try:
            forms = await case_forms(c, await team_header(c, jot_base()))
        except httpx.HTTPError:
            raise HTTPException(502, "Couldn't load the case note forms right now")
    from routes.forms import forms_query
    out = [{"title": f["title"], "url": prefill(f, display_name(participant), user), "kind": f["kind"], "prefilled": True}
           for f in forms if not (worker and f["kind"] != "day")]
    linked = {f["url"] for f in forms}
    # Every other Day-to-Day form the user can see (no participant field to pre-fill)
    async for f in db.forms.find({"$and": [{"category": "Day-to-Day"}, forms_query(user)]}, {"_id": 0, "title": 1, "url": 1}):
        if f.get("url") and f["url"] not in linked:
            out.append({"title": f["title"], "url": f["url"], "kind": "day", "prefilled": False})
    return sorted(out, key=lambda f: (f["kind"] != "coordinator", f["title"].lower()))


@router.get("/caseload")
async def caseload(user=Depends(current_user), refresh: Optional[bool] = False):
    """Coordinators, HR and Admins see every participant and all notes. Support Workers see only participants
    they're assigned to, and only notes written by Support Workers."""
    worker = is_worker(user)
    if not worker:
        check_access(user)
    pq = {"assigned_ids": user["user_id"]} if worker else {}
    listed = await db.participants.find(pq, {"_id": 0}).sort("name", 1).to_list(2000)
    rows = []
    if configured():
        if refresh:
            _cache["rows"] = None
            _cache.pop("team", None)
            _cache.pop("forms", None)
        rows = await load_rows()
    by_key = {p["key"]: p for p in listed}
    if worker:  # Support Workers only read Support Worker (Day-to-Day) case notes for their own participants
        rows = [r for r in rows if participant_key(r["participant"]) in by_key and r["kind"] == "day"]
    people: dict = {}
    shown: dict = {}
    for r in rows:
        people.setdefault(participant_key(r["participant"]), []).append(r)
        shown.setdefault(participant_key(r["participant"]), display_name(r["participant"]))
    for k in by_key:
        people.setdefault(k, [])
    names: dict = {}
    if not worker:
        ids = {i for p in listed for i in p.get("assigned_ids", [])}
        names = {u["user_id"]: u["name"] async for u in db.users.find({"user_id": {"$in": list(ids)}}, {"_id": 0, "user_id": 1, "name": 1})}
    out = []
    for k, v in people.items():
        p = by_key.get(k) or {}
        out.append({"name": p.get("name") or shown.get(k) or k, "participant_id": p.get("participant_id"), "count": len(v),
                    "last_date": max((n["date"] for n in v), default=""),
                    "assigned": [{"user_id": i, "name": names[i], "intro_read": i in p.get("intro_seen_ids", []),
                                  "nudged_at": (p.get("nudged_at") or {}).get(i, "")}
                                 for i in p.get("assigned_ids", []) if i in names],
                    "handover": max((n for n in v if "handover" in (n.get("source") or "").lower()),
                                    key=lambda n: (n["date"], n["created_at"] or ""), default=None),
                    "notes": sorted(v, key=lambda n: (n["date"], n["created_at"] or ""), reverse=True)[:10]})
    hids = [p["handover"]["id"] for p in out if p["handover"]]
    acks: dict = {}
    if hids:
        async for a in db.handover_acks.find({"submission_id": {"$in": hids}}, {"_id": 0}).sort("at", 1):
            acks.setdefault(a["submission_id"], []).append(a)
    for p in out:
        h = p["handover"]
        if h:
            h = p["handover"] = dict(h)  # copy: the row is shared via the 5-minute cache, don't leak per-user fields
            got = acks.get(h["id"], [])
            h["read_by_me"] = any(a["user_id"] == user["user_id"] for a in got)
            if not worker:
                done = {a["user_id"] for a in got}
                h["acks"] = [{"name": a["name"], "at": a["at"]} for a in got]
                h["waiting"] = [a["name"] for a in p["assigned"] if a["user_id"] not in done]
    out.sort(key=lambda p: (p["last_date"], p["name"]), reverse=True)
    intros = [p["participant_id"] for p in listed if worker and user["user_id"] not in p.get("intro_seen_ids", [])]
    return {"configured": configured(), "can_manage": can_manage(user), "worker": worker, "intros": intros, "participants": out}


class ParticipantIn(BaseModel):
    name: str


class AckIn(BaseModel):
    submission_id: str
    participant: str


@router.post("/caseload/handover/ack")
async def ack_handover(body: AckIn, user=Depends(current_user)):
    """'I've read it' on a shift handover, so coordinators can see who's caught up."""
    key = participant_key(body.participant)
    if is_worker(user):
        if not await db.participants.find_one({"key": key, "assigned_ids": user["user_id"]}):
            raise HTTPException(403, "You're not assigned to this participant")
    else:
        check_access(user)
    await db.handover_acks.update_one(
        {"submission_id": body.submission_id, "user_id": user["user_id"]},
        {"$setOnInsert": {"submission_id": body.submission_id, "user_id": user["user_id"], "participant": key,
                          "name": user.get("name") or "", "at": now_iso()}}, upsert=True)
    return {"ok": True}


class Contact(BaseModel):
    name: str
    relationship: Optional[str] = ""
    phone: Optional[str] = ""
    email: Optional[str] = ""


class ProfileIn(BaseModel):
    about: Optional[str] = ""
    goals: Optional[str] = ""
    support_needs: Optional[str] = ""
    communication: Optional[str] = ""
    health_alerts: Optional[str] = ""
    contacts: List[Contact] = []


PROFILE_FIELDS = ("about", "goals", "support_needs", "communication", "health_alerts")




class AssignIn(BaseModel):
    user_ids: List[str]


def manager(user=Depends(current_user)):
    if not can_manage(user):
        raise HTTPException(403, "Only Service & Support Coordinators and Admins can manage participants")
    return user


@router.post("/participants")
async def add_participant(body: ParticipantIn, user=Depends(manager)):
    name = display_name(body.name)
    if len(name) < 2:
        raise HTTPException(400, "Enter the participant's name")
    if await db.participants.find_one({"key": participant_key(name)}):
        raise HTTPException(400, f"{name} is already on the list")
    doc = {"participant_id": f"par_{secrets.token_hex(6)}", "name": name, "key": participant_key(name), "assigned_ids": [],
           "created_by": user.get("name") or "", "created_at": now_iso()}
    await db.participants.insert_one(dict(doc))
    return doc


@router.put("/participants/{participant_id}/assign")
async def assign_participant(participant_id: str, body: AssignIn, user=Depends(manager)):
    ids = list(dict.fromkeys(body.user_ids))
    valid = [u["user_id"] async for u in db.users.find({"user_id": {"$in": ids}, "user_type": "support_worker"}, {"_id": 0, "user_id": 1})]
    p = await db.participants.find_one({"participant_id": participant_id}, {"_id": 0})
    if not p:
        raise HTTPException(404, "Participant not found")
    before = set(p.get("assigned_ids", []))
    # Anyone taken off (and later re-added) gets the intro again
    seen = [i for i in p.get("intro_seen_ids", []) if i in valid]
    await db.participants.update_one({"participant_id": participant_id},
                                     {"$set": {"assigned_ids": valid, "intro_seen_ids": seen, "updated_at": now_iso()}})
    await welcome_workers([i for i in valid if i not in before], p)
    return {"assigned_ids": valid}


async def welcome_workers(user_ids: list, p: dict):
    """New Worker Intro: tell newly assigned Support Workers to read the participant's profile."""
    if user_ids:
        await notify(user_ids, "participant", f"New participant: {p['name']}",
                     f"You've been assigned to support {p['name']}. Read their profile before your first shift.",
                     f"/participant/{p['participant_id']}")


class NudgeIn(BaseModel):
    user_id: str


@router.post("/participants/{participant_id}/nudge")
async def nudge_intro(participant_id: str, body: NudgeIn, user=Depends(manager)):
    """Remind an assigned Support Worker to read the participant intro (once a day per worker)."""
    p = await db.participants.find_one({"participant_id": participant_id}, {"_id": 0})
    if not p or body.user_id not in p.get("assigned_ids", []):
        raise HTTPException(404, "That Support Worker isn't assigned to this participant")
    if body.user_id in p.get("intro_seen_ids", []):
        raise HTTPException(400, "They've already read the intro")
    last = (p.get("nudged_at") or {}).get(body.user_id, "")
    if last and datetime.fromisoformat(last) > datetime.now(timezone.utc) - timedelta(hours=24):
        raise HTTPException(429, "Already reminded in the last 24 hours")
    await notify([body.user_id], "participant", f"Reminder: meet {p['name']}",
                 f"{user.get('name') or 'Your coordinator'} asked you to read {p['name']}'s profile before your next shift.",
                 f"/participant/{participant_id}")
    at = now_iso()
    await db.participants.update_one({"participant_id": participant_id}, {"$set": {f"nudged_at.{body.user_id}": at}})
    return {"nudged_at": at}


@router.post("/participants/{participant_id}/intro-seen")
async def intro_seen(participant_id: str, user=Depends(current_user)):
    await db.participants.update_one({"participant_id": participant_id, "assigned_ids": user["user_id"]},
                                     {"$addToSet": {"intro_seen_ids": user["user_id"]}})
    return {"ok": True}


@router.post("/participants/import")
async def import_participants(file: UploadFile = File(...), user=Depends(manager)):
    """Bulk add participants and assign Support Workers from an Excel/CSV sheet: 'Participant name' plus an optional
    'Support Workers' column (emails or full names, separated by commas). Workers are added to existing assignments."""
    from routes.users import read_rows
    data = await file.read()
    if len(data) > 5 * 1024 * 1024:
        raise HTTPException(413, "File too large (max 5 MB)")
    try:
        rows = await run_in_threadpool(read_rows, file.filename or "", data)
    except Exception:
        raise HTTPException(400, "Couldn't read that file. Upload an Excel (.xlsx) or CSV file")
    rows = [r for r in rows if any(str(c or "").strip() for c in r)]
    if len(rows) < 2:
        raise HTTPException(400, "The sheet needs a header row and at least one participant")
    if len(rows) > 1001:
        raise HTTPException(400, "Import up to 1000 participants at a time")
    header = [" ".join(str(c or "").lower().split()) for c in rows[0]]
    pcol = next((i for i, h in enumerate(header) if h in ("participant name", "participant", "client name", "client", "name")), None)
    wcol = next((i for i, h in enumerate(header) if "worker" in h or h in ("assigned to", "staff")), None)
    if pcol is None:
        raise HTTPException(400, "Couldn't find a 'Participant name' column in the first row")
    workers = await db.users.find({"user_type": "support_worker"}, {"_id": 0, "user_id": 1, "name": 1, "email": 1}).to_list(5000)
    lookup = {}
    for w in workers:
        lookup[participant_key(w["name"])] = w
        if w.get("email"):
            lookup[w["email"].lower()] = w
    added, updated, skipped = [], [], []
    for n, r in enumerate(rows[1:], start=2):
        name = display_name(str(r[pcol] if pcol < len(r) else "") or "")
        if len(name) < 2:
            skipped.append({"row": n, "name": name, "reason": "Missing participant name"})
            continue
        raw = str(r[wcol] if wcol is not None and wcol < len(r) and r[wcol] else "")
        ids, unknown = [], []
        for part in re.split(r"[,;\n]+", raw):
            part = part.strip()
            if not part:
                continue
            w = lookup.get(part.lower()) or lookup.get(participant_key(part))
            (ids.append(w["user_id"]) if w else unknown.append(part))
        key = participant_key(name)
        existing = await db.participants.find_one({"key": key}, {"_id": 0})
        if existing:
            new_ids = list(dict.fromkeys(existing.get("assigned_ids", []) + ids))
            await db.participants.update_one({"key": key}, {"$set": {"assigned_ids": new_ids, "updated_at": now_iso()}})
            await welcome_workers([i for i in new_ids if i not in existing.get("assigned_ids", [])], existing)
            updated.append({"row": n, "name": existing["name"], "assigned": len(new_ids), "unknown": unknown})
        else:
            doc = {"participant_id": f"par_{secrets.token_hex(6)}", "name": name, "key": key,
                   "assigned_ids": list(dict.fromkeys(ids)), "created_by": user.get("name") or "", "created_at": now_iso()}
            await db.participants.insert_one(dict(doc))
            await welcome_workers(doc["assigned_ids"], doc)
            added.append({"row": n, "name": name, "assigned": len(set(ids)), "unknown": unknown})
    return {"added": added, "updated": updated, "skipped": skipped}


@router.get("/participants/import-template")
async def participants_template(request: Request, token: Optional[str] = None):
    user = await user_from_token(bearer(request) or token)
    if not user or not can_manage(user):
        raise HTTPException(403, "Only Service & Support Coordinators and Admins")
    import io
    import openpyxl
    from openpyxl.styles import Font, PatternFill
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Participants"
    ws.append(["Participant name", "Support Workers"])
    ws.append(["Jane Example", "sam.example@gmail.com, Alex Sample"])
    ws.append(["Chris Sample", ""])
    for c in ws[1]:
        c.font, c.fill = Font(bold=True, color="FFFFFF"), PatternFill("solid", fgColor="673E8D")
    ws.column_dimensions["A"].width, ws.column_dimensions["B"].width = 28, 60
    info = wb.create_sheet("How to fill this in")
    for row in [["Column", "Required?", "What to enter"],
                ["Participant name", "Yes", "Full name, the same as on case notes"],
                ["Support Workers", "No", "Support Workers' emails or full names, separated by commas"],
                [], ["Participants already in the app keep their Support Workers; anyone listed is added."],
                ["Delete the example rows before importing. Only the first sheet is read."]]:
        info.append(row)
    info.column_dimensions["A"].width, info.column_dimensions["C"].width = 18, 80
    buf = io.BytesIO()
    wb.save(buf)
    return Response(content=buf.getvalue(), media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    headers={"Content-Disposition": 'attachment; filename="No Limitts participants template.xlsx"'})


@router.get("/participants/export")
async def export_participants(request: Request, token: Optional[str] = None):
    """Spreadsheet of who's assigned to which participant (for rostering)."""
    user = await user_from_token(bearer(request) or token)
    if not user or not can_manage(user):
        raise HTTPException(403, "Only Service & Support Coordinators and Admins")
    import io
    import openpyxl
    from openpyxl.styles import Font, PatternFill
    listed = await db.participants.find({}, {"_id": 0}).sort("name", 1).to_list(5000)
    ids = list({i for p in listed for i in p.get("assigned_ids", [])})
    staff = {u["user_id"]: u async for u in db.users.find({"user_id": {"$in": ids}}, {"_id": 0, "user_id": 1, "name": 1, "email": 1, "phone": 1})}
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "By participant"
    ws.append(["Participant", "Support Workers", "Number assigned", "Added"])
    for p in listed:
        names = [staff[i]["name"] for i in p.get("assigned_ids", []) if i in staff]
        ws.append([p["name"], ", ".join(names), len(names), dmy((p.get("created_at") or "")[:10]) if p.get("created_at") else ""])
    ws2 = wb.create_sheet("By Support Worker")
    ws2.append(["Support Worker", "Email", "Phone", "Participants", "Number of participants"])
    for uid, u in sorted(staff.items(), key=lambda x: x[1]["name"].lower()):
        mine = [p["name"] for p in listed if uid in p.get("assigned_ids", [])]
        ws2.append([u["name"], u.get("email") or "", u.get("phone") or "", ", ".join(mine), len(mine)])
    for sheet, widths in ((ws, (30, 70, 16, 14)), (ws2, (28, 34, 16, 70, 22))):
        for c in sheet[1]:
            c.font, c.fill = Font(bold=True, color="FFFFFF"), PatternFill("solid", fgColor="673E8D")
        for col, w in zip("ABCDE", widths):
            sheet.column_dimensions[col].width = w
        sheet.freeze_panes = "A2"
    buf = io.BytesIO()
    wb.save(buf)
    return Response(content=buf.getvalue(), media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    headers={"Content-Disposition": f'attachment; filename="No Limitts assignments {date.today().isoformat()}.xlsx"'})


async def check_new_handovers():
    """Alert assigned Support Workers in-app when a new Shift Handover is submitted for their participant."""
    base = jot_base()
    async with httpx.AsyncClient(timeout=20, headers={"APIKEY": os.environ["JOTFORM_API_KEY"].strip()}) as c:
        team = await team_header(c, base)
        forms = [f for f in await case_forms(c, team) if f["kind"] == "day" and "handover" in f["title"].lower()]
        for form in forms:
            r = await c.get(f"{base}/form/{form['form_id']}/submissions", headers=team,
                            params={"limit": 100, "orderby": "created_at", "filter": json.dumps({"status:ne": "DELETED"})})
            if r.status_code != 200:
                continue
            subs = r.json().get("content") or []
            seen_key = f"handover_seen_{form['form_id']}"
            meta = await db.meta.find_one({"key": seen_key})
            seen = set(meta.get("ids", [])) if meta else None
            ids = [s.get("id") for s in subs]
            if seen is not None:
                for s in subs:
                    if s.get("id") in seen:
                        continue
                    named = {a.get("name"): as_text(a.get("answer")) for a in (s.get("answers") or {}).values() if "answer" in a}
                    who = named.get(form["p_name"]) or ""
                    p = await db.participants.find_one({"key": participant_key(who)}, {"_id": 0}) if who else None
                    if not p or not p.get("assigned_ids"):
                        continue
                    author_email = (named.get(form["e_name"]) or "").lower()
                    author = named.get(form["a_name"]) or "A Support Worker"
                    targets = [u["user_id"] async for u in db.users.find({"user_id": {"$in": p["assigned_ids"]}}, {"_id": 0, "user_id": 1, "email": 1})
                               if (u.get("email") or "").lower() != author_email or not author_email]
                    await notify(targets, "handover", f"New shift handover: {p['name']}",
                                 f"{author} posted a shift handover. Read it before your shift.", "/caseload")
            keep = list(dict.fromkeys(ids + list(seen or [])))[:500]
            await db.meta.update_one({"key": seen_key}, {"$set": {"key": seen_key, "ids": keep, "updated_at": now_iso()}}, upsert=True)


async def handover_alert_loop():
    await asyncio.sleep(60)
    while True:
        if configured():
            try:
                await check_new_handovers()
            except Exception as e:
                logger.error(f"Handover alert check failed: {type(e).__name__}: {e}")
        await asyncio.sleep(600)


@router.delete("/participants/{participant_id}")
async def remove_participant(participant_id: str, user=Depends(manager)):
    p = await db.participants.find_one_and_delete({"participant_id": participant_id})
    if not p:
        raise HTTPException(404, "Participant not found")
    key = p.get("key") or participant_key(p["name"])
    await db.caseload_summaries.delete_many({"participant": key})
    await db.caseload_shares.delete_many({"participant": key})
    await db.handover_acks.delete_many({"participant": key})
    return {"ok": True}


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
        summary = await ai_service.answer(SUMMARY_SYSTEM, f"Case notes for {display_name(body.name)} (newest first):\n\n" + "\n\n".join(blocks))
    except Exception as e:
        logger.error(f"Caseload summary failed: {type(e).__name__}")
        raise HTTPException(502, "Couldn't summarise right now. Please try again.")
    summary = summary.replace("**", "").strip()
    await db.caseload_summaries.update_one(
        {"participant": participant_key(body.name)},
        {"$set": {"participant": participant_key(body.name), "display": display_name(body.name), "summary": summary, "note_count": len(blocks),
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
    shown = saved.get("display") or display_name(name)
    pdf = await run_in_threadpool(build_summary_pdf, shown, saved, notes)
    fname = re.sub(r"[^A-Za-z0-9]+", "_", shown).strip("_")
    return Response(content=pdf, media_type="application/pdf",
                    headers={"Content-Disposition": f'inline; filename="Participant_Summary_{fname}.pdf"'})


class EmailIn(BaseModel):
    name: str
    user_ids: List[str]


@router.post("/caseload/summary/email")
async def email_summary(body: EmailIn, user=Depends(current_user)):
    """Email the plan review PDF to chosen No Limitts staff. Recipients come from staff records (never typed addresses);
    each gets a private link that opens the PDF for 7 days."""
    check_access(user)
    key = participant_key(body.name)
    ids = list(dict.fromkeys(body.user_ids))[:15]
    if not ids:
        raise HTTPException(400, "Choose at least one team member")
    saved = await db.caseload_summaries.find_one({"participant": key}, {"_id": 0})
    if not saved:
        raise HTTPException(404, "Create an AI summary for this participant first")
    staff = await db.users.find({"user_id": {"$in": ids}, "email": {"$nin": [None, ""]}},
                                {"_id": 0, "user_id": 1, "name": 1, "email": 1}).to_list(15)
    if not staff:
        raise HTTPException(400, "None of the people you chose have an email address on file")
    shown = saved.get("display") or display_name(body.name)
    base = (os.environ.get("PUBLIC_BACKEND_URL") or "").rstrip("/")
    expires = datetime.now(timezone.utc) + timedelta(days=7)
    sent = []
    for s in staff:
        token = secrets.token_urlsafe(24)
        await db.caseload_shares.insert_one({"token": token, "participant": key, "recipient_id": s["user_id"],
                                             "sent_by": user.get("name") or "", "expires_at": expires.isoformat(),
                                             "created_at": now_iso()})
        link = f"{base}/api/caseload/shared/{token}"
        html = (f'<table role="presentation" width="100%"><tr><td style="padding:24px;font-family:Arial,sans-serif;color:#11181C">'
                f'<p>Hi {escape(s["name"].split(" ")[0])},</p>'
                f'<p>{escape(user.get("name") or "A coordinator")} shared the plan review summary for '
                f'<strong>{escape(shown)}</strong> with you.</p>'
                f'<p><a href="{escape(link)}" style="display:inline-block;background:#673E8D;color:#ffffff;padding:12px 20px;'
                f'border-radius:10px;text-decoration:none;font-weight:bold">Open the summary (PDF)</a></p>'
                f'<p style="font-size:13px;color:#555">This private link works for 7 days. It contains participant information, '
                f'so please don\'t forward it.</p>'
                f'<p style="font-size:12px;color:#888">Sent by {escape(os.environ.get("EMAIL_FROM_NAME") or "No Limitts")}.</p>'
                f'</td></tr></table>')
        if await send_email(to=s["email"], subject=f"Plan review summary: {shown}", html=html):
            sent.append(s["name"])
    if not sent:
        raise HTTPException(502, "Couldn't send the email right now. Please try again.")
    return {"sent": sent}


@router.get("/caseload/shared/{token}")
async def shared_summary_pdf(token: str):
    share = await db.caseload_shares.find_one({"token": token}, {"_id": 0})
    if not share or share["expires_at"] < datetime.now(timezone.utc).isoformat():
        raise HTTPException(404, "This link has expired. Ask the coordinator to send it again.")
    saved = await db.caseload_summaries.find_one({"participant": share["participant"]}, {"_id": 0})
    if not saved:
        raise HTTPException(404, "This summary is no longer available")
    try:
        notes = [r for r in await load_rows() if participant_key(r["participant"]) == share["participant"]]
    except HTTPException:
        notes = []
    notes.sort(key=lambda n: (n["date"], n["created_at"] or ""), reverse=True)
    shown = saved.get("display") or display_name(share["participant"])
    pdf = await run_in_threadpool(build_summary_pdf, shown, saved, notes)
    fname = re.sub(r"[^A-Za-z0-9]+", "_", shown).strip("_")
    return Response(content=pdf, media_type="application/pdf",
                    headers={"Content-Disposition": f'inline; filename="Participant_Summary_{fname}.pdf"'})


@router.get("/participants/{participant_id}")
async def get_participant(participant_id: str, user=Depends(current_user)):
    p = await db.participants.find_one({"participant_id": participant_id}, {"_id": 0})
    if not p:
        raise HTTPException(404, "Participant not found")
    if is_worker(user):
        if user["user_id"] not in p.get("assigned_ids", []):
            raise HTTPException(403, "You're not assigned to this participant")
    else:
        check_access(user)
    names = {u["user_id"]: u["name"] async for u in db.users.find({"user_id": {"$in": p.get("assigned_ids", [])}}, {"_id": 0, "user_id": 1, "name": 1})}
    prof = p.get("profile") or {}
    return {"participant_id": p["participant_id"], "name": p["name"], "can_edit": can_manage(user),
            "assigned": [names[i] for i in p.get("assigned_ids", []) if i in names],
            "intro_status": [{"user_id": i, "name": names[i], "read": i in p.get("intro_seen_ids", []),
                              "nudged_at": (p.get("nudged_at") or {}).get(i, "")}
                             for i in p.get("assigned_ids", []) if i in names] if can_manage(user) else [],
            "profile": {**{k: prof.get(k, "") for k in PROFILE_FIELDS}, "contacts": prof.get("contacts", []),
                        "updated_by": prof.get("updated_by", ""), "updated_at": prof.get("updated_at", "")}}


@router.put("/participants/{participant_id}/profile")
async def save_profile(participant_id: str, body: ProfileIn, user=Depends(manager)):
    data = {k: (getattr(body, k) or "").strip()[:4000] for k in PROFILE_FIELDS}
    data["contacts"] = [{k: (v or "").strip()[:200] for k, v in c.model_dump().items()} for c in body.contacts[:20] if c.name.strip()]
    data.update(updated_by=user.get("name") or "", updated_at=now_iso())
    res = await db.participants.update_one({"participant_id": participant_id}, {"$set": {"profile": data}})
    if not res.matched_count:
        raise HTTPException(404, "Participant not found")
    return data


PROFILE_SYSTEM = (
    "You help NDIS Service & Support Coordinators at No Limitts write a participant profile for new Support Workers, "
    "using only facts in the case notes provided. Reply with JSON only, no markdown, in this shape: "
    '{"about": "", "goals": "", "support_needs": "", "communication": "", "health_alerts": "", '
    '"contacts": [{"name": "", "relationship": "", "phone": "", "email": ""}]}. '
    "about: interests, likes/dislikes, what a good day looks like. goals: NDIS goals they're working towards. "
    "support_needs: routines and how to support them. communication: how they communicate and what helps. "
    "health_alerts: allergies, conditions, risks, behaviours of concern. contacts: family, carers or professionals named "
    "with their role. Use short plain Australian English sentences, one point per line starting with '- ' when listing. "
    "Leave a field as an empty string if the notes don't mention it. Never invent details, phone numbers or emails."
)


@router.post("/participants/{participant_id}/profile/draft")
async def draft_profile(participant_id: str, user=Depends(manager)):
    """AI first draft of a participant profile from their case notes. Not saved: the coordinator reviews and saves."""
    p = await db.participants.find_one({"participant_id": participant_id}, {"_id": 0})
    if not p:
        raise HTTPException(404, "Participant not found")
    if not configured():
        raise HTTPException(400, "Jotform isn't connected yet")
    notes = sorted((r for r in await load_rows() if participant_key(r["participant"]) == p["key"]),
                   key=lambda n: (n["date"], n["created_at"] or ""), reverse=True)
    if not notes:
        raise HTTPException(404, f"No case notes found for {p['name']} yet")
    blocks, total = [], 0
    for n in notes[:30]:
        block = f"[{n['date']}] {n['source']}\n" + "\n".join(f"{f['label']}: {f['value']}" for f in n["fields"])
        total += len(block)
        if total > 45000:
            break
        blocks.append(block)
    try:
        raw = await ai_service.answer(PROFILE_SYSTEM, f"Case notes for {p['name']} (newest first):\n\n" + "\n\n".join(blocks))
        m = re.search(r"\{.*\}", raw, re.S)
        data = json.loads(m.group(0)) if m else {}
    except Exception as e:
        logger.error(f"Profile draft failed: {type(e).__name__}")
        raise HTTPException(502, "Couldn't write a draft right now. Please try again.")
    out = {k: str(data.get(k) or "").replace("**", "").strip()[:4000] for k in PROFILE_FIELDS}
    out["contacts"] = [{k: str(c.get(k) or "").strip()[:200] for k in ("name", "relationship", "phone", "email")}
                       for c in (data.get("contacts") or [])[:20] if isinstance(c, dict) and str(c.get("name") or "").strip()]
    out["note_count"] = len(blocks)
    return out
