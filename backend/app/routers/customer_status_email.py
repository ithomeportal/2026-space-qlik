"""Customer E-mail Activity — the Ops panel over the PCA load-status e-mails.

    GET  /api/custom/customer-status-email/activity?days=7&report=   sends log + today's grid
    GET  /api/custom/customer-status-email/reports                   the 4 reports + schedule
    GET  /api/custom/customer-status-email/{key}/preview             the e-mail as it would go NOW
    POST /api/custom/customer-status-email/{key}/send-test           mail it NOW — ADMIN only,
                                                                     ALWAYS test routing

The scheduler in ``main.py`` is the product; this report lets Ops see what was
sent, when and to whom (request 2026-10-20, "activity panel"), and preview an
e-mail. Read gate = the report's TagRoles (``require_digest_access``: machine
bearer ``REPORTS_CRON_SECRET`` first, fails closed, then ``role_report_access``).
``{key}`` is validated against the configured reports — unknown = 404, never a
default.
"""
from __future__ import annotations

import json
import logging
from datetime import timedelta
from typing import Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request
from fastapi.responses import HTMLResponse

from app.clock import cst_now
from app.config import settings
from app.routers.deps import get_pool, require_admin, require_user
from app.routers.digest_auth import CRON_IDENTITY, is_cron_bearer, require_digest_access
from app.services.customer_status_email.config import REPORTS, REPORTS_BY_KEY
from app.services.customer_status_email.data import StaleFeedError
from app.services.customer_status_email.html import render
from app.services.customer_status_email.sender import (
    ACTIVITY_SQL,
    build_all,
    routing_for,
    send_test_now,
    test_banner,
)

logger = logging.getLogger(__name__)

REPORT_KEY = "customer-status-email"
# A slot with no log row this long after its hour is MISSED — the job never ran
# (a dead dyno, an unregistered job). The :20 retry is inside this grace.
MISSED_AFTER = timedelta(minutes=45)

router = APIRouter(tags=["customer-status-email"], prefix=f"/custom/{REPORT_KEY}")
_read_gate = require_digest_access(REPORT_KEY)


async def require_admin_or_cron(
    authorization: Optional[str] = Header(None),
    x_proxy_secret: Optional[str] = Header(None),
) -> dict:
    if is_cron_bearer(authorization):
        return dict(CRON_IDENTITY)
    if not authorization:
        raise HTTPException(status_code=401, detail="Not authenticated")
    user = await require_user(authorization=authorization, x_proxy_secret=x_proxy_secret)
    return await require_admin(user=user)


def _report_or_404(key: str):
    report = REPORTS_BY_KEY.get(key)
    if report is None:
        raise HTTPException(status_code=404, detail="Unknown customer report")
    return report


def _json(value):
    return json.loads(value) if isinstance(value, str) else value


def today_grid(rows: list[dict], now) -> list[dict]:
    """Every (report, send hour) of TODAY with its outcome — including the ones
    that never ran, which a log alone cannot show (absence of a row is not health)."""
    today = now.strftime("%Y-%m-%d")
    by_slot = {(r["report_key"], r["slot_key"]): r for r in rows}
    grid = []
    for report in REPORTS:
        slots = []
        for hour in report.send_hours:
            row = by_slot.get((report.key, f"{today} {hour:02d}"))
            due = now.replace(hour=hour, minute=0, second=0, microsecond=0)
            if row:
                state = row["status"]
            elif now >= due + MISSED_AFTER:
                state = "missed"
            else:
                state = "upcoming"
            slots.append({"hour": hour, "status": state,
                          "sentAt": row["finished_at"] if row else None})
        grid.append({"key": report.key, "subject": report.subject, "slots": slots})
    return grid


@router.get("/activity")
async def activity(
    request: Request,
    days: int = Query(7, ge=1, le=90),
    report: Optional[str] = Query(None),
    _caller: dict = Depends(_read_gate),
):
    if report is not None:
        _report_or_404(report)
    async with get_pool(request).acquire() as conn:
        rows = [dict(r) for r in await conn.fetch(ACTIVITY_SQL, days, report)]
    for r in rows:
        for col in ("counts", "recipients", "loads"):
            r[col] = _json(r[col])
    now = cst_now()
    if report is None:
        today_rows = rows
    else:
        async with get_pool(request).acquire() as conn:
            today_rows = [dict(r) for r in await conn.fetch(ACTIVITY_SQL, 1, None)]
    return {
        "success": True,
        "data": {
            "rows": rows,
            "today": today_grid(today_rows, now),
            "live": bool(settings.CUSTOMER_STATUS_EMAIL_LIVE),
            "enabled": bool(settings.CUSTOMER_STATUS_EMAIL_ENABLED),
            "now": now.strftime("%Y-%m-%dT%H:%M:%S"),
        },
        "meta": {"total": len(rows), "page": 1, "limit": 1000},
    }


@router.get("/reports")
async def list_reports(_caller: dict = Depends(_read_gate)):
    return {
        "success": True,
        "data": {
            "live": bool(settings.CUSTOMER_STATUS_EMAIL_LIVE),
            "enabled": bool(settings.CUSTOMER_STATUS_EMAIL_ENABLED),
            "reports": [
                {"key": r.key, "subject": r.subject, "sendHoursCst": list(r.send_hours),
                 "destinations": [d.code for d in r.destinations],
                 "from": r.send_from, "to": list(r.to), "cc": list(r.cc)}
                for r in REPORTS
            ],
        },
    }


@router.get("/{key}/preview", response_class=HTMLResponse)
async def preview(key: str, request: Request, _caller: dict = Depends(_read_gate)):
    report = _report_or_404(key)
    now = cst_now()
    try:
        by_key, _ = await build_all(request.app, now)
    except StaleFeedError as exc:
        raise HTTPException(status_code=503, detail=f"order feed unusable: {exc}") from exc
    rc = by_key[report.key]
    routing = routing_for(report, live=bool(settings.CUSTOMER_STATUS_EMAIL_LIVE))
    return HTMLResponse(render(rc, now, test_banner(report, routing)))


@router.post("/{key}/send-test")
async def send_test(key: str, request: Request,
                    _caller: dict = Depends(require_admin_or_cron)):
    report = _report_or_404(key)
    try:
        result = await send_test_now(request.app, report.key)
    except StaleFeedError as exc:
        raise HTTPException(status_code=503, detail=f"order feed unusable: {exc}") from exc
    except Exception as exc:  # noqa: BLE001 — build (DB/pool) or Graph send
        logger.error("customer status email test send %s failed: %s", key, exc, exc_info=True)
        raise HTTPException(status_code=502, detail=f"test send failed: {type(exc).__name__}") from exc
    return {"success": True, "data": result}
