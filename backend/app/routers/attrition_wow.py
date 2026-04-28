"""Code-made report: Attrition WoW — week-over-week customer/lane attrition.

Mirrors Bruno's Qlik app ``e6440781-a111-4b71-be83-91821330e740`` ("Attrition
Week over Week") as a portal-native report. Reads from
``public.mcleod_gld_budget_report_v4`` (datalake gold). All time windows are
**completed Mon-Sun ISO weeks**; the current (in-progress) week is excluded
from every calculation so KPIs don't bounce mid-week as new loads land.

Scope (verbatim from PDF):
- team_id        IN (TEAM1..TEAM5, TEAM-DFW)
- company_id     IN (TMS, TMS3)
- status         IN (D, P)
- customer_name  NOT LIKE '%UNILINK%'  AND  NOT LIKE '%OILTEX%'
- origin_actual_departure >= '2025-01-01'

Sargability: every varchar predicate uses ``pad_variants(width=N)``; never
wrap team_id/company_id/status in TRIM() inside WHERE/JOIN. v4 is already
stored in CST so date arithmetic uses ``::date`` directly without
``AT TIME ZONE``.

Architecture:
- One ``weekly_facts`` CTE per request (computed once, reused by every
  panel). Contains 60 ISO weeks per (team_id, customer_name, lane,
  contract_type) of loads/revenue/profit.
- Endpoints reshape that CTE for KPIs / pivots / reactive-summaries /
  trends. Frontend pivots client-side from long-form rows.
- HTTP cache 5 min on heavy endpoints; data is daily-fresh.
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, Query, Request, Response

from app.clock import cst_today
from app.datalake import pad_variants as _pad_variants
from app.routers.deps import get_datalake_gold_pool, require_tag_role

ATTRITION_ROLES = ("CEO", "Executive", "Sales", "CORP", "DFW", "Operations", "Finance")

YEAR_START = date(2025, 1, 1)  # PDF base filter

ALL_TEAMS = ("TEAM1", "TEAM2", "TEAM3", "TEAM4", "TEAM5", "TEAM-DFW")
COMPANIES = ("TMS", "TMS3")
OPEN_STATUSES = ("D", "P")

# How many ISO weeks of history we keep in the weekly_facts CTE.
# 15 weeks (trends) + 12 weeks (pivots) + 8 weeks (rolling avg) + slack.
WEEKS_HISTORY = 60

CACHE_HEADER = "public, max-age=300, stale-while-revalidate=120"

router = APIRouter(tags=["attrition-wow"], prefix="/custom/attrition-wow")


# ---------------------------------------------------------------------------
# Date helpers — Mon-Sun ISO weeks, current week excluded.
# ---------------------------------------------------------------------------


def _last_completed_week(today: Optional[date] = None) -> tuple[date, date]:
    """Return (mon, sun) of the most recent completed Mon-Sun ISO week.

    Bruno's "LAST WEEK (13 APR 26 - 19 APR 26)" anchors here.
    """
    today = today or cst_today()
    # Mon=0..Sun=6 → days back to this Monday
    this_monday = today - timedelta(days=today.weekday())
    last_sunday = this_monday - timedelta(days=1)
    last_monday = last_sunday - timedelta(days=6)
    return last_monday, last_sunday


def _l8w_window(today: Optional[date] = None) -> tuple[date, date]:
    """8 completed weeks ENDING the day before last week starts.

    PDF: "LAST 8 WEEKS (16 FEB 26 - 12 APR 26)" — 8 full weeks immediately
    preceding LAST WEEK. Total span = 56 days = 8 × 7.
    """
    lw_mon, _ = _last_completed_week(today)
    end = lw_mon - timedelta(days=1)              # Sunday of the 8-week span
    start = end - timedelta(days=8 * 7 - 1)       # 56 days inclusive
    return start, end


def _l2w_window(today: Optional[date] = None) -> tuple[date, date]:
    """The 2 most recent completed weeks (LW + LW-1)."""
    lw_mon, lw_sun = _last_completed_week(today)
    start = lw_mon - timedelta(days=7)
    return start, lw_sun


# ---------------------------------------------------------------------------
# Filter parsing & SQL helpers.
# ---------------------------------------------------------------------------


def _parse_csv(raw: Optional[str], allowed: tuple[str, ...]) -> list[str]:
    if not raw:
        return list(allowed)
    wanted = [t.strip() for t in raw.split(",") if t.strip()]
    s = {t for t in allowed}
    return [t for t in wanted if t in s] or list(allowed)


def _scope_where(
    alias: str,
    teams: list[str],
    customer: Optional[str],
    contract: Optional[str],
    lane: Optional[str],
    params: list,
) -> str:
    """Common WHERE for v4. Appends positional params."""
    params.append(_pad_variants(teams, width=8))
    p_teams = len(params)
    params.append(_pad_variants(COMPANIES, width=4))
    p_companies = len(params)
    params.append(_pad_variants(OPEN_STATUSES, width=1))
    p_status = len(params)

    parts = [
        f"{alias}.team_id    = ANY(${p_teams})",
        f"{alias}.company_id = ANY(${p_companies})",
        f"{alias}.status     = ANY(${p_status})",
        f"UPPER(COALESCE({alias}.customer_name,'')) NOT LIKE '%UNILINK%'",
        f"UPPER(COALESCE({alias}.customer_name,'')) NOT LIKE '%OILTEX%'",
    ]
    if customer:
        params.append(customer)
        parts.append(f"TRIM({alias}.customer_name) = TRIM(${len(params)})")
    if contract:
        params.append(contract)
        parts.append(
            f"UPPER(COALESCE({alias}.contract_type_descr,'')) = UPPER(${len(params)})"
        )
    if lane:
        params.append(lane)
        parts.append(f"({_lane_expr(alias)}) = ${len(params)}")
    return " AND ".join(parts)


def _lane_expr(alias: str) -> str:
    """Bruno's lane = concat(trim(origin_name), ' - ', trim(dest_name))."""
    return (
        f"TRIM(COALESCE({alias}.origin_name,'')) "
        f"|| ' - ' || "
        f"TRIM(COALESCE({alias}.dest_name,''))"
    )


def _weekly_cte(scope_where: str, weeks_back: int = WEEKS_HISTORY) -> str:
    """A reusable CTE that buckets v4 into Mon-anchored ISO weeks.

    Excludes the current (in-progress) week so KPIs don't bounce.
    Returns SQL that produces columns:
      week_start (date, Monday), team_id, customer_id, customer_name,
      lane, contract_type, loads, revenue, profit.
    """
    return f"""
    WITH bounds AS (
      SELECT
        date_trunc('week', CURRENT_DATE)::date              AS this_monday,
        (date_trunc('week', CURRENT_DATE) - interval '{weeks_back} weeks')::date AS first_monday
    ),
    base AS (
      SELECT
        date_trunc('week', br4.origin_actual_departure)::date AS week_start,
        TRIM(br4.team_id)        AS team_id,
        TRIM(br4.customer_id)    AS customer_id,
        TRIM(br4.customer_name)  AS customer_name,
        {_lane_expr("br4")}      AS lane,
        UPPER(TRIM(COALESCE(br4.contract_type_descr,''))) AS contract_type,
        br4.id                   AS load_id,
        br4.total_charge,
        br4.margin_amt,
        br4.origin_actual_departure::date AS dep_date
      FROM public.mcleod_gld_budget_report_v4 br4, bounds b
      WHERE {scope_where}
        AND br4.origin_actual_departure >= b.first_monday
        AND br4.origin_actual_departure <  b.this_monday
    )
    """


# ---------------------------------------------------------------------------
# /filters — distinct customers / contract types / lanes for dropdowns.
# ---------------------------------------------------------------------------


@router.get("/filters")
async def filters(
    request: Request,
    response: Response,
    _user: dict = Depends(require_tag_role(*ATTRITION_ROLES)),
):
    pool = get_datalake_gold_pool(request)
    response.headers["Cache-Control"] = CACHE_HEADER

    # Customers + contract types + lanes from the last WEEKS_HISTORY weeks.
    rows = await pool.fetch(
        f"""
        SELECT
          DISTINCT TRIM(customer_name) AS customer_name,
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
        _pad_variants(ALL_TEAMS, width=8),
        _pad_variants(COMPANIES, width=4),
        _pad_variants(OPEN_STATUSES, width=1),
        YEAR_START,
    )
    customers = sorted({r["customer_name"] for r in rows if r["customer_name"]})
    contracts = sorted({r["contract_type"] for r in rows if r["contract_type"]})

    return {
        "success": True,
        "data": {
            "teams": list(ALL_TEAMS),
            "customers": customers,
            "contract_types": contracts,
        },
    }


# ---------------------------------------------------------------------------
# /freshness — last load date in scope; powers the data-refreshed pill.
# ---------------------------------------------------------------------------


@router.get("/freshness")
async def freshness(
    request: Request,
    response: Response,
    _user: dict = Depends(require_tag_role(*ATTRITION_ROLES)),
):
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
        _pad_variants(ALL_TEAMS, width=8),
        _pad_variants(COMPANIES, width=4),
        _pad_variants(OPEN_STATUSES, width=1),
        YEAR_START,
    )
    lw_mon, lw_sun = _last_completed_week()
    return {
        "success": True,
        "data": {
            "last_load_date": row["last_load_date"].isoformat() if row and row["last_load_date"] else None,
            "rows_in_scope": int(row["rows_in_scope"] or 0) if row else 0,
            "last_completed_week": {
                "start": lw_mon.isoformat(),
                "end": lw_sun.isoformat(),
            },
        },
    }


# ---------------------------------------------------------------------------
# /summary — 7 KPI rows (Active Lanes/Customers, Loads, Rev, Profit, Margin,
# $/Load) with L8W avg, LW value, L2W avg, and diffs.
# ---------------------------------------------------------------------------


@router.get("/summary")
async def summary(
    request: Request,
    response: Response,
    teams: Optional[str] = Query(None),
    customer: Optional[str] = Query(None),
    contract: Optional[str] = Query(None),
    lane: Optional[str] = Query(None),
    _user: dict = Depends(require_tag_role(*ATTRITION_ROLES)),
):
    pool = get_datalake_gold_pool(request)
    response.headers["Cache-Control"] = CACHE_HEADER

    team_list = _parse_csv(teams, ALL_TEAMS)
    l8w_start, l8w_end = _l8w_window()
    lw_start, lw_end = _last_completed_week()
    l2w_start, l2w_end = _l2w_window()

    params: list = []
    where = _scope_where("br4", team_list, customer, contract, lane, params)
    # Date-window params (windows are inclusive-inclusive)
    params.extend([l8w_start, l8w_end])
    p_l8s, p_l8e = len(params) - 1, len(params)
    params.extend([lw_start, lw_end])
    p_lws, p_lwe = len(params) - 1, len(params)
    params.extend([l2w_start, l2w_end])
    p_l2s, p_l2e = len(params) - 1, len(params)

    row = await pool.fetchrow(
        f"""
        WITH base AS (
          SELECT
            br4.origin_actual_departure::date  AS dep_date,
            br4.id                             AS load_id,
            br4.total_charge,
            br4.margin_amt,
            {_lane_expr("br4")}                AS lane,
            TRIM(br4.customer_name)            AS customer_name
          FROM public.mcleod_gld_budget_report_v4 br4
          WHERE {where}
            AND br4.origin_actual_departure::date BETWEEN ${p_l8s} AND ${p_lwe}
        )
        SELECT
          -- L8W (avg per week over 8 weeks)
          COUNT(DISTINCT lane)          FILTER (WHERE dep_date BETWEEN ${p_l8s} AND ${p_l8e}) AS l8w_lanes,
          COUNT(DISTINCT customer_name) FILTER (WHERE dep_date BETWEEN ${p_l8s} AND ${p_l8e}) AS l8w_customers,
          COUNT(*) FILTER (WHERE total_charge <> 0 AND dep_date BETWEEN ${p_l8s} AND ${p_l8e}) AS l8w_loads,
          COALESCE(SUM(total_charge) FILTER (WHERE dep_date BETWEEN ${p_l8s} AND ${p_l8e}), 0) AS l8w_rev,
          COALESCE(SUM(margin_amt)   FILTER (WHERE dep_date BETWEEN ${p_l8s} AND ${p_l8e}), 0) AS l8w_profit,

          -- LW (last completed week)
          COUNT(DISTINCT lane)          FILTER (WHERE dep_date BETWEEN ${p_lws} AND ${p_lwe}) AS lw_lanes,
          COUNT(DISTINCT customer_name) FILTER (WHERE dep_date BETWEEN ${p_lws} AND ${p_lwe}) AS lw_customers,
          COUNT(*) FILTER (WHERE total_charge <> 0 AND dep_date BETWEEN ${p_lws} AND ${p_lwe}) AS lw_loads,
          COALESCE(SUM(total_charge) FILTER (WHERE dep_date BETWEEN ${p_lws} AND ${p_lwe}), 0) AS lw_rev,
          COALESCE(SUM(margin_amt)   FILTER (WHERE dep_date BETWEEN ${p_lws} AND ${p_lwe}), 0) AS lw_profit,

          -- L2W (avg per week over the 2 most recent completed weeks)
          COUNT(*) FILTER (WHERE total_charge <> 0 AND dep_date BETWEEN ${p_l2s} AND ${p_l2e}) AS l2w_loads,
          COALESCE(SUM(total_charge) FILTER (WHERE dep_date BETWEEN ${p_l2s} AND ${p_l2e}), 0) AS l2w_rev,
          COALESCE(SUM(margin_amt)   FILTER (WHERE dep_date BETWEEN ${p_l2s} AND ${p_l2e}), 0) AS l2w_profit
        FROM base
        """,
        *params,
    )

    def _f(v) -> float:
        return float(v) if v is not None else 0.0

    # Counts (raw, not averages) for active lanes/customers
    l8w_lanes = int(row["l8w_lanes"] or 0)
    lw_lanes = int(row["lw_lanes"] or 0)
    l8w_customers = int(row["l8w_customers"] or 0)
    lw_customers = int(row["lw_customers"] or 0)

    # Per-week averages
    avg_l8w_loads   = _f(row["l8w_loads"])  / 8.0
    avg_l8w_rev     = _f(row["l8w_rev"])    / 8.0
    avg_l8w_profit  = _f(row["l8w_profit"]) / 8.0
    avg_l8w_margin  = (avg_l8w_profit / avg_l8w_rev) if avg_l8w_rev else None
    avg_l8w_perload = (avg_l8w_profit / avg_l8w_loads) if avg_l8w_loads else None

    lw_loads_v   = int(row["lw_loads"] or 0)
    lw_rev_v     = _f(row["lw_rev"])
    lw_profit_v  = _f(row["lw_profit"])
    lw_margin_v  = (lw_profit_v / lw_rev_v) if lw_rev_v else None
    lw_perload_v = (lw_profit_v / lw_loads_v) if lw_loads_v else None

    avg_l2w_loads   = _f(row["l2w_loads"])  / 2.0
    avg_l2w_rev     = _f(row["l2w_rev"])    / 2.0
    avg_l2w_profit  = _f(row["l2w_profit"]) / 2.0
    avg_l2w_margin  = (avg_l2w_profit / avg_l2w_rev) if avg_l2w_rev else None
    avg_l2w_perload = (avg_l2w_profit / avg_l2w_loads) if avg_l2w_loads else None

    def _diff(curr: Optional[float], base: Optional[float]) -> dict:
        if curr is None or base is None:
            return {"diff": None, "pct": None}
        d = curr - base
        pct = (d / base) if base not in (0, 0.0) else None
        return {"diff": d, "pct": pct}

    return {
        "success": True,
        "data": {
            "windows": {
                "l8w":  {"start": l8w_start.isoformat(), "end": l8w_end.isoformat()},
                "lw":   {"start": lw_start.isoformat(),  "end": lw_end.isoformat()},
                "l2w":  {"start": l2w_start.isoformat(), "end": l2w_end.isoformat()},
            },
            "active_lanes": {
                "l8w": l8w_lanes,
                "lw":  lw_lanes,
                **_diff(lw_lanes, l8w_lanes),
            },
            "active_customers": {
                "l8w": l8w_customers,
                "lw":  lw_customers,
                **_diff(lw_customers, l8w_customers),
            },
            "loads": {
                "l8w_avg": avg_l8w_loads,
                "lw":      lw_loads_v,
                "l2w_avg": avg_l2w_loads,
                "diff_lw_vs_l8w":  _diff(lw_loads_v, avg_l8w_loads),
                "diff_l2w_vs_l8w": _diff(avg_l2w_loads, avg_l8w_loads),
            },
            "revenue": {
                "l8w_avg": avg_l8w_rev,
                "lw":      lw_rev_v,
                "l2w_avg": avg_l2w_rev,
                "diff_lw_vs_l8w":  _diff(lw_rev_v, avg_l8w_rev),
                "diff_l2w_vs_l8w": _diff(avg_l2w_rev, avg_l8w_rev),
            },
            "profit": {
                "l8w_avg": avg_l8w_profit,
                "lw":      lw_profit_v,
                "l2w_avg": avg_l2w_profit,
                "diff_lw_vs_l8w":  _diff(lw_profit_v, avg_l8w_profit),
                "diff_l2w_vs_l8w": _diff(avg_l2w_profit, avg_l8w_profit),
            },
            "margin_pct": {
                "l8w_avg": avg_l8w_margin,
                "lw":      lw_margin_v,
                "l2w_avg": avg_l2w_margin,
                "diff_lw_vs_l8w":  _diff(lw_margin_v, avg_l8w_margin),
                "diff_l2w_vs_l8w": _diff(avg_l2w_margin, avg_l8w_margin),
            },
            "profit_per_load": {
                "l8w_avg": avg_l8w_perload,
                "lw":      lw_perload_v,
                "l2w_avg": avg_l2w_perload,
                "diff_lw_vs_l8w":  _diff(lw_perload_v, avg_l8w_perload),
                "diff_l2w_vs_l8w": _diff(avg_l2w_perload, avg_l8w_perload),
            },
        },
    }


# ---------------------------------------------------------------------------
# /weekly-trends — bar charts: 15 weeks of loads, customers, rev, profit,
# margin. Uses generate_series so empty weeks render as zero rather than
# missing bars.
# ---------------------------------------------------------------------------


@router.get("/weekly-trends")
async def weekly_trends(
    request: Request,
    response: Response,
    weeks: int = Query(15, ge=4, le=24),
    teams: Optional[str] = Query(None),
    customer: Optional[str] = Query(None),
    contract: Optional[str] = Query(None),
    lane: Optional[str] = Query(None),
    _user: dict = Depends(require_tag_role(*ATTRITION_ROLES)),
):
    pool = get_datalake_gold_pool(request)
    response.headers["Cache-Control"] = CACHE_HEADER

    team_list = _parse_csv(teams, ALL_TEAMS)

    params: list = []
    where = _scope_where("br4", team_list, customer, contract, lane, params)
    params.append(weeks)
    p_weeks = len(params)

    rows = await pool.fetch(
        f"""
        WITH bounds AS (
          SELECT
            date_trunc('week', CURRENT_DATE)::date AS this_monday,
            (date_trunc('week', CURRENT_DATE) - (${p_weeks} * interval '1 week'))::date AS first_monday
        ),
        weeks AS (
          SELECT generate_series(b.first_monday, b.this_monday - interval '1 week', interval '1 week')::date AS week_start
          FROM bounds b
        ),
        base AS (
          SELECT
            date_trunc('week', br4.origin_actual_departure)::date AS week_start,
            br4.id                               AS load_id,
            br4.total_charge,
            br4.margin_amt,
            TRIM(br4.customer_name)              AS customer_name
          FROM public.mcleod_gld_budget_report_v4 br4, bounds b
          WHERE {where}
            AND br4.origin_actual_departure >= b.first_monday
            AND br4.origin_actual_departure <  b.this_monday
        ),
        agg AS (
          SELECT
            week_start,
            COUNT(*) FILTER (WHERE total_charge <> 0)                AS loads,
            COUNT(DISTINCT customer_name)                            AS customers,
            COALESCE(SUM(total_charge), 0)::numeric                  AS revenue,
            COALESCE(SUM(margin_amt),   0)::numeric                  AS profit
          FROM base
          GROUP BY week_start
        )
        SELECT
          w.week_start,
          COALESCE(a.loads, 0)     AS loads,
          COALESCE(a.customers, 0) AS customers,
          COALESCE(a.revenue, 0)   AS revenue,
          COALESCE(a.profit, 0)    AS profit
        FROM weeks w
        LEFT JOIN agg a USING (week_start)
        ORDER BY w.week_start
        """,
        *params,
    )

    out = []
    for r in rows:
        rev = float(r["revenue"] or 0)
        prof = float(r["profit"] or 0)
        out.append({
            "week_start": r["week_start"].isoformat(),
            "loads":      int(r["loads"] or 0),
            "customers":  int(r["customers"] or 0),
            "revenue":    rev,
            "profit":     prof,
            "margin_pct": (prof / rev) if rev else None,
        })

    # 8-week rolling reference values (avg over the 8 most recent COMPLETED
    # weeks — same window the front-end's red/green coloring uses).
    l8w_start, l8w_end = _l8w_window()
    ref_rows = [r for r in out if l8w_start.isoformat() <= r["week_start"] <= l8w_end.isoformat()]
    if ref_rows:
        avg_loads     = sum(r["loads"]    for r in ref_rows) / len(ref_rows)
        avg_customers = sum(r["customers"] for r in ref_rows) / len(ref_rows)
        avg_revenue   = sum(r["revenue"]  for r in ref_rows) / len(ref_rows)
        avg_profit    = sum(r["profit"]   for r in ref_rows) / len(ref_rows)
        # Margin % = ratio of sums (not avg of ratios)
        sum_rev = sum(r["revenue"] for r in ref_rows)
        sum_prof = sum(r["profit"]  for r in ref_rows)
        avg_margin = (sum_prof / sum_rev) if sum_rev else None
    else:
        avg_loads = avg_customers = avg_revenue = avg_profit = 0
        avg_margin = None

    return {
        "success": True,
        "data": {
            "weeks": out,
            "reference": {
                "l8w_avg_loads":     avg_loads,
                "l8w_avg_customers": avg_customers,
                "l8w_avg_revenue":   avg_revenue,
                "l8w_avg_profit":    avg_profit,
                "l8w_avg_margin":    avg_margin,
            },
        },
    }


# ---------------------------------------------------------------------------
# /pivot — last-N-weeks pivot rows, by customer or by team, for a metric.
# Frontend renders the wide pivot client-side (long form keeps payload small).
# ---------------------------------------------------------------------------


@router.get("/pivot")
async def pivot(
    request: Request,
    response: Response,
    dim: str = Query("customer", regex="^(customer|team)$"),
    metric: str = Query("loads", regex="^(loads|revenue|profit|margin)$"),
    weeks: int = Query(12, ge=4, le=24),
    teams: Optional[str] = Query(None),
    customer: Optional[str] = Query(None),
    contract: Optional[str] = Query(None),
    lane: Optional[str] = Query(None),
    _user: dict = Depends(require_tag_role(*ATTRITION_ROLES)),
):
    pool = get_datalake_gold_pool(request)
    response.headers["Cache-Control"] = CACHE_HEADER

    team_list = _parse_csv(teams, ALL_TEAMS)
    params: list = []
    where = _scope_where("br4", team_list, customer, contract, lane, params)
    params.append(weeks)
    p_weeks = len(params)

    dim_sql = "TRIM(br4.customer_name)" if dim == "customer" else "TRIM(br4.team_id)"

    if metric == "loads":
        agg_sql = "COUNT(*) FILTER (WHERE br4.total_charge <> 0)::numeric"
    elif metric == "revenue":
        agg_sql = "COALESCE(SUM(br4.total_charge), 0)::numeric"
    elif metric == "profit":
        agg_sql = "COALESCE(SUM(br4.margin_amt), 0)::numeric"
    else:  # margin (will be computed as profit/rev in a wrapper)
        agg_sql = "NULL::numeric"  # placeholder; we'll select rev+profit separately

    if metric == "margin":
        rows = await pool.fetch(
            f"""
            WITH bounds AS (
              SELECT
                date_trunc('week', CURRENT_DATE)::date AS this_monday,
                (date_trunc('week', CURRENT_DATE) - (${p_weeks} * interval '1 week'))::date AS first_monday
            )
            SELECT
              date_trunc('week', br4.origin_actual_departure)::date AS week_start,
              {dim_sql}                                              AS dim_key,
              COALESCE(SUM(br4.total_charge), 0)::numeric            AS revenue,
              COALESCE(SUM(br4.margin_amt),   0)::numeric            AS profit
            FROM public.mcleod_gld_budget_report_v4 br4, bounds b
            WHERE {where}
              AND br4.origin_actual_departure >= b.first_monday
              AND br4.origin_actual_departure <  b.this_monday
            GROUP BY 1, 2
            HAVING {dim_sql} IS NOT NULL AND {dim_sql} <> ''
            ORDER BY 2, 1
            """,
            *params,
        )
        data = []
        for r in rows:
            rev = float(r["revenue"] or 0)
            prof = float(r["profit"] or 0)
            data.append({
                "week_start": r["week_start"].isoformat(),
                "dim_key":    r["dim_key"],
                "value":      (prof / rev) if rev else None,
            })
    else:
        rows = await pool.fetch(
            f"""
            WITH bounds AS (
              SELECT
                date_trunc('week', CURRENT_DATE)::date AS this_monday,
                (date_trunc('week', CURRENT_DATE) - (${p_weeks} * interval '1 week'))::date AS first_monday
            )
            SELECT
              date_trunc('week', br4.origin_actual_departure)::date AS week_start,
              {dim_sql}                                              AS dim_key,
              {agg_sql}                                              AS val
            FROM public.mcleod_gld_budget_report_v4 br4, bounds b
            WHERE {where}
              AND br4.origin_actual_departure >= b.first_monday
              AND br4.origin_actual_departure <  b.this_monday
            GROUP BY 1, 2
            HAVING {dim_sql} IS NOT NULL AND {dim_sql} <> ''
            ORDER BY 2, 1
            """,
            *params,
        )
        data = [
            {
                "week_start": r["week_start"].isoformat(),
                "dim_key":    r["dim_key"],
                "value":      float(r["val"] or 0),
            }
            for r in rows
        ]

    return {"success": True, "data": data, "meta": {"dim": dim, "metric": metric, "weeks": weeks}}


# ---------------------------------------------------------------------------
# /reactive-summary — per-customer reactive tables segmented by Days Since
# Last Load. Bucket categories: 1-7 (LW), 8-28 (L2-4W), 29-63 (L5-9W), >63
# (more than 9 weeks), 249-365 (SPOT-stale-1y).
# ---------------------------------------------------------------------------


@router.get("/reactive-summary")
async def reactive_summary(
    request: Request,
    response: Response,
    teams: Optional[str] = Query(None),
    customer: Optional[str] = Query(None),
    contract: Optional[str] = Query(None),
    _user: dict = Depends(require_tag_role(*ATTRITION_ROLES)),
):
    """Returns per (team, customer) row:
       - avg_loads_l8w / l2_4w / l5_9w
       - avg_rev_l8w / l2_4w / l5_9w
       - avg_profit_l8w / l2_4w / l5_9w
       - avg_margin_l8w / l2_4w / l5_9w
       - load_diff, % var (loads + rev + profit)
       - last_load_date, days_since_last_load
       - bucket: 'lw' | 'l2_4w' | 'l5_9w' | 'gt_9w' | 'spot_stale'
       - reactive_this_week (boolean)
    """
    pool = get_datalake_gold_pool(request)
    response.headers["Cache-Control"] = CACHE_HEADER

    team_list = _parse_csv(teams, ALL_TEAMS)
    today = cst_today()
    l8w_start, l8w_end = _l8w_window(today)
    lw_start, lw_end = _last_completed_week(today)
    # L2-4W = 3 weeks ending the day before LW starts (per PDF "previous 4
    # weeks, starting 1 week ago"/3 — Bruno's L2-4W is weeks -2..-4 averaged
    # over 3).
    l24_end = lw_start - timedelta(days=1)
    l24_start = l24_end - timedelta(days=3 * 7 - 1)
    # L5-9W = 5 weeks averaged: weeks -5..-9
    l59_end = l24_start - timedelta(days=1)
    l59_start = l59_end - timedelta(days=5 * 7 - 1)
    # Earliest week we need to read for any of the above:
    earliest = l59_start

    params: list = []
    where = _scope_where("br4", team_list, customer, contract, None, params)
    params.extend([
        earliest, l59_start, l59_end, l24_start, l24_end, l8w_start, l8w_end,
        lw_start, lw_end, today,
    ])
    (p_earliest, p_l59s, p_l59e, p_l24s, p_l24e, p_l8s, p_l8e,
     p_lws, p_lwe, p_today) = range(len(params) - 9, len(params) + 1)

    rows = await pool.fetch(
        f"""
        WITH base AS (
          SELECT
            br4.origin_actual_departure::date AS dep_date,
            TRIM(br4.team_id)                 AS team_id,
            TRIM(br4.customer_name)           AS customer_name,
            br4.id                            AS load_id,
            br4.total_charge,
            br4.margin_amt
          FROM public.mcleod_gld_budget_report_v4 br4
          WHERE {where}
            AND br4.origin_actual_departure::date >= ${p_earliest}
        ),
        per_cust AS (
          SELECT
            team_id,
            customer_name,
            -- L8W (8 weeks immediately before LW)
            COUNT(*) FILTER (WHERE total_charge <> 0 AND dep_date BETWEEN ${p_l8s} AND ${p_l8e}) / 8.0 AS avg_loads_l8w,
            COALESCE(SUM(total_charge) FILTER (WHERE dep_date BETWEEN ${p_l8s} AND ${p_l8e}), 0) / 8.0 AS avg_rev_l8w,
            COALESCE(SUM(margin_amt)   FILTER (WHERE dep_date BETWEEN ${p_l8s} AND ${p_l8e}), 0) / 8.0 AS avg_profit_l8w,
            COALESCE(SUM(total_charge) FILTER (WHERE dep_date BETWEEN ${p_l8s} AND ${p_l8e}), 0)       AS sum_rev_l8w,
            COALESCE(SUM(margin_amt)   FILTER (WHERE dep_date BETWEEN ${p_l8s} AND ${p_l8e}), 0)       AS sum_prof_l8w,
            -- L2-4W (3 weeks averaged)
            COUNT(*) FILTER (WHERE total_charge <> 0 AND dep_date BETWEEN ${p_l24s} AND ${p_l24e}) / 3.0 AS avg_loads_l2_4w,
            COALESCE(SUM(total_charge) FILTER (WHERE dep_date BETWEEN ${p_l24s} AND ${p_l24e}), 0) / 3.0 AS avg_rev_l2_4w,
            COALESCE(SUM(margin_amt)   FILTER (WHERE dep_date BETWEEN ${p_l24s} AND ${p_l24e}), 0) / 3.0 AS avg_profit_l2_4w,
            COALESCE(SUM(total_charge) FILTER (WHERE dep_date BETWEEN ${p_l24s} AND ${p_l24e}), 0)       AS sum_rev_l2_4w,
            COALESCE(SUM(margin_amt)   FILTER (WHERE dep_date BETWEEN ${p_l24s} AND ${p_l24e}), 0)       AS sum_prof_l2_4w,
            -- L5-9W (5 weeks averaged)
            COUNT(*) FILTER (WHERE total_charge <> 0 AND dep_date BETWEEN ${p_l59s} AND ${p_l59e}) / 5.0 AS avg_loads_l5_9w,
            COALESCE(SUM(total_charge) FILTER (WHERE dep_date BETWEEN ${p_l59s} AND ${p_l59e}), 0) / 5.0 AS avg_rev_l5_9w,
            COALESCE(SUM(margin_amt)   FILTER (WHERE dep_date BETWEEN ${p_l59s} AND ${p_l59e}), 0) / 5.0 AS avg_profit_l5_9w,
            COALESCE(SUM(total_charge) FILTER (WHERE dep_date BETWEEN ${p_l59s} AND ${p_l59e}), 0)       AS sum_rev_l5_9w,
            COALESCE(SUM(margin_amt)   FILTER (WHERE dep_date BETWEEN ${p_l59s} AND ${p_l59e}), 0)       AS sum_prof_l5_9w,
            -- Last week (raw, not averaged)
            COUNT(*) FILTER (WHERE total_charge <> 0 AND dep_date BETWEEN ${p_lws} AND ${p_lwe}) AS lw_loads,
            COALESCE(SUM(total_charge) FILTER (WHERE dep_date BETWEEN ${p_lws} AND ${p_lwe}), 0) AS lw_rev,
            COALESCE(SUM(margin_amt)   FILTER (WHERE dep_date BETWEEN ${p_lws} AND ${p_lwe}), 0) AS lw_profit,
            -- Last load date
            MAX(dep_date) AS last_load_date,
            -- Reactive flag: had at least 1 paying load this current (in-progress) week
            BOOL_OR(total_charge <> 0 AND dep_date >= date_trunc('week', CURRENT_DATE)::date) AS reactive_this_week
          FROM base
          GROUP BY team_id, customer_name
        )
        SELECT *,
          (${p_today} - last_load_date) AS days_since_last_load
        FROM per_cust
        WHERE customer_name IS NOT NULL AND customer_name <> ''
        """,
        *params,
    )

    def _bucket(days: Optional[int]) -> str:
        if days is None:
            return "no_load"
        if days <= 7:
            return "lw"
        if days <= 28:
            return "l2_4w"
        if days <= 63:
            return "l5_9w"
        if days <= 248:
            return "spot_recent"
        if days <= 365:
            return "spot_stale"
        return "gt_1y"

    def _pct_var(curr: float, base: float) -> Optional[float]:
        # Bruno's var formula: (curr - base) / abs(base) (sign of base preserved)
        if base == 0:
            return None
        return (curr - base) / abs(base)

    out = []
    for r in rows:
        days = int(r["days_since_last_load"]) if r["days_since_last_load"] is not None else None
        out.append({
            "team":              r["team_id"],
            "customer":          r["customer_name"],
            "avg_loads_l8w":     float(r["avg_loads_l8w"] or 0),
            "avg_rev_l8w":       float(r["avg_rev_l8w"] or 0),
            "avg_profit_l8w":    float(r["avg_profit_l8w"] or 0),
            "avg_margin_l8w": (
                float(r["sum_prof_l8w"]) / float(r["sum_rev_l8w"])
                if r["sum_rev_l8w"] else None
            ),
            "avg_loads_l2_4w":   float(r["avg_loads_l2_4w"] or 0),
            "avg_rev_l2_4w":     float(r["avg_rev_l2_4w"] or 0),
            "avg_profit_l2_4w":  float(r["avg_profit_l2_4w"] or 0),
            "avg_margin_l2_4w": (
                float(r["sum_prof_l2_4w"]) / float(r["sum_rev_l2_4w"])
                if r["sum_rev_l2_4w"] else None
            ),
            "avg_loads_l5_9w":   float(r["avg_loads_l5_9w"] or 0),
            "avg_rev_l5_9w":     float(r["avg_rev_l5_9w"] or 0),
            "avg_profit_l5_9w":  float(r["avg_profit_l5_9w"] or 0),
            "avg_margin_l5_9w": (
                float(r["sum_prof_l5_9w"]) / float(r["sum_rev_l5_9w"])
                if r["sum_rev_l5_9w"] else None
            ),
            "lw_loads":          int(r["lw_loads"] or 0),
            "lw_revenue":        float(r["lw_rev"] or 0),
            "lw_profit":         float(r["lw_profit"] or 0),
            "lw_margin": (
                float(r["lw_profit"]) / float(r["lw_rev"])
                if r["lw_rev"] else None
            ),
            "load_diff_lw_vs_l8w": int(r["lw_loads"] or 0) - float(r["avg_loads_l8w"] or 0),
            "pct_var_loads_lw_vs_l8w":  _pct_var(int(r["lw_loads"] or 0), float(r["avg_loads_l8w"] or 0)),
            "pct_var_rev_lw_vs_l8w":    _pct_var(float(r["lw_rev"] or 0), float(r["avg_rev_l8w"] or 0)),
            "pct_var_profit_lw_vs_l8w": _pct_var(float(r["lw_profit"] or 0), float(r["avg_profit_l8w"] or 0)),
            "pct_var_loads_l2_4_vs_l8w":  _pct_var(float(r["avg_loads_l2_4w"] or 0), float(r["avg_loads_l8w"] or 0)),
            "pct_var_rev_l2_4_vs_l8w":    _pct_var(float(r["avg_rev_l2_4w"] or 0), float(r["avg_rev_l8w"] or 0)),
            "pct_var_profit_l2_4_vs_l8w": _pct_var(float(r["avg_profit_l2_4w"] or 0), float(r["avg_profit_l8w"] or 0)),
            "pct_var_loads_l5_9_vs_l8w":  _pct_var(float(r["avg_loads_l5_9w"] or 0), float(r["avg_loads_l8w"] or 0)),
            "pct_var_rev_l5_9_vs_l8w":    _pct_var(float(r["avg_rev_l5_9w"] or 0), float(r["avg_rev_l8w"] or 0)),
            "pct_var_profit_l5_9_vs_l8w": _pct_var(float(r["avg_profit_l5_9w"] or 0), float(r["avg_profit_l8w"] or 0)),
            "last_load_date":    r["last_load_date"].isoformat() if r["last_load_date"] else None,
            "days_since_last_load": days,
            "bucket":            _bucket(days),
            "reactive_this_week": bool(r["reactive_this_week"]) if r["reactive_this_week"] is not None else False,
        })

    out.sort(key=lambda x: (x["team"] or "", x["customer"] or ""))
    return {"success": True, "data": out, "meta": {
        "windows": {
            "l8w":   {"start": l8w_start.isoformat(),  "end": l8w_end.isoformat()},
            "lw":    {"start": lw_start.isoformat(),   "end": lw_end.isoformat()},
            "l2_4w": {"start": l24_start.isoformat(),  "end": l24_end.isoformat()},
            "l5_9w": {"start": l59_start.isoformat(),  "end": l59_end.isoformat()},
        },
    }}


# ---------------------------------------------------------------------------
# /lane-summary — per (customer, lane) reactive list. Powers the "Summary
# Last Week" + "Summary 2 to 4 Week" tables that include Lane and contract
# filter. Returns a flat list; client filters by bucket + contract.
# ---------------------------------------------------------------------------


@router.get("/lane-summary")
async def lane_summary(
    request: Request,
    response: Response,
    teams: Optional[str] = Query(None),
    customer: Optional[str] = Query(None),
    contract: Optional[str] = Query(None),
    _user: dict = Depends(require_tag_role(*ATTRITION_ROLES)),
):
    """Per (team, customer, lane, contract_type) reactive aggregation.

    Used by the Lane-level summary tables in the PDF (pages 13, 14, 15-17).
    Slices into LW / L2-4W / L5-9W / >63d / SPOT-stale buckets just like
    /reactive-summary but with lane resolution.
    """
    pool = get_datalake_gold_pool(request)
    response.headers["Cache-Control"] = CACHE_HEADER

    team_list = _parse_csv(teams, ALL_TEAMS)
    today = cst_today()
    l8w_start, l8w_end = _l8w_window(today)
    lw_start, lw_end = _last_completed_week(today)
    l24_end = lw_start - timedelta(days=1)
    l24_start = l24_end - timedelta(days=3 * 7 - 1)
    l59_end = l24_start - timedelta(days=1)
    l59_start = l59_end - timedelta(days=5 * 7 - 1)
    # Spot tables go further back (1y).
    earliest = today - timedelta(days=365)

    params: list = []
    where = _scope_where("br4", team_list, customer, contract, None, params)
    params.extend([earliest, l8w_start, l8w_end, l24_start, l24_end, lw_start, lw_end, today])
    (p_earliest, p_l8s, p_l8e, p_l24s, p_l24e, p_lws, p_lwe, p_today) = range(
        len(params) - 7, len(params) + 1
    )

    rows = await pool.fetch(
        f"""
        WITH base AS (
          SELECT
            br4.origin_actual_departure::date AS dep_date,
            TRIM(br4.team_id)                  AS team_id,
            TRIM(br4.customer_name)            AS customer_name,
            {_lane_expr("br4")}                AS lane,
            UPPER(TRIM(COALESCE(br4.contract_type_descr,''))) AS contract_type,
            br4.id                             AS load_id,
            br4.total_charge,
            br4.margin_amt
          FROM public.mcleod_gld_budget_report_v4 br4
          WHERE {where}
            AND br4.origin_actual_departure::date >= ${p_earliest}
        ),
        agg AS (
          SELECT
            team_id, customer_name, lane, contract_type,
            COUNT(*) FILTER (WHERE total_charge <> 0 AND dep_date BETWEEN ${p_l8s} AND ${p_l8e}) / 8.0 AS avg_loads_l8w,
            COALESCE(SUM(total_charge) FILTER (WHERE dep_date BETWEEN ${p_l8s} AND ${p_l8e}), 0) / 8.0 AS avg_rev_l8w,
            COALESCE(SUM(margin_amt)   FILTER (WHERE dep_date BETWEEN ${p_l8s} AND ${p_l8e}), 0) / 8.0 AS avg_profit_l8w,
            COALESCE(SUM(total_charge) FILTER (WHERE dep_date BETWEEN ${p_l8s} AND ${p_l8e}), 0)       AS sum_rev_l8w,
            COALESCE(SUM(margin_amt)   FILTER (WHERE dep_date BETWEEN ${p_l8s} AND ${p_l8e}), 0)       AS sum_prof_l8w,
            COUNT(*) FILTER (WHERE total_charge <> 0 AND dep_date BETWEEN ${p_l24s} AND ${p_l24e}) / 3.0 AS avg_loads_l2_4w,
            COALESCE(SUM(total_charge) FILTER (WHERE dep_date BETWEEN ${p_l24s} AND ${p_l24e}), 0) / 3.0 AS avg_rev_l2_4w,
            COALESCE(SUM(margin_amt)   FILTER (WHERE dep_date BETWEEN ${p_l24s} AND ${p_l24e}), 0) / 3.0 AS avg_profit_l2_4w,
            COUNT(*) FILTER (WHERE total_charge <> 0 AND dep_date BETWEEN ${p_lws} AND ${p_lwe}) AS lw_loads,
            COALESCE(SUM(total_charge) FILTER (WHERE dep_date BETWEEN ${p_lws} AND ${p_lwe}), 0) AS lw_rev,
            COALESCE(SUM(margin_amt)   FILTER (WHERE dep_date BETWEEN ${p_lws} AND ${p_lwe}), 0) AS lw_profit,
            COUNT(*) FILTER (WHERE total_charge <> 0) AS total_loads,
            COALESCE(SUM(total_charge), 0)::numeric AS total_revenue,
            COALESCE(SUM(margin_amt),   0)::numeric AS total_profit,
            MAX(dep_date) AS last_load_date
          FROM base
          GROUP BY team_id, customer_name, lane, contract_type
        )
        SELECT *,
          (${p_today} - last_load_date) AS days_since_last_load
        FROM agg
        WHERE customer_name IS NOT NULL AND customer_name <> ''
          AND lane IS NOT NULL AND lane <> ' - '
        """,
        *params,
    )

    def _bucket(days: Optional[int]) -> str:
        if days is None:
            return "no_load"
        if days <= 7:
            return "lw"
        if days <= 28:
            return "l2_4w"
        if days <= 63:
            return "l5_9w"
        if days <= 248:
            return "spot_recent"
        if days <= 365:
            return "spot_stale"
        return "gt_1y"

    def _pct_var(curr: float, base: float) -> Optional[float]:
        if base == 0:
            return None
        return (curr - base) / abs(base)

    out = []
    for r in rows:
        days = int(r["days_since_last_load"]) if r["days_since_last_load"] is not None else None
        l8_loads = float(r["avg_loads_l8w"] or 0)
        l8_rev = float(r["avg_rev_l8w"] or 0)
        l8_prof = float(r["avg_profit_l8w"] or 0)
        out.append({
            "team":           r["team_id"],
            "customer":       r["customer_name"],
            "lane":           r["lane"],
            "contract_type":  r["contract_type"],
            "avg_loads_l8w":  l8_loads,
            "avg_rev_l8w":    l8_rev,
            "avg_profit_l8w": l8_prof,
            "avg_margin_l8w": (
                float(r["sum_prof_l8w"]) / float(r["sum_rev_l8w"])
                if r["sum_rev_l8w"] else None
            ),
            "avg_loads_l2_4w":  float(r["avg_loads_l2_4w"] or 0),
            "avg_rev_l2_4w":    float(r["avg_rev_l2_4w"] or 0),
            "avg_profit_l2_4w": float(r["avg_profit_l2_4w"] or 0),
            "lw_loads":     int(r["lw_loads"] or 0),
            "lw_revenue":   float(r["lw_rev"] or 0),
            "lw_profit":    float(r["lw_profit"] or 0),
            "lw_margin": (
                float(r["lw_profit"]) / float(r["lw_rev"])
                if r["lw_rev"] else None
            ),
            "total_loads":   int(r["total_loads"] or 0),
            "total_revenue": float(r["total_revenue"] or 0),
            "total_profit":  float(r["total_profit"] or 0),
            "total_margin": (
                float(r["total_profit"]) / float(r["total_revenue"])
                if r["total_revenue"] else None
            ),
            "load_diff_lw_vs_l8w": int(r["lw_loads"] or 0) - l8_loads,
            "pct_var_loads_lw_vs_l8w":  _pct_var(int(r["lw_loads"] or 0), l8_loads),
            "pct_var_rev_lw_vs_l8w":    _pct_var(float(r["lw_rev"] or 0), l8_rev),
            "pct_var_profit_lw_vs_l8w": _pct_var(float(r["lw_profit"] or 0), l8_prof),
            "pct_var_loads_l2_4_vs_l8w":  _pct_var(float(r["avg_loads_l2_4w"] or 0), l8_loads),
            "pct_var_rev_l2_4_vs_l8w":    _pct_var(float(r["avg_rev_l2_4w"] or 0), l8_rev),
            "pct_var_profit_l2_4_vs_l8w": _pct_var(float(r["avg_profit_l2_4w"] or 0), l8_prof),
            "last_load_date": r["last_load_date"].isoformat() if r["last_load_date"] else None,
            "days_since_last_load": days,
            "bucket": _bucket(days),
        })

    out.sort(key=lambda x: (x["team"] or "", x["customer"] or "", x["lane"] or ""))
    return {"success": True, "data": out}


# ---------------------------------------------------------------------------
# /wow-variation — Total $Var (LW − LW-1) by team and per (team, customer).
# ---------------------------------------------------------------------------


@router.get("/wow-variation")
async def wow_variation(
    request: Request,
    response: Response,
    teams: Optional[str] = Query(None),
    customer: Optional[str] = Query(None),
    contract: Optional[str] = Query(None),
    _user: dict = Depends(require_tag_role(*ATTRITION_ROLES)),
):
    """Profit variation: SUM(margin LW) − SUM(margin LW-1) per team + customer.

    Returns:
      total: scalar $Var across the whole filtered scope
      by_team:     [{team, var}]
      by_customer: [{team, customer_id, customer_name, var}]
    """
    pool = get_datalake_gold_pool(request)
    response.headers["Cache-Control"] = CACHE_HEADER

    team_list = _parse_csv(teams, ALL_TEAMS)
    lw_start, lw_end = _last_completed_week()
    lw_prev_start = lw_start - timedelta(days=7)
    lw_prev_end = lw_start - timedelta(days=1)

    params: list = []
    where = _scope_where("br4", team_list, customer, contract, None, params)
    params.extend([lw_prev_start, lw_prev_end, lw_start, lw_end])
    p_lwps, p_lwpe, p_lws, p_lwe = (
        len(params) - 3, len(params) - 2, len(params) - 1, len(params),
    )

    rows = await pool.fetch(
        f"""
        WITH base AS (
          SELECT
            TRIM(br4.team_id)        AS team_id,
            TRIM(br4.customer_id)    AS customer_id,
            TRIM(br4.customer_name)  AS customer_name,
            br4.origin_actual_departure::date AS dep_date,
            br4.margin_amt
          FROM public.mcleod_gld_budget_report_v4 br4
          WHERE {where}
            AND br4.origin_actual_departure::date BETWEEN ${p_lwps} AND ${p_lwe}
        )
        SELECT
          team_id, customer_id, customer_name,
          COALESCE(SUM(margin_amt) FILTER (WHERE dep_date BETWEEN ${p_lws}  AND ${p_lwe}),  0) AS lw_profit,
          COALESCE(SUM(margin_amt) FILTER (WHERE dep_date BETWEEN ${p_lwps} AND ${p_lwpe}), 0) AS lw_prev_profit
        FROM base
        WHERE customer_name IS NOT NULL AND customer_name <> ''
        GROUP BY team_id, customer_id, customer_name
        """,
        *params,
    )

    by_customer = []
    by_team_map: dict[str, float] = {}
    total = 0.0
    for r in rows:
        var = float(r["lw_profit"] or 0) - float(r["lw_prev_profit"] or 0)
        team = r["team_id"] or ""
        by_customer.append({
            "team":          team,
            "customer_id":   r["customer_id"],
            "customer_name": r["customer_name"],
            "var":           var,
        })
        by_team_map[team] = by_team_map.get(team, 0.0) + var
        total += var

    by_team = sorted(
        ({"team": k, "var": v} for k, v in by_team_map.items()),
        key=lambda x: x["team"],
    )
    by_customer.sort(key=lambda x: (x["team"], x["customer_name"] or ""))

    return {
        "success": True,
        "data": {
            "total":       total,
            "by_team":     by_team,
            "by_customer": by_customer,
            "windows": {
                "lw":      {"start": lw_start.isoformat(),      "end": lw_end.isoformat()},
                "lw_prev": {"start": lw_prev_start.isoformat(), "end": lw_prev_end.isoformat()},
            },
        },
    }
