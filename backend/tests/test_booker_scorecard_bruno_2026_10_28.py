"""Booker Performance Scorecard — Bruno PDF 2026-10-28.

* **R1** "Ali Cisneros" joins the Rank roster (16 names; feeds /rank and
  /rank/last-week through the one `_RANK_ROSTER_KEYS`).
* **R2** Carrier Cost = v4 ``override_pay_amt`` REPORT-WIDE (was Revenue −
  Profit). The placeholder / zero-cost exclusions stay keyed on
  ``total_charge − margin_amt`` so the POPULATION does not move.
* **R3** a "Cost Overrun" KPI: Σ (threshold − cost) over broken orders, ≤ 0 —
  the SAME figure as the Totals cell and Σ of the per-row column.
* **R4** Threshold Variance % = 1 − Cost / Threshold, signed; + green, − red,
  equal at cents → 0 yellow; Totals weighted 1 − ΣC/ΣT.
"""

from __future__ import annotations

import asyncio
import re
import types
from datetime import date, datetime
from pathlib import Path

import pytest

from app.booker_names import matches_roster, roster_keys
from app.routers import booker_scorecard as bs

_FRONT = Path(__file__).resolve().parents[2] / "frontend"
_REPORT_DIR = _FRONT / "app" / "reports" / "booker-performance-scorecard"


class _StubPool:
    def __init__(self, rows=None):
        self.sqls: list[str] = []
        self.rows = rows or []

    async def fetch(self, sql, *params):
        self.sqls.append(sql)
        return list(self.rows)


def _row(order_id: str, *, revenue: float, profit: float, carrier_cost: float):
    """One `base` row with an EXPLICIT carrier cost — deliberately NOT
    revenue − profit, so a test passing here cannot be relying on the old
    identity."""
    return {
        "order_id": order_id,
        "team": "TM4",
        "customer": "ACME",
        "posted_by": "ALI CISNEROS",
        "posted_date": datetime(2026, 10, 20, 10, 0),
        "contract_type": "CONTRACT",
        "revenue": revenue,
        "profit": profit,
        "carrier_cost": carrier_cost,
        "otp_on_time": True,
        "otd_on_time": True,
        "rc_count": 1,
    }


_CALL = dict(
    range="mtd", start_date=None, end_date=None,
    contract_type=None, customer_name=None, posted_by=None, adjustment=0.0,
)


def _drive(endpoint, rows, thresholds, **extra):
    pool = _StubPool(rows)
    orig_pool, orig_thresh = bs.get_datalake_gold_pool, bs._thresholds
    bs.get_datalake_gold_pool = lambda request: pool

    async def _stub_thresholds(request, order_ids):
        return thresholds

    bs._thresholds = _stub_thresholds
    try:
        request = types.SimpleNamespace(
            app=types.SimpleNamespace(state=types.SimpleNamespace())
        )
        resp = asyncio.run(endpoint(request=request, _user={}, **dict(_CALL, **extra)))
    finally:
        bs.get_datalake_gold_pool, bs._thresholds = orig_pool, orig_thresh
    return pool, resp["data"]


def _orders(rows, thresholds):
    return _drive(bs.orders, rows, thresholds, sort="posted_desc", page=1, limit=200)


def _summary(rows, thresholds):
    return _drive(bs.summary, rows, thresholds)


def _base_sql_text() -> str:
    return bs._base_sql(
        [], start=date(2026, 10, 1), end=date(2026, 10, 28),
        contract_types=[], customers=[], posted_by=[],
    )


def _strip_sql_comments(sql: str) -> str:
    return re.sub(r"--[^\n]*", "", sql)


# --------------------------------------------------------------------------
# R1 — roster
# --------------------------------------------------------------------------


def test_ali_cisneros_is_on_the_rank_roster():
    assert "Ali Cisneros" in bs.RANK_ROSTER
    assert len(bs.RANK_ROSTER) == 16
    assert matches_roster("ALI CISNEROS", bs._RANK_ROSTER_KEYS)


def test_ali_cisneros_key_collides_with_no_other_entry():
    keys = roster_keys(bs.RANK_ROSTER)
    others = roster_keys(tuple(n for n in bs.RANK_ROSTER if n != "Ali Cisneros"))
    assert len(keys) == len(bs.RANK_ROSTER)
    assert not matches_roster("ALI CISNEROS", others)


# --------------------------------------------------------------------------
# R2 — Carrier Cost = override_pay_amt; exclusions unchanged
# --------------------------------------------------------------------------


def test_carrier_cost_derives_from_override_pay_amt():
    sql = _strip_sql_comments(_base_sql_text())
    assert re.search(
        r"COALESCE\(\s*br\.override_pay_amt\s*,\s*0\s*\)::float\s+AS\s+override_pay", sql
    )
    assert re.search(r"rc\.override_pay\s+AS\s+carrier_cost", sql)
    # The old identity must be gone from the cost column.
    assert not re.search(r"rc\.revenue\s*-\s*rc\.profit", sql)


def test_placeholder_exclusions_still_key_on_total_charge_minus_margin():
    """Population unchanged by the cost switch: every exclusion is still
    judged on total_charge − margin_amt, never on override_pay_amt."""
    sql = _strip_sql_comments(_base_sql_text())
    assert re.search(
        r"\(br\.total_charge\s*-\s*br\.margin_amt\)\s+IS\s+DISTINCT\s+FROM\s+0::numeric", sql
    )
    for revenue in ("150", "250", "200"):
        assert re.search(
            r"\(br\.total_charge,\s*br\.total_charge\s*-\s*br\.margin_amt\)\s+"
            r"IS\s+DISTINCT\s+FROM\s*\(" + revenue + r"::numeric,\s*150::numeric\)",
            sql,
        ), revenue
    where = sql[sql.index("WHERE rp.rn = 1"): sql.index("sc AS (")]
    assert "override_pay" not in where


def test_scenario_keeps_revenue_and_moves_cost_and_profit_by_the_delta():
    rows = [_row("A", revenue=10_000.0, profit=1_500.0, carrier_cost=9_000.0)]
    moved = bs._apply_scenario(rows, 25.0)[0]
    assert moved["revenue"] == 10_000.0
    assert moved["profit"] == pytest.approx(1_525.0)
    assert moved["carrier_cost"] == pytest.approx(8_975.0)


# --------------------------------------------------------------------------
# R3 — Cost Overrun KPI = Totals = Σ per-row
# --------------------------------------------------------------------------


_MIXED = [
    _row("OVER1", revenue=2_000.0, profit=300.0, carrier_cost=1_100.0),   # T 1,000 → −100
    _row("OVER2", revenue=5_000.0, profit=100.0, carrier_cost=5_250.0),   # T 5,000 → −250
    _row("UNDER", revenue=3_000.0, profit=700.0, carrier_cost=2_000.0),   # T 2,500 → saving
    _row("ON", revenue=1_000.0, profit=0.0, carrier_cost=800.0),          # T   800 → neither
    _row("NOT", revenue=9_000.0, profit=10.0, carrier_cost=9_999.0),      # no threshold
]
_THRESH = {"OVER1": 1_000.0, "OVER2": 5_000.0, "UNDER": 2_500.0, "ON": 800.0}


def test_cost_overrun_kpi_equals_totals_equals_sum_of_rows():
    _, summ = _summary(_MIXED, _THRESH)
    _, orders = _orders(_MIXED, _THRESH)
    per_row = sum(r["cost_overrun"] or 0.0 for r in orders["rows"])
    assert summ["cost_overrun"] == pytest.approx(-350.0)
    assert orders["totals"]["cost_overrun"] == pytest.approx(summ["cost_overrun"])
    assert per_row == pytest.approx(summ["cost_overrun"])
    # The card's sub-line count spans the same population (§96).
    assert summ["broken_threshold"] == 2


def test_cost_overrun_is_none_when_ap_is_down():
    _, summ = _summary(_MIXED, None)
    _, orders = _orders(_MIXED, None)
    assert summ["cost_overrun"] is None
    assert orders["totals"]["cost_overrun"] is None


def test_cost_overrun_is_zero_not_none_when_nobody_went_over():
    rows = [_row("UNDER", revenue=3_000.0, profit=700.0, carrier_cost=2_000.0)]
    _, summ = _summary(rows, {"UNDER": 2_500.0})
    assert summ["cost_overrun"] == 0.0


# --------------------------------------------------------------------------
# R4 — Threshold Variance % = 1 − C/T
# --------------------------------------------------------------------------


def test_variance_rows_and_weighted_totals():
    _, orders = _orders(_MIXED, _THRESH)
    by_id = {r["order_id"]: r["threshold_variance_pct"] for r in orders["rows"]}
    assert by_id["OVER1"] == pytest.approx(-0.10)
    assert by_id["OVER2"] == pytest.approx(-0.05)
    assert by_id["UNDER"] == pytest.approx(0.20)
    assert by_id["ON"] == 0.0
    assert by_id["NOT"] is None
    cost = 1_100.0 + 5_250.0 + 2_000.0 + 800.0
    thresh = 1_000.0 + 5_000.0 + 2_500.0 + 800.0
    assert orders["totals"]["threshold_variance_pct"] == pytest.approx(1 - cost / thresh)


def test_variance_desc_now_leads_with_the_best_and_keeps_nulls_last():
    _, data = _drive(
        bs.orders, _MIXED, _THRESH, sort="variance_desc", page=1, limit=200
    )
    ids = [r["order_id"] for r in data["rows"]]
    assert ids[0] == "UNDER"
    assert ids[-1] == "NOT"
    _, data = _drive(
        bs.orders, _MIXED, _THRESH, sort="variance_asc", page=1, limit=200
    )
    ids = [r["order_id"] for r in data["rows"]]
    assert ids[0] == "OVER1"
    assert ids[-1] == "NOT"


def test_orders_table_colours_variance_by_sign():
    """No JS test runner (§107): read the TSX. Green for +, red for −, yellow
    for exactly 0, and the Totals cell goes through the same helper."""
    src = (_REPORT_DIR / "OrdersTable.tsx").read_text()
    assert "function varianceTone(" in src
    body = src[src.index("function varianceTone("):]
    body = body[: body.index("\n}\n")]
    assert "emerald" in body and "red" in body and "amber" in body
    assert src.count("varianceTone(") >= 3  # definition + row + totals


def test_kpi_cards_render_cost_overrun_after_cost_saving():
    src = (_REPORT_DIR / "KpiCards.tsx").read_text()
    assert "Revenue − Profit" not in src
    assert src.index("Cost Saving") < src.index("Cost Overrun")
    assert "cost_overrun" in src
    api = (_FRONT / "lib" / "booker-scorecard-api.ts").read_text()
    summary = api[api.index("interface BookerSummary"):]
    summary = summary[: summary.index("}")]
    assert "cost_overrun" in summary
