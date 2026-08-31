"""The ONE Attrition definition — shared by Attrition WoW and Ops Portal Overview.

Bruno (PDF "space -- Ops Portal Updates", 2026-08-31) Request 3:

    The variable "Cust. Attrition %" must match the "% Δ" variable from the
    "CUSTOMER ATTRITION" container in .../reports/attrition-wow.
    The variable "Lane Attrition %" must match the "% Δ" ... "LANE ATTRITION" ...

Before this round the two reports shipped **different metrics** under the same
label, which is why they never agreed (§95):

    attrition-wow  "% Δ"          (L8W_avg − LW) / L8W_avg   signed, a rate
    ops-portal     "Cust. Attr %"  stale>30d / YTD-2026 roster  unsigned, a census

The ops-portal version was never a ported formula — ``SPEC-CUSTOM-REPORTS.md``
records it as a **round-1 assumption made because Bruno's original PDF gave no
formula at all**. So this module makes attrition-wow's definition the canonical
one and both reports read it from here.

⚠ Why a SQL FRAGMENT and not a coroutine. ``attrition_wow.summary`` computes
the attrition counts inside one big multi-metric statement (loads, revenue,
profit, L2W, …). Extracting a coroutine would have added a second round-trip to
the busiest endpoint in that report purely to satisfy a refactor. Handing out
the fragment + the arithmetic keeps attrition-wow at exactly one statement AND
guarantees the arithmetic cannot drift — ``attrition_from_counts`` is the only
place the ``/8`` and the sign live.

⚠ The POPULATION rule is part of the definition, not decoration. attrition-wow
excludes ``%UNILINK%`` as well as ``%OILTEX%``, and its lane key COALESCEs the
endpoints so a row with a blank origin/dest becomes a `" - "` bucket rather
than vanishing. The ops-portal scope predicate does neither, so
``population_extra_where`` exists to bolt attrition-wow's rules onto it. Omit
it and the two reports diverge again, silently, with no error (§95).
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Optional

from app.clock import cst_today

# The rolling baseline is a FIXED divisor: 8 completed weeks. An empty week
# still divides by 8, which is the whole point of the weekly-average form
# (Bruno R17/R18 — it replaced a union-distinct denominator that counted a
# customer once no matter how many of the 8 weeks it was active in).
ATTRITION_WEEKS = 8


# ---------------------------------------------------------------------------
# Windows — completed Mon-Sun ISO weeks. The in-progress week is NEVER included.
# ---------------------------------------------------------------------------


def last_completed_week(today: Optional[date] = None) -> tuple[date, date]:
    """The most recent finished Mon-Sun week (inclusive both ends)."""
    today = today or cst_today()
    this_monday = today - timedelta(days=today.weekday())
    last_sunday = this_monday - timedelta(days=1)
    last_monday = last_sunday - timedelta(days=6)
    return last_monday, last_sunday


def l8w_window(today: Optional[date] = None) -> tuple[date, date]:
    """The 8 completed weeks ENDING the day before ``last_completed_week`` starts.

    The two windows are adjacent and disjoint: LW is never inside its own
    baseline, so a strong week cannot pull up the average it is compared with.
    """
    lw_mon, _ = last_completed_week(today)
    end = lw_mon - timedelta(days=1)
    start = end - timedelta(days=ATTRITION_WEEKS * 7 - 1)
    return start, end


# ---------------------------------------------------------------------------
# Population — the part that is easy to leave out and impossible to notice
# ---------------------------------------------------------------------------


def lane_key_expr(alias: str) -> str:
    """Lane = ``trim(origin) || ' - ' || trim(dest)``, COALESCEd.

    ⚠ Without the COALESCE a NULL endpoint makes the whole concat NULL and
    ``COUNT(DISTINCT lane)`` drops the row instead of bucketing it. The
    ops-portal's own ``_lane_expr`` COALESCEs too, but its attrition query used
    to additionally require ``TRIM(origin) <> '' AND TRIM(dest) <> ''`` —
    a different population. Both reports now use this.
    """
    return (
        f"TRIM(COALESCE({alias}.origin_name,'')) "
        f"|| ' - ' || "
        f"TRIM(COALESCE({alias}.dest_name,''))"
    )


def population_extra_where(alias: str) -> str:
    """attrition-wow's customer exclusions, as an AND-able fragment.

    ``ops_portal_overview._v4_scope_where`` already excludes OILTEX but NOT
    UNILINK (inter-company freight). Appending this to it makes the two
    reports' populations identical. Repeating the OILTEX clause is harmless —
    Postgres folds the duplicate predicate — and keeps this fragment complete
    enough to be correct on its own.
    """
    return (
        f"UPPER(COALESCE({alias}.customer_name,'')) NOT LIKE '%UNILINK%' "
        f"AND UPPER(COALESCE({alias}.customer_name,'')) NOT LIKE '%OILTEX%'"
    )


# ---------------------------------------------------------------------------
# The SQL fragment
# ---------------------------------------------------------------------------


def attrition_counts_sql(
    where: str,
    p_l8s: int,
    p_l8e: int,
    p_lws: int,
    p_lwe: int,
    *,
    alias: str = "br4",
    entity_expr: Optional[str] = None,
    group_col: Optional[str] = None,
) -> str:
    """A standalone statement returning the four raw counts attrition needs.

    ``group_col`` yields one row per group (plus a ``grp`` column) instead of a
    single scope-wide row — see ``_grouped_sql`` for why those rows must not be
    summed into a Total.

    ``entity_expr`` is the customer dimension — ``TRIM(br4.client)`` under
    attrition-wow's RUAN view, ``TRIM(br4.customer_name)`` everywhere else.

    Returns one row: ``l8w_lanes_sum``, ``l8w_customers_sum`` (SUMS of the
    per-week distinct counts, NOT union-distinct — divide by
    ``ATTRITION_WEEKS`` in Python), ``lw_lanes``, ``lw_customers``.

    Callers that already scan this window for other metrics should inline the
    two CTEs instead (see ``attrition_wow.summary``); the arithmetic in
    ``attrition_from_counts`` is what must be shared, not the round-trip.
    """
    entity = entity_expr or f"TRIM({alias}.customer_name)"
    if group_col:
        return _grouped_sql(
            where, p_l8s, p_l8e, p_lws, p_lwe,
            alias=alias, entity=entity, group_col=group_col,
        )
    return f"""
        WITH base AS (
          SELECT
            {alias}.origin_actual_departure::date AS dep_date,
            {lane_key_expr(alias)}                AS lane,
            {entity}                              AS customer_name
          FROM public.mcleod_gld_budget_report_v4 {alias}
          WHERE {where}
            AND {alias}.origin_actual_departure::date BETWEEN ${p_l8s} AND ${p_lwe}
        ),
        l8w_weekly AS (
          SELECT date_trunc('week', dep_date)::date AS wk,
                 COUNT(DISTINCT lane)          AS n_lanes,
                 COUNT(DISTINCT customer_name) AS n_customers
          FROM base
          WHERE dep_date BETWEEN ${p_l8s} AND ${p_l8e}
          GROUP BY 1
        )
        SELECT
          (SELECT COALESCE(SUM(n_lanes), 0)     FROM l8w_weekly) AS l8w_lanes_sum,
          (SELECT COALESCE(SUM(n_customers), 0) FROM l8w_weekly) AS l8w_customers_sum,
          COUNT(DISTINCT lane)          FILTER (WHERE dep_date BETWEEN ${p_lws} AND ${p_lwe}) AS lw_lanes,
          COUNT(DISTINCT customer_name) FILTER (WHERE dep_date BETWEEN ${p_lws} AND ${p_lwe}) AS lw_customers
        FROM base
    """


def _grouped_sql(
    where: str,
    p_l8s: int,
    p_l8e: int,
    p_lws: int,
    p_lwe: int,
    *,
    alias: str,
    entity: str,
    group_col: str,
) -> str:
    """One row per ``group_col`` value — used by the per-team breakdown modal.

    ⚠ FULL OUTER JOIN, not INNER. A team that shipped in the 8-week baseline
    and then went completely quiet last week has no ``lw`` row at all; an inner
    join would DELETE it, which is the one row a reader most needs to see —
    100% attrition would render as a missing line (§91, §75).

    ⚠ These per-group rows CANNOT be summed into a Total. A customer that
    shipped on two teams is distinct within each group and would be counted
    twice. Read the Total from an UNGROUPED call over the same scope, exactly
    as the distinct customer/lane counts beside it already do.
    """
    return f"""
        WITH base AS (
          SELECT
            {alias}.origin_actual_departure::date AS dep_date,
            {lane_key_expr(alias)}                AS lane,
            {entity}                              AS customer_name,
            {group_col}                           AS grp
          FROM public.mcleod_gld_budget_report_v4 {alias}
          WHERE {where}
            AND {alias}.origin_actual_departure::date BETWEEN ${p_l8s} AND ${p_lwe}
        ),
        l8w_weekly AS (
          SELECT grp, date_trunc('week', dep_date)::date AS wk,
                 COUNT(DISTINCT lane)          AS n_lanes,
                 COUNT(DISTINCT customer_name) AS n_customers
          FROM base
          WHERE dep_date BETWEEN ${p_l8s} AND ${p_l8e}
          GROUP BY 1, 2
        ),
        l8w AS (
          SELECT grp,
                 COALESCE(SUM(n_lanes), 0)     AS l8w_lanes_sum,
                 COALESCE(SUM(n_customers), 0) AS l8w_customers_sum
          FROM l8w_weekly GROUP BY grp
        ),
        lw AS (
          SELECT grp,
                 COUNT(DISTINCT lane)          AS lw_lanes,
                 COUNT(DISTINCT customer_name) AS lw_customers
          FROM base
          WHERE dep_date BETWEEN ${p_lws} AND ${p_lwe}
          GROUP BY grp
        )
        SELECT
          grp,
          COALESCE(l8w.l8w_lanes_sum, 0)     AS l8w_lanes_sum,
          COALESCE(l8w.l8w_customers_sum, 0) AS l8w_customers_sum,
          COALESCE(lw.lw_lanes, 0)           AS lw_lanes,
          COALESCE(lw.lw_customers, 0)       AS lw_customers
        FROM l8w FULL OUTER JOIN lw USING (grp)
    """


# ---------------------------------------------------------------------------
# The arithmetic — the ONE place the /8 and the sign live
# ---------------------------------------------------------------------------


def _f(v) -> float:
    return float(v) if v is not None else 0.0


def _attr_block(lw: float, l8w: float) -> dict:
    """One attrition card: L8W average, LW, the count Δ and the signed % Δ.

    ⚠ The two numerators are deliberately OPPOSITE (Bruno R13, 2026-07-01):

        diff = LW − L8W      a count — positive means MORE active this week
        pct  = (L8W − LW)/L8W  a rate — positive means attrition (fewer active)

    ``pct`` is a FRACTION, not a percentage. The attrition-wow frontend
    multiplies by 100 in ``fmtSignedPctInverted``; every other consumer must do
    the same at its own boundary (see ``attrition_pct_100``).
    """
    return {
        "l8w": l8w,
        "lw": lw,
        "diff": lw - l8w,
        "pct": ((l8w - lw) / l8w) if l8w not in (0, 0.0) else None,
    }


def attrition_from_counts(
    l8w_lanes_sum, lw_lanes, l8w_customers_sum, lw_customers
) -> dict:
    """Build the ``active_lanes`` / ``active_customers`` blocks from raw counts.

    Floats on purpose: the cards render one decimal and Δ / %Δ derive from
    these, so rounding here would desync a card from the chart it is pinned to
    match (``tests/test_attrition_card_chart_parity.py``).
    """
    return {
        "active_lanes": _attr_block(
            float(lw_lanes or 0), _f(l8w_lanes_sum) / float(ATTRITION_WEEKS)
        ),
        "active_customers": _attr_block(
            float(lw_customers or 0), _f(l8w_customers_sum) / float(ATTRITION_WEEKS)
        ),
    }


def attrition_pct_100(block: dict) -> float:
    """A card block's ``pct`` as a 0-100 percentage, ``0.0`` when undefined.

    ⚠ Exists so the ×100 happens in exactly one place. The Ops Portal panel,
    its two modals and the digest e-mail all render with a formatter that
    expects 0-100; handing them the raw fraction prints "-0.06%" where
    "-6.09%" belongs, and nothing errors.
    """
    return _f(block.get("pct")) * 100.0
