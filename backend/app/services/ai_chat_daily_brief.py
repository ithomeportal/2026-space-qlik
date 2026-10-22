"""AI chat — the `daily_brief` tool: one snapshot per CORP team the asker can open.

Contract `/BOT/teams-chat-ai/docs/SPEC-CONTRACTS.md` §5; design `docs/SPEC-AI-CHAT.md` §4c.

"How is the day looking?" needs numbers the generic loop cannot assemble: today's
profit WITH forecast is a frontend composite (Chart.tsx — today's /combo day bucket
`profit` + today's /cover-forecast `cover_prof`), /combo?grain=day is 365 buckets
(today sits past any truncation), and the model must not compute. So this module
reads each team's OWN endpoints in-process — exactly what the KAM portal page reads,
behind exactly its gate — and only *selects* their values. The few figures it adds
(the composite, its gap to `avg_prof_day`) are the chart's own arithmetic, done once
here so the model can quote them.

No business math lives here: projection, budget %, variance, losses and on-time %
are the reports' values verbatim (rounded to cents for size).

Access, per team, two gates (same as get_report_section): the catalog check
(`role_report_access`, admin bypass) BEFORE any call, then the endpoint's own
`require_report_access` — a 403 there omits the team too. An omitted team carries
no number, only its name and "no access".
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from typing import Any

from app.clock import cst_today

logger = logging.getLogger(__name__)

TEAM_NUMBERS = (1, 2, 3, 4)
# The whole 4-team payload measured ~6.1k chars in tests (real customer names and
# four feed stamps add more); the generic 6000 cap would cut the fourth team. Applies to this tool only.
DAILY_BRIEF_MAX_CHARS = 16000
TOP_LOSSES = 5
# 11 GETs per team, 44 for an executive — bound the burst on the gold datalake.
MAX_CONCURRENT_GETS = 8

# section -> query params. Ranges are the endpoints' defaults made explicit.
PORTAL_SECTIONS: dict[str, dict[str, Any]] = {
    "team-projection": {},
    "team-performance": {"range": "mtd"},
    "profit-tm-gauge": {},
    "team-variance": {"range": "mtd"},
    "customer-losses": {"range": "mtd", "limit": TOP_LOSSES},
    "combo": {"grain": "day"},
    "cover-forecast": {"grain": "day"},
}
PORTAL_FRESHNESS = "data-freshness"
SCORE_SECTIONS: dict[str, dict[str, Any]] = {"pu/pinned": {}, "del/pinned": {}}
SCORE_FRESHNESS = "freshness"

GLOSSARY = {
    "avg_prof_day": "AVG per day / Avg. Prof. x Day: average profit per business day over the "
                    "last 12 Mon-Sat business days, closed at yesterday (Team Monthly Projection)",
    "proj_profit": "Projection: month-end projected profit = avg_prof_day x pending_workdays + MTD",
    "today_profit": "profit booked today (today's day bucket of the KPI chart)",
    "today_cover_forecast_profit": "forecast profit of covered open loads scheduled to deliver today",
    "today_profit_with_forecast": "Today's profit with forecast = today_profit + "
                                  "today_cover_forecast_profit (the chart's Forecast bar)",
    "gap_vs_avg_day": "today_profit_with_forecast - avg_prof_day (negative = below a normal day)",
    "gap_pct": "gap_vs_avg_day / avg_prof_day x 100; null when avg_prof_day is not positive",
    "pct_of_budget": "MTD profit as % of the MTD profit budget (Profit-TM gauge)",
    "variance_vs_budget": "MTD actual - budget (positive = over budget)",
    "service": "Customer Score, current month: pickup / delivery on-time % and late loads",
}


def portal_key(n: int) -> str:
    return f"corp-t{n}-ops-kam-portal"


def score_key(n: int) -> str:
    return f"corp-t{n}-customer-score"


def _portal_prefix(n: int) -> str:
    return f"/api/custom/ops-portal-overview-t{n}"


def _score_prefix(n: int) -> str:
    return f"/api/custom/ops-customer-score-t{n}"


def portal_paths(n: int) -> list[str]:
    return [f"{_portal_prefix(n)}/{s}" for s in (*PORTAL_SECTIONS, PORTAL_FRESHNESS)]


def score_paths(n: int) -> list[str]:
    return [f"{_score_prefix(n)}/{s}" for s in (*SCORE_SECTIONS, SCORE_FRESHNESS)]


def declared_params(n: int) -> list[tuple[str, dict[str, Any]]]:
    return [(f"{_portal_prefix(n)}/{s}", p) for s, p in PORTAL_SECTIONS.items()]


# --------------------------------------------------------------------------
# Pure snapshot building
# --------------------------------------------------------------------------


def _num(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    return round(float(value), 2)


def gap_vs_avg(today_with_fc: float | None, avg: float | None) -> tuple[float | None, float | None]:
    """(gap, gap_pct). The pct needs a POSITIVE average: a negative one flips the sign
    (a bad day would read as an improvement), zero divides by nothing."""
    if today_with_fc is None or avg is None:
        return None, None
    gap = round(today_with_fc - avg, 2)
    pct = round(gap / avg * 100.0, 1) if avg > 0 else None
    return gap, pct


def _bucket(payload: Any, day: str, key: str) -> float | None:
    for b in (payload or {}).get("buckets") or []:
        if isinstance(b, dict) and b.get("bucket_start") == day:
            return _num(b.get(key))
    return None


def _today_fields(combo: Any, cover: Any, avg: float | None) -> dict[str, Any]:
    day = (combo or {}).get("today") or cst_today().isoformat()
    profit = _bucket(combo, day, "profit")
    # /cover-forecast only returns buckets that have loads: no bucket = no forecast.
    forecast = _bucket(cover, day, "cover_prof") or 0.0
    with_fc = round(profit + forecast, 2) if profit is not None else None
    gap, pct = gap_vs_avg(with_fc, avg)
    return {
        "today": day,
        "today_profit": profit,
        "today_cover_forecast_profit": forecast,
        "today_profit_with_forecast": with_fc,
        "gap_vs_avg_day": gap,
        "gap_pct": pct,
    }


def _service(score: Mapping[str, Any] | None) -> dict[str, Any] | None:
    if score is None:
        return None
    if "error" in score:
        return {"error": score["error"]}

    def side(payload: Any) -> dict[str, Any]:
        kpi = (payload or {}).get("kpi_month") or {}
        return {"on_time_pct": _num(kpi.get("pct_on_time")), "late": kpi.get("fail"),
                "orders": kpi.get("orders")}

    return {"window": "current month", "pickup": side(score.get("pu/pinned")),
            "delivery": side(score.get("del/pinned"))}


def _freshness(portal_fresh: Any, score_fresh: Any) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for src in (portal_fresh or {}).get("sources") or []:
        if isinstance(src, dict) and src.get("label"):
            out[src["label"]] = src.get("updated_at")
    if isinstance(score_fresh, dict) and "last_updated" in score_fresh:
        out["Customer Score"] = score_fresh.get("last_updated")
    return out


def build_team_snapshot(n: int, raw: Mapping[str, Any], score: Mapping[str, Any] | None) -> dict[str, Any]:
    """One team's compact snapshot from the endpoints' `data` payloads (keyed by section)."""
    proj = raw.get("team-projection") or {}
    perf = raw.get("team-performance") or {}
    gauge = raw.get("profit-tm-gauge") or {}
    var = raw.get("team-variance") or {}
    losses = raw.get("customer-losses") or []
    avg = _num(proj.get("avg_prof_day"))
    return {
        "team": f"TEAM{n}",
        "report_key": portal_key(n),
        "mtd": {
            "window": perf.get("window"),
            "volume": perf.get("volume"),
            "revenue": _num(perf.get("revenue")),
            "profit": _num(perf.get("profit")),
            "margin_pct": _num(perf.get("margin_pct")),
            "loss_loads": perf.get("loss_loads"),
            "profit_loss": _num(perf.get("profit_loss")),
        },
        "avg_prof_day": avg,
        "proj_profit": _num(proj.get("proj_profit")),
        "proj_revenue": _num(proj.get("proj_revenue")),
        "proj_margin_pct": _num(proj.get("proj_margin_pct")),
        "pending_workdays": proj.get("pending_workdays"),
        "pct_of_budget": _num(gauge.get("pct_of_budget")),
        "profit_budget_mtd": _num(gauge.get("profit_budget")),
        **_today_fields(raw.get("combo"), raw.get("cover-forecast"), avg),
        "variance_vs_budget": {
            "window": var.get("window"),
            "volume_var": _num(var.get("volume_var")),
            "revenue_var": _num(var.get("revenue_var")),
            "profit_var": _num(var.get("profit_var")),
            "margin_var_pct": _num(var.get("margin_var_pct")),
        },
        "top_losses": [
            {"customer": r.get("customer_name"), "loss_loads": r.get("loss_loads"),
             "loss_profit": _num(r.get("loss_profit"))}
            for r in losses[:TOP_LOSSES] if isinstance(r, dict)
        ],
        "service": _service(score),
        "freshness": _freshness(raw.get(PORTAL_FRESHNESS),
                                (score or {}).get(SCORE_FRESHNESS) if score else None),
    }


# --------------------------------------------------------------------------
# Fetching (in-process GETs supplied by the ToolSession)
# --------------------------------------------------------------------------

Getter = Callable[[str, dict | None], Awaitable[Any]]


class _Denied(Exception):
    """The report's own gate answered 403."""


class _Failed(Exception):
    """Any other non-200 / unreadable body."""


@dataclass
class TeamResult:
    """What one team contributed: its snapshot (or None = omitted) and the reports used."""

    team: str
    snapshot: dict[str, Any] | None
    used: dict[str, Any]  # report key -> its raw freshness payload (or None)
    reason: str | None = None


async def _fetch(get: Getter, sem: asyncio.Semaphore, path: str, params: dict | None) -> Any:
    async with sem:
        resp = await get(path, params or None)
    if resp.status_code == 403:
        raise _Denied(path)
    if resp.status_code != 200:
        raise _Failed(f"{path} HTTP {resp.status_code}")
    body = resp.json()
    if not isinstance(body, dict):
        raise _Failed(f"{path} body")
    return body.get("data")


async def _fetch_all(get: Getter, sem: asyncio.Semaphore, prefix: str,
                     sections: Mapping[str, dict[str, Any]], freshness: str) -> dict[str, Any]:
    """Every section, concurrently. A 403 anywhere wins; freshness may fail alone."""
    names = [*sections, freshness]
    results = await asyncio.gather(
        *[_fetch(get, sem, f"{prefix}/{s}", sections.get(s)) for s in names],
        return_exceptions=True,
    )
    by_name = dict(zip(names, results, strict=True))
    errors = [r for r in results if isinstance(r, BaseException)]
    if any(isinstance(e, _Denied) for e in errors):
        raise _Denied(prefix)
    for name, value in by_name.items():
        if isinstance(value, BaseException) and name != freshness:
            raise _Failed(f"{prefix}/{name}") from value
    if isinstance(by_name[freshness], BaseException):
        by_name[freshness] = None
    return by_name


async def _team(n: int, get: Getter, sem: asyncio.Semaphore, can_score: bool) -> TeamResult:
    team = f"TEAM{n}"
    try:
        raw = await _fetch_all(get, sem, _portal_prefix(n), PORTAL_SECTIONS, PORTAL_FRESHNESS)
    except _Denied:
        return TeamResult(team, None, {}, reason="no access")
    except Exception as exc:  # noqa: BLE001 - one team must not sink the brief
        logger.warning("ai-chat daily_brief %s unavailable: %s", team, exc)
        return TeamResult(team, {"team": team, "error": "unavailable"}, {})

    used: dict[str, Any] = {portal_key(n): raw.get(PORTAL_FRESHNESS)}
    score: dict[str, Any] | None = None
    if can_score:
        try:
            score = await _fetch_all(get, sem, _score_prefix(n), SCORE_SECTIONS, SCORE_FRESHNESS)
            used[score_key(n)] = score.get(SCORE_FRESHNESS)
        except _Denied:
            score = None
        except Exception as exc:  # noqa: BLE001
            logger.warning("ai-chat daily_brief %s customer score unavailable: %s", team, exc)
            score = {"error": "unavailable"}
    return TeamResult(team, build_team_snapshot(n, raw, score), used)


async def collect(get: Getter, accessible: Mapping[str, Any]) -> list[TeamResult]:
    """One TeamResult per CORP team, in team order. Teams not in ``accessible`` are
    never fetched."""
    sem = asyncio.Semaphore(MAX_CONCURRENT_GETS)

    async def one(n: int) -> TeamResult:
        if portal_key(n) not in accessible:
            return TeamResult(f"TEAM{n}", None, {}, reason="no access")
        return await _team(n, get, sem, score_key(n) in accessible)

    return list(await asyncio.gather(*[one(n) for n in TEAM_NUMBERS]))


def payload_of(results: list[TeamResult]) -> dict[str, Any]:
    return {
        "today": cst_today().isoformat(),
        "glossary": GLOSSARY,
        "teams": [r.snapshot for r in results if r.snapshot is not None],
        "teams_not_shown": [{"team": r.team, "reason": r.reason}
                            for r in results if r.snapshot is None],
    }
