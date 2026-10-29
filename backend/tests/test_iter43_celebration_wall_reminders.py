# Iteration 43: Celebration wall (posts/photos/delete), dashboard key+post_count, week-ahead admin reminders, old data cleanup
import asyncio
import io
import os
import sys
from datetime import date, datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch
from zoneinfo import ZoneInfo

import pytest
import requests
from dotenv import load_dotenv
from pymongo import MongoClient

load_dotenv("/app/backend/.env")
sys.path.insert(0, "/app/backend")

BASE_URL = os.environ.get("EXPO_PUBLIC_BACKEND_URL", os.environ.get("EXPO_BACKEND_URL")).rstrip("/")
ADMIN, EMP, ADMIN2 = "test_session_admin", "test_session_employee", "test_session_admin2"
H = lambda t: {"Authorization": f"Bearer {t}"}
YEAR = datetime.now(ZoneInfo("Australia/Perth")).year
ANNIV_KEY = f"anniversary-user_testadmin01-{YEAR}"
BDAY_KEY = f"birthday-user_testemp001-{YEAR}"
db = MongoClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]

PNG = (b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15\xc4\x89"
       b"\x00\x00\x00\rIDATx\x9cc\xf8\xff\xff?\x00\x05\xfe\x02\xfe\xa7V\xbd\xfa\x00\x00\x00\x00IEND\xaeB`\x82")


@pytest.fixture(scope="module", autouse=True)
def cleanup():
    yield
    db.celebration_posts.delete_many({"text": {"$regex": "^TEST_"}})
    db.celebration_posts.delete_many({"user_id": {"$regex": "^TEST_"}})
    db.notifications.delete_many({"type": "celebration", "body": {"$regex": "^TEST_"}})
    db.users.delete_many({"user_id": {"$regex": "^TEST_"}})
    db.user_sessions.delete_many({"session_token": "TEST_sess_vis43"})


@pytest.fixture(scope="module")
def visible_viewer():
    exp = datetime.now(timezone.utc) + timedelta(days=1)
    db.users.delete_many({"user_id": "TEST_vis43"})
    db.users.insert_one({"user_id": "TEST_vis43", "name": "TEST Vis", "email": "test_vis43@example.com", "role": "employee"})
    db.user_sessions.insert_one({"session_token": "TEST_sess_vis43", "user_id": "TEST_vis43",
                                 "created_at": datetime.now(timezone.utc), "expires_at": exp})
    return "TEST_sess_vis43"


# Old data cleanup
def test_old_collections_dropped():
    names = set(db.list_collection_names())
    assert not names & {"dashboards", "agts_dashboard_parts", "plan_reviews_booked", "plan_cal_events"}
    assert db.meta.count_documents({"key": {"$regex": "^agts"}}) == 0


# Dashboard celebrations include key + post_count
def test_dashboard_celebrations_key_post_count():
    r = requests.get(f"{BASE_URL}/api/dashboard", headers=H(EMP))
    assert r.status_code == 200
    cel = r.json()["celebrations"]
    a = [c for c in cel if c["key"] == ANNIV_KEY]
    assert a and a[0]["type"] == "anniversary" and isinstance(a[0]["post_count"], int) and a[0]["years"] == YEAR - 2023
    assert any(c["key"] == BDAY_KEY and c["type"] == "birthday" for c in cel)


# Wall GET + visibility
class TestWallGet:
    def test_get_wall(self):
        r = requests.get(f"{BASE_URL}/api/celebrations/{ANNIV_KEY}", headers=H(EMP))
        assert r.status_code == 200
        d = r.json()
        assert d["user_id"] == "user_testadmin01" and d["type"] == "anniversary" and d["year"] == YEAR
        assert d["years"] == YEAR - 2023 and isinstance(d["posts"], list)

    @pytest.mark.parametrize("key", ["bogus", f"party-user_testadmin01-{YEAR}", f"birthday-nouser_xyz-{YEAR}", "birthday-a-b-c-20"])
    def test_invalid_404(self, key):
        assert requests.get(f"{BASE_URL}/api/celebrations/{key}", headers=H(EMP)).status_code == 404

    def test_unauth_401(self):
        assert requests.get(f"{BASE_URL}/api/celebrations/{ANNIV_KEY}").status_code == 401

    def test_hidden_celebrant_hidden_from_visible_viewer(self, visible_viewer):
        assert requests.get(f"{BASE_URL}/api/celebrations/{ANNIV_KEY}", headers=H(visible_viewer)).status_code == 404
        r = requests.post(f"{BASE_URL}/api/celebrations/{ANNIV_KEY}/posts", data={"text": "TEST_x"}, headers=H(visible_viewer))
        assert r.status_code == 404
        dash = requests.get(f"{BASE_URL}/api/dashboard", headers=H(visible_viewer)).json()
        assert not any(c["user_id"] in ("user_testadmin01", "user_testemp001") for c in dash["celebrations"])


# Posting
class TestPosts:
    state = {}

    def test_empty_400(self):
        r = requests.post(f"{BASE_URL}/api/celebrations/{ANNIV_KEY}/posts", data={"text": "   "}, headers=H(EMP))
        assert r.status_code == 400

    def test_non_image_400(self):
        r = requests.post(f"{BASE_URL}/api/celebrations/{ANNIV_KEY}/posts", data={"text": "TEST_pdf"},
                          files={"file": ("a.pdf", b"%PDF-1.4", "application/pdf")}, headers=H(EMP))
        assert r.status_code == 400
        assert db.celebration_posts.count_documents({"text": "TEST_pdf"}) == 0

    def test_text_post_notifies_celebrant(self):
        before = db.notifications.count_documents({"user_id": "user_testadmin01", "type": "celebration"})
        r = requests.post(f"{BASE_URL}/api/celebrations/{ANNIV_KEY}/posts", data={"text": "TEST_congrats Alex"}, headers=H(EMP))
        assert r.status_code == 200, r.text
        p = r.json()
        assert p["text"] == "TEST_congrats Alex" and p["user_id"] == "user_testemp001" and p["has_photo"] is False
        assert p["can_delete"] is True and "_id" not in p and "storage_path" not in p
        self.state["text_post"] = p["post_id"]
        n = db.notifications.find_one({"user_id": "user_testadmin01", "type": "celebration"}, sort=[("created_at", -1)])
        assert db.notifications.count_documents({"user_id": "user_testadmin01", "type": "celebration"}) == before + 1
        assert n["link"] == f"/celebration/{ANNIV_KEY}" and "anniversary" in n["title"]
        # dashboard post_count reflects it
        cel = requests.get(f"{BASE_URL}/api/dashboard", headers=H(EMP)).json()["celebrations"]
        cnt = [c for c in cel if c["key"] == ANNIV_KEY][0]["post_count"]
        assert cnt == db.celebration_posts.count_documents({"key": ANNIV_KEY}) and cnt >= 1

    def test_self_post_no_notification(self):
        before = db.notifications.count_documents({"user_id": "user_testadmin01", "type": "celebration"})
        r = requests.post(f"{BASE_URL}/api/celebrations/{ANNIV_KEY}/posts", data={"text": "TEST_thanks team"}, headers=H(ADMIN))
        assert r.status_code == 200
        self.state["admin_post"] = r.json()["post_id"]
        assert db.notifications.count_documents({"user_id": "user_testadmin01", "type": "celebration"}) == before

    def test_photo_post_and_fetch(self):
        r = requests.post(f"{BASE_URL}/api/celebrations/{ANNIV_KEY}/posts",
                          files={"file": ("cake.png", io.BytesIO(PNG), "image/png")}, headers=H(EMP))
        assert r.status_code == 200, r.text
        p = r.json()
        assert p["has_photo"] is True and p["text"] == ""
        self.state["photo_post"] = p["post_id"]
        url = f"{BASE_URL}/api/celebrations/{ANNIV_KEY}/posts/{p['post_id']}/photo"
        g = requests.get(url, params={"token": EMP})
        assert g.status_code == 200 and g.headers["content-type"].startswith("image/png") and g.content == PNG
        assert requests.get(url, headers=H(ADMIN)).status_code == 200
        assert requests.get(url).status_code == 401
        assert requests.get(url, params={"token": "bad"}).status_code == 401
        # text-only post has no photo
        assert requests.get(f"{BASE_URL}/api/celebrations/{ANNIV_KEY}/posts/{self.state['text_post']}/photo",
                            params={"token": EMP}).status_code == 404

    def test_wall_lists_posts_with_can_delete(self):
        posts = requests.get(f"{BASE_URL}/api/celebrations/{ANNIV_KEY}", headers=H(ADMIN2)).json()["posts"]
        ids = [p["post_id"] for p in posts]
        assert {self.state["text_post"], self.state["admin_post"], self.state["photo_post"]} <= set(ids)
        assert all(p["can_delete"] for p in posts)  # admin2 is admin
        emp_posts = {p["post_id"]: p for p in requests.get(f"{BASE_URL}/api/celebrations/{ANNIV_KEY}", headers=H(EMP)).json()["posts"]}
        assert emp_posts[self.state["text_post"]]["can_delete"] is True
        assert emp_posts[self.state["admin_post"]]["can_delete"] is False

    def test_delete_permissions(self):
        # employee can't delete admin's post
        assert requests.delete(f"{BASE_URL}/api/celebrations/{ANNIV_KEY}/posts/{self.state['admin_post']}", headers=H(EMP)).status_code == 404
        # author deletes own
        r = requests.delete(f"{BASE_URL}/api/celebrations/{ANNIV_KEY}/posts/{self.state['text_post']}", headers=H(EMP))
        assert r.status_code == 200 and r.json()["ok"] is True
        # admin deletes others'
        assert requests.delete(f"{BASE_URL}/api/celebrations/{ANNIV_KEY}/posts/{self.state['photo_post']}", headers=H(ADMIN)).status_code == 200
        assert requests.delete(f"{BASE_URL}/api/celebrations/{ANNIV_KEY}/posts/{self.state['admin_post']}", headers=H(ADMIN)).status_code == 200
        ids = [p["post_id"] for p in requests.get(f"{BASE_URL}/api/celebrations/{ANNIV_KEY}", headers=H(EMP)).json()["posts"]]
        assert not set(self.state.values()) & set(ids)
        assert requests.delete(f"{BASE_URL}/api/celebrations/{ANNIV_KEY}/posts/{self.state['text_post']}", headers=H(EMP)).status_code == 404


# Week-ahead reminder (send_email + notify mocked; no real emails)
def test_send_week_ahead_admins_only_non_hidden():
    target = date(2031, 3, 17)
    md = "03-17"
    db.users.delete_many({"user_id": {"$in": ["TEST_cel43", "TEST_celhid43", "TEST_adm43", "TEST_admhid43"]}})
    db.users.insert_many([
        {"user_id": "TEST_cel43", "name": "TEST Celebrant", "email": "c43@example.com", "role": "employee", "birthday": md,
         "start_date": "2026-03-17"},
        {"user_id": "TEST_celhid43", "name": "TEST HiddenCel", "email": "h43@example.com", "role": "employee", "birthday": md, "hidden": True},
        {"user_id": "TEST_adm43", "name": "TEST Admin43", "email": "test_adm43@nolimitts.invalid", "role": "admin"},
        {"user_id": "TEST_admhid43", "name": "TEST AdmHid", "email": "test_admhid43@nolimitts.invalid", "role": "admin", "hidden": True},
    ])
    import routes.celebrations as rc
    with patch.object(rc, "send_email", new=AsyncMock()) as se, patch.object(rc, "notify", new=AsyncMock()) as nt:
        n = asyncio.run(rc.send_week_ahead(target))
    assert n >= 2  # birthday + 5-year anniversary for TEST_cel43
    uids = nt.call_args.args[0]
    assert "TEST_adm43" in uids and "TEST_admhid43" not in uids and "user_testadmin01" not in uids
    assert "TEST Celebrant's birthday" in nt.call_args.args[3] and "TEST HiddenCel" not in nt.call_args.args[3]
    assert "5-year work anniversary" in nt.call_args.args[3]
    tos = [c.kwargs["to"] for c in se.call_args_list]
    assert "test_adm43@nolimitts.invalid" in tos and "test_admhid43@nolimitts.invalid" not in tos
    assert not any(t.endswith("@example.com") for t in tos)
    html = [c.kwargs["html"] for c in se.call_args_list if c.kwargs["to"] == "test_adm43@nolimitts.invalid"][0]
    assert "TEST Celebrant" in html and "TEST HiddenCel" not in html and "Monday 17 March" in html
