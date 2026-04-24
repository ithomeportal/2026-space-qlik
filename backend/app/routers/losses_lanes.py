"""Code-made report: Losses Lanes — worst-margin lanes & customers.

Mirrors Bruno's Qlik sheet `app=de4ecec0-439b-4eb4-93b6-96f2a8c25366 /
sheet=GjMvAnC` ("BRUNO - Losses Lanes") as a portal-native report. Every
panel reads from `public.mcleod_gld_budget_report_v4` (datalake gold) and
is filtered to loads where ``margin_amt < 0``.

Scope (verbatim from PDF + project conventions):
- team_id     IN (TEAM1..TEAM5, TEAM-DFW)
- company_id  IN (TMS, TMS3)
- status      IN (D, P)
- customer_name NOT LIKE '%UNILINK%'     (PDF)
- customer_name NOT LIKE '%OILTEX%'      (project-wide exclusion)

All varchar columns use the padded-variants pattern (`pad_variants(width=N)`)
so btree indexes on team_id/company_id/status stay usable. Never wrap those
columns in TRIM() inside WHERE/JOIN.
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, Query, Request

from app.datalake import pad_variants as _pad_variants
from app.routers.deps import get_datalake_gold_pool, require_tag_role

LOSSES_ROLES = ("CEO", "Executive", "CORP", "DFW", "Operations", "Finance")

YEAR_START = date(2026, 1, 1)
YEAR_END = date(2026, 12, 31)

ALL_TEAMS = ("TEAM1", "TEAM2", "TEAM3", "TEAM4", "TEAM5", "TEAM-DFW")
COMPANIES = ("TMS", "TMS3")
OPEN_STATUSES = ("D", "P")

router = APIRouter(tags=["losses-lanes"], prefix="/custom/losses-lanes")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _clamp(d: Optional[date], default: date) -> date:
    if d is None:
        return default
    if d < YEAR_START:
        return YEAR_START
    if d > YEAR_END:
        return YEAR_END
    return d


def _month_bounds(today: date) -> tuple[date, date, date, date]:
    """Return (this_month_start, this_month_end, last_month_start, last_month_end)."""
    m_start = today.replace(day=1)
    if m_start.month == 12:
        m_end = m_start.replace(year=m_start.year + 1, month=1) - timedelta(days=1)
    else:
        m_end = m_start.replace(month=m_start.month + 1) - timedelta(days=1)
    lm_end = m_start - timedelta(days=1)
    lm_start = lm_end.replace(day=1)
    return m_start, m_end, lm_start, lm_end


def _resolve_range(
    rng: Optional[str],
    start_date: Optional[date],
    end_date: Optional[date],
) -> tuple[date, date]:
    """Expand the 4-preset range selector into a concrete [start, end] pair."""
    today = date.today()
    today_clamped = max(YEAR_START, min(YEAR_END, today))
    m_start, _m_end, lm_start, lm_end = _month_bounds(today)
    if rng == "last_month":
        return _clamp(lm_start, YEAR_START), _clamp(lm_end, YEAR_END)
    if rng == "ytd" or rng == "this_year":
        return YEAR_START, today_clamped
    if rng == "custom":
        s = _clamp(start_date, YEAR_START)
        e = _clamp(end_date, YEAR_END)
        if e < s:
            s, e = e, s
        return s, e
    # default: MTD
    return _clamp(m_start, YEAR_START), today_clamped


def _parse_teams(teams: Optional[str]) -> list[str]:
    """Comma-separated ``teams`` param -> validated list. Empty -> all teams."""
    if not teams:
        return list(ALL_TEAMS)
    wanted = [t.strip() for t in teams.split(",") if t.strip()]
    allowed = {t for t in ALL_TEAMS}
    return [t for t in wanted if t in allowed] or list(ALL_TEAMS)


def _scope_where(
    alias: str,
    teams: list[str],
    customer: Optional[str],
    params: list,
) -> str:
    """Common WHERE fragment for the v4 load-level table.

    Appends positional params onto ``params`` and returns the SQL snippet.
    Uses sargable ``= ANY($N)`` predicates with padded+unpadded variants.
    """
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
        parts.append(f"{alias}.customer_name = ${len(params)}")
    return " AND ".join(parts)


def _lane_expr(alias: str) -> str:
    """Canonical lane label: origin_city, origin_state, dest_city, dest_state."""
    return (
        f"NULLIF(TRIM({alias}.origin_city_name),'') || ',' || "
        f"NULLIF(TRIM({alias}.origin_state_id),'') || ',' || "
        f"NULLIF(TRIM({alias}.dest_city_name),'')   || ',' || "
        f"NULLIF(TRIM({alias}.dest_state_id),'')"
    )


# ---------------------------------------------------------------------------
# Filters endpoint — powers the team list + customer autosuggest
# ---------------------------------------------------------------------------


@router.get("/filters")
async def filters(
    request: Request,
    _user: dict = Depends(require_tag_role(*LOSSES_ROLES)),
):
    """Available teams + distinct customer list (within scope, year-limited)."""
    pool = get_datalake_gold_pool(request)
    rows = await pool.fetch(
        """
        SELECT DISTINCT TRIM(customer_name) AS customer_name
        FROM public.mcleod_gld_budget_report_v4
        WHERE team_id    = ANY($1)
          AND company_id = ANY($2)
          AND status     = ANY($3)
          AND UPPER(COALESCE(customer_name,'')) NOT LIKE '%UNILINK%'
          AND UPPER(COALESCE(customer_name,'')) NOT LIKE '%OILTEX%'
          AND customer_name IS NOT NULL
          AND TRIM(customer_name) <> ''
          AND origin_actual_departure >= $4
        ORDER BY customer_name
        """,
        _pad_variants(ALL_TEAMS, width=8),
        _pad_variants(COMPANIES, width=4),
        _pad_variants(OPEN_STATUSES, width=1),
        YEAR_START,
    )
    return {
        "success": True,
        "data": {
            "teams": list(ALL_TEAMS),
            "customers": [r["customer_name"] for r in rows if r["customer_name"]],
            "year_start": YEAR_START.isoformat(),
            "year_end": YEAR_END.isoformat(),
        },
    }


# ---------------------------------------------------------------------------
# Summary KPIs — 4 cards on top of the report
# ---------------------------------------------------------------------------


@router.get("/summary")
async def summary(
    request: Request,
    range: Optional[str] = Query("mtd"),
    start_date: Optional[date] = Query(None),
    end_date: Optional[date] = Query(None),
    teams: Optional[str] = Query(None),
    customer: Optional[str] = Query(None),
    _user: dict = Depends(require_tag_role(*LOSSES_ROLES)),
):
    pool = get_datalake_gold_pool(request)
    s, e = _resolve_range(range, start_date, end_date)
    team_list = _parse_teams(teams)

    params: list = []
    where = _scope_where("br4", team_list, customer, params)
    params.extend([s, e])
    date_fragment = (
        f"br4.origin_actual_departure::date BETWEEN ${len(params) - 1} AND ${len(params)}"
    )

    row = await pool.fetchrow(
        f"""
        SELECT
          COUNT(*) FILTER (WHERE br4.margin_amt < 0) AS loads,
          COALESCE(
            SUM(br4.total_charge) FILTER (
              WHERE br4.margin_amt < 0 AND br4.total_charge <> 0
            ), 0
          )::numeric AS revenue,
          COALESCE(
            SUM(br4.margin_amt) FILTER (
              WHERE br4.margin_amt < 0 AND br4.total_charge <> 0
            ), 0
          )::numeric AS profit
        FROM public.mcleod_gld_budget_report_v4 br4
        WHERE {where} AND {date_fragment}
        """,
        *params,
    )

    loads = int(row["loads"] or 0)
    revenue = float(row["revenue"] or 0)
    profit = float(row["profit"] or 0)
    margin_pct = (profit / revenue * 100.0) if revenue else None

    return {
        "success": True,
        "data": {
            "loads": loads,
            "revenue": revenue,
            "profit": profit,
            "margin_pct": margin_pct,
            "window": {"start": s.isoformat(), "end": e.isoformat()},
            "teams_applied": team_list,
        },
    }


# ---------------------------------------------------------------------------
# Worst Margins by Lanes — table with 15/18/20% target-profit columns
# ---------------------------------------------------------------------------


@router.get("/by-lane")
async def by_lane(
    request: Request,
    range: Optional[str] = Query("mtd"),
    start_date: Optional[date] = Query(None),
    end_date: Optional[date] = Query(None),
    teams: Optional[str] = Query(None),
    customer: Optional[str] = Query(None),
    sort: str = Query("profit_asc"),
    page: int = Query(1, ge=1),
    limit: int = Query(100, ge=1, le=500),
    _user: dict = Depends(require_tag_role(*LOSSES_ROLES)),
):
    """Per-customer + per-lane leak view.

    Every row has ``margin_amt < 0 AND total_charge <> 0`` applied at the
    load level, then grouped. So this shows the *loss portion* of each
    (customer, lane) pair, not its net result.
    """
    pool = get_datalake_gold_pool(request)
    s, e = _resolve_range(range, start_date, end_date)
    team_list = _parse_teams(teams)
    offset = (page - 1) * limit

    params: list = []
    where = _scope_where("br4", team_list, customer, params)
    params.extend([s, e])
    date_fragment = (
        f"br4.origin_actual_departure::date BETWEEN ${len(params) - 1} AND ${len(params)}"
    )

    order_by = {
        "profit_asc": "profit ASC",              # most-negative first (default)
        "profit_desc": "profit DESC",
        "revenue_desc": "revenue DESC NULLS LAST",
        "revenue_asc": "revenue ASC NULLS LAST",
        "margin_asc": "margin_pct ASC NULLS LAST",
        "margin_desc": "margin_pct DESC NULLS LAST",
    }.get(sort, "profit ASC")

    params.extend([limit, offset])
    lim_p, off_p = len(params) - 1, len(params)

    rows = await pool.fetch(
        f"""
        WITH base AS (
          SELECT
            TRIM(br4.customer_id) AS customer,
            {_lane_expr("br4")}    AS lane,
            br4.total_charge,
            br4.margin_amt
          FROM public.mcleod_gld_budget_report_v4 br4
          WHERE {where} AND {date_fragment}
            AND br4.margin_amt < 0 AND br4.total_charge <> 0
        ),
        agg AS (
          SELECT
            customer,
            lane,
            SUM(total_charge)::numeric AS revenue,
            SUM(margin_amt)::numeric   AS profit,
            CASE WHEN SUM(total_charge) <> 0
                 THEN SUM(margin_amt)::numeric / SUM(total_charge)::numeric
                 ELSE NULL END AS margin_pct
          FROM base
          GROUP BY customer, lane
        )
        SELECT
          customer,
          lane,
          revenue,
          profit,
          margin_pct,
          -- Bruno's 15/18/20% profit targets & diff+ columns (verbatim).
          CASE WHEN margin_pct > 0.15 THEN 0
               ELSE revenue * 0.15 END AS profit_15,
          CASE WHEN margin_pct < 0.15
               THEN revenue * 0.15 - profit ELSE 0 END AS diff_15,
          CASE WHEN margin_pct > 0.18 THEN 0
               ELSE revenue * 0.18 END AS profit_18,
          CASE WHEN margin_pct < 0.18
               THEN revenue * 0.18 - profit ELSE 0 END AS diff_18,
          CASE WHEN margin_pct > 0.20 THEN 0
               ELSE revenue * 0.20 END AS profit_20,
          CASE WHEN margin_pct < 0.20
               THEN revenue * 0.20 - profit ELSE 0 END AS diff_20,
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
            "lane": r["lane"],
            "revenue": float(r["revenue"] or 0),
            "profit": float(r["profit"] or 0),
            "margin_pct": float(r["margin_pct"]) * 100.0 if r["margin_pct"] is not None else None,
            "profit_15": float(r["profit_15"] or 0),
            "diff_15":   float(r["diff_15"] or 0),
            "profit_18": float(r["profit_18"] or 0),
            "diff_18":   float(r["diff_18"] or 0),
            "profit_20": float(r["profit_20"] or 0),
            "diff_20":   float(r["diff_20"] or 0),
        }
        for r in rows
    ]
    return {
        "success": True,
        "data": data,
        "meta": {"total": total, "page": page, "limit": limit},
    }


# ---------------------------------------------------------------------------
# Worst Margins by Customer — table
# ---------------------------------------------------------------------------


@router.get("/by-customer")
async def by_customer(
    request: Request,
    range: Optional[str] = Query("mtd"),
    start_date: Optional[date] = Query(None),
    end_date: Optional[date] = Query(None),
    teams: Optional[str] = Query(None),
    customer: Optional[str] = Query(None),
    sort: str = Query("profit_asc"),
    page: int = Query(1, ge=1),
    limit: int = Query(100, ge=1, le=500),
    _user: dict = Depends(require_tag_role(*LOSSES_ROLES)),
):
    pool = get_datalake_gold_pool(request)
    s, e = _resolve_range(range, start_date, end_date)
    team_list = _parse_teams(teams)
    offset = (page - 1) * limit

    params: list = []
    where = _scope_where("br4", team_list, customer, params)
    params.extend([s, e])
    date_fragment = (
        f"br4.origin_actual_departure::date BETWEEN ${len(params) - 1} AND ${len(params)}"
    )

    order_by = {
        "profit_asc": "profit ASC",
        "profit_desc": "profit DESC",
        "loads_desc": "loads DESC",
        "loads_asc": "loads ASC",
        "revenue_desc": "revenue DESC NULLS LAST",
        "revenue_asc": "revenue ASC NULLS LAST",
    }.get(sort, "profit ASC")

    params.extend([limit, offset])
    lim_p, off_p = len(params) - 1, len(params)

    rows = await pool.fetch(
        f"""
        SELECT
          TRIM(br4.customer_id) AS customer,
          COUNT(*) FILTER (WHERE br4.margin_amt < 0) AS loads,
          COALESCE(SUM(br4.total_charge) FILTER (
            WHERE br4.margin_amt < 0 AND br4.total_charge <> 0
          ), 0)::numeric AS revenue,
          COALESCE(SUM(br4.margin_amt) FILTER (
            WHERE br4.margin_amt < 0 AND br4.total_charge <> 0
          ), 0)::numeric AS profit,
          COUNT(*) OVER() AS total_count
        FROM public.mcleod_gld_budget_report_v4 br4
        WHERE {where} AND {date_fragment}
          AND br4.margin_amt < 0 AND br4.total_charge <> 0
        GROUP BY TRIM(br4.customer_id)
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
        }
        for r in rows
    ]
    return {
        "success": True,
        "data": data,
        "meta": {"total": total, "page": page, "limit": limit},
    }


# ---------------------------------------------------------------------------
# Top-N combo chart — "Top 10 $Revenue vs Negative $Profit by Lane"
# ---------------------------------------------------------------------------


@router.get("/top-lanes-combo")
async def top_lanes_combo(
    request: Request,
    range: Optional[str] = Query("mtd"),
    start_date: Optional[date] = Query(None),
    end_date: Optional[date] = Query(None),
    teams: Optional[str] = Query(None),
    customer: Optional[str] = Query(None),
    limit: int = Query(10, ge=1, le=50),
    _user: dict = Depends(require_tag_role(*LOSSES_ROLES)),
):
    pool = get_datalake_gold_pool(request)
    s, e = _resolve_range(range, start_date, end_date)
    team_list = _parse_teams(teams)

    params: list = []
    where = _scope_where("br4", team_list, customer, params)
    params.extend([s, e])
    date_fragment = (
        f"br4.origin_actual_departure::date BETWEEN ${len(params) - 1} AND ${len(params)}"
    )
    params.append(limit)
    lim_p = len(params)

    rows = await pool.fetch(
        f"""
        SELECT
          {_lane_expr("br4")} AS lane,
          COUNT(*) FILTER (WHERE br4.margin_amt < 0) AS loads,
          COALESCE(SUM(br4.total_charge) FILTER (
            WHERE br4.margin_amt < 0 AND br4.total_charge <> 0
          ), 0)::numeric AS revenue,
          COALESCE(SUM(br4.margin_amt) FILTER (
            WHERE br4.margin_amt < 0 AND br4.total_charge <> 0
          ), 0)::numeric AS profit
        FROM public.mcleod_gld_budget_report_v4 br4
        WHERE {where} AND {date_fragment}
          AND br4.margin_amt < 0 AND br4.total_charge <> 0
        GROUP BY {_lane_expr("br4")}
        ORDER BY profit ASC
        LIMIT ${lim_p}
        """,
        *params,
    )
    data = [
        {
            "lane": r["lane"],
            "loads": int(r["loads"] or 0),
            "revenue": float(r["revenue"] or 0),
            "profit": float(r["profit"] or 0),
        }
        for r in rows
    ]
    return {"success": True, "data": data}


# ---------------------------------------------------------------------------
# Trend charts — by Day / Week / Month
# ---------------------------------------------------------------------------


@router.get("/by-day")
async def by_day(
    request: Request,
    range: Optional[str] = Query("mtd"),
    start_date: Optional[date] = Query(None),
    end_date: Optional[date] = Query(None),
    teams: Optional[str] = Query(None),
    customer: Optional[str] = Query(None),
    _user: dict = Depends(require_tag_role(*LOSSES_ROLES)),
):
    """Daily revenue/profit/loads. Respects the user's date window."""
    pool = get_datalake_gold_pool(request)
    s, e = _resolve_range(range, start_date, end_date)
    team_list = _parse_teams(teams)

    params: list = []
    where = _scope_where("br4", team_list, customer, params)
    params.extend([s, e])
    p_s, p_e = len(params) - 1, len(params)

    rows = await pool.fetch(
        f"""
        SELECT
          br4.origin_actual_departure::date AS bucket,
          COUNT(*) FILTER (WHERE br4.margin_amt < 0) AS loads,
          COALESCE(SUM(br4.total_charge) FILTER (
            WHERE br4.margin_amt < 0 AND br4.total_charge <> 0
          ), 0)::numeric AS revenue,
          COALESCE(SUM(br4.margin_amt) FILTER (
            WHERE br4.margin_amt < 0 AND br4.total_charge <> 0
          ), 0)::numeric AS profit
        FROM public.mcleod_gld_budget_report_v4 br4
        WHERE {where}
          AND br4.origin_actual_departure::date BETWEEN ${p_s} AND ${p_e}
        GROUP BY br4.origin_actual_departure::date
        ORDER BY bucket
        """,
        *params,
    )
    return {
        "success": True,
        "data": [
            {
                "bucket": r["bucket"].isoformat(),
                "loads": int(r["loads"] or 0),
                "revenue": float(r["revenue"] or 0),
                "profit": float(r["profit"] or 0),
            }
            for r in rows
        ],
    }


@router.get("/by-week")
async def by_week(
    request: Request,
    teams: Optional[str] = Query(None),
    customer: Optional[str] = Query(None),
    _user: dict = Depends(require_tag_role(*LOSSES_ROLES)),
):
    """Weekly series — STICKY last 8 weeks (matches Bruno's Qlik expression)."""
    pool = get_datalake_gold_pool(request)
    today = date.today()
    # WeekStart(Today(),-8,0) → Monday of 8 weeks ago. WeekStart(Today(),1,0) → next Monday.
    monday = today - timedelta(days=today.weekday())
    start = monday - timedelta(weeks=8)
    end = monday + timedelta(days=6)  # end of current week (Sunday)
    team_list = _parse_teams(teams)

    params: list = []
    where = _scope_where("br4", team_list, customer, params)
    params.extend([start, end])
    p_s, p_e = len(params) - 1, len(params)

    rows = await pool.fetch(
        f"""
        SELECT
          DATE_TRUNC('week', br4.origin_actual_departure)::date AS bucket,
          COUNT(*) FILTER (WHERE br4.margin_amt < 0) AS loads,
          COALESCE(SUM(br4.total_charge) FILTER (
            WHERE br4.margin_amt < 0 AND br4.total_charge <> 0
          ), 0)::numeric AS revenue,
          COALESCE(SUM(br4.margin_amt) FILTER (
            WHERE br4.margin_amt < 0 AND br4.total_charge <> 0
          ), 0)::numeric AS profit
        FROM public.mcleod_gld_budget_report_v4 br4
        WHERE {where}
          AND br4.origin_actual_departure::date BETWEEN ${p_s} AND ${p_e}
        GROUP BY DATE_TRUNC('week', br4.origin_actual_departure)::date
        ORDER BY bucket
        """,
        *params,
    )
    return {
        "success": True,
        "data": [
            {
                "bucket": r["bucket"].isoformat(),
                "loads": int(r["loads"] or 0),
                "revenue": float(r["revenue"] or 0),
                "profit": float(r["profit"] or 0),
            }
            for r in rows
        ],
    }


@router.get("/by-month")
async def by_month(
    request: Request,
    teams: Optional[str] = Query(None),
    customer: Optional[str] = Query(None),
    _user: dict = Depends(require_tag_role(*LOSSES_ROLES)),
):
    """Monthly series — STICKY last 6 months (matches Bruno's Qlik expression)."""
    pool = get_datalake_gold_pool(request)
    today = date.today()
    # AddMonths(MonthStart(Today()), -6) → first day of 6 months ago.
    m_start = today.replace(day=1)
    y, m = m_start.year, m_start.month - 6
    while m <= 0:
        y -= 1
        m += 12
    start = date(y, m, 1)
    end = today  # through today
    team_list = _parse_teams(teams)

    params: list = []
    where = _scope_where("br4", team_list, customer, params)
    params.extend([start, end])
    p_s, p_e = len(params) - 1, len(params)

    rows = await pool.fetch(
        f"""
        SELECT
          DATE_TRUNC('month', br4.origin_actual_departure)::date AS bucket,
          COUNT(*) FILTER (WHERE br4.margin_amt < 0) AS loads,
          COALESCE(SUM(br4.total_charge) FILTER (
            WHERE br4.margin_amt < 0 AND br4.total_charge <> 0
          ), 0)::numeric AS revenue,
          COALESCE(SUM(br4.margin_amt) FILTER (
            WHERE br4.margin_amt < 0 AND br4.total_charge <> 0
          ), 0)::numeric AS profit
        FROM public.mcleod_gld_budget_report_v4 br4
        WHERE {where}
          AND br4.origin_actual_departure::date BETWEEN ${p_s} AND ${p_e}
        GROUP BY DATE_TRUNC('month', br4.origin_actual_departure)::date
        ORDER BY bucket
        """,
        *params,
    )
    return {
        "success": True,
        "data": [
            {
                "bucket": r["bucket"].isoformat(),
                "loads": int(r["loads"] or 0),
                "revenue": float(r["revenue"] or 0),
                "profit": float(r["profit"] or 0),
            }
            for r in rows
        ],
    }


# ---------------------------------------------------------------------------
# Order Details — load-level paginated table
# ---------------------------------------------------------------------------


@router.get("/orders")
async def orders(
    request: Request,
    range: Optional[str] = Query("mtd"),
    start_date: Optional[date] = Query(None),
    end_date: Optional[date] = Query(None),
    teams: Optional[str] = Query(None),
    customer: Optional[str] = Query(None),
    lane: Optional[str] = Query(None, description="Optional lane filter (canonical label)"),
    sort: str = Query("date_desc"),
    page: int = Query(1, ge=1),
    limit: int = Query(100, ge=1, le=500),
    _user: dict = Depends(require_tag_role(*LOSSES_ROLES)),
):
    pool = get_datalake_gold_pool(request)
    s, e = _resolve_range(range, start_date, end_date)
    team_list = _parse_teams(teams)
    offset = (page - 1) * limit

    params: list = []
    where = _scope_where("br4", team_list, customer, params)
    params.extend([s, e])
    date_fragment = (
        f"br4.origin_actual_departure::date BETWEEN ${len(params) - 1} AND ${len(params)}"
    )

    lane_filter = ""
    if lane:
        params.append(lane)
        lane_filter = f" AND {_lane_expr('br4')} = ${len(params)}"

    order_by = {
        "date_desc":    "actual_day DESC NULLS LAST, id DESC",
        "date_asc":     "actual_day ASC NULLS LAST, id ASC",
        "profit_asc":   "profit ASC",
        "profit_desc":  "profit DESC",
        "revenue_desc": "revenue DESC NULLS LAST",
        "revenue_asc":  "revenue ASC NULLS LAST",
        "margin_asc":   "margin_pct ASC NULLS LAST",
        "margin_desc":  "margin_pct DESC NULLS LAST",
    }.get(sort, "actual_day DESC NULLS LAST, id DESC")

    params.extend([limit, offset])
    lim_p, off_p = len(params) - 1, len(params)

    rows = await pool.fetch(
        f"""
        SELECT
          br4.origin_actual_departure::date AS actual_day,
          TRIM(br4.id)            AS id,
          TRIM(br4.customer_id)   AS customer_id,
          TRIM(br4.customer_name) AS customer_name,
          NULLIF(TRIM(br4.origin_city_name),'') || ',' ||
            NULLIF(TRIM(br4.origin_state_id),'')  AS origin,
          NULLIF(TRIM(br4.dest_city_name),'')   || ',' ||
            NULLIF(TRIM(br4.dest_state_id),'')    AS destination,
          br4.total_charge::numeric AS revenue,
          br4.margin_amt::numeric   AS profit,
          CASE WHEN br4.total_charge <> 0
               THEN br4.margin_amt::numeric / br4.total_charge::numeric
               ELSE NULL END AS margin_pct,
          TRIM(br4.contract_type) AS contract_type,
          COUNT(*) OVER() AS total_count
        FROM public.mcleod_gld_budget_report_v4 br4
        WHERE {where} AND {date_fragment}
          AND br4.margin_amt < 0 AND br4.total_charge <> 0
          {lane_filter}
        ORDER BY {order_by}
        LIMIT ${lim_p} OFFSET ${off_p}
        """,
        *params,
    )

    total = int(rows[0]["total_count"]) if rows else 0
    data = [
        {
            "actual_day": r["actual_day"].isoformat() if r["actual_day"] else None,
            "id": r["id"],
            "customer_id": r["customer_id"],
            "customer_name": r["customer_name"],
            "origin": r["origin"],
            "destination": r["destination"],
            "revenue": float(r["revenue"] or 0),
            "profit": float(r["profit"] or 0),
            "margin_pct": float(r["margin_pct"]) * 100.0 if r["margin_pct"] is not None else None,
            "contract_type": r["contract_type"],
        }
        for r in rows
    ]
    return {
        "success": True,
        "data": data,
        "meta": {"total": total, "page": page, "limit": limit},
    }
