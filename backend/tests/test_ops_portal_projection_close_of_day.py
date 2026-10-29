"""Monthly Projection — close of the previous day, and a weekend is ONE day.

Request 2026-10-20 (`Pictures/tasl.txt`, OPS Managers Portal):

  * "look like is not using CST time but UTC. The user see at some point in the
    afternoon that the values change, when normally is using the closing of the
    day before." — The clock was CST all along. The defect was the BOUND:
    revenue/profit MTD ran to month END, v4 is refreshed intraday, so today's
    partial loads crept into Proj. Revenue / Proj. Profit while `pending` also
    projected today as a full day. Measured 10-20 09:11 CST: 24 of today's
    loads already in v4.
  * "how it arrives at that 'AVG last 14 days' figure ... It should count
    Saturday and Sunday as one day by adding both amounts together." — Sunday
    rows were dropped from the 12-day sums, and `pending` (Mon-Sat) never
    projects a Sunday either, so Sunday production was in neither leg
    (10-06..10-19: 51 loads / $109,195 / $19,919).

Offline tests pin the bounds and the SQL shape; the `test_live_*` ones replay
against real gold and are skipped unless ``SAVINGS_DATABASE_URL`` is set.
"""

from __future__ import annotations

import asyncio
import inspect
import os
import re
import types
from datetime import date, timedelta

import pytest

from app.routers.ops_portal_overview import projection as proj_mod
from app.routers.ops_portal_overview._metrics import (
    _projection_anchor,
    _projection_bounds,
    _projection_params,
    _projection_sums_sql,
    _team_projection_core,
)
from app.routers.ops_portal_overview._scope import CORP_SCOPE, DFW_SCOPE, sub_team_expr
from app.routers.ops_portal_overview._sql import _v4_scope_where
from app.services import projection_history as ph

_NO_FILTERS = {
    "team": None, "customer": None, "load_type": None, "lanes": None,
    "exclude_lanes": None, "carriers": None, "exclude_carriers": None,
}


def _bound_dates(params: list) -> list[date]:
    """The plain ``date`` params — the scope predicate binds lists, never dates."""
    return [p for p in params if isinstance(p, date)]


# ---------------------------------------------------------------------------
# Close of the previous day — nothing measured may reach today
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("today", [
    date(2026, 10, 20),  # Tue — the request's day
    date(2026, 10, 19),  # Mon — yesterday is a Sunday
    date(2026, 10, 18),  # Sun — today is the weekend's second day
    date(2026, 10, 31),  # Sat — month end
    date(2026, 11, 1),   # Sun AND the 1st — no earlier day in the month
])
def test_every_projection_bound_closes_at_yesterday(today: date) -> None:
    """No bound may reach today or beyond — the drift was exactly that.

    "Yesterday" is the day before the ANCHOR: on a Sunday that is Friday,
    because the weekend slot (Sat + Sun) is still open.
    """
    _, params, _, pending = _projection_params(
        *_NO_FILTERS.values(), today=today, scope=CORP_SCOPE,
    )
    dates = _bound_dates(params)
    assert len(dates) == 6
    anchor = _projection_anchor(today)
    yesterday = anchor - timedelta(days=1)
    # Upper bounds only — on the 1st the MTD LOWER bound is today (empty range).
    assert max(dates[1::2]) < today
    win_start, _win_end, m_start, m_end, _ = _projection_bounds(today)
    # The six slots, in `_projection_sums_sql` order: window, vol MTD, rev/prof MTD.
    # Every UPPER bound is yesterday. On the 1st the MTD lower bound is today,
    # so `BETWEEN today AND yesterday` is empty — nothing measured, all projected.
    assert dates == [win_start, yesterday, m_start, yesterday, m_start, yesterday]
    assert dates[1::2] == [yesterday] * 3
    # The day in progress is PROJECTED: pending counts Mon-Sat from the anchor.
    assert pending == sum(
        1 for i in range((m_end - anchor).days + 1)
        if (anchor + timedelta(days=i)).weekday() < 6
    )


def test_a_sunday_shows_saturdays_panel() -> None:
    """Sat + Sun are ONE slot, so the whole weekend reads the same projection.

    Anchored on Sunday itself, the window would close at Saturday WITHOUT its
    Sunday: every Sunday's 02:45 snapshot dips by ~Sunday/12 — a weekly
    sawtooth and a fake Low in the stored history.
    """
    sat, sun = date(2026, 10, 17), date(2026, 10, 18)
    assert _projection_anchor(sun) == sat
    assert _projection_bounds(sun) == _projection_bounds(sat)
    for d in (date(2026, 10, 19), date(2026, 10, 20), sat):
        assert _projection_anchor(d) == d


def test_a_sunday_first_of_the_month_never_borrows_last_months_saturday() -> None:
    """2026-11-01 is a Sunday; its Saturday is October — wrong month."""
    nov1 = date(2026, 11, 1)
    assert _projection_anchor(nov1) == nov1
    _, _, m_start, m_end, pending = _projection_bounds(nov1)
    assert (m_start, m_end) == (date(2026, 11, 1), date(2026, 11, 30))
    assert pending == 25


def test_mtd_display_rows_and_projection_share_one_bound() -> None:
    """Volume/Revenue/Profit (MTD) on screen must be the legs the Proj. rows use.

    Before 10-20 only Volume was reconstructable (`avg × pending + MTD`);
    Revenue and Profit were not, because their legs ran to month end.
    """
    from app.routers.ops_portal_overview._metrics import _mtd_display_params

    today = date(2026, 10, 20)
    _, d_params, _, _ = _mtd_display_params(*_NO_FILTERS.values(), today=today)
    _, p_params, _, _ = _projection_params(*_NO_FILTERS.values(), today=today)
    d = _bound_dates(d_params)
    p = _bound_dates(p_params)
    assert d == [p[2], p[3]] == [p[4], p[5]]


def test_the_window_is_twelve_mon_sat_slots_spanning_fourteen_days() -> None:
    """The label says "last 14 days"; the divisor is 12 — both are true."""
    # Every day of a fortnight except a Sunday 1st — Sundays included now.
    days = [date(2026, 10, 12) + timedelta(days=i) for i in range(14)]
    for today in days:
        win_start, win_end, *_ = _projection_bounds(today)
        span = [win_start + timedelta(days=i) for i in range((win_end - win_start).days + 1)]
        assert sum(1 for d in span if d.weekday() < 6) == 12
        assert len(span) == 14, (today, win_start, win_end)
        assert win_start.weekday() != 6, "a window never starts on a Sunday"


# ---------------------------------------------------------------------------
# A weekend is one day — Sunday rows are summed, never filtered
# ---------------------------------------------------------------------------


def test_the_projection_sums_carry_no_sunday_predicate() -> None:
    params: list = []
    where = _v4_scope_where("br4", None, None, None, params)
    for scope in (CORP_SCOPE, DFW_SCOPE):
        sql = _projection_sums_sql(where, 1, 2, 3, 4, 5, 6, scope=scope)
        assert "EXTRACT(DOW" not in sql, "Sunday must fold into its weekend slot"
        sql_g = _projection_sums_sql(where, 1, 2, 3, 4, 5, 6, group_col="br4.customer_name")
        assert "EXTRACT(DOW" not in sql_g


class _StubPool:
    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple]] = []

    async def fetch(self, sql, *params):
        self.calls.append((sql, params))
        return []

    async def fetchrow(self, sql, *params):
        self.calls.append((sql, params))


def _drive_by_team(today: date, scope=None) -> _StubPool:
    """Call /team-projection-by-team with its FastAPI defaults resolved."""
    pool = _StubPool()
    state = types.SimpleNamespace()
    if scope is not None:
        state.opp_scope = scope
    fn = proj_mod.team_projection_by_team
    kwargs = {}
    for name, p in inspect.signature(fn).parameters.items():
        if name == "request":
            kwargs[name] = types.SimpleNamespace(
                app=types.SimpleNamespace(state=types.SimpleNamespace()),
                state=state,
            )
        elif name == "_user":
            kwargs[name] = {}
        else:
            kwargs[name] = getattr(p.default, "default", p.default)
    orig_pool, orig_today = proj_mod.get_datalake_gold_pool, proj_mod.cst_today
    proj_mod.get_datalake_gold_pool = lambda request: pool
    proj_mod.cst_today = lambda: today
    try:
        asyncio.run(fn(**kwargs))
    finally:
        proj_mod.get_datalake_gold_pool, proj_mod.cst_today = orig_pool, orig_today
    return pool


@pytest.mark.parametrize("today", [date(2026, 10, 20), date(2026, 10, 18)])
def test_the_by_team_breakout_uses_the_same_window_and_bounds(today: date) -> None:
    """The Team modal is a hand-written copy of the sums — it must not drift."""
    pool = _drive_by_team(today)
    assert len(pool.calls) == 1
    sql, params = pool.calls[0]
    assert "EXTRACT(DOW" not in sql
    _, live_params, _, _ = _projection_params(*_NO_FILTERS.values(), today=today)
    assert _bound_dates(list(params)) == _bound_dates(live_params)


def test_the_by_team_breakout_groups_on_the_scopes_team_column() -> None:
    """Under DFW `team_id` is the constant 'TEAM-DFW' (§77).

    Grouping on it returned one 'TEAM-DFW' row that matched none of TM1..TM5,
    so the DFW Team modal of Monthly Projection showed every team at zero.
    """
    for scope in (CORP_SCOPE, DFW_SCOPE):
        # DFW: the sub-team column, TM4 for a revenue-code-DFW CORP row.
        col = sub_team_expr(scope, "br4", scope.v4_team_col)
        pool = _drive_by_team(date(2026, 10, 20), scope=scope)
        sql = pool.calls[0][0]
        assert f"TRIM({col}) AS team_id" in sql
        assert f"GROUP BY TRIM({col})" in sql
    assert "br4.team END" in sub_team_expr(DFW_SCOPE, "br4", DFW_SCOPE.v4_team_col)


# ---------------------------------------------------------------------------
# Live replay against real gold — opt-in, the suite stays offline
# ---------------------------------------------------------------------------

_GOLD = os.environ.get("SAVINGS_DATABASE_URL")
live = pytest.mark.skipif(not _GOLD, reason="SAVINGS_DATABASE_URL not set — offline run")

# Sun, Mon, Tue, Sat, the 1st (a Thursday), the 2nd, a month-end Saturday and a
# Sunday 1st — every shape the window and the MTD legs can take.
_AS_OF = (
    date(2026, 10, 18), date(2026, 10, 19), date(2026, 10, 20), date(2026, 10, 17),
    date(2026, 10, 1), date(2026, 10, 2), date(2026, 1, 31), date(2026, 3, 1),
    date(2026, 9, 1),
)


async def _gold_pool():
    import asyncpg

    url = re.sub(r"[?&]sslmode=\w+", "", _GOLD or "")
    return await asyncpg.create_pool(url, ssl="require", min_size=1, max_size=2)


async def _per_day(pool, scope, start: date, end: date) -> dict[date, tuple]:
    params: list = []
    where = _v4_scope_where("br4", None, None, None, params, scope=scope)
    params.extend([start, end])
    n = len(params)
    rows = await pool.fetch(
        f"""
        SELECT br4.origin_actual_departure::date AS d,
               COUNT(*) FILTER (WHERE br4.total_charge IS NOT NULL
                                  AND br4.total_charge <> 0) AS vol,
               COALESCE(SUM(br4.total_charge), 0)::numeric AS rev,
               COALESCE(SUM(br4.margin_amt), 0)::numeric AS prof
          FROM public.mcleod_gld_budget_report_v4 br4
         WHERE {where}
           AND br4.origin_actual_departure::date BETWEEN ${n - 1} AND ${n}
         GROUP BY 1
        """,
        *params,
    )
    return {r["d"]: (r["vol"], float(r["rev"]), float(r["prof"])) for r in rows}


@live
def test_live_panel_equals_a_hand_reference_built_from_daily_sums() -> None:
    """Avg = (14 calendar days, Sundays INCLUDED) / 12; MTD = month start → yesterday."""

    async def run():
        pool = await _gold_pool()
        try:
            for today in _AS_OF:
                ws, we, ms, _me, pending = _projection_bounds(today)
                days = await _per_day(pool, CORP_SCOPE, min(ws, ms), we)
                win = [v for d, v in days.items() if ws <= d <= we]
                mtd = [v for d, v in days.items() if ms <= d <= we]
                got = await _team_projection_core(pool, **_NO_FILTERS, today=today,
                                                  with_mtd_display=True)
                avg_rev = sum(v[1] for v in win) / 12
                assert got["avg_vol_day"] == pytest.approx(sum(v[0] for v in win) / 12)
                assert got["avg_rev_day"] == pytest.approx(avg_rev, abs=0.01)
                assert got["avg_prof_day"] == pytest.approx(sum(v[2] for v in win) / 12, abs=0.01)
                assert got["proj_revenue"] == pytest.approx(
                    avg_rev * pending + sum(v[1] for v in mtd), abs=0.05), today
                # Reconstructable on screen: Avg × Pending + (MTD), all three.
                for avg, mtd_key, proj in (
                    ("avg_vol_day", "mtd_volume", "proj_volume"),
                    ("avg_rev_day", "mtd_revenue", "proj_revenue"),
                    ("avg_prof_day", "mtd_profit", "proj_profit"),
                ):
                    assert got[proj] == pytest.approx(
                        got[avg] * got["pending_workdays"] + got[mtd_key], abs=0.05
                    ), (today, proj)
        finally:
            await pool.close()

    asyncio.run(run())


@live
def test_live_replay_matches_the_live_panel_for_every_day_shape() -> None:
    """The stored history must be the panel's number, not a cousin of it (§69)."""

    async def run():
        pool = await _gold_pool()
        try:
            for scope_key, team_key, scope, team_ids in ph.SNAPSHOT_SCOPES:
                if team_key != ph.ALL_TEAMS:
                    continue
                replay = await ph._replay_scope(
                    pool, scope=scope, team_ids=team_ids,
                    start=date(2026, 1, 1), end=date(2026, 10, 20),
                )
                by_day = {r["as_of_date"]: r for r in replay}
                for today in _AS_OF:
                    want = await _team_projection_core(
                        pool, **_NO_FILTERS, today=today, scope=scope,
                    )
                    got = by_day[today]
                    for k in ("avg_vol_day", "avg_rev_day", "avg_prof_day",
                              "proj_volume", "proj_revenue", "proj_profit",
                              "pending_workdays", "team_count"):
                        assert got[k] == pytest.approx(want[k], abs=0.01), (
                            scope_key, today, k, got[k], want[k])
        finally:
            await pool.close()

    asyncio.run(run())
