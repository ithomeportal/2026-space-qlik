import asyncpg
from fastapi import Depends, Header, HTTPException, Request


def get_pool(request: Request) -> asyncpg.Pool:
    pool = request.app.state.pool
    if pool is None:
        raise HTTPException(status_code=503, detail="Database not available")
    return pool


def get_datalake_gold_pool(request: Request) -> asyncpg.Pool:
    """Pool for aivn_datalake_gold (carriers_savings, daily_production_budget_report, etc.)."""
    pool = getattr(request.app.state, "savings_pool", None)
    if pool is None:
        raise HTTPException(
            status_code=503,
            detail="Datalake (gold) data source not configured",
        )
    return pool


# Backward-compatible alias — carriers_savings router still imports this name.
get_savings_pool = get_datalake_gold_pool


def get_automations_pool(request: Request) -> asyncpg.Pool:
    """Pool for automations_db — tables produced by n8n workflows
    (e.g. contract_performance_analysis powering Track Award Loads)."""
    pool = getattr(request.app.state, "automations_pool", None)
    if pool is None:
        raise HTTPException(
            status_code=503,
            detail="Automations data source not configured",
        )
    return pool


def get_freshservice_pool(request: Request) -> asyncpg.Pool:
    """Pool for fresh_services_unlk — FreshService Tickets/Agents mirror
    populated by an external Spark ETL. Powers the IT Tickets Mgmt report."""
    pool = getattr(request.app.state, "freshservice_pool", None)
    if pool is None:
        raise HTTPException(
            status_code=503,
            detail="FreshService data source not configured",
        )
    return pool


def require_tag_role(*allowed: str):
    """Factory: require the user to have at least one of the given tag roles (admin bypasses)."""

    async def _check(user: dict = Depends(require_user)) -> dict:
        roles = {r.lower() for r in user.get("roles", [])}
        allowed_lower = {a.lower() for a in allowed}
        if "admin" in roles or roles & allowed_lower:
            return user
        raise HTTPException(
            status_code=403, detail="You do not have access to this report"
        )

    return _check


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


async def require_admin(user: dict = Depends(require_user)) -> dict:
    """Verify user has admin role."""
    if not user:
        raise HTTPException(status_code=401, detail="Not authenticated")
    roles = user.get("roles", [])
    if "admin" not in roles:
        raise HTTPException(status_code=403, detail="Admin access required")
    return user
