"""New Customer / Deactivated panel — Bruno PDF "Ops Portal Updates" 2026-11-17 R3.

Pins (no database):
* the two RULES, via the pure-Python reference, including the case that made
  Diego choose window-entry over the PDF's literal wording (HILTI: first-ever
  load in the window, shipped twice, must still be "new");
* the SQL shape — window params for ``new``, today for ``deactivated``, the
  charged-load population, the 1900 sentinel guard, lanes/carriers ignored;
* the route on EVERY portal family (a missing clone shim is a silent 404 on
  that portal, §40), and the frontend wiring.
"""

from __future__ import annotations

import importlib
import pathlib
from datetime import date, timedelta

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.routers import deps as deps_mod
from app.routers.ops_portal_overview import activity as ca

Load = ca.Load
FRONTEND = pathlib.Path(__file__).resolve().parents[2] / "frontend"
START, END = date(2026, 11, 1), date(2026, 11, 17)


# ---------------------------------------------------------------------------
# The rules
# ---------------------------------------------------------------------------


def test_first_ever_customer_stays_new_after_its_second_load() -> None:
    """The HILTI case: the literal 'two most recent dates' rule drops it."""
    loads = [Load("HILTI", date(2026, 11, 3)), Load("HILTI", date(2026, 11, 10))]
    assert ca.new_customers_reference(loads, START, END) == ["HILTI"]


def test_returning_after_long_silence_is_new() -> None:
    loads = [Load("PCA", date(2026, 5, 1)), Load("PCA", date(2026, 11, 5)), Load("PCA", date(2026, 11, 6))]
    assert ca.new_customers_reference(loads, START, END) == ["PCA"]


@pytest.mark.parametrize("gap,expected", [(75, []), (76, ["X"])])
def test_silence_threshold_is_strictly_greater_than_75(gap: int, expected: list) -> None:
    first_in = date(2026, 11, 5)
    loads = [Load("X", first_in - timedelta(days=gap)), Load("X", first_in)]
    assert ca.new_customers_reference(loads, START, END) == expected


def test_regular_customer_is_not_new_and_absent_one_is_not_listed() -> None:
    loads = [Load("REG", date(2026, 10, 28)), Load("REG", date(2026, 11, 2)), Load("GONE", date(2026, 1, 1))]
    assert ca.new_customers_reference(loads, START, END) == []


def test_deactivated_profit_is_last_ten_trips_and_threshold_strict() -> None:
    today = date(2026, 11, 17)
    old = [Load("OLD", date(2026, 8, 1) - timedelta(days=i), margin=100.0 + i) for i in range(12)]
    edge = [Load("EDGE", today - timedelta(days=75))]
    out = ca.deactivated_reference(old + edge, today)
    assert set(out) == {"OLD"}
    assert out["OLD"] == sum(100.0 + i for i in range(10))


# ---------------------------------------------------------------------------
# SQL shape (stub pool)
# ---------------------------------------------------------------------------


class _StubPool:
    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple]] = []

    async def fetch(self, sql, *params):
        self.calls.append((sql, params))
        return []


def _client(monkeypatch, router, extra_modules=()):
    pool = _StubPool()
    for name in ("app.routers.ops_portal_overview.activity", *extra_modules):
        m = importlib.import_module(name)
        if hasattr(m, "get_datalake_gold_pool"):
            monkeypatch.setattr(m, "get_datalake_gold_pool", lambda request, _p=pool: _p)
    monkeypatch.setattr(ca, "cst_today", lambda: date(2026, 11, 17))
    app = FastAPI()
    app.include_router(router, prefix="/api")
    app.dependency_overrides[deps_mod.require_user] = lambda: {"sub": "t", "roles": ["admin"]}
    return TestClient(app), pool


def _corp(monkeypatch):
    from app.routers import ops_portal_overview as opo
    return _client(monkeypatch, opo.router)


def test_new_binds_the_window_and_ignores_lane_and_carrier_filters(monkeypatch) -> None:
    client, pool = _corp(monkeypatch)
    res = client.get("/api/custom/ops-portal-overview/customer-activity", params={
        "kind": "new", "range": "custom", "start_date": "2026-11-01", "end_date": "2026-11-17",
        "lanes": "LAREDO - DALLAS", "carriers": "ACME", "load_type": "spot",
    })
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["success"] and body["meta"]["kind"] == "new"
    assert body["meta"]["window"] == {"start": "2026-11-01", "end": "2026-11-17"}
    (sql, params), = pool.calls
    flat = repr(params)
    assert "LAREDO" not in flat and "ACME" not in flat and "spot" not in flat
    assert date(2026, 11, 1) in params and date(2026, 11, 17) in params
    assert "total_charge <> 0" in sql and "> '2000-01-01'" in sql
    assert f"> {ca.SILENCE_DAYS}" in sql


def test_deactivated_ignores_the_window_and_binds_today(monkeypatch) -> None:
    client, pool = _corp(monkeypatch)
    res = client.get("/api/custom/ops-portal-overview/customer-activity",
                     params={"kind": "deactivated", "range": "mtd"})
    assert res.status_code == 200, res.text
    assert res.json()["meta"]["window"] is None
    (sql, params), = pool.calls
    assert params[-1] == date(2026, 11, 17)
    assert f"rn <= {ca.LAST_TRIPS}" in sql and "HAVING" in sql


def test_unknown_kind_falls_back_to_new(monkeypatch) -> None:
    client, _ = _corp(monkeypatch)
    res = client.get("/api/custom/ops-portal-overview/customer-activity", params={"kind": "x"})
    assert res.json()["meta"]["kind"] == "new"


# ---------------------------------------------------------------------------
# Every portal family serves it
# ---------------------------------------------------------------------------


def _paths(router) -> set[str]:
    return {r.path for r in router.routes}


def test_every_ops_portal_family_registers_customer_activity() -> None:
    from app.routers import ops_portal_overview as opo
    from app.routers import ops_portal_overview_ceo as ceo
    from app.routers import ops_portal_overview_dfw as dfw
    from app.routers import ops_portal_overview_dfw_team as dfw_team
    from app.routers import ops_portal_overview_team as team

    assert any(p.endswith("/customer-activity") for p in _paths(opo.router))
    assert any(p.endswith("/customer-activity") for p in _paths(dfw.r))
    assert any(p.endswith("/{division}/customer-activity") for p in _paths(ceo.r))
    for r in (*team.team_routers, *dfw_team.team_routers):
        assert any(p.endswith("/customer-activity") for p in _paths(r)), r.prefix


def test_ai_assistant_section_is_decided() -> None:
    from app.services import ai_chat_tools
    assert "customer-activity" in ai_chat_tools.SECTION_ALLOWLIST


# ---------------------------------------------------------------------------
# Frontend wiring (no JS test runner — read the TSX)
# ---------------------------------------------------------------------------


def test_panel_sits_left_of_service_incident_in_the_grid() -> None:
    grid = (FRONTEND / "app/reports/ops-portal-overview/OverviewPanelGrid.tsx").read_text()
    assert grid.index("<CustomerActivityPanel") < grid.index("<ServiceIncidentTables")
    panel = (FRONTEND / "app/reports/ops-portal-overview/CustomerActivityPanel.tsx").read_text()
    assert '"New Customer"' in panel and '"Deactivated"' in panel
    api = (FRONTEND / "lib/ops-portal-overview-api.ts").read_text()
    assert "/customer-activity" in api


def test_customers_bars_label_returning_new_and_bold_total() -> None:
    src = (FRONTEND / "app/reports/ops-portal-overview/CustomersSeries.tsx").read_text()
    assert 'dataKey="returning_customers"' in src
    assert "fontWeight" in src  # the bold Customers total on top


def test_fuel_labels_the_us_national_line() -> None:
    src = (FRONTEND / "app/reports/ops-portal-overview/FuelSeries.tsx").read_text()
    assert "NATIONAL_CODE" in src and "LabelList" in src
