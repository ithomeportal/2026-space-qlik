"""Per-team variants of OPs Direct Compare — one report per CORP team.

Bruno 2026-06-26: duplicate the entire ``ops-direct-compare`` side-by-side
comparison report for each CORP team so a TEAM1 KAM can only ever see TEAM1
data in both panels (and the compare tables / pivot / trend), even if they craft
a custom URL with ``?p1_division=DFW`` or ``?p2_teams=TEAM2``.

Bruno 2026-10-01 reshaped the parent report: the compare tables are now
/by-customer-diff, /by-lane-diff and the /by-customer-lane-diff pivot, and the
chart is /trend-yoy. /by-customer, /by-lane, /customer-revenue-margin,
/orders-window and /trend-12m are gone from both routers.

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

The /filters endpoint is custom (returns only this CORP team), and /trend-yoy
passes this one team to the parent's shared ``trend_yoy_for_teams``.
"""

from __future__ import annotations

from datetime import date
from typing import Optional

from fastapi import APIRouter, Depends, Query, Request

import app.routers.ops_direct_compare as odc
from app.routers.deps import require_report_access


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
        sort: str = Query(odc.DEFAULT_SORT),
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
        sort: str = Query(odc.DEFAULT_SORT),
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

    # ---- /by-customer-lane-diff — the pivot; lock BOTH panels -------------
    @r.get("/by-customer-lane-diff")
    async def by_customer_lane_diff(
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
        sort: str = Query(odc.DEFAULT_SORT),
        page: int = Query(1, ge=1),
        limit: int = Query(200, ge=1, le=1000),
        _user: dict = Depends(gate),
    ):
        return await odc.by_customer_lane_diff(
            request=request,
            p1_range=p1_range, p1_start_date=p1_start_date, p1_end_date=p1_end_date,
            p1_division="CORP", p1_teams=team, p1_sub_teams=None,
            p2_range=p2_range, p2_start_date=p2_start_date, p2_end_date=p2_end_date,
            p2_division="CORP", p2_teams=team, p2_sub_teams=None,
            sort=sort, page=page, limit=limit, _user=_user,
        )

    # ---- /trend-yoy — this team only (parent is ALL teams) ----------------
    @r.get("/trend-yoy")
    async def trend_yoy(request: Request, _user: dict = Depends(gate)):
        return await odc.trend_yoy_for_teams(request, [team])

    # ---- /freshness — no params, global; pass straight through ------------
    @r.get("/freshness")
    async def freshness(request: Request, _user: dict = Depends(gate)):
        return await odc.freshness(request=request, _user=_user)

    return r


# Build all 4 routers at import time — include them in main.py.
team_routers: tuple = tuple(
    _make_team_router(t, s, role) for t, s, role in TEAM_CONFIGS
)
