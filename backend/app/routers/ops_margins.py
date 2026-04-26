"""Code-made report: OPs Margins — best/worst margin lanes & customers.

Mirrors Bruno's Qlik app `6cca7e6f-97c6-4623-9eeb-5ff6380c6263` (BRUNO --
Margins) as a portal-native report. Like Top Losses Lanes this report reads
the v4 budget table, but it surfaces BOTH positive- and negative-margin
views and adds a richer cascading filter bar (Date / Division / Team /
Customer / Company / Origin / Destination).

Scope (verbatim from PDF + project conventions):
- team_id     IN (TEAM1..TEAM5, TEAM-DFW)        — DFW sub-team via v4.team
- company_id  IN (TMS, TMS3)                     — both included by default
- status      IN (D, P)
- customer_name NOT LIKE '%UNILINK%'             (PDF)
- customer_name NOT LIKE '%OILTEX%'              (project-wide)

Performance notes:
- Padded-variants pattern keeps team_id/company_id/status sargable. Never
  TRIM() those columns inside WHERE/JOIN.
- The ``mcleod_gld_movement`` LEFT JOIN (for Carrier Name) is only used by
  the "Negative Loads by Order" panel — every other panel reads v4 alone.
  Bruno's original query had ``AND d.sequence=1`` in the WHERE clause which
  silently turns the LEFT JOIN into an INNER JOIN, dropping every order
  outside the movement table's 45-day retention window. We move that
  predicate into the ON clause so older rows stay.
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, Query, Request

from app.datalake import pad_variants as _pad_variants
from app.routers.deps import get_datalake_gold_pool, require_tag_role

OPS_ROLES = ("CEO", "Executive", "CORP", "DFW", "Operations", "Finance")

YEAR_START = date(2026, 1, 1)
YEAR_END = date(2026, 12, 31)

CORP_TEAMS = ("TEAM1", "TEAM2", "TEAM3", "TEAM4", "TEAM5")
DFW_TEAM = "TEAM-DFW"
ALL_TEAMS = (*CORP_TEAMS, DFW_TEAM)
DFW_SUB_TEAMS = ("TM1", "TM2", "TM3", "TM4")

ALL_COMPANIES = ("TMS", "TMS3")
OPEN_STATUSES = ("D", "P")

router = APIRouter(tags=["ops-margins"], prefix="/custom/ops-margins")


# ---------------------------------------------------------------------------
# Date / param helpers
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
    today = date.today()
    today_clamped = max(YEAR_START, min(YEAR_END, today))
    m_start, _m_end, lm_start, lm_end = _month_bounds(today)
    if rng == "last_month":
        return _clamp(lm_start, YEAR_START), _clamp(lm_end, YEAR_END)
    if rng in ("ytd", "this_year"):
        return YEAR_START, today_clamped
    if rng == "custom":
        s = _clamp(start_date, YEAR_START)
        e = _clamp(end_date, YEAR_END)
        if e < s:
            s, e = e, s
        return s, e
    return _clamp(m_start, YEAR_START), today_clamped


def _parse_csv(raw: Optional[str], allowed: tuple[str, ...]) -> list[str]:
    if not raw:
        return list(allowed)
    wanted = [t.strip() for t in raw.split(",") if t.strip()]
    allowed_set = {t for t in allowed}
    keep = [t for t in wanted if t in allowed_set]
    return keep or list(allowed)


def _resolve_division(division: Optional[str]) -> tuple[list[str], bool]:
    """Return (team_ids_to_query, is_dfw_only)."""
    d = (division or "").strip().upper()
    if d == "CORP":
        return list(CORP_TEAMS), False
    if d == "DFW":
        return [DFW_TEAM], True
    return list(ALL_TEAMS), False


def _scope_where(
    alias: str,
    teams: list[str],
    companies: list[str],
    customer: Optional[str],
    origin: Optional[str],
    destination: Optional[str],
    sub_teams: Optional[list[str]],
    params: list,
) -> str:
    """Common WHERE fragment for v4. Appends positional params, returns SQL."""
    params.append(_pad_variants(teams, width=8))
    p_teams = len(params)
    params.append(_pad_variants(companies, width=4))
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
    if origin:
        params.append(origin)
        parts.append(f"{_origin_expr(alias)} = ${len(params)}")
    if destination:
        params.append(destination)
        parts.append(f"{_dest_expr(alias)} = ${len(params)}")
    if sub_teams:
        params.append(sub_teams)
        parts.append(f"TRIM({alias}.team) = ANY(${len(params)})")
    return " AND ".join(parts)


def _lane_expr(alias: str) -> str:
    return (
        f"NULLIF(TRIM({alias}.origin_city_name),'') || ',' || "
        f"NULLIF(TRIM({alias}.origin_state_id),'') || ',' || "
        f"NULLIF(TRIM({alias}.dest_city_name),'')   || ',' || "
        f"NULLIF(TRIM({alias}.dest_state_id),'')"
    )


def _origin_expr(alias: str) -> str:
    return (
        f"NULLIF(TRIM({alias}.origin_city_name),'') || ',' || "
        f"NULLIF(TRIM({alias}.origin_state_id),'')"
    )


def _dest_expr(alias: str) -> str:
    return (
        f"NULLIF(TRIM({alias}.dest_city_name),'') || ',' || "
        f"NULLIF(TRIM({alias}.dest_state_id),'')"
    )


def _clamp_threshold(value: float, default: float) -> float:
    try:
        v = float(value)
    except (TypeError, ValueError):
        return default
    if v != v or v < 0 or v > 1:
        return default
    return v


# ---------------------------------------------------------------------------
# Filters — single round-trip cascading payload
# ---------------------------------------------------------------------------


@router.get("/filters")
async def filters(
    request: Request,
    division: Optional[str] = Query(None),
    teams: Optional[str] = Query(None),
    companies: Optional[str] = Query(None),
    customer: Optional[str] = Query(None),
    origin: Optional[str] = Query(None),
    destination: Optional[str] = Query(None),
    sub_teams: Optional[str] = Query(None),
    _user: dict = Depends(require_tag_role(*OPS_ROLES)),
):
    """Cascading filter options.

    Returns customers, origins, destinations and DFW sub-teams visible
    inside the current scope so the UI can render dropdowns without making
    three more round-trips.
    """
    pool = get_datalake_gold_pool(request)

    division_teams, is_dfw = _resolve_division(division)
    requested_teams = _parse_csv(teams, ALL_TEAMS) if teams else None
    team_list = (
        [t for t in requested_teams if t in division_teams]
        if requested_teams is not None
        else division_teams
    )
    if not team_list:
        team_list = division_teams
    company_list = _parse_csv(companies, ALL_COMPANIES)
    sub_team_list = (
        _parse_csv(sub_teams, DFW_SUB_TEAMS)
        if (is_dfw and sub_teams)
        else None
    )

    # Customer list — full year (cheap, ILIKE-friendly)
    cust_params: list = []
    cust_where = _scope_where(
        "br4", team_list, company_list, None, None, None, sub_team_list, cust_params
    )
    cust_params.append(YEAR_START)
    cust_rows = await pool.fetch(
        f"""
        SELECT DISTINCT TRIM(br4.customer_name) AS customer_name
        FROM public.mcleod_gld_budget_report_v4 br4
        WHERE {cust_where}
          AND br4.origin_actual_departure >= ${len(cust_params)}
          AND br4.customer_name IS NOT NULL
          AND TRIM(br4.customer_name) <> ''
        ORDER BY customer_name
        """,
        *cust_params,
    )
    customers = [r["customer_name"] for r in cust_rows if r["customer_name"]]

    # Origins / destinations — narrow to the (optional) selected customer so
    # the lists shrink as the user picks. Dest list also narrows by origin.
    origin_params: list = []
    origin_where = _scope_where(
        "br4", team_list, company_list, customer, None, None, sub_team_list,
        origin_params,
    )
    origin_params.append(YEAR_START)
    origin_rows = await pool.fetch(
        f"""
        SELECT DISTINCT {_origin_expr("br4")} AS origin
        FROM public.mcleod_gld_budget_report_v4 br4
        WHERE {origin_where}
          AND br4.origin_actual_departure >= ${len(origin_params)}
          AND br4.origin_city_name IS NOT NULL
        ORDER BY origin
        """,
        *origin_params,
    )
    origins = [r["origin"] for r in origin_rows if r["origin"]]

    dest_params: list = []
    dest_where = _scope_where(
        "br4", team_list, company_list, customer, origin, None, sub_team_list,
        dest_params,
    )
    dest_params.append(YEAR_START)
    dest_rows = await pool.fetch(
        f"""
        SELECT DISTINCT {_dest_expr("br4")} AS destination
        FROM public.mcleod_gld_budget_report_v4 br4
        WHERE {dest_where}
          AND br4.origin_actual_departure >= ${len(dest_params)}
          AND br4.dest_city_name IS NOT NULL
        ORDER BY destination
        """,
        *dest_params,
    )
    destinations = [r["destination"] for r in dest_rows if r["destination"]]

    return {
        "success": True,
        "data": {
            "divisions": ["All", "CORP", "DFW"],
            "teams": list(ALL_TEAMS),
            "corp_teams": list(CORP_TEAMS),
            "dfw_team": DFW_TEAM,
            "dfw_sub_teams": list(DFW_SUB_TEAMS),
            "companies": list(ALL_COMPANIES),
            "customers": customers,
            "origins": origins,
            "destinations": destinations,
            "year_start": YEAR_START.isoformat(),
            "year_end": YEAR_END.isoformat(),
        },
    }


# ---------------------------------------------------------------------------
# Internal helper to bind the standard OPs-Margins filter bar
# ---------------------------------------------------------------------------


def _bind_scope(
    range_: Optional[str],
    start_date: Optional[date],
    end_date: Optional[date],
    division: Optional[str],
    teams_csv: Optional[str],
    companies_csv: Optional[str],
    sub_teams_csv: Optional[str],
    customer: Optional[str],
    origin: Optional[str],
    destination: Optional[str],
    params: list,
) -> tuple[str, date, date, list[str], list[str], list[str] | None]:
    """Push the standard scope WHERE + date predicate onto params.

    Returns (where_with_date, start, end, team_list, company_list,
    sub_team_list).
    """
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
    company_list = _parse_csv(companies_csv, ALL_COMPANIES)
    sub_team_list = (
        _parse_csv(sub_teams_csv, DFW_SUB_TEAMS) if (is_dfw and sub_teams_csv) else None
    )
    where = _scope_where(
        "br4", team_list, company_list, customer, origin, destination,
        sub_team_list, params,
    )
    params.extend([s, e])
    where_with_date = (
        f"{where} AND br4.origin_actual_departure::date "
        f"BETWEEN ${len(params) - 1} AND ${len(params)}"
    )
    return where_with_date, s, e, team_list, company_list, sub_team_list


# ---------------------------------------------------------------------------
# KPI summary — Margin %, Loads, Loss Loads
# ---------------------------------------------------------------------------


@router.get("/summary")
async def summary(
    request: Request,
    range: Optional[str] = Query("mtd"),
    start_date: Optional[date] = Query(None),
    end_date: Optional[date] = Query(None),
    division: Optional[str] = Query(None),
    teams: Optional[str] = Query(None),
    companies: Optional[str] = Query(None),
    sub_teams: Optional[str] = Query(None),
    customer: Optional[str] = Query(None),
    origin: Optional[str] = Query(None),
    destination: Optional[str] = Query(None),
    _user: dict = Depends(require_tag_role(*OPS_ROLES)),
):
    pool = get_datalake_gold_pool(request)
    params: list = []
    where, s, e, team_list, company_list, sub_team_list = _bind_scope(
        range, start_date, end_date, division, teams, companies, sub_teams,
        customer, origin, destination, params,
    )

    row = await pool.fetchrow(
        f"""
        SELECT
          COUNT(*) FILTER (WHERE br4.total_charge <> 0) AS loads,
          COUNT(*) FILTER (
            WHERE br4.total_charge <> 0 AND br4.margin_amt < 0
          ) AS loss_loads,
          COALESCE(SUM(br4.total_charge) FILTER (
            WHERE br4.total_charge <> 0
          ), 0)::numeric AS revenue,
          COALESCE(SUM(br4.margin_amt) FILTER (
            WHERE br4.total_charge <> 0
          ), 0)::numeric AS profit,
          COALESCE(SUM(br4.total_charge) FILTER (
            WHERE br4.total_charge <> 0 AND br4.margin_amt < 0
          ), 0)::numeric AS loss_revenue,
          COALESCE(SUM(br4.margin_amt) FILTER (
            WHERE br4.total_charge <> 0 AND br4.margin_amt < 0
          ), 0)::numeric AS loss_profit
        FROM public.mcleod_gld_budget_report_v4 br4
        WHERE {where}
        """,
        *params,
    )

    loads = int(row["loads"] or 0)
    loss_loads = int(row["loss_loads"] or 0)
    revenue = float(row["revenue"] or 0)
    profit = float(row["profit"] or 0)
    loss_revenue = float(row["loss_revenue"] or 0)
    loss_profit = float(row["loss_profit"] or 0)
    margin_pct = (profit / revenue * 100.0) if revenue else None
    loss_margin_pct = (loss_profit / loss_revenue * 100.0) if loss_revenue else None

    return {
        "success": True,
        "data": {
            "loads": loads,
            "loss_loads": loss_loads,
            "revenue": revenue,
            "profit": profit,
            "loss_revenue": loss_revenue,
            "loss_profit": loss_profit,
            "margin_pct": margin_pct,
            "loss_margin_pct": loss_margin_pct,
            "window": {"start": s.isoformat(), "end": e.isoformat()},
            "teams_applied": team_list,
            "companies_applied": company_list,
            "sub_teams_applied": sub_team_list,
        },
    }


# ---------------------------------------------------------------------------
# Trend — single endpoint, bucket = day | week | month
# ---------------------------------------------------------------------------


@router.get("/trend")
async def trend(
    request: Request,
    bucket: str = Query("day", pattern="^(day|week|month)$"),
    range: Optional[str] = Query("mtd"),
    start_date: Optional[date] = Query(None),
    end_date: Optional[date] = Query(None),
    division: Optional[str] = Query(None),
    teams: Optional[str] = Query(None),
    companies: Optional[str] = Query(None),
    sub_teams: Optional[str] = Query(None),
    customer: Optional[str] = Query(None),
    origin: Optional[str] = Query(None),
    destination: Optional[str] = Query(None),
    _user: dict = Depends(require_tag_role(*OPS_ROLES)),
):
    """Margin %, Loads, Loss Loads bucketed by day / week / month."""
    pool = get_datalake_gold_pool(request)
    params: list = []
    where, _s, _e, _t, _c, _sub = _bind_scope(
        range, start_date, end_date, division, teams, companies, sub_teams,
        customer, origin, destination, params,
    )

    bucket_expr = {
        "day": "br4.origin_actual_departure::date",
        "week": "DATE_TRUNC('week', br4.origin_actual_departure)::date",
        "month": "DATE_TRUNC('month', br4.origin_actual_departure)::date",
    }[bucket]

    rows = await pool.fetch(
        f"""
        SELECT
          {bucket_expr} AS bucket,
          COUNT(*) FILTER (WHERE br4.total_charge <> 0) AS loads,
          COUNT(*) FILTER (
            WHERE br4.total_charge <> 0 AND br4.margin_amt < 0
          ) AS loss_loads,
          COALESCE(SUM(br4.total_charge) FILTER (
            WHERE br4.total_charge <> 0
          ), 0)::numeric AS revenue,
          COALESCE(SUM(br4.margin_amt) FILTER (
            WHERE br4.total_charge <> 0
          ), 0)::numeric AS profit
        FROM public.mcleod_gld_budget_report_v4 br4
        WHERE {where}
        GROUP BY {bucket_expr}
        ORDER BY bucket
        """,
        *params,
    )

    out = []
    for r in rows:
        rev = float(r["revenue"] or 0)
        prof = float(r["profit"] or 0)
        out.append(
            {
                "bucket": r["bucket"].isoformat() if r["bucket"] else None,
                "loads": int(r["loads"] or 0),
                "loss_loads": int(r["loss_loads"] or 0),
                "revenue": rev,
                "profit": prof,
                "margin_pct": (prof / rev * 100.0) if rev else None,
            }
        )
    return {"success": True, "data": out, "meta": {"bucket": bucket}}


# ---------------------------------------------------------------------------
# Margin by Customer — best customers first (ALL loads)
# ---------------------------------------------------------------------------


@router.get("/customers-margin")
async def customers_margin(
    request: Request,
    range: Optional[str] = Query("mtd"),
    start_date: Optional[date] = Query(None),
    end_date: Optional[date] = Query(None),
    division: Optional[str] = Query(None),
    teams: Optional[str] = Query(None),
    companies: Optional[str] = Query(None),
    sub_teams: Optional[str] = Query(None),
    customer: Optional[str] = Query(None),
    origin: Optional[str] = Query(None),
    destination: Optional[str] = Query(None),
    sort: str = Query("margin_desc"),
    page: int = Query(1, ge=1),
    limit: int = Query(100, ge=1, le=500),
    _user: dict = Depends(require_tag_role(*OPS_ROLES)),
):
    """Customer · # Lanes · Loads · Margin % (sorted by best margin first).

    Tie-break: Margin DESC, Loads DESC, Customer ASC. Includes a 12-week
    margin sparkline per customer (all loads, not just losses) so the table
    can show a tiny trend line inline.
    """
    pool = get_datalake_gold_pool(request)
    params: list = []
    where, s, e, _t, _c, _sub = _bind_scope(
        range, start_date, end_date, division, teams, companies, sub_teams,
        customer, origin, destination, params,
    )
    offset = (page - 1) * limit

    order_by = {
        "margin_desc": "margin_pct DESC NULLS LAST, loads DESC, customer ASC",
        "margin_asc":  "margin_pct ASC NULLS LAST, loads DESC, customer ASC",
        "loads_desc":  "loads DESC, margin_pct DESC NULLS LAST, customer ASC",
        "loads_asc":   "loads ASC, margin_pct DESC NULLS LAST, customer ASC",
        "lanes_desc":  "lane_count DESC, margin_pct DESC NULLS LAST, customer ASC",
        "lanes_asc":   "lane_count ASC, margin_pct DESC NULLS LAST, customer ASC",
    }.get(sort, "margin_pct DESC NULLS LAST, loads DESC, customer ASC")

    params.extend([limit, offset])
    lim_p, off_p = len(params) - 1, len(params)

    rows = await pool.fetch(
        f"""
        SELECT
          TRIM(br4.customer_name) AS customer,
          COUNT(DISTINCT {_lane_expr("br4")}) AS lane_count,
          COUNT(*) FILTER (WHERE br4.total_charge <> 0) AS loads,
          COALESCE(SUM(br4.total_charge) FILTER (
            WHERE br4.total_charge <> 0
          ), 0)::numeric AS revenue,
          COALESCE(SUM(br4.margin_amt) FILTER (
            WHERE br4.total_charge <> 0
          ), 0)::numeric AS profit,
          CASE WHEN SUM(br4.total_charge) FILTER (
                 WHERE br4.total_charge <> 0
               ) <> 0
            THEN SUM(br4.margin_amt) FILTER (
                   WHERE br4.total_charge <> 0
                 )::numeric
              / SUM(br4.total_charge) FILTER (
                   WHERE br4.total_charge <> 0
                 )::numeric
            ELSE NULL END AS margin_pct,
          COUNT(*) OVER() AS total_count
        FROM public.mcleod_gld_budget_report_v4 br4
        WHERE {where}
          AND br4.customer_name IS NOT NULL
          AND TRIM(br4.customer_name) <> ''
        GROUP BY TRIM(br4.customer_name)
        ORDER BY {order_by}
        LIMIT ${lim_p} OFFSET ${off_p}
        """,
        *params,
    )

    total = int(rows[0]["total_count"]) if rows else 0
    data = [
        {
            "customer": r["customer"],
            "lane_count": int(r["lane_count"] or 0),
            "loads": int(r["loads"] or 0),
            "revenue": float(r["revenue"] or 0),
            "profit": float(r["profit"] or 0),
            "margin_pct": (
                float(r["margin_pct"]) * 100.0 if r["margin_pct"] is not None else None
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
# Margin by Lane — best lanes first (ALL loads)
# ---------------------------------------------------------------------------


@router.get("/lanes-margin")
async def lanes_margin(
    request: Request,
    range: Optional[str] = Query("mtd"),
    start_date: Optional[date] = Query(None),
    end_date: Optional[date] = Query(None),
    division: Optional[str] = Query(None),
    teams: Optional[str] = Query(None),
    companies: Optional[str] = Query(None),
    sub_teams: Optional[str] = Query(None),
    customer: Optional[str] = Query(None),
    origin: Optional[str] = Query(None),
    destination: Optional[str] = Query(None),
    sort: str = Query("margin_desc"),
    page: int = Query(1, ge=1),
    limit: int = Query(100, ge=1, le=500),
    _user: dict = Depends(require_tag_role(*OPS_ROLES)),
):
    """Customer · Origin · Destination · Margin % (best lanes first)."""
    pool = get_datalake_gold_pool(request)
    params: list = []
    where, _s, _e, _t, _c, _sub = _bind_scope(
        range, start_date, end_date, division, teams, companies, sub_teams,
        customer, origin, destination, params,
    )
    offset = (page - 1) * limit

    order_by = {
        "margin_desc": "margin_pct DESC NULLS LAST, loads DESC, customer ASC",
        "margin_asc":  "margin_pct ASC NULLS LAST, loads DESC, customer ASC",
        "loads_desc":  "loads DESC, margin_pct DESC NULLS LAST, customer ASC",
        "loads_asc":   "loads ASC, margin_pct DESC NULLS LAST, customer ASC",
        "profit_desc": "profit DESC NULLS LAST, customer ASC",
        "profit_asc":  "profit ASC NULLS LAST, customer ASC",
    }.get(sort, "margin_pct DESC NULLS LAST, loads DESC, customer ASC")

    params.extend([limit, offset])
    lim_p, off_p = len(params) - 1, len(params)

    rows = await pool.fetch(
        f"""
        SELECT
          TRIM(br4.customer_name) AS customer,
          {_origin_expr("br4")}    AS origin,
          {_dest_expr("br4")}      AS destination,
          COUNT(*) FILTER (WHERE br4.total_charge <> 0) AS loads,
          COALESCE(SUM(br4.total_charge) FILTER (
            WHERE br4.total_charge <> 0
          ), 0)::numeric AS revenue,
          COALESCE(SUM(br4.margin_amt) FILTER (
            WHERE br4.total_charge <> 0
          ), 0)::numeric AS profit,
          CASE WHEN SUM(br4.total_charge) FILTER (
                 WHERE br4.total_charge <> 0
               ) <> 0
            THEN SUM(br4.margin_amt) FILTER (
                   WHERE br4.total_charge <> 0
                 )::numeric
              / SUM(br4.total_charge) FILTER (
                   WHERE br4.total_charge <> 0
                 )::numeric
            ELSE NULL END AS margin_pct,
          COUNT(*) OVER() AS total_count
        FROM public.mcleod_gld_budget_report_v4 br4
        WHERE {where}
          AND br4.customer_name IS NOT NULL
          AND TRIM(br4.customer_name) <> ''
        GROUP BY
          TRIM(br4.customer_name), {_origin_expr("br4")}, {_dest_expr("br4")}
        ORDER BY {order_by}
        LIMIT ${lim_p} OFFSET ${off_p}
        """,
        *params,
    )

    total = int(rows[0]["total_count"]) if rows else 0
    data = [
        {
            "customer": r["customer"],
            "origin": r["origin"],
            "destination": r["destination"],
            "loads": int(r["loads"] or 0),
            "revenue": float(r["revenue"] or 0),
            "profit": float(r["profit"] or 0),
            "margin_pct": (
                float(r["margin_pct"]) * 100.0 if r["margin_pct"] is not None else None
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
# Worst Margins by Lane — losses only with 15/18/20% target gaps
# ---------------------------------------------------------------------------


@router.get("/by-lane")
async def by_lane(
    request: Request,
    range: Optional[str] = Query("mtd"),
    start_date: Optional[date] = Query(None),
    end_date: Optional[date] = Query(None),
    division: Optional[str] = Query(None),
    teams: Optional[str] = Query(None),
    companies: Optional[str] = Query(None),
    sub_teams: Optional[str] = Query(None),
    customer: Optional[str] = Query(None),
    origin: Optional[str] = Query(None),
    destination: Optional[str] = Query(None),
    sort: str = Query("profit_asc"),
    page: int = Query(1, ge=1),
    limit: int = Query(100, ge=1, le=500),
    threshold_1: float = Query(0.15, ge=0.0, le=1.0),
    threshold_2: float = Query(0.18, ge=0.0, le=1.0),
    threshold_3: float = Query(0.20, ge=0.0, le=1.0),
    _user: dict = Depends(require_tag_role(*OPS_ROLES)),
):
    """Worst-lane leak (margin_amt < 0) with target-gap columns."""
    pool = get_datalake_gold_pool(request)
    params: list = []
    where, _s, _e, _t, _c, _sub = _bind_scope(
        range, start_date, end_date, division, teams, companies, sub_teams,
        customer, origin, destination, params,
    )
    offset = (page - 1) * limit
    t1 = _clamp_threshold(threshold_1, 0.15)
    t2 = _clamp_threshold(threshold_2, 0.18)
    t3 = _clamp_threshold(threshold_3, 0.20)

    order_by = {
        "profit_asc":   "profit ASC",
        "profit_desc":  "profit DESC",
        "revenue_desc": "revenue DESC NULLS LAST",
        "revenue_asc":  "revenue ASC NULLS LAST",
        "margin_asc":   "margin_pct ASC NULLS LAST",
        "margin_desc":  "margin_pct DESC NULLS LAST",
        "loads_desc":   "loads DESC",
    }.get(sort, "profit ASC")

    params.extend([t1, t2, t3])
    pt1, pt2, pt3 = len(params) - 2, len(params) - 1, len(params)
    params.extend([limit, offset])
    lim_p, off_p = len(params) - 1, len(params)

    rows = await pool.fetch(
        f"""
        WITH base AS (
          SELECT
            TRIM(br4.customer_name) AS customer,
            {_origin_expr("br4")}   AS origin,
            {_dest_expr("br4")}     AS destination,
            br4.total_charge,
            br4.margin_amt
          FROM public.mcleod_gld_budget_report_v4 br4
          WHERE {where}
            AND br4.margin_amt < 0 AND br4.total_charge <> 0
        ),
        agg AS (
          SELECT
            customer, origin, destination,
            COUNT(*)                ::int     AS loads,
            SUM(total_charge)       ::numeric AS revenue,
            SUM(margin_amt)         ::numeric AS profit,
            CASE WHEN SUM(total_charge) <> 0
                 THEN SUM(margin_amt)::numeric / SUM(total_charge)::numeric
                 ELSE NULL END AS margin_pct
          FROM base
          GROUP BY customer, origin, destination
        )
        SELECT
          customer, origin, destination, loads, revenue, profit, margin_pct,
          CASE WHEN margin_pct > ${pt1} THEN 0
               ELSE revenue * ${pt1} END AS profit_1,
          CASE WHEN margin_pct < ${pt1}
               THEN revenue * ${pt1} - profit ELSE 0 END AS diff_1,
          CASE WHEN margin_pct > ${pt2} THEN 0
               ELSE revenue * ${pt2} END AS profit_2,
          CASE WHEN margin_pct < ${pt2}
               THEN revenue * ${pt2} - profit ELSE 0 END AS diff_2,
          CASE WHEN margin_pct > ${pt3} THEN 0
               ELSE revenue * ${pt3} END AS profit_3,
          CASE WHEN margin_pct < ${pt3}
               THEN revenue * ${pt3} - profit ELSE 0 END AS diff_3,
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
            "origin": r["origin"],
            "destination": r["destination"],
            "loads": int(r["loads"] or 0),
            "revenue": float(r["revenue"] or 0),
            "profit": float(r["profit"] or 0),
            "margin_pct": (
                float(r["margin_pct"]) * 100.0 if r["margin_pct"] is not None else None
            ),
            "profit_1": float(r["profit_1"] or 0),
            "diff_1":   float(r["diff_1"] or 0),
            "profit_2": float(r["profit_2"] or 0),
            "diff_2":   float(r["diff_2"] or 0),
            "profit_3": float(r["profit_3"] or 0),
            "diff_3":   float(r["diff_3"] or 0),
        }
        for r in rows
    ]
    return {
        "success": True,
        "data": data,
        "meta": {
            "total": total,
            "page": page,
            "limit": limit,
            "thresholds": [t1, t2, t3],
        },
    }


# ---------------------------------------------------------------------------
# Negative Loads by Order — order-grain detail with carrier name
# ---------------------------------------------------------------------------


@router.get("/negative-orders")
async def negative_orders(
    request: Request,
    range: Optional[str] = Query("mtd"),
    start_date: Optional[date] = Query(None),
    end_date: Optional[date] = Query(None),
    division: Optional[str] = Query(None),
    teams: Optional[str] = Query(None),
    companies: Optional[str] = Query(None),
    sub_teams: Optional[str] = Query(None),
    customer: Optional[str] = Query(None),
    origin: Optional[str] = Query(None),
    destination: Optional[str] = Query(None),
    sort: str = Query("profit_asc"),
    page: int = Query(1, ge=1),
    limit: int = Query(100, ge=1, le=500),
    _user: dict = Depends(require_tag_role(*OPS_ROLES)),
):
    """Order-level rows with margin_amt<0, including Carrier (payee_name).

    Carrier name comes from ``mcleod_gld_movement`` via a pre-filtered CTE
    that the planner can hash-join, instead of a per-row correlated
    subquery (which TRIM-ed both sides and full-scanned movement once per
    base row — caused 504s on the proxy). The ``sequence=1`` predicate
    lives in the CTE filter, never the WHERE of the outer query, so the
    LEFT JOIN stays a true LEFT JOIN — orders older than the movement
    table's 45-day retention window show up with ``carrier=NULL`` instead
    of silently disappearing.
    """
    pool = get_datalake_gold_pool(request)
    params: list = []
    where, _s, _e, _t, company_list, _sub = _bind_scope(
        range, start_date, end_date, division, teams, companies, sub_teams,
        customer, origin, destination, params,
    )
    offset = (page - 1) * limit

    order_by = {
        "profit_asc":   "profit ASC",
        "profit_desc":  "profit DESC",
        "revenue_desc": "revenue DESC NULLS LAST",
        "revenue_asc":  "revenue ASC NULLS LAST",
        "margin_asc":   "margin_pct ASC NULLS LAST",
        "margin_desc":  "margin_pct DESC NULLS LAST",
        "conc_desc":    "concentration DESC",
        "date_desc":    "actual_day DESC NULLS LAST, id DESC",
        "date_asc":     "actual_day ASC NULLS LAST, id ASC",
    }.get(sort, "profit ASC")

    # Pre-filter movement to the same companies in scope so the hash join
    # builds against a much smaller table. ROW_NUMBER picks sequence=1 (the
    # first stop = carrier of record).
    params.append(_pad_variants(company_list, width=4))
    p_mov_companies = len(params)
    params.extend([limit, offset])
    lim_p, off_p = len(params) - 1, len(params)

    rows = await pool.fetch(
        f"""
        WITH mov AS (
          SELECT
            order_id,
            company_id,
            payee_name,
            ROW_NUMBER() OVER (
              PARTITION BY order_id, company_id
              ORDER BY sequence ASC
            ) AS rn
          FROM public.mcleod_gld_movement
          WHERE company_id = ANY(${p_mov_companies})
        ),
        base AS (
          SELECT
            br4.origin_actual_departure::date AS actual_day,
            TRIM(br4.id)            AS id,
            TRIM(br4.customer_name) AS customer,
            COALESCE(TRIM(mov.payee_name), '') AS carrier,
            {_origin_expr("br4")}   AS origin,
            {_dest_expr("br4")}     AS destination,
            br4.total_charge::numeric AS revenue,
            br4.margin_amt::numeric   AS profit,
            CASE WHEN br4.total_charge <> 0
                 THEN br4.margin_amt::numeric / br4.total_charge::numeric
                 ELSE NULL END AS margin_pct
          FROM public.mcleod_gld_budget_report_v4 br4
          LEFT JOIN mov
                 ON mov.order_id   = br4.id
                AND mov.company_id = br4.company_id
                AND mov.rn = 1
          WHERE {where}
            AND br4.margin_amt < 0 AND br4.total_charge <> 0
        ),
        with_total AS (
          SELECT
            *,
            SUM(profit) OVER () AS total_profit,
            COUNT(*)    OVER () AS total_count
          FROM base
        )
        SELECT
          actual_day, id, customer, carrier, origin, destination,
          revenue, profit, margin_pct,
          CASE WHEN total_profit <> 0
               THEN profit / total_profit ELSE NULL END AS concentration,
          total_count
        FROM with_total
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
            "customer": r["customer"],
            "carrier": r["carrier"],
            "origin": r["origin"],
            "destination": r["destination"],
            "revenue": float(r["revenue"] or 0),
            "profit": float(r["profit"] or 0),
            "margin_pct": (
                float(r["margin_pct"]) * 100.0 if r["margin_pct"] is not None else None
            ),
            "concentration": (
                float(r["concentration"]) * 100.0
                if r["concentration"] is not None
                else None
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
# Negative Loads by Customer — customer-grain concentration view
# ---------------------------------------------------------------------------


@router.get("/loss-customers")
async def loss_customers(
    request: Request,
    range: Optional[str] = Query("mtd"),
    start_date: Optional[date] = Query(None),
    end_date: Optional[date] = Query(None),
    division: Optional[str] = Query(None),
    teams: Optional[str] = Query(None),
    companies: Optional[str] = Query(None),
    sub_teams: Optional[str] = Query(None),
    customer: Optional[str] = Query(None),
    origin: Optional[str] = Query(None),
    destination: Optional[str] = Query(None),
    sort: str = Query("profit_asc"),
    page: int = Query(1, ge=1),
    limit: int = Query(100, ge=1, le=500),
    _user: dict = Depends(require_tag_role(*OPS_ROLES)),
):
    """Per-customer aggregate of negative-margin loads with concentration."""
    pool = get_datalake_gold_pool(request)
    params: list = []
    where, _s, _e, _t, _c, _sub = _bind_scope(
        range, start_date, end_date, division, teams, companies, sub_teams,
        customer, origin, destination, params,
    )
    offset = (page - 1) * limit

    order_by = {
        "profit_asc":   "profit ASC",
        "profit_desc":  "profit DESC",
        "revenue_desc": "revenue DESC NULLS LAST",
        "loads_desc":   "loads DESC",
        "loads_asc":    "loads ASC",
        "conc_desc":    "concentration DESC",
        "customer_asc": "customer ASC",
    }.get(sort, "profit ASC")

    params.extend([limit, offset])
    lim_p, off_p = len(params) - 1, len(params)

    rows = await pool.fetch(
        f"""
        WITH base AS (
          SELECT
            TRIM(br4.customer_name) AS customer,
            br4.total_charge,
            br4.margin_amt
          FROM public.mcleod_gld_budget_report_v4 br4
          WHERE {where}
            AND br4.margin_amt < 0 AND br4.total_charge <> 0
            AND br4.customer_name IS NOT NULL
            AND TRIM(br4.customer_name) <> ''
        ),
        agg AS (
          SELECT
            customer,
            COUNT(*)::int             AS loads,
            SUM(total_charge)::numeric AS revenue,
            SUM(margin_amt)::numeric   AS profit
          FROM base
          GROUP BY customer
        ),
        with_total AS (
          SELECT
            *,
            SUM(profit) OVER () AS total_profit,
            COUNT(*)    OVER () AS total_count
          FROM agg
        )
        SELECT
          customer, loads, revenue, profit,
          CASE WHEN total_profit <> 0
               THEN profit / total_profit ELSE NULL END AS concentration,
          total_count
        FROM with_total
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
            "concentration": (
                float(r["concentration"]) * 100.0
                if r["concentration"] is not None
                else None
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
# Losses by Month / Week — combo charts (sticky 8 buckets, losses only)
# ---------------------------------------------------------------------------


@router.get("/losses-by-month")
async def losses_by_month(
    request: Request,
    division: Optional[str] = Query(None),
    teams: Optional[str] = Query(None),
    companies: Optional[str] = Query(None),
    sub_teams: Optional[str] = Query(None),
    customer: Optional[str] = Query(None),
    origin: Optional[str] = Query(None),
    destination: Optional[str] = Query(None),
    months: int = Query(8, ge=3, le=24),
    _user: dict = Depends(require_tag_role(*OPS_ROLES)),
):
    pool = get_datalake_gold_pool(request)
    today = date.today()
    m_start = today.replace(day=1)
    y, m = m_start.year, m_start.month - (months - 1)
    while m <= 0:
        y -= 1
        m += 12
    start = date(y, m, 1)
    end = today

    params: list = []
    where, _s, _e, _t, _c, _sub = _bind_scope(
        "custom", start, end, division, teams, companies, sub_teams,
        customer, origin, destination, params,
    )

    rows = await pool.fetch(
        f"""
        SELECT
          DATE_TRUNC('month', br4.origin_actual_departure)::date AS bucket,
          COUNT(*) FILTER (
            WHERE br4.total_charge <> 0 AND br4.margin_amt < 0
          ) AS loads,
          COALESCE(SUM(br4.margin_amt) FILTER (
            WHERE br4.total_charge <> 0 AND br4.margin_amt < 0
          ), 0)::numeric AS profit
        FROM public.mcleod_gld_budget_report_v4 br4
        WHERE {where}
        GROUP BY DATE_TRUNC('month', br4.origin_actual_departure)::date
        ORDER BY bucket
        """,
        *params,
    )
    return {
        "success": True,
        "data": [
            {
                "bucket": r["bucket"].isoformat() if r["bucket"] else None,
                "loads": int(r["loads"] or 0),
                "profit": float(r["profit"] or 0),
            }
            for r in rows
        ],
    }


@router.get("/losses-by-week")
async def losses_by_week(
    request: Request,
    division: Optional[str] = Query(None),
    teams: Optional[str] = Query(None),
    companies: Optional[str] = Query(None),
    sub_teams: Optional[str] = Query(None),
    customer: Optional[str] = Query(None),
    origin: Optional[str] = Query(None),
    destination: Optional[str] = Query(None),
    weeks: int = Query(8, ge=3, le=52),
    _user: dict = Depends(require_tag_role(*OPS_ROLES)),
):
    pool = get_datalake_gold_pool(request)
    today = date.today()
    monday = today - timedelta(days=today.weekday())
    start = monday - timedelta(weeks=weeks - 1)
    end = monday + timedelta(days=6)

    params: list = []
    where, _s, _e, _t, _c, _sub = _bind_scope(
        "custom", start, end, division, teams, companies, sub_teams,
        customer, origin, destination, params,
    )

    rows = await pool.fetch(
        f"""
        SELECT
          DATE_TRUNC('week', br4.origin_actual_departure)::date AS bucket,
          COUNT(*) FILTER (
            WHERE br4.total_charge <> 0 AND br4.margin_amt < 0
          ) AS loads,
          COALESCE(SUM(br4.margin_amt) FILTER (
            WHERE br4.total_charge <> 0 AND br4.margin_amt < 0
          ), 0)::numeric AS profit
        FROM public.mcleod_gld_budget_report_v4 br4
        WHERE {where}
        GROUP BY DATE_TRUNC('week', br4.origin_actual_departure)::date
        ORDER BY bucket
        """,
        *params,
    )
    return {
        "success": True,
        "data": [
            {
                "bucket": r["bucket"].isoformat() if r["bucket"] else None,
                "loads": int(r["loads"] or 0),
                "profit": float(r["profit"] or 0),
            }
            for r in rows
        ],
    }


# ---------------------------------------------------------------------------
# Margin distribution — histogram of customers per margin bucket
# ---------------------------------------------------------------------------


@router.get("/distribution")
async def distribution(
    request: Request,
    range: Optional[str] = Query("mtd"),
    start_date: Optional[date] = Query(None),
    end_date: Optional[date] = Query(None),
    division: Optional[str] = Query(None),
    teams: Optional[str] = Query(None),
    companies: Optional[str] = Query(None),
    sub_teams: Optional[str] = Query(None),
    customer: Optional[str] = Query(None),
    origin: Optional[str] = Query(None),
    destination: Optional[str] = Query(None),
    _user: dict = Depends(require_tag_role(*OPS_ROLES)),
):
    """Customer count + revenue per margin bucket: <0 / 0-5 / 5-10 / 10-15 / 15-20 / 20+."""
    pool = get_datalake_gold_pool(request)
    params: list = []
    where, _s, _e, _t, _c, _sub = _bind_scope(
        range, start_date, end_date, division, teams, companies, sub_teams,
        customer, origin, destination, params,
    )

    rows = await pool.fetch(
        f"""
        WITH cust AS (
          SELECT
            TRIM(br4.customer_name) AS customer,
            SUM(br4.total_charge) FILTER (
              WHERE br4.total_charge <> 0
            )::numeric AS revenue,
            SUM(br4.margin_amt) FILTER (
              WHERE br4.total_charge <> 0
            )::numeric AS profit
          FROM public.mcleod_gld_budget_report_v4 br4
          WHERE {where}
            AND br4.customer_name IS NOT NULL
            AND TRIM(br4.customer_name) <> ''
          GROUP BY TRIM(br4.customer_name)
        ),
        bucketed AS (
          SELECT
            customer, revenue, profit,
            CASE
              WHEN revenue IS NULL OR revenue = 0 THEN NULL
              ELSE profit / revenue
            END AS margin
          FROM cust
        ),
        labeled AS (
          SELECT
            CASE
              WHEN margin IS NULL    THEN 'no_revenue'
              WHEN margin < 0        THEN 'lt_0'
              WHEN margin < 0.05     THEN '0_5'
              WHEN margin < 0.10     THEN '5_10'
              WHEN margin < 0.15     THEN '10_15'
              WHEN margin < 0.20     THEN '15_20'
              ELSE                        'gte_20'
            END AS bucket,
            customer, revenue, profit
          FROM bucketed
        )
        SELECT
          bucket,
          COUNT(*)::int                     AS customers,
          COALESCE(SUM(revenue),0)::numeric AS revenue,
          COALESCE(SUM(profit), 0)::numeric AS profit
        FROM labeled
        GROUP BY bucket
        ORDER BY CASE bucket
          WHEN 'lt_0'       THEN 0
          WHEN '0_5'        THEN 1
          WHEN '5_10'       THEN 2
          WHEN '10_15'      THEN 3
          WHEN '15_20'      THEN 4
          WHEN 'gte_20'     THEN 5
          ELSE 6 END
        """,
        *params,
    )

    return {
        "success": True,
        "data": [
            {
                "bucket": r["bucket"],
                "customers": int(r["customers"] or 0),
                "revenue": float(r["revenue"] or 0),
                "profit": float(r["profit"] or 0),
            }
            for r in rows
        ],
    }


# ---------------------------------------------------------------------------
# Customer 8-week sparkline — fed inline by Margin by Customer table
# ---------------------------------------------------------------------------


@router.get("/customer-spark")
async def customer_spark(
    request: Request,
    customers: str = Query(..., description="Comma-separated customer names"),
    weeks: int = Query(8, ge=2, le=26),
    division: Optional[str] = Query(None),
    teams: Optional[str] = Query(None),
    companies: Optional[str] = Query(None),
    sub_teams: Optional[str] = Query(None),
    origin: Optional[str] = Query(None),
    destination: Optional[str] = Query(None),
    _user: dict = Depends(require_tag_role(*OPS_ROLES)),
):
    """Per-customer weekly margin % series, last N weeks (default 8).

    Returns a single payload keyed by customer for sparkline rendering.
    Cap the input at 200 customers to keep the IN-list small.
    """
    raw = [c.strip() for c in customers.split(",") if c.strip()]
    cust_list = raw[:200]
    if not cust_list:
        return {"success": True, "data": {}, "meta": {"weeks": weeks}}

    pool = get_datalake_gold_pool(request)
    today = date.today()
    monday = today - timedelta(days=today.weekday())
    start = monday - timedelta(weeks=weeks - 1)
    end = monday + timedelta(days=6)

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
    company_list = _parse_csv(companies, ALL_COMPANIES)
    sub_team_list = (
        _parse_csv(sub_teams, DFW_SUB_TEAMS) if (is_dfw and sub_teams) else None
    )

    where = _scope_where(
        "br4", team_list, company_list, None, origin, destination, sub_team_list,
        params,
    )
    params.extend([start, end])
    p_s, p_e = len(params) - 1, len(params)
    params.append(cust_list)
    p_cust = len(params)

    rows = await pool.fetch(
        f"""
        SELECT
          TRIM(br4.customer_name) AS customer,
          DATE_TRUNC('week', br4.origin_actual_departure)::date AS bucket,
          COALESCE(SUM(br4.total_charge) FILTER (
            WHERE br4.total_charge <> 0
          ), 0)::numeric AS revenue,
          COALESCE(SUM(br4.margin_amt) FILTER (
            WHERE br4.total_charge <> 0
          ), 0)::numeric AS profit
        FROM public.mcleod_gld_budget_report_v4 br4
        WHERE {where}
          AND br4.origin_actual_departure::date BETWEEN ${p_s} AND ${p_e}
          AND TRIM(br4.customer_name) = ANY(${p_cust})
        GROUP BY TRIM(br4.customer_name),
                 DATE_TRUNC('week', br4.origin_actual_departure)::date
        ORDER BY customer, bucket
        """,
        *params,
    )

    out: dict[str, list[dict]] = {c: [] for c in cust_list}
    for r in rows:
        cust = r["customer"]
        rev = float(r["revenue"] or 0)
        prof = float(r["profit"] or 0)
        out.setdefault(cust, []).append(
            {
                "bucket": r["bucket"].isoformat() if r["bucket"] else None,
                "margin_pct": (prof / rev * 100.0) if rev else None,
                "revenue": rev,
                "profit": prof,
            }
        )
    return {"success": True, "data": out, "meta": {"weeks": weeks}}


# ---------------------------------------------------------------------------
# Freshness — last refresh stamp for the source table
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
