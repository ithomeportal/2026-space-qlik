"""Ops Portal - Overview: the Hold board (Bruno PDF 2026-08-19 R1).

Offline — a stub pool captures the SQL the endpoint actually emits, so these
assertions read the real statement rather than a paraphrase of it.

The properties worth pinning are the two that were *decisions*, not mechanics:

  * the board is NOT date-windowed (holds sit for months; measured 2026-08-19,
    a date filter would have shown 2 of the 18 open holds and hidden the stale
    ones the board exists to surface);
  * status is EXCLUDED ('V','A'), never allow-listed ('D','P'). Those match
    today because v4 only ever holds D/V/A/P, so a regression here would be
    invisible in the data and would only bite when McLeod adds a status.
"""

from __future__ import annotations

import asyncio
import types

import pytest

from app.routers import ops_portal_overview as opo
from app.routers.ops_portal_overview import hold as hold_mod


class _StubPool:
    """Captures the statement instead of running it."""

    def __init__(self) -> None:
        self.sql: str | None = None
        self.params: list = []

    async def fetch(self, sql, *params):
        self.sql = sql
        self.params = list(params)
        return []


def _run(**kwargs):
    """Drive the endpoint against a stub pool; return (pool, response)."""
    pool = _StubPool()
    original = hold_mod.get_datalake_gold_pool
    hold_mod.get_datalake_gold_pool = lambda request: pool
    try:
        request = types.SimpleNamespace(
            app=types.SimpleNamespace(state=types.SimpleNamespace())
        )
        params = dict(
            request=request, team=None, customer=None, lanes=None,
            exclude_lanes=None, sort="departure_desc", limit=500, _user={},
        )
        params.update(kwargs)
        resp = asyncio.run(hold_mod.hold_board(**params))
    finally:
        hold_mod.get_datalake_gold_pool = original
    return pool, resp


# --------------------------------------------------------------------------
# The two decisions
# --------------------------------------------------------------------------


def test_the_board_is_not_date_windowed() -> None:
    """No date predicate at all — the whole point of the board.

    Holds routinely sit for months. Adding `origin_actual_departure >= ...`
    here would quietly drop the oldest, most stuck loads: exactly the rows
    somebody opens this table to find.
    """
    pool, _ = _run()
    assert "origin_actual_departure >=" not in pool.sql
    assert "origin_actual_departure <" not in pool.sql
    # ...but it is still fine to ORDER BY that column.
    assert "ORDER BY br4.origin_actual_departure" in pool.sql


def test_status_is_excluded_not_allow_listed() -> None:
    """`<> ALL('V','A')`, never `= ANY('D','P')`.

    The two are the same set today, so this cannot be caught by comparing row
    counts — only by reading the rule.
    """
    pool, _ = _run()
    assert "br4.status    <> ALL($4)" in pool.sql
    assert pool.params[3] == list(hold_mod.EXCLUDED_HOLD_STATUSES)
    assert "OPEN_STATUSES" not in pool.sql
    assert "= ANY($4)" not in pool.sql


# --------------------------------------------------------------------------
# Scope
# --------------------------------------------------------------------------


def test_hold_flag_and_corp_scope_are_always_applied() -> None:
    pool, _ = _run()
    assert "br4.on_hold    = ANY($3)" in pool.sql
    assert "Y" in pool.params[2]
    assert "br4.team_id    = ANY($1)" in pool.sql
    assert "br4.company_id = ANY($2)" in pool.sql
    assert "NOT LIKE '%OILTEX%'" in pool.sql
    # Padded + unpadded twins, or the CORP teams silently match nothing.
    assert "TEAM1" in pool.params[0] and "TEAM1   " in pool.params[0]


def test_a_team_pin_narrows_rather_than_replaces_the_corp_scope() -> None:
    """A scope-locked clone must not be able to widen past CORP."""
    pool, _ = _run(team="TEAM2")
    # Count in the main WHERE only: br4.team_id also appears in the SELECT
    # list, and the two LATERALs carry their own WHERE, so it is the LAST one.
    where = pool.sql.rsplit("WHERE ", 1)[1].split("ORDER BY")[0]
    assert where.count("br4.team_id") == 2, "the pin must ADD a predicate"
    assert "TEAM2   " in pool.params[4]
    # The CORP list is still the first predicate.
    assert "TEAM5" in pool.params[0]


def test_unknown_sort_falls_back_instead_of_reaching_sql() -> None:
    """`sort` is user input and is interpolated, so it must be whitelisted."""
    pool, _ = _run(sort="1; DROP TABLE mcleod_gld_budget_report_v4; --")
    assert "DROP TABLE" not in pool.sql
    assert "ORDER BY br4.origin_actual_departure DESC NULLS LAST" in pool.sql


@pytest.mark.parametrize("key", sorted(hold_mod._HOLD_SORTS))
def test_every_whitelisted_sort_renders(key: str) -> None:
    pool, _ = _run(sort=key)
    assert f"ORDER BY {hold_mod._HOLD_SORTS[key]}" in pool.sql


# --------------------------------------------------------------------------
# Columns Bruno asked for that did NOT previously exist on the wire
# --------------------------------------------------------------------------


def test_bill_date_strips_the_mcleod_sentinel() -> None:
    """1900-01-01 means "not billed" — rendering it as a date would be a lie."""
    pool, _ = _run()
    assert "br4.bill_date > '2000-01-01'::date" in pool.sql
    assert "to_char(br4.bill_date, 'YYYY-MM-DD')" in pool.sql


def test_carrier_cost_uses_total_carrier_pay_not_revenue_minus_profit() -> None:
    """One definition, shared with the Cover board (§69)."""
    pool, _ = _run()
    assert "COALESCE(br4.total_carrier_pay, 0)::numeric AS carrier_cost" in pool.sql


def test_totals_describe_the_full_universe_not_the_capped_page() -> None:
    """§44 — window aggregates run after WHERE but before LIMIT."""
    pool, _ = _run(limit=1)
    assert "COUNT(*) OVER ()" in pool.sql
    assert pool.params[-1] == 1


def test_empty_result_still_returns_a_totals_envelope() -> None:
    """The stub returns no rows; the response must not KeyError or 500."""
    _, resp = _run()
    assert resp["success"] is True
    assert resp["data"] == []
    assert resp["meta"]["totals"]["n_orders"] == 0
    assert resp["meta"]["totals"]["margin_pct"] == 0.0


# --------------------------------------------------------------------------
# Wiring — the failure mode that would 404 four live pages
# --------------------------------------------------------------------------


def test_the_facade_exports_hold_board() -> None:
    assert callable(opo.hold_board)
    assert "hold_board" in opo.__all__


def test_the_route_is_registered_once() -> None:
    paths = [r.path for r in opo.router.routes]
    assert paths.count("/custom/ops-portal-overview/hold") == 1


def test_the_team_clones_delegate_hold_with_every_param() -> None:
    """All five portals render the SAME OpsPortalOverviewContent.

    Without a delegator the Hold board 404s on the four CORP team pages while
    the main portal looks perfectly healthy. And a dropped param would widen a
    scope-locked clone (§40).
    """
    import inspect

    from app.routers import ops_portal_overview_team as team_mod

    src = inspect.getsource(team_mod)
    assert '@r.get("/hold")' in src
    assert "opo.hold_board(" in src
    for param in ("customer=customer", "lanes=lanes",
                  "exclude_lanes=exclude_lanes", "sort=sort", "limit=limit"):
        assert param in src, f"delegator drops {param}"
    # team is pinned from the closure, never taken from the query string.
    hold_call = src.split("opo.hold_board(")[1].split(")")[0]
    assert "team=team" in hold_call


def test_the_module_name_is_not_shadowed_by_its_endpoint() -> None:
    """`from .hold import hold` would rebind the submodule to the function."""
    import importlib

    assert isinstance(
        importlib.import_module("app.routers.ops_portal_overview.hold"),
        types.ModuleType,
    )
