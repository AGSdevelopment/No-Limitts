"""Iter36: AGTS therapist plans pages (view=nk) access control, wording, data scoping + alert logic unit tests.
READ-ONLY against live Wix data: never calls /agts-dashboard/save."""
import asyncio
import json
import os
import sys
from datetime import date, datetime

import pytest
import requests

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _base():
    url = os.environ.get("EXPO_BACKEND_URL") or os.environ.get("EXPO_PUBLIC_BACKEND_URL")
    if not url:
        for line in open("/app/frontend/.env"):
            if line.startswith("EXPO_PUBLIC_BACKEND_URL=") or line.startswith("EXPO_BACKEND_URL="):
                url = line.split("=", 1)[1].strip().strip('"')
    return url.rstrip("/")


BASE = _base()
ADMIN, EMP = "test_session_admin", "test_session_employee"


def get(path, **params):
    return requests.get(f"{BASE}/api/agts-dashboard/{path}", params=params, timeout=60)


# ---- Access control: engine / app / data for view=nk
class TestAccess:
    @pytest.mark.parametrize("ep", ["engine", "app", "data"])
    def test_no_token_401(self, ep):
        assert get(ep, view="nk", page="plans-test").status_code == 401

    @pytest.mark.parametrize("ep", ["engine", "app", "data"])
    def test_employee_allowed_plans_test(self, ep):
        r = get(ep, view="nk", page="plans-test", token=EMP)
        assert r.status_code == 200, r.text[:200]

    @pytest.mark.parametrize("ep", ["engine", "app", "data"])
    def test_admin_403_on_plans_test(self, ep):
        r = get(ep, view="nk", page="plans-test", token=ADMIN)
        assert r.status_code == 403

    @pytest.mark.parametrize("ep", ["engine", "app"])
    def test_employee_403_participant_plans(self, ep):
        assert get(ep, view="nk", page="participant-plans", token=EMP).status_code == 403

    def test_employee_403_unknown_page(self):
        assert get("engine", view="nk", page="plans-nope", token=EMP).status_code == 403

    def test_non_nk_page_doc_cannot_be_used(self):
        # therapist-dashboard has embed 'agts' (not agts-nk) -> must not be usable as a nk page
        assert get("engine", view="nk", page="therapist-dashboard", token=ADMIN).status_code == 403

    def test_bearer_header_works(self):
        r = requests.get(f"{BASE}/api/agts-dashboard/engine", params={"view": "nk", "page": "plans-test"},
                         headers={"Authorization": f"Bearer {EMP}"}, timeout=60)
        assert r.status_code == 200

    def test_admin_full_engine(self):
        r = get("engine", token=ADMIN)
        assert r.status_code == 200
        assert 'id="v-nk"' not in r.text and 'data-v="nk"' not in r.text
        assert "Nikki" in r.text  # full engine untouched

    def test_employee_full_engine_403(self):
        assert get("engine", token=EMP).status_code == 403
        assert get("data", token=EMP).status_code == 403


# ---- Therapist page wording / injections
class TestEngineHtml:
    @pytest.fixture(scope="class")
    def html(self):
        r = get("engine", view="nk", page="plans-test", token=EMP)
        assert r.status_code == 200
        return r.text

    def test_no_nikki_participants(self, html):
        assert "Nikki's participants" not in html
        assert "Nikki\\'s participants" not in html

    def test_my_participants_wording(self, html):
        assert "emergency plans for my participants" in html
        assert "My participants" in html
        assert "All of my participants" in html

    def test_tab_and_view_injected(self, html):
        assert 'data-v="nk"' in html and 'id="v-nk"' in html
        assert "Plan expiry calendar" in html and "function nkCal" in html

    def test_no_store_headers(self):
        r = get("engine", view="nk", page="plans-test", token=EMP)
        assert "no-store" in (r.headers.get("cache-control") or "")
        assert r.headers.get("referrer-policy") == "no-referrer"

    def test_app_wrapper_passes_page(self):
        r = get("app", view="nk", page="plans-test", token=EMP)
        assert "view=nk&page=plans-test" in r.text
        assert '"?view=nk&page=plans-test"' in r.text


# ---- Data endpoint: nk scoping, no billing leakage
class TestData:
    @pytest.fixture(scope="class")
    def data(self):
        r = get("data", view="nk", page="plans-test", token=EMP)
        assert r.status_code == 200
        return r.json()

    def test_no_billing_or_settings(self, data):
        for p in ["billing", "participants", "settings"]:
            assert data[p] is None
        assert data["user"] == "emp.test@example.com"

    def test_preview_has_only_nikki_and_tag(self, data):
        prev = json.loads(data["preview"]["data"])
        assert prev["weeks"] == {}
        assert set(prev.keys()) == {"weeks", "nikki"}
        assert prev["nikki"].get("cfg", {}).get("tag") == "Saraya's Clients"

    def test_client_scope_report(self, data):
        # Informational: does the server filter clients to the page tag, or send everyone (client-side filter)?
        clients = json.loads(data["preview"]["data"])["nikki"].get("clients") or []
        other = [c for c in clients if "saraya's clients" not in (c.get("tags") or "").lower()]
        print(f"clients sent={len(clients)} not-tagged-for-page={len(other)}")
        assert not other, f"{len(other)} participants of other therapists are sent to this therapist's page"


# ---- Alert logic unit tests (fake db + fake notify; no real notifications)
class FakeCursor:
    def __init__(self, docs): self.docs = docs
    async def to_list(self, n): return list(self.docs)


class FakeColl:
    def __init__(self, docs=None): self.docs = docs or []
    def _match(self, d, q):
        for k, v in q.items():
            if isinstance(v, dict) and "$ne" in v:
                if d.get(k) == v["$ne"]: return False
            elif isinstance(v, dict) and "$in" in v:
                if d.get(k) not in v["$in"]: return False
            elif d.get(k) != v: return False
        return True
    def find(self, q=None, proj=None): return FakeCursor([d for d in self.docs if self._match(d, q or {})])
    async def find_one(self, q, proj=None): return next((d for d in self.docs if self._match(d, q)), None)
    async def insert_one(self, d): self.docs.append(d)
    async def update_one(self, q, upd, upsert=False):
        d = await self.find_one(q)
        if not d:
            d = dict(q); self.docs.append(d)
        d.update(upd.get("$set", {}))
        for k, v in upd.get("$addToSet", {}).items():
            d.setdefault(k, [])
            for x in (v["$each"] if isinstance(v, dict) else [v]):
                if x not in d[k]: d[k].append(x)
    async def delete_one(self, q):
        d = await self.find_one(q)
        if d: self.docs.remove(d)
    async def delete_many(self, q):
        self.docs = [d for d in self.docs if not self._match(d, q)]


class FakeDB:
    def __init__(self, dashboards, users):
        self.dashboards, self.users, self.meta = FakeColl(dashboards), FakeColl(users), FakeColl()
        # iter37 collections: review booked ticks, calendar sync bookkeeping, calendar connections
        self.plan_reviews_booked, self.plan_cal_users, self.plan_cal_events, self.integrations = FakeColl(), FakeColl(), FakeColl(), FakeColl()


def serial(d): return (d - date(1899, 12, 30)).days


@pytest.fixture
def ag(monkeypatch):
    import core
    import routes.agts_dashboard as ag
    sent = []
    async def fake_notify(ids, t, title, body, link=""): sent.append((tuple(ids), title, body, link))
    monkeypatch.setattr(core, "notify", fake_notify)
    ag._sent = sent
    return ag


def ok_forms(clients, today):
    """Recent completed RA + PEP for each client so form alerts don't interfere with end/review tests."""
    return [{"p": c["name"], "t": t, "st": "Completed", "u": today - 10} for c in clients for t in ("ra", "pep")]


def run_plan_alerts(ag, monkeypatch, clients, forms=None, cfg=None, pages=None, users=None):
    nk = {"clients": clients, "forms": forms if forms is not None else [], "cfg": cfg or {}}
    async def fake_read(client, part): return {"data": json.dumps({"nikki": nk})} if part == "preview" else None
    monkeypatch.setattr(ag, "read_part", fake_read)
    fdb = FakeDB(pages if pages is not None else [
        {"dashboard_id": "participant-plans", "embed": "agts-nk", "users": ["u_nikki"]},
        {"dashboard_id": "plans-saraya", "embed": "agts-nk", "users": ["u_saraya"], "tag": "Saraya's Clients"}],
        users if users is not None else [{"user_id": "u_nikki", "name": "Nikki T"}, {"user_id": "u_saraya", "name": "Saraya X"}])
    monkeypatch.setattr(ag, "db", fdb)
    asyncio.run(ag.plan_alerts())
    return fdb


class TestPlanAlerts:
    def today(self):
        from core import DIGEST_TZ
        return serial(datetime.now(DIGEST_TZ).date())

    def test_plan_end_and_review_routing(self, ag, monkeypatch):
        T = self.today()
        clients = [
            {"name": "Ann End", "tags": "Saraya's Clients", "end": T + 10},       # ending soon -> saraya
            {"name": "Ben Rev", "tags": "Nikki's Clients", "end": T + 60},        # review overdue (3 months) -> nikki
            {"name": "Cat Later", "tags": "Nikki's Clients", "end": T + 200},     # nothing
            {"name": "Dan Past", "tags": "Saraya's Clients", "end": T - 5},       # expired -> nothing
            {"name": "Eve Arch", "tags": "Saraya's Clients", "end": T + 3, "archived": True},
            {"name": "Fay Today", "tags": "Saraya's Clients", "end": T},          # 0 days
        ]
        fdb = run_plan_alerts(ag, monkeypatch, clients, ok_forms(clients, T))
        titles = {(s[0], s[1]) for s in ag._sent}
        assert (("u_saraya",), "Plan ending soon: Ann End") in titles
        assert (("u_nikki",), "Plan review overdue: Ben Rev") in titles
        assert (("u_saraya",), "Plan ending soon: Fay Today") in titles
        assert len(ag._sent) == 3, ag._sent
        body = next(s[2] for s in ag._sent if "Fay" in s[1])
        assert "(0 days)" in body
        assert next(s[3] for s in ag._sent if "Ann" in s[1]) == "/dashboard/plans-saraya"
        # second run: deduped
        ag._sent.clear()
        async def again():
            await ag.plan_alerts()
        asyncio.run(again())
        assert ag._sent == []
        assert len(fdb.meta.docs) == 3

    def test_singular_day(self, ag, monkeypatch):
        T = self.today()
        cl = [{"name": "One Day", "tags": "Nikki's Clients", "end": T + 1}]
        run_plan_alerts(ag, monkeypatch, cl, ok_forms(cl, T))
        assert "(1 day)" in ag._sent[0][2]

    def test_risk_assessment_out_of_date(self, ag, monkeypatch):
        T = self.today()
        clients = [{"name": "Gus Old", "tags": "Nikki's Clients", "end": T + 300}]
        forms = [{"p": "Gus Old", "t": "ra", "st": "Completed", "u": T - 400},
                 {"p": "Gus Old", "t": "ra", "st": "Incomplete", "u": T - 500},
                 {"p": "Gus Old", "t": "pep", "st": "Completed", "u": T - 20}]
        run_plan_alerts(ag, monkeypatch, clients, forms)
        assert [s[1] for s in ag._sent] == ["Risk assessment out of date: Gus Old"]

    def test_recent_ra_no_alert(self, ag, monkeypatch):
        T = self.today()
        run_plan_alerts(ag, monkeypatch, [{"name": "Hal New", "tags": "Nikki's Clients", "end": T + 300}],
                        [{"p": "Hal New", "t": "ra", "st": "Completed", "u": T - 30},
                         {"p": "Hal New", "t": "pep", "st": "Completed", "u": T - 30}])
        assert ag._sent == []

    def test_sync_creates_page_for_unique_name(self, ag, monkeypatch):
        T = self.today()
        fdb = run_plan_alerts(ag, monkeypatch, [{"name": "Ivy", "tags": "Zara's Clients", "end": T + 300}],
                              pages=[], users=[{"user_id": "u_zara", "name": "Zara Q"}, {"user_id": "u_x", "name": "Xa"}])
        pg = next(d for d in fdb.dashboards.docs if d["dashboard_id"] == "plans-zara")
        assert pg["users"] == ["u_zara"] and pg["tag"] == "Zara's Clients" and pg["embed"] == "agts-nk"

    def test_sync_skips_ambiguous_name(self, ag, monkeypatch):
        T = self.today()
        fdb = run_plan_alerts(ag, monkeypatch, [{"name": "Ivy", "tags": "Zara's Clients", "end": T + 300}],
                              pages=[], users=[{"user_id": "a", "name": "Zara Q"}, {"user_id": "b", "name": "Zara W"}])
        assert not fdb.dashboards.docs


class TestHoursAlerts:
    def test_below_target_flagged(self):
        import routes.agts_dashboard as ag
        E = serial(date(2026, 1, 1))  # Thursday
        assert (date(1899, 12, 30).toordinal() + E) and ag._serial_to_date(E).weekday() == 3
        rows = []
        for wk in range(13):
            sd = E - wk * 7
            rows.append([sd, 0, 0, 0, 0, 0, 1000])  # Low: 1000/100 = 10h/wk
            rows.append([sd, 0, 0, 1, 0, 0, 2500])  # High: 25h/wk
        billing = json.dumps({"rows": rows, "fulls": ["Low Person", "High Person"], "codes": ["01_011_DS"]})
        settings = json.dumps({"therapists": {"Low": {"target": 20, "rate": 100, "full": "Low Person"},
                                              "High": {"target": 25, "rate": 100}}})
        end, low = ag.hours_alerts(billing, settings)
        assert end == E
        assert low == [("Low", "Low Person", 10.0, 20)]

    def test_new_starter_skipped_and_empty(self):
        import routes.agts_dashboard as ag
        E = serial(date(2026, 1, 1))
        rows = [[E - w * 7, 0, 0, 0, 0, 0, 100] for w in range(3)]
        billing = json.dumps({"rows": rows, "fulls": ["New Guy"], "codes": ["x_DS"]})
        assert ag.hours_alerts(billing, json.dumps({"therapists": {"New": {"target": 20, "rate": 100}}}))[1] == []
        assert ag.hours_alerts(json.dumps({"rows": [], "fulls": [], "codes": []}), "") == (None, [])

    def test_travel_counts_double(self):
        import routes.agts_dashboard as ag
        E = serial(date(2026, 1, 1))
        rows = []
        for wk in range(13):
            rows.append([E - wk * 7, 0, 0, 0, 0, 0, 900])   # DS 9h
            rows.append([E - wk * 7, 0, 0, 0, 1, 0, 500])   # PT travel at half rate -> 10h
        billing = json.dumps({"rows": rows, "fulls": ["Tess T"], "codes": ["01_011_DS", "01_011_PT"]})
        st = json.dumps({"therapists": {"Tess": {"target": 25, "rate": 100}}})
        assert ag.hours_alerts(billing, st)[1] == [("Tess", "Tess", 19.0, 25)]
