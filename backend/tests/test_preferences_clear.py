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
import os
import re
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


# --------------------------------------------------------------------------
# The INSERT arm (2026-08-18 production outage)
#
# The four tests above prove the *bindings*. They all passed while favourites
# was 100% broken in production, because they never exercised the SQL: the
# endpoint 500'd inside Postgres, not inside Python.
#
# `theme` is `NOT NULL DEFAULT 'light'` in the live table. Starring a report
# PATCHes only `pinned_reports`, so `$4` bound NULL — and an explicit NULL
# OVERRIDES a column default rather than falling back to it. The COALESCEs on
# the DO UPDATE arm hid this: only a user with no row yet reaches the INSERT
# arm, and `user_preferences` held 0 rows against 147 users, so EVERY user's
# first star click raised NotNullViolationError.
#
# Layer 1 is a shape guard on the SQL text; layer 2 replays it for real.
# --------------------------------------------------------------------------


class _SqlCapturingPool:
    """Captures the SQL text as well as the bound parameters."""

    def __init__(self) -> None:
        self.sql: str = ""
        self.params: tuple = ()

    async def execute(self, sql: str, *params):  # noqa: ANN002
        self.sql = sql
        self.params = params
        return "INSERT 0 1"


def _captured_sql(monkeypatch: pytest.MonkeyPatch) -> str:
    pool = _SqlCapturingPool()
    uid = uuid4()
    _patch(monkeypatch, pool, uid)
    asyncio.run(
        prefs.update_preferences(
            prefs.PreferencesUpdate(pinned_reports=[uuid4()]),
            _FakeRequest(pool),
            {"sub": str(uid)},
        )
    )
    return pool.sql


def _values_clause(sql: str) -> str:
    """The VALUES (...) list, i.e. everything before ON CONFLICT."""
    body = sql.split("VALUES", 1)[1]
    return body.split("ON CONFLICT", 1)[0]


def test_insert_arm_defaults_theme_rather_than_binding_null(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A star click leaves `theme` unset; the INSERT must not write NULL to it."""
    values = "".join(_values_clause(_captured_sql(monkeypatch)).split())
    assert "$4" in values, "theme must still be settable on insert"
    assert "COALESCE($4,'light')" in values, (
        "a bare $4 in VALUES writes NULL into a NOT NULL column — "
        "the default belongs on BOTH arms of the upsert"
    )


def test_insert_arm_defaults_every_optional_column(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Same trap for the arrays: absent must mean 'empty', never NULL."""
    values = "".join(_values_clause(_captured_sql(monkeypatch)).split())
    for placeholder in ("$2", "$3", "$4"):
        assert f"COALESCE({placeholder}" in values, (
            f"{placeholder} is bound bare in VALUES; if that column is ever made "
            "NOT NULL the first-ever PATCH for a user 500s"
        )


# --------------------------------------------------------------------------
# Layer 2: replay the real statement against the real schema, rolled back.
# --------------------------------------------------------------------------
_DSN = os.environ.get("DATABASE_URL")
live = pytest.mark.skipif(not _DSN, reason="DATABASE_URL not set — live replay skipped")


def _endpoint_sql() -> str:
    """Read the statement out of the router so the replay cannot drift from it."""
    src = open(
        os.path.join(os.path.dirname(__file__), "..", "app", "routers", "preferences.py")
    ).read()
    m = re.search(r'"""\s*(INSERT INTO user_preferences.*?)\s*"""', src, re.S)
    assert m, "could not extract the upsert from preferences.py"
    return m.group(1)


@live
def test_live_first_ever_star_click_does_not_violate_not_null() -> None:
    """The exact production scenario: a user with no row stars one report."""
    import asyncpg

    dsn = re.sub(r"[?&]sslmode=\w+", "", _DSN or "")
    sql = _endpoint_sql()

    async def run() -> None:
        conn = await asyncpg.connect(dsn, ssl="require")
        try:
            uid = await conn.fetchval("SELECT id FROM users LIMIT 1")
            rid = await conn.fetchval("SELECT id::text FROM reports LIMIT 1")
            tx = conn.transaction()
            await tx.start()
            try:
                await conn.execute(
                    "DELETE FROM user_preferences WHERE user_id = $1", uid
                )
                # theme and recent_reports omitted, exactly as a star click sends it
                await conn.execute(sql, uid, [rid], None, None)
                row = await conn.fetchrow(
                    "SELECT pinned_reports, theme FROM user_preferences WHERE user_id=$1",
                    uid,
                )
                assert row is not None, "the upsert wrote no row"
                assert len(row["pinned_reports"]) == 1
                assert row["theme"] == "light", "theme must fall back to its default"

                # And un-starring the last one must still clear it (the R1-R3 fix).
                await conn.execute(sql, uid, [], None, None)
                row = await conn.fetchrow(
                    "SELECT pinned_reports FROM user_preferences WHERE user_id=$1", uid
                )
                assert row["pinned_reports"] == [], "clearing must persist"
            finally:
                await tx.rollback()
        finally:
            await conn.close()

    asyncio.run(run())
