"""Teams bot assertion (`X-Bot-Assertion`) authenticates the REAL user, narrowly.

Contract: /BOT/teams-chat-ai/docs/SPEC-CONTRACTS.md §1 (aud = "unlk-space"),
local design docs/SPEC-AI-CHAT.md. The bot signs a 60-second HS256 JWS naming
the Teams user's email; this backend maps it to that user's own `users` row and
`user_roles`, so every report's own `require_report_access` decides what the
assistant may read. Pinned here:

- every bad token is a 401 and NEVER falls through to the proxy identity path;
- unset/short secret + header present is a 401, not "everyone passes";
- non-tenant domain, unknown or inactive user is a 403;
- the identity is the real user with the real roles (no elevation);
- only POST /api/custom/ai-chat/ask accepts the header — every other route 403s;
- per-user 20 / 10 min (429); one log line per accepted assertion, never the token.

No DB: the hub pool is an in-memory fake.
"""

from __future__ import annotations

import json
import logging
import time
import uuid
from types import SimpleNamespace

import jwt
import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from app.routers import bot_identity
from app.services import bot_assertion
from app.services.bot_assertion import (
    AUDIENCE,
    BOT_ALLOWED_ROUTES,
    ISSUER,
    BotAssertionError,
    ReplayCache,
    SlidingWindowLimiter,
    is_bot_route,
    verify_assertion,
)

SECRET = "s" * 40
EMAIL = "analyst@unilinktransportation.com"
USER_ID = "11111111-2222-3333-4444-555555555555"
OID = "00000000-aaaa-bbbb-cccc-000000000001"


def _token(secret=SECRET, lifetime=60, iat_offset=0, **overrides):
    now = int(time.time()) + iat_offset
    claims = {
        "iss": ISSUER,
        "aud": AUDIENCE,
        "sub": EMAIL,
        "oid": OID,
        "iat": now,
        "exp": now + lifetime,
        "jti": str(uuid.uuid4()),
    }
    claims.update(overrides)
    claims = {k: v for k, v in claims.items() if v is not None}
    return jwt.encode(claims, secret, algorithm="HS256")


# ---------------------------------------------------------------- fake hub DB


class _Conn:
    def __init__(self, users, roles):
        self.users = users
        self.roles = roles
        self.asked: list[tuple] = []

    async def fetchrow(self, sql, *args):
        self.asked.append((sql, args))

    async def fetch(self, sql, *args):
        self.asked.append((sql, args))
        if "FROM users" in sql:
            row = self.users.get(args[0])
            return row if isinstance(row, list) else ([row] if row else [])
        if "user_roles" in sql:
            return [{"name": r} for r in self.roles]
        return []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_a):
        return False


class _Pool:
    def __init__(self, conn):
        self.conn = conn

    def acquire(self):
        return self.conn


def _user_row(**overrides):
    row = {
        "id": uuid.UUID(USER_ID),
        "email": EMAIL,
        "name": "Ana Analyst",
        "department": "Operations",
        "company": "UNILINK",
        "is_active": True,
    }
    row.update(overrides)
    return row


@pytest.fixture(autouse=True)
def clean_state(monkeypatch):
    monkeypatch.setattr(bot_assertion.settings, "TEAMS_BOT_ASSERTION_SECRET", SECRET, raising=False)
    monkeypatch.setattr(bot_assertion.settings, "PROXY_SHARED_SECRET", "proxy-secret", raising=False)
    bot_assertion.reset_state()
    yield
    bot_assertion.reset_state()


@pytest.fixture
def hub():
    conn = _Conn(users={EMAIL: _user_row()}, roles=["Operations", "CORP"])
    return conn


def _request(hub_conn):
    state = SimpleNamespace(pool=_Pool(hub_conn))
    return SimpleNamespace(app=SimpleNamespace(state=state))


async def _resolve(hub_conn, token):
    return await bot_identity.authenticate_bot(_request(hub_conn), token)


async def _status_of(hub_conn, token):
    with pytest.raises(HTTPException) as exc:
        await _resolve(hub_conn, token)
    return exc.value


# ---------------------------------------------------------------- accept


@pytest.mark.asyncio
async def test_valid_assertion_resolves_the_real_user_and_roles(hub):
    ident = await _resolve(hub, _token())
    assert ident["sub"] == USER_ID, "sub must be users.id, exactly what the proxy sends"
    assert ident["email"] == EMAIL
    assert ident["name"] == "Ana Analyst"
    assert ident["roles"] == ["Operations", "CORP"], "real roles, no elevation"
    assert "admin" not in [r.lower() for r in ident["roles"]]


@pytest.mark.parametrize(
    "sub",
    [
        pytest.param("  analyst@unilinktransportation.com ", id="untrimmed"),
        pytest.param("Analyst@UnilinkTransportation.COM", id="not-lower-cased"),
        # U+212A KELVIN SIGN .lower()s to ASCII "k": it would resolve to ANOTHER
        # user's account (kim@...) if we normalised instead of rejecting.
        pytest.param("\u212aim@unilinktransportation.com", id="kelvin-sign"),
        pytest.param("ｋim@unilinktransportation.com", id="fullwidth-k"),
    ],
)
@pytest.mark.asyncio
async def test_non_canonical_sub_is_401_never_normalised_into_another_user(hub, sub):
    hub.users["kim@unilinktransportation.com"] = _user_row(id=uuid.uuid4(), email="kim@unilinktransportation.com")
    exc = await _status_of(hub, _token(sub=sub))
    assert exc.status_code == 401
    assert not [a for s, a in hub.asked if "FROM users" in s], "no lookup for a rejected sub"


@pytest.mark.asyncio
async def test_canonical_sub_is_looked_up_verbatim(hub):
    await _resolve(hub, _token())
    lookups = [a for s, a in hub.asked if "FROM users" in s]
    assert lookups and lookups[0][0] == EMAIL


def test_user_lookup_is_case_insensitive_sql():
    assert "lower(email)" in bot_identity.USER_BY_EMAIL_SQL.lower()
    assert "is_active" in bot_identity.USER_BY_EMAIL_SQL


@pytest.mark.asyncio
async def test_clock_skew_within_30s_is_accepted(hub):
    # expired 20 s ago — inside the 30 s leeway
    await _resolve(hub, _token(iat_offset=-80, lifetime=60))


@pytest.mark.asyncio
async def test_accept_logs_one_line_without_the_token(hub, caplog):
    token = _token()
    jti = jwt.decode(token, options={"verify_signature": False})["jti"]
    with caplog.at_level(logging.INFO, logger="app.routers.bot_identity"):
        await _resolve(hub, token)
    lines = [r.getMessage() for r in caplog.records if r.name == "app.routers.bot_identity"]
    assert len(lines) == 1
    assert EMAIL in lines[0] and jti in lines[0] and OID in lines[0]
    assert "/api/custom/ai-chat/ask" in lines[0]
    assert token not in " ".join(r.getMessage() for r in caplog.records)


# ---------------------------------------------------------------- 401s


@pytest.mark.parametrize(
    "token_kwargs",
    [
        pytest.param({"secret": "x" * 40}, id="bad-signature"),
        pytest.param({"aud": "unlk-financial"}, id="wrong-aud"),
        pytest.param({"iss": "someone-else"}, id="wrong-iss"),
        pytest.param({"iat_offset": -400}, id="expired"),
        pytest.param({"lifetime": 300}, id="lifetime-over-120s"),
        pytest.param({"iat_offset": 600}, id="issued-in-the-future"),
        pytest.param({"jti": None}, id="missing-jti"),
        pytest.param({"sub": None}, id="missing-sub"),
        pytest.param({"exp": None}, id="missing-exp"),
        pytest.param({"iat": None}, id="missing-iat"),
        pytest.param({"jti": ""}, id="empty-jti"),
        pytest.param({"sub": 12345}, id="non-string-sub"),
        pytest.param({"aud": ["unlk-space", "unlk-financial"]}, id="list-aud"),
        pytest.param({"aud": ["unlk-space"]}, id="single-item-list-aud"),
        pytest.param({"iat": "1700000000"}, id="string-iat"),
        pytest.param({"exp": "9999999999"}, id="string-exp"),
        pytest.param({"exp": True}, id="bool-exp"),
    ],
)
@pytest.mark.asyncio
async def test_bad_tokens_are_401(hub, token_kwargs):
    exc = await _status_of(hub, _token(**token_kwargs))
    assert exc.status_code == 401


@pytest.mark.asyncio
async def test_alg_none_is_401(hub):
    now = int(time.time())
    token = jwt.encode(
        {"iss": ISSUER, "aud": AUDIENCE, "sub": EMAIL, "iat": now, "exp": now + 60,
         "jti": str(uuid.uuid4())},
        key=None, algorithm="none",
    )
    assert (await _status_of(hub, token)).status_code == 401


@pytest.mark.asyncio
async def test_garbage_and_empty_header_are_401(hub):
    assert (await _status_of(hub, "not-a-jwt")).status_code == 401
    assert (await _status_of(hub, "")).status_code == 401


@pytest.mark.asyncio
async def test_replayed_jti_is_401(hub):
    token = _token()
    await _resolve(hub, token)
    exc = await _status_of(hub, token)
    assert exc.status_code == 401


@pytest.mark.parametrize("secret", ["", "short-secret", "y" * 31])
@pytest.mark.asyncio
async def test_unconfigured_or_short_secret_is_401(monkeypatch, hub, secret):
    monkeypatch.setattr(bot_assertion.settings, "TEAMS_BOT_ASSERTION_SECRET", secret)
    exc = await _status_of(hub, _token(secret=secret or "z" * 40))
    assert exc.status_code == 401
    assert exc.detail == "bot assertion not configured"


@pytest.mark.asyncio
async def test_401_detail_is_generic(hub):
    exc = await _status_of(hub, _token(secret="x" * 40))
    assert exc.detail == "invalid bot assertion"


# ---------------------------------------------------------------- 403s


@pytest.mark.asyncio
async def test_non_tenant_domain_is_403(hub):
    exc = await _status_of(hub, _token(sub="someone@gmail.com"))
    assert exc.status_code == 403


@pytest.mark.asyncio
async def test_unknown_email_is_403(hub):
    exc = await _status_of(hub, _token(sub="nobody@unilinktransportation.com"))
    assert exc.status_code == 403
    assert exc.detail == "no portal account for this email"


@pytest.mark.asyncio
async def test_inactive_user_is_403(hub):
    hub.users[EMAIL] = _user_row(is_active=False)
    exc = await _status_of(hub, _token())
    assert exc.status_code == 403
    assert exc.detail == "no portal account for this email"


# ---------------------------------------------------------------- rate limit


@pytest.mark.asyncio
async def test_per_user_rate_limit_20_per_10_minutes(hub):
    for _ in range(20):
        await _resolve(hub, _token())
    exc = await _status_of(hub, _token())
    assert exc.status_code == 429


@pytest.mark.asyncio
async def test_rate_limit_is_per_user(hub):
    other = "other@unilinktransportation.com"
    hub.users[other] = _user_row(id=uuid.uuid4(), email=other)
    for _ in range(20):
        await _resolve(hub, _token())
    await _resolve(hub, _token(sub=other))


def test_rate_limiter_window_slides():
    lim = SlidingWindowLimiter(limit=2, window_seconds=600)
    assert lim.hit("u", now=0) and lim.hit("u", now=1)
    assert not lim.hit("u", now=2)
    assert lim.hit("u", now=601.5)


def test_replay_cache_expires_and_is_bounded():
    cache = ReplayCache(min_ttl_seconds=180, max_entries=3)
    assert cache.check_and_add("a", expires_at=10, now=0) is True
    assert cache.check_and_add("a", expires_at=10, now=5) is False, "replay inside TTL"
    # TTL is at least 180 s even when exp is sooner
    assert cache.check_and_add("a", expires_at=10, now=100) is False
    assert cache.check_and_add("a", expires_at=10, now=181) is True
    for j in "bcdef":
        cache.check_and_add(j, expires_at=10_000, now=200)
    assert len(cache) <= 3


def test_constants_match_the_contract():
    assert ISSUER == "teams-chat-ai"
    assert AUDIENCE == "unlk-space"
    assert BOT_ALLOWED_ROUTES == frozenset({("POST", "/api/custom/ai-chat/ask")})
    assert bot_assertion.MAX_LIFETIME_SECONDS == 120
    assert bot_assertion.LEEWAY_SECONDS == 30
    assert bot_assertion.REPLAY_TTL_SECONDS >= 180
    assert (bot_assertion.RATE_LIMIT, bot_assertion.RATE_WINDOW_SECONDS) == (20, 600)


def test_verify_assertion_is_pure_and_reports_the_reason():
    with pytest.raises(BotAssertionError) as exc:
        verify_assertion(_token(aud="unlk-financial"), SECRET)
    assert exc.value.status_code == 401
    assert exc.value.reason  # server-side detail exists, caller never sees it


# ---------------------------------------------------------------- route restriction


def test_only_the_ask_route_is_a_bot_route():
    assert is_bot_route("POST", "/api/custom/ai-chat/ask")
    assert is_bot_route("POST", "/api/custom/ai-chat/ask/")
    assert not is_bot_route("GET", "/api/custom/ai-chat/ask")
    assert not is_bot_route("POST", "/api/custom/ai-chat/other")
    assert not is_bot_route("GET", "/api/reports")


@pytest.mark.parametrize(
    "method,path",
    [
        ("GET", "/api/reports"),
        ("GET", "/api/custom/ceo-cockpit/summary"),
        ("GET", "/api/custom/ai-chat/ask"),
        ("POST", "/api/admin/users"),
        ("GET", "/api/custom/auth/user-context?user_id=" + USER_ID),
    ],
)
def test_header_on_any_other_route_is_403_through_the_real_app(method, path):
    from app.main import app

    client = TestClient(app)
    resp = client.request(method, path, headers={"X-Bot-Assertion": _token()})
    assert resp.status_code == 403, resp.text


def test_ask_route_is_mounted_in_the_real_app():
    from app.main import app

    routes = {(m, r.path) for r in app.routes for m in (getattr(r, "methods", None) or ())}
    assert ("POST", "/api/custom/ai-chat/ask") in routes


@pytest.mark.asyncio
async def test_bad_assertion_never_falls_through_to_the_proxy_identity(hub):
    """A valid proxy identity next to a bad assertion is still a 401."""
    req = _request(hub)
    with pytest.raises(HTTPException) as exc:
        await bot_identity.require_ai_chat_user(
            req,
            x_bot_assertion=_token(secret="x" * 40),
            authorization='Bearer {"sub": "' + USER_ID + '", "roles": ["admin"]}',
            x_proxy_secret="proxy-secret",
        )
    assert exc.value.status_code == 401


@pytest.mark.asyncio
async def test_proxy_identity_still_works_without_the_header(hub):
    ident = await bot_identity.require_ai_chat_user(
        _request(hub),
        x_bot_assertion=None,
        authorization="Bearer " + json.dumps({"sub": USER_ID, "email": EMAIL, "roles": ["CORP"]}),
        x_proxy_secret="proxy-secret",
    )
    assert ident["sub"] == USER_ID and ident["roles"] == ["CORP"]


@pytest.mark.asyncio
async def test_no_header_and_no_credentials_is_401(hub):
    with pytest.raises(HTTPException) as exc:
        await bot_identity.require_ai_chat_user(
            _request(hub), x_bot_assertion=None, authorization=None, x_proxy_secret=None,
        )
    assert exc.value.status_code == 401


@pytest.mark.asyncio
async def test_empty_assertion_header_never_falls_through_to_the_proxy_identity(hub):
    """An EMPTY header is still the bot path — a valid proxy identity must not rescue it."""
    with pytest.raises(HTTPException) as exc:
        await bot_identity.require_ai_chat_user(
            _request(hub),
            x_bot_assertion="",
            authorization='Bearer {"sub": "' + USER_ID + '", "roles": ["admin"]}',
            x_proxy_secret="proxy-secret",
        )
    assert exc.value.status_code == 401


def test_anthropic_sdk_is_a_pinned_dependency():
    from pathlib import Path

    reqs = (Path(__file__).resolve().parents[1] / "requirements.txt").read_text().splitlines()
    pins = [r for r in reqs if r.startswith("anthropic")]
    assert pins and pins[0].startswith("anthropic=="), "pin the SDK like every other dependency"


@pytest.mark.asyncio
async def test_two_active_users_with_one_email_is_403_not_a_guess(hub):
    """lower(email) can match two rows whose case differs; never pick one's roles at random."""
    hub.users[EMAIL] = [_user_row(), _user_row(id=uuid.uuid4(), email=EMAIL.upper())]
    exc = await _status_of(hub, _token())
    assert exc.status_code == 403


@pytest.mark.asyncio
async def test_proxy_path_fails_closed_while_the_proxy_secret_is_unset(hub, monkeypatch):
    """require_user is fail-OPEN app-wide; this route spends money and must not be."""
    monkeypatch.setattr(bot_assertion.settings, "PROXY_SHARED_SECRET", "")
    with pytest.raises(HTTPException) as exc:
        await bot_identity.require_ai_chat_user(
            _request(hub),
            x_bot_assertion=None,
            authorization='Bearer {"sub": "' + USER_ID + '", "roles": ["admin"]}',
            x_proxy_secret=None,
        )
    assert exc.value.status_code == 401


def test_rate_limiter_forgets_idle_keys():
    lim = SlidingWindowLimiter(limit=2, window_seconds=10)
    lim.hit("a", now=0)
    lim.hit("b", now=100)  # "a" is idle past its window
    assert "a" not in lim._hits
