"""Code-made report: eSavings from Carriers.

Reads from aivn_datalake_gold.carriers_savings_results_report (populated daily by the
'Carriers Savings Update - 4 AM CST' n8n workflow, PdZIaBQPGSLD4VWB).

Base-lane rules (set 2026-04-16, nothing else):
  - Jul 2025 - Mar 2026 -> first month the lane had loads (e.g. base_month='2025-07')
  - Apr - Dec 2026      -> simple avg of non-zero Q1 2026 monthly avgs (base_month='Q1-2026')

Division / Team filter (added 2026-04-17):
  When `division` or `team` is set, results are restricted to customers that map to
  the selected teams via public.mcleod_gld_budget_report_v4 (same dominant-team-per-
  customer rule used in budget_followup_2026). Customers not present in McLeod are
  excluded ONLY when a filter is active; without a filter the report keeps its full
  historical universe so unfiltered numbers match today's dashboard.

This router reads `base_lane` / `base_month` / `variance` as-is; no recomputation.
"""

from datetime import date
from typing import Optional

from fastapi import APIRouter, Depends, Query, Request

from app.routers.deps import get_savings_pool, require_tag_role

# TagRoles that can view eSavings from Carriers (admin bypasses).
# DFW added 2026-04-17 so DFW users can filter by their own division.
SAVINGS_ROLES = ("CEO", "Executive", "Procurement", "Finance", "CORP", "DFW")

# Division → McLeod team_id mapping. Kept in sync with budget_followup_2026.
DIVISION_TEAMS: dict[str, tuple[str, ...]] = {
    "CORP": ("TEAM1", "TEAM2", "TEAM3", "TEAM4", "TEAM5"),
    "DFW": ("TEAM-DFW",),
}
ALL_ALLOWED_TEAMS = tuple(t for teams in DIVISION_TEAMS.values() for t in teams)

# Per-customer canonical team, derived from McLeod. One row per customer: the team
# with the most loads (tiebreak alphabetical). Prepend with `WITH ` when embedding.
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
        WHERE TRIM(team_id) IN {ALL_ALLOWED_TEAMS!r}
        GROUP BY TRIM(customer_name), TRIM(team_id)
    ) ranked
    WHERE rn = 1
)
"""

router = APIRouter(tags=["carriers-savings"], prefix="/custom/carriers-savings")


def _resolve_team_filter(
    division: Optional[str], team: Optional[str]
) -> Optional[list[str]]:
    """Translate (division, team) into the list of team_ids to restrict on.

    - `None`         → no restriction (join skipped, full historical universe).
    - `[]`           → inputs were set but invalid/unknown → force zero rows.
    - `[...]`        → explicit team list; strict inner join on McLeod.

    When both are set, `team` wins (narrower).
    """
    if team:
        value = team.strip().upper()
        if value in ALL_ALLOWED_TEAMS:
            return [value]
        return []
    if division:
        value = division.strip().upper()
        if value in DIVISION_TEAMS:
            return list(DIVISION_TEAMS[value])
        return []
    return None


def _build_team_clauses(
    team_ids: Optional[list[str]], next_param_index: int
) -> tuple[str, str, str, list]:
    """Return (cte_prefix, join_sql, where_extra, extra_params).

    `cte_prefix` starts with `WITH ` so it can be prepended directly to a query.
    `next_param_index` is the 1-based positional index of the next placeholder.
    """
    if team_ids is None:
        return "", "", "", []
    if not team_ids:
        # Filter was set but resolved to no valid teams — force empty result.
        return "", "", " AND FALSE", []
    return (
        f"WITH {CUSTOMER_TEAM_CTE}",
        "JOIN customer_team ct ON TRIM(report.customer_name) = ct.customer_name",
        f" AND ct.team_id = ANY(${next_param_index})",
        [team_ids],
    )


@router.get("/months")
async def list_months(
    request: Request,
    _user: dict = Depends(require_tag_role(*SAVINGS_ROLES)),
):
    """Distinct months available in the report table, newest first."""
    pool = get_savings_pool(request)
    rows = await pool.fetch(
        """
        SELECT DISTINCT month_date::text AS month_date,
                        type_month_description,
                        MAX(base_month) AS base_month
        FROM public.carriers_savings_results_report
        WHERE month_date IS NOT NULL
        GROUP BY month_date, type_month_description
        ORDER BY month_date DESC
        """
    )
    return {"success": True, "data": [dict(r) for r in rows]}


@router.get("/summary")
async def summary(
    request: Request,
    month: Optional[date] = Query(None, description="YYYY-MM-01"),
    customer_id: Optional[str] = Query(None),
    division: Optional[str] = Query(None, description="CORP | DFW"),
    team: Optional[str] = Query(None, description="TEAM1..TEAM5 | TEAM-DFW"),
    _user: dict = Depends(require_tag_role(*SAVINGS_ROLES)),
):
    """4 main KPIs for a given month: loads, savings, overpay, net variance.

    Mirrors the Qlik dashboard logic:
      - Total Savings  = SUM(variance WHERE variance > 0)
      - Total Overpay  = SUM(variance WHERE variance < 0)  (negative number)
      - Net Variance   = SUM(variance)
      - Volume (Loads) = SUM(number_monthly_loads)
    Plus lane-volume buckets (high-vol >=8, low-vol 1-7).
    """
    pool = get_savings_pool(request)

    target_month = await _resolve_month(pool, month)

    team_ids = _resolve_team_filter(division, team)
    params: list = [target_month, customer_id]
    cte, join_sql, where_extra, extra_params = _build_team_clauses(
        team_ids, next_param_index=len(params) + 1
    )
    params.extend(extra_params)

    row = await pool.fetchrow(
        f"""
        {cte}
        SELECT
          COALESCE(SUM(report.number_monthly_loads), 0)                        AS total_loads,
          COALESCE(SUM(report.cost_monthly_usd), 0)                            AS total_cost,
          COALESCE(SUM(CASE WHEN report.variance > 0 THEN report.variance END), 0) AS total_savings,
          COALESCE(SUM(CASE WHEN report.variance < 0 THEN report.variance END), 0) AS total_overpay,
          COALESCE(SUM(report.variance), 0)                                    AS net_variance,
          COUNT(*) FILTER (WHERE report.number_monthly_loads >= 8)             AS high_vol_lanes,
          COUNT(*) FILTER (WHERE report.number_monthly_loads BETWEEN 1 AND 7)  AS low_vol_lanes,
          COUNT(*) FILTER (WHERE report.number_monthly_loads >= 8
                             AND report.variance > 0)                          AS high_vol_savings_lanes,
          COUNT(*) FILTER (WHERE report.number_monthly_loads BETWEEN 1 AND 7
                             AND report.variance > 0)                          AS low_vol_savings_lanes,
          MAX(report.base_month)                                               AS base_month,
          AVG(NULLIF(report.base_lane, 0))                                     AS avg_base_lane
        FROM public.carriers_savings_results_report report
        {join_sql}
        WHERE report.month_date = $1
          AND ($2::text IS NULL OR report.customer_id = $2)
          {where_extra}
        """,
        *params,
    )

    data = dict(row) if row else {}
    data["month_date"] = target_month.isoformat() if target_month else None
    return {"success": True, "data": data}


@router.get("/by-customer")
async def by_customer(
    request: Request,
    month: Optional[date] = Query(None),
    division: Optional[str] = Query(None),
    team: Optional[str] = Query(None),
    _user: dict = Depends(require_tag_role(*SAVINGS_ROLES)),
    limit: int = Query(50, ge=1, le=500),
):
    """Aggregate savings per customer for a given month, biggest savings first."""
    pool = get_savings_pool(request)
    target_month = await _resolve_month(pool, month)

    team_ids = _resolve_team_filter(division, team)
    params: list = [target_month]
    cte, join_sql, where_extra, extra_params = _build_team_clauses(
        team_ids, next_param_index=len(params) + 1
    )
    params.extend(extra_params)
    params.append(limit)
    limit_placeholder = f"${len(params)}"

    rows = await pool.fetch(
        f"""
        {cte}
        SELECT
          report.customer_id,
          report.customer_name,
          COUNT(*)                                                   AS lane_count,
          SUM(report.number_monthly_loads)                           AS loads,
          SUM(report.cost_monthly_usd)                               AS cost,
          SUM(CASE WHEN report.variance > 0 THEN report.variance END) AS savings,
          SUM(CASE WHEN report.variance < 0 THEN report.variance END) AS overpay,
          SUM(report.variance)                                       AS net_variance
        FROM public.carriers_savings_results_report report
        {join_sql}
        WHERE report.month_date = $1
          {where_extra}
        GROUP BY report.customer_id, report.customer_name
        HAVING SUM(report.number_monthly_loads) > 0
        ORDER BY SUM(report.variance) DESC NULLS LAST
        LIMIT {limit_placeholder}
        """,
        *params,
    )
    return {
        "success": True,
        "data": [dict(r) for r in rows],
        "meta": {"month_date": target_month.isoformat() if target_month else None},
    }


@router.get("/lanes")
async def lanes(
    request: Request,
    month: Optional[date] = Query(None),
    customer_id: Optional[str] = Query(None),
    origin: Optional[str] = Query(None),
    dest: Optional[str] = Query(None),
    division: Optional[str] = Query(None),
    team: Optional[str] = Query(None),
    sort: str = Query("variance_desc"),
    page: int = Query(1, ge=1),
    limit: int = Query(100, ge=1, le=500),
    _user: dict = Depends(require_tag_role(*SAVINGS_ROLES)),
):
    """Detail rows — one row per lane for the selected month, with filters + paging."""
    pool = get_savings_pool(request)
    target_month = await _resolve_month(pool, month)

    sort_sql = {
        "variance_desc": "report.variance DESC NULLS LAST",
        "variance_asc": "report.variance ASC NULLS LAST",
        "loads_desc": "report.number_monthly_loads DESC",
        "cost_desc": "report.cost_monthly_usd DESC",
        "customer": "report.customer_name ASC",
    }.get(sort, "report.variance DESC NULLS LAST")

    offset = (page - 1) * limit

    where_parts = ["report.month_date = $1"]
    params: list = [target_month]
    if customer_id:
        params.append(customer_id)
        where_parts.append(f"report.customer_id = ${len(params)}")
    if origin:
        params.append(f"%{origin}%")
        where_parts.append(f"report.origin_name ILIKE ${len(params)}")
    if dest:
        params.append(f"%{dest}%")
        where_parts.append(f"report.dest_name ILIKE ${len(params)}")

    team_ids = _resolve_team_filter(division, team)
    cte, join_sql, where_extra, extra_params = _build_team_clauses(
        team_ids, next_param_index=len(params) + 1
    )
    params.extend(extra_params)
    if where_extra:
        # where_extra already starts with " AND "; strip that prefix when appending.
        where_parts.append(where_extra.lstrip().removeprefix("AND ").strip())

    count_params = list(params)

    params_with_paging = params + [limit, offset]

    rows = await pool.fetch(
        f"""
        {cte}
        SELECT report.customer_id, report.customer_name, report.origin_name, report.dest_name,
               report.cost_monthly_usd, report.number_monthly_loads, report.avg_monthly_usd,
               report.variance, report.base_lane, report.base_month, report.type_month_description,
               report.month_date::text AS month_date
        FROM public.carriers_savings_results_report report
        {join_sql}
        WHERE {' AND '.join(where_parts)}
        ORDER BY {sort_sql}
        LIMIT ${len(params) + 1} OFFSET ${len(params) + 2}
        """,
        *params_with_paging,
    )

    total = await pool.fetchval(
        f"""
        {cte}
        SELECT COUNT(*)
        FROM public.carriers_savings_results_report report
        {join_sql}
        WHERE {' AND '.join(where_parts)}
        """,
        *count_params,
    )

    return {
        "success": True,
        "data": [dict(r) for r in rows],
        "meta": {
            "total": total,
            "page": page,
            "limit": limit,
            "month_date": target_month.isoformat() if target_month else None,
        },
    }


async def _resolve_month(pool, requested: Optional[date]) -> Optional[date]:
    """Pick the month to display:
      1. Explicit request wins — if it has data, use it.
      2. Otherwise prefer the current calendar month when it has data
         (this keeps the dashboard on "today's month" by default).
      3. Fall back to the latest month with data.
    """
    if requested is not None:
        exists = await pool.fetchval(
            "SELECT 1 FROM public.carriers_savings_results_report WHERE month_date = $1 LIMIT 1",
            requested,
        )
        if exists:
            return requested
    current = await pool.fetchval(
        """
        SELECT month_date FROM public.carriers_savings_results_report
        WHERE month_date = date_trunc('month', CURRENT_DATE)::date
        LIMIT 1
        """
    )
    if current:
        return current
    return await pool.fetchval(
        "SELECT MAX(month_date) FROM public.carriers_savings_results_report"
    )
