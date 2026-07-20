"""Code-made report: DFW Losses — daily loss table for the DFW division.

Bruno's PDF spec. A portal-native, read-only report hard-scoped to the
single team ``team_id = 'TEAM-DFW'``. Every panel reads from
``public.mcleod_gld_budget_report_v4`` (datalake gold).

Two panels:
- ``/daily``  — one row per calendar day in the selected range, with the
  day's loads, amount lost, loss/load and a per-customer loss pivot.
- ``/lanes``  — "Biggest Offender Lane" table grouped by origin/dest.

Scope (applied everywhere, mirrors ``losses_lanes.py``):
- team_id      = 'TEAM-DFW'  (single team — no team selector)
- company_id   IN (TMS, TMS3)
- status       IN (D, P)
- customer_name NOT LIKE '%UNILINK%' AND NOT LIKE '%OILTEX%'

All scope varchar columns use the padded-variants pattern
(``pad_variants(width=N)``) so btree indexes stay usable — never TRIM()
team_id/company_id/status inside WHERE/JOIN. The date bound is sargable
(``>= $s AND < ($e::date + INTERVAL '1 day')``) so ``idx_v4_dep`` on the
raw timestamp stays usable — never ::date-cast the indexed column in the
bound. Dates are bound as python ``date`` objects, never strings.
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, Query, Request

from app.clock import cst_today
from app.datalake import pad_variants as _pad_variants
from app.routers.deps import get_datalake_gold_pool, require_report_access

YEAR_START = date(2026, 1, 1)
YEAR_END = date(2026, 12, 31)

DFW_TEAM = "TEAM-DFW"
DFW_TEAMS = (DFW_TEAM,)
COMPANIES = ("TMS", "TMS3")
OPEN_STATUSES = ("D", "P")

# Cap on the number of per-customer columns in the /daily pivot.
CUSTOMER_CAP = 25

router = APIRouter(tags=["dfw-losses"], prefix="/custom/dfw-losses")


# ---------------------------------------------------------------------------
# Range helpers (clone of losses_lanes + a WTD branch)
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
    """Return (this_month_start, this_month_end, last_month_start, last_month_end)."""
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
    """Expand the range selector (MTD / WTD / Last Month / YTD / Custom)."""
    today = cst_today()
    today_clamped = max(YEAR_START, min(YEAR_END, today))
    m_start, _m_end, lm_start, lm_end = _month_bounds(today)
    if rng == "wtd":
        monday = today - timedelta(days=today.weekday())
        return _clamp(monday, YEAR_START), today_clamped
    if rng == "last_month":
        return _clamp(lm_start, YEAR_START), _clamp(lm_end, YEAR_END)
    if rng == "ytd" or rng == "this_year":
        return YEAR_START, today_clamped
    if rng == "custom":
        s = _clamp(start_date, YEAR_START)
        e = _clamp(end_date, YEAR_END)
        if e < s:
            s, e = e, s
        return s, e
    # default: MTD
    return _clamp(m_start, YEAR_START), today_clamped


def _parse_multi(raw: Optional[list[str]]) -> list[str]:
    """FastAPI repeated-param list -> cleaned list (drop blanks, dedupe)."""
    if not raw:
        return []
    seen: set[str] = set()
    out: list[str] = []
    for v in raw:
        for part in (v or "").split(","):
            val = part.strip()
            if val and val not in seen:
                seen.add(val)
                out.append(val)
    return out


def _scope_where(
    alias: str,
    contract_types: list[str],
    customers: list[str],
    params: list,
) -> str:
    """Common WHERE fragment for the DFW-scoped v4 table.

    Appends positional params onto ``params`` and returns the SQL snippet.
    Team/company/status use sargable ``= ANY($N)`` with padded variants.
    Contract/customer filters are optional multi-selects.
    """
    params.append(_pad_variants(DFW_TEAMS, width=8))
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
    if contract_types:
        # contract_type is varchar(1); pad_variants(width=1) is a no-op but
        # keeps the pattern consistent and sargable.
        params.append(_pad_variants(contract_types, width=1))
        parts.append(f"{alias}.contract_type = ANY(${len(params)})")
    if customers:
        # customer_name is not a scope index column, so TRIM-matching here is
        # fine and matches the TRIM'd values /filters and /daily return.
        params.append(customers)
        parts.append(f"TRIM({alias}.customer_name) = ANY(${len(params)})")
    return " AND ".join(parts)


# ---------------------------------------------------------------------------
# Filters — distinct contract_type + customer_name for TEAM-DFW in window
# ---------------------------------------------------------------------------


@router.get("/filters")
async def filters(
    request: Request,
    range: Optional[str] = Query("mtd"),
    start_date: Optional[date] = Query(None),
    end_date: Optional[date] = Query(None),
    _user: dict = Depends(require_report_access("dfw-losses")),
):
    """Distinct contract_type + customer_name values within the current window."""
    pool = get_datalake_gold_pool(request)
    s, e = _resolve_range(range, start_date, end_date)

    params: list = [
        _pad_variants(DFW_TEAMS, width=8),
        _pad_variants(COMPANIES, width=4),
        _pad_variants(OPEN_STATUSES, width=1),
        s,
        e,
    ]
    rows = await pool.fetch(
        """
        SELECT DISTINCT
          NULLIF(TRIM(customer_name), '') AS customer_name,
          NULLIF(TRIM(contract_type), '') AS contract_type
        FROM public.mcleod_gld_budget_report_v4
        WHERE team_id    = ANY($1)
          AND company_id = ANY($2)
          AND status     = ANY($3)
          AND UPPER(COALESCE(customer_name,'')) NOT LIKE '%UNILINK%'
          AND UPPER(COALESCE(customer_name,'')) NOT LIKE '%OILTEX%'
          AND origin_actual_departure >= $4
          AND origin_actual_departure < ($5::date + INTERVAL '1 day')
        """,
        *params,
    )
    customers = sorted({r["customer_name"] for r in rows if r["customer_name"]})
    contracts = sorted({r["contract_type"] for r in rows if r["contract_type"]})
    return {
        "success": True,
        "data": {
            "contract_types": contracts,
            "customers": customers,
            "year_start": YEAR_START.isoformat(),
            "year_end": YEAR_END.isoformat(),
            "window": {"start": s.isoformat(), "end": e.isoformat()},
        },
    }


# ---------------------------------------------------------------------------
# Daily — the main DFW Losses table (daily grain + per-customer pivot)
# ---------------------------------------------------------------------------

_MONTH_NAMES = [
    "January", "February", "March", "April", "May", "June",
    "July", "August", "September", "October", "November", "December",
]


@router.get("/daily")
async def daily(
    request: Request,
    range: Optional[str] = Query("mtd"),
    start_date: Optional[date] = Query(None),
    end_date: Optional[date] = Query(None),
    contract_type: Optional[list[str]] = Query(None),
    customer_name: Optional[list[str]] = Query(None),
    _user: dict = Depends(require_report_access("dfw-losses")),
):
    """Daily-grain loss rows across the range, with a per-customer loss pivot.

    One grouped query by (date, customer) supplies both the per-day totals
    (aggregated up in Python) and the per-customer pivot cells. Loads count
    ALL ``total_charge <> 0`` rows for the day; amount_lost sums the negative
    margins only. The averages summary is computed server-side over the full
    day-row set (never a client reduce).
    """
    pool = get_datalake_gold_pool(request)
    s, e = _resolve_range(range, start_date, end_date)
    contracts = _parse_multi(contract_type)
    customers_filter = _parse_multi(customer_name)

    params: list = []
    where = _scope_where("br4", contracts, customers_filter, params)
    params.extend([s, e])
    p_s, p_e = len(params) - 1, len(params)

    rows = await pool.fetch(
        f"""
        SELECT
          br4.origin_actual_departure::date AS d,
          NULLIF(TRIM(br4.customer_name), '') AS customer,
          COUNT(*) FILTER (WHERE br4.total_charge <> 0) AS loads,
          COALESCE(
            SUM(br4.margin_amt) FILTER (WHERE br4.margin_amt < 0), 0
          )::numeric AS lost
        FROM public.mcleod_gld_budget_report_v4 br4
        WHERE {where}
          AND br4.origin_actual_departure >= ${p_s}
          AND br4.origin_actual_departure < (${p_e}::date + INTERVAL '1 day')
        GROUP BY br4.origin_actual_departure::date, NULLIF(TRIM(br4.customer_name), '')
        """,
        *params,
    )

    # Aggregate up in Python.
    per_day: dict[date, dict] = {}
    customer_totals: dict[str, float] = {}
    for r in rows:
        d = r["d"]
        cust = r["customer"] or "(blank)"
        loads = int(r["loads"] or 0)
        lost = float(r["lost"] or 0.0)

        day = per_day.setdefault(
            d, {"loads": 0, "amount_lost": 0.0, "by_customer": {}}
        )
        day["loads"] += loads
        day["amount_lost"] += lost
        # accumulate per-customer loss for the day (sum in case of "(blank)")
        day["by_customer"][cust] = day["by_customer"].get(cust, 0.0) + lost
        customer_totals[cust] = customer_totals.get(cust, 0.0) + lost

    # Ordered customer columns: biggest losers first (most-negative total).
    ordered_customers = sorted(
        customer_totals.keys(), key=lambda c: (customer_totals[c], c)
    )
    customers_truncated = len(ordered_customers) > CUSTOMER_CAP
    ordered_customers = ordered_customers[:CUSTOMER_CAP]
    kept = set(ordered_customers)

    out_rows = []
    for d in sorted(per_day.keys()):
        day = per_day[d]
        loads = day["loads"]
        amount_lost = day["amount_lost"]
        loss_per_load = (amount_lost / loads) if loads else None
        by_customer = {
            c: round(day["by_customer"].get(c, 0.0), 2)
            for c in ordered_customers
            if c in kept
        }
        out_rows.append(
            {
                "date": d.isoformat(),
                "day": d.day,
                "month": _MONTH_NAMES[d.month - 1],
                "loads": loads,
                "amount_lost": round(amount_lost, 2),
                "loss_per_load": round(loss_per_load, 2) if loss_per_load is not None else None,
                "by_customer": by_customer,
            }
        )

    # Averages across the day-rows (server-side pinned totals).
    n = len(out_rows)
    if n:
        loads_avg = sum(r["loads"] for r in out_rows) / n
        amount_lost_avg = sum(r["amount_lost"] for r in out_rows) / n
        lpl_vals = [r["loss_per_load"] for r in out_rows if r["loss_per_load"] is not None]
        loss_per_load_avg = (sum(lpl_vals) / len(lpl_vals)) if lpl_vals else None
    else:
        loads_avg = 0.0
        amount_lost_avg = 0.0
        loss_per_load_avg = None

    return {
        "success": True,
        "data": {
            "customers": ordered_customers,
            "customers_truncated": customers_truncated,
            "rows": out_rows,
            "summary": {
                "loads_avg": round(loads_avg, 2),
                "amount_lost_avg": round(amount_lost_avg, 2),
                "loss_per_load_avg": round(loss_per_load_avg, 2)
                if loss_per_load_avg is not None
                else None,
            },
            "window": {"start": s.isoformat(), "end": e.isoformat()},
        },
    }


# ---------------------------------------------------------------------------
# Lanes — "Biggest Offender Lane" (grouped by origin/dest, loss-only)
# ---------------------------------------------------------------------------


@router.get("/lanes")
async def lanes(
    request: Request,
    range: Optional[str] = Query("mtd"),
    start_date: Optional[date] = Query(None),
    end_date: Optional[date] = Query(None),
    contract_type: Optional[list[str]] = Query(None),
    customer_name: Optional[list[str]] = Query(None),
    limit: int = Query(50, ge=1, le=200),
    _user: dict = Depends(require_report_access("dfw-losses")),
):
    """Worst (most-negative) origin→dest lanes for TEAM-DFW. Loss-making only."""
    pool = get_datalake_gold_pool(request)
    s, e = _resolve_range(range, start_date, end_date)
    contracts = _parse_multi(contract_type)
    customers_filter = _parse_multi(customer_name)

    params: list = []
    where = _scope_where("br4", contracts, customers_filter, params)
    params.extend([s, e])
    p_s, p_e = len(params) - 1, len(params)
    params.append(limit)
    p_lim = len(params)

    rows = await pool.fetch(
        f"""
        SELECT
          br4.origin_name AS origin,
          br4.dest_name   AS destination,
          COUNT(*) FILTER (WHERE br4.total_charge <> 0) AS loads,
          COALESCE(
            SUM(br4.margin_amt) FILTER (WHERE br4.margin_amt < 0), 0
          )::numeric AS loss
        FROM public.mcleod_gld_budget_report_v4 br4
        WHERE {where}
          AND br4.origin_actual_departure >= ${p_s}
          AND br4.origin_actual_departure < (${p_e}::date + INTERVAL '1 day')
        GROUP BY br4.origin_name, br4.dest_name
        HAVING COALESCE(SUM(br4.margin_amt) FILTER (WHERE br4.margin_amt < 0), 0) < 0
        ORDER BY loss ASC
        LIMIT ${p_lim}
        """,
        *params,
    )
    data = [
        {
            "origin": r["origin"],
            "destination": r["destination"],
            "loads": int(r["loads"] or 0),
            "loss": float(r["loss"] or 0.0),
        }
        for r in rows
    ]
    return {
        "success": True,
        "data": data,
        "meta": {"total": len(data), "limit": limit},
    }
