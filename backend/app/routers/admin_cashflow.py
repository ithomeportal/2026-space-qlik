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

import csv
import io
from datetime import date, timedelta
from typing import Iterable, Optional

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import Response

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


def _resolve_prior_range(
    rng: Optional[str],
    s: date,
    e: date,
) -> tuple[date, date, str]:
    """Comparison window for the KPI trend Δ, keyed to the selected Range.

    Bruno Aging (PDF 2026-07-20): the baseline now shifts with the range —
    an equal-length prior window in every case:
      today      → yesterday
      wtd        → previous week (same weekday span)
      last_7d    → the 7 days before (days 8-14 prior)
      mtd        → same day of the previous month
      ytd        → same date of the previous year
      last_month → the month before last
      custom     → the equal-length span immediately before [s, e]
    Returns (prior_start, prior_end, basis_label).
    """
    if rng == "today":
        y = s - timedelta(days=1)
        return y, y, "yesterday"
    if rng == "wtd":
        return s - timedelta(days=7), e - timedelta(days=7), "last week"
    if rng == "last_7d":
        return s - timedelta(days=7), e - timedelta(days=7), "prev 7d"
    if rng == "mtd":
        lm_end = s - timedelta(days=1)              # last day of previous month
        lm_start = lm_end.replace(day=1)
        day = min(e.day, lm_end.day)
        return lm_start, lm_end.replace(day=day), "same day LM"
    if rng == "ytd":
        ps = date(s.year - 1, 1, 1)
        try:
            pe = e.replace(year=e.year - 1)
        except ValueError:                          # Feb 29 → Feb 28
            pe = date(e.year - 1, 2, 28)
        return ps, pe, "same date LY"
    if rng == "last_month":
        pe = s - timedelta(days=1)                  # last day of the month before
        ps = pe.replace(day=1)
        return ps, pe, "prior month"
    # custom (and any fallback): equal-length window immediately before [s, e]
    span = (e - s).days
    pe = s - timedelta(days=1)
    ps = pe - timedelta(days=span)
    return ps, pe, "prior period"


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


def _parse_customers(customers: Optional[str]) -> list[str]:
    if not customers:
        return []
    return [c.strip() for c in customers.split(",") if c.strip()]


def _scope_where(
    alias: str,
    teams: list[str],
    companies: list[str],
    statuses: tuple[str, ...],
    customer: Optional[str],
    contract_type: Optional[str],
    params: list,
    *,
    customers: Optional[list[str]] = None,
    customer_mode: str = "include",
) -> str:
    """Build the shared WHERE fragment for mcleod_gld_cashflow.

    Padded-variant ``= ANY($N)`` predicates keep btree indexes usable.
    Customer filter supports either single ``customer=`` (legacy) or
    multi-value ``customers=`` with ``customer_mode`` in {include, exclude}.
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
    cust_list = customers if customers else ([customer] if customer else [])
    if cust_list:
        params.append(cust_list)
        op = "<> ALL" if customer_mode == "exclude" else "= ANY"
        parts.append(f"{alias}.customer_name {op}(${len(params)})")
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


def _order_customer_filter(
    alias: str,
    order_q: Optional[str],
    customer_q: Optional[str],
    params: list,
) -> str:
    """Bruno Aging R2 (2026-06-11): free-text 'contains' filters for the Order
    id + Customer name columns of the two unbilled tables. Both are ILIKE
    '%q%' (non-sargable by nature — a search box), but they run on top of the
    already date+scope-narrowed set, so the scan is over a small subset. The
    '%q%' wrap also makes char-padded ``id`` match regardless of trailing pad.
    Returns a leading-`` AND ``-prefixed fragment (or '' when both blank)."""
    frag = ""
    if order_q and order_q.strip():
        params.append(f"%{order_q.strip()}%")
        frag += f" AND {alias}.id ILIKE ${len(params)}"
    if customer_q and customer_q.strip():
        params.append(f"%{customer_q.strip()}%")
        frag += f" AND {alias}.customer_name ILIKE ${len(params)}"
    return frag


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
    customers: Optional[str] = Query(None),
    customer_mode: str = Query("include"),
    contract_type: Optional[str] = Query(None),
    _user: dict = Depends(require_report_access("admin-cashflow")),
):
    pool = get_datalake_gold_pool(request)
    s, e = _resolve_range(range, start_date, end_date)
    team_list = _parse_teams(teams)
    company_list = _parse_companies(companies)

    params: list = []
    where_open = _scope_where(
        "c", team_list, company_list, OPEN_STATUSES, customer, contract_type, params,
        customers=_parse_customers(customers), customer_mode=customer_mode,
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
      -- discipline KPI #1: Delivery vs Bill, ≤2 days
      -- Bruno R4 PDF 2026-05-26: predicate widened to status IN ('D','P') and
      -- guarded on dest_actual_arrival>2000 (was status='D', no arrival guard).
      -- dest_actual_departure>2000 kept — required so the calendar-day diff
      -- doesn't explode on sentinel '1900' dates (Qlik's day() masked this).
      (
        SELECT
          COALESCE(
            COUNT(DISTINCT id) FILTER (
              WHERE (bill_date::date - dest_actual_departure::date) <= 2
            )::numeric
            / NULLIF(COUNT(DISTINCT id), 0),
          0)
        FROM base
        WHERE status IN ('D','P')
          AND bill_date              > '2000-01-01'::date
          AND dest_actual_arrival    > '2000-01-01'::date
          AND dest_actual_departure  > '2000-01-01'::date
      ) AS pct_del_bill_le2,

      -- discipline KPI #2: BOL vs Bill, ≤1 day (Bruno R3 PDF 2026-05-19)
      (
        SELECT
          COALESCE(
            COUNT(DISTINCT id) FILTER (
              WHERE (bill_date::date - bol_recv_date::date) <= 1
            )::numeric
            / NULLIF(COUNT(DISTINCT id), 0),
          0)
        FROM base
        WHERE bill_date    > '2000-01-01'::date
          AND bol_recv_date > '2000-01-01'::date
      ) AS pct_bol_bill_le1,

      -- discipline KPI #3: Carrier Invoice vs Bill, ≤1 day (Bruno R3 PDF 2026-05-19)
      -- Direction flipped: bill_date - invoice_recv_date (was invoice_recv - bill).
      (
        SELECT
          COALESCE(
            COUNT(DISTINCT id) FILTER (
              WHERE (bill_date::date - invoice_recv_date::date) <= 1
            )::numeric
            / NULLIF(COUNT(DISTINCT id), 0),
          0)
        FROM base
        WHERE bill_date         > '2000-01-01'::date
          AND invoice_recv_date > '2000-01-01'::date
      ) AS pct_carrinv_bill_le1,

      -- Avg KPI #A: Avg Days Delivery → Bill (bill_date - dest_actual_departure)
      -- Bruno R4 PDF 2026-05-26: same scope as the % above (D,P + arrival guard).
      (
        SELECT COALESCE(AVG(bill_date::date - dest_actual_departure::date)::numeric, 0)
        FROM base
        WHERE status IN ('D','P')
          AND bill_date              > '2000-01-01'::date
          AND dest_actual_arrival    > '2000-01-01'::date
          AND dest_actual_departure  > '2000-01-01'::date
      )::numeric AS avg_days_del_bill,

      -- Avg KPI #B: Avg Days BOL Rec → Bill (bill_date - bol_recv_date)
      (
        SELECT COALESCE(AVG(bill_date::date - bol_recv_date::date)::numeric, 0)
        FROM base
        WHERE bill_date    > '2000-01-01'::date
          AND bol_recv_date > '2000-01-01'::date
      )::numeric AS avg_days_bol_bill,

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
      (SELECT COUNT(*) FROM base) AS rows_in_scope,

      -- Bruno R4 PDF 2026-05-26: per-KPI supporting breakdown (count + revenue,
      -- ≤threshold vs total) shown under each card. Predicates intentionally
      -- match the matching % subquery above, so le_cnt / tot_cnt == the shown
      -- ratio (KPI detail must reconcile to the headline). The two Avg-Days
      -- cards reuse the same scope as their % companions (delivery / bol).
      d.le_cnt  AS del_le2_count,     d.tot_cnt AS del_total_count,
      d.le_rev  AS del_le2_rev,       d.tot_rev AS del_total_rev,
      b.le_cnt  AS bol_le1_count,     b.tot_cnt AS bol_total_count,
      b.le_rev  AS bol_le1_rev,       b.tot_rev AS bol_total_rev,
      v.le_cnt  AS carrinv_le1_count, v.tot_cnt AS carrinv_total_count,
      v.le_rev  AS carrinv_le1_rev,   v.tot_rev AS carrinv_total_rev
    FROM
      (SELECT
         COUNT(DISTINCT id) FILTER (WHERE (bill_date::date - dest_actual_departure::date) <= 2) AS le_cnt,
         COUNT(DISTINCT id)                                                                      AS tot_cnt,
         COALESCE(SUM(total_charge) FILTER (WHERE (bill_date::date - dest_actual_departure::date) <= 2), 0) AS le_rev,
         COALESCE(SUM(total_charge), 0)                                                          AS tot_rev
       FROM base
       WHERE status IN ('D','P')
         AND bill_date             > '2000-01-01'::date
         AND dest_actual_arrival   > '2000-01-01'::date
         AND dest_actual_departure > '2000-01-01'::date) d,
      (SELECT
         COUNT(DISTINCT id) FILTER (WHERE (bill_date::date - bol_recv_date::date) <= 1) AS le_cnt,
         COUNT(DISTINCT id)                                                             AS tot_cnt,
         COALESCE(SUM(total_charge) FILTER (WHERE (bill_date::date - bol_recv_date::date) <= 1), 0) AS le_rev,
         COALESCE(SUM(total_charge), 0)                                                 AS tot_rev
       FROM base
       WHERE bill_date     > '2000-01-01'::date
         AND bol_recv_date > '2000-01-01'::date) b,
      (SELECT
         COUNT(DISTINCT id) FILTER (WHERE (bill_date::date - invoice_recv_date::date) <= 1) AS le_cnt,
         COUNT(DISTINCT id)                                                                 AS tot_cnt,
         COALESCE(SUM(total_charge) FILTER (WHERE (bill_date::date - invoice_recv_date::date) <= 1), 0) AS le_rev,
         COALESCE(SUM(total_charge), 0)                                                     AS tot_rev
       FROM base
       WHERE bill_date         > '2000-01-01'::date
         AND invoice_recv_date > '2000-01-01'::date) v
    """

    row = await pool.fetchrow(sql, *params)

    delivered_not_billed = float(row["delivered_not_billed_usd"] or 0)
    ready_not_billed = float(row["ready_not_billed_usd"] or 0)
    total_unbilled = delivered_not_billed + ready_not_billed

    # ------------------------------------------------------------------
    # Bruno Aging (PDF 2026-07-20) — trend Δ is now RANGE-AWARE. The comparison
    # baseline shifts with the selected Range filter (equal-length prior
    # window): Today→Yesterday, WTD→previous week, Last 7d→days 8-14 prior,
    # MTD→same day last month, YTD→same date last year, Last Month→prior month,
    # Custom→immediately-preceding equal span. `curr` follows the selected
    # window [s, e] (so it reconciles to the headline %); `prev` follows the
    # shifted window. One scan over the union of both windows; the within/total
    # predicates mirror the headline % so the deltas reconcile.
    # ------------------------------------------------------------------
    ps, pe, basis_label = _resolve_prior_range(range, s, e)
    scan_start = min(s, ps)
    scan_end = max(e, pe)

    t_params: list = []
    t_where = _scope_where(
        "c", team_list, company_list, OPEN_STATUSES, customer, contract_type, t_params,
        customers=_parse_customers(customers), customer_mode=customer_mode,
    )
    t_params.extend([scan_start, scan_end])
    p_ws, p_we = len(t_params) - 1, len(t_params)
    t_params.append(s);  p_cs = len(t_params)
    t_params.append(e);  p_ce = len(t_params)
    t_params.append(ps); p_ps = len(t_params)
    t_params.append(pe); p_pe = len(t_params)

    trend_sql = f"""
    WITH tb AS (
      SELECT
        c.id,
        c.origin_actual_arrival::date AS oad,
        (c.status IN ('D','P')
          AND c.bill_date             > '2000-01-01'::date
          AND c.dest_actual_arrival   > '2000-01-01'::date
          AND c.dest_actual_departure > '2000-01-01'::date) AS del_ok,
        (c.status IN ('D','P')
          AND c.bill_date             > '2000-01-01'::date
          AND c.dest_actual_arrival   > '2000-01-01'::date
          AND c.dest_actual_departure > '2000-01-01'::date
          AND (c.bill_date::date - c.dest_actual_departure::date) <= 2) AS del_win,
        (c.bill_date > '2000-01-01'::date
          AND c.bol_recv_date > '2000-01-01'::date) AS bol_ok,
        (c.bill_date > '2000-01-01'::date
          AND c.bol_recv_date > '2000-01-01'::date
          AND (c.bill_date::date - c.bol_recv_date::date) <= 1) AS bol_win,
        CASE WHEN c.bill_date > '2000-01-01'::date
                  AND c.bol_recv_date > '2000-01-01'::date
             THEN (c.bill_date::date - c.bol_recv_date::date) END AS bol_days
      FROM public.mcleod_gld_cashflow c
      WHERE {t_where}
        AND c.origin_actual_arrival >= ${p_ws}
        AND c.origin_actual_arrival < (${p_we}::date + 1)
    )
    SELECT
      COUNT(DISTINCT id) FILTER (WHERE del_ok  AND oad >= ${p_cs} AND oad <= ${p_ce}) AS del_curr_tot,
      COUNT(DISTINCT id) FILTER (WHERE del_win AND oad >= ${p_cs} AND oad <= ${p_ce}) AS del_curr_le,
      COUNT(DISTINCT id) FILTER (WHERE del_ok  AND oad >= ${p_ps} AND oad <= ${p_pe}) AS del_prev_tot,
      COUNT(DISTINCT id) FILTER (WHERE del_win AND oad >= ${p_ps} AND oad <= ${p_pe}) AS del_prev_le,
      COUNT(DISTINCT id) FILTER (WHERE bol_ok  AND oad >= ${p_cs} AND oad <= ${p_ce}) AS bol_curr_tot,
      COUNT(DISTINCT id) FILTER (WHERE bol_win AND oad >= ${p_cs} AND oad <= ${p_ce}) AS bol_curr_le,
      COUNT(DISTINCT id) FILTER (WHERE bol_ok  AND oad >= ${p_ps} AND oad <= ${p_pe}) AS bol_prev_tot,
      COUNT(DISTINCT id) FILTER (WHERE bol_win AND oad >= ${p_ps} AND oad <= ${p_pe}) AS bol_prev_le,
      AVG(bol_days) FILTER (WHERE oad >= ${p_cs} AND oad <= ${p_ce})                  AS avgbol_curr,
      AVG(bol_days) FILTER (WHERE oad >= ${p_ps} AND oad <= ${p_pe})                  AS avgbol_prev
    FROM tb
    """
    tr = await pool.fetchrow(trend_sql, *t_params)

    def _pct_or_none(le, tot):
        tot = int(tot or 0)
        if tot == 0:
            return None
        return int(le or 0) * 100.0 / tot

    def _avg_or_none(v):
        return float(v) if v is not None else None

    trend = {
        "del": {
            "curr": _pct_or_none(tr["del_curr_le"], tr["del_curr_tot"]),
            "prev": _pct_or_none(tr["del_prev_le"], tr["del_prev_tot"]),
            "basis": basis_label,
            "unit": "pp",
        },
        "bol": {
            "curr": _pct_or_none(tr["bol_curr_le"], tr["bol_curr_tot"]),
            "prev": _pct_or_none(tr["bol_prev_le"], tr["bol_prev_tot"]),
            "basis": basis_label,
            "unit": "pp",
        },
        "avg_days_bol": {
            "curr": _avg_or_none(tr["avgbol_curr"]),
            "prev": _avg_or_none(tr["avgbol_prev"]),
            "basis": basis_label,
            "unit": "d",
        },
    }

    return {
        "success": True,
        "data": {
            "pct_del_bill_le2": float(row["pct_del_bill_le2"] or 0) * 100.0,
            "pct_bol_bill_le1": float(row["pct_bol_bill_le1"] or 0) * 100.0,
            "pct_carrinv_bill_le1": float(row["pct_carrinv_bill_le1"] or 0) * 100.0,
            "avg_days_del_bill": float(row["avg_days_del_bill"] or 0),
            "avg_days_bol_bill": float(row["avg_days_bol_bill"] or 0),
            "delivered_not_billed_usd": delivered_not_billed,
            "ready_not_billed_usd": ready_not_billed,
            "total_unbilled_usd": total_unbilled,
            "alarm": total_unbilled > UNBILLED_ALARM_USD,
            "alarm_threshold_usd": UNBILLED_ALARM_USD,
            "rows_in_scope": int(row["rows_in_scope"] or 0),
            # Bruno R4 PDF 2026-05-26 — per-KPI supporting breakdown
            "del_le2_count": int(row["del_le2_count"] or 0),
            "del_total_count": int(row["del_total_count"] or 0),
            "del_le2_rev": float(row["del_le2_rev"] or 0),
            "del_total_rev": float(row["del_total_rev"] or 0),
            "bol_le1_count": int(row["bol_le1_count"] or 0),
            "bol_total_count": int(row["bol_total_count"] or 0),
            "bol_le1_rev": float(row["bol_le1_rev"] or 0),
            "bol_total_rev": float(row["bol_total_rev"] or 0),
            "carrinv_le1_count": int(row["carrinv_le1_count"] or 0),
            "carrinv_total_count": int(row["carrinv_total_count"] or 0),
            "carrinv_le1_rev": float(row["carrinv_le1_rev"] or 0),
            "carrinv_total_rev": float(row["carrinv_total_rev"] or 0),
            "trend": trend,
            "window": {"start": s.isoformat(), "end": e.isoformat()},
        },
    }


# ---------------------------------------------------------------------------
# Sparklines — 12-week trend on the 3 discipline KPIs (ignores Date filter)
# ---------------------------------------------------------------------------


@router.get("/sparklines")
async def sparklines(
    request: Request,
    range: Optional[str] = Query(None),
    start_date: Optional[date] = Query(None),
    end_date: Optional[date] = Query(None),
    teams: Optional[str] = Query(None),
    companies: Optional[str] = Query(None),
    customer: Optional[str] = Query(None),
    customers: Optional[str] = Query(None),
    customer_mode: str = Query("include"),
    contract_type: Optional[str] = Query(None),
    _user: dict = Depends(require_report_access("admin-cashflow")),
):
    """ISO-week trend for the 3 % KPIs.

    Bucket = ISO week of ``origin_actual_arrival``. Includes the current
    week (partial).

    Bruno Aging R1 (2026-06-11): the trend now follows the selected date
    range. When a ``range`` is supplied it is resolved exactly like every
    other table (``_resolve_range``) and the line spans that window; with no
    range the legacy trailing-12-weeks window is used so the sparkline is
    never a single degenerate point on a fresh load.
    """
    pool = get_datalake_gold_pool(request)
    today = _today_clamped()
    if range:
        s, e = _resolve_range(range, start_date, end_date)
    else:
        # legacy default: 12 weeks back (Monday of week 11 weeks ago → today)
        week_start_today = today - timedelta(days=today.weekday())
        s = week_start_today - timedelta(weeks=11)
        e = today
    team_list = _parse_teams(teams)
    company_list = _parse_companies(companies)

    params: list = []
    where_open = _scope_where(
        "c", team_list, company_list, OPEN_STATUSES, customer, contract_type, params,
        customers=_parse_customers(customers), customer_mode=customer_mode,
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
        c.dest_actual_arrival,
        c.dest_actual_departure
      FROM public.mcleod_gld_cashflow c
      WHERE {where_open} AND {date_frag}
    )
    SELECT
      wk,
      -- denominators kept separate per KPI (different status/sentinel filters).
      -- Bruno R4 PDF 2026-05-26: delivery now D,P + arrival guard (base is
      -- already status IN ('D','P') via OPEN_STATUSES) to match the headline %.
      COUNT(DISTINCT id) FILTER (
        WHERE bill_date>'2000-01-01'::date
          AND dest_actual_arrival>'2000-01-01'::date
          AND dest_actual_departure>'2000-01-01'::date
      ) AS d_n_del,
      COUNT(DISTINCT id) FILTER (
        WHERE bill_date>'2000-01-01'::date
          AND dest_actual_arrival>'2000-01-01'::date
          AND dest_actual_departure>'2000-01-01'::date
          AND (bill_date::date - dest_actual_departure::date) <= 2
      ) AS d_le_del,
      COUNT(DISTINCT id) FILTER (
        WHERE bill_date>'2000-01-01'::date
          AND bol_recv_date>'2000-01-01'::date
      ) AS d_n_bol,
      COUNT(DISTINCT id) FILTER (
        WHERE bill_date>'2000-01-01'::date
          AND bol_recv_date>'2000-01-01'::date
          AND (bill_date::date - bol_recv_date::date) <= 1
      ) AS d_le_bol,
      COUNT(DISTINCT id) FILTER (
        WHERE bill_date>'2000-01-01'::date
          AND invoice_recv_date>'2000-01-01'::date
      ) AS d_n_inv,
      COUNT(DISTINCT id) FILTER (
        WHERE bill_date>'2000-01-01'::date
          AND invoice_recv_date>'2000-01-01'::date
          AND (bill_date::date - invoice_recv_date::date) <= 1
      ) AS d_le_inv
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
            "del_bill_le2": [pct(r["d_le_del"], r["d_n_del"]) for r in rows],
            "bol_bill_le1": [pct(r["d_le_bol"], r["d_n_bol"]) for r in rows],
            "carrinv_bill_le1": [pct(r["d_le_inv"], r["d_n_inv"]) for r in rows],
        },
    }


# ---------------------------------------------------------------------------
# Monthly timing trend — combo chart behind the KPI "+" pop-up
# ---------------------------------------------------------------------------


@router.get("/timing-monthly")
async def timing_monthly(
    request: Request,
    grain: str = Query("month"),
    teams: Optional[str] = Query(None),
    companies: Optional[str] = Query(None),
    customer: Optional[str] = Query(None),
    customers: Optional[str] = Query(None),
    customer_mode: str = Query("include"),
    contract_type: Optional[str] = Query(None),
    _user: dict = Depends(require_report_access("admin-cashflow")),
):
    """Bruno Aging "+" pop-up (PDF 2026-06-22): per-KPI monthly combo chart.

    For each of the 3 discipline KPIs the pop-up shows a bar (total orders in
    the metric's universe) plus a green line (within threshold) and a red line
    (over threshold). Bucket = calendar month of ``origin_actual_arrival``.

    Unlike the headline KPIs / sparklines this view is deliberately NOT scoped
    to the page date range — a monthly trend needs many months, and an MTD
    range would collapse to a single bar. It spans a fixed trailing 13 months
    (12 full months + the current partial one) and honours only the scope
    filters (teams / companies / customer / contract). A continuous month axis
    is guaranteed via ``generate_series`` so empty months still render.

    Metric denominators + within-threshold predicates are kept identical to the
    /kpis percentages so the bar totals reconcile with the card values:
      * del     — bill,arrival,departure set;     within = bill − departure ≤ 2
      * bol     — bill,bol_recv set;              within = bill − bol_recv ≤ 1
      * carrinv — bill,invoice_recv set;          within = bill − invoice ≤ 1
    """
    pool = get_datalake_gold_pool(request)
    today = _today_clamped()
    # Bruno Aging R (PDF 2026-07-13): grain toggle — Month (trailing 13 months)
    # or Week (trailing 13 ISO weeks; the modal defaults the brush to the last
    # 8). Both anchor a continuous axis via generate_series so empty buckets
    # still render, and both honour only the scope filters (not the page range).
    grain = (grain or "month").lower()
    if grain not in ("week", "month"):
        grain = "month"

    if grain == "week":
        # Bruno Aging (PDF 2026-07-20): 13 full weeks back through the current
        # (partial) week — 14 buckets, so the "+" Table view can list 14 weeks.
        cur_bucket = today - timedelta(days=today.weekday())  # Monday of this week
        first_bucket = cur_bucket - timedelta(weeks=13)
        trunc, gs_interval = "week", "1 week"
    else:
        # 12 full months back through the current (partial) month — 13 buckets.
        cur_bucket = date(today.year, today.month, 1)
        first_bucket = cur_bucket
        for _ in range(12):
            prev = first_bucket - timedelta(days=1)
            first_bucket = date(prev.year, prev.month, 1)
        trunc, gs_interval = "month", "1 month"

    s, e = first_bucket, today
    team_list = _parse_teams(teams)
    company_list = _parse_companies(companies)

    params: list = []
    where_open = _scope_where(
        "c", team_list, company_list, OPEN_STATUSES, customer, contract_type, params,
        customers=_parse_customers(customers), customer_mode=customer_mode,
    )
    date_frag = _date_fragment("c", s, e, params)
    # generate_series bounds (grain-truncated) — own params, distinct from the
    # half-open date_frag window above.
    params.append(first_bucket)
    p_gs_start = len(params)
    params.append(cur_bucket)
    p_gs_end = len(params)

    sql = f"""
    WITH base AS (
      SELECT
        date_trunc('{trunc}', c.origin_actual_arrival)::date AS mon,
        c.id,
        c.bill_date,
        c.bol_recv_date,
        c.invoice_recv_date,
        c.dest_actual_arrival,
        c.dest_actual_departure
      FROM public.mcleod_gld_cashflow c
      WHERE {where_open} AND {date_frag}
    ),
    agg AS (
      SELECT
        mon,
        COUNT(DISTINCT id) FILTER (
          WHERE bill_date>'2000-01-01'::date
            AND dest_actual_arrival>'2000-01-01'::date
            AND dest_actual_departure>'2000-01-01'::date
        ) AS del_total,
        COUNT(DISTINCT id) FILTER (
          WHERE bill_date>'2000-01-01'::date
            AND dest_actual_arrival>'2000-01-01'::date
            AND dest_actual_departure>'2000-01-01'::date
            AND (bill_date::date - dest_actual_departure::date) <= 2
        ) AS del_within,
        COUNT(DISTINCT id) FILTER (
          WHERE bill_date>'2000-01-01'::date
            AND bol_recv_date>'2000-01-01'::date
        ) AS bol_total,
        COUNT(DISTINCT id) FILTER (
          WHERE bill_date>'2000-01-01'::date
            AND bol_recv_date>'2000-01-01'::date
            AND (bill_date::date - bol_recv_date::date) <= 1
        ) AS bol_within,
        COUNT(DISTINCT id) FILTER (
          WHERE bill_date>'2000-01-01'::date
            AND invoice_recv_date>'2000-01-01'::date
        ) AS inv_total,
        COUNT(DISTINCT id) FILTER (
          WHERE bill_date>'2000-01-01'::date
            AND invoice_recv_date>'2000-01-01'::date
            AND (bill_date::date - invoice_recv_date::date) <= 1
        ) AS inv_within,
        -- Bruno Aging (PDF 2026-07-20): AVG days per bucket for the "+" Table
        -- view. Same universe as the matching % so it reconciles with the card.
        AVG(bill_date::date - dest_actual_departure::date) FILTER (
          WHERE bill_date>'2000-01-01'::date
            AND dest_actual_arrival>'2000-01-01'::date
            AND dest_actual_departure>'2000-01-01'::date
        ) AS del_avg,
        AVG(bill_date::date - bol_recv_date::date) FILTER (
          WHERE bill_date>'2000-01-01'::date
            AND bol_recv_date>'2000-01-01'::date
        ) AS bol_avg,
        AVG(bill_date::date - invoice_recv_date::date) FILTER (
          WHERE bill_date>'2000-01-01'::date
            AND invoice_recv_date>'2000-01-01'::date
        ) AS inv_avg
      FROM base
      GROUP BY mon
    ),
    months AS (
      SELECT generate_series(${p_gs_start}::date, ${p_gs_end}::date,
                             INTERVAL '{gs_interval}')::date AS mon
    )
    SELECT
      m.mon,
      COALESCE(a.del_total, 0)  AS del_total,
      COALESCE(a.del_within, 0) AS del_within,
      COALESCE(a.bol_total, 0)  AS bol_total,
      COALESCE(a.bol_within, 0) AS bol_within,
      COALESCE(a.inv_total, 0)  AS inv_total,
      COALESCE(a.inv_within, 0) AS inv_within,
      a.del_avg,
      a.bol_avg,
      a.inv_avg
    FROM months m
    LEFT JOIN agg a USING (mon)
    ORDER BY m.mon
    """
    rows = await pool.fetch(sql, *params)

    def series(total_col: str, within_col: str, avg_col: str) -> dict:
        total = [int(r[total_col] or 0) for r in rows]
        within = [int(r[within_col] or 0) for r in rows]
        over = [t - w for t, w in zip(total, within)]
        avg_days = [float(r[avg_col]) if r[avg_col] is not None else None for r in rows]
        return {"total": total, "within": within, "over": over, "avg_days": avg_days}

    return {
        "success": True,
        "data": {
            "grain": grain,
            "months": [r["mon"].isoformat() for r in rows],
            "del": series("del_total", "del_within", "del_avg"),
            "bol": series("bol_total", "bol_within", "bol_avg"),
            "carrinv": series("inv_total", "inv_within", "inv_avg"),
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
    # Bruno R4 PDF 2026-05-26: sort Customer + Days
    "customer_asc": "customer_name ASC NULLS LAST",
    "customer_desc": "customer_name DESC NULLS LAST",
    "days_asc": "days_since_delivery ASC NULLS LAST",
    "days_desc": "days_since_delivery DESC NULLS LAST",
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
    customers: Optional[str] = Query(None),
    customer_mode: str = Query("include"),
    contract_type: Optional[str] = Query(None),
    order_q: Optional[str] = Query(None),
    customer_q: Optional[str] = Query(None),
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
        "c", team_list, company_list, DELIVERED_ONLY, customer, contract_type, params,
        customers=_parse_customers(customers), customer_mode=customer_mode,
    )
    date_frag = _date_fragment("c", s, e, params)
    oc_frag = _order_customer_filter("c", order_q, customer_q, params)
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
      WHERE {where} AND {date_frag}{oc_frag}
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
            WHERE  {where} AND {date_frag}{oc_frag}
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
    # Bruno R4 PDF 2026-05-26: sort Customer + BOL Recv + Status + Days
    "status_desc": "status DESC, ship_date ASC NULLS LAST",
    "customer_asc": "customer_name ASC NULLS LAST",
    "customer_desc": "customer_name DESC NULLS LAST",
    "bol_asc": "bol_recv_date ASC NULLS LAST",
    "bol_desc": "bol_recv_date DESC NULLS LAST",
    "days_asc": "days_since_bol_recv ASC NULLS LAST",
    "days_desc": "days_since_bol_recv DESC NULLS LAST",
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
    customers: Optional[str] = Query(None),
    customer_mode: str = Query("include"),
    contract_type: Optional[str] = Query(None),
    order_q: Optional[str] = Query(None),
    customer_q: Optional[str] = Query(None),
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
        "c", team_list, company_list, OPEN_STATUSES, customer, contract_type, params,
        customers=_parse_customers(customers), customer_mode=customer_mode,
    )
    date_frag = _date_fragment("c", s, e, params)
    oc_frag = _order_customer_filter("c", order_q, customer_q, params)
    params.extend([limit, offset])
    p_lim, p_off = len(params) - 1, len(params)

    # Bruno R3 PDF 2026-05-19: DAYS column reflects today - bol_recv_date
    # (aging of the BOL document, not aging of the ship date).
    sql = f"""
    WITH base AS (
      SELECT
        c.id,
        c.orig_orig_sched_early   AS orig_sched_early,
        c.origin_actual_arrival   AS ship_date,
        c.bol_recv_date,
        c.status,
        c.customer_name,
        c.team_id,
        c.company_id,
        c.total_charge,
        CASE
          WHEN c.bol_recv_date > '2000-01-01'::date
          THEN ((now() AT TIME ZONE 'America/Chicago')::date
                - c.bol_recv_date::date)
          ELSE NULL
        END AS days_since_bol_recv
      FROM public.mcleod_gld_cashflow c
      WHERE {where} AND {date_frag}{oc_frag}
        AND c.bill_date < '2000-01-01'::date
        AND TRIM(c.ready_to_bill) = 'Y'
    )
    SELECT
      id, orig_sched_early, ship_date, bol_recv_date, status,
      customer_name, team_id, company_id, total_charge, days_since_bol_recv,
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
            "bol_recv_date": r["bol_recv_date"].isoformat() if r["bol_recv_date"] else None,
            "status": (r["status"] or "").strip(),
            "customer_name": (r["customer_name"] or "").strip(),
            "team_id": (r["team_id"] or "").strip(),
            "company_id": (r["company_id"] or "").strip(),
            "total_charge": float(r["total_charge"] or 0),
            "days_since_bol_recv": int(r["days_since_bol_recv"]) if r["days_since_bol_recv"] is not None else None,
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
    # Bruno R4 PDF 2026-05-26: sort every column
    "company_asc": "company_id ASC NULLS LAST",
    "company_desc": "company_id DESC NULLS LAST",
    "team_asc": "team_id ASC NULLS LAST",
    "team_desc": "team_id DESC NULLS LAST",
    "customer_asc": "customer_name ASC NULLS LAST",
    "customer_desc": "customer_name DESC NULLS LAST",
    "left_asc": "left_date ASC NULLS LAST",
    "left_desc": "left_date DESC NULLS LAST",
    "bill_asc": "bill_date ASC NULLS LAST",
    "bill_desc": "bill_date DESC NULLS LAST",
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
    customers: Optional[str] = Query(None),
    customer_mode: str = Query("include"),
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
    threshold = 2  # Bruno R3 PDF 2026-05-19: KPI now ≤2d (was ≤10d)

    params: list = []
    where = _scope_where(
        "c", team_list, company_list, OPEN_STATUSES, customer, contract_type, params,
        customers=_parse_customers(customers), customer_mode=customer_mode,
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
    customers: Optional[str] = Query(None),
    customer_mode: str = Query("include"),
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
    threshold = 1  # Bruno R3 PDF 2026-05-19: KPI now ≤1d (was ≤2d)

    params: list = []
    where = _scope_where(
        "c", team_list, company_list, OPEN_STATUSES, customer, contract_type, params,
        customers=_parse_customers(customers), customer_mode=customer_mode,
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
    customers: Optional[str] = Query(None),
    customer_mode: str = Query("include"),
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
    threshold = 1  # Bruno R3 PDF 2026-05-19: KPI now ≤1d (was ≤2d); direction flipped below

    params: list = []
    where = _scope_where(
        "c", team_list, company_list, OPEN_STATUSES, customer, contract_type, params,
        customers=_parse_customers(customers), customer_mode=customer_mode,
    )
    date_frag = _date_fragment("c", s, e, params)
    params.extend([limit, offset])
    p_lim, p_off = len(params) - 1, len(params)

    # Direction flipped (Bruno R3 PDF): days(bill_date) - days(inv_recv_date).
    sql = f"""
    WITH base AS (
      SELECT
        c.id, c.company_id, c.team_id, c.customer_name,
        c.invoice_recv_date                                  AS left_date,
        c.bill_date,
        c.origin_actual_arrival,
        c.total_charge,
        (c.bill_date::date - c.invoice_recv_date::date)      AS days
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
    customers: Optional[str] = Query(None),
    customer_mode: str = Query("include"),
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
        "c", team_list, company_list, OPEN_STATUSES, customer, contract_type, params,
        customers=_parse_customers(customers), customer_mode=customer_mode,
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
    customers: Optional[str] = Query(None),
    customer_mode: str = Query("include"),
    contract_type: Optional[str] = Query(None),
    limit: int = Query(10, ge=1, le=50),
    _user: dict = Depends(require_report_access("admin-cashflow")),
):
    """Customers ranked by $ revenue on loads where bill - delivery > 2 days.

    Bruno Aging R (PDF 2026-07-13): the "late" threshold was lowered from
    >10 days to >2 days. Kept as a single constant so the three FILTER sites
    (n_late / late_revenue / HAVING) can never drift apart.
    """
    pool = get_datalake_gold_pool(request)
    s, e = _resolve_range(range, start_date, end_date)
    team_list = _parse_teams(teams)
    company_list = _parse_companies(companies)
    late_days = 2  # Bruno Aging R (PDF 2026-07-13): was 10

    params: list = []
    where = _scope_where(
        "c", team_list, company_list, OPEN_STATUSES, customer, contract_type, params,
        customers=_parse_customers(customers), customer_mode=customer_mode,
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
      COUNT(*)                                       AS n_loads,
      COUNT(*) FILTER (WHERE days > {late_days})      AS n_late,
      COALESCE(SUM(total_charge) FILTER (WHERE days > {late_days}), 0)::numeric  AS late_revenue,
      COALESCE(AVG(days), 0)::numeric                 AS avg_days
    FROM base
    GROUP BY customer_name
    HAVING COUNT(*) FILTER (WHERE days > {late_days}) > 0
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


# ---------------------------------------------------------------------------
# CSV exports — one per Bruno-requested table (round-2 feedback 2026-05-13)
# ---------------------------------------------------------------------------


def _csv_response(filename: str, header: list[str], rows: Iterable[list]) -> Response:
    buf = io.StringIO()
    writer = csv.writer(buf, lineterminator="\n")
    writer.writerow(header)
    for r in rows:
        writer.writerow(r)
    return Response(
        content=buf.getvalue(),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


def _iso(d) -> str:
    return d.isoformat() if d else ""


def _csv_filename(stub: str, s: date, e: date) -> str:
    return f"admin-cashflow_{stub}_{s.isoformat()}_to_{e.isoformat()}.csv"


@router.get("/delivered-not-billed.csv")
async def delivered_not_billed_csv(
    request: Request,
    range: Optional[str] = Query("mtd"),
    start_date: Optional[date] = Query(None),
    end_date: Optional[date] = Query(None),
    teams: Optional[str] = Query(None),
    companies: Optional[str] = Query(None),
    customer: Optional[str] = Query(None),
    customers: Optional[str] = Query(None),
    customer_mode: str = Query("include"),
    contract_type: Optional[str] = Query(None),
    order_q: Optional[str] = Query(None),
    customer_q: Optional[str] = Query(None),
    sort: str = Query("delivered_asc"),
    _user: dict = Depends(require_report_access("admin-cashflow")),
):
    pool = get_datalake_gold_pool(request)
    s, e = _resolve_range(range, start_date, end_date)
    team_list = _parse_teams(teams)
    company_list = _parse_companies(companies)
    order_by = _DELIVERED_NOT_BILLED_SORTS.get(sort, "dest_actual_arrival ASC NULLS LAST")

    params: list = []
    where = _scope_where(
        "c", team_list, company_list, DELIVERED_ONLY, customer, contract_type, params,
        customers=_parse_customers(customers), customer_mode=customer_mode,
    )
    date_frag = _date_fragment("c", s, e, params)
    oc_frag = _order_customer_filter("c", order_q, customer_q, params)

    sql = f"""
    SELECT
      c.id,
      c.company_id,
      c.team_id,
      c.customer_name,
      c.orig_orig_sched_early                  AS orig_sched_early,
      c.origin_actual_arrival                  AS ship_date,
      c.dest_actual_arrival,
      c.total_charge,
      CASE
        WHEN c.dest_actual_arrival > '2000-01-01'::date
        THEN ((now() AT TIME ZONE 'America/Chicago')::date
              - c.dest_actual_arrival::date)
        ELSE NULL
      END AS days_since_delivery
    FROM public.mcleod_gld_cashflow c
    WHERE {where} AND {date_frag}{oc_frag}
      AND c.bill_date < '2000-01-01'::date
    ORDER BY {order_by}
    """
    rows = await pool.fetch(sql, *params)
    header = [
        "Order", "Company", "Team", "Customer",
        "Orig Sched Early", "Ship Date", "Delivered",
        "Days Since Delivery", "Revenue (USD)",
    ]
    body = (
        [
            (r["id"] or "").strip(),
            (r["company_id"] or "").strip(),
            (r["team_id"] or "").strip(),
            (r["customer_name"] or "").strip(),
            _iso(r["orig_sched_early"]),
            _iso(r["ship_date"]),
            _iso(r["dest_actual_arrival"]),
            r["days_since_delivery"] if r["days_since_delivery"] is not None else "",
            float(r["total_charge"] or 0),
        ]
        for r in rows
    )
    return _csv_response(_csv_filename("delivered-not-billed", s, e), header, body)


@router.get("/ready-not-billed.csv")
async def ready_not_billed_csv(
    request: Request,
    range: Optional[str] = Query("mtd"),
    start_date: Optional[date] = Query(None),
    end_date: Optional[date] = Query(None),
    teams: Optional[str] = Query(None),
    companies: Optional[str] = Query(None),
    customer: Optional[str] = Query(None),
    customers: Optional[str] = Query(None),
    customer_mode: str = Query("include"),
    contract_type: Optional[str] = Query(None),
    order_q: Optional[str] = Query(None),
    customer_q: Optional[str] = Query(None),
    sort: str = Query("ship_asc"),
    _user: dict = Depends(require_report_access("admin-cashflow")),
):
    pool = get_datalake_gold_pool(request)
    s, e = _resolve_range(range, start_date, end_date)
    team_list = _parse_teams(teams)
    company_list = _parse_companies(companies)
    order_by = _READY_NOT_BILLED_SORTS.get(sort, "ship_date ASC NULLS LAST")

    params: list = []
    where = _scope_where(
        "c", team_list, company_list, OPEN_STATUSES, customer, contract_type, params,
        customers=_parse_customers(customers), customer_mode=customer_mode,
    )
    date_frag = _date_fragment("c", s, e, params)
    oc_frag = _order_customer_filter("c", order_q, customer_q, params)

    # Bruno R3 PDF 2026-05-19: DAYS column now = today - bol_recv_date.
    sql = f"""
    SELECT
      c.id,
      c.company_id,
      c.team_id,
      c.customer_name,
      c.orig_orig_sched_early   AS orig_sched_early,
      c.origin_actual_arrival   AS ship_date,
      c.bol_recv_date,
      c.status,
      c.total_charge,
      CASE
        WHEN c.bol_recv_date > '2000-01-01'::date
        THEN ((now() AT TIME ZONE 'America/Chicago')::date
              - c.bol_recv_date::date)
        ELSE NULL
      END AS days_since_bol_recv
    FROM public.mcleod_gld_cashflow c
    WHERE {where} AND {date_frag}{oc_frag}
      AND c.bill_date < '2000-01-01'::date
      AND TRIM(c.ready_to_bill) = 'Y'
    ORDER BY {order_by}
    """
    rows = await pool.fetch(sql, *params)
    header = [
        "Order", "Company", "Team", "Customer",
        "Ship Date", "Orig Sched Early", "BOL Recv", "Status",
        "Days Since BOL Recv", "Revenue (USD)",
    ]
    body = (
        [
            (r["id"] or "").strip(),
            (r["company_id"] or "").strip(),
            (r["team_id"] or "").strip(),
            (r["customer_name"] or "").strip(),
            _iso(r["ship_date"]),
            _iso(r["orig_sched_early"]),
            _iso(r["bol_recv_date"]),
            (r["status"] or "").strip(),
            r["days_since_bol_recv"] if r["days_since_bol_recv"] is not None else "",
            float(r["total_charge"] or 0),
        ]
        for r in rows
    )
    return _csv_response(_csv_filename("ready-not-billed", s, e), header, body)


async def _aging_csv(
    pool,
    *,
    s: date,
    e: date,
    team_list: list[str],
    company_list: list[str],
    customer: Optional[str],
    customers: Optional[str],
    customer_mode: str,
    contract_type: Optional[str],
    sort: str,
    left_col_sql: str,
    days_sql: str,
    extra_filters: str,
    left_col_label: str,
    stub: str,
) -> Response:
    order_by = _AGING_SORTS.get(sort, "days DESC NULLS LAST")
    params: list = []
    where = _scope_where(
        "c", team_list, company_list, OPEN_STATUSES, customer, contract_type, params,
        customers=_parse_customers(customers), customer_mode=customer_mode,
    )
    date_frag = _date_fragment("c", s, e, params)

    sql = f"""
    SELECT
      c.id, c.company_id, c.team_id, c.customer_name,
      {left_col_sql}                       AS left_date,
      c.bill_date,
      c.origin_actual_arrival,
      c.total_charge,
      {days_sql}                           AS days
    FROM public.mcleod_gld_cashflow c
    WHERE {where} AND {date_frag} {extra_filters}
    ORDER BY {order_by}
    """
    rows = await pool.fetch(sql, *params)
    header = [
        "Company", "Team", "Order", "Customer",
        left_col_label, "Bill Date", "Days", "Revenue (USD)",
    ]
    body = (
        [
            (r["company_id"] or "").strip(),
            (r["team_id"] or "").strip(),
            (r["id"] or "").strip(),
            (r["customer_name"] or "").strip(),
            _iso(r["left_date"]),
            _iso(r["bill_date"]),
            int(r["days"]) if r["days"] is not None else "",
            float(r["total_charge"] or 0),
        ]
        for r in rows
    )
    return _csv_response(_csv_filename(stub, s, e), header, body)


@router.get("/aging/delivery-vs-bill.csv")
async def aging_delivery_vs_bill_csv(
    request: Request,
    range: Optional[str] = Query("mtd"),
    start_date: Optional[date] = Query(None),
    end_date: Optional[date] = Query(None),
    teams: Optional[str] = Query(None),
    companies: Optional[str] = Query(None),
    customer: Optional[str] = Query(None),
    customers: Optional[str] = Query(None),
    customer_mode: str = Query("include"),
    contract_type: Optional[str] = Query(None),
    sort: str = Query("days_desc"),
    _user: dict = Depends(require_report_access("admin-cashflow")),
):
    pool = get_datalake_gold_pool(request)
    s, e = _resolve_range(range, start_date, end_date)
    return await _aging_csv(
        pool,
        s=s, e=e,
        team_list=_parse_teams(teams),
        company_list=_parse_companies(companies),
        customer=customer, customers=customers, customer_mode=customer_mode,
        contract_type=contract_type,
        sort=sort,
        left_col_sql="c.dest_actual_departure",
        days_sql="(c.bill_date::date - c.dest_actual_departure::date)",
        extra_filters=(
            " AND c.bill_date              > '2000-01-01'::date"
            " AND c.dest_actual_arrival    > '2000-01-01'::date"
            " AND c.dest_actual_departure  > '2000-01-01'::date"
        ),
        left_col_label="Dest Departure",
        stub="delivery-vs-bill",
    )


@router.get("/aging/bol-vs-bill.csv")
async def aging_bol_vs_bill_csv(
    request: Request,
    range: Optional[str] = Query("mtd"),
    start_date: Optional[date] = Query(None),
    end_date: Optional[date] = Query(None),
    teams: Optional[str] = Query(None),
    companies: Optional[str] = Query(None),
    customer: Optional[str] = Query(None),
    customers: Optional[str] = Query(None),
    customer_mode: str = Query("include"),
    contract_type: Optional[str] = Query(None),
    sort: str = Query("days_desc"),
    _user: dict = Depends(require_report_access("admin-cashflow")),
):
    pool = get_datalake_gold_pool(request)
    s, e = _resolve_range(range, start_date, end_date)
    return await _aging_csv(
        pool,
        s=s, e=e,
        team_list=_parse_teams(teams),
        company_list=_parse_companies(companies),
        customer=customer, customers=customers, customer_mode=customer_mode,
        contract_type=contract_type,
        sort=sort,
        left_col_sql="c.bol_recv_date",
        days_sql="(c.bill_date::date - c.bol_recv_date::date)",
        extra_filters=(
            " AND c.bill_date     > '2000-01-01'::date"
            " AND c.bol_recv_date > '2000-01-01'::date"
        ),
        left_col_label="BOL Recv",
        stub="bol-vs-bill",
    )


@router.get("/aging/carrinv-vs-bill.csv")
async def aging_carrinv_vs_bill_csv(
    request: Request,
    range: Optional[str] = Query("mtd"),
    start_date: Optional[date] = Query(None),
    end_date: Optional[date] = Query(None),
    teams: Optional[str] = Query(None),
    companies: Optional[str] = Query(None),
    customer: Optional[str] = Query(None),
    customers: Optional[str] = Query(None),
    customer_mode: str = Query("include"),
    contract_type: Optional[str] = Query(None),
    sort: str = Query("days_desc"),
    _user: dict = Depends(require_report_access("admin-cashflow")),
):
    pool = get_datalake_gold_pool(request)
    s, e = _resolve_range(range, start_date, end_date)
    return await _aging_csv(
        pool,
        s=s, e=e,
        team_list=_parse_teams(teams),
        company_list=_parse_companies(companies),
        customer=customer, customers=customers, customer_mode=customer_mode,
        contract_type=contract_type,
        sort=sort,
        left_col_sql="c.invoice_recv_date",
        # Bruno R3 PDF 2026-05-19: direction flipped → days(bill_date) - days(inv_recv_date).
        days_sql="(c.bill_date::date - c.invoice_recv_date::date)",
        extra_filters=(
            " AND c.bill_date         > '2000-01-01'::date"
            " AND c.invoice_recv_date > '2000-01-01'::date"
        ),
        left_col_label="Inv Recv",
        stub="carrinv-vs-bill",
    )
