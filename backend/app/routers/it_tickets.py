"""Code-made report: IT Tickets Mgmt.

Portal-native replacement for Bruno's Qlik app
``86da731f-577f-45d3-9d40-c416649a4937`` ("IT Managed Services" — sheets
``RqXzx`` Incidents and ``8aae69c7-…`` Service Request).

Source: ``fresh_services_unlk."Tickets" ⨝ "Agents"`` -- own pool via
``get_freshservice_pool`` (env var ``FRESHSERVICE_DATABASE_URL``). The
table is loaded by an external Spark ETL (not n8n).

Access: any authenticated user (gated only by ``require_user``); seed.py
grants the report to every TagRole so it surfaces for everyone.

Bruno's PDF visuals (preserved):
  * Filter: date range
  * Type tabs at the page level (Service Request / Incident) — picks
    which side of the dataset every panel works against.
  * 4 KPI cards: Pending Now, % Open, Closed, % Closed
  * Stacked bar: # Pending Tickets by Month (last 12 calendar months,
    ignoring filter — matches Bruno's ``If(MonthStart >= AddMonths(...,-12))``
    behavior so users have stable trend context regardless of filter)
  * Pie: Status, Pie: Priority
  * Stacked bar: Created Date by Week (Pending only)
  * Stacked bar: Created Date by Day (Pending only)
  * Bar: Agents Assignments (Pending only, by FirstName)
  * History panel with Status / Category sub-tabs (stacked bar by day,
    respects the date filter)
  * Two paginated detail tables: Pending and Closed

Bruno's PDF SQL had a JOIN bug (``ON t.Id = a.Id`` matches 0 rows since
ticket IDs are 17xxx and agent IDs are 21000xxx). Corrected here to
``ON t."ResponderId" = a."Id"``.

Status code mapping (mirrors Bruno's CASE):
  '6' -> 'In Progress'
  '8' -> 'Waiting for user response'
  others (Pending/Open/Closed/Resolved) pass through.

Performance:
  * Indexes added 2026-04-28 via avnadmin: ``idx_tickets_created``,
    ``idx_tickets_type_status_active`` (partial), ``idx_tickets_responder``,
    ``idx_tickets_updated``.
  * Half-open date range (``>= $s AND < $e + 1d``) keeps queries sargable.
  * Single ``/summary`` endpoint returns all KPIs + chart data in one
    round-trip — avoids 8 separate API hits per page load.
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request

from app.clock import cst_today
from app.routers.deps import get_freshservice_pool, require_user

router = APIRouter(tags=["it-tickets"], prefix="/custom/it-tickets")

HISTORY_FLOOR = date(2025, 1, 1)

TYPE_SERVICE_REQUEST = "Service Request"
TYPE_INCIDENT = "Incident"
TYPES = (TYPE_SERVICE_REQUEST, TYPE_INCIDENT)

# Bruno's exclusion lists — kept in source SQL since they're domain rules.
EXCLUDED_CATEGORIES = (
    "Onboarding",
    "Offboarding",
    "Cancelled",
    "Canceled",
    "Test (IT)",
)

# Statuses that count as "open / pending" in every KPI Bruno authored.
PENDING_STATUSES = ("Pending", "Open", "In Progress", "Waiting for user response")
CLOSED_STATUSES = ("Closed", "Resolved")


# ---------------------------------------------------------------------------
# Range / type helpers
# ---------------------------------------------------------------------------


def _today() -> date:
    return cst_today()


def _resolve_range(
    rng: Optional[str],
    start_date: Optional[date],
    end_date: Optional[date],
) -> tuple[date, date]:
    """Map a preset name + optional explicit dates to a (start, end) window.

    Default is "last_30d". All windows are clamped to ``[HISTORY_FLOOR, today]``.
    """
    today = _today()
    rng = (rng or "last_30d").lower()

    if rng == "today":
        return today, today
    if rng == "wtd":
        return today - timedelta(days=today.weekday()), today
    if rng == "last_7d":
        return today - timedelta(days=6), today
    if rng == "last_30d":
        return today - timedelta(days=29), today
    if rng == "mtd":
        return today.replace(day=1), today
    if rng == "last_month":
        first_this = today.replace(day=1)
        last_prev = first_this - timedelta(days=1)
        first_prev = last_prev.replace(day=1)
        return first_prev, last_prev
    if rng == "ytd":
        return today.replace(month=1, day=1), today
    if rng == "custom":
        s = start_date or today.replace(day=1)
        e = end_date or today
        if e < s:
            s, e = e, s
        return s, e

    return today - timedelta(days=29), today


def _clamp(s: date, e: date) -> tuple[date, date]:
    today = _today()
    if s < HISTORY_FLOOR:
        s = HISTORY_FLOOR
    if e > today:
        e = today
    if e < s:
        s, e = e, s
    return s, e


def _coerce_type(type_param: Optional[str]) -> str:
    """Normalize the ``type`` query param to either Service Request / Incident."""
    if not type_param:
        return TYPE_SERVICE_REQUEST
    t = type_param.strip().lower().replace("_", " ").replace("-", " ")
    if t in {"service request", "servicerequest", "service", "request", "sr"}:
        return TYPE_SERVICE_REQUEST
    if t in {"incident", "incidents"}:
        return TYPE_INCIDENT
    raise HTTPException(
        status_code=400,
        detail="Invalid type — must be 'service_request' or 'incident'",
    )


# ---------------------------------------------------------------------------
# Shared SQL fragments
# ---------------------------------------------------------------------------

# CTE that applies all of Bruno's domain filters and the status-code mapping
# in one place. Every endpoint starts from this CTE so the filter set stays
# single-source-of-truth.
#
# Placeholders (in order): $1 = Type
_BASE_CTE = f"""
WITH t AS (
  SELECT
    "Id"                                                 AS id,
    "Subject"                                            AS subject,
    "Name"                                               AS name,
    "Email"                                              AS email,
    "Category"                                           AS category,
    "SubCategory"                                        AS sub_category,
    "ItemCategory"                                       AS item_category,
    "Priority"                                           AS priority,
    "Source"                                             AS source,
    "Type"                                               AS type,
    CASE WHEN "Status" = '6' THEN 'In Progress'
         WHEN "Status" = '8' THEN 'Waiting for user response'
         ELSE "Status" END                               AS status,
    "ResponderId"                                        AS responder_id,
    "DueBy"                                              AS due_by,
    "FirstResponseDueBy"                                 AS first_resp_due,
    "CreatedDate"                                        AS created_date,
    "UpdatedDate"                                        AS updated_date
  FROM "Tickets"
  WHERE "_active_value" = TRUE
    AND "Subject" NOT ILIKE '%test%'
    AND "Category" NOT IN ({", ".join(f"'{c}'" for c in EXCLUDED_CATEGORIES)})
    AND "CreatedDate" >= '2025-01-01'
    AND "Type" = $1
)
"""


def _type_only_params(type_value: str) -> list:
    return [type_value]


def _windowed_params(type_value: str, s: date, e: date) -> list:
    """Params for queries that filter by created_date in [s, e+1)."""
    return [type_value, s, e + timedelta(days=1)]


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.get("/summary")
async def summary(
    request: Request,
    type: Optional[str] = Query(None),
    range: Optional[str] = Query(None),
    start: Optional[date] = Query(None),
    end: Optional[date] = Query(None),
    user: dict = Depends(require_user),
) -> dict:
    """Single round-trip: KPIs + every chart series for the dashboard.

    The ``range`` filter only drives (a) the History panel and (b) the
    "Created by Week / Day" pending charts. The "Pending by Month" chart
    intentionally ignores the filter so it always shows a stable 12-month
    context (matches Bruno's Qlik expression).
    """
    type_value = _coerce_type(type)
    s, e = _clamp(*_resolve_range(range, start, end))
    e_plus = e + timedelta(days=1)

    pool = get_freshservice_pool(request)

    # ------------------------------------------------------------------ KPIs
    kpi_sql = (
        _BASE_CTE
        + """
        SELECT
          COUNT(*) FILTER (WHERE status IN ('Pending','Open','In Progress','Waiting for user response')) AS pending_now,
          COUNT(*) FILTER (WHERE status IN ('Closed','Resolved'))                                        AS closed,
          COUNT(*)                                                                                       AS total
        FROM t
        """
    )

    # --------------------------------------------------- Pending by Month (12)
    # Last 12 full months including current month, ignoring the date filter.
    by_month_sql = (
        _BASE_CTE
        + """
        SELECT
          to_char(date_trunc('month', created_date), 'Mon YYYY') AS month_label,
          date_trunc('month', created_date)                       AS month_start,
          COALESCE(NULLIF(category, ''), 'Other')                AS category,
          COUNT(*) AS cnt
        FROM t
        WHERE status IN ('Pending','Open','In Progress','Waiting for user response')
          AND created_date >= date_trunc('month', CURRENT_DATE) - INTERVAL '11 months'
        GROUP BY 1, 2, 3
        ORDER BY 2, 3
        """
    )

    # ------------------------------------------------------ Status / Priority
    status_sql = (
        _BASE_CTE
        + """
        SELECT status, COUNT(*) AS cnt
        FROM t
        WHERE status IN ('Pending','Open','In Progress','Waiting for user response')
        GROUP BY 1
        ORDER BY 2 DESC
        """
    )

    priority_sql = (
        _BASE_CTE
        + """
        SELECT COALESCE(NULLIF(priority, ''), 'Unset') AS priority, COUNT(*) AS cnt
        FROM t
        WHERE status IN ('Pending','Open','In Progress','Waiting for user response')
        GROUP BY 1
        ORDER BY 2 DESC
        """
    )

    # ------------------------------------------------ Pending by Week / Day
    # Both respect the date filter (these panels are about *recent*
    # pending arrivals — they need to follow the user's window).
    by_week_pending_sql = (
        _BASE_CTE
        + """
        SELECT
          date_trunc('week', created_date)::date              AS week_start,
          COALESCE(NULLIF(category, ''), 'Other')             AS category,
          COUNT(*)                                            AS cnt
        FROM t
        WHERE status IN ('Pending','Open','In Progress','Waiting for user response')
          AND created_date >= $2 AND created_date < $3
        GROUP BY 1, 2
        ORDER BY 1, 2
        """
    )

    by_day_pending_sql = (
        _BASE_CTE
        + """
        SELECT
          created_date::date                                  AS day,
          COALESCE(NULLIF(category, ''), 'Other')             AS category,
          COUNT(*)                                            AS cnt
        FROM t
        WHERE status IN ('Pending','Open','In Progress','Waiting for user response')
          AND created_date >= $2 AND created_date < $3
        GROUP BY 1, 2
        ORDER BY 1, 2
        """
    )

    # --------------------------------------------------- Agents (pending only)
    by_agent_sql = (
        _BASE_CTE
        + """
        SELECT
          COALESCE(a."FirstName", 'Unassigned') AS first_name,
          COUNT(*)                              AS cnt
        FROM t
        LEFT JOIN "Agents" a ON t.responder_id = a."Id"
        WHERE t.status IN ('Pending','Open','In Progress','Waiting for user response')
        GROUP BY 1
        ORDER BY 2 DESC
        """
    )

    # ------------------------------------------------------------ History
    history_status_sql = (
        _BASE_CTE
        + """
        SELECT
          created_date::date AS day,
          status,
          COUNT(*)           AS cnt
        FROM t
        WHERE created_date >= $2 AND created_date < $3
        GROUP BY 1, 2
        ORDER BY 1, 2
        """
    )

    history_category_sql = (
        _BASE_CTE
        + """
        SELECT
          COALESCE(NULLIF(category, ''), 'Other') AS category,
          COUNT(*)                                AS cnt
        FROM t
        WHERE created_date >= $2 AND created_date < $3
        GROUP BY 1
        ORDER BY 2 DESC
        """
    )

    p_type = _type_only_params(type_value)
    p_window = _windowed_params(type_value, s, e)

    async with pool.acquire() as conn:
        kpi = await conn.fetchrow(kpi_sql, *p_type)
        by_month = await conn.fetch(by_month_sql, *p_type)
        status_rows = await conn.fetch(status_sql, *p_type)
        priority_rows = await conn.fetch(priority_sql, *p_type)
        by_week_pending = await conn.fetch(by_week_pending_sql, *p_window)
        by_day_pending = await conn.fetch(by_day_pending_sql, *p_window)
        by_agent = await conn.fetch(by_agent_sql, *p_type)
        history_status = await conn.fetch(history_status_sql, *p_window)
        history_category = await conn.fetch(history_category_sql, *p_window)

    pending_now = kpi["pending_now"] or 0
    closed = kpi["closed"] or 0
    total = kpi["total"] or 0

    pct_open = round((pending_now / total) * 100, 1) if total else 0.0
    pct_closed = round((closed / total) * 100, 1) if total else 0.0

    return {
        "success": True,
        "data": {
            "type": type_value,
            "range": {"start": s.isoformat(), "end": e.isoformat()},
            "kpis": {
                "pending_now": pending_now,
                "closed": closed,
                "total": total,
                "pct_open": pct_open,
                "pct_closed": pct_closed,
            },
            "by_month": [
                {
                    "month_start": r["month_start"].date().isoformat(),
                    "month_label": r["month_label"],
                    "category": r["category"],
                    "cnt": r["cnt"],
                }
                for r in by_month
            ],
            "status": [
                {"status": r["status"], "cnt": r["cnt"]} for r in status_rows
            ],
            "priority": [
                {"priority": r["priority"], "cnt": r["cnt"]}
                for r in priority_rows
            ],
            "by_week_pending": [
                {
                    "week_start": r["week_start"].isoformat(),
                    "category": r["category"],
                    "cnt": r["cnt"],
                }
                for r in by_week_pending
            ],
            "by_day_pending": [
                {
                    "day": r["day"].isoformat(),
                    "category": r["category"],
                    "cnt": r["cnt"],
                }
                for r in by_day_pending
            ],
            "by_agent": [
                {"agent": r["first_name"], "cnt": r["cnt"]} for r in by_agent
            ],
            "history_status": [
                {
                    "day": r["day"].isoformat(),
                    "status": r["status"],
                    "cnt": r["cnt"],
                }
                for r in history_status
            ],
            "history_category": [
                {"category": r["category"], "cnt": r["cnt"]}
                for r in history_category
            ],
        },
    }


_TABLE_COLUMNS = {
    "id": "t.id",
    "created": "t.created_date",
    "category": "t.category",
    "sub_category": "t.sub_category",
    "item_category": "t.item_category",
    "agent": 'a."FirstName"',
    "name": "t.name",
    "subject": "t.subject",
    "status": "t.status",
    "due_by": "t.due_by",
    "updated": "t.updated_date",
}


def _normalize_sort(sort: str | None, fallback: str) -> tuple[str, str]:
    """Return (sql_column, direction). Direction is ASC or DESC."""
    if not sort:
        return _TABLE_COLUMNS[fallback], "DESC" if fallback == "updated" else "ASC"
    raw = sort.strip()
    direction = "ASC"
    if raw.startswith("-"):
        direction = "DESC"
        raw = raw[1:]
    col = _TABLE_COLUMNS.get(raw.lower())
    if not col:
        col = _TABLE_COLUMNS[fallback]
    return col, direction


async def _fetch_table(
    pool,
    type_value: str,
    s: date,
    e: date,
    filter_status: tuple[str, ...],
    page: int,
    page_size: int,
    sort: str | None,
    sort_fallback: str,
):
    sort_col, sort_dir = _normalize_sort(sort, sort_fallback)
    offset = max(0, (page - 1) * page_size)

    params = _windowed_params(type_value, s, e)
    # Build placeholder list for status IN (...)
    status_placeholders = []
    for st in filter_status:
        params.append(st)
        status_placeholders.append(f"${len(params)}")
    status_in = ", ".join(status_placeholders)

    base = (
        _BASE_CTE
        + f"""
        SELECT
          t.id, t.created_date, t.category, t.sub_category, t.item_category,
          a."FirstName" AS agent_first_name,
          t.name, t.subject, t.status, t.due_by, t.updated_date,
          COUNT(*) OVER () AS total_count
        FROM t
        LEFT JOIN "Agents" a ON t.responder_id = a."Id"
        WHERE t.created_date >= $2 AND t.created_date < $3
          AND t.status IN ({status_in})
        ORDER BY {sort_col} {sort_dir}, t.id DESC
        LIMIT {int(page_size)} OFFSET {int(offset)}
        """
    )

    rows = await pool.fetch(base, *params)
    total = rows[0]["total_count"] if rows else 0
    return [
        {
            "id": r["id"],
            "created": r["created_date"].isoformat() if r["created_date"] else None,
            "category": r["category"],
            "sub_category": r["sub_category"],
            "item_category": r["item_category"],
            "agent": r["agent_first_name"],
            "name": r["name"],
            "subject": r["subject"],
            "status": r["status"],
            "due_by": r["due_by"].isoformat() if r["due_by"] else None,
            "updated": r["updated_date"].isoformat() if r["updated_date"] else None,
        }
        for r in rows
    ], total


@router.get("/pending")
async def pending_table(
    request: Request,
    type: Optional[str] = Query(None),
    range: Optional[str] = Query(None),
    start: Optional[date] = Query(None),
    end: Optional[date] = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=500),
    sort: Optional[str] = Query(None),
    user: dict = Depends(require_user),
) -> dict:
    type_value = _coerce_type(type)
    s, e = _clamp(*_resolve_range(range, start, end))
    pool = get_freshservice_pool(request)

    rows, total = await _fetch_table(
        pool,
        type_value,
        s,
        e,
        PENDING_STATUSES,
        page,
        page_size,
        sort,
        sort_fallback="created",  # oldest pending first by default
    )
    return {
        "success": True,
        "data": rows,
        "meta": {"total": total, "page": page, "limit": page_size},
    }


@router.get("/closed")
async def closed_table(
    request: Request,
    type: Optional[str] = Query(None),
    range: Optional[str] = Query(None),
    start: Optional[date] = Query(None),
    end: Optional[date] = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=500),
    sort: Optional[str] = Query(None),
    user: dict = Depends(require_user),
) -> dict:
    type_value = _coerce_type(type)
    s, e = _clamp(*_resolve_range(range, start, end))
    pool = get_freshservice_pool(request)

    rows, total = await _fetch_table(
        pool,
        type_value,
        s,
        e,
        CLOSED_STATUSES,
        page,
        page_size,
        sort,
        sort_fallback="updated",  # most recently closed first
    )
    return {
        "success": True,
        "data": rows,
        "meta": {"total": total, "page": page, "limit": page_size},
    }
