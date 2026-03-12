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

# In-memory token cache: user_id -> (token, expires_at)
_token_cache: dict[str, tuple[str, float]] = {}


def generate_qlik_jwt(user_sub: str, groups: list[str], attrs: dict) -> str:
    now = time.time()
    payload = {
        "sub": user_sub,
        "name": attrs.get("display_name", ""),
        "email": attrs.get("email", ""),
        "groups": groups,
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


@router.post("/qlik/token")
@limiter.limit("10/minute")
async def get_qlik_token(
    request: Request,
    user: dict = Depends(require_user),
):
    user_id = user["sub"]
    now = time.time()

    # Return cached token if still valid (50 min threshold)
    if user_id in _token_cache:
        cached_token, expires_at = _token_cache[user_id]
        if expires_at - now > 600:  # More than 10 min left
            return {"success": True, "data": {"token": cached_token}}

    token = generate_qlik_jwt(
        user_sub=user.get("email", user_id),
        groups=user.get("roles", []),
        attrs={
            "display_name": user.get("name", ""),
            "email": user.get("email", ""),
            "company": user.get("company", ""),
        },
    )

    _token_cache[user_id] = (token, time.time() + 3600)
    return {"success": True, "data": {"token": token}}
