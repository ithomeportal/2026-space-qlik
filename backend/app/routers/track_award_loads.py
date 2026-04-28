"""Code-made report: Track Award Loads.

Replaces Bruno's Qlik app `949cafc8-cd79-4058-a528-cd4b330d9298`
("Awards Tracker", legacy `unilink.us.qlikcloud.com` tenant — not
embeddable from the portal tenant `mb01txe2h9rovgh.us.qlikcloud.com`).

Source
------
``public.contract_performance_analysis`` in ``automations_db`` (Aiven).
The table is repopulated daily at 02:25 by n8n workflow
``Contract Performance Analysis`` (id ``3XkU4PfCm4EBYgTl``) which joins
``awards_tracker_registration_source`` ⨝ ``contract_mcleod_results_details``
and keeps a 15-day rolling window. We always read the **latest** snapshot
(``analysis_date = MAX``) — without that filter every aggregate is wrong by
a factor of ~15.

Filter to ``award_status IN ('Primary','PRIMARY')`` per Bruno's spec.

Endpoints
---------
- GET ``/filters``           — distinct values for the 4 filter pills
- GET ``/kpis``              — Lanes / Volume / Profit / Carrier Cost containers
- GET ``/by-division``       — Summary by Division
- GET ``/by-customer``       — Summary by Customer ID
- GET ``/by-customer-award`` — Summary by Customer Name + Award + Status
- GET ``/by-award-lane``     — Detail per Award + Lane (with ratios + days-to-exp)

Caching
-------
The data only changes once per day at 02:25 CST, so each endpoint wraps
its result in a 10-minute in-process TTL cache keyed by the filter
signature. Across the four-tab page that turns ~5 round-trips into 1.
"""

from __future__ import annotations

import time
from datetime import date
from typing import Any, Optional

from fastapi import APIRouter, Depends, Query, Request, Response

from app.routers.deps import get_automations_pool, require_tag_role

# Approved by Diego 2026-04-27 (PDF spec review).
ROLES = (
    "CEO",
    "Executive",
    "Sales",
    "Procurement",
    "Operations",
    "Finance",
    "CORP",
    "DFW",
)

router = APIRouter(
    tags=["track-award-loads"],
    prefix="/custom/track-award-loads",
)


# ---------------------------------------------------------------------------
# Filters parsing
# ---------------------------------------------------------------------------


def _parse_csv(value: Optional[str]) -> list[str]:
    if not value:
        return []
    return [v.strip() for v in value.split(",") if v.strip()]


def _scope_where(
    status: list[str],
    division: list[str],
    customer_id: list[str],
    award_name: list[str],
    params: list,
) -> str:
    """Append filter params and return the WHERE fragment.

    Operates on the ``cpa`` CTE alias defined in every endpoint.
    """
    parts: list[str] = []
    if status:
        params.append(status)
        parts.append(f"cpa.status = ANY(${len(params)})")
    if division:
        params.append(division)
        parts.append(f"cpa.division = ANY(${len(params)})")
    if customer_id:
        params.append(customer_id)
        parts.append(f"cpa.mcleod_customer_id = ANY(${len(params)})")
    if award_name:
        params.append(award_name)
        parts.append(f"cpa.award_name = ANY(${len(params)})")
    return " AND ".join(parts) if parts else "TRUE"


# Snapshot CTE: pin to the latest analysis_date, filter to PRIMARY only,
# and pre-compute Status + Days-to-Expiration so every endpoint is a thin
# selector over the same table-expression.
SNAPSHOT_CTE = """
WITH latest AS (
  SELECT MAX(analysis_date) AS d
  FROM contract_performance_analysis
  WHERE award_status IN ('Primary','PRIMARY')
),
cpa AS (
  SELECT
    c.*,
    CASE
      WHEN c.expiration_date IS NULL THEN 'Active'
      WHEN c.expiration_date::date >= CURRENT_DATE THEN 'Active'
      ELSE 'Expired'
    END AS status,
    CASE
      WHEN c.expiration_date IS NULL THEN NULL
      ELSE (c.expiration_date::date - CURRENT_DATE)
    END AS days_to_expiration,
    -- Lane key: trim each component, fix Bruno's PDF typo
    -- (origin_state appeared twice; should be dest_state).
    TRIM(c.origin_city_name) || ', ' || TRIM(c.origin_state)
      || ' - '
      || TRIM(c.dest_city_name) || ', ' || TRIM(c.dest_state) AS lane
  FROM contract_performance_analysis c
  CROSS JOIN latest l
  WHERE c.analysis_date = l.d
    AND c.award_status IN ('Primary','PRIMARY')
)
"""


# ---------------------------------------------------------------------------
# Tiny TTL cache (per worker, ~30 lines, no extra deps)
# ---------------------------------------------------------------------------

_CACHE_TTL = 600.0  # seconds — source updates once/day at 02:25 CST
_cache: dict[str, tuple[float, Any]] = {}


def _cache_get(key: str) -> Any:
    entry = _cache.get(key)
    if entry is None:
        return None
    expires, value = entry
    if expires < time.time():
        _cache.pop(key, None)
        return None
    return value


def _cache_set(key: str, value: Any) -> None:
    _cache[key] = (time.time() + _CACHE_TTL, value)


def _cache_key(*parts) -> str:
    return "|".join(str(p) for p in parts)


# ---------------------------------------------------------------------------
# /filters
# ---------------------------------------------------------------------------


@router.get("/filters")
async def filters(
    request: Request,
    response: Response,
    _user: dict = Depends(require_tag_role(*ROLES)),
):
    """Distinct values for the 4 filter pills (single round-trip)."""
    cached = _cache_get("filters")
    if cached is not None:
        response.headers["Cache-Control"] = "private, max-age=600"
        return cached

    pool = get_automations_pool(request)
    rows = await pool.fetch(
        f"""
        {SNAPSHOT_CTE}
        SELECT
          ARRAY(SELECT DISTINCT status         FROM cpa WHERE status IS NOT NULL ORDER BY 1)            AS statuses,
          ARRAY(SELECT DISTINCT division       FROM cpa WHERE division IS NOT NULL AND division <> '' ORDER BY 1) AS divisions,
          ARRAY(SELECT DISTINCT mcleod_customer_id FROM cpa
                                               WHERE mcleod_customer_id IS NOT NULL AND mcleod_customer_id <> ''
                                               ORDER BY 1)                                                 AS customer_ids,
          ARRAY(SELECT DISTINCT award_name     FROM cpa WHERE award_name IS NOT NULL AND award_name <> '' ORDER BY 1) AS award_names,
          (SELECT MAX(analysis_date) FROM cpa) AS as_of
        """,
    )
    r = rows[0] if rows else None
    payload = {
        "success": True,
        "data": {
            "statuses": list(r["statuses"]) if r else [],
            "divisions": list(r["divisions"]) if r else [],
            "customer_ids": list(r["customer_ids"]) if r else [],
            "award_names": list(r["award_names"]) if r else [],
            "as_of": r["as_of"].isoformat() if r and r["as_of"] else None,
        },
    }
    _cache_set("filters", payload)
    response.headers["Cache-Control"] = "private, max-age=600"
    return payload


# ---------------------------------------------------------------------------
# /kpis — 4 containers in one trip
# ---------------------------------------------------------------------------


@router.get("/kpis")
async def kpis(
    request: Request,
    response: Response,
    status: Optional[str] = Query(None),
    division: Optional[str] = Query(None),
    customer_id: Optional[str] = Query(None),
    award_name: Optional[str] = Query(None),
    _user: dict = Depends(require_tag_role(*ROLES)),
):
    """Compact KPI payload covering all four containers (Lanes / Volume / Profit / Carrier Cost)."""
    s_list = _parse_csv(status)
    d_list = _parse_csv(division)
    c_list = _parse_csv(customer_id)
    a_list = _parse_csv(award_name)

    key = _cache_key("kpis", *s_list, "|", *d_list, "|", *c_list, "|", *a_list)
    cached = _cache_get(key)
    if cached is not None:
        response.headers["Cache-Control"] = "private, max-age=600"
        return cached

    pool = get_automations_pool(request)
    params: list = []
    where = _scope_where(s_list, d_list, c_list, a_list, params)

    sql = f"""
    {SNAPSHOT_CTE}
    SELECT
      COUNT(DISTINCT lane)                                               AS unique_lanes_awarded,
      COUNT(*) FILTER (WHERE COALESCE(total_revenue, 0) <> 0)            AS unique_actual_lanes,
      COALESCE(SUM(volume_all_term_award), 0)::numeric                   AS awarded_volume,
      COALESCE(SUM(total_loads), 0)::bigint                              AS total_actual_volume,
      COALESCE(SUM(projected_profit), 0)::numeric                        AS projected_profit,
      COALESCE(SUM(total_profit), 0)::numeric                            AS actual_profit,
      COALESCE(SUM(projected_carrier_cost), 0)::numeric                  AS projected_carrier_cost,
      COALESCE(SUM(total_carrier_cost), 0)::numeric                      AS actual_carrier_cost
    FROM cpa
    WHERE {where}
    """
    row = await pool.fetchrow(sql, *params)

    unique_lanes_awarded = int(row["unique_lanes_awarded"] or 0)
    unique_actual_lanes = int(row["unique_actual_lanes"] or 0)
    awarded_volume = float(row["awarded_volume"] or 0)
    total_actual_volume = int(row["total_actual_volume"] or 0)
    projected_profit = float(row["projected_profit"] or 0)
    actual_profit = float(row["actual_profit"] or 0)
    projected_carrier_cost = float(row["projected_carrier_cost"] or 0)
    actual_carrier_cost = float(row["actual_carrier_cost"] or 0)

    def _ratio(num: float, den: float) -> Optional[float]:
        return (num / den) if den else None

    payload = {
        "success": True,
        "data": {
            "lanes": {
                "unique_lanes_awarded": unique_lanes_awarded,
                "unique_actual_lanes": unique_actual_lanes,
                "lane_variance": unique_actual_lanes - unique_lanes_awarded,
                "ratio": _ratio(unique_actual_lanes, unique_lanes_awarded),
            },
            "volume": {
                "awarded_volume": awarded_volume,
                "total_actual_volume": total_actual_volume,
                "load_variance": total_actual_volume - awarded_volume,
                "ratio": _ratio(total_actual_volume, awarded_volume),
            },
            "profit": {
                "projected_profit": projected_profit,
                "actual_profit": actual_profit,
                "profit_variance": actual_profit - projected_profit,
                "ratio": _ratio(actual_profit, projected_profit),
            },
            "carrier_cost": {
                "projected_carrier_cost": projected_carrier_cost,
                "actual_carrier_cost": actual_carrier_cost,
                "variance": actual_carrier_cost - projected_carrier_cost,
                "ratio": _ratio(actual_carrier_cost, projected_carrier_cost),
            },
        },
    }
    _cache_set(key, payload)
    response.headers["Cache-Control"] = "private, max-age=600"
    return payload


# ---------------------------------------------------------------------------
# Aggregate fragment shared by every detail endpoint
# ---------------------------------------------------------------------------

_AGG_COLUMNS = """
COUNT(DISTINCT lane)                                       AS unique_lanes_awarded,
COALESCE(SUM(volume_all_term_award), 0)::numeric           AS awarded_volume,
COALESCE(SUM(total_loads), 0)::bigint                      AS total_actual_volume,
(COALESCE(SUM(total_loads), 0) - COALESCE(SUM(volume_all_term_award), 0))::numeric
                                                           AS load_variance,
COALESCE(SUM(projected_profit), 0)::numeric                AS projected_profit,
COALESCE(SUM(total_profit), 0)::numeric                    AS actual_profit,
(COALESCE(SUM(total_profit), 0) - COALESCE(SUM(projected_profit), 0))::numeric
                                                           AS profit_variance,
COALESCE(SUM(projected_carrier_cost), 0)::numeric          AS projected_carrier_cost,
COALESCE(SUM(total_carrier_cost), 0)::numeric              AS actual_carrier_cost,
(COALESCE(SUM(total_carrier_cost), 0) - COALESCE(SUM(projected_carrier_cost), 0))::numeric
                                                           AS carrier_cost_variance
"""


def _agg_row_to_dict(r) -> dict:
    return {
        "unique_lanes_awarded": int(r["unique_lanes_awarded"] or 0),
        "awarded_volume": float(r["awarded_volume"] or 0),
        "total_actual_volume": int(r["total_actual_volume"] or 0),
        "load_variance": float(r["load_variance"] or 0),
        "projected_profit": float(r["projected_profit"] or 0),
        "actual_profit": float(r["actual_profit"] or 0),
        "profit_variance": float(r["profit_variance"] or 0),
        "projected_carrier_cost": float(r["projected_carrier_cost"] or 0),
        "actual_carrier_cost": float(r["actual_carrier_cost"] or 0),
        "carrier_cost_variance": float(r["carrier_cost_variance"] or 0),
    }


# ---------------------------------------------------------------------------
# /by-division
# ---------------------------------------------------------------------------


@router.get("/by-division")
async def by_division(
    request: Request,
    response: Response,
    status: Optional[str] = Query(None),
    division: Optional[str] = Query(None),
    customer_id: Optional[str] = Query(None),
    award_name: Optional[str] = Query(None),
    _user: dict = Depends(require_tag_role(*ROLES)),
):
    s_list = _parse_csv(status)
    d_list = _parse_csv(division)
    c_list = _parse_csv(customer_id)
    a_list = _parse_csv(award_name)

    key = _cache_key("by-division", *s_list, "|", *d_list, "|", *c_list, "|", *a_list)
    cached = _cache_get(key)
    if cached is not None:
        response.headers["Cache-Control"] = "private, max-age=600"
        return cached

    pool = get_automations_pool(request)
    params: list = []
    where = _scope_where(s_list, d_list, c_list, a_list, params)

    rows = await pool.fetch(
        f"""
        {SNAPSHOT_CTE}
        SELECT
          COALESCE(NULLIF(division, ''), '—') AS division,
          {_AGG_COLUMNS}
        FROM cpa
        WHERE {where}
        GROUP BY 1
        ORDER BY 1
        """,
        *params,
    )

    payload = {
        "success": True,
        "data": {
            "rows": [{"division": r["division"], **_agg_row_to_dict(r)} for r in rows],
        },
    }
    _cache_set(key, payload)
    response.headers["Cache-Control"] = "private, max-age=600"
    return payload


# ---------------------------------------------------------------------------
# /by-customer
# ---------------------------------------------------------------------------


@router.get("/by-customer")
async def by_customer(
    request: Request,
    response: Response,
    status: Optional[str] = Query(None),
    division: Optional[str] = Query(None),
    customer_id: Optional[str] = Query(None),
    award_name: Optional[str] = Query(None),
    _user: dict = Depends(require_tag_role(*ROLES)),
):
    s_list = _parse_csv(status)
    d_list = _parse_csv(division)
    c_list = _parse_csv(customer_id)
    a_list = _parse_csv(award_name)

    key = _cache_key("by-customer", *s_list, "|", *d_list, "|", *c_list, "|", *a_list)
    cached = _cache_get(key)
    if cached is not None:
        response.headers["Cache-Control"] = "private, max-age=600"
        return cached

    pool = get_automations_pool(request)
    params: list = []
    where = _scope_where(s_list, d_list, c_list, a_list, params)

    rows = await pool.fetch(
        f"""
        {SNAPSHOT_CTE}
        SELECT
          COALESCE(NULLIF(mcleod_customer_id, ''), '—') AS customer_id,
          {_AGG_COLUMNS}
        FROM cpa
        WHERE {where}
        GROUP BY 1
        ORDER BY 1
        """,
        *params,
    )

    payload = {
        "success": True,
        "data": {
            "rows": [
                {"customer_id": r["customer_id"], **_agg_row_to_dict(r)} for r in rows
            ],
        },
    }
    _cache_set(key, payload)
    response.headers["Cache-Control"] = "private, max-age=600"
    return payload


# ---------------------------------------------------------------------------
# /by-customer-award
# ---------------------------------------------------------------------------


@router.get("/by-customer-award")
async def by_customer_award(
    request: Request,
    response: Response,
    status: Optional[str] = Query(None),
    division: Optional[str] = Query(None),
    customer_id: Optional[str] = Query(None),
    award_name: Optional[str] = Query(None),
    _user: dict = Depends(require_tag_role(*ROLES)),
):
    s_list = _parse_csv(status)
    d_list = _parse_csv(division)
    c_list = _parse_csv(customer_id)
    a_list = _parse_csv(award_name)

    key = _cache_key(
        "by-customer-award", *s_list, "|", *d_list, "|", *c_list, "|", *a_list
    )
    cached = _cache_get(key)
    if cached is not None:
        response.headers["Cache-Control"] = "private, max-age=600"
        return cached

    pool = get_automations_pool(request)
    params: list = []
    where = _scope_where(s_list, d_list, c_list, a_list, params)

    rows = await pool.fetch(
        f"""
        {SNAPSHOT_CTE}
        SELECT
          COALESCE(NULLIF(mcleod_customer_name, ''), '—') AS customer_name,
          COALESCE(NULLIF(award_name, ''), '—')           AS award_name,
          COALESCE(NULLIF(division, ''), '—')             AS division,
          MIN(status)                                     AS status,
          {_AGG_COLUMNS}
        FROM cpa
        WHERE {where}
        GROUP BY 1, 2, 3
        ORDER BY 1, 2
        """,
        *params,
    )

    payload = {
        "success": True,
        "data": {
            "rows": [
                {
                    "customer_name": r["customer_name"],
                    "award_name": r["award_name"],
                    "division": r["division"],
                    "status": r["status"],
                    **_agg_row_to_dict(r),
                }
                for r in rows
            ],
        },
    }
    _cache_set(key, payload)
    response.headers["Cache-Control"] = "private, max-age=600"
    return payload


# ---------------------------------------------------------------------------
# /by-award-lane — deepest table, includes ratios + days-to-exp
# ---------------------------------------------------------------------------


@router.get("/by-award-lane")
async def by_award_lane(
    request: Request,
    response: Response,
    status: Optional[str] = Query(None),
    division: Optional[str] = Query(None),
    customer_id: Optional[str] = Query(None),
    award_name: Optional[str] = Query(None),
    sort: str = Query("days_asc"),
    _user: dict = Depends(require_tag_role(*ROLES)),
):
    s_list = _parse_csv(status)
    d_list = _parse_csv(division)
    c_list = _parse_csv(customer_id)
    a_list = _parse_csv(award_name)

    key = _cache_key(
        "by-award-lane", sort, *s_list, "|", *d_list, "|", *c_list, "|", *a_list
    )
    cached = _cache_get(key)
    if cached is not None:
        response.headers["Cache-Control"] = "private, max-age=600"
        return cached

    pool = get_automations_pool(request)
    params: list = []
    where = _scope_where(s_list, d_list, c_list, a_list, params)

    order_by = {
        "days_asc":           "days_to_expiration ASC NULLS LAST",
        "days_desc":          "days_to_expiration DESC NULLS LAST",
        "loads_desc":         "total_actual_volume DESC",
        "loads_asc":          "total_actual_volume ASC",
        "load_variance_desc": "load_variance DESC",
        "load_variance_asc":  "load_variance ASC",
        "profit_desc":        "actual_profit DESC",
        "profit_asc":         "actual_profit ASC",
        "profit_variance_desc": "profit_variance DESC",
        "profit_variance_asc":  "profit_variance ASC",
        "carrier_desc":       "actual_carrier_cost DESC",
        "carrier_asc":        "actual_carrier_cost ASC",
        "award_asc":          "award_name ASC, lane ASC",
    }.get(sort, "days_to_expiration ASC NULLS LAST")

    # Bruno's PDF column "Award ID" maps to the bigint PK `audit_id`. NOTE:
    # destination `audit_id` is a SERIAL (`nextval(..._audit_id_seq)`), so a
    # new audit_id is minted on every n8n run. To match the same logical
    # award lane across daily snapshots we therefore join on the natural
    # business key, not on audit_id.
    #
    # WoW delta: pick the snapshot closest to (latest − 7d) within the
    # 15-day rolling window. Lane key reuses the same TRIM-concat the
    # snapshot CTE builds. Until 8 days of history accumulate, prev_*
    # values come back NULL and the frontend renders em-dashes.
    rows = await pool.fetch(
        f"""
        {SNAPSHOT_CTE}
        ,
        prior AS (
          SELECT MAX(analysis_date) AS d
          FROM contract_performance_analysis
          WHERE award_status IN ('Primary','PRIMARY')
            AND analysis_date <= (SELECT d FROM latest) - INTERVAL '7 days'
        ),
        cpa_prior AS (
          -- Distinct column names so the LEFT JOIN below doesn't collide
          -- with `cpa.lane` / `cpa.equipment` / `cpa.award_name` (which the
          -- shared _AGG_COLUMNS macro references unqualified).
          SELECT
            COALESCE(c.award_name, '')          AS pa_award_name,
            COALESCE(c.mcleod_customer_id, '')  AS pa_customer_id,
            TRIM(c.origin_city_name) || ', ' || TRIM(c.origin_state)
              || ' - ' ||
              TRIM(c.dest_city_name) || ', ' || TRIM(c.dest_state)  AS pa_lane,
            COALESCE(c.equipment, '')           AS pa_equipment,
            SUM(c.total_loads)                  AS prev_total_loads,
            MAX(c.analysis_date)                AS prev_snapshot
          FROM contract_performance_analysis c, prior p
          WHERE p.d IS NOT NULL
            AND c.analysis_date = p.d
            AND c.award_status IN ('Primary','PRIMARY')
          GROUP BY 1, 2, 3, 4
        ),
        -- Per-lane rate metadata pulled from the upstream registrations table.
        -- Same prefix-aliasing trick (`at_*`) so unqualified _AGG_COLUMNS refs
        -- continue to resolve to `cpa`. MAX() collapses the ~8 known cases
        -- where the same lane shows up twice with slightly different rates.
        ats_rates AS (
          SELECT
            COALESCE(ats.award_name, '')          AS at_award_name,
            COALESCE(ats.mcleod_customer_id, '')  AS at_customer_id,
            TRIM(ats.origin_city_name) || ', ' || TRIM(ats.origin_state)
              || ' - ' ||
              TRIM(ats.dest_city_name) || ', ' || TRIM(ats.dest_state) AS at_lane,
            COALESCE(ats.equipment, '')           AS at_equipment,
            MAX(ats.rpm_value_usd)                AS rpm,
            MAX(ats.min_charge_value)             AS min_charge,
            MAX(ats.all_in_rates_value)           AS all_in_rates
          FROM awards_tracker_registration_source ats
          WHERE UPPER(ats.award_status) = 'PRIMARY'
          GROUP BY 1, 2, 3, 4
        )
        SELECT
          cpa.audit_id,
          NULLIF(TRIM(cpa.award_id_name), '')                 AS award_id_name,
          COALESCE(NULLIF(cpa.award_name, ''), '—')           AS award_name,
          COALESCE(NULLIF(cpa.mcleod_customer_name, ''), '—') AS customer_name,
          cpa.lane,
          cpa.equipment                                       AS equip,
          cpa.effective_date,
          cpa.expiration_date,
          cpa.days_to_expiration,
          cp.prev_total_loads,
          cp.prev_snapshot,
          ar.rpm,
          ar.min_charge,
          ar.all_in_rates,
          {_AGG_COLUMNS}
        FROM cpa
        LEFT JOIN cpa_prior cp
               ON cp.pa_award_name  = COALESCE(cpa.award_name, '')
              AND cp.pa_customer_id = COALESCE(cpa.mcleod_customer_id, '')
              AND cp.pa_lane        = cpa.lane
              AND cp.pa_equipment   = COALESCE(cpa.equipment, '')
        LEFT JOIN ats_rates ar
               ON ar.at_award_name  = COALESCE(cpa.award_name, '')
              AND ar.at_customer_id = COALESCE(cpa.mcleod_customer_id, '')
              AND ar.at_lane        = cpa.lane
              AND ar.at_equipment   = COALESCE(cpa.equipment, '')
        WHERE {where}
        GROUP BY cpa.audit_id, cpa.award_id_name, cpa.award_name,
                 cpa.mcleod_customer_name, cpa.lane, cpa.equipment,
                 cpa.effective_date, cpa.expiration_date,
                 cpa.days_to_expiration, cp.prev_total_loads, cp.prev_snapshot,
                 ar.rpm, ar.min_charge, ar.all_in_rates
        ORDER BY {order_by}
        """,
        *params,
    )

    out = []
    for r in rows:
        agg = _agg_row_to_dict(r)
        # Per-row ratios (PDF: % Loads / % Profit / % Carrier Cost)
        load_ratio = (
            agg["total_actual_volume"] / agg["awarded_volume"]
            if agg["awarded_volume"]
            else None
        )
        profit_ratio = (
            agg["actual_profit"] / agg["projected_profit"]
            if agg["projected_profit"]
            else None
        )
        carrier_ratio = (
            agg["actual_carrier_cost"] / agg["projected_carrier_cost"]
            if agg["projected_carrier_cost"]
            else None
        )
        # WoW delta: total_actual_volume is summed across the row's GROUP BY
        # so it equals cpa.total_loads here. The prior snapshot's total_loads
        # is per-audit_id (no aggregation) since LEFT JOIN happens after the
        # GROUP BY, but cpa is grouped by audit_id so the join is 1:1 and
        # MAX() in the SQL is unneeded.
        prev_loads = (
            int(r["prev_total_loads"]) if r["prev_total_loads"] is not None else None
        )
        wow_delta = (
            agg["total_actual_volume"] - prev_loads
            if prev_loads is not None
            else None
        )
        out.append(
            {
                "audit_id": int(r["audit_id"]) if r["audit_id"] is not None else None,
                "award_id_name": r["award_id_name"],
                "award_name": r["award_name"],
                "customer_name": r["customer_name"],
                "lane": r["lane"],
                "equip": r["equip"],
                "effective_date": r["effective_date"].isoformat()
                if r["effective_date"]
                else None,
                "expiration_date": r["expiration_date"].isoformat()
                if r["expiration_date"]
                else None,
                "days_to_expiration": int(r["days_to_expiration"])
                if r["days_to_expiration"] is not None
                else None,
                **agg,
                "load_ratio": load_ratio,
                "profit_ratio": profit_ratio,
                "carrier_cost_ratio": carrier_ratio,
                "prev_total_loads": prev_loads,
                "prev_snapshot": r["prev_snapshot"].isoformat()
                if r["prev_snapshot"] is not None
                else None,
                "wow_delta_loads": wow_delta,
                # Per-lane rates from the upstream awards_tracker_registration_source
                "rpm": float(r["rpm"]) if r["rpm"] is not None else None,
                "min_charge": float(r["min_charge"]) if r["min_charge"] is not None else None,
                "all_in_rates": float(r["all_in_rates"]) if r["all_in_rates"] is not None else None,
            }
        )

    payload = {
        "success": True,
        "data": {"rows": out},
        "meta": {"total": len(out)},
    }
    _cache_set(key, payload)
    response.headers["Cache-Control"] = "private, max-age=600"
    return payload


# ---------------------------------------------------------------------------
# Diagnostics — confirm freshness without running a full report
# ---------------------------------------------------------------------------


@router.get("/freshness")
async def freshness(
    request: Request,
    _user: dict = Depends(require_tag_role(*ROLES)),
):
    """Returns the latest snapshot date and count of primary-award rows."""
    pool = get_automations_pool(request)
    row = await pool.fetchrow(
        """
        SELECT MAX(analysis_date) AS as_of,
               COUNT(*) AS rows_total
        FROM contract_performance_analysis
        WHERE award_status IN ('Primary','PRIMARY')
          AND analysis_date = (
            SELECT MAX(analysis_date)
            FROM contract_performance_analysis
            WHERE award_status IN ('Primary','PRIMARY')
          )
        """
    )
    today = date.today().isoformat()
    return {
        "success": True,
        "data": {
            "as_of": row["as_of"].isoformat() if row and row["as_of"] else None,
            "rows": int(row["rows_total"] or 0) if row else 0,
            "checked_at": today,
        },
    }
