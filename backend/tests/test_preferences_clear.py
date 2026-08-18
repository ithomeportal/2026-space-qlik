"""Un-favouriting the LAST report must persist (Bruno PDF 2026-08-17 R1-R3).

`PATCH /user/preferences` upserts with `COALESCE($2, user_preferences.…)`, so
NULL means "leave unchanged". The binding used truthiness — and an empty list is
falsy in Python — so clearing the list sent NULL and the old list survived.

Removing your only favourite therefore looked like it worked (the star flipped
optimistically) and silently reverted on the next fetch. Offline test: it drives
the endpoint with a fake pool and inspects the bound parameters, so it needs no
database.
"""

from __future__ import annotations

import asyncio
from uuid import UUID, uuid4

import pytest

from app.routers import preferences as prefs


class _FakePool:
    """Captures the parameters the endpoint binds."""

    def __init__(self) -> None:
        self.params: tuple = ()

    async def execute(self, _sql: str, *params):  # noqa: ANN002
        self.params = params
        return "UPDATE 1"


class _FakeRequest:
    def __init__(self, pool: _FakePool) -> None:
        self.app = type("app", (), {"state": type("state", (), {"pool": pool})()})()


def _patch(monkeypatch: pytest.MonkeyPatch, pool: _FakePool, user_id: UUID) -> None:
    monkeypatch.setattr(prefs, "get_pool", lambda _request: pool)
    monkeypatch.setattr(prefs, "user_uuid", lambda _user: user_id)


def _run(body: prefs.PreferencesUpdate, monkeypatch: pytest.MonkeyPatch) -> tuple:
    pool = _FakePool()
    uid = uuid4()
    _patch(monkeypatch, pool, uid)
    asyncio.run(prefs.update_preferences(body, _FakeRequest(pool), {"sub": str(uid)}))
    return pool.params


def test_empty_list_clears_rather_than_being_ignored(monkeypatch: pytest.MonkeyPatch) -> None:
    params = _run(prefs.PreferencesUpdate(pinned_reports=[]), monkeypatch)
    # params = (user_id, pinned, recent, theme)
    assert params[1] == [], "empty list must bind as [] so COALESCE stores it"
    assert params[1] is not None, "binding NULL makes COALESCE keep the old list"


def test_omitted_field_still_binds_null(monkeypatch: pytest.MonkeyPatch) -> None:
    """Absent != empty: a PATCH that only sets `theme` must not wipe favourites."""
    params = _run(prefs.PreferencesUpdate(theme="light"), monkeypatch)
    assert params[1] is None
    assert params[2] is None
    assert params[3] == "light"


def test_populated_list_round_trips_as_strings(monkeypatch: pytest.MonkeyPatch) -> None:
    a, b = uuid4(), uuid4()
    params = _run(prefs.PreferencesUpdate(pinned_reports=[a, b]), monkeypatch)
    assert params[1] == [str(a), str(b)]


def test_empty_recent_reports_clears_too(monkeypatch: pytest.MonkeyPatch) -> None:
    params = _run(prefs.PreferencesUpdate(recent_reports=[]), monkeypatch)
    assert params[2] == []
