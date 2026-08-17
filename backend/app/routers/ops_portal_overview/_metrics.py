"""Numeric core: the ONE Projected definition (§69) and variance maths.

Part of the ``ops_portal_overview`` package (split 2026-08-14 — see SPEC-CUSTOM-REPORTS §28).
"""

from __future__ import annotations

from datetime import date, timedelta

from ._constants import CORP_TEAMS
from ._dates import _count_workdays, _last_n_business_days_start, _month_bounds
from ._sql import _team_list, _v4_scope_where


# ---------------------------------------------------------------------------
# Projected — ONE definition for the whole report (Bruno PDF 2026-08-14 R6)
# ---------------------------------------------------------------------------
# Before this round four different formulas shipped under the name "Projected":
#
#   KPI chart (Month)  14 CALENDAR days / 14, Sundays included   → /combo
#   KPI chart (Week)   12 business days / 12, then × 7           → /team-projection
#   Team Monthly Proj. 12 BUSINESS days / 12, Sundays excluded   → /team-projection
#   Actuals Proj. EOM  the SELECTED window / 14 (hardcoded)      → /actuals
#
# Bruno's ruling: "Team Monthly Projection" is the single source of truth, so
# its window and divisor are the ones kept here and every other consumer is
# re-pointed at this helper.
#
# ⚠ Do NOT "tidy" the vol_mtd / rev_mtd asymmetry below (volume counts to
# yesterday, revenue and profit to month-end). It is what produces the numbers
# Bruno validated against — $2,301,182 revenue / $433,757 profit — so
# normalising it would move the very figure this round declares correct.
#
# ⚠ The projection is a MONTH concept: it always reads the last 12 business
# days plus month-to-date, and deliberately ignores the report's date-range
# filter. That is precisely why the Actuals projection columns can now equal
# Team Monthly Projection — under a non-default range the projection columns
# stay month-anchored while the actuals columns follow the window.

_PROJ_LOOKBACK_BUSINESS_DAYS = 12


def _projection_bounds(today: date) -> tuple[date, date, date, date, int]:
    """(win_start, win_end, month_start, month_end, pending_workdays)."""
    m_start, m_end = _month_bounds(today)
    win_start = _last_n_business_days_start(today, _PROJ_LOOKBACK_BUSINESS_DAYS)
    win_end = today - timedelta(days=1)
    return win_start, win_end, m_start, m_end, _count_workdays(today, m_end)


def _projection_sums_sql(
    where: str,
    p_ws: int, p_we: int, p_ms1: int, p_we2: int, p_ms2: int, p_me: int,
    group_col: str | None = None,
) -> str:
    """The six sums every Projected number is built from.

    ``group_col`` yields one row per group (used by /actuals for its per-
    customer rows); omit it for the report-wide figure. Bruno's "last 12
    business days" is Mon-Sat — ``EXTRACT(DOW) = 0`` is Sunday.
    """
    sel = f"{group_col} AS grp," if group_col else ""
    grp = f"GROUP BY {group_col}" if group_col else ""
    return f"""
        SELECT
          {sel}
          COUNT(*) FILTER (WHERE br4.origin_actual_departure::date BETWEEN ${p_ws} AND ${p_we}
                             AND EXTRACT(DOW FROM br4.origin_actual_departure::date) <> 0
                             AND br4.total_charge IS NOT NULL
                             AND br4.total_charge <> 0) AS vol_12,
          COALESCE(SUM(CASE WHEN br4.origin_actual_departure::date BETWEEN ${p_ws} AND ${p_we}
                              AND EXTRACT(DOW FROM br4.origin_actual_departure::date) <> 0
                            THEN br4.total_charge END), 0)::numeric AS rev_12,
          COALESCE(SUM(CASE WHEN br4.origin_actual_departure::date BETWEEN ${p_ws} AND ${p_we}
                              AND EXTRACT(DOW FROM br4.origin_actual_departure::date) <> 0
                            THEN br4.margin_amt END), 0)::numeric AS prof_12,
          COUNT(*) FILTER (WHERE br4.origin_actual_departure::date BETWEEN ${p_ms1} AND ${p_we2}
                             AND br4.total_charge IS NOT NULL
                             AND br4.total_charge <> 0) AS vol_mtd,
          COALESCE(SUM(CASE WHEN br4.origin_actual_departure::date BETWEEN ${p_ms2} AND ${p_me}
                            THEN br4.total_charge END), 0)::numeric AS rev_mtd,
          COALESCE(SUM(CASE WHEN br4.origin_actual_departure::date BETWEEN ${p_ms2} AND ${p_me}
                            THEN br4.margin_amt END), 0)::numeric AS prof_mtd,
          COUNT(DISTINCT br4.team_id) AS team_count
        FROM public.mcleod_gld_budget_report_v4 br4
        WHERE {where}
        {grp}
    """


def _projection_params(
    team, customer, load_type, lanes, exclude_lanes, carriers, exclude_carriers,
    today: date,
) -> tuple[str, list, tuple[int, int, int, int, int, int], int]:
    """Scope predicate + bound params for ``_projection_sums_sql``."""
    win_start, win_end, m_start, m_end, pending = _projection_bounds(today)
    params: list = []
    where = _v4_scope_where(
        "br4", team, customer, load_type, params,
        lanes, exclude_lanes, carriers, exclude_carriers,
    )
    params.extend([win_start, win_end, m_start, win_end, m_start, m_end])
    n = len(params)
    return where, params, (n - 5, n - 4, n - 3, n - 2, n - 1, n), pending


async def _team_projection_core(
    pool, *, team, customer, load_type, lanes, exclude_lanes,
    carriers, exclude_carriers, today: date,
) -> dict:
    """The report-wide Team Monthly Projection object — the source of truth."""
    where, params, idx, pending = _projection_params(
        team, customer, load_type, lanes, exclude_lanes,
        carriers, exclude_carriers, today,
    )
    row = await pool.fetchrow(_projection_sums_sql(where, *idx), *params)
    team_count = int(row["team_count"] or 0) if row else 0
    # Fallback only when the scan returned no rows at all. `team` may be a
    # single id or a list of them (PERFORMANCE CORP passes four), so count the
    # scope rather than testing its truthiness — `1 if team else …` would
    # charge a four-team scope one team's worth of capacity.
    team_count = team_count or len(_team_list(team)) or len(CORP_TEAMS)
    if not row:
        return _projection_from_sums(0, 0, 0, 0, 0, 0, pending, team_count)
    return _projection_from_sums(
        row["vol_12"], row["rev_12"], row["prof_12"],
        row["vol_mtd"], row["rev_mtd"], row["prof_mtd"],
        pending, team_count,
    )


def _safe_float(v) -> float:
    """Strip NaN/Inf so JSON serialization never blows up the page."""
    try:
        f = float(v) if v is not None else 0.0
    except (TypeError, ValueError):
        return 0.0
    if f != f or f in (float("inf"), float("-inf")):
        return 0.0
    return f


# ---------------------------------------------------------------------------
# Bruno (PDF 2026-07-13) — Week / Team toggles on the Team Budget Variance and
# Team Monthly Projection panels. Each returns the SAME metric set as its base
# panel, broken out by the last 5 Mon-Sun weeks or by CORP team (Total + T1..5).
# ---------------------------------------------------------------------------


def _variance_from_sums(customers, loads_a, loads_b, rev_a, rev_b, prof_a, prof_b) -> dict:
    """Build one Team-Budget-Variance object (actual − budget) from raw sums."""
    loads_var = _safe_float(loads_a) - _safe_float(loads_b)
    revenue_var = _safe_float(rev_a) - _safe_float(rev_b)
    profit_var = _safe_float(prof_a) - _safe_float(prof_b)
    margin_var_pct = (profit_var / revenue_var * 100.0) if revenue_var else 0.0
    return {
        "customers":      int(customers or 0),
        "volume_var":     _safe_float(loads_var),
        "revenue_var":    _safe_float(revenue_var),
        "profit_var":     _safe_float(profit_var),
        "margin_var_pct": _safe_float(margin_var_pct),
        "rev_x_l":        _safe_float((revenue_var / loads_var) if loads_var else 0.0),
        "prof_x_l":       _safe_float((profit_var / loads_var) if loads_var else 0.0),
    }


def _projection_from_sums(vol_12, rev_12, prof_12, vol_mtd, rev_mtd, prof_mtd,
                          pending: int, team_count: int) -> dict:
    """Build one Team-Monthly-Projection object from raw 12-day + MTD sums."""
    avg_vol = _safe_float(vol_12) / 12.0
    avg_rev = _safe_float(rev_12) / 12.0
    avg_prof = _safe_float(prof_12) / 12.0
    proj_vol = avg_vol * pending + _safe_float(vol_mtd)
    proj_rev = avg_rev * pending + _safe_float(rev_mtd)
    proj_prof = avg_prof * pending + _safe_float(prof_mtd)
    cap = 500.0 * (team_count or 0)
    return {
        "avg_vol_day":  _safe_float(avg_vol),
        "avg_rev_day":  _safe_float(avg_rev),
        "avg_prof_day": _safe_float(avg_prof),
        "pending_workdays": pending,
        "proj_volume":  _safe_float(proj_vol),
        "proj_revenue": _safe_float(proj_rev),
        "proj_profit":  _safe_float(proj_prof),
        "proj_margin_pct": _safe_float((proj_prof / proj_rev * 100.0) if proj_rev else 0.0),
        "proj_rev_x_l":  _safe_float((proj_rev / proj_vol) if proj_vol else 0.0),
        "proj_prof_x_l": _safe_float((proj_prof / proj_vol) if proj_vol else 0.0),
        "proj_team_ut":  _safe_float((proj_vol / cap * 100.0) if cap else 0.0),
    }
