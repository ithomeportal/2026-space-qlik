"""The budget-variance panels read their ACTUAL leg from v4, not from the mirror.

Bruno PDF 2026-08-31 "space -- Ops Portal Updates" R1: with "This Month"
selected the KPI cards read Volume 1,554 / Revenue 2,979,183 / Profit 508,214
against a budget of 1,432 / 2,706,634 / 502,242 — variance 122 / 272,549 /
5,973 — while the "Budget Monthly Variance" table beneath them printed
137 / 259,817 / 2,744.

Diagnosed arithmetically before a file was opened. Summing
``daily_production_budget_report`` over 2026-08-01..08-31 gives:

    "Loads Actual"   1,569      "Loads Budget"     1,432.03  → 136.97 → 137
    "Revenue Actual" 2,966,451  "Revenue Budget" 2,706,634.18 → 259,816.82
    "Profit Actual"  504,985    "Profit Budget"    502,241.50 →   2,743.50

i.e. exactly the three wrong numbers. The BUDGET leg was never wrong — it is
the §90-validated figure, identical in both panels. The ACTUAL leg was a
different measurement: the mirror's pre-aggregated "… Actual" columns instead
of ``mcleod_gld_budget_report_v4``, which is what the KPI cards, the /combo
chart and the bottom Actuals table all use.

Two independent causes, pushing OPPOSITE ways — which is why the panel looked
merely unremarkable rather than obviously broken for months:

  * the mirror counts loads with NO ``total_charge IS NOT NULL AND <> 0``
    guard, so its volume runs HIGH (NIAGARA BOTTLING 67 vs 60, OCV MEXICO
    64 vs 50);
  * n8n rebuilds the mirror every 6 h while v4 refreshes every 15 min, so its
    money runs LOW (TRANE −5 loads / −$14,380, PCA PHOENIX −3 / −$3,192 …).

⚠ FOUR endpoints moved, not the one reported. `/team-variance` alone would have
left its own by-team and weekly drill-throughs — and the per-customer list
under it — disagreeing with the panel they expand (§95, §96).

⚠ Layer 1 is a SOURCE scan over whole statements (``re.S``), not a line scan.
The mirror's actual columns are split across lines at several of these sites, so
a line-based grep reports a clean sweep while the read sits there (§96). The
scan is proved able to see a known positive first — a regex that matches
nothing satisfies every "no offenders" assertion ever written (§91).
"""

from __future__ import annotations

import asyncio
import inspect
import re
import types

import pytest

from app.routers.ops_portal_overview import variance as var_mod


# --------------------------------------------------------------------------
# Layer 1 — the source scan
# --------------------------------------------------------------------------

# The only way to READ one of the mirror's pre-aggregated production columns is
# through the `budget` alias, so that is what the scan matches. Matching the
# bare column name instead would fire on this module's own prose, which
# describes the defect at length and must be allowed to keep doing so.
#
# ⚠ Do NOT "fix" that by stripping docstrings with a `\"""..."""` regex: the SQL
# in this module is ALSO triple-quoted, so such a stripper deletes every
# statement and the offender scan then passes vacuously against an empty
# string. That is precisely the §91 trap — and the first version of this file
# fell into it, which is why the known-positive probe below uses the real
# historical statement rather than a synthetic one.
_ACTUAL_RE = re.compile(r'budget\."(?:Loads|Revenue|Profit) Actual"')
_BUDGET_RE = re.compile(r'budget\."(?:Loads|Revenue|Profit) Budget"')

_SOURCE = inspect.getsource(var_mod)
# Comment LINES only — see above.
_CODE_ONLY = re.sub(r"^\s*#.*$", "", _SOURCE, flags=re.M)

# The statement `/team-variance` actually carried until 2026-08-31.
_KNOWN_POSITIVE = '''
          SELECT
            budget."Customer Name" AS customer_name,
            SUM(budget."Loads Actual")    AS loads_actual,
            SUM(budget."Loads Budget")    AS loads_budget,
            SUM(budget."Profit Actual")   AS profit_actual
          FROM public.daily_production_budget_report budget
'''


def test_the_scan_can_see_a_known_positive():
    """A regex that matches nothing satisfies every "no offenders" assertion."""
    assert len(_ACTUAL_RE.findall(_KNOWN_POSITIVE)) == 2
    assert len(_BUDGET_RE.findall(_KNOWN_POSITIVE)) == 1


def test_the_scan_is_looking_at_real_sql():
    """Guards the scan's INPUT, not just its pattern: if _CODE_ONLY ever stops
    containing the statements, every assertion below goes green for free."""
    assert "public.mcleod_gld_budget_report_v4" in _CODE_ONLY
    assert "FULL OUTER JOIN bud b" in _CODE_ONLY
    assert _CODE_ONLY.count("public.daily_production_budget_report") >= 1


def test_no_panel_reads_the_mirrors_actual_columns():
    offenders = sorted(set(_ACTUAL_RE.findall(_CODE_ONLY)))
    assert not offenders, (
        f"variance.py still reads the mirror's pre-aggregated actuals: {offenders}. "
        "The actual leg must be mcleod_gld_budget_report_v4 — the same "
        "measurement the KPI cards and /combo use (Bruno 2026-08-31 R1)."
    )


def test_the_budget_leg_still_comes_from_the_mirror():
    """The budget half was never wrong (§90) — this fix must not have moved it."""
    assert _BUDGET_RE.search(_CODE_ONLY), "the budget leg left the mirror"
    assert "public.daily_production_budget_report" in _CODE_ONLY


# --------------------------------------------------------------------------
# Layer 2 — the statements the endpoints actually emit
# --------------------------------------------------------------------------


def _row(**kw):
    """A stub asyncpg Record: bracket access only, like the real thing."""
    base = dict(active_customers=0, loads_budget=0, loads_actual=0,
                revenue_budget=0, revenue_actual=0, profit_budget=0,
                profit_actual=0, team_id=None, wk=None)
    base.update(kw)
    return base


class _StubPool:
    """Captures every statement instead of running it."""

    def __init__(self, rows=None) -> None:
        self.sqls: list[str] = []
        self.rows = rows or []

    async def fetch(self, sql, *params):
        self.sqls.append(sql)
        return list(self.rows)

    async def fetchrow(self, sql, *params):
        self.sqls.append(sql)
        # An aggregate SELECT always returns exactly one row in production, so
        # the stub must too — a None here would test a state the DB cannot
        # produce and hide the assertions behind a TypeError.
        return self.rows[0] if self.rows else _row()


def _drive(fn, rows=None, **kwargs):
    pool = _StubPool(rows)
    original = var_mod.get_datalake_gold_pool
    var_mod.get_datalake_gold_pool = lambda request: pool
    try:
        request = types.SimpleNamespace(
            app=types.SimpleNamespace(state=types.SimpleNamespace())
        )
        resp = asyncio.run(fn(request=request, _user={}, **kwargs))
    finally:
        var_mod.get_datalake_gold_pool = original
    return pool, resp


_ALL_FOUR = (
    ("team_variance", dict(range="this_month", start_date=None, end_date=None,
                           team=None, customer=None)),
    ("customer_variance", dict(range="this_month", start_date=None, end_date=None,
                               team=None, customer=None, limit=50)),
    ("team_variance_weekly", dict(team=None, customer=None)),
    ("team_variance_by_team", dict(range="this_month", start_date=None,
                                   end_date=None, customer=None)),
)


@pytest.mark.parametrize("name,kwargs", _ALL_FOUR)
def test_every_panel_reads_v4_for_its_actual(name, kwargs):
    pool, _ = _drive(getattr(var_mod, name), **kwargs)
    sql = "\n".join(pool.sqls)
    assert "public.mcleod_gld_budget_report_v4" in sql, (
        f"{name} does not read v4 — its actual leg is not the KPI's measurement"
    )
    # The volume guard is what made the mirror's count run high. Asserted as a
    # whole statement (re.S) because it is split across lines.
    assert re.search(
        r"COUNT\(\*\)\s*FILTER\s*\(\s*WHERE\s+br4\.total_charge\s+IS\s+NOT\s+NULL"
        r"\s+AND\s+br4\.total_charge\s*<>\s*0\s*\)",
        sql,
        re.S,
    ), f"{name} counts loads without the total_charge guard"


@pytest.mark.parametrize("name,kwargs", _ALL_FOUR)
def test_every_panel_still_left_joins_the_budget_team_map(name, kwargs):
    """§91 — an INNER JOIN here deletes budget customers with no exact v4 twin."""
    pool, _ = _drive(getattr(var_mod, name), **kwargs)
    sql = "\n".join(pool.sqls)
    assert "LEFT JOIN budget_team ct" in sql, name
    assert not re.search(r"(?<!LEFT )JOIN customer_team ct", sql), name


@pytest.mark.parametrize("name,kwargs", _ALL_FOUR)
def test_the_two_legs_are_full_outer_joined(name, kwargs):
    """A customer that shipped with no budget, and a budget customer that
    shipped nothing, are both real. An inner join renders either as a MISSING
    row rather than a variance (§91, §75)."""
    pool, _ = _drive(getattr(var_mod, name), **kwargs)
    sql = "\n".join(pool.sqls)
    assert "FULL OUTER JOIN bud b" in sql, name


def test_the_budget_side_aggregates_after_resolving_the_name():
    """§83 — two budget names can resolve to one v4 customer. Grouping on the
    resolved key BEFORE the join makes them sum; joining first would emit the
    production row once per budget row and double-count the actual."""
    pool, _ = _drive(var_mod.customer_variance, range="this_month",
                     start_date=None, end_date=None, team=None,
                     customer=None, limit=50)
    sql = "\n".join(pool.sqls)
    assert "COALESCE(ct.v4_customer_name" in sql
    # The resolved name is the GROUP BY key of the budget CTE, not something
    # applied after the join.
    bud = sql.split("bud AS (", 1)[1].split("per_customer AS (", 1)[0]
    assert "GROUP BY" in bud and "COALESCE(ct.v4_customer_name" in bud


# --------------------------------------------------------------------------
# Layer 3 — the panel and its drill-throughs must agree
# --------------------------------------------------------------------------


def test_by_team_total_equals_the_panel_for_the_same_sums():
    """The modal is a decomposition of the panel, so the Total it prints has to
    be the panel's own number — computed from the same helper, not re-derived."""
    teams = [
        _row(team_id="TEAM1", active_customers=6, loads_actual=400,
             loads_budget=340.5, revenue_actual=900_000, revenue_budget=800_000,
             profit_actual=150_000, profit_budget=140_000),
        _row(team_id="TEAM2", active_customers=15, loads_actual=227,
             loads_budget=163.39, revenue_actual=396_047, revenue_budget=264_086,
             profit_actual=67_595, profit_budget=43_684),
    ]
    _, resp = _drive(var_mod.team_variance_by_team, rows=teams,
                     range="this_month", start_date=None, end_date=None,
                     customer=None)
    total = resp["data"]["total"]
    rows = {t["team_id"]: t for t in resp["data"]["teams"]}
    assert total["volume_var"] == pytest.approx(
        rows["TEAM1"]["volume_var"] + rows["TEAM2"]["volume_var"]
    )
    assert total["revenue_var"] == pytest.approx(
        rows["TEAM1"]["revenue_var"] + rows["TEAM2"]["revenue_var"]
    )
    assert total["customers"] == 21


def test_the_customers_count_reads_the_same_leg_as_the_sums():
    """§96 — a COUNT and a SUM printed as a pair must span one population.

    "Customers" is now `loads_actual > 0` over `per_customer`, i.e. the v4
    leg the variance beside it is computed from. Under the old code it counted
    the mirror's `"Loads Actual"` while the sums came from the same place —
    consistent then, and it had to move WITH the actual leg, not stay behind.
    """
    pool, _ = _drive(var_mod.team_variance, range="this_month", start_date=None,
                     end_date=None, team=None, customer=None)
    sql = "\n".join(pool.sqls)
    m = re.search(r"COUNT\(\*\)\s*FILTER\s*\(\s*WHERE\s+([^)]+)\)\s*AS\s+active_customers",
                  sql, re.S)
    assert m, "active_customers is no longer a FILTERed count"
    assert "loads_actual > 0" in m.group(1)
    # …and it is counted over per_customer, the FULL OUTER JOIN of both legs.
    tail = sql.split("AS active_customers", 1)[1]
    assert "FROM per_customer" in tail


def test_the_panel_and_the_customer_list_share_one_window_and_scope():
    """Both take the page date filter and the same v4 predicate; a divergence
    here is how the list stops summing to the panel above it."""
    p1, _ = _drive(var_mod.team_variance, range="this_month", start_date=None,
                   end_date=None, team=None, customer=None)
    p2, _ = _drive(var_mod.customer_variance, range="this_month",
                   start_date=None, end_date=None, team=None, customer=None,
                   limit=50)
    def _prod(sqls):
        s = "\n".join(sqls)
        return s.split("prod AS (", 1)[1].split("bud AS (", 1)[0]
    assert _prod(p1.sqls) == _prod(p2.sqls)


def test_the_by_team_split_narrows_by_the_same_column_the_team_pill_uses():
    """§16 — filtering the page to TEAM1 must give the by-team modal's TEAM1
    row. Both therefore key on the v4 row's own team column, not on the
    per-customer dominant-team map."""
    pool, _ = _drive(var_mod.team_variance_by_team, range="this_month",
                     start_date=None, end_date=None, customer=None)
    sql = "\n".join(pool.sqls)
    assert "TRIM(br4.team_id) AS grp" in sql
    # And the single-team path narrows the same column.
    pool2, _ = _drive(var_mod.team_variance, range="this_month",
                      start_date=None, end_date=None, team="TEAM1",
                      customer=None)
    assert "br4.team_id = ANY(" in "\n".join(pool2.sqls)


def test_the_weekly_modal_buckets_both_legs_on_their_own_date_column():
    """The production leg is dated on departure and the budget leg on the
    mirror's "Date" — bucketing both on one column would silently shift one."""
    pool, _ = _drive(var_mod.team_variance_weekly, team=None, customer=None)
    sql = "\n".join(pool.sqls)
    assert "DATE_TRUNC('week', br4.origin_actual_departure)::date AS grp" in sql
    assert 'DATE_TRUNC(\'week\', budget."Date")::date AS grp' in sql
