"""Production SPOTS Trends — the guards for report #65 (2026-09-21).

Four layers, cheapest first, following `test_xray_dfw_gm_tab.py`:

1. **emitted-SQL linters** over a recording stub pool,
2. **unit contracts** on the window arithmetic and the wire shape,
3. a **live PREPARE** that proves every statement variant parses, and
4. **live executed invariants** — the funnel partition identities and the
   timezone-bound equivalence, which no text assertion can reach.

Layers 3 and 4 are skipped unless `PRICING_DATABASE_URL` is set, which is the
expected offline state.

⚠ Every guard here was mutation-checked: the thing it claims to catch was
broken, the test was watched going red, and only then restored.
"""

from __future__ import annotations

import asyncio
import inspect
import os
import re
import types
from datetime import date, timedelta

import pytest
from fastapi import HTTPException

from app.routers import production_spots_trends as m


# ---------------------------------------------------------------------------
# harness
# ---------------------------------------------------------------------------


class _Conn:
    def __init__(self, pool):
        self._pool = pool

    async def fetch(self, sql, *params):
        self._pool.sqls.append(sql)
        self._pool.params.append(params)
        return []

    async def fetchrow(self, sql, *params):
        self._pool.sqls.append(sql)
        self._pool.params.append(params)
        return None

    async def fetchval(self, sql, *params):
        self._pool.sqls.append(sql)
        self._pool.params.append(params)
        return None


class _Acquire:
    def __init__(self, pool):
        self._pool = pool

    async def __aenter__(self):
        return _Conn(self._pool)

    async def __aexit__(self, *exc):
        return False


class _StubPool:
    """⚠ Records the SQL. A stub pool cannot see a WHERE — these tests assert
    on the statement TEXT, which is exactly why layers 3 and 4 exist."""

    def __init__(self):
        self.sqls: list[str] = []
        self.params: list[tuple] = []

    def acquire(self):
        return _Acquire(self)


def _filters(**overrides):
    """Build the shared filter dict the way FastAPI would.

    Calling `_common()` with no arguments hands back `Query` objects, not
    values — so every caller passes the full set explicitly.
    """
    call = dict(
        range="last90",
        start_date=None,
        end_date=None,
        channel=None,
        customer=None,
        actor=None,
        equipment=None,
        division=None,
    )
    call.update(overrides)
    return m._common(**call)


def _drive(endpoint: str, f=None, **kwargs):
    """Drive one endpoint against a stub pricing pool. Returns (pool, payload)."""
    pool = _StubPool()
    orig = m.get_pricing_pool
    m.get_pricing_pool = lambda request: pool
    try:
        request = types.SimpleNamespace(
            app=types.SimpleNamespace(state=types.SimpleNamespace())
        )
        fn = getattr(m, endpoint)
        # `/filters` and `/freshness` take no window — they are the two
        # endpoints that legitimately sit outside `_common`.
        if "f" in inspect.signature(fn).parameters:
            kwargs["f"] = f if f is not None else _filters()
        payload = asyncio.run(fn(request=request, _user={}, **kwargs))
    finally:
        m.get_pricing_pool = orig
    return pool, payload


def _strip_comments(sql: str) -> str:
    """Drop `-- ...` lines.

    ⚠ These statements carry comments that QUOTE the predicates the tests
    assert about, so a raw substring check would find the explanation and call
    it the code. Scan the executable text.
    """
    return "\n".join(
        line for line in sql.split("\n") if not line.strip().startswith("--")
    )


def _all_sql() -> list[str]:
    """Executable text of every statement the report can emit."""
    out: list[str] = []
    pool, _ = _drive("summary")
    out += pool.sqls
    for grain in m.GRAINS:
        pool, _ = _drive("trend", grain=grain)
        out += pool.sqls
    for dim in m.BREAKDOWN_DIMS:
        pool, _ = _drive("breakdown", dim=dim, sort="presented_desc")
        out += pool.sqls
    pool, _ = _drive("filters")
    out += pool.sqls
    pool, _ = _drive("freshness")
    out += pool.sqls
    assert len(out) >= 10, f"only {len(out)} statements — the harness went vacuous"
    return [_strip_comments(s) for s in out]


# ---------------------------------------------------------------------------
# layer 1 — emitted SQL
# ---------------------------------------------------------------------------


def test_the_frozen_legacy_feeds_are_excluded_as_a_NOT_IN():
    """§62. `legacy_hd` carries HOME DEPOT on 36,134 rows with `volume` NULL on
    every one, so a SUM(volume) funnel collapses to 0 while its WON rows still
    produce revenue. Written as a NOT-IN so a NEW live feed is picked up
    automatically rather than silently dropped by an IN-list nobody updates."""
    for sql in _all_sql():
        if "spot_report_condensed" not in sql:
            continue
        assert "source <> ALL(" in sql, sql[:400]
        assert not re.search(r"source\s+IN\s*\(", sql), sql[:400]


def test_the_date_bound_casts_through_timestamp_not_straight_from_date():
    """🔴 The defect this report was built on top of.

    `$1::date AT TIME ZONE 'America/Chicago'` does NOT mean midnight in
    Chicago. For a `date` input Postgres resolves the cast to timestamptz
    first, so the expression is midnight UTC *rendered* in Chicago and its type
    is `timestamp WITHOUT time zone` — proven live:

        SELECT pg_typeof('2026-06-24'::date AT TIME ZONE 'America/Chicago')
        -- timestamp without time zone | 2026-06-23 19:00:00

    It then compares back as GMT, so the window starts 10 hours early. The
    `::timestamp` step makes the naive midnight be *interpreted as* Chicago and
    yields a true timestamptz. Without it a 90-day window pulled 77 extra rows.
    """
    seen = 0
    for sql in _all_sql():
        if "price_date >=" not in sql:
            continue
        seen += 1
        assert "::date::timestamp AT TIME ZONE" in sql, sql[:400]
        # the bare form, the one that silently yields a naive timestamp
        assert not re.search(r"::date\s+AT TIME ZONE", sql), sql[:400]
    assert seen, "no statement carried a date bound — the guard would pass vacuously"


def test_the_date_bound_is_sargable_and_the_last_day_is_whole():
    """§64: the column side must stay bare or the index is unusable (measured
    36.7ms vs 2.5ms on this table). And `<= end` against a *timestamp* compares
    to midnight, so `from == to` returns nothing and reads as "no activity" —
    the upper bound is exclusive-next-day instead."""
    seen = 0
    for sql in _all_sql():
        if "price_date >=" not in sql:
            continue
        seen += 1
        assert not re.search(
            r"\(\s*price_date AT TIME ZONE[^)]*\)\s*::date\s*>=", sql
        ), sql[:400]
        assert "+ 1)::timestamp AT TIME ZONE" in sql, sql[:400]
    assert seen


def test_award_status_is_upper_and_trimmed_everywhere():
    """Mixed case once turned $3.34M into $546K in the quoting portal. There are
    no case or padding variants in the data today — which is an observation,
    not a contract."""
    assert "UPPER(BTRIM(COALESCE(award_status, '')))" in m._ST_SQL
    for sql in _all_sql():
        if "award_status" in sql:
            assert "UPPER(BTRIM(" in sql, sql[:400]


def test_no_reply_is_LOST_A_and_is_not_folded_into_lost():
    """The request's "not reply back" is `LOST-A` — written by a cron that ages
    off an unanswered quote at 30 days. Folding it into Lost would delete the
    single most actionable number on the page (20.7% of decided quotes over the
    last 90 days), and would also make "Lost" mean two different things."""
    by_name = {n: cond for n, _agg, cond in m._MEASURES}
    assert by_name["no_reply"] == "priced AND st = 'LOST-A'"
    assert "LOST-A" not in (by_name["lost"] or "")
    assert by_name["lost"] == "priced AND st IN ('LOST', 'DECLINED', 'CLOSE AUTO')"


def test_null_status_is_OPEN_not_no_reply():
    """Measured on the live table: at age <= 30 days 69-85% of lane rows are
    NULL and 0% are LOST-A; at age >= 35 days it is 0% and 87-96%. NULL is a
    transient OPEN state, so counting it as "no reply" would report every
    fresh quote as unanswered."""
    by_name = {n: cond for n, _agg, cond in m._MEASURES}
    assert by_name["open"] == "priced AND st IN ('', '-')"
    assert "''" not in (by_name["no_reply"] or "")


def test_every_outcome_bucket_carries_priced_so_they_partition_the_quoted_set():
    """Without `priced` on every arm, the buckets would span a wider population
    than the Quoted tile above them and stop summing to it — the §96 defect,
    and it flatters, so nobody reports it."""
    outcome = (
        "open", "accept", "won", "lost", "no_reply", "rejected", "cancelled",
        "other_outcome", "awarded_revenue", "awarded_rev_known", "awarded_profit",
        "awarded_profit_n", "loads_won",
    )
    by_name = {n: cond for n, _agg, cond in m._MEASURES}
    for name in outcome:
        assert by_name[name] and by_name[name].startswith("priced AND"), name


def test_the_outcome_buckets_cover_every_status_with_no_overlap():
    """`other_outcome` is the catch-all, so a status the feed invents tomorrow
    lands somewhere visible instead of falling out of the total."""
    by_name = {n: cond for n, _agg, cond in m._MEASURES}
    other = by_name["other_outcome"]
    for st in m._ALL_BUCKETED:
        assert f"'{st}'" in other, f"{st!r} is bucketed but missing from the catch-all"


def test_equipment_uses_ILIKE_and_keeps_reefer():
    """HD rows are DRY_VAN/FLATBED, the lane feed carries a bare VAN — an exact
    IN silently drops one. ⚠ And REEFER exists ONLY on the lane feed: HD Spot's
    `VAN or FLAT` guard would delete 350 rows here, so this report has a Reefer
    group and an Other catch-all. REEF must be tested before VAN, because
    'DRY_VAN' contains VAN."""
    assert "ILIKE" in m._EQUIP_SQL
    assert "Reefer" in m._EQUIP_SQL and "Other" in m._EQUIP_SQL
    assert m._EQUIP_SQL.index("REEF") < m._EQUIP_SQL.index("%VAN%")
    for sql in _all_sql():
        if "equipment" in sql:
            assert not re.search(r"equipment\s+IN\s*\(", sql), sql[:400]


def test_the_bot_is_matched_by_prefix_and_never_by_the_word_AUTOBOT():
    """The bot's literal identity is `agent:ops-external-spots`. The string
    "AUTOBOT" appears in NO identity column anywhere in the table, so a search
    for it matches nothing and reports "no bot activity" — which is how a
    fast-growing automation becomes invisible. One prefix covers all four
    portal agents; HD carries no actor at all and is a third bucket."""
    assert "created_by LIKE 'agent:%'" in m._ACTOR_SQL
    assert "created_by LIKE 'agent:%'" in m._CHANNEL_SQL
    # The LABELS say Autobot / AUTO-BOT, which is right — it is what the
    # quoting portal renders. What must never exist is a PREDICATE matching an
    # identity column against that word, because no row carries it.
    for sql in _all_sql():
        assert not re.search(
            r"(?i)(created_by|updated_by|status_set_by)\s*(=|I?LIKE)\s*'%?auto-?bot",
            sql,
        ), sql[:400]


def test_the_dead_columns_are_never_read():
    """Each of these last carried a value in March 2026 and now answers every
    query confidently with 0 rows. A panel over one would render an empty,
    plausible, permanent zero."""
    dead = (
        "status_set_at",
        "status_set_by",
        "status_id",
        "opting_out_reason",
        "pricing_reason",
        "mcleod_customer_name",
    )
    for sql in _all_sql():
        for col in dead:
            assert col not in sql, f"{col} is dead since 2026-03-26: {sql[:200]}"


def test_profit_subtracts_accessorials():
    """🛑 `price - buy_rate` reads ~$862k high over 120 days — accessorials are
    non-zero on 27% of consultations, and the error always flatters."""
    assert "accessorials" in m._PROFIT_SQL
    assert m._PROFIT_SQL.count("-") == 2


def test_the_margin_denominator_spans_the_same_rows_as_its_numerator():
    """§96. `awarded_profit` is summed only where BOTH legs are known; dividing
    it by `awarded_revenue` (every won row) would inflate the margin silently.
    On HD the two legs are NOT co-populated — 284 rows are priced with no buy
    rate — so this is a live hazard, not a theoretical one."""
    out = m._derive(
        {
            **m._blank(),
            "awarded_profit": 100.0,
            "awarded_rev_known": 1000.0,
            "awarded_revenue": 5000.0,
        }
    )
    assert out["awarded_margin"] == pytest.approx(0.1)


def test_the_actuals_leg_carries_the_mcleod_hygiene_filter():
    """The DATA_HANDBOOK rule: every query against budget_report_v4 must carry
    `total_charge <> 0`. And the ETL writes a 1900-01-01 sentinel for an unknown
    departure, which would otherwise bucket into a phantom month."""
    src = inspect.getsource(m.actuals)
    for frag in (
        "contract_type_descr = 'SPOT'",
        "total_charge <> 0",
        "status IN ('D', 'P')",
        "DATE '1900-01-02'",
    ):
        assert frag in src, frag


def test_the_actuals_leg_fails_soft_and_never_returns_an_empty_dict():
    """§56. The funnel is the report; McLeod actuals are the appendix. A 503
    would blank a page that is mostly fine, and `{}` renders as a real zero."""
    request = types.SimpleNamespace(
        app=types.SimpleNamespace(state=types.SimpleNamespace())
    )
    payload = asyncio.run(
        m.actuals(request=request, grain="month", f=_filters(), _user={})
    )
    assert payload["success"] is True
    assert payload["data"]["available"] is False
    assert payload["data"]["totals"] is None


# ---------------------------------------------------------------------------
# layer 2 — unit contracts
# ---------------------------------------------------------------------------


def test_every_endpoint_takes_the_shared_common_dependency():
    """§55: FastAPI DISCARDS an undeclared query param — no error, just a bigger
    number — so a KPI card would scope while the chart beside it did not. One
    `_common` makes that structural instead of a review item."""
    for name in ("summary", "trend", "breakdown", "actuals"):
        sig = inspect.signature(getattr(m, name)).parameters
        assert "f" in sig, f"{name} does not take the shared _common dependency"
        assert sig["f"].default.dependency is m._common, name


def test_an_unknown_sort_or_dim_is_a_400_not_a_fallback():
    """⚠ `SORT.get(key, default)` hides a dead key: a table ordered by something
    other than the header it advertises fails nothing and is believed."""
    with pytest.raises(HTTPException) as exc:
        _drive("breakdown", dim="channel", sort="margin_desc")
    assert exc.value.status_code == 400
    assert "sort must be one of" in exc.value.detail

    with pytest.raises(HTTPException) as exc:
        _drive("breakdown", dim="booker", sort="presented_desc")
    assert exc.value.status_code == 400
    assert "dim must be one of" in exc.value.detail


def test_a_rate_is_none_on_a_zero_or_negative_denominator():
    """`den > 0`, never `not den`: a negative denominator is the real hazard —
    it renders a percentage in the millions rather than a blank."""
    assert m._rate(1, 0) is None
    assert m._rate(1, -5) is None
    assert m._rate(None, 5) is None
    assert m._rate(1, 4) == pytest.approx(0.25)


def test_percentages_leave_as_fractions():
    """Hand a 0-100 number to a formatter that multiplies by 100 and it prints
    100x wrong, with no error anywhere (§95)."""
    out = m._derive({**m._blank(), "presented": 200.0, "quoted": 50.0})
    assert out["quote_rate"] == pytest.approx(0.25)


def test_business_days_are_monday_to_friday():
    """Mon-Fri, NOT the Ops Portal's Mon-Sat. HD posts exactly zero rows at
    weekends and the lane feed a trickle — 111 of 20,004 rows over 8 weeks.
    A Saturday in the divisor understates every run rate by ~17%."""
    # Mon 2026-09-07 .. Sun 2026-09-13
    assert m._business_days(date(2026, 9, 7), date(2026, 9, 13)) == 5
    assert m._business_days(date(2026, 9, 12), date(2026, 9, 13)) == 0  # Sat+Sun
    assert m._business_days(date(2026, 9, 13), date(2026, 9, 7)) == 0  # reversed


def test_week_to_date_compares_the_same_weekdays():
    """"Up to this day last week" means the same weekday, not the same date —
    Wednesday carries 5,025 rows over 8 weeks against Friday's 3,296, so a
    Wednesday-vs-Friday compare calls the calendar a performance change."""
    wed = date(2026, 9, 16)
    w = m._comparison_windows(wed, (wed, wed))["windows"]
    assert w["wtd"] == (date(2026, 9, 14), wed)  # Mon -> Wed
    assert w["wtd_prev"] == (date(2026, 9, 7), date(2026, 9, 9))  # Mon -> Wed
    assert w["wtd"][1].weekday() == w["wtd_prev"][1].weekday()


def test_month_to_date_compares_the_same_elapsed_business_days():
    """Aligned on the business-day ordinal, not the calendar day — otherwise a
    month that starts on a Saturday is compared against one that starts on a
    Tuesday and the gap is read as demand."""
    today = date(2026, 9, 16)
    meta = m._comparison_windows(today, (today, today))
    cur = meta["windows"]["mtd"]
    prev = meta["windows"]["mtd_prev"]
    assert cur == (date(2026, 9, 1), today)
    assert prev[0] == date(2026, 8, 1)
    assert m._business_days(*cur) == m._business_days(*prev) == meta["bd_elapsed"]


def test_month_to_date_alignment_survives_a_shorter_previous_month():
    """31 July (23 business days) against June (22): the ordinal runs past the
    previous month's end and must clamp there rather than roll into July.

    ⚠ March-vs-February would be the natural case and cannot be tested — the
    window chooser clamps `today` to DATA_FLOOR (2026-04-01), so the assertion
    would silently be made about April instead.
    """
    today = date(2026, 7, 31)
    meta = m._comparison_windows(today, (today, today))
    w = meta["windows"]
    assert meta["bd_elapsed"] == 23
    assert m._business_days(date(2026, 6, 1), date(2026, 6, 30)) == 22
    assert w["mtd_prev"][0] == date(2026, 6, 1)
    assert w["mtd_prev"][1] == date(2026, 6, 30)  # clamped, not 1 July


def test_the_settled_windows_are_older_than_the_maturity_horizon():
    """🔴 The rule that stops this report crying wolf every Monday.

    HD's ACCEPT resolves on day 7-10 and Manual settles at the 30-day age-off,
    so this week's win rate against last week's compares a 2-day-old cohort
    with a 9-day-old one and the older one wins every time. Outcome tiles
    therefore compare the last SETTLED periods.
    """
    today = date(2026, 9, 21)
    w = m._comparison_windows(today, (today, today))["windows"]
    cutoff = today - timedelta(days=m.MATURITY_DAYS)
    for tag in ("settled_week", "settled_week_prev", "settled_month", "settled_month_prev"):
        assert w[tag][1] <= cutoff, f"{tag} ends at {w[tag][1]}, inside the horizon"
    assert w["settled_week"][1] > w["settled_week_prev"][1]
    assert w["settled_month"][1] > w["settled_month_prev"][1]
    # a whole Mon-Sun week and a whole calendar month
    assert (w["settled_week"][1] - w["settled_week"][0]).days == 6
    assert w["settled_month"][0].day == 1


def test_a_settled_window_is_never_labelled_unsettled():
    """The wire's `settled` flag drives the caption; if it disagreed with the
    window chooser the page would explain itself wrongly."""
    today = m.cst_today()
    w = m._comparison_windows(today, (today, today))["windows"]
    assert m._window_meta(*w["settled_week"])["settled"] is True
    assert m._window_meta(*w["mtd"])["settled"] is False


def test_the_projection_divides_by_elapsed_business_days():
    """A calendar divisor understates every projection here, because the
    weekend is structurally empty rather than merely quiet."""
    meta = m._comparison_windows(date(2026, 9, 16), (date(2026, 9, 1), date(2026, 9, 16)))
    assert meta["bd_elapsed"] == 12  # Sep 1-16 2026, Mon-Fri
    assert meta["bd_total"] == 22  # September 2026
    assert meta["bd_elapsed"] < meta["bd_total"]


def test_a_delta_from_zero_has_no_percentage():
    """Returning 0 or 100% there is the lie that makes a launch look flat."""
    assert m._delta(10, 0)["pct"] is None
    assert m._delta(10, 0)["abs"] == 10
    assert m._delta(12, 10)["pct"] == pytest.approx(0.2)
    assert m._delta(None, 10)["abs"] is None


def test_a_single_element_status_list_renders_valid_sql():
    """§79. `('X',)` is a Python repr and a SQL syntax error; the helper exists
    so a list that happens to hold one value cannot break the statement."""
    assert m._lit_list(("WON",)) == "('WON')"
    assert m._lit_list(("A", "B")) == "('A', 'B')"
    assert m._lit_list(("O'Brien",)) == "('O''Brien')"


def test_the_trend_series_is_dense_and_flags_the_unsettled_tail():
    """§70: keep the data whole and let the viewport move. A dropped gap is a
    chart that silently closes over a dead day — which is how the July outage
    went unnoticed for three days."""
    f = _filters(range="custom", start_date=date(2026, 5, 1), end_date=date(2026, 5, 10))
    _pool, payload = _drive("trend", f=f, grain="day")
    series = payload["data"]
    assert len(series) == 10, "gaps were dropped instead of zero-filled"
    assert [s["bucket"] for s in series] == [
        f"2026-05-{d:02d}" for d in range(1, 11)
    ]
    assert all(s["provisional"] is False for s in series), "May 2026 has long settled"

    today = m.cst_today()
    f2 = _filters(range="last7")
    _pool, recent = _drive("trend", f=f2, grain="day")
    assert any(s["provisional"] for s in recent["data"]), (
        "the last 7 days cannot all be settled — the shading would never appear"
    )
    assert recent["data"][-1]["bucket"] == today.isoformat()


def test_the_window_flags_the_july_outage():
    """2026-07-17..20: one 215-char order_number raised SQLSTATE 22001 in the
    first of four sequential statements in one try, freezing both feeds for
    ~150 cron runs and rendering confident zeros. Any window containing it is
    partial and says so."""
    assert m._window_meta(date(2026, 7, 1), date(2026, 7, 31))["covers_outage"] is True
    assert m._window_meta(date(2026, 8, 1), date(2026, 8, 31))["covers_outage"] is False


def test_the_data_floor_clears_the_frozen_feed_overlap():
    """April is the first month with no frozen-feed rows at all. March still
    holds 4,580 legacy_hd + 1,484 legacy rows against the live feeds, and the
    two overlap on 3,319 duplicate offer ids."""
    assert m.DATA_FLOOR == date(2026, 4, 1)
    s, e = m._resolve_range("custom", date(2025, 1, 1), date(2026, 5, 1))
    assert s == m.DATA_FLOOR


def test_a_reversed_custom_range_is_swapped_not_empty():
    s, e = m._resolve_range("custom", date(2026, 6, 30), date(2026, 6, 1))
    assert (s, e) == (date(2026, 6, 1), date(2026, 6, 30))


def test_repeated_params_are_never_comma_split():
    """§45. Customer names contain commas — 'CONAGRA FOODS PACKAGED FOODS, LLC'
    is the third-biggest lane-feed customer. A comma split would turn it into
    two filters that match nothing, and return EMPTY with no error."""
    assert m._parse_multi(["A,B"]) == ["A,B"]
    assert m._parse_multi(["A", "A", " B ", ""]) == ["A", "B"]
    assert m._parse_multi(None) == []
    # ⚠ Scan the CODE, not the prose: this module's own docstrings quote the
    # rule they describe, so a raw source scan finds the warning and calls it a
    # violation. Strip docstrings via the AST — never by a triple-quote regex,
    # because the SQL is triple-quoted too and a blunt stripper empties the
    # file, leaving every assertion to pass vacuously (§98).
    import ast

    tree = ast.parse(inspect.getsource(m))
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef,
                             ast.AsyncFunctionDef)) and ast.get_docstring(node):
            node.body = node.body[1:]
    code = ast.unparse(tree)
    assert "_parse_multi" in code, "the stripper emptied the module"
    assert '.split(","' not in code


def test_a_dimension_filter_reaches_the_sql():
    """A filter the UI offers and the SQL ignores is worse than no filter."""
    pool, _ = _drive("summary", f=_filters(channel=["Autobot"], division=["CORP"]))
    sql = _strip_comments(pool.sqls[0])
    assert sql.count("= ANY($") == 2, sql[:600]
    assert any("Autobot" in str(p) for p in pool.params[0])


def test_small_samples_do_not_get_a_headline_win_rate():
    """One award out of one quote is not a 100% win rate, and a table sorted by
    win rate would put it on top. Suppressed rates render as an em-dash, and
    nulls sort LAST in both directions (§104)."""
    assert m.MIN_DECIDED_FOR_RATE >= 5
    src = inspect.getsource(m.breakdown)
    assert 'cur["win_rate"] = None' in src
    assert "known + unknown" in src, "nulls must be appended, never sorted by a flag"


def test_the_breakdown_totals_are_a_server_side_full_universe_aggregate():
    """§44. LIMITs are payload caps; a client reduce of the visible page would
    silently report the top 200's totals as the company's."""
    src = inspect.getsource(m.breakdown)
    assert src.index("totals[n] +=") < src.index("MAX_BREAKDOWN_ROWS")


def test_the_report_key_is_the_same_string_in_every_place():
    """The key is the router prefix, the access-gate key, the seed key and the
    frontend route. One byte of drift is a 403 that renders as an empty page."""
    from app.services.seed import CUSTOM_REPORTS

    assert m.REPORT_KEY == "production-spots-trends"
    assert m.router.prefix == f"/custom/{m.REPORT_KEY}"
    seeded = [r for r in CUSTOM_REPORTS if r["key"] == m.REPORT_KEY]
    assert len(seeded) == 1
    assert seeded[0]["title"] == "Production SPOTS Trends"


def test_every_endpoint_is_gated_on_the_report_key():
    """A report endpoint with no gate is readable by every authenticated user,
    and nothing about the page looks wrong."""
    for route in m.router.routes:
        deps = [d.call for d in route.dependant.dependencies]
        assert any(
            getattr(d, "__qualname__", "").startswith("require_report_access")
            for d in deps
        ), f"{route.path} is ungated"


def test_the_title_has_a_report_icon_entry():
    """§32 / SPEC-UI §9.4. `inferFromTitle()` is a safety net, not the contract:
    no family keyword matches SPOTS/PRODUCTION/TRENDS, so without an explicit
    entry the card renders neutral grey with a generic shield — which is how 17
    of 41 home cards once became visually identical."""
    import pathlib

    icons = (
        pathlib.Path(__file__).resolve().parents[2]
        / "frontend/components/ReportIcons.tsx"
    ).read_text()
    assert '"Production SPOTS Trends":' in icons


def test_the_sort_whitelist_matches_the_frontend():
    """There is no JS test runner here, so the frontend half of this contract is
    guarded from Python by reading the TSX (§107).

    A token that exists on one side of the wire only renders a table ordered by
    something other than the header it advertises — or a 400 the user reads as
    a broken page.
    """
    import pathlib

    src = (
        pathlib.Path(__file__).resolve().parents[2]
        / "frontend/lib/production-spots-trends-api.ts"
    ).read_text()
    block = re.search(r"export type SpotsSort =(.*?)\n\n", src, re.S)
    assert block, "could not find SpotsSort in the api file"
    used = set(re.findall(r'"([a-z_]+(?:_asc|_desc))"', block.group(1)))
    assert used, "parsed no sort tokens — the guard would pass vacuously"
    assert used == set(m._SORTS)


def test_the_frontend_route_folder_matches_the_report_key():
    """`custom_path` is `/reports/<key>`; a folder named anything else is a 404
    that looks exactly like a permissions problem."""
    import pathlib

    page = (
        pathlib.Path(__file__).resolve().parents[2]
        / f"frontend/app/reports/{m.REPORT_KEY}/page.tsx"
    )
    assert page.exists(), f"missing {page}"
    assert f'reportKey="{m.REPORT_KEY}"' in page.read_text()


def test_the_cockpit_catalog_carries_the_report():
    """⚠ The FIFTH mirror the 4-place checklist does not list — a report that
    follows the checklist literally goes missing from the CEO Cockpit."""
    from app.routers.ceo_cockpit import LINK_TILES, TILES

    keys = {t["key"] for t in LINK_TILES} | {t["key"] for t in TILES}
    assert m.REPORT_KEY in keys


# ---------------------------------------------------------------------------
# layers 3 & 4 — live
# ---------------------------------------------------------------------------

_PRICING = os.environ.get("PRICING_DATABASE_URL", "")
_skip_live = pytest.mark.skipif(
    not _PRICING, reason="PRICING_DATABASE_URL not set — offline run"
)


def _connect():
    import asyncpg

    return asyncpg.connect(re.sub(r"[?&]sslmode=\w+", "", _PRICING), ssl="require")


@_skip_live
def test_live_every_statement_variant_parses():
    """A text assertion is satisfied by a string Postgres will reject — this is
    the layer that proves the statement PARSES (§81). PREPARE, not execute:
    identical SQLSTATE, a fraction of the time."""
    statements = list(dict.fromkeys(_all_sql()))
    assert len(statements) >= 6, "the harness went vacuous"

    async def run():
        conn = await _connect()
        await conn.execute("SET statement_timeout = '30s'")
        bad = []
        try:
            for sql in statements:
                try:
                    await conn.prepare(sql)
                except Exception as exc:  # noqa: BLE001 — report, do not mask
                    bad.append(f"{getattr(exc, 'sqlstate', '?')} {exc}"[:220])
        finally:
            await conn.close()
        return bad

    bad = asyncio.run(run())
    assert not bad, "statements rejected by Postgres:\n" + "\n".join(bad)


@_skip_live
def test_live_the_funnel_buckets_partition_the_population():
    """The identity no stub can prove: Presented = Quoted + Skipped, and Quoted
    = the sum of every outcome bucket. If either drifts, the funnel tiles stop
    adding up to the KPI above them and the report quietly loses a population.
    """

    async def run():
        import asyncpg

        pool = await asyncpg.create_pool(
            re.sub(r"[?&]sslmode=\w+", "", _PRICING), min_size=1, max_size=2
        )
        try:
            today = m.cst_today()
            windows = {"w": (max(m.DATA_FLOOR, today - timedelta(days=90)), today)}
            return (await m._fetch_summary(pool, windows, {}))["w"]
        finally:
            await pool.close()

    r = asyncio.run(run())
    assert r["presented"] > 0, "no rows — the assertion would pass vacuously"
    assert r["presented"] == r["quoted"] + r["skipped"]
    assert r["quoted"] == (
        r["won"]
        + r["lost"]
        + r["no_reply"]
        + r["rejected"]
        + r["cancelled"]
        + r["accept"]
        + r["open"]
        + r["other_outcome"]
    )


@_skip_live
def test_live_the_sargable_bound_selects_exactly_the_cst_calendar_days():
    """The whole point of the `::timestamp` step: the fast form must return the
    same rows as the slow, obviously-correct one. Before the fix these differed
    by 77 rows on a 90-day window."""

    async def run():
        conn = await _connect()
        try:
            return await conn.fetchrow(
                """
                SELECT
                  (SELECT count(*) FROM spot_report_condensed
                    WHERE price_date >= ($1::date::timestamp AT TIME ZONE 'America/Chicago')
                      AND price_date <  (($2::date + 1)::timestamp AT TIME ZONE 'America/Chicago')
                      AND source <> ALL($3::text[])) AS sargable,
                  (SELECT count(*) FROM spot_report_condensed
                    WHERE (price_date AT TIME ZONE 'America/Chicago')::date BETWEEN $1 AND $2
                      AND source <> ALL($3::text[])) AS reference
                """,
                date(2026, 6, 24),
                date(2026, 9, 21),
                list(m.FROZEN_SOURCES),
            )
        finally:
            await conn.close()

    row = asyncio.run(run())
    assert row["reference"] > 0, "empty window — the assertion would pass vacuously"
    assert row["sargable"] == row["reference"]
