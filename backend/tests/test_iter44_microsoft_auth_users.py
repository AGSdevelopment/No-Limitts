# Iteration 44: Microsoft sign-in + Support Worker password auth, user types, Microsoft integrations, socials
import os
import pytest
import requests
from pymongo import MongoClient
from dotenv import load_dotenv

load_dotenv("/app/frontend/.env")
load_dotenv("/app/backend/.env")
BASE_URL = (os.environ.get("EXPO_PUBLIC_BACKEND_URL") or os.environ.get("EXPO_BACKEND_URL")).rstrip("/")
API = f"{BASE_URL}/api"
ADMIN = {"Authorization": "Bearer test_session_admin"}
ADMIN2 = {"Authorization": "Bearer test_session_admin2"}
EMP_EMAIL, EMP_PW = "emp.test@example.com", "TestWorker#2026"
mdb = MongoClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]


def reset_emp():
    mdb.users.update_one({"email": EMP_EMAIL}, {"$set": {"failed_logins": 0}, "$unset": {"locked_until": ""}})


def login(email, pw):
    return requests.post(f"{API}/auth/login", json={"email": email, "password": pw}, timeout=30)


@pytest.fixture
def cleanup():
    ids = []
    yield ids
    for uid in ids:
        requests.delete(f"{API}/users/{uid}", headers=ADMIN, timeout=30)
        mdb.users.delete_one({"user_id": uid})


# ---- Password login
class TestPasswordLogin:
    def test_worker_login_ok(self):
        reset_emp()
        r = login(EMP_EMAIL, EMP_PW)
        assert r.status_code == 200, r.text
        d = r.json()
        assert d["session_token"] and d["user"]["email"] == EMP_EMAIL
        assert d["user"].get("user_type") == "support_worker"
        assert not d["user"].get("must_change_password")

    def test_login_response_does_not_leak_password_hash(self):
        reset_emp()
        r = login(EMP_EMAIL, EMP_PW)
        assert "password_hash" not in r.json()["user"], "password_hash leaked in /auth/login user"
        me = requests.get(f"{API}/auth/me", headers={"Authorization": f"Bearer {r.json()['session_token']}"}, timeout=30)
        assert "password_hash" not in me.json(), "password_hash leaked in /auth/me"

    def test_wrong_password_401(self):
        reset_emp()
        r = login(EMP_EMAIL, "nope-12345")
        assert r.status_code == 401
        reset_emp()

    def test_lockout_after_5(self):
        reset_emp()
        codes = [login(EMP_EMAIL, f"bad{i}xx").status_code for i in range(5)]
        assert codes == [401] * 5
        r = login(EMP_EMAIL, EMP_PW)
        assert r.status_code == 429
        reset_emp()
        assert login(EMP_EMAIL, EMP_PW).status_code == 200

    def test_unknown_email_401(self):
        assert login("nobody.TEST@example.com", "whatever1").status_code == 401

    def test_office_user_with_password_rejected(self, cleanup):
        r = requests.post(f"{API}/users", headers=ADMIN, json={"name": "TEST Office", "email": "test_office44@example.com",
                                                                "user_type": "support_office"}, timeout=30)
        assert r.status_code == 200, r.text
        uid = r.json()["user"]["user_id"]
        cleanup.append(uid)
        assert r.json()["temporary_password"] is None
        # office user has no password at all -> 401
        assert login("test_office44@example.com", "anything1").status_code == 401
        # force a password onto the office user -> 400 "sign in with Microsoft"
        import bcrypt
        mdb.users.update_one({"user_id": uid}, {"$set": {"password_hash": bcrypt.hashpw(b"Office#123", bcrypt.gensalt()).decode()}})
        r2 = login("test_office44@example.com", "Office#123")
        assert r2.status_code == 400 and "Microsoft" in r2.json()["detail"]


# ---- Admin user management + forced password change
class TestUsers:
    def test_create_worker_flow(self, cleanup):
        r = requests.post(f"{API}/users", headers=ADMIN, json={"name": "TEST Worker", "email": "TEST_worker44@example.com",
                                                                "user_type": "support_worker", "job_title": "SW"}, timeout=30)
        assert r.status_code == 200, r.text
        d = r.json()
        uid = d["user"]["user_id"]
        cleanup.append(uid)
        assert d["user"]["email"] == "test_worker44@example.com" and d["user"]["role"] == "employee"
        assert "password_hash" not in d["user"]
        tmp = d["temporary_password"]
        assert tmp and len(tmp) >= 8
        # listed
        assert any(u["user_id"] == uid for u in requests.get(f"{API}/users", headers=ADMIN, timeout=30).json())
        # duplicate
        dup = requests.post(f"{API}/users", headers=ADMIN, json={"name": "x", "email": "test_worker44@example.com",
                                                                  "user_type": "support_worker"}, timeout=30)
        assert dup.status_code == 409
        # temp login -> must change
        lr = login("test_worker44@example.com", tmp)
        assert lr.status_code == 200 and lr.json()["user"]["must_change_password"] is True
        h = {"Authorization": f"Bearer {lr.json()['session_token']}"}
        assert requests.get(f"{API}/dashboard", headers=h, timeout=30).status_code == 403
        assert requests.get(f"{API}/auth/me", headers=h, timeout=30).status_code == 200
        # weak / same password rejected
        assert requests.post(f"{API}/auth/change-password", headers=h, json={"new_password": "short"}, timeout=30).status_code == 400
        assert requests.post(f"{API}/auth/change-password", headers=h, json={"new_password": tmp}, timeout=30).status_code == 400
        cp = requests.post(f"{API}/auth/change-password", headers=h, json={"new_password": "NewPass#4421"}, timeout=30)
        assert cp.status_code == 200 and cp.json()["must_change_password"] is False
        assert requests.get(f"{API}/dashboard", headers=h, timeout=30).status_code == 200
        assert login("test_worker44@example.com", tmp).status_code == 401
        assert login("test_worker44@example.com", "NewPass#4421").status_code == 200
        # reset password -> new temp, sessions killed
        rp = requests.post(f"{API}/users/{uid}/reset-password", headers=ADMIN, timeout=30)
        assert rp.status_code == 200 and rp.json()["temporary_password"]
        assert requests.get(f"{API}/auth/me", headers=h, timeout=30).status_code == 401
        lr2 = login("test_worker44@example.com", rp.json()["temporary_password"])
        assert lr2.status_code == 200 and lr2.json()["user"]["must_change_password"] is True
        # change type -> support_office strips password
        pt = requests.patch(f"{API}/users/{uid}/type", headers=ADMIN, json={"user_type": "support_office"}, timeout=30)
        assert pt.status_code == 200 and pt.json()["user"]["user_type"] == "support_office"
        assert not mdb.users.find_one({"user_id": uid}).get("password_hash")
        assert requests.post(f"{API}/users/{uid}/reset-password", headers=ADMIN, timeout=30).status_code == 400
        # back to support_worker -> new temp password
        pt2 = requests.patch(f"{API}/users/{uid}/type", headers=ADMIN, json={"user_type": "support_worker"}, timeout=30)
        assert pt2.status_code == 200 and pt2.json()["temporary_password"]
        # admin type -> role admin
        pt3 = requests.patch(f"{API}/users/{uid}/type", headers=ADMIN, json={"user_type": "admin"}, timeout=30)
        assert pt3.json()["user"]["role"] == "admin"
        # delete -> gone
        assert requests.delete(f"{API}/users/{uid}", headers=ADMIN, timeout=30).status_code == 200
        assert not any(u["user_id"] == uid for u in requests.get(f"{API}/users", headers=ADMIN, timeout=30).json())
        assert requests.delete(f"{API}/users/{uid}", headers=ADMIN, timeout=30).status_code == 404

    def test_admin_type_no_temp_password(self, cleanup):
        r = requests.post(f"{API}/users", headers=ADMIN, json={"name": "TEST Adm", "email": "test_adm44@example.com",
                                                                "user_type": "admin"}, timeout=30)
        assert r.status_code == 200 and r.json()["temporary_password"] is None
        cleanup.append(r.json()["user"]["user_id"])

    def test_non_exec_cannot_create_exec(self):
        r = requests.post(f"{API}/users", headers=ADMIN2, json={"name": "TEST Ex", "email": "test_ex44@example.com",
                                                                 "user_type": "executive"}, timeout=30)
        assert r.status_code == 403

    def test_non_exec_cannot_change_exec(self):
        ex = mdb.users.find_one({"email": "andrewt@nolimitts.com.au"})
        assert ex, "seeded executive missing"
        r = requests.patch(f"{API}/users/{ex['user_id']}/type", headers=ADMIN2, json={"user_type": "admin"}, timeout=30)
        assert r.status_code == 403
        assert requests.delete(f"{API}/users/{ex['user_id']}", headers=ADMIN2, timeout=30).status_code == 403

    def test_bad_type_and_email(self):
        assert requests.post(f"{API}/users", headers=ADMIN, json={"name": "x", "email": "t@e.com", "user_type": "therapist"},
                             timeout=30).status_code == 400
        assert requests.post(f"{API}/users", headers=ADMIN, json={"name": "x", "email": "bad", "user_type": "admin"},
                             timeout=30).status_code == 400

    def test_employee_cannot_manage(self):
        assert requests.post(f"{API}/users", headers={"Authorization": "Bearer test_session_employee"},
                             json={"name": "x", "email": "t2@e.com", "user_type": "support_worker"}, timeout=30).status_code == 403

    def test_users_list_no_hash_and_seed_execs(self):
        us = requests.get(f"{API}/users", headers=ADMIN, timeout=30).json()
        assert all("password_hash" not in u for u in us)
        emails = {u["email"] for u in us}
        for e in ("andrewt@nolimitts.com.au", "pronathin@nolimitts.com.au", "rond@nolimitts.com.au", "justined@nolimitts.com.au"):
            assert e in emails
        assert all(u.get("user_type") in ("executive", "admin", "support_office", "support_worker") for u in us)


# ---- Microsoft sign-in (not configured)
class TestMicrosoft:
    def test_unsafe_redirect_400(self):
        r = requests.get(f"{API}/auth/microsoft/start", params={"redirect": "https://evil.com/x"}, allow_redirects=False, timeout=30)
        assert r.status_code == 400

    def test_not_configured_redirects_back(self):
        r = requests.get(f"{API}/auth/microsoft/start", params={"redirect": f"{BASE_URL}/login"}, allow_redirects=False, timeout=30)
        assert r.status_code in (302, 307)
        assert r.headers["location"].startswith(f"{BASE_URL}/login?") and "auth_error=" in r.headers["location"]

    def test_deep_link_redirect_allowed(self):
        r = requests.get(f"{API}/auth/microsoft/start", params={"redirect": "staffhub://auth"}, allow_redirects=False, timeout=30)
        assert r.status_code == 302 and r.headers["location"].startswith("staffhub://auth?auth_error=")

    def test_status(self):
        assert requests.get(f"{API}/auth/microsoft/status", timeout=30).json()["configured"] is False

    def test_session_invalid_code(self):
        assert requests.post(f"{API}/auth/session", json={"session_id": "bogus"}, timeout=30).status_code == 401

    def test_callback_bad_state(self):
        r = requests.get(f"{API}/auth/microsoft/callback", params={"state": "x", "code": "y"}, timeout=30)
        assert r.status_code == 200 and "expired" in r.text.lower()


# ---- Integrations + socials
class TestIntegrations:
    def test_sharepoint_status(self):
        r = requests.get(f"{API}/integrations/sharepoint/status", headers=ADMIN, timeout=30)
        assert r.status_code == 200 and r.json().get("configured") is False

    def test_outlook_status(self):
        r = requests.get(f"{API}/integrations/outlook-calendar/status", headers=ADMIN, timeout=30)
        assert r.status_code == 200 and r.json()["configured"] is False

    @pytest.mark.parametrize("path", ["/integrations/google-drive/status", "/integrations/google-calendar/status",
                                      "/integrations/google-chat/status"])
    def test_google_gone(self, path):
        assert requests.get(f"{API}{path}", headers=ADMIN, timeout=30).status_code == 404

    def test_teams_rejects_non_teams(self):
        conv = mdb.conversations.find_one({"type": "channel"})
        r = requests.put(f"{API}/channels/{conv['conversation_id']}/teams", headers=ADMIN,
                         json={"webhook_url": "https://chat.googleapis.com/v1/spaces/x"}, timeout=30)
        assert r.status_code == 400
        r2 = requests.put(f"{API}/channels/{conv['conversation_id']}/teams", headers=ADMIN,
                          json={"webhook_url": "https://evil.com/?x=.logic.azure.com"}, timeout=30)
        assert r2.status_code == 400

    def test_socials(self):
        r = requests.get(f"{API}/socials", headers=ADMIN, timeout=30)
        assert r.status_code == 200
        d = r.json()
        assert len(d["websites"]) == 3
        links = d["links"]
        s = str(links).lower()
        assert "linkedin" not in s
        assert "instagram.com/nolimittsptyltd" in s and "facebook.com/nolimittswa" in s
