"""Per-team variants of OPs Direct Compare — one report per CORP team.

Bruno 2026-06-26: duplicate the entire ``ops-direct-compare`` side-by-side
comparison report for each CORP team so a TEAM1 KAM can only ever see TEAM1
data in both panels (and the diff tables / trend / orders), even if they craft
a custom URL with ``?p1_division=DFW`` or ``?p2_teams=TEAM2``.

Endpoints (per team):
    /api/custom/ops-direct-compare-t1/* … /ops-direct-compare-t4/*

Role gate (per report):
    require_report_access("corp-tN-direct-compare")  -- DB-backed per-report
    list, admin always bypasses, role list editable via /admin/reports.

Implementation mirrors ``ops_portal_overview_team.py``: each shim calls the
corresponding ``ops_direct_compare`` endpoint function directly (Python-level)
with ``division="CORP"`` + ``teams=team`` locked server-side. Every param is
forwarded explicitly — a direct Python call never applies FastAPI ``Query()``
defaults, so an omitted param would arrive as a FieldInfo and 500
(SPEC-CODE-RULES §40).

The /filters endpoint is custom (returns only this CORP team), and /trend-12m
is a team-scoped inline query (the parent /trend-12m is GLOBAL + date-cached).
"""

from __future__ import annotations

from datetime import date
from typing import Optional

from fastapi import APIRouter, Depends, Query, Request

import app.routers.ops_direct_compare as odc
from app.clock import cst_today
from app.routers.deps import get_datalake_gold_pool, require_report_access


# Single source of truth for the per-team config: (team_id, url-slug, TagRole).
# Bruno's PDF only asked for TEAM1–TEAM4.
TEAM_CONFIGS: tuple[tuple[str, str, str], ...] = (
    ("TEAM1", "t1", "CORP-T1"),
    ("TEAM2", "t2", "CORP-T2"),
    ("TEAM3", "t3", "CORP-T3"),
    ("TEAM4", "t4", "CORP-T4"),
)


def _make_team_router(team: str, slug: str, role: str) -> APIRouter:
    """Build one APIRouter for a single CORP team.

    Every endpoint delegates to the matching ``ops_direct_compare`` function
    with ``division="CORP"`` and ``teams=team`` locked in. The role gate is
    DB-backed via ``require_report_access("corp-tN-direct-compare")`` so admins
    can edit the role list via ``/admin/reports`` without redeploying.
    """
    report_key = f"corp-{slug}-direct-compare"
    gate = require_report_access(report_key)
    r = APIRouter(
        tags=[f"ops-direct-compare-{slug}"],
        prefix=f"/custom/ops-direct-compare-{slug}",
    )

    # ---- /filters — locked to THIS CORP team only -------------------------
    @r.get("/filters")
    async def filters(request: Request, _user: dict = Depends(gate)):
        return {
            "success": True,
            "data": {
                "divisions": ["CORP"],
                "teams": [team],
                "corp_teams": [team],
                "dfw_team": odc.DFW_TEAM,
                "dfw_sub_teams": [],
                "companies": list(odc.ALL_COMPANIES),
                "year_start": odc.YEAR_START.isoformat(),
                "year_end": odc.YEAR_END.isoformat(),
                "locked_team": team,
            },
        }

    # ---- /panel-summary ---------------------------------------------------
    @r.get("/panel-summary")
    async def panel_summary(
        request: Request,
        range: Optional[str] = Query("mtd"),
        start_date: Optional[date] = Query(None),
        end_date: Optional[date] = Query(None),
        division: Optional[str] = Query(None),
        teams: Optional[str] = Query(None),
        sub_teams: Optional[str] = Query(None),
        _user: dict = Depends(gate),
    ):
        return await odc.panel_summary(
            request=request, range=range, start_date=start_date, end_date=end_date,
            division="CORP", teams=team, sub_teams=None, _user=_user,
        )

    # ---- /concentration ---------------------------------------------------
    @r.get("/concentration")
    async def concentration(
        request: Request,
        range: Optional[str] = Query("mtd"),
        start_date: Optional[date] = Query(None),
        end_date: Optional[date] = Query(None),
        division: Optional[str] = Query(None),
        teams: Optional[str] = Query(None),
        sub_teams: Optional[str] = Query(None),
        top: int = Query(5, ge=3, le=20),
        _user: dict = Depends(gate),
    ):
        return await odc.concentration(
            request=request, range=range, start_date=start_date, end_date=end_date,
            division="CORP", teams=team, sub_teams=None, top=top, _user=_user,
        )

    # ---- /by-customer -----------------------------------------------------
    @r.get("/by-customer")
    async def by_customer(
        request: Request,
        range: Optional[str] = Query("mtd"),
        start_date: Optional[date] = Query(None),
        end_date: Optional[date] = Query(None),
        division: Optional[str] = Query(None),
        teams: Optional[str] = Query(None),
        sub_teams: Optional[str] = Query(None),
        sort: str = Query("profit_desc"),
        page: int = Query(1, ge=1),
        limit: int = Query(200, ge=1, le=1000),
        _user: dict = Depends(gate),
    ):
        return await odc.by_customer(
            request=request, range=range, start_date=start_date, end_date=end_date,
            division="CORP", teams=team, sub_teams=None, sort=sort, page=page,
            limit=limit, _user=_user,
        )

    # ---- /by-customer-diff — lock BOTH panels to this team ----------------
    @r.get("/by-customer-diff")
    async def by_customer_diff(
        request: Request,
        p1_range: Optional[str] = Query("mtd"),
        p1_start_date: Optional[date] = Query(None),
        p1_end_date: Optional[date] = Query(None),
        p1_division: Optional[str] = Query(None),
        p1_teams: Optional[str] = Query(None),
        p1_sub_teams: Optional[str] = Query(None),
        p2_range: Optional[str] = Query("last_month"),
        p2_start_date: Optional[date] = Query(None),
        p2_end_date: Optional[date] = Query(None),
        p2_division: Optional[str] = Query(None),
        p2_teams: Optional[str] = Query(None),
        p2_sub_teams: Optional[str] = Query(None),
        sort: str = Query("p2_profit_desc"),
        page: int = Query(1, ge=1),
        limit: int = Query(200, ge=1, le=1000),
        _user: dict = Depends(gate),
    ):
        return await odc.by_customer_diff(
            request=request,
            p1_range=p1_range, p1_start_date=p1_start_date, p1_end_date=p1_end_date,
            p1_division="CORP", p1_teams=team, p1_sub_teams=None,
            p2_range=p2_range, p2_start_date=p2_start_date, p2_end_date=p2_end_date,
            p2_division="CORP", p2_teams=team, p2_sub_teams=None,
            sort=sort, page=page, limit=limit, _user=_user,
        )

    # ---- /by-lane ---------------------------------------------------------
    @r.get("/by-lane")
    async def by_lane(
        request: Request,
        range: Optional[str] = Query("mtd"),
        start_date: Optional[date] = Query(None),
        end_date: Optional[date] = Query(None),
        division: Optional[str] = Query(None),
        teams: Optional[str] = Query(None),
        sub_teams: Optional[str] = Query(None),
        sort: str = Query("profit_desc"),
        page: int = Query(1, ge=1),
        limit: int = Query(200, ge=1, le=1000),
        _user: dict = Depends(gate),
    ):
        return await odc.by_lane(
            request=request, range=range, start_date=start_date, end_date=end_date,
            division="CORP", teams=team, sub_teams=None, sort=sort, page=page,
            limit=limit, _user=_user,
        )

    # ---- /by-lane-diff — lock BOTH panels to this team --------------------
    @r.get("/by-lane-diff")
    async def by_lane_diff(
        request: Request,
        p1_range: Optional[str] = Query("mtd"),
        p1_start_date: Optional[date] = Query(None),
        p1_end_date: Optional[date] = Query(None),
        p1_division: Optional[str] = Query(None),
        p1_teams: Optional[str] = Query(None),
        p1_sub_teams: Optional[str] = Query(None),
        p2_range: Optional[str] = Query("last_month"),
        p2_start_date: Optional[date] = Query(None),
        p2_end_date: Optional[date] = Query(None),
        p2_division: Optional[str] = Query(None),
        p2_teams: Optional[str] = Query(None),
        p2_sub_teams: Optional[str] = Query(None),
        sort: str = Query("p2_profit_desc"),
        page: int = Query(1, ge=1),
        limit: int = Query(200, ge=1, le=1000),
        _user: dict = Depends(gate),
    ):
        return await odc.by_lane_diff(
            request=request,
            p1_range=p1_range, p1_start_date=p1_start_date, p1_end_date=p1_end_date,
            p1_division="CORP", p1_teams=team, p1_sub_teams=None,
            p2_range=p2_range, p2_start_date=p2_start_date, p2_end_date=p2_end_date,
            p2_division="CORP", p2_teams=team, p2_sub_teams=None,
            sort=sort, page=page, limit=limit, _user=_user,
        )

    # ---- /customer-revenue-margin -----------------------------------------
    @r.get("/customer-revenue-margin")
    async def customer_revenue_margin(
        request: Request,
        range: Optional[str] = Query("mtd"),
        start_date: Optional[date] = Query(None),
        end_date: Optional[date] = Query(None),
        division: Optional[str] = Query(None),
        teams: Optional[str] = Query(None),
        sub_teams: Optional[str] = Query(None),
        top: int = Query(20, ge=5, le=50),
        _user: dict = Depends(gate),
    ):
        return await odc.customer_revenue_margin(
            request=request, range=range, start_date=start_date, end_date=end_date,
            division="CORP", teams=team, sub_teams=None, top=top, _user=_user,
        )

    # ---- /orders-window ---------------------------------------------------
    @r.get("/orders-window")
    async def orders_window(
        request: Request,
        division: Optional[str] = Query(None),
        teams: Optional[str] = Query(None),
        sub_teams: Optional[str] = Query(None),
        sort: str = Query("date_desc"),
        page: int = Query(1, ge=1),
        limit: int = Query(200, ge=1, le=500),
        _user: dict = Depends(gate),
    ):
        return await odc.orders_window(
            request=request, division="CORP", teams=team, sub_teams=None,
            sort=sort, page=page, limit=limit, _user=_user,
        )

    # ---- /trend-12m — team-scoped inline (parent is GLOBAL + date-cached) --
    @r.get("/trend-12m")
    async def trend_12m(request: Request, _user: dict = Depends(gate)):
        pool = get_datalake_gold_pool(request)
        today = cst_today()
        start, end = odc._last_12m_bounds(today)
        params: list = []
        where = odc._scope_where(
            "br4", [team], list(odc.ALL_COMPANIES), None, None, None, None, params,
        )
        params.extend([start, end])
        rows = await pool.fetch(
            f"""
            SELECT
              DATE_TRUNC('month', br4.origin_actual_departure)::date AS bucket,
              COALESCE(SUM(br4.total_charge) FILTER (WHERE br4.total_charge <> 0), 0)::numeric AS revenue,
              COALESCE(SUM(br4.margin_amt), 0)::numeric AS profit
            FROM public.mcleod_gld_budget_report_v4 br4
            WHERE {where}
              AND br4.origin_actual_departure::date BETWEEN ${len(params) - 1} AND ${len(params)}
            GROUP BY DATE_TRUNC('month', br4.origin_actual_departure)::date
            ORDER BY bucket
            """,
            *params,
        )
        out = []
        for row in rows:
            rev = float(row["revenue"] or 0)
            prof = float(row["profit"] or 0)
            out.append({
                "bucket": row["bucket"].isoformat() if row["bucket"] else None,
                "revenue": rev,
                "profit": prof,
                "margin_pct": (prof / rev * 100.0) if rev else None,
            })
        return {"success": True, "data": out, "meta": {"cached": False}}

    # ---- /freshness — no params, global; pass straight through ------------
    @r.get("/freshness")
    async def freshness(request: Request, _user: dict = Depends(gate)):
        return await odc.freshness(request=request, _user=_user)

    return r


# Build all 4 routers at import time — include them in main.py.
team_routers: tuple = tuple(
    _make_team_router(t, s, role) for t, s, role in TEAM_CONFIGS
)
