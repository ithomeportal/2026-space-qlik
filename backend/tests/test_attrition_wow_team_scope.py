"""Scope-lock proof for the per-CORP-team Attrition WoW clones.

Runs entirely offline (no DB, no network): every clone endpoint is driven with
a stub pool that records the SQL and params it was handed, and we assert that
the team parameter emitted is EXACTLY that router's locked team.

Why this is a test and not a one-off script: the shims delegate into the
1.7k-line parent router, so a future edit to ``attrition_wow.py`` (a new
endpoint, a renamed param, a widened default) can silently unlock the clones.
The failure mode is invisible — TEAM1's KAM simply starts seeing TEAM2's
customers, with no error anywhere.
"""

from __future__ import annotations

import re
from types import SimpleNamespace

import pytest
from fastapi import Response

from app.datalake import pad_variants
from app.routers import attrition_wow_team as awt

ALL_TEAM_VARIANTS = set(
    pad_variants(("TEAM1", "TEAM2", "TEAM3", "TEAM4", "TEAM5", "TEAM-DFW"), width=8)
)

# One fixed, non-default argument set per endpoint so no branch is skipped.
ARGS: dict[str, dict] = {
    "filters": {},
    "freshness": {},
    "summary": dict(customer=None, contract=None, lane=None),
    "weekly_trends": dict(weeks=15, customer=None, contract=None, lane=None),
    "customer_attrition": dict(weeks=15, customer=None, contract=None, lane=None),
    "pivot": dict(
        dim="customer", metric="loads", weeks=12,
        customer=None, contract=None, lane=None,
    ),
    "reactive_summary": dict(customer=None, contract=None),
    "lane_summary": dict(customer=None, contract=None),
    "wow_variation": dict(customer=None, contract=None),
    "losses": dict(
        customer=None, contract=None, lane=None,
        range="ytd", date_from=None, date_to=None,
    ),
}

USER = {"sub": "probe", "email": "probe@example.com", "roles": ["admin"]}


class _RecordingPool:
    """Stub asyncpg pool: records every statement, returns empty results."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, str, tuple]] = []

    async def fetch(self, sql, *params):
        self.calls.append(("fetch", sql, params))
        return []

    async def fetchrow(self, sql, *params):
        self.calls.append(("fetchrow", sql, params))
        return None

    async def fetchval(self, sql, *params):
        self.calls.append(("fetchval", sql, params))
        return None

    async def execute(self, sql, *params):
        self.calls.append(("execute", sql, params))
        return None


def _request(pool: _RecordingPool) -> SimpleNamespace:
    state = SimpleNamespace(savings_pool=pool, pool=pool)
    return SimpleNamespace(app=SimpleNamespace(state=state), headers={}, query_params={})


def test_every_clone_endpoint_is_mapped():
    """A new parent endpoint must be added here deliberately, not skipped."""
    for router in awt.team_routers:
        for route in router.routes:
            assert route.endpoint.__name__ in ARGS, (
                f"unmapped endpoint {route.endpoint.__name__} — add it to ARGS "
                "so its scope is proven too"
            )


def test_route_surface_is_four_routers_of_ten_get_endpoints():
    assert len(awt.team_routers) == len(awt.TEAM_CONFIGS) == 4
    paths = [rt.path for r in awt.team_routers for rt in r.routes]
    assert len(paths) == 40
    assert len(set(paths)) == 40
    for _team, slug, _role in awt.TEAM_CONFIGS:
        assert sum(p.startswith(f"/custom/attrition-wow-{slug}/") for p in paths) == 10


@pytest.mark.asyncio
async def test_emitted_sql_is_locked_to_the_routers_own_team():
    checked = 0
    for router, (team, slug, _role) in zip(awt.team_routers, awt.TEAM_CONFIGS):
        expected = set(pad_variants((team,), width=8))
        for route in router.routes:
            name = route.endpoint.__name__
            pool = _RecordingPool()
            try:
                await route.endpoint(
                    request=_request(pool), response=Response(), _user=USER,
                    **ARGS[name],
                )
            except Exception:
                # A stub pool returning [] can legitimately break downstream
                # arithmetic. What matters is the SQL emitted before it did.
                pass

            assert pool.calls, f"{slug}/{name} emitted no SQL at all"

            for _kind, sql, params in pool.calls:
                for p in params:
                    if not isinstance(p, (list, tuple)):
                        continue
                    got = set(p)
                    if not (got & ALL_TEAM_VARIANTS):
                        continue
                    checked += 1
                    assert got == expected, (
                        f"{slug}/{name}: team param {sorted(got)!r} is not the "
                        f"locked {sorted(expected)!r}"
                    )

                # A bare 'TEAM-DFW' literal is legitimate ONLY inside
                # _team_dim's display-grain CASE (CORP rows fall through to
                # ELSE TRIM(team_id)). Anywhere else it would widen the scope.
                for m in re.finditer(r"'TEAM-DFW'", sql):
                    ctx = sql[max(0, m.start() - 220) : m.start() + 60]
                    assert "CASE WHEN" in ctx, (
                        f"{slug}/{name}: 'TEAM-DFW' literal outside _team_dim"
                    )

    assert checked >= 40, f"only {checked} team-scoped params seen — probe went blind"


def test_report_keys_match_the_seed_catalog():
    """4-place mirror: a key mismatch makes require_report_access look up a
    report row that does not exist, and every endpoint 403s into a blank page."""
    from app.services.seed import CUSTOM_REPORTS

    keys = {r["key"] for r in CUSTOM_REPORTS}
    for _team, slug, _role in awt.TEAM_CONFIGS:
        assert f"corp-{slug}-attrition-wow" in keys


def test_seeded_roles_match_the_factory_config():
    from app.services.seed import CUSTOM_REPORTS

    by_key = {r["key"]: r for r in CUSTOM_REPORTS}
    for _team, slug, role in awt.TEAM_CONFIGS:
        assert role in by_key[f"corp-{slug}-attrition-wow"]["roles"]
