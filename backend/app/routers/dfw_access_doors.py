"""Code-made report: DFW - Access Log Doors.

Department-locked clone of `HR - Access Log Doors` for the DFW audience. The
business logic is identical (first punch / day, expected-arrival rule, integer
minute delta) but every endpoint hard-codes `dep = 'Operations (DFW)'` so:

  * users can never widen the scope by tampering with query strings
  * the front-end can drop the Department dropdown entirely
  * the by-job-title chart replaces the by-department bars (single bar
    would be useless)
  * the rolling-30-day trend stays locked to Operations (DFW) — unlike the
    HR original which was deliberately global

We import the SQL fragments + helpers from `hr_access_doors` so the
on-time-reference rule + department-drift normalization stay in one place.
"""

from datetime import date, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, Query, Request

from app.clock import cst_today
from app.routers.deps import get_datalake_gold_pool, require_tag_role
from app.routers.hr_access_doors import (
    _CHECK_MINUTES_EXPR,
    _first_punch_cte,
    _resolve_window,
    _scored_cte,
)

# TagRoles allowed to view this report (admin bypasses automatically).
# Strict DFW audience per Diego's call (2026-04-28). Spelling matches the
# admin-UI role names exactly — match is case-insensitive but spelling-exact.
DFW_ACCESS_ROLES = (
    "DFW",
    "DFW-Assistent",
    "DFW KAM",
    "Assitent OPs manager",
)

# The fixed department gate — applied as an extra AND clause on `scored` in
# every query. Matches the canonical spelling produced by
# `_DEPARTMENT_NORMALIZED` in hr_access_doors.py.
_DFW_DEPT_GATE = "AND dep = 'Operations (DFW)'"


router = APIRouter(tags=["dfw-access-doors"], prefix="/custom/dfw-access-doors")


# --------------------------------------------------------------------------
# /filters  -- dropdown options for name / job_title (no department)
# --------------------------------------------------------------------------
@router.get("/filters")
async def filters(
    request: Request,
    _user: dict = Depends(require_tag_role(*DFW_ACCESS_ROLES)),
):
    """Distinct job titles + employee names seen in Operations (DFW) over the
    last 90 days. Department dropdown intentionally omitted — the report is
    locked to Operations (DFW) server-side."""
    pool = get_datalake_gold_pool(request)
    since = cst_today() - timedelta(days=90)

    rows = await pool.fetch(
        f"""
        WITH {_first_punch_cte('$1', 'CURRENT_DATE')},
        {_scored_cte()}
        SELECT DISTINCT jt AS job_title, nm AS full_name
        FROM scored
        WHERE 1=1 {_DFW_DEPT_GATE}
        """,
        since,
    )
    job_titles = sorted({r["job_title"] for r in rows if r["job_title"]})
    names = sorted({r["full_name"] for r in rows if r["full_name"]})

    return {
        "success": True,
        "data": {
            "job_titles": job_titles,
            "names": names,
            "today": cst_today().isoformat(),
        },
    }


# --------------------------------------------------------------------------
# /kpis
# --------------------------------------------------------------------------
@router.get("/kpis")
async def kpis(
    request: Request,
    start_date: Optional[date] = Query(None, description="YYYY-MM-DD, default today"),
    end_date: Optional[date] = Query(None, description="YYYY-MM-DD, default today"),
    name: Optional[str] = Query(None),
    job_title: Optional[str] = Query(None),
    _user: dict = Depends(require_tag_role(*DFW_ACCESS_ROLES)),
):
    pool = get_datalake_gold_pool(request)
    s, e = _resolve_window(start_date, end_date)

    params: list = [s, e]
    filters_sql = _build_dfw_filters_sql(params, name, job_title)

    row = await pool.fetchrow(
        f"""
        WITH {_first_punch_cte('$1', '$2')},
             {_scored_cte()}
        SELECT
          COUNT(DISTINCT nm)                                           AS log_in_employees,
          COUNT(*) FILTER (WHERE expected IS NULL)                     AS not_on_time_ref,
          COUNT(*) FILTER (WHERE expected IS NOT NULL
                             AND {_CHECK_MINUTES_EXPR} >= 0)           AS on_time,
          COUNT(*) FILTER (WHERE expected IS NOT NULL
                             AND {_CHECK_MINUTES_EXPR} <= -1)          AS out_of_time,
          COUNT(*)                                                     AS total_rows
        FROM scored
        WHERE 1=1 {_DFW_DEPT_GATE} {filters_sql}
        """,
        *params,
    )

    data = dict(row) if row else {}
    denom = int(data.get("total_rows") or 0) - int(data.get("not_on_time_ref") or 0)
    data["pct_on_time"] = (
        float(data["on_time"]) / denom if denom > 0 else None
    )
    data["pct_out_of_time"] = (
        float(data["out_of_time"]) / denom if denom > 0 else None
    )
    data["window"] = {"start": s.isoformat(), "end": e.isoformat()}
    return {"success": True, "data": data}


# --------------------------------------------------------------------------
# /rows
# --------------------------------------------------------------------------
@router.get("/rows")
async def rows(
    request: Request,
    start_date: Optional[date] = Query(None),
    end_date: Optional[date] = Query(None),
    name: Optional[str] = Query(None),
    job_title: Optional[str] = Query(None),
    sort: str = Query("event_time_desc"),
    page: int = Query(1, ge=1),
    limit: int = Query(100, ge=1, le=500),
    _user: dict = Depends(require_tag_role(*DFW_ACCESS_ROLES)),
):
    pool = get_datalake_gold_pool(request)
    s, e = _resolve_window(start_date, end_date)

    sort_sql = {
        "event_time_desc": "event_time DESC, nm DESC",
        "event_time_asc": "event_time ASC, nm ASC",
        "check_desc": "check_minutes DESC NULLS LAST",
        "check_asc": "check_minutes ASC NULLS LAST",
        "name_asc": "nm ASC, event_time DESC",
        "job_title": "jt ASC, nm ASC",
    }.get(sort, "event_time DESC, nm DESC")

    offset = (page - 1) * limit
    params: list = [s, e]
    filters_sql = _build_dfw_filters_sql(params, name, job_title)

    count_params = list(params)
    params.extend([limit, offset])

    rows_out = await pool.fetch(
        f"""
        WITH {_first_punch_cte('$1', '$2')},
             {_scored_cte()}
        SELECT
          nm                    AS full_name,
          event_date::text      AS event_date,
          event_time            AS event_time,
          jt                    AS job_title,
          dep                   AS department,
          expected              AS on_time_reference,
          CASE WHEN expected IS NULL THEN NULL ELSE {_CHECK_MINUTES_EXPR} END AS check_minutes
        FROM scored
        WHERE 1=1 {_DFW_DEPT_GATE} {filters_sql}
        ORDER BY {sort_sql}
        LIMIT ${len(params) - 1} OFFSET ${len(params)}
        """,
        *params,
    )

    total = await pool.fetchval(
        f"""
        WITH {_first_punch_cte('$1', '$2')},
             {_scored_cte()}
        SELECT COUNT(*)
        FROM scored
        WHERE 1=1 {_DFW_DEPT_GATE} {filters_sql}
        """,
        *count_params,
    )

    data = [
        {
            "full_name": r["full_name"],
            "event_date": r["event_date"],
            "event_time": r["event_time"].isoformat() if r["event_time"] else None,
            "job_title": r["job_title"],
            "department": r["department"],
            "on_time_reference": (
                r["on_time_reference"].isoformat() if r["on_time_reference"] else None
            ),
            "check_minutes": r["check_minutes"],
        }
        for r in rows_out
    ]
    return {
        "success": True,
        "data": data,
        "meta": {
            "total": total or 0,
            "page": page,
            "limit": limit,
            "window": {"start": s.isoformat(), "end": e.isoformat()},
        },
    }


# --------------------------------------------------------------------------
# /trend-30d  -- rolling 30-day line, locked to Operations (DFW)
# --------------------------------------------------------------------------
@router.get("/trend-30d")
async def trend_30d(
    request: Request,
    name: Optional[str] = Query(None),
    job_title: Optional[str] = Query(None),
    _user: dict = Depends(require_tag_role(*DFW_ACCESS_ROLES)),
):
    """On-Time vs Out-of-Time per day, fixed-window last 30 days, scoped to
    Operations (DFW). Ignores the user-selected date filter (rolling 30d) but
    NOT the department gate — unlike the HR original."""
    pool = get_datalake_gold_pool(request)
    end = cst_today()
    start = end - timedelta(days=29)

    params: list = [start, end]
    filters_sql = _build_dfw_filters_sql(params, name, job_title)

    rows_out = await pool.fetch(
        f"""
        WITH {_first_punch_cte('$1', '$2')},
             {_scored_cte()}
        SELECT
          event_date::text AS event_date,
          COUNT(*) FILTER (WHERE expected IS NOT NULL
                             AND {_CHECK_MINUTES_EXPR} >= 0)  AS on_time,
          COUNT(*) FILTER (WHERE expected IS NOT NULL
                             AND {_CHECK_MINUTES_EXPR} <= -1) AS out_of_time
        FROM scored
        WHERE 1=1 {_DFW_DEPT_GATE} {filters_sql}
        GROUP BY event_date
        ORDER BY event_date ASC
        """,
        *params,
    )
    return {
        "success": True,
        "data": [dict(r) for r in rows_out],
        "meta": {"window": {"start": start.isoformat(), "end": end.isoformat()}},
    }


# --------------------------------------------------------------------------
# /by-job-title  -- bar chart (replaces /by-department since dept is fixed)
# --------------------------------------------------------------------------
@router.get("/by-job-title")
async def by_job_title(
    request: Request,
    start_date: Optional[date] = Query(None),
    end_date: Optional[date] = Query(None),
    name: Optional[str] = Query(None),
    _user: dict = Depends(require_tag_role(*DFW_ACCESS_ROLES)),
):
    """On-Time vs Out-of-Time per job title within Operations (DFW) for the
    selected window. Ignores the job-title filter (so the chart never
    collapses to a single bar)."""
    pool = get_datalake_gold_pool(request)
    s, e = _resolve_window(start_date, end_date)

    params: list = [s, e]
    # Pass job_title=None — chart should show every title regardless of the
    # filter pill so the user can still see the breakdown.
    filters_sql = _build_dfw_filters_sql(params, name, None)

    rows_out = await pool.fetch(
        f"""
        WITH {_first_punch_cte('$1', '$2')},
             {_scored_cte()}
        SELECT
          COALESCE(jt, '—')                                              AS job_title,
          COUNT(*) FILTER (WHERE expected IS NOT NULL
                             AND {_CHECK_MINUTES_EXPR} >= 0)              AS on_time,
          COUNT(*) FILTER (WHERE expected IS NOT NULL
                             AND {_CHECK_MINUTES_EXPR} <= -1)             AS out_of_time,
          COUNT(*) FILTER (WHERE expected IS NULL)                        AS unscored
        FROM scored
        WHERE 1=1 {_DFW_DEPT_GATE} {filters_sql}
        GROUP BY COALESCE(jt, '—')
        ORDER BY (
          COUNT(*) FILTER (WHERE expected IS NOT NULL
                             AND {_CHECK_MINUTES_EXPR} >= 0)
          + COUNT(*) FILTER (WHERE expected IS NOT NULL
                               AND {_CHECK_MINUTES_EXPR} <= -1)
        ) DESC
        """,
        *params,
    )
    return {
        "success": True,
        "data": [dict(r) for r in rows_out],
        "meta": {"window": {"start": s.isoformat(), "end": e.isoformat()}},
    }


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------
def _build_dfw_filters_sql(
    params: list,
    name: Optional[str],
    job_title: Optional[str],
) -> str:
    """Append name/job_title filter values to `params` and return the AND
    fragment. Department is intentionally NOT a parameter — it's gated by
    `_DFW_DEPT_GATE`."""
    parts: list[str] = []
    if name:
        params.append(name)
        parts.append(f"nm = ${len(params)}")
    if job_title:
        params.append(job_title)
        parts.append(f"jt = ${len(params)}")
    return ("".join(f" AND {p}" for p in parts)) if parts else ""
