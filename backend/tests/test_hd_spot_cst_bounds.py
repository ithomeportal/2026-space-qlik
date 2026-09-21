"""HD Spot — the CST day bound (fixed 2026-09-21).

`hd_spot.py` had no test file at all, which is part of why this survived: the
report shipped 2026-08-12 and every window it ever rendered opened 10 hours
early.

`$1::date AT TIME ZONE 'America/Chicago'` is not midnight in Chicago. For a
`date` input Postgres resolves the cast to `timestamptz` first, so the
expression is midnight **UTC** *rendered* in Chicago and its type is
`timestamp WITHOUT time zone`::

    SELECT pg_typeof('2026-06-24'::date AT TIME ZONE 'America/Chicago');
    -- timestamp without time zone | 2026-06-23 19:00:00
    SELECT pg_typeof('2026-06-24'::date::timestamp AT TIME ZONE 'America/Chicago');
    -- timestamp with time zone    | 2026-06-24 05:00:00+00

Measured on the day of the fix:

===============  =========  =======  ===========
window           before     after    reference
===============  =========  =======  ===========
MTD (default)    5,072      4,999    4,999
Last Month       6,279      6,267    6,267
Apr-Sep custom   36,672     36,627   36,627
Today            187        187      187
===============  =========  =======  ===========

The 73 extra MTD rows were 2026-08-31 from **14:02 CST** onward and included
**19 WON** orders. August's own window kept them too, so the boundary evening
was **double-counted** month-over-month rather than moved.

⚠ The defect is asymmetric: `date + INTERVAL` is already a naive timestamp, so
the upper bound was always correct and only the bare lower bound was wrong.
The window was too WIDE at the start and never short at the end — the error
could only over-count, which is why a report that ran high for a month was
never reported.

Fleet sweep and detection recipe: `/BOT/TIMEZONE-CAST-FLEET.md`.
"""

from __future__ import annotations

import asyncio
import os
import re
import types
from datetime import date

import pytest

from app.routers import hd_spot as h


class _Conn:
    def __init__(self, pool):
        self._pool = pool

    async def fetch(self, sql, *params):
        self._pool.sqls.append(sql)
        self._pool.params.append(params)
        return []

    async def fetchrow(self, sql, *params):
        self._pool.sqls.append(sql)
        self._pool.params.append(params)
        return None

    async def fetchval(self, sql, *params):
        self._pool.sqls.append(sql)
        self._pool.params.append(params)
        return None


class _Acquire:
    def __init__(self, pool):
        self._pool = pool

    async def __aenter__(self):
        return _Conn(self._pool)

    async def __aexit__(self, *exc):
        return False


class _StubPool:
    """⚠ Records the SQL. A stub pool cannot see a WHERE — these assert on the
    statement TEXT, which is why the live equivalence layer below exists."""

    def __init__(self):
        self.sqls: list[str] = []
        self.params: list[tuple] = []

    def acquire(self):
        return _Acquire(self)


def _emitted_sql() -> list[str]:
    """Every statement HD Spot's report path emits, comments stripped.

    ⚠ The statements carry comments that QUOTE the predicate under test, so a
    raw substring scan would find the explanation and call it the code.
    """
    pool = _StubPool()
    orig = h.get_pricing_pool
    h.get_pricing_pool = lambda request: pool
    try:
        request = types.SimpleNamespace(
            app=types.SimpleNamespace(state=types.SimpleNamespace())
        )
        f = {
            "start": date(2026, 9, 1),
            "end": date(2026, 9, 21),
            "groups": [],
            "statuses": [],
        }
        # /summary drives _build, which issues both spot-side statements.
        asyncio.run(h.summary(request=request, f=f, _user={}))
    finally:
        h.get_pricing_pool = orig
    assert len(pool.sqls) >= 2, "harness went vacuous — no SQL captured"
    return [
        "\n".join(
            line for line in sql.split("\n") if not line.strip().startswith("--")
        )
        for sql in pool.sqls
    ]


_BARE_DATE_AT_TZ = re.compile(r"::date\s+AT TIME ZONE")


def test_the_lower_bound_casts_through_timestamp():
    """🔴 The fix. Without `::timestamp` the bound is a naive timestamp and the
    window opens 10 hours early."""
    seen = 0
    for sql in _emitted_sql():
        if "price_date >=" not in sql:
            continue
        seen += 1
        assert "::date::timestamp AT TIME ZONE" in sql, sql[:400]
        assert not _BARE_DATE_AT_TZ.search(sql), sql[:400]
    assert seen, "no statement carried a date bound — the guard would pass vacuously"


def test_the_guard_can_actually_fail():
    """Without this, the assertion above would pass against any string at all."""
    assert _BARE_DATE_AT_TZ.search(
        "price_date >= ($1::date AT TIME ZONE 'America/Chicago')"
    )
    assert not _BARE_DATE_AT_TZ.search(
        "price_date >= ($1::date::timestamp AT TIME ZONE 'America/Chicago')"
    )


def test_the_upper_bound_is_exclusive_next_day():
    """`<= end` against a timestamp compares to MIDNIGHT, so `from == to` would
    return nothing and read as "no activity"."""
    for sql in _emitted_sql():
        if "price_date >=" in sql:
            assert "INTERVAL '1 day'" in sql
            assert "price_date <=" not in sql


def test_the_column_side_stays_bare_so_the_index_survives():
    """§64: a function on the indexed column forces a seq scan — measured
    36.7 ms vs 2.5 ms on this exact table."""
    for sql in _emitted_sql():
        assert not re.search(
            r"\(\s*price_date AT TIME ZONE[^)]*\)\s*::date\s*(>=|<|<=|>)", sql
        ), sql[:400]


def test_hd_spot_and_the_trends_report_bound_dates_identically():
    """Two reports over the SAME column of the SAME table must not disagree
    about which day a row belongs to. ⚠ Duplicated resolver logic drifts."""
    from app.routers import production_spots_trends as p

    frag = "::date::timestamp AT TIME ZONE 'America/Chicago'"
    hd = [s for s in _emitted_sql() if "price_date >=" in s]
    assert hd and all(frag in s for s in hd)

    params: list = []
    cte = p._base_cte(params, date(2026, 9, 1), date(2026, 9, 21), {})
    assert frag in cte


# ---------------------------------------------------------------------------
# live — the layer no text assertion can reach
# ---------------------------------------------------------------------------

_PRICING = os.environ.get("PRICING_DATABASE_URL", "")


@pytest.mark.skipif(
    not _PRICING, reason="PRICING_DATABASE_URL not set — offline run"
)
def test_live_the_bound_selects_exactly_the_cst_calendar_days():
    """The fast form must return the same rows as the slow, obviously-correct
    one. Before the fix these differed by 73 on the default MTD window."""
    import asyncpg

    async def run():
        conn = await asyncpg.connect(
            re.sub(r"[?&]sslmode=\w+", "", _PRICING), ssl="require"
        )
        try:
            return await conn.fetchrow(
                """
                SELECT
                  (SELECT count(*) FROM spot_report_condensed
                    WHERE express_module_customer_name = $3
                      AND price_date >= ($1::date::timestamp AT TIME ZONE 'America/Chicago')
                      AND price_date <  (($2::date + INTERVAL '1 day') AT TIME ZONE 'America/Chicago')
                      AND (source IS NULL OR source <> ALL($4::text[]))) AS sargable,
                  (SELECT count(*) FROM spot_report_condensed
                    WHERE express_module_customer_name = $3
                      AND (price_date AT TIME ZONE 'America/Chicago')::date BETWEEN $1 AND $2
                      AND (source IS NULL OR source <> ALL($4::text[]))) AS reference
                """,
                date(2026, 9, 1),
                date(2026, 9, 21),
                h.CUSTOMER,
                list(h.FROZEN_SOURCES),
            )
        finally:
            await conn.close()

    row = asyncio.run(run())
    assert row["reference"] > 0, "empty window — the assertion would pass vacuously"
    assert row["sargable"] == row["reference"]
