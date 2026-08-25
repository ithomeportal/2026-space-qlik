"""Pins the "Top customers contributing to delays" card and its Table pop-up.

Two defects this file exists to prevent, both from Bruno's PDF 2026-08-24:

* **R1 filtered in the wrong place.** "Do not display customers whose Avg d is
  less than 2" is a HAVING, not a UI filter. Dropped client-side it would trim
  the already-cut top ten down to however many happened to survive — measured
  on 2026-08-24, four of the top ten (HOME DEPOT 1.56, RUAN 1.44, CENTRAL TEXAS
  1.92, STAR CORR 1.98) fall below the line, so the card would have shown six
  names and looked broken.
* **R2 quietly describing a different universe.** The pop-up must be the same
  customers as the card that opened it — same late threshold, same average
  floor, same late-only revenue and all-loads average. They read one pair of
  module constants for exactly that reason.

The pop-up is scope-only by design (four fixed months, the page's date range
ignored) — an MTD range would collapse a four-month comparison to one populated
column. That is asserted here, because it is the kind of "fix" a later round
would apply in good faith.
"""

from __future__ import annotations

import inspect

import pytest

from app.routers import admin_cashflow as ac


class _StubPool:
    """Captures the SQL and its bound params instead of running them."""

    def __init__(self, rows=None):
        self.sql: list[str] = []
        self.params: list[tuple] = []
        self._rows = rows or []

    async def fetch(self, sql, *params):
        self.sql.append(sql)
        self.params.append(params)
        return self._rows


class _Req:
    class app:
        class state:
            savings_pool = None


def _req(pool):
    _Req.app.state.savings_pool = pool
    return _Req


USER = {"sub": "t", "email": "t@local", "roles": ["admin"]}


async def _card(pool, **kw):
    kw.setdefault("range", "mtd")
    return await ac.top_delayed_customers(
        _req(pool),
        kw.get("range"), kw.get("start_date"), kw.get("end_date"),
        kw.get("teams"), kw.get("companies"), kw.get("customer"),
        kw.get("customers"), kw.get("customer_mode", "include"),
        kw.get("contract_type"), kw.get("limit", 10), USER,
    )


async def _popup(pool, **kw):
    return await ac.top_delayed_customers_monthly(
        _req(pool),
        kw.get("teams"), kw.get("companies"), kw.get("customer"),
        kw.get("customers"), kw.get("customer_mode", "include"),
        kw.get("contract_type"), kw.get("limit", 200), USER,
    )


# --------------------------------------------------------------------------
# R1 — the Avg d floor
# --------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_the_average_floor_is_a_having_not_a_ui_filter():
    pool = _StubPool()
    await _card(pool)
    sql = pool.sql[0]
    assert f"AND COALESCE(AVG(days), 0) >= {ac.MIN_AVG_DAYS}" in sql
    # …and it must sit in the HAVING, ahead of the ORDER BY / LIMIT cut.
    having = sql.split("HAVING", 1)[1].split("ORDER BY", 1)[0]
    assert "AVG(days)" in having


@pytest.mark.asyncio
async def test_the_floor_survives_every_filter_combination():
    for kw in (
        {},
        {"range": "ytd"},
        {"teams": "TEAM1"},
        {"customer": "HOME DEPOT"},
        {"customers": "A,B", "customer_mode": "exclude"},
        {"contract_type": "SPOT"},
        {"limit": 50},
    ):
        pool = _StubPool()
        await _card(pool, **kw)
        assert f">= {ac.MIN_AVG_DAYS}" in pool.sql[0], kw


def test_the_two_thresholds_are_module_constants():
    """A local literal is how the three FILTER sites drifted apart before."""
    assert ac.LATE_DAYS == 2
    assert ac.MIN_AVG_DAYS == 2
    src = inspect.getsource(ac.top_delayed_customers)
    assert "late_days = LATE_DAYS" in src
    assert "min_avg_days = MIN_AVG_DAYS" in src


# --------------------------------------------------------------------------
# R2 — the four-month pop-up
# --------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_the_popup_buckets_four_discrete_months_newest_first():
    pool = _StubPool()
    resp = await _popup(pool)
    buckets = resp["meta"]["buckets"]
    assert [b["key"] for b in buckets] == ["tm", "lm", "l2m", "l3m"]

    months = [b["month"] for b in buckets]
    assert len(set(months)) == 4, "a bucket repeats — the month walk is wrong"
    assert months == sorted(months, reverse=True), "buckets must run newest first"
    for m in months:
        assert m.endswith("-01"), f"{m} is not a month start"
    # Consecutive: each bucket is the month immediately before the previous one.
    for newer, older in zip(months, months[1:]):
        ny, nm = int(newer[:4]), int(newer[5:7])
        oy, om = int(older[:4]), int(older[5:7])
        assert (ny * 12 + nm) - (oy * 12 + om) == 1, f"{newer} / {older} are not adjacent"


@pytest.mark.asyncio
async def test_the_popup_ignores_the_pages_date_range():
    """Scope-only, exactly like /timing-monthly."""
    sig = inspect.signature(ac.top_delayed_customers_monthly).parameters
    for name in ("range", "start_date", "end_date"):
        assert name not in sig, f"{name} would let a range collapse the pop-up"

    pool = _StubPool()
    await _popup(pool)
    # The window it DOES bind is the four buckets: L3M start → today.
    params = pool.params[0]
    start, end = params[-2], params[-1]
    assert start.day == 1
    assert (end.year * 12 + end.month) - (start.year * 12 + start.month) == 3


@pytest.mark.asyncio
async def test_the_popup_measures_lateness_exactly_like_the_card():
    card_pool, popup_pool = _StubPool(), _StubPool()
    await _card(card_pool)
    await _popup(popup_pool)
    card, popup = card_pool.sql[0], popup_pool.sql[0]

    for frag in (
        "(c.bill_date::date - c.dest_actual_departure::date) AS days",
        f"COUNT(*) FILTER (WHERE days > {ac.LATE_DAYS})",
        f"COALESCE(SUM(total_charge) FILTER (WHERE days > {ac.LATE_DAYS}), 0)::numeric",
        "COALESCE(AVG(days), 0)::numeric",
        "FROM public.mcleod_gld_cashflow c",
    ):
        assert frag in card, f"card lost: {frag}"
        assert frag in popup, f"pop-up drifted from the card: {frag}"

    # Both guard every operand against McLeod's 1900-01-01 sentinel.
    for sql in (card, popup):
        for col in ("bill_date", "dest_actual_arrival", "dest_actual_departure"):
            assert f"c.{col}              > '2000-01-01'::date" in sql or \
                   f"c.{col}    > '2000-01-01'::date" in sql or \
                   f"c.{col}  > '2000-01-01'::date" in sql, col


@pytest.mark.asyncio
async def test_the_popup_buckets_on_the_same_date_the_page_filters_by():
    """Bucketing on a different date would stop TM reconciling with the card."""
    pool = _StubPool()
    await _popup(pool)
    assert "date_trunc('month', c.origin_actual_arrival)::date  AS bucket" in pool.sql[0]
    assert "c.origin_actual_arrival >=" in pool.sql[0]


@pytest.mark.asyncio
async def test_a_customer_is_pivoted_into_its_four_columns():
    """One row per customer, one column per bucket, blanks where no loads."""
    resp_meta = await _popup(_StubPool())
    tm, lm = (resp_meta["meta"]["buckets"][0]["month"], resp_meta["meta"]["buckets"][1]["month"])
    from datetime import date

    def _d(iso):
        return date(int(iso[:4]), int(iso[5:7]), 1)

    rows = [
        {"customer_name": "ACME", "bucket": _d(tm), "n_loads": 10, "n_late": 4,
         "late_revenue": 1000, "avg_days": 3.0},
        {"customer_name": "ACME", "bucket": _d(lm), "n_loads": 5, "n_late": 1,
         "late_revenue": 250, "avg_days": 6.0},
        # Below the average floor across the window → dropped entirely.
        {"customer_name": "TINY", "bucket": _d(tm), "n_loads": 100, "n_late": 3,
         "late_revenue": 90, "avg_days": 0.5},
        # No late loads at all → dropped, exactly like the card's HAVING.
        {"customer_name": "PUNCTUAL", "bucket": _d(tm), "n_loads": 8, "n_late": 0,
         "late_revenue": 0, "avg_days": 9.0},
    ]
    resp = await _popup(_StubPool(rows))
    data = {r["customer_name"]: r for r in resp["data"]}
    assert set(data) == {"ACME"}, "the card's two HAVING rules were not applied"

    acme = data["ACME"]
    assert (acme["late_tm"], acme["late_lm"]) == (4, 1)
    assert (acme["rev_tm"], acme["rev_lm"]) == (1000.0, 250.0)
    assert (acme["avg_days_tm"], acme["avg_days_lm"]) == (3.0, 6.0)
    # Months with no loads stay None so the cell renders an em-dash rather than
    # a zero that reads as "on time".
    assert acme["late_l2m"] is None and acme["rev_l3m"] is None
    assert acme["n_late_total"] == 5
    assert acme["late_revenue_total"] == 1250.0
    # Weighted by loads (10×3 + 5×6) / 15 = 4.0 — a mean of the two monthly
    # means would say 4.5 and let a 1-load month outvote a 200-load one.
    assert acme["avg_days_total"] == pytest.approx(4.0)


@pytest.mark.asyncio
async def test_the_popup_reports_what_it_dropped():
    from datetime import date

    tm = (await _popup(_StubPool()))["meta"]["buckets"][0]["month"]
    bucket = date(int(tm[:4]), int(tm[5:7]), 1)
    rows = [
        {"customer_name": f"C{i}", "bucket": bucket, "n_loads": 3, "n_late": 1,
         "late_revenue": 100 * i, "avg_days": 5.0}
        for i in range(1, 6)
    ]
    resp = await _popup(_StubPool(rows), limit=2)
    assert resp["meta"]["total"] == 5
    assert resp["meta"]["returned"] == 2
    assert resp["meta"]["truncated"] is True
    # Biggest $ at risk first, so a cap keeps the rows that matter.
    assert [r["customer_name"] for r in resp["data"]] == ["C5", "C4"]


@pytest.mark.asyncio
async def test_both_endpoints_are_access_gated():
    for fn in (ac.top_delayed_customers, ac.top_delayed_customers_monthly):
        src = inspect.getsource(fn)
        assert 'require_report_access("admin-cashflow")' in src, fn.__name__
