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
- ``/trend-yoy`` is filter-less (per Bruno's spec "should not change with
  any filter panel") — cached in-process for 10 min so every viewer
  shares one DB hit.
- The compare tables (customer / lane / customer→lane pivot) compute BOTH
  panels in one SQL via FULL OUTER JOIN of two CTEs (one per panel). Diff
  sign: ``data1 - data2`` (Bruno 2026-10-01; the 2026-04 tables used
  ``data2 - data1``).
- Bruno 2026-10-01 removed the profit-only trend, the customer revenue/margin
  combo and the orders table; their endpoints (/trend-12m,
  /customer-revenue-margin, /orders-window) and the single-panel /by-customer
  + /by-lane went with them.
"""

from __future__ import annotations

import asyncio
import json
import time
from datetime import date, datetime, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request

from app.clock import cst_today
from app.datalake import pad_variants as _pad_variants
from app.routers.deps import get_datalake_gold_pool, require_report_access
from app.routers.ops_margins import (
    ALL_COMPANIES,
    ALL_TEAMS,
    CORP_TEAMS,
    DFW_SUB_TEAMS,
    DFW_TEAM,
    OPEN_STATUSES,
    YEAR_END,
    YEAR_START,
    _bind_scope,
    _lane_expr,
    _parse_csv,
    _resolve_division,
    _resolve_range,
    _scope_where,
)

router = APIRouter(tags=["ops-direct-compare"], prefix="/custom/ops-direct-compare")

# Every endpoint below accepts EITHER "ops-direct-compare" OR "ceo-executive"
# access (Bruno PDF 2026-07-22: CEO Executive gained a "Direct Compare" tab that
# embeds this whole report). Same multi-key pattern attrition_wow already uses
# for the CEO Attrition tab — no SQL duplicated, no new report key, no 4-place
# mirror. ⚠ Consequence, accepted and identical to the attrition_wow precedent:
# a ceo-executive holder can now also reach /custom/ops-direct-compare/* at the
# base URL, not only through the new tab.
#
# Not the ops_direct_compare_team.py pattern: that exists to RESTRICT data (a
# TEAM1 KAM must never see TEAM2 even by crafting ?p1_teams=TEAM2). There is no
# such restriction here — the tab is a full duplicate for an exec who already
# sees every division.


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
    _user: dict = Depends(require_report_access("ops-direct-compare", "ceo-executive")),
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
    _user: dict = Depends(require_report_access("ops-direct-compare", "ceo-executive")),
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
          -- Profit = SUM(margin_amt) over ALL in-scope rows. We intentionally
          -- do NOT filter total_charge <> 0 here: zero-charge rows carry
          -- accessorial margin that is real profit and must be added (matches
          -- CEO Executive's canonical sum(margin_amt); Bruno 2026-05-29).
          COALESCE(SUM(br4.margin_amt), 0)::numeric                 AS profit
        FROM public.mcleod_gld_budget_report_v4 br4
        WHERE {where}
        """,
        *params,
    )

    # ---- Budget vs Actual (CORP only) ------------------------------------
    # daily_production_budget_report is CORP-only and customer/division grain
    # (no reliable per-team split — budget rows collapse to one CORP team), so
    # we surface budget ONLY when the panel is scoped to the CORP division and
    # sum the goals across the panel's date window. DFW / All panels get no
    # budget (would be apples-to-oranges against non-CORP actuals).
    budget_applicable = (division or "").upper() == "CORP"
    budget_payload: dict = {"applicable": budget_applicable}
    if budget_applicable:
        b = await pool.fetchrow(
            """
            SELECT
              COALESCE(SUM(budget."Loads Budget"),   0)::numeric AS loads_budget,
              COALESCE(SUM(budget."Revenue Budget"), 0)::numeric AS revenue_budget,
              COALESCE(SUM(budget."Profit Budget"),  0)::numeric AS profit_budget
            FROM public.daily_production_budget_report budget
            WHERE budget."Date" BETWEEN $1 AND $2
            """,
            s, e,
        )
        budget_payload.update({
            "loads": float(b["loads_budget"] or 0),
            "revenue": float(b["revenue_budget"] or 0),
            "profit": float(b["profit_budget"] or 0),
        })

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
            "budget": budget_payload,
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
    _user: dict = Depends(require_report_access("ops-direct-compare", "ceo-executive")),
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
            COALESCE(SUM(br4.margin_amt), 0)::numeric AS profit
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
# Compare tables — Bruno PDF "BRUNO -- DIRECT COMPARE UPDATES" (2026-10-01).
#
# The four single-panel / "with Diff vs Panel 1" tables became TWO combined
# tables (Details by Customer, Details by Lane) plus a Customer → Lane pivot.
# Every row carries BOTH panels and the P1 − P2 diffs (⚠ the old diff tables
# printed P2 − P1; Bruno's new spec spells "Panel 1 − Panel 2" for every Diff
# column, which also matches the "Differential" KPI card).
#
# One definition, three grains: `_grouped_select` aggregates one panel at a
# grain, `_merged_cte` FULL OUTER JOINs the two panels, `_derived` adds margin /
# avg / diffs. Rows AND the Totals row run through the same `_derived`, and the
# totals are computed over the WHOLE population, never the visible page (§109).
# ---------------------------------------------------------------------------

_BASES = ("loads", "load_ids", "revenue", "profit")

# The lane key is COALESCEd, never NULL: a NULL key would not match itself in
# the FULL OUTER JOIN (and `IS NOT DISTINCT FROM` is not hash/merge-joinable,
# so Postgres refuses it in a FULL JOIN). 0 rows hit this on 2026-10-01 — it is
# a join guard, not a population change.
NO_LANE = "(no lane)"
_DIM_EXPR = {
    "customer": "TRIM(br4.customer_name)",
    "lane": f"COALESCE({_lane_expr('br4')}, '{NO_LANE}')",
}

# Every column the combined tables can sort by. Anything else is a 400 — a
# client-supplied key must never reach ORDER BY unvetted.
SORT_COLUMNS: tuple[str, ...] = tuple(
    f"{side}_{m}"
    for m in ("loads", "revenue", "profit", "margin", "avg_p")
    for side in ("p1", "p2", "diff")
)
DEFAULT_SORT = "p1_profit_desc"


def _grouped_select(where: str, dims: tuple[str, ...]) -> str:
    """One panel aggregated at `dims` grain (customer / lane / customer+lane).

    Same metric definitions as /panel-summary: loads + revenue skip zero-charge
    rows, profit sums ALL in-scope rows (accessorial margin is real profit).
    """
    keys = ",\n          ".join(f"{_DIM_EXPR[d]} AS {d}" for d in dims)
    group = ", ".join(str(i + 1) for i in range(len(dims)))
    return f"""
        SELECT
          {keys},
          COUNT(*) FILTER (WHERE br4.total_charge <> 0) AS loads,
          COUNT(DISTINCT br4.id) FILTER (WHERE br4.total_charge <> 0) AS load_ids,
          COALESCE(SUM(br4.total_charge) FILTER (
            WHERE br4.total_charge <> 0
          ), 0)::numeric AS revenue,
          COALESCE(SUM(br4.margin_amt), 0)::numeric AS profit
        FROM public.mcleod_gld_budget_report_v4 br4
        WHERE {where}
          AND br4.customer_name IS NOT NULL
          AND TRIM(br4.customer_name) <> ''
        GROUP BY {group}
    """


def _merged_cte(w1: str, w2: str, dims: tuple[str, ...]) -> str:
    """`d1`, `d2` and `merged` CTE bodies: both panels side by side, 0-filled."""
    keys = ", ".join(f"COALESCE(d1.{d}, d2.{d}) AS {d}" for d in dims)
    on = " AND ".join(f"d1.{d} = d2.{d}" for d in dims)
    bases = ",\n               ".join(
        f"COALESCE({p}.{b}, 0) AS {p.replace('d', 'p')}_{b}"
        for p in ("d1", "d2")
        for b in _BASES
    )
    return f"""
        d1 AS ({_grouped_select(w1, dims)}),
        d2 AS ({_grouped_select(w2, dims)}),
        merged AS (
          SELECT {keys},
               {bases}
          FROM d1 FULL OUTER JOIN d2 ON {on}
        )"""


def _derived(src: str) -> str:
    """Margin % / Avg $P per load per side + the five P1 − P2 diffs.

    The ONE definition for rows and totals. A side with no revenue has no
    margin; a diff with a missing side is NULL ("—"), never a fake ±100%.
    """
    def margin(p: str) -> str:
        return (
            f"CASE WHEN {src}.{p}_revenue <> 0 "
            f"THEN {src}.{p}_profit / {src}.{p}_revenue * 100 END"
        )

    def avg_p(p: str) -> str:
        return (
            f"CASE WHEN {src}.{p}_load_ids > 0 "
            f"THEN {src}.{p}_profit / {src}.{p}_load_ids END"
        )

    return ",\n          ".join([
        f"{margin('p1')} AS p1_margin",
        f"{margin('p2')} AS p2_margin",
        f"{avg_p('p1')} AS p1_avg_p",
        f"{avg_p('p2')} AS p2_avg_p",
        f"{src}.p1_loads - {src}.p2_loads AS diff_loads",
        f"{src}.p1_revenue - {src}.p2_revenue AS diff_revenue",
        f"{src}.p1_profit - {src}.p2_profit AS diff_profit",
        f"({margin('p1')}) - ({margin('p2')}) AS diff_margin",
        f"({avg_p('p1')}) - ({avg_p('p2')}) AS diff_avg_p",
    ])


def _sum_bases(src: str, extra: str = "") -> str:
    sums = ", ".join(
        f"SUM({p}_{b}) AS {p}_{b}" for p in ("p1", "p2") for b in _BASES
    )
    return f"SELECT COUNT(*) AS n_rows, {sums}{extra} FROM {src}"


def _order_by(sort: str, name_col: str) -> tuple[str, str]:
    """Validate `sort` → (ORDER BY body, column). Unknown key = 400."""
    col, _, direction = sort.rpartition("_")
    if direction not in ("asc", "desc") or col not in (*SORT_COLUMNS, name_col):
        raise HTTPException(status_code=400, detail=f"unknown sort: {sort}")
    d = direction.upper()
    if col == name_col:
        return f"{name_col} {d}", col
    return f"{col} {d} NULLS LAST, {name_col} ASC", col


def _side(j: dict, p: str) -> dict:
    return {
        "loads": int(j[f"{p}_loads"] or 0),
        "revenue": float(j[f"{p}_revenue"] or 0),
        "profit": float(j[f"{p}_profit"] or 0),
        "margin_pct": _f(j[f"{p}_margin"]),
        "avg_p_per_l": _f(j[f"{p}_avg_p"]),
    }


def _f(v) -> Optional[float]:
    return None if v is None else float(v)


def _shape(j: dict, dims: tuple[str, ...]) -> dict:
    out = {d: j[d] for d in dims}
    out["p1"] = _side(j, "p1")
    out["p2"] = _side(j, "p2")
    out["diff"] = {
        "loads": int(j["diff_loads"] or 0),
        "revenue": float(j["diff_revenue"] or 0),
        "profit": float(j["diff_profit"] or 0),
        "margin_pct": _f(j["diff_margin"]),
        "avg_p_per_l": _f(j["diff_avg_p"]),
    }
    return out


def _load_json(v):
    return json.loads(v) if isinstance(v, str) else v


async def _compare_table(
    request: Request,
    dim: str,
    panels: tuple[tuple, tuple],
    sort: str,
    page: int,
    limit: int,
) -> dict:
    """Flat combined table (Details by Customer / Details by Lane)."""
    order, _col = _order_by(sort, dim)
    pool = get_datalake_gold_pool(request)
    params: list = []
    w1, *_ = _bind_panel(*panels[0], params)
    w2, *_ = _bind_panel(*panels[1], params)
    params.extend([(page - 1) * limit, limit])
    off_p, lim_p = len(params) - 1, len(params)
    dims = (dim,)

    rows = await pool.fetch(
        f"""
        WITH {_merged_cte(w1, w2, dims)},
        calc AS (SELECT merged.*, {_derived("merged")} FROM merged),
        ranked AS (SELECT calc.*, ROW_NUMBER() OVER (ORDER BY {order}) AS rn FROM calc),
        tot AS ({_sum_bases("merged")}),
        tot_calc AS (SELECT tot.*, {_derived("tot")} FROM tot)
        SELECT 0 AS lvl, r.rn AS rn, row_to_json(r) AS j
        FROM ranked r
        WHERE r.rn > ${off_p} AND r.rn <= ${off_p} + ${lim_p}
        UNION ALL
        SELECT 2 AS lvl, 0 AS rn, row_to_json(t) AS j FROM tot_calc t
        ORDER BY lvl, rn
        """,
        *params,
    )
    data, totals = [], None
    for r in rows:
        j = _load_json(r["j"])
        if r["lvl"] == 2:
            totals = j
        else:
            data.append(_shape(j, dims))
    return {
        "success": True,
        "data": data,
        "meta": {
            "total": int(totals["n_rows"] or 0) if totals else 0,
            "page": page,
            "limit": limit,
            "sort": sort,
            "totals": _shape({**totals, dim: None}, dims) if totals else None,
        },
    }


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
    sort: str = Query(DEFAULT_SORT),
    page: int = Query(1, ge=1),
    limit: int = Query(200, ge=1, le=1000),
    _user: dict = Depends(require_report_access("ops-direct-compare", "ceo-executive")),
):
    """Details by Customer — both panels + P1 − P2 diffs, one row per customer."""
    return await _compare_table(
        request, "customer",
        (
            (p1_range, p1_start_date, p1_end_date, p1_division, p1_teams, p1_sub_teams),
            (p2_range, p2_start_date, p2_end_date, p2_division, p2_teams, p2_sub_teams),
        ),
        sort, page, limit,
    )


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
    sort: str = Query(DEFAULT_SORT),
    page: int = Query(1, ge=1),
    limit: int = Query(200, ge=1, le=1000),
    _user: dict = Depends(require_report_access("ops-direct-compare", "ceo-executive")),
):
    """Details by Lane — both panels + P1 − P2 diffs, one row per lane.

    ~3.6k lanes YTD, so this one is genuinely paged — the UI shows a pager.
    """
    return await _compare_table(
        request, "lane",
        (
            (p1_range, p1_start_date, p1_end_date, p1_division, p1_teams, p1_sub_teams),
            (p2_range, p2_start_date, p2_end_date, p2_division, p2_teams, p2_sub_teams),
        ),
        sort, page, limit,
    )


@router.get("/by-customer-lane-diff")
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
    sort: str = Query(DEFAULT_SORT),
    page: int = Query(1, ge=1),
    limit: int = Query(200, ge=1, le=1000),
    _user: dict = Depends(require_report_access("ops-direct-compare", "ceo-executive")),
):
    """Customer → Lane pivot. Customers are paged + sorted; each carries ALL its
    lanes (sorted by the same column). A customer row is the SUM of its lanes —
    aggregated from the lane grain, never re-queried — so the parent always
    reconciles with its children and with Details by Customer.
    """
    order, col = _order_by(sort, "customer")
    lane_order = "lane ASC" if col == "customer" else _order_by(f"{col}_{sort.rpartition('_')[2]}", "lane")[0]
    pool = get_datalake_gold_pool(request)
    params: list = []
    w1, *_ = _bind_panel(
        p1_range, p1_start_date, p1_end_date, p1_division, p1_teams, p1_sub_teams, params,
    )
    w2, *_ = _bind_panel(
        p2_range, p2_start_date, p2_end_date, p2_division, p2_teams, p2_sub_teams, params,
    )
    params.extend([(page - 1) * limit, limit])
    off_p, lim_p = len(params) - 1, len(params)
    dims = ("customer", "lane")
    cust_sums = ", ".join(
        f"SUM({p}_{b}) AS {p}_{b}" for p in ("p1", "p2") for b in _BASES
    )

    rows = await pool.fetch(
        f"""
        WITH {_merged_cte(w1, w2, dims)},
        merged_c AS (
          SELECT customer, COUNT(*) AS lane_count, {cust_sums}
          FROM merged GROUP BY customer
        ),
        calc_c AS (SELECT merged_c.*, {_derived("merged_c")} FROM merged_c),
        ranked AS (SELECT calc_c.*, ROW_NUMBER() OVER (ORDER BY {order}) AS rn FROM calc_c),
        pg AS (SELECT * FROM ranked WHERE rn > ${off_p} AND rn <= ${off_p} + ${lim_p}),
        calc_l AS (
          SELECT x.*, ROW_NUMBER() OVER (PARTITION BY x.customer ORDER BY {lane_order}) AS sub_rn
          FROM (
            SELECT merged.*, {_derived("merged")}
            FROM merged WHERE merged.customer IN (SELECT customer FROM pg)
          ) x
        ),
        tot AS ({_sum_bases("merged_c")}),
        tot_calc AS (SELECT tot.*, {_derived("tot")} FROM tot)
        SELECT 0 AS lvl, p.rn AS rn, 0::bigint AS sub_rn, row_to_json(p) AS j FROM pg p
        UNION ALL
        SELECT 1, p.rn, l.sub_rn, row_to_json(l)
        FROM calc_l l JOIN pg p ON p.customer = l.customer
        UNION ALL
        SELECT 2, 0, 0, row_to_json(t) FROM tot_calc t
        ORDER BY rn, lvl, sub_rn
        """,
        *params,
    )
    data: list[dict] = []
    totals = None
    for r in rows:
        j = _load_json(r["j"])
        if r["lvl"] == 2:
            totals = j
        elif r["lvl"] == 0:
            data.append({**_shape(j, ("customer",)),
                         "lane_count": int(j["lane_count"] or 0), "lanes": []})
        else:
            data[-1]["lanes"].append(_shape(j, ("lane",)))
    return {
        "success": True,
        "data": data,
        "meta": {
            "total": int(totals["n_rows"] or 0) if totals else 0,
            "page": page,
            "limit": limit,
            "sort": sort,
            "totals": _shape({**totals, "customer": None}, ("customer",)) if totals else None,
        },
    }


# ---------------------------------------------------------------------------
# /trend-yoy — Jan..Dec, previous year vs current year (Bruno 2026-10-01 R4).
# Replaces /trend-12m. Revenue = Σ total_charge, Profit = Σ margin_amt,
# Margin = ΣProfit / ΣRevenue. Filter-less like the chart it replaces (all
# teams; the per-team clones pass their one team). Months the current year has
# not reached are NULL, so the chart shows the previous year's bar alone.
# ⚠ The x-axis is the month NUMBER from SQL — the old chart did
# `new Date("2025-11-01")`, parsed it as UTC, and labelled every bar one month
# early in CST.
# ---------------------------------------------------------------------------

_TREND_TTL_S = 600.0  # 10 minutes
_trend_cache: dict[tuple, tuple[float, dict]] = {}
# One lock per cache key: a cold TEAM1 chart must not queue behind ALL teams.
_trend_locks: dict[tuple, asyncio.Lock] = {}
MONTH_LABELS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun",
                "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")


def _yoy_bounds(today: date) -> tuple[datetime, datetime]:
    """[Jan 1 of last year, tomorrow) — gold is already CST, so naive bounds
    against the raw column (sargable; no cast on the column)."""
    return datetime(today.year - 1, 1, 1), datetime.combine(
        today + timedelta(days=1), datetime.min.time(),
    )


def _yoy_point(rev: float, prof: float) -> dict:
    return {
        "revenue": rev,
        "profit": prof,
        "margin_pct": (prof / rev * 100.0) if rev else None,
    }


def _yoy_series(rows, today: date) -> dict:
    by_key = {
        (int(r["yr"]), int(r["mo"])): _yoy_point(
            float(r["revenue"] or 0), float(r["profit"] or 0),
        )
        for r in rows
    }
    prev_y, cur_y = today.year - 1, today.year
    months = [
        {
            "month": m,
            "label": MONTH_LABELS[m - 1],
            "prev": by_key.get((prev_y, m)),
            "cur": by_key.get((cur_y, m)) if m <= today.month else None,
        }
        for m in range(1, 13)
    ]
    return {"prev_year": prev_y, "cur_year": cur_y, "months": months}


async def trend_yoy_for_teams(request: Request, teams: list[str]) -> dict:
    """Shared by the cross-team router and the per-team clones."""
    today = cst_today()
    cache_key = (today.isoformat(), tuple(teams))
    cached = _trend_cache.get(cache_key)
    if cached and (time.monotonic() - cached[0]) < _TREND_TTL_S:
        return {"success": True, "data": cached[1], "meta": {"cached": True}}

    async with _trend_locks.setdefault(cache_key, asyncio.Lock()):
        cached = _trend_cache.get(cache_key)
        if cached and (time.monotonic() - cached[0]) < _TREND_TTL_S:
            return {"success": True, "data": cached[1], "meta": {"cached": True}}

        pool = get_datalake_gold_pool(request)
        start, end = _yoy_bounds(today)
        params: list = []
        where = _scope_where(
            "br4", list(teams), list(ALL_COMPANIES), None, None, None, None, params,
        )
        params.extend([start, end])
        rows = await pool.fetch(
            f"""
            SELECT
              EXTRACT(YEAR  FROM br4.origin_actual_departure)::int AS yr,
              EXTRACT(MONTH FROM br4.origin_actual_departure)::int AS mo,
              COALESCE(SUM(br4.total_charge) FILTER (
                WHERE br4.total_charge <> 0
              ), 0)::numeric AS revenue,
              COALESCE(SUM(br4.margin_amt), 0)::numeric AS profit
            FROM public.mcleod_gld_budget_report_v4 br4
            WHERE {where}
              AND br4.origin_actual_departure >= ${len(params) - 1}
              AND br4.origin_actual_departure <  ${len(params)}
            GROUP BY 1, 2
            ORDER BY 1, 2
            """,
            *params,
        )
        out = _yoy_series(rows, today)
        now_ts = time.monotonic()
        _trend_cache[cache_key] = (now_ts, out)
        # Drop other-day keys to keep the cache from growing forever
        for k in list(_trend_cache.keys()):
            if k[0] != cache_key[0]:
                _trend_cache.pop(k, None)
                _trend_locks.pop(k, None)
        return {"success": True, "data": out, "meta": {"cached": False}}


@router.get("/trend-yoy")
async def trend_yoy(
    request: Request,
    _user: dict = Depends(require_report_access("ops-direct-compare", "ceo-executive")),
):
    return await trend_yoy_for_teams(request, list(ALL_TEAMS))


# ---------------------------------------------------------------------------
# /freshness — last refresh stamp, same shape as ops_margins
# ---------------------------------------------------------------------------


@router.get("/freshness")
async def freshness(
    request: Request,
    _user: dict = Depends(require_report_access("ops-direct-compare", "ceo-executive")),
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
