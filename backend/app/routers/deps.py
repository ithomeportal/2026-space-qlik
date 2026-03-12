import asyncpg
from fastapi import Header, HTTPException, Request


def get_pool(request: Request) -> asyncpg.Pool:
    return request.app.state.pool


async def require_user(authorization: str = Header(...)) -> dict:
    """Extract user info from the Authorization header.

    The Next.js proxy forwards the session JWT. In production this would
    verify the NextAuth JWT signature. For MVP we trust the proxy and
    decode the payload claims.
    """
    if not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing bearer token")

    token = authorization[7:]

    # For MVP, we decode without verification since the Next.js proxy
    # already validated the session. In production, verify with NEXTAUTH_SECRET.
    import jwt as pyjwt

    try:
        payload = pyjwt.decode(token, options={"verify_signature": False})
    except pyjwt.DecodeError:
        raise HTTPException(status_code=401, detail="Invalid token")

    if not payload.get("sub"):
        raise HTTPException(status_code=401, detail="Missing subject")

    return payload


async def require_admin(user: dict = None) -> dict:
    """Verify user has admin role."""
    if not user:
        raise HTTPException(status_code=401, detail="Not authenticated")
    roles = user.get("roles", [])
    if "admin" not in roles:
        raise HTTPException(status_code=403, detail="Admin access required")
    return user
