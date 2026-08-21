"""Ops Managers Portal – DFW — the DFW division copy of Ops Portal Overview.

Bruno PDF "space -- Ops Portal DFW" (2026-08-20).

Endpoints:
    /api/custom/ops-portal-overview-dfw/*

Role gate:
    require_report_access("ops-managers-portal-dfw") — DB-backed per-report
    list, admin always bypasses, role list editable via /admin/reports.

What makes this different from the four CORP-T clones
-----------------------------------------------------
Those are **scope-LOCKED** copies: one CORP team pinned server-side, Team pills
hidden. This is a **DIVISION** copy: the whole DFW division, with TM1..TM5 as
its team dimension. It is the DFW analogue of the cross-team CORP portal, not
of a locked clone.

That is Request 3 exactly — "remove the filter team_id='TEAM1..TEAM5', add
team_id='TEAM-DFW', however display the teams in the team column as
TM1..TM5" — and it is why the work is a `DivisionScope` (``_scope.py``) rather
than another ``TEAM_CONFIGS`` row: under DFW the team a row belongs to lives in
``v4.team``, because ``team_id`` is the constant 'TEAM-DFW'.

⚠ Budget is GONE from this portal, and that is data-driven, not cosmetic
------------------------------------------------------------------------
Requests 5-8 delete the BDGT chart series, the Team Budget Monthly Variance
table, and the All / Budget / Variance-per-Cell modes, and Request 7 redefines
Customer Monthly Variance as month-over-month. Measured 2026-08-21: **0 of
DFW's 15 YTD customers appear in ``daily_production_budget_report``**, against
66 of 66 for CORP. Every budget panel here would render zeros.

So the budget endpoints are not merely hidden in the UI — they are not exposed
at all (``/team-variance``, ``/team-variance-weekly``), and ``DFW_SCOPE`` sets
``has_budget=False`` so the surviving endpoints skip the budget statement
instead of running a CORP-restricted CTE on behalf of a DFW page.

⚠ How the scope is pinned
-------------------------
A router-level dependency stamps ``request.state.opp_scope = DFW_SCOPE`` before
any handler runs; ``_scope.scope_of(request)`` reads it inside the shared
``ops_portal_overview`` package. It is request state, never module state, so
concurrent CORP and DFW requests cannot see each other's scope, and it is NOT
a query parameter — a client-settable scope would let a DFW user widen onto
CORP data.

⚠ Every param is forwarded explicitly — a direct Python call never applies
FastAPI ``Query()`` defaults, so an omitted param arrives as a FieldInfo and
500s (SPEC-CODE-RULES §40). ``team`` is additionally normalised through
``_sub_team``: it is a real user-facing pill here, but only TM1..TM5 are
accepted, so a crafted ``?team=TEAM1`` becomes "no narrowing" rather than a
predicate that silently returns nothing.
"""

from __future__ import annotations

import asyncio
from datetime import date, timedelta
from typing import List, Optional

from fastapi import APIRouter, Depends, Query, Request

from app.clock import cst_today
from app.routers import ops_portal_overview as opo
from app.routers.deps import get_datalake_gold_pool, require_report_access
from app.routers.ops_portal_overview._dates import _month_bounds
from app.routers.ops_portal_overview._metrics import _safe_float
from app.routers.ops_portal_overview._scope import DFW_SCOPE
from app.routers.ops_portal_overview._sql import _v4_scope_where

REPORT_KEY = "ops-managers-portal-dfw"

gate = require_report_access(REPORT_KEY)


def _pin_dfw_scope(request: Request) -> None:
    """Stamp the DFW division onto the request before any handler runs."""
    request.state.opp_scope = DFW_SCOPE


def _sub_team(team: Optional[str]) -> Optional[str]:
    """Accept only this division's sub-teams; anything else means "all".

    ⚠ Returns None rather than raising. An unknown value must widen to the
    division, never narrow to nothing: a predicate that matches zero rows is
    indistinguishable from "this team had no work" (§75).
    """
    if not isinstance(team, str):
        return None
    t = team.strip().upper()
    return t if t in DFW_SCOPE.sub_teams else None


r = APIRouter(
    tags=["ops-portal-overview-dfw"],
    prefix="/custom/ops-portal-overview-dfw",
    # Runs before every handler below, including the ones that then call the
    # CORP functions directly in Python.
    dependencies=[Depends(_pin_dfw_scope)],
)


# ---- /filters — DFW customers + lanes, TM1..TM5 as the team pills ----------
@r.get("/filters")
async def filters(request: Request, _user: dict = Depends(gate)):
    """teams = TM1..TM5; customers + lanes scoped to TEAM-DFW.

    Hand-written rather than delegated for the same reason the CORP-T clones
    override theirs: the CORP /filters returns every CORP customer, which on a
    DFW page is both wrong and a disclosure. Measured 2026-08-21, DFW has 15
    customers YTD against CORP's 66.
    """
    pool = get_datalake_gold_pool(request)
    scope_args = [
        list(DFW_SCOPE.base_teams),
        list(opo.CORP_COMPANIES),
        list(opo.OPEN_STATUSES),
        opo.YEAR_START,
    ]
    cust_sql = """
        SELECT DISTINCT TRIM(br4.customer_name) AS customer_name
        FROM public.mcleod_gld_budget_report_v4 br4
        WHERE TRIM(br4.team_id) = ANY($1)
          AND TRIM(br4.company_id) = ANY($2)
          AND TRIM(br4.status) = ANY($3)
          AND br4.origin_actual_departure >= $4
          AND br4.customer_name IS NOT NULL
          AND UPPER(COALESCE(br4.customer_name,'')) NOT LIKE '%OILTEX%'
        ORDER BY 1
    """
    lane_sql = f"""
        SELECT DISTINCT {opo._lane_expr("br4")} AS lane
        FROM public.mcleod_gld_budget_report_v4 br4
        WHERE TRIM(br4.team_id) = ANY($1)
          AND TRIM(br4.company_id) = ANY($2)
          AND TRIM(br4.status) = ANY($3)
          AND br4.origin_actual_departure >= $4
          AND TRIM(COALESCE(br4.origin_name,'')) <> ''
          AND TRIM(COALESCE(br4.dest_name,''))   <> ''
        ORDER BY 1
    """
    carrier_sql = """
        SELECT DISTINCT TRIM(m.payee_name) AS carrier
        FROM public.mcleod_gld_budget_report_v4 br4
        JOIN public.mcleod_gld_movement m
          ON m.order_id = br4.id AND m.company_id = br4.company_id
        WHERE TRIM(br4.team_id) = ANY($1)
          AND TRIM(br4.company_id) = ANY($2)
          AND TRIM(br4.status) = ANY($3)
          AND br4.origin_actual_departure >= $4
          AND TRIM(COALESCE(m.payee_name,'')) <> ''
        ORDER BY 1
    """
    cust_rows, lane_rows, carrier_rows = await asyncio.gather(
        pool.fetch(cust_sql, *scope_args),
        pool.fetch(lane_sql, *scope_args),
        pool.fetch(carrier_sql, *scope_args),
    )
    return {
        "success": True,
        "data": {
            "teams": list(DFW_SCOPE.sub_teams),
            "customers": [r0["customer_name"] for r0 in cust_rows],
            "lanes": [r0["lane"] for r0 in lane_rows],
            "carriers": [r0["carrier"] for r0 in carrier_rows],
            "division": DFW_SCOPE.label,
            "has_budget": DFW_SCOPE.has_budget,
        },
    }


# ---- /customer-variance — Request 7: month-over-month, not vs budget -------
@r.get("/customer-variance")
async def customer_variance(
    request: Request,
    team: Optional[str] = Query(None),
    customer: Optional[str] = Query(None),
    load_type: Optional[str] = Query(None),
    lanes: Optional[List[str]] = Query(None),
    exclude_lanes: Optional[List[str]] = Query(None),
    carriers: Optional[List[str]] = Query(None),
    exclude_carriers: Optional[List[str]] = Query(None),
    limit: int = Query(50, ge=1, le=200),
    _user: dict = Depends(gate),
):
    """Per customer: LAST month minus THIS month, on origin_actual_departure.

    Bruno PDF 2026-08-20 Request 7, verbatim:
        Vol    = count(id where origin_actual_departure = last_month)
                 - count(id where origin_actual_departure = this_month)
        Profit = sum(margin_amt where origin_actual_departure = last_month)
                 - sum(margin_amt where origin_actual_departure = this_month)

    ⚠ This REPLACES the CORP definition (actual − budget) rather than extending
    it. Same endpoint name, same wire fields, different metric — which is only
    safe because it is a different report: the CORP portal keeps its own
    /customer-variance untouched, and this one is not reachable from it.

    ⚠ Deliberately NOT date-windowed by the page filter. "Last month vs this
    month" is a calendar statement; inheriting the page's range would make the
    two halves mean whatever the user last clicked, and an MTD range would
    compare a full month against a partial one under a label that says neither.

    ⚠ Both months come from ONE scan with FILTER clauses, not two statements
    (§73): a second pass over a live table can disagree with the first — v4 is
    refreshed every 15 minutes and orders move between runs.

    ⚠ The direction is last − this, exactly as written: POSITIVE means the
    customer is DOWN this month. That is the opposite sign convention from the
    CORP panel's actual − budget, so the UI labels it explicitly.
    """
    pool = get_datalake_gold_pool(request)
    today = cst_today()
    this_start, this_end = _month_bounds(today)
    last_end = this_start - timedelta(days=1)
    last_start, _ = _month_bounds(last_end)

    params: list = []
    where = _v4_scope_where(
        "br4", _sub_team(team), customer, load_type, params,
        lanes, exclude_lanes, carriers, exclude_carriers, scope=DFW_SCOPE,
    )
    params.extend([last_start, last_end, this_start, this_end, limit])
    n = len(params)
    p_ls, p_le, p_ts, p_te, p_lim = n - 4, n - 3, n - 2, n - 1, n

    rows = await pool.fetch(
        f"""
        SELECT
          br4.customer_name AS customer_name,
          COUNT(*) FILTER (
            WHERE br4.origin_actual_departure >= ${p_ls}
              AND br4.origin_actual_departure < (${p_le}::date + INTERVAL '1 day')
          ) AS vol_last,
          COUNT(*) FILTER (
            WHERE br4.origin_actual_departure >= ${p_ts}
              AND br4.origin_actual_departure < (${p_te}::date + INTERVAL '1 day')
          ) AS vol_this,
          COALESCE(SUM(br4.margin_amt) FILTER (
            WHERE br4.origin_actual_departure >= ${p_ls}
              AND br4.origin_actual_departure < (${p_le}::date + INTERVAL '1 day')
          ), 0)::numeric AS profit_last,
          COALESCE(SUM(br4.margin_amt) FILTER (
            WHERE br4.origin_actual_departure >= ${p_ts}
              AND br4.origin_actual_departure < (${p_te}::date + INTERVAL '1 day')
          ), 0)::numeric AS profit_this,
          COALESCE(SUM(br4.total_charge) FILTER (
            WHERE br4.origin_actual_departure >= ${p_ls}
              AND br4.origin_actual_departure < (${p_le}::date + INTERVAL '1 day')
          ), 0)::numeric AS revenue_last,
          COALESCE(SUM(br4.total_charge) FILTER (
            WHERE br4.origin_actual_departure >= ${p_ts}
              AND br4.origin_actual_departure < (${p_te}::date + INTERVAL '1 day')
          ), 0)::numeric AS revenue_this
        FROM public.mcleod_gld_budget_report_v4 br4
        WHERE {where}
          AND br4.origin_actual_departure >= ${p_ls}
          AND br4.origin_actual_departure < (${p_te}::date + INTERVAL '1 day')
        GROUP BY br4.customer_name
        HAVING COUNT(*) > 0
        ORDER BY ABS(
          COALESCE(SUM(br4.margin_amt) FILTER (
            WHERE br4.origin_actual_departure >= ${p_ls}
              AND br4.origin_actual_departure < (${p_le}::date + INTERVAL '1 day')
          ), 0)
          - COALESCE(SUM(br4.margin_amt) FILTER (
            WHERE br4.origin_actual_departure >= ${p_ts}
              AND br4.origin_actual_departure < (${p_te}::date + INTERVAL '1 day')
          ), 0)
        ) DESC NULLS LAST
        LIMIT ${p_lim}
        """,
        *params,
    )
    return {
        "success": True,
        "data": [
            {
                "customer_name": r0["customer_name"],
                # Same wire names the shared panel already reads, so the
                # frontend needs no per-report branching for the values —
                # only for the labels (§69: the meaning is named in `basis`).
                "volume_var": int(r0["vol_last"] or 0) - int(r0["vol_this"] or 0),
                "profit_var": _safe_float(r0["profit_last"]) - _safe_float(r0["profit_this"]),
                "revenue_var": _safe_float(r0["revenue_last"]) - _safe_float(r0["revenue_this"]),
                "vol_last": int(r0["vol_last"] or 0),
                "vol_this": int(r0["vol_this"] or 0),
                "profit_last": _safe_float(r0["profit_last"]),
                "profit_this": _safe_float(r0["profit_this"]),
            }
            for r0 in rows
        ],
        "meta": {
            "basis": "month_over_month",
            "last_month": last_start.isoformat(),
            "this_month": this_start.isoformat(),
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
    team: Optional[str] = Query(None),
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
        request=request, team=_sub_team(team), customer=customer, load_type=load_type,
        lanes=lanes, exclude_lanes=exclude_lanes, carriers=carriers, exclude_carriers=exclude_carriers, grain=grain, _user=_user,
    )



# ---- /customer-losses -------------------------------------------------
@r.get("/customer-losses")
async def customer_losses(
    request: Request,
    team: Optional[str] = Query(None),
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
        team=_sub_team(team), customer=customer, load_type=load_type, lanes=lanes,
        exclude_lanes=exclude_lanes, carriers=carriers, exclude_carriers=exclude_carriers, limit=limit, _user=_user,
    )

# ---- /customer-not-billed ---------------------------------------------
# MANDATORY: `SidePanels` renders the "Not Billed" panel unconditionally, so a
# missing delegator 404s a visible panel while the rest of the page looks fine.
# (The four CORP-T clones are missing exactly this shim — fixed there too.)
@r.get("/customer-not-billed")
async def customer_not_billed(
    request: Request,
    range: Optional[str] = Query("mtd"),
    start_date: Optional[date] = Query(None),
    end_date: Optional[date] = Query(None),
    team: Optional[str] = Query(None),
    customer: Optional[str] = Query(None),
    load_type: Optional[str] = Query(None),
    lanes: Optional[List[str]] = Query(None),
    exclude_lanes: Optional[List[str]] = Query(None),
    carriers: Optional[List[str]] = Query(None),
    exclude_carriers: Optional[List[str]] = Query(None),
    limit: int = Query(100, ge=1, le=500),
    _user: dict = Depends(gate),
):
    return await opo.customer_not_billed(
        request=request, range=range, start_date=start_date, end_date=end_date,
        team=_sub_team(team), customer=customer, load_type=load_type, lanes=lanes,
        exclude_lanes=exclude_lanes, carriers=carriers,
        exclude_carriers=exclude_carriers, limit=limit, _user=_user,
    )


# ---- /team-performance ------------------------------------------------
@r.get("/team-performance")
async def team_performance(
    request: Request,
    team: Optional[str] = Query(None),
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
        team=_sub_team(team), customer=customer, load_type=load_type, lanes=lanes,
        exclude_lanes=exclude_lanes, carriers=carriers, exclude_carriers=exclude_carriers, _user=_user,
    )

# ---- /team-projection -------------------------------------------------
@r.get("/team-projection")
async def team_projection(
    request: Request,
    team: Optional[str] = Query(None),
    customer: Optional[str] = Query(None),
    load_type: Optional[str] = Query(None),
    lanes: Optional[List[str]] = Query(None),
    exclude_lanes: Optional[List[str]] = Query(None),
    carriers: Optional[List[str]] = Query(None),
    exclude_carriers: Optional[List[str]] = Query(None),
    _user: dict = Depends(gate),
):
    return await opo.team_projection(
        request=request, team=_sub_team(team), customer=customer, load_type=load_type,
        lanes=lanes, exclude_lanes=exclude_lanes, carriers=carriers, exclude_carriers=exclude_carriers, _user=_user,
    )

# ---- /profit-tm-gauge -------------------------------------------------
@r.get("/profit-tm-gauge")
async def profit_tm_gauge(
    request: Request,
    team: Optional[str] = Query(None),
    customer: Optional[str] = Query(None),
    load_type: Optional[str] = Query(None),
    lanes: Optional[List[str]] = Query(None),
    exclude_lanes: Optional[List[str]] = Query(None),
    carriers: Optional[List[str]] = Query(None),
    exclude_carriers: Optional[List[str]] = Query(None),
    _user: dict = Depends(gate),
):
    return await opo.profit_tm_gauge(
        request=request, team=_sub_team(team), customer=customer, load_type=load_type,
        lanes=lanes, exclude_lanes=exclude_lanes, carriers=carriers, exclude_carriers=exclude_carriers, _user=_user,
    )

# ---- /actuals ---------------------------------------------------------
@r.get("/actuals")
async def actuals(
    request: Request,
    team: Optional[str] = Query(None),
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
        team=_sub_team(team), customer=customer, load_type=load_type, lanes=lanes,
        exclude_lanes=exclude_lanes, carriers=carriers, exclude_carriers=exclude_carriers, sort=sort, limit=limit,
        losses_only=losses_only, unbilled_only=unbilled_only, _user=_user,
    )

# ---- /actuals-by-lane -------------------------------------------------
@r.get("/actuals-by-lane")
async def actuals_by_lane(
    request: Request,
    team: Optional[str] = Query(None),
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
        team=_sub_team(team), customer=customer, load_type=load_type, lanes=lanes,
        exclude_lanes=exclude_lanes, carriers=carriers, exclude_carriers=exclude_carriers, sort=sort, limit=limit,
        losses_only=losses_only, unbilled_only=unbilled_only, _user=_user,
    )

# ---- /service ---------------------------------------------------------
@r.get("/service")
async def service(
    request: Request,
    team: Optional[str] = Query(None),
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
        request=request, team=_sub_team(team), customer=customer, load_type=load_type,
        lanes=lanes, exclude_lanes=exclude_lanes, carriers=carriers, exclude_carriers=exclude_carriers, grain=grain, _user=_user,
    )

# ---- /by-order --------------------------------------------------------
@r.get("/by-order")
async def by_order(
    request: Request,
    team: Optional[str] = Query(None),
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
        team=_sub_team(team), customer=customer, load_type=load_type, lanes=lanes,
        exclude_lanes=exclude_lanes, carriers=carriers, exclude_carriers=exclude_carriers, sort=sort, limit=limit,
        losses_only=losses_only, unbilled_only=unbilled_only, _user=_user,
    )

# ---- /pending-to-cover (Bruno PDF 2026-07-15 R16) --------------------
@r.get("/pending-to-cover")
async def pending_to_cover(
    request: Request,
    team: Optional[str] = Query(None),
    customer: Optional[str] = Query(None),
    lanes: Optional[List[str]] = Query(None),
    exclude_lanes: Optional[List[str]] = Query(None),
    limit: int = Query(500, ge=1, le=2000),
    _user: dict = Depends(gate),
):
    return await opo.pending_to_cover(
        request=request, team=_sub_team(team), customer=customer, lanes=lanes,
        exclude_lanes=exclude_lanes, limit=limit, _user=_user,
    )

# ---- /cover (Bruno PDF 2026-07-20 R1) --------------------------------
@r.get("/cover")
async def cover(
    request: Request,
    team: Optional[str] = Query(None),
    customer: Optional[str] = Query(None),
    lanes: Optional[List[str]] = Query(None),
    exclude_lanes: Optional[List[str]] = Query(None),
    limit: int = Query(500, ge=1, le=2000),
    _user: dict = Depends(gate),
):
    return await opo.cover(
        request=request, team=_sub_team(team), customer=customer, lanes=lanes,
        exclude_lanes=exclude_lanes, limit=limit, _user=_user,
    )

# ---- /hold (Bruno PDF 2026-08-19 R1) ---------------------------------
# MANDATORY, not optional: all six portals render the SAME
# `OpsPortalOverviewContent`, so a missing delegator here 404s the Hold
# board on every CORP team page while the main portal looks fine.
# `team` is PINNED from the closure and EVERY other param is forwarded —
# a dropped param silently widens a scope-locked clone (§40).
@r.get("/hold")
async def hold(
    request: Request,
    team: Optional[str] = Query(None),
    customer: Optional[str] = Query(None),
    lanes: Optional[List[str]] = Query(None),
    exclude_lanes: Optional[List[str]] = Query(None),
    # Must track hold.py's default — see the CORP factory.
    sort: str = Query("date_asc"),
    limit: int = Query(500, ge=1, le=2000),
    _user: dict = Depends(gate),
):
    return await opo.hold_board(
        request=request, team=_sub_team(team), customer=customer, lanes=lanes,
        exclude_lanes=exclude_lanes, sort=sort, limit=limit, _user=_user,
    )

# ---- /cover-forecast (Bruno PDF 2026-07-30 R4) -----------------------
@r.get("/cover-forecast")
async def cover_forecast(
    request: Request,
    team: Optional[str] = Query(None),
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
        request=request, team=_sub_team(team), customer=customer, load_type=load_type,
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
    team: Optional[str] = Query(None),
    customer: Optional[str] = Query(None),
    load_type: Optional[str] = Query(None),
    lanes: Optional[List[str]] = Query(None),
    exclude_lanes: Optional[List[str]] = Query(None),
    carriers: Optional[List[str]] = Query(None),
    exclude_carriers: Optional[List[str]] = Query(None),
    _user: dict = Depends(gate),
):
    return await opo.team_weekly_performance(
        request=request, team=_sub_team(team), customer=customer, load_type=load_type,
        lanes=lanes, exclude_lanes=exclude_lanes, carriers=carriers, exclude_carriers=exclude_carriers, _user=_user,
    )

# ---- /team-performance-by-team ----------------------------------------
@r.get("/team-performance-by-team")
async def team_performance_by_team(
    request: Request,
    team: Optional[str] = Query(None),
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
        team=_sub_team(team), customer=customer, load_type=load_type, lanes=lanes,
        exclude_lanes=exclude_lanes, carriers=carriers, exclude_carriers=exclude_carriers, _user=_user,
    )

# ---- /service-incident-by-customer ------------------------------------
@r.get("/service-incident-by-customer")
async def service_incident_by_customer(
    request: Request,
    team: Optional[str] = Query(None),
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
        team=_sub_team(team), customer=customer, load_type=load_type, lanes=lanes,
        exclude_lanes=exclude_lanes, carriers=carriers, exclude_carriers=exclude_carriers, stop_type=stop_type, _user=_user,
    )

# ---- /service-by-carrier (Bruno PDF 2026-07-15 R8) --------------------
@r.get("/service-by-carrier")
async def service_by_carrier(
    request: Request,
    team: Optional[str] = Query(None),
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
        team=_sub_team(team), customer=customer, load_type=load_type, lanes=lanes,
        exclude_lanes=exclude_lanes, carriers=carriers,
        exclude_carriers=exclude_carriers, limit=limit, _user=_user,
    )

# ---- /margin-distribution ---------------------------------------------
@r.get("/margin-distribution")
async def margin_distribution(
    request: Request,
    team: Optional[str] = Query(None),
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
        team=_sub_team(team), customer=customer, load_type=load_type, lanes=lanes,
        exclude_lanes=exclude_lanes, carriers=carriers, exclude_carriers=exclude_carriers, _user=_user,
    )

# ---- Bruno (PDF 2026-07-13): "Week" toggle on Projection ---------------
# The Variance half of that toggle is NOT here: PDF 2026-08-21 Request 6
# deletes the Team Budget Monthly Variance panel from this portal entirely,
# and `daily_production_budget_report` holds 0 of DFW's 15 customers anyway.
# The cross-team "Team" breakdowns are likewise absent — see the module
# docstring.
@r.get("/team-projection-weekly")
async def team_projection_weekly(
    request: Request,
    team: Optional[str] = Query(None),
    customer: Optional[str] = Query(None),
    load_type: Optional[str] = Query(None),
    lanes: Optional[List[str]] = Query(None),
    exclude_lanes: Optional[List[str]] = Query(None),
    carriers: Optional[List[str]] = Query(None),
    exclude_carriers: Optional[List[str]] = Query(None),
    _user: dict = Depends(gate),
):
    return await opo.team_projection_weekly(
        request=request, team=_sub_team(team), customer=customer, load_type=load_type,
        lanes=lanes, exclude_lanes=exclude_lanes, carriers=carriers, exclude_carriers=exclude_carriers, _user=_user,
    )
