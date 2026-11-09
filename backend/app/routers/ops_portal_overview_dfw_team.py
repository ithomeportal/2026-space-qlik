"""OPS Portal DFW TM1..TM4 — the DFW portal, scope-LOCKED to one sub-team.

Bruno PDF "BRUNO -- Ops Portal DFW" (2026-11-09): duplicate
/reports/ops-managers-portal-dfw four times, "OPS Portal DFW TM1".."TM4",
each with TEAMS = its TM. No TM5.

Endpoints (per team):
    /api/custom/ops-portal-overview-dfw-tm1/* … /ops-portal-overview-dfw-tm4/*

Role gate (per report):
    require_report_access("ops-portal-dfw-tmN") — DB-backed, admin/CEO bypass,
    role list editable via /admin/reports.

How this differs from the two existing families
-----------------------------------------------
* ``ops_portal_overview_team.py`` (CORP T1-T4) locks a CORP team and delegates
  to the CORP functions.
* ``ops_portal_overview_dfw.py`` is the whole DFW DIVISION with TM1..TM5 pills.

This is the DFW portal with the pill pinned. Each shim delegates to the DFW
MODULE's function (not the CORP one) with ``team=TMn``, so a clone inherits
every DFW-only behaviour by construction: month-over-month Customer Variance,
Actuals vs the same days of last month (``compare="prior_month"``), no budget
endpoints at all.

⚠ ``dependencies=[Depends(dfw._pin_dfw_scope)]`` is load-bearing. The DFW
functions read the division from ``request.state`` (``_scope.scope_of``); the
pin lives on the DFW ROUTER, not inside the functions. Without it here every
query runs under the CORP default, where ``TM1`` is not a sub-team — the team
widens to nothing and the page renders zeros without an error.

⚠ The team lock: no shim declares ``team``/``teams``, so FastAPI never reads a
crafted ``?team=TM2`` off the TM1 page; the closure's ``tm`` is the only team
that reaches SQL. Every other param is forwarded explicitly with the DFW
shim's own default — a direct Python call never applies ``Query()`` defaults,
and a dropped param is silent (SPEC-CODE-RULES §40).

⚠ The two cross-team breakdowns are deliberately NOT registered:
``/team-projection-by-team`` (the DFW function takes no ``team``) and
``/team-performance-by-team`` (it takes one but IGNORES it — "this panel always
returns all teams", ``performance.py``). Either would hand a TM1 viewer the
other four teams' numbers, and their only callers — the Monthly Projection /
Monthly Performance "Team" buttons — are hidden whenever ``lockedTeam`` is set.
Found by the end-to-end probe, not by reading: the CORP T1-T4 clones still
register ``/team-performance-by-team``. Budget endpoints do not exist on the
DFW portal either.

Measured/asserted in ``tests/test_ops_portal_dfw_team_scope.py``.
"""

# FastAPI declares query params as `Query()` defaults — the idiom B008 flags.
# ruff: noqa: B008
from __future__ import annotations

import asyncio
from datetime import date

from fastapi import APIRouter, Depends, Query, Request

from app.routers import ops_portal_overview as opo
from app.routers import ops_portal_overview_dfw as dfw
from app.routers.deps import get_datalake_gold_pool, require_report_access
from app.routers.ops_portal_overview._scope import DFW_SCOPE
from app.routers.ops_portal_overview._sql import _v4_scope_where

# One line per report. TM5 is not requested (Bruno 2026-11-09).
TEAM_CONFIGS: tuple[str, ...] = ("TM1", "TM2", "TM3", "TM4")


async def _filters(request: Request, tm: str) -> dict:
    """Customers / lanes / carriers of the DFW division narrowed to ``tm``.

    Built on ``_v4_scope_where`` under ``DFW_SCOPE`` — the SAME predicate every
    panel on the page uses — so the pickers list exactly the rows the panels
    count: TEAM-DFW plus the CORP-team rows the revenue-code rule makes DFW, and
    those land in TM4 (§134 §135). Never a bare ``team_id = ANY``.
    """
    pool = get_datalake_gold_pool(request)
    params: list = []
    where = _v4_scope_where("br4", tm, None, None, params, scope=DFW_SCOPE)
    params.append(opo.YEAR_START)
    p_start = len(params)
    cust_sql = f"""
        SELECT DISTINCT TRIM(br4.customer_name) AS customer_name
        FROM public.mcleod_gld_budget_report_v4 br4
        WHERE {where}
          AND br4.origin_actual_departure >= ${p_start}
          AND br4.customer_name IS NOT NULL
          AND TRIM(br4.customer_name) <> ''
        ORDER BY 1
    """
    lane_sql = f"""
        SELECT DISTINCT {opo._lane_expr("br4")} AS lane
        FROM public.mcleod_gld_budget_report_v4 br4
        WHERE {where}
          AND br4.origin_actual_departure >= ${p_start}
          AND TRIM(COALESCE(br4.origin_name,'')) <> ''
          AND TRIM(COALESCE(br4.dest_name,''))   <> ''
        ORDER BY 1
    """
    carrier_sql = f"""
        SELECT DISTINCT TRIM(m.payee_name) AS carrier
        FROM public.mcleod_gld_budget_report_v4 br4
        JOIN public.mcleod_gld_movement m
          ON m.order_id = br4.id AND m.company_id = br4.company_id
        WHERE {where}
          AND br4.origin_actual_departure >= ${p_start}
          AND TRIM(COALESCE(m.payee_name,'')) <> ''
        ORDER BY 1
    """
    cust_rows, lane_rows, carrier_rows = await asyncio.gather(
        pool.fetch(cust_sql, *params),
        pool.fetch(lane_sql, *params),
        pool.fetch(carrier_sql, *params),
    )
    return {
        "success": True,
        "data": {
            "teams": [tm],
            "customers": [r0["customer_name"] for r0 in cust_rows],
            "lanes": [r0["lane"] for r0 in lane_rows],
            "carriers": [r0["carrier"] for r0 in carrier_rows],
            "year_start": opo.YEAR_START.isoformat(),
            "year_end": opo.YEAR_END.isoformat(),
            "locked_team": tm,
            "division": DFW_SCOPE.label,
            "has_budget": DFW_SCOPE.has_budget,
        },
    }


def _make_team_router(tm: str) -> APIRouter:
    """One APIRouter for a single DFW sub-team; every shim pins ``team=tm``."""
    slug = tm.lower()
    gate = require_report_access(f"ops-portal-dfw-{slug}")
    r = APIRouter(
        tags=[f"ops-portal-overview-dfw-{slug}"],
        prefix=f"/custom/ops-portal-overview-dfw-{slug}",
        dependencies=[Depends(dfw._pin_dfw_scope)],
    )

    @r.get("/filters")
    async def filters(request: Request, _user: dict = Depends(gate)):
        return await _filters(request, tm)

    @r.get("/customer-variance")
    async def customer_variance(
        request: Request,
        customer: list[str] | None = Query(None),
        load_type: str | None = Query(None),
        lanes: list[str] | None = Query(None),
        exclude_lanes: list[str] | None = Query(None),
        carriers: list[str] | None = Query(None),
        exclude_carriers: list[str] | None = Query(None),
        limit: int = Query(50, ge=1, le=200),
        _user: dict = Depends(gate),
    ):
        return await dfw.customer_variance(
            request=request, team=tm, customer=customer, load_type=load_type,
            lanes=lanes, exclude_lanes=exclude_lanes, carriers=carriers,
            exclude_carriers=exclude_carriers, limit=limit, _user=_user,
        )

    @r.get("/workdays")
    async def workdays(request: Request, _user: dict = Depends(gate)):
        return await dfw.workdays(request=request, _user=_user)

    @r.get("/combo")
    async def combo(
        request: Request,
        customer: list[str] | None = Query(None),
        load_type: str | None = Query(None),
        lanes: list[str] | None = Query(None),
        exclude_lanes: list[str] | None = Query(None),
        carriers: list[str] | None = Query(None),
        exclude_carriers: list[str] | None = Query(None),
        grain: str = Query("month"),
        _user: dict = Depends(gate),
    ):
        return await dfw.combo(
            request=request, team=tm, customer=customer, load_type=load_type,
            lanes=lanes, exclude_lanes=exclude_lanes, carriers=carriers,
            exclude_carriers=exclude_carriers, grain=grain, _user=_user,
        )

    @r.get("/customer-losses")
    async def customer_losses(
        request: Request,
        range: str | None = Query("mtd"),
        start_date: date | None = Query(None),
        end_date: date | None = Query(None),
        customer: list[str] | None = Query(None),
        load_type: str | None = Query(None),
        lanes: list[str] | None = Query(None),
        exclude_lanes: list[str] | None = Query(None),
        carriers: list[str] | None = Query(None),
        exclude_carriers: list[str] | None = Query(None),
        limit: int = Query(50, ge=1, le=200),
        _user: dict = Depends(gate),
    ):
        return await dfw.customer_losses(
            request=request, team=tm, range=range, start_date=start_date,
            end_date=end_date, customer=customer, load_type=load_type, lanes=lanes,
            exclude_lanes=exclude_lanes, carriers=carriers,
            exclude_carriers=exclude_carriers, limit=limit, _user=_user,
        )

    @r.get("/customer-overpay")
    async def customer_overpay(
        request: Request,
        range: str | None = Query("mtd"),
        start_date: date | None = Query(None),
        end_date: date | None = Query(None),
        customer: list[str] | None = Query(None),
        load_type: str | None = Query(None),
        lanes: list[str] | None = Query(None),
        exclude_lanes: list[str] | None = Query(None),
        carriers: list[str] | None = Query(None),
        exclude_carriers: list[str] | None = Query(None),
        limit: int = Query(100, ge=1, le=500),
        _user: dict = Depends(gate),
    ):
        return await dfw.customer_overpay(
            request=request, team=tm, range=range, start_date=start_date,
            end_date=end_date, customer=customer, load_type=load_type, lanes=lanes,
            exclude_lanes=exclude_lanes, carriers=carriers,
            exclude_carriers=exclude_carriers, limit=limit, _user=_user,
        )

    @r.get("/team-performance")
    async def team_performance(
        request: Request,
        range: str | None = Query("mtd"),
        start_date: date | None = Query(None),
        end_date: date | None = Query(None),
        customer: list[str] | None = Query(None),
        load_type: str | None = Query(None),
        lanes: list[str] | None = Query(None),
        exclude_lanes: list[str] | None = Query(None),
        carriers: list[str] | None = Query(None),
        exclude_carriers: list[str] | None = Query(None),
        _user: dict = Depends(gate),
    ):
        return await dfw.team_performance(
            request=request, team=tm, range=range, start_date=start_date,
            end_date=end_date, customer=customer, load_type=load_type, lanes=lanes,
            exclude_lanes=exclude_lanes, carriers=carriers,
            exclude_carriers=exclude_carriers, _user=_user,
        )

    @r.get("/team-projection")
    async def team_projection(
        request: Request,
        customer: list[str] | None = Query(None),
        load_type: str | None = Query(None),
        lanes: list[str] | None = Query(None),
        exclude_lanes: list[str] | None = Query(None),
        carriers: list[str] | None = Query(None),
        exclude_carriers: list[str] | None = Query(None),
        _user: dict = Depends(gate),
    ):
        return await dfw.team_projection(
            request=request, team=tm, customer=customer, load_type=load_type,
            lanes=lanes, exclude_lanes=exclude_lanes, carriers=carriers,
            exclude_carriers=exclude_carriers, _user=_user,
        )

    @r.get("/profit-tm-gauge")
    async def profit_tm_gauge(
        request: Request,
        customer: list[str] | None = Query(None),
        load_type: str | None = Query(None),
        lanes: list[str] | None = Query(None),
        exclude_lanes: list[str] | None = Query(None),
        carriers: list[str] | None = Query(None),
        exclude_carriers: list[str] | None = Query(None),
        _user: dict = Depends(gate),
    ):
        return await dfw.profit_tm_gauge(
            request=request, team=tm, customer=customer, load_type=load_type,
            lanes=lanes, exclude_lanes=exclude_lanes, carriers=carriers,
            exclude_carriers=exclude_carriers, _user=_user,
        )

    @r.get("/actuals")
    async def actuals(
        request: Request,
        range: str | None = Query("mtd"),
        start_date: date | None = Query(None),
        end_date: date | None = Query(None),
        customer: list[str] | None = Query(None),
        load_type: str | None = Query(None),
        lanes: list[str] | None = Query(None),
        exclude_lanes: list[str] | None = Query(None),
        carriers: list[str] | None = Query(None),
        exclude_carriers: list[str] | None = Query(None),
        sort: str = Query("revenue_desc"),
        limit: int = Query(100, ge=1, le=500),
        losses_only: bool = Query(False),
        unbilled_only: bool = Query(False),
        _user: dict = Depends(gate),
    ):
        # The DFW shim pins compare="prior_month" — inherited, not restated.
        return await dfw.actuals(
            request=request, team=tm, range=range, start_date=start_date,
            end_date=end_date, customer=customer, load_type=load_type, lanes=lanes,
            exclude_lanes=exclude_lanes, carriers=carriers,
            exclude_carriers=exclude_carriers, sort=sort, limit=limit,
            losses_only=losses_only, unbilled_only=unbilled_only, _user=_user,
        )

    @r.get("/actuals-by-lane")
    async def actuals_by_lane(
        request: Request,
        range: str | None = Query("mtd"),
        start_date: date | None = Query(None),
        end_date: date | None = Query(None),
        customer: list[str] | None = Query(None),
        load_type: str | None = Query(None),
        lanes: list[str] | None = Query(None),
        exclude_lanes: list[str] | None = Query(None),
        carriers: list[str] | None = Query(None),
        exclude_carriers: list[str] | None = Query(None),
        sort: str = Query("revenue_desc"),
        limit: int = Query(100, ge=1, le=500),
        losses_only: bool = Query(False),
        unbilled_only: bool = Query(False),
        _user: dict = Depends(gate),
    ):
        return await dfw.actuals_by_lane(
            request=request, team=tm, range=range, start_date=start_date,
            end_date=end_date, customer=customer, load_type=load_type, lanes=lanes,
            exclude_lanes=exclude_lanes, carriers=carriers,
            exclude_carriers=exclude_carriers, sort=sort, limit=limit,
            losses_only=losses_only, unbilled_only=unbilled_only, _user=_user,
        )

    @r.get("/service")
    async def service(
        request: Request,
        customer: list[str] | None = Query(None),
        load_type: str | None = Query(None),
        lanes: list[str] | None = Query(None),
        exclude_lanes: list[str] | None = Query(None),
        carriers: list[str] | None = Query(None),
        exclude_carriers: list[str] | None = Query(None),
        grain: str = Query("month"),
        _user: dict = Depends(gate),
    ):
        return await dfw.service(
            request=request, team=tm, customer=customer, load_type=load_type,
            lanes=lanes, exclude_lanes=exclude_lanes, carriers=carriers,
            exclude_carriers=exclude_carriers, grain=grain, _user=_user,
        )

    @r.get("/by-order")
    async def by_order(
        request: Request,
        range: str | None = Query("mtd"),
        start_date: date | None = Query(None),
        end_date: date | None = Query(None),
        customer: list[str] | None = Query(None),
        load_type: str | None = Query(None),
        lanes: list[str] | None = Query(None),
        exclude_lanes: list[str] | None = Query(None),
        carriers: list[str] | None = Query(None),
        exclude_carriers: list[str] | None = Query(None),
        sort: str = Query("revenue_desc"),
        limit: int = Query(500, ge=1, le=2000),
        losses_only: bool = Query(False),
        unbilled_only: bool = Query(False),
        _user: dict = Depends(gate),
    ):
        return await dfw.by_order(
            request=request, team=tm, range=range, start_date=start_date,
            end_date=end_date, customer=customer, load_type=load_type, lanes=lanes,
            exclude_lanes=exclude_lanes, carriers=carriers,
            exclude_carriers=exclude_carriers, sort=sort, limit=limit,
            losses_only=losses_only, unbilled_only=unbilled_only, _user=_user,
        )

    @r.get("/pending-to-cover")
    async def pending_to_cover(
        request: Request,
        customer: list[str] | None = Query(None),
        lanes: list[str] | None = Query(None),
        exclude_lanes: list[str] | None = Query(None),
        limit: int = Query(500, ge=1, le=2000),
        _user: dict = Depends(gate),
    ):
        return await dfw.pending_to_cover(
            request=request, team=tm, customer=customer, lanes=lanes,
            exclude_lanes=exclude_lanes, limit=limit, _user=_user,
        )

    @r.get("/cover")
    async def cover(
        request: Request,
        customer: list[str] | None = Query(None),
        lanes: list[str] | None = Query(None),
        exclude_lanes: list[str] | None = Query(None),
        limit: int = Query(500, ge=1, le=2000),
        _user: dict = Depends(gate),
    ):
        return await dfw.cover(
            request=request, team=tm, customer=customer, lanes=lanes,
            exclude_lanes=exclude_lanes, limit=limit, _user=_user,
        )

    @r.get("/hold")
    async def hold(
        request: Request,
        customer: list[str] | None = Query(None),
        lanes: list[str] | None = Query(None),
        exclude_lanes: list[str] | None = Query(None),
        # Must track hold.py's default (test_ops_portal_hold.py).
        sort: str = Query("delay_asc"),
        limit: int = Query(500, ge=1, le=2000),
        _user: dict = Depends(gate),
    ):
        return await dfw.hold(
            request=request, team=tm, customer=customer, lanes=lanes,
            exclude_lanes=exclude_lanes, sort=sort, limit=limit, _user=_user,
        )

    @r.get("/cover-forecast")
    async def cover_forecast(
        request: Request,
        customer: list[str] | None = Query(None),
        load_type: str | None = Query(None),
        lanes: list[str] | None = Query(None),
        exclude_lanes: list[str] | None = Query(None),
        carriers: list[str] | None = Query(None),
        exclude_carriers: list[str] | None = Query(None),
        grain: str = Query("month"),
        _user: dict = Depends(gate),
    ):
        return await dfw.cover_forecast(
            request=request, team=tm, customer=customer, load_type=load_type,
            lanes=lanes, exclude_lanes=exclude_lanes, carriers=carriers,
            exclude_carriers=exclude_carriers, grain=grain, _user=_user,
        )

    # EIA diesel market data: division-blind, but still behind THIS gate.
    @r.get("/fuel")
    async def fuel(
        request: Request,
        grain: str = Query("month"),
        start: date | None = Query(None),
        end: date | None = Query(None),
        _user: dict = Depends(gate),
    ):
        return await dfw.fuel(request=request, grain=grain, start=start, end=end, _user=_user)

    # Source-level, not team-scoped: staleness is a property of the ETL feed.
    @r.get("/data-freshness")
    async def data_freshness(request: Request, _user: dict = Depends(gate)):
        return await dfw.data_freshness(request=request, _user=_user)

    @r.get("/team-weekly-performance")
    async def team_weekly_performance(
        request: Request,
        customer: list[str] | None = Query(None),
        load_type: str | None = Query(None),
        lanes: list[str] | None = Query(None),
        exclude_lanes: list[str] | None = Query(None),
        carriers: list[str] | None = Query(None),
        exclude_carriers: list[str] | None = Query(None),
        _user: dict = Depends(gate),
    ):
        return await dfw.team_weekly_performance(
            request=request, team=tm, customer=customer, load_type=load_type,
            lanes=lanes, exclude_lanes=exclude_lanes, carriers=carriers,
            exclude_carriers=exclude_carriers, _user=_user,
        )

    @r.get("/service-incident-by-customer")
    async def service_incident_by_customer(
        request: Request,
        range: str | None = Query("mtd"),
        start_date: date | None = Query(None),
        end_date: date | None = Query(None),
        customer: list[str] | None = Query(None),
        load_type: str | None = Query(None),
        lanes: list[str] | None = Query(None),
        exclude_lanes: list[str] | None = Query(None),
        carriers: list[str] | None = Query(None),
        exclude_carriers: list[str] | None = Query(None),
        stop_type: str = Query("pu"),
        _user: dict = Depends(gate),
    ):
        return await dfw.service_incident_by_customer(
            request=request, team=tm, range=range, start_date=start_date,
            end_date=end_date, customer=customer, load_type=load_type, lanes=lanes,
            exclude_lanes=exclude_lanes, carriers=carriers,
            exclude_carriers=exclude_carriers, stop_type=stop_type, _user=_user,
        )

    @r.get("/service-by-carrier")
    async def service_by_carrier(
        request: Request,
        range: str | None = Query("mtd"),
        start_date: date | None = Query(None),
        end_date: date | None = Query(None),
        customer: list[str] | None = Query(None),
        load_type: str | None = Query(None),
        lanes: list[str] | None = Query(None),
        exclude_lanes: list[str] | None = Query(None),
        carriers: list[str] | None = Query(None),
        exclude_carriers: list[str] | None = Query(None),
        limit: int = Query(100, ge=1, le=500),
        _user: dict = Depends(gate),
    ):
        return await dfw.service_by_carrier(
            request=request, team=tm, range=range, start_date=start_date,
            end_date=end_date, customer=customer, load_type=load_type, lanes=lanes,
            exclude_lanes=exclude_lanes, carriers=carriers,
            exclude_carriers=exclude_carriers, limit=limit, _user=_user,
        )

    @r.get("/margin-distribution")
    async def margin_distribution(
        request: Request,
        range: str | None = Query("mtd"),
        start_date: date | None = Query(None),
        end_date: date | None = Query(None),
        customer: list[str] | None = Query(None),
        load_type: str | None = Query(None),
        lanes: list[str] | None = Query(None),
        exclude_lanes: list[str] | None = Query(None),
        carriers: list[str] | None = Query(None),
        exclude_carriers: list[str] | None = Query(None),
        _user: dict = Depends(gate),
    ):
        return await dfw.margin_distribution(
            request=request, team=tm, range=range, start_date=start_date,
            end_date=end_date, customer=customer, load_type=load_type, lanes=lanes,
            exclude_lanes=exclude_lanes, carriers=carriers,
            exclude_carriers=exclude_carriers, _user=_user,
        )

    @r.get("/team-projection-weekly")
    async def team_projection_weekly(
        request: Request,
        customer: list[str] | None = Query(None),
        load_type: str | None = Query(None),
        lanes: list[str] | None = Query(None),
        exclude_lanes: list[str] | None = Query(None),
        carriers: list[str] | None = Query(None),
        exclude_carriers: list[str] | None = Query(None),
        _user: dict = Depends(gate),
    ):
        return await dfw.team_projection_weekly(
            request=request, team=tm, customer=customer, load_type=load_type,
            lanes=lanes, exclude_lanes=exclude_lanes, carriers=carriers,
            exclude_carriers=exclude_carriers, _user=_user,
        )

    # Resolves the dfw/TMn stored series; the DFW shim pins teams=None.
    @r.get("/team-projection-history")
    async def team_projection_history(
        request: Request,
        customer: list[str] | None = Query(None),
        load_type: str | None = Query(None),
        lanes: list[str] | None = Query(None),
        exclude_lanes: list[str] | None = Query(None),
        carriers: list[str] | None = Query(None),
        exclude_carriers: list[str] | None = Query(None),
        months: int = Query(13, ge=1, le=60),
        _user: dict = Depends(gate),
    ):
        return await dfw.team_projection_history(
            request=request, team=tm, customer=customer, load_type=load_type,
            lanes=lanes, exclude_lanes=exclude_lanes, carriers=carriers,
            exclude_carriers=exclude_carriers, months=months, _user=_user,
        )

    return r


# Built at import time — main.py includes them next to the DFW router.
team_routers: tuple[APIRouter, ...] = tuple(_make_team_router(tm) for tm in TEAM_CONFIGS)
