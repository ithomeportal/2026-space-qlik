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

# In-memory token cache: single viewer token
_viewer_token: str | None = None
_viewer_token_expires: float = 0


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
    """
    global _viewer_token, _viewer_token_expires

    now = time.time()
    # Return cached token if still valid (more than 10 min left)
    if _viewer_token and _viewer_token_expires - now > 600:
        return {"success": True, "data": {"token": _viewer_token}}

    _viewer_token = _generate_viewer_jwt()
    _viewer_token_expires = now + 3600

    return {"success": True, "data": {"token": _viewer_token}}


# Keep legacy endpoint for backward compatibility
@router.post("/qlik/token")
@limiter.limit("10/minute")
async def get_qlik_token(
    request: Request,
    user: dict = Depends(require_user),
):
    """Legacy per-user token endpoint. Redirects to viewer token."""
    return await get_viewer_token(request, user)
