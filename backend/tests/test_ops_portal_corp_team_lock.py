"""CORP T1..T4 OPS Kam Portals — a crafted ``?team=`` must never widen a clone.

Found 2026-11-09 while building the DFW TM1-4 clones: the CORP clone registered
``/team-performance-by-team`` with a comment saying the breakdown "collapses to a
single team row", but the shared function IGNORES ``team`` ("this panel always
returns all CORP teams"). A T1 KAM with a hand-made URL — or the Teams AI
assistant, whose section list is the live route table — read every CORP team.

Asserted end to end: every endpoint of every clone is called through FastAPI
with another team in ``team`` / ``teams``; the bound parameters and the SQL of
every statement (stub pool, no database) must name only the clone's own team.
"""

from __future__ import annotations

import importlib
import inspect
import json
import pathlib
import re

import pytest
from dfw_marker_sql import strip_dfw_marker_rule
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.routers import deps as deps_mod
from app.routers import ops_portal_overview as opo
from app.routers import ops_portal_overview_team as mod
from app.routers.ops_portal_overview import meta as _meta

TEAMS = ("TEAM1", "TEAM2", "TEAM3", "TEAM4")
ALL_CORP_TEAMS = ("TEAM1", "TEAM2", "TEAM3", "TEAM4", "TEAM5")
FRONTEND = pathlib.Path(__file__).resolve().parents[2] / "frontend"

# Cross-team breakdowns: never on a locked clone (their UI buttons are hidden
# whenever `lockedTeam` is set — asserted in test_ops_portal_dfw_team_scope.py).
NOT_ON_A_CLONE = {"team-projection-by-team", "team-performance-by-team"}
# Division/team-blind by design: feed staleness, calendar, EIA diesel.
UNSCOPED_BY_DESIGN = {"data-freshness", "workdays", "fuel"}


def _slug(path: str) -> str:
    return path.rsplit("/", 1)[-1]


def _routes(router) -> dict[str, object]:
    return {_slug(r.path): r.endpoint for r in router.routes}


def _router(team: str):
    n = team[-1]
    hits = [r for r in mod.team_routers if r.prefix.endswith(f"-t{n}")]
    assert len(hits) == 1, f"{team}: {len(hits)} routers"
    return hits[0]


@pytest.mark.parametrize("team", TEAMS)
def test_no_cross_team_breakdown_is_registered_on_a_clone(team: str) -> None:
    assert not set(_routes(_router(team))) & NOT_ON_A_CLONE


def test_the_shared_breakdown_really_ignores_team() -> None:
    """The measurement behind NOT_ON_A_CLONE (§103): if this ever changes, the
    route could come back — locked — on the clones."""
    src = inspect.getsource(opo.team_performance_by_team)
    assert "team filter intentionally dropped" in src


def test_the_division_portal_still_has_the_breakdown() -> None:
    """Only the clones lose it; the unlocked CORP portal and its digest keep it."""
    assert "team-performance-by-team" in {_slug(r.path) for r in opo.router.routes}


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
    names = [f"app.routers.ops_portal_overview.{p.stem}"
             for p in pathlib.Path(pkg.__file__).parent.glob("*.py")]
    for name in [*names, mod.__name__]:
        m = importlib.import_module(name)
        for getter in _POOL_GETTERS:
            if hasattr(m, getter):
                monkeypatch.setattr(m, getter, lambda request, _p=pool: _p)


def _client(monkeypatch, team: str) -> tuple[TestClient, _StubPool]:
    pool = _StubPool()
    _patch_pools(monkeypatch, pool)
    _meta._freshness_cache["at"] = None
    app = FastAPI()
    app.include_router(_router(team), prefix="/api")
    app.dependency_overrides[deps_mod.require_user] = lambda: {"sub": "t", "roles": ["admin"]}
    return TestClient(app, raise_server_exceptions=False), pool


def _is_division_list(values) -> bool:
    """The CORP division membership (TEAM1..TEAM5 together) is bound or inlined
    on purpose — it is the scope, not a team filter. Only a list naming EVERY
    CORP team counts, so a widened team filter can never hide behind it."""
    return set(ALL_CORP_TEAMS) <= {str(x).strip().upper() for x in values}


def _bound(pool: _StubPool) -> list[str]:
    out: list[str] = []
    for _sql, params in pool.calls:
        for p in params:
            items = p if isinstance(p, (list, tuple)) else [p]
            if isinstance(p, (list, tuple)) and _is_division_list(items):
                continue
            out.extend(str(x).strip().upper() for x in items)
    return out


_IN_LIST = re.compile(r"\(([^()]*'TEAM[^()]*)\)")


def _drop_division_lists(sql: str) -> str:
    def repl(m: re.Match) -> str:
        values = re.findall(r"'([^']*)'", m.group(1))
        return "(<corp-division>)" if _is_division_list(values) else m.group(0)
    return _IN_LIST.sub(repl, sql)


def _sql(pool: _StubPool) -> str:
    return "\n".join(_drop_division_lists(strip_dfw_marker_rule(sql)) for sql, _ in pool.calls)


def test_the_division_list_filter_cannot_hide_a_single_foreign_team() -> None:
    assert _is_division_list(["TEAM1 ", "TEAM2", "TEAM3", "TEAM4", "TEAM5"])
    assert not _is_division_list(["TEAM1", "TEAM2"])
    assert "'TEAM2'" in _drop_division_lists("x IN ('TEAM1','TEAM2')")
    assert "'TEAM2'" not in _drop_division_lists("x IN ('TEAM1','TEAM2','TEAM3','TEAM4','TEAM5')")


def _cases():
    return [(t, s) for t in TEAMS for s in _routes(_router(t))]


@pytest.mark.parametrize("team,slug", _cases())
def test_a_crafted_team_is_ignored_and_only_its_own_team_is_bound(monkeypatch, team: str, slug: str) -> None:
    client, pool = _client(monkeypatch, team)
    other = TEAMS[(TEAMS.index(team) + 1) % len(TEAMS)]
    n = team[-1]
    client.get(f"/api/custom/ops-portal-overview-t{n}/{slug}",
               params={"team": other, "teams": f"{other},TEAM5"})
    if not pool.calls:
        assert slug in UNSCOPED_BY_DESIGN, f"{slug} emitted no SQL — the probe would be vacuous"
        return
    bound = _bound(pool)
    sql = _sql(pool)
    for foreign in set(ALL_CORP_TEAMS) - {team}:
        assert foreign not in bound, f"T{n} /{slug} binds {foreign}"
        assert f"'{foreign}'" not in sql, f"T{n} /{slug} inlines {foreign}"
    if slug not in UNSCOPED_BY_DESIGN:
        assert team in json.dumps(bound) + sql, f"T{n} /{slug} is not narrowed to {team}"
