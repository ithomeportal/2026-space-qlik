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

Per Bruno R5 (2026-05-21) panels fall into three groups:
- FULLY SCOPED: respect range + division + team + customer (KPIs, Summary by
  Team, Profit by Customer, Worst Profit by Customer, Worst Margins by
  Lanes, Negative Loads by Order / Customer, Lane Production Analysis,
  All Orders).
- DATE-FIXED: respect division + team + customer, but date windows are
  fixed (Yd/Wk/Mo for All Teams Performance; 15 months / 80 days for
  Trends; 10 weeks / 12 weeks for Weekly; full year for Top-5
  Concentration by Revenue / Profit).
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

from app.clock import cst_today
from app.datalake import pad_variants as _pad_variants
from app.routers.deps import get_datalake_gold_pool, require_report_access

YEAR_START = date(2026, 1, 1)
YEAR_END = date(2026, 12, 31)
# Bruno R9 (2026-06-03): Custom range may reach back to last year and two
# years ago (v4 has full 2024+2025 data). MTD/YTD/Full stay pinned to 2026.
CUSTOM_MIN = date(2024, 1, 1)

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
    """Clamp a Custom-range bound to [CUSTOM_MIN, YEAR_END].

    Only the range="custom" branch calls this — preset ranges stay pinned
    to the 2026 calendar year.
    """
    if d is None:
        return default
    if d < CUSTOM_MIN:
        return CUSTOM_MIN
    if d > YEAR_END:
        return YEAR_END
    return d


def _resolve_range(
    rng: Optional[str],
    start_date: Optional[date],
    end_date: Optional[date],
) -> tuple[date, date]:
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


def _production_cte(start_pos: int, end_pos: int) -> str:
    """Unified production source — CORP from daily_production_budget_report,
    DFW from v4 (aggregated to customer × day to match budget_report grain).

    daily_production_budget_report is CORP-only (Team IDs TEAM1..TEAM5);
    DFW customers are absent there, which made every DFW Overview panel
    return $0. v4 has all DFW production, so we UNION ALL the two sources
    keyed by customer_name + Date and the rest of each Overview query
    (the customer_team JOIN, the GROUP BY ct.division_team, etc.) keeps
    working unchanged.

    For CORP, v4 vs budget_report MTD parity is ~0.0% (Jan-Mar 2026)
    and ~0.17% in the current month. Empirically zero DFW customers
    overlap with budget_report customers, so no double-counting.

    Args:
      start_pos / end_pos: 1-indexed $ placeholder positions for the
        date window (date / date). The same two params drive both
        sides — outer queries can keep `WHERE budget."Date" BETWEEN
        $s AND $e` if they want the redundant predicate.
    """
    return f"""
    production AS (
      SELECT
        TRIM("Customer Name") AS "Customer Name",
        COALESCE("Loads Actual",   0)::numeric AS "Loads Actual",
        COALESCE("Revenue Actual", 0)::numeric AS "Revenue Actual",
        COALESCE("Profit Actual",  0)::numeric AS "Profit Actual",
        "Date"
      FROM public.daily_production_budget_report
      WHERE "Date" BETWEEN ${start_pos} AND ${end_pos}
      UNION ALL
      SELECT
        TRIM(customer_name) AS "Customer Name",
        COUNT(*)::numeric AS "Loads Actual",
        COALESCE(SUM(total_charge), 0)::numeric AS "Revenue Actual",
        COALESCE(SUM(margin_amt),   0)::numeric AS "Profit Actual",
        origin_actual_departure::date AS "Date"
      FROM public.mcleod_gld_budget_report_v4
      WHERE team_id = 'TEAM-DFW'
        AND company_id = ANY('{{TMS,"TMS ",TMS3}}'::text[])
        AND status     = ANY('{{D,P}}'::text[])
        AND origin_actual_departure >= ${start_pos}
        AND origin_actual_departure <  (${end_pos}::date + 1)
      GROUP BY TRIM(customer_name), origin_actual_departure::date
    )
    """


# ---------------------------------------------------------------------------
# /filters — teams + distinct customer list
# ---------------------------------------------------------------------------


@router.get("/filters")
async def filters(
    request: Request,
    _user: dict = Depends(require_report_access("ceo-executive")),
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
    _user: dict = Depends(require_report_access("ceo-executive")),
):
    pool = get_datalake_gold_pool(request)
    s, e = _resolve_range(range, start_date, end_date)
    today = cst_today()
    m_start = _month_start(today)
    m_end = _month_end(today)

    # Row-list for Summary by Team unnest join. One-row-per-team so teams
    # with no production still appear in the table.
    if team:
        team_list_for_unnest = [team]
    elif division == "CORP":
        team_list_for_unnest = list(CORP_TEAMS)
    elif division == "DFW":
        team_list_for_unnest = list(DFW_SUB_TEAMS)
    else:
        team_list_for_unnest = list(ALL_DIVISION_TEAMS)

    # ---- KPIs (scoped) --------------------------------------------------
    # Read v4 directly to match the calculation used in /customers
    # "Profit by Customer" — Bruno's canonical aggregation
    # (SUM(margin_amt) / SUM(total_charge) grouped from raw v4 rows).
    # The previous unified production CTE (CORP daily_production_budget_report
    # UNION DFW v4) produced different roll-ups vs what the customer table
    # showed; users called this out as inconsistent on 2026-05-07.
    kpi_params: list = []
    kpi_where = _scope_where("br4", team, customer, kpi_params, division=division)
    kpi_params.extend([s, e])
    kpi_df = (
        f"br4.origin_actual_departure >= ${len(kpi_params)-1}"
        f" AND br4.origin_actual_departure < (${len(kpi_params)}::date + 1)"
    )
    kpi_task = pool.fetchrow(
        f"""
        SELECT
          COUNT(*) FILTER (WHERE br4.total_charge IS NOT NULL AND br4.total_charge <> 0) AS loads,
          COALESCE(SUM(br4.total_charge), 0)::numeric AS revenue,
          COALESCE(SUM(br4.margin_amt),   0)::numeric AS profit,
          CASE WHEN SUM(br4.total_charge) > 0
               THEN SUM(br4.margin_amt)::numeric / SUM(br4.total_charge)::numeric
               ELSE 0 END AS margin_pct,
          CASE WHEN COUNT(*) FILTER (WHERE br4.total_charge IS NOT NULL AND br4.total_charge <> 0) > 0
               THEN SUM(br4.total_charge)::numeric
                    / NULLIF(COUNT(*) FILTER (WHERE br4.total_charge IS NOT NULL AND br4.total_charge <> 0), 0)::numeric
               ELSE 0 END AS avg_r_per_l,
          CASE WHEN COUNT(*) FILTER (WHERE br4.total_charge IS NOT NULL AND br4.total_charge <> 0) > 0
               THEN SUM(br4.margin_amt)::numeric
                    / NULLIF(COUNT(*) FILTER (WHERE br4.total_charge IS NOT NULL AND br4.total_charge <> 0), 0)::numeric
               ELSE 0 END AS avg_p_per_l
        FROM public.mcleod_gld_budget_report_v4 br4
        WHERE {kpi_where} AND {kpi_df}
        """,
        *kpi_params,
    )

    # ---- Summary by Team (scoped) --------------------------------------
    # Same v4-direct path as KPIs, grouped by the unified team label
    # (team_id for CORP, TRIM(team) sub-team for DFW). LEFT JOIN unnest
    # so empty teams still appear with zeros.
    sbt_params: list = []
    sbt_where = _scope_where("br4", team, customer, sbt_params, division=division)
    sbt_params.extend([s, e])
    sbt_df = (
        f"br4.origin_actual_departure >= ${len(sbt_params)-1}"
        f" AND br4.origin_actual_departure < (${len(sbt_params)}::date + 1)"
    )
    sbt_params.append(team_list_for_unnest)
    sbt_unnest_pos = len(sbt_params)
    sbt_task = pool.fetch(
        f"""
        WITH agg AS (
          SELECT
            CASE WHEN TRIM(br4.team_id) = '{DFW_TEAM_ID}' THEN TRIM(br4.team)
                 ELSE TRIM(br4.team_id) END AS team,
            COUNT(DISTINCT TRIM(br4.customer_name)) AS cust,
            COUNT(*) FILTER (WHERE br4.total_charge IS NOT NULL AND br4.total_charge <> 0) AS loads,
            COALESCE(SUM(br4.total_charge), 0)::numeric AS revenue,
            COALESCE(SUM(br4.margin_amt),   0)::numeric AS profit
          FROM public.mcleod_gld_budget_report_v4 br4
          WHERE {sbt_where} AND {sbt_df}
          GROUP BY 1
        )
        SELECT
          t.team,
          COALESCE(a.cust,    0) AS cust,
          COALESCE(a.loads,   0) AS loads,
          COALESCE(a.revenue, 0)::numeric AS revenue,
          COALESCE(a.profit,  0)::numeric AS profit
        FROM unnest(${sbt_unnest_pos}::text[]) AS t(team)
        LEFT JOIN agg a ON a.team = t.team
        ORDER BY profit DESC NULLS LAST, team
        """,
        *sbt_params,
    )

    # ---- Profit-TM (semi-scoped: current month, division+team+customer apply) ---
    # Same v4-direct read for consistency with the KPIs above.
    tm_params: list = []
    tm_where = _scope_where("br4", team, customer, tm_params, division=division)
    tm_params.extend([m_start, m_end])
    tm_df = (
        f"br4.origin_actual_departure >= ${len(tm_params)-1}"
        f" AND br4.origin_actual_departure < (${len(tm_params)}::date + 1)"
    )
    profit_tm_task = pool.fetchval(
        f"""
        SELECT COALESCE(SUM(br4.margin_amt), 0)::numeric
        FROM public.mcleod_gld_budget_report_v4 br4
        WHERE {tm_where} AND {tm_df}
        """,
        *tm_params,
    )

    # ---- All Teams Performance (Yd / Week / Month — fixed windows) ------
    # Bruno R5 (2026-05-21): now honors Division + Team + Customer. Date
    # windows (yesterday / week / month-to-date) stay fixed regardless of
    # the Range pill, so the panel is still useful as a quick "are we
    # tracking" snapshot. The unnest LEFT JOIN ensures empty teams in the
    # current selection still render with zeros.
    # Placeholders:
    #   $1 yesterday, $2 week_start, $3 today, $4 m_start (production window),
    #   $5 padded team_id universe for customer_team CTE (narrowed by division),
    #   $6 unnest list of visible team labels,
    #   $7 customer filter ("" = all customers — predicate is no-op).
    yesterday = today - timedelta(days=1)
    week_start = _week_start(today)
    atp_task = pool.fetch(
        f"""
        WITH {_production_cte(4, 3)},
        {_customer_team_cte(5)},
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
          FROM production budget
          JOIN customer_team ct ON TRIM(budget."Customer Name") = ct.customer_name
          WHERE UPPER(COALESCE(budget."Customer Name",'')) NOT LIKE '%OILTEX%'
            AND UPPER(COALESCE(budget."Customer Name",'')) NOT LIKE '%UNILINK%'
            AND ($7 = '' OR TRIM(budget."Customer Name") = $7)
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
        _pad_variants(_division_team_ids(division), width=8),
        team_list_for_unnest,
        customer or "",
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
    division: Optional[str] = Query(None),
    team: Optional[str] = Query(None),
    customer: Optional[str] = Query(None),
    _user: dict = Depends(require_report_access("ceo-executive")),
):
    pool = get_datalake_gold_pool(request)
    today = cst_today()
    fifteen_months_start = _shift_months(_month_start(today), -14)
    eighty_days_start = today - timedelta(days=79)

    # Bruno R4 (2026-05-12): Trends panels honor Team. R5 (2026-05-21):
    # Customer too. Date windows stay fixed at 15 months / 80 days. Separate
    # param lists per task — different placeholder counts per gather call.
    monthly_params: list = []
    monthly_scope = _scope_where("br4", team, customer, monthly_params, division=division)
    monthly_params.extend([fifteen_months_start, today])
    m_s, m_e = len(monthly_params) - 1, len(monthly_params)

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
        WHERE {monthly_scope}
          AND br4.origin_actual_departure::date >= ${m_s}
          AND br4.origin_actual_departure::date <= ${m_e}
        GROUP BY 1
        ORDER BY 1
        """,
        *monthly_params,
    )

    daily_params: list = []
    daily_scope = _scope_where("br4", team, customer, daily_params, division=division)
    daily_params.extend([eighty_days_start, today])
    d_s, d_e = len(daily_params) - 1, len(daily_params)

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
        WHERE {daily_scope}
          AND br4.origin_actual_departure::date >= ${d_s}
          AND br4.origin_actual_departure::date <= ${d_e}
        GROUP BY 1
        ORDER BY 1
        """,
        *daily_params,
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
    _user: dict = Depends(require_report_access("ceo-executive")),
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

    # ---- Top-5 Concentration ($-window = full year) ---------------------
    # Bruno R5 (2026-05-21): Customer-aware (collapses to one slice when set).
    # R7 (2026-05-26): now also honors Division + Team (previously global), and
    # returns ALL ranked customers so the frontend can expand the "Others"
    # slice into the full remaining-customer list. Date window stays full-year
    # and date-immutable.
    t5r_params: list = []
    t5r_scope = _scope_where("br4", team, customer, t5r_params, division=division)
    t5r_params.extend([YEAR_START, YEAR_END])
    t5r_df = (
        f"br4.origin_actual_departure >= ${len(t5r_params)-1}"
        f" AND br4.origin_actual_departure < (${len(t5r_params)}::date + 1)"
    )
    top5_rev_task = pool.fetch(
        f"""
        WITH by_cust AS (
          SELECT
            TRIM(br4.customer_name) AS customer,
            COALESCE(SUM(br4.total_charge), 0)::numeric AS revenue,
            COALESCE(SUM(br4.margin_amt), 0)::numeric   AS profit
          FROM public.mcleod_gld_budget_report_v4 br4
          WHERE {t5r_scope} AND {t5r_df}
            AND br4.customer_name IS NOT NULL
          GROUP BY TRIM(br4.customer_name)
        )
        SELECT
          customer, revenue, profit,
          ROW_NUMBER() OVER (ORDER BY revenue DESC NULLS LAST) AS rn,
          SUM(revenue) OVER () AS total_metric
        FROM by_cust
        ORDER BY rn
        """,
        *t5r_params,
    )

    t5p_params: list = []
    t5p_scope = _scope_where("br4", team, customer, t5p_params, division=division)
    t5p_params.extend([YEAR_START, YEAR_END])
    t5p_df = (
        f"br4.origin_actual_departure >= ${len(t5p_params)-1}"
        f" AND br4.origin_actual_departure < (${len(t5p_params)}::date + 1)"
    )
    top5_prof_task = pool.fetch(
        f"""
        WITH by_cust AS (
          SELECT
            TRIM(br4.customer_name) AS customer,
            COALESCE(SUM(br4.total_charge), 0)::numeric AS revenue,
            COALESCE(SUM(br4.margin_amt), 0)::numeric   AS profit
          FROM public.mcleod_gld_budget_report_v4 br4
          WHERE {t5p_scope} AND {t5p_df}
            AND br4.customer_name IS NOT NULL
          GROUP BY TRIM(br4.customer_name)
        )
        SELECT
          customer, revenue, profit,
          ROW_NUMBER() OVER (ORDER BY profit DESC NULLS LAST) AS rn,
          SUM(profit) OVER () AS total_metric
        FROM by_cust
        ORDER BY rn
        """,
        *t5p_params,
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

    def _split_top5(rows, metric_key):
        """Split ranked customers into the 5 named slices + an aggregated
        'Others' slice, and return the full remaining-customer list so the UI
        can expand 'Others'. conc_pct is each row's share of the metric total.
        """
        total = float(rows[0]["total_metric"] or 0) if rows else 0.0
        top: list = []
        others: list = []
        o_rev = o_prof = 0.0
        for r in rows:
            metric_val = float(r[metric_key] or 0)
            item = {
                "customer": r["customer"],
                "revenue": float(r["revenue"] or 0),
                "profit": float(r["profit"] or 0),
                "conc_pct": (metric_val / total * 100.0) if total else 0.0,
            }
            if r["rn"] <= 5:
                top.append(item)
            else:
                others.append(item)
                o_rev += item["revenue"]
                o_prof += item["profit"]
        slices = list(top)
        if others:
            o_metric = o_rev if metric_key == "revenue" else o_prof
            slices.append(
                {
                    "customer": "Others",
                    "revenue": o_rev,
                    "profit": o_prof,
                    "conc_pct": (o_metric / total * 100.0) if total else 0.0,
                }
            )
        return slices, others[:500]

    t5r_slices, t5r_others = _split_top5(t5r, "revenue")
    t5p_slices, t5p_others = _split_top5(t5p, "profit")

    return {
        "success": True,
        "data": {
            "by_customer": [_map_cust(r) for r in pc],
            "worst_by_customer": [_map_cust(r) for r in wp],
            "top5_revenue": t5r_slices,
            "top5_revenue_others": t5r_others,
            "top5_profit": t5p_slices,
            "top5_profit_others": t5p_others,
            "window": {"start": s.isoformat(), "end": e.isoformat()},
        },
    }


# ---------------------------------------------------------------------------
# Tab 4 — Weekly  (ALL panels GLOBAL)
# ---------------------------------------------------------------------------


@router.get("/weekly")
async def weekly(
    request: Request,
    division: Optional[str] = Query(None),
    team: Optional[str] = Query(None),
    customer: Optional[str] = Query(None),
    _user: dict = Depends(require_report_access("ceo-executive")),
):
    pool = get_datalake_gold_pool(request)
    today = cst_today()
    this_week_mon = _week_start(today)
    # Bruno R7 (2026-05-26): widened 10 → 20 weeks so the charts scroll back up
    # to 20 weeks (frontend shows ~8 at a time, scrolled to most recent).
    twenty_weeks_start = this_week_mon - timedelta(weeks=19)
    summary_start = today - timedelta(weeks=20)  # ~20 weeks for Summary by Week

    # Bruno R4 (2026-05-12): Weekly honors Team. R5 (2026-05-21): Customer
    # too. R7 (2026-05-26): windows widened to 20 weeks. Still date-immutable.
    weekly_params: list = []
    weekly_scope = _scope_where("br4", team, customer, weekly_params, division=division)
    weekly_params.extend([twenty_weeks_start, today])
    w_s, w_e = len(weekly_params) - 1, len(weekly_params)

    # Last 20 weeks — loads + revenue + profit + margin
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
        WHERE {weekly_scope}
          AND br4.origin_actual_departure::date >= ${w_s}
          AND br4.origin_actual_departure::date <= ${w_e}
        GROUP BY 1
        ORDER BY 1
        """,
        *weekly_params,
    )

    summary_params: list = []
    summary_scope = _scope_where("br4", team, customer, summary_params, division=division)
    summary_params.extend([summary_start, today])
    s_s, s_e = len(summary_params) - 1, len(summary_params)

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
        WHERE {summary_scope}
          AND br4.origin_actual_departure::date >= ${s_s}
          AND br4.origin_actual_departure::date <= ${s_e}
        GROUP BY 1
        ORDER BY 1 DESC
        """,
        *summary_params,
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
    _user: dict = Depends(require_report_access("ceo-executive")),
):
    pool = get_datalake_gold_pool(request)
    s, e = _resolve_range(range, start_date, end_date)

    # ---- Universe totals (Bruno 2026-06-03) -----------------------------
    # One shared totals row for all three Risk tables, computed over the
    # full negative-loads universe (status D/P via _scope_where +
    # margin_amt < 0). The row LIMITs below are payload caps, not the
    # totals' source — YTD already has 4k+ negative loads, so client-side
    # sums over capped rows would never reconcile.
    tt_params: list = []
    tt_where = _scope_where("br4", team, customer, tt_params, division=division)
    tt_params.extend([s, e])
    tt_df = (
        f"br4.origin_actual_departure >= ${len(tt_params)-1}"
        f" AND br4.origin_actual_departure < (${len(tt_params)}::date + 1)"
    )
    tt_task = pool.fetchrow(
        f"""
        SELECT
          COUNT(*) AS loads,
          COALESCE(SUM(br4.total_charge), 0)::numeric AS revenue,
          COALESCE(SUM(br4.margin_amt), 0)::numeric AS profit
        FROM public.mcleod_gld_budget_report_v4 br4
        WHERE {tt_where} AND {tt_df}
          AND br4.margin_amt < 0
        """,
        *tt_params,
    )

    # ---- Worst Margins by Lanes ----------------------------------------
    # Date filter is half-open `>= s AND < e+1` so Postgres can use the btree
    # on origin_actual_departure (idx_v4_dep). Wrapping the column in `::date`
    # was killing sargability and forcing a full seq-scan of v4 (380 MB).
    #
    # Bruno 2026-06-03: all three Risk tables share ONE universe — status D/P
    # (already in _scope_where) + per-row margin_amt < 0 — so their totals
    # reconcile. Previously this table filtered at the LANE level
    # (HAVING SUM(margin_amt) < 0), blending positive loads into net-negative
    # lanes and dropping negative loads in net-positive lanes (647 vs 687).
    # Loads are plain COUNT(*) (zero-charge accessorial rows count too, same
    # as the by-Order listing) and LIMITs are generous caps, not page sizes.
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
          COUNT(*) AS loads,
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
          AND br4.margin_amt < 0
        GROUP BY TRIM(br4.customer_name), TRIM(br4.origin_name), TRIM(br4.dest_name)
        ORDER BY profit ASC NULLS LAST
        LIMIT 2000
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
          CASE WHEN TRIM(br4.team_id) = '{DFW_TEAM_ID}' THEN TRIM(br4.team)
               ELSE TRIM(br4.team_id) END AS team,
          COALESCE(TRIM(br4.contract_type_descr), '') AS contract_type,
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
        LIMIT 5000
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
          COUNT(*) AS loads,
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
        LIMIT 1000
        """,
        *nc_params,
    )

    tt, wm, no, nc = await asyncio.gather(tt_task, wm_task, no_task, nc_task)

    tot_revenue = float(tt["revenue"] or 0)
    tot_profit = float(tt["profit"] or 0)

    return {
        "success": True,
        "data": {
            "totals": {
                "loads": int(tt["loads"] or 0),
                "revenue": tot_revenue,
                "profit": tot_profit,
                "margin_pct": (tot_profit / tot_revenue * 100.0) if tot_revenue > 0 else 0.0,
            },
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
                    "team": r["team"],
                    "contract_type": r["contract_type"],
                    "customer": r["customer"],
                    "carrier": r["carrier"],
                    "origin": r["origin"],
                    "destination": r["destination"],
                    "departure": r["departure"].isoformat() if r["departure"] else None,
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
    page: int = Query(1, ge=1),
    page_size: int = Query(100, ge=1, le=500),
    _user: dict = Depends(require_report_access("ceo-executive")),
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
    # Bruno R7 (2026-05-26): server-side pagination. The COUNT() reuses the
    # same scope/date predicate so "Page X of Y" reflects the full result set,
    # not just the fetched page. Departure-DESC keeps the stable page order.
    ao_params: list = []
    ao_where = _scope_where("br4", team, customer, ao_params, division=division)
    ao_params.extend([s, e])
    ao_df = (
        f"br4.origin_actual_departure >= ${len(ao_params)-1}"
        f" AND br4.origin_actual_departure < (${len(ao_params)}::date + 1)"
    )
    ao_count_task = pool.fetchval(
        f"""
        SELECT COUNT(*)
        FROM public.mcleod_gld_budget_report_v4 br4
        WHERE {ao_where} AND {ao_df}
        """,
        *ao_params,
    )
    # Page params follow the scope/date params positionally.
    ao_params.append(page_size)
    p_limit = len(ao_params)
    ao_params.append((page - 1) * page_size)
    p_offset = len(ao_params)
    ao_task = pool.fetch(
        f"""
        SELECT
          CASE WHEN TRIM(br4.team_id) = '{DFW_TEAM_ID}' THEN TRIM(br4.team)
               ELSE TRIM(br4.team_id) END AS team,
          COALESCE(TRIM(br4.contract_type_descr), '') AS contract_type,
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
        LIMIT ${p_limit} OFFSET ${p_offset}
        """,
        *ao_params,
    )

    lpa, ao, ao_total = await asyncio.gather(lpa_task, ao_task, ao_count_task)

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
                    "contract_type": r["contract_type"],
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
            "all_orders_total": int(ao_total or 0),
            "page": page,
            "page_size": page_size,
            "window": {"start": s.isoformat(), "end": e.isoformat()},
        },
    }
