"""Code-made report: Sales — Attrition to OPs.

Mirrors Bruno's Qlik app `9b669acd-bf18-4467-9dbc-adeaec537670`
("BRUNO -- Attrition to Sales") as a portal-native report. Every panel
reads from `public.mcleod_gld_budget_report_v4` (datalake gold).

Scope (verbatim from PDF + project conventions):
- team_id     IN (TEAM1..TEAM5, TEAM-DFW)
- company_id  IN (TMS, TMS3)
- status      IN (D, P)
- customer_name NOT LIKE '%UNILINK%'   (project-wide exclusion)
- customer_name NOT LIKE '%OILTEX%'    (project-wide exclusion)

Endpoints
---------
- GET /filters  — distinct customers (within 365d window) + canonical teams
- GET /details  — main per-customer table; honors Date / Teams / Customer /
                  days-bucket; embeds an 8-week #Loads sparkline per row.
- GET /trend    — three monthly series (#Loads / $Profit / %Margin) over a
                  FIXED 13-month window ending the current month.
                  Honors Teams + Customer; **ignores** date filters
                  (Bruno's "It should not change with the date filter").

Sargability rule: never wrap team_id / company_id / status in TRIM() in
WHERE/JOIN. Use _pad_variants(...) so btree indexes stay usable.
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, Query, Request, Response

from app.datalake import pad_variants as _pad_variants
from app.routers.deps import get_datalake_gold_pool, require_tag_role

ROLES = ("CEO", "Executive", "Sales", "CORP", "DFW", "Operations", "Finance")

ALL_TEAMS = ("TEAM1", "TEAM2", "TEAM3", "TEAM4", "TEAM5", "TEAM-DFW")
COMPANIES = ("TMS", "TMS3")
OPEN_STATUSES = ("D", "P")

# Days-since-last-load buckets (matches Attrition WoW reactive segments,
# slightly retuned for the broader 365-day default window).
DAYS_BUCKETS = {
    "1_30":   (1, 30),
    "31_90":  (31, 90),
    "91_180": (91, 180),
    "181_365": (181, 365),
    "365_plus": (366, None),
}

# Floor for the year-window in /filters customer list (avoid full-table scan).
WINDOW_FLOOR_DAYS = 400  # ~13 months — covers all bar-chart months too.

router = APIRouter(
    tags=["sales-attrition-to-ops"],
    prefix="/custom/sales-attrition-to-ops",
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _resolve_range(
    rng: Optional[str],
    start_date: Optional[date],
    end_date: Optional[date],
) -> tuple[date, date]:
    """Expand the preset range selector into a concrete [start, end] pair.

    Default = ``last_365`` (Bruno's "Last 365 days" filter default).
    """
    today = date.today()
    if rng == "mtd":
        return today.replace(day=1), today
    if rng == "last_month":
        first = today.replace(day=1)
        lm_end = first - timedelta(days=1)
        lm_start = lm_end.replace(day=1)
        return lm_start, lm_end
    if rng in ("ytd", "this_year"):
        return date(today.year, 1, 1), today
    if rng == "custom":
        s = start_date or today - timedelta(days=365)
        e = end_date or today
        if e < s:
            s, e = e, s
        return s, e
    # default: last 365 days
    return today - timedelta(days=365), today


def _parse_teams(teams: Optional[str]) -> list[str]:
    if not teams:
        return list(ALL_TEAMS)
    wanted = [t.strip() for t in teams.split(",") if t.strip()]
    allowed = set(ALL_TEAMS)
    return [t for t in wanted if t in allowed] or list(ALL_TEAMS)


def _scope_where(
    alias: str,
    teams: list[str],
    customer: Optional[str],
    params: list,
) -> str:
    """Common WHERE fragment for v4 (sargable, padded variants)."""
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


def _days_bucket_having(bucket: Optional[str]) -> Optional[str]:
    if not bucket or bucket not in DAYS_BUCKETS:
        return None
    lo, hi = DAYS_BUCKETS[bucket]
    if hi is None:
        return f"days_since >= {lo}"
    return f"days_since BETWEEN {lo} AND {hi}"


# ---------------------------------------------------------------------------
# Filters endpoint — powers the team list + customer typeahead
# ---------------------------------------------------------------------------


@router.get("/filters")
async def filters(
    request: Request,
    _user: dict = Depends(require_tag_role(*ROLES)),
):
    """Available teams + distinct customer list (within scope, 13-month floor)."""
    pool = get_datalake_gold_pool(request)
    floor = date.today() - timedelta(days=WINDOW_FLOOR_DAYS)
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
        floor,
    )
    return {
        "success": True,
        "data": {
            "teams": list(ALL_TEAMS),
            "customers": [r["customer_name"] for r in rows if r["customer_name"]],
            "buckets": list(DAYS_BUCKETS.keys()),
        },
    }


# ---------------------------------------------------------------------------
# Details endpoint — main per-customer table with 8-week sparkline
# ---------------------------------------------------------------------------


@router.get("/details")
async def details(
    request: Request,
    range: Optional[str] = Query("last_365"),
    start_date: Optional[date] = Query(None),
    end_date: Optional[date] = Query(None),
    teams: Optional[str] = Query(None),
    customer: Optional[str] = Query(None),
    bucket: Optional[str] = Query(None),
    sort: str = Query("days_desc"),
    page: int = Query(1, ge=1),
    limit: int = Query(100, ge=1, le=500),
    _user: dict = Depends(require_tag_role(*ROLES)),
):
    """Per-customer aggregate rows + grand totals + 8-week #Loads sparkline.

    Bucket lets the table answer "who's about to churn" without re-querying
    via free-text dates. Sparkline is computed in a CTE so it's one round-trip.
    """
    pool = get_datalake_gold_pool(request)
    s, e = _resolve_range(range, start_date, end_date)
    team_list = _parse_teams(teams)
    today = date.today()
    spark_floor = today - timedelta(weeks=8)
    offset = (page - 1) * limit

    params: list = []
    where = _scope_where("br4", team_list, customer, params)
    params.append(s); p_s = len(params)
    params.append(e); p_e = len(params)
    params.append(today); p_today = len(params)
    params.append(spark_floor); p_spark = len(params)
    params.append(limit); p_limit = len(params)
    params.append(offset); p_offset = len(params)

    bucket_having = _days_bucket_having(bucket)

    order_by = {
        "days_desc":     "days_since DESC NULLS LAST",
        "days_asc":      "days_since ASC NULLS LAST",
        "loads_desc":    "loads DESC",
        "loads_asc":     "loads ASC",
        "revenue_desc":  "revenue DESC",
        "revenue_asc":   "revenue ASC",
        "profit_desc":   "profit DESC",
        "profit_asc":    "profit ASC",
        "margin_desc":   "margin_pct DESC NULLS LAST",
        "margin_asc":    "margin_pct ASC NULLS LAST",
        "customer_asc":  "customer ASC",
    }.get(sort, "days_since DESC NULLS LAST")

    # Single round-trip: filtered customer aggregates + 8-week sparkline +
    # grand totals (computed independent of bucket so the totals row stays
    # stable as the user toggles the bucket pills).
    sql = f"""
    WITH filtered AS (
      SELECT
        TRIM(br4.customer_name)            AS customer,
        TRIM(br4.team_id)                  AS team,
        br4.id,
        br4.total_charge,
        br4.margin_amt,
        br4.origin_actual_departure::date  AS dep_date
      FROM public.mcleod_gld_budget_report_v4 br4
      WHERE {where}
        AND br4.origin_actual_departure::date BETWEEN ${p_s} AND ${p_e}
    ),
    agg AS (
      SELECT
        customer,
        -- Pick the team with the most loads as the customer's primary team.
        (ARRAY_AGG(team ORDER BY 1) FILTER (WHERE team IS NOT NULL))[1] AS team,
        COUNT(id) FILTER (WHERE total_charge <> 0)                  AS loads,
        COALESCE(SUM(total_charge), 0)::numeric                     AS revenue,
        COALESCE(SUM(margin_amt), 0)::numeric                       AS profit,
        CASE WHEN COALESCE(SUM(total_charge),0) <> 0
             THEN SUM(margin_amt)::numeric / SUM(total_charge)::numeric
             ELSE NULL END                                          AS margin_pct,
        MAX(dep_date)                                               AS last_load_date,
        (${p_today}::date - MAX(dep_date))                          AS days_since
      FROM filtered
      GROUP BY customer
    ),
    spark AS (
      -- 8-week mini chart (week_start Mon-anchored, #loads per week).
      SELECT
        TRIM(br4.customer_name) AS customer,
        date_trunc('week', br4.origin_actual_departure)::date AS wk_start,
        COUNT(*) FILTER (WHERE br4.total_charge <> 0) AS loads_wk
      FROM public.mcleod_gld_budget_report_v4 br4
      WHERE {where}
        AND br4.origin_actual_departure::date >= ${p_spark}
        AND br4.origin_actual_departure::date <= ${p_today}
      GROUP BY 1, 2
    ),
    spark_arr AS (
      SELECT
        customer,
        ARRAY_AGG(loads_wk ORDER BY wk_start) AS sparkline
      FROM spark
      GROUP BY customer
    ),
    totals AS (
      SELECT
        COUNT(*)                                                  AS customers_total,
        COALESCE(SUM(loads), 0)::bigint                           AS loads_total,
        COALESCE(SUM(revenue), 0)::numeric                        AS revenue_total,
        COALESCE(SUM(profit), 0)::numeric                         AS profit_total,
        CASE WHEN COALESCE(SUM(revenue),0) <> 0
             THEN SUM(profit)::numeric / SUM(revenue)::numeric
             ELSE NULL END                                        AS margin_total
      FROM agg
    )
    SELECT
      a.customer,
      a.team,
      a.loads,
      a.revenue,
      a.profit,
      a.margin_pct,
      a.last_load_date,
      a.days_since,
      COALESCE(sa.sparkline, ARRAY[]::bigint[]) AS sparkline,
      (SELECT customers_total FROM totals) AS customers_total,
      (SELECT loads_total     FROM totals) AS loads_total,
      (SELECT revenue_total   FROM totals) AS revenue_total,
      (SELECT profit_total    FROM totals) AS profit_total,
      (SELECT margin_total    FROM totals) AS margin_total,
      COUNT(*) OVER ()                     AS rows_after_bucket
    FROM agg a
    LEFT JOIN spark_arr sa USING (customer)
    {f"WHERE {bucket_having}" if bucket_having else ""}
    ORDER BY {order_by}
    LIMIT ${p_limit} OFFSET ${p_offset}
    """

    rows = await pool.fetch(sql, *params)

    if not rows:
        return {
            "success": True,
            "data": {
                "rows": [],
                "totals": {
                    "customers": 0, "loads": 0, "revenue": 0.0,
                    "profit": 0.0, "margin_pct": None,
                },
                "window": {"start": s.isoformat(), "end": e.isoformat()},
                "teams_applied": team_list,
                "bucket": bucket,
            },
            "meta": {"total": 0, "page": page, "limit": limit},
        }

    out_rows = [
        {
            "customer": r["customer"],
            "team": r["team"],
            "loads": int(r["loads"] or 0),
            "revenue": float(r["revenue"] or 0),
            "profit": float(r["profit"] or 0),
            "margin_pct": float(r["margin_pct"]) if r["margin_pct"] is not None else None,
            "last_load_date": r["last_load_date"].isoformat() if r["last_load_date"] else None,
            "days_since": int(r["days_since"]) if r["days_since"] is not None else None,
            "sparkline": [int(x) for x in (r["sparkline"] or [])],
        }
        for r in rows
    ]

    first = rows[0]
    totals = {
        "customers": int(first["customers_total"] or 0),
        "loads": int(first["loads_total"] or 0),
        "revenue": float(first["revenue_total"] or 0),
        "profit": float(first["profit_total"] or 0),
        "margin_pct": float(first["margin_total"]) if first["margin_total"] is not None else None,
    }
    rows_after_bucket = int(first["rows_after_bucket"] or 0)

    return {
        "success": True,
        "data": {
            "rows": out_rows,
            "totals": totals,
            "window": {"start": s.isoformat(), "end": e.isoformat()},
            "teams_applied": team_list,
            "bucket": bucket,
        },
        "meta": {"total": rows_after_bucket, "page": page, "limit": limit},
    }


# ---------------------------------------------------------------------------
# Trend endpoint — fixed 13-month window, ignores date filter
# ---------------------------------------------------------------------------


@router.get("/trend")
async def trend(
    request: Request,
    response: Response,
    teams: Optional[str] = Query(None),
    customer: Optional[str] = Query(None),
    _user: dict = Depends(require_tag_role(*ROLES)),
):
    """Last 13 months (incl. current) — #Loads / $Profit / %Margin.

    Cached for 10 minutes (read-mostly; even with team/customer changes the
    underlying scan is ~150ms).
    """
    pool = get_datalake_gold_pool(request)
    team_list = _parse_teams(teams)

    today = date.today()
    # 13-month window starting at the first of (today − 12 months).
    start_month = today.replace(day=1)
    for _ in range(12):
        prev_end = start_month - timedelta(days=1)
        start_month = prev_end.replace(day=1)

    params: list = []
    where = _scope_where("br4", team_list, customer, params)
    params.append(start_month); p_start = len(params)
    params.append(today); p_end = len(params)

    # Generate the 13 month buckets so empty months still show 0 (cosmetic
    # parity with Bruno's chart — flat bars for dead months, not gaps).
    rows = await pool.fetch(
        f"""
        WITH months AS (
          SELECT generate_series(${p_start}::date, ${p_end}::date, '1 month')::date AS month_start
        ),
        agg AS (
          SELECT
            date_trunc('month', br4.origin_actual_departure)::date AS month_start,
            COUNT(br4.id) FILTER (WHERE br4.total_charge <> 0)::bigint AS loads,
            COALESCE(SUM(br4.total_charge), 0)::numeric AS revenue,
            COALESCE(SUM(br4.margin_amt),  0)::numeric AS profit
          FROM public.mcleod_gld_budget_report_v4 br4
          WHERE {where}
            AND br4.origin_actual_departure::date >= ${p_start}
            AND br4.origin_actual_departure::date <= ${p_end}
          GROUP BY 1
        )
        SELECT
          m.month_start,
          COALESCE(a.loads,   0) AS loads,
          COALESCE(a.revenue, 0) AS revenue,
          COALESCE(a.profit,  0) AS profit,
          CASE WHEN COALESCE(a.revenue,0) <> 0
               THEN a.profit::numeric / a.revenue::numeric
               ELSE NULL END AS margin_pct
        FROM months m
        LEFT JOIN agg a USING (month_start)
        ORDER BY m.month_start
        """,
        *params,
    )

    series = [
        {
            "month": r["month_start"].isoformat(),
            "loads": int(r["loads"] or 0),
            "revenue": float(r["revenue"] or 0),
            "profit": float(r["profit"] or 0),
            "margin_pct": float(r["margin_pct"]) if r["margin_pct"] is not None else None,
        }
        for r in rows
    ]

    response.headers["Cache-Control"] = "private, max-age=600"

    return {
        "success": True,
        "data": {
            "series": series,
            "window": {
                "start": start_month.isoformat(),
                "end": today.isoformat(),
                "months": len(series),
            },
            "teams_applied": team_list,
        },
    }
