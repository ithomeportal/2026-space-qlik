"""Freshness watchdog must cover BOTH portal-owned scorecard mirrors.

Until 2026-10-23 it watched only ``mcleod_gld_scorecard_portal``; the incident-grain
mirror (``mcleod_gld_scorecard_incidents_portal``, read by OPs Customer Score, the
XRay reports, the Ops portals and Bonus) had no watchdog at all — a stated TODO in
SPEC-RELIABILITY. The incidents mirror's change marker sums BOTH of its sources.
"""

import asyncio
from datetime import datetime, timezone

import pytest

from app.services import scorecard_mirror_monitor as m


def _row(**over):
    base = {
        "mirror_rows": 127_000,
        "refreshed_at": datetime(2026, 10, 23, 19, 15, tzinfo=timezone.utc),
        "source_advanced": False,
        "past_grace": False,
        "source_size": "1 GB",
    }
    return {**base, **over}


class _Conn:
    def __init__(self, rows_by_mirror, present=True):
        self.rows_by_mirror = rows_by_mirror
        self.present = present
        self.sql: list[str] = []

    async def fetchval(self, sql):
        self.sql.append(sql)
        return self.present

    async def fetchrow(self, sql):
        self.sql.append(sql)
        for mirror, row in self.rows_by_mirror.items():
            if f"FROM {mirror})" in sql:
                return row
        raise AssertionError("query for an unknown mirror")


class _Pool:
    def __init__(self, conn):
        self.conn = conn

    def acquire(self):
        conn = self.conn

        class _Ctx:
            async def __aenter__(self):
                return conn

            async def __aexit__(self, *a):
                return False

        return _Ctx()


def test_both_mirrors_are_watched():
    names = {spec.mirror for spec in m.MIRRORS}
    assert names == {
        "public.mcleod_gld_scorecard_portal",
        "public.mcleod_gld_scorecard_incidents_portal",
    }


def test_incidents_marker_sums_both_sources():
    spec = next(s for s in m.MIRRORS if "incidents" in s.mirror)
    assert set(spec.sources) == {"mcleod_gld_scorecard", "mcleod_gld_incidents_v3"}
    sql = m._probe_sql(spec)
    assert "relname IN ('mcleod_gld_scorecard','mcleod_gld_incidents_v3')" in sql
    assert "sum(n_tup_ins + n_tup_upd)" in sql
    assert f"FROM {spec.meta} WHERE id = 1" in sql


@pytest.mark.parametrize(
    "over, stale",
    [
        ({}, False),
        ({"source_advanced": True}, False),  # changed, still inside the grace window
        ({"past_grace": True}, False),  # old but nothing to refresh
        ({"source_advanced": True, "past_grace": True}, True),
        ({"mirror_rows": 0}, True),
        ({"refreshed_at": None}, True),
    ],
)
def test_stale_decision(over, stale):
    assert m._is_stale(_row(**over)) is stale


def test_only_the_stale_mirror_alerts(monkeypatch):
    sent = []

    async def fake_alert(spec, to, stats, reason, *, reason_code):
        sent.append(spec.mirror)
        return {"checked": True, "stale": True, "alerted": True}

    monkeypatch.setattr(m, "_alert", fake_alert)
    conn = _Conn(
        {
            "public.mcleod_gld_scorecard_portal": _row(),
            "public.mcleod_gld_scorecard_incidents_portal": _row(
                source_advanced=True, past_grace=True
            ),
        }
    )
    result = asyncio.run(m.check_scorecard_mirror(_Pool(conn)))
    assert sent == ["public.mcleod_gld_scorecard_incidents_portal"]
    assert result["public.mcleod_gld_scorecard_portal"]["stale"] is False
    assert result["public.mcleod_gld_scorecard_incidents_portal"]["stale"] is True


def test_a_failing_probe_does_not_hide_the_other_mirror(monkeypatch):
    """One mirror's query error (e.g. lock_timeout on a held lock) is reported for
    that mirror only; the other is still checked."""

    class _HalfBroken(_Conn):
        async def fetchrow(self, sql):
            if "incidents" in sql:
                raise RuntimeError("canceling statement due to lock timeout")
            return await super().fetchrow(sql)

    conn = _HalfBroken({"public.mcleod_gld_scorecard_portal": _row()})
    result = asyncio.run(m.check_scorecard_mirror(_Pool(conn)))
    assert result["public.mcleod_gld_scorecard_portal"]["stale"] is False
    assert result["public.mcleod_gld_scorecard_incidents_portal"]["reason"] == "query_failed"


def test_no_pool_is_a_skip_not_a_crash():
    assert asyncio.run(m.check_scorecard_mirror(None)) == {"checked": False, "reason": "no_pool"}


def test_alert_names_the_mirror_and_its_workflow():
    spec = next(s for s in m.MIRRORS if "incidents" in s.mirror)
    html = m._render_html(spec, _row(), "Mirror is empty.")
    assert spec.mirror in html
    assert spec.workflow in html
