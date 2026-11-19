"""Ops Portal Updates PDF (2026-11-18) — the "Info" modal + equal Row 2.

R1    Row 2 (New Customer / Deactivated · Service Incident · By Carrier) is
      three EQUAL columns — its own `xl:grid-cols-3` grid, the Service pair
      spanning two of them with the same gap, so each panel is one column.
R2-4  Monthly Performance / Monthly Projection / Budget Monthly Variance:
      the "Week" + "Team" buttons became ONE "Info" button. The modal keeps
      the Week matrix, adds an internal Team filter and Day / Week / Month
      toggles (Week default): last 12 days / 8 weeks / 8 months.

What fails SILENTLY here, and is therefore pinned:
  * a clone router (CEO, DFW, CORP T1-T4, DFW TM1-4) that does not forward
    `grain` — FastAPI drops the param and the modal shows weeks under a
    "Month" toggle (§40). Pinned on EVERY registered route, not by name.
  * a bucket key that does not normalise to its anchor — the period renders
    as all zeros next to a fetched row.
"""

from __future__ import annotations

import inspect
from datetime import date
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.routers.ops_portal_overview import _dates, performance, projection, variance
from app.routers.ops_portal_overview._dates import (
    INFO_PERIODS,
    _info_bucket_end,
    _info_bucket_of,
    _info_buckets,
    _info_label,
    _info_trunc_sql,
)

USER = {"sub": "probe", "email": "probe@example.com", "roles": ["admin"]}
TODAY = date(2026, 11, 19)  # a Thursday
FRONT = Path(__file__).resolve().parents[2] / "frontend"
OPP = FRONT / "app" / "reports" / "ops-portal-overview"

ENDPOINTS = {
    "team-weekly-performance": performance.team_weekly_performance,
    "team-projection-weekly": projection.team_projection_weekly,
    "team-variance-weekly": variance.team_variance_weekly,
}


# ---------------------------------------------------------------------------
# Buckets
# ---------------------------------------------------------------------------


def test_period_counts_match_the_request():
    assert INFO_PERIODS == {"day": 12, "week": 8, "month": 8}
    for grain, n in INFO_PERIODS.items():
        anchors, start, end = _info_buckets(grain, TODAY)
        assert len(anchors) == n
        assert anchors == sorted(anchors)
        assert start == anchors[0]
        assert end == _info_bucket_end(grain, anchors[-1])
        # The current, partial period is always the last column.
        assert _info_bucket_of(grain, TODAY) == anchors[-1]


def test_day_grain_is_the_last_12_calendar_days():
    anchors, start, end = _info_buckets("day", TODAY)
    assert start == date(2026, 11, 8) and end == TODAY
    assert [(b - a).days for a, b in zip(anchors, anchors[1:])] == [1] * 11


def test_week_grain_is_8_mon_sun_weeks():
    anchors, start, end = _info_buckets("week", TODAY)
    assert all(a.weekday() == 0 for a in anchors)
    assert start == date(2026, 9, 28)
    assert end == date(2026, 11, 22)  # Sunday of the current week


def test_month_grain_crosses_the_year_boundary():
    anchors, start, end = _info_buckets("month", date(2027, 2, 10))
    assert [a.month for a in anchors] == [7, 8, 9, 10, 11, 12, 1, 2]
    assert all(a.day == 1 for a in anchors)
    assert start == date(2026, 7, 1)
    assert end == date(2027, 2, 28)  # whole month: the budget leg is a whole-period goal (§92)


def test_labels():
    assert _info_label("day", date(2026, 11, 8)) == "08/11"
    assert _info_label("week", date(2026, 11, 16)) == "16/11 - 22/11"
    assert _info_label("month", date(2026, 11, 1)) == "Nov 2026"


def test_trunc_sql_is_whitelisted():
    assert _info_trunc_sql("month", "x.d") == "DATE_TRUNC('month', x.d)::date"
    for bad in ("year", "week'); DROP TABLE x; --", None):
        with pytest.raises(ValueError):
            _info_trunc_sql(bad, "x.d")
        with pytest.raises(ValueError):
            _info_buckets(bad, TODAY)


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


class _Pool:
    """Records statements; returns one canned row per `fetch`."""

    def __init__(self, rows):
        self.rows = rows
        self.sqls: list[str] = []
        self.params: list[tuple] = []

    async def fetch(self, sql, *params):
        self.sqls.append(sql)
        self.params.append(params)
        return self.rows

    async def fetchrow(self, sql, *params):
        self.sqls.append(sql)
        self.params.append(params)
        return None


def _request(pool):
    state = SimpleNamespace(savings_pool=pool, pool=pool)
    return SimpleNamespace(app=SimpleNamespace(state=state), headers={}, query_params={})


async def _call(endpoint, pool, grain):
    args = {"request": _request(pool)}
    for name in inspect.signature(endpoint).parameters:
        if name == "request":
            continue
        args[name] = USER if name.startswith("_") else None
    args["grain"] = grain
    try:
        return await endpoint(**args)
    except (TypeError, KeyError, AttributeError):
        return None  # the canned row lacks some column; SQL is captured


@pytest.fixture
def frozen(monkeypatch):
    for mod in (performance, projection, variance):
        monkeypatch.setattr(mod, "cst_today", lambda: TODAY)


@pytest.mark.asyncio
@pytest.mark.parametrize("path", sorted(ENDPOINTS))
@pytest.mark.parametrize("grain", ["day", "week", "month"])
async def test_every_endpoint_buckets_on_the_requested_grain(frozen, path, grain):
    pool = _Pool([])
    await _call(ENDPOINTS[path], pool, grain)
    sql = "\n".join(pool.sqls)
    assert f"DATE_TRUNC('{grain}', br4.origin_actual_departure)::date" in sql
    others = {"day", "week", "month"} - {grain}
    for g in others:
        assert f"DATE_TRUNC('{g}', br4.origin_actual_departure)" not in sql
    _, start, end = _info_buckets(grain, TODAY)
    flat = [p for ps in pool.params for p in ps]
    assert start in flat and end in flat, f"{path}/{grain}: window bounds not bound"


@pytest.mark.asyncio
async def test_variance_budget_leg_buckets_on_its_own_date_column(frozen):
    pool = _Pool([])
    await _call(variance.team_variance_weekly, pool, "month")
    sql = "\n".join(pool.sqls)
    assert 'DATE_TRUNC(\'month\', budget."Date")::date' in sql


@pytest.mark.asyncio
@pytest.mark.parametrize("grain", ["day", "week", "month"])
async def test_projection_rows_land_in_their_period(frozen, grain):
    anchors, _, _ = _info_buckets(grain, TODAY)
    # A datetime-ish key mid-period must still normalise to the anchor.
    row = {"wk": anchors[-2], "vol": 10, "rev": 1000, "prof": 100, "team_count": 1}
    out = await _call(projection.team_projection_weekly, _Pool([row]), grain)
    data = out["data"]
    assert data["grain"] == grain
    periods = data["periods"]
    assert data["weeks"] is periods  # legacy alias
    assert len(periods) == INFO_PERIODS[grain]
    assert periods[-2]["proj_volume"] == 10
    assert periods[-1]["proj_volume"] == 0
    assert periods[-2]["label"] == _info_label(grain, anchors[-2])


@pytest.mark.asyncio
async def test_variance_month_row_keyed_on_the_first_lands_in_its_month(frozen):
    anchors, _, _ = _info_buckets("month", TODAY)
    row = {
        "wk": anchors[0], "active_customers": 3,
        "loads_budget": 10, "loads_actual": 12,
        "revenue_budget": 100, "revenue_actual": 150,
        "profit_budget": 10, "profit_actual": 20,
    }
    out = await _call(variance.team_variance_weekly, _Pool([row]), "month")
    periods = out["data"]["periods"]
    assert len(periods) == 8
    assert periods[0]["volume_var"] == 2
    assert periods[0]["label"] == _info_label("month", anchors[0])
    assert periods[1]["volume_var"] == 0


def test_every_endpoint_defaults_to_week_and_validates_grain():
    for path, fn in ENDPOINTS.items():
        p = inspect.signature(fn).parameters["grain"]
        assert p.default.default == "week", path
        assert _dates.INFO_GRAIN_PATTERN in repr(p.default.metadata), path


# ---------------------------------------------------------------------------
# §40 — every clone must forward `grain`
# ---------------------------------------------------------------------------


def test_every_registered_info_route_declares_grain():
    """Walk the LIVE app: every route ending in one of the three Info paths
    (CORP, T1-T4, DFW, TM1-4, CEO /{division}) must accept `grain`. A wrapper
    that omits it serves weeks under every toggle and raises nothing."""
    from app.main import app

    hits = []
    for r in app.routes:
        path = getattr(r, "path", "")
        if any(path.endswith("/" + p) for p in ENDPOINTS):
            hits.append(path)
            assert "grain" in inspect.signature(r.endpoint).parameters, path
    # CORP + 4 CORP teams + DFW + 4 DFW TMs + CEO for perf/projection;
    # variance has no DFW legs. Fewer means a portal lost its Info modal.
    assert len(hits) >= 25, sorted(hits)


@pytest.mark.parametrize(
    "module",
    ["ops_portal_overview_ceo", "ops_portal_overview_dfw",
     "ops_portal_overview_team", "ops_portal_overview_dfw_team"],
)
def test_every_clone_wrapper_passes_grain_through(module):
    src = (Path(__file__).resolve().parents[1] / "app" / "routers" / f"{module}.py").read_text()
    for fn in ("team_weekly_performance", "team_projection_weekly", "team_variance_weekly"):
        head = f"async def {fn}("
        if head not in src:
            continue
        body = src.split(head, 1)[1].split("\n    @r.", 1)[0].split("\n@r.", 1)[0]
        assert "grain=grain" in body, f"{module}.{fn} declares but does not forward grain"


# ---------------------------------------------------------------------------
# Frontend guards (no JS test runner — read the TSX, §107)
# ---------------------------------------------------------------------------


def _tsx(name: str) -> str:
    return (OPP / name).read_text()


@pytest.mark.parametrize(
    "panel",
    ["MonthlyPerformancePanel.tsx", "MonthlyProjectionPanel.tsx", "BudgetMonthlyVariancePanel.tsx"],
)
def test_panels_show_one_info_button_not_week_and_team(panel):
    src = _tsx(panel)
    assert "<InfoButton" in src or "InfoButtons" in src, panel
    assert ">\n            Week\n" not in src and ">Week<" not in src, panel
    assert ">\n              Team\n" not in src and ">Team<" not in src, panel
    assert "WeekTeamButtons" not in src, panel


def test_info_controls_offer_day_week_month_with_week_default():
    src = _tsx("InfoControls.tsx")
    for label in ('"Day"', '"Week"', '"Month"'):
        assert label in src
    assert 'useState<InfoGrain>("week")' in src


@pytest.mark.parametrize(
    "hook", ["useOppTeamWeekly", "useOppTeamProjectionWeekly", "useOppTeamVarianceWeekly"],
)
def test_info_hooks_send_grain_and_key_on_it(hook):
    """`grain` must reach the querystring AND the queryKey — without the key,
    Day/Month toggles silently re-read the Week cache entry."""
    src = (FRONT / "lib" / "ops-portal-overview-api.ts").read_text()
    body = src.split(f"export function {hook}(", 1)[1].split("\nexport ", 1)[0]
    assert 'grain: InfoGrain = "week"' in body, hook
    key = body.split("queryKey:", 1)[1].split("\n", 1)[0]
    assert "grain" in key, f"{hook}: grain missing from queryKey"
    assert "{ grain }" in body.split("queryFn:", 1)[1], f"{hook}: grain not sent"


def test_by_team_modals_are_gone():
    assert not (OPP / "TeamMonthlyModal.tsx").exists()
    for panel in ("MonthlyProjectionPanel.tsx", "BudgetMonthlyVariancePanel.tsx"):
        assert "TeamModal" not in _tsx(panel), panel


def test_row2_is_three_equal_columns():
    src = _tsx("OverviewPanelGrid.tsx")
    assert "ROW2_GRID_CLS" in src
    assert "xl:grid-cols-3" in src.split("ROW2_GRID_CLS =", 1)[1].split("\n\n", 1)[0]
    assert 'className="xl:col-span-2"' in src
