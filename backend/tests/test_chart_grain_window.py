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

from app.routers.ops_portal_overview._dates import _bucket_end, _resolve_grain_window

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


# ---------------------------------------------------------------------------
# _bucket_end — the whole-period end, the counterpart to the capped window
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "grain,anchor,expected",
    [
        # 2026-08-27 is a Thursday: mid-week and mid-month, so every grain's
        # last bucket extends PAST today and the two windows must differ.
        ("day", date(2026, 8, 27), date(2026, 8, 27)),
        ("week", date(2026, 8, 24), date(2026, 8, 30)),
        ("month", date(2026, 8, 1), date(2026, 8, 31)),
        # month-length edge cases the `+30 days` shortcut would get wrong
        ("month", date(2026, 2, 1), date(2026, 2, 28)),
        ("month", date(2028, 2, 1), date(2028, 2, 29)),
        # a week that straddles a month AND a year boundary
        ("week", date(2026, 12, 28), date(2027, 1, 3)),
    ],
)
def test_bucket_end_returns_the_whole_period(grain, anchor, expected) -> None:
    assert _bucket_end(grain, anchor) == expected


@pytest.mark.parametrize("grain", sorted(EXPECTED_BUCKETS))
def test_bucket_end_never_precedes_the_capped_window(grain: str) -> None:
    """The budget leg widens the window, it never narrows it.

    Together with `test_window_ends_at_today_and_is_ordered` this pins the pair:
    the measured leg stops at today, the planned leg reaches the period's end,
    and neither can silently become the other.
    """
    today = date(2026, 8, 27)
    _start, end, anchors = _resolve_grain_window(grain, today)
    assert _bucket_end(grain, anchors[-1]) >= end


# ---------------------------------------------------------------------------
# The window must SURVIVE a filter click — Bruno's Observation, PDF 2026-08-31
# ---------------------------------------------------------------------------
# Reported as "clicking on any other filter … is affecting the chart's default
# time range". Root cause was NOT this component's logic: Recharts 3 keeps the
# visible window in an internal Redux store, and swapping the `data` array runs
# ChartDataContextProvider's cleanup — `setChartData(undefined)` zeroes both
# indices, and the follow-up call restores only `dataEndIndex`, leaving the
# start at 0. <Brush> re-syncs its props into that store only when their VALUES
# change, and they don't: the backend emits a DENSE fixed-length series per
# grain, so a filter change leaves every index identical. `keepPreviousData`
# keeps the chart mounted across the refetch, so nothing else resets it either.
#
# Measured on the real page with the network stubbed (2026-08-31): at the Day
# grain one filter click took the window from 52 buckets to all 365, and it
# stayed there for the rest of the session. Week and Month share the mechanism.
#
# The browser repro cannot run in this suite (it needs a built Next server), so
# these pin the three code elements the fix consists of. Each one alone is
# insufficient — remove any and the window stops re-anchoring.


def _chart_src() -> str:
    return CHART_TSX.read_text(encoding="utf-8")


def test_filter_change_clears_the_user_scrolled_flag() -> None:
    """A filter click must re-arm the default window, exactly like a grain switch.

    Without `filterKey` in these deps, a user who had ever dragged the brush
    kept their stale window on every later filter click — pointing at entirely
    different dates than the labels beside it.
    """
    src = _chart_src()
    assert "const filterKey = [" in src, "the filter identity is gone"
    assert re.search(
        r"userScrolledRef\.current\s*=\s*false\s*\n\s*\}\s*,\s*\[grain,\s*filterKey\]", src
    ), "the reset effect no longer fires on a filter change"


def test_window_reanchors_on_data_IDENTITY_not_length() -> None:
    """⚠ `chartData.length` is filter-INVARIANT — the backend series is dense.

    Keying the re-anchor effect on `.length` is why it silently stopped firing.
    """
    src = _chart_src()
    m = re.search(r"\}, \[grain, ([^\]]*?), defaultVisible\]", src)
    assert m, "the brush-positioning effect's dependency list changed shape"
    deps = m.group(1)
    assert "chartData" in deps and "chartData.length" not in deps, (
        f"re-anchor deps are {deps!r} — must watch chartData identity, not its length"
    )


def test_both_brushes_remount_when_the_data_changes() -> None:
    """Recharts ignores startIndex/endIndex whose VALUES did not change.

    Remounting is the only way to push our indices back into its store. There
    are two <Brush> elements (Service and combo) and both need it — the Service
    chart shares one `brush` state with the combo chart.
    """
    src = _chart_src()
    keys = re.findall(r"<Brush\b[\s\S]{0,400}?key=\{`\$\{grain\}-\$\{dataEpoch\}`\}", src)
    assert len(keys) == 2, f"expected both Brushes to carry a remount key, found {len(keys)}"
    # The epoch must be bumped in an EFFECT, so the remount lands in the commit
    # AFTER Recharts zeroes its store. Reading it straight off `chartData`
    # makes the ordering a coin flip.
    assert re.search(
        r"useEffect\(\(\) => \{\s*setDataEpoch\(\(e\) => e \+ 1\)\s*\}, \[chartData, serviceData\]\)",
        src,
    ), "dataEpoch is no longer bumped in an effect over both datasets"
