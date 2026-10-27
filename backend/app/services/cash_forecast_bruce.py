"""Collections Settlement Forecast — Bruce's EXPECTED collections, per customer.

Port of the CFO workbook "2026-10 Collection Settlement Forecast.xlsx",
sheet "Collections Forecast" (row per customer, column per week):

    =IF(week_end - TODAY() < days_to_pay,
        SUMIFS(revenue, customer, c, ship_week, week_start - ROUND(days/7)*7),
        IF(two of the previous three weeks > 0, AVERAGE(previous three), 0))

i.e. a load's revenue is collected ``days_to_pay`` after it ships; a week whose
payers have not all shipped yet (it ends ``days_to_pay`` or more from today)
takes the customer's 3-week run-rate instead.

Two deliberate refinements (spec §Bruce):

* the shift is in DAYS from the BILL date (McLeod measures average pay days
  from the invoice), not whole weeks from the ship week; an unbilled load uses
  ship date + ``BILL_LAG_DAYS``;
* weeks are the Saturday → Friday finance week, not Excel's Sunday WEEKNUM.

Days to pay = McLeod ``customer_info.average_pay_days`` (UNLK-Financial
``ar_customer_directory``); ``DEFAULT_PAY_DAYS`` when McLeod has none (Bruce:
``IFERROR(VLOOKUP(...), 30)``, and 0 → 30).
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import timedelta
from typing import Optional

from app.services.cash_forecast import HORIZON_WEEKS, Sources, week_at, week_index

DEFAULT_PAY_DAYS = 30.0
#: Ship → invoice lag for a load not billed yet (median measured 2026-10-27: 3 days).
BILL_LAG_DAYS = 3
#: Weeks before this one computed so the run-rate of week 0 has three priors.
LOOKBACK_WEEKS = 3
#: Oldest base date read: a customer slower than this is an outlier whose
#: revenue the run-rate still carries.
MAX_PAY_DAYS = 180


def bruce_run_rate(previous: list[float]) -> float:
    """``IF(OR(AND(a>0,b>0),AND(a>0,c>0),AND(b>0,c>0)),AVERAGE(a:c),0)``."""
    last3 = previous[-3:]
    if len(last3) < 3 or sum(1 for v in last3 if v > 0) < 2:
        return 0.0
    return sum(last3) / 3


def pay_days_of(src: Sources, customer_id: str) -> tuple[float, bool]:
    """(days to pay, from McLeod?) — the default when McLeod has none or 0."""
    days = (src.pay_days or {}).get(customer_id)
    if days is None or days <= 0:
        return DEFAULT_PAY_DAYS, False
    return float(days), True


@dataclass(frozen=True)
class CustomerForecast:
    customer_id: str
    customer_name: str
    pay_days: float
    pay_days_known: bool
    weeks: tuple[float, ...]       # k = 0 .. HORIZON_WEEKS-1
    run_rate: tuple[bool, ...]     # True where the week took the run-rate


def forecast_by_customer(src: Sources, horizon: int = HORIZON_WEEKS) -> Optional[list[CustomerForecast]]:
    """Expected collections per customer and week; ``None`` if a source is unknown."""
    if src.shipped is None or src.pay_days is None:
        return None
    shipped: dict[str, dict[int, float]] = defaultdict(lambda: defaultdict(float))
    names: dict[str, str] = {}
    for s in src.shipped:
        days, _ = pay_days_of(src, s.customer_id)
        k = week_index(s.base_date + timedelta(days=round(days)), src.week)
        if -LOOKBACK_WEEKS <= k < horizon:
            shipped[s.customer_id][k] += s.revenue
        names.setdefault(s.customer_id, s.customer_name)
    out = []
    for cid, by_week in shipped.items():
        days, known = pay_days_of(src, cid)
        series: list[float] = []
        flags: list[bool] = []
        for k in range(-LOOKBACK_WEEKS, horizon):
            if (week_at(src.week, k).end - src.today).days < days:
                series.append(by_week.get(k, 0.0))
                flags.append(False)
            else:
                series.append(bruce_run_rate(series))
                flags.append(True)
        out.append(CustomerForecast(
            cid, names.get(cid, cid), days, known,
            tuple(series[LOOKBACK_WEEKS:]), tuple(flags[LOOKBACK_WEEKS:]),
        ))
    return out


def weekly_totals(forecasts: Optional[list[CustomerForecast]], horizon: int = HORIZON_WEEKS
                  ) -> Optional[list[tuple[float, float]]]:
    """Per week: (expected total, of which run-rate)."""
    if forecasts is None:
        return None
    totals = [[0.0, 0.0] for _ in range(horizon)]
    for f in forecasts:
        for k, (v, rr) in enumerate(zip(f.weeks, f.run_rate)):
            totals[k][0] += v
            if rr:
                totals[k][1] += v
    return [(t, rr) for t, rr in totals]
