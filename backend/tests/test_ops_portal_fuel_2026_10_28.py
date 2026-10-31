"""KPI MANAGEMENT chart — R1a default toggles + R1b "Fuel" measure (2026-10-31).

(a) Overlays start HIDDEN: BDGT, Avg. LQ, Projected, Losses. Only the measure
    bars are on; the Variance tooltip row follows the BDGT chip.
(b) ``GET /fuel`` — EIA weekly retail diesel ($/gal) from modern_pricing_portal,
    bucketed on /combo's buckets: week exact, month = AVG of the month's weeks
    (+ forecast for future months), day = the week's value carried. The change
    is computed on the full weekly series BEFORE windowing. Fail soft: no pool,
    a revoked GRANT, any error → success with empty points + ``unavailable``.

No JS test runner in this repo: the frontend guards read the TSX (§107).
"""

from __future__ import annotations

import asyncio
import importlib
import inspect
import re
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import asyncpg
import pytest

from app.routers import ops_portal_overview as opo
from app.routers import ops_portal_overview_ceo as ceo
from app.routers import ops_portal_overview_dfw as dfw
from app.routers import ops_portal_overview_team as team_mod
from app.routers.ops_portal_overview._dates import _resolve_grain_window
from app.services import ai_chat_tools

# ⚠ `opo.fuel` is the ENDPOINT (the façade re-exports the function under the
# module's own name), so the module is reached through importlib.
fuel_mod = importlib.import_module("app.routers.ops_portal_overview.fuel")

TODAY = date(2026, 10, 31)  # a Saturday
USER = {"sub": "probe", "email": "probe@example.com", "roles": ["admin"]}
FRONT = Path(__file__).resolve().parents[2] / "frontend"
OPO_DIR = FRONT / "app" / "reports" / "ops-portal-overview"
FETCHED = datetime(2026, 10, 26, 15, 0, tzinfo=timezone.utc)


def _row(code: str, period: date, value: float, name: str | None = None) -> dict:
    return {"region_code": code, "region_name": name or code, "period": period, "value": value}


# Four NUS Mondays straddling Sep/Oct + one region, the shape the table has.
WEEKLY = [
    _row("NUS", date(2026, 9, 28), 6.382, "U.S. National"),
    _row("NUS", date(2026, 10, 5), 6.199, "U.S. National"),
    _row("NUS", date(2026, 10, 12), 6.179, "U.S. National"),
    _row("NUS", date(2026, 10, 19), 6.276, "U.S. National"),
    _row("R20", date(2026, 10, 12), 6.000, "Midwest"),
    _row("R20", date(2026, 10, 19), 6.100, "Midwest"),
]
FORECAST = [
    {"region_code": "NUS", "period": date(2026, 11, 1), "value": 6.31},
    {"region_code": "R20", "period": date(2026, 11, 1), "value": 6.12},
    {"region_code": "NUS", "period": date(2026, 12, 1), "value": 6.25},
]


class _Pool:
    def __init__(self, weekly=None, forecast=None, raise_exc: Exception | None = None) -> None:
        self.calls: list[tuple[str, tuple]] = []
        self.weekly = WEEKLY if weekly is None else weekly
        self.forecast = FORECAST if forecast is None else forecast
        self.raise_exc = raise_exc

    async def fetch(self, sql, *params):
        self.calls.append((sql, params))
        if self.raise_exc:
            raise self.raise_exc
        return self.forecast if "fuel_diesel_forecast" in sql else self.weekly

    async def fetchrow(self, sql, *params):
        self.calls.append((sql, params))
        if self.raise_exc:
            raise self.raise_exc
        return {"latest_period": date(2026, 10, 19), "fetched_at": FETCHED}


def _request(pool):
    state = SimpleNamespace() if pool is None else SimpleNamespace(pricing_pool=pool)
    return SimpleNamespace(app=SimpleNamespace(state=state), state=SimpleNamespace(), headers={})


def _run(monkeypatch, grain="month", pool="default", **kw):
    monkeypatch.setattr(fuel_mod, "cst_today", lambda: TODAY)
    pool = _Pool() if pool == "default" else pool
    res = asyncio.run(opo.fuel(request=_request(pool), grain=grain, start=kw.get("start"),
                               end=kw.get("end"), _user=USER))
    return res, pool


def _by_bucket(res) -> dict:
    return {p["bucket_start"]: p for p in res["data"]["points"]}


# ---------------------------------------------------------------------------
# Grain shaping
# ---------------------------------------------------------------------------


def test_week_grain_is_exact_and_buckets_align_with_combo(monkeypatch):
    res, _ = _run(monkeypatch, grain="week")
    anchors = _resolve_grain_window("week", TODAY)[2]
    assert [p["bucket_start"] for p in res["data"]["points"]] == [a.isoformat() for a in anchors]
    p = _by_bucket(res)["2026-10-19"]
    assert p["values"] == {"NUS": 6.276, "R20": 6.1}
    assert p["period"] == "2026-10-19"
    # The current week (10-26) is not loaded yet: empty, not carried forward.
    assert _by_bucket(res)["2026-10-26"]["values"] == {}


def test_wow_is_computed_on_the_full_series_before_windowing(monkeypatch):
    res, pool = _run(monkeypatch, grain="week")
    p = _by_bucket(res)
    assert p["2026-10-19"]["wow"] == {"NUS": 0.097, "R20": 0.1}
    assert p["2026-10-05"]["wow"] == {"NUS": -0.183}
    # The weekly read starts BEFORE the first bucket so it has a predecessor.
    weekly_params = next(prm for sql, prm in pool.calls if "fuel_diesel_weekly" in sql and prm)
    first = _resolve_grain_window("week", TODAY)[2][0]
    assert weekly_params[0] <= first - timedelta(days=7)


def test_month_grain_averages_the_months_weeks_and_mom(monkeypatch):
    res, _ = _run(monkeypatch, grain="month")
    oct_ = _by_bucket(res)["2026-10-01"]
    assert oct_["values"]["NUS"] == round((6.199 + 6.179 + 6.276) / 3, 3)
    assert oct_["values"]["R20"] == 6.05
    assert oct_["wow"]["NUS"] == round(oct_["values"]["NUS"] - 6.382, 3)
    assert "R20" not in oct_["wow"], "no September R20 ⇒ no MoM"
    assert res["data"]["change_basis"] == "mom"


def test_month_grain_forecast_is_future_months_only(monkeypatch):
    res, pool = _run(monkeypatch, grain="month")
    fc = res["data"]["forecast"]
    assert [f["bucket_start"] for f in fc] == ["2026-11-01", "2026-12-01"]
    assert fc[0]["values"] == {"NUS": 6.31, "R20": 6.12}
    sql, params = next((s, p) for s, p in pool.calls if "fuel_diesel_forecast" in s)
    assert "period > $1" in sql and params[0] == date(2026, 10, 1)
    assert "DISTINCT ON (region_code, period)" in sql


@pytest.mark.parametrize("grain", ["day", "week"])
def test_no_forecast_query_below_month(monkeypatch, grain):
    res, pool = _run(monkeypatch, grain=grain)
    assert res["data"]["forecast"] == []
    assert not any("fuel_diesel_forecast" in s for s, _ in pool.calls)


def test_day_grain_carries_the_weeks_value_to_each_day(monkeypatch):
    res, _ = _run(monkeypatch, grain="day")
    p = _by_bucket(res)
    for d in range(19, 26):
        pt = p[f"2026-10-{d}"]
        assert pt["values"]["NUS"] == 6.276 and pt["period"] == "2026-10-19"
        assert pt["wow"]["NUS"] == 0.097
    assert p["2026-10-26"]["values"] == {}
    assert len(res["data"]["points"]) == len(_resolve_grain_window("day", TODAY)[2])


def test_explicit_window_overrides_the_default(monkeypatch):
    res, _ = _run(monkeypatch, grain="week", start=date(2026, 10, 7), end=date(2026, 10, 20))
    assert [p["bucket_start"] for p in res["data"]["points"]] == ["2026-10-05", "2026-10-12", "2026-10-19"]


def test_regions_follow_the_registry_and_freshness_is_reported(monkeypatch):
    res, _ = _run(monkeypatch)
    codes = [r["code"] for r in res["data"]["regions"]]
    assert codes == ["NUS", "R1X", "R1Y", "R1Z", "R20", "R30", "R40", "R50", "SCA"]
    assert res["data"]["freshness"] == {"latest_period": "2026-10-19", "fetched_at": FETCHED.isoformat()}
    assert res["data"]["unavailable"] is None


# ---------------------------------------------------------------------------
# Fail soft — never a 500, never breaks the bars
# ---------------------------------------------------------------------------


def _assert_soft(res):
    assert res["success"] is True
    assert res["data"]["points"] == [] and res["data"]["forecast"] == []
    assert res["data"]["unavailable"]


def test_missing_pool_fails_soft(monkeypatch):
    res, _ = _run(monkeypatch, pool=None)
    _assert_soft(res)


def test_revoked_grant_fails_soft_and_logs(monkeypatch, caplog):
    exc = asyncpg.InsufficientPrivilegeError("permission denied for table fuel_diesel_weekly")
    with caplog.at_level("ERROR"):
        res, _ = _run(monkeypatch, pool=_Pool(raise_exc=exc))
    _assert_soft(res)
    assert "fuel query failed" in caplog.text


def test_any_error_fails_soft(monkeypatch):
    res, _ = _run(monkeypatch, pool=_Pool(raise_exc=RuntimeError("boom")))
    _assert_soft(res)


def test_the_sql_reads_only_the_two_granted_tables():
    for sql in (fuel_mod.WEEKLY_SQL, fuel_mod.FRESHNESS_SQL, fuel_mod.FORECAST_SQL):
        tables = set(re.findall(r"public\.(\w+)", sql))
        assert tables <= {"fuel_diesel_weekly", "fuel_diesel_forecast"}


# ---------------------------------------------------------------------------
# Gate + mirrors
# ---------------------------------------------------------------------------


def _gate_key(fn) -> str:
    dep = inspect.signature(fn).parameters["_user"].default.dependency
    cells = [c.cell_contents for c in (dep.__closure__ or ())]
    keys = next(c for c in cells if isinstance(c, tuple))
    assert len(keys) == 1, keys
    return keys[0]


def test_the_corp_endpoint_is_behind_the_report_gate():
    assert _gate_key(opo.fuel) == "ops-portal-overview"


def test_fuel_is_mirrored_in_every_clone_with_its_own_gate():
    team_routers = {slug: team_mod._make_team_router(t, slug, role) for t, slug, role in team_mod.TEAM_CONFIGS}
    for slug, r in team_routers.items():
        route = next(x for x in r.routes if x.path.endswith("/fuel"))
        assert _gate_key(route.endpoint) == f"corp-{slug}-ops-kam-portal"
    dfw_route = next(x for x in dfw.r.routes if x.path.endswith("/fuel"))
    assert _gate_key(dfw_route.endpoint) == dfw.REPORT_KEY
    ceo_route = next(x for x in ceo.r.routes if x.path.endswith("/fuel"))
    assert "/{division}/fuel" in ceo_route.path
    assert _gate_key(ceo_route.endpoint) == ceo.REPORT_KEY


def test_every_clone_forwards_every_param():
    want = set(inspect.signature(opo.fuel).parameters) - {"_user"}
    shims = [next(x for x in dfw.r.routes if x.path.endswith("/fuel")).endpoint,
             next(x for x in ceo.r.routes if x.path.endswith("/fuel")).endpoint]
    r = team_mod._make_team_router(*team_mod.TEAM_CONFIGS[0])
    shims.append(next(x for x in r.routes if x.path.endswith("/fuel")).endpoint)
    for fn in shims:
        assert want <= set(inspect.signature(fn).parameters)
    for src in ("ops_portal_overview_team.py", "ops_portal_overview_dfw.py", "ops_portal_overview_ceo.py"):
        text = (Path(team_mod.__file__).parent / src).read_text()
        assert "opo.fuel(request=request, grain=grain, start=start, end=end, _user=_user)" in text


def test_the_ai_assistant_section_is_decided():
    assert "fuel" in ai_chat_tools.SECTION_ALLOWLIST


# ---------------------------------------------------------------------------
# Frontend source guards
# ---------------------------------------------------------------------------


def _src(name: str) -> str:
    return (OPO_DIR / name).read_text()


def test_fuel_pill_follows_service():
    labels = re.findall(r'\{ k: "(\w+)",\s+label: "([^"]+)"', _src("Chart.tsx"))
    keys = [k for k, _ in labels]
    assert keys[:7] == ["volume", "revenue", "profit", "margin_pct", "customers", "service", "fuel"]


def test_default_hidden_set_is_every_overlay_but_the_bars():
    src = _src("Chart.tsx")
    m = re.search(r"const DEFAULT_HIDDEN: readonly SeriesKey\[\] = \[([^\]]*)\]", src)
    assert m, "DEFAULT_HIDDEN constant missing"
    assert set(re.findall(r'"(\w+)"', m.group(1))) == {"budget", "avgLq", "projected", "losses"}
    assert "useState<Set<SeriesKey>>(() => new Set(DEFAULT_HIDDEN))" in src
    assert "useState(false)" in src.split("const [forecast, setForecast] =", 1)[1][:40], "Forecast stays off"


def test_variance_row_follows_the_budget_chip():
    src = _src("Chart.tsx")
    assert '{ key: "budget" as SeriesKey, label: "Variance"' in src
    assert '{ key: "variance" as SeriesKey, label: "Variance"' not in src


def test_fuel_never_parses_a_date_only_string_as_utc():
    for name in ("FuelSeries.tsx", "FuelTooltip.tsx", "fuelChartData.ts"):
        assert not re.search(r"new Date\(\s*[a-zA-Z_\"`]", _src(name)), name
    assert "parseLocalDate" in _src("fuelChartData.ts")


def test_fuel_query_key_covers_every_param():
    api = (FRONT / "lib" / "ops-portal-overview-api.ts").read_text()
    body = api.split("export function useOppFuel", 1)[1].split("\n}\n", 1)[0]
    assert 'queryKey: [prefix, "opp-fuel", grain]' in body
    assert "new URLSearchParams({ grain })" in body


def test_fuel_caption_says_it_is_market_data():
    assert "not filtered by team/customer/lane" in _src("FuelSeries.tsx")


def test_chart_line_cap_still_holds():
    assert len(_src("Chart.tsx").splitlines()) <= 991
