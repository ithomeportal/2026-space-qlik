"""DFW - Access Log Doors — "repeat Out of Time" digest endpoint.

Kept in its own router file so the live scope-locked report
(``scoped_access_doors.dfw_router``) stays untouched apart from the SQL
fragments this imports. Same prefix as that report, so a user who can see
``dfw-access-doors`` can open the URL and preview the e-mail.

The consumer is an external n8n workflow that GETs this and mails the HTML —
it does NOT send anything itself. Response envelope:

    {"success": true,
     "data": {"subject": …, "html": …, "generatedAt": …, "meta": {…}}}

    GET /api/custom/dfw-access-doors/delays-email
    GET /api/custom/dfw-access-doors/delays-email?days=14&min_days=4

Auth — two accepted callers (see ``_require_digest_access``), copied from
``ops_team_perf_digest`` so both pulled digests gate identically:

  1. a machine bearer ``Authorization: Bearer <REPORTS_CRON_SECRET>`` for n8n,
     which has no portal session and therefore cannot satisfy the normal gate;
  2. otherwise the standard ``require_report_access("dfw-access-doors")``
     chain, so an admin can open the URL through the portal proxy to preview.

⚠ ``PROXY_SHARED_SECRET`` is deliberately NOT accepted here. Its meaning is
"this request came through our Vercel proxy, so the identity in the
Authorization header is trustworthy" — handing it to a third-party scheduler
would let that scheduler self-assert ``roles:["admin"]`` against every endpoint
in the app.
"""
from __future__ import annotations

import hmac
import logging
from typing import Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request

from app.config import settings
from app.routers.deps import (
    get_datalake_gold_pool,
    require_report_access,
    require_user,
)
from app.services.access_doors_delays_digest import (
    DEFAULT_DAYS,
    DEFAULT_MIN_DAYS,
    build_access_doors_delays_digest,
)

logger = logging.getLogger(__name__)

router = APIRouter(tags=["dfw-access-doors"], prefix="/custom/dfw-access-doors")

REPORT_KEY = "dfw-access-doors"

# Ceilings on the query params. `days` is capped because the CTE scans the
# 128K-row punch table; `min_days` cannot exceed `days` (a threshold larger
# than the window can never be met, which would render a permanent all-clear
# that looks exactly like good news).
MAX_DAYS = 90

# Identity handed to the endpoint when the machine bearer is used. No roles —
# it is not a portal user and must never be mistaken for one downstream.
_CRON_IDENTITY = {
    "sub": "reports-cron",
    "email": "reports-cron@internal",
    "name": "Reports cron (n8n)",
    "roles": [],
    "machine": True,
}


def _is_cron_bearer(authorization: Optional[str]) -> bool:
    """True only when REPORTS_CRON_SECRET is SET and the bearer matches it.

    Fails closed: an unset secret disables this path entirely rather than
    letting an empty string compare equal to an empty header. ``compare_digest``
    keeps the comparison constant-time.
    """
    expected = settings.REPORTS_CRON_SECRET
    if not expected or not authorization:
        return False
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer":
        return False
    return hmac.compare_digest(token.strip(), expected)


def _require_digest_access():
    """Machine bearer FIRST, then fall through to the normal report gate.

    ``require_report_access`` is invoked as a plain function rather than a
    FastAPI dependency so the fall-through stays conditional — its own
    ``Depends(require_user)`` would otherwise run (and 401) before we ever got
    to look at the machine bearer. Every parameter it declares is forwarded
    explicitly (SPEC-CODE-RULES §40).
    """
    report_gate = require_report_access(REPORT_KEY)

    async def _check(
        request: Request,
        authorization: Optional[str] = Header(None),
        x_proxy_secret: Optional[str] = Header(None),
    ) -> dict:
        if _is_cron_bearer(authorization):
            return dict(_CRON_IDENTITY)
        if not authorization:
            raise HTTPException(status_code=401, detail="Not authenticated")
        user = await require_user(
            authorization=authorization, x_proxy_secret=x_proxy_secret
        )
        return await report_gate(request=request, user=user)

    return _check


@router.get("/delays-email")
async def delays_email(
    request: Request,
    days: int = Query(
        DEFAULT_DAYS,
        ge=1,
        le=MAX_DAYS,
        description="Rolling window length in calendar days, ending today (CST).",
    ),
    min_days: int = Query(
        DEFAULT_MIN_DAYS,
        ge=1,
        description=(
            "Inclusive floor on Out of Time days. The default 4 is the "
            'request\'s "more than 3".'
        ),
    ),
    _caller: dict = Depends(_require_digest_access()),
):
    """Render the DFW "repeat Out of Time" e-mail digest.

    Always renders. If nobody exceeds the threshold the body is an explicit
    all-clear panel, never an error and never an empty document — the n8n
    workflow sends this unconditionally, so a silent failure and a clean
    fortnight must not look alike.
    """
    if min_days > days:
        raise HTTPException(
            status_code=400,
            detail=(
                f"min_days ({min_days}) cannot exceed days ({days}) — a "
                "threshold larger than the window can never be met and would "
                "render a permanent all-clear."
            ),
        )

    pool = get_datalake_gold_pool(request)
    data = await build_access_doors_delays_digest(
        pool, days=days, min_days=min_days
    )
    return {"success": True, "data": data}
