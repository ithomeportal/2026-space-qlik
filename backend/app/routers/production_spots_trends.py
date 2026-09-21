"""Production SPOTS Trends — the executive view over the whole spot funnel.

The detail already exists on the quoting portal (``pricing.unilinkportal.com``
``/spots/manual``, ``/spots/homedepot``, ``/spots/emerge``). This report is the
layer above it: global KPIs, period-over-period comparatives aligned to the same
elapsed business days, month-end projection, and the trend lines — for managers
who need the shape, not the rows.

Source, and what it can and cannot see
--------------------------------------
ONE table: ``spot_report_condensed`` in ``modern_pricing_portal`` (pool
``get_pricing_pool``). Verified 2026-09-21 with a real query — not
``information_schema``, which is privilege-filtered and would have reported the
rest of the database as non-existent — the read-only role
``spaceqlik_pricing_ro`` holds ``SELECT`` on **1 of the 99 tables** there::

    SELECT count(*) FILTER (WHERE has_table_privilege(current_user, c.oid,'SELECT')),
           count(*) FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
    WHERE n.nspname='public' AND c.relkind='r';        -- 1 | 99

Consequences, all of them deliberate and all of them stated on screen:

* **The Emerge / Trane board is not in this report.** Emerge opportunities land
  in ``emerge_quote_requests`` via an inbound webhook and there is **no sync
  path into** ``spot_report_condensed`` at all. Trane's *manual* rows do appear
  (671 in the last 90 days) — its Emerge board does not. Covering it needs a
  ``GRANT`` first; ``docs/SPEC-PRODUCTION-SPOTS-TRENDS.md`` carries the exact
  statement.
* **Skip *reasons* are unavailable.** ``opting_out_reason`` has had 0 rows for
  90 days and last fired 2026-03-26; the live taxonomy lives in
  ``spot_manual_consultations.skip_reason``, which is denied. We can count a
  skip; we cannot say why.
* **Response latency is not computable.** There is no "responded at". The only
  candidate, ``updated_at``, is BULK-TOUCHED — 38.9M updates against 8.4k
  inserts, because the sync re-upserts the whole table every run, so every row
  from 2026-09-01 carries today's ``updated_at``. It is a pipeline heartbeat
  and nothing else (which is exactly what ``/freshness`` uses it for). Building
  a latency KPI on it would read ~14 days and be pure artefact.
* **Portal provenance does not propagate.** e2open, Princeton, Transporeon and
  RXO rows all arrive as ``source = 'lane_analysis'``; they are separable only
  as *customers*. ``source`` means "which pipeline fed the report" here and
  "which external portal filed the row" on ``spot_manual_consultations`` — two
  different things with one name.

The status lifecycle, measured rather than assumed
--------------------------------------------------
``award_status`` is the only live status column (``status_id`` /
``status_set_at`` / ``status_set_by`` all died 2026-03-26). Its values map onto
the request's vocabulary exactly, and ``LOST-A`` is the important one:

===================  ===========================================================
Presented            every row
Quoted               ``price IS NOT NULL AND price <> 0``
Skipped              not priced — we never put a number on it
Won                  ``WON``
Lost (rejected)      ``LOST`` / ``DECLINED`` / ``CLOSE AUTO`` / ``REJECTED``
**No reply**         ``LOST-A`` — aged off by a cron after 30 days unanswered
In play              ``ACCEPT`` (HD: priced, outcome pending) · ``''`` (open)
Cancelled            ``CANCELED`` (one L)
===================  ===========================================================

⚠ A prior analysis of this table reported ``award_status IS NULL`` as a
*terminal* "no reply" state, and read the 2026-08-23 switch from ``LOST-A`` to
NULL as a taxonomy change. Both are wrong, and the age curve says so::

    SELECT width_bucket(today - price_date::date, 0, 90, 18)*5 AS age, count(*),
           ... FILTER (WHERE award_status IS NULL), ... FILTER (WHERE st='LOST-A')
    -- age <= 30d : 69-85% NULL, 0% LOST-A
    -- age >= 35d :     0% NULL, 87-96% LOST-A

NULL is **OPEN and transient**; the age-off cron converts it to ``LOST-A`` at 30
days. The "2026-08-23 regime break" is just that boundary sliding with the
calendar. So there is no definition change to draw on the chart — but there IS
right-censoring, which is the next section.

🔴 Outcomes right-censor, and the horizon is per channel
--------------------------------------------------------
Measured on live data 2026-09-21:

* **HD** — ``ACCEPT`` ("priced, outcome pending") is 89-95% of rows at age ≤ 6
  days, 36% at day 7, 1.6% at day 10, 0% at day 13. Win rate reads 1-3% on
  young cohorts against 4-8% once matured.
* **Manual** — settles at the 30-day age-off described above.

Therefore **activity** metrics (Presented / Quoted / Skip / Quote-rate /
Potential revenue) are maturity-free and compare on the raw aligned windows,
while **outcome** metrics (Win rate / Won / Awarded revenue) compare on the last
**SETTLED** periods — a window whose end is at least ``MATURITY_DAYS`` ago. One
conservative horizon (30 d) is used for both channels rather than two, because a
window settled for Manual is necessarily settled for HD.

Without that split, a Monday-morning "this week vs last week win rate" tile
would print a collapse every single week, forever, and be believed once.

Other rules this file obeys
---------------------------
* Date bounds bind on the **parameter** — ``price_date >= ($n::date AT TIME ZONE
  'America/Chicago')`` — never ``(price_date AT TIME ZONE ...)::date >= $n``,
  which is a function on the indexed column: measured 36.7 ms vs 2.5 ms on this
  exact table, and the parameter form is DST-correct. The upper bound is
  exclusive-next-day so the last day is whole (``<= $end`` against a timestamp
  compares to midnight, so ``from == to`` returns nothing and reads as "no
  activity"). §64
* The frozen ``legacy_hd`` / ``legacy`` imports are excluded as a **NOT-IN**, so
  a new *live* feed is picked up automatically instead of silently dropped. They
  are not merely old: ``legacy_hd.volume`` is NULL on all 36,134 rows, and the
  two overlap the live feeds on 3,319 duplicate offer ids. §62
* ``DATA_FLOOR = 2026-04-01`` — April is the first month with no frozen-feed
  overlap at all. (HD Spot floors at 2026-03-01 because it only reads the HD
  feed, where March is already clean.)
* **Profit is ``price − accessorials − buy_rate``**, never ``price − buy_rate``.
  Accessorials are non-zero on 27% of consultations and the naive form reads
  ~$862k high over 120 days — always flattering, so nobody reports it.
* A COUNT beside a SUM spans ONE population (§96): ``awarded_profit`` is summed
  only where both legs are known, so it is divided by ``awarded_rev_known`` —
  never by ``awarded_revenue``, which spans every won row — and the row count
  behind it ships to the screen.
* Every outcome bucket carries ``priced``, so the buckets **partition** the
  quoted set exactly (``quoted = won + lost + no_reply + rejected + cancelled +
  accept + open + other``) and ``presented = quoted + skipped``. Both identities
  are asserted against the live table by the test suite. 5 of 2,949 won rows
  since April are unpriced (0.17%) and fall into ``skipped`` — the alternative,
  letting revenue span a wider population than its count, is the §96 defect.
* Equipment groups use ``ILIKE``, never ``IN``: HD rows are ``DRY_VAN`` /
  ``FLATBED`` and the lane feed carries a bare ``VAN``. ⚠ ``REEFER`` exists only
  on the lane feed — HD Spot's ``VAN``-or-``FLAT`` guard would silently delete
  it here, so this report has a Reefer group and an Other catch-all.
* Rates are recomputed from components, never averaged, and guarded ``den > 0``
  rather than ``not den``. Percentages leave as **fractions**.
* Spot volume is a **Mon–Fri** business: Sat+Sun are 111 of 20,004 rows (0.55%)
  and HD posts exactly zero at weekends. So the projection divisor is Mon–Fri —
  not the Ops Portal's Mon–Sat — and week alignment is by weekday.

Two scars this report annotates rather than hides
-------------------------------------------------
* **2026-07-17 → 07-20** — a 215-char ``order_number`` raised SQLSTATE 22001 in
  the first of four sequential statements in one try block, freezing both feeds
  for ~150 cron runs. Any window containing those days is partial (17 Jul
  captured 54 of 229 HD offers) and says so.
* **Bot outcomes before 2026-09-21** — the external-portal agent recorded zero
  wins, ever, until that date: an e2open award event was unmapped, and all 14
  historical wins were typed in by hand on one day. A bot-vs-human win-rate line
  crossing it is not apples-to-apples, and a pessimistic bot win rate reads as
  "the formula is priced too high".
"""

from __future__ import annotations

import asyncio
import logging
from calendar import monthrange
from datetime import date, timedelta
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request

from app.clock import cst_today
from app.routers.deps import (
    get_datalake_gold_pool,
    get_pricing_pool,
    require_report_access,
)

logger = logging.getLogger(__name__)

router = APIRouter(
    tags=["production-spots-trends"], prefix="/custom/production-spots-trends"
)

REPORT_KEY = "production-spots-trends"

# April 2026 is the first month with no frozen-feed overlap. See the docstring.
DATA_FLOOR = date(2026, 4, 1)
YEAR_END = date(2026, 12, 31)

# Frozen one-time imports from express_module_prod. Excluded as a NOT-IN so a
# new *live* feed is included automatically rather than silently dropped.
FROZEN_SOURCES = ("legacy_hd", "legacy")

# Outcome maturity. Manual settles at the 30-day age-off; HD's ACCEPT resolves
# between day 7 and day 10. One conservative horizon covers both.
MATURITY_DAYS = 30
HD_MATURITY_DAYS = 10

# The 3-day sync outage — any window containing it is partial.
OUTAGE_START = date(2026, 7, 17)
OUTAGE_END = date(2026, 7, 20)

# Before this date the external-portal agent recorded no wins at all.
BOT_OUTCOMES_FROM = date(2026, 9, 21)

# Payload caps. Both named even though only one is a display width today (§94):
# a fetch width and a display width that happen to be equal still deserve two
# names, or the next person widens one and silently widens the population.
MAX_TREND_BUCKETS = 400
MAX_BREAKDOWN_ROWS = 200

CHANNELS = ("HD Board", "Manual", "Autobot")
EQUIP_GROUPS = ("Van", "Reefer", "Flatbed", "Other")
DIVISIONS = ("DFW", "CORP", "(Unmapped)")
GRAINS = ("day", "week", "month")
BREAKDOWN_DIMS = ("channel", "customer", "actor", "equipment", "division")

UNASSIGNED = "(Unassigned)"

# --------------------------------------------------------------------------
# SQL fragments — one definition each, shared by every query (§16, §69)
# --------------------------------------------------------------------------

# Normalised status. Always UPPER/BTRIM: mixed case once turned $3.34M into
# $546K in the quoting portal, and the absence of variants today is not a
# contract.
_ST_SQL = "UPPER(BTRIM(COALESCE(award_status, '')))"

# "We put a number on it." The quoting portal's Spot Desk uses exactly this;
# HD Spot uses `buy_rate IS NOT NULL` instead and the two differ on ~1.5% of HD
# rows (284 priced with no buy rate). The Sources tab prints both so the gap is
# visible rather than argued about.
_PRICED_SQL = "(price IS NOT NULL AND price <> 0)"

_PROFIT_SQL = (
    "(COALESCE(price, 0) - COALESCE(accessorials, 0) - COALESCE(buy_rate, 0))"
)
_PROFIT_KNOWN_SQL = "(price IS NOT NULL AND buy_rate IS NOT NULL)"

_CHANNEL_SQL = """
    CASE WHEN source = 'homedepot'         THEN 'HD Board'
         WHEN created_by LIKE 'agent:%'   THEN 'Autobot'
         ELSE 'Manual' END
"""

# The bot is `agent:ops-external-spots` — one actor string for all four portal
# agents. The literal "AUTOBOT" appears nowhere in any identity column, so a
# search for it finds nothing and reports "no bot activity". HD carries no actor
# at all (100% NULL): that is a machine feed, not an unknown human.
_ACTOR_SQL = """
    CASE WHEN created_by LIKE 'agent:%'              THEN 'AUTO-BOT'
         WHEN source = 'homedepot'                    THEN 'HD Auto-pricer'
         WHEN COALESCE(BTRIM(created_by), '') = ''    THEN '(Unassigned)'
         ELSE split_part(created_by, '@', 1) END
"""

# REEFER must be tested before VAN — 'DRY_VAN' contains VAN and so would a
# careless reefer arm. 'Other' is a catch-all so no row can fall out of the
# universe just because a feed invented a new label.
_EQUIP_SQL = """
    CASE WHEN equipment ILIKE '%FLAT%'  THEN 'Flatbed'
         WHEN equipment ILIKE '%REEF%'  THEN 'Reefer'
         WHEN equipment ILIKE '%VAN%'   THEN 'Van'
         ELSE 'Other' END
"""

# `division_v2` is the clean, fully backfilled split (0 nulls in every month
# since 2025-08). The raw `division` column holds 'DFW - Pricing' / 'DFW - OPS'
# and `division = 'DFW'` matches ZERO rows there.
_DIVISION_SQL = """
    CASE WHEN UPPER(BTRIM(COALESCE(division_v2, ''))) = 'CORP'      THEN 'CORP'
         WHEN UPPER(BTRIM(COALESCE(division_v2, ''))) LIKE 'DFW%'  THEN 'DFW'
         ELSE '(Unmapped)' END
"""

# 733 rows in 90 days carry no customer, and 11 carry the literal '0'. They are
# 7% of the lane feed's funnel top, so they get a named bucket rather than
# vanishing.
_CUSTOMER_SQL = """
    CASE WHEN COALESCE(BTRIM(express_module_customer_name), '') IN ('', '0')
         THEN '(Unassigned)'
         ELSE BTRIM(express_module_customer_name) END
"""

# Loads behind an award. HD carries `volume_awarded` (populated on exactly its
# won rows); the lane feed does not, so the loads are counted out of
# `order_number`, which can hold several space-separated McLeod ids. A load is a
# run of 5+ digits — naive whitespace splitting overcounted by 2.4% in the
# quoting portal. Counted without a set-returning function: replace each run
# with a sentinel, then measure how much shorter the string gets when the
# sentinel is removed. U+0001 cannot occur in an order number.
_ORDER_COUNT_SQL = r"""
    (
      length(regexp_replace(COALESCE(order_number, ''), '[0-9]{5,}', E'\001', 'g'))
      - length(replace(
          regexp_replace(COALESCE(order_number, ''), '[0-9]{5,}', E'\001', 'g'),
          E'\001', ''))
    )
"""

_AWARDED_COUNT_SQL = f"""
    CASE WHEN source = 'homedepot' THEN COALESCE(volume_awarded, 0)
         ELSE {_ORDER_COUNT_SQL} END
"""

# Outcome buckets. Every one carries `priced`, so they partition the quoted set.
_DECIDED_STATUSES = ("WON", "LOST", "DECLINED", "CLOSE AUTO", "LOST-A", "REJECTED")
_ALL_BUCKETED = (
    "", "-", "ACCEPT", "WON", "LOST", "DECLINED", "CLOSE AUTO", "LOST-A",
    "REJECTED", "CANCELED",
)


def _lit_list(values: tuple[str, ...]) -> str:
    """Render a tuple as a SQL IN-list of literals.

    ⚠ A tuple of ONE renders `('X',)` in Python and that is a syntax error in
    SQL, which is why this is a helper and not an f-string `{tuple!r}` (§79).
    """
    return "(" + ", ".join("'" + v.replace("'", "''") + "'" for v in values) + ")"


# (name, aggregate, row-level condition or None)
_MEASURES: list[tuple[str, str, Optional[str]]] = [
    ("presented", "COUNT(*)", None),
    ("volume", "SUM(COALESCE(vol, 0))", None),
    ("quoted", "COUNT(*)", "priced"),
    ("skipped", "COUNT(*)", "NOT priced"),
    ("open", "COUNT(*)", "priced AND st IN ('', '-')"),
    ("accept", "COUNT(*)", "priced AND st = 'ACCEPT'"),
    ("won", "COUNT(*)", "priced AND st = 'WON'"),
    ("lost", "COUNT(*)", "priced AND st IN ('LOST', 'DECLINED', 'CLOSE AUTO')"),
    ("no_reply", "COUNT(*)", "priced AND st = 'LOST-A'"),
    ("rejected", "COUNT(*)", "priced AND st = 'REJECTED'"),
    ("cancelled", "COUNT(*)", "priced AND st = 'CANCELED'"),
    ("other_outcome", "COUNT(*)", f"priced AND st NOT IN {_lit_list(_ALL_BUCKETED)}"),
    ("potential_revenue", "SUM(price)", "priced"),
    ("awarded_revenue", "SUM(price)", "priced AND st = 'WON'"),
    ("awarded_rev_known", "SUM(price)", "priced AND st = 'WON' AND profit_known"),
    ("awarded_profit", "SUM(profit)", "priced AND st = 'WON' AND profit_known"),
    ("awarded_profit_n", "COUNT(*)", "priced AND st = 'WON' AND profit_known"),
    ("loads_won", "SUM(awarded_count)", "priced AND st = 'WON'"),
]

_MEASURE_NAMES = tuple(m[0] for m in _MEASURES)


def _measure_sql(prefix: str = "", window: Optional[str] = None) -> str:
    """Render every measure, optionally scoped to a window predicate.

    One generator so a window can never carry a different measure set than the
    window beside it — the failure mode is two tiles that look comparable and
    are not.
    """
    out = []
    for name, agg, cond in _MEASURES:
        parts = [p for p in (window, cond) if p]
        expr = f"{agg} FILTER (WHERE {' AND '.join(parts)})" if parts else agg
        out.append(f"{expr} AS {prefix}{name}")
    return ",\n       ".join(out)


# --------------------------------------------------------------------------
# date helpers — cst_today(), never date.today() (§2)
# --------------------------------------------------------------------------


def _clamp(d: Optional[date], default: date) -> date:
    if d is None:
        return default
    return max(DATA_FLOOR, min(YEAR_END, d))


def _month_bounds(d: date) -> tuple[date, date]:
    return d.replace(day=1), d.replace(day=monthrange(d.year, d.month)[1])


def _week_start(d: date) -> date:
    """Monday of d's week. The Ops Portal anchors on Monday too; the Booker
    Rank tab's Sat-Fri week is specific to that tab and does not apply here."""
    return d - timedelta(days=d.weekday())


def _business_days(start: date, end: date) -> int:
    """Mon-Fri days in [start, end].

    Mon-Fri, NOT the Ops Portal's Mon-Sat: HD posts exactly zero rows at
    weekends and the lane feed a trickle — 111 of 20,004 rows over 8 weeks.
    Dividing by a Saturday nobody works understates the daily run rate by ~17%.
    """
    if end < start:
        return 0
    n = 0
    d = start
    while d <= end:
        if d.weekday() < 5:
            n += 1
        d += timedelta(days=1)
    return n


def _nth_business_day(month_start: date, n: int) -> date:
    """The date of the n-th Mon-Fri day of that month, clamped to month end."""
    _, last = _month_bounds(month_start)
    if n <= 0:
        return month_start
    seen = 0
    d = month_start
    while d <= last:
        if d.weekday() < 5:
            seen += 1
            if seen >= n:
                return d
        d += timedelta(days=1)
    return last


def _resolve_range(
    rng: Optional[str],
    start_date: Optional[date],
    end_date: Optional[date],
) -> tuple[date, date]:
    """The filter bar's window. MTD is the default."""
    today = cst_today()
    t = max(DATA_FLOOR, min(YEAR_END, today))
    if rng == "today":
        return t, t
    if rng == "yesterday":
        y = _clamp(t - timedelta(days=1), DATA_FLOOR)
        return y, y
    if rng == "wtd":
        return _clamp(_week_start(t), DATA_FLOOR), t
    if rng == "last7":
        return _clamp(t - timedelta(days=6), DATA_FLOOR), t
    if rng == "last30":
        return _clamp(t - timedelta(days=29), DATA_FLOOR), t
    if rng == "last90":
        return _clamp(t - timedelta(days=89), DATA_FLOOR), t
    if rng == "last_month":
        prev_start, prev_end = _month_bounds(t.replace(day=1) - timedelta(days=1))
        return _clamp(prev_start, DATA_FLOOR), _clamp(prev_end, YEAR_END)
    if rng == "qtd":
        q_first_month = 3 * ((t.month - 1) // 3) + 1
        return _clamp(date(t.year, q_first_month, 1), DATA_FLOOR), t
    if rng == "ytd":
        return _clamp(date(t.year, 1, 1), DATA_FLOOR), t
    if rng == "custom":
        s = _clamp(start_date, DATA_FLOOR)
        e = _clamp(end_date, YEAR_END)
        if e < s:
            s, e = e, s
        return s, e
    return _clamp(t.replace(day=1), DATA_FLOOR), t  # mtd


def _comparison_windows(today: date, rng: tuple[date, date]) -> dict[str, Any]:
    """Every window the summary compares, plus the projection arithmetic.

    Activity windows are aligned by ELAPSED BUSINESS DAYS, not by calendar day:
    Wednesday is the volume peak (5,025 rows over 8 weeks against Friday's
    3,296), so "the 21st vs the 21st" compares a Monday with a Thursday and
    calls the difference performance.

    Outcome windows are the last SETTLED periods — a period whose end is at
    least MATURITY_DAYS old. Comparing this week's win rate with last week's
    would compare a 2-day-old cohort with a 9-day-old one, and HD's ACCEPT
    resolves between day 7 and day 10, so the older week would win every time.
    """
    t = max(DATA_FLOOR, min(YEAR_END, today))

    # --- week to date vs the same elapsed weekdays last week ---------------
    wk = _week_start(t)
    wtd = (wk, t)
    wtd_prev = (wk - timedelta(days=7), t - timedelta(days=7))

    # --- month to date vs the same business-day ordinal last month ---------
    m_start, m_end = _month_bounds(t)
    bd_elapsed = _business_days(m_start, t)
    bd_total = _business_days(m_start, m_end)
    mtd = (m_start, t)

    lm_start, lm_end = _month_bounds(m_start - timedelta(days=1))
    mtd_prev = (lm_start, _nth_business_day(lm_start, bd_elapsed))
    lm_full = (lm_start, lm_end)

    # --- settled outcome windows -------------------------------------------
    cutoff = t - timedelta(days=MATURITY_DAYS)
    # the most recent Mon-Sun week that ended on or before the cutoff
    s_week_end = _week_start(cutoff) - timedelta(days=1)
    s_week = (s_week_end - timedelta(days=6), s_week_end)
    s_week_prev = (s_week[0] - timedelta(days=7), s_week[0] - timedelta(days=1))

    # the most recent complete calendar month that ended on or before the cutoff
    anchor = cutoff.replace(day=1) - timedelta(days=1)
    s_month = _month_bounds(anchor)
    s_month_prev = _month_bounds(s_month[0] - timedelta(days=1))

    return {
        "windows": {
            "range": rng,
            "wtd": wtd,
            "wtd_prev": wtd_prev,
            "mtd": mtd,
            "mtd_prev": mtd_prev,
            "lm_full": lm_full,
            "settled_week": s_week,
            "settled_week_prev": s_week_prev,
            "settled_month": s_month,
            "settled_month_prev": s_month_prev,
        },
        "bd_elapsed": bd_elapsed,
        "bd_total": bd_total,
        "bd_last_month": _business_days(*lm_full),
    }


def _rate(num: Optional[float], den: Optional[float]) -> Optional[float]:
    """Recompute a rate from its components.

    ``den > 0``, never ``not den``: a zero denominator is not the hazard, a
    negative one is — it renders a percentage in the millions rather than a
    blank.
    """
    if num is None or den is None or float(den) <= 0:
        return None
    return float(num) / float(den)


def _f(v: Any) -> float:
    return float(v or 0)


def _blank() -> dict[str, float]:
    return {name: 0.0 for name in _MEASURE_NAMES}


def _derive(b: dict) -> dict:
    """Attach every rate, recomputed from components — never averaged."""
    out = {k: (_f(v) if k in _MEASURE_NAMES else v) for k, v in b.items()}
    presented = out.get("presented", 0.0)
    quoted = out.get("quoted", 0.0)
    decided = (
        out.get("won", 0.0)
        + out.get("lost", 0.0)
        + out.get("no_reply", 0.0)
        + out.get("rejected", 0.0)
    )
    out["decided"] = decided
    out["in_play"] = out.get("open", 0.0) + out.get("accept", 0.0)
    out["quote_rate"] = _rate(quoted, presented)
    out["skip_rate"] = _rate(out.get("skipped"), presented)
    out["win_rate"] = _rate(out.get("won"), decided)
    out["no_reply_rate"] = _rate(out.get("no_reply"), decided)
    out["reject_rate"] = _rate(out.get("lost", 0.0) + out.get("rejected", 0.0), decided)
    out["hit_rate"] = _rate(out.get("won"), presented)
    out["in_play_share"] = _rate(out["in_play"], quoted)
    # §96: the profit numerator spans only rows where BOTH legs are known, so
    # its denominator must span the same rows. Dividing by `awarded_revenue`
    # (every won row) would flatter the margin and nobody would notice.
    out["awarded_margin"] = _rate(out.get("awarded_profit"), out.get("awarded_rev_known"))
    out["avg_award_price"] = _rate(out.get("awarded_revenue"), out.get("won"))
    out["avg_quote_price"] = _rate(out.get("potential_revenue"), quoted)
    return out


def _delta(cur: Optional[float], prev: Optional[float]) -> dict[str, Optional[float]]:
    """Absolute and relative change. A change FROM zero has no percentage —
    returning 0 or 100% there is the lie that makes a launch look flat."""
    if cur is None or prev is None:
        return {"abs": None, "pct": None}
    d = float(cur) - float(prev)
    return {"abs": d, "pct": (d / float(prev)) if float(prev) != 0 else None}


# --------------------------------------------------------------------------
# query builders
# --------------------------------------------------------------------------


def _parse_multi(raw: Optional[list[str]]) -> list[str]:
    """Repeated query params -> clean list.

    NEVER ``.split(",")``: repeated keys travel as repeated params, the proxy
    preserves them with ``.append()``, and customer names contain commas (§45).
    """
    if not raw:
        return []
    seen: set[str] = set()
    out: list[str] = []
    for v in raw:
        v = (v or "").strip()
        if v and v not in seen:
            seen.add(v)
            out.append(v)
    return out


def _base_cte(params: list, start: date, end: date, f: dict) -> str:
    """The ONE scope definition. Every panel on this page is built from it, so a
    drill can never apply a different scope than the KPI it was clicked from
    (§16) — and the dimension filters cannot be forgotten on one endpoint.
    """
    params.append(start)
    lo = f"${len(params)}"
    params.append(end)
    hi = f"${len(params)}"
    params.append(list(FROZEN_SOURCES))
    frozen = f"${len(params)}"

    extra = ""
    for key, sql in (
        ("channels", _CHANNEL_SQL),
        ("customers", _CUSTOMER_SQL),
        ("actors", _ACTOR_SQL),
        ("equipment", _EQUIP_SQL),
        ("divisions", _DIVISION_SQL),
    ):
        vals = f.get(key) or []
        if vals:
            params.append(list(vals))
            extra += f"\n          AND ({sql.strip()}) = ANY(${len(params)}::text[])"

    return f"""
    WITH base AS (
      SELECT (price_date AT TIME ZONE 'America/Chicago')::date AS d,
             {_ST_SQL}          AS st,
             {_PRICED_SQL}      AS priced,
             {_PROFIT_KNOWN_SQL} AS profit_known,
             {_PROFIT_SQL}      AS profit,
             price,
             volume             AS vol,
             {_AWARDED_COUNT_SQL.strip()} AS awarded_count,
             ({_CHANNEL_SQL.strip()})   AS channel,
             ({_CUSTOMER_SQL.strip()})  AS customer,
             ({_ACTOR_SQL.strip()})     AS actor,
             ({_EQUIP_SQL.strip()})     AS equipment,
             ({_DIVISION_SQL.strip()})  AS division
      FROM spot_report_condensed
      -- Parameter-side AT TIME ZONE keeps idx_..._price_date usable AND is
      -- DST-correct; the upper bound is exclusive-next-day so the last day is
      -- whole. Measured 36.7ms -> 2.5ms on this table (§64).
      --
      -- 🔴 The `::timestamp` step is LOAD-BEARING, not tidying. `$1::date AT
      -- TIME ZONE 'America/Chicago'` does NOT mean "midnight in Chicago": for a
      -- `date` input Postgres resolves the cast to timestamptz FIRST, so the
      -- expression is (midnight UTC) RENDERED in Chicago and its type is
      -- `timestamp WITHOUT time zone` — 2026-06-23 19:00, which then compares
      -- back as GMT. The window silently starts 10 hours early. Measured on
      -- this table 2026-09-21: it pulls 77 extra rows into a 90-day window, and
      -- on HD Spot's September MTD it counts 5,051 Home Depot rows where the
      -- true CST month holds 4,978 — 73 rows belonging to the evening of
      -- 31 Aug. With `::timestamp` the naive midnight is interpreted AS Chicago
      -- and the result is a true timestamptz (2026-06-24 05:00+00), which
      -- matches `(price_date AT TIME ZONE 'America/Chicago')::date BETWEEN s
      -- AND e` to the row while staying sargable.
      WHERE price_date >= ({lo}::date::timestamp AT TIME ZONE 'America/Chicago')
        AND price_date <  (({hi}::date + 1)::timestamp AT TIME ZONE 'America/Chicago')
        AND (source IS NULL OR source <> ALL({frozen}::text[])){extra}
    )
    """


async def _fetch_summary(pool, windows: dict, f: dict) -> dict[str, dict]:
    """Every window from ONE day-grain scan, folded in Python.

    The obvious shape — one FILTER predicate per window in the SELECT list — is
    correct but 180 aggregate expressions wide, and measured **6.4 s** over four
    months on this table. Aggregating to days once and summing the days each
    window needs is **0.8 s** for the same answer, holds the small, HD-Spot-
    shared pricing pool for a fraction as long, and has a second virtue: the
    summary and the day-grain `/trend` series are then literally the same
    numbers, so a KPI tile can never drift from the chart under it.

    Windows overlap on purpose (week-to-date sits inside month-to-date), which
    is exactly why they are folded rather than grouped.
    """
    lo = max(DATA_FLOOR, min(w[0] for w in windows.values()))
    hi = max(w[1] for w in windows.values())
    params: list = []
    cte = _base_cte(params, lo, hi, f)
    sql = cte + f"SELECT d,\n       {_measure_sql()}\n    FROM base\n    GROUP BY 1"

    async with pool.acquire() as conn:
        rows = await conn.fetch(sql, *params)
    by_day = {r["d"]: r for r in rows}

    out: dict[str, dict] = {}
    for tag, (s, e) in windows.items():
        acc = _blank()
        d = s
        while d <= e:
            r = by_day.get(d)
            if r is not None:
                for name in _MEASURE_NAMES:
                    acc[name] += _f(r[name])
            d += timedelta(days=1)
        out[tag] = _derive(acc)
    return out


_GRAIN_TRUNC = {"day": "day", "week": "week", "month": "month"}


async def _fetch_trend(pool, start: date, end: date, grain: str, f: dict):
    params: list = []
    cte = _base_cte(params, start, end, f)
    trunc = _GRAIN_TRUNC[grain]
    sql = (
        cte
        + f"""
    SELECT date_trunc('{trunc}', d)::date AS bucket,
           {_measure_sql()}
    FROM base
    GROUP BY 1
    ORDER BY 1
    """
    )
    async with pool.acquire() as conn:
        return await conn.fetch(sql, *params)


async def _fetch_breakdown(pool, start: date, end: date, dim: str, f: dict):
    params: list = []
    cte = _base_cte(params, start, end, f)
    sql = (
        cte
        + f"""
    SELECT {dim} AS label,
           {_measure_sql()}
    FROM base
    GROUP BY 1
    """
    )
    async with pool.acquire() as conn:
        return await conn.fetch(sql, *params)


# --------------------------------------------------------------------------
# dense series
# --------------------------------------------------------------------------


def _bucket_starts(start: date, end: date, grain: str) -> list[date]:
    out: list[date] = []
    if grain == "day":
        d = start
        while d <= end and len(out) < MAX_TREND_BUCKETS:
            out.append(d)
            d += timedelta(days=1)
    elif grain == "week":
        d = _week_start(start)
        while d <= end and len(out) < MAX_TREND_BUCKETS:
            out.append(d)
            d += timedelta(days=7)
    else:
        d = start.replace(day=1)
        while d <= end and len(out) < MAX_TREND_BUCKETS:
            out.append(d)
            d = (d.replace(day=monthrange(d.year, d.month)[1]) + timedelta(days=1))
    return out


def _bucket_end(bucket: date, grain: str) -> date:
    if grain == "day":
        return bucket
    if grain == "week":
        return bucket + timedelta(days=6)
    return bucket.replace(day=monthrange(bucket.year, bucket.month)[1])


# --------------------------------------------------------------------------
# endpoints
# --------------------------------------------------------------------------
#
# Sibling endpoints on one screen MUST declare the same params — FastAPI
# silently DROPS an undeclared query param, so a card would scope while the
# chart beside it did not (§55). One `_common` dependency makes that structural
# instead of a review item.


def _common(
    range: Optional[str] = Query("mtd"),
    start_date: Optional[date] = Query(None),
    end_date: Optional[date] = Query(None),
    channel: Optional[list[str]] = Query(None),
    customer: Optional[list[str]] = Query(None),
    actor: Optional[list[str]] = Query(None),
    equipment: Optional[list[str]] = Query(None),
    division: Optional[list[str]] = Query(None),
):
    s, e = _resolve_range(range, start_date, end_date)
    return {
        "start": s,
        "end": e,
        "channels": _parse_multi(channel),
        "customers": _parse_multi(customer),
        "actors": _parse_multi(actor),
        "equipment": _parse_multi(equipment),
        "divisions": _parse_multi(division),
    }


def _window_meta(s: date, e: date) -> dict:
    return {
        "start": s.isoformat(),
        "end": e.isoformat(),
        "business_days": _business_days(s, e),
        "settled": e <= cst_today() - timedelta(days=MATURITY_DAYS),
        "covers_outage": s <= OUTAGE_END and e >= OUTAGE_START,
    }


@router.get("/filters")
async def filters(
    request: Request,
    _user: dict = Depends(require_report_access(REPORT_KEY)),
):
    """Filter options. Customers and actors come from the live data, not a
    hand-kept list — a whitelist that outlives its data advertises dead keys."""
    customers: list[str] = []
    actors: list[str] = []
    try:
        pool = get_pricing_pool(request)
        params: list = []
        today = cst_today()
        cte = _base_cte(params, max(DATA_FLOOR, today - timedelta(days=180)), today, {})
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                cte
                + """
            SELECT 'customer' AS kind, customer AS v, COUNT(*) AS n FROM base GROUP BY 2
            UNION ALL
            SELECT 'actor', actor, COUNT(*) FROM base GROUP BY 2
            ORDER BY 1, 3 DESC
            """,
                *params,
            )
        customers = [r["v"] for r in rows if r["kind"] == "customer" and r["v"]]
        actors = [r["v"] for r in rows if r["kind"] == "actor" and r["v"]]
    except Exception as e:  # options are a convenience, never a blocker
        logger.warning("Production SPOTS Trends: filter options unavailable (%s)", e)

    return {
        "success": True,
        "data": {
            "channels": list(CHANNELS),
            "equipment": list(EQUIP_GROUPS),
            "divisions": list(DIVISIONS),
            "customers": customers,
            "actors": actors,
            "data_floor": DATA_FLOOR.isoformat(),
            "year_end": YEAR_END.isoformat(),
            "maturity_days": MATURITY_DAYS,
            "hd_maturity_days": HD_MATURITY_DAYS,
            "outage": {
                "start": OUTAGE_START.isoformat(),
                "end": OUTAGE_END.isoformat(),
            },
            "bot_outcomes_from": BOT_OUTCOMES_FROM.isoformat(),
        },
    }


@router.get("/summary")
async def summary(
    request: Request,
    f: dict = Depends(_common),
    _user: dict = Depends(require_report_access(REPORT_KEY)),
):
    """Global KPIs, the funnel, the comparatives and the month projection.

    Reconciles with `/trend` and `/breakdown` because all three are built from
    `_base_cte` — the funnel tiles here sum to Presented exactly, and the
    Channels tab's rows sum to these totals.
    """
    pool = get_pricing_pool(request)
    today = cst_today()
    meta = _comparison_windows(today, (f["start"], f["end"]))
    data = await _fetch_summary(pool, meta["windows"], f)

    def cmp_block(cur: str, prev: str, keys: tuple[str, ...]) -> dict:
        return {
            "current": data[cur],
            "previous": data[prev],
            "window": _window_meta(*meta["windows"][cur]),
            "previous_window": _window_meta(*meta["windows"][prev]),
            "deltas": {k: _delta(data[cur].get(k), data[prev].get(k)) for k in keys},
        }

    activity = ("presented", "quoted", "skipped", "quote_rate", "potential_revenue")
    outcome = ("won", "win_rate", "no_reply_rate", "awarded_revenue", "awarded_margin")

    # Projection: MTD run rate over ELAPSED business days, extended over the
    # month's business days. Not calendar days — the weekend is structurally
    # empty here, so a calendar divisor understates every projection.
    bd_elapsed = meta["bd_elapsed"]
    bd_total = meta["bd_total"]
    mtd = data["mtd"]
    projection = {}
    for key in ("presented", "quoted", "won", "potential_revenue", "awarded_revenue"):
        rate_per_day = _rate(mtd.get(key), bd_elapsed)
        projected = None if rate_per_day is None else rate_per_day * bd_total
        projection[key] = {
            "mtd": mtd.get(key),
            "projected": projected,
            "last_month": data["lm_full"].get(key),
            "vs_last_month": _delta(projected, data["lm_full"].get(key)),
        }

    return {
        "success": True,
        "data": {
            "range": data["range"],
            "range_window": _window_meta(f["start"], f["end"]),
            "week": cmp_block("wtd", "wtd_prev", activity),
            "month": cmp_block("mtd", "mtd_prev", activity),
            "settled_week": cmp_block("settled_week", "settled_week_prev", outcome),
            "settled_month": cmp_block("settled_month", "settled_month_prev", outcome),
            "projection": {
                **projection,
                "business_days_elapsed": bd_elapsed,
                "business_days_total": bd_total,
                "business_days_last_month": meta["bd_last_month"],
                "pace": _rate(bd_elapsed, bd_total),
            },
            "maturity_days": MATURITY_DAYS,
            "hd_maturity_days": HD_MATURITY_DAYS,
        },
    }


@router.get("/trend")
async def trend(
    request: Request,
    grain: str = Query("day", pattern="^(day|week|month)$"),
    f: dict = Depends(_common),
    _user: dict = Depends(require_report_access(REPORT_KEY)),
):
    """A dense, zero-filled series — one bucket per period, gaps included.

    The series is whole and the frontend's brush windows it (§70/§97): a gap
    dropped here becomes a chart that silently closes over a dead day, which is
    exactly how the July outage went unnoticed for three days.

    Each bucket carries `provisional`: its outcomes have not finished settling,
    so its win rate is structurally understated and the chart shades it.
    """
    pool = get_pricing_pool(request)
    rows = await _fetch_trend(pool, f["start"], f["end"], grain, f)
    by_bucket = {r["bucket"]: r for r in rows}
    cutoff = cst_today() - timedelta(days=MATURITY_DAYS)

    series = []
    for b in _bucket_starts(f["start"], f["end"], grain):
        r = by_bucket.get(b)
        bucket = {n: _f(r[n]) if r is not None else 0.0 for n in _MEASURE_NAMES}
        end = _bucket_end(b, grain)
        series.append(
            {
                "bucket": b.isoformat(),
                "bucket_end": end.isoformat(),
                "provisional": end > cutoff,
                "covers_outage": b <= OUTAGE_END and end >= OUTAGE_START,
                **_derive(bucket),
            }
        )
    return {
        "success": True,
        "data": series,
        "meta": {"total": len(series), "grain": grain, "maturity_days": MATURITY_DAYS},
    }


_SORTS = (
    "label_asc",
    "label_desc",
    "presented_desc",
    "presented_asc",
    "quoted_desc",
    "quoted_asc",
    "skipped_desc",
    "won_desc",
    "won_asc",
    "no_reply_desc",
    "quote_rate_desc",
    "quote_rate_asc",
    "win_rate_desc",
    "win_rate_asc",
    "awarded_revenue_desc",
    "awarded_revenue_asc",
    "awarded_margin_desc",
    "awarded_margin_asc",
)

# Below this many decided quotes a win rate is noise, so it is rendered "—"
# rather than a headline 100% off a single award. Null sorts last in BOTH
# directions in the table component, so a suppressed rate cannot lead a board
# it has no claim to (§104).
MIN_DECIDED_FOR_RATE = 10


@router.get("/breakdown")
async def breakdown(
    request: Request,
    dim: str = Query("channel"),
    sort: str = Query("presented_desc"),
    f: dict = Depends(_common),
    _user: dict = Depends(require_report_access(REPORT_KEY)),
):
    """One row per dimension value, with the previous equal-length window's
    deltas, plus a Totals row aggregated server-side over the FULL universe —
    never a client reduce of the visible page (§44)."""
    if dim not in BREAKDOWN_DIMS:
        raise HTTPException(
            status_code=400, detail=f"dim must be one of: {', '.join(BREAKDOWN_DIMS)}"
        )
    # ⚠ An unknown sort token is a 400, NOT a silent fall back to the default: a
    # table ordered by something other than the header it advertises fails
    # nothing and is believed.
    if sort not in _SORTS:
        raise HTTPException(
            status_code=400, detail=f"sort must be one of: {', '.join(sorted(_SORTS))}"
        )

    pool = get_pricing_pool(request)
    span = (f["end"] - f["start"]).days + 1
    prev_end = f["start"] - timedelta(days=1)
    prev_start = max(DATA_FLOOR, prev_end - timedelta(days=span - 1))

    cur_rows, prev_rows = await asyncio.gather(
        _fetch_breakdown(pool, f["start"], f["end"], dim, f),
        _fetch_breakdown(pool, prev_start, prev_end, dim, f),
    )
    prev_by = {r["label"]: r for r in prev_rows}

    rows = []
    totals = _blank()
    for r in cur_rows:
        bucket = {n: _f(r[n]) for n in _MEASURE_NAMES}
        for n in _MEASURE_NAMES:
            totals[n] += bucket[n]
        cur = _derive(bucket)
        p = prev_by.get(r["label"])
        prev = _derive({n: _f(p[n]) for n in _MEASURE_NAMES}) if p is not None else None
        if cur["decided"] < MIN_DECIDED_FOR_RATE:
            cur["win_rate"] = None
            cur["no_reply_rate"] = None
            cur["reject_rate"] = None
        rows.append(
            {
                "label": r["label"],
                **cur,
                "prev_presented": prev["presented"] if prev else None,
                "delta_presented": _delta(
                    cur["presented"], prev["presented"] if prev else None
                ),
                "delta_win_rate": _delta(
                    cur["win_rate"], prev["win_rate"] if prev else None
                ),
            }
        )

    key, _, direction = sort.rpartition("_")
    # Nulls last in BOTH directions. A `reverse=` over an (is_none, value) key
    # puts them FIRST on desc, so a rate suppressed for a small sample would
    # head the very table it has no claim to (§104).
    known = [r for r in rows if r.get(key) is not None]
    unknown = [r for r in rows if r.get(key) is None]
    known.sort(key=lambda r: r[key], reverse=(direction == "desc"))
    rows = (known + unknown)[:MAX_BREAKDOWN_ROWS]

    return {
        "success": True,
        "data": {
            "rows": rows,
            "totals": _derive(totals),
            "dim": dim,
            "sort": sort,
            "previous_window": _window_meta(prev_start, prev_end),
            "min_decided_for_rate": MIN_DECIDED_FOR_RATE,
        },
        "meta": {"total": len(rows)},
    }


@router.get("/actuals")
async def actuals(
    request: Request,
    grain: str = Query("month", pattern="^(day|week|month)$"),
    f: dict = Depends(_common),
    _user: dict = Depends(require_report_access(REPORT_KEY)),
):
    """What actually MOVED — the other population, from the gold datalake.

    ⚠ This is deliberately NOT reconcilable with the funnel above, and the UI
    says so. The funnel is quoting activity bucketed on ``price_date``; this is
    ``mcleod_gld_budget_report_v4 WHERE contract_type_descr = 'SPOT'`` bucketed
    on ``origin_actual_departure``. A lost bid never becomes a McLeod load, so
    "conversion" measured here would be a flawless, wrong 100%.

    Fails SOFT: the funnel is the report, this is the appendix. Gold down
    returns ``available: false`` and nulls — never ``{}``, which renders as a
    real zero, and never a 503, which would blank a page that is mostly fine.
    """
    trunc = _GRAIN_TRUNC[grain]
    try:
        gold = get_datalake_gold_pool(request)
        async with gold.acquire() as conn:
            rows = await conn.fetch(
                f"""
                SELECT date_trunc('{trunc}', origin_actual_departure)::date AS bucket,
                       COUNT(DISTINCT TRIM(id))  AS loads,
                       SUM(total_charge)         AS revenue,
                       SUM(margin_amt)           AS profit
                FROM mcleod_gld_budget_report_v4
                WHERE contract_type_descr = 'SPOT'
                  -- The DATA_HANDBOOK rule: zero-revenue rows skew every
                  -- average. And the ETL writes a 1900-01-01 sentinel for an
                  -- unknown departure, which would bucket into a phantom month.
                  AND total_charge <> 0
                  AND status IN ('D', 'P')
                  AND origin_actual_departure IS NOT NULL
                  AND origin_actual_departure > DATE '1900-01-02'
                  AND origin_actual_departure >= $1::date
                  AND origin_actual_departure < ($2::date + INTERVAL '1 day')
                GROUP BY 1
                ORDER BY 1
                """,
                f["start"],
                f["end"],
            )
    except Exception as e:  # fail soft — never {} , never a 503
        logger.warning("Production SPOTS Trends: actuals unavailable (%s)", e)
        return {
            "success": True,
            "data": {"available": False, "series": [], "totals": None},
        }

    series = [
        {
            "bucket": r["bucket"].isoformat(),
            "loads": int(r["loads"] or 0),
            "revenue": _f(r["revenue"]),
            "profit": _f(r["profit"]),
            "margin": _rate(_f(r["profit"]), _f(r["revenue"])),
        }
        for r in rows
    ]
    tot_rev = sum(s["revenue"] for s in series)
    tot_prof = sum(s["profit"] for s in series)
    return {
        "success": True,
        "data": {
            "available": True,
            "series": series,
            "totals": {
                "loads": sum(s["loads"] for s in series),
                "revenue": tot_rev,
                "profit": tot_prof,
                # A rate over the totals, never the mean of the per-bucket rates
                # (§44): two months at 99% and 50% do not average to 74.5%.
                "margin": _rate(tot_prof, tot_rev),
            },
        },
        "meta": {"total": len(series), "grain": grain},
    }


@router.get("/freshness")
async def freshness(
    request: Request,
    _user: dict = Depends(require_report_access(REPORT_KEY)),
):
    """"Data as of", per feed, plus the stalest reading (§54).

    The sync cron runs every 30 min, so >90 minutes without an update is two
    missed runs. That threshold is the only reason the July 3-day outage became
    visible at all — until then the page rendered confident zeros. A feed with
    no timestamp is DEAD, not skippable, and a failed call renders
    "unavailable", never blank.

    ``updated_at`` is the heartbeat and only the heartbeat: the sync re-upserts
    every row each run, so it is meaningless per row but perfect here.
    """
    out: dict[str, Any] = {
        "feeds": [],
        "spot": None,
        "gold": None,
        "stale_minutes": None,
        "is_stale": False,
    }
    try:
        pool = get_pricing_pool(request)
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT source,
                       MAX(updated_at)  AS heartbeat,
                       MAX(price_date)  AS last_event,
                       EXTRACT(EPOCH FROM (now() - MAX(updated_at))) / 60 AS mins
                FROM spot_report_condensed
                WHERE source <> ALL($1::text[])
                GROUP BY 1
                ORDER BY 1
                """,
                list(FROZEN_SOURCES),
            )
        feeds = []
        for r in rows:
            mins = float(r["mins"]) if r["mins"] is not None else None
            feeds.append(
                {
                    "source": r["source"],
                    "heartbeat": r["heartbeat"].isoformat() if r["heartbeat"] else None,
                    "last_event": (
                        r["last_event"].isoformat() if r["last_event"] else None
                    ),
                    "stale_minutes": mins,
                    "is_stale": mins is None or mins > 90,
                }
            )
        out["feeds"] = feeds
        if feeds:
            # The STALEST feed is the report's freshness — an average would hide
            # one dead pipeline behind one healthy one.
            worst = max(feeds, key=lambda x: (x["stale_minutes"] is None, x["stale_minutes"] or 0))
            out["spot"] = worst["heartbeat"]
            out["stale_minutes"] = worst["stale_minutes"]
            out["is_stale"] = worst["is_stale"]
    except Exception as e:
        logger.warning("Production SPOTS Trends freshness (spot) failed: %s", e)

    try:
        gold = get_datalake_gold_pool(request)
        async with gold.acquire() as conn:
            ts = await conn.fetchval(
                "SELECT MAX(ordered_date) FROM mcleod_gld_budget_report_v4"
            )
        out["gold"] = ts.isoformat() if ts else None
    except Exception as e:
        logger.warning("Production SPOTS Trends freshness (gold) failed: %s", e)

    return {"success": True, "data": out}
