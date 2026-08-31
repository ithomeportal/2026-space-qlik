"""Bruno PDF "space -- Ops Portal Updates" (2026-08-31) — the parts that fail silently.

Three of the nine requests move a NUMBER, and each of the three is a defect
class this repo has already been bitten by:

  R3  Attrition — the panel and the Attrition WoW report shipped DIFFERENT
      METRICS under the same label. Nothing errored; they simply disagreed.
      Pinned here by driving both and asserting they agree on the same data
      (§95).

  R4  Volume / Revenue / Profit (MTD) — the window must end at the close of
      YESTERDAY and must not follow the page's Date filter. A wrong bound reads
      as a plausible number, never as an error.

  R6  Total Negative Loads Losses — `loss_loads` carried a `total_charge`
      guard and `profit_loss` on the very next line did not, so a count over 54
      rows was printed beside a sum over 76 (§96).

⚠ These assert on emitted SQL and on arithmetic, not on live data. With today's
data every wrong variant still returns plausible rows, so no data-driven check
distinguishes right from wrong here — the same reasoning as
`test_ops_portal_scope.py`.

⚠ Guards are mutation-checked: each one is written so that reverting the fix it
pins makes it fail. Do not "simplify" them into shape assertions (§93).
"""

from __future__ import annotations

import inspect
import re
from datetime import date
from types import SimpleNamespace

import pytest

from app import attrition_core as ac
from app.routers import attrition_wow as aw
from app.routers import ops_portal_overview as opo
from app.routers.ops_portal_overview import _metrics, performance
from app.routers.ops_portal_overview._scope import CORP_SCOPE, DFW_SCOPE
from app.routers.ops_portal_overview._sql import _v4_scope_where

USER = {"sub": "probe", "email": "probe@example.com", "roles": ["admin"]}


class _RecordingPool:
    """Captures every statement instead of running any of them."""

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


def _request(pool):
    state = SimpleNamespace(savings_pool=pool, pool=pool)
    return SimpleNamespace(app=SimpleNamespace(state=state), headers={}, query_params={})


def _norm(sql: str) -> str:
    return re.sub(r"\s+", " ", sql).strip()


async def _drive(endpoint, **kw):
    pool = _RecordingPool()
    sig = inspect.signature(endpoint)
    args = {"request": _request(pool)}
    for name, p in sig.parameters.items():
        if name in ("request", "response"):
            continue
        if name.startswith("_"):
            args[name] = USER
        elif name in kw:
            args[name] = kw[name]
        else:
            args[name] = None
    try:
        await endpoint(**args)
    except (TypeError, KeyError, AttributeError):
        # A None row from the stub can blow up downstream arithmetic. The
        # statements are already captured, which is all these tests read.
        pass
    return pool


# ---------------------------------------------------------------------------
# R3 — attrition parity
# ---------------------------------------------------------------------------


def test_attrition_windows_are_adjacent_disjoint_completed_weeks():
    """L8W must end the day before LW starts, and LW must be a finished week.

    Overlapping them would let a strong last week inflate its own baseline and
    drive the % Δ toward zero — a wrong number that still looks reasonable.
    """
    for today in (date(2026, 8, 31), date(2026, 1, 1), date(2026, 3, 2), date(2027, 12, 27)):
        lw_start, lw_end = ac.last_completed_week(today)
        l8_start, l8_end = ac.l8w_window(today)
        assert lw_start.weekday() == 0, today          # Monday
        assert lw_end.weekday() == 6, today            # Sunday
        assert (lw_end - lw_start).days == 6, today
        assert lw_end < today, today                   # never the in-progress week
        assert l8_end == lw_start - __import__("datetime").timedelta(days=1), today
        assert (l8_end - l8_start).days == ac.ATTRITION_WEEKS * 7 - 1, today


def test_attrition_pct_is_signed_and_divides_by_a_fixed_eight():
    """(L8W_avg − LW)/L8W_avg, L8W_avg = Σ weekly-distinct / 8.

    Both halves matter. A union-distinct denominator (the pre-R17 form) or a
    "divide by the weeks that had data" denominator each move the number
    without erroring.
    """
    # 8 weeks summing to 800 ⇒ avg 100. LW 112 ⇒ the roster GREW ⇒ negative.
    blocks = ac.attrition_from_counts(800, 112, 232, 29)
    assert blocks["active_lanes"]["l8w"] == 100.0
    assert blocks["active_lanes"]["pct"] == pytest.approx((100 - 112) / 100)
    assert blocks["active_lanes"]["pct"] < 0, "growth must be NEGATIVE"
    # The count Δ keeps the OPPOSITE numerator — LW − L8W.
    assert blocks["active_lanes"]["diff"] == pytest.approx(112 - 100)
    # 232/8 = 29 ⇒ exactly flat.
    assert blocks["active_customers"]["pct"] == 0.0

    # A quiet week still divides by 8, not by the weeks that had rows.
    assert ac.attrition_from_counts(700, 100, 0, 0)["active_lanes"]["l8w"] == 87.5

    # Zero baseline ⇒ undefined, never a ZeroDivisionError and never 0%.
    assert ac.attrition_from_counts(0, 5, 0, 5)["active_lanes"]["pct"] is None
    assert ac.attrition_pct_100({"pct": None}) == 0.0
    assert ac.attrition_pct_100({"pct": -0.0568}) == pytest.approx(-5.68)


def test_ops_portal_and_attrition_wow_agree_on_the_same_counts():
    """The two reports must derive the SAME percentage from the SAME counts.

    This is the property Bruno asked for. It is asserted through the one shared
    function, so a future edit that re-inlines the arithmetic on either side
    lands here.
    """
    counts = (750, 112, 232, 29)  # the live CORP numbers on 2026-08-31
    blocks = ac.attrition_from_counts(*counts)

    # attrition-wow renders `pct` as a FRACTION (×100 in the frontend).
    assert blocks["active_lanes"]["pct"] == pytest.approx(-0.19466, abs=1e-5)
    # ops-portal renders the SAME value as a 0-100 percentage on the wire.
    assert ac.attrition_pct_100(blocks["active_lanes"]) == pytest.approx(-19.466, abs=1e-3)
    assert ac.attrition_pct_100(blocks["active_customers"]) == 0.0

    # …and performance.py must do exactly that conversion, in that order.
    row = {
        "l8w_lanes_sum": counts[0], "lw_lanes": counts[1],
        "l8w_customers_sum": counts[2], "lw_customers": counts[3],
    }
    cust, lane = performance._attrition_pcts(row)
    assert cust == pytest.approx(ac.attrition_pct_100(blocks["active_customers"]))
    assert lane == pytest.approx(ac.attrition_pct_100(blocks["active_lanes"]))
    # ⚠ Order matters and is easy to swap: customers first, lanes second.
    assert (cust, lane) != (lane, cust) or cust == lane


def test_attrition_wow_summary_still_builds_its_cards_from_the_shared_math():
    """attrition_wow must not keep a private copy of the /8 or the sign."""
    src = inspect.getsource(aw)
    assert "attrition_from_counts" in src
    # The old inlined forms are gone — either would silently win over the import.
    assert "_attr_diff" not in src, "the private attrition helper is back"
    assert "l8w_lanes_sum\"]) / 8.0" not in src


def test_ops_portal_attrition_adopts_attrition_wows_population():
    """The UNILINK exclusion and the COALESCEd lane key are part of the metric.

    Dropping either changes the denominator with no error — the exact way these
    two reports drifted apart in the first place.
    """
    sql, params = performance._attrition_query(
        lambda pr: _v4_scope_where(
            "br4", None, None, None, pr, None, None, None, None, scope=CORP_SCOPE
        )
    )
    assert "NOT LIKE '%UNILINK%'" in sql
    assert "NOT LIKE '%OILTEX%'" in sql
    assert "COALESCE(br4.origin_name,'')" in sql
    # The OLD metric is gone: no 30-day staleness census, no YTD floor.
    assert "CURRENT_DATE - last_load" not in sql
    assert "> 30" not in sql
    # Windows are bound, never interpolated, and are the completed-week pair.
    l8s, l8e, lws, lwe = params[-4:]
    assert (l8s, l8e) == ac.l8w_window()
    assert (lws, lwe) == ac.last_completed_week()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "endpoint",
    [opo.team_performance, opo.team_weekly_performance, opo.team_performance_by_team],
    ids=["panel", "weekly-modal", "team-modal"],
)
async def test_attrition_ignores_the_date_filter_at_every_site(endpoint):
    """No attrition statement may carry the page's range params.

    Its windows are fixed completed ISO weeks; binding a date range would make
    a "Last Month" click silently redefine the metric. Driven with a range that
    is NOT the default so a leaked bound is visibly wrong.

    All three sites, not one: fixing only the panel would leave the two modals
    showing the old metric under the same label.
    """
    pool = await _drive(endpoint, range="last_month", start_date=None, end_date=None)
    calls = [(s, p) for s, p in pool.calls if "l8w_weekly" in s]
    assert calls, f"{endpoint.__name__} emitted no attrition query"
    expected = (*ac.l8w_window(), *ac.last_completed_week())
    for _sql, params in calls:
        assert tuple(params[-4:]) == expected, (
            f"{endpoint.__name__}: attrition window is not the fixed completed-week pair"
        )


def test_per_team_attrition_full_outer_joins_so_a_dead_team_survives():
    """A team with an 8-week history and a silent last week must still appear.

    An INNER JOIN deletes exactly the row a reader most needs — 100% attrition
    would render as a MISSING LINE, not as a red number (§91, §75).
    """
    sql, _ = performance._attrition_query(
        lambda pr: _v4_scope_where(
            "br4", None, None, None, pr, None, None, None, None, scope=CORP_SCOPE
        ),
        group_col="TRIM(br4.team_id)",
    )
    norm = _norm(sql)
    assert "FULL OUTER JOIN" in norm
    assert re.search(r"\bl8w\b\s+FULL OUTER JOIN\s+\blw\b", norm)
    assert "grp" in norm


def test_dfw_attrition_groups_by_the_dfw_team_column():
    """Under DFW the sub-team lives in `team`, not the constant `team_id`."""
    sql, _ = performance._attrition_query(
        lambda pr: _v4_scope_where(
            "br4", None, None, None, pr, None, None, None, None, scope=DFW_SCOPE
        ),
        group_col=f"TRIM(br4.{DFW_SCOPE.v4_team_col})",
    )
    assert "TRIM(br4.team)" in sql
    assert "TRIM(br4.team_id)" not in sql
    # ⚠ Never `TRIM(<alias> AS team_id)` — 42601 (§81).
    assert " AS team_id" not in sql


# ---------------------------------------------------------------------------
# R4 — the three MTD display rows
# ---------------------------------------------------------------------------


def test_mtd_display_window_is_month_start_to_yesterday():
    """Bruno: "if today is August 31 … include data through August 30 at 11:59 PM"."""
    for today, expected in (
        (date(2026, 8, 31), (date(2026, 8, 1), date(2026, 8, 30))),
        (date(2026, 8, 1),  (date(2026, 8, 1), date(2026, 7, 31))),  # empty, not the future
        (date(2026, 3, 1),  (date(2026, 3, 1), date(2026, 2, 28))),
    ):
        _, params, p_ms, p_ye = _metrics._mtd_display_params(
            None, None, None, None, None, None, None, today, scope=CORP_SCOPE
        )
        assert (params[p_ms - 1], params[p_ye - 1]) == expected, today
        # ⚠ Today must NEVER be in the window.
        assert params[p_ye - 1] < today, today


def test_mtd_display_reuses_the_projections_yesterday_bound():
    """The display rows and the projection window must share one definition."""
    today = date(2026, 8, 31)
    _, win_end, m_start, _, _ = _metrics._projection_bounds(today)
    _, params, p_ms, p_ye = _metrics._mtd_display_params(
        None, None, None, None, None, None, None, today, scope=CORP_SCOPE
    )
    assert params[p_ye - 1] == win_end
    assert params[p_ms - 1] == m_start


def test_mtd_volume_uses_the_reports_house_volume_definition():
    """"Volume" means charge-bearing orders EVERYWHERE in this report (§69).

    A bare COUNT(*) reads ~22 higher and would stop reconciling with both
    Monthly Performance's "Volume" and the Proj. Volume leg directly below it.
    """
    sql = _metrics._mtd_display_sql("W", 1, 2)
    norm = _norm(sql)
    assert "COUNT(*) FILTER (WHERE br4.origin_actual_departure::date BETWEEN $1 AND $2 AND br4.total_charge IS NOT NULL AND br4.total_charge <> 0) AS mtd_volume" in norm
    # Revenue/Profit deliberately carry NO charge guard — they are sums.
    assert "THEN br4.total_charge END), 0)::numeric AS mtd_revenue" in norm
    assert "THEN br4.margin_amt END), 0)::numeric AS mtd_profit" in norm


def test_mtd_display_is_opt_in_and_never_touches_the_shared_projection_sql():
    """§69's byte-identity guard must stay intact.

    `test_ops_portal_projection` asserts /team-projection, /combo and /actuals
    emit the SAME projection statement. Folding display columns into
    `_projection_sums_sql` breaks that for no gain — this pins the separation.
    """
    src = inspect.getsource(_metrics._projection_sums_sql)
    for leaked in ("mtd_volume", "mtd_revenue", "mtd_profit", "with_mtd_display"):
        assert leaked not in src, f"{leaked} leaked into the shared projection SQL"


@pytest.mark.asyncio
async def test_team_projection_serves_the_mtd_rows_and_actuals_does_not():
    """Only the panel that renders them pays for them."""
    tp = await _drive(opo.team_projection, range=None, start_date=None, end_date=None)
    ac_pool = await _drive(opo.actuals, range="mtd", start_date=None, end_date=None,
                           losses_only=False, unbilled_only=False)
    assert any("mtd_volume" in s for s, _ in tp.calls), "/team-projection lost the MTD rows"
    assert not any("mtd_volume" in s for s, _ in ac_pool.calls), (
        "/actuals is paying for display columns it does not render"
    )


# ---------------------------------------------------------------------------
# R6 — the losses pair must span one population
# ---------------------------------------------------------------------------

# Every site that prints a negative-margin COUNT beside a negative-margin SUM.
# Fixing one and not the others makes the panels disagree with each other
# instead of with the Margin-distribution tile (§96).
_LOSS_PAIR_MODULES = (
    "app/routers/ops_portal_overview/performance.py",
    "app/routers/ops_portal_overview/actuals.py",
    "app/routers/ops_portal_overview/variance.py",
)


def _repo_file(rel: str) -> str:
    from pathlib import Path

    return (Path(__file__).resolve().parents[1] / rel).read_text()


def test_every_negative_margin_sum_carries_the_total_charge_guard():
    """`margin_amt < 0` must never be summed without the charge guard.

    Scanned over WHOLE FILES, not line by line — the predicate is split across
    lines at every one of these sites, and a line-based check would report a
    clean sweep while the bug sat there.
    """
    offenders: list[str] = []
    for rel in _LOSS_PAIR_MODULES:
        text = _repo_file(rel)
        # Every SUM(...) over a negative margin, in either the FILTER or the
        # CASE WHEN spelling.
        for m in re.finditer(
            r"SUM\(\s*(?:br4\.)?margin_amt\s*\)\s*FILTER\s*\(\s*WHERE(.{0,400}?)\)"
            r"|SUM\(\s*CASE\s+WHEN(.{0,400}?)THEN\s+(?:br4\.)?margin_amt\s+END\s*\)",
            text,
            re.S,
        ):
            pred = m.group(1) or m.group(2) or ""
            if "margin_amt < 0" not in pred:
                continue
            if "total_charge <> 0" not in pred:
                offenders.append(f"{rel}: {_norm(pred)[:120]}")
    assert not offenders, "negative-margin sum without the total_charge guard:\n" + "\n".join(offenders)


def test_loss_count_and_loss_sum_appear_the_same_number_of_times():
    """A count and a sum are added in pairs; a new site must bring both guards."""
    for rel in _LOSS_PAIR_MODULES:
        text = _repo_file(rel)
        counts = len(re.findall(r"AS loss_loads", text))
        sums = len(re.findall(r"AS (?:profit_loss|loss_profit)", text))
        assert counts == sums, f"{rel}: {counts} loss counts vs {sums} loss sums"


def test_the_guard_text_is_not_merely_present_but_inside_the_predicate():
    """Mutation check: a `total_charge <> 0` sitting elsewhere must not pass.

    Without this, someone could satisfy the sweep above by leaving the guard in
    a neighbouring clause — the test would go green while the sum stayed wrong.
    """
    good = "COALESCE(SUM(margin_amt) FILTER (WHERE margin_amt < 0\n AND total_charge IS NOT NULL\n AND total_charge <> 0), 0)"
    bad = "COALESCE(SUM(margin_amt) FILTER (WHERE margin_amt < 0), 0) -- total_charge <> 0"

    def sweep(text: str) -> list[str]:
        out = []
        for m in re.finditer(
            r"SUM\(\s*margin_amt\s*\)\s*FILTER\s*\(\s*WHERE(.{0,400}?)\)", text, re.S
        ):
            pred = m.group(1)
            if "margin_amt < 0" in pred and "total_charge <> 0" not in pred:
                out.append(pred)
        return out

    assert sweep(good) == []
    assert sweep(bad), "the sweep would miss a guard left outside the predicate"
