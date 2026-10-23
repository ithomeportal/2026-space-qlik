"""The CEO reads every report — and nothing more (owner decision 2026-10-23).

Company policy: the CEO (TagRole ``CEO``) has unlimited READ access to all reports.
Until now only ``admin`` bypassed ``role_report_access``, so 24 of 67 active reports
(e.g. corp-t1..t4-ops-kam-portal, granted only to ``CORP KAM#``) were closed to him.

The rule is ONE helper, ``deps.can_read_all_reports``, used at every report-access
decision point: ``require_report_access``, ``user_has_report_access``,
``/reports/access/{key}`` (ReportGuard), the Home list + count + trending + search +
favorites + ``/reports/{id}``, the AI chat's accessible-report catalog (which the
daily brief gates teams on) and the CEO Cockpit's re-gated tiles.

What it must NOT do: grant ``require_admin`` (every admin/settings/write endpoint) —
read-all is not admin. And it must not widen anyone else: a user with neither role
is still denied exactly as before.

Offline: fake pools and direct calls; nothing touches a database.
"""

from __future__ import annotations

import asyncio
import inspect
from uuid import uuid4

import pytest
from fastapi import HTTPException

from app.routers import ceo_cockpit, deps
from app.routers import reports as reports_mod
from app.routers import search as search_mod
from app.routers.deps import (
    READ_ALL_REPORT_ROLES,
    can_read_all_reports,
    require_admin,
    require_report_access,
    user_has_report_access,
)
from app.services import ai_chat_tools

CEO = {"sub": str(uuid4()), "email": "emendoza@unilinktransportation.com", "roles": ["CEO"]}
KAM = {"sub": str(uuid4()), "email": "kam@unilinktransportation.com", "roles": ["CORP KAM1"]}
OTHER = {"sub": str(uuid4()), "email": "ops@unilinktransportation.com", "roles": ["Operations"]}
ADMIN = {"sub": str(uuid4()), "email": "it@unilinktransportation.com", "roles": ["admin"]}

# The live grant of corp-t1-ops-kam-portal excludes CEO (only `CORP KAM#`).
KAM_ONLY = frozenset({"corp kam1"})


# ── the helper ───────────────────────────────────────────────────────────────


@pytest.mark.parametrize("roles", [["CEO"], ["ceo"], ["Ceo", "Executive"], ["admin"], ["ADMIN"]])
def test_read_all_roles_are_admin_and_ceo_case_insensitive(roles):
    assert can_read_all_reports(roles) is True


@pytest.mark.parametrize("roles", [[], None, ["Executive"], ["CORP KAM1"], ["super_admin"],
                                   ["CEO Assistant"], ["c e o"]])
def test_everyone_else_does_not_read_all(roles):
    assert can_read_all_reports(roles) is False


def test_read_all_set_is_exactly_admin_and_ceo():
    """Widening this set is a policy change — make it a visible test diff."""
    assert READ_ALL_REPORT_ROLES == frozenset({"admin", "ceo"})


# ── backend gates ────────────────────────────────────────────────────────────


class _Req:
    def __init__(self):
        self.app = type("app", (), {"state": type("state", (), {"pool": object()})()})()


@pytest.fixture
def kam_only_grant(monkeypatch):
    async def allowed(_pool, _key):
        return KAM_ONLY

    monkeypatch.setattr(deps, "get_allowed_roles_for_report", allowed)


def _check(user, *keys):
    gate = require_report_access(*keys)
    return asyncio.run(gate(_Req(), user))


def test_ceo_passes_require_report_access_on_a_report_that_excludes_ceo(kam_only_grant):
    assert _check(CEO, "corp-t1-ops-kam-portal") is CEO


def test_a_genuine_holder_still_passes(kam_only_grant):
    assert _check(KAM, "corp-t1-ops-kam-portal") is KAM


@pytest.mark.parametrize("user", [OTHER, {"sub": "x", "roles": []}, {"sub": "x"}])
def test_a_non_ceo_non_admin_user_is_still_403(kam_only_grant, user):
    with pytest.raises(HTTPException) as exc:
        _check(user, "corp-t1-ops-kam-portal")
    assert exc.value.status_code == 403


def test_user_has_report_access_is_true_for_ceo(kam_only_grant):
    assert asyncio.run(user_has_report_access(_Req(), CEO, "ops-customer-score")) is True
    assert asyncio.run(user_has_report_access(_Req(), OTHER, "ops-customer-score")) is False


@pytest.mark.parametrize("roles", [["CEO"], ["ceo"], ["CEO", "Executive"]])
def test_ceo_is_still_403_on_require_admin(roles):
    """Read-all is not admin: /admin/*, seeding, user/role/report CRUD stay admin-only."""
    with pytest.raises(HTTPException) as exc:
        asyncio.run(require_admin({"sub": "x", "roles": roles}))
    assert exc.value.status_code == 403


def test_admin_still_passes_require_admin():
    assert asyncio.run(require_admin(ADMIN)) is ADMIN


def test_require_admin_does_not_use_the_read_all_helper():
    assert "can_read_all_reports" not in inspect.getsource(require_admin)


def test_tag_role_gate_is_not_widened():
    """`require_tag_role` (deprecated, for non-report gates) keeps admin-only bypass."""
    gate = deps.require_tag_role("HR")
    with pytest.raises(HTTPException):
        asyncio.run(gate(CEO))


# ── /reports/access/{key} — what ReportGuard renders ─────────────────────────


class _AccessPool:
    async def fetch(self, _sql, *_args):
        return [{"name": "CORP KAM1"}]


def _access(user, monkeypatch):
    monkeypatch.setattr(reports_mod, "get_pool", lambda _r: _AccessPool())
    return asyncio.run(reports_mod.report_access("corp-t1-ops-kam-portal", _Req(), user))["data"]


def test_report_guard_allows_ceo_on_a_report_that_excludes_ceo(monkeypatch):
    data = _access(CEO, monkeypatch)
    assert data["allowed"] is True
    assert data["roles"] == ["CORP KAM1"]


def test_report_guard_still_denies_everyone_else(monkeypatch):
    assert _access(OTHER, monkeypatch)["allowed"] is False
    assert _access(KAM, monkeypatch)["allowed"] is True


# ── the Home list and its siblings ───────────────────────────────────────────


class _SqlPool:
    def __init__(self):
        self.sql: list[str] = []
        self.params: list[tuple] = []

    async def fetch(self, sql, *params):
        self.sql.append(sql)
        self.params.append(params)
        return []

    async def fetchval(self, sql, *params):
        self.sql.append(sql)
        self.params.append(params)
        return 0

    async def fetchrow(self, sql, *params):
        self.sql.append(sql)
        self.params.append(params)
        return None


def _drive(name, user, monkeypatch):
    pool = _SqlPool()
    module = search_mod if name == "search_reports" else reports_mod
    monkeypatch.setattr(module, "get_pool", lambda _r: pool)
    fn = getattr(module, name)
    calls = {
        "list_reports": lambda: fn(_Req(), user, None, False, 1, 500),
        "trending_reports": lambda: fn(_Req(), user, False, 6),
        "get_report": lambda: fn(uuid4(), _Req(), user),
        "list_user_favorites": lambda: fn(_Req(), user, False),
        "search_reports": lambda: fn(_Req(), "spot", None, user, 20),
    }
    asyncio.run(calls[name]())
    return pool


def _catalog_sql(pool):
    """The report statements only (search also queries `apps`, which are open to all)."""
    out = [sql for sql in pool.sql if "FROM reports r" in sql]
    assert out, "no catalog statement was issued — this guard is blind"
    return out


_LISTINGS = ("list_reports", "trending_reports", "get_report", "list_user_favorites",
             "search_reports")


@pytest.mark.parametrize("name", _LISTINGS)
def test_ceo_listing_has_no_role_join(name, monkeypatch):
    """Home shows the CEO every active report — no TagRole join on any statement."""
    pool = _drive(name, CEO, monkeypatch)
    for sql in _catalog_sql(pool):
        assert "JOIN user_roles" not in sql, sql
        assert "r.is_active = TRUE" in sql


@pytest.mark.parametrize("name", _LISTINGS)
def test_everyone_else_keeps_the_role_join(name, monkeypatch):
    pool = _drive(name, OTHER, monkeypatch)
    for sql in _catalog_sql(pool):
        assert "JOIN user_roles ur ON ur.role_id = rra.role_id AND ur.user_id = $1" in sql, sql


@pytest.mark.parametrize("name", _LISTINGS)
def test_the_bypass_binds_the_same_arguments(name, monkeypatch):
    """`$1` stays referenced either way, so no statement changes its arity
    (an unreferenced parameter is a Postgres prepare error)."""
    ceo = _drive(name, CEO, monkeypatch)
    other = _drive(name, OTHER, monkeypatch)
    assert [len(p) for p in ceo.params] == [len(p) for p in other.params]
    for sql in _catalog_sql(ceo):
        assert "$1" in sql


# ── the AI chat catalog (and with it the daily brief) ────────────────────────


class _CatalogPool:
    async def fetch(self, _sql, *_args):
        return [
            {"custom_path": "/reports/corp-t1-ops-kam-portal", "title": "CORP T1 - Ops KAM Portal",
             "description": "", "roles": ["corp kam1"]},
            {"custom_path": "/reports/hd-spot", "title": "HD Spot", "description": "",
             "roles": ["pricing"]},
        ]


def _accessible(identity):
    session = ai_chat_tools.ToolSession(app=None, identity=identity, pool=_CatalogPool(), client=None)
    return asyncio.run(session._accessible_reports())


def test_ai_chat_catalog_gives_ceo_every_report():
    assert set(_accessible(CEO)) == {"corp-t1-ops-kam-portal", "hd-spot"}


def test_ai_chat_catalog_still_filters_everyone_else():
    assert set(_accessible(OTHER)) == set()
    assert set(_accessible(KAM)) == {"corp-t1-ops-kam-portal"}


# ── no decision point left on a bare `"admin" in roles` ──────────────────────


@pytest.mark.parametrize("module", [deps, reports_mod, ai_chat_tools, ceo_cockpit])
def test_report_access_sites_use_the_helper(module):
    src = inspect.getsource(module)
    assert "can_read_all_reports" in src
    if module is deps:
        # Only require_admin and the deprecated require_tag_role keep an admin-only test.
        src = src.replace(inspect.getsource(deps.require_admin), "")
        src = src.replace(inspect.getsource(deps.require_tag_role), "")
    assert '"admin" in roles' not in src and '"admin" not in roles' not in src
