"""Ops Portal Overview — "Performance for Team N" digest endpoint.

Kept in its own router file so the live UI report stays untouched apart from
the helpers this imports. (``ops_portal_overview`` became a PACKAGE on
2026-08-14 — this module imports ``CORP_TEAMS`` through its façade, which is
why that re-export must survive any future re-split.) Same prefix as its
neighbours, so a user who can see the report can preview its digest.

The consumer is an external n8n workflow that GETs this and mails the HTML —
it does NOT send anything itself. Response envelope:

    {"success": true,
     "data": {"subject": …, "html": …, "generatedAt": …, "meta": {…}}}

    GET /api/custom/ops-portal-overview/team-digest-email?team=TEAM1

Auth — two accepted callers (see ``_require_digest_access``):

  1. a machine bearer ``Authorization: Bearer <REPORTS_CRON_SECRET>`` for n8n,
     which has no portal session and therefore cannot satisfy the normal gate;
  2. otherwise the standard ``require_report_access("ops-portal-overview")``
     chain, so an admin can open the URL through the portal proxy to preview.
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
from app.routers.ops_portal_overview import CORP_TEAMS
from app.services.team_perf_digest import build_team_perf_digest

logger = logging.getLogger(__name__)

router = APIRouter(tags=["ops-portal-overview"], prefix="/custom/ops-portal-overview")

REPORT_KEY = "ops-portal-overview"

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


@router.get("/team-digest-email")
async def team_digest_email(
    request: Request,
    team: str = Query("TEAM1", description="CORP team id, e.g. TEAM1"),
    teams: Optional[str] = Query(
        None,
        description=(
            "Comma-separated multi-team scope for the combined CORP digest, "
            "e.g. TEAM1,TEAM2,TEAM3,TEAM4. Overrides `team` when present."
        ),
    ),
    _caller: dict = Depends(_require_digest_access()),
):
    """Render the "Performance for Team N" or "PERFORMANCE CORP" e-mail digest.

    ``team=TEAM4``                      → one team, exactly as before.
    ``teams=TEAM1,TEAM2,TEAM3,TEAM4``   → the four teams aggregated into ONE
                                          report (the PERFORMANCE CORP email).

    The multi-team scope is pushed into SQL, not assembled from four responses
    — see ``build_team_perf_digest`` for why that distinction is load-bearing.
    """
    if teams is not None:
        scope = [t.strip().upper() for t in teams.split(",") if t.strip()]
        if not scope:
            raise HTTPException(
                status_code=400, detail="teams must name at least one team"
            )
    else:
        scope = [(team or "").strip().upper()]

    unknown = [t for t in scope if t not in CORP_TEAMS]
    if unknown:
        raise HTTPException(
            status_code=400,
            detail=(
                f"unknown team(s) {', '.join(unknown)} — "
                f"must be one of {', '.join(CORP_TEAMS)}"
            ),
        )
    # De-duplicate while preserving order: a repeated id would otherwise widen
    # nothing but would show up in the header and the footer scope line.
    scope = list(dict.fromkeys(scope))

    pool = get_datalake_gold_pool(request)
    data = await build_team_perf_digest(request.app, pool, scope)
    return {"success": True, "data": data}
