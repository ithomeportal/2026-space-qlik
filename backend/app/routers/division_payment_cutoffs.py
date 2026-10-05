"""Division Payment Calculator — Recalculations tab (Bruno PDF 2026-10-05, p.3).

Replaces the five vendor demo recalculation records with the real thing:

* one row per month from January 2025 through the PREVIOUS month, newest
  first, with its live v4 TEAM-DFW totals (R1, R2);
* a month is final on the 10th of the following month. From September 2026 on,
  the first run after that cutoff freezes every order of the month
  (``dpc_cutoff_orders``, written by ``daily_dpc_cutoff_snapshot``);
* a tracked month lists the orders whose amounts moved since the freeze (R3),
  diffed in Python because the snapshot (analytics_hub) and v4 (gold) live in
  different databases.

⚠ DISPLAY ONLY (Diego 2026-10-05). The 25 % / 75 % split is shown, but nothing
here feeds a month's net payment — the Δ keeps moving while v4 changes, and
auto-applying it would shift numbers that were already approved.

⚠ A tracked month's Δ comes from the per-order diff, not from live-total −
snapshot-total: v4 sums carry sub-cent decimals, the diff rounds each order to
the cent, and the month's Δ must equal the sum of the orders printed under it.
"""

from __future__ import annotations

import asyncio
import logging
from decimal import Decimal
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from app.clock import cst_today
from app.routers.deps import get_pool, require_report_access
from app.routers.division_payment import (
    RECALC_AO_SHARE,
    RECALC_CORP_SHARE,
    REPORT_KEY,
    _gold_pool,
    _money,
)
from app.services.division_payment_v4 import (
    AMOUNT_COLS,
    FIRST_MONTH,
    MONTH_ORDER,
    TRACKING_START,
    add_months,
    cutoff_date,
    cutoff_status,
    diff_orders,
    fetch_month_orders,
    fetch_month_totals,
    month_index,
    month_label,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/custom/division-payment", tags=["division-payment"])
_access = require_report_access(REPORT_KEY)


def _amounts_out(d: dict[str, Decimal] | None) -> dict[str, float] | None:
    return None if d is None else {c: _money(d[c]) for c in AMOUNT_COLS}


def _parse_month(year: int, month: str) -> tuple[int, str, int]:
    month = month.strip().lower()
    if month not in MONTH_ORDER:
        raise HTTPException(status_code=422, detail="Unknown month")
    return year, month, month_index(month)


async def _snapshot_orders(pool, year: int, month: str) -> list:
    return await pool.fetch(
        """
        SELECT order_id AS id, company_id, customer_id, customer_name,
               total_charge, total_carrier_pay, margin_amt
          FROM dpc_cutoff_orders
         WHERE year = $1 AND month = $2
        """,
        year, month,
    )


async def _month_diff(pool, gold, year: int, month: str, month_num: int) -> dict[str, Any]:
    snapshot = await _snapshot_orders(pool, year, month)
    try:
        live = await fetch_month_orders(gold, year, month_num)
    except Exception as e:  # noqa: BLE001 — a 503, never an empty diff
        logger.error("Division Payment cutoff diff read failed: %s", e, exc_info=True)
        raise HTTPException(status_code=503, detail="Datalake unavailable") from e
    return diff_orders(snapshot, live)


@router.get("/cutoffs")
async def cutoffs(request: Request, user: dict = Depends(_access)):
    """Every month through the previous one, with its close status and Δ."""
    pool = get_pool(request)
    gold = _gold_pool(request)
    today = cst_today()
    last = add_months(today.year, today.month, -1)

    try:
        totals = await fetch_month_totals(gold, FIRST_MONTH, last)
    except Exception as e:  # noqa: BLE001
        logger.error("Division Payment cutoff totals read failed: %s", e, exc_info=True)
        raise HTTPException(status_code=503, detail="Datalake unavailable") from e

    snaps = {
        (r["year"], r["month"]): r
        for r in await pool.fetch(
            "SELECT year, month, captured_at, revenue, carrier_cost, profit, "
            "order_count, note FROM dpc_cutoffs"
        )
    }

    # Tracked months' diffs run CONCURRENTLY — one v4 month scan each, and the
    # list grows by one month a month.
    tracked = [
        (y, mn) for (y, mn) in totals if (y, MONTH_ORDER[mn - 1]) in snaps
    ]
    diffs = dict(zip(tracked, await asyncio.gather(*(
        _month_diff(pool, gold, y, MONTH_ORDER[mn - 1], mn) for y, mn in tracked
    ))))

    out = []
    for (y, mn), t in sorted(totals.items(), reverse=True):
        month = MONTH_ORDER[mn - 1]
        snap = snaps.get((y, month))
        status = cutoff_status(y, mn, today, snap is not None)
        row: dict[str, Any] = {
            "year": y, "month": month, "month_label": month_label(y, mn),
            "period_start": f"{y:04d}-{mn:02d}-01",
            "cutoff_date": cutoff_date(y, mn).isoformat(),
            "status": status,
            "live": {
                "revenue": _money(t.revenue), "carrier_cost": _money(t.carrier_cost),
                "profit": _money(t.profit), "order_count": t.order_count,
            },
            "snapshot": None, "delta": None, "ao_share": None,
            "corporate_share": None, "changed_count": None,
            "note": snap["note"] if snap else "",
        }
        if snap is not None:
            diff = diffs[(y, mn)]
            tot = diff["totals"]
            row.update({
                "snapshot": {
                    "revenue": _money(snap["revenue"]),
                    "carrier_cost": _money(snap["carrier_cost"]),
                    "profit": _money(snap["profit"]),
                    "order_count": snap["order_count"],
                    "captured_at": snap["captured_at"].isoformat(),
                },
                "delta": {
                    "revenue": _money(tot["total_charge"]),
                    "carrier_cost": _money(tot["total_carrier_pay"]),
                    "profit": _money(tot["margin_amt"]),
                },
                "ao_share": _money(tot["margin_amt"] * RECALC_AO_SHARE),
                "corporate_share": _money(tot["margin_amt"] * RECALC_CORP_SHARE),
                "changed_count": len(diff["changes"]),
            })
        out.append(row)

    return {"success": True, "data": {
        "tracking_start": {"year": TRACKING_START[0], "month": MONTH_ORDER[TRACKING_START[1] - 1]},
        "months": out,
    }}


@router.get("/cutoffs/{year}/{month}/orders")
async def cutoff_orders(year: int, month: str, request: Request, user: dict = Depends(_access)):
    """The orders of one tracked month whose amounts moved after its cutoff."""
    pool = get_pool(request)
    year, month, month_num = _parse_month(year, month)
    snap = await pool.fetchrow(
        "SELECT captured_at FROM dpc_cutoffs WHERE year = $1 AND month = $2", year, month
    )
    if snap is None:
        raise HTTPException(status_code=404, detail=f"{month} {year} has no cutoff snapshot")
    diff = await _month_diff(pool, _gold_pool(request), year, month, month_num)
    return {"success": True, "data": {
        "year": year, "month": month,
        "captured_at": snap["captured_at"].isoformat(),
        "changes": [
            {**c, "before": _amounts_out(c["before"]), "after": _amounts_out(c["after"]),
             "delta": _amounts_out(c["delta"])}
            for c in diff["changes"]
        ],
        "totals": _amounts_out(diff["totals"]),
    }}


class CutoffNote(BaseModel):
    note: str = Field(default="", max_length=4000)


@router.put("/cutoffs/{year}/{month}/note")
async def save_cutoff_note(
    year: int, month: str, body: CutoffNote, request: Request, user: dict = Depends(_access),
):
    """Refacturación notes against a tracked month."""
    pool = get_pool(request)
    year, month, _ = _parse_month(year, month)
    updated = await pool.fetchval(
        "UPDATE dpc_cutoffs SET note = $3, note_updated_at = NOW(), note_updated_by = $4 "
        "WHERE year = $1 AND month = $2 RETURNING year",
        year, month, body.note, user.get("email") or user.get("sub"),
    )
    if updated is None:
        raise HTTPException(status_code=404, detail=f"{month} {year} has no cutoff snapshot")
    return {"success": True, "data": {"year": year, "month": month}}
