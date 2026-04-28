"""SONAR + 123LoadBoard monthly rate clients (Python port).

Purpose
-------
Fetch one-row-per-month historical benchmark prices for a US lane and persist
them in `aivn_datalake_gold.public.lane_market_rates`. Closed months are
cached permanently; the current MTD month is soft-cached for 24h.

Why a Python port (vs calling /BOT/quoting over HTTP)?
- Portal backend is FastAPI on Render; quoting is Node on Vercel — separate
  cold-start surface, separate auth, separate latency budget.
- The two endpoints we actually need (TRAC Statistics, Rate History Monthly)
  are <150 LOC each; trivial to port and now self-contained.

Scope guards
- US-only: lanes with non-2-char states (e.g. "CI" Chihuahua) skip the API
  call entirely and return None — both providers are US-only.
- Equipment: defaults to "VAN" (UNILINK lanes are overwhelmingly van).
"""

from __future__ import annotations

import asyncio
import calendar
import logging
import os
import re
from base64 import b64encode
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Optional

import httpx

from app.clock import cst_today

_ONE_DAY = timedelta(days=1)

logger = logging.getLogger(__name__)

# US-state regex: exactly two ASCII letters. Excludes "CI" (Chihuahua), "TM",
# "NL" (Nuevo León), "BC" (Baja California) etc. — those are valid 2-char codes
# in our data but not US states. We keep a positive whitelist.
_US_STATES = frozenset({
    "AL","AK","AZ","AR","CA","CO","CT","DE","FL","GA","HI","ID","IL","IN","IA",
    "KS","KY","LA","ME","MD","MA","MI","MN","MS","MO","MT","NE","NV","NH","NJ",
    "NM","NY","NC","ND","OH","OK","OR","PA","RI","SC","SD","TN","TX","UT","VT",
    "VA","WA","WV","WI","WY","DC",
})

_LANE_RE = re.compile(r"^\s*(.+?)\s*,\s*([A-Za-z]{2})\s*$")


@dataclass(frozen=True)
class Lane:
    origin_city: str
    origin_state: str
    dest_city: str
    dest_state: str
    equipment: str = "VAN"

    @property
    def is_us(self) -> bool:
        return (
            self.origin_state.upper() in _US_STATES
            and self.dest_state.upper() in _US_STATES
        )


def parse_lane_string(s: str) -> Optional[tuple[str, str]]:
    """Split 'TEMPLE, TX' → ('TEMPLE', 'TX'). None on bad input.

    Last-comma split so "GENERAL, ESCOBEDO, NL" still parses to (city, state)
    even when the city contains a comma.
    """
    if not s:
        return None
    m = _LANE_RE.match(s)
    if not m:
        return None
    return m.group(1).upper().strip(), m.group(2).upper()


def make_lane(origin_name: str, dest_name: str, equipment: str = "VAN") -> Optional[Lane]:
    """Build a Lane from carriers_savings_results_report origin_name/dest_name.

    Returns None when either side fails to parse. Caller should treat as
    "skip API, write nothing, surface — to UI".
    """
    o = parse_lane_string(origin_name)
    d = parse_lane_string(dest_name)
    if not o or not d:
        return None
    return Lane(o[0], o[1], d[0], d[1], equipment.upper())


@dataclass
class MonthlyRate:
    """Normalized output shared by both providers."""
    year_month: str           # 'YYYY-MM'
    avg_rate: Optional[float]
    min_rate: Optional[float]
    max_rate: Optional[float]
    avg_rpm: Optional[float]
    min_rpm: Optional[float]
    max_rpm: Optional[float]
    loads_included: Optional[int]
    mileage: Optional[int]
    raw: dict


# ============================================================================
# SONAR (FreightWaves) — TRAC Statistics, MONTHLY aggregation
# ============================================================================

_SONAR_BASE = "https://api.sonar.surf"
_SONAR_TIMEOUT = 20.0
_sonar_token: dict[str, float | str] | None = None  # {token, expires_at}
_sonar_kma_cache: list[dict] | None = None
_sonar_kma_lock = asyncio.Lock()


async def _sonar_token_value(client: httpx.AsyncClient) -> Optional[str]:
    """Return a valid SONAR bearer token, or None when not configured."""
    global _sonar_token

    static = os.environ.get("SONAR_TOKEN")
    if static:
        return static

    if _sonar_token and float(_sonar_token["expires_at"]) > datetime.now(timezone.utc).timestamp():
        return str(_sonar_token["token"])

    user = os.environ.get("SONAR_USERNAME")
    pw = os.environ.get("SONAR_PASSWORD")
    if not user or not pw:
        return None

    try:
        r = await client.post(
            f"{_SONAR_BASE}/Credential/authenticate",
            json={"Username": user, "Password": pw},
            timeout=_SONAR_TIMEOUT,
        )
        r.raise_for_status()
        data = r.json()
        token = data.get("token") or data.get("Token") or data
        token_str = token if isinstance(token, str) else str(token)
        _sonar_token = {
            "token": token_str,
            # Refresh monthly even though SONAR tokens last 365 days.
            "expires_at": datetime.now(timezone.utc).timestamp() + 30 * 86400,
        }
        return token_str
    except Exception as exc:
        logger.warning("[SONAR] auth failed: %s", exc)
        return None


async def _sonar_kma_ref(client: httpx.AsyncClient, token: str) -> list[dict]:
    """SONAR's airport-code/ZIP3 reference list. Cached for the process lifetime."""
    global _sonar_kma_cache
    if _sonar_kma_cache is not None:
        return _sonar_kma_cache
    async with _sonar_kma_lock:
        if _sonar_kma_cache is not None:
            return _sonar_kma_cache
        try:
            r = await client.get(
                f"{_SONAR_BASE}/lookup/KMARef",
                headers={"Authorization": f"Bearer {token}"},
                timeout=_SONAR_TIMEOUT,
            )
            r.raise_for_status()
            data = r.json() or []
            _sonar_kma_cache = [
                {
                    "city": (e.get("reference_City") or e.get("actual_City") or "").upper().strip(),
                    "state": (e.get("reference_State") or e.get("actual_State") or "").upper().strip(),
                    "zip3": e.get("zip3") or "",
                    "airport": e.get("airportCode") or "",
                }
                for e in data
            ]
            return _sonar_kma_cache
        except Exception as exc:
            logger.warning("[SONAR] KMARef fetch failed: %s", exc)
            _sonar_kma_cache = []
            return _sonar_kma_cache


def _sonar_pick_location(kma: list[dict], city: str, state: str) -> str:
    """Map (city,state) → airport code or ZIP3 SONAR will accept.

    SONAR rejects bare state codes; if we can't find a match, we fall back to
    the state — the API will return null, which is fine (cell shows "—").
    """
    cu, su = city.upper().strip(), state.upper().strip()
    for e in kma:
        if e["city"] == cu and e["state"] == su:
            return e["airport"] or e["zip3"] or su
    for e in kma:
        if e["state"] == su and (cu in e["city"] or e["city"] in cu):
            return e["airport"] or e["zip3"] or su
    return su


def _map_sonar_equipment(equipment: str) -> str:
    upper = equipment.upper()
    if "REEFER" in upper:
        return "REEFER"
    if "FLAT" in upper:
        return "FLATBED"
    return "VAN"


async def fetch_sonar_history(
    client: httpx.AsyncClient,
    lane: Lane,
    months: int = 24,
) -> list[MonthlyRate]:
    """One row per month from SONAR /v2/truckload/rates/trac/statistics."""
    if not lane.is_us:
        return []

    token = await _sonar_token_value(client)
    if not token:
        logger.debug("[SONAR] no credentials; skipping %s→%s", lane.origin_city, lane.dest_city)
        return []

    kma = await _sonar_kma_ref(client, token)
    origin = _sonar_pick_location(kma, lane.origin_city, lane.origin_state)
    dest = _sonar_pick_location(kma, lane.dest_city, lane.dest_state)

    today = cst_today()
    start = date(today.year, today.month, 1)
    # `months - 1` because the start date counts as month 1.
    for _ in range(months - 1):
        start = (start.replace(day=1) - _ONE_DAY).replace(day=1)

    body = {
        "start_date": start.isoformat(),
        "end_date": today.isoformat(),
        "aggregation": "MONTHLY",
        "lanes": [{
            "lane_id": f"{lane.origin_city}-{lane.origin_state}-{lane.dest_city}-{lane.dest_state}-stats",
            "origin": origin, "origin_country_code": "USA",
            "destination": dest, "destination_country_code": "USA",
            "equipment_type": _map_sonar_equipment(lane.equipment),
        }],
    }

    try:
        r = await client.post(
            f"{_SONAR_BASE}/v2/truckload/rates/trac/statistics",
            json=body,
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
            timeout=_SONAR_TIMEOUT,
        )
        if r.status_code == 401:
            global _sonar_token
            _sonar_token = None
            return []
        if r.status_code >= 400:
            logger.info("[SONAR] %s→%s status=%s body=%s",
                        lane.origin_city, lane.dest_city, r.status_code, r.text[:200])
            return []
        data = r.json() or {}
    except Exception as exc:
        logger.warning("[SONAR] %s→%s request failed: %s", lane.origin_city, lane.dest_city, exc)
        return []

    out: list[MonthlyRate] = []
    for entry in (data.get("lanes") or []):
        period = (entry.get("period_start_date") or entry.get("period")
                  or entry.get("start_date") or "")
        ym = str(period)[:7] if period else ""
        if len(ym) < 7:
            continue
        miles = entry.get("miles")
        out.append(MonthlyRate(
            year_month=ym,
            avg_rate=_num(entry.get("avg_rate")),
            min_rate=_num(entry.get("lowest_rate")) or _mul(entry.get("lowest_rpm"), miles),
            max_rate=_num(entry.get("highest_rate")) or _mul(entry.get("highest_rpm"), miles),
            avg_rpm=_num(entry.get("avg_rpm")),
            min_rpm=_num(entry.get("lowest_rpm")),
            max_rpm=_num(entry.get("highest_rpm")),
            loads_included=_int(entry.get("avg_total_load_count") or entry.get("total_load_count")),
            mileage=_int(miles),
            raw=entry,
        ))
    return out


# ============================================================================
# 123LoadBoard — Rate History, Monthly
# ============================================================================

_LB123_BASE = "https://api.123loadboard.com"
_LB123_API_VERSION = "1.3"
_LB123_TIMEOUT = 30.0
_lb123_token: dict[str, float | str] | None = None


async def _lb123_token_value(client: httpx.AsyncClient) -> Optional[str]:
    global _lb123_token

    if _lb123_token and float(_lb123_token["expires_at"]) > datetime.now(timezone.utc).timestamp():
        return str(_lb123_token["token"])

    cid = os.environ.get("LB123_CLIENT_ID")
    secret = os.environ.get("LB123_CLIENT_SECRET")
    if not cid or not secret:
        return None

    basic = b64encode(f"{cid}:{secret}".encode()).decode()
    try:
        r = await client.post(
            f"{_LB123_BASE}/token",
            content="grant_type=client_credentials&scope=ratecheck",
            headers={
                "123LB-Api-Version": _LB123_API_VERSION,
                "Content-Type": "application/x-www-form-urlencoded",
                "Authorization": f"Basic {basic}",
            },
            timeout=_LB123_TIMEOUT,
        )
        r.raise_for_status()
        data = r.json()
        token = data.get("access_token")
        if not token:
            return None
        _lb123_token = {
            "token": token,
            "expires_at": datetime.now(timezone.utc).timestamp()
            + max(60, int(data.get("expires_in", 3600)) - 60),
        }
        return token
    except Exception as exc:
        logger.warning("[123LB] auth failed: %s", exc)
        return None


def _map_lb123_equipment(equipment: str) -> str:
    m = {"VAN": "Van", "REEFER": "Reefer", "FLATBED": "Flatbed",
         "V": "Van", "R": "Reefer", "F": "Flatbed"}
    return m.get(equipment.upper(), "Van")


async def fetch_lb123_history(
    client: httpx.AsyncClient,
    lane: Lane,
    months: int = 12,
) -> list[MonthlyRate]:
    """One row per month from 123LB /ratechecks/history (timeSpan=Monthly)."""
    if not lane.is_us:
        return []

    token = await _lb123_token_value(client)
    if not token:
        return []

    today = cst_today()
    end_d = today
    start = date(today.year, today.month, 1)
    for _ in range(months - 1):
        start = (start.replace(day=1) - _ONE_DAY).replace(day=1)

    body = {
        "origin": {"city": lane.origin_city, "state": lane.origin_state},
        "destination": {"city": lane.dest_city, "state": lane.dest_state},
        "equipment": _map_lb123_equipment(lane.equipment),
        "timeSpan": "Monthly",
        "startDate": start.isoformat(),
        "endDate": end_d.isoformat(),
    }

    try:
        r = await client.post(
            f"{_LB123_BASE}/ratechecks/history",
            json=body,
            headers={
                "Authorization": f"Bearer {token}",
                "123LB-Api-Version": _LB123_API_VERSION,
                "123LB-AID": "analytics-hub-portal",
                "Content-Type": "application/json",
                "User-Agent": "Unilink-AnalyticsHub/1.0 (ithome@unilinkportal.com)",
            },
            timeout=_LB123_TIMEOUT,
        )
        if r.status_code >= 400:
            logger.info("[123LB] %s→%s status=%s body=%s",
                        lane.origin_city, lane.dest_city, r.status_code, r.text[:200])
            return []
        data = r.json() or {}
    except Exception as exc:
        logger.warning("[123LB] %s→%s request failed: %s", lane.origin_city, lane.dest_city, exc)
        return []

    items = data.get("revenues") or data.get("lanes") or []
    out: list[MonthlyRate] = []
    for it in items:
        ym_obj = it.get("yearMonth")
        ds = it.get("date") or it.get("startDate") or it.get("start_date")
        if isinstance(ym_obj, dict) and ym_obj.get("year") and ym_obj.get("month"):
            ym = f"{int(ym_obj['year']):04d}-{int(ym_obj['month']):02d}"
        elif isinstance(ds, str) and len(ds) >= 7:
            ym = ds[:7]
        else:
            continue
        avg_rpm = _num(it.get("avgRatePerMile") or it.get("averageRatePerMile"))
        min_rpm = _num(it.get("ratePerMileMin") or it.get("ratePerMileMinimum"))
        max_rpm = _num(it.get("ratePerMileMax") or it.get("ratePerMileMaximum"))
        miles = _num(it.get("totalMileage")) or _num(it.get("mileage"))
        out.append(MonthlyRate(
            year_month=ym,
            avg_rate=_mul(avg_rpm, miles) or _num(it.get("averageRateForMileage")),
            min_rate=_mul(min_rpm, miles) or _num(it.get("minRateForMileage")),
            max_rate=_mul(max_rpm, miles) or _num(it.get("maxRateForMileage")),
            avg_rpm=avg_rpm,
            min_rpm=min_rpm,
            max_rpm=max_rpm,
            loads_included=_int(it.get("loadsIncluded")),
            mileage=_int(miles),
            raw=it,
        ))
    return out


# ============================================================================
# Cache layer (PostgreSQL on aivn_datalake_gold)
# ============================================================================

# How long the current MTD month is considered "fresh" before we re-fetch.
MTD_CACHE_TTL_HOURS = 24


def _is_current_mtd(year_month: str) -> bool:
    today = cst_today()
    return year_month == f"{today.year:04d}-{today.month:02d}"


async def get_cached_rates(
    pool, lanes: list[Lane], year_months: list[str], source: str
) -> dict[tuple, MonthlyRate]:
    """Bulk read cached rows. Returns a map keyed by (city,state,city,state,equip,ym).

    A row is treated as "missing" (so caller refetches) when:
      - it doesn't exist, OR
      - year_month is the current MTD month AND fetched_at is > MTD_CACHE_TTL_HOURS old.
    """
    if not lanes or not year_months:
        return {}

    rows = await pool.fetch(
        """
        SELECT origin_city, origin_state, dest_city, dest_state, equipment, year_month, source,
               avg_rate, min_rate, max_rate, avg_rpm, min_rpm, max_rpm,
               loads_included, mileage, fetched_at
          FROM public.lane_market_rates
         WHERE source = $1
           AND year_month = ANY($2::text[])
           AND (origin_city, origin_state, dest_city, dest_state, equipment) IN (
                SELECT * FROM UNNEST(
                    $3::text[], $4::text[], $5::text[], $6::text[], $7::text[]
                )
           )
        """,
        source,
        year_months,
        [l.origin_city for l in lanes],
        [l.origin_state for l in lanes],
        [l.dest_city for l in lanes],
        [l.dest_state for l in lanes],
        [l.equipment for l in lanes],
    )

    cutoff = datetime.now(timezone.utc).timestamp() - MTD_CACHE_TTL_HOURS * 3600
    out: dict[tuple, MonthlyRate] = {}
    for r in rows:
        if _is_current_mtd(r["year_month"]) and r["fetched_at"].timestamp() < cutoff:
            continue
        key = (r["origin_city"], r["origin_state"], r["dest_city"], r["dest_state"],
               r["equipment"], r["year_month"])
        out[key] = MonthlyRate(
            year_month=r["year_month"],
            avg_rate=_num(r["avg_rate"]),
            min_rate=_num(r["min_rate"]),
            max_rate=_num(r["max_rate"]),
            avg_rpm=_num(r["avg_rpm"]),
            min_rpm=_num(r["min_rpm"]),
            max_rpm=_num(r["max_rpm"]),
            loads_included=_int(r["loads_included"]),
            mileage=_int(r["mileage"]),
            raw={},
        )
    return out


async def upsert_rates(
    pool, lane: Lane, source: str, monthly: list[MonthlyRate]
) -> int:
    """Insert/replace one provider's monthly rows for one lane."""
    if not monthly:
        return 0
    import json as _json

    args = []
    for m in monthly:
        args.append((
            lane.origin_city, lane.origin_state, lane.dest_city, lane.dest_state,
            lane.equipment, m.year_month, source,
            m.avg_rate, m.min_rate, m.max_rate,
            m.avg_rpm, m.min_rpm, m.max_rpm,
            m.loads_included, m.mileage,
            _json.dumps(m.raw, default=str),
        ))

    await pool.executemany(
        """
        INSERT INTO public.lane_market_rates
          (origin_city, origin_state, dest_city, dest_state, equipment, year_month, source,
           avg_rate, min_rate, max_rate, avg_rpm, min_rpm, max_rpm,
           loads_included, mileage, raw_payload, fetched_at)
        VALUES
          ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15,$16::jsonb, NOW())
        ON CONFLICT (origin_city, origin_state, dest_city, dest_state, equipment, year_month, source)
        DO UPDATE SET
          avg_rate = EXCLUDED.avg_rate,
          min_rate = EXCLUDED.min_rate,
          max_rate = EXCLUDED.max_rate,
          avg_rpm  = EXCLUDED.avg_rpm,
          min_rpm  = EXCLUDED.min_rpm,
          max_rpm  = EXCLUDED.max_rpm,
          loads_included = EXCLUDED.loads_included,
          mileage = EXCLUDED.mileage,
          raw_payload = EXCLUDED.raw_payload,
          fetched_at = NOW()
        """,
        args,
    )
    return len(args)


# ============================================================================
# helpers
# ============================================================================


def _num(v) -> Optional[float]:
    if v is None:
        return None
    try:
        f = float(v)
        return f if f != 0 else None
    except (TypeError, ValueError):
        return None


def _int(v) -> Optional[int]:
    n = _num(v)
    return int(n) if n is not None else None


def _mul(rpm, miles) -> Optional[float]:
    a, b = _num(rpm), _num(miles)
    if a is None or b is None:
        return None
    return round(a * b, 2)


# Calendar helper kept around for a future "include EOM in start_date" tweak.
def _last_day(year: int, month: int) -> int:
    return calendar.monthrange(year, month)[1]
