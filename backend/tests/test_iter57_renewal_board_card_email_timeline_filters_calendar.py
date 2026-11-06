"""Iter57: renewal streak board, birthday card email + shared link, handover photo timeline filters, expiry calendar."""
import os
import sys
from datetime import datetime, timedelta, timezone

import pytest
import requests

sys.path.insert(0, os.path.dirname(__file__))
import iter57_seed as seed  # noqa: E402


def _env(path, key):
    for line in open(path):
        if line.startswith(key + "="):
            return line.split("=", 1)[1].strip().strip('"')


BASE_URL = (os.environ.get("EXPO_PUBLIC_BACKEND_URL") or _env("/app/frontend/.env", "EXPO_PUBLIC_BACKEND_URL")).rstrip("/")
ADMIN = {"Authorization": "Bearer test_session_admin"}
EMP = {"Authorization": "Bearer test_session_employee"}
PID = seed.PID


@pytest.fixture(scope="module", autouse=True)
def seeded():
    seed.cleanup()
    st = seed.seed()
    yield st
    seed.cleanup()


# ---- Renewal board ----
class TestRenewalBoard:
    def test_board_employee_row_math(self, seeded):
        r = requests.get(f"{BASE_URL}/api/certificates/renewal-board", headers=EMP)
        assert r.status_code == 200, r.text
        d = r.json()
        assert [b["streak"] for b in d["badges"]] == [1, 3, 5]
        row = next((x for x in d["rows"] if x["user_id"] == seed.EMP), None)
        assert row, d
        # latest renewal (A, on time) then B (late) -> streak 1, on_time 1, renewals 2
        assert row["renewals"] == 2 and row["on_time"] == 1 and row["streak"] == 1, row
        assert row["badge"] == {"emoji": "✅", "label": "On Time"}
        assert row["me"] is True

    def test_board_admin_me_false(self):
        r = requests.get(f"{BASE_URL}/api/certificates/renewal-board", headers=ADMIN)
        assert r.status_code == 200
        row = next(x for x in r.json()["rows"] if x["user_id"] == seed.EMP)
        assert row["me"] is False

    def test_board_unauth(self):
        assert requests.get(f"{BASE_URL}/api/certificates/renewal-board").status_code == 401

    def test_streak_badges_unit(self):
        sys.path.insert(0, "/app/backend")
        from routes.certificates import renewal_record

        def pair(i, on_time):
            old = {"cert_id": f"o{i}", "title": f"Cert{i}x", "expiry_date": f"2026-0{i}-15", "created_at": f"2025-0{i}-01"}
            up = f"2026-0{i}-10T00:00:00" if on_time else f"2026-0{i}-20T00:00:00"
            new = {"cert_id": f"n{i}", "title": f"Cert{i}x", "expiry_date": f"2027-0{i}-15", "created_at": up, "renews": f"o{i}"}
            return [old, new]
        five = sum((pair(i, True) for i in range(1, 6)), [])
        assert renewal_record(five)["badge"]["label"] == "Compliance Champion"
        three = sum((pair(i, True) for i in range(3, 6)), []) + pair(1, False)
        rec = renewal_record(three)
        assert rec["streak"] == 3 and rec["badge"]["emoji"] == "⭐" and rec["on_time"] == 3 and rec["renewals"] == 4
        late_latest = pair(1, True) + pair(2, True) + pair(3, False)
        rec = renewal_record(late_latest)
        assert rec["streak"] == 0 and rec["badge"] is None and rec["on_time"] == 2

    def test_hidden_user_excluded(self, seeded):
        seed.db.users.update_one({"user_id": seed.EMP}, {"$set": {"hidden": True}})
        try:
            rows = requests.get(f"{BASE_URL}/api/certificates/renewal-board", headers=ADMIN).json()["rows"]
            assert not any(x["user_id"] == seed.EMP for x in rows)
        finally:
            seed.db.users.update_one({"user_id": seed.EMP}, {"$set": {"hidden": False}})


# ---- Expiry calendar ----
class TestCalendar:
    def test_worker_403(self):
        assert requests.get(f"{BASE_URL}/api/certificates/team/calendar", headers=EMP).status_code == 403

    @pytest.mark.parametrize("m", ["2026-13", "2026-1", "abc", "2026-00"])
    def test_bad_month_400(self, m):
        assert requests.get(f"{BASE_URL}/api/certificates/team/calendar", params={"month": m}, headers=ADMIN).status_code == 400

    def test_default_month_has_seeded(self, seeded):
        r = requests.get(f"{BASE_URL}/api/certificates/team/calendar", headers=ADMIN)
        assert r.status_code == 200
        d = r.json()
        assert d["month"] == datetime.now().strftime("%Y-%m")
        c = next((x for x in d["certificates"] if x["cert_id"] == seeded["certs"]["cal"]), None)
        assert c and c["owner_name"] == "Emp Test" and c["renewed"] is None and "status" in c
        assert all(x["expiry_date"].startswith(d["month"]) for x in d["certificates"])

    def test_renewed_info(self, seeded):
        d = requests.get(f"{BASE_URL}/api/certificates/team/calendar", params={"month": "2026-06"}, headers=ADMIN).json()
        c = next(x for x in d["certificates"] if x["cert_id"] == seeded["certs"]["a_old"])
        assert c["renewed"]["cert_id"] == seeded["certs"]["a_new"]


# ---- Handover photo timeline filters ----
class TestTimelineFilters:
    url = f"{BASE_URL}/api/participants/{PID}/handover-photos"

    def test_unfiltered(self):
        d = requests.get(self.url, headers=ADMIN).json()
        assert d["all_total"] == 3 and d["total"] == 3
        assert {w["user_id"] for w in d["workers"]} == {seed.EMP, seed.ADMIN}
        assert [w["name"] for w in d["workers"]] == ["Alex Admin", "Emp Test"]

    def test_worker_filter(self):
        d = requests.get(self.url, params={"worker": seed.EMP}, headers=ADMIN).json()
        assert d["total"] == 2 and d["all_total"] == 3 and len(d["workers"]) == 2
        assert all(p["by_id"] == seed.EMP for g in d["handovers"] for p in g["photos"])

    def test_date_ranges(self):
        today = datetime.now(timezone(timedelta(hours=8))).date()
        f7 = (today - timedelta(days=7)).isoformat()
        f30 = (today - timedelta(days=30)).isoformat()
        assert requests.get(self.url, params={"date_from": f7}, headers=ADMIN).json()["total"] == 1
        assert requests.get(self.url, params={"date_from": f30, "date_to": today.isoformat()}, headers=ADMIN).json()["total"] == 2
        d = requests.get(self.url, params={"date_from": f30, "worker": seed.ADMIN}, headers=ADMIN).json()
        assert d["total"] == 1
        assert requests.get(self.url, params={"date_to": (today - timedelta(days=30)).isoformat()}, headers=ADMIN).json()["total"] == 1

    @pytest.mark.parametrize("p", [{"date_from": "06-11-2026"}, {"date_to": "2026-02-30"}, {"date_from": "x"}])
    def test_invalid_dates_400(self, p):
        assert requests.get(self.url, params=p, headers=ADMIN).status_code == 400

    def test_worker_forbidden(self):
        assert requests.get(self.url, headers=EMP).status_code == 403


# ---- Birthday card email ----
class TestBirthdayEmail:
    url = f"{BASE_URL}/api/participants/{PID}/birthday-wall/email"

    def test_a_worker_403(self):
        assert requests.post(self.url, json={"email": seed.FAMILY_EMAIL}, headers=EMP).status_code == 403

    def test_b_no_messages_400(self):
        if seed.db.birthday_messages.count_documents({"participant_id": PID}):
            pytest.skip("wall already has messages")
        r = requests.post(self.url, json={"email": seed.FAMILY_EMAIL}, headers=ADMIN)
        assert r.status_code == 400 and "signed" in r.json()["detail"]

    def test_c_non_contact_400(self):
        r = requests.post(self.url, json={"email": "stranger@example.com"}, headers=ADMIN)
        assert r.status_code == 400 and "key contacts" in r.json()["detail"]
        assert requests.post(self.url, json={"email": ""}, headers=ADMIN).status_code == 400

    def test_d_happy_path_and_shared_pdf(self):
        s = requests.post(f"{BASE_URL}/api/participants/{PID}/birthday-wall", json={"text": "TEST_ Happy birthday!"}, headers=ADMIN)
        assert s.status_code == 200, s.text
        seed.track("messages", s.json()["message_id"])
        before = {lk["token"] for lk in seed.db.birthday_card_links.find({"participant_id": PID})}
        r = requests.post(self.url, json={"email": seed.FAMILY_EMAIL.upper()}, headers=ADMIN)
        new = [lk for lk in seed.db.birthday_card_links.find({"participant_id": PID}) if lk["token"] not in before]
        for lk in new:
            seed.track("tokens", lk["token"])
        assert r.status_code == 200, r.text
        assert r.json() == {"sent_to": seed.FAMILY_EMAIL, "name": "TEST57 Family"}
        assert len(new) == 1 and new[0]["sent"] is True and new[0]["by_id"] == seed.ADMIN
        pdf = requests.get(f"{BASE_URL}/api/birthday-card/shared/{new[0]['token']}")
        assert pdf.status_code == 200 and pdf.content[:4] == b"%PDF"
        assert pdf.headers["content-type"].startswith("application/pdf")

    def test_d2_shared_pdf_from_valid_link(self):
        # independent of the email provider: a valid unexpired link serves the signed card PDF
        win = requests.get(f"{BASE_URL}/api/participants/{PID}/birthday-wall", headers=ADMIN).json()
        bday = win["birthday"]["date"]
        tok = "TEST57_valid_" + os.urandom(4).hex()
        seed.db.birthday_card_links.insert_one({"token": tok, "participant_id": PID, "date": bday, "turns": 36,
                                                "expires_at": (datetime.now(timezone.utc) + timedelta(days=30)).isoformat()})
        seed.track("tokens", tok)
        pdf = requests.get(f"{BASE_URL}/api/birthday-card/shared/{tok}")
        assert pdf.status_code == 200 and pdf.content[:4] == b"%PDF"

    def test_e_bad_and_expired_token_404(self):
        assert requests.get(f"{BASE_URL}/api/birthday-card/shared/nope_TEST57").status_code == 404
        tok = "TEST57_expired_" + os.urandom(4).hex()
        seed.db.birthday_card_links.insert_one({"token": tok, "participant_id": PID, "date": "2026-11-03", "turns": 36,
                                                "expires_at": "2020-01-01T00:00:00+00:00"})
        seed.track("tokens", tok)
        assert requests.get(f"{BASE_URL}/api/birthday-card/shared/{tok}").status_code == 404

    def test_f_closed_wall_400(self):
        p = seed.db.participants.find_one({"participant_id": {"$ne": PID}, "profile.date_of_birth": {"$in": [None, ""]}}, {"participant_id": 1})
        if not p:
            p = seed.db.participants.find_one({"participant_id": {"$ne": PID}, "profile": {"$exists": False}}, {"participant_id": 1})
        if not p:
            pytest.skip("no participant without DOB")
        r = requests.post(f"{BASE_URL}/api/participants/{p['participant_id']}/birthday-wall/email", json={"email": "a@example.com"}, headers=ADMIN)
        assert r.status_code == 400
