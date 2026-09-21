"""KAM Performance - DFW — Tab 8 "Loads Under 5%" (Bruno PDF 2026-09-21).

The request reads like a clone of Worst 10 Lanes ("same information and
structure ... but with the following filter"), and the one thing these tests
exist to stop is someone finishing that sentence literally.

`/worst-lanes` measures Loads / Revenue / Profit over the **negative-margin
slice** of each lane so its numbers tie out to the daily Losses email. A margin
PERCENTAGE over that slice is negative by construction for every row, so the
5% threshold would select all of them and mean nothing. `/under-5-lanes`
therefore aggregates **every** load on the lane and applies the threshold to
that ratio — which is why the same lane prints different numbers in the two
tabs, and why `margin_amt < 0` must be absent here and present there.

Three layers, cheapest first, following `test_xray_dfw_gm_tab.py`:

1. the emitted-SQL linters over a stub pool,
2. the month/threshold/scope unit contracts,
3. `test_live_*` — PREPARE and run against real gold, skipped unless
   ``SAVINGS_DATABASE_URL`` is set, so the suite stays offline.
"""

from __future__ import annotations

import asyncio
import os
import re
import types
from datetime import date

import pytest
from fastapi import HTTPException

from app.routers import kam_performance_dfw as k


class _StubPool:
    """⚠ Records the SQL. A stub pool cannot see a WHERE — these tests assert
    on the statement text, which is why the live layer below exists too."""

    def __init__(self, rows=None):
        self.sqls: list[str] = []
        self.params: list[tuple] = []
        self._rows = rows or []

    async def fetch(self, sql, *params):
        self.sqls.append(sql)
        self.params.append(params)
        return self._rows


def _drive(**overrides):
    """Drive `/under-5-lanes` against stub pools. Returns (gold, hub, payload)."""
    gold, hub = _StubPool(), _StubPool()
    orig_gold, orig_hub = k.get_datalake_gold_pool, k.get_pool
    k.get_datalake_gold_pool = lambda request: gold
    k.get_pool = lambda request: hub
    try:
        request = types.SimpleNamespace(
            app=types.SimpleNamespace(state=types.SimpleNamespace())
        )
        call = dict(month=None, sub_teams=None, limit=k.UNDER_5_MAX_ROWS,
                    user={"sub": "user-1"})
        call.update(overrides)
        resp = asyncio.run(k.under_5_lanes(request=request, **call))
    finally:
        k.get_datalake_gold_pool, k.get_pool = orig_gold, orig_hub
    return gold, hub, resp


def _worst_lanes_sql() -> str:
    """The sibling endpoint's statement, for the did-NOT-move assertions."""
    gold, hub = _StubPool(), _StubPool()
    orig_gold, orig_hub = k.get_datalake_gold_pool, k.get_pool
    k.get_datalake_gold_pool = lambda request: gold
    k.get_pool = lambda request: hub
    try:
        request = types.SimpleNamespace(
            app=types.SimpleNamespace(state=types.SimpleNamespace())
        )
        asyncio.run(
            k.worst_lanes(
                request=request, range="ytd", start_date=None, end_date=None,
                limit=10, sub_teams=None, user={"sub": "user-1"},
            )
        )
    finally:
        k.get_datalake_gold_pool, k.get_pool = orig_gold, orig_hub
    return _strip_comments(gold.sqls[0])


def _strip_comments(sql: str) -> str:
    """Drop `-- ...` lines. Scan the executable text, never the prose that
    quotes the very predicates these tests assert about."""
    return "\n".join(
        line for line in sql.split("\n") if not line.strip().startswith("--")
    )


def _sql(gold) -> str:
    return _strip_comments(gold.sqls[0])


# ---------------------------------------------------------------------------
# The population — what makes this NOT a clone
# ---------------------------------------------------------------------------


def test_the_negative_margin_row_filter_is_absent():
    """🔴 The defect this whole tab could have shipped with.

    Inheriting `margin_amt < 0` would compute Margin% over the losing loads
    only: every lane would score negative, all of them would pass "< 5%", and
    the Revenue / Profit / Loads columns would describe a slice of the lane
    rather than the lane. The tab would look plausible and be wrong.
    """
    assert "margin_amt < 0" not in _sql(_drive()[0])


def test_worst_lanes_still_has_it():
    """The other half of the same statement: the sibling endpoint must keep
    measuring the neg-margin slice, or IT stops tying out to the Losses email.
    One of these two tests failing alone means the population moved."""
    assert "b.margin_amt < 0" in _worst_lanes_sql()


def test_the_threshold_is_a_HAVING_over_the_group():
    """A lane is under 5% when its OWN revenue earns less than 5% — not when
    it happens to carry one thin load. As a per-row predicate the same input
    would return a different, larger set."""
    sql = _sql(_drive()[0])
    having = re.search(r"HAVING (.+?)\n\s*ORDER BY", sql, re.S)
    assert having, "the threshold is not in a HAVING clause"
    assert f"* 100 < {k.UNDER_MARGIN_PCT}" in having.group(1)
    assert "WHERE" not in having.group(1)


def test_the_denominator_is_guarded_positive():
    """A lane whose revenue nets to zero has no margin percentage, and one that
    nets NEGATIVE (credits exceeding charges) flips the sign — a loss would
    read as a healthy margin and be dropped from a report about losses.
    Measured 2026-09-21: 0 such groups in DFW 2026, so this guard is a no-op
    today and the sentry for the day it is not."""
    assert "HAVING SUM(total_charge) > 0" in _sql(_drive()[0])


def test_the_zero_charge_filter_is_kept():
    """⚠ Dropping it is a POPULATION change, not a cleanup (§111): an unbilled
    load carries cost and no revenue, so it would push lanes under 5% for a
    BILLING reason rather than a margin one. COALESCE-wrapped because a bare
    `<> 0` is NULL for a NULL charge and Postgres drops the row."""
    assert "COALESCE(b.total_charge, 0) <> 0" in _sql(_drive()[0])


def test_ordered_worst_margin_first():
    assert "ORDER BY margin_pct ASC, profit ASC" in _sql(_drive()[0])


# ---------------------------------------------------------------------------
# The month window
# ---------------------------------------------------------------------------


def test_default_month_is_the_current_CST_month():
    """⚠ Render and Aiven both run UTC. A naive `date.today()` would serve the
    PREVIOUS month for the first 5-6 hours of every CST 1st-of-the-month."""
    _, _, resp = _drive()
    today = k.cst_today()
    assert resp["meta"]["month"] == today.strftime("%Y-%m")
    assert resp["meta"]["window"]["start"] == today.replace(day=1).isoformat()


@pytest.mark.parametrize(
    "month,start,end",
    [
        ("2026-01", "2026-01-01", "2026-01-31"),
        ("2026-02", "2026-02-01", "2026-02-28"),  # 2026 is not a leap year
        ("2026-06", "2026-06-01", "2026-06-30"),
        ("2026-12", "2026-12-01", "2026-12-31"),
    ],
)
def test_a_month_resolves_to_its_whole_window(month, start, end):
    """The whole month, never truncated at today (the request says "for the
    selected month"). For the current month that is identical in practice —
    `origin_actual_departure` is an ACTUAL departure, so it cannot be future."""
    s, e = k._resolve_month(month)
    assert (s.isoformat(), e.isoformat()) == (start, end)


@pytest.mark.parametrize("month", ["2025-12", "2020-01"])
def test_a_month_before_the_scope_year_clamps_forward(month):
    assert k._resolve_month(month)[0] == k.YEAR_START.replace(day=1)


@pytest.mark.parametrize("month", ["2027-01", "2099-06"])
def test_a_month_after_the_scope_year_clamps_back(month):
    s, e = k._resolve_month(month)
    assert s == k.YEAR_END.replace(day=1)
    assert e <= k.YEAR_END


@pytest.mark.parametrize("month", ["2026", "2026-13", "2026-00", "sept", "2026-1", "0000-01"])
def test_a_malformed_month_is_a_422(month):
    """Validated at the boundary rather than silently coerced — a typo'd month
    that quietly returns the current one reads as a data problem."""
    with pytest.raises(HTTPException) as exc:
        k._resolve_month(month)
    assert exc.value.status_code == 422


def test_an_empty_month_falls_back_to_the_default():
    """`?month=` from a form is absence, not a malformed value."""
    assert k._resolve_month("")[0] == k.cst_today().replace(day=1)


# ---------------------------------------------------------------------------
# Scope — what a hand-crafted URL cannot widen
# ---------------------------------------------------------------------------


def test_the_dfw_scope_is_the_shared_one():
    sql = _sql(_drive()[0])
    for frag in (
        "b.team_id    = ANY($1)",
        "b.company_id = ANY($2)",
        "b.status     = ANY($3)",
        "NOT LIKE '%UNILINK%'",
        "NOT LIKE '%OILTEX%'",
    ):
        assert frag in sql


def test_the_team_filter_only_honours_TM1_to_TM4():
    """⚠ `?sub_teams=TEAM1` must not reach the statement. The allow-list is the
    scope lock — DFW's own rows also carry TM5 and blanks, and an unknown value
    dropping through as a predicate would silently empty the table."""
    gold, _, _ = _drive(sub_teams="TM2,TEAM1,tm3,../*")
    assert "TRIM(b.team) = ANY($4)" in _sql(gold)
    assert gold.params[0][3] == ["TM2", "TM3"]


def test_no_team_filter_means_no_predicate():
    gold, _, _ = _drive()
    assert "TRIM(b.team)" not in _sql(gold)


def test_the_notes_are_the_worst_lanes_rows():
    """One action plan per lane, whichever tab surfaced it — the same
    `(user_id, lane_key)` rows Worst 10 Lanes reads and `PUT /worst-lane-notes`
    writes. A second table here would give one lane two plans."""
    _, hub, _ = _drive()
    assert "FROM kam_worst_lane_notes WHERE user_id = $1" in hub.sqls[0]
    assert hub.params[0] == ("user-1",)


def test_the_note_read_is_scoped_to_the_caller():
    """Per-user rows: a leaked lane_key must not read another KAM's plan."""
    _, hub, _ = _drive(user={"sub": "someone-else"})
    assert hub.params[0] == ("someone-else",)


# ---------------------------------------------------------------------------
# The envelope
# ---------------------------------------------------------------------------


def test_truncation_is_published_not_silent():
    """⚠ §105. The cap is a runaway guard, not a business limit (the busiest
    month of 2026 produced 241 lanes), but a list that quietly stops at N is
    how "50 of 64 reports" shipped for months."""
    rows = [
        {"customer": f"C{i}", "lane": f"L{i}", "loads": 1,
         "revenue": 100, "profit": 1, "margin_pct": 1.0}
        for i in range(3)
    ]
    gold, hub = _StubPool(rows), _StubPool()
    orig_gold, orig_hub = k.get_datalake_gold_pool, k.get_pool
    k.get_datalake_gold_pool = lambda request: gold
    k.get_pool = lambda request: hub
    try:
        request = types.SimpleNamespace(
            app=types.SimpleNamespace(state=types.SimpleNamespace())
        )
        full = asyncio.run(k.under_5_lanes(
            request=request, month=None, sub_teams=None, limit=3,
            user={"sub": "u"}))
        room = asyncio.run(k.under_5_lanes(
            request=request, month=None, sub_teams=None, limit=50,
            user={"sub": "u"}))
    finally:
        k.get_datalake_gold_pool, k.get_pool = orig_gold, orig_hub
    assert full["meta"]["truncated"] is True
    assert room["meta"]["truncated"] is False
    assert room["meta"]["total"] == 3


def test_rows_carry_the_lane_key_and_the_note_columns():
    rows = [{"customer": "ACME", "lane": "A, TX - B, TX", "loads": 4,
             "revenue": 1000, "profit": 10, "margin_pct": 1.0}]
    gold, hub = _StubPool(rows), _StubPool()
    hub._rows = [{"lane_key": "ACME::A, TX - B, TX",
                  "expiration_date": date(2026, 10, 1),
                  "action_plan": "renegotiate"}]
    orig_gold, orig_hub = k.get_datalake_gold_pool, k.get_pool
    k.get_datalake_gold_pool = lambda request: gold
    k.get_pool = lambda request: hub
    try:
        request = types.SimpleNamespace(
            app=types.SimpleNamespace(state=types.SimpleNamespace())
        )
        resp = asyncio.run(k.under_5_lanes(
            request=request, month="2026-06", sub_teams=None,
            limit=k.UNDER_5_MAX_ROWS, user={"sub": "u"}))
    finally:
        k.get_datalake_gold_pool, k.get_pool = orig_gold, orig_hub
    row = resp["data"][0]
    assert row["lane_key"] == "ACME::A, TX - B, TX"
    assert row["expiration_date"] == "2026-10-01"
    assert row["action_plan"] == "renegotiate"
    assert resp["meta"]["threshold_pct"] == 5.0


# ---------------------------------------------------------------------------
# Layer 3 — replay against real gold (opt-in; the suite stays offline)
# ---------------------------------------------------------------------------

_GOLD = os.environ.get("SAVINGS_DATABASE_URL")


@pytest.mark.skipif(not _GOLD, reason="SAVINGS_DATABASE_URL not set — offline run")
def test_live_the_statement_parses_and_every_row_is_under_the_threshold():
    """PREPARE catches what the linters cannot — a renamed column, a type
    mismatch, a dropped table. Then EXECUTE, because the threshold is the
    whole feature: a returned row at 7% would mean the HAVING is not doing
    what the text says it does."""
    import asyncpg

    url = re.sub(r"[?&]sslmode=\w+", "", _GOLD)
    gold, _, _ = _drive()
    sql, params = gold.sqls[0], gold.params[0]

    async def run():
        conn = await asyncpg.connect(url, ssl="require")
        try:
            await conn.execute("SET statement_timeout = '30s'")
            await conn.execute(f"PREPARE _u5 AS {sql}")
            await conn.execute("DEALLOCATE _u5")
            return await conn.fetch(sql, *params)
        finally:
            await conn.close()

    rows = asyncio.run(run())
    for r in rows:
        assert r["revenue"] > 0
        assert float(r["margin_pct"]) < k.UNDER_MARGIN_PCT
        assert r["customer"] and r["lane"]
