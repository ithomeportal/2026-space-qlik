"""Door-data health for every Access Log Doors report (2026-11-18).

GET /api/custom/<report-key>/door-feed-health?date=YYYY-MM-DD

WHY. On 2026-11-16 at 11:28 Monterrey the 2ND FLOOR reader — the main entrance,
~270 punches on a weekday — stopped reaching `zk_gld_onlyfingerprint`, and
SITE MTY at 08:58. 3F Door and IT ROOM kept syncing, so the feed's newest record
stayed current and every freshness signal read healthy. The reports then told
HR, with full confidence, that most of the building "did not come in" and that
Alan Santiago arrived at 10:33 (his earlier badge never reached the table).
An unfiltered `max(event_time)` cannot see a dead reader while another one is
alive; only a per-reader count against its own normal can.

RULE (mirrors the n8n Late Arrivals `readers` CTE — change both together):
  * per reader, punches on the date up to a cutoff — Monterrey now() when the
    date is today there, else the whole day — exit button (200) excluded;
  * baseline = MEDIAN of the same count on the 4 previous same weekdays
    (a median, so one earlier outage or holiday cannot drag the normal down);
  * a reader is DOWN when baseline >= 15 and today < 25 % of it — a reader that
    is quiet anyway (SITE MTY, weekends) can never trip it;
  * the building is DEGRADED when the summed baseline >= 30 and the summed
    count < 40 % of it (catches a whole-feed gap, e.g. 11-17 before 10:22).
SQL returns counts only; `classify_door_feed` decides, so the thresholds are
unit-tested without a database.

The reply names readers and counts — never a person — so it is the same for
every scope-locked clone and safe for the AI-chat section allowlist.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import date
from statistics import median
from typing import Any

from fastapi import APIRouter, Depends, Query, Request

from app.clock import cst_today
from app.routers.deps import get_datalake_gold_pool

BASELINE_WEEKS = 4
READER_MIN_BASELINE = 15
READER_DOWN_RATIO = 0.25
BUILDING_MIN_BASELINE = 30
BUILDING_DEGRADED_RATIO = 0.40

# $1 = the date. `k` = weeks back (0 = the date itself). One grouped pass over
# five event_date values (index-friendly), plus a 28-day max for "last record".
FEED_HEALTH_SQL = f"""
WITH cut AS (
    SELECT CASE
             WHEN $1::date = (now() AT TIME ZONE 'America/Monterrey')::date
               THEN (now() AT TIME ZONE 'America/Monterrey')::time
             ELSE TIME '23:59:59.999999'
           END AS t
),
days AS (
    SELECT ($1::date - 7 * k)::date AS d, k
      FROM generate_series(0, {BASELINE_WEEKS}) AS k
),
counts AS (
    SELECT z.event_point_name AS reader, days.k, count(*)::int AS n
      FROM public.zk_gld_onlyfingerprint z
      JOIN days ON days.d = z.event_date
     CROSS JOIN cut
     WHERE z.event_date IN (SELECT d FROM days)
       AND z.verify_mode_no IS DISTINCT FROM 200
       AND z.event_time::time <= cut.t
     GROUP BY 1, 2
),
last_seen AS (
    SELECT z.event_point_name AS reader, max(z.event_time) AS last_event
      FROM public.zk_gld_onlyfingerprint z
     WHERE z.event_date BETWEEN $1::date - 28 AND $1::date
       AND z.verify_mode_no IS DISTINCT FROM 200
     GROUP BY 1
)
SELECT n.reader, n.k, n.n,
       (l.last_event AT TIME ZONE 'America/Monterrey'
                     AT TIME ZONE 'America/Chicago') AS last_event_cst,
       (SELECT t FROM cut) AS cutoff
  FROM counts n
  LEFT JOIN last_seen l USING (reader)
 ORDER BY n.reader, n.k
"""


@dataclass(frozen=True)
class ReaderHealth:
    reader: str
    today: int
    baseline: float
    last_event_cst: str | None
    down: bool


@dataclass(frozen=True)
class FeedHealth:
    readers: tuple[ReaderHealth, ...]
    total_today: int
    total_baseline: float
    building_degraded: bool

    @property
    def down(self) -> tuple[str, ...]:
        return tuple(r.reader for r in self.readers if r.down)

    @property
    def degraded(self) -> bool:
        return self.building_degraded or bool(self.down)


def classify_reader(today: int, baseline: float) -> bool:
    """True when a normally busy reader has (nearly) gone silent."""
    return baseline >= READER_MIN_BASELINE and today < READER_DOWN_RATIO * baseline


def classify_building(total_today: int, total_baseline: float) -> bool:
    return (
        total_baseline >= BUILDING_MIN_BASELINE
        and total_today < BUILDING_DEGRADED_RATIO * total_baseline
    )


def classify_door_feed(rows: Iterable[dict[str, Any]]) -> FeedHealth:
    """Rows: {reader, k, n, last_event_cst}. A (reader, k) pair with no row is a
    zero — a reader silent all day is exactly the case this exists to catch."""
    counts: dict[str, dict[int, int]] = {}
    last: dict[str, str | None] = {}
    for r in rows:
        name = r["reader"] or "(unnamed reader)"
        counts.setdefault(name, {})[int(r["k"])] = int(r["n"])
        ts = r.get("last_event_cst")
        last[name] = ts.isoformat() if hasattr(ts, "isoformat") else ts

    readers = []
    for name in sorted(counts):
        by_k = counts[name]
        today = by_k.get(0, 0)
        baseline = float(median(by_k.get(k, 0) for k in range(1, BASELINE_WEEKS + 1)))
        readers.append(
            ReaderHealth(name, today, baseline, last.get(name), classify_reader(today, baseline))
        )
    total_today = sum(r.today for r in readers)
    total_baseline = float(sum(r.baseline for r in readers))
    return FeedHealth(
        readers=tuple(readers),
        total_today=total_today,
        total_baseline=total_baseline,
        building_degraded=classify_building(total_today, total_baseline),
    )


def feed_health_payload(day: date, health: FeedHealth, cutoff: Any) -> dict[str, Any]:
    return {
        "date": day.isoformat(),
        "cutoff": cutoff.isoformat() if hasattr(cutoff, "isoformat") else cutoff,
        "degraded": health.degraded,
        "building_degraded": health.building_degraded,
        "down": list(health.down),
        "total_today": health.total_today,
        "total_baseline": health.total_baseline,
        "readers": [
            {
                "reader": r.reader,
                "today": r.today,
                "baseline": r.baseline,
                "last_event": r.last_event_cst,
                "down": r.down,
            }
            for r in health.readers
        ],
    }


def add_door_feed_health_route(router: APIRouter, guard: Callable[..., Any]) -> None:
    """Mount GET /door-feed-health on a report router behind ITS OWN gate.

    Every Access Doors report (HR + each scope-locked clone) calls this with the
    guard it already uses, so access is decided exactly as for the report."""

    @router.get("/door-feed-health")
    async def door_feed_health(
        request: Request,
        date_: date | None = Query(None, alias="date", description="YYYY-MM-DD, default today"),
        _user: dict = Depends(guard),
    ):
        day = date_ or cst_today()
        pool = get_datalake_gold_pool(request)
        rows = await pool.fetch(FEED_HEALTH_SQL, day)
        records = [dict(r) for r in rows]
        cutoff = records[0]["cutoff"] if records else None
        health = classify_door_feed(records)
        return {"success": True, "data": feed_health_payload(day, health, cutoff)}
