"""StaffHub admin-promotion / Google Chat OAuth tests (Andrew admin, gchat start + callback, role gating).
Requires temporary session created by andrew_session.py create (deleted afterwards)."""
import os

import pytest
import requests
from dotenv import load_dotenv

load_dotenv("/app/frontend/.env")
BASE_URL = (os.environ.get("EXPO_PUBLIC_BACKEND_URL") or os.environ.get("EXPO_BACKEND_URL")).rstrip("/")
API = f"{BASE_URL}/api"
ANDREW = "test_session_andrew_tmp"
ADMIN = "test_session_admin"
EMP = "test_session_employee"


def h(tok):
    return {"Authorization": f"Bearer {tok}"}


# Auth / roles
class TestRoles:
    def test_andrew_is_admin(self):
        r = requests.get(f"{API}/auth/me", headers=h(ANDREW))
        assert r.status_code == 200, r.text
        d = r.json()
        assert d["email"] == "andrew@aspireandgrow.com.au"
        assert d["role"] == "admin"
        assert "_id" not in d

    def test_employee_is_employee(self):
        r = requests.get(f"{API}/auth/me", headers=h(EMP))
        assert r.status_code == 200
        assert r.json()["role"] == "employee"


# Google Chat OAuth start/callback/status
class TestGoogleChatOAuth:
    def test_start_as_andrew(self):
        r = requests.post(f"{API}/integrations/google-chat/start", headers=h(ANDREW), json={})
        assert r.status_code == 200, r.text
        url = r.json()["authorization_url"]
        assert url.startswith("https://accounts.google.com/")
        assert "state=" in url and "client_id=" in url

    def test_start_no_body_as_admin(self):
        r = requests.post(f"{API}/integrations/google-chat/start", headers=h(ADMIN))
        assert r.status_code == 200, r.text
        assert "accounts.google.com" in r.json()["authorization_url"]

    def test_start_forbidden_for_employee(self):
        r = requests.post(f"{API}/integrations/google-chat/start", headers=h(EMP), json={})
        assert r.status_code == 403

    def test_start_unauth(self):
        r = requests.post(f"{API}/integrations/google-chat/start", json={})
        assert r.status_code == 401

    def test_callback_bad_state(self):
        r = requests.get(f"{API}/integrations/google-chat/callback", params={"state": "bad", "code": "x"})
        assert r.status_code == 200
        assert "text/html" in r.headers.get("content-type", "")
        assert "Google Chat not connected" in r.text

    def test_callback_error_param(self):
        r = requests.get(f"{API}/integrations/google-chat/callback", params={"error": "access_denied"})
        assert r.status_code == 200
        assert "Google Chat not connected" in r.text

    def test_status_as_andrew(self):
        r = requests.get(f"{API}/integrations/google-chat/status", headers=h(ANDREW))
        assert r.status_code == 200, r.text
        d = r.json()
        assert d.get("configured") is True
        print("gchat status:", d)


# Linked channels state (read-only)
class TestLinkedChannels:
    def test_channels_linked_and_two_way(self):
        r = requests.get(f"{API}/conversations", headers=h(ANDREW))
        assert r.status_code == 200
        by = {c["name"]: c for c in r.json() if c.get("type") == "channel"}
        for name in ("Allied Health", "Celebrate the Wins"):
            assert name in by, f"{name} missing"
            assert by[name].get("google_chat"), f"{name} not linked"
            assert by[name].get("google_chat_two_way") is True, f"{name} two-way off"
