"""Attrition WoW — weekly "Atrition WOW -Week N" e-mail digest (data layer).

Pulled by an external n8n workflow (Mondays 08:15 CST) through
``GET /api/custom/attrition-wow/digest-email`` — see
``app/routers/attrition_wow_digest.py``. Rendering lives in
``attrition_wow_digest_html.py``.

Every number is read back from the report's OWN endpoints, in process via
``httpx.ASGITransport`` (the ``team_perf_digest`` pattern), so the e-mail is the
page — the windows, the population, the /8 and the attrition sign all stay in
``attrition_wow.py`` / ``attrition_core.py`` (§95: one definition).

  /summary  × 3 scopes (UNILINK / CORP / DFW) → cards + metric table + prose
  /pivot?dim=customer&metric=loads × 2 (CORP, DFW) → the customer lists
  /freshness → newest departure, so n8n can refuse a frozen feed

Customer lists — the page computes these in the BROWSER (``PivotsTab.tsx``), so
the arithmetic is ported here and pinned by tests against the request's PDF
(week Sep 28 – Oct 4 2026, reproduced 9/9 CORP + 4/4 DFW below-average rows,
5/5 inactive, 6/6 reactivated against live data):

  values[0]  = last completed week (LW), values[1] = the week before, …
  ref        = mean(values[1..8]), a missing week counts as 0 (fixed /8)
  diff       = values[0] − ref           ("Difference LW – L8W")
  diff2w     = values[0] − values[1]     ("Difference LW – L2W", ONE week)

  below average  LW > 0 AND diff rounds to ≤ −1  (customers at 0 in LW are the
                 inactive list's business, not this one — the PDF omits BALL)
  inactive       paying loads the week before LW, NONE in LW   (week-over-week)
  reactivated    NO paying loads the week before LW, some in LW (week-over-week)

  (Decision 2026-10-05: week-over-week, because it reproduces the PDF exactly;
  an "any load in the 8 weeks" basis listed 21 CORP names vs the PDF's 5.)
"""
from __future__ import annotations

import asyncio
import logging
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal
from typing import Any, Optional

import httpx

from app.clock import cst_now
from app.config import settings

logger = logging.getLogger(__name__)

API_PREFIX = "/api/custom/attrition-wow"
REPORT_URL = "https://space.unilinkportal.com/reports/attrition-wow"

# Scope → the `teams` query the PAGE sends (AttritionWowContent.tsx). UNILINK
# sends no `teams` at all, which the backend resolves to ALL_TEAMS. CORP is the
# page's five teams (TEAM5 is dormant but in scope there, so it is here).
SCOPES: tuple[tuple[str, Optional[str]], ...] = (
    ("UNILINK", None),
    ("CORP", "TEAM1,TEAM2,TEAM3,TEAM4,TEAM5"),
    ("DFW", "TEAM-DFW"),
)
LIST_SCOPES = ("CORP", "DFW")

PIVOT_WEEKS = 12    # what the page requests (PivotsTab `useState(12)`)
SHOWN_WEEKS = 9     # LW + the 8 baseline weeks, as in the PDF
BASELINE_WEEKS = 8


class DigestSourceError(RuntimeError):
    """A report endpoint failed — never render a partial e-mail."""


class DigestStaleError(DigestSourceError):
    """The datalake has not loaded all of last week — never report on it."""


# One build at a time: each runs 6 datalake reads, and an n8n retry overlapping
# a slow first attempt (or an admin preview) would otherwise double the load on
# the shared max_size=8 pool. A waiter just gets the next fresh build.
_BUILD_LOCK = asyncio.Lock()


def assert_fresh(data_as_of: Optional[str], lw_end: date) -> None:
    """Newest departure must reach LW's Saturday, or the e-mail is a lie.

    A v4 feed that stalled on Thursday renders a low LW, an inflated inactive
    list and a long below-average list — indistinguishable from real attrition.
    ``None`` (no rows at all) is stale too.
    """
    if data_as_of is None or date.fromisoformat(data_as_of) < lw_end - timedelta(days=1):
        raise DigestStaleError(
            f"newest load departure {data_as_of} is before last week ended {lw_end}"
        )


# ---------------------------------------------------------------------------
# Rounding — the page uses Intl.NumberFormat (halfExpand = away from zero);
# Python's round() is banker's rounding, which would print -0 for -0.5.
# ---------------------------------------------------------------------------


def round_half_away(v: float, places: int = 0) -> float:
    q = Decimal(1).scaleb(-places)
    # `+ 0.0` turns -0.0 into 0.0, so a value that rounds to zero never prints "-0".
    return float(Decimal(str(v)).quantize(q, rounding=ROUND_HALF_UP)) + 0.0


# ---------------------------------------------------------------------------
# In-process reads (team_perf_digest pattern)
# ---------------------------------------------------------------------------


def _internal_headers() -> dict[str, str]:
    # Admin bypasses require_report_access (deps.py) → the same SQL users hit.
    auth = (
        'Bearer {"sub":"attrition-digest","email":"attrition-digest@internal",'
        '"name":"attrition-digest","roles":["admin"]}'
    )
    headers = {"authorization": auth}
    if settings.PROXY_SHARED_SECRET:
        headers["x-proxy-secret"] = settings.PROXY_SHARED_SECRET
    return headers


async def _get_many(app, calls: list[tuple[str, dict]]) -> list[dict]:
    """GET report endpoints concurrently, in process. Any failure RAISES.

    Callers keep each batch ≤ 3: the datalake gold pool is max_size=8 and is
    shared with live users (§43 pool starvation).
    """
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    async with httpx.AsyncClient(
        transport=transport, base_url="http://attrition-digest.internal",
        timeout=90.0,
    ) as client:
        results = await asyncio.gather(
            *[client.get(f"{API_PREFIX}{path}", params=params,
                         headers=_internal_headers())
              for path, params in calls],
            return_exceptions=True,
        )
    out: list[dict] = []
    for (path, params), res in zip(calls, results):
        if isinstance(res, BaseException):
            raise DigestSourceError(f"{path} {params} raised {res!r}")
        if res.status_code != 200:
            raise DigestSourceError(f"{path} {params} returned {res.status_code}")
        payload = res.json()
        if not payload.get("success"):
            raise DigestSourceError(f"{path} {params} returned success=false")
        out.append(payload)
    return out


def _scope_params(teams: Optional[str]) -> dict:
    return {"teams": teams} if teams else {}


# ---------------------------------------------------------------------------
# Customer lists (port of PivotsTab.tsx)
# ---------------------------------------------------------------------------


def week_list(lw_monday: date, n: int = PIVOT_WEEKS) -> list[date]:
    """Latest-first Mondays, index 0 = LW (the page's ``weeksList``)."""
    return [lw_monday - timedelta(weeks=i) for i in range(n)]


def customer_rows(pivot: list[dict], lw_monday: date) -> list[dict]:
    """Wide rows from /pivot's long form, with ref / diff / diff2w."""
    weeks = week_list(lw_monday)
    by_key: dict[str, dict] = {}
    for r in pivot:
        key = r.get("dim_key")
        if not key:
            continue
        b = by_key.setdefault(key, {"team": r.get("team"), "by_week": {}})
        b["by_week"][r["week_start"]] = r.get("value")
        if r.get("team") and not b["team"]:
            b["team"] = r["team"]

    rows = []
    for key, b in by_key.items():
        values = [b["by_week"].get(w.isoformat()) for w in weeks]
        baseline = values[1:1 + BASELINE_WEEKS]
        ref = sum((v or 0) for v in baseline) / len(baseline)
        lw, prev = values[0], values[1]
        rows.append({
            "team": b["team"],
            "customer": key,
            "values": values[:SHOWN_WEEKS],
            "ref": ref,
            "diff": None if lw is None else lw - ref,
            "diff2w": None if lw is None or prev is None else lw - prev,
            "lw": lw or 0,
            "prev": prev or 0,
        })
    return rows


def below_average(rows: list[dict]) -> list[dict]:
    """Shipped last week, but at least one load (rounded) under the 8-wk avg."""
    out = [
        r for r in rows
        if r["lw"] > 0 and r["diff"] is not None
        and round_half_away(r["diff"]) <= -1
    ]
    return sorted(out, key=lambda r: (r["diff"], r["customer"]))


def inactive(rows: list[dict]) -> list[str]:
    return sorted(r["customer"] for r in rows if r["prev"] > 0 and r["lw"] == 0)


def reactivated(rows: list[dict]) -> list[str]:
    return sorted(r["customer"] for r in rows if r["prev"] == 0 and r["lw"] > 0)


# ---------------------------------------------------------------------------
# Highlights prose — deterministic, from /summary only
# ---------------------------------------------------------------------------


def _pct_txt(p: Optional[float]) -> Optional[str]:
    return None if p is None else f"{abs(p) * 100:.2f}%"


def _usd_txt(v: float) -> str:
    r = round_half_away(v)
    return f"-${abs(r):,.0f}" if r < 0 else f"${r:,.0f}"


def _vs_avg(p: float) -> str:
    return "above" if p > 0 else "below" if p < 0 else "in line with"


def _up_down(v: float) -> str:
    return "up" if v > 0 else "down" if v < 0 else "flat"


def previous_week_loads(summary: dict) -> Optional[int]:
    """Week before LW = 2 × L2W avg − LW (L2W = LW + the week before)."""
    loads = summary.get("loads") or {}
    if loads.get("l2w_avg") is None or loads.get("lw") is None:
        return None
    return int(round_half_away(loads["l2w_avg"] * 2 - loads["lw"]))


def highlight(summary: dict) -> str:
    """One paragraph in the request PDF's voice, for one scope."""
    loads = summary["loads"]
    lw = int(loads["lw"] or 0)
    prev = previous_week_loads(summary)
    parts: list[str] = []

    if prev is not None:
        if lw > prev:
            parts.append(f"Loads improved WoW, increasing from {prev:,} to {lw:,}")
        elif lw < prev:
            parts.append(f"Loads declined WoW, decreasing from {prev:,} to {lw:,}")
        else:
            parts.append(f"Loads held flat WoW at {lw:,}")
    else:
        parts.append(f"Loads finished at {lw:,}")
    lp = loads["diff_lw_vs_l8w"]["pct"]
    first = parts[0]
    if lp is not None:
        first += (
            f", {_pct_txt(lp)} {_vs_avg(lp)} the 8-week average"
            if lp else ", in line with the 8-week average"
        )
    sentences = [first + "."]

    clauses: list[str] = []
    rp = summary["revenue"]["diff_lw_vs_l8w"]["pct"]
    if rp is not None:
        clauses.append(
            f"Revenue finished {_pct_txt(rp)} {_vs_avg(rp)} the 8-week average"
        )
    profit = summary["profit"]
    pp = profit["diff_lw_vs_l8w"]["pct"]
    if profit["l8w_avg"] is not None and profit["l8w_avg"] <= 0:
        # A % of a negative base flips sign (a better week reads "below"), so
        # state the dollars instead (§102).
        clauses.append(
            f"Profit was {_usd_txt(profit['lw'])} against an 8-week "
            f"average of {_usd_txt(profit['l8w_avg'])}"
        )
    elif pp is not None:
        clauses.append(f"Profit was {_pct_txt(pp)} {_vs_avg(pp)}")
    md = summary["margin_pct"]["diff_lw_vs_l8w"]["diff"]
    if md is not None:
        md_pp = round_half_away(md * 100, 2)  # the word follows the PRINTED value
        clauses.append(f"Margin was {_up_down(md_pp)} {abs(md_pp):.2f}pp")
    ppl = summary["profit_per_load"]
    pl = ppl["diff_lw_vs_l8w"]["pct"]
    if pl is not None and ppl["lw"] is not None:
        clauses.append(
            f"Profit per load was {_up_down(pl)} {_pct_txt(pl)} at "
            f"{_usd_txt(ppl['lw'])}"
        )
    if clauses:
        body = clauses[0] if len(clauses) == 1 else (
            ", ".join(clauses[:-1]) + ", and " + clauses[-1]
        )
        sentences.append(body + ".")
    return " ".join(sentences)


# ---------------------------------------------------------------------------
# Builder
# ---------------------------------------------------------------------------


def subject_for(lw_monday: date) -> str:
    # Wording and spacing exactly as requested ("Atrition WOW -Week # ").
    return f"Atrition WOW -Week {lw_monday.isocalendar()[1]}"


async def build_attrition_wow_digest(app) -> dict[str, Any]:
    async with _BUILD_LOCK:
        return await _build(app)


async def _build(app) -> dict[str, Any]:
    from app.services.attrition_wow_digest_html import render_html

    summaries = await _get_many(
        app, [("/summary", _scope_params(t)) for _, t in SCOPES]
    )
    scopes = {name: s["data"] for (name, _), s in zip(SCOPES, summaries)}

    windows = scopes["UNILINK"]["windows"]
    for name, data in scopes.items():
        if data["windows"] != windows:  # a midnight straddle between calls
            raise DigestSourceError(f"{name} windows differ from UNILINK's")
    lw_monday = date.fromisoformat(windows["lw"]["start"])

    teams = dict(SCOPES)
    *pivots, fresh = await _get_many(app, [
        *[("/pivot", {"dim": "customer", "metric": "loads",
                      "weeks": PIVOT_WEEKS, **_scope_params(teams[name])})
          for name in LIST_SCOPES],
        # Newest departure in the report's population — assert_fresh() refuses
        # (502) if it is older than LW's Saturday, and the n8n assert node
        # re-checks it: a frozen v4 still answers every query confidently.
        ("/freshness", {}),
    ])
    data_as_of = fresh["data"].get("last_load_date")
    assert_fresh(data_as_of, date.fromisoformat(windows["lw"]["end"]))
    lists: dict[str, dict] = {}
    for name, p in zip(LIST_SCOPES, pivots):
        rows = customer_rows(p["data"], lw_monday)
        lists[name] = {
            "below": below_average(rows),
            "inactive": inactive(rows),
            "reactivated": reactivated(rows),
        }

    highlights = {name: highlight(data) for name, data in scopes.items()}
    generated = cst_now()
    week_no = lw_monday.isocalendar()[1]
    subject = subject_for(lw_monday)
    html = render_html(
        subject=subject,
        week_no=week_no,
        windows=windows,
        scopes=scopes,
        highlights=highlights,
        lists=lists,
        weeks=week_list(lw_monday, SHOWN_WEEKS),
        generated=generated,
        data_as_of=data_as_of,
        report_url=REPORT_URL,
    )
    return {
        "subject": subject,
        "html": html,
        "generatedAt": generated.isoformat(),
        "meta": {
            "week_no": week_no,
            "windows": windows,
            "data_as_of": data_as_of,
            "loads_lw": {n: scopes[n]["loads"]["lw"] for n in scopes},
            "below_average": {n: len(lists[n]["below"]) for n in lists},
            "inactive": {n: len(lists[n]["inactive"]) for n in lists},
            "reactivated": {n: len(lists[n]["reactivated"]) for n in lists},
        },
    }
