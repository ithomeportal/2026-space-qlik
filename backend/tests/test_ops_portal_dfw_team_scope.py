"""OPS Portal DFW TM1..TM4 — the DFW portal, scope-LOCKED to one sub-team.

Bruno PDF "BRUNO -- Ops Portal DFW" (2026-11-09): duplicate
/reports/ops-managers-portal-dfw into four reports, "OPS Portal DFW TM1".."TM4",
each with TEAMS = its TM. Locked server-side like the CORP T1-T4 portals and
XRay DFW TM1-4.

What fails SILENTLY here, and therefore what this file drives:

  * **The DFW scope pin.** The shims delegate to the DFW module's functions,
    which read the division from ``request.state``. A clone router without
    ``_pin_dfw_scope`` runs every query under the CORP default, where TM1 is
    not a sub-team: the team narrows to nothing and the page renders zeros.
  * **The team lock.** A crafted ``?team=TM2`` on the TM1 page must be
    dropped. Asserted by sending it through FastAPI and reading the bound
    parameters of every statement — not by inspecting a scope object (§100).
  * **A dropped param (§40).** Every shim must forward every parameter its DFW
    target declares, with the same default. Asserted with a spy per endpoint.

The statements are captured by a stub pool; nothing touches a database.
"""

from __future__ import annotations

import asyncio
import importlib
import inspect
import json
import pathlib
import types

import pytest
from dfw_marker_sql import strip_dfw_marker_rule
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.routers import deps as deps_mod
from app.routers import ops_portal_overview_dfw as dfw
from app.routers import ops_portal_overview_dfw_team as mod
from app.routers.ops_portal_overview import meta as _meta
from app.routers.ops_portal_overview._scope import DFW_SCOPE, case_variants
from app.services import ai_chat_tools
from app.services.seed import CUSTOM_REPORTS

FRONTEND = pathlib.Path(__file__).resolve().parents[2] / "frontend"
TMS = ("TM1", "TM2", "TM3", "TM4")
ALL_DFW_SUB_TEAMS = DFW_SCOPE.sub_teams  # TM1..TM5

# Budget panels: DFW has none (0 of its YTD customers in the budget table).
BUDGET_SLUGS = {"team-variance", "team-variance-weekly", "team-variance-by-team"}

# Deliberately NOT on a clone, with the measurement (§103) — both are
# cross-team breakdowns that would show TM1 the other four teams' numbers:
#   * /team-projection-by-team — the DFW function takes NO `team` parameter;
#   * /team-performance-by-team — takes `team` but IGNORES it ("this panel
#     always returns all teams"): the end-to-end probe below caught it binding
#     no TM at all while the DFW shim's comment claimed it was locked;
#   * their only callers, the Monthly Projection / Performance "Team" buttons,
#     are hidden whenever `lockedTeam` is set (asserted below).
NOT_ON_A_CLONE = {"team-projection-by-team", "team-performance-by-team"}

# Division-blind by design (same list and reasons as the CEO portal's guard).
UNSCOPED_BY_DESIGN = {"data-freshness", "workdays", "fuel"}


def _slug(path: str) -> str:
    return path.rsplit("/", 1)[-1]


def _routes(router) -> dict[str, object]:
    return {_slug(r.path): r.endpoint for r in router.routes}


def _gate_key(fn) -> str:
    dep = inspect.signature(fn).parameters["_user"].default.dependency
    cells = [c.cell_contents for c in (dep.__closure__ or ())]
    keys = next(c for c in cells if isinstance(c, tuple))
    assert len(keys) == 1, keys
    return keys[0]


def _router(tm: str):
    hits = [r for r in mod.team_routers if r.prefix.endswith(f"-{tm.lower()}")]
    assert len(hits) == 1, f"{tm}: {len(hits)} routers"
    return hits[0]


# ---------------------------------------------------------------------------
# Shape: four routers, the DFW pin, the DFW route set, own gates
# ---------------------------------------------------------------------------


def test_there_are_exactly_four_clones_tm1_to_tm4() -> None:
    assert tuple(mod.TEAM_CONFIGS) == TMS
    assert [r.prefix for r in mod.team_routers] == [
        f"/custom/ops-portal-overview-dfw-tm{n}" for n in range(1, 5)
    ]


@pytest.mark.parametrize("tm", TMS)
def test_every_clone_router_carries_the_dfw_scope_pin(tm: str) -> None:
    deps = [d.dependency for d in _router(tm).dependencies]
    assert dfw._pin_dfw_scope in deps, f"{tm} router would run under the CORP default scope"


@pytest.mark.parametrize("tm", TMS)
def test_the_route_set_is_the_dfw_portals_minus_the_cross_team_breakdown(tm: str) -> None:
    mine = set(_routes(_router(tm)))
    theirs = set(_routes(dfw.r))
    assert mine == theirs - NOT_ON_A_CLONE, (
        f"missing {sorted(theirs - NOT_ON_A_CLONE - mine)}, extra {sorted(mine - theirs)}"
    )
    assert not mine & BUDGET_SLUGS


def test_the_excluded_routes_really_cannot_be_locked_and_are_never_called() -> None:
    """The measurement behind NOT_ON_A_CLONE."""
    assert "team" not in inspect.signature(dfw.team_projection_by_team).parameters
    perf_src = inspect.getsource(importlib.import_module(
        "app.routers.ops_portal_overview.performance").team_performance_by_team)
    assert "team filter intentionally dropped" in perf_src
    src = (FRONTEND / "app/reports/ops-portal-overview/PanelShared.tsx").read_text()
    shim = src.split("export function WeekTeamButtons")[1].split("\n}\n")[0]
    assert "{!lockedTeam && (" in shim and "onClick={onTeam}" in shim
    perf = (FRONTEND / "app/reports/ops-portal-overview/MonthlyPerformancePanel.tsx").read_text()
    assert "{!lockedTeam && (" in perf and "setMonthlyOpen(true)" in perf.split("{!lockedTeam && (")[1]


@pytest.mark.parametrize("tm", TMS)
def test_every_route_is_behind_its_own_report_gate(tm: str) -> None:
    key = f"ops-portal-dfw-{tm.lower()}"
    for slug, fn in _routes(_router(tm)).items():
        assert _gate_key(fn) == key, f"{tm} /{slug}"


@pytest.mark.parametrize("tm", TMS)
def test_no_shim_accepts_a_team_from_the_client(tm: str) -> None:
    for slug, fn in _routes(_router(tm)).items():
        params = inspect.signature(fn).parameters
        assert "team" not in params and "teams" not in params, f"{tm} /{slug}"


def test_the_dfw_module_itself_is_untouched_by_the_clones() -> None:
    assert dfw.REPORT_KEY == "ops-managers-portal-dfw"
    assert dfw.r.prefix == "/custom/ops-portal-overview-dfw"


def test_main_registers_all_four() -> None:
    from app.main import app

    paths = {getattr(r, "path", "") for r in app.routes}
    for n in range(1, 5):
        assert f"/api/custom/ops-portal-overview-dfw-tm{n}/actuals" in paths
        assert f"/api/custom/ops-portal-overview-dfw-tm{n}/team-projection-by-team" not in paths


# ---------------------------------------------------------------------------
# §40 — every param forwarded, same defaults, team pinned (spy per endpoint)
# ---------------------------------------------------------------------------


def _delegated(tm: str):
    """(slug, clone fn, dfw fn) for every delegating route (all but /filters)."""
    theirs = _routes(dfw.r)
    return [
        (slug, fn, theirs[slug])
        for slug, fn in _routes(_router(tm)).items()
        if slug != "filters"
    ]


def _cases():
    return [(tm, slug) for tm in TMS for slug, _, _ in _delegated(tm)]


@pytest.mark.parametrize("tm,slug", _cases())
def test_each_shim_declares_every_dfw_param_with_the_same_default(tm: str, slug: str) -> None:
    clone_fn, dfw_fn = next((c, d) for s, c, d in _delegated(tm) if s == slug)
    mine = inspect.signature(clone_fn).parameters
    theirs = inspect.signature(dfw_fn).parameters
    assert set(mine) == set(theirs) - {"team"}, f"{slug}: {set(mine) ^ (set(theirs) - {'team'})}"
    for name, p in theirs.items():
        if name in ("team", "request", "_user"):
            continue
        a, b = mine[name].default, p.default
        assert getattr(a, "default", a) == getattr(b, "default", b), f"{slug}.{name} default"
        assert repr(getattr(a, "metadata", None)) == repr(getattr(b, "metadata", None)), (
            f"{slug}.{name} constraints"
        )


@pytest.mark.parametrize("tm,slug", _cases())
def test_each_shim_forwards_every_param_and_pins_its_team(monkeypatch, tm: str, slug: str) -> None:
    clone_fn, dfw_fn = next((c, d) for s, c, d in _delegated(tm) if s == slug)
    seen: list[dict] = []

    async def spy(**kw):
        seen.append(kw)
        return {"success": True}

    monkeypatch.setattr(dfw, dfw_fn.__name__, spy)
    request = types.SimpleNamespace(state=types.SimpleNamespace())
    sentinels = {}
    for i, name in enumerate(inspect.signature(clone_fn).parameters):
        sentinels[name] = request if name == "request" else f"sentinel-{i}"
    asyncio.run(clone_fn(**sentinels))
    (kw,) = seen
    want = set(inspect.signature(dfw_fn).parameters)
    assert set(kw) == want, f"{slug} forwards {sorted(set(kw))}, DFW takes {sorted(want)}"
    for name, value in sentinels.items():
        assert kw[name] is value, f"{slug} rewrites {name}"
    if "team" in want:
        assert kw["team"] == tm, f"{slug} does not pin {tm}"


# ---------------------------------------------------------------------------
# End to end: a crafted ?team= through FastAPI, every endpoint, bound params read
# ---------------------------------------------------------------------------


class _StubPool:
    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple]] = []

    async def fetch(self, sql, *params):
        self.calls.append((sql, params))
        return []

    async def fetchrow(self, sql, *params):
        self.calls.append((sql, params))

    async def fetchval(self, sql, *params):
        self.calls.append((sql, params))


_POOL_GETTERS = ("get_datalake_gold_pool", "get_pool", "get_pricing_pool")


def _patch_pools(monkeypatch, pool) -> None:
    pkg = importlib.import_module("app.routers.ops_portal_overview")
    names = [
        f"app.routers.ops_portal_overview.{p.stem}"
        for p in pathlib.Path(pkg.__file__).parent.glob("*.py")
    ]
    for name in [*names, dfw.__name__, mod.__name__]:
        m = importlib.import_module(name)
        for getter in _POOL_GETTERS:
            if hasattr(m, getter):
                monkeypatch.setattr(m, getter, lambda request, _p=pool: _p)


def _client(monkeypatch, tm: str) -> tuple[TestClient, _StubPool]:
    pool = _StubPool()
    _patch_pools(monkeypatch, pool)
    _meta._freshness_cache["at"] = None
    app = FastAPI()
    app.include_router(_router(tm), prefix="/api")
    app.dependency_overrides[deps_mod.require_user] = lambda: {"sub": "t", "roles": ["admin"]}
    return TestClient(app, raise_server_exceptions=False), pool


def _other(tm: str) -> str:
    return TMS[(TMS.index(tm) + 1) % len(TMS)]


def _params_blob(pool: _StubPool) -> list[str]:
    out: list[str] = []
    for _sql, params in pool.calls:
        for p in params:
            if isinstance(p, (list, tuple)):
                out.extend(str(x).strip().upper() for x in p)
            else:
                out.append(str(p).strip().upper())
    return out


def _sql_blob(pool: _StubPool) -> str:
    # The DFW rule names TM1..TM5 on purpose; the TM4 relabel of a DFW-marked
    # CORP row is part of the same rule (§134).
    return "\n".join(
        strip_dfw_marker_rule(sql).replace("THEN 'TM4' ELSE", "THEN <dfw-relabel> ELSE")
        for sql, _ in pool.calls
    )


def _e2e_cases():
    return [(tm, slug) for tm in TMS for slug in _routes(_router(tm))]


@pytest.mark.parametrize("tm,slug", _e2e_cases())
def test_a_crafted_team_is_ignored_and_only_its_own_tm_is_bound(monkeypatch, tm: str, slug: str) -> None:
    client, pool = _client(monkeypatch, tm)
    other = _other(tm)
    path = f"/api/custom/ops-portal-overview-dfw-{tm.lower()}/{slug}"
    client.get(path, params={"team": other, "teams": f"{other},TM5"})
    if not pool.calls:
        assert slug in UNSCOPED_BY_DESIGN, f"{slug} emitted no SQL — the probe would be vacuous"
        return
    bound = _params_blob(pool)
    sql = _sql_blob(pool)
    for foreign in set(ALL_DFW_SUB_TEAMS) - {tm}:
        assert foreign not in bound, f"{tm} /{slug} binds {foreign}"
        assert f"'{foreign}'" not in sql, f"{tm} /{slug} inlines {foreign}"
    if slug in UNSCOPED_BY_DESIGN:
        assert "TEAM-DFW" not in bound and "TEAM-DFW" not in sql
        return
    blob = json.dumps(bound) + sql
    assert "TEAM-DFW" in blob, f"{tm} /{slug} is not scoped to the DFW division"
    assert tm in bound, f"{tm} /{slug} is not narrowed to {tm}"


# ---------------------------------------------------------------------------
# /filters — only its own team, the scope's own predicates
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("tm", TMS)
def test_filters_return_only_its_team_with_the_scope_predicates(monkeypatch, tm: str) -> None:
    client, pool = _client(monkeypatch, tm)
    res = client.get(f"/api/custom/ops-portal-overview-dfw-{tm.lower()}/filters",
                     params={"team": _other(tm)})
    assert res.status_code == 200, res.text
    data = res.json()["data"]
    assert data["teams"] == [tm]
    assert data["locked_team"] == tm
    assert data["has_budget"] is False
    assert data["division"] == "DFW"
    assert len(pool.calls) == 3  # customers, lanes, carriers
    for sql, params in pool.calls:
        flat = [list(p) if isinstance(p, (list, tuple)) else p for p in params]
        # The division rule: TEAM-DFW OR a DFW-marked CORP row (§134).
        assert any(isinstance(p, list) and "TEAM-DFW" in p for p in flat)
        assert "<dfw-marked-corp-row>" in strip_dfw_marker_rule(sql)
        # The sub-team narrowing is the panels' own expression (TM4 relabel
        # included), bound with case variants — never a bare team_id = ANY.
        assert case_variants([tm]) in flat
        assert "THEN 'TM4' ELSE br4.team END" in sql


# ---------------------------------------------------------------------------
# 4-place mirror: seed ↔ page ↔ backend gate ↔ REPORT_MAP (+ AI assistant)
# ---------------------------------------------------------------------------


def _seed(key: str) -> dict:
    hits = [r for r in CUSTOM_REPORTS if r["key"] == key]
    assert len(hits) == 1, f"{key}: {len(hits)} seed entries"
    return hits[0]


@pytest.mark.parametrize("n", range(1, 5))
def test_the_four_place_mirror(n: int) -> None:
    key = f"ops-portal-dfw-tm{n}"
    title = f"OPS Portal DFW TM{n}"
    entry = _seed(key)
    assert entry["title"] == title
    assert entry["roles"] == [f"DFW KAM{n}", "Executive"]
    assert entry["category"] == _seed("ops-managers-portal-dfw")["category"]

    page = (FRONTEND / f"app/reports/{key}/page.tsx").read_text()
    assert f'reportKey="{key}"' in page
    assert f'tm="TM{n}"' in page

    assert _gate_key(_routes(_router(f"TM{n}"))["actuals"]) == key

    icons = (FRONTEND / "components/ReportIcons.tsx").read_text()
    assert f'"{title}":' in icons

    assert ai_chat_tools.REPORT_ROUTE_PREFIX[key] == f"ops-portal-overview-dfw-tm{n}"


def test_the_shared_page_body_is_the_dfw_portal_locked_to_one_team() -> None:
    body = (FRONTEND / "components/OpsPortalDfwTeamContent.tsx").read_text()
    dfw_page = (FRONTEND / "app/reports/ops-managers-portal-dfw/page.tsx").read_text()
    # Every DFW-only prop the division page sets, the clones set too.
    for prop in ("hideBonusNav", "hideGoTo", "hideBudget",
                 'customerVarianceBasis="mom"', 'actualsCompare="prior_month"'):
        assert prop in dfw_page and prop in body, prop
    assert "custom/ops-portal-overview-dfw-${" in body
    assert "lockedTeam={tm}" in body
    assert "OPS Portal DFW ${tm}" in body
