"""Watchdog for the revenue-code lookup behind the MX division rule (§135).

A frozen ``mcleod_gld_cash_flow_dinfo`` does not break any report — MX orders
just fall back to the TM marker, silently. So the only signal is this job:
it must alert on a frozen table and on MX orders with no code, stay quiet on a
normal overnight gap, and never raise.
"""

import asyncio
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from app.services import revenue_code_monitor as m

# Naive on purpose: gold `updated_dt` is a naive CST timestamp.
NOW = datetime(2026, 10, 29, 6, 20)  # noqa: DTZ001


class _Conn:
    def __init__(self, row=None, missing=(), fail=False):
        self.row = row or {"v4_last": NOW, "dinfo_last": NOW - timedelta(minutes=30)}
        self.missing = [{"id": i} for i in missing]
        self.fail = fail
        self.sql: list[str] = []

    async def fetchrow(self, sql):
        self.sql.append(sql)
        if self.fail:
            raise RuntimeError("gold unreachable")
        return self.row

    async def fetch(self, sql):
        self.sql.append(sql)
        return self.missing


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


@pytest.fixture
def sent(monkeypatch):
    mails: list[dict] = []
    monkeypatch.setattr(m.settings, "RESEND_API_KEY", "re_test")
    monkeypatch.setattr(m.resend.Emails, "send", lambda msg: mails.append(msg))
    return mails


def _run(conn):
    return asyncio.run(m.check_revenue_code_lookup(_Pool(conn)))


# ---------------------------------------------------------------------------
# assess — the decision itself
# ---------------------------------------------------------------------------


def test_an_overnight_gap_is_healthy() -> None:
    # dinfo goes nearly quiet overnight / at weekends while v4 keeps a write
    # or two: the lag is judged against v4, with a 24 h margin.
    assert m.assess(NOW, NOW - timedelta(hours=10), []) == []


def test_a_frozen_table_is_reported() -> None:
    [problem] = m.assess(NOW, NOW - timedelta(hours=30), [])
    assert "looks frozen" in problem and "30 h" in problem


def test_an_empty_table_is_reported() -> None:
    assert m.assess(NOW, None, []) and "empty" in m.assess(NOW, None, [])[0]


def test_missing_mx_orders_are_reported_with_examples() -> None:
    ids = [f"00075{n:02d}" for n in range(15)]
    [problem] = m.assess(NOW, NOW, ids)
    assert problem.startswith("15 McLeod MX order(s)")
    assert ids[0] in problem and ids[m.SAMPLE_IDS] not in problem  # capped sample


# ---------------------------------------------------------------------------
# The job — alerts, silence, never raises
# ---------------------------------------------------------------------------


def test_healthy_sends_nothing(sent) -> None:
    out = _run(_Conn())
    assert out["healthy"] is True and sent == []


def test_frozen_sends_one_alert(sent) -> None:
    out = _run(_Conn(row={"v4_last": NOW, "dinfo_last": NOW - timedelta(days=3)}))
    assert out["alerted"] is True and len(sent) == 1
    assert "falling back" in sent[0]["subject"]
    assert "TM4" in sent[0]["html"] and "§135" in sent[0]["html"]


def test_coverage_gap_sends_an_alert(sent) -> None:
    out = _run(_Conn(missing=["0007601"]))
    assert out["missing"] == 1 and out["alerted"] is True
    assert "0007601" in sent[0]["html"]


def test_a_query_failure_is_swallowed(sent) -> None:
    out = _run(_Conn(fail=True))
    assert out == {"checked": False, "reason": "query_failed", "error": "gold unreachable"}
    assert sent == []


def test_no_pool_is_a_skip_not_a_crash() -> None:
    assert asyncio.run(m.check_revenue_code_lookup(None))["reason"] == "no_pool"


def test_without_a_resend_key_it_reports_but_cannot_mail(monkeypatch) -> None:
    monkeypatch.setattr(m.settings, "RESEND_API_KEY", "")
    out = _run(_Conn(missing=["0007601"]))
    assert out["healthy"] is False and out["reason"] == "no_resend_key"


# ---------------------------------------------------------------------------
# The SQL — the same population and key the division rule uses
# ---------------------------------------------------------------------------


def test_coverage_probe_is_the_rules_population_and_key() -> None:
    sql = m.MISSING_SQL
    # MX only — the companies the rule reads a revenue code for.
    assert "v.company_id IN ('TMS3')" in sql
    # Both PK columns, unpadded on neither side (v4 and dinfo pad alike).
    assert "d.company_id = v.company_id AND d.id = v.id" in sql
    # A day's grace for the normal sync lag.
    assert "created_dt <  now() - interval '1 day'" in sql


def test_the_job_is_scheduled_and_on_the_roster() -> None:
    src = (Path(__file__).resolve().parents[1] / "app" / "main.py").read_text()
    roster = src.split("EXPECTED_JOBS = {", 1)[1].split("}", 1)[0]
    assert '"daily_revenue_code_check":' in roster
    assert 'id="daily_revenue_code_check"' in src
    body = src.split("async def _scheduled_revenue_code_check", 1)[1].split("\nasync def ", 1)[0]
    assert "check_revenue_code_lookup(pool)" in body
