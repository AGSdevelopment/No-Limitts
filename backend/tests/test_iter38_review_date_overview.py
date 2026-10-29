"""Iter38: booked review date (API, email section, calendar event) + admin Team plans overview."""
import asyncio
import json
import os
import sys
from datetime import date

import pytest
import requests

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from tests.test_iter36_plans_dashboard import BASE, serial  # noqa: E402
from tests.test_iter37_plans_features import ag, cal, setup, today, FakeCal  # noqa: E402,F401

ADMIN, EMP = "test_session_admin", "test_session_employee"
H = lambda t: {"Authorization": f"Bearer {t}"}


def row(name, end, months=3, booked=False, bdate=None):
    import routes.agts_dashboard as m
    return {"name": name, "end": end, "rev": m._addmonths(end, -months), "booked": booked, "booked_date": bdate,
            "forms": {"ra": ("ok", None), "pep": ("ok", None)}}


# ---------------- Unit: plans_email 'Reviews booked this month'
class TestEmailBookedSection:
    T = serial(date(2026, 3, 10))

    def test_booked_section_in_month_only(self):
        import routes.agts_dashboard as m
        T = self.T
        rows = [row("Book In", T + 60, booked=True, bdate=T + 5), row("Book Next", T + 70, booked=True, bdate=T + 40),
                row("Book Past", T + 80, booked=True, bdate=T - 2), row("Book Nodate", T + 90, booked=True)]
        subj, html = m.plans_email("Sam", rows, T)
        assert "Reviews booked this month (1)" in html and "Book In" in html and "review booked for 15 Mar 2026" in html
        assert "Book Next" not in html and "Book Past" not in html and "Book Nodate" not in html
        assert subj.startswith("Your participant plans: 0 reviews")
        from email_service import _assert_safe_email
        _assert_safe_email(subj, html)

    def test_booked_month_end_boundary_and_only_booked_sends(self):
        import routes.agts_dashboard as m
        T = self.T
        assert m.plans_email("Sam", [row("Edge", T + 120, booked=True, bdate=serial(date(2026, 3, 31)))], T) is not None
        assert m.plans_email("Sam", [row("Apr", T + 120, booked=True, bdate=serial(date(2026, 4, 1)))], T) is None


# ---------------- Unit: calendar 'Plan review booked' event
class TestCalendarBooked:
    def names(self, fc):
        return sorted((b["summary"], b["start"]["date"]) for s, b in fc.events.values() if s == "svc:u_saraya")

    def test_booked_event_add_move_remove(self, ag, cal, monkeypatch):  # noqa: F811
        import routes.agts_dashboard as m
        T = today()
        cl = [{"name": "Bk One", "tags": "Saraya's Clients", "end": T + 200}]
        fdb = setup(ag, monkeypatch, cl, [])
        key = f"bk one|{T + 200}"
        fdb.plan_reviews_booked.docs.append({"key": key, "booked_by_name": "X", "booked_at": "t", "review_date": T + 10})
        r = asyncio.run(m.sync_plan_calendar())
        got = self.names(cal)
        d10 = (date(1899, 12, 30).toordinal() + T + 10)
        assert ("Plan review booked: Bk One", date.fromordinal(d10).isoformat()) in got
        assert not any(g[0].startswith("Plan review due") for g in got) and r["added"] == 2
        assert any(e["ekey"] == f"bk|{key}|{T + 10}" for e in fdb.plan_cal_events.docs)
        # date change -> old event removed, new added
        fdb.plan_reviews_booked.docs[0]["review_date"] = T + 20
        assert asyncio.run(m.sync_plan_calendar()) == {"added": 1, "removed": 1}
        assert [g for g in self.names(cal) if "booked" in g[0]][0][1] == date.fromordinal(d10 + 10).isoformat()
        # past booked date -> no event
        fdb.plan_reviews_booked.docs[0]["review_date"] = T - 1
        assert asyncio.run(m.sync_plan_calendar()) == {"added": 0, "removed": 1}
        # unbook -> review due event restored, no booked event
        fdb.plan_reviews_booked.docs.clear()
        r = asyncio.run(m.sync_plan_calendar())
        got = self.names(cal)
        assert r == {"added": 1, "removed": 0} and "Plan review due: Bk One" in [g[0] for g in got]
        assert not any("booked" in g[0] for g in got)


# ---------------- Unit: team_overview logic with fakes
class TestTeamOverviewUnit:
    def test_excludes_test_pages_and_booked(self, ag, monkeypatch):  # noqa: F811
        import routes.agts_dashboard as m
        T = today()
        cl = [{"name": "Ov Due", "tags": "Saraya's Clients", "end": T + 20}, {"name": "Ov Book", "tags": "Saraya's Clients", "end": T + 21},
              {"name": "Ov Soon", "tags": "Saraya's Clients", "end": T + 100}, {"name": "Ov Ok", "tags": "Saraya's Clients", "end": T + 300}]
        pages = [{"dashboard_id": "plans-saraya", "embed": "agts-nk", "users": ["u_saraya"], "tag": "Saraya's Clients", "name": "S"},
                 {"dashboard_id": "plans-test", "embed": "agts-nk", "users": ["u_t"], "tag": "Saraya's Clients", "test": True}]
        fdb = setup(ag, monkeypatch, cl, [], pages=pages)
        fdb.plan_reviews_booked.docs.append({"key": f"ov book|{T + 21}", "review_date": T + 3})
        d = asyncio.run(m.team_overview({"role": "admin"}))
        assert [p["dashboard_id"] for p in d["pages"]] == ["plans-saraya"]
        p = d["pages"][0]
        # plans ending within 30 days are shown under ending_30 only (same as the page's alert box), not as overdue
        assert [x["name"] for x in p["overdue"]] == [] and p["owners"] == ["Saraya X"] and p["participants"] == 4
        assert [x["name"] for x in p["booked"]] == ["Ov Book"] and p["booked"][0]["review"]
        assert {x["name"] for x in p["ending_30"]} == {"Ov Due", "Ov Book"}
        assert len(p["forms"]) == 4 and d["totals"]["overdue"] == 0 and d["review_months"] == 3


# ---------------- Live API (public URL)
def post(path, token=None, page="plans-test", **kw):
    return requests.post(f"{BASE}/api/agts-dashboard/{path}", params={"page": page}, headers=H(token) if token else {}, timeout=60, **kw)


@pytest.fixture(scope="module")
def live():
    r = requests.get(f"{BASE}/api/agts-dashboard/data", params={"view": "nk", "page": "plans-test", "token": EMP}, timeout=60)
    assert r.status_code == 200
    T = today()
    cs = [c for c in json.loads(r.json()["preview"]["data"])["nikki"]["clients"]
          if isinstance(c.get("end"), (int, float)) and c["end"] > T and not c.get("archived")]
    if not cs:
        pytest.skip("no live participant")
    yield cs
    for c in cs:  # ALWAYS undo bookings
        post("review-booked", EMP, json={"name": c["name"], "end": int(c["end"]), "booked": False})


class TestReviewDateLive:
    def test_book_with_date_change_and_unbook(self, live):
        c = live[0]
        name, end = c["name"], int(c["end"])
        key = f"{name.strip().lower()}|{end}"
        try:
            r = post("review-booked", EMP, json={"name": name, "end": end, "booked": True, "date": end - 30})
            assert r.status_code == 200, r.text
            assert r.json()["booked"][key]["date"] == end - 30 and r.json()["booked"][key]["by"]
            r = post("review-booked", EMP, json={"name": name, "end": end, "booked": True, "date": end - 20})
            assert r.json()["booked"][key]["date"] == end - 20
            d = requests.get(f"{BASE}/api/agts-dashboard/data", params={"view": "nk", "page": "plans-test", "token": EMP}, timeout=60).json()
            assert json.loads(d["preview"]["data"])["nikki"]["booked"][key]["date"] == end - 20
            r = post("review-booked", EMP, json={"name": name, "end": end, "booked": True})
            assert r.status_code == 200 and r.json()["booked"][key]["date"] is None
        finally:
            r = post("review-booked", EMP, json={"name": name, "end": end, "booked": False})
        assert r.status_code == 200 and key not in r.json()["booked"]

    def test_unreasonable_dates_400(self, live):
        c = live[0]
        name, end = c["name"], int(c["end"])
        key = f"{name.strip().lower()}|{end}"
        for bad in (end - 801, end + 401, 0, 99999999):
            r = post("review-booked", EMP, json={"name": name, "end": end, "booked": True, "date": bad})
            assert r.status_code == 400 and "doesn't look right" in r.text
        for edge in (end - 800, end + 400):
            r = post("review-booked", EMP, json={"name": name, "end": end, "booked": True, "date": edge})
            assert r.status_code == 200
        r = post("review-booked", EMP, json={"name": name, "end": end, "booked": False})
        assert key not in r.json()["booked"]
        assert post("review-booked", EMP, json={"name": name, "end": end, "booked": True, "date": "abc"}).status_code == 422


class TestTeamOverviewLive:
    def get(self, token=None):
        return requests.get(f"{BASE}/api/agts-dashboard/team-overview", headers=H(token) if token else {}, timeout=60)

    def test_auth(self):
        assert self.get().status_code == 401
        assert self.get(EMP).status_code == 403

    def test_shape_and_test_page_excluded(self):
        r = self.get(ADMIN)
        assert r.status_code == 200
        d = r.json()
        assert set(d) >= {"pages", "totals", "today", "review_months"}
        ids = [p["dashboard_id"] for p in d["pages"]]
        assert "plans-test" not in ids and len(ids) >= 1
        for p in d["pages"]:
            assert set(p) >= {"dashboard_id", "name", "owners", "participants", "overdue", "due_30", "ending_30", "booked", "forms"}
        assert d["totals"]["overdue"] == sum(len(p["overdue"]) for p in d["pages"])

    def test_booked_excluded_from_overdue(self, live):
        d = self.get(ADMIN).json()
        sar = next((p for p in d["pages"] if p["dashboard_id"] == "plans-saraya"), None)
        if not sar or not sar["overdue"]:
            pytest.skip("no overdue review on Saraya page")
        live_names = {c["name"]: int(c["end"]) for c in live}
        target = next((o for o in sar["overdue"] if o["name"] in live_names), None)
        if not target:
            pytest.skip("overdue participant not on plans-test page")
        name, end = target["name"], live_names[target["name"]]
        try:
            assert post("review-booked", EMP, json={"name": name, "end": end, "booked": True, "date": end - 10}).status_code == 200
            sar2 = next(p for p in self.get(ADMIN).json()["pages"] if p["dashboard_id"] == "plans-saraya")
            assert name not in [o["name"] for o in sar2["overdue"]]
            bk = next(b for b in sar2["booked"] if b["name"] == name)
            assert bk["review"]
        finally:
            post("review-booked", EMP, json={"name": name, "end": end, "booked": False})
        sar3 = next(p for p in self.get(ADMIN).json()["pages"] if p["dashboard_id"] == "plans-saraya")
        assert name in [o["name"] for o in sar3["overdue"]]
