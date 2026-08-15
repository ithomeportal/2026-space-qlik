"""Reusable SQL fragments — scope predicate, scorecard CTEs, lane/carrier keys.

Part of the ``ops_portal_overview`` package (split 2026-08-14 — see SPEC-CUSTOM-REPORTS §28).
"""

from __future__ import annotations

from typing import List, Optional


from app.datalake import pad_variants as _pad_variants

from ._constants import CORP_COMPANIES, CORP_TEAMS, OPEN_STATUSES, OTD_CODES, OTP_CODES


def _lane_expr(alias: str) -> str:
    """Lane key — ``concat(origin_name, ' - ', dest_name)`` per Bruno R7.

    COALESCE so a NULL origin/dest never turns the whole concat NULL (a NULL
    lane would silently drop rows under ``<> ALL`` exclusion). TRIM here is
    fine sargability-wise: lane is never the access path — the date + scope
    predicates narrow first (same expression /actuals-by-lane already groups
    by).
    """
    return (
        f"(TRIM(COALESCE({alias}.origin_name,'')) || ' - ' || "
        f"TRIM(COALESCE({alias}.dest_name,'')))"
    )


def _carrier_first_expr(alias: str) -> str:
    """First-movement carrier (``payee_name``) for a v4 order.

    Matches exactly what the By Order table / by-Carrier table display: the
    payee of the earliest movement (``ORDER BY movement_id``). Used only when a
    carrier filter is active, so the correlated subquery cost is never paid on
    the default (unfiltered) path.
    """
    return (
        f"(SELECT TRIM(m.payee_name) FROM public.mcleod_gld_movement m "
        f"WHERE m.order_id = {alias}.id AND m.company_id = {alias}.company_id "
        f"ORDER BY m.movement_id ASC LIMIT 1)"
    )


def _v4_scope_where(
    alias: str,
    team: Optional[str],
    customer: Optional[str],
    load_type: Optional[str],
    params: list,
    lanes: Optional[List[str]] = None,
    exclude_lanes: Optional[List[str]] = None,
    carriers: Optional[List[str]] = None,
    exclude_carriers: Optional[List[str]] = None,
) -> str:
    """CORP-scope WHERE for ``mcleod_gld_budget_report_v4``.

    Sargable (no TRIM()): pushes padded+unpadded literal variants per the
    width=8 / width=4 / width=1 declared schema on team_id / company_id /
    status. ``customer`` is exact-match (single select). ``load_type`` is
    "contract" or "spot" — falls back to no filter when None/empty.
    ``lanes`` / ``exclude_lanes`` (Bruno R7) are multi-select lane keys —
    empty/None means no filter.
    """
    teams_param = _pad_variants(CORP_TEAMS, width=8)
    companies_param = _pad_variants(CORP_COMPANIES, width=4)
    statuses_param = _pad_variants(OPEN_STATUSES, width=1)

    params.append(teams_param)
    p_teams = len(params)
    params.append(companies_param)
    p_companies = len(params)
    params.append(statuses_param)
    p_status = len(params)

    parts = [
        f"{alias}.team_id    = ANY(${p_teams})",
        f"{alias}.company_id = ANY(${p_companies})",
        f"{alias}.status     = ANY(${p_status})",
        f"UPPER(COALESCE({alias}.customer_name,'')) NOT LIKE '%OILTEX%'",
    ]
    if team:
        params.append(_pad_variants([team], width=8))
        parts.append(f"{alias}.team_id = ANY(${len(params)})")
    if customer:
        params.append(customer)
        parts.append(f"{alias}.customer_name = ${len(params)}")
    if load_type and load_type.lower() in ("contract", "spot"):
        params.append(load_type.lower())
        parts.append(
            f"LOWER(TRIM(COALESCE({alias}.contract_type_descr,''))) = ${len(params)}"
        )
    if lanes:
        params.append(lanes)
        parts.append(f"{_lane_expr(alias)} = ANY(${len(params)})")
    if exclude_lanes:
        params.append(exclude_lanes)
        parts.append(f"{_lane_expr(alias)} <> ALL(${len(params)})")
    # Bruno (PDF 2026-07-15) R1: Carrier multi-select (Include/Exclude), matched
    # against the first-movement payee — consistent with the By Order / by-Carrier
    # display. Correlated subquery cost only when a carrier is actually selected.
    if carriers:
        params.append(carriers)
        parts.append(f"{_carrier_first_expr(alias)} = ANY(${len(params)})")
    if exclude_carriers:
        params.append(exclude_carriers)
        parts.append(f"COALESCE({_carrier_first_expr(alias)}, '') <> ALL(${len(params)})")
    return " AND ".join(parts)


def _scorecard_cte(kind: str) -> str:
    """OTP/OTD per-order roll-up — same shape as xray_corp._scorecard_cte.

    Reads ``mcleod_gld_scorecard_incidents_portal`` (incident grain) since
    2026-06-15 — real stop types only (no '' bucket); ``COUNT(DISTINCT id)`` keeps
    it fan-out-safe. See SPEC-CODE-RULES §43.
    """
    if kind == "otp":
        codes = OTP_CODES
        stops = ("PU", "SH")
        out = "scorecard_count_otp"
    else:
        codes = OTD_CODES
        stops = ("CO", "SO")
        out = "scorecard_count_otd"

    def _lit(values, *, width: int) -> str:
        return ",".join(f"'{v}'" for v in _pad_variants(values, width=width))

    codes_sql = _lit(codes, width=40)
    stops_sql = _lit(stops, width=2)
    teams_sql = _lit(CORP_TEAMS, width=8)
    companies_sql = _lit(CORP_COMPANIES, width=4)
    statuses_sql = _lit(OPEN_STATUSES, width=1)
    return f"""
    SELECT
      TRIM(id)         AS id_key,
      TRIM(company_id) AS company_id_key,
      COUNT(DISTINCT id) AS {out}
    FROM public.mcleod_gld_scorecard_incidents_portal
    WHERE team_id    IN ({teams_sql})
      AND company_id IN ({companies_sql})
      AND status     IN ({statuses_sql})
      AND stop_type  IN ({stops_sql})
      AND total_charge IS NOT NULL AND total_charge <> 0
      AND edi_standard_code IN ({codes_sql})
    GROUP BY TRIM(id), TRIM(company_id)
    """


def _bill_metrics_sql(where: str, p_s: int, p_e: int, *, group_by_team: bool) -> str:
    """Per-order billing metrics — Bruno round (2026-07-01) R12.

      avg_days_billed     = AVG(bill_date − dest_actual_departure) over billed orders
      avg_days_not_billed = AVG(CURRENT_DATE − dest_actual_departure) over unbilled orders
      del_bill_le2/denom  = Delivery-vs-Bill <=2D ratio (mirrors admin-cashflow)

    ``bill_date`` is on v4; ``dest_actual_departure``/``dest_actual_arrival`` come
    from ``mcleod_gld_customer_windows`` (same sentinel-guarded LATERAL as By
    Order R11, so the panel reconciles with the Days-to-Bill column). When
    ``group_by_team`` the result carries one row per ``team_id``.
    """
    team_sel = "TRIM(br4.team_id) AS team_id," if group_by_team else ""
    team_out = "team_id," if group_by_team else ""
    group_clause = "GROUP BY team_id" if group_by_team else ""
    return f"""
        WITH ord AS (
            SELECT
              {team_sel}
              br4.bill_date AS bill_date,
              win.dest_dep, win.dest_arr
            FROM public.mcleod_gld_budget_report_v4 br4
            LEFT JOIN LATERAL (
                SELECT MAX(CASE WHEN cw.dest_actual_departure > '2000-01-01' THEN cw.dest_actual_departure END) AS dest_dep,
                       MAX(CASE WHEN cw.dest_actual_arrival   > '2000-01-01' THEN cw.dest_actual_arrival   END) AS dest_arr
                FROM public.mcleod_gld_customer_windows cw
                WHERE TRIM(UPPER(cw.id)) = TRIM(UPPER(br4.id))
            ) win ON TRUE
            WHERE {where}
              AND br4.origin_actual_departure >= ${p_s}
              AND br4.origin_actual_departure < (${p_e}::date + INTERVAL '1 day')
        )
        SELECT
          {team_out}
          AVG(bill_date::date - dest_dep::date)
            FILTER (WHERE bill_date > '2000-01-01' AND dest_dep IS NOT NULL) AS avg_days_billed,
          AVG(CURRENT_DATE - dest_dep::date)
            FILTER (WHERE bill_date < '2000-01-01' AND dest_dep IS NOT NULL) AS avg_days_not_billed,
          COUNT(*) FILTER (WHERE bill_date > '2000-01-01' AND dest_dep IS NOT NULL AND dest_arr IS NOT NULL) AS del_bill_denom,
          COUNT(*) FILTER (WHERE bill_date > '2000-01-01' AND dest_dep IS NOT NULL AND dest_arr IS NOT NULL
                             AND (bill_date::date - dest_dep::date) <= 2) AS del_bill_le2
        FROM ord
        {group_clause}
    """


# ---------------------------------------------------------------------------
# /cover — Bruno (PDF 2026-07-20) R1: every status='A' load ("Cover" toggle in
# the By Order panel). Superset of /pending-to-cover, which shows only the
# status='A' loads that have no carrier yet.
# ---------------------------------------------------------------------------

# "This load has a carrier" — the predicate that splits Cover from Pending.
# Named once so the row list, the pinned totals and the counts can never drift.
_ASSIGNED = "COALESCE(TRIM(mov.payee_name), '') <> ''"
