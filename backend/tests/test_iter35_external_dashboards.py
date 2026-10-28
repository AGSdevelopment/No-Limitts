# External dashboards (role-gated Wix therapist dashboard)
import os
import pytest
import requests

BASE_URL = os.environ.get("EXPO_PUBLIC_BACKEND_URL", os.environ.get("EXPO_BACKEND_URL")).rstrip("/")
ADMIN = {"Authorization": "Bearer test_session_admin"}
EMP = {"Authorization": "Bearer test_session_employee"}
URL = "https://www.aspireandgrowtherapyservices.com.au/therapist-dashboard"


class TestDashboards:
    def test_admin_list(self):
        r = requests.get(f"{BASE_URL}/api/dashboards", headers=ADMIN)
        assert r.status_code == 200
        data = r.json()
        assert len(data) == 1
        assert data[0] == {"dashboard_id": "therapist-dashboard", "name": "Therapist dashboard", "url": URL}

    def test_admin_get(self):
        r = requests.get(f"{BASE_URL}/api/dashboards/therapist-dashboard", headers=ADMIN)
        assert r.status_code == 200
        assert r.json()["url"] == URL
        assert "_id" not in r.json()

    def test_admin_unknown_404(self):
        r = requests.get(f"{BASE_URL}/api/dashboards/nope-xyz", headers=ADMIN)
        assert r.status_code == 404

    def test_employee_list_empty(self):
        r = requests.get(f"{BASE_URL}/api/dashboards", headers=EMP)
        assert r.status_code == 200
        assert r.json() == []
        assert "aspireandgrow" not in r.text

    def test_employee_get_404(self):
        r = requests.get(f"{BASE_URL}/api/dashboards/therapist-dashboard", headers=EMP)
        assert r.status_code == 404
        assert r.json()["detail"] == "Dashboard not found"
        assert "aspireandgrow" not in r.text

    @pytest.mark.parametrize("path", ["/api/dashboards", "/api/dashboards/therapist-dashboard"])
    def test_unauth_401(self, path):
        r = requests.get(f"{BASE_URL}{path}")
        assert r.status_code == 401
        assert "aspireandgrow" not in r.text
