"""Approved figures for the Bonus Calculators: lock, unlock and the stored report.

HR pays from this screen (Daniela Nava, 2026-11-05), and Space recomputes every
month from live loads, so a locked month kept moving after it was paid: August
was paid at $504.08 per person and later showed $501.28. Approving a month now
stores the whole report beside the lock, and the screen serves that report for as
long as the month stays approved.

Reverses R16's "no report-JSON freeze" (CIO, 2026-11-05). The trade-off: a later
correction reaches an approved month only through an unlock and a re-approve.

Going forward only. A month locked before this shipped has no stored row and
stays live. Approving it again stores nothing, because today's figures are not
what was paid; only an explicit unlock + approve can record a new set.

⚠ Every function takes a REQUIRED scope, and each calculator has its own table
(SPEC-BONUS-CALCULATOR, §78 §100).
"""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.encoders import jsonable_encoder
from pydantic import BaseModel, Field

from app.routers.bonus_roster_writes import PERIOD_PATTERN
from app.routers.deps import get_pool

if TYPE_CHECKING:
    from app.routers.bonus_calculator import BonusScope

logger = logging.getLogger("uvicorn.error")

APPROVED_SOURCE = "Approved figures, stored when this month was approved"

# The live comparison is optional. It must give up well before the proxy's 45 s
# abort, or a saturated gold pool would take the stored figures away too.
LIVE_COMPARISON_TIMEOUT_S = 20


class LockBody(BaseModel):
    """⚠ MODULE level: a model inside a factory 500s /openapi.json."""

    period_key: str = Field(pattern=PERIOD_PATTERN)
    # The grand total HR was looking at. Approve stores a fresh build, so it must
    # prove that build is the screen HR reviewed.
    reviewed_total_usd: float


async def load_approved_record(primary, period_key: str, scope: BonusScope) -> dict | None:
    """The newest stored report, only while the month is approved."""
    row = await primary.fetchrow(
        f"""
        SELECT s.report_json, l.status, l.approved_by, l.approved_at
        FROM {scope.tbl_paid} s
        JOIN {scope.tbl_lock} l
          ON l.period_key = s.period_key
         -- Both are NOW() in one transaction. A lock written any other way (a
         -- rollback to old code, a hand fix) must not inherit an older record.
         AND l.approved_at = s.approved_at
        WHERE s.period_key = $1 AND l.status = 'approved'
        ORDER BY s.id DESC
        LIMIT 1
        """,
        period_key,
    )
    if row is None:
        return None
    report = row["report_json"]
    return {
        "report": json.loads(report) if isinstance(report, str) else report,
        "lock": {
            "status": row["status"],
            "approvedBy": row["approved_by"],
            "approvedAt": row["approved_at"].isoformat() if row["approved_at"] else None,
        },
    }


async def store_approval(
    primary, period_key: str, report: dict, approved_by: str | None, scope: BonusScope
) -> bool:
    """Write the lock and the stored report in ONE transaction.

    The lock insert decides a race: of two simultaneous approvals, only the one
    that turned the row approved stores a report. Returns False for the other.
    """
    payload = json.dumps(jsonable_encoder(report))
    async with primary.acquire() as conn:
        async with conn.transaction():
            locked = await conn.fetchrow(
                f"""
                INSERT INTO {scope.tbl_lock} (period_key, status, approved_by, approved_at)
                VALUES ($1, 'approved', $2, NOW())
                ON CONFLICT (period_key) DO UPDATE
                  SET status = 'approved', approved_by = EXCLUDED.approved_by, approved_at = NOW()
                  WHERE {scope.tbl_lock}.status <> 'approved'
                RETURNING period_key
                """,
                period_key,
                approved_by,
            )
            if locked is None:
                return False
            await conn.execute(
                f"""
                INSERT INTO {scope.tbl_paid} (period_key, report_json, approved_by, approved_at)
                VALUES ($1, $2::jsonb, $3, NOW())
                """,
                period_key,
                payload,
                approved_by,
            )
    return True


def _grand_total(report: dict) -> float:
    return float(report["totals"]["grandBonusUsd"])


def _approved_report(record: dict, live: dict | None) -> dict:
    """The stored report with today's lock, plus how far live has moved from it."""
    approved_total = _grand_total(record["report"])
    live_total = _grand_total(live) if live is not None else None
    lock = record["lock"]
    return {
        **record["report"],
        "source": APPROVED_SOURCE,
        "lock": lock,
        # Stored as "Connected / Live datalake", which is no longer what this is.
        "dataSource": {
            **record["report"].get("dataSource", {}),
            "status": "Approved",
            "lastSyncLabel": "Stored at approval",
        },
        "approvedRecord": {
            "approvedAt": lock["approvedAt"],
            "approvedBy": lock["approvedBy"],
            "approvedTotalUsd": round(approved_total, 2),
            "liveTotalUsd": round(live_total, 2) if live_total is not None else None,
            "differenceUsd": round(live_total - approved_total, 2) if live_total is not None else None,
        },
    }


async def report_for_display(
    primary,
    period_key: str,
    build_live: Callable[[], Awaitable[dict]],
    scope: BonusScope,
) -> dict:
    """What `/report` serves: stored figures if approved with a record, else live.

    A month with no record is byte-identical to before, including failing loudly
    when gold is down. With a record, gold only feeds the comparison, so an outage
    must not take the approved figures away.
    """
    record = await load_approved_record(primary, period_key, scope)
    if record is None:
        return await build_live()
    try:
        live = await asyncio.wait_for(build_live(), LIVE_COMPARISON_TIMEOUT_S)
    except Exception as exc:  # noqa: BLE001 — the stored figures do not need it
        logger.warning("%s bonus %s: live comparison unavailable: %s", scope.key, period_key, exc)
        live = None
    return _approved_report(record, live)


def _assert_report_is_the_one_reviewed(report: dict, body: LockBody) -> None:
    """Refuse to freeze figures nobody looked at.

    An empty read turns into $0 without raising, and a re-rated load changes the
    total between the screen and this click. Either would otherwise stay on screen
    until someone unlocks the month.
    """
    if sum(t.get("monthlyLoads") or 0 for t in report["teams"]) == 0:
        raise HTTPException(
            status_code=503,
            detail=f"{body.period_key} was NOT locked: no loads were read for this month.",
        )
    built = round(_grand_total(report), 2)
    reviewed = round(body.reviewed_total_usd, 2)
    if abs(built - reviewed) >= 0.01:
        raise HTTPException(
            status_code=409,
            detail=(
                f"{body.period_key} was NOT locked: the total changed from ${reviewed:,.2f} on "
                f"screen to ${built:,.2f}. Review the updated figures and approve again."
            ),
        )


def register_lock_routes(
    router: APIRouter,
    scope: BonusScope,
    write_gate,
    build_live: Callable[[Request, str], Awaitable[dict]],
    parse_period: Callable[[str], object],
) -> None:
    """POST /lock and DELETE /lock/{period_key} for one calculator."""

    @router.post("/lock")
    async def lock_period(
        request: Request,
        body: LockBody,
        user: dict = Depends(write_gate),
    ):
        """Approve a month: store its report and lock it, or do neither."""
        parse_period(body.period_key)
        primary = get_pool(request)
        already = await primary.fetchval(
            f"SELECT 1 FROM {scope.tbl_lock} WHERE period_key = $1 AND status = 'approved'",
            body.period_key,
        )
        if already:
            return {"success": True, "data": {"stored": False}}
        try:
            report = await build_live(request, body.period_key)
        except Exception as exc:  # noqa: BLE001 — turned into a refusal the screen shows
            logger.error("%s bonus %s: approval refused: %s", scope.key, body.period_key, exc)
            raise HTTPException(
                status_code=503,
                detail=(
                    f"{body.period_key} was NOT locked: the figures could not be read. "
                    "Please try again in a few minutes."
                ),
            ) from exc
        _assert_report_is_the_one_reviewed(report, body)
        stored = await store_approval(
            primary,
            body.period_key,
            report,
            user.get("email") or user.get("name") or user.get("sub"),
            scope,
        )
        return {"success": True, "data": {"stored": stored}}

    @router.delete("/lock/{period_key}")
    async def unlock_period(
        request: Request,
        period_key: str,
        user: dict = Depends(write_gate),
    ):
        """Return a month to live figures. Stored reports stay as the audit trail."""
        parse_period(period_key)
        primary = get_pool(request)
        await primary.execute(f"DELETE FROM {scope.tbl_lock} WHERE period_key = $1", period_key)
        return {"success": True}
