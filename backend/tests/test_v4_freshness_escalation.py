"""A STOPPED gold load must keep reminding Data / BI until it resumes (§143 v5).

2026-11-11: the load stopped twice in one day (23:20 → 07:36, then 13:20). One
mail per freeze let the afternoon stop sit unanswered. Owner request: re-notify
Omar every 6 h while it stays stopped, CC Daniela Castro; run once at 02:40 so
a stop after 22:40 is caught before morning; the resumed mail counts the orders
v4 still shows 'A' after McLeod moved them.
"""

import asyncio
from datetime import datetime, timedelta
from pathlib import Path

import pytest
from graph_fake import capture

from app.services import mirror_status_lag_monitor as lag
from app.services import v4_freshness_companions as comp
from app.services import v4_freshness_monitor as f

NOW = datetime(2026, 11, 11, 15, 40)  # noqa: DTZ001 — gold stamps are naive CST
V4_LAST = datetime(2026, 11, 11, 13, 20, 47)  # noqa: DTZ001
MOV_LAST = datetime(2026, 11, 11, 12, 42, 33)  # noqa: DTZ001

OMAR = "oorozco@unilinktransportation.com"
DANIELA = "dcastrog@unilinktransportation.com"
DIEGO = "dfrodriguez@unilinktransportation.com"


def _row(now=NOW, v4=V4_LAST, mov=MOV_LAST, since=18):
    return {"cst_now": now, "v4_last": v4, "movement_last": mov, "live_last": now,
            "events_since_v4": since, "events_since_movement": since + 10,
            "customer_windows_last": now - timedelta(minutes=12), "events_since_customer_windows": 0,
            "pu_del_windows_last": now - timedelta(minutes=7), "events_since_pu_del_windows": 0}


def _fresh(now):
    return _row(now=now, v4=now - timedelta(minutes=9), mov=now - timedelta(minutes=4), since=0)


class _Pool:
    def __init__(self, row, stuck=None, stuck_fail=False):
        self.row = row
        self.stuck = stuck if stuck is not None else []
        self.stuck_fail = stuck_fail
        self.fetch_sql: list[str] = []

    async def fetchrow(self, sql, *params, **kw):
        if sql is f.FRESHNESS_SQL:
            return self.row
        assert sql is comp.COMPANION_SQL
        return None

    async def fetch(self, sql, *params, **kw):
        self.fetch_sql.append(sql)
        assert sql is lag.LAG_SQL
        if self.stuck_fail:
            raise TimeoutError
        return self.stuck


@pytest.fixture
def sent(monkeypatch):
    mails: list[dict] = []
    monkeypatch.setattr(f, "send_notification", capture(mails))
    return mails


def _run(row, memory, **kw):
    pool = kw.pop("pool", None) or _Pool(row)
    return asyncio.run(f.check_v4_freshness(pool, memory=memory, **kw))


def test_daniela_is_copied_on_the_stopped_mail(sent) -> None:
    _run(_row(), f.AlertMemory())
    assert sent[0]["to"] == [DIEGO]
    assert sent[0]["cc"] == [OMAR, DANIELA]


def test_reminds_omar_every_6_hours_while_stopped(sent) -> None:
    memory = f.AlertMemory()
    _run(_row(), memory)
    for h in range(1, 6):  # hourly runs inside the 6 h: silent
        res = _run(_row(now=NOW + timedelta(hours=h)), memory)
        assert res["reason"] == "already_alerted"
    assert len(sent) == 1

    res = _run(_row(now=NOW + timedelta(hours=6)), memory)
    assert res["alerted"] is True and res.get("reminder") is True
    msg = sent[1]
    assert msg["to"] == [OMAR]
    assert msg["cc"] == [DIEGO, DANIELA]
    assert "STILL STOPPED" in msg["subject"] and "8 h 19 min" in msg["subject"]
    assert "reminder" in msg["html"].lower()

    _run(_row(now=NOW + timedelta(hours=7)), memory)
    assert len(sent) == 2
    _run(_row(now=NOW + timedelta(hours=12)), memory)
    assert len(sent) == 3


def test_a_failed_reminder_is_retried_next_hour(sent, monkeypatch) -> None:
    memory = f.AlertMemory()
    _run(_row(), memory)
    first_sent = memory.sent_at

    async def _down(**_kw):
        return {"sent": False, "reason": "graph_error"}

    monkeypatch.setattr(f, "send_notification", _down)
    res = _run(_row(now=NOW + timedelta(hours=6)), memory)
    assert res["alerted"] is False
    assert memory.sent_at == first_sent  # not advanced → next hour retries


def test_resume_clears_the_reminder_clock(sent) -> None:
    memory = f.AlertMemory()
    _run(_row(), memory)
    later = NOW + timedelta(hours=2)
    _run(_fresh(later), memory)
    assert memory.stamps == {} and memory.sent_at is None


def test_resumed_mail_counts_orders_still_a(sent) -> None:
    memory = f.AlertMemory()
    _run(_row(), memory)
    stuck = [{"id": "0123", "live_updated": NOW}] * 7
    pool = _Pool(_fresh(NOW + timedelta(hours=2)), stuck=stuck)
    _run(None, memory, pool=pool)
    msg = sent[-1]
    assert "resumed" in msg["subject"]
    assert "7 orders" in msg["html"] and pool.fetch_sql == [lag.LAG_SQL]
    assert msg["cc"] == [OMAR, DANIELA]


def test_resumed_mail_survives_a_failed_count(sent) -> None:
    memory = f.AlertMemory()
    _run(_row(), memory)
    pool = _Pool(_fresh(NOW + timedelta(hours=2)), stuck_fail=True)
    res = _run(None, memory, pool=pool)
    assert res["resumed"] == ["v4", "movement"]
    assert "could not be counted" in sent[-1]["html"]


def test_the_job_also_runs_at_0240() -> None:
    src = (Path(__file__).resolve().parents[1] / "app" / "main.py").read_text()
    assert 'hour="2,6-22", minute=40' in src
