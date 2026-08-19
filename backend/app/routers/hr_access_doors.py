"""Code-made report: HR - Access Log Doors.

Replaces Bruno's legacy Qlik app `4573ff42-c0b5-48ef-9945-20861b7a6f63` (which lives
on the separate `unilink.us.qlikcloud.com` tenant) with a portal-native custom
report that reads the same tables directly.

Data source: `aivn_datalake_gold` — already wired via `get_datalake_gold_pool`
(no new env var needed).

Source tables:
  - `public.zk_gld_onlyfingerprint`   -- one row per ZKTeco fingerprint event
  - `public.timeoff_employee`         -- Graph-synced employee directory

Source tables (cont.):
  - `public.late_arrival_schedule`    -- HR-editable expected-arrival rules
  - `public.app_auth_users`           -- team + shift roster, READ ONLY (owned
                                         by another system)

Business rules:
  * Expected arrival ("On Time Reference") comes from `late_arrival_schedule`,
    the same table the n8n workflow reads. Most specific rule wins:
    email > full_name > job_title > department. See `_EXPECTED_TIME_LOOKUP`.
    This used to be a hardcoded CASE here — a second copy of the same rules that
    had already drifted (it never learned the Aranza Romero 07:00 override).
  * SHIFT AWARENESS (Aug 2026). An expected_time at or after 12:00 marks an
    overnight shift. Its punches straddle midnight, so they are grouped by the
    EVENING the shift began, not by calendar date, and only a punch within
    [expected-3h, expected+6h] counts as an arrival.
    Before this, the first punch on a calendar date was a night worker's morning
    EXIT badge and got scored as a late arrival — the report was telling five
    recipients that the DFW night team was ~12 hours late every day.
    "No entry badge for this shift" is now absent from the report rather than
    being reported as lateness.
  * The arrival row per (employee, shift date) is the scoring row — later
    punches in that shift are ignored (in/out cycles).
  * `check_minutes` = TRUNC(EXTRACT(EPOCH FROM (expected - actual)) / 60).
      + positive -> arrived at or before expected (ON TIME)
      + negative -> arrived late            (OUT OF TIME)
      + NULL     -> no rule matched         (NOT ON TIME REFERENCE bucket)
    A true timestamp difference, so it stays correct across midnight. The old
    hour*60+minute form scored a 00:30 arrival against 19:30 as "19h early".

Department normalization:
  The source `timeoff_employee.department` has drift: `Pricin`/`Pricing`, `QA`/
  `Quality Assurance`, `Operations DFW`/`Operations (DFW)`. The CTE normalizes
  to the canonical spelling BEFORE the expected-time rules run, so 50+
  employees who would silently fall into "Not On Time Reference" now get
  scored correctly.

Perf notes:
  * Every query's CTE bounds `event_date BETWEEN $1-1 AND $2+1` FIRST so the
    128K-row table is narrowed before ROW_NUMBER() runs. The one-day overscan is
    deliberate — an overnight shift must be assembled whole before it can be
    attributed to a shift date — and `_scored_cte` narrows back to the exact
    range afterwards.
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
_EXPECTED_TIME_LOOKUP = """
  (
    SELECT s.expected_time
      FROM public.late_arrival_schedule s
     WHERE s.active
       AND (s.email      IS NULL OR lower(btrim(s.email))      = p.em)
       AND (s.full_name  IS NULL OR lower(btrim(s.full_name))  = lower(p.nm))
       AND (s.job_title  IS NULL OR lower(btrim(s.job_title))  = lower(p.jt))
       AND (s.department IS NULL OR lower(btrim(s.department)) = lower(p.dep))
     ORDER BY (s.email      IS NOT NULL)::int * 1000
            + (s.full_name  IS NOT NULL)::int * 100
            + (s.job_title  IS NOT NULL)::int * 10
            + (s.department IS NOT NULL)::int DESC,
              s.id
     LIMIT 1
  )
"""

# A shift whose expected start is at or after noon runs overnight, so its punches
# straddle midnight. Group them by the EVENING the shift began — otherwise the
# first punch on a calendar date is the night worker's morning EXIT badge and it
# gets scored as a late arrival. That is what produced
# "Ruben Aguilera | 06:30 AM | 7:12 AM | 42 min" for a man whose shift had just
# ended at 07:12, and -729 min for colleagues who arrived on time at 18:39.
_SHIFT_DATE_EXPR = """
  CASE
    WHEN a.expected_time >= TIME '12:00' AND a.event_time::time < TIME '12:00'
      THEN a.event_time::date - 1
    ELSE a.event_time::date
  END
"""

# Only a punch near the expected start counts as an arrival. Two things follow:
# a night worker badging OUT at 07:00 is no longer scored as a late arrival, and
# "no entry badge recorded for this shift" stops being reported as lateness.
_ARRIVAL_WINDOW = "INTERVAL '3 hours'", "INTERVAL '6 hours'"

# Team label, derived from the datalake auth roster — the only directory whose
# team + shift assignment matches the org's own DFW roster person for person, and
# where "Team 5" is actually defined (TM5 = Ali Cisneros + Kraufeerg Derflingher).
# Read-only: that table belongs to another system, so gaps surface as
# "Unassigned" rather than being patched from here.
_TEAM_LABEL_EXPR = """
  CASE
    WHEN u.shift = 'nightshift'     THEN 'Night'
    WHEN u.shift = 'weekend'        THEN 'Weekend'
    WHEN u.team_id ~ '^TM[0-9]+$'   THEN 'Team ' || substring(u.team_id from 3)
    WHEN u.team_id ~ '^TEAM[0-9]+$' THEN 'Team ' || substring(u.team_id from 5)
    ELSE 'Unassigned'
  END
"""

# Integer-minute delta (expected - actual). Positive = on time, negative = late.
#
# A true timestamp difference, not hour*60+minute of each side. The old clock
# arithmetic broke across midnight — a 00:30 arrival against a 19:30 expected
# computed as "19 hours early" — and it disagreed with the n8n workflow by up to
# a minute. Both now truncate the same epoch difference.
_CHECK_MINUTES_EXPR = """
  TRUNC(EXTRACT(EPOCH FROM (expected - event_time)) / 60)::int
"""

# The three mutually-exclusive buckets a `scored` row falls into. Written ONCE,
# here, and reused by every endpoint in this module, by every scope-locked clone
# in `scoped_access_doors.py`, and by the DFW delays digest. Before this, the
# pair was re-typed at nine call sites; a report that re-types the definition of
# its own headline metric is a report that will one day disagree with itself
# (SPEC-CODE-RULES §69 — one metric, one named definition).
#
# ⚠ "Not on time reference" is NOT "on time". A row with no matching rule in
# `late_arrival_schedule` cannot be scored at all, so it must be counted in
# neither bucket — folding it into ON_TIME would flatter every rate, and folding
# it into OUT_OF_TIME would accuse people the report has no expectation for.
_NOT_ON_TIME_REF_PREDICATE = "expected IS NULL"
_ON_TIME_PREDICATE = f"(expected IS NOT NULL AND {_CHECK_MINUTES_EXPR} >= 0)"

# OUT OF TIME. `<= -1`, not `< 0`: check_minutes is already TRUNCated to whole
# minutes, so there is no grace period — one minute late is Out of Time.
_OUT_OF_TIME_PREDICATE = f"(expected IS NOT NULL AND {_CHECK_MINUTES_EXPR} <= -1)"

# Plain-language wording for the same rule, so an e-mail/tooltip explaining
# "Out of Time" cannot drift from the SQL that computes it.
OUT_OF_TIME_DEFINITION = (
    "A day is counted Out of Time when the employee's first badge-in for that "
    "shift is later than their scheduled start time by one minute or more. "
    "There is no grace period. Days with no scheduled start on file are not "
    "scored at all \u2014 they count as neither on time nor out of time."
)


def _first_punch_cte(start_placeholder: str, end_placeholder: str) -> str:
    """CTE body (no leading `WITH`) yielding every punch in range, annotated with
    normalized department + job_title + name + team, and the employee's expected
    arrival time from `late_arrival_schedule`.

    The placeholders ($1, $2, ...) are passed in by the caller — they must
    line up with the corresponding values in the params list.

    The scan is widened by a day either side of the requested range: a night
    shift that began the evening before the window, or ends the morning after,
    must be assembled whole before it can be attributed to the right shift date.
    """
    before, after = _ARRIVAL_WINDOW
    return f"""
    punches AS (
        SELECT
            TRIM(z.full_name)                                AS nm,
            lower(btrim(z.email))                            AS em,
            z.event_time,
            TRIM(e.job_title)                                AS jt,
            {_DEPARTMENT_NORMALIZED}                         AS dep,
            {_TEAM_LABEL_EXPR}                               AS team,
            COALESCE(e.display_name, z.full_name)            AS ident
        FROM public.zk_gld_onlyfingerprint z
        JOIN public.timeoff_employee e
          ON TRIM(z.email) = TRIM(e.email)
         AND COALESCE(e.email, '') <> ''
        -- LEFT, never INNER: two DFW people have no row in the auth roster and
        -- an inner join would silently drop them from every KPI.
        LEFT JOIN public.app_auth_users u
          ON lower(btrim(u.email)) = lower(btrim(e.email))
         {_EXCLUDE_IT_SQL}
        WHERE z.event_date BETWEEN ({start_placeholder}::date - 1)
                               AND ({end_placeholder}::date + 1)
    ),
    scheduled AS (
        SELECT p.*, {_EXPECTED_TIME_LOOKUP} AS expected_time
        FROM punches p
    ),
    attributed AS (
        SELECT a.*, {_SHIFT_DATE_EXPR} AS shift_date
        FROM scheduled a
    ),
    first_punch AS (
        SELECT
            r.nm, r.em, r.jt, r.dep, r.team, r.event_time,
            r.shift_date AS event_date,
            CASE WHEN r.expected_time IS NULL THEN NULL
                 ELSE r.shift_date + r.expected_time END AS expected,
            ROW_NUMBER() OVER (
                PARTITION BY r.shift_date, r.ident
                ORDER BY r.event_time ASC
            ) AS rn
        FROM attributed r
        WHERE r.expected_time IS NULL
           OR (r.event_time >= r.shift_date + r.expected_time - {before}
          AND  r.event_time <= r.shift_date + r.expected_time + {after})
    )
    """


def _scored_cte(
    start_placeholder: str,
    end_placeholder: str,
    alias: str = "scored",
) -> str:
    """CTE that keeps only the arrival row per (employee, shift date), then
    narrows back to the requested range.

    Input: `first_punch`. Output: one row per (employee, shift). The expected
    timestamp is already attached upstream, because shift-date attribution needs
    the expected time to know whether the shift crosses midnight.

    The range filter belongs HERE, not in `first_punch`: that CTE deliberately
    over-scans by a day either side so overnight shifts can be assembled whole.
    Narrowing after `rn` is computed is safe — `rn` partitions by shift_date, so
    dropping whole shift dates cannot renumber the ones that remain."""
    return f"""
    {alias} AS (
        SELECT nm, jt, dep, team, event_date, event_time, expected
        FROM first_punch
        WHERE rn = 1
          AND event_date BETWEEN {start_placeholder}::date AND {end_placeholder}::date
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
        {_scored_cte('$1', 'CURRENT_DATE')}
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
             {_scored_cte('$1', '$2')}
        SELECT
          COUNT(DISTINCT nm)                                           AS log_in_employees,
          COUNT(*) FILTER (WHERE {_NOT_ON_TIME_REF_PREDICATE})                     AS not_on_time_ref,
          COUNT(*) FILTER (WHERE {_ON_TIME_PREDICATE})           AS on_time,
          COUNT(*) FILTER (WHERE {_OUT_OF_TIME_PREDICATE})          AS out_of_time,
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
             {_scored_cte('$1', '$2')}
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
             {_scored_cte('$1', '$2')}
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
             {_scored_cte('$1', '$2')}
        SELECT
          event_date::text AS event_date,
          COUNT(*) FILTER (WHERE {_ON_TIME_PREDICATE})  AS on_time,
          COUNT(*) FILTER (WHERE {_OUT_OF_TIME_PREDICATE}) AS out_of_time
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
             {_scored_cte('$1', '$2')}
        SELECT
          COALESCE(dep, '—')                                              AS department,
          COUNT(*) FILTER (WHERE {_ON_TIME_PREDICATE})              AS on_time,
          COUNT(*) FILTER (WHERE {_OUT_OF_TIME_PREDICATE})             AS out_of_time,
          COUNT(*) FILTER (WHERE {_NOT_ON_TIME_REF_PREDICATE})                        AS unscored
        FROM scored
        WHERE 1=1 {filters_sql}
        GROUP BY COALESCE(dep, '—')
        ORDER BY (
          COUNT(*) FILTER (WHERE {_ON_TIME_PREDICATE})
          + COUNT(*) FILTER (WHERE {_OUT_OF_TIME_PREDICATE})
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
