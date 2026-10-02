"""IT Tickets — FreshService timestamps are NAIVE UTC; the report must speak CST.

Found 2026-10-01 (§116 follow-up). The four timestamp columns are
`timestamp without time zone` and hold UTC (tickets peak 13:00-22:00 = the
8 AM-5 PM CST working day). Before the fix:

* `created_date::date` bucketed every ticket opened after 7 PM CST on the NEXT
  day (and `date_trunc('week'|'month')` likewise at the boundaries);
* the window bounds compared a UTC column against CST dates (5-6 h skew);
* the API emitted naive ISO strings, which the browser parses as LOCAL time —
  every Created / Due / Updated cell printed 5-6 h late, and the aging band
  started the clock late.

And the feed itself stopped on 2026-04-15 while the page kept rendering — so
/summary now carries an unfiltered freshness stamp.

Three layers: SQL linters over the emitted statements, the freshness unit
contract, and `test_live_*` (skipped unless FRESHSERVICE_DATABASE_URL is set)
that recomputes the day buckets independently from the raw UTC column.
"""

from __future__ import annotations

import asyncio
import os
import re
import types
from collections import Counter
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest

from app.routers import it_tickets as it

_COLS = (("CreatedDate", "created_date"), ("UpdatedDate", "updated_date"),
         ("DueBy", "due_by"), ("FirstResponseDueBy", "first_resp_due"))


@pytest.mark.parametrize("col,alias", _COLS)
def test_every_timestamp_is_converted_from_utc_once_in_the_base_cte(col, alias):
    assert re.search(
        rf'\("{col}" AT TIME ZONE \'UTC\'\)\s+AS {alias}\b', it._BASE_CTE
    ), f"{col} is still read as a naive local timestamp"


def test_no_raw_timestamp_column_is_read_outside_the_base_cte():
    """Every endpoint must go through the converted alias — a raw
    "CreatedDate" in a SELECT would bring the UTC bug straight back.
    (The CTE's own `"CreatedDate" >= '2025-01-01'` history floor is the one
    allowed raw read, as is the freshness probe.)"""
    src = open(it.__file__, encoding="utf-8").read()
    body = src
    for start in ('_BASE_CTE = f"""', '_FRESHNESS_SQL = """'):
        a = body.index(start)
        b = body.index('\n"""\n', a + len(start))
        body = body[:a] + body[b:]
    for col, _ in _COLS:
        assert f'"{col}"' not in body, col


class _Conn:
    def __init__(self):
        self.sqls: list[str] = []

    async def fetch(self, sql, *p):
        self.sqls.append(sql)
        return []

    async def fetchrow(self, sql, *p):
        self.sqls.append(sql)
        return {"pending_now": 0, "closed": 0, "total": 0}

    async def fetchval(self, sql, *p):
        self.sqls.append(sql)
        return None


class _Pool:
    def __init__(self):
        self.conn = _Conn()

    def acquire(self):
        pool = self

        class _Ctx:
            async def __aenter__(self):
                return pool.conn

            async def __aexit__(self, *a):
                return False

        return _Ctx()

    async def fetch(self, sql, *p):
        return await self.conn.fetch(sql, *p)


def _drive_summary(pool):
    orig = it.get_freshservice_pool
    it.get_freshservice_pool = lambda request: pool
    try:
        return asyncio.run(it.summary(
            request=types.SimpleNamespace(), type=None, range="last_30d",
            start=None, end=None, user={},
        ))
    finally:
        it.get_freshservice_pool = orig


def test_every_window_bound_is_a_cst_date():
    """`$2::date` against a timestamptz = CST midnight under the session TZ."""
    pool = _Pool()
    _drive_summary(pool)
    orig = it.get_freshservice_pool
    asyncio.run(it._fetch_table(pool, "Incident", date(2026, 4, 1), date(2026, 4, 2),
                                it.PENDING_STATUSES, 1, 50, None, "created"))
    windowed = [s for s in pool.conn.sqls if "$2" in s and "$3" in s]
    assert len(windowed) == 5
    for sql in windowed:
        assert re.search(r"created_date >= \$2::date AND (t\.)?created_date < \$3::date", sql)
    assert orig is it.get_freshservice_pool


def test_summary_reports_freshness_from_the_unfiltered_table():
    pool = _Pool()
    resp = _drive_summary(pool)
    assert any(s.strip() == it._FRESHNESS_SQL.strip() for s in pool.conn.sqls)
    assert "WHERE" not in it._FRESHNESS_SQL
    assert resp["data"]["freshness"] == {"last_synced": None, "stale": True}


def test_freshness_staleness_threshold():
    now = datetime(2026, 10, 1, 18, 0, tzinfo=timezone.utc)
    fresh = it._freshness(now - timedelta(hours=60), now)  # a quiet weekend
    assert fresh["stale"] is False
    dead = it._freshness(datetime(2026, 4, 15, 14, 7, tzinfo=timezone.utc), now)
    assert dead == {"last_synced": "2026-04-15T14:07:00+00:00", "stale": True}


# ---------------------------------------------------------------------------
# Live — recompute the CST day buckets from the raw UTC column, independently
# ---------------------------------------------------------------------------

_FS = os.environ.get("FRESHSERVICE_DATABASE_URL", "")
live = pytest.mark.skipif(not _FS, reason="FRESHSERVICE_DATABASE_URL not set")
_CST = ZoneInfo("America/Chicago")


async def _live_pool():
    import asyncpg

    async def _cst(conn):
        await conn.execute("SET TIME ZONE 'America/Chicago'")

    url = re.sub(r"[?&]sslmode=\w+", "", _FS)
    return await asyncpg.create_pool(url, ssl="require", min_size=1, max_size=2, init=_cst)


@live
def test_live_day_buckets_are_cst_days():
    """history_status per-day counts == the raw UTC timestamps converted to
    America/Chicago in Python. Window: the feed's last live fortnight."""
    s, e = date(2026, 4, 1), date(2026, 4, 14)

    async def run():
        pool = await _live_pool()
        try:
            orig = it.get_freshservice_pool
            it.get_freshservice_pool = lambda request: pool
            try:
                resp = await it.summary(
                    request=types.SimpleNamespace(), type="incident", range="custom",
                    start=s, end=e, user={},
                )
            finally:
                it.get_freshservice_pool = orig
            raw = await pool.fetch(
                it._BASE_CTE.replace(
                    '("CreatedDate" AT TIME ZONE \'UTC\')', '"CreatedDate"'
                ) + "SELECT created_date FROM t",
                it.TYPE_INCIDENT,
            )
            return resp, raw
        finally:
            await pool.close()

    resp, raw = asyncio.run(run())
    got = Counter()
    for r in resp["data"]["history_status"]:
        got[r["day"]] += r["cnt"]
    want = Counter()
    for r in raw:
        d = r["created_date"].replace(tzinfo=timezone.utc).astimezone(_CST).date()
        if s <= d <= e:
            want[d.isoformat()] += 1
    assert sum(want.values()) > 0, "no tickets in the probe window"
    assert dict(got) == dict(want)


@live
def test_live_table_rows_carry_an_offset():
    async def run():
        pool = await _live_pool()
        try:
            return await it._fetch_table(
                pool, it.TYPE_INCIDENT, date(2026, 4, 1), date(2026, 4, 14),
                it.CLOSED_STATUSES, 1, 5, None, "updated",
            )
        finally:
            await pool.close()

    rows, total = asyncio.run(run())
    assert total > 0
    for r in rows:
        assert r["created"].endswith("+00:00"), r["created"]


# ---------------------------------------------------------------------------
# Frontend source guards (no JS test runner — frontend/CLAUDE.md)
# ---------------------------------------------------------------------------

_FE = os.path.join(os.path.dirname(__file__), "..", "..", "frontend")


def _read(rel: str) -> str:
    with open(os.path.join(_FE, rel), encoding="utf-8") as fh:
        return fh.read()


def test_fe_date_only_keys_are_parsed_as_local_dates():
    page = _read("app/reports/it-tickets-mgmt/page.tsx")
    api = _read("lib/it-tickets-api.ts")
    assert "new Date(k)" not in page
    assert page.count("parseLocalDate(k)") == 2  # day/week_start + month_start
    fmt_iso_day = api[api.index("export function fmtIsoDay"):]
    fmt_iso_day = fmt_iso_day[: fmt_iso_day.index("\n}\n")]
    assert "parseLocalDate(iso)" in fmt_iso_day and "new Date(" not in fmt_iso_day


def test_fe_page_surfaces_a_stale_feed():
    """The 2026-04-15 freeze was invisible for 5½ months — the page must say so."""
    page = _read("app/reports/it-tickets-mgmt/page.tsx")
    assert "freshness?.stale &&" in page
    assert 'role="alert"' in page
    assert "Data as of" in page
