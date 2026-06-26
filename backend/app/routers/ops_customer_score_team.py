"""Per-team variants of OPs Customer Score — one report per CORP team.

Bruno 2026-06-26: duplicate the entire ``ops-customer-score`` report for each
CORP team so a TEAM1 KAM can only ever see TEAM1 customer-score data — pinned
KPIs, overviews, detail tables, fault rows, everything — even if they craft a
custom URL with ``?division=DFW`` or ``?teams=TEAM2``.

Endpoints (per team):
    /api/custom/ops-customer-score-t1/* … /ops-customer-score-t4/*

Role gate (per report):
    require_report_access("corp-tN-customer-score") -- DB-backed per-report
    list, admin always bypasses, role list editable via /admin/reports.

Implementation mirrors ``ops_portal_overview_team.py``: each shim calls the
corresponding ``ops_customer_score`` endpoint function directly (Python-level)
with ``division="CORP"`` + ``teams=TEAMn`` + ``sub_teams=None`` locked
server-side. Every param is forwarded explicitly — a direct Python call never
applies FastAPI ``Query()`` defaults, so an omitted param would arrive as a
FieldInfo and 500 (SPEC-CODE-RULES §40).

NOTE: the parent ``ops-customer-score`` is also consumed by KAM Performance DFW
(via division=DFW); this module only ADDS the locked CORP-team variants and
never touches the parent router.
"""

from __future__ import annotations

from datetime import date
from typing import Optional

from fastapi import APIRouter, Depends, Query, Request

import app.routers.ops_customer_score as ocs
from app.routers.deps import require_report_access


# Single source of truth for the per-team config: (team_id, url-slug, TagRole).
# Adding TEAM5 later means adding one line here — everything else is
# parametrized. Bruno only asked for TEAM1–TEAM4.
TEAM_CONFIGS: tuple[tuple[str, str, str], ...] = (
    ("TEAM1", "t1", "CORP-T1"),
    ("TEAM2", "t2", "CORP-T2"),
    ("TEAM3", "t3", "CORP-T3"),
    ("TEAM4", "t4", "CORP-T4"),
)


def _make_team_router(team: str, slug: str, role: str) -> APIRouter:
    """Build one APIRouter for a single CORP team.

    All data endpoints delegate to the matching ``ops_customer_score`` function
    with ``division="CORP"`` + ``teams=team`` locked in. The role gate is
    DB-backed via ``require_report_access("corp-tN-customer-score")`` so admins
    can edit the role list via ``/admin/reports`` without redeploying.
    """
    report_key = f"corp-{slug}-customer-score"
    gate = require_report_access(report_key)
    r = APIRouter(
        tags=[f"ops-customer-score-{slug}"],
        prefix=f"/custom/ops-customer-score-{slug}",
    )

    # ---- /filters — customers + carriers scoped to THIS team only ----------
    @r.get("/filters")
    async def filters(
        request: Request,
        companies: Optional[str] = Query(None),
        customer: Optional[str] = Query(None),
        carrier: Optional[str] = Query(None),
        _user: dict = Depends(gate),
    ):
        return await ocs.filters(
            request=request,
            division="CORP",
            teams=team,
            companies=companies,
            sub_teams=None,
            customer=customer,
            carrier=carrier,
            _user=_user,
        )

    # ---- Pinned panels ----------------------------------------------------
    @r.get("/pu/pinned")
    async def pu_pinned(
        request: Request,
        companies: Optional[str] = Query(None),
        customer: Optional[str] = Query(None),
        carrier: Optional[str] = Query(None),
        _user: dict = Depends(gate),
    ):
        return await ocs.pu_pinned(
            request=request,
            division="CORP",
            teams=team,
            companies=companies,
            sub_teams=None,
            customer=customer,
            carrier=carrier,
            _user=_user,
        )

    @r.get("/del/pinned")
    async def del_pinned(
        request: Request,
        companies: Optional[str] = Query(None),
        customer: Optional[str] = Query(None),
        carrier: Optional[str] = Query(None),
        _user: dict = Depends(gate),
    ):
        return await ocs.del_pinned(
            request=request,
            division="CORP",
            teams=team,
            companies=companies,
            sub_teams=None,
            customer=customer,
            carrier=carrier,
            _user=_user,
        )

    # ---- Overview ---------------------------------------------------------
    @r.get("/pu/overview")
    async def pu_overview(
        request: Request,
        range: Optional[str] = Query("mtd"),
        start_date: Optional[date] = Query(None),
        end_date: Optional[date] = Query(None),
        companies: Optional[str] = Query(None),
        customer: Optional[str] = Query(None),
        carrier: Optional[str] = Query(None),
        _user: dict = Depends(gate),
    ):
        return await ocs.pu_overview(
            request=request,
            range=range,
            start_date=start_date,
            end_date=end_date,
            division="CORP",
            teams=team,
            companies=companies,
            sub_teams=None,
            customer=customer,
            carrier=carrier,
            _user=_user,
        )

    @r.get("/del/overview")
    async def del_overview(
        request: Request,
        range: Optional[str] = Query("mtd"),
        start_date: Optional[date] = Query(None),
        end_date: Optional[date] = Query(None),
        companies: Optional[str] = Query(None),
        customer: Optional[str] = Query(None),
        carrier: Optional[str] = Query(None),
        _user: dict = Depends(gate),
    ):
        return await ocs.del_overview(
            request=request,
            range=range,
            start_date=start_date,
            end_date=end_date,
            division="CORP",
            teams=team,
            companies=companies,
            sub_teams=None,
            customer=customer,
            carrier=carrier,
            _user=_user,
        )

    # ---- Detail -----------------------------------------------------------
    @r.get("/pu/detail")
    async def pu_detail(
        request: Request,
        range: Optional[str] = Query("mtd"),
        start_date: Optional[date] = Query(None),
        end_date: Optional[date] = Query(None),
        companies: Optional[str] = Query(None),
        customer: Optional[str] = Query(None),
        carrier: Optional[str] = Query(None),
        _user: dict = Depends(gate),
    ):
        return await ocs.pu_detail(
            request=request,
            range=range,
            start_date=start_date,
            end_date=end_date,
            division="CORP",
            teams=team,
            companies=companies,
            sub_teams=None,
            customer=customer,
            carrier=carrier,
            _user=_user,
        )

    @r.get("/del/detail")
    async def del_detail(
        request: Request,
        range: Optional[str] = Query("mtd"),
        start_date: Optional[date] = Query(None),
        end_date: Optional[date] = Query(None),
        companies: Optional[str] = Query(None),
        customer: Optional[str] = Query(None),
        carrier: Optional[str] = Query(None),
        _user: dict = Depends(gate),
    ):
        return await ocs.del_detail(
            request=request,
            range=range,
            start_date=start_date,
            end_date=end_date,
            division="CORP",
            teams=team,
            companies=companies,
            sub_teams=None,
            customer=customer,
            carrier=carrier,
            _user=_user,
        )

    # ---- Fault rows (paginated) -------------------------------------------
    @r.get("/pu/our-fault")
    async def pu_our_fault(
        request: Request,
        range: Optional[str] = Query("mtd"),
        start_date: Optional[date] = Query(None),
        end_date: Optional[date] = Query(None),
        companies: Optional[str] = Query(None),
        customer: Optional[str] = Query(None),
        carrier: Optional[str] = Query(None),
        page: int = Query(1, ge=1),
        limit: int = Query(200, ge=1, le=500),
        _user: dict = Depends(gate),
    ):
        return await ocs.pu_our_fault(
            request=request,
            range=range,
            start_date=start_date,
            end_date=end_date,
            division="CORP",
            teams=team,
            companies=companies,
            sub_teams=None,
            customer=customer,
            carrier=carrier,
            page=page,
            limit=limit,
            _user=_user,
        )

    @r.get("/pu/not-our-fault")
    async def pu_not_our_fault(
        request: Request,
        range: Optional[str] = Query("mtd"),
        start_date: Optional[date] = Query(None),
        end_date: Optional[date] = Query(None),
        companies: Optional[str] = Query(None),
        customer: Optional[str] = Query(None),
        carrier: Optional[str] = Query(None),
        page: int = Query(1, ge=1),
        limit: int = Query(200, ge=1, le=500),
        _user: dict = Depends(gate),
    ):
        return await ocs.pu_not_our_fault(
            request=request,
            range=range,
            start_date=start_date,
            end_date=end_date,
            division="CORP",
            teams=team,
            companies=companies,
            sub_teams=None,
            customer=customer,
            carrier=carrier,
            page=page,
            limit=limit,
            _user=_user,
        )

    @r.get("/del/our-fault")
    async def del_our_fault(
        request: Request,
        range: Optional[str] = Query("mtd"),
        start_date: Optional[date] = Query(None),
        end_date: Optional[date] = Query(None),
        companies: Optional[str] = Query(None),
        customer: Optional[str] = Query(None),
        carrier: Optional[str] = Query(None),
        page: int = Query(1, ge=1),
        limit: int = Query(200, ge=1, le=500),
        _user: dict = Depends(gate),
    ):
        return await ocs.del_our_fault(
            request=request,
            range=range,
            start_date=start_date,
            end_date=end_date,
            division="CORP",
            teams=team,
            companies=companies,
            sub_teams=None,
            customer=customer,
            carrier=carrier,
            page=page,
            limit=limit,
            _user=_user,
        )

    @r.get("/del/not-our-fault")
    async def del_not_our_fault(
        request: Request,
        range: Optional[str] = Query("mtd"),
        start_date: Optional[date] = Query(None),
        end_date: Optional[date] = Query(None),
        companies: Optional[str] = Query(None),
        customer: Optional[str] = Query(None),
        carrier: Optional[str] = Query(None),
        page: int = Query(1, ge=1),
        limit: int = Query(200, ge=1, le=500),
        _user: dict = Depends(gate),
    ):
        return await ocs.del_not_our_fault(
            request=request,
            range=range,
            start_date=start_date,
            end_date=end_date,
            division="CORP",
            teams=team,
            companies=companies,
            sub_teams=None,
            customer=customer,
            carrier=carrier,
            page=page,
            limit=limit,
            _user=_user,
        )

    # ---- /freshness — global (no team/division params) --------------------
    @r.get("/freshness")
    async def freshness(request: Request, _user: dict = Depends(gate)):
        return await ocs.freshness(request=request, _user=_user)

    return r


# Build all 4 routers at import time — include them in main.py.
team_routers: tuple = tuple(
    _make_team_router(t, s, role) for t, s, role in TEAM_CONFIGS
)
