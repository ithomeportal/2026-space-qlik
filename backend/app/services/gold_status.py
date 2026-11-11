"""Is the McLeod → gold load stopped right now? — for the report banner (§143 v5).

2026-11-11 the load stopped at 13:20 CST while every report over v4 kept
rendering 13:20 numbers as current; only two people got a mail. The report
chrome asks this once per page view; the answer is shared and cached.

Cost: a 0.3 s probe of v4's TMS ``max(updated_dt)`` (measured 11-11). Only when
v4 is already older than ``STALE_MINUTES`` does it run the watchdog's own
``FRESHNESS_SQL`` (≈2 s, one live-feed scan) — so a quiet night with no stop
events is NOT called a stop, by the same evidence rule as the hourly mail.
Cached ``TTL_S``; a failure is cached ``FAIL_TTL_S`` so a sick DB is not
hammered by every page view. Never raises: an unknown status shows no banner.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from app.services.v4_freshness_monitor import (
    _CST_NOW,
    _TMS,
    FRESHNESS_SQL,
    STALE_MINUTES,
    V4_TABLE,
    stale_tables,
)

logger = logging.getLogger("uvicorn.error")

TTL_S = 300.0
FAIL_TTL_S = 60.0
QUERY_TIMEOUT_S = 15.0

PROBE_SQL = (
    f"SELECT max(updated_dt) AS v4_last, {_CST_NOW} AS cst_now "
    f"FROM {V4_TABLE} WHERE company_id IN {_TMS}"
)

UNKNOWN: dict[str, Any] = {"stopped": False, "unknown": True, "last_write": None,
                           "silent_minutes": None}


@dataclass
class StatusCache:
    value: dict[str, Any] | None = None
    expires: float = 0.0
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)


_CACHE = StatusCache()


def _status(stopped: bool, v4_last, now) -> dict[str, Any]:
    silent = None if v4_last is None else int((now - v4_last).total_seconds() // 60)
    return {"stopped": stopped, "unknown": False,
            "last_write": None if v4_last is None else v4_last.isoformat(),
            "silent_minutes": silent}


async def _measure(pool) -> dict[str, Any]:
    probe = await pool.fetchrow(PROBE_SQL, timeout=QUERY_TIMEOUT_S)
    v4_last, now = probe["v4_last"], probe["cst_now"]
    if v4_last is not None and (now - v4_last).total_seconds() <= STALE_MINUTES * 60:
        return _status(False, v4_last, now)
    row = await pool.fetchrow(FRESHNESS_SQL, timeout=QUERY_TIMEOUT_S)
    stopped = any(t.name == "v4" for t in stale_tables(row))
    return _status(stopped, row["v4_last"], row["cst_now"])


async def gold_status(
    pool,
    *,
    cache: StatusCache | None = None,
    clock: Callable[[], float] = time.monotonic,
) -> dict[str, Any]:
    """Cached {stopped, unknown, last_write (naive CST ISO), silent_minutes}."""
    if pool is None:
        return dict(UNKNOWN)
    c = _CACHE if cache is None else cache
    async with c.lock:
        if c.value is not None and clock() < c.expires:
            return c.value
        try:
            value, ttl = await _measure(pool), TTL_S
        except Exception:
            logger.exception("gold_status: measurement failed (no banner)")
            value, ttl = dict(UNKNOWN), FAIL_TTL_S
        c.value, c.expires = value, clock() + ttl
        return value
