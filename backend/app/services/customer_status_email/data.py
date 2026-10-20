"""Datalake reads for the customer load-status e-mails.

One statement per SOURCE, never one per load — every load of all four reports
is read in a single pass and partitioned in Python (``cards.py``).

Sources (all ``aivn_datalake_gold`` via the savings pool unless noted):
  ORDERS_SQL     v4 + customer_view + customer_windows (all three keyed on the
                 padded ``(id, company_id)`` PK — no fan-out possible)
  MOVEMENTS_SQL  mcleod_gld_movement — leg status + the MacroPoint link
  AUGIE_SQL      app_augment_n8n_data_ra_rt — last GPS city + ETA, per LEG
  COMMENTS_SQL   mcleod_gld_order_post_hist — last customer-safe comment
  POD_SQL        unilink_portal_ap.pod_tracker_loads — POD file link (AP pool)

Traps handled here (docs/SPEC-CUSTOMER-STATUS-EMAIL.md):
  • McLeod keys are PADDED (``'0349842 '``, ``'TMS '``); the Augie feed and the
    AP tracker store them TRIMMED — a plain join returns 0 rows, no error.
  • Every McLeod timestamp uses ``1900-01-01`` for "none" — guarded > 2000.
  • ``blnum`` / ``carrier_trailer`` are EMPTY STRINGS before assignment, not
    NULL — ``NULLIF(btrim(..), '')``.
  • ``mcleod_gld_control_tower_callin`` (the McLeod call-in mirror) holds 0
    rows; the last call-in comment comes from ``order_post_hist`` instead.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Any, Optional
from zoneinfo import ZoneInfo

import httpx

from app.config import settings
from app.services.customer_status_email.config import BILL_TO

logger = logging.getLogger(__name__)

# Orders older than this are never in an e-mail: an A/P load ordered 90+ days
# ago is a data-entry orphan, not a live load (max seen 2026-10-20: 12 days).
ORDER_LOOKBACK_DAYS = 90
# Delivered loads are fetched with a wide margin; the exact 24-hour cut is
# applied per destination time zone in cards.py (stop times are LOCAL).
DELIVERED_FETCH_HOURS = 30
# Comments older than this are not "the most current status".
COMMENT_LOOKBACK_DAYS = 14
# The v4 mirror updates every ~15 min by day but only a few rows an hour at
# night; a max(updated_dt) older than this means the feed is dead, not quiet.
STALE_FEED_HOURS = 8


class StaleFeedError(RuntimeError):
    """The order feed stopped — mailing it would report stale status as current."""


def _ts(col: str) -> str:
    """A McLeod timestamp with the 1900-01-01 'none' sentinel mapped to NULL."""
    return f"CASE WHEN {col} > '2000-01-01' THEN {col} END"


ORDERS_SQL = f"""
SELECT b.id                                            AS id,
       b.company_id                                    AS company_id,
       btrim(b.status)                                 AS status,
       btrim(b.origin_city_name)                       AS origin_city,
       btrim(b.origin_state_id)                        AS origin_state,
       btrim(b.dest_city_name)                         AS dest_city,
       btrim(b.dest_state_id)                          AS dest_state,
       NULLIF(btrim(v.po), '')                         AS po,
       NULLIF(btrim(v.blnum), '')                      AS bol,
       NULLIF(btrim(v.carrier_trailer), '')            AS trailer,
       NULLIF(btrim(v.location_name), '')              AS consignee,
       NULLIF(btrim(v.delivery_location), '')          AS delivery_location,
       {_ts('w.orig_sched_arrive_early')}              AS pu_sched_early,
       {_ts('w.orig_sched_arrive_late')}               AS pu_sched_late,
       {_ts('w.orig_actual_arrival')}                  AS pu_in,
       {_ts('w.orig_actual_departure')}                AS pu_out,
       {_ts('w.dest_sched_arrive_early')}              AS del_sched_early,
       {_ts('w.dest_sched_arrive_late')}               AS del_sched_late,
       {_ts('w.dest_actual_arrival')}                  AS del_in,
       {_ts('w.dest_actual_departure')}                AS del_out
FROM mcleod_gld_budget_report_v4 b
JOIN mcleod_gld_customer_view    v ON v.id = b.id AND v.company_id = b.company_id
JOIN mcleod_gld_customer_windows w ON w.id = b.id AND w.company_id = b.company_id
WHERE b.customer_id = $1
  AND b.status IN ('A', 'P', 'D')
  AND b.ordered_date >= $2
  AND (b.status <> 'D'
       OR w.dest_actual_arrival >= $3
       OR w.dest_actual_departure >= $3)
"""

# Global, not per customer: a quiet customer must not read as a dead feed.
# A future-dated row (bad data) must not make a dead feed look fresh forever.
FRESHNESS_SQL = (
    "SELECT max(updated_dt) FROM mcleod_gld_budget_report_v4 "
    "WHERE updated_dt <= localtimestamp + interval '1 hour'"
)

MOVEMENTS_SQL = """
SELECT m.order_id                                  AS id,
       m.movement_id                               AS movement_id,
       btrim(m.brokerage_status)                   AS brokerage_status,
       NULLIF(btrim(m.br_details_link), '')        AS track_link
FROM mcleod_gld_movement m
WHERE m.order_id = ANY($1::varchar[])
  AND m.company_id = ANY($2::varchar[])
"""

AUGIE_SQL = """
SELECT r.id                                        AS id,
       r.movement_id                               AS movement_id,
       btrim(r.dest_city_name)                     AS leg_dest_city,
       btrim(r.dest_state)                         AS leg_dest_state,
       r.destin_sche_arrieve_late                  AS leg_sched_late,
       r.new_eta                                   AS eta,
       NULLIF(btrim(r.geo_city_name), '')          AS geo_city,
       NULLIF(btrim(r.geo_state), '')              AS geo_state,
       r.gps_updated_dt                            AS gps_at
FROM app_augment_n8n_data_ra_rt r
WHERE r.company_id = ANY($1::varchar[])
  AND r.id = ANY($2::varchar[])
  AND NOT COALESCE(r.is_deleted, false)
"""

# Customer-safe comment types only (decision 2026-10-20): Augie tracking
# events / carrier + stop updates, loaded, departed, empty at consignee,
# appointment confirmed. Excluded on purpose: AUGCOMME (call outcomes such as
# "Voicemail, no answer from the driver"), SVCINCD (incident attribution),
# BRKSTCHG (raw status codes), rate/settlement/billing types, blank (call
# recordings). The phrase filter drops the Augie updates that only say a call
# failed. Change both together with the spec.
SAFE_COMMENT_TYPES: tuple[str, ...] = (
    "AUGTRAEV", "AUGCARRU", "AUGSTOPU", "LOADSHIP", "ADDTNSTP", "UNLDCONS", "APPTCNFM",
)
UNSAFE_COMMENT_PATTERN = (
    r"(unable to|no answer|voicemail|no human|identity|did not answer|not reachable)"
)

COMMENTS_SQL = """
SELECT DISTINCT ON (h.id)
       h.id                                        AS id,
       btrim(h.posted_type)                        AS posted_type,
       h.posted_date                               AS posted_at,
       btrim(h.comments)                           AS comment
FROM mcleod_gld_order_post_hist h
WHERE h.id = ANY($1::varchar[])
  AND h.company_id = ANY($2::varchar[])
  AND btrim(h.posted_type) = ANY($3::text[])
  AND h.comments !~* $4
  AND h.posted_date >= $5
ORDER BY h.id, h.posted_date DESC
"""

# Augie phone/e-mail location pings (Augment TRACKING_UPDATE webhooks). TRIMMED
# order ids; event_utc is a real timestamptz → shown on the CST clock.
PINGS_SQL = """
SELECT DISTINCT ON (l.order_id)
       l.order_id                                              AS id,
       btrim(l.city)                                           AS city,
       NULLIF(btrim(l.state_or_province), '')                  AS state,
       (l.event_utc AT TIME ZONE 'America/Chicago')            AS at_cst
FROM app_load_locations l
WHERE l.order_id = ANY($1::varchar[])
  AND NULLIF(btrim(l.city), '') IS NOT NULL
ORDER BY l.order_id, l.event_utc DESC
"""

TTCONTROL_PATH = "/api/share/customer-tracking"
TTCONTROL_BATCH = 200  # the route's own cap
TTCONTROL_TIMEOUT_S = 20.0

POD_SQL = """
SELECT mcleod_order_id AS id, has_pod, pod_file_url
FROM pod_tracker_loads
WHERE mcleod_order_id = ANY($1::varchar[])
"""


async def fetch_freshness(pool: Any) -> Optional[datetime]:
    async with pool.acquire() as conn:
        return await conn.fetchval(FRESHNESS_SQL)


def assert_fresh(last_update: Optional[datetime], now_cst: datetime) -> None:
    """Raise when the order feed is older than STALE_FEED_HOURS (naive CST)."""
    if last_update is None:
        raise StaleFeedError("order feed is empty")
    age = now_cst.replace(tzinfo=None) - last_update
    if age > timedelta(hours=STALE_FEED_HOURS):
        raise StaleFeedError(f"order feed last updated {last_update:%Y-%m-%d %H:%M} CST")


async def fetch_orders(pool: Any, now_cst: datetime) -> list[dict]:
    naive_now = now_cst.replace(tzinfo=None)
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            ORDERS_SQL,
            BILL_TO,
            naive_now - timedelta(days=ORDER_LOOKBACK_DAYS),
            naive_now - timedelta(hours=DELIVERED_FETCH_HOURS),
        )
    return [dict(r) for r in rows]


async def fetch_details(
    gold_pool: Any, ap_pool: Any, orders: list[dict], now_cst: datetime
) -> dict[str, dict[str, Any]]:
    """Movements, Augie legs, comments and PODs for ``orders``, keyed by TRIMMED id.

    The POD read is optional (``AP_DATABASE_URL`` may be unset) and fails SOFT —
    a card then simply shows no POD link. The gold reads are not optional: a
    failure raises, and the run is recorded failed rather than mailing a card
    with a silently missing status.
    """
    if not orders:
        return {"movements": {}, "augie": {}, "comments": {}, "pods": {}, "pings": {},
                "tt": {}}
    padded_ids = sorted({o["id"] for o in orders})
    padded_cos = sorted({o["company_id"] for o in orders})
    trimmed_ids = sorted({i.strip() for i in padded_ids})
    trimmed_cos = sorted({c.strip() for c in padded_cos})
    since = now_cst.replace(tzinfo=None) - timedelta(days=COMMENT_LOOKBACK_DAYS)

    async with gold_pool.acquire() as conn:
        moves = await conn.fetch(MOVEMENTS_SQL, padded_ids, padded_cos)
        legs = await conn.fetch(AUGIE_SQL, trimmed_cos, trimmed_ids)
        comments = await conn.fetch(
            COMMENTS_SQL, padded_ids, padded_cos, list(SAFE_COMMENT_TYPES),
            UNSAFE_COMMENT_PATTERN, since,
        )
        pings = await conn.fetch(PINGS_SQL, trimmed_ids)

    pods: dict[str, dict] = {}
    if ap_pool is not None:
        try:
            async with ap_pool.acquire() as conn:
                for r in await conn.fetch(POD_SQL, trimmed_ids):
                    pods[r["id"].strip()] = dict(r)
        except Exception as exc:  # noqa: BLE001 — POD link is an optional extra
            logger.error("customer status email: POD read failed, links omitted: %s", exc)

    return {
        "movements": _group(moves),
        "augie": _group(legs),
        "comments": {r["id"].strip(): dict(r) for r in comments},
        "pods": pods,
        "pings": {r["id"].strip(): dict(r) for r in pings},
        # Only loads still moving need a live link / position.
        "tt": await fetch_ttcontrol(
            sorted({o["id"].strip() for o in orders if (o.get("status") or "").strip() == "P"})),
    }


async def fetch_ttcontrol(order_ids: list[str]) -> dict[str, dict]:
    """Carrier share links + positions from TTControl, keyed by trimmed id.

    Optional and fail-SOFT: unset secret or any HTTP fault ⇒ {} (the e-mail
    still goes, without share links). ⚠ Share URLs are bearer credentials —
    never logged here.
    """
    secret = settings.TTCONTROL_TRACKING_SECRET
    if not secret or not order_ids:
        return {}
    out: dict[str, dict] = {}
    url = settings.TTCONTROL_URL.rstrip("/") + TTCONTROL_PATH
    try:
        async with httpx.AsyncClient(timeout=TTCONTROL_TIMEOUT_S) as client:
            for i in range(0, len(order_ids), TTCONTROL_BATCH):
                batch = order_ids[i:i + TTCONTROL_BATCH]
                r = await client.get(url, params={"orders": ",".join(batch)},
                                     headers={"Authorization": f"Bearer {secret}"})
                r.raise_for_status()
                out.update(parse_ttcontrol(r.json()))
    except Exception as exc:  # noqa: BLE001 — optional enrichment
        logger.error("customer status email: TTControl feed failed, no share links: %s",
                     type(exc).__name__)
        return {}
    return out


def parse_ttcontrol(payload: dict) -> dict[str, dict]:
    """TTControl's envelope → {order: {share_link, share_provider, place, at_cst}}."""
    out: dict[str, dict] = {}
    for oid, row in ((payload or {}).get("data") or {}).items():
        link = (row or {}).get("shareLink") or {}
        url = link.get("url")
        pos = (row or {}).get("position") or {}
        at_cst = None
        if pos.get("atUtc"):
            at = datetime.fromisoformat(pos["atUtc"].replace("Z", "+00:00"))
            at_cst = at.astimezone(ZoneInfo("America/Chicago")).replace(tzinfo=None)
        out[str(oid).strip()] = {
            "share_link": url if isinstance(url, str) and url.startswith("https://") else None,
            "share_provider": link.get("provider"),
            "place": pos.get("place"),
            "at_cst": at_cst,
        }
    return out


def _group(rows: list) -> dict[str, list[dict]]:
    out: dict[str, list[dict]] = {}
    for r in rows:
        out.setdefault(r["id"].strip(), []).append(dict(r))
    return out
