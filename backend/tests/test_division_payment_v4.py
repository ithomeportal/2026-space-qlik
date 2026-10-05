"""Division Payment Calculator — Bruno PDF 2026-10-05 (v4 inputs, overrides,
GL edit/delete, month close on the 10th, post-cutoff recalculations).

The money rules here are new and each one is a way the tab could lie quietly:

* **The month closes on the 10th, inclusive.** Capturing on the 10th freezes a
  month before its last legitimate edits; capturing on the 12th lets one more
  day of changes in. ``is_closed`` / ``due_cutoff_months`` pin the boundary,
  including the December → January rollover.
* **Per-order legs SUM to the month's Δ.** The diff rounds every order to the
  cent on BOTH sides; otherwise v4's 6-decimal NUMERIC against the stored
  NUMERIC(16,2) would list sub-cent noise as "modified" orders.
* **v4's key is (id, company_id).** The same id under two companies is two
  orders, never one.
* **A swallowed failure is a success.** The capture must raise after the loop
  when any month failed, and the scheduled wrapper must re-raise.

SQL is proven by EXECUTING the module's own statements against gold (skipped
without ``SAVINGS_DATABASE_URL``), never by asserting on a copy of the text.
"""

import inspect
import os
import re
from datetime import date, datetime
from decimal import Decimal

import pytest

from app.routers import division_payment as dp
from app.routers import division_payment_cutoffs as dpc
from app.services import division_payment_v4 as v4


# --------------------------------------------------------------------------
# Calendar — the 10th-of-next-month close
# --------------------------------------------------------------------------
def test_cutoff_is_the_tenth_of_the_following_month():
    assert v4.cutoff_date(2026, 9) == date(2026, 10, 10)
    assert v4.cutoff_date(2026, 12) == date(2027, 1, 10)  # year rollover


def test_a_month_closes_only_after_its_cutoff_day_has_passed():
    """"September is complete after the October 10 cutoff" — the 10th itself
    still belongs to the closing figures."""
    assert not v4.is_closed(2026, 9, date(2026, 10, 9))
    assert not v4.is_closed(2026, 9, date(2026, 10, 10))
    assert v4.is_closed(2026, 9, date(2026, 10, 11))


@pytest.mark.parametrize("today, captured, expected", [
    (date(2026, 10, 5), set(), []),                      # Sep still open
    (date(2026, 10, 10), set(), []),                     # cutoff day itself
    (date(2026, 10, 11), set(), [(2026, 9)]),            # first capture
    (date(2026, 10, 11), {(2026, 9)}, []),               # already done
    (date(2026, 12, 15), {(2026, 9)}, [(2026, 10), (2026, 11)]),  # catch-up
    (date(2027, 1, 11), {(2026, 9), (2026, 10), (2026, 11)}, [(2026, 12)]),
])
def test_due_months_start_at_september_2026_and_catch_up(today, captured, expected):
    assert v4.due_cutoff_months(today, captured) == expected


def test_months_before_tracking_are_never_due():
    """August 2026 closed on Sep 10 — before anything was recorded. It must not
    be captured late with post-cutoff data and passed off as its close."""
    due = v4.due_cutoff_months(date(2026, 10, 11), set())
    assert (2026, 8) not in due


@pytest.mark.parametrize("ym, today, snap, status", [
    ((2026, 8), date(2026, 10, 5), False, "before_tracking"),
    ((2026, 9), date(2026, 10, 5), False, "open"),
    ((2026, 9), date(2026, 10, 11), False, "snapshot_pending"),
    ((2026, 9), date(2026, 10, 11), True, "tracked"),
])
def test_cutoff_status(ym, today, snap, status):
    assert v4.cutoff_status(*ym, today, snap) == status


def test_month_bounds_are_naive_and_half_open():
    """Gold timestamps are naive CST — a tz-aware bound would shift the month."""
    lo, hi = v4.month_bounds(2026, 12)
    assert (lo, hi) == (datetime(2026, 12, 1), datetime(2027, 1, 1))
    assert lo.tzinfo is None and hi.tzinfo is None


def test_months_between_is_inclusive_and_crosses_years():
    assert v4.months_between((2025, 11), (2026, 2)) == [
        (2025, 11), (2025, 12), (2026, 1), (2026, 2),
    ]


# --------------------------------------------------------------------------
# The diff
# --------------------------------------------------------------------------
def _o(oid, charge, pay, margin, company="TMS ", name="ACME"):
    return {"id": oid, "company_id": company, "customer_id": name[:4],
            "customer_name": name, "total_charge": Decimal(str(charge)),
            "total_carrier_pay": Decimal(str(pay)), "margin_amt": Decimal(str(margin))}


SNAP = [_o("A", 100, 80, 20), _o("B", 200, 150, 50), _o("C", 300, 250, 50)]
LIVE = [_o("A", 100, 80, 20), _o("B", 260, 150, 110), _o("D", 50, 40, 10)]


def test_diff_classifies_modified_added_removed_and_skips_unchanged():
    out = v4.diff_orders(SNAP, LIVE)
    kinds = {c["order_id"]: c["change_type"] for c in out["changes"]}
    assert kinds == {"B": "modified", "C": "removed", "D": "added"}


def test_per_order_legs_sum_to_the_month_delta():
    out = v4.diff_orders(SNAP, LIVE)
    for col in v4.AMOUNT_COLS:
        live_total = sum(Decimal(str(r[col])) for r in LIVE)
        snap_total = sum(Decimal(str(r[col])) for r in SNAP)
        assert out["totals"][col] == live_total - snap_total, col
        assert sum(c["delta"][col] for c in out["changes"]) == out["totals"][col]


def test_sub_cent_noise_is_not_a_change():
    """v4 is NUMERIC(…,6); the snapshot is NUMERIC(16,2). 100.004 vs 100.00 is
    the same order, not a recalculation."""
    snap = [_o("A", "100.00", "80.00", "20.00")]
    live = [_o("A", "100.004", "80.001", "19.999")]
    assert v4.diff_orders(snap, live)["changes"] == []


def test_the_composite_key_keeps_two_companies_apart():
    snap = [_o("A", 100, 80, 20, company="TMS ")]
    live = [_o("A", 100, 80, 20, company="TMS3")]
    kinds = sorted(c["change_type"] for c in v4.diff_orders(snap, live)["changes"])
    assert kinds == ["added", "removed"]


# --------------------------------------------------------------------------
# Capture — isolates months, raises after the loop
# --------------------------------------------------------------------------
class _Conn:
    def __init__(self, store):
        self.store = store

    def transaction(self):
        return _Ctx()

    async def fetchval(self, sql, *args):
        key = (args[0], args[1])
        if key in self.store["cutoffs"]:
            return None
        self.store["cutoffs"][key] = args
        return args[0]

    async def executemany(self, sql, rows):
        self.store["orders"].extend(rows)


class _Ctx:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False


class _Hub:
    def __init__(self, captured=()):
        self.store = {"cutoffs": {k: None for k in captured}, "orders": []}

    async def fetch(self, sql, *args):
        return [{"year": y, "month": m} for (y, m) in self.store["cutoffs"]]

    def acquire(self):
        conn = _Conn(self.store)

        class _A:
            async def __aenter__(self_inner):
                return conn

            async def __aexit__(self_inner, *exc):
                return False
        return _A()


class _Gold:
    def __init__(self, fail_month=None, orders=2, prev_count=2):
        self.fail_month = fail_month
        self.orders = orders
        self.prev_count = prev_count

    async def fetch(self, sql, team, lo, hi):
        assert team == "TEAM-DFW"
        if sql == v4.MONTH_TOTALS_SQL:  # the previous month's count, for the floor
            return [{"year": lo.year, "month_num": lo.month, "revenue": 1, "carrier_cost": 1,
                     "profit": 1, "order_count": self.prev_count}]
        if self.fail_month and (lo.year, lo.month) == self.fail_month:
            raise RuntimeError("boom")
        rows = [_o(f"{lo.month}-1", "100.004", 80, "20.004"), _o(f"{lo.month}-2", 50, 40, 10)]
        return rows[: self.orders]


@pytest.mark.asyncio
async def test_capture_freezes_rounded_orders_and_totals():
    hub = _Hub()
    out = await v4.capture_due_cutoffs(hub, _Gold(), date(2026, 10, 11), datetime(2026, 10, 11))
    assert out["captured"] == {"September 2026": 2}
    row = hub.store["cutoffs"][(2026, "september")]
    # (year, month, label, cutoff, captured_at, revenue, cost, profit, count)
    assert row[3] == date(2026, 10, 10)
    assert row[5] == Decimal("150.00") and row[7] == Decimal("30.00") and row[8] == 2
    assert hub.store["orders"][0][6] == Decimal("100.00")


@pytest.mark.asyncio
async def test_capture_raises_after_committing_the_good_months():
    hub = _Hub(captured=[])
    with pytest.raises(RuntimeError, match="October 2026"):
        await v4.capture_due_cutoffs(
            hub, _Gold(fail_month=(2026, 10)), date(2026, 12, 15), datetime(2026, 12, 15)
        )
    # September and November still landed — one bad month must not cost the rest.
    assert set(hub.store["cutoffs"]) == {(2026, "september"), (2026, "november")}


@pytest.mark.asyncio
@pytest.mark.parametrize("orders, prev_count", [(0, 0), (0, 2), (1, 3)])
async def test_an_empty_or_partial_v4_read_is_never_frozen_as_the_close(orders, prev_count):
    """The ETL rewrites v4 in bulk; a capture taken mid-rewrite would be frozen
    as the month's PERMANENT close and list every order as "added" forever."""
    hub = _Hub()
    with pytest.raises(RuntimeError, match="refusing"):
        await v4.capture_due_cutoffs(
            hub, _Gold(orders=orders, prev_count=prev_count),
            date(2026, 10, 11), datetime(2026, 10, 11),
        )
    assert hub.store["cutoffs"] == {} and hub.store["orders"] == []


@pytest.mark.asyncio
async def test_capture_without_a_pool_is_a_failure_not_a_skip():
    with pytest.raises(RuntimeError):
        await v4.capture_due_cutoffs(None, _Gold(), date(2026, 10, 11), datetime(2026, 10, 11))


def test_the_scheduled_wrapper_reraises():
    from app import main

    src = inspect.getsource(main._scheduled_dpc_cutoff_snapshot)
    assert re.search(r"except Exception.*?\n\s+raise\b", src, re.S), "the job swallows failures"


# --------------------------------------------------------------------------
# Overrides
# --------------------------------------------------------------------------
_TOT = v4.MonthTotals(Decimal("1000"), Decimal("900"), Decimal("98"), 3)


def _m(**over):
    base = {"revenue_override": None, "carrier_cost_override": None, "profit_override": None}
    return {**base, **over}


def test_v4_is_used_when_nothing_is_overridden():
    eff = dp._effective(_m(), _TOT)
    assert eff == {"revenue": Decimal("1000"), "carrier_cost": Decimal("900"), "profit": Decimal("98")}
    assert not dp._is_overridden(_m())


def test_profit_is_margin_amt_not_revenue_minus_cost():
    """The PDF names SUM(margin_amt); v4's margin differs from charge − pay by a
    few dollars a month, so deriving it would print a number nobody asked for."""
    assert dp._effective(_m(), _TOT)["profit"] != _TOT.revenue - _TOT.carrier_cost


def test_an_override_replaces_only_its_own_field():
    eff = dp._effective(_m(carrier_cost_override=Decimal("500")), _TOT)
    assert eff["carrier_cost"] == Decimal("500")
    assert eff["revenue"] == Decimal("1000") and eff["profit"] == Decimal("98")
    assert dp._is_overridden(_m(carrier_cost_override=Decimal("500")))


def test_a_zero_override_is_still_an_override():
    """$0 is a value an operator can mean; only NULL falls back to v4."""
    assert dp._effective(_m(revenue_override=Decimal("0")), _TOT)["revenue"] == Decimal("0")


def test_override_payload_distinguishes_absent_from_null():
    """``null`` clears (reset to datalake); an absent key is left alone."""
    body = dp.MonthOverrides.model_validate({"revenue": None, "profit": 5})
    assert body.model_fields_set == {"revenue", "profit"}
    assert dp.MonthOverrides.model_validate({}).model_fields_set == set()


def test_override_bounds():
    with pytest.raises(Exception):
        dp.MonthOverrides(revenue=-1)
    dp.MonthOverrides(profit=-1000)  # a loss month is legitimate


# --------------------------------------------------------------------------
# GL edit / delete
# --------------------------------------------------------------------------
def test_gl_patch_accepts_every_editable_field_and_validates_category():
    p = dp.GLPatch(code="6100", description="  Parking ", category="Facilities")
    assert (p.category, p.description) == ("facilities", "Parking")
    with pytest.raises(Exception):
        dp.GLPatch(category="nonsense")
    with pytest.raises(Exception):
        dp.GLPatch(description="   ")


def test_delete_is_soft_and_reads_exclude_deleted_rows():
    """A hard delete of a month's last row lets the startup seeder refill it."""
    assert "UPDATE dpc_gl_accounts SET deleted_at" in inspect.getsource(dp.delete_expense)
    assert "DELETE FROM" not in inspect.getsource(dp.delete_expense)
    assert "is_custom" not in inspect.getsource(dp.delete_expense)
    for fn in (dp._gl_rows, dp.patch_expense, dp.toggle_category):
        assert "deleted_at IS NULL" in inspect.getsource(fn), fn.__name__


def test_the_seeder_counts_deleted_rows_before_refilling():
    from app.services import division_payment_defaults as d

    src = inspect.getsource(d.seed_division_payment)
    assert "SELECT COUNT(*) FROM dpc_gl_accounts WHERE month_id = $1" in src
    assert "deleted_at" not in src.split("SELECT COUNT(*)")[1].split("\n")[0]


def test_vendor_recalcs_are_no_longer_seeded():
    from app.services import division_payment_defaults as d

    assert "INSERT INTO dpc_recalcs" not in inspect.getsource(d.seed_division_payment)


# --------------------------------------------------------------------------
# Structure
# --------------------------------------------------------------------------
def test_every_cutoff_endpoint_is_access_gated():
    for route in dpc.router.routes:
        src = inspect.getsource(route.endpoint)
        assert "Depends(_access)" in src, f"{route.path} is ungated"


def test_sql_reads_v4_team_dfw_by_departure_without_tz_conversion():
    for sql in (v4.MONTH_TOTALS_SQL, v4.MONTH_ORDERS_SQL):
        assert "mcleod_gld_budget_report_v4" in sql
        assert "_v5" not in sql
        assert "br4.team_id = $1" in sql
        assert "origin_actual_departure >= $2" in sql and "origin_actual_departure <  $3" in sql
        assert "AT TIME ZONE" not in sql  # gold is already naive CST (§112)
    assert v4.DFW_TEAM_ID == "TEAM-DFW"


def test_old_free_form_inputs_endpoint_is_gone():
    paths = {(r.path, tuple(sorted(r.methods))) for r in dp.router.routes}
    assert ("/custom/division-payment/months/{year}/{month}", ("PUT",)) not in paths
    assert ("/custom/division-payment/months/{year}/{month}/overrides", ("PUT",)) in paths


# --------------------------------------------------------------------------
# Live — execute the module's OWN SQL against gold (read-only)
# --------------------------------------------------------------------------
_GOLD = os.environ.get("SAVINGS_DATABASE_URL")
live_gold = pytest.mark.skipif(not _GOLD, reason="SAVINGS_DATABASE_URL not set")


@live_gold
@pytest.mark.asyncio
async def test_live_v4_totals_equal_the_sum_of_their_orders():
    import asyncpg

    conn = await asyncpg.connect(re.sub(r"[?&]sslmode=\w+", "", _GOLD), ssl="require")
    try:
        totals = await v4.fetch_month_totals(conn, (2026, 8), (2026, 9))
        assert set(totals) == {(2026, 8), (2026, 9)}
        sep = totals[(2026, 9)]
        assert sep.order_count > 0 and sep.revenue > 0
        orders = await v4.fetch_month_orders(conn, 2026, 9)
        assert len(orders) == sep.order_count
        assert sum(Decimal(str(o["total_charge"])) for o in orders) == sep.revenue
        # A snapshot of "now" diffed against "now" is empty — the diff has no
        # false positives on real data (padded company_id, 6-decimal money).
        assert v4.diff_orders(orders, orders)["changes"] == []
    finally:
        await conn.close()
