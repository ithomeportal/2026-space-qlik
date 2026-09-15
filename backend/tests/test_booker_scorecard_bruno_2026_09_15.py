"""Booker Performance Scorecard — Bruno PDF 2026-09-15 (Scorecard tab, Orders table).

Three requests:

* **R1** a "Cost Savings" column at the end of the table
* **R2** a "Threshold Variance %" column right after it, = Carrier Cost / Threshold
* **R3** sorting on EVERY column

R1 and R2 are per-order legs of figures that until now existed only as
full-universe aggregates, so the tests that matter are the reconciliation ones:
the column must sum to the KPI card above it.

R3 is the structural one. Three of the fourteen columns come from a different
database and are merged in Python, so `ORDER BY` cannot reach them; sorting
moved out of SQL entirely and pagination now follows it. These tests pin the
consequences — nulls last in BOTH directions, one scan not two, and a page
boundary that does not shuffle.
"""

from __future__ import annotations

import asyncio
import inspect
import re
import types
from datetime import date, datetime
from pathlib import Path

import pytest
from fastapi import HTTPException

from app.routers import booker_scorecard as bs


# --------------------------------------------------------------------------
# Harness
# --------------------------------------------------------------------------


class _StubPool:
    def __init__(self, rows=None):
        self.sqls: list[str] = []
        self.rows = rows or []

    async def fetch(self, sql, *params):
        self.sqls.append(sql)
        return list(self.rows)

    async def fetchrow(self, sql, *params):
        self.sqls.append(sql)
        return self.rows[0] if self.rows else None


def _row(
    order_id: str,
    *,
    revenue=10_000.0,
    profit=1_000.0,
    team="TM1",
    customer="ACME",
    posted_by="ANA LOPEZ",
    posted_date=datetime(2026, 9, 2, 10, 0),
    otp=True,
    otd=True,
    rc_count=1,
):
    """One `base` CTE row, carrier cost derived exactly as the SQL derives it."""
    return {
        "order_id": order_id,
        "team": team,
        "customer": customer,
        "posted_by": posted_by,
        "posted_date": posted_date,
        "contract_type": "CONTRACT",
        "revenue": revenue,
        "profit": profit,
        "carrier_cost": None if revenue is None or profit is None else revenue - profit,
        "otp_on_time": otp,
        "otd_on_time": otd,
        "rc_count": rc_count,
    }


_SCOPE = dict(contract_type=None, customer_name=None, posted_by=None)
_DATED = dict(range="mtd", start_date=None, end_date=None, **_SCOPE)


def _orders(rows, thresholds, **kwargs):
    """Drive `/orders` against a stub pool. Returns (pool, payload)."""
    pool = _StubPool(rows)
    orig_pool = bs.get_datalake_gold_pool
    orig_thresh = bs._thresholds
    bs.get_datalake_gold_pool = lambda request: pool

    async def _stub_thresholds(request, order_ids):
        return thresholds

    bs._thresholds = _stub_thresholds
    try:
        request = types.SimpleNamespace(
            app=types.SimpleNamespace(state=types.SimpleNamespace())
        )
        call = dict(_DATED, adjustment=0.0, sort="posted_desc", page=1, limit=200)
        call.update(kwargs)
        resp = asyncio.run(bs.orders(request=request, _user={}, **call))
    finally:
        bs.get_datalake_gold_pool = orig_pool
        bs._thresholds = orig_thresh
    return pool, resp["data"]


# --------------------------------------------------------------------------
# R1 — the per-order Cost Savings column
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "threshold,cost,expected",
    [
        (9_000.0, 8_000.0, 1_000.0),  # under  -> the saving
        (9_000.0, 9_500.0, None),     # broken -> not a negative saving
        (9_000.0, 9_000.0, None),     # exactly ON -> neither broken nor saving
        (None, 8_000.0, None),        # no threshold typed in AP_module
        (9_000.0, None, None),        # McLeod has no margin for this order
    ],
)
def test_row_cost_saving(threshold, cost, expected):
    assert bs._row_cost_saving(threshold, cost) == expected


def test_cost_savings_column_sums_to_the_kpi_card():
    """§16 — the column and the Cost Saving KPI describe one population.

    The asymmetry in `_row_cost_saving` (em-dash for broken orders rather than
    a negative saving) exists to make exactly this true. If a later round
    "improves" the column to show a signed variance, this goes red.
    """
    rows = [
        _row("A", revenue=10_000.0, profit=2_000.0),  # cost 8,000 vs 9,000 -> saves 1,000
        _row("B", revenue=10_000.0, profit=500.0),    # cost 9,500 vs 9,000 -> broken
        _row("C", revenue=10_000.0, profit=1_000.0),  # cost 9,000 vs 9,000 -> on threshold
        _row("D", revenue=10_000.0, profit=3_000.0),  # cost 7,000 vs 9,000 -> saves 2,000
        _row("E", revenue=10_000.0, profit=1_500.0),  # no threshold at all
    ]
    thresholds = {"A": 9_000.0, "B": 9_000.0, "C": 9_000.0, "D": 9_000.0}
    _, data = _orders(rows, thresholds)

    per_row = sum(r["cost_saving"] or 0.0 for r in data["rows"])
    assert per_row == pytest.approx(3_000.0)
    assert data["totals"]["cost_saving"] == pytest.approx(per_row)
    assert data["totals"]["under_threshold"] == 2


def test_broken_orders_keep_their_own_flag():
    """The em-dash hides nothing: `threshold` still rides on the row, which is
    what the (amber) Threshold cell reads to mark an order broken."""
    rows = [_row("B", revenue=10_000.0, profit=500.0)]
    _, data = _orders(rows, {"B": 9_000.0})
    row = data["rows"][0]
    assert row["cost_saving"] is None
    assert row["threshold"] == 9_000.0
    assert row["carrier_cost"] > row["threshold"]
    assert data["totals"]["broken_threshold"] == 1


# --------------------------------------------------------------------------
# R2 — Threshold Variance % = Carrier Cost / Threshold
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "threshold,cost,expected",
    [
        (10_000.0, 9_400.0, 0.94),   # 94% of threshold
        (10_000.0, 10_600.0, 1.06),  # 6% over
        (10_000.0, 10_000.0, 1.0),   # exactly on
        (0.0, 5_000.0, None),        # never ZeroDivisionError
        (None, 5_000.0, None),
        (10_000.0, None, None),
    ],
)
def test_row_threshold_variance(threshold, cost, expected):
    got = bs._row_threshold_variance(threshold, cost)
    if expected is None:
        assert got is None
    else:
        assert got == pytest.approx(expected)


def test_threshold_variance_is_a_fraction_not_a_percentage():
    """⚠ `fmtPct` multiplies by 100 on the way out. Handing it an already-scaled
    value prints 100× wrong with no error anywhere (§95)."""
    rows = [_row("A", revenue=10_000.0, profit=600.0)]  # cost 9,400
    _, data = _orders(rows, {"A": 10_000.0})
    assert data["rows"][0]["threshold_variance_pct"] == pytest.approx(0.94)
    assert data["totals"]["threshold_variance_pct"] == pytest.approx(0.94)


def test_totals_variance_is_weighted_not_a_mean_of_ratios():
    """Σcost / Σthreshold, so a $900 order cannot outvote a $9,000 one.

    The mean of the two per-order ratios here is 0.75; the weighted ratio is
    0.9818. A totals cell showing 75% under a table whose big order came in at
    99% of threshold is the §96 failure this pins.
    """
    rows = [
        _row("BIG", revenue=20_000.0, profit=200.0),   # cost 19,800 / 20,000 = 0.99
        _row("SMALL", revenue=1_000.0, profit=500.0),  # cost    500 /  1,000 = 0.50
    ]
    _, data = _orders(rows, {"BIG": 20_000.0, "SMALL": 1_000.0})

    ratios = [r["threshold_variance_pct"] for r in data["rows"]]
    assert sorted(ratios) == pytest.approx([0.5, 0.99])
    mean_of_ratios = sum(ratios) / len(ratios)
    weighted = (19_800.0 + 500.0) / (20_000.0 + 1_000.0)
    assert data["totals"]["threshold_variance_pct"] == pytest.approx(weighted)
    assert data["totals"]["threshold_variance_pct"] != pytest.approx(mean_of_ratios)


def test_totals_variance_spans_the_comparable_population_only():
    """The same orders `cost_saving` and `compliance_threshold_pct` run over —
    an order with no threshold must not drag the denominator (§96)."""
    rows = [
        _row("A", revenue=10_000.0, profit=1_000.0),   # cost 9,000, thresh 10,000
        _row("NOPE", revenue=50_000.0, profit=100.0),  # cost 49,900, NO threshold
    ]
    _, data = _orders(rows, {"A": 10_000.0})
    assert data["totals"]["threshold_orders"] == 1
    assert data["totals"]["threshold_variance_pct"] == pytest.approx(0.9)


def test_ap_outage_yields_none_never_zero():
    """⚠ A zero here reads as "every order came in free". `_thresholds`
    returning None means the source is DOWN, which is not the same answer as
    "no order has a threshold"."""
    rows = [_row("A"), _row("B")]
    _, data = _orders(rows, None)
    assert data["thresholds_available"] is False
    for key in ("cost_saving", "threshold_variance_pct", "compliance_threshold_pct"):
        assert data["totals"][key] is None, key
    for r in data["rows"]:
        assert r["threshold"] is None
        assert r["cost_saving"] is None
        assert r["threshold_variance_pct"] is None


# --------------------------------------------------------------------------
# R3 — sorting on every column
# --------------------------------------------------------------------------


def test_every_rendered_column_has_a_sort_key():
    """Bruno asked for ALL columns. The table renders 14; each needs an
    asc/desc pair the backend actually understands."""
    fields = {field for field, _ in bs._ORDERS_SORT.values()}
    expected = {
        "order_id", "team", "customer", "posted_by", "posted_date", "rc_count",
        "revenue", "carrier_cost", "profit", "otp_on_time", "otd_on_time",
        "threshold", "cost_saving", "threshold_variance_pct",
    }
    assert fields == expected
    # Every key comes as a matched asc/desc pair, or a header renders an arrow
    # it cannot act on.
    for field in fields:
        dirs = {desc for f, desc in bs._ORDERS_SORT.values() if f == field}
        assert dirs == {True, False}, f"{field} is missing a direction"


def test_unknown_sort_is_a_400_not_a_silent_fallback():
    """⚠ The old `_ORDERS_SORT.get(sort, posted_desc)` meant a token that
    existed on only ONE side of the wire still rendered a plausible table: the
    frontend painted ▼ on a column the server never sorted by, and nothing
    failed. A drift must be visible."""
    with pytest.raises(HTTPException) as exc:
        _orders([_row("A")], {}, sort="margin_desc")
    assert exc.value.status_code == 400
    assert "sort must be one of" in exc.value.detail


_TSX = (
    Path(__file__).resolve().parents[2]
    / "frontend/app/reports/booker-performance-scorecard/OrdersTable.tsx"
)


def test_orders_sort_whitelist_matches_frontend():
    """The two lists are one contract. There is no JS test runner here, so the
    guard reads the TSX (§107)."""
    src = _TSX.read_text()
    block = re.search(r"const SORTS[^=]*=\s*\{(.*?)\n\}", src, re.S)
    assert block, "could not find the SORTS map in OrdersTable.tsx"
    used = set(re.findall(r'"([a-z_]+(?:_asc|_desc))"', block.group(1)))
    assert used, "parsed no sort tokens — the guard would pass vacuously"
    unknown = used - set(bs._ORDERS_SORT)
    assert not unknown, f"frontend sorts the backend rejects: {sorted(unknown)}"
    assert used == set(bs._ORDERS_SORT), (
        f"backend keys no column offers: {sorted(set(bs._ORDERS_SORT) - used)}"
    )


@pytest.mark.parametrize("column", ["threshold", "cost_saving", "threshold_variance_pct"])
@pytest.mark.parametrize("direction", ["asc", "desc"])
def test_nulls_sort_last_in_both_directions(column, direction):
    """⚠ The bug this exists for: a `?? +Infinity` sentinel sorts nulls last
    ASCENDING and FIRST descending. Only ~61% of DFW bookings carry a
    threshold, so these three columns are null on ~2 rows in 5 — a sentinel
    would put the least-informative rows on top of the default view.
    """
    token = {
        "threshold": "threshold",
        "cost_saving": "saving",
        "threshold_variance_pct": "variance",
    }[column]
    rows = [
        _row("A", revenue=10_000.0, profit=2_000.0),
        _row("NULL1", revenue=10_000.0, profit=1_000.0),
        _row("B", revenue=10_000.0, profit=3_000.0),
        _row("NULL2", revenue=10_000.0, profit=1_500.0),
    ]
    _, data = _orders(rows, {"A": 9_000.0, "B": 9_000.0}, sort=f"{token}_{direction}")
    values = [r[column] for r in data["rows"]]
    seen_null = False
    for v in values:
        if v is None:
            seen_null = True
        else:
            assert not seen_null, f"{column} {direction} put a null above a value"
    assert values[-1] is None and values[-2] is None


def test_sort_ties_break_on_order_id_desc():
    """OTP/OTD are two distinct values across thousands of rows, so almost the
    whole table is a tie. Without a deterministic tiebreak a page boundary
    shuffles between two identical requests and rows vanish from both pages."""
    rows = [_row(o, otp=True) for o in ("0001", "0003", "0002", "0004")]
    _, data = _orders(rows, {}, sort="otp_desc")
    assert [r["order_id"] for r in data["rows"]] == ["0004", "0003", "0002", "0001"]


def test_pagination_follows_the_sort():
    """The page is a slice of the SORTED universe, not of the SQL order.

    Sorting a page-local slice would make page 2 re-show rows from page 1.
    """
    rows = [
        _row(f"{i:04d}", revenue=10_000.0, profit=float(i) * 100.0) for i in range(1, 11)
    ]
    _, p1 = _orders(rows, {}, sort="profit_desc", page=1, limit=4)
    _, p2 = _orders(rows, {}, sort="profit_desc", page=2, limit=4)
    _, p3 = _orders(rows, {}, sort="profit_desc", page=3, limit=4)

    got = [r["profit"] for r in p1["rows"] + p2["rows"] + p3["rows"]]
    assert got == sorted(got, reverse=True)
    assert len(got) == 10 == len(set(got))
    assert p1["totals"]["orders"] == 10, "totals stay full-universe (§44)"


def test_orders_makes_exactly_one_datalake_scan():
    """⚠ `mcleod_gld_order_post_hist` is 1.9M rows with no usable index — each
    execution of the base CTE is a ~2-3s seq scan. Serving the page from the
    full-universe pass the Totals row already needed took this endpoint from
    two scans to one; a later round re-adding a paged query silently doubles
    the latency of the report's slowest endpoint.
    """
    pool, _ = _orders([_row("A")], {})
    assert len(pool.sqls) == 1, f"expected 1 datalake scan, made {len(pool.sqls)}"


# --------------------------------------------------------------------------
# Interaction with the Scenario tab
# --------------------------------------------------------------------------


def test_scenario_feeds_the_adjusted_cost_into_both_new_columns():
    """The scenario lowers carrier cost, so an order can cross its threshold.

    This is precisely why the two columns are computed in Python after
    `_apply_scenario` rather than in SQL: at step 0 the order is broken, at
    step 15 it is saving, and the variance must move with it.
    """
    rows = [_row("A", revenue=10_000.0, profit=990.0)]  # cost 9,010 vs 9,000
    _, base = _orders(rows, {"A": 9_000.0}, adjustment=0.0)
    _, lifted = _orders(rows, {"A": 9_000.0}, adjustment=15.0)

    assert base["rows"][0]["cost_saving"] is None  # broken by $10
    assert base["rows"][0]["threshold_variance_pct"] == pytest.approx(9_010 / 9_000)

    assert lifted["rows"][0]["carrier_cost"] == pytest.approx(8_995.0)
    assert lifted["rows"][0]["cost_saving"] == pytest.approx(5.0)
    assert lifted["rows"][0]["threshold_variance_pct"] == pytest.approx(8_995 / 9_000)
    assert lifted["totals"]["cost_saving"] == pytest.approx(5.0)


def test_step_zero_is_still_the_identity():
    """Round 2's invariant, re-pinned now that the code path changed shape."""
    rows = [_row("A"), _row("B", revenue=5_000.0, profit=250.0)]
    _, none = _orders(rows, {"A": 9_500.0}, adjustment=None)
    _, zero = _orders(rows, {"A": 9_500.0}, adjustment=0.0)
    assert none == zero


def test_revenue_stays_invariant_under_every_step():
    rows = [_row("A"), _row("B", revenue=5_000.0, profit=250.0)]
    _, base = _orders(rows, {}, adjustment=0.0)
    for step in bs.SCENARIO_STEPS:
        _, moved = _orders(rows, {}, adjustment=float(step))
        assert moved["totals"]["revenue"] == pytest.approx(base["totals"]["revenue"])


# --------------------------------------------------------------------------
# Structural guards
# --------------------------------------------------------------------------


def test_the_two_new_columns_have_exactly_one_definition_each():
    """§69. A second call site is fine; a reimplementation is not."""
    src = Path(bs.__file__).read_text()
    for name in ("_row_cost_saving", "_row_threshold_variance"):
        assert src.count(f"def {name}(") == 1

    outside = src
    for fn in (bs._row_cost_saving, bs._row_threshold_variance, bs._threshold_stats):
        outside = outside.replace(inspect.getsource(fn), "")
    assert "cost / threshold" not in outside
    assert "threshold - cost" not in outside


def test_sort_helper_never_substitutes_a_sentinel():
    """Partitioning, not `?? Infinity` — which also keeps the comparison
    type-clean, so no float sentinel ever meets a date string or a bool."""
    # The docstring NAMES the sentinel bug it exists to prevent, so scan the
    # body only — otherwise the guard goes red for explaining itself.
    src = inspect.getsource(bs._sort_orders).replace(bs._sort_orders.__doc__, "")
    assert "inf" not in src.lower()
    assert "is not None" in src and "is None" in src
