"""Code-made report: Customer Lifespan (#69, request 2026-10-29; deck 2026-11-03).

Every customer since 2016: first and last load, lifespan, status, reactivations,
cohorts by first year, survival, and the monthly new / lost / reactivated flow.
Reads ``customer_lifespan_orders`` (analytics_hub) — the workbook's history to
2026-08-31 plus the nightly v4 sync (``services/customer_lifespan_store``).
Definitions: ``services/customer_lifespan_core`` + ``_trends`` + ``_scope`` +
``_board``. Spec: docs/SPEC-CUSTOMER-LIFESPAN.md.

The division is a PATH SEGMENT (``/{all|corp|dfw}/…``) so it can never default
(§100). Safe to be client-chosen here: every TagRole granted this report may
read both divisions, and ``require_report_access`` runs before it is honoured.
Date, teams and customer are query params on EVERY section (``Filters``).
"""
from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass
from datetime import date
from enum import Enum

from fastapi import APIRouter, Depends, HTTPException, Query, Request

from app.routers.deps import get_pool, require_report_access
from app.services.customer_lifespan_board import RECENT_SQL, board, merge_recent, tile_counts
from app.services.customer_lifespan_core import (
    CUSTOMER_MONTHS_RANGE_SQL,
    CUSTOMER_MONTHS_SQL,
    DEFAULT_WINDOW,
    WINDOWS,
    Customer,
    customer_detail,
    customer_row,
    merge_rows,
    summary,
)
from app.services.customer_lifespan_scope import (
    ALL_START,
    OWNERS_EVER_OK_SQL,
    OWNERS_SQL,
    TEAMS_SQL,
    Assignments,
    Period,
    filter_rows,
    resolve_period,
    scope_customers,
    shift_year,
    team_chips,
)
from app.services.customer_lifespan_store import CUTOVER, EXCEL_LAST_SHIP, TAIL_START
from app.services.customer_lifespan_trends import GRAINS, cohorts, flow_members, lifespan, trend

logger = logging.getLogger(__name__)

REPORT_KEY = "customer-lifespan"
CACHE_TTL_SECONDS = 300.0
MAX_CACHED_RANGES = 32
ASSIGNMENTS_KEY = "assignments"

router = APIRouter(tags=[REPORT_KEY], prefix=f"/custom/{REPORT_KEY}")


class Division(str, Enum):
    all = "all"
    corp = "corp"
    dfw = "dfw"


@dataclass(frozen=True)
class Filters:
    """The filter bar. ``teams`` None = every team; ``("",)`` = every chip off = nobody."""

    range_key: str = "last_365"
    start: date | None = None
    end: date | None = None
    teams: tuple[str, ...] | None = None
    customer: str | None = None


def filters_dep(
    range_key: str = Query("last_365", alias="range", description="last_365, mtd, last_month, ytd, custom, all"),
    start: date | None = Query(None, description="custom range start"),
    end: date | None = Query(None, description="custom range end"),
    teams: list[str] | None = Query(None, description="team chips, repeated; absent = every team"),
    customer: str | None = Query(None, description="McLeod customer ID"),
) -> Filters:
    return Filters(range_key, start, end, tuple(teams) if teams is not None else None, customer)


@dataclass(frozen=True)
class Scoped:
    customers: list[Customer]
    period: Period
    data_as_of: date
    assignments: Assignments
    total: int


SOURCES_SQL = """
SELECT source, COUNT(*)::int AS orders, MIN(ship_date) AS first_ship,
       MAX(ship_date) AS last_ship, MAX(loaded_at) AS loaded_at,
       COUNT(*) FILTER (WHERE voided_in_datalake)::int AS voided
  FROM customer_lifespan_orders
 GROUP BY source
"""
LAST_SYNC_SQL = """
SELECT status, started_at, finished_at, v4_rows, stored_v4_rows, gap_fills,
       v4_last_write, reconciliation::text AS reconciliation, error
  FROM customer_lifespan_sync_log
 ORDER BY started_at DESC LIMIT 1
"""
LAST_OK_SQL = """
SELECT finished_at, reconciliation::text AS reconciliation
  FROM customer_lifespan_sync_log
 WHERE status = 'ok' ORDER BY finished_at DESC LIMIT 1
"""
REFRESH_STATUS_SQL = """
SELECT kind,
       MAX(finished_at) FILTER (WHERE status = 'ok') AS last_ok_at,
       (ARRAY_AGG(status ORDER BY started_at DESC))[1] AS last_status
  FROM customer_lifespan_refresh_log
 GROUP BY kind
"""

_cache: dict = {}
_lock = asyncio.Lock()


def invalidate_cache() -> None:
    """Called after a sync so the next page view reads the new rows."""
    _cache.clear()


async def _rows(request: Request) -> tuple[list, date]:
    """Every customer × month × division row, cached ``CACHE_TTL_SECONDS``.

    The as-of date is the latest ship date in the table — NOT today: if the
    sync stops, statuses must freeze with the data instead of every customer
    sliding to "lost" (datalake-table-health).
    """
    pool = get_pool(request)
    async with _lock:
        hit = _cache.get("rows")
        if hit and time.monotonic() - hit[0] < CACHE_TTL_SECONDS:
            rows, as_of = hit[1], hit[2]
        else:
            rows = [dict(r) for r in await pool.fetch(CUSTOMER_MONTHS_SQL)]
            as_of = max((r["last_ship"] for r in rows), default=None)
            _cache["rows"] = (time.monotonic(), rows, as_of)
    if as_of is None:
        raise HTTPException(503, "Customer Lifespan has no data loaded yet")
    return rows, as_of


async def _between(request: Request, start: date, end: date) -> list:
    """The month rows of one date range, cached like ``_rows`` and bounded: custom dates churn."""
    key = ("range", start, end)
    async with _lock:
        hit = _cache.get(key)
        if hit and time.monotonic() - hit[0] < CACHE_TTL_SECONDS:
            return hit[1]
        rows = [dict(r) for r in await get_pool(request).fetch(CUSTOMER_MONTHS_RANGE_SQL, start, end)]
        ranges = [k for k in _cache if isinstance(k, tuple)]
        if len(ranges) >= MAX_CACHED_RANGES:
            for k in ranges:
                del _cache[k]
        _cache[key] = (time.monotonic(), rows, None)
        return rows


async def _assignments(request: Request) -> Assignments:
    """Teams + Pipedrive owners. Fails SOFT: without them the report still answers,
    and an owner map that was never filled is unknown, not "nobody assigned"."""
    hit = _cache.get(ASSIGNMENTS_KEY)
    if hit and time.monotonic() - hit[0] < CACHE_TTL_SECONDS:
        return hit[1]
    pool = get_pool(request)
    try:
        teams = {r["customer_id"]: r["team_id"] for r in await pool.fetch(TEAMS_SQL)}
        rows = await pool.fetch(OWNERS_SQL)
        ever_ok = bool(rows) or bool(await pool.fetchval(OWNERS_EVER_OK_SQL))
        owners = {r["customer_code"]: r["owner_name"] for r in rows} if ever_ok else None
    except Exception as e:  # noqa: BLE001 — logged; the report answers without owners
        logger.error("customer lifespan assignments unavailable: %s", type(e).__name__)
        return Assignments({}, None)
    result = Assignments(teams, owners)
    _cache[ASSIGNMENTS_KEY] = (time.monotonic(), result, None)
    return result


def _window(window: int) -> int:
    if window not in WINDOWS:
        raise HTTPException(422, f"window must be one of {list(WINDOWS)}")
    return window


async def _customers_in(request: Request, period: Period, division: Division, window: int,
                        f: Filters, a: Assignments, all_rows: list, data_as_of: date) -> list[Customer]:
    history = all_rows if period.end >= data_as_of else await _between(request, ALL_START, period.end)
    first = min(r["first_ship"] for r in all_rows)
    inside = history if period.start <= first else await _between(request, period.start, period.end)
    return scope_customers(
        merge_rows(filter_rows(history, a, f.teams, f.customer), division.value),
        merge_rows(filter_rows(inside, a, f.teams, f.customer), division.value),
        period.end, window,
    )


async def _scoped(request: Request, division: Division, window: int, f: Filters) -> Scoped:
    _window(window)
    all_rows, data_as_of = await _rows(request)
    try:
        period = resolve_period(f.range_key, f.start, f.end, data_as_of)
    except ValueError as e:
        raise HTTPException(422, str(e)) from None
    a = await _assignments(request)
    customers = await _customers_in(request, period, division, window, f, a, all_rows, data_as_of)
    total = len({m.customer_id for m in merge_rows(filter_rows(all_rows, a, f.teams, f.customer), division.value)})
    return Scoped(customers, period, data_as_of, a, total)


def _envelope(data, division: Division, window: int, s: Scoped, **meta) -> dict:
    return {"success": True, "data": data,
            "meta": {"division": division.value, "window_days": window,
                     "as_of": s.period.end.isoformat(), "data_as_of": s.data_as_of.isoformat(),
                     "range": s.period.key, "range_label": s.period.label,
                     "start": s.period.start.isoformat(), "end": s.period.end.isoformat(), **meta}}


def _public_sync(row) -> dict | None:
    """The last run for every viewer — the raw exception stays in the log table
    (it can name tables, roles and columns; review 2026-10-29)."""
    if row is None:
        return None
    out = {k: row[k] for k in ("status", "started_at", "finished_at", "v4_rows", "gap_fills", "v4_last_write")}
    err = row["error"] or ""
    out["error"] = (None if not err else "the datalake stopped updating" if "stale" in err
                    else "the datalake returned too few orders" if "shrink" in err
                    else "sync error — details in the server log")
    return out


_WINDOW_Q = Query(DEFAULT_WINDOW, description="Silence window in days (60, 90 or 180)")


@router.get("/freshness")
async def freshness(request: Request, _user: dict = Depends(require_report_access(REPORT_KEY))):
    """Where the data comes from, how fresh it is, and the Excel-vs-datalake check."""
    pool = get_pool(request)
    sources = [dict(r) for r in await pool.fetch(SOURCES_SQL)]
    last = await pool.fetchrow(LAST_SYNC_SQL)
    ok = await pool.fetchrow(LAST_OK_SQL)
    refresh = {r["kind"]: {"last_ok_at": r["last_ok_at"], "last_status": r["last_status"]}
               for r in await pool.fetch(REFRESH_STATUS_SQL)}
    return {"success": True, "data": {
        "sources": sources,
        "excel_last_ship": EXCEL_LAST_SHIP.isoformat(),
        "cutover": CUTOVER.isoformat(),
        "reconciliation_window_start": TAIL_START.isoformat(),
        "last_sync": _public_sync(last),
        "last_ok_sync_at": ok["finished_at"] if ok else None,
        "reconciliation": ok["reconciliation"] if ok else None,
        "teams_refresh": refresh.get("teams"),
        "owners_refresh": refresh.get("owners"),
    }}


_FILTERS = Depends(filters_dep)
_ACCESS = Depends(require_report_access(REPORT_KEY))


@router.get("/{division}/filters")
async def filters_view(request: Request, division: Division, _user: dict = _ACCESS):
    """The team chips and customers of a division, for the filter bar. Not narrowed by dates."""
    rows, _as_of = await _rows(request)
    a = await _assignments(request)
    months = merge_rows(rows, division.value)
    names: dict[str, tuple[date, str]] = {}
    for m in months:
        if m.customer_id not in names or m.last_ship > names[m.customer_id][0]:
            names[m.customer_id] = (m.last_ship, m.name)
    return {"success": True, "data": {
        "teams": team_chips(rows, division.value, a),
        "customers": sorted(({"customer_id": k, "name": v[1]} for k, v in names.items()),
                            key=lambda c: c["name"]),
    }}


@router.get("/{division}/summary")
async def summary_view(request: Request, division: Division, window: int = _WINDOW_Q,
                       f: Filters = _FILTERS, _user: dict = _ACCESS):
    """KPIs: customers in the base, at risk, lost, new, reactivated, lifespans, concentration."""
    s = await _scoped(request, division, window, f)
    return _envelope(summary(s.customers, s.period.end, window, s.period.start, s.total), division, window, s)


@router.get("/{division}/board")
async def board_view(request: Request, division: Division, window: int = _WINDOW_Q,
                     f: Filters = _FILTERS, _user: dict = _ACCESS):
    """The Summary tab: five tiles against the same period last year, and the tables behind them."""
    s = await _scoped(request, division, window, f)
    prior_period = shift_year(s.period)
    prior = None
    if prior_period is not None:
        all_rows, _as_of = await _rows(request)
        before = await _customers_in(request, prior_period, division, window, f, s.assignments,
                                     all_rows, s.data_as_of)
        prior = tile_counts(before, prior_period.end, window, prior_period.start)
    recent = await get_pool(request).fetch(RECENT_SQL, s.period.end)
    data = board(s.customers, prior, merge_recent(recent, division.value), s.period.end, window,
                 s.period.start, s.assignments)
    return _envelope(data, division, window, s)


@router.get("/{division}/trend")
async def trend_view(request: Request, division: Division, window: int = _WINDOW_Q,
                     grain: str = Query("month", description="month, quarter or year"),
                     f: Filters = _FILTERS, _user: dict = _ACCESS):
    """Active / new / lost / reactivated customers, base, revenue and margin per period."""
    if grain not in GRAINS:
        raise HTTPException(422, f"grain must be one of {list(GRAINS)}")
    s = await _scoped(request, division, window, f)
    return _envelope(trend(s.customers, s.period.end, window, grain, s.period.start),
                     division, window, s, grain=grain)


@router.get("/{division}/flow-customers")
async def flow_customers_view(request: Request, division: Division, window: int = _WINDOW_Q,
                              grain: str = Query("month", description="month, quarter or year"),
                              period: str = Query(..., max_length=16, description="a period label from /trend"),
                              f: Filters = _FILTERS, _user: dict = _ACCESS):
    """Who is behind one period's bars: new, came back and lost, one row per event."""
    if grain not in GRAINS:
        raise HTTPException(422, f"grain must be one of {list(GRAINS)}")
    s = await _scoped(request, division, window, f)
    members = flow_members(s.customers, window, grain, period, s.period.start)
    data = {k: [{**e, **s.assignments.of(e["customer_id"], e["status"])} for e in rows]
            for k, rows in members.items()}
    return _envelope(data, division, window, s, grain=grain, period=period)


@router.get("/{division}/cohorts")
async def cohorts_view(request: Request, division: Division, window: int = _WINDOW_Q,
                       f: Filters = _FILTERS, _user: dict = _ACCESS):
    """One row per first-load year: new, still in base, lost, lifespans, retention by year."""
    s = await _scoped(request, division, window, f)
    return _envelope(cohorts(s.customers, s.period.end, s.period.start), division, window, s)


@router.get("/{division}/lifespan")
async def lifespan_view(request: Request, division: Division, window: int = _WINDOW_Q,
                        f: Filters = _FILTERS, _user: dict = _ACCESS):
    """Lifespan distribution by status and the Kaplan–Meier survival curve."""
    s = await _scoped(request, division, window, f)
    return _envelope(lifespan(s.customers, s.period.end), division, window, s)


@router.get("/{division}/customers")
async def customers_view(request: Request, division: Division, window: int = _WINDOW_Q,
                         f: Filters = _FILTERS, _user: dict = _ACCESS):
    """Every customer with a load in the range (filtered and sorted further in the browser)."""
    s = await _scoped(request, division, window, f)
    rows = sorted((customer_row(c, s.period.end, s.assignments.of(c.customer_id, c.status))
                   for c in s.customers), key=lambda r: -r["revenue"])
    return _envelope(rows, division, window, s, total=len(rows))


@router.get("/{division}/customers/{customer_id}")
async def customer_view(request: Request, division: Division, customer_id: str,
                        window: int = _WINDOW_Q, f: Filters = _FILTERS, _user: dict = _ACCESS):
    """One customer's monthly loads, revenue, margin and margin % in the range."""
    s = await _scoped(request, division, window, f)
    match = next((c for c in s.customers if c.customer_id == customer_id), None)
    if match is None:
        raise HTTPException(404, f"customer {customer_id} has no loads in {division.value} in {s.period.label}")
    return _envelope(customer_detail(match, s.period.end, s.assignments.of(match.customer_id, match.status)),
                     division, window, s)
