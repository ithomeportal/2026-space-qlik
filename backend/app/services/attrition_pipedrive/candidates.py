"""Who is due today — the SAME population and day count as the Reactive tab.

``/attrition-wow/reactive-summary`` groups v4 by ``TRIM(team_id)`` and
``TRIM(customer_name)`` under ``_scope_where`` and counts days since the last
PAYING load (``total_charge <> 0``) from ``cst_today()``. This module reuses that
exact WHERE (imported, never copied) so a customer the tab shows at 29 days is
the customer the job sees at 29 days.

The statement is built here and executed by both the job and the live PREPARE
test — a verification that held its own copy would prove nothing (cron-job-debug §1b).
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from typing import Any, Optional

from app.routers.attrition_wow import _scope_where
from app.services.attrition_pipedrive.config import MAX_FEED_AGE_HOURS, READ_WINDOW_DAYS

# Every team the report shows — TEAM5 included, so a skip is visible in the log.
TEAMS = ("TEAM1", "TEAM2", "TEAM3", "TEAM4", "TEAM5", "TEAM-DFW")

# Unfiltered on purpose: the feed's own clock, not one team's activity.
FRESHNESS_SQL = "SELECT MAX(updated_dt) AS as_of FROM public.mcleod_gld_budget_report_v4"


class StaleFeedError(RuntimeError):
    """v4 is older than MAX_FEED_AGE_HOURS — acting would age every customer falsely."""


@dataclass(frozen=True)
class Candidate:
    team: str
    customer: str
    last_load_date: date
    days_since: int
    # Newest-first McLeod customer codes the name traded under (``ID_McLeod``).
    mcleod_ids: tuple[str, ...]


def candidates_sql() -> tuple[str, list[Any]]:
    """The statement and its params, minus the read floor (appended by the caller)."""
    params: list[Any] = []
    where = _scope_where("br4", list(TEAMS), None, None, None, params)
    params.append(None)  # placeholder for the read floor
    p_floor = len(params)
    sql = f"""
        SELECT
          TRIM(br4.team_id)       AS team,
          TRIM(br4.customer_name) AS customer,
          MAX(br4.origin_actual_departure::date) AS last_load_date,
          ARRAY_REMOVE(
            ARRAY_AGG(NULLIF(TRIM(br4.customer_id), '') ORDER BY br4.origin_actual_departure DESC),
            NULL
          ) AS mcleod_ids
        FROM public.mcleod_gld_budget_report_v4 br4
        WHERE {where}
          AND br4.total_charge <> 0
          AND br4.origin_actual_departure >= ${p_floor}
          AND TRIM(COALESCE(br4.customer_name, '')) <> ''
        GROUP BY 1, 2
    """
    return sql, params


def _dedupe(ids: Optional[list[str]]) -> tuple[str, ...]:
    seen: dict[str, None] = {}
    for i in ids or []:
        seen.setdefault(i, None)
    return tuple(seen)


async def assert_fresh(pool, now: datetime) -> datetime:
    """Raise StaleFeedError unless v4 was written within MAX_FEED_AGE_HOURS.

    ``updated_dt`` is naive CST wall time (gold is already CST); ``now`` is aware CST.
    """
    as_of = await pool.fetchval(FRESHNESS_SQL)
    if as_of is None:
        raise StaleFeedError("budget_report_v4 has no rows")
    age = now.replace(tzinfo=None) - as_of
    if age > timedelta(hours=MAX_FEED_AGE_HOURS):
        raise StaleFeedError(f"budget_report_v4 last written {as_of:%Y-%m-%d %H:%M} ({age} ago)")
    return as_of


async def fetch_candidates(pool, today: date) -> list[Candidate]:
    sql, params = candidates_sql()
    # origin_actual_departure is a naive timestamp; bind a datetime, not a date.
    params[-1] = datetime.combine(today - timedelta(days=READ_WINDOW_DAYS), time())
    rows = await pool.fetch(sql, *params)
    out = [
        Candidate(
            team=r["team"],
            customer=r["customer"],
            last_load_date=r["last_load_date"],
            days_since=(today - r["last_load_date"]).days,
            mcleod_ids=_dedupe(r["mcleod_ids"]),
        )
        for r in rows
    ]
    out.sort(key=lambda c: (c.team, c.customer))
    return out
