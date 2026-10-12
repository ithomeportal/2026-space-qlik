"""Previous-month comparison leg for the Actuals table.

Bruno PDF "space -- Ops Portal DFW" (2026-10-12), Request 1: the DFW Actuals
table gets All / Actuals / Variances, where the comparison is "the previous
month's calculated value" over the SAME days — a 10-01 → 10-12 filter compares
against 09-01 → 09-12. Variance = current − previous; % = current ÷ previous.

DFW has no budget (``DFW_SCOPE.has_budget`` is False), so this leg replaces the
budget leg there. It is a separate, explicitly named set of wire fields
(``*_prev`` / ``*_vs_prev``), never the ``*_budget`` fields re-used under a
different meaning (§69).

⚠ The previous window is NOT clamped to ``YEAR_START``. The page window is
clamped into 2026, but its comparison is a different window: Jan 1-12 compares
against Dec 1-12 2025, which v4 holds (1,509 DFW loads, measured 2026-10-12).
Clamping it would compare January against a one-day "December" of Jan 1.

⚠ The previous leg is its own statement, not a FILTER column of the current
scan (§73 prefers one scan). The two windows are disjoint and a month apart, so
one scan would read the whole gap between them; the previous month is settled
data that a 15-minute v4 refresh does not move in any way that matters here.
What MUST be shared is the population — the same ``_v4_scope_where``, the same
Losses / Unbilled clauses and the same COUNT predicate as the current leg —
otherwise a variance compares two different sets of loads (§96).
"""

from __future__ import annotations

import calendar
from datetime import date
from typing import Literal

Compare = Literal["budget", "prior_month"]
COMPARE_BASES: tuple[str, ...] = ("budget", "prior_month")


def _last_day(y: int, m: int) -> int:
    return calendar.monthrange(y, m)[1]


def _shift_back_one_month(d: date, to_month_end: bool = False) -> date:
    """Same day of the previous calendar month, clamped to that month's length
    (Mar 31 → Feb 28). ``to_month_end`` lands on the previous month's LAST day."""
    y, m = (d.year - 1, 12) if d.month == 1 else (d.year, d.month - 1)
    last = _last_day(y, m)
    return date(y, m, last if to_month_end else min(d.day, last))


def prior_month_window(start: date, end: date, today: date) -> tuple[date, date]:
    """The page window moved back one calendar month — over the SAME days.

    * The end is capped at ``today`` first. "This Month" resolves to the whole
      month (10-01 → 10-31), but nothing has shipped after today, so comparing
      with the whole previous month would score the days not yet elapsed as a
      drop. Capped, it is 10-01 → 10-12 vs 09-01 → 09-12 — Bruno's example.
    * A window of WHOLE months (starts on the 1st, ends on a month-end) maps to
      whole months: Sep 1-30 → Aug 1-31, Feb 1-28 → Jan 1-31. Anything else is
      day-for-day, so "Yesterday" on Oct 1 (Sep 30) compares with Aug 30, not
      Aug 31 (code review 2026-10-12).
    """
    end = _capped_end(start, end, today)
    whole_months = start.day == 1 and _is_month_end(end)
    return _shift_back_one_month(start), _shift_back_one_month(end, whole_months)


def full_month_window(start: date, end: date, today: date) -> tuple[date, date] | None:
    """The previous month(s) WHOLE, for a month-to-date window — else None.

    User 2026-10-12: an MTD window shows two comparisons — the same days of the
    previous month (``prior_month_window``) AND the previous month's full total,
    so the gap reads as "what is still missing to match last month by month-end".
    Oct 1-12 → Sep 1-30.

    Only a window that starts on the 1st and stops short of a month-end (after
    the today cap) has one. A whole-month window already compares whole months,
    and a window starting mid-month ("Last 7 Days") has no month-end target.
    """
    end = _capped_end(start, end, today)
    if start.day != 1 or _is_month_end(end):
        return None
    return _shift_back_one_month(start), _shift_back_one_month(end, to_month_end=True)


def _capped_end(start: date, end: date, today: date) -> date:
    return min(end, max(today, start))


def _is_month_end(d: date) -> bool:
    return d.day == _last_day(d.year, d.month)


def prior_month_sql(where: str, p_s: int, p_e: int, extra_clauses: str) -> str:
    """Per-customer volume / revenue / profit over the previous-month window.

    ``where`` and ``extra_clauses`` are the SAME strings the current leg uses;
    the COUNT predicate is the current leg's ``vol`` definition verbatim.
    ``::date + INTERVAL '1 day'`` is a half-open upper bound on a naive
    timestamp column — v4 ``origin_actual_departure`` is already CST (§112 is
    about ``timestamptz`` columns and does not apply here).
    """
    return f"""
        SELECT
          br4.customer_name AS customer_name,
          COUNT(*) FILTER (WHERE br4.total_charge IS NOT NULL AND br4.total_charge <> 0) AS vol,
          COALESCE(SUM(br4.total_charge), 0)::numeric AS rev,
          COALESCE(SUM(br4.margin_amt),  0)::numeric AS prof
        FROM public.mcleod_gld_budget_report_v4 br4
        WHERE {where}
          AND br4.origin_actual_departure >= ${p_s}
          AND br4.origin_actual_departure < (${p_e}::date + INTERVAL '1 day')
          {extra_clauses}
        GROUP BY br4.customer_name
    """


PREV = "prev"            # the same days of the previous month
PREV_FULL = "prev_full"  # the previous month whole (MTD windows only)


def prior_fields(vol: int, rev: float, prof: float,
                 vol_p: int, rev_p: float, prof_p: float, tag: str = PREV) -> dict:
    """The ``*_<tag>`` / ``*_vs_<tag>`` wire fields for one row (or the TOTAL);
    ``tag`` is ``PREV`` (same days) or ``PREV_FULL`` (whole previous month).

    Margin variance is in percentage POINTS (15.28% − 18.34% = −3.06), as in
    Bruno's mock. The "current ÷ previous" percent beside each cell is computed
    by the UI, exactly as the CORP All mode does for actual ÷ budget.
    """
    margin = (prof / rev * 100.0) if rev else 0.0
    margin_p = (prof_p / rev_p * 100.0) if rev_p else 0.0
    return {
        f"vol_{tag}": vol_p,
        f"vol_vs_{tag}": vol - vol_p,
        f"rev_{tag}": rev_p,
        f"rev_vs_{tag}": rev - rev_p,
        f"prof_{tag}": prof_p,
        f"prof_vs_{tag}": prof - prof_p,
        f"margin_{tag}_pct": margin_p,
        f"margin_vs_{tag}_pct": margin - margin_p,
    }
