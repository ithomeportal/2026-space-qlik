"""123LoadBoard removal — pins the 2026-10-31 contract end.

UNILINK's 123LB contract ended 31-Oct-2026 and the API was shut off the next
day. Had the nightly prewarm kept calling it, every lane would fail and the job
would report `degraded_sources: ["lb123"]` forever — a permanent false alarm
that hides a real SONAR failure. These tests pin that:
  1. no 123LB client code survives in the runtime modules;
  2. the prewarm never reads/writes source='lb123' and never reports it degraded;
  3. the prewarm still degrades on a real SONAR failure.
Historical lb123 rows in lane_market_rates are kept on purpose (not tested here).
"""

import inspect

import pytest

from app.routers import carriers_savings
from app.services import lane_rates, lane_rates_prewarm
from app.services.lane_rates import MonthlyRate


def test_no_lb123_client_left_in_lane_rates():
    for name in ("fetch_lb123_history", "_lb123_token_value",
                 "_map_lb123_equipment", "_LB123_BASE"):
        assert not hasattr(lane_rates, name), name


@pytest.mark.parametrize("module", [lane_rates_prewarm, carriers_savings])
def test_runtime_modules_never_touch_lb123(module):
    src = inspect.getsource(module)
    assert "fetch_lb123" not in src
    assert '"lb123"' not in src
    assert "123loadboard.com" not in src.lower()


class _FakePool:
    async def fetch(self, *_args, **_kwargs):
        return [{"origin_name": "Dallas, TX", "dest_name": "Atlanta, GA"}]


def _patch_prewarm(monkeypatch, *, sonar_history, sonar_ok=True):
    sources_read: list[str] = []
    sources_written: list[str] = []

    async def fake_cached(_pool, _lanes, _yms, source):
        sources_read.append(source)
        return {}

    async def fake_upsert(_pool, _ln, source, _history):
        sources_written.append(source)

    async def fake_sonar(_client, _ln, months=24):
        return sonar_history

    monkeypatch.setattr(lane_rates_prewarm, "get_cached_rates", fake_cached)
    monkeypatch.setattr(lane_rates_prewarm, "upsert_rates", fake_upsert)
    monkeypatch.setattr(lane_rates_prewarm, "fetch_sonar_history", fake_sonar)
    monkeypatch.setattr(lane_rates_prewarm, "sonar_status",
                        lambda: {"ok": sonar_ok, "reason": None if sonar_ok else "test"})
    return sources_read, sources_written


def _rate(ym: str) -> MonthlyRate:
    return MonthlyRate(year_month=ym, avg_rate=2000.0, min_rate=None, max_rate=None,
                       avg_rpm=2.5, min_rpm=None, max_rpm=None,
                       loads_included=10, mileage=800, raw={})


@pytest.mark.asyncio
async def test_prewarm_is_sonar_only_and_ok(monkeypatch):
    read, written = _patch_prewarm(monkeypatch, sonar_history=[_rate("2026-10")])
    summary = await lane_rates_prewarm.prewarm_lane_market_rates(_FakePool())

    assert read == ["sonar"]
    assert written == ["sonar"]
    assert summary["status"] == "ok"
    assert summary["degraded_sources"] == []
    assert "lb123" not in summary
    assert summary["sonar"]["ok"] == 1


@pytest.mark.asyncio
async def test_prewarm_degrades_only_for_sonar(monkeypatch):
    _patch_prewarm(monkeypatch, sonar_history=[], sonar_ok=True)
    summary = await lane_rates_prewarm.prewarm_lane_market_rates(_FakePool())

    assert summary["status"] == "degraded"
    assert summary["degraded_sources"] == ["sonar"]
