"""Referral Partners on a free OpenStreetMap map (Leaflet). Addresses are geocoded with the free OSM-based
Photon service (Nominatim as backup), about 1 request/second, cached in `geocache` and on each entry."""
import asyncio
import json
import re
from html import escape
from typing import Optional
import httpx
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse
from core import P, bearer, db, logger, now_iso, user_from_token

router = APIRouter(prefix="/api")
REFERRAL = "Trusted Referral Partner Organisations"
_geo_lock = asyncio.Lock()
_queued: set = set()


async def geocode(text: str) -> Optional[dict]:
    q = " ".join(text.split()).lower()
    if not q:
        return None
    hit = await db.geocache.find_one({"q": q}, P)
    if hit:
        return hit if hit.get("lat") is not None else None
    async with _geo_lock:  # free public OpenStreetMap geocoders: keep to ~1 request per second
        rows = None
        try:
            async with httpx.AsyncClient(timeout=10, headers={"User-Agent": "AGTS-No Limitts/1.0 (referral partner map)"}) as client:
                r = await client.get("https://photon.komoot.io/api/",
                                     params={"q": f"{text} Australia", "limit": 5, "lat": -31.95, "lon": 115.86})
                if r.status_code == 200:
                    feats = [f for f in r.json().get("features", []) if f["properties"].get("countrycode") == "AU"]
                    rows = [{"lat": f["geometry"]["coordinates"][1], "lon": f["geometry"]["coordinates"][0]} for f in feats[:1]]
                else:
                    r = await client.get("https://nominatim.openstreetmap.org/search",
                                         params={"q": text, "countrycodes": "au", "format": "json", "limit": 1})
                    if r.status_code == 200:
                        rows = r.json()
        except Exception as e:
            logger.error(f"Geocoding error: {e}")
        finally:
            await asyncio.sleep(1.1)
    if rows is None:  # service unavailable: don't cache, try again next time
        return None
    g = {"q": q, "lat": float(rows[0]["lat"]), "lng": float(rows[0]["lon"])} if rows else {"q": q, "lat": None, "lng": None}
    await db.geocache.update_one({"q": q}, {"$set": {**g, "at": now_iso()}}, upsert=True)
    return g if rows else None


async def geocode_entry(e: dict) -> dict:
    g = await geocode(e["address"])
    if g is None and not await db.geocache.find_one({"q": " ".join(e["address"].split()).lower()}):
        return e.get("geo") or {}  # lookup service unavailable; retry on a later map load
    geo = {"for": e["address"], "at": now_iso(), **({"lat": g["lat"], "lng": g["lng"]} if g else {"failed": True})}
    await db.directory.update_one({"entry_id": e["entry_id"]}, {"$set": {"geo": geo}})
    return geo


def needs_geo(e: dict) -> bool:
    return bool(e.get("address")) and (e.get("geo") or {}).get("for") != e["address"]


async def geocode_later(entry_id: str):
    """Called after a referral partner is added or edited so it's ready on the map."""
    e = await db.directory.find_one({"entry_id": entry_id}, P)
    if e and e["category"] == REFERRAL and needs_geo(e):
        await geocode_entry(e)


PAGE = """<!doctype html><html><head><meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="referrer" content="no-referrer">
<link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css">
<style>html,body,#map{height:100%;margin:0;font-family:Arial,sans-serif}.msg{padding:24px;color:#374151;text-align:center}
.iw b{color:#673E8D;font-size:15px}.iw div{margin-top:4px;font-size:13px;color:#374151}
.note{position:absolute;z-index:1000;bottom:8px;left:8px;right:8px;background:#fff;border-radius:10px;padding:8px 10px;font-size:12px;color:#374151;box-shadow:0 1px 4px rgba(0,0,0,.2)}</style>
</head><body>__BODY__</body></html>"""


@router.get("/referral-map", response_class=HTMLResponse)
async def referral_map(request: Request, token: Optional[str] = None, postcode: str = "", radius: Optional[int] = None):
    user = await user_from_token(bearer(request) or token)
    if not user:
        raise HTTPException(401, "Not authenticated")
    entries = await db.directory.find({"category": REFERRAL, "status": {"$ne": "pending"}}, P).to_list(500)
    pc = "".join(ch for ch in postcode if ch.isdigit())[:4]
    if len(pc) == 4 and radius is not None and radius >= 0:
        # Same postcode-number rule as the list's Same / Nearby / Wider chips
        def pc_of(e):
            m = re.findall(r"\b(\d{4})\b", e.get("address") or "")
            return int(m[-1]) if m else None
        entries = [e for e in entries if pc_of(e) is not None and abs(pc_of(e) - int(pc)) <= radius]
    for e in [e for e in entries if needs_geo(e)][:8]:
        e["geo"] = await geocode_entry(e)
    for e in [e for e in entries if needs_geo(e) and e["entry_id"] not in _queued]:
        _queued.add(e["entry_id"])
        task = asyncio.create_task(geocode_later(e["entry_id"]))
        task.add_done_callback(lambda _t, i=e["entry_id"]: _queued.discard(i))
    pins = [{"name": e["name"], "services": e.get("services", ""), "phone": e.get("phone", ""), "address": e.get("address", ""),
             "link": e.get("link", ""), "lat": e["geo"]["lat"], "lng": e["geo"]["lng"]}
            for e in entries if (e.get("geo") or {}).get("lat") is not None]
    centre = None
    if len(pc) == 4:
        g = await geocode(f"{pc}")
        if g:
            centre = {"lat": g["lat"], "lng": g["lng"], "label": f"Participant area {pc}"}
    with_address = len([e for e in entries if e.get("address")])
    note = ""
    if not entries:
        note = "No referral partners in this range. Try Wider or All." if radius is not None and len(pc) == 4 else "No referral partners yet."
    elif len(pins) < len(entries):
        note = f"Showing {len(pins)} of {len(entries)} partners. Others need a location or postcode we can find."
    data = json.dumps({"pins": pins, "centre": centre, "note": note}).replace("</", "<\\/")
    body = """<div id="map"></div><div id="note" class="note" style="display:none"></div>
<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script><script>
const D = __DATA__;
function el(tag, text){const n=document.createElement(tag); if(text) n.textContent=text; return n;}
const map = L.map('map').setView([-31.95, 115.86], 10);
L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {maxZoom: 19, attribution: '&copy; OpenStreetMap contributors'}).addTo(map);
const pts = [];
D.pins.forEach(p => {
  const box = el('div'); box.className = 'iw'; box.appendChild(el('b', p.name));
  if (p.services) box.appendChild(el('div', p.services));
  if (p.address) box.appendChild(el('div', '📍 ' + p.address));
  if (p.phone) { const a = el('a', '📞 ' + p.phone); a.href = 'tel:' + p.phone.replace(/\\s/g, ''); const d = el('div'); d.appendChild(a); box.appendChild(d); }
  if (/^https?:\\/\\//.test(p.link)) { const a = el('a', 'Website'); a.href = p.link; a.target = '_blank'; const d = el('div'); d.appendChild(a); box.appendChild(d); }
  { const a = el('a', '🧭 Get directions'); a.href = 'https://www.google.com/maps/dir/?api=1&destination=' + p.lat + ',' + p.lng; a.target = '_blank'; a.rel = 'noopener'; a.style.fontWeight = '700'; const d = el('div'); d.appendChild(a); box.appendChild(d); }
  L.marker([p.lat, p.lng], {title: p.name}).addTo(map).bindPopup(box);
  pts.push([p.lat, p.lng]);
});
if (D.centre) {
  L.circleMarker([D.centre.lat, D.centre.lng], {radius: 9, color: '#fff', weight: 2, fillColor: '#673E8D', fillOpacity: 1}).addTo(map).bindTooltip(D.centre.label);
  map.setView([D.centre.lat, D.centre.lng], 11);
} else if (pts.length > 1) { map.fitBounds(pts, {padding: [30, 30]}); } else if (pts.length === 1) { map.setView(pts[0], 12); }
if (D.note) { const n = document.getElementById('note'); n.textContent = D.note; n.style.display = 'block'; }
</script>"""
    return HTMLResponse(PAGE.replace("__BODY__", body.replace("__DATA__", data)),
                        headers={"X-Map-Pins": str(len(pins)), "X-Map-With-Address": str(with_address)})


@router.get("/referral-map/summary")
async def referral_map_summary(request: Request):
    user = await user_from_token(bearer(request))
    if not user:
        raise HTTPException(401, "Not authenticated")
    entries = await db.directory.find({"category": REFERRAL, "status": {"$ne": "pending"}}, {"_id": 0, "address": 1, "geo": 1}).to_list(500)
    return {"configured": True, "total": len(entries),
            "located": len([e for e in entries if (e.get("geo") or {}).get("lat") is not None]),
            "no_address": len([e for e in entries if not e.get("address")])}
