"""Code-made report: Carrier SMS Score.

A flat, sortable/searchable roster of every carrier in the AP_module's own
database (``unilink_portal_ap``) joined to its FMCSA Safety Performance (SMS)
profile and final MyCarrierPortal (MCP) risk verdict. This is the same data the
AP app shows one carrier at a time at
``/dashboard/admin/carriers/<id>/view`` — surfaced here as one table so
Procurement can spot carriers that exceed the **national average** Vehicle /
Driver Out-of-Service rates or carry concerning **BASIC** measures, and confirm
the dataset is fresh.

Source tables (both in ``unilink_portal_ap``, read via the dedicated AP pool):
  * ``carriers``         — name, city, state, dot_number, mc_number, is_active,
                           mcp_risk_overall, mcp_risk_points, mcp_is_blocked,
                           mcp_last_checked
  * ``fmcsa_sms_data``   — *_insp_total / *_oos_insp_total + the 5 BASIC
                           measures, joined on ``dot_number`` (LEFT JOIN — a
                           carrier with no DOT or no SMS row still appears, with
                           NULL safety metrics)

National OOS averages (FMCSA published, matching the app's
``safety-performance-card.tsx``): Vehicle 23.2%, Driver 6.4%. BASIC measures
are 0–100 weighted scores where higher = more concern (amber ≥ 50, red ≥ 75).

This is the **first portal report to read ``unilink_portal_ap``** — it needs the
``ap_pool`` (``AP_DATABASE_URL``), the 5th external asyncpg pool.
"""

from __future__ import annotations

import csv
import io
import math
from typing import Any, Optional

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import Response

from app.clock import cst_today
from app.routers.deps import get_ap_pool, require_report_access

router = APIRouter(tags=["carrier-sms"], prefix="/custom/carrier-sms")

# FMCSA published national Out-of-Service averages (24-month measurement
# window) — identical to the AP app's Safety Performance card.
NAT_AVG_VEHICLE = 23.2
NAT_AVG_DRIVER = 6.4
# A BASIC measure at/above this percentile is treated as "concerning".
BASIC_CONCERN = 75.0


def _num(value: Any) -> Optional[float]:
    """Coerce a Postgres NUMERIC/INT to float, mapping NaN/±Inf/None to None.

    SMS measures and the computed OOS percentages can be NULL (no inspections)
    or, defensively, NaN/Inf from a bad upstream row — both would crash the JSON
    encoder. Keep NULL semantics (None) rather than collapsing to 0 so the UI
    can render an honest "N/A".
    """
    if value is None:
        return None
    try:
        f = float(value)
    except (TypeError, ValueError):
        return None
    if math.isnan(f) or math.isinf(f):
        return None
    return f


# ---------------------------------------------------------------------------
# Shared SQL — the join + computed columns every endpoint selects from.
# ---------------------------------------------------------------------------

# Computed OOS-rate expressions (percent). NULLIF guards a 0 inspection total.
_VEHICLE_OOS = (
    "s.vehicle_oos_insp_total::numeric / NULLIF(s.vehicle_insp_total, 0) * 100"
)
_DRIVER_OOS = (
    "s.driver_oos_insp_total::numeric / NULLIF(s.driver_insp_total, 0) * 100"
)

# The 5 BASIC measures, cast to numeric and aliased to wire names.
_BASICS = {
    "unsafe": "s.unsafe_driv_measure::numeric",
    "hos": "s.hos_driv_measure::numeric",
    "fitness": "s.driv_fit_measure::numeric",
    "drugalc": "s.contr_subst_measure::numeric",
    "vehmaint": "s.veh_maint_measure::numeric",
}

_SELECT_COLUMNS = f"""
    c.id::text                          AS id,
    c.name                              AS name,
    c.city                              AS city,
    c.state                             AS state,
    c.dot_number                        AS dot_number,
    c.mc_number                         AS mc_number,
    c.is_active                         AS is_active,
    {_VEHICLE_OOS}                      AS vehicle_oos_pct,
    {_DRIVER_OOS}                       AS driver_oos_pct,
    s.vehicle_insp_total                AS vehicle_insp_total,
    s.driver_insp_total                 AS driver_insp_total,
    {_BASICS['unsafe']}                 AS basic_unsafe,
    {_BASICS['hos']}                    AS basic_hos,
    {_BASICS['fitness']}                AS basic_fitness,
    {_BASICS['drugalc']}                AS basic_drugalc,
    {_BASICS['vehmaint']}               AS basic_vehmaint,
    s.unsafe_driv_ac                    AS unsafe_ac,
    s.hos_compliance_ac                 AS hos_ac,
    s.driv_fit_ac                       AS fitness_ac,
    s.contr_subst_sv                    AS drugalc_sv,
    s.veh_maint_ac                      AS vehmaint_ac,
    c.mcp_risk_overall                  AS mcp_risk_overall,
    c.mcp_risk_points                   AS mcp_risk_points,
    c.mcp_is_blocked                    AS mcp_is_blocked,
    c.mcp_last_checked                  AS mcp_last_checked,
    s.data_file_date                    AS data_file_date
"""

_FROM = (
    "FROM carriers c "
    "LEFT JOIN fmcsa_sms_data s ON c.dot_number = s.dot_number"
)


def _build_where(
    search: Optional[str],
    include_inactive: bool,
    flagged: bool,
    params: list,
) -> str:
    """Assemble the WHERE clause, appending bind params in order."""
    parts: list[str] = []

    if not include_inactive:
        parts.append("c.is_active = TRUE")

    if search and search.strip():
        params.append(f"%{search.strip()}%")
        p = len(params)
        parts.append(
            f"(c.name ILIKE ${p} OR c.dot_number ILIKE ${p} "
            f"OR c.mc_number ILIKE ${p} OR c.city ILIKE ${p} "
            f"OR c.state ILIKE ${p})"
        )

    if flagged:
        # Above either national OOS average, or any BASIC at/above the concern
        # threshold. GREATEST ignores NULLs only if at least one is non-null;
        # COALESCE each to 0 so an all-NULL carrier is simply not flagged.
        basics = ", ".join(
            f"COALESCE({expr}, 0)" for expr in _BASICS.values()
        )
        parts.append(
            f"(COALESCE({_VEHICLE_OOS}, 0) > {NAT_AVG_VEHICLE} "
            f"OR COALESCE({_DRIVER_OOS}, 0) > {NAT_AVG_DRIVER} "
            f"OR GREATEST({basics}) >= {BASIC_CONCERN})"
        )

    return (" WHERE " + " AND ".join(parts)) if parts else ""


# Whitelist of sortable columns → safe ORDER BY fragments. The computed OOS /
# BASIC columns sort on their SQL expressions; everything NULLS LAST so carriers
# missing safety data sink to the bottom regardless of direction.
_SORTS = {
    "name_asc": "c.name ASC",
    "name_desc": "c.name DESC",
    "state_asc": "c.state ASC NULLS LAST, c.city ASC NULLS LAST",
    "state_desc": "c.state DESC NULLS LAST, c.city DESC NULLS LAST",
    "vehicle_oos_asc": f"({_VEHICLE_OOS}) ASC NULLS LAST",
    "vehicle_oos_desc": f"({_VEHICLE_OOS}) DESC NULLS LAST",
    "driver_oos_asc": f"({_DRIVER_OOS}) ASC NULLS LAST",
    "driver_oos_desc": f"({_DRIVER_OOS}) DESC NULLS LAST",
    "basic_unsafe_asc": f"({_BASICS['unsafe']}) ASC NULLS LAST",
    "basic_unsafe_desc": f"({_BASICS['unsafe']}) DESC NULLS LAST",
    "basic_hos_asc": f"({_BASICS['hos']}) ASC NULLS LAST",
    "basic_hos_desc": f"({_BASICS['hos']}) DESC NULLS LAST",
    "basic_fitness_asc": f"({_BASICS['fitness']}) ASC NULLS LAST",
    "basic_fitness_desc": f"({_BASICS['fitness']}) DESC NULLS LAST",
    "basic_drugalc_asc": f"({_BASICS['drugalc']}) ASC NULLS LAST",
    "basic_drugalc_desc": f"({_BASICS['drugalc']}) DESC NULLS LAST",
    "basic_vehmaint_asc": f"({_BASICS['vehmaint']}) ASC NULLS LAST",
    "basic_vehmaint_desc": f"({_BASICS['vehmaint']}) DESC NULLS LAST",
    "mcp_points_asc": "c.mcp_risk_points ASC NULLS LAST",
    "mcp_points_desc": "c.mcp_risk_points DESC NULLS LAST",
    "mcp_risk_asc": "c.mcp_risk_overall ASC NULLS LAST",
    "mcp_risk_desc": "c.mcp_risk_overall DESC NULLS LAST",
    "data_date_asc": "s.data_file_date ASC NULLS LAST",
    "data_date_desc": "s.data_file_date DESC NULLS LAST",
}
_DEFAULT_SORT = "name_asc"


def _row_to_dict(r) -> dict:
    return {
        "id": r["id"],
        "name": r["name"],
        "city": r["city"],
        "state": r["state"],
        "dot_number": r["dot_number"],
        "mc_number": r["mc_number"],
        "is_active": r["is_active"],
        "vehicle_oos_pct": _num(r["vehicle_oos_pct"]),
        "driver_oos_pct": _num(r["driver_oos_pct"]),
        "vehicle_insp_total": int(r["vehicle_insp_total"]) if r["vehicle_insp_total"] is not None else None,
        "driver_insp_total": int(r["driver_insp_total"]) if r["driver_insp_total"] is not None else None,
        "basic_unsafe": _num(r["basic_unsafe"]),
        "basic_hos": _num(r["basic_hos"]),
        "basic_fitness": _num(r["basic_fitness"]),
        "basic_drugalc": _num(r["basic_drugalc"]),
        "basic_vehmaint": _num(r["basic_vehmaint"]),
        "unsafe_ac": r["unsafe_ac"],
        "hos_ac": r["hos_ac"],
        "fitness_ac": r["fitness_ac"],
        "drugalc_sv": r["drugalc_sv"],
        "vehmaint_ac": r["vehmaint_ac"],
        "mcp_risk_overall": r["mcp_risk_overall"],
        "mcp_risk_points": int(r["mcp_risk_points"]) if r["mcp_risk_points"] is not None else None,
        "mcp_is_blocked": r["mcp_is_blocked"],
        "mcp_last_checked": r["mcp_last_checked"].isoformat() if r["mcp_last_checked"] else None,
        "data_file_date": r["data_file_date"].isoformat() if r["data_file_date"] else None,
        "nat_avg_vehicle": NAT_AVG_VEHICLE,
        "nat_avg_driver": NAT_AVG_DRIVER,
    }


# ---------------------------------------------------------------------------
# Summary — KPI strip + dataset freshness
# ---------------------------------------------------------------------------


@router.get("/summary")
async def summary(
    request: Request,
    search: Optional[str] = Query(None),
    include_inactive: bool = Query(False),
    flagged: bool = Query(False),
    _user: dict = Depends(require_report_access("carrier-sms-score")),
):
    pool = get_ap_pool(request)
    params: list = []
    where = _build_where(search, include_inactive, flagged, params)

    sql = f"""
    SELECT
      COUNT(*)                                                       AS total,
      COUNT(*) FILTER (WHERE {_VEHICLE_OOS} > {NAT_AVG_VEHICLE})     AS above_vehicle,
      COUNT(*) FILTER (WHERE {_DRIVER_OOS} > {NAT_AVG_DRIVER})       AS above_driver,
      COUNT(*) FILTER (WHERE GREATEST(
          COALESCE({_BASICS['unsafe']}, 0),
          COALESCE({_BASICS['hos']}, 0),
          COALESCE({_BASICS['fitness']}, 0),
          COALESCE({_BASICS['drugalc']}, 0),
          COALESCE({_BASICS['vehmaint']}, 0)
      ) >= {BASIC_CONCERN})                                         AS concerning_basics,
      COUNT(*) FILTER (
          WHERE c.mcp_is_blocked = TRUE
             OR (c.mcp_risk_overall IS NOT NULL
                 AND lower(c.mcp_risk_overall) <> 'acceptable')
      )                                                             AS mcp_not_acceptable,
      MAX(s.data_file_date)                                          AS sms_newest,
      MIN(s.data_file_date)                                          AS sms_oldest,
      MAX(c.mcp_last_checked)                                        AS mcp_newest,
      MIN(c.mcp_last_checked)                                        AS mcp_oldest,
      COUNT(*) FILTER (WHERE s.dot_number IS NULL)                   AS missing_sms
    {_FROM}
    {where}
    """
    row = await pool.fetchrow(sql, *params)

    return {
        "success": True,
        "data": {
            "total": int(row["total"] or 0),
            "above_vehicle_nat_avg": int(row["above_vehicle"] or 0),
            "above_driver_nat_avg": int(row["above_driver"] or 0),
            "concerning_basics": int(row["concerning_basics"] or 0),
            "mcp_not_acceptable": int(row["mcp_not_acceptable"] or 0),
            "missing_sms": int(row["missing_sms"] or 0),
            "sms_data_newest": row["sms_newest"].isoformat() if row["sms_newest"] else None,
            "sms_data_oldest": row["sms_oldest"].isoformat() if row["sms_oldest"] else None,
            "mcp_checked_newest": row["mcp_newest"].isoformat() if row["mcp_newest"] else None,
            "mcp_checked_oldest": row["mcp_oldest"].isoformat() if row["mcp_oldest"] else None,
            "nat_avg_vehicle": NAT_AVG_VEHICLE,
            "nat_avg_driver": NAT_AVG_DRIVER,
            "basic_concern": BASIC_CONCERN,
        },
    }


# ---------------------------------------------------------------------------
# Carriers — paginated, sortable, searchable table
# ---------------------------------------------------------------------------


@router.get("/carriers")
async def carriers(
    request: Request,
    search: Optional[str] = Query(None),
    include_inactive: bool = Query(False),
    flagged: bool = Query(False),
    sort: str = Query(_DEFAULT_SORT),
    page: int = Query(1, ge=1),
    limit: int = Query(50, ge=1, le=500),
    _user: dict = Depends(require_report_access("carrier-sms-score")),
):
    pool = get_ap_pool(request)
    order_by = _SORTS.get(sort, _SORTS[_DEFAULT_SORT])
    offset = (page - 1) * limit

    params: list = []
    where = _build_where(search, include_inactive, flagged, params)
    params.extend([limit, offset])
    p_lim, p_off = len(params) - 1, len(params)

    sql = f"""
    SELECT {_SELECT_COLUMNS},
           COUNT(*) OVER() AS total_count
    {_FROM}
    {where}
    ORDER BY {order_by}, c.name ASC
    LIMIT ${p_lim} OFFSET ${p_off}
    """
    rows = await pool.fetch(sql, *params)
    total = int(rows[0]["total_count"]) if rows else 0

    return {
        "success": True,
        "data": [_row_to_dict(r) for r in rows],
        "meta": {"total": total, "page": page, "limit": limit},
    }


# ---------------------------------------------------------------------------
# CSV — streams every matching row (no pagination)
# ---------------------------------------------------------------------------

_CSV_HEADER = [
    "Carrier", "City", "State", "DOT #", "MC #", "Active",
    "Vehicle OOS %", "Driver OOS %",
    "BASIC Unsafe", "BASIC HOS", "BASIC Fitness", "BASIC Drug/Alc", "BASIC Veh Maint",
    "MCP Risk", "MCP Risk Points", "MCP Blocked",
    "SMS Data Date", "MCP Last Checked",
]


def _csv_cell(value: Optional[float], digits: int = 1) -> str:
    return "" if value is None else f"{value:.{digits}f}"


@router.get("/carriers.csv")
async def carriers_csv(
    request: Request,
    search: Optional[str] = Query(None),
    include_inactive: bool = Query(False),
    flagged: bool = Query(False),
    sort: str = Query(_DEFAULT_SORT),
    _user: dict = Depends(require_report_access("carrier-sms-score")),
):
    pool = get_ap_pool(request)
    order_by = _SORTS.get(sort, _SORTS[_DEFAULT_SORT])

    params: list = []
    where = _build_where(search, include_inactive, flagged, params)

    sql = f"""
    SELECT {_SELECT_COLUMNS}
    {_FROM}
    {where}
    ORDER BY {order_by}, c.name ASC
    """
    rows = await pool.fetch(sql, *params)

    buf = io.StringIO()
    writer = csv.writer(buf, lineterminator="\n")
    writer.writerow(_CSV_HEADER)
    for raw in rows:
        d = _row_to_dict(raw)
        writer.writerow([
            d["name"] or "",
            d["city"] or "",
            d["state"] or "",
            d["dot_number"] or "",
            d["mc_number"] or "",
            "Yes" if d["is_active"] else "No",
            _csv_cell(d["vehicle_oos_pct"]),
            _csv_cell(d["driver_oos_pct"]),
            _csv_cell(d["basic_unsafe"]),
            _csv_cell(d["basic_hos"]),
            _csv_cell(d["basic_fitness"]),
            _csv_cell(d["basic_drugalc"]),
            _csv_cell(d["basic_vehmaint"]),
            d["mcp_risk_overall"] or "",
            d["mcp_risk_points"] if d["mcp_risk_points"] is not None else "",
            "Yes" if d["mcp_is_blocked"] else "",
            d["data_file_date"] or "",
            d["mcp_last_checked"] or "",
        ])

    filename = f"carrier-sms-score_{cst_today().isoformat()}.csv"
    return Response(
        content=buf.getvalue(),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
