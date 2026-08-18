"""Guards for the chart's per-grain history window (Bruno PDF 2026-08-17 R2).

The chart shows a fixed number of periods per grain (52 days / 8 weeks /
8 months) but the user must be able to drag the brush back into older history.
That only works if the BACKEND keeps sending more buckets than the frontend
shows by default — the two numbers are a contract across the stack:

    backend window (here)   >=   frontend default window (PERIODS_BY_GRAIN)

The 2026-08-14 round broke exactly this by slicing the extra buckets away in
the client. Nothing tested the counts, so it shipped silently. These tests pin
the backend half and assert the inequality against the real frontend constant,
parsed out of Chart.tsx rather than duplicated here (a copy would drift).
"""

from __future__ import annotations

import json
import re
from datetime import date
from pathlib import Path

import pytest

from app.routers.ops_portal_overview._dates import _resolve_grain_window

CHART_TSX = (
    Path(__file__).resolve().parents[2]
    / "frontend"
    / "app"
    / "reports"
    / "ops-portal-overview"
    / "Chart.tsx"
)

# The maximum window the backend fetches per grain. Day was widened 120 -> 365
# so "scroll back to the previous year" is reachable at every grain.
EXPECTED_BUCKETS = {"day": 365, "week": 50, "month": 26}


@pytest.mark.parametrize("grain,count", sorted(EXPECTED_BUCKETS.items()))
def test_backend_window_bucket_count(grain: str, count: int) -> None:
    _start, _end, anchors = _resolve_grain_window(grain, date(2026, 8, 17))
    assert len(anchors) == count


@pytest.mark.parametrize("grain", sorted(EXPECTED_BUCKETS))
def test_window_ends_at_today_and_is_ordered(grain: str) -> None:
    today = date(2026, 8, 17)
    start, end, anchors = _resolve_grain_window(grain, today)
    assert anchors == sorted(anchors), "anchors must be oldest-first"
    assert start == anchors[0]
    assert end <= today, "window must never run past today"
    assert anchors[-1] <= today


def test_day_window_spans_a_full_year() -> None:
    """R2 asked specifically for previous-year history at Day grain."""
    start, end, _ = _resolve_grain_window("day", date(2026, 8, 17))
    assert (end - start).days >= 364


def _frontend_periods() -> dict[str, int]:
    """Parse PERIODS_BY_GRAIN out of Chart.tsx."""
    src = CHART_TSX.read_text(encoding="utf-8")
    m = re.search(
        r"const PERIODS_BY_GRAIN: Record<OppGrain, number> = \{(.*?)\}", src, re.S
    )
    assert m, "PERIODS_BY_GRAIN not found in Chart.tsx"
    body = re.sub(r"(\w+):", r'"\1":', m.group(1))
    body = re.sub(r",\s*$", "", body.strip())
    return json.loads("{" + body + "}")


@pytest.mark.parametrize("grain", sorted(EXPECTED_BUCKETS))
def test_backend_sends_more_than_the_frontend_shows(grain: str) -> None:
    """The scroll-back affordance IS this inequality.

    If the frontend default ever equals the backend window, the brush has
    nothing left to reveal and dragging it does nothing.
    """
    periods = _frontend_periods()
    assert periods[grain] < EXPECTED_BUCKETS[grain], (
        f"{grain}: frontend shows {periods[grain]} of {EXPECTED_BUCKETS[grain]} "
        "buckets — no history left to scroll back to"
    )


def test_frontend_does_not_slice_history_away() -> None:
    """The 2026-08-14 regression, pinned.

    `allBase.slice(-periods)` discarded the older buckets before Recharts ever
    saw them, so the extra backend window was unreachable. The default window is
    the brush's job; the dataset must stay whole.
    """
    src = CHART_TSX.read_text(encoding="utf-8")
    assert "allBase.slice(-periods)" not in src
    assert "all.slice(-periods)" not in src
