"""Customer Lifespan — Iris's deck 2026-11-03: Date / Teams / Customer + the Summary tab.

Operator decision 2026-11-04: the Date filter filters EVERYTHING. A customer with
no load in the range is not in the report; loads, revenue, profit and lifespans
count only inside it. Facts about the customer stay true: "new" and the cohort
year come from the REAL first load, or every customer would read as new.
"""
from __future__ import annotations

from datetime import date

import pytest
from fastapi import HTTPException

from app.routers import customer_lifespan as rt
from app.services import customer_lifespan_board as board
from app.services import customer_lifespan_core as core
from app.services import customer_lifespan_scope as sc
from app.services import customer_lifespan_trends as tr

AS_OF = date(2026, 6, 30)
USER = {"sub": "t", "email": "t@local", "roles": ["admin"]}


def _m(cid, month, first, last, division="CORP", loads=1, revenue=1000.0, margin=100.0):
    return {"customer_id": cid, "month": month, "division": division, "loads": loads,
            "revenue": revenue, "margin": margin, "first_ship": first, "last_ship": last,
            "name": f"Cust {cid}"}


ROWS = [
    # OLD: since 2020, silent until 2026-05, back → recovered in 2026, active
    _m("OLD", date(2020, 3, 1), date(2020, 3, 2), date(2020, 3, 20), loads=2),
    _m("OLD", date(2026, 5, 1), date(2026, 5, 10), date(2026, 5, 10)),
    _m("OLD", date(2026, 6, 1), date(2026, 6, 25), date(2026, 6, 25)),
    # NEWBIE: first load in the period, at risk (61 days quiet)
    _m("NEWBIE", date(2026, 4, 1), date(2026, 4, 30), date(2026, 4, 30)),
    # GONE: shipped in the period, then silent > 90 → lost in the period
    _m("GONE", date(2025, 12, 1), date(2025, 12, 5), date(2025, 12, 20), revenue=500.0, margin=50.0),
    # ANCIENT: no load in the period at all
    _m("ANCIENT", date(2018, 5, 1), date(2018, 5, 5), date(2018, 5, 5)),
]


def _clip(start, end):
    """What ``CUSTOMER_MONTHS_RANGE_SQL`` returns for the fixture (whole-row clip)."""
    return [r for r in ROWS if r["first_ship"] >= start and r["last_ship"] <= end]


def _scope(start, end, window=90, division="all"):
    return sc.scope_customers(core.merge_rows(_clip(date(2000, 1, 1), end), division),
                              core.merge_rows(_clip(start, end), division), end, window)


def _by_id(cs):
    return {c.customer_id: c for c in cs}


# ------------------------------------------------------------------ period


@pytest.mark.parametrize("key,start,end", [
    ("last_365", date(2025, 7, 1), AS_OF),
    ("mtd", date(2026, 6, 1), AS_OF),
    ("last_month", date(2026, 5, 1), date(2026, 5, 31)),
    ("ytd", date(2026, 1, 1), AS_OF),
    ("all", sc.ALL_START, AS_OF),
])
def test_named_ranges_anchor_on_the_data_as_of(key, start, end):
    p = sc.resolve_period(key, None, None, AS_OF)
    assert (p.start, p.end, p.key) == (start, end, key)


def test_custom_range_is_clipped_to_the_data_and_validated():
    p = sc.resolve_period("custom", date(2026, 1, 1), date(2030, 1, 1), AS_OF)
    assert (p.start, p.end) == (date(2026, 1, 1), AS_OF)
    for bad in [("custom", None, AS_OF), ("custom", AS_OF, date(2020, 1, 1)), ("forever", None, None)]:
        with pytest.raises(ValueError):
            sc.resolve_period(*bad, AS_OF)


def test_same_period_last_year_survives_a_leap_day():
    p = sc.resolve_period("custom", date(2024, 2, 29), date(2024, 3, 1), date(2024, 12, 1))
    assert (sc.shift_year(p).start, sc.shift_year(p).end) == (date(2023, 2, 28), date(2023, 3, 1))
    assert sc.shift_year(sc.resolve_period("all", None, None, AS_OF)) is None


# ------------------------------------------------------------------ the population


def test_a_customer_with_no_load_in_the_range_is_not_in_the_report():
    cs = _by_id(_scope(date(2025, 7, 1), AS_OF))
    assert set(cs) == {"OLD", "NEWBIE", "GONE"}


def test_counts_stay_inside_the_range_but_first_load_stays_true():
    old = _by_id(_scope(date(2025, 7, 1), AS_OF))["OLD"]
    assert old.loads == 2 and old.revenue == 2000.0 and old.active_months == 2
    assert old.first_ship == date(2020, 3, 2) and old.cohort_year == 2020
    assert old.lifespan_months == 1                                    # May → Jun, cut at the range
    assert old.reactivations == 1 and len(old.history) == 3


def test_status_is_as_of_the_range_end():
    cs = _by_id(_scope(date(2026, 4, 1), date(2026, 5, 31)))
    assert set(cs) == {"NEWBIE", "OLD"} and cs["NEWBIE"].status == "at_risk"
    assert cs["NEWBIE"].days_since_last == 31


def test_new_means_the_true_first_load_not_the_first_load_in_range():
    cs = _scope(date(2025, 7, 1), AS_OF)
    s = core.summary(cs, AS_OF, 90, date(2025, 7, 1), customers_total=4)
    assert s["new_period"] == 2                                        # NEWBIE, GONE — never OLD
    assert s["customers_total"] == 4


def test_all_time_reproduces_the_unfiltered_report():
    p = sc.resolve_period("all", None, None, AS_OF)
    scoped = {c.customer_id: c for c in _scope(p.start, AS_OF)}
    plain = {c.customer_id: c for c in core.build_customers(core.merge_rows(ROWS, "all"), AS_OF, 90)}
    assert set(scoped) == set(plain)
    for cid, c in plain.items():
        s = scoped[cid]
        assert (s.first_ship, s.last_ship, s.status, s.lifespan_months, s.loads, s.revenue, s.reactivations) == (
            c.first_ship, c.last_ship, c.status, c.lifespan_months, c.loads, c.revenue, c.reactivations)


def test_summary_period_flows_match_the_flow_chart_and_money_is_in_range():
    start = date(2025, 7, 1)
    cs = _scope(start, AS_OF)
    s = core.summary(cs, AS_OF, 90, start)
    rows = tr.trend(cs, AS_OF, 90, "month", start)
    assert s["lost_period"] == sum(r["lost"] for r in rows) == 1
    assert s["reactivated_period"] == sum(r["reactivated"] for r in rows) == 1
    assert s["new_period"] == sum(r["new"] for r in rows) == 2
    assert s["revenue_period"] == sum(r["revenue"] for r in rows) == 3500.0
    assert s["margin_period"] == 350.0
    assert (s["base"], s["active"], s["at_risk"], s["lost"]) == (2, 1, 1, 1)


def test_a_loss_before_the_range_is_not_counted_but_the_return_is():
    start = date(2025, 7, 1)
    old = _by_id(_scope(start, AS_OF))["OLD"]
    lost, back = core.flow_events(old, 90, start)
    assert lost == [] and back == [date(2026, 5, 10)]


def test_trend_periods_are_clipped_to_the_range():
    start = date(2025, 7, 1)
    rows = tr.trend(_scope(start, AS_OF), AS_OF, 90, "month", start)
    assert rows[0]["period"] == "2025-12" and rows[-1]["period"] == "2026-06"


def test_cohorts_keep_the_true_year_and_only_selected_years():
    start = date(2025, 7, 1)
    rows = {r["cohort"]: r for r in tr.cohorts(_scope(start, AS_OF), AS_OF, start)}
    assert set(rows) == {2020, 2025, 2026}
    assert [c["year"] for c in rows[2020]["retention"]] == [2025, 2026]
    assert rows[2020]["retention"][1]["customers"] == 1 and rows[2020]["retention"][0]["customers"] == 0
    assert rows[2026]["at_risk_now"] == 1 and rows[2020]["active_now"] == 1


# ------------------------------------------------------------------ click-through lists


@pytest.mark.parametrize("grain", ["month", "quarter", "year"])
def test_every_bar_equals_its_list(grain):
    start = sc.ALL_START
    cs = _scope(start, AS_OF, window=60)
    for row in tr.trend(cs, AS_OF, 60, grain, start):
        members = tr.flow_members(cs, 60, grain, row["period"], start)
        assert len(members["new"]) == row["new"], row["period"]
        assert len(members["reactivated"]) == row["reactivated"], row["period"]
        assert len(members["lost"]) == row["lost"], row["period"]


def test_flow_members_name_the_customer_and_the_date():
    start = date(2025, 7, 1)
    m = tr.flow_members(_scope(start, AS_OF), 90, "quarter", "2026 Q2", start)
    assert [(e["customer_id"], e["date"]) for e in m["reactivated"]] == [("OLD", date(2026, 5, 10))]
    assert [e["customer_id"] for e in m["new"]] == ["NEWBIE"] and m["lost"] == []
    assert tr.flow_members(_scope(start, AS_OF), 90, "quarter", "1999 Q1", start)["new"] == []


def test_every_customer_row_names_its_lifespan_bucket():
    cs = _scope(sc.ALL_START, AS_OF)
    buckets = {b["bucket"]: b for b in tr.lifespan(cs, AS_OF)["buckets"]}
    for c in cs:
        row = core.customer_row(c, AS_OF)
        assert row["lifespan_bucket"] in buckets
    for label, b in buckets.items():
        rows = [core.customer_row(c, AS_OF) for c in cs]
        assert sum(1 for r in rows if r["lifespan_bucket"] == label) == b["active"] + b["at_risk"] + b["lost"]


# ------------------------------------------------------------------ teams + Pipedrive


def test_team_chip_keeps_real_teams_and_never_hides_the_rest():
    assert sc.team_chip("TEAM3") == "TEAM3" and sc.team_chip("TEAM-OCA") == "TEAM-OCA"
    assert sc.team_chip("BD2") == "BD2"
    assert sc.team_chip("JMCGHEE") == sc.OTHER_TEAM and sc.team_chip("N/A") == sc.OTHER_TEAM
    assert sc.team_chip("") == sc.OTHER_TEAM
    assert sc.team_chip(None) == sc.NO_TEAM


def test_every_chip_selected_keeps_every_customer():
    a = sc.Assignments({"OLD": "TEAM2", "GONE": "JMCGHEE"}, {})
    chips = sc.team_chips(ROWS, "all", a)
    assert chips == ["TEAM2", sc.OTHER_TEAM, sc.NO_TEAM]
    kept = sc.filter_rows(ROWS, a, chips, None)
    assert {r["customer_id"] for r in kept} == {r["customer_id"] for r in ROWS}
    assert {r["customer_id"] for r in sc.filter_rows(ROWS, a, ["TEAM2"], None)} == {"OLD"}
    assert sc.filter_rows(ROWS, a, [""], None) == []                   # every chip off = nobody
    assert {r["customer_id"] for r in sc.filter_rows(ROWS, a, None, "gone")} == {"GONE"}


def test_active_shows_the_team_lost_shows_the_sales_exec():
    a = sc.Assignments({"A": "TEAM1"}, {"A": "Iris Moreno"})
    assert a.of("A", "active") == {"team": "TEAM1", "assigned_to": "TEAM1", "pending_assignment": False}
    assert a.of("A", "at_risk")["assigned_to"] == "TEAM1"
    assert a.of("A", "lost") == {"team": "TEAM1", "assigned_to": "Iris Moreno", "pending_assignment": False}


def test_lost_without_a_deal_is_pending_to_assign():
    a = sc.Assignments({"A": "TEAM1"}, {})
    assert a.of("A", "lost") == {"team": "TEAM1", "assigned_to": sc.PENDING_LABEL, "pending_assignment": True}
    assert sc.PENDING_LABEL == "PENDING TO ASSIGN"


def test_a_pipedrive_that_never_answered_is_not_pending():
    """Unknown is not "nobody assigned" — 351 false amber rows otherwise."""
    a = sc.Assignments({"A": "TEAM1"}, None)
    assert a.of("A", "lost") == {"team": "TEAM1", "assigned_to": None, "pending_assignment": False}


def test_owner_lookup_ignores_case_and_padding():
    a = sc.Assignments({}, {"BAYERCMO": "Miguel Millan"})
    assert a.of("bayercmo ", "lost")["assigned_to"] == "Miguel Millan"


# ------------------------------------------------------------------ the Summary board


RECENT = [
    {"customer_id": "OLD", "division": "CORP", "loads_30": 1, "loads_base": 24, "margin_90": 100.0},
    {"customer_id": "NEWBIE", "division": "CORP", "loads_30": 0, "loads_base": 1, "margin_90": 100.0},
    {"customer_id": "NEWBIE", "division": "DFW", "loads_30": 0, "loads_base": 0, "margin_90": 25.5},
]


def _board(start=date(2025, 7, 1), prior=None):
    cs = _scope(start, AS_OF)
    a = sc.Assignments({"OLD": "TEAM2", "NEWBIE": "TEAM1"}, {})
    return board.board(cs, prior, board.merge_recent(RECENT, "all"), AS_OF, 90, start, a)


def test_tiles_count_the_same_customers_as_their_tables():
    b = _board()
    assert b["tiles"]["active"]["value"] == 1
    assert b["tiles"]["at_risk"]["value"] == len(b["at_risk"]) == 1
    assert b["tiles"]["first_year"]["value"] == len(b["first_year"]) == 2
    assert b["tiles"]["lost"]["value"] == len(b["lost"]) == 1
    assert b["tiles"]["recovered"]["value"] == len(b["recovered"]) == 1


def test_at_risk_row_has_the_decks_columns():
    (row,) = _board()["at_risk"]
    assert row["customer_id"] == "NEWBIE" and row["assigned_to"] == "TEAM1"
    assert row["age_months"] == 2 and row["days_since_last"] == 61
    assert row["profit_90d"] == 125.5                                  # both divisions, ALL scope


def test_lost_row_has_last_load_and_pending_label():
    (row,) = _board()["lost"]
    assert row["customer_id"] == "GONE" and row["last_ship"] == date(2025, 12, 20)
    assert row["assigned_to"] == sc.PENDING_LABEL and row["pending_assignment"] is True


def test_recovered_row_says_when_and_current_status():
    (row,) = _board()["recovered"]
    assert (row["customer_id"], row["returned_on"], row["status"]) == ("OLD", date(2026, 5, 10), "active")


def test_declining_compares_last_30_days_with_the_prior_monthly_average():
    (row,) = _board()["declining"]
    assert row["customer_id"] == "OLD"
    assert row["avg_monthly_loads"] == 2.0 and row["loads_30d"] == 1
    assert row["change"] == -1.0 and row["change_pct"] == -50.0


def test_declining_skips_lost_rising_tiny_and_too_new_customers():
    cs = _scope(date(2025, 7, 1), AS_OF)
    recent = {"OLD": board.Recent(30, 24, 0.0), "GONE": board.Recent(0, 240, 0.0),
              "NEWBIE": board.Recent(0, 1, 0.0)}
    rows = board.declining(cs, recent, AS_OF, lambda c: {})
    assert rows == []                                                  # OLD rose, GONE lost
    assert board.baseline_days(date(2026, 6, 1), AS_OF) == 0           # first load inside the last 30 days
    assert board.baseline_days(date(2020, 1, 1), AS_OF) == 365


def test_deltas_compare_with_the_prior_year_and_never_divide_by_zero():
    prior = {"active": 2, "at_risk": 0, "first_year": 1, "lost": 1, "recovered": 4}
    t = _board(prior=prior)["tiles"]
    assert t["active"] == {"value": 1, "prior": 2, "delta_pct": -50.0}
    assert t["at_risk"]["delta_pct"] is None
    assert t["first_year"]["delta_pct"] == 100.0
    assert _board()["tiles"]["active"] == {"value": 1, "prior": None, "delta_pct": None}


def test_tile_counts_at_a_past_period_use_only_what_was_known_then():
    end = date(2020, 6, 1)
    start = date(2019, 6, 2)
    t = board.tile_counts(_scope(start, end), end, 90, start)
    assert t == {"active": 0, "at_risk": 1, "first_year": 1, "lost": 0, "recovered": 0}


def test_recent_sql_binds_the_period_end_and_skips_voided():
    assert "$1::date - 395" in board.RECENT_SQL and "NOT voided_in_datalake" in board.RECENT_SQL


# ------------------------------------------------------------------ router


class _Pool:
    """Answers the exported statements; anything else fails the test."""

    def __init__(self, rows=ROWS, teams=(), owners=(), owners_ok=True):
        self.rows, self.teams, self.owners, self.owners_ok, self.sql = rows, teams, owners, owners_ok, []

    async def fetch(self, sql, *p):
        self.sql.append(sql)
        if sql == core.CUSTOMER_MONTHS_SQL:
            return self.rows
        if sql == core.CUSTOMER_MONTHS_RANGE_SQL:
            return [r for r in self.rows if r["first_ship"] >= p[0] and r["last_ship"] <= p[1]]
        if sql == board.RECENT_SQL:
            return RECENT
        if sql == sc.TEAMS_SQL:
            return list(self.teams)
        if sql == sc.OWNERS_SQL:
            return list(self.owners)
        raise AssertionError(f"unexpected SQL: {sql[:60]}")

    async def fetchval(self, sql, *p):
        assert sql == sc.OWNERS_EVER_OK_SQL
        return self.owners_ok


class _Req:
    def __init__(self, pool):
        self.app = type("A", (), {"state": type("S", (), {"pool": pool})()})()


@pytest.fixture(autouse=True)
def _fresh():
    rt.invalidate_cache()
    yield
    rt.invalidate_cache()


F_ALL = rt.Filters(range_key="all")


@pytest.mark.asyncio
async def test_meta_names_the_period_and_the_data_date():
    body = await rt.summary_view(_Req(_Pool()), rt.Division.all, 90, rt.Filters(range_key="last_month"), USER)
    assert body["meta"]["as_of"] == "2026-05-31" and body["meta"]["data_as_of"] == "2026-06-25"
    assert body["meta"]["range"] == "last_month" and body["meta"]["range_label"] == "Last month"


@pytest.mark.asyncio
async def test_bad_range_is_a_422_not_a_500():
    with pytest.raises(HTTPException) as e:
        await rt.summary_view(_Req(_Pool()), rt.Division.all, 90, rt.Filters(range_key="forever"), USER)
    assert e.value.status_code == 422


@pytest.mark.asyncio
async def test_customers_filter_by_team_and_carry_the_assignment():
    pool = _Pool(teams=[{"customer_id": "OLD", "team_id": "TEAM2"}],
                 owners=[{"customer_code": "ANCIENT", "owner_name": "Iris Moreno"}])
    body = await rt.customers_view(_Req(pool), rt.Division.all, 90, F_ALL, USER)
    rows = {r["customer_id"]: r for r in body["data"]}
    assert rows["ANCIENT"]["assigned_to"] == "Iris Moreno"
    assert rows["GONE"]["pending_assignment"] is True
    one = await rt.customers_view(_Req(pool), rt.Division.all, 90,
                                  rt.Filters(range_key="all", teams=("TEAM2",)), USER)
    assert [r["customer_id"] for r in one["data"]] == ["OLD"]


@pytest.mark.asyncio
async def test_all_time_count_ignores_the_dates_but_not_the_teams():
    pool = _Pool(teams=[{"customer_id": "OLD", "team_id": "TEAM2"}])
    wide = await rt.summary_view(_Req(pool), rt.Division.all, 90, rt.Filters(range_key="mtd"), USER)
    assert wide["data"]["customers_total"] == 4
    only = await rt.summary_view(_Req(pool), rt.Division.all, 90,
                                 rt.Filters(range_key="mtd", teams=("TEAM2",)), USER)
    assert only["data"]["customers_total"] == 1


@pytest.mark.asyncio
async def test_unavailable_assignment_tables_fail_soft():
    class _NoTables(_Pool):
        async def fetch(self, sql, *p):
            if sql in (sc.TEAMS_SQL, sc.OWNERS_SQL):
                raise RuntimeError("relation does not exist")
            return await super().fetch(sql, *p)

    body = await rt.customers_view(_Req(_NoTables()), rt.Division.all, 90, F_ALL, USER)
    assert all(r["pending_assignment"] is False for r in body["data"])


@pytest.mark.asyncio
async def test_board_endpoint_compares_with_last_year():
    body = await rt.board_view(_Req(_Pool()), rt.Division.all, 90, rt.Filters(range_key="ytd"), USER)
    assert "tiles" in body["data"] and body["data"]["tiles"]["recovered"]["prior"] == 0
    all_time = await rt.board_view(_Req(_Pool()), rt.Division.all, 90, F_ALL, USER)
    assert all_time["data"]["tiles"]["recovered"]["prior"] is None


@pytest.mark.asyncio
async def test_flow_customers_endpoint_and_filter_options():
    body = await rt.flow_customers_view(_Req(_Pool()), rt.Division.all, 90, "quarter", "2026 Q2",
                                        rt.Filters(range_key="ytd"), USER)
    assert [e["customer_id"] for e in body["data"]["reactivated"]] == ["OLD"]
    with pytest.raises(HTTPException):
        await rt.flow_customers_view(_Req(_Pool()), rt.Division.all, 90, "week", "x", F_ALL, USER)
    opts = await rt.filters_view(_Req(_Pool()), rt.Division.corp, USER)
    assert opts["data"]["teams"] == [sc.NO_TEAM]
    assert {c["customer_id"] for c in opts["data"]["customers"]} == {"OLD", "NEWBIE", "GONE", "ANCIENT"}


def test_range_query_param_is_declared_on_every_section():
    """§ FastAPI drops an undeclared param silently: a section without it ignores the filter."""
    from app.main import app

    for r in app.routes:
        path = getattr(r, "path", "")
        if not path.startswith("/api/custom/customer-lifespan/{division}/") or path.endswith("/filters"):
            continue
        names = {p.alias for p in r.dependant.query_params}
        for dep in r.dependant.dependencies:
            names |= {p.alias for p in dep.query_params}
        assert {"range", "start", "end", "teams", "customer"} <= names, path


# ------------------------------------------------------------------ team + owner jobs


def test_the_team_of_the_latest_load_wins():
    from app.services import customer_lifespan_store as store

    rows = [{"customer_id": "K", "team_id": "TEAM4", "last_ship": date(2023, 1, 1), "orders": 800},
            {"customer_id": "K", "team_id": "TEAM1", "last_ship": date(2026, 1, 1), "orders": 5},
            {"customer_id": "T", "team_id": "TEAM3", "last_ship": date(2026, 2, 2), "orders": 9},
            {"customer_id": "T", "team_id": "TEAM6", "last_ship": date(2026, 2, 2), "orders": 2}]
    assert store.latest_team_records(rows) == [("K", "TEAM1", date(2026, 1, 1)), ("T", "TEAM3", date(2026, 2, 2))]
    assert "TM4" in store.V4_TEAMS_SQL and "TRIM(v4.company_id)" not in store.V4_TEAMS_SQL


def test_owner_is_the_newest_open_deal_by_deal_field_then_org_field():
    from app.services import customer_lifespan_pipedrive as pd

    deals = [
        {"id": 1, "code": "bayercmo ", "org_id": 9, "owner_id": 10, "add_time": "2026-01-01", "title": "old"},
        {"id": 2, "code": "BAYERCMO", "org_id": 9, "owner_id": 11, "add_time": "2026-02-01", "title": "new"},
        {"id": 3, "code": None, "org_id": 7, "owner_id": 10, "add_time": "2026-01-01", "title": "by org"},
        {"id": 4, "code": "", "org_id": 8, "owner_id": 10, "add_time": "2026-01-01", "title": "no code"},
        {"id": 5, "code": "GHOST", "org_id": 8, "owner_id": 99, "add_time": "2026-01-01", "title": "no owner"},
    ]
    recs = pd.owner_records(deals, {7: "PCAATLGA"}, {10: "Iris Moreno", 11: "Miguel Millan"})
    assert recs == [("BAYERCMO", "Miguel Millan", 2, "new"), ("PCAATLGA", "Iris Moreno", 3, "by org")]


class _Tx:
    def __init__(self, hub):
        self.hub = hub

    def transaction(self):
        return self

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def execute(self, sql, *p):
        self.hub.calls.append(sql)

    async def executemany(self, sql, rows):
        self.hub.calls.append(sql)
        self.hub.written = list(rows)


class _WriteHub:
    def __init__(self, stored=0):
        self.calls, self.stored, self.written = [], stored, None

    async def fetchval(self, sql, *p):
        self.calls.append(sql)
        return 7 if "RETURNING id" in sql else self.stored

    async def execute(self, sql, *p):
        self.calls.append(sql)

    def acquire(self):
        return _Tx(self)


class _Client:
    def __init__(self, deals):
        self.deals = deals

    async def read_reactivation_owners(self):
        return self.deals, {}, {10: "Iris Moreno"}


DEAL = {"id": 1, "code": "A", "org_id": None, "owner_id": 10, "add_time": "2026-01-01", "title": "t"}


@pytest.mark.asyncio
async def test_owner_refresh_replaces_in_one_transaction_and_logs():
    from app.services import customer_lifespan_pipedrive as pd
    from app.services import customer_lifespan_store as store

    hub = _WriteHub()
    assert await pd.refresh_deal_owners(hub, _Client([DEAL])) == 1
    assert hub.written == [("A", "Iris Moreno", 1, "t")]
    assert pd.DELETE_OWNERS_SQL in hub.calls and store.LOG_REFRESH_OK_SQL in hub.calls


@pytest.mark.asyncio
async def test_an_empty_read_does_not_blank_the_owner_map_and_is_recorded():
    from app.services import customer_lifespan_pipedrive as pd
    from app.services import customer_lifespan_store as store

    hub = _WriteHub(stored=50)
    with pytest.raises(RuntimeError, match="refusing to empty"):
        await pd.refresh_deal_owners(hub, _Client([]))
    assert pd.DELETE_OWNERS_SQL not in hub.calls and store.LOG_REFRESH_FAILED_SQL in hub.calls


@pytest.mark.asyncio
async def test_a_shrunk_team_read_is_refused():
    from app.services import customer_lifespan_store as store

    class _Gold:
        async def fetch(self, sql, *p):
            assert sql == store.V4_TEAMS_SQL
            return [{"customer_id": "A", "team_id": "TEAM1", "last_ship": date(2026, 1, 1), "orders": 1}]

    hub = _WriteHub(stored=200)
    with pytest.raises(RuntimeError, match="refusing to shrink"):
        await store.sync_customer_teams(hub, _Gold())
    assert store.DELETE_TEAMS_SQL not in hub.calls and store.LOG_REFRESH_FAILED_SQL in hub.calls


def test_owner_job_never_writes_to_pipedrive():
    from pathlib import Path

    root = Path(__file__).resolve().parents[1] / "app/services"
    mod = (root / "customer_lifespan_pipedrive.py").read_text()
    for writer in ("set_owner", "create_deal", "create_org", "set_org_mcleod"):
        assert writer not in mod
    src = (root / "attrition_pipedrive/pipedrive.py").read_text()
    reader = src.split("async def read_reactivation_owners", 1)[1].split("# ---- organizations", 1)[0]
    assert '"POST"' not in reader and '"PATCH"' not in reader


def test_owner_job_is_on_the_roster_and_raises():
    from pathlib import Path

    src = (Path(__file__).resolve().parents[1] / "app/main.py").read_text()
    assert 'id="hourly_customer_lifespan_owners"' in src
    assert '"hourly_customer_lifespan_owners":' in src.split("EXPECTED_JOBS = {", 1)[1].split("}", 1)[0]
    body = src.split("async def _scheduled_customer_lifespan_owners", 1)[1].split("\nasync def ", 1)[0]
    assert "raise" in body and "aclose()" in body


# ------------------------------------------------------------------ the deck's wording (no JS runner: read the TSX)


def _tsx(name: str) -> str:
    from pathlib import Path

    return (Path(__file__).resolve().parents[2] / "frontend/app/reports/customer-lifespan" / name).read_text()


def test_summary_is_the_first_and_default_tab():
    page = _tsx("page.tsx")
    assert page.index('{ k: "summary", label: "Summary" }') < page.index('{ k: "trends", label: "Trends" }')
    assert 'pick<TabKey>(params.get("tab"), TABS, "summary")' in page


@pytest.mark.parametrize("name,texts", [
    ("KpiStrip.tsx", ["Current customers", "Avg. lifespan · Lost customers", "Avg. lifespan · Current customers",
                      "First to most recent load · To date", "Top 10 customers:", "all-time"]),
    ("TrendPanel.tsx", ["Tracks new, returning, and lost customers over time", "Profit per Customer ($)",
                        "Margin %", "Revenue ($)", "Bars use the left axis; lines use the right."]),
    ("CohortsPanel.tsx", ["By %", "By #", "Customers by first-load year: active, lost and value", "At Risk",
                          "Lifetime Profit ($)", "Avg. Profit ($) per active month", "fmtMo(r.avg_lifespan_base)"]),
    ("LifespanPanel.tsx", ["Customer lifespan", "Customer retention over time", "the 50% line marks the median"]),
    ("CustomersPanel.tsx", ["TEAM / Sales Exec.", "Days since last load", "Customer lifespan", "Reactivations",
                            "Total loads", "Total Revenue ($)", "Profit ($)", "Avg. monthly Profit ($)"]),
    ("SummaryPanel.tsx", ["Customer Retention | Summary", "Customers with declining load volume",
                          "Profit last 90 days", "Reactivated customers", "vs. same period last year"]),
])
def test_deck_wording(name, texts):
    src = _tsx(name)
    for text in texts:
        assert text in src, text


def test_flow_tooltip_reads_stock_then_flows():
    src = _tsx("TrendPanel.tsx")
    order = src.split("const FLOW_ORDER", 1)[1].split("}", 1)[0]
    positions = [order.index(k) for k in ('"Customer base"', '"Shipping customers"', "New:", '"Came back"', "Lost:")]
    assert positions == sorted(positions)


def test_survival_axis_is_round_months():
    src = _tsx("LifespanPanel.tsx")
    assert "horizon >= 24 ? 12 : 3" in src and "tickFormatter={(m: number) => `${m}m`}" in src


def test_filter_bar_uses_the_shared_sticky_bar():
    assert "<CollapsibleFilterBar>" in _tsx("LifespanFilterBar.tsx")


# ------------------------------------------------------------------ review 2026-11-04


def test_a_year_typed_halfway_never_breaks_the_period():
    """A date input emits 0001-… while someone types: `replace(year=0)` was a 500 on /board."""
    p = sc.resolve_period("custom", date(1, 6, 1), date(1, 7, 1), AS_OF)
    assert p.start == sc.ALL_START and p.end == sc.ALL_START
    assert sc.shift_year(p).start == date(1999, 1, 1)


def test_a_month_straddling_the_range_start_keeps_the_true_first_load():
    """The range SQL clips a month's first_ship; history keeps the real one."""
    history = core.merge_rows([_m("X", date(2026, 3, 1), date(2026, 3, 5), date(2026, 3, 28), loads=4)], "all")
    inside = core.merge_rows([_m("X", date(2026, 3, 1), date(2026, 3, 15), date(2026, 3, 28), loads=2)], "all")
    start = date(2026, 3, 15)
    (c,) = sc.scope_customers(history, inside, AS_OF, 90)
    assert c.first_ship == date(2026, 3, 5) and c.loads == 2
    assert not core.is_new(c, start)
    rows = tr.trend([c], AS_OF, 90, "month", start)
    assert rows[0]["period"] == "2026-03" and rows[0]["new"] == 0 and rows[0]["lost"] == 1


def test_a_customer_missing_from_history_is_skipped_not_a_500():
    inside = core.merge_rows([_m("X", date(2026, 3, 1), date(2026, 3, 15), date(2026, 3, 28))], "all")
    assert sc.scope_customers([], inside, AS_OF, 90) == []


def test_clicking_outside_a_bar_opens_nothing():
    for name in ("TrendPanel.tsx", "LifespanPanel.tsx"):
        assert "state?.activeTooltipIndex == null" in _tsx(name), name


def test_drawers_sit_above_the_site_header():
    """The sticky header is z-50: at z-40 it hid the drawer's title and close button."""
    for name in ("ListDrawer.tsx", "CustomerDrawer.tsx"):
        assert "fixed inset-0 z-[60]" in _tsx(name), name
