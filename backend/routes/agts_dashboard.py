"""AGTS Therapist Performance Dashboard inside StaffHub.

Runs the team's own dashboard engine (assets/therapist-dashboard.html, unchanged logic) with a phone-first
stylesheet, and plays the role of the Wix page: data is read from / saved to the same Wix CMS collection
(`TherapistDashboard`) so updates made on the website show here and vice versa. Admins only.
Until WIX_API_KEY + WIX_SITE_ID are set, data is kept in StaffHub (`agts_dashboard_parts`)."""
import json
import os
from pathlib import Path
from typing import Optional
import httpx
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
from core import P, admin_user, bearer, db, logger, now_iso, user_from_token

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


@router.get("/agts-dashboard/data")
async def dashboard_data(request: Request, token: Optional[str] = None):
    user = await require_admin_token(request, token)
    async with httpx.AsyncClient(timeout=30) as client:
        out = {"user": user["email"], "source": "wix" if wix_headers() else "staffhub"}
        for p in PARTS:
            out[p] = await read_part(client, p)
    return out


class SaveIn(BaseModel):
    part: str
    json: str


@router.post("/agts-dashboard/save")
async def dashboard_save(body: SaveIn, admin=Depends(admin_user)):
    if body.part not in PARTS:
        raise HTTPException(400, "Unknown data type.")
    if len(body.json) > 480000:
        raise HTTPException(400, "The data is too large to save.")
    h = wix_headers()
    if h:
        item = {"id": body.part, "data": {"_id": body.part, "title": body.part, "data": body.json, "updatedBy": admin["email"]}}
        async with httpx.AsyncClient(timeout=30) as client:
            r = await client.post(f"{WIX}/save", json={"dataCollectionId": COLLECTION, "dataItem": item}, headers=h)
        if r.status_code != 200:
            logger.error(f"Wix save failed {r.status_code}: {r.text[:300]}")
            raise HTTPException(502, f"Could not save to Wix ({r.status_code})")
        return {"updated": now_iso(), "updatedBy": admin["email"]}
    await db.agts_dashboard_parts.update_one({"part": body.part}, {"$set": {"data": body.json, "updatedBy": admin["email"],
                                                                             "updated": now_iso()}}, upsert=True)
    return {"updated": now_iso(), "updatedBy": admin["email"]}


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


@router.get("/agts-dashboard/engine", response_class=HTMLResponse)
async def engine(request: Request, token: Optional[str] = None):
    await require_admin_token(request, token)
    html = ENGINE.read_text(encoding="utf-8")
    html = html.replace("<head>", "<head>" + MOBILE_CSS, 1)
    return HTMLResponse(html, headers={"Cache-Control": "no-store", "Referrer-Policy": "no-referrer"})


@router.get("/agts-dashboard/app", response_class=HTMLResponse)
async def app_page(request: Request, token: Optional[str] = None):
    """Wrapper that hosts the engine in a frame and relays load/save messages, like the Wix page did."""
    await require_admin_token(request, token)
    t = json.dumps(token or "")
    html = """<!doctype html><html><head><meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
<meta name="referrer" content="no-referrer"><style>html,body{margin:0;height:100%;background:#f4f8fb}iframe{border:0;width:100%;height:100%;display:block}</style></head>
<body><iframe id="f" src="engine?token=__TOK__"></iframe><script>
const TOKEN=__T__; const f=document.getElementById('f');
const api=(p,o={})=>fetch(p,{...o,headers:{'Authorization':'Bearer '+TOKEN,'Content-Type':'application/json'}}).then(async r=>{const j=await r.json().catch(()=>({})); if(!r.ok) throw new Error(j.detail||('Error '+r.status)); return j;});
let loading=false;
window.addEventListener('message',async e=>{ if(e.source!==f.contentWindow) return; const m=e.data||{};
  if(m.type==='ready'&&!loading){ loading=true; try{ const d=await api('data'); f.contentWindow.postMessage({type:'shared-data',...d},'*'); }
    catch(err){ f.contentWindow.postMessage({type:'shared-error',message:err.message},'*'); loading=false; } }
  if(m.type==='save'){ try{ const r=await api('save',{method:'POST',body:JSON.stringify({part:m.part,json:m.json})}); f.contentWindow.postMessage({type:'saved',part:m.part,...r},'*'); }
    catch(err){ f.contentWindow.postMessage({type:'shared-error',message:'Could not save: '+err.message},'*'); } }
});
</script></body></html>"""
    from urllib.parse import quote
    return HTMLResponse(html.replace("__TOK__", quote(token or "")).replace("__T__", t),
                        headers={"Cache-Control": "no-store", "Referrer-Policy": "no-referrer"})
