"""KPI MANAGEMENT combo chart, service series and the Forecast overlay.

Part of the ``ops_portal_overview`` package (split 2026-08-14 — see SPEC-CUSTOM-REPORTS §28).
"""

from __future__ import annotations

import asyncio
from typing import List, Optional

from fastapi import Depends, Query, Request

from app.clock import cst_today
from app.datalake import pad_variants as _pad_variants
from app.routers.deps import get_datalake_gold_pool, require_report_access

from ._constants import customer_team_cte, CORP_COMPANIES, CORP_TEAMS, CUSTOMER_TEAM_CTE, router
from ._dates import _count_workdays, _month_bounds, _resolve_grain_window
from ._scope import scope_of
from ._sql import _sub_team_param, _ASSIGNED, _carrier_first_expr, _lane_expr, _scorecard_cte, _v4_scope_where
from ._metrics import _empty_rows, _safe_float, _team_projection_core


@router.get("/combo")
async def combo(
    request: Request,
    team: Optional[str] = Query(None),
    customer: Optional[str] = Query(None),
    load_type: Optional[str] = Query(None, description="'contract' | 'spot' | null"),
    lanes: Optional[List[str]] = Query(None),
    exclude_lanes: Optional[List[str]] = Query(None),
    # Bruno (PDF 2026-07-15) R1: Carrier multi-select (Include/Exclude).
    carriers: Optional[List[str]] = Query(None),
    exclude_carriers: Optional[List[str]] = Query(None),
    grain: str = Query("month", description="'day' | 'week' | 'month'"),
    _user: dict = Depends(require_report_access("ops-portal-overview")),
):
    """Day/Week/Month combo. Bars carry vol/rev/prof/margin so the UI can swap
    between them without re-fetching. Lines: losses_{vol,rev,prof,margin_pct},
    budget_{loads,revenue,profit,margin_pct}, projected_{vol,revenue,profit,margin_pct}.

    Bruno's round-3 per-tab "Losses x M" formula spec (2026-05-19 PDF):
      - Vol tab   → losses_vol         = COUNT(*) WHERE margin_amt < 0
      - Rev tab   → losses_rev         = SUM(total_charge) WHERE margin_amt < 0
      - Prof tab  → losses_prof        = SUM(margin_amt) WHERE margin_amt < 0
      - Marg.% tab→ losses_margin_pct  = losses_prof / losses_rev * 100

    BDGT line scales with the tab too — backend returns all four budget variants.
    Frontend picks the matching key based on the active measure pill.

    Source split unchanged:
      - Bars + losses_*   → mcleod_gld_budget_report_v4 (Production)
      - budget_*          → daily_production_budget_report (Budget)
      - projected_*       → 14-day rolling Production extrapolated to EoM
    """
    if grain not in ("day", "week", "month"):
        grain = "month"
    pool = get_datalake_gold_pool(request)
    scope = scope_of(request)
    today = cst_today()
    win_start, win_end, anchors = _resolve_grain_window(grain, today)

    # Bruno (PDF 2026-08-27 "Ops Portal Updates") Request 1: the BDGT line read
    # 1,243 / $2,317,148 / $433,303 for Aug-2026 against the budget table's true
    # 1,432.03 / $2,706,634.18 / $502,241.50. `_resolve_grain_window` caps the
    # window at today so a partial period is not double-counted — right for the
    # v4 bars (production that has not happened yet does not exist), wrong for
    # the budget line, which is a WHOLE-MONTH plan that merely happens to be
    # stored one row per day. Truncating it compared a full month of production
    # against 27/31 of its target.
    #
    # So the budget leg alone runs to the end of the last MONTH bucket. The
    # gauge directly under this chart already pairs MTD actual with the full
    # month's target, so this makes the two agree instead of disagreeing by the
    # remaining days. Day and week grains keep `win_end` untouched: a day bucket
    # is already whole, and Bruno validated the month figure only.
    #
    # ⚠ Deliberately computed here and NOT inside `_resolve_grain_window` —
    # `test_chart_grain_window.py` pins that helper to end at today, and that
    # guard protects the production bars. This widens one leg, not the window.
    bud_end = win_end
    if grain == "month":
        bud_end = _month_bounds(anchors[-1])[1]

    trunc_v4 = {
        "day":   "br4.origin_actual_departure::date",
        "week":  "DATE_TRUNC('week', br4.origin_actual_departure)::date",
        "month": "DATE_TRUNC('month', br4.origin_actual_departure)::date",
    }[grain]
    trunc_bud = {
        "day":   'budget."Date"::date',
        "week":  'DATE_TRUNC(\'week\', budget."Date")::date',
        "month": 'DATE_TRUNC(\'month\', budget."Date")::date',
    }[grain]

    # ---- Production query (bars + losses) -------------------------------
    prod_params: list = []
    where = _v4_scope_where("br4", team, customer, load_type, prod_params, lanes, exclude_lanes, carriers, exclude_carriers, scope=scope)
    prod_params.extend([win_start, win_end])
    p_ws = len(prod_params) - 1
    p_we = len(prod_params)
    prod_sql = f"""
        SELECT
          {trunc_v4} AS bucket_start,
          COUNT(*) FILTER (WHERE br4.total_charge IS NOT NULL AND br4.total_charge <> 0) AS volume,
          COALESCE(SUM(br4.total_charge), 0)::numeric AS revenue,
          COALESCE(SUM(br4.margin_amt), 0)::numeric   AS profit,
          COUNT(*) FILTER (WHERE br4.margin_amt < 0
                             AND br4.total_charge IS NOT NULL
                             AND br4.total_charge <> 0) AS losses_vol,
          COALESCE(SUM(br4.total_charge) FILTER (WHERE br4.margin_amt < 0), 0)::numeric AS losses_rev,
          COALESCE(SUM(br4.margin_amt)   FILTER (WHERE br4.margin_amt < 0), 0)::numeric AS losses_prof
        FROM public.mcleod_gld_budget_report_v4 br4
        WHERE {where}
          AND br4.origin_actual_departure >= ${p_ws}
          AND br4.origin_actual_departure < (${p_we}::date + INTERVAL '1 day')
        GROUP BY 1
    """

    # ---- Budget (Budget URL) --------------------------------------------
    bud_params: list = [win_start, bud_end]
    bud_extra = ""
    if team:
        bud_params.append(team)
        bud_extra += f" AND ct.team_id = ${len(bud_params)}"
    if customer:
        bud_params.append(customer)
        bud_extra += f' AND budget."Customer Name" = ${len(bud_params)}'
    bud_sql = f"""
        WITH {customer_team_cte(scope, with_budget_team=True)}
        SELECT
          {trunc_bud} AS bucket_start,
          COALESCE(SUM(budget."Revenue Budget"), 0)::numeric AS budget_revenue,
          COALESCE(SUM(budget."Profit Budget"),  0)::numeric AS budget_profit,
          COALESCE(SUM(budget."Loads Budget"),   0)::numeric AS budget_loads
        FROM public.daily_production_budget_report budget
        LEFT JOIN budget_team ct ON TRIM(budget."Customer Name") = ct.customer_name
        WHERE budget."Date" BETWEEN $1 AND $2
        {bud_extra}
        GROUP BY 1
    """

    # ---- Projected — Bruno (PDF 2026-08-14) R6 ---------------------------
    # Was its own 14-calendar-day / 14 formula, which read $2,121,651 against
    # the Team Monthly Projection panel's $2,301,182 on the same screen. Now
    # the identical helper, so the chart's reference line and the panel can no
    # longer disagree.
    m_start, m_end = _month_bounds(today)
    pending_workdays = _count_workdays(today, m_end)

    prod_rows, bud_rows, proj = await asyncio.gather(
        pool.fetch(prod_sql, *prod_params),
        pool.fetch(bud_sql, *bud_params) if scope.has_budget else _empty_rows(),
        _team_projection_core(
            pool, team=team, customer=customer, load_type=load_type,
            lanes=lanes, exclude_lanes=exclude_lanes,
            carriers=carriers, exclude_carriers=exclude_carriers, today=today, scope=scope,
        ),
    )

    prod_map = {r["bucket_start"]: r for r in prod_rows}
    bud_map = {r["bucket_start"]: r for r in bud_rows}

    projected_vol        = proj["proj_volume"]
    projected_revenue    = proj["proj_revenue"]
    projected_profit     = proj["proj_profit"]
    projected_margin_pct = proj["proj_margin_pct"]

    out = []
    for a in anchors:
        p = prod_map.get(a)
        b = bud_map.get(a)
        p_rev   = _safe_float(p["revenue"]) if p else 0.0
        p_prof  = _safe_float(p["profit"])  if p else 0.0
        l_rev   = _safe_float(p["losses_rev"])  if p else 0.0
        l_prof  = _safe_float(p["losses_prof"]) if p else 0.0
        b_rev   = _safe_float(b["budget_revenue"]) if b else 0.0
        b_prof  = _safe_float(b["budget_profit"])  if b else 0.0
        out.append({
            "bucket_start": a.isoformat(),
            "volume":     int(p["volume"]) if p else 0,
            "revenue":    p_rev,
            "profit":     p_prof,
            "margin_pct": (p_prof / p_rev * 100.0) if p_rev else 0.0,
            # Per-tab losses variants (Bruno round 3).
            "losses_vol":        int(p["losses_vol"]) if p else 0,
            "losses_rev":        l_rev,
            "losses_prof":       l_prof,
            "losses_margin_pct": (l_prof / l_rev * 100.0) if l_rev else 0.0,
            # Per-tab budget variants.
            "budget_loads":      _safe_float(b["budget_loads"]) if b else 0.0,
            "budget_revenue":    b_rev,
            "budget_profit":     b_prof,
            "budget_margin_pct": (b_prof / b_rev * 100.0) if b_rev else 0.0,
        })

    return {
        "success": True,
        "data": {
            "grain": grain,
            "buckets": out,
            "projected_vol":        _safe_float(projected_vol),
            "projected_revenue":    _safe_float(projected_revenue),
            "projected_profit":     _safe_float(projected_profit),
            "projected_margin_pct": _safe_float(projected_margin_pct),
            "today": today.isoformat(),
            "month_start": m_start.isoformat(),
            "month_end": m_end.isoformat(),
            "pending_workdays": pending_workdays,
        },
    }


# ---------------------------------------------------------------------------
# /service — Bruno R4 (2026-05-27) per-bucket OTP / OTD time series
# ---------------------------------------------------------------------------


@router.get("/service")
async def service(
    request: Request,
    team: Optional[str] = Query(None),
    customer: Optional[str] = Query(None),
    load_type: Optional[str] = Query(None),
    lanes: Optional[List[str]] = Query(None),
    exclude_lanes: Optional[List[str]] = Query(None),
    # Bruno (PDF 2026-07-15) R1: Carrier multi-select (Include/Exclude).
    carriers: Optional[List[str]] = Query(None),
    exclude_carriers: Optional[List[str]] = Query(None),
    grain: str = Query("month", description="'day' | 'week' | 'month'"),
    _user: dict = Depends(require_report_access("ops-portal-overview")),
):
    """Second "KPI MANAGEMENT" chart ("Service") — OTP% / OTD% over the grain.

    Same Day/Week/Month window model as /combo. OTP%/OTD% per bucket use the
    same scorecard-late formula as /team-performance:
      otp_pct = (1 - SUM(otp_late) / volume) * 100
    """
    if grain not in ("day", "week", "month"):
        grain = "month"
    pool = get_datalake_gold_pool(request)
    scope = scope_of(request)
    today = cst_today()
    win_start, win_end, anchors = _resolve_grain_window(grain, today)

    trunc_v4 = {
        "day":   "br4.origin_actual_departure::date",
        "week":  "DATE_TRUNC('week', br4.origin_actual_departure)::date",
        "month": "DATE_TRUNC('month', br4.origin_actual_departure)::date",
    }[grain]

    params: list = []
    where = _v4_scope_where("br4", team, customer, load_type, params, lanes, exclude_lanes, carriers, exclude_carriers, scope=scope)
    params.extend([win_start, win_end])
    p_ws = len(params) - 1
    p_we = len(params)
    sql = f"""
        WITH otp AS ({_scorecard_cte("otp", scope)}),
             otd AS ({_scorecard_cte("otd", scope)}),
             prod AS (
                SELECT {trunc_v4} AS bucket_start,
                       br4.total_charge,
                       COALESCE(otp.scorecard_count_otp, 0) AS otp_cnt,
                       COALESCE(otd.scorecard_count_otd, 0) AS otd_cnt
                FROM public.mcleod_gld_budget_report_v4 br4
                LEFT JOIN otp ON TRIM(br4.id)=otp.id_key AND TRIM(br4.company_id)=otp.company_id_key
                LEFT JOIN otd ON TRIM(br4.id)=otd.id_key AND TRIM(br4.company_id)=otd.company_id_key
                WHERE {where}
                  AND br4.origin_actual_departure >= ${p_ws}
                  AND br4.origin_actual_departure < (${p_we}::date + INTERVAL '1 day')
             )
        SELECT
          bucket_start,
          COUNT(*) FILTER (WHERE total_charge IS NOT NULL AND total_charge <> 0) AS volume,
          SUM(otp_cnt) AS otp_late,
          SUM(otd_cnt) AS otd_late
        FROM prod
        GROUP BY bucket_start
    """
    rows = await pool.fetch(sql, *params)
    by_bucket = {r["bucket_start"]: r for r in rows}

    out = []
    for a in anchors:
        r = by_bucket.get(a)
        vol = int(r["volume"]) if r else 0
        otp_late = int(r["otp_late"] or 0) if r else 0
        otd_late = int(r["otd_late"] or 0) if r else 0
        out.append({
            "bucket_start": a.isoformat(),
            "volume": vol,
            "otp_pct": _safe_float((1.0 - otp_late / vol) * 100.0 if vol else 0.0),
            "otd_pct": _safe_float((1.0 - otd_late / vol) * 100.0 if vol else 0.0),
            "lates_pu": otp_late,
            "lates_del": otd_late,
        })

    return {
        "success": True,
        "data": {"grain": grain, "buckets": out, "today": today.isoformat()},
    }


# ---------------------------------------------------------------------------
# /cover-forecast — Bruno (PDF 2026-07-30) R4: the "Forecast" pill in KPI
# Management. Per-bucket Cover totals that stack on top of the Production bars.
# ---------------------------------------------------------------------------


@router.get("/cover-forecast")
async def cover_forecast(
    request: Request,
    team: Optional[str] = Query(None),
    customer: Optional[str] = Query(None),
    load_type: Optional[str] = Query(None, description="'contract' | 'spot' | null"),
    lanes: Optional[List[str]] = Query(None),
    exclude_lanes: Optional[List[str]] = Query(None),
    carriers: Optional[List[str]] = Query(None),
    exclude_carriers: Optional[List[str]] = Query(None),
    grain: str = Query("month", description="'day' | 'week' | 'month'"),
    _user: dict = Depends(require_report_access("ops-portal-overview")),
):
    """Cover volume / revenue / profit bucketed on ``orig_sched_arrive_late``.

    Bruno (PDF 2026-07-30) R4: KPI Management gains a "Forecast" pill that shows
    Production + Cover as one cumulative bar. This endpoint supplies only the
    Cover half — the frontend stacks it on the ``/combo`` bars — so the default
    (Forecast off) page load is completely unchanged.

    Design notes (verified against the datalake 2026-07-30):

    * **"Cover" means carrier-assigned**, matching the Cover board since Bruno's
      2026-07-23 R1 (the uncovered rows are Pending to Cover): 100 of the 166
      CORP status='A' loads.
    * **No double-counting.** ``/combo``'s bars run over ``_v4_scope_where``,
      which pins ``status = ANY(('D','P'))``. ``status='A'`` is disjoint from
      that universe, so Production + Cover never counts an order twice. That
      same pin is why the scope is rebuilt inline here instead of reusing the
      helper — as in /cover and /pending-to-cover.
    * **Bucketed on ``orig_sched_arrive_late``** per Bruno, not on
      ``origin_actual_departure`` (an open load has no actual departure). The
      column is populated on 94.6% of status='A' rows; the remainder cannot be
      placed on a timeline and are dropped by the ``IS NOT NULL`` guard.
    * **Buckets run into the future** — 28 of the 100 covered loads sit in the
      month *after* today. ``/combo``'s anchor list stops at the current period,
      so the frontend appends any forecast-only bucket rather than inner-joining
      (which would silently swallow them).
    * ``cover_vol`` mirrors ``/combo``'s volume rule (``total_charge`` non-null
      and non-zero) so the Vol. stack is apples-to-apples; that excludes exactly
      1 of the 100 rows today.
    """
    if grain not in ("day", "week", "month"):
        grain = "month"
    pool = get_datalake_gold_pool(request)
    scope = scope_of(request)

    teams_param = _pad_variants(scope.base_teams, width=8)
    companies_param = _pad_variants(CORP_COMPANIES, width=4)
    status_param = _pad_variants(("A",), width=1)
    params: list = [teams_param, companies_param, status_param]
    parts = [
        "br4.team_id    = ANY($1)",
        "br4.company_id = ANY($2)",
        "br4.status     = ANY($3)",
        "UPPER(COALESCE(br4.customer_name,'')) NOT LIKE '%OILTEX%'",
    ]
    if team:
        params.append(_sub_team_param(scope, [team]))
        parts.append(f"br4.{scope.v4_team_col} = ANY(${len(params)})")
    if customer:
        params.append(customer)
        parts.append(f"br4.customer_name = ${len(params)}")
    if load_type and load_type.lower() in ("contract", "spot"):
        params.append(load_type.lower())
        parts.append(f"LOWER(TRIM(COALESCE(br4.contract_type_descr,''))) = ${len(params)}")
    if lanes:
        params.append(lanes)
        parts.append(f"{_lane_expr('br4')} = ANY(${len(params)})")
    if exclude_lanes:
        params.append(exclude_lanes)
        parts.append(f"{_lane_expr('br4')} <> ALL(${len(params)})")
    if carriers:
        params.append(carriers)
        parts.append(f"{_carrier_first_expr('br4')} = ANY(${len(params)})")
    if exclude_carriers:
        params.append(exclude_carriers)
        parts.append(f"{_carrier_first_expr('br4')} <> ALL(${len(params)})")
    where = " AND ".join(parts)

    trunc = {
        "day":   "win.arrive_late::date",
        "week":  "DATE_TRUNC('week', win.arrive_late)::date",
        "month": "DATE_TRUNC('month', win.arrive_late)::date",
    }[grain]

    sql = f"""
        SELECT
          {trunc} AS bucket_start,
          COUNT(*) FILTER (WHERE br4.total_charge IS NOT NULL AND br4.total_charge <> 0) AS cover_vol,
          COALESCE(SUM(br4.total_charge), 0)::numeric AS cover_rev,
          COALESCE(SUM(br4.margin_amt), 0)::numeric   AS cover_prof
        FROM public.mcleod_gld_budget_report_v4 br4
        LEFT JOIN LATERAL (
            SELECT MAX(CASE WHEN cw.orig_sched_arrive_late > '2000-01-01' THEN cw.orig_sched_arrive_late END) AS arrive_late
            FROM public.mcleod_gld_customer_windows cw
            WHERE TRIM(UPPER(cw.id)) = TRIM(UPPER(br4.id))
        ) win ON TRUE
        LEFT JOIN LATERAL (
            SELECT m.payee_name
            FROM public.mcleod_gld_movement m
            WHERE m.order_id = br4.id AND m.company_id = br4.company_id
            ORDER BY m.movement_id ASC
            LIMIT 1
        ) mov ON TRUE
        WHERE {where}
          AND {_ASSIGNED}
        GROUP BY 1
        ORDER BY 1 NULLS LAST
    """

    rows = await pool.fetch(sql, *params)
    # Covered loads with no schedule date land in the NULL bucket. They cannot
    # be placed on a timeline, so they are split out rather than dropped
    # silently — the UI surfaces the count (SPEC-CODE-RULES §53 "no silent
    # caps"). `DATE_TRUNC(..., NULL)` is NULL, so one bucket collects them all.
    buckets = [
        {
            "bucket_start": r["bucket_start"].isoformat(),
            "cover_vol":    int(r["cover_vol"]),
            "cover_rev":    _safe_float(r["cover_rev"]),
            "cover_prof":   _safe_float(r["cover_prof"]),
        }
        for r in rows
        if r["bucket_start"] is not None
    ]
    unscheduled = next(
        (int(r["cover_vol"]) for r in rows if r["bucket_start"] is None), 0
    )
    return {
        "success": True,
        "data": {"grain": grain, "buckets": buckets, "unscheduled": unscheduled},
    }
