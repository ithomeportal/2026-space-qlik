"""DFW - Access Log Doors — "repeat Out of Time" nightly digest (data layer).

Pulled by an external n8n workflow, exactly like ``team_perf_digest``: the
deliverable is a GET endpoint returning
``{"success":true,"data":{subject, html, generatedAt, meta}}`` — see
``app/routers/dfw_access_doors_digest.py``. Nothing here sends mail.

Scope and scoring are BORROWED, never restated:

  * ``_first_punch_cte`` / ``_scored_cte`` / ``_OUT_OF_TIME_PREDICATE`` come
    from ``hr_access_doors`` — the same CTE chain and the same classification
    the on-screen report runs, so the e-mail and the report a recipient opens
    to check it cannot disagree;
  * ``DFW_GATE_SQL`` comes from ``scoped_access_doors`` — the same literal the
    ``dfw-access-doors`` report is server-locked to.

⚠ Rows with no scheduled start (``expected IS NULL``) are NOT counted. They are
unscoreable, not punctual: counting them as on time would flatter the rate, and
counting them as Out of Time would accuse people the report holds no
expectation for. ``_OUT_OF_TIME_PREDICATE`` already carries that guard, which is
the whole reason this module imports it instead of writing ``check_minutes <=
-1`` itself.

⚠ One scan, not two. ``first_punch`` is the expensive CTE (a ROW_NUMBER() over
the 128K-row punch table), so the offender list and every window-level total
are read from ONE ``fetchrow`` via ``json_agg`` + scalar subqueries over a
shared ``scope`` CTE — the same shape ``podium_top`` uses. Postgres materialises
a CTE referenced more than once, so ``scope`` is built exactly once.

Grain: one row per (employee, shift date). "Days" throughout this module means
shift dates with a recorded arrival, never raw badge events.
"""
from __future__ import annotations

import json
import logging
from datetime import date, datetime, timedelta
from typing import Any, Optional

from app.clock import cst_now, cst_today
from app.routers.hr_access_doors import (
    OUT_OF_TIME_DEFINITION,
    _NOT_ON_TIME_REF_PREDICATE,
    _CHECK_MINUTES_EXPR,
    _ON_TIME_PREDICATE,
    _OUT_OF_TIME_PREDICATE,
    _first_punch_cte,
    _scored_cte,
)
from app.routers.scoped_access_doors import DFW_GATE_SQL, DFW_SCOPE_LABEL
from app.services.access_doors_delays_digest_html import render_html

logger = logging.getLogger(__name__)

REPORT_KEY = "dfw-access-doors"

# Rolling window, in calendar days, ending today (inclusive).
DEFAULT_DAYS = 14
# "More than 3" Out of Time days => 4 or more. Expressed as an inclusive floor
# so the SQL comparison is `>=` and the boundary is stated once, here: at
# exactly 3 a person is NOT reported.
DEFAULT_MIN_DAYS = 4

# Hard ceiling on the rendered table. The DFW scope is ~40 people, so this can
# only ever bite if the scoring breaks wholesale — in which case a truncated
# table plus the "showing N of M" line is a better failure than a 2MB e-mail.
MAX_ROWS = 60


def resolve_window(days: int) -> tuple[date, date]:
    """Rolling ``days``-day window ending TODAY in CST, inclusive both ends.

    ``days=14`` -> today-13 .. today, i.e. 14 calendar days. Every boundary
    comes from ``cst_today()`` (SPEC-CODE-RULES §2): Render runs in UTC, and a
    ``date.today()`` here would flip the window a day early every evening.
    """
    end = cst_today()
    start = end - timedelta(days=max(days, 1) - 1)
    return start, end


def _build_sql() -> str:
    """The single query behind the digest.

    ``$1``/``$2`` are the window bounds, ``$3`` the inclusive Out-of-Time-day
    floor. ``per_person`` aggregates the whole scope; the floor is applied once,
    in the offender subquery, so the window totals in the footer stay
    full-scope and the e-mail can say what it is a subset OF.
    """
    return f"""
        WITH {_first_punch_cte('$1', '$2')},
             {_scored_cte('$1', '$2')},
        scope AS (
            SELECT nm, jt, event_date, event_time, expected
            FROM scored
            WHERE 1=1 {DFW_GATE_SQL}
        ),
        per_person AS (
            SELECT
              nm                                                        AS full_name,
              -- One job title per person: `jt` comes from the single
              -- `timeoff_employee` row joined on e-mail, so it is constant
              -- within a name. MAX() keeps the grain at one row per person —
              -- grouping by (name, title) would SPLIT a mid-window title change
              -- into two sub-threshold rows and silently drop the person.
              MAX(jt)                                                   AS job_title,
              COUNT(*)                                                  AS badged_days,
              COUNT(*) FILTER (WHERE {_OUT_OF_TIME_PREDICATE})          AS out_of_time_days,
              COUNT(*) FILTER (WHERE {_ON_TIME_PREDICATE})              AS on_time_days,
              COUNT(*) FILTER (WHERE {_NOT_ON_TIME_REF_PREDICATE})      AS unscored_days,
              -- check_minutes is NEGATIVE when late, so the WORST lateness is
              -- the MINIMUM. Both are computed over Out-of-Time days only —
              -- averaging in the on-time days would report a punctual average
              -- for someone who is late half the week.
              MIN({_CHECK_MINUTES_EXPR})
                 FILTER (WHERE {_OUT_OF_TIME_PREDICATE})                AS worst_check_minutes,
              AVG({_CHECK_MINUTES_EXPR})
                 FILTER (WHERE {_OUT_OF_TIME_PREDICATE})                AS avg_check_minutes,
              MAX(event_date) FILTER (WHERE {_OUT_OF_TIME_PREDICATE})   AS last_out_of_time_date
            FROM scope
            GROUP BY nm
        )
        SELECT
          (SELECT COALESCE(json_agg(t ORDER BY t.out_of_time_days DESC, t.full_name ASC),
                           '[]'::json)
             FROM (SELECT * FROM per_person
                    WHERE out_of_time_days >= $3
                    ORDER BY out_of_time_days DESC, full_name ASC) t)   AS offenders,
          -- Freshness. `scope_as_of` is the latest arrival this report actually
          -- scored; `feed_as_of` is the latest raw punch of ANY kind in the
          -- window. A page over a synced table that renders 0 for both "nobody
          -- was late" and "the feed died" hides an outage indefinitely.
          (SELECT MAX(event_time) FROM scope)                           AS scope_as_of,
          (SELECT MAX(z.event_time)
             FROM public.zk_gld_onlyfingerprint z
            WHERE z.event_date BETWEEN $1::date AND $2::date)           AS feed_as_of,
          (SELECT COUNT(DISTINCT nm) FROM scope)                        AS people_in_scope,
          (SELECT COUNT(*) FROM scope)                                  AS shifts_in_scope,
          (SELECT COUNT(*) FROM scope WHERE {_OUT_OF_TIME_PREDICATE})   AS out_of_time_shifts,
          (SELECT COUNT(*) FROM scope WHERE {_ON_TIME_PREDICATE})       AS on_time_shifts,
          (SELECT COUNT(*) FROM scope WHERE {_NOT_ON_TIME_REF_PREDICATE})
                                                                        AS unscored_shifts
    """


def _parse_json(value: Any) -> list[dict]:
    """asyncpg hands a ``json`` column back as ``str``. Same shim as podium_top."""
    if value is None:
        return []
    if isinstance(value, str):
        return json.loads(value)
    return list(value)


def _as_int(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _as_float(value: Any) -> Optional[float]:
    if value is None:
        return None
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    if out != out or out in (float("inf"), float("-inf")):
        return None
    return out


def _ratio(num: float, den: float) -> Optional[float]:
    """num/den, or ``None`` when the denominator is zero (rendered as a dash).

    Never 0.0 for a missing denominator — "0% late" and "no scored days at
    all" are different facts and must not print the same.
    """
    if not den:
        return None
    return num / den


def _shape_person(raw: dict) -> dict:
    """One offender row, with the derived fields the template renders.

    ``out_of_time_pct`` is over SCORED days (badged minus unscored), not over
    badged days — the unscored ones carry no expectation, so leaving them in
    the denominator would quietly shrink everybody's rate.
    """
    badged = _as_int(raw.get("badged_days"))
    unscored = _as_int(raw.get("unscored_days"))
    out_days = _as_int(raw.get("out_of_time_days"))
    scored = badged - unscored
    worst = _as_float(raw.get("worst_check_minutes"))
    avg = _as_float(raw.get("avg_check_minutes"))
    pct = _ratio(float(out_days), float(scored))
    return {
        "full_name": raw.get("full_name") or "(unknown)",
        "job_title": raw.get("job_title") or "—",
        "out_of_time_days": out_days,
        "on_time_days": _as_int(raw.get("on_time_days")),
        "badged_days": badged,
        "unscored_days": unscored,
        "scored_days": scored,
        "out_of_time_pct": None if pct is None else pct * 100.0,
        # Reported as POSITIVE minutes late. check_minutes is expected-actual,
        # so a late arrival is negative in SQL and flipped exactly once, here.
        "worst_minutes_late": None if worst is None else abs(worst),
        "avg_minutes_late": None if avg is None else abs(avg),
        "last_out_of_time_date": raw.get("last_out_of_time_date"),
    }


def _iso(value: Any) -> Optional[str]:
    if value is None:
        return None
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    return str(value)


async def build_access_doors_delays_digest(
    pool,
    *,
    days: int = DEFAULT_DAYS,
    min_days: int = DEFAULT_MIN_DAYS,
) -> dict[str, Any]:
    """Assemble the DFW "repeat Out of Time" digest payload.

    Returns ``{"subject", "html", "generatedAt", "meta"}``.

    Always returns a renderable e-mail. An empty offender list is the ALL-CLEAR
    case, not an error and not an empty body: the n8n workflow sends this
    unconditionally, so "nobody qualified" has to be a sentence a recipient can
    read, otherwise a silent send failure and a clean week look identical.
    """
    start, end = resolve_window(days)
    now = cst_now()

    row = await pool.fetchrow(_build_sql(), start, end, int(min_days))
    row = dict(row) if row else {}

    people = [_shape_person(r) for r in _parse_json(row.get("offenders"))]
    truncated = max(len(people) - MAX_ROWS, 0)
    if truncated:
        logger.warning(
            "dfw delays digest: %s offenders over the threshold, rendering %s",
            len(people), MAX_ROWS,
        )
        people = people[:MAX_ROWS]

    totals = {
        "people_in_scope": _as_int(row.get("people_in_scope")),
        "shifts_in_scope": _as_int(row.get("shifts_in_scope")),
        "out_of_time_shifts": _as_int(row.get("out_of_time_shifts")),
        "on_time_shifts": _as_int(row.get("on_time_shifts")),
        "unscored_shifts": _as_int(row.get("unscored_shifts")),
    }
    scored_shifts = totals["shifts_in_scope"] - totals["unscored_shifts"]
    pct = _ratio(float(totals["out_of_time_shifts"]), float(scored_shifts))
    totals["scored_shifts"] = scored_shifts
    totals["out_of_time_pct"] = None if pct is None else pct * 100.0

    html = render_html(
        scope_label=DFW_SCOPE_LABEL,
        now=now,
        start=start,
        end=end,
        days=days,
        min_days=int(min_days),
        people=people,
        totals=totals,
        truncated=truncated,
        scope_as_of=row.get("scope_as_of"),
        feed_as_of=row.get("feed_as_of"),
        definition=OUT_OF_TIME_DEFINITION,
    )

    if people:
        subject = (
            f"DFW Access Doors — {len(people)} employee"
            f"{'' if len(people) == 1 else 's'} over {min_days - 1} Out of Time "
            f"days (last {days}d, {end.isoformat()})"
        )
    else:
        subject = (
            f"DFW Access Doors — all clear: nobody over {min_days - 1} "
            f"Out of Time days (last {days}d, {end.isoformat()})"
        )

    return {
        "subject": subject,
        "html": html,
        "generatedAt": now.isoformat(),
        "meta": {
            "report_key": REPORT_KEY,
            "scope": DFW_SCOPE_LABEL,
            "gate_sql": DFW_GATE_SQL,
            "window": {
                "start": start.isoformat(),
                "end": end.isoformat(),
                "days": days,
            },
            "threshold": {
                # `min_days` is the inclusive floor actually used in SQL;
                # `more_than` is the same rule as the request phrased it.
                "min_out_of_time_days": int(min_days),
                "more_than": int(min_days) - 1,
            },
            "employees_over_threshold": len(people),
            "rows_truncated": truncated,
            "totals": totals,
            "data_as_of": {
                "scope_latest_badge_in": _iso(row.get("scope_as_of")),
                "feed_latest_punch": _iso(row.get("feed_as_of")),
            },
            "employees": [
                {**p, "last_out_of_time_date": _iso(p["last_out_of_time_date"])}
                for p in people
            ],
            "definition": OUT_OF_TIME_DEFINITION,
            "sources": [
                "direct SQL: zk_gld_onlyfingerprint + timeoff_employee "
                "+ late_arrival_schedule + app_auth_users",
                "scoring: hr_access_doors._first_punch_cte / _scored_cte / "
                "_OUT_OF_TIME_PREDICATE",
                "scope: scoped_access_doors.DFW_GATE_SQL",
            ],
        },
    }
