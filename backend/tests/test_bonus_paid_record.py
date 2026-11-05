"""Approved bonus months keep the figures HR paid from (2026-11-05).

Daniela Nava, 2026-11-05: "amounts to be paid are from space calculator". Space
recomputed every month from live loads, so a locked month kept moving after it
was paid (Aug: paid $504.08 per person, live $501.28). The CIO approved storing
the whole report at Approve, going forward only: this reverses R16's "no
report-JSON freeze".

These tests drive the real endpoints against an in-memory hub. The SQL itself was
rehearsed on real Postgres temp tables, because a stub cannot prove it parses.
"""

from __future__ import annotations

import asyncio
import inspect
import json
import re
import types
from pathlib import Path

import pytest
from fastapi import HTTPException
from fastapi.routing import APIRoute

from app.routers import bonus_calculator as bc
from app.routers import bonus_paid_record as bpr

SCOPES = [bc.CORP_SCOPE, bc.DFW_SCOPE]
ROUTERS = {"corp": bc.router, "dfw": bc.dfw_router}
PERIOD = "2026-10"
USER = {"email": "hr@example.com"}


class _Hub:
    """In-memory hub: the lock rows and stored reports of ONE scope."""

    def __init__(self, scope) -> None:
        self.scope = scope
        self.locks: dict[str, dict] = {}
        self.snapshots: list[dict] = []
        self.fail_snapshot_insert = False

    # -- pool surface -----------------------------------------------------
    async def fetchval(self, sql, *params):
        assert self.scope.tbl_lock in sql, sql
        lock = self.locks.get(params[0])
        return 1 if lock and lock["status"] == "approved" else None

    async def fetchrow(self, sql, *params):
        if self.scope.tbl_paid in sql:
            return self._latest_record(params[0])
        return None

    async def execute(self, sql, *params):
        assert sql.strip().startswith("DELETE"), sql
        assert self.scope.tbl_lock in sql, sql
        self.locks.pop(params[0], None)

    def acquire(self):
        return _Acquire(self)

    # -- connection surface ----------------------------------------------
    async def conn_fetchrow(self, sql, *params):
        assert "ON CONFLICT" in sql and self.scope.tbl_lock in sql, sql
        # The approved guard must be in the SQL: this row is the race arbiter.
        assert "<> 'approved'" in sql, sql
        lock = self.locks.get(params[0])
        if lock and lock["status"] == "approved":
            return None
        self.locks[params[0]] = {"status": "approved", "approved_by": params[1], "approved_at": _NOW}
        return {"period_key": params[0]}

    async def conn_execute(self, sql, *params):
        assert self.scope.tbl_paid in sql, sql
        if self.fail_snapshot_insert:
            raise RuntimeError("insert failed")
        self.snapshots.append(
            {"period_key": params[0], "report_json": params[1], "approved_by": params[2]}
        )

    def _latest_record(self, period_key: str):
        lock = self.locks.get(period_key)
        if not lock or lock["status"] != "approved":
            return None
        rows = [s for s in self.snapshots if s["period_key"] == period_key]
        if not rows:
            return None
        return {
            "report_json": rows[-1]["report_json"],
            "status": lock["status"],
            "approved_by": lock["approved_by"],
            "approved_at": lock["approved_at"],
        }


class _FakeNow:
    def isoformat(self) -> str:
        return "2026-11-09T15:00:00+00:00"


_NOW = _FakeNow()


class _Conn:
    def __init__(self, hub: _Hub) -> None:
        self.hub = hub

    async def fetchrow(self, sql, *params):
        return await self.hub.conn_fetchrow(sql, *params)

    async def execute(self, sql, *params):
        return await self.hub.conn_execute(sql, *params)

    def transaction(self):
        return _Txn(self.hub)


class _Acquire:
    def __init__(self, hub: _Hub) -> None:
        self.hub = hub

    async def __aenter__(self):
        return _Conn(self.hub)

    async def __aexit__(self, *exc):
        return False


class _Txn:
    """Restores both tables on an exception, as a real transaction does."""

    def __init__(self, hub: _Hub) -> None:
        self.hub = hub

    async def __aenter__(self):
        self.saved = (dict(self.hub.locks), list(self.hub.snapshots))
        return self

    async def __aexit__(self, exc_type, exc, tb):
        if exc_type is not None:
            self.hub.locks, self.hub.snapshots = self.saved
        return False


class _Live:
    """The live calculator: `grand` moves when a load is re-rated."""

    def __init__(self) -> None:
        self.grand = 1000.0
        self.loads = 100
        self.down = False

    async def build(self, gold, primary, financial, period, scope) -> dict:
        if self.down:
            raise RuntimeError("gold down")
        return {
            "source": "McLeod TMS — live datalake (aivn_datalake_gold)",
            "teams": [{"id": scope.teams[0], "totalBonusUsd": self.grand, "monthlyLoads": self.loads}],
            "totals": {"grandBonusUsd": self.grand},
            "period": {"key": PERIOD, "label": "October 2026"},
            "lock": {"status": "open", "approvedBy": None, "approvedAt": None},
        }


@pytest.fixture(params=SCOPES, ids=lambda s: s.key)
def env(request, monkeypatch):
    scope = request.param
    hub, live = _Hub(scope), _Live()
    monkeypatch.setattr(bc, "get_pool", lambda _r: hub)
    monkeypatch.setattr(bpr, "get_pool", lambda _r: hub)
    monkeypatch.setattr(bc, "get_datalake_gold_pool", lambda _r: object())
    monkeypatch.setattr(bc, "build_bonus_report_data", live.build)
    return types.SimpleNamespace(scope=scope, hub=hub, live=live, router=ROUTERS[scope.key])


def _endpoint(router, suffix: str, method: str):
    for route in router.routes:
        if isinstance(route, APIRoute) and route.path.endswith(suffix) and method in route.methods:
            return route.endpoint
    raise AssertionError(f"no {method} {suffix}")


_REQUEST = types.SimpleNamespace(app=types.SimpleNamespace(state=types.SimpleNamespace()))


def _get_report(env) -> dict:
    fn = _endpoint(env.router, "/report", "GET")
    return asyncio.run(fn(request=_REQUEST, period=PERIOD, _user=USER))["data"]


def _approve(env, reviewed: float | None = None) -> dict:
    """Approve what the screen shows: the live total, unless a test says otherwise."""
    body = bc.LockBody(
        period_key=PERIOD,
        reviewed_total_usd=env.live.grand if reviewed is None else reviewed,
    )
    fn = _endpoint(env.router, "/lock", "POST")
    return asyncio.run(fn(request=_REQUEST, body=body, user=USER))


def _unlock(env) -> dict:
    fn = _endpoint(env.router, "/lock/{period_key}", "DELETE")
    return asyncio.run(fn(request=_REQUEST, period_key=PERIOD, user=USER))


def test_an_open_month_is_served_live_and_carries_no_new_field(env) -> None:
    data = _get_report(env)
    assert data["totals"]["grandBonusUsd"] == 1000.0
    # Byte-identical to before: nothing changes until a month is approved.
    assert "approvedRecord" not in data


def test_a_month_locked_before_this_feature_stays_live(env) -> None:
    """Go forward only: no stored row means live figures, never invented ones."""
    env.hub.locks[PERIOD] = {"status": "approved", "approved_by": "hr", "approved_at": _NOW}
    env.live.grand = 1234.0
    data = _get_report(env)
    assert data["totals"]["grandBonusUsd"] == 1234.0
    assert "approvedRecord" not in data


def test_approving_stores_the_report_and_locks_together(env) -> None:
    assert _approve(env) == {"success": True, "data": {"stored": True}}
    assert env.hub.locks[PERIOD]["approved_by"] == USER["email"]
    assert len(env.hub.snapshots) == 1
    stored = json.loads(env.hub.snapshots[0]["report_json"])
    assert stored["totals"]["grandBonusUsd"] == 1000.0


def test_an_approved_month_keeps_its_figures_when_loads_move(env) -> None:
    _approve(env)
    env.live.grand = 997.2
    data = _get_report(env)
    assert data["totals"]["grandBonusUsd"] == 1000.0
    assert data["teams"][0]["totalBonusUsd"] == 1000.0
    record = data["approvedRecord"]
    assert record["approvedTotalUsd"] == 1000.0
    assert record["liveTotalUsd"] == 997.2
    assert record["differenceUsd"] == -2.8
    assert record["approvedBy"] == USER["email"]


def test_the_served_report_says_it_is_stored_and_locked(env) -> None:
    """The stored JSON says lock=open and 'live datalake'; neither may reach the screen."""
    _approve(env)
    data = _get_report(env)
    assert data["lock"]["status"] == "approved"
    assert data["lock"]["approvedBy"] == USER["email"]
    assert "live datalake" not in data["source"].lower()


def test_a_failed_build_leaves_no_lock_and_no_record(env) -> None:
    env.live.down = True
    with pytest.raises(HTTPException) as exc:
        _approve(env)
    assert exc.value.status_code == 503
    assert "not" in exc.value.detail.lower()
    assert env.hub.locks == {}
    assert env.hub.snapshots == []


def test_a_failed_snapshot_insert_rolls_the_lock_back(env) -> None:
    env.hub.fail_snapshot_insert = True
    with pytest.raises(RuntimeError):
        _approve(env)
    assert env.hub.locks == {}
    assert env.hub.snapshots == []


def test_approving_an_approved_month_changes_nothing(env) -> None:
    """A double click must not store today's figures over the approved ones."""
    _approve(env)
    env.live.grand = 500.0
    assert _approve(env) == {"success": True, "data": {"stored": False}}
    assert len(env.hub.snapshots) == 1
    assert _get_report(env)["totals"]["grandBonusUsd"] == 1000.0


def test_approving_a_month_locked_before_this_feature_stores_nothing(env) -> None:
    """Otherwise a stray Approve would label today's figures as what was paid."""
    env.hub.locks[PERIOD] = {"status": "approved", "approved_by": "hr", "approved_at": _NOW}
    assert _approve(env) == {"success": True, "data": {"stored": False}}
    assert env.hub.snapshots == []
    assert env.hub.locks[PERIOD]["approved_by"] == "hr"


def test_unlock_returns_the_month_to_live_and_keeps_the_record(env) -> None:
    _approve(env)
    env.live.grand = 1100.0
    assert _unlock(env) == {"success": True}
    data = _get_report(env)
    assert data["totals"]["grandBonusUsd"] == 1100.0
    assert "approvedRecord" not in data
    assert len(env.hub.snapshots) == 1, "the audit trail must survive an unlock"


def test_re_approving_adds_a_row_and_serves_the_new_figures(env) -> None:
    _approve(env)
    _unlock(env)
    env.live.grand = 1100.0
    _approve(env)
    assert len(env.hub.snapshots) == 2
    assert _get_report(env)["totals"]["grandBonusUsd"] == 1100.0


def test_approving_refuses_figures_that_moved_since_the_screen_loaded(env) -> None:
    """HR reviewed $1,000; the fresh build says $997.20. Neither gets stored."""
    env.live.grand = 997.2
    with pytest.raises(HTTPException) as exc:
        _approve(env, reviewed=1000.0)
    assert exc.value.status_code == 409
    assert "$997.20" in exc.value.detail and "$1,000.00" in exc.value.detail
    assert env.hub.locks == {} and env.hub.snapshots == []


def test_approving_tolerates_float_noise_below_a_cent(env) -> None:
    env.live.grand = 1000.0000001
    assert _approve(env, reviewed=1000.0)["data"]["stored"] is True


def test_approving_refuses_an_empty_read(env) -> None:
    """Zero loads builds a confident $0 without raising anything."""
    env.live.grand, env.live.loads = 0.0, 0
    with pytest.raises(HTTPException) as exc:
        _approve(env, reviewed=0.0)
    assert exc.value.status_code == 503
    assert env.hub.locks == {} and env.hub.snapshots == []


@pytest.mark.parametrize("bad", ["2026-1", "", "2026-13", "x"])
def test_a_malformed_period_cannot_be_approved(bad: str) -> None:
    """A lock under `2026-1` answers success while `/report` reads `2026-01`."""
    with pytest.raises(ValueError):
        bc.LockBody(period_key=bad, reviewed_total_usd=1.0)


def test_the_record_query_ties_a_record_to_its_own_lock() -> None:
    """The stub picks rows in Python, so the SQL itself is pinned here."""
    src = inspect.getsource(bpr.load_approved_record)
    assert "ORDER BY s.id DESC" in src
    assert "l.status = 'approved'" in src
    assert "l.approved_at = s.approved_at" in src


def test_a_stored_engine_report_stops_claiming_to_be_live(env) -> None:
    """The toy report has no dataSource; run a real engine report through instead."""
    from test_bonus_scope import _report

    real = _report()
    total = real["totals"]["grandBonusUsd"]
    assert real["dataSource"]["status"] == "draft"

    async def build(*_a) -> dict:
        return {**real, "lock": {"status": "open"}, "period": {"key": PERIOD}}

    env.live.grand = total
    bc.build_bonus_report_data, original = build, bc.build_bonus_report_data
    try:
        real["teams"][0]["monthlyLoads"] = 5
        _approve(env)
        data = _get_report(env)
    finally:
        bc.build_bonus_report_data = original
    assert data["dataSource"]["status"] == "Approved"
    assert "live" not in data["dataSource"]["lastSyncLabel"].lower()
    assert data["totals"]["grandBonusUsd"] == total
    assert data["dataSource"]["mode"] == real["dataSource"]["mode"]


def test_a_hung_gold_does_not_hold_the_approved_figures_hostage(env, monkeypatch) -> None:
    _approve(env)
    monkeypatch.setattr(bpr, "LIVE_COMPARISON_TIMEOUT_S", 0.01)

    async def hang(*_a):
        await asyncio.sleep(5)

    monkeypatch.setattr(bc, "build_bonus_report_data", hang)
    data = _get_report(env)
    assert data["totals"]["grandBonusUsd"] == 1000.0
    assert data["approvedRecord"]["liveTotalUsd"] is None


@pytest.mark.parametrize("scope", SCOPES, ids=lambda s: s.key)
def test_history_freezes_an_approved_month_at_its_approved_figures(scope, monkeypatch) -> None:
    """The cutoff job builds live; approved early, History would disagree for good."""
    from app.services import bonus_history as bh

    class Pool:
        written: list = []

        async def fetchval(self, *_a):
            return None

        async def fetchrow(self, *_a):
            return {
                "report_json": json.dumps(
                    {"teams": [{"id": scope.teams[0], "name": "T", "monthlyProfit": 9, "teamBonusUsd": 1000.0}]}
                ),
                "status": "approved",
                "approved_by": "hr",
                "approved_at": _NOW,
            }

        async def executemany(self, _sql, rows):
            Pool.written.extend(rows)

    async def must_not_build(*_a):
        raise AssertionError("an approved month must not be rebuilt from live data")

    monkeypatch.setattr(bc, "_recent_period_keys", lambda _n: ["2026-09"])
    monkeypatch.setattr(bc, "build_bonus_report_data", must_not_build)
    state = types.SimpleNamespace(savings_pool=object(), pool=Pool(), financial_pool=None)
    result = asyncio.run(bh.finalize_due_periods(types.SimpleNamespace(state=state), scope))
    assert result["finalized"] == 1
    assert Pool.written[0][4] == 1000.0


def test_gold_down_still_serves_the_approved_figures(env) -> None:
    _approve(env)
    env.live.down = True
    data = _get_report(env)
    assert data["totals"]["grandBonusUsd"] == 1000.0
    assert data["approvedRecord"]["liveTotalUsd"] is None
    assert data["approvedRecord"]["differenceUsd"] is None


def test_gold_down_on_an_open_month_still_fails_loudly(env) -> None:
    env.live.down = True
    with pytest.raises(RuntimeError):
        _get_report(env)


def test_every_record_function_takes_a_required_scope() -> None:
    """A defaulted scope served the DFW page the corporate report for two weeks."""
    for fn in (bpr.load_approved_record, bpr.store_approval, bpr.report_for_display):
        param = inspect.signature(fn).parameters["scope"]
        assert param.default is inspect.Parameter.empty, fn.__name__


def test_the_record_module_never_names_a_table_literally() -> None:
    src = inspect.getsource(bpr)
    assert not re.search(r"\b(?:FROM|INTO|JOIN)\s+bonus_", src)
    assert "{scope.tbl_paid}" in src and "{scope.tbl_lock}" in src


def test_the_startup_schema_creates_one_table_per_calculator() -> None:
    main_src = (Path(__file__).parent.parent / "app" / "main.py").read_text()
    for scope in SCOPES:
        assert f"CREATE TABLE IF NOT EXISTS {scope.tbl_paid}" in main_src


def test_the_screen_tells_stored_figures_from_live_ones() -> None:
    root = Path(__file__).parent.parent.parent / "frontend"
    banner = (
        root / "app/reports/bonus-calculator/components/ApprovedRecordBanner.tsx"
    ).read_text()
    assert "approvedRecord" in banner
    assert "Approved figures" in banner and "Live figures" in banner
    assert "ApprovedRecordBanner" in (root / "components/BonusCalculatorContent.tsx").read_text()
    # Old stored reports and an old backend omit the field: it must be optional.
    assert re.search(r"approvedRecord\?:", (root / "lib/bonus-api.ts").read_text())
    # A one-click Approve would freeze payroll figures with no warning.
    editor = (root / "app/reports/bonus-calculator/components/RosterEditor.tsx").read_text()
    assert "window.confirm" in editor
    # Approve proves which total HR saw, and waits for FX edits to be saved.
    assert "reviewed_total_usd" in editor
    assert "fxUnsaved" in editor
