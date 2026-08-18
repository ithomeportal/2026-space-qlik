"""Booker Performance Scorecard — scenario what-if + threshold arithmetic.

Bruno PDF 2026-08-18: a "Scenario" tab whose 15 / 25 / 50 buttons re-state the
whole report with profit raised and carrier cost cut by that amount, plus a
"Cost Saving" KPI and Broken Threshold expressed as a percentage.

The report shipped (2026-08-10) with NO tests at all — its verification was a
one-off live replay that was never committed. These are offline: they drive the
helpers directly and need no database.

The properties worth pinning:

  * revenue is INVARIANT under a scenario (the two deltas cancel by
    construction) — if that ever breaks, the tab is silently modelling a price
    rise instead of a cost saving;
  * adjustment 0 is the IDENTITY, so the Scenario tab at zero and the Scorecard
    tab cannot drift apart (§69);
  * "broken" and "cost saving" share one comparable set;
  * an AP outage yields None everywhere, never a zero that reads as good news.
"""

from __future__ import annotations

import pytest
from fastapi import HTTPException

from app.routers import booker_scorecard as bs


def _row(order_id: str, revenue, profit):
    """A base-CTE row: carrier_cost is derived exactly as the SQL derives it."""
    cost = None if (revenue is None or profit is None) else revenue - profit
    return {
        "order_id": order_id,
        "revenue": revenue,
        "profit": profit,
        "carrier_cost": cost,
        "otp_on_time": True,
        "otd_on_time": True,
    }


# --------------------------------------------------------------------------
# _apply_scenario
# --------------------------------------------------------------------------


def test_zero_adjustment_is_the_identity() -> None:
    """Scenario at 0 must return the very same objects, not equal-looking ones."""
    rows = [_row("A", 1000.0, 200.0)]
    assert bs._apply_scenario(rows, 0.0) is rows


def test_profit_rises_and_carrier_cost_falls_by_the_step() -> None:
    out = bs._apply_scenario([_row("A", 1000.0, 200.0)], 25.0)
    assert out[0]["profit"] == 225.0
    assert out[0]["carrier_cost"] == 775.0


def test_revenue_is_invariant_under_every_step() -> None:
    """The defining property: +delta on profit, −delta on cost, revenue fixed."""
    for step in bs.SCENARIO_STEPS:
        out = bs._apply_scenario([_row("A", 1000.0, 200.0)], step)
        assert out[0]["revenue"] == 1000.0, f"step {step} moved revenue"
        # and the identity carrier_cost == revenue - profit still holds
        assert out[0]["revenue"] - out[0]["profit"] == out[0]["carrier_cost"]


def test_nulls_are_not_fabricated() -> None:
    """An order McLeod has no margin for must not gain one from a scenario."""
    out = bs._apply_scenario([_row("A", None, None)], 50.0)
    assert out[0]["profit"] is None
    assert out[0]["carrier_cost"] is None


def test_scenario_does_not_mutate_the_input_rows() -> None:
    rows = [_row("A", 1000.0, 200.0)]
    bs._apply_scenario(rows, 50.0)
    assert rows[0]["profit"] == 200.0, "the source rows were mutated in place"


# --------------------------------------------------------------------------
# _resolve_adjustment — whitelist
# --------------------------------------------------------------------------


@pytest.mark.parametrize("value", [None, 0, 15, 25, 50, 15.0])
def test_whitelisted_adjustments_are_accepted(value) -> None:
    assert bs._resolve_adjustment(value) in bs.ALLOWED_ADJUSTMENTS


@pytest.mark.parametrize("value", [1, -15, 17.5, 500, 49.99])
def test_arbitrary_adjustments_are_rejected(value) -> None:
    """A hand-crafted URL must not be able to render a fictional scenario."""
    with pytest.raises(HTTPException) as exc:
        bs._resolve_adjustment(value)
    assert exc.value.status_code == 400


# --------------------------------------------------------------------------
# _threshold_stats — broken %, cost saving
# --------------------------------------------------------------------------


def test_broken_counts_only_costs_strictly_over_threshold() -> None:
    rows = [
        _row("over", 1000.0, 100.0),   # cost 900 > 800  -> broken
        _row("under", 1000.0, 400.0),  # cost 600 < 800  -> saving 200
        _row("equal", 1000.0, 200.0),  # cost 800 == 800 -> neither
    ]
    stats = bs._threshold_stats(rows, {"over": 800.0, "under": 800.0, "equal": 800.0})
    assert stats["broken_threshold"] == 1
    assert stats["under_threshold"] == 1
    assert stats["threshold_orders"] == 3
    assert stats["cost_saving"] == 200.0


def test_broken_pct_is_over_comparable_orders_not_all_orders() -> None:
    """Only 61% of DFW bookings carry a threshold; all-orders would understate."""
    rows = [
        _row("a", 1000.0, 100.0),  # cost 900 > 800 -> broken
        _row("b", 1000.0, 400.0),  # cost 600 < 800
        _row("c", 1000.0, 400.0),  # no threshold at all
    ]
    stats = bs._threshold_stats(rows, {"a": 800.0, "b": 800.0})
    assert stats["threshold_orders"] == 2
    assert stats["broken_threshold_pct"] == 0.5


def test_orders_missing_either_number_leave_both_sides_alone() -> None:
    rows = [_row("nocost", None, None)]
    stats = bs._threshold_stats(rows, {"nocost": 800.0})
    assert stats["threshold_orders"] == 0
    assert stats["broken_threshold_pct"] is None
    assert stats["cost_saving"] == 0.0


def test_ap_outage_yields_none_never_zero() -> None:
    """A zero here would read as 'nothing was over budget' — the opposite."""
    stats = bs._threshold_stats([_row("a", 1000.0, 100.0)], None)
    assert set(stats.values()) == {None}


# --------------------------------------------------------------------------
# The two features composed: a scenario must move both threshold sides
# --------------------------------------------------------------------------


def test_scenario_converts_broken_orders_into_savings() -> None:
    """The point of the tab: shaving carrier pay un-breaks marginal orders."""
    rows = [_row("a", 1000.0, 190.0)]  # cost 810, threshold 800 -> broken
    thresholds = {"a": 800.0}

    before = bs._threshold_stats(rows, thresholds)
    assert before["broken_threshold"] == 1
    assert before["cost_saving"] == 0.0

    after = bs._threshold_stats(bs._apply_scenario(rows, 25.0), thresholds)
    assert after["broken_threshold"] == 0
    assert after["threshold_orders"] == 1, "the denominator must not move"
    assert after["cost_saving"] == pytest.approx(15.0)  # 800 - (810 - 25)


def test_margin_recomputes_off_the_adjusted_rows() -> None:
    """Margin % is Σprofit/Σrevenue — a ratio of sums, over the adjusted set."""
    rows = [_row("a", 1000.0, 100.0), _row("b", 1000.0, 300.0)]
    adjusted = bs._apply_scenario(rows, 50.0)
    profit = sum(r["profit"] for r in adjusted)
    revenue = sum(r["revenue"] for r in adjusted)
    assert profit == 500.0            # 400 + 2 x 50
    assert revenue == 2000.0          # unchanged
    assert profit / revenue == 0.25   # was 0.20


def test_summary_and_orders_share_one_threshold_definition() -> None:
    """Both endpoints must fold the SAME helper — §69, one metric one definition."""
    src = open(bs.__file__).read()
    assert src.count("_threshold_stats(") == 3, (
        "expected one definition + exactly two call sites (/summary, /orders); "
        "a third caller means a metric is being recomputed somewhere else"
    )
    assert src.count("_apply_scenario(") == 4, (
        "expected one definition + three call sites (/summary rows, /orders "
        "page rows, /orders full universe)"
    )
