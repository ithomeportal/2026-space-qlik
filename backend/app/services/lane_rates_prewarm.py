"""Nightly pre-warm of lane_market_rates for the eSavings report.

Runs at 5 AM CST. For every distinct US lane in the current MTD month + the
previous closed month, ensures both SONAR and 123LB caches are populated.
Closed-month rows that already exist are skipped (they never change).
"""

from __future__ import annotations

import asyncio
import logging
from datetime import date

import httpx

from app.clock import cst_today
from app.services.lane_rates import (
    Lane,
    fetch_lb123_history,
    fetch_sonar_history,
    get_cached_rates,
    make_lane,
    upsert_rates,
)

logger = logging.getLogger(__name__)

_PREWARM_CONCURRENCY = 6


def _previous_month(d: date) -> date:
    if d.month == 1:
        return date(d.year - 1, 12, 1)
    return date(d.year, d.month - 1, 1)


async def prewarm_lane_market_rates(pool) -> dict:
    """Iterate distinct lanes in the last two months and back-fill the cache."""
    if pool is None:
        logger.warning("[lane-rates prewarm] no savings pool; skipping")
        return {"status": "skipped", "reason": "no-pool"}

    today = cst_today()
    months = [
        date(today.year, today.month, 1),
        _previous_month(date(today.year, today.month, 1)),
    ]

    rows = await pool.fetch(
        """
        SELECT DISTINCT origin_name, dest_name
          FROM public.carriers_savings_results_report
         WHERE month_date = ANY($1::date[])
        """,
        months,
    )

    unique: dict[tuple, Lane] = {}
    for r in rows:
        ln = make_lane(r["origin_name"] or "", r["dest_name"] or "", "VAN")
        if not ln or not ln.is_us:
            continue
        unique[(ln.origin_city, ln.origin_state, ln.dest_city, ln.dest_state, ln.equipment)] = ln

    lanes = list(unique.values())
    yms = [f"{m.year:04d}-{m.month:02d}" for m in months]

    cached_sonar = await get_cached_rates(pool, lanes, yms, "sonar")
    cached_lb123 = await get_cached_rates(pool, lanes, yms, "lb123")

    def _missing(ln: Lane, cache) -> bool:
        # If either of the two months is missing, refetch (the API call covers
        # 12-24 months in one shot anyway).
        return any(
            (ln.origin_city, ln.origin_state, ln.dest_city, ln.dest_state, ln.equipment, ym)
            not in cache
            for ym in yms
        )

    todo_sonar = [ln for ln in lanes if _missing(ln, cached_sonar)]
    todo_lb123 = [ln for ln in lanes if _missing(ln, cached_lb123)]

    sem = asyncio.Semaphore(_PREWARM_CONCURRENCY)
    sonar_ok = sonar_err = 0
    lb123_ok = lb123_err = 0

    async def _do_sonar(client: httpx.AsyncClient, ln: Lane) -> None:
        nonlocal sonar_ok, sonar_err
        async with sem:
            try:
                history = await fetch_sonar_history(client, ln, months=24)
                if history:
                    await upsert_rates(pool, ln, "sonar", history)
                    sonar_ok += 1
                else:
                    sonar_err += 1
            except Exception as exc:
                sonar_err += 1
                logger.info("[lane-rates prewarm] sonar fail %s→%s: %s",
                            ln.origin_city, ln.dest_city, exc)

    async def _do_lb123(client: httpx.AsyncClient, ln: Lane) -> None:
        nonlocal lb123_ok, lb123_err
        async with sem:
            try:
                history = await fetch_lb123_history(client, ln, months=12)
                if history:
                    await upsert_rates(pool, ln, "lb123", history)
                    lb123_ok += 1
                else:
                    lb123_err += 1
            except Exception as exc:
                lb123_err += 1
                logger.info("[lane-rates prewarm] lb123 fail %s→%s: %s",
                            ln.origin_city, ln.dest_city, exc)

    async with httpx.AsyncClient() as client:
        await asyncio.gather(
            *(_do_sonar(client, ln) for ln in todo_sonar),
            *(_do_lb123(client, ln) for ln in todo_lb123),
            return_exceptions=True,
        )

    summary = {
        "status": "ok",
        "lanes_total": len(lanes),
        "sonar": {"refetched": len(todo_sonar), "ok": sonar_ok, "err": sonar_err},
        "lb123": {"refetched": len(todo_lb123), "ok": lb123_ok, "err": lb123_err},
        "months": yms,
    }
    logger.info("[lane-rates prewarm] %s", summary)
    return summary
