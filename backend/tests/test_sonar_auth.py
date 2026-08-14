"""SONAR credential handling — pins the 2026-07-22 expiry outage.

What happened: `SONAR_TOKEN` was minted 2025-07-22 with a 365-day life and
expired 2026-07-22. `_sonar_token_value()` returned the static token
**unconditionally**, so the backend kept presenting a dead credential, SONAR
answered a bare 401, and `lane_rates` logged that per lane — 4,063 warning lines
in one prewarm pass — while the job still reported `status: "ok"`.

Two separate defects, both pinned here:
  1. an expired static token outranked working username/password credentials
     forever, so *setting* the fallback would have fixed nothing;
  2. one rejection disabled the feature for the whole process instead of
     reaching for that fallback.
"""

import base64
import json
import time

import pytest

from app.services import lane_rates as lr


def _jwt(exp: float | None) -> str:
    """A structurally valid JWT with the given exp. Signature is never checked."""
    def seg(d: dict) -> str:
        return base64.urlsafe_b64encode(json.dumps(d).encode()).decode().rstrip("=")
    claims = {"sub": "svc", "iss": "sonar", "iat": 1721674573}
    if exp is not None:
        claims["exp"] = exp
    return f"{seg({'alg': 'HS256', 'typ': 'JWT'})}.{seg(claims)}.sig"


@pytest.fixture(autouse=True)
def _reset_module_state(monkeypatch):
    """Module-level breaker/caches leak between tests otherwise."""
    monkeypatch.setattr(lr, "_static_token_rejected", False, raising=False)
    monkeypatch.setattr(lr, "_sonar_disabled_reason", None, raising=False)
    monkeypatch.setattr(lr, "_sonar_token", None, raising=False)
    monkeypatch.setattr(lr, "_sonar_kma_cache", None, raising=False)
    for var in ("SONAR_TOKEN", "SONAR_USERNAME", "SONAR_PASSWORD"):
        monkeypatch.delenv(var, raising=False)


# --- the exp guard --------------------------------------------------------
def test_reads_exp_from_a_real_shaped_jwt():
    assert lr._jwt_exp(_jwt(1786500000.0)) == 1786500000.0


def test_exp_absent_or_unparseable_returns_none():
    assert lr._jwt_exp(_jwt(None)) is None
    assert lr._jwt_exp("not-a-jwt") is None
    assert lr._jwt_exp("") is None


@pytest.mark.asyncio
async def test_live_static_token_is_used(monkeypatch):
    tok = _jwt(time.time() + 86_400)
    monkeypatch.setenv("SONAR_TOKEN", tok)
    assert await lr._sonar_token_value(client=None) == tok


@pytest.mark.asyncio
async def test_expired_static_token_is_not_presented(monkeypatch):
    """THE production bug: this used to return the dead token."""
    monkeypatch.setenv("SONAR_TOKEN", _jwt(time.time() - 86_400))
    assert await lr._sonar_token_value(client=None) is None


@pytest.mark.asyncio
async def test_token_without_exp_is_still_used(monkeypatch):
    """No exp claim means we cannot know it is dead — send it and find out."""
    tok = _jwt(None)
    monkeypatch.setenv("SONAR_TOKEN", tok)
    assert await lr._sonar_token_value(client=None) == tok


# --- the fallback ---------------------------------------------------------
@pytest.mark.asyncio
async def test_expired_token_falls_through_to_password_auth(monkeypatch):
    """The exact production fix: an expired token must not outrank credentials."""
    monkeypatch.setenv("SONAR_TOKEN", _jwt(time.time() - 86_400))
    monkeypatch.setenv("SONAR_USERNAME", "u")
    monkeypatch.setenv("SONAR_PASSWORD", "p")

    class _Resp:
        status_code = 200
        def raise_for_status(self): pass
        def json(self): return {"token": "MINTED"}

    class _Client:
        async def post(self, *a, **k): return _Resp()

    assert await lr._sonar_token_value(_Client()) == "MINTED"


def test_rejection_falls_back_instead_of_disabling(monkeypatch):
    monkeypatch.setenv("SONAR_TOKEN", _jwt(None))
    monkeypatch.setenv("SONAR_USERNAME", "u")
    monkeypatch.setenv("SONAR_PASSWORD", "p")

    assert lr._handle_auth_rejection("KMARef (HTTP 401)") is True
    assert lr._static_token_rejected is True
    assert lr.sonar_status()["ok"] is True, "must NOT disable while a fallback exists"


def test_rejection_with_no_fallback_disables_once(monkeypatch):
    monkeypatch.setenv("SONAR_TOKEN", _jwt(None))
    assert lr._handle_auth_rejection("KMARef (HTTP 401)") is False
    assert lr.sonar_status()["ok"] is False
    assert "KMARef" in lr.sonar_status()["reason"]


def test_a_rejected_static_token_is_not_presented_again(monkeypatch):
    monkeypatch.setenv("SONAR_TOKEN", _jwt(None))
    monkeypatch.setenv("SONAR_USERNAME", "u")
    monkeypatch.setenv("SONAR_PASSWORD", "p")
    lr._handle_auth_rejection("rate statistics (HTTP 401)")
    # Second rejection has no fallback left to try, so now it disables.
    assert lr._handle_auth_rejection("rate statistics (HTTP 401)") is False
    assert lr.sonar_status()["ok"] is False


def test_breaker_states_the_reason_once(monkeypatch):
    lr._sonar_disable("first")
    lr._sonar_disable("second")
    assert lr.sonar_status()["reason"] == "first", "the first cause must win"
