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
from app.config import settings
from app.routers.deps import (
    get_allowed_roles_for_report,
    get_pool,
    require_report_access,
)

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
        "desc": "Sum of margin_amt for all CORP + DFW loads departing this "
                "month (month-to-date). Includes accessorial profit.",
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
        "desc": "Sum of margin_amt for CORP loads (teams 1–5) departing this "
                "month (month-to-date).",
    },
    {
        "key": "xray-dfw-mng",
        "title": "XRay DFW Mng",
        "category": "Executive",
        "label": "MTD Profit",
        "endpoint": "/custom/xray-dfw/kpis",
        "params": {"range": "mtd"},
        "value_path": "data.profit",
        "unit": "usd",
        "compare": {"type": "sign"},  # profit_tm is not a target — see CEO Executive note
        "desc": "Sum of margin_amt for DFW loads (team TEAM-DFW) departing "
                "this month (month-to-date).",
    },
    {
        # "Better or Worse Profit" (Bruno 2026-05-29): the MoM swing in profit.
        # value shown = Σ margin_amt this month − Σ margin_amt last month
        # (same all-division scope), green when up, red when down. Reuses
        # ops-direct-compare/panel-summary (mtd vs last_month) — no new SQL.
        "key": "profit-mom",
        "title": "Profit — Better or Worse",
        "category": "Executive",
        "label": "MTD profit Δ vs last month",
        "endpoint": "/custom/ops-direct-compare/panel-summary",
        "params": {"range": "mtd"},
        "value_path": "data.profit",
        "baseline_endpoint": "/custom/ops-direct-compare/panel-summary",
        "baseline_params": {"range": "last_month"},
        "baseline_value_path": "data.profit",
        "unit": "usd",
        "compare": {"type": "mom_delta"},
        "deeplink": "/reports/ops-direct-compare",
        "desc": "This month's profit (Σ margin_amt) minus last month's, same "
                "company-wide scope. Positive (green) = doing better than "
                "last month.",
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
        "desc": "MTD actual revenue ÷ MTD budgeted revenue × 100 "
                "(100% = on pace with budget).",
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
        "desc": "Last completed week's profit; the Δ compares it to the "
                "trailing 8-week average.",
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
        "desc": "Sum of margin_amt for all CORP + DFW loads departing this "
                "month (month-to-date).",
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
        "desc": "Loads picked up on/before scheduled pickup ÷ total pickups "
                "this month × 100.",
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
        "desc": "Sum of margin_amt across loads with negative margin this "
                "month (the MTD loss).",
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
        "desc": "Carrier savings minus overpay, measured against each lane's "
                "quarterly base rate.",
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
        "desc": "Share of this month's load volume handled by the single "
                "largest carrier (lower = less concentration risk).",
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
        "desc": "Actual profit on awarded loads; the Δ compares it to "
                "projected awarded profit.",
    },
    # ---- DFW --------------------------------------------------------------
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
        "desc": "Count of rate confirmations (loads booked) this month.",
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
        "desc": "On-time first punch-ins ÷ scored punch-ins today, DFW badge "
                "readers (× 100).",
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
        "desc": "Total unbilled dollars aging in accounts receivable "
                "(lower is better).",
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
        "desc": "Awarded RFP lanes ÷ total bid lanes, year-to-date (× 100).",
    },
    # ---- HR ---------------------------------------------------------------
    {
        "key": "hr-access-doors",
        "title": "HR Access Doors",
        "category": "HR",
        "label": "Arrived On-Time % (today)",
        "endpoint": "/custom/hr-access-doors/kpis",
        "params": {},
        "value_path": "data.pct_on_time",
        "unit": "pct",
        "scale": 100,
        "compare": {"type": "high", "green": 90, "warn": 75},
        "desc": "People who arrived on time ÷ scored first punch-ins today "
                "(× 100).",
    },
    {
        # Bruno 2026-05-29: the complement of on-time. Same endpoint, the
        # pct_out_of_time field — late arrivals ÷ scored punch-ins today.
        "key": "hr-access-doors-late",
        "title": "HR Access Doors",
        "category": "HR",
        "label": "Arrived Late % (today)",
        "endpoint": "/custom/hr-access-doors/kpis",
        "params": {},
        "value_path": "data.pct_out_of_time",
        "unit": "pct",
        "scale": 100,
        "compare": {"type": "low", "green": 10, "warn": 25},
        "deeplink": "/reports/hr-access-doors",
        "desc": "People who did NOT arrive on time ÷ scored first punch-ins "
                "today (× 100; the complement of arrived-on-time).",
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
        "desc": "Closed tickets ÷ total tickets in scope × 100.",
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
        "desc": "Total call legs logged so far this week.",
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
        "desc": "On-time first punch-ins ÷ scored punch-ins today, Admin "
                "badge readers (× 100).",
    },
]

# Reports with no single monitorable headline KPI — shown as subdued
# "open to explore" cards so the cockpit still represents every report.
# Tiles whose backing endpoint accepts a borrowed report key (§52) and therefore
# cannot self-gate on a 403 any more. Re-gated on genuine access below.
_BORROWED_ENDPOINT_TILES = frozenset({"ops-customer-score"})

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
    {"key": "bonus-calculator", "title": "Bonus Calculator", "category": "HR",
     "note": "Per-team monthly bonus engine — open to explore"},
    # Bruno PDF 2026-08-20. ⚠ This catalog is a FIFTH mirror the new-report
    # checklist in docs/SPEC-BONUS-CALCULATOR.md does not list — a clone that
    # follows the 4-place checklist literally goes missing from the Cockpit.
    {"key": "bonus-calculator-dfw", "title": "Bonus Calculator – DFW", "category": "HR",
     "note": "DFW monthly bonus engine (15/16/17/18/19% margin ladder) — open to explore"},
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


async def _fetch_one(
    client: httpx.AsyncClient, auth: str, endpoint: str,
    params: Optional[dict], value_path: str,
) -> tuple[Optional[float], Optional[dict], str]:
    """Call one endpoint in-process and dig a single float out of it.

    Returns (value, body, hint) where hint ∈ {"ok", "locked", "unavailable"}.
    `value` is None unless hint == "ok".
    """
    try:
        # These fan-out calls re-enter our own app via ASGITransport and so hit
        # require_user again — they must carry the proxy secret, exactly like a
        # request arriving from the Next.js proxy would.
        headers = {"authorization": auth, "content-type": "application/json"}
        if settings.PROXY_SHARED_SECRET:
            headers["x-proxy-secret"] = settings.PROXY_SHARED_SECRET
        resp = await client.get(
            f"/api{endpoint}",
            params=_resolve_params(params),
            headers=headers,
        )
    except Exception:
        return None, None, "unavailable"

    if resp.status_code == 403:
        return None, None, "locked"
    if resp.status_code != 200:
        return None, None, "unavailable"

    try:
        body = resp.json()
    except ValueError:
        return None, None, "unavailable"
    if not isinstance(body, dict) or not body.get("success"):
        return None, None, "unavailable"

    raw = _dig(body, value_path)
    if raw is None:
        return None, body, "unavailable"
    try:
        return float(raw), body, "ok"
    except (TypeError, ValueError):
        return None, body, "unavailable"


async def _fetch_tile(client: httpx.AsyncClient, auth: str, spec: dict) -> dict:
    """Call one report endpoint in-process and reduce it to a tile."""
    base = {
        "key": spec["key"],
        "title": spec["title"],
        "category": spec["category"],
        "label": spec["label"],
        "unit": spec["unit"],
        "desc": spec.get("desc"),
        "deeplink": spec.get("deeplink", f"/reports/{spec['key']}"),
        "value": None,
        "baseline": None,
        "delta_abs": None,
        "delta_pct": None,
        "status": "unavailable",
        "as_of": None,
    }
    scale = float(spec.get("scale", 1))
    value, body, hint = await _fetch_one(
        client, auth, spec["endpoint"], spec.get("params"), spec["value_path"],
    )
    if hint == "locked":
        return {**base, "status": "locked"}
    if value is None or body is None:
        return base
    value *= scale

    rule = spec["compare"]

    # Month-over-month delta: the hero number IS (this period − baseline
    # period), green when up. Fetches a second endpoint for the baseline so
    # no underlying router needs to expose a MoM number itself.
    if rule["type"] == "mom_delta":
        bval, _bbody, _bhint = await _fetch_one(
            client, auth, spec["baseline_endpoint"],
            spec.get("baseline_params"), spec["baseline_value_path"],
        )
        if bval is None:
            # Baseline unavailable — show this period's value, no verdict.
            return {**base, "value": value, "status": "neutral",
                    "as_of": _extract_as_of(body)}
        bval *= scale
        delta_abs = value - bval
        delta_pct = ((value / bval - 1.0) * 100.0) if bval else None
        return {
            **base,
            "value": delta_abs,
            "baseline": bval,
            "delta_abs": delta_abs,
            "delta_pct": _clamp_delta(delta_pct),
            "status": "good" if delta_abs >= 0 else "bad",
            "as_of": _extract_as_of(body),
        }

    status, baseline, delta_abs, delta_pct = _evaluate(rule, value, body)
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
        "desc": spec.get("desc", spec.get("note")),
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

    # ⚠ Tiles whose endpoint now accepts a BORROWED report key (SPEC-CODE-RULES
    # §52) can no longer self-gate on a 403 — the call succeeds, but the borrowed
    # caller is scope-pinned, so the number is a SUBSET under a company-wide
    # label. `ops-customer-score/pu/overview` is pinned to DFW for a DFW-KAM /
    # Sales holder, who would otherwise read "Pickup On-Time % (MTD)" as the
    # whole company. Re-gate those tiles on GENUINE access, restoring exactly the
    # locked tile they saw before the widening.
    if "admin" not in roles:
        pool = get_pool(request)
        for _tile_key in _BORROWED_ENDPOINT_TILES:
            allowed = await get_allowed_roles_for_report(pool, _tile_key)
            if not (roles & allowed):
                tiles = [
                    {**x, "status": "locked", "value": None} if x["key"] == _tile_key else x
                    for x in tiles
                ]

    # Link-tiles are "open to explore" cards with a live deep-link but no KPI
    # query, so — unlike the self-gating KPI TILES (which render a locked tile on
    # a 403 from their endpoint) — they were previously emitted to every cockpit
    # user regardless of report access. That advertised sensitive reports (e.g.
    # Bonus Calculator: CEO + HR Manager + OPs Manager only) and a working
    # deep-link to unauthorized cockpit users. Gate each link-tile by the
    # caller's actual access: admin bypasses; everyone else must share a granting
    # TagRole (same rule as require_report_access). The cache is keyed by role
    # set, so per-role filtering is cache-safe.
    if "admin" in roles:
        visible_links = list(LINK_TILES)
    else:
        pool = get_pool(request)
        link_allowed = await asyncio.gather(
            *[get_allowed_roles_for_report(pool, t["key"]) for t in LINK_TILES]
        )
        visible_links = [
            t for t, allowed in zip(LINK_TILES, link_allowed) if roles & allowed
        ]

    payload = {
        "generated_at": cst_now().isoformat(),
        "category_order": _CATEGORY_ORDER,
        "tiles": list(tiles),
        "link_tiles": [_link_tile(t) for t in visible_links],
    }
    _CACHE[roles] = (now + _CACHE_TTL, payload)
    return {"success": True, "data": payload, "meta": {"cached": False}}
