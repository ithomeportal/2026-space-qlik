"""Daily "Augie Funnel" e-mail digest (data layer).

Requested by Bruno 2026-10-16 (page 3 of "space Augie funnel report.pdf"): once
the funnel is live in Space, a daily e-mail with the CLOSE OF THE DAY BEFORE,
trends, and comparisons between relevant periods.

Pulled by an external n8n workflow (daily 07:00 CST, ops-digest recipients)
through ``GET /api/custom/augie-funnel/digest-email`` — see
``app/routers/augie_funnel_digest.py``. Rendering is in
``augie_funnel_digest_html.py``.

Every number is read back from the report's OWN endpoints in process via
``httpx.ASGITransport`` (the recruitment / attrition digest pattern), so the
e-mail is the page — one definition per metric.

Periods (D = yesterday, CST):
  * D vs the day before, and vs the same weekday last week (like-for-like:
    Saturday pickups are ~40% of a weekday's, so day-over-day alone misleads
    every Monday);
  * last 7 days vs the 7 before;
  * month-to-date vs the same calendar days of last month (clamped when last
    month is shorter);
  * a dense 14-day daily trend, and D by unit × team.

Refusal (503, never a misleading e-mail): the load feed has written nothing for
``augie_funnel.STALE_MINUTES`` — a stopped feed would print a quiet day.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import date, timedelta
from typing import Any, Optional

import httpx

from app.clock import cst_now, cst_today
from app.config import settings
from app.services.augie_funnel_digest_html import render_html

logger = logging.getLogger(__name__)

API_PREFIX = "/api/custom/augie-funnel"
REPORT_URL = "https://space.unilinkportal.com/reports/augie-funnel"
TREND_DAYS = 14

# The gold pool is shared by ~23 reports (max 8 connections): fetch in small
# batches rather than firing every call at once.
BATCH = 4


class DigestSourceError(RuntimeError):
    """A report endpoint failed — never render a partial e-mail."""


class DigestStaleError(DigestSourceError):
    """The Augie load feed stopped writing."""


_BUILD_LOCK = asyncio.Lock()


def _internal_headers() -> dict[str, str]:
    # Admin bypasses require_report_access (deps.py) -> the same SQL users hit.
    auth = (
        'Bearer {"sub":"augie-funnel-digest","email":"augie-funnel-digest@internal",'
        '"name":"augie-funnel-digest","roles":["admin"]}'
    )
    headers = {"authorization": auth}
    if settings.PROXY_SHARED_SECRET:
        headers["x-proxy-secret"] = settings.PROXY_SHARED_SECRET
    return headers


async def _get_many(app, calls: list[tuple[str, dict]]) -> list[dict]:
    """GET report endpoints in process, BATCH at a time. Any failure RAISES."""
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    out: list[dict] = []
    async with httpx.AsyncClient(
        transport=transport, base_url="http://augie-funnel-digest.internal",
        timeout=90.0,
    ) as client:
        for i in range(0, len(calls), BATCH):
            chunk = calls[i:i + BATCH]
            results = await asyncio.gather(
                *[client.get(f"{API_PREFIX}{path}", params=params,
                             headers=_internal_headers())
                  for path, params in chunk],
                return_exceptions=True,
            )
            for (path, params), res in zip(chunk, results):
                if isinstance(res, BaseException):
                    raise DigestSourceError(f"{path} {params} raised {res!r}")
                if res.status_code != 200:
                    raise DigestSourceError(f"{path} {params} returned {res.status_code}")
                payload = res.json()
                if not payload.get("success"):
                    raise DigestSourceError(f"{path} {params} returned success=false")
                out.append(payload)
    return out


# ---------------------------------------------------------------------------
# Periods + comparisons (pure, unit-tested)
# ---------------------------------------------------------------------------


def _same_day_last_month(d: date) -> date:
    """The same day-of-month last month, clamped to that month's last day."""
    first = d.replace(day=1)
    prev_last = first - timedelta(days=1)
    return prev_last.replace(day=min(d.day, prev_last.day))


def periods(d: date) -> dict[str, tuple[date, date]]:
    """Every window the e-mail compares, keyed by name. ``d`` = the closed day."""
    mtd_lo = d.replace(day=1)
    prev_hi = _same_day_last_month(d)
    return {
        "day": (d, d),
        "prev_day": (d - timedelta(days=1), d - timedelta(days=1)),
        "last_week_day": (d - timedelta(days=7), d - timedelta(days=7)),
        "last7": (d - timedelta(days=6), d),
        "prior7": (d - timedelta(days=13), d - timedelta(days=7)),
        "mtd": (mtd_lo, d),
        "prev_mtd": (prev_hi.replace(day=1), prev_hi),
        "trend": (d - timedelta(days=TREND_DAYS - 1), d),
    }


def compare(cur: dict, base: dict) -> dict[str, Any]:
    """Count deltas and percentage-POINT deltas of the two funnel rates.

    ⚠ Rates compare in points, never as a % of a %: 38% → 42% is "+4.0 pts",
    not "+10.5%". A rate with no denominator on either side is None.
    """
    def pts(key: str) -> Optional[float]:
        a, b = cur.get(key), base.get(key)
        return None if a is None or b is None else round(a - b, 1)

    def delta_pct(key: str) -> Optional[float]:
        b = base.get(key) or 0
        return None if b <= 0 else round(100.0 * (cur.get(key, 0) - b) / b, 1)

    return {
        "pickups": cur.get("pickups", 0) - base.get("pickups", 0),
        "pickups_pct": delta_pct("pickups"),
        "tracked": cur.get("tracked", 0) - base.get("tracked", 0),
        "captured": cur.get("captured", 0) - base.get("captured", 0),
        "tracked_pts": pts("tracked_pct"),
        "captured_pts": pts("captured_pct"),
    }


def assert_feed_fresh(fresh: dict) -> None:
    if fresh.get("is_stale"):
        raise DigestStaleError(
            f"Augie load feed last wrote {fresh.get('loads_updated')} "
            f"({fresh.get('loads_stale_minutes')} min ago)"
        )


def subject_for(d: date, day: dict) -> str:
    def pct(v: Optional[float]) -> str:
        return "n/a" if v is None else f"{v:.0f}%"

    return (f"Augie Funnel - {d.strftime('%a')} {d.strftime('%b')} {d.day}, {d.year} - "
            f"{day['pickups']:,} pickups, {pct(day['tracked_pct'])} tracked, "
            f"{pct(day['captured_pct'])} info captured")


def _range_params(lo: date, hi: date, **extra: Any) -> dict:
    return {"range": "custom", "start_date": lo.isoformat(),
            "end_date": hi.isoformat(), **extra}


# ---------------------------------------------------------------------------
# Build
# ---------------------------------------------------------------------------


async def build_augie_funnel_digest(app, day: Optional[date] = None) -> dict[str, Any]:
    async with _BUILD_LOCK:
        return await _build(app, day or cst_today() - timedelta(days=1))


_SUMMARY_KEYS = ("day", "prev_day", "last_week_day", "last7", "prior7", "mtd", "prev_mtd")


async def _build(app, d: date) -> dict[str, Any]:
    (fresh,) = await _get_many(app, [("/freshness", {})])
    assert_feed_fresh(fresh["data"])

    p = periods(d)
    calls = [("/summary", _range_params(*p[k])) for k in _SUMMARY_KEYS]
    calls += [
        ("/summary", _range_params(*p["day"], unit="CORP")),
        ("/summary", _range_params(*p["day"], unit="DFW")),
        ("/trend", _range_params(*p["trend"], grain="day")),
        ("/by-team", _range_params(*p["day"])),
    ]
    res = await _get_many(app, calls)
    s = {k: res[i]["data"] for i, k in enumerate(_SUMMARY_KEYS)}
    corp, dfw, trend, teams = (r["data"] for r in res[len(_SUMMARY_KEYS):])

    model = {
        "day": d,
        "periods": p,
        "summary": s,
        "units": {"CORP": corp, "DFW": dfw},
        "vs_prev_day": compare(s["day"], s["prev_day"]),
        "vs_last_week_day": compare(s["day"], s["last_week_day"]),
        "vs_prior7": compare(s["last7"], s["prior7"]),
        "vs_prev_mtd": compare(s["mtd"], s["prev_mtd"]),
        "trend": trend,
        "teams": teams,
        "freshness": fresh["data"],
        "report_url": REPORT_URL,
        "generated_at": cst_now(),
    }
    html = render_html(model)
    return {
        "subject": subject_for(d, s["day"]),
        "html": html,
        "generatedAt": model["generated_at"].isoformat(),
        "meta": {
            "day": d.isoformat(),
            "pickups": s["day"]["pickups"],
            "tracked": s["day"]["tracked"],
            "captured": s["day"]["captured"],
            "loads_updated": fresh["data"].get("loads_updated"),
        },
    }
