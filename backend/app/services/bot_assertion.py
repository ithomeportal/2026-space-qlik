"""Teams bot assertion (`X-Bot-Assertion`) — the pure half: JWS checks + caches.

Contract: /BOT/teams-chat-ai/docs/SPEC-CONTRACTS.md §1, design in
docs/SPEC-AI-CHAT.md. The Teams bot (teams-chat-ai) signs a 60-second HS256
compact JWS naming the Teams user's email; this module proves the token is
genuine, fresh, single-use and for THIS backend. Mapping the email to the
user's own `users` row + `user_roles` (the real permissions) lives in
`app.routers.bot_identity`.

Why a new path instead of the proxy identity: the proxy's `Authorization:
Bearer <JSON>` is trusted only because `X-Proxy-Secret` proves it came from our
Vercel proxy. Handing that secret to the bot would let it self-assert ANY
identity on EVERY endpoint (incl. `roles:["admin"]`). The assertion instead
names only an email, is accepted on exactly one route, and lives 60 s.

Fails CLOSED: an unset or short secret makes every assertion a 401 — never a
fall-through to another auth path.
"""

from __future__ import annotations

import threading
import time
from collections import OrderedDict, deque
from dataclasses import dataclass

import jwt

from app.config import settings
from app.services.allowed_domains import email_domain, is_org_email

ISSUER = "teams-chat-ai"
AUDIENCE = "unlk-space"
BOT_ASSERTION_HEADER = "X-Bot-Assertion"
ASK_PATH = "/api/custom/ai-chat/ask"
# (method, path) pairs the assertion may authenticate. Everything else is 403.
BOT_ALLOWED_ROUTES = frozenset({("POST", ASK_PATH)})

MIN_SECRET_BYTES = 32
MAX_LIFETIME_SECONDS = 120
LEEWAY_SECONDS = 30
# A jti must stay remembered at least as long as its token could still verify
# (exp + leeway); 180 s covers the contract's 120 s cap + 30 s skew with margin.
REPLAY_TTL_SECONDS = 180
REPLAY_MAX_ENTRIES = 10_000
RATE_LIMIT = 20
RATE_WINDOW_SECONDS = 600

_REQUIRED_CLAIMS = ["iss", "aud", "sub", "iat", "exp", "jti"]


class BotAssertionError(Exception):
    """A rejected assertion. ``detail`` goes to the caller; ``reason`` to the log only."""

    def __init__(self, status_code: int, detail: str, reason: str) -> None:
        super().__init__(reason)
        self.status_code = status_code
        self.detail = detail
        self.reason = reason


@dataclass(frozen=True)
class AssertionClaims:
    email: str
    oid: str
    jti: str
    expires_at: float


def is_bot_route(method: str, path: str) -> bool:
    """True only for the route(s) the assertion may authenticate (trailing slash tolerated)."""
    normalized = path.rstrip("/") or "/"
    return (method.upper(), normalized) in BOT_ALLOWED_ROUTES


def secret_is_usable(secret: str | None) -> bool:
    return bool(secret) and len(secret.encode("utf-8")) >= MIN_SECRET_BYTES


def _invalid(reason: str) -> BotAssertionError:
    # One generic message for every 401: a prober learns nothing about which
    # check failed. The precise reason is logged server-side by the caller.
    return BotAssertionError(401, "invalid bot assertion", reason)


def verify_assertion(token: str, secret: str, *, now: float | None = None) -> AssertionClaims:
    """Verify signature, iss, aud, exp/iat (30 s leeway), lifetime ≤ 120 s, sub, jti.

    Pure: no replay cache, no DB. Raises ``BotAssertionError``.
    """
    if not secret_is_usable(secret):
        raise BotAssertionError(401, "bot assertion not configured", "secret unset or short")
    if not token:
        raise _invalid("empty assertion")
    try:
        claims = jwt.decode(
            token,
            secret,
            algorithms=["HS256"],
            audience=AUDIENCE,
            issuer=ISSUER,
            leeway=LEEWAY_SECONDS,
            options={"require": _REQUIRED_CLAIMS},
        )
    except jwt.PyJWTError as exc:
        raise _invalid(f"{type(exc).__name__}: {exc}") from exc

    # pyjwt accepts a LIST aud that merely contains ours; the contract says exact.
    if not isinstance(claims.get("aud"), str) or claims["aud"] != AUDIENCE:
        raise _invalid("aud is not exactly the audience string")
    iat, exp = claims.get("iat"), claims.get("exp")
    if any(isinstance(v, bool) or not isinstance(v, int | float) for v in (iat, exp)):
        raise _invalid("iat/exp not numeric")
    current = time.time() if now is None else now
    if iat > current + LEEWAY_SECONDS:
        raise _invalid("issued in the future")
    if exp <= iat or exp - iat > MAX_LIFETIME_SECONDS:
        raise _invalid(f"lifetime {exp - iat}s outside (0, {MAX_LIFETIME_SECONDS}]")

    sub, jti = claims.get("sub"), claims.get("jti")
    if not isinstance(sub, str) or not sub.strip():
        raise _invalid("sub missing or not a string")
    # The contract says the bot sends sub lower-cased and trimmed. We REJECT
    # anything else instead of normalising: Unicode case-folding is not
    # injective — "\u212aim@…" (KELVIN SIGN) .lower()s to ASCII "kim@…", i.e.
    # someone else's account. ASCII-only + already-canonical closes that.
    if not sub.isascii() or sub != sub.strip().lower():
        raise _invalid("sub is not a canonical (ASCII, lower-case, trimmed) email")
    if not isinstance(jti, str) or not jti.strip() or len(jti) > 128:
        raise _invalid("jti missing or malformed")
    oid = claims.get("oid")

    return AssertionClaims(
        email=sub,
        oid=str(oid) if oid is not None else "",
        jti=jti,
        expires_at=float(exp),
    )


def check_domain(email: str) -> None:
    """403 unless the email is on one of the 16 tenant domains (shared module)."""
    if not is_org_email(email):
        raise BotAssertionError(
            403, "email domain not allowed", f"non-tenant domain {email_domain(email)}"
        )


class ReplayCache:
    """In-memory jti set with TTL ≥ ``min_ttl_seconds``; bounded, oldest evicted first."""

    def __init__(self, min_ttl_seconds: float = REPLAY_TTL_SECONDS,
                 max_entries: int = REPLAY_MAX_ENTRIES) -> None:
        self._ttl = min_ttl_seconds
        self._max = max_entries
        self._seen: OrderedDict[str, float] = OrderedDict()
        self._lock = threading.Lock()

    def __len__(self) -> int:
        return len(self._seen)

    def check_and_add(self, jti: str, *, expires_at: float, now: float | None = None) -> bool:
        """True when ``jti`` is fresh (and now remembered); False on a replay."""
        current = time.time() if now is None else now
        with self._lock:
            self._purge(current)
            if jti in self._seen:
                return False
            forget_at = max(current + self._ttl, expires_at + LEEWAY_SECONDS)
            self._seen[jti] = forget_at
            while len(self._seen) > self._max:
                self._seen.popitem(last=False)
            return True

    def _purge(self, now: float) -> None:
        expired = [k for k, until in self._seen.items() if until <= now]
        for k in expired:
            del self._seen[k]

    def clear(self) -> None:
        with self._lock:
            self._seen.clear()


class SlidingWindowLimiter:
    """``limit`` hits per ``window_seconds`` per key (in-memory, per process)."""

    def __init__(self, limit: int = RATE_LIMIT, window_seconds: float = RATE_WINDOW_SECONDS) -> None:
        self._limit = limit
        self._window = window_seconds
        self._hits: dict[str, deque[float]] = {}
        self._lock = threading.Lock()

    def hit(self, key: str, *, now: float | None = None) -> bool:
        current = time.time() if now is None else now
        with self._lock:
            self._forget_idle(current)
            bucket = self._hits.setdefault(key, deque())
            while bucket and bucket[0] <= current - self._window:
                bucket.popleft()
            if len(bucket) >= self._limit:
                return False
            bucket.append(current)
            return True

    def _forget_idle(self, now: float) -> None:
        idle = [k for k, b in self._hits.items() if not b or b[-1] <= now - self._window]
        for k in idle:
            del self._hits[k]

    def clear(self) -> None:
        with self._lock:
            self._hits.clear()


replay_cache = ReplayCache()
rate_limiter = SlidingWindowLimiter()


def reset_state() -> None:
    """Test hook: forget every jti and rate-limit hit."""
    replay_cache.clear()
    rate_limiter.clear()


def configured_secret() -> str:
    return settings.TEAMS_BOT_ASSERTION_SECRET or ""
