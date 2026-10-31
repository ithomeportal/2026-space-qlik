"""Bonus Calculator — effective-dated roster + lock-guarded writes (2026-10-31).

🔴 Root cause: `bonus_roster` / `bonus_afterhours` (and the DFW twins) had no
period column, so EVERY month read EVERY row. A person HR added in October was
paid in every earlier month the moment anyone reopened it; a hard DELETE erased a
leaver from months they had worked; and "Locked · approved" was a label no write
ever checked.

Decision (Diego 2026-10-31): a write belongs to the period HR Settings is open on
and a write into an approved month is refused (409). These tests drive the REAL
endpoints against an in-memory, effective-dated pool and read back what each
month's loader returns — a property of the scope object is not proof (§7.1).
"""

from __future__ import annotations

import asyncio
import inspect
import re
import types
import uuid
from datetime import date

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from app.routers import bonus_calculator as bc
from app.routers import bonus_roster_writes as bw
from app.services import bonus_dfw_roster_sync as sync

SEP, OCT, NOV = date(2026, 9, 1), date(2026, 10, 1), date(2026, 11, 1)


# ---------------------------------------------------------------------------
# An in-memory hub DB that understands exactly the statements the module emits
# ---------------------------------------------------------------------------


class _Tx:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False


class _Acquire:
    def __init__(self, pool):
        self._pool = pool

    async def __aenter__(self):
        return self._pool

    async def __aexit__(self, *exc):
        return False


def _visible(row, first):
    return (row["effective_from"] is None or row["effective_from"] <= first) and (
        row["effective_to"] is None or row["effective_to"] >= first
    )


class _HubPool:
    def __init__(self) -> None:
        self.tables: dict[str, list[dict]] = {}
        self.locks: dict[str, dict[str, str]] = {}
        self.settings: dict[str, dict] = {}
        self.sql: list[str] = []

    # -- pool / connection protocol --------------------------------------
    def acquire(self):
        return _Acquire(self)

    def transaction(self):
        return _Tx()

    def seed(self, table, **row):
        full = {"id": uuid.uuid4(), "sort_order": 0, "effective_from": None, "effective_to": None, **row}
        self.tables.setdefault(table, []).append(full)
        return full["id"]

    def _table(self, sql):
        m = re.search(r"\b(?:FROM|INTO|UPDATE)\s+(bonus_\w+)", sql)
        return m.group(1)

    async def fetch(self, sql, *params):
        self.sql.append(sql)
        rows = self.tables.get(self._table(sql), [])
        assert "effective_from" in sql, "a roster read without the month filter"
        return sorted(
            (r for r in rows if _visible(r, params[0])),
            key=lambda r: (r.get("team_id", ""), r["sort_order"], r["employee_name"]),
        )

    async def fetchrow(self, sql, *params):
        self.sql.append(sql)
        tbl = self._table(sql)
        if sql.strip().startswith("SELECT *"):
            hit = next(
                (r for r in self.tables.get(tbl, []) if r["id"] == params[0] and _visible(r, params[1])),
                None,
            )
            return dict(hit) if hit else None  # a Record is a snapshot, not a live view
        if "INSERT" in sql:
            return {"id": self._insert(sql, tbl, params)}
        if "_lock" in tbl:
            return None
        return None

    async def fetchval(self, sql, *params):
        self.sql.append(sql)
        tbl = self._table(sql)
        if "MIN(period_key)" in sql:
            op = ">=" if ">=" in sql else "="
            keys = sorted(
                k for k, v in self.locks.get(tbl, {}).items()
                if v == "approved" and (k >= params[0] if op == ">=" else k == params[0])
            )
            return keys[0] if keys else None
        if "MAX(sort_order)" in sql:
            return len(self.tables.get(tbl, []))
        if "INSERT" in sql:
            return self._insert(sql, tbl, params)
        raise AssertionError(sql)

    async def execute(self, sql, *params):
        self.sql.append(sql)
        tbl = self._table(sql)
        verb = sql.strip().split()[0]
        if "_settings" in tbl:
            self.settings[params[0]] = {"team_fx": params[1]}
        elif verb == "INSERT":
            self._insert(sql, tbl, params)
        elif verb == "DELETE":
            self.tables[tbl] = [r for r in self.tables[tbl] if r["id"] != params[0]]
        elif verb == "UPDATE":
            cols = re.findall(r"(\w+) = \$(\d+)", sql.split("WHERE")[0])
            for r in self.tables[tbl]:
                if r["id"] == params[0]:
                    for col, idx in cols:
                        r[col] = params[int(idx) - 1]
        return "OK"

    def _insert(self, sql, tbl, params):
        cols = [c.strip() for c in re.search(r"\(([^)]*)\)\s*VALUES", sql, re.S).group(1).split(",")]
        row = {"id": uuid.uuid4(), "effective_from": None, "effective_to": None, **dict(zip(cols, params))}
        self.tables.setdefault(tbl, []).append(row)
        return row["id"]

    # -- helpers for assertions -----------------------------------------
    def roster_names(self, scope, first) -> list[str]:
        grouped = asyncio.run(bc._load_roster(_Filtered(self), first, scope))
        return sorted(e["name"] for emps in grouped.values() for e in emps)

    def after_names(self, scope, first) -> list[str]:
        return sorted(e["name"] for e in asyncio.run(bc._load_afterhours(_Filtered(self), first, scope)))


class _Filtered:
    """Reads through `_HubPool.fetch` (the month filter) whatever the subclass does."""

    def __init__(self, pool):
        self._pool = pool

    async def fetch(self, sql, *params):
        return await _HubPool.fetch(self._pool, sql, *params)


def _route(router, method: str, suffix: str):
    for r in router.routes:
        if method in getattr(r, "methods", ()) and r.path.endswith(suffix):
            return r.endpoint
    raise AssertionError(f"no {method} {suffix}")


def _call(pool, router, method, suffix, **kwargs):
    req = types.SimpleNamespace(app=types.SimpleNamespace(state=types.SimpleNamespace()))
    orig_w, orig_c = bw.get_pool, bc.get_pool
    bw.get_pool = bc.get_pool = lambda request: pool
    try:
        return asyncio.run(_route(router, method, suffix)(request=req, user={}, **kwargs))
    finally:
        bw.get_pool, bc.get_pool = orig_w, orig_c


SCOPES = [(bc.CORP_SCOPE, bc.router), (bc.DFW_SCOPE, bc.dfw_router)]


def _roster_body(scope, name="New Hire", salary=1000, period="2026-10"):
    return bc.RosterRow(team_id=scope.teams[0], name=name, role="kam", salary_mxn=salary, period_key=period)


# ---------------------------------------------------------------------------


@pytest.mark.parametrize("scope,router", SCOPES)
def test_a_row_added_in_p_is_absent_from_p_minus_1(scope, router) -> None:
    pool = _HubPool()
    pool.seed(scope.tbl_roster, team_id=scope.teams[0], employee_name="Old Timer", role="kam", salary_mxn=1)
    _call(pool, router, "POST", "/roster", body=_roster_body(scope))
    _call(pool, router, "POST", "/afterhours",
          body=bc.AfterhoursCreate(shift_group="Night Shift", name="Night Hire", salary_mxn=1, period_key="2026-10"))

    assert pool.roster_names(scope, SEP) == ["Old Timer"], "an October hire was paid in September"
    assert pool.roster_names(scope, OCT) == ["New Hire", "Old Timer"]
    assert pool.roster_names(scope, NOV) == ["New Hire", "Old Timer"]
    assert pool.after_names(scope, SEP) == []
    assert pool.after_names(scope, OCT) == ["Night Hire"]


@pytest.mark.parametrize("scope,router", SCOPES)
def test_a_delete_keeps_the_person_in_earlier_months(scope, router) -> None:
    pool = _HubPool()
    old = pool.seed(scope.tbl_roster, team_id=scope.teams[0], employee_name="Leaver", role="kam", salary_mxn=1)
    res = _call(pool, router, "DELETE", "/roster/{row_id}", row_id=old, period="2026-10")

    assert res["data"]["outcome"] == "closed"
    assert pool.roster_names(scope, SEP) == ["Leaver"], "a hard delete erased a month they worked"
    assert pool.roster_names(scope, OCT) == []
    assert pool.roster_names(scope, NOV) == []


@pytest.mark.parametrize("scope,router", SCOPES)
def test_a_row_that_starts_in_p_is_hard_deleted_in_p(scope, router) -> None:
    pool = _HubPool()
    _call(pool, router, "POST", "/roster", body=_roster_body(scope, name="Typo"))
    row_id = pool.tables[scope.tbl_roster][0]["id"]
    res = _call(pool, router, "DELETE", "/roster/{row_id}", row_id=row_id, period="2026-10")
    assert res["data"]["outcome"] == "deleted"
    assert pool.tables[scope.tbl_roster] == []


@pytest.mark.parametrize("scope,router", SCOPES)
def test_an_afterhours_delete_is_effective_dated_too(scope, router) -> None:
    pool = _HubPool()
    old = pool.seed(scope.tbl_afterhours, shift_group="Night Shift", employee_name="Night Leaver",
                    salary_mxn=1, receives_bonus=True)
    _call(pool, router, "DELETE", "/afterhours/{row_id}", row_id=old, period="2026-10")
    assert pool.after_names(scope, SEP) == ["Night Leaver"]
    assert pool.after_names(scope, OCT) == []


@pytest.mark.parametrize("scope,router", SCOPES)
def test_a_put_on_an_old_row_splits_it(scope, router) -> None:
    """Editing October must not rewrite September's pay."""
    pool = _HubPool()
    old = pool.seed(scope.tbl_roster, team_id=scope.teams[0], employee_name="Ana", role="kam",
                    salary_mxn=100, sort_order=3)
    res = _call(pool, router, "PUT", "/roster/{row_id}", row_id=old,
                body=_roster_body(scope, name="Ana", salary=999))

    rows = pool.tables[scope.tbl_roster]
    assert len(rows) == 2
    sep = asyncio.run(bc._load_roster(pool, SEP, scope))[scope.teams[0]]
    oct_ = asyncio.run(bc._load_roster(pool, OCT, scope))[scope.teams[0]]
    assert [e["salaryMxn"] for e in sep] == [100]
    assert [e["salaryMxn"] for e in oct_] == [999]
    assert res["data"]["id"] != str(old)
    new = next(r for r in rows if r["id"] != old)
    assert (new["effective_from"], new["sort_order"]) == (OCT, 3)


@pytest.mark.parametrize("scope,router", SCOPES)
def test_a_put_on_a_row_that_starts_in_p_updates_in_place(scope, router) -> None:
    pool = _HubPool()
    _call(pool, router, "POST", "/roster", body=_roster_body(scope, name="Bea", salary=1))
    row_id = pool.tables[scope.tbl_roster][0]["id"]
    _call(pool, router, "PUT", "/roster/{row_id}", row_id=row_id, body=_roster_body(scope, name="Bea", salary=2))
    assert [(r["employee_name"], r["salary_mxn"]) for r in pool.tables[scope.tbl_roster]] == [("Bea", 2)]


@pytest.mark.parametrize("scope,router", SCOPES)
def test_an_afterhours_put_on_an_old_row_splits_it(scope, router) -> None:
    pool = _HubPool()
    old = pool.seed(scope.tbl_afterhours, shift_group="Weekend Shift", employee_name="Wk",
                    salary_mxn=5, receives_bonus=True)
    _call(pool, router, "PUT", "/afterhours/{row_id}", row_id=old,
          body=bc.AfterhoursRow(name="Wk", salary_mxn=5, receives_bonus=False, period_key="2026-10"))
    sep = asyncio.run(bc._load_afterhours(pool, SEP, scope))
    oct_ = asyncio.run(bc._load_afterhours(pool, OCT, scope))
    assert [e["receivesBonus"] for e in sep] == [True]
    assert [(e["receivesBonus"], e["group"]) for e in oct_] == [(False, "Weekend Shift")]


# ---------------------------------------------------------------------------
# 🔴 Locked · approved now means something
# ---------------------------------------------------------------------------


def _locked_pool(scope, *keys):
    pool = _HubPool()
    pool.locks[scope.tbl_lock] = {k: "approved" for k in keys}
    return pool


@pytest.mark.parametrize("scope,router", SCOPES)
def test_every_write_to_a_locked_period_is_a_409(scope, router) -> None:
    pool = _locked_pool(scope, "2026-10")
    row = pool.seed(scope.tbl_roster, team_id=scope.teams[0], employee_name="X", role="kam", salary_mxn=1)
    ah = pool.seed(scope.tbl_afterhours, shift_group="Night Shift", employee_name="Y",
                   salary_mxn=1, receives_bonus=True)
    before = {t: [dict(r) for r in rows] for t, rows in pool.tables.items()}

    calls = [
        ("POST", "/roster", {"body": _roster_body(scope)}),
        ("PUT", "/roster/{row_id}", {"row_id": row, "body": _roster_body(scope, salary=5)}),
        ("DELETE", "/roster/{row_id}", {"row_id": row, "period": "2026-10"}),
        ("POST", "/afterhours", {"body": bc.AfterhoursCreate(
            shift_group="Night Shift", name="Z", salary_mxn=1, period_key="2026-10")}),
        ("PUT", "/afterhours/{row_id}", {"row_id": ah, "body": bc.AfterhoursRow(
            name="Y", salary_mxn=9, period_key="2026-10")}),
        ("DELETE", "/afterhours/{row_id}", {"row_id": ah, "period": "2026-10"}),
        ("PUT", "/settings", {"body": bc.FxSettings(period_key="2026-10", team_fx=18, night_fx=17)}),
    ]
    for method, path, kw in calls:
        with pytest.raises(HTTPException) as exc:
            _call(pool, router, method, path, **kw)
        assert exc.value.status_code == 409, (method, path)
        assert "October 2026 is Locked · approved — unlock it to edit" in exc.value.detail
    assert pool.tables == before, "a refused write still changed a row"
    assert pool.settings == {}


@pytest.mark.parametrize("scope,router", SCOPES)
def test_a_roster_write_that_carries_into_a_locked_later_month_is_refused(scope, router) -> None:
    """A July add is visible in August; with August approved it would move August's pay."""
    pool = _locked_pool(scope, "2026-08")
    with pytest.raises(HTTPException) as exc:
        _call(pool, router, "POST", "/roster", body=_roster_body(scope, period="2026-07"))
    assert exc.value.status_code == 409
    assert "August 2026 is Locked" in exc.value.detail
    # ...but FX is per-period, so July's FX stays editable.
    _call(pool, router, "PUT", "/settings", body=bc.FxSettings(period_key="2026-07", team_fx=18, night_fx=17))
    assert "2026-07" in pool.settings


@pytest.mark.parametrize("scope,router", SCOPES)
def test_writes_to_an_open_month_after_a_locked_one_go_through(scope, router) -> None:
    pool = _locked_pool(scope, "2026-09")
    _call(pool, router, "POST", "/roster", body=_roster_body(scope, period="2026-10"))
    assert pool.roster_names(scope, OCT) == ["New Hire"]
    assert pool.roster_names(scope, SEP) == [], "an open-month write reached the locked month"


def test_the_lock_check_reads_the_scopes_own_lock_table() -> None:
    """A DFW lock must not freeze corporate writes, nor the reverse."""
    pool = _locked_pool(bc.DFW_SCOPE, "2026-10")
    _call(pool, bc.router, "POST", "/roster", body=_roster_body(bc.CORP_SCOPE))
    with pytest.raises(HTTPException):
        _call(pool, bc.dfw_router, "POST", "/roster", body=_roster_body(bc.DFW_SCOPE))


# ---------------------------------------------------------------------------
# Signatures, SQL text and request validation
# ---------------------------------------------------------------------------


def test_the_loaders_require_the_period() -> None:
    for fn in (bc._load_roster, bc._load_afterhours):
        p = inspect.signature(fn).parameters["period_start"]
        assert p.default is inspect.Parameter.empty, f"{fn.__name__} defaults its period"
        with pytest.raises(TypeError):
            asyncio.run(fn(_HubPool(), scope=bc.CORP_SCOPE))


@pytest.mark.parametrize("scope", [bc.CORP_SCOPE, bc.DFW_SCOPE])
def test_the_loader_sql_filters_on_the_effective_dates_of_its_scopes_table(scope) -> None:
    pool = _HubPool()
    asyncio.run(bc._load_roster(pool, OCT, scope))
    asyncio.run(bc._load_afterhours(pool, OCT, scope))
    roster_sql, after_sql = pool.sql
    for sql, tbl in ((roster_sql, scope.tbl_roster), (after_sql, scope.tbl_afterhours)):
        assert re.search(rf"FROM {tbl}\b", sql)
        assert "effective_from IS NULL OR effective_from <= $1" in sql
        assert "effective_to IS NULL OR effective_to >= $1" in sql


def test_the_report_reads_the_roster_of_its_own_month() -> None:
    """`build_bonus_report_data` must pass the report month, not "every row"."""
    from tests.test_bonus_scope import _drive  # noqa: PLC0415 — reuse the stub driver

    _data, _gold, primary = _drive(bc.router, "/report", period="2026-09")
    roster_calls = [p for sql, p in primary.calls if "FROM bonus_roster" in sql or "FROM bonus_afterhours" in sql]
    assert roster_calls and all(p == (SEP,) for p in roster_calls)


def test_a_malformed_period_key_is_rejected() -> None:
    with pytest.raises(ValidationError):
        bc.RosterRow(team_id="team-1", name="X", role="kam", salary_mxn=1, period_key="2026-13")
    with pytest.raises(HTTPException):
        bw.period_start("2026-1")


def test_an_absent_period_falls_back_to_the_current_cst_month(monkeypatch) -> None:
    monkeypatch.setattr(bw, "cst_today", lambda: date(2026, 11, 2))
    assert bw.resolve_write_period(None) == ("2026-11", NOV)
    assert bw.previous_month(date(2026, 1, 1)) == date(2025, 12, 1)


# ---------------------------------------------------------------------------
# The DFW sync follows the same contract
# ---------------------------------------------------------------------------


class _SyncSource:
    def __init__(self, rows):
        self._rows = rows

    async def fetch(self, sql, *params):
        return self._rows


class _SyncPrimary(_HubPool):
    async def fetch(self, sql, *params):
        self.sql.append(sql)
        return list(self.tables.get(self._table(sql), []))


def _sync(pool, people, postings, today=date(2026, 11, 3)):
    return asyncio.run(sync.sync_dfw_bonus_roster(pool, _SyncSource(people), _SyncSource(postings), today=today))


def _person(name, title="Key Account Manager", active=True):
    return {"name": name, "jobTitle": title, "shiftType": "DAY", "isActive": active}


def test_the_sync_inserts_from_the_current_month() -> None:
    pool = _SyncPrimary()
    _sync(pool, [_person("Nuevo Ingreso")], [{"posted_by_name": "NUEVO INGRESO", "team": "TM2", "n": 50}])
    (row,) = pool.tables["bonus_dfw_roster"]
    assert row["effective_from"] == NOV
    assert pool.roster_names(bc.DFW_SCOPE, OCT) == []
    assert pool.roster_names(bc.DFW_SCOPE, NOV) == ["Nuevo Ingreso"]


def test_the_sync_does_not_reinsert_a_person_hr_removed() -> None:
    """HR closed them; Time-off still says active. A re-insert would pay them again."""
    pool = _SyncPrimary()
    pool.seed("bonus_dfw_roster", team_id="dfw-tm-1", employee_name="Removed By Hr", role="kam",
              salary_mxn=1, effective_to=SEP)
    rep = _sync(pool, [_person("Removed By Hr")], [{"posted_by_name": "REMOVED BY HR", "team": "TM1", "n": 9}])
    assert rep["added_team"] == []
    assert len(pool.tables["bonus_dfw_roster"]) == 1


def test_the_sync_does_not_reinsert_a_shortened_name() -> None:
    """2026-10-08: HR's `Mauricio Mahuad` was joined by the job's `Mauricio Mahuad Ortiz`."""
    pool = _SyncPrimary()
    pool.seed("bonus_dfw_roster", team_id="dfw-tm-4", employee_name="Mauricio Mahuad",
              role="tracking_tracing", salary_mxn=0)
    rep = _sync(pool, [_person("Mauricio Mahuad Ortiz", "Tracking and Tracking")],
                [{"posted_by_name": "MAURICIO MAHUAD", "team": "TM4", "n": 25}])
    assert rep["added_team"] == []
    assert len(pool.tables["bonus_dfw_roster"]) == 1
    assert any("Mauricio Mahuad Ortiz" in x for x in rep["skipped_similar_name"])


def test_the_sync_soft_closes_only_open_rows() -> None:
    pool = _SyncPrimary()
    pool.seed("bonus_dfw_roster", team_id="dfw-tm-1", employee_name="Gone Person", role="kam",
              salary_mxn=1, effective_to=SEP)
    pool.seed("bonus_dfw_roster", team_id="dfw-tm-1", employee_name="Gone Person", role="kam",
              salary_mxn=2, effective_from=OCT)
    rep = _sync(pool, [_person("Gone Person", active=False)], [])
    rows = sorted(pool.tables["bonus_dfw_roster"], key=lambda r: r["salary_mxn"])
    assert [r["effective_to"] for r in rows] == [SEP, OCT], "a closed row was re-closed"
    assert len(rep["removed"]) == 1
    assert pool.roster_names(bc.DFW_SCOPE, OCT) == ["Gone Person"]
    assert pool.roster_names(bc.DFW_SCOPE, NOV) == []
