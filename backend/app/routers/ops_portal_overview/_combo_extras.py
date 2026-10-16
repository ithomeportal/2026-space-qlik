"""KPI MANAGEMENT chart extras — Customers measure + Projected candlesticks.

Bruno PDF 2026-10-16 "Ops Portal Updates" R1. Part of the ``ops_portal_overview``
package (see SPEC-CUSTOM-REPORTS §28); helpers only, no routes — ``chart.py``
stays the one place ``/combo`` is defined, so the 7 portals that wrap it get
both features with no new endpoint and no parameter-parity work.

Customers
---------
``customers`` = DISTINCT ``customer_name`` per bucket over the SAME population
as the Vol. bars (``total_charge IS NOT NULL AND total_charge <> 0``, §96) — a
customer whose only rows in a bucket are zero-charge has no load in the Vol.
count, so it must not be a customer in the bar beside it either.

``new_customers`` = customers present in a bucket with NO load in the
IMMEDIATELY previous bucket of the same grain (previous day / ISO week /
calendar month). It is computed in the SAME scan as the volume bars — a
per-(bucket, customer) GROUP BY, a ``LAG`` over it, then the bucket roll-up —
never a second CTE over v4 (memory feedback_derived_count_same_scan: a second
materialised re-count timed out). Every CTE below is referenced exactly once,
so Postgres inlines it: one seq scan of the window, one WindowAgg.

⚠ The scan starts ONE BUCKET BEFORE the visible window. Without it every
customer in the first anchor would have no "previous bucket" row and the first
bar would read 100 % new. The extra bucket is dropped by the caller, which only
emits the anchors.

Projected candles
-----------------
Per bucket, the open / high / low / close of the projection AS IT MOVED during
that bucket, read from the portal-owned ``ops_projection_history`` (one row per
scope, team, as-of date — §84-86):

  * month → ``proj_<m>``              (the month-end projection)
  * week  → ``avg_<m>_day × 7``       (the convention the flat line already used)
  * day   → ``avg_<m>_day``           (one snapshot ⇒ a degenerate candle)
  * margin_pct is a ratio — never scaled; ``proj_margin_pct`` at every grain.

History is UNFILTERED (same rule as /team-projection-history): any customer,
lane, carrier or load-type filter, or a team selection with no stored series,
answers ``tracked: false`` and the UI falls back to the flat Projected line.

The live projection is folded into today's bucket and REPLACES today's stored
row (§84) — the stored row is the 02:45 opening value, and a candle whose high
sits below the number the panel prints is the defect §84 exists to prevent.
"""

from __future__ import annotations

import logging
from datetime import date, timedelta
from typing import Any, Iterable, Mapping, Optional, Sequence

from ._metrics import _safe_float

logger = logging.getLogger(__name__)

# Measures a candle exists for. Service and Customers have no projection.
CANDLE_MEASURES: tuple[str, ...] = ("volume", "revenue", "profit", "margin_pct")

# Week candles scale the per-business-day average by 7 — identical to the flat
# week Projected line this replaces (see the `_metrics.py` header table), so
# the two renderings of "Projected" cannot disagree at the week grain.
WEEK_SCALE_DAYS = 7

_AVG_COL = {"volume": "avg_vol_day", "revenue": "avg_rev_day", "profit": "avg_prof_day"}
_PROJ_COL = {
    "volume": "proj_volume",
    "revenue": "proj_revenue",
    "profit": "proj_profit",
    "margin_pct": "proj_margin_pct",
}


# ---------------------------------------------------------------------------
# Bucket arithmetic (pure)
# ---------------------------------------------------------------------------


def bucket_of(grain: str, d: date) -> date:
    """The bucket ``d`` falls in — mirrors ``DATE_TRUNC`` in the /combo SQL."""
    if grain == "month":
        return d.replace(day=1)
    if grain == "week":
        return d - timedelta(days=d.weekday())
    return d


def previous_bucket(grain: str, anchor: date) -> date:
    """The bucket immediately before ``anchor`` at ``grain``."""
    if grain == "month":
        return (anchor - timedelta(days=1)).replace(day=1)
    if grain == "week":
        return anchor - timedelta(days=7)
    return anchor - timedelta(days=1)


# Day grain compares against the previous active BUSINESS day, not the
# calendar day before: with the calendar rule every Monday (and every day after
# a holiday) read ~100 % "new". Week and month buckets are
# never empty in practice, so they keep the strict "immediately previous" rule.
DAY_LOOKBACK_DAYS = 7


def lookback_start(grain: str, anchor: date) -> date:
    """Where the scan starts so the first visible bucket has a predecessor.

    Day grain reaches back a week so the first visible Monday still finds the
    previous Friday (or the last active day before a long weekend)."""
    if grain == "day":
        return anchor - timedelta(days=DAY_LOOKBACK_DAYS)
    return previous_bucket(grain, anchor)


# SQL spelling of the predecessor bucket. Week subtracts an integer
# (date - int = date); month needs the interval and a cast back; day takes the
# latest ACTIVE WEEKDAY strictly before this one — a window frame over the
# already aggregated rows, so `per_cust` is still referenced once (inlined, one
# v4 scan). Weekday, not merely active: weekends run a handful of customers
# (5 on Sun 2026-10-11 vs 22 on Fri 10-09), so Monday-vs-Sunday still read
# ~70 % "new" live. Every day compares with the previous BUSINESS day.
_PREV_BUCKET_SQL = {
    "day": (
        "MAX(pc.bucket_start) FILTER (WHERE pc.volume > 0"
        " AND EXTRACT(ISODOW FROM pc.bucket_start) < 6) OVER ("
        "ORDER BY pc.bucket_start "
        "RANGE BETWEEN UNBOUNDED PRECEDING AND INTERVAL '1 day' PRECEDING)"
    ),
    "week": "(pc.bucket_start - 7)",
    "month": "(pc.bucket_start - INTERVAL '1 month')::date",
}


# When the customer was last seen, on the SAME calendar as the predecessor:
# week/month use the plain LAG over the customer's counted buckets; day grain
# must ask for the customer's latest earlier WEEKDAY, or a Fri+Sat customer
# reads "last seen Sat ≠ predecessor Fri" and is miscounted as new on Sunday
# (caught by the live reference check).
_PREV_SEEN_SQL = {
    "day": (
        "MAX(pc.bucket_start) FILTER (WHERE pc.volume > 0"
        " AND EXTRACT(ISODOW FROM pc.bucket_start) < 6) OVER ("
        "PARTITION BY pc.cust ORDER BY pc.bucket_start "
        "RANGE BETWEEN UNBOUNDED PRECEDING AND INTERVAL '1 day' PRECEDING)"
    ),
    "default": (
        "LAG(pc.bucket_start) OVER (\n"
        "                   PARTITION BY pc.cust, (pc.volume > 0)\n"
        "                   ORDER BY pc.bucket_start\n"
        "                 )"
    ),
}


def combo_production_sql(grain: str, trunc_v4: str, where: str, p_ws: int, p_we: int) -> str:
    """The /combo production statement: bars + losses + customers, ONE scan.

    Sums are re-aggregated from per-customer partials, so every pre-existing
    column is the same number it was before customers existed (a NULL
    ``customer_name`` is its own group and still contributes to the sums).
    """
    prev = _PREV_BUCKET_SQL.get(grain, _PREV_BUCKET_SQL["month"])
    prev_seen = _PREV_SEEN_SQL["day"] if grain == "day" else _PREV_SEEN_SQL["default"]
    return f"""
        WITH per_cust AS (
          SELECT
            {trunc_v4} AS bucket_start,
            NULLIF(TRIM(br4.customer_name), '') AS cust,
            COUNT(*) FILTER (WHERE br4.total_charge IS NOT NULL AND br4.total_charge <> 0) AS volume,
            SUM(br4.total_charge) AS revenue,
            SUM(br4.margin_amt)   AS profit,
            COUNT(*) FILTER (WHERE br4.margin_amt < 0
                               AND br4.total_charge IS NOT NULL
                               AND br4.total_charge <> 0) AS losses_vol,
            SUM(br4.total_charge) FILTER (WHERE br4.margin_amt < 0) AS losses_rev,
            SUM(br4.margin_amt)   FILTER (WHERE br4.margin_amt < 0) AS losses_prof
          FROM public.mcleod_gld_budget_report_v4 br4
          WHERE {where}
            AND br4.origin_actual_departure >= ${p_ws}
            AND br4.origin_actual_departure < (${p_we}::date + INTERVAL '1 day')
          GROUP BY 1, 2
        ),
        flagged AS (
          SELECT pc.*,
                 (pc.volume > 0 AND pc.cust IS NOT NULL) AS present,
                 {prev_seen} AS prev_seen,
                 {prev} AS prev_bucket
          FROM per_cust pc
        )
        SELECT
          bucket_start,
          COALESCE(SUM(volume), 0)::bigint      AS volume,
          COALESCE(SUM(revenue), 0)::numeric    AS revenue,
          COALESCE(SUM(profit), 0)::numeric     AS profit,
          COALESCE(SUM(losses_vol), 0)::bigint  AS losses_vol,
          COALESCE(SUM(losses_rev), 0)::numeric AS losses_rev,
          COALESCE(SUM(losses_prof), 0)::numeric AS losses_prof,
          COUNT(*) FILTER (WHERE present) AS customers,
          COUNT(*) FILTER (WHERE present
                             AND prev_seen IS DISTINCT FROM prev_bucket) AS new_customers
        FROM flagged
        GROUP BY 1
    """


def new_customers_reference(presence: Mapping[date, Iterable[str]], grain: str) -> dict[date, int]:
    """Pure-Python statement of the ``new_customers`` rule, for tests and probes.

    ``presence`` maps bucket → customers with ≥1 counted load in it. A customer
    is new in a bucket when it is absent from the IMMEDIATELY previous bucket —
    not merely from the last bucket that happens to have data. Day grain is the
    exception: its predecessor is the previous active WEEKDAY (Mon–Fri).
    """
    sets = {b: set(c) for b, c in presence.items() if c}
    if grain == "day":
        weekdays = sorted(d for d in sets if d.weekday() < 5)
        prev_of = {d: max((w for w in weekdays if w < d), default=None) for d in sets}
        return {b: len(cs - sets.get(prev_of[b], set())) if prev_of[b] else 0
                for b, cs in sets.items()}
    return {
        b: len(cs - sets.get(previous_bucket(grain, b), set()))
        for b, cs in sets.items()
    }


# ---------------------------------------------------------------------------
# Projected candles
# ---------------------------------------------------------------------------

CANDLE_HISTORY_SQL = """
    SELECT as_of_date,
           proj_volume, proj_revenue, proj_profit, proj_margin_pct,
           avg_vol_day, avg_rev_day, avg_prof_day
      FROM ops_projection_history
     WHERE scope_key = $1 AND team_key = $2
       AND as_of_date BETWEEN $3 AND $4
     ORDER BY as_of_date
"""


def candle_value(row: Mapping[str, Any], measure: str, grain: str) -> float:
    """One snapshot's value for ``measure`` at ``grain`` (see module docstring)."""
    if measure == "margin_pct" or grain == "month":
        return _safe_float(row.get(_PROJ_COL[measure]))
    per_day = _safe_float(row.get(_AVG_COL[measure]))
    return per_day * WEEK_SCALE_DAYS if grain == "week" else per_day


def fold_live(rows: Sequence[Mapping[str, Any]], live: Optional[Mapping[str, Any]],
              today: date) -> list[dict]:
    """Replace today's stored snapshot with the live projection (§84)."""
    merged = [dict(r) for r in rows if r.get("as_of_date") != today]
    if live:
        merged.append({"as_of_date": today, **{
            k: _safe_float(live.get(k)) for k in (*_PROJ_COL.values(), *_AVG_COL.values())
        }})
    return sorted(merged, key=lambda r: r["as_of_date"])


def aggregate_candles(rows: Sequence[Mapping[str, Any]], grain: str) -> dict[date, dict]:
    """bucket → {measure: {open, high, low, close, days}} over ordered snapshots."""
    by_bucket: dict[date, list[Mapping[str, Any]]] = {}
    for r in sorted(rows, key=lambda x: x["as_of_date"]):
        by_bucket.setdefault(bucket_of(grain, r["as_of_date"]), []).append(r)
    out: dict[date, dict] = {}
    for b, snaps in by_bucket.items():
        out[b] = {}
        for m in CANDLE_MEASURES:
            vals = [candle_value(s, m, grain) for s in snaps]
            out[b][m] = {
                "open": vals[0], "high": max(vals), "low": min(vals),
                "close": vals[-1], "days": len(vals),
            }
    return out


def candle_tracking(scope: Any, team_ids: Sequence[str], filtered: bool) -> tuple[Optional[str], Optional[str]]:
    """(team_key, untracked_reason) — exactly one of them is None.

    Same decision as /team-projection-history: a filter makes the chart's
    population incomparable with the stored (unfiltered) series.
    """
    # Deferred: the service imports this package's leaf modules, so a
    # module-level import here closes the §86 cycle through the façade.
    from app.services.projection_history import resolve_history_key

    if filtered:
        return None, "filtered"
    key = resolve_history_key(scope, team_ids)
    if key is None:
        return None, "team_scope"
    return key, None


async def fetch_candles(hub_pool, *, scope_key: str, team_key: str, grain: str,
                        start: date, end: date) -> list[dict]:
    """The stored snapshots in [start, end], oldest first."""
    rows = await hub_pool.fetch(CANDLE_HISTORY_SQL, scope_key, team_key, start, end)
    return [dict(r) for r in rows]


def candles_for_anchors(rows: Sequence[Mapping[str, Any]], live: Optional[Mapping[str, Any]],
                        grain: str, anchors: Sequence[date], today: date) -> dict[date, dict]:
    """Fold live in, aggregate, and keep only the chart's anchors."""
    agg = aggregate_candles(fold_live(rows, live, today), grain)
    wanted = set(anchors)
    return {b: v for b, v in agg.items() if b in wanted}

