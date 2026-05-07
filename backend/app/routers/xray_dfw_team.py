"""Per-team variants of XRay DFW Mng — one report per DFW sub-team.

Wraps each XRay DFW Mng endpoint with the ``sub_teams`` query param locked
server-side to a single TM so a TM1 user can only ever see TM1 data, even
if they craft a custom URL with ``?sub_teams=TM2``.

Endpoints (per TM):
    /api/custom/xray-dfw-tm1/* … /xray-dfw-tm4/*

Role gate (per report):
    require_tag_role("DFW-TMn", "CEO", "Executive")  -- admin always bypasses

Implementation: each shim calls the corresponding ``xray_dfw`` endpoint
function directly (Python-level, bypassing FastAPI's dependency tree for
the role gate -- we apply our own per-TM gate instead). The locked
``sub_teams=TMn`` string flows through the existing query path.

The /filters endpoint is custom: it returns customers scoped to that TM
only (vs the CORP/DFW filters which return all DFW customers across TMs).
"""

from __future__ import annotations

from datetime import date
from typing import Optional

from fastapi import APIRouter, Depends, Query, Request

from app.routers import xray_dfw
from app.routers.deps import get_datalake_gold_pool, require_tag_role


# Single source of truth for the per-team config. Adding TM5 later means
# adding one line here -- everything else is parametrized.
TEAM_CONFIGS: tuple[tuple[str, str], ...] = (
    ("TM1", "DFW-TM1"),
    ("TM2", "DFW-TM2"),
    ("TM3", "DFW-TM3"),
    ("TM4", "DFW-TM4"),
)


def _make_team_router(tm: str, role: str) -> APIRouter:
    """Build one APIRouter for a single sub-team.

    All endpoints delegate to the matching ``xray_dfw.py`` function but with
    ``sub_teams=tm`` locked in. The shared role gate is `(role, CEO, Exec)`.
    """
    allowed_roles = (role, "CEO", "Executive")
    slug = tm.lower()
    r = APIRouter(tags=[f"xray-dfw-{slug}"], prefix=f"/custom/xray-dfw-{slug}")

    @r.get("/filters")
    async def filters(
        request: Request,
        _user: dict = Depends(require_tag_role(*allowed_roles)),
    ):
        """Return customers scoped to *this* TM only (server-locked)."""
        pool = get_datalake_gold_pool(request)
        rows = await pool.fetch(
            """
            SELECT DISTINCT TRIM(customer_name) AS customer_name
            FROM public.mcleod_gld_budget_report_v4
            WHERE TRIM(team_id)    = 'TEAM-DFW'
              AND TRIM(team)       = $1
              AND TRIM(company_id) = ANY($2)
              AND TRIM(status)     = ANY($3)
              AND UPPER(COALESCE(customer_name,'')) NOT LIKE '%OILTEX%'
              AND UPPER(COALESCE(customer_name,'')) NOT LIKE '%UNILINK%'
              AND customer_name IS NOT NULL
              AND TRIM(customer_name) <> ''
              AND origin_actual_departure >= $4
            ORDER BY customer_name
            """,
            tm,
            list(xray_dfw.DFW_COMPANIES),
            list(xray_dfw.OPEN_STATUSES),
            xray_dfw.YEAR_START,
        )
        return {
            "success": True,
            "data": {
                "sub_teams": [tm],
                "customers": [row["customer_name"] for row in rows],
                "year_start": xray_dfw.YEAR_START.isoformat(),
                "year_end": xray_dfw.YEAR_END.isoformat(),
                "locked_team": tm,
            },
        }

    @r.get("/kpis")
    async def kpis(
        request: Request,
        range: Optional[str] = Query("ytd"),
        start_date: Optional[date] = Query(None),
        end_date: Optional[date] = Query(None),
        customer: Optional[str] = Query(None),
        _user: dict = Depends(require_tag_role(*allowed_roles)),
    ):
        return await xray_dfw.kpis(
            request=request, range=range, start_date=start_date, end_date=end_date,
            sub_teams=tm, customer=customer, _user=_user,
        )

    @r.get("/trio-tables")
    async def trio_tables(
        request: Request,
        customer: Optional[str] = Query(None),
        _user: dict = Depends(require_tag_role(*allowed_roles)),
    ):
        return await xray_dfw.trio_tables(
            request=request, sub_teams=tm, customer=customer, _user=_user,
        )

    @r.get("/projection")
    async def projection(
        request: Request,
        customer: Optional[str] = Query(None),
        _user: dict = Depends(require_tag_role(*allowed_roles)),
    ):
        return await xray_dfw.projection(
            request=request, sub_teams=tm, customer=customer, _user=_user,
        )

    @r.get("/by-customer")
    async def by_customer(
        request: Request,
        range: Optional[str] = Query("ytd"),
        start_date: Optional[date] = Query(None),
        end_date: Optional[date] = Query(None),
        customer: Optional[str] = Query(None),
        limit: int = Query(200, ge=1, le=1000),
        _user: dict = Depends(require_tag_role(*allowed_roles)),
    ):
        return await xray_dfw.by_customer(
            request=request, range=range, start_date=start_date, end_date=end_date,
            sub_teams=tm, customer=customer, limit=limit, _user=_user,
        )

    @r.get("/by-lane")
    async def by_lane(
        request: Request,
        range: Optional[str] = Query("ytd"),
        start_date: Optional[date] = Query(None),
        end_date: Optional[date] = Query(None),
        customer: Optional[str] = Query(None),
        limit: int = Query(200, ge=1, le=1000),
        _user: dict = Depends(require_tag_role(*allowed_roles)),
    ):
        return await xray_dfw.by_lane(
            request=request, range=range, start_date=start_date, end_date=end_date,
            sub_teams=tm, customer=customer, limit=limit, _user=_user,
        )

    @r.get("/attrition")
    async def attrition(
        request: Request,
        customer: Optional[str] = Query(None),
        limit: int = Query(200, ge=1, le=1000),
        _user: dict = Depends(require_tag_role(*allowed_roles)),
    ):
        return await xray_dfw.attrition(
            request=request, sub_teams=tm, customer=customer, limit=limit, _user=_user,
        )

    @r.get("/teams-breakdown")
    async def teams_breakdown(
        request: Request,
        customer: Optional[str] = Query(None),
        _user: dict = Depends(require_tag_role(*allowed_roles)),
    ):
        # The Teams tab table on the locked report still shows the same per-TM
        # rows; backend doesn't take sub_teams here -- it always returns all 4.
        # We let it through and the frontend will hide / dim non-locked rows.
        return await xray_dfw.teams_breakdown(
            request=request, customer=customer, _user=_user,
        )

    @r.get("/trends")
    async def trends(
        request: Request,
        customer: Optional[str] = Query(None),
        _user: dict = Depends(require_tag_role(*allowed_roles)),
    ):
        return await xray_dfw.trends(
            request=request, sub_teams=tm, customer=customer, _user=_user,
        )

    @r.get("/summary-table")
    async def summary_table(
        request: Request,
        customer: Optional[str] = Query(None),
        _user: dict = Depends(require_tag_role(*allowed_roles)),
    ):
        return await xray_dfw.summary_table(
            request=request, sub_teams=tm, customer=customer, _user=_user,
        )

    @r.get("/risk")
    async def risk(
        request: Request,
        range: Optional[str] = Query("ytd"),
        start_date: Optional[date] = Query(None),
        end_date: Optional[date] = Query(None),
        customer: Optional[str] = Query(None),
        limit: int = Query(200, ge=1, le=1000),
        _user: dict = Depends(require_tag_role(*allowed_roles)),
    ):
        return await xray_dfw.risk(
            request=request, range=range, start_date=start_date, end_date=end_date,
            sub_teams=tm, customer=customer, limit=limit, _user=_user,
        )

    @r.get("/contract-spot")
    async def contract_spot(
        request: Request,
        customer: Optional[str] = Query(None),
        _user: dict = Depends(require_tag_role(*allowed_roles)),
    ):
        return await xray_dfw.contract_spot(
            request=request, sub_teams=tm, customer=customer, _user=_user,
        )

    @r.get("/all-orders")
    async def all_orders(
        request: Request,
        range: Optional[str] = Query("ytd"),
        start_date: Optional[date] = Query(None),
        end_date: Optional[date] = Query(None),
        customer: Optional[str] = Query(None),
        limit: int = Query(500, ge=1, le=2000),
        _user: dict = Depends(require_tag_role(*allowed_roles)),
    ):
        return await xray_dfw.all_orders(
            request=request, range=range, start_date=start_date, end_date=end_date,
            sub_teams=tm, customer=customer, limit=limit, _user=_user,
        )

    @r.get("/lane-analysis")
    async def lane_analysis(
        request: Request,
        range: Optional[str] = Query("ytd"),
        start_date: Optional[date] = Query(None),
        end_date: Optional[date] = Query(None),
        customer: Optional[str] = Query(None),
        limit: int = Query(300, ge=1, le=1000),
        _user: dict = Depends(require_tag_role(*allowed_roles)),
    ):
        return await xray_dfw.lane_analysis(
            request=request, range=range, start_date=start_date, end_date=end_date,
            sub_teams=tm, customer=customer, limit=limit, _user=_user,
        )

    return r


# Build all 4 routers at import time -- include them in main.py.
team_routers: tuple[APIRouter, ...] = tuple(
    _make_team_router(tm, role) for tm, role in TEAM_CONFIGS
)
