"""Code-made report: HR - Access Log Doors.

Replaces Bruno's legacy Qlik app `4573ff42-c0b5-48ef-9945-20861b7a6f63` (which lives
on the separate `unilink.us.qlikcloud.com` tenant) with a portal-native custom
report that reads the same tables directly.

Data source: `aivn_datalake_gold` — already wired via `get_datalake_gold_pool`
(no new env var needed).

Source tables:
  - `public.zk_gld_onlyfingerprint`   -- one row per ZKTeco fingerprint event
  - `public.timeoff_employee`         -- Graph-synced employee directory

Business rules (mirrors Bruno's Qlik variables page):
  * First punch-in per (event_date, display_name) is the scoring row — later
    punches that day are ignored (in/out cycles).
  * Expected arrival ("On Time Reference") is derived from normalized
    department + job_title + name. See `_ON_TIME_REFERENCE_EXPR`.
  * `check_minutes` = `(expected_h*60 + expected_m) - (actual_h*60 + actual_m)`.
      + positive -> arrived at or before expected (ON TIME)
      + negative -> arrived late            (OUT OF TIME)
      + NULL     -> no rule matched         (NOT ON TIME REFERENCE bucket)
    The minute math mirrors Qlik `floor(minute(x)+hour(x)*60)` exactly -- we
    don't use `EXTRACT(EPOCH ...) / 60` because that includes seconds.

Department normalization:
  The source `timeoff_employee.department` has drift: `Pricin`/`Pricing`, `QA`/
  `Quality Assurance`, `Operations DFW`/`Operations (DFW)`. The CTE normalizes
  to the canonical spelling BEFORE the expected-time rules run, so 50+
  employees who would silently fall into "Not On Time Reference" now get
  scored correctly.

Perf notes:
  * Every query's CTE bounds `event_date BETWEEN $1 AND $2` FIRST so the 128K-
    row table is narrowed before ROW_NUMBER() runs.
  * `/trend-30d` and `/by-department` have their own fixed windows so the main
    date filter doesn't change them (per the PDF annotations).
  * Indexes recommended on `zk_gld_onlyfingerprint (event_date)` and
    `zk_gld_onlyfingerprint (email)` -- see docs/SPEC-CUSTOM-REPORTS.md.
"""

from datetime import date, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, Query, Request

from app.clock import cst_today
from app.routers.deps import get_datalake_gold_pool, require_report_access

# --------------------------------------------------------------------------
# SQL fragments (kept at module level, reused by every endpoint)
# --------------------------------------------------------------------------

# Fold drift variants into the canonical department spelling Bruno's rules
# match against. Applied inside the CTE so downstream queries never see drift.
_DEPARTMENT_NORMALIZED = """
  CASE UPPER(TRIM(e.department))
    WHEN 'PRICIN'           THEN 'Pricing'
    WHEN 'QA'               THEN 'Quality Assurance'
    WHEN 'OPERATIONS DFW'   THEN 'Operations (DFW)'
    ELSE NULLIF(TRIM(e.department), '')
  END
"""

# IT department employees are excluded from this report (requested by HR — IT
# staff keep irregular hours so their punches are noise in the on-time metric).
# Applied inside the JOIN so every endpoint (filters, kpis, rows, trend,
# by-department) drops them uniformly. The REPLACE strips periods so dot-style
# spellings ("I.T.", "I.T") collapse to "IT". Covered variants:
#   "IT", "I.T.", "I.T", "Information Technology", "IT Support" (any "IT "
#   prefix). Case + trailing whitespace normalised via UPPER(TRIM(...)).
# NULL departments pass through (Graph-sync drift safety).
_EXCLUDE_IT_SQL = """
  AND (
    e.department IS NULL
    OR (
      UPPER(REPLACE(TRIM(e.department), '.', '')) NOT IN ('IT', 'INFORMATION TECHNOLOGY')
      AND UPPER(REPLACE(TRIM(e.department), '.', '')) NOT LIKE 'IT %'
    )
  )
"""

# Expected-arrival timestamp for this row. NULL when no rule matches -> the
# row falls in the "Not On Time Reference" bucket. Order matters: the
# `Operations (DFW) / Operations Intern` exception must come BEFORE the
# general `Operations (DFW) -> 06:30` rule.
_ON_TIME_REFERENCE_EXPR = """
  CASE
    WHEN dep = 'Operations (DFW)' AND jt = 'Operations Intern'
      THEN event_date::timestamp + TIME '07:30'
    WHEN dep IN ('Sales','Operations','Operations (DFW)','Pricing','Legal')
      THEN event_date::timestamp + TIME '06:30'
    WHEN dep = 'Admin'
      THEN event_date::timestamp + TIME '07:00'
    WHEN dep = 'Quality Assurance'
      THEN event_date::timestamp + TIME '07:30'
    WHEN dep = 'Finance' AND jt = 'Chief Financial Officer'
      THEN event_date::timestamp + TIME '07:00'
    WHEN dep = 'Finance' AND jt = 'Finance Manager'
      THEN event_date::timestamp + TIME '08:00'
    WHEN dep = 'Human Resources' AND jt = 'Sr. Corporate Recruiter'
      THEN event_date::timestamp + TIME '07:00'
    WHEN dep = 'Human Resources'
         AND jt IN ('Human Resources Manager','Corporate Human Resources Director')
      THEN event_date::timestamp + TIME '08:00'
    WHEN dep = 'Executive' AND jt = 'Executive Assistant' AND nm = 'Ruth Garza'
      THEN event_date::timestamp + TIME '06:30'
    WHEN dep = 'Executive' AND jt = 'Executive Assistant' AND nm = 'Gabriela Murguia'
      THEN event_date::timestamp + TIME '07:00'
    ELSE NULL
  END
"""

# Integer-minute delta (expected - actual), matching Qlik's
#   `floor(minute(x) + hour(x)*60)` exactly. Positive = on time, negative = late.
_CHECK_MINUTES_EXPR = """
  (
    (EXTRACT(HOUR FROM expected)::int * 60 + EXTRACT(MINUTE FROM expected)::int)
    - (EXTRACT(HOUR FROM event_time)::int * 60 + EXTRACT(MINUTE FROM event_time)::int)
  )
"""


def _first_punch_cte(start_placeholder: str, end_placeholder: str) -> str:
    """CTE body (no leading `WITH`) that yields first-of-day punches with
    normalized department + job_title + name columns.

    The placeholders ($1, $2, ...) are passed in by the caller — they must
    line up with the corresponding values in the params list.
    """
    return f"""
    first_punch AS (
        SELECT
            TRIM(z.full_name)                                AS nm,
            z.event_date,
            z.event_time,
            TRIM(e.job_title)                                AS jt,
            {_DEPARTMENT_NORMALIZED}                         AS dep,
            ROW_NUMBER() OVER (
                PARTITION BY z.event_date,
                             COALESCE(e.display_name, z.full_name)
                ORDER BY z.event_time ASC
            ) AS rn
        FROM public.zk_gld_onlyfingerprint z
        JOIN public.timeoff_employee e
          ON TRIM(z.email) = TRIM(e.email)
         AND COALESCE(e.email, '') <> ''
         {_EXCLUDE_IT_SQL}
        WHERE z.event_date BETWEEN {start_placeholder} AND {end_placeholder}
    )
    """


def _scored_cte(alias: str = "scored") -> str:
    """CTE that keeps only first-of-day rows and attaches the expected-time
    column. Input: `first_punch`. Output: one row per (employee, day)."""
    return f"""
    {alias} AS (
        SELECT nm, jt, dep, event_date, event_time,
               ({_ON_TIME_REFERENCE_EXPR}) AS expected
        FROM first_punch
        WHERE rn = 1
    )
    """


router = APIRouter(tags=["hr-access-doors"], prefix="/custom/hr-access-doors")


# --------------------------------------------------------------------------
# /filters  -- dropdown options for department / name / job_title
# --------------------------------------------------------------------------
@router.get("/filters")
async def filters(
    request: Request,
    _user: dict = Depends(require_report_access("hr-access-doors")),
):
    """Distinct departments, job titles, and employee names seen in the last
    90 days. Scoped to 90d so the dropdowns stay tight (ex-employees age out).
    """
    pool = get_datalake_gold_pool(request)
    since = cst_today() - timedelta(days=90)

    rows = await pool.fetch(
        f"""
        WITH {_first_punch_cte('$1', 'CURRENT_DATE')},
        {_scored_cte()}
        SELECT DISTINCT dep AS department, jt AS job_title, nm AS full_name
        FROM scored
        """,
        since,
    )
    departments = sorted({r["department"] for r in rows if r["department"]})
    job_titles = sorted({r["job_title"] for r in rows if r["job_title"]})
    names = sorted({r["full_name"] for r in rows if r["full_name"]})

    return {
        "success": True,
        "data": {
            "departments": departments,
            "job_titles": job_titles,
            "names": names,
            "today": cst_today().isoformat(),
        },
    }


# --------------------------------------------------------------------------
# /kpis  -- the 6 cards: Log-In / Not-On-Ref / On Time / Out Time / % On / % Out
# --------------------------------------------------------------------------
@router.get("/kpis")
async def kpis(
    request: Request,
    start_date: Optional[date] = Query(None, description="YYYY-MM-DD, default today"),
    end_date: Optional[date] = Query(None, description="YYYY-MM-DD, default today"),
    department: Optional[str] = Query(None),
    name: Optional[str] = Query(None),
    job_title: Optional[str] = Query(None),
    _user: dict = Depends(require_report_access("hr-access-doors")),
):
    """KPI counts for the selected window + filters.

    Percentages use `scored_rows - not_on_time_ref` as the denominator,
    matching Bruno's Qlik formula exactly.
    """
    pool = get_datalake_gold_pool(request)
    s, e = _resolve_window(start_date, end_date)

    params: list = [s, e]
    filters_sql = _build_filters_sql(params, department, name, job_title)

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
        WHERE 1=1 {filters_sql}
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
# /rows  -- the big Access Log Doors table (paginated)
# --------------------------------------------------------------------------
@router.get("/rows")
async def rows(
    request: Request,
    start_date: Optional[date] = Query(None),
    end_date: Optional[date] = Query(None),
    department: Optional[str] = Query(None),
    name: Optional[str] = Query(None),
    job_title: Optional[str] = Query(None),
    sort: str = Query("event_time_desc"),
    page: int = Query(1, ge=1),
    limit: int = Query(100, ge=1, le=500),
    _user: dict = Depends(require_report_access("hr-access-doors")),
):
    """Per-row table: Name, Event Date, Access Log Door, Job Title, Check,
    On Time Reference. Paginated + sortable."""
    pool = get_datalake_gold_pool(request)
    s, e = _resolve_window(start_date, end_date)

    sort_sql = {
        "event_time_desc": "event_time DESC, nm DESC",
        "event_time_asc": "event_time ASC, nm ASC",
        "check_desc": "check_minutes DESC NULLS LAST",
        "check_asc": "check_minutes ASC NULLS LAST",
        "name_asc": "nm ASC, event_time DESC",
        "department": "dep ASC, nm ASC",
    }.get(sort, "event_time DESC, nm DESC")

    offset = (page - 1) * limit
    params: list = [s, e]
    filters_sql = _build_filters_sql(params, department, name, job_title)

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
        WHERE 1=1 {filters_sql}
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
        WHERE 1=1 {filters_sql}
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
# /trend-30d  -- rolling 30-day line chart (ignores main date + dept filter)
# --------------------------------------------------------------------------
@router.get("/trend-30d")
async def trend_30d(
    request: Request,
    name: Optional[str] = Query(None),
    job_title: Optional[str] = Query(None),
    _user: dict = Depends(require_report_access("hr-access-doors")),
):
    """On-Time vs Out-of-Time per day, fixed-window last 30 days.

    Bruno's PDF: "It should not change with the date filter. Show just the
    previous 30 days." Also ignores department per the same annotation.
    """
    pool = get_datalake_gold_pool(request)
    end = cst_today()
    start = end - timedelta(days=29)  # inclusive 30-day window

    params: list = [start, end]
    filters_sql = _build_filters_sql(params, None, name, job_title)

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
        WHERE 1=1 {filters_sql}
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
# /by-department  -- bar chart (ignores department filter)
# --------------------------------------------------------------------------
@router.get("/by-department")
async def by_department(
    request: Request,
    start_date: Optional[date] = Query(None),
    end_date: Optional[date] = Query(None),
    name: Optional[str] = Query(None),
    job_title: Optional[str] = Query(None),
    _user: dict = Depends(require_report_access("hr-access-doors")),
):
    """On-Time vs Out-of-Time per department for the selected window.

    Honors the date filter + name/job_title. Ignores the department filter
    (per the PDF: "It should not change with the department filter.").
    """
    pool = get_datalake_gold_pool(request)
    s, e = _resolve_window(start_date, end_date)

    params: list = [s, e]
    filters_sql = _build_filters_sql(params, None, name, job_title)

    rows_out = await pool.fetch(
        f"""
        WITH {_first_punch_cte('$1', '$2')},
             {_scored_cte()}
        SELECT
          COALESCE(dep, '—')                                              AS department,
          COUNT(*) FILTER (WHERE expected IS NOT NULL
                             AND {_CHECK_MINUTES_EXPR} >= 0)              AS on_time,
          COUNT(*) FILTER (WHERE expected IS NOT NULL
                             AND {_CHECK_MINUTES_EXPR} <= -1)             AS out_of_time,
          COUNT(*) FILTER (WHERE expected IS NULL)                        AS unscored
        FROM scored
        WHERE 1=1 {filters_sql}
        GROUP BY COALESCE(dep, '—')
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
def _resolve_window(start_date: Optional[date], end_date: Optional[date]) -> tuple[date, date]:
    """Both default to today; swap if inverted. The user-facing filter default
    matches Bruno's Qlik spec: `Date (default value = today)`."""
    today = cst_today()
    s = start_date or today
    e = end_date or start_date or today
    if s > e:
        s, e = e, s
    return s, e


def _build_filters_sql(
    params: list,
    department: Optional[str],
    name: Optional[str],
    job_title: Optional[str],
) -> str:
    """Append filter values to `params` and return the AND fragment.

    Caller must have already pushed the date-window params ($1 and $2) onto
    `params` before invoking this helper.
    """
    parts: list[str] = []
    if department:
        params.append(department)
        parts.append(f"dep = ${len(params)}")
    if name:
        params.append(name)
        parts.append(f"nm = ${len(params)}")
    if job_title:
        params.append(job_title)
        parts.append(f"jt = ${len(params)}")
    return ("".join(f" AND {p}" for p in parts)) if parts else ""
