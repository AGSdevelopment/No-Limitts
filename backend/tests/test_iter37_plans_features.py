"""Iter37: participant plans features - missing/incomplete form alerts, review booked tick, Monday plans email,
plan dates in Google Calendar. Unit tests use fake db / notify / email / calendar (never contact real users).
Live API tests are READ-ONLY on Wix data (never /agts-dashboard/save); booking is toggled back to un-booked."""
import asyncio
import json
import os
import sys
from datetime import date, datetime

import pytest
import requests

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from tests.test_iter36_plans_dashboard import BASE, FakeDB, ok_forms, serial  # noqa: E402

ADMIN, EMP = "test_session_admin", "test_session_employee"
H = lambda t: {"Authorization": f"Bearer {t}"}


def today():
    from core import DIGEST_TZ
    return serial(datetime.now(DIGEST_TZ).date())


# ---------------- Unit: form_status
class TestFormStatus:
    def st(self, forms, c=None, age=12):
        import routes.agts_dashboard as ag
        c = c or {"name": "Ann Lee"}
        idx = {}
        for f in forms:
            idx.setdefault(f["p"].lower(), []).append(f)
        return {k: v[0] for k, v in ag.form_status(c, idx, {"formAge": age}, today()).items()}

    def test_missing_both(self):
        assert self.st([]) == {"ra": "missing", "pep": "missing"}

    def test_incomplete_and_ok(self):
        T = today()
        r = self.st([{"p": "Ann Lee", "t": "ra", "st": "Incomplete", "u": T}, {"p": "Ann Lee", "t": "pep", "st": "Completed", "u": T}])
        assert r == {"ra": "incomplete", "pep": "ok"}

    def test_draft_status_incomplete_and_old(self):
        T = today()
        r = self.st([{"p": "Ann Lee", "t": "ra", "st": "Draft", "u": T}, {"p": "Ann Lee", "t": "pep", "st": "Completed", "u": T - 400}])
        assert r == {"ra": "incomplete", "pep": "old"}

    def test_latest_wins_and_pref_name(self):
        T = today()
        forms = [{"p": "Annie Lee", "t": "ra", "st": "Completed", "u": T - 5}, {"p": "Annie Lee", "t": "ra", "st": "Incomplete", "u": T - 300},
                 {"p": "Ann Lee", "t": "pep", "st": "Completed", "c": T - 2}]
        assert self.st(forms, {"name": "Ann Lee", "pref": "Annie"}) == {"ra": "ok", "pep": "ok"}


# ---------------- Unit: plan_alerts with missing/incomplete forms + booked reviews
@pytest.fixture
def ag(monkeypatch):
    import core
    import routes.agts_dashboard as ag
    sent = []

    async def fake_notify(ids, t, title, body, link=""):
        sent.append((tuple(ids), title, body, link))
    monkeypatch.setattr(core, "notify", fake_notify)
    ag._sent = sent
    return ag


def setup(ag, monkeypatch, clients, forms, pages=None, users=None, booked=None):
    nk = {"clients": clients, "forms": forms, "cfg": {}}

    async def fake_read(client, part):
        return {"data": json.dumps({"nikki": nk})} if part == "preview" else None
    monkeypatch.setattr(ag, "read_part", fake_read)
    fdb = FakeDB(pages if pages is not None else [
        {"dashboard_id": "participant-plans", "embed": "agts-nk", "users": ["u_nikki"]},
        {"dashboard_id": "plans-saraya", "embed": "agts-nk", "users": ["u_saraya"], "tag": "Saraya's Clients"}],
        users if users is not None else [{"user_id": "u_nikki", "name": "Nikki T", "email": "nikki@x.test"},
                                         {"user_id": "u_saraya", "name": "Saraya X", "email": "saraya@x.test"}])
    for k in booked or []:
        fdb.plan_reviews_booked.docs.append({"key": k, "booked_by_name": "Tester", "booked_at": "2026-01-01"})
    monkeypatch.setattr(ag, "db", fdb)
    return fdb


class TestFormAlerts:
    def test_missing_both_forms_once_per_page(self, ag, monkeypatch):
        T = today()
        cl = [{"name": "Max Both", "tags": "Saraya's Clients, Nikki's Clients", "end": T + 300}]
        setup(ag, monkeypatch, cl, [])
        asyncio.run(ag.plan_alerts())
        got = sorted((s[0][0], s[1]) for s in ag._sent)
        assert got == sorted([("u_nikki", "Risk assessment missing: Max Both"), ("u_nikki", "Personal emergency plan missing: Max Both"),
                              ("u_saraya", "Risk assessment missing: Max Both"), ("u_saraya", "Personal emergency plan missing: Max Both")])
        ag._sent.clear()
        asyncio.run(ag.plan_alerts())
        assert ag._sent == []  # deduped

    def test_incomplete_and_pep_old(self, ag, monkeypatch):
        T = today()
        cl = [{"name": "Ned Inc", "tags": "Nikki's Clients", "end": T + 300}]
        forms = [{"p": "Ned Inc", "t": "ra", "st": "In progress", "u": T - 3}, {"p": "Ned Inc", "t": "pep", "st": "Completed", "u": T - 500}]
        setup(ag, monkeypatch, cl, forms)
        asyncio.run(ag.plan_alerts())
        titles = sorted(s[1] for s in ag._sent)
        assert titles == ["Personal emergency plan out of date: Ned Inc", "Risk assessment not completed: Ned Inc"]
        body = next(s[2] for s in ag._sent if "not completed" in s[1])
        assert '"In progress"' in body

    def test_expired_and_archived_no_form_alerts(self, ag, monkeypatch):
        T = today()
        cl = [{"name": "Old Plan", "tags": "Nikki's Clients", "end": T - 1},
              {"name": "Arch Ive", "tags": "Nikki's Clients", "end": T + 300, "archived": True}]
        setup(ag, monkeypatch, cl, [])
        asyncio.run(ag.plan_alerts())
        assert ag._sent == []

    def test_booked_review_skips_overdue(self, ag, monkeypatch):
        T = today()
        cl = [{"name": "Rev Booked", "tags": "Nikki's Clients", "end": T + 60}, {"name": "Rev Open", "tags": "Nikki's Clients", "end": T + 60}]
        setup(ag, monkeypatch, cl, ok_forms(cl, T), booked=[f"rev booked|{T + 60}"])
        asyncio.run(ag.plan_alerts())
        assert [s[1] for s in ag._sent] == ["Plan review overdue: Rev Open"]


# ---------------- Unit: booked_map scoping
class TestBookedMap:
    def test_scoped_to_clients(self, ag, monkeypatch):
        setup(ag, monkeypatch, [], [], booked=["a b|100", "c d|200"])
        assert set(asyncio.run(ag.booked_map())) == {"a b|100", "c d|200"}
        assert set(asyncio.run(ag.booked_map([{"name": "A B", "end": 100}, {"name": "C D", "end": 999}]))) == {"a b|100"}
        assert asyncio.run(ag.booked_map([])) == {}


# ---------------- Unit: plans_email + send_plans_emails
def row(name, end, months=3, booked=False, forms=None):
    import routes.agts_dashboard as ag
    return {"name": name, "end": end, "rev": ag._addmonths(end, -months), "booked": booked,
            "forms": forms or {"ra": ("ok", None), "pep": ("ok", None)}}


class TestPlansEmail:
    T = serial(date(2026, 3, 10))

    def test_nothing_due_returns_none(self):
        import routes.agts_dashboard as ag
        assert ag.plans_email("Sam", [row("Far Away", self.T + 300), row("Gone", self.T - 3)], self.T) is None

    def test_sections(self):
        import routes.agts_dashboard as ag
        T = self.T
        rows = [row("Over Due", T + 60), row("Over Booked", T + 61, booked=True), row("Due Month", serial(date(2026, 6, 20))),
                row("Ends Month", serial(date(2026, 3, 25)), booked=True), row("Form Gap", T + 300, forms={"ra": ("missing", None), "pep": ("incomplete", {})}),
                row("Far Away", T + 300)]
        subj, html = ag.plans_email("Sam", rows, T)
        assert "Plan reviews overdue (1)" in html and "Over Due" in html and "Over Booked" not in html
        assert "Plan reviews due this month (1)" in html and "Due Month" in html
        assert "Plans ending this month (1)" in html and "Ends Month" in html
        assert "Forms to action (1)" in html and "Risk assessment missing, Personal emergency plan not completed" in html
        assert "Far Away" not in html and "Hi Sam" in html and "March 2026" in html
        assert subj.startswith("Your participant plans: 3 reviews")
        from email_service import _assert_safe_email
        _assert_safe_email(subj, html)  # passes the outgoing email safety checks

    def test_escapes_names(self):
        import routes.agts_dashboard as ag
        _, html = ag.plans_email("<Sam>", [row("<b>X</b>", self.T + 60)], self.T)
        assert "<b>X</b>" not in html.replace("<b>&lt;b&gt;X&lt;/b&gt;</b>", "") and "&lt;Sam&gt;" in html

    def test_send_plans_emails_fake(self, ag, monkeypatch):
        import email_service
        T = today()
        out = []

        async def fake_send(*, to, subject, html):
            out.append((to, subject))
            return True
        monkeypatch.setattr(email_service, "send_email", fake_send)
        cl = [{"name": "Sar Due", "tags": "Saraya's Clients", "end": T + 20}]
        setup(ag, monkeypatch, cl, ok_forms(cl, T),
              users=[{"user_id": "u_nikki", "name": "Nikki T", "email": "nikki@x.test"},
                     {"user_id": "u_saraya", "name": "Saraya X", "email": "saraya@x.test"}])
        r = asyncio.run(ag.send_plans_emails())
        assert r == {"sent": 1, "nothing_due": 1}
        assert [o[0] for o in out] == ["saraya@x.test"]
        out.clear()
        r = asyncio.run(ag.send_plans_emails(({"name": "Tess T", "email": "t@x.test"}, "plans-saraya")))
        assert r == {"sent": 1, "nothing_due": 0} and out[0][0] == "t@x.test"


# ---------------- Unit: sync_plan_calendar with fake Google calendar
class FakeCal:
    def __init__(self): self.events, self.n = {}, 0
    def insert(self, svc, body):
        self.n += 1
        self.events[f"g{self.n}"] = (svc, body)
        return {"id": f"g{self.n}"}
    def delete(self, svc, eid): self.events.pop(eid)


@pytest.fixture
def cal(ag, monkeypatch):
    import google_services as gs
    import routes.calendar as rc
    fc = FakeCal()
    connected = {"u_saraya", "u_admin"}

    async def fake_admin_calendar(uid): return f"svc:{uid}" if uid in connected else None
    monkeypatch.setattr(rc, "admin_calendar", fake_admin_calendar)
    monkeypatch.setattr(gs, "calendar_insert", fc.insert)
    monkeypatch.setattr(gs, "calendar_delete", fc.delete)
    return fc


class TestCalendarSync:
    def titles(self, fc, uid):
        return sorted((b["summary"], b["start"]["date"]) for s, b in fc.events.values() if s == f"svc:{uid}")

    def test_adds_skips_and_dedupes(self, ag, cal, monkeypatch):
        import routes.agts_dashboard as m
        T = today()
        cl = [{"name": "Cal One", "tags": "Saraya's Clients", "end": T + 200},     # end + review
              {"name": "Cal Near", "tags": "Saraya's Clients", "end": T + 30},     # review in past -> end only
              {"name": "Cal Far", "tags": "Saraya's Clients", "end": T + 500},     # end too far; review (T+~410) too far
              {"name": "Cal Past", "tags": "Saraya's Clients", "end": T - 2},
              {"name": "Cal Book", "tags": "Saraya's Clients", "end": T + 150}]    # booked -> end only
        fdb = setup(ag, monkeypatch, cl, [], booked=[f"cal book|{T + 150}"])
        r = asyncio.run(m.sync_plan_calendar())
        got = self.titles(cal, "u_saraya")
        names = [g[0] for g in got]
        assert names.count("Plan ends: Cal One") == 1 and "Plan review due: Cal One" in names
        assert "Plan ends: Cal Near" in names and "Plan review due: Cal Near" not in names
        assert not any("Cal Far" in n or "Cal Past" in n for n in names)
        assert "Plan ends: Cal Book" in names and "Plan review due: Cal Book" not in names
        assert r == {"added": 4, "removed": 0} and not self.titles(cal, "u_nikki")
        ev = next(b for s, b in cal.events.values() if b["summary"] == "Plan ends: Cal One")
        d = date.fromisoformat(ev["start"]["date"])
        assert serial(d) == T + 200 and (date.fromisoformat(ev["end"]["date"]) - d).days == 1
        # rerun: no duplicates
        assert asyncio.run(m.sync_plan_calendar()) == {"added": 0, "removed": 0} and len(cal.events) == 4
        # booking Cal One's review removes its event; un-booking adds it back
        fdb.plan_reviews_booked.docs.append({"key": f"cal one|{T + 200}"})
        assert asyncio.run(m.sync_plan_calendar()) == {"added": 0, "removed": 1}
        assert "Plan review due: Cal One" not in [g[0] for g in self.titles(cal, "u_saraya")]
        fdb.plan_reviews_booked.docs.clear()
        assert asyncio.run(m.sync_plan_calendar())["added"] == 2  # Cal One + Cal Book reviews

    def test_stale_removed_and_extra_user(self, ag, cal, monkeypatch):
        import routes.agts_dashboard as m
        T = today()
        cl = [{"name": "Stale P", "tags": "Saraya's Clients", "end": T + 200}]
        fdb = setup(ag, monkeypatch, cl, [])
        asyncio.run(m.sync_plan_calendar(("u_admin", "plans-saraya")))
        assert len(self.titles(cal, "u_admin")) == 2 and len(self.titles(cal, "u_saraya")) == 2
        assert fdb.plan_cal_users.docs[0]["pages"] == ["plans-saraya"]
        cl[0]["archived"] = True  # participant archived -> events removed everywhere
        r = asyncio.run(m.sync_plan_calendar())
        assert r == {"added": 0, "removed": 4} and cal.events == {} and fdb.plan_cal_events.docs == []


# ---------------- Live API (public URL): review booked, calendar sync, email endpoint guards
def post(path, token=None, page="plans-test", **kw):
    return requests.post(f"{BASE}/api/agts-dashboard/{path}", params={"page": page}, headers=H(token) if token else {}, timeout=60, **kw)


@pytest.fixture(scope="module")
def live_client():
    r = requests.get(f"{BASE}/api/agts-dashboard/data", params={"view": "nk", "page": "plans-test", "token": EMP}, timeout=60)
    assert r.status_code == 200
    nk = json.loads(r.json()["preview"]["data"])["nikki"]
    assert "booked" in nk
    T = today()
    cs = [c for c in nk["clients"] if isinstance(c.get("end"), (int, float)) and c["end"] > T]
    if not cs:
        pytest.skip("no live participant with a future plan end")
    return cs[-1]


class TestReviewBookedLive:
    def test_auth(self, live_client):
        body = {"name": live_client["name"], "end": int(live_client["end"]), "booked": False}
        assert post("review-booked", json=body).status_code == 401
        assert post("review-booked", ADMIN, json=body).status_code == 403
        assert post("review-booked", EMP, page="participant-plans", json=body).status_code == 403

    def test_not_on_page_404(self, live_client):
        assert post("review-booked", EMP, json={"name": "TEST_Nobody", "end": 46000, "booked": True}).status_code == 404
        assert post("review-booked", EMP, json={"name": live_client["name"], "end": int(live_client["end"]) + 1, "booked": True}).status_code == 404
        assert post("review-booked", ADMIN, page="participant-plans", json={"name": "TEST_Nobody", "end": 1, "booked": True}).status_code == 404

    def test_toggle_and_data(self, live_client):
        name, end = live_client["name"], int(live_client["end"])
        key = f"{name.strip().lower()}|{end}"
        try:
            r = post("review-booked", EMP, json={"name": name, "end": end, "booked": True})
            assert r.status_code == 200, r.text
            b = r.json()["booked"]
            assert key in b and set(b[key]) == {"by", "at"} and b[key]["at"]
            d = requests.get(f"{BASE}/api/agts-dashboard/data", params={"view": "nk", "page": "plans-test", "token": EMP}, timeout=60).json()
            nkb = json.loads(d["preview"]["data"])["nikki"]["booked"]
            assert key in nkb
            names = {c["name"].lower() for c in json.loads(d["preview"]["data"])["nikki"]["clients"]}
            assert all(k.split("|")[0] in names for k in nkb)  # only this page's participants
        finally:
            r = post("review-booked", EMP, json={"name": name, "end": end, "booked": False})
        assert r.status_code == 200 and key not in r.json()["booked"]


class TestCalendarLive:
    def test_status_employee_and_no_auth(self):
        r = requests.get(f"{BASE}/api/integrations/google-calendar/status", headers=H(EMP), timeout=30)
        assert r.status_code == 200 and {"configured", "connected"} <= set(r.json())
        assert requests.get(f"{BASE}/api/integrations/google-calendar/status", timeout=30).status_code == 401

    def test_sync_not_connected_409(self):
        r = post("calendar-sync", EMP)
        assert r.status_code == 409 and "Connect your Google Calendar first" in r.text
        assert post("calendar-sync").status_code == 401
        assert post("calendar-sync", ADMIN).status_code == 403

    def test_email_guards(self):
        # guards only - these never send. The real send is exercised manually once (sends to emp.test@example.com)
        assert post("plans-email/test").status_code == 401
        assert post("plans-email/test", ADMIN).status_code == 403
        assert post("plans-email/test", EMP, page="participant-plans").status_code == 403
