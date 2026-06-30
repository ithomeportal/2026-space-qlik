import time

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


def get_ap_pool(request: Request) -> asyncpg.Pool:
    """Pool for unilink_portal_ap — the AP_module app's own DB
    (carriers + fmcsa_sms_data). Powers the Carrier SMS Score report."""
    pool = getattr(request.app.state, "ap_pool", None)
    if pool is None:
        raise HTTPException(
            status_code=503,
            detail="Carrier (AP) data source not configured",
        )
    return pool


def require_tag_role(*allowed: str):
    """Factory: require the user to have at least one of the given tag roles (admin bypasses).

    DEPRECATED for code-made reports — use ``require_report_access(report_key)`` instead so the
    DB (`role_report_access`) is the single source of truth and admin-UI changes take effect
    without redeploying. Kept for callers that aren't tied to a specific report row.
    """

    async def _check(user: dict = Depends(require_user)) -> dict:
        roles = {r.lower() for r in user.get("roles", [])}
        allowed_lower = {a.lower() for a in allowed}
        if "admin" in roles or roles & allowed_lower:
            return user
        raise HTTPException(
            status_code=403, detail="You do not have access to this report"
        )

    return _check


# ---------------------------------------------------------------------------
# DB-backed report access — single source of truth for code-made reports.
#
# Every custom report has a stable key (e.g. ``"hr-access-doors"``) that maps
# to ``reports.custom_path = '/reports/<key>'``. Allowed TagRoles for that
# report live in ``role_report_access`` and are managed through the admin UI
# (``/admin/reports``). Routers depend on ``require_report_access(<key>)``,
# the frontend ``<ReportGuard reportKey="<key>"/>`` calls
# ``GET /api/reports/access/<key>``, and both resolve to the same DB rows so
# updates take effect within ~60s without a redeploy.
# ---------------------------------------------------------------------------

# In-process TTL cache keyed by report_key. Avoids hitting the DB on every
# protected request while still honouring admin-UI updates promptly. The cache
# is invalidated explicitly from admin mutations (see ``invalidate_report_access_cache``).
_ACCESS_CACHE: dict[str, tuple[float, frozenset[str]]] = {}
_ACCESS_CACHE_TTL = 60.0  # seconds


def invalidate_report_access_cache(report_key: str | None = None) -> None:
    """Invalidate the cache for a single report key, or globally when ``None``."""
    if report_key is None:
        _ACCESS_CACHE.clear()
    else:
        _ACCESS_CACHE.pop(report_key, None)


async def get_allowed_roles_for_report(pool, report_key: str) -> frozenset[str]:
    """Return the set of TagRole names (lower-cased) that grant access to a custom report.

    Uses ``reports.custom_path = '/reports/<key>'`` as the lookup. Returns an
    empty frozenset when the report doesn't exist or has no role assignments.
    """
    now = time.monotonic()
    cached = _ACCESS_CACHE.get(report_key)
    if cached and cached[0] > now:
        return cached[1]

    rows = await pool.fetch(
        """
        SELECT lower(ro.name) AS name
        FROM reports r
        JOIN role_report_access rra ON rra.report_id = r.id
        JOIN roles ro ON ro.id = rra.role_id
        WHERE r.custom_path = $1 AND r.is_active = TRUE
        """,
        f"/reports/{report_key}",
    )
    allowed = frozenset(r["name"] for r in rows)
    _ACCESS_CACHE[report_key] = (now + _ACCESS_CACHE_TTL, allowed)
    return allowed


def require_report_access(*report_keys: str):
    """Factory: gate a custom-report endpoint by its DB role assignments.

    Admin always bypasses. Allowed roles come from ``role_report_access`` for the
    matching ``reports.custom_path`` row, refreshed on a 60s TTL (or sooner via
    ``invalidate_report_access_cache``).

    Pass more than one report key to grant access when the user holds a role on
    ANY of them. This lets a shared endpoint back two reports — e.g. the
    Attrition-WoW summary/pivot endpoints are reused by the CEO Executive
    "Attrition" tab, so they accept either ``attrition-wow`` or
    ``ceo-executive`` access.
    """
    if not report_keys:
        raise ValueError("require_report_access needs at least one report key")

    async def _check(
        request: Request,
        user: dict = Depends(require_user),
    ) -> dict:
        roles = {r.lower() for r in user.get("roles", [])}
        if "admin" in roles:
            return user
        pool = get_pool(request)
        for key in report_keys:
            allowed = await get_allowed_roles_for_report(pool, key)
            if roles & allowed:
                return user
        raise HTTPException(
            status_code=403,
            detail="You do not have access to this report",
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
