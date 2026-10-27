"""Collections Settlement Forecast — the 13-week view, per customer, accuracy.

Pure functions over ``cash_forecast.Sources``. Cash IN per week is Bruce's
EXPECTED collections (``cash_forecast_bruce``); the terms-basis open AR due
that week is shown beside it (week 0 = the COMMITTED basis). Settlements use
McLeod's Friday pay runs while the schedule covers the week; after its last
scheduled pay date Bruce's 3-week rule fills the week. AP is placed on its
pay date only (no run-rate).
"""
from __future__ import annotations

from collections import defaultdict
from datetime import date, timedelta
from typing import Optional

from app.services.cash_forecast import (
    HORIZON_WEEKS,
    FinanceWeek,
    Sources,
    _r,
    add_known,
    ap_in_week,
    ar_due_split,
    compute_this_week,
    forecast_week_offset,
    pay_date,
    settlements_in_week,
    typical_week,
    week_at,
)
from app.services.cash_forecast_bruce import (
    bruce_run_rate,
    forecast_by_customer,
    weekly_totals,
)

#: Weekly columns on the By Customer tab (this week + 4).
CUSTOMER_WEEKS = 5


def _settlement_weeks(src: Sources, weeks: int) -> Optional[list[tuple[float, str]]]:
    """Scheduled while McLeod's schedule reaches the week, then Bruce's rule.

    Coverage is the last scheduled pay date, not a fixed "week 4": a snapshot
    taken the Friday before shifts every bucket one week earlier.
    """
    if src.settlements is None:
        return None
    covered = max((pay_date(r.when) for r in src.settlements if r.when), default=None)
    out: list[tuple[float, str]] = []
    for k in range(weeks):
        if covered is not None and week_at(src.week, k).start <= covered:
            out.append((settlements_in_week(src, k) or 0.0, "scheduled"))
        else:
            out.append((bruce_run_rate([v for v, _ in out]), "run-rate"))
    return out


def _due_by_terms(src: Sources, weeks: int) -> Optional[list[float]]:
    """Open AR by terms due week (after this week's receipts); week 0 holds the
    committed basis (collected + due + all past due)."""
    split = ar_due_split(src)
    if split is None:
        return None
    offset = forecast_week_offset(src.ar_snapshot, src.week)  # type: ignore[arg-type]
    out = [0.0] * weeks
    for o in src.ar_orders or []:
        k = o.week_n - offset  # type: ignore[operator]
        if 0 < k < weeks:
            out[k] += src.remaining(o)
    out[0] = (src.collected_this_week or 0.0) + split["remaining_due"] + split["remaining_past_due"]
    return out


def compute_all(src: Sources, weeks: int = HORIZON_WEEKS) -> dict:
    """This week + the 13 weeks, from ONE Bruce run (report, AI and job agree)."""
    forecasts = forecast_by_customer(src, weeks)
    totals = weekly_totals(forecasts, weeks)
    this_week = compute_this_week(src, totals[0][0] if totals else None)
    settle = _settlement_weeks(src, weeks)
    due = _due_by_terms(src, weeks)
    rows, cumulative = [], 0.0
    known = True
    for k in range(weeks):
        wk = week_at(src.week, k)
        cash_in = totals[k][0] if totals else None
        settlements, out_basis = settle[k] if settle else (None, None)
        ap = ap_in_week(src, k)
        cash_out = add_known(settlements, ap)
        net = None if cash_in is None or cash_out is None else cash_in - cash_out
        known = known and net is not None
        cumulative += net or 0.0
        rows.append({
            "week_offset": k,
            "week_start": wk.start.isoformat(),
            "week_end": wk.end.isoformat(),
            "cash_in": _r(cash_in),
            "in_run_rate": _r(totals[k][1]) if totals else None,
            "in_due_terms": _r(due[k]) if due else None,
            "settlements": _r(settlements),
            "out_basis": out_basis,
            "ap": _r(ap),
            "cash_out": _r(cash_out),
            "net": _r(net),
            "cumulative": round(cumulative, 2) if known else None,
        })
    return {
        "this_week": this_week,
        "rows": rows,
        "forecasts": forecasts,
        "meta": {
            "this_week_committed_in": this_week["cash_in"]["committed"],
            "typical_week": typical_week(src),
            "settlements_unplaced": _r(src.settlements_future),
        },
    }


def compute_by_customer(src: Sources, forecasts) -> Optional[list[dict]]:
    """Bruce's "Per Customer" view + each customer's open / past-due AR."""
    if forecasts is None:
        return None
    offset = forecast_week_offset(src.ar_snapshot, src.week) if src.ar_snapshot else None
    open_ar: dict[str, list[float]] = defaultdict(lambda: [0.0, 0.0])
    names: dict[str, str] = {}
    for o in src.ar_orders or []:
        rem = src.remaining(o)
        open_ar[o.customer_id][0] += rem
        if offset is not None and o.week_n < offset:
            open_ar[o.customer_id][1] += rem
        names.setdefault(o.customer_id, o.customer_name)
    by_id = {f.customer_id: f for f in forecasts}
    rows = []
    for cid in set(by_id) | set(open_ar):
        f = by_id.get(cid)
        weeks = list(f.weeks[:CUSTOMER_WEEKS]) if f else [0.0] * CUSTOMER_WEEKS
        if not any(weeks) and not open_ar.get(cid, [0, 0])[0]:
            continue
        rows.append({
            "customer_id": cid,
            "customer_name": (f.customer_name if f else names.get(cid, cid)) or cid,
            "avg_pay_days": round(f.pay_days, 1) if f else None,
            "pay_days_known": f.pay_days_known if f else None,
            "open": round(open_ar[cid][0], 2) if cid in open_ar else 0.0,
            "past_due": round(open_ar[cid][1], 2) if cid in open_ar else 0.0,
            "weeks": [round(v, 2) for v in weeks],
            "run_rate_weeks": sum(f.run_rate[:CUSTOMER_WEEKS]) if f else 0,
            "expected_5w": round(sum(weeks), 2),
        })
    rows.sort(key=lambda r: (-r["expected_5w"], -r["open"], r["customer_id"]))
    return rows


def compute_accuracy(
    snapshots: list[dict], receipts_by_week: Optional[dict[date, float]], week: FinanceWeek,
    weeks_back: int = 12,
) -> list[dict]:
    """Forecast vs actual per past week (Bruce's "Totals" sheet).

    ``snapshots`` are ``cash_forecast_snapshot`` rows. The forecast for week W
    is the FIRST snapshot taken inside W for that week (offset 0) and the first
    taken the week before (offset 1). Actual collections = receipts with a GL
    date in W; actual settlements = the LAST snapshot of W's own pay run.
    """
    by_week: dict[date, dict[int, list[dict]]] = defaultdict(lambda: defaultdict(list))
    for s in snapshots:
        by_week[s["week_start"]][s["week_offset"]].append(s)
    rows = []
    for i in range(weeks_back, -1, -1):
        ws = week.start - timedelta(weeks=i)
        snaps = by_week.get(ws, {})
        first0 = min(snaps.get(0, []), key=lambda s: s["snapshot_date"], default=None)
        last0 = max(snaps.get(0, []), key=lambda s: s["snapshot_date"], default=None)
        first1 = min(snaps.get(1, []), key=lambda s: s["snapshot_date"], default=None)
        actual_in = None if receipts_by_week is None else receipts_by_week.get(ws)
        f_in = first0["in_expected"] if first0 else None
        f_settle = first0["settlements"] if first0 else None
        a_settle = last0["settlements"] if last0 and i > 0 else None
        rows.append({
            "week_start": ws.isoformat(),
            "week_end": (ws + timedelta(days=6)).isoformat(),
            "complete": i > 0,
            "forecast_in": _num(f_in),
            "forecast_in_committed": _num(first0["in_committed"] if first0 else None),
            "forecast_in_prior_week": _num(first1["in_expected"] if first1 else None),
            "actual_in": _r(actual_in),
            "variance_in": _diff(actual_in, f_in) if i > 0 else None,
            "forecast_settlements": _num(f_settle),
            "actual_settlements": _num(a_settle),
            "variance_settlements": _diff(a_settle, f_settle),
            "forecast_taken": first0["snapshot_date"].isoformat() if first0 else None,
        })
    return rows


def _num(v) -> Optional[float]:
    return None if v is None else round(float(v), 2)


def _diff(actual, forecast) -> Optional[float]:
    if actual is None or forecast is None:
        return None
    return round(float(actual) - float(forecast), 2)

