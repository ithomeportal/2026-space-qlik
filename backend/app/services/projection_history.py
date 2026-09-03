"""Team Monthly Projection — daily history, so the number has a HIGH and a LOW.

Request 2026-08-25 (`Pictures/space-projected profit.txt`): *"what it will be
more useful is to show that section as the stock markets, showing not only the
actual, but for the actual month (always actual month) which was (or is) the
high for the current month, the lowest, and in % the variation. We need to start
tracking this variation by month as well, to have clear the error-rate or
variation we are getting. We need to keep all this weekly values as well for
ever, so we can keep tracking year after year seasonality."*

WHY A TABLE
-----------
``proj_profit`` is computed live from ``mcleod_gld_budget_report_v4`` and moves
every day — measured on the CORP scope for August 2026 it ran from $405,981
(08-02) to $542,601 (08-20), a **33.6%** range. None of that path is visible
anywhere: the page shows one number and the previous ones are gone.

TWO SOURCES, AND THEY ARE NOT THE SAME THING
--------------------------------------------
* ``source='live'`` — written each morning by the scheduler. This is the
  as-OBSERVED value: what the team actually saw that day. It is the truth and
  is never overwritten by a replay.
* ``source='backfill'`` — the formula REPLAYED over history. v4 keeps history
  back to 2020-12, so the whole path can be reconstructed, which is the only
  reason the High/Low and the seasonality answer exist on day one instead of a
  year from now. It is *approximately* what we saw: a load posted late shows up
  in the replay's 12-day window even though it was invisible at the time. Rows
  are labelled so a reader can tell the two apart, and a backfill upserts
  ``ON CONFLICT DO NOTHING`` — it can never clobber an observed row.

⚠ THE REPLAY MUST CLAMP THE MTD UPPER BOUND
-------------------------------------------
``_projection_params`` binds the revenue/profit MTD leg as
``BETWEEN month_start AND month_END`` (the documented vol/rev asymmetry in
``_metrics.py``). Live that is harmless — no rows exist past today, verified
2026-08-25: exactly ONE row table-wide carries a future ``origin_actual_departure``
(2026-09-19) out of 279,671. Replayed at an as-of date inside a CLOSED month it
would sum the WHOLE month, so the "projection" would contain the answer and
every historical point would be wrong in the flattering direction. Hence
``mtd_end``: ``None`` for the live path (identical SQL text AND identical bound
params, so ``tests/test_ops_portal_scope.py``'s byte-identical baseline keeps
its teeth) and the as-of date for a replay.

⚠ ONE DEFINITION OF PROJECTED (§69)
-----------------------------------
The replay SQL below computes only the SIX RAW SUMS. Every arithmetic step —
the ÷12, the × pending, the margin/rev-per-load/utilisation ratios — goes
through ``_projection_from_sums``, the same function the live panel uses. If
this module re-derived the maths there would be two "Projected" formulas again,
which is exactly the defect §69 was written for.

⚠ DAYS 1-4 OF A MONTH ARE NOISE, AND THE HIGH/LOW MUST NOT HIDE IT
------------------------------------------------------------------
On day 1 the MTD leg is ~0 and ``pending`` is the whole month, so the value is
pure extrapolation off a 12-day window that may straddle a holiday. Measured
over 19 closed months: January 2026 opened at $115,707 against a $303,575
outcome — a 62% under-call that on its own produces a 187% "range". The month
stats therefore publish BOTH the full-month range and a ``settled_*`` range
measured from business day 5, and the caller shows the full one with the
settled one beside it.
"""

from __future__ import annotations

import logging
from calendar import monthrange
from datetime import date, timedelta
from typing import Any, Optional, Sequence

from app.clock import cst_today
from app.routers.ops_portal_overview._constants import (
    CORP_COMPANIES,
    CORP_TEAMS,
    DFW_SUB_TEAMS,
    OPEN_STATUSES,
)
from app.routers.ops_portal_overview._dates import _count_workdays, _month_bounds
from app.routers.ops_portal_overview._metrics import (
    _projection_from_sums,
    _safe_float,
    _team_projection_core,
)
from app.routers.ops_portal_overview._scope import CORP_SCOPE, DFW_SCOPE, DivisionScope
from app.routers.ops_portal_overview._sql import _v4_scope_where

logger = logging.getLogger(__name__)

# The scope of the PERFORMANCE CORP digest is FOUR teams, not five — see
# `team_perf_digest.DIGEST_CORP_TEAMS` for why TEAM5 is deliberately excluded.
# Imported lazily-by-value here so this module does not import the digest
# service (which imports the router package, which would be a cycle).
DIGEST_CORP_TEAMS = ("TEAM1", "TEAM2", "TEAM3", "TEAM4")

# `team_key` sentinel meaning "the scope's whole division, unnarrowed".
ALL_TEAMS = "ALL"
# `team_key` for the four-team PERFORMANCE CORP email scope.
DIGEST_KEY = "DIGEST"

# Every (scope_key, team_key) pair we keep history for. Deliberately a fixed,
# small list: the projection panel is also filterable by customer / lane /
# carrier / load type, and snapshotting the cross-product of those is neither
# possible nor meaningful. A filtered panel reports `tracked: false` instead of
# silently comparing a filtered number against unfiltered history.
#
#   corp/ALL     the Ops Portal Overview default + the CEO Cockpit aggregate
#   corp/TEAMn   the four scope-locked CORP clone portals and their e-mails
#   corp/DIGEST  the PERFORMANCE CORP e-mail (TEAM1..TEAM4)
#   dfw/ALL      the Ops Managers Portal DFW default
#   dfw/TMn      the DFW sub-team pills
SNAPSHOT_SCOPES: tuple[tuple[str, str, DivisionScope, tuple[str, ...]], ...] = (
    ("corp", ALL_TEAMS, CORP_SCOPE, ()),
    *tuple((("corp", t, CORP_SCOPE, (t,)) for t in CORP_TEAMS)),
    ("corp", DIGEST_KEY, CORP_SCOPE, DIGEST_CORP_TEAMS),
    ("dfw", ALL_TEAMS, DFW_SCOPE, ()),
    *tuple((("dfw", t, DFW_SCOPE, (t,)) for t in DFW_SUB_TEAMS)),
)

# How far back a first-run backfill reaches. v4 holds 2020-12 onward, but two
# and a half years already answers the seasonality question and keeps the first
# deploy's background task short. `backfill_projection_history` takes an
# explicit start so this is a default, not a limit.
BACKFILL_START = date(2023, 1, 1)

# Business day (Mon-Sat count within the month) from which a month's range is
# considered "settled" — see the module docstring.
SETTLED_FROM_BUSINESS_DAY = 5

# The eleven numeric fields `_projection_from_sums` returns, in column order.
_PROJ_FIELDS: tuple[str, ...] = (
    "avg_vol_day",
    "avg_rev_day",
    "avg_prof_day",
    "proj_volume",
    "proj_revenue",
    "proj_profit",
    "proj_margin_pct",
    "proj_rev_x_l",
    "proj_prof_x_l",
    "proj_team_ut",
)

_WEEK_FIELDS: tuple[str, ...] = (
    "volume",
    "revenue",
    "profit",
    "margin_pct",
    "rev_x_l",
    "prof_x_l",
    "team_ut",
)


# ---------------------------------------------------------------------------
# DDL — kept beside the code that writes it, called from main.py's lifespan.
# ---------------------------------------------------------------------------

PROJECTION_HISTORY_DDL = """
CREATE TABLE IF NOT EXISTS ops_projection_history (
  scope_key        TEXT        NOT NULL,
  team_key         TEXT        NOT NULL,
  as_of_date       DATE        NOT NULL,
  month_start      DATE        NOT NULL,
  source           TEXT        NOT NULL,
  pending_workdays INTEGER     NOT NULL,
  team_count       INTEGER     NOT NULL,
  avg_vol_day      NUMERIC     NOT NULL,
  avg_rev_day      NUMERIC     NOT NULL,
  avg_prof_day     NUMERIC     NOT NULL,
  proj_volume      NUMERIC     NOT NULL,
  proj_revenue     NUMERIC     NOT NULL,
  proj_profit      NUMERIC     NOT NULL,
  proj_margin_pct  NUMERIC     NOT NULL,
  proj_rev_x_l     NUMERIC     NOT NULL,
  proj_prof_x_l    NUMERIC     NOT NULL,
  proj_team_ut     NUMERIC     NOT NULL,
  captured_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  PRIMARY KEY (scope_key, team_key, as_of_date)
)
"""

PROJECTION_HISTORY_INDEX_DDL = """
CREATE INDEX IF NOT EXISTS idx_ops_projection_history_month
  ON ops_projection_history (scope_key, team_key, month_start, as_of_date)
"""

WEEKLY_ACTUALS_DDL = """
CREATE TABLE IF NOT EXISTS ops_weekly_actuals (
  scope_key   TEXT        NOT NULL,
  team_key    TEXT        NOT NULL,
  week_start  DATE        NOT NULL,
  week_end    DATE        NOT NULL,
  workdays    INTEGER     NOT NULL,
  team_count  INTEGER     NOT NULL,
  volume      NUMERIC     NOT NULL,
  revenue     NUMERIC     NOT NULL,
  profit      NUMERIC     NOT NULL,
  margin_pct  NUMERIC     NOT NULL,
  rev_x_l     NUMERIC     NOT NULL,
  prof_x_l    NUMERIC     NOT NULL,
  team_ut     NUMERIC     NOT NULL,
  source      TEXT        NOT NULL,
  captured_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  PRIMARY KEY (scope_key, team_key, week_start)
)
"""


# ---------------------------------------------------------------------------
# Small date helpers
# ---------------------------------------------------------------------------


def _month_start_of(d: date) -> date:
    return d.replace(day=1)


def _month_end_of(d: date) -> date:
    return d.replace(day=monthrange(d.year, d.month)[1])


def _business_day_of_month(d: date) -> int:
    """1-based Mon-Sat ordinal of ``d`` within its own month."""
    return _count_workdays(_month_start_of(d), d)


def _week_start_of(d: date) -> date:
    return d - timedelta(days=d.weekday())


def resolve_history_key(
    scope: DivisionScope, team_ids: Sequence[str],
) -> Optional[str]:
    """The ``team_key`` this (scope, team-selection) is tracked under.

    ``None`` means "not tracked" — the caller must then report
    ``tracked: false`` rather than fall back to a neighbouring scope. Silently
    answering with the division total when the user has TWO teams selected
    would put a High/Low beside a number it does not describe, which is the
    §16 defect the fold-in elsewhere in this module exists to prevent.
    """
    ids = [t.strip().upper() for t in team_ids if t]
    if not ids:
        return ALL_TEAMS
    if len(ids) == 1 and ids[0] in scope.sub_teams:
        return ids[0]
    if scope is CORP_SCOPE and sorted(ids) == sorted(DIGEST_CORP_TEAMS):
        return DIGEST_KEY
    return None


# ---------------------------------------------------------------------------
# The replay — six raw sums per as-of date, arithmetic left to _metrics.py
# ---------------------------------------------------------------------------


def _team_count_sql(where: str, scope: DivisionScope) -> str:
    """Distinct team count for a scope, over the WHOLE table.

    ⚠ Unbounded on purpose: ``_projection_sums_sql`` computes
    ``COUNT(DISTINCT br4.<team col>)`` in the same pass as its sums, and its
    predicate carries no date bound either. Recomputing it over the replay's
    date window instead would give a different capacity denominator — and
    ``proj_team_ut`` is ``proj_volume / (500 x team_count)``, so the utilisation
    figure would silently disagree with the panel's.

    ⚠ The column is ``scope.v4_team_col``, never a literal ``team_id``: under
    DFW ``team_id`` is the constant 'TEAM-DFW', so counting it would return 1
    for every DFW scope and inflate utilisation five-fold (§77).
    """
    return (
        f"SELECT COUNT(DISTINCT br4.{scope.v4_team_col}) "
        f"FROM public.mcleod_gld_budget_report_v4 br4 WHERE {where}"
    )


def _replay_sums_sql(where: str, p_start: int, p_end: int, p_scan_from: int) -> str:
    """One statement yielding the six projection sums for EVERY as-of date.

    Written set-based on purpose. The obvious shape — loop the dates in Python
    and run ``_projection_sums_sql`` once per day — is 13 scopes x ~950 days =
    ~12,000 round trips against a 40s command timeout, and it re-scans v4 every
    time. Here v4 is scanned ONCE into a per-day aggregate; everything after
    that is window functions over ~1,000 rows (the "derived count → same scan"
    rule). Measured: 19 months replayed in a few seconds.

    ``$p_scan_from`` deliberately reaches ~40 days before ``$p_start`` so the
    first as-of date still has a full 12-business-day lookback behind it.

    The Mon-Sat rule (``EXTRACT(DOW) <> 0`` = not Sunday) and the loads-count
    filter (``total_charge IS NOT NULL AND <> 0``, volume only — profit is
    never filtered, §39) mirror ``_projection_sums_sql`` exactly.
    """
    return f"""
        WITH daily AS (
          SELECT br4.origin_actual_departure::date AS d,
                 COUNT(*) FILTER (WHERE br4.total_charge IS NOT NULL
                                    AND br4.total_charge <> 0)      AS vol,
                 COALESCE(SUM(br4.total_charge), 0)::numeric        AS rev,
                 COALESCE(SUM(br4.margin_amt),   0)::numeric        AS prof
            FROM public.mcleod_gld_budget_report_v4 br4
           WHERE {where}
             AND br4.origin_actual_departure >= ${p_scan_from}
             AND br4.origin_actual_departure < (${p_end}::date + INTERVAL '1 day')
           GROUP BY 1
        ),
        cal AS (
          SELECT g::date                              AS d,
                 COALESCE(dd.vol,  0)::numeric        AS vol,
                 COALESCE(dd.rev,  0)::numeric        AS rev,
                 COALESCE(dd.prof, 0)::numeric        AS prof
            FROM generate_series(${p_scan_from}::date, ${p_end}::date, '1 day') g
            LEFT JOIN daily dd ON dd.d = g::date
        ),
        -- 12-business-day rolling window. Sundays are dropped BEFORE the
        -- window so "12 rows back" really is 12 Mon-Sat days.
        bdays AS (
          SELECT d,
                 SUM(vol)  OVER w AS vol_12,
                 SUM(rev)  OVER w AS rev_12,
                 SUM(prof) OVER w AS prof_12,
                 COUNT(*)  OVER w AS n_12
            FROM cal
           WHERE EXTRACT(DOW FROM d) <> 0
          WINDOW w AS (ORDER BY d ROWS BETWEEN 11 PRECEDING AND CURRENT ROW)
        ),
        -- Month-to-date cumulative legs. `vol_mtd` stops at the PREVIOUS day
        -- and `rev/prof_mtd` include the as-of day itself: that asymmetry is
        -- load-bearing (see _metrics.py) and is reproduced here, not tidied.
        mtd AS (
          SELECT d,
                 SUM(vol)  OVER m AS vol_cum,
                 SUM(rev)  OVER m AS rev_cum,
                 SUM(prof) OVER m AS prof_cum
            FROM cal
          WINDOW m AS (PARTITION BY date_trunc('month', d) ORDER BY d)
        ),
        -- Months with no scoped volume at all are skipped: writing a $0
        -- projection for a division that did not exist yet would plant a
        -- permanent fake LOW in every range calculation.
        live_months AS (
          SELECT date_trunc('month', d)::date AS m
            FROM cal GROUP BY 1 HAVING SUM(vol) > 0
        )
        SELECT
          a.d                                                   AS as_of,
          date_trunc('month', a.d)::date                        AS month_start,
          COALESCE(b.vol_12,  0)                                AS vol_12,
          COALESCE(b.rev_12,  0)                                AS rev_12,
          COALESCE(b.prof_12, 0)                                AS prof_12,
          COALESCE(mp.vol_cum,  0)                              AS vol_mtd,
          COALESCE(mc.rev_cum,  0)                              AS rev_mtd,
          COALESCE(mc.prof_cum, 0)                              AS prof_mtd
          FROM cal a
          JOIN live_months lm ON lm.m = date_trunc('month', a.d)::date
          LEFT JOIN LATERAL (
            SELECT vol_12, rev_12, prof_12 FROM bdays
             WHERE bdays.d <= a.d - 1 AND bdays.n_12 = 12
             ORDER BY bdays.d DESC LIMIT 1
          ) b ON TRUE
          LEFT JOIN mtd mp ON mp.d = a.d - 1
                          AND date_trunc('month', mp.d) = date_trunc('month', a.d)
          LEFT JOIN mtd mc ON mc.d = a.d
         WHERE a.d BETWEEN ${p_start} AND ${p_end}
         ORDER BY a.d
    """


async def _replay_scope(
    gold_pool,
    *,
    scope: DivisionScope,
    team_ids: Sequence[str],
    start: date,
    end: date,
) -> list[dict[str, Any]]:
    """Replay one (scope, team) pair over ``[start, end]``.

    Returns one dict per as-of date, already run through
    ``_projection_from_sums`` so the arithmetic is the panel's.
    """
    scope_params: list = []
    where = _v4_scope_where(
        "br4", list(team_ids) or None, None, None, scope_params,
        None, None, None, None, scope=scope,
    )
    # Capacity denominator first — same unbounded COUNT(DISTINCT) the live
    # panel does, so proj_team_ut cannot drift between the two.
    team_count = int(
        await gold_pool.fetchval(_team_count_sql(where, scope), *scope_params) or 0
    ) or len(team_ids) or len(scope.sub_teams)

    params = list(scope_params)
    scan_from = start - timedelta(days=40)
    params.extend([start, end, scan_from])
    n = len(params)
    rows = await gold_pool.fetch(
        _replay_sums_sql(where, n - 2, n - 1, n), *params
    )

    out: list[dict[str, Any]] = []
    for r in rows:
        as_of: date = r["as_of"]
        m_end = _month_end_of(as_of)
        pending = _count_workdays(as_of, m_end)
        proj = _projection_from_sums(
            r["vol_12"], r["rev_12"], r["prof_12"],
            r["vol_mtd"], r["rev_mtd"], r["prof_mtd"],
            pending, team_count,
        )
        out.append({
            "as_of_date": as_of,
            "month_start": r["month_start"],
            "team_count": team_count,
            **proj,
        })
    return out


# ---------------------------------------------------------------------------
# Writers
# ---------------------------------------------------------------------------

_UPSERT_COLS = (
    "scope_key", "team_key", "as_of_date", "month_start", "source",
    "pending_workdays", "team_count", *_PROJ_FIELDS,
)


def _upsert_sql(*, overwrite: bool) -> str:
    """INSERT for the projection history.

    ``overwrite=False`` (a replay) is ``DO NOTHING``: a backfill must never
    rewrite a row that was observed live. ``overwrite=True`` (the daily job) is
    ``DO UPDATE`` so re-running the job, or upgrading a backfilled row to a
    live one, is idempotent.
    """
    cols = ", ".join(_UPSERT_COLS)
    ph = ", ".join(f"${i}" for i in range(1, len(_UPSERT_COLS) + 1))
    if not overwrite:
        conflict = "DO NOTHING"
    else:
        sets = ", ".join(
            f"{c} = EXCLUDED.{c}"
            for c in _UPSERT_COLS
            if c not in ("scope_key", "team_key", "as_of_date")
        )
        conflict = f"DO UPDATE SET {sets}, captured_at = NOW()"
    return (
        f"INSERT INTO ops_projection_history ({cols}) VALUES ({ph}) "
        f"ON CONFLICT (scope_key, team_key, as_of_date) {conflict}"
    )


def _row_values(scope_key: str, team_key: str, source: str, rec: dict) -> list:
    return [
        scope_key, team_key, rec["as_of_date"], rec["month_start"], source,
        int(rec["pending_workdays"]), int(rec["team_count"]),
        *[_safe_float(rec[f]) for f in _PROJ_FIELDS],
    ]


async def capture_projection_snapshots(
    hub_pool, gold_pool, *, as_of: Optional[date] = None,
) -> dict[str, Any]:
    """Record TODAY's projection for every tracked scope. Never raises.

    Runs the live ``_team_projection_core`` — the identical call the panel
    makes — once per scope, so what is stored is exactly what the report would
    have shown at that moment (§69), not a re-derivation.
    """
    if hub_pool is None or gold_pool is None:
        logger.warning("Projection snapshot skipped — pools not configured")
        return {"skipped": "pools not configured"}

    day = as_of or cst_today()
    m_start, _ = _month_bounds(day)
    written, failed = 0, []

    for scope_key, team_key, scope, team_ids in SNAPSHOT_SCOPES:
        try:
            proj = await _team_projection_core(
                gold_pool, team=list(team_ids) or None, customer=None, load_type=None,
                lanes=None, exclude_lanes=None, carriers=None, exclude_carriers=None,
                today=day, scope=scope,
            )
        except Exception as e:  # noqa: BLE001 — one scope must not kill the rest
            # ⚠ Never wrap the whole loop in one try: a single failing scope
            # would silently stop every later one (the 3-day-outage lesson).
            logger.error("Projection snapshot %s/%s failed: %s", scope_key, team_key, e)
            failed.append(f"{scope_key}/{team_key}")
            continue
        # A scope with no volume this month writes nothing — see live_months.
        if not _safe_float(proj.get("proj_volume")) and not _safe_float(proj.get("proj_profit")):
            continue
        rec = {"as_of_date": day, "month_start": m_start, **proj}
        try:
            await hub_pool.execute(_upsert_sql(overwrite=True),
                                   *_row_values(scope_key, team_key, "live", rec))
            written += 1
        except Exception as e:  # noqa: BLE001
            logger.error("Projection snapshot write %s/%s failed: %s", scope_key, team_key, e)
            failed.append(f"{scope_key}/{team_key}")

    result = {"as_of": day.isoformat(), "written": written,
              "scopes": len(SNAPSHOT_SCOPES), "failed": failed}
    logger.info("Projection snapshot: %s", result)
    return result


async def backfill_projection_history(
    hub_pool, gold_pool, *, start: date = BACKFILL_START, end: Optional[date] = None,
) -> dict[str, Any]:
    """Replay the projection over ``[start, end]`` for every tracked scope.

    ``DO NOTHING`` on conflict, so this is safe to re-run and can never
    overwrite an observed row. Today is deliberately EXCLUDED — today's value
    is the live one, and the endpoint folds it in at read time.
    """
    if hub_pool is None or gold_pool is None:
        return {"skipped": "pools not configured"}

    last = end or (cst_today() - timedelta(days=1))
    if start > last:
        return {"skipped": "empty range"}

    total, failed = 0, []
    for scope_key, team_key, scope, team_ids in SNAPSHOT_SCOPES:
        try:
            recs = await _replay_scope(
                gold_pool, scope=scope, team_ids=team_ids, start=start, end=last,
            )
        except Exception as e:  # noqa: BLE001 — isolate each scope
            logger.error("Projection backfill %s/%s failed: %s", scope_key, team_key, e)
            failed.append(f"{scope_key}/{team_key}")
            continue
        if not recs:
            continue
        try:
            await hub_pool.executemany(
                _upsert_sql(overwrite=False),
                [_row_values(scope_key, team_key, "backfill", r) for r in recs],
            )
            total += len(recs)
        except Exception as e:  # noqa: BLE001
            logger.error("Projection backfill write %s/%s failed: %s", scope_key, team_key, e)
            failed.append(f"{scope_key}/{team_key}")

    result = {"start": start.isoformat(), "end": last.isoformat(),
              "rows": total, "failed": failed}
    logger.info("Projection backfill: %s", result)
    return result


# ---------------------------------------------------------------------------
# Weekly actuals — "keep all this weekly values as well for ever"
# ---------------------------------------------------------------------------


def _weekly_sql(where: str, p_start: int, p_end: int) -> str:
    """Per Mon-Sun week actuals. Mirrors ``/team-projection-weekly``'s SELECT.

    The live endpoint only ever shows five weeks; this keeps every week, so a
    year-over-year seasonality comparison survives even if the shared gold
    table is one day frozen or purged (13 McLeod tables already are).
    """
    return f"""
        SELECT
          DATE_TRUNC('week', br4.origin_actual_departure)::date AS wk,
          COUNT(*) FILTER (WHERE br4.total_charge IS NOT NULL
                             AND br4.total_charge <> 0) AS vol,
          COALESCE(SUM(br4.total_charge), 0)::numeric    AS rev,
          COALESCE(SUM(br4.margin_amt),   0)::numeric    AS prof,
          COUNT(DISTINCT br4.team_id)                    AS team_count
        FROM public.mcleod_gld_budget_report_v4 br4
        WHERE {where}
          AND br4.origin_actual_departure >= ${p_start}
          AND br4.origin_actual_departure < (${p_end}::date + INTERVAL '1 day')
        GROUP BY wk
        ORDER BY wk
    """


_WEEK_COLS = (
    "scope_key", "team_key", "week_start", "week_end", "workdays", "team_count",
    *_WEEK_FIELDS, "source",
)


def _week_upsert_sql() -> str:
    """Always ``DO UPDATE``: a week's figures keep moving as loads post late.

    Older weeks converge and stop changing on their own; re-writing them is a
    no-op, which is cheaper than tracking which ones are final.
    """
    cols = ", ".join(_WEEK_COLS)
    ph = ", ".join(f"${i}" for i in range(1, len(_WEEK_COLS) + 1))
    sets = ", ".join(
        f"{c} = EXCLUDED.{c}" for c in _WEEK_COLS
        if c not in ("scope_key", "team_key", "week_start")
    )
    return (
        f"INSERT INTO ops_weekly_actuals ({cols}) VALUES ({ph}) "
        f"ON CONFLICT (scope_key, team_key, week_start) "
        f"DO UPDATE SET {sets}, captured_at = NOW()"
    )


async def capture_weekly_actuals(
    hub_pool, gold_pool, *, start: Optional[date] = None, end: Optional[date] = None,
    source: str = "live",
) -> dict[str, Any]:
    """Upsert Mon-Sun weekly actuals for every tracked scope.

    Defaults to the trailing eight weeks — wide enough that late-posted loads
    are picked up, narrow enough to stay cheap on a daily run. Pass an explicit
    ``start`` to seed history.
    """
    if hub_pool is None or gold_pool is None:
        return {"skipped": "pools not configured"}

    today = cst_today()
    last = end or today
    first = start or (_week_start_of(today) - timedelta(weeks=7))
    total, failed = 0, []

    for scope_key, team_key, scope, team_ids in SNAPSHOT_SCOPES:
        params: list = []
        where = _v4_scope_where(
            "br4", list(team_ids) or None, None, None, params,
            None, None, None, None, scope=scope,
        )
        params.extend([first, last])
        n = len(params)
        try:
            rows = await gold_pool.fetch(_weekly_sql(where, n - 1, n), *params)
        except Exception as e:  # noqa: BLE001 — isolate each scope
            logger.error("Weekly actuals %s/%s failed: %s", scope_key, team_key, e)
            failed.append(f"{scope_key}/{team_key}")
            continue

        payload = []
        for r in rows:
            ws: date = r["wk"]
            we = ws + timedelta(days=6)
            vol = int(r["vol"] or 0)
            if not vol:
                continue
            rev = _safe_float(r["rev"])
            prof = _safe_float(r["prof"])
            workdays = _count_workdays(ws, min(we, today)) or 1
            team_count = int(r["team_count"] or 0) or len(team_ids) or len(scope.sub_teams)
            cap = 500.0 * team_count
            payload.append([
                scope_key, team_key, ws, we, workdays, team_count,
                float(vol), rev, prof,
                _safe_float((prof / rev * 100.0) if rev else 0.0),
                _safe_float((rev / vol) if vol else 0.0),
                _safe_float((prof / vol) if vol else 0.0),
                _safe_float((vol / cap * 100.0) if cap else 0.0),
                source,
            ])
        if not payload:
            continue
        try:
            await hub_pool.executemany(_week_upsert_sql(), payload)
            total += len(payload)
        except Exception as e:  # noqa: BLE001
            logger.error("Weekly actuals write %s/%s failed: %s", scope_key, team_key, e)
            failed.append(f"{scope_key}/{team_key}")

    result = {"start": first.isoformat(), "end": last.isoformat(),
              "rows": total, "failed": failed}
    logger.info("Weekly actuals: %s", result)
    return result


# ---------------------------------------------------------------------------
# Readers — the stats the panel and the e-mail render
# ---------------------------------------------------------------------------


def _pct_change(current: float, base: float) -> Optional[float]:
    """Percent change against a baseline. ``None`` when the baseline is zero.

    ``abs(base)`` so a negative baseline still yields the intuitive sign —
    same convention as ``team_perf_digest._pct_change``.
    """
    if not base:
        return None
    return (current - base) / abs(base) * 100.0


def _extremes(points: list[dict]) -> dict[str, Any]:
    """High/Low/Open/Close + range % over an already-ordered point list."""
    if not points:
        return {"open": None, "close": None, "high": None, "low": None,
                "high_date": None, "low_date": None, "range_pct": None}
    hi = max(points, key=lambda p: p["proj_profit"])
    lo = min(points, key=lambda p: p["proj_profit"])
    return {
        "open": points[0]["proj_profit"],
        "close": points[-1]["proj_profit"],
        "high": hi["proj_profit"],
        "low": lo["proj_profit"],
        "high_date": hi["as_of_date"],
        "low_date": lo["as_of_date"],
        "range_pct": _pct_change(hi["proj_profit"], lo["proj_profit"]),
    }


async def month_points(
    hub_pool, *, scope_key: str, team_key: str, month_start: date,
) -> list[dict]:
    """The stored daily path for one month, oldest first."""
    rows = await hub_pool.fetch(
        """
        SELECT as_of_date, proj_profit, proj_revenue, proj_volume,
               proj_margin_pct, pending_workdays, source
          FROM ops_projection_history
         WHERE scope_key = $1 AND team_key = $2 AND month_start = $3
         ORDER BY as_of_date
        """,
        scope_key, team_key, month_start,
    )
    return [
        {
            "as_of_date": r["as_of_date"],
            "proj_profit": _safe_float(r["proj_profit"]),
            "proj_revenue": _safe_float(r["proj_revenue"]),
            "proj_volume": _safe_float(r["proj_volume"]),
            "proj_margin_pct": _safe_float(r["proj_margin_pct"]),
            "pending_workdays": int(r["pending_workdays"] or 0),
            "source": r["source"],
        }
        for r in rows
    ]


def current_month_stats(points: list[dict], *, live_value: Optional[float],
                        today: date) -> dict[str, Any]:
    """High/Low/range for the month in progress.

    ⚠ ``live_value`` is folded in and REPLACES today's stored row. The stored
    row is the 02:45 CST opening value; by the time anyone reads the page or
    the 05:28 e-mail goes out the live number has moved. Without this fold-in
    the strip could print a "High" BELOW the figure printed directly above it
    — the §16 defect (a KPI must match its own detail), which is exactly how
    this kind of panel loses trust.
    """
    merged = [p for p in points if p["as_of_date"] != today]
    if live_value is not None:
        merged.append({
            "as_of_date": today,
            "proj_profit": _safe_float(live_value),
            "proj_revenue": 0.0, "proj_volume": 0.0, "proj_margin_pct": 0.0,
            "pending_workdays": 0, "source": "live",
        })
    merged.sort(key=lambda p: p["as_of_date"])

    stats = _extremes(merged)
    settled = _extremes([
        p for p in merged
        if _business_day_of_month(p["as_of_date"]) >= SETTLED_FROM_BUSINESS_DAY
    ])
    prev = merged[-2]["proj_profit"] if len(merged) >= 2 else None
    latest = merged[-1]["proj_profit"] if merged else None
    return {
        **stats,
        "latest": latest,
        "prev": prev,
        "chg_pct": _pct_change(latest, prev) if (latest is not None and prev) else None,
        "settled_high": settled["high"],
        "settled_low": settled["low"],
        "settled_range_pct": settled["range_pct"],
        "settled_from_business_day": SETTLED_FROM_BUSINESS_DAY,
        "points": merged,
        "days": len(merged),
        "backfilled_days": sum(1 for p in merged if p["source"] == "backfill"),
    }


async def monthly_summary(
    hub_pool, *, scope_key: str, team_key: str, months: int,
    before_month: date,
) -> list[dict[str, Any]]:
    """Open / High / Low / Close per month — the OHLC ladder.

    The error column is filled in by the caller, which has the realised actual;
    this half only knows what was projected.
    """
    rows = await hub_pool.fetch(
        """
        SELECT month_start,
               MIN(proj_profit)  AS low,
               MAX(proj_profit)  AS high,
               COUNT(*)          AS days,
               COUNT(*) FILTER (WHERE source = 'live') AS live_days
          FROM ops_projection_history
         WHERE scope_key = $1 AND team_key = $2 AND month_start < $3
         GROUP BY month_start
         ORDER BY month_start DESC
         LIMIT $4
        """,
        scope_key, team_key, before_month, months,
    )
    if not rows:
        return []
    oldest = min(r["month_start"] for r in rows)
    # Open/Close need the FIRST and LAST row of each month, which an aggregate
    # cannot give — one extra pass over the same already-narrow slice rather
    # than a correlated subquery per month.
    edges = await hub_pool.fetch(
        """
        SELECT DISTINCT ON (month_start) month_start, as_of_date, proj_profit
          FROM ops_projection_history
         WHERE scope_key = $1 AND team_key = $2
           AND month_start >= $3 AND month_start < $4
         ORDER BY month_start, as_of_date
        """,
        scope_key, team_key, oldest, before_month,
    )
    closes = await hub_pool.fetch(
        """
        SELECT DISTINCT ON (month_start) month_start, as_of_date, proj_profit
          FROM ops_projection_history
         WHERE scope_key = $1 AND team_key = $2
           AND month_start >= $3 AND month_start < $4
         ORDER BY month_start, as_of_date DESC
        """,
        scope_key, team_key, oldest, before_month,
    )
    open_by = {r["month_start"]: _safe_float(r["proj_profit"]) for r in edges}
    close_by = {r["month_start"]: _safe_float(r["proj_profit"]) for r in closes}

    out = []
    for r in sorted(rows, key=lambda x: x["month_start"]):
        m = r["month_start"]
        hi, lo = _safe_float(r["high"]), _safe_float(r["low"])
        out.append({
            "month_start": m,
            "open": open_by.get(m),
            "close": close_by.get(m),
            "high": hi,
            "low": lo,
            "range_pct": _pct_change(hi, lo),
            "days": int(r["days"] or 0),
            "live_days": int(r["live_days"] or 0),
        })
    return out


_ACTUALS_SQL = """
    SELECT date_trunc('month', br4.origin_actual_departure)::date AS m,
           COALESCE(SUM(br4.margin_amt), 0)::numeric              AS profit
      FROM public.mcleod_gld_budget_report_v4 br4
     WHERE {where}
       AND br4.origin_actual_departure >= ${p_start}
       AND br4.origin_actual_departure < (${p_end}::date + INTERVAL '1 day')
     GROUP BY 1
"""


async def actual_profit_by_month(
    gold_pool, *, scope: DivisionScope, team_ids: Sequence[str],
    start: date, end: date,
) -> dict[date, float]:
    """Realised profit per month — the denominator of the projection error.

    §39: profit is ``SUM(margin_amt)`` over ALL rows. The ``total_charge <> 0``
    filter belongs to the loads COUNT only; applying it here would quietly drop
    accessorial-only revenue and make every error figure look worse than it is.

    ⚠ Half-open on the raw column (no ``::date`` cast in WHERE) so ``idx_v4_dep``
    is still usable (§1/§43).
    """
    params: list = []
    where = _v4_scope_where(
        "br4", list(team_ids) or None, None, None, params,
        None, None, None, None, scope=scope,
    )
    params.extend([start, end])
    n = len(params)
    rows = await gold_pool.fetch(
        _ACTUALS_SQL.format(where=where, p_start=n - 1, p_end=n), *params
    )
    return {r["m"]: _safe_float(r["profit"]) for r in rows}


def deviation_pct(actual: Optional[float], high: Optional[float]) -> Optional[float]:
    """Bruno's "Deviation" — ``(Actual - High) / Actual``, as a percent.

    PDF "space -- Ops Portal Updates" (2026-09-03), Request 1, verbatim:
    the month's realised profit against the HIGHEST projection it ever showed.
    Negative means the high overshot what landed; positive means the month beat
    every projection it made.

    ⚠ NOT ``_pct_change(actual, high)`` and NOT ``-high_error_pct``, even though
    all three agree on a profitable month. ``_pct_change`` divides by
    ``abs(base)`` so a negative baseline still reads intuitively — a deliberate
    convention for the OTHER columns. Bruno wrote a plain ``/ "Actual"``, so a
    LOSING month (actual < 0) flips sign between the two formulas. This is a
    different measurement from ``high_error_pct``, so it gets its own name and
    its own function rather than a sign flip at the call site (§69).

    ``None`` when either leg is missing or ``actual`` is zero — a zero
    denominator has no percent, and printing 0% there would claim the
    projection was perfect (§93: the same trap the replay clamp fixed).
    """
    if actual is None or high is None or not actual:
        return None
    return (actual - high) / actual * 100.0


def attach_actuals(months: list[dict], actual_by_month: dict[date, float]) -> list[dict]:
    """Add the realised profit and the projection error to each month row.

    ``error_pct`` is (close − actual) / |actual|: how wrong the LAST projection
    of the month was. Signed, so a persistent bias is visible rather than being
    averaged away by an absolute value.

    ``deviation_pct`` is Bruno's (actual − high) / actual — see the function
    above for why it is not a sign flip of ``high_error_pct``.
    """
    for m in months:
        actual = actual_by_month.get(m["month_start"])
        m["actual_profit"] = actual
        m["error_pct"] = (
            _pct_change(m["close"], actual)
            if (actual and m.get("close") is not None) else None
        )
        m["high_error_pct"] = (
            _pct_change(m["high"], actual) if actual else None
        )
        m["low_error_pct"] = (
            _pct_change(m["low"], actual) if actual else None
        )
        m["deviation_pct"] = deviation_pct(actual, m.get("high"))
    return months
