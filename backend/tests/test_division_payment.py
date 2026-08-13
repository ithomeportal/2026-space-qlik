"""Pins the Division Payment Calculator's arithmetic and its seed data.

This report exists to produce ONE number — the payment owed to A&O — and the
vendor prototype we ported got it wrong in four separate ways. Each of those is
a test here, so a future round cannot quietly reintroduce them:

* **The tariff was subtracted twice.** The vendor's ``DEVELOPER_README.md``
  documents ``profit − glDeductions − penaltyFee − corporateGain``, but
  ``corporateGain`` already *contains* the tariff. Its own code subtracts it
  once. ``test_tariff_charged_exactly_once`` pins the code's version, which is
  what the PDF's figures reconcile to.
* **Two tabs, two answers.** The prototype computed the Calculator's net payment
  separately from the Dashboard's and they disagreed by $1,575 on May 2026
  ($290,030 vs $291,605) — the KPI-≠-detail failure of §16. There is now exactly
  one :func:`compute_summary`; ``test_single_computation_path`` asserts no
  second one has appeared.
* **A recalculation's split was 50 %, not 75 %.** The Calculator subtracted
  Corporate's 25 % *and* added A&O's 75 %. ``test_recalc_splits_25_75`` pins the
  documented rule against every seeded record.
* **The seed data did not reconcile.** ``rec-mar`` carried May's GL total,
  turning a +$29,470 month into a −$47,120 loss; audit loads summed to none of
  the five records. Both are asserted below.

The truth table is the vendor prototype's own output, derived twice
independently (once by reading ``calculateMonthSummary`` and once by replaying
the extracted data through it). It is the contract the port must not drift from.
"""

import inspect
import os
import re
from decimal import Decimal

import pytest

from app.routers import division_payment as dp
from app.services.division_payment_defaults import load_seed, seed_division_payment

# (year, month, revenue, profit, margin%, gl_deductions, tariff, corp_gain, net)
TRUTH = [
    (2026, "january",   2400000.00, 200000.00,  8.3333,  57900.00, 10000.00,  60000.00,  82100.00),
    (2026, "february",  2750000.00, 220000.00,  8.0000,  61470.00, 13750.00,  68750.00,  89780.00),
    (2026, "march",     3000000.00, 170000.00,  5.6667,  65530.00, 32500.00,  75000.00,  29470.00),
    (2026, "april",     4867010.58, 316005.77,  6.4928, 130000.00, 42673.82, 121675.26,  64330.51),
    (2026, "may",       5200000.00, 572000.00, 11.0000, 142120.00,     0.00, 143000.00, 286880.00),
    (2026, "june",      5800000.00, 638000.00, 11.0000, 153600.00,     0.00, 159500.00, 324900.00),
    (2026, "july",      6100000.00, 732000.00, 12.0000, 166390.00,     0.00, 183000.00, 382610.00),
    (2025, "january",   1800000.00, 150000.00,  8.3333,  43830.00,  7500.00,  45000.00,  61170.00),
    (2025, "february",  2100000.00, 180000.00,  8.5714,  47160.00,  7500.00,  52500.00,  80340.00),
    (2025, "march",     2300000.00, 200000.00,  8.6957,  49245.00,  7500.00,  57500.00,  93255.00),
    (2025, "april",     2600000.00, 220000.00,  8.4615,  51385.00, 10000.00,  65000.00, 103615.00),
    (2025, "may",       2900000.00, 250000.00,  8.6207,  55190.00, 10000.00,  72500.00, 122310.00),
    (2025, "june",      3200000.00, 280000.00,  8.7500,  59730.00, 10000.00,  80000.00, 140270.00),
    (2025, "july",      3500000.00, 320000.00,  9.1429,  64620.00,  7500.00,  87500.00, 167880.00),
    (2025, "august",    3700000.00, 330000.00,  8.9189,  66190.00, 10000.00,  92500.00, 171310.00),
    (2025, "september", 3900000.00, 350000.00,  8.9744,  69115.00, 10000.00,  97500.00, 183385.00),
    (2025, "october",   4200000.00, 380000.00,  9.0476,  72305.00, 10000.00, 105000.00, 202695.00),
    (2025, "november",  4500000.00, 410000.00,  9.1111,  77050.00, 10000.00, 112500.00, 220450.00),
    (2025, "december",  4800000.00, 450000.00,  9.3750,  81650.00,  7500.00, 120000.00, 248350.00),
]

SEED = load_seed()
MONTHS = {(m["year"], m["month"]): m for m in SEED["months"]}


def _gl_total(year, month):
    rows = SEED["gl_accounts"][f"{year}-{month}"]
    return sum(r["amount"] for r in rows if r["included"])


# --------------------------------------------------------------------------
# The arithmetic
# --------------------------------------------------------------------------
@pytest.mark.parametrize("row", TRUTH, ids=[f"{r[0]}-{r[1]}" for r in TRUTH])
def test_truth_table(row):
    """Every seeded month reproduces the prototype's own figures to the cent."""
    year, month, revenue, profit, margin, gl, tariff, corp, net = row
    m = MONTHS[(year, month)]
    assert m["revenue"] == pytest.approx(revenue), "seed revenue drifted"
    assert m["profit"] == pytest.approx(profit), "seed profit drifted"
    assert _gl_total(year, month) == pytest.approx(gl), "seed GL rows drifted"

    s = dp.compute_summary(m["revenue"], m["carrier_cost"], m["profit"], _gl_total(year, month))
    assert s["margin_pct"] == pytest.approx(margin, abs=1e-4)
    assert s["gl_deductions"] == pytest.approx(gl)
    assert s["penalty_fee"] == pytest.approx(tariff)
    assert s["corporate_gain"] == pytest.approx(corp)
    assert s["net_payment"] == pytest.approx(net)


@pytest.mark.parametrize("row", TRUTH, ids=[f"{r[0]}-{r[1]}" for r in TRUTH])
def test_tariff_charged_exactly_once(row):
    """net == profit − gl − corporate_gain, and the tariff lives INSIDE corp.

    Mutation check: the vendor README's ``− penaltyFee − corporateGain`` would
    fail this for every month that carries a tariff, which is 16 of the 19.
    """
    year, month = row[0], row[1]
    m = MONTHS[(year, month)]
    gl = _gl_total(year, month)
    s = dp.compute_summary(m["revenue"], m["carrier_cost"], m["profit"], gl)

    assert s["net_payment"] == pytest.approx(s["profit"] - gl - s["corporate_gain"])
    assert s["corporate_gain"] == pytest.approx(s["actual_fee"] + s["penalty_fee"])
    double_charged = s["profit"] - gl - s["penalty_fee"] - s["corporate_gain"]
    if s["penalty_fee"] > 0:
        assert s["net_payment"] != pytest.approx(double_charged), (
            "the double-subtraction bug would be invisible on this month"
        )


def test_tariff_only_below_target_and_boundary_is_inclusive():
    """Exactly 10.00 % pays no tariff; a hair under pays one."""
    on_target = dp.compute_summary(1_000_000, 900_000, 100_000, 0)
    assert on_target["meets_target"] is True
    assert on_target["penalty_fee"] == 0.0

    just_under = dp.compute_summary(1_000_000, 900_100, 99_900, 0)
    assert just_under["meets_target"] is False
    assert just_under["penalty_fee"] == pytest.approx(25.0)  # 0.025 × (rev − profit) delta

    # Above target never charges, however far above.
    assert dp.compute_summary(1_000_000, 500_000, 500_000, 0)["penalty_fee"] == 0.0


def test_tariff_equals_the_pdf_breakdown_cards():
    """PDF Dashboard Request 4 — the five cards must agree with each other.

    February 2026: 10 % of revenue $275,000 · 25 % of target profit $68,750 ·
    25 % of actual profit $55,000 · difference = tariff = $13,750.
    """
    s = dp.compute_summary(2_750_000, 2_530_000, 220_000, 61_470)
    assert s["ten_pct_of_revenue"] == pytest.approx(275_000.00)
    assert s["target_fee"] == pytest.approx(68_750.00)
    assert s["actual_fee"] == pytest.approx(55_000.00)
    assert s["difference"] == pytest.approx(13_750.00)
    assert s["penalty_fee"] == pytest.approx(s["target_fee"] - s["actual_fee"])


def test_zero_revenue_does_not_divide_by_zero():
    s = dp.compute_summary(0, 0, 0, 0)
    assert s["margin_pct"] == 0.0
    assert s["penalty_fee"] == 0.0
    assert s["net_payment"] == 0.0


def test_excluding_a_gl_row_raises_net_payment_by_exactly_that_amount():
    """The include/exclude toggle must not touch profit, margin or the tariff."""
    base = dp.compute_summary(2_750_000, 2_530_000, 220_000, 61_470)
    without = dp.compute_summary(2_750_000, 2_530_000, 220_000, 61_470 - 1_200)
    assert without["net_payment"] - base["net_payment"] == pytest.approx(1_200.00)
    for k in ("profit", "margin_pct", "penalty_fee", "corporate_gain"):
        assert without[k] == base[k]


def test_frozen_tariff_overrides_recomputation():
    """A recalculation never re-opens the tariff, even across the 10 % line."""
    revised = dp.compute_summary(5_200_000, 4_628_000, 572_000, 142_120, frozen_tariff=32_500)
    assert revised["meets_target"] is True          # 11 % margin…
    assert revised["penalty_fee"] == pytest.approx(32_500.00)  # …but the archive's tariff stands


# --------------------------------------------------------------------------
# The recalculation split
# --------------------------------------------------------------------------
def test_split_constants_sum_to_one():
    assert dp.RECALC_CORP_SHARE + dp.RECALC_AO_SHARE == Decimal("1")
    assert dp.RECALC_CORP_SHARE == dp.CORPORATE_SHARE


@pytest.mark.parametrize("rec", SEED["recalcs"], ids=[r["recalc_key"] for r in SEED["recalcs"]])
def test_recalc_splits_25_75(rec):
    """Δcorporate = 25 % of Δprofit, Δnet = 75 % of Δprofit — exactly.

    This is the identity the prototype's Calculator page broke by netting only
    50 % of the delta to A&O.
    """
    d = rec["diff"]
    assert d["profit"] != 0, "a recalc with no profit delta proves nothing"
    assert d["corporate_gain"] == pytest.approx(d["profit"] * 0.25)
    assert d["net_payment"] == pytest.approx(d["profit"] * 0.75)


@pytest.mark.parametrize("rec", SEED["recalcs"], ids=[r["recalc_key"] for r in SEED["recalcs"]])
def test_recalc_internally_reconciles(rec):
    """snapshot and tms_update each satisfy the report's own arithmetic, and the
    tariff and GL deductions are frozen between them."""
    for side in ("snapshot", "tms_update"):
        s = rec[side]
        assert s["profit"] == pytest.approx(s["revenue"] - s["carrier_cost"])
        assert s["corporate_gain"] == pytest.approx(s["profit"] * 0.25 + s["penalty_fee"])
        assert s["net_payment"] == pytest.approx(
            s["profit"] - s["gl_deductions"] - s["corporate_gain"]
        )
    assert rec["tms_update"]["penalty_fee"] == pytest.approx(rec["snapshot"]["penalty_fee"])
    assert rec["tms_update"]["gl_deductions"] == pytest.approx(rec["snapshot"]["gl_deductions"])


def test_march_2026_is_a_profit_not_a_loss():
    """The vendor's ``rec-mar`` carried May's GL total ($142,120 vs $65,530),
    rendering March as −$47,120. It is +$29,470."""
    rec = next(r for r in SEED["recalcs"] if r["recalc_key"] == "rec-mar")
    assert rec["snapshot"]["gl_deductions"] == pytest.approx(65_530.00)
    assert rec["snapshot"]["net_payment"] == pytest.approx(29_470.00)


@pytest.mark.parametrize("rec", SEED["recalcs"], ids=[r["recalc_key"] for r in SEED["recalcs"]])
def test_audit_loads_sum_to_the_recalc_delta(rec):
    """Every recalculation must be explainable by the loads behind it.

    None of the vendor's five reconciled, and ``rec-feb``'s were sign-inverted.
    """
    loads = [l for l in SEED["audit_loads"] if l["recalc_key"] == rec["recalc_key"]]
    assert loads, f"{rec['recalc_key']} has no load detail — the delta is unauditable"
    assert sum(l["revenue_delta"] for l in loads) == pytest.approx(rec["diff"]["revenue"])
    assert sum(l["cost_delta"] for l in loads) == pytest.approx(rec["diff"]["carrier_cost"])
    for l in loads:
        assert l["updated_revenue"] - l["original_revenue"] == pytest.approx(l["revenue_delta"])
        assert l["updated_carrier_cost"] - l["original_carrier_cost"] == pytest.approx(l["cost_delta"])


# --------------------------------------------------------------------------
# Seed integrity
# --------------------------------------------------------------------------
def test_seed_has_every_month_and_no_duplicates():
    assert len(SEED["months"]) == 19
    keys = [(m["year"], m["month"]) for m in SEED["months"]]
    assert len(set(keys)) == len(keys)
    assert {m["year"] for m in SEED["months"]} == {2025, 2026}
    for m in SEED["months"]:
        assert m["month"] in dp.MONTH_ORDER
        assert SEED["gl_accounts"][f"{m['year']}-{m['month']}"], "month has no GL rows"


def test_every_gl_row_uses_a_known_category():
    """An unknown category would silently vanish from the PDF's KPI strip."""
    for key, rows in SEED["gl_accounts"].items():
        for r in rows:
            assert r["category"] in dp.CATEGORY_LABELS, f"{key}: {r['category']}"


def test_archive_dates_are_valid_and_in_the_right_year():
    """The prototype generated ``2026-13-15`` … ``2026-19-15`` and stamped 2025
    months with 2026 dates."""
    from datetime import date

    for s in SEED["snapshots"]:
        y, m, d = (int(x) for x in s["snapshot_date"].split("-"))
        date(y, m, d)                      # raises on an impossible date
        assert 1 <= m <= 12
        # The archive is taken the month AFTER the data month.
        assert y == s["year"] + (1 if s["month"] == "december" else 0)


@pytest.mark.parametrize("snap", SEED["snapshots"], ids=[f"{s['year']}-{s['month']}" for s in SEED["snapshots"]])
def test_archive_matches_a_live_recomputation(snap):
    """An approved archive must equal what the calculator would produce today."""
    m = MONTHS[(snap["year"], snap["month"])]
    s = dp.compute_summary(m["revenue"], m["carrier_cost"], m["profit"],
                           _gl_total(snap["year"], snap["month"]))
    for k in ("revenue", "carrier_cost", "profit", "gl_deductions",
              "penalty_fee", "corporate_gain", "net_payment"):
        assert snap[k] == pytest.approx(s[k]), k


# --------------------------------------------------------------------------
# Structure — the guards that keep the two tabs honest
# --------------------------------------------------------------------------
def test_single_computation_path():
    """The payment formula may live in exactly one function.

    The prototype's Dashboard and Calculator each had their own copy; that is how
    the $1,575 May discrepancy happened. Reading a *stored* net payment back out
    of an approved archive is fine — re-deriving one is not. So the test is on
    the formula's own constants: only :func:`compute_summary` may reference the
    10 % target or Corporate's 25 % share. (``RECALC_*_SHARE`` is deliberately
    excluded — the recalculation split is a different rule, applied in
    ``_recalc_adjustment``.)
    """
    offenders = []
    for name, fn in inspect.getmembers(dp, inspect.isfunction):
        if fn.__module__ != dp.__name__ or name == "compute_summary":
            continue
        src = inspect.getsource(fn)
        if "TARGET_MARGIN_PCT" in src or "CORPORATE_SHARE" in src.replace("RECALC_CORP_SHARE", ""):
            offenders.append(name)
    assert not offenders, f"these re-implement the payment formula: {offenders}"


def test_every_endpoint_is_access_gated():
    """§52 — a report endpoint without ``require_report_access`` is world-readable
    to any authenticated user, and a 403 renders as an empty tab, not an error."""
    for route in dp.router.routes:
        src = inspect.getsource(route.endpoint)
        assert "_access" in src or "Depends(_access)" in src, f"{route.path} is ungated"


def test_report_key_matches_the_seed_catalog():
    """4-place mirror: the router's key must match ``CUSTOM_REPORTS``, or
    ``require_report_access`` looks up a report row that does not exist and
    every endpoint 403s into a blank screen."""
    from app.services.seed import CUSTOM_REPORTS

    keys = {r["key"] for r in CUSTOM_REPORTS}
    assert dp.REPORT_KEY in keys


def test_mutations_declare_bounded_inputs():
    """Money fields must be bounded — an unbounded NUMERIC write is how a UI
    typo becomes a nine-figure payment."""
    for model in (dp.MonthInputs, dp.GLCreate, dp.GLPatch):
        for name, field in model.model_fields.items():
            if name in {"revenue", "carrier_cost", "profit", "amount"}:
                meta = str(field.metadata)
                assert "le=" in meta or "Le(" in meta, f"{model.__name__}.{name} is unbounded"


# --------------------------------------------------------------------------
# Live replay — the SQL half
#
# The tests above prove the Python. Per this repo's convention the SQL is proven
# by replaying it against the real database inside a rolled-back transaction, so
# nothing is written and no table is left behind. Skipped without a DSN.
#
# This replay already earned its keep once: it caught the seed binding ISO
# **strings** to DATE columns (§4). asyncpg raises `'str' object has no attribute
# 'toordinal'`, and because the seed call is wrapped in a try/except at the
# lifespan, that would not have crashed startup — it would have logged one
# warning and shipped the report with no data at all.
# --------------------------------------------------------------------------
_DSN = os.environ.get("DATABASE_URL")
live = pytest.mark.skipif(not _DSN, reason="DATABASE_URL not set — live replay skipped")


class _TxPool:
    """Quacks like an asyncpg pool, but every call rides one rolled-back tx."""

    def __init__(self, conn):
        self._c = conn

    async def execute(self, *a, **k):
        return await self._c.execute(*a, **k)

    async def fetch(self, *a, **k):
        return await self._c.fetch(*a, **k)

    async def fetchrow(self, *a, **k):
        return await self._c.fetchrow(*a, **k)

    async def fetchval(self, *a, **k):
        return await self._c.fetchval(*a, **k)

    def acquire(self):
        return _Acquired(self._c)


class _Acquired:
    def __init__(self, c):
        self._c = c

    async def __aenter__(self):
        return self._c

    async def __aexit__(self, *exc):
        return False


def _lifespan_ddl() -> tuple[list[str], list[str]]:
    """Extract the dpc_* DDL from main.py so the replay cannot drift from it."""
    main = open(os.path.join(os.path.dirname(__file__), "..", "app", "main.py")).read()
    tables = re.findall(r'"""\s*(CREATE TABLE IF NOT EXISTS dpc_\w+.*?)\s*"""', main, re.S)
    # Index DDL is written as adjacent Python string literals in places; a
    # per-literal regex truncates it into a syntax error.
    indexes = [
        " ".join(re.findall(r'"([^"]*)"', blk)).strip()
        for blk in re.findall(
            r'await app\.state\.pool\.execute\(\s*((?:\s*"[^"]*"\s*)+)\)', main
        )
        if "CREATE INDEX IF NOT EXISTS idx_dpc_" in blk
    ]
    return tables, indexes


@live
@pytest.mark.asyncio
async def test_live_replay_ddl_seed_and_every_query():
    import asyncpg

    tables, indexes = _lifespan_ddl()
    assert len(tables) == 5, f"expected 5 dpc tables in main.py, found {len(tables)}"

    conn = await asyncpg.connect(re.sub(r"[?&]sslmode=\w+", "", _DSN), ssl="require")
    tx = conn.transaction()
    await tx.start()
    try:
        for stmt in tables + indexes:
            await conn.execute(stmt)

        pool = _TxPool(conn)
        await seed_division_payment(pool)

        expected_gl = sum(len(v) for v in SEED["gl_accounts"].values())
        assert await conn.fetchval("SELECT COUNT(*) FROM dpc_months") == 19
        assert await conn.fetchval("SELECT COUNT(*) FROM dpc_gl_accounts") == expected_gl

        # Seeding runs on EVERY startup — a second pass must change nothing.
        await seed_division_payment(pool)
        assert await conn.fetchval("SELECT COUNT(*) FROM dpc_gl_accounts") == expected_gl

        class _Req:
            class app:
                class state:
                    pool = None

        _Req.app.state.pool = pool
        user = {"sub": "test", "email": "test@local", "roles": ["admin"]}

        assert len((await dp.periods(_Req, user))["data"]["months"]) == 19
        assert len((await dp.archives(_Req, user))["data"]) == 19
        assert len((await dp.recalcs(_Req, user))["data"]) == 5

        # Every month must serve, and agree with the archive it was seeded from.
        for m in SEED["months"]:
            d = (await dp.summary(_Req, m["year"], m["month"], user))["data"]
            snap = next(
                s for s in SEED["snapshots"]
                if s["year"] == m["year"] and s["month"] == m["month"]
            )
            assert d["net_payment"] == pytest.approx(snap["net_payment"], abs=0.01)

        # The PDF's own figures, end to end through the SQL.
        jul = (await dp.summary(_Req, 2026, "july", user))["data"]
        assert jul["net_payment"] == 382_610.00
        assert jul["corporate_gain"] == 183_000.00
        assert jul["gl_deductions"] == 166_390.00

        # February carries rec-jan (+$6,000 profit delta). The PDF's Dashboard
        # KPI card reads $94,280.00 — i.e. 75 % of the delta to A&O, which is
        # the rule this report implements. (Its Calculator screenshot shows
        # $92,780.00, the prototype's 50 % variant. The PDF disagrees with
        # itself; the Dashboard side is the one whose spec text defines the
        # formula, so it wins.)
        feb = (await dp.summary(_Req, 2026, "february", user))["data"]
        assert feb["net_payment"] == 89_780.00
        assert feb["recalc_ao_adjustment"] == 4_500.00
        assert feb["net_payment_adjusted"] == 94_280.00

        # Excluding a GL row moves the net payment by exactly that amount and
        # touches nothing else.
        gl_id = await conn.fetchval(
            "SELECT g.id FROM dpc_gl_accounts g JOIN dpc_months m ON m.id = g.month_id "
            "WHERE m.year = 2026 AND m.month = 'july' AND g.included "
            "ORDER BY g.amount DESC LIMIT 1"
        )
        amount = float(
            await conn.fetchval("SELECT amount FROM dpc_gl_accounts WHERE id = $1", gl_id)
        )
        await dp.patch_expense(gl_id, dp.GLPatch(included=False), _Req, user)
        after = (await dp.summary(_Req, 2026, "july", user))["data"]
        assert after["net_payment"] - jul["net_payment"] == pytest.approx(amount, abs=0.01)
        assert after["profit"] == jul["profit"]
        assert after["penalty_fee"] == jul["penalty_fee"]

        # Profit is derived from the inputs, never a free third field.
        await dp.save_inputs(
            2026, "july", dp.MonthInputs(revenue=6_100_000, carrier_cost=5_368_000), _Req, user
        )
        assert (await dp.summary(_Req, 2026, "july", user))["data"]["profit"] == 732_000.00

        approved = (await dp.approve(2026, "july", _Req, user))["data"]
        assert approved["net_payment"] == pytest.approx(after["net_payment"], abs=0.01)
    finally:
        await tx.rollback()
        await conn.close()
