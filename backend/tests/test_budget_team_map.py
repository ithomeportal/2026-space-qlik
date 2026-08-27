"""The budget→team map must never silently drop a budget row.

Bruno PDFs 2026-08-27 ("space -- Budget Updates" R1, "BRUNO -- Ops Portal
Updates" R1). Both asked to "update the report to the table
``2026_budget_ops_by_customer``", validating on Aug-2026 =
1,432.03 loads / $2,706,634.18 / $502,241.50.

Measured before writing a line: that table is a numerically exact row-for-row
copy of the CORP/2026 slice of ``2025_budget_ops_by_customer`` (0 rows differ
once float-expansion noise is rounded away), and the mirror both reports
actually read — ``daily_production_budget_report`` — matches it day-for-day
across all 365 days of 2026. **The table swap was a no-op. The numbers were
already in the database.** Two query defects lost them:

  * Every budget panel did ``JOIN customer_team ct ON TRIM(budget."Customer
    Name") = ct.customer_name`` — an INNER JOIN onto a map keyed on
    ``mcleod_gld_budget_report_v4`` names. Two budget customers carry a
    McLeod-id prefix v4 does not have, so they matched nothing and vanished:

        KELLQUMX - KELLOGG COMPANY MEXICO           → v4 'KELLOGG …'  (TEAM4)
        STARCOMX - STARCORR DE MEXICO S DE RL DE CV → v4 'STARCORR …' (TEAM3)

    −14.07 loads / −$58,940.28 / −$6,899.76 in Aug-2026; −107.97 loads /
    −$391,540 / −$49,091 across 2026. That is exactly why Budget Follow Up
    read 1,417.96 against the table's true 1,432.03 — no error, no log line.

  * ``/combo`` at month grain capped its window at today, so the BDGT line
    compared a full month of production target against 27/31 of it. That is
    where Bruno's 1,243 / $2,317,148 / $433,303 came from: the Aug bucket
    truncated at 2026-08-27 sums to 1,242.52 / $2,317,148.42 / $433,303.44.

⚠ Layer 1 is a SOURCE scan, not an assertion about today's call sites. A
per-site assertion passes forever while a new panel is added with the old
INNER JOIN — which is precisely how this survived across 20 sites and five
consumers. The class is what is pinned.

⚠ Layer 3 freezes the clock. ``this_month`` and the month-grain anchor both
read ``cst_today()``, so without a freeze these assertions pass in Aug-2026
and fail in September while nothing is wrong. The budget is a fixed annual
plan, so pinning Aug-2026's figures is stable; if the CFO reloads the table
this SHOULD go red.
"""

from __future__ import annotations

import asyncio
import importlib
import inspect
import os
import re
import types
from datetime import date
from pathlib import Path

import pytest

from app.datalake import BUDGET_NAME_PREFIX_RE, budget_team_cte
from app.routers.ops_portal_overview._constants import (
    CUSTOMER_TEAM_CTE,
    customer_team_cte,
)

BACKEND = Path(__file__).resolve().parents[1]

# Bruno's validation criteria, both PDFs, Aug-2026 CORP.
AUG = (date(2026, 8, 1), date(2026, 8, 31))
EXPECT_LOADS = 1432.03
EXPECT_REVENUE = 2706634.18
EXPECT_PROFIT = 502241.50

# What the prefix-strip must resolve, measured against live gold 2026-08-27.
EXPECT_FALLBACK = {
    "KELLQUMX - KELLOGG COMPANY MEXICO": "TEAM4",
    "STARCOMX - STARCORR DE MEXICO S DE RL DE CV": "TEAM3",
}

FROZEN_TODAY = date(2026, 8, 27)  # a Thursday — mid-week AND mid-month on purpose

# The last bucket of each grain, and the whole-period budget it must carry.
# Measured against live gold 2026-08-27. Truncating at today read 1,242.52 /
# $2,317,148.42 / $433,303.44 (month) and 199.32 / $373,032.72 / $68,641.60
# (week) — the week bucket was 39% short.
BUCKETS = {
    "month": (date(2026, 8, 1),  date(2026, 8, 31), 1432.03, 2706634.18, 502241.50),
    "week":  (date(2026, 8, 24), date(2026, 8, 30),  326.27,  615933.38, 114176.62),
}


# ---------------------------------------------------------------------------
# Layer 1 — the class, scanned over the source
# ---------------------------------------------------------------------------


def _python_sources():
    for p in sorted((BACKEND / "app").rglob("*.py")):
        if "__pycache__" in p.parts:
            continue
        yield p


# ⚠ Scan STATEMENTS, not lines. `ceo_executive` has a v4 CTE it aliases
# `budget`, so a line-level regex flags a join that never touches the mirror,
# and `deps.py` names the table only in a docstring. Anchor on the real FROM
# clause and read the join list that follows it (§ scan whole files, not lines).
_SQL_KEYWORDS = {"WHERE", "GROUP", "ORDER", "UNION", "LEFT", "JOIN", "INNER"}
_MIRROR_FROM = re.compile(
    r"FROM\s+public\.daily_production_budget_report\s+(?:AS\s+)?(\w+)?", re.S
)


def _mirror_reads():
    """(path, alias, the join list that follows) for every read of the mirror."""
    for p in _python_sources():
        src = p.read_text()
        for m in _MIRROR_FROM.finditer(src):
            alias = m.group(1)
            if alias and alias.upper() in _SQL_KEYWORDS:
                alias = None  # bare `FROM <table> WHERE …` — no alias at all
            tail = src[m.end(): m.end() + 400]
            cut = re.search(r"\n\s*(WHERE|GROUP BY|ORDER BY)", tail)
            yield p, alias, tail[: cut.start()] if cut else tail


def test_no_budget_join_uses_the_dropping_inner_join() -> None:
    """An INNER JOIN here deletes a customer instead of erroring."""
    offenders = [
        f"{p.relative_to(BACKEND)} (alias {alias})"
        for p, alias, joins in _mirror_reads()
        if re.search(r"(?<!LEFT )JOIN\s+customer_team", joins)
    ]
    assert not offenders, (
        "budget-mirror joins must be `LEFT JOIN budget_team` (app.datalake."
        "budget_team_cte) — a bare JOIN to customer_team drops any budget "
        "customer whose name has no exact v4 twin: " + ", ".join(offenders)
    )


def test_every_budget_team_join_site_is_a_left_join() -> None:
    """The other direction: budget_team must never be INNER JOINed either."""
    offenders = [
        f"{p.relative_to(BACKEND)}:{i}"
        for p in _python_sources()
        for i, line in enumerate(p.read_text().splitlines(), 1)
        if "JOIN budget_team" in line and "LEFT JOIN budget_team" not in line
    ]
    assert not offenders, offenders


def test_every_mirror_reader_that_scopes_by_team_renders_budget_team() -> None:
    """A file that reads the mirror and maps customers to teams uses the new map.

    Stated per FILE, not per join: `ceo_executive` builds its `production` CTE
    straight off the mirror and applies the map one level up, so a per-statement
    rule would read that source as unmapped. `ops_direct_compare` is the one
    deliberate exception — it sums the whole table with no team scope at all, so
    it never dropped anything.
    """
    offenders = []
    for p in {path for path, _a, _j in _mirror_reads()}:
        src = p.read_text()
        if "customer_team" in src and "budget_team" not in src:
            offenders.append(p.name)
    assert not offenders, (
        f"{sorted(offenders)} map budget customers to teams without budget_team"
    )


def test_the_mirror_scan_can_see_a_known_positive() -> None:
    """A scan that matches nothing would pass every test above.

    Prove it finds the real call sites before trusting any negative from it.
    """
    reads = list(_mirror_reads())
    names = {p.name for p, _a, _j in reads}
    assert len(reads) >= 18, f"only {len(reads)} mirror reads found"
    assert {"budget_followup.py", "chart.py", "variance.py", "actuals.py"} <= names


# ---------------------------------------------------------------------------
# Layer 2 — the rendered CTE
# ---------------------------------------------------------------------------


def test_cte_resolves_exact_first_then_the_stripped_name() -> None:
    cte = budget_team_cte()
    assert "LEFT JOIN customer_team t_exact" in cte
    assert "LEFT JOIN customer_team t_stripped" in cte
    # The fallback may only fire where the exact match found nothing.
    assert "t_exact.customer_name IS NULL" in cte
    assert BUDGET_NAME_PREFIX_RE in cte
    assert "COALESCE(t_exact.team_id, t_stripped.team_id) AS team_id" in cte


def test_cte_follows_the_upstream_maps_output_column() -> None:
    """CEO Executive's map emits `division_team`, not `team_id`."""
    ceo = budget_team_cte(team_col="division_team")
    assert "COALESCE(t_exact.division_team, t_stripped.division_team)" in ceo
    assert "team_id" not in ceo


def test_the_strip_never_rewrites_the_displayed_customer() -> None:
    """§83: two budget customers can strip to the same v4 name.

    `STARCOMX - STARCORR …` and the separate `STARCORR …` row (mcleod_id
    STARTETX) both do. The regex may appear ONLY inside the join predicate —
    if it ever reached a SELECT list or a GROUP BY the two would merge and
    their actuals would be counted twice.
    """
    cte = budget_team_cte()
    stripped_lines = [ln for ln in cte.splitlines() if "regexp_replace" in ln]
    assert stripped_lines, "the fallback vanished"
    body = cte[: cte.index("regexp_replace")]
    assert body.rstrip().endswith("t_stripped.customer_name ="), (
        "the strip must sit in the join predicate, never in a projection"
    )


def test_the_plain_render_is_unchanged() -> None:
    """Non-budget callers must stay byte-identical — savings joins share this."""
    assert "budget_team" not in customer_team_cte()
    assert customer_team_cte() == CUSTOMER_TEAM_CTE
    assert customer_team_cte(with_budget_team=True).startswith(
        CUSTOMER_TEAM_CTE.rstrip("\n")
    )


# ---------------------------------------------------------------------------
# Layer 3 — replay the app's real SQL against real gold
# ---------------------------------------------------------------------------

_GOLD = os.environ.get("SAVINGS_DATABASE_URL")
live = pytest.mark.skipif(not _GOLD, reason="SAVINGS_DATABASE_URL not set — offline run")


class _RecordingPool:
    """Captures (sql, params) — the statement the endpoint really emits."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple]] = []

    async def fetch(self, sql, *params):
        self.calls.append((sql, params))
        return []

    async def fetchrow(self, sql, *params):
        self.calls.append((sql, params))
        return None

    async def fetchval(self, sql, *params):
        self.calls.append((sql, params))
        return None


_POOL_ATTRS = ("get_datalake_gold_pool", "get_pool")


def _drive(module_path: str, fn_name: str, **kwargs):
    """Run one endpoint against a recording pool with the clock frozen."""
    mod = importlib.import_module(module_path)
    pool = _RecordingPool()
    undo = []
    for attr in _POOL_ATTRS:
        if hasattr(mod, attr):
            undo.append((mod, attr, getattr(mod, attr)))
            setattr(mod, attr, lambda request, _p=pool: _p)
    if hasattr(mod, "cst_today"):
        undo.append((mod, "cst_today", mod.cst_today))
        setattr(mod, "cst_today", lambda: FROZEN_TODAY)
    fn = getattr(mod, fn_name)
    sig = inspect.signature(fn)
    call = {}
    for name, p in sig.parameters.items():
        if name in ("request", "_user", "user"):
            continue
        d = p.default
        v = getattr(d, "default", d)
        if v is Ellipsis or repr(v).startswith("PydanticUndefined"):
            v = None
        call[name] = v
    call.update(kwargs)
    call["request"] = types.SimpleNamespace(
        state=types.SimpleNamespace(),
        app=types.SimpleNamespace(state=types.SimpleNamespace(ap_pool=None)),
        query_params={},
    )
    for u in ("_user", "user"):
        if u in sig.parameters:
            call[u] = {}
    try:
        try:
            asyncio.run(fn(**call))
        except Exception:
            pass  # the stub returns None/[]; the statement is what we came for
    finally:
        for mod_, attr, orig in undo:
            setattr(mod_, attr, orig)
    return pool.calls


def _budget_statements(calls):
    return [(s, p) for s, p in calls if "daily_production_budget_report" in s]


async def _gold():
    import asyncpg

    return await asyncpg.connect(re.sub(r"[?&]sslmode=\w+", "", _GOLD), ssl="require")


@live
def test_live_the_map_leaves_no_2026_budget_row_unresolved() -> None:
    async def run():
        conn = await _gold()
        try:
            sql = f"""
            WITH {customer_team_cte(with_budget_team=True)}
            SELECT
              COUNT(*) FILTER (WHERE ct.team_id IS NULL) AS unresolved_rows,
              COUNT(DISTINCT b."Customer Name")
                FILTER (WHERE ct.team_id IS NULL)        AS unresolved_customers
            FROM public.daily_production_budget_report b
            LEFT JOIN budget_team ct
                   ON TRIM(b."Customer Name") = ct.customer_name
            WHERE b."Date" BETWEEN $1 AND $2
            """
            row = await conn.fetchrow(sql, date(2026, 1, 1), date(2026, 12, 31))
            fallback = await conn.fetch(
                f"""
                WITH {customer_team_cte(with_budget_team=True)},
                exact AS (SELECT customer_name FROM customer_team)
                SELECT bt.customer_name, bt.team_id
                FROM budget_team bt
                WHERE bt.team_id IS NOT NULL
                  AND bt.customer_name NOT IN (SELECT customer_name FROM exact)
                """
            )
            return row, fallback
        finally:
            await conn.close()

    row, fallback = asyncio.run(run())
    assert row["unresolved_rows"] == 0, (
        f"{row['unresolved_rows']} budget rows across "
        f"{row['unresolved_customers']} customers resolve to no team — under "
        "the old INNER JOIN every one of them would have vanished from the "
        "totals with no error"
    )
    assert {r["customer_name"]: r["team_id"] for r in fallback} == EXPECT_FALLBACK


@live
def test_live_budget_followup_summary_matches_brunos_figures() -> None:
    """`space -- Budget Updates` R1: 1432.03 / 2706634.18 / 502241.50."""
    calls = _drive(
        "app.routers.budget_followup",
        "summary",
        start_date=AUG[0],
        end_date=AUG[1],
    )
    stmts = _budget_statements(calls)
    assert len(stmts) == 1, f"expected one budget statement, got {len(stmts)}"
    sql, params = stmts[0]

    async def run():
        conn = await _gold()
        try:
            return await conn.fetchrow(sql, *params)
        finally:
            await conn.close()

    row = asyncio.run(run())
    assert round(float(row["loads_budget"]), 2) == EXPECT_LOADS
    assert round(float(row["revenue_budget"]), 2) == EXPECT_REVENUE
    assert round(float(row["profit_budget"]), 2) == EXPECT_PROFIT


@live
def test_live_ops_portal_this_month_matches_brunos_figures() -> None:
    """`BRUNO -- Ops Portal Updates` R1, the date-filtered panel."""
    calls = _drive(
        "app.routers.ops_portal_overview.variance",
        "team_variance",
        range="this_month",
    )
    stmts = _budget_statements(calls)
    assert len(stmts) == 1
    sql, params = stmts[0]
    assert params[0] == AUG[0] and params[1] == AUG[1], params[:2]

    async def run():
        conn = await _gold()
        try:
            return await conn.fetchrow(sql, *params)
        finally:
            await conn.close()

    row = asyncio.run(run())
    assert round(float(row["loads_budget"]), 2) == EXPECT_LOADS
    assert round(float(row["revenue_budget"]), 2) == EXPECT_REVENUE
    assert round(float(row["profit_budget"]), 2) == EXPECT_PROFIT


@live
@pytest.mark.parametrize("grain", sorted(BUCKETS))
def test_live_the_chart_bucket_carries_the_whole_period(grain: str) -> None:
    """The BDGT line read 1,243 because its window stopped at today.

    A budget is a whole-PERIOD plan stored one row per day, so every grain's
    last bucket must carry the full period. The week bucket had the identical
    defect one grain down; leaving it would have put two conventions on one
    chart behind a grain toggle.

    The production leg must stay capped — this asserts the two windows DIFFER,
    not merely that the budget one is long enough.
    """
    bucket_start, bucket_end, loads, revenue, profit = BUCKETS[grain]
    calls = _drive("app.routers.ops_portal_overview.chart", "combo", grain=grain)
    bud = _budget_statements(calls)
    assert len(bud) == 1
    bud_sql, bud_params = bud[0]
    prod = [(s, p) for s, p in calls if "mcleod_gld_budget_report_v4" in s]
    assert prod, "no production statement emitted"

    assert bud_params[1] == bucket_end, bud_params[1]
    assert bud_params[1] > FROZEN_TODAY, "the budget leg was not widened at all"
    assert any(FROZEN_TODAY in p for _s, p in prod), (
        "the production bars must still stop at today"
    )

    async def run():
        conn = await _gold()
        try:
            return await conn.fetch(bud_sql, *bud_params)
        finally:
            await conn.close()

    rows = asyncio.run(run())
    last = [r for r in rows if r["bucket_start"] == bucket_start]
    assert len(last) == 1, f"no {bucket_start} bucket at {grain} grain"
    assert round(float(last[0]["budget_loads"]), 2) == loads
    assert round(float(last[0]["budget_revenue"]), 2) == revenue
    assert round(float(last[0]["budget_profit"]), 2) == profit


@live
def test_live_the_day_grain_is_unchanged() -> None:
    """Day buckets are already whole — widening must be a no-op there.

    `_bucket_end` is the identity for `day`, which is what lets `combo` apply it
    with no branch. If that ever stops holding, the budget leg would run past
    the production leg for a single day and the last bar would read as a miss.
    """
    calls = _drive("app.routers.ops_portal_overview.chart", "combo", grain="day")
    bud_sql, bud_params = _budget_statements(calls)[0]
    assert bud_params[1] == FROZEN_TODAY, bud_params[1]
