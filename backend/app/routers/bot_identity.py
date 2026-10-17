"""Identity for the AI chat route: Teams bot assertion OR the normal proxy identity.

- `X-Bot-Assertion` present ⇒ the bot path, and ONLY the bot path: verify the
  assertion (`app.services.bot_assertion`), map its email to the user's own
  `users` row + `user_roles` (exactly how `/custom/auth/user-context` resolves
  roles), and return the same identity dict the Vercel proxy would send. A bad
  assertion is a 401 even if a valid proxy identity rides along — never a
  fall-through.
- header absent ⇒ the existing `require_user` proxy path, unchanged.

`bot_assertion_route_guard` (mounted in main.py) 403s the header on every other
route, so the assertion can never authenticate anything but
POST /api/custom/ai-chat/ask.

⚠ Audit lines are WARNING, not INFO: `logger.info` does not reach Render's log
stream (CLAUDE.md, Deployments), and the contract wants one visible line per
accepted assertion. Never log the token.
"""

from __future__ import annotations

import logging

from fastapi import Header, HTTPException, Request
from fastapi.responses import JSONResponse

from app.config import settings
from app.routers.auth_email import _user_payload
from app.routers.deps import require_user
from app.services import bot_assertion
from app.services.allowed_domains import email_domain
from app.services.bot_assertion import (
    ASK_PATH,
    BOT_ASSERTION_HEADER,
    BotAssertionError,
    check_domain,
    is_bot_route,
    verify_assertion,
)

logger = logging.getLogger(__name__)

# Case-insensitive on purpose: the bot lower-cases `sub`, but `users.email` is
# synced from the time-off DB with whatever casing HR typed. `users` is a few
# hundred rows, so the non-sargable lower() is irrelevant.
USER_BY_EMAIL_SQL = """
    SELECT id, email, name, department, company, is_active
      FROM users
     WHERE lower(email) = $1
       AND is_active = TRUE
"""

NO_ACCOUNT = "no portal account for this email"


def _hub_pool(request: Request):
    pool = getattr(request.app.state, "pool", None)
    if pool is None:
        raise HTTPException(status_code=503, detail="Application database unavailable")
    return pool


async def _lookup_identity(request: Request, email: str) -> dict | None:
    """The proxy-shaped identity for an active user, or None."""
    async with _hub_pool(request).acquire() as conn:
        rows = [r for r in await conn.fetch(USER_BY_EMAIL_SQL, email) if r["is_active"]]
        if len(rows) != 1:
            # 0 = no account; 2+ = two active rows whose emails differ only in
            # case — never guess whose roles to use.
            if len(rows) > 1:
                logger.warning("bot assertion refused: %d active users share one email", len(rows))
            return None
        user = rows[0]
        extra = await _user_payload(conn, user["id"])
    # Same keys, same meaning as frontend/app/api/proxy/[...path]/route.ts.
    return {
        "sub": str(user["id"]),
        "email": user["email"],
        "name": user["name"],
        "roles": list(extra["roles"]),
        "department": user["department"],
        "company": user["company"],
    }


def _reject(exc: BotAssertionError) -> HTTPException:
    logger.warning("bot assertion rejected status=%s reason=%s", exc.status_code, exc.reason)
    return HTTPException(status_code=exc.status_code, detail=exc.detail)


async def authenticate_bot(request: Request, token: str) -> dict:
    """Verify an `X-Bot-Assertion` and return the REAL user's identity. Raises HTTPException."""
    try:
        claims = verify_assertion(token, bot_assertion.configured_secret())
    except BotAssertionError as exc:
        raise _reject(exc) from None

    if not bot_assertion.replay_cache.check_and_add(claims.jti, expires_at=claims.expires_at):
        raise _reject(BotAssertionError(401, "invalid bot assertion", f"replayed jti {claims.jti}"))

    try:
        check_domain(claims.email)
    except BotAssertionError as exc:
        raise _reject(exc) from None

    identity = await _lookup_identity(request, claims.email)
    if identity is None:
        logger.warning(
            "bot assertion refused: no active portal user (domain=%s, jti=%s)",
            email_domain(claims.email), claims.jti,
        )
        raise HTTPException(status_code=403, detail=NO_ACCOUNT)

    if not bot_assertion.rate_limiter.hit(identity["sub"]):
        logger.warning("bot assertion throttled user=%s jti=%s", identity["sub"], claims.jti)
        raise HTTPException(status_code=429, detail="too many requests")

    logger.warning(
        "bot assertion accepted email=%s oid=%s route=%s jti=%s",
        claims.email, claims.oid, ASK_PATH, claims.jti,
    )
    return identity


async def require_ai_chat_user(
    request: Request,
    x_bot_assertion: str | None = Header(None, alias=BOT_ASSERTION_HEADER),
    authorization: str | None = Header(None),
    x_proxy_secret: str | None = Header(None),
) -> dict:
    """FastAPI dependency for POST /api/custom/ai-chat/ask."""
    if x_bot_assertion is not None:
        return await authenticate_bot(request, x_bot_assertion)
    if not authorization:
        raise HTTPException(status_code=401, detail="Not authenticated")
    if not settings.PROXY_SHARED_SECRET:
        # require_user is deliberately fail-OPEN app-wide while the secret is
        # unset. This route spends money per call and the rate limit keys on
        # the caller-chosen `sub`, so here an unverifiable identity is a 401.
        raise HTTPException(status_code=401, detail="Not authenticated")
    identity = await require_user(authorization=authorization, x_proxy_secret=x_proxy_secret)
    # The model call costs money per question; the portal path shares the bot's
    # per-user budget so no caller can run it unbounded.
    if not bot_assertion.rate_limiter.hit(str(identity.get("sub"))):
        raise HTTPException(status_code=429, detail="too many requests")
    return identity


async def bot_assertion_route_guard(request: Request, call_next):
    """403 any request that carries `X-Bot-Assertion` to a route other than the ask route."""
    if BOT_ASSERTION_HEADER.lower() in request.headers and not is_bot_route(
        request.method, request.url.path
    ):
        logger.warning(
            "bot assertion refused on non-allowlisted route %s %s",
            request.method, request.url.path,
        )
        return JSONResponse(
            status_code=403, content={"detail": "bot assertion not accepted on this route"}
        )
    return await call_next(request)
