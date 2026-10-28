# Iteration 28: Company Drive directory (Suppliers/Templates/Referral/Activities/Resources + files),
# AGTS favourites kinds (Eat & Drink/Coffee/WiFi / Meet, admin-only add/delete), small fixes.
import os
from pathlib import Path

import pytest
import requests
from dotenv import load_dotenv
from pymongo import MongoClient

load_dotenv("/app/backend/.env")


def _base():
    url = os.environ.get("EXPO_PUBLIC_BACKEND_URL") or os.environ.get("EXPO_BACKEND_URL")
    if not url:
        for line in Path("/app/frontend/.env").read_text().splitlines():
            if line.startswith(("EXPO_PUBLIC_BACKEND_URL=", "EXPO_BACKEND_URL=")):
                url = line.split("=", 1)[1].strip().strip('"')
                break
    return url.rstrip("/")


BASE = _base() + "/api"
ADMIN = {"Authorization": "Bearer test_session_admin"}
EMP = {"Authorization": "Bearer test_session_employee"}
mdb = MongoClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]


@pytest.fixture(scope="module", autouse=True)
def cleanup():
    yield
    mdb.directory.delete_many({"name": {"$regex": "^TEST_"}})
    mdb.places.delete_many({"name": {"$regex": "^TEST_"}})


def entry(**kw):
    d = {"space": "therapist", "category": "Suppliers", "name": "TEST_Supplier A", "contact": "Sam",
         "phone": "08 1234", "email": "a@b.com", "address": "Perth", "link": "example.com", "note": "n"}
    d.update(kw)
    return d


# --- Directory categories / list ---
def test_categories():
    r = requests.get(f"{BASE}/directory/categories", headers=EMP)
    assert r.status_code == 200
    assert r.json()["participant"] == ["Suppliers", "Activities", "Resources"]
    assert r.json()["therapist"] == ["Suppliers", "Templates", "Trusted Referral Partner Organisations"]


def test_list_requires_auth():
    assert requests.get(f"{BASE}/directory?space=therapist&category=Suppliers").status_code == 401


def test_employee_cannot_create():
    r = requests.post(f"{BASE}/directory", json=entry(), headers=EMP)
    assert r.status_code == 403


@pytest.mark.parametrize("bad", [{"space": "bad"}, {"category": "Templates", "space": "participant"}, {"name": "  "}])
def test_invalid_create_400(bad):
    r = requests.post(f"{BASE}/directory", json=entry(**bad), headers=ADMIN)
    assert r.status_code == 400, r.text


# --- Directory full CRUD + files ---
def test_directory_crud_and_files():
    r = requests.post(f"{BASE}/directory", json=entry(), headers=ADMIN)
    assert r.status_code == 200, r.text
    e = r.json()
    eid = e["entry_id"]
    assert e["link"] == "https://example.com" and e["files"] == [] and e["can_edit"] is True
    assert "_id" not in e

    # employee view list + get
    lst = requests.get(f"{BASE}/directory", params={"space": "therapist", "category": "Suppliers"}, headers=EMP).json()
    me = next(x for x in lst if x["entry_id"] == eid)
    assert me["can_edit"] is False and me["name"] == "TEST_Supplier A"
    # not visible in other category
    other = requests.get(f"{BASE}/directory", params={"space": "participant", "category": "Suppliers"}, headers=EMP).json()
    assert all(x["entry_id"] != eid for x in other)
    assert requests.get(f"{BASE}/directory/{eid}", headers=EMP).status_code == 200

    # employee forbidden on edit/delete/file upload
    assert requests.put(f"{BASE}/directory/{eid}", json=entry(), headers=EMP).status_code == 403
    assert requests.delete(f"{BASE}/directory/{eid}", headers=EMP).status_code == 403
    assert requests.post(f"{BASE}/directory/{eid}/files", files={"file": ("a.txt", b"x", "text/plain")}, headers=EMP).status_code == 403

    # update
    r = requests.put(f"{BASE}/directory/{eid}", json=entry(name="TEST_Supplier B", space="participant", category="Activities", link="http://x.org"), headers=ADMIN)
    assert r.status_code == 200, r.text
    assert r.json()["name"] == "TEST_Supplier B" and r.json()["category"] == "Activities" and r.json()["link"] == "http://x.org"
    assert requests.get(f"{BASE}/directory/{eid}", headers=EMP).json()["space"] == "participant"

    # file upload
    r = requests.post(f"{BASE}/directory/{eid}/files", files={"file": ("notes.txt", b"hello directory", "text/plain")}, headers=ADMIN)
    assert r.status_code == 200, r.text
    f = r.json()
    assert f["name"] == "notes.txt" and f["size"] == 15 and "storage_path" not in f
    fid = f["file_id"]
    got = requests.get(f"{BASE}/directory/{eid}", headers=EMP).json()
    assert [x["file_id"] for x in got["files"]] == [fid] and "storage_path" not in got["files"][0]

    # empty file
    assert requests.post(f"{BASE}/directory/{eid}/files", files={"file": ("e.txt", b"", "text/plain")}, headers=ADMIN).status_code == 400

    # download via token query & bearer; unauth 401
    d = requests.get(f"{BASE}/directory/{eid}/files/{fid}?token=test_session_employee")
    assert d.status_code == 200 and d.content == b"hello directory"
    assert requests.get(f"{BASE}/directory/{eid}/files/{fid}", headers=EMP).status_code == 200
    assert requests.get(f"{BASE}/directory/{eid}/files/{fid}").status_code == 401
    assert requests.get(f"{BASE}/directory/{eid}/files/{fid}?token=bad").status_code == 401
    assert requests.get(f"{BASE}/directory/{eid}/files/dfl_nope?token=test_session_admin").status_code == 404

    # delete file
    assert requests.delete(f"{BASE}/directory/{eid}/files/{fid}", headers=EMP).status_code == 403
    assert requests.delete(f"{BASE}/directory/{eid}/files/{fid}", headers=ADMIN).status_code == 200
    assert requests.get(f"{BASE}/directory/{eid}", headers=ADMIN).json()["files"] == []
    assert requests.delete(f"{BASE}/directory/{eid}/files/{fid}", headers=ADMIN).status_code == 404

    # delete entry
    assert requests.delete(f"{BASE}/directory/{eid}", headers=ADMIN).status_code == 200
    assert requests.get(f"{BASE}/directory/{eid}", headers=ADMIN).status_code == 404
    assert requests.delete(f"{BASE}/directory/{eid}", headers=ADMIN).status_code == 404


def test_missing_entry_404s():
    assert requests.put(f"{BASE}/directory/dir_nope", json=entry(), headers=ADMIN).status_code == 404
    assert requests.post(f"{BASE}/directory/dir_nope/files", files={"file": ("a.txt", b"x", "text/plain")}, headers=ADMIN).status_code == 404


# --- Places / AGTS favourites ---
def test_places_kinds_and_admin_only():
    assert requests.post(f"{BASE}/places", json={"name": "TEST_Cafe", "kind": "Coffee"}, headers=EMP).status_code == 403
    assert requests.post(f"{BASE}/places", json={"name": "TEST_Cafe", "kind": "Eat"}, headers=ADMIN).status_code == 400
    ids = []
    for k in ("Eat & Drink", "Coffee", "WiFi / Meet"):
        r = requests.post(f"{BASE}/places", json={"name": f"TEST_{k}", "kind": k, "link": "maps.app/x"}, headers=ADMIN)
        assert r.status_code == 200, r.text
        assert r.json()["kind"] == k and r.json()["link"].startswith("https://")
        ids.append(r.json()["place_id"])
    assert requests.post(f"{BASE}/places", json={"name": "test_coffee", "kind": "Coffee"}, headers=ADMIN).status_code == 409
    lst = requests.get(f"{BASE}/places", headers=EMP).json()
    mine = [p for p in lst if p["place_id"] in ids]
    assert len(mine) == 3 and all(p["can_delete"] is False for p in mine)
    # like still open to employee
    r = requests.post(f"{BASE}/places/{ids[0]}/like", headers=EMP)
    assert r.status_code == 200 and r.json()["liked"] is True
    assert requests.delete(f"{BASE}/places/{ids[0]}", headers=EMP).status_code == 403
    for i in ids:
        assert requests.delete(f"{BASE}/places/{i}", headers=ADMIN).status_code == 200


def test_all_places_have_new_kinds():
    lst = requests.get(f"{BASE}/places", headers=ADMIN).json()
    assert all(p["kind"] in ("Eat & Drink", "Coffee", "WiFi / Meet") for p in lst), {p["kind"] for p in lst}


# --- small fixes ---
def test_leaderboard_bad_period():
    assert requests.get(f"{BASE}/events/leaderboard?period=bad", headers=ADMIN).status_code == 400
    assert requests.get(f"{BASE}/events/leaderboard?period=all", headers=ADMIN).status_code == 200


def test_pathway_user_not_emerging_404():
    r = requests.get(f"{BASE}/pathway/user/user_testadmin01", headers=ADMIN)
    assert r.status_code == 404, r.text
    assert requests.get(f"{BASE}/pathway/user/user_testemp001", headers=ADMIN).status_code == 200
