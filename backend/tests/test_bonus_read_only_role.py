"""Bonus Calculator — the Financial (``CFO``) TagRole is VIEW-ONLY (2026-11-03).

Request: the Financial role reads payroll in both calculators but never writes
it. HR Manager / OPs Manager / admin / CEO keep write access. Every write route
(roster, afterhours, FX settings, lock / unlock) must sit behind the WRITE gate,
and every read route behind the plain report gate — a new write route added
with ``Depends(gate)`` fails ``test_every_write_route_uses_the_write_gate``.
"""
from __future__ import annotations

import pytest
from fastapi import HTTPException
from fastapi.routing import APIRoute

import app.routers.bonus_calculator as bc
import app.routers.deps as deps

WRITE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}
GRANTS = frozenset({"admin", "ceo", "cfo", "hr manager", "ops manager"})


def _gate_names(route: APIRoute) -> set[str]:
    return {getattr(d.call, "__qualname__", "") for d in route.dependant.dependencies}


@pytest.mark.parametrize("router", [bc.router, bc.dfw_router], ids=["corp", "dfw"])
def test_every_write_route_uses_the_write_gate(router) -> None:
    writes = [r for r in router.routes if isinstance(r, APIRoute) and r.methods & WRITE_METHODS]
    assert len(writes) == 9  # roster ×3, afterhours ×3, settings, lock, unlock
    for route in writes:
        names = _gate_names(route)
        assert "require_report_write.<locals>._check" in names, (route.path, route.methods)
        assert "require_report_access.<locals>._check" not in names, (route.path, route.methods)


@pytest.mark.parametrize("router", [bc.router, bc.dfw_router], ids=["corp", "dfw"])
def test_read_routes_keep_the_read_gate(router) -> None:
    reads = [r for r in router.routes if isinstance(r, APIRoute) and not r.methods & WRITE_METHODS]
    assert reads
    for route in reads:
        assert "require_report_access.<locals>._check" in _gate_names(route), route.path


def test_the_financial_role_is_the_read_only_one() -> None:
    assert bc.BONUS_READ_ONLY_ROLES == frozenset({"cfo"})


@pytest.fixture
def grants(monkeypatch):
    async def _allowed(_pool, _key):
        return GRANTS

    monkeypatch.setattr(deps, "get_allowed_roles_for_report", _allowed)
    monkeypatch.setattr(deps, "get_pool", lambda _req: None)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("roles", "can_write"),
    [
        (["CFO"], False),
        (["CFO", "Finance"], False),          # Finance does not grant the report
        (["CFO", "Executive"], False),
        (["HR Manager"], True),
        (["OPs Manager"], True),
        (["CFO", "HR Manager"], True),        # another granted role still writes
        (["admin"], True),
        (["CEO"], True),
        (["Finance"], False),
    ],
)
async def test_write_rule(grants, roles, can_write) -> None:
    user = {"roles": roles}
    got = await deps.user_can_write_report(None, user, "bonus-calculator", bc.BONUS_READ_ONLY_ROLES)
    assert got is can_write
    gate = deps.require_report_write("bonus-calculator", bc.BONUS_READ_ONLY_ROLES)
    if can_write:
        assert await gate(request=None, user=user) is user
    else:
        with pytest.raises(HTTPException) as exc:
            await gate(request=None, user=user)
        assert exc.value.status_code == 403
        assert "view-only" in exc.value.detail
