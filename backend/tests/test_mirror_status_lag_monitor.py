"""Watchdog: gold v4 order status vs McLeod's live feed (§143).

From the 2026-11-01 DST fall-back the gold McLeod ETL skipped status changes
while ``max(updated_dt)`` stayed fresh — every freshness check read healthy.
This job must alert over the threshold, stay quiet at or under it, give the ETL
a grace period, and never raise.
"""

import asyncio
from datetime import datetime
from pathlib import Path

import pytest

from app.services import mirror_status_lag_monitor as m

T0 = datetime(2026, 11, 1, 11, 13)  # noqa: DTZ001 — gold stamps are naive CST


class _Pool:
    def __init__(self, ids=(), fail=False):
        self.rows = [{"id": i, "order_status": "P", "live_updated": T0} for i in ids]
        self.fail = fail
        self.sql: list[str] = []

    async def fetch(self, sql, *params):
        self.sql.append(sql)
        if self.fail:
            raise RuntimeError("permission denied for table app_augment_n8n_data_ra_rt")
        return self.rows


@pytest.fixture
def sent(monkeypatch):
    mails: list[dict] = []
    monkeypatch.setattr(m.settings, "RESEND_API_KEY", "re_test")
    monkeypatch.setattr(m.resend.Emails, "send", lambda msg: mails.append(msg))
    return mails


def _ids(n):
    return [f"03515{i:02d}" for i in range(n)]


def test_quiet_at_the_threshold(sent) -> None:
    res = asyncio.run(m.check_mirror_status_lag(_Pool(_ids(m.THRESHOLD))))
    assert res["healthy"] is True and res["stuck"] == m.THRESHOLD
    assert sent == []


def test_alerts_over_the_threshold(sent) -> None:
    res = asyncio.run(m.check_mirror_status_lag(_Pool(_ids(63))))
    assert res["healthy"] is False and res["alerted"] is True
    assert len(sent) == 1
    msg = sent[0]
    assert "63 orders" in msg["subject"]
    assert "0351500" in msg["html"] and "2026-11-01 11:13" in msg["html"]
    assert msg["to"] == ["dfrodriguez@unilinktransportation.com"]


def test_never_raises_on_a_query_failure(sent) -> None:
    res = asyncio.run(m.check_mirror_status_lag(_Pool(fail=True)))
    assert res["checked"] is False and res["reason"] == "query_failed"
    assert sent == []


def test_no_pool_is_a_skip() -> None:
    assert asyncio.run(m.check_mirror_status_lag(None))["reason"] == "no_pool"


def test_sql_shape() -> None:
    sql = m.LAG_SQL
    # Live feed holds TMS only; v4 pads its keys, the live table does not.
    assert "v.company_id IN ('TMS'," in sql
    assert "TRIM(v.company_id) AS co, TRIM(v.id) AS id" in sql
    assert "l.co = a.co AND l.id = a.id" in sql
    # The LATEST live row decides, and its status is the signal — never "has a
    # pickup arrival"; the status filter runs AFTER the dedupe.
    assert "r.updated_dt DESC NULLS LAST, r.movement_id DESC" in sql
    assert sql.index("DISTINCT ON (r.company_id, r.id)") < sql.index("l.order_status IN ('P', 'D', 'V')")
    assert "origin_actual_arrival" not in sql
    # Grace measured on v4's own last write (the live row is re-stamped by GPS).
    assert f"v.updated_dt < now() - interval '{m.GRACE_HOURS} hours'" in sql and m.GRACE_HOURS >= 1
    assert "is_deleted" in sql


def test_the_job_is_scheduled_and_on_the_roster() -> None:
    src = (Path(__file__).resolve().parents[1] / "app" / "main.py").read_text()
    roster = src.split("EXPECTED_JOBS = {", 1)[1].split("}", 1)[0]
    assert '"daily_mirror_status_lag_check":' in roster
    assert 'id="daily_mirror_status_lag_check"' in src
    body = src.split("async def _scheduled_mirror_status_lag_check", 1)[1].split("\nasync def ", 1)[0]
    assert "check_mirror_status_lag(pool)" in body
