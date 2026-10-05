"""Attrition WoW — weekly "Atrition WOW -Week N" e-mail digest endpoint.

Own router file so the 1.7k-line UI router stays untouched; same prefix as the
report, so a user who can see ``attrition-wow`` can open the URL to preview.

The consumer is an external n8n workflow (Mondays 08:15 CST) that GETs this
and mails the HTML — it does NOT send anything itself. Response envelope:

    {"success": true,
     "data": {"subject": …, "html": …, "generatedAt": …, "meta": {…}}}

    GET /api/custom/attrition-wow/digest-email

No scope parameter: the e-mail is always UNILINK + CORP + DFW in one document,
so there is nothing a caller can widen (backend CLAUDE.md §100).

Auth: ``app.routers.digest_auth`` — machine bearer ``REPORTS_CRON_SECRET``
first (fails closed), else the normal ``attrition-wow`` report gate.
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Request

from app.routers.digest_auth import require_digest_access
from app.services.attrition_wow_digest import (
    DigestSourceError,
    DigestStaleError,
    build_attrition_wow_digest,
)

logger = logging.getLogger(__name__)

router = APIRouter(tags=["attrition-wow"], prefix="/custom/attrition-wow")

REPORT_KEY = "attrition-wow"


@router.get("/digest-email")
async def digest_email(
    request: Request,
    _caller: dict = Depends(require_digest_access(REPORT_KEY)),
):
    """Render the weekly Attrition WoW e-mail for the last completed week.

    A failed source endpoint is a 502, never a partial e-mail: n8n retries,
    then its errorWorkflow alerts — a half-empty digest would be sent and read
    as good news.
    """
    try:
        data = await build_attrition_wow_digest(request.app)
    except DigestStaleError as exc:
        logger.error("attrition-wow digest refused, stale datalake: %s", exc)
        raise HTTPException(
            status_code=503, detail=f"datalake is stale: {exc}"
        ) from exc
    except DigestSourceError as exc:
        logger.error("attrition-wow digest: %s", exc)
        raise HTTPException(
            status_code=502, detail="attrition-wow source endpoint failed"
        ) from exc
    return {"success": True, "data": data}
