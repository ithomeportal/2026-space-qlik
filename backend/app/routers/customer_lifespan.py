"""Code-made report: Customer Lifespan (#69, request 2026-10-29).

Every customer since 2016: first and last load, lifespan, status, reactivations,
cohorts by first year, survival, and the monthly new / lost / reactivated flow.
Reads ``customer_lifespan_orders`` (analytics_hub) — the workbook's history to
2026-08-31 plus the nightly v4 sync (``services/customer_lifespan_store``).
Definitions: ``services/customer_lifespan_core`` + ``_trends``. Spec:
docs/SPEC-CUSTOMER-LIFESPAN.md.

The division is a PATH SEGMENT (``/{all|corp|dfw}/…``) so it can never default
(§100). Safe to be client-chosen here: every TagRole granted this report may
read both divisions, and ``require_report_access`` runs before it is honoured.
"""
from __future__ import annotations

import asyncio
import time
from datetime import date
from enum import Enum

from fastapi import APIRouter, Depends, HTTPException, Query, Request

from app.routers.deps import get_pool, require_report_access
from app.services.customer_lifespan_core import (
    CUSTOMER_MONTHS_SQL,
    DEFAULT_WINDOW,
    WINDOWS,
    Customer,
    build_customers,
    customer_detail,
    customer_row,
    merge_rows,
    summary,
)
from app.services.customer_lifespan_store import CUTOVER, EXCEL_LAST_SHIP, TAIL_START
from app.services.customer_lifespan_trends import GRAINS, cohorts, lifespan, trend

REPORT_KEY = "customer-lifespan"
CACHE_TTL_SECONDS = 300.0

router = APIRouter(tags=[REPORT_KEY], prefix=f"/custom/{REPORT_KEY}")


class Division(str, Enum):
    all = "all"
    corp = "corp"
    dfw = "dfw"


SOURCES_SQL = """
SELECT source, COUNT(*)::int AS orders, MIN(ship_date) AS first_ship,
       MAX(ship_date) AS last_ship, MAX(loaded_at) AS loaded_at,
       COUNT(*) FILTER (WHERE voided_in_datalake)::int AS voided
  FROM customer_lifespan_orders
 GROUP BY source
"""
LAST_SYNC_SQL = """
SELECT status, started_at, finished_at, v4_rows, stored_v4_rows, gap_fills,
       v4_last_write, reconciliation::text AS reconciliation, error
  FROM customer_lifespan_sync_log
 ORDER BY started_at DESC LIMIT 1
"""
LAST_OK_SQL = """
SELECT finished_at, reconciliation::text AS reconciliation
  FROM customer_lifespan_sync_log
 WHERE status = 'ok' ORDER BY finished_at DESC LIMIT 1
"""

_cache: dict[str, tuple[float, list, date | None]] = {}
_lock = asyncio.Lock()


def invalidate_cache() -> None:
    """Called after a sync so the next page view reads the new rows."""
    _cache.clear()


async def _rows(request: Request) -> tuple[list, date]:
    """Every customer × month × division row, cached ``CACHE_TTL_SECONDS``.

    The as-of date is the latest ship date in the table — NOT today: if the
    sync stops, statuses must freeze with the data instead of every customer
    sliding to "lost" (datalake-table-health).
    """
    pool = get_pool(request)
    async with _lock:
        hit = _cache.get("rows")
        if hit and time.monotonic() - hit[0] < CACHE_TTL_SECONDS:
            rows, as_of = hit[1], hit[2]
        else:
            rows = [dict(r) for r in await pool.fetch(CUSTOMER_MONTHS_SQL)]
            as_of = max((r["last_ship"] for r in rows), default=None)
            _cache["rows"] = (time.monotonic(), rows, as_of)
    if as_of is None:
        raise HTTPException(503, "Customer Lifespan has no data loaded yet")
    return rows, as_of


def _window(window: int) -> int:
    if window not in WINDOWS:
        raise HTTPException(422, f"window must be one of {list(WINDOWS)}")
    return window


async def _customers(request: Request, division: Division, window: int) -> tuple[list[Customer], date]:
    rows, as_of = await _rows(request)
    return build_customers(merge_rows(rows, division.value), as_of, _window(window)), as_of


def _envelope(data, division: Division, window: int, as_of: date, **meta) -> dict:
    return {"success": True, "data": data,
            "meta": {"division": division.value, "window_days": window,
                     "as_of": as_of.isoformat(), **meta}}


def _public_sync(row) -> dict | None:
    """The last run for every viewer — the raw exception stays in the log table
    (it can name tables, roles and columns; review 2026-10-29)."""
    if row is None:
        return None
    out = {k: row[k] for k in ("status", "started_at", "finished_at", "v4_rows", "gap_fills", "v4_last_write")}
    err = row["error"] or ""
    out["error"] = (None if not err else "the datalake stopped updating" if "stale" in err
                    else "the datalake returned too few orders" if "shrink" in err
                    else "sync error — details in the server log")
    return out


_WINDOW_Q = Query(DEFAULT_WINDOW, description="Silence window in days (60, 90 or 180)")


@router.get("/freshness")
async def freshness(request: Request, _user: dict = Depends(require_report_access(REPORT_KEY))):
    """Where the data comes from, how fresh it is, and the Excel-vs-datalake check."""
    pool = get_pool(request)
    sources = [dict(r) for r in await pool.fetch(SOURCES_SQL)]
    last = await pool.fetchrow(LAST_SYNC_SQL)
    ok = await pool.fetchrow(LAST_OK_SQL)
    return {"success": True, "data": {
        "sources": sources,
        "excel_last_ship": EXCEL_LAST_SHIP.isoformat(),
        "cutover": CUTOVER.isoformat(),
        "reconciliation_window_start": TAIL_START.isoformat(),
        "last_sync": _public_sync(last),
        "last_ok_sync_at": ok["finished_at"] if ok else None,
        "reconciliation": ok["reconciliation"] if ok else None,
    }}


@router.get("/{division}/summary")
async def summary_view(request: Request, division: Division, window: int = _WINDOW_Q,
                       _user: dict = Depends(require_report_access(REPORT_KEY))):
    """KPIs: customers in the base, at risk, lost, new, reactivated, lifespans, concentration."""
    cs, as_of = await _customers(request, division, window)
    return _envelope(summary(cs, as_of, window), division, window, as_of)


@router.get("/{division}/trend")
async def trend_view(request: Request, division: Division, window: int = _WINDOW_Q,
                     grain: str = Query("month", description="month, quarter or year"),
                     _user: dict = Depends(require_report_access(REPORT_KEY))):
    """Active / new / lost / reactivated customers, base, revenue and margin per period."""
    if grain not in GRAINS:
        raise HTTPException(422, f"grain must be one of {list(GRAINS)}")
    cs, as_of = await _customers(request, division, window)
    return _envelope(trend(cs, as_of, window, grain), division, window, as_of, grain=grain)


@router.get("/{division}/cohorts")
async def cohorts_view(request: Request, division: Division, window: int = _WINDOW_Q,
                       _user: dict = Depends(require_report_access(REPORT_KEY))):
    """One row per first-load year: new, still in base, lost, lifespans, retention by year."""
    cs, as_of = await _customers(request, division, window)
    return _envelope(cohorts(cs, as_of), division, window, as_of)


@router.get("/{division}/lifespan")
async def lifespan_view(request: Request, division: Division, window: int = _WINDOW_Q,
                        _user: dict = Depends(require_report_access(REPORT_KEY))):
    """Lifespan distribution by status and the Kaplan–Meier survival curve."""
    cs, as_of = await _customers(request, division, window)
    return _envelope(lifespan(cs, as_of), division, window, as_of)


@router.get("/{division}/customers")
async def customers_view(request: Request, division: Division, window: int = _WINDOW_Q,
                         _user: dict = Depends(require_report_access(REPORT_KEY))):
    """Every customer in the division (≈410 rows — filtered and sorted in the browser)."""
    cs, as_of = await _customers(request, division, window)
    rows = sorted((customer_row(c, as_of) for c in cs), key=lambda r: -r["revenue"])
    return _envelope(rows, division, window, as_of, total=len(rows))


@router.get("/{division}/customers/{customer_id}")
async def customer_view(request: Request, division: Division, customer_id: str,
                        window: int = _WINDOW_Q,
                        _user: dict = Depends(require_report_access(REPORT_KEY))):
    """One customer's monthly loads, revenue, margin and margin % since the first load."""
    cs, as_of = await _customers(request, division, window)
    match = next((c for c in cs if c.customer_id == customer_id), None)
    if match is None:
        raise HTTPException(404, f"customer {customer_id} has no loads in {division.value}")
    return _envelope(customer_detail(match, as_of), division, window, as_of)
