"""Code-made report: OPs Customer Score.

Portal-native replacement for Bruno's "Customer Scorecard" Qlik app
``de4c1a28-5e6a-465d-a351-59f99950a5d4`` (PDF: ``BRUNO -- Customer Scorecard``).

Source: ``aivn_datalake_gold.public.mcleod_gld_scorecard_incidents_portal`` —
a portal-owned, INCIDENT-grain table built by n8n (poll-on-change, 15 min):
scoped scorecard order rows (denominator + dates + carrier) LEFT JOINed on the
full key (id, company_id, movement_id) to ALL rows of ``mcleod_gld_incidents_v3``.

Why not read ``mcleod_gld_scorecard`` directly (the old source): its PK is
(id, company_id, movement_id) with NO stop_type, so the Spark upsert keeps only
ONE incident per movement — a load with both a Pickup and a Delivery service
fail loses one, and which one survives flips every load (Bruno 2026-06-15 PDF:
"sometimes the data does not show in pickup or Delivery after refresh"). The
incidents source keeps every incident as its own row, so both survive. A
no-incident order is one base row with NULL incident columns (counts in the
on-time denominator, never a fail).

Scope (verbatim from Bruno's PDF base SQL):
- ``team_id``    IN (TEAM1..TEAM5, TEAM-DFW)
- ``company_id`` IN (TMS, TMS3)
- ``status``     IN (D, P)

Layout (4 tabs, single sticky filter bar):

| Tab            | Date column applied to filtered charts | "Pinned" charts (ignore date filter) |
|----------------|----------------------------------------|---------------------------------------|
| PU Overview    | ``orig_actual_departure``              | This-Month/Quarter/Year + Rolling 12m + Rolling 10w |
| DEL Overview   | ``dest_actual_departure``              | (same, but DEL)                        |
| PU Detail      | ``orig_actual_departure``              | —                                      |
| DEL Detail     | ``dest_actual_departure``              | —                                      |

Service-fail / fault classification (codes verbatim from PDF; the '' stop-type
from the PDF's movement-grain SQL is dropped — incidents carry a real stop_type):
- PU "Our Fault"      = stop_type IN ('PU','SH') AND edi_standard_code IN (T4,T3,D1,D2,BO,BE,AL,AI,AH,AF,A5,A2)
- PU "Not Our Fault"  = stop_type IN ('PU','SH') AND edi_standard_code IN (AD,AJ,AO,BQ,BT,C6,P2,S4,U2,U4) AND orig_stop_type='PU'
- DEL "Our Fault"     = stop_type IN ('CO','SO') AND edi_standard_code IN (AL,D2,AZ,AH,BE,D1,A5,AI,AF,A2,A1,AU,U3)
- DEL "Not Our Fault" = stop_type IN ('CO','SO') AND edi_standard_code IN
                        (C6,U4,U2,T7,P2,CA,RC,F1,BT,BQ,BJ,BH,BD,BC,BB,B8,B4,
                         AX,AS,AR,AQ,AO,AN,AM,AJ,AG,AD,A6,A3)
                        (Bruno's PDF says 'SPO' here — confirmed typo for 'SO'.)

Performance notes (proceed-with-all suggestions):
1. Single materialised base CTE per request — overview endpoints batch
   KPI + 3 tables in one query so we hit the DB once instead of four.
2. 10-min in-process TTL cache on ``/pu/pinned`` and ``/del/pinned``
   keyed by (today, division, customer, carrier, company, sub_teams).
   Pinned panels ignore the user's date filter so changing dates does
   not invalidate the cache.
3. Sargability — never ``TRIM()`` ``team_id``/``company_id``/``status``/
   ``stop_type``/``edi_standard_code`` in WHERE/JOIN. Use
   ``_pad_variants(values, width=col_width)`` per CLAUDE.md.
4. ``is_edi_servicefail`` flag was audited against Bruno's hand-rolled
   PU code list on a 90-day window and disagreed by ~1.6k rows
   (flag is broader, mixing PU+DEL). Stuck with explicit code lists.
5. Detail tables (Our Fault / Not Our Fault) paginated 200/page.
6. Filter dropdowns cached client-side 5 min via React Query.
"""

from __future__ import annotations

import asyncio
import time
from datetime import date, datetime, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, Query, Request

from app.clock import cst_today
from app.datalake import pad_variants as _pad_variants
from app.routers.deps import get_datalake_gold_pool, require_report_access

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

YEAR_START = date(2026, 1, 1)
YEAR_END = date(2026, 12, 31)

CORP_TEAMS = ("TEAM1", "TEAM2", "TEAM3", "TEAM4", "TEAM5")
DFW_TEAM = "TEAM-DFW"
ALL_TEAMS = (*CORP_TEAMS, DFW_TEAM)
DFW_SUB_TEAMS = ("TM1", "TM2", "TM3", "TM4")
ALL_COMPANIES = ("TMS", "TMS3")
OPEN_STATUSES = ("D", "P")

# Stop-type buckets. Source is now mcleod_gld_incidents_v3 (one row per real
# incident), so every incident carries an explicit stop_type — the empty-string
# bucket (a movement-grain scorecard artefact) is gone. A no-incident base row
# has stop_type NULL and so never satisfies _service_fail_predicate.
PU_STOP_TYPES = ("PU", "SH")
DEL_STOP_TYPES = ("CO", "SO")

# EDI code buckets (verbatim from PDF — see module doc)
PU_FAIL_CODES = (
    "T4", "T3", "D1", "D2", "BO", "BE", "AL", "AI", "AH", "AF", "A5", "A2",
)
PU_NOT_FAULT_CODES = (
    "AD", "AJ", "AO", "BQ", "BT", "C6", "P2", "S4", "U2", "U4",
)
DEL_FAIL_CODES = (
    "AL", "D2", "AZ", "AH", "BE", "D1", "A5", "AI", "AF", "A2", "A1", "AU", "U3",
)
DEL_NOT_FAULT_CODES = (
    "C6", "U4", "U2", "T7", "P2", "CA", "RC", "F1", "BT", "BQ", "BJ", "BH",
    "BD", "BC", "BB", "B8", "B4", "AX", "AS", "AR", "AQ", "AO", "AN", "AM",
    "AJ", "AG", "AD", "A6", "A3",
)

# Pre-padded code lists (varchar(40) on edi_standard_code).
_PU_FAIL_PAD = _pad_variants(PU_FAIL_CODES, width=40)
_PU_NOT_PAD = _pad_variants(PU_NOT_FAULT_CODES, width=40)
_DEL_FAIL_PAD = _pad_variants(DEL_FAIL_CODES, width=40)
_DEL_NOT_PAD = _pad_variants(DEL_NOT_FAULT_CODES, width=40)
_PU_STOP_PAD = _pad_variants(PU_STOP_TYPES, width=2)
_DEL_STOP_PAD = _pad_variants(DEL_STOP_TYPES, width=2)
_PU_ORIG_STOP_PAD = _pad_variants(("PU",), width=2)


router = APIRouter(tags=["ops-customer-score"], prefix="/custom/ops-customer-score")


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
    today = cst_today()
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
    allowed_set = set(allowed)
    keep = [t for t in wanted if t in allowed_set]
    return keep or list(allowed)


def _resolve_division(division: Optional[str]) -> tuple[list[str], bool]:
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
    carrier: Optional[str],
    sub_teams: Optional[list[str]],
    params: list,
) -> str:
    """WHERE fragment for mcleod_gld_scorecard. Appends params, returns SQL."""
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
    ]
    if customer:
        params.append(customer)
        parts.append(f"{alias}.customer_name = ${len(params)}")
    if carrier:
        params.append(carrier)
        parts.append(f"{alias}.payee_name = ${len(params)}")
    if sub_teams:
        # team_dfw is varchar(512) — pad to common width.
        params.append(sub_teams)
        parts.append(f"TRIM({alias}.team_dfw) = ANY(${len(params)})")
    return " AND ".join(parts)


def _bind_scope_with_date(
    date_col: str,
    range_: Optional[str],
    start_date: Optional[date],
    end_date: Optional[date],
    division: Optional[str],
    teams_csv: Optional[str],
    companies_csv: Optional[str],
    sub_teams_csv: Optional[str],
    customer: Optional[str],
    carrier: Optional[str],
    params: list,
    alias: str = "sc",
) -> tuple[str, date, date, list[str], list[str], list[str] | None]:
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
        alias, team_list, company_list, customer, carrier, sub_team_list, params
    )
    params.extend([s, e])
    where_with_date = (
        f"{where} AND {alias}.{date_col}::date "
        f"BETWEEN ${len(params) - 1} AND ${len(params)}"
    )
    return where_with_date, s, e, team_list, company_list, sub_team_list


def _bind_scope_no_date(
    division: Optional[str],
    teams_csv: Optional[str],
    companies_csv: Optional[str],
    sub_teams_csv: Optional[str],
    customer: Optional[str],
    carrier: Optional[str],
    params: list,
    alias: str = "sc",
) -> tuple[str, list[str], list[str], list[str] | None]:
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
        alias, team_list, company_list, customer, carrier, sub_team_list, params
    )
    return where, team_list, company_list, sub_team_list


def _service_fail_predicate(
    alias: str,
    fail_codes_param_idx: int,
    stop_types_param_idx: int,
) -> str:
    """SQL predicate for "service fail" rows.

    True when stop_type ∈ given list AND edi_standard_code ∈ given fail list.
    Both columns are sargable (no TRIM in predicate).
    """
    return (
        f"({alias}.stop_type = ANY(${stop_types_param_idx}) "
        f"AND {alias}.edi_standard_code = ANY(${fail_codes_param_idx}))"
    )


# ---------------------------------------------------------------------------
# Filters
# ---------------------------------------------------------------------------


@router.get("/filters")
async def filters(
    request: Request,
    division: Optional[str] = Query(None),
    teams: Optional[str] = Query(None),
    companies: Optional[str] = Query(None),
    sub_teams: Optional[str] = Query(None),
    customer: Optional[str] = Query(None),
    carrier: Optional[str] = Query(None),
    _user: dict = Depends(require_report_access("ops-customer-score")),
):
    """Cascading filter options.

    Returns customer_name, payee_name (carrier), company_id options visible
    in the current scope (full year). Saves 3 round-trips on initial load.
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
        _parse_csv(sub_teams, DFW_SUB_TEAMS) if (is_dfw and sub_teams) else None
    )

    # Customers
    cust_params: list = []
    cust_where = _scope_where(
        "sc", team_list, company_list, None, carrier, sub_team_list, cust_params
    )
    cust_params.append(YEAR_START)
    cust_rows = await pool.fetch(
        f"""
        SELECT DISTINCT TRIM(sc.customer_name) AS customer_name
        FROM public.mcleod_gld_scorecard_incidents_portal sc
        WHERE {cust_where}
          AND sc.orig_actual_departure >= ${len(cust_params)}
          AND sc.customer_name IS NOT NULL
          AND TRIM(sc.customer_name) <> ''
        ORDER BY customer_name
        """,
        *cust_params,
    )
    customers = [r["customer_name"] for r in cust_rows if r["customer_name"]]

    # Carriers (payee_name) — narrow to selected customer
    carr_params: list = []
    carr_where = _scope_where(
        "sc", team_list, company_list, customer, None, sub_team_list, carr_params
    )
    carr_params.append(YEAR_START)
    carr_rows = await pool.fetch(
        f"""
        SELECT DISTINCT TRIM(sc.payee_name) AS payee_name
        FROM public.mcleod_gld_scorecard_incidents_portal sc
        WHERE {carr_where}
          AND sc.orig_actual_departure >= ${len(carr_params)}
          AND sc.payee_name IS NOT NULL
          AND TRIM(sc.payee_name) <> ''
        ORDER BY payee_name
        """,
        *carr_params,
    )
    carriers = [r["payee_name"] for r in carr_rows if r["payee_name"]]

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
            "carriers": carriers,
            "year_start": YEAR_START.isoformat(),
            "year_end": YEAR_END.isoformat(),
        },
    }


# ---------------------------------------------------------------------------
# Pinned panels — ignore date filter, applied filters: division/customer/
# carrier/company/sub_teams. Cached 10 min keyed by (today, scope-tuple).
# ---------------------------------------------------------------------------


_PINNED_TTL_S = 600.0  # 10 minutes
_pinned_cache: dict[tuple, tuple[float, dict]] = {}
_pinned_lock = asyncio.Lock()


def _pinned_cache_key(
    side: str,
    division: Optional[str],
    teams_csv: Optional[str],
    companies_csv: Optional[str],
    sub_teams_csv: Optional[str],
    customer: Optional[str],
    carrier: Optional[str],
) -> tuple:
    return (
        side,
        cst_today().isoformat(),
        (division or "All").upper(),
        teams_csv or "",
        companies_csv or "",
        sub_teams_csv or "",
        customer or "",
        carrier or "",
    )


async def _pinned_payload(pool, side: str, params_seed: list, where: str) -> dict:
    """Compute pinned payload (this-month/quarter/year + rolling 12m + 10w).

    ``side`` is "pu" or "del" — selects which date column / fail code list /
    stop_type list to use. ``params_seed`` already contains the scope params
    from ``_bind_scope_no_date``. ``where`` already references those params.
    """
    if side == "pu":
        date_col = "orig_actual_departure"
        fail_codes = _PU_FAIL_PAD
        stop_types = _PU_STOP_PAD
    else:
        date_col = "dest_actual_departure"
        fail_codes = _DEL_FAIL_PAD
        stop_types = _DEL_STOP_PAD

    today = cst_today()
    today_clamped = max(YEAR_START, min(YEAR_END, today))
    m_start, _m_end, _lm_start, _lm_end = _month_bounds(today)
    # Quarter-start: month at 1/4/7/10
    q_month = ((today.month - 1) // 3) * 3 + 1
    q_start = today.replace(month=q_month, day=1)
    y_start = today.replace(month=1, day=1)
    # Last 12 months — 1st-of-month 11 months back
    y, m = today.year, today.month - 11
    while m <= 0:
        y -= 1
        m += 12
    rolling_12m_start = date(y, m, 1)
    rolling_10w_start = today - timedelta(weeks=10)

    # asyncpg requires the param count passed in to MATCH the placeholder
    # count in the SQL exactly. Each query gets its own `params` list (cloned
    # from `params_seed` so the scope `where` placeholders stay valid) plus
    # only the extra args that query references. Order matters: append in
    # the same order as the placeholder indices below.

    # ---- KPI: needs fail_codes, stop_types, m_start, q_start, y_start, today
    p_kpi = list(params_seed)
    p_kpi.append(fail_codes)
    p_kpi_fail = len(p_kpi)
    p_kpi.append(stop_types)
    p_kpi_stop = len(p_kpi)
    p_kpi.append(m_start)
    p_kpi_m = len(p_kpi)
    p_kpi.append(q_start)
    p_kpi_q = len(p_kpi)
    p_kpi.append(y_start)
    p_kpi_y = len(p_kpi)
    p_kpi.append(today_clamped)
    p_kpi_today = len(p_kpi)
    fail_pred_kpi = _service_fail_predicate("sc", p_kpi_fail, p_kpi_stop)

    kpi_sql = f"""
    SELECT
      COUNT(DISTINCT sc.id) FILTER (
        WHERE sc.{date_col}::date BETWEEN ${p_kpi_m} AND ${p_kpi_today}
          AND sc.total_charge <> 0
      ) AS m_orders,
      COUNT(DISTINCT sc.id) FILTER (
        WHERE sc.{date_col}::date BETWEEN ${p_kpi_m} AND ${p_kpi_today}
          AND {fail_pred_kpi}
      ) AS m_fail,
      COUNT(DISTINCT sc.id) FILTER (
        WHERE sc.{date_col}::date BETWEEN ${p_kpi_q} AND ${p_kpi_today}
          AND sc.total_charge <> 0
      ) AS q_orders,
      COUNT(DISTINCT sc.id) FILTER (
        WHERE sc.{date_col}::date BETWEEN ${p_kpi_q} AND ${p_kpi_today}
          AND {fail_pred_kpi}
      ) AS q_fail,
      COUNT(DISTINCT sc.id) FILTER (
        WHERE sc.{date_col}::date BETWEEN ${p_kpi_y} AND ${p_kpi_today}
          AND sc.total_charge <> 0
      ) AS y_orders,
      COUNT(DISTINCT sc.id) FILTER (
        WHERE sc.{date_col}::date BETWEEN ${p_kpi_y} AND ${p_kpi_today}
          AND {fail_pred_kpi}
      ) AS y_fail
    FROM public.mcleod_gld_scorecard_incidents_portal sc
    WHERE {where}
      AND sc.{date_col}::date BETWEEN ${p_kpi_y} AND ${p_kpi_today}
    """

    # ---- Rolling 12 months: fail_codes, stop_types, 12m_start, today
    p_12m = list(params_seed)
    p_12m.append(fail_codes)
    p_12m_fail = len(p_12m)
    p_12m.append(stop_types)
    p_12m_stop = len(p_12m)
    p_12m.append(rolling_12m_start)
    p_12m_start_idx = len(p_12m)
    p_12m.append(today_clamped)
    p_12m_today = len(p_12m)
    fail_pred_12m = _service_fail_predicate("sc", p_12m_fail, p_12m_stop)

    rolling_12m_sql = f"""
    SELECT
      DATE_TRUNC('month', sc.{date_col})::date AS bucket,
      COUNT(DISTINCT sc.id) FILTER (WHERE sc.total_charge <> 0) AS orders,
      COUNT(DISTINCT sc.id) FILTER (WHERE {fail_pred_12m}) AS fail
    FROM public.mcleod_gld_scorecard_incidents_portal sc
    WHERE {where}
      AND sc.{date_col}::date BETWEEN ${p_12m_start_idx} AND ${p_12m_today}
    GROUP BY DATE_TRUNC('month', sc.{date_col})
    ORDER BY bucket
    """

    # ---- Rolling 10 weeks: fail_codes, stop_types, 10w_start, today
    p_10w = list(params_seed)
    p_10w.append(fail_codes)
    p_10w_fail = len(p_10w)
    p_10w.append(stop_types)
    p_10w_stop = len(p_10w)
    p_10w.append(rolling_10w_start)
    p_10w_start_idx = len(p_10w)
    p_10w.append(today_clamped)
    p_10w_today = len(p_10w)
    fail_pred_10w = _service_fail_predicate("sc", p_10w_fail, p_10w_stop)

    rolling_10w_sql = f"""
    SELECT
      DATE_TRUNC('week', sc.{date_col})::date AS bucket,
      EXTRACT(ISOYEAR FROM sc.{date_col})::int AS iso_year,
      EXTRACT(WEEK    FROM sc.{date_col})::int AS iso_week,
      COUNT(DISTINCT sc.id) FILTER (WHERE sc.total_charge <> 0) AS orders,
      COUNT(DISTINCT sc.id) FILTER (WHERE {fail_pred_10w}) AS fail
    FROM public.mcleod_gld_scorecard_incidents_portal sc
    WHERE {where}
      AND sc.{date_col}::date BETWEEN ${p_10w_start_idx} AND ${p_10w_today}
    GROUP BY 1, 2, 3
    ORDER BY bucket
    """

    kpi_row, r12m, r10w = await asyncio.gather(
        pool.fetchrow(kpi_sql, *p_kpi),
        pool.fetch(rolling_12m_sql, *p_12m),
        pool.fetch(rolling_10w_sql, *p_10w),
    )

    def pct_on_time(orders: int, fail: int) -> Optional[float]:
        if not orders:
            return None
        return (1.0 - (float(fail) / float(orders))) * 100.0

    def kpi(orders, fail) -> dict:
        o = int(orders or 0)
        f = int(fail or 0)
        return {"orders": o, "fail": f, "pct_on_time": pct_on_time(o, f)}

    return {
        "kpi_month": kpi(kpi_row["m_orders"], kpi_row["m_fail"]),
        "kpi_quarter": kpi(kpi_row["q_orders"], kpi_row["q_fail"]),
        "kpi_year": kpi(kpi_row["y_orders"], kpi_row["y_fail"]),
        "rolling_12m": [
            {
                "bucket": r["bucket"].isoformat() if r["bucket"] else None,
                "orders": int(r["orders"] or 0),
                "fail": int(r["fail"] or 0),
                "pct_on_time": pct_on_time(r["orders"], r["fail"]),
            }
            for r in r12m
        ],
        "rolling_10w": [
            {
                "bucket": r["bucket"].isoformat() if r["bucket"] else None,
                "iso_year": int(r["iso_year"]),
                "iso_week": int(r["iso_week"]),
                "label": f"{int(r['iso_week']):02d} - {int(r['iso_year']) % 100:02d}",
                "orders": int(r["orders"] or 0),
                "fail": int(r["fail"] or 0),
                "pct_on_time": pct_on_time(r["orders"], r["fail"]),
            }
            for r in r10w
        ],
        "windows": {
            "month_start": m_start.isoformat(),
            "quarter_start": q_start.isoformat(),
            "year_start": y_start.isoformat(),
            "today": today_clamped.isoformat(),
            "rolling_12m_start": rolling_12m_start.isoformat(),
            "rolling_10w_start": rolling_10w_start.isoformat(),
        },
    }


async def _get_pinned(
    request: Request,
    side: str,
    division: Optional[str],
    teams: Optional[str],
    companies: Optional[str],
    sub_teams: Optional[str],
    customer: Optional[str],
    carrier: Optional[str],
) -> dict:
    cache_key = _pinned_cache_key(
        side, division, teams, companies, sub_teams, customer, carrier
    )
    now_ts = time.monotonic()
    cached = _pinned_cache.get(cache_key)
    if cached and (now_ts - cached[0]) < _PINNED_TTL_S:
        return {**cached[1], "_cached": True}

    async with _pinned_lock:
        cached = _pinned_cache.get(cache_key)
        if cached and (now_ts - cached[0]) < _PINNED_TTL_S:
            return {**cached[1], "_cached": True}

        pool = get_datalake_gold_pool(request)
        params: list = []
        where, team_list, company_list, sub_team_list = _bind_scope_no_date(
            division, teams, companies, sub_teams, customer, carrier, params
        )
        payload = await _pinned_payload(pool, side, params, where)
        _pinned_cache[cache_key] = (now_ts, payload)
        # Drop other-day keys so the cache cannot grow unbounded.
        today_iso = cst_today().isoformat()
        for k in list(_pinned_cache.keys()):
            if k[1] != today_iso:
                _pinned_cache.pop(k, None)
        return {**payload, "_cached": False}


@router.get("/pu/pinned")
async def pu_pinned(
    request: Request,
    division: Optional[str] = Query(None),
    teams: Optional[str] = Query(None),
    companies: Optional[str] = Query(None),
    sub_teams: Optional[str] = Query(None),
    customer: Optional[str] = Query(None),
    carrier: Optional[str] = Query(None),
    _user: dict = Depends(require_report_access("ops-customer-score")),
):
    payload = await _get_pinned(
        request, "pu", division, teams, companies, sub_teams, customer, carrier
    )
    cached = payload.pop("_cached", False)
    return {"success": True, "data": payload, "meta": {"cached": cached}}


@router.get("/del/pinned")
async def del_pinned(
    request: Request,
    division: Optional[str] = Query(None),
    teams: Optional[str] = Query(None),
    companies: Optional[str] = Query(None),
    sub_teams: Optional[str] = Query(None),
    customer: Optional[str] = Query(None),
    carrier: Optional[str] = Query(None),
    _user: dict = Depends(require_report_access("ops-customer-score")),
):
    payload = await _get_pinned(
        request, "del", division, teams, companies, sub_teams, customer, carrier
    )
    cached = payload.pop("_cached", False)
    return {"success": True, "data": payload, "meta": {"cached": cached}}


# ---------------------------------------------------------------------------
# Overview endpoints — filtered by date.
# Bundles: total Service-Fail KPI + by_team + by_customer + by_delay
# ---------------------------------------------------------------------------


async def _overview(
    request: Request,
    side: str,
    range_: Optional[str],
    start_date: Optional[date],
    end_date: Optional[date],
    division: Optional[str],
    teams: Optional[str],
    companies: Optional[str],
    sub_teams: Optional[str],
    customer: Optional[str],
    carrier: Optional[str],
):
    pool = get_datalake_gold_pool(request)
    if side == "pu":
        date_col = "orig_actual_departure"
        fail_codes = _PU_FAIL_PAD
        stop_types = _PU_STOP_PAD
    else:
        date_col = "dest_actual_departure"
        fail_codes = _DEL_FAIL_PAD
        stop_types = _DEL_STOP_PAD

    params: list = []
    where, s, e, team_list, company_list, sub_team_list = _bind_scope_with_date(
        date_col, range_, start_date, end_date, division, teams, companies,
        sub_teams, customer, carrier, params,
    )
    params.append(fail_codes)
    p_fail = len(params)
    params.append(stop_types)
    p_stop = len(params)
    fail_pred = _service_fail_predicate("sc", p_fail, p_stop)

    # KPI + base totals
    kpi_sql = f"""
    SELECT
      COUNT(DISTINCT sc.id) FILTER (WHERE sc.total_charge <> 0) AS orders,
      COUNT(DISTINCT sc.id) FILTER (WHERE {fail_pred}) AS fail
    FROM public.mcleod_gld_scorecard_incidents_portal sc
    WHERE {where}
    """

    by_team_sql = f"""
    SELECT
      TRIM(sc.team_id) AS team_id,
      COUNT(DISTINCT sc.id) FILTER (WHERE sc.total_charge <> 0) AS orders,
      COUNT(DISTINCT sc.id) FILTER (WHERE {fail_pred}) AS fail
    FROM public.mcleod_gld_scorecard_incidents_portal sc
    WHERE {where}
    GROUP BY TRIM(sc.team_id)
    ORDER BY fail DESC NULLS LAST, team_id
    """

    by_customer_sql = f"""
    SELECT
      TRIM(sc.customer_name) AS customer_name,
      COUNT(DISTINCT sc.id) FILTER (WHERE sc.total_charge <> 0) AS orders,
      COUNT(DISTINCT sc.id) FILTER (WHERE {fail_pred}) AS fail
    FROM public.mcleod_gld_scorecard_incidents_portal sc
    WHERE {where}
      AND sc.customer_name IS NOT NULL
      AND TRIM(sc.customer_name) <> ''
    GROUP BY TRIM(sc.customer_name)
    HAVING COUNT(DISTINCT sc.id) FILTER (WHERE sc.total_charge <> 0) > 0
    ORDER BY fail DESC NULLS LAST, orders DESC
    LIMIT 100
    """

    # Delay code bar chart — only the Service-Fail rows, grouped by code.
    by_delay_sql = f"""
    SELECT
      TRIM(sc.edi_standard_code) AS edi_standard_code,
      COUNT(DISTINCT sc.id) AS fail
    FROM public.mcleod_gld_scorecard_incidents_portal sc
    WHERE {where}
      AND {fail_pred}
    GROUP BY TRIM(sc.edi_standard_code)
    ORDER BY fail DESC NULLS LAST
    """

    kpi_row, by_team, by_customer, by_delay = await asyncio.gather(
        pool.fetchrow(kpi_sql, *params),
        pool.fetch(by_team_sql, *params),
        pool.fetch(by_customer_sql, *params),
        pool.fetch(by_delay_sql, *params),
    )

    def on_time(o, f):
        if not o:
            return None
        return (1.0 - (float(f) / float(o))) * 100.0

    return {
        "success": True,
        "data": {
            "kpi": {
                "orders": int(kpi_row["orders"] or 0),
                "fail": int(kpi_row["fail"] or 0),
                "pct_on_time": on_time(kpi_row["orders"], kpi_row["fail"]),
            },
            "by_team": [
                {
                    "team_id": r["team_id"],
                    "orders": int(r["orders"] or 0),
                    "fail": int(r["fail"] or 0),
                    "pct_on_time": on_time(r["orders"], r["fail"]),
                }
                for r in by_team
            ],
            "by_customer": [
                {
                    "customer_name": r["customer_name"],
                    "orders": int(r["orders"] or 0),
                    "fail": int(r["fail"] or 0),
                    "pct_on_time": on_time(r["orders"], r["fail"]),
                }
                for r in by_customer
            ],
            "by_delay": [
                {
                    "edi_standard_code": r["edi_standard_code"],
                    "fail": int(r["fail"] or 0),
                }
                for r in by_delay
            ],
            "window": {"start": s.isoformat(), "end": e.isoformat()},
            "teams_applied": team_list,
            "companies_applied": company_list,
            "sub_teams_applied": sub_team_list,
        },
    }


@router.get("/pu/overview")
async def pu_overview(
    request: Request,
    range: Optional[str] = Query("mtd"),
    start_date: Optional[date] = Query(None),
    end_date: Optional[date] = Query(None),
    division: Optional[str] = Query(None),
    teams: Optional[str] = Query(None),
    companies: Optional[str] = Query(None),
    sub_teams: Optional[str] = Query(None),
    customer: Optional[str] = Query(None),
    carrier: Optional[str] = Query(None),
    _user: dict = Depends(require_report_access("ops-customer-score")),
):
    return await _overview(
        request, "pu", range, start_date, end_date, division, teams, companies,
        sub_teams, customer, carrier,
    )


@router.get("/del/overview")
async def del_overview(
    request: Request,
    range: Optional[str] = Query("mtd"),
    start_date: Optional[date] = Query(None),
    end_date: Optional[date] = Query(None),
    division: Optional[str] = Query(None),
    teams: Optional[str] = Query(None),
    companies: Optional[str] = Query(None),
    sub_teams: Optional[str] = Query(None),
    customer: Optional[str] = Query(None),
    carrier: Optional[str] = Query(None),
    _user: dict = Depends(require_report_access("ops-customer-score")),
):
    return await _overview(
        request, "del", range, start_date, end_date, division, teams, companies,
        sub_teams, customer, carrier,
    )


# ---------------------------------------------------------------------------
# Detail endpoints — Summary by Customer + Summary by Lane + Our-Fault and
# Not-Our-Fault summary KPIs in one DB round-trip.
# ---------------------------------------------------------------------------


async def _detail(
    request: Request,
    side: str,
    range_: Optional[str],
    start_date: Optional[date],
    end_date: Optional[date],
    division: Optional[str],
    teams: Optional[str],
    companies: Optional[str],
    sub_teams: Optional[str],
    customer: Optional[str],
    carrier: Optional[str],
):
    pool = get_datalake_gold_pool(request)
    if side == "pu":
        date_col = "orig_actual_departure"
        fail_codes = _PU_FAIL_PAD
        not_codes = _PU_NOT_PAD
        stop_types = _PU_STOP_PAD
    else:
        date_col = "dest_actual_departure"
        fail_codes = _DEL_FAIL_PAD
        not_codes = _DEL_NOT_PAD
        stop_types = _DEL_STOP_PAD

    # Scope params shared by every query.
    base_params: list = []
    where, s, e, team_list, company_list, sub_team_list = _bind_scope_with_date(
        date_col, range_, start_date, end_date, division, teams, companies,
        sub_teams, customer, carrier, base_params,
    )

    # KPI references BOTH fail-codes AND not-codes; by_customer/by_lane only
    # reference fail-codes. Postgres rejects unreferenced positional params
    # ("could not determine data type of parameter $N"), so each query gets
    # its own params list.

    # ---- KPI: scope + fail_codes + not_codes + stop_types
    p_kpi = list(base_params)
    p_kpi.append(fail_codes)
    p_kpi_fail = len(p_kpi)
    p_kpi.append(not_codes)
    p_kpi_not = len(p_kpi)
    p_kpi.append(stop_types)
    p_kpi_stop = len(p_kpi)
    fail_pred_kpi = _service_fail_predicate("sc", p_kpi_fail, p_kpi_stop)
    not_pred_kpi = _service_fail_predicate("sc", p_kpi_not, p_kpi_stop)

    kpi_sql = f"""
    SELECT
      COUNT(DISTINCT sc.id) FILTER (WHERE sc.total_charge <> 0) AS orders,
      COUNT(DISTINCT sc.id) FILTER (WHERE {fail_pred_kpi}) AS fail,
      COUNT(DISTINCT sc.id) FILTER (WHERE {not_pred_kpi}) AS not_fault_fail
    FROM public.mcleod_gld_scorecard_incidents_portal sc
    WHERE {where}
    """

    # ---- by_customer / by_lane: scope + fail_codes + stop_types
    p_simple = list(base_params)
    p_simple.append(fail_codes)
    p_simple_fail = len(p_simple)
    p_simple.append(stop_types)
    p_simple_stop = len(p_simple)
    fail_pred_simple = _service_fail_predicate("sc", p_simple_fail, p_simple_stop)

    by_customer_sql = f"""
    SELECT
      TRIM(sc.customer_name) AS customer_name,
      COUNT(DISTINCT sc.id) FILTER (WHERE sc.total_charge <> 0) AS orders,
      COUNT(DISTINCT sc.id) FILTER (WHERE {fail_pred_simple}) AS fail
    FROM public.mcleod_gld_scorecard_incidents_portal sc
    WHERE {where}
      AND sc.customer_name IS NOT NULL
      AND TRIM(sc.customer_name) <> ''
    GROUP BY TRIM(sc.customer_name)
    HAVING COUNT(DISTINCT sc.id) FILTER (WHERE sc.total_charge <> 0) > 0
    ORDER BY orders DESC
    LIMIT 200
    """

    by_lane_sql = f"""
    SELECT
      TRIM(sc.customer_name) AS customer_name,
      TRIM(sc.orig_city_name) || ', ' || TRIM(sc.orig_state) AS origin,
      TRIM(sc.dest_city_name) || ', ' || TRIM(sc.dest_state) AS destination,
      COUNT(DISTINCT sc.id) FILTER (WHERE sc.total_charge <> 0) AS orders,
      COUNT(DISTINCT sc.id) FILTER (WHERE {fail_pred_simple}) AS fail
    FROM public.mcleod_gld_scorecard_incidents_portal sc
    WHERE {where}
      AND sc.customer_name IS NOT NULL
      AND TRIM(sc.customer_name) <> ''
      AND sc.orig_city_name IS NOT NULL
      AND sc.dest_city_name IS NOT NULL
    GROUP BY 1, 2, 3
    HAVING COUNT(DISTINCT sc.id) FILTER (WHERE sc.total_charge <> 0) > 0
    ORDER BY orders DESC
    LIMIT 500
    """

    kpi_row, by_customer, by_lane = await asyncio.gather(
        pool.fetchrow(kpi_sql, *p_kpi),
        pool.fetch(by_customer_sql, *p_simple),
        pool.fetch(by_lane_sql, *p_simple),
    )

    def on_time(o, f):
        if not o:
            return None
        return (1.0 - (float(f) / float(o))) * 100.0

    orders = int(kpi_row["orders"] or 0)
    fail = int(kpi_row["fail"] or 0)
    not_fault = int(kpi_row["not_fault_fail"] or 0)
    return {
        "success": True,
        "data": {
            "kpi": {
                "orders": orders,
                "fail": fail,
                "pct_on_time": on_time(orders, fail),
            },
            "our_fault_kpi": {
                "fail": fail,
                "pct_on_time": on_time(orders, fail),
            },
            "not_fault_kpi": {
                "fail": not_fault,
                "pct_on_time": on_time(orders, not_fault),
            },
            "by_customer": [
                {
                    "customer_name": r["customer_name"],
                    "orders": int(r["orders"] or 0),
                    "fail": int(r["fail"] or 0),
                    "pct_on_time": on_time(r["orders"], r["fail"]),
                }
                for r in by_customer
            ],
            "by_lane": [
                {
                    "customer_name": r["customer_name"],
                    "origin": r["origin"],
                    "destination": r["destination"],
                    "orders": int(r["orders"] or 0),
                    "fail": int(r["fail"] or 0),
                    "pct_on_time": on_time(r["orders"], r["fail"]),
                }
                for r in by_lane
            ],
            "window": {"start": s.isoformat(), "end": e.isoformat()},
            "teams_applied": team_list,
            "companies_applied": company_list,
            "sub_teams_applied": sub_team_list,
        },
    }


@router.get("/pu/detail")
async def pu_detail(
    request: Request,
    range: Optional[str] = Query("mtd"),
    start_date: Optional[date] = Query(None),
    end_date: Optional[date] = Query(None),
    division: Optional[str] = Query(None),
    teams: Optional[str] = Query(None),
    companies: Optional[str] = Query(None),
    sub_teams: Optional[str] = Query(None),
    customer: Optional[str] = Query(None),
    carrier: Optional[str] = Query(None),
    _user: dict = Depends(require_report_access("ops-customer-score")),
):
    return await _detail(
        request, "pu", range, start_date, end_date, division, teams, companies,
        sub_teams, customer, carrier,
    )


@router.get("/del/detail")
async def del_detail(
    request: Request,
    range: Optional[str] = Query("mtd"),
    start_date: Optional[date] = Query(None),
    end_date: Optional[date] = Query(None),
    division: Optional[str] = Query(None),
    teams: Optional[str] = Query(None),
    companies: Optional[str] = Query(None),
    sub_teams: Optional[str] = Query(None),
    customer: Optional[str] = Query(None),
    carrier: Optional[str] = Query(None),
    _user: dict = Depends(require_report_access("ops-customer-score")),
):
    return await _detail(
        request, "del", range, start_date, end_date, division, teams, companies,
        sub_teams, customer, carrier,
    )


# ---------------------------------------------------------------------------
# Detail tables — Our Fault / Not Our Fault paginated rows
# ---------------------------------------------------------------------------


async def _fault_rows(
    request: Request,
    side: str,
    fault: str,  # "our" or "not"
    range_: Optional[str],
    start_date: Optional[date],
    end_date: Optional[date],
    division: Optional[str],
    teams: Optional[str],
    companies: Optional[str],
    sub_teams: Optional[str],
    customer: Optional[str],
    carrier: Optional[str],
    page: int,
    limit: int,
):
    pool = get_datalake_gold_pool(request)
    if side == "pu":
        date_col = "orig_actual_departure"
        codes = _PU_FAIL_PAD if fault == "our" else _PU_NOT_PAD
        stop_types = _PU_STOP_PAD
        arrival_col = "orig_actual_arrival"
        sched_late_col = "orig_sched_late"
    else:
        date_col = "dest_actual_departure"
        codes = _DEL_FAIL_PAD if fault == "our" else _DEL_NOT_PAD
        stop_types = _DEL_STOP_PAD
        arrival_col = "dest_actual_arrival"
        sched_late_col = "dest_sched_late"

    page = max(1, page)
    limit = max(1, min(500, limit))
    offset = (page - 1) * limit

    base_params: list = []
    where, s, e, _team_list, _company_list, _sub_team_list = _bind_scope_with_date(
        date_col, range_, start_date, end_date, division, teams, companies,
        sub_teams, customer, carrier, base_params,
    )
    base_params.append(codes)
    p_codes = len(base_params)
    base_params.append(stop_types)
    p_stop = len(base_params)
    extra_sql = ""
    if side == "pu" and fault == "not":
        base_params.append(_PU_ORIG_STOP_PAD)
        p_orig_stop = len(base_params)
        extra_sql = f"AND sc.orig_stop_type = ANY(${p_orig_stop})"

    fail_pred = _service_fail_predicate("sc", p_codes, p_stop)

    count_sql = f"""
    SELECT COUNT(*) AS n
    FROM public.mcleod_gld_scorecard_incidents_portal sc
    WHERE {where}
      AND sc.total_charge <> 0
      AND {fail_pred}
      {extra_sql}
    """

    rows_params = list(base_params)
    rows_params.extend([limit, offset])
    p_limit = len(rows_params) - 1
    p_offset = len(rows_params)
    rows_sql = f"""
    SELECT
      sc.id,
      TRIM(sc.team_id) AS team_id,
      TRIM(sc.team_dfw) AS team_dfw,
      TRIM(sc.customer_name) AS customer_name,
      sc.{arrival_col} AS actual_arrival,
      sc.{sched_late_col} AS sched_late,
      TRIM(sc.edi_standard_code) AS edi_standard_code,
      TRIM(sc.edi_code_descr) AS edi_code_descr,
      sc.dsp_comment,
      TRIM(sc.payee_name) AS payee_name,
      TRIM(sc.entered_user_id) AS entered_user_id
    FROM public.mcleod_gld_scorecard_incidents_portal sc
    WHERE {where}
      AND sc.total_charge <> 0
      AND {fail_pred}
      {extra_sql}
    ORDER BY sc.{date_col} DESC NULLS LAST, sc.id
    LIMIT ${p_limit} OFFSET ${p_offset}
    """

    total_row, rows = await asyncio.gather(
        pool.fetchrow(count_sql, *base_params),
        pool.fetch(rows_sql, *rows_params),
    )

    def iso(dt):
        return dt.isoformat() if isinstance(dt, datetime) else None

    return {
        "success": True,
        "data": [
            {
                "id": r["id"],
                "team_id": r["team_id"],
                "team_dfw": r["team_dfw"],
                "customer_name": r["customer_name"],
                "actual_arrival": iso(r["actual_arrival"]),
                "sched_late": iso(r["sched_late"]),
                "edi_standard_code": r["edi_standard_code"],
                "edi_code_descr": r["edi_code_descr"],
                "dsp_comment": r["dsp_comment"],
                "payee_name": r["payee_name"],
                "entered_user_id": r["entered_user_id"],
            }
            for r in rows
        ],
        "meta": {
            "total": int(total_row["n"] or 0),
            "page": page,
            "limit": limit,
            "window": {"start": s.isoformat(), "end": e.isoformat()},
        },
    }


@router.get("/pu/our-fault")
async def pu_our_fault(
    request: Request,
    range: Optional[str] = Query("mtd"),
    start_date: Optional[date] = Query(None),
    end_date: Optional[date] = Query(None),
    division: Optional[str] = Query(None),
    teams: Optional[str] = Query(None),
    companies: Optional[str] = Query(None),
    sub_teams: Optional[str] = Query(None),
    customer: Optional[str] = Query(None),
    carrier: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    limit: int = Query(200, ge=1, le=500),
    _user: dict = Depends(require_report_access("ops-customer-score")),
):
    return await _fault_rows(
        request, "pu", "our", range, start_date, end_date, division, teams,
        companies, sub_teams, customer, carrier, page, limit,
    )


@router.get("/pu/not-our-fault")
async def pu_not_our_fault(
    request: Request,
    range: Optional[str] = Query("mtd"),
    start_date: Optional[date] = Query(None),
    end_date: Optional[date] = Query(None),
    division: Optional[str] = Query(None),
    teams: Optional[str] = Query(None),
    companies: Optional[str] = Query(None),
    sub_teams: Optional[str] = Query(None),
    customer: Optional[str] = Query(None),
    carrier: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    limit: int = Query(200, ge=1, le=500),
    _user: dict = Depends(require_report_access("ops-customer-score")),
):
    return await _fault_rows(
        request, "pu", "not", range, start_date, end_date, division, teams,
        companies, sub_teams, customer, carrier, page, limit,
    )


@router.get("/del/our-fault")
async def del_our_fault(
    request: Request,
    range: Optional[str] = Query("mtd"),
    start_date: Optional[date] = Query(None),
    end_date: Optional[date] = Query(None),
    division: Optional[str] = Query(None),
    teams: Optional[str] = Query(None),
    companies: Optional[str] = Query(None),
    sub_teams: Optional[str] = Query(None),
    customer: Optional[str] = Query(None),
    carrier: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    limit: int = Query(200, ge=1, le=500),
    _user: dict = Depends(require_report_access("ops-customer-score")),
):
    return await _fault_rows(
        request, "del", "our", range, start_date, end_date, division, teams,
        companies, sub_teams, customer, carrier, page, limit,
    )


@router.get("/del/not-our-fault")
async def del_not_our_fault(
    request: Request,
    range: Optional[str] = Query("mtd"),
    start_date: Optional[date] = Query(None),
    end_date: Optional[date] = Query(None),
    division: Optional[str] = Query(None),
    teams: Optional[str] = Query(None),
    companies: Optional[str] = Query(None),
    sub_teams: Optional[str] = Query(None),
    customer: Optional[str] = Query(None),
    carrier: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    limit: int = Query(200, ge=1, le=500),
    _user: dict = Depends(require_report_access("ops-customer-score")),
):
    return await _fault_rows(
        request, "del", "not", range, start_date, end_date, division, teams,
        companies, sub_teams, customer, carrier, page, limit,
    )


# ---------------------------------------------------------------------------
# Freshness
# ---------------------------------------------------------------------------


@router.get("/freshness")
async def freshness(
    request: Request,
    _user: dict = Depends(require_report_access("ops-customer-score")),
):
    pool = get_datalake_gold_pool(request)
    row = await pool.fetchrow(
        """
        SELECT
          MAX(updated_dt)            AS last_updated,
          MAX(orig_actual_departure) AS last_pu,
          MAX(dest_actual_departure) AS last_del,
          COUNT(*)                   AS rows_in_scope
        FROM public.mcleod_gld_scorecard_incidents_portal
        WHERE team_id    = ANY($1)
          AND company_id = ANY($2)
          AND status     = ANY($3)
        """,
        _pad_variants(ALL_TEAMS, width=8),
        _pad_variants(ALL_COMPANIES, width=4),
        _pad_variants(OPEN_STATUSES, width=1),
    )
    return {
        "success": True,
        "data": {
            "last_updated": row["last_updated"].isoformat() if row["last_updated"] else None,
            "last_pu": row["last_pu"].isoformat() if row["last_pu"] else None,
            "last_del": row["last_del"].isoformat() if row["last_del"] else None,
            "rows_in_scope": int(row["rows_in_scope"] or 0),
        },
    }
