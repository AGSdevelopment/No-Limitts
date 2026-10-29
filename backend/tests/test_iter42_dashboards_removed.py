# Iteration 42: Therapist/Participant/Team-plans dashboards removed; regression of home, chat, events, certs, policies, profile PDF
import os

import pytest
import requests
from dotenv import load_dotenv

load_dotenv("/app/frontend/.env")
BASE_URL = os.environ.get("EXPO_PUBLIC_BACKEND_URL", os.environ.get("EXPO_BACKEND_URL")).rstrip("/")
ADMIN = "test_session_admin"
EMP = "test_session_employee"
H = lambda t: {"Authorization": f"Bearer {t}"}


# --- Removed dashboard endpoints should be gone (404) ---
@pytest.mark.parametrize("method,path", [
    ("get", "/api/dashboards"),
    ("get", "/api/dashboards/therapist"),
    ("get", "/api/agts-dashboard/data"),
    ("post", "/api/agts-dashboard/save"),
    ("post", "/api/agts-dashboard/plans-email/test"),
    ("post", "/api/agts-dashboard/review-booked"),
    ("post", "/api/agts-dashboard/calendar-sync"),
    ("get", "/api/agts-dashboard/team-overview"),
    ("get", "/api/agts-dashboard/team-overview/pdf"),
    ("post", "/api/agts-dashboard/team-overview/email-me"),
    ("get", "/api/agts-dashboard/engine"),
    ("get", "/api/agts-dashboard/app"),
])
def test_removed_endpoints_404(method, path):
    r = getattr(requests, method)(f"{BASE_URL}{path}", headers=H(ADMIN), json={}, timeout=20)
    assert r.status_code == 404, f"{path} -> {r.status_code} {r.text[:200]}"


# --- Home summary still works with celebrations ---
class TestHome:
    def test_dashboard_admin(self):
        r = requests.get(f"{BASE_URL}/api/dashboard", headers=H(ADMIN), timeout=20)
        assert r.status_code == 200
        d = r.json()
        for k in ("cert_alerts", "events", "open_tasks", "updates", "unread_notifications", "pending_policies", "celebrations"):
            assert k in d
        assert isinstance(d["celebrations"], list)
        assert not any(k in d for k in ("dashboards", "plans", "team_plans"))

    def test_dashboard_employee_celebrations(self):
        r = requests.get(f"{BASE_URL}/api/dashboard", headers=H(EMP), timeout=20)
        assert r.status_code == 200
        cel = r.json()["celebrations"]
        print("EMP celebrations:", cel)
        assert isinstance(cel, list)

    def test_dashboard_unauth(self):
        assert requests.get(f"{BASE_URL}/api/dashboard", timeout=20).status_code == 401

    def test_me(self):
        r = requests.get(f"{BASE_URL}/api/auth/me", headers=H(ADMIN), timeout=20)
        assert r.status_code == 200 and r.json()["user_id"] == "user_testadmin01"

    def test_brand_logo(self):
        r = requests.get(f"{BASE_URL}/api/brand/logo.png", timeout=20)
        assert r.status_code == 200 and r.content[:4] == b"\x89PNG"


# --- Regression of core features ---
class TestRegression:
    @pytest.mark.parametrize("path", ["/api/conversations", "/api/events", "/api/certificates", "/api/policies", "/api/users"])
    def test_lists_admin(self, path):
        r = requests.get(f"{BASE_URL}{path}", headers=H(ADMIN), timeout=20)
        assert r.status_code == 200, r.text[:200]
        assert isinstance(r.json(), (list, dict))

    @pytest.mark.parametrize("path", ["/api/conversations", "/api/events", "/api/certificates", "/api/policies"])
    def test_lists_employee(self, path):
        r = requests.get(f"{BASE_URL}{path}", headers=H(EMP), timeout=20)
        assert r.status_code == 200, r.text[:200]

    def test_staff_profile(self):
        r = requests.get(f"{BASE_URL}/api/staff/user_testemp001/profile", headers=H(ADMIN), timeout=20)
        assert r.status_code == 200
        u = r.json()["user"]
        assert u["user_id"] == "user_testemp001" and "birthday" in u
        print("emp birthday:", u.get("birthday"), "start:", u.get("start_date"))

    def test_profile_pdf(self):
        r = requests.get(f"{BASE_URL}/api/staff/user_testemp001/profile/pdf", params={"token": ADMIN}, timeout=60)
        assert r.status_code == 200
        assert r.content[:4] == b"%PDF"
        assert b"/Image" in r.content  # logo embedded

    def test_profile_pdf_employee_forbidden(self):
        r = requests.get(f"{BASE_URL}/api/staff/user_testemp001/profile/pdf", params={"token": EMP}, timeout=30)
        assert r.status_code == 403

    def test_executive_toggle_still_exists(self):
        r = requests.get(f"{BASE_URL}/api/users", headers=H(ADMIN), timeout=20)
        assert r.status_code == 200
