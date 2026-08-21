"""Filter catalog, workday KPIs and data freshness.

Part of the ``ops_portal_overview`` package (split 2026-08-14 — see SPEC-CUSTOM-REPORTS §28).
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta

from fastapi import Depends, Request

from app.clock import cst_today
from app.routers.deps import get_datalake_gold_pool, require_report_access

from ._constants import CORP_COMPANIES, OPEN_STATUSES, YEAR_END, YEAR_START, router
from ._scope import scope_of
from ._dates import _count_workdays, _month_bounds
from ._sql import _lane_expr
from ._metrics import _safe_float


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
    scope = scope_of(request)
    scope_args = [
        list(scope.base_teams),
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
    # Bruno (PDF 2026-07-15) R1: distinct carriers (first-movement payee) on
    # in-scope YTD orders. ~11 rows — the movement join is order_id-indexed.
    carrier_sql = """
        SELECT DISTINCT TRIM(m.payee_name) AS carrier
        FROM public.mcleod_gld_movement m
        JOIN public.mcleod_gld_budget_report_v4 br4
          ON m.order_id = br4.id AND m.company_id = br4.company_id
        WHERE TRIM(br4.team_id)    = ANY($1)
          AND TRIM(br4.company_id) = ANY($2)
          AND TRIM(br4.status)     = ANY($3)
          AND UPPER(COALESCE(br4.customer_name,'')) NOT LIKE '%OILTEX%'
          AND br4.origin_actual_departure >= $4
          AND m.payee_name IS NOT NULL AND TRIM(m.payee_name) <> ''
        ORDER BY carrier
    """
    cust_rows, lane_rows, carrier_rows = await asyncio.gather(
        pool.fetch(cust_sql, *scope_args),
        pool.fetch(lane_sql, *scope_args),
        pool.fetch(carrier_sql, *scope_args),
    )
    return {
        "success": True,
        "data": {
            "teams": list(scope.sub_teams),
            "customers": [r["customer_name"] for r in cust_rows],
            "lanes": [r["lane"] for r in lane_rows],
            "carriers": [r["carrier"] for r in carrier_rows],
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
# /data-freshness — "Data as of …" signal for the page header.
# ---------------------------------------------------------------------------

# 60s in-process cache. The page fires this on every mount and the answer only
# moves when an ETL run lands, so re-querying per render is pure waste.
_FRESHNESS_TTL = timedelta(seconds=60)
_freshness_cache: dict[str, object] = {"at": None, "payload": None}


@router.get("/data-freshness")
async def data_freshness(
    request: Request,
    _user: dict = Depends(require_report_access("ops-portal-overview")),
):
    """Newest row timestamp per upstream source, for the header's "Data as of".

    ⚠ **Deliberately NOT named ``/freshness``.** Several reports
    (``ops_margins``, ``ops_direct_compare``, ``ops_customer_score``,
    ``attrition_wow``, …) already expose ``GET /freshness`` returning a
    single-table ``{last_updated, last_created, rows_in_scope}``. This report
    merges *four* feeds and needs to name the stalest one, which that shape
    cannot express — so it gets a distinct path rather than the same name with
    a different contract. If the two ever converge, converge the shape first.

    **Why this exists.** Every panel here reads n8n/Spark-refreshed mirrors. When
    a refresh stalls the page keeps rendering happily with yesterday's numbers —
    a dead pipeline and a quiet day look identical. That ambiguity is what hid a
    3-day production outage on another portal. The headline is deliberately the
    **oldest** of the sources: a dashboard is only as fresh as its stalest feed.

    ⚠ **None of these columns is indexed**, so an unfiltered ``MAX()`` is a seq
    scan — ``budget_report_v4`` alone is 391 MB, and ``movement`` is 983 MB for
    2,183 live tuples (badly bloated). Measured 2026-07-30. So:

    * ``v4`` is scoped to the last 7 days of ``origin_actual_departure``, which
      rides the existing ``idx_v4_dep``. Verified equivalent: scoped max
      13:36:20 vs unfiltered 13:37:06 — 46s apart. This still detects a dead
      pipeline (a stalled ETL stops writing the hot slice first) and it is NOT
      the "filtered max hides staleness" trap, which is about *business*
      filters (one customer/team) rather than the recent window the ETL writes.
    * ``budget`` (7.8 MB) and ``savings`` (15 MB) are small enough to scan.
    * ``scorecard`` (68 MB) is included because the portal-owned mirror is the
      one with a known stall mode (``daily_scorecard_mirror_check`` alerts on
      it) — this makes that visible in the UI rather than only by email.
    * ``movement`` / ``customer_windows`` are deliberately omitted — 983 MB and
      185 MB of seq scan for feeds that move with v4 anyway.

    Timestamps are CST already (the gold datalake stores CST and the pool is
    pinned via ``_set_cst_session``), so ``age_minutes`` compares against
    ``LOCALTIMESTAMP`` on the same session — no tz maths.
    """
    now = datetime.now()
    cached_at = _freshness_cache.get("at")
    if isinstance(cached_at, datetime) and now - cached_at < _FRESHNESS_TTL:
        return {"success": True, "data": _freshness_cache["payload"]}

    pool = get_datalake_gold_pool(request)
    scope = scope_of(request)
    sql = """
        SELECT
          (SELECT MAX(updated_dt) FROM public.mcleod_gld_budget_report_v4
             WHERE origin_actual_departure >= (CURRENT_DATE - 7))        AS production,
          (SELECT MAX(updated_dt) FROM public.mcleod_gld_scorecard_portal) AS scorecard,
          (SELECT MAX(created_at) FROM public.daily_production_budget_report) AS budget,
          (SELECT MAX(created_at) FROM public.carriers_savings_results_report) AS savings,
          -- Explicit AT TIME ZONE rather than LOCALTIMESTAMP: the gold pool IS
          -- pinned to America/Chicago via _set_cst_session, but spelling it out
          -- means the age maths stays right even if this is ever called from a
          -- pool that isn't. Getting this wrong shows every feed as ~6h stale
          -- and cries wolf. Matches clock.CST_NOW_DATE_SQL.
          (now() AT TIME ZONE 'America/Chicago') AS now_cst
    """
    row = await pool.fetchrow(sql)

    now_cst = row["now_cst"]
    sources = []
    for key, label in (
        ("production", "Production"),
        ("scorecard", "Scorecard"),
        ("budget", "Budget"),
        ("savings", "Savings"),
    ):
        ts = row[key]
        sources.append({
            "key": key,
            "label": label,
            "updated_at": ts.isoformat() if ts else None,
            "age_minutes": (
                _safe_float((now_cst - ts).total_seconds() / 60.0) if ts else None
            ),
        })

    # Headline = the STALEST feed. A dashboard is only as fresh as its worst
    # source, so reporting the newest would paper over exactly the failure we
    # are trying to surface.
    aged = [s for s in sources if s["age_minutes"] is not None]
    oldest = max(aged, key=lambda s: s["age_minutes"]) if aged else None
    payload = {
        "sources": sources,
        "as_of": oldest["updated_at"] if oldest else None,
        "age_minutes": oldest["age_minutes"] if oldest else None,
        "stalest": oldest["label"] if oldest else None,
        "checked_at": now_cst.isoformat(),
    }
    _freshness_cache["at"] = now
    _freshness_cache["payload"] = payload
    return {"success": True, "data": payload}
