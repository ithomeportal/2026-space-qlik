"""Code-made report: OPs Direct Compare — side-by-side period comparison.

Mirrors Bruno's Qlik app ``4a8e2ffd-b049-4853-b716-195d568aaf11`` / sheet
``eebace42-2060-41d0-9d51-b628be1adc74`` (BRUNO -- Direct Compare). Two
independent panels (data1 / data2), each with its own date range +
Division + Team filters. Center delta KPIs compute client-side from the
two panel-summary payloads. Customer + Lane diff tables are computed
server-side in a single SQL via FULL OUTER JOIN of two CTEs (one per
panel) so we hit v4 twice instead of four times.

Scope (matches OPs Margins / Top Losses Lanes / Sales-Attrition):
- team_id     IN (TEAM1..TEAM5, TEAM-DFW)        — DFW sub-team via v4.team
- company_id  IN (TMS, TMS3)
- status      IN (D, P)
- customer_name NOT LIKE '%UNILINK%' / '%OILTEX%' (project-wide)

Performance notes:
- Reuses ``_scope_where`` + ``_pad_variants`` from ops_margins so the
  sargable padded-variants pattern stays single-source.
- ``/trend-12m`` is filter-less (per Bruno's spec "should not change with
  any filter panel") — cached in-process for 10 min so every viewer
  shares one DB hit.
- Diff tables use FULL OUTER JOIN on customer_name / lane key. Sign
  convention follows Bruno's PDF verbatim: ``data2 - data1``.
- ``/orders-window`` returns the last-year + this-year window scoped to
  team/division only (ignores the panel's date filter) and is paginated
  (default 200/page) since it's the only non-aggregated panel.
"""

from __future__ import annotations

import asyncio
import time
from datetime import date, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, Query, Request

from app.datalake import pad_variants as _pad_variants
from app.routers.deps import get_datalake_gold_pool, require_tag_role
from app.routers.ops_margins import (
    ALL_COMPANIES,
    ALL_TEAMS,
    CORP_TEAMS,
    DFW_SUB_TEAMS,
    DFW_TEAM,
    OPEN_STATUSES,
    OPS_ROLES,
    YEAR_END,
    YEAR_START,
    _bind_scope,
    _dest_expr,
    _lane_expr,
    _origin_expr,
    _parse_csv,
    _resolve_division,
    _resolve_range,
    _scope_where,
)

router = APIRouter(tags=["ops-direct-compare"], prefix="/custom/ops-direct-compare")


# ---------------------------------------------------------------------------
# Per-panel filter binding — same shape as ops_margins but only the date /
# division / team / sub-team subset (no customer / origin / destination —
# Direct Compare keeps the filter bar lean per Bruno's PDF).
# ---------------------------------------------------------------------------


def _bind_panel(
    range_: Optional[str],
    start_date: Optional[date],
    end_date: Optional[date],
    division: Optional[str],
    teams_csv: Optional[str],
    sub_teams_csv: Optional[str],
    params: list,
) -> tuple[str, date, date, list[str], list[str] | None]:
    s, e = _resolve_range(range_, start_date, end_date)
    division_teams, is_dfw = _resolve_division(division)
    requested_teams = _parse_csv(teams_csv, ALL_TEAMS) if teams_csv else None
    team_list = (
        [t for t in requested_teams if t in division_teams]
        if requested_teams is not None
        else division_teams
    )
    if not team_list:
        team_list = division_teams
    sub_team_list = (
        _parse_csv(sub_teams_csv, DFW_SUB_TEAMS) if (is_dfw and sub_teams_csv) else None
    )
    where = _scope_where(
        "br4", team_list, list(ALL_COMPANIES), None, None, None, sub_team_list, params,
    )
    params.extend([s, e])
    where_with_date = (
        f"{where} AND br4.origin_actual_departure::date "
        f"BETWEEN ${len(params) - 1} AND ${len(params)}"
    )
    return where_with_date, s, e, team_list, sub_team_list


# ---------------------------------------------------------------------------
# /filters — cascading dropdowns (year-wide, no date filter)
# ---------------------------------------------------------------------------


@router.get("/filters")
async def filters(
    request: Request,
    division: Optional[str] = Query(None),
    teams: Optional[str] = Query(None),
    sub_teams: Optional[str] = Query(None),
    _user: dict = Depends(require_tag_role(*OPS_ROLES)),
):
    """Static filter shape — no customer/origin/destination dropdowns here."""
    return {
        "success": True,
        "data": {
            "divisions": ["All", "CORP", "DFW"],
            "teams": list(ALL_TEAMS),
            "corp_teams": list(CORP_TEAMS),
            "dfw_team": DFW_TEAM,
            "dfw_sub_teams": list(DFW_SUB_TEAMS),
            "companies": list(ALL_COMPANIES),
            "year_start": YEAR_START.isoformat(),
            "year_end": YEAR_END.isoformat(),
        },
    }


# ---------------------------------------------------------------------------
# /panel-summary — 6 KPIs for one panel (called twice, once per panel)
# ---------------------------------------------------------------------------


@router.get("/panel-summary")
async def panel_summary(
    request: Request,
    range: Optional[str] = Query("mtd"),
    start_date: Optional[date] = Query(None),
    end_date: Optional[date] = Query(None),
    division: Optional[str] = Query(None),
    teams: Optional[str] = Query(None),
    sub_teams: Optional[str] = Query(None),
    _user: dict = Depends(require_tag_role(*OPS_ROLES)),
):
    pool = get_datalake_gold_pool(request)
    params: list = []
    where, s, e, team_list, sub_team_list = _bind_panel(
        range, start_date, end_date, division, teams, sub_teams, params,
    )

    row = await pool.fetchrow(
        f"""
        SELECT
          COUNT(*) FILTER (WHERE br4.total_charge <> 0)            AS loads,
          COUNT(DISTINCT br4.id) FILTER (WHERE br4.total_charge <> 0) AS load_ids,
          COALESCE(SUM(br4.total_charge) FILTER (
            WHERE br4.total_charge <> 0
          ), 0)::numeric                                            AS revenue,
          COALESCE(SUM(br4.margin_amt) FILTER (
            WHERE br4.total_charge <> 0
          ), 0)::numeric                                            AS profit
        FROM public.mcleod_gld_budget_report_v4 br4
        WHERE {where}
        """,
        *params,
    )

    loads = int(row["loads"] or 0)
    load_ids = int(row["load_ids"] or 0) or loads  # fall back if id is null
    revenue = float(row["revenue"] or 0)
    profit = float(row["profit"] or 0)
    margin_pct = (profit / revenue * 100.0) if revenue else None
    avg_r_per_l = (revenue / load_ids) if load_ids else None
    avg_p_per_l = (profit / load_ids) if load_ids else None

    return {
        "success": True,
        "data": {
            "loads": loads,
            "revenue": revenue,
            "profit": profit,
            "margin_pct": margin_pct,
            "avg_r_per_l": avg_r_per_l,
            "avg_p_per_l": avg_p_per_l,
            "window": {"start": s.isoformat(), "end": e.isoformat()},
            "teams_applied": team_list,
            "sub_teams_applied": sub_team_list,
        },
    }


# ---------------------------------------------------------------------------
# /concentration — Top-5 customers by profit + others bucket (per panel)
# ---------------------------------------------------------------------------


@router.get("/concentration")
async def concentration(
    request: Request,
    range: Optional[str] = Query("mtd"),
    start_date: Optional[date] = Query(None),
    end_date: Optional[date] = Query(None),
    division: Optional[str] = Query(None),
    teams: Optional[str] = Query(None),
    sub_teams: Optional[str] = Query(None),
    top: int = Query(5, ge=3, le=20),
    _user: dict = Depends(require_tag_role(*OPS_ROLES)),
):
    pool = get_datalake_gold_pool(request)
    params: list = []
    where, s, e, _t, _sub = _bind_panel(
        range, start_date, end_date, division, teams, sub_teams, params,
    )
    params.append(top)
    p_top = len(params)

    rows = await pool.fetch(
        f"""
        WITH cust AS (
          SELECT
            TRIM(br4.customer_name) AS customer,
            COALESCE(SUM(br4.total_charge) FILTER (
              WHERE br4.total_charge <> 0
            ), 0)::numeric AS revenue,
            COALESCE(SUM(br4.margin_amt) FILTER (
              WHERE br4.total_charge <> 0
            ), 0)::numeric AS profit
          FROM public.mcleod_gld_budget_report_v4 br4
          WHERE {where}
            AND br4.customer_name IS NOT NULL
            AND TRIM(br4.customer_name) <> ''
          GROUP BY TRIM(br4.customer_name)
        ),
        ranked AS (
          SELECT *,
                 ROW_NUMBER() OVER (ORDER BY profit DESC NULLS LAST) AS rn,
                 SUM(profit) OVER ()  AS total_profit,
                 SUM(revenue) OVER () AS total_revenue
          FROM cust
        )
        SELECT
          CASE WHEN rn <= ${p_top} THEN customer ELSE 'Others' END AS bucket,
          SUM(revenue)::numeric AS revenue,
          SUM(profit)::numeric  AS profit,
          MAX(total_profit)::numeric  AS total_profit,
          MAX(total_revenue)::numeric AS total_revenue,
          MAX(rn) AS sort_rn
        FROM ranked
        GROUP BY CASE WHEN rn <= ${p_top} THEN customer ELSE 'Others' END
        ORDER BY MIN(rn)
        """,
        *params,
    )

    total_profit = float(rows[0]["total_profit"] or 0) if rows else 0.0
    total_revenue = float(rows[0]["total_revenue"] or 0) if rows else 0.0
    out = []
    for r in rows:
        prof = float(r["profit"] or 0)
        out.append({
            "customer": r["bucket"],
            "revenue": float(r["revenue"] or 0),
            "profit": prof,
            "concentration_pct": (prof / total_profit * 100.0) if total_profit else None,
            "is_others": r["bucket"] == "Others",
        })
    return {
        "success": True,
        "data": out,
        "meta": {
            "total_profit": total_profit,
            "total_revenue": total_revenue,
            "top": top,
            "window": {"start": s.isoformat(), "end": e.isoformat()},
        },
    }


# ---------------------------------------------------------------------------
# /by-customer — single-panel customer table
# ---------------------------------------------------------------------------


def _customer_select(where: str) -> str:
    return f"""
        SELECT
          TRIM(br4.customer_name) AS customer,
          COUNT(*) FILTER (WHERE br4.total_charge <> 0) AS loads,
          COUNT(DISTINCT br4.id) FILTER (WHERE br4.total_charge <> 0) AS load_ids,
          COALESCE(SUM(br4.total_charge) FILTER (
            WHERE br4.total_charge <> 0
          ), 0)::numeric AS revenue,
          COALESCE(SUM(br4.margin_amt) FILTER (
            WHERE br4.total_charge <> 0
          ), 0)::numeric AS profit
        FROM public.mcleod_gld_budget_report_v4 br4
        WHERE {where}
          AND br4.customer_name IS NOT NULL
          AND TRIM(br4.customer_name) <> ''
        GROUP BY TRIM(br4.customer_name)
    """


@router.get("/by-customer")
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
    _user: dict = Depends(require_tag_role(*OPS_ROLES)),
):
    pool = get_datalake_gold_pool(request)
    params: list = []
    where, _s, _e, _t, _sub = _bind_panel(
        range, start_date, end_date, division, teams, sub_teams, params,
    )
    offset = (page - 1) * limit
    order_by = {
        "profit_desc":  "profit DESC NULLS LAST, customer ASC",
        "profit_asc":   "profit ASC NULLS LAST, customer ASC",
        "revenue_desc": "revenue DESC NULLS LAST",
        "loads_desc":   "loads DESC, profit DESC NULLS LAST",
        "margin_desc":  "margin_pct DESC NULLS LAST, profit DESC",
        "margin_asc":   "margin_pct ASC NULLS LAST, profit DESC",
        "customer_asc": "customer ASC",
    }.get(sort, "profit DESC NULLS LAST, customer ASC")
    params.extend([limit, offset])
    lim_p, off_p = len(params) - 1, len(params)

    rows = await pool.fetch(
        f"""
        WITH agg AS ({_customer_select(where)})
        SELECT
          customer, loads, load_ids, revenue, profit,
          CASE WHEN revenue <> 0 THEN profit / revenue ELSE NULL END AS margin_pct,
          CASE WHEN load_ids > 0 THEN profit / load_ids ELSE NULL END AS avg_p_per_l,
          COUNT(*) OVER() AS total_count
        FROM agg
        ORDER BY {order_by}
        LIMIT ${lim_p} OFFSET ${off_p}
        """,
        *params,
    )

    total = int(rows[0]["total_count"]) if rows else 0
    data = [
        {
            "customer": r["customer"],
            "loads": int(r["loads"] or 0),
            "revenue": float(r["revenue"] or 0),
            "profit": float(r["profit"] or 0),
            "margin_pct": (
                float(r["margin_pct"]) * 100.0 if r["margin_pct"] is not None else None
            ),
            "avg_p_per_l": (
                float(r["avg_p_per_l"]) if r["avg_p_per_l"] is not None else None
            ),
        }
        for r in rows
    ]
    return {
        "success": True,
        "data": data,
        "meta": {"total": total, "page": page, "limit": limit},
    }


# ---------------------------------------------------------------------------
# /by-customer-diff — both panels in one query, diff = data2 - data1
# (Bruno's spec verbatim — diff sign matches the PDF)
# ---------------------------------------------------------------------------


@router.get("/by-customer-diff")
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
    _user: dict = Depends(require_tag_role(*OPS_ROLES)),
):
    pool = get_datalake_gold_pool(request)
    params: list = []
    w1, _, _, _, _ = _bind_panel(
        p1_range, p1_start_date, p1_end_date, p1_division, p1_teams, p1_sub_teams,
        params,
    )
    w2, _, _, _, _ = _bind_panel(
        p2_range, p2_start_date, p2_end_date, p2_division, p2_teams, p2_sub_teams,
        params,
    )
    offset = (page - 1) * limit
    order_by = {
        "p2_profit_desc":  "p2_profit DESC NULLS LAST, customer ASC",
        "p2_profit_asc":   "p2_profit ASC NULLS LAST, customer ASC",
        "p2_revenue_desc": "p2_revenue DESC NULLS LAST",
        "p2_loads_desc":   "p2_loads DESC NULLS LAST",
        "diff_profit_desc": "diff_profit DESC NULLS LAST",
        "diff_profit_asc":  "diff_profit ASC NULLS LAST",
        "diff_revenue_desc": "diff_revenue DESC NULLS LAST",
        "diff_revenue_asc":  "diff_revenue ASC NULLS LAST",
        "margin_desc":  "p2_margin_pct DESC NULLS LAST",
        "margin_asc":   "p2_margin_pct ASC NULLS LAST",
        "customer_asc": "customer ASC",
    }.get(sort, "p2_profit DESC NULLS LAST, customer ASC")
    params.extend([limit, offset])
    lim_p, off_p = len(params) - 1, len(params)

    rows = await pool.fetch(
        f"""
        WITH d1 AS ({_customer_select(w1)}),
             d2 AS ({_customer_select(w2)}),
             merged AS (
               SELECT
                 COALESCE(d2.customer, d1.customer) AS customer,
                 COALESCE(d1.loads, 0)    AS p1_loads,
                 COALESCE(d1.load_ids, 0) AS p1_load_ids,
                 COALESCE(d1.revenue, 0)  AS p1_revenue,
                 COALESCE(d1.profit, 0)   AS p1_profit,
                 COALESCE(d2.loads, 0)    AS p2_loads,
                 COALESCE(d2.load_ids, 0) AS p2_load_ids,
                 COALESCE(d2.revenue, 0)  AS p2_revenue,
                 COALESCE(d2.profit, 0)   AS p2_profit
               FROM d2 FULL OUTER JOIN d1 ON d1.customer = d2.customer
             )
        SELECT
          customer,
          p1_loads, p1_load_ids, p1_revenue, p1_profit,
          p2_loads, p2_load_ids, p2_revenue, p2_profit,
          CASE WHEN p2_revenue <> 0 THEN p2_profit / p2_revenue ELSE NULL END
            AS p2_margin_pct,
          CASE WHEN p2_load_ids > 0 THEN p2_profit / p2_load_ids ELSE NULL END
            AS p2_avg_p_per_l,
          (p2_revenue - p1_revenue) AS diff_revenue,
          (p2_profit  - p1_profit)  AS diff_profit,
          COUNT(*) OVER() AS total_count
        FROM merged
        ORDER BY {order_by}
        LIMIT ${lim_p} OFFSET ${off_p}
        """,
        *params,
    )

    total = int(rows[0]["total_count"]) if rows else 0
    data = [
        {
            "customer": r["customer"],
            "loads": int(r["p2_loads"] or 0),
            "revenue": float(r["p2_revenue"] or 0),
            "profit": float(r["p2_profit"] or 0),
            "margin_pct": (
                float(r["p2_margin_pct"]) * 100.0
                if r["p2_margin_pct"] is not None else None
            ),
            "avg_p_per_l": (
                float(r["p2_avg_p_per_l"])
                if r["p2_avg_p_per_l"] is not None else None
            ),
            "diff_profit":  float(r["diff_profit"]  or 0),
            "diff_revenue": float(r["diff_revenue"] or 0),
        }
        for r in rows
    ]
    return {
        "success": True,
        "data": data,
        "meta": {"total": total, "page": page, "limit": limit},
    }


# ---------------------------------------------------------------------------
# /by-lane — single panel
# ---------------------------------------------------------------------------


def _lane_select(where: str) -> str:
    return f"""
        SELECT
          {_lane_expr("br4")}     AS lane,
          {_origin_expr("br4")}   AS origin,
          {_dest_expr("br4")}     AS destination,
          COUNT(*) FILTER (WHERE br4.total_charge <> 0) AS loads,
          COUNT(DISTINCT br4.id) FILTER (WHERE br4.total_charge <> 0) AS load_ids,
          COALESCE(SUM(br4.total_charge) FILTER (
            WHERE br4.total_charge <> 0
          ), 0)::numeric AS revenue,
          COALESCE(SUM(br4.margin_amt) FILTER (
            WHERE br4.total_charge <> 0
          ), 0)::numeric AS profit
        FROM public.mcleod_gld_budget_report_v4 br4
        WHERE {where}
          AND br4.origin_city_name IS NOT NULL
          AND br4.dest_city_name   IS NOT NULL
        GROUP BY {_lane_expr("br4")}, {_origin_expr("br4")}, {_dest_expr("br4")}
    """


@router.get("/by-lane")
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
    _user: dict = Depends(require_tag_role(*OPS_ROLES)),
):
    pool = get_datalake_gold_pool(request)
    params: list = []
    where, _s, _e, _t, _sub = _bind_panel(
        range, start_date, end_date, division, teams, sub_teams, params,
    )
    offset = (page - 1) * limit
    order_by = {
        "profit_desc":  "profit DESC NULLS LAST, lane ASC",
        "profit_asc":   "profit ASC NULLS LAST, lane ASC",
        "revenue_desc": "revenue DESC NULLS LAST",
        "loads_desc":   "loads DESC NULLS LAST",
        "margin_desc":  "margin_pct DESC NULLS LAST",
        "margin_asc":   "margin_pct ASC NULLS LAST",
        "lane_asc":     "lane ASC",
    }.get(sort, "profit DESC NULLS LAST, lane ASC")
    params.extend([limit, offset])
    lim_p, off_p = len(params) - 1, len(params)

    rows = await pool.fetch(
        f"""
        WITH agg AS ({_lane_select(where)})
        SELECT
          lane, origin, destination, loads, load_ids, revenue, profit,
          CASE WHEN revenue <> 0 THEN profit / revenue ELSE NULL END AS margin_pct,
          CASE WHEN load_ids > 0 THEN profit / load_ids ELSE NULL END AS avg_p_per_l,
          COUNT(*) OVER() AS total_count
        FROM agg
        ORDER BY {order_by}
        LIMIT ${lim_p} OFFSET ${off_p}
        """,
        *params,
    )

    total = int(rows[0]["total_count"]) if rows else 0
    data = [
        {
            "lane": r["lane"],
            "origin": r["origin"],
            "destination": r["destination"],
            "loads": int(r["loads"] or 0),
            "revenue": float(r["revenue"] or 0),
            "profit": float(r["profit"] or 0),
            "margin_pct": (
                float(r["margin_pct"]) * 100.0 if r["margin_pct"] is not None else None
            ),
            "avg_p_per_l": (
                float(r["avg_p_per_l"]) if r["avg_p_per_l"] is not None else None
            ),
        }
        for r in rows
    ]
    return {
        "success": True,
        "data": data,
        "meta": {"total": total, "page": page, "limit": limit},
    }


# ---------------------------------------------------------------------------
# /by-lane-diff — both panels in one query
# ---------------------------------------------------------------------------


@router.get("/by-lane-diff")
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
    _user: dict = Depends(require_tag_role(*OPS_ROLES)),
):
    pool = get_datalake_gold_pool(request)
    params: list = []
    w1, _, _, _, _ = _bind_panel(
        p1_range, p1_start_date, p1_end_date, p1_division, p1_teams, p1_sub_teams,
        params,
    )
    w2, _, _, _, _ = _bind_panel(
        p2_range, p2_start_date, p2_end_date, p2_division, p2_teams, p2_sub_teams,
        params,
    )
    offset = (page - 1) * limit
    order_by = {
        "p2_profit_desc":  "p2_profit DESC NULLS LAST, lane ASC",
        "p2_profit_asc":   "p2_profit ASC NULLS LAST, lane ASC",
        "p2_revenue_desc": "p2_revenue DESC NULLS LAST",
        "p2_loads_desc":   "p2_loads DESC NULLS LAST",
        "diff_profit_desc": "diff_profit DESC NULLS LAST",
        "diff_profit_asc":  "diff_profit ASC NULLS LAST",
        "diff_revenue_desc": "diff_revenue DESC NULLS LAST",
        "diff_revenue_asc":  "diff_revenue ASC NULLS LAST",
        "margin_desc":  "p2_margin_pct DESC NULLS LAST",
        "margin_asc":   "p2_margin_pct ASC NULLS LAST",
        "lane_asc":     "lane ASC",
    }.get(sort, "p2_profit DESC NULLS LAST, lane ASC")
    params.extend([limit, offset])
    lim_p, off_p = len(params) - 1, len(params)

    rows = await pool.fetch(
        f"""
        WITH d1 AS ({_lane_select(w1)}),
             d2 AS ({_lane_select(w2)}),
             merged AS (
               SELECT
                 COALESCE(d2.lane, d1.lane)                 AS lane,
                 COALESCE(d2.origin, d1.origin)             AS origin,
                 COALESCE(d2.destination, d1.destination)   AS destination,
                 COALESCE(d1.loads, 0)    AS p1_loads,
                 COALESCE(d1.load_ids, 0) AS p1_load_ids,
                 COALESCE(d1.revenue, 0)  AS p1_revenue,
                 COALESCE(d1.profit, 0)   AS p1_profit,
                 COALESCE(d2.loads, 0)    AS p2_loads,
                 COALESCE(d2.load_ids, 0) AS p2_load_ids,
                 COALESCE(d2.revenue, 0)  AS p2_revenue,
                 COALESCE(d2.profit, 0)   AS p2_profit
               FROM d2 FULL OUTER JOIN d1 ON d1.lane = d2.lane
             )
        SELECT
          lane, origin, destination,
          p1_loads, p1_load_ids, p1_revenue, p1_profit,
          p2_loads, p2_load_ids, p2_revenue, p2_profit,
          CASE WHEN p2_revenue <> 0 THEN p2_profit / p2_revenue ELSE NULL END
            AS p2_margin_pct,
          CASE WHEN p2_load_ids > 0 THEN p2_profit / p2_load_ids ELSE NULL END
            AS p2_avg_p_per_l,
          (p2_revenue - p1_revenue) AS diff_revenue,
          (p2_profit  - p1_profit)  AS diff_profit,
          COUNT(*) OVER() AS total_count
        FROM merged
        ORDER BY {order_by}
        LIMIT ${lim_p} OFFSET ${off_p}
        """,
        *params,
    )

    total = int(rows[0]["total_count"]) if rows else 0
    data = [
        {
            "lane": r["lane"],
            "origin": r["origin"],
            "destination": r["destination"],
            "loads": int(r["p2_loads"] or 0),
            "revenue": float(r["p2_revenue"] or 0),
            "profit": float(r["p2_profit"] or 0),
            "margin_pct": (
                float(r["p2_margin_pct"]) * 100.0
                if r["p2_margin_pct"] is not None else None
            ),
            "avg_p_per_l": (
                float(r["p2_avg_p_per_l"])
                if r["p2_avg_p_per_l"] is not None else None
            ),
            "diff_profit":  float(r["diff_profit"]  or 0),
            "diff_revenue": float(r["diff_revenue"] or 0),
        }
        for r in rows
    ]
    return {
        "success": True,
        "data": data,
        "meta": {"total": total, "page": page, "limit": limit},
    }


# ---------------------------------------------------------------------------
# /trend-12m — last 12 months, NO filters (per Bruno: "all division and all
# teams. It should not change with any filter panel."). In-process TTL cache.
# ---------------------------------------------------------------------------

_TREND_TTL_S = 600.0  # 10 minutes
_trend_cache: dict[str, tuple[float, list[dict]]] = {}
_trend_lock = asyncio.Lock()


def _last_12m_bounds(today: date) -> tuple[date, date]:
    end = today
    y, m = today.year, today.month - 11
    while m <= 0:
        y -= 1
        m += 12
    return date(y, m, 1), end


@router.get("/trend-12m")
async def trend_12m(
    request: Request,
    _user: dict = Depends(require_tag_role(*OPS_ROLES)),
):
    today = date.today()
    cache_key = today.isoformat()
    now_ts = time.monotonic()
    cached = _trend_cache.get(cache_key)
    if cached and (now_ts - cached[0]) < _TREND_TTL_S:
        return {"success": True, "data": cached[1], "meta": {"cached": True}}

    async with _trend_lock:
        cached = _trend_cache.get(cache_key)
        if cached and (now_ts - cached[0]) < _TREND_TTL_S:
            return {"success": True, "data": cached[1], "meta": {"cached": True}}

        pool = get_datalake_gold_pool(request)
        start, end = _last_12m_bounds(today)

        params: list = []
        where = _scope_where(
            "br4", list(ALL_TEAMS), list(ALL_COMPANIES), None, None, None, None,
            params,
        )
        params.extend([start, end])
        rows = await pool.fetch(
            f"""
            SELECT
              DATE_TRUNC('month', br4.origin_actual_departure)::date AS bucket,
              COALESCE(SUM(br4.total_charge) FILTER (
                WHERE br4.total_charge <> 0
              ), 0)::numeric AS revenue,
              COALESCE(SUM(br4.margin_amt) FILTER (
                WHERE br4.total_charge <> 0
              ), 0)::numeric AS profit
            FROM public.mcleod_gld_budget_report_v4 br4
            WHERE {where}
              AND br4.origin_actual_departure::date
                  BETWEEN ${len(params) - 1} AND ${len(params)}
            GROUP BY DATE_TRUNC('month', br4.origin_actual_departure)::date
            ORDER BY bucket
            """,
            *params,
        )

        out = []
        for r in rows:
            rev = float(r["revenue"] or 0)
            prof = float(r["profit"] or 0)
            out.append({
                "bucket": r["bucket"].isoformat() if r["bucket"] else None,
                "revenue": rev,
                "profit": prof,
                "margin_pct": (prof / rev * 100.0) if rev else None,
            })
        _trend_cache[cache_key] = (now_ts, out)
        # Drop other-day keys to keep the cache from growing forever
        for k in list(_trend_cache.keys()):
            if k != cache_key:
                _trend_cache.pop(k, None)
        return {"success": True, "data": out, "meta": {"cached": False}}


# ---------------------------------------------------------------------------
# /customer-revenue-margin — combo chart (data2 panel)
# Bars: revenue, Line: margin %. Sorted by revenue DESC, top N customers.
# ---------------------------------------------------------------------------


@router.get("/customer-revenue-margin")
async def customer_revenue_margin(
    request: Request,
    range: Optional[str] = Query("mtd"),
    start_date: Optional[date] = Query(None),
    end_date: Optional[date] = Query(None),
    division: Optional[str] = Query(None),
    teams: Optional[str] = Query(None),
    sub_teams: Optional[str] = Query(None),
    top: int = Query(20, ge=5, le=50),
    _user: dict = Depends(require_tag_role(*OPS_ROLES)),
):
    pool = get_datalake_gold_pool(request)
    params: list = []
    where, _s, _e, _t, _sub = _bind_panel(
        range, start_date, end_date, division, teams, sub_teams, params,
    )
    params.append(top)
    p_top = len(params)

    rows = await pool.fetch(
        f"""
        WITH cust AS (
          SELECT
            TRIM(br4.customer_name) AS customer,
            COALESCE(SUM(br4.total_charge) FILTER (
              WHERE br4.total_charge <> 0
            ), 0)::numeric AS revenue,
            COALESCE(SUM(br4.margin_amt) FILTER (
              WHERE br4.total_charge <> 0
            ), 0)::numeric AS profit
          FROM public.mcleod_gld_budget_report_v4 br4
          WHERE {where}
            AND br4.customer_name IS NOT NULL
            AND TRIM(br4.customer_name) <> ''
          GROUP BY TRIM(br4.customer_name)
        )
        SELECT
          customer, revenue, profit,
          CASE WHEN revenue <> 0 THEN profit / revenue ELSE NULL END AS margin_pct
        FROM cust
        ORDER BY revenue DESC NULLS LAST
        LIMIT ${p_top}
        """,
        *params,
    )
    return {
        "success": True,
        "data": [
            {
                "customer": r["customer"],
                "revenue": float(r["revenue"] or 0),
                "profit": float(r["profit"] or 0),
                "margin_pct": (
                    float(r["margin_pct"]) * 100.0
                    if r["margin_pct"] is not None else None
                ),
            }
            for r in rows
        ],
    }


# ---------------------------------------------------------------------------
# /orders-window — Details by Order (this year + last year)
# Filter: team/division ONLY (date filter ignored, per Bruno's spec).
# Paginated since it spans 2 years.
# ---------------------------------------------------------------------------


@router.get("/orders-window")
async def orders_window(
    request: Request,
    division: Optional[str] = Query(None),
    teams: Optional[str] = Query(None),
    sub_teams: Optional[str] = Query(None),
    sort: str = Query("date_desc"),
    page: int = Query(1, ge=1),
    limit: int = Query(200, ge=1, le=500),
    _user: dict = Depends(require_tag_role(*OPS_ROLES)),
):
    pool = get_datalake_gold_pool(request)
    today = date.today()
    start = date(today.year - 1, 1, 1)
    end = today

    params: list = []
    division_teams, is_dfw = _resolve_division(division)
    requested_teams = _parse_csv(teams, ALL_TEAMS) if teams else None
    team_list = (
        [t for t in requested_teams if t in division_teams]
        if requested_teams is not None
        else division_teams
    )
    if not team_list:
        team_list = division_teams
    sub_team_list = (
        _parse_csv(sub_teams, DFW_SUB_TEAMS) if (is_dfw and sub_teams) else None
    )
    where = _scope_where(
        "br4", team_list, list(ALL_COMPANIES), None, None, None, sub_team_list, params,
    )
    params.extend([start, end])
    p_s, p_e = len(params) - 1, len(params)

    offset = (page - 1) * limit
    order_by = {
        "date_desc":   "actual_day DESC NULLS LAST, id DESC",
        "date_asc":    "actual_day ASC NULLS LAST, id ASC",
        "profit_desc": "profit DESC NULLS LAST",
        "profit_asc":  "profit ASC NULLS LAST",
        "revenue_desc": "revenue DESC NULLS LAST",
        "margin_desc": "margin_pct DESC NULLS LAST",
        "margin_asc":  "margin_pct ASC NULLS LAST",
    }.get(sort, "actual_day DESC NULLS LAST, id DESC")
    params.extend([limit, offset])
    lim_p, off_p = len(params) - 1, len(params)

    rows = await pool.fetch(
        f"""
        SELECT
          br4.origin_actual_departure        AS actual_day,
          TRIM(br4.id)                        AS id,
          TRIM(br4.customer_id)               AS cust_id,
          TRIM(br4.customer_name)             AS customer,
          TRIM(br4.team_id)                   AS team,
          {_origin_expr("br4")} || '-' || {_dest_expr("br4")} AS lane,
          br4.total_charge::numeric           AS revenue,
          br4.margin_amt::numeric             AS profit,
          CASE WHEN br4.total_charge <> 0
               THEN br4.margin_amt::numeric / br4.total_charge::numeric
               ELSE NULL END                  AS margin_pct,
          COUNT(*) OVER()                     AS total_count
        FROM public.mcleod_gld_budget_report_v4 br4
        WHERE {where}
          AND br4.origin_actual_departure::date BETWEEN ${p_s} AND ${p_e}
        ORDER BY {order_by}
        LIMIT ${lim_p} OFFSET ${off_p}
        """,
        *params,
    )

    total = int(rows[0]["total_count"]) if rows else 0
    data = []
    for r in rows:
        rev = float(r["revenue"] or 0)
        prof = float(r["profit"] or 0)
        data.append({
            "actual_day": r["actual_day"].isoformat() if r["actual_day"] else None,
            "id": r["id"],
            "cust_id": r["cust_id"],
            "customer": r["customer"],
            "team": r["team"],
            "lane": r["lane"],
            "revenue": rev,
            "profit": prof,
            "margin_pct": (
                float(r["margin_pct"]) * 100.0
                if r["margin_pct"] is not None else None
            ),
            "avg_r_per_l": rev,  # one row = one load → same as revenue
            "avg_p_per_l": prof,
        })
    return {
        "success": True,
        "data": data,
        "meta": {
            "total": total,
            "page": page,
            "limit": limit,
            "window": {"start": start.isoformat(), "end": end.isoformat()},
        },
    }


# ---------------------------------------------------------------------------
# /freshness — last refresh stamp, same shape as ops_margins
# ---------------------------------------------------------------------------


@router.get("/freshness")
async def freshness(
    request: Request,
    _user: dict = Depends(require_tag_role(*OPS_ROLES)),
):
    pool = get_datalake_gold_pool(request)
    row = await pool.fetchrow(
        """
        SELECT
          MAX(updated_dt) AS last_updated,
          MAX(created_dt) AS last_created,
          COUNT(*)        AS rows_in_scope
        FROM public.mcleod_gld_budget_report_v4
        WHERE team_id    = ANY($1)
          AND company_id = ANY($2)
          AND status     = ANY($3)
        """,
        _pad_variants(ALL_TEAMS, width=8),
        _pad_variants(ALL_COMPANIES, width=4),
        _pad_variants(OPEN_STATUSES, width=1),
    )
    last_updated = row["last_updated"] if row else None
    last_created = row["last_created"] if row else None
    return {
        "success": True,
        "data": {
            "last_updated": last_updated.isoformat() if last_updated else None,
            "last_created": last_created.isoformat() if last_created else None,
            "rows_in_scope": int(row["rows_in_scope"] or 0) if row else 0,
        },
    }
