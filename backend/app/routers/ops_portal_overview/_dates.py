"""Date-window resolution: report ranges, workday counts, chart grains.

Part of the ``ops_portal_overview`` package (split 2026-08-14 — see SPEC-CUSTOM-REPORTS §28).
"""

from __future__ import annotations

from calendar import monthrange
from datetime import date, timedelta
from typing import Optional


from app.clock import cst_today

from ._constants import YEAR_END, YEAR_START


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _clamp(d: Optional[date], default: date) -> date:
    if d is None:
        return default
    if d < YEAR_START:
        return YEAR_START
    if d > YEAR_END:
        return YEAR_END
    return d


def _resolve_range(
    rng: Optional[str],
    start_date: Optional[date],
    end_date: Optional[date],
) -> tuple[date, date]:
    """Date-filter range model.

    Bruno R5 (2026-06-01) reworked the filter options. ``full`` is dropped from
    the UI but kept here as the silent default/fallback (the rolling endpoints —
    /combo, /workdays, /team-projection, /profit-tm-gauge — still pass it):
      - yesterday   → the single prior day (Bruno PDF 2026-07-20 R2)
      - mtd         → 1st of current month → today (Month-to-Date)
      - this_month  → full current month (1st → last day)
      - last_month  → full previous month
      - custom      → user start/end
      - ytd         → Jan 1 → today (button removed by Bruno PDF 2026-07-20 R2;
                      the branch is kept so a stale client that still sends
                      ``range=ytd`` gets YTD rather than silently falling
                      through to the whole-year default)
      - full (fallback) → whole year
    """
    today = cst_today()
    today_clamped = max(YEAR_START, min(YEAR_END, today))
    if rng == "mtd":
        return today_clamped.replace(day=1), today_clamped
    # Bruno (PDF 2026-07-20) R2: "Yesterday" replaces the YTD button. Clamped
    # into the 2026 window, so on Jan 1 it collapses to Jan 1 itself.
    if rng == "yesterday":
        y = _clamp(today_clamped - timedelta(days=1), YEAR_START)
        return y, y
    if rng == "ytd":
        return YEAR_START, today_clamped
    if rng == "this_month":
        m_start, m_end = _month_bounds(today_clamped)
        return _clamp(m_start, YEAR_START), _clamp(m_end, YEAR_END)
    if rng == "last_month":
        first_this = today_clamped.replace(day=1)
        last_prev = first_this - timedelta(days=1)
        prev_start, prev_end = _month_bounds(last_prev)
        return _clamp(prev_start, YEAR_START), _clamp(prev_end, YEAR_END)
    if rng == "custom":
        s = _clamp(start_date, YEAR_START)
        e = _clamp(end_date, YEAR_END)
        if e < s:
            s, e = e, s
        return s, e
    # default = full year
    return YEAR_START, YEAR_END


def _count_workdays(start: date, end: date) -> int:
    """Mon-Sat days in [start, end].

    Bruno round-2 (2026-05-13) — Total/Past/Pending working days are
    Monday-Saturday (Sundays only). Holidays are NOT excluded per his
    literal spec on the round-2 PDF; he didn't repeat the holiday clause
    from Budget Follow Up here.
    """
    if start > end:
        return 0
    n, d = 0, start
    while d <= end:
        if d.weekday() < 6:  # Mon=0..Sat=5
            n += 1
        d += timedelta(days=1)
    return n


def _last_n_business_days_start(today: date, n: int) -> date:
    """Earliest Mon-Sat date such that ``[start, today-1]`` has exactly n Mon-Sat days.

    Used by /team-projection and /actuals to anchor the "last 12 business
    days" averages Bruno specified in round 2.
    """
    end = today - timedelta(days=1)
    count = 0
    d = end
    while True:
        if d.weekday() < 6:
            count += 1
            if count == n:
                return d
        d -= timedelta(days=1)
        if (end - d).days > n * 3:
            # Safety bail — shouldn't ever trip, but never spin forever.
            return d


def _month_bounds(today: date) -> tuple[date, date]:
    m_start = today.replace(day=1)
    m_end = today.replace(day=monthrange(today.year, today.month)[1])
    return m_start, m_end


# ---------------------------------------------------------------------------
# /combo — Day / Week / Month bars + lines (Bruno round 3, 2026-05-19)
# ---------------------------------------------------------------------------


def _resolve_grain_window(grain: str, today: date) -> tuple[date, date, list[date]]:
    """Build the bucket window and per-bucket anchor dates for a grain.

    Bruno round 3 (2026-05-19): chart adds Day / Week / Month grain pickers
    with scroll-bar zoom. Backend fetches the maximum window per grain (365 d
    / 50 w / 26 m); frontend Brush positions the visible window.

    Bruno (PDF 2026-08-17) R2: the brush must reach "the previous year" at every
    grain, so Day went 120 -> 365. Week (50) and Month (26) already spanned a
    year or more. The widening is cheap and was measured before shipping: 365
    days scans ~35.5k rows of budget_report_v4 against the ~84.7k the Month
    grain already scans on every default page load.
    """
    if grain == "day":
        n = 365
        end = today
        start = end - timedelta(days=n - 1)
        anchors = [start + timedelta(days=i) for i in range(n)]
        return start, end, anchors
    if grain == "week":
        n = 50
        # Anchor on Monday of the current ISO week.
        this_mon = today - timedelta(days=today.weekday())
        start = this_mon - timedelta(weeks=n - 1)
        anchors = [start + timedelta(weeks=i) for i in range(n)]
        end = anchors[-1] + timedelta(days=6)
        if end > today:
            end = today
        return start, end, anchors
    # month
    n = 26
    cursor = today.replace(day=1)
    anchors_desc: list[date] = [cursor]
    for _ in range(n - 1):
        prev_last = anchors_desc[-1] - timedelta(days=1)
        anchors_desc.append(prev_last.replace(day=1))
    anchors = list(reversed(anchors_desc))
    last = anchors[-1]
    end = last.replace(day=monthrange(last.year, last.month)[1])
    if end > today:
        # Cap window at today so we don't double-count partials.
        end = today
    return anchors[0], end, anchors


def _last_5_weeks(today: date) -> tuple[list[date], date, date]:
    """The 5 most recent Mon-Sun week-starts (current week included), plus the
    span bounds. Mirrors /team-weekly-performance so the two Week views align."""
    this_mon = today - timedelta(days=today.weekday())
    week_starts = [this_mon - timedelta(weeks=k) for k in range(4, -1, -1)]
    return week_starts, week_starts[0], week_starts[-1] + timedelta(days=6)


def _week_label(ws: date) -> str:
    we = ws + timedelta(days=6)
    return f"{ws.day:02d}/{ws.month:02d} - {we.day:02d}/{we.month:02d}"
