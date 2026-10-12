"""Exec Meeting – Recruitment — weekly "Recruitment Status" e-mail digest endpoint.

Own router file so the report router stays untouched; same prefix as the
report, so a user who can see ``exec-meeting-recruitment`` can open the URL to
preview the e-mail.

The consumer is an external n8n workflow (Mondays 16:00 CST) that GETs this
and mails the HTML — it does NOT send anything itself. Response envelope:

    {"success": true,
     "data": {"subject": …, "html": …, "generatedAt": …, "meta": {…}}}

    GET /api/custom/exec-meeting-recruitment/digest-email

No department parameter: the e-mail is always the whole company, so there is
nothing a caller can widen (backend CLAUDE.md §100).

Auth: ``app.routers.digest_auth`` — machine bearer ``REPORTS_CRON_SECRET``
first (fails closed), else the normal report gate.
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Request

from app.routers.digest_auth import require_digest_access
from app.services.exec_recruitment_digest import (
    DigestSourceError,
    DigestStaleError,
    build_recruitment_digest,
)

logger = logging.getLogger(__name__)

router = APIRouter(
    tags=["exec-meeting-recruitment"],
    prefix="/custom/exec-meeting-recruitment",
)

REPORT_KEY = "exec-meeting-recruitment"


@router.get("/digest-email")
async def digest_email(
    request: Request,
    _caller: dict = Depends(require_digest_access(REPORT_KEY)),
):
    """Render the weekly Recruitment Status e-mail for the last completed week.

    A failed source endpoint is a 502 and a dead/drifted Jobs portal a 503,
    never a partial e-mail: n8n retries, then its errorWorkflow alerts — a
    half-empty digest would be read as a quiet week.
    """
    try:
        data = await build_recruitment_digest(request.app)
    except DigestStaleError as exc:
        logger.error("recruitment digest refused: %s", exc)
        raise HTTPException(status_code=503, detail=f"recruitment data unusable: {exc}") from exc
    except DigestSourceError as exc:
        logger.error("recruitment digest: %s", exc)
        raise HTTPException(
            status_code=502, detail="exec-meeting-recruitment source endpoint failed"
        ) from exc
    return {"success": True, "data": data}
