"""CEO Executive Portal — Ops Portal Overview across BOTH divisions.

Bruno PDF "BRUNO -- Exec Portal" (2026-09-03).

Endpoints:
    /api/custom/ceo-executive-portal/{division}/*      division ∈ {corp, dfw}

Role gate:
    require_report_access("ceo-executive-portal") — DB-backed per-report list,
    admin always bypasses, role list editable via /admin/reports. Seeded to the
    ``CEO`` TagRole, which on 2026-09-03 is held by Erick Mendoza plus two
    admins — exactly Request 1's "CEO – Erick Mendoza (and Admin users)".

What this is, and what it deliberately is NOT
---------------------------------------------
Request 1 says "duplicate ops-portal-overview"; Requests 2 and 3 add TEAM-DFW
and a user-facing **Division** filter. So this is neither a scope-LOCKED clone
(``ops_portal_overview_team.py``) nor a second DIVISION copy
(``ops_portal_overview_dfw.py``) — it is a **dispatcher** over the two scopes
``_scope.py`` already defines. No third implementation, no third set of SQL: a
CORP view here emits the same statements, to the byte, that
/reports/ops-portal-overview does (§7.1 — the 3rd copy is the factory).

⚠ The division is a PATH SEGMENT, and that is the whole point
-------------------------------------------------------------
``/{division}/actuals``, never ``/actuals?division=…`` with a default.

On 2026-09-02 the DFW Bonus Calculator served the CORPORATE report whole for
weeks (``afff8d6``) because its ``scope`` argument carried a default: a caller
that forgot to pass one got a complete, plausible, entirely wrong report — TM 1
showing 449 loads / $84,193 instead of Team 1's 606 / $228,096. Nothing errored,
because a defaulted scope is not a missing value, it is the OTHER TENANT'S
value (SPEC-CODE-RULES §100).

A path segment cannot default. A request that omits it 404s at the router
before any handler runs; a request that misspells it 422s in ``_pin_scope``.
There is no code path on which this report renders a division nobody asked for.

⚠ Why a client-settable scope is safe HERE and nowhere else
-----------------------------------------------------------
``_scope.scope_of`` documents that the scope is deliberately NOT a query
parameter — a client-settable scope would let a DFW user widen onto CORP data.
That reasoning is about the DFW portal, whose audience is DFW. This report's
audience is the CEO: ``require_report_access`` runs BEFORE the division is
honoured, and anyone who can reach any division here is already entitled to
both. The division selects a view; it does not grant one. The five pinned
per-division portals are untouched and unreachable from here.

⚠ Budget exists for CORP only
-----------------------------
0 of DFW's 15 YTD customers appear in ``daily_production_budget_report`` (66 of
66 for CORP, measured 2026-08-21) — which is why the DFW portal has no budget
panels. Here the four budget routes stay REGISTERED (the path set must not
depend on the division, or one view would 404 a route the other defines) but
raise 404 under ``dfw`` rather than return zeros: a zero is a number and reads
as data (§98).

⚠ Every param is forwarded explicitly — a direct Python call never applies
FastAPI ``Query()`` defaults, so an omitted param arrives as a FieldInfo and
500s (§40). ``tests/test_ceo_executive_portal.py`` asserts mechanically that
each shim's parameter set is a SUPERSET of the CORP endpoint it delegates to,
so a param added upstream cannot be silently dropped here (a dropped param is
not an error, it is a filter that stops applying).
"""

from __future__ import annotations

from datetime import date
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Path, Query, Request

from app.routers import ops_portal_overview as opo
from app.routers import ops_portal_overview_dfw as dfw
from app.routers.deps import require_report_access
from app.routers.ops_portal_overview._scope import (
    DFW_SCOPE,
    DIVISIONS,
    DivisionScope,
    scope_of,
    sub_team_of as _sub_team,
    sub_teams_of as _sub_teams,
)

REPORT_KEY = "ceo-executive-portal"

gate = require_report_access(REPORT_KEY)

# Request 3's two options live in ``_scope.DIVISIONS``, keyed by URL segment.
# CORP is the live ``ops-portal-overview`` scope (TEAM1..TEAM5) and DFW the live
# ``ops-managers-portal-dfw`` one, unchanged — confirmed with Diego 2026-09-03.
#
# ⚠ The PDF writes CORP as TEAM1..TEAM4 and DFW as "TEAM-DFW AND team IN
# (TM1..TM5)". Both were measured before choosing: TEAM5 is 84 loads / $120
# profit YTD (still trading 30-Aug) and the DFW sub-team AND would drop 1 order
# whose ``team`` is blank. Taking the PDF literally would make this report
# disagree with the two reports Request 1 says to DUPLICATE — and that is the
# stronger instruction, so the live scopes win (§95: parity is a DEFINITION,
# and the answer is to ASK rather than to pick).


def _pin_scope(request: Request, division: str = Path(...)) -> None:
    """Stamp the requested division onto the request before any handler runs.

    Router-level, exactly as ``ops_portal_overview_dfw._pin_dfw_scope`` is, so
    it also covers the handlers that then call the shared package directly in
    Python. Request state, never module state — concurrent CORP and DFW
    requests cannot see each other's scope.

    ⚠ An unknown division 422s. It must NOT fall back to CORP: a fallback is
    how a wrong scope becomes a plausible report instead of an error (§100).
    """
    scope = DIVISIONS.get(division.strip().lower())
    if scope is None:
        raise HTTPException(
            status_code=422,
            detail=f"unknown division '{division}' — expected one of {sorted(DIVISIONS)}",
        )
    request.state.opp_scope = scope


def _require_budget(scope: DivisionScope) -> None:
    """404 the budget-only panels on a division that has no budget.

    Not an empty payload: the caller cannot tell "no budget rows this period"
    from "this division is not in the budget table at all", and the second one
    must not render as zeros (§98).
    """
    if not scope.has_budget:
        raise HTTPException(
            status_code=404,
            detail=(
                f"budget panels are not available for division "
                f"'{scope.label}' — it has no rows in daily_production_budget_report"
            ),
        )


r = APIRouter(
    tags=["ceo-executive-portal"],
    prefix="/custom/ceo-executive-portal",
    # Runs before every handler below, including the ones that then call the
    # shared package's functions directly in Python.
    dependencies=[Depends(_pin_scope)],
)


# ---- /filters — delegated; `opo.filters` is already scope-aware ------------
@r.get("/{division}/filters")
async def filters(
    request: Request,
    _user: dict = Depends(gate),
):
    """Teams / customers / lanes / carriers for the requested division.

    Delegated rather than hand-written: unlike the per-team clones (which must
    narrow CORP's customer list to one team) and the DFW portal (written before
    ``opo.filters`` read the scope), ``opo.filters`` already predicates on
    ``scope.base_teams`` and returns ``scope.sub_teams``. Under ``dfw`` it
    returns DFW's 15 customers and TM1..TM5; under ``corp``, CORP's 66 and
    TEAM1..TEAM5. Re-implementing it here would be a second definition of the
    same list (§69).

    ``division`` / ``has_budget`` are added so the page labels itself from the
    server's answer rather than from its own copy of the rule.
    """
    scope = scope_of(request)
    res = await opo.filters(request=request, _user=_user)
    data = dict(res.get("data") or {})
    data["division"] = scope.label
    data["division_key"] = scope.key
    data["has_budget"] = scope.has_budget
    return {**res, "data": data}


# ---- /customer-variance — the definition CHANGES with the division ---------
@r.get("/{division}/customer-variance")
async def customer_variance(
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
    limit: int = Query(50, ge=1, le=200),
    _user: dict = Depends(gate),
):
    """CORP: actual − budget. DFW: last month − this month.

    ⚠ This is the one endpoint where the division changes the MEASUREMENT, not
    just the population — and the two have OPPOSITE sign conventions (positive
    = over budget on CORP, positive = down this month on DFW). It dispatches to
    each division's own implementation rather than reimplementing either, and
    both already stamp ``meta.basis`` so the panel can label what it is showing
    instead of leaving the reader to infer it (§69, §95).

    DFW's version is deliberately not date-windowed — "last month vs this
    month" is a calendar statement — so the page's range params are accepted
    (siblings declare them; FastAPI drops what is not declared) and, for DFW,
    not forwarded. That asymmetry is the DFW panel's documented contract, not
    an omission.
    """
    scope = scope_of(request)
    if scope is DFW_SCOPE:
        return await dfw.customer_variance(
            request=request,
            team=_sub_team(scope, team),
            customer=customer,
            load_type=load_type,
            lanes=lanes,
            exclude_lanes=exclude_lanes,
            carriers=carriers,
            exclude_carriers=exclude_carriers,
            limit=limit,
            _user=_user,
        )
    return await opo.customer_variance(
        request=request,
        range=range,
        start_date=start_date,
        end_date=end_date,
        team=_sub_team(scope, team),
        customer=customer,
        limit=limit,
        _user=_user,
    )


@r.get("/{division}/workdays")
async def workdays(
    request: Request,
    _user: dict = Depends(gate),
):
    return await opo.workdays(
        request=request, _user=_user,
    )

@r.get("/{division}/data-freshness")
async def data_freshness(
    request: Request,
    _user: dict = Depends(gate),
):
    return await opo.data_freshness(
        request=request, _user=_user,
    )

@r.get("/{division}/combo")
async def combo(
    request: Request,
    team: Optional[str] = Query(None),
    customer: Optional[str] = Query(None),
    load_type: Optional[str] = Query(None),
    lanes: Optional[List[str]] = Query(None),
    exclude_lanes: Optional[List[str]] = Query(None),
    carriers: Optional[List[str]] = Query(None),
    exclude_carriers: Optional[List[str]] = Query(None),
    grain: str = Query('month'),
    _user: dict = Depends(gate),
):
    scope = scope_of(request)
    return await opo.combo(
        request=request, team=_sub_team(scope, team), customer=customer,
        load_type=load_type, lanes=lanes, exclude_lanes=exclude_lanes,
        carriers=carriers, exclude_carriers=exclude_carriers, grain=grain,
        _user=_user,
    )

@r.get("/{division}/service")
async def service(
    request: Request,
    team: Optional[str] = Query(None),
    customer: Optional[str] = Query(None),
    load_type: Optional[str] = Query(None),
    lanes: Optional[List[str]] = Query(None),
    exclude_lanes: Optional[List[str]] = Query(None),
    carriers: Optional[List[str]] = Query(None),
    exclude_carriers: Optional[List[str]] = Query(None),
    grain: str = Query('month'),
    _user: dict = Depends(gate),
):
    scope = scope_of(request)
    return await opo.service(
        request=request, team=_sub_team(scope, team), customer=customer,
        load_type=load_type, lanes=lanes, exclude_lanes=exclude_lanes,
        carriers=carriers, exclude_carriers=exclude_carriers, grain=grain,
        _user=_user,
    )

@r.get("/{division}/cover-forecast")
async def cover_forecast(
    request: Request,
    team: Optional[str] = Query(None),
    customer: Optional[str] = Query(None),
    load_type: Optional[str] = Query(None),
    lanes: Optional[List[str]] = Query(None),
    exclude_lanes: Optional[List[str]] = Query(None),
    carriers: Optional[List[str]] = Query(None),
    exclude_carriers: Optional[List[str]] = Query(None),
    grain: str = Query('month'),
    _user: dict = Depends(gate),
):
    scope = scope_of(request)
    return await opo.cover_forecast(
        request=request, team=_sub_team(scope, team), customer=customer,
        load_type=load_type, lanes=lanes, exclude_lanes=exclude_lanes,
        carriers=carriers, exclude_carriers=exclude_carriers, grain=grain,
        _user=_user,
    )

@r.get("/{division}/team-variance")
async def team_variance(
    request: Request,
    range: Optional[str] = Query('mtd'),
    start_date: Optional[date] = Query(None),
    end_date: Optional[date] = Query(None),
    team: Optional[str] = Query(None),
    customer: Optional[str] = Query(None),
    _user: dict = Depends(gate),
):
    scope = scope_of(request)
    _require_budget(scope)
    return await opo.team_variance(
        request=request, range=range, start_date=start_date, end_date=end_date,
        team=_sub_team(scope, team), customer=customer, _user=_user,
    )

@r.get("/{division}/customer-losses")
async def customer_losses(
    request: Request,
    range: Optional[str] = Query('mtd'),
    start_date: Optional[date] = Query(None),
    end_date: Optional[date] = Query(None),
    team: Optional[str] = Query(None),
    customer: Optional[str] = Query(None),
    load_type: Optional[str] = Query(None),
    lanes: Optional[List[str]] = Query(None),
    exclude_lanes: Optional[List[str]] = Query(None),
    carriers: Optional[List[str]] = Query(None),
    exclude_carriers: Optional[List[str]] = Query(None),
    limit: int = Query(50),
    _user: dict = Depends(gate),
):
    scope = scope_of(request)
    return await opo.customer_losses(
        request=request, range=range, start_date=start_date, end_date=end_date,
        team=_sub_team(scope, team), customer=customer, load_type=load_type,
        lanes=lanes, exclude_lanes=exclude_lanes, carriers=carriers,
        exclude_carriers=exclude_carriers, limit=limit, _user=_user,
    )

@r.get("/{division}/customer-not-billed")
async def customer_not_billed(
    request: Request,
    range: Optional[str] = Query('mtd'),
    start_date: Optional[date] = Query(None),
    end_date: Optional[date] = Query(None),
    team: Optional[str] = Query(None),
    customer: Optional[str] = Query(None),
    load_type: Optional[str] = Query(None),
    lanes: Optional[List[str]] = Query(None),
    exclude_lanes: Optional[List[str]] = Query(None),
    carriers: Optional[List[str]] = Query(None),
    exclude_carriers: Optional[List[str]] = Query(None),
    limit: int = Query(100),
    _user: dict = Depends(gate),
):
    scope = scope_of(request)
    return await opo.customer_not_billed(
        request=request, range=range, start_date=start_date, end_date=end_date,
        team=_sub_team(scope, team), customer=customer, load_type=load_type,
        lanes=lanes, exclude_lanes=exclude_lanes, carriers=carriers,
        exclude_carriers=exclude_carriers, limit=limit, _user=_user,
    )

@r.get("/{division}/team-variance-weekly")
async def team_variance_weekly(
    request: Request,
    team: Optional[str] = Query(None),
    customer: Optional[str] = Query(None),
    _user: dict = Depends(gate),
):
    scope = scope_of(request)
    _require_budget(scope)
    return await opo.team_variance_weekly(
        request=request, team=_sub_team(scope, team), customer=customer,
        _user=_user,
    )

@r.get("/{division}/team-variance-by-team")
async def team_variance_by_team(
    request: Request,
    range: Optional[str] = Query('mtd'),
    start_date: Optional[date] = Query(None),
    end_date: Optional[date] = Query(None),
    customer: Optional[str] = Query(None),
    _user: dict = Depends(gate),
):
    scope = scope_of(request)
    _require_budget(scope)
    return await opo.team_variance_by_team(
        request=request, range=range, start_date=start_date, end_date=end_date,
        customer=customer, _user=_user,
    )

@r.get("/{division}/team-performance")
async def team_performance(
    request: Request,
    range: Optional[str] = Query('mtd'),
    start_date: Optional[date] = Query(None),
    end_date: Optional[date] = Query(None),
    team: Optional[str] = Query(None),
    teams: Optional[str] = Query(None),
    customer: Optional[str] = Query(None),
    load_type: Optional[str] = Query(None),
    lanes: Optional[List[str]] = Query(None),
    exclude_lanes: Optional[List[str]] = Query(None),
    carriers: Optional[List[str]] = Query(None),
    exclude_carriers: Optional[List[str]] = Query(None),
    _user: dict = Depends(gate),
):
    scope = scope_of(request)
    return await opo.team_performance(
        request=request, range=range, start_date=start_date, end_date=end_date,
        team=_sub_team(scope, team), teams=_sub_teams(scope, teams),
        customer=customer, load_type=load_type, lanes=lanes,
        exclude_lanes=exclude_lanes, carriers=carriers,
        exclude_carriers=exclude_carriers, _user=_user,
    )

@r.get("/{division}/team-weekly-performance")
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
    scope = scope_of(request)
    return await opo.team_weekly_performance(
        request=request, team=_sub_team(scope, team), customer=customer,
        load_type=load_type, lanes=lanes, exclude_lanes=exclude_lanes,
        carriers=carriers, exclude_carriers=exclude_carriers, _user=_user,
    )

@r.get("/{division}/team-performance-by-team")
async def team_performance_by_team(
    request: Request,
    range: Optional[str] = Query('mtd'),
    start_date: Optional[date] = Query(None),
    end_date: Optional[date] = Query(None),
    team: Optional[str] = Query(None),
    customer: Optional[str] = Query(None),
    load_type: Optional[str] = Query(None),
    lanes: Optional[List[str]] = Query(None),
    exclude_lanes: Optional[List[str]] = Query(None),
    carriers: Optional[List[str]] = Query(None),
    exclude_carriers: Optional[List[str]] = Query(None),
    _user: dict = Depends(gate),
):
    scope = scope_of(request)
    return await opo.team_performance_by_team(
        request=request, range=range, start_date=start_date, end_date=end_date,
        team=_sub_team(scope, team), customer=customer, load_type=load_type,
        lanes=lanes, exclude_lanes=exclude_lanes, carriers=carriers,
        exclude_carriers=exclude_carriers, _user=_user,
    )

@r.get("/{division}/team-projection")
async def team_projection(
    request: Request,
    team: Optional[str] = Query(None),
    teams: Optional[str] = Query(None),
    customer: Optional[str] = Query(None),
    load_type: Optional[str] = Query(None),
    lanes: Optional[List[str]] = Query(None),
    exclude_lanes: Optional[List[str]] = Query(None),
    carriers: Optional[List[str]] = Query(None),
    exclude_carriers: Optional[List[str]] = Query(None),
    _user: dict = Depends(gate),
):
    scope = scope_of(request)
    return await opo.team_projection(
        request=request, team=_sub_team(scope, team), teams=_sub_teams(scope,
        teams), customer=customer, load_type=load_type, lanes=lanes,
        exclude_lanes=exclude_lanes, carriers=carriers,
        exclude_carriers=exclude_carriers, _user=_user,
    )

@r.get("/{division}/profit-tm-gauge")
async def profit_tm_gauge(
    request: Request,
    team: Optional[str] = Query(None),
    teams: Optional[str] = Query(None),
    customer: Optional[str] = Query(None),
    load_type: Optional[str] = Query(None),
    lanes: Optional[List[str]] = Query(None),
    exclude_lanes: Optional[List[str]] = Query(None),
    carriers: Optional[List[str]] = Query(None),
    exclude_carriers: Optional[List[str]] = Query(None),
    _user: dict = Depends(gate),
):
    scope = scope_of(request)
    return await opo.profit_tm_gauge(
        request=request, team=_sub_team(scope, team), teams=_sub_teams(scope,
        teams), customer=customer, load_type=load_type, lanes=lanes,
        exclude_lanes=exclude_lanes, carriers=carriers,
        exclude_carriers=exclude_carriers, _user=_user,
    )

@r.get("/{division}/team-projection-by-team")
async def team_projection_by_team(
    request: Request,
    customer: Optional[str] = Query(None),
    load_type: Optional[str] = Query(None),
    lanes: Optional[List[str]] = Query(None),
    exclude_lanes: Optional[List[str]] = Query(None),
    carriers: Optional[List[str]] = Query(None),
    exclude_carriers: Optional[List[str]] = Query(None),
    _user: dict = Depends(gate),
):
    return await opo.team_projection_by_team(
        request=request, customer=customer, load_type=load_type, lanes=lanes,
        exclude_lanes=exclude_lanes, carriers=carriers,
        exclude_carriers=exclude_carriers, _user=_user,
    )

@r.get("/{division}/team-projection-weekly")
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
    scope = scope_of(request)
    return await opo.team_projection_weekly(
        request=request, team=_sub_team(scope, team), customer=customer,
        load_type=load_type, lanes=lanes, exclude_lanes=exclude_lanes,
        carriers=carriers, exclude_carriers=exclude_carriers, _user=_user,
    )

@r.get("/{division}/team-projection-history")
async def team_projection_history(
    request: Request,
    team: Optional[str] = Query(None),
    teams: Optional[str] = Query(None),
    customer: Optional[str] = Query(None),
    load_type: Optional[str] = Query(None),
    lanes: Optional[List[str]] = Query(None),
    exclude_lanes: Optional[List[str]] = Query(None),
    carriers: Optional[List[str]] = Query(None),
    exclude_carriers: Optional[List[str]] = Query(None),
    months: int = Query(13),
    _user: dict = Depends(gate),
):
    scope = scope_of(request)
    return await opo.team_projection_history(
        request=request, team=_sub_team(scope, team), teams=_sub_teams(scope,
        teams), customer=customer, load_type=load_type, lanes=lanes,
        exclude_lanes=exclude_lanes, carriers=carriers,
        exclude_carriers=exclude_carriers, months=months, _user=_user,
    )

@r.get("/{division}/actuals")
async def actuals(
    request: Request,
    range: Optional[str] = Query('mtd'),
    start_date: Optional[date] = Query(None),
    end_date: Optional[date] = Query(None),
    team: Optional[str] = Query(None),
    teams: Optional[str] = Query(None),
    customer: Optional[str] = Query(None),
    load_type: Optional[str] = Query(None),
    lanes: Optional[List[str]] = Query(None),
    exclude_lanes: Optional[List[str]] = Query(None),
    carriers: Optional[List[str]] = Query(None),
    exclude_carriers: Optional[List[str]] = Query(None),
    sort: str = Query('revenue_desc'),
    limit: int = Query(100),
    losses_only: bool = Query(False),
    unbilled_only: bool = Query(False),
    _user: dict = Depends(gate),
):
    scope = scope_of(request)
    return await opo.actuals(
        request=request, range=range, start_date=start_date, end_date=end_date,
        team=_sub_team(scope, team), teams=_sub_teams(scope, teams),
        customer=customer, load_type=load_type, lanes=lanes,
        exclude_lanes=exclude_lanes, carriers=carriers,
        exclude_carriers=exclude_carriers, sort=sort, limit=limit,
        losses_only=losses_only, unbilled_only=unbilled_only, _user=_user,
    )

@r.get("/{division}/actuals-by-lane")
async def actuals_by_lane(
    request: Request,
    range: Optional[str] = Query('mtd'),
    start_date: Optional[date] = Query(None),
    end_date: Optional[date] = Query(None),
    team: Optional[str] = Query(None),
    customer: Optional[str] = Query(None),
    load_type: Optional[str] = Query(None),
    lanes: Optional[List[str]] = Query(None),
    exclude_lanes: Optional[List[str]] = Query(None),
    carriers: Optional[List[str]] = Query(None),
    exclude_carriers: Optional[List[str]] = Query(None),
    sort: str = Query('revenue_desc'),
    limit: int = Query(100),
    losses_only: bool = Query(False),
    unbilled_only: bool = Query(False),
    _user: dict = Depends(gate),
):
    scope = scope_of(request)
    return await opo.actuals_by_lane(
        request=request, range=range, start_date=start_date, end_date=end_date,
        team=_sub_team(scope, team), customer=customer, load_type=load_type,
        lanes=lanes, exclude_lanes=exclude_lanes, carriers=carriers,
        exclude_carriers=exclude_carriers, sort=sort, limit=limit,
        losses_only=losses_only, unbilled_only=unbilled_only, _user=_user,
    )

@r.get("/{division}/margin-distribution")
async def margin_distribution(
    request: Request,
    range: Optional[str] = Query('mtd'),
    start_date: Optional[date] = Query(None),
    end_date: Optional[date] = Query(None),
    team: Optional[str] = Query(None),
    customer: Optional[str] = Query(None),
    load_type: Optional[str] = Query(None),
    lanes: Optional[List[str]] = Query(None),
    exclude_lanes: Optional[List[str]] = Query(None),
    carriers: Optional[List[str]] = Query(None),
    exclude_carriers: Optional[List[str]] = Query(None),
    _user: dict = Depends(gate),
):
    scope = scope_of(request)
    return await opo.margin_distribution(
        request=request, range=range, start_date=start_date, end_date=end_date,
        team=_sub_team(scope, team), customer=customer, load_type=load_type,
        lanes=lanes, exclude_lanes=exclude_lanes, carriers=carriers,
        exclude_carriers=exclude_carriers, _user=_user,
    )

@r.get("/{division}/by-order")
async def by_order(
    request: Request,
    range: Optional[str] = Query('mtd'),
    start_date: Optional[date] = Query(None),
    end_date: Optional[date] = Query(None),
    team: Optional[str] = Query(None),
    customer: Optional[str] = Query(None),
    load_type: Optional[str] = Query(None),
    lanes: Optional[List[str]] = Query(None),
    exclude_lanes: Optional[List[str]] = Query(None),
    carriers: Optional[List[str]] = Query(None),
    exclude_carriers: Optional[List[str]] = Query(None),
    sort: str = Query('revenue_desc'),
    limit: int = Query(500),
    losses_only: bool = Query(False),
    unbilled_only: bool = Query(False),
    _user: dict = Depends(gate),
):
    scope = scope_of(request)
    return await opo.by_order(
        request=request, range=range, start_date=start_date, end_date=end_date,
        team=_sub_team(scope, team), customer=customer, load_type=load_type,
        lanes=lanes, exclude_lanes=exclude_lanes, carriers=carriers,
        exclude_carriers=exclude_carriers, sort=sort, limit=limit,
        losses_only=losses_only, unbilled_only=unbilled_only, _user=_user,
    )

@r.get("/{division}/pending-to-cover")
async def pending_to_cover(
    request: Request,
    team: Optional[str] = Query(None),
    customer: Optional[str] = Query(None),
    lanes: Optional[List[str]] = Query(None),
    exclude_lanes: Optional[List[str]] = Query(None),
    limit: int = Query(500),
    _user: dict = Depends(gate),
):
    scope = scope_of(request)
    return await opo.pending_to_cover(
        request=request, team=_sub_team(scope, team), customer=customer,
        lanes=lanes, exclude_lanes=exclude_lanes, limit=limit, _user=_user,
    )

@r.get("/{division}/cover")
async def cover(
    request: Request,
    team: Optional[str] = Query(None),
    customer: Optional[str] = Query(None),
    lanes: Optional[List[str]] = Query(None),
    exclude_lanes: Optional[List[str]] = Query(None),
    limit: int = Query(500),
    _user: dict = Depends(gate),
):
    scope = scope_of(request)
    return await opo.cover(
        request=request, team=_sub_team(scope, team), customer=customer,
        lanes=lanes, exclude_lanes=exclude_lanes, limit=limit, _user=_user,
    )

@r.get("/{division}/hold")
async def hold_board(
    request: Request,
    team: Optional[str] = Query(None),
    customer: Optional[str] = Query(None),
    lanes: Optional[List[str]] = Query(None),
    exclude_lanes: Optional[List[str]] = Query(None),
    sort: str = Query('delay_asc'),
    limit: int = Query(500),
    _user: dict = Depends(gate),
):
    scope = scope_of(request)
    return await opo.hold_board(
        request=request, team=_sub_team(scope, team), customer=customer,
        lanes=lanes, exclude_lanes=exclude_lanes, sort=sort, limit=limit,
        _user=_user,
    )

@r.get("/{division}/service-incident-by-customer")
async def service_incident_by_customer(
    request: Request,
    range: Optional[str] = Query('mtd'),
    start_date: Optional[date] = Query(None),
    end_date: Optional[date] = Query(None),
    team: Optional[str] = Query(None),
    customer: Optional[str] = Query(None),
    load_type: Optional[str] = Query(None),
    lanes: Optional[List[str]] = Query(None),
    exclude_lanes: Optional[List[str]] = Query(None),
    carriers: Optional[List[str]] = Query(None),
    exclude_carriers: Optional[List[str]] = Query(None),
    stop_type: str = Query('pu'),
    _user: dict = Depends(gate),
):
    scope = scope_of(request)
    return await opo.service_incident_by_customer(
        request=request, range=range, start_date=start_date, end_date=end_date,
        team=_sub_team(scope, team), customer=customer, load_type=load_type,
        lanes=lanes, exclude_lanes=exclude_lanes, carriers=carriers,
        exclude_carriers=exclude_carriers, stop_type=stop_type, _user=_user,
    )

@r.get("/{division}/service-by-carrier")
async def service_by_carrier(
    request: Request,
    range: Optional[str] = Query('mtd'),
    start_date: Optional[date] = Query(None),
    end_date: Optional[date] = Query(None),
    team: Optional[str] = Query(None),
    customer: Optional[str] = Query(None),
    load_type: Optional[str] = Query(None),
    lanes: Optional[List[str]] = Query(None),
    exclude_lanes: Optional[List[str]] = Query(None),
    carriers: Optional[List[str]] = Query(None),
    exclude_carriers: Optional[List[str]] = Query(None),
    limit: int = Query(100),
    _user: dict = Depends(gate),
):
    scope = scope_of(request)
    return await opo.service_by_carrier(
        request=request, range=range, start_date=start_date, end_date=end_date,
        team=_sub_team(scope, team), customer=customer, load_type=load_type,
        lanes=lanes, exclude_lanes=exclude_lanes, carriers=carriers,
        exclude_carriers=exclude_carriers, limit=limit, _user=_user,
    )
