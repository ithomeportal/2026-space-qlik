"""Code-made report: VoIP Calls Logs.

Portal-native replacement for Bruno's Qlik app
``3e30136b-050a-4f19-83ab-17a7d55a2fc3`` ("Vonage VoIP Calls").

Source: ``aivn_datalake_gold.public.vonage_gld_by_user`` -- shared pool via
``get_datalake_gold_pool`` (no new env var). The table is loaded by an
upstream pipeline (not n8n) and is fresh through the current minute.

Access: any authenticated user (gated only by ``require_user``). The home
page hides reports the user has no role for, but seed.py grants this
report to every TagRole, so it reaches everyone.

Bruno's PDF visuals (preserved verbatim):
  * Filter Panel (date / call_direction / calling_party text search)
  * Detail table: Type, Start, Identif, Call Details, End, Call ID,
    Call Duration (Min) = (end - start) * 24 * 60
  * Pie: Count by call_direction
  * Combo bar+line: Count + avg duration per day
  * Hour-of-day line — but rebuilt to span the SELECTED window instead
    of just one date (Bruno's chart was misleading otherwise)

New panels (don't exist in Bruno's):
  * KPI strip: total calls, unique users, avg/total duration, %inbound,
    %short-calls (<30s)
  * DOW × hour heatmap (count)
  * Top 20 users by call count + by talk-time

Performance:
  * Indexes added 2026-04-26: ``idx_vonage_gld_by_user_start`` (single col)
    + ``idx_vonage_gld_by_user_start_dir`` (composite). Queries are
    bounded by ``start`` so they stay on the new btree (~30ms/MTD).
  * The "trend-daily" endpoint is in-process cached for 60s — multi-user
    dashboards share one DB hit.
  * Floor for ``start`` is hard-clamped to ``2025-01-01`` server-side
    (Bruno's WHERE-clause floor; avoids accidental scans of 2023-2024).
"""

from __future__ import annotations

import time
from datetime import date, datetime, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request

from app.routers.deps import get_datalake_gold_pool, require_user

router = APIRouter(tags=["voip-calls"], prefix="/custom/voip-calls")

# History floor matches Bruno's ``WHERE start >= '2025-01-01'`` and prevents
# accidental queries against the 1.6M-row 2023-2024 archive.
HISTORY_FLOOR = date(2025, 1, 1)
TODAY_CEIL_GUARD = timedelta(days=1)  # allow "today" to include now+epsilon

DIRECTIONS = ("INBOUND", "OUTBOUND", "INTRA_PBX")


# ---------------------------------------------------------------------------
# Date / range helpers
# ---------------------------------------------------------------------------


def _today() -> date:
    return date.today()


def _resolve_range(
    rng: Optional[str],
    start_date: Optional[date],
    end_date: Optional[date],
) -> tuple[date, date]:
    """Map a preset name + optional explicit dates to a (start, end) window.

    Default is WTD (Monday → today, inclusive). All windows are clamped
    to ``[HISTORY_FLOOR, today]``.
    """
    today = _today()
    rng = (rng or "wtd").lower()

    if rng == "today":
        return today, today
    if rng == "last_7d":
        return today - timedelta(days=6), today
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

    # default → WTD: ISO Monday → today (inclusive)
    monday = today - timedelta(days=today.weekday())
    return monday, today


def _clamp(s: date, e: date) -> tuple[date, date]:
    today = _today()
    if s < HISTORY_FLOOR:
        s = HISTORY_FLOOR
    if e > today:
        e = today
    if e < s:
        s, e = e, s
    return s, e


def _direction_filter(direction: Optional[str]) -> Optional[str]:
    """Validate ``direction`` against the known set; return None if 'all'."""
    if not direction:
        return None
    d = direction.strip().upper()
    if d in {"", "ALL"}:
        return None
    if d not in DIRECTIONS:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid direction '{direction}'. Allowed: {','.join(DIRECTIONS)}.",
        )
    return d


def _scope_where(
    s: date,
    e: date,
    direction: Optional[str],
    search: Optional[str],
    params: list,
) -> str:
    """Build the shared WHERE for vonage_gld_by_user.

    ``end`` is treated as inclusive on the day boundary by adding +1d and
    using ``< $end+1d`` -- avoids dropping the last day's tail entries.
    Always seeds the date range first so the index can drive the scan.
    """
    params.append(s)
    p_start = len(params)
    params.append(e + timedelta(days=1))
    p_end = len(params)

    parts = [
        f"start >= ${p_start}",
        f"start <  ${p_end}",
    ]

    if direction:
        params.append(direction)
        parts.append(f"call_direction = ${len(params)}")

    if search:
        # Free-text search across the four "who/where" columns. Phone
        # numbers and extensions are short enough that ILIKE on a few-day
        # range still hits the start-index first, so the filter stays cheap.
        params.append(f"%{search.strip()}%")
        p = len(params)
        parts.append(
            f"(calling_party ILIKE ${p} OR calling_party_identif ILIKE ${p} "
            f"OR caller_id ILIKE ${p} OR dnis ILIKE ${p} OR username ILIKE ${p} "
            f"OR call_details ILIKE ${p})"
        )

    return " AND ".join(parts)


# ---------------------------------------------------------------------------
# In-process cache for the daily trend (multi-user dashboards share it).
# Key includes window+direction+search so cross-filter switches still hit
# fresh data; TTL kept tight (60s) since the source updates every minute.
# ---------------------------------------------------------------------------

_TREND_CACHE: dict[tuple, tuple[float, list]] = {}
_TREND_TTL = 60.0


def _cache_get(key: tuple):
    hit = _TREND_CACHE.get(key)
    if not hit:
        return None
    ts, value = hit
    if time.time() - ts > _TREND_TTL:
        _TREND_CACHE.pop(key, None)
        return None
    return value


def _cache_put(key: tuple, value):
    _TREND_CACHE[key] = (time.time(), value)
    # Trim if it grows too big (defensive — shouldn't happen with normal use).
    if len(_TREND_CACHE) > 256:
        for k in list(_TREND_CACHE)[:128]:
            _TREND_CACHE.pop(k, None)


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


def _common_window_params(
    range_: Optional[str],
    start_date: Optional[date],
    end_date: Optional[date],
):
    s, e = _resolve_range(range_, start_date, end_date)
    s, e = _clamp(s, e)
    return s, e


@router.get("/summary")
async def summary(
    request: Request,
    range: Optional[str] = Query("wtd"),
    start_date: Optional[date] = Query(None),
    end_date: Optional[date] = Query(None),
    direction: Optional[str] = Query(None),
    q: Optional[str] = Query(None, alias="q"),
    _user: dict = Depends(require_user),
):
    """KPI strip: total calls, unique users, avg/total duration, %dirs,
    %short calls (<30s).
    """
    pool = get_datalake_gold_pool(request)
    s, e = _common_window_params(range, start_date, end_date)
    d = _direction_filter(direction)

    params: list = []
    where = _scope_where(s, e, d, q, params)

    sql = f"""
    SELECT
      COUNT(*)                                                    AS total_calls,
      COUNT(DISTINCT NULLIF(username, ''))                        AS unique_users,
      COALESCE(AVG(EXTRACT(EPOCH FROM ("end" - start)) / 60.0), 0)::float AS avg_duration_min,
      COALESCE(SUM(EXTRACT(EPOCH FROM ("end" - start)) / 60.0), 0)::float AS total_duration_min,
      SUM(CASE WHEN call_direction = 'INBOUND'   THEN 1 ELSE 0 END) AS inbound,
      SUM(CASE WHEN call_direction = 'OUTBOUND'  THEN 1 ELSE 0 END) AS outbound,
      SUM(CASE WHEN call_direction = 'INTRA_PBX' THEN 1 ELSE 0 END) AS intra_pbx,
      SUM(CASE WHEN EXTRACT(EPOCH FROM ("end" - start)) < 30 THEN 1 ELSE 0 END) AS short_calls
    FROM public.vonage_gld_by_user
    WHERE {where}
    """

    row = await pool.fetchrow(sql, *params)
    total = (row["total_calls"] or 0) if row else 0
    inbound = (row["inbound"] or 0) if row else 0
    outbound = (row["outbound"] or 0) if row else 0
    intra = (row["intra_pbx"] or 0) if row else 0
    short_calls = (row["short_calls"] or 0) if row else 0

    return {
        "success": True,
        "data": {
            "total_calls":        total,
            "unique_users":       (row["unique_users"] or 0) if row else 0,
            "avg_duration_min":   row["avg_duration_min"] if row else 0.0,
            "total_duration_min": row["total_duration_min"] if row else 0.0,
            "inbound":            inbound,
            "outbound":           outbound,
            "intra_pbx":          intra,
            "pct_inbound":   (inbound  / total) if total else None,
            "pct_outbound":  (outbound / total) if total else None,
            "pct_intra_pbx": (intra    / total) if total else None,
            "short_calls":       short_calls,
            "pct_short_calls": (short_calls / total) if total else None,
        },
        "meta": {"window": {"start": s.isoformat(), "end": e.isoformat()}},
    }


@router.get("/by-direction")
async def by_direction(
    request: Request,
    range: Optional[str] = Query("wtd"),
    start_date: Optional[date] = Query(None),
    end_date: Optional[date] = Query(None),
    direction: Optional[str] = Query(None),
    q: Optional[str] = Query(None, alias="q"),
    _user: dict = Depends(require_user),
):
    """Pie data: [{direction, count}] sorted desc by count."""
    pool = get_datalake_gold_pool(request)
    s, e = _common_window_params(range, start_date, end_date)
    d = _direction_filter(direction)

    params: list = []
    where = _scope_where(s, e, d, q, params)

    sql = f"""
    SELECT call_direction, COUNT(*) AS count
    FROM public.vonage_gld_by_user
    WHERE {where}
    GROUP BY 1
    ORDER BY 2 DESC
    """
    rows = await pool.fetch(sql, *params)
    return {
        "success": True,
        "data": [
            {"direction": r["call_direction"], "count": r["count"]}
            for r in rows
        ],
        "meta": {"window": {"start": s.isoformat(), "end": e.isoformat()}},
    }


@router.get("/trend-daily")
async def trend_daily(
    request: Request,
    range: Optional[str] = Query("wtd"),
    start_date: Optional[date] = Query(None),
    end_date: Optional[date] = Query(None),
    direction: Optional[str] = Query(None),
    q: Optional[str] = Query(None, alias="q"),
    _user: dict = Depends(require_user),
):
    """Combo bar+line: per-day count and avg duration (minutes).

    Cached in-process for 60s keyed on (window, direction, search).
    """
    pool = get_datalake_gold_pool(request)
    s, e = _common_window_params(range, start_date, end_date)
    d = _direction_filter(direction)

    cache_key = ("trend", s, e, d or "_", (q or "").lower())
    cached = _cache_get(cache_key)
    if cached is not None:
        return {
            "success": True,
            "data": cached,
            "meta": {
                "window": {"start": s.isoformat(), "end": e.isoformat()},
                "cached": True,
            },
        }

    params: list = []
    where = _scope_where(s, e, d, q, params)

    sql = f"""
    SELECT
      start::date                                          AS day,
      COUNT(*)                                             AS count,
      AVG(EXTRACT(EPOCH FROM ("end" - start)) / 60.0)::float AS avg_duration_min
    FROM public.vonage_gld_by_user
    WHERE {where}
    GROUP BY 1
    ORDER BY 1
    """
    rows = await pool.fetch(sql, *params)
    out = [
        {
            "day": r["day"].isoformat(),
            "count": r["count"],
            "avg_duration_min": r["avg_duration_min"],
        }
        for r in rows
    ]
    _cache_put(cache_key, out)

    return {
        "success": True,
        "data": out,
        "meta": {
            "window": {"start": s.isoformat(), "end": e.isoformat()},
            "cached": False,
        },
    }


@router.get("/by-hour")
async def by_hour(
    request: Request,
    range: Optional[str] = Query("wtd"),
    start_date: Optional[date] = Query(None),
    end_date: Optional[date] = Query(None),
    direction: Optional[str] = Query(None),
    q: Optional[str] = Query(None, alias="q"),
    _user: dict = Depends(require_user),
):
    """Hour-of-day distribution (0-23) across the SELECTED window.

    Bruno's Qlik chart bucketed by Floor(start, 1/24) which collapsed to
    a single date — this version aggregates over the full window so it
    actually answers "what hours are busiest?"
    """
    pool = get_datalake_gold_pool(request)
    s, e = _common_window_params(range, start_date, end_date)
    d = _direction_filter(direction)

    params: list = []
    where = _scope_where(s, e, d, q, params)

    sql = f"""
    SELECT EXTRACT(HOUR FROM start)::int AS hour,
           COUNT(*)                       AS count
    FROM public.vonage_gld_by_user
    WHERE {where}
    GROUP BY 1
    ORDER BY 1
    """
    rows = await pool.fetch(sql, *params)

    # Pad missing hours with 0 so the chart shows a full 0-23 axis.
    by_hour = {r["hour"]: r["count"] for r in rows}
    out = [{"hour": h, "count": by_hour.get(h, 0)} for h in range_iter(24)]

    return {
        "success": True,
        "data": out,
        "meta": {"window": {"start": s.isoformat(), "end": e.isoformat()}},
    }


def range_iter(n: int):
    return list(range(n))


@router.get("/heatmap")
async def heatmap(
    request: Request,
    range: Optional[str] = Query("wtd"),
    start_date: Optional[date] = Query(None),
    end_date: Optional[date] = Query(None),
    direction: Optional[str] = Query(None),
    q: Optional[str] = Query(None, alias="q"),
    _user: dict = Depends(require_user),
):
    """Day-of-week × hour matrix.

    DOW: 0=Mon … 6=Sun (Postgres ISODOW - 1, kept in DB land).
    Hour: 0-23.
    Returns {data: [{dow, hour, count}], days: ['Mon',…,'Sun']}.
    """
    pool = get_datalake_gold_pool(request)
    s, e = _common_window_params(range, start_date, end_date)
    d = _direction_filter(direction)

    params: list = []
    where = _scope_where(s, e, d, q, params)

    sql = f"""
    SELECT
      (EXTRACT(ISODOW FROM start)::int - 1) AS dow,
      EXTRACT(HOUR FROM start)::int          AS hour,
      COUNT(*)                               AS count
    FROM public.vonage_gld_by_user
    WHERE {where}
    GROUP BY 1, 2
    ORDER BY 1, 2
    """
    rows = await pool.fetch(sql, *params)
    return {
        "success": True,
        "data": [
            {"dow": r["dow"], "hour": r["hour"], "count": r["count"]}
            for r in rows
        ],
        "meta": {
            "window": {"start": s.isoformat(), "end": e.isoformat()},
            "days": ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"],
        },
    }


@router.get("/top-users")
async def top_users(
    request: Request,
    range: Optional[str] = Query("wtd"),
    start_date: Optional[date] = Query(None),
    end_date: Optional[date] = Query(None),
    direction: Optional[str] = Query(None),
    q: Optional[str] = Query(None, alias="q"),
    limit: int = Query(20, ge=1, le=100),
    _user: dict = Depends(require_user),
):
    """Top users by call count and by talk-time (minutes).

    Returns two lists in one shape: data.by_count + data.by_talk_time.
    """
    pool = get_datalake_gold_pool(request)
    s, e = _common_window_params(range, start_date, end_date)
    d = _direction_filter(direction)

    params: list = []
    where = _scope_where(s, e, d, q, params)

    sql = f"""
    WITH agg AS (
      SELECT
        COALESCE(NULLIF(username, ''), '(unknown)') AS username,
        COUNT(*)                                    AS calls,
        SUM(EXTRACT(EPOCH FROM ("end" - start)) / 60.0)::float AS minutes
      FROM public.vonage_gld_by_user
      WHERE {where}
      GROUP BY 1
    )
    SELECT username, calls, minutes
    FROM agg
    """
    rows = await pool.fetch(sql, *params)
    rows_list = [
        {
            "username": r["username"],
            "calls":    r["calls"],
            "minutes":  r["minutes"] or 0.0,
        }
        for r in rows
    ]
    by_count = sorted(rows_list, key=lambda r: r["calls"], reverse=True)[:limit]
    by_time = sorted(rows_list, key=lambda r: r["minutes"], reverse=True)[:limit]

    return {
        "success": True,
        "data": {
            "by_count":     by_count,
            "by_talk_time": by_time,
        },
        "meta": {"window": {"start": s.isoformat(), "end": e.isoformat()}},
    }


@router.get("/detail")
async def detail(
    request: Request,
    range: Optional[str] = Query("wtd"),
    start_date: Optional[date] = Query(None),
    end_date: Optional[date] = Query(None),
    direction: Optional[str] = Query(None),
    q: Optional[str] = Query(None, alias="q"),
    page: int = Query(1, ge=1),
    limit: int = Query(200, ge=1, le=500),
    sort: str = Query(
        "start_desc",
        pattern="^(start_desc|start_asc|duration_desc|duration_asc|user_asc)$",
    ),
    _user: dict = Depends(require_user),
):
    """Paginated detail rows for the bottom table.

    Columns mirror Bruno's Qlik table verbatim plus username (useful for
    skimming / filtering): Type · Start · Identif · Call Details · End ·
    Call ID · Duration (Min) · username.
    """
    pool = get_datalake_gold_pool(request)
    s, e = _common_window_params(range, start_date, end_date)
    d = _direction_filter(direction)

    params: list = []
    where = _scope_where(s, e, d, q, params)

    order_sql = {
        "start_desc":    "start DESC",
        "start_asc":     "start ASC",
        "duration_desc": '("end" - start) DESC',
        "duration_asc":  '("end" - start) ASC',
        "user_asc":      "username ASC NULLS LAST, start DESC",
    }[sort]

    offset = (page - 1) * limit
    params.append(limit)
    params.append(offset)

    sql_rows = f"""
    SELECT
      call_id,
      call_direction        AS type,
      calling_party_identif AS identif,
      call_details,
      start,
      "end"                 AS end_ts,
      EXTRACT(EPOCH FROM ("end" - start)) / 60.0 AS duration_min,
      username
    FROM public.vonage_gld_by_user
    WHERE {where}
    ORDER BY {order_sql}
    LIMIT ${len(params) - 1} OFFSET ${len(params)}
    """

    sql_count = f"""
    SELECT COUNT(*) FROM public.vonage_gld_by_user WHERE {where}
    """

    # Two separate fetches; count uses params WITHOUT the trailing limit/offset.
    rows = await pool.fetch(sql_rows, *params)
    total = await pool.fetchval(sql_count, *params[:-2])

    out = [
        {
            "call_id":      r["call_id"],
            "type":         r["type"],
            "identif":      r["identif"],
            "call_details": r["call_details"],
            "start":        r["start"].isoformat() if r["start"] else None,
            "end":          r["end_ts"].isoformat() if r["end_ts"] else None,
            "duration_min": float(r["duration_min"]) if r["duration_min"] is not None else None,
            "username":     r["username"],
        }
        for r in rows
    ]

    return {
        "success": True,
        "data": out,
        "meta": {
            "window": {"start": s.isoformat(), "end": e.isoformat()},
            "total": int(total or 0),
            "page": page,
            "limit": limit,
        },
    }
