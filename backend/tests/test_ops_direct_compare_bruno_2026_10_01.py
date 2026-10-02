"""OPs Direct Compare — Bruno PDF "BRUNO -- DIRECT COMPARE UPDATES" (2026-10-01).

The four "(1)/(2) Details by …" tables became two combined tables (Details by
Customer, Details by Lane) carrying BOTH panels + P1 − P2 diffs, plus a new
Customer → Lane pivot; the "last 12 months" chart became a Jan–Dec previous-
year-vs-current-year chart (/trend-yoy).

What these tests exist to stop:

* the Diff sign drifting back to the 2026-04 tables' P2 − P1 (the new spec is
  "Panel 1 − Panel 2" on every Diff column, same as the Differential card);
* a client-supplied sort key reaching ORDER BY unvetted;
* the Totals row describing ONE PAGE instead of the population (§109) —
  Details by Lane has ~3.6k lanes YTD, so it really is paged;
* a pivot parent that does not equal the sum of its lanes;
* a per-team clone (corp-tN-direct-compare) leaking another team through a
  crafted ``?p1_division=DFW`` / ``?p2_teams=TEAM2`` on the NEW endpoints, or
  500ing on a param it forgot to forward (§40);
* the removed endpoints quietly coming back.

Three layers, cheapest first (same as test_kam_under5_loads.py):

1. emitted-SQL linters over a stub pool,
2. unit contracts (sort whitelist, YoY series, pivot nesting),
3. ``test_live_*`` — run against real gold and RECONCILE the three tables with
   the KPI cards and each other. Skipped unless ``SAVINGS_DATABASE_URL`` is
   set, so the suite stays offline.
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import types
from datetime import date, datetime

import pytest
from fastapi import HTTPException

from app.routers import ops_direct_compare as odc
from app.routers import ops_direct_compare_team as odct
from app.datalake import pad_variants


class _StubPool:
    """⚠ Records the SQL. A stub pool cannot see a WHERE — the live layer
    below is what proves the numbers."""

    def __init__(self, rows=None):
        self.sqls: list[str] = []
        self.params: list[tuple] = []
        self._rows = rows or []

    async def fetch(self, sql, *params):
        self.sqls.append(sql)
        self.params.append(params)
        return self._rows

    async def fetchrow(self, sql, *params):
        self.sqls.append(sql)
        self.params.append(params)
        return None


_REQ = types.SimpleNamespace(app=types.SimpleNamespace(state=types.SimpleNamespace()))

_PANELS = dict(
    p1_range="mtd", p1_start_date=None, p1_end_date=None,
    p1_division=None, p1_teams=None, p1_sub_teams=None,
    p2_range="last_month", p2_start_date=None, p2_end_date=None,
    p2_division=None, p2_teams=None, p2_sub_teams=None,
)
_PAGING = dict(sort=odc.DEFAULT_SORT, page=1, limit=200, _user={"sub": "u"})

_COMPARE_ENDPOINTS = ("by_customer_diff", "by_lane_diff", "by_customer_lane_diff")


def _drive(fn_name: str, pool=None, **overrides):
    pool = pool or _StubPool()
    orig = odc.get_datalake_gold_pool
    odc.get_datalake_gold_pool = lambda request: pool
    try:
        call = {**_PANELS, **_PAGING, **overrides}
        resp = asyncio.run(getattr(odc, fn_name)(request=_REQ, **call))
    finally:
        odc.get_datalake_gold_pool = orig
    return pool, resp


def _strip_comments(sql: str) -> str:
    return "\n".join(l for l in sql.split("\n") if not l.strip().startswith("--"))


# ---------------------------------------------------------------------------
# 1. Emitted SQL
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("fn", _COMPARE_ENDPOINTS)
def test_every_diff_is_panel1_minus_panel2(fn):
    """🔴 Bruno 2026-10-01 spells "Panel 1 − Panel 2" for every Diff column.
    The 2026-04 tables printed P2 − P1 — one flipped line would silently
    invert every Diff on the page."""
    sql = _strip_comments(_drive(fn)[0].sqls[0])
    for m in ("loads", "revenue", "profit"):
        assert re.search(rf"\.p1_{m} - \w+\.p2_{m} AS diff_{m}", sql), m
        assert not re.search(rf"\.p2_{m} - \w+\.p1_{m}", sql), m
    assert re.search(r"\) - \(CASE WHEN \w+\.p2_revenue <> 0.*AS diff_margin", sql)
    assert re.search(r"\) - \(CASE WHEN \w+\.p2_load_ids > 0.*AS diff_avg_p", sql)


@pytest.mark.parametrize("fn", _COMPARE_ENDPOINTS)
def test_two_panels_two_scans_one_statement(fn):
    """Both panels in ONE statement, v4 scanned once per panel — the pivot's
    customer rows are summed from the lane grain, never re-queried."""
    pool = _drive(fn)[0]
    assert len(pool.sqls) == 1
    assert pool.sqls[0].count("FROM public.mcleod_gld_budget_report_v4") == 2
    assert "FULL OUTER JOIN" in pool.sqls[0]


@pytest.mark.parametrize("fn,src", [
    ("by_customer_diff", "merged"),
    ("by_lane_diff", "merged"),
    ("by_customer_lane_diff", "merged_c"),
])
def test_totals_are_over_the_population_not_the_page(fn, src):
    """§109: the Totals row sums the merged population; paging is applied to
    `ranked`, which the totals never read."""
    sql = _strip_comments(_drive(fn)[0].sqls[0])
    m = re.search(r"tot AS \((.+?)\),\n", sql, re.S)
    assert m, "tot CTE not found"
    assert m.group(1).rstrip().endswith(f"FROM {src}")
    assert "ranked" not in m.group(1) and "pg" not in m.group(1).split()


def test_pivot_joins_on_both_keys():
    """A composite grain joins on ALL its columns — on customer alone it fans
    every lane out against every other lane of the customer."""
    sql = _drive("by_customer_lane_diff")[0].sqls[0]
    assert "ON d1.customer = d2.customer AND d1.lane = d2.lane" in sql


def test_lane_key_is_never_null():
    """A NULL lane would not match itself in the FULL JOIN and print twice."""
    assert odc._DIM_EXPR["lane"].startswith("COALESCE(")
    assert odc.NO_LANE in odc._DIM_EXPR["lane"]


def test_compare_metrics_match_panel_summary_definitions():
    """Same definitions as the KPI cards, or the Totals row and the cards
    disagree: loads/revenue skip zero-charge rows, profit sums ALL rows."""
    g = odc._grouped_select("TRUE", ("customer",))
    assert "COUNT(*) FILTER (WHERE br4.total_charge <> 0) AS loads" in g
    assert "COALESCE(SUM(br4.margin_amt), 0)::numeric AS profit" in g
    assert "SUM(br4.margin_amt) FILTER" not in g


def test_trend_yoy_bounds_the_raw_column():
    """Convert the param, not the column: no cast on origin_actual_departure,
    and gold is already CST — no AT TIME ZONE."""
    odc._trend_cache.clear()
    pool = _StubPool()
    orig = odc.get_datalake_gold_pool
    odc.get_datalake_gold_pool = lambda request: pool
    try:
        asyncio.run(odc.trend_yoy(request=_REQ, _user={}))
    finally:
        odc.get_datalake_gold_pool = orig
        odc._trend_cache.clear()
    sql = pool.sqls[0]
    assert "origin_actual_departure::date" not in sql
    assert "AT TIME ZONE" not in sql
    start, end = pool.params[0][-2:]
    assert isinstance(start, datetime) and isinstance(end, datetime)
    today = odc.cst_today()
    assert start == datetime(today.year - 1, 1, 1)
    assert end.date() > today


# ---------------------------------------------------------------------------
# 2. Unit contracts
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("col", odc.SORT_COLUMNS)
@pytest.mark.parametrize("d", ("asc", "desc"))
def test_every_table_column_sorts(col, d):
    order, c = odc._order_by(f"{col}_{d}", "customer")
    assert c == col and order.startswith(f"{col} {d.upper()} NULLS LAST")


def test_the_whitelist_covers_all_15_metric_columns():
    assert len(odc.SORT_COLUMNS) == 15
    for m in ("loads", "revenue", "profit", "margin", "avg_p"):
        for side in ("p1", "p2", "diff"):
            assert f"{side}_{m}" in odc.SORT_COLUMNS


@pytest.mark.parametrize("bad", [
    "profit_desc",               # the 2026-04 single-panel key
    "p1_profit",                 # no direction
    "p1_profit_up",
    "p1_profit; DROP TABLE x_desc",
    "lane_asc",                  # wrong name column for the customer table
])
def test_unknown_sort_is_a_400(bad):
    with pytest.raises(HTTPException) as e:
        odc._order_by(bad, "customer")
    assert e.value.status_code == 400


def test_the_name_column_sorts_on_its_own_table():
    assert odc._order_by("lane_asc", "lane") == ("lane ASC", "lane")


def test_yoy_series_is_always_twelve_months():
    today = date(2026, 10, 1)
    rows = [{"yr": 2025, "mo": m, "revenue": 100.0, "profit": 10.0} for m in range(1, 13)]
    rows += [{"yr": 2026, "mo": m, "revenue": 200.0, "profit": 30.0} for m in range(1, 11)]
    s = odc._yoy_series(rows, today)
    assert (s["prev_year"], s["cur_year"]) == (2025, 2026)
    assert [m["label"] for m in s["months"]] == list(odc.MONTH_LABELS)
    assert all(m["prev"] for m in s["months"])
    assert [m["month"] for m in s["months"] if m["cur"] is None] == [11, 12]
    assert s["months"][0]["cur"]["margin_pct"] == pytest.approx(15.0)
    assert s["months"][0]["prev"]["margin_pct"] == pytest.approx(10.0)


def test_yoy_month_without_revenue_has_no_margin():
    s = odc._yoy_series([{"yr": 2025, "mo": 3, "revenue": 0, "profit": 5}], date(2026, 1, 5))
    assert s["months"][2]["prev"]["margin_pct"] is None
    assert s["months"][0]["prev"] is None  # no row → no bar, never a fake $0


def _j(**kw):
    base = {f"{p}_{b}": 0 for p in ("p1", "p2") for b in odc._BASES}
    base.update({k: None for k in ("p1_margin", "p2_margin", "p1_avg_p", "p2_avg_p",
                                   "diff_margin", "diff_avg_p")})
    base.update({"diff_loads": 0, "diff_revenue": 0, "diff_profit": 0})
    base.update(kw)
    return json.dumps(base)


def test_pivot_nests_lanes_under_their_customer():
    rows = [
        {"lvl": 2, "rn": 0, "sub_rn": 0, "j": _j(n_rows=2, p1_profit=30)},
        {"lvl": 0, "rn": 1, "sub_rn": 0, "j": _j(customer="A", lane_count=2, p1_profit=20)},
        {"lvl": 1, "rn": 1, "sub_rn": 1, "j": _j(customer="A", lane="X", p1_profit=15)},
        {"lvl": 1, "rn": 1, "sub_rn": 2, "j": _j(customer="A", lane="Y", p1_profit=5)},
        {"lvl": 0, "rn": 2, "sub_rn": 0, "j": _j(customer="B", lane_count=1, p1_profit=10)},
        {"lvl": 1, "rn": 2, "sub_rn": 1, "j": _j(customer="B", lane="Z", p1_profit=10)},
    ]
    _, resp = _drive("by_customer_lane_diff", pool=_StubPool(rows))
    data = resp["data"]
    assert [c["customer"] for c in data] == ["A", "B"]
    assert [l["lane"] for l in data[0]["lanes"]] == ["X", "Y"]
    assert data[0]["lane_count"] == 2
    assert resp["meta"]["total"] == 2
    assert resp["meta"]["totals"]["p1"]["profit"] == 30


def test_flat_table_envelope_carries_both_panels_and_diff():
    rows = [
        {"lvl": 2, "rn": 0, "j": _j(n_rows=1)},
        {"lvl": 0, "rn": 1, "j": _j(customer="A", p1_loads=3, p2_loads=1, diff_loads=2,
                                     p1_margin=10.0, p2_margin=None, diff_margin=None)},
    ]
    _, resp = _drive("by_customer_diff", pool=_StubPool(rows))
    row = resp["data"][0]
    assert set(row) == {"customer", "p1", "p2", "diff"}
    assert row["diff"]["loads"] == 2
    assert row["p1"]["margin_pct"] == 10.0 and row["diff"]["margin_pct"] is None
    assert resp["meta"]["sort"] == odc.DEFAULT_SORT


def test_removed_endpoints_stay_removed():
    paths = {r.path for r in odc.router.routes}
    for gone in ("by-customer", "by-lane", "trend-12m", "customer-revenue-margin",
                 "orders-window"):
        assert f"/custom/ops-direct-compare/{gone}" not in paths
    for kept in ("by-customer-diff", "by-lane-diff", "by-customer-lane-diff", "trend-yoy",
                 "panel-summary", "concentration", "filters", "freshness"):
        assert f"/custom/ops-direct-compare/{kept}" in paths


# ---------------------------------------------------------------------------
# Per-team clones — the lock must hold on the new endpoints too
# ---------------------------------------------------------------------------


def _team_endpoint(router, path_tail):
    for r in router.routes:
        if r.path.endswith(path_tail):
            return r.endpoint
    raise AssertionError(f"{path_tail} missing")


def test_every_team_router_mirrors_the_parent_routes():
    parent = {r.path.split("/")[-1] for r in odc.router.routes}
    for tr in odct.team_routers:
        assert {r.path.split("/")[-1] for r in tr.routes} == parent


@pytest.mark.parametrize("tail", ["/by-customer-diff", "/by-lane-diff", "/by-customer-lane-diff"])
def test_team_clone_locks_both_panels(tail):
    """A TEAM1 KAM crafting ?p1_division=DFW&p2_teams=TEAM2 still sees TEAM1
    only — and every param is forwarded, so nothing arrives as a FieldInfo."""
    router = odct.team_routers[0]
    team = odct.TEAM_CONFIGS[0][0]
    pool = _StubPool()
    orig = odc.get_datalake_gold_pool
    odc.get_datalake_gold_pool = lambda request: pool
    try:
        hostile = {**_PANELS, "p1_division": "DFW", "p1_teams": "TEAM-DFW",
                   "p2_division": "All", "p2_teams": "TEAM2", "p2_sub_teams": "TM1"}
        asyncio.run(_team_endpoint(router, tail)(request=_REQ, **hostile, **_PAGING))
    finally:
        odc.get_datalake_gold_pool = orig
    team_lists = [p for p in pool.params[0] if isinstance(p, list)]
    mine = set(pad_variants((team,), width=8))
    others = set(pad_variants(("TEAM2", "TEAM-DFW"), width=8))
    assert any(set(p) & mine for p in team_lists)
    assert not any(set(p) & others for p in team_lists)


def test_team_trend_is_scoped_to_the_team():
    router = odct.team_routers[1]
    team = odct.TEAM_CONFIGS[1][0]
    odc._trend_cache.clear()
    pool = _StubPool()
    orig = odc.get_datalake_gold_pool
    odc.get_datalake_gold_pool = lambda request: pool
    try:
        asyncio.run(_team_endpoint(router, "/trend-yoy")(request=_REQ, _user={}))
    finally:
        odc.get_datalake_gold_pool = orig
        odc._trend_cache.clear()
    team_lists = [p for p in pool.params[0] if isinstance(p, list)]
    assert any(set(p) & set(pad_variants((team,), width=8)) for p in team_lists)
    assert not any(set(p) & set(pad_variants(("TEAM1",), width=8)) for p in team_lists)


# ---------------------------------------------------------------------------
# 3. Live — reconcile against real gold
# ---------------------------------------------------------------------------

_GOLD = os.environ.get("SAVINGS_DATABASE_URL", "")
live = pytest.mark.skipif(not _GOLD, reason="SAVINGS_DATABASE_URL not set")


class _LivePool:
    """Runs each statement on a fresh connection (each endpoint call is its
    own asyncio.run)."""

    async def _conn(self):
        import asyncpg
        url = re.sub(r"[?&]sslmode=\w+", "", _GOLD)
        conn = await asyncpg.connect(url, ssl="require")
        await conn.execute("SET statement_timeout = '60s'")
        return conn

    async def fetch(self, sql, *params):
        conn = await self._conn()
        try:
            return await conn.fetch(sql, *params)
        finally:
            await conn.close()

    async def fetchrow(self, sql, *params):
        conn = await self._conn()
        try:
            return await conn.fetchrow(sql, *params)
        finally:
            await conn.close()


_LIVE_PANELS = {**_PANELS, "p1_range": "ytd", "p2_range": "last_month"}


def _live(fn, **kw):
    return _drive(fn, pool=_LivePool(), **{**_LIVE_PANELS, **kw})[1]


def _summary(prefix):
    pool = _LivePool()
    orig = odc.get_datalake_gold_pool
    odc.get_datalake_gold_pool = lambda request: pool
    try:
        return asyncio.run(odc.panel_summary(
            request=_REQ, range=_LIVE_PANELS[f"{prefix}_range"], start_date=None,
            end_date=None, division=None, teams=None, sub_teams=None, _user={},
        ))["data"]
    finally:
        odc.get_datalake_gold_pool = orig


@live
def test_live_all_three_tables_reconcile_with_the_kpi_cards():
    cust = _live("by_customer_diff")["meta"]["totals"]
    lane = _live("by_lane_diff")["meta"]["totals"]
    piv = _live("by_customer_lane_diff")["meta"]["totals"]
    for p in ("p1", "p2"):
        card = _summary(p)
        for t in (cust, lane, piv):
            assert t[p]["loads"] == card["loads"]
            assert t[p]["revenue"] == pytest.approx(card["revenue"], abs=0.01)
            assert t[p]["profit"] == pytest.approx(card["profit"], abs=0.01)
            assert t[p]["margin_pct"] == pytest.approx(card["margin_pct"], abs=1e-6)
        assert cust["diff"]["profit"] == pytest.approx(
            cust["p1"]["profit"] - cust["p2"]["profit"], abs=0.01)


@live
def test_live_every_pivot_parent_is_the_sum_of_its_lanes():
    resp = _live("by_customer_lane_diff", sort="p1_revenue_desc")
    assert resp["data"], "no customers YTD?"
    for c in resp["data"]:
        assert len(c["lanes"]) == c["lane_count"]
        for p in ("p1", "p2"):
            for m in ("loads", "revenue", "profit"):
                assert c[p][m] == pytest.approx(sum(l[p][m] for l in c["lanes"]), abs=0.01)
    revs = [c["p1"]["revenue"] for c in resp["data"]]
    assert revs == sorted(revs, reverse=True)


@live
def test_live_lane_table_pages_without_losing_rows():
    first = _live("by_lane_diff", limit=50)
    second = _live("by_lane_diff", limit=50, page=2)
    assert first["meta"]["total"] > 50
    assert len(first["data"]) == 50
    assert not {r["lane"] for r in first["data"]} & {r["lane"] for r in second["data"]}


@live
def test_live_trend_yoy_current_year_equals_the_ytd_card():
    odc._trend_cache.clear()
    pool = _LivePool()
    orig = odc.get_datalake_gold_pool
    odc.get_datalake_gold_pool = lambda request: pool
    try:
        s = asyncio.run(odc.trend_yoy(request=_REQ, _user={}))["data"]
    finally:
        odc.get_datalake_gold_pool = orig
        odc._trend_cache.clear()
    ytd = _summary("p1")
    cur = [m["cur"] for m in s["months"] if m["cur"]]
    assert sum(c["revenue"] for c in cur) == pytest.approx(ytd["revenue"], abs=0.01)
    assert sum(c["profit"] for c in cur) == pytest.approx(ytd["profit"], abs=0.01)
    assert all(m["prev"] for m in s["months"]), "previous year should have 12 months"


# ---------------------------------------------------------------------------
# Frontend source guards (no JS test runner — frontend/CLAUDE.md)
# ---------------------------------------------------------------------------

_FE = os.path.join(os.path.dirname(__file__), "..", "..", "frontend")


def _read(rel: str) -> str:
    with open(os.path.join(_FE, rel), encoding="utf-8") as fh:
        return fh.read()


def test_fe_the_page_no_longer_renders_the_removed_sections():
    """R9 + R6/R7: the profit-only trend, the combo, the orders table and the
    four (1)/(2) tables are gone — from the page AND from disk."""
    src = _read("components/DirectCompareContent.tsx")
    for gone in ("Trend12m", "CustomerRevMarginCombo", "OrdersTable",
                 "CustomerTable", "LaneTable", "(1) Details by", "(2) Details by"):
        assert gone not in src, gone
    for kept in ('title="Details by Customer"', 'title="Details by Lane"',
                 "CustomerLanePivot", "<TrendYoY"):
        assert kept in src, kept
    sections = os.path.join(_FE, "app/reports/ops-direct-compare/sections")
    for f in ("Trend12m", "CustomerRevMarginCombo", "OrdersTable", "CustomerTable", "LaneTable"):
        assert not os.path.exists(os.path.join(sections, f + ".tsx")), f


def test_fe_column_ids_are_exactly_the_backend_sort_whitelist():
    """Every header click sends its column id as `sort`; one id the backend
    does not know is a 400 on click."""
    src = _read("app/reports/ops-direct-compare/sections/compareColumns.tsx")
    metrics = re.findall(r'\{ key: "(\w+)", label: "[^"]+", diffLabel: "[^"]+" \}', src)
    assert metrics == ["loads", "revenue", "profit", "margin", "avg_p"]  # Bruno's order
    assert {f"{s}_{m}" for m in metrics for s in ("p1", "p2", "diff")} == set(odc.SORT_COLUMNS)
    assert f'DC_DEFAULT_SORT = "{odc.DEFAULT_SORT}"' in _read("lib/ops-direct-compare-api.ts")


def test_fe_cards_say_differential_and_name_their_period():
    src = _read("app/reports/ops-direct-compare/KpiCards.tsx")
    assert 'title: "Differential"' in src
    assert 'title: "Δ' not in src
    page = _read("components/DirectCompareContent.tsx")
    assert page.count("period={period1}") == 1 and page.count("period={period2}") == 1
