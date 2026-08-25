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
  * the Delay Time column (PDF 2026-08-24 R1, replacing "Date") is guarded on
    both halves of its rule: the sentinel AND the "already passed" filter.
    110 of 273 status='P' rows carry a 1900-01-01 `dest_sched_late`; unguarded
    they render as ~-46,000 days, which no row-count test would catch;
  * POD Age follows the POD Tracker's anchor (actual delivery, falling back to
    the SCHEDULED late delivery) and only runs once that anchor has passed.
    The same expression lives in By Order, and the two must not diverge — they
    sit on one page and describe the same orders (§69).

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
            exclude_lanes=None, sort="delay_asc", limit=500, _user={},
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
    assert "ORDER BY delay_days ASC NULLS LAST" in pool.sql


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


def test_the_delay_column_is_guarded_by_the_sentinel_and_by_today() -> None:
    """Delay Time must never do arithmetic on 1900-01-01, and never on a
    delivery still in the future.

    McLeod writes the sentinel instead of NULL here too, and it is NOT rare:
    110 of the 273 status='P' rows carry a sentinel `dest_sched_late`
    (measured 2026-08-21). Unguarded, `sentinel - CURRENT_DATE` renders as
    about -46,000 days and sorts to the top of an ascending Delay column — so
    the failure mode is a board whose first page is entirely garbage.

    Asserted structurally rather than on data: with clean rows a missing guard
    changes nothing, which is exactly why this needs reading the statement.
    """
    pool, _ = _run()
    expr = pool.sql.split("END AS delay_days")[0].rsplit("CASE", 1)[1]

    assert "TRIM(br4.status) = 'P'" in expr, "Delay Time is in-progress only"
    assert "win.dest_sched_late_ts IS NOT NULL" in expr
    assert "win.dest_sched_late_ts::date < CURRENT_DATE" in expr, (
        "the PDF says 'already passed' — without this every future delivery "
        "reads as a positive 'delay'"
    )
    # …and the LATERAL that produces the operand filtered the sentinel out.
    assert (
        "MAX(CASE WHEN cw.dest_sched_arrive_late > '2000-01-01' "
        "THEN cw.dest_sched_arrive_late END) AS dest_sched_late_ts"
    ) in pool.sql

    # No CASE arm may reach the subtraction without a guard.
    for arm in expr.split("WHEN")[1:]:
        cond = arm.split("THEN")[0]
        assert "IS NOT NULL" in cond or "'2000-01-01'" in cond or "CURRENT_DATE" in cond, (
            f"unguarded Delay arm: {cond.strip()!r}"
        )

    # The transit-days branch the "Date" column carried is GONE — one column,
    # one meaning (PDF 2026-08-24 R1).
    assert "AS date_days" not in pool.sql
    assert "win.dest_dep_ts::date)" not in expr


def test_delay_time_replaced_the_date_column_and_departure_came_back() -> None:
    """PDF 2026-08-24 R1 reverses 08-20 R2: Departure returns, Date becomes
    Delay Time, and Customer / Sched Dest Late / Actual Delivery join it.

    Bruno's rounds reverse each other — what matters is that the sort keys move
    WITH the column. A stale `date_asc` would not error; `_HOLD_SORTS.get()`
    would hand back the default and the board would silently ignore the click.
    """
    pool, resp = _run()
    for frag in (
        "AS departure",
        "AS delay_days",
        "AS sched_dest_late",
        "AS actual_delivery",
        "br4.customer_name   AS customer_name",
    ):
        assert frag in pool.sql, frag

    assert "date_asc" not in hold_mod._HOLD_SORTS
    assert "date_desc" not in hold_mod._HOLD_SORTS
    for key in ("delay_asc", "delay_desc", "departure_asc", "customer_asc"):
        assert key in hold_mod._HOLD_SORTS, key

    # Departure is a v4 column, so it carries its own sentinel comparison.
    assert (
        "CASE WHEN br4.origin_actual_departure > '2000-01-01'::date\n"
        "               THEN to_char(br4.origin_actual_departure, 'YYYY-MM-DD') END AS departure"
    ) in pool.sql


def test_the_removed_columns_are_still_served() -> None:
    """Carrier Cost and Margin % left the TABLE, not the endpoint.

    The pinned totals row still sums carrier cost, so dropping them from the
    payload would blank a number nobody asked to remove.
    """
    pool, resp = _run()
    assert "AS carrier_cost" in pool.sql
    assert "AS margin" in pool.sql
    assert "t_carrier_cost" in pool.sql


def test_pod_age_uses_the_pod_tracker_anchor() -> None:
    """PDF 2026-08-24 R1: "the same calculation method as the POD Tracker".

    Two rules from AP_module's `lib/pod-tracker-age.ts`:
      * anchor = actual delivery, falling back to the SCHEDULED late delivery
        (NOT to dest_actual_departure — on an in-progress load only the
        schedule exists: 13 of 178 CORP rows had an actual arrival on
        2026-08-24, all 178 had a schedule);
      * the clock runs only once that anchor has passed, or status is 'D' —
        otherwise a load is "POD overdue" before it has arrived.
    """
    pool, _ = _run()
    anchor = "COALESCE(win.arr_ts, win.dest_sched_late_ts)"
    assert f"CASE WHEN {anchor} IS NOT NULL" in pool.sql
    assert f"{anchor} <= CURRENT_TIMESTAMP" in pool.sql
    assert "OR TRIM(br4.status) = 'D'" in pool.sql
    assert f"EXTRACT(EPOCH FROM (CURRENT_TIMESTAMP - {anchor})) / 3600.0" in pool.sql
    # The old fallback must be gone, or the two anchors coexist and the column
    # means whichever one the row happens to hit.
    assert "COALESCE(win.arr_ts, win.dest_dep_ts)" not in pool.sql


def test_by_order_pod_age_matches_the_hold_boards() -> None:
    """One metric, one definition — the two tables share a page (§69)."""
    import inspect

    from app.routers.ops_portal_overview import orders as orders_mod

    src = inspect.getsource(orders_mod)
    anchor = "COALESCE(win.arr_ts, win.dest_sched_late_ts)"
    assert f"EXTRACT(EPOCH FROM (CURRENT_TIMESTAMP - {anchor})) / 3600.0" in src
    assert f"{anchor} <= CURRENT_TIMESTAMP" in src
    assert "COALESCE(win.arr_ts, win.dest_dep_ts)" not in src
    # …and its LATERAL must actually produce the fallback it now reads.
    assert (
        "MAX(CASE WHEN cw.dest_sched_arrive_late > '2000-01-01' "
        "THEN cw.dest_sched_arrive_late END) AS dest_sched_late_ts"
    ) in src


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
    """All six portals render the SAME OpsPortalOverviewContent.

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


def test_every_delegator_advertises_a_sort_key_that_exists() -> None:
    """The 5 clone shims must track hold.py's own default.

    Found during close-out: the shims still declared `departure_desc` after the
    Departure column was removed. It "worked" — `_HOLD_SORTS.get(sort, default)`
    falls back — so no request failed, while every clone's OpenAPI schema
    advertised a sort key that no longer existed and the fallback quietly did
    the work. A whitelist with a default hides exactly this.
    """
    import inspect

    from app.routers import ops_portal_overview_dfw as dfw_mod
    from app.routers import ops_portal_overview_team as team_mod

    default = inspect.signature(hold_mod.hold_board).parameters["sort"].default.default
    assert default in hold_mod._HOLD_SORTS

    for mod in (team_mod, dfw_mod):
        src = inspect.getsource(mod)
        shim = src.split('@r.get("/hold")')[1].split("return await")[0]
        declared = shim.split('sort: str = Query("')[1].split('"')[0]
        assert declared in hold_mod._HOLD_SORTS, (
            f"{mod.__name__} advertises sort={declared!r}, which is not whitelisted"
        )
        assert declared == default, (
            f"{mod.__name__} default {declared!r} != hold.py default {default!r}"
        )


def test_the_module_name_is_not_shadowed_by_its_endpoint() -> None:
    """`from .hold import hold` would rebind the submodule to the function."""
    import importlib

    assert isinstance(
        importlib.import_module("app.routers.ops_portal_overview.hold"),
        types.ModuleType,
    )
