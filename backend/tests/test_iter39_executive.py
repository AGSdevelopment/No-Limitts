"""Iter39: Executive user type gates Therapist dashboard, Participant plans & safety and Team plans overview.
NEVER calls /agts-dashboard/save or upload (live Wix CMS). Never toggles real users. Never presses real Email buttons."""
import asyncio
import os
import sys

import pytest
import requests
from dotenv import load_dotenv

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from tests.test_iter36_plans_dashboard import BASE  # noqa: E402

load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"))

EXEC, ADMIN2, EMP = "test_session_admin", "test_session_admin2", "test_session_employee"
H = lambda t: {"Authorization": f"Bearer {t}"}


def g(path, tok=None, **params):
    return requests.get(f"{BASE}/api/{path}", headers=H(tok) if tok else {}, params=params, timeout=90)


# ---------------- auth/me exposes the executive flag
class _Me:
    @pytest.mark.parametrize("tok,exp", [(EXEC, True), (ADMIN2, False), (EMP, False)])
    def test_me_executive(self, tok, exp):
        r = g("auth/me", tok)
        assert r.status_code == 200
        assert bool(r.json().get("executive")) is exp


# ---------------- Home dashboards list / dashboard detail
class _Dash:
    def ids(self, tok):
        r = g("dashboards", tok)
        assert r.status_code == 200
        return {d["dashboard_id"] for d in r.json()}

    def test_exec_list(self):
        ids = self.ids(EXEC)
        assert {"therapist-dashboard", "participant-plans"} <= ids
        assert "plans-saraya" not in ids  # not cluttering Home

    def test_non_exec_admin_list(self):
        ids = self.ids(ADMIN2)
        assert not ({"therapist-dashboard", "participant-plans"} & ids)

    def test_employee_list(self):
        ids = self.ids(EMP)
        assert "plans-test" in ids
        assert not ({"therapist-dashboard", "participant-plans", "plans-saraya"} & ids)

    @pytest.mark.parametrize("tok", [ADMIN2, EMP])
    @pytest.mark.parametrize("did", ["therapist-dashboard", "participant-plans"])
    def test_non_exec_detail_404(self, tok, did):
        assert g(f"dashboards/{did}", tok).status_code == 404

    @pytest.mark.parametrize("did", ["therapist-dashboard", "participant-plans", "plans-saraya"])
    def test_exec_detail_200(self, did):
        r = g(f"dashboards/{did}", EXEC)
        assert r.status_code == 200 and r.json()["dashboard_id"] == did

    def test_admin2_plans_saraya_404(self):
        assert g("dashboards/plans-saraya", ADMIN2).status_code == 404

    def test_emp_plans_test_200(self):
        assert g("dashboards/plans-test", EMP).status_code == 200


# ---------------- agts-dashboard data/engine/app + team overview
class _Agts:
    VIEWS = [{}, {"view": "nk", "page": "participant-plans"}]

    @pytest.mark.parametrize("tok", [ADMIN2, EMP])
    @pytest.mark.parametrize("part", ["data", "engine", "app"])
    @pytest.mark.parametrize("vi", [0, 1])
    def test_agts_non_exec_403(self, tok, part, vi):
        assert g(f"agts-dashboard/{part}", tok, **self.VIEWS[vi]).status_code == 403
        # query-token variant too (engine/app are opened in iframes with ?token=)
        assert g(f"agts-dashboard/{part}", None, token=tok, **self.VIEWS[vi]).status_code == 403

    @pytest.mark.parametrize("part", ["data", "engine", "app"])
    @pytest.mark.parametrize("vi", [0, 1])
    def test_agts_exec_200(self, part, vi):
        assert g(f"agts-dashboard/{part}", EXEC, **self.VIEWS[vi]).status_code == 200

    def test_exec_plans_saraya_direct(self):
        assert g("agts-dashboard/data", EXEC, view="nk", page="plans-saraya").status_code == 200

    def test_admin2_plans_saraya_403(self):
        assert g("agts-dashboard/data", ADMIN2, view="nk", page="plans-saraya").status_code == 403

    def test_agts_emp_plans_test_200(self):
        assert g("agts-dashboard/data", EMP, view="nk", page="plans-test").status_code == 200
        assert g("agts-dashboard/app", EMP, view="nk", page="plans-test").status_code == 200

    def test_emp_plans_saraya_403(self):
        assert g("agts-dashboard/data", EMP, view="nk", page="plans-saraya").status_code == 403

    @pytest.mark.parametrize("tok", [ADMIN2, EMP])
    def test_team_overview_non_exec(self, tok):
        assert g("agts-dashboard/team-overview", tok).status_code == 403
        assert g("agts-dashboard/team-overview/pdf", None, token=tok).status_code == 403
        r = requests.post(f"{BASE}/api/agts-dashboard/team-overview/email-me", headers=H(tok), timeout=30)
        assert r.status_code == 403

    def test_team_overview_exec(self):
        r = g("agts-dashboard/team-overview", EXEC)
        assert r.status_code == 200 and "pages" in r.json() and "totals" in r.json()
        p = g("agts-dashboard/team-overview/pdf", None, token=EXEC)
        assert p.status_code == 200 and p.content[:4] == b"%PDF"

    def test_unauth(self):
        assert g("agts-dashboard/team-overview").status_code in (401, 403)
        assert g("agts-dashboard/data").status_code == 401


# ---------------- PATCH /users/{id}/executive
class _Toggle:
    def xpatch(self, tok, uid, val):
        return requests.patch(f"{BASE}/api/users/{uid}/executive", headers=H(tok), json={"executive": val}, timeout=30)

    @pytest.mark.parametrize("tok", [ADMIN2, EMP])
    def test_toggle_non_exec_403(self, tok):
        assert self.xpatch(tok, "user_testadmin02", True).status_code == 403

    def test_self_remove_400(self):
        assert self.xpatch(EXEC, "user_testadmin01", False).status_code == 400

    def test_unknown_404(self):
        assert self.xpatch(EXEC, "user_doesnotexist_x", True).status_code == 404

    def test_validation_422(self):
        r = requests.patch(f"{BASE}/api/users/user_testadmin02/executive", headers=H(EXEC), json={}, timeout=30)
        assert r.status_code == 422

    def test_toggle_admin2_on_then_off(self):
        try:
            r = self.xpatch(EXEC, "user_testadmin02", True)
            assert r.status_code == 200 and r.json()["executive"] is True and "_id" not in r.json()
            assert g("auth/me", ADMIN2).json().get("executive") is True
            assert g("agts-dashboard/team-overview", ADMIN2).status_code == 200
            assert "therapist-dashboard" in {d["dashboard_id"] for d in g("dashboards", ADMIN2).json()}
        finally:
            r = self.xpatch(EXEC, "user_testadmin02", False)
        assert r.status_code == 200 and r.json()["executive"] is False
        assert g("agts-dashboard/team-overview", ADMIN2).status_code == 403


# ---------------- Unit: monthly report + dashboard alerts go to Executives (hidden excluded); fake email only
class _Cur:
    def __init__(self, docs): self.docs = docs
    async def to_list(self, n): return list(self.docs)


class _Users:
    def __init__(self, docs): self.docs, self.queries = docs, []

    def find(self, q, proj=None):
        self.queries.append(q)
        out = []
        for d in self.docs:
            ok = True
            for k, v in q.items():
                if isinstance(v, dict) and "$ne" in v:
                    ok &= d.get(k) != v["$ne"]
                else:
                    ok &= d.get(k) == v
            if ok:
                out.append(d)
        return _Cur(out)


class _DB:
    def __init__(self, users): self.users = _Users(users)


USERS = [
    {"user_id": "u1", "name": "Exec One", "email": "exec1@fake.invalid", "role": "admin", "executive": True},
    {"user_id": "u2", "name": "Admin Two", "email": "admin2@fake.invalid", "role": "admin"},
    {"user_id": "u3", "name": "Hidden Exec", "email": "hid@fake.invalid", "role": "admin", "executive": True, "hidden": True},
    {"user_id": "u4", "name": "Emp Exec", "email": "emp@fake.invalid", "role": "employee", "executive": True},
    {"user_id": "u5", "name": "Ex Example", "email": "x@example.com", "role": "admin", "executive": True},
]


class _Recip:
    def test_send_team_report_recipients(self, monkeypatch):
        import email_service
        import routes.agts_dashboard as m
        fdb = _DB(USERS)
        sent = []

        async def fake_send(to, subject, html, **kw):
            sent.append(to)
            return True

        async def fake_overview():
            return {"today": "1 Jan 2026", "totals": {}, "pages": []}

        monkeypatch.setattr(m, "db", fdb)
        monkeypatch.setattr(email_service, "send_email", fake_send)
        monkeypatch.setattr(m, "overview_data", fake_overview)
        r = asyncio.run(m.send_team_report())
        assert sorted(sent) == ["emp@fake.invalid", "exec1@fake.invalid"]
        assert r["sent"] == 2
        assert fdb.users.queries[0] == {"executive": True, "hidden": {"$ne": True}}

    def test_admin_ids_are_executives(self, monkeypatch):
        import routes.agts_dashboard as m
        monkeypatch.setattr(m, "db", _DB(USERS))
        assert sorted(asyncio.run(m._admin_ids())) == ["u1", "u4", "u5"]


# One test class so pytest-xdist loadscope keeps everything on one worker (the toggle test flips admin2 briefly)
class TestExecutive(_Me, _Dash, _Agts, _Toggle, _Recip):
    pass
