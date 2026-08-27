"""EDI Load Tenders — the 204 tender stream and what we did with it.

Source: ``aivn_datalake_gold.mcleod_gld_edi_load_tender``, delivered by Omar
Orozco 2026-08-26 and re-ingested every ~10 minutes. It is the first table in
this portal that can see a tender we **never turned into an order** — such a
shipment has no row in ``budget_report_v4`` at all, so every existing report is
structurally blind to it.

It also closes the cancellation blind spot. ``OPEN_STATUSES = ("D","P")`` is
redefined in five separate modules here and quietly drops voided orders, so
until now only HD Spot surfaced a cancellation at all.

Grain: ``id`` is the row, ``shipment_id`` is the BUSINESS grain
--------------------------------------------------------------
``id`` is unique (65,751 / 65,751 on 2026-08-26). ``shipment_id`` is **not** —
37,188 distinct shipments carry those 65,751 rows, because one shipment
accumulates an ORIGINAL, then any number of CHANGEs, then a CANCEL. The worst
observed shipment carries 80 tenders.

⚠ Every headline number is therefore counted at SHIPMENT grain. Counting rows
inflates "tenders we accepted" by ~77% and double-counts every customer that
amends a lot. The raw row count is still reported, separately and labelled
"Tender messages", because the messages themselves are the EDI traffic volume.

⚠ `order_id` is EMPTY STRING, never NULL
----------------------------------------
17,823 rows carry ``order_id = ''``; **zero** carry NULL. The natural
``order_id IS NULL`` test returns 0 and the whole "never created" KPI silently
reads zero. Always test ``order_id <> ''``.

⚠ `order_id` is 7 chars, `budget_report_v4.id` is 8 — the join needs rpad()
---------------------------------------------------------------------------
Omar's note says ``order_id`` matches the identifiers we already use with
budget_report. It does, but not literally: ``order_id`` is uniformly 7
characters (``'0343903'``) while ``v4.id`` is uniformly 8, right-padded
(``'0343903 '``). A plain ``br4.id = t.order_id`` matched **0 of 47,928** rows
— silently, as a LEFT JOIN yielding all-NULL enrichment.

``rpad(t.order_id, 8)`` matches **47,928 / 47,928 = 100%**. It is applied to
the TENDER side on purpose: that leaves ``br4.id`` bare, so the join still
plans as an Index Only Scan on ``mcleod_gld_budget_report_v4_pkey``. Wrapping
the v4 side in ``TRIM()`` would match just as well and cost a full scan — the
sargability rule in ``app.datalake``.

⚠ `company_id` is declared varchar(32) but STORES the varchar(4) value
---------------------------------------------------------------------
Every row holds ``'TMS '`` — 4 characters, right-padded to v4's width, not to
its own declared 32. ``pad_variants(("TMS",), width=32)`` produces ``'TMS'``
and ``'TMS' + 29 spaces`` and matches **neither**. Pad to the width the value
is actually stored at, not the width the column declares. The join below
compares the two columns directly, which sidesteps it entirely.

⚠ `status_desc` and `intercompany` are NOT usable as an acceptance signal
------------------------------------------------------------------------
Both columns hold ACCEPTED / DECLINED / PROGRESS with the identical
distribution — 65,746 / 3 / 2. ``intercompany`` is plainly mis-mapped in the
ETL (it should carry an intercompany flag) and both are ~100% constant, so an
acceptance funnel built on either reads 99.99% forever. Acceptance is derived
from ``order_id <> ''`` instead, which gives a real 75.7%.

Likewise ``reply_created`` is NOT acceptance: 13,948 of its 18,570 ``'N'`` rows
do have an order. It records whether an EDI 990 reply went back out.

⚠ `purpose` and `cancelled_order` are the same fact
--------------------------------------------------
``purpose='CANCEL'`` ⇔ ``cancelled_order='Y'``, exactly, on all 8,750 rows.
ORIGINAL and CHANGE are always ``N``/``N``. Only ``order_cancelled`` adds
information, so the two-flag split the note describes is really one flag plus
an action-taken flag.

🔴 The stated invariant does NOT hold — and the gap is the point
---------------------------------------------------------------
The note states: ``cancelled_order='Y'`` and ``order_id`` not null ⇒
``order_cancelled='Y'``. Measured 2026-08-26: **1,596 rows violate it**, against
1,828 that satisfy it — a 46.6% violation rate, far too high to be ETL lag.

Joined to v4 those violations resolve into two very different populations:

    v4 status  rows  orders   reading
    V           877     860   already voided — the flag merely lags
    D           708     642   🔴 customer cancelled, we DELIVERED it anyway
    A             9       8
    P             2       2

So ``order_cancelled`` does not mean "the cancel was received", it means "we
actioned it in McLeod". The residue is an exception worklist, not noise: **644
distinct orders still sitting in status D/P carrying $588,016 of total_charge**
are loads the customer cancelled by EDI that nobody cancelled on our side.
That is what ``/exceptions`` serves, and it is the reason this report exists.

⚠ Money is missing on half the rows
-----------------------------------
32,392 rows (49.3%) have ``rate`` NULL-or-zero, and every one of those also has
``total_charge = 0``. Tender-side money is therefore never presented as a total
— the exception board takes its dollars from ``v4.total_charge`` instead.

⚠ `received` has no `updated_dt` companion
------------------------------------------
The table carries no ETL timestamp, so freshness is ``MAX(received)`` — an
event time, not a load time. Volume is business-hours shaped (~10-20/hour
07:00-17:00 CST, low single digits overnight), so a quiet evening looks like a
2-hour-stale feed. The staleness threshold is deliberately generous and the
endpoint reports the raw timestamp so a human can judge.
"""

from __future__ import annotations

import logging
from datetime import date, timedelta
from typing import Any, Optional

from fastapi import APIRouter, Depends, Query, Request

from app.clock import cst_today
from app.datalake import pad_variants
from app.routers.deps import get_datalake_gold_pool, require_report_access

logger = logging.getLogger(__name__)

router = APIRouter(tags=["edi-load-tenders"], prefix="/custom/edi-load-tenders")

REPORT_KEY = "edi-load-tenders"

TABLE = "public.mcleod_gld_edi_load_tender"
V4 = "public.mcleod_gld_budget_report_v4"

# `v4.id` is varchar(8) right-padded; the tender's `order_id` is a bare 7.
V4_ID_WIDTH = 8

# Column widths on the tender table, from information_schema 2026-08-26.
CUSTOMER_ID_WIDTH = 8
PURPOSE_WIDTH = 15
TEAM_ID_WIDTH = 8

# First row in the table. Anything earlier is a filter typo, not history.
DATA_FLOOR = date(2025, 8, 12)

PURPOSES = ("ORIGINAL", "CHANGE", "CANCEL")

# McLeod statuses that mean the order is still alive. Matches the five existing
# OPEN_STATUSES definitions; kept local rather than imported so this report does
# not inherit a change made for a margin report.
LIVE_STATUSES = ("D", "P")

# `reply_error` is 0 or 99 — 5,838 rows (8.9%) carry 99.
REPLY_OK = 0

MAX_ROWS = 2000

# A shipment can carry more than one order_id (137 of 37,188 on 2026-08-26).
# `max()` picks one deterministically; the count columns stay honest because
# they aggregate over rows, not over the picked id.
_SHIPMENT_ORDER_EXPR = "max(t.order_id) FILTER (WHERE t.order_id <> '')"


# --------------------------------------------------------------------------
# filters
# --------------------------------------------------------------------------


def _parse_multi(raw: Optional[list[str]]) -> list[str]:
    """Flatten repeated query params.

    Never comma-splits: customer names contain commas and splitting them yields
    an empty result set with no error.
    """
    out: list[str] = []
    for item in raw or []:
        if item is None:
            continue
        v = item.strip()
        if v:
            out.append(v)
    return out


def _month_start(d: date) -> date:
    return d.replace(day=1)


def _resolve_range(
    range_: Optional[str], start: Optional[date], end: Optional[date]
) -> tuple[date, date]:
    today = cst_today()
    if start and end:
        lo, hi = start, end
    elif range_ == "ytd":
        lo, hi = date(today.year, 1, 1), today
    elif range_ == "l30":
        lo, hi = today - timedelta(days=29), today
    elif range_ == "l90":
        lo, hi = today - timedelta(days=89), today
    elif range_ == "all":
        lo, hi = DATA_FLOOR, today
    else:  # "mtd"
        lo, hi = _month_start(today), today
    lo = max(lo, DATA_FLOOR)
    if hi < lo:
        hi = lo
    return lo, hi


def _common(
    range: Optional[str] = Query("mtd"),
    start_date: Optional[date] = Query(None),
    end_date: Optional[date] = Query(None),
    customer: Optional[list[str]] = Query(None),
    purpose: Optional[list[str]] = Query(None),
    team: Optional[list[str]] = Query(None),
):
    s, e = _resolve_range(range, start_date, end_date)
    return {
        "start": s,
        "end": e,
        "customers": _parse_multi(customer),
        "purposes": _parse_multi(purpose),
        "teams": _parse_multi(team),
    }


def _scope(f: dict) -> tuple[str, list]:
    """WHERE over the tender table plus the params that fill it.

    `received` is a timestamp, so the upper bound is an exclusive `< end + 1
    day` rather than `<= end` — a `<=` on a date silently drops everything that
    arrived after midnight on the last day.
    """
    params: list[Any] = [f["start"], f["end"] + timedelta(days=1)]
    where = ["t.received >= $1", "t.received < $2"]

    if f["customers"]:
        params.append(pad_variants(f["customers"], width=CUSTOMER_ID_WIDTH))
        where.append(f"t.customer_id = ANY(${len(params)})")

    if f["purposes"]:
        params.append(pad_variants(f["purposes"], width=PURPOSE_WIDTH))
        where.append(f"t.purpose = ANY(${len(params)})")

    if f["teams"]:
        # Team only exists for a tender we turned into an order, so a team
        # filter necessarily excludes the never-created population. That is
        # correct — an uncreated tender has no team — but it means the
        # "never created" KPI reads 0 whenever a team is selected, and the
        # endpoint flags that with `team_filtered`.
        params.append(pad_variants(f["teams"], width=TEAM_ID_WIDTH))
        where.append(
            f"EXISTS (SELECT 1 FROM {V4} b"
            f" WHERE b.id = rpad(t.order_id, {V4_ID_WIDTH})"
            f"   AND b.company_id = t.company_id"
            f"   AND b.team_id = ANY(${len(params)}))"
        )

    return " AND ".join(where), params


def _per_shipment_cte(where: str) -> str:
    """Roll the tender rows up to the shipment lifecycle."""
    return f"""
        WITH scoped AS (
            SELECT t.* FROM {TABLE} t WHERE {where}
        ),
        per_shipment AS (
            SELECT t.shipment_id,
                   max(t.customer_id)                                   AS customer_id,
                   max(t.customer)                                      AS customer,
                   count(*)                                             AS tenders,
                   count(*) FILTER (WHERE t.purpose = 'CANCEL')         AS cancels,
                   count(*) FILTER (WHERE t.reply_error <> {REPLY_OK})  AS reply_errors,
                   max(CASE WHEN t.order_id <> '' THEN 1 ELSE 0 END)    AS ever_created,
                   max(CASE WHEN t.order_cancelled = 'Y' THEN 1 ELSE 0 END)
                                                                        AS we_cancelled,
                   {_SHIPMENT_ORDER_EXPR}                               AS order_id,
                   max(t.company_id)                                    AS company_id,
                   min(t.received)                                      AS first_received,
                   max(t.received)                                      AS last_received
              FROM scoped t
             GROUP BY t.shipment_id
        )
    """


def _rate(num: Optional[float], den: Optional[float]) -> Optional[float]:
    if not den:
        return None
    return round(100.0 * float(num or 0) / float(den), 2)


def _f(v: Any) -> float:
    return float(v) if v is not None else 0.0


# --------------------------------------------------------------------------
# endpoints
# --------------------------------------------------------------------------


@router.get("/filters")
async def filters(
    request: Request,
    _user: dict = Depends(require_report_access(REPORT_KEY)),
):
    """Customer and team lists come from the data, not a constant.

    Seventeen customers send us EDI today; hardcoding them would silently drop
    the eighteenth the day trading starts.
    """
    pool = get_datalake_gold_pool(request)
    async with pool.acquire() as conn:
        customers = await conn.fetch(
            f"""
            SELECT trim(customer_id) AS value,
                   max(trim(customer)) AS label,
                   count(*) AS tenders
              FROM {TABLE}
             GROUP BY 1
             ORDER BY 3 DESC
            """
        )
        teams = await conn.fetch(
            f"""
            SELECT DISTINCT trim(b.team_id) AS value
              FROM {TABLE} t
              JOIN {V4} b ON b.id = rpad(t.order_id, {V4_ID_WIDTH})
                         AND b.company_id = t.company_id
             WHERE t.order_id <> '' AND b.team_id IS NOT NULL
             ORDER BY 1
            """
        )
    return {
        "success": True,
        "data": {
            "customers": [
                {"value": r["value"], "label": r["label"], "tenders": r["tenders"]}
                for r in customers
            ],
            "teams": [r["value"] for r in teams if r["value"]],
            "purposes": list(PURPOSES),
            "data_floor": DATA_FLOOR.isoformat(),
        },
    }


@router.get("/summary")
async def summary(
    request: Request,
    f: dict = Depends(_common),
    _user: dict = Depends(require_report_access(REPORT_KEY)),
):
    """The KPI row — everything at shipment grain except `tender_messages`."""
    where, params = _scope(f)
    pool = get_datalake_gold_pool(request)
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            _per_shipment_cte(where)
            + """
            SELECT count(*)                                    AS shipments,
                   coalesce(sum(tenders), 0)                   AS tender_messages,
                   coalesce(sum(reply_errors), 0)              AS reply_errors,
                   coalesce(sum(ever_created), 0)              AS created,
                   count(*) - coalesce(sum(ever_created), 0)   AS never_created,
                   count(*) FILTER (WHERE cancels > 0)         AS cust_cancelled,
                   count(*) FILTER (WHERE cancels > 0
                                      AND ever_created = 1)    AS cust_cancelled_created,
                   coalesce(sum(we_cancelled), 0)              AS we_cancelled,
                   count(*) FILTER (WHERE cancels > 0
                                      AND ever_created = 1
                                      AND we_cancelled = 0)    AS cancel_not_actioned
              FROM per_shipment
            """,
            *params,
        )

    shipments = int(row["shipments"] or 0)
    data = {
        "shipments": shipments,
        "tender_messages": int(row["tender_messages"] or 0),
        "reply_errors": int(row["reply_errors"] or 0),
        "created": int(row["created"] or 0),
        "never_created": int(row["never_created"] or 0),
        "cust_cancelled": int(row["cust_cancelled"] or 0),
        "cust_cancelled_created": int(row["cust_cancelled_created"] or 0),
        "we_cancelled": int(row["we_cancelled"] or 0),
        "cancel_not_actioned": int(row["cancel_not_actioned"] or 0),
        "start_date": f["start"].isoformat(),
        "end_date": f["end"].isoformat(),
        # A team filter can only match created orders, so `never_created`
        # is structurally 0 under one. Say so rather than render a lie.
        "team_filtered": bool(f["teams"]),
    }
    data["create_rate"] = _rate(data["created"], shipments)
    data["cancel_rate"] = _rate(data["cust_cancelled"], shipments)
    data["reply_error_rate"] = _rate(data["reply_errors"], data["tender_messages"])
    # Denominator is the cancels we COULD have actioned. A cancel on a shipment
    # we never turned into an order needs no action, and including those makes
    # the team look ~4x worse than it is (1,717 of 8,213 vs 1,717 of 3,952).
    data["actioned_rate"] = _rate(
        data["we_cancelled"], data["cust_cancelled_created"]
    )
    return {"success": True, "data": data}


@router.get("/chart")
async def chart(
    request: Request,
    grain: str = Query("day", pattern="^(day|week|month)$"),
    f: dict = Depends(_common),
    _user: dict = Depends(require_report_access(REPORT_KEY)),
):
    """Tender volume over time, bucketed on the shipment's FIRST tender.

    Bucketing every row would draw the amendment traffic, not the demand: a
    shipment tendered in June and amended four times in July would appear as
    five loads across two months.
    """
    where, params = _scope(f)
    pool = get_datalake_gold_pool(request)
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            _per_shipment_cte(where)
            + f"""
            SELECT date_trunc('{grain}', first_received)::date AS bucket,
                   count(*)                                   AS shipments,
                   coalesce(sum(ever_created), 0)             AS created,
                   count(*) FILTER (WHERE cancels > 0)        AS cust_cancelled,
                   count(*) FILTER (WHERE cancels > 0
                                      AND ever_created = 1
                                      AND we_cancelled = 0)   AS cancel_not_actioned
              FROM per_shipment
             GROUP BY 1
             ORDER BY 1
            """,
            *params,
        )
    return {
        "success": True,
        "data": [
            {
                "bucket": r["bucket"].isoformat(),
                "shipments": int(r["shipments"]),
                "created": int(r["created"]),
                "cust_cancelled": int(r["cust_cancelled"]),
                "cancel_not_actioned": int(r["cancel_not_actioned"]),
                "create_rate": _rate(r["created"], r["shipments"]),
            }
            for r in rows
        ],
    }


@router.get("/by-customer")
async def by_customer(
    request: Request,
    f: dict = Depends(_common),
    _user: dict = Depends(require_report_access(REPORT_KEY)),
):
    """One row per EDI trading partner."""
    where, params = _scope(f)
    pool = get_datalake_gold_pool(request)
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            _per_shipment_cte(where)
            + """
            SELECT trim(customer_id)                          AS customer_id,
                   trim(max(customer))                        AS customer,
                   count(*)                                   AS shipments,
                   coalesce(sum(tenders), 0)                  AS tender_messages,
                   coalesce(sum(ever_created), 0)             AS created,
                   count(*) - coalesce(sum(ever_created), 0)  AS never_created,
                   count(*) FILTER (WHERE cancels > 0)        AS cust_cancelled,
                   coalesce(sum(we_cancelled), 0)             AS we_cancelled,
                   count(*) FILTER (WHERE cancels > 0
                                      AND ever_created = 1
                                      AND we_cancelled = 0)   AS cancel_not_actioned
              FROM per_shipment
             GROUP BY 1
             ORDER BY 3 DESC
            """,
            *params,
        )
    return {
        "success": True,
        "data": [
            {
                "customer_id": r["customer_id"],
                "customer": r["customer"],
                "shipments": int(r["shipments"]),
                "tender_messages": int(r["tender_messages"]),
                "created": int(r["created"]),
                "never_created": int(r["never_created"]),
                "cust_cancelled": int(r["cust_cancelled"]),
                "we_cancelled": int(r["we_cancelled"]),
                "cancel_not_actioned": int(r["cancel_not_actioned"]),
                "create_rate": _rate(r["created"], r["shipments"]),
                "cancel_rate": _rate(r["cust_cancelled"], r["shipments"]),
            }
            for r in rows
        ],
        "meta": {"total": len(rows)},
    }


@router.get("/exceptions")
async def exceptions(
    request: Request,
    live_only: bool = Query(True),
    f: dict = Depends(_common),
    _user: dict = Depends(require_report_access(REPORT_KEY)),
):
    """🔴 Customer cancelled by EDI, order exists, nobody cancelled it here.

    ``live_only`` keeps only the orders still in status D/P — the ones that can
    still be acted on. Turn it off to see the already-voided ones too, which is
    how you tell "the flag lags" apart from "we shipped it anyway".

    Money comes from ``v4.total_charge``, never the tender's own ``rate``: half
    the tender rows carry no rate at all.
    """
    where, params = _scope(f)
    # ⚠ Append the status param ONLY when it is actually referenced. asyncpg
    # rejects a statement whose placeholder count is lower than the argument
    # count ("the server expects 2 arguments, 3 were passed"), so appending it
    # unconditionally 500s the whole endpoint under live_only=False.
    live_clause = ""
    if live_only:
        params.append(pad_variants(LIVE_STATUSES, width=1))
        live_clause = f"AND b.status = ANY(${len(params)})"

    pool = get_datalake_gold_pool(request)
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            _per_shipment_cte(where)
            + f"""
            SELECT s.shipment_id,
                   trim(s.order_id)      AS order_id,
                   trim(s.customer)      AS customer,
                   s.last_received,
                   trim(b.status)        AS status,
                   trim(b.team_id)       AS team_id,
                   b.total_charge,
                   b.margin_amt,
                   b.ordered_date
              FROM per_shipment s
              JOIN {V4} b ON b.id = rpad(s.order_id, {V4_ID_WIDTH})
                         AND b.company_id = s.company_id
             WHERE s.cancels > 0
               AND s.ever_created = 1
               AND s.we_cancelled = 0
               {live_clause}
             ORDER BY b.total_charge DESC NULLS LAST
             LIMIT {MAX_ROWS}
            """,
            *params,
        )

    out = [
        {
            "shipment_id": r["shipment_id"],
            "order_id": r["order_id"],
            "customer": r["customer"],
            "last_received": r["last_received"].isoformat() if r["last_received"] else None,
            "status": r["status"],
            "team_id": r["team_id"],
            "total_charge": _f(r["total_charge"]),
            "margin_amt": _f(r["margin_amt"]),
            "ordered_date": r["ordered_date"].isoformat() if r["ordered_date"] else None,
        }
        for r in rows
    ]
    return {
        "success": True,
        "data": out,
        "meta": {
            "total": len(out),
            "truncated": len(out) >= MAX_ROWS,
            "live_only": live_only,
            "total_charge": round(sum(r["total_charge"] for r in out), 2),
        },
    }


@router.get("/table")
async def table(
    request: Request,
    f: dict = Depends(_common),
    _user: dict = Depends(require_report_access(REPORT_KEY)),
):
    """Shipment-grain detail, newest tender first."""
    where, params = _scope(f)
    pool = get_datalake_gold_pool(request)
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            _per_shipment_cte(where)
            + f"""
            SELECT s.shipment_id,
                   trim(s.customer)   AS customer,
                   trim(s.order_id)   AS order_id,
                   s.tenders,
                   s.cancels,
                   s.ever_created,
                   s.we_cancelled,
                   s.reply_errors,
                   s.first_received,
                   s.last_received,
                   trim(b.status)     AS status,
                   trim(b.team_id)    AS team_id,
                   b.total_charge
              FROM per_shipment s
              LEFT JOIN {V4} b ON b.id = rpad(s.order_id, {V4_ID_WIDTH})
                              AND b.company_id = s.company_id
             ORDER BY s.last_received DESC
             LIMIT {MAX_ROWS}
            """,
            *params,
        )
    out = [
        {
            "shipment_id": r["shipment_id"],
            "customer": r["customer"],
            "order_id": r["order_id"] or None,
            "tenders": int(r["tenders"]),
            "cancels": int(r["cancels"]),
            "created": bool(r["ever_created"]),
            "we_cancelled": bool(r["we_cancelled"]),
            "reply_errors": int(r["reply_errors"]),
            "first_received": r["first_received"].isoformat() if r["first_received"] else None,
            "last_received": r["last_received"].isoformat() if r["last_received"] else None,
            "status": r["status"],
            "team_id": r["team_id"],
            "total_charge": _f(r["total_charge"]),
        }
        for r in rows
    ]
    return {
        "success": True,
        "data": out,
        "meta": {"total": len(out), "truncated": len(out) >= MAX_ROWS},
    }


@router.get("/freshness")
async def freshness(
    request: Request,
    _user: dict = Depends(require_report_access(REPORT_KEY)),
):
    """"Data as of" = ``MAX(received)``.

    There is no `updated_dt` on this table, so this is an EVENT time, not a
    load time — a quiet evening is indistinguishable from a stopped feed at
    small lags. The threshold is 6 hours: overnight traffic still runs a few
    rows an hour, so six consecutive empty hours is a real signal while an
    ordinary evening lull is not.
    """
    out: dict[str, Any] = {"received": None, "stale_minutes": None, "is_stale": False}
    try:
        pool = get_datalake_gold_pool(request)
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                f"""
                SELECT max(received) AS ts,
                       EXTRACT(EPOCH FROM (
                           (now() AT TIME ZONE 'America/Chicago') - max(received)
                       )) / 60 AS mins
                  FROM {TABLE}
                """
            )
        if row and row["ts"]:
            out["received"] = row["ts"].isoformat()
            out["stale_minutes"] = round(float(row["mins"] or 0), 1)
            out["is_stale"] = out["stale_minutes"] > 360
    except Exception as e:  # a dead feed must not 500 the page
        logger.warning("EDI Load Tenders freshness failed: %s", e)
    return {"success": True, "data": out}
