"""KPI MANAGEMENT "Fuel" measure — EIA weekly retail diesel, $/gal (2026-10-31).

Part of the ``ops_portal_overview`` package. Ported from the quoting portal's
US National Fuel page (``/BOT/quoting/quotingportal-client-main``,
``src/lib/fuel/{db,chart-data}.ts``) — the SHAPING is ported, nothing is
imported across repos.

Source: ``modern_pricing_portal`` (pool ``get_pricing_pool``, role
``spaceqlik_pricing_ro`` — SELECT on both fuel tables granted 2026-10-31):

* ``fuel_diesel_weekly``   — one row per (region, EIA Monday ``period``);
  9 regions; loaded Mondays 15:00 UTC, so the CURRENT week is never present.
* ``fuel_diesel_forecast`` — monthly STEO national + derived regional points,
  ``period`` = first of month, ~15 months ahead.

Grain shaping, aligned to ``/combo``'s buckets (``_resolve_grain_window``):

* week  — exact: the EIA period IS the bucket's Monday (``DATE_TRUNC('week')``).
* month — AVG of that month's weekly values; future months get the forecast.
* day   — each day carries its week's value (the price is a weekly figure).

The change column is computed on the FULL weekly series before windowing, so
the first visible bucket still has a real predecessor: week/day = WoW (vs the
prior available week), month = MoM (vs the prior month's average).

Fuel is MARKET data — it ignores team / customer / lane / carrier filters by
design (the frontend says so in its caption). It is still behind the report
gate like every other section.

🔴 Fail soft. The fuel line rides on top of the business bars; a missing pool,
a revoked GRANT (``InsufficientPrivilegeError``) or any other error answers
``success: true`` with empty points and an ``unavailable`` message — never a
500 — and is logged. The bars come from ``/combo`` and are never affected.
"""

from __future__ import annotations

import asyncio
import calendar
import logging
from collections import defaultdict
from datetime import date, timedelta
from typing import Any, Optional

from fastapi import Depends, HTTPException, Query, Request

from app.clock import cst_today
from app.routers.deps import get_pricing_pool, require_report_access

from ._constants import router
from ._dates import _resolve_grain_window

logger = logging.getLogger(__name__)

# (code, name) in display order — national first. Mirrors the quoting portal's
# FUEL_REGIONS registry; an unknown code from the table is appended after these.
FUEL_REGIONS: tuple[tuple[str, str], ...] = (
    ("NUS", "U.S. National"),
    ("R1X", "New England"),
    ("R1Y", "Central Atlantic"),
    ("R1Z", "Lower Atlantic"),
    ("R20", "Midwest"),
    ("R30", "Gulf Coast"),
    ("R40", "Rocky Mountain"),
    ("R50", "West Coast"),
    ("SCA", "California"),
)

# Weekly rows read BEFORE the first bucket so its change has a predecessor.
# 40 days covers a whole prior month (month grain) and any 1-4 missing weeks.
LOOKBACK_DAYS = 40
# Same horizon as the reference page's forecast (FORECAST_MONTHS = 6).
FORECAST_MONTHS = 6
# Longest custom window accepted (≈ the Day grain's 365 + margin).
MAX_SPAN_DAYS = 800
QUERY_TIMEOUT_S = 10.0
UNAVAILABLE_MSG = "Fuel prices are unavailable right now."

WEEKLY_SQL = """
    SELECT region_code, region_name, period, value::float8 AS value
    FROM public.fuel_diesel_weekly
    WHERE period >= $1 AND period <= $2 AND value IS NOT NULL
    ORDER BY region_code, period
"""

FRESHNESS_SQL = """
    SELECT MAX(period) AS latest_period, MAX(fetched_at) AS fetched_at
    FROM public.fuel_diesel_weekly
"""

# One value per (region, month): the newest STEO report wins.
FORECAST_SQL = """
    SELECT DISTINCT ON (region_code, period)
           region_code, period, value::float8 AS value
    FROM public.fuel_diesel_forecast
    WHERE period > $1 AND period <= $2 AND value IS NOT NULL
    ORDER BY region_code, period, report_period DESC NULLS LAST, fetched_at DESC
"""


# ---------------------------------------------------------------------------
# Window
# ---------------------------------------------------------------------------


def _add_months(d: date, n: int) -> date:
    idx = d.year * 12 + (d.month - 1) + n
    return date(idx // 12, idx % 12 + 1, 1)


def _custom_anchors(grain: str, start: date, end: date) -> list[date]:
    """Bucket starts for an explicit [start, end] window, /combo's conventions."""
    if grain == "day":
        return [start + timedelta(days=i) for i in range((end - start).days + 1)]
    if grain == "week":
        first = start - timedelta(days=start.weekday())
        return [first + timedelta(weeks=i) for i in range((end - first).days // 7 + 1)]
    out: list[date] = []
    cur = start.replace(day=1)
    while cur <= end:
        out.append(cur)
        cur = _add_months(cur, 1)
    return out


def fuel_anchors(grain: str, today: date, start: Optional[date], end: Optional[date]) -> list[date]:
    """The chart's buckets: /combo's default window, or an explicit one."""
    if start is None or end is None:
        return _resolve_grain_window(grain, today)[2]
    if start > end:
        raise HTTPException(status_code=422, detail="start must be on or before end")
    clamped = max(start, end - timedelta(days=MAX_SPAN_DAYS))
    return _custom_anchors(grain, clamped, end)


def _bucket_last_day(grain: str, anchor: date) -> date:
    if grain == "month":
        return anchor.replace(day=calendar.monthrange(anchor.year, anchor.month)[1])
    if grain == "week":
        return anchor + timedelta(days=6)
    return anchor


# ---------------------------------------------------------------------------
# Pure shaping (unit-tested without a database)
# ---------------------------------------------------------------------------


def regions_from_rows(rows: list[Any]) -> list[dict]:
    """Registry order first, then any code the table carries that we don't know."""
    known = {code for code, _ in FUEL_REGIONS}
    extra: dict[str, str] = {}
    for r in rows:
        code = r["region_code"]
        if code not in known and code not in extra:
            extra[code] = r["region_name"] or code
    return [{"code": c, "name": n} for c, n in FUEL_REGIONS] + [
        {"code": c, "name": n} for c, n in sorted(extra.items())
    ]


def series_by_region(rows: list[Any]) -> dict[str, list[tuple[date, float]]]:
    """{code: [(period, value), ...]} ascending, values as float."""
    acc: dict[str, list[tuple[date, float]]] = defaultdict(list)
    for r in rows:
        if r["value"] is None:
            continue
        acc[r["region_code"]].append((r["period"], float(r["value"])))
    return {code: sorted(points) for code, points in acc.items()}


def weekly_changes(series: list[tuple[date, float]]) -> dict[date, float]:
    """Delta vs the prior AVAILABLE week, over the whole series (pre-window)."""
    return {
        cur[0]: round(cur[1] - prev[1], 3)
        for prev, cur in zip(series, series[1:])
    }


def _monthly_averages(series: list[tuple[date, float]]) -> dict[date, float]:
    acc: dict[date, list[float]] = defaultdict(list)
    for period, value in series:
        acc[period.replace(day=1)].append(value)
    return {m: round(sum(v) / len(v), 3) for m, v in acc.items()}


def _point(anchor: date, period: Optional[date], values: dict, changes: dict) -> dict:
    return {
        "bucket_start": anchor.isoformat(),
        "period": period.isoformat() if period else None,
        "values": values,
        "wow": changes,
    }


def shape_points(grain: str, anchors: list[date], series: dict[str, list[tuple[date, float]]]) -> list[dict]:
    """One point per anchor (dense, so the frontend merges by bucket key)."""
    if grain == "month":
        return _shape_month(anchors, series)
    by_period = {code: dict(pts) for code, pts in series.items()}
    changes = {code: weekly_changes(pts) for code, pts in series.items()}
    out = []
    for a in anchors:
        monday = a - timedelta(days=a.weekday())
        values = {c: v[monday] for c, v in by_period.items() if monday in v}
        deltas = {c: changes[c][monday] for c in values if monday in changes[c]}
        out.append(_point(a, monday if values else None, values, deltas))
    return out


def _shape_month(anchors: list[date], series: dict[str, list[tuple[date, float]]]) -> list[dict]:
    avgs = {code: _monthly_averages(pts) for code, pts in series.items()}
    out = []
    for a in anchors:
        prior = _add_months(a, -1)
        values = {c: m[a] for c, m in avgs.items() if a in m}
        deltas = {c: round(values[c] - avgs[c][prior], 3) for c in values if prior in avgs[c]}
        out.append(_point(a, None, values, deltas))
    return out


def shape_forecast(rows: list[Any]) -> list[dict]:
    acc: dict[date, dict[str, float]] = defaultdict(dict)
    for r in rows:
        if r["value"] is not None:
            acc[r["period"]][r["region_code"]] = round(float(r["value"]), 3)
    return [{"bucket_start": p.isoformat(), "values": dict(acc[p])} for p in sorted(acc)]


def _iso(v: Any) -> Optional[str]:
    return v.isoformat() if v is not None else None


def empty_payload(grain: str, message: Optional[str]) -> dict:
    return {
        "success": True,
        "data": {
            "grain": grain,
            "change_basis": "mom" if grain == "month" else "wow",
            "regions": [{"code": c, "name": n} for c, n in FUEL_REGIONS],
            "points": [],
            "forecast": [],
            "freshness": {"latest_period": None, "fetched_at": None},
            "unavailable": message,
        },
    }


# ---------------------------------------------------------------------------
# I/O
# ---------------------------------------------------------------------------


def _fuel_pool(request: Request):
    """The pricing pool, or None when it is not configured (fail soft)."""
    try:
        return get_pricing_pool(request)
    except HTTPException:
        return None


async def _read(pool, grain: str, anchors: list[date]) -> tuple[list, Any, list]:
    lo = anchors[0] - timedelta(days=LOOKBACK_DAYS)
    hi = _bucket_last_day(grain, anchors[-1])
    weekly_q = pool.fetch(WEEKLY_SQL, lo, hi)
    fresh_q = pool.fetchrow(FRESHNESS_SQL)
    if grain != "month":
        weekly, fresh = await asyncio.gather(weekly_q, fresh_q)
        return weekly, fresh, []
    fc_q = pool.fetch(FORECAST_SQL, anchors[-1], _add_months(anchors[-1], FORECAST_MONTHS))
    weekly, fresh, fc = await asyncio.gather(weekly_q, fresh_q, fc_q)
    return weekly, fresh, fc


def build_payload(grain: str, anchors: list[date], weekly: list, fresh: Any, fc: list) -> dict:
    series = series_by_region(weekly)
    payload = empty_payload(grain, None)
    data = {
        **payload["data"],
        "regions": regions_from_rows(weekly),
        "points": shape_points(grain, anchors, series),
        "forecast": shape_forecast(fc),
        "freshness": {
            "latest_period": _iso(fresh["latest_period"]) if fresh else None,
            "fetched_at": _iso(fresh["fetched_at"]) if fresh else None,
        },
    }
    return {**payload, "data": data}


@router.get("/fuel")
async def fuel(
    request: Request,
    grain: str = Query("month", description="'day' | 'week' | 'month'"),
    start: Optional[date] = Query(None, description="optional window start (ISO date)"),
    end: Optional[date] = Query(None, description="optional window end (ISO date)"),
    _user: dict = Depends(require_report_access("ops-portal-overview")),
):
    """EIA weekly retail diesel ($/gal) per region, bucketed like ``/combo``.

    Market data: team / customer / lane / carrier filters do not apply.
    Fails SOFT — see the module docstring.
    """
    if grain not in ("day", "week", "month"):
        grain = "month"
    anchors = fuel_anchors(grain, cst_today(), start, end)
    if not anchors:
        return empty_payload(grain, None)
    pool = _fuel_pool(request)
    if pool is None:
        logger.warning("ops-portal /fuel: pricing pool not configured")
        return empty_payload(grain, UNAVAILABLE_MSG)
    try:
        weekly, fresh, fc = await asyncio.wait_for(_read(pool, grain, anchors), QUERY_TIMEOUT_S)
    except Exception:  # noqa: BLE001 — fail soft by contract; logged below
        logger.exception("ops-portal /fuel: fuel query failed (grain=%s)", grain)
        return empty_payload(grain, UNAVAILABLE_MSG)
    return build_payload(grain, anchors, weekly, fresh, fc)
