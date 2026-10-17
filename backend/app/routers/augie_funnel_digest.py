"""Funnel Augie Activities — daily "Augie Funnel" e-mail digest endpoint.

Own router file so the report router stays untouched; same prefix as the
report, so a user who can see ``augie-funnel`` can open the URL to preview the
e-mail.

The consumer is an external n8n workflow (daily 07:00 CST) that GETs this and
mails the HTML — it does NOT send anything itself. Response envelope:

    {"success": true,
     "data": {"subject": …, "html": …, "generatedAt": …, "meta": {…}}}

    GET /api/custom/augie-funnel/digest-email

No unit / team parameter: the e-mail is always company-wide, so there is
nothing a caller can widen (backend CLAUDE.md §100). The closed day is always
yesterday (CST); there is deliberately no ``day=`` override on the wire.

Auth: ``app.routers.digest_auth`` — machine bearer ``REPORTS_CRON_SECRET``
first (fails closed), else the normal report gate.
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Request

from app.routers.augie_funnel import REPORT_KEY
from app.routers.digest_auth import require_digest_access
from app.services.augie_funnel_digest import (
    DigestSourceError,
    DigestStaleError,
    build_augie_funnel_digest,
)

logger = logging.getLogger(__name__)

router = APIRouter(tags=["augie-funnel"], prefix=f"/custom/{REPORT_KEY}")


@router.get("/digest-email")
async def digest_email(
    request: Request,
    _caller: dict = Depends(require_digest_access(REPORT_KEY)),
):
    """Render the daily Augie Funnel e-mail for yesterday's close.

    A failed source endpoint is a 502 and a stopped load feed a 503, never a
    partial e-mail: n8n retries, then its errorWorkflow alerts — a half-empty
    digest would be read as a quiet day.
    """
    try:
        data = await build_augie_funnel_digest(request.app)
    except DigestStaleError as exc:
        logger.error("augie funnel digest refused: %s", exc)
        raise HTTPException(status_code=503, detail=f"augie feed unusable: {exc}") from exc
    except DigestSourceError as exc:
        logger.error("augie funnel digest: %s", exc)
        raise HTTPException(
            status_code=502, detail="augie-funnel source endpoint failed"
        ) from exc
    return {"success": True, "data": data}
