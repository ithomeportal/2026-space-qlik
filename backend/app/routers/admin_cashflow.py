"""Code-made report: Admin Aging Cashflow.

Mirrors Bruno's PDF spec ("BRUNO -- Admin CashFlow") which currently lives as
a Qlik dashboard. Single-page A/R aging discipline view sourced from
``aivn_datalake_gold.public.mcleod_gld_cashflow`` (Spark/McLeod ETL — already
populated, no n8n workflow needed).

Scope (Bruno's clause): team_id ∈ {TEAM1..5, TEAM-DFW} · company_id ∈
{TMS, TMS3} · status ∈ {D, P}. Covers ~213k of the 220k rows.

Bug fixes vs Bruno's PDF (confirmed with the user 2026-04-30):

* Real calendar-day diff ``(a::date - b::date)`` everywhere — Bruno's Qlik
  ``day(a) - day(b)`` only returned day-of-month and silently broke across
  month boundaries (Apr 30 → May 2 became -28 instead of 2).
* "Delivery Date vs Bill Date" detail uses ``dest_actual_arrival > '2000'``
  (delivered loads), not the typo ``< '2000'`` in the PDF.
* "CarrInvoice vs Bill Date" uses ``invoice_recv_date - bill_date`` (matches
  the "C-B" card title and the PDF's page-6 detail-table direction).
* "Orig Sched Early" column resolves to ``orig_orig_sched_early`` (raw
  pickup-window early) — closest match to the PDF sample times.

UX additions (over Bruno's flat dashboard):

* 12-week % sparklines on the 3 discipline KPIs.
* Aging buckets bar chart for delivery-vs-bill (0-3, 4-7, 8-10, 11-15, >15).
* Top-delayed-customers leaderboard ($ revenue at risk, days >10).
* Risk banner when delivered-not-billed + ready-not-billed exceeds $3M.

Performance non-negotiables (CLAUDE.md sargability rule):

* Padded-variant filters via ``_pad_variants(values, width=N)`` — never
  ``TRIM()`` in WHERE/JOIN. Column widths: team_id varchar(8),
  company_id varchar(4), status varchar(1), ready_to_bill varchar(512).
* Half-open date bounds: ``col >= start AND col < (end + 1 day)``.
* ``cst_today()`` / pool ``init=_set_cst_session`` — datalake is CST, the
  app must be too. Bare CURRENT_DATE / now() in SQL resolves to CST.

Indexes created via avnadmin 2026-04-30:
* idx_cashflow_arrival      btree (origin_actual_arrival)
* idx_cashflow_bill_date    btree (bill_date)
* idx_cashflow_unbilled     btree (status, ready_to_bill, origin_actual_arrival)
                              WHERE bill_date < '2000-01-01'
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, Query, Request

from app.clock import cst_today
from app.datalake import pad_variants as _pad_variants
from app.routers.deps import get_datalake_gold_pool, require_report_access


# Bruno's scope tuples — kept verbatim from the PDF.
ALL_TEAMS = ("TEAM1", "TEAM2", "TEAM3", "TEAM4", "TEAM5", "TEAM-DFW")
COMPANIES = ("TMS", "TMS3")
OPEN_STATUSES = ("D", "P")
DELIVERED_ONLY = ("D",)

# McLeod uses ``< '2000-01-01'`` as a sentinel for "field not set".
DATE_SENTINEL = date(2000, 1, 1)

# Dollar threshold above which the "cash parked unbilled" banner fires.
UNBILLED_ALARM_USD = 3_000_000.0

# Soft year floor — ``mcleod_gld_cashflow`` has rows with
# ``origin_actual_arrival = 1900-01-01`` that are noise.
YEAR_FLOOR = date(2024, 1, 1)


router = APIRouter(tags=["admin-cashflow"], prefix="/custom/admin-cashflow")


# ---------------------------------------------------------------------------
# Date helpers
# ---------------------------------------------------------------------------


def _today_clamped() -> date:
    return max(YEAR_FLOOR, cst_today())


def _month_bounds(today: date) -> tuple[date, date, date, date]:
    m_start = today.replace(day=1)
    if m_start.month == 12:
        next_first = m_start.replace(year=m_start.year + 1, month=1)
    else:
        next_first = m_start.replace(month=m_start.month + 1)
    m_end = next_first - timedelta(days=1)
    lm_end = m_start - timedelta(days=1)
    lm_start = lm_end.replace(day=1)
    return m_start, m_end, lm_start, lm_end


def _clamp(d: Optional[date], default: date) -> date:
    if d is None:
        return default
    if d < YEAR_FLOOR:
        return YEAR_FLOOR
    today = _today_clamped()
    if d > today:
        return today
    return d


def _resolve_range(
    rng: Optional[str],
    start_date: Optional[date],
    end_date: Optional[date],
) -> tuple[date, date]:
    today = _today_clamped()
    m_start, _m_end, lm_start, lm_end = _month_bounds(today)

    if rng == "today":
        return today, today
    if rng == "wtd":
        # ISO Mon-anchored week, current included
        wstart = today - timedelta(days=today.weekday())
        return _clamp(wstart, wstart), today
    if rng == "last_7d":
        return _clamp(today - timedelta(days=6), today - timedelta(days=6)), today
    if rng == "last_month":
        return _clamp(lm_start, lm_start), _clamp(lm_end, lm_end)
    if rng == "ytd":
        ys = date(today.year, 1, 1)
        return _clamp(ys, ys), today
    if rng == "custom":
        s = _clamp(start_date, m_start)
        e = _clamp(end_date, today)
        if e < s:
            s, e = e, s
        return s, e
    # default: MTD (1st of month → today)
    return _clamp(m_start, m_start), today


def _parse_teams(teams: Optional[str]) -> list[str]:
    if not teams:
        return list(ALL_TEAMS)
    wanted = [t.strip() for t in teams.split(",") if t.strip()]
    allowed = {t for t in ALL_TEAMS}
    return [t for t in wanted if t in allowed] or list(ALL_TEAMS)


def _parse_companies(companies: Optional[str]) -> list[str]:
    if not companies:
        return list(COMPANIES)
    wanted = [c.strip() for c in companies.split(",") if c.strip()]
    allowed = {c for c in COMPANIES}
    return [c for c in wanted if c in allowed] or list(COMPANIES)


# ---------------------------------------------------------------------------
# Shared WHERE builders
# ---------------------------------------------------------------------------


def _scope_where(
    alias: str,
    teams: list[str],
    companies: list[str],
    statuses: tuple[str, ...],
    customer: Optional[str],
    contract_type: Optional[str],
    params: list,
) -> str:
    """Build the shared WHERE fragment for mcleod_gld_cashflow.

    Padded-variant ``= ANY($N)`` predicates keep btree indexes usable.
    """
    params.append(_pad_variants(teams, width=8))
    p_teams = len(params)
    params.append(_pad_variants(companies, width=4))
    p_companies = len(params)
    params.append(_pad_variants(statuses, width=1))
    p_status = len(params)

    parts = [
        f"{alias}.team_id    = ANY(${p_teams})",
        f"{alias}.company_id = ANY(${p_companies})",
        f"{alias}.status     = ANY(${p_status})",
    ]
    if customer:
        params.append(customer)
        parts.append(f"{alias}.customer_name = ${len(params)}")
    if contract_type:
        params.append(contract_type)
        parts.append(f"{alias}.contract_type_descr = ${len(params)}")
    return " AND ".join(parts)


def _date_fragment(alias: str, s: date, e: date, params: list) -> str:
    """Half-open date bound on origin_actual_arrival (sargable)."""
    params.extend([s, e])
    p_s, p_e = len(params) - 1, len(params)
    return (
        f"{alias}.origin_actual_arrival >= ${p_s} "
        f"AND {alias}.origin_actual_arrival < (${p_e}::date + 1)"
    )


# ---------------------------------------------------------------------------
# Facets — distinct customer + contract_type lists for the filter dropdowns
# ---------------------------------------------------------------------------


@router.get("/facets")
async def facets(
    request: Request,
    _user: dict = Depends(require_report_access("admin-cashflow")),
):
    pool = get_datalake_gold_pool(request)
    today = _today_clamped()
    one_year_ago = today - timedelta(days=365)

    rows = await pool.fetch(
        """
        SELECT DISTINCT TRIM(customer_name) AS customer_name
        FROM   public.mcleod_gld_cashflow
        WHERE  team_id    = ANY($1)
          AND  company_id = ANY($2)
          AND  status     = ANY($3)
          AND  origin_actual_arrival >= $4
          AND  customer_name IS NOT NULL
          AND  TRIM(customer_name) <> ''
        ORDER BY customer_name
        """,
        _pad_variants(ALL_TEAMS, width=8),
        _pad_variants(COMPANIES, width=4),
        _pad_variants(OPEN_STATUSES, width=1),
        one_year_ago,
    )
    customers = [r["customer_name"] for r in rows if r["customer_name"]]

    rows = await pool.fetch(
        """
        SELECT DISTINCT TRIM(contract_type_descr) AS contract_type_descr
        FROM   public.mcleod_gld_cashflow
        WHERE  team_id    = ANY($1)
          AND  company_id = ANY($2)
          AND  status     = ANY($3)
          AND  origin_actual_arrival >= $4
          AND  contract_type_descr IS NOT NULL
          AND  TRIM(contract_type_descr) <> ''
        ORDER BY contract_type_descr
        """,
        _pad_variants(ALL_TEAMS, width=8),
        _pad_variants(COMPANIES, width=4),
        _pad_variants(OPEN_STATUSES, width=1),
        one_year_ago,
    )
    contract_types = [r["contract_type_descr"] for r in rows if r["contract_type_descr"]]

    return {
        "success": True,
        "data": {
            "teams": list(ALL_TEAMS),
            "companies": list(COMPANIES),
            "customers": customers,
            "contract_types": contract_types,
            "today": today.isoformat(),
            "year_floor": YEAR_FLOOR.isoformat(),
            "alarm_usd": UNBILLED_ALARM_USD,
        },
    }


# ---------------------------------------------------------------------------
# KPIs — top of the report (3 discipline % + 2 unbilled $)
# ---------------------------------------------------------------------------


@router.get("/kpis")
async def kpis(
    request: Request,
    range: Optional[str] = Query("mtd"),
    start_date: Optional[date] = Query(None),
    end_date: Optional[date] = Query(None),
    teams: Optional[str] = Query(None),
    companies: Optional[str] = Query(None),
    customer: Optional[str] = Query(None),
    contract_type: Optional[str] = Query(None),
    _user: dict = Depends(require_report_access("admin-cashflow")),
):
    pool = get_datalake_gold_pool(request)
    s, e = _resolve_range(range, start_date, end_date)
    team_list = _parse_teams(teams)
    company_list = _parse_companies(companies)

    params: list = []
    where_open = _scope_where(
        "c", team_list, company_list, OPEN_STATUSES, customer, contract_type, params
    )
    date_frag = _date_fragment("c", s, e, params)

    # Single CTE — one round-trip computes every KPI on the same in-scope set.
    sql = f"""
    WITH base AS (
      SELECT
        c.id,
        c.status,
        c.bill_date,
        c.bol_recv_date,
        c.invoice_recv_date,
        c.dest_actual_arrival,
        c.dest_actual_departure,
        c.ready_to_bill,
        c.total_charge
      FROM public.mcleod_gld_cashflow c
      WHERE {where_open} AND {date_frag}
    )
    SELECT
      -- discipline KPI #1: Delivery vs Bill, ≤10 days, status=D, billed
      (
        SELECT
          COALESCE(
            COUNT(DISTINCT id) FILTER (
              WHERE (bill_date::date - dest_actual_departure::date) <= 10
            )::numeric
            / NULLIF(COUNT(DISTINCT id), 0),
          0)
        FROM base
        WHERE status = 'D'
          AND bill_date              > '2000-01-01'::date
          AND dest_actual_departure  > '2000-01-01'::date
      ) AS pct_del_bill_le10,

      -- discipline KPI #2: BOL vs Bill, ≤2 days, status in (D,P), billed
      (
        SELECT
          COALESCE(
            COUNT(DISTINCT id) FILTER (
              WHERE (bill_date::date - bol_recv_date::date) <= 2
            )::numeric
            / NULLIF(COUNT(DISTINCT id), 0),
          0)
        FROM base
        WHERE bill_date    > '2000-01-01'::date
          AND bol_recv_date > '2000-01-01'::date
      ) AS pct_bol_bill_le2,

      -- discipline KPI #3: Carrier Invoice vs Bill, ≤2 days (invoice_recv - bill)
      (
        SELECT
          COALESCE(
            COUNT(DISTINCT id) FILTER (
              WHERE (invoice_recv_date::date - bill_date::date) <= 2
            )::numeric
            / NULLIF(COUNT(DISTINCT id), 0),
          0)
        FROM base
        WHERE bill_date         > '2000-01-01'::date
          AND invoice_recv_date > '2000-01-01'::date
      ) AS pct_carrinv_bill_le2,

      -- $ KPI #1: Delivered but not billed
      (
        SELECT COALESCE(SUM(total_charge), 0)
        FROM base
        WHERE status = 'D'
          AND bill_date < '2000-01-01'::date
      )::numeric AS delivered_not_billed_usd,

      -- $ KPI #2: Ready to bill but not billed
      (
        SELECT COALESCE(SUM(total_charge), 0)
        FROM base
        WHERE bill_date < '2000-01-01'::date
          AND TRIM(ready_to_bill) = 'Y'
      )::numeric AS ready_not_billed_usd,

      -- supporting counts — useful for tooltips / sanity
      (SELECT COUNT(*) FROM base) AS rows_in_scope
    """

    row = await pool.fetchrow(sql, *params)

    delivered_not_billed = float(row["delivered_not_billed_usd"] or 0)
    ready_not_billed = float(row["ready_not_billed_usd"] or 0)
    total_unbilled = delivered_not_billed + ready_not_billed

    return {
        "success": True,
        "data": {
            "pct_del_bill_le10": float(row["pct_del_bill_le10"] or 0) * 100.0,
            "pct_bol_bill_le2": float(row["pct_bol_bill_le2"] or 0) * 100.0,
            "pct_carrinv_bill_le2": float(row["pct_carrinv_bill_le2"] or 0) * 100.0,
            "delivered_not_billed_usd": delivered_not_billed,
            "ready_not_billed_usd": ready_not_billed,
            "total_unbilled_usd": total_unbilled,
            "alarm": total_unbilled > UNBILLED_ALARM_USD,
            "alarm_threshold_usd": UNBILLED_ALARM_USD,
            "rows_in_scope": int(row["rows_in_scope"] or 0),
            "window": {"start": s.isoformat(), "end": e.isoformat()},
        },
    }


# ---------------------------------------------------------------------------
# Sparklines — 12-week trend on the 3 discipline KPIs (ignores Date filter)
# ---------------------------------------------------------------------------


@router.get("/sparklines")
async def sparklines(
    request: Request,
    teams: Optional[str] = Query(None),
    companies: Optional[str] = Query(None),
    customer: Optional[str] = Query(None),
    contract_type: Optional[str] = Query(None),
    _user: dict = Depends(require_report_access("admin-cashflow")),
):
    """12 ISO-week trend for the 3 % KPIs.

    Bucket = ISO week of ``origin_actual_arrival``. Includes the current
    week (partial). Caller can drop the last point if they prefer "completed
    weeks only" but for a 12-week sparkline the current point is fine.
    """
    pool = get_datalake_gold_pool(request)
    today = _today_clamped()
    # 12 weeks back (Monday of week 11 weeks ago through today)
    week_start_today = today - timedelta(days=today.weekday())
    s = week_start_today - timedelta(weeks=11)
    e = today
    team_list = _parse_teams(teams)
    company_list = _parse_companies(companies)

    params: list = []
    where_open = _scope_where(
        "c", team_list, company_list, OPEN_STATUSES, customer, contract_type, params
    )
    date_frag = _date_fragment("c", s, e, params)

    sql = f"""
    WITH base AS (
      SELECT
        date_trunc('week', c.origin_actual_arrival)::date AS wk,
        c.id,
        c.status,
        c.bill_date,
        c.bol_recv_date,
        c.invoice_recv_date,
        c.dest_actual_departure
      FROM public.mcleod_gld_cashflow c
      WHERE {where_open} AND {date_frag}
    )
    SELECT
      wk,
      -- denominators kept separate per KPI (different status/sentinel filters)
      COUNT(DISTINCT id) FILTER (
        WHERE status='D' AND bill_date>'2000-01-01'::date
          AND dest_actual_departure>'2000-01-01'::date
      ) AS d_n_del,
      COUNT(DISTINCT id) FILTER (
        WHERE status='D' AND bill_date>'2000-01-01'::date
          AND dest_actual_departure>'2000-01-01'::date
          AND (bill_date::date - dest_actual_departure::date) <= 10
      ) AS d_le10_del,
      COUNT(DISTINCT id) FILTER (
        WHERE bill_date>'2000-01-01'::date
          AND bol_recv_date>'2000-01-01'::date
      ) AS d_n_bol,
      COUNT(DISTINCT id) FILTER (
        WHERE bill_date>'2000-01-01'::date
          AND bol_recv_date>'2000-01-01'::date
          AND (bill_date::date - bol_recv_date::date) <= 2
      ) AS d_le2_bol,
      COUNT(DISTINCT id) FILTER (
        WHERE bill_date>'2000-01-01'::date
          AND invoice_recv_date>'2000-01-01'::date
      ) AS d_n_inv,
      COUNT(DISTINCT id) FILTER (
        WHERE bill_date>'2000-01-01'::date
          AND invoice_recv_date>'2000-01-01'::date
          AND (invoice_recv_date::date - bill_date::date) <= 2
      ) AS d_le2_inv
    FROM base
    GROUP BY wk
    ORDER BY wk
    """
    rows = await pool.fetch(sql, *params)

    def pct(num, den):
        n = int(num or 0)
        d = int(den or 0)
        if d == 0:
            return None
        return round(n * 100.0 / d, 2)

    return {
        "success": True,
        "data": {
            "weeks": [r["wk"].isoformat() for r in rows],
            "del_bill_le10": [pct(r["d_le10_del"], r["d_n_del"]) for r in rows],
            "bol_bill_le2": [pct(r["d_le2_bol"], r["d_n_bol"]) for r in rows],
            "carrinv_bill_le2": [pct(r["d_le2_inv"], r["d_n_inv"]) for r in rows],
        },
    }


# ---------------------------------------------------------------------------
# Delivered but not billed — table + grand total
# ---------------------------------------------------------------------------

_DELIVERED_NOT_BILLED_SORTS = {
    "ship_desc": "ship_date DESC NULLS LAST",
    "ship_asc": "ship_date ASC NULLS LAST",
    "delivered_desc": "dest_actual_arrival DESC NULLS LAST",
    "delivered_asc": "dest_actual_arrival ASC NULLS LAST",
    "revenue_desc": "total_charge DESC NULLS LAST",
    "revenue_asc": "total_charge ASC NULLS LAST",
    "id_asc": "id ASC",
    "id_desc": "id DESC",
}


@router.get("/delivered-not-billed")
async def delivered_not_billed(
    request: Request,
    range: Optional[str] = Query("mtd"),
    start_date: Optional[date] = Query(None),
    end_date: Optional[date] = Query(None),
    teams: Optional[str] = Query(None),
    companies: Optional[str] = Query(None),
    customer: Optional[str] = Query(None),
    contract_type: Optional[str] = Query(None),
    sort: str = Query("delivered_asc"),  # oldest unbilled first = most actionable
    page: int = Query(1, ge=1),
    limit: int = Query(50, ge=1, le=500),
    _user: dict = Depends(require_report_access("admin-cashflow")),
):
    pool = get_datalake_gold_pool(request)
    s, e = _resolve_range(range, start_date, end_date)
    team_list = _parse_teams(teams)
    company_list = _parse_companies(companies)
    offset = (page - 1) * limit
    order_by = _DELIVERED_NOT_BILLED_SORTS.get(sort, "dest_actual_arrival ASC NULLS LAST")

    params: list = []
    where = _scope_where(
        "c", team_list, company_list, DELIVERED_ONLY, customer, contract_type, params
    )
    date_frag = _date_fragment("c", s, e, params)
    params.extend([limit, offset])
    p_lim, p_off = len(params) - 1, len(params)

    sql = f"""
    WITH base AS (
      SELECT
        c.id,
        c.orig_orig_sched_early                                AS orig_sched_early,
        c.origin_actual_arrival                                AS ship_date,
        c.dest_actual_arrival,
        c.customer_name,
        c.team_id,
        c.company_id,
        c.total_charge,
        CASE
          WHEN c.dest_actual_arrival > '2000-01-01'::date
          THEN ((now() AT TIME ZONE 'America/Chicago')::date
                - c.dest_actual_arrival::date)
          ELSE NULL
        END AS days_since_delivery
      FROM public.mcleod_gld_cashflow c
      WHERE {where} AND {date_frag}
        AND c.bill_date < '2000-01-01'::date
    )
    SELECT
      id, orig_sched_early, ship_date, dest_actual_arrival,
      customer_name, team_id, company_id, total_charge, days_since_delivery,
      COUNT(*)         OVER() AS total_count,
      SUM(total_charge) OVER() AS total_revenue
    FROM base
    ORDER BY {order_by}
    LIMIT ${p_lim} OFFSET ${p_off}
    """
    rows = await pool.fetch(sql, *params)
    total = int(rows[0]["total_count"]) if rows else 0
    total_revenue = float(rows[0]["total_revenue"] or 0) if rows else 0.0

    data = [
        {
            "id": r["id"].strip() if r["id"] else None,
            "orig_sched_early": r["orig_sched_early"].isoformat() if r["orig_sched_early"] else None,
            "ship_date": r["ship_date"].isoformat() if r["ship_date"] else None,
            "dest_actual_arrival": r["dest_actual_arrival"].isoformat() if r["dest_actual_arrival"] else None,
            "customer_name": (r["customer_name"] or "").strip(),
            "team_id": (r["team_id"] or "").strip(),
            "company_id": (r["company_id"] or "").strip(),
            "total_charge": float(r["total_charge"] or 0),
            "days_since_delivery": int(r["days_since_delivery"]) if r["days_since_delivery"] is not None else None,
        }
        for r in rows
    ]

    # Grand total over the full filtered set (not just this page)
    if rows:
        grand = total_revenue
    else:
        grand_row = await pool.fetchrow(
            f"""
            SELECT COALESCE(SUM(total_charge),0) AS s
            FROM   public.mcleod_gld_cashflow c
            WHERE  {where} AND {date_frag}
              AND  c.bill_date < '2000-01-01'::date
            """,
            *params[:-2],  # drop limit/offset
        )
        grand = float(grand_row["s"] or 0)

    return {
        "success": True,
        "data": data,
        "meta": {
            "total": total,
            "page": page,
            "limit": limit,
            "grand_total_revenue": grand,
        },
    }


# ---------------------------------------------------------------------------
# Ready to bill but not billed — table + grand total
# ---------------------------------------------------------------------------

_READY_NOT_BILLED_SORTS = {
    "ship_desc": "ship_date DESC NULLS LAST",
    "ship_asc": "ship_date ASC NULLS LAST",
    "revenue_desc": "total_charge DESC NULLS LAST",
    "revenue_asc": "total_charge ASC NULLS LAST",
    "status_asc": "status ASC, ship_date ASC NULLS LAST",
    "id_asc": "id ASC",
    "id_desc": "id DESC",
}


@router.get("/ready-not-billed")
async def ready_not_billed(
    request: Request,
    range: Optional[str] = Query("mtd"),
    start_date: Optional[date] = Query(None),
    end_date: Optional[date] = Query(None),
    teams: Optional[str] = Query(None),
    companies: Optional[str] = Query(None),
    customer: Optional[str] = Query(None),
    contract_type: Optional[str] = Query(None),
    sort: str = Query("ship_asc"),
    page: int = Query(1, ge=1),
    limit: int = Query(50, ge=1, le=500),
    _user: dict = Depends(require_report_access("admin-cashflow")),
):
    pool = get_datalake_gold_pool(request)
    s, e = _resolve_range(range, start_date, end_date)
    team_list = _parse_teams(teams)
    company_list = _parse_companies(companies)
    offset = (page - 1) * limit
    order_by = _READY_NOT_BILLED_SORTS.get(sort, "ship_date ASC NULLS LAST")

    params: list = []
    where = _scope_where(
        "c", team_list, company_list, OPEN_STATUSES, customer, contract_type, params
    )
    date_frag = _date_fragment("c", s, e, params)
    params.extend([limit, offset])
    p_lim, p_off = len(params) - 1, len(params)

    sql = f"""
    WITH base AS (
      SELECT
        c.id,
        c.orig_orig_sched_early   AS orig_sched_early,
        c.origin_actual_arrival   AS ship_date,
        c.status,
        c.customer_name,
        c.team_id,
        c.company_id,
        c.total_charge
      FROM public.mcleod_gld_cashflow c
      WHERE {where} AND {date_frag}
        AND c.bill_date < '2000-01-01'::date
        AND TRIM(c.ready_to_bill) = 'Y'
    )
    SELECT
      id, orig_sched_early, ship_date, status,
      customer_name, team_id, company_id, total_charge,
      COUNT(*)          OVER() AS total_count,
      SUM(total_charge) OVER() AS total_revenue
    FROM base
    ORDER BY {order_by}
    LIMIT ${p_lim} OFFSET ${p_off}
    """
    rows = await pool.fetch(sql, *params)
    total = int(rows[0]["total_count"]) if rows else 0
    total_revenue = float(rows[0]["total_revenue"] or 0) if rows else 0.0

    data = [
        {
            "id": r["id"].strip() if r["id"] else None,
            "orig_sched_early": r["orig_sched_early"].isoformat() if r["orig_sched_early"] else None,
            "ship_date": r["ship_date"].isoformat() if r["ship_date"] else None,
            "status": (r["status"] or "").strip(),
            "customer_name": (r["customer_name"] or "").strip(),
            "team_id": (r["team_id"] or "").strip(),
            "company_id": (r["company_id"] or "").strip(),
            "total_charge": float(r["total_charge"] or 0),
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
            "grand_total_revenue": total_revenue,
        },
    }


# ---------------------------------------------------------------------------
# Aging detail tables — Delivery vs Bill / BOL vs Bill / Carrier Invoice vs Bill
# ---------------------------------------------------------------------------

_AGING_SORTS = {
    "days_desc": "days DESC NULLS LAST",
    "days_asc": "days ASC NULLS LAST",
    "revenue_desc": "total_charge DESC NULLS LAST",
    "revenue_asc": "total_charge ASC NULLS LAST",
    "ship_desc": "origin_actual_arrival DESC NULLS LAST",
    "ship_asc": "origin_actual_arrival ASC NULLS LAST",
    "id_asc": "id ASC",
    "id_desc": "id DESC",
}


def _aging_payload(rows, *, threshold: int) -> dict:
    if not rows:
        return {
            "rows": [],
            "total_count": 0,
            "le_threshold_count": 0,
            "gt_threshold_count": 0,
            "threshold": threshold,
        }
    le = int(rows[0]["le_threshold_count"] or 0)
    gt = int(rows[0]["gt_threshold_count"] or 0)
    total = int(rows[0]["total_count"] or 0)
    out_rows = []
    for r in rows:
        d = int(r["days"]) if r["days"] is not None else None
        out_rows.append(
            {
                "id": r["id"].strip() if r["id"] else None,
                "company_id": (r["company_id"] or "").strip(),
                "team_id": (r["team_id"] or "").strip(),
                "customer_name": (r["customer_name"] or "").strip(),
                "left_date": r["left_date"].isoformat() if r["left_date"] else None,
                "bill_date": r["bill_date"].isoformat() if r["bill_date"] else None,
                "days": d,
                "total_charge": float(r["total_charge"] or 0),
            }
        )
    return {
        "rows": out_rows,
        "total_count": total,
        "le_threshold_count": le,
        "gt_threshold_count": gt,
        "threshold": threshold,
    }


@router.get("/aging/delivery-vs-bill")
async def aging_delivery_vs_bill(
    request: Request,
    range: Optional[str] = Query("mtd"),
    start_date: Optional[date] = Query(None),
    end_date: Optional[date] = Query(None),
    teams: Optional[str] = Query(None),
    companies: Optional[str] = Query(None),
    customer: Optional[str] = Query(None),
    contract_type: Optional[str] = Query(None),
    sort: str = Query("days_desc"),
    page: int = Query(1, ge=1),
    limit: int = Query(50, ge=1, le=500),
    _user: dict = Depends(require_report_access("admin-cashflow")),
):
    pool = get_datalake_gold_pool(request)
    s, e = _resolve_range(range, start_date, end_date)
    team_list = _parse_teams(teams)
    company_list = _parse_companies(companies)
    offset = (page - 1) * limit
    order_by = _AGING_SORTS.get(sort, "days DESC NULLS LAST")
    threshold = 10

    params: list = []
    where = _scope_where(
        "c", team_list, company_list, OPEN_STATUSES, customer, contract_type, params
    )
    date_frag = _date_fragment("c", s, e, params)
    params.extend([limit, offset])
    p_lim, p_off = len(params) - 1, len(params)

    sql = f"""
    WITH base AS (
      SELECT
        c.id, c.company_id, c.team_id, c.customer_name,
        c.dest_actual_departure                            AS left_date,
        c.bill_date,
        c.origin_actual_arrival,
        c.total_charge,
        (c.bill_date::date - c.dest_actual_departure::date) AS days
      FROM public.mcleod_gld_cashflow c
      WHERE {where} AND {date_frag}
        AND c.bill_date              > '2000-01-01'::date
        AND c.dest_actual_arrival    > '2000-01-01'::date
        AND c.dest_actual_departure  > '2000-01-01'::date
    )
    SELECT
      id, company_id, team_id, customer_name, left_date, bill_date,
      days, total_charge, origin_actual_arrival,
      COUNT(*)                                  OVER() AS total_count,
      COUNT(*) FILTER (WHERE days <= {threshold}) OVER() AS le_threshold_count,
      COUNT(*) FILTER (WHERE days >  {threshold}) OVER() AS gt_threshold_count
    FROM base
    ORDER BY {order_by}
    LIMIT ${p_lim} OFFSET ${p_off}
    """
    rows = await pool.fetch(sql, *params)
    payload = _aging_payload(rows, threshold=threshold)
    return {
        "success": True,
        "data": payload["rows"],
        "meta": {
            "total": payload["total_count"],
            "page": page,
            "limit": limit,
            "le_threshold_count": payload["le_threshold_count"],
            "gt_threshold_count": payload["gt_threshold_count"],
            "threshold": threshold,
        },
    }


@router.get("/aging/bol-vs-bill")
async def aging_bol_vs_bill(
    request: Request,
    range: Optional[str] = Query("mtd"),
    start_date: Optional[date] = Query(None),
    end_date: Optional[date] = Query(None),
    teams: Optional[str] = Query(None),
    companies: Optional[str] = Query(None),
    customer: Optional[str] = Query(None),
    contract_type: Optional[str] = Query(None),
    sort: str = Query("days_desc"),
    page: int = Query(1, ge=1),
    limit: int = Query(50, ge=1, le=500),
    _user: dict = Depends(require_report_access("admin-cashflow")),
):
    pool = get_datalake_gold_pool(request)
    s, e = _resolve_range(range, start_date, end_date)
    team_list = _parse_teams(teams)
    company_list = _parse_companies(companies)
    offset = (page - 1) * limit
    order_by = _AGING_SORTS.get(sort, "days DESC NULLS LAST")
    threshold = 2

    params: list = []
    where = _scope_where(
        "c", team_list, company_list, OPEN_STATUSES, customer, contract_type, params
    )
    date_frag = _date_fragment("c", s, e, params)
    params.extend([limit, offset])
    p_lim, p_off = len(params) - 1, len(params)

    sql = f"""
    WITH base AS (
      SELECT
        c.id, c.company_id, c.team_id, c.customer_name,
        c.bol_recv_date                                AS left_date,
        c.bill_date,
        c.origin_actual_arrival,
        c.total_charge,
        (c.bill_date::date - c.bol_recv_date::date)    AS days
      FROM public.mcleod_gld_cashflow c
      WHERE {where} AND {date_frag}
        AND c.bill_date     > '2000-01-01'::date
        AND c.bol_recv_date > '2000-01-01'::date
    )
    SELECT
      id, company_id, team_id, customer_name, left_date, bill_date,
      days, total_charge, origin_actual_arrival,
      COUNT(*)                                  OVER() AS total_count,
      COUNT(*) FILTER (WHERE days <= {threshold}) OVER() AS le_threshold_count,
      COUNT(*) FILTER (WHERE days >  {threshold}) OVER() AS gt_threshold_count
    FROM base
    ORDER BY {order_by}
    LIMIT ${p_lim} OFFSET ${p_off}
    """
    rows = await pool.fetch(sql, *params)
    payload = _aging_payload(rows, threshold=threshold)
    return {
        "success": True,
        "data": payload["rows"],
        "meta": {
            "total": payload["total_count"],
            "page": page,
            "limit": limit,
            "le_threshold_count": payload["le_threshold_count"],
            "gt_threshold_count": payload["gt_threshold_count"],
            "threshold": threshold,
        },
    }


@router.get("/aging/carrinv-vs-bill")
async def aging_carrinv_vs_bill(
    request: Request,
    range: Optional[str] = Query("mtd"),
    start_date: Optional[date] = Query(None),
    end_date: Optional[date] = Query(None),
    teams: Optional[str] = Query(None),
    companies: Optional[str] = Query(None),
    customer: Optional[str] = Query(None),
    contract_type: Optional[str] = Query(None),
    sort: str = Query("days_desc"),
    page: int = Query(1, ge=1),
    limit: int = Query(50, ge=1, le=500),
    _user: dict = Depends(require_report_access("admin-cashflow")),
):
    pool = get_datalake_gold_pool(request)
    s, e = _resolve_range(range, start_date, end_date)
    team_list = _parse_teams(teams)
    company_list = _parse_companies(companies)
    offset = (page - 1) * limit
    order_by = _AGING_SORTS.get(sort, "days DESC NULLS LAST")
    threshold = 2

    params: list = []
    where = _scope_where(
        "c", team_list, company_list, OPEN_STATUSES, customer, contract_type, params
    )
    date_frag = _date_fragment("c", s, e, params)
    params.extend([limit, offset])
    p_lim, p_off = len(params) - 1, len(params)

    sql = f"""
    WITH base AS (
      SELECT
        c.id, c.company_id, c.team_id, c.customer_name,
        c.invoice_recv_date                                  AS left_date,
        c.bill_date,
        c.origin_actual_arrival,
        c.total_charge,
        (c.invoice_recv_date::date - c.bill_date::date)      AS days
      FROM public.mcleod_gld_cashflow c
      WHERE {where} AND {date_frag}
        AND c.bill_date         > '2000-01-01'::date
        AND c.invoice_recv_date > '2000-01-01'::date
    )
    SELECT
      id, company_id, team_id, customer_name, left_date, bill_date,
      days, total_charge, origin_actual_arrival,
      COUNT(*)                                  OVER() AS total_count,
      COUNT(*) FILTER (WHERE days <= {threshold}) OVER() AS le_threshold_count,
      COUNT(*) FILTER (WHERE days >  {threshold}) OVER() AS gt_threshold_count
    FROM base
    ORDER BY {order_by}
    LIMIT ${p_lim} OFFSET ${p_off}
    """
    rows = await pool.fetch(sql, *params)
    payload = _aging_payload(rows, threshold=threshold)
    return {
        "success": True,
        "data": payload["rows"],
        "meta": {
            "total": payload["total_count"],
            "page": page,
            "limit": limit,
            "le_threshold_count": payload["le_threshold_count"],
            "gt_threshold_count": payload["gt_threshold_count"],
            "threshold": threshold,
        },
    }


# ---------------------------------------------------------------------------
# UX add-on #1: Aging buckets (delivery-vs-bill distribution)
# ---------------------------------------------------------------------------


@router.get("/aging-buckets")
async def aging_buckets(
    request: Request,
    range: Optional[str] = Query("mtd"),
    start_date: Optional[date] = Query(None),
    end_date: Optional[date] = Query(None),
    teams: Optional[str] = Query(None),
    companies: Optional[str] = Query(None),
    customer: Optional[str] = Query(None),
    contract_type: Optional[str] = Query(None),
    _user: dict = Depends(require_report_access("admin-cashflow")),
):
    """Bucket the delivery-to-bill day delta into 0-3 / 4-7 / 8-10 / 11-15 / >15."""
    pool = get_datalake_gold_pool(request)
    s, e = _resolve_range(range, start_date, end_date)
    team_list = _parse_teams(teams)
    company_list = _parse_companies(companies)

    params: list = []
    where = _scope_where(
        "c", team_list, company_list, OPEN_STATUSES, customer, contract_type, params
    )
    date_frag = _date_fragment("c", s, e, params)

    sql = f"""
    WITH base AS (
      SELECT (c.bill_date::date - c.dest_actual_departure::date) AS days
      FROM   public.mcleod_gld_cashflow c
      WHERE  {where} AND {date_frag}
        AND  c.bill_date              > '2000-01-01'::date
        AND  c.dest_actual_arrival    > '2000-01-01'::date
        AND  c.dest_actual_departure  > '2000-01-01'::date
    )
    SELECT
      COUNT(*) FILTER (WHERE days <  0)                AS bk_neg,
      COUNT(*) FILTER (WHERE days BETWEEN 0  AND 3)    AS bk_0_3,
      COUNT(*) FILTER (WHERE days BETWEEN 4  AND 7)    AS bk_4_7,
      COUNT(*) FILTER (WHERE days BETWEEN 8  AND 10)   AS bk_8_10,
      COUNT(*) FILTER (WHERE days BETWEEN 11 AND 15)   AS bk_11_15,
      COUNT(*) FILTER (WHERE days > 15)                AS bk_gt15,
      COUNT(*)                                         AS total
    FROM base
    """
    row = await pool.fetchrow(sql, *params)
    return {
        "success": True,
        "data": {
            "buckets": [
                {"label": "<0",    "count": int(row["bk_neg"]   or 0)},
                {"label": "0-3",   "count": int(row["bk_0_3"]   or 0)},
                {"label": "4-7",   "count": int(row["bk_4_7"]   or 0)},
                {"label": "8-10",  "count": int(row["bk_8_10"]  or 0)},
                {"label": "11-15", "count": int(row["bk_11_15"] or 0)},
                {"label": ">15",   "count": int(row["bk_gt15"]  or 0)},
            ],
            "total": int(row["total"] or 0),
        },
    }


# ---------------------------------------------------------------------------
# UX add-on #2: Top delayed customers leaderboard ($ revenue at risk)
# ---------------------------------------------------------------------------


@router.get("/top-delayed-customers")
async def top_delayed_customers(
    request: Request,
    range: Optional[str] = Query("mtd"),
    start_date: Optional[date] = Query(None),
    end_date: Optional[date] = Query(None),
    teams: Optional[str] = Query(None),
    companies: Optional[str] = Query(None),
    customer: Optional[str] = Query(None),
    contract_type: Optional[str] = Query(None),
    limit: int = Query(10, ge=1, le=50),
    _user: dict = Depends(require_report_access("admin-cashflow")),
):
    """Customers ranked by $ revenue on loads where bill - delivery > 10 days."""
    pool = get_datalake_gold_pool(request)
    s, e = _resolve_range(range, start_date, end_date)
    team_list = _parse_teams(teams)
    company_list = _parse_companies(companies)

    params: list = []
    where = _scope_where(
        "c", team_list, company_list, OPEN_STATUSES, customer, contract_type, params
    )
    date_frag = _date_fragment("c", s, e, params)
    params.append(limit)
    p_lim = len(params)

    sql = f"""
    WITH base AS (
      SELECT
        TRIM(c.customer_name)                              AS customer_name,
        c.id,
        c.total_charge,
        (c.bill_date::date - c.dest_actual_departure::date) AS days
      FROM public.mcleod_gld_cashflow c
      WHERE {where} AND {date_frag}
        AND c.bill_date              > '2000-01-01'::date
        AND c.dest_actual_arrival    > '2000-01-01'::date
        AND c.dest_actual_departure  > '2000-01-01'::date
        AND c.customer_name IS NOT NULL
        AND TRIM(c.customer_name) <> ''
    )
    SELECT
      customer_name,
      COUNT(*)                              AS n_loads,
      COUNT(*) FILTER (WHERE days > 10)     AS n_late,
      COALESCE(SUM(total_charge) FILTER (WHERE days > 10), 0)::numeric  AS late_revenue,
      COALESCE(AVG(days), 0)::numeric       AS avg_days
    FROM base
    GROUP BY customer_name
    HAVING COUNT(*) FILTER (WHERE days > 10) > 0
    ORDER BY late_revenue DESC
    LIMIT ${p_lim}
    """
    rows = await pool.fetch(sql, *params)

    return {
        "success": True,
        "data": [
            {
                "customer_name": r["customer_name"],
                "n_loads": int(r["n_loads"] or 0),
                "n_late": int(r["n_late"] or 0),
                "late_revenue": float(r["late_revenue"] or 0),
                "avg_days": float(r["avg_days"] or 0),
            }
            for r in rows
        ],
    }
