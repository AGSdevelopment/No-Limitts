"""AGTS Therapist Performance Dashboard inside StaffHub.

Runs the team's own dashboard engine (assets/therapist-dashboard.html, unchanged logic) with a phone-first
stylesheet, and plays the role of the Wix page: data is read from / saved to the same Wix CMS collection
(`TherapistDashboard`) so updates made on the website show here and vice versa. Admins only.
Until WIX_API_KEY + WIX_SITE_ID are set, data is kept in StaffHub (`agts_dashboard_parts`)."""
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
from core import P, bearer, db, logger, now_iso, user_from_token

router = APIRouter(prefix="/api")
COLLECTION = "TherapistDashboard"
PARTS = ["billing", "participants", "settings", "preview"]
ENGINE = Path(__file__).resolve().parent.parent / "assets" / "therapist-dashboard.html"
WIX = "https://www.wixapis.com/wix-data/v2/items"


def wix_headers() -> Optional[dict]:
    key, site = os.environ.get("WIX_API_KEY", "").strip(), os.environ.get("WIX_SITE_ID", "").strip()
    return {"Authorization": key, "wix-site-id": site, "Content-Type": "application/json"} if key and site else None


async def require_admin_token(request: Request, token: Optional[str]) -> dict:
    user = await user_from_token(bearer(request) or token)
    if not user:
        raise HTTPException(401, "Not authenticated")
    if user.get("role") != "admin":
        raise HTTPException(403, "Admins only")
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
            if user.get("_plans_tag"):  # a therapist's own page: show only participants with their tag
                nk = {**nk, "cfg": {**(nk.get("cfg") or {}), "tag": user["_plans_tag"]}}
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
        # merge just the Nikki section into the shared record so nothing else is overwritten
        async with httpx.AsyncClient(timeout=30) as client:
            prev = await read_part(client, "preview")
        full = json.loads(prev["data"]) if prev and prev.get("data") else {}
        old_cfg = (full.get("nikki") or {}).get("cfg") or {}
        full["nikki"] = json.loads(body.json).get("nikki") or {}
        if user.get("_plans_tag"):  # keep Nikki's tag setting; a therapist page only views with its own tag
            full["nikki"]["cfg"] = {**(full["nikki"].get("cfg") or {}), "tag": old_cfg.get("tag", "Nikki's Clients")}
        return await write_part("preview", json.dumps(full, separators=(",", ":")), user["email"])
    return await write_part(body.part, body.json, user["email"])


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
    shared only with the StaffHub user whose first name matches (skipped when the name is ambiguous)."""
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
                if rev <= today:
                    await once(f"agts_review_{k}_{rev}", f"Plan review overdue: {name}",
                               f"The plan review was due {_fmt(rev)} (plan ends {_fmt(end)}).")
            last = (c.get("name", "").split(" ") or [""])[-1]
            mine = forms.get(name.strip().lower(), []) + (forms.get(f"{c['pref']} {last}".strip().lower(), []) if c.get("pref") else [])
            ra = sorted([f for f in mine if f.get("t") == "ra"], key=lambda f: f.get("u") or f.get("c") or 0, reverse=True)
            if ra:
                f = ra[0]
                done = f.get("u") or f.get("c") or today
                complete = "complete" in str(f.get("st", "")).lower() and "incomplete" not in str(f.get("st", "")).lower()
                if complete and today - done > float(cfg["formAge"]) * 30.4:
                    await once(f"agts_ra_{k}_{done}", f"Risk assessment out of date: {name}",
                               f"Last completed {_fmt(done)}, over {cfg['formAge']} months ago. Please complete a new one.")


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
 table.sh-cards tr.sh-head{display:none}
 table.sh-cards tr{background:var(--surface);border:1px solid var(--border);border-radius:14px;margin:0 0 10px;padding:6px 12px;box-shadow:0 1px 2px rgba(20,35,58,.05)}
 table.sh-cards tr.tot{background:var(--tint-sky)}
 table.sh-cards td{border:none;white-space:normal;text-align:right;display:flex;justify-content:space-between;align-items:center;gap:12px;padding:6px 0;min-height:32px;position:static!important;box-shadow:none!important;max-width:none!important;min-width:0!important;background:none!important}
 table.sh-cards td+td{border-top:1px solid var(--border)}
 table.sh-cards td::before{content:attr(data-label);color:var(--ink-2);font-size:12.5px;font-weight:600;text-align:left;flex:1 1 45%}
 table.sh-cards td.sh-title{font-size:16px;font-weight:700;color:var(--navy);text-align:left;justify-content:flex-start;padding-top:8px}
 table.sh-cards td.sh-title::before{display:none}
 table.sh-cards td:empty{display:none}
 table.sh-cards td input,table.sh-cards td select{max-width:55%}
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
    var col=0; Array.prototype.forEach.call(r.cells,function(c,idx){ if(!c.hasAttribute('data-label')) c.setAttribute('data-label',labels[col]||''); if(idx===0) c.classList.add('sh-title'); col+=c.colSpan||1; });
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
            html = re.sub(r"(for |All of )?Nikki(\\?)'s participants",
                          lambda m: (m.group(1) or "") + ("my" if m.group(1) else "My") + " participants", html)
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
async def _admin_ids() -> list:
    return [u["user_id"] for u in await db.users.find({"role": "admin", "hidden": {"$ne": True}}, {"_id": 0, "user_id": 1}).to_list(100)]


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
