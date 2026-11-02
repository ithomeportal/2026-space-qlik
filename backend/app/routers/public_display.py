"""Public displays — read-only report views for the floor TVs (2026-11-02).

Request "space -- Public URL" (2026-11-02): show the Booker Performance
Scorecard **Rank** tab on TVs in several locations, autonomously, with no user
login. The page lives at ``/public/booker-rank`` on the frontend; the TV
provider authenticates with an access KEY, never a user session.

HOW IT IS GATED
---------------
The browser never calls this router. The Next.js page
(``frontend/app/public/booker-rank/page.tsx``) checks the display key
(``PUBLIC_DISPLAY_KEYS``, Vercel only) and then calls here server-to-server
with ``X-Proxy-Secret``. So this router answers only to our own frontend:

* ``require_proxy_strict`` — the proxy-secret check, but **FAIL-CLOSED**: while
  ``PROXY_SHARED_SECRET`` is unset every call is a 503. ``require_proxy`` /
  ``require_user`` fail OPEN by design (a deploy must never take login down);
  a page with no user identity behind it gets no such grace.
* No user identity is accepted or needed — there is no ``Authorization`` header.

WHAT IT RETURNS
---------------
An explicit ALLOWLIST of what the TV shows (``RANK_ROW_FIELDS`` /
``RANK_TOP_FIELDS``), projected out of the very same functions the report's
Rank tab calls (``booker_scorecard.rank`` / ``rank_last_week``), so the TV and
the report cannot disagree. Picker lists (``bookers`` / ``roster``) and every
other scorecard field stay private. ⚠ Adding a field here publishes it to the
internet — ``tests/test_public_display.py`` pins both key sets.

⚠ ``TV_SECRET`` (the 2026-03 Qlik ``/dfw-podium`` route) is GONE and must not be
re-added; this is a separate mechanism with its own env var.
"""

from __future__ import annotations

import asyncio
import hmac
import logging
import time
from typing import Any, Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Request

from app.config import settings
from app.routers import booker_scorecard as bs

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/public", tags=["public-display"])

# What one row of the TV table may carry. Everything else is dropped.
RANK_ROW_FIELDS: tuple[str, ...] = (
    "booker",
    "rank",
    "prev_rank",
    "rank_delta",
    "bookings",
    "prev_bookings",
    "compliance_threshold_pct",
    "compliant_threshold",
    "threshold_orders",
    "cost_saving",
)

# What the table header may carry (the week label, the "of N", the cut).
RANK_TOP_FIELDS: tuple[str, ...] = (
    "total_bookers",
    "min_bookings",
    "week",
    "prev_week",
    "like_for_like",
)


# Several TVs refresh every 5 minutes, and each payload is two full scans of
# `mcleod_gld_order_post_hist` (§73). One shared answer per CACHE_TTL_S keeps
# the scan count independent of how many screens are on the wall.
CACHE_TTL_S = 120.0
_cache: dict[str, tuple[float, dict[str, Any]]] = {}
_cache_lock = asyncio.Lock()


async def require_proxy_strict(
    x_proxy_secret: Optional[str] = Header(None),
) -> None:
    """The proxy-secret check, FAIL-CLOSED (see module docstring)."""
    expected = settings.PROXY_SHARED_SECRET
    if not expected:
        logger.warning("public display refused: PROXY_SHARED_SECRET is unset")
        raise HTTPException(status_code=503, detail="Display not configured")
    if not x_proxy_secret or not hmac.compare_digest(x_proxy_secret, expected):
        raise HTTPException(status_code=401, detail="Not authenticated")


def _project_rank(data: dict[str, Any]) -> dict[str, Any]:
    """Keep only the allowlisted keys. Returns a NEW dict; input untouched."""
    top = {k: data.get(k) for k in RANK_TOP_FIELDS}
    rows = [{k: row.get(k) for k in RANK_ROW_FIELDS} for row in data.get("rows", [])]
    return {**top, "rows": rows}


@router.get("/booker-rank")
async def booker_rank(
    request: Request,
    _proxy: None = Depends(require_proxy_strict),
) -> dict[str, Any]:
    """Both Rank-tab tables at their DEFAULTS: this booking week (Fri 5:01 PM →
    Fri 5:00 PM CST) and Rank Last Week. No parameters are declared, so no
    crafted URL can widen the window or the scope.
    """
    async with _cache_lock:
        hit = _cache.get("booker-rank")
        if hit and time.monotonic() - hit[0] < CACHE_TTL_S:
            return hit[1]
        payload = await _build_booker_rank(request)
        _cache["booker-rank"] = (time.monotonic(), payload)
        return payload


async def _build_booker_rank(request: Request) -> dict[str, Any]:
    current = await bs.rank(
        request,
        period=None,
        start=None,
        end=None,
        contract_type=None,
        customer_name=None,
        posted_by=None,
        _user={},
    )
    last_week = await bs.rank_last_week(
        request,
        contract_type=None,
        customer_name=None,
        posted_by=None,
        _user={},
    )
    return {
        "success": True,
        "data": {
            "current": _project_rank(current["data"]),
            "last_week": _project_rank(last_week["data"]),
        },
    }
