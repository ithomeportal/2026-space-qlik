"""Team Monthly Projection panels and the Profit-TM gauge.

Part of the ``ops_portal_overview`` package (split 2026-08-14 — see SPEC-CUSTOM-REPORTS §28).
"""

from __future__ import annotations

import asyncio
from datetime import timedelta
from typing import Any, List, Optional

from fastapi import Depends, Query, Request

from app.clock import cst_today
from app.routers.deps import get_datalake_gold_pool, get_pool, require_report_access

from ._constants import customer_team_cte, CORP_TEAMS, CUSTOMER_TEAM_CTE, router
from ._dates import _count_workdays, _last_5_weeks, _last_n_business_days_start, _month_bounds, _week_label
from ._scope import scope_of
from ._sql import _parse_team_scope, _v4_scope_where
from ._metrics import _zero_val, _projection_from_sums, _safe_float, _team_projection_core

# ⚠ `app.services.projection_history` is imported INSIDE the endpoint, not at
# module level, and the indirection is load-bearing.
#
# The service needs this package's leaf modules (`_metrics`, `_sql`, `_scope`,
# `_constants`) — and importing ANY submodule of a package runs that package's
# `__init__` first. This package's `__init__` is a façade that imports
# `.projection` (§28), so a module-level import here closes the loop:
#
#     app.services.projection_history
#       -> app.routers.ops_portal_overview._constants
#       -> app.routers.ops_portal_overview.__init__   (the façade)
#       -> .projection
#       -> app.services.projection_history            (still initialising)
#
# It only fails in ONE direction — importing the router package first works,
# which is what the app and every existing test do — so it would have shipped
# green and broken the scheduler job and any standalone script that reaches for
# the service on its own. `sys.modules` makes the deferred import a dict lookup.


def _history() -> Any:
    """The projection-history service — deferred; see the note above."""
    from app.services import projection_history

    return projection_history


# ---------------------------------------------------------------------------
# /team-projection — §6 Team Monthly Projection. SOURCE OF TRUTH for Projected
# across the whole report (Bruno R6, 2026-08-14). Ignores the Date filter.
# ---------------------------------------------------------------------------


@router.get("/team-projection")
async def team_projection(
    request: Request,
    team: Optional[str] = Query(None),
    teams: Optional[str] = Query(
        None, description="Comma-separated multi-team scope, e.g. TEAM1,TEAM2,TEAM3,TEAM4"
    ),
    customer: Optional[str] = Query(None),
    load_type: Optional[str] = Query(None),
    lanes: Optional[List[str]] = Query(None),
    exclude_lanes: Optional[List[str]] = Query(None),
    # Bruno (PDF 2026-07-15) R1: Carrier multi-select (Include/Exclude).
    carriers: Optional[List[str]] = Query(None),
    exclude_carriers: Optional[List[str]] = Query(None),
    _user: dict = Depends(require_report_access("ops-portal-overview")),
):
    """§6 Team Monthly Projection — last 12 Mon-Sat business days extrapolated to EoM.

    Bruno round-2 (2026-05-13): switched divisor from 14 calendar days to
    12 business days (Mon-Sat). The SQL still scans a calendar window
    ending yesterday, but filters out Sundays so the divisor is exact.

    Date filter intentionally ignored (projection always uses the rolling
    business-day window). Team + Customer apply.
    """
    pool = get_datalake_gold_pool(request)
    scope = scope_of(request)
    today = cst_today()
    m_start, m_end = _month_bounds(today)

    # R6: this endpoint IS the source of truth for Projected. The window,
    # divisor and MTD legs now live in _team_projection_core so /combo and
    # /actuals compute the identical number instead of their own variants.
    proj = await _team_projection_core(
        pool, team=_parse_team_scope(team, teams), customer=customer, load_type=load_type,
        lanes=lanes, exclude_lanes=exclude_lanes,
        carriers=carriers, exclude_carriers=exclude_carriers, today=today, scope=scope,
    )

    return {
        "success": True,
        "data": {
            **proj,
            "today": today.isoformat(),
            "month_start": m_start.isoformat(),
            "month_end": m_end.isoformat(),
        },
    }


# ---------------------------------------------------------------------------
# /profit-tm-gauge — bottom-middle Profit-TM gauge (MTD profit vs budget)
# ---------------------------------------------------------------------------


@router.get("/profit-tm-gauge")
async def profit_tm_gauge(
    request: Request,
    team: Optional[str] = Query(None),
    teams: Optional[str] = Query(
        None, description="Comma-separated multi-team scope, e.g. TEAM1,TEAM2,TEAM3,TEAM4"
    ),
    customer: Optional[str] = Query(None),
    load_type: Optional[str] = Query(None),
    lanes: Optional[List[str]] = Query(None),
    exclude_lanes: Optional[List[str]] = Query(None),
    # Bruno (PDF 2026-07-15) R1: Carrier multi-select (Include/Exclude).
    carriers: Optional[List[str]] = Query(None),
    exclude_carriers: Optional[List[str]] = Query(None),
    _user: dict = Depends(require_report_access("ops-portal-overview")),
):
    """Horizontal gauge under the chart. Always current month MTD."""
    pool = get_datalake_gold_pool(request)
    scope = scope_of(request)
    today = cst_today()
    m_start, m_end = _month_bounds(today)
    team_scope = _parse_team_scope(team, teams)

    # Production MTD profit
    p_params: list = []
    where = _v4_scope_where("br4", team_scope, customer, load_type, p_params, lanes, exclude_lanes, carriers, exclude_carriers, scope=scope)
    p_params.extend([m_start, today])
    p_s = len(p_params) - 1
    p_e = len(p_params)
    prod_sql = f"""
        SELECT COALESCE(SUM(br4.margin_amt), 0)::numeric AS profit_mtd
        FROM public.mcleod_gld_budget_report_v4 br4
        WHERE {where}
          AND br4.origin_actual_departure >= ${p_s}
          AND br4.origin_actual_departure < (${p_e}::date + INTERVAL '1 day')
    """

    # Budget MTD profit (target)
    b_params: list = [m_start, m_end]
    b_extra = ""
    # ct.team_id is the TRIMmed CUSTOMER_TEAM_CTE output — plain ids, no padding.
    if team_scope:
        b_params.append(team_scope)
        b_extra += f" AND ct.team_id = ANY(${len(b_params)})"
    if customer:
        b_params.append(customer)
        b_extra += f' AND budget."Customer Name" = ${len(b_params)}'
    bud_sql = f"""
        WITH {customer_team_cte(scope, with_budget_team=True)}
        SELECT COALESCE(SUM(budget."Profit Budget"), 0)::numeric AS profit_budget
        FROM public.daily_production_budget_report budget
        LEFT JOIN budget_team ct ON TRIM(budget."Customer Name") = ct.customer_name
        WHERE budget."Date" BETWEEN $1 AND $2
        {b_extra}
    """

    prod_val, bud_val = await asyncio.gather(
        pool.fetchval(prod_sql, *p_params),
        pool.fetchval(bud_sql, *b_params) if scope.has_budget else _zero_val(),
    )
    profit_mtd = _safe_float(prod_val)
    profit_budget = _safe_float(bud_val)
    return {
        "success": True,
        "data": {
            "profit_mtd": profit_mtd,
            "profit_budget": profit_budget,
            "pct_of_budget": (profit_mtd / profit_budget * 100.0) if profit_budget else 0.0,
            "month_start": m_start.isoformat(),
            "month_end": m_end.isoformat(),
        },
    }


@router.get("/team-projection-by-team")
async def team_projection_by_team(
    request: Request,
    customer: Optional[str] = Query(None),
    load_type: Optional[str] = Query(None),
    lanes: Optional[List[str]] = Query(None),
    exclude_lanes: Optional[List[str]] = Query(None),
    # Bruno (PDF 2026-07-15) R1: Carrier multi-select (Include/Exclude).
    carriers: Optional[List[str]] = Query(None),
    exclude_carriers: Optional[List[str]] = Query(None),
    _user: dict = Depends(require_report_access("ops-portal-overview")),
):
    """Team Monthly Projection split per CORP team (TEAM1..TEAM5) + a Total.

    Same rolling 12-business-day → EoM extrapolation as /team-projection, run
    once per team_id. Per-team capacity uses team_count = 1; the Total uses the
    number of teams with data. The single ``team`` filter is dropped.
    """
    pool = get_datalake_gold_pool(request)
    scope = scope_of(request)
    today = cst_today()
    m_start, m_end = _month_bounds(today)
    win_start = _last_n_business_days_start(today, 12)
    win_end = today - timedelta(days=1)
    pending_workdays = _count_workdays(today, m_end)

    params: list = []
    where = _v4_scope_where("br4", None, customer, load_type, params, lanes, exclude_lanes, carriers, exclude_carriers, scope=scope)
    params.extend([win_start, win_end, m_start, win_end, m_start, m_end])
    p_ws = len(params) - 5
    p_we = len(params) - 4
    p_ms1 = len(params) - 3
    p_we2 = len(params) - 2
    p_ms2 = len(params) - 1
    p_me = len(params)
    rows = await pool.fetch(
        f"""
        SELECT
          TRIM(br4.team_id) AS team_id,
          COUNT(*) FILTER (WHERE br4.origin_actual_departure::date BETWEEN ${p_ws} AND ${p_we}
                             AND EXTRACT(DOW FROM br4.origin_actual_departure::date) <> 0
                             AND br4.total_charge IS NOT NULL AND br4.total_charge <> 0) AS vol_12,
          COALESCE(SUM(CASE WHEN br4.origin_actual_departure::date BETWEEN ${p_ws} AND ${p_we}
                              AND EXTRACT(DOW FROM br4.origin_actual_departure::date) <> 0
                            THEN br4.total_charge END), 0)::numeric AS rev_12,
          COALESCE(SUM(CASE WHEN br4.origin_actual_departure::date BETWEEN ${p_ws} AND ${p_we}
                              AND EXTRACT(DOW FROM br4.origin_actual_departure::date) <> 0
                            THEN br4.margin_amt END), 0)::numeric AS prof_12,
          COUNT(*) FILTER (WHERE br4.origin_actual_departure::date BETWEEN ${p_ms1} AND ${p_we2}
                             AND br4.total_charge IS NOT NULL AND br4.total_charge <> 0) AS vol_mtd,
          COALESCE(SUM(CASE WHEN br4.origin_actual_departure::date BETWEEN ${p_ms2} AND ${p_me}
                            THEN br4.total_charge END), 0)::numeric AS rev_mtd,
          COALESCE(SUM(CASE WHEN br4.origin_actual_departure::date BETWEEN ${p_ms2} AND ${p_me}
                            THEN br4.margin_amt END), 0)::numeric AS prof_mtd
        FROM public.mcleod_gld_budget_report_v4 br4
        WHERE {where}
        GROUP BY TRIM(br4.team_id)
        """,
        *params,
    )
    by_team = {r["team_id"]: r for r in rows}
    acc = {"v12": 0.0, "r12": 0.0, "p12": 0.0, "vm": 0.0, "rm": 0.0, "pm": 0.0}
    teams_out = []
    for t in scope.sub_teams:
        r = by_team.get(t)
        obj = _projection_from_sums(
            r["vol_12"] if r else 0, r["rev_12"] if r else 0, r["prof_12"] if r else 0,
            r["vol_mtd"] if r else 0, r["rev_mtd"] if r else 0, r["prof_mtd"] if r else 0,
            pending_workdays, 1,
        )
        obj["team_id"] = t
        teams_out.append(obj)
        if r:
            acc["v12"] += _safe_float(r["vol_12"]); acc["r12"] += _safe_float(r["rev_12"]); acc["p12"] += _safe_float(r["prof_12"])
            acc["vm"] += _safe_float(r["vol_mtd"]); acc["rm"] += _safe_float(r["rev_mtd"]); acc["pm"] += _safe_float(r["prof_mtd"])
    total = _projection_from_sums(
        acc["v12"], acc["r12"], acc["p12"], acc["vm"], acc["rm"], acc["pm"],
        pending_workdays, len(rows) or len(scope.sub_teams),
    )
    return {
        "success": True,
        "data": {
            "total": total, "teams": teams_out,
            "today": today.isoformat(),
            "month_start": m_start.isoformat(),
            "month_end": m_end.isoformat(),
        },
    }


@router.get("/team-projection-weekly")
async def team_projection_weekly(
    request: Request,
    team: Optional[str] = Query(None),
    customer: Optional[str] = Query(None),
    load_type: Optional[str] = Query(None),
    lanes: Optional[List[str]] = Query(None),
    exclude_lanes: Optional[List[str]] = Query(None),
    # Bruno (PDF 2026-07-15) R1: Carrier multi-select (Include/Exclude).
    carriers: Optional[List[str]] = Query(None),
    exclude_carriers: Optional[List[str]] = Query(None),
    _user: dict = Depends(require_report_access("ops-portal-overview")),
):
    """Team Monthly Projection "Week" view — per-week ACTUALS for the last 5
    Mon-Sun weeks (Bruno decision 2026-07-13).

    A projection is inherently forward-looking, so a per-week grouping shows
    each recent week's realised figures under the projection's row labels:
    Avg *·Day = week total ÷ that week's Mon-Sat workdays; Proj * = that week's
    actual; Team Ut. = week volume ÷ (500 × active teams). Fixed rolling
    window; team/customer/lane filters apply, the page date filter is ignored.
    """
    pool = get_datalake_gold_pool(request)
    scope = scope_of(request)
    today = cst_today()
    week_starts, weeks_start, weeks_end = _last_5_weeks(today)
    params: list = []
    where = _v4_scope_where("br4", team, customer, load_type, params, lanes, exclude_lanes, carriers, exclude_carriers, scope=scope)
    params.extend([weeks_start, weeks_end])
    p_s = len(params) - 1
    p_e = len(params)
    rows = await pool.fetch(
        f"""
        SELECT
          DATE_TRUNC('week', br4.origin_actual_departure)::date AS wk,
          COUNT(*) FILTER (WHERE br4.total_charge IS NOT NULL AND br4.total_charge <> 0) AS vol,
          COALESCE(SUM(br4.total_charge), 0)::numeric AS rev,
          COALESCE(SUM(br4.margin_amt),  0)::numeric AS prof,
          COUNT(DISTINCT br4.team_id) AS team_count
        FROM public.mcleod_gld_budget_report_v4 br4
        WHERE {where}
          AND br4.origin_actual_departure >= ${p_s}
          AND br4.origin_actual_departure < (${p_e}::date + INTERVAL '1 day')
        GROUP BY wk
        """,
        *params,
    )
    by_wk = {r["wk"]: r for r in rows}
    weeks_out = []
    for ws in week_starts:
        r = by_wk.get(ws)
        we = ws + timedelta(days=6)
        vol = int(r["vol"] or 0) if r else 0
        rev = _safe_float(r["rev"]) if r else 0.0
        prof = _safe_float(r["prof"]) if r else 0.0
        # Workdays elapsed in this week (cap the current, partial week at today).
        wk_workdays = _count_workdays(ws, min(we, today)) or 1
        team_count = (int(r["team_count"] or 0) if r else 0) or (1 if team else len(scope.sub_teams))
        cap = 500.0 * team_count
        weeks_out.append({
            "start": ws.isoformat(),
            "end": we.isoformat(),
            "label": _week_label(ws),
            "avg_vol_day":  _safe_float(vol / wk_workdays),
            "avg_rev_day":  _safe_float(rev / wk_workdays),
            "avg_prof_day": _safe_float(prof / wk_workdays),
            "pending_workdays": wk_workdays,
            "proj_volume":  vol,
            "proj_revenue": rev,
            "proj_profit":  prof,
            "proj_margin_pct": _safe_float((prof / rev * 100.0) if rev else 0.0),
            "proj_rev_x_l":  _safe_float((rev / vol) if vol else 0.0),
            "proj_prof_x_l": _safe_float((prof / vol) if vol else 0.0),
            "proj_team_ut":  _safe_float((vol / cap * 100.0) if cap else 0.0),
        })
    return {"success": True, "data": {"weeks": weeks_out}}


# ---------------------------------------------------------------------------
# /team-projection-history — the "stock market" view of Proj. Profit
# ---------------------------------------------------------------------------
# Request 2026-08-25: show the month's HIGH, LOW and % variation beside the
# projection, track that variation by month to expose the error rate, and keep
# the series for ever so seasonality is comparable year over year.
#
# Reads `ops_projection_history` (analytics_hub, portal-owned) rather than
# recomputing: the point of the panel is what the number DID, and only a
# stored series knows that. See services/projection_history.py.
#
# ⚠ Today's LIVE value is folded in over the stored row. The snapshot job runs
# at 02:45 CST and captures the day's OPENING value; by the time anyone opens
# the page — or the 05:28 e-mail goes out — the live figure has moved. Without
# the fold-in the strip could print a "High" lower than the number printed
# directly above it (§16).
#
# ⚠ History is UNFILTERED. A customer / lane / carrier / load-type filter makes
# the panel's number incomparable with the stored series, so the endpoint
# answers `tracked: false` and the UI hides the strip instead of showing a
# High/Low that belongs to a different population.


@router.get("/team-projection-history")
async def team_projection_history(
    request: Request,
    team: Optional[str] = Query(None),
    teams: Optional[str] = Query(
        None, description="Comma-separated multi-team scope, e.g. TEAM1,TEAM2,TEAM3,TEAM4"
    ),
    customer: Optional[str] = Query(None),
    load_type: Optional[str] = Query(None),
    lanes: Optional[List[str]] = Query(None),
    exclude_lanes: Optional[List[str]] = Query(None),
    carriers: Optional[List[str]] = Query(None),
    exclude_carriers: Optional[List[str]] = Query(None),
    months: int = Query(13, ge=1, le=60, description="How many closed months of OHLC history"),
    _user: dict = Depends(require_report_access("ops-portal-overview")),
):
    """Month-to-date High / Low / variation for Proj. Profit, plus monthly OHLC.

    Every filter parameter is declared even though only the team scope selects
    a stored series: sibling endpoints on this router must accept the same set
    or FastAPI drops the ones they omit, and the page sends one filter object
    to all of them.
    """
    gold = get_datalake_gold_pool(request)
    hub = get_pool(request)
    scope = scope_of(request)
    today = cst_today()
    m_start, m_end = _month_bounds(today)
    team_scope = _parse_team_scope(team, teams)

    filtered = bool(customer or load_type or lanes or exclude_lanes
                    or carriers or exclude_carriers)
    hist = _history()
    team_key = hist.resolve_history_key(scope, team_scope)

    # The live figure is fetched either way — it is what the strip compares
    # against, and it is the same call the panel above it makes (§69).
    live = await _team_projection_core(
        gold, team=team_scope or None, customer=customer, load_type=load_type,
        lanes=lanes, exclude_lanes=exclude_lanes,
        carriers=carriers, exclude_carriers=exclude_carriers,
        today=today, scope=scope,
    )
    live_profit = _safe_float(live.get("proj_profit"))

    base = {
        "scope_key": scope.key,
        "team_key": team_key,
        "today": today.isoformat(),
        "month_start": m_start.isoformat(),
        "month_end": m_end.isoformat(),
        "live_proj_profit": live_profit,
    }
    if filtered or team_key is None:
        return {
            "success": True,
            "data": {
                **base,
                "tracked": False,
                "untracked_reason": "filtered" if filtered else "team_scope",
                "current_month": None,
                "months": [],
            },
        }

    points, month_rows = await asyncio.gather(
        hist.month_points(hub, scope_key=scope.key, team_key=team_key, month_start=m_start),
        hist.monthly_summary(hub, scope_key=scope.key, team_key=team_key,
                             months=months, before_month=m_start),
    )
    current = hist.current_month_stats(points, live_value=live_profit, today=today)

    if month_rows:
        actuals = await hist.actual_profit_by_month(
            gold, scope=scope, team_ids=team_scope,
            start=month_rows[0]["month_start"], end=m_start - timedelta(days=1),
        )
        month_rows = hist.attach_actuals(month_rows, actuals)

    return {
        "success": True,
        "data": {
            **base,
            "tracked": True,
            "current_month": {
                **{k: v for k, v in current.items() if k != "points"},
                "high_date": current["high_date"].isoformat() if current["high_date"] else None,
                "low_date": current["low_date"].isoformat() if current["low_date"] else None,
                "points": [
                    {**p, "as_of_date": p["as_of_date"].isoformat()}
                    for p in current["points"]
                ],
            },
            "months": [
                {**m, "month_start": m["month_start"].isoformat()}
                for m in month_rows
            ],
        },
    }
