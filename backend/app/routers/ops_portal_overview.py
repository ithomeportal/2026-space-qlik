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
"""

from __future__ import annotations

import asyncio
from calendar import monthrange
from datetime import date, datetime, timedelta
from typing import Optional

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
    """Same range model as xray-corp: full / ytd / mtd / custom."""
    today = cst_today()
    today_clamped = max(YEAR_START, min(YEAR_END, today))
    if rng == "mtd":
        return today_clamped.replace(day=1), today_clamped
    if rng == "ytd":
        return YEAR_START, today_clamped
    if rng == "custom":
        s = _clamp(start_date, YEAR_START)
        e = _clamp(end_date, YEAR_END)
        if e < s:
            s, e = e, s
        return s, e
    # default = full year
    return YEAR_START, YEAR_END


def _count_workdays(start: date, end: date) -> int:
    """Mon-Fri days in [start, end] excluding US 2026 federal holidays."""
    if start > end:
        return 0
    n, d = 0, start
    while d <= end:
        if d.weekday() < 5 and d not in US_HOLIDAYS_2026:
            n += 1
        d += timedelta(days=1)
    return n


def _month_bounds(today: date) -> tuple[date, date]:
    m_start = today.replace(day=1)
    m_end = today.replace(day=monthrange(today.year, today.month)[1])
    return m_start, m_end


def _v4_scope_where(
    alias: str,
    team: Optional[str],
    customer: Optional[str],
    load_type: Optional[str],
    params: list,
) -> str:
    """CORP-scope WHERE for ``mcleod_gld_budget_report_v4``.

    Sargable (no TRIM()): pushes padded+unpadded literal variants per the
    width=8 / width=4 / width=1 declared schema on team_id / company_id /
    status. ``customer`` is exact-match (single select). ``load_type`` is
    "contract" or "spot" — falls back to no filter when None/empty.
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
    return " AND ".join(parts)


def _scorecard_cte(kind: str) -> str:
    """OTP/OTD per-order roll-up — same shape as xray_corp._scorecard_cte."""
    if kind == "otp":
        codes = OTP_CODES
        stops = ("", "PU", "SH")
        out = "scorecard_count_otp"
    else:
        codes = OTD_CODES
        stops = ("", "CO", "SO")
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
    FROM public.mcleod_gld_scorecard
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


# ---------------------------------------------------------------------------
# /filters — teams + customers
# ---------------------------------------------------------------------------


@router.get("/filters")
async def filters(
    request: Request,
    _user: dict = Depends(require_report_access("ops-portal-overview")),
):
    """Teams (TEAM1..TEAM5) and distinct customer list across the YTD window."""
    pool = get_datalake_gold_pool(request)
    rows = await pool.fetch(
        """
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
        """,
        list(CORP_TEAMS),
        list(CORP_COMPANIES),
        list(OPEN_STATUSES),
        YEAR_START,
    )
    return {
        "success": True,
        "data": {
            "teams": list(CORP_TEAMS),
            "customers": [r["customer_name"] for r in rows],
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
# /combo — 12-month bars + lines (ignores Date filter)
# ---------------------------------------------------------------------------


@router.get("/combo")
async def combo(
    request: Request,
    team: Optional[str] = Query(None),
    customer: Optional[str] = Query(None),
    load_type: Optional[str] = Query(None, description="'contract' | 'spot' | null"),
    _user: dict = Depends(require_report_access("ops-portal-overview")),
):
    """Last-12-months combo. Bars carry vol/rev/prof/margin so the UI can swap
    between them without re-fetching. Lines: losses_x_m, budget_revenue,
    projected_tm (single value, last bucket only).

    Bruno's "Use Production URL / Budget URL" split:
      - Bars + losses_x_m  → mcleod_gld_budget_report_v4 (Production)
      - budget_revenue     → daily_production_budget_report (Budget)
      - projected_tm       → 14-day rolling Production extrapolated to EoM
    """
    pool = get_datalake_gold_pool(request)
    today = cst_today()

    # Last 12 month buckets ending at the current month.
    months: list[tuple[date, date]] = []
    cursor = today.replace(day=1)
    for _ in range(12):
        m_end = cursor.replace(day=monthrange(cursor.year, cursor.month)[1])
        months.append((cursor, m_end))
        # step back one month
        prev_last = cursor - timedelta(days=1)
        cursor = prev_last.replace(day=1)
    months.reverse()  # oldest → newest
    win_start = months[0][0]
    win_end = months[-1][1]

    # ---- Production query (bars + losses) -------------------------------
    prod_params: list = []
    where = _v4_scope_where("br4", team, customer, load_type, prod_params)
    prod_params.extend([win_start, win_end])
    p_ws = len(prod_params) - 1
    p_we = len(prod_params)
    prod_sql = f"""
        SELECT
          DATE_TRUNC('month', br4.origin_actual_departure)::date AS month_start,
          COUNT(*) FILTER (WHERE br4.total_charge IS NOT NULL AND br4.total_charge <> 0) AS volume,
          COALESCE(SUM(br4.total_charge), 0)::numeric AS revenue,
          COALESCE(SUM(br4.margin_amt), 0)::numeric   AS profit,
          COALESCE(SUM(br4.margin_amt) FILTER (WHERE br4.margin_amt < 0), 0)::numeric AS losses
        FROM public.mcleod_gld_budget_report_v4 br4
        WHERE {where}
          AND br4.origin_actual_departure::date BETWEEN ${p_ws} AND ${p_we}
        GROUP BY 1
    """

    # ---- Budget revenue (Budget URL) ------------------------------------
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
          DATE_TRUNC('month', budget."Date")::date AS month_start,
          COALESCE(SUM(budget."Revenue Budget"), 0)::numeric AS budget_revenue,
          COALESCE(SUM(budget."Profit Budget"),  0)::numeric AS budget_profit,
          COALESCE(SUM(budget."Loads Budget"),   0)::numeric AS budget_loads
        FROM public.daily_production_budget_report budget
        JOIN customer_team ct ON TRIM(budget."Customer Name") = ct.customer_name
        WHERE budget."Date" BETWEEN $1 AND $2
        {bud_extra}
        GROUP BY 1
    """

    # ---- Projected TM — last 14 calendar days extrapolated to EoM -------
    m_start, m_end = _month_bounds(today)
    win14_start = today - timedelta(days=14)
    win14_end = today - timedelta(days=1)  # don't include today (partial)
    pending_workdays = _count_workdays(today, m_end)

    proj_params: list = []
    where_proj = _v4_scope_where("br4", team, customer, load_type, proj_params)
    proj_params.extend([win14_start, win14_end, m_start, win14_end])
    p_w14s = len(proj_params) - 3
    p_w14e = len(proj_params) - 2
    p_ms = len(proj_params) - 1
    p_w14e2 = len(proj_params)
    proj_sql = f"""
        SELECT
          COALESCE(SUM(CASE WHEN br4.origin_actual_departure::date BETWEEN ${p_w14s} AND ${p_w14e}
                            THEN br4.total_charge ELSE 0 END), 0)::numeric AS rev_14,
          COALESCE(SUM(CASE WHEN br4.origin_actual_departure::date BETWEEN ${p_ms} AND ${p_w14e2}
                            THEN br4.total_charge ELSE 0 END), 0)::numeric AS rev_mtd
        FROM public.mcleod_gld_budget_report_v4 br4
        WHERE {where_proj}
    """

    prod_rows, bud_rows, proj_row = await asyncio.gather(
        pool.fetch(prod_sql, *prod_params),
        pool.fetch(bud_sql, *bud_params),
        pool.fetchrow(proj_sql, *proj_params),
    )

    prod_map = {r["month_start"]: r for r in prod_rows}
    bud_map = {r["month_start"]: r for r in bud_rows}

    rev_14 = _safe_float(proj_row["rev_14"]) if proj_row else 0.0
    rev_mtd = _safe_float(proj_row["rev_mtd"]) if proj_row else 0.0
    # ((rev_14 / 14) * pending_workdays) + rev_mtd → end-of-month projection.
    projected_tm = (rev_14 / 14.0) * pending_workdays + rev_mtd if rev_14 else rev_mtd

    out = []
    for ms, _ in months:
        p = prod_map.get(ms)
        b = bud_map.get(ms)
        out.append({
            "month_start": ms.isoformat(),
            "volume": int(p["volume"]) if p else 0,
            "revenue": _safe_float(p["revenue"]) if p else 0.0,
            "profit": _safe_float(p["profit"]) if p else 0.0,
            "margin_pct": (
                _safe_float(p["profit"]) / _safe_float(p["revenue"]) * 100.0
                if p and _safe_float(p["revenue"]) else 0.0
            ),
            "losses": _safe_float(p["losses"]) if p else 0.0,
            "budget_revenue": _safe_float(b["budget_revenue"]) if b else 0.0,
            "budget_profit":  _safe_float(b["budget_profit"])  if b else 0.0,
            "budget_loads":   _safe_float(b["budget_loads"])   if b else 0.0,
        })

    return {
        "success": True,
        "data": {
            "months": out,
            "projected_tm": _safe_float(projected_tm),
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

    Variance convention follows Bruno's literal spec: ``budget − actual``
    (positive = under-performing actuals). The Volume formula was a typo
    (``loads_budget − loads_budget``) — corrected to ``loads_budget − loads_actual``.
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

    loads_var   = _safe_float(row["loads_budget"])   - _safe_float(row["loads_actual"])
    revenue_var = _safe_float(row["revenue_budget"]) - _safe_float(row["revenue_actual"])
    profit_var  = _safe_float(row["profit_budget"])  - _safe_float(row["profit_actual"])
    margin_var_pct = (profit_var / revenue_var * 100.0) if revenue_var else 0.0
    rev_x_l = (revenue_var / loads_var) if loads_var else 0.0
    prof_x_l = (profit_var / loads_var) if loads_var else 0.0

    return {
        "success": True,
        "data": {
            # "Customers" = active_customers − inactive_customers (Bruno's spec).
            # in_scope_customers − inactive_customers = active_customers, so
            # the displayed "Customers" variance is ``active − (in_scope − active)``
            # i.e. ``2*active − in_scope``. Mirrors his literal formula:
            # count(customer_name) − count(customer_name where loads_actual=0).
            "customers": (int(row["active_customers"] or 0)
                          - (int(row["in_scope_customers"] or 0)
                             - int(row["active_customers"] or 0))),
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

    rows = await pool.fetch(
        f"""
        WITH {CUSTOMER_TEAM_CTE}
        SELECT
          budget."Customer Name" AS customer_name,
          COALESCE(SUM(budget."Loads Budget"),    0)
            - COALESCE(SUM(budget."Loads Actual"),    0) AS volume_var,
          COALESCE(SUM(budget."Profit Budget"),   0)
            - COALESCE(SUM(budget."Profit Actual"),   0) AS profit_var,
          COALESCE(SUM(budget."Revenue Budget"),  0)
            - COALESCE(SUM(budget."Revenue Actual"),  0) AS revenue_var
        FROM public.daily_production_budget_report budget
        JOIN customer_team ct ON TRIM(budget."Customer Name") = ct.customer_name
        WHERE budget."Date" BETWEEN $1 AND $2
        {extra}
        GROUP BY budget."Customer Name"
        ORDER BY ABS(COALESCE(SUM(budget."Profit Budget"),0)
                   - COALESCE(SUM(budget."Profit Actual"),0)) DESC NULLS LAST
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
    limit: int = Query(50, ge=1, le=200),
    _user: dict = Depends(require_report_access("ops-portal-overview")),
):
    """§4 Customer Monthly Losses — one row per customer."""
    pool = get_datalake_gold_pool(request)
    s, e = _resolve_range(range, start_date, end_date)
    params: list = []
    where = _v4_scope_where("br4", team, customer, load_type, params)
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
          AND br4.origin_actual_departure::date BETWEEN ${p_s} AND ${p_e}
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
    where = _v4_scope_where("br4", team, customer, load_type, prod_params)
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
                       br4.total_charge, br4.margin_amt,
                       COALESCE(otp.scorecard_count_otp, 0) AS otp_cnt,
                       COALESCE(otd.scorecard_count_otd, 0) AS otd_cnt
                FROM public.mcleod_gld_budget_report_v4 br4
                LEFT JOIN otp ON TRIM(br4.id)=otp.id_key AND TRIM(br4.company_id)=otp.company_id_key
                LEFT JOIN otd ON TRIM(br4.id)=otd.id_key AND TRIM(br4.company_id)=otd.company_id_key
                WHERE {where}
                  AND br4.origin_actual_departure::date BETWEEN ${p_s} AND ${p_e}
             )
        SELECT
          COUNT(DISTINCT customer_name) AS customers,
          COUNT(DISTINCT (origin || ' - ' || dest))
            FILTER (WHERE origin <> '' AND dest <> '') AS lanes,
          COUNT(*) FILTER (WHERE total_charge IS NOT NULL AND total_charge <> 0) AS volume,
          COALESCE(SUM(total_charge), 0)::numeric AS revenue,
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
    where_attr = _v4_scope_where("br4", team, customer, load_type, attr_params)
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

    prod_row, sav_row, attr_row = await asyncio.gather(
        pool.fetchrow(prod_sql, *prod_params),
        pool.fetchrow(sav_sql, *sav_params),
        pool.fetchrow(attr_sql, *attr_params),
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
    _user: dict = Depends(require_report_access("ops-portal-overview")),
):
    """§6 Team Monthly Projection — last 14 calendar days extrapolated to EoM.

    Date filter intentionally ignored (the projection always uses the rolling
    14-day window from yesterday). Team + Customer apply.
    """
    pool = get_datalake_gold_pool(request)
    today = cst_today()
    m_start, m_end = _month_bounds(today)
    win14_start = today - timedelta(days=14)
    win14_end = today - timedelta(days=1)
    pending_workdays = _count_workdays(today, m_end)

    params: list = []
    where = _v4_scope_where("br4", team, customer, load_type, params)
    params.extend([win14_start, win14_end, m_start, win14_end, m_start, m_end])
    p_w14s = len(params) - 5
    p_w14e = len(params) - 4
    p_ms1  = len(params) - 3
    p_w14e2 = len(params) - 2
    p_ms2  = len(params) - 1
    p_me   = len(params)

    row = await pool.fetchrow(
        f"""
        SELECT
          COUNT(*) FILTER (WHERE br4.origin_actual_departure::date BETWEEN ${p_w14s} AND ${p_w14e}
                             AND br4.total_charge IS NOT NULL
                             AND br4.total_charge <> 0) AS vol_14,
          COALESCE(SUM(CASE WHEN br4.origin_actual_departure::date BETWEEN ${p_w14s} AND ${p_w14e}
                            THEN br4.total_charge END), 0)::numeric AS rev_14,
          COALESCE(SUM(CASE WHEN br4.origin_actual_departure::date BETWEEN ${p_w14s} AND ${p_w14e}
                            THEN br4.margin_amt END), 0)::numeric AS prof_14,
          COUNT(*) FILTER (WHERE br4.origin_actual_departure::date BETWEEN ${p_ms1} AND ${p_w14e2}
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

    avg_vol_day  = _safe_float(row["vol_14"]) / 14.0
    avg_rev_day  = _safe_float(row["rev_14"]) / 14.0
    avg_prof_day = _safe_float(row["prof_14"]) / 14.0

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
    _user: dict = Depends(require_report_access("ops-portal-overview")),
):
    """Horizontal gauge under the chart. Always current month MTD."""
    pool = get_datalake_gold_pool(request)
    today = cst_today()
    m_start, m_end = _month_bounds(today)

    # Production MTD profit
    p_params: list = []
    where = _v4_scope_where("br4", team, customer, load_type, p_params)
    p_params.extend([m_start, today])
    p_s = len(p_params) - 1
    p_e = len(p_params)
    prod_sql = f"""
        SELECT COALESCE(SUM(br4.margin_amt), 0)::numeric AS profit_mtd
        FROM public.mcleod_gld_budget_report_v4 br4
        WHERE {where}
          AND br4.origin_actual_departure::date BETWEEN ${p_s} AND ${p_e}
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
    sort: str = Query("revenue_desc"),
    limit: int = Query(100, ge=1, le=500),
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
    p_params: list = []
    where = _v4_scope_where("br4", team, customer, load_type, p_params)
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
                  AND br4.origin_actual_departure::date BETWEEN ${p_s} AND ${p_e}
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
    # variance row still shows the gap.
    for name, b in bud_map.items():
        vol_budget = _safe_float(b["vol_budget"])
        rev_budget = _safe_float(b["rev_budget"])
        prof_budget = _safe_float(b["prof_budget"])
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
    out.sort(key=sort_key)
    out = out[:limit]

    return {
        "success": True,
        "data": out,
        "meta": {
            "window": {"start": s.isoformat(), "end": e.isoformat()},
            "pending_workdays": pending_workdays,
            "total": len(out),
        },
    }
