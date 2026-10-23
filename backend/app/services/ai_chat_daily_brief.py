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

Divisions (2026-10-23): for a user who can open the DIVISION reports, one row each for
CORP (`ops-portal-overview`, the non-clone CORP scope TEAM1..TEAM5) and DFW
(`ops-managers-portal-dfw`), read from the same sections as a team, plus TOTAL (= CORP
+ DFW, only when both are open). Same fields as a team row; what a division report does
not provide (DFW has no budget) is null. TOTAL's additive fields are server-side sums,
its ratios are re-derived from those sums with the reports' own formulas, and its
on-time % is the Customer Score report's own all-division value (a % is not additive).
A division the user cannot open is simply absent — never "not shown" noise.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from typing import Any

from app.clock import cst_today

logger = logging.getLogger(__name__)

# There is no TEAM5 clone (corp-t5-ops-kam-portal / ops-portal-overview-t5 do not exist;
# `ops_portal_overview_team.TEAM_CONFIGS` stops at TEAM4) — TEAM5 is inside CORP's row.
TEAM_NUMBERS = (1, 2, 3, 4)
# The 4-team payload measured ~6.1k chars in tests, the CEO's (4 teams + 3 divisions)
# ~9k; real customer names and feed stamps add more. The generic 6000 cap would cut
# it. Applies to this tool only.
DAILY_BRIEF_MAX_CHARS = 24000
TOP_LOSSES = 5
# 11 GETs per team (44) + 7 CORP + 5 DFW + 9 division Customer Score = 65 for the CEO,
# all in ONE gather behind this bound on the gold datalake.
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

# DFW exposes no /team-variance at all, and its /profit-tm-gauge answers 0.0 % of a 0
# budget (DFW_SCOPE.has_budget=False) — a fabricated number, so neither is read.
BUDGET_SECTIONS = ("profit-tm-gauge", "team-variance")
DFW_SECTIONS: dict[str, dict[str, Any]] = {
    k: v for k, v in PORTAL_SECTIONS.items() if k not in BUDGET_SECTIONS
}


@dataclass(frozen=True)
class Division:
    label: str            # the row's "team" value
    report_key: str       # catalog gate
    prefix: str           # the division report's OWN endpoints (not a clone)
    sections: Mapping[str, dict[str, Any]]
    score_division: str   # ops-customer-score `division` param


DIVISIONS: tuple[Division, ...] = (
    Division("CORP", "ops-portal-overview", "/api/custom/ops-portal-overview",
             PORTAL_SECTIONS, "CORP"),
    Division("DFW", "ops-managers-portal-dfw", "/api/custom/ops-portal-overview-dfw",
             DFW_SECTIONS, "DFW"),
)
TOTAL = "TOTAL"
DIVISION_SCORE_KEY = "ops-customer-score"
DIVISION_SCORE_PREFIX = "/api/custom/ops-customer-score"

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


def _division_score_sections(division: str | None) -> dict[str, dict[str, Any]]:
    """Customer Score pinned sections for one division; ``None`` = all divisions (TOTAL)."""
    params = {"division": division} if division else {}
    return {s: dict(params) for s in SCORE_SECTIONS}


def division_paths() -> list[str]:
    paths = [f"{d.prefix}/{s}" for d in DIVISIONS for s in (*d.sections, PORTAL_FRESHNESS)]
    paths += [f"{DIVISION_SCORE_PREFIX}/{s}" for s in (*SCORE_SECTIONS, SCORE_FRESHNESS)]
    return paths


def division_declared_params() -> list[tuple[str, dict[str, Any]]]:
    out = [(f"{d.prefix}/{s}", p) for d in DIVISIONS for s, p in d.sections.items()]
    out += [(f"{DIVISION_SCORE_PREFIX}/{s}", p)
            for s, p in _division_score_sections("CORP").items()]
    return out


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


def _budget_fields(raw: Mapping[str, Any]) -> dict[str, Any]:
    """% of budget / budget only where the report HAS a budget: a section not read
    (DFW) or a non-positive budget (the gauge answers 0.0 % of 0) is null, not 0."""
    gauge = raw.get("profit-tm-gauge")
    budget = _num((gauge or {}).get("profit_budget"))
    if not gauge or budget is None or budget <= 0:
        return {"pct_of_budget": None, "profit_budget_mtd": None}
    return {"pct_of_budget": _num(gauge.get("pct_of_budget")), "profit_budget_mtd": budget}


def _variance(raw: Mapping[str, Any]) -> dict[str, Any] | None:
    if "team-variance" not in raw:
        return None
    var = raw.get("team-variance") or {}
    return {
        "window": var.get("window"),
        "volume_var": _num(var.get("volume_var")),
        "revenue_var": _num(var.get("revenue_var")),
        "profit_var": _num(var.get("profit_var")),
        "margin_var_pct": _num(var.get("margin_var_pct")),
    }


def build_team_snapshot(n: int, raw: Mapping[str, Any], score: Mapping[str, Any] | None) -> dict[str, Any]:
    """One team's compact snapshot from the endpoints' `data` payloads (keyed by section)."""
    return build_snapshot(f"TEAM{n}", portal_key(n), raw, score)


def build_snapshot(label: str, report_key: str, raw: Mapping[str, Any],
                   score: Mapping[str, Any] | None) -> dict[str, Any]:
    """A team's or a division's snapshot — the same fields either way."""
    proj = raw.get("team-projection") or {}
    perf = raw.get("team-performance") or {}
    losses = raw.get("customer-losses") or []
    avg = _num(proj.get("avg_prof_day"))
    return {
        "team": label,
        "report_key": report_key,
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
        **_budget_fields(raw),
        **_today_fields(raw.get("combo"), raw.get("cover-forecast"), avg),
        "variance_vs_budget": _variance(raw),
        "top_losses": [
            {"customer": r.get("customer_name"), "loss_loads": r.get("loss_loads"),
             "loss_profit": _num(r.get("loss_profit"))}
            for r in losses[:TOP_LOSSES] if isinstance(r, dict)
        ],
        "service": _service(score),
        "freshness": _freshness(raw.get(PORTAL_FRESHNESS),
                                (score or {}).get(SCORE_FRESHNESS) if score else None),
    }


def _add(a: Any, b: Any) -> Any:
    """CORP + DFW for one additive field; unknown on either side ⇒ unknown (null)."""
    if isinstance(a, bool) or isinstance(b, bool):
        return None
    if isinstance(a, int) and isinstance(b, int):
        return a + b
    if isinstance(a, int | float) and isinstance(b, int | float):
        return round(float(a) + float(b), 2)
    return None


def _ratio_pct(num: float | None, den: float | None) -> float | None:
    """The reports' own margin formula (profit / revenue × 100), null without revenue."""
    if num is None or den is None or den <= 0:
        return None
    return round(num / den * 100.0, 2)


def _same(a: Any, b: Any) -> Any:
    return a if a == b else None


_MTD_ADDITIVE = ("volume", "revenue", "profit", "loss_loads", "profit_loss")


def build_total_snapshot(corp: Mapping[str, Any], dfw: Mapping[str, Any],
                         score: Mapping[str, Any] | None) -> dict[str, Any]:
    """TOTAL = CORP + DFW (disjoint team_id scopes, so the sum IS the company).

    Additive fields are summed; gap and margins are re-derived from the sums (never a
    sum of gaps or of percentages); % of budget is null because DFW has no budget (a
    company % would silently be CORP's); on-time % is the score report's ALL value.
    """
    c_mtd, d_mtd = corp.get("mtd") or {}, dfw.get("mtd") or {}
    mtd: dict[str, Any] = {"window": _same(c_mtd.get("window"), d_mtd.get("window"))}
    for key in _MTD_ADDITIVE:
        mtd[key] = _add(c_mtd.get(key), d_mtd.get(key))
    mtd["margin_pct"] = _ratio_pct(mtd["profit"], mtd["revenue"])
    mtd = {k: mtd[k] for k in ("window", "volume", "revenue", "profit", "margin_pct",
                               "loss_loads", "profit_loss")}

    def add(key: str) -> Any:
        return _add(corp.get(key), dfw.get(key))

    avg, with_fc = add("avg_prof_day"), add("today_profit_with_forecast")
    gap, pct = gap_vs_avg(with_fc, avg)
    proj_profit, proj_revenue = add("proj_profit"), add("proj_revenue")
    return {
        "team": TOTAL,
        "report_keys": [corp.get("report_key"), dfw.get("report_key")],
        "mtd": mtd,
        "avg_prof_day": avg,
        "proj_profit": proj_profit,
        "proj_revenue": proj_revenue,
        "proj_margin_pct": _ratio_pct(proj_profit, proj_revenue),
        "pending_workdays": _same(corp.get("pending_workdays"), dfw.get("pending_workdays")),
        "pct_of_budget": None,
        "profit_budget_mtd": None,
        "today": _same(corp.get("today"), dfw.get("today")),
        "today_profit": add("today_profit"),
        "today_cover_forecast_profit": add("today_cover_forecast_profit"),
        "today_profit_with_forecast": with_fc,
        "gap_vs_avg_day": gap,
        "gap_pct": pct,
        "variance_vs_budget": None,
        "top_losses": [],
        "service": _service(score),
        "freshness": {},
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
    kind: str = "team"  # "team" | "division"


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


async def _score(get: Getter, sem: asyncio.Semaphore, prefix: str,
                 sections: Mapping[str, dict[str, Any]], label: str) -> dict[str, Any] | None:
    """Customer Score sections: 403 ⇒ None (service null), other failure ⇒ error marker."""
    try:
        return await _fetch_all(get, sem, prefix, sections, SCORE_FRESHNESS)
    except _Denied:
        return None
    except Exception as exc:  # noqa: BLE001
        logger.warning("ai-chat daily_brief %s customer score unavailable: %s", label, exc)
        return {"error": "unavailable"}


async def _unit(label: str, report_key: str, prefix: str, sections: Mapping[str, dict[str, Any]],
                get: Getter, sem: asyncio.Semaphore, score_key_: str | None, score_prefix: str,
                score_sections: Mapping[str, dict[str, Any]], kind: str) -> TeamResult:
    """One team or division: its portal sections, then (if open) its Customer Score."""
    try:
        raw = await _fetch_all(get, sem, prefix, sections, PORTAL_FRESHNESS)
    except _Denied:
        return TeamResult(label, None, {}, reason="no access", kind=kind)
    except Exception as exc:  # noqa: BLE001 - one team must not sink the brief
        logger.warning("ai-chat daily_brief %s unavailable: %s", label, exc)
        return TeamResult(label, {"team": label, "error": "unavailable"}, {}, kind=kind)

    used: dict[str, Any] = {report_key: raw.get(PORTAL_FRESHNESS)}
    score: dict[str, Any] | None = None
    if score_key_:
        score = await _score(get, sem, score_prefix, score_sections, label)
        if score is not None and "error" not in score:
            used[score_key_] = score.get(SCORE_FRESHNESS)
    return TeamResult(label, build_snapshot(label, report_key, raw, score), used, kind=kind)


async def _team(n: int, get: Getter, sem: asyncio.Semaphore, can_score: bool) -> TeamResult:
    return await _unit(f"TEAM{n}", portal_key(n), _portal_prefix(n), PORTAL_SECTIONS, get, sem,
                       score_key(n) if can_score else None, _score_prefix(n), SCORE_SECTIONS,
                       kind="team")


async def _division(d: Division, get: Getter, sem: asyncio.Semaphore, can_score: bool) -> TeamResult:
    return await _unit(d.label, d.report_key, d.prefix, d.sections, get, sem,
                       DIVISION_SCORE_KEY if can_score else None, DIVISION_SCORE_PREFIX,
                       _division_score_sections(d.score_division), kind="division")


def _total(divs: list[TeamResult], score: dict[str, Any] | None) -> TeamResult | None:
    """TOTAL from the two division results; None when either was not shown."""
    if len(divs) != 2 or any(r.snapshot is None for r in divs):
        return None
    corp, dfw = (r.snapshot for r in divs)
    if "error" in corp or "error" in dfw:
        return TeamResult(TOTAL, {"team": TOTAL, "error": "unavailable"}, {}, kind="division")
    used = {}
    if score is not None and "error" not in score:
        used[DIVISION_SCORE_KEY] = score.get(SCORE_FRESHNESS)
    return TeamResult(TOTAL, build_total_snapshot(corp, dfw, score), used, kind="division")


async def collect(get: Getter, accessible: Mapping[str, Any]) -> list[TeamResult]:
    """One TeamResult per CORP team (team order), then one per division the user can
    open (CORP, DFW, TOTAL). Reports not in ``accessible`` are never fetched. Teams,
    divisions and TOTAL's score all run in ONE gather behind ONE semaphore."""
    sem = asyncio.Semaphore(MAX_CONCURRENT_GETS)

    async def one(n: int) -> TeamResult:
        if portal_key(n) not in accessible:
            return TeamResult(f"TEAM{n}", None, {}, reason="no access")
        return await _team(n, get, sem, score_key(n) in accessible)

    async def no_score() -> None:
        return None

    shown = [d for d in DIVISIONS if d.report_key in accessible]
    can_div_score = DIVISION_SCORE_KEY in accessible
    total_score = (_score(get, sem, DIVISION_SCORE_PREFIX, _division_score_sections(None), TOTAL)
                   if len(shown) == len(DIVISIONS) and can_div_score else no_score())
    *units, score = await asyncio.gather(
        *[one(n) for n in TEAM_NUMBERS],
        *[_division(d, get, sem, can_div_score) for d in shown],
        total_score,
    )
    teams, divs = units[:len(TEAM_NUMBERS)], units[len(TEAM_NUMBERS):]
    total = _total(divs, score)
    return [*teams, *divs, *([total] if total else [])]


def payload_of(results: list[TeamResult]) -> dict[str, Any]:
    teams = [r for r in results if r.kind == "team"]
    # A division the user cannot open is ABSENT: no row, no "not shown" line.
    divisions = [r.snapshot for r in results if r.kind == "division" and r.snapshot is not None]
    payload: dict[str, Any] = {
        "today": cst_today().isoformat(),
        "glossary": GLOSSARY,
        "teams": [r.snapshot for r in teams if r.snapshot is not None],
        "teams_not_shown": [{"team": r.team, "reason": r.reason}
                            for r in teams if r.snapshot is None],
    }
    if divisions:
        payload["divisions"] = divisions
    return payload


def _board_row(snap: Mapping[str, Any]) -> dict[str, Any]:
    mtd = snap.get("mtd") or {}
    service = snap.get("service") if isinstance(snap.get("service"), dict) else {}
    return {
        "team": snap.get("team"),
        "today_profit_with_forecast": snap.get("today_profit_with_forecast"),
        "avg_prof_day": snap.get("avg_prof_day"),
        "gap_vs_avg_day": snap.get("gap_vs_avg_day"),
        "gap_pct": snap.get("gap_pct"),
        "pct_of_budget": snap.get("pct_of_budget"),
        "proj_profit": snap.get("proj_profit"),
        "proj_margin_pct": snap.get("proj_margin_pct"),
        "loss_loads": mtd.get("loss_loads"),
        "profit_loss": mtd.get("profit_loss"),
        "pickup_on_time_pct": ((service or {}).get("pickup") or {}).get("on_time_pct"),
        "delivery_on_time_pct": ((service or {}).get("delivery") or {}).get("on_time_pct"),
    }


def _rows(snaps: list[Mapping[str, Any]]) -> tuple[list[dict[str, Any]], list[Any]]:
    rows, unavailable = [], []
    for snap in snaps:
        if "error" in snap:
            unavailable.append(snap.get("team"))
        else:
            rows.append(_board_row(snap))
    return rows, unavailable


def scoreboard_of(payload: Mapping[str, Any]) -> dict[str, Any]:
    """The Teams card's at-a-glance table: a PROJECTION of the snapshot, never a new number.

    One row per team with numbers; teams that failed and teams the user cannot open are
    listed by name only (contract §5). ``divisions`` (CORP / DFW / TOTAL) have exactly
    the team rows' fields; a division the user cannot open is not listed at all.
    """
    rows, unavailable = _rows(payload.get("teams") or [])
    div_rows, div_unavailable = _rows(payload.get("divisions") or [])
    return {
        "today": payload.get("today"),
        "teams": rows,
        "unavailable": unavailable,
        "not_shown": [t.get("team") for t in payload.get("teams_not_shown") or []],
        "divisions": div_rows,
        "divisions_unavailable": div_unavailable,
    }
