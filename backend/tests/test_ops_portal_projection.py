"""Projected is ONE number (Bruno PDF 2026-08-14 R6).

Four formulas used to ship under that name. The KPI chart's month projection
read a 14-calendar-day window while the Team Monthly Projection panel beside it
read 12 business days; replayed against live data on 2026-08-14 that was
$2,668,146 vs $2,950,709 revenue on the same screen.

These tests pin the fix at the level that actually broke: the SQL each consumer
emits. A future edit that reintroduces a private formula fails here rather than
silently putting two different "Projected" values in front of the reader.
"""

from __future__ import annotations

import re
from datetime import date
from types import SimpleNamespace

import pytest

from app.routers import ops_portal_overview as opo

USER = {"sub": "probe", "email": "probe@example.com", "roles": ["admin"]}


class _RecordingPool:
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


def _projection_queries(pool) -> list[tuple[str, tuple]]:
    """Every emitted statement that computes the projection sums."""
    return [(s, p) for s, p in pool.calls if "vol_12" in s and "prof_mtd" in s]


SCOPE = dict(
    team=None, customer=None, load_type=None, lanes=None,
    exclude_lanes=None, carriers=None, exclude_carriers=None,
)


async def _drive(endpoint, **kw):
    pool = _RecordingPool()
    try:
        await endpoint(request=_request(pool), _user=USER, **kw)
    except Exception:
        # The stub returns empty results; downstream arithmetic may raise.
        # What we assert on is the SQL emitted before that point.
        pass
    return pool


@pytest.mark.asyncio
async def test_team_projection_combo_and_actuals_emit_identical_projection_sql():
    """The report-wide projection query must be byte-identical everywhere."""
    tp = await _drive(opo.team_projection, **SCOPE)
    cb = await _drive(opo.combo, grain="month", **SCOPE)
    ac = await _drive(opo.actuals, range="mtd", start_date=None, end_date=None,
                      losses_only=False, unbilled_only=False, **SCOPE)

    def global_query(pool):
        qs = [(s, p) for s, p in _projection_queries(pool) if "GROUP BY" not in s]
        assert len(qs) == 1, f"expected exactly one report-wide projection query, got {len(qs)}"
        return _norm(qs[0][0]), qs[0][1]

    tp_sql, tp_params = global_query(tp)
    cb_sql, cb_params = global_query(cb)
    ac_sql, ac_params = global_query(ac)

    assert tp_sql == cb_sql, "KPI chart projection SQL drifted from Team Monthly Projection"
    assert tp_sql == ac_sql, "Actuals projection SQL drifted from Team Monthly Projection"
    assert tp_params == cb_params == ac_params, "same SQL, different window/scope params"


@pytest.mark.asyncio
async def test_combo_no_longer_uses_a_14_calendar_day_window():
    """The old private formula divided by 14 over a calendar window."""
    cb = await _drive(opo.combo, grain="month", **SCOPE)
    for sql, _ in cb.calls:
        assert "vol_14" not in sql, "combo still emits its own 14-day projection"


@pytest.mark.asyncio
async def test_actuals_emits_a_per_customer_projection_grouped_the_same_way():
    """Per-row Proj. EOM must be grouped on the same key the rows are."""
    ac = await _drive(opo.actuals, range="mtd", start_date=None, end_date=None,
                      losses_only=False, unbilled_only=False, **SCOPE)
    grouped = [s for s, _ in _projection_queries(ac) if "GROUP BY" in s]
    assert len(grouped) == 1
    assert "br4.customer_name AS grp" in grouped[0]
    assert "GROUP BY br4.customer_name" in _norm(grouped[0])


def test_projection_is_linear_so_rows_sum_to_the_total():
    """§16 KPI = detail.

    Proj = (sum_12 / 12) * pending + sum_mtd is linear in its sums, so the
    per-customer rows add up to the report-wide total exactly. Verified against
    live data on 2026-08-14: 154 customers summed to 503,304.50 profit and
    1,476.50 volume — the same figures the report-wide query returns.
    """
    pending, teams = 15, 5
    parts = [
        (674 * 0.4, 1298793 * 0.5, 219818 * 0.3, 634 * 0.6, 1327218 * 0.2, 228532 * 0.7),
        (674 * 0.6, 1298793 * 0.5, 219818 * 0.7, 634 * 0.4, 1327218 * 0.8, 228532 * 0.3),
    ]
    rows = [opo._projection_from_sums(*p, pending, 1) for p in parts]
    total = opo._projection_from_sums(
        *[sum(p[i] for p in parts) for i in range(6)], pending, teams
    )
    for key in ("proj_volume", "proj_revenue", "proj_profit"):
        assert sum(r[key] for r in rows) == pytest.approx(total[key], rel=1e-9)


def test_pending_workdays_excludes_sundays_only():
    """Mon-Sat, holidays not excluded — Bruno's literal round-2 spec."""
    # 2026-08-14 is a Friday; Aug has 31 days.
    assert opo._count_workdays(date(2026, 8, 14), date(2026, 8, 31)) == 15
    # The 12-business-day lookback ends yesterday and skips Sundays.
    assert opo._last_n_business_days_start(date(2026, 8, 14), 12) == date(2026, 7, 31)
