"""Customer Lifespan — the Summary tab (deck p.2): what to track and where to focus.

Five tiles with their "same period last year" comparison and the five tables behind
them. Every table is exactly the customers its tile counts. Pure, except that the
router loads ``RECENT_SQL``.

Definitions (operator-visible in the plan, 2026-11-04):
* Active / At risk compare with the same DATE last year; First-year, Lost and
  Recovered with the same PERIOD last year.
* "Loads last 30 days", "Profit last 90 days" and the declining baseline are FIXED
  windows back from the period end, as their titles say: the Date filter decides
  WHICH customers are listed, never how long those windows are. A shorter range
  would make the titles false.
* Declining volume: a customer not lost whose loads in the last 30 days are under
  its monthly average over the 365 days before them (or since its first load).
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from typing import Callable

from app.services.customer_lifespan_core import (
    Customer,
    flow_events,
    is_first_year,
    month_index,
)

RECENT_DAYS = 30
BASELINE_DAYS = 365
PROFIT_DAYS = 90
DAYS_PER_MONTH = 365 / 12
MIN_BASELINE_DAYS = 30      # a shorter baseline turns one load into a huge "average"
MIN_AVG_MONTHLY_LOADS = 2.0 # under this, one load more or less is noise

#: Exact-day facts the month rows cannot give, per customer × division up to ``$1``.
RECENT_SQL = """
SELECT customer_id, division,
       COUNT(*) FILTER (WHERE ship_date > $1::date - 30)::int              AS loads_30,
       COUNT(*) FILTER (WHERE ship_date <= $1::date - 30)::int             AS loads_base,
       COALESCE(SUM(margin) FILTER (WHERE ship_date > $1::date - 90), 0)::float8 AS margin_90
  FROM customer_lifespan_orders
 WHERE NOT voided_in_datalake
   AND ship_date > $1::date - 395 AND ship_date <= $1::date
 GROUP BY customer_id, division
"""


@dataclass(frozen=True)
class Recent:
    loads_30: int = 0
    loads_base: int = 0
    margin_90: float = 0.0


def merge_recent(rows, division: str) -> dict[str, Recent]:
    wanted = None if division == "all" else division.upper()
    out: dict[str, Recent] = {}
    for r in rows:
        if wanted and r["division"] != wanted:
            continue
        p = out.get(r["customer_id"], Recent())
        out[r["customer_id"]] = Recent(p.loads_30 + r["loads_30"], p.loads_base + r["loads_base"],
                                       p.margin_90 + float(r["margin_90"] or 0))
    return out


def tile_counts(customers: list[Customer], as_of: date, window: int, start: date) -> dict[str, int]:
    events = [flow_events(c, window, start) for c in customers]
    return {
        "active": sum(1 for c in customers if c.status == "active"),
        "at_risk": sum(1 for c in customers if c.status == "at_risk"),
        "first_year": sum(1 for c in customers if is_first_year(c, as_of)),
        "lost": sum(1 for lost, _ in events if lost),
        "recovered": sum(1 for _, back in events if back),
    }


def _tile(value: int, prior: int | None) -> dict:
    delta = round((value - prior) / prior * 100, 1) if prior else None
    return {"value": value, "prior": prior, "delta_pct": delta}


def baseline_days(first_ship: date, as_of: date) -> int:
    """Days of the 365-day baseline the customer actually existed for."""
    end = as_of - timedelta(days=RECENT_DAYS)
    return max(min((end - first_ship).days + 1, BASELINE_DAYS), 0)


def declining(customers: list[Customer], recent: dict[str, Recent], as_of: date,
              assign: Callable[[Customer], dict]) -> list[dict]:
    rows = []
    for c in customers:
        days = baseline_days(c.first_ship, as_of)
        r = recent.get(c.customer_id)
        if c.status == "lost" or r is None or days < MIN_BASELINE_DAYS:
            continue
        avg = r.loads_base / (days / DAYS_PER_MONTH)
        if avg < MIN_AVG_MONTHLY_LOADS or r.loads_30 >= avg:
            continue
        rows.append({
            "customer_id": c.customer_id, "name": c.name, **assign(c),
            "avg_monthly_loads": round(avg, 1), "loads_30d": r.loads_30,
            "change": round(r.loads_30 - avg, 1),
            "change_pct": round((r.loads_30 - avg) / avg * 100, 1),
        })
    return sorted(rows, key=lambda x: x["change"])


def board(customers: list[Customer], prior: dict[str, int] | None, recent: dict[str, Recent],
          as_of: date, window: int, start: date, assignments) -> dict:
    """``prior`` = ``tile_counts`` of the same period last year (None for "all time")."""
    def assign(c: Customer) -> dict:
        return assignments.of(c.customer_id, c.status)

    def base(c: Customer) -> dict:
        return {"customer_id": c.customer_id, "name": c.name, "status": c.status, **assign(c),
                "age_months": month_index(as_of) - month_index(c.first_ship),
                "days_since_last": c.days_since_last, "last_ship": c.last_ship}

    counts = tile_counts(customers, as_of, window, start)
    events = {c.customer_id: flow_events(c, window, start) for c in customers}
    lost = [c for c in customers if events[c.customer_id][0]]
    back = [c for c in customers if events[c.customer_id][1]]
    at_risk = [{**base(c), "profit_90d": round(recent.get(c.customer_id, Recent()).margin_90, 2)}
               for c in customers if c.status == "at_risk"]
    first_year = sorted((c for c in customers if is_first_year(c, as_of)),
                        key=lambda c: c.first_ship, reverse=True)
    return {
        "tiles": {k: _tile(v, prior[k] if prior else None) for k, v in counts.items()},
        "at_risk": sorted(at_risk, key=lambda r: -r["profit_90d"]),
        "first_year": [base(c) for c in first_year],
        "declining": declining(customers, recent, as_of, assign),
        "lost": [base(c) for c in sorted(lost, key=lambda c: events[c.customer_id][0][-1], reverse=True)],
        "lost_since_returned": sum(1 for c in lost if c.status != "lost"),
        "recovered": sorted(({**base(c), "returned_on": events[c.customer_id][1][-1]} for c in back),
                            key=lambda r: r["returned_on"], reverse=True),
    }
