"""A gold load can come back PARTLY, and a deploy must not erase a freeze (§143 v6).

2026-11-11 ~16:00 Data / BI removed a blocking Spark task: v4, movement and
cashflow wrote again, while ``orders_pu_del_windows`` (Hold board) stayed at
12:41 and ``customer_windows`` (DPC delivery month, Ops portals, PCA mails) at
13:18 — 29 / 45 orders picked up or delivered since (measured 16:30). Watching
v4 + movement alone would have mailed "resumed". And the 16:05 deploy had wiped
the in-process memory, so no "resumed" mail at all would have gone out.
"""

import asyncio
import json
from datetime import datetime, timedelta

import pytest
from graph_fake import capture

from app.services import mirror_status_lag_monitor as lag
from app.services import v4_freshness_companions as comp
from app.services import v4_freshness_monitor as f
from app.services import v4_freshness_state as st

NOW = datetime(2026, 11, 11, 15, 40)  # noqa: DTZ001 — gold stamps are naive CST
V4_LAST = datetime(2026, 11, 11, 13, 20, 47)  # noqa: DTZ001
MOV_LAST = datetime(2026, 11, 11, 12, 42, 33)  # noqa: DTZ001
CW_LAST = datetime(2026, 11, 11, 13, 18, 2)  # noqa: DTZ001
PD_LAST = datetime(2026, 11, 11, 12, 41, 14)  # noqa: DTZ001


def _row(now=NOW, *, v4=V4_LAST, mov=MOV_LAST, cw=CW_LAST, pd=PD_LAST, since=18):
    """since = orders picked up / delivered after each STALE table's last write."""
    def ev(last):
        return since if (now - last) > timedelta(minutes=f.STALE_MINUTES) else 0

    return {"cst_now": now, "live_last": now,
            "v4_last": v4, "events_since_v4": ev(v4),
            "movement_last": mov, "events_since_movement": ev(mov),
            "customer_windows_last": cw, "events_since_customer_windows": ev(cw),
            "pu_del_windows_last": pd, "events_since_pu_del_windows": ev(pd)}


def _partial(now):
    """16:30 on 11-11: v4 + movement back, the two windows tables still frozen."""
    return _row(now, v4=now - timedelta(minutes=14), mov=now - timedelta(minutes=31))


def _all_fresh(now):
    return _row(now, v4=now - timedelta(minutes=9), mov=now - timedelta(minutes=4),
                cw=now - timedelta(minutes=20), pd=now - timedelta(minutes=6))


class _Gold:
    def __init__(self, row):
        self.row = row

    async def fetchrow(self, sql, *params, **kw):
        if sql is f.FRESHNESS_SQL:
            return self.row
        assert sql is comp.COMPANION_SQL
        return None

    async def fetch(self, sql, *params, **kw):
        assert sql is lag.LAG_SQL
        return []


class _Hub:
    """The hub DB: one gold_freshness_alert_state row, as asyncpg returns it."""

    def __init__(self, fail_load=False, fail_save=False):
        self.row: dict | None = None
        self.fail_load, self.fail_save = fail_load, fail_save
        self.saves = 0

    async def fetchrow(self, sql, *params, **kw):
        if self.fail_load:
            raise ConnectionError("hub down")
        assert "gold_freshness_alert_state" in sql and params == (st.STATE_KEY,)
        return self.row

    async def execute(self, sql, key, stamps, sent_at, **kw):
        if self.fail_save:
            raise ConnectionError("hub down")
        assert "ON CONFLICT (watch_key)" in sql and key == st.STATE_KEY
        self.row = {"stamps": json.loads(stamps), "sent_at": sent_at}  # jsonb → dict
        self.saves += 1


@pytest.fixture
def sent(monkeypatch):
    mails: list[dict] = []
    monkeypatch.setattr(f, "send_notification", capture(mails))
    return mails


def _run(row, memory=None, hub=None, sync=None):
    return asyncio.run(f.check_v4_freshness(
        _Gold(row), memory=f.AlertMemory() if memory is None else memory, hub_pool=hub,
        sync=f.HubSync() if sync is None else sync))


# ── the two windows tables are watched ───────────────────────────────────────

def test_the_16_30_state_flags_only_the_windows_tables() -> None:
    stale = f.stale_tables(_partial(NOW + timedelta(minutes=50)))
    assert [t.name for t in stale] == ["customer_windows", "pu_del_windows"]
    assert "Hold board" in stale[1].read_by and "Division Payment" in stale[0].read_by


def test_a_windows_table_alone_raises_the_alarm(sent) -> None:
    res = _run(_partial(NOW + timedelta(minutes=50)))
    assert res["alerted"] is True and res["stale"] == ["customer_windows", "pu_del_windows"]
    assert "customer_windows not written for" in sent[0]["subject"]
    html = sent[0]["html"]
    assert "mcleod_gld_orders_pu_del_windows" in html and "Hold board" in html


def test_quiet_windows_tables_are_not_a_freeze() -> None:
    # Silent for hours, but McLeod recorded no arrival since — a quiet evening.
    row = _row(NOW, v4=NOW - timedelta(minutes=5), mov=NOW - timedelta(minutes=5), since=0)
    assert f.stale_tables(row) == []


def test_sql_reads_both_windows_tables_on_tms_in_one_live_scan() -> None:
    sql = f.FRESHNESS_SQL
    for table in (f.CUSTOMER_WINDOWS_TABLE, f.PU_DEL_WINDOWS_TABLE):
        assert f"max(updated_dt) FROM {table} WHERE company_id IN ('TMS'," in sql
    assert "events_since_customer_windows" in sql and "events_since_pu_del_windows" in sql
    assert sql.count(f.LIVE_TABLE) == 2  # max + ONE scan for every count
    assert "COALESCE(t.pu_del_windows_last, '-infinity')) - interval '1 hour'" in sql


def test_windows_tables_are_no_longer_companions() -> None:
    tables = {c.table for c in comp.COMPANIONS}
    assert "mcleod_gld_customer_windows" not in tables
    assert "mcleod_gld_orders_pu_del_windows" not in tables


# ── partial resume ───────────────────────────────────────────────────────────

def test_partial_resume_names_what_is_still_stopped_in_one_mail(sent) -> None:
    memory = f.AlertMemory()
    _run(_row(), memory)  # 15:40: all four stopped
    assert len(sent) == 1
    res = _run(_partial(NOW + timedelta(minutes=50)), memory)  # 16:30
    assert res["resumed"] == ["v4", "movement"]
    assert len(sent) == 2  # ONE mail: the partial resume is the windows tables' alert
    msg = sent[1]
    assert "partly resumed" in msg["subject"]
    assert "still stopped: customer_windows, pu_del_windows" in msg["subject"]
    assert "Only a partial resume" in msg["html"] and "Hold board" in msg["html"]
    assert set(memory.stamps) == {"customer_windows", "pu_del_windows"}


def test_after_a_partial_resume_reminders_and_final_resume(sent) -> None:
    memory = f.AlertMemory()
    _run(_row(), memory)
    t1 = NOW + timedelta(minutes=50)
    _run(_partial(t1), memory)
    for h in range(1, 6):
        assert _run(_partial(t1 + timedelta(hours=h)), memory)["reason"] == "already_alerted"
    assert len(sent) == 2
    res = _run(_partial(t1 + timedelta(hours=6)), memory)
    assert res.get("reminder") is True and "STILL STOPPED" in sent[2]["subject"]
    _run(_all_fresh(t1 + timedelta(hours=7)), memory)
    final = sent[3]
    assert "resumed — customer_windows, pu_del_windows written again" in final["subject"]
    assert "partly" not in final["subject"]
    assert memory.stamps == {} and memory.sent_at is None


def test_a_first_freeze_beside_a_resume_still_gets_its_stopped_mail(sent) -> None:
    # The exact 11-11 hand-over: memory from the pre-v6 code knows only v4/movement;
    # the windows tables were never alerted. A first freeze must never be announced
    # only under a "resumed" subject (review 11-11).
    memory = f.AlertMemory(stamps={"v4": V4_LAST, "movement": MOV_LAST}, sent_at=NOW)
    t1 = NOW + timedelta(minutes=50)
    res = _run(_partial(t1), memory)
    assert [m["subject"].split(" — ")[0] for m in sent] == [
        "[UNILINK Space] Gold McLeod load partly resumed",
        "[UNILINK Space] Gold McLeod load STOPPED",
    ]
    assert "customer_windows not written for" in sent[1]["subject"]
    assert res["alerted"] is True and res.get("reminder") is False
    assert set(memory.stamps) == {"customer_windows", "pu_del_windows"}
    assert memory.sent_at == t1
    _run(_partial(t1 + timedelta(hours=1)), memory)
    assert len(sent) == 2


# ── the memory survives a deploy ─────────────────────────────────────────────

def test_a_deploy_inside_a_freeze_neither_repeats_nor_loses_mail(sent) -> None:
    hub = _Hub()
    _run(_row(), f.AlertMemory(), hub)
    assert len(sent) == 1 and hub.saves == 1
    # Deploy: a fresh process, empty in-process memory, same hub row.
    res = _run(_row(NOW + timedelta(hours=1)), f.AlertMemory(), hub)
    assert res["reason"] == "already_alerted" and len(sent) == 1
    # Another deploy, then the load resumes: the resumed mail still goes out.
    _run(_all_fresh(NOW + timedelta(hours=2)), f.AlertMemory(), hub)
    assert len(sent) == 2 and "resumed" in sent[1]["subject"]
    assert hub.row["stamps"] == {} and hub.row["sent_at"] is None


def test_a_healthy_run_writes_nothing(sent) -> None:
    hub = _Hub()
    _run(_all_fresh(NOW), f.AlertMemory(), hub)
    assert hub.saves == 0 and sent == []


def test_hub_load_failure_falls_back_to_process_memory(sent) -> None:
    memory = f.AlertMemory()
    _run(_row(), memory, _Hub(fail_load=True, fail_save=True))
    assert len(sent) == 1 and "v4" in memory.stamps
    res = _run(_row(NOW + timedelta(hours=1)), memory, _Hub(fail_load=True, fail_save=True))
    assert res["reason"] == "already_alerted" and len(sent) == 1


def test_a_failed_save_never_loads_the_older_hub_row_over_memory(sent) -> None:
    # Load works, save fails: the hub row stays OLDER than the process. Reloading
    # it each run re-sent the STOPPED mail hourly (review 11-11).
    hub, sync, memory = _Hub(fail_save=True), f.HubSync(), f.AlertMemory()
    for h in range(4):
        _run(_row(NOW + timedelta(hours=h)), memory, hub, sync)
    assert len(sent) == 1 and sync.dirty is True
    # The hub heals: the next run saves (even with nothing new) and is in sync.
    hub.fail_save = False
    _run(_row(NOW + timedelta(hours=4)), memory, hub, sync)
    assert sync.dirty is False and hub.row["stamps"]["v4"] == V4_LAST.isoformat()
    # A deploy now reads that row: still one mail for the freeze.
    _run(_row(NOW + timedelta(hours=5)), f.AlertMemory(), hub)
    assert len(sent) == 1


def test_stamps_round_trip_including_never_written() -> None:
    stamps = {"v4": V4_LAST, "pu_del_windows": None}
    assert st.decode_stamps(st.encode_stamps(stamps)) == stamps
    assert st.decode_stamps({"v4": V4_LAST.isoformat()}) == {"v4": V4_LAST}


def test_unreadable_state_is_a_fallback_not_a_crash() -> None:
    class _Bad:
        async def fetchrow(self, *a, **kw):
            return {"stamps": {"v4": "not-a-date"}, "sent_at": None}

    assert asyncio.run(st.load(_Bad())) is None
    assert asyncio.run(st.load(None)) is None
    assert asyncio.run(st.save(None, f.AlertMemory())) is False
