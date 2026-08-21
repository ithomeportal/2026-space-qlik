"""Actuals per customer, per lane, and the margin distribution.

Part of the ``ops_portal_overview`` package (split 2026-08-14 — see SPEC-CUSTOM-REPORTS §28).
"""

from __future__ import annotations

import asyncio
from datetime import date
from typing import List, Optional

from fastapi import Depends, Query, Request

from app.clock import cst_today
from app.routers.deps import get_datalake_gold_pool, require_report_access

from ._constants import customer_team_cte, CUSTOMER_TEAM_CTE, router
from ._dates import _count_workdays, _month_bounds, _resolve_range
from ._scope import scope_of
from ._sql import _parse_team_scope, _scorecard_cte, _v4_scope_where
from ._metrics import _empty_rows, _projection_from_sums, _projection_params, _projection_sums_sql, _safe_float, _team_projection_core


# ---------------------------------------------------------------------------
# /actuals — bottom Actuals per-customer roll-up
# ---------------------------------------------------------------------------


@router.get("/actuals")
async def actuals(
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
    sort: str = Query("revenue_desc"),
    limit: int = Query(100, ge=1, le=500),
    losses_only: bool = Query(False),
    unbilled_only: bool = Query(False),
    _user: dict = Depends(require_report_access("ops-portal-overview")),
):
    """Bottom Actuals table — per customer, stacked Production / Budget / Variance.

    Variance convention here is ``actual − budget`` (matches the Kohler MTY
    mock 133/153/-20 in Bruno's PDF). Different sign from §2/§3 — that's what
    the spec literally shows.

    Production columns come from v4 (sargable date-decode clamp on the per-row
    date columns is unnecessary because we don't return any). Budget columns
    come from daily_production_budget_report joined per customer.
    """
    pool = get_datalake_gold_pool(request)
    scope = scope_of(request)
    s, e = _resolve_range(range, start_date, end_date)
    today = cst_today()
    m_start, m_end = _month_bounds(today)
    pending_workdays = _count_workdays(today, m_end)

    # ---- Production per customer ----------------------------------------
    # Bruno R5 (2026-06-01): "Losses" button → restrict to margin_amt < 0 rows.
    # Bruno (PDF 2026-07-13): "Unbilled" button → bill_date < sentinel (never
    # billed). ANDs with Losses when both are on.
    losses_clause = " AND br4.margin_amt < 0" if losses_only else ""
    unbilled_clause = " AND br4.bill_date < '2000-01-01'::date" if unbilled_only else ""
    team_scope = _parse_team_scope(team, teams)
    p_params: list = []
    where = _v4_scope_where("br4", team_scope, customer, load_type, p_params, lanes, exclude_lanes, carriers, exclude_carriers, scope=scope)
    p_params.extend([s, e])
    p_s = len(p_params) - 1
    p_e = len(p_params)
    prod_sql = f"""
        WITH otp AS ({_scorecard_cte("otp", scope)}),
             otd AS ({_scorecard_cte("otd", scope)}),
             prod AS (
                SELECT br4.customer_name,
                       br4.id, br4.company_id, br4.total_charge, br4.margin_amt,
                       COALESCE(otp.scorecard_count_otp, 0) AS otp_cnt,
                       COALESCE(otd.scorecard_count_otd, 0) AS otd_cnt
                FROM public.mcleod_gld_budget_report_v4 br4
                LEFT JOIN otp ON TRIM(br4.id)=otp.id_key AND TRIM(br4.company_id)=otp.company_id_key
                LEFT JOIN otd ON TRIM(br4.id)=otd.id_key AND TRIM(br4.company_id)=otd.company_id_key
                WHERE {where}
                  AND br4.origin_actual_departure >= ${p_s}
                  AND br4.origin_actual_departure < (${p_e}::date + INTERVAL '1 day')
                  {losses_clause}
                  {unbilled_clause}
             )
        SELECT
          customer_name,
          COUNT(*) FILTER (WHERE total_charge IS NOT NULL AND total_charge <> 0) AS vol,
          COALESCE(SUM(total_charge), 0)::numeric AS rev,
          COALESCE(SUM(margin_amt),  0)::numeric AS prof,
          SUM(otp_cnt) AS otp_late,
          SUM(otd_cnt) AS otd_late
        FROM prod
        GROUP BY customer_name
    """

    # ---- Budget per customer --------------------------------------------
    b_params: list = [s, e]
    b_extra = ""
    # ct.team_id is the TRIMmed CUSTOMER_TEAM_CTE output — plain ids, no padding.
    if team_scope:
        b_params.append(team_scope)
        b_extra += f" AND ct.team_id = ANY(${len(b_params)})"
    if customer:
        b_params.append(customer)
        b_extra += f' AND budget."Customer Name" = ${len(b_params)}'
    bud_sql = f"""
        WITH {customer_team_cte(scope)}
        SELECT
          budget."Customer Name" AS customer_name,
          COALESCE(SUM(budget."Loads Budget"),    0)::numeric AS vol_budget,
          COALESCE(SUM(budget."Revenue Budget"),  0)::numeric AS rev_budget,
          COALESCE(SUM(budget."Profit Budget"),   0)::numeric AS prof_budget
        FROM public.daily_production_budget_report budget
        JOIN customer_team ct ON TRIM(budget."Customer Name") = ct.customer_name
        WHERE budget."Date" BETWEEN $1 AND $2
        {b_extra}
        GROUP BY budget."Customer Name"
    """

    # Bruno (PDF 2026-08-14) R6: the projection columns now use the SAME
    # 12-business-day window and divisor as Team Monthly Projection, per
    # customer, instead of "the selected window / 14". The projection is a
    # month concept, so it deliberately ignores the Date filter — that is what
    # makes the TOTAL row equal the Team Monthly Projection panel.
    proj_where, proj_params_l, proj_idx, _pending = _projection_params(
        team_scope, customer, load_type, lanes, exclude_lanes,
        carriers, exclude_carriers, today, scope=scope,
    )
    proj_by_cust_sql = _projection_sums_sql(
        proj_where, *proj_idx, group_col="br4.customer_name", scope=scope,
    )

    prod_rows, bud_rows, proj_rows, proj_all = await asyncio.gather(
        pool.fetch(prod_sql, *p_params),
        pool.fetch(bud_sql, *b_params) if scope.has_budget else _empty_rows(),
        pool.fetch(proj_by_cust_sql, *proj_params_l),
        _team_projection_core(
            pool, team=team_scope, customer=customer, load_type=load_type,
            lanes=lanes, exclude_lanes=exclude_lanes,
            carriers=carriers, exclude_carriers=exclude_carriers, today=today, scope=scope,
        ),
    )

    # team_count is irrelevant per customer — only the volume/profit legs are
    # read below, and _projection_from_sums guards a zero cap.
    proj_map = {
        r["grp"]: _projection_from_sums(
            r["vol_12"], r["rev_12"], r["prof_12"],
            r["vol_mtd"], r["rev_mtd"], r["prof_mtd"],
            pending_workdays, 1,
        )
        for r in proj_rows
    }

    bud_map = {r["customer_name"]: r for r in bud_rows}
    # Bruno R4 (2026-05-27): totals row at top of the table. Accumulate over the
    # full filtered set (before the limit slice) so totals stay accurate.
    tot = {"vol": 0, "rev": 0.0, "prof": 0.0, "vol_b": 0.0, "rev_b": 0.0,
           "prof_b": 0.0, "otp_late": 0, "otd_late": 0}
    out = []
    for r in prod_rows:
        name = r["customer_name"]
        b = bud_map.pop(name, None)
        vol = int(r["vol"] or 0)
        rev = _safe_float(r["rev"])
        prof = _safe_float(r["prof"])
        otp_late = int(r["otp_late"] or 0)
        otd_late = int(r["otd_late"] or 0)
        vol_budget = _safe_float(b["vol_budget"]) if b else 0.0
        rev_budget = _safe_float(b["rev_budget"]) if b else 0.0
        prof_budget = _safe_float(b["prof_budget"]) if b else 0.0
        tot["vol"] += vol; tot["rev"] += rev; tot["prof"] += prof
        tot["vol_b"] += vol_budget; tot["rev_b"] += rev_budget; tot["prof_b"] += prof_budget
        tot["otp_late"] += otp_late; tot["otd_late"] += otd_late
        margin_pct = (prof / rev * 100.0) if rev else 0.0
        margin_budget_pct = (prof_budget / rev_budget * 100.0) if rev_budget else 0.0
        # R6: Vol×Day / Prof×Day and Projected EoM come from this customer's
        # own Team-Monthly-Projection sums (last 12 Mon-Sat days ÷ 12, plus
        # month-to-date actual) — NOT from the filtered window ÷ 14. A customer
        # with no activity in the projection window projects to zero, which is
        # the correct answer for "where will they end the month".
        pc = proj_map.get(name)
        vol_x_day = pc["avg_vol_day"] if pc else 0.0
        prof_x_day = pc["avg_prof_day"] if pc else 0.0
        proj_vol = pc["proj_volume"] if pc else 0.0
        proj_prof = pc["proj_profit"] if pc else 0.0
        out.append({
            "customer_name": name,
            "vol": vol,
            "vol_budget": vol_budget,
            "vol_var": vol - vol_budget,  # actual − budget
            "rev": rev,
            "rev_budget": rev_budget,
            "rev_var": rev - rev_budget,
            "prof": prof,
            "prof_budget": prof_budget,
            "prof_var": prof - prof_budget,
            "margin_pct": _safe_float(margin_pct),
            "margin_budget_pct": _safe_float(margin_budget_pct),
            "margin_var_pct": _safe_float(margin_pct - margin_budget_pct),
            "otp_pct": (1.0 - otp_late / vol) * 100.0 if vol else 0.0,
            "otd_pct": (1.0 - otd_late / vol) * 100.0 if vol else 0.0,
            "rev_x_l":  (rev / vol) if vol else 0.0,
            "prof_x_l": (prof / vol) if vol else 0.0,
            "vol_x_day": _safe_float(vol_x_day),
            "prof_x_day": _safe_float(prof_x_day),
            "proj_eom_vol":  _safe_float(proj_vol),
            "proj_eom_prof": _safe_float(proj_prof),
        })

    # Customers in budget but with zero production — surface them so the
    # variance row still shows the gap. Skipped under the Losses / Unbilled
    # filters (zero-production customers have no margin<0 / unbilled loads).
    for name, b in ({} if (losses_only or unbilled_only) else bud_map).items():
        vol_budget = _safe_float(b["vol_budget"])
        rev_budget = _safe_float(b["rev_budget"])
        prof_budget = _safe_float(b["prof_budget"])
        tot["vol_b"] += vol_budget; tot["rev_b"] += rev_budget; tot["prof_b"] += prof_budget
        out.append({
            "customer_name": name,
            "vol": 0, "vol_budget": vol_budget, "vol_var": -vol_budget,
            "rev": 0.0, "rev_budget": rev_budget, "rev_var": -rev_budget,
            "prof": 0.0, "prof_budget": prof_budget, "prof_var": -prof_budget,
            "margin_pct": 0.0,
            "margin_budget_pct": (prof_budget / rev_budget * 100.0) if rev_budget else 0.0,
            "margin_var_pct": -((prof_budget / rev_budget * 100.0) if rev_budget else 0.0),
            "otp_pct": 0.0, "otd_pct": 0.0,
            "rev_x_l": 0.0, "prof_x_l": 0.0,
            "vol_x_day": 0.0, "prof_x_day": 0.0,
            "proj_eom_vol": 0.0, "proj_eom_prof": 0.0,
        })

    sort_key = {
        "revenue_desc":  lambda r: -r["rev"],
        "profit_desc":   lambda r: -r["prof"],
        "volume_desc":   lambda r: -r["vol"],
        "customer":      lambda r: (r["customer_name"] or "").upper(),
        "loss_desc":     lambda r: r["prof"],  # most negative profit first
    }.get(sort, lambda r: -r["rev"])
    full_total = len(out)
    out.sort(key=sort_key)
    out = out[:limit]

    t_vol, t_rev, t_prof = tot["vol"], tot["rev"], tot["prof"]
    t_vol_b, t_rev_b, t_prof_b = tot["vol_b"], tot["rev_b"], tot["prof_b"]
    totals = {
        "vol": t_vol, "vol_budget": _safe_float(t_vol_b), "vol_var": t_vol - t_vol_b,
        "rev": _safe_float(t_rev), "rev_budget": _safe_float(t_rev_b), "rev_var": _safe_float(t_rev - t_rev_b),
        "prof": _safe_float(t_prof), "prof_budget": _safe_float(t_prof_b), "prof_var": _safe_float(t_prof - t_prof_b),
        "margin_pct": _safe_float((t_prof / t_rev * 100.0) if t_rev else 0.0),
        "margin_budget_pct": _safe_float((t_prof_b / t_rev_b * 100.0) if t_rev_b else 0.0),
        "otp_pct": _safe_float((1.0 - tot["otp_late"] / t_vol) * 100.0 if t_vol else 0.0),
        "otd_pct": _safe_float((1.0 - tot["otd_late"] / t_vol) * 100.0 if t_vol else 0.0),
        "rev_x_l": _safe_float((t_rev / t_vol) if t_vol else 0.0),
        "prof_x_l": _safe_float((t_prof / t_vol) if t_vol else 0.0),
    }
    totals["margin_var_pct"] = _safe_float(totals["margin_pct"] - totals["margin_budget_pct"])
    # Bruno (PDF 2026-08-14) R6: the TOTAL row for the 4 projection columns is
    # the report-wide Team Monthly Projection itself (§44 full-universe
    # aggregate, never a client reduce). Because every per-row value is the same
    # linear formula over the same universe, the rows sum to exactly this total
    # whenever the row set covers the projection window — i.e. on the default
    # month range (§16 KPI = detail). Under a narrow custom Date range the rows
    # are a subset while the projection stays month-anchored, which is the
    # intended behaviour, not drift.
    totals["vol_x_day"] = _safe_float(proj_all["avg_vol_day"])
    totals["prof_x_day"] = _safe_float(proj_all["avg_prof_day"])
    totals["proj_eom_vol"] = _safe_float(proj_all["proj_volume"])
    totals["proj_eom_prof"] = _safe_float(proj_all["proj_profit"])

    return {
        "success": True,
        "data": out,
        "meta": {
            "window": {"start": s.isoformat(), "end": e.isoformat()},
            "pending_workdays": pending_workdays,
            "total": full_total,
            "totals": totals,
        },
    }


# ---------------------------------------------------------------------------
# /actuals-by-lane — Bruno round 3 (2026-05-19) Production-only per-lane roll-up
# ---------------------------------------------------------------------------


@router.get("/actuals-by-lane")
async def actuals_by_lane(
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
    sort: str = Query("revenue_desc"),
    limit: int = Query(100, ge=1, le=500),
    losses_only: bool = Query(False),
    unbilled_only: bool = Query(False),
    _user: dict = Depends(require_report_access("ops-portal-overview")),
):
    """Second table below Actuals — Production data only, grouped by lane.

    Lane key = ``TRIM(origin_name) || ' - ' || TRIM(dest_name)`` (city-pair —
    same shape as XRay CORP / Top Losses Lanes so the count matches §5).
    No Budget join — Bruno's spec: "second table … just with Production Data".
    """
    pool = get_datalake_gold_pool(request)
    scope = scope_of(request)
    s, e = _resolve_range(range, start_date, end_date)
    # Bruno R5 (2026-06-01): "Losses" button → restrict to margin_amt < 0 rows.
    # Bruno (PDF 2026-07-13): "Unbilled" button → bill_date < sentinel.
    losses_clause = " AND br4.margin_amt < 0" if losses_only else ""
    unbilled_clause = " AND br4.bill_date < '2000-01-01'::date" if unbilled_only else ""

    p_params: list = []
    where = _v4_scope_where("br4", team, customer, load_type, p_params, lanes, exclude_lanes, carriers, exclude_carriers, scope=scope)
    p_params.extend([s, e])
    p_s = len(p_params) - 1
    p_e = len(p_params)

    sql = f"""
        WITH otp AS ({_scorecard_cte("otp", scope)}),
             otd AS ({_scorecard_cte("otd", scope)}),
             prod AS (
                SELECT
                    TRIM(br4.origin_name) AS origin,
                    TRIM(br4.dest_name)   AS dest,
                    br4.id, br4.company_id,
                    br4.total_charge, br4.margin_amt,
                    -- Bruno round (2026-07-01) R3: carrier per order (first movement).
                    NULLIF(TRIM(mov.payee_name), '') AS carrier,
                    COALESCE(otp.scorecard_count_otp, 0) AS otp_cnt,
                    COALESCE(otd.scorecard_count_otd, 0) AS otd_cnt
                FROM public.mcleod_gld_budget_report_v4 br4
                LEFT JOIN otp ON TRIM(br4.id)=otp.id_key AND TRIM(br4.company_id)=otp.company_id_key
                LEFT JOIN otd ON TRIM(br4.id)=otd.id_key AND TRIM(br4.company_id)=otd.company_id_key
                LEFT JOIN LATERAL (
                    SELECT m.payee_name
                    FROM public.mcleod_gld_movement m
                    WHERE m.order_id = br4.id AND m.company_id = br4.company_id
                    ORDER BY m.movement_id ASC
                    LIMIT 1
                ) mov ON TRUE
                WHERE {where}
                  AND br4.origin_actual_departure >= ${p_s}
                  AND br4.origin_actual_departure < (${p_e}::date + INTERVAL '1 day')
                  AND TRIM(br4.origin_name) <> ''
                  AND TRIM(br4.dest_name)   <> ''
                  {losses_clause}
                  {unbilled_clause}
             ),
             uni AS (SELECT COUNT(DISTINCT carrier) AS n_carriers_total FROM prod)
        SELECT
          origin || ' - ' || dest AS lane,
          origin,
          dest,
          COUNT(*) FILTER (WHERE total_charge IS NOT NULL AND total_charge <> 0) AS vol,
          COUNT(DISTINCT carrier) AS n_carriers,
          MAX(uni.n_carriers_total) AS n_carriers_total,
          COALESCE(SUM(total_charge), 0)::numeric AS rev,
          COALESCE(SUM(margin_amt),  0)::numeric  AS prof,
          COUNT(*) FILTER (WHERE margin_amt < 0
                             AND total_charge IS NOT NULL
                             AND total_charge <> 0) AS loss_loads,
          COALESCE(SUM(margin_amt) FILTER (WHERE margin_amt < 0), 0)::numeric AS loss_profit,
          SUM(otp_cnt) AS otp_late,
          SUM(otd_cnt) AS otd_late
        FROM prod CROSS JOIN uni
        GROUP BY origin, dest
    """

    rows = await pool.fetch(sql, *p_params)
    # Bruno R4 (2026-05-27): totals row at top — accumulate over the full set.
    tot = {"vol": 0, "rev": 0.0, "prof": 0.0, "loss_loads": 0, "loss_profit": 0.0,
           "otp_late": 0, "otd_late": 0}
    out = []
    for r in rows:
        vol = int(r["vol"] or 0)
        rev = _safe_float(r["rev"])
        prof = _safe_float(r["prof"])
        otp_late = int(r["otp_late"] or 0)
        otd_late = int(r["otd_late"] or 0)
        tot["vol"] += vol; tot["rev"] += rev; tot["prof"] += prof
        tot["loss_loads"] += int(r["loss_loads"] or 0)
        tot["loss_profit"] += _safe_float(r["loss_profit"])
        tot["otp_late"] += otp_late; tot["otd_late"] += otd_late
        out.append({
            "lane":       r["lane"],
            "origin":     r["origin"],
            "dest":       r["dest"],
            "vol":        vol,
            "carriers":   int(r["n_carriers"] or 0),
            "rev":        rev,
            "prof":       prof,
            "margin_pct": (prof / rev * 100.0) if rev else 0.0,
            "loss_loads":  int(r["loss_loads"] or 0),
            "loss_profit": _safe_float(r["loss_profit"]),
            "otp_pct":    (1.0 - otp_late / vol) * 100.0 if vol else 0.0,
            "otd_pct":    (1.0 - otd_late / vol) * 100.0 if vol else 0.0,
            "rev_x_l":    (rev / vol) if vol else 0.0,
            "prof_x_l":   (prof / vol) if vol else 0.0,
        })

    sort_key = {
        "revenue_desc": lambda r: -r["rev"],
        "profit_desc":  lambda r: -r["prof"],
        "volume_desc":  lambda r: -r["vol"],
        "loss_desc":    lambda r: r["prof"],   # most negative first
        "lane":         lambda r: (r["lane"] or "").upper(),
        "margin_desc":  lambda r: -r["margin_pct"],
    }.get(sort, lambda r: -r["rev"])
    full_total = len(out)
    out.sort(key=sort_key)
    out = out[:limit]

    t_vol, t_rev, t_prof = tot["vol"], tot["rev"], tot["prof"]
    # Universe-wide distinct carrier count (same scalar on every row via uni CTE).
    carriers_total = int(rows[0]["n_carriers_total"] or 0) if rows else 0
    totals = {
        "vol": t_vol,
        "carriers": carriers_total,
        "rev": _safe_float(t_rev),
        "prof": _safe_float(t_prof),
        "margin_pct": _safe_float((t_prof / t_rev * 100.0) if t_rev else 0.0),
        "loss_loads": tot["loss_loads"],
        "loss_profit": _safe_float(tot["loss_profit"]),
        "otp_pct": _safe_float((1.0 - tot["otp_late"] / t_vol) * 100.0 if t_vol else 0.0),
        "otd_pct": _safe_float((1.0 - tot["otd_late"] / t_vol) * 100.0 if t_vol else 0.0),
        "rev_x_l": _safe_float((t_rev / t_vol) if t_vol else 0.0),
        "prof_x_l": _safe_float((t_prof / t_vol) if t_vol else 0.0),
    }

    return {
        "success": True,
        "data": out,
        "meta": {
            "window": {"start": s.isoformat(), "end": e.isoformat()},
            "total": full_total,
            "totals": totals,
        },
    }


# ---------------------------------------------------------------------------
# /margin-distribution — ORDERS per per-order margin% bucket (Bruno R18)
# ---------------------------------------------------------------------------


@router.get("/margin-distribution")
async def margin_distribution(
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
    """ORDER count + revenue per per-order margin% bucket over v4 production.

    Buckets on each order's ``margin_amt / total_charge``:
      lt_0 (<0%) / 0_5 / 5_10 / 10_15 / 15_20 / gte_20.
    Orders with ``total_charge = 0`` have an undefined margin% so they land in a
    ``no_revenue`` bucket (same handling as ops-margins /distribution) — the v4
    profit rule (SUM(margin_amt) over ALL rows) is not violated because we never
    filter those rows out of the totals; only the per-order margin% needs a
    non-zero charge to be defined.

    Unlike OPs Margins' /distribution (which counts CUSTOMERS), this counts
    ORDERS — the intended difference per Bruno R18.
    """
    pool = get_datalake_gold_pool(request)
    scope = scope_of(request)
    s, e = _resolve_range(range, start_date, end_date)
    params: list = []
    where = _v4_scope_where("br4", team, customer, load_type, params, lanes, exclude_lanes, carriers, exclude_carriers, scope=scope)
    params.extend([s, e])
    p_s = len(params) - 1
    p_e = len(params)

    rows = await pool.fetch(
        f"""
        WITH labeled AS (
          SELECT
            CASE
              WHEN br4.total_charge IS NULL OR br4.total_charge = 0 THEN 'no_revenue'
              WHEN br4.margin_amt / br4.total_charge < 0     THEN 'lt_0'
              WHEN br4.margin_amt / br4.total_charge < 0.05  THEN '0_5'
              WHEN br4.margin_amt / br4.total_charge < 0.10  THEN '5_10'
              WHEN br4.margin_amt / br4.total_charge < 0.15  THEN '10_15'
              WHEN br4.margin_amt / br4.total_charge < 0.20  THEN '15_20'
              ELSE                                                'gte_20'
            END AS bucket,
            br4.total_charge,
            br4.margin_amt
          FROM public.mcleod_gld_budget_report_v4 br4
          WHERE {where}
            AND br4.origin_actual_departure >= ${p_s}
            AND br4.origin_actual_departure < (${p_e}::date + INTERVAL '1 day')
        )
        SELECT
          bucket,
          COUNT(*)::int                          AS orders,
          COALESCE(SUM(total_charge), 0)::numeric AS revenue,
          COALESCE(SUM(margin_amt), 0)::numeric   AS profit
        FROM labeled
        GROUP BY bucket
        ORDER BY CASE bucket
          WHEN 'lt_0'   THEN 0
          WHEN '0_5'    THEN 1
          WHEN '5_10'   THEN 2
          WHEN '10_15'  THEN 3
          WHEN '15_20'  THEN 4
          WHEN 'gte_20' THEN 5
          ELSE 6 END
        """,
        *params,
    )

    data = [
        {
            "bucket": r["bucket"],
            "orders": int(r["orders"] or 0),
            "revenue": _safe_float(r["revenue"]),
            # Bruno (PDF 2026-07-13): Profit total per bucket (SUM(margin_amt)).
            "profit": _safe_float(r["profit"]),
        }
        for r in rows
    ]
    # Header totals cover only the orders with a definable margin% (the six
    # rendered buckets). The 'no_revenue' bucket (total_charge = 0 → undefined
    # margin%) is excluded so the header reconciles with the visible buckets;
    # it stays in `data` for completeness but the frontend renders the six.
    total_orders = sum(d["orders"] for d in data if d["bucket"] != "no_revenue")
    total_revenue = _safe_float(sum(d["revenue"] for d in data if d["bucket"] != "no_revenue"))
    total_profit = _safe_float(sum(d["profit"] for d in data if d["bucket"] != "no_revenue"))
    return {
        "success": True,
        "data": data,
        "meta": {
            "window": {"start": s.isoformat(), "end": e.isoformat()},
            "total_orders": total_orders,
            "total_revenue": total_revenue,
            "total_profit": total_profit,
        },
    }
