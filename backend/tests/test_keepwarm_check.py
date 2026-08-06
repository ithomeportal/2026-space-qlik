"""Tests for the keep-warm watchdog's decision logic.

The SQL itself is verified separately by replaying it against the live DB in a
rolled-back transaction. What matters here is *when the watchdog decides to
email*, because both mistakes are costly: a missed stall leaves the portal on a
single pinger with nobody told, and a spurious alert re-creates exactly the
notification noise this change removed.
"""

import pytest

from app.services import keepwarm_monitor as km


class _FakeConn:
    def __init__(self, rows):
        self._rows = rows

    async def fetch(self, *_a, **_kw):
        return self._rows


class _FakeAcquire:
    def __init__(self, conn):
        self._conn = conn

    async def __aenter__(self):
        return self._conn

    async def __aexit__(self, *_exc):
        return False


class _FakePool:
    """Minimal stand-in for an asyncpg pool."""

    def __init__(self, rows):
        self._conn = _FakeConn(rows)
        self.executed: list[str] = []

    def acquire(self):
        return _FakeAcquire(self._conn)

    async def execute(self, sql, *_a):
        self.executed.append(sql)


def _row(source, *, age_seconds=10, stale=False, max_gap=0, window_seconds=86400,
         ping_count=288):
    return {
        "source": source,
        "last_seen": None,
        "ping_count": ping_count,
        "max_gap_seconds": max_gap,
        "age_seconds": age_seconds,
        "stale": stale,
        "window_seconds": window_seconds,
    }


@pytest.fixture
def sent(monkeypatch):
    """Capture Resend sends instead of emailing anyone."""
    calls = []
    monkeypatch.setattr(km.settings, "RESEND_API_KEY", "test-key", raising=False)
    monkeypatch.setattr(km.resend.Emails, "send", lambda payload: calls.append(payload))
    monkeypatch.setattr(
        km, "partition_recipients", lambda addrs: (list(addrs), [])
    )
    return calls


@pytest.mark.asyncio
async def test_no_pool_is_a_no_op():
    r = await km.check_keepwarm(None)
    assert r == {"checked": False, "reason": "no_pool"}


@pytest.mark.asyncio
async def test_healthy_pair_sends_nothing(sent):
    pool = _FakePool([_row(km.SOURCE_N8N), _row(km.SOURCE_SYSTEMD)])
    r = await km.check_keepwarm(pool)
    assert r["degraded"] is False
    assert sent == []


@pytest.mark.asyncio
async def test_empty_ledger_does_not_alert_on_its_own_rollout(sent):
    # Right after deploy no ping has landed yet; alerting here would mean the
    # watchdog's first act is a false alarm about itself.
    pool = _FakePool([])
    r = await km.check_keepwarm(pool)
    assert r["degraded"] is False
    assert r["reason"] == "no_pings_yet"
    assert sent == []


@pytest.mark.asyncio
async def test_missing_source_ignored_while_ledger_is_young(sent):
    # Only n8n has ever pinged and the ledger is 10 min old — the systemd timer
    # simply hasn't had its turn yet. Must stay quiet.
    pool = _FakePool([_row(km.SOURCE_N8N, window_seconds=600)])
    r = await km.check_keepwarm(pool)
    assert r["degraded"] is False
    assert sent == []


@pytest.mark.asyncio
async def test_missing_source_alerts_once_ledger_is_mature(sent):
    # Same shape, but the ledger has been live 24h: the systemd timer really has
    # never pinged.
    pool = _FakePool([_row(km.SOURCE_N8N, window_seconds=86400)])
    r = await km.check_keepwarm(pool)
    assert r["degraded"] is True
    assert len(sent) == 1
    assert "never seen" in sent[0]["html"]


@pytest.mark.asyncio
async def test_stalled_primary_alerts(sent):
    pool = _FakePool([
        _row(km.SOURCE_N8N, age_seconds=5400, stale=True),
        _row(km.SOURCE_SYSTEMD),
    ])
    r = await km.check_keepwarm(pool)
    assert r["degraded"] is True
    assert len(sent) == 1
    assert "stalled" in sent[0]["html"]
    assert "90 min ago" in sent[0]["html"]


@pytest.mark.asyncio
async def test_self_healed_gap_still_reported(sent):
    # Beating right now, but it went quiet for 47 min overnight. A last_seen-only
    # check would call this healthy and the intermittent stall would never surface.
    pool = _FakePool([
        _row(km.SOURCE_N8N, max_gap=2820),
        _row(km.SOURCE_SYSTEMD),
    ])
    r = await km.check_keepwarm(pool)
    assert r["degraded"] is True
    assert "47 min gap" in sent[0]["html"]


@pytest.mark.asyncio
async def test_gap_within_threshold_is_not_reported(sent):
    pool = _FakePool([
        _row(km.SOURCE_N8N, max_gap=km.STALE_MINUTES * 60 - 1),
        _row(km.SOURCE_SYSTEMD),
    ])
    r = await km.check_keepwarm(pool)
    assert r["degraded"] is False
    assert sent == []


@pytest.mark.asyncio
async def test_gap_window_is_reset_after_each_check(sent):
    pool = _FakePool([_row(km.SOURCE_N8N), _row(km.SOURCE_SYSTEMD)])
    await km.check_keepwarm(pool)
    assert any("max_gap_seconds = 0" in s for s in pool.executed), (
        "window must reset or one bad gap would re-alert every day forever"
    )


@pytest.mark.asyncio
async def test_missing_resend_key_degrades_quietly(monkeypatch):
    monkeypatch.setattr(km.settings, "RESEND_API_KEY", "", raising=False)
    pool = _FakePool([
        _row(km.SOURCE_N8N, age_seconds=5400, stale=True),
        _row(km.SOURCE_SYSTEMD),
    ])
    r = await km.check_keepwarm(pool)
    assert r["degraded"] is True and r["alerted"] is False
    assert r["reason"] == "no_resend_key"


@pytest.mark.asyncio
async def test_resend_failure_never_raises(monkeypatch):
    def boom(_payload):
        raise RuntimeError("resend 502")

    monkeypatch.setattr(km.settings, "RESEND_API_KEY", "test-key", raising=False)
    monkeypatch.setattr(km.resend.Emails, "send", boom)
    monkeypatch.setattr(km, "partition_recipients", lambda a: (list(a), []))
    pool = _FakePool([
        _row(km.SOURCE_N8N, age_seconds=5400, stale=True),
        _row(km.SOURCE_SYSTEMD),
    ])
    r = await km.check_keepwarm(pool)
    assert r["degraded"] is True and r["alerted"] is False
    assert r["reason"] == "resend_failed"


@pytest.mark.asyncio
async def test_non_company_recipients_are_dropped_not_emailed(monkeypatch):
    # Outbound mail is restricted to verified tenant domains, and the guard lives
    # at the transport. If it strips every recipient we must degrade quietly
    # rather than attempt a send.
    sends = []
    monkeypatch.setattr(km.settings, "RESEND_API_KEY", "test-key", raising=False)
    monkeypatch.setattr(km.resend.Emails, "send", lambda p: sends.append(p))
    monkeypatch.setattr(
        km, "partition_recipients", lambda a: ([], ["outsider@example.com"])
    )
    pool = _FakePool([
        _row(km.SOURCE_N8N, age_seconds=5400, stale=True),
        _row(km.SOURCE_SYSTEMD),
    ])
    r = await km.check_keepwarm(pool)
    assert r["alerted"] is False and r["reason"] == "no_recipients"
    assert sends == []


@pytest.mark.asyncio
async def test_query_failure_never_raises():
    class Boom(_FakePool):
        def acquire(self):
            raise RuntimeError("connection reset")

    r = await km.check_keepwarm(Boom([]))
    assert r["checked"] is False and r["reason"] == "query_failed"
