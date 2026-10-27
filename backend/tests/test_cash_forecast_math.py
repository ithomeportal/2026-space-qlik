"""Collections Settlement Forecast — the definitions (request 2026-10-27).

The defect this report exists to prevent is the 2026-10-26 Teams answer:
cash IN = $142K of NOT-YET-INVOICED orders read as "collected", cash OUT = all
five settlement weeks, net −$1.42M. These tests pin the replacement:

* Daniela's own table is reproduced to the cent (COMMITTED basis);
* Bruce's sheet formula is ported cell for cell (EXPECTED basis);
* a source that failed reads as ``None`` — never a $0 that nets as good news;
* weekend-dated payments land on the Friday before (measured on live data).
"""
from __future__ import annotations

from datetime import date, timedelta

import pytest

from app.services import cash_forecast as cf
from app.services import cash_forecast_bruce as cb
from app.services import cash_forecast_weeks as cw

MON = date(2026, 10, 26)          # the CEO's question day
WEEK = cf.finance_week(MON)       # Sat 10-24 → Fri 10-30
SNAP = date(2026, 10, 26)


def _order(oid, bal, week_n, cust="C1"):
    bill = WEEK.start - timedelta(days=30)
    return cf.ArOrder(oid, cust, f"{cust} name", bal, bill, 30, bill + timedelta(days=30), week_n)


def _src(**kw) -> cf.Sources:
    base = dict(week=WEEK, today=MON, ar_snapshot=SNAP, ar_orders=[], paid_this_week={},
                receipts_by_week={}, pay_days={}, shipped=[], settlements=[], ap=[])
    base.update(kw)
    return cf.Sources(**base)


# ------------------------------------------------------------------ calendar

def test_finance_week_is_saturday_to_friday():
    assert WEEK.start == date(2026, 10, 24) and WEEK.start.weekday() == 5
    assert WEEK.end == date(2026, 10, 30) and WEEK.end.weekday() == 4
    assert cf.finance_week(date(2026, 10, 24)) == WEEK
    assert cf.finance_week(date(2026, 10, 30)) == WEEK
    assert cf.finance_week(date(2026, 10, 31)).start == date(2026, 10, 31)


def test_saturday_reads_fridays_snapshot_as_next_week():
    """UNLK-Financial parity: on Saturday the newest AR snapshot is Friday's."""
    sat = cf.finance_week(date(2026, 10, 31))
    assert cf.forecast_week_offset(date(2026, 10, 30), sat) == 1
    assert cf.forecast_week_offset(SNAP, WEEK) == 0
    assert cf.forecast_week_offset(date(2026, 11, 2), WEEK) is None


def test_weekend_payment_is_paid_the_friday_before():
    assert cf.pay_date(date(2026, 10, 31)) == date(2026, 10, 30)   # Sat
    assert cf.pay_date(date(2026, 11, 1)) == date(2026, 10, 30)    # Sun
    assert cf.pay_date(date(2026, 11, 2)) == date(2026, 11, 2)     # Mon
    assert cf.pay_date(None) is None


def test_add_known_is_unknown_when_any_part_is():
    assert cf.add_known(1.0, 2.0) == 3.0
    assert cf.add_known(1.0, None) is None


# ------------------------------------------------------------------ this week

def _daniela_sources() -> cf.Sources:
    """Daniela's 2026-10-27 table: Projected $1,808,180 (past due $834,841),
    collected $402,435; carriers $1,228,924.36; AP $31,168.23 — the AP as it
    sits in McLeod (Fri 10-23 past due + Sat 10-31 + Sun 11-01)."""
    paid = 402_435.0
    return _src(
        ar_orders=[_order("A", 973_339.0, 0), _order("B", 834_841.0, -2)],
        paid_this_week={"A": paid},
        receipts_by_week={WEEK.start: paid},
        settlements=[cf.Dated(WEEK.end, 1_228_924.36, 264)],
        ap=[cf.Dated(date(2026, 10, 23), 1_169.19, 1),
            cf.Dated(date(2026, 10, 31), 1_867.01, 1),
            cf.Dated(date(2026, 11, 1), 28_132.03, 5)],
    )


def test_committed_basis_reproduces_danielas_table_to_the_cent():
    out = cf.compute_this_week(_daniela_sources(), None)
    cash_in = out["cash_in"]
    assert cash_in["collected_so_far"] == 402_435.0
    assert cash_in["remaining_due"] == 570_904.0
    assert cash_in["remaining_past_due"] == 834_841.0
    assert cash_in["committed"] == 1_808_180.0
    assert out["cash_out"]["settlements"] == 1_228_924.36
    assert out["cash_out"]["ap_due"] == 31_168.23
    assert out["cash_out"]["total"] == 1_260_092.59
    assert out["net"]["committed"] == 548_087.41


def test_expected_net_uses_bruces_week_and_progress_is_shown():
    out = cf.compute_this_week(_daniela_sources(), 1_700_000.0)
    assert out["cash_in"]["expected"] == 1_700_000.0
    assert out["cash_in"]["still_expected"] == 1_700_000.0 - 402_435.0
    assert out["net"]["expected"] == round(1_700_000.0 - 1_260_092.59, 2)


def test_receipt_is_matched_by_order_never_double_counted():
    src = _src(ar_orders=[_order("A", 100.0, 0), _order("B", 50.0, 0)],
               paid_this_week={"A": 130.0}, receipts_by_week={WEEK.start: 130.0})
    cash_in = cf.compute_this_week(src, None)["cash_in"]
    assert cash_in["remaining_due"] == 50.0
    assert cash_in["committed"] == 180.0


def test_only_this_fridays_settlement_run_counts():
    src = _src(settlements=[cf.Dated(WEEK.end, 1_227_724.36),
                            cf.Dated(WEEK.end + timedelta(days=7), 1_344_642.90)])
    out = cf.compute_this_week(src, None)["cash_out"]
    assert out["settlements"] == 1_227_724.36
    assert out["settlement_pay_dates"] == [WEEK.end.isoformat()]


def test_ap_older_than_four_weeks_and_undated_are_shown_not_netted():
    src = _src(ap=[cf.Dated(WEEK.start - timedelta(days=40), 9_000.0),
                   cf.Dated(None, 77.0), cf.Dated(WEEK.end, 10.0)],
               settlements=[cf.Dated(WEEK.end, 100.0)])
    out = cf.compute_this_week(src, None)["cash_out"]
    assert (out["ap_due"], out["ap_past_due_older"], out["ap_undated"]) == (10.0, 9_000.0, 77.0)
    assert out["total"] == 110.0


@pytest.mark.parametrize("dead", ["ar_orders", "settlements", "ap", "receipts_by_week", "paid_this_week"])
def test_a_dead_source_gives_unknown_never_zero(dead):
    """Reviewer 2026-10-27: unknown AP / receipts were netted as $0."""
    src = _daniela_sources()
    setattr(src, dead, None)
    out = cf.compute_this_week(src, 1_700_000.0)
    if dead in ("settlements", "ap"):
        assert out["cash_out"]["total"] is None
        assert out["net"] == {"committed": None, "expected": None}
    else:
        assert out["cash_in"]["committed"] is None and out["net"]["committed"] is None


def test_typical_week_skips_gap_weeks_and_this_week():
    rec = {WEEK.start - timedelta(weeks=1): 1_000.0, WEEK.start - timedelta(weeks=2): 0.0,
           WEEK.start - timedelta(weeks=3): 2_000.0, WEEK.start: 99.0,
           WEEK.start - timedelta(weeks=9): 50_000.0}
    assert cf.typical_week(_src(receipts_by_week=rec)) == 1_500.0


# ------------------------------------------------------------------ Bruce

def test_bruce_run_rate_needs_two_of_three_non_zero():
    assert cb.bruce_run_rate([0, 0, 0, 30, 0, 60]) == 30.0
    assert cb.bruce_run_rate([10, 0, 0]) == 0.0
    assert cb.bruce_run_rate([5, 5]) == 0.0


def test_bruce_shifts_revenue_by_average_pay_days_from_the_bill_date():
    ship = [cf.Shipped("C1", "Cust", WEEK.start - timedelta(days=40), 1_000.0),
            cf.Shipped("C1", "Cust", WEEK.start - timedelta(days=33), 500.0)]
    src = _src(shipped=ship, pay_days={"C1": 42.4})
    f = cb.forecast_by_customer(src)[0]
    assert f.pay_days == 42.4 and f.pay_days_known
    assert f.weeks[0] == 1_000.0      # -40 + 42 = this week
    assert f.weeks[1] == 500.0        # -33 + 42 = next week
    assert f.run_rate[0] is False


def test_bruce_default_30_days_when_mcleod_has_none_or_zero():
    src = _src(shipped=[cf.Shipped("C9", "X", WEEK.start - timedelta(days=28), 70.0)],
               pay_days={"C9": 0})
    f = cb.forecast_by_customer(src)[0]
    assert (f.pay_days, f.pay_days_known, f.weeks[0]) == (30.0, False, 70.0)


def test_bruce_unshipped_weeks_take_the_customers_run_rate():
    """Weeks ending ≥ days-to-pay from today have not fully shipped:
    Bruce's IF(week_end − TODAY() < days, actual, AVERAGE(prev 3))."""
    ship = [cf.Shipped("C1", "Cust", WEEK.start + timedelta(weeks=k) - timedelta(days=14), 100.0)
            for k in range(-3, 3)]
    f = cb.forecast_by_customer(_src(shipped=ship, pay_days={"C1": 14}))[0]
    assert f.weeks[:2] == (100.0, 100.0)
    assert f.run_rate[2] is True and f.weeks[2] == 100.0   # average of 3 × 100
    assert all(f.run_rate[2:])


def test_bruce_unknown_when_shipped_or_pay_days_unread():
    assert cb.forecast_by_customer(_src(shipped=None)) is None
    assert cb.forecast_by_customer(_src(pay_days=None)) is None


# ------------------------------------------------------------------ 13 weeks

def test_week_zero_equals_this_week_and_settlements_fill_after_coverage():
    sched = [cf.Dated(WEEK.end + timedelta(weeks=k), 600.0) for k in range(5)]
    src = _daniela_sources()
    src.settlements = sched
    src.shipped = [cf.Shipped("C1", "Cust", WEEK.start - timedelta(days=30), 2_000.0)]
    res = cw.compute_all(src)
    rows, this = res["rows"], res["this_week"]
    assert len(rows) == cf.HORIZON_WEEKS
    assert rows[0]["cash_in"] == this["cash_in"]["expected"] == 2_000.0
    assert rows[0]["cash_out"] == this["cash_out"]["total"]
    assert rows[0]["in_due_terms"] == this["cash_in"]["committed"]
    assert rows[4]["out_basis"] == "scheduled" and rows[5]["out_basis"] == "run-rate"
    assert rows[5]["settlements"] == 600.0


def test_coverage_follows_the_snapshot_not_a_fixed_week_4():
    """A Friday snapshot shifts every bucket one week earlier (reviewer #4)."""
    sched = [cf.Dated(WEEK.end + timedelta(weeks=k), 600.0) for k in range(4)]
    rows = cw.compute_all(_src(settlements=sched))["rows"]
    assert rows[3]["out_basis"] == "scheduled" and rows[4]["out_basis"] == "run-rate"
    assert rows[4]["settlements"] == 600.0


def test_saturday_dated_settlement_run_stays_in_its_friday_week():
    """McLeod dated the Nov 13 run Sat 11-14 (measured 2026-10-27)."""
    src = _src(settlements=[cf.Dated(WEEK.end + timedelta(days=8), 1_519_184.40)])
    rows = cw.compute_all(src)["rows"]
    assert rows[1]["settlements"] == 1_519_184.40 and rows[2]["settlements"] == 0.0


@pytest.mark.parametrize("dead", ["settlements", "ap", "shipped"])
def test_weeks_unknown_source_blanks_net_and_cumulative(dead):
    src = _daniela_sources()
    setattr(src, dead, None)
    rows = cw.compute_all(src)["rows"]
    assert all(r["net"] is None and r["cumulative"] is None for r in rows)


# ------------------------------------------------------------------ customers / accuracy

def test_by_customer_joins_bruce_weeks_with_open_ar():
    src = _src(ar_orders=[_order("A", 100.0, 0, "C1"), _order("B", 50.0, -1, "C1"),
                          _order("C", 70.0, 1, "C2")],
               shipped=[cf.Shipped("C1", "Cust 1", WEEK.start - timedelta(days=30), 400.0)],
               pay_days={"C1": 30})
    res = cw.compute_all(src)
    rows = {r["customer_id"]: r for r in cw.compute_by_customer(src, res["forecasts"])}
    assert rows["C1"]["open"] == 150.0 and rows["C1"]["past_due"] == 50.0
    assert rows["C1"]["weeks"][0] == 400.0 and rows["C1"]["expected_5w"] == 400.0
    assert rows["C2"]["open"] == 70.0 and rows["C2"]["avg_pay_days"] is None


def test_accuracy_uses_first_snapshot_and_last_pay_run():
    w1 = WEEK.start - timedelta(weeks=1)
    snaps = [
        {"snapshot_date": w1, "week_start": w1, "week_offset": 0, "in_expected": 900,
         "in_committed": 1_200, "settlements": 800},
        {"snapshot_date": w1 + timedelta(days=3), "week_start": w1, "week_offset": 0,
         "in_expected": 999, "in_committed": 1, "settlements": 850},
        {"snapshot_date": w1 - timedelta(days=2), "week_start": w1, "week_offset": 1,
         "in_expected": 700, "in_committed": None, "settlements": 700},
    ]
    rows = cw.compute_accuracy(snaps, {w1: 1_000.0, WEEK.start: 5.0}, WEEK)
    row = next(r for r in rows if r["week_start"] == w1.isoformat())
    assert row["forecast_in"] == 900 and row["forecast_in_prior_week"] == 700
    assert row["actual_in"] == 1_000.0 and row["variance_in"] == 100.0
    assert row["actual_settlements"] == 850 and row["variance_settlements"] == 50.0
    assert rows[-1]["complete"] is False and rows[-1]["variance_in"] is None
    assert len(rows) == 13
