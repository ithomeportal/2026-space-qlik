"""Team performance panels — scope-wide, weekly and per-team.

Part of the ``ops_portal_overview`` package (split 2026-08-14 — see SPEC-CUSTOM-REPORTS §28).
"""

from __future__ import annotations

import asyncio
from datetime import date, timedelta
from typing import List, Optional

from fastapi import Depends, Query, Request

from app.clock import cst_today
from app.routers.deps import get_datalake_gold_pool, require_report_access

from ._constants import customer_team_cte, CORP_TEAMS, CUSTOMER_TEAM_CTE, YEAR_START, router
from ._dates import _resolve_range
from ._scope import scope_of
from ._sql import (
    _bill_metrics_sql,
    _parse_team_scope,
    _scorecard_cte,
    _team_id_select,
    _v4_scope_where,
)
from ._metrics import _safe_float


def _bill_fields(row) -> dict:
    """Map a billing-metrics row → the 3 R12 wire fields (0-safe)."""
    denom = int(row["del_bill_denom"] or 0) if row else 0
    le2 = int(row["del_bill_le2"] or 0) if row else 0
    return {
        "avg_days_billed":     _safe_float(row["avg_days_billed"]) if row else 0.0,
        "avg_days_not_billed": _safe_float(row["avg_days_not_billed"]) if row else 0.0,
        "pct_del_bill":        (le2 / denom * 100.0) if denom else 0.0,
    }


# ---------------------------------------------------------------------------
# /team-performance — §5 single-row team Production+Savings KPIs
# ---------------------------------------------------------------------------


@router.get("/team-performance")
async def team_performance(
    request: Request,
    range: Optional[str] = Query("mtd"),
    start_date: Optional[date] = Query(None),
    end_date: Optional[date] = Query(None),
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
    """§5 Team Monthly Performance — Production + Savings.

    Bruno's PDF had ``where margin_amt<0`` on Profit / Margin / Prof×L which
    flipped them losses-only and contradicted the $23,000 positive mock. Fix
    confirmed 2026-05-10: top-of-table Profit/Margin/Prof×L drop the filter;
    explicitly named Loads-w/-Loss and Profit-Loss rows keep it.

    ``teams`` widens the scope to several teams at once and aggregates in SQL —
    the PERFORMANCE CORP digest needs one combined row, and distinct customer
    counts, OTP/OTD and margin % cannot be recovered by adding four per-team
    responses together.
    """
    pool = get_datalake_gold_pool(request)
    scope = scope_of(request)
    s, e = _resolve_range(range, start_date, end_date)
    team_scope = _parse_team_scope(team, teams)

    # ---- Production query ------------------------------------------------
    prod_params: list = []
    where = _v4_scope_where("br4", team_scope, customer, load_type, prod_params, lanes, exclude_lanes, carriers, exclude_carriers, scope=scope)
    prod_params.extend([s, e])
    p_s = len(prod_params) - 1
    p_e = len(prod_params)

    # Distinct team count for Team Ut. — when a single team is filtered,
    # capacity = 1 × 500. Otherwise = (number of CORP teams that appear in scope).
    prod_sql = f"""
        WITH otp AS ({_scorecard_cte("otp", scope)}),
             otd AS ({_scorecard_cte("otd", scope)}),
             prod AS (
                SELECT br4.id, br4.company_id, {_team_id_select('br4', scope)}, br4.customer_name,
                       TRIM(br4.origin_name) AS origin,
                       TRIM(br4.dest_name)   AS dest,
                       br4.total_charge, br4.margin_amt, br4.total_carrier_pay,
                       COALESCE(otp.scorecard_count_otp, 0) AS otp_cnt,
                       COALESCE(otd.scorecard_count_otd, 0) AS otd_cnt
                FROM public.mcleod_gld_budget_report_v4 br4
                LEFT JOIN otp ON TRIM(br4.id)=otp.id_key AND TRIM(br4.company_id)=otp.company_id_key
                LEFT JOIN otd ON TRIM(br4.id)=otd.id_key AND TRIM(br4.company_id)=otd.company_id_key
                WHERE {where}
                  AND br4.origin_actual_departure >= ${p_s}
                  AND br4.origin_actual_departure < (${p_e}::date + INTERVAL '1 day')
             )
        SELECT
          COUNT(DISTINCT customer_name) AS customers,
          COUNT(DISTINCT (origin || ' - ' || dest))
            FILTER (WHERE origin <> '' AND dest <> '') AS lanes,
          COUNT(*) FILTER (WHERE total_charge IS NOT NULL AND total_charge <> 0) AS volume,
          COALESCE(SUM(total_charge), 0)::numeric AS revenue,
          -- Bruno R5 (2026-06-01): Total Cost between Revenue and Profit.
          COALESCE(SUM(total_carrier_pay), 0)::numeric AS total_cost,
          COALESCE(SUM(margin_amt),  0)::numeric AS profit,
          COUNT(*) FILTER (WHERE margin_amt < 0
                             AND total_charge IS NOT NULL
                             AND total_charge <> 0) AS loss_loads,
          COALESCE(SUM(margin_amt) FILTER (WHERE margin_amt < 0), 0)::numeric AS profit_loss,
          SUM(otp_cnt) AS otp_late_sum,
          SUM(otd_cnt) AS otd_late_sum,
          COUNT(DISTINCT team_id) AS team_count
        FROM prod
    """

    # ---- Savings query (variance>0 = savings, variance<0 = over-pay) -----
    sav_params: list = [s, e]
    sav_extra = " AND UPPER(COALESCE(cs.customer_name,'')) NOT LIKE '%OILTEX%'"
    if customer:
        sav_params.append(customer)
        sav_extra += f" AND cs.customer_name = ${len(sav_params)}"
    # ct.team_id comes out of CUSTOMER_TEAM_CTE already TRIMmed, so these are
    # plain ids — no pad_variants here (unlike the v4 predicate above).
    if team_scope:
        sav_params.append(team_scope)
        sav_extra += f" AND ct.team_id = ANY(${len(sav_params)})"
    sav_sql = f"""
        WITH {customer_team_cte(scope)}
        SELECT
          COALESCE(SUM(CASE WHEN cs.variance > 0 THEN cs.variance ELSE 0 END), 0)::numeric AS total_savings,
          COALESCE(SUM(CASE WHEN cs.variance < 0 THEN cs.variance ELSE 0 END), 0)::numeric AS total_overpay,
          COALESCE(SUM(cs.variance), 0)::numeric AS net_savings
        FROM public.carriers_savings_results_report cs
        JOIN customer_team ct ON TRIM(cs.customer_name) = ct.customer_name
        WHERE cs.month_date BETWEEN $1 AND $2
        {sav_extra}
    """

    # ---- Attrition (mirrors xray-corp /attrition) — last-load freshness --
    # Customer attrition % = customers with last_load > 30d / customers total
    # Lane attrition % = lanes with last_load > 30d / lanes total
    attr_params: list = []
    where_attr = _v4_scope_where("br4", team_scope, customer, load_type, attr_params, lanes, exclude_lanes, carriers, exclude_carriers, scope=scope)
    attr_params.append(YEAR_START)
    p_ys = len(attr_params)
    attr_sql = f"""
        WITH lane_last AS (
            SELECT br4.customer_name,
                   TRIM(br4.origin_name) AS origin,
                   TRIM(br4.dest_name)   AS dest,
                   MAX(br4.origin_actual_departure)::date AS last_load
            FROM public.mcleod_gld_budget_report_v4 br4
            WHERE {where_attr}
              AND br4.origin_actual_departure >= ${p_ys}
              AND br4.customer_name IS NOT NULL
              AND TRIM(br4.origin_name) <> ''
              AND TRIM(br4.dest_name)   <> ''
            GROUP BY br4.customer_name, TRIM(br4.origin_name), TRIM(br4.dest_name)
        ),
        cust_last AS (
            SELECT customer_name, MAX(last_load) AS last_load
            FROM lane_last
            GROUP BY customer_name
        )
        SELECT
          (SELECT COUNT(*) FROM cust_last)                                          AS cust_total,
          (SELECT COUNT(*) FROM cust_last WHERE (CURRENT_DATE - last_load) > 30)    AS cust_attr,
          (SELECT COUNT(*) FROM lane_last)                                          AS lane_total,
          (SELECT COUNT(*) FROM lane_last WHERE (CURRENT_DATE - last_load) > 30)    AS lane_attr
    """

    # ---- Billing (Bruno round 2026-07-01 R12) — bill_date on v4 + dest_actual_
    # departure/arrival from customer_windows (same sources as By Order R11, so
    # the panel reconciles with the Days-to-Bill column). See _bill_sql().
    bill_params: list = []
    where_bill = _v4_scope_where("br4", team_scope, customer, load_type, bill_params, lanes, exclude_lanes, carriers, exclude_carriers, scope=scope)
    bill_params.extend([s, e])
    b_s = len(bill_params) - 1
    b_e = len(bill_params)
    bill_sql = _bill_metrics_sql(where_bill, b_s, b_e, group_by_team=False, scope=scope)

    prod_row, sav_row, attr_row, bill_row = await asyncio.gather(
        pool.fetchrow(prod_sql, *prod_params),
        pool.fetchrow(sav_sql, *sav_params),
        pool.fetchrow(attr_sql, *attr_params),
        pool.fetchrow(bill_sql, *bill_params),
    )

    revenue = _safe_float(prod_row["revenue"])
    profit  = _safe_float(prod_row["profit"])
    volume  = int(prod_row["volume"] or 0)
    team_count = int(prod_row["team_count"] or 0) or (len(team_scope) or len(scope.sub_teams))
    capacity = 500 * team_count
    otp_late = int(prod_row["otp_late_sum"] or 0)
    otd_late = int(prod_row["otd_late_sum"] or 0)
    cust_total = int(attr_row["cust_total"] or 0)
    lane_total = int(attr_row["lane_total"] or 0)

    return {
        "success": True,
        "data": {
            "customers":  int(prod_row["customers"] or 0),
            "lanes":      int(prod_row["lanes"] or 0),
            "volume":     volume,
            "revenue":    revenue,
            "total_cost": _safe_float(prod_row["total_cost"]),
            "profit":     profit,
            "margin_pct": (profit / revenue * 100.0) if revenue else 0.0,
            "rev_x_l":    (revenue / volume) if volume else 0.0,
            "prof_x_l":   (profit  / volume) if volume else 0.0,
            "team_ut":    (volume / capacity * 100.0) if capacity else 0.0,
            "otp_pct":    (1.0 - otp_late / volume) * 100.0 if volume else 0.0,
            "lates_pu":   otp_late,
            "otd_pct":    (1.0 - otd_late / volume) * 100.0 if volume else 0.0,
            "lates_del":  otd_late,
            "savings":    _safe_float(sav_row["total_savings"]),
            "over_pay":   _safe_float(sav_row["total_overpay"]),
            "net_savings": _safe_float(sav_row["net_savings"]),
            "loss_loads":  int(prod_row["loss_loads"] or 0),
            "profit_loss": _safe_float(prod_row["profit_loss"]),
            # Bruno round (2026-07-01) R12 — below Profit Loss.
            **_bill_fields(bill_row),
            "cust_attr_pct": (int(attr_row["cust_attr"] or 0) / cust_total * 100.0) if cust_total else 0.0,
            "lane_attr_pct": (int(attr_row["lane_attr"] or 0) / lane_total * 100.0) if lane_total else 0.0,
            "window": {"start": s.isoformat(), "end": e.isoformat()},
        },
    }


# ---------------------------------------------------------------------------
# /team-weekly-performance — Bruno R4 (2026-05-27): "+" modal, last 5 weeks
# ---------------------------------------------------------------------------


@router.get("/team-weekly-performance")
async def team_weekly_performance(
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
    """Same KPI set as §5 Team Monthly Performance, split into the last 5
    Mon-Sun weeks (current week included).

    Three grouped queries (not five fan-outs) keep it inside the small
    datalake pool: production grouped by ISO week, savings grouped by ISO
    week (a month's savings lands in the week containing the 1st — matches
    Bruno's mock), and one window-independent attrition query (its value is
    identical across all weeks, as the PDF shows: 18% / 61.6% repeated).

    Team Ut. uses the same capacity formula as the monthly panel —
    volume / (500 × distinct active teams) — verified against the mock
    (289 / 2000 = 14.45%).
    """
    pool = get_datalake_gold_pool(request)
    scope = scope_of(request)
    today = cst_today()
    this_mon = today - timedelta(days=today.weekday())
    week_starts = [this_mon - timedelta(weeks=k) for k in range(4, -1, -1)]
    weeks_start = week_starts[0]
    weeks_end = week_starts[-1] + timedelta(days=6)

    def _wk(d: date) -> date:
        return d - timedelta(days=d.weekday())

    def _label(ws: date) -> str:
        we = ws + timedelta(days=6)
        return f"{ws.day:02d}/{ws.month:02d} - {we.day:02d}/{we.month:02d}"

    # ---- Production grouped by ISO week ---------------------------------
    prod_params: list = []
    where = _v4_scope_where("br4", team, customer, load_type, prod_params, lanes, exclude_lanes, carriers, exclude_carriers, scope=scope)
    prod_params.extend([weeks_start, weeks_end])
    p_s = len(prod_params) - 1
    p_e = len(prod_params)
    prod_sql = f"""
        WITH otp AS ({_scorecard_cte("otp", scope)}),
             otd AS ({_scorecard_cte("otd", scope)}),
             prod AS (
                SELECT DATE_TRUNC('week', br4.origin_actual_departure)::date AS wk,
                       br4.id, {_team_id_select('br4', scope)}, br4.customer_name,
                       TRIM(br4.origin_name) AS origin,
                       TRIM(br4.dest_name)   AS dest,
                       br4.total_charge, br4.margin_amt, br4.total_carrier_pay,
                       COALESCE(otp.scorecard_count_otp, 0) AS otp_cnt,
                       COALESCE(otd.scorecard_count_otd, 0) AS otd_cnt
                FROM public.mcleod_gld_budget_report_v4 br4
                LEFT JOIN otp ON TRIM(br4.id)=otp.id_key AND TRIM(br4.company_id)=otp.company_id_key
                LEFT JOIN otd ON TRIM(br4.id)=otd.id_key AND TRIM(br4.company_id)=otd.company_id_key
                WHERE {where}
                  AND br4.origin_actual_departure >= ${p_s}
                  AND br4.origin_actual_departure < (${p_e}::date + INTERVAL '1 day')
             )
        SELECT
          wk,
          COUNT(DISTINCT customer_name) AS customers,
          COUNT(DISTINCT (origin || ' - ' || dest))
            FILTER (WHERE origin <> '' AND dest <> '') AS lanes,
          COUNT(*) FILTER (WHERE total_charge IS NOT NULL AND total_charge <> 0) AS volume,
          COALESCE(SUM(total_charge), 0)::numeric AS revenue,
          COALESCE(SUM(total_carrier_pay), 0)::numeric AS total_cost,
          COALESCE(SUM(margin_amt),  0)::numeric AS profit,
          COUNT(*) FILTER (WHERE margin_amt < 0
                             AND total_charge IS NOT NULL
                             AND total_charge <> 0) AS loss_loads,
          COALESCE(SUM(margin_amt) FILTER (WHERE margin_amt < 0), 0)::numeric AS profit_loss,
          SUM(otp_cnt) AS otp_late,
          SUM(otd_cnt) AS otd_late,
          COUNT(DISTINCT team_id) AS team_count
        FROM prod
        GROUP BY wk
    """

    # ---- Savings grouped by ISO week ------------------------------------
    sav_params: list = [weeks_start, weeks_end]
    sav_extra = " AND UPPER(COALESCE(cs.customer_name,'')) NOT LIKE '%OILTEX%'"
    if customer:
        sav_params.append(customer)
        sav_extra += f" AND cs.customer_name = ${len(sav_params)}"
    if team:
        sav_params.append(team)
        sav_extra += f" AND ct.team_id = ${len(sav_params)}"
    sav_sql = f"""
        WITH {customer_team_cte(scope)}
        SELECT
          DATE_TRUNC('week', cs.month_date)::date AS wk,
          COALESCE(SUM(CASE WHEN cs.variance > 0 THEN cs.variance ELSE 0 END), 0)::numeric AS savings,
          COALESCE(SUM(CASE WHEN cs.variance < 0 THEN cs.variance ELSE 0 END), 0)::numeric AS over_pay,
          COALESCE(SUM(cs.variance), 0)::numeric AS net_savings
        FROM public.carriers_savings_results_report cs
        JOIN customer_team ct ON TRIM(cs.customer_name) = ct.customer_name
        WHERE cs.month_date BETWEEN $1 AND $2
        {sav_extra}
        GROUP BY DATE_TRUNC('week', cs.month_date)::date
    """

    # ---- Attrition (window-independent, identical across weeks) ----------
    attr_params: list = []
    where_attr = _v4_scope_where("br4", team, customer, load_type, attr_params, lanes, exclude_lanes, carriers, exclude_carriers, scope=scope)
    attr_params.append(YEAR_START)
    p_ys = len(attr_params)
    attr_sql = f"""
        WITH lane_last AS (
            SELECT br4.customer_name,
                   TRIM(br4.origin_name) AS origin,
                   TRIM(br4.dest_name)   AS dest,
                   MAX(br4.origin_actual_departure)::date AS last_load
            FROM public.mcleod_gld_budget_report_v4 br4
            WHERE {where_attr}
              AND br4.origin_actual_departure >= ${p_ys}
              AND br4.customer_name IS NOT NULL
              AND TRIM(br4.origin_name) <> ''
              AND TRIM(br4.dest_name)   <> ''
            GROUP BY br4.customer_name, TRIM(br4.origin_name), TRIM(br4.dest_name)
        ),
        cust_last AS (
            SELECT customer_name, MAX(last_load) AS last_load
            FROM lane_last GROUP BY customer_name
        )
        SELECT
          (SELECT COUNT(*) FROM cust_last)                                       AS cust_total,
          (SELECT COUNT(*) FROM cust_last WHERE (CURRENT_DATE - last_load) > 30) AS cust_attr,
          (SELECT COUNT(*) FROM lane_last)                                       AS lane_total,
          (SELECT COUNT(*) FROM lane_last WHERE (CURRENT_DATE - last_load) > 30) AS lane_attr
    """

    prod_rows, sav_rows, attr_row = await asyncio.gather(
        pool.fetch(prod_sql, *prod_params),
        pool.fetch(sav_sql, *sav_params),
        pool.fetchrow(attr_sql, *attr_params),
    )

    prod_map = {_wk(r["wk"]): r for r in prod_rows}
    sav_map = {_wk(r["wk"]): r for r in sav_rows}
    cust_total = int(attr_row["cust_total"] or 0) if attr_row else 0
    lane_total = int(attr_row["lane_total"] or 0) if attr_row else 0
    cust_attr_pct = (int(attr_row["cust_attr"] or 0) / cust_total * 100.0) if cust_total else 0.0
    lane_attr_pct = (int(attr_row["lane_attr"] or 0) / lane_total * 100.0) if lane_total else 0.0

    weeks = []
    for ws in week_starts:
        p = prod_map.get(ws)
        sv = sav_map.get(ws)
        volume = int(p["volume"] or 0) if p else 0
        revenue = _safe_float(p["revenue"]) if p else 0.0
        profit = _safe_float(p["profit"]) if p else 0.0
        otp_late = int(p["otp_late"] or 0) if p else 0
        otd_late = int(p["otd_late"] or 0) if p else 0
        team_count = (int(p["team_count"] or 0) if p else 0) or (1 if team else len(scope.sub_teams))
        capacity = 500 * team_count
        weeks.append({
            "start": ws.isoformat(),
            "end": (ws + timedelta(days=6)).isoformat(),
            "label": _label(ws),
            "customers":  int(p["customers"] or 0) if p else 0,
            "lanes":      int(p["lanes"] or 0) if p else 0,
            "volume":     volume,
            "revenue":    revenue,
            "total_cost": _safe_float(p["total_cost"]) if p else 0.0,
            "profit":     profit,
            "margin_pct": _safe_float((profit / revenue * 100.0) if revenue else 0.0),
            "rev_x_l":    _safe_float((revenue / volume) if volume else 0.0),
            "prof_x_l":   _safe_float((profit / volume) if volume else 0.0),
            "team_ut":    _safe_float((volume / capacity * 100.0) if capacity else 0.0),
            "otp_pct":    _safe_float((1.0 - otp_late / volume) * 100.0 if volume else 0.0),
            "lates_pu":   otp_late,
            "otd_pct":    _safe_float((1.0 - otd_late / volume) * 100.0 if volume else 0.0),
            "lates_del":  otd_late,
            "savings":    _safe_float(sv["savings"]) if sv else 0.0,
            "over_pay":   _safe_float(sv["over_pay"]) if sv else 0.0,
            "net_savings": _safe_float(sv["net_savings"]) if sv else 0.0,
            "loss_loads":  int(p["loss_loads"] or 0) if p else 0,
            "profit_loss": _safe_float(p["profit_loss"]) if p else 0.0,
            "cust_attr_pct": _safe_float(cust_attr_pct),
            "lane_attr_pct": _safe_float(lane_attr_pct),
        })

    return {"success": True, "data": {"weeks": weeks}}


# ---------------------------------------------------------------------------
# /team-performance-by-team — §5 split per CORP team (TEAM1..TEAM5) + Total
# ---------------------------------------------------------------------------


def _team_perf_obj(
    *,
    customers: int,
    lanes: int,
    volume: int,
    revenue: float,
    total_cost: float,
    profit: float,
    loss_loads: int,
    profit_loss: float,
    otp_late: int,
    otd_late: int,
    team_count: int,
    savings: float,
    over_pay: float,
    net_savings: float,
    cust_total: int,
    cust_attr: int,
    lane_total: int,
    lane_attr: int,
    avg_days_billed: float = 0.0,
    avg_days_not_billed: float = 0.0,
    pct_del_bill: float = 0.0,
) -> dict:
    """Build one §5 row from raw aggregates — shared by every team + Total so
    every TeamPerf object carries the exact same field set as /team-performance.
    """
    capacity = 500 * (team_count or 0)
    return {
        "customers":  customers,
        "lanes":      lanes,
        "volume":     volume,
        "revenue":    _safe_float(revenue),
        "total_cost": _safe_float(total_cost),
        "profit":     _safe_float(profit),
        "margin_pct": _safe_float((profit / revenue * 100.0) if revenue else 0.0),
        "rev_x_l":    _safe_float((revenue / volume) if volume else 0.0),
        "prof_x_l":   _safe_float((profit / volume) if volume else 0.0),
        "team_ut":    _safe_float((volume / capacity * 100.0) if capacity else 0.0),
        "otp_pct":    _safe_float((1.0 - otp_late / volume) * 100.0 if volume else 0.0),
        "lates_pu":   otp_late,
        "otd_pct":    _safe_float((1.0 - otd_late / volume) * 100.0 if volume else 0.0),
        "lates_del":  otd_late,
        "savings":    _safe_float(savings),
        "over_pay":   _safe_float(over_pay),
        "net_savings": _safe_float(net_savings),
        "loss_loads":  loss_loads,
        "profit_loss": _safe_float(profit_loss),
        # Bruno round (2026-07-01) R12 — below Profit Loss.
        "avg_days_billed":     _safe_float(avg_days_billed),
        "avg_days_not_billed": _safe_float(avg_days_not_billed),
        "pct_del_bill":        _safe_float(pct_del_bill),
        "cust_attr_pct": _safe_float((cust_attr / cust_total * 100.0) if cust_total else 0.0),
        "lane_attr_pct": _safe_float((lane_attr / lane_total * 100.0) if lane_total else 0.0),
    }


@router.get("/team-performance-by-team")
async def team_performance_by_team(
    request: Request,
    range: Optional[str] = Query("mtd"),
    start_date: Optional[date] = Query(None),
    end_date: Optional[date] = Query(None),
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
    """§5 Team Monthly Performance split per CORP team (TEAM1..TEAM5) + a Total.

    Same field set as /team-performance, computed once per team_id in a single
    grouped scan (production grouped by team_id, savings grouped by canonical
    team_id, attrition grouped by team_id) plus a window-wide Total. The single
    ``team`` filter is intentionally ignored — this panel always returns all
    CORP teams; ``customer`` / date / lane filters still apply.
    """
    pool = get_datalake_gold_pool(request)
    scope = scope_of(request)
    s, e = _resolve_range(range, start_date, end_date)

    # ---- Production grouped by team_id (team filter intentionally dropped) --
    prod_params: list = []
    where = _v4_scope_where("br4", None, customer, load_type, prod_params, lanes, exclude_lanes, carriers, exclude_carriers, scope=scope)
    prod_params.extend([s, e])
    p_s = len(prod_params) - 1
    p_e = len(prod_params)
    prod_sql = f"""
        WITH otp AS ({_scorecard_cte("otp", scope)}),
             otd AS ({_scorecard_cte("otd", scope)}),
             prod AS (
                SELECT TRIM(br4.{scope.v4_team_col}) AS team_id,
                       br4.id, br4.customer_name,
                       TRIM(br4.origin_name) AS origin,
                       TRIM(br4.dest_name)   AS dest,
                       br4.total_charge, br4.margin_amt, br4.total_carrier_pay,
                       COALESCE(otp.scorecard_count_otp, 0) AS otp_cnt,
                       COALESCE(otd.scorecard_count_otd, 0) AS otd_cnt
                FROM public.mcleod_gld_budget_report_v4 br4
                LEFT JOIN otp ON TRIM(br4.id)=otp.id_key AND TRIM(br4.company_id)=otp.company_id_key
                LEFT JOIN otd ON TRIM(br4.id)=otd.id_key AND TRIM(br4.company_id)=otd.company_id_key
                WHERE {where}
                  AND br4.origin_actual_departure >= ${p_s}
                  AND br4.origin_actual_departure < (${p_e}::date + INTERVAL '1 day')
             )
        SELECT
          team_id,
          COUNT(DISTINCT customer_name) AS customers,
          COUNT(DISTINCT (origin || ' - ' || dest))
            FILTER (WHERE origin <> '' AND dest <> '') AS lanes,
          COUNT(*) FILTER (WHERE total_charge IS NOT NULL AND total_charge <> 0) AS volume,
          COALESCE(SUM(total_charge), 0)::numeric AS revenue,
          COALESCE(SUM(total_carrier_pay), 0)::numeric AS total_cost,
          COALESCE(SUM(margin_amt),  0)::numeric AS profit,
          COUNT(*) FILTER (WHERE margin_amt < 0
                             AND total_charge IS NOT NULL
                             AND total_charge <> 0) AS loss_loads,
          COALESCE(SUM(margin_amt) FILTER (WHERE margin_amt < 0), 0)::numeric AS profit_loss,
          SUM(otp_cnt) AS otp_late,
          SUM(otd_cnt) AS otd_late
        FROM prod
        GROUP BY team_id
    """

    # ---- Savings grouped by canonical team_id ---------------------------
    sav_params: list = [s, e]
    sav_extra = " AND UPPER(COALESCE(cs.customer_name,'')) NOT LIKE '%OILTEX%'"
    if customer:
        sav_params.append(customer)
        sav_extra += f" AND cs.customer_name = ${len(sav_params)}"
    sav_sql = f"""
        WITH {customer_team_cte(scope)}
        SELECT
          ct.team_id AS team_id,
          COALESCE(SUM(CASE WHEN cs.variance > 0 THEN cs.variance ELSE 0 END), 0)::numeric AS savings,
          COALESCE(SUM(CASE WHEN cs.variance < 0 THEN cs.variance ELSE 0 END), 0)::numeric AS over_pay,
          COALESCE(SUM(cs.variance), 0)::numeric AS net_savings
        FROM public.carriers_savings_results_report cs
        JOIN customer_team ct ON TRIM(cs.customer_name) = ct.customer_name
        WHERE cs.month_date BETWEEN $1 AND $2
        {sav_extra}
        GROUP BY ct.team_id
    """

    # ---- Attrition grouped by team_id (and rolled up for Total) ----------
    attr_params: list = []
    where_attr = _v4_scope_where("br4", None, customer, load_type, attr_params, lanes, exclude_lanes, carriers, exclude_carriers, scope=scope)
    attr_params.append(YEAR_START)
    p_ys = len(attr_params)
    attr_sql = f"""
        WITH lane_last AS (
            SELECT TRIM(br4.{scope.v4_team_col}) AS team_id,
                   br4.customer_name,
                   TRIM(br4.origin_name) AS origin,
                   TRIM(br4.dest_name)   AS dest,
                   MAX(br4.origin_actual_departure)::date AS last_load
            FROM public.mcleod_gld_budget_report_v4 br4
            WHERE {where_attr}
              AND br4.origin_actual_departure >= ${p_ys}
              AND br4.customer_name IS NOT NULL
              AND TRIM(br4.origin_name) <> ''
              AND TRIM(br4.dest_name)   <> ''
            GROUP BY TRIM(br4.{scope.v4_team_col}), br4.customer_name,
                     TRIM(br4.origin_name), TRIM(br4.dest_name)
        ),
        cust_last AS (
            SELECT team_id, customer_name, MAX(last_load) AS last_load
            FROM lane_last GROUP BY team_id, customer_name
        )
        SELECT
          c.team_id,
          (SELECT COUNT(*) FROM cust_last x WHERE x.team_id = c.team_id)                                          AS cust_total,
          (SELECT COUNT(*) FROM cust_last x WHERE x.team_id = c.team_id AND (CURRENT_DATE - x.last_load) > 30)    AS cust_attr,
          (SELECT COUNT(*) FROM lane_last l WHERE l.team_id = c.team_id)                                          AS lane_total,
          (SELECT COUNT(*) FROM lane_last l WHERE l.team_id = c.team_id AND (CURRENT_DATE - l.last_load) > 30)    AS lane_attr
        FROM (SELECT DISTINCT team_id FROM cust_last) c
    """

    # ---- Billing grouped by team_id (Bruno round 2026-07-01 R12) ---------
    bill_params: list = []
    where_bill = _v4_scope_where("br4", None, customer, load_type, bill_params, lanes, exclude_lanes, carriers, exclude_carriers, scope=scope)
    bill_params.extend([s, e])
    bt_s = len(bill_params) - 1
    bt_e = len(bill_params)
    bill_sql = _bill_metrics_sql(where_bill, bt_s, bt_e, group_by_team=True, scope=scope)

    prod_rows, sav_rows, attr_rows, bill_rows = await asyncio.gather(
        pool.fetch(prod_sql, *prod_params),
        pool.fetch(sav_sql, *sav_params),
        pool.fetch(attr_sql, *attr_params),
        pool.fetch(bill_sql, *bill_params),
    )

    prod_map = {r["team_id"]: r for r in prod_rows}
    sav_map = {r["team_id"]: r for r in sav_rows}
    attr_map = {r["team_id"]: r for r in attr_rows}
    bill_map = {r["team_id"]: r for r in bill_rows}

    teams_out = []
    tot = {
        "customers": set(), "lanes": set(), "volume": 0, "revenue": 0.0,
        "total_cost": 0.0, "profit": 0.0, "loss_loads": 0, "profit_loss": 0.0,
        "otp_late": 0, "otd_late": 0, "teams": set(), "savings": 0.0,
        "over_pay": 0.0, "net_savings": 0.0, "cust_total": 0, "cust_attr": 0,
        "lane_total": 0, "lane_attr": 0,
    }
    for tid in scope.sub_teams:
        p = prod_map.get(tid)
        sv = sav_map.get(tid)
        at = attr_map.get(tid)
        bl = bill_map.get(tid)
        volume = int(p["volume"] or 0) if p else 0
        obj = _team_perf_obj(
            customers=int(p["customers"] or 0) if p else 0,
            lanes=int(p["lanes"] or 0) if p else 0,
            volume=volume,
            revenue=_safe_float(p["revenue"]) if p else 0.0,
            total_cost=_safe_float(p["total_cost"]) if p else 0.0,
            profit=_safe_float(p["profit"]) if p else 0.0,
            loss_loads=int(p["loss_loads"] or 0) if p else 0,
            profit_loss=_safe_float(p["profit_loss"]) if p else 0.0,
            otp_late=int(p["otp_late"] or 0) if p else 0,
            otd_late=int(p["otd_late"] or 0) if p else 0,
            team_count=1 if volume else 0,
            savings=_safe_float(sv["savings"]) if sv else 0.0,
            over_pay=_safe_float(sv["over_pay"]) if sv else 0.0,
            net_savings=_safe_float(sv["net_savings"]) if sv else 0.0,
            cust_total=int(at["cust_total"] or 0) if at else 0,
            cust_attr=int(at["cust_attr"] or 0) if at else 0,
            lane_total=int(at["lane_total"] or 0) if at else 0,
            lane_attr=int(at["lane_attr"] or 0) if at else 0,
            **_bill_fields(bl),
        )
        teams_out.append({"team_id": tid, **obj})
        # Accumulate the Total over the full universe (server-side, not a
        # client reduce over a LIMIT slice — there is no limit here).
        if volume:
            tot["teams"].add(tid)
        tot["volume"] += volume
        tot["revenue"] += _safe_float(p["revenue"]) if p else 0.0
        tot["total_cost"] += _safe_float(p["total_cost"]) if p else 0.0
        tot["profit"] += _safe_float(p["profit"]) if p else 0.0
        tot["loss_loads"] += int(p["loss_loads"] or 0) if p else 0
        tot["profit_loss"] += _safe_float(p["profit_loss"]) if p else 0.0
        tot["otp_late"] += int(p["otp_late"] or 0) if p else 0
        tot["otd_late"] += int(p["otd_late"] or 0) if p else 0
        tot["savings"] += _safe_float(sv["savings"]) if sv else 0.0
        tot["over_pay"] += _safe_float(sv["over_pay"]) if sv else 0.0
        tot["net_savings"] += _safe_float(sv["net_savings"]) if sv else 0.0
        tot["cust_total"] += int(at["cust_total"] or 0) if at else 0
        tot["cust_attr"] += int(at["cust_attr"] or 0) if at else 0
        tot["lane_total"] += int(at["lane_total"] or 0) if at else 0
        tot["lane_attr"] += int(at["lane_attr"] or 0) if at else 0

    # Total: distinct customers / lanes can't be summed across teams (a customer
    # may ship on two teams), so re-read the universe-wide distinct counts.
    uni_params: list = []
    uni_where = _v4_scope_where("br4", None, customer, load_type, uni_params, lanes, exclude_lanes, carriers, exclude_carriers, scope=scope)
    uni_params.extend([s, e])
    u_s = len(uni_params) - 1
    u_e = len(uni_params)
    # Universe-wide billing for the Total column — AVGs / ratios can't be summed
    # across teams, so re-read them over the whole scope (same treatment as the
    # distinct customer/lane counts above).
    ubill_params: list = []
    ubill_where = _v4_scope_where("br4", None, customer, load_type, ubill_params, lanes, exclude_lanes, carriers, exclude_carriers, scope=scope)
    ubill_params.extend([s, e])
    ub_s = len(ubill_params) - 1
    ub_e = len(ubill_params)
    ubill_sql = _bill_metrics_sql(ubill_where, ub_s, ub_e, group_by_team=False, scope=scope)

    uni_row, ubill_row = await asyncio.gather(
        pool.fetchrow(
            f"""
            SELECT
              COUNT(DISTINCT br4.customer_name) AS customers,
              COUNT(DISTINCT (TRIM(br4.origin_name) || ' - ' || TRIM(br4.dest_name)))
                FILTER (WHERE TRIM(br4.origin_name) <> '' AND TRIM(br4.dest_name) <> '') AS lanes
            FROM public.mcleod_gld_budget_report_v4 br4
            WHERE {uni_where}
              AND br4.origin_actual_departure >= ${u_s}
              AND br4.origin_actual_departure < (${u_e}::date + INTERVAL '1 day')
            """,
            *uni_params,
        ),
        pool.fetchrow(ubill_sql, *ubill_params),
    )

    total_obj = _team_perf_obj(
        customers=int(uni_row["customers"] or 0) if uni_row else 0,
        lanes=int(uni_row["lanes"] or 0) if uni_row else 0,
        volume=tot["volume"],
        revenue=tot["revenue"],
        total_cost=tot["total_cost"],
        profit=tot["profit"],
        loss_loads=tot["loss_loads"],
        profit_loss=tot["profit_loss"],
        otp_late=tot["otp_late"],
        otd_late=tot["otd_late"],
        team_count=len(tot["teams"]) or len(scope.sub_teams),
        savings=tot["savings"],
        over_pay=tot["over_pay"],
        net_savings=tot["net_savings"],
        cust_total=tot["cust_total"],
        cust_attr=tot["cust_attr"],
        lane_total=tot["lane_total"],
        lane_attr=tot["lane_attr"],
        **_bill_fields(ubill_row),
    )

    return {
        "success": True,
        "data": {"total": total_obj, "teams": teams_out},
        "meta": {"window": {"start": s.isoformat(), "end": e.isoformat()}},
    }
