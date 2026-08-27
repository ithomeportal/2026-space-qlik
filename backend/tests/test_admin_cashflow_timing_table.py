"""Pins the "+" KPI pop-up's Table view — Orders and Revenue (Bruno 2026-08-27 R3).

The defect this file exists to prevent is a quiet reconciliation break. One row
of that table reads `Month | Orders | Revenue | Percentage | AVG Days`, and all
four numbers are only meaningful if they describe the SAME set of orders:

* **Orders** is `series.total` — the metric's denominator, i.e. exactly what the
  Percentage beside it divides by. It is not a second count, which is the point;
  a separately-derived count could disagree with its own percentage.
* **Revenue** must therefore carry the denominator's predicates verbatim. Filter
  it to the on-time orders instead and the column silently becomes a different
  question, still rendering a plausible number (§16).

Both are asserted by comparing the pop-up's SQL against the `/kpis` card it
expands, because that is the pair a later round would let drift.
"""

from __future__ import annotations

import re

import pytest

from app.routers import admin_cashflow as ac


class _StubPool:
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


async def _timing(pool, **kw):
    return await ac.timing_monthly(
        _req(pool),
        kw.get("grain", "month"),
        kw.get("teams"), kw.get("companies"), kw.get("customer"),
        kw.get("customers"), kw.get("customer_mode", "include"),
        kw.get("contract_type"), USER,
    )


def _norm(sql: str) -> str:
    return re.sub(r"\s+", " ", sql)


def _filter_body(sql: str, col: str) -> str:
    """The FILTER body attached to `… ) AS <col>`.

    Taken as the LAST `FILTER (` before the column's alias — a lazy regex from
    the start of the statement matches the first aggregate in the SELECT and
    silently reports every column as identical to it.
    """
    head, sep, _ = sql.partition(f") AS {col},")
    if not sep:
        head, sep, _ = sql.partition(f") AS {col} ")
    assert sep, f"{col} is missing from the SQL — the aggregate changed shape"
    idx = head.rfind("FILTER (")
    assert idx != -1, f"{col} lost its FILTER"
    return head[idx + len("FILTER (") :].strip()


# --------------------------------------------------------------------------
# Revenue rides the DENOMINATOR's predicates
# --------------------------------------------------------------------------
@pytest.mark.asyncio
@pytest.mark.parametrize(
    "rev_col, predicates",
    [
        (
            "del_rev",
            [
                "bill_date>'2000-01-01'::date",
                "dest_actual_arrival>'2000-01-01'::date",
                "dest_actual_departure>'2000-01-01'::date",
            ],
        ),
        ("bol_rev", ["bill_date>'2000-01-01'::date", "bol_recv_date>'2000-01-01'::date"]),
        ("inv_rev", ["bill_date>'2000-01-01'::date", "invoice_recv_date>'2000-01-01'::date"]),
    ],
)
async def test_revenue_filters_match_the_matching_total(rev_col, predicates):
    pool = _StubPool()
    await _timing(pool)
    sql = _norm(pool.sql[0])

    total_col = rev_col.replace("_rev", "_total")

    def filter_body(col: str) -> str:
        return _filter_body(sql, col)

    assert filter_body(rev_col) == filter_body(total_col), (
        f"{rev_col} no longer describes the same universe as {total_col}; "
        "Revenue and Orders would stop reconciling with the Percentage"
    )
    for p in predicates:
        assert p in filter_body(rev_col), f"{rev_col} lost the sentinel guard {p}"


@pytest.mark.asyncio
async def test_revenue_is_not_narrowed_to_the_on_time_orders():
    """The one wrong turn that still renders a believable column."""
    pool = _StubPool()
    await _timing(pool)
    sql = _norm(pool.sql[0])
    for col in ("del_rev", "bol_rev", "inv_rev"):
        body = _filter_body(sql, col)
        assert "<=" not in body, (
            f"{col} is filtered by a threshold — that is the on-time revenue, "
            "not the metric's total revenue"
        )


@pytest.mark.asyncio
async def test_the_base_cte_actually_selects_total_charge():
    """A SUM over a column the CTE never projected is a 500, not a wrong number."""
    pool = _StubPool()
    await _timing(pool)
    base = _norm(pool.sql[0]).split("agg AS", 1)[0]
    assert "c.total_charge" in base


# --------------------------------------------------------------------------
# The payload the table reads
# --------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_every_metric_returns_revenue_alongside_total():
    rows = [
        {
            "mon": __import__("datetime").date(2026, 8, 1),
            "del_total": 10, "del_within": 7, "del_avg": 1.5, "del_rev": 1000.0,
            "bol_total": 8, "bol_within": 8, "bol_avg": 0.5, "bol_rev": 800.0,
            "inv_total": 4, "inv_within": 1, "inv_avg": 3.0, "inv_rev": 400.0,
        }
    ]
    resp = await _timing(_StubPool(rows=rows))
    data = resp["data"]
    for key, (total, rev) in {
        "del": (10, 1000.0), "bol": (8, 800.0), "carrinv": (4, 400.0),
    }.items():
        s = data[key]
        assert s["total"] == [total], f"{key} Orders column"
        assert s["revenue"] == [rev], f"{key} Revenue column"
        # Orders IS the denominator — the table divides `within` by it.
        assert s["total"][0] >= s["within"][0]


@pytest.mark.asyncio
async def test_an_empty_bucket_reports_zero_revenue_not_null():
    """generate_series gap-fills the axis; a gap must not render as a blank cell."""
    rows = [
        {
            "mon": __import__("datetime").date(2026, 7, 1),
            "del_total": 0, "del_within": 0, "del_avg": None, "del_rev": 0,
            "bol_total": 0, "bol_within": 0, "bol_avg": None, "bol_rev": 0,
            "inv_total": 0, "inv_within": 0, "inv_avg": None, "inv_rev": 0,
        }
    ]
    resp = await _timing(_StubPool(rows=rows))
    for key in ("del", "bol", "carrinv"):
        assert resp["data"][key]["revenue"] == [0.0]
        assert resp["data"][key]["avg_days"] == [None]


@pytest.mark.asyncio
async def test_revenue_survives_both_grains_and_every_filter():
    for kw in (
        {}, {"grain": "week"}, {"teams": "TEAM1"}, {"companies": "TMS"},
        {"customer": "HOME DEPOT"},
        {"customers": "A,B", "customer_mode": "exclude"},
        {"contract_type": "SPOT"},
    ):
        pool = _StubPool()
        await _timing(pool, **kw)
        sql = pool.sql[0]
        for col in ("del_rev", "bol_rev", "inv_rev"):
            assert f") AS {col}" in sql, f"{col} dropped for {kw}"
