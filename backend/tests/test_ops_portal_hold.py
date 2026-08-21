"""Ops Portal - Overview: the Hold board (Bruno PDF 2026-08-19 R1).

Offline — a stub pool captures the SQL the endpoint actually emits, so these
assertions read the real statement rather than a paraphrase of it.

The properties worth pinning are the ones that were *decisions*, not mechanics:

  * the board is NOT date-windowed (holds and unbilled orders sit for months;
    measured 2026-08-19, a date filter would have shown 2 of the 18 open holds
    and hidden the stale ones the board exists to surface, §74);
  * status is EXCLUDED ('V','A'), never allow-listed ('D','P'). Those match
    today because v4 only ever holds D/V/A/P, so a regression here would be
    invisible in the data and would only bite when McLeod adds a status;
  * since PDF 2026-08-20 R2 the filter is `bill_date < sentinel`, NOT
    `on_hold='Y'` — with a hard floor at `UNBILLED_FROM`, because 2021 is an
    ETL artifact (99.4% sentinel that year) and without the floor the board is
    59,139 rows of which ~58,500 are phantom;
  * the Date column's every operand is sentinel-guarded on BOTH branches.
    110 of 273 status='P' rows carry a 1900-01-01 `dest_sched_late`; unguarded
    they render as ~-46,000 days, which no row-count test would catch.

⚠ Several assertions read the SQL TEXT rather than the data, deliberately: with
correct data, reverting these rules still returns plausible rows. They are
mutation-checked — flip the rule and the test must fail.
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
            exclude_lanes=None, sort="date_asc", limit=500, _user={},
        )
        params.update(kwargs)
        resp = asyncio.run(hold_mod.hold_board(**params))
    finally:
        hold_mod.get_datalake_gold_pool = original
    return pool, resp


# --------------------------------------------------------------------------
# The two decisions
# --------------------------------------------------------------------------


def test_the_board_is_not_windowed_by_the_pages_date_filter() -> None:
    """No `range`/`start_date`/`end_date` reaches the SQL — the point of it.

    Unbilled orders routinely sit for months. Inheriting the page's window
    would quietly drop the oldest, most stuck loads: exactly the rows somebody
    opens this table to find (§74).
    """
    import inspect

    pool, _ = _run()
    assert "br4.origin_actual_departure >=" not in pool.sql
    assert "br4.origin_actual_departure <" not in pool.sql
    # The endpoint must not even ACCEPT date params.
    sig = inspect.signature(hold_mod.hold_board).parameters
    for p in ("range", "start_date", "end_date"):
        assert p not in sig, f"the board must not accept {p}"


def test_the_unbilled_floor_is_a_fixed_constant_and_is_reported() -> None:
    """`UNBILLED_FROM` excludes the 2021 ETL gap, and says so.

    Bare `bill_date < sentinel` matches 59,139 rows table-wide because the
    2021 feed never wrote bill_date (99.4% sentinel that year vs ~0.0% in
    2022-2025). The floor cuts that to ~350 CORP / ~220 DFW. It is a
    data-quality constant, NOT the page's window — it must never move when the
    user changes the date filter — and the drop must be visible to the UI.
    """
    pool, resp = _run()
    assert f"br4.ordered_date >= '{hold_mod.UNBILLED_FROM}'::date" in pool.sql
    assert resp["meta"]["unbilled_from"] == hold_mod.UNBILLED_FROM
    # Identical whatever else the caller passes — it is not a filter.
    other, _ = _run(team="TEAM2", customer="ACME", limit=7)
    assert f"br4.ordered_date >= '{hold_mod.UNBILLED_FROM}'::date" in other.sql


def test_the_filter_is_unbilled_not_on_hold() -> None:
    """PDF 2026-08-20 R2 — `on_hold` is SHOWN, never filtered on.

    Text-level on purpose: the old population is a subset of the new one (3 of
    350 CORP rows are also on_hold today), so a row-count check cannot tell
    the two rules apart.
    """
    pool, _ = _run()
    assert f"br4.bill_date < '{hold_mod.BILL_SENTINEL}'::date" in pool.sql
    where = pool.sql.rsplit("WHERE ", 1)[1].split("ORDER BY")[0]
    assert "on_hold" not in where, "on_hold must not be a filter any more"
    # ...but it is still selected, so the column renders off the DATA.
    assert "(TRIM(COALESCE(br4.on_hold,'')) = 'Y') AS on_hold" in pool.sql


def test_status_is_excluded_not_allow_listed() -> None:
    """`<> ALL('V','A')`, never `= ANY('D','P')`.

    The two are the same set today, so this cannot be caught by comparing row
    counts — only by reading the rule.
    """
    pool, _ = _run()
    assert "br4.status    <> ALL($3)" in pool.sql
    assert pool.params[2] == list(hold_mod.EXCLUDED_HOLD_STATUSES)
    assert "OPEN_STATUSES" not in pool.sql
    assert "br4.status     = ANY(" not in pool.sql


# --------------------------------------------------------------------------
# Scope
# --------------------------------------------------------------------------


def test_the_division_scope_is_always_applied() -> None:
    pool, _ = _run()
    assert "br4.team_id    = ANY($1)" in pool.sql
    assert "br4.company_id = ANY($2)" in pool.sql
    assert "NOT LIKE '%OILTEX%'" in pool.sql
    # Padded + unpadded twins, or the CORP teams silently match nothing.
    assert "TEAM1" in pool.params[0] and "TEAM1   " in pool.params[0]


def test_a_team_pin_narrows_rather_than_replaces_the_corp_scope() -> None:
    """A scope-locked clone must not be able to widen past CORP."""
    pool, _ = _run(team="TEAM2")
    # Count in the main WHERE only: the two LATERALs carry their own WHERE, so
    # the board's predicate is the LAST one.
    where = pool.sql.rsplit("WHERE ", 1)[1].split("ORDER BY")[0]
    assert where.count("br4.team_id") == 2, "the pin must ADD a predicate"
    assert "TEAM2   " in pool.params[3]
    # The CORP list is still the first predicate.
    assert "TEAM5" in pool.params[0]


def test_unknown_sort_falls_back_instead_of_reaching_sql() -> None:
    """`sort` is user input and is interpolated, so it must be whitelisted."""
    pool, _ = _run(sort="1; DROP TABLE mcleod_gld_budget_report_v4; --")
    assert "DROP TABLE" not in pool.sql
    assert "ORDER BY date_days ASC NULLS LAST" in pool.sql


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


def test_every_date_operand_is_sentinel_guarded_on_both_branches() -> None:
    """The Date column must never do arithmetic on 1900-01-01.

    McLeod writes the sentinel instead of NULL here too, and it is NOT rare:
    110 of the 273 status='P' rows carry a sentinel `dest_sched_late`
    (measured 2026-08-21). Unguarded, `sentinel - CURRENT_DATE` renders as
    about -46,000 days and sorts to the top of an ascending Date column — so
    the failure mode is a board whose first page is entirely garbage.

    Asserted structurally rather than on data: with clean rows a missing guard
    changes nothing, which is exactly why this needs reading the statement.
    """
    pool, _ = _run()
    expr = pool.sql.split("END AS date_days")[0].rsplit("CASE", 1)[1]

    # status='P' branch — dest_sched_late must be NULL-checked, and the LATERAL
    # that produces it must itself have filtered the sentinel out.
    assert "win.dest_sched_late_ts IS NOT NULL" in expr
    assert (
        "MAX(CASE WHEN cw.dest_sched_arrive_late > '2000-01-01' "
        "THEN cw.dest_sched_arrive_late END) AS dest_sched_late_ts"
    ) in pool.sql

    # status='D' branch — BOTH operands, and origin_actual_departure comes
    # straight off v4 so it needs its own explicit comparison.
    assert "win.dest_dep_ts IS NOT NULL" in expr
    assert "br4.origin_actual_departure > '2000-01-01'::date" in expr
    assert (
        "MAX(CASE WHEN cw.dest_actual_departure  > '2000-01-01' "
        "THEN cw.dest_actual_departure  END) AS dest_dep_ts"
    ) in pool.sql

    # No CASE arm may reach the subtraction without a guard: every WHEN in the
    # expression must mention IS NOT NULL or the sentinel comparison.
    arms = [a for a in expr.split("WHEN")[1:]]
    for arm in arms:
        cond = arm.split("THEN")[0]
        assert "IS NOT NULL" in cond or "'2000-01-01'" in cond, (
            f"unguarded Date arm: {cond.strip()!r}"
        )


def test_the_date_column_replaced_departure() -> None:
    """PDF 2026-08-20 R2 removed Departure and added Date."""
    pool, resp = _run()
    assert "AS date_days" in pool.sql
    assert "AS departure" not in pool.sql
    assert "departure_asc" not in hold_mod._HOLD_SORTS
    assert "date_asc" in hold_mod._HOLD_SORTS and "date_desc" in hold_mod._HOLD_SORTS


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
