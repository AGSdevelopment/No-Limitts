# Iteration 40: No Limitts branding - logo on Staff profile PDF
import os
import pytest
import requests
import pymupdf

BASE_URL = os.environ.get("EXPO_PUBLIC_BACKEND_URL", os.environ.get("EXPO_BACKEND_URL")).rstrip("/")
ADMIN = "test_session_admin"
EMP = "test_session_employee"


def _pdf(resp):
    assert resp.status_code == 200, resp.text[:300]
    assert resp.content[:4] == b"%PDF"
    return pymupdf.open("pdf", resp.content)


def _assert_logo_top_left(doc):
    imgs = doc[0].get_images(full=True)
    assert len(imgs) >= 1, "no image on page 1"
    rects = doc[0].get_image_rects(imgs[0][0])
    assert rects, "image not placed"
    r = rects[0]
    assert r.y0 < 60 and r.x0 < 80 and r.y1 <= 122, f"logo rect unexpected: {r}"
    # content must start below logo
    blocks = [b for b in doc[0].get_text("blocks") if b[4].strip()]
    assert blocks and min(b[1] for b in blocks) >= r.y1 - 1, "text overlaps logo"
    return r


# (Team plans overview PDF tests removed in iteration 42: feature deleted, endpoint now 404)


# Staff profile PDF
class TestStaffProfilePdf:
    def test_profile_pdf_query_token(self):
        r = requests.get(f"{BASE_URL}/api/staff/user_testemp001/profile/pdf", params={"token": ADMIN}, timeout=60)
        doc = _pdf(r)
        _assert_logo_top_left(doc)
        assert "Erin Employee" in doc[0].get_text()
        assert len(doc) == 1

    def test_profile_pdf_unknown_user(self):
        r = requests.get(f"{BASE_URL}/api/staff/user_doesnotexist/profile/pdf", params={"token": ADMIN}, timeout=30)
        assert r.status_code == 404

    def test_profile_pdf_no_auth(self):
        r = requests.get(f"{BASE_URL}/api/staff/user_testemp001/profile/pdf", timeout=30)
        assert r.status_code in (401, 403)

    def test_profile_pdf_employee_forbidden(self):
        r = requests.get(f"{BASE_URL}/api/staff/user_testemp001/profile/pdf", params={"token": EMP}, timeout=30)
        assert r.status_code in (401, 403)


def test_me_name_for_welcome():
    r = requests.get(f"{BASE_URL}/api/auth/me", headers={"Authorization": f"Bearer {ADMIN}"}, timeout=30)
    assert r.status_code == 200
    assert r.json().get("name")
