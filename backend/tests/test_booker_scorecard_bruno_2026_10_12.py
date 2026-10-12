"""Booker Performance Scorecard — Bruno PDF 2026-10-12 (Scenario tab, Orders table).

"Add the following filters to the Orders table: Revenue = '200', Carrier Cost =
'150', Profit = '50'" — read (confirmed with the user) as per-column amount
filters, the quoted figures being Bruno's example values.

What these tests stop:

* "= 200" missing a $200.00 order because the scenario's float arithmetic left
  it at 199.99999999 (compare at CENTS);
* the filter running on the RAW numbers while the table shows the ADJUSTED ones
  (it must run after `_apply_scenario`);
* the Totals row / ``meta.total`` describing the unfiltered set while the rows
  are filtered — a COUNT and a SUM must span one population (§96);
* an unknown operator silently ignored (400, same rule as the sort whitelist);
* a NULL amount matching "<= 50" as if it were $0;
* a direct call receiving FastAPI's ``Query(None)`` FieldInfo as a filter;
* the frontend sending param names the backend does not declare — FastAPI
  DROPS those silently and the table looks unfiltered.
"""

from __future__ import annotations

import asyncio
import re
import types
from datetime import datetime
from pathlib import Path

import pytest
from fastapi import HTTPException

from app.routers import booker_scorecard as bs

_FRONTEND = Path(__file__).resolve().parents[2] / "frontend"


class _StubPool:
    def __init__(self, rows):
        self.rows = rows

    async def fetch(self, sql, *params):
        return list(self.rows)


def _row(order_id, revenue, profit):
    return {
        "order_id": order_id,
        "team": "TM1",
        "customer": "ACME",
        "posted_by": "ANA LOPEZ",
        "posted_date": datetime(2026, 10, 2, 10, 0),
        "contract_type": "CONTRACT",
        "revenue": revenue,
        "profit": profit,
        "carrier_cost": None if revenue is None or profit is None else revenue - profit,
        "otp_on_time": True,
        "otd_on_time": False,
        "rc_count": 1,
    }


ROWS = [
    _row("A", 200.0, 50.0),       # Bruno's example order: 200 / 150 / 50
    _row("B", 200.0, 35.0),       # +15 scenario -> 200 / 150 / 50
    _row("C", 1_000.0, 100.0),
    _row("D", 200.0, None),       # McLeod has no margin
    _row("E", 199.999999, 49.999999),  # float noise around the example
]


def _orders(rows=ROWS, thresholds=None, **kwargs):
    pool = _StubPool(rows)
    orig_pool, orig_thresh = bs.get_datalake_gold_pool, bs._thresholds
    bs.get_datalake_gold_pool = lambda request: pool

    async def _stub_thresholds(request, order_ids):
        return thresholds if thresholds is not None else {}

    bs._thresholds = _stub_thresholds
    try:
        request = types.SimpleNamespace(app=types.SimpleNamespace(state=types.SimpleNamespace()))
        call = dict(
            range="mtd", start_date=None, end_date=None,
            contract_type=None, customer_name=None, posted_by=None,
            adjustment=0.0, sort="order_asc", page=1, limit=200,
        )
        call.update(kwargs)
        return asyncio.run(bs.orders(request=request, _user={}, **call))
    finally:
        bs.get_datalake_gold_pool, bs._thresholds = orig_pool, orig_thresh


def _ids(resp):
    return [r["order_id"] for r in resp["data"]["rows"]]


# --------------------------------------------------------------------------
# No filter = today's behaviour
# --------------------------------------------------------------------------


def test_no_filter_direct_call_returns_everything():
    """Guards the Annotated declarations — a FieldInfo default would filter."""
    resp = _orders()
    assert _ids(resp) == ["A", "B", "C", "D", "E"]
    assert resp["meta"]["total"] == resp["meta"]["unfiltered_total"] == 5
    assert resp["meta"]["filtered"] is False


def test_op_without_value_is_no_filter():
    assert _ids(_orders(revenue_op="eq")) == ["A", "B", "C", "D", "E"]


# --------------------------------------------------------------------------
# Bruno's three example filters
# --------------------------------------------------------------------------


def test_brunos_example_at_cents_catches_float_noise():
    resp = _orders(revenue_val=200, cost_val=150, profit_val=50)
    assert _ids(resp) == ["A", "E"]


def test_value_without_op_means_equals():
    assert _ids(_orders(revenue_val=1000)) == ["C"]


def test_filter_runs_on_the_scenario_adjusted_numbers():
    """At +15, order B shows 200 / 150 / 50 — it must match; A shows 65 profit."""
    resp = _orders(adjustment=15.0, cost_val=150, profit_val=50)
    assert _ids(resp) == ["B"]


@pytest.mark.parametrize(
    "kwargs,expected",
    [
        (dict(profit_op="gte", profit_val=50), ["A", "C", "E"]),
        (dict(profit_op="lte", profit_val=50), ["A", "B", "E"]),
        (dict(revenue_op="gte", revenue_val=500), ["C"]),
        (dict(cost_op="lte", cost_val=165), ["A", "B", "E"]),
    ],
)
def test_range_operators(kwargs, expected):
    assert _ids(_orders(**kwargs)) == expected


def test_null_amount_matches_nothing():
    """D has no profit/cost: not '$0', so '<= 50' must not catch it."""
    assert "D" not in _ids(_orders(profit_op="lte", profit_val=50))
    assert "D" not in _ids(_orders(cost_op="lte", cost_val=1e9))
    assert "D" in _ids(_orders(revenue_val=200))  # its revenue IS known


# --------------------------------------------------------------------------
# One population: rows, total and the Totals row (§96)
# --------------------------------------------------------------------------


def test_totals_and_count_span_the_filtered_rows():
    resp = _orders(revenue_val=200, cost_val=150, profit_val=50)
    rows, totals, meta = resp["data"]["rows"], resp["data"]["totals"], resp["meta"]
    assert meta["total"] == totals["orders"] == len(rows) == 2
    assert meta["unfiltered_total"] == 5 and meta["filtered"] is True
    assert totals["revenue"] == pytest.approx(sum(r["revenue"] for r in rows))
    assert totals["profit"] == pytest.approx(sum(r["profit"] for r in rows))
    assert totals["carrier_cost"] == pytest.approx(sum(r["carrier_cost"] for r in rows))
    assert totals["otd_pct"] == 0.0


def test_filtered_cost_saving_column_still_sums_to_its_totals_cell():
    """§109 holds inside the filtered population."""
    th = {"A": 300.0, "B": 100.0, "C": 950.0, "E": 160.0}
    resp = _orders(thresholds=th, revenue_val=200)
    rows, totals = resp["data"]["rows"], resp["data"]["totals"]
    assert {r["order_id"] for r in rows} == {"A", "B", "D", "E"}
    assert totals["cost_saving"] == pytest.approx(
        sum(r["cost_saving"] or 0.0 for r in rows)
    )


def test_pagination_counts_the_filtered_set():
    resp = _orders(limit=1, page=2, revenue_val=200)
    assert resp["meta"]["total"] == 4
    assert len(resp["data"]["rows"]) == 1


# --------------------------------------------------------------------------
# Validation
# --------------------------------------------------------------------------


@pytest.mark.parametrize("op", ["gt", "EQ", "=", "between", ""])
def test_unknown_op_is_a_400(op):
    with pytest.raises(HTTPException) as e:
        _orders(revenue_op=op, revenue_val=200)
    assert e.value.status_code == 400


def test_non_finite_value_is_a_400():
    with pytest.raises(HTTPException) as e:
        _orders(profit_val=float("nan"))
    assert e.value.status_code == 400


def test_endpoint_declares_every_filter_param():
    route = next(r for r in bs.router.routes if r.path.endswith("/orders"))
    declared = {p.name for p in route.dependant.query_params}
    for wire in ("revenue", "cost", "profit"):
        assert {f"{wire}_op", f"{wire}_val"} <= declared


# --------------------------------------------------------------------------
# Frontend wire contract (source scan)
# --------------------------------------------------------------------------


def test_frontend_sends_only_declared_params_and_keys_on_them():
    src = (_FRONTEND / "lib" / "booker-scorecard-api.ts").read_text()
    hook = src[src.index("export function useBookerOrders"):]
    hook = hook[: hook.index("\n}\n")]
    sent = set(re.findall(r"\b((?:revenue|cost|profit)_(?:op|val))\b", src))
    assert sent == {f"{w}_{k}" for w in ("revenue", "cost", "profit") for k in ("op", "val")}
    key = re.search(r"queryKey:\s*\[(.*?)\]", hook, re.S)
    assert key and "valueFilters" in key.group(1), "queryKey must cover the value filters"


def test_only_the_scenario_tab_renders_the_filter_bar():
    base = _FRONTEND / "app" / "reports" / "booker-performance-scorecard"
    scenario = (base / "ScenarioPanel.tsx").read_text()
    page = (base / "page.tsx").read_text()
    assert re.search(r"<OrdersTable[^>]*\bvalueFilterable\b", scenario)
    assert not re.search(r"<OrdersTable[^>]*\bvalueFilterable\b", page)
