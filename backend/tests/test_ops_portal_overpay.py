"""Ops Portal "Over Pay" panel — Bruno "Ops Portal Updates" 2026-10-16 R4.

`/customer-overpay` replaces `/customer-not-billed` on all seven portals. It
recomputes the eSavings-from-Carriers over pay LIVE from v4 so it honours the
page's scope and filters; these tests pin the rules it borrows from the n8n
"Carriers Savings Update" workflow, the totals population (§44 / §96), and the
wrappers' §40 forwarding.

Live parity, measured 2026-10-16 for Sep-2026 (endpoint vs
`carriers_savings_results_report` SUM(variance < 0) per division):
CORP −84,510.37 vs −84,510.85 · DFW −104,853.47 vs −104,853.26.
Statement validity against real gold is covered by the PREPARE layer in
`test_ops_portal_dfw_sql_valid.py`, which drives every registered route.
"""

from __future__ import annotations

import asyncio
import inspect
import re
import types
from datetime import date

import pytest

from app.routers import ops_portal_overview as opo
from app.routers import ops_portal_overview_ceo as ceo
from app.routers import ops_portal_overview_dfw as dfw
from app.routers import ops_portal_overview_team as team_mod
from app.routers.ops_portal_overview import variance
from app.routers.ops_portal_overview._scope import CORP_SCOPE, DFW_SCOPE


class _Pool:
    def __init__(self, rows=None) -> None:
        self.calls: list[tuple[str, tuple]] = []
        self._rows = rows or []

    async def fetch(self, sql, *params):
        self.calls.append((sql, params))
        return self._rows


def _request(scope=None):
    state = types.SimpleNamespace()
    if scope is not None:
        state.opp_scope = scope
    return types.SimpleNamespace(
        state=state, app=types.SimpleNamespace(state=types.SimpleNamespace()),
    )


def _call(monkeypatch, rows=None, scope=None, **kw):
    pool = _Pool(rows)
    monkeypatch.setattr(variance, "get_datalake_gold_pool", lambda request: pool)
    args = dict(
        range="custom", start_date=date(2026, 9, 1), end_date=date(2026, 9, 30),
        team=None, customer=None, load_type=None, lanes=None, exclude_lanes=None,
        carriers=None, exclude_carriers=None, limit=100, _user={},
    )
    args.update(kw)
    res = asyncio.run(variance.customer_overpay(request=_request(scope), **args))
    return pool, res


def _sql(monkeypatch, **kw) -> tuple[str, tuple]:
    pool, _ = _call(monkeypatch, **kw)
    assert len(pool.calls) == 1
    return pool.calls[0]


def _norm(sql: str) -> str:
    return re.sub(r"\s+", " ", sql)


# ---------------------------------------------------------------------------
# The rules borrowed from the eSavings workflow
# ---------------------------------------------------------------------------


def test_it_applies_the_page_scope_and_window(monkeypatch) -> None:
    sql, params = _sql(monkeypatch, customer=["ACME", "BETA, INC"], carriers=["X"])
    s = _norm(sql)
    assert "br4.team_id = ANY(" in s and "br4.status = ANY(" in s
    # Multi-select Customer (Bruno PDF 2026-10-16 R2): the list binds whole.
    assert "br4.customer_name = ANY($" in s and ["ACME", "BETA, INC"] in params
    assert "br4.origin_actual_departure >= $" in s
    assert "INTERVAL '1 day'" in s
    assert date(2026, 9, 1) in params and date(2026, 9, 30) in params


def test_loads_under_201_are_excluded(monkeypatch) -> None:
    sql, params = _sql(monkeypatch)
    m = re.search(r"br4\.override_pay_amt >= \$(\d+)", sql)
    assert m, "the ≥ $201 carrier-pay floor is missing"
    assert params[int(m.group(1)) - 1] == 201


def test_the_lane_join_uses_the_whole_primary_key(monkeypatch) -> None:
    """(customer_id, origin_name, dest_name) is the PK — all three or it fans out."""
    s = _norm(_sql(monkeypatch)[0])
    assert "JOIN public.carriers_savings_results c" in s
    for col in ("customer_id", "origin_name", "dest_name"):
        assert f"c.{col} = br4.{col}" in s


def test_the_base_is_chosen_by_the_loads_month() -> None:
    case = _norm(variance._OVERPAY_BASE_CASE)
    assert "m >= DATE '2026-10-01' AND m < DATE '2027-01-01' THEN c.q4_base_lane" in case
    assert "m >= DATE '2026-07-01' AND m < DATE '2026-10-01' THEN c.q3_base_lane" in case
    assert "m >= DATE '2026-04-01' AND m < DATE '2026-07-01' THEN c.q2_base_lane" in case
    # Aug-2025..Mar-2026: base_lane, but never in the lane's own base month.
    assert "m >= DATE '2025-08-01' AND m < DATE '2026-04-01'" in case
    assert "c.base_month IS DISTINCT FROM to_char(m, 'YYYY-MM') THEN c.base_lane" in case
    # No fallback to base_lane for the quarters (feedback_carriers_savings_zero_base),
    # and nothing past Dec-2026 until the workflow grows a 2027 base.
    assert "ELSE NULL" in case
    assert "COALESCE" not in case
    assert "2027-01-01" in case and "q1_2027" not in case


def test_variance_is_per_lane_month_and_only_negative_counts(monkeypatch) -> None:
    s = _norm(_sql(monkeypatch)[0])
    assert "SUM(base - pay) FILTER (WHERE base > 0) AS var" in s
    assert "GROUP BY customer_name, customer_id, origin_name, dest_name, m" in s
    assert "SUM(var) FILTER (WHERE var < 0)" in s
    assert "ORDER BY over_pay ASC" in s


def test_the_totals_span_the_whole_filtered_set(monkeypatch) -> None:
    """§44: the totals select reads ALL customers, not the over-paid LIMIT slice."""
    s = _norm(_sql(monkeypatch)[0])
    totals_part, rows_part = s.split("UNION ALL")
    assert "FROM cust)" in totals_part
    assert "WHERE over_pay < 0" not in totals_part.split("FROM cust")[1]
    assert "WHERE over_pay < 0" in rows_part and "LIMIT $" in rows_part


def test_meta_totals_come_from_the_server_row_not_a_reduce(monkeypatch) -> None:
    rows = [
        {"is_total": True, "customer_name": None, "loads": 1000,
         "over_pay": -500.5, "customers": 2, "listed_loads": 30},
        {"is_total": False, "customer_name": "A", "loads": 10, "over_pay": -400.0,
         "customers": None, "listed_loads": None},
        {"is_total": False, "customer_name": "B", "loads": 20, "over_pay": -100.5,
         "customers": None, "listed_loads": None},
    ]
    _, res = _call(monkeypatch, rows=rows)
    assert res["success"] is True
    assert res["data"] == [
        {"customer_name": "A", "loads": 10, "over_pay": -400.0},
        {"customer_name": "B", "loads": 20, "over_pay": -100.5},
    ]
    assert res["meta"]["totals"] == {
        "loads": 1000, "over_pay": -500.5, "customers": 2, "listed_loads": 30,
    }
    assert res["meta"]["total"] == 2


def test_an_empty_scope_returns_zero_totals(monkeypatch) -> None:
    _, res = _call(monkeypatch, rows=[])
    assert res["data"] == []
    assert res["meta"]["totals"] == {
        "loads": 0, "over_pay": 0.0, "customers": 0, "listed_loads": 0,
    }


def test_dfw_scope_reads_the_dfw_division(monkeypatch) -> None:
    _, params = _sql(monkeypatch, scope=DFW_SCOPE)
    flat = [x for p in params if isinstance(p, list) for x in p]
    assert "TEAM-DFW" in flat
    assert "TEAM1" not in flat


# ---------------------------------------------------------------------------
# §40 — every wrapper forwards every param
# ---------------------------------------------------------------------------

_DISTINCT = dict(
    range="custom", start_date=date(2026, 9, 1), end_date=date(2026, 9, 30),
    customer="ACME", load_type="spot", lanes=["A - B"], exclude_lanes=["C - D"],
    carriers=["X"], exclude_carriers=["Y"], limit=7,
)


def _spy(monkeypatch) -> list[dict]:
    seen: list[dict] = []

    async def fake(**kw):
        seen.append(kw)
        return {"success": True, "data": []}

    monkeypatch.setattr(opo, "customer_overpay", fake)
    return seen


def _core_params() -> set[str]:
    return set(inspect.signature(variance.customer_overpay).parameters)


def _endpoint(router, suffix: str):
    hits = [r.endpoint for r in router.routes if r.path.endswith(suffix)]
    assert len(hits) == 1, f"{suffix} registered {len(hits)}x"
    return hits[0]


@pytest.mark.parametrize("router", team_mod.team_routers, ids=lambda r: r.prefix)
def test_team_clones_pin_team_and_forward_the_rest(monkeypatch, router) -> None:
    seen = _spy(monkeypatch)
    fn = _endpoint(router, "/customer-overpay")
    asyncio.run(fn(request=_request(CORP_SCOPE), _user={}, **_DISTINCT))
    (kw,) = seen
    assert set(kw) == _core_params()
    assert kw["team"]  # pinned by the factory, not taken from the query
    for k, v in _DISTINCT.items():
        assert kw[k] == v, k


def test_dfw_forwards_every_param(monkeypatch) -> None:
    seen = _spy(monkeypatch)
    fn = _endpoint(dfw.r, "/customer-overpay")
    asyncio.run(fn(request=_request(DFW_SCOPE), _user={}, team="TM1", **_DISTINCT))
    (kw,) = seen
    assert set(kw) == _core_params()
    assert kw["team"] == "TM1"
    for k, v in _DISTINCT.items():
        assert kw[k] == v, k


@pytest.mark.parametrize("scope,team", [(CORP_SCOPE, "TEAM2"), (DFW_SCOPE, "TM2")])
def test_ceo_forwards_every_param_under_both_divisions(monkeypatch, scope, team) -> None:
    seen = _spy(monkeypatch)
    fn = _endpoint(ceo.r, "/{division}/customer-overpay")
    asyncio.run(fn(request=_request(scope), _user={}, team=team, **_DISTINCT))
    (kw,) = seen
    assert set(kw) == _core_params()
    assert kw["team"] == team
    for k, v in _DISTINCT.items():
        assert kw[k] == v, k


def test_not_billed_is_gone_from_every_router() -> None:
    routers = [opo.router, dfw.r, ceo.r, *team_mod.team_routers]
    for router in routers:
        assert not any("customer-not-billed" in r.path for r in router.routes)
    assert not hasattr(opo, "customer_not_billed")
