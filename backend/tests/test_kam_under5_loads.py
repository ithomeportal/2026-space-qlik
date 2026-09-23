"""KAM Performance - DFW — Tab 8 "Loads Under 5%".

R1 (Bruno PDF 2026-09-21) listed every LANE under 5% for a calendar month.
R2 (Bruno PDF 2026-09-23): "Don't display the information group by lane,
instead show the information by load" + "Add the filter YTD, MTD and WTD".

What these tests exist to stop:

* the threshold staying a lane-level HAVING after the grain moved to the load
  (a 6% lane hides its -30% loads — the very rows this view is for);
* `margin_amt < 0` leaking in from Worst 10 Lanes (a +3% load IS under 5%);
* the zero/negative-charge guard going missing (a negative charge flips the
  ratio, so a loss would read as a healthy margin);
* the summary totals describing ONE PAGE instead of the population (§109);
* a client-supplied sort key reaching the ORDER BY unvetted.

Three layers, cheapest first, following `test_xray_dfw_gm_tab.py`:

1. the emitted-SQL linters over a stub pool,
2. the range/sort/page/envelope unit contracts,
3. `test_live_*` — PREPARE and run against real gold, skipped unless
   ``SAVINGS_DATABASE_URL`` is set, so the suite stays offline.
"""

from __future__ import annotations

import asyncio
import os
import re
import types
from datetime import date, timedelta

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


_DEFAULTS = dict(
    range="mtd", start_date=None, end_date=None, sub_teams=None,
    sort="margin_pct", dir="asc", page=1, page_size=k.UNDER_5_PAGE_SIZE,
    user={"sub": "user-1"},
)


def _drive(gold_rows=None, hub_rows=None, **overrides):
    """Drive `/under-5-loads` against stub pools. Returns (gold, hub, payload)."""
    gold, hub = _StubPool(gold_rows), _StubPool(hub_rows)
    orig_gold, orig_hub = k.get_datalake_gold_pool, k.get_pool
    k.get_datalake_gold_pool = lambda request: gold
    k.get_pool = lambda request: hub
    try:
        request = types.SimpleNamespace(
            app=types.SimpleNamespace(state=types.SimpleNamespace())
        )
        call = {**_DEFAULTS, **overrides}
        resp = asyncio.run(k.under_5_loads(request=request, **call))
    finally:
        k.get_datalake_gold_pool, k.get_pool = orig_gold, orig_hub
    return gold, hub, resp


def _strip_comments(sql: str) -> str:
    """Drop `-- ...` lines. Scan the executable text, never the prose that
    quotes the very predicates these tests assert about."""
    return "\n".join(
        line for line in sql.split("\n") if not line.strip().startswith("--")
    )


def _sql(gold) -> str:
    return _strip_comments(gold.sqls[0])


def _base_cte(sql: str) -> str:
    m = re.search(r"WITH base AS \((.+?)\n\s*\),\n\s*scoped AS", sql, re.S)
    assert m, "base CTE not found"
    return m.group(1)


def _row(**kw):
    r = {
        "total_loads": 1, "total_revenue": 1000, "total_profit": 10,
        "order_id": "0123456", "departure": date(2026, 9, 22),
        "customer": "ACME", "lane": "A, TX - B, TX", "team": "TM2",
        "revenue": 1000, "profit": 10, "margin_pct": 1.0,
    }
    r.update(kw)
    return r


# ---------------------------------------------------------------------------
# The population — one row per LOAD, threshold on the load's own ratio
# ---------------------------------------------------------------------------


def test_the_threshold_is_per_load_not_a_group_HAVING():
    """🔴 R2's whole point. Left as R1's HAVING over lane sums, a lane at 6%
    would hide its -30% loads — the rows Bruno asked to see."""
    sql = _sql(_drive()[0])
    assert "HAVING" not in sql
    assert "GROUP BY" not in sql
    assert (
        f"b.margin_amt::numeric / b.total_charge::numeric * 100 < {k.UNDER_MARGIN_PCT}"
        in _base_cte(sql)
    )


def test_one_row_per_load_carries_the_order_id():
    assert "TRIM(b.id)                           AS order_id" in _sql(_drive()[0])


def test_the_negative_margin_row_filter_is_absent():
    """Not Worst 10 Lanes' population: a load at +3% is under 5% without
    losing money, and belongs here."""
    assert "margin_amt < 0" not in _sql(_drive()[0])


def test_worst_lanes_still_has_it():
    """The sibling must keep measuring the neg-margin slice, or IT stops tying
    out to the Losses email. One of these two failing alone = a moved
    population."""
    gold, hub = _StubPool(), _StubPool()
    orig_gold, orig_hub = k.get_datalake_gold_pool, k.get_pool
    k.get_datalake_gold_pool = lambda request: gold
    k.get_pool = lambda request: hub
    try:
        request = types.SimpleNamespace(
            app=types.SimpleNamespace(state=types.SimpleNamespace())
        )
        asyncio.run(k.worst_lanes(
            request=request, range="ytd", start_date=None, end_date=None,
            limit=10, sub_teams=None, user={"sub": "user-1"},
        ))
    finally:
        k.get_datalake_gold_pool, k.get_pool = orig_gold, orig_hub
    assert "b.margin_amt < 0" in _strip_comments(gold.sqls[0])


def test_the_charge_is_guarded_positive():
    """One predicate, two jobs: the §111 zero-charge filter (an unbilled load
    has no margin) and the sign guard (a negative charge flips the ratio, so a
    loss would score as a healthy margin). Measured 2026-09-23: 0 negative
    charges in DFW 2026 — the sentry for the day that changes."""
    base = _base_cte(_sql(_drive()[0]))
    assert "AND b.total_charge > 0" in base
    # and it precedes the division it protects
    assert base.index("b.total_charge > 0") < base.index("* 100 <")


def test_the_totals_span_the_population_not_the_page():
    """§109: the summary line is the whole filtered set. `totals` must read
    `scoped`, never `pg` (the LIMIT/OFFSET slice)."""
    sql = _sql(_drive()[0])
    totals = re.search(r"totals AS \((.+?)\n\s*\),\n\s*pg AS", sql, re.S)
    assert totals and "FROM scoped" in totals.group(1)
    assert "LIMIT" not in totals.group(1)
    assert "FROM totals t\n        LEFT JOIN pg ON TRUE" in sql


# ---------------------------------------------------------------------------
# The window — YTD / MTD / WTD / Custom, CST
# ---------------------------------------------------------------------------


def _window(**kw):
    _, _, resp = _drive(**kw)
    w = resp["meta"]["window"]
    return date.fromisoformat(w["start"]), date.fromisoformat(w["end"])


def test_default_is_MTD_in_CST():
    today = k.cst_today()
    assert _window() == (today.replace(day=1), today)


def test_ytd_starts_on_jan_1():
    assert _window(range="ytd") == (k.YEAR_START, k.cst_today())


def test_wtd_is_monday_anchored():
    s, e = _window(range="wtd")
    assert s.weekday() == 0 or s == k.YEAR_START
    assert e == k.cst_today()
    assert e - s < timedelta(days=7)


def test_custom_is_honoured_and_bound_as_params():
    gold, _, resp = _drive(range="custom", start_date=date(2026, 3, 1),
                           end_date=date(2026, 3, 31))
    assert resp["meta"]["window"] == {"start": "2026-03-01", "end": "2026-03-31"}
    assert date(2026, 3, 1) in gold.params[0]
    assert date(2026, 3, 31) in gold.params[0]


# ---------------------------------------------------------------------------
# Sort + page — a client-chosen ORDER BY must be whitelisted
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("sort", sorted(k.UNDER_5_SORTS))
@pytest.mark.parametrize("dir_", ["asc", "desc"])
def test_every_whitelisted_sort_reaches_the_order_by(sort, dir_):
    sql = _sql(_drive(sort=sort, dir=dir_)[0])
    col = k.UNDER_5_SORTS[sort]
    assert f"ORDER BY {col} {dir_.upper()} NULLS LAST, order_id ASC" in sql
    assert f"ORDER BY pg.{col} {dir_.upper()} NULLS LAST, pg.order_id ASC" in sql


@pytest.mark.parametrize(
    "sort,dir_",
    [("margin_pct; DROP TABLE x", "asc"), ("total_charge", "asc"),
     ("margin_pct", "sideways"), ("margin_pct", "")],
)
def test_an_unknown_sort_or_dir_is_a_400(sort, dir_):
    with pytest.raises(HTTPException) as exc:
        _drive(sort=sort, dir=dir_)
    assert exc.value.status_code == 400


def test_default_order_is_worst_margin_first():
    assert "ORDER BY margin_pct ASC NULLS LAST, order_id ASC" in _sql(_drive()[0])


def test_page_becomes_limit_and_offset_params():
    gold, _, resp = _drive(page=3, page_size=25)
    assert gold.params[0][-2:] == (25, 50)
    assert resp["meta"]["page"] == 3 and resp["meta"]["limit"] == 25


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
    gold, _, _ = _drive(sub_teams="TM2,TEAM1,tm3,../*")
    assert "TRIM(b.team) = ANY($4)" in _sql(gold)
    assert gold.params[0][3] == ["TM2", "TM3"]


def test_no_team_filter_means_no_predicate():
    assert "TRIM(b.team) = ANY" not in _sql(_drive()[0])


def test_the_notes_are_the_worst_lanes_rows_scoped_to_the_caller():
    """One action plan per LANE, whichever tab surfaced it (Diego 2026-09-23:
    keep them lane-keyed) — the same rows `PUT /worst-lane-notes` writes."""
    _, hub, _ = _drive(user={"sub": "someone-else"})
    assert "FROM kam_worst_lane_notes WHERE user_id = $1" in hub.sqls[0]
    assert hub.params[0] == ("someone-else",)


# ---------------------------------------------------------------------------
# The envelope
# ---------------------------------------------------------------------------


def test_rows_carry_the_load_and_its_lanes_plan():
    rows = [_row(order_id="0000001", total_loads=2, total_revenue=2500,
                 total_profit=-40),
            _row(order_id="0000002", total_loads=2, total_revenue=2500,
                 total_profit=-40, revenue=1500, profit=-50, margin_pct=-3.33)]
    notes = [{"lane_key": "ACME::A, TX - B, TX",
              "expiration_date": date(2026, 10, 1), "action_plan": "renegotiate"}]
    _, _, resp = _drive(gold_rows=rows, hub_rows=notes)
    assert [r["order_id"] for r in resp["data"]] == ["0000001", "0000002"]
    first = resp["data"][0]
    assert first["departure"] == "2026-09-22"
    assert first["team"] == "TM2"
    assert first["lane_key"] == "ACME::A, TX - B, TX"
    # both loads on the lane show the lane's one plan
    assert {r["action_plan"] for r in resp["data"]} == {"renegotiate"}
    assert first["expiration_date"] == "2026-10-01"
    meta = resp["meta"]
    assert meta["total"] == 2
    assert meta["totals"] == {"loads": 2, "revenue": 2500.0, "profit": -40.0}
    assert meta["threshold_pct"] == 5.0


def test_a_page_past_the_end_keeps_the_real_total():
    """The LEFT JOIN yields one all-NULL `pg` row carrying the totals. It must
    not render as a load, and the count must not read 0."""
    empty = [{"total_loads": 175, "total_revenue": 9e5, "total_profit": 1e3,
              "order_id": None, "departure": None, "customer": None,
              "lane": None, "team": None, "revenue": None, "profit": None,
              "margin_pct": None}]
    _, _, resp = _drive(gold_rows=empty, page=99)
    assert resp["data"] == []
    assert resp["meta"]["total"] == 175


def test_no_rows_at_all_is_an_empty_envelope():
    _, _, resp = _drive(gold_rows=[])
    assert resp["data"] == [] and resp["meta"]["total"] == 0


# ---------------------------------------------------------------------------
# Layer 3 — replay against real gold (opt-in; the suite stays offline)
# ---------------------------------------------------------------------------

_GOLD = os.environ.get("SAVINGS_DATABASE_URL")


@pytest.mark.skipif(not _GOLD, reason="SAVINGS_DATABASE_URL not set — offline run")
def test_live_the_statement_parses_and_every_load_is_under_the_threshold():
    """PREPARE catches what the linters cannot; EXECUTE proves the threshold
    and that the totals tie to the rows when everything fits on one page."""
    import asyncpg

    url = re.sub(r"[?&]sslmode=\w+", "", _GOLD)
    gold, _, _ = _drive(range="wtd", page_size=k.UNDER_5_MAX_PAGE_SIZE)
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

    rows = [r for r in asyncio.run(run()) if r["order_id"] is not None]
    for r in rows:
        assert r["revenue"] > 0
        assert float(r["margin_pct"]) < k.UNDER_MARGIN_PCT
        assert r["customer"] and r["lane"]
    if rows and rows[0]["total_loads"] <= k.UNDER_5_MAX_PAGE_SIZE:
        assert len(rows) == rows[0]["total_loads"]
        assert abs(sum(float(r["profit"]) for r in rows)
                   - float(rows[0]["total_profit"])) < 0.01
