"""Code-made report: Ops Portal - Overview.

Single-page Ops landing requested by Bruno (2026-05-10 PDF — round 1). Merges
three sources into one view:

- Production — public.mcleod_gld_budget_report_v4 (load-level) + scorecard for
  OTP/OTD; mirrors xray-corp-mng's CORP-scope filter contract.
- Budget — public.daily_production_budget_report (refreshed every 6h by n8n);
  joined to v4 via customer_team CTE for canonical team mapping.
- Savings — public.carriers_savings_results_report (variance > 0 = savings,
  variance < 0 = over-pay).

All three live on SAVINGS_DATABASE_URL (aivn_datalake_gold) → one shared pool
(``get_datalake_gold_pool``).

Scope: CORP only (TEAM1-TEAM5). The PDF explicitly excludes TEAM-DFW.

Two formula corrections from Bruno's PDF (confirmed with Diego 2026-05-10):
  A) §2/§3/Actuals "Volume" was typoed as ``loads_budget − loads_budget = 0``.
     Real intent is variance: ``loads_budget − loads_actual`` (§2/§3 follow
     Bruno's existing budget-minus-actual convention for Revenue/Profit; the
     bottom Actuals table sub-row uses ``actual − budget`` to match the
     ``133 / 153 / -20`` Kohler MTY mock).
  B) §5 "Profit / Margin / Prof×L" had ``where margin_amt<0`` filter (a paste
     from the dedicated "Profit Loss" row). The example shows $23,000 positive
     so the top-of-table Profit/Margin/Prof×L drop the filter; the explicitly
     named "Loads w/ Loss" and "Profit Loss" rows keep it.

Endpoints (all under /api/custom/ops-portal-overview, all guarded by
``require_report_access("ops-portal-overview")``):

  /filters             → teams + distinct customers
  /workdays            → Total / Past / Pending workday KPIs
  /combo               → 12-month combo (bars: Vol|Rev|Prof|Marg toggle ·
                         lines: Losses, Budget, Projected TM) — ignores Date filter
  /team-variance       → §2 — scope-wide Budget vs Actual variance row
  /customer-variance   → §3 — per-customer Budget vs Actual variance
  /customer-losses     → §4 — per-customer Production losses (margin<0)
  /team-performance    → §5 — single-row team Production+Savings KPIs
  /team-projection     → §6 — single-row team rolling 14d projection
  /profit-tm-gauge     → bottom-middle Profit-TM gauge (MTD profit vs budget)
  /actuals             → bottom Actuals per-customer roll-up

Date-filter semantics:
  - /combo, /team-projection, /workdays, /profit-tm-gauge IGNORE the Date filter
    (rolling/MTD-pinned per Bruno's "should not change with the date filter").
  - All other endpoints honor it.
  - Team + Customer filters apply everywhere.
  - Lane filter (Bruno R7, 2026-06-05 — multi-select with exclusion;
    ``concat(origin_name, ' - ', dest_name)``) applies to every v4-based
    query. The budget-only panels (§2 /team-variance, §3 /customer-variance)
    and the budget/savings sub-queries can't honor it —
    ``daily_production_budget_report`` / ``carriers_savings_results_report``
    have no lane grain (same precedent as ``load_type``).
"""

from __future__ import annotations

import asyncio
from calendar import monthrange
from datetime import date, datetime, timedelta
from typing import List, Optional

from fastapi import APIRouter, Depends, Query, Request

from app.clock import cst_today
from app.datalake import pad_variants as _pad_variants
from app.routers.deps import get_datalake_gold_pool, require_report_access

YEAR_START = date(2026, 1, 1)
YEAR_END = date(2026, 12, 31)

# CORP-only scope per the PDF (excludes TEAM-DFW).
CORP_TEAMS = ("TEAM1", "TEAM2", "TEAM3", "TEAM4", "TEAM5")
CORP_COMPANIES = ("TMS", "TMS3")
OPEN_STATUSES = ("D", "P")

# Mirrors xray_corp.OTP_CODES / OTD_CODES (Bruno's Qlik load script).
OTP_CODES = ("T4", "T3", "D1", "D2", "BO", "BE", "AL", "AI", "AH", "AF", "A5", "A2")
OTD_CODES = ("AL", "D2", "AZ", "AH", "BE", "D1", "A5", "AI", "AF", "A2", "A1", "AU", "U3")

# Mirrors budget_followup.US_HOLIDAYS_2026 — kept local so this router doesn't
# import from a sibling. If the canonical list changes, update both.
US_HOLIDAYS_2026 = frozenset({
    date(2026, 1, 1),
    date(2026, 1, 19),
    date(2026, 2, 16),
    date(2026, 5, 25),
    date(2026, 6, 19),
    date(2026, 7, 3),
    date(2026, 9, 7),
    date(2026, 10, 12),
    date(2026, 11, 11),
    date(2026, 11, 26),
    date(2026, 12, 25),
})

# Per-customer canonical team — same pattern budget_followup uses (the team
# with the most loads in v4, alphabetical tiebreak), restricted to CORP teams.
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
        WHERE TRIM(team_id) IN {CORP_TEAMS!r}
        GROUP BY TRIM(customer_name), TRIM(team_id)
    ) ranked
    WHERE rn = 1
)
"""

router = APIRouter(tags=["ops-portal-overview"], prefix="/custom/ops-portal-overview")


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


def _resolve_range(
    rng: Optional[str],
    start_date: Optional[date],
    end_date: Optional[date],
) -> tuple[date, date]:
    """Date-filter range model.

    Bruno R5 (2026-06-01) reworked the filter options. ``full`` is dropped from
    the UI but kept here as the silent default/fallback (the rolling endpoints —
    /combo, /workdays, /team-projection, /profit-tm-gauge — still pass it):
      - ytd         → Jan 1 → today
      - mtd         → 1st of current month → today (Month-to-Date)
      - this_month  → full current month (1st → last day)
      - last_month  → full previous month
      - custom      → user start/end
      - full (fallback) → whole year
    """
    today = cst_today()
    today_clamped = max(YEAR_START, min(YEAR_END, today))
    if rng == "mtd":
        return today_clamped.replace(day=1), today_clamped
    if rng == "ytd":
        return YEAR_START, today_clamped
    if rng == "this_month":
        m_start, m_end = _month_bounds(today_clamped)
        return _clamp(m_start, YEAR_START), _clamp(m_end, YEAR_END)
    if rng == "last_month":
        first_this = today_clamped.replace(day=1)
        last_prev = first_this - timedelta(days=1)
        prev_start, prev_end = _month_bounds(last_prev)
        return _clamp(prev_start, YEAR_START), _clamp(prev_end, YEAR_END)
    if rng == "custom":
        s = _clamp(start_date, YEAR_START)
        e = _clamp(end_date, YEAR_END)
        if e < s:
            s, e = e, s
        return s, e
    # default = full year
    return YEAR_START, YEAR_END


def _count_workdays(start: date, end: date) -> int:
    """Mon-Sat days in [start, end].

    Bruno round-2 (2026-05-13) — Total/Past/Pending working days are
    Monday-Saturday (Sundays only). Holidays are NOT excluded per his
    literal spec on the round-2 PDF; he didn't repeat the holiday clause
    from Budget Follow Up here.
    """
    if start > end:
        return 0
    n, d = 0, start
    while d <= end:
        if d.weekday() < 6:  # Mon=0..Sat=5
            n += 1
        d += timedelta(days=1)
    return n


def _last_n_business_days_start(today: date, n: int) -> date:
    """Earliest Mon-Sat date such that ``[start, today-1]`` has exactly n Mon-Sat days.

    Used by /team-projection and /actuals to anchor the "last 12 business
    days" averages Bruno specified in round 2.
    """
    end = today - timedelta(days=1)
    count = 0
    d = end
    while True:
        if d.weekday() < 6:
            count += 1
            if count == n:
                return d
        d -= timedelta(days=1)
        if (end - d).days > n * 3:
            # Safety bail — shouldn't ever trip, but never spin forever.
            return d


def _month_bounds(today: date) -> tuple[date, date]:
    m_start = today.replace(day=1)
    m_end = today.replace(day=monthrange(today.year, today.month)[1])
    return m_start, m_end


def _lane_expr(alias: str) -> str:
    """Lane key — ``concat(origin_name, ' - ', dest_name)`` per Bruno R7.

    COALESCE so a NULL origin/dest never turns the whole concat NULL (a NULL
    lane would silently drop rows under ``<> ALL`` exclusion). TRIM here is
    fine sargability-wise: lane is never the access path — the date + scope
    predicates narrow first (same expression /actuals-by-lane already groups
    by).
    """
    return (
        f"(TRIM(COALESCE({alias}.origin_name,'')) || ' - ' || "
        f"TRIM(COALESCE({alias}.dest_name,'')))"
    )


def _v4_scope_where(
    alias: str,
    team: Optional[str],
    customer: Optional[str],
    load_type: Optional[str],
    params: list,
    lanes: Optional[List[str]] = None,
    exclude_lanes: Optional[List[str]] = None,
) -> str:
    """CORP-scope WHERE for ``mcleod_gld_budget_report_v4``.

    Sargable (no TRIM()): pushes padded+unpadded literal variants per the
    width=8 / width=4 / width=1 declared schema on team_id / company_id /
    status. ``customer`` is exact-match (single select). ``load_type`` is
    "contract" or "spot" — falls back to no filter when None/empty.
    ``lanes`` / ``exclude_lanes`` (Bruno R7) are multi-select lane keys —
    empty/None means no filter.
    """
    teams_param = _pad_variants(CORP_TEAMS, width=8)
    companies_param = _pad_variants(CORP_COMPANIES, width=4)
    statuses_param = _pad_variants(OPEN_STATUSES, width=1)

    params.append(teams_param)
    p_teams = len(params)
    params.append(companies_param)
    p_companies = len(params)
    params.append(statuses_param)
    p_status = len(params)

    parts = [
        f"{alias}.team_id    = ANY(${p_teams})",
        f"{alias}.company_id = ANY(${p_companies})",
        f"{alias}.status     = ANY(${p_status})",
        f"UPPER(COALESCE({alias}.customer_name,'')) NOT LIKE '%OILTEX%'",
    ]
    if team:
        params.append(_pad_variants([team], width=8))
        parts.append(f"{alias}.team_id = ANY(${len(params)})")
    if customer:
        params.append(customer)
        parts.append(f"{alias}.customer_name = ${len(params)}")
    if load_type and load_type.lower() in ("contract", "spot"):
        params.append(load_type.lower())
        parts.append(
            f"LOWER(TRIM(COALESCE({alias}.contract_type_descr,''))) = ${len(params)}"
        )
    if lanes:
        params.append(lanes)
        parts.append(f"{_lane_expr(alias)} = ANY(${len(params)})")
    if exclude_lanes:
        params.append(exclude_lanes)
        parts.append(f"{_lane_expr(alias)} <> ALL(${len(params)})")
    return " AND ".join(parts)


def _scorecard_cte(kind: str) -> str:
    """OTP/OTD per-order roll-up — same shape as xray_corp._scorecard_cte.

    Reads ``mcleod_gld_scorecard_incidents_portal`` (incident grain) since
    2026-06-15 — real stop types only (no '' bucket); ``COUNT(DISTINCT id)`` keeps
    it fan-out-safe. See SPEC-CODE-RULES §43.
    """
    if kind == "otp":
        codes = OTP_CODES
        stops = ("PU", "SH")
        out = "scorecard_count_otp"
    else:
        codes = OTD_CODES
        stops = ("CO", "SO")
        out = "scorecard_count_otd"

    def _lit(values, *, width: int) -> str:
        return ",".join(f"'{v}'" for v in _pad_variants(values, width=width))

    codes_sql = _lit(codes, width=40)
    stops_sql = _lit(stops, width=2)
    teams_sql = _lit(CORP_TEAMS, width=8)
    companies_sql = _lit(CORP_COMPANIES, width=4)
    statuses_sql = _lit(OPEN_STATUSES, width=1)
    return f"""
    SELECT
      TRIM(id)         AS id_key,
      TRIM(company_id) AS company_id_key,
      COUNT(DISTINCT id) AS {out}
    FROM public.mcleod_gld_scorecard_incidents_portal
    WHERE team_id    IN ({teams_sql})
      AND company_id IN ({companies_sql})
      AND status     IN ({statuses_sql})
      AND stop_type  IN ({stops_sql})
      AND total_charge IS NOT NULL AND total_charge <> 0
      AND edi_standard_code IN ({codes_sql})
    GROUP BY TRIM(id), TRIM(company_id)
    """


def _safe_float(v) -> float:
    """Strip NaN/Inf so JSON serialization never blows up the page."""
    try:
        f = float(v) if v is not None else 0.0
    except (TypeError, ValueError):
        return 0.0
    if f != f or f in (float("inf"), float("-inf")):
        return 0.0
    return f


def _bill_metrics_sql(where: str, p_s: int, p_e: int, *, group_by_team: bool) -> str:
    """Per-order billing metrics — Bruno round (2026-07-01) R12.

      avg_days_billed     = AVG(bill_date − dest_actual_departure) over billed orders
      avg_days_not_billed = AVG(CURRENT_DATE − dest_actual_departure) over unbilled orders
      del_bill_le2/denom  = Delivery-vs-Bill <=2D ratio (mirrors admin-cashflow)

    ``bill_date`` is on v4; ``dest_actual_departure``/``dest_actual_arrival`` come
    from ``mcleod_gld_customer_windows`` (same sentinel-guarded LATERAL as By
    Order R11, so the panel reconciles with the Days-to-Bill column). When
    ``group_by_team`` the result carries one row per ``team_id``.
    """
    team_sel = "TRIM(br4.team_id) AS team_id," if group_by_team else ""
    team_out = "team_id," if group_by_team else ""
    group_clause = "GROUP BY team_id" if group_by_team else ""
    return f"""
        WITH ord AS (
            SELECT
              {team_sel}
              br4.bill_date AS bill_date,
              win.dest_dep, win.dest_arr
            FROM public.mcleod_gld_budget_report_v4 br4
            LEFT JOIN LATERAL (
                SELECT MAX(CASE WHEN cw.dest_actual_departure > '2000-01-01' THEN cw.dest_actual_departure END) AS dest_dep,
                       MAX(CASE WHEN cw.dest_actual_arrival   > '2000-01-01' THEN cw.dest_actual_arrival   END) AS dest_arr
                FROM public.mcleod_gld_customer_windows cw
                WHERE TRIM(UPPER(cw.id)) = TRIM(UPPER(br4.id))
            ) win ON TRUE
            WHERE {where}
              AND br4.origin_actual_departure >= ${p_s}
              AND br4.origin_actual_departure < (${p_e}::date + INTERVAL '1 day')
        )
        SELECT
          {team_out}
          AVG(bill_date::date - dest_dep::date)
            FILTER (WHERE bill_date > '2000-01-01' AND dest_dep IS NOT NULL) AS avg_days_billed,
          AVG(CURRENT_DATE - dest_dep::date)
            FILTER (WHERE bill_date < '2000-01-01' AND dest_dep IS NOT NULL) AS avg_days_not_billed,
          COUNT(*) FILTER (WHERE bill_date > '2000-01-01' AND dest_dep IS NOT NULL AND dest_arr IS NOT NULL) AS del_bill_denom,
          COUNT(*) FILTER (WHERE bill_date > '2000-01-01' AND dest_dep IS NOT NULL AND dest_arr IS NOT NULL
                             AND (bill_date::date - dest_dep::date) <= 2) AS del_bill_le2
        FROM ord
        {group_clause}
    """


def _bill_fields(row) -> dict:
    """Map a billing-metrics row → the 3 R12 wire fields (0-safe)."""
    denom = int(row["del_bill_denom"] or 0) if row else 0
    le2 = int(row["del_bill_le2"] or 0) if row else 0
    return {
        "avg_days_billed":     _safe_float(row["avg_days_billed"]) if row else 0.0,
        "avg_days_not_billed": _safe_float(row["avg_days_not_billed"]) if row else 0.0,
        "pct_del_bill":        (le2 / denom * 100.0) if denom else 0.0,
    }


# ---------------------------------------------------------------------------
# /filters — teams + customers
# ---------------------------------------------------------------------------


@router.get("/filters")
async def filters(
    request: Request,
    _user: dict = Depends(require_report_access("ops-portal-overview")),
):
    """Teams (TEAM1..TEAM5), distinct customers and distinct lanes (Bruno R7)
    across the YTD window."""
    pool = get_datalake_gold_pool(request)
    scope_args = [
        list(CORP_TEAMS),
        list(CORP_COMPANIES),
        list(OPEN_STATUSES),
        YEAR_START,
    ]
    cust_sql = """
        SELECT DISTINCT TRIM(customer_name) AS customer_name
        FROM public.mcleod_gld_budget_report_v4
        WHERE TRIM(team_id)    = ANY($1)
          AND TRIM(company_id) = ANY($2)
          AND TRIM(status)     = ANY($3)
          AND UPPER(COALESCE(customer_name,'')) NOT LIKE '%OILTEX%'
          AND customer_name IS NOT NULL
          AND TRIM(customer_name) <> ''
          AND origin_actual_departure >= $4
        ORDER BY customer_name
    """
    lane_sql = f"""
        SELECT DISTINCT {_lane_expr("br4")} AS lane
        FROM public.mcleod_gld_budget_report_v4 br4
        WHERE TRIM(br4.team_id)    = ANY($1)
          AND TRIM(br4.company_id) = ANY($2)
          AND TRIM(br4.status)     = ANY($3)
          AND UPPER(COALESCE(br4.customer_name,'')) NOT LIKE '%OILTEX%'
          AND TRIM(COALESCE(br4.origin_name,'')) <> ''
          AND TRIM(COALESCE(br4.dest_name,''))   <> ''
          AND br4.origin_actual_departure >= $4
        ORDER BY lane
    """
    cust_rows, lane_rows = await asyncio.gather(
        pool.fetch(cust_sql, *scope_args),
        pool.fetch(lane_sql, *scope_args),
    )
    return {
        "success": True,
        "data": {
            "teams": list(CORP_TEAMS),
            "customers": [r["customer_name"] for r in cust_rows],
            "lanes": [r["lane"] for r in lane_rows],
            "year_start": YEAR_START.isoformat(),
            "year_end": YEAR_END.isoformat(),
        },
    }


# ---------------------------------------------------------------------------
# /workdays — Total / Past / Pending Mon-Fri ex-holidays for current month
# ---------------------------------------------------------------------------


@router.get("/workdays")
async def workdays(
    request: Request,
    _user: dict = Depends(require_report_access("ops-portal-overview")),
):
    """KPI strip at bottom-left of the chart. Mon-Fri excluding US 2026 holidays."""
    today = cst_today()
    m_start, m_end = _month_bounds(today)
    total = _count_workdays(m_start, m_end)
    past = _count_workdays(m_start, today - timedelta(days=1))
    pending = _count_workdays(today, m_end)
    return {
        "success": True,
        "data": {
            "month_start": m_start.isoformat(),
            "month_end": m_end.isoformat(),
            "today": today.isoformat(),
            "total_workdays": total,
            "past_workdays": past,
            "pending_workdays": pending,
        },
    }


# ---------------------------------------------------------------------------
# /combo — Day / Week / Month bars + lines (Bruno round 3, 2026-05-19)
# ---------------------------------------------------------------------------


def _resolve_grain_window(grain: str, today: date) -> tuple[date, date, list[date]]:
    """Build the bucket window and per-bucket anchor dates for a grain.

    Bruno round 3 (2026-05-19): chart adds Day / Week / Month grain pickers
    with scroll-bar zoom. Backend fetches the maximum window per grain (120 d
    / 50 w / 26 m); frontend Brush positions the visible window.
    """
    if grain == "day":
        n = 120
        end = today
        start = end - timedelta(days=n - 1)
        anchors = [start + timedelta(days=i) for i in range(n)]
        return start, end, anchors
    if grain == "week":
        n = 50
        # Anchor on Monday of the current ISO week.
        this_mon = today - timedelta(days=today.weekday())
        start = this_mon - timedelta(weeks=n - 1)
        anchors = [start + timedelta(weeks=i) for i in range(n)]
        end = anchors[-1] + timedelta(days=6)
        if end > today:
            end = today
        return start, end, anchors
    # month
    n = 26
    cursor = today.replace(day=1)
    anchors_desc: list[date] = [cursor]
    for _ in range(n - 1):
        prev_last = anchors_desc[-1] - timedelta(days=1)
        anchors_desc.append(prev_last.replace(day=1))
    anchors = list(reversed(anchors_desc))
    last = anchors[-1]
    end = last.replace(day=monthrange(last.year, last.month)[1])
    if end > today:
        # Cap window at today so we don't double-count partials.
        end = today
    return anchors[0], end, anchors


@router.get("/combo")
async def combo(
    request: Request,
    team: Optional[str] = Query(None),
    customer: Optional[str] = Query(None),
    load_type: Optional[str] = Query(None, description="'contract' | 'spot' | null"),
    lanes: Optional[List[str]] = Query(None),
    exclude_lanes: Optional[List[str]] = Query(None),
    grain: str = Query("month", description="'day' | 'week' | 'month'"),
    _user: dict = Depends(require_report_access("ops-portal-overview")),
):
    """Day/Week/Month combo. Bars carry vol/rev/prof/margin so the UI can swap
    between them without re-fetching. Lines: losses_{vol,rev,prof,margin_pct},
    budget_{loads,revenue,profit,margin_pct}, projected_{vol,revenue,profit,margin_pct}.

    Bruno's round-3 per-tab "Losses x M" formula spec (2026-05-19 PDF):
      - Vol tab   → losses_vol         = COUNT(*) WHERE margin_amt < 0
      - Rev tab   → losses_rev         = SUM(total_charge) WHERE margin_amt < 0
      - Prof tab  → losses_prof        = SUM(margin_amt) WHERE margin_amt < 0
      - Marg.% tab→ losses_margin_pct  = losses_prof / losses_rev * 100

    BDGT line scales with the tab too — backend returns all four budget variants.
    Frontend picks the matching key based on the active measure pill.

    Source split unchanged:
      - Bars + losses_*   → mcleod_gld_budget_report_v4 (Production)
      - budget_*          → daily_production_budget_report (Budget)
      - projected_*       → 14-day rolling Production extrapolated to EoM
    """
    if grain not in ("day", "week", "month"):
        grain = "month"
    pool = get_datalake_gold_pool(request)
    today = cst_today()
    win_start, win_end, anchors = _resolve_grain_window(grain, today)

    trunc_v4 = {
        "day":   "br4.origin_actual_departure::date",
        "week":  "DATE_TRUNC('week', br4.origin_actual_departure)::date",
        "month": "DATE_TRUNC('month', br4.origin_actual_departure)::date",
    }[grain]
    trunc_bud = {
        "day":   'budget."Date"::date',
        "week":  'DATE_TRUNC(\'week\', budget."Date")::date',
        "month": 'DATE_TRUNC(\'month\', budget."Date")::date',
    }[grain]

    # ---- Production query (bars + losses) -------------------------------
    prod_params: list = []
    where = _v4_scope_where("br4", team, customer, load_type, prod_params, lanes, exclude_lanes)
    prod_params.extend([win_start, win_end])
    p_ws = len(prod_params) - 1
    p_we = len(prod_params)
    prod_sql = f"""
        SELECT
          {trunc_v4} AS bucket_start,
          COUNT(*) FILTER (WHERE br4.total_charge IS NOT NULL AND br4.total_charge <> 0) AS volume,
          COALESCE(SUM(br4.total_charge), 0)::numeric AS revenue,
          COALESCE(SUM(br4.margin_amt), 0)::numeric   AS profit,
          COUNT(*) FILTER (WHERE br4.margin_amt < 0
                             AND br4.total_charge IS NOT NULL
                             AND br4.total_charge <> 0) AS losses_vol,
          COALESCE(SUM(br4.total_charge) FILTER (WHERE br4.margin_amt < 0), 0)::numeric AS losses_rev,
          COALESCE(SUM(br4.margin_amt)   FILTER (WHERE br4.margin_amt < 0), 0)::numeric AS losses_prof
        FROM public.mcleod_gld_budget_report_v4 br4
        WHERE {where}
          AND br4.origin_actual_departure >= ${p_ws}
          AND br4.origin_actual_departure < (${p_we}::date + INTERVAL '1 day')
        GROUP BY 1
    """

    # ---- Budget (Budget URL) --------------------------------------------
    bud_params: list = [win_start, win_end]
    bud_extra = ""
    if team:
        bud_params.append(team)
        bud_extra += f" AND ct.team_id = ${len(bud_params)}"
    if customer:
        bud_params.append(customer)
        bud_extra += f' AND budget."Customer Name" = ${len(bud_params)}'
    bud_sql = f"""
        WITH {CUSTOMER_TEAM_CTE}
        SELECT
          {trunc_bud} AS bucket_start,
          COALESCE(SUM(budget."Revenue Budget"), 0)::numeric AS budget_revenue,
          COALESCE(SUM(budget."Profit Budget"),  0)::numeric AS budget_profit,
          COALESCE(SUM(budget."Loads Budget"),   0)::numeric AS budget_loads
        FROM public.daily_production_budget_report budget
        JOIN customer_team ct ON TRIM(budget."Customer Name") = ct.customer_name
        WHERE budget."Date" BETWEEN $1 AND $2
        {bud_extra}
        GROUP BY 1
    """

    # ---- Projected — last 14 calendar days extrapolated to EoM ----------
    m_start, m_end = _month_bounds(today)
    win14_start = today - timedelta(days=14)
    win14_end = today - timedelta(days=1)  # don't include today (partial)
    pending_workdays = _count_workdays(today, m_end)

    proj_params: list = []
    where_proj = _v4_scope_where("br4", team, customer, load_type, proj_params, lanes, exclude_lanes)
    proj_params.extend([win14_start, win14_end, m_start, win14_end])
    p_w14s = len(proj_params) - 3
    p_w14e = len(proj_params) - 2
    p_ms = len(proj_params) - 1
    p_w14e2 = len(proj_params)
    proj_sql = f"""
        SELECT
          COUNT(*) FILTER (WHERE br4.origin_actual_departure::date BETWEEN ${p_w14s} AND ${p_w14e}
                             AND br4.total_charge IS NOT NULL
                             AND br4.total_charge <> 0) AS vol_14,
          COALESCE(SUM(CASE WHEN br4.origin_actual_departure::date BETWEEN ${p_w14s} AND ${p_w14e}
                            THEN br4.total_charge ELSE 0 END), 0)::numeric AS rev_14,
          COALESCE(SUM(CASE WHEN br4.origin_actual_departure::date BETWEEN ${p_w14s} AND ${p_w14e}
                            THEN br4.margin_amt  ELSE 0 END), 0)::numeric AS prof_14,
          COUNT(*) FILTER (WHERE br4.origin_actual_departure::date BETWEEN ${p_ms} AND ${p_w14e2}
                             AND br4.total_charge IS NOT NULL
                             AND br4.total_charge <> 0) AS vol_mtd,
          COALESCE(SUM(CASE WHEN br4.origin_actual_departure::date BETWEEN ${p_ms} AND ${p_w14e2}
                            THEN br4.total_charge ELSE 0 END), 0)::numeric AS rev_mtd,
          COALESCE(SUM(CASE WHEN br4.origin_actual_departure::date BETWEEN ${p_ms} AND ${p_w14e2}
                            THEN br4.margin_amt  ELSE 0 END), 0)::numeric AS prof_mtd
        FROM public.mcleod_gld_budget_report_v4 br4
        WHERE {where_proj}
    """

    prod_rows, bud_rows, proj_row = await asyncio.gather(
        pool.fetch(prod_sql, *prod_params),
        pool.fetch(bud_sql, *bud_params),
        pool.fetchrow(proj_sql, *proj_params),
    )

    prod_map = {r["bucket_start"]: r for r in prod_rows}
    bud_map = {r["bucket_start"]: r for r in bud_rows}

    vol_14 = _safe_float(proj_row["vol_14"]) if proj_row else 0.0
    rev_14 = _safe_float(proj_row["rev_14"]) if proj_row else 0.0
    prof_14 = _safe_float(proj_row["prof_14"]) if proj_row else 0.0
    vol_mtd = _safe_float(proj_row["vol_mtd"]) if proj_row else 0.0
    rev_mtd = _safe_float(proj_row["rev_mtd"]) if proj_row else 0.0
    prof_mtd = _safe_float(proj_row["prof_mtd"]) if proj_row else 0.0
    projected_vol     = (vol_14  / 14.0) * pending_workdays + vol_mtd
    projected_revenue = (rev_14  / 14.0) * pending_workdays + rev_mtd
    projected_profit  = (prof_14 / 14.0) * pending_workdays + prof_mtd
    projected_margin_pct = (projected_profit / projected_revenue * 100.0) if projected_revenue else 0.0

    out = []
    for a in anchors:
        p = prod_map.get(a)
        b = bud_map.get(a)
        p_rev   = _safe_float(p["revenue"]) if p else 0.0
        p_prof  = _safe_float(p["profit"])  if p else 0.0
        l_rev   = _safe_float(p["losses_rev"])  if p else 0.0
        l_prof  = _safe_float(p["losses_prof"]) if p else 0.0
        b_rev   = _safe_float(b["budget_revenue"]) if b else 0.0
        b_prof  = _safe_float(b["budget_profit"])  if b else 0.0
        out.append({
            "bucket_start": a.isoformat(),
            "volume":     int(p["volume"]) if p else 0,
            "revenue":    p_rev,
            "profit":     p_prof,
            "margin_pct": (p_prof / p_rev * 100.0) if p_rev else 0.0,
            # Per-tab losses variants (Bruno round 3).
            "losses_vol":        int(p["losses_vol"]) if p else 0,
            "losses_rev":        l_rev,
            "losses_prof":       l_prof,
            "losses_margin_pct": (l_prof / l_rev * 100.0) if l_rev else 0.0,
            # Per-tab budget variants.
            "budget_loads":      _safe_float(b["budget_loads"]) if b else 0.0,
            "budget_revenue":    b_rev,
            "budget_profit":     b_prof,
            "budget_margin_pct": (b_prof / b_rev * 100.0) if b_rev else 0.0,
        })

    return {
        "success": True,
        "data": {
            "grain": grain,
            "buckets": out,
            "projected_vol":        _safe_float(projected_vol),
            "projected_revenue":    _safe_float(projected_revenue),
            "projected_profit":     _safe_float(projected_profit),
            "projected_margin_pct": _safe_float(projected_margin_pct),
            "today": today.isoformat(),
            "month_start": m_start.isoformat(),
            "month_end": m_end.isoformat(),
            "pending_workdays": pending_workdays,
        },
    }


# ---------------------------------------------------------------------------
# /team-variance — §2 scope-wide Budget vs Actual variance row (Budget URL)
# ---------------------------------------------------------------------------


@router.get("/team-variance")
async def team_variance(
    request: Request,
    range: Optional[str] = Query("mtd"),
    start_date: Optional[date] = Query(None),
    end_date: Optional[date] = Query(None),
    team: Optional[str] = Query(None),
    customer: Optional[str] = Query(None),
    _user: dict = Depends(require_report_access("ops-portal-overview")),
):
    """Bruno's "Team Budget Monthly Variance" inverted table — single row.

    Bruno round-2 (2026-05-13) — flipped the variance convention to
    ``actual − budget`` (positive = over-performing) to harmonise with the
    bottom Actuals table. Customers KPI = count of customers in budget
    that actually shipped (loads_actual > 0); his literal subtraction
    formula reads negative, but the screenshot value (24) matches the
    active count, so display that.
    """
    pool = get_datalake_gold_pool(request)
    s, e = _resolve_range(range, start_date, end_date)
    params: list = [s, e]
    extra = ""
    if team:
        params.append(team)
        extra += f" AND ct.team_id = ${len(params)}"
    if customer:
        params.append(customer)
        extra += f' AND budget."Customer Name" = ${len(params)}'

    row = await pool.fetchrow(
        f"""
        WITH {CUSTOMER_TEAM_CTE},
        per_customer AS (
          SELECT
            budget."Customer Name" AS customer_name,
            SUM(budget."Loads Actual")    AS loads_actual,
            SUM(budget."Loads Budget")    AS loads_budget,
            SUM(budget."Revenue Actual")  AS revenue_actual,
            SUM(budget."Revenue Budget")  AS revenue_budget,
            SUM(budget."Profit Actual")   AS profit_actual,
            SUM(budget."Profit Budget")   AS profit_budget
          FROM public.daily_production_budget_report budget
          JOIN customer_team ct ON TRIM(budget."Customer Name") = ct.customer_name
          WHERE budget."Date" BETWEEN $1 AND $2
          {extra}
          GROUP BY budget."Customer Name"
        )
        SELECT
          COUNT(*) FILTER (WHERE COALESCE(loads_actual,0) > 0) AS active_customers,
          COUNT(*)                                              AS in_scope_customers,
          COALESCE(SUM(loads_budget),   0) AS loads_budget,
          COALESCE(SUM(loads_actual),   0) AS loads_actual,
          COALESCE(SUM(revenue_budget), 0) AS revenue_budget,
          COALESCE(SUM(revenue_actual), 0) AS revenue_actual,
          COALESCE(SUM(profit_budget),  0) AS profit_budget,
          COALESCE(SUM(profit_actual),  0) AS profit_actual
        FROM per_customer
        """,
        *params,
    )

    # Bruno round-2 (2026-05-13): actual − budget direction (positive = over-budget).
    loads_var   = _safe_float(row["loads_actual"])   - _safe_float(row["loads_budget"])
    revenue_var = _safe_float(row["revenue_actual"]) - _safe_float(row["revenue_budget"])
    profit_var  = _safe_float(row["profit_actual"])  - _safe_float(row["profit_budget"])
    margin_var_pct = (profit_var / revenue_var * 100.0) if revenue_var else 0.0
    rev_x_l = (revenue_var / loads_var) if loads_var else 0.0
    prof_x_l = (profit_var / loads_var) if loads_var else 0.0

    return {
        "success": True,
        "data": {
            # Active customers = customers in budget that actually shipped.
            # Bruno's literal "count(loads_actual=0) − count(*)" reads negative;
            # his screenshot value (24) matches the active count, so we surface that.
            "customers":      int(row["active_customers"] or 0),
            "volume_var":     _safe_float(loads_var),
            "revenue_var":    _safe_float(revenue_var),
            "profit_var":     _safe_float(profit_var),
            "margin_var_pct": _safe_float(margin_var_pct),
            "rev_x_l":        _safe_float(rev_x_l),
            "prof_x_l":       _safe_float(prof_x_l),
            "window": {"start": s.isoformat(), "end": e.isoformat()},
        },
    }


# ---------------------------------------------------------------------------
# /customer-variance — §3 per-customer Budget vs Actual variance (Budget URL)
# ---------------------------------------------------------------------------


@router.get("/customer-variance")
async def customer_variance(
    request: Request,
    range: Optional[str] = Query("mtd"),
    start_date: Optional[date] = Query(None),
    end_date: Optional[date] = Query(None),
    team: Optional[str] = Query(None),
    customer: Optional[str] = Query(None),
    limit: int = Query(50, ge=1, le=200),
    _user: dict = Depends(require_report_access("ops-portal-overview")),
):
    """§3 Customer Monthly Variance — one row per customer."""
    pool = get_datalake_gold_pool(request)
    s, e = _resolve_range(range, start_date, end_date)
    params: list = [s, e]
    extra = ""
    if team:
        params.append(team)
        extra += f" AND ct.team_id = ${len(params)}"
    if customer:
        params.append(customer)
        extra += f' AND budget."Customer Name" = ${len(params)}'
    params.append(limit)

    # Bruno round-2 (2026-05-13): actual − budget direction (positive = over-budget).
    rows = await pool.fetch(
        f"""
        WITH {CUSTOMER_TEAM_CTE}
        SELECT
          budget."Customer Name" AS customer_name,
          COALESCE(SUM(budget."Loads Actual"),    0)
            - COALESCE(SUM(budget."Loads Budget"),    0) AS volume_var,
          COALESCE(SUM(budget."Profit Actual"),   0)
            - COALESCE(SUM(budget."Profit Budget"),   0) AS profit_var,
          COALESCE(SUM(budget."Revenue Actual"),  0)
            - COALESCE(SUM(budget."Revenue Budget"),  0) AS revenue_var
        FROM public.daily_production_budget_report budget
        JOIN customer_team ct ON TRIM(budget."Customer Name") = ct.customer_name
        WHERE budget."Date" BETWEEN $1 AND $2
        {extra}
        GROUP BY budget."Customer Name"
        ORDER BY ABS(COALESCE(SUM(budget."Profit Actual"),0)
                   - COALESCE(SUM(budget."Profit Budget"),0)) DESC NULLS LAST
        LIMIT ${len(params)}
        """,
        *params,
    )
    return {
        "success": True,
        "data": [
            {
                "customer_name": r["customer_name"],
                "volume_var":   _safe_float(r["volume_var"]),
                "revenue_var":  _safe_float(r["revenue_var"]),
                "profit_var":   _safe_float(r["profit_var"]),
            }
            for r in rows
        ],
    }


# ---------------------------------------------------------------------------
# /customer-losses — §4 per-customer Production losses (margin<0) — Production URL
# ---------------------------------------------------------------------------


@router.get("/customer-losses")
async def customer_losses(
    request: Request,
    range: Optional[str] = Query("mtd"),
    start_date: Optional[date] = Query(None),
    end_date: Optional[date] = Query(None),
    team: Optional[str] = Query(None),
    customer: Optional[str] = Query(None),
    load_type: Optional[str] = Query(None),
    lanes: Optional[List[str]] = Query(None),
    exclude_lanes: Optional[List[str]] = Query(None),
    limit: int = Query(50, ge=1, le=200),
    _user: dict = Depends(require_report_access("ops-portal-overview")),
):
    """§4 Customer Monthly Losses — one row per customer."""
    pool = get_datalake_gold_pool(request)
    s, e = _resolve_range(range, start_date, end_date)
    params: list = []
    where = _v4_scope_where("br4", team, customer, load_type, params, lanes, exclude_lanes)
    params.extend([s, e, limit])
    p_s = len(params) - 2
    p_e = len(params) - 1
    p_lim = len(params)

    rows = await pool.fetch(
        f"""
        SELECT
          br4.customer_name,
          COUNT(*) FILTER (WHERE br4.margin_amt < 0
                             AND br4.total_charge IS NOT NULL
                             AND br4.total_charge <> 0) AS loss_loads,
          COALESCE(SUM(CASE WHEN br4.margin_amt < 0 THEN br4.margin_amt END), 0)::numeric AS loss_profit
        FROM public.mcleod_gld_budget_report_v4 br4
        WHERE {where}
          AND br4.origin_actual_departure >= ${p_s}
          AND br4.origin_actual_departure < (${p_e}::date + INTERVAL '1 day')
        GROUP BY br4.customer_name
        HAVING COUNT(*) FILTER (WHERE br4.margin_amt < 0) > 0
        ORDER BY loss_profit ASC NULLS LAST
        LIMIT ${p_lim}
        """,
        *params,
    )
    return {
        "success": True,
        "data": [
            {
                "customer_name": r["customer_name"],
                "loss_loads":  int(r["loss_loads"] or 0),
                "loss_profit": _safe_float(r["loss_profit"]),
            }
            for r in rows
        ],
    }


# ---------------------------------------------------------------------------
# /customer-not-billed — Bruno round (2026-07-01) R14: per-customer "Not Billed"
# ---------------------------------------------------------------------------


@router.get("/customer-not-billed")
async def customer_not_billed(
    request: Request,
    range: Optional[str] = Query("mtd"),
    start_date: Optional[date] = Query(None),
    end_date: Optional[date] = Query(None),
    team: Optional[str] = Query(None),
    customer: Optional[str] = Query(None),
    load_type: Optional[str] = Query(None),
    lanes: Optional[List[str]] = Query(None),
    exclude_lanes: Optional[List[str]] = Query(None),
    limit: int = Query(100, ge=1, le=500),
    _user: dict = Depends(require_report_access("ops-portal-overview")),
):
    """Bruno R14 — orders never billed (``bill_date < '2000-01-01'`` sentinel),
    grouped per customer.

      Loads   = COUNT(orders where bill_date < '2000-01-01')
      Revenue = SUM(total_charge where bill_date < '2000-01-01')

    Same CORP scope + page date range (origin_actual_departure) as the sibling
    Customer Monthly Losses table. Totals in ``meta`` are the full-universe
    window aggregate (never a client reduce over the LIMIT slice — §44)."""
    pool = get_datalake_gold_pool(request)
    s, e = _resolve_range(range, start_date, end_date)
    params: list = []
    where = _v4_scope_where("br4", team, customer, load_type, params, lanes, exclude_lanes)
    params.extend([s, e, limit])
    p_s = len(params) - 2
    p_e = len(params) - 1
    p_lim = len(params)

    rows = await pool.fetch(
        f"""
        WITH g AS (
            SELECT
              br4.customer_name AS customer_name,
              COUNT(*)                                     AS loads,
              COALESCE(SUM(br4.total_charge), 0)::numeric  AS revenue
            FROM public.mcleod_gld_budget_report_v4 br4
            WHERE {where}
              AND br4.origin_actual_departure >= ${p_s}
              AND br4.origin_actual_departure < (${p_e}::date + INTERVAL '1 day')
              AND br4.bill_date < '2000-01-01'::date
            GROUP BY br4.customer_name
        )
        SELECT
          customer_name, loads, revenue,
          SUM(loads)   OVER () AS loads_total,
          SUM(revenue) OVER () AS revenue_total,
          COUNT(*)     OVER () AS cust_total
        FROM g
        ORDER BY revenue DESC NULLS LAST
        LIMIT ${p_lim}
        """,
        *params,
    )
    totals = {
        "loads":   int(rows[0]["loads_total"] or 0) if rows else 0,
        "revenue": _safe_float(rows[0]["revenue_total"]) if rows else 0.0,
    }
    return {
        "success": True,
        "data": [
            {
                "customer_name": r["customer_name"],
                "loads":   int(r["loads"] or 0),
                "revenue": _safe_float(r["revenue"]),
            }
            for r in rows
        ],
        "meta": {
            "window": {"start": s.isoformat(), "end": e.isoformat()},
            "total": int(rows[0]["cust_total"] or 0) if rows else 0,
            "totals": totals,
        },
    }


# ---------------------------------------------------------------------------
# /team-performance — §5 single-row team Production+Savings KPIs
# ---------------------------------------------------------------------------


@router.get("/team-performance")
async def team_performance(
    request: Request,
    range: Optional[str] = Query("mtd"),
    start_date: Optional[date] = Query(None),
    end_date: Optional[date] = Query(None),
    team: Optional[str] = Query(None),
    customer: Optional[str] = Query(None),
    load_type: Optional[str] = Query(None),
    lanes: Optional[List[str]] = Query(None),
    exclude_lanes: Optional[List[str]] = Query(None),
    _user: dict = Depends(require_report_access("ops-portal-overview")),
):
    """§5 Team Monthly Performance — Production + Savings.

    Bruno's PDF had ``where margin_amt<0`` on Profit / Margin / Prof×L which
    flipped them losses-only and contradicted the $23,000 positive mock. Fix
    confirmed 2026-05-10: top-of-table Profit/Margin/Prof×L drop the filter;
    explicitly named Loads-w/-Loss and Profit-Loss rows keep it.
    """
    pool = get_datalake_gold_pool(request)
    s, e = _resolve_range(range, start_date, end_date)

    # ---- Production query ------------------------------------------------
    prod_params: list = []
    where = _v4_scope_where("br4", team, customer, load_type, prod_params, lanes, exclude_lanes)
    prod_params.extend([s, e])
    p_s = len(prod_params) - 1
    p_e = len(prod_params)

    # Distinct team count for Team Ut. — when a single team is filtered,
    # capacity = 1 × 500. Otherwise = (number of CORP teams that appear in scope).
    prod_sql = f"""
        WITH otp AS ({_scorecard_cte("otp")}),
             otd AS ({_scorecard_cte("otd")}),
             prod AS (
                SELECT br4.id, br4.company_id, br4.team_id, br4.customer_name,
                       TRIM(br4.origin_name) AS origin,
                       TRIM(br4.dest_name)   AS dest,
                       br4.total_charge, br4.margin_amt, br4.total_carrier_pay,
                       COALESCE(otp.scorecard_count_otp, 0) AS otp_cnt,
                       COALESCE(otd.scorecard_count_otd, 0) AS otd_cnt
                FROM public.mcleod_gld_budget_report_v4 br4
                LEFT JOIN otp ON TRIM(br4.id)=otp.id_key AND TRIM(br4.company_id)=otp.company_id_key
                LEFT JOIN otd ON TRIM(br4.id)=otd.id_key AND TRIM(br4.company_id)=otd.company_id_key
                WHERE {where}
                  AND br4.origin_actual_departure >= ${p_s}
                  AND br4.origin_actual_departure < (${p_e}::date + INTERVAL '1 day')
             )
        SELECT
          COUNT(DISTINCT customer_name) AS customers,
          COUNT(DISTINCT (origin || ' - ' || dest))
            FILTER (WHERE origin <> '' AND dest <> '') AS lanes,
          COUNT(*) FILTER (WHERE total_charge IS NOT NULL AND total_charge <> 0) AS volume,
          COALESCE(SUM(total_charge), 0)::numeric AS revenue,
          -- Bruno R5 (2026-06-01): Total Cost between Revenue and Profit.
          COALESCE(SUM(total_carrier_pay), 0)::numeric AS total_cost,
          COALESCE(SUM(margin_amt),  0)::numeric AS profit,
          COUNT(*) FILTER (WHERE margin_amt < 0
                             AND total_charge IS NOT NULL
                             AND total_charge <> 0) AS loss_loads,
          COALESCE(SUM(margin_amt) FILTER (WHERE margin_amt < 0), 0)::numeric AS profit_loss,
          SUM(otp_cnt) AS otp_late_sum,
          SUM(otd_cnt) AS otd_late_sum,
          COUNT(DISTINCT team_id) AS team_count
        FROM prod
    """

    # ---- Savings query (variance>0 = savings, variance<0 = over-pay) -----
    sav_params: list = [s, e]
    sav_extra = " AND UPPER(COALESCE(cs.customer_name,'')) NOT LIKE '%OILTEX%'"
    if customer:
        sav_params.append(customer)
        sav_extra += f" AND cs.customer_name = ${len(sav_params)}"
    if team:
        sav_params.append(team)
        sav_extra += f" AND ct.team_id = ${len(sav_params)}"
    sav_sql = f"""
        WITH {CUSTOMER_TEAM_CTE}
        SELECT
          COALESCE(SUM(CASE WHEN cs.variance > 0 THEN cs.variance ELSE 0 END), 0)::numeric AS total_savings,
          COALESCE(SUM(CASE WHEN cs.variance < 0 THEN cs.variance ELSE 0 END), 0)::numeric AS total_overpay,
          COALESCE(SUM(cs.variance), 0)::numeric AS net_savings
        FROM public.carriers_savings_results_report cs
        JOIN customer_team ct ON TRIM(cs.customer_name) = ct.customer_name
        WHERE cs.month_date BETWEEN $1 AND $2
        {sav_extra}
    """

    # ---- Attrition (mirrors xray-corp /attrition) — last-load freshness --
    # Customer attrition % = customers with last_load > 30d / customers total
    # Lane attrition % = lanes with last_load > 30d / lanes total
    attr_params: list = []
    where_attr = _v4_scope_where("br4", team, customer, load_type, attr_params, lanes, exclude_lanes)
    attr_params.append(YEAR_START)
    p_ys = len(attr_params)
    attr_sql = f"""
        WITH lane_last AS (
            SELECT br4.customer_name,
                   TRIM(br4.origin_name) AS origin,
                   TRIM(br4.dest_name)   AS dest,
                   MAX(br4.origin_actual_departure)::date AS last_load
            FROM public.mcleod_gld_budget_report_v4 br4
            WHERE {where_attr}
              AND br4.origin_actual_departure >= ${p_ys}
              AND br4.customer_name IS NOT NULL
              AND TRIM(br4.origin_name) <> ''
              AND TRIM(br4.dest_name)   <> ''
            GROUP BY br4.customer_name, TRIM(br4.origin_name), TRIM(br4.dest_name)
        ),
        cust_last AS (
            SELECT customer_name, MAX(last_load) AS last_load
            FROM lane_last
            GROUP BY customer_name
        )
        SELECT
          (SELECT COUNT(*) FROM cust_last)                                          AS cust_total,
          (SELECT COUNT(*) FROM cust_last WHERE (CURRENT_DATE - last_load) > 30)    AS cust_attr,
          (SELECT COUNT(*) FROM lane_last)                                          AS lane_total,
          (SELECT COUNT(*) FROM lane_last WHERE (CURRENT_DATE - last_load) > 30)    AS lane_attr
    """

    # ---- Billing (Bruno round 2026-07-01 R12) — bill_date on v4 + dest_actual_
    # departure/arrival from customer_windows (same sources as By Order R11, so
    # the panel reconciles with the Days-to-Bill column). See _bill_sql().
    bill_params: list = []
    where_bill = _v4_scope_where("br4", team, customer, load_type, bill_params, lanes, exclude_lanes)
    bill_params.extend([s, e])
    b_s = len(bill_params) - 1
    b_e = len(bill_params)
    bill_sql = _bill_metrics_sql(where_bill, b_s, b_e, group_by_team=False)

    prod_row, sav_row, attr_row, bill_row = await asyncio.gather(
        pool.fetchrow(prod_sql, *prod_params),
        pool.fetchrow(sav_sql, *sav_params),
        pool.fetchrow(attr_sql, *attr_params),
        pool.fetchrow(bill_sql, *bill_params),
    )

    revenue = _safe_float(prod_row["revenue"])
    profit  = _safe_float(prod_row["profit"])
    volume  = int(prod_row["volume"] or 0)
    team_count = int(prod_row["team_count"] or 0) or (1 if team else len(CORP_TEAMS))
    capacity = 500 * team_count
    otp_late = int(prod_row["otp_late_sum"] or 0)
    otd_late = int(prod_row["otd_late_sum"] or 0)
    cust_total = int(attr_row["cust_total"] or 0)
    lane_total = int(attr_row["lane_total"] or 0)

    return {
        "success": True,
        "data": {
            "customers":  int(prod_row["customers"] or 0),
            "lanes":      int(prod_row["lanes"] or 0),
            "volume":     volume,
            "revenue":    revenue,
            "total_cost": _safe_float(prod_row["total_cost"]),
            "profit":     profit,
            "margin_pct": (profit / revenue * 100.0) if revenue else 0.0,
            "rev_x_l":    (revenue / volume) if volume else 0.0,
            "prof_x_l":   (profit  / volume) if volume else 0.0,
            "team_ut":    (volume / capacity * 100.0) if capacity else 0.0,
            "otp_pct":    (1.0 - otp_late / volume) * 100.0 if volume else 0.0,
            "lates_pu":   otp_late,
            "otd_pct":    (1.0 - otd_late / volume) * 100.0 if volume else 0.0,
            "lates_del":  otd_late,
            "savings":    _safe_float(sav_row["total_savings"]),
            "over_pay":   _safe_float(sav_row["total_overpay"]),
            "net_savings": _safe_float(sav_row["net_savings"]),
            "loss_loads":  int(prod_row["loss_loads"] or 0),
            "profit_loss": _safe_float(prod_row["profit_loss"]),
            # Bruno round (2026-07-01) R12 — below Profit Loss.
            **_bill_fields(bill_row),
            "cust_attr_pct": (int(attr_row["cust_attr"] or 0) / cust_total * 100.0) if cust_total else 0.0,
            "lane_attr_pct": (int(attr_row["lane_attr"] or 0) / lane_total * 100.0) if lane_total else 0.0,
            "window": {"start": s.isoformat(), "end": e.isoformat()},
        },
    }


# ---------------------------------------------------------------------------
# /team-projection — §6 single-row team rolling 14d projection (ignores Date)
# ---------------------------------------------------------------------------


@router.get("/team-projection")
async def team_projection(
    request: Request,
    team: Optional[str] = Query(None),
    customer: Optional[str] = Query(None),
    load_type: Optional[str] = Query(None),
    lanes: Optional[List[str]] = Query(None),
    exclude_lanes: Optional[List[str]] = Query(None),
    _user: dict = Depends(require_report_access("ops-portal-overview")),
):
    """§6 Team Monthly Projection — last 12 Mon-Sat business days extrapolated to EoM.

    Bruno round-2 (2026-05-13): switched divisor from 14 calendar days to
    12 business days (Mon-Sat). The SQL still scans a calendar window
    ending yesterday, but filters out Sundays so the divisor is exact.

    Date filter intentionally ignored (projection always uses the rolling
    business-day window). Team + Customer apply.
    """
    pool = get_datalake_gold_pool(request)
    today = cst_today()
    m_start, m_end = _month_bounds(today)
    win_start = _last_n_business_days_start(today, 12)
    win_end = today - timedelta(days=1)
    pending_workdays = _count_workdays(today, m_end)

    params: list = []
    where = _v4_scope_where("br4", team, customer, load_type, params, lanes, exclude_lanes)
    params.extend([win_start, win_end, m_start, win_end, m_start, m_end])
    p_ws = len(params) - 5
    p_we = len(params) - 4
    p_ms1  = len(params) - 3
    p_we2  = len(params) - 2
    p_ms2  = len(params) - 1
    p_me   = len(params)

    # Bruno's "last 12 business days" = Mon-Sat only; EXTRACT(DOW)=0 is Sunday.
    row = await pool.fetchrow(
        f"""
        SELECT
          COUNT(*) FILTER (WHERE br4.origin_actual_departure::date BETWEEN ${p_ws} AND ${p_we}
                             AND EXTRACT(DOW FROM br4.origin_actual_departure::date) <> 0
                             AND br4.total_charge IS NOT NULL
                             AND br4.total_charge <> 0) AS vol_12,
          COALESCE(SUM(CASE WHEN br4.origin_actual_departure::date BETWEEN ${p_ws} AND ${p_we}
                              AND EXTRACT(DOW FROM br4.origin_actual_departure::date) <> 0
                            THEN br4.total_charge END), 0)::numeric AS rev_12,
          COALESCE(SUM(CASE WHEN br4.origin_actual_departure::date BETWEEN ${p_ws} AND ${p_we}
                              AND EXTRACT(DOW FROM br4.origin_actual_departure::date) <> 0
                            THEN br4.margin_amt END), 0)::numeric AS prof_12,
          COUNT(*) FILTER (WHERE br4.origin_actual_departure::date BETWEEN ${p_ms1} AND ${p_we2}
                             AND br4.total_charge IS NOT NULL
                             AND br4.total_charge <> 0) AS vol_mtd,
          COALESCE(SUM(CASE WHEN br4.origin_actual_departure::date BETWEEN ${p_ms2} AND ${p_me}
                            THEN br4.total_charge END), 0)::numeric AS rev_mtd,
          COALESCE(SUM(CASE WHEN br4.origin_actual_departure::date BETWEEN ${p_ms2} AND ${p_me}
                            THEN br4.margin_amt END), 0)::numeric AS prof_mtd,
          COUNT(DISTINCT br4.team_id) AS team_count
        FROM public.mcleod_gld_budget_report_v4 br4
        WHERE {where}
        """,
        *params,
    )

    avg_vol_day  = _safe_float(row["vol_12"]) / 12.0
    avg_rev_day  = _safe_float(row["rev_12"]) / 12.0
    avg_prof_day = _safe_float(row["prof_12"]) / 12.0

    proj_volume = avg_vol_day * pending_workdays + _safe_float(row["vol_mtd"])
    proj_revenue = avg_rev_day * pending_workdays + _safe_float(row["rev_mtd"])
    proj_profit  = avg_prof_day * pending_workdays + _safe_float(row["prof_mtd"])
    team_count = int(row["team_count"] or 0) or (1 if team else len(CORP_TEAMS))

    return {
        "success": True,
        "data": {
            "avg_vol_day":  _safe_float(avg_vol_day),
            "avg_rev_day":  _safe_float(avg_rev_day),
            "avg_prof_day": _safe_float(avg_prof_day),
            "pending_workdays": pending_workdays,
            "proj_volume":  _safe_float(proj_volume),
            "proj_revenue": _safe_float(proj_revenue),
            "proj_profit":  _safe_float(proj_profit),
            "proj_margin_pct": (proj_profit / proj_revenue * 100.0) if proj_revenue else 0.0,
            "proj_rev_x_l":  (proj_revenue / proj_volume) if proj_volume else 0.0,
            "proj_prof_x_l": (proj_profit  / proj_volume) if proj_volume else 0.0,
            "proj_team_ut":  (proj_volume / (500.0 * team_count) * 100.0) if team_count else 0.0,
            "today": today.isoformat(),
            "month_start": m_start.isoformat(),
            "month_end": m_end.isoformat(),
        },
    }


# ---------------------------------------------------------------------------
# /profit-tm-gauge — bottom-middle Profit-TM gauge (MTD profit vs budget)
# ---------------------------------------------------------------------------


@router.get("/profit-tm-gauge")
async def profit_tm_gauge(
    request: Request,
    team: Optional[str] = Query(None),
    customer: Optional[str] = Query(None),
    load_type: Optional[str] = Query(None),
    lanes: Optional[List[str]] = Query(None),
    exclude_lanes: Optional[List[str]] = Query(None),
    _user: dict = Depends(require_report_access("ops-portal-overview")),
):
    """Horizontal gauge under the chart. Always current month MTD."""
    pool = get_datalake_gold_pool(request)
    today = cst_today()
    m_start, m_end = _month_bounds(today)

    # Production MTD profit
    p_params: list = []
    where = _v4_scope_where("br4", team, customer, load_type, p_params, lanes, exclude_lanes)
    p_params.extend([m_start, today])
    p_s = len(p_params) - 1
    p_e = len(p_params)
    prod_sql = f"""
        SELECT COALESCE(SUM(br4.margin_amt), 0)::numeric AS profit_mtd
        FROM public.mcleod_gld_budget_report_v4 br4
        WHERE {where}
          AND br4.origin_actual_departure >= ${p_s}
          AND br4.origin_actual_departure < (${p_e}::date + INTERVAL '1 day')
    """

    # Budget MTD profit (target)
    b_params: list = [m_start, m_end]
    b_extra = ""
    if team:
        b_params.append(team)
        b_extra += f" AND ct.team_id = ${len(b_params)}"
    if customer:
        b_params.append(customer)
        b_extra += f' AND budget."Customer Name" = ${len(b_params)}'
    bud_sql = f"""
        WITH {CUSTOMER_TEAM_CTE}
        SELECT COALESCE(SUM(budget."Profit Budget"), 0)::numeric AS profit_budget
        FROM public.daily_production_budget_report budget
        JOIN customer_team ct ON TRIM(budget."Customer Name") = ct.customer_name
        WHERE budget."Date" BETWEEN $1 AND $2
        {b_extra}
    """

    prod_val, bud_val = await asyncio.gather(
        pool.fetchval(prod_sql, *p_params),
        pool.fetchval(bud_sql, *b_params),
    )
    profit_mtd = _safe_float(prod_val)
    profit_budget = _safe_float(bud_val)
    return {
        "success": True,
        "data": {
            "profit_mtd": profit_mtd,
            "profit_budget": profit_budget,
            "pct_of_budget": (profit_mtd / profit_budget * 100.0) if profit_budget else 0.0,
            "month_start": m_start.isoformat(),
            "month_end": m_end.isoformat(),
        },
    }


# ---------------------------------------------------------------------------
# /actuals — bottom Actuals per-customer roll-up
# ---------------------------------------------------------------------------


@router.get("/actuals")
async def actuals(
    request: Request,
    range: Optional[str] = Query("mtd"),
    start_date: Optional[date] = Query(None),
    end_date: Optional[date] = Query(None),
    team: Optional[str] = Query(None),
    customer: Optional[str] = Query(None),
    load_type: Optional[str] = Query(None),
    lanes: Optional[List[str]] = Query(None),
    exclude_lanes: Optional[List[str]] = Query(None),
    sort: str = Query("revenue_desc"),
    limit: int = Query(100, ge=1, le=500),
    losses_only: bool = Query(False),
    unbilled_only: bool = Query(False),
    _user: dict = Depends(require_report_access("ops-portal-overview")),
):
    """Bottom Actuals table — per customer, stacked Production / Budget / Variance.

    Variance convention here is ``actual − budget`` (matches the Kohler MTY
    mock 133/153/-20 in Bruno's PDF). Different sign from §2/§3 — that's what
    the spec literally shows.

    Production columns come from v4 (sargable date-decode clamp on the per-row
    date columns is unnecessary because we don't return any). Budget columns
    come from daily_production_budget_report joined per customer.
    """
    pool = get_datalake_gold_pool(request)
    s, e = _resolve_range(range, start_date, end_date)
    today = cst_today()
    m_start, m_end = _month_bounds(today)
    pending_workdays = _count_workdays(today, m_end)

    # ---- Production per customer ----------------------------------------
    # Bruno R5 (2026-06-01): "Losses" button → restrict to margin_amt < 0 rows.
    # Bruno (PDF 2026-07-13): "Unbilled" button → bill_date < sentinel (never
    # billed). ANDs with Losses when both are on.
    losses_clause = " AND br4.margin_amt < 0" if losses_only else ""
    unbilled_clause = " AND br4.bill_date < '2000-01-01'::date" if unbilled_only else ""
    p_params: list = []
    where = _v4_scope_where("br4", team, customer, load_type, p_params, lanes, exclude_lanes)
    p_params.extend([s, e])
    p_s = len(p_params) - 1
    p_e = len(p_params)
    prod_sql = f"""
        WITH otp AS ({_scorecard_cte("otp")}),
             otd AS ({_scorecard_cte("otd")}),
             prod AS (
                SELECT br4.customer_name,
                       br4.id, br4.company_id, br4.total_charge, br4.margin_amt,
                       COALESCE(otp.scorecard_count_otp, 0) AS otp_cnt,
                       COALESCE(otd.scorecard_count_otd, 0) AS otd_cnt
                FROM public.mcleod_gld_budget_report_v4 br4
                LEFT JOIN otp ON TRIM(br4.id)=otp.id_key AND TRIM(br4.company_id)=otp.company_id_key
                LEFT JOIN otd ON TRIM(br4.id)=otd.id_key AND TRIM(br4.company_id)=otd.company_id_key
                WHERE {where}
                  AND br4.origin_actual_departure >= ${p_s}
                  AND br4.origin_actual_departure < (${p_e}::date + INTERVAL '1 day')
                  {losses_clause}
                  {unbilled_clause}
             )
        SELECT
          customer_name,
          COUNT(*) FILTER (WHERE total_charge IS NOT NULL AND total_charge <> 0) AS vol,
          COALESCE(SUM(total_charge), 0)::numeric AS rev,
          COALESCE(SUM(margin_amt),  0)::numeric AS prof,
          SUM(otp_cnt) AS otp_late,
          SUM(otd_cnt) AS otd_late
        FROM prod
        GROUP BY customer_name
    """

    # ---- Budget per customer --------------------------------------------
    b_params: list = [s, e]
    b_extra = ""
    if team:
        b_params.append(team)
        b_extra += f" AND ct.team_id = ${len(b_params)}"
    if customer:
        b_params.append(customer)
        b_extra += f' AND budget."Customer Name" = ${len(b_params)}'
    bud_sql = f"""
        WITH {CUSTOMER_TEAM_CTE}
        SELECT
          budget."Customer Name" AS customer_name,
          COALESCE(SUM(budget."Loads Budget"),    0)::numeric AS vol_budget,
          COALESCE(SUM(budget."Revenue Budget"),  0)::numeric AS rev_budget,
          COALESCE(SUM(budget."Profit Budget"),   0)::numeric AS prof_budget
        FROM public.daily_production_budget_report budget
        JOIN customer_team ct ON TRIM(budget."Customer Name") = ct.customer_name
        WHERE budget."Date" BETWEEN $1 AND $2
        {b_extra}
        GROUP BY budget."Customer Name"
    """

    prod_rows, bud_rows = await asyncio.gather(
        pool.fetch(prod_sql, *p_params),
        pool.fetch(bud_sql, *b_params),
    )

    bud_map = {r["customer_name"]: r for r in bud_rows}
    # Bruno R4 (2026-05-27): totals row at top of the table. Accumulate over the
    # full filtered set (before the limit slice) so totals stay accurate.
    tot = {"vol": 0, "rev": 0.0, "prof": 0.0, "vol_b": 0.0, "rev_b": 0.0,
           "prof_b": 0.0, "otp_late": 0, "otd_late": 0}
    out = []
    for r in prod_rows:
        name = r["customer_name"]
        b = bud_map.pop(name, None)
        vol = int(r["vol"] or 0)
        rev = _safe_float(r["rev"])
        prof = _safe_float(r["prof"])
        otp_late = int(r["otp_late"] or 0)
        otd_late = int(r["otd_late"] or 0)
        vol_budget = _safe_float(b["vol_budget"]) if b else 0.0
        rev_budget = _safe_float(b["rev_budget"]) if b else 0.0
        prof_budget = _safe_float(b["prof_budget"]) if b else 0.0
        tot["vol"] += vol; tot["rev"] += rev; tot["prof"] += prof
        tot["vol_b"] += vol_budget; tot["rev_b"] += rev_budget; tot["prof_b"] += prof_budget
        tot["otp_late"] += otp_late; tot["otd_late"] += otd_late
        margin_pct = (prof / rev * 100.0) if rev else 0.0
        margin_budget_pct = (prof_budget / rev_budget * 100.0) if rev_budget else 0.0
        # Vol×Day, Prof×Day → 14-day average (Bruno: "/14"). Honors filtered window.
        vol_x_day = vol / 14.0
        prof_x_day = prof / 14.0
        # Projected EoM = (avg per day × pending workdays) + actual
        proj_vol = vol_x_day * pending_workdays + vol
        proj_prof = prof_x_day * pending_workdays + prof
        out.append({
            "customer_name": name,
            "vol": vol,
            "vol_budget": vol_budget,
            "vol_var": vol - vol_budget,  # actual − budget
            "rev": rev,
            "rev_budget": rev_budget,
            "rev_var": rev - rev_budget,
            "prof": prof,
            "prof_budget": prof_budget,
            "prof_var": prof - prof_budget,
            "margin_pct": _safe_float(margin_pct),
            "margin_budget_pct": _safe_float(margin_budget_pct),
            "margin_var_pct": _safe_float(margin_pct - margin_budget_pct),
            "otp_pct": (1.0 - otp_late / vol) * 100.0 if vol else 0.0,
            "otd_pct": (1.0 - otd_late / vol) * 100.0 if vol else 0.0,
            "rev_x_l":  (rev / vol) if vol else 0.0,
            "prof_x_l": (prof / vol) if vol else 0.0,
            "vol_x_day": _safe_float(vol_x_day),
            "prof_x_day": _safe_float(prof_x_day),
            "proj_eom_vol":  _safe_float(proj_vol),
            "proj_eom_prof": _safe_float(proj_prof),
        })

    # Customers in budget but with zero production — surface them so the
    # variance row still shows the gap. Skipped under the Losses / Unbilled
    # filters (zero-production customers have no margin<0 / unbilled loads).
    for name, b in ({} if (losses_only or unbilled_only) else bud_map).items():
        vol_budget = _safe_float(b["vol_budget"])
        rev_budget = _safe_float(b["rev_budget"])
        prof_budget = _safe_float(b["prof_budget"])
        tot["vol_b"] += vol_budget; tot["rev_b"] += rev_budget; tot["prof_b"] += prof_budget
        out.append({
            "customer_name": name,
            "vol": 0, "vol_budget": vol_budget, "vol_var": -vol_budget,
            "rev": 0.0, "rev_budget": rev_budget, "rev_var": -rev_budget,
            "prof": 0.0, "prof_budget": prof_budget, "prof_var": -prof_budget,
            "margin_pct": 0.0,
            "margin_budget_pct": (prof_budget / rev_budget * 100.0) if rev_budget else 0.0,
            "margin_var_pct": -((prof_budget / rev_budget * 100.0) if rev_budget else 0.0),
            "otp_pct": 0.0, "otd_pct": 0.0,
            "rev_x_l": 0.0, "prof_x_l": 0.0,
            "vol_x_day": 0.0, "prof_x_day": 0.0,
            "proj_eom_vol": 0.0, "proj_eom_prof": 0.0,
        })

    sort_key = {
        "revenue_desc":  lambda r: -r["rev"],
        "profit_desc":   lambda r: -r["prof"],
        "volume_desc":   lambda r: -r["vol"],
        "customer":      lambda r: (r["customer_name"] or "").upper(),
        "loss_desc":     lambda r: r["prof"],  # most negative profit first
    }.get(sort, lambda r: -r["rev"])
    full_total = len(out)
    out.sort(key=sort_key)
    out = out[:limit]

    t_vol, t_rev, t_prof = tot["vol"], tot["rev"], tot["prof"]
    t_vol_b, t_rev_b, t_prof_b = tot["vol_b"], tot["rev_b"], tot["prof_b"]
    totals = {
        "vol": t_vol, "vol_budget": _safe_float(t_vol_b), "vol_var": t_vol - t_vol_b,
        "rev": _safe_float(t_rev), "rev_budget": _safe_float(t_rev_b), "rev_var": _safe_float(t_rev - t_rev_b),
        "prof": _safe_float(t_prof), "prof_budget": _safe_float(t_prof_b), "prof_var": _safe_float(t_prof - t_prof_b),
        "margin_pct": _safe_float((t_prof / t_rev * 100.0) if t_rev else 0.0),
        "margin_budget_pct": _safe_float((t_prof_b / t_rev_b * 100.0) if t_rev_b else 0.0),
        "otp_pct": _safe_float((1.0 - tot["otp_late"] / t_vol) * 100.0 if t_vol else 0.0),
        "otd_pct": _safe_float((1.0 - tot["otd_late"] / t_vol) * 100.0 if t_vol else 0.0),
        "rev_x_l": _safe_float((t_rev / t_vol) if t_vol else 0.0),
        "prof_x_l": _safe_float((t_prof / t_vol) if t_vol else 0.0),
    }
    totals["margin_var_pct"] = _safe_float(totals["margin_pct"] - totals["margin_budget_pct"])

    return {
        "success": True,
        "data": out,
        "meta": {
            "window": {"start": s.isoformat(), "end": e.isoformat()},
            "pending_workdays": pending_workdays,
            "total": full_total,
            "totals": totals,
        },
    }


# ---------------------------------------------------------------------------
# /actuals-by-lane — Bruno round 3 (2026-05-19) Production-only per-lane roll-up
# ---------------------------------------------------------------------------


@router.get("/actuals-by-lane")
async def actuals_by_lane(
    request: Request,
    range: Optional[str] = Query("mtd"),
    start_date: Optional[date] = Query(None),
    end_date: Optional[date] = Query(None),
    team: Optional[str] = Query(None),
    customer: Optional[str] = Query(None),
    load_type: Optional[str] = Query(None),
    lanes: Optional[List[str]] = Query(None),
    exclude_lanes: Optional[List[str]] = Query(None),
    sort: str = Query("revenue_desc"),
    limit: int = Query(100, ge=1, le=500),
    losses_only: bool = Query(False),
    unbilled_only: bool = Query(False),
    _user: dict = Depends(require_report_access("ops-portal-overview")),
):
    """Second table below Actuals — Production data only, grouped by lane.

    Lane key = ``TRIM(origin_name) || ' - ' || TRIM(dest_name)`` (city-pair —
    same shape as XRay CORP / Top Losses Lanes so the count matches §5).
    No Budget join — Bruno's spec: "second table … just with Production Data".
    """
    pool = get_datalake_gold_pool(request)
    s, e = _resolve_range(range, start_date, end_date)
    # Bruno R5 (2026-06-01): "Losses" button → restrict to margin_amt < 0 rows.
    # Bruno (PDF 2026-07-13): "Unbilled" button → bill_date < sentinel.
    losses_clause = " AND br4.margin_amt < 0" if losses_only else ""
    unbilled_clause = " AND br4.bill_date < '2000-01-01'::date" if unbilled_only else ""

    p_params: list = []
    where = _v4_scope_where("br4", team, customer, load_type, p_params, lanes, exclude_lanes)
    p_params.extend([s, e])
    p_s = len(p_params) - 1
    p_e = len(p_params)

    sql = f"""
        WITH otp AS ({_scorecard_cte("otp")}),
             otd AS ({_scorecard_cte("otd")}),
             prod AS (
                SELECT
                    TRIM(br4.origin_name) AS origin,
                    TRIM(br4.dest_name)   AS dest,
                    br4.id, br4.company_id,
                    br4.total_charge, br4.margin_amt,
                    -- Bruno round (2026-07-01) R3: carrier per order (first movement).
                    NULLIF(TRIM(mov.payee_name), '') AS carrier,
                    COALESCE(otp.scorecard_count_otp, 0) AS otp_cnt,
                    COALESCE(otd.scorecard_count_otd, 0) AS otd_cnt
                FROM public.mcleod_gld_budget_report_v4 br4
                LEFT JOIN otp ON TRIM(br4.id)=otp.id_key AND TRIM(br4.company_id)=otp.company_id_key
                LEFT JOIN otd ON TRIM(br4.id)=otd.id_key AND TRIM(br4.company_id)=otd.company_id_key
                LEFT JOIN LATERAL (
                    SELECT m.payee_name
                    FROM public.mcleod_gld_movement m
                    WHERE m.order_id = br4.id AND m.company_id = br4.company_id
                    ORDER BY m.movement_id ASC
                    LIMIT 1
                ) mov ON TRUE
                WHERE {where}
                  AND br4.origin_actual_departure >= ${p_s}
                  AND br4.origin_actual_departure < (${p_e}::date + INTERVAL '1 day')
                  AND TRIM(br4.origin_name) <> ''
                  AND TRIM(br4.dest_name)   <> ''
                  {losses_clause}
                  {unbilled_clause}
             ),
             uni AS (SELECT COUNT(DISTINCT carrier) AS n_carriers_total FROM prod)
        SELECT
          origin || ' - ' || dest AS lane,
          origin,
          dest,
          COUNT(*) FILTER (WHERE total_charge IS NOT NULL AND total_charge <> 0) AS vol,
          COUNT(DISTINCT carrier) AS n_carriers,
          MAX(uni.n_carriers_total) AS n_carriers_total,
          COALESCE(SUM(total_charge), 0)::numeric AS rev,
          COALESCE(SUM(margin_amt),  0)::numeric  AS prof,
          COUNT(*) FILTER (WHERE margin_amt < 0
                             AND total_charge IS NOT NULL
                             AND total_charge <> 0) AS loss_loads,
          COALESCE(SUM(margin_amt) FILTER (WHERE margin_amt < 0), 0)::numeric AS loss_profit,
          SUM(otp_cnt) AS otp_late,
          SUM(otd_cnt) AS otd_late
        FROM prod CROSS JOIN uni
        GROUP BY origin, dest
    """

    rows = await pool.fetch(sql, *p_params)
    # Bruno R4 (2026-05-27): totals row at top — accumulate over the full set.
    tot = {"vol": 0, "rev": 0.0, "prof": 0.0, "loss_loads": 0, "loss_profit": 0.0,
           "otp_late": 0, "otd_late": 0}
    out = []
    for r in rows:
        vol = int(r["vol"] or 0)
        rev = _safe_float(r["rev"])
        prof = _safe_float(r["prof"])
        otp_late = int(r["otp_late"] or 0)
        otd_late = int(r["otd_late"] or 0)
        tot["vol"] += vol; tot["rev"] += rev; tot["prof"] += prof
        tot["loss_loads"] += int(r["loss_loads"] or 0)
        tot["loss_profit"] += _safe_float(r["loss_profit"])
        tot["otp_late"] += otp_late; tot["otd_late"] += otd_late
        out.append({
            "lane":       r["lane"],
            "origin":     r["origin"],
            "dest":       r["dest"],
            "vol":        vol,
            "carriers":   int(r["n_carriers"] or 0),
            "rev":        rev,
            "prof":       prof,
            "margin_pct": (prof / rev * 100.0) if rev else 0.0,
            "loss_loads":  int(r["loss_loads"] or 0),
            "loss_profit": _safe_float(r["loss_profit"]),
            "otp_pct":    (1.0 - otp_late / vol) * 100.0 if vol else 0.0,
            "otd_pct":    (1.0 - otd_late / vol) * 100.0 if vol else 0.0,
            "rev_x_l":    (rev / vol) if vol else 0.0,
            "prof_x_l":   (prof / vol) if vol else 0.0,
        })

    sort_key = {
        "revenue_desc": lambda r: -r["rev"],
        "profit_desc":  lambda r: -r["prof"],
        "volume_desc":  lambda r: -r["vol"],
        "loss_desc":    lambda r: r["prof"],   # most negative first
        "lane":         lambda r: (r["lane"] or "").upper(),
        "margin_desc":  lambda r: -r["margin_pct"],
    }.get(sort, lambda r: -r["rev"])
    full_total = len(out)
    out.sort(key=sort_key)
    out = out[:limit]

    t_vol, t_rev, t_prof = tot["vol"], tot["rev"], tot["prof"]
    # Universe-wide distinct carrier count (same scalar on every row via uni CTE).
    carriers_total = int(rows[0]["n_carriers_total"] or 0) if rows else 0
    totals = {
        "vol": t_vol,
        "carriers": carriers_total,
        "rev": _safe_float(t_rev),
        "prof": _safe_float(t_prof),
        "margin_pct": _safe_float((t_prof / t_rev * 100.0) if t_rev else 0.0),
        "loss_loads": tot["loss_loads"],
        "loss_profit": _safe_float(tot["loss_profit"]),
        "otp_pct": _safe_float((1.0 - tot["otp_late"] / t_vol) * 100.0 if t_vol else 0.0),
        "otd_pct": _safe_float((1.0 - tot["otd_late"] / t_vol) * 100.0 if t_vol else 0.0),
        "rev_x_l": _safe_float((t_rev / t_vol) if t_vol else 0.0),
        "prof_x_l": _safe_float((t_prof / t_vol) if t_vol else 0.0),
    }

    return {
        "success": True,
        "data": out,
        "meta": {
            "window": {"start": s.isoformat(), "end": e.isoformat()},
            "total": full_total,
            "totals": totals,
        },
    }


# ---------------------------------------------------------------------------
# /service — Bruno R4 (2026-05-27) per-bucket OTP / OTD time series
# ---------------------------------------------------------------------------


@router.get("/service")
async def service(
    request: Request,
    team: Optional[str] = Query(None),
    customer: Optional[str] = Query(None),
    load_type: Optional[str] = Query(None),
    lanes: Optional[List[str]] = Query(None),
    exclude_lanes: Optional[List[str]] = Query(None),
    grain: str = Query("month", description="'day' | 'week' | 'month'"),
    _user: dict = Depends(require_report_access("ops-portal-overview")),
):
    """Second "KPI MANAGEMENT" chart ("Service") — OTP% / OTD% over the grain.

    Same Day/Week/Month window model as /combo. OTP%/OTD% per bucket use the
    same scorecard-late formula as /team-performance:
      otp_pct = (1 - SUM(otp_late) / volume) * 100
    """
    if grain not in ("day", "week", "month"):
        grain = "month"
    pool = get_datalake_gold_pool(request)
    today = cst_today()
    win_start, win_end, anchors = _resolve_grain_window(grain, today)

    trunc_v4 = {
        "day":   "br4.origin_actual_departure::date",
        "week":  "DATE_TRUNC('week', br4.origin_actual_departure)::date",
        "month": "DATE_TRUNC('month', br4.origin_actual_departure)::date",
    }[grain]

    params: list = []
    where = _v4_scope_where("br4", team, customer, load_type, params, lanes, exclude_lanes)
    params.extend([win_start, win_end])
    p_ws = len(params) - 1
    p_we = len(params)
    sql = f"""
        WITH otp AS ({_scorecard_cte("otp")}),
             otd AS ({_scorecard_cte("otd")}),
             prod AS (
                SELECT {trunc_v4} AS bucket_start,
                       br4.total_charge,
                       COALESCE(otp.scorecard_count_otp, 0) AS otp_cnt,
                       COALESCE(otd.scorecard_count_otd, 0) AS otd_cnt
                FROM public.mcleod_gld_budget_report_v4 br4
                LEFT JOIN otp ON TRIM(br4.id)=otp.id_key AND TRIM(br4.company_id)=otp.company_id_key
                LEFT JOIN otd ON TRIM(br4.id)=otd.id_key AND TRIM(br4.company_id)=otd.company_id_key
                WHERE {where}
                  AND br4.origin_actual_departure >= ${p_ws}
                  AND br4.origin_actual_departure < (${p_we}::date + INTERVAL '1 day')
             )
        SELECT
          bucket_start,
          COUNT(*) FILTER (WHERE total_charge IS NOT NULL AND total_charge <> 0) AS volume,
          SUM(otp_cnt) AS otp_late,
          SUM(otd_cnt) AS otd_late
        FROM prod
        GROUP BY bucket_start
    """
    rows = await pool.fetch(sql, *params)
    by_bucket = {r["bucket_start"]: r for r in rows}

    out = []
    for a in anchors:
        r = by_bucket.get(a)
        vol = int(r["volume"]) if r else 0
        otp_late = int(r["otp_late"] or 0) if r else 0
        otd_late = int(r["otd_late"] or 0) if r else 0
        out.append({
            "bucket_start": a.isoformat(),
            "volume": vol,
            "otp_pct": _safe_float((1.0 - otp_late / vol) * 100.0 if vol else 0.0),
            "otd_pct": _safe_float((1.0 - otd_late / vol) * 100.0 if vol else 0.0),
            "lates_pu": otp_late,
            "lates_del": otd_late,
        })

    return {
        "success": True,
        "data": {"grain": grain, "buckets": out, "today": today.isoformat()},
    }


# ---------------------------------------------------------------------------
# /by-order — Bruno R4 (2026-05-27) load-level Production table
# ---------------------------------------------------------------------------

_BY_ORDER_SORTS = {
    "order_asc":     "order_id ASC",
    "order_desc":    "order_id DESC",
    "team_asc":      "team_id ASC, order_id ASC",
    "team_desc":     "team_id DESC, order_id ASC",
    "departure_asc": "br4.origin_actual_departure ASC NULLS LAST",
    "departure_desc": "br4.origin_actual_departure DESC NULLS LAST",
    "customer_asc":  "customer_name ASC, order_id ASC",
    "customer_desc": "customer_name DESC, order_id ASC",
    "lane_asc":      "lane ASC, order_id ASC",
    "lane_desc":     "lane DESC, order_id ASC",
    # Bruno round (2026-07-01) R2: Carrier column (movement.payee_name).
    "carrier_asc":   "carrier ASC, order_id ASC",
    "carrier_desc":  "carrier DESC, order_id ASC",
    "revenue_asc":   "revenue ASC NULLS LAST",
    "revenue_desc":  "revenue DESC NULLS LAST",
    "profit_asc":    "profit ASC NULLS LAST",
    "profit_desc":   "profit DESC NULLS LAST",
    "margin_asc":    "margin ASC NULLS LAST",
    "margin_desc":   "margin DESC NULLS LAST",
    # Bruno R5 (2026-06-01): OTP/OTD/Transit columns (sort by SELECT alias).
    "otp_asc":       "otp_pct ASC, order_id ASC",
    "otp_desc":      "otp_pct DESC, order_id ASC",
    "otd_asc":       "otd_pct ASC, order_id ASC",
    "otd_desc":      "otd_pct DESC, order_id ASC",
    "transit_asc":   "transit_seconds ASC NULLS LAST",
    "transit_desc":  "transit_seconds DESC NULLS LAST",
}


@router.get("/by-order")
async def by_order(
    request: Request,
    range: Optional[str] = Query("mtd"),
    start_date: Optional[date] = Query(None),
    end_date: Optional[date] = Query(None),
    team: Optional[str] = Query(None),
    customer: Optional[str] = Query(None),
    load_type: Optional[str] = Query(None),
    lanes: Optional[List[str]] = Query(None),
    exclude_lanes: Optional[List[str]] = Query(None),
    sort: str = Query("revenue_desc"),
    limit: int = Query(500, ge=1, le=2000),
    losses_only: bool = Query(False),
    unbilled_only: bool = Query(False),
    _user: dict = Depends(require_report_access("ops-portal-overview")),
):
    """Load-level Production table (one row per order).

    Columns per Bruno's R4 PDF:
      Order=id · Team=team_id · Departure=origin_actual_departure ·
      Customer=customer_name · Lane=origin_name - dest_name ·
      Revenue=total_charge · Profit=margin_amt · Margin=margin_amt/total_charge.

    Bruno R5 (2026-06-01) added:
      - OTP % / OTD %  → per-order on-time flag from mcleod_gld_scorecard
        (0 late stops → 100%, else 0%; same code list as the §5 panel).
      - Transit Time   → dest_actual_arrival − orig_actual_departure from
        public.mcleod_gld_customer_windows (joined on id; the PDF's
        "origin_actual_departure − dest_actual_arrival" is reversed — we
        compute arrival − departure so the duration is positive).
      - In-progress timer → for status 'P' loads with no arrival yet, the UI
        ticks now() − departed_at; the backend hands back ``departed_at`` and
        the ``in_progress`` flag.
      - "Losses" button → ``losses_only`` restricts to margin_amt < 0.

    Server-side sort on every column (the set is load-level, so a client-side
    sort of the fetched page could mis-rank). Totals are computed over the
    full filtered set in ``meta`` regardless of the limit slice.

    All window timestamps are emitted via ``to_char`` (text) to dodge the
    asyncpg date-decode overflow on any 5-digit-year McLeod typo
    (SPEC-CODE-RULES §4). The customer_windows join is a correlated LATERAL that
    MAXes the (sentinel-guarded) departure/arrival per id — backed by the
    functional index ``idx_customer_windows_id_upper`` on ``TRIM(UPPER(id))``
    (created 2026-06-02). The aggregate (not LIMIT 1) keeps the original
    MAX-of-non-sentinel semantics so a 1900 placeholder row never wins, and the
    single-row aggregate can't fan out the order list. Replaces the prior
    full-table pre-agg CTE that scanned all ~195k window rows every call
    (SPEC-CODE-RULES §42 chose that only because the index was missing).
    Sentinel 1900/1899 placeholder dates are guarded to NULL.
    """
    pool = get_datalake_gold_pool(request)
    s, e = _resolve_range(range, start_date, end_date)
    order_by = _BY_ORDER_SORTS.get(sort, _BY_ORDER_SORTS["revenue_desc"])
    losses_clause = " AND br4.margin_amt < 0" if losses_only else ""
    # Bruno (PDF 2026-07-13): "Unbilled" button → bill_date < sentinel.
    unbilled_clause = " AND br4.bill_date < '2000-01-01'::date" if unbilled_only else ""

    rows_params: list = []
    where_rows = _v4_scope_where("br4", team, customer, load_type, rows_params, lanes, exclude_lanes)
    rows_params.extend([s, e, limit])
    p_s = len(rows_params) - 2
    p_e = len(rows_params) - 1
    p_lim = len(rows_params)
    rows_sql = f"""
        WITH otp AS ({_scorecard_cte("otp")}),
             otd AS ({_scorecard_cte("otd")})
        SELECT
          TRIM(br4.id)        AS order_id,
          TRIM(br4.team_id)   AS team_id,
          TRIM(br4.status)    AS status,
          to_char(br4.origin_actual_departure, 'YYYY-MM-DD') AS departure,
          br4.customer_name   AS customer_name,
          COALESCE(TRIM(mov.payee_name), '') AS carrier,
          NULLIF(TRIM(COALESCE(br4.origin_name,'')) || ' - ' || TRIM(COALESCE(br4.dest_name,'')), ' - ') AS lane,
          COALESCE(br4.total_charge, 0)::numeric AS revenue,
          COALESCE(br4.margin_amt, 0)::numeric   AS profit,
          CASE WHEN br4.total_charge IS NOT NULL AND br4.total_charge <> 0
               THEN br4.margin_amt / br4.total_charge * 100.0 ELSE 0 END AS margin,
          CASE WHEN COALESCE(otp.scorecard_count_otp, 0) = 0 THEN 100.0 ELSE 0.0 END AS otp_pct,
          CASE WHEN COALESCE(otd.scorecard_count_otd, 0) = 0 THEN 100.0 ELSE 0.0 END AS otd_pct,
          to_char(win.dep_ts, 'YYYY-MM-DD"T"HH24:MI:SS') AS departed_at,
          to_char(win.arr_ts, 'YYYY-MM-DD"T"HH24:MI:SS') AS arrived_at,
          CASE WHEN win.dep_ts IS NOT NULL AND win.arr_ts IS NOT NULL AND win.arr_ts > win.dep_ts
               THEN EXTRACT(EPOCH FROM (win.arr_ts - win.dep_ts)) END AS transit_seconds,
          -- Bruno round (2026-07-01) R11: Bill checkmark + Days to Bill.
          (br4.bill_date > '2000-01-01'::date) AS billed,
          CASE
            WHEN win.dest_dep_ts IS NULL THEN NULL
            WHEN br4.bill_date > '2000-01-01'::date
                 THEN (br4.bill_date::date - win.dest_dep_ts::date)
            ELSE (CURRENT_DATE - win.dest_dep_ts::date)
          END AS days_to_bill
        FROM public.mcleod_gld_budget_report_v4 br4
        LEFT JOIN otp ON TRIM(br4.id)=otp.id_key AND TRIM(br4.company_id)=otp.company_id_key
        LEFT JOIN otd ON TRIM(br4.id)=otd.id_key AND TRIM(br4.company_id)=otd.company_id_key
        LEFT JOIN LATERAL (
            SELECT MAX(CASE WHEN cw.orig_actual_departure > '2000-01-01' THEN cw.orig_actual_departure END) AS dep_ts,
                   MAX(CASE WHEN cw.dest_actual_arrival   > '2000-01-01' THEN cw.dest_actual_arrival   END) AS arr_ts,
                   MAX(CASE WHEN cw.dest_actual_departure > '2000-01-01' THEN cw.dest_actual_departure END) AS dest_dep_ts
            FROM public.mcleod_gld_customer_windows cw
            WHERE TRIM(UPPER(cw.id)) = TRIM(UPPER(br4.id))
        ) win ON TRUE
        LEFT JOIN LATERAL (
            SELECT m.payee_name
            FROM public.mcleod_gld_movement m
            WHERE m.order_id = br4.id AND m.company_id = br4.company_id
            ORDER BY m.movement_id ASC
            LIMIT 1
        ) mov ON TRUE
        WHERE {where_rows}
          AND br4.origin_actual_departure >= ${p_s}
          AND br4.origin_actual_departure < (${p_e}::date + INTERVAL '1 day')
          {losses_clause}
          {unbilled_clause}
        ORDER BY {order_by}
        LIMIT ${p_lim}
    """

    tot_params: list = []
    where_tot = _v4_scope_where("br4", team, customer, load_type, tot_params, lanes, exclude_lanes)
    tot_params.extend([s, e])
    t_s = len(tot_params) - 1
    t_e = len(tot_params)
    tot_sql = f"""
        SELECT
          COUNT(*)                               AS n_orders,
          COALESCE(SUM(br4.total_charge), 0)::numeric AS rev,
          COALESCE(SUM(br4.margin_amt), 0)::numeric   AS prof
        FROM public.mcleod_gld_budget_report_v4 br4
        WHERE {where_tot}
          AND br4.origin_actual_departure >= ${t_s}
          AND br4.origin_actual_departure < (${t_e}::date + INTERVAL '1 day')
          {losses_clause}
          {unbilled_clause}
    """

    rows, tot_row = await asyncio.gather(
        pool.fetch(rows_sql, *rows_params),
        pool.fetchrow(tot_sql, *tot_params),
    )

    out = []
    for r in rows:
        departed_at = r["departed_at"]
        arrived_at = r["arrived_at"]
        status = (r["status"] or "").strip().upper()
        # In transit = open 'P' load that departed but hasn't arrived yet.
        in_progress = status == "P" and not arrived_at and bool(departed_at)
        ts = r["transit_seconds"]
        dtb = r["days_to_bill"]
        out.append({
            "order_id":      r["order_id"],
            "team_id":       r["team_id"],
            "status":        status,
            "departure":     r["departure"] or "",
            "customer_name": r["customer_name"] or "",
            "carrier":       r["carrier"] or "",
            "lane":          r["lane"] or "",
            "revenue":       _safe_float(r["revenue"]),
            "profit":        _safe_float(r["profit"]),
            "margin_pct":    _safe_float(r["margin"]),
            "otp_pct":       _safe_float(r["otp_pct"]),
            "otd_pct":       _safe_float(r["otd_pct"]),
            "departed_at":   departed_at,
            "arrived_at":    arrived_at,
            "transit_seconds": _safe_float(ts) if ts is not None else None,
            "in_progress":   in_progress,
            "billed":        bool(r["billed"]),
            "days_to_bill":  int(dtb) if dtb is not None else None,
        })

    # Bruno (PDF 2026-07-13): POD indicator — tick orders that already have a
    # POD Tracker document. The POD Tracker lives in the AP_module DB
    # (unilink_portal_ap.pod_tracker_loads, has_pod flag) — a SEPARATE Postgres
    # server, so it can't be JOINed into the datalake query. Look the fetched
    # page's order ids up in one bounded extra query and set a boolean. Degrades
    # to pod=False (never 503s the whole table) if the AP pool is unavailable —
    # POD is a supplementary indicator, not core production data. NOTE: the
    # tracker is a synced D/P snapshot, so orders outside its sync scope read
    # False even if physically documented.
    pod_set: set[str] = set()
    order_ids = [r["order_id"] for r in out if r["order_id"]]
    ap_pool = getattr(request.app.state, "ap_pool", None)
    if ap_pool is not None and order_ids:
        try:
            pod_rows = await ap_pool.fetch(
                """
                SELECT UPPER(TRIM(mcleod_order_id)) AS oid
                FROM pod_tracker_loads
                WHERE has_pod = TRUE
                  AND UPPER(TRIM(mcleod_order_id)) = ANY($1::text[])
                """,
                [o.upper() for o in order_ids],
            )
            pod_set = {r["oid"] for r in pod_rows}
        except Exception:
            # Intentional non-fatal degradation: a down/misconfigured AP DB
            # must not break the By Order table — fall back to pod=False.
            pod_set = set()
    for r in out:
        r["pod"] = bool(r["order_id"]) and r["order_id"].upper() in pod_set

    t_rev = _safe_float(tot_row["rev"]) if tot_row else 0.0
    t_prof = _safe_float(tot_row["prof"]) if tot_row else 0.0
    totals = {
        "n_orders": int(tot_row["n_orders"] or 0) if tot_row else 0,
        "revenue":  t_rev,
        "profit":   t_prof,
        "margin_pct": _safe_float((t_prof / t_rev * 100.0) if t_rev else 0.0),
    }

    return {
        "success": True,
        "data": out,
        "meta": {
            "window": {"start": s.isoformat(), "end": e.isoformat()},
            "total": totals["n_orders"],
            "returned": len(out),
            "limit": limit,
            "totals": totals,
        },
    }


# ---------------------------------------------------------------------------
# /team-weekly-performance — Bruno R4 (2026-05-27): "+" modal, last 5 weeks
# ---------------------------------------------------------------------------


@router.get("/team-weekly-performance")
async def team_weekly_performance(
    request: Request,
    team: Optional[str] = Query(None),
    customer: Optional[str] = Query(None),
    load_type: Optional[str] = Query(None),
    lanes: Optional[List[str]] = Query(None),
    exclude_lanes: Optional[List[str]] = Query(None),
    _user: dict = Depends(require_report_access("ops-portal-overview")),
):
    """Same KPI set as §5 Team Monthly Performance, split into the last 5
    Mon-Sun weeks (current week included).

    Three grouped queries (not five fan-outs) keep it inside the small
    datalake pool: production grouped by ISO week, savings grouped by ISO
    week (a month's savings lands in the week containing the 1st — matches
    Bruno's mock), and one window-independent attrition query (its value is
    identical across all weeks, as the PDF shows: 18% / 61.6% repeated).

    Team Ut. uses the same capacity formula as the monthly panel —
    volume / (500 × distinct active teams) — verified against the mock
    (289 / 2000 = 14.45%).
    """
    pool = get_datalake_gold_pool(request)
    today = cst_today()
    this_mon = today - timedelta(days=today.weekday())
    week_starts = [this_mon - timedelta(weeks=k) for k in range(4, -1, -1)]
    weeks_start = week_starts[0]
    weeks_end = week_starts[-1] + timedelta(days=6)

    def _wk(d: date) -> date:
        return d - timedelta(days=d.weekday())

    def _label(ws: date) -> str:
        we = ws + timedelta(days=6)
        return f"{ws.day:02d}/{ws.month:02d} - {we.day:02d}/{we.month:02d}"

    # ---- Production grouped by ISO week ---------------------------------
    prod_params: list = []
    where = _v4_scope_where("br4", team, customer, load_type, prod_params, lanes, exclude_lanes)
    prod_params.extend([weeks_start, weeks_end])
    p_s = len(prod_params) - 1
    p_e = len(prod_params)
    prod_sql = f"""
        WITH otp AS ({_scorecard_cte("otp")}),
             otd AS ({_scorecard_cte("otd")}),
             prod AS (
                SELECT DATE_TRUNC('week', br4.origin_actual_departure)::date AS wk,
                       br4.id, br4.team_id, br4.customer_name,
                       TRIM(br4.origin_name) AS origin,
                       TRIM(br4.dest_name)   AS dest,
                       br4.total_charge, br4.margin_amt, br4.total_carrier_pay,
                       COALESCE(otp.scorecard_count_otp, 0) AS otp_cnt,
                       COALESCE(otd.scorecard_count_otd, 0) AS otd_cnt
                FROM public.mcleod_gld_budget_report_v4 br4
                LEFT JOIN otp ON TRIM(br4.id)=otp.id_key AND TRIM(br4.company_id)=otp.company_id_key
                LEFT JOIN otd ON TRIM(br4.id)=otd.id_key AND TRIM(br4.company_id)=otd.company_id_key
                WHERE {where}
                  AND br4.origin_actual_departure >= ${p_s}
                  AND br4.origin_actual_departure < (${p_e}::date + INTERVAL '1 day')
             )
        SELECT
          wk,
          COUNT(DISTINCT customer_name) AS customers,
          COUNT(DISTINCT (origin || ' - ' || dest))
            FILTER (WHERE origin <> '' AND dest <> '') AS lanes,
          COUNT(*) FILTER (WHERE total_charge IS NOT NULL AND total_charge <> 0) AS volume,
          COALESCE(SUM(total_charge), 0)::numeric AS revenue,
          COALESCE(SUM(total_carrier_pay), 0)::numeric AS total_cost,
          COALESCE(SUM(margin_amt),  0)::numeric AS profit,
          COUNT(*) FILTER (WHERE margin_amt < 0
                             AND total_charge IS NOT NULL
                             AND total_charge <> 0) AS loss_loads,
          COALESCE(SUM(margin_amt) FILTER (WHERE margin_amt < 0), 0)::numeric AS profit_loss,
          SUM(otp_cnt) AS otp_late,
          SUM(otd_cnt) AS otd_late,
          COUNT(DISTINCT team_id) AS team_count
        FROM prod
        GROUP BY wk
    """

    # ---- Savings grouped by ISO week ------------------------------------
    sav_params: list = [weeks_start, weeks_end]
    sav_extra = " AND UPPER(COALESCE(cs.customer_name,'')) NOT LIKE '%OILTEX%'"
    if customer:
        sav_params.append(customer)
        sav_extra += f" AND cs.customer_name = ${len(sav_params)}"
    if team:
        sav_params.append(team)
        sav_extra += f" AND ct.team_id = ${len(sav_params)}"
    sav_sql = f"""
        WITH {CUSTOMER_TEAM_CTE}
        SELECT
          DATE_TRUNC('week', cs.month_date)::date AS wk,
          COALESCE(SUM(CASE WHEN cs.variance > 0 THEN cs.variance ELSE 0 END), 0)::numeric AS savings,
          COALESCE(SUM(CASE WHEN cs.variance < 0 THEN cs.variance ELSE 0 END), 0)::numeric AS over_pay,
          COALESCE(SUM(cs.variance), 0)::numeric AS net_savings
        FROM public.carriers_savings_results_report cs
        JOIN customer_team ct ON TRIM(cs.customer_name) = ct.customer_name
        WHERE cs.month_date BETWEEN $1 AND $2
        {sav_extra}
        GROUP BY DATE_TRUNC('week', cs.month_date)::date
    """

    # ---- Attrition (window-independent, identical across weeks) ----------
    attr_params: list = []
    where_attr = _v4_scope_where("br4", team, customer, load_type, attr_params, lanes, exclude_lanes)
    attr_params.append(YEAR_START)
    p_ys = len(attr_params)
    attr_sql = f"""
        WITH lane_last AS (
            SELECT br4.customer_name,
                   TRIM(br4.origin_name) AS origin,
                   TRIM(br4.dest_name)   AS dest,
                   MAX(br4.origin_actual_departure)::date AS last_load
            FROM public.mcleod_gld_budget_report_v4 br4
            WHERE {where_attr}
              AND br4.origin_actual_departure >= ${p_ys}
              AND br4.customer_name IS NOT NULL
              AND TRIM(br4.origin_name) <> ''
              AND TRIM(br4.dest_name)   <> ''
            GROUP BY br4.customer_name, TRIM(br4.origin_name), TRIM(br4.dest_name)
        ),
        cust_last AS (
            SELECT customer_name, MAX(last_load) AS last_load
            FROM lane_last GROUP BY customer_name
        )
        SELECT
          (SELECT COUNT(*) FROM cust_last)                                       AS cust_total,
          (SELECT COUNT(*) FROM cust_last WHERE (CURRENT_DATE - last_load) > 30) AS cust_attr,
          (SELECT COUNT(*) FROM lane_last)                                       AS lane_total,
          (SELECT COUNT(*) FROM lane_last WHERE (CURRENT_DATE - last_load) > 30) AS lane_attr
    """

    prod_rows, sav_rows, attr_row = await asyncio.gather(
        pool.fetch(prod_sql, *prod_params),
        pool.fetch(sav_sql, *sav_params),
        pool.fetchrow(attr_sql, *attr_params),
    )

    prod_map = {_wk(r["wk"]): r for r in prod_rows}
    sav_map = {_wk(r["wk"]): r for r in sav_rows}
    cust_total = int(attr_row["cust_total"] or 0) if attr_row else 0
    lane_total = int(attr_row["lane_total"] or 0) if attr_row else 0
    cust_attr_pct = (int(attr_row["cust_attr"] or 0) / cust_total * 100.0) if cust_total else 0.0
    lane_attr_pct = (int(attr_row["lane_attr"] or 0) / lane_total * 100.0) if lane_total else 0.0

    weeks = []
    for ws in week_starts:
        p = prod_map.get(ws)
        sv = sav_map.get(ws)
        volume = int(p["volume"] or 0) if p else 0
        revenue = _safe_float(p["revenue"]) if p else 0.0
        profit = _safe_float(p["profit"]) if p else 0.0
        otp_late = int(p["otp_late"] or 0) if p else 0
        otd_late = int(p["otd_late"] or 0) if p else 0
        team_count = (int(p["team_count"] or 0) if p else 0) or (1 if team else len(CORP_TEAMS))
        capacity = 500 * team_count
        weeks.append({
            "start": ws.isoformat(),
            "end": (ws + timedelta(days=6)).isoformat(),
            "label": _label(ws),
            "customers":  int(p["customers"] or 0) if p else 0,
            "lanes":      int(p["lanes"] or 0) if p else 0,
            "volume":     volume,
            "revenue":    revenue,
            "total_cost": _safe_float(p["total_cost"]) if p else 0.0,
            "profit":     profit,
            "margin_pct": _safe_float((profit / revenue * 100.0) if revenue else 0.0),
            "rev_x_l":    _safe_float((revenue / volume) if volume else 0.0),
            "prof_x_l":   _safe_float((profit / volume) if volume else 0.0),
            "team_ut":    _safe_float((volume / capacity * 100.0) if capacity else 0.0),
            "otp_pct":    _safe_float((1.0 - otp_late / volume) * 100.0 if volume else 0.0),
            "lates_pu":   otp_late,
            "otd_pct":    _safe_float((1.0 - otd_late / volume) * 100.0 if volume else 0.0),
            "lates_del":  otd_late,
            "savings":    _safe_float(sv["savings"]) if sv else 0.0,
            "over_pay":   _safe_float(sv["over_pay"]) if sv else 0.0,
            "net_savings": _safe_float(sv["net_savings"]) if sv else 0.0,
            "loss_loads":  int(p["loss_loads"] or 0) if p else 0,
            "profit_loss": _safe_float(p["profit_loss"]) if p else 0.0,
            "cust_attr_pct": _safe_float(cust_attr_pct),
            "lane_attr_pct": _safe_float(lane_attr_pct),
        })

    return {"success": True, "data": {"weeks": weeks}}


# ---------------------------------------------------------------------------
# /team-performance-by-team — §5 split per CORP team (TEAM1..TEAM5) + Total
# ---------------------------------------------------------------------------


def _team_perf_obj(
    *,
    customers: int,
    lanes: int,
    volume: int,
    revenue: float,
    total_cost: float,
    profit: float,
    loss_loads: int,
    profit_loss: float,
    otp_late: int,
    otd_late: int,
    team_count: int,
    savings: float,
    over_pay: float,
    net_savings: float,
    cust_total: int,
    cust_attr: int,
    lane_total: int,
    lane_attr: int,
    avg_days_billed: float = 0.0,
    avg_days_not_billed: float = 0.0,
    pct_del_bill: float = 0.0,
) -> dict:
    """Build one §5 row from raw aggregates — shared by every team + Total so
    every TeamPerf object carries the exact same field set as /team-performance.
    """
    capacity = 500 * (team_count or 0)
    return {
        "customers":  customers,
        "lanes":      lanes,
        "volume":     volume,
        "revenue":    _safe_float(revenue),
        "total_cost": _safe_float(total_cost),
        "profit":     _safe_float(profit),
        "margin_pct": _safe_float((profit / revenue * 100.0) if revenue else 0.0),
        "rev_x_l":    _safe_float((revenue / volume) if volume else 0.0),
        "prof_x_l":   _safe_float((profit / volume) if volume else 0.0),
        "team_ut":    _safe_float((volume / capacity * 100.0) if capacity else 0.0),
        "otp_pct":    _safe_float((1.0 - otp_late / volume) * 100.0 if volume else 0.0),
        "lates_pu":   otp_late,
        "otd_pct":    _safe_float((1.0 - otd_late / volume) * 100.0 if volume else 0.0),
        "lates_del":  otd_late,
        "savings":    _safe_float(savings),
        "over_pay":   _safe_float(over_pay),
        "net_savings": _safe_float(net_savings),
        "loss_loads":  loss_loads,
        "profit_loss": _safe_float(profit_loss),
        # Bruno round (2026-07-01) R12 — below Profit Loss.
        "avg_days_billed":     _safe_float(avg_days_billed),
        "avg_days_not_billed": _safe_float(avg_days_not_billed),
        "pct_del_bill":        _safe_float(pct_del_bill),
        "cust_attr_pct": _safe_float((cust_attr / cust_total * 100.0) if cust_total else 0.0),
        "lane_attr_pct": _safe_float((lane_attr / lane_total * 100.0) if lane_total else 0.0),
    }


@router.get("/team-performance-by-team")
async def team_performance_by_team(
    request: Request,
    range: Optional[str] = Query("mtd"),
    start_date: Optional[date] = Query(None),
    end_date: Optional[date] = Query(None),
    team: Optional[str] = Query(None),
    customer: Optional[str] = Query(None),
    load_type: Optional[str] = Query(None),
    lanes: Optional[List[str]] = Query(None),
    exclude_lanes: Optional[List[str]] = Query(None),
    _user: dict = Depends(require_report_access("ops-portal-overview")),
):
    """§5 Team Monthly Performance split per CORP team (TEAM1..TEAM5) + a Total.

    Same field set as /team-performance, computed once per team_id in a single
    grouped scan (production grouped by team_id, savings grouped by canonical
    team_id, attrition grouped by team_id) plus a window-wide Total. The single
    ``team`` filter is intentionally ignored — this panel always returns all
    CORP teams; ``customer`` / date / lane filters still apply.
    """
    pool = get_datalake_gold_pool(request)
    s, e = _resolve_range(range, start_date, end_date)

    # ---- Production grouped by team_id (team filter intentionally dropped) --
    prod_params: list = []
    where = _v4_scope_where("br4", None, customer, load_type, prod_params, lanes, exclude_lanes)
    prod_params.extend([s, e])
    p_s = len(prod_params) - 1
    p_e = len(prod_params)
    prod_sql = f"""
        WITH otp AS ({_scorecard_cte("otp")}),
             otd AS ({_scorecard_cte("otd")}),
             prod AS (
                SELECT TRIM(br4.team_id) AS team_id,
                       br4.id, br4.customer_name,
                       TRIM(br4.origin_name) AS origin,
                       TRIM(br4.dest_name)   AS dest,
                       br4.total_charge, br4.margin_amt, br4.total_carrier_pay,
                       COALESCE(otp.scorecard_count_otp, 0) AS otp_cnt,
                       COALESCE(otd.scorecard_count_otd, 0) AS otd_cnt
                FROM public.mcleod_gld_budget_report_v4 br4
                LEFT JOIN otp ON TRIM(br4.id)=otp.id_key AND TRIM(br4.company_id)=otp.company_id_key
                LEFT JOIN otd ON TRIM(br4.id)=otd.id_key AND TRIM(br4.company_id)=otd.company_id_key
                WHERE {where}
                  AND br4.origin_actual_departure >= ${p_s}
                  AND br4.origin_actual_departure < (${p_e}::date + INTERVAL '1 day')
             )
        SELECT
          team_id,
          COUNT(DISTINCT customer_name) AS customers,
          COUNT(DISTINCT (origin || ' - ' || dest))
            FILTER (WHERE origin <> '' AND dest <> '') AS lanes,
          COUNT(*) FILTER (WHERE total_charge IS NOT NULL AND total_charge <> 0) AS volume,
          COALESCE(SUM(total_charge), 0)::numeric AS revenue,
          COALESCE(SUM(total_carrier_pay), 0)::numeric AS total_cost,
          COALESCE(SUM(margin_amt),  0)::numeric AS profit,
          COUNT(*) FILTER (WHERE margin_amt < 0
                             AND total_charge IS NOT NULL
                             AND total_charge <> 0) AS loss_loads,
          COALESCE(SUM(margin_amt) FILTER (WHERE margin_amt < 0), 0)::numeric AS profit_loss,
          SUM(otp_cnt) AS otp_late,
          SUM(otd_cnt) AS otd_late
        FROM prod
        GROUP BY team_id
    """

    # ---- Savings grouped by canonical team_id ---------------------------
    sav_params: list = [s, e]
    sav_extra = " AND UPPER(COALESCE(cs.customer_name,'')) NOT LIKE '%OILTEX%'"
    if customer:
        sav_params.append(customer)
        sav_extra += f" AND cs.customer_name = ${len(sav_params)}"
    sav_sql = f"""
        WITH {CUSTOMER_TEAM_CTE}
        SELECT
          ct.team_id AS team_id,
          COALESCE(SUM(CASE WHEN cs.variance > 0 THEN cs.variance ELSE 0 END), 0)::numeric AS savings,
          COALESCE(SUM(CASE WHEN cs.variance < 0 THEN cs.variance ELSE 0 END), 0)::numeric AS over_pay,
          COALESCE(SUM(cs.variance), 0)::numeric AS net_savings
        FROM public.carriers_savings_results_report cs
        JOIN customer_team ct ON TRIM(cs.customer_name) = ct.customer_name
        WHERE cs.month_date BETWEEN $1 AND $2
        {sav_extra}
        GROUP BY ct.team_id
    """

    # ---- Attrition grouped by team_id (and rolled up for Total) ----------
    attr_params: list = []
    where_attr = _v4_scope_where("br4", None, customer, load_type, attr_params, lanes, exclude_lanes)
    attr_params.append(YEAR_START)
    p_ys = len(attr_params)
    attr_sql = f"""
        WITH lane_last AS (
            SELECT TRIM(br4.team_id) AS team_id,
                   br4.customer_name,
                   TRIM(br4.origin_name) AS origin,
                   TRIM(br4.dest_name)   AS dest,
                   MAX(br4.origin_actual_departure)::date AS last_load
            FROM public.mcleod_gld_budget_report_v4 br4
            WHERE {where_attr}
              AND br4.origin_actual_departure >= ${p_ys}
              AND br4.customer_name IS NOT NULL
              AND TRIM(br4.origin_name) <> ''
              AND TRIM(br4.dest_name)   <> ''
            GROUP BY TRIM(br4.team_id), br4.customer_name,
                     TRIM(br4.origin_name), TRIM(br4.dest_name)
        ),
        cust_last AS (
            SELECT team_id, customer_name, MAX(last_load) AS last_load
            FROM lane_last GROUP BY team_id, customer_name
        )
        SELECT
          c.team_id,
          (SELECT COUNT(*) FROM cust_last x WHERE x.team_id = c.team_id)                                          AS cust_total,
          (SELECT COUNT(*) FROM cust_last x WHERE x.team_id = c.team_id AND (CURRENT_DATE - x.last_load) > 30)    AS cust_attr,
          (SELECT COUNT(*) FROM lane_last l WHERE l.team_id = c.team_id)                                          AS lane_total,
          (SELECT COUNT(*) FROM lane_last l WHERE l.team_id = c.team_id AND (CURRENT_DATE - l.last_load) > 30)    AS lane_attr
        FROM (SELECT DISTINCT team_id FROM cust_last) c
    """

    # ---- Billing grouped by team_id (Bruno round 2026-07-01 R12) ---------
    bill_params: list = []
    where_bill = _v4_scope_where("br4", None, customer, load_type, bill_params, lanes, exclude_lanes)
    bill_params.extend([s, e])
    bt_s = len(bill_params) - 1
    bt_e = len(bill_params)
    bill_sql = _bill_metrics_sql(where_bill, bt_s, bt_e, group_by_team=True)

    prod_rows, sav_rows, attr_rows, bill_rows = await asyncio.gather(
        pool.fetch(prod_sql, *prod_params),
        pool.fetch(sav_sql, *sav_params),
        pool.fetch(attr_sql, *attr_params),
        pool.fetch(bill_sql, *bill_params),
    )

    prod_map = {r["team_id"]: r for r in prod_rows}
    sav_map = {r["team_id"]: r for r in sav_rows}
    attr_map = {r["team_id"]: r for r in attr_rows}
    bill_map = {r["team_id"]: r for r in bill_rows}

    teams_out = []
    tot = {
        "customers": set(), "lanes": set(), "volume": 0, "revenue": 0.0,
        "total_cost": 0.0, "profit": 0.0, "loss_loads": 0, "profit_loss": 0.0,
        "otp_late": 0, "otd_late": 0, "teams": set(), "savings": 0.0,
        "over_pay": 0.0, "net_savings": 0.0, "cust_total": 0, "cust_attr": 0,
        "lane_total": 0, "lane_attr": 0,
    }
    for tid in CORP_TEAMS:
        p = prod_map.get(tid)
        sv = sav_map.get(tid)
        at = attr_map.get(tid)
        bl = bill_map.get(tid)
        volume = int(p["volume"] or 0) if p else 0
        obj = _team_perf_obj(
            customers=int(p["customers"] or 0) if p else 0,
            lanes=int(p["lanes"] or 0) if p else 0,
            volume=volume,
            revenue=_safe_float(p["revenue"]) if p else 0.0,
            total_cost=_safe_float(p["total_cost"]) if p else 0.0,
            profit=_safe_float(p["profit"]) if p else 0.0,
            loss_loads=int(p["loss_loads"] or 0) if p else 0,
            profit_loss=_safe_float(p["profit_loss"]) if p else 0.0,
            otp_late=int(p["otp_late"] or 0) if p else 0,
            otd_late=int(p["otd_late"] or 0) if p else 0,
            team_count=1 if volume else 0,
            savings=_safe_float(sv["savings"]) if sv else 0.0,
            over_pay=_safe_float(sv["over_pay"]) if sv else 0.0,
            net_savings=_safe_float(sv["net_savings"]) if sv else 0.0,
            cust_total=int(at["cust_total"] or 0) if at else 0,
            cust_attr=int(at["cust_attr"] or 0) if at else 0,
            lane_total=int(at["lane_total"] or 0) if at else 0,
            lane_attr=int(at["lane_attr"] or 0) if at else 0,
            **_bill_fields(bl),
        )
        teams_out.append({"team_id": tid, **obj})
        # Accumulate the Total over the full universe (server-side, not a
        # client reduce over a LIMIT slice — there is no limit here).
        if volume:
            tot["teams"].add(tid)
        tot["volume"] += volume
        tot["revenue"] += _safe_float(p["revenue"]) if p else 0.0
        tot["total_cost"] += _safe_float(p["total_cost"]) if p else 0.0
        tot["profit"] += _safe_float(p["profit"]) if p else 0.0
        tot["loss_loads"] += int(p["loss_loads"] or 0) if p else 0
        tot["profit_loss"] += _safe_float(p["profit_loss"]) if p else 0.0
        tot["otp_late"] += int(p["otp_late"] or 0) if p else 0
        tot["otd_late"] += int(p["otd_late"] or 0) if p else 0
        tot["savings"] += _safe_float(sv["savings"]) if sv else 0.0
        tot["over_pay"] += _safe_float(sv["over_pay"]) if sv else 0.0
        tot["net_savings"] += _safe_float(sv["net_savings"]) if sv else 0.0
        tot["cust_total"] += int(at["cust_total"] or 0) if at else 0
        tot["cust_attr"] += int(at["cust_attr"] or 0) if at else 0
        tot["lane_total"] += int(at["lane_total"] or 0) if at else 0
        tot["lane_attr"] += int(at["lane_attr"] or 0) if at else 0

    # Total: distinct customers / lanes can't be summed across teams (a customer
    # may ship on two teams), so re-read the universe-wide distinct counts.
    uni_params: list = []
    uni_where = _v4_scope_where("br4", None, customer, load_type, uni_params, lanes, exclude_lanes)
    uni_params.extend([s, e])
    u_s = len(uni_params) - 1
    u_e = len(uni_params)
    # Universe-wide billing for the Total column — AVGs / ratios can't be summed
    # across teams, so re-read them over the whole scope (same treatment as the
    # distinct customer/lane counts above).
    ubill_params: list = []
    ubill_where = _v4_scope_where("br4", None, customer, load_type, ubill_params, lanes, exclude_lanes)
    ubill_params.extend([s, e])
    ub_s = len(ubill_params) - 1
    ub_e = len(ubill_params)
    ubill_sql = _bill_metrics_sql(ubill_where, ub_s, ub_e, group_by_team=False)

    uni_row, ubill_row = await asyncio.gather(
        pool.fetchrow(
            f"""
            SELECT
              COUNT(DISTINCT br4.customer_name) AS customers,
              COUNT(DISTINCT (TRIM(br4.origin_name) || ' - ' || TRIM(br4.dest_name)))
                FILTER (WHERE TRIM(br4.origin_name) <> '' AND TRIM(br4.dest_name) <> '') AS lanes
            FROM public.mcleod_gld_budget_report_v4 br4
            WHERE {uni_where}
              AND br4.origin_actual_departure >= ${u_s}
              AND br4.origin_actual_departure < (${u_e}::date + INTERVAL '1 day')
            """,
            *uni_params,
        ),
        pool.fetchrow(ubill_sql, *ubill_params),
    )

    total_obj = _team_perf_obj(
        customers=int(uni_row["customers"] or 0) if uni_row else 0,
        lanes=int(uni_row["lanes"] or 0) if uni_row else 0,
        volume=tot["volume"],
        revenue=tot["revenue"],
        total_cost=tot["total_cost"],
        profit=tot["profit"],
        loss_loads=tot["loss_loads"],
        profit_loss=tot["profit_loss"],
        otp_late=tot["otp_late"],
        otd_late=tot["otd_late"],
        team_count=len(tot["teams"]) or len(CORP_TEAMS),
        savings=tot["savings"],
        over_pay=tot["over_pay"],
        net_savings=tot["net_savings"],
        cust_total=tot["cust_total"],
        cust_attr=tot["cust_attr"],
        lane_total=tot["lane_total"],
        lane_attr=tot["lane_attr"],
        **_bill_fields(ubill_row),
    )

    return {
        "success": True,
        "data": {"total": total_obj, "teams": teams_out},
        "meta": {"window": {"start": s.isoformat(), "end": e.isoformat()}},
    }


# ---------------------------------------------------------------------------
# /service-incident-by-customer — incident-grain PU/DEL fails per customer
# ---------------------------------------------------------------------------

# PU = on-time-pickup fail codes (mirrors OTP_CODES / xray_corp); stops PU/SH.
# DEL = on-time-delivery fail codes (mirrors OTD_CODES); stops CO/SO. Same
# padded-variant EDI approach the file already uses for OTP/OTD (_scorecard_cte).
_PU_STOP_LIT = ",".join(f"'{v}'" for v in _pad_variants(("PU", "SH"), width=2))
_DEL_STOP_LIT = ",".join(f"'{v}'" for v in _pad_variants(("CO", "SO"), width=2))
_PU_CODE_LIT = ",".join(f"'{v}'" for v in _pad_variants(OTP_CODES, width=40))
_DEL_CODE_LIT = ",".join(f"'{v}'" for v in _pad_variants(OTD_CODES, width=40))


@router.get("/service-incident-by-customer")
async def service_incident_by_customer(
    request: Request,
    range: Optional[str] = Query("mtd"),
    start_date: Optional[date] = Query(None),
    end_date: Optional[date] = Query(None),
    team: Optional[str] = Query(None),
    customer: Optional[str] = Query(None),
    load_type: Optional[str] = Query(None),
    lanes: Optional[List[str]] = Query(None),
    exclude_lanes: Optional[List[str]] = Query(None),
    stop_type: str = Query("pu", description="'pu' | 'del'"),
    _user: dict = Depends(require_report_access("ops-portal-overview")),
):
    """PU or DEL service fails per customer over the incident-grain source
    ``mcleod_gld_scorecard_incidents_portal`` (same OTP/OTD code lists +
    padded-variant approach as ``_scorecard_cte``).

    ``orders`` = distinct charged loads, ``fail`` = distinct loads with a PU/DEL
    service fail, ``pct_on_time`` = 100 − 100*fail/orders. Top 100 by fail desc;
    ``meta.totals`` is the full-universe server-side aggregate.

    The incident table has no lane / city-pair grain (it is not in v4) and no
    contract_type column, so the ``lanes`` / ``exclude_lanes`` / ``load_type``
    filters are ignored here (same precedent the file already documents for the
    budget-only panels). Team / customer / date filters are honored.
    """
    pool = get_datalake_gold_pool(request)
    side = "del" if (stop_type or "").lower() == "del" else "pu"
    date_col = "orig_actual_departure" if side == "pu" else "dest_actual_departure"
    stops_lit = _PU_STOP_LIT if side == "pu" else _DEL_STOP_LIT
    codes_lit = _PU_CODE_LIT if side == "pu" else _DEL_CODE_LIT

    s, e = _resolve_range(range, start_date, end_date)

    teams_param = _pad_variants(CORP_TEAMS, width=8)
    companies_param = _pad_variants(CORP_COMPANIES, width=4)
    statuses_param = _pad_variants(OPEN_STATUSES, width=1)
    params: list = [teams_param, companies_param, statuses_param, s, e]
    parts = [
        "sc.team_id    = ANY($1)",
        "sc.company_id = ANY($2)",
        "sc.status     = ANY($3)",
        "UPPER(COALESCE(sc.customer_name,'')) NOT LIKE '%OILTEX%'",
        f"sc.{date_col} >= $4",
        f"sc.{date_col} < ($5::date + INTERVAL '1 day')",
    ]
    if team:
        params.append(_pad_variants([team], width=8))
        parts.append(f"sc.team_id = ANY(${len(params)})")
    if customer:
        params.append(customer)
        parts.append(f"sc.customer_name = ${len(params)}")
    # ``load_type`` is accepted for API symmetry with /actuals but ignored here:
    # the incident table has no contract_type / load-type grain.
    where = " AND ".join(parts)
    fail_pred = (
        f"(sc.stop_type IN ({stops_lit}) "
        f"AND sc.edi_standard_code IN ({codes_lit}))"
    )

    by_customer_sql = f"""
        SELECT
          TRIM(sc.customer_name) AS customer_name,
          COUNT(DISTINCT sc.id) FILTER (WHERE sc.total_charge IS NOT NULL AND sc.total_charge <> 0) AS orders,
          COUNT(DISTINCT sc.id) FILTER (WHERE {fail_pred}) AS fail
        FROM public.mcleod_gld_scorecard_incidents_portal sc
        WHERE {where}
          AND sc.customer_name IS NOT NULL
          AND TRIM(sc.customer_name) <> ''
        GROUP BY TRIM(sc.customer_name)
        HAVING COUNT(DISTINCT sc.id) FILTER (WHERE sc.total_charge IS NOT NULL AND sc.total_charge <> 0) > 0
        ORDER BY fail DESC NULLS LAST, orders DESC
        LIMIT 100
    """
    totals_sql = f"""
        SELECT
          COUNT(DISTINCT sc.id) FILTER (WHERE sc.total_charge IS NOT NULL AND sc.total_charge <> 0) AS orders,
          COUNT(DISTINCT sc.id) FILTER (WHERE {fail_pred}) AS fail
        FROM public.mcleod_gld_scorecard_incidents_portal sc
        WHERE {where}
    """

    rows, tot_row = await asyncio.gather(
        pool.fetch(by_customer_sql, *params),
        pool.fetchrow(totals_sql, *params),
    )

    def _on_time(orders: int, fail: int) -> float:
        return (1.0 - (fail / orders)) * 100.0 if orders else 0.0

    data = [
        {
            "customer_name": r["customer_name"],
            "orders": int(r["orders"] or 0),
            "fail": int(r["fail"] or 0),
            "pct_on_time": _safe_float(_on_time(int(r["orders"] or 0), int(r["fail"] or 0))),
        }
        for r in rows
    ]
    t_orders = int(tot_row["orders"] or 0) if tot_row else 0
    t_fail = int(tot_row["fail"] or 0) if tot_row else 0
    return {
        "success": True,
        "data": data,
        "meta": {
            "stop_type": side,
            "window": {"start": s.isoformat(), "end": e.isoformat()},
            "totals": {
                "orders": t_orders,
                "fail": t_fail,
                "pct_on_time": _safe_float(_on_time(t_orders, t_fail)),
            },
        },
    }


# ---------------------------------------------------------------------------
# /margin-distribution — ORDERS per per-order margin% bucket (Bruno R18)
# ---------------------------------------------------------------------------


@router.get("/margin-distribution")
async def margin_distribution(
    request: Request,
    range: Optional[str] = Query("mtd"),
    start_date: Optional[date] = Query(None),
    end_date: Optional[date] = Query(None),
    team: Optional[str] = Query(None),
    customer: Optional[str] = Query(None),
    load_type: Optional[str] = Query(None),
    lanes: Optional[List[str]] = Query(None),
    exclude_lanes: Optional[List[str]] = Query(None),
    _user: dict = Depends(require_report_access("ops-portal-overview")),
):
    """ORDER count + revenue per per-order margin% bucket over v4 production.

    Buckets on each order's ``margin_amt / total_charge``:
      lt_0 (<0%) / 0_5 / 5_10 / 10_15 / 15_20 / gte_20.
    Orders with ``total_charge = 0`` have an undefined margin% so they land in a
    ``no_revenue`` bucket (same handling as ops-margins /distribution) — the v4
    profit rule (SUM(margin_amt) over ALL rows) is not violated because we never
    filter those rows out of the totals; only the per-order margin% needs a
    non-zero charge to be defined.

    Unlike OPs Margins' /distribution (which counts CUSTOMERS), this counts
    ORDERS — the intended difference per Bruno R18.
    """
    pool = get_datalake_gold_pool(request)
    s, e = _resolve_range(range, start_date, end_date)
    params: list = []
    where = _v4_scope_where("br4", team, customer, load_type, params, lanes, exclude_lanes)
    params.extend([s, e])
    p_s = len(params) - 1
    p_e = len(params)

    rows = await pool.fetch(
        f"""
        WITH labeled AS (
          SELECT
            CASE
              WHEN br4.total_charge IS NULL OR br4.total_charge = 0 THEN 'no_revenue'
              WHEN br4.margin_amt / br4.total_charge < 0     THEN 'lt_0'
              WHEN br4.margin_amt / br4.total_charge < 0.05  THEN '0_5'
              WHEN br4.margin_amt / br4.total_charge < 0.10  THEN '5_10'
              WHEN br4.margin_amt / br4.total_charge < 0.15  THEN '10_15'
              WHEN br4.margin_amt / br4.total_charge < 0.20  THEN '15_20'
              ELSE                                                'gte_20'
            END AS bucket,
            br4.total_charge,
            br4.margin_amt
          FROM public.mcleod_gld_budget_report_v4 br4
          WHERE {where}
            AND br4.origin_actual_departure >= ${p_s}
            AND br4.origin_actual_departure < (${p_e}::date + INTERVAL '1 day')
        )
        SELECT
          bucket,
          COUNT(*)::int                          AS orders,
          COALESCE(SUM(total_charge), 0)::numeric AS revenue,
          COALESCE(SUM(margin_amt), 0)::numeric   AS profit
        FROM labeled
        GROUP BY bucket
        ORDER BY CASE bucket
          WHEN 'lt_0'   THEN 0
          WHEN '0_5'    THEN 1
          WHEN '5_10'   THEN 2
          WHEN '10_15'  THEN 3
          WHEN '15_20'  THEN 4
          WHEN 'gte_20' THEN 5
          ELSE 6 END
        """,
        *params,
    )

    data = [
        {
            "bucket": r["bucket"],
            "orders": int(r["orders"] or 0),
            "revenue": _safe_float(r["revenue"]),
            # Bruno (PDF 2026-07-13): Profit total per bucket (SUM(margin_amt)).
            "profit": _safe_float(r["profit"]),
        }
        for r in rows
    ]
    # Header totals cover only the orders with a definable margin% (the six
    # rendered buckets). The 'no_revenue' bucket (total_charge = 0 → undefined
    # margin%) is excluded so the header reconciles with the visible buckets;
    # it stays in `data` for completeness but the frontend renders the six.
    total_orders = sum(d["orders"] for d in data if d["bucket"] != "no_revenue")
    total_revenue = _safe_float(sum(d["revenue"] for d in data if d["bucket"] != "no_revenue"))
    total_profit = _safe_float(sum(d["profit"] for d in data if d["bucket"] != "no_revenue"))
    return {
        "success": True,
        "data": data,
        "meta": {
            "window": {"start": s.isoformat(), "end": e.isoformat()},
            "total_orders": total_orders,
            "total_revenue": total_revenue,
            "total_profit": total_profit,
        },
    }


# ---------------------------------------------------------------------------
# Bruno (PDF 2026-07-13) — Week / Team toggles on the Team Budget Variance and
# Team Monthly Projection panels. Each returns the SAME metric set as its base
# panel, broken out by the last 5 Mon-Sun weeks or by CORP team (Total + T1..5).
# ---------------------------------------------------------------------------


def _variance_from_sums(customers, loads_a, loads_b, rev_a, rev_b, prof_a, prof_b) -> dict:
    """Build one Team-Budget-Variance object (actual − budget) from raw sums."""
    loads_var = _safe_float(loads_a) - _safe_float(loads_b)
    revenue_var = _safe_float(rev_a) - _safe_float(rev_b)
    profit_var = _safe_float(prof_a) - _safe_float(prof_b)
    margin_var_pct = (profit_var / revenue_var * 100.0) if revenue_var else 0.0
    return {
        "customers":      int(customers or 0),
        "volume_var":     _safe_float(loads_var),
        "revenue_var":    _safe_float(revenue_var),
        "profit_var":     _safe_float(profit_var),
        "margin_var_pct": _safe_float(margin_var_pct),
        "rev_x_l":        _safe_float((revenue_var / loads_var) if loads_var else 0.0),
        "prof_x_l":       _safe_float((profit_var / loads_var) if loads_var else 0.0),
    }


def _projection_from_sums(vol_12, rev_12, prof_12, vol_mtd, rev_mtd, prof_mtd,
                          pending: int, team_count: int) -> dict:
    """Build one Team-Monthly-Projection object from raw 12-day + MTD sums."""
    avg_vol = _safe_float(vol_12) / 12.0
    avg_rev = _safe_float(rev_12) / 12.0
    avg_prof = _safe_float(prof_12) / 12.0
    proj_vol = avg_vol * pending + _safe_float(vol_mtd)
    proj_rev = avg_rev * pending + _safe_float(rev_mtd)
    proj_prof = avg_prof * pending + _safe_float(prof_mtd)
    cap = 500.0 * (team_count or 0)
    return {
        "avg_vol_day":  _safe_float(avg_vol),
        "avg_rev_day":  _safe_float(avg_rev),
        "avg_prof_day": _safe_float(avg_prof),
        "pending_workdays": pending,
        "proj_volume":  _safe_float(proj_vol),
        "proj_revenue": _safe_float(proj_rev),
        "proj_profit":  _safe_float(proj_prof),
        "proj_margin_pct": _safe_float((proj_prof / proj_rev * 100.0) if proj_rev else 0.0),
        "proj_rev_x_l":  _safe_float((proj_rev / proj_vol) if proj_vol else 0.0),
        "proj_prof_x_l": _safe_float((proj_prof / proj_vol) if proj_vol else 0.0),
        "proj_team_ut":  _safe_float((proj_vol / cap * 100.0) if cap else 0.0),
    }


def _last_5_weeks(today: date) -> tuple[list[date], date, date]:
    """The 5 most recent Mon-Sun week-starts (current week included), plus the
    span bounds. Mirrors /team-weekly-performance so the two Week views align."""
    this_mon = today - timedelta(days=today.weekday())
    week_starts = [this_mon - timedelta(weeks=k) for k in range(4, -1, -1)]
    return week_starts, week_starts[0], week_starts[-1] + timedelta(days=6)


def _week_label(ws: date) -> str:
    we = ws + timedelta(days=6)
    return f"{ws.day:02d}/{ws.month:02d} - {we.day:02d}/{we.month:02d}"


@router.get("/team-variance-weekly")
async def team_variance_weekly(
    request: Request,
    team: Optional[str] = Query(None),
    customer: Optional[str] = Query(None),
    _user: dict = Depends(require_report_access("ops-portal-overview")),
):
    """Team Budget Variance broken out by the last 5 completed Mon-Sun weeks.

    Each week column is the actual − budget variance for that week (same
    convention as /team-variance). Fixed rolling 5-week window; team/customer
    filters apply, the page date filter is intentionally ignored.
    """
    pool = get_datalake_gold_pool(request)
    today = cst_today()
    week_starts, weeks_start, weeks_end = _last_5_weeks(today)
    params: list = [weeks_start, weeks_end]
    extra = ""
    if team:
        params.append(team)
        extra += f" AND ct.team_id = ${len(params)}"
    if customer:
        params.append(customer)
        extra += f' AND budget."Customer Name" = ${len(params)}'
    rows = await pool.fetch(
        f"""
        WITH {CUSTOMER_TEAM_CTE},
        per_cw AS (
          SELECT
            DATE_TRUNC('week', budget."Date")::date AS wk,
            budget."Customer Name" AS cust,
            SUM(budget."Loads Actual")   AS la, SUM(budget."Loads Budget")   AS lb,
            SUM(budget."Revenue Actual") AS ra, SUM(budget."Revenue Budget") AS rb,
            SUM(budget."Profit Actual")  AS pa, SUM(budget."Profit Budget")  AS pb
          FROM public.daily_production_budget_report budget
          JOIN customer_team ct ON TRIM(budget."Customer Name") = ct.customer_name
          WHERE budget."Date" BETWEEN $1 AND $2
          {extra}
          GROUP BY 1, 2
        )
        SELECT
          wk,
          COUNT(*) FILTER (WHERE COALESCE(la,0) > 0) AS active_customers,
          COALESCE(SUM(lb),0) AS loads_budget,   COALESCE(SUM(la),0) AS loads_actual,
          COALESCE(SUM(rb),0) AS revenue_budget, COALESCE(SUM(ra),0) AS revenue_actual,
          COALESCE(SUM(pb),0) AS profit_budget,  COALESCE(SUM(pa),0) AS profit_actual
        FROM per_cw
        GROUP BY wk
        """,
        *params,
    )
    by_wk = {r["wk"]: r for r in rows}
    weeks_out = []
    for ws in week_starts:
        r = by_wk.get(ws)
        obj = _variance_from_sums(
            r["active_customers"] if r else 0,
            r["loads_actual"] if r else 0, r["loads_budget"] if r else 0,
            r["revenue_actual"] if r else 0, r["revenue_budget"] if r else 0,
            r["profit_actual"] if r else 0, r["profit_budget"] if r else 0,
        )
        obj["start"] = ws.isoformat()
        obj["end"] = (ws + timedelta(days=6)).isoformat()
        obj["label"] = _week_label(ws)
        weeks_out.append(obj)
    return {"success": True, "data": {"weeks": weeks_out}}


@router.get("/team-variance-by-team")
async def team_variance_by_team(
    request: Request,
    range: Optional[str] = Query("mtd"),
    start_date: Optional[date] = Query(None),
    end_date: Optional[date] = Query(None),
    customer: Optional[str] = Query(None),
    _user: dict = Depends(require_report_access("ops-portal-overview")),
):
    """Team Budget Variance split per CORP team (TEAM1..TEAM5) + a Total.

    The single ``team`` filter is intentionally dropped — this view always
    returns every CORP team; ``customer`` / date filters still apply.
    """
    pool = get_datalake_gold_pool(request)
    s, e = _resolve_range(range, start_date, end_date)
    params: list = [s, e]
    extra = ""
    if customer:
        params.append(customer)
        extra += f' AND budget."Customer Name" = ${len(params)}'
    rows = await pool.fetch(
        f"""
        WITH {CUSTOMER_TEAM_CTE},
        per_ct AS (
          SELECT
            ct.team_id AS team_id,
            budget."Customer Name" AS cust,
            SUM(budget."Loads Actual")   AS la, SUM(budget."Loads Budget")   AS lb,
            SUM(budget."Revenue Actual") AS ra, SUM(budget."Revenue Budget") AS rb,
            SUM(budget."Profit Actual")  AS pa, SUM(budget."Profit Budget")  AS pb
          FROM public.daily_production_budget_report budget
          JOIN customer_team ct ON TRIM(budget."Customer Name") = ct.customer_name
          WHERE budget."Date" BETWEEN $1 AND $2
          {extra}
          GROUP BY 1, 2
        )
        SELECT
          team_id,
          COUNT(*) FILTER (WHERE COALESCE(la,0) > 0) AS active_customers,
          COALESCE(SUM(lb),0) AS loads_budget,   COALESCE(SUM(la),0) AS loads_actual,
          COALESCE(SUM(rb),0) AS revenue_budget, COALESCE(SUM(ra),0) AS revenue_actual,
          COALESCE(SUM(pb),0) AS profit_budget,  COALESCE(SUM(pa),0) AS profit_actual
        FROM per_ct
        GROUP BY team_id
        """,
        *params,
    )
    by_team = {r["team_id"]: r for r in rows}
    acc = {"cust": 0, "la": 0.0, "lb": 0.0, "ra": 0.0, "rb": 0.0, "pa": 0.0, "pb": 0.0}
    teams_out = []
    for t in CORP_TEAMS:
        r = by_team.get(t)
        obj = _variance_from_sums(
            r["active_customers"] if r else 0,
            r["loads_actual"] if r else 0, r["loads_budget"] if r else 0,
            r["revenue_actual"] if r else 0, r["revenue_budget"] if r else 0,
            r["profit_actual"] if r else 0, r["profit_budget"] if r else 0,
        )
        obj["team_id"] = t
        teams_out.append(obj)
        if r:
            acc["cust"] += int(r["active_customers"] or 0)
            acc["la"] += _safe_float(r["loads_actual"]);  acc["lb"] += _safe_float(r["loads_budget"])
            acc["ra"] += _safe_float(r["revenue_actual"]); acc["rb"] += _safe_float(r["revenue_budget"])
            acc["pa"] += _safe_float(r["profit_actual"]);  acc["pb"] += _safe_float(r["profit_budget"])
    total = _variance_from_sums(
        acc["cust"], acc["la"], acc["lb"], acc["ra"], acc["rb"], acc["pa"], acc["pb"],
    )
    return {"success": True, "data": {"total": total, "teams": teams_out}}


@router.get("/team-projection-by-team")
async def team_projection_by_team(
    request: Request,
    customer: Optional[str] = Query(None),
    load_type: Optional[str] = Query(None),
    lanes: Optional[List[str]] = Query(None),
    exclude_lanes: Optional[List[str]] = Query(None),
    _user: dict = Depends(require_report_access("ops-portal-overview")),
):
    """Team Monthly Projection split per CORP team (TEAM1..TEAM5) + a Total.

    Same rolling 12-business-day → EoM extrapolation as /team-projection, run
    once per team_id. Per-team capacity uses team_count = 1; the Total uses the
    number of teams with data. The single ``team`` filter is dropped.
    """
    pool = get_datalake_gold_pool(request)
    today = cst_today()
    m_start, m_end = _month_bounds(today)
    win_start = _last_n_business_days_start(today, 12)
    win_end = today - timedelta(days=1)
    pending_workdays = _count_workdays(today, m_end)

    params: list = []
    where = _v4_scope_where("br4", None, customer, load_type, params, lanes, exclude_lanes)
    params.extend([win_start, win_end, m_start, win_end, m_start, m_end])
    p_ws = len(params) - 5
    p_we = len(params) - 4
    p_ms1 = len(params) - 3
    p_we2 = len(params) - 2
    p_ms2 = len(params) - 1
    p_me = len(params)
    rows = await pool.fetch(
        f"""
        SELECT
          TRIM(br4.team_id) AS team_id,
          COUNT(*) FILTER (WHERE br4.origin_actual_departure::date BETWEEN ${p_ws} AND ${p_we}
                             AND EXTRACT(DOW FROM br4.origin_actual_departure::date) <> 0
                             AND br4.total_charge IS NOT NULL AND br4.total_charge <> 0) AS vol_12,
          COALESCE(SUM(CASE WHEN br4.origin_actual_departure::date BETWEEN ${p_ws} AND ${p_we}
                              AND EXTRACT(DOW FROM br4.origin_actual_departure::date) <> 0
                            THEN br4.total_charge END), 0)::numeric AS rev_12,
          COALESCE(SUM(CASE WHEN br4.origin_actual_departure::date BETWEEN ${p_ws} AND ${p_we}
                              AND EXTRACT(DOW FROM br4.origin_actual_departure::date) <> 0
                            THEN br4.margin_amt END), 0)::numeric AS prof_12,
          COUNT(*) FILTER (WHERE br4.origin_actual_departure::date BETWEEN ${p_ms1} AND ${p_we2}
                             AND br4.total_charge IS NOT NULL AND br4.total_charge <> 0) AS vol_mtd,
          COALESCE(SUM(CASE WHEN br4.origin_actual_departure::date BETWEEN ${p_ms2} AND ${p_me}
                            THEN br4.total_charge END), 0)::numeric AS rev_mtd,
          COALESCE(SUM(CASE WHEN br4.origin_actual_departure::date BETWEEN ${p_ms2} AND ${p_me}
                            THEN br4.margin_amt END), 0)::numeric AS prof_mtd
        FROM public.mcleod_gld_budget_report_v4 br4
        WHERE {where}
        GROUP BY TRIM(br4.team_id)
        """,
        *params,
    )
    by_team = {r["team_id"]: r for r in rows}
    acc = {"v12": 0.0, "r12": 0.0, "p12": 0.0, "vm": 0.0, "rm": 0.0, "pm": 0.0}
    teams_out = []
    for t in CORP_TEAMS:
        r = by_team.get(t)
        obj = _projection_from_sums(
            r["vol_12"] if r else 0, r["rev_12"] if r else 0, r["prof_12"] if r else 0,
            r["vol_mtd"] if r else 0, r["rev_mtd"] if r else 0, r["prof_mtd"] if r else 0,
            pending_workdays, 1,
        )
        obj["team_id"] = t
        teams_out.append(obj)
        if r:
            acc["v12"] += _safe_float(r["vol_12"]); acc["r12"] += _safe_float(r["rev_12"]); acc["p12"] += _safe_float(r["prof_12"])
            acc["vm"] += _safe_float(r["vol_mtd"]); acc["rm"] += _safe_float(r["rev_mtd"]); acc["pm"] += _safe_float(r["prof_mtd"])
    total = _projection_from_sums(
        acc["v12"], acc["r12"], acc["p12"], acc["vm"], acc["rm"], acc["pm"],
        pending_workdays, len(rows) or len(CORP_TEAMS),
    )
    return {
        "success": True,
        "data": {
            "total": total, "teams": teams_out,
            "today": today.isoformat(),
            "month_start": m_start.isoformat(),
            "month_end": m_end.isoformat(),
        },
    }


@router.get("/team-projection-weekly")
async def team_projection_weekly(
    request: Request,
    team: Optional[str] = Query(None),
    customer: Optional[str] = Query(None),
    load_type: Optional[str] = Query(None),
    lanes: Optional[List[str]] = Query(None),
    exclude_lanes: Optional[List[str]] = Query(None),
    _user: dict = Depends(require_report_access("ops-portal-overview")),
):
    """Team Monthly Projection "Week" view — per-week ACTUALS for the last 5
    Mon-Sun weeks (Bruno decision 2026-07-13).

    A projection is inherently forward-looking, so a per-week grouping shows
    each recent week's realised figures under the projection's row labels:
    Avg *·Day = week total ÷ that week's Mon-Sat workdays; Proj * = that week's
    actual; Team Ut. = week volume ÷ (500 × active teams). Fixed rolling
    window; team/customer/lane filters apply, the page date filter is ignored.
    """
    pool = get_datalake_gold_pool(request)
    today = cst_today()
    week_starts, weeks_start, weeks_end = _last_5_weeks(today)
    params: list = []
    where = _v4_scope_where("br4", team, customer, load_type, params, lanes, exclude_lanes)
    params.extend([weeks_start, weeks_end])
    p_s = len(params) - 1
    p_e = len(params)
    rows = await pool.fetch(
        f"""
        SELECT
          DATE_TRUNC('week', br4.origin_actual_departure)::date AS wk,
          COUNT(*) FILTER (WHERE br4.total_charge IS NOT NULL AND br4.total_charge <> 0) AS vol,
          COALESCE(SUM(br4.total_charge), 0)::numeric AS rev,
          COALESCE(SUM(br4.margin_amt),  0)::numeric AS prof,
          COUNT(DISTINCT br4.team_id) AS team_count
        FROM public.mcleod_gld_budget_report_v4 br4
        WHERE {where}
          AND br4.origin_actual_departure >= ${p_s}
          AND br4.origin_actual_departure < (${p_e}::date + INTERVAL '1 day')
        GROUP BY wk
        """,
        *params,
    )
    by_wk = {r["wk"]: r for r in rows}
    weeks_out = []
    for ws in week_starts:
        r = by_wk.get(ws)
        we = ws + timedelta(days=6)
        vol = int(r["vol"] or 0) if r else 0
        rev = _safe_float(r["rev"]) if r else 0.0
        prof = _safe_float(r["prof"]) if r else 0.0
        # Workdays elapsed in this week (cap the current, partial week at today).
        wk_workdays = _count_workdays(ws, min(we, today)) or 1
        team_count = (int(r["team_count"] or 0) if r else 0) or (1 if team else len(CORP_TEAMS))
        cap = 500.0 * team_count
        weeks_out.append({
            "start": ws.isoformat(),
            "end": we.isoformat(),
            "label": _week_label(ws),
            "avg_vol_day":  _safe_float(vol / wk_workdays),
            "avg_rev_day":  _safe_float(rev / wk_workdays),
            "avg_prof_day": _safe_float(prof / wk_workdays),
            "pending_workdays": wk_workdays,
            "proj_volume":  vol,
            "proj_revenue": rev,
            "proj_profit":  prof,
            "proj_margin_pct": _safe_float((prof / rev * 100.0) if rev else 0.0),
            "proj_rev_x_l":  _safe_float((rev / vol) if vol else 0.0),
            "proj_prof_x_l": _safe_float((prof / vol) if vol else 0.0),
            "proj_team_ut":  _safe_float((vol / cap * 100.0) if cap else 0.0),
        })
    return {"success": True, "data": {"weeks": weeks_out}}
