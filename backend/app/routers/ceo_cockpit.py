"""CEO Cockpit — one hero KPI per report, aggregated in-process.

The portal has ~27 code-made reports. The CEO wanted a single landing page
that surfaces the *one* headline number from each, colour-coded so anything
abnormal stands out, with a click-through to the full source report.

Rather than re-implement each report's SQL (and re-solve every McLeod
sargability / CST gotcha), this router calls the **existing** report endpoints
in-process via an httpx ASGITransport pointed at our own app. That means:

  * every tile number is byte-identical to the source report (KPI=detail holds)
  * zero changes to the underlying routers — this file is pure config
  * each underlying endpoint already gates itself, so access falls out for free
    (a 403 simply renders a "locked" tile)
  * one slow / broken report degrades to an "unavailable" tile, never blanks
    the page (each call is independently guarded)

Hero KPIs, baselines and red/amber/green thresholds below are a FIRST DRAFT
based on our read of executive importance — they are meant to be red-lined by
the CEO and re-tuned here (and, for access, via /admin/reports).
"""

from __future__ import annotations

import asyncio
import time
from typing import Any, Optional

import httpx
from fastapi import APIRouter, Depends, Query, Request

from app.clock import cst_now, cst_today
from app.routers.deps import require_report_access

router = APIRouter(tags=["ceo-cockpit"], prefix="/custom/ceo-cockpit")

# ---------------------------------------------------------------------------
# Tile catalogue
# ---------------------------------------------------------------------------
# Each spec:
#   key        report seed key (drives access grouping)
#   title      display title
#   category   group bucket (ordered by _CATEGORY_ORDER)
#   label      what the hero number means
#   endpoint   path AFTER /api (the live router prefix, may differ from `key`)
#   params     query string sent to the endpoint
#   value_path dotted path into the JSON body to the hero number
#   unit       "usd" | "pct" | "count"
#   scale      multiply raw value (e.g. 100 for a 0–1 ratio)  [optional]
#   deeplink   /reports/<seed-key> to open on click  [defaults to /reports/<key>]
#   compare    status rule (see _evaluate)
#
# A "good/warn/bad" direction is encoded in each compare rule.

TILES: list[dict[str, Any]] = [
    # ---- Executive --------------------------------------------------------
    {
        "key": "ceo-executive",
        "title": "CEO Executive",
        "category": "Executive",
        "label": "MTD Profit",
        "endpoint": "/custom/ceo-executive/overview",
        "params": {"range": "mtd"},
        "value_path": "data.kpis.profit",
        "unit": "usd",
        # NOTE: `profit_tm` is MTD *actual* profit from the budget-report source
        # (a 2nd reading of the same number), NOT a target — so it's not a valid
        # baseline. No real quota is exposed here; show plain MTD profit.
        "compare": {"type": "sign"},
    },
    {
        "key": "xray-corp-mng",
        "title": "XRay CORP Mng",
        "category": "Executive",
        "label": "MTD Profit",
        "endpoint": "/custom/xray-corp/kpis",
        "params": {"range": "mtd"},
        "value_path": "data.profit",
        "unit": "usd",
        "compare": {"type": "sign"},  # profit_tm is not a target — see CEO Executive note
    },
    # ---- Operations -------------------------------------------------------
    {
        "key": "budget-followup-2026",
        "title": "2026 Budget Follow Up",
        "category": "Operations",
        "label": "Revenue vs Budget (MTD pace)",
        "endpoint": "/custom/budget-followup/summary",
        # Window = month-start..today so it's MTD actual vs MTD budget (a fair
        # "on pace?" %). The default (full-year) makes YTD/full-year-budget,
        # which always reads ~40% mid-year — a false alarm.
        "params": {"start_date": "@month_start", "end_date": "@today"},
        "value_path": "data.revenue_achievement_pct",
        "unit": "pct",
        "compare": {"type": "high", "green": 100, "warn": 90},
    },
    {
        "key": "attrition-wow",
        "title": "Attrition WoW",
        "category": "Operations",
        "label": "Last-Week Profit vs 8-wk avg",
        "endpoint": "/custom/attrition-wow/summary",
        "params": {},
        "value_path": "data.profit.lw",
        "unit": "usd",
        "compare": {"type": "delta_high", "baseline_path": "data.profit.l8w_avg",
                    "warn_pct": -10},
    },
    {
        "key": "ops-direct-compare",
        "title": "OPs Direct Compare",
        "category": "Operations",
        "label": "MTD Profit",
        "endpoint": "/custom/ops-direct-compare/panel-summary",
        "params": {"range": "mtd"},
        "value_path": "data.profit",
        "unit": "usd",
        "compare": {"type": "sign"},
    },
    {
        "key": "ops-customer-score",
        "title": "OPs Customer Score",
        "category": "Operations",
        "label": "Pickup On-Time % (MTD)",
        "endpoint": "/custom/ops-customer-score/pu/overview",
        "params": {"range": "mtd"},
        "value_path": "data.kpi.pct_on_time",
        "unit": "pct",
        "compare": {"type": "high", "green": 95, "warn": 90},
    },
    {
        "key": "losses-lanes",
        "title": "Top Losses Lanes",
        "category": "Operations",
        "label": "MTD Loss (neg-margin loads)",
        "endpoint": "/custom/losses-lanes/summary",
        "params": {"range": "mtd"},
        "value_path": "data.profit",
        "unit": "usd",
        "compare": {"type": "loss"},
    },
    {
        "key": "esavings-carriers",
        "title": "eSavings from Carriers",
        "category": "Operations",
        "label": "Net Variance (savings vs overpay)",
        "endpoint": "/custom/carriers-savings/summary",
        "params": {},
        "value_path": "data.net_variance",
        "unit": "usd",
        "compare": {"type": "sign"},
    },
    {
        "key": "carrier-risk",
        "title": "Risk Asss for Carriers",
        "category": "Operations",
        "label": "Single-carrier volume % (MTD)",
        "endpoint": "/custom/carrier-risk/kpis",
        "params": {"range": "mtd"},
        "value_path": "data.single_carrier_volume_pct",
        "unit": "pct",
        "compare": {"type": "low", "green": 30, "warn": 50},
    },
    {
        "key": "track-award-loads",
        "title": "Track Award Loads",
        "category": "Operations",
        "label": "Awarded Profit vs Projected",
        "endpoint": "/custom/track-award-loads/kpis",
        "params": {},
        "value_path": "data.profit.actual_profit",
        "unit": "usd",
        "compare": {"type": "achievement",
                    "baseline_path": "data.profit.projected_profit"},
    },
    # ---- DFW --------------------------------------------------------------
    {
        "key": "xray-dfw-mng",
        "title": "XRay DFW Mng",
        "category": "DFW",
        "label": "MTD Profit",
        "endpoint": "/custom/xray-dfw/kpis",
        "params": {"range": "mtd"},
        "value_path": "data.profit",
        "unit": "usd",
        "compare": {"type": "sign"},  # profit_tm is not a target — see CEO Executive note
    },
    {
        "key": "podium-dfw",
        "title": "Podium Set DFW",
        "category": "DFW",
        "label": "MTD Rate Confirmations",
        "endpoint": "/custom/podium-dfw/overview",
        "params": {"range": "mtd"},
        "value_path": "data.kpis.loads",
        "unit": "count",
        "compare": {"type": "neutral"},
    },
    {
        "key": "dfw-access-doors",
        "title": "DFW Access Doors",
        "category": "DFW",
        "label": "On-Time Punch % (today)",
        "endpoint": "/custom/dfw-access-doors/kpis",
        "params": {},
        "value_path": "data.pct_on_time",
        "unit": "pct",
        "scale": 100,
        "compare": {"type": "high", "green": 90, "warn": 75},
    },
    # ---- Finance ----------------------------------------------------------
    {
        "key": "admin-cashflow",
        "title": "Admin Aging Cashflow",
        "category": "Finance",
        "label": "Total Unbilled $ (lower is better)",
        "endpoint": "/custom/admin-cashflow/kpis",
        "params": {},
        "value_path": "data.total_unbilled_usd",
        "unit": "usd",
        "compare": {"type": "low_dynamic", "threshold_path": "data.alarm_threshold_usd",
                    "green_frac": 0.6},
    },
    # ---- Sales ------------------------------------------------------------
    {
        "key": "rfp-performance",
        "title": "Performance for RFPs",
        "category": "Sales",
        "label": "Awarded Conversion Ratio (YTD)",
        "endpoint": "/custom/rfp-performance/summary",
        "params": {},
        "value_path": "data.won.awarded_convertio_ratio",
        "unit": "pct",
        "scale": 100,
        "compare": {"type": "high", "green": 20, "warn": 10},  # DRAFT threshold
    },
    # ---- HR ---------------------------------------------------------------
    {
        "key": "hr-access-doors",
        "title": "HR Access Doors",
        "category": "HR",
        "label": "On-Time Punch % (today)",
        "endpoint": "/custom/hr-access-doors/kpis",
        "params": {},
        "value_path": "data.pct_on_time",
        "unit": "pct",
        "scale": 100,
        "compare": {"type": "high", "green": 90, "warn": 75},
    },
    # ---- IT ---------------------------------------------------------------
    {
        "key": "it-tickets-mgmt",
        "title": "IT Tickets Mgmt",
        "category": "IT",
        "label": "% Tickets Closed",
        "endpoint": "/custom/it-tickets/summary",
        "params": {},
        "value_path": "data.kpis.pct_closed",
        "unit": "pct",
        "compare": {"type": "high", "green": 80, "warn": 60},
    },
    {
        "key": "voip-calls-logs",
        "title": "VoIP Calls Logs",
        "category": "IT",
        "label": "Calls This Week",
        "endpoint": "/custom/voip-calls/summary",
        "params": {},
        "value_path": "data.total_calls",
        "unit": "count",
        "compare": {"type": "neutral"},
    },
    # ---- Admin ------------------------------------------------------------
    {
        "key": "admin-access-doors",
        "title": "Admin Access Doors",
        "category": "Admin",
        "label": "On-Time Punch % (today)",
        "endpoint": "/custom/admin-access-doors/kpis",
        "params": {},
        "value_path": "data.pct_on_time",
        "unit": "pct",
        "scale": 100,
        "compare": {"type": "high", "green": 90, "warn": 75},
    },
]

# Reports with no single monitorable headline KPI — shown as subdued
# "open to explore" cards so the cockpit still represents every report.
LINK_TILES: list[dict[str, Any]] = [
    {"key": "ops-margins", "title": "OPs Margins", "category": "Operations",
     "note": "Best/worst margin leaderboards — open to explore"},
    {"key": "ops-portal-overview", "title": "Ops Portal - Overview", "category": "Operations",
     "note": "Multi-source operations overview — open to explore"},
    {"key": "kam-performance-dfw", "title": "KAM Performance - DFW", "category": "DFW",
     "note": "Per-KAM scorecards — open to explore"},
    {"key": "sales-attrition-to-ops", "title": "Sales- Attrition to OPs", "category": "Sales",
     "note": "Sales→Ops attrition crossover — open to explore"},
    {"key": "dfw-podium-top", "title": "DFW Podium Top", "category": "DFW",
     "note": "Top-3 leaderboards — open to explore"},
    {"key": "bonus-calculator", "title": "Bonus Calculator", "category": "Finance",
     "note": "Per-team monthly bonus engine — open to explore"},
]

_CATEGORY_ORDER = ["Executive", "Operations", "DFW", "Finance", "Sales", "HR", "IT", "Admin"]

# In-process result cache, keyed by the caller's role set (different leaders
# see different tiles). Short TTL — protects the source DBs from a burst of
# ~19 in-process reads on every reload without serving meaningfully stale data.
_CACHE: dict[frozenset, tuple[float, dict]] = {}
_CACHE_TTL = 90.0  # seconds


def _resolve_params(params: Optional[dict]) -> Optional[dict]:
    """Replace date sentinels with live CST values at request time.

    `@month_start` → first day of the current CST month, `@today` → today (CST).
    Lets a tile request a month-to-date window without hard-coding dates.
    """
    if not params:
        return None
    today = cst_today()
    subs = {
        "@month_start": today.replace(day=1).isoformat(),
        "@today": today.isoformat(),
    }
    return {k: (subs.get(v, v) if isinstance(v, str) else v) for k, v in params.items()}


# Beyond this, an achievement/delta % is noise (e.g. projected ≈ 0): keep the
# colour, drop the meaningless number.
_DELTA_PCT_CAP = 999.0


def _clamp_delta(delta_pct: Optional[float]) -> Optional[float]:
    if delta_pct is None or abs(delta_pct) > _DELTA_PCT_CAP:
        return None
    return delta_pct


def _dig(obj: Any, path: str) -> Any:
    """Walk a dotted path into nested dicts; return None on any miss."""
    cur = obj
    for part in path.split("."):
        if not isinstance(cur, dict) or part not in cur:
            return None
        cur = cur[part]
    return cur


def _extract_as_of(body: dict) -> Optional[str]:
    """Best-effort 'data as of' timestamp from the common window shapes."""
    for path in ("data.window.end", "data.window.start", "meta.window.end",
                 "data.windows.lw.end", "data.month_date", "data.range.end"):
        v = _dig(body, path)
        if isinstance(v, str):
            return v
    return None


def _evaluate(
    rule: dict, value: float, body: dict,
) -> tuple[str, Optional[float], Optional[float], Optional[float]]:
    """Return (status, baseline, delta_abs, delta_pct).

    status ∈ {"good", "warn", "bad", "neutral"}.
    """
    rtype = rule["type"]

    if rtype == "achievement":
        baseline = _dig(body, rule["baseline_path"])
        if baseline in (None, 0):
            return "neutral", baseline, None, None
        baseline = float(baseline)
        delta_abs = value - baseline
        ach = value / baseline
        delta_pct = (ach - 1.0) * 100.0
        status = "good" if ach >= 1.0 else "warn" if ach >= 0.9 else "bad"
        return status, baseline, delta_abs, _clamp_delta(delta_pct)

    if rtype == "delta_high":
        baseline = _dig(body, rule["baseline_path"])
        if baseline in (None, 0):
            return "neutral", baseline, None, None
        baseline = float(baseline)
        delta_abs = value - baseline
        delta_pct = (value / baseline - 1.0) * 100.0
        warn_pct = rule.get("warn_pct", -10)
        status = "good" if delta_pct >= 0 else "warn" if delta_pct >= warn_pct else "bad"
        return status, baseline, delta_abs, _clamp_delta(delta_pct)

    if rtype == "high":
        status = ("good" if value >= rule["green"]
                  else "warn" if value >= rule["warn"] else "bad")
        return status, None, None, None

    if rtype == "low":
        status = ("good" if value < rule["green"]
                  else "warn" if value < rule["warn"] else "bad")
        return status, None, None, None

    if rtype == "low_dynamic":
        thr = _dig(body, rule["threshold_path"])
        if thr in (None, 0):
            return "neutral", None, None, None
        thr = float(thr)
        green = thr * rule.get("green_frac", 0.6)
        status = "good" if value < green else "warn" if value < thr else "bad"
        return status, thr, None, None

    if rtype == "sign":
        return ("good" if value >= 0 else "bad"), None, None, None

    if rtype == "loss":
        # value is a negative-margin total (≤ 0); any loss is flagged.
        return ("bad" if value < 0 else "good"), None, None, None

    return "neutral", None, None, None


async def _fetch_tile(client: httpx.AsyncClient, auth: str, spec: dict) -> dict:
    """Call one report endpoint in-process and reduce it to a tile."""
    base = {
        "key": spec["key"],
        "title": spec["title"],
        "category": spec["category"],
        "label": spec["label"],
        "unit": spec["unit"],
        "deeplink": spec.get("deeplink", f"/reports/{spec['key']}"),
        "value": None,
        "baseline": None,
        "delta_abs": None,
        "delta_pct": None,
        "status": "unavailable",
        "as_of": None,
    }
    try:
        resp = await client.get(
            f"/api{spec['endpoint']}",
            params=_resolve_params(spec.get("params")),
            headers={"authorization": auth, "content-type": "application/json"},
        )
    except Exception:
        return base

    if resp.status_code == 403:
        return {**base, "status": "locked"}
    if resp.status_code != 200:
        return base

    try:
        body = resp.json()
    except ValueError:
        return base
    if not isinstance(body, dict) or not body.get("success"):
        return base

    raw = _dig(body, spec["value_path"])
    if raw is None:
        return base
    try:
        value = float(raw) * float(spec.get("scale", 1))
    except (TypeError, ValueError):
        return base

    status, baseline, delta_abs, delta_pct = _evaluate(spec["compare"], value, body)
    return {
        **base,
        "value": value,
        "baseline": baseline,
        "delta_abs": delta_abs,
        "delta_pct": delta_pct,
        "status": status,
        "as_of": _extract_as_of(body),
    }


def _link_tile(spec: dict) -> dict:
    return {
        "key": spec["key"],
        "title": spec["title"],
        "category": spec["category"],
        "note": spec.get("note"),
        "deeplink": spec.get("deeplink", f"/reports/{spec['key']}"),
        "status": "link",
    }


@router.get("/summary")
async def summary(
    request: Request,
    fresh: int = Query(0, description="1 = bypass the in-process cache"),
    _user: dict = Depends(require_report_access("ceo-cockpit")),
):
    """One round-trip for the whole cockpit: every report's hero KPI.

    Response: { success, data: { generated_at, category_order, tiles[],
    link_tiles[] }, meta: { cached } }.
    """
    roles = frozenset(r.lower() for r in (_user.get("roles") or []))
    now = time.monotonic()

    if not fresh:
        hit = _CACHE.get(roles)
        if hit and hit[0] > now:
            return {"success": True, "data": hit[1], "meta": {"cached": True}}

    auth = request.headers.get("authorization", "")
    transport = httpx.ASGITransport(app=request.app, raise_app_exceptions=False)
    async with httpx.AsyncClient(
        transport=transport, base_url="http://cockpit.internal", timeout=30.0,
    ) as client:
        tiles = await asyncio.gather(*[_fetch_tile(client, auth, t) for t in TILES])

    payload = {
        "generated_at": cst_now().isoformat(),
        "category_order": _CATEGORY_ORDER,
        "tiles": list(tiles),
        "link_tiles": [_link_tile(t) for t in LINK_TILES],
    }
    _CACHE[roles] = (now + _CACHE_TTL, payload)
    return {"success": True, "data": payload, "meta": {"cached": False}}
