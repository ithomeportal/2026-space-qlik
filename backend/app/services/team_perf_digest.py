"""Ops Portal Overview — "Performance for Team N" email digest (data layer).

One digest per CORP team (TEAM1..TEAM4). Unlike ``ops_team_digest`` (which
sends through MS Graph on a schedule) this one is *pulled* by an external n8n
workflow, so the deliverable is a GET endpoint returning
``{"success":true,"data":{subject, html, generatedAt, meta}}`` —
see ``app/routers/ops_team_perf_digest.py``.

Every displayed metric is read back from the exact endpoints the UI uses, in
process via ``httpx.ASGITransport`` with a synthetic admin bearer (admin
bypasses ``require_report_access``) + the proxy secret — the same pattern
``ops_team_digest._fetch_team_data`` uses. That is how we guarantee the email
matches the report.

Two things the UI has no endpoint for are computed here with DIRECT SQL,
reusing ``_v4_scope_where`` / ``CUSTOMER_TEAM_CTE`` so the predicates are
byte-identical to the report's:

  1. the 14-day daily series behind the two charts (``/combo`` is a live UI
     endpoint on a month grain — deliberately not modified);
  2. the YTD profit-budget achievement %.

Correctness rules honoured here (SPEC-CODE-RULES + CLAUDE.md):
  - §39  Profit = ``SUM(margin_amt)`` over ALL rows — never filtered by
         ``total_charge <> 0``. Only the loads COUNT carries that filter.
  - §1/§43  ``origin_actual_departure`` is bounded half-open with the raw
         column (no ``::date`` cast in WHERE) so ``idx_v4_dep`` is used.
  - §2   Every boundary comes from ``cst_today()``.
  - Never compare a partial period against a full one: the last-month window
    is clamped to the SAME number of elapsed days as the current MTD window,
    derived from the resolved MTD window (not from ``today.day``).
  - Rates (margin / OTP / OTD / budget achievement) are recomputed from their
    components and their deltas are percentage POINTS.
  - Every division guards its denominator and returns ``None`` → rendered as
    an em dash, never ``0``.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import date, timedelta
from typing import Any, Optional

import httpx

from app.clock import cst_now, cst_today
from app.config import settings
from app.routers.ops_portal_overview import (
    CORP_TEAMS,
    CUSTOMER_TEAM_CTE,
    YEAR_START,
    _resolve_range,
    _month_bounds,
    _safe_float,
    _team_list,
    _v4_scope_where,
)
from app.services.team_perf_digest_html import (
    CUSTOMER_PANEL_BASIS,
    CUSTOMER_PANEL_FETCH,
    CUSTOMER_PANEL_LIMIT,
    CUSTOMER_PANEL_SORT,
    render_html,
)

logger = logging.getLogger(__name__)

API_PREFIX = "/api/custom/ops-portal-overview"

# The scope of the PERFORMANCE CORP digest (request PDF, 2026-08-17):
#   team_id IN ('TEAM1','TEAM2','TEAM3','TEAM4')
#
# ⚠ Deliberately NOT `CORP_TEAMS`, which is FIVE teams — it also carries
# TEAM5. TEAM5 is dormant (last load 2026-04-30; 83 loads and $300 margin in
# 2026 against $4.2M for TEAM1-4), so the two are numerically indistinguishable
# today and a reader would never catch the substitution. The request names four
# teams, so four is what this sends — and if TEAM5 ever revives, this stays
# right instead of silently widening.
DIGEST_CORP_TEAMS = ("TEAM1", "TEAM2", "TEAM3", "TEAM4")

# Chart / series window: today-14 .. today-1 (14 calendar days, zero-filled).
SERIES_DAYS = 14
# "Last 6 days" pill window: today-6 .. today-1.
WEEK_DAYS = 6


# ---------------------------------------------------------------------------
# Small numeric guards — every ratio in this module goes through one of these.
# ---------------------------------------------------------------------------


def _ratio(num: float, den: float) -> Optional[float]:
    """num/den, or ``None`` when the denominator is zero/absent (→ em dash)."""
    if not den:
        return None
    out = num / den
    if out != out or out in (float("inf"), float("-inf")):
        return None
    return out


def _pct_change(current: float, base: float) -> Optional[float]:
    """Percent change vs a baseline. ``None`` when the baseline is zero.

    ``abs(base)`` so a negative baseline still yields the intuitive sign.
    """
    if not base:
        return None
    return (current - base) / abs(base) * 100.0


def _pp_delta(current_rate: Optional[float], base_rate: Optional[float]) -> Optional[float]:
    """Difference between two RATES, in percentage points."""
    if current_rate is None or base_rate is None:
        return None
    return current_rate - base_rate


def _achievement_pct(actual: float, budget: float) -> Optional[float]:
    """actual / budget as a percentage — recomputed from components."""
    r = _ratio(actual, budget)
    return None if r is None else r * 100.0


# ---------------------------------------------------------------------------
# In-process endpoint reads (ASGITransport) — identical pattern to
# ops_team_digest._fetch_team_data.
# ---------------------------------------------------------------------------


def _internal_headers() -> dict[str, str]:
    # Admin bypasses require_report_access (deps.py) → runs the same SQL users hit.
    auth = (
        'Bearer {"sub":"team-digest","email":"team-digest@internal",'
        '"name":"team-digest","roles":["admin"]}'
    )
    # In-process via ASGITransport, but require_user cannot tell that apart from
    # a network call — so internal callers must carry the proxy secret too.
    headers = {"authorization": auth}
    if settings.PROXY_SHARED_SECRET:
        headers["x-proxy-secret"] = settings.PROXY_SHARED_SECRET
    return headers


async def _get_many(app, calls: list[tuple[str, dict]]) -> list[Optional[dict]]:
    """GET several ops-portal-overview endpoints concurrently, in process.

    Batched by the caller: the shared datalake pool is max_size=8 and
    /team-performance alone fans out 4 queries, so we never launch more than a
    handful at a time (§43 pool-starvation lesson).
    """
    headers = _internal_headers()
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    async with httpx.AsyncClient(
        transport=transport, base_url="http://team-digest.internal", timeout=90.0,
    ) as client:
        results = await asyncio.gather(
            *[client.get(f"{API_PREFIX}{path}", params=params, headers=headers)
              for path, params in calls],
            return_exceptions=True,
        )
    out: list[Optional[dict]] = []
    for (path, _params), res in zip(calls, results):
        if isinstance(res, BaseException):
            logger.warning("team digest: %s raised %s", path, res)
            out.append(None)
            continue
        if res.status_code != 200:
            logger.warning("team digest: %s returned %s", path, res.status_code)
            out.append(None)
            continue
        payload = res.json()
        out.append(payload if payload.get("success") else None)
    return out


# ---------------------------------------------------------------------------
# Gap 1 — daily series, last 14 days, zero-filled
# ---------------------------------------------------------------------------


async def _fetch_daily_series(pool, team, start: date, end: date) -> list[dict]:
    """One row per calendar day in [start, end] — days with no loads included.

    ``loads`` keeps the ``total_charge <> 0`` filter (a $0 load isn't a load);
    ``profit`` is the UNFILTERED margin sum (§39). ``margin_pct`` is recomputed
    in Python from the day's own components, never averaged.
    """
    params: list = []
    where = _v4_scope_where("br4", team, None, None, params)
    params.extend([start, end])
    p_s = len(params) - 1
    p_e = len(params)
    rows = await pool.fetch(
        f"""
        WITH days AS (
            SELECT generate_series(${p_s}::date, ${p_e}::date, INTERVAL '1 day')::date AS d
        ),
        agg AS (
            SELECT
              br4.origin_actual_departure::date AS d,
              COUNT(*) FILTER (WHERE br4.total_charge IS NOT NULL
                                 AND br4.total_charge <> 0)   AS loads,
              COALESCE(SUM(br4.margin_amt),   0)::numeric      AS profit,
              COALESCE(SUM(br4.total_charge), 0)::numeric      AS revenue,
              COUNT(DISTINCT br4.customer_name)                AS customers
            FROM public.mcleod_gld_budget_report_v4 br4
            WHERE {where}
              AND br4.origin_actual_departure >= ${p_s}
              AND br4.origin_actual_departure < (${p_e}::date + INTERVAL '1 day')
            GROUP BY 1
        )
        SELECT
          days.d                     AS day,
          COALESCE(agg.loads, 0)     AS loads,
          COALESCE(agg.profit, 0)    AS profit,
          COALESCE(agg.revenue, 0)   AS revenue,
          COALESCE(agg.customers, 0) AS customers
        FROM days
        LEFT JOIN agg ON agg.d = days.d
        ORDER BY days.d
        """,
        *params,
    )
    series = []
    for r in rows:
        profit = _safe_float(r["profit"])
        revenue = _safe_float(r["revenue"])
        margin = _ratio(profit, revenue)
        series.append({
            "day": r["day"],
            "loads": int(r["loads"] or 0),
            "profit": profit,
            "revenue": revenue,
            "customers": int(r["customers"] or 0),
            "margin_pct": None if margin is None else margin * 100.0,
        })
    return series


# ---------------------------------------------------------------------------
# Gap 2 — YTD profit + the four budget windows (daily / weekly / monthly / YTD)
# ---------------------------------------------------------------------------


async def _fetch_ytd_profit(pool, team, start: date, end: date) -> float:
    params: list = []
    where = _v4_scope_where("br4", team, None, None, params)
    params.extend([start, end])
    p_s = len(params) - 1
    p_e = len(params)
    val = await pool.fetchval(
        f"""
        SELECT COALESCE(SUM(br4.margin_amt), 0)::numeric AS ytd_profit
        FROM public.mcleod_gld_budget_report_v4 br4
        WHERE {where}
          AND br4.origin_actual_departure >= ${p_s}
          AND br4.origin_actual_departure < (${p_e}::date + INTERVAL '1 day')
        """,
        *params,
    )
    return _safe_float(val)


async def _fetch_profit_budgets(
    pool,
    team,
    *,
    ytd_start: date,
    ytd_end: date,
    day: date,
    week_start: date,
    week_end: date,
    mtd_start: date,
    mtd_end: date,
    month_start: date,
    month_end: date,
) -> dict[str, float]:
    """SUM("Profit Budget") over five "Date" windows in one scan.

    ``daily_production_budget_report`` has no pre-aggregated daily/weekly/
    monthly budget columns — every window is a sum over the matching "Date"
    range. Team scoping goes through CUSTOMER_TEAM_CTE (canonical per-customer
    team), exactly like /profit-tm-gauge and /actuals.

    ⚠ ``mtd_budget`` (month-start → TODAY) and ``month_budget`` (the whole
    month) are deliberately separate. The MTD *variance* pill pairs an elapsed
    actual with the budget for the SAME elapsed days — pairing it with the full
    month would print a ~-95% collapse on the 2nd of every month. Only the
    projection, which is itself a full-month figure, may use ``month_budget``.
    (/profit-tm-gauge pairs MTD actual with the full month on purpose: it is a
    "how far through the month's target am I" gauge, not a variance.)
    """
    row = await pool.fetchrow(
        f"""
        WITH {CUSTOMER_TEAM_CTE}
        SELECT
          COALESCE(SUM(b."Profit Budget") FILTER (WHERE b."Date" BETWEEN $1 AND $2), 0)::numeric  AS ytd_budget,
          COALESCE(SUM(b."Profit Budget") FILTER (WHERE b."Date" = $3), 0)::numeric               AS day_budget,
          COALESCE(SUM(b."Profit Budget") FILTER (WHERE b."Date" BETWEEN $4 AND $5), 0)::numeric  AS week_budget,
          COALESCE(SUM(b."Profit Budget") FILTER (WHERE b."Date" BETWEEN $6 AND $7), 0)::numeric  AS mtd_budget,
          COALESCE(SUM(b."Profit Budget") FILTER (WHERE b."Date" BETWEEN $8 AND $9), 0)::numeric  AS month_budget
        FROM public.daily_production_budget_report b
        JOIN customer_team ct ON TRIM(b."Customer Name") = ct.customer_name
        WHERE ct.team_id = ANY($10)
          AND b."Date" BETWEEN LEAST($1, $3, $4, $6, $8) AND GREATEST($2, $3, $5, $7, $9)
        """,
        ytd_start, ytd_end, day, week_start, week_end,
        mtd_start, mtd_end, month_start, month_end, _team_list(team),
    )
    return {
        "ytd_budget": _safe_float(row["ytd_budget"]),
        "day_budget": _safe_float(row["day_budget"]),
        "week_budget": _safe_float(row["week_budget"]),
        "mtd_budget": _safe_float(row["mtd_budget"]),
        "month_budget": _safe_float(row["month_budget"]),
    }


# ---------------------------------------------------------------------------
# Window maths
# ---------------------------------------------------------------------------


def _same_elapsed_last_month(mtd_start: date, mtd_end: date) -> Optional[tuple[date, date]]:
    """Previous month clamped to the SAME number of elapsed days as [s, e].

    Derived from the resolved MTD window rather than ``today.day`` so a clamped
    window (e.g. the YEAR_START clamp) still compares like for like. Returns
    ``None`` when the previous month falls outside the reporting year — better
    an em dash than a fake comparison against a truncated window.
    """
    elapsed = (mtd_end - mtd_start).days + 1
    prev_month_end = mtd_start - timedelta(days=1)
    prev_month_start = prev_month_end.replace(day=1)
    if prev_month_start < YEAR_START:
        return None
    end = min(prev_month_start + timedelta(days=elapsed - 1), prev_month_end)
    return prev_month_start, end


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


async def build_team_perf_digest(app, pool, team) -> dict[str, Any]:
    """Assemble the "Performance for Team N" / "PERFORMANCE CORP" payload.

    ``team`` is either one team id (``"TEAM4"``) or several
    (``["TEAM1","TEAM2","TEAM3","TEAM4"]`` — the CORP roll-up). A multi-team
    scope is pushed all the way down into SQL and aggregated ONCE. It is never
    assembled by adding four single-team digests together: distinct customer
    counts, OTP %, OTD %, margin % and the top-15 customer table are all
    non-additive across teams, so summing them would produce numbers that look
    entirely plausible and are wrong.

    Returns ``{"subject", "html", "generatedAt", "meta"}``.
    """
    team_ids = _team_list(team)
    unknown = [t for t in team_ids if t not in CORP_TEAMS]
    if not team_ids or unknown:
        raise ValueError(f"unknown team(s) {unknown or team!r}")
    multi = len(team_ids) > 1

    # What the downstream endpoints are asked for. One team keeps the original
    # `team=` parameter so the per-team emails emit byte-identical requests to
    # the ones they have always sent.
    scope_query = (
        {"teams": ",".join(team_ids)} if multi else {"team": team_ids[0]}
    )
    if multi:
        scope_title = "Performance CORP"
        scope_footer = f"{'+'.join(team_ids)} (CORP)"
    else:
        scope_title = f"Performance for Team {team_ids[0].replace('TEAM', '')}"
        scope_footer = f"{team_ids[0]} (CORP)"

    today = cst_today()
    now = cst_now()
    mtd_start, mtd_end = _resolve_range("mtd", None, None)
    month_start, month_end = _month_bounds(today)
    yesterday = today - timedelta(days=1)
    series_start = today - timedelta(days=SERIES_DAYS)
    series_end = today - timedelta(days=1)
    week_start = today - timedelta(days=WEEK_DAYS)
    week_end = today - timedelta(days=1)
    # Elapsed days in the CURRENT MTD window — derived from the resolved window,
    # never from today.day, so a clamped window still compares like for like.
    # Every month-over-month / vs-budget comparison below is pinned to it.
    elapsed_days = (mtd_end - mtd_start).days + 1
    last_month = _same_elapsed_last_month(mtd_start, mtd_end)

    # --- Batch 1: the three /team-performance windows ----------------------
    calls_a: list[tuple[str, dict]] = [
        ("/team-performance", {**scope_query, "range": "mtd"}),
        ("/team-performance", {
            **scope_query, "range": "custom",
            "start_date": yesterday.isoformat(), "end_date": yesterday.isoformat(),
        }),
    ]
    if last_month:
        calls_a.append(("/team-performance", {
            **scope_query, "range": "custom",
            "start_date": last_month[0].isoformat(), "end_date": last_month[1].isoformat(),
        }))
    batch_a = await _get_many(app, calls_a)
    tp_mtd = (batch_a[0] or {}).get("data") or {}
    tp_yday = (batch_a[1] or {}).get("data") or {}
    tp_lm = ((batch_a[2] or {}).get("data") or {}) if last_month else {}

    # --- Batch 2: gauge + projection + actuals, alongside the direct SQL ---
    calls_b: list[tuple[str, dict]] = [
        ("/profit-tm-gauge", dict(scope_query)),
        ("/team-projection", dict(scope_query)),
        # Request 2026-08-25: the customer panel ranks by PROFIT, not revenue.
        # `profit_desc` already existed in the /actuals sort map, so this is a
        # parameter change, not new ordering code. The sort key, the limit and
        # the caption's wording all come from ONE place so the rendered footer
        # cannot disagree with what was actually requested.
        ("/actuals", {
            **scope_query,
            "range": "mtd",
            "sort": CUSTOMER_PANEL_SORT,
            "limit": CUSTOMER_PANEL_FETCH,
        }),
    ]
    batch_b, series, ytd_profit, budgets = await asyncio.gather(
        _get_many(app, calls_b),
        _fetch_daily_series(pool, team_ids, series_start, series_end),
        _fetch_ytd_profit(pool, team_ids, YEAR_START, today),
        _fetch_profit_budgets(
            pool, team_ids,
            ytd_start=YEAR_START, ytd_end=today,
            day=yesterday,
            week_start=week_start, week_end=week_end,
            mtd_start=mtd_start, mtd_end=mtd_end,
            month_start=month_start, month_end=month_end,
        ),
    )
    gauge = (batch_b[0] or {}).get("data") or {}
    proj = (batch_b[1] or {}).get("data") or {}
    actuals_payload = batch_b[2] or {}
    all_customer_rows = actuals_payload.get("data") or []
    # /actuals appends budget-only customers with zero production so the
    # variance columns still show the gap. This panel shows ACTUALS only, where
    # those rows are all-zero noise — drop them for display. The TOTAL row stays
    # the server-side full-universe total (§44), so it still ties to the ACTUAL
    # PROFIT card regardless of what is filtered out here.
    producing_rows = [
        r for r in all_customer_rows
        if int(r.get("vol") or 0) > 0
        or _safe_float(r.get("rev"))
        or _safe_float(r.get("prof"))
    ]
    # /actuals already returned these sorted by CUSTOMER_PANEL_SORT, so the
    # slice is the top N of the PRODUCING customers — not the top N of a list
    # padded with budget-only zeros. Slicing here rather than server-side is
    # what makes "top 15" mean fifteen real rows.
    customer_rows = producing_rows[:CUSTOMER_PANEL_LIMIT]
    if len(all_customer_rows) >= CUSTOMER_PANEL_FETCH:
        # Hitting the fetch ceiling means the ranking may be truncated upstream
        # and the panel could be missing a customer that belongs in the top N.
        logger.warning(
            "team digest: /actuals returned %s rows, at the %s fetch ceiling — "
            "the customer ranking may be incomplete",
            len(all_customer_rows), CUSTOMER_PANEL_FETCH,
        )
    customer_totals = (actuals_payload.get("meta") or {}).get("totals") or {}

    # --- Card 1 — ACTUAL PROFIT (MTD) --------------------------------------
    profit_mtd = _safe_float(tp_mtd.get("profit"))
    revenue_mtd = _safe_float(tp_mtd.get("revenue"))
    margin_mtd = _ratio(profit_mtd, revenue_mtd)
    margin_mtd_pct = None if margin_mtd is None else margin_mtd * 100.0

    profit_yday = _safe_float(tp_yday.get("profit"))
    # Average profit/day over the 14-day window — the series is zero-filled, so
    # the divisor is the full window length (no "days with data" inflation).
    avg_profit_day = _ratio(sum(d["profit"] for d in series), float(len(series)))
    profit_lm = _safe_float(tp_lm.get("profit")) if tp_lm else None

    # Budget for the SAME elapsed days as the MTD actual above — NOT the full
    # month (that is `budgets["month_budget"]`, used only by the projection).
    budget_mtd = budgets["mtd_budget"]

    card1 = {
        "profit": profit_mtd,
        "margin_pct": margin_mtd_pct,
        "caption": f"MTD ({mtd_start.strftime('%B %Y')})",
        "pills": [
            {
                "label": "Yesterday vs 14-day avg/day",
                "delta": (None if avg_profit_day is None
                          else _pct_change(profit_yday, avg_profit_day)),
                "unit": "%",
                "basis": avg_profit_day,
                "basis_kind": "usd",
                "basis_label": "avg/day",
            },
            {
                "label": f"MTD vs last month (same {elapsed_days}d)",
                "delta": (None if profit_lm is None
                          else _pct_change(profit_mtd, profit_lm)),
                "unit": "%",
                "basis": profit_lm,
                "basis_kind": "usd",
                "basis_label": "last month",
            },
            {
                "label": f"MTD vs budget (same {elapsed_days}d)",
                "delta": _pct_change(profit_mtd, budget_mtd),
                "unit": "%",
                "basis": budget_mtd if budget_mtd else None,
                "basis_kind": "usd",
                "basis_label": "budget",
            },
        ],
    }

    # --- Card 2 — PROFIT BUDGET PERFORMANCE (TM), YTD ----------------------
    ytd_achievement = _achievement_pct(ytd_profit, budgets["ytd_budget"])
    profit_week = sum(d["profit"] for d in series[-WEEK_DAYS:]) if series else 0.0
    proj_profit = _safe_float(proj.get("proj_profit")) if proj else 0.0

    # Each pill = (achievement% − 100) in percentage POINTS. Achievement is a
    # rate recomputed from its own components, so the delta is pp, not a
    # percent-of-percent.
    def _pp_vs_budget(actual: float, budget: float) -> Optional[float]:
        a = _achievement_pct(actual, budget)
        return None if a is None else a - 100.0

    card2 = {
        "ytd_achievement_pct": ytd_achievement,
        "caption": f"YTD ({today.year})",
        "pills": [
            {
                "label": "Yesterday vs daily budget",
                "delta": _pp_vs_budget(profit_yday, budgets["day_budget"]),
                "unit": "pp",
                "basis": budgets["day_budget"] or None,
                "basis_kind": "usd",
                "basis_label": "daily budget",
            },
            {
                "label": f"Last {WEEK_DAYS} days vs weekly budget",
                "delta": _pp_vs_budget(profit_week, budgets["week_budget"]),
                "unit": "pp",
                "basis": budgets["week_budget"] or None,
                "basis_kind": "usd",
                "basis_label": "weekly budget",
            },
            {
                "label": "Projected month vs monthly budget",
                "delta": _pp_vs_budget(proj_profit, budgets["month_budget"]),
                "unit": "pp",
                "basis": budgets["month_budget"] or None,
                "basis_kind": "usd",
                "basis_label": "monthly budget",
            },
        ],
    }

    # --- Cards 3 & 4 — OTP / OTD (MTD), pp vs last-month same elapsed days --
    def _rate(obj: dict, field: str) -> Optional[float]:
        if not obj or obj.get(field) is None:
            return None
        return _safe_float(obj.get(field))

    otp_mtd, otd_mtd = _rate(tp_mtd, "otp_pct"), _rate(tp_mtd, "otd_pct")
    otp_lm, otd_lm = _rate(tp_lm, "otp_pct"), _rate(tp_lm, "otd_pct")
    lm_label = "last month" if last_month else "n/a"
    card3 = {
        "title": "ACTUAL OTP (MTD)",
        "value": otp_mtd,
        "pill": {
            "label": f"vs {lm_label} (same days)",
            "delta": _pp_delta(otp_mtd, otp_lm),
            "unit": "pp",
            "basis": otp_lm,
            "basis_kind": "pct",
            "basis_label": "last month",
        },
    }
    card4 = {
        "title": "ACTUAL OTD (MTD)",
        "value": otd_mtd,
        "pill": {
            "label": f"vs {lm_label} (same days)",
            "delta": _pp_delta(otd_mtd, otd_lm),
            "unit": "pp",
            "basis": otd_lm,
            "basis_kind": "pct",
            "basis_label": "last month",
        },
    }

    # --- Card 5 — PROJECTED PROFIT PERFORMANCE (TM) ------------------------
    month_budget = budgets["month_budget"]
    card5 = {
        "proj_profit": proj_profit,
        "month_budget": month_budget,
        "on_track": bool(month_budget) and proj_profit >= month_budget,
        "has_budget": bool(month_budget),
        "achievement_pct": _achievement_pct(proj_profit, month_budget),
    }

    html, chart_urls = render_html(
        scope_title=scope_title,
        scope_footer=scope_footer,
        scope_is_multi_team=multi,
        now=now,
        card1=card1,
        card2=card2,
        card3=card3,
        card4=card4,
        card5=card5,
        customer_rows=customer_rows,
        customer_totals=customer_totals,
        customer_limit=CUSTOMER_PANEL_LIMIT,
        customer_basis=CUSTOMER_PANEL_BASIS,
        series=series,
    )

    profit_str = ("-" if profit_mtd < 0 else "") + f"${abs(profit_mtd):,.0f}"
    subject = f"{scope_title} — {profit_str} Profit MTD ({today.isoformat()})"

    return {
        "subject": subject,
        "html": html,
        "generatedAt": now.isoformat(),
        "meta": {
            # `team` / `team_number` are kept for the four per-team workflows
            # that already read this payload — ADDED to, never renamed. For a
            # multi-team scope `team` is the joined list and `team_number` is
            # "CORP", which is what a single-team consumer would print anyway.
            "team": ",".join(team_ids),
            "team_number": "CORP" if multi else team_ids[0].replace("TEAM", ""),
            "teams": list(team_ids),
            "scope": "CORP" if multi else team_ids[0],
            "today": today.isoformat(),
            "windows": {
                "mtd": {"start": mtd_start.isoformat(), "end": mtd_end.isoformat()},
                "last_month_same_days": (
                    {"start": last_month[0].isoformat(), "end": last_month[1].isoformat()}
                    if last_month else None
                ),
                "yesterday": yesterday.isoformat(),
                "series": {"start": series_start.isoformat(), "end": series_end.isoformat()},
                "week": {"start": week_start.isoformat(), "end": week_end.isoformat()},
                "month": {"start": month_start.isoformat(), "end": month_end.isoformat()},
                "ytd": {"start": YEAR_START.isoformat(), "end": today.isoformat()},
            },
            "profit_mtd": profit_mtd,
            "revenue_mtd": revenue_mtd,
            "margin_pct_mtd": margin_mtd_pct,
            "volume_mtd": int(tp_mtd.get("volume") or 0),
            "customers_mtd": int(tp_mtd.get("customers") or 0),
            "profit_yesterday": profit_yday,
            "profit_last_month_same_days": profit_lm,
            "avg_profit_per_day_14d": avg_profit_day,
            "profit_last_6_days": profit_week,
            "profit_ytd": ytd_profit,
            "budget_ytd": budgets["ytd_budget"],
            "ytd_budget_achievement_pct": ytd_achievement,
            # Elapsed-days budget — the denominator of the MTD variance pill.
            "budget_mtd": budget_mtd,
            "budget_day": budgets["day_budget"],
            "budget_week": budgets["week_budget"],
            # Full-month budget — used ONLY by the projection comparison.
            "budget_month": month_budget,
            # Cross-check: /profit-tm-gauge is MTD actual over the FULL-month
            # budget by design, so gauge_profit_budget should equal
            # budget_month, and gauge_profit_mtd should equal profit_mtd.
            "gauge_profit_mtd": _safe_float(gauge.get("profit_mtd")) if gauge else None,
            "gauge_profit_budget": _safe_float(gauge.get("profit_budget")) if gauge else None,
            "gauge_pct_of_budget": _safe_float(gauge.get("pct_of_budget")) if gauge else None,
            "otp_pct_mtd": otp_mtd,
            "otd_pct_mtd": otd_mtd,
            "proj_profit": proj_profit,
            "on_track": card5["on_track"],
            "customer_rows": len(customer_rows),
            "customer_rows_before_zero_filter": len(all_customer_rows),
            "customer_rows_producing": len(producing_rows),
            # Published so a consumer can assert the ranking basis instead of
            # reading it out of the rendered footer prose.
            "customer_sort": CUSTOMER_PANEL_SORT,
            "customer_limit": CUSTOMER_PANEL_LIMIT,
            "customer_totals": customer_totals,
            "charts": chart_urls,
            "sources": [
                f"{API_PREFIX}/team-performance",
                f"{API_PREFIX}/profit-tm-gauge",
                f"{API_PREFIX}/team-projection",
                f"{API_PREFIX}/actuals",
                "direct SQL: mcleod_gld_budget_report_v4 (14d series, YTD profit)",
                "direct SQL: daily_production_budget_report (day/week/month/YTD budget)",
            ],
        },
    }
