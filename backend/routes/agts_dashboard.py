"""AGTS Therapist Performance Dashboard inside No Limitts.

Runs the team's own dashboard engine (assets/therapist-dashboard.html, unchanged logic) with a phone-first
stylesheet, and plays the role of the Wix page: data is read from / saved to the same Wix CMS collection
(`TherapistDashboard`) so updates made on the website show here and vice versa. Admins only.
Until WIX_API_KEY + WIX_SITE_ID are set, data is kept in No Limitts (`agts_dashboard_parts`)."""
import asyncio
import json
import os
import re
from pathlib import Path
from typing import Optional
import httpx
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
from core import P, bearer, db, executive_user, is_executive, logger, now_iso, spawn, user_from_token

router = APIRouter(prefix="/api")
COLLECTION = "TherapistDashboard"
PARTS = ["billing", "participants", "settings", "preview"]
ENGINE = Path(__file__).resolve().parent.parent / "assets" / "therapist-dashboard.html"
WIX = "https://www.wixapis.com/wix-data/v2/items"


def wix_headers() -> Optional[dict]:
    key, site = os.environ.get("WIX_API_KEY", "").strip(), os.environ.get("WIX_SITE_ID", "").strip()
    return {"Authorization": key, "wix-site-id": site, "Content-Type": "application/json"} if key and site else None


async def require_admin_token(request: Request, token: Optional[str]) -> dict:
    """The full Therapist dashboard: Executives only."""
    user = await user_from_token(bearer(request) or token)
    if not user:
        raise HTTPException(401, "Not authenticated")
    if not is_executive(user):
        raise HTTPException(403, "Executives only")
    return user


async def require_view(request: Request, token: Optional[str], view: str, page: str = "participant-plans") -> dict:
    """view='nk' is the Participant plans & safety page: only people the dashboard is shared with (Nikki)."""
    if view != "nk":
        return await require_admin_token(request, token)
    from routes.dashboards import allowed
    user = await user_from_token(bearer(request) or token)
    if not user:
        raise HTTPException(401, "Not authenticated")
    d = await db.dashboards.find_one({"dashboard_id": page or "participant-plans", "embed": "agts-nk"}, P)
    if not d or not allowed(d, user):
        raise HTTPException(403, "Not available for your account")
    user["_plans_tag"] = d.get("tag") or ""
    return user


async def read_part(client: Optional[httpx.AsyncClient], part: str) -> Optional[dict]:
    h = wix_headers()
    if h:
        r = await client.get(f"{WIX}/{part}", params={"dataCollectionId": COLLECTION, "consistentRead": "true"}, headers=h)
        if r.status_code == 404:
            return None
        if r.status_code != 200:
            raise HTTPException(502, f"Wix said {r.status_code}: {r.text[:200]}")
        d = (r.json().get("dataItem") or {}).get("data") or {}
        upd = d.get("_updatedDate")
        return {"data": d.get("data"), "updatedBy": d.get("updatedBy"), "updated": upd.get("$date") if isinstance(upd, dict) else upd}
    doc = await db.agts_dashboard_parts.find_one({"part": part}, P)
    return {"data": doc["data"], "updatedBy": doc.get("updatedBy"), "updated": doc.get("updated")} if doc else None


async def write_part(part: str, data: str, email: str):
    h = wix_headers()
    if h:
        item = {"id": part, "data": {"_id": part, "title": part, "data": data, "updatedBy": email}}
        async with httpx.AsyncClient(timeout=30) as client:
            r = await client.post(f"{WIX}/save", json={"dataCollectionId": COLLECTION, "dataItem": item}, headers=h)
        if r.status_code != 200:
            logger.error(f"Wix save failed {r.status_code}: {r.text[:300]}")
            raise HTTPException(502, f"Could not save to Wix ({r.status_code})")
    else:
        await db.agts_dashboard_parts.update_one({"part": part}, {"$set": {"data": data, "updatedBy": email, "updated": now_iso()}}, upsert=True)
    return {"updated": now_iso(), "updatedBy": email}


@router.get("/agts-dashboard/data")
async def dashboard_data(request: Request, token: Optional[str] = None, view: str = "", page: str = "participant-plans"):
    user = await require_view(request, token, view, page)
    async with httpx.AsyncClient(timeout=30) as client:
        out = {"user": user["email"], "source": "wix" if wix_headers() else "staffhub"}
        if view == "nk":  # only Nikki's participant data, never billing, pay or bonus figures
            prev = await read_part(client, "preview")
            nk = (json.loads(prev["data"]).get("nikki") if prev and prev.get("data") else None) or {}
            if user.get("_plans_tag"):  # a therapist's own page: send only participants (and their forms) with their tag
                nk = own_participants(nk, user["_plans_tag"])
            nk = {**nk, "booked": await booked_map(nk.get("clients") or [])}
            out.update({p: None for p in PARTS})
            out["preview"] = {"data": json.dumps({"weeks": {}, "nikki": nk or {}}), "updatedBy": (prev or {}).get("updatedBy"),
                              "updated": (prev or {}).get("updated")}
            return out
        for p in PARTS:
            out[p] = await read_part(client, p)
    return out


class SaveIn(BaseModel):
    part: str
    json: str


@router.post("/agts-dashboard/save")
async def dashboard_save(body: SaveIn, request: Request, view: str = "", page: str = "participant-plans"):
    user = await require_view(request, None, view, page)
    if body.part not in PARTS:
        raise HTTPException(400, "Unknown data type.")
    if len(body.json) > 480000:
        raise HTTPException(400, "The data is too large to save.")
    if view == "nk":
        if body.part != "preview":
            raise HTTPException(403, "Only participant plan data can be saved here")
        if user.get("_plans_tag"):  # therapist pages are view-only: an upload there would replace everyone's shared list
            raise HTTPException(403, "This page is view-only. Plan data is uploaded on the main plans page.")
        # merge just the Nikki section into the shared record so nothing else is overwritten
        async with httpx.AsyncClient(timeout=30) as client:
            prev = await read_part(client, "preview")
        full = json.loads(prev["data"]) if prev and prev.get("data") else {}
        full["nikki"] = json.loads(body.json).get("nikki") or {}
        full["nikki"].pop("booked", None)  # booked ticks live in No Limitts, not in the shared Wix record
        return await write_part("preview", json.dumps(full, separators=(",", ":")), user["email"])
    return await write_part(body.part, body.json, user["email"])


def own_participants(nk: dict, tag: str) -> dict:
    """Plans data for one therapist's page: only their tagged, active participants and those participants' forms."""
    t = tag.lower()
    clients = [c for c in nk.get("clients") or [] if not c.get("archived") and t in (c.get("tags") or "").lower()]
    names = set()
    for c in clients:
        n = (c.get("name") or "").lower()
        names.add(n)
        if c.get("pref") and n:
            names.add(f"{c['pref']} {n.split(' ')[-1]}".lower())
    forms = [f for f in nk.get("forms") or [] if (f.get("p") or "").lower() in names]
    return {**nk, "clients": clients, "forms": forms, "cfg": {**(nk.get("cfg") or {}), "tag": tag}}


def _addmonths(serial: int, months: int) -> int:
    from datetime import date, timedelta
    import calendar
    d = date(1899, 12, 30) + timedelta(days=int(serial))
    m = d.month - 1 + months
    y, m = d.year + m // 12, m % 12 + 1
    return (date(y, m, min(d.day, calendar.monthrange(y, m)[1])) - date(1899, 12, 30)).days


def _fmt(serial: int) -> str:
    from datetime import date, timedelta
    return (date(1899, 12, 30) + timedelta(days=int(serial))).strftime("%d %b %Y")


async def sync_plan_pages(nk: dict):
    """One private 'My participant plans' page per therapist tag found in the client list ("<Name>'s Clients"),
    shared only with the No Limitts user whose first name matches (skipped when the name is ambiguous)."""
    import re
    tags = set()
    for c in nk.get("clients") or []:
        for t in (c.get("tags") or "").split(","):
            m = re.match(r"^\s*(.+?)['’]s Clients\s*$", t)
            if m:
                tags.add(m.group(1).strip())
    users = await db.users.find({"hidden": {"$ne": True}}, {"_id": 0, "user_id": 1, "name": 1}).to_list(2000)
    for name in tags:
        if name.lower() == "nikki":
            continue  # Nikki keeps the original page
        match = [u for u in users if (u.get("name") or "").split(" ")[0].lower() == name.lower()]
        if len(match) != 1:
            continue
        did = f"plans-{re.sub(r'[^a-z0-9]+', '-', name.lower()).strip('-')}"
        await db.dashboards.update_one({"dashboard_id": did}, {"$set": {
            "name": "My participant plans", "url": "", "roles": [], "groups": [], "embed": "agts-nk",
            "users": [match[0]["user_id"]], "tag": f"{name}'s Clients"}, "$setOnInsert": {"created_at": now_iso()}}, upsert=True)


async def plan_alerts():
    """For every private plans page: plan ending within 30 days, plan review overdue, risk assessment out of date.
    Each alert is sent once (per participant + date) to the page's owner."""
    from datetime import date, datetime
    from core import DIGEST_TZ, notify
    async with httpx.AsyncClient(timeout=30) as client:
        prev = await read_part(client, "preview")
    if not prev or not prev.get("data"):
        return
    nk = json.loads(prev["data"]).get("nikki") or {}
    await sync_plan_pages(nk)
    cfg = {"tag": "Nikki's Clients", "months": 3, "formAge": 12, **(nk.get("cfg") or {})}
    today = (datetime.now(DIGEST_TZ).date() - date(1899, 12, 30)).days
    forms = {}
    for f in nk.get("forms") or []:
        forms.setdefault(str(f.get("p", "")).strip().lower(), []).append(f)
    booked = await booked_map()
    pages = await db.dashboards.find({"embed": "agts-nk"}, P).to_list(100)
    for pg in pages:
        ids, tag = pg.get("users") or [], (pg.get("tag") or cfg["tag"]).lower()
        if not ids:
            continue
        link = f"/dashboard/{pg['dashboard_id']}"

        async def once(key, title, body):
            if not await db.meta.find_one({"key": key}):
                await db.meta.insert_one({"key": key, "created_at": now_iso()})
                await notify(ids, "dashboard", title, body, link)
        for c in nk.get("clients") or []:
            end = c.get("end")
            if c.get("archived") or tag not in (c.get("tags") or "").lower() or not isinstance(end, (int, float)):
                continue
            end, name = int(end), c["name"]
            d_end = end - today
            if d_end < 0:
                continue
            k = f"{pg['dashboard_id']}_{name}"
            if d_end <= 30:
                await once(f"agts_plan_end_{name}_{end}" if pg["dashboard_id"] == "participant-plans" else f"agts_plan_end_{k}_{end}",
                           f"Plan ending soon: {name}", f"Their plan ends {_fmt(end)} ({d_end} day{'s' if d_end != 1 else ''}). Time to check the plan review.")
            else:
                rev = _addmonths(end, -int(cfg["months"]))
                if rev <= today and _bkey(name, end) not in booked:
                    await once(f"agts_review_{k}_{rev}", f"Plan review overdue: {name}",
                               f"The plan review was due {_fmt(rev)} (plan ends {_fmt(end)}).")
            for t, (st, f) in form_status(c, forms, cfg, today).items():
                lab = FORM_LABEL[t]
                if st == "missing":
                    await once(f"agts_{t}_missing_{k}", f"{lab} missing: {name}",
                               f"There's no {lab.lower()} on file for {name}. Please complete one.")
                elif st == "incomplete":
                    await once(f"agts_{t}_incomplete_{k}_{f.get('c') or f.get('u') or 0}", f"{lab} not completed: {name}",
                               f"The latest {lab.lower()} is marked \"{f.get('st') or 'not complete'}\". Please finish it.")
                elif st == "old":
                    done = f.get("u") or f.get("c")
                    await once(f"agts_ra_{k}_{done}" if t == "ra" else f"agts_{t}_{k}_{done}", f"{lab} out of date: {name}",
                               f"Last completed {_fmt(done)}, over {cfg['formAge']} months ago. Please complete a new one.")


FORM_LABEL = {"ra": "Risk assessment", "pep": "Personal emergency plan"}


def _bkey(name: str, end) -> str:
    return f"{str(name).strip().lower()}|{int(end)}"


async def booked_map(clients: Optional[list] = None) -> dict:
    """Plan reviews marked as booked: {name|plan end: {by, at}}; limited to the given clients when passed."""
    keys = None if clients is None else {_bkey(c.get("name", ""), c["end"]) for c in clients if isinstance(c.get("end"), (int, float))}
    docs = await db.plan_reviews_booked.find({}, P).to_list(5000)
    return {d["key"]: {"by": d.get("booked_by_name", ""), "at": d.get("booked_at", ""), "date": d.get("review_date")}
            for d in docs if keys is None or d["key"] in keys}


def form_status(c: dict, forms: dict, cfg: dict, today: int) -> dict:
    """Latest risk assessment / personal emergency plan per participant: missing, incomplete, old or ok (same rules as the page)."""
    last = (c.get("name") or "").split(" ")[-1]
    mine = forms.get((c.get("name") or "").strip().lower(), []) + (forms.get(f"{c['pref']} {last}".strip().lower(), []) if c.get("pref") else [])
    out = {}
    for t in ("ra", "pep"):
        fs = sorted([f for f in mine if f.get("t") == t], key=lambda f: f.get("u") or f.get("c") or 0, reverse=True)
        f = fs[0] if fs else None
        s = str((f or {}).get("st", "")).lower()
        if not f:
            out[t] = ("missing", None)
        elif "complete" not in s or "incomplete" in s:
            out[t] = ("incomplete", f)
        elif today - (f.get("u") or f.get("c") or today) > float(cfg["formAge"]) * 30.4:
            out[t] = ("old", f)
        else:
            out[t] = ("ok", f)
    return out


async def plans_context():
    """(nk, cfg, today, [(page, rows)]) for every plans page with owners; rows hold what the email and calendar need."""
    async with httpx.AsyncClient(timeout=30) as client:
        prev = await read_part(client, "preview")
    if not prev or not prev.get("data"):
        return None
    nk = json.loads(prev["data"]).get("nikki") or {}
    cfg = {"tag": "Nikki's Clients", "months": 3, "formAge": 12, **(nk.get("cfg") or {})}
    today = _today_serial()
    forms = {}
    for f in nk.get("forms") or []:
        forms.setdefault(str(f.get("p", "")).strip().lower(), []).append(f)
    booked = await booked_map()
    out = []
    for pg in await db.dashboards.find({"embed": "agts-nk"}, P).to_list(100):
        tag = (pg.get("tag") or cfg["tag"]).lower()
        rows = []
        for c in nk.get("clients") or []:
            end = c.get("end")
            if c.get("archived") or tag not in (c.get("tags") or "").lower() or not isinstance(end, (int, float)):
                continue
            end = int(end)
            bk = booked.get(_bkey(c["name"], end))
            rows.append({"name": c["name"], "end": end, "rev": _addmonths(end, -int(cfg["months"])),
                         "booked": bool(bk), "booked_date": (bk or {}).get("date"), "forms": form_status(c, forms, cfg, today)})
        out.append((pg, rows))
    return nk, cfg, today, out


def _today_serial() -> int:
    from datetime import date, datetime
    from core import DIGEST_TZ
    return (datetime.now(DIGEST_TZ).date() - date(1899, 12, 30)).days


# ---- Monday plans email
def plans_email(first: str, rows: list, today: int) -> Optional[tuple]:
    """(subject, html) summary of one therapist's plans for this calendar month; None when nothing needs doing."""
    from datetime import date, timedelta
    import calendar
    from html import escape
    d = date(1899, 12, 30) + timedelta(days=today)
    month_end = today + calendar.monthrange(d.year, d.month)[1] - d.day
    live = [r for r in rows if r["end"] >= today]
    overdue = sorted([r for r in live if r["rev"] < today and not r["booked"] and r["end"] > month_end], key=lambda r: r["rev"])
    due = sorted([r for r in live if today <= r["rev"] <= month_end and not r["booked"] and r["end"] > month_end], key=lambda r: r["rev"])
    ending = sorted([r for r in live if r["end"] <= month_end], key=lambda r: r["end"])
    booked = sorted([r for r in live if r["booked"] and r.get("booked_date") is not None and today <= r["booked_date"] <= month_end],
                    key=lambda r: r["booked_date"])
    word = {"missing": "missing", "incomplete": "not completed", "old": "out of date"}
    forms = [(r, [f"{FORM_LABEL[t]} {word[s]}" for t, (s, _) in r["forms"].items() if s != "ok"]) for r in live]
    forms = sorted([x for x in forms if x[1]], key=lambda x: x[0]["name"])
    if not (overdue or due or ending or forms or booked):
        return None

    def sec(title, items, colour):
        if not items:
            return ""
        li = "".join(f'<li style="margin:0 0 6px">{i}</li>' for i in items)
        return (f'<h3 style="margin:20px 0 8px;font-size:15px;color:{colour}">{escape(title)} ({len(items)})</h3>'
                f'<ul style="margin:0;padding-left:18px;font-size:14px;color:#1f2937">{li}</ul>')
    b = lambda s: f"<b>{escape(s)}</b>"
    html = (f'<div style="font-family:Arial,Helvetica,sans-serif;max-width:560px;margin:auto;color:#1f2937">'
            f'<h2 style="color:#673E8D;margin:0 0 6px">Your participant plans – {d.strftime("%B %Y")}</h2>'
            f'<p style="font-size:14px;margin:0 0 4px">Hi {escape(first)}, here is what needs doing for your participants this month.</p>'
            + sec("Plan reviews overdue", [f"{b(r['name'])} – review was due {_fmt(r['rev'])}, plan ends {_fmt(r['end'])}" for r in overdue], "#b42318")
            + sec("Plan reviews due this month", [f"{b(r['name'])} – review due {_fmt(r['rev'])}" for r in due], "#8f5f00")
            + sec("Plans ending this month", [f"{b(r['name'])} – plan ends {_fmt(r['end'])}" for r in ending], "#b42318")
            + sec("Reviews booked this month", [f"{b(r['name'])} – review booked for {_fmt(r['booked_date'])}" for r in booked], "#1e7b3a")
            + sec("Forms to action", [f"{b(r['name'])} – {escape(', '.join(x))}" for r, x in forms], "#673E8D")
            + '<p style="font-size:13px;color:#6b7280;margin-top:22px">Open No Limitts → Home → My participant plans to see details '
              'or tick a review as booked. Booked reviews drop off this email.</p></div>')
    n = len(overdue) + len(due) + len(ending)
    return f"Your participant plans: {n} review{'s' if n != 1 else ''} / plan date{'s' if n != 1 else ''} this month", html


async def send_plans_emails(only: Optional[tuple] = None) -> dict:
    """Every plans page owner gets their own summary. only=(user, page_id) sends just that page to that user (test)."""
    from email_service import send_email
    ctx = await plans_context()
    if not ctx:
        return {"sent": 0, "reason": "No plan data uploaded yet"}
    _, _, today, pages = ctx
    sent, skipped = 0, 0
    for pg, rows in pages:
        if only and pg["dashboard_id"] != only[1]:
            continue
        users = [only[0]] if only else await db.users.find({"user_id": {"$in": pg.get("users") or []}, "hidden": {"$ne": True}},
                                                          {"_id": 0, "name": 1, "email": 1}).to_list(20)
        for u in users:
            msg = plans_email((u.get("name") or "there").split(" ")[0], rows, today)
            if not msg or not u.get("email"):
                skipped += 1
                continue
            sent += bool(await send_email(to=u["email"], subject=msg[0], html=msg[1]))
    return {"sent": sent, "nothing_due": skipped}


@router.post("/agts-dashboard/plans-email/test")
async def plans_email_test(request: Request, page: str = "participant-plans"):
    user = await require_view(request, None, "nk", page)
    return {**await send_plans_emails((user, page)), "to": user.get("email")}


# ---- Review booked tick
class BookIn(BaseModel):
    name: str
    end: int
    booked: bool = True
    date: Optional[int] = None  # booked review date (Excel serial day), optional


@router.post("/agts-dashboard/review-booked")
async def review_booked(body: BookIn, request: Request, token: Optional[str] = None, page: str = "participant-plans"):
    user = await require_view(request, token, "nk", page)
    async with httpx.AsyncClient(timeout=30) as client:
        prev = await read_part(client, "preview")
    nk = (json.loads(prev["data"]).get("nikki") if prev and prev.get("data") else None) or {}
    if user.get("_plans_tag"):
        nk = own_participants(nk, user["_plans_tag"])
    if not any(c.get("name") == body.name and c.get("end") == body.end for c in nk.get("clients") or []):
        raise HTTPException(404, "Participant not found on this page")
    key = _bkey(body.name, body.end)
    if body.date is not None and not (body.end - 800 <= body.date <= body.end + 400):
        raise HTTPException(400, "That review date doesn't look right")
    if body.booked:
        await db.plan_reviews_booked.update_one({"key": key}, {"$set": {
            "key": key, "name": body.name, "end": body.end, "review_date": body.date, "booked_by": user["user_id"],
            "booked_by_name": user.get("name", ""), "booked_at": now_iso()}}, upsert=True)
    else:
        await db.plan_reviews_booked.delete_one({"key": key})
    spawn(sync_plan_calendar())  # drop / restore the review date in connected calendars
    return {"booked": await booked_map(nk.get("clients") or [])}


# ---- Plan dates in each therapist's own Google Calendar
_cal_lock = asyncio.Lock()


async def sync_plan_calendar(extra: Optional[tuple] = None) -> dict:
    async with _cal_lock:  # one sync at a time so overlapping runs can't add the same event twice
        return await _sync_plan_calendar(extra)


async def _sync_plan_calendar(extra: Optional[tuple] = None) -> dict:
    """Adds all-day 'Plan ends' and 'Plan review due' events to the calendars of page owners who connected Google Calendar,
    and removes ones that no longer apply (booked, archived, date changed). extra=(user_id, page_id) also syncs a
    non-owner (e.g. an admin) for that page."""
    from datetime import date, timedelta
    from fastapi.concurrency import run_in_threadpool
    import google_services as gs
    from routes.calendar import admin_calendar
    if extra:
        await db.plan_cal_users.update_one({"user_id": extra[0]}, {"$addToSet": {"pages": extra[1]}}, upsert=True)
    ctx = await plans_context()
    if not ctx:
        return {"added": 0, "removed": 0}
    _, _, today, pages = ctx
    by_page = {pg["dashboard_id"]: rows for pg, rows in pages}
    targets = {}
    for pg, _ in pages:
        for uid in pg.get("users") or []:
            targets.setdefault(uid, set()).add(pg["dashboard_id"])
    for d in await db.plan_cal_users.find({}, P).to_list(500):
        targets.setdefault(d["user_id"], set()).update(d.get("pages") or [])
    day = lambda s: (date(1899, 12, 30) + timedelta(days=int(s))).isoformat()
    added = removed = 0
    for uid, pids in targets.items():
        try:
            svc = await admin_calendar(uid)
        except Exception as e:
            logger.error(f"Plan calendar connect failed for {uid}: {e}")
            continue
        if not svc:
            continue
        want = {}
        for pid in pids:
            for r in by_page.get(pid, []):
                if today <= r["end"] <= today + 400:
                    want[f"end|{_bkey(r['name'], r['end'])}"] = (f"Plan ends: {r['name']}", r["end"])
                if today <= r["rev"] <= today + 400 and not r["booked"] and r["rev"] < r["end"]:
                    want[f"rev|{_bkey(r['name'], r['end'])}|{r['rev']}"] = (f"Plan review due: {r['name']}", r["rev"])
                bd = r.get("booked_date")
                if r["booked"] and bd is not None and today <= bd <= today + 400:
                    want[f"bk|{_bkey(r['name'], r['end'])}|{bd}"] = (f"Plan review booked: {r['name']}", bd)
        have = {d["ekey"]: d for d in await db.plan_cal_events.find({"user_id": uid}, P).to_list(5000)}
        try:
            for ek, (title, s) in want.items():
                if ek in have:
                    continue
                g = await run_in_threadpool(gs.calendar_insert, svc, {
                    "summary": title, "description": "From No Limitts participant plans.", "transparency": "transparent",
                    "start": {"date": day(s)}, "end": {"date": day(s + 1)}})
                await db.plan_cal_events.insert_one({"user_id": uid, "ekey": ek, "google_event_id": g["id"], "created_at": now_iso()})
                added += 1
            for ek, d in have.items():
                if ek in want:
                    continue
                try:
                    await run_in_threadpool(gs.calendar_delete, svc, d["google_event_id"])
                except Exception as e:  # already deleted by the user in Google Calendar
                    logger.info(f"Plan calendar delete skipped: {e}")
                await db.plan_cal_events.delete_one({"user_id": uid, "ekey": ek})
                removed += 1
        except Exception as e:
            logger.error(f"Plan calendar sync failed for {uid}: {e}")
    return {"added": added, "removed": removed}


@router.post("/agts-dashboard/calendar-sync")
async def calendar_sync_now(request: Request, page: str = "participant-plans"):
    user = await require_view(request, None, "nk", page)
    from routes.calendar import cal_key
    if not await db.integrations.find_one({"key": cal_key(user["user_id"])}):
        raise HTTPException(409, "Connect your Google Calendar first")
    return await sync_plan_calendar((user["user_id"], page))


# ---- Team plans overview (admins): every therapist's overdue reviews and form gaps on one page
@router.get("/agts-dashboard/team-overview")
async def team_overview(admin=Depends(executive_user)):
    return await overview_data()


@router.get("/agts-dashboard/team-overview/pdf")
async def team_overview_pdf(request: Request, token: Optional[str] = None, exp: int = 0, sig: str = ""):
    """Printable team plans overview for team meetings (admins). Token in the query so it opens in a browser tab;
    the monthly email uses a signed link (exp + sig) that only opens this PDF and expires after 14 days."""
    from fastapi.concurrency import run_in_threadpool
    from fastapi.responses import Response
    import hmac
    import time
    if sig:
        if exp < time.time() or not hmac.compare_digest(sig, _pdf_sig(exp)):
            raise HTTPException(403, "This link has expired. Open No Limitts → Team plans overview for the latest PDF.")
    else:
        admin = await user_from_token(bearer(request) or token)
        if not admin or not is_executive(admin):
            raise HTTPException(403, "Executives only")
    d = await overview_data()
    pdf = await run_in_threadpool(build_overview_pdf, d)
    stamp = (d.get("today") or "").replace(" ", "_")
    return Response(content=pdf, media_type="application/pdf",
                    headers={"Content-Disposition": f'inline; filename="Team_Plans_Overview_{stamp}.pdf"'})


def _pdf_sig(exp: int) -> str:
    import hashlib
    import hmac
    key = (os.environ.get("WEBHOOK_ENCRYPTION_KEY") or "") + "|team-overview-pdf"
    return hmac.new(key.encode(), str(int(exp)).encode(), hashlib.sha256).hexdigest()[:32]


def team_report_email(first: str, d: dict) -> tuple:
    """(subject, html) monthly team plans report: totals, one row per therapist and a 14-day signed PDF link."""
    import time
    from html import escape as e
    exp = int(time.time()) + 14 * 86400
    base = (os.environ.get("PUBLIC_BACKEND_URL") or "").rstrip("/")
    link = f"{base}/api/agts-dashboard/team-overview/pdf?exp={exp}&sig={_pdf_sig(exp)}" if base.startswith("https://") else ""
    t = d.get("totals") or {}
    td = "padding:6px 8px;border-bottom:1px solid #e5e7eb;font-size:13px"
    rows = "".join(f"<tr><td style='{td}'>{e(', '.join(p['owners']) or p['name'])}</td><td style='{td};text-align:center'>{len(p['overdue'])}</td>"
                   f"<td style='{td};text-align:center'>{len(p['forms'])}</td><td style='{td};text-align:center'>{len(p['due_30'])}</td>"
                   f"<td style='{td};text-align:center'>{len(p['ending_30'])}</td></tr>" for p in d["pages"])
    th = "padding:6px 8px;background:#EFE8F5;font-size:12px;text-align:left;color:#673E8D"
    btn = (f'<p style="margin:20px 0"><a href="{link}" style="background:#673E8D;color:#ffffff;padding:12px 18px;border-radius:10px;'
           f'text-decoration:none;font-weight:bold;font-size:14px">Download the team plans PDF</a></p>'
           f'<p style="font-size:12px;color:#6b7280">The link opens the latest figures and expires in 14 days.</p>') if link else ""
    html = (f'<table role="presentation" width="100%"><tr><td style="padding:20px;font-family:Arial,Helvetica,sans-serif;color:#1f2937">'
            f'<h2 style="color:#673E8D;margin:0 0 6px">Monthly team plans report – {e(d.get("today") or "")}</h2>'
            f'<p style="font-size:14px">Hi {e(first)}, here is this month\'s participant plans snapshot for the team meeting.</p>'
            f'<p style="font-size:14px"><b>{t.get("overdue", 0)}</b> reviews overdue · <b>{t.get("forms", 0)}</b> participants with forms to action · '
            f'<b>{t.get("due_30", 0)}</b> reviews due in 30 days · <b>{t.get("ending_30", 0)}</b> plans ending in 30 days · '
            f'<b>{t.get("booked", 0)}</b> reviews booked</p>'
            f'<table role="presentation" width="100%" style="border-collapse:collapse"><tr><th style="{th}">Therapist</th><th style="{th}">Overdue</th>'
            f'<th style="{th}">Forms</th><th style="{th}">Due ≤30d</th><th style="{th}">Ending ≤30d</th></tr>{rows}</table>'
            f'{btn}<p style="font-size:12px;color:#6b7280">Sent by No Limitts (Aspire &amp; Grow) on the first Monday of each month. '
            f'Names and dates are in the PDF and in No Limitts → Team plans overview.</p></td></tr></table>')
    return f"Team plans report: {t.get('overdue', 0)} overdue reviews, {t.get('forms', 0)} forms to action", html


async def send_team_report(only: Optional[dict] = None) -> dict:
    """Monthly report to every admin (test accounts excluded), or just `only` (the 'Email it to me' button)."""
    from email_service import send_email
    d = await overview_data()
    admins = [only] if only else [u for u in await db.users.find({"executive": True, "hidden": {"$ne": True}}, {"_id": 0, "name": 1, "email": 1}).to_list(50)
                                  if u.get("email") and not u["email"].endswith("@example.com")]
    sent = 0
    for u in admins:
        subject, html = team_report_email((u.get("name") or "there").split(" ")[0], d)
        sent += bool(await send_email(to=u["email"], subject=subject, html=html))
    return {"sent": sent, "to": [u["email"] for u in admins]}


@router.post("/agts-dashboard/team-overview/email-me")
async def team_report_email_me(admin=Depends(executive_user)):
    return await send_team_report(admin)


def build_overview_pdf(d: dict) -> bytes:
    import io
    import pymupdf
    from html import escape as e
    t = d.get("totals") or {}
    th = "background:#EFE8F5;text-align:left"
    tbl = "<table style='width:100%;border-collapse:collapse;font-size:8.5px' border='1' cellpadding='3'>"

    def section(title, colour, head, rows):
        if not rows:
            return ""
        body = "".join("<tr>" + "".join(f"<td>{e(str(c))}</td>" for c in r) + "</tr>" for r in rows)
        return (f"<p style='font-size:10px;color:{colour};margin:8px 0 3px'><b>{e(title)} ({len(rows)})</b></p>{tbl}<tr>"
                + "".join(f"<th style='{th}'>{h}</th>" for h in head) + f"</tr>{body}</table>")

    summary = (f"{tbl}<tr>" + "".join(f"<th style='{th}'>{h}</th>" for h in ("Therapist", "Participants", "Overdue", "Forms", "Due ≤30d", "Ending ≤30d", "Booked"))
               + "</tr>" + "".join(f"<tr><td>{e(', '.join(p['owners']) or p['name'])}</td><td>{p['participants']}</td><td>{len(p['overdue'])}</td>"
                                   f"<td>{len(p['forms'])}</td><td>{len(p['due_30'])}</td><td>{len(p['ending_30'])}</td><td>{len(p['booked'])}</td></tr>"
                                   for p in d["pages"]) + "</table>")
    html = (f"<h2 style='color:#673E8D;margin:0'>Team plans overview</h2>"
            f"<p style='font-size:9.5px'>As of {e(d.get('today') or '')} · generated by No Limitts (Aspire &amp; Grow). "
            f"Plan reviews fall due {d.get('review_months', 3)} months before the plan ends; booked reviews are not counted as overdue.<br/>"
            f"<b>Team totals:</b> {t.get('overdue', 0)} reviews overdue · {t.get('forms', 0)} participants with forms to action · "
            f"{t.get('due_30', 0)} reviews due in 30 days · {t.get('ending_30', 0)} plans ending in 30 days · {t.get('booked', 0)} reviews booked</p>"
            + summary)
    for p in d["pages"]:
        html += f"<h3 style='color:#673E8D;margin:14px 0 2px'>{e(', '.join(p['owners']) or p['name'])} · {p['participants']} active participants</h3>"
        parts = (section("Reviews overdue", "#B42318", ("Participant", "Review was due", "Days overdue", "Plan ends"),
                         [(r["name"], r["review"], r["days_overdue"], r["end"]) for r in p["overdue"]])
                 + section("Forms to action", "#9A5B00", ("Participant", "Issue"), [(f["name"], ", ".join(f["issues"])) for f in p["forms"]])
                 + section("Reviews due in 30 days", "#9A5B00", ("Participant", "Review due", "Plan ends"),
                           [(r["name"], r["review"], r["end"]) for r in p["due_30"]])
                 + section("Plans ending in 30 days", "#B42318", ("Participant", "Plan ends", "Days left"),
                           [(r["name"], r["end"], r["days_to_end"]) for r in p["ending_30"]])
                 + section("Reviews booked", "#1E7B3A", ("Participant", "Booked for", "Plan ends"),
                           [(r["name"], r.get("review") or "date not set", r["end"]) for r in p["booked"]]))
        html += parts or "<p style='font-size:9px'>All up to date.</p>"
    if not d["pages"]:
        html += "<p style='font-size:10px'>No plan data uploaded yet.</p>"
    from pdf_brand import FIRST_TOP, add_logo
    buf = io.BytesIO()
    writer = pymupdf.DocumentWriter(buf)
    story = pymupdf.Story(html=html)
    page, more, top = pymupdf.paper_rect("a4"), True, FIRST_TOP
    while more:  # flow onto as many pages as needed
        dev = writer.begin_page(page)
        more, _ = story.place(page + (36, top, -36, -36))
        story.draw(dev)
        writer.end_page()
        top = 36
    writer.close()
    return add_logo(buf.getvalue())


async def overview_data() -> dict:
    ctx = await plans_context()
    if not ctx:
        return {"pages": [], "totals": {}, "today": _fmt(_today_serial()), "review_months": 3}
    _, cfg, today, pages = ctx
    word = {"missing": "missing", "incomplete": "not completed", "old": "out of date"}
    out = []
    for pg, rows in pages:
        if pg.get("test"):
            continue
        owners = await db.users.find({"user_id": {"$in": pg.get("users") or []}}, {"_id": 0, "name": 1}).to_list(20)
        live = [r for r in rows if r["end"] >= today]
        item = lambda r, **k: {"name": r["name"], "end": _fmt(r["end"]), "days_to_end": r["end"] - today, **k}
        out.append({
            "dashboard_id": pg["dashboard_id"], "name": pg.get("name", ""),
            "owners": [u.get("name", "") for u in owners], "participants": len(live),
            "overdue": [item(r, review=_fmt(r["rev"]), days_overdue=today - r["rev"])
                        for r in sorted(live, key=lambda r: r["rev"]) if r["rev"] < today and r["end"] - today > 30 and not r["booked"]],
            "due_30": [item(r, review=_fmt(r["rev"])) for r in sorted(live, key=lambda r: r["rev"])
                       if today <= r["rev"] <= today + 30 and r["end"] - today > 30 and not r["booked"]],
            "ending_30": [item(r) for r in sorted(live, key=lambda r: r["end"]) if r["end"] <= today + 30],
            "booked": [item(r, review=_fmt(r["booked_date"]) if r.get("booked_date") is not None else "") for r in live if r["booked"]],
            "forms": [{"name": r["name"], "issues": [f"{FORM_LABEL[t]} {word[s]}" for t, (s, _) in r["forms"].items() if s != "ok"]}
                      for r in sorted(live, key=lambda r: r["name"]) if any(s != "ok" for s, _ in r["forms"].values())],
        })
    out.sort(key=lambda p: (-(len(p["overdue"]) + len(p["forms"])), p["name"]))
    totals = {k: sum(len(p[k]) for p in out) for k in ("overdue", "due_30", "ending_30", "booked", "forms")}
    return {"pages": out, "totals": totals, "today": _fmt(today), "review_months": cfg["months"]}


MOBILE_CSS = """<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover"><style id="sh-mobile">
@media (max-width: 760px){
 body{font-size:15px;-webkit-text-size-adjust:100%}
 html body .wrap{padding:12px 12px 40px}
 html body .brandbar{height:4px;margin-bottom:10px}
 html body h1{font-size:20px} html body h2{font-size:16px;margin:22px 0 10px}
 html body .controls,html body .controls label{width:100%} html body .controls input{width:100%;min-height:44px;font-size:16px}
 html body .top{flex-direction:column;align-items:stretch;gap:10px}
 html body .uploads{grid-template-columns:1fr;gap:8px}
 .drop{padding:12px;min-height:56px}
 .note{font-size:12.5px}
 html body .tabs{position:sticky;top:0;z-index:20;background:var(--bg);flex-wrap:nowrap;overflow-x:auto;gap:8px;padding:10px 0;margin-top:12px;border-bottom:none;-webkit-overflow-scrolling:touch;scrollbar-width:none}
 html body .tabs::-webkit-scrollbar{display:none}
 html body .tab{flex:0 0 auto;white-space:nowrap;min-height:40px;padding:8px 14px;border-radius:20px;border:1px solid var(--border);background:var(--surface);margin:0}
 html body .tab.on{background:var(--navy);color:#fff;border-color:var(--navy)}
 html body .tiles{grid-template-columns:1fr 1fr;gap:8px}
 .tile .v{font-size:20px}
 canvas{max-width:100%!important}
 select,input.in,button{min-height:40px;font-size:16px}
 /* tables become stacked cards */
 html body .tblwrap,html body .scrollbox{overflow:visible;max-height:none;background:none;border:none}
 table.sh-cards,table.sh-cards tbody,table.sh-cards tr,table.sh-cards td{display:block;width:100%}
 table.sh-cards tr.sh-head{display:none!important}
 table.sh-cards tr{background:var(--surface);border:1px solid var(--border);border-radius:14px;margin:0 0 10px;padding:8px 12px 10px;box-shadow:0 1px 2px rgba(20,35,58,.05);display:grid!important;grid-template-columns:1fr 1fr;column-gap:12px}
 table.sh-cards tr.tot{background:var(--tint-sky)}
 table.sh-cards td{border:none;white-space:normal;text-align:left;display:flex;flex-direction:column;align-items:flex-start;justify-content:flex-start;gap:1px;padding:6px 0;min-height:0;position:static!important;box-shadow:none!important;max-width:none!important;min-width:0!important;background:none!important;font-size:14.5px;font-weight:600;overflow-wrap:anywhere}
table.sh-cards td.sh-wide{grid-column:1 / -1}
 table.sh-cards td::before{content:attr(data-label);color:var(--ink-3);font-size:11.5px;font-weight:500;text-align:left;line-height:1.25}
 table.sh-cards td.sh-title{grid-column:1 / -1;font-size:16px;font-weight:700;color:var(--navy);padding:4px 0 6px;margin-bottom:2px;border-bottom:1px solid var(--border)}
 table.sh-cards td.sh-title::before{display:none}
 table.sh-cards td:empty{display:none}
 table.sh-cards td input,table.sh-cards td select{width:100%;max-width:100%}
 .topscroll{display:none}
 html body .sh-toggle{display:flex;width:100%;align-items:center;justify-content:space-between;min-height:44px;margin-top:10px;padding:10px 14px;border-radius:12px;border:1px solid var(--border);background:var(--surface);color:var(--navy);font:inherit;font-weight:700}
 html body:not(.sh-open) .uploads, html body:not(.sh-open) .note, html body:not(.sh-open) .sharebar{display:none!important}
 html body .sub{font-size:12px}
}
@media (min-width: 761px){ .sh-toggle{display:none} }
</style>
<script>
(function(){
 function cardify(){
  if (window.innerWidth > 760) return;
  document.querySelectorAll('table').forEach(function(t){
   var rows=t.rows; if(!rows.length) return;
   var head=null; for(var i=0;i<rows.length;i++){ if(rows[i].querySelector('th')){ head=rows[i]; break; } }
   if(!head) return;
   var labels=[]; Array.prototype.forEach.call(head.cells,function(c){ var n=c.colSpan||1; for(var k=0;k<n;k++) labels.push(c.innerText.replace(/\\s+/g,' ').trim()); });
   head.classList.add('sh-head'); t.classList.add('sh-cards');
   Array.prototype.forEach.call(rows,function(r){ if(r===head||r.querySelector('th')&&!r.querySelector('td')){ if(r!==head) r.classList.add('sh-head'); return; }
    var col=0; Array.prototype.forEach.call(r.cells,function(c,idx){ if(!c.hasAttribute('data-label')) c.setAttribute('data-label',labels[col]||''); if(idx===0) c.classList.add('sh-title'); else if((c.colSpan||1)>2||c.querySelector('textarea')||c.innerText.trim().length>22) c.classList.add('sh-wide'); col+=c.colSpan||1; });
   });
  });
 }
 var tmr=null; function soon(){ clearTimeout(tmr); tmr=setTimeout(cardify,60); }
 document.addEventListener('DOMContentLoaded',function(){
  var up=document.querySelector('.uploads');
  if(up){ var b=document.createElement('button'); b.type='button'; b.className='sh-toggle'; b.id='shToggle';
   var set=function(){ var open=document.body.classList.contains('sh-open'); b.innerHTML=(open?'Hide':'Show')+' uploads &amp; data status <span>'+(open?'▲':'▼')+'</span>'; };
   b.onclick=function(){ document.body.classList.toggle('sh-open'); set(); }; set(); up.parentNode.insertBefore(b,up); }
  document.querySelectorAll('.tab').forEach(function(t){ t.addEventListener('click',function(){ if(window.innerWidth<=760){ t.scrollIntoView({block:'nearest',inline:'center'}); var tabs=document.getElementById('tabs'); if(tabs) window.scrollTo({top:tabs.offsetTop-4}); } }); });
  cardify(); new MutationObserver(soon).observe(document.body,{childList:true,subtree:true}); });
 window.addEventListener('resize',soon);
})();
</script>"""


def _inject(html: str, anchor: str, new: str) -> str:
    """Swap one anchor in the dashboard template; log loudly if the template changed and the anchor is gone."""
    if anchor not in html:
        logger.error("AGTS dashboard template anchor missing: %r", anchor)
        return html
    return html.replace(anchor, new, 1)


@router.get("/agts-dashboard/engine", response_class=HTMLResponse)
async def engine(request: Request, token: Optional[str] = None, view: str = "", page: str = "participant-plans"):
    user = await require_view(request, token, view, page)
    html = ENGINE.read_text(encoding="utf-8")
    html = html.replace("<head>", "<head>" + MOBILE_CSS, 1)
    # Participant plans & safety (Nikki) view: the engine already renders it into #v-nk; give it a tab and a home
    if view == "nk":
        own = bool(user.get("_plans_tag"))  # a therapist's own page
        if own:  # covers plain and JS-escaped (Nikki\'s) wording, with or without "for"/"All of"
            html = re.sub(r"(for |All of |of )?Nikki(\\?)'s participants",
                          lambda m: (m.group(1) or "") + ("my" if m.group(1) else "My") + " participants", html)
            html = html.replace("`Nikki_plan_reviews_", "`My_plan_reviews_")
            # view-only: hide uploads and settings (the server also refuses saves from these pages)
            html = _inject(html, "</body>", "<style>label.btn:has(#nkCl),label.btn:has(#nkFo),.controls:has(#nkTag),"
                           "h2:has(+ .controls #nkTag){display:none!important}</style></body>")
        who = "my participants" if own else "Nikki's participants"
        html = _inject(html, '<button class="tab" data-v="set">Settings</button>',
                       '<button class="tab" data-v="set">Settings</button>\n    <button class="tab" data-v="nk">Plans &amp; safety</button>')
        html = _inject(html, '<div class="view" id="v-set">',
                       '<div class="view" id="v-nk"><div class="empty">Loading…</div></div>\n  <div class="view" id="v-set">')
        html = _inject(html, "</body>", """<style>#tabs,.uploads,.note,#shToggle,.sharebar,.top .controls,#periodLine{display:none!important}</style>
<script>document.addEventListener('DOMContentLoaded',function(){ var h=document.querySelector('h1'); if(h) h.textContent='Participant Plans & Safety';
 var p=document.getElementById('periodLine'); if(p) p.textContent=""" + json.dumps("Plan reviews, risk assessments and emergency plans for " + who) + """;
 setTimeout(function(){ if(typeof show==='function') show('nk'); },0); });</script></body>""")
    return HTMLResponse(html, headers={"Cache-Control": "no-store", "Referrer-Policy": "no-referrer"})


# ---- Background: Friday upload reminder + below-hours-target alerts
async def _admin_ids() -> list:  # dashboard alerts go to Executives (the only people who can open the dashboard)
    return [u["user_id"] for u in await db.users.find({"executive": True, "hidden": {"$ne": True}}, {"_id": 0, "user_id": 1}).to_list(100)]


def _serial_to_date(s: int):
    from datetime import date, timedelta
    return date(1899, 12, 30) + timedelta(days=int(s))


def hours_alerts(billing_json: str, settings_json: str) -> tuple:
    """Same maths as the dashboard's scorecard (statsFor/hoursFrom): returns (window_end_serial, [(key, full, h4, target)])."""
    d = json.loads(billing_json)
    st = json.loads(settings_json) if settings_json else {}
    ths = st.get("therapists") or {}
    rows = []
    for a in d.get("rows", []):
        full = str(d["fulls"][a[3]] or "").strip()
        code = str(d["codes"][a[4]] or "")
        p = code.split("_")
        cat = "km" if len(p) > 1 and p[1] == "799" else {"PT": "tt", "CA": "ca", "NF": "nf", "TH": "nf", "RR": "nf"}.get(p[-1], "ds")
        rows.append({"sd": a[0], "key": full.split()[0] if full else "", "cat": cat, "tot": a[6] or 0})
    if not rows:
        return None, []
    mx = max(r["sd"] for r in rows)
    E = mx - ((_serial_to_date(mx).weekday() - 3) % 7)  # last Thursday on/before latest service date
    S4, S12 = E - 27, E - 83
    out = []
    for k, t in ths.items():
        mine = [r for r in rows if r["key"] == k]
        if not mine or not t.get("target") or not t.get("rate"):
            continue
        first = min(r["sd"] for r in mine)
        w = lambda S: max(0, min((E - S + 1) / 7, -(-(E - max(first, S) + 1) // 7)))
        w4, w12 = w(S4), w(S12)
        if w12 < 6 or not w4:
            continue  # new starters are flagged differently on the dashboard
        r4 = [r for r in mine if S4 <= r["sd"] <= E]
        tot = sum(r["tot"] for r in r4)
        tt = sum(r["tot"] for r in r4 if r["cat"] == "tt")
        km = sum(r["tot"] for r in r4 if r["cat"] == "km")
        rate = float(t["rate"])
        h4 = ((tot - tt - km) / rate + tt / (rate / 2)) / w4
        if h4 / float(t["target"]) < 0.9:
            out.append((k, t.get("full") or k, round(h4, 1), t["target"]))
    return E, out


async def dashboard_loop():
    from datetime import datetime, timedelta
    from core import DIGEST_TZ, notify
    while True:
        try:
            local = datetime.now(DIGEST_TZ)
            async with httpx.AsyncClient(timeout=30) as client:
                # Friday 9am reminder unless this week's export is already in
                if local.weekday() == 4 and local.hour >= 9:
                    key = f"agts_upload_reminder_{local.date().isoformat()}"
                    if not await db.meta.find_one({"key": key}):
                        await db.meta.insert_one({"key": key, "created_at": now_iso()})
                        prev = await read_part(client, "preview")
                        upd = (prev or {}).get("updated") or ""
                        fresh = upd and upd[:10] >= (local.date() - timedelta(days=1)).isoformat()
                        if not fresh:
                            await notify(await _admin_ids(), "dashboard", "Upload this week's End of Week export",
                                         "Keep the Therapist dashboard current: open it, tap Show uploads & data status and add the export.",
                                         "/dashboard/therapist-dashboard")
                await plan_alerts()
                # Monday 8am: each therapist's plans summary email
                if local.weekday() == 0 and local.hour >= 8:
                    ekey = f"agts_plans_email_{local.date().isoformat()}"
                    if not await db.meta.find_one({"key": ekey}):
                        await db.meta.insert_one({"key": ekey, "created_at": now_iso()})
                        logger.info(f"Plans emails: {await send_plans_emails()}")
                    # first Monday of the month: team plans report to admins
                    if local.day <= 7:
                        rkey = f"agts_team_report_{local.strftime('%Y-%m')}"
                        if not await db.meta.find_one({"key": rkey}):
                            await db.meta.insert_one({"key": rkey, "created_at": now_iso()})
                            logger.info(f"Team plans report: {await send_team_report()}")
                await sync_plan_calendar()
                # Below hours target alerts, once per therapist per dashboard week
                bill, sett = await read_part(client, "billing"), await read_part(client, "settings")
                if bill and bill.get("data"):
                    E, low = hours_alerts(bill["data"], (sett or {}).get("data") or "")
                    for k, full, h4, target in low:
                        akey = f"agts_hours_alert_{k}_{E}"
                        if await db.meta.find_one({"key": akey}):
                            continue
                        await db.meta.insert_one({"key": akey, "created_at": now_iso()})
                        await notify(await _admin_ids(), "dashboard", f"{full} is below their hours target",
                                     f"Averaging {h4} of {target} hrs/wk over the last 4 weeks (to {_serial_to_date(E).strftime('%d %b %Y')}).",
                                     "/dashboard/therapist-dashboard")
        except Exception as e:
            logger.error(f"AGTS dashboard loop error: {e}")
        await asyncio.sleep(3600)


@router.get("/agts-dashboard/app", response_class=HTMLResponse)
async def app_page(request: Request, token: Optional[str] = None, view: str = "", page: str = "participant-plans"):
    """Wrapper that hosts the engine in a frame and relays load/save messages, like the Wix page did."""
    await require_view(request, token, view, page)
    from urllib.parse import quote as _q
    pq = f"&page={_q(page)}" if view == "nk" else ""
    t = json.dumps(token or "")
    html = """<!doctype html><html><head><meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
<meta name="referrer" content="no-referrer"><style>html,body{margin:0;height:100%;background:#f4f8fb}iframe{border:0;width:100%;height:100%;display:block}</style></head>
<body><iframe id="f" src="engine?token=__TOK____VIEW__"></iframe><script>
const TOKEN=__T__; const Q=__Q__; const f=document.getElementById('f');
const api=(p,o={})=>fetch(p,{...o,headers:{'Authorization':'Bearer '+TOKEN,'Content-Type':'application/json'}}).then(async r=>{const j=await r.json().catch(()=>({})); if(!r.ok) throw new Error(j.detail||('Error '+r.status)); return j;});
let loading=false;
window.addEventListener('message',async e=>{ if(e.source!==f.contentWindow) return; const m=e.data||{};
  if(m.type==='ready'&&!loading){ loading=true; try{ const d=await api('data'+Q); f.contentWindow.postMessage({type:'shared-data',...d},'*'); }
    catch(err){ f.contentWindow.postMessage({type:'shared-error',message:err.message},'*'); loading=false; } }
  if(m.type==='save'){ try{ const r=await api('save'+Q,{method:'POST',body:JSON.stringify({part:m.part,json:m.json})}); f.contentWindow.postMessage({type:'saved',part:m.part,...r},'*'); }
    catch(err){ f.contentWindow.postMessage({type:'shared-error',message:'Could not save: '+err.message},'*'); } }
});
</script></body></html>"""
    from urllib.parse import quote
    return HTMLResponse(html.replace("__TOK__", quote(token or "")).replace("__VIEW__", ("&view=nk" + pq) if view == "nk" else "").replace("__T__", t).replace("__Q__", json.dumps(("?view=nk" + pq) if view == "nk" else "")),
                        headers={"Cache-Control": "no-store", "Referrer-Policy": "no-referrer"})
