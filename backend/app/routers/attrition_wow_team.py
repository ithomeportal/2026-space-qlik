"""Per-team variants of Attrition WoW — one report per CORP team.

Bruno 2026-08-14 (PDF "space -- Attrition WoW Updates" Request 1): duplicate the
``attrition-wow`` report for each CORP team so a TEAM1 KAM only ever sees TEAM1
customers, lanes and losses — even if they hand-craft ``?teams=TEAM2``.

Endpoints (per team):
    /api/custom/attrition-wow-t1/* … /attrition-wow-t4/*

Role gate (per report):
    require_report_access("corp-tN-attrition-wow")  -- DB-backed per-report list,
    admin always bypasses, editable via /admin/reports.

Implementation mirrors ``ops_portal_overview_team.py`` / ``xray_dfw_team.py``:
each shim calls the corresponding ``attrition_wow`` endpoint function directly
(Python-level) with ``teams="TEAMn"`` locked server-side. Every param is
forwarded explicitly — a direct Python call never applies FastAPI ``Query()``
defaults, so an omitted param would arrive as a ``FieldInfo`` and 500
(SPEC-CODE-RULES §40).

Two parent concepts are deliberately NOT exposed here:

* ``view=ruan`` — the RUAN pseudo-team forces ``team_id='TEAM-DFW'`` server-side,
  which would punch straight through the CORP team lock. Always passed as None.
* ``sub_team`` — the TM1..TM4 breakdown only exists inside TEAM-DFW, so it is
  meaningless on a CORP team and is likewise pinned to None.

The parent's own gate is dual-key (``"attrition-wow", "ceo-executive"``) on
/summary and /pivot because the CEO Executive tab borrows them. The clones gate
on their OWN key only — inheriting the parent's keys would hand every
attrition-wow viewer a per-team report they were never granted.
"""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, Query, Request, Response

from app.datalake import pad_variants
from app.routers import attrition_wow as aw
from app.routers.deps import get_datalake_gold_pool, require_report_access


# Single source of truth for the per-team config: (team_id, url-slug, TagRole).
# Adding TEAM5 later means adding one line here — everything else is
# parametrized. Bruno's PDF only asked for TEAM1–TEAM4.
TEAM_CONFIGS: tuple[tuple[str, str, str], ...] = (
    ("TEAM1", "t1", "CORP KAM1"),
    ("TEAM2", "t2", "CORP KAM2"),
    ("TEAM3", "t3", "CORP KAM3"),
    ("TEAM4", "t4", "CORP KAM4"),
)


def _make_team_router(team: str, slug: str, role: str) -> APIRouter:
    """Build one APIRouter for a single CORP team.

    ``team`` is baked into every endpoint as the ``teams`` argument, so the
    client has no way to widen the scope. ``role`` is documentation only — the
    live grant lives in ``role_report_access`` and is edited via /admin/reports.
    """
    report_key = f"corp-{slug}-attrition-wow"
    gate = require_report_access(report_key)
    r = APIRouter(
        tags=[f"attrition-wow-{slug}"],
        prefix=f"/custom/attrition-wow-{slug}",
    )

    # ---- /filters — customers + contract types for THIS team only ----------
    @r.get("/filters")
    async def filters(
        request: Request,
        response: Response,
        _user: dict = Depends(gate),
    ):
        """Single-team version of ``aw.filters``.

        The parent hardcodes ``ALL_TEAMS`` and takes no ``teams`` param, so
        delegating would leak every other team's customer names into this
        report's dropdown — a real isolation leak, not a cosmetic one.
        """
        pool = get_datalake_gold_pool(request)
        response.headers["Cache-Control"] = aw.CACHE_HEADER

        rows = await pool.fetch(
            """
            SELECT
              DISTINCT TRIM(customer_name) AS entity,
              UPPER(TRIM(COALESCE(contract_type_descr,''))) AS contract_type
            FROM public.mcleod_gld_budget_report_v4
            WHERE team_id    = ANY($1)
              AND company_id = ANY($2)
              AND status     = ANY($3)
              AND UPPER(COALESCE(customer_name,'')) NOT LIKE '%UNILINK%'
              AND UPPER(COALESCE(customer_name,'')) NOT LIKE '%OILTEX%'
              AND customer_name IS NOT NULL
              AND TRIM(customer_name) <> ''
              AND origin_actual_departure >= $4
            """,
            pad_variants((team,), width=8),
            pad_variants(aw.COMPANIES, width=4),
            pad_variants(aw.OPEN_STATUSES, width=1),
            aw.YEAR_START,
        )
        customers = sorted({x["entity"] for x in rows if x["entity"]})
        contracts = sorted({x["contract_type"] for x in rows if x["contract_type"]})

        return {
            "success": True,
            "data": {
                "teams": [team],
                "customers": customers,
                "contract_types": contracts,
            },
        }

    # ---- /freshness — last load date + row count for THIS team only --------
    @r.get("/freshness")
    async def freshness(
        request: Request,
        response: Response,
        _user: dict = Depends(gate),
    ):
        """Single-team version of ``aw.freshness``.

        Delegating would report the cross-team ``rows_in_scope`` in this
        report's "Data through" tooltip — a company-wide row count on a
        team-locked page, which both leaks scale and misleads. The last-load
        date is likewise the team's own, so the pill answers "is MY data
        fresh", not "is anyone's".
        """
        pool = get_datalake_gold_pool(request)
        response.headers["Cache-Control"] = "public, max-age=120"

        row = await pool.fetchrow(
            """
            SELECT
              MAX(origin_actual_departure)::date AS last_load_date,
              COUNT(*) AS rows_in_scope
            FROM public.mcleod_gld_budget_report_v4
            WHERE team_id    = ANY($1)
              AND company_id = ANY($2)
              AND status     = ANY($3)
              AND UPPER(COALESCE(customer_name,'')) NOT LIKE '%UNILINK%'
              AND UPPER(COALESCE(customer_name,'')) NOT LIKE '%OILTEX%'
              AND origin_actual_departure >= $4
            """,
            pad_variants((team,), width=8),
            pad_variants(aw.COMPANIES, width=4),
            pad_variants(aw.OPEN_STATUSES, width=1),
            aw.YEAR_START,
        )
        lw_mon, lw_sun = aw._last_completed_week()
        return {
            "success": True,
            "data": {
                "last_load_date": (
                    row["last_load_date"].isoformat()
                    if row and row["last_load_date"]
                    else None
                ),
                "rows_in_scope": int(row["rows_in_scope"] or 0) if row else 0,
                "last_completed_week": {
                    "start": lw_mon.isoformat(),
                    "end": lw_sun.isoformat(),
                },
            },
        }

    # ---- /summary ---------------------------------------------------------
    @r.get("/summary")
    async def summary(
        request: Request,
        response: Response,
        customer: Optional[str] = Query(None),
        contract: Optional[str] = Query(None),
        lane: Optional[str] = Query(None),
        _user: dict = Depends(gate),
    ):
        return await aw.summary(
            request=request,
            response=response,
            teams=team,
            customer=customer,
            contract=contract,
            lane=lane,
            view=None,
            sub_team=None,
            _user=_user,
        )

    # ---- /weekly-trends ---------------------------------------------------
    @r.get("/weekly-trends")
    async def weekly_trends(
        request: Request,
        response: Response,
        weeks: int = Query(15, ge=4, le=24),
        customer: Optional[str] = Query(None),
        contract: Optional[str] = Query(None),
        lane: Optional[str] = Query(None),
        _user: dict = Depends(gate),
    ):
        return await aw.weekly_trends(
            request=request,
            response=response,
            weeks=weeks,
            teams=team,
            customer=customer,
            contract=contract,
            lane=lane,
            view=None,
            sub_team=None,
            _user=_user,
        )

    # ---- /customer-attrition ---------------------------------------------
    @r.get("/customer-attrition")
    async def customer_attrition(
        request: Request,
        response: Response,
        weeks: int = Query(15, ge=4, le=24),
        customer: Optional[str] = Query(None),
        contract: Optional[str] = Query(None),
        lane: Optional[str] = Query(None),
        _user: dict = Depends(gate),
    ):
        return await aw.customer_attrition(
            request=request,
            response=response,
            weeks=weeks,
            teams=team,
            customer=customer,
            contract=contract,
            lane=lane,
            view=None,
            sub_team=None,
            _user=_user,
        )

    # ---- /pivot -----------------------------------------------------------
    @r.get("/pivot")
    async def pivot(
        request: Request,
        response: Response,
        dim: str = Query("customer", regex="^(customer|team|customer_lane)$"),
        metric: str = Query("loads", regex="^(loads|revenue|profit|margin)$"),
        weeks: int = Query(12, ge=4, le=24),
        customer: Optional[str] = Query(None),
        contract: Optional[str] = Query(None),
        lane: Optional[str] = Query(None),
        _user: dict = Depends(gate),
    ):
        return await aw.pivot(
            request=request,
            response=response,
            dim=dim,
            metric=metric,
            weeks=weeks,
            teams=team,
            customer=customer,
            contract=contract,
            lane=lane,
            view=None,
            sub_team=None,
            _user=_user,
        )

    # ---- /reactive-summary (no `lane`, no `sub_team` upstream) ------------
    @r.get("/reactive-summary")
    async def reactive_summary(
        request: Request,
        response: Response,
        customer: Optional[str] = Query(None),
        contract: Optional[str] = Query(None),
        _user: dict = Depends(gate),
    ):
        return await aw.reactive_summary(
            request=request,
            response=response,
            teams=team,
            customer=customer,
            contract=contract,
            view=None,
            _user=_user,
        )

    # ---- /lane-summary ----------------------------------------------------
    @r.get("/lane-summary")
    async def lane_summary(
        request: Request,
        response: Response,
        customer: Optional[str] = Query(None),
        contract: Optional[str] = Query(None),
        _user: dict = Depends(gate),
    ):
        return await aw.lane_summary(
            request=request,
            response=response,
            teams=team,
            customer=customer,
            contract=contract,
            view=None,
            _user=_user,
        )

    # ---- /wow-variation ---------------------------------------------------
    @r.get("/wow-variation")
    async def wow_variation(
        request: Request,
        response: Response,
        customer: Optional[str] = Query(None),
        contract: Optional[str] = Query(None),
        _user: dict = Depends(gate),
    ):
        return await aw.wow_variation(
            request=request,
            response=response,
            teams=team,
            customer=customer,
            contract=contract,
            view=None,
            _user=_user,
        )

    # ---- /losses ----------------------------------------------------------
    @r.get("/losses")
    async def losses(
        request: Request,
        response: Response,
        customer: Optional[str] = Query(None),
        contract: Optional[str] = Query(None),
        lane: Optional[str] = Query(None),
        range: Optional[str] = Query("ytd"),
        date_from: Optional[str] = Query(None, alias="from"),
        date_to: Optional[str] = Query(None, alias="to"),
        _user: dict = Depends(gate),
    ):
        return await aw.losses(
            request=request,
            response=response,
            teams=team,
            customer=customer,
            contract=contract,
            lane=lane,
            view=None,
            range=range,
            date_from=date_from,
            date_to=date_to,
            _user=_user,
        )

    return r


team_routers: tuple[APIRouter, ...] = tuple(
    _make_team_router(team, slug, role) for team, slug, role in TEAM_CONFIGS
)
