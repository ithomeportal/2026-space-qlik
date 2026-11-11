"""Watchdog: is the McLeod → gold load still WRITING v4 / movement? (§143)

2026-11-11: v4 stopped at 23:20 CST and movement at 22:28 while the n8n live
feed kept moving (245 orders changed). Nothing watched v4's freshness; the
06:25 status-lag mail called it "still skipping" and said "freshness checks stay
green". This hourly job must alert ONCE per freeze, only when the live feed
proves McLeod kept moving, say when the load resumes, and never raise.
"""

import asyncio
from datetime import datetime, timedelta
from pathlib import Path

import pytest
from graph_fake import capture

from app.services import v4_freshness_monitor as f

NOW = datetime(2026, 11, 11, 7, 38)  # noqa: DTZ001 — gold stamps are naive CST
V4_LAST = datetime(2026, 11, 10, 23, 20, 31)  # noqa: DTZ001
MOV_LAST = datetime(2026, 11, 10, 22, 28, 26)  # noqa: DTZ001


def _row(v4=V4_LAST, mov=MOV_LAST, live=NOW, since_v4=245, since_mov=260, now=NOW, **extra):
    # The two windows tables (v6) default to fresh; a test overrides them by key.
    return {
        "cst_now": now, "v4_last": v4, "movement_last": mov, "live_last": live,
        "events_since_v4": since_v4, "events_since_movement": since_mov,
        "customer_windows_last": now - timedelta(minutes=12), "events_since_customer_windows": 0,
        "pu_del_windows_last": now - timedelta(minutes=7), "events_since_pu_del_windows": 0,
        **extra,
    }


FRESH = _row(v4=NOW - timedelta(minutes=9), mov=NOW - timedelta(minutes=4),
             since_v4=3, since_mov=1)


class _Pool:
    def __init__(self, row=None, fail=False):
        self.row = row
        self.fail = fail
        self.sql: list[str] = []

    async def fetchrow(self, sql, *params, **kw):
        self.sql.append(sql)
        if sql is not f.FRESHNESS_SQL:
            return None  # the companion sweep — covered in test_v4_freshness_companions
        if self.fail:
            raise RuntimeError("canceling statement due to statement timeout")
        return self.row


@pytest.fixture
def sent(monkeypatch):
    mails: list[dict] = []
    monkeypatch.setattr(f, "send_notification", capture(mails))
    return mails


def _run(row, memory, **kw):
    return asyncio.run(f.check_v4_freshness(_Pool(row), memory=memory, **kw))


# ── pure assessment ──────────────────────────────────────────────────────────

def test_the_11_11_freeze_is_stale_on_both_tables() -> None:
    stale = f.stale_tables(_row())
    assert [t.name for t in stale] == ["v4", "movement"]
    v4 = stale[0]
    assert v4.last == V4_LAST and v4.events_since == 245
    assert v4.age_s == int((NOW - V4_LAST).total_seconds())


def test_fresh_tables_are_healthy() -> None:
    assert f.stale_tables(FRESH) == []


def test_a_quiet_hour_is_not_a_freeze() -> None:
    # v4 silent but McLeod recorded no stops since — a quiet night, no alert.
    assert f.stale_tables(_row(since_v4=f.MIN_EVENTS - 1, since_mov=0)) == []


def test_just_under_the_window_is_healthy() -> None:
    row = _row(v4=NOW - timedelta(minutes=f.STALE_MINUTES - 1),
               mov=NOW - timedelta(minutes=5))
    assert f.stale_tables(row) == []


def test_an_empty_table_is_stale() -> None:
    assert [t.name for t in f.stale_tables(_row(v4=None, mov=NOW))] == ["v4"]


@pytest.mark.parametrize(("secs", "text"), [(95 * 60, "95 min"), (8 * 3600 + 18 * 60, "8 h 18 min"), (7200, "2 h"),
                                             (2 * 86400 + 3600, "2 d 1 h")])
def test_age_text(secs, text) -> None:
    assert f.age_text(secs) == text


# ── the job ──────────────────────────────────────────────────────────────────

def test_alerts_once_per_freeze(sent) -> None:
    memory = f.AlertMemory()
    res = _run(_row(), memory)
    assert res["alerted"] is True and len(sent) == 1
    msg = sent[0]
    assert "STOPPED" in msg["subject"] and "v4 not written for 8 h 17 min" in msg["subject"]
    assert msg["to"] == ["dfrodriguez@unilinktransportation.com"]
    assert msg["cc"] == ["oorozco@unilinktransportation.com", "dcastrog@unilinktransportation.com"]
    html = msg["html"]
    assert "mcleod_gld_budget_report_v4" in html and "mcleod_gld_movement" in html
    assert "2026-11-10 23:20" in html and ">245<" in html
    # Same freeze an hour later: no second mail.
    later = _row(now=NOW + timedelta(hours=1))
    res2 = _run(later, memory)
    assert res2["alerted"] is False and res2["reason"] == "already_alerted"
    assert len(sent) == 1


def test_a_new_freeze_after_a_partial_write_alerts_again(sent) -> None:
    memory = f.AlertMemory()
    _run(_row(), memory)
    # v4 wrote one batch, then froze again: a different last stamp = a new freeze.
    again = _row(v4=V4_LAST + timedelta(hours=2), now=NOW + timedelta(hours=4))
    _run(again, memory)
    assert len(sent) == 2


def test_one_stray_batch_is_not_a_resume(sent) -> None:
    memory = f.AlertMemory()
    _run(_row(), memory)
    # v4 wrote one batch at 01:20 and froze again; few stops since, so not "stale"
    # yet — but not fresh either: no "resumed" mail, the freeze stays remembered.
    stray = _row(v4=V4_LAST + timedelta(hours=2), now=NOW + timedelta(hours=1),
                 since_v4=1, since_mov=300)
    res = _run(stray, memory)
    assert res.get("resumed", []) == [] and len(sent) == 1
    assert "v4" in memory.stamps


def test_an_empty_table_subject(sent) -> None:
    _run(_row(v4=None, mov=NOW), f.AlertMemory())
    assert "v4 never written" in sent[0]["subject"]


def test_resumed_mail_after_a_freeze(sent) -> None:
    memory = f.AlertMemory()
    _run(_row(), memory)
    res = _run(FRESH, memory)
    assert res["healthy"] is True and res["resumed"] == ["v4", "movement"]
    assert len(sent) == 2 and "resumed" in sent[1]["subject"]
    assert "06:25" in sent[1]["html"]  # points at the backlog check
    # Healthy again with nothing remembered: silent.
    _run(FRESH, memory)
    assert len(sent) == 2


def test_healthy_is_silent(sent) -> None:
    res = _run(FRESH, f.AlertMemory())
    assert res == {**res, "checked": True, "healthy": True}
    assert sent == []


def test_failed_send_is_retried_next_hour(sent, monkeypatch) -> None:
    async def _down(**_kw):
        return {"sent": False, "reason": "graph_error"}

    memory = f.AlertMemory()
    monkeypatch.setattr(f, "send_notification", _down)
    assert _run(_row(), memory)["alerted"] is False
    assert memory.stamps == {}  # not remembered → the next run tries again


def test_never_raises_on_a_query_failure(sent) -> None:
    res = asyncio.run(f.check_v4_freshness(_Pool(fail=True), memory=f.AlertMemory()))
    assert res["checked"] is False and res["reason"] == "query_failed"
    assert sent == []


def test_no_pool_is_a_skip() -> None:
    assert asyncio.run(f.check_v4_freshness(None))["reason"] == "no_pool"


def test_non_company_cc_is_dropped(sent) -> None:
    _run(_row(), f.AlertMemory(), cc=("someone@gmail.com",))
    assert "cc" not in sent[0]


def test_sql_shape() -> None:
    sql = f.FRESHNESS_SQL
    # TMS only on both — the live feed is TMS-only; an MX trickle must not hide a stop.
    assert "max(updated_dt) FROM public.mcleod_gld_budget_report_v4 WHERE company_id IN ('TMS'," in sql
    assert "max(updated_dt) FROM public.mcleod_gld_movement WHERE company_id IN ('TMS'," in sql
    assert "(now() AT TIME ZONE 'America/Chicago') AS cst_now" in sql
    # Orders, not GPS rows; deleted live rows never count.
    assert "count(DISTINCT r.id)" in sql and "is_deleted" in sql
    # Real stop events, never the GPS-re-stamped live updated_dt.
    assert "r.origin_actual_arrival > COALESCE(t.v4_last" in sql
    assert "r.dest_actual_arrival > COALESCE(t.movement_last" in sql
    assert sql.count(f.LIVE_TABLE) == 2  # max + ONE scan for both counts
    assert "WITH t AS MATERIALIZED" in sql  # each max() runs once (14 s inlined)


def test_the_job_is_scheduled_and_on_the_roster() -> None:
    src = (Path(__file__).resolve().parents[1] / "app" / "main.py").read_text()
    roster = src.split("EXPECTED_JOBS = {", 1)[1].split("}", 1)[0]
    assert '"hourly_v4_freshness_check":' in roster
    assert 'id="hourly_v4_freshness_check"' in src
    assert 'hour="2,6-22", minute=40' in src
    body = src.split("async def _scheduled_v4_freshness_check", 1)[1].split("\nasync def ", 1)[0]
    # The hub pool keeps the alert memory across deploys (v6).
    assert 'check_v4_freshness(pool, hub_pool=getattr(app.state, "pool", None))' in body
    assert "GF_STATE_DDL" in src  # the state table is created at startup
