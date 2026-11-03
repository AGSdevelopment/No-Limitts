"""Iter55: birthday card wall, nudge-all-expired certificates, handover photo caption edit + single nudge regression."""
import os
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
DOB = "1990-11-03"
EMP_ID = "user_testemp001"


@pytest.fixture(scope="module")
def db():
    c = MongoClient(MONGO_URL)
    yield c[DB_NAME]
    c.close()


def perth_today():
    return (datetime.now(timezone.utc) + timedelta(hours=8)).date()


def wall(h=ADMIN):
    return requests.get(f"{BASE_URL}/api/participants/{PID}/birthday-wall", headers=h)


def sign(text, h=ADMIN):
    return requests.post(f"{BASE_URL}/api/participants/{PID}/birthday-wall", headers=h, json={"text": text})


# ---- Birthday card wall ----
class TestBirthdayWall:
    @pytest.fixture(autouse=True, scope="class")
    def setup(self, db):
        db.participants.update_one({"participant_id": PID}, {"$set": {"profile.date_of_birth": perth_today().replace(year=1990).isoformat()}})
        yield
        db.participants.update_one({"participant_id": PID}, {"$set": {"profile.date_of_birth": DOB}, "$pull": {"assigned_ids": EMP_ID}})
        db.birthday_messages.delete_many({"participant_id": PID, "text": {"$regex": "^TEST_"}})

    def test_open_today(self):
        r = wall()
        assert r.status_code == 200
        d = r.json()
        assert d["open"] is True
        assert d["birthday"]["in_days"] == 0
        assert d["birthday"]["turns"] == perth_today().year - 1990
        assert d["birthday"]["date"] == perth_today().isoformat()

    def test_sign_upsert_one_per_user(self):
        r1 = sign("TEST_first message")
        assert r1.status_code == 200, r1.text
        m1 = r1.json()
        assert m1["mine"] is True and m1["can_remove"] is True and m1["text"] == "TEST_first message"
        r2 = sign("  TEST_updated message  ")
        assert r2.status_code == 200
        assert r2.json()["message_id"] == m1["message_id"]
        mine = [m for m in wall().json()["messages"] if m["mine"]]
        assert len(mine) == 1 and mine[0]["text"] == "TEST_updated message"

    def test_empty_and_too_long(self):
        assert sign("   ").status_code == 400
        assert sign("x" * 301).status_code == 400
        assert sign("TEST_" + "x" * 295).status_code == 200  # exactly 300

    def test_unassigned_worker_forbidden(self):
        assert wall(EMP).status_code == 403
        assert sign("TEST_nope", EMP).status_code == 403

    def test_assigned_worker_signs_and_admin_can_remove(self, db):
        db.participants.update_one({"participant_id": PID}, {"$addToSet": {"assigned_ids": EMP_ID}})
        r = sign("TEST_worker msg", EMP)
        assert r.status_code == 200, r.text
        mid = r.json()["message_id"]
        # admin sees worker message as not mine but removable
        am = [m for m in wall().json()["messages"] if m["message_id"] == mid][0]
        assert am["mine"] is False and am["can_remove"] is True
        # worker sees admin message as not removable
        admin_msgs = [m for m in wall(EMP).json()["messages"] if not m["mine"]]
        assert admin_msgs and all(m["can_remove"] is False for m in admin_msgs)
        # worker cannot remove admin's message
        ar = requests.delete(f"{BASE_URL}/api/participants/{PID}/birthday-wall/{admin_msgs[0]['message_id']}", headers=EMP)
        assert ar.status_code == 403
        # admin removes worker message
        d = requests.delete(f"{BASE_URL}/api/participants/{PID}/birthday-wall/{mid}", headers=ADMIN)
        assert d.status_code == 200 and d.json()["ok"] is True
        assert all(m["message_id"] != mid for m in wall().json()["messages"])
        assert requests.delete(f"{BASE_URL}/api/participants/{PID}/birthday-wall/{mid}", headers=ADMIN).status_code == 404

    def test_window_edges(self, db):
        t = perth_today()
        for off, expect in ((7, True), (-7, True), (8, False), (-8, False)):
            dob = (t + timedelta(days=off)).replace(year=1990).isoformat()
            db.participants.update_one({"participant_id": PID}, {"$set": {"profile.date_of_birth": dob}})
            d = wall().json()
            assert d["open"] is expect, (off, d)
            if expect:
                assert d["birthday"]["in_days"] == off
        # closed -> POST 400
        assert d["open"] is False and d["messages"] == []
        assert sign("TEST_closed").status_code == 400
        db.participants.update_one({"participant_id": PID}, {"$set": {"profile.date_of_birth": t.replace(year=1990).isoformat()}})

    def test_unknown_participant_404(self):
        assert requests.get(f"{BASE_URL}/api/participants/par_nope/birthday-wall", headers=ADMIN).status_code == 404


# ---- Nudge all expired + single nudge regression ----
class TestNudgeAll:
    IDS = ["cert_TEST55_exp1", "cert_TEST55_exp2", "cert_TEST55_soon", "cert_TEST55_single"]

    @pytest.fixture(autouse=True, scope="class")
    def setup(self, db):
        t = date.today()
        mk = lambda cid, days: {"cert_id": cid, "owner_id": EMP_ID, "owner_name": "Emp Test", "title": cid,
                                "expiry_date": (t + timedelta(days=days)).isoformat(), "is_deleted": False, "storage_path": "x"}
        db.certificates.insert_many([mk(self.IDS[0], -3), mk(self.IDS[1], -30), mk(self.IDS[2], 10), mk(self.IDS[3], 5)])
        db.users.update_one({"user_id": EMP_ID}, {"$set": {"hidden": False}})
        yield
        db.users.update_one({"user_id": EMP_ID}, {"$set": {"hidden": True}})
        db.certificates.delete_many({"cert_id": {"$in": self.IDS}})
        db.notifications.delete_many({"user_id": EMP_ID, "title": {"$regex": "cert_TEST55"}})

    def test_employee_forbidden(self):
        assert requests.post(f"{BASE_URL}/api/certificates/team/nudge-expired", headers=EMP).status_code == 403

    def test_nudge_all_then_zero(self, db):
        r = requests.post(f"{BASE_URL}/api/certificates/team/nudge-expired", headers=ADMIN)
        assert r.status_code == 200, r.text
        d = r.json()
        assert d["nudged"] == 2 and d["workers"] == 1, d
        c = {x["cert_id"]: x for x in db.certificates.find({"cert_id": {"$in": self.IDS}})}
        assert c[self.IDS[0]].get("nudged_at") and c[self.IDS[1]].get("nudged_at")
        assert not c[self.IDS[2]].get("nudged_at")  # expiring, not expired
        assert c[self.IDS[0]]["nudged_by_name"] == "Alex Admin"
        n = db.notifications.count_documents({"user_id": EMP_ID, "title": {"$regex": "cert_TEST55_exp"}})
        assert n == 2
        r2 = requests.post(f"{BASE_URL}/api/certificates/team/nudge-expired", headers=ADMIN).json()
        assert r2 == {"nudged": 0, "workers": 0}

    def test_single_nudge_regression(self, db):
        r = requests.post(f"{BASE_URL}/api/certificates/{self.IDS[3]}/nudge", headers=ADMIN)
        assert r.status_code == 200, r.text
        assert r.json()["nudged_by_name"] == "Alex Admin" and r.json()["nudged_at"]
        assert db.notifications.count_documents({"user_id": EMP_ID, "title": f"Please renew: {self.IDS[3]}"}) == 1
        r2 = requests.post(f"{BASE_URL}/api/certificates/{self.IDS[3]}/nudge", headers=ADMIN)
        assert r2.status_code == 400
        assert requests.post(f"{BASE_URL}/api/certificates/cert_nope/nudge", headers=ADMIN).status_code == 404
        assert requests.post(f"{BASE_URL}/api/certificates/{self.IDS[0]}/nudge", headers=EMP).status_code == 403


# ---- Handover photo caption edit ----
class TestCaption:
    @pytest.fixture(autouse=True, scope="class")
    def setup(self, db):
        base = {"submission_id": "sub_TEST55", "participant": "test birthday person", "caption": "orig",
                "storage_path": "x", "content_type": "image/png", "by_name": "x", "at": "2026-01-01T00:00:00+00:00"}
        db.handover_photos.insert_many([{**base, "photo_id": "hph_TEST55_emp", "by_id": EMP_ID},
                                        {**base, "photo_id": "hph_TEST55_other", "by_id": "user_someone_else"}])
        yield
        db.handover_photos.delete_many({"photo_id": {"$regex": "^hph_TEST55"}})

    def patch(self, pid, cap, h):
        return requests.patch(f"{BASE_URL}/api/caseload/handover/photos/{pid}", headers=h, json={"caption": cap})

    def test_uploader_edits(self, db):
        r = self.patch("hph_TEST55_emp", "  Kitchen bench  ", EMP)
        assert r.status_code == 200, r.text
        assert r.json()["caption"] == "Kitchen bench" and r.json()["photo_id"] == "hph_TEST55_emp"
        assert db.handover_photos.find_one({"photo_id": "hph_TEST55_emp"})["caption"] == "Kitchen bench"

    def test_non_uploader_worker_forbidden(self):
        assert self.patch("hph_TEST55_other", "hack", EMP).status_code == 403

    def test_manager_edits_and_truncates(self, db):
        r = self.patch("hph_TEST55_other", "y" * 250, ADMIN)
        assert r.status_code == 200
        assert len(db.handover_photos.find_one({"photo_id": "hph_TEST55_other"})["caption"]) == 200

    def test_unknown_404(self):
        assert self.patch("hph_nope", "x", ADMIN).status_code == 404
