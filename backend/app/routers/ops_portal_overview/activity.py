"""New Customer / Deactivated — Bruno PDF "Ops Portal Updates" 2026-11-17 R3.

Part of the ``ops_portal_overview`` package. One endpoint, two populations,
selected by ``kind`` (the panel's two-button toggle):

``kind=new`` — a customer whose FIRST charged load inside the Date window came
  after more than ``SILENCE_DAYS`` days with no load, or is its first load ever.
  ⚠ The PDF's literal wording ("the gap between the two most recent load dates
  > 75 days") drops a customer the moment it ships a second time: HILTI's first
  ever load was in Nov-2026 and it had already shipped twice, so it vanished.
  Measured over the last 90 days: 7 customers literal vs 17 with this
  "window-entry" rule. Diego chose window-entry on 2026-11-17.
  Vol / Prof / M % / Lanes are over the Date window; First Load is the first
  load EVER, Last Load the latest load up to the window end.

``kind=deactivated`` — a customer whose latest charged load is more than
  ``SILENCE_DAYS`` days before today (CST). It IGNORES the Date filter: under
  MTD no customer can be 75 days silent, so a windowed version is always empty.
  Profit = SUM(margin_amt) over the customer's last 10 charged trips.

Both read v4 through ``_v4_scope_where`` (division scope incl. the DFW revenue
code marker, §134 §135), count only charged loads (``total_charge`` set and
non-zero — the population the Customers bars and Vol use, §96) and key a
customer on ``TRIM(customer_name)`` like the /combo Customers measure.
Team + Customer filters apply. Lane / carrier / load-type filters are accepted
for API symmetry and IGNORED: a customer is not "new" or "deactivated" on one
lane, and narrowing the history would invent silences that did not happen.
"""

# FastAPI declares query params as `Query()` defaults — the idiom B008 flags.
# ruff: noqa: B008
from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import date, datetime

from fastapi import Depends, Query, Request

from app.clock import cst_today
from app.routers.deps import get_datalake_gold_pool, require_report_access

from ._constants import router
from ._dates import _resolve_range
from ._metrics import _safe_float
from ._scope import scope_of
from ._sql import _lane_expr, _v4_scope_where

SILENCE_DAYS = 75
LAST_TRIPS = 10
KINDS = ("new", "deactivated")
# v4 parks a not-yet-departed load at 1900-01-01; never let it be a "first load".
_SENTINEL_FLOOR = "2000-01-01"


def _charged_rows_sql(where: str) -> str:
    """Charged, departed, named-customer v4 rows inside the scope ``where``."""
    return f"""
        SELECT TRIM(br4.customer_name)      AS cust,
               br4.origin_actual_departure AS dep,
               br4.total_charge,
               br4.margin_amt,
               {_lane_expr("br4")}          AS lane
        FROM public.mcleod_gld_budget_report_v4 br4
        WHERE {where}
          AND br4.customer_name IS NOT NULL
          AND TRIM(br4.customer_name) <> ''
          AND br4.total_charge IS NOT NULL
          AND br4.total_charge <> 0
          AND br4.origin_actual_departure > '{_SENTINEL_FLOOR}'
    """


def new_customers_sql(where: str, p_s: int, p_e: int) -> str:
    """Window-entry rule; ``$p_s`` / ``$p_e`` are the inclusive window dates."""
    return f"""
        WITH rows_ AS (
          {_charged_rows_sql(where)}
            AND br4.origin_actual_departure < (${p_e}::date + INTERVAL '1 day')
        ),
        per AS (
          SELECT cust,
                 MIN(dep)                                  AS first_load,
                 MAX(dep)                                  AS last_load,
                 MIN(dep) FILTER (WHERE dep >= ${p_s})     AS first_in_window,
                 MAX(dep) FILTER (WHERE dep <  ${p_s})     AS last_before_window,
                 COUNT(*) FILTER (WHERE dep >= ${p_s})     AS vol,
                 SUM(margin_amt)   FILTER (WHERE dep >= ${p_s}) AS prof,
                 SUM(total_charge) FILTER (WHERE dep >= ${p_s}) AS rev,
                 ARRAY_AGG(DISTINCT lane) FILTER (WHERE dep >= ${p_s}) AS lanes
          FROM rows_
          GROUP BY cust
        )
        SELECT cust, first_load, last_load, vol, prof, rev, lanes,
               (first_in_window::date - last_before_window::date) AS gap_days
        FROM per
        WHERE first_in_window IS NOT NULL
          AND (last_before_window IS NULL
               OR first_in_window::date - last_before_window::date > {SILENCE_DAYS})
        ORDER BY first_in_window DESC, cust
    """


def deactivated_sql(where: str, p_today: int) -> str:
    """Latest load more than SILENCE_DAYS before ``$p_today``; profit of last 10."""
    return f"""
        WITH rows_ AS (
          {_charged_rows_sql(where)}
            AND br4.origin_actual_departure < (${p_today}::date + INTERVAL '1 day')
        ),
        ranked AS (
          SELECT cust, dep, margin_amt,
                 ROW_NUMBER() OVER (PARTITION BY cust ORDER BY dep DESC) AS rn
          FROM rows_
        )
        SELECT cust,
               MAX(dep)                                AS last_load,
               SUM(margin_amt) FILTER (WHERE rn <= {LAST_TRIPS}) AS profit,
               COUNT(*)        FILTER (WHERE rn <= {LAST_TRIPS}) AS trips
        FROM ranked
        GROUP BY cust
        HAVING ${p_today}::date - MAX(dep)::date > {SILENCE_DAYS}
        ORDER BY last_load DESC, cust
    """


def _iso(v: datetime | None) -> str | None:
    return v.date().isoformat() if isinstance(v, datetime) else (v.isoformat() if v else None)


def _margin_pct(prof: float | None, rev: float | None) -> float | None:
    """Profit ÷ revenue × 100; None when revenue is not positive (a negative base
    would flip the sign and score a loss as a healthy margin, §113)."""
    if prof is None or rev is None or float(rev) <= 0:
        return None
    return _safe_float(float(prof) / float(rev) * 100.0)


def _new_row(r) -> dict:
    lanes = sorted(x for x in (r["lanes"] or []) if x and x.strip() != "-")
    return {
        "customer_name": r["cust"],
        "vol": int(r["vol"] or 0),
        "prof": _safe_float(float(r["prof"] or 0)),
        "first_load": _iso(r["first_load"]),
        "last_load": _iso(r["last_load"]),
        "margin_pct": _margin_pct(r["prof"], r["rev"]),
        "lanes": lanes,
        "gap_days": int(r["gap_days"]) if r["gap_days"] is not None else None,
    }


def _deactivated_row(r, today: date) -> dict:
    last = r["last_load"]
    return {
        "customer_name": r["cust"],
        "profit": _safe_float(float(r["profit"] or 0)),
        "trips": int(r["trips"] or 0),
        "last_load": _iso(last),
        "days_since": (today - last.date()).days if isinstance(last, datetime) else None,
    }


@router.get("/customer-activity")
async def customer_activity(
    request: Request,
    kind: str = Query("new", description="'new' | 'deactivated'"),
    range: str | None = Query("mtd"),
    start_date: date | None = Query(None),
    end_date: date | None = Query(None),
    team: str | None = Query(None),
    customer: list[str] | None = Query(None),
    load_type: str | None = Query(None),
    lanes: list[str] | None = Query(None),
    exclude_lanes: list[str] | None = Query(None),
    carriers: list[str] | None = Query(None),
    exclude_carriers: list[str] | None = Query(None),
    _user: dict = Depends(require_report_access("ops-portal-overview")),
):
    """New Customer / Deactivated tables (see module docstring)."""
    pool = get_datalake_gold_pool(request)
    scope = scope_of(request)
    side = "deactivated" if (kind or "").lower() == "deactivated" else "new"
    today = cst_today()
    params: list = []
    # lanes / carriers / load_type deliberately NOT passed — module docstring.
    where = _v4_scope_where("br4", team, customer, None, params, scope=scope)

    if side == "new":
        s, e = _resolve_range(range, start_date, end_date)
        params.extend([s, e])
        rows = await pool.fetch(new_customers_sql(where, len(params) - 1, len(params)), *params)
        data = [_new_row(r) for r in rows]
        window = {"start": s.isoformat(), "end": e.isoformat()}
    else:
        params.append(today)
        rows = await pool.fetch(deactivated_sql(where, len(params)), *params)
        data = [_deactivated_row(r, today) for r in rows]
        window = None

    return {
        "success": True,
        "data": data,
        "meta": {
            "kind": side,
            "window": window,
            "as_of": today.isoformat(),
            "silence_days": SILENCE_DAYS,
            "last_trips": LAST_TRIPS,
            "total": len(data),
        },
    }


# ---------------------------------------------------------------------------
# Pure-Python statement of both rules — for tests and probes (no DB).
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Load:
    cust: str
    day: date
    margin: float = 0.0


def new_customers_reference(loads: Iterable[Load], start: date, end: date) -> list[str]:
    """Customers whose first load in [start, end] follows > SILENCE_DAYS of silence."""
    by_cust: dict[str, list[date]] = {}
    for ld in loads:
        if ld.day <= end:
            by_cust.setdefault(ld.cust, []).append(ld.day)
    out = []
    for cust, days in by_cust.items():
        inside = [d for d in days if d >= start]
        before = [d for d in days if d < start]
        if not inside:
            continue
        if not before or (min(inside) - max(before)).days > SILENCE_DAYS:
            out.append(cust)
    return sorted(out)


def deactivated_reference(loads: Sequence[Load], today: date) -> dict[str, float]:
    """{customer: profit of its last LAST_TRIPS loads} for customers silent > SILENCE_DAYS."""
    by_cust: dict[str, list[Load]] = {}
    for ld in loads:
        if ld.day <= today:
            by_cust.setdefault(ld.cust, []).append(ld)
    out: dict[str, float] = {}
    for cust, lds in by_cust.items():
        ordered = sorted(lds, key=lambda x: x.day, reverse=True)
        if (today - ordered[0].day).days > SILENCE_DAYS:
            out[cust] = sum(x.margin for x in ordered[:LAST_TRIPS])
    return out
