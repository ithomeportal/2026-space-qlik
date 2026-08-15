"""Budget-vs-actual variance panels and the customer losses / not-billed lists.

Part of the ``ops_portal_overview`` package (split 2026-08-14 — see SPEC-CUSTOM-REPORTS §28).
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import List, Optional

from fastapi import Depends, Query, Request

from app.clock import cst_today
from app.routers.deps import get_datalake_gold_pool, require_report_access

from ._constants import CORP_TEAMS, CUSTOMER_TEAM_CTE, router
from ._dates import _last_5_weeks, _resolve_range, _week_label
from ._sql import _v4_scope_where
from ._metrics import _safe_float, _variance_from_sums


# ---------------------------------------------------------------------------
# /team-variance — §2 scope-wide Budget vs Actual variance row (Budget URL)
# ---------------------------------------------------------------------------


@router.get("/team-variance")
async def team_variance(
    request: Request,
    range: Optional[str] = Query("mtd"),
    start_date: Optional[date] = Query(None),
    end_date: Optional[date] = Query(None),
    team: Optional[str] = Query(None),
    customer: Optional[str] = Query(None),
    _user: dict = Depends(require_report_access("ops-portal-overview")),
):
    """Bruno's "Team Budget Monthly Variance" inverted table — single row.

    Bruno round-2 (2026-05-13) — flipped the variance convention to
    ``actual − budget`` (positive = over-performing) to harmonise with the
    bottom Actuals table. Customers KPI = count of customers in budget
    that actually shipped (loads_actual > 0); his literal subtraction
    formula reads negative, but the screenshot value (24) matches the
    active count, so display that.
    """
    pool = get_datalake_gold_pool(request)
    s, e = _resolve_range(range, start_date, end_date)
    params: list = [s, e]
    extra = ""
    if team:
        params.append(team)
        extra += f" AND ct.team_id = ${len(params)}"
    if customer:
        params.append(customer)
        extra += f' AND budget."Customer Name" = ${len(params)}'

    row = await pool.fetchrow(
        f"""
        WITH {CUSTOMER_TEAM_CTE},
        per_customer AS (
          SELECT
            budget."Customer Name" AS customer_name,
            SUM(budget."Loads Actual")    AS loads_actual,
            SUM(budget."Loads Budget")    AS loads_budget,
            SUM(budget."Revenue Actual")  AS revenue_actual,
            SUM(budget."Revenue Budget")  AS revenue_budget,
            SUM(budget."Profit Actual")   AS profit_actual,
            SUM(budget."Profit Budget")   AS profit_budget
          FROM public.daily_production_budget_report budget
          JOIN customer_team ct ON TRIM(budget."Customer Name") = ct.customer_name
          WHERE budget."Date" BETWEEN $1 AND $2
          {extra}
          GROUP BY budget."Customer Name"
        )
        SELECT
          COUNT(*) FILTER (WHERE COALESCE(loads_actual,0) > 0) AS active_customers,
          COUNT(*)                                              AS in_scope_customers,
          COALESCE(SUM(loads_budget),   0) AS loads_budget,
          COALESCE(SUM(loads_actual),   0) AS loads_actual,
          COALESCE(SUM(revenue_budget), 0) AS revenue_budget,
          COALESCE(SUM(revenue_actual), 0) AS revenue_actual,
          COALESCE(SUM(profit_budget),  0) AS profit_budget,
          COALESCE(SUM(profit_actual),  0) AS profit_actual
        FROM per_customer
        """,
        *params,
    )

    # Bruno round-2 (2026-05-13): actual − budget direction (positive = over-budget).
    loads_var   = _safe_float(row["loads_actual"])   - _safe_float(row["loads_budget"])
    revenue_var = _safe_float(row["revenue_actual"]) - _safe_float(row["revenue_budget"])
    profit_var  = _safe_float(row["profit_actual"])  - _safe_float(row["profit_budget"])
    margin_var_pct = (profit_var / revenue_var * 100.0) if revenue_var else 0.0
    rev_x_l = (revenue_var / loads_var) if loads_var else 0.0
    prof_x_l = (profit_var / loads_var) if loads_var else 0.0

    return {
        "success": True,
        "data": {
            # Active customers = customers in budget that actually shipped.
            # Bruno's literal "count(loads_actual=0) − count(*)" reads negative;
            # his screenshot value (24) matches the active count, so we surface that.
            "customers":      int(row["active_customers"] or 0),
            "volume_var":     _safe_float(loads_var),
            "revenue_var":    _safe_float(revenue_var),
            "profit_var":     _safe_float(profit_var),
            "margin_var_pct": _safe_float(margin_var_pct),
            "rev_x_l":        _safe_float(rev_x_l),
            "prof_x_l":       _safe_float(prof_x_l),
            "window": {"start": s.isoformat(), "end": e.isoformat()},
        },
    }


# ---------------------------------------------------------------------------
# /customer-variance — §3 per-customer Budget vs Actual variance (Budget URL)
# ---------------------------------------------------------------------------


@router.get("/customer-variance")
async def customer_variance(
    request: Request,
    range: Optional[str] = Query("mtd"),
    start_date: Optional[date] = Query(None),
    end_date: Optional[date] = Query(None),
    team: Optional[str] = Query(None),
    customer: Optional[str] = Query(None),
    limit: int = Query(50, ge=1, le=200),
    _user: dict = Depends(require_report_access("ops-portal-overview")),
):
    """§3 Customer Monthly Variance — one row per customer."""
    pool = get_datalake_gold_pool(request)
    s, e = _resolve_range(range, start_date, end_date)
    params: list = [s, e]
    extra = ""
    if team:
        params.append(team)
        extra += f" AND ct.team_id = ${len(params)}"
    if customer:
        params.append(customer)
        extra += f' AND budget."Customer Name" = ${len(params)}'
    params.append(limit)

    # Bruno round-2 (2026-05-13): actual − budget direction (positive = over-budget).
    rows = await pool.fetch(
        f"""
        WITH {CUSTOMER_TEAM_CTE}
        SELECT
          budget."Customer Name" AS customer_name,
          COALESCE(SUM(budget."Loads Actual"),    0)
            - COALESCE(SUM(budget."Loads Budget"),    0) AS volume_var,
          COALESCE(SUM(budget."Profit Actual"),   0)
            - COALESCE(SUM(budget."Profit Budget"),   0) AS profit_var,
          COALESCE(SUM(budget."Revenue Actual"),  0)
            - COALESCE(SUM(budget."Revenue Budget"),  0) AS revenue_var
        FROM public.daily_production_budget_report budget
        JOIN customer_team ct ON TRIM(budget."Customer Name") = ct.customer_name
        WHERE budget."Date" BETWEEN $1 AND $2
        {extra}
        GROUP BY budget."Customer Name"
        ORDER BY ABS(COALESCE(SUM(budget."Profit Actual"),0)
                   - COALESCE(SUM(budget."Profit Budget"),0)) DESC NULLS LAST
        LIMIT ${len(params)}
        """,
        *params,
    )
    return {
        "success": True,
        "data": [
            {
                "customer_name": r["customer_name"],
                "volume_var":   _safe_float(r["volume_var"]),
                "revenue_var":  _safe_float(r["revenue_var"]),
                "profit_var":   _safe_float(r["profit_var"]),
            }
            for r in rows
        ],
    }


# ---------------------------------------------------------------------------
# /customer-losses — §4 per-customer Production losses (margin<0) — Production URL
# ---------------------------------------------------------------------------


@router.get("/customer-losses")
async def customer_losses(
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
    limit: int = Query(50, ge=1, le=200),
    _user: dict = Depends(require_report_access("ops-portal-overview")),
):
    """§4 Customer Monthly Losses — one row per customer."""
    pool = get_datalake_gold_pool(request)
    s, e = _resolve_range(range, start_date, end_date)
    params: list = []
    where = _v4_scope_where("br4", team, customer, load_type, params, lanes, exclude_lanes, carriers, exclude_carriers)
    params.extend([s, e, limit])
    p_s = len(params) - 2
    p_e = len(params) - 1
    p_lim = len(params)

    rows = await pool.fetch(
        f"""
        SELECT
          br4.customer_name,
          COUNT(*) FILTER (WHERE br4.margin_amt < 0
                             AND br4.total_charge IS NOT NULL
                             AND br4.total_charge <> 0) AS loss_loads,
          COALESCE(SUM(CASE WHEN br4.margin_amt < 0 THEN br4.margin_amt END), 0)::numeric AS loss_profit
        FROM public.mcleod_gld_budget_report_v4 br4
        WHERE {where}
          AND br4.origin_actual_departure >= ${p_s}
          AND br4.origin_actual_departure < (${p_e}::date + INTERVAL '1 day')
        GROUP BY br4.customer_name
        HAVING COUNT(*) FILTER (WHERE br4.margin_amt < 0) > 0
        ORDER BY loss_profit ASC NULLS LAST
        LIMIT ${p_lim}
        """,
        *params,
    )
    return {
        "success": True,
        "data": [
            {
                "customer_name": r["customer_name"],
                "loss_loads":  int(r["loss_loads"] or 0),
                "loss_profit": _safe_float(r["loss_profit"]),
            }
            for r in rows
        ],
    }


# ---------------------------------------------------------------------------
# /customer-not-billed — Bruno round (2026-07-01) R14: per-customer "Not Billed"
# ---------------------------------------------------------------------------


@router.get("/customer-not-billed")
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
    # Bruno (PDF 2026-07-15) R1: Carrier multi-select (Include/Exclude).
    carriers: Optional[List[str]] = Query(None),
    exclude_carriers: Optional[List[str]] = Query(None),
    limit: int = Query(100, ge=1, le=500),
    _user: dict = Depends(require_report_access("ops-portal-overview")),
):
    """Bruno R14 — orders never billed (``bill_date < '2000-01-01'`` sentinel),
    grouped per customer.

      Loads   = COUNT(orders where bill_date < '2000-01-01')
      Revenue = SUM(total_charge where bill_date < '2000-01-01')

    Same CORP scope + page date range (origin_actual_departure) as the sibling
    Customer Monthly Losses table. Totals in ``meta`` are the full-universe
    window aggregate (never a client reduce over the LIMIT slice — §44)."""
    pool = get_datalake_gold_pool(request)
    s, e = _resolve_range(range, start_date, end_date)
    params: list = []
    where = _v4_scope_where("br4", team, customer, load_type, params, lanes, exclude_lanes, carriers, exclude_carriers)
    params.extend([s, e, limit])
    p_s = len(params) - 2
    p_e = len(params) - 1
    p_lim = len(params)

    rows = await pool.fetch(
        f"""
        WITH g AS (
            SELECT
              br4.customer_name AS customer_name,
              COUNT(*)                                     AS loads,
              COALESCE(SUM(br4.total_charge), 0)::numeric  AS revenue
            FROM public.mcleod_gld_budget_report_v4 br4
            WHERE {where}
              AND br4.origin_actual_departure >= ${p_s}
              AND br4.origin_actual_departure < (${p_e}::date + INTERVAL '1 day')
              AND br4.bill_date < '2000-01-01'::date
            GROUP BY br4.customer_name
        )
        SELECT
          customer_name, loads, revenue,
          SUM(loads)   OVER () AS loads_total,
          SUM(revenue) OVER () AS revenue_total,
          COUNT(*)     OVER () AS cust_total
        FROM g
        ORDER BY revenue DESC NULLS LAST
        LIMIT ${p_lim}
        """,
        *params,
    )
    totals = {
        "loads":   int(rows[0]["loads_total"] or 0) if rows else 0,
        "revenue": _safe_float(rows[0]["revenue_total"]) if rows else 0.0,
    }
    return {
        "success": True,
        "data": [
            {
                "customer_name": r["customer_name"],
                "loads":   int(r["loads"] or 0),
                "revenue": _safe_float(r["revenue"]),
            }
            for r in rows
        ],
        "meta": {
            "window": {"start": s.isoformat(), "end": e.isoformat()},
            "total": int(rows[0]["cust_total"] or 0) if rows else 0,
            "totals": totals,
        },
    }


@router.get("/team-variance-weekly")
async def team_variance_weekly(
    request: Request,
    team: Optional[str] = Query(None),
    customer: Optional[str] = Query(None),
    _user: dict = Depends(require_report_access("ops-portal-overview")),
):
    """Team Budget Variance broken out by the last 5 completed Mon-Sun weeks.

    Each week column is the actual − budget variance for that week (same
    convention as /team-variance). Fixed rolling 5-week window; team/customer
    filters apply, the page date filter is intentionally ignored.
    """
    pool = get_datalake_gold_pool(request)
    today = cst_today()
    week_starts, weeks_start, weeks_end = _last_5_weeks(today)
    params: list = [weeks_start, weeks_end]
    extra = ""
    if team:
        params.append(team)
        extra += f" AND ct.team_id = ${len(params)}"
    if customer:
        params.append(customer)
        extra += f' AND budget."Customer Name" = ${len(params)}'
    rows = await pool.fetch(
        f"""
        WITH {CUSTOMER_TEAM_CTE},
        per_cw AS (
          SELECT
            DATE_TRUNC('week', budget."Date")::date AS wk,
            budget."Customer Name" AS cust,
            SUM(budget."Loads Actual")   AS la, SUM(budget."Loads Budget")   AS lb,
            SUM(budget."Revenue Actual") AS ra, SUM(budget."Revenue Budget") AS rb,
            SUM(budget."Profit Actual")  AS pa, SUM(budget."Profit Budget")  AS pb
          FROM public.daily_production_budget_report budget
          JOIN customer_team ct ON TRIM(budget."Customer Name") = ct.customer_name
          WHERE budget."Date" BETWEEN $1 AND $2
          {extra}
          GROUP BY 1, 2
        )
        SELECT
          wk,
          COUNT(*) FILTER (WHERE COALESCE(la,0) > 0) AS active_customers,
          COALESCE(SUM(lb),0) AS loads_budget,   COALESCE(SUM(la),0) AS loads_actual,
          COALESCE(SUM(rb),0) AS revenue_budget, COALESCE(SUM(ra),0) AS revenue_actual,
          COALESCE(SUM(pb),0) AS profit_budget,  COALESCE(SUM(pa),0) AS profit_actual
        FROM per_cw
        GROUP BY wk
        """,
        *params,
    )
    by_wk = {r["wk"]: r for r in rows}
    weeks_out = []
    for ws in week_starts:
        r = by_wk.get(ws)
        obj = _variance_from_sums(
            r["active_customers"] if r else 0,
            r["loads_actual"] if r else 0, r["loads_budget"] if r else 0,
            r["revenue_actual"] if r else 0, r["revenue_budget"] if r else 0,
            r["profit_actual"] if r else 0, r["profit_budget"] if r else 0,
        )
        obj["start"] = ws.isoformat()
        obj["end"] = (ws + timedelta(days=6)).isoformat()
        obj["label"] = _week_label(ws)
        weeks_out.append(obj)
    return {"success": True, "data": {"weeks": weeks_out}}


@router.get("/team-variance-by-team")
async def team_variance_by_team(
    request: Request,
    range: Optional[str] = Query("mtd"),
    start_date: Optional[date] = Query(None),
    end_date: Optional[date] = Query(None),
    customer: Optional[str] = Query(None),
    _user: dict = Depends(require_report_access("ops-portal-overview")),
):
    """Team Budget Variance split per CORP team (TEAM1..TEAM5) + a Total.

    The single ``team`` filter is intentionally dropped — this view always
    returns every CORP team; ``customer`` / date filters still apply.
    """
    pool = get_datalake_gold_pool(request)
    s, e = _resolve_range(range, start_date, end_date)
    params: list = [s, e]
    extra = ""
    if customer:
        params.append(customer)
        extra += f' AND budget."Customer Name" = ${len(params)}'
    rows = await pool.fetch(
        f"""
        WITH {CUSTOMER_TEAM_CTE},
        per_ct AS (
          SELECT
            ct.team_id AS team_id,
            budget."Customer Name" AS cust,
            SUM(budget."Loads Actual")   AS la, SUM(budget."Loads Budget")   AS lb,
            SUM(budget."Revenue Actual") AS ra, SUM(budget."Revenue Budget") AS rb,
            SUM(budget."Profit Actual")  AS pa, SUM(budget."Profit Budget")  AS pb
          FROM public.daily_production_budget_report budget
          JOIN customer_team ct ON TRIM(budget."Customer Name") = ct.customer_name
          WHERE budget."Date" BETWEEN $1 AND $2
          {extra}
          GROUP BY 1, 2
        )
        SELECT
          team_id,
          COUNT(*) FILTER (WHERE COALESCE(la,0) > 0) AS active_customers,
          COALESCE(SUM(lb),0) AS loads_budget,   COALESCE(SUM(la),0) AS loads_actual,
          COALESCE(SUM(rb),0) AS revenue_budget, COALESCE(SUM(ra),0) AS revenue_actual,
          COALESCE(SUM(pb),0) AS profit_budget,  COALESCE(SUM(pa),0) AS profit_actual
        FROM per_ct
        GROUP BY team_id
        """,
        *params,
    )
    by_team = {r["team_id"]: r for r in rows}
    acc = {"cust": 0, "la": 0.0, "lb": 0.0, "ra": 0.0, "rb": 0.0, "pa": 0.0, "pb": 0.0}
    teams_out = []
    for t in CORP_TEAMS:
        r = by_team.get(t)
        obj = _variance_from_sums(
            r["active_customers"] if r else 0,
            r["loads_actual"] if r else 0, r["loads_budget"] if r else 0,
            r["revenue_actual"] if r else 0, r["revenue_budget"] if r else 0,
            r["profit_actual"] if r else 0, r["profit_budget"] if r else 0,
        )
        obj["team_id"] = t
        teams_out.append(obj)
        if r:
            acc["cust"] += int(r["active_customers"] or 0)
            acc["la"] += _safe_float(r["loads_actual"]);  acc["lb"] += _safe_float(r["loads_budget"])
            acc["ra"] += _safe_float(r["revenue_actual"]); acc["rb"] += _safe_float(r["revenue_budget"])
            acc["pa"] += _safe_float(r["profit_actual"]);  acc["pb"] += _safe_float(r["profit_budget"])
    total = _variance_from_sums(
        acc["cust"], acc["la"], acc["lb"], acc["ra"], acc["rb"], acc["pa"], acc["pb"],
    )
    return {"success": True, "data": {"total": total, "teams": teams_out}}
