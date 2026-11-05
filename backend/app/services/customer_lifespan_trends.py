"""Customer Lifespan (#69) — trend, cohorts and survival over ``Customer`` rows. Pure.

Flow events per month (they replace the workbook's four quarterly bar charts):

* **new** — the customer's first month with a load;
* **lost** — the last month before a silence longer than the window, counted
  only once that silence is CONFIRMED (a customer quiet for 40 days under a
  90-day window is not lost yet — the workbook counted it lost at once);
* **reactivated** — the first month back after such a silence;
* **active** — customers with a load in the month (the workbook's "Active
  Customers"); **base** — customers with a load inside the window at month end.

Survival is a Kaplan–Meier curve over tenure in months: a lost customer is an
event, a customer still in the base is CENSORED at the as-of month. Averaging
first → last lifespans instead would count every 2026 customer as short-lived.
"""
from __future__ import annotations

from datetime import date

from app.services.customer_lifespan_core import (
    LIFESPAN_BUCKETS,
    Customer,
    flow_events,
    is_new,
    month_end,
    month_index,
    month_label,
    month_of,
    pct,
)

GRAINS = ("month", "quarter", "year")

def _base_at(c: Customer, end: date, window: int) -> bool:
    """Had a load in the ``window`` days up to ``end`` (a month end, or as-of)."""
    last = None
    for m in c.history:
        if m.first_ship > end:
            break
        last = min(m.last_ship, end)
    return last is not None and (end - last).days <= window


def monthly(customers: list[Customer], as_of: date, window: int, start: date = date.min) -> list[dict]:
    months = [month_index(m.month) for c in customers for m in c.months]
    if not months:
        return []
    rows = {i: {"active": set(), "new": 0, "lost": 0, "reactivated": 0, "base": 0,
                "revenue": 0.0, "margin": 0.0} for i in range(min(months), month_index(as_of) + 1)}
    for c in customers:
        if is_new(c, start):
            rows[month_index(c.first_ship)]["new"] += 1
        lost, back = flow_events(c, window, start)
        for d in lost:
            rows[month_index(d)]["lost"] += 1
        for d in back:
            rows[month_index(d)]["reactivated"] += 1
        for m in c.months:
            r = rows[month_index(m.month)]
            r["active"].add(c.customer_id)
            r["revenue"] += m.revenue
            r["margin"] += m.margin
    for i, r in rows.items():
        cut = min(month_end(month_of(i)), as_of)
        r["base"] = sum(1 for c in customers if _base_at(c, cut, window))
    return [{"index": i, **r} for i, r in sorted(rows.items())]


def _period(index: int, grain: str) -> tuple[str, int]:
    d = month_of(index)
    if grain == "month":
        return month_label(d), index
    if grain == "quarter":
        q = (d.month - 1) // 3
        return f"{d.year} Q{q + 1}", d.year * 4 + q
    return str(d.year), d.year


def _period_end(d: date, grain: str) -> date:
    if grain == "month":
        return month_end(d)
    if grain == "quarter":
        return month_end(date(d.year, (d.month - 1) // 3 * 3 + 3, 1))
    return date(d.year, 12, 31)


def trend(customers: list[Customer], as_of: date, window: int, grain: str,
          start: date = date.min) -> list[dict]:
    if grain not in GRAINS:
        raise ValueError(f"unknown grain {grain!r}")
    out: dict[int, dict] = {}
    for r in monthly(customers, as_of, window, start):
        label, key = _period(r["index"], grain)
        p = out.setdefault(key, {"period": label, "active_ids": set(), "monthly_active": [],
                                 "new": 0, "lost": 0, "reactivated": 0, "base": 0,
                                 "revenue": 0.0, "margin": 0.0, "last_index": r["index"]})
        p["active_ids"] |= r["active"]
        p["monthly_active"].append(len(r["active"]))
        for k in ("new", "lost", "reactivated", "revenue", "margin"):
            p[k] += r[k]
        p["base"], p["last_index"] = r["base"], r["index"]
    rows = []
    for p in (out[k] for k in sorted(out)):
        active = len(p["active_ids"])
        partial = p["last_index"] == month_index(as_of) and as_of < _period_end(as_of, grain)
        rows.append({
            "period": p["period"],
            "active": active,
            "avg_monthly_active": round(sum(p["monthly_active"]) / len(p["monthly_active"]), 1),
            "new": p["new"], "reactivated": p["reactivated"], "lost": p["lost"],
            "net": p["new"] + p["reactivated"] - p["lost"],
            "base": p["base"],
            "revenue": round(p["revenue"], 2), "margin": round(p["margin"], 2),
            "margin_pct": pct(p["margin"], p["revenue"]),
            "margin_per_active": round(p["margin"] / active, 2) if active else None,
            "partial": partial,
        })
    return rows


def flow_members(customers: list[Customer], window: int, grain: str, period: str,
                 start: date = date.min) -> dict[str, list[dict]]:
    """Who is behind one period's bars: ONE ROW PER EVENT, so a list equals its bar."""
    def in_period(d: date) -> bool:
        return _period(month_index(d), grain)[0] == period

    out: dict[str, list[dict]] = {"new": [], "reactivated": [], "lost": []}
    for c in customers:
        row = {"customer_id": c.customer_id, "name": c.name, "status": c.status,
               "days_since_last": c.days_since_last}
        lost, back = flow_events(c, window, start)
        if is_new(c, start) and in_period(c.first_ship):
            out["new"].append({**row, "date": c.first_ship})
        out["reactivated"].extend({**row, "date": d} for d in back if in_period(d))
        out["lost"].extend({**row, "date": d} for d in lost if in_period(d))
    return {k: sorted(v, key=lambda e: (e["date"], e["name"]), reverse=True) for k, v in out.items()}


def _avg(values: list[float]) -> float | None:
    return round(sum(values) / len(values), 1) if values else None


def cohorts(customers: list[Customer], as_of: date, start: date = date.min) -> list[dict]:
    """One row per TRUE first-load year + its retention across the years in the range."""
    by_year: dict[int, list[Customer]] = {}
    for c in customers:
        by_year.setdefault(c.cohort_year, []).append(c)
    rows = []
    for year in sorted(by_year):
        cs = by_year[year]
        base = [c for c in cs if c.status != "lost"]
        lost = [c for c in cs if c.status == "lost"]
        retention = []
        for y in range(max(year, start.year), as_of.year + 1):
            shipped = sum(1 for c in cs if any(m.month.year == y for m in c.months))
            retention.append({"year": y, "customers": shipped, "pct": pct(shipped, len(cs))})
        rows.append({
            "cohort": year,
            "new": len(cs),
            "base_now": len(base),
            "active_now": sum(1 for c in base if c.status == "active"),
            "at_risk_now": sum(1 for c in base if c.status == "at_risk"),
            "lost": len(lost),
            "retained_pct": pct(len(base), len(cs)),
            "avg_lifespan_base": _avg([c.lifespan_months for c in base]),
            "avg_lifespan_lost": _avg([c.lifespan_months for c in lost]),
            "revenue": round(sum(c.revenue for c in cs), 2),
            "margin": round(sum(c.margin for c in cs), 2),
            "avg_monthly_margin": _avg([c.margin / c.active_months for c in cs]),
            "retention": retention,
        })
    return rows


def _tenure(c: Customer) -> tuple[int, bool]:
    """(tenure in months, event?) — a customer still in the base is censored at its last load.

    Censoring at as-of would credit an at-risk customer with up to ``window``
    silent days a lost one never gets (review 2026-10-29).
    """
    return c.lifespan_months + 1, c.status == "lost"


def survival(customers: list[Customer], as_of: date) -> dict:
    """Kaplan–Meier: share of customers still shipping after N months."""
    obs = sorted(_tenure(c) for c in customers)
    at_risk, s, points, median = len(obs), 1.0, [], None
    horizon = max((t for t, _ in obs), default=0)
    by_t: dict[int, tuple[int, int]] = {}
    for t, event in obs:
        d, n = by_t.get(t, (0, 0))
        by_t[t] = (d + int(event), n + 1)
    for t in range(1, horizon + 1):
        d, n = by_t.get(t, (0, 0))
        if at_risk > 0 and d:
            s *= 1 - d / at_risk
        points.append({"month": t, "survival": round(s * 100, 2), "at_risk": at_risk})
        if median is None and s <= 0.5:
            median = t
        at_risk -= n
    return {"points": points, "median_months": median}


def lifespan(customers: list[Customer], as_of: date) -> dict:
    buckets = []
    for lo, hi, label in LIFESPAN_BUCKETS:
        inside = [c for c in customers if lo <= c.lifespan_months <= hi]
        buckets.append({
            "bucket": label,
            "active": sum(1 for c in inside if c.status == "active"),
            "at_risk": sum(1 for c in inside if c.status == "at_risk"),
            "lost": sum(1 for c in inside if c.status == "lost"),
            "revenue": round(sum(c.revenue for c in inside), 2),
        })
    return {"buckets": buckets, "survival": survival(customers, as_of)}
