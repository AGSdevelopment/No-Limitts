"""Iter56: birthday card PDF, renewal thank-you to nudgers, renew-from-reminder (renews field), handover photo timeline."""
import os
import time
from datetime import date, datetime, timedelta, timezone

import pytest
import requests
from pymongo import MongoClient


def _env(path, key):
    for line in open(path):
        if line.startswith(key + "="):
            return line.split("=", 1)[1].strip().strip('"')


BASE_URL = (os.environ.get("EXPO_PUBLIC_BACKEND_URL") or _env("/app/frontend/.env", "EXPO_PUBLIC_BACKEND_URL")).rstrip("/")
MONGO_URL = _env("/app/backend/.env", "MONGO_URL")
DB_NAME = _env("/app/backend/.env", "DB_NAME")
ADMIN = {"Authorization": "Bearer test_session_admin"}
EMP = {"Authorization": "Bearer test_session_employee"}
PID = "par_960475e91169"
EMP_ID = "user_testemp001"
ADMIN_ID = "user_testadmin01"
PDF = b"%PDF-1.4\n1 0 obj<<>>endobj\ntrailer<<>>\n%%EOF"


@pytest.fixture(scope="module")
def db():
    c = MongoClient(MONGO_URL)
    yield c[DB_NAME]
    c.close()


def upload(h, title, expiry, renews=""):
    return requests.post(f"{BASE_URL}/api/certificates", headers=h,
                         data={"title": title, "expiry_date": expiry, "issuer": "TEST_Issuer", "renews": renews},
                         files={"file": ("cert.pdf", PDF, "application/pdf")})


# ---- Birthday card PDF ----
class TestBirthdayCardPdf:
    @pytest.fixture(autouse=True, scope="class")
    def setup(self, db):
        r = requests.post(f"{BASE_URL}/api/participants/{PID}/birthday-wall", headers=ADMIN, json={"text": "TEST_Happy birthday from the team <b>&</b>"})
        assert r.status_code == 200, r.text
        self.__class__.mid = r.json()["message_id"]
        yield
        db.birthday_messages.delete_one({"message_id": self.__class__.mid})

    def test_pdf_with_token_200(self):
        r = requests.get(f"{BASE_URL}/api/participants/{PID}/birthday-wall/pdf", params={"token": "test_session_admin"})
        assert r.status_code == 200, r.text
        assert r.headers["content-type"].startswith("application/pdf")
        assert r.content[:4] == b"%PDF" and len(r.content) > 1000
        assert "Birthday_card_Test_Birthday_Person.pdf" in r.headers.get("content-disposition", "")

    def test_pdf_with_bearer_200(self):
        r = requests.get(f"{BASE_URL}/api/participants/{PID}/birthday-wall/pdf", headers=ADMIN)
        assert r.status_code == 200 and r.content[:4] == b"%PDF"

    def test_pdf_contains_text(self):
        import pymupdf
        r = requests.get(f"{BASE_URL}/api/participants/{PID}/birthday-wall/pdf", params={"token": "test_session_admin"})
        doc = pymupdf.open(stream=r.content, filetype="pdf")
        txt = "".join(p.get_text() for p in doc)
        assert "Happy Birthday, Test!" in txt
        assert "TEST_Happy birthday from the team <b>&</b>" in txt  # escaped, rendered literally
        assert "36th birthday" in txt or "birthday" in txt

    def test_pdf_no_token_401(self):
        r = requests.get(f"{BASE_URL}/api/participants/{PID}/birthday-wall/pdf")
        assert r.status_code == 401

    def test_pdf_bad_token_401(self):
        r = requests.get(f"{BASE_URL}/api/participants/{PID}/birthday-wall/pdf", params={"token": "nope"})
        assert r.status_code == 401

    def test_pdf_unassigned_worker_403(self):
        r = requests.get(f"{BASE_URL}/api/participants/{PID}/birthday-wall/pdf", params={"token": "test_session_employee"})
        assert r.status_code == 403

    def test_pdf_unknown_404(self):
        r = requests.get(f"{BASE_URL}/api/participants/par_nope/birthday-wall/pdf", params={"token": "test_session_admin"})
        assert r.status_code == 404

    def test_pdf_wall_closed_400(self, db):
        p = db.participants.find_one({"participant_id": PID}, {"_id": 0, "profile": 1})
        dob = p["profile"]["date_of_birth"]
        try:
            far = (date.today() + timedelta(days=60)).replace(year=1990).isoformat()
            db.participants.update_one({"participant_id": PID}, {"$set": {"profile.date_of_birth": far}})
            r = requests.get(f"{BASE_URL}/api/participants/{PID}/birthday-wall/pdf", params={"token": "test_session_admin"})
            assert r.status_code == 400
            assert "7 days" in r.json()["detail"]
        finally:
            db.participants.update_one({"participant_id": PID}, {"$set": {"profile.date_of_birth": dob}})


# ---- Handover photo timeline ----
class TestHandoverTimeline:
    @pytest.fixture(autouse=True, scope="class")
    def setup(self, db):
        now = datetime.now(timezone.utc)
        self.__class__.ids = ["hph_TEST_a", "hph_TEST_b", "hph_TEST_c"]
        db.handover_photos.insert_many([
            {"photo_id": "hph_TEST_a", "participant": "test birthday person", "submission_id": "TEST_sub1", "caption": "TEST_a",
             "by_name": "Admin", "by_id": ADMIN_ID, "at": (now - timedelta(days=3)).isoformat(), "storage_path": "x"},
            {"photo_id": "hph_TEST_b", "participant": "test birthday person", "submission_id": "TEST_sub1", "caption": "TEST_b",
             "by_name": "Admin", "by_id": ADMIN_ID, "at": (now - timedelta(days=3, minutes=-5)).isoformat(), "storage_path": "x"},
            {"photo_id": "hph_TEST_c", "participant": "test birthday person", "submission_id": "TEST_sub2", "caption": "",
             "by_name": "Admin", "by_id": ADMIN_ID, "at": (now - timedelta(days=1)).isoformat(), "storage_path": "x"},
        ])
        yield
        db.handover_photos.delete_many({"photo_id": {"$in": self.__class__.ids}})

    def test_admin_grouped(self):
        r = requests.get(f"{BASE_URL}/api/participants/{PID}/handover-photos", headers=ADMIN)
        assert r.status_code == 200, r.text
        d = r.json()
        assert d["name"] == "Test Birthday Person" and d["total"] == 3
        assert [g["submission_id"] for g in d["handovers"]] == ["TEST_sub2", "TEST_sub1"]  # newest handover first
        g1 = d["handovers"][1]
        assert len(g1["photos"]) == 2 and g1["source"] == "Shift handover"
        assert set(g1["photos"][0]) == {"photo_id", "caption", "by_name", "by_id", "at"}  # no storage_path leak
        assert len(g1["date"]) == 10

    def test_employee_403(self):
        assert requests.get(f"{BASE_URL}/api/participants/{PID}/handover-photos", headers=EMP).status_code == 403

    def test_unauth_401(self):
        assert requests.get(f"{BASE_URL}/api/participants/{PID}/handover-photos").status_code == 401

    def test_unknown_404(self):
        assert requests.get(f"{BASE_URL}/api/participants/par_nope/handover-photos", headers=ADMIN).status_code == 404


# ---- Nudge -> renewal upload -> thank-you notification ----
class TestRenewalThanks:
    @pytest.fixture(autouse=True, scope="class")
    def setup(self, db):
        db.users.update_one({"user_id": EMP_ID}, {"$set": {"hidden": False}})
        self.__class__.t0 = datetime.now(timezone.utc).isoformat()
        old = (date.today() - timedelta(days=10)).isoformat()
        r = upload(EMP, "TEST_Manual Handling", old)
        assert r.status_code == 200, r.text
        self.__class__.old = r.json()["cert_id"]
        self.__class__.created = [self.__class__.old]
        yield
        db.users.update_one({"user_id": EMP_ID}, {"$set": {"hidden": True}})
        ids = self.__class__.created
        db.certificates.delete_many({"cert_id": {"$in": ids}})
        db.cert_nudges.delete_many({"cert_id": {"$in": ids}})
        db.cpd_logs.delete_many({"cert_id": {"$in": ids}})
        db.notifications.delete_many({"created_at": {"$gte": self.__class__.t0},
                                      "$or": [{"title": {"$regex": "TEST_"}}, {"body": {"$regex": "TEST_"}}]})

    def test_1_nudge_link_points_to_renew(self, db):
        r = requests.post(f"{BASE_URL}/api/certificates/{self.old}/nudge", headers=ADMIN)
        assert r.status_code == 200, r.text
        n = db.notifications.find_one({"user_id": EMP_ID, "title": "Please renew: TEST_Manual Handling"}, {"_id": 0}, sort=[("created_at", -1)])
        assert n, "nudge notification missing"
        assert n["link"] == f"/upload-certificate?renew={self.old}"

    def test_2_bogus_renews_400(self):
        r = upload(EMP, "TEST_Bogus", (date.today() + timedelta(days=300)).isoformat(), renews="cert_doesnotexist")
        assert r.status_code == 400
        assert "renewing" in r.json()["detail"]

    def test_3_other_users_cert_renews_400(self, db):
        ra = upload(ADMIN, "TEST_Admin cert", (date.today() + timedelta(days=300)).isoformat())
        assert ra.status_code == 200
        self.__class__.created.append(ra.json()["cert_id"])
        r = upload(EMP, "TEST_Bogus2", (date.today() + timedelta(days=300)).isoformat(), renews=ra.json()["cert_id"])
        assert r.status_code == 400

    def test_4_renew_with_different_title_thanks_once(self, db):
        # Different title -> only the explicit renews link makes it a renewal
        r = upload(EMP, "TEST_Totally new name", (date.today() + timedelta(days=700)).isoformat(), renews=self.old)
        assert r.status_code == 200, r.text
        new_id = r.json()["cert_id"]
        self.__class__.created.append(new_id)
        assert db.certificates.find_one({"cert_id": new_id})["renews"] == self.old
        time.sleep(2)
        thanks = list(db.notifications.find({"user_id": ADMIN_ID, "title": "✓ Emp Test renewed TEST_Manual Handling"}, {"_id": 0}))
        assert len(thanks) == 1, thanks
        assert thanks[0]["link"] == "/team-certificates" and "Thanks for the nudge" in thanks[0]["body"]
        assert db.cert_nudges.count_documents({"cert_id": self.old, "thanked": True}) >= 1
        # Another upload must not re-thank
        r2 = upload(EMP, "TEST_Manual Handling", (date.today() + timedelta(days=720)).isoformat())
        assert r2.status_code == 200
        self.__class__.created.append(r2.json()["cert_id"])
        time.sleep(2)
        assert db.notifications.count_documents({"user_id": ADMIN_ID, "title": "✓ Emp Test renewed TEST_Manual Handling"}) == 1

    def test_5_renewals_endpoint_shows_renewed(self):
        r = requests.get(f"{BASE_URL}/api/certificates/team/renewals", headers=ADMIN)
        assert r.status_code == 200
        row = next((x for x in r.json()["renewals"] if x["cert_id"] == self.old), None)
        assert row, "nudged cert missing in renewals"
        assert row["renewed"] and row["renewed"]["cert_id"] in self.created[1:]
        assert not row["renewed"].get("before_nudge")

    def test_6_team_certs_shows_renewed(self):
        r = requests.get(f"{BASE_URL}/api/certificates/team", headers=ADMIN)
        row = next((x for x in r.json()["certificates"] if x["cert_id"] == self.old), None)
        assert row and row["renewed"] and row["renewed"]["cert_id"] in self.created[1:]
