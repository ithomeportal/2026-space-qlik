"""Booker Performance Scorecard — Bruno PDF 2026-10-06 (Rank tab).

R1  The Rank tab FOLLOWS a date filter. Default: the booking week containing
    now — previous Friday 5:01 PM through the coming Friday 5:00 PM (CST). On
    Tue 2026-10-06 that is Oct 2 17:01 → Oct 9 17:00.
R2  A second table, "Rank Last Week": not affected by the date filter, always
    the previous booking week (Sep 25 17:01 → Oct 2 17:00 on that Tuesday),
    only bookers with # of Bookings >= 35, sorted by Cost Saving high → low.

Decision (Diego, 2026-10-06): while the selected window is still open, the
movement arrows compare LIKE-FOR-LIKE — the previous window clipped to the same
elapsed time. That replaces the 2026-08-31 rule "never rank the in-progress
week", whose defect (+13-position swings from ranking 1 day against 7) it
still prevents.

Measured on live gold before shipping: `posted_date` is naive CST at minute
precision (the first posting after the 25 Sep boundary is exactly 17:01), so
the half-open [Fri 17:01, Fri 17:01) loses and double-counts nothing. A rough
roster count for 25 Sep - 2 Oct put ~3 bookers at >= 35 (Daniel Salazar 39,
Juan Reyna 36, Eugenio Miranda exactly 35) — the cut is INCLUSIVE.

⚠ Every clock is pinned: these tests bucket by week, and an unpinned one is
green today and red next Friday for no code change (§104).
"""

from __future__ import annotations

import inspect
import pathlib
import re
from datetime import date, datetime, time, timedelta, timezone

import pytest
from fastapi import HTTPException

from app.clock import CST
from app.routers import booker_scorecard as bs

from test_booker_scorecard_bruno_2026_08_31 import _SCOPE, _drive


# Tuesday 2026-10-06 09:00 CST — the morning the PDF was dropped.
NOW = datetime(2026, 10, 6, 9, 0)
NOW_AWARE = NOW.replace(tzinfo=CST)

CUR_START = datetime(2026, 10, 2, 17, 1)
CUR_END = datetime(2026, 10, 9, 17, 1)       # exclusive
LAST_START = datetime(2026, 9, 25, 17, 1)
LAST_END = CUR_START                          # exclusive

_DEFAULT = dict(_SCOPE, period=None, start=None, end=None)


def _row(order_id, name, when, carrier_cost=500.0):
    return {"order_id": order_id, "carrier_cost": carrier_cost,
            "posted_by": name, "posted_date": when}


# ==========================================================================
# R1 — the booking week
# ==========================================================================


def test_the_default_window_is_the_one_in_the_pdf():
    assert bs._booking_week(NOW) == (CUR_START, CUR_END)
    assert bs._resolve_rank_window(None, None, None, NOW) == (CUR_START, CUR_END)
    assert bs._resolve_rank_window("week", None, None, NOW) == (CUR_START, CUR_END)


def test_the_week_turns_over_at_friday_1701_not_1700():
    """Bruno: "5:01 PM through 5:00 PM". 17:00 still belongs to the closing
    week; 17:01 opens the next one. An off-by-one minute here moves every
    booking posted at 17:00 into the wrong week."""
    fri = date(2026, 10, 9)
    assert bs._booking_week(datetime.combine(fri, time(17, 0)))[0] == CUR_START
    assert bs._booking_week(datetime.combine(fri, time(17, 1)))[0] == CUR_END
    # Friday morning is still the old week; Friday 23:59 the new one.
    assert bs._booking_week(datetime.combine(fri, time(9, 0)))[0] == CUR_START
    assert bs._booking_week(datetime.combine(fri, time(23, 59)))[0] == CUR_END


def test_every_hour_of_two_weeks_lands_in_a_friday_1701_week_that_contains_it():
    """Every weekday, not one sample: the modulo that finds "the most recent
    Friday" is the identity on a Friday, and an off-by-one there is invisible
    on any single other day."""
    t = datetime(2026, 9, 26, 0, 0)
    while t < datetime(2026, 10, 10, 0, 0):
        s, e = bs._booking_week(t)
        assert s.weekday() == 4 and s.time() == time(17, 1), (t, s)
        assert e - s == timedelta(days=7)
        assert s <= t < e, f"{t} is outside its own week {s} → {e}"
        t += timedelta(hours=1)


def test_last_is_the_week_before_the_current_one():
    assert bs._resolve_rank_window("last", None, None, NOW) == (LAST_START, LAST_END)


def test_mtd_runs_from_the_first_to_the_end_of_today():
    s, e = bs._resolve_rank_window("mtd", None, None, NOW)
    assert s == datetime(2026, 10, 1, 0, 0)
    assert e == datetime(2026, 10, 7, 0, 0)


def test_custom_end_is_inclusive_to_the_minute():
    """The person types "…5:00 PM" and means that minute included."""
    s, e = bs._resolve_rank_window(
        "custom", datetime(2026, 10, 2, 17, 1), datetime(2026, 10, 9, 17, 0), NOW
    )
    assert (s, e) == (CUR_START, CUR_END)


def test_custom_converts_an_aware_timestamp_to_chicago():
    """A browser that sends an offset must not shift Friday by its timezone."""
    utc = datetime(2026, 10, 2, 22, 1, tzinfo=timezone.utc)  # 17:01 CDT
    s, _ = bs._resolve_rank_window("custom", utc, datetime(2026, 10, 9, 17, 0), NOW)
    assert s == CUR_START


def test_custom_is_clamped_to_the_report_year():
    s, e = bs._resolve_rank_window(
        "custom", datetime(2025, 6, 1), datetime(2027, 3, 1), NOW
    )
    assert s == datetime(2026, 1, 1, 0, 0)
    assert e == datetime(2027, 1, 1, 0, 0)


@pytest.mark.parametrize("period,start,end", [
    ("fortnight", None, None),                     # not a preset
    ("custom", None, datetime(2026, 10, 9)),       # half a range
    ("custom", datetime(2026, 10, 9), None),
    ("custom", datetime(2026, 10, 9, 12), datetime(2026, 10, 9, 11)),  # inverted
])
def test_a_bad_window_is_a_400_not_a_silent_default(period, start, end):
    with pytest.raises(HTTPException) as ei:
        bs._resolve_rank_window(period, start, end, NOW)
    assert ei.value.status_code == 400


def test_the_presets_ignore_start_and_end():
    """`start`/`end` are read for `custom` only — otherwise a stale pair left in
    a URL would silently override the preset the button shows as selected."""
    assert bs._resolve_rank_window(
        "week", datetime(2026, 3, 1), datetime(2026, 3, 2), NOW
    ) == (CUR_START, CUR_END)


# ==========================================================================
# R1 — like-for-like movement
# ==========================================================================


def test_an_open_window_compares_against_the_same_elapsed_time():
    """Tue 09:00 is 3 days 15h59m into the week; the comparison window is the
    previous Friday 17:01 plus exactly that, never the whole previous week."""
    ps, pe = bs._comparison_window(CUR_START, CUR_END, NOW)
    assert ps == LAST_START
    assert pe == NOW - timedelta(days=7)
    assert pe - ps == NOW - CUR_START


def test_a_closed_window_compares_against_the_whole_previous_one():
    ps, pe = bs._comparison_window(LAST_START, LAST_END, NOW)
    assert (ps, pe) == (LAST_START - timedelta(days=7), LAST_START)


def test_the_endpoint_buckets_both_windows_like_for_like():
    rows = [
        # this week
        _row("C1", "EUGENIO MIRANDA", datetime(2026, 10, 3, 10, 0)),
        _row("C2", "EUGENIO MIRANDA", datetime(2026, 10, 5, 10, 0)),
        _row("C3", "JUAN REYNA", datetime(2026, 10, 5, 11, 0)),
        # last week, BEFORE the same point (Tue 29 Sep 09:00) — compared
        _row("P1", "JUAN REYNA", datetime(2026, 9, 26, 10, 0)),
        _row("P2", "JUAN REYNA", datetime(2026, 9, 28, 10, 0)),
        _row("P3", "EUGENIO MIRANDA", datetime(2026, 9, 28, 11, 0)),
        # last week, AFTER that point — outside a like-for-like comparison
        _row("X1", "EUGENIO MIRANDA", datetime(2026, 10, 1, 10, 0)),
        _row("X2", "EUGENIO MIRANDA", datetime(2026, 10, 1, 11, 0)),
    ]
    _, resp = _drive(bs.rank, rows=rows, now=NOW_AWARE, **_DEFAULT)
    d = resp["data"]
    by = {r["booker"]: r for r in d["rows"]}
    assert by["EUGENIO MIRANDA"]["bookings"] == 2
    assert by["EUGENIO MIRANDA"]["prev_bookings"] == 1, (
        "the rest of last week leaked into a like-for-like comparison"
    )
    assert by["JUAN REYNA"]["prev_bookings"] == 2
    # Eugenio was 2nd at this point last week and is 1st now: up one.
    assert by["EUGENIO MIRANDA"]["rank"] == 1
    assert by["EUGENIO MIRANDA"]["rank_delta"] == 1
    assert d["like_for_like"] is True
    assert d["week"]["start"] == "2026-10-02T17:01"
    assert d["week"]["end"] == "2026-10-09T17:00", "the END printed is inclusive"
    assert d["week"]["label"] == "Fri Oct 02, 5:01 PM → Fri Oct 09, 5:00 PM"
    assert d["prev_week"]["end"] == "2026-09-29T08:59"


def test_a_booking_at_1700_and_one_at_1701_land_in_different_weeks():
    rows = [
        _row("A", "EUGENIO MIRANDA", datetime(2026, 10, 2, 17, 0)),
        _row("B", "EUGENIO MIRANDA", datetime(2026, 10, 2, 17, 1)),
    ]
    _, resp = _drive(bs.rank, rows=rows, now=NOW_AWARE,
                     **dict(_DEFAULT, period="custom",
                            start=CUR_START, end=datetime(2026, 10, 3, 0, 0)))
    row = resp["data"]["rows"][0]
    assert row["bookings"] == 1 and row["prev_bookings"] == 1


def test_the_sql_bound_keeps_the_1701_time():
    """⚠ `datetime` is a `date` subclass. A bound helper that tests `date`
    first truncates Friday 17:01 to midnight — every booking of Friday
    morning would join the week, and nothing in the rows would say so."""
    params: list = []
    bs._base_sql(params, start=CUR_START, end=CUR_END - timedelta(microseconds=1),
                 contract_types=[], customers=[], posted_by=[])
    assert params[1] == CUR_START
    assert params[2] == CUR_END - timedelta(microseconds=1)

    # …and every date-based caller is byte-identical to before.
    params2: list = []
    bs._base_sql(params2, start=date(2026, 10, 1), end=date(2026, 10, 6),
                 contract_types=[], customers=[], posted_by=[])
    assert params2[1] == datetime(2026, 10, 1, 0, 0)
    assert params2[2] == datetime.combine(date(2026, 10, 6), time.max)


def test_rank_still_scans_once_for_both_windows():
    pool, _ = _drive(bs.rank, now=NOW_AWARE, **_DEFAULT)
    assert len(pool.sqls) == 1


# ==========================================================================
# R2 — Rank Last Week
# ==========================================================================


def _last_week_rows():
    """Bookings in the previous booking week. JUAN REYNA books the most but
    saves the least; DANIEL SALAZAR sits at 34, one under the cut."""
    rows = []
    n = 0
    for name, count, cost in (
        ("JUAN REYNA", 40, 900.0),        # 40 × 100 saved
        ("EUGENIO MIRANDA", 35, 500.0),   # 35 × 500 saved — exactly on the cut
        ("DANIEL SALAZAR", 34, 100.0),    # most saved, but under the cut
    ):
        for _ in range(count):
            n += 1
            rows.append(_row(f"L{n}", name, datetime(2026, 9, 28, 10, 0), cost))
    # One booking in the CURRENT week: the table must not see it.
    rows.append(_row("NOW1", "EUGENIO MIRANDA", datetime(2026, 10, 5, 10, 0), 500.0))
    return rows


def _thresholds_for(rows):
    return {r["order_id"]: 1000.0 for r in rows}


def test_rank_last_week_keeps_35_and_drops_34():
    rows = _last_week_rows()
    _, resp = _drive(bs.rank_last_week, rows=rows, now=NOW_AWARE,
                     thresholds=_thresholds_for(rows), **_SCOPE)
    names = [r["booker"] for r in resp["data"]["rows"]]
    assert "EUGENIO MIRANDA" in names, ">= 35 is inclusive"
    assert "DANIEL SALAZAR" not in names
    assert resp["data"]["min_bookings"] == 35


def test_rank_last_week_sorts_by_cost_saving_high_to_low():
    rows = _last_week_rows()
    _, resp = _drive(bs.rank_last_week, rows=rows, now=NOW_AWARE,
                     thresholds=_thresholds_for(rows), **_SCOPE)
    out = resp["data"]["rows"]
    assert [r["booker"] for r in out] == ["EUGENIO MIRANDA", "JUAN REYNA"]
    savings = [r["cost_saving"] for r in out]
    assert savings == sorted(savings, reverse=True)


def test_the_cut_does_not_renumber_the_league():
    """§75 — the >= 35 cut is a DISPLAY filter. Rank stays the position by
    # of Bookings among every roster booker that week, and "of N" counts the
    booker the cut hid."""
    rows = _last_week_rows()
    _, resp = _drive(bs.rank_last_week, rows=rows, now=NOW_AWARE,
                     thresholds=_thresholds_for(rows), **_SCOPE)
    by = {r["booker"]: r for r in resp["data"]["rows"]}
    assert by["JUAN REYNA"]["rank"] == 1
    assert by["EUGENIO MIRANDA"]["rank"] == 2
    assert resp["data"]["total_bookers"] == 3


def test_rank_last_week_is_the_previous_booking_week_whatever_the_day():
    rows = _last_week_rows()
    _, resp = _drive(bs.rank_last_week, rows=rows, now=NOW_AWARE,
                     thresholds=_thresholds_for(rows), **_SCOPE)
    w = resp["data"]["week"]
    assert (w["start"], w["end"]) == ("2026-09-25T17:01", "2026-10-02T17:00")
    # Two complete weeks: never clipped.
    assert resp["data"]["like_for_like"] is False
    # Eugenio's current-week booking is not counted: he stays at exactly 35.
    by = {r["booker"]: r for r in resp["data"]["rows"]}
    assert by["EUGENIO MIRANDA"]["bookings"] == 35


def test_a_null_cost_saving_sorts_last_not_first():
    """No threshold coverage is not a saving — and with a descending sort a
    negated-sentinel key would put it at the TOP (the 2026-09-03 inversion,
    §104). Asserted on the key: live, `cost_saving` is None only when AP is
    down, and then it is None for everyone."""
    rows = [
        {"booker": "A", "rank": 1, "cost_saving": None},
        {"booker": "B", "rank": 2, "cost_saving": 50.0},
        {"booker": "C", "rank": 3, "cost_saving": 900.0},
        {"booker": "D", "rank": 4, "cost_saving": 0.0},
    ]
    assert [r["booker"] for r in sorted(rows, key=bs._cost_saving_desc_key)] == [
        "C", "B", "D", "A",
    ]


def test_rank_last_week_survives_an_ap_outage_in_rank_order():
    rows = _last_week_rows()
    _, resp = _drive(bs.rank_last_week, rows=rows, now=NOW_AWARE,
                     thresholds=None, **_SCOPE)
    out = resp["data"]["rows"]
    assert [r["booker"] for r in out] == ["JUAN REYNA", "EUGENIO MIRANDA"]
    assert all(r["cost_saving"] is None for r in out)


# ==========================================================================
# Scope of the change
# ==========================================================================


def test_only_the_rank_tab_uses_the_booking_week():
    """⚠ §95 — `wtd` on the Scorecard tab and the 10-week /weekly trend are
    read beside other portal reports on the ISO week. They stay Mon-Sun."""
    for fn in (bs._resolve_range, bs.weekly):
        src = inspect.getsource(fn)
        assert "_booking_week" not in src and "_BOOKING_WEEK" not in src, fn.__name__
    # …and the helper IS reachable from the rank endpoints (§91).
    assert "_booking_week" in inspect.getsource(bs.rank_last_week)
    assert "_resolve_rank_window" in inspect.getsource(bs.rank)

    orig = bs.cst_today
    bs.cst_today = lambda: NOW.date()
    try:
        assert bs._resolve_range("wtd", None, None) == (date(2026, 10, 5), NOW.date())
    finally:
        bs.cst_today = orig


def test_the_ui_never_sends_a_date_to_rank_last_week():
    """The backend refuses date params by signature; this proves the UI does
    not try (it would be a dead control rather than an error)."""
    root = pathlib.Path(bs.__file__).resolve().parents[3]
    src = (root / "frontend" / "lib" / "booker-scorecard-api.ts").read_text()
    body = src.split("export function useBookerRankLastWeek", 1)[1]
    body = body.split("\nexport ", 1)[0]
    assert "rank/last-week" in body
    for forbidden in ("period", "start", "end", "rankWindowParams", "RankWindow"):
        assert not re.search(rf"\b{forbidden}\b", body), forbidden
    # Known positive (§91): the main hook DOES send the window.
    main = src.split("export function useBookerRank(", 1)[1].split("\nexport ", 1)[0]
    assert "rankWindowParams" in main
