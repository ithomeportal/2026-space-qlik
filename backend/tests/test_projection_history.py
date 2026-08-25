"""Team Monthly Projection history — the defects this feature can ship with.

Request 2026-08-25 (`Pictures/space-projected profit.txt`): show Proj. Profit
"as the stock markets" — the current month's HIGH, LOW and % variation — track
that variation by month to expose the error rate, and keep the weekly values
for ever.

Each test below pins ONE way this can be wrong in a way nobody would notice:

  * a replay overwriting an observed row, so the history quietly becomes a
    recomputation of itself;
  * a replay summing the WHOLE month instead of stopping at the as-of date, so
    every historical "projection" contains the answer and the error rate reads
    far better than it is;
  * a High printed BELOW the Proj. Profit figure on the line above it (§16);
  * the first days of a month — near-pure extrapolation — silently setting the
    range that people are asked to manage by;
  * a team selection we do not track being answered with a neighbouring
    scope's range instead of "not tracked";
  * a missing delegator, which is a 404 on five of the six portals (§74).
"""

from __future__ import annotations

import inspect
from datetime import date

import pytest

from app.routers import ops_portal_overview as opo
from app.routers import ops_portal_overview_dfw as dfw
from app.routers import ops_portal_overview_team as team_mod
from app.routers.ops_portal_overview._metrics import _projection_from_sums
from app.routers.ops_portal_overview._scope import CORP_SCOPE, DFW_SCOPE
from app.routers.ops_portal_overview._sql import _v4_scope_where
from app.services import projection_history as ph


# ---------------------------------------------------------------------------
# The upsert precedence — a replay must never rewrite what was observed
# ---------------------------------------------------------------------------


def test_a_backfill_can_never_overwrite_a_live_row() -> None:
    """`DO NOTHING` for a replay, `DO UPDATE` for the daily job.

    Get this backwards and the whole distinction collapses: every restart would
    relabel the observed series as a recomputation of itself, and the "what did
    we actually see" question becomes unanswerable — permanently, because the
    original values are gone.
    """
    backfill = ph._upsert_sql(overwrite=False)
    live = ph._upsert_sql(overwrite=True)
    assert "ON CONFLICT (scope_key, team_key, as_of_date) DO NOTHING" in backfill
    assert "DO UPDATE SET" in live
    assert "DO NOTHING" not in live
    # The key columns must never appear in the SET list — updating a PK column
    # to itself is noise at best and a silent no-op guard at worst.
    set_clause = live.split("DO UPDATE SET", 1)[1]
    for key in ("scope_key = EXCLUDED", "team_key = EXCLUDED", "as_of_date = EXCLUDED"):
        assert key not in set_clause


def test_the_weekly_upsert_is_do_update_because_a_week_keeps_moving() -> None:
    """Loads post late; a frozen first write would keep the wrong figure."""
    assert "DO UPDATE SET" in ph._week_upsert_sql()


def test_every_projection_field_is_persisted() -> None:
    """A column added to the panel but not to the table is invisible for ever.

    The stored row must carry the full `_projection_from_sums` output, not just
    profit — otherwise the day a Revenue high/low is asked for, the history
    starts from zero again.
    """
    produced = set(_projection_from_sums(1, 1, 1, 1, 1, 1, 1, 1))
    stored = set(ph._PROJ_FIELDS) | {"pending_workdays", "team_count"}
    assert produced == stored, f"not persisted: {sorted(produced - stored)}"


# ---------------------------------------------------------------------------
# The replay clamp — the trap that makes history look flattering
# ---------------------------------------------------------------------------


def test_the_replay_stops_the_mtd_leg_at_the_as_of_date() -> None:
    """`rev/prof_mtd` must be cumulative TO the as-of day, not to month end.

    The live query binds the leg as `BETWEEN month_start AND month_END`, which
    is harmless today (no rows exist past today) and catastrophic in a replay:
    an as-of date inside a closed month would sum the entire month, so the
    "projection" would contain the outcome and every error figure would be
    near-zero — a graph that says the forecast is perfect.
    """
    params: list = []
    where = _v4_scope_where("br4", None, None, None, params,
                            None, None, None, None, scope=CORP_SCOPE)
    n = len(params) + 3
    sql = ph._replay_sums_sql(where, n - 2, n - 1, n)

    # The month-to-date CTE is joined on the AS-OF row, never on month end.
    assert "LEFT JOIN mtd mc ON mc.d = a.d" in sql
    assert "m_end" not in sql
    # ...and the volume leg keeps the documented one-day lag.
    assert "LEFT JOIN mtd mp ON mp.d = a.d - 1" in sql


def test_the_replay_excludes_sundays_before_the_rolling_window() -> None:
    """"Last 12 business days" is 12 Mon-Sat days, not 12 calendar rows.

    Filtering after the window would silently make it ~10 business days.
    """
    params: list = []
    where = _v4_scope_where("br4", None, None, None, params,
                            None, None, None, None, scope=CORP_SCOPE)
    sql = ph._replay_sums_sql(where, 1, 2, 3)
    window_cte = sql.split("bdays AS (", 1)[1].split("mtd AS (", 1)[0]
    assert "WHERE EXTRACT(DOW FROM d) <> 0" in window_cte
    assert "ROWS BETWEEN 11 PRECEDING AND CURRENT ROW" in window_cte
    # A partial lookback must not produce a point at all.
    assert "n_12 = 12" in sql


def test_the_replay_skips_months_with_no_volume() -> None:
    """A division that did not exist yet must not plant a $0 LOW for ever."""
    params: list = []
    where = _v4_scope_where("br4", None, None, None, params,
                            None, None, None, None, scope=CORP_SCOPE)
    sql = ph._replay_sums_sql(where, 1, 2, 3)
    assert "HAVING SUM(vol) > 0" in sql
    assert "JOIN live_months lm" in sql


def test_the_capacity_denominator_uses_the_scope_team_column() -> None:
    """`proj_team_ut` is volume / (500 x team_count).

    Counting `team_id` under DFW returns 1 (it is the constant 'TEAM-DFW'), so
    utilisation would come out five times the panel's. §77.
    """
    for scope, col in ((CORP_SCOPE, "team_id"), (DFW_SCOPE, "team")):
        params: list = []
        where = _v4_scope_where("br4", None, None, None, params,
                                None, None, None, None, scope=scope)
        assert f"COUNT(DISTINCT br4.{col})" in ph._team_count_sql(where, scope)


# ---------------------------------------------------------------------------
# §16 — the strip must never contradict the number printed above it
# ---------------------------------------------------------------------------


def _pt(day: int, value: float, source: str = "backfill") -> dict:
    return {
        "as_of_date": date(2026, 8, day),
        "proj_profit": value,
        "proj_revenue": 0.0, "proj_volume": 0.0, "proj_margin_pct": 0.0,
        "pending_workdays": 0, "source": source,
    }


def test_the_live_value_is_folded_into_the_high() -> None:
    """The snapshot is taken at 02:45; by 16:00 the live figure has moved.

    Without the fold-in the panel prints "High $520,000" directly under a
    Proj. Profit of $560,000 — the reader's first thought is that the number is
    broken, and they are right.
    """
    pts = [_pt(20, 500_000.0), _pt(25, 510_000.0)]
    stats = ph.current_month_stats(pts, live_value=560_000.0, today=date(2026, 8, 25))
    assert stats["high"] == 560_000.0
    assert stats["high_date"] == date(2026, 8, 25)
    assert stats["latest"] == 560_000.0


def test_the_live_value_is_folded_into_the_low_too() -> None:
    pts = [_pt(20, 500_000.0), _pt(25, 510_000.0)]
    stats = ph.current_month_stats(pts, live_value=410_000.0, today=date(2026, 8, 25))
    assert stats["low"] == 410_000.0
    assert stats["low_date"] == date(2026, 8, 25)


def test_todays_stored_row_is_replaced_not_added() -> None:
    """The stored row is today's OPENING value; the live one supersedes it.

    Keeping both would let a single day contribute two points, and the "days"
    count — which the e-mail uses to decide whether a range is meaningful at
    all — would over-report.
    """
    pts = [_pt(24, 500_000.0), _pt(25, 505_000.0)]
    stats = ph.current_month_stats(pts, live_value=520_000.0, today=date(2026, 8, 25))
    assert stats["days"] == 2
    assert [p["as_of_date"].day for p in stats["points"]] == [24, 25]
    assert stats["points"][-1]["proj_profit"] == 520_000.0
    # The day-over-day move compares against the 24th, not against the
    # superseded 25th — otherwise "vs yesterday" silently means "vs 02:45".
    assert stats["prev"] == 500_000.0
    assert stats["chg_pct"] == pytest.approx(4.0)


def test_a_high_can_never_come_out_below_the_live_value() -> None:
    """The property, stated directly — this is the whole point of the fold-in."""
    pts = [_pt(d, 400_000.0 + d * 1000) for d in range(1, 25)]
    for live in (0.0, 350_000.0, 424_000.0, 999_999.0):
        stats = ph.current_month_stats(pts, live_value=live, today=date(2026, 8, 25))
        assert stats["high"] >= live
        assert stats["low"] <= live


def test_no_stored_history_still_reports_the_live_value() -> None:
    """Day one after deploy: one point, no range — but never a crash."""
    stats = ph.current_month_stats([], live_value=500_000.0, today=date(2026, 8, 25))
    assert stats["high"] == stats["low"] == 500_000.0
    assert stats["days"] == 1
    assert stats["range_pct"] == 0.0
    assert stats["chg_pct"] is None


# ---------------------------------------------------------------------------
# The early-month distortion
# ---------------------------------------------------------------------------


def test_the_settled_range_excludes_the_opening_days() -> None:
    """Measured: January 2026 opened at $115,707 against a $303,575 outcome.

    On day 1 the month-to-date leg is ~0 and every dollar is extrapolated, so
    the raw range is dominated by days nobody would act on. The settled range
    starts at business day 5 and is published beside the raw one — not instead
    of it, because the raw one is what the panel actually showed.
    """
    pts = [_pt(1, 115_707.0), _pt(2, 140_000.0), _pt(3, 160_000.0)]
    pts += [_pt(d, 300_000.0 + (d % 3) * 1000) for d in range(6, 26)]
    stats = ph.current_month_stats(pts, live_value=302_000.0, today=date(2026, 8, 26))

    assert stats["low"] == 115_707.0, "the raw low is still the truth"
    assert stats["settled_low"] >= 300_000.0, "the settled low skips the opening days"
    assert stats["settled_range_pct"] < stats["range_pct"]
    assert stats["settled_from_business_day"] == ph.SETTLED_FROM_BUSINESS_DAY


def test_business_day_of_month_counts_mon_to_sat() -> None:
    """Sundays are not business days — the divisor everywhere in this report."""
    # 2026-08-01 is a Saturday; 08-02 a Sunday; 08-03 a Monday.
    assert ph._business_day_of_month(date(2026, 8, 1)) == 1
    assert ph._business_day_of_month(date(2026, 8, 2)) == 1, "Sunday adds nothing"
    assert ph._business_day_of_month(date(2026, 8, 3)) == 2


# ---------------------------------------------------------------------------
# Scope resolution — "not tracked" must not become "someone else's range"
# ---------------------------------------------------------------------------


def test_the_tracked_scopes_cover_every_portal() -> None:
    keys = {(s, t) for s, t, _, _ in ph.SNAPSHOT_SCOPES}
    assert ("corp", "ALL") in keys, "the base Ops Portal Overview"
    for t in ("TEAM1", "TEAM2", "TEAM3", "TEAM4"):
        assert ("corp", t) in keys, "the four scope-locked CORP clones"
    assert ("corp", "DIGEST") in keys, "the PERFORMANCE CORP e-mail (TEAM1..4)"
    assert ("dfw", "ALL") in keys, "the Ops Managers Portal DFW"
    for t in DFW_SCOPE.sub_teams:
        assert ("dfw", t) in keys, "the DFW sub-team pills"


def test_the_digest_scope_is_four_teams_not_five() -> None:
    """TEAM5 is dormant, so a five-team series would be indistinguishable.

    The e-mail's own scope is TEAM1..TEAM4; storing history under a different
    population would make its High/Low disagree with its headline by an amount
    too small to notice and too real to ignore.
    """
    from app.services.team_perf_digest import DIGEST_CORP_TEAMS

    assert ph.DIGEST_CORP_TEAMS == DIGEST_CORP_TEAMS
    assert "TEAM5" not in ph.DIGEST_CORP_TEAMS
    assert len(ph.DIGEST_CORP_TEAMS) == 4


def test_resolve_history_key_maps_the_scopes_we_store() -> None:
    assert ph.resolve_history_key(CORP_SCOPE, []) == ph.ALL_TEAMS
    assert ph.resolve_history_key(CORP_SCOPE, ["TEAM3"]) == "TEAM3"
    assert ph.resolve_history_key(CORP_SCOPE, ["team3"]) == "TEAM3", "case-insensitive"
    assert ph.resolve_history_key(CORP_SCOPE, list(ph.DIGEST_CORP_TEAMS)) == ph.DIGEST_KEY
    assert ph.resolve_history_key(DFW_SCOPE, ["TM2"]) == "TM2"


def test_an_untracked_selection_returns_none_rather_than_a_neighbour() -> None:
    """Two teams selected is not "the division", and not "TEAM1" either.

    Falling back to either would attach a High/Low to a number it does not
    describe — the §16 defect, arrived at from the other direction.
    """
    assert ph.resolve_history_key(CORP_SCOPE, ["TEAM1", "TEAM2"]) is None
    assert ph.resolve_history_key(CORP_SCOPE, ["TEAM1", "TEAM2", "TEAM3"]) is None
    assert ph.resolve_history_key(DFW_SCOPE, ["TEAM1"]) is None, "wrong division"
    assert ph.resolve_history_key(CORP_SCOPE, ["TM1"]) is None, "wrong division"


# ---------------------------------------------------------------------------
# §74 — a missing delegator is a 404 on five of the six portals
# ---------------------------------------------------------------------------


def _paths(router) -> set[str]:
    return {r.path for r in router.routes}


def test_every_portal_serves_team_projection_history() -> None:
    """All six pages render the SAME OpsPortalOverviewContent.

    The base router having the endpoint proves nothing about the five copies —
    that is exactly how the `_team` / `_dfw` delegators became mandatory.
    """
    assert any(p.endswith("/team-projection-history") for p in _paths(opo.router))
    assert any(p.endswith("/team-projection-history") for p in _paths(dfw.r))
    assert len(team_mod.team_routers) == 4
    for r in team_mod.team_routers:
        assert any(p.endswith("/team-projection-history") for p in _paths(r)), (
            f"{r.prefix} would 404 on the projection ticker"
        )


def test_the_clone_delegators_cannot_widen_their_scope() -> None:
    """A locked clone must not accept `team` or `teams` from the client.

    Either one would let a TEAM1 user read TEAM3's projection history (§7.1).
    """
    for r in team_mod.team_routers:
        route = next(x for x in r.routes if x.path.endswith("/team-projection-history"))
        params = inspect.signature(route.endpoint).parameters
        assert "team" not in params, f"{r.prefix} exposes `team`"
        assert "teams" not in params, f"{r.prefix} exposes `teams`"


def test_the_dfw_delegator_maps_the_sub_team_pills() -> None:
    """DFW's team column is `team` (TM1..TM5), not `team_id` — §77."""
    route = next(x for x in dfw.r.routes if x.path.endswith("/team-projection-history"))
    src = inspect.getsource(route.endpoint)
    assert "_sub_team(team)" in src, "the pill value must go through the DFW mapper"
    assert "teams=None" in src, "a DFW page must not carry a CORP multi-team scope"


def test_the_history_endpoint_declares_every_filter_its_siblings_do() -> None:
    """FastAPI silently DROPS a query parameter an endpoint does not declare.

    The page sends one filter object to every panel; an endpoint missing
    `carriers` would answer as if no carrier filter were applied — and here
    that would mean showing a range while claiming it is unfiltered.
    """
    hist = next(x for x in opo.router.routes
                if x.path.endswith("/team-projection-history"))
    proj = next(x for x in opo.router.routes if x.path.endswith("/team-projection"))
    missing = set(inspect.signature(proj.endpoint).parameters) - set(
        inspect.signature(hist.endpoint).parameters
    )
    assert not missing, f"/team-projection-history drops {sorted(missing)}"


# ---------------------------------------------------------------------------
# The scheduler roster — a job that is never registered never runs
# ---------------------------------------------------------------------------


def test_the_snapshot_job_is_on_the_startup_roster() -> None:
    """A firing cron is not a working cron, and an unregistered one is silent.

    The roster log is the only thing that turns "job absent" into an ERROR, so
    a new job that is not listed there fails exactly the way the fleet's two
    dead crons did.
    """
    import pathlib

    src = pathlib.Path(inspect.getfile(__import__("app.main", fromlist=["x"]))).read_text()
    assert '"daily_projection_snapshot"' in src
    roster = src.split("EXPECTED_JOBS = {", 1)[1].split("}", 1)[0]
    assert "daily_projection_snapshot" in roster, (
        "the job is scheduled but absent from EXPECTED_JOBS — its absence "
        "would never be reported"
    )
    # ...and it must run before the 05:28 CST n8n digest that prints its output.
    assert "hour=2, minute=45" in src


# ---------------------------------------------------------------------------
# Percent-change convention
# ---------------------------------------------------------------------------


def test_pct_change_uses_abs_of_the_baseline() -> None:
    """A negative baseline must still give the intuitive sign.

    Same convention as `team_perf_digest._pct_change` — a projection CAN be
    negative, and a month that goes from -$50k to -$25k improved.
    """
    assert ph._pct_change(110.0, 100.0) == pytest.approx(10.0)
    assert ph._pct_change(-25.0, -50.0) == pytest.approx(50.0)
    assert ph._pct_change(10.0, 0.0) is None


def test_attach_actuals_signs_the_error() -> None:
    """Signed, so a standing over-forecast is visible instead of averaged away."""
    months = [
        {"month_start": date(2026, 7, 1), "close": 500_000.0, "high": 556_008.0, "low": 399_161.0},
        {"month_start": date(2026, 6, 1), "close": 430_000.0, "high": 458_415.0, "low": 378_640.0},
    ]
    out = ph.attach_actuals(months, {date(2026, 7, 1): 453_495.0, date(2026, 6, 1): 439_285.0})
    assert out[0]["error_pct"] == pytest.approx(10.25, abs=0.01), "over-forecast is positive"
    assert out[1]["error_pct"] == pytest.approx(-2.11, abs=0.01), "under-forecast is negative"


def test_attach_actuals_leaves_an_unknown_month_as_none() -> None:
    """An absent actual must render as an em dash, never as a 0% error."""
    months = [{"month_start": date(2026, 7, 1), "close": 500_000.0, "high": 1.0, "low": 1.0}]
    out = ph.attach_actuals(months, {})
    assert out[0]["actual_profit"] is None
    assert out[0]["error_pct"] is None


# ---------------------------------------------------------------------------
# The import cycle — green in one direction, broken in the other
# ---------------------------------------------------------------------------


def test_the_service_imports_standalone() -> None:
    """`import app.services.projection_history` FIRST must work.

    The router package's `__init__` is a façade that imports `.projection`
    (§28), and importing any submodule runs it — so a module-level import of
    this service from `projection.py` closes a cycle that only fails when the
    service is imported first. Every existing test imports the router package
    first, so it shipped green and would have broken the scheduler job and any
    standalone script. Run in a child process because the parent's `sys.modules`
    already holds both.
    """
    import subprocess
    import sys

    r = subprocess.run(
        [sys.executable, "-c", "import app.services.projection_history"],
        capture_output=True, text=True,
    )
    assert r.returncode == 0, r.stderr[-600:]


def test_the_ddl_and_upserts_are_parseable_statements() -> None:
    """Cheap structural guard on the statements no endpoint emits.

    They run once, at startup, inside a `try` that logs and continues — so a
    syntax error there produces a warning nobody reads and a table that never
    exists, and the feature is simply blank for ever.
    """
    stmts = {
        "projection_ddl": ph.PROJECTION_HISTORY_DDL,
        "projection_index": ph.PROJECTION_HISTORY_INDEX_DDL,
        "weekly_ddl": ph.WEEKLY_ACTUALS_DDL,
        "upsert_backfill": ph._upsert_sql(overwrite=False),
        "upsert_live": ph._upsert_sql(overwrite=True),
        "week_upsert": ph._week_upsert_sql(),
    }
    for label, sql in stmts.items():
        assert sql.count("(") == sql.count(")"), f"{label}: unbalanced parentheses"
        for bad in ("None", "True", "False", "[", "]"):
            assert bad not in sql, f"{label}: a Python literal reached the SQL"

    # Placeholder count must equal the column count, in both upsert flavours —
    # asyncpg reports a mismatch only at execution time, inside the scheduler.
    for label, cols in (("projection", ph._UPSERT_COLS), ("weekly", ph._WEEK_COLS)):
        sql = ph._upsert_sql(overwrite=True) if label == "projection" else ph._week_upsert_sql()
        values = sql.split("VALUES (", 1)[1].split(")", 1)[0]
        assert values.count("$") == len(cols), f"{label}: {values.count('$')} != {len(cols)}"
        assert f"${len(cols)}" in values and f"${len(cols) + 1}" not in values


def test_the_stored_row_matches_the_column_list() -> None:
    """`_row_values` builds a positional tuple — a drift is a silent shift.

    Columns are all NUMERIC/INTEGER, so a mis-ordered value does not raise; it
    writes revenue into the volume column and nobody finds out.
    """
    proj = _projection_from_sums(120, 240_000, 36_000, 300, 600_000, 90_000, 6, 5)
    rec = {"as_of_date": date(2026, 8, 25), "month_start": date(2026, 8, 1), **proj}
    values = ph._row_values("corp", "ALL", "live", rec)
    assert len(values) == len(ph._UPSERT_COLS)
    by_name = dict(zip(ph._UPSERT_COLS, values))
    assert by_name["scope_key"] == "corp"
    assert by_name["team_key"] == "ALL"
    assert by_name["source"] == "live"
    assert by_name["as_of_date"] == date(2026, 8, 25)
    assert by_name["pending_workdays"] == 6
    for field in ph._PROJ_FIELDS:
        assert by_name[field] == pytest.approx(proj[field]), f"{field} landed in the wrong column"


# ---------------------------------------------------------------------------
# The endpoint, end to end over stub pools
# ---------------------------------------------------------------------------


class _HubStub:
    """Serves a fixed month of stored points; everything else empty."""

    def __init__(self, points: list[tuple[date, float, str]]) -> None:
        self._points = points

    async def fetch(self, sql, *params):
        if "FROM ops_projection_history" in sql and "ORDER BY as_of_date" in sql:
            return [
                {
                    "as_of_date": d, "proj_profit": v, "proj_revenue": 0,
                    "proj_volume": 0, "proj_margin_pct": 0,
                    "pending_workdays": 0, "source": src,
                }
                for d, v, src in self._points
            ]
        return []

    async def fetchrow(self, sql, *params):
        return None

    async def fetchval(self, sql, *params):
        return None


class _GoldStub:
    """Returns the six raw sums, so the LIVE projection is a real number.

    Returning None here makes `_team_projection_core` yield $0 — which the
    fold-in then correctly adopts as the month's LOW. That is the endpoint
    behaving properly on an empty scope, so a fixture that leaves it at None
    is testing the fold-in with the answer already decided.
    """

    def __init__(self, prof_12: float = 240_000.0, prof_mtd: float = 407_038.0) -> None:
        self._row = {
            "vol_12": 720, "rev_12": 1_400_000.0, "prof_12": prof_12,
            "vol_mtd": 1_200, "rev_mtd": 2_396_351.0, "prof_mtd": prof_mtd,
            "team_count": 5,
        }

    async def fetch(self, sql, *params):
        return []

    async def fetchrow(self, sql, *params):
        return self._row

    async def fetchval(self, sql, *params):
        return None


def _call(*, hub, gold, **kwargs):
    import asyncio
    import types

    from app.routers.ops_portal_overview import projection as proj_mod

    # ⚠ The clock is frozen. `pending_workdays` is derived from today, so a
    # live-clock test would assert a different projection every day and go red
    # on its own on the 1st of a month.
    orig_gold = proj_mod.get_datalake_gold_pool
    orig_hub = proj_mod.get_pool
    orig_today = proj_mod.cst_today
    proj_mod.get_datalake_gold_pool = lambda request: gold
    proj_mod.get_pool = lambda request: hub
    proj_mod.cst_today = lambda: date(2026, 8, 25)
    try:
        request = types.SimpleNamespace(
            state=types.SimpleNamespace(),
            app=types.SimpleNamespace(state=types.SimpleNamespace()),
            query_params={},
        )
        base = dict(
            team=None, teams=None, customer=None, load_type=None, lanes=None,
            exclude_lanes=None, carriers=None, exclude_carriers=None, months=13,
        )
        base.update(kwargs)
        return asyncio.run(
            proj_mod.team_projection_history(request=request, _user={}, **base)
        )["data"]
    finally:
        proj_mod.get_datalake_gold_pool = orig_gold
        proj_mod.get_pool = orig_hub
        proj_mod.cst_today = orig_today


def test_the_endpoint_reports_the_month_high_low_and_range() -> None:
    pts = [
        (date(2026, 8, 2), 405_981.0, "backfill"),
        (date(2026, 8, 20), 542_601.0, "backfill"),
        (date(2026, 8, 24), 534_995.0, "backfill"),
    ]
    d = _call(hub=_HubStub(pts), gold=_GoldStub())
    assert d["tracked"] is True
    # 2026-08-25 leaves 6 Mon-Sat days: 240,000/12 x 6 + 407,038 = 527,038.
    assert d["live_proj_profit"] == pytest.approx(527_038.0)
    assert d["team_key"] == "ALL"
    assert d["scope_key"] == "corp"
    cur = d["current_month"]
    assert cur["high"] == 542_601.0
    assert cur["low"] == 405_981.0
    assert cur["high_date"] == "2026-08-20"
    assert cur["range_pct"] == pytest.approx(33.65, abs=0.01)
    # Today's live point is appended, so the series is 4 days, not 3.
    assert cur["days"] == 4
    assert cur["latest"] == pytest.approx(527_038.0)
    # Dates must leave as ISO strings — a `date` object is not JSON-serialisable
    # and FastAPI would 500 on the whole panel.
    assert all(isinstance(p["as_of_date"], str) for p in cur["points"])


def test_the_endpoint_refuses_to_answer_for_a_filtered_panel() -> None:
    """History is unfiltered; a range beside a filtered number would be a lie.

    Every filter must trip it — not just the obvious one.
    """
    pts = [(date(2026, 8, 2), 405_981.0, "backfill"), (date(2026, 8, 20), 542_601.0, "backfill")]
    for kwargs in (
        {"customer": "KOHLER CO MONTERREY"},
        {"load_type": "contract"},
        {"lanes": ["A - B"]},
        {"exclude_lanes": ["A - B"]},
        {"carriers": ["CARRIER X"]},
        {"exclude_carriers": ["CARRIER X"]},
    ):
        d = _call(hub=_HubStub(pts), gold=_GoldStub(), **kwargs)
        assert d["tracked"] is False, f"{kwargs} did not disable the strip"
        assert d["untracked_reason"] == "filtered"
        assert d["current_month"] is None
        # ...but the live figure is still published, so the caller can show the
        # panel itself without a second round trip.
        assert "live_proj_profit" in d


def test_the_endpoint_refuses_an_untracked_team_selection() -> None:
    pts = [(date(2026, 8, 2), 1.0, "backfill")]
    d = _call(hub=_HubStub(pts), gold=_GoldStub(), teams="TEAM1,TEAM2")
    assert d["tracked"] is False
    assert d["untracked_reason"] == "team_scope"
    assert d["team_key"] is None


def test_the_endpoint_maps_the_four_team_digest_scope() -> None:
    """`teams=TEAM1,TEAM2,TEAM3,TEAM4` is the PERFORMANCE CORP e-mail scope."""
    pts = [(date(2026, 8, 2), 1.0, "backfill"), (date(2026, 8, 3), 2.0, "backfill")]
    d = _call(hub=_HubStub(pts), gold=_GoldStub(), teams="TEAM1,TEAM2,TEAM3,TEAM4")
    assert d["tracked"] is True
    assert d["team_key"] == ph.DIGEST_KEY
