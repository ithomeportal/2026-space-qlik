"""KPI MANAGEMENT chart — Bruno PDF 2026-10-16 "Ops Portal Updates" R1.

Three changes, pinned at the level each can break:

  (a) a **Customers** measure: DISTINCT customers per bucket over the Vol.
      population (§96) plus ``new_customers`` — present in a bucket, absent from
      the IMMEDIATELY previous one. Computed in the SAME v4 scan as the bars
      (a 2nd scan timed out once — memory feedback_derived_count_same_scan),
      and the scan starts ONE bucket early so the first visible bar is not
      100 % new.
  (b) **Projected candlesticks**: per-bucket OHLC from ``ops_projection_history``
      — month = proj_<m>, week = avg_<m>_day × 6 (× 7 until 2026-10-20), day = avg_<m>_day, margin never
      scaled; live value folded into today (§84); filtered / untracked ⇒ none.
  (c) the **Variance** legend entry is a static label, not a toggle.

There is no JS test runner in this repo, so (c) reads the TSX (frontend
CLAUDE.md §107 convention). The live test at the bottom proves the SQL rule
against the pure-Python statement of it on real gold; it is skipped offline.
"""

from __future__ import annotations

import asyncio
import os
import re
from datetime import date, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.routers import ops_portal_overview as opo
from app.routers.ops_portal_overview import _combo_extras as cx
from app.routers.ops_portal_overview import chart as chart_mod
from app.routers.ops_portal_overview._dates import _resolve_grain_window
from app.routers.ops_portal_overview._scope import CORP_SCOPE, DFW_SCOPE

TODAY = date(2026, 10, 16)  # a Friday
USER = {"sub": "probe", "email": "probe@example.com", "roles": ["admin"]}
FRONT = Path(__file__).resolve().parents[2] / "frontend" / "app" / "reports" / "ops-portal-overview"

NO_FILTERS = dict(
    team=None, customer=None, load_type=None, lanes=None,
    exclude_lanes=None, carriers=None, exclude_carriers=None,
)


# ---------------------------------------------------------------------------
# Harness
# ---------------------------------------------------------------------------


class _Pool:
    """Records every statement; answers the ones a test scripts by marker."""

    def __init__(self, answers: dict[str, list] | None = None) -> None:
        self.calls: list[tuple[str, tuple]] = []
        self.answers = answers or {}

    async def fetch(self, sql, *params):
        self.calls.append((sql, params))
        for marker, rows in self.answers.items():
            if marker in sql:
                return rows
        return []

    async def fetchrow(self, sql, *params):
        self.calls.append((sql, params))
        return None

    async def fetchval(self, sql, *params):
        self.calls.append((sql, params))
        return None


def _request(gold, hub, scope=None):
    state = SimpleNamespace()
    if scope is not None:
        state.opp_scope = scope
    return SimpleNamespace(
        app=SimpleNamespace(state=SimpleNamespace(savings_pool=gold, pool=hub)),
        state=state, headers={}, query_params={},
    )


def _run_combo(monkeypatch, *, grain="month", gold=None, hub=None, scope=None, **filters):
    monkeypatch.setattr(chart_mod, "cst_today", lambda: TODAY)
    gold = gold or _Pool()
    hub = hub or _Pool()
    kw = {**NO_FILTERS, **filters}
    res = asyncio.run(opo.combo(request=_request(gold, hub, scope), grain=grain, _user=USER, **kw))
    return res["data"], gold, hub


def _prod(gold) -> tuple[str, tuple]:
    stmts = [(s, p) for s, p in gold.calls if "per_cust" in s]
    assert len(stmts) == 1, f"expected ONE production statement, got {len(stmts)}"
    return stmts[0]


# ---------------------------------------------------------------------------
# (a) Customers — SQL shape
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("grain", ["day", "week", "month"])
def test_customers_come_from_the_same_single_scan_as_the_bars(monkeypatch, grain):
    _, gold, _ = _run_combo(monkeypatch, grain=grain)
    sql, _ = _prod(gold)
    assert sql.count("mcleod_gld_budget_report_v4") == 1, "customers must not re-scan v4"
    assert "MATERIALIZED" not in sql.upper()
    # Each CTE referenced exactly once ⇒ Postgres inlines it (one scan).
    for cte in ("per_cust", "flagged"):
        refs = len(re.findall(rf"\b{cte}\b", sql))
        assert refs == 2, f"{cte} defined+referenced {refs} times — would materialise"
    for col in ("AS volume", "AS customers", "AS new_customers", "AS losses_prof"):
        assert col in sql


def test_customers_span_the_volume_population():
    """§96: a customer is counted only where Vol. counts a load for it."""
    sql = cx.combo_production_sql("month", "x::date", "TRUE", 1, 2)
    flat = re.sub(r"\s+", " ", sql)
    assert re.search(
        r"COUNT\(\*\) FILTER \(WHERE br4\.total_charge IS NOT NULL AND br4\.total_charge <> 0\) AS volume", flat
    )
    assert "(pc.volume > 0 AND pc.cust IS NOT NULL) AS present" in flat
    assert "COUNT(*) FILTER (WHERE present) AS customers" in flat
    # the LAG skips buckets where the customer had no COUNTED load
    assert "PARTITION BY pc.cust, (pc.volume > 0)" in flat


@pytest.mark.parametrize("grain,expr", [
    ("day", "RANGE BETWEEN UNBOUNDED PRECEDING AND INTERVAL '1 day' PRECEDING)"),
    ("week", "(pc.bucket_start - 7)"),
    ("month", "(pc.bucket_start - INTERVAL '1 month')::date"),
])
def test_new_means_absent_from_the_IMMEDIATELY_previous_bucket(grain, expr):
    sql = cx.combo_production_sql(grain, "x::date", "TRUE", 1, 2)
    assert f"{expr} AS prev_bucket" in sql
    assert "prev_seen IS DISTINCT FROM prev_bucket" in sql


def test_production_sql_parens_balance_and_no_python_reprs():
    for grain in ("day", "week", "month"):
        sql = cx.combo_production_sql(grain, "x::date", "TRUE", 1, 2)
        body = re.sub(r"'(?:[^']|'')*'", "''", sql)
        assert body.count("(") == body.count(")"), grain
        assert not re.search(r"\bNone\b|\[|\]", body), grain


@pytest.mark.parametrize("grain", ["day", "week", "month"])
def test_scan_starts_one_bucket_before_the_window_and_still_ends_today(monkeypatch, grain):
    _, gold, _ = _run_combo(monkeypatch, grain=grain)
    sql, params = _prod(gold)
    _, win_end, anchors = _resolve_grain_window(grain, TODAY)
    p_ws = int(re.search(r"origin_actual_departure >= \$(\d+)", sql).group(1))
    p_we = int(re.search(r"origin_actual_departure < \(\$(\d+)::date", sql).group(1))
    assert params[p_ws - 1] == cx.lookback_start(grain, anchors[0]) < anchors[0]
    assert params[p_we - 1] == win_end == TODAY


def test_previous_bucket_per_grain():
    assert cx.previous_bucket("day", date(2026, 3, 1)) == date(2026, 2, 28)
    assert cx.previous_bucket("week", date(2026, 10, 12)) == date(2026, 10, 5)
    assert cx.previous_bucket("month", date(2026, 1, 1)) == date(2025, 12, 1)
    assert cx.previous_bucket("month", date(2026, 3, 1)) == date(2026, 2, 1)


def test_day_grain_compares_with_the_previous_active_WEEKDAY():
    """Review 2026-10-16: with the calendar rule every Monday read ~100 % new,
    and with "previous active day" Monday still compared with a thin Sunday.
    Monday — and the weekend days themselves — compare with Friday."""
    thu, fri, sun = date(2026, 10, 8), date(2026, 10, 9), date(2026, 10, 11)
    mon, tue = date(2026, 10, 12), date(2026, 10, 13)
    presence = {thu: {"A"}, fri: {"A", "B"}, sun: {"E"}, mon: {"A", "B", "C"}, tue: {"C", "D"}}
    got = cx.new_customers_reference(presence, "day")
    assert got == {thu: 0, fri: 1, sun: 1, mon: 1, tue: 1}
    sql = cx.combo_production_sql("day", "x::date", "TRUE", 1, 2)
    assert "FILTER (WHERE pc.volume > 0 AND EXTRACT(ISODOW FROM pc.bucket_start) < 6) OVER (" in sql
    for grain in ("week", "month"):
        assert "PRECEDING" not in cx.combo_production_sql(grain, "x::date", "TRUE", 1, 2)


def test_day_lookback_reaches_past_a_long_weekend():
    assert cx.lookback_start("day", date(2026, 10, 12)) == date(2026, 10, 5)
    assert cx.lookback_start("week", date(2026, 10, 12)) == date(2026, 10, 5)
    assert cx.lookback_start("month", date(2026, 3, 1)) == date(2026, 2, 1)


def test_new_customers_reference_rule():
    """Returning after a GAP is new; the earliest bucket has no history."""
    m = lambda d: date(2026, d, 1)  # noqa: E731
    presence = {m(1): {"A", "B"}, m(2): {"A", "C"}, m(4): {"A", "C"}, m(5): {"A", "B", "C"}}
    got = cx.new_customers_reference(presence, "month")
    assert got == {m(1): 2, m(2): 1, m(4): 2, m(5): 1}


# ---------------------------------------------------------------------------
# (a) Customers — payload
# ---------------------------------------------------------------------------


def test_payload_starts_at_the_window_and_drops_the_lookback_bucket(monkeypatch):
    _, _, anchors = _resolve_grain_window("month", TODAY)
    look = cx.previous_bucket("month", anchors[0])
    rows = [
        {"bucket_start": look, "volume": 9, "revenue": 1, "profit": 1, "losses_vol": 0,
         "losses_rev": 0, "losses_prof": 0, "customers": 7, "new_customers": 7},
        {"bucket_start": anchors[0], "volume": 10, "revenue": 100, "profit": 20, "losses_vol": 1,
         "losses_rev": 5, "losses_prof": -2, "customers": 8, "new_customers": 2},
    ]
    data, _, _ = _run_combo(monkeypatch, gold=_Pool({"per_cust": rows}))
    buckets = data["buckets"]
    assert len(buckets) == len(anchors)
    assert buckets[0]["bucket_start"] == anchors[0].isoformat()
    assert look.isoformat() not in {b["bucket_start"] for b in buckets}
    assert (buckets[0]["customers"], buckets[0]["new_customers"]) == (8, 2)
    assert buckets[0]["volume"] == 10 and buckets[0]["profit"] == 20.0
    assert (buckets[1]["customers"], buckets[1]["new_customers"]) == (0, 0)


# ---------------------------------------------------------------------------
# (b) Candles — pure aggregation
# ---------------------------------------------------------------------------


def _snap(d: date, prof: float, *, vol=100.0, rev=1000.0, margin=15.0,
          avg_vol=10.0, avg_rev=100.0, avg_prof=20.0) -> dict:
    return {
        "as_of_date": d, "proj_volume": vol, "proj_revenue": rev, "proj_profit": prof,
        "proj_margin_pct": margin, "avg_vol_day": avg_vol, "avg_rev_day": avg_rev,
        "avg_prof_day": avg_prof,
    }


def test_month_candle_is_open_first_close_last_high_max_low_min():
    rows = [_snap(date(2026, 9, d), p) for d, p in ((1, 300), (2, 500), (3, 200), (4, 400))]
    c = cx.aggregate_candles(rows, "month")[date(2026, 9, 1)]["profit"]
    assert (c["open"], c["high"], c["low"], c["close"], c["days"]) == (300, 500, 200, 400, 4)


def test_week_candle_scales_the_daily_average_by_7_and_never_scales_margin():
    mon = date(2026, 10, 12)
    rows = [
        _snap(mon, 0, avg_prof=10, margin=14.0),
        _snap(mon + timedelta(days=1), 0, avg_prof=30, margin=18.0),
        _snap(mon + timedelta(days=2), 0, avg_prof=20, margin=16.0),
    ]
    agg = cx.aggregate_candles(rows, "week")
    assert list(agg) == [mon], "a Mon-based week bucket, like DATE_TRUNC('week')"
    p = agg[mon]["profit"]
    assert (p["open"], p["high"], p["low"], p["close"]) == (60, 180, 60, 120)
    m = agg[mon]["margin_pct"]
    assert (m["open"], m["high"], m["low"], m["close"]) == (14.0, 18.0, 14.0, 16.0)
    # Six day-slots a week — Sat + Sun are ONE since 2026-10-20 (was 7).
    assert cx.WEEK_SCALE_DAYS == 6


def test_day_candle_is_degenerate_and_reads_the_daily_average():
    d = date(2026, 10, 14)
    c = cx.aggregate_candles([_snap(d, 999, avg_vol=12.5)], "day")[d]["volume"]
    assert c["open"] == c["high"] == c["low"] == c["close"] == 12.5


def test_month_candle_uses_the_month_end_projection_not_the_daily_average():
    d = date(2026, 10, 2)
    c = cx.aggregate_candles([_snap(d, 450_000, avg_prof=20)], "month")[date(2026, 10, 1)]["profit"]
    assert c["close"] == 450_000


def test_live_value_replaces_todays_row_and_bounds_the_candle():
    """§84 as a property: the current candle always contains the live value."""
    rows = [_snap(date(2026, 10, d), p) for d, p in ((1, 400_000), (2, 420_000), (16, 410_000))]
    for live in (0.0, 350_000.0, 415_000.0, 999_999.0):
        live_row = {k: v for k, v in _snap(TODAY, live).items() if k != "as_of_date"}
        got = cx.candles_for_anchors(rows, live_row, "month", [date(2026, 10, 1)], TODAY)
        c = got[date(2026, 10, 1)]["profit"]
        assert c["close"] == live and c["high"] >= live >= c["low"]
        assert c["days"] == 3, "today's stored row must be REPLACED, not appended"


def test_candles_outside_the_anchors_are_dropped():
    rows = [_snap(date(2024, 1, 5), 1), _snap(date(2026, 10, 1), 2)]
    got = cx.candles_for_anchors(rows, None, "month", [date(2026, 10, 1)], TODAY)
    assert list(got) == [date(2026, 10, 1)]


# ---------------------------------------------------------------------------
# (b) Candles — tracking through /combo
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("flt", [
    {"customer": "ACME"}, {"load_type": "spot"}, {"lanes": ["A - B"]},
    {"exclude_lanes": ["A - B"]}, {"carriers": ["X"]}, {"exclude_carriers": ["X"]},
])
def test_any_filter_means_untracked_and_no_history_read(monkeypatch, flt):
    data, _, hub = _run_combo(monkeypatch, **flt)
    assert data["projection_tracked"] is False
    assert data["projection_untracked_reason"] == "filtered"
    assert not any("ops_projection_history" in s for s, _ in hub.calls)
    assert all(b["projection"] is None for b in data["buckets"])


def test_a_team_selection_with_no_stored_series_is_untracked(monkeypatch):
    data, _, hub = _run_combo(monkeypatch, team="TEAM1,TEAM2")
    assert data["projection_untracked_reason"] == "team_scope"
    assert not hub.calls


@pytest.mark.parametrize("scope,team,key", [
    (None, None, ("corp", "ALL")),
    (None, "TEAM2", ("corp", "TEAM2")),
    (DFW_SCOPE, None, ("dfw", "ALL")),
])
def test_tracked_scope_reads_its_own_series_and_fills_the_buckets(monkeypatch, scope, team, key):
    snaps = [_snap(date(2026, 9, 3), 300_000), _snap(date(2026, 9, 20), 350_000)]
    data, _, hub = _run_combo(monkeypatch, scope=scope, team=team,
                              hub=_Pool({"ops_projection_history": snaps}))
    assert data["projection_tracked"] is True
    (sql, params), = [(s, p) for s, p in hub.calls if "ops_projection_history" in s]
    assert params[:2] == key
    _, _, anchors = _resolve_grain_window("month", TODAY)
    assert params[2:] == (anchors[0], TODAY)
    by = {b["bucket_start"]: b for b in data["buckets"]}
    sept = by["2026-09-01"]["projection"]["profit"]
    assert (sept["open"], sept["close"], sept["high"], sept["low"]) == (300_000, 350_000, 350_000, 300_000)
    # The stub projection core returns zeros ⇒ today's live candle is 0.
    assert by["2026-10-01"]["projection"]["profit"]["close"] == 0.0


def test_hub_failure_degrades_to_the_flat_line_not_a_500(monkeypatch):
    class _Broken(_Pool):
        async def fetch(self, sql, *params):
            raise RuntimeError("relation does not exist")

    data, _, _ = _run_combo(monkeypatch, hub=_Broken())
    assert data["projection_tracked"] is False
    assert data["projection_untracked_reason"] == "unavailable"
    assert len(data["buckets"]) == 26


def test_candle_tracking_matches_the_projection_history_endpoint():
    assert cx.candle_tracking(CORP_SCOPE, [], False) == ("ALL", None)
    assert cx.candle_tracking(CORP_SCOPE, ["TEAM1", "TEAM2", "TEAM3", "TEAM4"], False) == ("DIGEST", None)
    assert cx.candle_tracking(CORP_SCOPE, [], True) == (None, "filtered")


# ---------------------------------------------------------------------------
# (c) Variance legend is static; chart wiring
# ---------------------------------------------------------------------------


def _src(name: str) -> str:
    return (FRONT / name).read_text(encoding="utf-8")


def test_variance_legend_is_a_static_label_not_a_toggle():
    chart = _src("Chart.tsx")
    assert '<LegendLabel label="Variance"' in chart
    assert not re.search(r"<LegendChip\s[^>]*label=\"Variance\"", chart), "Variance is a toggle again"
    assert 'toggle("variance")' not in chart
    legend = _src("ChartLegend.tsx")
    m = re.search(r"export function LegendLabel[\s\S]*?\n}\n", legend)
    assert m, "LegendLabel not found"
    body = m.group(0)
    assert "onClick" not in body and "<button" not in body and "hover:" not in body
    # still budget-gated: no Variance on a budget-less (DFW) portal
    assert re.search(r"\{showBudget && <LegendLabel label=\"Variance\"", chart)


def test_chart_wires_customers_and_candles():
    chart = _src("Chart.tsx")
    assert '{ k: "customers",  label: "Customers", fmt: fmtCount }' in chart
    assert "showBudget = !hideBudget && !isCustomers" in chart
    assert "&& !isCustomers" in chart.split("const showLosses")[1].split("\n")[0]
    assert 'shape={renderCandle}' in chart and 'dataKey="proj_range"' in chart
    # the flat line is kept as the fallback
    assert "!hasCandles && !isHidden(\"projected\") && projected !== 0" in chart
    candle = _src("ProjectedCandle.tsx")
    assert "proj_range: c ? [c.low, c.high] : null" in candle
    assert "c.close >= c.open ? CANDLE_UP : CANDLE_DOWN" in candle


def test_chart_did_not_grow():
    assert len(_src("Chart.tsx").splitlines()) <= 991


# ---------------------------------------------------------------------------
# Live — the SQL rule against its pure-Python statement, on real gold
# ---------------------------------------------------------------------------

live = pytest.mark.skipif(not os.getenv("SAVINGS_DATABASE_URL"), reason="needs SAVINGS_DATABASE_URL")


@live
@pytest.mark.parametrize("grain", ["day", "week", "month"])
def test_live_new_customers_match_the_reference_rule(monkeypatch, grain):
    import asyncpg

    from app.clock import cst_today

    monkeypatch.setattr(chart_mod, "cst_today", cst_today)
    gold = _Pool()
    asyncio.run(opo.combo(request=_request(gold, _Pool()), grain=grain, _user=USER, **NO_FILTERS))
    sql, params = _prod(gold)
    # Re-derive presence from the per-customer CTE body itself, so the probe
    # and the statement cannot drift apart.
    inner = sql.split("WITH per_cust AS (", 1)[1].split("),\n        flagged AS", 1)[0]
    pairs_sql = f"SELECT bucket_start, cust FROM ({inner}) t WHERE volume > 0 AND cust IS NOT NULL"

    async def run():
        conn = await asyncpg.connect(os.environ["SAVINGS_DATABASE_URL"])
        try:
            return await conn.fetch(sql, *params), await conn.fetch(pairs_sql, *params)
        finally:
            await conn.close()

    rows, pairs = asyncio.run(run())
    presence: dict[date, set] = {}
    for r in pairs:
        presence.setdefault(r["bucket_start"], set()).add(r["cust"])
    ref = cx.new_customers_reference(presence, grain)
    first_anchor = _resolve_grain_window(grain, cst_today())[2][0]
    checked = 0
    for r in rows:
        if r["bucket_start"] < first_anchor:
            continue
        assert r["customers"] == len(presence.get(r["bucket_start"], ())), r["bucket_start"]
        assert r["new_customers"] == ref.get(r["bucket_start"], 0), r["bucket_start"]
        checked += 1
    assert checked >= 6
