"""Email-code login, moved off Vercel.

**Why this exists.** The Next.js frontend used to hold `DATABASE_URL` and talk to
Postgres directly (Prisma) for the login flow. That made Vercel's ~23 *rotating*
AWS egress IPs part of the set of things that must reach Aiven, which is the
single blocker to removing `ip_filter: 0.0.0.0/0` from a Postgres instance
holding 27 databases. Vercel serverless has no stable egress without the paid
Secure Compute add-on, so the cheaper fix is for the frontend to stop touching
Postgres at all. See `/BOT/aiven-mcp/docs/SPEC-security.md`.

**What changed, and what deliberately did not.** The user-visible flow is
unchanged: enter a company email, receive an 8-digit code, type it in. What
changed is where the work happens:

* the code is issued, hashed, stored and mailed **here**, not in
  `lib/auth.ts`'s `sendVerificationRequest`;
* NextAuth drops `PrismaAdapter` + the Resend magic-link provider for a
  Credentials provider whose credential IS the code, verified by `/verify`
  below. That removes the adapter contract entirely (~8 methods with exacting
  date/null semantics) rather than reimplementing it over HTTP — a much smaller
  surface to get wrong, which matters because end-to-end login cannot be
  automatically tested here (nobody can receive the mail).

**Security notes — this is stricter than what it replaces, not looser:**

* The old `email_codes.code` was stored **plaintext**, next to the callback URL
  that would complete the sign-in, so the table held a directly usable
  credential. We store a **SHA-256 hash** and compare hashes.
* The old code was `abs(hash(token)) % 10**8` — a 32-bit non-cryptographic hash
  folded to 8 digits, so codes were biased and predictable from the token.
  Ours comes from `secrets`.
* Verification is a single atomic `DELETE … RETURNING`, so a code cannot be
  redeemed twice by two concurrent requests.
* Brute force is bounded by rate limits, not by an attempt counter: an attempt
  column would need DDL on a live table for a negligible gain. 10 verify/min per
  IP against a 10-minute TTL is at most ~100 guesses per code, i.e. ~1e-6 of the
  1e8 space.

⚠ **`is_active` is returned but NOT enforced.** Today a deactivated user can
still sign in (the Prisma adapter never checked it either) — they simply hold no
roles. Enforcing it here would be a silent behaviour change that could lock
someone out mid-session, so it is surfaced for the caller and left as a
deliberate follow-up decision.
"""

from __future__ import annotations

import hashlib
import logging
import secrets
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from ..config import settings
from ..services.allowed_domains import email_domain, is_org_email
from .deps import require_proxy

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/custom/auth", tags=["auth"])

CODE_TTL_MINUTES = 10
CODE_DIGITS = 8


def _hash_code(code: str) -> str:
    """SHA-256 of the code. No salt on purpose: the input is an 8-digit number,
    so a salt buys nothing against an offline attacker who can enumerate 1e8
    hashes either way. The point is that a DB read alone does not yield a usable
    credential, and that is achieved. The real defences are the 10-minute TTL,
    single use, and the rate limit.
    """
    return hashlib.sha256(code.encode("utf-8")).hexdigest()


def _new_code() -> str:
    """Cryptographically random 8-digit code, zero-padded."""
    return f"{secrets.randbelow(10 ** CODE_DIGITS):0{CODE_DIGITS}d}"


def _hub_pool(request: Request):
    """analytics_hub pool — the app DB this backend already owns."""
    pool = getattr(request.app.state, "pool", None)
    if pool is None:
        raise HTTPException(status_code=503, detail="Application database unavailable")
    return pool


class IssueRequest(BaseModel):
    email: str = Field(min_length=3, max_length=320)
    # Where the frontend wants to land the user after sign-in. Stored so the
    # emailed "sign in directly" link can carry it through, exactly as the old
    # magic-link `callbackUrl` did.
    callback_url: str = Field(default="/", max_length=2000)


class VerifyRequest(BaseModel):
    email: str = Field(min_length=3, max_length=320)
    code: str = Field(min_length=CODE_DIGITS, max_length=CODE_DIGITS)


def _login_email_html(code: str, direct_url: Optional[str]) -> str:
    """Byte-for-byte the same design the frontend sent, so nothing about the
    email changes for users in this migration.
    """
    direct = (
        f'<p style="color: #6B7280; font-size: 14px; margin-top: 24px;">'
        f'Or <a href="{direct_url}" style="color: #2563EB;">click here to sign in '
        f"directly</a>.</p>"
        if direct_url
        else ""
    )
    return f"""
            <div style="font-family: Inter, sans-serif; max-width: 480px; margin: 0 auto; padding: 32px;">
              <h2 style="color: #1B3A5C; margin-bottom: 24px;">UNILINK Space</h2>
              <p style="color: #111827; font-size: 16px;">Your verification code is:</p>
              <p style="font-size: 32px; font-weight: 700; color: #2563EB; letter-spacing: 4px; margin: 24px 0;">{code}</p>
              <p style="color: #6B7280; font-size: 14px;">This code expires in {CODE_TTL_MINUTES} minutes.</p>
              {direct}
            </div>
          """


@router.post("/email-code/issue")
async def issue_email_code(
    body: IssueRequest,
    request: Request,
    _proxy: None = Depends(require_proxy),
):
    """Issue + mail an 8-digit login code. Never returns the code."""
    email = body.email.strip().lower()

    # Tenant-domain guard. Log the DOMAIN only, never the address
    # (SPEC-EMAIL-DOMAIN-POLICY). Mirrors lib/allowed-domains.ts on the
    # frontend, which stays as a UX pre-check — this is the authority.
    if not is_org_email(email):
        logger.warning("login code refused for non-tenant domain: %s", email_domain(email))
        raise HTTPException(status_code=403, detail="Email domain not allowed")

    if not settings.RESEND_API_KEY:
        # Fail loudly: a silent no-op here means nobody can log in and the
        # frontend would show "code sent".
        logger.error("issue_email_code: RESEND_API_KEY is not configured")
        raise HTTPException(status_code=503, detail="Mail transport not configured")

    code = _new_code()
    expires = datetime.now(timezone.utc) + timedelta(minutes=CODE_TTL_MINUTES)
    pool = _hub_pool(request)

    async with pool.acquire() as conn:
        async with conn.transaction():
            # One live code per address, same as the old deleteMany + create.
            await conn.execute("DELETE FROM email_codes WHERE email = $1", email)
            await conn.execute(
                """
                INSERT INTO email_codes (email, code, callback_url, expires)
                VALUES ($1, $2, $3, $4)
                """,
                email,
                _hash_code(code),
                body.callback_url,
                expires,
            )

    # Sent AFTER the row is committed: a mail that arrives before its code is
    # stored is a code that does not work. The reverse (row stored, mail fails)
    # is recoverable — the user just requests another.
    try:
        import resend

        resend.api_key = settings.RESEND_API_KEY
        direct = (
            f"{settings.APP_BASE_URL.rstrip('/')}/login/verify"
            f"?email={email}&code={code}"
            if settings.APP_BASE_URL
            else None
        )
        resend.Emails.send(
            {
                "from": "UNILINK Space <noreply@unilinkportal.com>",
                "to": email,
                "subject": f"Your login code: {code}",
                "html": _login_email_html(code, direct),
            }
        )
    except Exception as e:  # noqa: BLE001 — never leak provider detail to the client
        logger.exception("issue_email_code: Resend send failed: %s", e)
        raise HTTPException(status_code=502, detail="Could not send the code") from e

    return {
        "success": True,
        "data": {"sent": True, "expires_at": expires.isoformat()},
    }


async def _user_payload(conn, user_id) -> dict:
    roles = await conn.fetch(
        """
        SELECT r.name
          FROM user_roles ur
          JOIN roles r ON r.id = ur.role_id
         WHERE ur.user_id = $1
         ORDER BY r.name
        """,
        user_id,
    )
    return {"roles": [r["name"] for r in roles]}


@router.post("/email-code/verify")
async def verify_email_code(
    body: VerifyRequest,
    request: Request,
    _proxy: None = Depends(require_proxy),
):
    """Redeem a code and return the user NextAuth should sign in.

    A wrong code and an expired code are the same 401 on purpose — telling a
    prober which one it was distinguishes "this address has a live code" from
    "this address does not".
    """
    email = body.email.strip().lower()
    code = body.code.strip()

    if not is_org_email(email):
        logger.warning("verify refused for non-tenant domain: %s", email_domain(email))
        raise HTTPException(status_code=403, detail="Email domain not allowed")

    pool = _hub_pool(request)
    async with pool.acquire() as conn:
        async with conn.transaction():
            # Atomic single-use: two concurrent redemptions cannot both win.
            row = await conn.fetchrow(
                """
                DELETE FROM email_codes
                 WHERE email = $1 AND code = $2 AND expires > now()
             RETURNING callback_url
                """,
                email,
                _hash_code(code),
            )
            if row is None:
                raise HTTPException(status_code=401, detail="Invalid or expired code")

            # Same semantics the Prisma adapter had: first sign-in creates the
            # row, later ones just stamp it verified. The daily user sync owns
            # name/department/company, so we never overwrite them here.
            # ⚠ `users.email_verified` is `timestamp WITHOUT time zone` while
            # everything else here is timestamptz, and this backend pins its
            # session to CST (clock.py `_set_cst_session`). A bare `now()` would
            # therefore store CST-naive, while the 47 rows Prisma already wrote
            # hold UTC-naive — the same "5 hours into the future" trap as the
            # freshness stamps. Write UTC explicitly to match the existing rows.
            # `updated_at` IS timestamptz, so plain now() is correct there.
            #
            # `ON CONFLICT (email)` resolves against the unique INDEX
            # `users_email_key` (Prisma creates a unique index, not a
            # constraint — a `pg_constraint` check will not show it).
            user = await conn.fetchrow(
                """
                INSERT INTO users (email, email_verified, updated_at)
                     VALUES ($1, now() AT TIME ZONE 'UTC', now())
                ON CONFLICT (email) DO UPDATE
                        SET email_verified = now() AT TIME ZONE 'UTC',
                            updated_at = now()
                  RETURNING id, email, name, department, company, is_active
                """,
                email,
            )
            extra = await _user_payload(conn, user["id"])

    return {
        "success": True,
        "data": {
            "user": {
                "id": str(user["id"]),
                "email": user["email"],
                "name": user["name"],
                "department": user["department"],
                "company": user["company"],
                # Surfaced, not enforced — see the module docstring.
                "is_active": user["is_active"],
                **extra,
            },
            "callback_url": row["callback_url"],
        },
    }


@router.get("/user-context")
async def user_context(
    request: Request,
    user_id: str,
    _proxy: None = Depends(require_proxy),
):
    """Roles + org fields for an already-signed-in user.

    Backs the JWT refresh in `lib/auth.ts`. The old `session()` callback hit
    Postgres on EVERY session read; routing that through this backend instead
    would put a Render cold start (30-60s) in front of every page load, so the
    frontend caches this in the JWT and refreshes on an interval, keeping the
    previous values if this call fails.
    """
    pool = _hub_pool(request)
    async with pool.acquire() as conn:
        user = await conn.fetchrow(
            """
            SELECT id, email, name, department, company, is_active
              FROM users WHERE id = $1::uuid
            """,
            user_id,
        )
        if user is None:
            raise HTTPException(status_code=404, detail="User not found")
        extra = await _user_payload(conn, user["id"])

    return {
        "success": True,
        "data": {
            "id": str(user["id"]),
            "email": user["email"],
            "name": user["name"],
            "department": user["department"],
            "company": user["company"],
            "is_active": user["is_active"],
            **extra,
        },
    }
