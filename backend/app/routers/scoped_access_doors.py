"""Code-made reports: every scope-locked clone of `HR - Access Log Doors`.

One factory — `build_scoped_access_doors_router` — instantiated once per report.
The emitted SQL differs ONLY in the gate fragment, so all five reports stay
numerically comparable and a fix lands once:

  * ``DFW - Access Log Doors``                 -> ``dep = 'Operations (DFW)'``
  * ``Admin - Access Log Doors``               -> ``dep = 'Admin'``
  * ``OPS - Access Log Doors``                 -> ``dep = 'Operations'``
  * ``Pricing - Access Log Doors``             -> ``dep = 'Pricing'``
  * ``Carrier Procurement - Access Log Doors`` -> ``jt IN ('Carrier Procurement',
                                                  'Carrier Procurement Team Leader')``

History: DFW (2026-04-28) and Admin (2026-05-07) each began as a hand-written
~330-line router; the two were near-verbatim copies differing in one constant.
Bruno's PDF of 2026-08-12 asked for three more, which would have made five
copies — so that round introduced this factory for the three new reports, then
migrated DFW and Admin onto it. The migration was gated on a harness that
called every endpoint on both the old and new implementations with a stub pool
and diffed the emitted SQL + params: all 12 queries came out identical, so
neither live report changed.

Design rules:
  * the gate is a hard-coded SQL literal applied to `scored` in EVERY endpoint,
    so no query string can widen the scope (server-locked, not UI-locked)
  * the front-end therefore drops the Department dropdown entirely (and the
    Job Title dropdown too on Carrier Procurement, which is job-title-gated)
  * `/by-job-title` replaces HR's `/by-department` — a single-department report
    would render one useless bar
  * the rolling-30-day trend keeps the gate but ignores the user's date filter

Why `dep = 'Operations'` does NOT include DFW: `_DEPARTMENT_NORMALIZED` in
`hr_access_doors` folds `Operations DFW` into the distinct canonical spelling
`Operations (DFW)`, which already has its own report. Verified 2026-08-12
against `aivn_datalake_gold` (last 90d, first punch/day, IT excluded):
`Operations` 964 rows / 24 people · `Pricing` 385 / 7 · the two Carrier
Procurement titles 134 / 3 (all of them inside `Operations`).

The SQL fragments + helpers are imported from `hr_access_doors` so the
on-time-reference rule and the department-drift normalization stay in one place.
"""

from datetime import date, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, Query, Request

from app.clock import cst_today
from app.routers.deps import get_datalake_gold_pool, require_report_access
from app.routers.hr_access_doors import (
    _CHECK_MINUTES_EXPR,
    _NOT_ON_TIME_REF_PREDICATE,
    _ON_TIME_PREDICATE,
    _OUT_OF_TIME_PREDICATE,
    _first_punch_cte,
    _resolve_window,
    _scored_cte,
)

# Sort keys accepted by /rows. Identical to the DFW/Admin clones.
_SORT_SQL = {
    "event_time_desc": "event_time DESC, nm DESC",
    "event_time_asc": "event_time ASC, nm ASC",
    "check_desc": "check_minutes DESC NULLS LAST",
    "check_asc": "check_minutes ASC NULLS LAST",
    "name_asc": "nm ASC, event_time DESC",
    "job_title": "jt ASC, nm ASC",
}
_SORT_DEFAULT = "event_time DESC, nm DESC"


def _build_filters_sql(
    params: list,
    name: Optional[str],
    job_title: Optional[str],
    team: Optional[str] = None,
) -> str:
    """Append name/job_title/team filter values to `params` and return the AND
    fragment. Department is intentionally NOT a parameter — it's gated by the
    router's fixed `gate_sql`."""
    parts: list[str] = []
    if name:
        params.append(name)
        parts.append(f"nm = ${len(params)}")
    if job_title:
        params.append(job_title)
        parts.append(f"jt = ${len(params)}")
    if team:
        params.append(team)
        parts.append(f"team = ${len(params)}")
    return ("".join(f" AND {p}" for p in parts)) if parts else ""


def build_scoped_access_doors_router(
    *,
    report_key: str,
    gate_sql: str,
    scope_label: str,
) -> APIRouter:
    """Build a scope-locked Access Log Doors router.

    Args:
        report_key: stable custom-report key, e.g. ``"ops-access-doors"``. Drives
            both the URL prefix (``/custom/<key>``) and the
            ``require_report_access`` gate — the two must always agree.
        gate_sql: the fixed scope predicate, already prefixed with ``AND`` and
            written against the `scored` CTE columns (``dep`` / ``jt``). A SQL
            literal by design: it must never be user-supplied.
        scope_label: human-readable scope, used only in docstrings/logs.
    """
    router = APIRouter(tags=[report_key], prefix=f"/custom/{report_key}")
    guard = require_report_access(report_key)

    # ----------------------------------------------------------------------
    # /filters  -- dropdown options for name / job_title (no department)
    # ----------------------------------------------------------------------
    @router.get("/filters")
    async def filters(request: Request, _user: dict = Depends(guard)):
        """Distinct job titles + employee names inside the locked scope over the
        last 90 days. Department dropdown intentionally omitted — the report is
        locked server-side."""
        pool = get_datalake_gold_pool(request)
        since = cst_today() - timedelta(days=90)

        rows = await pool.fetch(
            f"""
            WITH {_first_punch_cte('$1', 'CURRENT_DATE')},
            {_scored_cte('$1', 'CURRENT_DATE')}
            SELECT DISTINCT jt AS job_title, nm AS full_name, team
            FROM scored
            WHERE 1=1 {gate_sql}
            """,
            since,
        )

        # "Team 1".."Team 5" ahead of Night / Weekend / Unassigned, rather than
        # the lexical order that would put "Night" between them.
        def team_sort(label: str) -> tuple:
            if label.startswith("Team "):
                return (0, int(label.split()[1]))
            return ({"Night": 1, "Weekend": 2}.get(label, 3), 0)

        return {
            "success": True,
            "data": {
                "job_titles": sorted({r["job_title"] for r in rows if r["job_title"]}),
                "names": sorted({r["full_name"] for r in rows if r["full_name"]}),
                "teams": sorted({r["team"] for r in rows if r["team"]}, key=team_sort),
                "today": cst_today().isoformat(),
            },
        }

    # ----------------------------------------------------------------------
    # /kpis
    # ----------------------------------------------------------------------
    @router.get("/kpis")
    async def kpis(
        request: Request,
        start_date: Optional[date] = Query(None, description="YYYY-MM-DD, default today"),
        end_date: Optional[date] = Query(None, description="YYYY-MM-DD, default today"),
        name: Optional[str] = Query(None),
        job_title: Optional[str] = Query(None),
        team: Optional[str] = Query(None),
        _user: dict = Depends(guard),
    ):
        pool = get_datalake_gold_pool(request)
        s, e = _resolve_window(start_date, end_date)

        params: list = [s, e]
        filters_sql = _build_filters_sql(params, name, job_title, team)

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
            WHERE 1=1 {gate_sql} {filters_sql}
            """,
            *params,
        )

        data = dict(row) if row else {}
        denom = int(data.get("total_rows") or 0) - int(data.get("not_on_time_ref") or 0)
        data["pct_on_time"] = float(data["on_time"]) / denom if denom > 0 else None
        data["pct_out_of_time"] = (
            float(data["out_of_time"]) / denom if denom > 0 else None
        )
        data["window"] = {"start": s.isoformat(), "end": e.isoformat()}
        return {"success": True, "data": data}

    # ----------------------------------------------------------------------
    # /rows
    # ----------------------------------------------------------------------
    @router.get("/rows")
    async def rows(
        request: Request,
        start_date: Optional[date] = Query(None),
        end_date: Optional[date] = Query(None),
        name: Optional[str] = Query(None),
        job_title: Optional[str] = Query(None),
        team: Optional[str] = Query(None),
        sort: str = Query("event_time_desc"),
        page: int = Query(1, ge=1),
        limit: int = Query(100, ge=1, le=500),
        _user: dict = Depends(guard),
    ):
        pool = get_datalake_gold_pool(request)
        s, e = _resolve_window(start_date, end_date)
        sort_sql = _SORT_SQL.get(sort, _SORT_DEFAULT)

        offset = (page - 1) * limit
        params: list = [s, e]
        filters_sql = _build_filters_sql(params, name, job_title, team)

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
              team                  AS team,
              expected              AS on_time_reference,
              CASE WHEN expected IS NULL THEN NULL ELSE {_CHECK_MINUTES_EXPR} END AS check_minutes
            FROM scored
            WHERE 1=1 {gate_sql} {filters_sql}
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
            WHERE 1=1 {gate_sql} {filters_sql}
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
                "team": r["team"],
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

    # ----------------------------------------------------------------------
    # /trend-30d  -- rolling 30-day line, still scope-locked
    # ----------------------------------------------------------------------
    @router.get("/trend-30d")
    async def trend_30d(
        request: Request,
        name: Optional[str] = Query(None),
        job_title: Optional[str] = Query(None),
        team: Optional[str] = Query(None),
        _user: dict = Depends(guard),
    ):
        """On-Time vs Out-of-Time per day, fixed-window last 30 days. Ignores the
        user-selected date filter (rolling 30d) but NOT the scope gate — unlike
        the HR original, which is deliberately global."""
        pool = get_datalake_gold_pool(request)
        end = cst_today()
        start = end - timedelta(days=29)  # inclusive 30-day window

        params: list = [start, end]
        filters_sql = _build_filters_sql(params, name, job_title, team)

        rows_out = await pool.fetch(
            f"""
            WITH {_first_punch_cte('$1', '$2')},
                 {_scored_cte('$1', '$2')}
            SELECT
              event_date::text AS event_date,
              COUNT(*) FILTER (WHERE {_ON_TIME_PREDICATE})  AS on_time,
              COUNT(*) FILTER (WHERE {_OUT_OF_TIME_PREDICATE}) AS out_of_time
            FROM scored
            WHERE 1=1 {gate_sql} {filters_sql}
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

    # ----------------------------------------------------------------------
    # /by-job-title  -- bar chart (replaces /by-department, dept is fixed)
    # ----------------------------------------------------------------------
    @router.get("/by-job-title")
    async def by_job_title(
        request: Request,
        start_date: Optional[date] = Query(None),
        end_date: Optional[date] = Query(None),
        name: Optional[str] = Query(None),
        team: Optional[str] = Query(None),
        _user: dict = Depends(guard),
    ):
        """On-Time vs Out-of-Time per job title inside the locked scope for the
        selected window. Ignores the job-title filter so the chart never
        collapses to a single bar."""
        pool = get_datalake_gold_pool(request)
        s, e = _resolve_window(start_date, end_date)

        params: list = [s, e]
        # job_title=None on purpose — the chart shows every title regardless of
        # the filter pill so the breakdown stays visible. `team` IS honoured:
        # narrowing to one team is the point of that filter, and a team spans
        # several job titles so the chart keeps more than one bar.
        filters_sql = _build_filters_sql(params, name, None, team)

        rows_out = await pool.fetch(
            f"""
            WITH {_first_punch_cte('$1', '$2')},
                 {_scored_cte('$1', '$2')}
            SELECT
              COALESCE(jt, '—')                                              AS job_title,
              COUNT(*) FILTER (WHERE {_ON_TIME_PREDICATE})              AS on_time,
              COUNT(*) FILTER (WHERE {_OUT_OF_TIME_PREDICATE})             AS out_of_time,
              COUNT(*) FILTER (WHERE {_NOT_ON_TIME_REF_PREDICATE})                        AS unscored
            FROM scored
            WHERE 1=1 {gate_sql} {filters_sql}
            GROUP BY COALESCE(jt, '—')
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

    return router


# --------------------------------------------------------------------------
# The scope-locked reports
# --------------------------------------------------------------------------

# `dep` values below are the CANONICAL spellings produced by
# `_DEPARTMENT_NORMALIZED` in hr_access_doors.py — not the raw source values.

# DFW + Admin: migrated here 2026-08-12 from `dfw_access_doors.py` /
# `admin_access_doors.py`, both deleted in the same commit (see the module
# docstring for how equivalence was proven before the swap).
# Exported: the DFW delays digest e-mail (`routers/dfw_access_doors_digest.py`)
# must be scoped by the SAME literal the on-screen report is locked to, or the
# nightly mail and the report a recipient opens to check it would disagree.
DFW_GATE_SQL = "AND dep = 'Operations (DFW)'"
DFW_SCOPE_LABEL = "Operations (DFW)"

dfw_router = build_scoped_access_doors_router(
    report_key="dfw-access-doors",
    gate_sql=DFW_GATE_SQL,
    scope_label=DFW_SCOPE_LABEL,
)

admin_router = build_scoped_access_doors_router(
    report_key="admin-access-doors",
    gate_sql="AND dep = 'Admin'",
    scope_label="Admin",
)

ops_router = build_scoped_access_doors_router(
    report_key="ops-access-doors",
    gate_sql="AND dep = 'Operations'",
    scope_label="Operations",
)

pricing_router = build_scoped_access_doors_router(
    report_key="pricing-access-doors",
    gate_sql="AND dep = 'Pricing'",
    scope_label="Pricing",
)

# Job-title-gated rather than department-gated (Request 6): both titles live in
# `dep = 'Operations'`, so this report is a strict subset of ops-access-doors.
carrier_procurement_router = build_scoped_access_doors_router(
    report_key="carrier-procurement-access-doors",
    gate_sql=(
        "AND jt IN ('Carrier Procurement', 'Carrier Procurement Team Leader')"
    ),
    scope_label="Carrier Procurement",
)
