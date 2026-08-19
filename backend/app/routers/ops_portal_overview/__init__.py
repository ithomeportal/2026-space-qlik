"""Code-made report: Ops Portal - Overview.

Single-page Ops landing requested by Bruno (2026-05-10 PDF — round 1). Merges
three sources into one view:

- Production — public.mcleod_gld_budget_report_v4 (load-level) + scorecard for
  OTP/OTD; mirrors xray-corp-mng's CORP-scope filter contract.
- Budget — public.daily_production_budget_report (refreshed every 6h by n8n);
  joined to v4 via customer_team CTE for canonical team mapping.
- Savings — public.carriers_savings_results_report (variance > 0 = savings,
  variance < 0 = over-pay).

All three live on SAVINGS_DATABASE_URL (aivn_datalake_gold) → one shared pool
(``get_datalake_gold_pool``).

Scope: CORP only (TEAM1-TEAM5). The PDF explicitly excludes TEAM-DFW.

Two formula corrections from Bruno's PDF (confirmed with Diego 2026-05-10):
  A) §2/§3/Actuals "Volume" was typoed as ``loads_budget − loads_budget = 0``.
     Real intent is variance: ``loads_budget − loads_actual`` (§2/§3 follow
     Bruno's existing budget-minus-actual convention for Revenue/Profit; the
     bottom Actuals table sub-row uses ``actual − budget`` to match the
     ``133 / 153 / -20`` Kohler MTY mock).
  B) §5 "Profit / Margin / Prof×L" had ``where margin_amt<0`` filter (a paste
     from the dedicated "Profit Loss" row). The example shows $23,000 positive
     so the top-of-table Profit/Margin/Prof×L drop the filter; the explicitly
     named "Loads w/ Loss" and "Profit Loss" rows keep it.

Endpoints (all under /api/custom/ops-portal-overview, all guarded by
``require_report_access("ops-portal-overview")``):

  /filters             → teams + distinct customers
  /workdays            → Total / Past / Pending workday KPIs
  /combo               → 12-month combo (bars: Vol|Rev|Prof|Marg toggle ·
                         lines: Losses, Budget, Projected TM) — ignores Date filter
  /team-variance       → §2 — scope-wide Budget vs Actual variance row
  /customer-variance   → §3 — per-customer Budget vs Actual variance
  /customer-losses     → §4 — per-customer Production losses (margin<0)
  /team-performance    → §5 — single-row team Production+Savings KPIs
  /team-projection     → §6 — single-row team rolling 14d projection
  /profit-tm-gauge     → bottom-middle Profit-TM gauge (MTD profit vs budget)
  /actuals             → bottom Actuals per-customer roll-up

Date-filter semantics:
  - /combo, /team-projection, /workdays, /profit-tm-gauge IGNORE the Date filter
    (rolling/MTD-pinned per Bruno's "should not change with the date filter").
  - All other endpoints honor it.
  - Team + Customer filters apply everywhere.
  - Lane filter (Bruno R7, 2026-06-05 — multi-select with exclusion;
    ``concat(origin_name, ' - ', dest_name)``) applies to every v4-based
    query. The budget-only panels (§2 /team-variance, §3 /customer-variance)
    and the budget/savings sub-queries can't honor it —
    ``daily_production_budget_report`` / ``carriers_savings_results_report``
    have no lane grain (same precedent as ``load_type``).
"""

# ---------------------------------------------------------------------------
# Split into a package on 2026-08-14 (was a single 4,076-line module).
#
# This file is a FAÇADE and must stay one: `ops_portal_overview_team.py`,
# `ops_team_perf_digest.py` and `services/team_perf_digest.py` all reach in for
# helpers by name (`opo._lane_expr`, `CORP_TEAMS`, `_v4_scope_where`, …), so
# every public symbol is re-exported here and those call sites are unchanged.
#
# Importing the endpoint modules is what REGISTERS their routes on the shared
# `router` — the import list below is load-bearing, not decorative.
# ---------------------------------------------------------------------------

from ._constants import (  # noqa: F401
    CORP_COMPANIES,
    CORP_TEAMS,
    CUSTOMER_TEAM_CTE,
    OPEN_STATUSES,
    OTD_CODES,
    OTP_CODES,
    YEAR_END,
    YEAR_START,
    router,
)
from ._dates import (  # noqa: F401
    _clamp,
    _count_workdays,
    _last_5_weeks,
    _last_n_business_days_start,
    _month_bounds,
    _resolve_grain_window,
    _resolve_range,
    _week_label,
)
from ._sql import (  # noqa: F401
    _ASSIGNED,
    _bill_metrics_sql,
    _carrier_first_expr,
    _lane_expr,
    _parse_team_scope,
    _scorecard_cte,
    _team_list,
    _v4_scope_where,
)
from ._metrics import (  # noqa: F401
    _PROJ_LOOKBACK_BUSINESS_DAYS,
    _projection_bounds,
    _projection_from_sums,
    _projection_params,
    _projection_sums_sql,
    _safe_float,
    _team_projection_core,
    _variance_from_sums,
)

# Route registration — order preserved for readability; every path is a
# static literal, so FastAPI matching does not depend on it.
from .meta import (  # noqa: F401
    data_freshness,
    filters,
    workdays,
)
from .chart import (  # noqa: F401
    combo,
    cover_forecast,
    service,
)
from .variance import (  # noqa: F401
    customer_losses,
    customer_not_billed,
    customer_variance,
    team_variance,
    team_variance_by_team,
    team_variance_weekly,
)
from .performance import (  # noqa: F401
    team_performance,
    team_performance_by_team,
    team_weekly_performance,
)
from .projection import (  # noqa: F401
    profit_tm_gauge,
    team_projection,
    team_projection_by_team,
    team_projection_weekly,
)
from .actuals import (  # noqa: F401
    actuals,
    actuals_by_lane,
    margin_distribution,
)
from .orders import (  # noqa: F401
    by_order,
    cover,
    pending_to_cover,
)
# Bruno PDF 2026-08-19 R1 — the Hold board. Its own module rather than more
# lines in orders.py, which is already 595 of the package's 800-line cap.
from .hold import hold_board  # noqa: F401
from .incidents import (  # noqa: F401
    service_by_carrier,
    service_incident_by_customer,
)

__all__ = [
    "CORP_COMPANIES",
    "CORP_TEAMS",
    "CUSTOMER_TEAM_CTE",
    "OPEN_STATUSES",
    "OTD_CODES",
    "OTP_CODES",
    "YEAR_END",
    "YEAR_START",
    "_ASSIGNED",
    "_BY_ORDER_SORTS",
    "_DEL_CODE_LIT",
    "_DEL_STOP_LIT",
    "_FRESHNESS_TTL",
    "_PROJ_LOOKBACK_BUSINESS_DAYS",
    "_PU_CODE_LIT",
    "_PU_STOP_LIT",
    "_bill_fields",
    "_bill_metrics_sql",
    "_carrier_first_expr",
    "_clamp",
    "_count_workdays",
    "_freshness_cache",
    "_lane_expr",
    "_last_5_weeks",
    "_last_n_business_days_start",
    "_month_bounds",
    "_parse_team_scope",
    "_projection_bounds",
    "_projection_from_sums",
    "_projection_params",
    "_projection_sums_sql",
    "_resolve_grain_window",
    "_resolve_range",
    "_safe_float",
    "_scorecard_cte",
    "_team_list",
    "_team_perf_obj",
    "_team_projection_core",
    "_v4_scope_where",
    "_variance_from_sums",
    "_week_label",
    "actuals",
    "actuals_by_lane",
    "by_order",
    "hold_board",
    "combo",
    "cover",
    "cover_forecast",
    "customer_losses",
    "customer_not_billed",
    "customer_variance",
    "data_freshness",
    "filters",
    "margin_distribution",
    "pending_to_cover",
    "profit_tm_gauge",
    "router",
    "service",
    "service_by_carrier",
    "service_incident_by_customer",
    "team_performance",
    "team_performance_by_team",
    "team_projection",
    "team_projection_by_team",
    "team_projection_weekly",
    "team_variance",
    "team_variance_by_team",
    "team_variance_weekly",
    "team_weekly_performance",
    "workdays",
]
