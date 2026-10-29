"""Customer Lifespan (#69) — definitions, the nightly sync, the router, the 4-place mirror.

The maths tests pin hand-computed numbers on a 3-customer fixture. The sync tests
drive ``sync_from_datalake`` with stub pools that answer the EXPORTED statements
(never a paraphrase — cron-job-debug §1b). The live layer at the bottom EXPLAINs
the gold statements when ``SAVINGS_DATABASE_URL`` is set.
"""
from __future__ import annotations

import os
from datetime import date, datetime, timedelta
from pathlib import Path

import pytest
from fastapi import HTTPException

from app.routers import customer_lifespan as rt
from app.services import customer_lifespan_core as core
from app.services import customer_lifespan_store as store
from app.services import customer_lifespan_trends as tr
from tools import load_customer_lifespan_excel as loader

ROOT = Path(__file__).resolve().parents[2]
AS_OF = date(2024, 12, 31)
USER = {"sub": "t", "email": "t@local", "roles": ["admin"]}


def _m(cid, month, first, last, division="CORP", loads=1, revenue=1000.0, margin=100.0, name=None):
    return {"customer_id": cid, "month": month, "division": division, "loads": loads,
            "revenue": revenue, "margin": margin, "first_ship": first, "last_ship": last,
            "name": name or f"Cust {cid}"}


ROWS = [
    # A: Jan–Feb, silent 187 days, back in Aug, then quiet → lost (window 90)
    _m("A", date(2024, 1, 1), date(2024, 1, 5), date(2024, 1, 20), loads=2),
    _m("A", date(2024, 2, 1), date(2024, 2, 10), date(2024, 2, 10)),
    _m("A", date(2024, 8, 1), date(2024, 8, 15), date(2024, 8, 20), revenue=500.0, margin=-50.0),
    # B: Nov CORP, Dec CORP + DFW → active, two divisions
    _m("B", date(2024, 11, 1), date(2024, 11, 3), date(2024, 11, 28)),
    _m("B", date(2024, 12, 1), date(2024, 12, 2), date(2024, 12, 2)),
    _m("B", date(2024, 12, 1), date(2024, 12, 30), date(2024, 12, 30), division="DFW",
       name="Cust B renamed"),
    # C: one October load, 77 days quiet → at risk
    _m("C", date(2024, 10, 1), date(2024, 10, 15), date(2024, 10, 15), division="DFW"),
]


def _customers(division="all", window=90, as_of=AS_OF):
    return {c.customer_id: c for c in core.build_customers(core.merge_rows(ROWS, division), as_of, window)}


# ------------------------------------------------------------------ core


def test_lifespan_status_and_reactivations():
    cs = _customers()
    a, b, c = cs["A"], cs["B"], cs["C"]
    assert (a.lifespan_months, a.active_months, a.reactivations, a.status) == (7, 3, 1, "lost")
    assert a.days_since_last == 133 and a.loads == 4 and a.margin == 150.0
    assert (b.status, b.lifespan_months, b.divisions, b.name) == ("active", 1, ("CORP", "DFW"), "Cust B renamed")
    assert (c.status, c.lifespan_months, c.days_since_last) == ("at_risk", 0, 77)


def test_window_moves_status_not_lifespan():
    assert _customers(window=180)["A"].status == "at_risk"
    assert _customers(window=180)["A"].reactivations == 1          # 187-day gap still > 180
    assert _customers(window=60)["C"].status == "lost"
    assert _customers(window=60)["C"].lifespan_months == 0


def test_status_thresholds():
    assert core.status_of(30, 90) == "active"
    assert core.status_of(31, 90) == "at_risk"
    assert core.status_of(90, 90) == "at_risk"
    assert core.status_of(91, 90) == "lost"


def test_division_scope_filters_and_all_merges_one_month():
    corp = _customers("corp")
    assert set(corp) == {"A", "B"} and corp["B"].last_ship == date(2024, 12, 2)
    dfw = _customers("dfw")
    assert set(dfw) == {"B", "C"} and dfw["B"].first_ship == date(2024, 12, 30)
    merged = [m for m in core.merge_rows(ROWS, "all") if m.customer_id == "B" and m.month.month == 12]
    assert len(merged) == 1 and merged[0].loads == 2 and merged[0].divisions == frozenset({"CORP", "DFW"})
    with pytest.raises(ValueError):
        core.merge_rows(ROWS, "mx")


def test_pct_needs_a_positive_base():
    assert core.pct(-50, 500) == -10.0
    assert core.pct(50, -500) is None and core.pct(1, 0) is None


def test_summary_counts_one_population():
    s = core.summary(list(_customers().values()), AS_OF, 90)
    assert (s["customers_total"], s["base"], s["active"], s["at_risk"], s["lost"]) == (3, 2, 1, 1, 1)
    assert s["base"] == s["active"] + s["at_risk"]
    assert s["new_ytd"] == 3 and s["lost_12m"] == 1 and s["reactivated_12m"] == 1
    assert s["avg_lifespan_lost"] == 7 and s["median_lifespan_lost"] == 7
    assert s["first_ship"] == date(2024, 1, 5)


def test_a_customer_lost_and_won_back_counts_as_both():
    """Review 2026-10-29: the tile showed Lost 0 but "1 came back"."""
    rows = [_m("Z", date(2025, 11, 1), date(2025, 11, 1), date(2025, 11, 1)),
            _m("Z", date(2026, 8, 1), date(2026, 8, 15), date(2026, 8, 15))]
    as_of = date(2026, 8, 20)
    cs = core.build_customers(core.merge_rows(rows, "all"), as_of, 90)
    s = core.summary(cs, as_of, 90)
    assert cs[0].status == "active" and (s["lost_12m"], s["reactivated_12m"]) == (1, 1)
    assert core.loss_dates(cs[0], 90) == [date(2026, 1, 30)]


def test_customer_detail_is_zero_filled_to_as_of():
    d = core.customer_detail(_customers()["A"], AS_OF)
    assert [p["month"] for p in d["series"]][:3] == ["2024-01", "2024-02", "2024-03"]
    assert len(d["series"]) == 12 and d["series"][2]["revenue"] == 0.0
    assert d["series"][7]["margin_pct"] == -10.0 and d["months_active"] == ["2024-01", "2024-02", "2024-08"]
    assert len(d["spark_24m"]) == 24 and d["spark_24m"][-1] == 0.0


# ------------------------------------------------------------------ trends


def _by_period(rows):
    return {r["period"]: r for r in rows}


def test_monthly_flow_counts_confirmed_losses_only():
    t = _by_period(tr.trend(list(_customers().values()), AS_OF, 90, "month"))
    assert t["2024-01"]["new"] == 1 and t["2024-01"]["active"] == 1
    assert t["2024-02"]["lost"] == 1                                  # silence before August
    assert (t["2024-08"]["lost"], t["2024-08"]["reactivated"]) == (1, 1)
    assert t["2024-10"]["lost"] == 0                                  # C is at risk, not lost
    assert t["2024-03"]["base"] == 1 and t["2024-05"]["base"] == 0    # 50 vs 111 days quiet
    assert t["2024-12"]["base"] == 2 and t["2024-12"]["active"] == 1
    assert t["2024-08"]["margin_pct"] == -10.0


def test_quarter_grain_sums_flows_and_flags_partial():
    q = _by_period(tr.trend(list(_customers().values()), AS_OF, 90, "quarter"))
    assert (q["2024 Q1"]["new"], q["2024 Q1"]["lost"]) == (1, 1)
    assert (q["2024 Q4"]["new"], q["2024 Q4"]["active"], q["2024 Q4"]["base"]) == (2, 2, 2)
    assert q["2024 Q4"]["avg_monthly_active"] == 1.0 and not q["2024 Q4"]["partial"]
    mid = date(2024, 12, 30)
    q2 = _by_period(tr.trend(list(_customers(as_of=mid).values()), mid, 90, "quarter"))
    assert q2["2024 Q4"]["partial"]
    with pytest.raises(ValueError):
        tr.trend([], AS_OF, 90, "week")


def test_cohorts_and_retention():
    (row,) = tr.cohorts(list(_customers().values()), AS_OF)
    assert (row["cohort"], row["new"], row["base_now"], row["active_now"], row["lost"]) == (2024, 3, 2, 1, 1)
    assert row["retained_pct"] == 66.67
    assert row["retention"] == [{"year": 2024, "customers": 3, "pct": 100.0}]


def test_survival_censors_customers_still_in_the_base():
    s = tr.survival(list(_customers().values()), AS_OF)
    pts = {p["month"]: p for p in s["points"]}
    assert pts[7]["survival"] == 100.0 and pts[8]["survival"] == 0.0
    assert pts[1]["at_risk"] == 3 and pts[2]["at_risk"] == 2 and pts[8]["at_risk"] == 1
    assert s["median_months"] == 8


def test_lifespan_buckets_split_by_status():
    b = {x["bucket"]: x for x in tr.lifespan(list(_customers().values()), AS_OF)["buckets"]}
    assert b["1 month"]["at_risk"] == 1 and b["2–6 months"]["active"] == 1
    assert b["7–12 months"]["lost"] == 1


# ------------------------------------------------------------------ Excel loader


def _mv(order, ship, rev, sp="CORP", cust="RUANTRIA - Ruan Transport Corporation"):
    return {"Order": order, "Ship date": ship, "Customer": cust, "Salesperson": sp,
            "Total revenue": rev, "Carrier total pay": "100", "Margin $": "10"}


def test_movements_collapse_to_orders():
    orders = {o.order_id: o for o in loader.collapse_movements([
        _mv("0033280", "2016-01-05", "39.42"),
        _mv("0033280", "2016-01-04", "1105.58"),
        _mv("0033281", "2016-01-04", "", sp="TEAM-DFW"),
        _mv("0033282", datetime(2016, 1, 4, 0, 0), 5.0, sp="", cust="OILTEXTX - Oiltex Corp LLC"),
        _mv("", "2016-01-04", "1"),
    ])}
    o = orders["0033280"]
    assert (o.ship_date, round(o.revenue, 2), o.movements, o.margin) == (date(2016, 1, 4), 1145.0, 2, 20.0)
    assert (o.customer_id, o.customer_name, o.division) == ("RUANTRIA", "Ruan Transport Corporation", "CORP")
    assert orders["0033281"].division == "DFW" and orders["0033281"].revenue == 0.0
    assert orders["0033282"].division == "CORP" and orders["0033282"].ship_date == date(2016, 1, 4)
    assert len(orders) == 3
    assert o.record()[0] == store.COMPANY_ID and o.record()[-1] == "excel"


def test_loader_refuses_the_wrong_sheet():
    with pytest.raises(SystemExit):
        list(loader._dicts(["Month", "Customer"], [["2016 M01", "X"]]))


# ------------------------------------------------------------------ store / sync


def test_v4_sql_applies_the_dfw_marker_rule():
    assert "TM4" in store.V4_ORDERS_SQL and "TEAM-DFW" in store.V4_ORDERS_SQL
    assert "TRIM(v4.company_id)" not in store.V4_ORDERS_SQL       # sargable (pad variants)
    assert store.division_of("TEAM-DFW") == "DFW" and store.division_of("TEAM3") == "CORP"
    assert store.division_of("TEAM5   ") == "CORP"
    assert store.division_of("TEAM9") == "OTHER" and store.division_of(None) == "OTHER"
    assert "TRIM(v4.customer_id) <> ''" in store.V4_ORDERS_SQL
    rec = store.v4_records([{"order_id": "1", "ship_date": date(2026, 9, 2), "customer_id": "C",
                             "customer_name": "N", "division_team": "TEAM-DFW", "revenue": 1,
                             "carrier_pay": 0, "margin": 1}])
    assert rec == [("TMS ", "1", date(2026, 9, 2), "C", "N", "DFW", 1, 0, 1)]


def test_an_order_shifted_across_the_tail_start_is_not_a_gap():
    """Review 2026-10-29: Excel ships 06-30, v4 departs 07-01 — the Excel row is kept."""
    excel = [{"order_id": "5", "ship_date": date(2026, 6, 30), "revenue": 10}]
    window = [{"order_id": "5", "ship_date": date(2026, 7, 1), "revenue": 10}]
    r = store.reconcile(excel, [], window)
    assert r["gap_fill_orders"] == 0 and r["excel_orders"] == 0 and r["missing_in_datalake"] == 0


def test_freshness_never_shows_the_raw_exception():
    row = {"status": "failed", "started_at": None, "finished_at": None, "v4_rows": None,
           "gap_fills": None, "v4_last_write": None,
           "error": "UndefinedTableError: relation spaceqlik_gold_ro.x does not exist"}
    assert rt._public_sync(row)["error"] == "sync error — details in the server log"
    assert rt._public_sync({**row, "error": "RuntimeError: budget_report_v4 is stale"})["error"] == (
        "the datalake stopped updating")
    assert rt._public_sync({**row, "error": None})["error"] is None
    assert rt._public_sync(None) is None


def test_reconcile_counts_orders():
    excel = [{"order_id": "1", "ship_date": date(2026, 7, 31), "revenue": 100.4},
             {"order_id": "2", "ship_date": date(2026, 8, 2), "revenue": 50},
             {"order_id": "3", "ship_date": date(2026, 8, 3), "revenue": 70}]
    v4_tail = [{"order_id": "1", "status": "D", "ship_date": date(2026, 8, 1), "revenue": 100},
               {"order_id": "2", "status": "V", "ship_date": date(2026, 8, 2), "revenue": 50}]
    window = [{"order_id": "9", "ship_date": date(2026, 8, 30), "revenue": 20},
              {"order_id": "10", "ship_date": date(2026, 9, 2), "revenue": 99},
              {"order_id": "1", "ship_date": date(2026, 8, 1), "revenue": 100}]
    r = store.reconcile(excel, v4_tail, window)
    assert (r["excel_orders"], r["matched"], r["missing_in_datalake"], r["voided_in_datalake"]) == (3, 1, 1, 1)
    assert r["missing_sample"] == ["3"] and r["voided_ids"] == ["2"]
    assert r["revenue_diff"] == -0.4 and r["orders_revenue_off_over_1usd"] == 0
    assert r["orders_ship_month_moved"] == 1
    assert (r["gap_fill_orders"], r["gap_fill_revenue"]) == (1, 20.0)


class _Conn:
    def __init__(self, hub):
        self.hub = hub

    def transaction(self):
        return self

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def execute(self, sql, *p):
        self.hub.calls.append(("tx", sql, p))

    async def executemany(self, sql, rows):
        self.hub.calls.append(("tx-many", sql, (len(rows),)))

    async def fetchval(self, sql, *p):
        self.hub.calls.append(("tx", sql, p))
        return 5 if sql == store.COUNT_V4_SQL else 1


class _Hub:
    def __init__(self, stored=0, tail=()):
        self.calls, self.stored, self.tail = [], stored, list(tail)

    async def fetchval(self, sql, *p):
        self.calls.append(("hub", sql, p))
        return {store.LOG_START_SQL: 42, store.COUNT_V4_SQL: self.stored}[sql]

    async def fetch(self, sql, *p):
        assert sql == store.EXCEL_TAIL_SQL and p == (store.TAIL_START - store.SHIP_SHIFT_MARGIN,)
        return self.tail

    async def execute(self, sql, *p):
        self.calls.append(("hub", sql, p))

    def acquire(self):
        return _Conn(self)


class _Gold:
    def __init__(self, last_write, rows):
        self.last_write, self.rows, self.calls = last_write, rows, []

    async def fetchval(self, sql, *p):
        assert sql == store.V4_FRESHNESS_SQL
        return self.last_write

    async def fetch(self, sql, *p):
        self.calls.append((sql, p))
        if sql == store.V4_ORDERS_SQL:
            return self.rows
        assert sql == store.V4_BY_ID_SQL
        return [{"order_id": "1", "status": "D", "ship_date": date(2026, 8, 1), "revenue": 10}]


NOW = datetime(2026, 10, 29, 3, 30)
V4_ROW = {"order_id": "7", "ship_date": date(2026, 9, 3), "customer_id": "C", "customer_name": "N",
          "division_team": "TEAM1", "revenue": 10, "carrier_pay": 5, "margin": 5}


@pytest.mark.asyncio
async def test_sync_replaces_v4_rows_in_one_transaction_and_logs_ok():
    hub = _Hub(tail=[{"order_id": "1", "ship_date": date(2026, 7, 2), "revenue": 10}])
    gold = _Gold(NOW - timedelta(minutes=20), [V4_ROW])
    out = await store.sync_from_datalake(hub, gold, NOW)
    assert out["v4_rows"] == 1 and out["matched"] == 1
    tx = [sql for kind, sql, _ in hub.calls if kind.startswith("tx")]
    assert tx[:3] == [store.DELETE_V4_SQL, store.INSERT_V4_SQL, store.MARK_VOIDED_SQL]
    orders_call = gold.calls[0]
    assert orders_call[1][0] == ["TMS", "TMS "] and orders_call[1][1] == ["D", "P"]
    assert orders_call[1][2] == datetime(2026, 7, 1)
    assert gold.calls[1][1][1] == ["1", "1       "]                # ids padded to varchar(8)
    ok = [p for kind, sql, p in hub.calls if sql == store.LOG_OK_SQL]
    assert ok and ok[0][0] == 42


@pytest.mark.asyncio
@pytest.mark.parametrize("last_write,stored,match", [
    (NOW - timedelta(hours=49), 0, "stale"),
    (None, 0, "stale"),
    (NOW - timedelta(minutes=5), 1000, "refusing to shrink"),
])
async def test_sync_refuses_and_records_the_failure(last_write, stored, match):
    hub = _Hub(stored=stored)
    with pytest.raises(RuntimeError, match=match):
        await store.sync_from_datalake(hub, _Gold(last_write, [V4_ROW]), NOW)
    failed = [p for kind, sql, p in hub.calls if sql == store.LOG_FAILED_SQL]
    assert failed and failed[0][0] == 42
    assert not any(sql == store.DELETE_V4_SQL for _, sql, _ in hub.calls)


@pytest.mark.asyncio
async def test_sync_without_pools_raises():
    with pytest.raises(RuntimeError):
        await store.sync_from_datalake(None, None, NOW)


# ------------------------------------------------------------------ router


class _HubRead:
    def __init__(self, rows):
        self.rows, self.reads = rows, 0

    async def fetch(self, sql, *p):
        assert sql == core.CUSTOMER_MONTHS_SQL
        self.reads += 1
        return self.rows


class _Req:
    def __init__(self, pool):
        self.app = type("A", (), {"state": type("S", (), {"pool": pool})()})()


@pytest.fixture(autouse=True)
def _fresh_cache():
    rt.invalidate_cache()
    yield
    rt.invalidate_cache()


@pytest.mark.asyncio
async def test_endpoints_share_one_cached_read_and_report_as_of():
    pool = _HubRead(ROWS)
    body = await rt.summary_view(_Req(pool), rt.Division.all, 90, USER)
    assert body["meta"] == {"division": "all", "window_days": 90, "as_of": "2024-12-30"}
    assert body["data"]["base"] == 2
    cust = await rt.customers_view(_Req(pool), rt.Division.dfw, 90, USER)
    assert {r["customer_id"] for r in cust["data"]} == {"B", "C"}
    trend = await rt.trend_view(_Req(pool), rt.Division.corp, 90, "year", USER)
    assert trend["data"][0]["period"] == "2024"
    assert pool.reads == 1


@pytest.mark.asyncio
async def test_bad_window_grain_customer_and_empty_table():
    pool = _HubRead(ROWS)
    with pytest.raises(HTTPException) as e:
        await rt.summary_view(_Req(pool), rt.Division.all, 45, USER)
    assert e.value.status_code == 422
    with pytest.raises(HTTPException) as e:
        await rt.trend_view(_Req(pool), rt.Division.all, 90, "week", USER)
    assert e.value.status_code == 422
    with pytest.raises(HTTPException) as e:
        await rt.customer_view(_Req(pool), rt.Division.corp, "C", 90, USER)
    assert e.value.status_code == 404
    rt.invalidate_cache()
    with pytest.raises(HTTPException) as e:
        await rt.summary_view(_Req(_HubRead([])), rt.Division.all, 90, USER)
    assert e.value.status_code == 503


def test_division_is_a_required_path_segment():
    from app.main import app

    paths = {r.path for r in app.routes if getattr(r, "path", "").startswith("/api/custom/customer-lifespan")}
    assert paths == {
        "/api/custom/customer-lifespan/freshness",
        "/api/custom/customer-lifespan/{division}/summary",
        "/api/custom/customer-lifespan/{division}/trend",
        "/api/custom/customer-lifespan/{division}/cohorts",
        "/api/custom/customer-lifespan/{division}/lifespan",
        "/api/custom/customer-lifespan/{division}/customers",
        "/api/custom/customer-lifespan/{division}/customers/{customer_id}",
    }


# ------------------------------------------------------------------ wiring


def test_four_place_mirror_and_roles():
    from app.services.seed import CUSTOM_REPORTS

    entry = next(r for r in CUSTOM_REPORTS if r["key"] == rt.REPORT_KEY)
    assert entry["title"] == "Customer Lifespan"
    for role in ("Executive", "admin", "Sales", "Operations", "CORP", "DFW", "CEO"):
        assert role in entry["roles"]
    icons = (ROOT / "frontend/components/ReportIcons.tsx").read_text()
    assert '"Customer Lifespan":' in icons
    page = (ROOT / "frontend/app/reports/customer-lifespan/page.tsx").read_text()
    assert 'reportKey="customer-lifespan"' in page
    src = (ROOT / "backend/app/routers/customer_lifespan.py").read_text()
    assert src.count("require_report_access(REPORT_KEY)") == 7


def test_job_is_scheduled_and_on_the_roster():
    src = (ROOT / "backend/app/main.py").read_text()
    assert 'id="daily_customer_lifespan_sync"' in src
    roster = src.split("EXPECTED_JOBS = {", 1)[1].split("}", 1)[0]
    assert '"daily_customer_lifespan_sync":' in roster
    body = src.split("async def _scheduled_customer_lifespan_sync", 1)[1].split("\nasync def ", 1)[0]
    assert "raise" in body and "invalidate_cache()" in body


# ------------------------------------------------------------------ live (opt-in)


@pytest.mark.asyncio
@pytest.mark.skipif(not os.getenv("SAVINGS_DATABASE_URL"), reason="live gold datalake not configured")
async def test_live_gold_statements_parse():
    import asyncpg

    conn = await asyncpg.connect(os.environ["SAVINGS_DATABASE_URL"], ssl="require")
    try:
        await conn.execute(f"EXPLAIN {store.V4_ORDERS_SQL}".replace("$3", "'2026-07-01'::timestamp")
                           .replace("$1::text[]", "ARRAY['TMS ']").replace("$2::text[]", "ARRAY['D']"))
        assert await conn.fetchval(store.V4_FRESHNESS_SQL) is not None
    finally:
        await conn.close()
