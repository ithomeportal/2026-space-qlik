"""Collections Settlement Forecast — the ONE definition of "this week's cash".

Request 2026-10-27 (CEO question in Teams 2026-10-26: "what are we expecting to
collect and to pay this week? are we having positive cash flow this week?").
Two finance proposals are reconciled here (docs/SPEC-COLLECTIONS-SETTLEMENT-
FORECAST.md), and BOTH nets are shown — neither replaces the other:

* COMMITTED (Daniela, AR Collections Weekly Review): collected so far + what is
  still open on invoices due this week + ALL past due. The contractual ask.
* EXPECTED (Bruce, CFO sheet): every shipped load's revenue lands on its bill
  date + the customer's McLeod average days to pay; weeks not yet shipped use
  the customer's 3-week run-rate (``cash_forecast_bruce``). What history says
  will actually arrive.

Cash OUT = this Friday's carrier settlement run + vendor AP due by Friday
(incl. past due ≤ 4 weeks; a weekend due date is paid the Friday before).

The week is Saturday → Friday in America/Chicago: the AR Collections week and
the settlement pay date, as in UNLK-Financial ``ai_weekly_cashflow``. A source
that could not be read is ``None`` — unknown, never $0: a fabricated 0 nets as
good news (SPEC-CODE-RULES §93). Pure functions only; SQL lives in
``cash_forecast_sources``.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Optional

#: Weeks shown in the forecast (this week + 12).
HORIZON_WEEKS = 13
#: AP past due younger than this still counts as payable THIS week; older is
#: shown apart (disputed / stale), never netted. Daniela: "this week and the
#: weeks before (last week, 2 to 4 weeks ago)".
CATCH_UP_DAYS = 28
#: Complete weeks averaged for the typical-week benchmark.
TYPICAL_WEEKS = 8
_SATURDAY = 5
_FRIDAY = 4


@dataclass(frozen=True)
class FinanceWeek:
    start: date  # Saturday
    end: date    # Friday — the settlement pay date


def finance_week(today: date) -> FinanceWeek:
    """The Saturday → Friday week containing ``today``."""
    start = today - timedelta(days=(today.weekday() - _SATURDAY) % 7)
    return FinanceWeek(start=start, end=start + timedelta(days=6))


def week_at(base: FinanceWeek, k: int) -> FinanceWeek:
    start = base.start + timedelta(weeks=k)
    return FinanceWeek(start=start, end=start + timedelta(days=6))


def week_index(d: date, week: FinanceWeek) -> int:
    """Weeks from ``week`` to the finance week holding ``d`` (negative = before)."""
    return (d - week.start).days // 7


def forecast_week_offset(snapshot_date: date, week: FinanceWeek) -> Optional[int]:
    """The AR forecast ``week_n`` meaning THIS week (UNLK-Financial parity).

    ``week_n`` is relative to the snapshot's own week: on a Saturday the newest
    snapshot is still Friday's, so this week is its ``week_n = 1``. A snapshot
    dated after this week cannot be mapped ⇒ ``None``.
    """
    offset = (week.start - finance_week(snapshot_date).start).days // 7
    return offset if offset >= 0 else None


def pay_date(due: Optional[date]) -> Optional[date]:
    """A payment dated Saturday/Sunday is paid the Friday before.

    Measured 2026-10-27, both sides: Daniela's AP "This Week" ($31,168.23) held
    $29,999.04 due Sat 10-31 / Sun 11-01, and McLeod dated the Nov 13 settlement
    run ($1.52M) Sat 11-14 — on a Sat→Fri week each fell into the NEXT week.
    """
    if due is None or due.weekday() < _SATURDAY:
        return due
    return due - timedelta(days=due.weekday() - _FRIDAY)


@dataclass(frozen=True)
class ArOrder:
    """An open AR invoice line (``ar_customer_forecast``)."""
    order_id: str
    customer_id: str
    customer_name: str
    balance: float
    bill_date: Optional[date]
    terms_days: Optional[int]
    terms_date: Optional[date]  # customer_payment_date = bill_date + terms
    week_n: int


@dataclass(frozen=True)
class Dated:
    """An amount on a date (settlement pay run, AP due date)."""
    when: Optional[date]
    amount: float
    count: int = 0


@dataclass(frozen=True)
class Shipped:
    """Revenue of one customer's loads sharing one base date (bill, or ship + lag)."""
    customer_id: str
    customer_name: str
    base_date: date
    revenue: float


@dataclass
class Sources:
    """Everything read for one finance week. ``None`` = that source failed."""
    week: FinanceWeek
    today: date
    ar_snapshot: Optional[date] = None
    ar_orders: Optional[list[ArOrder]] = None
    paid_this_week: Optional[dict[str, float]] = None
    receipts_by_week: Optional[dict[date, float]] = None
    latest_receipt_date: Optional[date] = None
    receipts_checked_at: Optional[str] = None
    pay_days: Optional[dict[str, float]] = None
    shipped: Optional[list[Shipped]] = None
    shipped_fresh: Optional[str] = None
    settlements: Optional[list[Dated]] = None
    settlements_future: Optional[float] = None
    settlements_snapshot: Optional[date] = None
    ap: Optional[list[Dated]] = None
    ap_snapshot: Optional[date] = None
    errors: list[str] = field(default_factory=list)

    @property
    def receipts_known(self) -> bool:
        return self.receipts_by_week is not None and self.paid_this_week is not None

    @property
    def collected_this_week(self) -> Optional[float]:
        if self.receipts_by_week is None:
            return None
        return self.receipts_by_week.get(self.week.start, 0.0)

    def remaining(self, order: ArOrder) -> float:
        """Open balance net of THIS week's receipts on the same order, floored at 0.

        Matched order by order, never by date: receipts carry back-dated GL
        dates, so no date test can tell whether the snapshot already netted
        them (UNLK-Financial ``ai_weekly_cashflow`` docstring).
        """
        paid = (self.paid_this_week or {}).get(order.order_id, 0.0)
        return max(order.balance - paid, 0.0)


def typical_week(src: Sources) -> Optional[float]:
    """Average collected over the last complete weeks that HAVE receipts.

    A week missing from the feed is an ingest gap, not a $0 week.
    """
    if src.receipts_by_week is None:
        return None
    lo = src.week.start - timedelta(weeks=TYPICAL_WEEKS)
    vals = [v for wk, v in src.receipts_by_week.items() if lo <= wk < src.week.start and v]
    return round(sum(vals) / len(vals), 2) if vals else None


def _r(v: Optional[float]) -> Optional[float]:
    return None if v is None else round(v, 2)


def add_known(*parts: Optional[float]) -> Optional[float]:
    """Sum that is unknown when ANY part is unknown — never a partial total."""
    if any(p is None for p in parts):
        return None
    return sum(parts)  # type: ignore[arg-type]


def ap_in_week(src: Sources, k: int) -> Optional[float]:
    """Vendor AP paid in week k (weekend due dates on the Friday before).

    Week 0 also carries past due up to ``CATCH_UP_DAYS``; older is apart.
    """
    if src.ap is None:
        return None
    wk = week_at(src.week, k)
    floor = src.week.start - timedelta(days=CATCH_UP_DAYS) if k == 0 else wk.start
    return sum(r.amount for r in src.ap
               if (d := pay_date(r.when)) is not None and floor <= d <= wk.end)


def settlements_in_week(src: Sources, k: int) -> Optional[float]:
    if src.settlements is None:
        return None
    wk = week_at(src.week, k)
    return sum(r.amount for r in src.settlements
               if (d := pay_date(r.when)) is not None and wk.start <= d <= wk.end)


def ar_due_split(src: Sources) -> Optional[dict]:
    """Open AR still due this week vs. past due (terms basis, after receipts)."""
    if src.ar_orders is None or src.ar_snapshot is None or not src.receipts_known:
        return None
    offset = forecast_week_offset(src.ar_snapshot, src.week)
    if offset is None:
        return None
    due = past_due = 0.0
    customers: set[str] = set()
    for o in src.ar_orders:
        rem = src.remaining(o)
        if o.week_n == offset:
            due += rem
            if rem > 0:
                customers.add(o.customer_id)
        elif o.week_n < offset:
            past_due += rem
    return {"remaining_due": due, "remaining_past_due": past_due, "due_customers": len(customers)}


def compute_this_week(src: Sources, expected_in: Optional[float]) -> dict:
    """The answer to "what do we collect and pay this week, are we positive?".

    ``expected_in`` is Bruce's week-0 forecast (``cash_forecast_bruce``).
    """
    week = src.week
    ar = ar_due_split(src)
    collected = src.collected_this_week if src.receipts_known else None
    committed_in = None if ar is None else add_known(
        collected, ar["remaining_due"], ar["remaining_past_due"])
    settlements = settlements_in_week(src, 0)
    ap_due = ap_in_week(src, 0)
    out_total = add_known(settlements, ap_due)
    older = undated = None
    if src.ap is not None:
        cutoff = week.start - timedelta(days=CATCH_UP_DAYS)
        older = sum(r.amount for r in src.ap if r.when and pay_date(r.when) < cutoff)
        undated = sum(r.amount for r in src.ap if r.when is None)
    pay_dates = sorted({d for r in (src.settlements or [])
                        if (d := pay_date(r.when)) is not None and week.start <= d <= week.end})

    def _net(cash_in: Optional[float]) -> Optional[float]:
        return None if cash_in is None or out_total is None else round(cash_in - out_total, 2)

    still_expected = None
    if expected_in is not None and collected is not None:
        still_expected = max(expected_in - collected, 0.0)
    return {
        "week_start": week.start.isoformat(),
        "week_end": week.end.isoformat(),
        "company": "TMS",
        "cash_in": {
            "collected_so_far": _r(collected),
            "receipts_included": src.receipts_known,
            "remaining_due": _r(ar and ar["remaining_due"]),
            "due_customers": ar["due_customers"] if ar else None,
            "remaining_past_due": _r(ar and ar["remaining_past_due"]),
            "committed": _r(committed_in),
            "expected": _r(expected_in),
            "still_expected": _r(still_expected),
            "typical_week": typical_week(src),
        },
        "cash_out": {
            "settlements": _r(settlements),
            "settlement_pay_dates": [d.isoformat() for d in pay_dates],
            "ap_due": _r(ap_due),
            "ap_past_due_older": _r(older),
            "ap_undated": _r(undated),
            "total": _r(out_total),
        },
        "net": {"committed": _net(committed_in), "expected": _net(expected_in)},
    }
