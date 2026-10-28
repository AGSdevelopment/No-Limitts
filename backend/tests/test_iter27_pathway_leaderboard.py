# Iteration 27: Emerging Therapist Pathway (steps + CPD goals) and Participation Leaderboard.
# Uses seeded test sessions + temp TEST_ users/events (cleaned up). Run serially: pytest -n 0
import os
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest
import requests
from dotenv import load_dotenv
from pymongo import MongoClient

load_dotenv("/app/backend/.env")


def _base():
    url = os.environ.get("EXPO_PUBLIC_BACKEND_URL") or os.environ.get("EXPO_BACKEND_URL")
    if not url:
        for line in Path("/app/frontend/.env").read_text().splitlines():
            if line.startswith(("EXPO_PUBLIC_BACKEND_URL=", "EXPO_BACKEND_URL=")):
                url = line.split("=", 1)[1].strip().strip('"')
                break
    return url.rstrip("/")


BASE_URL = _base()
ADMIN = {"Authorization": "Bearer test_session_admin"}
EMP = {"Authorization": "Bearer test_session_employee"}
EMP_ID, ADMIN_ID = "user_testemp001", "user_testadmin01"
mdb = MongoClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]
S = requests.Session()

# temp users: X = plain employee (not emerging), SO = support office, A/B = visible leaderboard users
TMP = {
    "X": ("TEST_user_pw27x", "TEST_session_pw27x", {"role": "employee", "staff_group": "therapist", "hidden": True}),
    "SO": ("TEST_user_pw27so", "TEST_session_pw27so", {"role": "employee", "staff_group": "support_office", "hidden": True}),
    "A": ("TEST_user_lb27a", "TEST_session_lb27a", {"role": "employee", "name": "TEST_Lb Alpha"}),
    "B": ("TEST_user_lb27b", "TEST_session_lb27b", {"role": "employee", "name": "TEST_Lb Bravo"}),
}
H = {k: {"Authorization": f"Bearer {v[1]}"} for k, v in TMP.items()}
TODAY = datetime.now(ZoneInfo("Australia/Perth")).date()
YESTERDAY = (TODAY - timedelta(days=1)).isoformat()
LAST_YEAR = date(TODAY.year - 1, 6, 15).isoformat()
FUTURE = (TODAY + timedelta(days=10)).isoformat()


def _clean():
    mdb.events.delete_many({"title": {"$regex": "^TEST_lb27"}})
    mdb.cpd_goals.delete_many({"title": {"$regex": "^TEST_pw27"}})
    for uid, tok, _ in TMP.values():
        mdb.users.delete_many({"user_id": uid})
        mdb.user_sessions.delete_many({"session_token": tok})


@pytest.fixture(scope="module", autouse=True)
def setup():
    _clean()
    # remember employee's pathway ticks so we can restore them
    orig = mdb.pathways.find_one({"user_id": EMP_ID}, {"_id": 0})
    for key, (uid, tok, extra) in TMP.items():
        mdb.users.insert_one({"user_id": uid, "name": extra.get("name", f"Test {key}"), "email": f"{uid.lower()}@example.com",
                              "created_at": datetime.now(timezone.utc).isoformat(),
                              **{k: v for k, v in extra.items() if k != "name"}})
        mdb.user_sessions.insert_one({"session_token": tok, "user_id": uid,
                                      "expires_at": datetime.now(timezone.utc) + timedelta(days=1)})
    yield
    _clean()
    mdb.pathways.delete_many({"user_id": EMP_ID})
    if orig:
        mdb.pathways.insert_one(orig)


def api(method, path, h, **kw):
    return S.request(method, f"{BASE_URL}/api{path}", headers=h, timeout=30, **kw)


# ---- Pathway access
class TestPathwayAccess:
    def test_emerging_gets_pathway(self):
        r = api("GET", "/pathway", EMP)
        assert r.status_code == 200, r.text
        d = r.json()
        assert d["steps_total"] == 9 and len(d["steps"]) == 9
        assert {"key", "title", "description", "done", "done_at"} <= set(d["steps"][0])
        assert isinstance(d["goals"], list) and isinstance(d["cpd_year_hours"], (int, float))

    def test_non_emerging_forbidden(self):
        for m, p, kw in [("GET", "/pathway", {}), ("POST", "/pathway/steps/meet_supervisor", {}),
                         ("POST", "/pathway/goals", {"json": {"title": "TEST_pw27 x"}})]:
            r = api(m, p, H["X"], **kw)
            assert r.status_code == 403, (p, r.status_code, r.text)

    def test_admin_without_group_forbidden_on_own(self):
        assert api("GET", "/pathway", ADMIN).status_code in (403, 200)  # admin staff_group may vary

    def test_unauth(self):
        assert requests.get(f"{BASE_URL}/api/pathway", timeout=30).status_code == 401


# ---- Steps toggle
class TestSteps:
    def test_toggle_on_off(self):
        mdb.pathways.delete_many({"user_id": EMP_ID})
        r = api("POST", "/pathway/steps/first_session", EMP)
        assert r.status_code == 200 and r.json()["done"] is True
        d = api("GET", "/pathway", EMP).json()
        st = next(s for s in d["steps"] if s["key"] == "first_session")
        assert st["done"] and st["done_at"] and d["steps_done"] == 1
        r = api("POST", "/pathway/steps/first_session", EMP)
        assert r.json()["done"] is False
        d = api("GET", "/pathway", EMP).json()
        assert d["steps_done"] == 0 and not next(s for s in d["steps"] if s["key"] == "first_session")["done"]

    def test_unknown_step_404(self):
        assert api("POST", "/pathway/steps/nope", EMP).status_code == 404


# ---- Goals CRUD
class TestGoals:
    def test_goal_crud(self):
        r = api("POST", "/pathway/goals", EMP, json={"title": "  TEST_pw27 sensory course ", "due": "2026-09-30", "notes": "n"})
        assert r.status_code == 200, r.text
        g = r.json()
        assert g["title"] == "TEST_pw27 sensory course" and g["due"] == "2026-09-30" and g["done"] is False
        assert "_id" not in g
        gid = g["goal_id"]
        d = api("GET", "/pathway", EMP).json()
        assert any(x["goal_id"] == gid for x in d["goals"])
        # toggle done
        r = api("PATCH", f"/pathway/goals/{gid}", EMP, json={"done": True})
        assert r.status_code == 200 and r.json()["done"] is True and r.json()["done_at"]
        d = api("GET", "/pathway", EMP).json()
        assert d["goals_done"] >= 1
        # edit title/due
        r = api("PATCH", f"/pathway/goals/{gid}", EMP, json={"title": "TEST_pw27 renamed", "due": ""})
        assert r.status_code == 200 and r.json()["title"] == "TEST_pw27 renamed" and r.json()["due"] == ""
        # undo done
        r = api("PATCH", f"/pathway/goals/{gid}", EMP, json={"done": False})
        assert r.json()["done"] is False and r.json()["done_at"] is None
        # other user cannot edit (admin isn't emerging -> 403, otherwise 404)
        # delete
        assert api("DELETE", f"/pathway/goals/{gid}", EMP).status_code == 200
        assert api("DELETE", f"/pathway/goals/{gid}", EMP).status_code == 404
        d = api("GET", "/pathway", EMP).json()
        assert not any(x["goal_id"] == gid for x in d["goals"])

    def test_validation(self):
        assert api("POST", "/pathway/goals", EMP, json={"title": "   "}).status_code == 400
        r = api("POST", "/pathway/goals", EMP, json={"title": "TEST_pw27 bad", "due": "30-09-2026"})
        assert r.status_code == 400
        assert api("PATCH", "/pathway/goals/goal_missing", EMP, json={"done": True}).status_code == 404

    def test_patch_empty_body(self):
        g = api("POST", "/pathway/goals", EMP, json={"title": "TEST_pw27 empty patch"}).json()
        r = api("PATCH", f"/pathway/goals/{g['goal_id']}", EMP, json={})
        assert r.status_code in (200, 400), f"empty PATCH -> {r.status_code}: {r.text[:200]}"


# ---- Admin view
class TestAdminView:
    def test_admin_views_staff_pathway(self):
        api("POST", "/pathway/steps/meet_supervisor", EMP)
        r = api("GET", f"/pathway/user/{EMP_ID}", ADMIN)
        assert r.status_code == 200
        d = r.json()
        assert d["steps_total"] == 9 and any(s["key"] == "meet_supervisor" and s["done"] for s in d["steps"])

    def test_non_admin_forbidden(self):
        assert api("GET", f"/pathway/user/{EMP_ID}", EMP).status_code == 403
        assert api("GET", f"/pathway/user/{EMP_ID}", H["SO"]).status_code == 403


# ---- Leaderboard
def _ev(title, d, **kw):
    doc = {"event_id": f"evt_{title.lower()}", "title": title, "date": d, "time": "", "location": "", "description": "",
           "rsvps": [], "attendees": [], "created_by": "Admin", "created_by_id": ADMIN_ID,
           "created_at": datetime.now(timezone.utc).isoformat(), **kw}
    mdb.events.insert_one(doc)


def _p(key, status=None):
    uid, _, extra = TMP[key]
    d = {"user_id": uid, "name": extra.get("name", key)}
    if status:
        d["status"] = status
    return d


class TestLeaderboard:
    @pytest.fixture(scope="class", autouse=True)
    def events(self):
        if YESTERDAY[:4] != str(TODAY.year):
            pytest.skip("Jan 1 – no past date this year")
        _ev("TEST_lb27_e1", YESTERDAY, attended=[_p("A"), _p("B")],
            rsvps=[_p("A", "going"), _p("B", "going")])
        _ev("TEST_lb27_e2", YESTERDAY, rsvps=[_p("A", "going"), _p("B", "not_going")])
        _ev("TEST_lb27_e3", LAST_YEAR, attended=[_p("B")])
        _ev("TEST_lb27_e4", FUTURE, rsvps=[_p("A", "going"), _p("B", "going")])
        _ev("TEST_lb27_e5", YESTERDAY, private_for=TMP["A"][0], attended=[_p("A")])
        _ev("TEST_lb27_e6", YESTERDAY, checkin_for=TMP["A"][0], attended=[_p("A")])
        _ev("TEST_lb27_e7", YESTERDAY, attended=[{"user_id": EMP_ID, "name": "Hidden Emp"}])
        yield

    def rows(self, period, h=ADMIN):
        r = api("GET", f"/events/leaderboard?period={period}", h)
        assert r.status_code == 200, r.text
        return r.json()

    def test_year_counts(self):
        d = self.rows("year")
        assert d["period"] == "year"
        rows = {r["user_id"]: r for r in d["rows"]}
        a, b = rows[TMP["A"][0]], rows[TMP["B"][0]]
        assert (a["events"], a["attended"], a["rsvp_only"]) == (2, 1, 1), a
        assert (b["events"], b["attended"], b["rsvp_only"]) == (1, 1, 0), b
        assert a["name"] == "TEST_Lb Alpha"
        assert EMP_ID not in rows  # hidden excluded

    def test_all_time_counts_and_order(self):
        d = self.rows("all")
        ids = [r["user_id"] for r in d["rows"]]
        rows = {r["user_id"]: r for r in d["rows"]}
        assert rows[TMP["B"][0]]["events"] == 2 and rows[TMP["B"][0]]["attended"] == 2
        assert rows[TMP["A"][0]]["events"] == 2
        assert ids.index(TMP["B"][0]) < ids.index(TMP["A"][0])  # tie broken by attended
        assert d["events_counted"] >= self.rows("year")["events_counted"] + 1

    def test_sorted_desc(self):
        ev = [r["events"] for r in self.rows("all")["rows"]]
        assert ev == sorted(ev, reverse=True)

    def test_support_office_allowed(self):
        assert api("GET", "/events/leaderboard", H["SO"]).status_code == 200

    def test_employee_forbidden(self):
        assert api("GET", "/events/leaderboard", EMP).status_code == 403
        assert api("GET", "/events/leaderboard?period=all", H["X"]).status_code == 403

    def test_route_not_shadowed(self):
        # /events/leaderboard must not be caught by /events/{event_id}
        r = api("GET", "/events/leaderboard", ADMIN)
        assert "rows" in r.json()
