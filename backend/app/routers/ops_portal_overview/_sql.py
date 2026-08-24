"""Reusable SQL fragments — scope predicate, scorecard CTEs, lane/carrier keys.

Part of the ``ops_portal_overview`` package (split 2026-08-14 — see SPEC-CUSTOM-REPORTS §28).
"""

from __future__ import annotations

from typing import List, Optional, Sequence, Union


from app.datalake import pad_variants as _pad_variants

from ._constants import CORP_COMPANIES, CORP_TEAMS, OPEN_STATUSES, OTD_CODES, OTP_CODES
from ._scope import CORP_SCOPE, DivisionScope, case_variants

# A scope is one team, several teams, or none (= the whole CORP base scope).
TeamScope = Union[str, Sequence[str], None]


def _team_list(team: TeamScope) -> List[str]:
    """Normalise a team scope to a list of ids. ``None``/empty → ``[]``.

    Every team-scoped predicate in this package goes through here, so a single
    team and a list of teams take the same code path and cannot drift. A bare
    string is NOT iterated character-wise — that would silently scope a query
    to ``['T','E','A','M','1']`` and return nothing.

    Anything that is neither a string nor a list of strings is treated as "no
    scope" — see ``_parse_team_scope`` for why that matters.
    """
    if not team:
        return []
    if isinstance(team, str):
        return [team]
    if isinstance(team, (list, tuple, set, frozenset)):
        return [t for t in team if isinstance(t, str) and t]
    return []


def _parse_team_scope(team: TeamScope = None, teams: Optional[str] = None) -> List[str]:
    """Resolve the ``(team, teams)`` query-parameter pair into a team list.

    ``teams`` is the comma-separated multi-team form (same shape
    ``budget_followup._parse_teams`` uses); ``team`` is the single-team form the
    UI has always sent. ``teams`` wins when both are given. An empty result
    means "no narrowing" — the CORP base predicate in ``_v4_scope_where``
    still applies, so this is never an unscoped query.

    ⚠ Both arguments are type-checked rather than merely truth-tested. Several
    endpoints in this package are ALSO called as plain Python functions —
    ``ops_portal_overview_team.py`` does exactly that for /team-performance,
    /team-projection, /profit-tm-gauge and /actuals — and such a caller omits
    the newer parameter entirely. Python then binds the literal
    ``Query(None)`` DEFAULT OBJECT, which is truthy and has no ``.split``. A
    plain ``if teams:`` would therefore raise ``AttributeError`` on every
    per-team portal view while working perfectly over HTTP, where FastAPI
    resolves the default to ``None``. Caught by
    ``test_ops_portal_projection.py`` — keep the isinstance guards.
    """
    if isinstance(teams, str) and teams.strip():
        return [t.strip().upper() for t in teams.split(",") if t.strip()]
    return [t.strip().upper() for t in _team_list(team)]


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



def _sub_team_param(scope: DivisionScope, team_ids: Sequence[str]) -> List[str]:
    """Bound array for narrowing to specific sub-teams under ``scope``.

    Padded variants for the narrow ``varchar(8)`` ``team_id``; case variants for
    the wide unpadded ``team`` / ``team_dfw``. Pair it with
    ``scope.v4_team_col`` (v4) or ``scope.sc_team_col`` (scorecard) — using the
    wrong column silently returns zero rows rather than erroring.
    """
    if scope.padded_sub_teams:
        return _pad_variants(list(team_ids), width=8)
    return case_variants(list(team_ids))


def _team_id_col(alias: str, scope: DivisionScope = CORP_SCOPE) -> str:
    """The scope's team COLUMN — a bare reference, no alias, safe to wrap.

    Use this anywhere the column feeds an expression: ``TRIM(...)``, a
    ``GROUP BY``, a predicate. Use ``_team_id_select`` only for a bare SELECT
    item, where the ``AS team_id`` it appends is legal.
    """
    return f"{alias}.{scope.v4_team_col}"


def _team_id_select(alias: str, scope: DivisionScope = CORP_SCOPE) -> str:
    """The scope's team column as a SELECT ITEM, always surfacing as ``team_id``.

    CORP renders bare ``br4.team_id`` — no redundant alias — so the emitted SQL
    stays byte-identical to the pre-scope version and the equivalence harness in
    ``tests/test_ops_portal_scope.py`` keeps its teeth.

    ⚠ Under any non-CORP scope this returns ``br4.<col> AS team_id`` — an alias,
    not an expression — so it can NEVER be wrapped in a function call.
    ``TRIM({_team_id_select(...)})`` renders ``TRIM(br4.team AS team_id)``, which
    Postgres rejects with ``42601 syntax error at or near "AS"``. It shipped that
    way in ``hold.py`` and took the DFW Hold board down on every sort key while
    CORP — where the helper returns a bare column — stayed green. Wrap
    ``_team_id_col`` instead; a test scans this package's source for the
    mistake (§81).
    """
    col = _team_id_col(alias, scope)
    return col if scope.v4_team_col == "team_id" else f"{col} AS team_id"


def _v4_scope_where(
    alias: str,
    team: TeamScope,
    customer: Optional[str],
    load_type: Optional[str],
    params: list,
    lanes: Optional[List[str]] = None,
    exclude_lanes: Optional[List[str]] = None,
    carriers: Optional[List[str]] = None,
    exclude_carriers: Optional[List[str]] = None,
    scope: DivisionScope = CORP_SCOPE,
) -> str:
    """Division-scope WHERE for ``mcleod_gld_budget_report_v4``.

    Sargable (no TRIM()): pushes padded+unpadded literal variants per the
    width=8 / width=4 / width=1 declared schema on team_id / company_id /
    status. ``customer`` is exact-match (single select). ``load_type`` is
    "contract" or "spot" — falls back to no filter when None/empty.
    ``lanes`` / ``exclude_lanes`` (Bruno R7) are multi-select lane keys —
    empty/None means no filter.

    ``scope`` selects the division (see ``_scope.py``). With the default
    ``CORP_SCOPE`` the emitted SQL is byte-identical to the pre-2026-08-21
    version — asserted against a captured baseline in
    ``tests/test_ops_portal_scope.py``, since five live portals share this.
    """
    teams_param = _pad_variants(scope.base_teams, width=8)
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
    # One team or four — same predicate, same shape. The emitted SQL is
    # byte-identical either way; only the bound array grows. Each id must go
    # through pad_variants: McLeod stores team_id BOTH unpadded ('TEAM1', in
    # budget_report_v4) and right-padded to varchar(8) ('TEAM1   ', in the
    # scorecard tables), so a literal IN ('TEAM1',...) matches ZERO scorecard
    # rows and would silently zero OTP/OTD rather than fail.
    #
    # Under DFW the narrowing column is `team` (TM1..TM5), not `team_id` —
    # `team_id` is constant there. `team` is varchar(512) and stored unpadded,
    # so pad_variants would be a no-op; what it DOES carry is mixed case
    # ('tm4' on 2 rows vs 16,312 'TM4', measured 2026-08-21), so both spellings
    # go into the bound array. UPPER() on the column would drop sargability.
    team_ids = _team_list(team)
    if team_ids:
        params.append(_sub_team_param(scope, team_ids))
        parts.append(f"{alias}.{scope.v4_team_col} = ANY(${len(params)})")
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


def _scorecard_cte(kind: str, scope: DivisionScope = CORP_SCOPE) -> str:
    """OTP/OTD per-order roll-up — same shape as xray_corp._scorecard_cte.

    Reads ``mcleod_gld_scorecard_incidents_portal`` (incident grain) since
    2026-06-15 — real stop types only (no '' bucket); ``COUNT(DISTINCT id)`` keeps
    it fan-out-safe. See SPEC-CODE-RULES §43.

    ``scope`` only swaps the ``team_id`` division literal; the CTE never narrows
    to a sub-team, because the join back to v4 already restricts each order.
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
    teams_sql = _lit(scope.base_teams, width=8)
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


def _bill_metrics_sql(
    where: str, p_s: int, p_e: int, *, group_by_team: bool,
    scope: DivisionScope = CORP_SCOPE,
) -> str:
    """Per-order billing metrics — Bruno round (2026-07-01) R12.

      avg_days_billed     = AVG(bill_date − dest_actual_departure) over billed orders
      avg_days_not_billed = AVG(CURRENT_DATE − dest_actual_departure) over unbilled orders
      del_bill_le2/denom  = Delivery-vs-Bill <=2D ratio (mirrors admin-cashflow)

    ``bill_date`` is on v4; ``dest_actual_departure``/``dest_actual_arrival`` come
    from ``mcleod_gld_customer_windows`` (same sentinel-guarded LATERAL as By
    Order R11, so the panel reconciles with the Days-to-Bill column). When
    ``group_by_team`` the result carries one row per ``team_id``.
    """
    # The output column stays `team_id` whatever it is read from — the wire
    # contract and every by-team panel key off that name (§69: one name, one
    # definition). Under DFW the VALUES become TM1..TM5.
    team_sel = f"TRIM(br4.{scope.v4_team_col}) AS team_id," if group_by_team else ""
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
