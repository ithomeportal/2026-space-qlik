"""Code-made report: CEO Executive — 6-tab executive view across CORP + DFW.

Mirrors Bruno's "Executive Report" Qlik app
(8a36f235-d077-4ab0-85ae-ba3732fd36c3) as a portal custom report. Scope:
CORP (team_id TEAM1-5) + DFW (team_id TEAM-DFW, sub-teams TM1-TM4 via
v4.team column), company TMS/TMS3, status D/P, excluding OILTEX and
UNILINK customers.

Divisions:
- CORP: team_id ∈ {TEAM1, TEAM2, TEAM3, TEAM4, TEAM5} — "team" label = team_id
- DFW : team_id = 'TEAM-DFW'                         — "team" label = v4.team
        (sub-team) with values TM1, TM2, TM3, TM4

Data sources:
- Overview tab roll-ups (KPIs, Summary by Team, All Teams Performance,
  Profit-TM gauge) all read from public.daily_production_budget_report,
  joined to a customer→division_team mapping derived from
  public.mcleod_gld_budget_report_v4. division_team = team_id for CORP
  rows, TRIM(team) for DFW rows. This is the same source that powers
  the 2026 Official Budget Follow Up report and the Profit-TM gauge, and
  it is refreshed every 6h by n8n (SQi0VmZS1nYmo7Kt). Using v4 directly
  for these panels used to produce $0 for teams with no April production
  in v4 even when budget_report had daily actuals — the mismatch was
  confusing users.
- Tabs that need load-level / lane-level detail (Customers, Risk, Orders,
  Trends, Weekly) still read from public.mcleod_gld_budget_report_v4,
  because daily_production_budget_report is a day-level aggregate and
  doesn't expose origin/destination/order id/carrier.

The v4-based panels LEFT JOIN public.mcleod_gld_movement for carrier name.

Filter contract:
- range    : "mtd" | "ytd" | "full" | "custom"  (default mtd)
- start_date / end_date : ISO dates (used when range="custom")
- division : "CORP" | "DFW" | "" (all)
- team     : one of CORP_TEAMS ∪ DFW_SUB_TEAMS | "" (all)
- customer : single customer name | "" (all)

Per PDF spec, panels fall into three groups:
- SCOPED: respect range + team + customer (KPIs, Summary by Team, Profit by
  Customer, Worst Profit by Customer, Worst Margins by Lanes, Negative Loads
  by Order / Customer, Lane Production Analysis, All Orders).
- GLOBAL: ignore ALL filters (All Teams Performance, Customer Count & Margin
  last 15 months, Profit/Loads by Month last 15 months, Profit/Loads by Day
  last 80 days, Customer Count & Margin by Day last 80 days, Loads vs
  Revenue by Week last 10 weeks, Profit/%Margin by Week last 10 weeks,
  Summary by Week, Top-5 Concentration by Revenue, Top-5 Concentration by
  Profit).
- SEMI-SCOPED: Profit-TM gauge respects team + customer but always uses the
  current calendar month.

Endpoints are organised one-per-tab so the UI can lazy-load. Each endpoint
fires its independent panel reads in parallel via asyncio.gather.
"""

from __future__ import annotations

import asyncio
from datetime import date, datetime, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, Query, Request

from app.datalake import pad_variants as _pad_variants
from app.routers.deps import get_datalake_gold_pool, require_tag_role

# Roles allowed. Admin is always bypassed by require_tag_role.
CEO_ROLES = ("CEO",)

YEAR_START = date(2026, 1, 1)
YEAR_END = date(2026, 12, 31)

# Division universe — CORP team_ids + the single DFW team_id.
CORP_TEAMS = ("TEAM1", "TEAM2", "TEAM3", "TEAM4", "TEAM5")
DFW_TEAM_ID = "TEAM-DFW"
# Sub-teams that live UNDER TEAM-DFW (stored in v4.team, not v4.team_id).
DFW_SUB_TEAMS = ("TM1", "TM2", "TM3", "TM4")
# team_id universe: what v4.team_id is allowed to be across the whole report.
ALLOWED_TEAMS = (*CORP_TEAMS, DFW_TEAM_ID)
# Unified "team" filter values shown in the UI pills (CORP divisions + DFW sub-teams).
ALL_DIVISION_TEAMS = (*CORP_TEAMS, *DFW_SUB_TEAMS)
ALLOWED_COMPANIES = ("TMS", "TMS3")
OPEN_STATUSES = ("D", "P")

router = APIRouter(tags=["ceo-executive"], prefix="/custom/ceo-executive")


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
    today = date.today()
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
    return YEAR_START, YEAR_END


def _division_team_ids(division: Optional[str]) -> tuple[str, ...]:
    """team_id values that satisfy the division filter.

    None/""/unknown -> full universe (CORP + DFW).
    """
    if division == "CORP":
        return CORP_TEAMS
    if division == "DFW":
        return (DFW_TEAM_ID,)
    return ALLOWED_TEAMS


def _scope_where(
    alias: str,
    team: Optional[str],
    customer: Optional[str],
    params: list,
    include_unilink_filter: bool = True,
    division: Optional[str] = None,
) -> str:
    """Sargable WHERE fragment shared by every scoped query.

    Pushes $-placeholders onto `params` in order. Uses `= ANY($N)` with
    padded+unpadded literal variants so Postgres can use btree indexes on
    team_id, company_id, status. No TRIM() in predicates for the wide
    dimensions. DFW sub-team uses TRIM(team) only after the sargable
    team_id filter has already pruned to a single division.
    """
    # v4 declared widths: team_id varchar(8), company_id varchar(4), status varchar(1).
    # Seed team_id universe narrowed by division (CORP, DFW, or both).
    params.append(_pad_variants(_division_team_ids(division), width=8))
    p_teams = len(params)
    params.append(_pad_variants(ALLOWED_COMPANIES, width=4))
    p_comp = len(params)
    params.append(_pad_variants(OPEN_STATUSES, width=1))
    p_stat = len(params)

    parts = [
        f"{alias}.team_id    = ANY(${p_teams})",
        f"{alias}.company_id = ANY(${p_comp})",
        f"{alias}.status     = ANY(${p_stat})",
        f"UPPER(COALESCE({alias}.customer_name,'')) NOT LIKE '%OILTEX%'",
    ]
    if include_unilink_filter:
        parts.append(
            f"UPPER(COALESCE({alias}.customer_name,'')) NOT LIKE '%UNILINK%'"
        )
    if team:
        if team in CORP_TEAMS:
            params.append(_pad_variants([team], width=8))
            parts.append(f"{alias}.team_id = ANY(${len(params)})")
        elif team in DFW_SUB_TEAMS:
            params.append(_pad_variants([DFW_TEAM_ID], width=8))
            parts.append(f"{alias}.team_id = ANY(${len(params)})")
            params.append(team)
            # team column width is not documented; TRIM is safe here because
            # team_id has already pruned to one division's rows (~1/6 scan).
            parts.append(f"TRIM({alias}.team) = ${len(params)}")
        else:
            # Unknown value — fall back to literal team_id filter (defensive).
            params.append(_pad_variants([team], width=8))
            parts.append(f"{alias}.team_id = ANY(${len(params)})")
    if customer:
        params.append(customer)
        parts.append(f"{alias}.customer_name = ${len(params)}")
    return " AND ".join(parts)


def _global_scope_where(alias: str) -> str:
    """Scope fragment for GLOBAL panels — no team/customer/date/division
    filter, but still restricted to the CORP + DFW team_id universe. Safe
    literal-only SQL.
    """
    def _lit(values, *, width: int) -> str:
        return ",".join(f"'{v}'" for v in _pad_variants(values, width=width))

    return (
        f"{alias}.team_id    IN ({_lit(ALLOWED_TEAMS, width=8)}) AND "
        f"{alias}.company_id IN ({_lit(ALLOWED_COMPANIES, width=4)}) AND "
        f"{alias}.status     IN ({_lit(OPEN_STATUSES, width=1)}) AND "
        f"UPPER(COALESCE({alias}.customer_name,'')) NOT LIKE '%OILTEX%' AND "
        f"UPPER(COALESCE({alias}.customer_name,'')) NOT LIKE '%UNILINK%'"
    )


def _month_start(d: date) -> date:
    return d.replace(day=1)


def _month_end(d: date) -> date:
    if d.month == 12:
        return d.replace(year=d.year + 1, month=1, day=1) - timedelta(days=1)
    return d.replace(month=d.month + 1, day=1) - timedelta(days=1)


def _shift_months(d: date, n: int) -> date:
    """Return first-of-month shifted by n months (n may be negative)."""
    y = d.year + (d.month - 1 + n) // 12
    m = (d.month - 1 + n) % 12 + 1
    return date(y, m, 1)


def _week_start(d: date) -> date:
    """Monday of the week containing d."""
    return d - timedelta(days=d.weekday())


def _customer_team_cte(teams_param_pos: int) -> str:
    """Per-customer canonical division_team CTE, derived from v4.

    Emits ``customer_team(customer_name, division_team)`` where each customer
    is mapped to the (team_id OR DFW sub-team) with the most v4 rows (tiebreak
    by division_team). The padded-variants list must be at $-placeholder
    position ``teams_param_pos``.

    division_team is:
      * ``TRIM(team_id)`` for CORP rows (TEAM1..TEAM5)
      * ``TRIM(team)``    for DFW rows (TM1..TM4) — so DFW rolls up at the
                          sub-team level, not as a single "TEAM-DFW" bucket.

    Used by every Overview panel that aggregates daily_production_budget_report
    by team — production actuals come from budget_report (6h n8n refresh),
    team assignment from v4. This matches the Profit-TM gauge logic and the
    2026 Official Budget Follow Up report.

    A customer that ships across divisions is attributed to whichever
    division_team holds the majority of their v4 rows — acceptable
    simplification; budget_report is customer-keyed with no team column.
    """
    return f"""
    customer_team AS (
        SELECT customer_name, division_team FROM (
            SELECT
                TRIM(customer_name) AS customer_name,
                CASE
                  WHEN TRIM(team_id) = '{DFW_TEAM_ID}' THEN TRIM(team)
                  ELSE TRIM(team_id)
                END AS division_team,
                ROW_NUMBER() OVER (
                    PARTITION BY TRIM(customer_name)
                    ORDER BY COUNT(*) DESC,
                             CASE
                               WHEN TRIM(team_id) = '{DFW_TEAM_ID}' THEN TRIM(team)
                               ELSE TRIM(team_id)
                             END
                ) AS rn
            FROM public.mcleod_gld_budget_report_v4
            WHERE team_id = ANY(${teams_param_pos})
            GROUP BY TRIM(customer_name),
                     CASE
                       WHEN TRIM(team_id) = '{DFW_TEAM_ID}' THEN TRIM(team)
                       ELSE TRIM(team_id)
                     END
        ) ranked
        WHERE rn = 1
    )
    """


_BUDGET_EXCLUDE_FRAG = (
    " AND UPPER(COALESCE(budget.\"Customer Name\",'')) NOT LIKE '%OILTEX%'"
    " AND UPPER(COALESCE(budget.\"Customer Name\",'')) NOT LIKE '%UNILINK%'"
)


# ---------------------------------------------------------------------------
# /filters — teams + distinct customer list
# ---------------------------------------------------------------------------


@router.get("/filters")
async def filters(
    request: Request,
    _user: dict = Depends(require_tag_role(*CEO_ROLES)),
):
    pool = get_datalake_gold_pool(request)
    rows = await pool.fetch(
        """
        SELECT DISTINCT TRIM(customer_name) AS customer_name
        FROM public.mcleod_gld_budget_report_v4
        WHERE team_id    = ANY($1)
          AND company_id = ANY($2)
          AND status     = ANY($3)
          AND UPPER(COALESCE(customer_name,'')) NOT LIKE '%OILTEX%'
          AND UPPER(COALESCE(customer_name,'')) NOT LIKE '%UNILINK%'
          AND customer_name IS NOT NULL
          AND TRIM(customer_name) <> ''
          AND origin_actual_departure >= $4
        ORDER BY customer_name
        """,
        _pad_variants(ALLOWED_TEAMS, width=8),
        _pad_variants(ALLOWED_COMPANIES, width=4),
        _pad_variants(OPEN_STATUSES, width=1),
        YEAR_START,
    )
    return {
        "success": True,
        "data": {
            "divisions": ["CORP", "DFW"],
            "teams": list(ALL_DIVISION_TEAMS),
            "teams_by_division": {
                "CORP": list(CORP_TEAMS),
                "DFW": list(DFW_SUB_TEAMS),
            },
            "customers": [r["customer_name"] for r in rows],
            "year_start": YEAR_START.isoformat(),
            "year_end": YEAR_END.isoformat(),
        },
    }


# ---------------------------------------------------------------------------
# Tab 1 — Overview
#   * KPIs (scoped)
#   * Profit-TM (semi-scoped: current month + team + customer)
#   * Summary by Team (scoped)
#   * All Teams Performance (global, Yd/Week/Month)
# ---------------------------------------------------------------------------


@router.get("/overview")
async def overview(
    request: Request,
    range: Optional[str] = Query("mtd"),
    start_date: Optional[date] = Query(None),
    end_date: Optional[date] = Query(None),
    division: Optional[str] = Query(None),
    team: Optional[str] = Query(None),
    customer: Optional[str] = Query(None),
    _user: dict = Depends(require_tag_role(*CEO_ROLES)),
):
    pool = get_datalake_gold_pool(request)
    s, e = _resolve_range(range, start_date, end_date)
    today = date.today()
    m_start = _month_start(today)
    m_end = _month_end(today)

    # division narrows the team_id universe that the customer_team CTE scans.
    scoped_team_ids = _division_team_ids(division)
    scoped_teams_padded = _pad_variants(scoped_team_ids, width=8)

    # Row-list for Summary by Team / All Teams Performance "unnest" joins.
    # One-row-per-team so teams with no production still appear.
    if team:
        team_list_for_unnest = [team]
    elif division == "CORP":
        team_list_for_unnest = list(CORP_TEAMS)
    elif division == "DFW":
        team_list_for_unnest = list(DFW_SUB_TEAMS)
    else:
        team_list_for_unnest = list(ALL_DIVISION_TEAMS)

    # ---- KPIs (scoped) --------------------------------------------------
    # Production actuals come from daily_production_budget_report so teams
    # with no April rows in v4 still show real numbers (matches Profit-TM
    # gauge). Team assignment comes from v4 via customer_team CTE.
    kpi_params: list = [s, e, scoped_teams_padded]
    kpi_extra = ""
    if team:
        kpi_params.append(team)
        kpi_extra += f" AND ct.division_team = ${len(kpi_params)}"
    if customer:
        kpi_params.append(customer)
        kpi_extra += f' AND budget."Customer Name" = ${len(kpi_params)}'
    kpi_task = pool.fetchrow(
        f"""
        WITH {_customer_team_cte(3)}
        SELECT
          COALESCE(SUM(budget."Loads Actual"),   0)::numeric AS loads,
          COALESCE(SUM(budget."Revenue Actual"), 0)::numeric AS revenue,
          COALESCE(SUM(budget."Profit Actual"),  0)::numeric AS profit,
          CASE WHEN SUM(budget."Revenue Actual") > 0
               THEN SUM(budget."Profit Actual")::numeric
                    / SUM(budget."Revenue Actual")::numeric
               ELSE 0 END AS margin_pct,
          CASE WHEN SUM(budget."Loads Actual") > 0
               THEN SUM(budget."Revenue Actual")::numeric
                    / SUM(budget."Loads Actual")::numeric
               ELSE 0 END AS avg_r_per_l,
          CASE WHEN SUM(budget."Loads Actual") > 0
               THEN SUM(budget."Profit Actual")::numeric
                    / SUM(budget."Loads Actual")::numeric
               ELSE 0 END AS avg_p_per_l
        FROM public.daily_production_budget_report budget
        JOIN customer_team ct ON TRIM(budget."Customer Name") = ct.customer_name
        WHERE budget."Date" BETWEEN $1 AND $2
        {_BUDGET_EXCLUDE_FRAG}
        {kpi_extra}
        """,
        *kpi_params,
    )

    # ---- Summary by Team (scoped) --------------------------------------
    sbt_params: list = [s, e, scoped_teams_padded, team_list_for_unnest]
    sbt_extra = ""
    if team:
        sbt_params.append(team)
        sbt_extra += f" AND ct.division_team = ${len(sbt_params)}"
    if customer:
        sbt_params.append(customer)
        sbt_extra += f' AND budget."Customer Name" = ${len(sbt_params)}'
    sbt_task = pool.fetch(
        f"""
        WITH {_customer_team_cte(3)},
        agg AS (
          SELECT
            ct.division_team AS team,
            COUNT(DISTINCT budget."Customer Name") AS cust,
            COALESCE(SUM(budget."Loads Actual"),   0)::numeric AS loads,
            COALESCE(SUM(budget."Revenue Actual"), 0)::numeric AS revenue,
            COALESCE(SUM(budget."Profit Actual"),  0)::numeric AS profit
          FROM public.daily_production_budget_report budget
          JOIN customer_team ct ON TRIM(budget."Customer Name") = ct.customer_name
          WHERE budget."Date" BETWEEN $1 AND $2
          {_BUDGET_EXCLUDE_FRAG}
          {sbt_extra}
          GROUP BY ct.division_team
        )
        SELECT
          t.team,
          COALESCE(a.cust,    0) AS cust,
          COALESCE(a.loads,   0) AS loads,
          COALESCE(a.revenue, 0)::numeric AS revenue,
          COALESCE(a.profit,  0)::numeric AS profit
        FROM unnest($4::text[]) AS t(team)
        LEFT JOIN agg a ON a.team = t.team
        ORDER BY profit DESC NULLS LAST, team
        """,
        *sbt_params,
    )

    # ---- Profit-TM (semi-scoped: current month, division+team+customer apply) ---
    tm_params: list = [m_start, m_end, scoped_teams_padded]
    tm_extra = ""
    if team:
        tm_params.append(team)
        tm_extra += f" AND ct.division_team = ${len(tm_params)}"
    if customer:
        tm_params.append(customer)
        tm_extra += f' AND budget."Customer Name" = ${len(tm_params)}'
    profit_tm_task = pool.fetchval(
        f"""
        WITH {_customer_team_cte(3)}
        SELECT COALESCE(SUM(budget."Profit Actual"), 0)::numeric
        FROM public.daily_production_budget_report budget
        JOIN customer_team ct ON TRIM(budget."Customer Name") = ct.customer_name
        WHERE budget."Date" BETWEEN $1 AND $2
        {_BUDGET_EXCLUDE_FRAG}
        {tm_extra}
        """,
        *tm_params,
    )

    # ---- All Teams Performance (GLOBAL — Yd / Week / Month) -------------
    # Ignores every filter. Always emits one row per ALL_DIVISION_TEAMS
    # member via unnest LEFT JOIN agg so teams with no production still
    # appear. $5 carries the full CORP+DFW team_id universe so the CTE can
    # see rows from both divisions regardless of the currently-selected
    # division filter.
    yesterday = today - timedelta(days=1)
    week_start = _week_start(today)
    atp_task = pool.fetch(
        f"""
        WITH {_customer_team_cte(5)},
        agg AS (
          SELECT
            ct.division_team AS team,
            COALESCE(SUM(budget."Loads Actual")
              FILTER (WHERE budget."Date" = $1), 0)::numeric AS yd_loads,
            COALESCE(SUM(budget."Profit Actual")
              FILTER (WHERE budget."Date" = $1), 0)::numeric AS yd_profit,
            CASE WHEN SUM(budget."Revenue Actual")
                      FILTER (WHERE budget."Date" = $1) > 0
                 THEN SUM(budget."Profit Actual")
                        FILTER (WHERE budget."Date" = $1)::numeric
                      / SUM(budget."Revenue Actual")
                        FILTER (WHERE budget."Date" = $1)::numeric
                 ELSE 0 END AS yd_margin,
            COALESCE(SUM(budget."Loads Actual")
              FILTER (WHERE budget."Date" BETWEEN $2 AND $3), 0)::numeric AS wk_loads,
            COALESCE(SUM(budget."Profit Actual")
              FILTER (WHERE budget."Date" BETWEEN $2 AND $3), 0)::numeric AS wk_profit,
            CASE WHEN SUM(budget."Revenue Actual")
                      FILTER (WHERE budget."Date" BETWEEN $2 AND $3) > 0
                 THEN SUM(budget."Profit Actual")
                        FILTER (WHERE budget."Date" BETWEEN $2 AND $3)::numeric
                      / SUM(budget."Revenue Actual")
                        FILTER (WHERE budget."Date" BETWEEN $2 AND $3)::numeric
                 ELSE 0 END AS wk_margin,
            COALESCE(SUM(budget."Loads Actual")
              FILTER (WHERE budget."Date" BETWEEN $4 AND $3), 0)::numeric AS mo_loads,
            COALESCE(SUM(budget."Profit Actual")
              FILTER (WHERE budget."Date" BETWEEN $4 AND $3), 0)::numeric AS mo_profit,
            CASE WHEN SUM(budget."Revenue Actual")
                      FILTER (WHERE budget."Date" BETWEEN $4 AND $3) > 0
                 THEN SUM(budget."Profit Actual")
                        FILTER (WHERE budget."Date" BETWEEN $4 AND $3)::numeric
                      / SUM(budget."Revenue Actual")
                        FILTER (WHERE budget."Date" BETWEEN $4 AND $3)::numeric
                 ELSE 0 END AS mo_margin,
            CASE WHEN SUM(budget."Loads Actual")
                      FILTER (WHERE budget."Date" BETWEEN $4 AND $3) > 0
                 THEN SUM(budget."Profit Actual")
                        FILTER (WHERE budget."Date" BETWEEN $4 AND $3)::numeric
                      / SUM(budget."Loads Actual")
                        FILTER (WHERE budget."Date" BETWEEN $4 AND $3)::numeric
                 ELSE 0 END AS mo_p_per_l
          FROM public.daily_production_budget_report budget
          JOIN customer_team ct ON TRIM(budget."Customer Name") = ct.customer_name
          WHERE budget."Date" BETWEEN $4 AND $3
            AND UPPER(COALESCE(budget."Customer Name",'')) NOT LIKE '%OILTEX%'
            AND UPPER(COALESCE(budget."Customer Name",'')) NOT LIKE '%UNILINK%'
          GROUP BY ct.division_team
        )
        SELECT
          t.team,
          COALESCE(a.yd_loads,   0) AS yd_loads,
          COALESCE(a.yd_profit,  0)::numeric AS yd_profit,
          COALESCE(a.yd_margin,  0) AS yd_margin,
          COALESCE(a.wk_loads,   0) AS wk_loads,
          COALESCE(a.wk_profit,  0)::numeric AS wk_profit,
          COALESCE(a.wk_margin,  0) AS wk_margin,
          COALESCE(a.mo_loads,   0) AS mo_loads,
          COALESCE(a.mo_profit,  0)::numeric AS mo_profit,
          COALESCE(a.mo_margin,  0) AS mo_margin,
          COALESCE(a.mo_p_per_l, 0)::numeric AS mo_p_per_l
        FROM unnest($6::text[]) AS t(team)
        LEFT JOIN agg a ON a.team = t.team
        ORDER BY mo_profit DESC NULLS LAST, team
        """,
        yesterday, week_start, today, m_start,
        _pad_variants(ALLOWED_TEAMS, width=8),
        list(ALL_DIVISION_TEAMS),
    )

    kpi, sbt, profit_tm, atp = await asyncio.gather(
        kpi_task, sbt_task, profit_tm_task, atp_task
    )

    return {
        "success": True,
        "data": {
            "kpis": {
                "loads": int(kpi["loads"] or 0),
                "revenue": float(kpi["revenue"] or 0),
                "profit": float(kpi["profit"] or 0),
                "margin_pct": float(kpi["margin_pct"] or 0) * 100.0,
                "avg_r_per_l": float(kpi["avg_r_per_l"] or 0),
                "avg_p_per_l": float(kpi["avg_p_per_l"] or 0),
            },
            "profit_tm": float(profit_tm or 0),
            "window": {"start": s.isoformat(), "end": e.isoformat()},
            "summary_by_team": [
                {
                    "team": r["team"],
                    "cust": int(r["cust"] or 0),
                    "loads": int(r["loads"] or 0),
                    "revenue": float(r["revenue"] or 0),
                    "profit": float(r["profit"] or 0),
                    "margin_pct": (
                        float(r["profit"]) / float(r["revenue"]) * 100.0
                        if r["revenue"] else 0.0
                    ),
                    "avg_r_per_l": (
                        float(r["revenue"]) / int(r["loads"])
                        if r["loads"] else 0.0
                    ),
                    "avg_p_per_l": (
                        float(r["profit"]) / int(r["loads"])
                        if r["loads"] else 0.0
                    ),
                }
                for r in sbt
            ],
            "all_teams_performance": [
                {
                    "team": r["team"],
                    "yd_loads": int(r["yd_loads"] or 0),
                    "yd_profit": float(r["yd_profit"] or 0),
                    "yd_margin_pct": float(r["yd_margin"] or 0) * 100.0,
                    "wk_loads": int(r["wk_loads"] or 0),
                    "wk_profit": float(r["wk_profit"] or 0),
                    "wk_margin_pct": float(r["wk_margin"] or 0) * 100.0,
                    "mo_loads": int(r["mo_loads"] or 0),
                    "mo_profit": float(r["mo_profit"] or 0),
                    "mo_margin_pct": float(r["mo_margin"] or 0) * 100.0,
                    "mo_p_per_l": float(r["mo_p_per_l"] or 0),
                }
                for r in atp
            ],
            "atp_window": {
                "yesterday": yesterday.isoformat(),
                "week_start": week_start.isoformat(),
                "month_start": m_start.isoformat(),
            },
        },
    }


# ---------------------------------------------------------------------------
# Tab 2 — Trends  (ALL panels GLOBAL, ignore every filter)
# ---------------------------------------------------------------------------


@router.get("/trends")
async def trends(
    request: Request,
    _user: dict = Depends(require_tag_role(*CEO_ROLES)),
):
    pool = get_datalake_gold_pool(request)
    today = date.today()
    fifteen_months_start = _shift_months(_month_start(today), -14)
    eighty_days_start = today - timedelta(days=79)

    scope = _global_scope_where("br4")

    # Monthly 15m: customer count + margin %, and profit + loads
    monthly_task = pool.fetch(
        f"""
        SELECT
          DATE_TRUNC('month', br4.origin_actual_departure)::date AS bucket,
          COUNT(DISTINCT br4.customer_name) AS customers,
          CASE WHEN SUM(br4.total_charge) > 0
               THEN SUM(br4.margin_amt)::numeric / SUM(br4.total_charge)::numeric
               ELSE 0 END AS margin_pct,
          COALESCE(SUM(br4.margin_amt), 0)::numeric AS profit,
          COUNT(*) FILTER (WHERE br4.total_charge IS NOT NULL AND br4.total_charge <> 0) AS loads
        FROM public.mcleod_gld_budget_report_v4 br4
        WHERE {scope}
          AND br4.origin_actual_departure::date >= $1
          AND br4.origin_actual_departure::date <= $2
        GROUP BY 1
        ORDER BY 1
        """,
        fifteen_months_start, today,
    )

    # Daily 80d: customer count + margin %, and profit + loads
    daily_task = pool.fetch(
        f"""
        SELECT
          br4.origin_actual_departure::date AS bucket,
          COUNT(DISTINCT br4.customer_name) AS customers,
          CASE WHEN SUM(br4.total_charge) > 0
               THEN SUM(br4.margin_amt)::numeric / SUM(br4.total_charge)::numeric
               ELSE 0 END AS margin_pct,
          COALESCE(SUM(br4.margin_amt), 0)::numeric AS profit,
          COUNT(*) FILTER (WHERE br4.total_charge IS NOT NULL AND br4.total_charge <> 0) AS loads
        FROM public.mcleod_gld_budget_report_v4 br4
        WHERE {scope}
          AND br4.origin_actual_departure::date >= $1
          AND br4.origin_actual_departure::date <= $2
        GROUP BY 1
        ORDER BY 1
        """,
        eighty_days_start, today,
    )

    monthly, daily = await asyncio.gather(monthly_task, daily_task)

    return {
        "success": True,
        "data": {
            "monthly": [
                {
                    "bucket": r["bucket"].isoformat(),
                    "customers": int(r["customers"] or 0),
                    "margin_pct": float(r["margin_pct"] or 0) * 100.0,
                    "profit": float(r["profit"] or 0),
                    "loads": int(r["loads"] or 0),
                }
                for r in monthly
            ],
            "daily": [
                {
                    "bucket": r["bucket"].isoformat(),
                    "customers": int(r["customers"] or 0),
                    "margin_pct": float(r["margin_pct"] or 0) * 100.0,
                    "profit": float(r["profit"] or 0),
                    "loads": int(r["loads"] or 0),
                }
                for r in daily
            ],
            "monthly_window": {
                "start": fifteen_months_start.isoformat(),
                "end": today.isoformat(),
            },
            "daily_window": {
                "start": eighty_days_start.isoformat(),
                "end": today.isoformat(),
            },
        },
    }


# ---------------------------------------------------------------------------
# Tab 3 — Customers
#   * Profit by Customer (scoped, sorted by profit DESC)
#   * Worst Profit by Customer (scoped, sorted by profit ASC)
#   * Top-5 Concentration by Revenue (GLOBAL, + "Others")
#   * Top-5 Concentration by Profit  (GLOBAL, + "Others")
# ---------------------------------------------------------------------------


@router.get("/customers")
async def customers(
    request: Request,
    range: Optional[str] = Query("mtd"),
    start_date: Optional[date] = Query(None),
    end_date: Optional[date] = Query(None),
    division: Optional[str] = Query(None),
    team: Optional[str] = Query(None),
    customer: Optional[str] = Query(None),
    _user: dict = Depends(require_tag_role(*CEO_ROLES)),
):
    pool = get_datalake_gold_pool(request)
    s, e = _resolve_range(range, start_date, end_date)

    # ---- Profit by Customer (scoped) ------------------------------------
    pc_params: list = []
    pc_where = _scope_where("br4", team, customer, pc_params, division=division)
    pc_params.extend([s, e])
    pc_df = (
        f"br4.origin_actual_departure >= ${len(pc_params)-1}"
        f" AND br4.origin_actual_departure < (${len(pc_params)}::date + 1)"
    )
    pc_task = pool.fetch(
        f"""
        WITH tot AS (
          SELECT
            COALESCE(SUM(br4.margin_amt), 0)::numeric AS total_margin
          FROM public.mcleod_gld_budget_report_v4 br4
          WHERE {pc_where} AND {pc_df}
        )
        SELECT
          TRIM(br4.customer_name) AS customer,
          COUNT(*) FILTER (WHERE br4.total_charge IS NOT NULL AND br4.total_charge <> 0) AS loads,
          COALESCE(SUM(br4.total_charge), 0)::numeric AS revenue,
          COALESCE(SUM(br4.margin_amt), 0)::numeric   AS profit,
          CASE WHEN SUM(br4.total_charge) > 0
               THEN SUM(br4.margin_amt)::numeric / SUM(br4.total_charge)::numeric
               ELSE 0 END AS margin_pct,
          CASE WHEN (SELECT total_margin FROM tot) > 0
               THEN SUM(br4.margin_amt)::numeric / (SELECT total_margin FROM tot)
               ELSE 0 END AS conc_pct
        FROM public.mcleod_gld_budget_report_v4 br4
        WHERE {pc_where} AND {pc_df}
          AND br4.customer_name IS NOT NULL
        GROUP BY TRIM(br4.customer_name)
        ORDER BY profit DESC NULLS LAST
        LIMIT 200
        """,
        *pc_params,
    )

    # ---- Worst Profit by Customer (scoped, reverse sort) ---------------
    wp_params: list = []
    wp_where = _scope_where("br4", team, customer, wp_params, division=division)
    wp_params.extend([s, e])
    wp_df = (
        f"br4.origin_actual_departure >= ${len(wp_params)-1}"
        f" AND br4.origin_actual_departure < (${len(wp_params)}::date + 1)"
    )
    wp_task = pool.fetch(
        f"""
        WITH tot AS (
          SELECT COALESCE(SUM(br4.margin_amt), 0)::numeric AS total_margin
          FROM public.mcleod_gld_budget_report_v4 br4
          WHERE {wp_where} AND {wp_df}
        )
        SELECT
          TRIM(br4.customer_name) AS customer,
          COUNT(*) FILTER (WHERE br4.total_charge IS NOT NULL AND br4.total_charge <> 0) AS loads,
          COALESCE(SUM(br4.total_charge), 0)::numeric AS revenue,
          COALESCE(SUM(br4.margin_amt), 0)::numeric   AS profit,
          CASE WHEN SUM(br4.total_charge) > 0
               THEN SUM(br4.margin_amt)::numeric / SUM(br4.total_charge)::numeric
               ELSE 0 END AS margin_pct,
          CASE WHEN (SELECT total_margin FROM tot) > 0
               THEN SUM(br4.margin_amt)::numeric / (SELECT total_margin FROM tot)
               ELSE 0 END AS conc_pct
        FROM public.mcleod_gld_budget_report_v4 br4
        WHERE {wp_where} AND {wp_df}
          AND br4.customer_name IS NOT NULL
        GROUP BY TRIM(br4.customer_name)
        ORDER BY profit ASC NULLS LAST
        LIMIT 200
        """,
        *wp_params,
    )

    # ---- Top-5 Concentration by Revenue (GLOBAL) ------------------------
    # Use full year to be stable. "Others" is rank 6+.
    g_scope = _global_scope_where("br4")
    top5_rev_task = pool.fetch(
        f"""
        WITH by_cust AS (
          SELECT
            TRIM(br4.customer_name) AS customer,
            COALESCE(SUM(br4.total_charge), 0)::numeric AS revenue,
            COALESCE(SUM(br4.margin_amt), 0)::numeric   AS profit
          FROM public.mcleod_gld_budget_report_v4 br4
          WHERE {g_scope}
            AND br4.origin_actual_departure >= $1
            AND br4.origin_actual_departure < ($2::date + 1)
            AND br4.customer_name IS NOT NULL
          GROUP BY TRIM(br4.customer_name)
        ),
        ranked AS (
          SELECT
            customer, revenue, profit,
            ROW_NUMBER() OVER (ORDER BY revenue DESC NULLS LAST) AS rn,
            SUM(revenue) OVER () AS total_rev
          FROM by_cust
        )
        SELECT
          CASE WHEN rn <= 5 THEN customer ELSE 'Others' END AS customer,
          SUM(revenue)::numeric AS revenue,
          SUM(profit)::numeric  AS profit,
          CASE WHEN MAX(total_rev) > 0
               THEN SUM(revenue)::numeric / MAX(total_rev)
               ELSE 0 END AS conc_pct,
          MIN(rn) AS rank_min
        FROM ranked
        GROUP BY CASE WHEN rn <= 5 THEN customer ELSE 'Others' END
        ORDER BY rank_min
        """,
        YEAR_START, YEAR_END,
    )

    # ---- Top-5 Concentration by Profit (GLOBAL) -------------------------
    top5_prof_task = pool.fetch(
        f"""
        WITH by_cust AS (
          SELECT
            TRIM(br4.customer_name) AS customer,
            COALESCE(SUM(br4.total_charge), 0)::numeric AS revenue,
            COALESCE(SUM(br4.margin_amt), 0)::numeric   AS profit
          FROM public.mcleod_gld_budget_report_v4 br4
          WHERE {g_scope}
            AND br4.origin_actual_departure >= $1
            AND br4.origin_actual_departure < ($2::date + 1)
            AND br4.customer_name IS NOT NULL
          GROUP BY TRIM(br4.customer_name)
        ),
        ranked AS (
          SELECT
            customer, revenue, profit,
            ROW_NUMBER() OVER (ORDER BY profit DESC NULLS LAST) AS rn,
            SUM(profit) OVER () AS total_prof
          FROM by_cust
        )
        SELECT
          CASE WHEN rn <= 5 THEN customer ELSE 'Others' END AS customer,
          SUM(revenue)::numeric AS revenue,
          SUM(profit)::numeric  AS profit,
          CASE WHEN MAX(total_prof) > 0
               THEN SUM(profit)::numeric / MAX(total_prof)
               ELSE 0 END AS conc_pct,
          MIN(rn) AS rank_min
        FROM ranked
        GROUP BY CASE WHEN rn <= 5 THEN customer ELSE 'Others' END
        ORDER BY rank_min
        """,
        YEAR_START, YEAR_END,
    )

    pc, wp, t5r, t5p = await asyncio.gather(
        pc_task, wp_task, top5_rev_task, top5_prof_task
    )

    def _map_cust(r):
        return {
            "customer": r["customer"],
            "loads": int(r["loads"] or 0),
            "revenue": float(r["revenue"] or 0),
            "profit": float(r["profit"] or 0),
            "margin_pct": float(r["margin_pct"] or 0) * 100.0,
            "conc_pct": float(r["conc_pct"] or 0) * 100.0,
            "avg_p_per_l": (
                float(r["profit"]) / int(r["loads"]) if r["loads"] else 0.0
            ),
        }

    def _map_top5(r):
        return {
            "customer": r["customer"],
            "revenue": float(r["revenue"] or 0),
            "profit": float(r["profit"] or 0),
            "conc_pct": float(r["conc_pct"] or 0) * 100.0,
        }

    return {
        "success": True,
        "data": {
            "by_customer": [_map_cust(r) for r in pc],
            "worst_by_customer": [_map_cust(r) for r in wp],
            "top5_revenue": [_map_top5(r) for r in t5r],
            "top5_profit": [_map_top5(r) for r in t5p],
            "window": {"start": s.isoformat(), "end": e.isoformat()},
        },
    }


# ---------------------------------------------------------------------------
# Tab 4 — Weekly  (ALL panels GLOBAL)
# ---------------------------------------------------------------------------


@router.get("/weekly")
async def weekly(
    request: Request,
    _user: dict = Depends(require_tag_role(*CEO_ROLES)),
):
    pool = get_datalake_gold_pool(request)
    today = date.today()
    this_week_mon = _week_start(today)
    ten_weeks_start = this_week_mon - timedelta(weeks=9)
    summary_start = today - timedelta(weeks=12)  # ~12 weeks for Summary by Week

    scope = _global_scope_where("br4")

    # Last 10 weeks — loads + revenue + profit + margin
    weekly_task = pool.fetch(
        f"""
        SELECT
          (br4.origin_actual_departure::date
             - ((EXTRACT(DOW FROM br4.origin_actual_departure)::int + 6) % 7))::date AS week_start,
          COUNT(*) FILTER (WHERE br4.total_charge IS NOT NULL AND br4.total_charge <> 0) AS loads,
          COALESCE(SUM(br4.total_charge), 0)::numeric AS revenue,
          COALESCE(SUM(br4.margin_amt), 0)::numeric AS profit,
          CASE WHEN SUM(br4.total_charge) > 0
               THEN SUM(br4.margin_amt)::numeric / SUM(br4.total_charge)::numeric
               ELSE 0 END AS margin_pct
        FROM public.mcleod_gld_budget_report_v4 br4
        WHERE {scope}
          AND br4.origin_actual_departure::date >= $1
          AND br4.origin_actual_departure::date <= $2
        GROUP BY 1
        ORDER BY 1
        """,
        ten_weeks_start, today,
    )

    # Summary by Week — wider window, with lane count
    summary_task = pool.fetch(
        f"""
        SELECT
          (br4.origin_actual_departure::date
             - ((EXTRACT(DOW FROM br4.origin_actual_departure)::int + 6) % 7))::date AS week_start,
          COUNT(DISTINCT TRIM(COALESCE(br4.origin_name,'')) || '-' || TRIM(COALESCE(br4.dest_name,''))) AS lanes,
          COUNT(*) FILTER (WHERE br4.total_charge IS NOT NULL AND br4.total_charge <> 0) AS loads,
          COALESCE(SUM(br4.total_charge), 0)::numeric AS revenue,
          COALESCE(SUM(br4.margin_amt), 0)::numeric AS profit,
          CASE WHEN SUM(br4.total_charge) > 0
               THEN SUM(br4.margin_amt)::numeric / SUM(br4.total_charge)::numeric
               ELSE 0 END AS margin_pct
        FROM public.mcleod_gld_budget_report_v4 br4
        WHERE {scope}
          AND br4.origin_actual_departure::date >= $1
          AND br4.origin_actual_departure::date <= $2
        GROUP BY 1
        ORDER BY 1 DESC
        """,
        summary_start, today,
    )

    weekly_rows, summary_rows = await asyncio.gather(weekly_task, summary_task)

    return {
        "success": True,
        "data": {
            "weeks": [
                {
                    "week_start": r["week_start"].isoformat(),
                    "loads": int(r["loads"] or 0),
                    "revenue": float(r["revenue"] or 0),
                    "profit": float(r["profit"] or 0),
                    "margin_pct": float(r["margin_pct"] or 0) * 100.0,
                }
                for r in weekly_rows
            ],
            "summary_by_week": [
                {
                    "week_start": r["week_start"].isoformat(),
                    "lanes": int(r["lanes"] or 0),
                    "loads": int(r["loads"] or 0),
                    "revenue": float(r["revenue"] or 0),
                    "profit": float(r["profit"] or 0),
                    "margin_pct": float(r["margin_pct"] or 0) * 100.0,
                }
                for r in summary_rows
            ],
        },
    }


# ---------------------------------------------------------------------------
# Tab 5 — Risk (scoped; all filters to margin_amt < 0)
#   * Worst Margins by Lanes (with 15/18/20% profit + diff+)
#   * Negative Loads by Order (with carrier, concentration)
#   * Negative Loads by Customer
# ---------------------------------------------------------------------------


@router.get("/risk")
async def risk(
    request: Request,
    range: Optional[str] = Query("mtd"),
    start_date: Optional[date] = Query(None),
    end_date: Optional[date] = Query(None),
    division: Optional[str] = Query(None),
    team: Optional[str] = Query(None),
    customer: Optional[str] = Query(None),
    _user: dict = Depends(require_tag_role(*CEO_ROLES)),
):
    pool = get_datalake_gold_pool(request)
    s, e = _resolve_range(range, start_date, end_date)

    # ---- Worst Margins by Lanes ----------------------------------------
    # Date filter is half-open `>= s AND < e+1` so Postgres can use the btree
    # on origin_actual_departure (idx_v4_dep). Wrapping the column in `::date`
    # was killing sargability and forcing a full seq-scan of v4 (380 MB).
    wm_params: list = []
    wm_where = _scope_where("br4", team, customer, wm_params, division=division)
    wm_params.extend([s, e])
    wm_df = (
        f"br4.origin_actual_departure >= ${len(wm_params)-1}"
        f" AND br4.origin_actual_departure < (${len(wm_params)}::date + 1)"
    )
    wm_task = pool.fetch(
        f"""
        SELECT
          TRIM(br4.customer_name) AS customer,
          TRIM(br4.origin_name)   AS origin,
          TRIM(br4.dest_name)     AS destination,
          COUNT(*) FILTER (WHERE br4.total_charge IS NOT NULL AND br4.total_charge <> 0) AS loads,
          COALESCE(SUM(br4.total_charge), 0)::numeric AS revenue,
          COALESCE(SUM(br4.margin_amt), 0)::numeric AS profit,
          CASE WHEN SUM(br4.total_charge) > 0
               THEN SUM(br4.margin_amt)::numeric / SUM(br4.total_charge)::numeric
               ELSE 0 END AS margin_pct,
          GREATEST(0, SUM(br4.total_charge)::numeric * 0.15 - SUM(br4.margin_amt)::numeric) AS diff_15,
          GREATEST(0, SUM(br4.total_charge)::numeric * 0.18 - SUM(br4.margin_amt)::numeric) AS diff_18,
          GREATEST(0, SUM(br4.total_charge)::numeric * 0.20 - SUM(br4.margin_amt)::numeric) AS diff_20
        FROM public.mcleod_gld_budget_report_v4 br4
        WHERE {wm_where} AND {wm_df}
        GROUP BY TRIM(br4.customer_name), TRIM(br4.origin_name), TRIM(br4.dest_name)
        HAVING COALESCE(SUM(br4.margin_amt), 0) < 0
        ORDER BY profit ASC NULLS LAST
        LIMIT 200
        """,
        *wm_params,
    )

    # ---- Negative Loads by Order ---------------------------------------
    # LEFT JOIN LATERAL to fetch first-by-movement_id payee_name per
    # (order_id, company_id). The old CTE pre-aggregated all 400k+ movement
    # rows with a window function before joining (5.9s). LATERAL fires one
    # index seek per matching v4 row using idx_movement_order_company_mv,
    # cutting the query to ~150ms even when all filters are open.
    no_params: list = []
    no_where = _scope_where("br4", team, customer, no_params, division=division)
    no_params.extend([s, e])
    no_df = (
        f"br4.origin_actual_departure >= ${len(no_params)-1}"
        f" AND br4.origin_actual_departure < (${len(no_params)}::date + 1)"
    )
    no_task = pool.fetch(
        f"""
        WITH tot AS (
          SELECT COALESCE(SUM(br4.margin_amt), 0)::numeric AS total_margin
          FROM public.mcleod_gld_budget_report_v4 br4
          WHERE {no_where} AND {no_df}
            AND br4.margin_amt < 0
        )
        SELECT
          TRIM(br4.id)            AS id,
          TRIM(br4.customer_name) AS customer,
          COALESCE(TRIM(mov.payee_name), '') AS carrier,
          TRIM(br4.origin_name)   AS origin,
          TRIM(br4.dest_name)     AS destination,
          COALESCE(br4.total_charge, 0)::numeric AS revenue,
          COALESCE(br4.margin_amt, 0)::numeric AS profit,
          CASE WHEN br4.total_charge > 0
               THEN br4.margin_amt::numeric / br4.total_charge::numeric
               ELSE 0 END AS margin_pct,
          CASE WHEN (SELECT total_margin FROM tot) <> 0
               THEN br4.margin_amt::numeric / (SELECT total_margin FROM tot)
               ELSE 0 END AS conc_pct
        FROM public.mcleod_gld_budget_report_v4 br4
        LEFT JOIN LATERAL (
          SELECT m.payee_name
          FROM public.mcleod_gld_movement m
          WHERE m.order_id = br4.id AND m.company_id = br4.company_id
          ORDER BY m.movement_id ASC
          LIMIT 1
        ) mov ON TRUE
        WHERE {no_where} AND {no_df}
          AND br4.margin_amt < 0
        ORDER BY br4.margin_amt ASC
        LIMIT 500
        """,
        *no_params,
    )

    # ---- Negative Loads by Customer ------------------------------------
    nc_params: list = []
    nc_where = _scope_where("br4", team, customer, nc_params, division=division)
    nc_params.extend([s, e])
    nc_df = (
        f"br4.origin_actual_departure >= ${len(nc_params)-1}"
        f" AND br4.origin_actual_departure < (${len(nc_params)}::date + 1)"
    )
    nc_task = pool.fetch(
        f"""
        WITH tot AS (
          SELECT COALESCE(SUM(br4.margin_amt), 0)::numeric AS total_margin
          FROM public.mcleod_gld_budget_report_v4 br4
          WHERE {nc_where} AND {nc_df}
            AND br4.margin_amt < 0
        )
        SELECT
          TRIM(br4.customer_name) AS customer,
          COUNT(*) FILTER (WHERE br4.total_charge IS NOT NULL AND br4.total_charge <> 0) AS loads,
          COALESCE(SUM(br4.total_charge), 0)::numeric AS revenue,
          COALESCE(SUM(br4.margin_amt), 0)::numeric AS profit,
          CASE WHEN (SELECT total_margin FROM tot) <> 0
               THEN SUM(br4.margin_amt)::numeric / (SELECT total_margin FROM tot)
               ELSE 0 END AS conc_pct
        FROM public.mcleod_gld_budget_report_v4 br4
        WHERE {nc_where} AND {nc_df}
          AND br4.margin_amt < 0
        GROUP BY TRIM(br4.customer_name)
        ORDER BY profit ASC
        LIMIT 200
        """,
        *nc_params,
    )

    wm, no, nc = await asyncio.gather(wm_task, no_task, nc_task)

    return {
        "success": True,
        "data": {
            "worst_lanes": [
                {
                    "customer": r["customer"],
                    "origin": r["origin"],
                    "destination": r["destination"],
                    "loads": int(r["loads"] or 0),
                    "revenue": float(r["revenue"] or 0),
                    "profit": float(r["profit"] or 0),
                    "margin_pct": float(r["margin_pct"] or 0) * 100.0,
                    "diff_15": float(r["diff_15"] or 0),
                    "diff_18": float(r["diff_18"] or 0),
                    "diff_20": float(r["diff_20"] or 0),
                }
                for r in wm
            ],
            "neg_orders": [
                {
                    "id": r["id"],
                    "customer": r["customer"],
                    "carrier": r["carrier"],
                    "origin": r["origin"],
                    "destination": r["destination"],
                    "revenue": float(r["revenue"] or 0),
                    "profit": float(r["profit"] or 0),
                    "margin_pct": float(r["margin_pct"] or 0) * 100.0,
                    "conc_pct": float(r["conc_pct"] or 0) * 100.0,
                }
                for r in no
            ],
            "neg_customers": [
                {
                    "customer": r["customer"],
                    "loads": int(r["loads"] or 0),
                    "revenue": float(r["revenue"] or 0),
                    "profit": float(r["profit"] or 0),
                    "conc_pct": float(r["conc_pct"] or 0) * 100.0,
                }
                for r in nc
            ],
            "window": {"start": s.isoformat(), "end": e.isoformat()},
        },
    }


# ---------------------------------------------------------------------------
# Tab 6 — Orders
#   * Lane Production Analysis (scoped, customer+origin+dest aggregate)
#   * All Orders (scoped, load-level detail with carrier)
# ---------------------------------------------------------------------------


@router.get("/orders")
async def orders(
    request: Request,
    range: Optional[str] = Query("mtd"),
    start_date: Optional[date] = Query(None),
    end_date: Optional[date] = Query(None),
    division: Optional[str] = Query(None),
    team: Optional[str] = Query(None),
    customer: Optional[str] = Query(None),
    _user: dict = Depends(require_tag_role(*CEO_ROLES)),
):
    pool = get_datalake_gold_pool(request)
    s, e = _resolve_range(range, start_date, end_date)

    # ---- Lane Production Analysis --------------------------------------
    lpa_params: list = []
    lpa_where = _scope_where("br4", team, customer, lpa_params, division=division)
    lpa_params.extend([s, e])
    lpa_df = (
        f"br4.origin_actual_departure >= ${len(lpa_params)-1}"
        f" AND br4.origin_actual_departure < (${len(lpa_params)}::date + 1)"
    )
    lpa_task = pool.fetch(
        f"""
        WITH tot AS (
          SELECT COALESCE(SUM(br4.margin_amt), 0)::numeric AS total_margin
          FROM public.mcleod_gld_budget_report_v4 br4
          WHERE {lpa_where} AND {lpa_df}
        )
        SELECT
          TRIM(br4.customer_name) AS customer,
          TRIM(br4.origin_name)   AS origin,
          TRIM(br4.dest_name)     AS destination,
          COUNT(*) FILTER (WHERE br4.total_charge IS NOT NULL AND br4.total_charge <> 0) AS loads,
          COALESCE(SUM(br4.total_charge), 0)::numeric AS revenue,
          COALESCE(SUM(br4.margin_amt), 0)::numeric AS profit,
          CASE WHEN SUM(br4.total_charge) > 0
               THEN SUM(br4.margin_amt)::numeric / SUM(br4.total_charge)::numeric
               ELSE 0 END AS margin_pct,
          CASE WHEN (SELECT total_margin FROM tot) <> 0
               THEN SUM(br4.margin_amt)::numeric / (SELECT total_margin FROM tot)
               ELSE 0 END AS conc_pct,
          GREATEST(0, SUM(br4.total_charge)::numeric * 0.15 - SUM(br4.margin_amt)::numeric) AS diff_15,
          GREATEST(0, SUM(br4.total_charge)::numeric * 0.18 - SUM(br4.margin_amt)::numeric) AS diff_18,
          GREATEST(0, SUM(br4.total_charge)::numeric * 0.20 - SUM(br4.margin_amt)::numeric) AS diff_20
        FROM public.mcleod_gld_budget_report_v4 br4
        WHERE {lpa_where} AND {lpa_df}
        GROUP BY TRIM(br4.customer_name), TRIM(br4.origin_name), TRIM(br4.dest_name)
        ORDER BY profit DESC NULLS LAST
        LIMIT 500
        """,
        *lpa_params,
    )

    # ---- All Orders (with carrier via LEFT JOIN movement) --------------
    # LATERAL pulls first-by-movement_id payee_name per (order_id, company_id)
    # using idx_movement_order_company_mv (1 index seek per matching v4 row),
    # vs the old CTE that pre-aggregated 400k+ movement rows with a window
    # function. Cuts the query from ~6s to ~150ms.
    ao_params: list = []
    ao_where = _scope_where("br4", team, customer, ao_params, division=division)
    ao_params.extend([s, e])
    ao_df = (
        f"br4.origin_actual_departure >= ${len(ao_params)-1}"
        f" AND br4.origin_actual_departure < (${len(ao_params)}::date + 1)"
    )
    ao_task = pool.fetch(
        f"""
        SELECT
          CASE WHEN TRIM(br4.team_id) = '{DFW_TEAM_ID}' THEN TRIM(br4.team)
               ELSE TRIM(br4.team_id) END AS team,
          TRIM(br4.id)            AS id,
          TRIM(br4.customer_name) AS customer,
          COALESCE(TRIM(mov.payee_name), '') AS carrier,
          TRIM(br4.origin_name)   AS origin,
          TRIM(br4.dest_name)     AS destination,
          br4.origin_actual_departure AS departure,
          COALESCE(br4.total_charge, 0)::numeric AS revenue,
          COALESCE(br4.margin_amt, 0)::numeric AS profit,
          CASE WHEN br4.total_charge > 0
               THEN br4.margin_amt::numeric / br4.total_charge::numeric
               ELSE 0 END AS margin_pct,
          GREATEST(0, br4.total_charge::numeric * 0.15 - br4.margin_amt::numeric) AS diff_15,
          GREATEST(0, br4.total_charge::numeric * 0.18 - br4.margin_amt::numeric) AS diff_18,
          GREATEST(0, br4.total_charge::numeric * 0.20 - br4.margin_amt::numeric) AS diff_20
        FROM public.mcleod_gld_budget_report_v4 br4
        LEFT JOIN LATERAL (
          SELECT m.payee_name
          FROM public.mcleod_gld_movement m
          WHERE m.order_id = br4.id AND m.company_id = br4.company_id
          ORDER BY m.movement_id ASC
          LIMIT 1
        ) mov ON TRUE
        WHERE {ao_where} AND {ao_df}
        ORDER BY br4.origin_actual_departure DESC NULLS LAST
        LIMIT 1000
        """,
        *ao_params,
    )

    lpa, ao = await asyncio.gather(lpa_task, ao_task)

    return {
        "success": True,
        "data": {
            "lane_analysis": [
                {
                    "customer": r["customer"],
                    "origin": r["origin"],
                    "destination": r["destination"],
                    "loads": int(r["loads"] or 0),
                    "revenue": float(r["revenue"] or 0),
                    "profit": float(r["profit"] or 0),
                    "margin_pct": float(r["margin_pct"] or 0) * 100.0,
                    "conc_pct": float(r["conc_pct"] or 0) * 100.0,
                    "diff_15": float(r["diff_15"] or 0),
                    "diff_18": float(r["diff_18"] or 0),
                    "diff_20": float(r["diff_20"] or 0),
                }
                for r in lpa
            ],
            "all_orders": [
                {
                    "team": r["team"],
                    "id": r["id"],
                    "customer": r["customer"],
                    "carrier": r["carrier"],
                    "origin": r["origin"],
                    "destination": r["destination"],
                    "departure": r["departure"].isoformat() if r["departure"] else None,
                    "revenue": float(r["revenue"] or 0),
                    "profit": float(r["profit"] or 0),
                    "margin_pct": float(r["margin_pct"] or 0) * 100.0,
                    "diff_15": float(r["diff_15"] or 0),
                    "diff_18": float(r["diff_18"] or 0),
                    "diff_20": float(r["diff_20"] or 0),
                }
                for r in ao
            ],
            "window": {"start": s.isoformat(), "end": e.isoformat()},
        },
    }
