"""READ_ONLY_EMAILS: named people who may view Space and change nothing.

Owner decision: from 2026-11-05 bkimbark@ is an external Financial Advisor, read-only
in every /BOT app. Space has no viewer role (24 write routes use
`require_report_access`, so whoever reads a report can write it), and his TagRoles must
stay so the reports stay visible. So the rule is enforced here, ahead of every router,
including any added later.

A constant, not an env var: an unset var would silently allow writes.

⚠ Identity is what `require_user` trusts: the Authorization JSON, and only once
`X-Proxy-Secret` proves the proxy built it from a validated session. A request without
that proof is passed on untouched, because the handler answers 401 by itself.

⚠ `is_active` is not enforced at login, so it is no substitute for this guard.
"""

from __future__ import annotations

import hmac
import json
import logging

from fastapi import Request
from fastapi.responses import JSONResponse

from app.config import settings

logger = logging.getLogger(__name__)

READ_ONLY_EMAILS: frozenset[str] = frozenset({"bkimbark@unilinktransportation.com"})

SAFE_METHODS: frozenset[str] = frozenset({"GET", "HEAD", "OPTIONS"})

READ_ONLY_EXEMPT_WRITES: frozenset[str] = frozenset(
    {
        # Login: issues and redeems the code. The session does not exist yet.
        "/api/custom/auth/email-code/issue",
        "/api/custom/auth/email-code/verify",
        # A question to the AI assistant is a read: its tools can only GET a report
        # the caller can already open (`ai_chat_tools`), and it stores nothing.
        "/api/custom/ai-chat/ask",
    }
)

REFUSAL_CODE = "READ_ONLY_USER"
REFUSAL_MESSAGE = "Your account is read-only in Space: you can view reports but not change anything."


def request_email(authorization: str | None) -> str | None:
    """The e-mail in a proxy identity header, lower-cased and trimmed, else None."""
    if not authorization or not authorization.startswith("Bearer "):
        return None
    try:
        payload = json.loads(authorization[7:])
    except ValueError:
        return None
    email = payload.get("email") if isinstance(payload, dict) else None
    return email.strip().lower() if isinstance(email, str) else None


def _proxy_proved(secret_header: str | None) -> bool:
    """Same rule as `require_user`, including its fail-open while the secret is unset."""
    expected = settings.PROXY_SHARED_SECRET
    if not expected:
        return True
    return bool(secret_header) and hmac.compare_digest(secret_header, expected)


async def read_only_guard(request: Request, call_next):
    """403 a non-safe request from a READ_ONLY_EMAILS session before any handler runs."""
    if request.method in SAFE_METHODS or request.url.path in READ_ONLY_EXEMPT_WRITES:
        return await call_next(request)
    if not _proxy_proved(request.headers.get("x-proxy-secret")):
        return await call_next(request)
    if request_email(request.headers.get("authorization")) not in READ_ONLY_EMAILS:
        return await call_next(request)
    # WARNING: `logger.info` does not reach Render's log stream. Path only.
    logger.warning("read-only user refused: %s %s", request.method, request.url.path)
    return JSONResponse(
        status_code=403,
        content={"success": False, "code": REFUSAL_CODE, "error": REFUSAL_MESSAGE, "detail": REFUSAL_MESSAGE},
    )
