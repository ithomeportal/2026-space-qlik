"""Funnel Augie Activities — every picked-up load, and how many Augie tracked.

Requested by Bruno 2026-10-16 ("space Augie funnel report.pdf"): start from ALL
loads picked up in a window, show how many entered Augie tracking, how many of
those yielded information, and WHY the rest never reached Augie. A daily e-mail
with yesterday's close rides on the same endpoints (``augie_funnel_digest``).

Source: the Augie app's own tables in ``aivn_datalake_gold`` (read as
``spaceqlik_gold_ro``; SELECT verified 2026-10-17 with ``has_table_privilege``).

Population — ``app_augment_n8n_data_ra_rt``
-------------------------------------------
The n8n mirror of McLeod, one row per order × movement. It is NOT the set of
loads sent to Augie: 1,652 of 1,660 v4 orders (10/01–10/15) are in it, so it is
the company-wide load universe and the engine decides later what to send.
Pickup = ``original_origin_sched_early`` — the column the Augie dashboard's
"Pickup" filter reads (``queries.ts`` DATE_COLUMN), so "163 picked up on 10-16"
reconciles with the app. ⚠ The counted unit is a PICKUP = one order on one
pickup day: an order with legs on two days is two pickups (as in the app's
day lists), and a range is the sum of its days — the trend adds up to the KPI. Naive America/Chicago wall clock, so the
bound is a plain half-open ``>= lo AND < hi + 1 day`` with no AT TIME ZONE.
⚠ One order can carry several movements → once per pickup day; its attributes
(unit, team, customer, carrier, status) come from the latest movement (the
ETA-Late report's DISTINCT ON). ⚠ ``is_deleted`` rows are dropped.

🔴 "Augie tracking" = SENT to Augment, NOT "has an augie_status"
---------------------------------------------------------------
Bruno's mock shows 113 tracked of 163 (69%). 113 is the number of loads with a
non-null ``augie_status`` — but that column is the n8n mirror's McLeod-derived
status, and only **62** of those orders were ever accepted by Augment. A load is
tracked when it has an ``app_load_tracking`` row from a SEND (``automatic``,
``backfill``, ``manual``, ``pod-cron``): those rows are written only after a 2xx
from Augment, and "any tracking row" is the engine's own ``isAlreadyTrackToAugie``
test. 62 = the orders with a successful ``app_augment_requests`` send, exactly.
The 113 is still returned (``has_status``) so the page can reconcile with the
Augie dashboard — the gap between the two IS the leakage this report exists for.
Decided by the user 2026-10-17.

Info captured — the Augie Daily Activity e-mail's definition, per LOAD
----------------------------------------------------------------------
n8n's ``AUGIE - DAILY ACTIVITY REPORT`` counts ``calls_info_captured`` from three
webhook shapes (``sql/augie-activity-daily-etl.sql`` §A2, 2026-10-02):
``carrier-update`` with ``loadCarrierUpdate.source = 'PHONE'``,
``tracking-event`` with ``trackingEvent.eventSource = 'PHONE_EMAIL'``, and every
``stop-update``. A tracked load is "info captured" when ANY of those arrived for
it. One metric, one definition: the e-mail counts calls, this counts loads, but
both mean the same thing by "captured". ⚠ A PHONE ``comment`` is what Augment
posts when a call produced NO usable data, so it counts as "contacted" only.
On 10-16: 62 tracked → 53 contacted → 45 captured (73% of tracked).

Not in Augie — one reason per load, in priority order
-----------------------------------------------------
The mock lists "Not covered" and "Multistop". Measured on 10-16 those two are
37 of 101 untracked loads; the engine rejects for more reasons
(``SPEC-AUTOMATIC-TRACKING`` rules 10-12). Each untracked load gets the FIRST
matching reason, so the branch partitions the untracked set exactly:

  canceled       voided / canceled (``order_status='V'``, ``CANCELED``, flag)
  international  either end outside the US (rule 11) — NULL counts as non-US
  multistop      an extra stop at either end (rule 12, ``extra-stops.ts``) OR
                 more than one live movement on the order (rule 10)
  not_covered    no carrier/driver: ``augie_status`` NULL/blank or NOTCOVER
                 (``NOTCOVER`` is local-only — sending it is a 422)
  other          allow-list, blocking rules, kill switches, timing

Decided by the user 2026-10-17 ("all 5 real reasons").
"""

from __future__ import annotations

import logging
from datetime import date, timedelta
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request

from app.clock import cst_today
from app.routers.deps import get_datalake_gold_pool, require_report_access

logger = logging.getLogger(__name__)

router = APIRouter(tags=["augie-funnel"], prefix="/custom/augie-funnel")

REPORT_KEY = "augie-funnel"

LOADS = "public.app_augment_n8n_data_ra_rt"
TRACKING = "public.app_load_tracking"
WEBHOOKS = "public.app_augment_webhooks"

# First month the feed is populated (24 rows in Feb, 1,647 in March).
DATA_FLOOR = date(2026, 3, 1)
UPCOMING_DAYS = 14
MAX_SPAN_DAYS = 400
MAX_ROWS = 2000
# Overnight the feed still writes a few rows an hour (2-25/h, 2026-10-17), but
# a weekend night can be thinner — 6 h of silence is a stopped feed.
STALE_MINUTES = 360

# `app_load_tracking.change_source` values written by a SEND. `comment` and
# `webhook` rows are Augment talking back, which can only follow a send.
SEND_SOURCES = ("automatic", "backfill", "manual", "pod-cron")

REASONS = ("canceled", "international", "multistop", "not_covered", "other")
NODES = ("all", "tracked", "contacted", "captured", "tracked_no_info", "not_tracked") + REASONS
UNITS = ("CORP", "DFW")

RANGES = ("today", "last7", "last30", "last90", "upcoming", "custom")

# Sort tokens for /loads. Unknown token = 400, never a silent fallback.
_SORTS = {
    "pickup_desc": "pickup_at DESC NULLS LAST, order_id, pickup_day",
    "pickup_asc": "pickup_at ASC NULLS LAST, order_id, pickup_day",
    "order_asc": "order_id ASC",
    "customer_asc": "customer_name ASC NULLS LAST, order_id",
    "carrier_asc": "carrier_name ASC NULLS LAST, order_id",
    "team_asc": "unit ASC, team ASC, order_id",
    "stage_asc": "stage_rank ASC, order_id",
}

# The info-captured shapes — verbatim from the Augie Daily Activity ETL §A2.
_INFO_WEBHOOK = (
    "((w.webhook_type = 'carrier-update'"
    " AND w.payload -> 'loadCarrierUpdate' ->> 'source' = 'PHONE')"
    " OR (w.webhook_type = 'tracking-event'"
    " AND w.payload -> 'trackingEvent' ->> 'eventSource' = 'PHONE_EMAIL')"
    " OR w.webhook_type = 'stop-update')"
)
_CONTACT_WEBHOOK = (
    "((w.webhook_type = 'comment' AND w.payload ->> 'eventSource' = 'PHONE')"
    " OR w.webhook_type IN ('completed-call', 'call-recording'))"
)


# --------------------------------------------------------------------------
# filters
# --------------------------------------------------------------------------


def _parse_multi(raw: Optional[list[str]]) -> list[str]:
    """Flatten repeated query params. Never comma-splits: customer and carrier
    names contain commas, and splitting them returns zero rows with no error."""
    out: list[str] = []
    for item in raw or []:
        if item is None:
            continue
        v = item.strip()
        if v:
            out.append(v)
    return out


def _resolve_range(
    range_: Optional[str], start: Optional[date], end: Optional[date]
) -> tuple[date, date]:
    today = cst_today()
    if range_ == "custom" or (start and end):
        if not (start and end):
            raise HTTPException(400, "custom range needs start_date and end_date")
        lo, hi = (start, end) if start <= end else (end, start)
    elif range_ == "last7":
        lo, hi = today - timedelta(days=6), today
    elif range_ == "last30":
        lo, hi = today - timedelta(days=29), today
    elif range_ == "last90":
        lo, hi = today - timedelta(days=89), today
    elif range_ == "upcoming":
        lo, hi = today + timedelta(days=1), today + timedelta(days=UPCOMING_DAYS)
    elif range_ in (None, "today"):
        lo, hi = today, today
    else:
        raise HTTPException(400, f"unknown range {range_!r}")
    if hi < DATA_FLOOR:
        # Clamping lo up to the floor and hi up to lo would serve the floor
        # day's funnel under a February label — refuse instead.
        raise HTTPException(400, f"range ends before the data starts ({DATA_FLOOR})")
    lo = max(lo, DATA_FLOOR)
    if hi < lo:
        hi = lo
    if (hi - lo).days > MAX_SPAN_DAYS:
        lo = hi - timedelta(days=MAX_SPAN_DAYS)
    return lo, hi


def _common(
    range: Optional[str] = Query("today"),
    start_date: Optional[date] = Query(None),
    end_date: Optional[date] = Query(None),
    unit: Optional[list[str]] = Query(None),
    team: Optional[list[str]] = Query(None),
    customer: Optional[list[str]] = Query(None),
    carrier: Optional[list[str]] = Query(None),
    q: Optional[str] = Query(None, max_length=80),
) -> dict:
    s, e = _resolve_range(range, start_date, end_date)
    units = [u.upper() for u in _parse_multi(unit)]
    bad = [u for u in units if u not in UNITS]
    if bad:
        raise HTTPException(400, f"unknown unit {bad[0]!r}")
    return {
        "start": s,
        "end": e,
        "units": units,
        "teams": [t.upper() for t in _parse_multi(team)],
        "customers": _parse_multi(customer),
        "carriers": _parse_multi(carrier),
        "q": (q or "").strip(),
    }


def _like(term: str) -> str:
    escaped = term.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


def _load_filters(f: dict, params: list) -> str:
    """WHERE over the deduped `latest` rows. Appends to `params` in place —
    the caller owns the list and the placeholder numbering."""
    where = ["TRUE"]
    if f["units"]:
        params.append(f["units"])
        where.append(f"l.unit = ANY(${len(params)}::text[])")
    if f["teams"]:
        params.append(f["teams"])
        where.append(f"l.team = ANY(${len(params)}::text[])")
    if f["customers"]:
        params.append(f["customers"])
        where.append(f"l.customer_name = ANY(${len(params)}::text[])")
    if f["carriers"]:
        params.append(f["carriers"])
        where.append(f"l.carrier_name = ANY(${len(params)}::text[])")
    if f["q"]:
        params.append(_like(f["q"]))
        n = len(params)
        where.append(
            f"(l.order_id ILIKE ${n} OR l.customer_name ILIKE ${n}"
            f" OR l.carrier_name ILIKE ${n} OR l.team ILIKE ${n}"
            f" OR l.customer_id ILIKE ${n} OR l.carrier_id ILIKE ${n})"
        )
    return " AND ".join(where)


def _funnel_cte(f: dict) -> tuple[str, list]:
    """The ONE population every endpoint aggregates. Returns (WITH …, params).

    `classified` carries one row per order with tracked / contacted / captured
    flags and, when not tracked, exactly one `reason` — so every count on the
    page is a slice of the same set and the branches add up by construction.
    """
    params: list[Any] = [f["start"], f["end"] + timedelta(days=1)]
    load_where = _load_filters(f, params)
    sends = ", ".join(f"'{s}'" for s in SEND_SOURCES)
    sql = f"""
        WITH pickups AS (
            -- The unit is a PICKUP: one row per order per pickup day. Each day
            -- then equals the Augie dashboard's "Pickup = that day" list (an
            -- order counts on every day it has a live movement picking up), and
            -- a range is the SUM of its days, so the trend adds up to the KPI.
            -- 21 of 164 orders on 10-16 had an earlier leg: an order-level
            -- "first pickup" would have printed 143 against the app's 163.
            SELECT BTRIM(a.id::text)                     AS order_id,
                   a.original_origin_sched_early::date    AS pickup_day,
                   min(a.original_origin_sched_early)     AS pickup_at
              FROM {LOADS} a
             WHERE NOT COALESCE(a.is_deleted, false)
               AND a.original_origin_sched_early >= $1
               AND a.original_origin_sched_early <  $2
             GROUP BY 1, 2
        ),
        mv AS (
            SELECT BTRIM(a.id::text)            AS order_id,
                   count(DISTINCT a.movement_id) AS movements
              FROM {LOADS} a
             WHERE NOT COALESCE(a.is_deleted, false)
               AND BTRIM(a.id::text) IN (SELECT order_id FROM pickups)
             GROUP BY 1
        ),
        latest AS (
            SELECT DISTINCT ON (BTRIM(a.id::text))
                   BTRIM(a.id::text)                          AS order_id,
                   COALESCE(BTRIM(a.business_unit::text), '') AS unit,
                   COALESCE(BTRIM(a.team_id::text), '')       AS team,
                   BTRIM(a.customer_id::text)                 AS customer_id,
                   BTRIM(a.customer_name)                     AS customer_name,
                   BTRIM(a.override_payee_id::text)           AS carrier_id,
                   BTRIM(a.carrier_name)                      AS carrier_name,
                   BTRIM(a.augie_status::text)                AS augie_status,
                   BTRIM(a.order_status::text)                AS order_status,
                   a.is_load_canceled,
                   BTRIM(a.origin_country::text)              AS origin_country,
                   BTRIM(a.destination_country::text)         AS destination_country,
                   COALESCE(a.extra_stops_at_pickup, 0)::int   AS extra_pu,
                   COALESCE(a.extra_stops_at_delivery, 0)::int AS extra_del,
                   BTRIM(a.origin_city_name)                  AS origin_city,
                   BTRIM(a.origin_state::text)                AS origin_state,
                   BTRIM(a.dest_city_name)                    AS dest_city,
                   BTRIM(a.dest_state::text)                  AS dest_state
              FROM {LOADS} a
             WHERE NOT COALESCE(a.is_deleted, false)
               AND BTRIM(a.id::text) IN (SELECT order_id FROM pickups)
             ORDER BY BTRIM(a.id::text), a.updated_dt DESC NULLS LAST,
                      a.movement_id DESC
        ),
        loads AS MATERIALIZED (
            SELECT l.*, p.pickup_day, p.pickup_at, mv.movements
              FROM pickups p
              JOIN latest l ON l.order_id = p.order_id
              JOIN mv       ON mv.order_id = p.order_id
             WHERE {load_where}
        ),
        sent AS (
            SELECT DISTINCT t.order_id
              FROM {TRACKING} t
             WHERE t.order_id IN (SELECT order_id FROM loads)
               AND t.change_source IN ({sends})
        ),
        talk AS (
            SELECT w.load_number AS order_id,
                   bool_or({_INFO_WEBHOOK})    AS info,
                   bool_or({_CONTACT_WEBHOOK}) AS contact
              FROM {WEBHOOKS} w
             WHERE w.load_number IN (SELECT order_id FROM loads)
             GROUP BY 1
        ),
        classified AS (
            SELECT l.*,
                   (s.order_id IS NOT NULL)                         AS tracked,
                   (s.order_id IS NOT NULL
                    AND (COALESCE(k.info, false)
                         OR COALESCE(k.contact, false)))            AS contacted,
                   (s.order_id IS NOT NULL AND COALESCE(k.info, false)) AS captured,
                   (COALESCE(l.augie_status, '') <> '')             AS has_status,
                   CASE
                     WHEN s.order_id IS NOT NULL THEN NULL
                     WHEN l.order_status = 'V' OR l.augie_status = 'CANCELED'
                          OR COALESCE(l.is_load_canceled, false)   THEN 'canceled'
                     WHEN COALESCE(l.origin_country, '') <> 'US'
                          OR COALESCE(l.destination_country, '') <> 'US'
                                                                    THEN 'international'
                     WHEN l.extra_pu > 0 OR l.extra_del > 0
                          OR l.movements > 1                        THEN 'multistop'
                     WHEN COALESCE(l.augie_status, '') IN ('', 'NOTCOVER')
                                                                    THEN 'not_covered'
                     ELSE 'other'
                   END                                              AS reason
              FROM loads l
              LEFT JOIN sent s     ON s.order_id = l.order_id
              LEFT JOIN talk k     ON k.order_id = l.order_id
        )
    """
    return sql, params


_COUNTS_SQL = """
           count(*)                                               AS pickups,
           count(*) FILTER (WHERE tracked)                        AS tracked,
           count(*) FILTER (WHERE contacted)                      AS contacted,
           count(*) FILTER (WHERE captured)                       AS captured,
           count(*) FILTER (WHERE has_status)                     AS has_status,
           count(*) FILTER (WHERE reason = 'canceled')            AS canceled,
           count(*) FILTER (WHERE reason = 'international')       AS international,
           count(*) FILTER (WHERE reason = 'multistop')           AS multistop,
           count(*) FILTER (WHERE reason = 'not_covered')         AS not_covered,
           count(*) FILTER (WHERE reason = 'other')               AS other
"""

_COUNT_KEYS = (
    "pickups", "tracked", "contacted", "captured", "has_status", *REASONS,
)


def _rate(num: Optional[float], den: Optional[float]) -> Optional[float]:
    """Percent 0-100, None on an empty denominator (never a fake 0%)."""
    if not den or den <= 0:
        return None
    return round(100.0 * float(num or 0) / float(den), 1)


def funnel_payload(row: Any) -> dict:
    """Counts + the rates the page and the e-mail print. Pure, unit-tested.

    ⚠ Two denominators, on purpose: tracked / not-tracked / reasons are shares
    of PICKUPS; contacted and captured are shares of TRACKED (the mock's "84%
    out of 113 from augie tracking").
    """
    c = {k: int((row[k] if row is not None else 0) or 0) for k in _COUNT_KEYS}
    not_tracked = c["pickups"] - c["tracked"]
    return {
        **c,
        "not_tracked": not_tracked,
        "tracked_pct": _rate(c["tracked"], c["pickups"]),
        "not_tracked_pct": _rate(not_tracked, c["pickups"]),
        "contacted_pct": _rate(c["contacted"], c["tracked"]),
        "captured_pct": _rate(c["captured"], c["tracked"]),
        "has_status_pct": _rate(c["has_status"], c["pickups"]),
        "reason_pct": {r: _rate(c[r], c["pickups"]) for r in REASONS},
    }


# --------------------------------------------------------------------------
# endpoints
# --------------------------------------------------------------------------


@router.get("/filters")
async def filters(
    request: Request,
    _user: dict = Depends(require_report_access(REPORT_KEY)),
):
    """Team, customer and carrier lists from the last 120 days of the feed —
    from the data, never a constant (TEAM5 / TM5 carry ~2 orders each)."""
    lo = cst_today() - timedelta(days=120)
    pool = get_datalake_gold_pool(request)
    async with pool.acquire() as conn:
        teams = await conn.fetch(
            f"""
            SELECT BTRIM(business_unit::text) AS unit, BTRIM(team_id::text) AS team,
                   count(*) AS n
              FROM {LOADS}
             WHERE original_origin_sched_early >= $1
               AND COALESCE(BTRIM(team_id::text), '') <> ''
               AND BTRIM(business_unit::text) = ANY($2::text[])
             GROUP BY 1, 2
             ORDER BY 1, 2
            """,
            lo,
            list(UNITS),
        )
        customers = await conn.fetch(
            f"""
            SELECT BTRIM(customer_name) AS v, count(*) AS n
              FROM {LOADS}
             WHERE original_origin_sched_early >= $1
               AND COALESCE(BTRIM(customer_name), '') <> ''
             GROUP BY 1 ORDER BY 2 DESC, 1
            """,
            lo,
        )
        carriers = await conn.fetch(
            f"""
            SELECT BTRIM(carrier_name) AS v, count(*) AS n
              FROM {LOADS}
             WHERE original_origin_sched_early >= $1
               AND COALESCE(BTRIM(carrier_name), '') <> ''
             GROUP BY 1 ORDER BY 2 DESC, 1
            """,
            lo,
        )
    return {
        "success": True,
        "data": {
            "units": list(UNITS),
            "teams": [{"unit": r["unit"], "team": r["team"]} for r in teams],
            "customers": [r["v"] for r in customers],
            "carriers": [r["v"] for r in carriers],
            "reasons": list(REASONS),
            "data_floor": DATA_FLOOR.isoformat(),
        },
    }


@router.get("/summary")
async def summary(
    request: Request,
    f: dict = Depends(_common),
    _user: dict = Depends(require_report_access(REPORT_KEY)),
):
    """The funnel: pickups → tracked → contacted → captured, plus the reasons."""
    cte, params = _funnel_cte(f)
    pool = get_datalake_gold_pool(request)
    async with pool.acquire() as conn:
        row = await conn.fetchrow(cte + f"SELECT {_COUNTS_SQL} FROM classified", *params)
    data = funnel_payload(row)
    data["start_date"] = f["start"].isoformat()
    data["end_date"] = f["end"].isoformat()
    return {"success": True, "data": data}


@router.get("/trend")
async def trend(
    request: Request,
    grain: str = Query("day", pattern="^(day|week)$"),
    f: dict = Depends(_common),
    _user: dict = Depends(require_report_access(REPORT_KEY)),
):
    """The funnel per pickup day (or ISO week, Monday start). Dense: a day with
    no pickups is a zero row, never a gap the chart draws a line across."""
    cte, params = _funnel_cte(f)
    bucket = "date_trunc('week', pickup_day)::date" if grain == "week" else "pickup_day"
    pool = get_datalake_gold_pool(request)
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            cte
            + f"SELECT {bucket} AS bucket, {_COUNTS_SQL} FROM classified GROUP BY 1 ORDER BY 1",
            *params,
        )
    by_bucket = {r["bucket"]: r for r in rows}
    out = []
    step = 7 if grain == "week" else 1
    cur = f["start"] - timedelta(days=f["start"].weekday()) if grain == "week" else f["start"]
    while cur <= f["end"]:
        out.append({"bucket": cur.isoformat(), **funnel_payload(by_bucket.get(cur))})
        cur += timedelta(days=step)
    return {"success": True, "data": out, "meta": {"grain": grain}}


@router.get("/by-team")
async def by_team(
    request: Request,
    f: dict = Depends(_common),
    _user: dict = Depends(require_report_access(REPORT_KEY)),
):
    """The funnel per unit × team, ordered by pickups. Server-side aggregate
    over the whole filtered universe — never a client reduce of a page."""
    cte, params = _funnel_cte(f)
    pool = get_datalake_gold_pool(request)
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            cte
            + f"""
            SELECT unit, team, {_COUNTS_SQL}
              FROM classified
             GROUP BY 1, 2
             ORDER BY count(*) DESC, 1, 2
            """,
            *params,
        )
    out = [
        {"unit": r["unit"] or None, "team": r["team"] or None, **funnel_payload(r)}
        for r in rows
    ]
    return {"success": True, "data": out}


def _node_where(node: str) -> str:
    if node == "all":
        return "TRUE"
    if node == "tracked":
        return "tracked"
    if node == "contacted":
        return "contacted"
    if node == "captured":
        return "captured"
    if node == "tracked_no_info":
        return "tracked AND NOT captured"
    if node == "not_tracked":
        return "NOT tracked"
    if node in REASONS:
        return f"reason = '{node}'"
    raise HTTPException(400, f"unknown node {node!r}")


@router.get("/loads")
async def loads(
    request: Request,
    node: str = Query("all"),
    sort: str = Query("pickup_desc"),
    f: dict = Depends(_common),
    _user: dict = Depends(require_report_access(REPORT_KEY)),
):
    """Load-level detail behind a funnel box. Capped at MAX_ROWS; `meta.total`
    is the full count so the page can say it is showing a slice."""
    if sort not in _SORTS:
        raise HTTPException(400, f"unknown sort {sort!r}")
    node_where = _node_where(node)
    cte, params = _funnel_cte(f)
    pool = get_datalake_gold_pool(request)
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            cte
            + f"""
            , picked AS (
                SELECT c.*,
                       CASE WHEN captured THEN 1 WHEN contacted THEN 2
                            WHEN tracked THEN 3 ELSE 4 END AS stage_rank,
                       count(*) OVER () AS total
                  FROM classified c
                 WHERE {node_where}
            )
            SELECT order_id, unit, team, customer_name, carrier_name, augie_status,
                   order_status, pickup_day, pickup_at, origin_city, origin_state, dest_city,
                   dest_state, tracked, contacted, captured, reason, total
              FROM picked
             ORDER BY {_SORTS[sort]}
             LIMIT {MAX_ROWS}
            """,
            *params,
        )
    total = int(rows[0]["total"]) if rows else 0
    out = [
        {
            "order_id": r["order_id"],
            "unit": r["unit"] or None,
            "team": r["team"] or None,
            "customer": r["customer_name"],
            "carrier": r["carrier_name"],
            "augie_status": r["augie_status"] or None,
            "order_status": r["order_status"],
            "pickup_day": r["pickup_day"].isoformat(),
            "pickup_at": r["pickup_at"].isoformat() if r["pickup_at"] else None,
            "origin": ", ".join(x for x in (r["origin_city"], r["origin_state"]) if x),
            "destination": ", ".join(x for x in (r["dest_city"], r["dest_state"]) if x),
            "tracked": bool(r["tracked"]),
            "contacted": bool(r["contacted"]),
            "captured": bool(r["captured"]),
            "reason": r["reason"],
        }
        for r in rows
    ]
    return {
        "success": True,
        "data": out,
        "meta": {"total": total, "truncated": total > len(out), "node": node},
    }


@router.get("/freshness")
async def freshness(
    request: Request,
    _user: dict = Depends(require_report_access(REPORT_KEY)),
):
    """"Data as of": the load feed (naive CST ``updated_dt``) and Augment's
    callbacks (``received_at`` timestamptz). Either can stop on its own.

    The load feed writes around the clock (n8n's McLeod poll), thinly at night,
    so STALE_MINUTES of silence is a stopped feed, not a quiet evening.
    """
    out: dict[str, Any] = {
        "loads_updated": None,
        "loads_stale_minutes": None,
        "webhooks_received": None,
        "webhooks_stale_minutes": None,
        "is_stale": False,
    }
    try:
        pool = get_datalake_gold_pool(request)
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                f"""
                SELECT (SELECT max(updated_dt) FROM {LOADS}) AS loads_ts,
                       (SELECT max(received_at) FROM {WEBHOOKS}) AS wh_ts,
                       now() AT TIME ZONE 'America/Chicago' AS now_cst,
                       now() AS now_tz
                """
            )
        if row and row["loads_ts"]:
            out["loads_updated"] = row["loads_ts"].isoformat()
            out["loads_stale_minutes"] = round(
                (row["now_cst"] - row["loads_ts"]).total_seconds() / 60, 1
            )
        if row and row["wh_ts"]:
            out["webhooks_received"] = row["wh_ts"].isoformat()
            out["webhooks_stale_minutes"] = round(
                (row["now_tz"] - row["wh_ts"]).total_seconds() / 60, 1
            )
        mins = out["loads_stale_minutes"]
        out["is_stale"] = mins is None or mins > STALE_MINUTES
    except Exception as e:  # a dead feed must not 500 the page
        logger.warning("Augie funnel freshness failed: %s", e)
        out["is_stale"] = True
    return {"success": True, "data": out}

