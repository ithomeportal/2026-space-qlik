"""The "McLeod data stopped updating" banner on every report (§143 v5).

2026-11-11 the McLeod → gold load stopped at 13:20 while Production, XRay,
Division Payment… kept rendering 13:20 numbers as current. ``GET
/api/data-status/gold`` tells the report chrome whether to show a banner.
It must be CHEAP per request (cached; the 0.3 s v4 probe first, the live-feed
scan only when v4 is already old), must not call a quiet night a stop (same
evidence rule as the hourly watchdog), and must never 500 a report page.
"""

import asyncio
from datetime import datetime, timedelta

import pytest

from app.services import gold_status as g
from app.services import v4_freshness_monitor as f

NOW = datetime(2026, 11, 11, 15, 40)  # noqa: DTZ001
V4_LAST = datetime(2026, 11, 11, 13, 20, 47)  # noqa: DTZ001


class _Pool:
    def __init__(self, v4_last, since=18, fail=False):
        self.v4_last = v4_last
        self.since = since
        self.fail = fail
        self.calls: list[str] = []

    async def fetchrow(self, sql, *params, **kw):
        self.calls.append(sql)
        if self.fail:
            raise TimeoutError
        if sql is g.PROBE_SQL:
            return {"v4_last": self.v4_last, "cst_now": NOW}
        assert sql is f.FRESHNESS_SQL
        return {"cst_now": NOW, "v4_last": self.v4_last, "movement_last": self.v4_last,
                "live_last": NOW, "events_since_v4": self.since,
                "events_since_movement": self.since,
                # The windows tables (v6) frozen too: the banner must still read v4 only.
                "customer_windows_last": self.v4_last, "events_since_customer_windows": self.since,
                "pu_del_windows_last": self.v4_last, "events_since_pu_del_windows": self.since}


def _status(pool, cache=None, clock=lambda: 1000.0):
    return asyncio.run(g.gold_status(pool, cache=cache or g.StatusCache(), clock=clock))


def test_fresh_v4_skips_the_live_scan() -> None:
    pool = _Pool(NOW - timedelta(minutes=10))
    st = _status(pool)
    assert st["stopped"] is False and st["unknown"] is False
    assert pool.calls == [g.PROBE_SQL]


def test_a_stopped_load_is_reported_with_its_last_write() -> None:
    st = _status(_Pool(V4_LAST))
    assert st["stopped"] is True
    assert st["last_write"] == "2026-11-11T13:20:47"
    assert st["silent_minutes"] == 139


def test_a_quiet_night_is_not_a_stop() -> None:
    st = _status(_Pool(V4_LAST, since=f.MIN_EVENTS - 1))
    assert st["stopped"] is False


def test_a_failure_is_unknown_never_raises() -> None:
    st = _status(_Pool(V4_LAST, fail=True))
    assert st == {**st, "stopped": False, "unknown": True}


def test_no_pool_is_unknown() -> None:
    assert _status(None)["unknown"] is True


def test_cached_for_ttl() -> None:
    cache = g.StatusCache()
    pool = _Pool(V4_LAST)
    _status(pool, cache, clock=lambda: 1000.0)
    n = len(pool.calls)
    _status(pool, cache, clock=lambda: 1000.0 + g.TTL_S - 1)
    assert len(pool.calls) == n
    _status(pool, cache, clock=lambda: 1000.0 + g.TTL_S + 1)
    assert len(pool.calls) > n


def test_a_failure_is_cached_briefly_not_for_the_full_ttl() -> None:
    cache = g.StatusCache()
    pool = _Pool(V4_LAST, fail=True)
    _status(pool, cache, clock=lambda: 1000.0)
    n = len(pool.calls)
    _status(pool, cache, clock=lambda: 1000.0 + g.FAIL_TTL_S + 1)
    assert len(pool.calls) > n


def test_the_route_requires_a_user_and_wraps_the_envelope() -> None:
    from app.routers import gold_status as r

    route = next(x for x in r.router.routes if x.path == "/data-status/gold")
    deps = [d.call.__name__ for d in route.dependant.dependencies]
    assert "require_user" in deps


@pytest.mark.parametrize("path", ["frontend/app/reports/layout.tsx"])
def test_the_banner_is_in_the_report_chrome(path) -> None:
    from pathlib import Path

    src = (Path(__file__).resolve().parents[2] / path).read_text()
    assert "<GoldStaleBanner" in src
