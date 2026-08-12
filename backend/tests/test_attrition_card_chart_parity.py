"""The Customer Attrition CARD and the Customer Attrition CHART must agree.

This report has produced three "two numbers disagree on one screen" defects in
ten days, all in the same seam between `/summary` (the card) and
`/customer-attrition` (the chart):

* **R17 (2026-08-03)** — the card moved to a per-week-average L8W (35.25) while
  the chart kept a union-distinct count (55). Card and chart legend disagreed.
* **R18 (2026-08-05)** — same denominator split, plus the chart plotted
  `1 − ratio` where Bruno's arithmetic was the ratio: card 31 / 35.4 vs chart
  43.64%. AND `/customer-attrition` did not declare `sub_team`, so a TM1..TM4
  pill scoped the card but not the chart — FastAPI silently DROPS undeclared
  query params, so there was no error, just two disagreeing numbers.
* **R19 (2026-08-12)** — chart flipped back to `1 − ratio`, which is
  *algebraically the card's own `% Δ` cell*. That identity is now the invariant
  worth pinning: `1 − chart.ratio == card.pct`.

Each round was verified by a hand-written replay script that was then thrown
away, so the next round re-derived the same checks from scratch. These tests are
that replay, kept.

**Scope of what is proven here.** The fast tests below stub the pool, so they
verify the *Python* half — the fixed `/8.0` divisor, the ratio, `_attr_diff`,
and the route signatures. They deliberately do NOT verify the SQL; per this
repo's convention the SQL is proven by replaying it against the live DB (see
`test_live_card_chart_parity`, which does exactly that when a real
`SAVINGS_DATABASE_URL` is present).
"""

import inspect
import os
from datetime import date

import pytest

from app.routers import attrition_wow as aw

# Real observed weekly distinct-customer counts (2026-08-03, TEAM-DFW): the 8
# weeks preceding the last completed week, then the last completed week itself.
# Chosen from real data so the numbers in the assertions match the ones in the
# spec and the Bruno PDFs: 282 / 8 = 35.25 against an LW of 31.
PRIOR_8_WEEKS = (35, 36, 31, 38, 34, 36, 37, 35)
DEN_SUM = sum(PRIOR_8_WEEKS)          # 282
LW_CUSTOMERS = 31
EXPECTED_L8W = DEN_SUM / 8.0          # 35.25


# --------------------------------------------------------------------------
# Fakes — one pool serving both endpoints from the SAME underlying weekly
# counts, which is the whole point: if the two endpoints derive different
# numbers from identical inputs, that is the bug this file exists to catch.
# --------------------------------------------------------------------------


class _FakePool:
    """Serves `/summary`'s single fetchrow and `/customer-attrition`'s fetch."""

    def __init__(self):
        self.summary_row = {
            "l8w_customers_sum": DEN_SUM,
            "lw_customers": LW_CUSTOMERS,
            # Lanes + money columns are not under test; any non-null value that
            # keeps the endpoint's arithmetic defined will do.
            "l8w_lanes_sum": 160,
            "lw_lanes": 18,
            "l8w_loads": 800, "l8w_rev": 1_600_000.0, "l8w_profit": 240_000.0,
            "lw_loads": 95,   "lw_rev": 190_000.0,    "lw_profit": 28_000.0,
            "l2w_loads": 200, "l2w_rev": 400_000.0,   "l2w_profit": 60_000.0,
        }
        # 9 weeks: 8 priors then the last completed week. `den_sum` on the final
        # row is the SUM of the 8 before it — the same 282 the card reads.
        self.chart_rows = [
            {"ws": date(2026, 6, 1), "num_cust": PRIOR_8_WEEKS[0], "den_sum": 0},
            {"ws": date(2026, 6, 8), "num_cust": PRIOR_8_WEEKS[1], "den_sum": 0},
            {"ws": date(2026, 6, 15), "num_cust": PRIOR_8_WEEKS[2], "den_sum": 0},
            {"ws": date(2026, 6, 22), "num_cust": PRIOR_8_WEEKS[3], "den_sum": 0},
            {"ws": date(2026, 6, 29), "num_cust": PRIOR_8_WEEKS[4], "den_sum": 0},
            {"ws": date(2026, 7, 6), "num_cust": PRIOR_8_WEEKS[5], "den_sum": 0},
            {"ws": date(2026, 7, 13), "num_cust": PRIOR_8_WEEKS[6], "den_sum": 0},
            {"ws": date(2026, 7, 20), "num_cust": PRIOR_8_WEEKS[7], "den_sum": 0},
            {"ws": date(2026, 7, 27), "num_cust": LW_CUSTOMERS, "den_sum": DEN_SUM},
        ]

    async def fetchrow(self, *_a, **_kw):
        return self.summary_row

    async def fetch(self, *_a, **_kw):
        return self.chart_rows


class _FakeRequest:
    def __init__(self, pool):
        self.app = type("_App", (), {"state": type("_S", (), {"savings_pool": pool})()})()


class _FakeResponse:
    def __init__(self):
        self.headers: dict = {}


# ⚠ Calling an endpoint function directly bypasses FastAPI's dependency
# resolution, so any param left unpassed keeps its `Query(None)` DEFAULT OBJECT
# rather than becoming None — `_parse_csv` then blows up on
# `'Query' object has no attribute 'split'`. Every param must be forwarded
# explicitly (SPEC-CODE-RULES §40). These helpers are the single place that
# knows the full param list, so a new param breaks them loudly instead of
# silently reaching the SQL as a Query object.
CARD_PARAMS = dict(
    teams=None, customer=None, contract=None, lane=None, view=None, sub_team=None
)
CHART_PARAMS = {**CARD_PARAMS, "weeks": 15}


async def _card(pool, **scope):
    res = await aw.summary(
        _FakeRequest(pool), _FakeResponse(), _user={}, **{**CARD_PARAMS, **scope}
    )
    return res["data"]


async def _chart(pool, **scope):
    res = await aw.customer_attrition(
        _FakeRequest(pool), _FakeResponse(), _user={}, **{**CHART_PARAMS, **scope}
    )
    return res["data"]


# --------------------------------------------------------------------------
# 1. Route-signature parity — the R18 `sub_team` defect, made unrepeatable.
# --------------------------------------------------------------------------

# Everything that narrows WHICH ROWS an endpoint sees. If a future round adds a
# scope filter to the card, the chart must gain it in the same commit or the two
# silently diverge (FastAPI drops params an endpoint does not declare — the
# failure is an empty/unscoped chart, never a 4xx). See SPEC-CODE-RULES §55.
SCOPE_PARAMS = {"teams", "customer", "contract", "lane", "view", "sub_team"}


def _params(fn) -> set:
    return set(inspect.signature(fn).parameters)


def test_chart_declares_every_scope_param_the_card_declares():
    card = _params(aw.summary)
    chart = _params(aw.customer_attrition)

    missing = (card & SCOPE_PARAMS) - chart
    assert not missing, (
        f"/customer-attrition is missing scope param(s) {sorted(missing)} that "
        "/summary declares. FastAPI DROPS undeclared query params silently, so "
        "the card would be scoped and the chart would not — the R18 bug."
    )


def test_scope_param_list_is_still_complete():
    """Catches a NEW filter added to both endpoints but not to SCOPE_PARAMS.

    Without this, the parity test above would keep passing while quietly
    checking a stale list.
    """
    undeclared = (_params(aw.summary) & _params(aw.customer_attrition)) - (
        SCOPE_PARAMS | {"request", "response", "_user", "weeks"}
    )
    assert not undeclared, (
        f"Unrecognised shared param(s) {sorted(undeclared)}. If these scope the "
        "query, add them to SCOPE_PARAMS; if not, add them to the exempt set."
    )


# --------------------------------------------------------------------------
# 2. The numbers themselves, from identical inputs.
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_chart_last_point_equals_the_card():
    pool = _FakePool()
    card = await _card(pool)
    chart = await _chart(pool)

    cust = card["active_customers"]
    last = chart["weeks"][-1]

    assert last["numerator"] == cust["lw"] == LW_CUSTOMERS
    assert last["denominator"] == cust["l8w"] == EXPECTED_L8W


@pytest.mark.asyncio
async def test_plotted_value_equals_the_card_percent_delta():
    """R19's invariant: the chart plots `1 − ratio`, and the card's `% Δ` cell is
    `(L8W − LW)/L8W`. Those are the same number.

    ⚠ **What this does NOT cover.** The `1 −` is applied in the FRONTEND
    (`frontend/app/reports/attrition-wow/tabs/CustomerAttritionChart.tsx`), and
    this test recomputes it here rather than reading it from there. So it proves
    the two *endpoints* stay reconcilable — it can NOT catch a frontend-only
    formula flip, which is exactly what R11/R13/R18/R19 each were. There is no
    frontend test runner in this repo (no vitest/jest), so that half is still
    guarded only by the comment block in the component. If a fifth flip lands,
    add a frontend test rather than trusting this file.
    """
    pool = _FakePool()
    card = await _card(pool)
    chart = await _chart(pool)

    plotted = 1 - chart["weeks"][-1]["ratio"]      # what the frontend charts
    assert plotted == pytest.approx(card["active_customers"]["pct"], abs=1e-12)
    # Sanity-check the magnitude against the shipped screenshot (12.37%), so a
    # sign flip cannot pass by satisfying the identity on both sides at once.
    assert plotted == pytest.approx(0.1206, abs=5e-5)


@pytest.mark.asyncio
async def test_denominator_divides_by_a_fixed_eight_not_by_weeks_present():
    """An empty week must still count as a zero, or the card and chart drift
    apart the moment a scope has a quiet week (R17/R18's fixed `/8.0`).
    """
    pool = _FakePool()
    # Same 8-week span, one week with no loads at all: sum drops, divisor cannot.
    pool.summary_row = {**pool.summary_row, "l8w_customers_sum": DEN_SUM - 35}
    pool.chart_rows = [
        *pool.chart_rows[:-1],
        {**pool.chart_rows[-1], "den_sum": DEN_SUM - 35},
    ]

    card = await _card(pool)
    chart = await _chart(pool)

    assert card["active_customers"]["l8w"] == (DEN_SUM - 35) / 8.0
    assert chart["weeks"][-1]["denominator"] == card["active_customers"]["l8w"]


@pytest.mark.asyncio
async def test_zero_denominator_yields_null_not_a_crash():
    """A brand-new scope with no history: ratio must be None, not ZeroDivision."""
    pool = _FakePool()
    pool.summary_row = {**pool.summary_row, "l8w_customers_sum": 0}
    pool.chart_rows = [{**pool.chart_rows[-1], "den_sum": 0}]

    card = await _card(pool)
    chart = await _chart(pool)

    assert chart["weeks"][-1]["ratio"] is None
    assert card["active_customers"]["pct"] is None


# --------------------------------------------------------------------------
# 3. The live replay — the R18 verification, committed instead of discarded.
# --------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.skipif(
    not os.getenv("SAVINGS_DATABASE_URL"),
    reason="live datalake replay: set SAVINGS_DATABASE_URL to run",
)
@pytest.mark.parametrize(
    "scope",
    [
        {},
        {"teams": "TEAM-DFW"},
        {"teams": "TEAM-DFW", "sub_team": "TM1"},
        {"teams": "TEAM-DFW", "sub_team": "TM2"},
        {"view": "ruan"},
    ],
    ids=["all", "dfw", "dfw-tm1", "dfw-tm2", "ruan"],
)
async def test_live_card_chart_parity(scope):
    """Replays BOTH real endpoints against the live datalake and asserts the card
    and the chart's last point are the same numbers.

    The TM1/TM2 scopes are the ones that proved the R18 `sub_team` fix real; a
    scope-less replay cannot detect that class of bug at all.
    """
    import asyncpg

    url = os.environ["SAVINGS_DATABASE_URL"].replace("?sslmode=require", "")
    pool = await asyncpg.create_pool(url, min_size=1, max_size=2)
    try:
        card = await _card(pool, **scope)
        chart = await _chart(pool, **scope)

        cust, last = card["active_customers"], chart["weeks"][-1]
        assert last["numerator"] == cust["lw"], "chart numerator != card LW"
        assert last["denominator"] == pytest.approx(cust["l8w"], abs=1e-9), (
            "chart denominator != card L8W"
        )
        if last["ratio"] is not None:
            assert 1 - last["ratio"] == pytest.approx(cust["pct"], abs=1e-9)
    finally:
        await pool.close()
