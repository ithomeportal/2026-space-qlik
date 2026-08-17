"""Monthly headcount snapshot — the one number we cannot reconstruct later.

WHY THIS EXISTS
---------------
Turnover needs a denominator: headcount *during* the period. The time-off `users`
table cannot supply that for any past month, because it is a **current-state**
table that drops departed staff as they age out — measured 2026-08-17, it held
only 25% of the people actually onboarded in 2024 (30 rows vs 119 FreshService
onboarding tickets), rising to 89% for 2026. Reading a past year's headcount out
of it therefore returns today's survivors, not that year's staff.

There is no way to recover this after the fact. Every month without a snapshot is
a month of turnover history lost permanently. So we start recording now, and
`Exec Meeting – Recruitment` shows prior-year turnover as "—" until enough months
accumulate rather than publishing a reconstructed (wrong) figure.

DESIGN
------
* **Daily, not monthly.** The job upserts the *current* month's rows every day.
  A once-a-month job gets exactly one attempt, and Render's free tier spins the
  dyno down — a single missed firing would lose that month forever. Upserting
  daily is self-healing: a missed day is corrected the next day, and the last
  write of any month is that month's closing headcount.
* **Same definition as the KPI card.** Headcount comes from
  `active_headcount_by_department()`, the single definition shared with the
  report (§69). If the snapshot used its own query, the turnover denominator
  would silently stop matching the headcount printed beside it.
* Rows are keyed `(snapshot_month, department)` so re-running is idempotent.
  Departments are canonical display names; `Unassigned` is kept so that
  SUM(headcount) equals total headcount.
"""

from __future__ import annotations

import logging
from datetime import date

from app.clock import cst_today
from app.routers.exec_meeting_recruitment import active_headcount_by_department

logger = logging.getLogger(__name__)


def _month_start(day: date) -> date:
    return day.replace(day=1)


async def capture_headcount_snapshot(hub_pool, timeoff_pool) -> dict:
    """Upsert the current month's headcount-by-department into `analytics_hub`.

    Returns a summary dict. Never raises for an empty source — an empty result
    is logged and skipped rather than written, because writing zeros would look
    exactly like "the company emptied out" a year from now.
    """
    if hub_pool is None or timeoff_pool is None:
        logger.warning("Headcount snapshot skipped — pools not configured")
        return {"skipped": "pools not configured"}

    month = _month_start(cst_today())
    counts = await active_headcount_by_department(timeoff_pool)

    if not counts:
        # A real company never has zero active employees. Empty means the read
        # failed or the source is broken; recording it would poison the series.
        logger.error(
            "Headcount snapshot for %s returned NO rows — refusing to write "
            "zeros. Check the time-off pool's grants on users.",
            month,
        )
        return {"month": month.isoformat(), "skipped": "source returned no rows"}

    total = sum(counts.values())
    for department, headcount in sorted(counts.items()):
        await hub_pool.execute(
            """
            INSERT INTO headcount_snapshots (snapshot_month, department, headcount)
            VALUES ($1, $2, $3)
            ON CONFLICT (snapshot_month, department)
            DO UPDATE SET headcount = EXCLUDED.headcount, captured_at = NOW()
            """,
            month,
            department,
            headcount,
        )

    logger.info(
        "Headcount snapshot %s — %d employees across %d departments",
        month,
        total,
        len(counts),
    )
    return {"month": month.isoformat(), "total": total, "departments": len(counts)}


async def average_headcount_for_year(
    hub_pool, year: int, department: str | None = None
) -> float | None:
    """Mean of the monthly headcounts recorded for `year`, or None if none are.

    Returning None is meaningful and must be preserved: it is what makes the
    report render "—" instead of inventing a turnover rate for a year we were
    not yet recording.
    """
    if hub_pool is None:
        return None

    if department:
        rows = await hub_pool.fetch(
            """
            SELECT headcount FROM headcount_snapshots
             WHERE EXTRACT(YEAR FROM snapshot_month)::int = $1
               AND department = $2
            """,
            year,
            department,
        )
    else:
        rows = await hub_pool.fetch(
            """
            SELECT SUM(headcount)::int AS headcount
              FROM headcount_snapshots
             WHERE EXTRACT(YEAR FROM snapshot_month)::int = $1
             GROUP BY snapshot_month
            """,
            year,
        )

    values = [r["headcount"] for r in rows if r["headcount"] is not None]
    if not values:
        return None
    return sum(values) / len(values)
