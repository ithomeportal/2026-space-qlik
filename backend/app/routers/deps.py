import asyncpg
from fastapi import Header, HTTPException, Request


def get_pool(request: Request) -> asyncpg.Pool:
    pool = request.app.state.pool
    if pool is None:
        raise HTTPException(status_code=503, detail="Database not available")
    return pool


async def require_user(authorization: str = Header(...)) -> dict:
    """Extract user info from the Authorization header.

    The Next.js proxy forwards the session as a JSON-serialised object.
    We trust the proxy (it already validated the session) and parse the
    payload directly.
    """
    if not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing bearer token")

    token = authorization[7:]

    import json

    try:
        payload = json.loads(token)
    except (json.JSONDecodeError, ValueError):
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
