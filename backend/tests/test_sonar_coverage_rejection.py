"""Ops Portal "By Lane" — Origin / Dest Rejection % from SONAR (Bruno 2026-10-16 R6).

What these pin (all offline — httpx is a MockTransport, the hub pool a dict):
  * the request body is the pricing portal's coverage-guide shape, batched
    ``BATCH_SIZE`` lanes per request, capped at ``MAX_FETCH_LANES`` per call;
  * only US→US lanes with a ZIP are ever sent — a Mexican ZIP that is also a
    valid US ZIP (Juárez 67250 = Kansas) must NOT reach SONAR;
  * response mapping (percent units, 0 kept, lane_id matching, absent = no data);
  * a fresh cache row avoids HTTP; an expired one refetches; an empty answer is
    cached on its own (shorter) TTL;
  * HTTP errors, exceptions and timeouts give nulls, never an exception, and a
    failed request is not cached but opens a cooldown;
  * the endpoint merges values per lane and the table still renders.
"""

from __future__ import annotations

import asyncio
import importlib
import json
from datetime import date, datetime, timedelta, timezone
from types import SimpleNamespace

import httpx
import pytest

from app.services import lane_rates
from app.services import sonar_coverage as sc

actuals_mod = importlib.import_module("app.routers.ops_portal_overview.actuals")


@pytest.fixture(autouse=True)
def _state(monkeypatch):
    sc.reset_state_for_tests()
    monkeypatch.setattr(lane_rates, "_sonar_disabled_reason", None, raising=False)
    monkeypatch.setattr(lane_rates, "_static_token_rejected", False, raising=False)
    monkeypatch.setattr(lane_rates, "_sonar_token", None, raising=False)
    monkeypatch.delenv("SONAR_TOKEN", raising=False)
    monkeypatch.setenv("SONAR_USERNAME", "u")
    monkeypatch.setenv("SONAR_PASSWORD", "p")
    yield
    sc.reset_state_for_tests()


class HubPool:
    """In-memory stand-in for sonar_lane_rejection_cache."""

    def __init__(self, rows: dict | None = None) -> None:
        self.rows: dict[tuple, dict] = dict(rows or {})
        self.writes = 0

    async def fetch(self, sql, o, d, e):
        assert "sonar_lane_rejection_cache" in sql
        out = []
        for key in zip(o, d, e):
            if key in self.rows:
                out.append({"origin_key": key[0], "dest_key": key[1], "equipment": key[2], **self.rows[key]})
        return out

    async def executemany(self, sql, args):
        assert "ON CONFLICT" in sql
        self.writes += 1
        for o, d, e, op, dp, has in args:
            self.rows[(o, d, e)] = {
                "origin_rejection_pct": op, "dest_rejection_pct": dp,
                "has_data": has, "fetched_at": datetime.now(timezone.utc),
            }


def _sonar(handler):
    """MockTransport client. Auth is answered here; coverage calls go to ``handler``."""
    calls: list[dict] = []

    def route(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/Credential/authenticate":
            return httpx.Response(200, json={"token": "tkn"})
        assert request.url.path == "/v2/truckload/coverage_guide"
        body = json.loads(request.content)
        calls.append(body)
        return handler(body)

    return httpx.AsyncClient(transport=httpx.MockTransport(route)), calls


def _echo(body):
    return httpx.Response(200, json={"lanes": [
        {"lane_id": ln["lane_id"], "origin_rejection_percent": 12.5,
         "destination_rejection_percent": 3.25}
        for ln in body["lanes"]
    ]})


K1 = sc.LaneKey("76504", "75172", "VAN")
K2 = sc.LaneKey("76712", "78537", "REEFER")


# ---------------------------------------------------------------------------
# Lane resolution
# ---------------------------------------------------------------------------


def test_location_prefers_zip5_then_zip3_us_only():
    assert sc.location_code("TX", "76504     ") == "76504"
    assert sc.location_code("tx", "765") == "765"
    assert sc.location_code("TX", "") is None            # never a bare state
    assert sc.location_code("TX", None) is None
    # Juárez: 67250 is ALSO a Kansas ZIP — the state whitelist must stop it.
    assert sc.location_code("NX", "67250") is None
    assert sc.location_code("TM", "88783") is None


def test_lane_key_needs_both_ends_and_maps_equipment():
    assert sc.lane_key("TX", "76504", "TM", "88783", "Van") is None
    assert sc.lane_key("TX", "76504", "TX", "75172", "DRY VAN NO MORE THAN 9 YEARS OLD") == K1
    assert sc.lane_key("TX", "76712", "TX", "78537", "Reefer").equipment == "REEFER"
    assert sc.lane_key("TX", "76712", "TX", "78537", "Flatbed").equipment == "FLATBED"
    assert sc.lane_key("TX", "76712", "TX", "78537", "Power Only").equipment == "VAN"
    assert sc.lane_key("TX", "76712", "TX", "78537", None).equipment == "VAN"


def test_request_body_matches_pricing_portal_shape():
    body = sc.build_request_body([K1])
    assert body == {"lanes": [{
        "lane_id": K1.lane_id, "origin": "76504", "origin_country_code": "USA",
        "destination": "75172", "destination_country_code": "USA", "equipment_type": "VAN",
    }]}


# ---------------------------------------------------------------------------
# Response mapping
# ---------------------------------------------------------------------------


def test_parse_maps_by_lane_id_keeps_zero_and_marks_absent_empty():
    data = {"lanes": [
        {"lane_id": K2.lane_id, "origin_rejection_percent": 0, "destination_rejection_percent": "4.5"},
    ]}
    got = sc.parse_response(data, [K1, K2])
    assert got[K2] == sc.Rejection(0.0, 4.5)
    assert got[K2].has_data
    assert got[K1] == sc.Rejection(None, None) and not got[K1].has_data


def test_parse_without_lane_id_only_trusted_for_single_lane():
    row = {"origin_rejection_percent": 9.0, "destination_rejection_percent": 1.0}
    assert sc.parse_response({"lanes": [row]}, [K1])[K1] == sc.Rejection(9.0, 1.0)
    multi = sc.parse_response({"lanes": [row]}, [K1, K2])
    assert not multi[K1].has_data and not multi[K2].has_data


def test_parse_tolerates_garbage():
    assert not sc.parse_response(None, [K1])[K1].has_data
    assert not sc.parse_response({"errors": [{"error_found": "x"}]}, [K1])[K1].has_data


# ---------------------------------------------------------------------------
# Fetch, batching, cache
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_batches_and_caps_requests(monkeypatch):
    keys = [sc.LaneKey(f"{75000 + i:05d}", "60601", "VAN") for i in range(sc.MAX_FETCH_LANES + 30)]
    client, calls = _sonar(_echo)
    pool = HubPool()
    got = await sc.get_rejections(pool, keys, client=client)
    assert [len(c["lanes"]) for c in calls] == [sc.BATCH_SIZE] * (sc.MAX_FETCH_LANES // sc.BATCH_SIZE)
    assert len(got) == sc.MAX_FETCH_LANES
    assert got[keys[0]].origin_rejection_pct == 12.5
    assert got[keys[0]].dest_rejection_pct == 3.25
    assert len(pool.rows) == sc.MAX_FETCH_LANES and pool.writes == len(calls)


@pytest.mark.asyncio
async def test_fresh_cache_hit_avoids_http():
    now = datetime.now(timezone.utc)
    pool = HubPool({(K1.origin_key, K1.dest_key, K1.equipment): {
        "origin_rejection_pct": 7, "dest_rejection_pct": 2, "has_data": True,
        "fetched_at": now - timedelta(hours=23)}})
    client, calls = _sonar(_echo)
    got = await sc.get_rejections(pool, [K1, K1, None], client=client)
    assert calls == []
    assert got[K1].origin_rejection_pct == 7.0


@pytest.mark.asyncio
async def test_expired_cache_refetches():
    pool = HubPool({(K1.origin_key, K1.dest_key, K1.equipment): {
        "origin_rejection_pct": 7, "dest_rejection_pct": 2, "has_data": True,
        "fetched_at": datetime.now(timezone.utc) - timedelta(hours=25)}})
    client, calls = _sonar(_echo)
    got = await sc.get_rejections(pool, [K1], client=client)
    assert len(calls) == 1
    assert got[K1].origin_rejection_pct == 12.5


@pytest.mark.asyncio
async def test_empty_answer_is_cached_on_its_own_ttl():
    client, calls = _sonar(lambda body: httpx.Response(200, json={"lanes": []}))
    pool = HubPool()
    got = await sc.get_rejections(pool, [K1], client=client)
    assert not got[K1].has_data
    assert pool.rows[(K1.origin_key, K1.dest_key, K1.equipment)]["has_data"] is False
    await sc.get_rejections(pool, [K1], client=client)
    assert len(calls) == 1                                   # negative cache hit
    # Past EMPTY_TTL (but well inside the 24 h data TTL) it is asked again.
    pool.rows[(K1.origin_key, K1.dest_key, K1.equipment)]["fetched_at"] = (
        datetime.now(timezone.utc) - sc.EMPTY_TTL - timedelta(minutes=1))
    await sc.get_rejections(pool, [K1], client=client)
    assert len(calls) == 2


@pytest.mark.asyncio
@pytest.mark.parametrize("handler", [
    lambda body: httpx.Response(500, text="boom"),
    lambda body: httpx.Response(429, text="slow down"),
    lambda body: (_ for _ in ()).throw(httpx.ConnectError("down")),
])
async def test_errors_give_nulls_not_cached_and_cool_down(handler):
    client, calls = _sonar(handler)
    pool = HubPool()
    got = await sc.get_rejections(pool, [K1, K2], client=client)
    assert got == {}
    assert pool.rows == {}                                   # a failure says nothing about the lane
    await sc.get_rejections(pool, [K1, K2], client=client)
    assert len(calls) == 1                                   # cooldown: SONAR not hammered


@pytest.mark.asyncio
async def test_timeout_gives_nulls():
    async def slow(*_a, **_k):
        await asyncio.sleep(5)

    pool = HubPool()
    orig = sc.fetch_from_sonar
    sc.fetch_from_sonar = slow
    try:
        got = await sc.get_rejections(pool, [K1], timeout_s=0.05)
    finally:
        sc.fetch_from_sonar = orig
    assert got == {}


@pytest.mark.asyncio
async def test_no_credentials_or_no_pool_never_calls_sonar(monkeypatch):
    client, calls = _sonar(_echo)
    assert await sc.get_rejections(None, [K1], client=client) == {}
    monkeypatch.delenv("SONAR_USERNAME")
    monkeypatch.delenv("SONAR_PASSWORD")
    assert await sc.get_rejections(HubPool(), [K1], client=client) == {}
    assert calls == []


@pytest.mark.asyncio
async def test_auth_rejection_gives_nulls(monkeypatch):
    client, calls = _sonar(lambda body: httpx.Response(401))
    got = await sc.get_rejections(HubPool(), [K1], client=client)
    assert got == {} and len(calls) == 1


# ---------------------------------------------------------------------------
# The endpoint
# ---------------------------------------------------------------------------


def _row(origin, dest, o_loc, d_loc, equip="Van", prof=100.0):
    return {
        "lane": f"{origin} - {dest}", "origin": origin, "dest": dest,
        "vol": 2, "n_carriers": 1, "n_carriers_total": 3, "rev": 1000.0, "prof": prof,
        "loss_loads": 0, "loss_profit": 0.0, "otp_late": 0, "otd_late": 0,
        "o_loc": o_loc, "d_loc": d_loc, "equip": equip,
    }


class GoldPool:
    def __init__(self, rows):
        self.rows = rows

    async def fetch(self, sql, *params):
        return self.rows


_FILTERS = dict(
    team=None, range="custom", start_date=date(2026, 10, 1), end_date=date(2026, 10, 12),
    customer=None, load_type=None, lanes=None, exclude_lanes=None,
    carriers=None, exclude_carriers=None, sort="profit_desc", limit=200,
    losses_only=False, unbilled_only=False,
)


def _request(hub):
    return SimpleNamespace(state=SimpleNamespace(), app=SimpleNamespace(state=SimpleNamespace(pool=hub)),
                           query_params={})


@pytest.mark.asyncio
async def test_endpoint_merges_values_by_lane(monkeypatch):
    rows = [
        _row("TEMPLE, TX", "WILMER, TX", "TX|76504", "TX|75172", prof=300),
        _row("JUAREZ, NX", "WILMER, TX", "NX|67250", "TX|75172", prof=200),   # MX → never sent
        _row("WACO, TX", "DONNA, TX", "TX|76712", "TX|", prof=100),            # no dest ZIP
    ]
    monkeypatch.setattr(actuals_mod, "get_datalake_gold_pool", lambda request: GoldPool(rows))
    sent: list[list] = []

    async def fake_get(pool, keys, **_kw):
        ks = [k for k in keys]
        sent.append(ks)
        return {K1: sc.Rejection(15.2, 4.0, datetime(2026, 10, 16, tzinfo=timezone.utc))}

    monkeypatch.setattr(sc, "get_rejections", fake_get)
    res = await actuals_mod.actuals_by_lane(request=_request(HubPool()), _user={}, **_FILTERS)

    assert [k for k in sent[0] if k is not None] == [K1]
    by_lane = {r["lane"]: r for r in res["data"]}
    assert by_lane["TEMPLE, TX - WILMER, TX"]["origin_rejection_pct"] == 15.2
    assert by_lane["TEMPLE, TX - WILMER, TX"]["dest_rejection_pct"] == 4.0
    for lane in ("JUAREZ, NX - WILMER, TX", "WACO, TX - DONNA, TX"):
        assert by_lane[lane]["origin_rejection_pct"] is None
        assert by_lane[lane]["dest_rejection_pct"] is None
    assert all("_sonar_key" not in r and "o_loc" not in r for r in res["data"])
    assert res["meta"]["rejection"]["as_of"].startswith("2026-10-16")


@pytest.mark.asyncio
async def test_endpoint_renders_when_sonar_fails(monkeypatch):
    rows = [_row("TEMPLE, TX", "WILMER, TX", "TX|76504", "TX|75172")]
    monkeypatch.setattr(actuals_mod, "get_datalake_gold_pool", lambda request: GoldPool(rows))
    client, _ = _sonar(lambda body: httpx.Response(503))
    real = sc.get_rejections

    async def via_failing_sonar(pool, keys, **_kw):
        return await real(pool, keys, client=client)

    monkeypatch.setattr(sc, "get_rejections", via_failing_sonar)
    res = await actuals_mod.actuals_by_lane(request=_request(HubPool()), _user={}, **_FILTERS)
    assert res["success"] is True
    assert res["data"][0]["origin_rejection_pct"] is None
    assert res["meta"]["rejection"]["as_of"] is None


@pytest.mark.asyncio
async def test_endpoint_only_looks_up_returned_lanes(monkeypatch):
    rows = [_row("A, TX", f"B{i}, TX", "TX|76504", f"TX|{75000 + i}", prof=i) for i in range(10)]
    monkeypatch.setattr(actuals_mod, "get_datalake_gold_pool", lambda request: GoldPool(rows))
    sent: list[list] = []

    async def fake_get(pool, keys, **_kw):
        sent.append([k for k in keys])
        return {}

    monkeypatch.setattr(sc, "get_rejections", fake_get)
    res = await actuals_mod.actuals_by_lane(request=_request(HubPool()), _user={}, **{**_FILTERS, "limit": 3})
    assert len(res["data"]) == 3 and len(sent[0]) == 3
    assert {k.dest_key for k in sent[0]} == {"75009", "75008", "75007"}   # top 3 by profit


def test_wrappers_need_no_new_param():
    """The rejection columns add NO query param, so the team/dfw/ceo wrappers
    (which forward every param explicitly, §40) need no change. If one is ever
    added, this signature check goes red until every wrapper forwards it."""
    import inspect
    from app.routers import ops_portal_overview_ceo as ceo
    from app.routers import ops_portal_overview_dfw as dfw

    base = set(inspect.signature(actuals_mod.actuals_by_lane).parameters)
    for wrapper in (dfw.actuals_by_lane, ceo.actuals_by_lane):
        assert base - {"_user", "request"} <= set(inspect.signature(wrapper).parameters)
