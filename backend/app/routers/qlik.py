import time
import uuid

import jwt
from fastapi import APIRouter, Depends, Request
from slowapi import Limiter
from slowapi.util import get_remote_address

from app.config import settings
from app.routers.deps import require_user

router = APIRouter(tags=["qlik"])

limiter = Limiter(key_func=get_remote_address)

# Universal viewer identity — ONE Qlik user for ALL portal users.
# Avoids per-user licensing and simplifies auth.
# Your portal (NextAuth) still controls who sees which reports via roles.
VIEWER_SUB = "portal-viewer@unilinktransportation.com"
VIEWER_NAME = "Analytics Portal Viewer"
VIEWER_EMAIL = "portal-viewer@unilinktransportation.com"


def _generate_viewer_jwt() -> str:
    """Generate a JWT for the universal portal viewer identity."""
    now = time.time()
    payload = {
        "sub": VIEWER_SUB,
        "name": VIEWER_NAME,
        "email": VIEWER_EMAIL,
        "groups": ["Viewers"],
        "jti": str(uuid.uuid4()),
        "iat": int(now),
        "nbf": int(now),
        "exp": int(now + 3600),
        "iss": settings.QLIK_ISSUER,
        "aud": "qlik.api/login/jwt-session",
    }
    return jwt.encode(
        payload,
        settings.QLIK_PRIVATE_KEY,
        algorithm="RS256",
        headers={"kid": settings.QLIK_KEY_ID},
    )


@router.post("/qlik/viewer-token")
@limiter.limit("30/minute")
async def get_viewer_token(
    request: Request,
    user: dict = Depends(require_user),
):
    """Return a JWT for the universal portal viewer.

    All portal users share the same Qlik identity (portal-viewer).
    Access control is handled by the portal (NextAuth roles), not Qlik.

    Never cache the token: Qlik's ``/login/jwt-session`` enforces one-time use
    per JWT (rejects a reused ``jti`` with "jwt token has already been used").
    A fresh, uniquely-jti'd token is minted on every call — RS256 signing is
    cheap and the frontend already calls this once per session exchange.
    """
    return {"success": True, "data": {"token": _generate_viewer_jwt()}}


@router.post("/qlik/tv-token")
@limiter.limit("10/minute")
async def get_tv_token(
    request: Request,
    secret: str = "",
):
    """Return a viewer JWT for unattended TV displays.

    Authenticated via a shared secret instead of NextAuth session.
    Used by /dfw-podium and similar kiosk/TV pages.
    """
    if not secret or secret != settings.TV_SECRET:
        from fastapi import HTTPException
        raise HTTPException(status_code=401, detail="Invalid TV secret")

    # Fresh, single-use token per call (see get_viewer_token — Qlik rejects a
    # reused jti at /login/jwt-session).
    return {"success": True, "data": {"token": _generate_viewer_jwt()}}


# Keep legacy endpoint for backward compatibility
@router.post("/qlik/token")
@limiter.limit("10/minute")
async def get_qlik_token(
    request: Request,
    user: dict = Depends(require_user),
):
    """Legacy per-user token endpoint. Redirects to viewer token."""
    return await get_viewer_token(request, user)
