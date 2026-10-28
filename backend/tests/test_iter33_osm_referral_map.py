# Iteration 33: Referral map on Leaflet + OSM (Photon/Nominatim geocoding), activity-poll lock description
import os
import time
from datetime import datetime, timezone

import pytest
import requests
from dotenv import load_dotenv
from pymongo import MongoClient

load_dotenv("/app/frontend/.env")
load_dotenv("/app/backend/.env")
BASE_URL = os.environ.get("EXPO_PUBLIC_BACKEND_URL").rstrip("/")
API = f"{BASE_URL}/api"
db = MongoClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]
ADMIN = {"Authorization": "Bearer test_session_admin"}
EMP = {"Authorization": "Bearer test_session_employee"}
REF = "Trusted Referral Partner Organisations"
STATE = {"events": []}


@pytest.fixture(scope="module", autouse=True)
def cleanup():
    since = datetime.now(timezone.utc).isoformat()
    yield
    db.directory.delete_many({"name": {"$regex": "^TEST_"}})
    db.events.delete_many({"event_id": {"$in": STATE["events"]}})
    db.notifications.delete_many({"created_at": {"$gte": since}, "type": {"$in": ["directory", "event"]}})


def ref(name, address, **kw):
    return {"space": "therapist", "category": REF, "name": name, "address": address, "services": "OT", **kw}


def map_get(params, headers=None):
    return requests.get(f"{API}/referral-map", params=params, headers=headers or {}, timeout=60)


# ---- Map page
class TestReferralMap:
    def test_create_two_partners_and_bg_geocode(self):
        for n, a in [("TEST_Joondalup Therapy", "Joondalup WA 6027"), ("TEST_Fremantle Allied", "Fremantle WA 6160")]:
            r = requests.post(f"{API}/directory", json=ref(n, a, phone="08 9000 0000"), headers=ADMIN)
            assert r.status_code == 200, r.text
            assert r.json()["status"] == "approved"
            STATE.setdefault("ids", []).append(r.json()["entry_id"])
        # background geocode on add (serialised ~1.1s/request)
        deadline = time.time() + 20
        while time.time() < deadline:
            docs = list(db.directory.find({"entry_id": {"$in": STATE["ids"]}}, {"_id": 0, "geo": 1}))
            if all((d.get("geo") or {}).get("lat") is not None for d in docs):
                break
            time.sleep(1.5)
        docs = {d["entry_id"]: d for d in db.directory.find({"entry_id": {"$in": STATE["ids"]}}, {"_id": 0})}
        g1, g2 = docs[STATE["ids"][0]]["geo"], docs[STATE["ids"][1]]["geo"]
        assert g1["for"] == "Joondalup WA 6027" and -32.0 < g1["lat"] < -31.5 and 115.5 < g1["lng"] < 116.0, g1
        assert g2["for"] == "Fremantle WA 6160" and -32.2 < g2["lat"] < -31.9 and 115.6 < g2["lng"] < 115.9, g2

    def test_map_html_leaflet_and_pins(self):
        r = map_get({"token": "test_session_admin"})
        assert r.status_code == 200, r.text
        assert "text/html" in r.headers["content-type"]
        h = r.text
        assert "leaflet@1.9.4/dist/leaflet.js" in h and "tile.openstreetmap.org" in h
        assert "maps.googleapis" not in h
        assert "TEST_Joondalup Therapy" in h and "TEST_Fremantle Allied" in h
        assert int(r.headers["X-Map-Pins"]) >= 2
        assert int(r.headers["X-Map-With-Address"]) >= 2
        assert '"centre": null' in h
        assert "fitBounds" in h

    def test_map_bearer_header_works(self):
        r = map_get({}, headers=EMP)
        assert r.status_code == 200 and int(r.headers["X-Map-Pins"]) >= 2

    def test_map_with_postcode_centre(self):
        r = map_get({"token": "test_session_employee", "postcode": "6000"})
        assert r.status_code == 200
        assert '"label": "Participant area 6000"' in r.text
        assert "circleMarker" in r.text

    def test_map_unauthenticated(self):
        assert map_get({}).status_code == 401
        assert map_get({"token": "bogus"}).status_code == 401

    def test_no_address_note(self):
        r = requests.post(f"{API}/directory", json=ref("TEST_No Address Org", ""), headers=ADMIN)
        assert r.status_code == 200
        STATE["noaddr"] = r.json()["entry_id"]
        r = map_get({"token": "test_session_admin"})
        pins = int(r.headers["X-Map-Pins"])
        total = db.directory.count_documents({"category": REF, "status": {"$ne": "pending"}})
        assert pins < total
        assert f"Showing {pins} of {total} partners" in r.text

    def test_pending_not_on_map(self):
        r = requests.post(f"{API}/directory", json=ref("TEST_Pending Org", "Joondalup WA 6027"), headers=EMP)
        assert r.status_code == 200 and r.json()["status"] == "pending"
        r = map_get({"token": "test_session_admin"})
        assert "TEST_Pending Org" not in r.text

    def test_xss_escaped(self):
        r = requests.post(f"{API}/directory", json=ref("TEST_</script><script>alert(1)</script>", "Joondalup WA 6027"), headers=ADMIN)
        assert r.status_code == 200
        time.sleep(1)
        h = map_get({"token": "test_session_admin"}).text
        assert "</script><script>alert(1)" not in h

    def test_summary(self):
        r = requests.get(f"{API}/referral-map/summary", headers=EMP)
        assert r.status_code == 200
        s = r.json()
        assert s["configured"] is True and s["located"] >= 2 and s["no_address"] >= 1

    def test_edit_address_regeocodes(self):
        eid = STATE["ids"][1]
        r = requests.put(f"{API}/directory/{eid}", json=ref("TEST_Fremantle Allied", "Joondalup WA 6027"), headers=ADMIN)
        assert r.status_code == 200
        time.sleep(3)  # cached query -> fast
        g = db.directory.find_one({"entry_id": eid})["geo"]
        assert g["for"] == "Joondalup WA 6027" and -32.0 < g["lat"] < -31.5


# ---- Activity poll lock description
class TestActivityLock:
    def test_lock_updates_description(self):
        ids = []
        for i in range(2):
            r = requests.post(f"{API}/directory", json={"space": "participant", "category": "Activities", "name": f"TEST_Act33 {i}",
                                                        "address": f"{i} Beach Rd WA"}, headers=ADMIN)
            ids.append(r.json()["entry_id"])
        r = requests.post(f"{API}/events/activity-vote", json={"entry_ids": ids}, headers=EMP)
        assert r.status_code == 200, r.text
        ev = r.json()
        STATE["events"].append(ev["event_id"])
        assert ev["description"].startswith("Vote for what we do next:")
        opt = ev["poll"]["options"][1]
        r = requests.post(f"{API}/events/{ev['event_id']}/poll/{opt['option_id']}/lock", headers=EMP)
        assert r.status_code == 200, r.text
        g = requests.get(f"{API}/events/{ev['event_id']}", headers=EMP).json()
        assert g["description"] == "The team voted for TEST_Act33 1."
        assert g["title"] == "TEST_Act33 1" and g["location"] == "1 Beach Rd WA"
