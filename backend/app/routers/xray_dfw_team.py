"""Per-team variants of XRay DFW Mng — one report per DFW sub-team.

Wraps each XRay DFW Mng endpoint with the ``sub_teams`` query param locked
server-side to a single TM so a TM1 user can only ever see TM1 data, even
if they craft a custom URL with ``?sub_teams=TM2``.

Endpoints (per TM):
    /api/custom/xray-dfw-tm1/* … /xray-dfw-tm4/*

Role gate (per report):
    require_report_access("xray-dfw-tmN")  -- DB-backed per-report list,
    admin always bypasses, role list editable via /admin/reports.

Implementation: each shim calls the corresponding ``xray_dfw`` endpoint
function directly (Python-level, bypassing FastAPI's dependency tree for
the role gate -- we apply our own per-TM gate instead). The locked
``sub_teams=TMn`` string flows through the existing query path.

The /filters endpoint is custom: it returns customers scoped to that TM
only (vs the CORP/DFW filters which return all DFW customers across TMs).
"""

from __future__ import annotations

import asyncio
from datetime import date
from typing import Optional

from fastapi import APIRouter, Depends, Query, Request

from app.routers import xray_dfw
from app.routers.deps import get_datalake_gold_pool, require_report_access


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
    ``sub_teams=tm`` locked in. The role gate is DB-backed via
    ``require_report_access("xray-dfw-tmN")`` so admins can edit the role
    list via ``/admin/reports`` without redeploying.
    """
    slug = tm.lower()
    report_key = f"xray-dfw-{slug}"
    gate = require_report_access(report_key)
    r = APIRouter(tags=[f"xray-dfw-{slug}"], prefix=f"/custom/xray-dfw-{slug}")

    @r.get("/filters")
    async def filters(
        request: Request,
        view: Optional[str] = Query(None),
        _user: dict = Depends(gate),
    ):
        """Return customers + lanes scoped to *this* TM only (server-locked).

        Under the RUAN view the entity list switches from ``customer_name`` to
        ``client`` and is filtered to RUAN rows (parity with the parent
        ``xray_dfw.filters``)."""
        pool = get_datalake_gold_pool(request)
        ruan = view == xray_dfw.RUAN_VIEW
        entity_col = "client" if ruan else "customer_name"
        ruan_filter = (
            " AND UPPER(COALESCE(customer_name,'')) LIKE 'RUAN%'" if ruan else ""
        )
        cust_task = pool.fetch(
            f"""
            SELECT DISTINCT TRIM({entity_col}) AS customer_name
            FROM public.mcleod_gld_budget_report_v4
            WHERE TRIM(team_id)    = 'TEAM-DFW'
              AND TRIM(team)       = $1
              AND TRIM(company_id) = ANY($2)
              AND TRIM(status)     = ANY($3)
              AND UPPER(COALESCE(customer_name,'')) NOT LIKE '%OILTEX%'
              AND UPPER(COALESCE(customer_name,'')) NOT LIKE '%UNILINK%'
              AND {entity_col} IS NOT NULL
              AND TRIM({entity_col}) <> ''
              AND origin_actual_departure >= $4{ruan_filter}
            ORDER BY customer_name
            """,
            tm,
            list(xray_dfw.DFW_COMPANIES),
            list(xray_dfw.OPEN_STATUSES),
            xray_dfw.YEAR_START,
        )
        lane_task = pool.fetch(
            f"""
            SELECT DISTINCT ({xray_dfw._lane_expr("br4")}) AS lane
            FROM public.mcleod_gld_budget_report_v4 br4
            WHERE TRIM(br4.team_id)    = 'TEAM-DFW'
              AND TRIM(br4.team)       = $1
              AND TRIM(br4.company_id) = ANY($2)
              AND TRIM(br4.status)     = ANY($3)
              AND UPPER(COALESCE(br4.customer_name,'')) NOT LIKE '%OILTEX%'
              AND UPPER(COALESCE(br4.customer_name,'')) NOT LIKE '%UNILINK%'
              AND br4.origin_actual_departure >= $4{ruan_filter.replace('customer_name', 'br4.customer_name')}
              AND TRIM(COALESCE(br4.origin_name,'')) <> ''
              AND TRIM(COALESCE(br4.dest_name,'')) <> ''
            ORDER BY lane
            LIMIT 3000
            """,
            tm,
            list(xray_dfw.DFW_COMPANIES),
            list(xray_dfw.OPEN_STATUSES),
            xray_dfw.YEAR_START,
        )
        cust_rows, lane_rows = await asyncio.gather(cust_task, lane_task)
        return {
            "success": True,
            "data": {
                "sub_teams": [tm],
                "customers": [row["customer_name"] for row in cust_rows],
                "lanes": [row["lane"] for row in lane_rows],
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
        customers: Optional[str] = Query(None),
        lanes: Optional[str] = Query(None),
        view: Optional[str] = Query(None),
        exclude_customers: Optional[str] = Query(None),
        _user: dict = Depends(gate),
    ):
        return await xray_dfw.kpis(
            request=request, range=range, start_date=start_date, end_date=end_date,
            sub_teams=tm, customers=customers, lanes=lanes, view=view,
            exclude_customers=exclude_customers, _user=_user,
        )

    @r.get("/trio-tables")
    async def trio_tables(
        request: Request,
        customers: Optional[str] = Query(None),
        lanes: Optional[str] = Query(None),
        view: Optional[str] = Query(None),
        _user: dict = Depends(gate),
    ):
        return await xray_dfw.trio_tables(
            request=request, sub_teams=tm, customers=customers, lanes=lanes,
            view=view, _user=_user,
        )

    @r.get("/projection")
    async def projection(
        request: Request,
        customers: Optional[str] = Query(None),
        lanes: Optional[str] = Query(None),
        view: Optional[str] = Query(None),
        _user: dict = Depends(gate),
    ):
        return await xray_dfw.projection(
            request=request, sub_teams=tm, customers=customers, lanes=lanes,
            view=view, _user=_user,
        )

    @r.get("/by-customer")
    async def by_customer(
        request: Request,
        range: Optional[str] = Query("ytd"),
        start_date: Optional[date] = Query(None),
        end_date: Optional[date] = Query(None),
        customers: Optional[str] = Query(None),
        lanes: Optional[str] = Query(None),
        view: Optional[str] = Query(None),
        limit: int = Query(200, ge=1, le=1000),
        _user: dict = Depends(gate),
    ):
        return await xray_dfw.by_customer(
            request=request, range=range, start_date=start_date, end_date=end_date,
            sub_teams=tm, customers=customers, lanes=lanes, view=view, limit=limit, _user=_user,
        )

    @r.get("/by-lane")
    async def by_lane(
        request: Request,
        range: Optional[str] = Query("ytd"),
        start_date: Optional[date] = Query(None),
        end_date: Optional[date] = Query(None),
        customers: Optional[str] = Query(None),
        lanes: Optional[str] = Query(None),
        view: Optional[str] = Query(None),
        exclude_customers: Optional[str] = Query(None),
        limit: int = Query(200, ge=1, le=1000),
        _user: dict = Depends(gate),
    ):
        return await xray_dfw.by_lane(
            request=request, range=range, start_date=start_date, end_date=end_date,
            sub_teams=tm, customers=customers, lanes=lanes, view=view,
            exclude_customers=exclude_customers, limit=limit, _user=_user,
        )

    @r.get("/attrition")
    async def attrition(
        request: Request,
        customers: Optional[str] = Query(None),
        lanes: Optional[str] = Query(None),
        view: Optional[str] = Query(None),
        limit: int = Query(200, ge=1, le=1000),
        _user: dict = Depends(gate),
    ):
        return await xray_dfw.attrition(
            request=request, sub_teams=tm, customers=customers, lanes=lanes,
            view=view, limit=limit, _user=_user,
        )

    @r.get("/teams-breakdown")
    async def teams_breakdown(
        request: Request,
        customers: Optional[str] = Query(None),
        lanes: Optional[str] = Query(None),
        view: Optional[str] = Query(None),
        _user: dict = Depends(gate),
    ):
        # The Teams tab table on the locked report still shows the same per-TM
        # rows; backend doesn't take sub_teams here -- it always returns all 4.
        # We let it through and the frontend will hide / dim non-locked rows.
        return await xray_dfw.teams_breakdown(
            request=request, customers=customers, lanes=lanes, view=view, _user=_user,
        )

    @r.get("/trends")
    async def trends(
        request: Request,
        customers: Optional[str] = Query(None),
        lanes: Optional[str] = Query(None),
        view: Optional[str] = Query(None),
        _user: dict = Depends(gate),
    ):
        return await xray_dfw.trends(
            request=request, sub_teams=tm, customers=customers, lanes=lanes,
            view=view, _user=_user,
        )

    @r.get("/summary-table")
    async def summary_table(
        request: Request,
        customers: Optional[str] = Query(None),
        lanes: Optional[str] = Query(None),
        view: Optional[str] = Query(None),
        _user: dict = Depends(gate),
    ):
        return await xray_dfw.summary_table(
            request=request, sub_teams=tm, customers=customers, lanes=lanes,
            view=view, _user=_user,
        )

    @r.get("/weekly-performance")
    async def weekly_performance(
        request: Request,
        customers: Optional[str] = Query(None),
        lanes: Optional[str] = Query(None),
        view: Optional[str] = Query(None),
        _user: dict = Depends(gate),
    ):
        return await xray_dfw.weekly_performance(
            request=request, sub_teams=tm, customers=customers, lanes=lanes,
            view=view, _user=_user,
        )

    @r.get("/risk")
    async def risk(
        request: Request,
        range: Optional[str] = Query("ytd"),
        start_date: Optional[date] = Query(None),
        end_date: Optional[date] = Query(None),
        customers: Optional[str] = Query(None),
        lanes: Optional[str] = Query(None),
        view: Optional[str] = Query(None),
        limit: int = Query(200, ge=1, le=1000),
        _user: dict = Depends(gate),
    ):
        return await xray_dfw.risk(
            request=request, range=range, start_date=start_date, end_date=end_date,
            sub_teams=tm, customers=customers, lanes=lanes, view=view, limit=limit, _user=_user,
        )

    @r.get("/contract-spot")
    async def contract_spot(
        request: Request,
        customers: Optional[str] = Query(None),
        lanes: Optional[str] = Query(None),
        view: Optional[str] = Query(None),
        _user: dict = Depends(gate),
    ):
        return await xray_dfw.contract_spot(
            request=request, sub_teams=tm, customers=customers, lanes=lanes,
            view=view, _user=_user,
        )

    @r.get("/all-orders")
    async def all_orders(
        request: Request,
        range: Optional[str] = Query("ytd"),
        start_date: Optional[date] = Query(None),
        end_date: Optional[date] = Query(None),
        customers: Optional[str] = Query(None),
        lanes: Optional[str] = Query(None),
        view: Optional[str] = Query(None),
        limit: int = Query(500, ge=1, le=2000),
        # Bruno 2026-06-03 pagination — declared AND forwarded explicitly per
        # SPEC-CODE-RULES §40 (a direct Python call never applies Query()
        # defaults; an omitted param would arrive as FieldInfo and 500).
        page: int = Query(1, ge=1),
        _user: dict = Depends(gate),
    ):
        return await xray_dfw.all_orders(
            request=request, range=range, start_date=start_date, end_date=end_date,
            sub_teams=tm, customers=customers, lanes=lanes, view=view, limit=limit,
            page=page, _user=_user,
        )

    @r.get("/lane-analysis")
    async def lane_analysis(
        request: Request,
        range: Optional[str] = Query("ytd"),
        start_date: Optional[date] = Query(None),
        end_date: Optional[date] = Query(None),
        customers: Optional[str] = Query(None),
        lanes: Optional[str] = Query(None),
        view: Optional[str] = Query(None),
        limit: int = Query(300, ge=1, le=1000),
        _user: dict = Depends(gate),
    ):
        return await xray_dfw.lane_analysis(
            request=request, range=range, start_date=start_date, end_date=end_date,
            sub_teams=tm, customers=customers, lanes=lanes, view=view, limit=limit, _user=_user,
        )

    return r


# Build all 4 routers at import time -- include them in main.py.
team_routers: tuple[APIRouter, ...] = tuple(
    _make_team_router(tm, role) for tm, role in TEAM_CONFIGS
)
