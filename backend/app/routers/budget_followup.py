"""Code-made report: 2026 Official Budget Follow Up.

Reads from aivn_datalake_gold.public.daily_production_budget_report (refreshed every
6 hours by the n8n workflow 'CORP Update Production vs Goals Follow Up' — SQi0VmZS1nYmo7Kt).

Scope: Date BETWEEN 2026-01-01 AND 2026-12-31. Team IDs TEAM1-TEAM5.
UI filters narrow within this window. Does not recompute actuals/budgets — the workflow
owns that math; this router just aggregates per filter.
"""

from datetime import date
from typing import Optional

from fastapi import APIRouter, Depends, Query, Request

from app.routers.deps import get_datalake_gold_pool, require_tag_role

BUDGET_ROLES = ("CEO", "Executive", "Operations", "Finance", "CORP", "DFW")

# Scope of this report.
YEAR_START = date(2026, 1, 1)
YEAR_END = date(2026, 12, 31)

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
    parts = ['"Date" BETWEEN $1 AND $2']
    params: list = [s, e]
    team_list = _parse_teams(teams)
    if team_list:
        params.append(team_list)
        parts.append(f'"Team ID" = ANY(${len(params)})')
    if customer:
        params.append(customer)
        parts.append(f'"Customer Name" = ${len(params)}')
    return " AND ".join(parts), params


@router.get("/filters")
async def filters(
    request: Request,
    _user: dict = Depends(require_tag_role(*BUDGET_ROLES)),
):
    """Distinct teams and customers in the 2026 window — powers the dropdowns."""
    pool = get_datalake_gold_pool(request)
    teams = await pool.fetch(
        """
        SELECT DISTINCT "Team ID" AS team_id
        FROM public.daily_production_budget_report
        WHERE "Date" BETWEEN $1 AND $2 AND "Team ID" IS NOT NULL
        ORDER BY team_id
        """,
        YEAR_START,
        YEAR_END,
    )
    customers = await pool.fetch(
        """
        SELECT DISTINCT "Customer Name" AS customer_name
        FROM public.daily_production_budget_report
        WHERE "Date" BETWEEN $1 AND $2 AND "Customer Name" IS NOT NULL
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
        SELECT
            COALESCE(SUM("Loads Actual"),    0)::numeric  AS loads_actual,
            COALESCE(SUM("Loads Budget"),    0)::numeric  AS loads_budget,
            COALESCE(SUM("Revenue Actual"),  0)::numeric  AS revenue_actual,
            COALESCE(SUM("Revenue Budget"),  0)::numeric  AS revenue_budget,
            COALESCE(SUM("Profit Actual"),   0)::numeric  AS profit_actual,
            COALESCE(SUM("Profit Budget"),   0)::numeric  AS profit_budget,
            COUNT(DISTINCT "Customer Name") FILTER (WHERE "Loads Actual" > 0)       AS active_customers,
            COUNT(DISTINCT "Customer Name")                                           AS total_customers,
            COUNT(DISTINCT "Date") FILTER (WHERE "Loads Actual" > 0 OR "Loads Budget" > 0) AS active_days
        FROM public.daily_production_budget_report
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

    # Working-days elapsed / remaining within the applied window (vs full year 2026).
    today = date.today()
    clamp_today = min(max(today, YEAR_START), YEAR_END)
    total_days = (YEAR_END - YEAR_START).days + 1
    elapsed_days = (clamp_today - YEAR_START).days + (1 if clamp_today >= YEAR_START else 0)
    data["total_days"] = total_days
    data["days_elapsed"] = max(0, min(total_days, elapsed_days))
    data["days_remaining"] = max(0, total_days - data["days_elapsed"])

    data["start_date"] = _clamp(start_date, YEAR_START).isoformat()
    data["end_date"] = _clamp(end_date, YEAR_END).isoformat()

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
        "customer": 'customer_name ASC',
    }.get(sort, "revenue_actual DESC NULLS LAST")

    offset = (page - 1) * limit

    rows = await pool.fetch(
        f"""
        WITH base AS (
            SELECT
                "Customer Name" AS customer_name,
                SUM("Loads Actual")   AS loads_actual,
                SUM("Loads Budget")   AS loads_budget,
                SUM("Revenue Actual") AS revenue_actual,
                SUM("Revenue Budget") AS revenue_budget,
                SUM("Profit Actual")  AS profit_actual,
                SUM("Profit Budget")  AS profit_budget
            FROM public.daily_production_budget_report
            WHERE {where}
            GROUP BY "Customer Name"
        )
        SELECT
            customer_name,
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
        SELECT COUNT(DISTINCT "Customer Name")
        FROM public.daily_production_budget_report
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
    """Rollup per Team ID in the window (no teams filter — we want all 5 cards)."""
    pool = get_datalake_gold_pool(request)
    where, params = _where_and_params(start_date, end_date, None, customer)

    rows = await pool.fetch(
        f"""
        SELECT
            "Team ID" AS team_id,
            SUM("Loads Actual")    AS loads_actual,
            SUM("Loads Budget")    AS loads_budget,
            SUM("Revenue Actual")  AS revenue_actual,
            SUM("Revenue Budget")  AS revenue_budget,
            SUM("Profit Actual")   AS profit_actual,
            SUM("Profit Budget")   AS profit_budget
        FROM public.daily_production_budget_report
        WHERE {where}
        GROUP BY "Team ID"
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
        SELECT
            DATE_TRUNC('month', "Date")::date AS month_date,
            SUM("Loads Actual")    AS loads_actual,
            SUM("Loads Budget")    AS loads_budget,
            SUM("Revenue Actual")  AS revenue_actual,
            SUM("Revenue Budget")  AS revenue_budget,
            SUM("Profit Actual")   AS profit_actual,
            SUM("Profit Budget")   AS profit_budget
        FROM public.daily_production_budget_report
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
