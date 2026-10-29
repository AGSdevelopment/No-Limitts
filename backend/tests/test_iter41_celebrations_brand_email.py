# Iteration 41: Birthdays (admin-set dd-mm), work anniversaries, dashboard celebrations, branded emails
import os
import sys
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest
import requests
from dotenv import load_dotenv
from pymongo import MongoClient

load_dotenv("/app/backend/.env")
sys.path.insert(0, "/app/backend")

BASE_URL = os.environ.get("EXPO_PUBLIC_BACKEND_URL", os.environ.get("EXPO_BACKEND_URL")).rstrip("/")
ADMIN = "test_session_admin"
EMP = "test_session_employee"
H = lambda t: {"Authorization": f"Bearer {t}"}
PERTH = datetime.now(ZoneInfo("Australia/Perth")).date()
TODAY_MD = PERTH.strftime("%m-%d")

db = MongoClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]


@pytest.fixture(scope="module")
def temp_users():
    """TEST_ users: a visible viewer (with session), visible bday-today user, hidden bday-today user, new starter."""
    exp = datetime.now(timezone.utc) + timedelta(days=1)
    users = [
        {"user_id": "TEST_viewer41", "name": "TEST Viewer", "email": "test_viewer41@example.com", "role": "employee"},
        {"user_id": "TEST_bday41", "name": "TEST Bday", "email": "test_bday41@example.com", "role": "employee",
         "birthday": TODAY_MD},
        {"user_id": "TEST_hidden41", "name": "TEST Hidden", "email": "test_hidden41@example.com", "role": "employee",
         "birthday": TODAY_MD, "hidden": True},
        {"user_id": "TEST_newstart41", "name": "TEST New", "email": "test_new41@example.com", "role": "employee",
         "start_date": PERTH.isoformat()},  # 0-year anniversary must NOT show
    ]
    for u in users:
        db.users.delete_many({"$or": [{"user_id": u["user_id"]}, {"email": u["email"]}]})
        db.users.insert_one(dict(u))
    db.user_sessions.insert_one({"session_token": "TEST_sess_viewer41", "user_id": "TEST_viewer41",
                                 "created_at": datetime.now(timezone.utc), "expires_at": exp})
    yield
    db.users.delete_many({"user_id": {"$regex": "^TEST_"}})
    db.user_sessions.delete_many({"session_token": "TEST_sess_viewer41"})


# Birthday PATCH endpoint
class TestBirthdayPatch:
    def test_employee_forbidden(self, temp_users):
        r = requests.patch(f"{BASE_URL}/api/staff/TEST_bday41/birthday", json={"birthday": "01-01"}, headers=H(EMP))
        assert r.status_code == 403

    def test_unknown_user_404(self):
        r = requests.patch(f"{BASE_URL}/api/staff/nope_xyz/birthday", json={"birthday": "01-01"}, headers=H(ADMIN))
        assert r.status_code == 404

    @pytest.mark.parametrize("inp,exp", [("14-03", "03-14"), ("29-02", "02-29"), ("1/7", "07-01"), (" 05-12 ", "12-05")])
    def test_valid_and_persisted(self, temp_users, inp, exp):
        r = requests.patch(f"{BASE_URL}/api/staff/TEST_viewer41/birthday", json={"birthday": inp}, headers=H(ADMIN))
        assert r.status_code == 200, r.text
        assert r.json()["birthday"] == exp
        p = requests.get(f"{BASE_URL}/api/staff/TEST_viewer41/profile", headers=H(ADMIN))
        assert p.status_code == 200
        assert p.json()["user"]["birthday"] == exp

    @pytest.mark.parametrize("inp", ["31-02", "32-01", "00-05", "12-13", "abc", "2000-03-14", "14-03-1990"])
    def test_invalid_400(self, temp_users, inp):
        r = requests.patch(f"{BASE_URL}/api/staff/TEST_viewer41/birthday", json={"birthday": inp}, headers=H(ADMIN))
        assert r.status_code == 400, f"{inp}: {r.status_code} {r.text}"

    @pytest.mark.parametrize("body", [{"birthday": ""}, {"birthday": None}, {}])
    def test_empty_clears(self, temp_users, body):
        requests.patch(f"{BASE_URL}/api/staff/TEST_viewer41/birthday", json={"birthday": "01-01"}, headers=H(ADMIN))
        r = requests.patch(f"{BASE_URL}/api/staff/TEST_viewer41/birthday", json=body, headers=H(ADMIN))
        assert r.status_code == 200 and r.json()["birthday"] is None
        assert db.users.find_one({"user_id": "TEST_viewer41"})["birthday"] is None


# Dashboard celebrations
class TestCelebrations:
    def _cel(self, tok):
        r = requests.get(f"{BASE_URL}/api/dashboard", headers=H(tok))
        assert r.status_code == 200, r.text
        return r.json()["celebrations"]

    def test_hidden_viewer_sees_test_data(self, temp_users):
        cel = self._cel(EMP)  # test employee is hidden -> sees everyone
        bd = [c for c in cel if c["user_id"] == "user_testemp001" and c["type"] == "birthday"]
        an = [c for c in cel if c["user_id"] == "user_testadmin01" and c["type"] == "anniversary"]
        assert bd and bd[0]["name"] == "Erin Employee"
        assert an and an[0]["years"] == PERTH.year - 2023
        assert any(c["user_id"] == "TEST_hidden41" for c in cel)
        assert all("_id" not in c for c in cel)

    def test_admin_sees_same(self, temp_users):
        cel = self._cel(ADMIN)
        assert any(c["user_id"] == "user_testemp001" and c["type"] == "birthday" for c in cel)
        assert any(c["user_id"] == "user_testadmin01" and c["type"] == "anniversary" for c in cel)

    def test_visible_viewer_excludes_hidden(self, temp_users):
        cel = self._cel("TEST_sess_viewer41")
        ids = {c["user_id"] for c in cel}
        assert "TEST_bday41" in ids
        assert "TEST_hidden41" not in ids
        assert "user_testemp001" not in ids and "user_testadmin01" not in ids  # both test users hidden

    def test_zero_year_anniversary_excluded(self, temp_users):
        cel = self._cel(EMP)
        assert not any(c["user_id"] == "TEST_newstart41" for c in cel)

    def test_unauth(self):
        assert requests.get(f"{BASE_URL}/api/dashboard").status_code == 401


# Celebrations unit: 29 Feb on 28 Feb non-leap year
def test_feb29_on_feb28_nonleap(monkeypatch):
    import asyncio
    import routes.dashboard as d

    class FakeDT:
        @staticmethod
        def now(tz=None):
            return datetime(2027, 2, 28, 9, 0, tzinfo=tz)

    captured = {}

    class Cur:
        def __init__(self, q): captured["q"] = q
        def __aiter__(self): return self
        async def __anext__(self): raise StopAsyncIteration

    class FakeUsers:
        def find(self, q, proj): return Cur(q)

    class FakeDB:
        users = FakeUsers()

    monkeypatch.setattr(d, "datetime", FakeDT)
    monkeypatch.setattr(d, "db", FakeDB())
    asyncio.run(d.celebrations({"hidden": False}))
    assert "02-29" in captured["q"]["$or"][0]["birthday"]["$in"]


# Branded emails
class TestBrand:
    def test_logo_public(self):
        r = requests.get(f"{BASE_URL}/api/brand/logo.png")
        assert r.status_code == 200
        assert r.headers["content-type"].startswith("image/png")
        assert r.content[:8] == b"\x89PNG\r\n\x1a\n"

    def test_brand_header_safe(self):
        import email_service as es
        html = es.brand_header("<p>Hello</p>")
        assert "/api/brand/logo.png" in html and html.endswith("<p>Hello</p>")
        assert all(c in html for c in es.BRAND_STRIPE)
        assert 'src="https://' in html
        es._assert_safe_email("Subject", html)

    def test_send_email_wraps(self, monkeypatch):
        import asyncio
        import email_service as es
        sent = {}

        class Resp:
            status_code = 200
            text = "ok"

        class Client:
            def __init__(self, *a, **k): pass
            async def __aenter__(self): return self
            async def __aexit__(self, *a): pass
            async def post(self, url, headers=None, json=None):
                sent.update(json)
                return Resp()

        monkeypatch.setattr(es.httpx, "AsyncClient", Client)
        ok = asyncio.run(es.send_email(to="test@example.com", subject="Hi", html="<p>Body</p>"))
        assert ok and sent["html"].startswith('<div style="background:#FCFEFF')
        assert "/api/brand/logo.png" in sent["html"]
