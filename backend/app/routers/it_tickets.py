"""Code-made report: IT Tickets Mgmt.

Portal-native replacement for Bruno's Qlik app
``86da731f-577f-45d3-9d40-c416649a4937`` ("IT Managed Services" — sheets
``RqXzx`` Incidents and ``8aae69c7-…`` Service Request).

Source: ``it_route."Ticket" ⨝ "User"`` -- own pool via ``get_itroute_pool``
(env var ``IT_ROUTE_DATABASE_URL``, role ``spaceqlik_itroute_ro``, SELECT on
those two tables only). IT ROUTE is the in-house ticketing app
(/BOT/ticket-system, route.unilinkportal.com) that replaced FreshService on
2026-08-24 with the full FreshService history imported.

⚠ Until 2026-10-01 this report read ``fresh_services_unlk."Tickets"``, the
Spark mirror of FreshService, which froze on 2026-04-15 when the FreshService
relationship ended — so it showed nothing after that date. Re-pointed here; on
the overlap (2025-01-01..2026-04-14) both sources select the same population
to within 0.5% (1,306 vs 1,303 incidents; 4,037 vs 4,015 service requests).

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

Agents: ``"Ticket"."responderId" = "User".id``, shown by first name.

Status mapping — IT ROUTE's enum to the FreshService labels the page always
used: OPEN Open · IN_PROGRESS In Progress · PENDING Pending · WAITING_ON_USER
Waiting for user response · RESOLVED Resolved · CLOSED Closed. CANCELLED is
dropped, as FreshService's "Cancelled" category always was.

Performance:
  * ``"Ticket"`` is ~20k rows with IT ROUTE's own indexes (type, status,
    createdAt, responderId).
  * Half-open date range (``>= $s AND < $e + 1d``) keeps queries sargable.
  * Single ``/summary`` endpoint returns all KPIs + chart data in one
    round-trip — avoids 8 separate API hits per page load.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request

from app.clock import cst_today
from app.routers.deps import get_itroute_pool, require_user

router = APIRouter(tags=["it-tickets"], prefix="/custom/it-tickets")

HISTORY_FLOOR = date(2025, 1, 1)

# IT ROUTE's TicketType enum values; TYPE_LABELS keeps the API's human label.
TYPE_SERVICE_REQUEST = "SERVICE_REQUEST"
TYPE_INCIDENT = "INCIDENT"
TYPE_LABELS = {TYPE_SERVICE_REQUEST: "Service Request", TYPE_INCIDENT: "Incident"}
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
# The FreshService mirror stopped on 2026-04-15 and the report kept rendering
# — an empty window read as "a quiet month". /summary reports the newest write
# in the UNFILTERED source table; older than this ⇒ the page says the source
# is stale. 72 h so an ordinary weekend with no ticket activity does not alarm.
STALE_AFTER = timedelta(hours=72)

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
# ⚠ IT ROUTE (Prisma `DateTime`) stores every timestamp as NAIVE UTC
# (`timestamp without time zone`; tickets peak at 13:00-22:00 = 8 AM-5 PM CST)
# — exactly as the FreshService mirror before it did. They are
# made `timestamptz` HERE, once, so that under the pool's CST session every
# `::date`, `date_trunc` and window bound below is a CST day, and the API emits
# offset-qualified ISO strings the browser cannot misread as local time.
# Before 2026-10-01 a ticket opened after 7 PM CST was bucketed on the next
# day, and every time in the tables printed 5-6 h late (SPEC-CODE-RULES §116).
#
# Placeholders (in order): $1 = Type (IT ROUTE enum value, compared as text)
_STATUS_LABEL = """CASE tk.status::text
      WHEN 'OPEN'            THEN 'Open'
      WHEN 'IN_PROGRESS'     THEN 'In Progress'
      WHEN 'PENDING'         THEN 'Pending'
      WHEN 'WAITING_ON_USER' THEN 'Waiting for user response'
      WHEN 'RESOLVED'        THEN 'Resolved'
      WHEN 'CLOSED'          THEN 'Closed'
      ELSE initcap(tk.status::text) END"""

# An agent is an IT ROUTE "User"; FreshService's FirstName is "firstName"
# here, which is null on some accounts — fall back to the first word of name.
_AGENT_FIRST_NAME = """COALESCE(NULLIF(a."firstName", ''), split_part(a.name, ' ', 1))"""

_BASE_CTE = f"""
WITH t AS (
  SELECT
    tk."displayId"                                       AS id,
    tk.sequence                                          AS seq,
    tk.subject                                           AS subject,
    tk."requesterName"                                   AS name,
    tk."requesterEmail"                                  AS email,
    tk.category                                          AS category,
    tk."subCategory"                                     AS sub_category,
    tk."itemCategory"                                    AS item_category,
    initcap(tk.priority::text)                           AS priority,
    tk.type::text                                        AS type,
    {_STATUS_LABEL}                                      AS status,
    tk."responderId"                                     AS responder_id,
    (tk."dueBy" AT TIME ZONE 'UTC')                      AS due_by,
    (tk."frDueBy" AT TIME ZONE 'UTC')                    AS first_resp_due,
    (tk."createdAt" AT TIME ZONE 'UTC')                  AS created_date,
    (tk."updatedAt" AT TIME ZONE 'UTC')                  AS updated_date
  FROM "Ticket" tk
  WHERE NOT tk."isDeleted"
    AND tk.status::text <> 'CANCELLED'
    AND tk.subject NOT ILIKE '%test%'
    AND tk.category NOT IN ({", ".join(f"'{c}'" for c in EXCLUDED_CATEGORIES)})
    AND tk."createdAt" >= '2025-01-01'
    AND tk.type::text = $1
)
"""


# Newest write anywhere in "Ticket" — no type / category / isDeleted filter,
# so it measures the SOURCE, not the slice the page is showing. Kept after the
# move to IT ROUTE: the FreshService mirror died silently for 5½ months.
_FRESHNESS_SQL = """
SELECT max("updatedAt") AT TIME ZONE 'UTC' FROM "Ticket"
"""


def _freshness(last_synced: Optional[datetime], now: datetime) -> dict:
    """`{last_synced, stale}` for the page's "Data as of" pill / stale banner."""
    if last_synced is None:
        return {"last_synced": None, "stale": True}
    return {
        "last_synced": last_synced.isoformat(),
        "stale": now - last_synced > STALE_AFTER,
    }


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

    pool = get_itroute_pool(request)

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
          date_trunc('month', created_date)::date                 AS month_start,
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
          AND created_date >= $2::date AND created_date < $3::date
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
          AND created_date >= $2::date AND created_date < $3::date
        GROUP BY 1, 2
        ORDER BY 1, 2
        """
    )

    # --------------------------------------------------- Agents (pending only)
    by_agent_sql = (
        _BASE_CTE
        + f"""
        SELECT
          COALESCE({_AGENT_FIRST_NAME}, 'Unassigned') AS first_name,
          COUNT(*)                              AS cnt
        FROM t
        LEFT JOIN "User" a ON t.responder_id = a.id
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
        WHERE created_date >= $2::date AND created_date < $3::date
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
        WHERE created_date >= $2::date AND created_date < $3::date
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
        last_synced = await conn.fetchval(_FRESHNESS_SQL)

    pending_now = kpi["pending_now"] or 0
    closed = kpi["closed"] or 0
    total = kpi["total"] or 0

    pct_open = round((pending_now / total) * 100, 1) if total else 0.0
    pct_closed = round((closed / total) * 100, 1) if total else 0.0

    return {
        "success": True,
        "data": {
            "type": TYPE_LABELS[type_value],
            "range": {"start": s.isoformat(), "end": e.isoformat()},
            "freshness": _freshness(last_synced, datetime.now(timezone.utc)),
            "kpis": {
                "pending_now": pending_now,
                "closed": closed,
                "total": total,
                "pct_open": pct_open,
                "pct_closed": pct_closed,
            },
            "by_month": [
                {
                    "month_start": r["month_start"].isoformat(),
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
    "id": "t.seq",  # display id INC-1234 sorts by its number
    "created": "t.created_date",
    "category": "t.category",
    "sub_category": "t.sub_category",
    "item_category": "t.item_category",
    "agent": _AGENT_FIRST_NAME,
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
          {_AGENT_FIRST_NAME} AS agent_first_name,
          t.name, t.subject, t.status, t.due_by, t.updated_date,
          COUNT(*) OVER () AS total_count
        FROM t
        LEFT JOIN "User" a ON t.responder_id = a.id
        WHERE t.created_date >= $2::date AND t.created_date < $3::date
          AND t.status IN ({status_in})
        ORDER BY {sort_col} {sort_dir}, t.seq DESC
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
    pool = get_itroute_pool(request)

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
    pool = get_itroute_pool(request)

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
