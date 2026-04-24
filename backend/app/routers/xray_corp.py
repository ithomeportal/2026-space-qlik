"""Code-made report: XRay CORP Mng — management X-Ray for CORP teams.

Mirrors Bruno's Qlik app (4b45853f-057b-4710-a4b8-38a98856cd5e) as a portal
custom report. Scope: TEAM1-5 only, company TMS/TMS3, status D/P, excluding
OILTEX customers. Mobile-only embed of the Qlik version is not a goal — we
rebuild all 23 PDF pages with direct SQL against aivn_datalake_gold.

Data sources (all on SAVINGS_DATABASE_URL / get_datalake_gold_pool):
- public.mcleod_gld_budget_report_v4  (load-level production)
- public.mcleod_gld_scorecard          (OTP/OTD counters + origin/dest timing)
- public.mcleod_gld_movement           (carrier/payee name, last ~45 days)
- public.daily_production_budget_report (Profit-TM card only)
- public.carriers_savings_results_report (savings trio)

Filter contract (all endpoints accept these as query params):
- range: "full" | "ytd" | "custom" — shapes start_date/end_date
- start_date, end_date: ISO dates (used when range="custom")
- team:   single team "TEAM1".."TEAM5" or empty for all
- customer: single customer name or empty for all

Panels marked "should not change with date filter" on the PDF are implemented
as endpoints that accept but ignore the date params — they compute their own
sticky window (yesterday, this/last week, this/last month, last N weeks, etc.).
"""

from __future__ import annotations

import asyncio
from datetime import date, datetime, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, Query, Request

from app.routers.deps import get_datalake_gold_pool, require_tag_role

XRAY_ROLES = ("CEO", "Executive", "CORP", "Operations", "Finance")

YEAR_START = date(2026, 1, 1)
YEAR_END = date(2026, 12, 31)

# CORP-only scope, echoed across every SQL statement.
CORP_TEAMS = ("TEAM1", "TEAM2", "TEAM3", "TEAM4", "TEAM5")
CORP_COMPANIES = ("TMS", "TMS3")
OPEN_STATUSES = ("D", "P")

# EDI standard codes that qualify as OTP / OTD events in the scorecard
# (copied verbatim from Bruno's Qlik load script).
OTP_CODES = ("T4", "T3", "D1", "D2", "BO", "BE", "AL", "AI", "AH", "AF", "A5", "A2")
OTD_CODES = ("AL", "D2", "AZ", "AH", "BE", "D1", "A5", "AI", "AF", "A2", "A1", "AU", "U3")

# Throughput Utilization (TU) constants — capacity per team for day/week/month.
# These are goals; the TU metric is (loads) / (GOAL * team_count).
TU_DAY = 25
TU_WEEK = 125
TU_MONTH = 500

# Monthly profit goal per team (shown in Profit-TM card context if we ever need it).
# Not currently used but kept here for reference.
PROFIT_GOAL_PER_TEAM = 55_000

router = APIRouter(tags=["xray-corp"], prefix="/custom/xray-corp")


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
    """Expand the 3-mode range selector into a concrete [start, end] pair."""
    today = date.today()
    today_clamped = max(YEAR_START, min(YEAR_END, today))
    if rng == "ytd":
        return YEAR_START, today_clamped
    if rng == "custom":
        s = _clamp(start_date, YEAR_START)
        e = _clamp(end_date, YEAR_END)
        if e < s:
            s, e = e, s
        return s, e
    # default: full year
    return YEAR_START, YEAR_END


def _scope_where(
    alias: str,
    team: Optional[str],
    customer: Optional[str],
    params: list,
) -> str:
    """Common CORP-scope WHERE clauses for the budget_report_v4 load-level table.

    `alias` is the SQL alias of the budget_report_v4 table.
    Pushes $-placeholders onto `params` and returns the WHERE fragment.
    """
    parts = [
        f"TRIM({alias}.team_id) = ANY($" + str(len(params) + 1) + ")",
    ]
    params.append(list(CORP_TEAMS))
    parts.append(f"TRIM({alias}.company_id) = ANY($" + str(len(params) + 1) + ")")
    params.append(list(CORP_COMPANIES))
    parts.append(f"TRIM({alias}.status) = ANY($" + str(len(params) + 1) + ")")
    params.append(list(OPEN_STATUSES))
    parts.append(f"UPPER(COALESCE({alias}.customer_name,'')) NOT LIKE '%OILTEX%'")
    if team:
        parts.append(f"TRIM({alias}.team_id) = $" + str(len(params) + 1))
        params.append(team)
    if customer:
        parts.append(f"{alias}.customer_name = $" + str(len(params) + 1))
        params.append(customer)
    return " AND ".join(parts)


def _pad_variants(values) -> list[str]:
    """Expand each value into unpadded + 3-space-padded twins.

    mcleod_gld_scorecard stores text columns inconsistently: sometimes `'TEAM1'`,
    sometimes `'TEAM1   '` (CHAR(8)-style padding). Covering both in the WHERE
    clause lets PostgreSQL use a plain btree index on the column (no expression
    indexes needed) — which is the difference between a ~200ms seek and a
    multi-minute full-table sequential scan.
    """
    seen: set[str] = set()
    out: list[str] = []
    for v in values:
        for cand in (v, v + "   "):
            if cand not in seen:
                seen.add(cand)
                out.append(cand)
    return out


def _scorecard_cte(kind: str) -> str:
    """Return a CTE that rolls the scorecard table up into per-order OTP / OTD counts.

    `kind` is "otp" or "otd". Codes and stop_types differ between the two.
    Every WHERE predicate uses direct equality (no TRIM) against both padded
    and unpadded literal variants, so the planner can use any existing btree
    index on `team_id`, `company_id`, `stop_type`, etc. TRIM is kept ONLY on
    the GROUP BY output so downstream joins against `TRIM(br4.id)` still match.
    """
    if kind == "otp":
        codes = OTP_CODES
        stops = ("", "PU", "SH")
        out = "scorecard_count_otp"
    else:
        codes = OTD_CODES
        stops = ("", "CO", "SO")
        out = "scorecard_count_otd"

    def _lit(values) -> str:
        return ",".join(f"'{v}'" for v in _pad_variants(values))

    codes_sql = _lit(codes)
    stops_sql = _lit(stops)
    teams_sql = _lit(CORP_TEAMS)
    companies_sql = _lit(CORP_COMPANIES)
    statuses_sql = _lit(OPEN_STATUSES)
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


def _business_days_between(start: date, end: date) -> int:
    """Mon–Sat business-day count (US calendar, no holidays)."""
    if end < start:
        return 0
    d, n = start, 0
    while d <= end:
        if d.weekday() != 6:  # 6 = Sunday
            n += 1
        d += timedelta(days=1)
    return n


def _month_bounds(today: date) -> tuple[date, date, date, date, int, int]:
    """Return (month_start, month_end, last_month_start, last_month_end,
    past_business_days, pending_business_days) for the current calendar month.
    """
    m_start = today.replace(day=1)
    # next month first day - 1 day
    if m_start.month == 12:
        m_end = m_start.replace(year=m_start.year + 1, month=1) - timedelta(days=1)
    else:
        m_end = m_start.replace(month=m_start.month + 1) - timedelta(days=1)
    # previous month
    lm_end = m_start - timedelta(days=1)
    lm_start = lm_end.replace(day=1)
    past = _business_days_between(m_start, today)
    pending = _business_days_between(today + timedelta(days=1), m_end)
    return m_start, m_end, lm_start, lm_end, past, pending


def _week_bounds(today: date) -> tuple[date, date, date, date]:
    """Week bounds (Mon–Sun). Returns (this_week_start, this_week_end,
    last_week_start, last_week_end).
    """
    monday = today - timedelta(days=today.weekday())
    sunday = monday + timedelta(days=6)
    last_mon = monday - timedelta(days=7)
    last_sun = last_mon + timedelta(days=6)
    return monday, sunday, last_mon, last_sun


# ---------------------------------------------------------------------------
# Filters endpoint — powers the customer autosuggest + team list
# ---------------------------------------------------------------------------


@router.get("/filters")
async def filters(
    request: Request,
    _user: dict = Depends(require_tag_role(*XRAY_ROLES)),
):
    """Teams + distinct customer list in scope."""
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
# Tab 1 — Overview
# ---------------------------------------------------------------------------


@router.get("/kpis")
async def kpis(
    request: Request,
    range: Optional[str] = Query("ytd"),
    start_date: Optional[date] = Query(None),
    end_date: Optional[date] = Query(None),
    team: Optional[str] = Query(None),
    customer: Optional[str] = Query(None),
    _user: dict = Depends(require_tag_role(*XRAY_ROLES)),
):
    """Top KPIs + Profit-TM + Savings trio.

    - KPIs (Loads / Revenue / Profit / Margin / OTP / OTD) respect RANGE+team+customer.
    - Loss Loads respects RANGE+team+customer (it's a derived KPI).
    - Profit-TM is "current month only" regardless of RANGE.
    - Savings trio default: current-month; honors RANGE when user changes it.
    """
    pool = get_datalake_gold_pool(request)
    s, e = _resolve_range(range, start_date, end_date)
    today = date.today()
    m_start, m_end, _, _, _, _ = _month_bounds(today)

    # ---- KPIs + Loss Loads via production query --------------------------
    params: list = []
    where = _scope_where("br4", team, customer, params)
    params.extend([s, e])
    date_fragment = (
        f"br4.origin_actual_departure::date BETWEEN ${len(params) - 1} AND ${len(params)}"
    )

    kpi_task = pool.fetchrow(
        f"""
        WITH otp AS ({_scorecard_cte("otp")}),
             otd AS ({_scorecard_cte("otd")}),
             prod AS (
                SELECT br4.id, br4.company_id, br4.total_charge, br4.margin_amt,
                       COALESCE(otp.scorecard_count_otp, 0) AS otp_cnt,
                       COALESCE(otd.scorecard_count_otd, 0) AS otd_cnt
                FROM public.mcleod_gld_budget_report_v4 br4
                LEFT JOIN otp ON TRIM(br4.id)=otp.id_key AND br4.company_id=otp.company_id_key
                LEFT JOIN otd ON TRIM(br4.id)=otd.id_key AND br4.company_id=otd.company_id_key
                WHERE {where}
                  AND {date_fragment}
             )
        SELECT
          COUNT(*) FILTER (WHERE total_charge IS NOT NULL AND total_charge <> 0) AS loads,
          COALESCE(SUM(total_charge), 0)::numeric AS revenue,
          COALESCE(SUM(margin_amt), 0)::numeric   AS profit,
          CASE WHEN SUM(total_charge) > 0
               THEN SUM(margin_amt)::numeric / SUM(total_charge)::numeric
               ELSE 0 END AS margin_pct,
          CASE WHEN COUNT(*) FILTER (WHERE total_charge IS NOT NULL AND total_charge <> 0) > 0
               THEN 1.0 - (SUM(otp_cnt)::numeric
                          / COUNT(*) FILTER (WHERE total_charge IS NOT NULL AND total_charge <> 0))
               ELSE 0 END AS otp_pct,
          CASE WHEN COUNT(*) FILTER (WHERE total_charge IS NOT NULL AND total_charge <> 0) > 0
               THEN 1.0 - (SUM(otd_cnt)::numeric
                          / COUNT(*) FILTER (WHERE total_charge IS NOT NULL AND total_charge <> 0))
               ELSE 0 END AS otd_pct,
          COUNT(*) FILTER (
              WHERE margin_amt < 0 AND total_charge IS NOT NULL AND total_charge <> 0
          ) AS loss_loads
        FROM prod
        """,
        *params,
    )

    # ---- Profit-TM (current calendar month) ------------------------------
    # daily_production_budget_report aggregates "Profit Actual" per (Date, Customer).
    # Team ID lives in the v4 table, so resolve per customer via ALLOWED_TEAMS.
    tm_params: list = [m_start, m_end, list(CORP_TEAMS)]
    tm_extra = ""
    if team:
        tm_params.append(team)
        tm_extra += f" AND ct.team_id = ${len(tm_params)}"
    if customer:
        tm_params.append(customer)
        tm_extra += f" AND budget.\"Customer Name\" = ${len(tm_params)}"
    profit_tm_task = pool.fetchval(
        f"""
        WITH customer_team AS (
            SELECT customer_name, team_id FROM (
                SELECT
                    TRIM(customer_name) AS customer_name,
                    TRIM(team_id)       AS team_id,
                    ROW_NUMBER() OVER (
                        PARTITION BY TRIM(customer_name)
                        ORDER BY COUNT(*) DESC, TRIM(team_id)
                    ) AS rn
                FROM public.mcleod_gld_budget_report_v4
                WHERE TRIM(team_id) = ANY($3)
                GROUP BY TRIM(customer_name), TRIM(team_id)
            ) ranked
            WHERE rn = 1
        )
        SELECT COALESCE(SUM(budget."Profit Actual"), 0)::numeric
        FROM public.daily_production_budget_report budget
        JOIN customer_team ct ON TRIM(budget."Customer Name") = ct.customer_name
        WHERE budget."Date" BETWEEN $1 AND $2
        {tm_extra}
        """,
        *tm_params,
    )

    # ---- Savings trio (default current month, honors RANGE) --------------
    # When range="ytd" / "custom" with a different window, use that instead of current month.
    sav_start = s if range in ("ytd", "custom") else m_start
    sav_end = e if range in ("ytd", "custom") else m_end
    sav_params: list = [sav_start, sav_end]
    sav_extra = " AND UPPER(COALESCE(cs.customer_name,'')) NOT LIKE '%OILTEX%'"
    if customer:
        sav_params.append(customer)
        sav_extra += f" AND cs.customer_name = ${len(sav_params)}"
    # Savings trio excludes TEAM-DFW per the PDF; when a specific team is
    # chosen, we further filter by it in the customer_team mapping below.
    sav_team_filter = ""
    if team:
        sav_params.append(team)
        sav_team_filter = f" AND ct.team_id = ${len(sav_params)}"
    sav_task = pool.fetchrow(
        f"""
        WITH customer_team AS (
            SELECT customer_name, team_id FROM (
                SELECT
                    TRIM(customer_name) AS customer_name,
                    TRIM(team_id)       AS team_id,
                    ROW_NUMBER() OVER (
                        PARTITION BY TRIM(customer_name)
                        ORDER BY COUNT(*) DESC, TRIM(team_id)
                    ) AS rn
                FROM public.mcleod_gld_budget_report_v4
                WHERE TRIM(team_id) = ANY(ARRAY['TEAM1','TEAM2','TEAM3','TEAM4','TEAM5'])
                GROUP BY TRIM(customer_name), TRIM(team_id)
            ) ranked
            WHERE rn = 1
        )
        SELECT
          COALESCE(SUM(CASE WHEN cs.variance > 0 THEN cs.variance ELSE 0 END), 0)::numeric AS total_savings,
          COALESCE(SUM(CASE WHEN cs.variance < 0 THEN cs.variance ELSE 0 END), 0)::numeric AS total_overpay,
          COALESCE(SUM(cs.variance), 0)::numeric AS net_variance
        FROM public.carriers_savings_results_report cs
        JOIN customer_team ct ON TRIM(cs.customer_name) = ct.customer_name
        WHERE cs.month_date BETWEEN $1 AND $2
        {sav_extra}
        {sav_team_filter}
        """,
        *sav_params,
    )

    # Run the three independent reads concurrently — saves ~2/3 of total latency.
    kpi_row, profit_tm, sav_row = await asyncio.gather(kpi_task, profit_tm_task, sav_task)

    return {
        "success": True,
        "data": {
            "loads": int(kpi_row["loads"] or 0),
            "revenue": float(kpi_row["revenue"] or 0),
            "profit": float(kpi_row["profit"] or 0),
            "margin_pct": float(kpi_row["margin_pct"] or 0) * 100.0,
            "otp_pct": float(kpi_row["otp_pct"] or 0) * 100.0,
            "otd_pct": float(kpi_row["otd_pct"] or 0) * 100.0,
            "loss_loads": int(kpi_row["loss_loads"] or 0),
            "profit_tm": float(profit_tm or 0),
            "total_savings": float(sav_row["total_savings"] or 0),
            "total_overpay": float(sav_row["total_overpay"] or 0),
            "net_variance": float(sav_row["net_variance"] or 0),
            "window": {"start": s.isoformat(), "end": e.isoformat()},
        },
    }


@router.get("/trio-tables")
async def trio_tables(
    request: Request,
    team: Optional[str] = Query(None),
    customer: Optional[str] = Query(None),
    _user: dict = Depends(require_tag_role(*XRAY_ROLES)),
):
    """Yesterday / This Week / This Month team-summary triplet.

    Does NOT respect the RANGE filter (per PDF). Respects team+customer.
    Returns one row per team per window, plus totals.
    """
    pool = get_datalake_gold_pool(request)
    today = date.today()
    yesterday = today - timedelta(days=1)
    m_start, _, _, _, _, _ = _month_bounds(today)
    w_start, _, _, _ = _week_bounds(today)

    # When a single team is filtered, totals row capacity = 1 × goal (not 5 ×).
    total_team_count = 1 if team else len(CORP_TEAMS)

    async def _window(d_from: date, d_to: date, capacity: int) -> dict:
        params: list = []
        where = _scope_where("br4", team, customer, params)
        params.extend([d_from, d_to])
        date_frag = (
            f"br4.origin_actual_departure::date BETWEEN ${len(params)-1} AND ${len(params)}"
        )
        rows = await pool.fetch(
            f"""
            WITH otp AS ({_scorecard_cte("otp")}),
                 otd AS ({_scorecard_cte("otd")}),
                 prod AS (
                    SELECT TRIM(br4.team_id) AS team_id,
                           br4.id, br4.company_id, br4.total_charge, br4.margin_amt,
                           COALESCE(otp.scorecard_count_otp, 0) AS otp_cnt,
                           COALESCE(otd.scorecard_count_otd, 0) AS otd_cnt
                    FROM public.mcleod_gld_budget_report_v4 br4
                    LEFT JOIN otp ON TRIM(br4.id)=otp.id_key AND br4.company_id=otp.company_id_key
                    LEFT JOIN otd ON TRIM(br4.id)=otd.id_key AND br4.company_id=otd.company_id_key
                    WHERE {where} AND {date_frag}
                 )
            SELECT
              team_id,
              COUNT(*) FILTER (WHERE total_charge IS NOT NULL AND total_charge <> 0) AS vol,
              COALESCE(SUM(total_charge), 0)::numeric AS rev,
              COALESCE(SUM(margin_amt), 0)::numeric AS prof,
              SUM(otp_cnt) AS otp_sum,
              SUM(otd_cnt) AS otd_sum,
              COUNT(DISTINCT id) FILTER (WHERE total_charge IS NOT NULL AND total_charge <> 0) AS load_ids
            FROM prod
            GROUP BY ROLLUP(team_id)
            ORDER BY team_id NULLS FIRST
            """,
            *params,
        )
        totals = None
        teams_out = []
        for r in rows:
            vol = int(r["vol"] or 0)
            rev = float(r["rev"] or 0)
            prof = float(r["prof"] or 0)
            load_ids = int(r["load_ids"] or 0)
            otp_sum = int(r["otp_sum"] or 0)
            otd_sum = int(r["otd_sum"] or 0)
            pl_count = load_ids or 1
            row_out = {
                "team": r["team_id"] or "Totals",
                "vol": vol,
                "rev": rev,
                "prof": prof,
                "m_pct": (prof / rev * 100.0) if rev else None,
                "otp_pct": ((1 - otp_sum / vol) * 100.0) if vol else None,
                "otd_pct": ((1 - otd_sum / vol) * 100.0) if vol else None,
                "tu": (vol / (capacity * (total_team_count if r["team_id"] is None else 1))) * 100.0,
                "r_per_l": rev / pl_count if pl_count else 0.0,
                "p_per_l": prof / pl_count if pl_count else 0.0,
            }
            if r["team_id"] is None:
                totals = row_out
            else:
                teams_out.append(row_out)
        return {"totals": totals, "teams": teams_out}

    yesterday_data, week_data, month_data = await asyncio.gather(
        _window(yesterday, yesterday, TU_DAY),
        _window(w_start, today, TU_WEEK),
        _window(m_start, today, TU_MONTH),
    )
    return {
        "success": True,
        "data": {
            "yesterday": {"from": yesterday.isoformat(), "to": yesterday.isoformat(), **yesterday_data},
            "week": {"from": w_start.isoformat(), "to": today.isoformat(), **week_data},
            "month": {"from": m_start.isoformat(), "to": today.isoformat(), **month_data},
        },
    }


@router.get("/projection")
async def projection(
    request: Request,
    team: Optional[str] = Query(None),
    customer: Optional[str] = Query(None),
    _user: dict = Depends(require_tag_role(*XRAY_ROLES)),
):
    """Customers / Lanes / AVG Vol/Profit per day/week / Projected month totals.

    These numbers are rolling (previous 14 business days, last 3 weeks,
    this-month-to-date) and ignore the RANGE filter.
    """
    pool = get_datalake_gold_pool(request)
    today = date.today()
    m_start, m_end, _, _, past, pending = _month_bounds(today)

    # Find the window that contains the last 14 business days (Mon–Sat).
    bdays, d = [], today - timedelta(days=1)
    while len(bdays) < 14:
        if d.weekday() != 6:  # skip Sunday
            bdays.append(d)
        d -= timedelta(days=1)
    prev_14_end = bdays[0]
    prev_14_start = bdays[-1]

    # Last 3 complete ISO weeks before this week.
    monday = today - timedelta(days=today.weekday())
    three_weeks_start = monday - timedelta(days=7 * 3)
    three_weeks_end = monday - timedelta(days=1)

    params: list = []
    where = _scope_where("br4", team, customer, params)
    p14s = len(params) + 1; params.append(prev_14_start)
    p14e = len(params) + 1; params.append(prev_14_end)
    p3ws = len(params) + 1; params.append(three_weeks_start)
    p3we = len(params) + 1; params.append(three_weeks_end)
    pms  = len(params) + 1; params.append(m_start)
    pme  = len(params) + 1; params.append(today)

    row = await pool.fetchrow(
        f"""
        WITH prod AS (
            SELECT TRIM(br4.origin_name) AS origin, TRIM(br4.dest_name) AS dest,
                   br4.customer_name,
                   br4.total_charge, br4.margin_amt,
                   br4.origin_actual_departure::date AS dep_date
            FROM public.mcleod_gld_budget_report_v4 br4
            WHERE {where}
        )
        SELECT
          COUNT(*) FILTER (
              WHERE dep_date BETWEEN ${p14s} AND ${p14e}
                AND total_charge IS NOT NULL AND total_charge <> 0
          ) AS vol_14,
          COALESCE(SUM(margin_amt) FILTER (
              WHERE dep_date BETWEEN ${p14s} AND ${p14e}
                AND total_charge IS NOT NULL AND total_charge <> 0
          ), 0)::numeric AS profit_14,
          COUNT(*) FILTER (
              WHERE dep_date BETWEEN ${p3ws} AND ${p3we}
                AND total_charge IS NOT NULL AND total_charge <> 0
          ) AS vol_3w,
          COALESCE(SUM(margin_amt) FILTER (
              WHERE dep_date BETWEEN ${p3ws} AND ${p3we}
                AND total_charge IS NOT NULL AND total_charge <> 0
          ), 0)::numeric AS profit_3w,
          COUNT(*) FILTER (
              WHERE dep_date BETWEEN ${pms} AND ${pme}
                AND total_charge IS NOT NULL AND total_charge <> 0
          ) AS vol_tm,
          COALESCE(SUM(margin_amt) FILTER (
              WHERE dep_date BETWEEN ${pms} AND ${pme}
                AND total_charge IS NOT NULL AND total_charge <> 0
          ), 0)::numeric AS profit_tm,
          COUNT(DISTINCT customer_name) FILTER (WHERE dep_date BETWEEN ${pms} AND ${pme}) AS cust_tm,
          COUNT(DISTINCT (origin || ' - ' || dest)) FILTER (
              WHERE dep_date BETWEEN ${pms} AND ${pme}
          ) AS lanes_tm
        FROM prod
        """,
        *params,
    )

    avg_vol_day = (row["vol_14"] or 0) / 14
    avg_profit_day = float(row["profit_14"] or 0) / 14
    avg_vol_week = (row["vol_3w"] or 0) / 3
    avg_profit_week = float(row["profit_3w"] or 0) / 3

    vol_tm = int(row["vol_tm"] or 0)
    profit_tm = float(row["profit_tm"] or 0)
    proj_vol_month = (vol_tm / past * pending + vol_tm) if past else vol_tm
    proj_profit_month = (profit_tm / past * pending + profit_tm) if past else profit_tm

    return {
        "success": True,
        "data": {
            "total_customers": int(row["cust_tm"] or 0),
            "total_lanes": int(row["lanes_tm"] or 0),
            "avg_vol_day": avg_vol_day,
            "avg_vol_week": avg_vol_week,
            "projected_vol_month": proj_vol_month,
            "avg_profit_day": avg_profit_day,
            "avg_profit_week": avg_profit_week,
            "projected_profit_month": proj_profit_month,
            "past_days": past,
            "pending_days": pending,
        },
    }


# ---------------------------------------------------------------------------
# Tab 2 — Customers & Lanes
# ---------------------------------------------------------------------------


@router.get("/by-customer")
async def by_customer(
    request: Request,
    range: Optional[str] = Query("ytd"),
    start_date: Optional[date] = Query(None),
    end_date: Optional[date] = Query(None),
    team: Optional[str] = Query(None),
    customer: Optional[str] = Query(None),
    limit: int = Query(200, ge=1, le=1000),
    _user: dict = Depends(require_tag_role(*XRAY_ROLES)),
):
    """Profit by Customer — one row per customer in the applied window."""
    pool = get_datalake_gold_pool(request)
    s, e = _resolve_range(range, start_date, end_date)
    params: list = []
    where = _scope_where("br4", team, customer, params)
    params.extend([s, e, limit])
    date_frag = f"br4.origin_actual_departure::date BETWEEN ${len(params)-2} AND ${len(params)-1}"

    rows = await pool.fetch(
        f"""
        WITH otp AS ({_scorecard_cte("otp")}),
             otd AS ({_scorecard_cte("otd")}),
             prod AS (
                SELECT br4.customer_name, br4.id, br4.company_id,
                       br4.total_charge, br4.margin_amt,
                       COALESCE(otp.scorecard_count_otp, 0) AS otp_cnt,
                       COALESCE(otd.scorecard_count_otd, 0) AS otd_cnt
                FROM public.mcleod_gld_budget_report_v4 br4
                LEFT JOIN otp ON TRIM(br4.id)=otp.id_key AND br4.company_id=otp.company_id_key
                LEFT JOIN otd ON TRIM(br4.id)=otd.id_key AND br4.company_id=otd.company_id_key
                WHERE {where} AND {date_frag}
             )
        SELECT
          customer_name,
          COUNT(*) FILTER (WHERE total_charge IS NOT NULL AND total_charge <> 0) AS loads,
          COALESCE(SUM(total_charge), 0)::numeric AS revenue,
          COALESCE(SUM(margin_amt), 0)::numeric AS profit,
          CASE WHEN SUM(total_charge) > 0 THEN SUM(margin_amt)/SUM(total_charge)*100 ELSE 0 END AS margin_pct,
          CASE WHEN COUNT(*) FILTER (WHERE total_charge <> 0) > 0
               THEN (1 - SUM(otp_cnt)::numeric/COUNT(*) FILTER (WHERE total_charge <> 0))*100
               ELSE 0 END AS otp_pct,
          CASE WHEN COUNT(*) FILTER (WHERE total_charge <> 0) > 0
               THEN (1 - SUM(otd_cnt)::numeric/COUNT(*) FILTER (WHERE total_charge <> 0))*100
               ELSE 0 END AS otd_pct
        FROM prod
        WHERE customer_name IS NOT NULL AND TRIM(customer_name) <> ''
        GROUP BY customer_name
        ORDER BY profit DESC NULLS LAST
        LIMIT ${len(params)}
        """,
        *params,
    )
    return {"success": True, "data": [dict(r) for r in rows]}


@router.get("/by-lane")
async def by_lane(
    request: Request,
    range: Optional[str] = Query("ytd"),
    start_date: Optional[date] = Query(None),
    end_date: Optional[date] = Query(None),
    team: Optional[str] = Query(None),
    customer: Optional[str] = Query(None),
    limit: int = Query(200, ge=1, le=1000),
    _user: dict = Depends(require_tag_role(*XRAY_ROLES)),
):
    """Profit by Lane — one row per origin→destination pair in window."""
    pool = get_datalake_gold_pool(request)
    s, e = _resolve_range(range, start_date, end_date)
    params: list = []
    where = _scope_where("br4", team, customer, params)
    params.extend([s, e, limit])
    date_frag = f"br4.origin_actual_departure::date BETWEEN ${len(params)-2} AND ${len(params)-1}"

    rows = await pool.fetch(
        f"""
        WITH otp AS ({_scorecard_cte("otp")}),
             otd AS ({_scorecard_cte("otd")}),
             prod AS (
                SELECT TRIM(br4.origin_name) AS origin,
                       TRIM(br4.dest_name)   AS dest,
                       br4.id, br4.company_id, br4.total_charge, br4.margin_amt,
                       COALESCE(otp.scorecard_count_otp, 0) AS otp_cnt,
                       COALESCE(otd.scorecard_count_otd, 0) AS otd_cnt
                FROM public.mcleod_gld_budget_report_v4 br4
                LEFT JOIN otp ON TRIM(br4.id)=otp.id_key AND br4.company_id=otp.company_id_key
                LEFT JOIN otd ON TRIM(br4.id)=otd.id_key AND br4.company_id=otd.company_id_key
                WHERE {where} AND {date_frag}
             )
        SELECT
          (origin || ' - ' || dest) AS lane,
          COUNT(*) FILTER (WHERE total_charge IS NOT NULL AND total_charge <> 0) AS loads,
          COALESCE(SUM(total_charge), 0)::numeric AS revenue,
          COALESCE(SUM(margin_amt), 0)::numeric AS profit,
          CASE WHEN SUM(total_charge) > 0 THEN SUM(margin_amt)/SUM(total_charge)*100 ELSE 0 END AS margin_pct,
          CASE WHEN COUNT(*) FILTER (WHERE total_charge <> 0) > 0
               THEN (1 - SUM(otp_cnt)::numeric/COUNT(*) FILTER (WHERE total_charge <> 0))*100
               ELSE 0 END AS otp_pct,
          CASE WHEN COUNT(*) FILTER (WHERE total_charge <> 0) > 0
               THEN (1 - SUM(otd_cnt)::numeric/COUNT(*) FILTER (WHERE total_charge <> 0))*100
               ELSE 0 END AS otd_pct
        FROM prod
        WHERE origin <> '' AND dest <> ''
        GROUP BY origin, dest
        ORDER BY profit DESC NULLS LAST
        LIMIT ${len(params)}
        """,
        *params,
    )
    return {"success": True, "data": [dict(r) for r in rows]}


@router.get("/attrition")
async def attrition(
    request: Request,
    team: Optional[str] = Query(None),
    customer: Optional[str] = Query(None),
    limit: int = Query(200, ge=1, le=1000),
    _user: dict = Depends(require_tag_role(*XRAY_ROLES)),
):
    """Attrition by customer×lane — last load date + days since today. Ignores RANGE."""
    pool = get_datalake_gold_pool(request)
    params: list = []
    where = _scope_where("br4", team, customer, params)
    params.append(limit)

    rows = await pool.fetch(
        f"""
        WITH otp AS ({_scorecard_cte("otp")}),
             otd AS ({_scorecard_cte("otd")}),
             prod AS (
                SELECT br4.customer_name,
                       TRIM(br4.origin_name) AS origin,
                       TRIM(br4.dest_name)   AS dest,
                       br4.id, br4.company_id, br4.total_charge, br4.margin_amt,
                       br4.origin_actual_departure,
                       COALESCE(otp.scorecard_count_otp, 0) AS otp_cnt,
                       COALESCE(otd.scorecard_count_otd, 0) AS otd_cnt
                FROM public.mcleod_gld_budget_report_v4 br4
                LEFT JOIN otp ON TRIM(br4.id)=otp.id_key AND br4.company_id=otp.company_id_key
                LEFT JOIN otd ON TRIM(br4.id)=otd.id_key AND br4.company_id=otd.company_id_key
                WHERE {where}
             )
        SELECT
          customer_name,
          (origin || ' - ' || dest) AS lane,
          COUNT(*) FILTER (WHERE total_charge IS NOT NULL AND total_charge <> 0) AS loads,
          COALESCE(SUM(total_charge), 0)::numeric AS revenue,
          COALESCE(SUM(margin_amt), 0)::numeric AS profit,
          CASE WHEN SUM(total_charge) > 0 THEN SUM(margin_amt)/SUM(total_charge)*100 ELSE 0 END AS margin_pct,
          CASE WHEN COUNT(*) FILTER (WHERE total_charge <> 0) > 0
               THEN (1 - SUM(otp_cnt)::numeric/COUNT(*) FILTER (WHERE total_charge <> 0))*100
               ELSE 0 END AS otp_pct,
          CASE WHEN COUNT(*) FILTER (WHERE total_charge <> 0) > 0
               THEN (1 - SUM(otd_cnt)::numeric/COUNT(*) FILTER (WHERE total_charge <> 0))*100
               ELSE 0 END AS otd_pct,
          MAX(origin_actual_departure)::date AS last_load_date,
          (CURRENT_DATE - MAX(origin_actual_departure)::date) AS days_since
        FROM prod
        WHERE origin <> '' AND dest <> '' AND customer_name IS NOT NULL
        GROUP BY customer_name, origin, dest
        HAVING MAX(origin_actual_departure) IS NOT NULL
        ORDER BY days_since ASC NULLS LAST, profit DESC
        LIMIT ${len(params)}
        """,
        *params,
    )
    return {
        "success": True,
        "data": [
            {
                **dict(r),
                "last_load_date": r["last_load_date"].isoformat() if r["last_load_date"] else None,
            }
            for r in rows
        ],
    }


# ---------------------------------------------------------------------------
# Tab 3 — Teams Breakdown (TM / TW / LW / L2W..L5W)
# ---------------------------------------------------------------------------


@router.get("/teams-breakdown")
async def teams_breakdown(
    request: Request,
    customer: Optional[str] = Query(None),
    _user: dict = Depends(require_tag_role(*XRAY_ROLES)),
):
    """Per-team Loads / Profit / Margin across TM, TW, LW, L2W..L5W. Ignores RANGE+team."""
    pool = get_datalake_gold_pool(request)
    today = date.today()
    m_start, _, _, _, _, _ = _month_bounds(today)
    w_mon, _, _, _ = _week_bounds(today)

    # Build week buckets
    weeks = []
    for i in range(5):  # 0=LW, 1=L2W, 2=L3W, 3=L4W, 4=L5W
        end = w_mon - timedelta(days=1 + 7 * i)
        start = end - timedelta(days=6)
        weeks.append((f"l{i+1}w", start, end))
    # This week: w_mon..today
    ranges = [
        ("tm", m_start, today),
        ("tw", w_mon, today),
    ] + weeks

    params: list = []
    where = _scope_where("br4", None, customer, params)
    # Earliest window start
    min_start = min(r[1] for r in ranges)
    max_end = max(r[2] for r in ranges)
    params.extend([min_start, max_end])

    rows = await pool.fetch(
        f"""
        SELECT
          TRIM(br4.team_id) AS team_id,
          br4.origin_actual_departure::date AS dep_date,
          br4.total_charge, br4.margin_amt
        FROM public.mcleod_gld_budget_report_v4 br4
        WHERE {where}
          AND br4.origin_actual_departure::date BETWEEN ${len(params)-1} AND ${len(params)}
        """,
        *params,
    )

    def empty_bucket():
        return {"loads": 0, "revenue": 0.0, "profit": 0.0}

    teams_out: dict[str, dict[str, dict]] = {t: {r[0]: empty_bucket() for r in ranges} for t in CORP_TEAMS}
    totals = {r[0]: empty_bucket() for r in ranges}

    for r in rows:
        t = r["team_id"]
        if t not in teams_out:
            continue
        d = r["dep_date"]
        tc = float(r["total_charge"] or 0)
        ma = float(r["margin_amt"] or 0)
        for key, start, end in ranges:
            if start <= d <= end:
                if tc != 0:
                    teams_out[t][key]["loads"] += 1
                    totals[key]["loads"] += 1
                teams_out[t][key]["revenue"] += tc
                teams_out[t][key]["profit"] += ma
                totals[key]["revenue"] += tc
                totals[key]["profit"] += ma

    def compute(agg):
        out = {}
        for k, v in agg.items():
            out[k] = {
                "loads": v["loads"],
                "revenue": v["revenue"],
                "profit": v["profit"],
                "margin_pct": (v["profit"] / v["revenue"] * 100.0) if v["revenue"] else 0.0,
            }
        # AVG L5W = mean of l1w..l5w loads/profit/margin
        keys5 = ["l1w", "l2w", "l3w", "l4w", "l5w"]
        out["avg_l5w"] = {
            "loads": sum(out[k]["loads"] for k in keys5) / 5,
            "revenue": sum(out[k]["revenue"] for k in keys5) / 5,
            "profit": sum(out[k]["profit"] for k in keys5) / 5,
            "margin_pct": sum(out[k]["margin_pct"] for k in keys5) / 5,
        }
        # AVG L5W - LW (delta)
        out["avg_l5w_minus_lw"] = {
            "loads": out["avg_l5w"]["loads"] - out["l1w"]["loads"],
            "revenue": out["avg_l5w"]["revenue"] - out["l1w"]["revenue"],
            "profit": out["avg_l5w"]["profit"] - out["l1w"]["profit"],
            "margin_pct": out["avg_l5w"]["margin_pct"] - out["l1w"]["margin_pct"],
        }
        return out

    return {
        "success": True,
        "data": {
            "teams": [{"team": t, **compute(teams_out[t])} for t in CORP_TEAMS],
            "totals": compute(totals),
        },
    }


# ---------------------------------------------------------------------------
# Tab 4 — Trends
# ---------------------------------------------------------------------------


@router.get("/trends")
async def trends(
    request: Request,
    team: Optional[str] = Query(None),
    customer: Optional[str] = Query(None),
    _user: dict = Depends(require_tag_role(*XRAY_ROLES)),
):
    """Daily / weekly / monthly rollups for all trend charts. Ignores RANGE.

    Returns:
      - day:   last 15 calendar days (for loads/revenue/profit/margin bar charts)
      - week:  last 12 ISO weeks      (for by-week charts + rev-vs-CC/L)
      - month: last 15 months          (for by-month combo charts + rev-vs-CC/L)
    """
    pool = get_datalake_gold_pool(request)
    today = date.today()
    day_start = today - timedelta(days=14)
    week_start = (today - timedelta(days=today.weekday())) - timedelta(days=7 * 11)
    month_start = date(today.year, today.month, 1)
    # Step back 14 whole months, then truncate to 1st
    y, m = month_start.year, month_start.month
    for _ in range(14):
        m -= 1
        if m == 0:
            m = 12
            y -= 1
    month_start = date(y, m, 1)

    params: list = []
    where = _scope_where("br4", team, customer, params)
    params.append(min(day_start, week_start, month_start))

    rows = await pool.fetch(
        f"""
        SELECT
          br4.origin_actual_departure::date AS dep_date,
          br4.total_charge,
          br4.margin_amt,
          br4.total_carrier_pay
        FROM public.mcleod_gld_budget_report_v4 br4
        WHERE {where}
          AND br4.origin_actual_departure::date >= ${len(params)}
        """,
        *params,
    )

    # Aggregate in Python — rows cap is bounded by window size × CORP volume.
    def bucket(d: date, mode: str) -> date:
        if mode == "day":
            return d
        if mode == "week":
            return d - timedelta(days=d.weekday())  # Monday
        return date(d.year, d.month, 1)

    def empty():
        return {"loads": 0, "revenue": 0.0, "profit": 0.0, "carrier_pay": 0.0}

    day_agg: dict[date, dict] = {}
    week_agg: dict[date, dict] = {}
    month_agg: dict[date, dict] = {}

    for r in rows:
        d = r["dep_date"]
        tc = float(r["total_charge"] or 0)
        ma = float(r["margin_amt"] or 0)
        cp = float(r["total_carrier_pay"] or 0)
        if d >= day_start:
            b = bucket(d, "day")
            day_agg.setdefault(b, empty())
            if tc != 0:
                day_agg[b]["loads"] += 1
            day_agg[b]["revenue"] += tc
            day_agg[b]["profit"] += ma
            day_agg[b]["carrier_pay"] += cp
        if d >= week_start:
            b = bucket(d, "week")
            week_agg.setdefault(b, empty())
            if tc != 0:
                week_agg[b]["loads"] += 1
            week_agg[b]["revenue"] += tc
            week_agg[b]["profit"] += ma
            week_agg[b]["carrier_pay"] += cp
        if d >= month_start:
            b = bucket(d, "month")
            month_agg.setdefault(b, empty())
            if tc != 0:
                month_agg[b]["loads"] += 1
            month_agg[b]["revenue"] += tc
            month_agg[b]["profit"] += ma
            month_agg[b]["carrier_pay"] += cp

    def serialize(agg: dict, start: date, end: date, step: str) -> list[dict]:
        out = []
        for b in sorted(agg.keys()):
            if b < start or b > end:
                continue
            v = agg[b]
            loads = v["loads"]
            out.append({
                "bucket": b.isoformat(),
                "loads": loads,
                "revenue": v["revenue"],
                "profit": v["profit"],
                "carrier_pay": v["carrier_pay"],
                "margin_pct": (v["profit"] / v["revenue"] * 100.0) if v["revenue"] else 0.0,
                "avg_r_per_l": (v["revenue"] / loads) if loads else 0.0,
                "avg_p_per_l": (v["profit"] / loads) if loads else 0.0,
                "avg_cc_per_l": (v["carrier_pay"] / loads) if loads else 0.0,
            })
        return out

    return {
        "success": True,
        "data": {
            "day": serialize(day_agg, day_start, today, "day"),
            "week": serialize(week_agg, week_start, today, "week"),
            "month": serialize(month_agg, month_start, today, "month"),
        },
    }


@router.get("/summary-table")
async def summary_table(
    request: Request,
    team: Optional[str] = Query(None),
    customer: Optional[str] = Query(None),
    _user: dict = Depends(require_tag_role(*XRAY_ROLES)),
):
    """Summary by Month (last 15) + Summary by Week (last 16) tables for the Trends tab."""
    pool = get_datalake_gold_pool(request)
    today = date.today()
    # Enough history for both tables
    start = today - timedelta(days=500)

    params: list = []
    where = _scope_where("br4", team, customer, params)
    params.append(start)

    rows = await pool.fetch(
        f"""
        WITH otp AS ({_scorecard_cte("otp")}),
             otd AS ({_scorecard_cte("otd")}),
             prod AS (
                SELECT br4.origin_actual_departure::date AS dep_date,
                       TRIM(br4.origin_name) AS origin, TRIM(br4.dest_name) AS dest,
                       br4.id, br4.company_id, br4.total_charge, br4.margin_amt,
                       COALESCE(otp.scorecard_count_otp, 0) AS otp_cnt,
                       COALESCE(otd.scorecard_count_otd, 0) AS otd_cnt
                FROM public.mcleod_gld_budget_report_v4 br4
                LEFT JOIN otp ON TRIM(br4.id)=otp.id_key AND br4.company_id=otp.company_id_key
                LEFT JOIN otd ON TRIM(br4.id)=otd.id_key AND br4.company_id=otd.company_id_key
                WHERE {where} AND br4.origin_actual_departure::date >= ${len(params)}
             )
        SELECT
          DATE_TRUNC('month', dep_date)::date AS month_bucket,
          DATE_TRUNC('week',  dep_date)::date AS week_bucket,
          COUNT(DISTINCT (origin || ' - ' || dest)) AS lanes,
          COUNT(*) FILTER (WHERE total_charge <> 0) AS loads,
          COALESCE(SUM(total_charge), 0)::numeric AS revenue,
          COALESCE(SUM(margin_amt), 0)::numeric AS profit,
          SUM(otp_cnt) AS otp_sum,
          SUM(otd_cnt) AS otd_sum
        FROM prod
        GROUP BY GROUPING SETS ((month_bucket), (week_bucket))
        ORDER BY month_bucket DESC NULLS LAST, week_bucket DESC NULLS LAST
        """,
        *params,
    )

    months, weeks = [], []
    for r in rows:
        loads = int(r["loads"] or 0)
        revenue = float(r["revenue"] or 0)
        profit = float(r["profit"] or 0)
        otp_sum = int(r["otp_sum"] or 0)
        otd_sum = int(r["otd_sum"] or 0)
        base = {
            "lanes": int(r["lanes"] or 0),
            "loads": loads,
            "revenue": revenue,
            "profit": profit,
            "margin_pct": (profit / revenue * 100) if revenue else 0,
            "otp_pct": ((1 - otp_sum / loads) * 100) if loads else 0,
            "otd_pct": ((1 - otd_sum / loads) * 100) if loads else 0,
        }
        if r["month_bucket"] is not None:
            months.append({"bucket": r["month_bucket"].isoformat(), **base})
        elif r["week_bucket"] is not None:
            weeks.append({"bucket": r["week_bucket"].isoformat(), **base})
    return {
        "success": True,
        "data": {"months": months[:15], "weeks": weeks[:16]},
    }


# ---------------------------------------------------------------------------
# Tab 5 — Risk
# ---------------------------------------------------------------------------


@router.get("/risk")
async def risk(
    request: Request,
    range: Optional[str] = Query("ytd"),
    start_date: Optional[date] = Query(None),
    end_date: Optional[date] = Query(None),
    team: Optional[str] = Query(None),
    customer: Optional[str] = Query(None),
    limit: int = Query(200, ge=1, le=1000),
    _user: dict = Depends(require_tag_role(*XRAY_ROLES)),
):
    """Worst Margins by Lane + Negative Loads by Order + Negative Loads by Customer.

    Movement (payee_name / carrier) is LEFT JOINed — 45-day window means older
    orders get NULL carrier_name, which is acceptable per user confirmation.
    Losses-over-time series ignores RANGE (own 8-month / 8-week window).
    """
    pool = get_datalake_gold_pool(request)
    s, e = _resolve_range(range, start_date, end_date)

    params: list = []
    where = _scope_where("br4", team, customer, params)
    params.extend([s, e, limit])
    date_frag = f"br4.origin_actual_departure::date BETWEEN ${len(params)-2} AND ${len(params)-1}"
    lim_idx = len(params)

    # Worst margins by lane
    worst_lanes = await pool.fetch(
        f"""
        SELECT
          br4.customer_name AS customer,
          TRIM(br4.origin_name) AS origin,
          TRIM(br4.dest_name)   AS destination,
          COUNT(*) FILTER (WHERE br4.total_charge <> 0) AS loads,
          COALESCE(SUM(br4.total_charge), 0)::numeric AS revenue,
          COALESCE(SUM(br4.margin_amt), 0)::numeric  AS profit,
          CASE WHEN SUM(br4.total_charge) > 0
               THEN SUM(br4.margin_amt)::numeric / SUM(br4.total_charge)::numeric * 100
               ELSE 0 END AS margin_pct,
          GREATEST(0, SUM(br4.total_charge) * 0.15 - SUM(br4.margin_amt))::numeric AS diff_15,
          GREATEST(0, SUM(br4.total_charge) * 0.18 - SUM(br4.margin_amt))::numeric AS diff_18,
          GREATEST(0, SUM(br4.total_charge) * 0.20 - SUM(br4.margin_amt))::numeric AS diff_20
        FROM public.mcleod_gld_budget_report_v4 br4
        WHERE {where} AND {date_frag}
        GROUP BY br4.customer_name, TRIM(br4.origin_name), TRIM(br4.dest_name)
        HAVING SUM(br4.margin_amt) < 0
        ORDER BY profit ASC
        LIMIT ${lim_idx}
        """,
        *params,
    )

    # Negative loads by order — one row per order, LEFT JOIN movement
    neg_orders = await pool.fetch(
        f"""
        WITH neg AS (
            SELECT br4.id, br4.customer_name, br4.company_id,
                   TRIM(br4.origin_name) AS origin,
                   TRIM(br4.dest_name)   AS destination,
                   br4.total_charge, br4.margin_amt
            FROM public.mcleod_gld_budget_report_v4 br4
            WHERE {where} AND {date_frag}
              AND br4.margin_amt < 0 AND br4.total_charge <> 0
        ),
        mov1 AS (
            SELECT TRIM(order_id) AS order_id_key, company_id, payee_name,
                   ROW_NUMBER() OVER (PARTITION BY TRIM(order_id), company_id
                                      ORDER BY movement_id) AS rn
            FROM public.mcleod_gld_movement
        ),
        totals AS (
            SELECT SUM(margin_amt)::numeric AS total_neg_margin FROM neg
        )
        SELECT
            neg.id,
            neg.customer_name AS customer,
            COALESCE(mov1.payee_name, '—') AS carrier,
            neg.origin,
            neg.destination,
            neg.total_charge AS revenue,
            neg.margin_amt   AS profit,
            CASE WHEN neg.total_charge > 0 THEN neg.margin_amt / neg.total_charge * 100 ELSE 0 END AS margin_pct,
            CASE WHEN totals.total_neg_margin <> 0
                 THEN neg.margin_amt / totals.total_neg_margin * 100
                 ELSE 0 END AS conc_pct
        FROM neg
        LEFT JOIN mov1 ON mov1.rn = 1
                     AND TRIM(neg.id) = mov1.order_id_key
                     AND neg.company_id = mov1.company_id
        CROSS JOIN totals
        ORDER BY profit ASC
        LIMIT ${lim_idx}
        """,
        *params,
    )

    # Negative loads — roll-up by customer
    neg_customer = await pool.fetch(
        f"""
        WITH neg AS (
            SELECT br4.customer_name,
                   br4.total_charge, br4.margin_amt
            FROM public.mcleod_gld_budget_report_v4 br4
            WHERE {where} AND {date_frag}
              AND br4.margin_amt < 0 AND br4.total_charge <> 0
        ),
        totals AS (
            SELECT SUM(margin_amt)::numeric AS total_neg_margin FROM neg
        )
        SELECT
            neg.customer_name AS customer,
            COUNT(*) AS loads,
            SUM(neg.total_charge)::numeric AS revenue,
            SUM(neg.margin_amt)::numeric   AS profit,
            CASE WHEN totals.total_neg_margin <> 0
                 THEN SUM(neg.margin_amt) / totals.total_neg_margin * 100
                 ELSE 0 END AS conc_pct
        FROM neg CROSS JOIN totals
        WHERE customer_name IS NOT NULL
        GROUP BY neg.customer_name, totals.total_neg_margin
        ORDER BY profit ASC
        LIMIT ${lim_idx}
        """,
        *params,
    )

    # Losses-over-time (last 8 months and 8 weeks; independent of RANGE)
    today = date.today()
    losses_start = today - timedelta(days=280)  # ~8 months safety window
    loss_params: list = []
    loss_where = _scope_where("br4", team, customer, loss_params)
    loss_params.append(losses_start)
    losses_rows = await pool.fetch(
        f"""
        SELECT
          DATE_TRUNC('month', br4.origin_actual_departure)::date AS month_bucket,
          DATE_TRUNC('week',  br4.origin_actual_departure)::date AS week_bucket,
          COUNT(*) FILTER (WHERE br4.total_charge <> 0) AS loads,
          SUM(br4.margin_amt)::numeric AS profit
        FROM public.mcleod_gld_budget_report_v4 br4
        WHERE {loss_where}
          AND br4.margin_amt < 0
          AND br4.origin_actual_departure::date >= ${len(loss_params)}
        GROUP BY GROUPING SETS ((month_bucket), (week_bucket))
        ORDER BY month_bucket DESC NULLS LAST, week_bucket DESC NULLS LAST
        """,
        *loss_params,
    )
    losses_month, losses_week = [], []
    for r in losses_rows:
        base = {"loads": int(r["loads"] or 0), "profit": float(r["profit"] or 0)}
        if r["month_bucket"] is not None:
            losses_month.append({"bucket": r["month_bucket"].isoformat(), **base})
        elif r["week_bucket"] is not None:
            losses_week.append({"bucket": r["week_bucket"].isoformat(), **base})

    return {
        "success": True,
        "data": {
            "worst_lanes": [dict(r) for r in worst_lanes],
            "neg_orders": [dict(r) for r in neg_orders],
            "neg_customers": [dict(r) for r in neg_customer],
            "losses_month": losses_month[:8],
            "losses_week": losses_week[:8],
        },
    }


# ---------------------------------------------------------------------------
# Tab 6 — Contract vs Spot + All Orders + Lane Analysis
# ---------------------------------------------------------------------------


@router.get("/contract-spot")
async def contract_spot(
    request: Request,
    team: Optional[str] = Query(None),
    customer: Optional[str] = Query(None),
    _user: dict = Depends(require_tag_role(*XRAY_ROLES)),
):
    """Contract vs Spot weekly breakdown — last 9 ISO weeks. Ignores RANGE."""
    pool = get_datalake_gold_pool(request)
    today = date.today()
    start = (today - timedelta(days=today.weekday())) - timedelta(days=7 * 8)

    params: list = []
    where = _scope_where("br4", team, customer, params)
    params.append(start)

    rows = await pool.fetch(
        f"""
        SELECT
          DATE_TRUNC('week', br4.origin_actual_departure)::date AS week_bucket,
          LOWER(TRIM(COALESCE(br4.contract_type_descr, ''))) AS kind,
          COUNT(*) FILTER (WHERE br4.total_charge <> 0) AS loads,
          COALESCE(SUM(br4.total_charge), 0)::numeric AS revenue,
          COALESCE(SUM(br4.margin_amt), 0)::numeric AS profit
        FROM public.mcleod_gld_budget_report_v4 br4
        WHERE {where}
          AND br4.origin_actual_departure::date >= ${len(params)}
          AND LOWER(TRIM(COALESCE(br4.contract_type_descr,''))) IN ('contract','spot')
        GROUP BY week_bucket, kind
        ORDER BY week_bucket
        """,
        *params,
    )
    contract, spot = [], []
    for r in rows:
        point = {
            "bucket": r["week_bucket"].isoformat(),
            "loads": int(r["loads"] or 0),
            "revenue": float(r["revenue"] or 0),
            "profit": float(r["profit"] or 0),
            "margin_pct": (
                float(r["profit"] or 0) / float(r["revenue"] or 0) * 100.0
                if r["revenue"]
                else 0.0
            ),
        }
        if r["kind"] == "contract":
            contract.append(point)
        else:
            spot.append(point)
    return {"success": True, "data": {"contract": contract, "spot": spot}}


@router.get("/all-orders")
async def all_orders(
    request: Request,
    range: Optional[str] = Query("ytd"),
    start_date: Optional[date] = Query(None),
    end_date: Optional[date] = Query(None),
    team: Optional[str] = Query(None),
    customer: Optional[str] = Query(None),
    limit: int = Query(500, ge=1, le=2000),
    _user: dict = Depends(require_tag_role(*XRAY_ROLES)),
):
    """Order-level detail with 15/18/20% profit target + diff columns."""
    pool = get_datalake_gold_pool(request)
    s, e = _resolve_range(range, start_date, end_date)

    params: list = []
    where = _scope_where("br4", team, customer, params)
    params.extend([s, e, limit])
    date_frag = f"br4.origin_actual_departure::date BETWEEN ${len(params)-2} AND ${len(params)-1}"

    rows = await pool.fetch(
        f"""
        WITH mov1 AS (
            SELECT TRIM(order_id) AS order_id_key, company_id, payee_name,
                   ROW_NUMBER() OVER (PARTITION BY TRIM(order_id), company_id
                                      ORDER BY movement_id) AS rn
            FROM public.mcleod_gld_movement
        )
        SELECT
          TRIM(br4.team_id) AS team,
          br4.id,
          br4.customer_name AS customer,
          COALESCE(mov1.payee_name, '—') AS carrier,
          TRIM(br4.origin_name) AS origin,
          TRIM(br4.dest_name)   AS destination,
          br4.origin_actual_departure AS departure,
          br4.total_charge AS revenue,
          br4.margin_amt   AS profit,
          CASE WHEN br4.total_charge > 0 THEN br4.margin_amt/br4.total_charge*100 ELSE 0 END AS margin_pct,
          GREATEST(0, br4.total_charge * 0.15 - br4.margin_amt)::numeric AS diff_15,
          GREATEST(0, br4.total_charge * 0.18 - br4.margin_amt)::numeric AS diff_18,
          GREATEST(0, br4.total_charge * 0.20 - br4.margin_amt)::numeric AS diff_20
        FROM public.mcleod_gld_budget_report_v4 br4
        LEFT JOIN mov1 ON mov1.rn = 1
                       AND TRIM(br4.id) = mov1.order_id_key
                       AND br4.company_id = mov1.company_id
        WHERE {where} AND {date_frag}
          AND br4.total_charge <> 0
        ORDER BY br4.origin_actual_departure DESC NULLS LAST
        LIMIT ${len(params)}
        """,
        *params,
    )
    out = []
    for r in rows:
        d = dict(r)
        dep = d.pop("departure")
        d["departure"] = dep.isoformat() if isinstance(dep, datetime) else (dep.isoformat() if dep else None)
        out.append(d)
    return {"success": True, "data": out}


@router.get("/lane-analysis")
async def lane_analysis(
    request: Request,
    range: Optional[str] = Query("ytd"),
    start_date: Optional[date] = Query(None),
    end_date: Optional[date] = Query(None),
    team: Optional[str] = Query(None),
    customer: Optional[str] = Query(None),
    limit: int = Query(300, ge=1, le=1000),
    _user: dict = Depends(require_tag_role(*XRAY_ROLES)),
):
    """Lane Production Analysis — per customer×origin×destination with target diffs."""
    pool = get_datalake_gold_pool(request)
    s, e = _resolve_range(range, start_date, end_date)

    params: list = []
    where = _scope_where("br4", team, customer, params)
    params.extend([s, e, limit])
    date_frag = f"br4.origin_actual_departure::date BETWEEN ${len(params)-2} AND ${len(params)-1}"

    rows = await pool.fetch(
        f"""
        WITH base AS (
            SELECT br4.customer_name,
                   TRIM(br4.origin_name) AS origin,
                   TRIM(br4.dest_name) AS destination,
                   br4.total_charge, br4.margin_amt
            FROM public.mcleod_gld_budget_report_v4 br4
            WHERE {where} AND {date_frag} AND br4.total_charge <> 0
        ),
        totals AS (SELECT SUM(margin_amt)::numeric AS total_margin FROM base)
        SELECT
            base.customer_name AS customer,
            origin, destination,
            COUNT(*) AS loads,
            SUM(total_charge)::numeric AS revenue,
            SUM(margin_amt)::numeric   AS profit,
            CASE WHEN SUM(total_charge) > 0 THEN SUM(margin_amt)/SUM(total_charge)*100 ELSE 0 END AS margin_pct,
            CASE WHEN COUNT(*) > 0 THEN SUM(total_charge)/COUNT(*) ELSE 0 END AS avg_r_per_l,
            CASE WHEN COUNT(*) > 0 THEN SUM(margin_amt)/COUNT(*) ELSE 0 END AS avg_p_per_l,
            CASE WHEN totals.total_margin <> 0
                 THEN SUM(margin_amt)/totals.total_margin*100 ELSE 0 END AS conc_pct,
            GREATEST(0, SUM(total_charge) * 0.15 - SUM(margin_amt))::numeric AS diff_15,
            GREATEST(0, SUM(total_charge) * 0.18 - SUM(margin_amt))::numeric AS diff_18,
            GREATEST(0, SUM(total_charge) * 0.20 - SUM(margin_amt))::numeric AS diff_20
        FROM base CROSS JOIN totals
        WHERE origin <> '' AND destination <> '' AND customer_name IS NOT NULL
        GROUP BY base.customer_name, origin, destination, totals.total_margin
        ORDER BY conc_pct DESC NULLS LAST
        LIMIT ${len(params)}
        """,
        *params,
    )
    return {"success": True, "data": [dict(r) for r in rows]}
