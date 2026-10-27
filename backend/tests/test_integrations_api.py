"""StaffHub integrations tests: Claude AI (ask SSE, history, extract), Google Chat webhooks, Google Drive, Jotform forms."""
import io
import os
import json

import pytest
import requests
from pymongo import MongoClient
from dotenv import load_dotenv

load_dotenv("/app/frontend/.env")
load_dotenv("/app/backend/.env")
BASE_URL = (os.environ.get("EXPO_PUBLIC_BACKEND_URL") or os.environ.get("EXPO_BACKEND_URL")).rstrip("/")
API = f"{BASE_URL}/api"
ADMIN = "test_session_admin"
EMP = "test_session_employee"
FAKE_HOOK = "https://chat.googleapis.com/v1/spaces/TESTX/messages?key=a&token=b"


def h(tok):
    return {"Authorization": f"Bearer {tok}"}


@pytest.fixture(scope="module")
def db():
    d = MongoClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]
    yield d
    d.forms.delete_many({"title": {"$regex": "^TEST_"}})
    d.policies.delete_many({"title": {"$regex": "^TEST_"}})
    d.notifications.delete_many({"body": {"$regex": "^TEST_"}})


@pytest.fixture(scope="module")
def channel_id():
    convs = requests.get(f"{API}/conversations", headers=h(ADMIN)).json()
    ch = next(c for c in convs if c["type"] == "channel" and c["name"] == "general")
    return ch["conversation_id"]


def cert_png() -> bytes:
    from PIL import Image, ImageDraw, ImageFont
    img = Image.new("RGB", (900, 600), "white")
    d = ImageDraw.Draw(img)
    try:
        f = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 30)
        s = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 24)
    except Exception:
        f = s = ImageFont.load_default()
    d.rectangle([20, 20, 880, 580], outline="navy", width=8)
    d.text((150, 80), "Certificate of Completion", fill="navy", font=f)
    d.text((150, 180), "First Aid at Work", fill="black", font=f)
    d.text((150, 260), "Issued by: Red Cross", fill="black", font=s)
    d.text((150, 320), "Issued: 2025-03-01", fill="black", font=s)
    d.text((150, 380), "Valid until: 2028-03-01", fill="black", font=s)
    d.ellipse([700, 430, 840, 560], outline="red", width=6)
    buf = io.BytesIO()
    img.save(buf, "PNG")
    return buf.getvalue()


def cert_pdf() -> bytes:
    import pymupdf
    doc = pymupdf.open()
    p = doc.new_page()
    p.insert_text((72, 100), "Certificate of Completion", fontsize=24)
    p.insert_text((72, 160), "Fire Marshal Training", fontsize=20)
    p.insert_text((72, 210), "Issued by: Safety Council", fontsize=14)
    p.insert_text((72, 240), "Issue date: 2025-06-15", fontsize=14)
    p.insert_text((72, 270), "Expiry date: 2027-06-15", fontsize=14)
    return doc.tobytes()


# --- Claude
class TestAI:
    def test_ask_streams_and_history(self):
        requests.delete(f"{API}/ai/history", headers=h(EMP))
        r = requests.post(f"{API}/ai/ask", headers=h(EMP), json={"question": "What does the health and safety policy say? One sentence."},
                          stream=True, timeout=120)
        assert r.status_code == 200
        assert "text/event-stream" in r.headers.get("content-type", "")
        deltas, done, err = [], False, None
        for line in r.iter_lines(decode_unicode=True):
            if not line or not line.startswith("data: "):
                continue
            ev = json.loads(line[6:])
            if "delta" in ev:
                deltas.append(ev["delta"])
            if "error" in ev:
                err = ev["error"]
            if ev.get("done"):
                done = True
        assert err is None, err
        assert done and len(deltas) >= 1
        answer = "".join(deltas)
        print("ANSWER:", answer[:300], "| chunks:", len(deltas))
        hist = requests.get(f"{API}/ai/history", headers=h(EMP)).json()
        assert [m["role"] for m in hist] == ["user", "assistant"]
        assert "_id" not in hist[0]
        assert requests.delete(f"{API}/ai/history", headers=h(EMP)).status_code == 200
        assert requests.get(f"{API}/ai/history", headers=h(EMP)).json() == []

    def test_ask_empty_400_and_unauth(self):
        assert requests.post(f"{API}/ai/ask", headers=h(EMP), json={"question": "  "}).status_code == 400
        assert requests.post(f"{API}/ai/ask", json={"question": "x"}).status_code == 401

    def test_extract_png(self):
        r = requests.post(f"{API}/ai/extract-certificate", headers=h(EMP),
                          files={"file": ("cert.png", cert_png(), "image/png")}, timeout=120)
        assert r.status_code == 200, r.text
        d = r.json()
        print("PNG EXTRACT:", d)
        assert set(d) == {"title", "issuer", "issue_date", "expiry_date"}
        assert "first aid" in d["title"].lower()
        assert d["expiry_date"] == "2028-03-01"

    def test_extract_pdf(self):
        r = requests.post(f"{API}/ai/extract-certificate", headers=h(EMP),
                          files={"file": ("cert.pdf", cert_pdf(), "application/pdf")}, timeout=120)
        assert r.status_code == 200, r.text
        d = r.json()
        print("PDF EXTRACT:", d)
        assert d["expiry_date"] == "2027-06-15"
        assert d["issue_date"] == "2025-06-15"

    def test_extract_rejects_other_types(self):
        r = requests.post(f"{API}/ai/extract-certificate", headers=h(EMP),
                          files={"file": ("a.txt", b"hello", "text/plain")})
        assert r.status_code == 415


# --- Google Chat
class TestGoogleChat:
    def test_bad_url_400(self, channel_id):
        r = requests.put(f"{API}/channels/{channel_id}/google-chat", headers=h(ADMIN),
                         json={"webhook_url": "https://example.com/hook?key=a&token=b"})
        assert r.status_code == 400

    def test_employee_403(self, channel_id):
        r = requests.put(f"{API}/channels/{channel_id}/google-chat", headers=h(EMP), json={"webhook_url": FAKE_HOOK})
        assert r.status_code == 403
        assert requests.delete(f"{API}/channels/{channel_id}/google-chat", headers=h(EMP)).status_code == 403

    def test_unknown_channel_404(self):
        r = requests.put(f"{API}/channels/conv_doesnotexist/google-chat", headers=h(ADMIN), json={"webhook_url": FAKE_HOOK})
        assert r.status_code == 404

    def test_link_flag_no_leak_unlink(self, channel_id):
        r = requests.put(f"{API}/channels/{channel_id}/google-chat", headers=h(ADMIN), json={"webhook_url": FAKE_HOOK},
                         timeout=60)
        assert r.status_code == 200
        assert r.json() == {"ok": True, "test_delivered": False}
        try:
            for tok in (ADMIN, EMP):
                resp = requests.get(f"{API}/conversations", headers=h(tok))
                raw = resp.text
                assert "chat.googleapis.com" not in raw and "gchat_webhook" not in raw and "gAAAA" not in raw
                ch = next(c for c in resp.json() if c["conversation_id"] == channel_id)
                assert ch["google_chat"] is True
            # message still sends fine with webhook linked
            m = requests.post(f"{API}/conversations/{channel_id}/messages", headers=h(EMP), json={"text": "TEST_gchat mirror"})
            assert m.status_code == 200
        finally:
            d = requests.delete(f"{API}/channels/{channel_id}/google-chat", headers=h(ADMIN))
            assert d.status_code == 200
        ch = next(c for c in requests.get(f"{API}/conversations", headers=h(ADMIN)).json()
                  if c["conversation_id"] == channel_id)
        assert ch["google_chat"] is False


# --- Google Drive
class TestDrive:
    def test_status(self):
        for tok in (ADMIN, EMP):
            d = requests.get(f"{API}/integrations/google-drive/status", headers=h(tok)).json()
            assert d["configured"] is False and d["connected"] is False
            assert d["folder_name"] == "StaffHub Certificates"
        assert requests.get(f"{API}/integrations/google-drive/status", headers=h(EMP)).json()["redirect_uri"] is None

    def test_start(self):
        assert requests.post(f"{API}/integrations/google-drive/start", headers=h(ADMIN)).status_code == 409
        assert requests.post(f"{API}/integrations/google-drive/start", headers=h(EMP)).status_code == 403

    def test_files(self):
        assert requests.get(f"{API}/drive/files", headers=h(EMP)).status_code == 403
        assert requests.get(f"{API}/drive/files", headers=h(ADMIN)).status_code == 409

    def test_callback_invalid_state(self):
        r = requests.get(f"{API}/integrations/google-drive/callback?state=bad&code=x")
        assert r.status_code == 200 and "not connected" in r.text

    def test_policy_without_and_with_drive(self, db):
        r = requests.post(f"{API}/policies", headers=h(ADMIN),
                          json={"title": "TEST_Drive policy", "category": "Policy", "content": "TEST_ body"})
        assert r.status_code == 200, r.text
        assert r.json()["drive_file"] is None
        r2 = requests.post(f"{API}/policies", headers=h(ADMIN),
                           json={"title": "TEST_Drive policy2", "category": "Policy", "content": "x", "drive_file_id": "abc"})
        assert r2.status_code == 409


# --- Jotform
class TestForms:
    def test_crud_and_validation(self, db):
        r = requests.post(f"{API}/forms", headers=h(EMP), json={"title": "TEST_f", "url": "123456"})
        assert r.status_code == 403
        bad = requests.post(f"{API}/forms", headers=h(ADMIN), json={"title": "TEST_bad", "url": "https://evil.com/form"})
        assert bad.status_code == 400
        bad2 = requests.post(f"{API}/forms", headers=h(ADMIN), json={"title": "TEST_bad2", "url": "https://jotform.com.evil.com/1"})
        assert bad2.status_code == 400
        notitle = requests.post(f"{API}/forms", headers=h(ADMIN), json={"title": " ", "url": "123"})
        assert notitle.status_code == 400
        a = requests.post(f"{API}/forms", headers=h(ADMIN), json={"title": "TEST_Numeric", "url": "241234567890"})
        assert a.status_code == 200 and a.json()["url"] == "https://form.jotform.com/241234567890"
        b = requests.post(f"{API}/forms", headers=h(ADMIN),
                          json={"title": "TEST_Url", "url": "https://form.jotform.com/250001", "description": "d"})
        assert b.status_code == 200 and b.json()["url"] == "https://form.jotform.com/250001"
        lst = requests.get(f"{API}/forms", headers=h(EMP)).json()
        ids = [f["form_id"] for f in lst]
        assert a.json()["form_id"] in ids and b.json()["form_id"] in ids
        assert all("_id" not in f for f in lst)
        notes = requests.get(f"{API}/notifications", headers=h(EMP)).json()
        items = notes if isinstance(notes, list) else notes.get("items", notes.get("notifications", []))
        assert any(n.get("type") == "form" and n.get("body") == "TEST_Url" for n in items)
        assert requests.delete(f"{API}/forms/{a.json()['form_id']}", headers=h(EMP)).status_code == 403
        for f in (a, b):
            assert requests.delete(f"{API}/forms/{f.json()['form_id']}", headers=h(ADMIN)).status_code == 200
        assert requests.delete(f"{API}/forms/{a.json()['form_id']}", headers=h(ADMIN)).status_code == 404
        ids = [f["form_id"] for f in requests.get(f"{API}/forms", headers=h(EMP)).json()]
        assert a.json()["form_id"] not in ids
