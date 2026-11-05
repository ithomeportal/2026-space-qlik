"""Customer Lifespan (#69) — the ONE definition of a customer's lifespan and status.

Pure functions over customer × month rows (``CUSTOMER_MONTHS_SQL``); the router
only loads and caches. Definitions (request 2026-10-29, "2016-2026 Analysis.xlsx"):

* **Lifespan** = months between the first and the last month with a load —
  the workbook's ``ROUND((Finish-Start)/365*12)``, so a one-month customer is 0.
* **Status** (decided 2026-10-29 — NOT the workbook's "shipped in the extract's
  last month", which flips a customer to Lost after one quiet month):
  ``active`` = last load ≤ 30 days before the data's as-of date, ``at_risk`` =
  31 days … the silence WINDOW (60/90/180, default 90), ``lost`` = beyond it.
* **Reactivation** = a load after a silence longer than the window. 150 of 421
  workbook customers did that; first → last lifespan alone hides it.

Everything is keyed on the McLeod customer ID (409 in the workbook), never on the
name (421 — customers were renamed).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta
from itertools import pairwise

from app.clock import CST_NOW_DATE_SQL

AT_RISK_AFTER_DAYS = 30
WINDOWS = (60, 90, 180)
DEFAULT_WINDOW = 90
DIVISIONS = ("all", "corp", "dfw")
FIRST_YEAR_DAYS = 365
LIFESPAN_BUCKETS = (
    (0, 0, "1 month"),
    (1, 5, "2–6 months"),
    (6, 11, "7–12 months"),
    (12, 23, "1–2 years"),
    (24, 47, "2–4 years"),
    (48, 95, "4–8 years"),
    (96, 10_000, "8+ years"),
)

#: Departures dated after today (seen 2026-10-29: one order on 10-30) wait for
#: their day — they would push as-of into the future and past the month range.
CUSTOMER_MONTHS_SQL = f"""
SELECT customer_id,
       date_trunc('month', ship_date)::date                   AS month,
       division,
       COUNT(*)::int                                          AS loads,
       SUM(revenue)::float8                                   AS revenue,
       SUM(margin)::float8                                    AS margin,
       MIN(ship_date)                                         AS first_ship,
       MAX(ship_date)                                         AS last_ship,
       (ARRAY_AGG(customer_name ORDER BY ship_date DESC))[1]  AS name
  FROM customer_lifespan_orders
 WHERE NOT voided_in_datalake
   AND ship_date <= {CST_NOW_DATE_SQL}
 GROUP BY customer_id, date_trunc('month', ship_date), division
"""

#: The same rows limited to a date range (the Date filter, operator decision
#: 2026-11-04: it filters everything). ``first_ship``/``last_ship`` are clipped to it.
CUSTOMER_MONTHS_RANGE_SQL = f"""
SELECT customer_id,
       date_trunc('month', ship_date)::date                   AS month,
       division,
       COUNT(*)::int                                          AS loads,
       SUM(revenue)::float8                                   AS revenue,
       SUM(margin)::float8                                    AS margin,
       MIN(ship_date)                                         AS first_ship,
       MAX(ship_date)                                         AS last_ship,
       (ARRAY_AGG(customer_name ORDER BY ship_date DESC))[1]  AS name
  FROM customer_lifespan_orders
 WHERE NOT voided_in_datalake
   AND ship_date >= $1::date AND ship_date <= $2::date
   AND ship_date <= {CST_NOW_DATE_SQL}
 GROUP BY customer_id, date_trunc('month', ship_date), division
"""


@dataclass(frozen=True)
class Month:
    """One customer × calendar month, divisions merged per the requested scope."""

    customer_id: str
    name: str
    month: date
    loads: int
    revenue: float
    margin: float
    first_ship: date
    last_ship: date
    divisions: frozenset[str]


@dataclass(frozen=True)
class Customer:
    customer_id: str
    name: str
    first_ship: date
    last_ship: date
    lifespan_months: int
    active_months: int
    loads: int
    revenue: float
    margin: float
    reactivations: int
    days_since_last: int
    status: str
    cohort_year: int
    divisions: tuple[str, ...]
    months: tuple[Month, ...]
    #: Every month up to the period end. ``months`` holds only those in the period;
    #: flows and the true first load read this one.
    history: tuple[Month, ...] = field(default=())


def month_index(d: date) -> int:
    return d.year * 12 + d.month - 1


def month_of(index: int) -> date:
    return date(index // 12, index % 12 + 1, 1)


def month_label(d: date) -> str:
    return f"{d.year}-{d.month:02d}"


def month_end(d: date) -> date:
    return month_of(month_index(d) + 1) - timedelta(days=1)


def pct(part: float, whole: float) -> float | None:
    """Margin % over a POSITIVE revenue only — a negative base flips the sign (§113)."""
    return round(part / whole * 100, 2) if whole > 0 else None


def status_of(days_since_last: int, window: int) -> str:
    if days_since_last <= AT_RISK_AFTER_DAYS:
        return "active"
    return "at_risk" if days_since_last <= window else "lost"


def merge_rows(rows, division: str) -> list[Month]:
    """SQL rows → ``Month`` per (customer, month) inside ``division``."""
    if division not in DIVISIONS:
        raise ValueError(f"unknown division {division!r}")
    wanted = None if division == "all" else division.upper()
    acc: dict[tuple[str, date], Month] = {}
    for r in rows:
        if wanted and r["division"] != wanted:
            continue
        key = (r["customer_id"], r["month"])
        cur = Month(r["customer_id"], r["name"] or r["customer_id"], r["month"], r["loads"],
                    float(r["revenue"] or 0), float(r["margin"] or 0), r["first_ship"],
                    r["last_ship"], frozenset({r["division"]}))
        prev = acc.get(key)
        if prev is not None:
            cur = Month(
                cur.customer_id,
                cur.name if cur.last_ship >= prev.last_ship else prev.name,
                cur.month, prev.loads + cur.loads, prev.revenue + cur.revenue,
                prev.margin + cur.margin, min(prev.first_ship, cur.first_ship),
                max(prev.last_ship, cur.last_ship), prev.divisions | cur.divisions,
            )
        acc[key] = cur
    return sorted(acc.values(), key=lambda m: (m.customer_id, m.month))


def _customer(ms: list[Month], as_of: date, window: int) -> Customer:
    first, last = ms[0], ms[-1]
    days = (as_of - last.last_ship).days
    return Customer(
        customer_id=first.customer_id,
        name=max(ms, key=lambda m: m.last_ship).name,
        first_ship=first.first_ship,
        last_ship=last.last_ship,
        lifespan_months=month_index(last.month) - month_index(first.month),
        active_months=len(ms),
        loads=sum(m.loads for m in ms),
        revenue=sum(m.revenue for m in ms),
        margin=sum(m.margin for m in ms),
        reactivations=sum(1 for a, b in pairwise(ms) if (b.first_ship - a.last_ship).days > window),
        days_since_last=days,
        status=status_of(days, window),
        cohort_year=first.first_ship.year,
        divisions=tuple(sorted(set().union(*(m.divisions for m in ms)))),
        months=tuple(ms),
        history=tuple(ms),
    )


def build_customers(months: list[Month], as_of: date, window: int) -> list[Customer]:
    by_id: dict[str, list[Month]] = {}
    for m in months:
        by_id.setdefault(m.customer_id, []).append(m)
    return [_customer(sorted(ms, key=lambda m: m.month), as_of, window) for ms in by_id.values()]


def _median(values: list[float]) -> float | None:
    s = sorted(values)
    if not s:
        return None
    mid = len(s) // 2
    return float(s[mid]) if len(s) % 2 else (s[mid - 1] + s[mid]) / 2


def _mean(values: list[float]) -> float | None:
    return round(sum(values) / len(values), 2) if values else None


def bucket_of(lifespan_months: int) -> str:
    return next(label for lo, hi, label in LIFESPAN_BUCKETS if lo <= lifespan_months <= hi)


def flow_events(c: Customer, window: int, start: date = date.min) -> tuple[list[date], list[date]]:
    """(last load before each loss, first load of each return) inside the period.

    A loss belongs to the customer's LAST LOAD, and counts only once the silence
    is longer than the window. ONE source for the KPI tiles, the flow chart's
    bars and the lists behind them, so the three cannot disagree. A customer lost
    and won back counts as both (review 2026-10-29).
    """
    gaps = [(a, b) for a, b in pairwise(c.history) if (b.first_ship - a.last_ship).days > window]
    lost = [a.last_ship for a, _ in gaps if a.last_ship >= start]
    back = [b.first_ship for _, b in gaps if b.first_ship >= start]
    if c.status == "lost":
        lost.append(c.last_ship)
    return lost, back


def is_new(c: Customer, start: date = date.min) -> bool:
    """The customer's TRUE first load is in the period — not its first load in the range."""
    return c.first_ship >= start


def is_first_year(c: Customer, as_of: date) -> bool:
    return c.first_ship > as_of - timedelta(days=FIRST_YEAR_DAYS)


def summary(customers: list[Customer], as_of: date, window: int, start: date = date.min,
            customers_total: int | None = None) -> dict:
    """The KPI strip over the customers with a load in the period.

    ``lost_period`` / ``reactivated_period`` count customers, not events: a
    customer with two losses in the period is one customer.
    ``customers_total`` is the all-time count under the same teams + customer.
    """
    base = [c for c in customers if c.status != "lost"]
    lost = [c for c in customers if c.status == "lost"]
    events = [flow_events(c, window, start) for c in customers]
    revenue = [c.revenue for c in customers]
    total = sum(revenue)
    return {
        "customers_total": len(customers) if customers_total is None else customers_total,
        "customers_in_period": len(customers),
        "base": len(base),
        "active": sum(1 for c in base if c.status == "active"),
        "at_risk": sum(1 for c in base if c.status == "at_risk"),
        "lost": len(lost),
        "new_period": sum(1 for c in customers if is_new(c, start)),
        "lost_period": sum(1 for lost_on, _ in events if lost_on),
        "reactivated_period": sum(1 for _, back in events if back),
        "avg_lifespan_lost": _mean([c.lifespan_months for c in lost]),
        "median_lifespan_lost": _median([c.lifespan_months for c in lost]),
        "avg_lifespan_base": _mean([c.lifespan_months for c in base]),
        "revenue_period": round(total, 2),
        "margin_period": round(sum(c.margin for c in customers), 2),
        "top10_share": pct(sum(sorted(revenue, reverse=True)[:10]), total),
        "first_ship": min((c.first_ship for c in customers), default=None),
    }


def _spark(c: Customer, as_of: date, months: int = 24) -> list[float]:
    end = month_index(as_of)
    by = {month_index(m.month): m.revenue for m in c.history}
    return [round(by.get(i, 0.0), 2) for i in range(end - months + 1, end + 1)]


def customer_row(c: Customer, as_of: date, assignment: dict | None = None) -> dict:
    """``assignment``: team / Sales Exec. (``customer_lifespan_scope.Assignments.of``)."""
    return {
        "team": None, "assigned_to": None, "pending_assignment": False, **(assignment or {}),
        "customer_id": c.customer_id,
        "name": c.name,
        "divisions": list(c.divisions),
        "first_ship": c.first_ship,
        "last_ship": c.last_ship,
        "lifespan_months": c.lifespan_months,
        "lifespan_bucket": bucket_of(c.lifespan_months),
        "age_months": month_index(as_of) - month_index(c.first_ship),
        "active_months": c.active_months,
        "loads": c.loads,
        "revenue": round(c.revenue, 2),
        "margin": round(c.margin, 2),
        "margin_pct": pct(c.margin, c.revenue),
        "avg_monthly_margin": round(c.margin / c.active_months, 2),
        "reactivations": c.reactivations,
        "days_since_last": c.days_since_last,
        "status": c.status,
        "cohort_year": c.cohort_year,
        "months_active": [month_label(m.month) for m in c.months],
        "spark_24m": _spark(c, as_of),
    }


def customer_detail(c: Customer, as_of: date, assignment: dict | None = None) -> dict:
    """Every month from the first load in the period to its end, zero-filled."""
    by = {month_index(m.month): m for m in c.months}
    series = []
    for i in range(month_index(c.months[0].month), month_index(as_of) + 1):
        m = by.get(i)
        rev, mar = (m.revenue, m.margin) if m else (0.0, 0.0)
        series.append({"month": month_label(month_of(i)), "loads": m.loads if m else 0,
                       "revenue": round(rev, 2), "margin": round(mar, 2),
                       "margin_pct": pct(mar, rev)})
    return {**customer_row(c, as_of, assignment), "series": series}
