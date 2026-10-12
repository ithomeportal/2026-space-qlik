"""OPs Direct Compare — Bruno PDF "BRUNO -- DIRECT COMPARE UPDATES" (2026-10-12).

R1 data labels and R3 the top scrollbar are frontend-only. R2 — a "Team" filter
inside the "Month by Month" chart that "must apply exclusively to this chart" —
is the one with a server contract, and what these tests stop is:

* a missing / junk ``?teams=`` narrowing the chart to NOTHING instead of ALL;
* two spellings of one team set (``TEAM3,TEAM1`` vs ``TEAM1,TEAM3``) caching
  twice — or worse, two DIFFERENT sets sharing one cache entry;
* a direct call (tests, shims) receiving FastAPI's ``Query(None)`` FieldInfo as
  a truthy filter value;
* a per-team clone (corp-tN-direct-compare) being widened by a crafted
  ``?teams=TEAM2`` — the clones must not declare the param at all;
* the frontend hook and the backend disagreeing on the param name, or the
  hook's cache key not covering it (§ queryKey must cover qs()).
"""

from __future__ import annotations

import asyncio
import inspect
import re
import types
from pathlib import Path

import pytest

from app.datalake import pad_variants
from app.routers import ops_direct_compare as odc
from app.routers import ops_direct_compare_team as odct

_REQ = types.SimpleNamespace(app=types.SimpleNamespace(state=types.SimpleNamespace()))
_FRONTEND = Path(__file__).resolve().parents[2] / "frontend"


class _StubPool:
    def __init__(self):
        self.params: list[tuple] = []

    async def fetch(self, sql, *params):
        self.params.append(params)
        return []


def _run_trend(pool, **kwargs):
    orig = odc.get_datalake_gold_pool
    odc.get_datalake_gold_pool = lambda request: pool
    try:
        return asyncio.run(odc.trend_yoy(request=_REQ, _user={}, **kwargs))
    finally:
        odc.get_datalake_gold_pool = orig


@pytest.fixture(autouse=True)
def _clean_cache():
    odc._trend_cache.clear()
    odc._trend_locks.clear()
    yield
    odc._trend_cache.clear()
    odc._trend_locks.clear()


def _queried_teams(params: tuple) -> set[str]:
    """The team padded-variant list bound into the WHERE, back to bare ids."""
    lists = [p for p in params if isinstance(p, list)]
    found = set()
    for team in odc.ALL_TEAMS:
        variants = set(pad_variants((team,), width=8))
        if any(set(p) & variants for p in lists):
            found.add(team)
    return found


# --------------------------------------------------------------------------
# _trend_teams — the canonical team list
# --------------------------------------------------------------------------


@pytest.mark.parametrize("raw", [None, "", " , ", "TEAM9", "team1", "DROP TABLE"])
def test_missing_or_junk_teams_mean_all_teams_never_none(raw):
    assert odc._trend_teams(raw) == list(odc.ALL_TEAMS)


def test_team_order_is_canonical():
    assert odc._trend_teams("TEAM3,TEAM1") == odc._trend_teams("TEAM1,TEAM3") == ["TEAM1", "TEAM3"]


def test_unknown_names_drop_valid_ones_survive():
    assert odc._trend_teams("TEAM9, TEAM-DFW ,,") == ["TEAM-DFW"]


# --------------------------------------------------------------------------
# /trend-yoy — the filter reaches the SQL, and the cache keys on it
# --------------------------------------------------------------------------


def test_direct_call_without_teams_is_all_teams():
    """Guards the Annotated declaration: a `= Query(None)` default would hand a
    direct caller a FieldInfo, not None."""
    pool = _StubPool()
    resp = _run_trend(pool)
    assert _queried_teams(pool.params[0]) == set(odc.ALL_TEAMS)
    assert resp["data"]["teams"] == list(odc.ALL_TEAMS)


def test_teams_filter_scopes_the_sql_and_echoes_the_applied_set():
    pool = _StubPool()
    resp = _run_trend(pool, teams="TEAM2,TEAM-DFW")
    assert _queried_teams(pool.params[0]) == {"TEAM2", "TEAM-DFW"}
    assert resp["data"]["teams"] == ["TEAM2", "TEAM-DFW"]


def test_same_set_any_order_shares_one_cache_entry():
    pool = _StubPool()
    _run_trend(pool, teams="TEAM3,TEAM1")
    second = _run_trend(pool, teams="TEAM1,TEAM3")
    assert len(pool.params) == 1, "a reordered team list must hit the cache"
    assert second["meta"]["cached"] is True


def test_different_sets_never_share_a_cache_entry():
    pool = _StubPool()
    _run_trend(pool, teams="TEAM1")
    resp = _run_trend(pool, teams="TEAM2")
    assert len(pool.params) == 2
    assert _queried_teams(pool.params[1]) == {"TEAM2"}
    assert resp["data"]["teams"] == ["TEAM2"]


def test_trend_endpoint_declares_teams_as_a_query_param():
    route = next(r for r in odc.router.routes if r.path.endswith("/trend-yoy"))
    assert "teams" in {p.name for p in route.dependant.query_params}


# --------------------------------------------------------------------------
# Per-team clones stay locked
# --------------------------------------------------------------------------


@pytest.mark.parametrize("router", odct.team_routers)
def test_team_clone_trend_declares_no_teams_param(router):
    """FastAPI DROPS an undeclared query param, so a crafted `?teams=TEAM2`
    never reaches a clone. Declaring it would be the leak."""
    route = next(r for r in router.routes if r.path.endswith("/trend-yoy"))
    assert "teams" not in {p.name for p in route.dependant.query_params}
    assert "teams" not in inspect.signature(route.endpoint).parameters


# --------------------------------------------------------------------------
# Frontend wire contract (source scan)
# --------------------------------------------------------------------------


def _hook_source() -> str:
    src = (_FRONTEND / "lib" / "ops-direct-compare-api.ts").read_text()
    start = src.index("export function useDCTrendYoY")
    return src[start : src.index("\n}\n", start)]


def test_frontend_hook_sends_teams_and_keys_on_it():
    hook = _hook_source()
    assert "teams=" in hook, "the hook must send the param the backend declares"
    key = re.search(r"queryKey:\s*\[(.*?)\]", hook, re.S)
    assert key and "teams" in key.group(1), "queryKey must cover the teams in the qs"


def test_chart_team_filter_never_touches_the_url():
    """'Must apply exclusively to this chart' — local state, not the panels'
    URL-backed filters."""
    src = (_FRONTEND / "app" / "reports" / "ops-direct-compare" / "sections" / "TrendYoY.tsx").read_text()
    assert "useSearchParams" not in src and "router.replace" not in src
