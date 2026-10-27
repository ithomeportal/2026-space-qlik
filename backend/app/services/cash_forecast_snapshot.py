"""Collections Settlement Forecast — the daily stored forecast (accuracy tab).

A forecast recomputed today cannot say what was forecast LAST week: the AR
snapshot drops paid invoices and the settlement schedule moves on. The CFO's
sheet compares forecast vs actual per week, so the forecast must be STORED the
day it is made (cf. ``daily_projection_snapshot``, §84). One row per
(snapshot day, forecast week) in analytics_hub, written at 06:30 CST — after
UNLK-Financial's 01:00 CT McLeod sync.

A run that read EVERY source overwrites the day's rows (the 06:30 run is
authoritative over an early catch-up); a partial run only FILLS fields that are
still NULL — it can never replace a complete observation with a partial one.
"""
from __future__ import annotations

import logging
from datetime import date, timedelta

from app.services.cash_forecast import HORIZON_WEEKS, finance_week
from app.services.cash_forecast_sources import load_sources
from app.services.cash_forecast_weeks import compute_all

logger = logging.getLogger(__name__)

SNAPSHOT_DDL = """
CREATE TABLE IF NOT EXISTS cash_forecast_snapshot (
  snapshot_date  DATE          NOT NULL,
  week_start     DATE          NOT NULL,
  week_offset    SMALLINT      NOT NULL,
  in_expected    NUMERIC(18,2),
  in_committed   NUMERIC(18,2),
  in_run_rate    NUMERIC(18,2),
  settlements    NUMERIC(18,2),
  ap             NUMERIC(18,2),
  out_basis      TEXT,
  complete       BOOLEAN       NOT NULL DEFAULT FALSE,
  captured_at    TIMESTAMPTZ   NOT NULL DEFAULT NOW(),
  PRIMARY KEY (snapshot_date, week_start)
)
"""

_INSERT = """
INSERT INTO cash_forecast_snapshot
  (snapshot_date, week_start, week_offset, in_expected, in_committed, in_run_rate,
   settlements, ap, out_basis, complete)
VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10)
ON CONFLICT (snapshot_date, week_start) DO UPDATE SET
"""
_COLS = ("in_expected", "in_committed", "in_run_rate", "settlements", "ap", "out_basis")

#: A complete run replaces the day's row — unless that row is itself complete
#: (the first complete observation of the day stands).
UPSERT_COMPLETE_SQL = _INSERT + ",\n".join(
    f"  {c} = EXCLUDED.{c}" for c in (*_COLS, "complete")
) + ",\n  captured_at = NOW()\n WHERE NOT cash_forecast_snapshot.complete"

#: A partial run only fills what is still NULL.
UPSERT_PARTIAL_SQL = _INSERT + ",\n".join(
    f"  {c} = COALESCE(cash_forecast_snapshot.{c}, EXCLUDED.{c})" for c in _COLS
)

READ_SQL = """
SELECT snapshot_date, week_start, week_offset, in_expected, in_committed,
       in_run_rate, settlements, ap, complete
  FROM cash_forecast_snapshot
 WHERE week_start >= $1 AND week_offset <= 1
 ORDER BY week_start, snapshot_date
"""

HAS_TODAY_SQL = (
    "SELECT EXISTS (SELECT 1 FROM cash_forecast_snapshot WHERE snapshot_date = $1 AND complete)"
)


def snapshot_rows(today: date, result: dict, complete: bool) -> list[tuple]:
    """The rows to store for one day — pure, so a test can pin them."""
    committed = result["meta"]["this_week_committed_in"]
    return [
        (today, date.fromisoformat(r["week_start"]), r["week_offset"], r["cash_in"],
         committed if r["week_offset"] == 0 else None, r["in_run_rate"],
         r["settlements"], r["ap"], r["out_basis"], complete)
        for r in result["rows"]
    ]


async def capture_forecast_snapshot(hub_pool, financial_pool, gold_pool, today: date) -> dict:
    """Store today's forecast. RAISES when nothing usable could be read.

    A snapshot with every source unknown is not a snapshot: storing it would
    record a NULL forecast for the day. Partial reads are stored (missing fields
    stay NULL; a later complete run the same day replaces them).
    """
    if hub_pool is None or financial_pool is None:
        raise RuntimeError("cash forecast snapshot: analytics_hub or UNLK-Financial pool missing")
    src = await load_sources(financial_pool, gold_pool, finance_week(today), today)
    result = compute_all(src, HORIZON_WEEKS)
    if all(r["cash_in"] is None and r["settlements"] is None for r in result["rows"]):
        raise RuntimeError(f"cash forecast snapshot: no source readable ({', '.join(src.errors)})")
    complete = not src.errors
    rows = snapshot_rows(today, result, complete)
    async with hub_pool.acquire() as conn:
        async with conn.transaction():
            await conn.executemany(UPSERT_COMPLETE_SQL if complete else UPSERT_PARTIAL_SQL, rows)
    return {"snapshot_date": today.isoformat(), "rows": len(rows), "complete": complete,
            "failed_sources": src.errors}


async def read_snapshots(hub_pool, since: date) -> list[dict]:
    rows = await hub_pool.fetch(READ_SQL, since)
    return [dict(r) for r in rows]


async def has_snapshot(hub_pool, day: date) -> bool:
    """True when today already holds a COMPLETE snapshot."""
    return bool(await hub_pool.fetchval(HAS_TODAY_SQL, day))


def accuracy_since(week_start: date, weeks_back: int = 12) -> date:
    return week_start - timedelta(weeks=weeks_back + 1)
