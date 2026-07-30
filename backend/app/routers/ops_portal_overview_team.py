"""Per-team variants of Ops Portal Overview — one report per CORP team.

Bruno 2026-06-26 (PDF "Ops Portal Updates" Request 1): duplicate the entire
``ops-portal-overview`` report for each CORP team so a TEAM1 KAM can only ever
see TEAM1 data — orders, customers, lanes, budget, everything — even if they
craft a custom URL with ``?team=TEAM2``.

Endpoints (per team):
    /api/custom/ops-portal-overview-t1/* … /ops-portal-overview-t4/*

Role gate (per report):
    require_report_access("corp-tN-ops-kam-portal")  -- DB-backed per-report
    list, admin always bypasses, role list editable via /admin/reports.

Implementation mirrors ``xray_dfw_team.py``: each shim calls the corresponding
``ops_portal_overview`` endpoint function directly (Python-level) with
``team=TEAMn`` locked server-side. Every param is forwarded explicitly — a
direct Python call never applies FastAPI ``Query()`` defaults, so an omitted
param would arrive as a FieldInfo and 500 (SPEC-CODE-RULES §40).

The /filters endpoint is custom: it returns customers + lanes scoped to that
team only (vs the CORP /filters which returns all teams' customers).
"""

from __future__ import annotations

import asyncio
from datetime import date
from typing import List, Optional

from fastapi import APIRouter, Depends, Query, Request

from app.routers import ops_portal_overview as opo
from app.routers.deps import get_datalake_gold_pool, require_report_access


# Single source of truth for the per-team config: (team_id, url-slug, TagRole).
# Adding TEAM5 later means adding one line here — everything else is
# parametrized. Bruno's PDF only asked for TEAM1–TEAM4.
TEAM_CONFIGS: tuple[tuple[str, str, str], ...] = (
    ("TEAM1", "t1", "CORP-T1"),
    ("TEAM2", "t2", "CORP-T2"),
    ("TEAM3", "t3", "CORP-T3"),
    ("TEAM4", "t4", "CORP-T4"),
)


def _make_team_router(team: str, slug: str, role: str) -> APIRouter:
    """Build one APIRouter for a single CORP team.

    All endpoints delegate to the matching ``ops_portal_overview`` function with
    ``team=team`` locked in. The role gate is DB-backed via
    ``require_report_access("corp-tN-ops-kam-portal")`` so admins can edit the
    role list via ``/admin/reports`` without redeploying.
    """
    report_key = f"corp-{slug}-ops-kam-portal"
    gate = require_report_access(report_key)
    r = APIRouter(
        tags=[f"ops-portal-overview-{slug}"],
        prefix=f"/custom/ops-portal-overview-{slug}",
    )

    # ---- /filters — customers + lanes scoped to THIS team only -------------
    @r.get("/filters")
    async def filters(request: Request, _user: dict = Depends(gate)):
        """Return teams=[team], customers + lanes scoped to *this* team only
        (server-locked). Mirrors ``opo.filters`` with a single-team predicate."""
        pool = get_datalake_gold_pool(request)
        scope_args = [
            team,
            list(opo.CORP_COMPANIES),
            list(opo.OPEN_STATUSES),
            opo.YEAR_START,
        ]
        cust_sql = """
            SELECT DISTINCT TRIM(customer_name) AS customer_name
            FROM public.mcleod_gld_budget_report_v4
            WHERE TRIM(team_id)    = $1
              AND TRIM(company_id) = ANY($2)
              AND TRIM(status)     = ANY($3)
              AND UPPER(COALESCE(customer_name,'')) NOT LIKE '%OILTEX%'
              AND customer_name IS NOT NULL
              AND TRIM(customer_name) <> ''
              AND origin_actual_departure >= $4
            ORDER BY customer_name
        """
        lane_sql = f"""
            SELECT DISTINCT {opo._lane_expr("br4")} AS lane
            FROM public.mcleod_gld_budget_report_v4 br4
            WHERE TRIM(br4.team_id)    = $1
              AND TRIM(br4.company_id) = ANY($2)
              AND TRIM(br4.status)     = ANY($3)
              AND UPPER(COALESCE(br4.customer_name,'')) NOT LIKE '%OILTEX%'
              AND TRIM(COALESCE(br4.origin_name,'')) <> ''
              AND TRIM(COALESCE(br4.dest_name,''))   <> ''
              AND br4.origin_actual_departure >= $4
            ORDER BY lane
        """
        # Bruno (PDF 2026-07-15) R1: carriers scoped to this team.
        carrier_sql = """
            SELECT DISTINCT TRIM(m.payee_name) AS carrier
            FROM public.mcleod_gld_movement m
            JOIN public.mcleod_gld_budget_report_v4 br4
              ON m.order_id = br4.id AND m.company_id = br4.company_id
            WHERE TRIM(br4.team_id)    = $1
              AND TRIM(br4.company_id) = ANY($2)
              AND TRIM(br4.status)     = ANY($3)
              AND UPPER(COALESCE(br4.customer_name,'')) NOT LIKE '%OILTEX%'
              AND br4.origin_actual_departure >= $4
              AND m.payee_name IS NOT NULL AND TRIM(m.payee_name) <> ''
            ORDER BY carrier
        """
        cust_rows, lane_rows, carrier_rows = await asyncio.gather(
            pool.fetch(cust_sql, *scope_args),
            pool.fetch(lane_sql, *scope_args),
            pool.fetch(carrier_sql, *scope_args),
        )
        return {
            "success": True,
            "data": {
                "teams": [team],
                "customers": [r0["customer_name"] for r0 in cust_rows],
                "lanes": [r0["lane"] for r0 in lane_rows],
                "carriers": [r0["carrier"] for r0 in carrier_rows],
                "year_start": opo.YEAR_START.isoformat(),
                "year_end": opo.YEAR_END.isoformat(),
                "locked_team": team,
            },
        }

    # ---- /workdays — no team dimension; pass straight through --------------
    @r.get("/workdays")
    async def workdays(request: Request, _user: dict = Depends(gate)):
        return await opo.workdays(request=request, _user=_user)

    # ---- /combo -----------------------------------------------------------
    @r.get("/combo")
    async def combo(
        request: Request,
        customer: Optional[str] = Query(None),
        load_type: Optional[str] = Query(None),
        lanes: Optional[List[str]] = Query(None),
        exclude_lanes: Optional[List[str]] = Query(None),
        carriers: Optional[List[str]] = Query(None),
        exclude_carriers: Optional[List[str]] = Query(None),
        grain: str = Query("month"),
        _user: dict = Depends(gate),
    ):
        return await opo.combo(
            request=request, team=team, customer=customer, load_type=load_type,
            lanes=lanes, exclude_lanes=exclude_lanes, carriers=carriers, exclude_carriers=exclude_carriers, grain=grain, _user=_user,
        )

    # ---- /team-variance ---------------------------------------------------
    @r.get("/team-variance")
    async def team_variance(
        request: Request,
        range: Optional[str] = Query("mtd"),
        start_date: Optional[date] = Query(None),
        end_date: Optional[date] = Query(None),
        customer: Optional[str] = Query(None),
        _user: dict = Depends(gate),
    ):
        return await opo.team_variance(
            request=request, range=range, start_date=start_date, end_date=end_date,
            team=team, customer=customer, _user=_user,
        )

    # ---- /customer-variance -----------------------------------------------
    @r.get("/customer-variance")
    async def customer_variance(
        request: Request,
        range: Optional[str] = Query("mtd"),
        start_date: Optional[date] = Query(None),
        end_date: Optional[date] = Query(None),
        customer: Optional[str] = Query(None),
        limit: int = Query(50, ge=1, le=200),
        _user: dict = Depends(gate),
    ):
        return await opo.customer_variance(
            request=request, range=range, start_date=start_date, end_date=end_date,
            team=team, customer=customer, limit=limit, _user=_user,
        )

    # ---- /customer-losses -------------------------------------------------
    @r.get("/customer-losses")
    async def customer_losses(
        request: Request,
        range: Optional[str] = Query("mtd"),
        start_date: Optional[date] = Query(None),
        end_date: Optional[date] = Query(None),
        customer: Optional[str] = Query(None),
        load_type: Optional[str] = Query(None),
        lanes: Optional[List[str]] = Query(None),
        exclude_lanes: Optional[List[str]] = Query(None),
        carriers: Optional[List[str]] = Query(None),
        exclude_carriers: Optional[List[str]] = Query(None),
        limit: int = Query(50, ge=1, le=200),
        _user: dict = Depends(gate),
    ):
        return await opo.customer_losses(
            request=request, range=range, start_date=start_date, end_date=end_date,
            team=team, customer=customer, load_type=load_type, lanes=lanes,
            exclude_lanes=exclude_lanes, carriers=carriers, exclude_carriers=exclude_carriers, limit=limit, _user=_user,
        )

    # ---- /team-performance ------------------------------------------------
    @r.get("/team-performance")
    async def team_performance(
        request: Request,
        range: Optional[str] = Query("mtd"),
        start_date: Optional[date] = Query(None),
        end_date: Optional[date] = Query(None),
        customer: Optional[str] = Query(None),
        load_type: Optional[str] = Query(None),
        lanes: Optional[List[str]] = Query(None),
        exclude_lanes: Optional[List[str]] = Query(None),
        carriers: Optional[List[str]] = Query(None),
        exclude_carriers: Optional[List[str]] = Query(None),
        _user: dict = Depends(gate),
    ):
        return await opo.team_performance(
            request=request, range=range, start_date=start_date, end_date=end_date,
            team=team, customer=customer, load_type=load_type, lanes=lanes,
            exclude_lanes=exclude_lanes, carriers=carriers, exclude_carriers=exclude_carriers, _user=_user,
        )

    # ---- /team-projection -------------------------------------------------
    @r.get("/team-projection")
    async def team_projection(
        request: Request,
        customer: Optional[str] = Query(None),
        load_type: Optional[str] = Query(None),
        lanes: Optional[List[str]] = Query(None),
        exclude_lanes: Optional[List[str]] = Query(None),
        carriers: Optional[List[str]] = Query(None),
        exclude_carriers: Optional[List[str]] = Query(None),
        _user: dict = Depends(gate),
    ):
        return await opo.team_projection(
            request=request, team=team, customer=customer, load_type=load_type,
            lanes=lanes, exclude_lanes=exclude_lanes, carriers=carriers, exclude_carriers=exclude_carriers, _user=_user,
        )

    # ---- /profit-tm-gauge -------------------------------------------------
    @r.get("/profit-tm-gauge")
    async def profit_tm_gauge(
        request: Request,
        customer: Optional[str] = Query(None),
        load_type: Optional[str] = Query(None),
        lanes: Optional[List[str]] = Query(None),
        exclude_lanes: Optional[List[str]] = Query(None),
        carriers: Optional[List[str]] = Query(None),
        exclude_carriers: Optional[List[str]] = Query(None),
        _user: dict = Depends(gate),
    ):
        return await opo.profit_tm_gauge(
            request=request, team=team, customer=customer, load_type=load_type,
            lanes=lanes, exclude_lanes=exclude_lanes, carriers=carriers, exclude_carriers=exclude_carriers, _user=_user,
        )

    # ---- /actuals ---------------------------------------------------------
    @r.get("/actuals")
    async def actuals(
        request: Request,
        range: Optional[str] = Query("mtd"),
        start_date: Optional[date] = Query(None),
        end_date: Optional[date] = Query(None),
        customer: Optional[str] = Query(None),
        load_type: Optional[str] = Query(None),
        lanes: Optional[List[str]] = Query(None),
        exclude_lanes: Optional[List[str]] = Query(None),
        carriers: Optional[List[str]] = Query(None),
        exclude_carriers: Optional[List[str]] = Query(None),
        sort: str = Query("revenue_desc"),
        limit: int = Query(100, ge=1, le=500),
        losses_only: bool = Query(False),
        unbilled_only: bool = Query(False),
        _user: dict = Depends(gate),
    ):
        return await opo.actuals(
            request=request, range=range, start_date=start_date, end_date=end_date,
            team=team, customer=customer, load_type=load_type, lanes=lanes,
            exclude_lanes=exclude_lanes, carriers=carriers, exclude_carriers=exclude_carriers, sort=sort, limit=limit,
            losses_only=losses_only, unbilled_only=unbilled_only, _user=_user,
        )

    # ---- /actuals-by-lane -------------------------------------------------
    @r.get("/actuals-by-lane")
    async def actuals_by_lane(
        request: Request,
        range: Optional[str] = Query("mtd"),
        start_date: Optional[date] = Query(None),
        end_date: Optional[date] = Query(None),
        customer: Optional[str] = Query(None),
        load_type: Optional[str] = Query(None),
        lanes: Optional[List[str]] = Query(None),
        exclude_lanes: Optional[List[str]] = Query(None),
        carriers: Optional[List[str]] = Query(None),
        exclude_carriers: Optional[List[str]] = Query(None),
        sort: str = Query("revenue_desc"),
        limit: int = Query(100, ge=1, le=500),
        losses_only: bool = Query(False),
        unbilled_only: bool = Query(False),
        _user: dict = Depends(gate),
    ):
        return await opo.actuals_by_lane(
            request=request, range=range, start_date=start_date, end_date=end_date,
            team=team, customer=customer, load_type=load_type, lanes=lanes,
            exclude_lanes=exclude_lanes, carriers=carriers, exclude_carriers=exclude_carriers, sort=sort, limit=limit,
            losses_only=losses_only, unbilled_only=unbilled_only, _user=_user,
        )

    # ---- /service ---------------------------------------------------------
    @r.get("/service")
    async def service(
        request: Request,
        customer: Optional[str] = Query(None),
        load_type: Optional[str] = Query(None),
        lanes: Optional[List[str]] = Query(None),
        exclude_lanes: Optional[List[str]] = Query(None),
        carriers: Optional[List[str]] = Query(None),
        exclude_carriers: Optional[List[str]] = Query(None),
        grain: str = Query("month"),
        _user: dict = Depends(gate),
    ):
        return await opo.service(
            request=request, team=team, customer=customer, load_type=load_type,
            lanes=lanes, exclude_lanes=exclude_lanes, carriers=carriers, exclude_carriers=exclude_carriers, grain=grain, _user=_user,
        )

    # ---- /by-order --------------------------------------------------------
    @r.get("/by-order")
    async def by_order(
        request: Request,
        range: Optional[str] = Query("mtd"),
        start_date: Optional[date] = Query(None),
        end_date: Optional[date] = Query(None),
        customer: Optional[str] = Query(None),
        load_type: Optional[str] = Query(None),
        lanes: Optional[List[str]] = Query(None),
        exclude_lanes: Optional[List[str]] = Query(None),
        carriers: Optional[List[str]] = Query(None),
        exclude_carriers: Optional[List[str]] = Query(None),
        sort: str = Query("revenue_desc"),
        limit: int = Query(500, ge=1, le=2000),
        losses_only: bool = Query(False),
        unbilled_only: bool = Query(False),
        _user: dict = Depends(gate),
    ):
        return await opo.by_order(
            request=request, range=range, start_date=start_date, end_date=end_date,
            team=team, customer=customer, load_type=load_type, lanes=lanes,
            exclude_lanes=exclude_lanes, carriers=carriers, exclude_carriers=exclude_carriers, sort=sort, limit=limit,
            losses_only=losses_only, unbilled_only=unbilled_only, _user=_user,
        )

    # ---- /pending-to-cover (Bruno PDF 2026-07-15 R16) --------------------
    @r.get("/pending-to-cover")
    async def pending_to_cover(
        request: Request,
        customer: Optional[str] = Query(None),
        lanes: Optional[List[str]] = Query(None),
        exclude_lanes: Optional[List[str]] = Query(None),
        limit: int = Query(500, ge=1, le=2000),
        _user: dict = Depends(gate),
    ):
        return await opo.pending_to_cover(
            request=request, team=team, customer=customer, lanes=lanes,
            exclude_lanes=exclude_lanes, limit=limit, _user=_user,
        )

    # ---- /cover (Bruno PDF 2026-07-20 R1) --------------------------------
    @r.get("/cover")
    async def cover(
        request: Request,
        customer: Optional[str] = Query(None),
        lanes: Optional[List[str]] = Query(None),
        exclude_lanes: Optional[List[str]] = Query(None),
        limit: int = Query(500, ge=1, le=2000),
        _user: dict = Depends(gate),
    ):
        return await opo.cover(
            request=request, team=team, customer=customer, lanes=lanes,
            exclude_lanes=exclude_lanes, limit=limit, _user=_user,
        )

    # ---- /cover-forecast (Bruno PDF 2026-07-30 R4) -----------------------
    @r.get("/cover-forecast")
    async def cover_forecast(
        request: Request,
        customer: Optional[str] = Query(None),
        load_type: Optional[str] = Query(None),
        lanes: Optional[List[str]] = Query(None),
        exclude_lanes: Optional[List[str]] = Query(None),
        carriers: Optional[List[str]] = Query(None),
        exclude_carriers: Optional[List[str]] = Query(None),
        grain: str = Query("month"),
        _user: dict = Depends(gate),
    ):
        return await opo.cover_forecast(
            request=request, team=team, customer=customer, load_type=load_type,
            lanes=lanes, exclude_lanes=exclude_lanes, carriers=carriers,
            exclude_carriers=exclude_carriers, grain=grain, _user=_user,
        )

    # ---- /data-freshness --------------------------------------------------
    # Source-level, not team-scoped: staleness is a property of the ETL feed,
    # so every portal reports the same answer (and shares the 60s cache).
    @r.get("/data-freshness")
    async def data_freshness(request: Request, _user: dict = Depends(gate)):
        return await opo.data_freshness(request=request, _user=_user)

    # ---- /team-weekly-performance -----------------------------------------
    @r.get("/team-weekly-performance")
    async def team_weekly_performance(
        request: Request,
        customer: Optional[str] = Query(None),
        load_type: Optional[str] = Query(None),
        lanes: Optional[List[str]] = Query(None),
        exclude_lanes: Optional[List[str]] = Query(None),
        carriers: Optional[List[str]] = Query(None),
        exclude_carriers: Optional[List[str]] = Query(None),
        _user: dict = Depends(gate),
    ):
        return await opo.team_weekly_performance(
            request=request, team=team, customer=customer, load_type=load_type,
            lanes=lanes, exclude_lanes=exclude_lanes, carriers=carriers, exclude_carriers=exclude_carriers, _user=_user,
        )

    # ---- /team-performance-by-team ----------------------------------------
    @r.get("/team-performance-by-team")
    async def team_performance_by_team(
        request: Request,
        range: Optional[str] = Query("mtd"),
        start_date: Optional[date] = Query(None),
        end_date: Optional[date] = Query(None),
        customer: Optional[str] = Query(None),
        load_type: Optional[str] = Query(None),
        lanes: Optional[List[str]] = Query(None),
        exclude_lanes: Optional[List[str]] = Query(None),
        carriers: Optional[List[str]] = Query(None),
        exclude_carriers: Optional[List[str]] = Query(None),
        _user: dict = Depends(gate),
    ):
        # Locked to this team — the "by team" breakdown collapses to a single
        # team row + Total (both this team), which is the desired isolation.
        return await opo.team_performance_by_team(
            request=request, range=range, start_date=start_date, end_date=end_date,
            team=team, customer=customer, load_type=load_type, lanes=lanes,
            exclude_lanes=exclude_lanes, carriers=carriers, exclude_carriers=exclude_carriers, _user=_user,
        )

    # ---- /service-incident-by-customer ------------------------------------
    @r.get("/service-incident-by-customer")
    async def service_incident_by_customer(
        request: Request,
        range: Optional[str] = Query("mtd"),
        start_date: Optional[date] = Query(None),
        end_date: Optional[date] = Query(None),
        customer: Optional[str] = Query(None),
        load_type: Optional[str] = Query(None),
        lanes: Optional[List[str]] = Query(None),
        exclude_lanes: Optional[List[str]] = Query(None),
        carriers: Optional[List[str]] = Query(None),
        exclude_carriers: Optional[List[str]] = Query(None),
        stop_type: str = Query("pu"),
        _user: dict = Depends(gate),
    ):
        return await opo.service_incident_by_customer(
            request=request, range=range, start_date=start_date, end_date=end_date,
            team=team, customer=customer, load_type=load_type, lanes=lanes,
            exclude_lanes=exclude_lanes, carriers=carriers, exclude_carriers=exclude_carriers, stop_type=stop_type, _user=_user,
        )

    # ---- /service-by-carrier (Bruno PDF 2026-07-15 R8) --------------------
    @r.get("/service-by-carrier")
    async def service_by_carrier(
        request: Request,
        range: Optional[str] = Query("mtd"),
        start_date: Optional[date] = Query(None),
        end_date: Optional[date] = Query(None),
        customer: Optional[str] = Query(None),
        load_type: Optional[str] = Query(None),
        lanes: Optional[List[str]] = Query(None),
        exclude_lanes: Optional[List[str]] = Query(None),
        carriers: Optional[List[str]] = Query(None),
        exclude_carriers: Optional[List[str]] = Query(None),
        limit: int = Query(100, ge=1, le=500),
        _user: dict = Depends(gate),
    ):
        return await opo.service_by_carrier(
            request=request, range=range, start_date=start_date, end_date=end_date,
            team=team, customer=customer, load_type=load_type, lanes=lanes,
            exclude_lanes=exclude_lanes, carriers=carriers,
            exclude_carriers=exclude_carriers, limit=limit, _user=_user,
        )

    # ---- /margin-distribution ---------------------------------------------
    @r.get("/margin-distribution")
    async def margin_distribution(
        request: Request,
        range: Optional[str] = Query("mtd"),
        start_date: Optional[date] = Query(None),
        end_date: Optional[date] = Query(None),
        customer: Optional[str] = Query(None),
        load_type: Optional[str] = Query(None),
        lanes: Optional[List[str]] = Query(None),
        exclude_lanes: Optional[List[str]] = Query(None),
        carriers: Optional[List[str]] = Query(None),
        exclude_carriers: Optional[List[str]] = Query(None),
        _user: dict = Depends(gate),
    ):
        return await opo.margin_distribution(
            request=request, range=range, start_date=start_date, end_date=end_date,
            team=team, customer=customer, load_type=load_type, lanes=lanes,
            exclude_lanes=exclude_lanes, carriers=carriers, exclude_carriers=exclude_carriers, _user=_user,
        )

    # ---- Bruno (PDF 2026-07-13): "Week" toggle on Variance + Projection.
    # Only the WEEKLY variants are mirrored (locked to this team). The "Team"
    # (cross-team) breakdown is meaningless / a data-isolation leak on a
    # single-team portal, so its endpoints are intentionally NOT exposed here —
    # the frontend hides the Team button when locked, and a crafted URL 404s.
    @r.get("/team-variance-weekly")
    async def team_variance_weekly(
        request: Request,
        customer: Optional[str] = Query(None),
        _user: dict = Depends(gate),
    ):
        return await opo.team_variance_weekly(
            request=request, team=team, customer=customer, _user=_user,
        )

    @r.get("/team-projection-weekly")
    async def team_projection_weekly(
        request: Request,
        customer: Optional[str] = Query(None),
        load_type: Optional[str] = Query(None),
        lanes: Optional[List[str]] = Query(None),
        exclude_lanes: Optional[List[str]] = Query(None),
        carriers: Optional[List[str]] = Query(None),
        exclude_carriers: Optional[List[str]] = Query(None),
        _user: dict = Depends(gate),
    ):
        return await opo.team_projection_weekly(
            request=request, team=team, customer=customer, load_type=load_type,
            lanes=lanes, exclude_lanes=exclude_lanes, carriers=carriers, exclude_carriers=exclude_carriers, _user=_user,
        )

    return r


# Build all 4 routers at import time — include them in main.py.
team_routers: tuple[APIRouter, ...] = tuple(
    _make_team_router(team, slug, role) for team, slug, role in TEAM_CONFIGS
)
