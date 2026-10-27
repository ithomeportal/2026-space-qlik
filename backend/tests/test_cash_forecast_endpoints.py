"""Collections Settlement Forecast — every endpoint, the readers, the job.

A stub pool cannot see a WHERE (§99), so each test asserts BOTH the statement
it served (by its exported constant, never a paraphrase — cron-job-debug §1b)
and the payload. The live layer at the bottom EXPLAINs every exported statement
on the real UNLK-Financial DB when ``FINANCIAL_DATABASE_URL`` is set.
"""
from __future__ import annotations

import ast
import os
from datetime import date, datetime, timedelta
from pathlib import Path

import pytest
from fastapi import HTTPException

from app.routers import collections_settlement_forecast as rt
from app.services import cash_forecast as cf
from app.services import cash_forecast_snapshot as snap
from app.services import cash_forecast_sources as cs

TODAY = date(2026, 10, 26)
WEEK = cf.finance_week(TODAY)
USER = {"sub": "t", "email": "t@local", "roles": ["admin"]}
ROOT = Path(__file__).resolve().parents[1]


class _Pool:
    """Answers each exported statement with canned rows; records every call."""

    def __init__(self, statements: dict, fail: tuple[str, ...] = ()):
        self.statements = statements
        self.calls: list[tuple[str, tuple]] = []
        self.fail = fail

    def _rows(self, sql):
        name = next(k for k, v in self.statements.items() if v == sql)
        if name in self.fail:
            raise RuntimeError(f"permission denied for table ({name})")
        bill = WEEK.start - timedelta(days=30)
        return name, {
            "ar_orders": [
                {"snapshot_date": TODAY, "order_id": "A", "customer_id": "C1", "customer_name": "Cust 1 ",
                 "balance": 1_000, "bill_date": bill, "bill_due_days": 30,
                 "customer_payment_date": bill + timedelta(days=30), "week_n": 0},
                {"snapshot_date": TODAY, "order_id": "B", "customer_id": "C2", "customer_name": "Cust 2",
                 "balance": 500, "bill_date": bill - timedelta(days=14), "bill_due_days": 30,
                 "customer_payment_date": bill + timedelta(days=16), "week_n": -2},
            ],
            "directory": [{"customer_id": "C1", "average_pay_days": 30}],
            "receipts_weekly": [{"week_start": WEEK.start, "collected": 250, "latest": TODAY},
                                {"week_start": WEEK.start - timedelta(weeks=1), "collected": 4_000,
                                 "latest": WEEK.start - timedelta(days=1)}],
            "receipts_by_order": [{"order_id": "A", "paid": 250}],
            "receipts_checked": datetime(2026, 10, 26, 20, 31),
            "settlements": [{"pay_date": WEEK.end, "amount": 900, "payees": 3}],
            "settlements_future": {"snap": TODAY, "future": 123},
            "ap": [{"due_date": WEEK.end + timedelta(days=1), "amount": 40, "items": 2, "snap": TODAY},
                   {"due_date": None, "amount": 5, "items": 1, "snap": TODAY}],
            "shipped": [{"customer_id": "C1", "customer_name": "Cust 1", "base_date": bill, "revenue": 1_200},
                        {"customer_id": "C3", "customer_name": "Cust 3",
                         "base_date": WEEK.start - timedelta(days=16), "revenue": 70}],
            "shipped_fresh": datetime(2026, 10, 26, 16, 47),
        }[name]

    async def fetch(self, sql, *params):
        name, rows = self._rows(sql)
        self.calls.append((name, params))
        return rows

    async def fetchrow(self, sql, *params):
        return await self.fetch(sql, *params)

    async def fetchval(self, sql, *params):
        return await self.fetch(sql, *params)


def _fin(fail=()):
    return _Pool(cs.FINANCIAL_STATEMENTS, fail)


def _gold(fail=()):
    return _Pool(cs.GOLD_STATEMENTS, fail)


class _Req:
    def __init__(self, fin=None, hub=None, gold="default"):
        gold = _gold() if gold == "default" else gold
        state = {"financial_pool": fin, "pool": hub, "savings_pool": gold}
        self.app = type("A", (), {"state": type("S", (), state)()})()


@pytest.fixture(autouse=True)
def _frozen(monkeypatch):
    monkeypatch.setattr(rt, "cst_today", lambda: TODAY)
    rt._cache.clear()


@pytest.mark.asyncio
async def test_this_week_reads_every_source_with_tms_and_the_week():
    fin, gold = _fin(), _gold()
    body = await rt.this_week(_Req(fin, gold=gold), USER)
    names = {n: p for n, p in fin.calls}
    assert names["ar_orders"] == ("TMS",) and names["directory"] == ("TMS",)
    assert names["receipts_by_order"] == ("TMS", WEEK.start, WEEK.end)
    assert names["receipts_weekly"][0] == "TMS" and names["receipts_weekly"][2] == WEEK.end
    assert names["receipts_checked"] == (cs.RECEIPTS_CHECK_JOB_ID,)
    shipped = dict(gold.calls)["shipped"]
    assert "TMS " in shipped[1] and "D" in shipped[2] and "UNILINTX" in shipped[3]
    assert shipped[4] == 3                                  # bill lag for unbilled loads
    d = body["data"]
    assert d["cash_in"]["collected_so_far"] == 250.0
    assert d["cash_in"]["remaining_due"] == 750.0           # 1,000 − 250 paid on order A
    assert d["cash_in"]["committed"] == 1_500.0             # 250 + 750 + 500 past due
    assert d["cash_in"]["expected"] == 1_200.0              # C1 bill+30; C3 (−16 + 30 default) is week 2
    assert d["cash_out"]["ap_due"] == 40.0                  # Saturday due → this Friday
    assert d["cash_out"]["total"] == 940.0 and d["cash_out"]["ap_undated"] == 5.0
    assert d["net"] == {"committed": 560.0, "expected": 260.0}
    fresh = body["meta"]["freshness"]
    assert fresh["receipts_checked_at"] == "2026-10-26 15:31 CT"   # naive UTC → CT
    assert fresh["shipped_as_of"] == "2026-10-26 16:47 CT"         # gold is already CST
    assert fresh["failed_sources"] == []


@pytest.mark.asyncio
async def test_one_page_view_reads_the_financial_db_once():
    pool = _fin()
    await rt.this_week(_Req(pool), USER)
    await rt.weeks(_Req(pool), USER)
    await rt.by_customer(_Req(pool), USER)
    await rt.sources(_Req(pool), USER)
    assert sum(1 for n, _ in pool.calls if n == "ar_orders") == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("dead,label", [("settlements", "settlements"), ("ap", "ap")])
async def test_failed_source_is_named_and_unknown_not_zero(dead, label):
    body = await rt.this_week(_Req(_fin(fail=(dead,))), USER)
    assert body["data"]["cash_out"]["total"] is None
    assert body["data"]["net"] == {"committed": None, "expected": None}
    assert body["meta"]["freshness"]["failed_sources"] == [label]


@pytest.mark.asyncio
async def test_missing_gold_pool_blanks_only_the_expected_basis():
    body = await rt.this_week(_Req(_fin(), gold=None), USER)
    assert body["data"]["net"]["expected"] is None
    assert body["data"]["net"]["committed"] == 560.0
    assert body["meta"]["freshness"]["failed_sources"] == ["shipped_revenue"]


@pytest.mark.asyncio
async def test_weeks_by_customer_sources_payloads():
    pool = _fin()
    weeks = await rt.weeks(_Req(pool), USER)
    assert len(weeks["data"]) == cf.HORIZON_WEEKS
    assert weeks["meta"]["settlements_unplaced"] == 123.0
    assert weeks["data"][0]["in_due_terms"] == 1_500.0
    cust = await rt.by_customer(_Req(pool), USER)
    assert cust["meta"]["total"] == len(cust["data"]) == 3
    assert {r["customer_name"] for r in cust["data"]} == {"Cust 1", "Cust 2", "Cust 3"}
    c3 = next(r for r in cust["data"] if r["customer_id"] == "C3")
    assert c3["pay_days_known"] is False and c3["avg_pay_days"] == 30.0
    src = await rt.sources(_Req(pool), USER)
    assert src["data"]["ar_snapshot_date"] == TODAY.isoformat()


@pytest.mark.asyncio
async def test_by_customer_503_when_bruce_inputs_unreadable():
    with pytest.raises(HTTPException) as e:
        await rt.by_customer(_Req(_fin(fail=("directory",))), USER)
    assert e.value.status_code == 503


@pytest.mark.asyncio
async def test_missing_financial_pool_is_503():
    with pytest.raises(HTTPException) as e:
        await rt.this_week(_Req(None), USER)
    assert e.value.status_code == 503


class _HubPool:
    def __init__(self, rows=None, fail=False):
        self.rows, self.fail = rows or [], fail
        self.executed: list[tuple] = []
        self.sql: list[str] = []

    async def fetch(self, sql, *params):
        if self.fail:
            raise RuntimeError("relation does not exist")
        assert sql == snap.READ_SQL
        return self.rows

    async def fetchval(self, sql, *params):
        return False

    def acquire(self):
        hub = self

        class _Conn:
            async def __aenter__(self):
                return self

            async def __aexit__(self, *a):
                return False

            def transaction(self):
                return self

            async def executemany(self, sql, rows):
                hub.sql.append(sql)
                hub.executed.extend(rows)

        return _Conn()


@pytest.mark.asyncio
async def test_accuracy_reads_snapshots_and_survives_their_absence():
    w1 = WEEK.start - timedelta(weeks=1)
    hub = _HubPool([{"snapshot_date": w1, "week_start": w1, "week_offset": 0, "in_expected": 3_000,
                     "in_committed": 3_500, "in_run_rate": 0, "settlements": 1_000, "ap": 0,
                     "complete": True}])
    body = await rt.accuracy(_Req(_fin(), hub), USER)
    row = next(r for r in body["data"] if r["week_start"] == w1.isoformat())
    assert row["actual_in"] == 4_000.0 and row["variance_in"] == 1_000.0
    assert body["meta"]["first_snapshot"] == w1.isoformat()
    rt._cache.clear()
    empty = await rt.accuracy(_Req(_fin(), _HubPool(fail=True)), USER)
    assert all(r["forecast_in"] is None for r in empty["data"])


@pytest.mark.asyncio
async def test_snapshot_job_writes_13_weeks_and_raises_when_blind():
    hub = _HubPool()
    result = await snap.capture_forecast_snapshot(hub, _fin(), _gold(), TODAY)
    assert result["rows"] == cf.HORIZON_WEEKS == len(hub.executed) and result["complete"]
    assert hub.sql == [snap.UPSERT_COMPLETE_SQL]
    first = hub.executed[0]
    assert first[:3] == (TODAY, WEEK.start, 0) and first[4] == 1_500.0   # committed on week 0 only
    assert all(r[4] is None for r in hub.executed[1:]) and first[-1] is True
    hub2 = _HubPool()
    partial = await snap.capture_forecast_snapshot(hub2, _fin(fail=("ap",)), _gold(), TODAY)
    assert partial["complete"] is False and hub2.sql == [snap.UPSERT_PARTIAL_SQL]
    with pytest.raises(RuntimeError):
        await snap.capture_forecast_snapshot(hub, _fin(fail=("settlements",)), None, TODAY)
    with pytest.raises(RuntimeError):
        await snap.capture_forecast_snapshot(None, _fin(), _gold(), TODAY)


def test_partial_upsert_only_fills_and_complete_never_overwrites_complete():
    assert "COALESCE(cash_forecast_snapshot.in_expected, EXCLUDED.in_expected)" in snap.UPSERT_PARTIAL_SQL
    assert "complete" not in snap.UPSERT_PARTIAL_SQL.split("DO UPDATE SET", 1)[1]
    assert snap.UPSERT_COMPLETE_SQL.rstrip().endswith("WHERE NOT cash_forecast_snapshot.complete")


# ------------------------------------------------------------------ wiring

def _main_src() -> str:
    return (ROOT / "app" / "main.py").read_text()


def test_router_registered_gated_and_job_rostered():
    src = _main_src()
    assert "app.include_router(collections_settlement_forecast.router" in src
    assert 'id="daily_cash_forecast_snapshot"' in src and '"daily_cash_forecast_snapshot":' in src
    tree = ast.parse((ROOT / "app" / "routers" / "collections_settlement_forecast.py").read_text())
    endpoints = [n for n in tree.body if isinstance(n, ast.AsyncFunctionDef)
                 and any("router.get" in ast.unparse(d) for d in n.decorator_list)]
    assert len(endpoints) == 5
    for fn in endpoints:
        assert "require_report_access(REPORT_KEY)" in ast.unparse(fn.args)


def test_scheduled_job_reraises():
    tree = ast.parse(_main_src())
    fn = next(n for n in tree.body if isinstance(n, ast.AsyncFunctionDef)
              and n.name == "_scheduled_cash_forecast_snapshot")
    assert any(isinstance(n, ast.Raise) for n in ast.walk(fn))


def test_seed_entry_and_ai_sections():
    from app.services.ai_chat_tools import DENIED_KEY_STEMS, SECTION_ALLOWLIST
    from app.services.seed import CUSTOM_REPORTS

    entry = next(r for r in CUSTOM_REPORTS if r["key"] == rt.REPORT_KEY)
    assert entry["title"] == "Collections Settlement Forecast"
    assert {"CFO", "Finance", "AdminFinance", "Executive"} <= set(entry["roles"])
    assert {"this-week", "weeks", "by-customer", "accuracy", "sources"} <= SECTION_ALLOWLIST
    assert not any(stem in rt.REPORT_KEY for stem in DENIED_KEY_STEMS)


# ------------------------------------------------------------------ live layer

@pytest.mark.asyncio
@pytest.mark.skipif(not os.getenv("FINANCIAL_DATABASE_URL"), reason="live UNLK-Financial DB not configured")
async def test_live_every_financial_statement_runs_under_the_real_role():
    """Executes (not just parses) every exported statement as the deployed role
    — proves the grants AND the SQL (§81, db-url-derivation-audit)."""
    import asyncpg

    conn = await asyncpg.connect(os.environ["FINANCIAL_DATABASE_URL"])
    try:
        async with conn.transaction(readonly=True):
            for name, sql in cs.FINANCIAL_STATEMENTS.items():
                params = {
                    "ar_orders": ("TMS",), "directory": ("TMS",),
                    "receipts_weekly": ("TMS", WEEK.start - timedelta(weeks=13), WEEK.end),
                    "receipts_by_order": ("TMS", WEEK.start, WEEK.end),
                    "receipts_checked": (cs.RECEIPTS_CHECK_JOB_ID,),
                }.get(name, ())
                await conn.fetch(sql, *params)
    finally:
        await conn.close()


@pytest.mark.asyncio
@pytest.mark.skipif(not os.getenv("SAVINGS_DATABASE_URL"), reason="live gold datalake not configured")
async def test_live_shipped_revenue_statement_runs():
    import asyncpg

    conn = await asyncpg.connect(os.environ["SAVINGS_DATABASE_URL"])
    try:
        async with conn.transaction(readonly=True):
            rows = await conn.fetch(cs.SHIPPED_SQL, *cs.shipped_params(WEEK))
            assert rows and all(r["base_date"].year >= 2000 for r in rows)   # sentinel guarded
    finally:
        await conn.close()
