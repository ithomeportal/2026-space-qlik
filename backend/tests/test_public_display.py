"""Public displays — floor-TV pages (request "space -- Public URL", 2026-11-02),
plus the CEO Executive customer-table guards (request "space -- Exec Portal").

⚠ `/api/public/*` is reachable without a user. These tests pin:
  * the proxy-secret gate is FAIL-CLOSED (unlike require_proxy / require_user);
  * the payload is an explicit ALLOWLIST — adding a key publishes it to the
    internet, so both key sets are pinned here and must change deliberately;
  * the endpoint declares NO query parameters (no URL can widen the window);
  * the frontend page 404s on a bad key, never imports the key module from a
    client file, and `/public/*` alone may be framed by other origins.
"""

from __future__ import annotations

import asyncio
import inspect
import pathlib
import re
import types

import pytest
from fastapi import HTTPException

from app.routers import public_display as pd

FRONTEND = pathlib.Path(__file__).resolve().parents[2] / "frontend"


def _run(coro):
    return asyncio.run(coro)


# ---------------------------------------------------------------- gate


def test_gate_fails_closed_when_secret_unset(monkeypatch):
    monkeypatch.setattr(pd.settings, "PROXY_SHARED_SECRET", "")
    with pytest.raises(HTTPException) as exc:
        _run(pd.require_proxy_strict(x_proxy_secret="anything"))
    assert exc.value.status_code == 503


@pytest.mark.parametrize("given", [None, "", "wrong-secret"])
def test_gate_rejects_missing_or_wrong_secret(monkeypatch, given):
    monkeypatch.setattr(pd.settings, "PROXY_SHARED_SECRET", "s3cret-value")
    with pytest.raises(HTTPException) as exc:
        _run(pd.require_proxy_strict(x_proxy_secret=given))
    assert exc.value.status_code == 401


def test_gate_accepts_the_proxy_secret(monkeypatch):
    monkeypatch.setattr(pd.settings, "PROXY_SHARED_SECRET", "s3cret-value")
    assert _run(pd.require_proxy_strict(x_proxy_secret="s3cret-value")) is None


def test_route_is_gated_and_declares_no_query_params():
    params = inspect.signature(pd.booker_rank).parameters
    assert set(params) == {"request", "_proxy"}
    assert params["_proxy"].default.dependency is pd.require_proxy_strict


# ---------------------------------------------------------------- allowlist


def test_field_allowlists_are_pinned():
    # ⚠ Changing either set publishes (or withdraws) data on the open internet.
    assert pd.RANK_ROW_FIELDS == (
        "booker", "rank", "prev_rank", "rank_delta", "bookings", "prev_bookings",
        "compliance_threshold_pct", "compliant_threshold", "threshold_orders",
        "cost_saving",
    )
    assert pd.RANK_TOP_FIELDS == (
        "total_bookers", "min_bookings", "week", "prev_week", "like_for_like",
    )


def _fake_rank(**extra_row):
    row = {f: 1 for f in pd.RANK_ROW_FIELDS}
    row.update(booker="Jane Doe", broken_threshold=3, under_threshold=2, **extra_row)
    return {
        "success": True,
        "data": {
            "rows": [row],
            "bookers": ["Jane Doe", "John Roe"],
            "roster": ["Jane Doe", "John Roe"],
            "total_bookers": 2,
            "min_bookings": 0,
            "week": {"start": "a", "end": "b", "label": "L"},
            "prev_week": {"start": "c", "end": "d", "label": "P"},
            "like_for_like": True,
        },
    }


def _drive(monkeypatch, calls):
    async def fake_rank(request, **kw):
        calls.append(("rank", kw))
        return _fake_rank(secret_margin=999)

    async def fake_last(request, **kw):
        calls.append(("last", kw))
        return _fake_rank()

    monkeypatch.setattr(pd.bs, "rank", fake_rank)
    monkeypatch.setattr(pd.bs, "rank_last_week", fake_last)
    pd._cache.clear()
    request = types.SimpleNamespace(app=types.SimpleNamespace(state=types.SimpleNamespace()))
    return _run(pd.booker_rank(request=request, _proxy=None))


def test_payload_is_projected_to_the_allowlist(monkeypatch):
    calls: list = []
    body = _drive(monkeypatch, calls)
    for table in (body["data"]["current"], body["data"]["last_week"]):
        assert set(table) == set(pd.RANK_TOP_FIELDS) | {"rows"}
        assert "bookers" not in table and "roster" not in table
        for row in table["rows"]:
            assert set(row) == set(pd.RANK_ROW_FIELDS)


def test_both_tables_use_report_defaults(monkeypatch):
    calls: list = []
    _drive(monkeypatch, calls)
    rank_kw = dict(calls[0][1])
    assert calls[0][0] == "rank" and calls[1][0] == "last"
    assert rank_kw["period"] is None and rank_kw["start"] is None and rank_kw["end"] is None
    for _, kw in calls:
        assert kw["contract_type"] is None
        assert kw["customer_name"] is None
        assert kw["posted_by"] is None


def test_payload_is_cached_across_screens(monkeypatch):
    calls: list = []
    _drive(monkeypatch, calls)
    request = types.SimpleNamespace(app=types.SimpleNamespace(state=types.SimpleNamespace()))
    _run(pd.booker_rank(request=request, _proxy=None))
    assert len(calls) == 2  # second screen served from cache: no new scans
    pd._cache.clear()


def test_router_is_registered():
    main_src = (pathlib.Path(pd.__file__).parents[1] / "main.py").read_text()
    assert "app.include_router(public_display.router" in main_src


# ---------------------------------------------------------------- frontend guards


def _read(rel: str) -> str:
    return (FRONTEND / rel).read_text()


def test_page_404s_on_a_bad_key_before_fetching():
    src = _read("app/public/booker-rank/page.tsx")
    gate = src.index("if (!isValidDisplayKey(searchParams.key)) notFound()")
    assert gate < src.index("await fetchPublicDisplay")
    assert 'dynamic = "force-dynamic"' in src
    assert "@/components/ReportGuard" not in src


def test_key_check_is_constant_time_and_fail_closed():
    src = _read("lib/public-display.ts")
    assert "timingSafeEqual" in src
    assert "PUBLIC_DISPLAY_KEYS" in src
    assert "if (keys.length === 0) return false" in src
    assert "TV_SECRET" not in src  # the retired Qlik mechanism stays retired
    assert not src.lstrip().startswith('"use client"')


def test_key_module_never_imported_from_a_client_file():
    offenders = []
    for path in list(FRONTEND.rglob("*.ts")) + list(FRONTEND.rglob("*.tsx")):
        if "node_modules" in path.parts or ".next" in path.parts:
            continue
        text = path.read_text(errors="ignore")
        if text.lstrip().startswith(('"use client"', "'use client'")) and re.search(
            r"""from\s+["']@/lib/public-display["']""", text
        ):
            offenders.append(str(path))
    assert offenders == []


def test_only_public_routes_may_be_framed():
    cfg = _read("next.config.mjs")
    assert 'source: "/((?!public/).*)"' in cfg
    assert "frame-ancestors 'self'" in cfg
    public_block = cfg[cfg.index('source: "/public/:path*"'):]
    assert "frame-ancestors *" in public_block
    assert "X-Frame-Options" not in public_block
    assert '"Referrer-Policy", value: "no-referrer"' in public_block
    assert "noindex" in public_block


def test_header_hidden_on_public_routes():
    assert 'pathname?.startsWith("/public/")) return null' in _read("components/Header.tsx")


def test_ceo_customer_tables_sort_and_expand():
    table = _read("app/reports/ceo-executive/CustomerTable.tsx")
    sort = _read("app/reports/ceo-executive/customer-table-sort.ts")
    customers = _read("app/reports/ceo-executive/tabs/Customers.tsx")
    assert "aria-sort" in table
    assert "ExpandButton" in table and "ExpandModal" in table
    # Sorting a COPY — never the server's array in place.
    assert "[...rows].sort(" in sort
    for label in ("Customer", "Loads", "Revenue", "Profit", "Margin %", "Conc %", "AVG P / L"):
        assert f'label: "{label}"' in sort
    assert customers.count("<CustomerTable") == 2
