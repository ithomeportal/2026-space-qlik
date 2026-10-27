"""Code-made report: Collections Settlement Forecast (request 2026-10-27).

"What are we expecting to collect and to pay this week, are we cash-flow
positive?" — and the 13 weeks after it. Definitions: ``services/cash_forecast``
(this week) and ``services/cash_forecast_weeks`` (weeks, customers, accuracy);
spec: docs/SPEC-COLLECTIONS-SETTLEMENT-FORECAST.md.

Every section reads ONE cached ``Sources`` load (60 s per CST week), so the four
tabs of one page view cost one round of UNLK-Financial reads, and the Teams AI
reading /this-week sees the same numbers as the page.
"""
from __future__ import annotations

import asyncio
import logging
import time

from fastapi import APIRouter, Depends, HTTPException, Request

from app.clock import cst_today
from app.routers.deps import get_financial_pool, require_report_access
from app.services.cash_forecast import Sources, finance_week
from app.services.cash_forecast_snapshot import accuracy_since, read_snapshots
from app.services.cash_forecast_sources import freshness, load_sources
from app.services.cash_forecast_weeks import compute_accuracy, compute_all, compute_by_customer

logger = logging.getLogger(__name__)

REPORT_KEY = "collections-settlement-forecast"
CACHE_TTL_SECONDS = 60.0

router = APIRouter(tags=[REPORT_KEY], prefix=f"/custom/{REPORT_KEY}")

_cache: dict[str, tuple[float, Sources, dict]] = {}
_lock = asyncio.Lock()


async def _load(request: Request) -> tuple[Sources, dict]:
    """Today's sources + ``compute_all``, cached ``CACHE_TTL_SECONDS``.

    The lock makes concurrent tabs share ONE read instead of stampeding the
    UNLK-Financial pool (max 3 connections).
    """
    pool = get_financial_pool(request)
    gold = getattr(request.app.state, "savings_pool", None)
    today = cst_today()
    key = today.isoformat()
    async with _lock:
        hit = _cache.get(key)
        if hit and time.monotonic() - hit[0] < CACHE_TTL_SECONDS:
            return hit[1], hit[2]
        src = await load_sources(pool, gold, finance_week(today), today)
        result = compute_all(src)
        _cache.clear()
        _cache[key] = (time.monotonic(), src, result)
        return src, result


def _envelope(data, src: Sources, **meta) -> dict:
    return {"success": True, "data": data, "meta": {"freshness": freshness(src), **meta}}


@router.get("/this-week")
async def this_week(request: Request, _user: dict = Depends(require_report_access(REPORT_KEY))):
    """Cash in (collected / due / past due; committed vs expected) vs out (settlements + AP)."""
    src, result = await _load(request)
    return _envelope(result["this_week"], src)


@router.get("/weeks")
async def weeks(request: Request, _user: dict = Depends(require_report_access(REPORT_KEY))):
    """This week + 12: expected cash in, settlements, AP, net and cumulative."""
    src, result = await _load(request)
    return _envelope(result["rows"], src, **result["meta"])


@router.get("/by-customer")
async def by_customer(request: Request, _user: dict = Depends(require_report_access(REPORT_KEY))):
    """Bruce's per-customer expected collections, this week + 4, with open AR."""
    src, result = await _load(request)
    rows = compute_by_customer(src, result["forecasts"])
    if rows is None:
        raise HTTPException(status_code=503, detail="Shipped revenue or average pay days could not be read")
    return _envelope(rows, src, total=len(rows))


@router.get("/accuracy")
async def accuracy(request: Request, _user: dict = Depends(require_report_access(REPORT_KEY))):
    """Forecast vs actual for the last 12 weeks (stored daily forecasts vs receipts)."""
    src, _ = await _load(request)
    hub = getattr(request.app.state, "pool", None)
    snapshots: list[dict] = []
    if hub is not None:
        try:
            snapshots = await read_snapshots(hub, accuracy_since(src.week.start))
        except Exception as e:  # the history half reads as empty, the receipts half stays
            logger.warning("cash forecast accuracy: snapshot read failed: %s", e)
    rows = compute_accuracy(snapshots, src.receipts_by_week, src.week)
    first = min((s["snapshot_date"] for s in snapshots), default=None)
    return _envelope(rows, src, first_snapshot=first.isoformat() if first else None)


@router.get("/sources")
async def sources(request: Request, _user: dict = Depends(require_report_access(REPORT_KEY))):
    """When each source was last refreshed, and which failed."""
    src, _ = await _load(request)
    return _envelope(freshness(src), src)
