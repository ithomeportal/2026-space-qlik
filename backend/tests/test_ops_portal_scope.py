"""Ops Portal division scope — CORP unchanged, DFW never leaks CORP.

Bruno PDF "space -- Ops Portal DFW" (2026-08-20), Request 3.

Two properties, and they fail in opposite directions:

  * **CORP must not have moved.** Five live portals (the main one and the four
    CORP-T clones) share every helper this refactor touched. A drift there is
    silent — the numbers change but nothing errors — so the CORP half is
    asserted structurally: the base predicate is still the five CORP team ids,
    the team column is still `team_id`, and no DFW literal can appear.

  * **DFW must not leak CORP.** The scope is stamped on `request.state`, not
    passed per call, so a single endpoint that forgets to read it would quietly
    serve CORP data on a DFW page. The only way to catch that is to drive
    EVERY endpoint and read the statement it emits — which is what
    `test_no_dfw_endpoint_emits_a_corp_team` does.

⚠ These read SQL text on purpose. With today's data a scope mistake returns
plausible rows (DFW is a real division with real orders), so no data-driven
assertion distinguishes "scoped correctly" from "scoped to the wrong column".
"""

from __future__ import annotations

import asyncio
import inspect
import json
import types

import pytest

from app.routers import ops_portal_overview as opo
from app.routers import ops_portal_overview_dfw as dfw
from app.routers.ops_portal_overview import _constants, _sql
from app.routers.ops_portal_overview._scope import (
    CORP_SCOPE,
    DFW_SCOPE,
    case_variants,
    scope_of,
)

CORP_IDS = ("TEAM1", "TEAM2", "TEAM3", "TEAM4", "TEAM5")


class _StubPool:
    """Captures every statement instead of running any of them."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple]] = []

    async def fetch(self, sql, *params):
        self.calls.append((sql, params))
        return []

    async def fetchrow(self, sql, *params):
        self.calls.append((sql, params))
        return None

    async def fetchval(self, sql, *params):
        self.calls.append((sql, params))
        return None


_ENDPOINT_MODULES = (
    "meta", "chart", "variance", "performance",
    "projection", "actuals", "orders", "hold", "incidents",
)


def _patch_pools(pool):
    """Point every module's pool factory at the stub; return an undo callable."""
    import importlib

    originals = []
    for name in _ENDPOINT_MODULES:
        m = importlib.import_module(f"app.routers.ops_portal_overview.{name}")
        if hasattr(m, "get_datalake_gold_pool"):
            originals.append((m, m.get_datalake_gold_pool))
            m.get_datalake_gold_pool = lambda request, _p=pool: _p
    m = dfw
    originals.append((m, m.get_datalake_gold_pool))
    m.get_datalake_gold_pool = lambda request, _p=pool: pool
    return lambda: [setattr(mod, "get_datalake_gold_pool", fn) for mod, fn in originals]


def _drive(fn, scope=None, **overrides) -> _StubPool:
    """Call an endpoint function with FastAPI's declared defaults resolved.

    Mirrors what FastAPI does over HTTP: a `Query(...)` default object is
    replaced by its `.default`. Calling these as plain Python without that is
    exactly the §40 bug the package documents.
    """
    pool = _StubPool()
    undo = _patch_pools(pool)
    state = types.SimpleNamespace()
    if scope is not None:
        state.opp_scope = scope
    request = types.SimpleNamespace(
        app=types.SimpleNamespace(state=types.SimpleNamespace()),
        state=state,
    )
    kwargs = {}
    for name, p in inspect.signature(fn).parameters.items():
        if name == "request":
            kwargs[name] = request
        elif name in ("_user", "user"):
            kwargs[name] = {}
        else:
            d = p.default
            v = getattr(d, "default", d)
            kwargs[name] = None if v is Ellipsis else v
    kwargs.update(overrides)
    try:
        try:
            asyncio.run(fn(**kwargs))
        except Exception:
            # The stub returns None/[]; several endpoints subscript that after
            # emitting their SQL. The statement is what we came for.
            pass
    finally:
        undo()
    return pool


def _blob(pool: _StubPool) -> str:
    out = []
    for sql, params in pool.calls:
        out.append(sql)
        out.append(json.dumps([list(p) if isinstance(p, (list, tuple)) else str(p)
                               for p in params]))
    return "\n".join(out)


# ---------------------------------------------------------------------------
# The scope objects themselves
# ---------------------------------------------------------------------------


def test_corp_is_the_default_scope_everywhere() -> None:
    """A request with no stamp is CORP — the five live portals depend on it."""
    bare = types.SimpleNamespace(state=types.SimpleNamespace())
    assert scope_of(bare) is CORP_SCOPE
    assert scope_of(types.SimpleNamespace()) is CORP_SCOPE
    # ...and the helper signatures default to it too.
    for fn in (_sql._v4_scope_where, _sql._scorecard_cte, _sql._bill_metrics_sql,
               _sql._team_id_select):
        assert inspect.signature(fn).parameters["scope"].default is CORP_SCOPE


def test_the_two_scopes_name_different_team_columns() -> None:
    """The whole point of Request 3 — same metrics, different team column."""
    assert CORP_SCOPE.base_teams == CORP_IDS
    assert CORP_SCOPE.v4_team_col == "team_id"
    assert DFW_SCOPE.base_teams == ("TEAM-DFW",)
    assert DFW_SCOPE.v4_team_col == "team"
    assert DFW_SCOPE.sc_team_col == "team_dfw"
    assert DFW_SCOPE.sub_teams == ("TM1", "TM2", "TM3", "TM4", "TM5")


def test_dfw_declares_no_budget() -> None:
    """0 of DFW's 15 YTD customers are in daily_production_budget_report."""
    assert CORP_SCOPE.has_budget is True
    assert DFW_SCOPE.has_budget is False


def test_sub_team_params_match_how_each_column_is_stored() -> None:
    """Padding vs case is a CORRECTNESS choice, not an optimisation.

    `team_id` is varchar(8) and McLeod stores it both padded and unpadded, so a
    bare 'TEAM1' misses the scorecard rows. `team` is varchar(512) and stored
    unpadded but NOT case-clean ('tm4' on 2 rows). Get either wrong and the
    predicate matches nothing — which looks exactly like "no work this month".
    """
    corp = _sql._sub_team_param(CORP_SCOPE, ["TEAM2"])
    assert "TEAM2" in corp and "TEAM2   " in corp

    dfw_param = _sql._sub_team_param(DFW_SCOPE, ["TM4"])
    assert "TM4" in dfw_param and "tm4" in dfw_param
    assert not any(p != p.strip() for p in dfw_param), "team is not padded"

    assert case_variants(["TM1", "TM1"]) == ["TM1", "tm1"], "must de-duplicate"


def test_corp_team_select_carries_no_redundant_alias() -> None:
    """Keeps the CORP SQL byte-identical so the equivalence proof has teeth."""
    assert _sql._team_id_select("br4", CORP_SCOPE) == "br4.team_id"
    assert _sql._team_id_select("br4", DFW_SCOPE) == "br4.team AS team_id"


def test_the_customer_team_map_ranks_the_scopes_own_column() -> None:
    """Ranking `team_id` under DFW would map every customer to one bucket."""
    corp = _constants.customer_team_cte(CORP_SCOPE)
    assert "TRIM(team_id)       AS team_id" in corp
    assert "'TEAM1'" in corp
    # The back-compat constant must not drift from the CORP rendering.
    assert _constants.CUSTOMER_TEAM_CTE == corp

    dfw_cte = _constants.customer_team_cte(DFW_SCOPE)
    assert "TRIM(team)       AS team_id" in dfw_cte, "output name must stay team_id"
    assert "'TEAM-DFW'" in dfw_cte
    assert "'TEAM1'" not in dfw_cte


# ---------------------------------------------------------------------------
# The property that matters: drive EVERY endpoint
# ---------------------------------------------------------------------------


def _dfw_endpoints():
    """(path, handler) for every route the DFW router exposes."""
    return [(route.path, route.endpoint) for route in dfw.r.routes]


@pytest.mark.parametrize("path,fn", _dfw_endpoints(), ids=lambda v: v if isinstance(v, str) else "")
def test_no_dfw_endpoint_emits_a_corp_team(path: str, fn) -> None:
    """Every statement a DFW page can cause must be DFW-scoped.

    Drives the DFW router's own handlers, which is what the browser hits — so
    this covers the router-level `_pin_dfw_scope` dependency AND the delegation
    into the shared package, not just the helpers in isolation.
    """
    pool = _drive(fn, scope=DFW_SCOPE)
    if not pool.calls:
        pytest.skip(f"{path} emits no SQL")
    blob = _blob(pool)
    for corp_id in CORP_IDS:
        assert corp_id not in blob, f"{path} leaks {corp_id}"


# Endpoints that are legitimately division-blind, with the reason. Anything
# NOT on this list must scope itself — a new endpoint is opted IN by default.
_UNSCOPED_BY_DESIGN = {
    # Staleness is a property of the ETL feed, not of a team: every portal
    # reports the same answer and shares the same 60s cache. Scoping it would
    # make one portal claim fresh data while another called the same feed
    # stale.
    "/custom/ops-portal-overview-dfw/data-freshness",
}


@pytest.mark.parametrize("path,fn", _dfw_endpoints(), ids=lambda v: v if isinstance(v, str) else "")
def test_every_dfw_endpoint_actually_scopes_to_the_division(path: str, fn) -> None:
    """Absence of CORP is not presence of DFW — an unscoped query has neither.

    The CORP-leak test alone would pass for an endpoint that scopes to nothing
    at all, so this asserts the positive. Exemptions are named above with a
    reason rather than skipped, so adding an endpoint cannot quietly opt out.
    """
    pool = _drive(fn, scope=DFW_SCOPE)
    if not pool.calls:
        pytest.skip(f"{path} emits no SQL")
    if path in _UNSCOPED_BY_DESIGN:
        assert "TEAM-DFW" not in _blob(pool), (
            f"{path} is listed as division-blind but now scopes itself — "
            "remove it from _UNSCOPED_BY_DESIGN"
        )
        return
    assert "TEAM-DFW" in _blob(pool), f"{path} is not scoped to the division"


# Endpoints whose OUTPUT carries a per-team breakdown. Under DFW these must
# read the sub-team column; reading `team_id` there is not an error and does
# not leak CORP — it silently collapses TM1..TM5 into a single row labelled
# "TEAM-DFW", which is precisely the failure Request 3 exists to prevent.
_BY_TEAM_ENDPOINTS = (
    "/custom/ops-portal-overview-dfw/team-performance-by-team",
    "/custom/ops-portal-overview-dfw/team-performance",
    "/custom/ops-portal-overview-dfw/team-weekly-performance",
)


@pytest.mark.parametrize("path", _BY_TEAM_ENDPOINTS)
def test_by_team_output_reads_the_sub_team_column_under_dfw(path: str) -> None:
    """TM1..TM5 must survive as five rows, not collapse into one.

    ⚠ Neither leak test catches this: `br4.team_id` under DFW still contains
    'TEAM-DFW' and still excludes every CORP id, so both pass while the panel
    shows one row. The only signal is which COLUMN the statement reads.
    """
    fn = {r.path: r.endpoint for r in dfw.r.routes}[path]
    blob = _blob(_drive(fn, scope=DFW_SCOPE))
    assert "br4.team AS team_id" in blob or "TRIM(br4.team)" in blob, (
        f"{path} must project the sub-team column, not the constant team_id"
    )
    # And it must not ALSO be grouping/aliasing on the division constant.
    assert "TRIM(br4.team_id) AS team_id" not in blob
    assert "br4.team_id AS team_id" not in blob


def test_the_corp_router_is_untouched_by_the_dfw_router() -> None:
    """A DFW request must not change what the CORP portal then emits.

    The scope lives on `request.state`; module state would make this fail.
    """
    corp_before = _blob(_drive(opo.by_order))
    _drive(dfw.r.routes[0].endpoint, scope=DFW_SCOPE)
    corp_after = _blob(_drive(opo.by_order))
    assert corp_before == corp_after
    assert "TEAM1" in corp_before and "TEAM-DFW" not in corp_before


# ---------------------------------------------------------------------------
# Wiring
# ---------------------------------------------------------------------------


def test_the_dfw_router_pins_the_scope_as_a_router_dependency() -> None:
    """Not per-handler: one missed handler would silently serve CORP."""
    names = [d.dependency.__name__ for d in dfw.r.dependencies]
    assert "_pin_dfw_scope" in names


def test_scope_is_not_reachable_from_the_query_string() -> None:
    """A client-settable scope would let a DFW user widen onto CORP."""
    for route in dfw.r.routes:
        params = inspect.signature(route.endpoint).parameters
        assert "scope" not in params, f"{route.path} exposes scope"


def test_an_unknown_team_widens_to_the_division_rather_than_to_nothing() -> None:
    """§75 — a filter that matches nothing deletes rows silently."""
    assert dfw._sub_team("TM3") == "TM3"
    assert dfw._sub_team("tm3") == "TM3"
    assert dfw._sub_team("TEAM1") is None
    assert dfw._sub_team(None) is None
    # A FastAPI Query default object reaching a direct Python call (§40).
    assert dfw._sub_team(object()) is None


def test_the_budget_only_endpoints_are_not_exposed_on_dfw() -> None:
    """Requests 5-6 delete every budget panel; the endpoints go with them.

    ⚠ `/team-projection-by-team` used to be on this list and did not belong on
    it — corrected 2026-09-03 while building the CEO Executive Portal, which
    registers all 29 paths for both divisions.

    It is not a budget endpoint. It breaks the ROLLING 14-DAY PROJECTION out
    per sub-team and never touches `daily_production_budget_report`; only its
    name sits near the three that do. Because it was classified as budget it
    was never shimmed, and `SidePanels` renders the Monthly Projection "Team"
    button unconditionally — so on DFW that button opened a modal onto a 404
    while every other panel on the page rendered normally.

    The lesson this line now pins: a name is not a classification. The three
    below are asserted absent because a query PROVES they read the budget
    table; the fourth is asserted PRESENT because the same query proves it
    does not.
    """
    paths = {route.path for route in dfw.r.routes}
    for gone in ("/team-variance", "/team-variance-weekly", "/team-variance-by-team"):
        assert f"/custom/ops-portal-overview-dfw{gone}" not in paths
    assert "/custom/ops-portal-overview-dfw/team-projection-by-team" in paths


def test_the_not_billed_panel_is_delegated_everywhere() -> None:
    """SidePanels renders it unconditionally on all six portals.

    It was missing from the CORP team factory until 2026-08-21 — a live 404 on
    four pages while the main portal looked healthy.
    """
    from app.routers import ops_portal_overview_team as team_mod

    src = inspect.getsource(team_mod)
    assert '@r.get("/customer-not-billed")' in src
    assert "opo.customer_not_billed(" in src
    call = src.split("opo.customer_not_billed(")[1].split(")")[0]
    assert "team=team" in call
    assert any(r.path.endswith("/customer-not-billed") for r in dfw.r.routes)


def test_customer_variance_is_month_over_month_and_says_so() -> None:
    """Request 7 REPLACES actual−budget with last month − this month.

    Same endpoint name and wire fields as the CORP panel, different metric —
    so the response names its own basis rather than leaving the UI to guess
    (§69).
    """
    pool = _drive(dfw.customer_variance, scope=DFW_SCOPE)
    sql = pool.calls[0][0]
    assert "daily_production_budget_report" not in sql, "must not read budget"
    assert "Loads Budget" not in sql and "Profit Budget" not in sql
    assert "vol_last" in sql and "vol_this" in sql
    assert "profit_last" in sql and "profit_this" in sql
    assert "br4.margin_amt" in sql and "origin_actual_departure" in sql
    # §73 — both months in ONE scan; a second pass over a live table disagrees.
    assert len(pool.calls) == 1, "both months must come from a single statement"
    assert sql.count("FILTER (") >= 6


def test_customer_variance_ignores_the_pages_date_range() -> None:
    """"Last month vs this month" is a calendar statement, not a window."""
    params = inspect.signature(dfw.customer_variance).parameters
    for p in ("range", "start_date", "end_date"):
        assert p not in params, f"month-over-month must not accept {p}"
