"""Booker Performance Scorecard — Bruno PDF 2026-10-16 ("space -- Booker
Performance Scorecard").

  R1  "Delete" the Revenue 200 / Carrier Cost 150 / Profit 50 orders — from the
      KPIs, Rank and Scenario. McLeod is read-only to us, so it joins the other
      placeholder pairs in the ONE rate-conf CTE every endpoint builds from.
  R2  New Orders column "Cost Overrun" = Threshold − Carrier Cost when that is
      negative, else "—". Sortable like the other columns, summed in Totals.
"""

from __future__ import annotations

import re

import pytest

from app.routers import booker_scorecard as bs
from tests.test_booker_scorecard_bruno_2026_09_15 import _orders, _row


# --------------------------------------------------------------------------
# R1 — the 200/150 placeholder pair
# --------------------------------------------------------------------------


def _rate_conf_sql() -> str:
    """The rate-conf CTE text, from the module source (the SQL is built by an
    f-string inside a helper, so read the source the way the 08-31 test does)."""
    import inspect

    return inspect.getsource(bs)


def test_the_200_150_pair_is_excluded_null_safely():
    """Row-wise IS DISTINCT FROM, never `NOT (a = 200 AND b = 150)` — the NOT
    form evaluates to NULL for an order whose revenue has not posted and
    silently deletes it (see the 08-31 test)."""
    src = _rate_conf_sql()
    assert re.search(
        r"\(br\.total_charge,\s*br\.total_charge\s*-\s*br\.margin_amt\)\s*"
        r"IS\s+DISTINCT\s+FROM\s*\(200::numeric,\s*150::numeric\)",
        src,
        re.S,
    ), "the 200/150 placeholder pair must be excluded in the rate-conf CTE"


def test_all_placeholder_pairs_live_in_one_cte():
    """One CTE ⇒ KPI cards, Orders, Rank, Rank Last Week and Scenario cannot
    disagree about which orders exist (§16/§96). A second copy of the pair
    anywhere else in the module would mean a second population."""
    src = _rate_conf_sql()
    hits = re.findall(r"IS\s+DISTINCT\s+FROM\s*\(200::numeric,\s*150::numeric\)", src)
    assert len(hits) == 1


# --------------------------------------------------------------------------
# R2 — Cost Overrun
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "threshold,cost,expected",
    [
        (9_000.0, 9_500.0, -500.0),  # over -> the (negative) overrun
        (9_000.0, 8_000.0, None),    # under -> that's a saving, not an overrun
        (9_000.0, 9_000.0, None),    # exactly ON -> result 0 -> "—"
        (None, 9_500.0, None),       # no threshold typed
        (9_000.0, None, None),       # no carrier cost
    ],
)
def test_row_cost_overrun(threshold, cost, expected):
    assert bs._row_cost_overrun(threshold, cost) == expected


def test_overrun_and_saving_are_disjoint_per_row():
    rows = [
        _row("A", revenue=10_000.0, profit=2_000.0),  # cost 8,000 vs 9,000 -> saving
        _row("B", revenue=10_000.0, profit=500.0),    # cost 9,500 vs 9,000 -> overrun
        _row("C", revenue=10_000.0, profit=1_000.0),  # on threshold -> neither
    ]
    _, data = _orders(rows, {"A": 9_000.0, "B": 9_000.0, "C": 9_000.0})
    by_id = {r["order_id"]: r for r in data["rows"]}
    assert by_id["A"]["cost_saving"] == pytest.approx(1_000.0)
    assert by_id["A"]["cost_overrun"] is None
    assert by_id["B"]["cost_saving"] is None
    assert by_id["B"]["cost_overrun"] == pytest.approx(-500.0)
    assert by_id["C"]["cost_saving"] is None and by_id["C"]["cost_overrun"] is None


def test_totals_overrun_sums_the_full_universe_not_the_page():
    """§44 — the Totals cell spans every matching order, even past page 1."""
    rows = [
        _row("A", revenue=10_000.0, profit=500.0),   # -500
        _row("B", revenue=10_000.0, profit=-1_000.0),  # cost 11,000 -> -2,000
        _row("C", revenue=10_000.0, profit=2_000.0),  # saving, contributes 0
    ]
    _, data = _orders(rows, {"A": 9_000.0, "B": 9_000.0, "C": 9_000.0}, limit=1)
    assert len(data["rows"]) == 1
    assert data["totals"]["cost_overrun"] == pytest.approx(-2_500.0)


def test_overrun_total_is_none_when_threshold_source_is_down():
    """A $0 would claim "nobody went over"; a dead AP source is not that."""
    _, data = _orders([_row("A")], None)
    assert data["totals"]["cost_overrun"] is None
    assert data["rows"][0]["cost_overrun"] is None


def test_overrun_sorts_nulls_last_both_ways():
    rows = [
        _row("A", revenue=10_000.0, profit=500.0),     # -500
        _row("B", revenue=10_000.0, profit=-1_000.0),  # -2,000
        _row("C", revenue=10_000.0, profit=2_000.0),   # None
    ]
    th = {"A": 9_000.0, "B": 9_000.0, "C": 9_000.0}
    _, asc = _orders(rows, th, sort="overrun_asc")
    _, desc = _orders(rows, th, sort="overrun_desc")
    assert [r["order_id"] for r in asc["rows"]] == ["B", "A", "C"]
    assert [r["order_id"] for r in desc["rows"]] == ["A", "B", "C"]
