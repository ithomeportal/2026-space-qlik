"""Code-made report: 2026 Official Budget Follow Up.

Reads from aivn_datalake_gold.public.daily_production_budget_report (refreshed every
6 hours by the n8n workflow 'CORP Update Production vs Goals Follow Up' — SQi0VmZS1nYmo7Kt).

Team ID comes from the McLeod source of truth (public.mcleod_gld_budget_report_v4) joined
on customer name — not from the stored "Team ID" column in daily_production_budget_report,
which has edge cases (budget-only rows get forced to a fallback team, CORP/DFW workflows
disagree, etc.). Each customer is mapped to ONE canonical team (the team with the most
loads in McLeod), whitelisted to TEAM1–TEAM5 + TEAM-DFW. Customers not on an allowed
team — or not present in McLeod — are excluded.

Scope: Date BETWEEN 2026-01-01 AND 2026-12-31. UI filters narrow within this window.
Does not recompute actuals/budgets — the workflow owns that math; this router just
aggregates per filter.
"""

from calendar import monthrange
from datetime import date, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, Query, Request

from app.clock import cst_today
from app.routers.deps import get_datalake_gold_pool, require_tag_role

BUDGET_ROLES = ("CEO", "Executive", "Operations", "Finance", "CORP", "DFW")

# Scope of this report.
YEAR_START = date(2026, 1, 1)
YEAR_END = date(2026, 12, 31)

# Teams we surface — anything else in McLeod is ignored here.
ALLOWED_TEAMS = ("TEAM1", "TEAM2", "TEAM3", "TEAM4", "TEAM5", "TEAM-DFW")

# US federal holidays observed in 2026 — used by Pending/Holidays-Days KPIs and as
# the "no-holidays" filter for the workday helpers in this report. Independence
# Day 2026 falls on Saturday, so the federal observance shifts to Friday Jul 3.
US_HOLIDAYS_2026 = frozenset({
    date(2026, 1, 1),    # New Year's Day
    date(2026, 1, 19),   # MLK Day
    date(2026, 2, 16),   # Presidents' Day
    date(2026, 5, 25),   # Memorial Day
    date(2026, 6, 19),   # Juneteenth
    date(2026, 7, 3),    # Independence Day (observed — Jul 4 is Sat)
    date(2026, 9, 7),    # Labor Day
    date(2026, 10, 12),  # Columbus Day
    date(2026, 11, 11),  # Veterans Day
    date(2026, 11, 26),  # Thanksgiving
    date(2026, 12, 25),  # Christmas
})

# Per-customer canonical team, derived from McLeod. One row per customer: the team with
# the most loads (tiebreak alphabetical). Prepend with `WITH ` when embedding in a query.
CUSTOMER_TEAM_CTE = f"""
customer_team AS (
    SELECT customer_name, team_id FROM (
        SELECT
            TRIM(customer_name) AS customer_name,
            TRIM(team_id)       AS team_id,
            ROW_NUMBER() OVER (
                PARTITION BY TRIM(customer_name)
                ORDER BY COUNT(*) DESC, TRIM(team_id)
            ) AS rn
        FROM public.mcleod_gld_budget_report_v4
        WHERE TRIM(team_id) IN {ALLOWED_TEAMS!r}
        GROUP BY TRIM(customer_name), TRIM(team_id)
    ) ranked
    WHERE rn = 1
)
"""

router = APIRouter(tags=["budget-followup"], prefix="/custom/budget-followup")


def _clamp(d: Optional[date], default: date) -> date:
    if d is None:
        return default
    if d < YEAR_START:
        return YEAR_START
    if d > YEAR_END:
        return YEAR_END
    return d


def _parse_teams(teams: Optional[str]) -> list[str]:
    if not teams:
        return []
    return [t.strip() for t in teams.split(",") if t.strip()]


def _where_and_params(
    start_date: Optional[date],
    end_date: Optional[date],
    teams: Optional[str],
    customer: Optional[str],
) -> tuple[str, list]:
    s = _clamp(start_date, YEAR_START)
    e = _clamp(end_date, YEAR_END)
    parts = ['budget."Date" BETWEEN $1 AND $2']
    params: list = [s, e]
    team_list = _parse_teams(teams)
    if team_list:
        params.append(team_list)
        parts.append(f"ct.team_id = ANY(${len(params)})")
    if customer:
        params.append(customer)
        parts.append(f'budget."Customer Name" = ${len(params)}')
    return " AND ".join(parts), params


@router.get("/filters")
async def filters(
    request: Request,
    _user: dict = Depends(require_tag_role(*BUDGET_ROLES)),
):
    """Distinct teams and customers in the 2026 window — powers the dropdowns."""
    pool = get_datalake_gold_pool(request)
    teams = await pool.fetch(
        f"""
        WITH {CUSTOMER_TEAM_CTE}
        SELECT DISTINCT ct.team_id AS team_id
        FROM public.daily_production_budget_report budget
        JOIN customer_team ct ON TRIM(budget."Customer Name") = ct.customer_name
        WHERE budget."Date" BETWEEN $1 AND $2
        ORDER BY team_id
        """,
        YEAR_START,
        YEAR_END,
    )
    customers = await pool.fetch(
        f"""
        WITH {CUSTOMER_TEAM_CTE}
        SELECT DISTINCT budget."Customer Name" AS customer_name
        FROM public.daily_production_budget_report budget
        JOIN customer_team ct ON TRIM(budget."Customer Name") = ct.customer_name
        WHERE budget."Date" BETWEEN $1 AND $2 AND budget."Customer Name" IS NOT NULL
        ORDER BY customer_name
        """,
        YEAR_START,
        YEAR_END,
    )
    return {
        "success": True,
        "data": {
            "teams": [r["team_id"] for r in teams],
            "customers": [r["customer_name"] for r in customers],
            "year_start": YEAR_START.isoformat(),
            "year_end": YEAR_END.isoformat(),
        },
    }


@router.get("/summary")
async def summary(
    request: Request,
    start_date: Optional[date] = Query(None),
    end_date: Optional[date] = Query(None),
    teams: Optional[str] = Query(None, description="Comma-separated team IDs"),
    customer: Optional[str] = Query(None),
    _user: dict = Depends(require_tag_role(*BUDGET_ROLES)),
):
    """Primary KPIs: Loads / Revenue / Profit / Margin — actuals vs budget vs variance."""
    pool = get_datalake_gold_pool(request)
    where, params = _where_and_params(start_date, end_date, teams, customer)

    row = await pool.fetchrow(
        f"""
        WITH {CUSTOMER_TEAM_CTE}
        SELECT
            COALESCE(SUM(budget."Loads Actual"),    0)::numeric  AS loads_actual,
            COALESCE(SUM(budget."Loads Budget"),    0)::numeric  AS loads_budget,
            COALESCE(SUM(budget."Revenue Actual"),  0)::numeric  AS revenue_actual,
            COALESCE(SUM(budget."Revenue Budget"),  0)::numeric  AS revenue_budget,
            COALESCE(SUM(budget."Profit Actual"),   0)::numeric  AS profit_actual,
            COALESCE(SUM(budget."Profit Budget"),   0)::numeric  AS profit_budget,
            COUNT(DISTINCT budget."Customer Name") FILTER (WHERE budget."Loads Actual" > 0)                                   AS active_customers,
            COUNT(DISTINCT budget."Customer Name")                                                                            AS total_customers,
            COUNT(DISTINCT budget."Date") FILTER (WHERE budget."Loads Actual" > 0 OR budget."Loads Budget" > 0)               AS active_days
        FROM public.daily_production_budget_report budget
        JOIN customer_team ct ON TRIM(budget."Customer Name") = ct.customer_name
        WHERE {where}
        """,
        *params,
    )
    data = {k: (float(v) if v is not None else 0.0) for k, v in dict(row).items()} if row else {}

    # Margin % (aggregate from totals, not the stored per-row margin).
    data["margin_actual_pct"] = (
        data["profit_actual"] / data["revenue_actual"] * 100.0
        if data.get("revenue_actual")
        else 0.0
    )
    data["margin_budget_pct"] = (
        data["profit_budget"] / data["revenue_budget"] * 100.0
        if data.get("revenue_budget")
        else 0.0
    )

    # Variances + % achievement.
    for metric in ("loads", "revenue", "profit"):
        a = data.get(f"{metric}_actual", 0.0)
        b = data.get(f"{metric}_budget", 0.0)
        data[f"{metric}_variance"] = a - b
        data[f"{metric}_achievement_pct"] = (a / b * 100.0) if b else 0.0
    data["margin_variance_pct"] = data["margin_actual_pct"] - data["margin_budget_pct"]

    # Calendar-day breakdown of the *applied filter window* (not the full year),
    # so Bruno's "KPIs should move with the filters" requirement holds.
    today = cst_today()
    win_start = _clamp(start_date, YEAR_START)
    win_end = _clamp(end_date, YEAR_END)
    total_days = (win_end - win_start).days + 1
    if today < win_start:
        elapsed_days = 0
    elif today > win_end:
        elapsed_days = total_days
    else:
        elapsed_days = (today - win_start).days + 1
    data["total_days"] = total_days
    data["days_elapsed"] = max(0, min(total_days, elapsed_days))
    data["days_remaining"] = max(0, total_days - data["days_elapsed"])

    # Pending Days = Mon–Fri working days remaining inside the window from today
    # onwards (holidays excluded). Complements `days_remaining` (calendar days).
    pending_start = max(today, win_start)
    pending_days = 0
    if pending_start <= win_end:
        d = pending_start
        while d <= win_end:
            if d.weekday() < 5 and d not in US_HOLIDAYS_2026:
                pending_days += 1
            d = d + timedelta(days=1)
    data["pending_days"] = pending_days

    # Holidays Days = US federal holidays falling inside the window.
    data["holidays_days"] = sum(1 for h in US_HOLIDAYS_2026 if win_start <= h <= win_end)

    data["start_date"] = win_start.isoformat()
    data["end_date"] = win_end.isoformat()

    return {"success": True, "data": data}


@router.get("/by-customer")
async def by_customer(
    request: Request,
    start_date: Optional[date] = Query(None),
    end_date: Optional[date] = Query(None),
    teams: Optional[str] = Query(None),
    customer: Optional[str] = Query(None),
    sort: str = Query("revenue_actual_desc"),
    page: int = Query(1, ge=1),
    limit: int = Query(100, ge=1, le=500),
    _user: dict = Depends(require_tag_role(*BUDGET_ROLES)),
):
    """Rollup per customer — one row per customer in the filtered window."""
    pool = get_datalake_gold_pool(request)
    where, params = _where_and_params(start_date, end_date, teams, customer)

    sort_sql = {
        "revenue_actual_desc": "revenue_actual DESC NULLS LAST",
        "revenue_variance_desc": "revenue_variance DESC NULLS LAST",
        "revenue_variance_asc": "revenue_variance ASC NULLS LAST",
        "profit_actual_desc": "profit_actual DESC NULLS LAST",
        "profit_variance_desc": "profit_variance DESC NULLS LAST",
        "loads_actual_desc": "loads_actual DESC NULLS LAST",
        "customer": "customer_name ASC",
    }.get(sort, "revenue_actual DESC NULLS LAST")

    offset = (page - 1) * limit

    rows = await pool.fetch(
        f"""
        WITH {CUSTOMER_TEAM_CTE},
        base AS (
            SELECT
                budget."Customer Name" AS customer_name,
                ct.team_id             AS team_id,
                SUM(budget."Loads Actual")   AS loads_actual,
                SUM(budget."Loads Budget")   AS loads_budget,
                SUM(budget."Revenue Actual") AS revenue_actual,
                SUM(budget."Revenue Budget") AS revenue_budget,
                SUM(budget."Profit Actual")  AS profit_actual,
                SUM(budget."Profit Budget")  AS profit_budget
            FROM public.daily_production_budget_report budget
            JOIN customer_team ct ON TRIM(budget."Customer Name") = ct.customer_name
            WHERE {where}
            GROUP BY budget."Customer Name", ct.team_id
        )
        SELECT
            customer_name,
            team_id,
            loads_actual, loads_budget,
            (loads_actual - loads_budget) AS loads_variance,
            revenue_actual, revenue_budget,
            (revenue_actual - revenue_budget) AS revenue_variance,
            profit_actual, profit_budget,
            (profit_actual - profit_budget) AS profit_variance,
            CASE WHEN revenue_actual > 0 THEN profit_actual / revenue_actual * 100 ELSE 0 END AS margin_actual_pct,
            CASE WHEN revenue_budget > 0 THEN profit_budget / revenue_budget * 100 ELSE 0 END AS margin_budget_pct
        FROM base
        ORDER BY {sort_sql}
        LIMIT ${len(params) + 1} OFFSET ${len(params) + 2}
        """,
        *(params + [limit, offset]),
    )
    total = await pool.fetchval(
        f"""
        WITH {CUSTOMER_TEAM_CTE}
        SELECT COUNT(DISTINCT budget."Customer Name")
        FROM public.daily_production_budget_report budget
        JOIN customer_team ct ON TRIM(budget."Customer Name") = ct.customer_name
        WHERE {where}
        """,
        *params,
    )
    return {
        "success": True,
        "data": [dict(r) for r in rows],
        "meta": {"total": total or 0, "page": page, "limit": limit},
    }


@router.get("/by-team")
async def by_team(
    request: Request,
    start_date: Optional[date] = Query(None),
    end_date: Optional[date] = Query(None),
    customer: Optional[str] = Query(None),
    _user: dict = Depends(require_tag_role(*BUDGET_ROLES)),
):
    """Rollup per Team ID in the window (no teams filter — we want all team cards)."""
    pool = get_datalake_gold_pool(request)
    where, params = _where_and_params(start_date, end_date, None, customer)

    rows = await pool.fetch(
        f"""
        WITH {CUSTOMER_TEAM_CTE}
        SELECT
            ct.team_id AS team_id,
            SUM(budget."Loads Actual")    AS loads_actual,
            SUM(budget."Loads Budget")    AS loads_budget,
            SUM(budget."Revenue Actual")  AS revenue_actual,
            SUM(budget."Revenue Budget")  AS revenue_budget,
            SUM(budget."Profit Actual")   AS profit_actual,
            SUM(budget."Profit Budget")   AS profit_budget
        FROM public.daily_production_budget_report budget
        JOIN customer_team ct ON TRIM(budget."Customer Name") = ct.customer_name
        WHERE {where}
        GROUP BY ct.team_id
        ORDER BY team_id
        """,
        *params,
    )
    return {"success": True, "data": [dict(r) for r in rows]}


@router.get("/monthly")
async def monthly(
    request: Request,
    start_date: Optional[date] = Query(None),
    end_date: Optional[date] = Query(None),
    teams: Optional[str] = Query(None),
    customer: Optional[str] = Query(None),
    _user: dict = Depends(require_tag_role(*BUDGET_ROLES)),
):
    """12-point monthly series — actual and budget for loads/revenue/profit."""
    pool = get_datalake_gold_pool(request)
    where, params = _where_and_params(start_date, end_date, teams, customer)

    rows = await pool.fetch(
        f"""
        WITH {CUSTOMER_TEAM_CTE}
        SELECT
            DATE_TRUNC('month', budget."Date")::date AS month_date,
            SUM(budget."Loads Actual")    AS loads_actual,
            SUM(budget."Loads Budget")    AS loads_budget,
            SUM(budget."Revenue Actual")  AS revenue_actual,
            SUM(budget."Revenue Budget")  AS revenue_budget,
            SUM(budget."Profit Actual")   AS profit_actual,
            SUM(budget."Profit Budget")   AS profit_budget
        FROM public.daily_production_budget_report budget
        JOIN customer_team ct ON TRIM(budget."Customer Name") = ct.customer_name
        WHERE {where}
        GROUP BY 1
        ORDER BY 1
        """,
        *params,
    )
    return {
        "success": True,
        "data": [
            {
                "month_date": r["month_date"].isoformat(),
                "loads_actual": float(r["loads_actual"] or 0),
                "loads_budget": float(r["loads_budget"] or 0),
                "revenue_actual": float(r["revenue_actual"] or 0),
                "revenue_budget": float(r["revenue_budget"] or 0),
                "profit_actual": float(r["profit_actual"] or 0),
                "profit_budget": float(r["profit_budget"] or 0),
            }
            for r in rows
        ],
    }


# ---------------------------------------------------------------------------
# Bruno's 2026-04-28 feedback: weekly chart, top-5 leaderboards, tabbed detail
# ---------------------------------------------------------------------------

def _count_workdays(start: date, end: date) -> int:
    """Mon–Fri days in [start, end] inclusive, excluding US 2026 federal holidays.

    Used by the Avg×LastMonth divisor and Projected days-remaining math in the
    detail-tab tables (Bruno's 2026-04-30 v3 spec — adds holiday calendar to the
    earlier "Mon–Fri, no holidays" rule from 2026-04-28 v2).
    """
    if start > end:
        return 0
    count = 0
    d = start
    while d <= end:
        if d.weekday() < 5 and d not in US_HOLIDAYS_2026:
            count += 1
        d = d + timedelta(days=1)
    return count


def _windows():
    """Anchor points for tab metrics.

    Day-count denominators (Avg×LastMonth divisor and Projected days-remaining)
    are *Mon–Fri working days, no holidays* per Bruno's 2026-04-28 v2 spec.
    Numerator sums (revenue/profit windows) still aggregate every calendar day
    with data — the spec just constrains the divisor.
    """
    today = cst_today()
    yesterday = today - timedelta(days=1)

    last_month_end = today.replace(day=1) - timedelta(days=1)
    last_month_start = last_month_end.replace(day=1)
    workdays_in_last_month = _count_workdays(last_month_start, last_month_end)

    cm_start = today.replace(day=1)
    cm_end = today.replace(day=monthrange(today.year, today.month)[1])
    # Actuals through yesterday — today's data is partial (n8n every 6h).
    cm_actual_end = max(cm_start, yesterday)
    # "Remaining" = today through end of month (today inclusive — its work is
    # still ahead, even if the row is partial).
    cm_workdays_remaining = _count_workdays(today, cm_end) if today <= cm_end else 0

    last21_start = yesterday - timedelta(days=20)  # inclusive 21 days
    last14_start = yesterday - timedelta(days=13)  # inclusive 14 days

    # Bound for SQL date filter: oldest needed boundary.
    min_scan = min(YEAR_START, last_month_start, last21_start, last14_start)
    return {
        "today": today,
        "yesterday": yesterday,
        "last_month_start": last_month_start,
        "last_month_end": last_month_end,
        "workdays_in_last_month": workdays_in_last_month,
        "cm_start": cm_start,
        "cm_actual_end": cm_actual_end,
        "cm_workdays_remaining": cm_workdays_remaining,
        "last21_start": last21_start,
        "last14_start": last14_start,
        "min_scan": min_scan,
    }


@router.get("/by-customer-detail")
async def by_customer_detail(
    request: Request,
    start_date: Optional[date] = Query(None),
    end_date: Optional[date] = Query(None),
    teams: Optional[str] = Query(None),
    customer: Optional[str] = Query(None),
    _user: dict = Depends(require_tag_role(*BUDGET_ROLES)),
):
    """Per-customer trajectory rows for the Revenue/Profit/Loads tabs.

    Actual / Budget / Var respect the filter date window (so they line up with
    the Overview tab). The avg-and-projected columns are anchored to *now*
    (last calendar month, rolling 21d, rolling 14d, current MTD) regardless
    of the filter range.
    """
    pool = get_datalake_gold_pool(request)
    s = _clamp(start_date, YEAR_START)
    e = _clamp(end_date, YEAR_END)
    w = _windows()

    params: list = [
        s,                   # $1 window start
        e,                   # $2 window end
        w["last_month_start"],  # $3
        w["last_month_end"],    # $4
        w["last21_start"],   # $5
        w["last14_start"],   # $6
        w["yesterday"],      # $7  (also used as upper bound for last21/last14)
        w["cm_start"],       # $8
        w["cm_actual_end"],  # $9
        w["min_scan"],       # $10 outer date floor
        e,                   # $11 outer date ceiling
    ]
    parts = ['budget."Date" BETWEEN $10 AND $11']
    team_list = _parse_teams(teams)
    if team_list:
        params.append(team_list)
        parts.append(f"ct.team_id = ANY(${len(params)})")
    if customer:
        params.append(customer)
        parts.append(f'budget."Customer Name" = ${len(params)}')
    where = " AND ".join(parts)

    days_in_last = w["workdays_in_last_month"] or 1
    cm_remaining = w["cm_workdays_remaining"]

    # Three metrics in one query — cuts the round-trip overhead 3×.
    rows = await pool.fetch(
        f"""
        WITH {CUSTOMER_TEAM_CTE},
        agg AS (
            SELECT
                budget."Customer Name" AS customer_name,
                ct.team_id             AS team_id,

                -- WINDOW (filter range) actual + budget for each metric
                COALESCE(SUM(budget."Revenue Actual") FILTER (WHERE budget."Date" BETWEEN $1 AND $2), 0) AS rev_actual,
                COALESCE(SUM(budget."Revenue Budget") FILTER (WHERE budget."Date" BETWEEN $1 AND $2), 0) AS rev_budget,
                COALESCE(SUM(budget."Profit Actual")  FILTER (WHERE budget."Date" BETWEEN $1 AND $2), 0) AS prof_actual,
                COALESCE(SUM(budget."Profit Budget")  FILTER (WHERE budget."Date" BETWEEN $1 AND $2), 0) AS prof_budget,
                COALESCE(SUM(budget."Loads Actual")   FILTER (WHERE budget."Date" BETWEEN $1 AND $2), 0) AS loads_actual,
                COALESCE(SUM(budget."Loads Budget")   FILTER (WHERE budget."Date" BETWEEN $1 AND $2), 0) AS loads_budget,

                -- LAST MONTH (calendar)
                COALESCE(SUM(budget."Revenue Actual") FILTER (WHERE budget."Date" BETWEEN $3 AND $4), 0) AS rev_last_month,
                COALESCE(SUM(budget."Profit Actual")  FILTER (WHERE budget."Date" BETWEEN $3 AND $4), 0) AS prof_last_month,
                COALESCE(SUM(budget."Loads Actual")   FILTER (WHERE budget."Date" BETWEEN $3 AND $4), 0) AS loads_last_month,

                -- LAST 21 DAYS (rolling 3 weeks, inclusive through yesterday)
                COALESCE(SUM(budget."Revenue Actual") FILTER (WHERE budget."Date" BETWEEN $5 AND $7), 0) AS rev_last21,
                COALESCE(SUM(budget."Profit Actual")  FILTER (WHERE budget."Date" BETWEEN $5 AND $7), 0) AS prof_last21,
                COALESCE(SUM(budget."Loads Actual")   FILTER (WHERE budget."Date" BETWEEN $5 AND $7), 0) AS loads_last21,

                -- LAST 14 DAYS (rolling 2 weeks, inclusive through yesterday)
                COALESCE(SUM(budget."Revenue Actual") FILTER (WHERE budget."Date" BETWEEN $6 AND $7), 0) AS rev_last14,
                COALESCE(SUM(budget."Profit Actual")  FILTER (WHERE budget."Date" BETWEEN $6 AND $7), 0) AS prof_last14,
                COALESCE(SUM(budget."Loads Actual")   FILTER (WHERE budget."Date" BETWEEN $6 AND $7), 0) AS loads_last14,

                -- CURRENT MONTH-TO-YESTERDAY actual
                COALESCE(SUM(budget."Revenue Actual") FILTER (WHERE budget."Date" BETWEEN $8 AND $9), 0) AS rev_mtd,
                COALESCE(SUM(budget."Profit Actual")  FILTER (WHERE budget."Date" BETWEEN $8 AND $9), 0) AS prof_mtd,
                COALESCE(SUM(budget."Loads Actual")   FILTER (WHERE budget."Date" BETWEEN $8 AND $9), 0) AS loads_mtd
            FROM public.daily_production_budget_report budget
            JOIN customer_team ct ON TRIM(budget."Customer Name") = ct.customer_name
            WHERE {where}
            GROUP BY budget."Customer Name", ct.team_id
        )
        SELECT
            customer_name,
            team_id,

            rev_actual,  rev_budget,  (rev_actual  - rev_budget)  AS rev_var,
            (rev_last_month / {days_in_last})::numeric              AS rev_avg_last_month,
            (rev_last21 / 3.0)::numeric                              AS rev_avg_week,
            (rev_last14 / 14.0)::numeric                             AS rev_avg_day,
            ((rev_last_month / {days_in_last}) * {cm_remaining} + rev_mtd)::numeric AS rev_projected,

            prof_actual, prof_budget, (prof_actual - prof_budget) AS prof_var,
            (prof_last_month / {days_in_last})::numeric              AS prof_avg_last_month,
            (prof_last21 / 3.0)::numeric                             AS prof_avg_week,
            (prof_last14 / 14.0)::numeric                            AS prof_avg_day,
            ((prof_last_month / {days_in_last}) * {cm_remaining} + prof_mtd)::numeric AS prof_projected,

            loads_actual, loads_budget, (loads_actual - loads_budget) AS loads_var,
            (loads_last_month / {days_in_last})::numeric             AS loads_avg_last_month,
            (loads_last21 / 3.0)::numeric                            AS loads_avg_week,
            (loads_last14 / 14.0)::numeric                           AS loads_avg_day,
            ((loads_last_month / {days_in_last}) * {cm_remaining} + loads_mtd)::numeric AS loads_projected
        FROM agg
        ORDER BY rev_actual DESC NULLS LAST
        """,
        *params,
    )

    def _f(row, key):
        v = row[key]
        return float(v) if v is not None else 0.0

    data = []
    for r in rows:
        data.append({
            "customer_name": r["customer_name"],
            "team_id": r["team_id"],
            "revenue": {
                "actual": _f(r, "rev_actual"),
                "budget": _f(r, "rev_budget"),
                "var": _f(r, "rev_var"),
                "avg_last_month": _f(r, "rev_avg_last_month"),
                "avg_week": _f(r, "rev_avg_week"),
                "avg_day": _f(r, "rev_avg_day"),
                "projected": _f(r, "rev_projected"),
            },
            "profit": {
                "actual": _f(r, "prof_actual"),
                "budget": _f(r, "prof_budget"),
                "var": _f(r, "prof_var"),
                "avg_last_month": _f(r, "prof_avg_last_month"),
                "avg_week": _f(r, "prof_avg_week"),
                "avg_day": _f(r, "prof_avg_day"),
                "projected": _f(r, "prof_projected"),
            },
            "loads": {
                "actual": _f(r, "loads_actual"),
                "budget": _f(r, "loads_budget"),
                "var": _f(r, "loads_var"),
                "avg_last_month": _f(r, "loads_avg_last_month"),
                "avg_week": _f(r, "loads_avg_week"),
                "avg_day": _f(r, "loads_avg_day"),
                "projected": _f(r, "loads_projected"),
            },
        })

    return {
        "success": True,
        "data": data,
        "meta": {
            "windows": {
                "last_month_start": w["last_month_start"].isoformat(),
                "last_month_end": w["last_month_end"].isoformat(),
                "workdays_in_last_month": w["workdays_in_last_month"],
                "current_month_actual_end": w["cm_actual_end"].isoformat(),
                "current_month_workdays_remaining": w["cm_workdays_remaining"],
                "day_basis": "mon-fri (no holidays)",
            },
        },
    }


@router.get("/top5")
async def top5(
    request: Request,
    start_date: Optional[date] = Query(None),
    end_date: Optional[date] = Query(None),
    teams: Optional[str] = Query(None),
    customer: Optional[str] = Query(None),
    _user: dict = Depends(require_tag_role(*BUDGET_ROLES)),
):
    """Five small leaderboards: Top/Worst Volume, Top/Worst Profit, Non-Budget Active.

    All buckets respect the same Range/Team/Customer filters as the rest of the
    page. Each list is at most 5 rows.
    """
    pool = get_datalake_gold_pool(request)
    where, params = _where_and_params(start_date, end_date, teams, customer)

    rows = await pool.fetch(
        f"""
        WITH {CUSTOMER_TEAM_CTE},
        agg AS (
            SELECT
                budget."Customer Name" AS customer_name,
                COALESCE(SUM(budget."Loads Actual"),  0) AS loads_actual,
                COALESCE(SUM(budget."Loads Budget"),  0) AS loads_budget,
                COALESCE(SUM(budget."Profit Actual"), 0) AS profit_actual,
                COALESCE(SUM(budget."Profit Budget"), 0) AS profit_budget
            FROM public.daily_production_budget_report budget
            JOIN customer_team ct ON TRIM(budget."Customer Name") = ct.customer_name
            WHERE {where}
            GROUP BY budget."Customer Name"
        )
        SELECT
            customer_name,
            (loads_actual  - loads_budget)  AS loads_var,
            (profit_actual - profit_budget) AS profit_var,
            loads_actual, loads_budget,
            profit_actual, profit_budget
        FROM agg
        """,
        *params,
    )

    customers = [dict(r) for r in rows]

    def _pick(predicate, sort_key, reverse=True, limit=5):
        return [
            {
                "customer_name": r["customer_name"],
                "loads_var": float(r["loads_var"] or 0),
                "profit_var": float(r["profit_var"] or 0),
                "loads_actual": float(r["loads_actual"] or 0),
                "loads_budget": float(r["loads_budget"] or 0),
                "profit_actual": float(r["profit_actual"] or 0),
                "profit_budget": float(r["profit_budget"] or 0),
            }
            for r in sorted(
                [c for c in customers if predicate(c)],
                key=sort_key,
                reverse=reverse,
            )[:limit]
        ]

    has_loads_budget    = lambda c: float(c["loads_budget"] or 0) > 0
    has_profit_budget   = lambda c: float(c["profit_budget"] or 0) > 0
    no_profit_budget    = lambda c: float(c["profit_budget"] or 0) == 0 and float(c["profit_actual"] or 0) > 0

    return {
        "success": True,
        "data": {
            "top_volume":  _pick(has_loads_budget,  lambda c: float(c["loads_var"]  or 0), reverse=True),
            "worst_volume": _pick(has_loads_budget, lambda c: float(c["loads_var"]  or 0), reverse=False),
            "top_profit":  _pick(has_profit_budget, lambda c: float(c["profit_var"] or 0), reverse=True),
            "worst_profit": _pick(has_profit_budget, lambda c: float(c["profit_var"] or 0), reverse=False),
            "non_budget":  _pick(no_profit_budget,  lambda c: float(c["profit_actual"] or 0), reverse=True),
        },
    }


@router.get("/weekly")
async def weekly(
    request: Request,
    teams: Optional[str] = Query(None),
    customer: Optional[str] = Query(None),
    _user: dict = Depends(require_tag_role(*BUDGET_ROLES)),
):
    """Last 12 ISO weeks (Mon–Sun, current excluded — Attrition WoW convention)."""
    pool = get_datalake_gold_pool(request)

    today = cst_today()
    # ISO Monday of current week, then back 12 weeks => 12-week window through last Sunday.
    weekday = today.isoweekday()  # Mon=1
    cur_week_mon = today - timedelta(days=weekday - 1)
    last_week_sun = cur_week_mon - timedelta(days=1)
    window_start = cur_week_mon - timedelta(weeks=12)  # 12 full prior weeks
    window_end = last_week_sun

    parts = ['budget."Date" BETWEEN $1 AND $2']
    params: list = [window_start, window_end]
    team_list = _parse_teams(teams)
    if team_list:
        params.append(team_list)
        parts.append(f"ct.team_id = ANY(${len(params)})")
    if customer:
        params.append(customer)
        parts.append(f'budget."Customer Name" = ${len(params)}')
    where = " AND ".join(parts)

    rows = await pool.fetch(
        f"""
        WITH {CUSTOMER_TEAM_CTE}
        SELECT
            DATE_TRUNC('week', budget."Date")::date AS week_start,
            SUM(budget."Loads Actual")   AS loads_actual,
            SUM(budget."Loads Budget")   AS loads_budget,
            SUM(budget."Revenue Actual") AS revenue_actual,
            SUM(budget."Revenue Budget") AS revenue_budget,
            SUM(budget."Profit Actual")  AS profit_actual,
            SUM(budget."Profit Budget")  AS profit_budget
        FROM public.daily_production_budget_report budget
        JOIN customer_team ct ON TRIM(budget."Customer Name") = ct.customer_name
        WHERE {where}
        GROUP BY 1
        ORDER BY 1
        """,
        *params,
    )

    return {
        "success": True,
        "data": [
            {
                "week_start": r["week_start"].isoformat(),
                "loads_actual": float(r["loads_actual"] or 0),
                "loads_budget": float(r["loads_budget"] or 0),
                "revenue_actual": float(r["revenue_actual"] or 0),
                "revenue_budget": float(r["revenue_budget"] or 0),
                "profit_actual": float(r["profit_actual"] or 0),
                "profit_budget": float(r["profit_budget"] or 0),
            }
            for r in rows
        ],
    }
