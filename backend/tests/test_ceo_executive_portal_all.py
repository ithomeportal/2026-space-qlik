"""Executive OPS Portal — the ALL division (Erick Mendoza, 2026-09-24).

"me falta el de ALL … porque Bruce también debe de ver las dos divisiones."

ALL is a THIRD ``DivisionScope`` over the same engine, not new SQL: CORP's five
``team_id`` values plus ``TEAM-DFW`` as a sixth, team column ``team_id``, no
budget. What must hold:

* it is built FROM the two live scopes, so it cannot drift from either;
* every endpoint scopes to BOTH divisions under it (not one, not neither);
* budget panels 404 under it — the budget table is CORP-only, so a variance
  would set CORP+DFW actuals against a CORP-only plan;
* Customer Monthly Variance takes the month-over-month definition, over ALL's
  population — not DFW's;
* the projection history tracks it, and the startup seed backfills a scope
  added AFTER the first deploy.

Helpers are imported from ``test_ceo_executive_portal`` so both files drive
the endpoints the same way (the real ``_pin_scope``, FastAPI's defaults).
"""

from __future__ import annotations

import asyncio
import types

import pytest
from fastapi import HTTPException

import test_ceo_executive_portal as base
from app.routers import ops_portal_overview_ceo as ceo
from app.routers.ops_portal_overview._scope import (
    ALL_SCOPE,
    CORP_SCOPE,
    DFW_SCOPE,
    DIVISIONS,
    sub_team_of,
    sub_teams_of,
)
from app.services import projection_history as ph

DFW_ID = base.DFW_ID


# ---------------------------------------------------------------------------
# The scope itself
# ---------------------------------------------------------------------------


def test_all_is_registered_and_built_from_the_two_live_scopes() -> None:
    assert DIVISIONS["all"] is ALL_SCOPE
    assert ALL_SCOPE.base_teams == CORP_SCOPE.base_teams + DFW_SCOPE.base_teams
    assert set(ALL_SCOPE.sub_teams) == set(CORP_SCOPE.base_teams) | {DFW_ID}


def test_all_names_teams_by_team_id_not_by_v4_team() -> None:
    """``v4.team`` is '' on CORP rows except 20 TEAM3 rows carrying TM1/TM4
    (2026-09-24). Keyed on it, those CORP loads would sit under a DFW pill."""
    assert ALL_SCOPE.v4_team_col == "team_id"
    assert ALL_SCOPE.sc_team_col == "team_id"
    assert ALL_SCOPE.padded_sub_teams is True


def test_all_has_no_budget() -> None:
    assert ALL_SCOPE.has_budget is False


@pytest.mark.parametrize(
    "value,expected",
    [
        ("TEAM1", "TEAM1"),
        ("team-dfw", DFW_ID),
        ("TM1", None),        # a DFW sub-team is foreign here — widen, not narrow
        ("TEAM9", None),
        (None, None),
    ],
)
def test_a_team_pill_under_all(value, expected) -> None:
    assert sub_team_of(ALL_SCOPE, value) == expected


def test_the_csv_team_form_under_all() -> None:
    assert sub_teams_of(ALL_SCOPE, "TEAM1,TM2,TEAM-DFW") == "TEAM1,TEAM-DFW"
    assert sub_teams_of(ALL_SCOPE, "TM1,TM2") is None


# ---------------------------------------------------------------------------
# Every endpoint, driven under `all`
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("slug,fn", base._routes(), ids=lambda v: v if isinstance(v, str) else "")
def test_every_endpoint_scopes_to_both_divisions_under_all(slug: str, fn) -> None:
    """Presence of BOTH — "absence of neither" would pass for an endpoint that
    still carried one division's literal."""
    if slug in base.BUDGET_PATHS:
        pytest.skip("404s under all — asserted separately")
    pool = base._drive(fn, division="all")
    if not pool.calls:
        pytest.skip(f"{slug} emits no SQL")
    blob = base._blob(pool)
    if slug in base.UNSCOPED_BY_DESIGN:
        assert DFW_ID not in blob
        return
    assert DFW_ID in blob, f"{slug} drops DFW from the ALL view"
    assert "TEAM1" in blob, f"{slug} drops CORP from the ALL view"


@pytest.mark.parametrize("slug,fn", base._routes(), ids=lambda v: v if isinstance(v, str) else "")
def test_no_endpoint_narrows_all_to_a_dfw_sub_team(slug: str, fn) -> None:
    """A TM1 pill left over from the DFW view must widen to ALL, never become
    a ``team_id = 'TM1'`` predicate that matches nothing (§75)."""
    if slug in base.BUDGET_PATHS:
        pytest.skip("404s under all")
    pool = base._drive(fn, division="all", **base._cross(fn, "TM1"))
    if not pool.calls:
        pytest.skip(f"{slug} emits no SQL")
    assert "TM1" not in base._blob(pool), f"{slug} passes TM1 into the ALL view"


@pytest.mark.parametrize("slug", sorted(base.BUDGET_PATHS))
def test_the_budget_panels_404_under_all(slug: str) -> None:
    with pytest.raises(HTTPException) as e:
        base._drive(dict(base._routes())[slug], division="all")
    assert e.value.status_code == 404


def test_customer_variance_under_all_is_month_over_month_over_both_divisions() -> None:
    """Dispatching on ``is DFW_SCOPE`` sent ALL to the budget definition; and a
    ``DFW_SCOPE`` literal in the DFW implementation would have served DFW's
    customers under an ALL heading. Both are asserted from the SQL."""
    blob = base._blob(base._drive(ceo.customer_variance, division="all"))
    assert "daily_production_budget_report" not in blob
    assert blob.count("FILTER (") >= 6
    assert DFW_ID in blob and "TEAM1" in blob


def test_customer_variance_still_serves_dfw_only_under_dfw() -> None:
    blob = base._blob(base._drive(ceo.customer_variance, division="dfw"))
    assert DFW_ID in blob
    for corp_id in base.CORP_IDS:
        assert corp_id not in blob


# ---------------------------------------------------------------------------
# Projection history — tracked, and seeded after the first deploy
# ---------------------------------------------------------------------------


def test_the_all_division_and_each_of_its_pills_are_tracked() -> None:
    keys = {(s, t) for s, t, _, _ in ph.SNAPSHOT_SCOPES}
    assert ("all", ph.ALL_TEAMS) in keys
    for t in ALL_SCOPE.sub_teams:
        assert ("all", t) in keys
    for s, t, scope, _ in ph.SNAPSHOT_SCOPES:
        if s == "all":
            assert scope is ALL_SCOPE


def test_a_tracked_all_pill_resolves_to_its_own_key() -> None:
    assert ph.resolve_history_key(ALL_SCOPE, []) == ph.ALL_TEAMS
    assert ph.resolve_history_key(ALL_SCOPE, [DFW_ID]) == DFW_ID
    assert ph.resolve_history_key(ALL_SCOPE, ["TM1"]) is None


class _HubStub:
    def __init__(self, rows):
        self.rows = rows
        self.sql: list[str] = []

    async def fetch(self, sql, *params):
        self.sql.append(sql)
        return self.rows


def test_unbackfilled_scopes_keys_on_backfill_rows_not_any_row() -> None:
    """The 02:45 job writes a LIVE row for every tracked scope — keyed on "any
    row", a scope added after the first deploy would be marked done with one
    day of history, for ever."""
    done = [{"scope_key": s, "team_key": t}
            for s, t, _, _ in ph.SNAPSHOT_SCOPES if s != "all"]
    hub = _HubStub(done)
    missing = asyncio.run(ph.unbackfilled_scopes(hub))
    assert {(s, t) for s, t, _, _ in missing} == {
        (s, t) for s, t, _, _ in ph.SNAPSHOT_SCOPES if s == "all"
    }
    assert "source = 'backfill'" in hub.sql[0]


def test_nothing_is_missing_once_every_scope_is_backfilled() -> None:
    hub = _HubStub([{"scope_key": s, "team_key": t} for s, t, _, _ in ph.SNAPSHOT_SCOPES])
    assert asyncio.run(ph.unbackfilled_scopes(hub)) == ()


def _run_seed(monkeypatch, missing):
    import app.main as main

    calls: dict[str, dict] = {}

    async def fake_missing(hub):
        return missing

    async def fake_backfill(hub, gold, **kw):
        calls["backfill"] = kw
        return {}

    async def fake_weekly(hub, gold, **kw):
        calls["weekly"] = kw
        return {}

    monkeypatch.setattr(ph, "unbackfilled_scopes", fake_missing)
    monkeypatch.setattr(ph, "backfill_projection_history", fake_backfill)
    monkeypatch.setattr(ph, "capture_weekly_actuals", fake_weekly)
    monkeypatch.setattr(main.app, "state", types.SimpleNamespace(pool=object(), savings_pool=object()))
    asyncio.run(main._seed_projection_history())
    return calls


def test_the_seed_replays_only_the_missing_scopes_in_both_writes(monkeypatch) -> None:
    """Both writes take the SAME list: the weekly one is DO UPDATE, so running
    it over every scope would relabel live rows as 'backfill'."""
    missing = tuple(s for s in ph.SNAPSHOT_SCOPES if s[0] == "all")
    calls = _run_seed(monkeypatch, missing)
    assert calls["backfill"]["scopes"] == missing
    assert calls["weekly"]["scopes"] == missing
    assert calls["weekly"]["source"] == "backfill"


def test_the_seed_does_nothing_when_every_scope_is_backfilled(monkeypatch) -> None:
    assert _run_seed(monkeypatch, ()) == {}
