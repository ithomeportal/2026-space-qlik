"""SONAR Coverage Guide — live origin/destination tender-rejection % per lane.

Bruno PDF 2026-10-16 "Ops Portal Updates" R6: the Ops Portal "By Lane" table
shows **Origin Rejection %** and **Dest Rejection %**. Source is the live
FreightWaves SONAR Coverage Guide, the same call the pricing portal makes
(`/BOT/quoting/.../lib/sonar/api-client.ts` ``querySonarCoverageGuide``):

    POST https://api.sonar.surf/v2/truckload/coverage_guide
    {"lanes": [{lane_id, origin, origin_country_code: "USA",
                destination, destination_country_code: "USA", equipment_type}]}

    origin_rejection_pct = lane.origin_rejection_percent
    dest_rejection_pct   = lane.destination_rejection_percent

Units are PERCENT (7.4 means 7.4 %) — the pricing portal prints the raw value
with a "%" suffix and colours it at 15 / 8 / 4.

⚠ These are CURRENT market readings. They are NOT tied to the report's date
filter, and the UI says so.

Budget (why this module is so defensive)
----------------------------------------
SONAR allows **100 requests/min ACCOUNT-WIDE**, shared with the quoting portal
(Manual Spots, RFP "Get Rates"), plus a weekly TRAC record quota. On
2026-07-22 the quoting portal burned the window and every SONAR call returned
null for 38 minutes. So:

* only lanes the endpoint is about to RETURN are looked up (its top N);
* only US→US lanes with a ZIP on both ends — the location is ZIP5 (else ZIP3),
  mirroring the pricing portal's ``buildLaneLocation`` first two rungs. No KMA
  lookup, no state-only location (SONAR rejects bare states). The state must be
  in the US whitelist because a Mexican ZIP is often also a valid US ZIP (Juárez
  ``67250`` is a Kansas ZIP) and would silently return a US market;
* lanes are batched ``BATCH_SIZE`` per request (the pricing portal's
  ``SONAR_BATCH_SIZE``) and at most ``MAX_FETCH_LANES`` per page view;
* every answer is cached in the portal-owned ``sonar_lane_rejection_cache``
  (analytics_hub): a reading for 24 h, a "SONAR has nothing for this lane" for
  ``EMPTY_TTL`` so an unresolvable lane is not re-asked on every page view;
* a failed request is NOT cached (it says nothing about the lane) but opens a
  process-local cooldown so a SONAR outage is not hammered by every viewer;
* one in-process lock serialises fetches — two viewers opening the portal at
  once do not both pay for the same lanes;
* the whole lookup runs under a hard ``TOTAL_TIMEOUT_S`` budget. On timeout or
  any error the columns are null and the table still renders. Never a 5xx.
"""

from __future__ import annotations

import asyncio
import logging
import re
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Iterable, Optional

import httpx

from app.services import lane_rates
from app.services.lane_rates import _US_STATES, _map_sonar_equipment

logger = logging.getLogger(__name__)

COVERAGE_GUIDE_URL = f"{lane_rates._SONAR_BASE}/v2/truckload/coverage_guide"

# Pricing portal: SONAR_BATCH_SIZE = 25 ("SONAR accepts an array of lanes and
# echoes each back under its own lane_id").
BATCH_SIZE = 25
# At most this many uncached lanes are looked up per page view (= 4 requests).
# The rest stay "—" until the next view; the cache fills in a few views.
MAX_FETCH_LANES = 100
# Wall-clock budget for the lock wait + SONAR fetch (the cache read is outside
# it). Short, because By Lane waits on it; lanes not reached fill on a later view.
TOTAL_TIMEOUT_S = 4.0
REQUEST_TIMEOUT_S = 3.5

DATA_TTL = timedelta(hours=24)
EMPTY_TTL = timedelta(hours=6)
# After a failed request, skip SONAR for this long (process-local).
FAILURE_COOLDOWN_S = 300.0

SOURCE_LABEL = "SONAR coverage guide (live, current market)"

SONAR_REJECTION_CACHE_DDL = """
CREATE TABLE IF NOT EXISTS sonar_lane_rejection_cache (
  origin_key           TEXT        NOT NULL,
  dest_key             TEXT        NOT NULL,
  equipment            TEXT        NOT NULL,
  origin_rejection_pct NUMERIC,
  dest_rejection_pct   NUMERIC,
  has_data             BOOLEAN     NOT NULL,
  fetched_at           TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  PRIMARY KEY (origin_key, dest_key, equipment)
)
"""

_ZIP5 = re.compile(r"^\d{5}")
_ZIP3 = re.compile(r"^\d{3}")

_fetch_lock = asyncio.Lock()
_cooldown_until: float = 0.0


@dataclass(frozen=True)
class LaneKey:
    """What SONAR is asked — and the cache's primary key."""
    origin_key: str
    dest_key: str
    equipment: str

    @property
    def lane_id(self) -> str:
        return f"{self.origin_key}-{self.dest_key}-{self.equipment}"


@dataclass(frozen=True)
class Rejection:
    origin_rejection_pct: Optional[float]
    dest_rejection_pct: Optional[float]
    fetched_at: Optional[datetime] = None

    @property
    def has_data(self) -> bool:
        return self.origin_rejection_pct is not None or self.dest_rejection_pct is not None


# ---------------------------------------------------------------------------
# Lane resolution (pure)
# ---------------------------------------------------------------------------


def location_code(state: Optional[str], zip_code: Optional[str]) -> Optional[str]:
    """ZIP5 → ZIP3 for a US state; None otherwise (never a bare state)."""
    st = (state or "").strip().upper()
    if st not in _US_STATES:
        return None
    z = (zip_code or "").strip()
    if _ZIP5.match(z):
        return z[:5]
    if _ZIP3.match(z):
        return z[:3]
    return None


def map_equipment(descr: Optional[str]) -> str:
    """v4 equipment description → SONAR equipment_type (VAN default)."""
    return _map_sonar_equipment(descr or "")


def lane_key(
    origin_state: Optional[str], origin_zip: Optional[str],
    dest_state: Optional[str], dest_zip: Optional[str],
    equipment_descr: Optional[str],
) -> Optional[LaneKey]:
    """A SONAR-askable lane, or None (non-US / no ZIP ⇒ the cell is "—")."""
    o = location_code(origin_state, origin_zip)
    d = location_code(dest_state, dest_zip)
    if not o or not d:
        return None
    return LaneKey(o, d, map_equipment(equipment_descr))


def build_request_body(keys: list[LaneKey]) -> dict:
    return {
        "lanes": [
            {
                "lane_id": k.lane_id,
                "origin": k.origin_key,
                "origin_country_code": "USA",
                "destination": k.dest_key,
                "destination_country_code": "USA",
                "equipment_type": k.equipment,
            }
            for k in keys
        ]
    }


def _pct(v) -> Optional[float]:
    """Percent value or None. ⚠ 0 is a real reading (no rejections), keep it."""
    if v is None or isinstance(v, bool):
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def parse_response(data, keys: list[LaneKey]) -> dict[LaneKey, Rejection]:
    """Map a coverage-guide response back onto the keys that were asked.

    Rows are matched by the echoed ``lane_id``. A response row WITHOUT a
    lane_id is only trusted when exactly one lane was asked — positional
    matching on a multi-lane batch would mislabel every lane after one that
    SONAR dropped. Asked lanes absent from the answer are a definitive
    "no data" (the request itself succeeded).
    """
    by_id = {k.lane_id: k for k in keys}
    found: dict[LaneKey, Rejection] = {}
    rows = data.get("lanes") if isinstance(data, dict) else None
    for row in rows if isinstance(rows, list) else []:
        if not isinstance(row, dict):
            continue
        lid = row.get("lane_id")
        key = by_id.get(str(lid)) if lid is not None else (keys[0] if len(keys) == 1 else None)
        if key is None or (key in found and found[key].has_data):
            continue
        found[key] = Rejection(
            _pct(row.get("origin_rejection_percent")),
            _pct(row.get("destination_rejection_percent")),
        )
    return {k: found.get(k, Rejection(None, None)) for k in keys}


# ---------------------------------------------------------------------------
# Cache (analytics_hub, portal-owned)
# ---------------------------------------------------------------------------


def _is_fresh(has_data: bool, fetched_at: datetime, now: datetime) -> bool:
    ttl = DATA_TTL if has_data else EMPTY_TTL
    return fetched_at > now - ttl


async def read_cache(pool, keys: list[LaneKey], now: datetime) -> dict[LaneKey, Rejection]:
    """Fresh cached rows for ``keys`` (stale rows are treated as missing)."""
    if not keys:
        return {}
    rows = await pool.fetch(
        """
        SELECT origin_key, dest_key, equipment,
               origin_rejection_pct, dest_rejection_pct, has_data, fetched_at
          FROM sonar_lane_rejection_cache
         WHERE (origin_key, dest_key, equipment) IN (
               SELECT * FROM UNNEST($1::text[], $2::text[], $3::text[]))
        """,
        [k.origin_key for k in keys],
        [k.dest_key for k in keys],
        [k.equipment for k in keys],
    )
    out: dict[LaneKey, Rejection] = {}
    for r in rows:
        fetched = r["fetched_at"]
        if not _is_fresh(bool(r["has_data"]), fetched, now):
            continue
        key = LaneKey(r["origin_key"], r["dest_key"], r["equipment"])
        out[key] = Rejection(_pct(r["origin_rejection_pct"]), _pct(r["dest_rejection_pct"]), fetched)
    return out


async def write_cache(pool, results: dict[LaneKey, Rejection]) -> None:
    if not results:
        return
    await pool.executemany(
        """
        INSERT INTO sonar_lane_rejection_cache
          (origin_key, dest_key, equipment, origin_rejection_pct,
           dest_rejection_pct, has_data, fetched_at)
        VALUES ($1, $2, $3, $4, $5, $6, NOW())
        ON CONFLICT (origin_key, dest_key, equipment) DO UPDATE SET
          origin_rejection_pct = EXCLUDED.origin_rejection_pct,
          dest_rejection_pct   = EXCLUDED.dest_rejection_pct,
          has_data             = EXCLUDED.has_data,
          fetched_at           = NOW()
        """,
        [
            (k.origin_key, k.dest_key, k.equipment,
             v.origin_rejection_pct, v.dest_rejection_pct, v.has_data)
            for k, v in results.items()
        ],
    )


# ---------------------------------------------------------------------------
# SONAR fetch
# ---------------------------------------------------------------------------


def _credentials_configured() -> bool:
    import os
    return bool(os.environ.get("SONAR_TOKEN")) or lane_rates._has_password_auth()


def _open_cooldown(reason: str) -> None:
    global _cooldown_until
    _cooldown_until = time.monotonic() + FAILURE_COOLDOWN_S
    # Error CLASS / status only — never a body, header or token.
    logger.warning("[SONAR coverage] %s — skipping SONAR for %ds", reason, int(FAILURE_COOLDOWN_S))


def _in_cooldown() -> bool:
    return time.monotonic() < _cooldown_until


async def _fetch_chunk(client: httpx.AsyncClient, keys: list[LaneKey]) -> Optional[dict[LaneKey, Rejection]]:
    """One request. None = the request failed (nothing is learned or cached)."""
    token = await lane_rates._sonar_token_value(client)
    if not token:
        _open_cooldown("no usable SONAR credential")
        return None
    r = await client.post(
        COVERAGE_GUIDE_URL,
        json=build_request_body(keys),
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        timeout=REQUEST_TIMEOUT_S,
    )
    if r.status_code in (401, 403):
        lane_rates._sonar_token = None
        lane_rates._handle_auth_rejection(f"coverage guide (HTTP {r.status_code})")
        _open_cooldown(f"coverage guide HTTP {r.status_code}")
        return None
    if r.status_code >= 400:
        _open_cooldown(f"coverage guide HTTP {r.status_code}")
        return None
    return parse_response(r.json(), keys)


async def fetch_from_sonar(
    keys: list[LaneKey], client: Optional[httpx.AsyncClient] = None, on_chunk=None,
) -> dict[LaneKey, Rejection]:
    """Batched coverage-guide lookups. A failed chunk stops the run (cooldown).

    ``on_chunk`` (async) is awaited with each successful chunk's answers, so a
    run cut short by the time budget still keeps what it already paid for.
    """
    out: dict[LaneKey, Rejection] = {}
    own = client is None
    http = client or httpx.AsyncClient()
    try:
        for i in range(0, len(keys), BATCH_SIZE):
            if _in_cooldown() or lane_rates._sonar_disabled_reason is not None:
                break
            chunk = keys[i:i + BATCH_SIZE]
            try:
                got = await _fetch_chunk(http, chunk)
            except Exception as exc:  # noqa: BLE001 — fail soft, log the class only
                _open_cooldown(f"coverage guide request failed ({type(exc).__name__})")
                break
            if got is None:
                break
            out.update(got)
            if on_chunk is not None:
                await on_chunk(got)
    finally:
        if own:
            await http.aclose()
    return out


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


def _dedupe(keys: Iterable[Optional[LaneKey]]) -> list[LaneKey]:
    seen: dict[LaneKey, None] = {}
    for k in keys:
        if k is not None:
            seen.setdefault(k, None)
    return list(seen)


async def _fetch_missing(
    pool, keys: list[LaneKey], client, sink: dict[LaneKey, Rejection],
) -> None:
    """Fill ``sink`` with what is still missing from it: cache re-read, then SONAR.

    ``sink`` is written as answers ARRIVE (cache re-read, then each persisted
    chunk) so a caller whose time budget runs out still has every reading
    gathered so far — a timeout must not throw away rows already in hand.
    """
    async with _fetch_lock:
        now = datetime.now(timezone.utc)
        # Another viewer may have filled these while we waited for the lock.
        sink.update(await read_cache(pool, [k for k in keys if k not in sink], now))
        missing = [k for k in keys if k not in sink][:MAX_FETCH_LANES]
        if not missing or _in_cooldown():
            return

        async def _persist(got: dict[LaneKey, Rejection]) -> None:
            stamp = datetime.now(timezone.utc)
            sink.update({k: Rejection(v.origin_rejection_pct, v.dest_rejection_pct, stamp)
                         for k, v in got.items()})
            try:
                await write_cache(pool, got)
            except Exception as exc:  # noqa: BLE001
                logger.warning("[SONAR coverage] cache write failed (%s)", type(exc).__name__)

        await fetch_from_sonar(missing, client, on_chunk=_persist)


async def get_rejections(
    pool, keys: Iterable[Optional[LaneKey]], client: Optional[httpx.AsyncClient] = None,
    timeout_s: float = TOTAL_TIMEOUT_S,
) -> dict[LaneKey, Rejection]:
    """Cached-or-live readings for ``keys``. Never raises.

    ``pool`` is the analytics_hub pool (portal-owned cache). With no pool or
    no SONAR credential, nothing is fetched — the cache alone answers.

    The cache read is OUTSIDE the time budget and the budget bounds only the
    lock wait + SONAR fetch (review 2026-10-16): on a timeout the cached rows
    and any chunks already fetched are still returned, never ``{}``.
    """
    wanted = _dedupe(keys)
    if pool is None or not wanted:
        return {}
    try:
        found = dict(await read_cache(pool, wanted, datetime.now(timezone.utc)))
    except Exception as exc:  # noqa: BLE001 — the table must render regardless
        logger.warning("[SONAR coverage] cache read failed (%s)", type(exc).__name__)
        return {}
    if all(k in found for k in wanted) or _in_cooldown() or not _credentials_configured():
        return found
    try:
        await asyncio.wait_for(_fetch_missing(pool, wanted, client, found), timeout=timeout_s)
    except asyncio.TimeoutError:
        logger.warning("[SONAR coverage] fetch exceeded %.1fs — partial columns", timeout_s)
    except Exception as exc:  # noqa: BLE001
        logger.warning("[SONAR coverage] fetch failed (%s) — partial columns", type(exc).__name__)
    return dict(found)


def reset_state_for_tests() -> None:
    global _cooldown_until, _fetch_lock
    _cooldown_until = 0.0
    _fetch_lock = asyncio.Lock()
