"""Booker Performance Scorecard — Bruno PDF 2026-08-31 (both pages).

Page 2 (Scorecard tab)
  R1  Carrier Cost = 0 → the order leaves the Orders table AND the KPIs.
  R2  Revenue 150 / Cost 150 and Revenue 250 / Cost 150 → same.
  R3  "Broken Threshold" KPI becomes "Compliance Threshold" = 1 − broken.

Page 1 (new Rank tab)
  Bookers ranked by # of Bookings in the last COMPLETED week, with the
  positions moved against the week before, plus the threshold measure and Cost
  Saving over that week.

⚠ SUPERSEDED IN PART by Bruno PDF 2026-09-03 (see
``test_booker_scorecard_bruno_2026_09_03.py``): the Rank tab's week became
Sat-Fri and its population became `RANK_ROSTER` only. The assertions below were
rewritten to that reality rather than deleted — the RULES they pin (the
in-progress week is never ranked, `posted_by` never re-ranks, one scan, a
booker who stopped keeps a row) all still hold. Stub bookers are roster names
now, because a non-roster name no longer produces a row at all.

Measured before shipping (MTD 2026-08, TEAM-DFW): the exclusions take the
universe from 1,425 to 1,395 orders and profit from $312,582 to $295,042 —
mostly the 8 zero-carrier-cost loads. Material, and Bruno's explicit call.

⚠ The exclusions live in ``_base_sql``, the ONE CTE every endpoint builds its
universe from. Added anywhere else — the /orders page query, say — the table
would shrink while the KPI cards above it did not, which is the §16/§96 class
this report has already been bitten by. The parametrised test below drives
EVERY endpoint rather than asserting the helper once.

⚠ Several assertions read SQL TEXT. With correct data, reverting a NULL-safety
rule still returns plausible rows, so the text is the only thing that can fail.
They are mutation-checked.
"""

from __future__ import annotations

import asyncio
import inspect
import re
import types
from datetime import date, datetime, timedelta

import pytest

from app.booker_names import matches_roster, name_key, roster_keys
from app.routers import booker_scorecard as bs


_SOURCE = inspect.getsource(bs)


# ==========================================================================
# R1 / R2 — the exclusions
# ==========================================================================


def _rate_conf_where() -> str:
    """The WHERE of the `rate_conf` CTE, as one string (never line by line).

    ⚠ Whole-statement, `re.S`. Every one of these predicates is split across
    lines, so a line-based scan reports a clean sweep while the rule is absent
    (§96). And it is sliced to the CTE that OWNS the universe: a guard parked
    in a neighbouring clause is not the same rule, which is what the mutation
    check proves.
    """
    body = _SOURCE.split("rate_conf AS MATERIALIZED (", 1)[1]
    body = body.split("\n    sc AS (", 1)[0]
    return body.split("WHERE rp.rn = 1", 1)[1]


def test_the_slice_actually_contains_the_universe_predicate():
    """Guards the scan's INPUT. If the slice ever comes back empty the
    assertions below pass for free."""
    where = _rate_conf_where()
    assert "br.status <> 'V'" in where
    assert "br.team_id = ANY(" in where


def test_zero_carrier_cost_is_excluded():
    assert re.search(
        r"\(br\.total_charge\s*-\s*br\.margin_amt\)\s*IS\s+DISTINCT\s+FROM\s+0",
        _rate_conf_where(),
        re.S,
    )


@pytest.mark.parametrize("revenue", ["150", "250"])
def test_the_placeholder_rate_pairs_are_excluded(revenue):
    assert re.search(
        r"\(br\.total_charge,\s*br\.total_charge\s*-\s*br\.margin_amt\)\s*"
        r"IS\s+DISTINCT\s+FROM\s*\(" + revenue + r"::numeric,\s*150::numeric\)",
        _rate_conf_where(),
        re.S,
    )


def test_the_exclusions_are_null_safe():
    """⚠ `NOT (br.total_charge = 150 AND …)` evaluates to NULL when revenue is
    NULL, and Postgres DELETES the row — silently dropping every order whose
    revenue has not posted yet. Only an explicit ZERO carrier cost goes.

    Row-wise `IS DISTINCT FROM` is the null-safe spelling, so the presence of a
    `NOT (` around these comparisons is itself the defect.
    """
    where = _rate_conf_where()
    assert not re.search(r"NOT\s*\(\s*br\.total_charge", where, re.S), (
        "a NOT(...) form here deletes NULL-revenue orders with no error"
    )


# The three predicates, as emitted. Counting occurrences of the phrase would be
# off by the SQL comment that explains it — assert the rules, not a tally.
_EXCLUSION_RES = (
    re.compile(r"\(br\.total_charge\s*-\s*br\.margin_amt\)\s*"
               r"IS\s+DISTINCT\s+FROM\s+0::numeric", re.S),
    re.compile(r"IS\s+DISTINCT\s+FROM\s*\(150::numeric,\s*150::numeric\)", re.S),
    re.compile(r"IS\s+DISTINCT\s+FROM\s*\(250::numeric,\s*150::numeric\)", re.S),
)


class _StubPool:
    def __init__(self, rows=None):
        self.sqls: list[str] = []
        self.rows = rows or []

    async def fetch(self, sql, *params):
        self.sqls.append(sql)
        return list(self.rows)

    async def fetchrow(self, sql, *params):
        self.sqls.append(sql)
        return self.rows[0] if self.rows else None


_NO_THRESHOLDS: dict = {}


def _drive(fn, rows=None, today=None, thresholds=_NO_THRESHOLDS, **kwargs):
    """Drive an endpoint against a stub pool.

    ⚠ `today` pins the clock. /rank resolves its own window from `cst_today()`,
    so a stub row dated in August lands in a DIFFERENT week each time the real
    calendar advances — a test that passes today and goes red next Saturday for
    no code change. Every rank test that asserts on bucketing passes it.

    ⚠ `thresholds` is what `_thresholds` returns: `{}` (the default — the AP
    source is up and knows none of these orders), a dict, or `None` (the source
    is DOWN, which is a different answer). It is a parameter because this
    helper stubs `_thresholds` unconditionally: a caller that patched it before
    calling had its stub silently replaced, and every threshold assertion then
    ran against an empty dict and read as a broken feature.
    """
    pool = _StubPool(rows)
    orig_pool = bs.get_datalake_gold_pool
    orig_thresh = bs._thresholds
    orig_clock = bs.cst_today
    bs.get_datalake_gold_pool = lambda request: pool

    async def _stub_thresholds(request, order_ids):
        return thresholds

    bs._thresholds = _stub_thresholds
    if today is not None:
        bs.cst_today = lambda: today
    try:
        request = types.SimpleNamespace(
            app=types.SimpleNamespace(state=types.SimpleNamespace())
        )
        resp = asyncio.run(fn(request=request, _user={}, **kwargs))
    finally:
        bs.get_datalake_gold_pool = orig_pool
        bs._thresholds = orig_thresh
        bs.cst_today = orig_clock
    return pool, resp


_SCOPE = dict(contract_type=None, customer_name=None, posted_by=None)
_DATED = dict(range="mtd", start_date=None, end_date=None, **_SCOPE)

_EVERY_ENDPOINT = (
    ("summary", dict(_DATED, adjustment=0.0)),
    ("orders", dict(_DATED, adjustment=0.0, sort="profit_desc", page=0, limit=200)),
    ("filters", dict(range="mtd", start_date=None, end_date=None)),
    ("weekly", dict(_SCOPE)),
    ("rank", dict(_SCOPE)),
)


@pytest.mark.parametrize("name,kwargs", _EVERY_ENDPOINT)
def test_every_endpoint_inherits_the_exclusions(name, kwargs):
    """§16 — the table, its totals, the KPI cards, the pickers and both trend
    views must see ONE population. Asserted per endpoint, not once on the
    helper: a future endpoint that hand-rolls its own CTE is the failure mode."""
    pool, _ = _drive(getattr(bs, name), **kwargs)
    sql = "\n".join(pool.sqls)
    missing = [i for i, rx in enumerate(_EXCLUSION_RES) if not rx.search(sql)]
    assert not missing, f"{name} is missing exclusion(s) {missing}"


# ==========================================================================
# R3 — Compliance Threshold
# ==========================================================================


def _rows(*specs):
    """(order_id, carrier_cost) tuples as stub Records."""
    return [
        {"order_id": oid, "carrier_cost": cc, "profit": 100.0, "revenue": 1000.0,
         "otp_on_time": True, "otd_on_time": True, "rc_count": 1,
         "posted_by": "TEST BOOKER", "posted_date": datetime(2026, 8, 25, 9, 0)}
        for oid, cc in specs
    ]


def test_compliance_is_exactly_one_minus_broken():
    rows = _rows(("A", 900.0), ("B", 1100.0), ("C", 1200.0), ("D", 700.0))
    thresholds = {"A": 1000.0, "B": 1000.0, "C": 1000.0, "D": 1000.0}
    st = bs._threshold_stats(rows, thresholds)
    assert st["broken_threshold"] == 2
    assert st["threshold_orders"] == 4
    assert st["broken_threshold_pct"] == pytest.approx(0.5)
    assert st["compliance_threshold_pct"] == pytest.approx(1.0 - st["broken_threshold_pct"])


def test_compliance_is_a_fraction_not_a_percentage():
    """⚠ fmtPct multiplies by 100. Handing it an already-scaled value prints
    100x wrong with no error — the §95 sign-and-scale trap."""
    rows = _rows(("A", 900.0), ("B", 1100.0))
    st = bs._threshold_stats(rows, {"A": 1000.0, "B": 1000.0})
    assert 0.0 <= st["compliance_threshold_pct"] <= 1.0


def test_compliance_is_none_when_the_ap_source_is_down():
    """None, never 0.0 — a 0% compliance card is an alarm, and an outage must
    not raise one. `_thresholds` returns None (not {}) for exactly this."""
    st = bs._threshold_stats(_rows(("A", 900.0)), None)
    assert st["compliance_threshold_pct"] is None
    assert st["broken_threshold_pct"] is None


def test_compliance_is_none_when_no_order_carries_a_threshold():
    """0 comparable orders is an undefined ratio, not 100% compliant."""
    st = bs._threshold_stats(_rows(("A", 900.0)), {})
    assert st["compliance_threshold_pct"] is None


def test_summary_and_orders_share_one_compliance_definition():
    """§69 — both fold the SAME helper, so they cannot drift.

    Asserted structurally rather than by counting a string: the figure exists
    only inside `_threshold_stats`, and every consumer must go through it.
    """
    stats_src = inspect.getsource(bs._threshold_stats)
    # Both branches of the helper publish the key — the outage branch included,
    # or a caller would KeyError exactly when AP is down.
    # The quoted form is the dict KEY; the helper's docstring also names it in
    # prose, which is not a definition.
    assert stats_src.count('"compliance_threshold_pct"') == 2
    assert stats_src.count('"compliant_threshold"') == 2

    # Nobody DERIVES the figure outside the helper.
    #
    # ⚠ This used to read `"compliance_threshold_pct" not in others`, which was
    # the right property spelled as the wrong assertion: it also forbade a
    # legitimate FORWARD, and went red the moment /rank put the same helper's
    # value on its own wire (Bruno 2026-09-03 R1). The property meant is
    # "every mention outside the helper reads it back from `stats`" — a second
    # `1 − broken/comparable` anywhere else is the defect, because two
    # derivations drift and the two tabs then disagree about one person.
    others = _SOURCE.replace(stats_src, "")
    for key in ("compliance_threshold_pct", "compliant_threshold"):
        for line in others.splitlines():
            if key not in line:
                continue
            assert f'stats["{key}"]' in line, (
                f"{key} is derived outside _threshold_stats: {line.strip()}"
            )
    # And the arithmetic itself appears nowhere else, in any spelling.
    assert not re.search(r"1(\.0)?\s*-\s*\w*broken", others), (
        "a second `1 - broken` derivation exists outside _threshold_stats"
    )

    for endpoint in (bs.summary, bs.orders, bs.rank):
        assert "_threshold_stats(" in inspect.getsource(endpoint), endpoint.__name__


# ==========================================================================
# Page 1 — the Rank tab
# ==========================================================================


def test_the_rank_window_is_two_completed_weeks():
    """⚠ Never the in-progress week. Shipped on Monday 2026-08-31, when the
    current week held ONE day: ranking it against a full previous week produced
    +13-position moves for a booker who merely started early. Same rule
    `attrition_core` states for its own weekly windows.

    The week turned Sat-Fri on 2026-09-03; the rule did not move. The
    weekday-agnostic half of this assertion is deliberately kept here, and the
    Saturday boundary itself is pinned in the 09-03 file.
    """
    for weekday in range(7):
        today = date(2026, 8, 31) + timedelta(days=weekday)
        prev_s, prev_e, cur_s, cur_e = bs._rank_weeks(today)
        assert cur_s.weekday() == prev_s.weekday()
        assert (cur_e - cur_s).days == 6 and (prev_e - prev_s).days == 6
        assert prev_e + timedelta(days=1) == cur_s, "the two weeks must be adjacent"
        # The whole compared week is in the past, on every day of the week.
        assert cur_e < today, "the in-progress week leaked into the ranking"
        assert (today - cur_e).days <= 7, (
            "the ranked week is more than one week stale"
        )


def test_rank_is_competition_ranked_so_ties_consume_slots():
    """1,2,2,4 — "rank 4 of N" must keep meaning "three bookers are ahead"."""
    ranks = bs._rank_rows({
        "A": {"bookings": 10},
        "B": {"bookings": 7},
        "C": {"bookings": 7},
        "D": {"bookings": 3},
    })
    assert ranks == {"A": 1, "B": 2, "C": 2, "D": 4}


def test_rank_ties_break_deterministically():
    """Two runs over the same data must not swap tied bookers around."""
    agg = {"Zoe": {"bookings": 5}, "Abe": {"bookings": 5}}
    assert bs._rank_rows(agg) == bs._rank_rows(dict(reversed(list(agg.items()))))


def test_the_roster_resolves_brunos_spellings():
    """⚠ Bruno's PDF and McLeod disagree on three names. Matching goes through
    the shared normaliser, never string equality."""
    keys = roster_keys(bs.RANK_ROSTER)
    for live in ("ANTHARES MONTOYA", "JONATHAN HERNANDEZ", "ROBERTO BARCENAS",
                 "EUGENIO MIRANDA", "JONATHAN RODRIGUEZ", "CINDY DE LOS SANTOS"):
        assert matches_roster(live, keys), live
    # A compound surname written either way is one person.
    assert name_key("Andres Sanmiguel") == name_key("ANDRES SAN MIGUEL")
    # And the reversed "Surname, Forename" spelling McLeod sometimes records.
    assert matches_roster("Montoya Anthares", keys)


def test_the_roster_does_not_swallow_a_different_person():
    """ARMANDO CALVILLO is the busiest DFW booker and is deliberately NOT on
    Bruno's list — the roster orders the picker, it must not mislabel people."""
    keys = roster_keys(bs.RANK_ROSTER)
    for outsider in ("ARMANDO CALVILLO", "KARLA TREVINO", "LORENZO AGUILAR"):
        assert not matches_roster(outsider, keys), outsider


def test_the_rank_roster_is_not_the_podium_roster():
    """⚠ Two DIFFERENT lists of people that happen to overlap on 10 names.
    Only the normalisation is shared (§69); merging them would silently rewrite
    who each report is about."""
    from app.routers.podium_top import BOOKER_NAMES

    assert set(bs.RANK_ROSTER) != set(BOOKER_NAMES)
    assert len(bs.RANK_ROSTER) == 15


def test_rank_takes_no_date_parameters():
    """⚠ Like /weekly. Declaring them and ignoring them would let a
    hand-crafted URL widen a window the UI captions as two fixed weeks (§55)."""
    params = inspect.signature(bs.rank).parameters
    for forbidden in ("range", "start_date", "end_date"):
        assert forbidden not in params, forbidden


def test_rank_scans_the_bookings_table_once():
    """§73 — `mcleod_gld_order_post_hist` is 1.9M rows with no usable index, so
    every execution is a full sequential scan. Both weeks come from ONE 14-day
    pass, which also gives each order exactly one week instead of crediting a
    re-confirmed order to both."""
    pool, _ = _drive(bs.rank, today=date(2026, 8, 31), **_SCOPE)
    assert len(pool.sqls) == 1


def test_posted_by_filters_the_rows_but_never_the_ranking():
    """§75 — rank is a RULE. Filtering before ranking would make every
    single-name selection read "rank 1 of 1"."""
    rows = [
        {"order_id": f"O{i}", "carrier_cost": 500.0, "posted_by": name,
         "posted_date": datetime(2026, 8, 25, 9, 0)}
        # ⚠ Roster names since 2026-09-03: a non-roster booker no longer
        # produces a row at all, so the old placeholders would have made this
        # assertion vacuously true against an empty table.
        for name, n in (("EUGENIO MIRANDA", 5), ("JUAN REYNA", 1))
        for i in range(n)
    ]
    _, unfiltered = _drive(bs.rank, rows=rows, today=date(2026, 8, 31), **_SCOPE)
    _, filtered = _drive(bs.rank, rows=rows, today=date(2026, 8, 31),
                         contract_type=None, customer_name=None,
                         posted_by=["JUAN REYNA"])

    assert unfiltered["data"]["total_bookers"] == 2
    # The population, and therefore the rank, is unchanged by the picker.
    assert filtered["data"]["total_bookers"] == 2
    only = filtered["data"]["rows"]
    assert len(only) == 1 and only[0]["booker"] == "JUAN REYNA"
    assert only[0]["rank"] == 2, "the picker renumbered the league"


def test_posted_by_never_reaches_the_rank_query():
    """⚠ The assertion above CANNOT catch this on its own: a stub pool returns
    the same rows whatever the statement says, so pushing `posted_by` down into
    `_base_sql` passes every row-level check while silently re-ranking a
    one-person universe in production. Caught by a mutation test; the fix is to
    read the emitted SQL.

    The predicate must be absent from /rank and PRESENT on a dated endpoint —
    the second half proves the scan can see a known positive (§91).
    """
    pool, _ = _drive(bs.rank, contract_type=None, customer_name=None,
                     posted_by=["JUAN REYNA"])
    rank_sql = "\n".join(pool.sqls)
    assert "TRIM(rp.posted_by_name) = ANY(" not in rank_sql, (
        "/rank pushed the Posted By picker into the query, which re-ranks a "
        "filtered universe (§75)"
    )

    pool2, _ = _drive(bs.summary, range="mtd", start_date=None, end_date=None,
                      contract_type=None, customer_name=None,
                      posted_by=["JUAN REYNA"], adjustment=0.0)
    assert "TRIM(rp.posted_by_name) = ANY(" in "\n".join(pool2.sqls), (
        "the scan cannot see the predicate at all — the check above is vacuous"
    )


def test_a_booker_who_stopped_still_gets_a_row():
    """§91/§75 — someone who booked last week and nothing this week has fallen
    to the bottom. That is information; an inner join would render it as a
    missing row instead of a red one."""
    rows = [
        {"order_id": "OLD", "carrier_cost": 500.0, "posted_by": "OSCAR MACIAS",
         "posted_date": datetime(2026, 8, 18, 9, 0)},
        {"order_id": "NEW", "carrier_cost": 500.0, "posted_by": "DANIEL SALAZAR",
         "posted_date": datetime(2026, 8, 25, 9, 0)},
    ]
    # Pin the clock so the two stub dates land in the intended weeks: with
    # today = Mon 2026-08-31 the Sat-Fri pair is 15-21 Aug and 22-28 Aug.
    _, resp = _drive(bs.rank, rows=rows, today=date(2026, 8, 31), **_SCOPE)
    by_name = {r["booker"]: r for r in resp["data"]["rows"]}
    assert set(by_name) == {"OSCAR MACIAS", "DANIEL SALAZAR"}
    assert by_name["OSCAR MACIAS"]["rank"] is None
    assert by_name["OSCAR MACIAS"]["bookings"] == 0
    assert by_name["OSCAR MACIAS"]["prev_bookings"] == 1
    # A first appearance is "new", never a 0 that claims the position held.
    assert by_name["DANIEL SALAZAR"]["rank_delta"] is None
    assert by_name["DANIEL SALAZAR"]["rank"] == 1
    # Unranked bookers sort last, not first.
    assert resp["data"]["rows"][0]["booker"] == "DANIEL SALAZAR"


def test_rank_survives_an_ap_outage():
    """The threshold source is secondary — the ranking must still render."""
    rows = [{"order_id": "A", "carrier_cost": 500.0, "posted_by": "EUGENIO MIRANDA",
             "posted_date": datetime(2026, 8, 25, 9, 0)}]
    pool = _StubPool(rows)
    orig_pool = bs.get_datalake_gold_pool
    orig_thresh = bs._thresholds
    bs.get_datalake_gold_pool = lambda request: pool

    async def _down(request, order_ids):
        return None

    bs._thresholds = _down
    orig_clock = bs.cst_today
    bs.cst_today = lambda: date(2026, 8, 31)
    try:
        request = types.SimpleNamespace(
            app=types.SimpleNamespace(state=types.SimpleNamespace())
        )
        resp = asyncio.run(bs.rank(request=request, _user={}, **_SCOPE))
    finally:
        bs.get_datalake_gold_pool = orig_pool
        bs._thresholds = orig_thresh
        bs.cst_today = orig_clock
    row = resp["data"]["rows"][0]
    assert row["bookings"] == 1
    assert row["broken_threshold"] is None and row["cost_saving"] is None
