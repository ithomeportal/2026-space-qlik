"""Customer Concentration must move with the date filter.

Bruno PDF "BRUNO -- CEo Updates" (2026-08-27), Requests 1 & 2: both donuts on
the Customers tab were pinned to ``[YEAR_START, YEAR_END]`` and ignored the
filter, so full-year concentration sat next to date-scoped tables on the same
screen — two answers to "who are our top 5" (§69).

⚠ Assert on the BOUND PARAMETERS, not on the SQL text. The two Top-5 statements
never mention a date literal; the window arrives as ``$n``, so a text assertion
is satisfied by either binding and would have passed the whole time the bug was
live. The endpoint is driven for real and the params it hands the pool are read
back.

⚠ The panel subtitle is part of the fix. A donut that quietly changed meaning
while still captioned "full-year window" is worse than the original bug, so the
frontend string is pinned here rather than in a comment — the backend and the
label cannot drift apart without this going red.
"""

from __future__ import annotations

import asyncio
import inspect
import types
from datetime import date
from pathlib import Path

import pytest

from app.routers import ceo_executive as ceo

WINDOW = (date(2026, 3, 1), date(2026, 3, 31))
CUSTOMERS_TSX = (
    Path(__file__).resolve().parents[2]
    / "frontend" / "app" / "reports" / "ceo-executive" / "tabs" / "Customers.tsx"
)


class _StubPool:
    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple]] = []

    async def fetch(self, sql, *params):
        self.calls.append((sql, params))
        return []

    async def fetchrow(self, sql, *params):
        self.calls.append((sql, params))
        return None

    async def fetchval(self, sql, *params):
        self.calls.append((sql, params))
        return None


def _drive_customers(**kwargs):
    pool = _StubPool()
    orig = ceo.get_datalake_gold_pool
    ceo.get_datalake_gold_pool = lambda request: pool
    try:
        sig = inspect.signature(ceo.customers)
        call = {}
        for name, p in sig.parameters.items():
            if name in ("request", "_user"):
                continue
            d = p.default
            v = getattr(d, "default", d)
            call[name] = None if v is Ellipsis else v
        call.update(kwargs)
        call["request"] = types.SimpleNamespace(state=types.SimpleNamespace())
        call["_user"] = {}
        try:
            asyncio.run(ceo.customers(**call))
        except Exception:
            pass  # the stub returns []/None; the statements are what we came for
    finally:
        ceo.get_datalake_gold_pool = orig
    return pool.calls


def _top5_statements(calls):
    """The two concentration queries — the only ones ranking by a metric total."""
    return [(s, p) for s, p in calls if "SUM(revenue) OVER ()" in s or "SUM(profit) OVER ()" in s]


def test_both_donuts_bind_the_selected_window() -> None:
    calls = _drive_customers(range="custom", start_date=WINDOW[0], end_date=WINDOW[1])
    top5 = _top5_statements(calls)
    assert len(top5) == 2, f"expected the revenue and profit donuts, got {len(top5)}"
    for sql, params in top5:
        assert WINDOW[0] in params and WINDOW[1] in params, params
        assert date(2026, 1, 1) not in params, "still pinned to YEAR_START"
        assert date(2026, 12, 31) not in params, "still pinned to YEAR_END"


def test_the_donuts_use_the_same_window_as_the_tables_beside_them() -> None:
    """§69 — one screen, one definition of the window."""
    calls = _drive_customers(range="custom", start_date=WINDOW[0], end_date=WINDOW[1])
    windows = set()
    for _sql, params in calls:
        dates = tuple(p for p in params if isinstance(p, date))
        if len(dates) == 2:
            windows.add(dates)
    assert windows == {WINDOW}, f"panels disagree on the window: {windows}"


@pytest.mark.parametrize("rng,expected", [("mtd", True), ("full", True)])
def test_the_window_tracks_the_range_preset(rng: str, expected: bool) -> None:
    """Not just `custom` — every preset must reach the donuts too."""
    s, e = ceo._resolve_range(rng, None, None)
    top5 = _top5_statements(_drive_customers(range=rng))
    assert len(top5) == 2
    for _sql, params in top5:
        assert (s in params and e in params) is expected, (rng, params)


def test_the_panel_subtitle_no_longer_claims_a_full_year() -> None:
    src = CUSTOMERS_TSX.read_text()
    assert "full-year window" not in src, (
        "the donuts now honour the date filter — a stale 'full-year window' "
        "caption makes a correct number read as a wrong one"
    )
    assert "· honors Division · Team · Customer · date filter" in src
