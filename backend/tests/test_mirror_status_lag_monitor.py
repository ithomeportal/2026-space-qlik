"""Watchdog: gold v4 order status vs McLeod's live feed (§143).

From the 2026-11-01 DST fall-back the gold McLeod ETL skipped status changes
while ``max(updated_dt)`` stayed fresh — every freshness check read healthy.
This job must alert over the threshold, stay quiet at or under it, give the ETL
a grace period, and never raise.
"""

import asyncio
from datetime import date, datetime
from pathlib import Path

import pytest
from graph_fake import capture

from app.services import mirror_status_lag_monitor as m

T0 = datetime(2026, 11, 1, 11, 13)  # noqa: DTZ001 — gold stamps are naive CST


TODAY = date(2026, 11, 3)
LAST = datetime(2026, 11, 3, 5, 10)  # noqa: DTZ001
V4_FROZEN = datetime(2026, 11, 10, 23, 20, 31)  # noqa: DTZ001
FROZEN_OFFSET = -424 * 60  # the 2026-11-11 06:25 mail


def _day(day, moved, still_a, missing=0, moved_recent=0, still_a_recent=0, last_stuck=None):
    return {
        "day": day, "moved": moved, "still_a": still_a, "missing": missing,
        "moved_recent": moved_recent, "still_a_recent": still_a_recent, "last_stuck": last_stuck,
    }


DAILY = [
    _day(date(2026, 10, 31), 42, 0),
    _day(date(2026, 11, 2), 529, 33, 4, moved_recent=80, still_a_recent=9, last_stuck=T0),
    _day(TODAY, 49, 11, moved_recent=49, still_a_recent=11, last_stuck=LAST),
]


class _Pool:
    """Answers each of the job's three statements; any of them can be made to fail."""

    def __init__(self, ids=(), fail=False, offset_s=3600, daily=DAILY, fail_extras=False,
                 events=245, fail_fresh=False):
        self.rows = [{"id": i, "order_status": "P", "live_updated": T0} for i in ids]
        self.fail = fail
        self.fail_extras = fail_extras
        self.events = events
        self.fail_fresh = fail_fresh
        self.offset_s = offset_s
        self.daily = daily
        self.sql: list[str] = []
        self.params: list[tuple] = []

    async def fetchrow(self, sql, *params):
        self.sql.append(sql)
        if self.fail_extras:
            raise RuntimeError("canceling statement due to statement timeout")
        if sql is m.FRESHNESS_SQL:
            if self.fail_fresh:
                raise RuntimeError("canceling statement due to statement timeout")
            return {"v4_last": V4_FROZEN, "events_since_v4": self.events}
        assert sql is m.OFFSET_SQL
        return {"offset_s": self.offset_s}

    async def fetch(self, sql, *params):
        self.sql.append(sql)
        self.params.append(params)
        if sql is m.DAILY_SQL:
            if self.fail_extras:
                raise RuntimeError("canceling statement due to statement timeout")
            return self.daily
        assert sql is m.LAG_SQL
        if self.fail:
            raise RuntimeError("permission denied for table app_augment_n8n_data_ra_rt")
        return self.rows


@pytest.fixture
def sent(monkeypatch):
    mails: list[dict] = []
    monkeypatch.setattr(m, "cst_today", lambda: TODAY)
    monkeypatch.setattr(m, "send_notification", capture(mails))
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
    # The Data / BI owner of the load is copied (2026-11-03).
    assert msg["cc"] == ["oorozco@unilinktransportation.com"]


def test_mail_carries_the_escalation_evidence(sent) -> None:
    asyncio.run(m.check_mirror_status_lag(_Pool(_ids(57))))
    html = sent[0]["html"]
    assert "STILL SKIPPING: 20 of 129" in html and "(16%)" in html
    assert "latest skipped change 11-03 05:10" in html
    assert "+60 min" in html and "FUTURE" in html
    # Per-day table: the 11-02 row with its still-A and missing counts.
    assert "Mon 11-02" in html and ">33<" in html and ">4<" in html


def test_grace_adds_back_the_measured_offset(sent) -> None:
    pool = _Pool(_ids(9), offset_s=3600)  # over threshold: both queries run
    asyncio.run(m.check_mirror_status_lag(pool))
    assert pool.params[0] == (3600,)
    assert pool.params[1] == (3600,)  # the per-day table uses the SAME grace
    # A stamp behind the clock (normal 15-min lag) changes nothing; a garbage
    # far-future stamp is capped so it cannot eat the whole grace (review 11-03).
    assert m.clamp_offset(-600) == 0 and m.clamp_offset(None) == 0
    assert m.clamp_offset(10**7) == m.MAX_OFFSET_SECONDS
    assert m.GRACE_HOURS * 3600 - m.MAX_OFFSET_SECONDS >= 3600


def test_extras_fail_soft(sent) -> None:
    pool = _Pool(_ids(9), fail_extras=True)
    res = asyncio.run(m.check_mirror_status_lag(pool))
    assert res["alerted"] is True and res["verdict"] is None
    assert pool.params[0] == (0,)  # unknown offset = unadjusted grace
    assert "unavailable" in sent[0]["html"] and "STILL SKIPPING" not in sent[0]["html"]


@pytest.mark.parametrize(
    ("daily", "expected"),
    [
        (DAILY, "STILL SKIPPING"),
        # Old backlog (still_a) but nothing stuck in the last 24 h = fixed load.
        ([_day(date(2026, 11, 2), 529, 33, moved_recent=0), _day(TODAY, 40, 0, moved_recent=40)],
         "Backlog only"),
        # Missing-from-v4 is shown, never a verdict input (can be a late entry).
        ([_day(TODAY, 40, 0, missing=2, moved_recent=40)], "Backlog only"),
        ([], "No settled McLeod moves"),
    ],
)
def test_verdict(daily, expected) -> None:
    assert m.verdict(daily).startswith(expected)
    assert m.verdict(None) is None


def test_non_company_cc_is_dropped(sent) -> None:
    asyncio.run(m.check_mirror_status_lag(_Pool(_ids(9)), cc=("someone@gmail.com",)))
    assert "cc" not in sent[0]


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
    # Session-timezone independent CST clock, plus the measured v4 offset.
    assert f"< (now() AT TIME ZONE 'America/Chicago') - interval '{m.GRACE_HOURS} hours'" in sql
    assert "make_interval(secs => $1::int)" in sql and m.GRACE_HOURS >= 1
    assert "is_deleted" in sql


def test_daily_sql_shape() -> None:
    sql = m.DAILY_SQL
    # Latest live row decides; v4's latest row decides; LEFT JOIN keeps orders v4 lacks.
    assert "r.updated_dt DESC NULLS LAST, r.movement_id DESC" in sql
    assert "LEFT JOIN v ON v.co = l.co AND v.id = l.id" in sql
    assert "v.company_id IN ('TMS'," in sql
    assert f"interval '{m.SETTLE_MINUTES} minutes'" in sql
    # Bucketed by the EVENT, never the live updated_dt (n8n re-stamps the row).
    assert "WHEN 'P' THEN COALESCE(r.origin_actual_arrival, r.updated_dt)" in sql
    assert "WHEN 'D' THEN COALESCE(r.dest_actual_arrival, r.updated_dt)" in sql
    assert "SELECT event_dt::date AS day" in sql
    # still A uses the same offset-adjusted grace as LAG_SQL.
    assert m._GRACE_BOUND in sql and m._GRACE_BOUND in m.LAG_SQL
    assert "WHERE v.company_id IN ('TMS'," in m.OFFSET_SQL


def test_the_job_is_scheduled_and_on_the_roster() -> None:
    src = (Path(__file__).resolve().parents[1] / "app" / "main.py").read_text()
    roster = src.split("EXPECTED_JOBS = {", 1)[1].split("}", 1)[0]
    assert '"daily_mirror_status_lag_check":' in roster
    assert 'id="daily_mirror_status_lag_check"' in src
    body = src.split("async def _scheduled_mirror_status_lag_check", 1)[1].split("\nasync def ", 1)[0]
    assert "check_mirror_status_lag(pool)" in body


# ── v3 (2026-11-11): a STOPPED load is not "still skipping" ─────────────────

def test_a_stopped_load_says_stopped(sent) -> None:
    asyncio.run(m.check_mirror_status_lag(_Pool(_ids(17), offset_s=FROZEN_OFFSET)))
    msg = sent[0]
    assert "STOPPED" in msg["subject"] and "7 h 4 min" in msg["subject"]
    html = msg["html"]
    assert "LOAD STOPPED" in html and "2026-11-10 23:20" in html and "245 pickups/deliveries" in html
    # The skip verdict and the "freshness stays green" claim are both false now.
    assert "STILL SKIPPING" not in html and "Freshness checks stay green" not in html
    assert "−424 min ⚠ v4 not written for over 2 h<" in html


def test_a_stopped_load_alerts_under_the_threshold(sent) -> None:
    res = asyncio.run(m.check_mirror_status_lag(_Pool(_ids(1), offset_s=FROZEN_OFFSET)))
    assert res["alerted"] is True and res["stopped"] is True
    assert len(sent) == 1


def test_normal_lag_is_not_stopped(sent) -> None:
    res = asyncio.run(m.check_mirror_status_lag(_Pool(_ids(2), offset_s=-14 * 60)))
    assert res["healthy"] is True and sent == []
    ev = {"events_since_v4": m.MIN_EVENTS}
    assert m.is_stopped(-14 * 60, ev) is False and m.is_stopped(None, ev) is False
    assert m.is_stopped(-(m.STALE_MINUTES * 60 + 1), ev) is True
    assert m.is_stopped(-(m.STALE_MINUTES * 60 + 1), None) is False


def test_skipping_mail_keeps_its_wording(sent) -> None:
    asyncio.run(m.check_mirror_status_lag(_Pool(_ids(9))))
    html = sent[0]["html"]
    assert "Freshness checks stay green" in html and "LOAD STOPPED" not in html
    assert "STOPPED" not in sent[0]["subject"]


def test_stopped_evidence_fails_soft(sent) -> None:
    # Offset read fine, the live-feed evidence query fails: never "stopped" on
    # silence alone; the ordinary count alert still goes out.
    pool = _Pool(_ids(9), offset_s=FROZEN_OFFSET, fail_fresh=True)
    res = asyncio.run(m.check_mirror_status_lag(pool))
    assert res["alerted"] is True and res["stopped"] is False
    assert "STOPPED" not in sent[0]["subject"] and "−424 min" in sent[0]["html"]


def test_a_quiet_morning_is_not_stopped(sent) -> None:
    # v4 is change-stamped: hours of silence with no McLeod stops is normal (review 11-11).
    res = asyncio.run(m.check_mirror_status_lag(_Pool(_ids(2), offset_s=FROZEN_OFFSET, events=0)))
    assert res["healthy"] is True and res["stopped"] is False and sent == []


def test_stopped_mail_shows_the_zero_threshold(sent) -> None:
    asyncio.run(m.check_mirror_status_lag(_Pool(_ids(1), offset_s=FROZEN_OFFSET)))
    assert "0 (load stopped)" in sent[0]["html"]


def test_a_stopped_load_alerts_with_nothing_stuck_yet(sent) -> None:
    res = asyncio.run(m.check_mirror_status_lag(_Pool((), offset_s=FROZEN_OFFSET)))
    assert res["alerted"] is True and "LOAD STOPPED" in sent[0]["html"]
