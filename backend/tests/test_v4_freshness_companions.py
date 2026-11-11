"""The STOPPED mail must show the WHOLE gold load, not just v4 + movement (§143).

2026-11-11 15:40: the alert named v4 (13:20) and movement (12:42) only, while every
McLeod gold table our reports read had stopped between 12:16 and 13:24 — Aging
Cashflow, Division Payment's delivery month, XRay, Customer Score all froze too.
The companion sweep runs ONLY when a STOPPED mail goes out (≈2 GB unindexed
reads), is time-capped, and fails soft: a failed sweep never blocks the alert.
"""

import asyncio
from datetime import datetime, timedelta

import pytest
from graph_fake import capture

from app.services import v4_freshness_companions as c
from app.services import v4_freshness_monitor as f

NOW = datetime(2026, 11, 11, 15, 40)  # noqa: DTZ001 — gold stamps are naive CST
V4_LAST = datetime(2026, 11, 11, 13, 20, 47)  # noqa: DTZ001
MOV_LAST = datetime(2026, 11, 11, 12, 42, 33)  # noqa: DTZ001
FRESH_S = f.STALE_MINUTES * 60


def _companion_row(**over):
    base = {comp.col: V4_LAST - timedelta(minutes=i) for i, comp in enumerate(c.COMPANIONS)}
    return {**base, **over}


# ── classification ───────────────────────────────────────────────────────────

def test_tables_frozen_with_the_load_are_stopped_together() -> None:
    res = c.classify(_companion_row(), anchor=V4_LAST, now=NOW, fresh_s=FRESH_S)
    assert [x.table for x in res.stopped] == [comp.table for comp in c.COMPANIONS][::-1]
    assert res.still_written == []


def test_a_fresh_table_is_still_written() -> None:
    col = c.COMPANIONS[0].col
    res = c.classify(_companion_row(**{col: NOW - timedelta(minutes=5)}),
                     anchor=V4_LAST, now=NOW, fresh_s=FRESH_S)
    assert [x.table for x in res.still_written] == [c.COMPANIONS[0].table]
    assert c.COMPANIONS[0].table not in [x.table for x in res.stopped]


def test_a_quiet_dimension_table_is_omitted() -> None:
    # Last written days before the freeze = normal quiet, not part of this stop.
    col = c.COMPANIONS[1].col
    res = c.classify(_companion_row(**{col: V4_LAST - timedelta(days=3)}),
                     anchor=V4_LAST, now=NOW, fresh_s=FRESH_S)
    names = [x.table for x in res.stopped + res.still_written]
    assert c.COMPANIONS[1].table not in names


def test_stopped_is_sorted_oldest_first_and_carries_age() -> None:
    res = c.classify(_companion_row(), anchor=V4_LAST, now=NOW, fresh_s=FRESH_S)
    lasts = [x.last for x in res.stopped]
    assert lasts == sorted(lasts)
    assert res.stopped[0].age_s == int((NOW - res.stopped[0].last).total_seconds())


def test_a_never_written_companion_is_omitted() -> None:
    col = c.COMPANIONS[2].col
    res = c.classify(_companion_row(**{col: None}), anchor=V4_LAST, now=NOW, fresh_s=FRESH_S)
    assert c.COMPANIONS[2].table not in [x.table for x in res.stopped + res.still_written]


def test_sql_reads_one_max_per_companion() -> None:
    sql = c.COMPANION_SQL
    for comp in c.COMPANIONS:
        assert f"(SELECT max(updated_dt) FROM public.{comp.table}) AS {comp.col}" in sql
    assert "budget_report_v4" not in sql and "mcleod_gld_movement" not in sql


def test_every_companion_names_its_readers() -> None:
    assert len({comp.table for comp in c.COMPANIONS}) == len(c.COMPANIONS)
    assert all(comp.read_by.strip() for comp in c.COMPANIONS)


# ── wired into the STOPPED mail ──────────────────────────────────────────────

def _row():
    return {"cst_now": NOW, "v4_last": V4_LAST, "movement_last": MOV_LAST, "live_last": NOW,
            "events_since_v4": 18, "events_since_movement": 33}


class _Pool:
    def __init__(self, companions=None, fail=False):
        self.companions = companions
        self.fail = fail
        self.calls: list[tuple[str, dict]] = []

    async def fetchrow(self, sql, *params, **kw):
        self.calls.append((sql, kw))
        if sql is f.FRESHNESS_SQL:
            return _row()
        assert sql is c.COMPANION_SQL
        if self.fail:
            raise TimeoutError
        return self.companions


@pytest.fixture
def sent(monkeypatch):
    mails: list[dict] = []
    monkeypatch.setattr(f, "send_notification", capture(mails))
    return mails


def test_stopped_mail_lists_the_companion_tables(sent) -> None:
    pool = _Pool(_companion_row())
    res = asyncio.run(f.check_v4_freshness(pool, memory=f.AlertMemory()))
    assert res["alerted"] is True
    html = sent[0]["html"]
    for comp in c.COMPANIONS:
        assert comp.table in html and comp.read_by in html
    assert f"+ {len(c.COMPANIONS)} more gold tables" in sent[0]["subject"]
    # Time-capped read.
    kw = next(kw for sql, kw in pool.calls if sql is c.COMPANION_SQL)
    assert kw.get("timeout") == c.COMPANION_TIMEOUT_S


def test_a_still_written_companion_says_partial(sent) -> None:
    col = c.COMPANIONS[0].col
    pool = _Pool(_companion_row(**{col: NOW - timedelta(minutes=3)}))
    asyncio.run(f.check_v4_freshness(pool, memory=f.AlertMemory()))
    html = sent[0]["html"]
    assert "Still being written" in html and c.COMPANIONS[0].table in html


def test_a_failed_sweep_never_blocks_the_alert(sent) -> None:
    pool = _Pool(fail=True)
    res = asyncio.run(f.check_v4_freshness(pool, memory=f.AlertMemory()))
    assert res["alerted"] is True and len(sent) == 1
    assert "could not be checked" in sent[0]["html"]
    assert "more gold tables" not in sent[0]["subject"]


def test_no_sweep_when_already_alerted(sent) -> None:
    memory = f.AlertMemory()
    asyncio.run(f.check_v4_freshness(_Pool(_companion_row()), memory=memory))
    pool = _Pool(_companion_row())
    res = asyncio.run(f.check_v4_freshness(pool, memory=memory))
    assert res["reason"] == "already_alerted"
    assert all(sql is not c.COMPANION_SQL for sql, _ in pool.calls)
