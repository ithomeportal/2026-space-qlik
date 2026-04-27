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

import asyncio
import logging
from datetime import date
from typing import Optional

import httpx
from fastapi import APIRouter, Depends, Query, Request

from app.routers.deps import get_savings_pool, require_tag_role
from app.services.lane_rates import (
    Lane,
    fetch_lb123_history,
    fetch_sonar_history,
    get_cached_rates,
    make_lane,
    upsert_rates,
)

_logger = logging.getLogger(__name__)

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


def _collect_lane_filters(
    params: list, origin: Optional[str], dest: Optional[str]
) -> list[str]:
    """Append origin/dest ILIKE values to `params` in place.

    Returns the WHERE fragments (without leading AND). Caller joins them.
    Origin/dest come from the Lanes filter but apply to every endpoint so
    the whole report (KPIs, teams, trend) respects the user's lane scope.
    """
    parts: list[str] = []
    if origin:
        params.append(f"%{origin}%")
        parts.append(f"report.origin_name ILIKE ${len(params)}")
    if dest:
        params.append(f"%{dest}%")
        parts.append(f"report.dest_name ILIKE ${len(params)}")
    return parts


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
    origin: Optional[str] = Query(None, description="Origin ILIKE substring"),
    dest: Optional[str] = Query(None, description="Destination ILIKE substring"),
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

    params: list = [target_month, customer_id]
    lane_parts = _collect_lane_filters(params, origin, dest)
    lane_extra = ("".join(f" AND {p}" for p in lane_parts))

    team_ids = _resolve_team_filter(division, team)
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
          {lane_extra}
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
    origin: Optional[str] = Query(None, description="Origin ILIKE substring"),
    dest: Optional[str] = Query(None, description="Destination ILIKE substring"),
    _user: dict = Depends(require_tag_role(*SAVINGS_ROLES)),
    limit: int = Query(50, ge=1, le=500),
):
    """Aggregate savings per customer for a given month, biggest savings first."""
    pool = get_savings_pool(request)
    target_month = await _resolve_month(pool, month)

    params: list = [target_month]
    lane_parts = _collect_lane_filters(params, origin, dest)
    lane_extra = "".join(f" AND {p}" for p in lane_parts)

    team_ids = _resolve_team_filter(division, team)
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
          {lane_extra}
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


@router.get("/by-team")
async def by_team(
    request: Request,
    month: Optional[date] = Query(None),
    customer_id: Optional[str] = Query(None),
    division: Optional[str] = Query(None),
    team: Optional[str] = Query(None),
    origin: Optional[str] = Query(None, description="Origin ILIKE substring"),
    dest: Optional[str] = Query(None, description="Destination ILIKE substring"),
    _user: dict = Depends(require_tag_role(*SAVINGS_ROLES)),
):
    """One row per (division, team_id) for the selected month.

    Always uses the McLeod customer→team join — the point of this breakdown IS
    the per-team split. Customers missing from McLeod never appear here, even
    when no division/team filter is applied. When a filter IS applied, rows
    are narrowed accordingly.

    Ordering: CORP teams first (team_id ASC), then DFW.
    """
    pool = get_savings_pool(request)
    target_month = await _resolve_month(pool, month)

    where_parts = ["report.month_date = $1"]
    params: list = [target_month]

    if customer_id:
        params.append(customer_id)
        where_parts.append(f"report.customer_id = ${len(params)}")

    where_parts.extend(_collect_lane_filters(params, origin, dest))

    # Resolve which team_ids to include. When no filter is set, we still want
    # the full breakdown — so default to every allowed team.
    team_ids = _resolve_team_filter(division, team)
    if team_ids is None:
        scoped_teams = list(ALL_ALLOWED_TEAMS)
    else:
        scoped_teams = team_ids

    if not scoped_teams:
        return {
            "success": True,
            "data": [],
            "meta": {"month_date": target_month.isoformat() if target_month else None},
        }

    params.append(scoped_teams)
    where_parts.append(f"ct.team_id = ANY(${len(params)})")

    rows = await pool.fetch(
        f"""
        WITH {CUSTOMER_TEAM_CTE}
        SELECT
            CASE WHEN ct.team_id = 'TEAM-DFW' THEN 'DFW' ELSE 'CORP' END      AS division,
            ct.team_id                                                        AS team_id,
            COALESCE(SUM(report.number_monthly_loads), 0)::numeric            AS loads,
            COALESCE(SUM(CASE WHEN report.variance > 0 THEN report.variance END), 0)::numeric AS total_savings,
            COALESCE(SUM(CASE WHEN report.variance < 0 THEN report.variance END), 0)::numeric AS total_overpay,
            COALESCE(SUM(report.variance), 0)::numeric                        AS net_variance
        FROM public.carriers_savings_results_report report
        JOIN customer_team ct ON TRIM(report.customer_name) = ct.customer_name
        WHERE {' AND '.join(where_parts)}
        GROUP BY ct.team_id
        ORDER BY
            CASE WHEN ct.team_id = 'TEAM-DFW' THEN 2 ELSE 1 END,
            ct.team_id
        """,
        *params,
    )
    return {
        "success": True,
        "data": [
            {
                "division": r["division"],
                "team_id": r["team_id"],
                "loads": float(r["loads"] or 0),
                "total_savings": float(r["total_savings"] or 0),
                "total_overpay": float(r["total_overpay"] or 0),
                "net_variance": float(r["net_variance"] or 0),
            }
            for r in rows
        ],
        "meta": {"month_date": target_month.isoformat() if target_month else None},
    }


@router.get("/monthly-totals")
async def monthly_totals(
    request: Request,
    customer_id: Optional[str] = Query(None),
    division: Optional[str] = Query(None),
    team: Optional[str] = Query(None),
    origin: Optional[str] = Query(None, description="Origin ILIKE substring"),
    dest: Optional[str] = Query(None, description="Destination ILIKE substring"),
    months_window: int = Query(9, ge=1, le=36, alias="window"),
    _user: dict = Depends(require_tag_role(*SAVINGS_ROLES)),
):
    """Rolling time series for the trend chart. Ignores the month picker.

    Returns one row per month for the N most-recent months with data
    (default 9). Respects division/team/customer filters.
    """
    pool = get_savings_pool(request)

    where_parts = ["report.month_date IN (SELECT month_date FROM recent_months)"]
    params: list = []

    if customer_id:
        params.append(customer_id)
        where_parts.append(f"report.customer_id = ${len(params)}")

    where_parts.extend(_collect_lane_filters(params, origin, dest))

    team_ids = _resolve_team_filter(division, team)
    team_cte, join_sql, where_extra, extra_params = _build_team_clauses(
        team_ids, next_param_index=len(params) + 1
    )
    params.extend(extra_params)
    if where_extra:
        where_parts.append(where_extra.lstrip().removeprefix("AND ").strip())

    params.append(months_window)
    window_placeholder = f"${len(params)}"

    # Compose CTEs: recent_months is always needed; customer_team only when a
    # team filter is active.
    cte_bodies: list[str] = []
    if team_cte:
        cte_bodies.append(team_cte.removeprefix("WITH").strip())
    # Exclude future months so the chart never extends past the current calendar
    # month even when the source table has pre-seeded rows for upcoming months.
    cte_bodies.append(
        f"""recent_months AS (
            SELECT DISTINCT month_date
            FROM public.carriers_savings_results_report
            WHERE month_date IS NOT NULL
              AND month_date <= date_trunc('month', CURRENT_DATE)::date
            ORDER BY month_date DESC
            LIMIT {window_placeholder}
        )"""
    )
    full_cte = "WITH " + ",\n".join(cte_bodies)

    rows = await pool.fetch(
        f"""
        {full_cte}
        SELECT
            report.month_date::text                                           AS month_date,
            COALESCE(SUM(report.number_monthly_loads), 0)::numeric            AS volume,
            COALESCE(SUM(CASE WHEN report.variance > 0 THEN report.variance END), 0)::numeric AS total_savings,
            COALESCE(SUM(CASE WHEN report.variance < 0 THEN report.variance END), 0)::numeric AS total_overpay,
            COALESCE(SUM(report.variance), 0)::numeric                        AS net_variance
        FROM public.carriers_savings_results_report report
        {join_sql}
        WHERE {' AND '.join(where_parts)}
        GROUP BY report.month_date
        ORDER BY report.month_date ASC
        """,
        *params,
    )
    return {
        "success": True,
        "data": [
            {
                "month_date": r["month_date"],
                "volume": float(r["volume"] or 0),
                "total_savings": float(r["total_savings"] or 0),
                "total_overpay": float(r["total_overpay"] or 0),
                "net_variance": float(r["net_variance"] or 0),
            }
            for r in rows
        ],
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


# ============================================================================
# Lane market rates  (SONAR + 123LoadBoard, monthly historical benchmarks)
# ============================================================================

# SONAR is hard-capped at 100 req/min globally. We bound parallelism well below
# that since each call also costs a 123LB request.
_RATE_FETCH_CONCURRENCY = 8


@router.get("/lane-rates")
async def lane_rates(
    request: Request,
    month: Optional[date] = Query(None, description="YYYY-MM-01"),
    customer_id: Optional[str] = Query(None),
    origin: Optional[str] = Query(None),
    dest: Optional[str] = Query(None),
    division: Optional[str] = Query(None),
    team: Optional[str] = Query(None),
    sort: str = Query("variance_desc"),
    page: int = Query(1, ge=1),
    limit: int = Query(100, ge=1, le=500),
    equipment: str = Query("VAN"),
    _user: dict = Depends(require_tag_role(*SAVINGS_ROLES)),
):
    """Return SONAR + 123LB monthly benchmark rates for the same lanes /lanes returns.

    Mirrors /lanes filters/sort/paging exactly so the frontend can join row-for-row
    by `customer_id|origin_name|dest_name`. Per lane we look up the cache; on miss
    we call the provider once for that lane and persist all months in one shot
    (a single API call returns ~24 months — closing future months for free).
    """
    pool = get_savings_pool(request)
    target_month = await _resolve_month(pool, month)
    if not target_month:
        return {"success": True, "data": {}, "meta": {"month_date": None}}

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
        where_parts.append(where_extra.lstrip().removeprefix("AND ").strip())

    params_with_paging = params + [limit, offset]

    rows = await pool.fetch(
        f"""
        {cte}
        SELECT report.customer_id, report.origin_name, report.dest_name
        FROM public.carriers_savings_results_report report
        {join_sql}
        WHERE {' AND '.join(where_parts)}
        ORDER BY {sort_sql}
        LIMIT ${len(params) + 1} OFFSET ${len(params) + 2}
        """,
        *params_with_paging,
    )

    year_month = f"{target_month.year:04d}-{target_month.month:02d}"
    equipment = (equipment or "VAN").upper()

    # Build the parsed-Lane list, dropping cross-border / unparseable lanes.
    parsed: list[tuple[dict, Optional[Lane]]] = []
    seen: set[tuple[str, str, str, str, str]] = set()
    unique_lanes: list[Lane] = []
    for r in rows:
        ln = make_lane(r["origin_name"] or "", r["dest_name"] or "", equipment)
        parsed.append(({"customer_id": r["customer_id"],
                        "origin_name": r["origin_name"],
                        "dest_name": r["dest_name"]}, ln))
        if ln and ln.is_us:
            key = (ln.origin_city, ln.origin_state, ln.dest_city, ln.dest_state, ln.equipment)
            if key not in seen:
                seen.add(key)
                unique_lanes.append(ln)

    # 1) Bulk cache lookup for both providers, just for this month.
    cached_sonar = await get_cached_rates(pool, unique_lanes, [year_month], "sonar")
    cached_lb123 = await get_cached_rates(pool, unique_lanes, [year_month], "lb123")

    def _key_for(ln: Lane) -> tuple:
        return (ln.origin_city, ln.origin_state, ln.dest_city, ln.dest_state, ln.equipment, year_month)

    missing_sonar = [ln for ln in unique_lanes if _key_for(ln) not in cached_sonar]
    missing_lb123 = [ln for ln in unique_lanes if _key_for(ln) not in cached_lb123]

    sem = asyncio.Semaphore(_RATE_FETCH_CONCURRENCY)

    async def _fill_sonar(client: httpx.AsyncClient, ln: Lane) -> None:
        async with sem:
            history = await fetch_sonar_history(client, ln, months=24)
            if history:
                try:
                    await upsert_rates(pool, ln, "sonar", history)
                except Exception as exc:
                    _logger.warning("[SONAR] upsert failed %s→%s: %s",
                                    ln.origin_city, ln.dest_city, exc)
            for m in history:
                if m.year_month == year_month:
                    cached_sonar[_key_for(ln)] = m
                    break

    async def _fill_lb123(client: httpx.AsyncClient, ln: Lane) -> None:
        async with sem:
            history = await fetch_lb123_history(client, ln, months=12)
            if history:
                try:
                    await upsert_rates(pool, ln, "lb123", history)
                except Exception as exc:
                    _logger.warning("[123LB] upsert failed %s→%s: %s",
                                    ln.origin_city, ln.dest_city, exc)
            for m in history:
                if m.year_month == year_month:
                    cached_lb123[_key_for(ln)] = m
                    break

    if missing_sonar or missing_lb123:
        async with httpx.AsyncClient() as client:
            await asyncio.gather(
                *(_fill_sonar(client, ln) for ln in missing_sonar),
                *(_fill_lb123(client, ln) for ln in missing_lb123),
                return_exceptions=True,
            )

    # Build the response, keyed how the frontend keys lane rows.
    out: dict[str, dict] = {}
    for r, ln in parsed:
        row_key = f"{r['customer_id']}|{r['origin_name']}|{r['dest_name']}"
        if not ln or not ln.is_us:
            out[row_key] = {
                "sonar": None, "lb123": None, "skip_reason": "non-us"
                if (ln and not ln.is_us) else "unparseable",
            }
            continue
        s = cached_sonar.get(_key_for(ln))
        l = cached_lb123.get(_key_for(ln))
        out[row_key] = {
            "sonar": _serialize_rate(s),
            "lb123": _serialize_rate(l),
        }
    return {
        "success": True,
        "data": out,
        "meta": {
            "month_date": target_month.isoformat(),
            "year_month": year_month,
            "lanes_in_page": len(parsed),
            "us_lanes": len(unique_lanes),
        },
    }


def _serialize_rate(m) -> Optional[dict]:
    if m is None:
        return None
    return {
        "avg_rate": m.avg_rate,
        "min_rate": m.min_rate,
        "max_rate": m.max_rate,
        "avg_rpm": m.avg_rpm,
        "min_rpm": m.min_rpm,
        "max_rpm": m.max_rpm,
        "loads_included": m.loads_included,
        "mileage": m.mileage,
    }
