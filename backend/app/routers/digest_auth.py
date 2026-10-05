"""Shared auth gate for e-mail digests PULLED by n8n.

Third pulled digest (after ``ops_team_perf_digest`` and
``dfw_access_doors_digest``, which each carry their own byte-identical copy —
their mutation-checked tests inspect those copies, so they are left in place).
New digests import from here instead of pasting a fourth copy.

Two accepted callers:

  1. a machine bearer ``Authorization: Bearer <REPORTS_CRON_SECRET>`` for n8n,
     which has no portal session and therefore cannot satisfy the normal gate;
  2. otherwise the standard ``require_report_access(<report key>)`` chain, so an
     admin can open the URL through the portal proxy to preview the e-mail.

⚠ ``PROXY_SHARED_SECRET`` is deliberately NOT accepted. Its meaning is "this
request came through our Vercel proxy, so the identity in the Authorization
header is trustworthy" — handing it to a third-party scheduler would let that
scheduler self-assert ``roles:["admin"]`` against every endpoint in the app.
"""
from __future__ import annotations

import hmac
from typing import Optional

from fastapi import Header, HTTPException, Request

from app.config import settings
from app.routers.deps import require_report_access, require_user

# Identity handed to the endpoint when the machine bearer is used. No roles —
# it is not a portal user and must never be mistaken for one downstream.
CRON_IDENTITY = {
    "sub": "reports-cron",
    "email": "reports-cron@internal",
    "name": "Reports cron (n8n)",
    "roles": [],
    "machine": True,
}


def is_cron_bearer(authorization: Optional[str]) -> bool:
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
    # Compare BYTES: compare_digest raises TypeError on a non-ASCII str, which
    # turned a junk header into a 500 instead of a 401.
    return hmac.compare_digest(
        token.strip().encode("utf-8"), expected.encode("utf-8")
    )


def require_digest_access(report_key: str):
    """Machine bearer FIRST, then fall through to ``report_key``'s report gate.

    ``require_report_access`` is invoked as a plain function rather than a
    FastAPI dependency so the fall-through stays conditional — its own
    ``Depends(require_user)`` would otherwise run (and 401) before we ever got
    to look at the machine bearer. Every parameter it declares is forwarded
    explicitly (SPEC-CODE-RULES §40).
    """
    report_gate = require_report_access(report_key)

    async def _check(
        request: Request,
        authorization: Optional[str] = Header(None),
        x_proxy_secret: Optional[str] = Header(None),
    ) -> dict:
        if is_cron_bearer(authorization):
            return dict(CRON_IDENTITY)
        if not authorization:
            raise HTTPException(status_code=401, detail="Not authenticated")
        user = await require_user(
            authorization=authorization, x_proxy_secret=x_proxy_secret
        )
        return await report_gate(request=request, user=user)

    return _check
