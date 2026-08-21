"""Service incident breakdowns by customer and by carrier.

Part of the ``ops_portal_overview`` package (split 2026-08-14 — see SPEC-CUSTOM-REPORTS §28).
"""

from __future__ import annotations

import asyncio
from datetime import date
from typing import List, Optional

from fastapi import Depends, Query, Request

from app.datalake import pad_variants as _pad_variants
from app.routers.deps import get_datalake_gold_pool, require_report_access

from ._constants import CORP_COMPANIES, CORP_TEAMS, OPEN_STATUSES, OTD_CODES, OTP_CODES, router
from ._dates import _resolve_range
from ._scope import scope_of
from ._sql import _sub_team_param, _scorecard_cte, _v4_scope_where
from ._metrics import _safe_float


# ---------------------------------------------------------------------------
# /service-incident-by-customer — incident-grain PU/DEL fails per customer
# ---------------------------------------------------------------------------

# PU = on-time-pickup fail codes (mirrors OTP_CODES / xray_corp); stops PU/SH.
# DEL = on-time-delivery fail codes (mirrors OTD_CODES); stops CO/SO. Same
# padded-variant EDI approach the file already uses for OTP/OTD (_scorecard_cte).
_PU_STOP_LIT = ",".join(f"'{v}'" for v in _pad_variants(("PU", "SH"), width=2))
_DEL_STOP_LIT = ",".join(f"'{v}'" for v in _pad_variants(("CO", "SO"), width=2))
_PU_CODE_LIT = ",".join(f"'{v}'" for v in _pad_variants(OTP_CODES, width=40))
_DEL_CODE_LIT = ",".join(f"'{v}'" for v in _pad_variants(OTD_CODES, width=40))


@router.get("/service-incident-by-customer")
async def service_incident_by_customer(
    request: Request,
    range: Optional[str] = Query("mtd"),
    start_date: Optional[date] = Query(None),
    end_date: Optional[date] = Query(None),
    team: Optional[str] = Query(None),
    customer: Optional[str] = Query(None),
    load_type: Optional[str] = Query(None),
    lanes: Optional[List[str]] = Query(None),
    exclude_lanes: Optional[List[str]] = Query(None),
    # Bruno (PDF 2026-07-15) R1: Carrier multi-select (Include/Exclude).
    carriers: Optional[List[str]] = Query(None),
    exclude_carriers: Optional[List[str]] = Query(None),
    stop_type: str = Query("pu", description="'pu' | 'del'"),
    _user: dict = Depends(require_report_access("ops-portal-overview")),
):
    """PU or DEL service fails per customer over the incident-grain source
    ``mcleod_gld_scorecard_incidents_portal`` (same OTP/OTD code lists +
    padded-variant approach as ``_scorecard_cte``).

    ``orders`` = distinct charged loads, ``fail`` = distinct loads with a PU/DEL
    service fail, ``pct_on_time`` = 100 − 100*fail/orders. Top 100 by fail desc;
    ``meta.totals`` is the full-universe server-side aggregate.

    The incident table has no lane / city-pair grain (it is not in v4) and no
    contract_type column, so the ``lanes`` / ``exclude_lanes`` / ``load_type``
    filters are ignored here (same precedent the file already documents for the
    budget-only panels). Team / customer / date filters are honored.
    """
    pool = get_datalake_gold_pool(request)
    scope = scope_of(request)
    side = "del" if (stop_type or "").lower() == "del" else "pu"
    date_col = "orig_actual_departure" if side == "pu" else "dest_actual_departure"
    stops_lit = _PU_STOP_LIT if side == "pu" else _DEL_STOP_LIT
    codes_lit = _PU_CODE_LIT if side == "pu" else _DEL_CODE_LIT

    s, e = _resolve_range(range, start_date, end_date)

    teams_param = _pad_variants(scope.base_teams, width=8)
    companies_param = _pad_variants(CORP_COMPANIES, width=4)
    statuses_param = _pad_variants(OPEN_STATUSES, width=1)
    params: list = [teams_param, companies_param, statuses_param, s, e]
    parts = [
        "sc.team_id    = ANY($1)",
        "sc.company_id = ANY($2)",
        "sc.status     = ANY($3)",
        "UPPER(COALESCE(sc.customer_name,'')) NOT LIKE '%OILTEX%'",
        f"sc.{date_col} >= $4",
        f"sc.{date_col} < ($5::date + INTERVAL '1 day')",
    ]
    if team:
        params.append(_sub_team_param(scope, [team]))
        parts.append(f"sc.{scope.sc_team_col} = ANY(${len(params)})")
    if customer:
        params.append(customer)
        parts.append(f"sc.customer_name = ${len(params)}")
    # ``load_type`` is accepted for API symmetry with /actuals but ignored here:
    # the incident table has no contract_type / load-type grain.
    where = " AND ".join(parts)
    fail_pred = (
        f"(sc.stop_type IN ({stops_lit}) "
        f"AND sc.edi_standard_code IN ({codes_lit}))"
    )

    by_customer_sql = f"""
        SELECT
          TRIM(sc.customer_name) AS customer_name,
          COUNT(DISTINCT sc.id) FILTER (WHERE sc.total_charge IS NOT NULL AND sc.total_charge <> 0) AS orders,
          COUNT(DISTINCT sc.id) FILTER (WHERE {fail_pred}) AS fail
        FROM public.mcleod_gld_scorecard_incidents_portal sc
        WHERE {where}
          AND sc.customer_name IS NOT NULL
          AND TRIM(sc.customer_name) <> ''
        GROUP BY TRIM(sc.customer_name)
        HAVING COUNT(DISTINCT sc.id) FILTER (WHERE sc.total_charge IS NOT NULL AND sc.total_charge <> 0) > 0
        ORDER BY fail DESC NULLS LAST, orders DESC
        LIMIT 100
    """
    totals_sql = f"""
        SELECT
          COUNT(DISTINCT sc.id) FILTER (WHERE sc.total_charge IS NOT NULL AND sc.total_charge <> 0) AS orders,
          COUNT(DISTINCT sc.id) FILTER (WHERE {fail_pred}) AS fail
        FROM public.mcleod_gld_scorecard_incidents_portal sc
        WHERE {where}
    """

    rows, tot_row = await asyncio.gather(
        pool.fetch(by_customer_sql, *params),
        pool.fetchrow(totals_sql, *params),
    )

    def _on_time(orders: int, fail: int) -> float:
        return (1.0 - (fail / orders)) * 100.0 if orders else 0.0

    data = [
        {
            "customer_name": r["customer_name"],
            "orders": int(r["orders"] or 0),
            "fail": int(r["fail"] or 0),
            "pct_on_time": _safe_float(_on_time(int(r["orders"] or 0), int(r["fail"] or 0))),
        }
        for r in rows
    ]
    t_orders = int(tot_row["orders"] or 0) if tot_row else 0
    t_fail = int(tot_row["fail"] or 0) if tot_row else 0
    return {
        "success": True,
        "data": data,
        "meta": {
            "stop_type": side,
            "window": {"start": s.isoformat(), "end": e.isoformat()},
            "totals": {
                "orders": t_orders,
                "fail": t_fail,
                "pct_on_time": _safe_float(_on_time(t_orders, t_fail)),
            },
        },
    }


# ---------------------------------------------------------------------------
# /service-by-carrier — Bruno (PDF 2026-07-15) R8: Vol / %Vol / OTP / OTD per
# carrier (first-movement payee). Same v4 + _scorecard_cte + movement pattern as
# /actuals-by-lane, grouped by carrier instead of lane.
# ---------------------------------------------------------------------------


@router.get("/service-by-carrier")
async def service_by_carrier(
    request: Request,
    range: Optional[str] = Query("mtd"),
    start_date: Optional[date] = Query(None),
    end_date: Optional[date] = Query(None),
    team: Optional[str] = Query(None),
    customer: Optional[str] = Query(None),
    load_type: Optional[str] = Query(None),
    lanes: Optional[List[str]] = Query(None),
    exclude_lanes: Optional[List[str]] = Query(None),
    carriers: Optional[List[str]] = Query(None),
    exclude_carriers: Optional[List[str]] = Query(None),
    limit: int = Query(100, ge=1, le=500),
    _user: dict = Depends(require_report_access("ops-portal-overview")),
):
    """Per-carrier trip counts + OTP/OTD over the production window.

    ``carrier`` = first-movement ``payee_name`` (same definition the By Order /
    By Lane tables use). ``vol`` = charged loads; ``pct_vol`` = carrier vol /
    all-carrier vol (loads with an assigned carrier); OTP/OTD use the same
    ``_scorecard_cte`` per-order late roll-up as /team-performance. Orders with
    no carrier assigned are excluded (they belong to Pending-to-Cover).
    """
    pool = get_datalake_gold_pool(request)
    scope = scope_of(request)
    s, e = _resolve_range(range, start_date, end_date)

    p_params: list = []
    where = _v4_scope_where(
        "br4", team, customer, load_type, p_params,
        lanes, exclude_lanes, carriers, exclude_carriers, scope=scope,
    )
    p_params.extend([s, e])
    p_s = len(p_params) - 1
    p_e = len(p_params)

    sql = f"""
        WITH otp AS ({_scorecard_cte("otp", scope)}),
             otd AS ({_scorecard_cte("otd", scope)}),
             prod AS (
                SELECT
                    NULLIF(TRIM(mov.payee_name), '') AS carrier,
                    br4.total_charge,
                    COALESCE(otp.scorecard_count_otp, 0) AS otp_cnt,
                    COALESCE(otd.scorecard_count_otd, 0) AS otd_cnt
                FROM public.mcleod_gld_budget_report_v4 br4
                LEFT JOIN otp ON TRIM(br4.id)=otp.id_key AND TRIM(br4.company_id)=otp.company_id_key
                LEFT JOIN otd ON TRIM(br4.id)=otd.id_key AND TRIM(br4.company_id)=otd.company_id_key
                LEFT JOIN LATERAL (
                    SELECT m.payee_name
                    FROM public.mcleod_gld_movement m
                    WHERE m.order_id = br4.id AND m.company_id = br4.company_id
                    ORDER BY m.movement_id ASC
                    LIMIT 1
                ) mov ON TRUE
                WHERE {where}
                  AND br4.origin_actual_departure >= ${p_s}
                  AND br4.origin_actual_departure < (${p_e}::date + INTERVAL '1 day')
             )
        SELECT
          carrier,
          COUNT(*) FILTER (WHERE total_charge IS NOT NULL AND total_charge <> 0) AS vol,
          SUM(otp_cnt) AS otp_late,
          SUM(otd_cnt) AS otd_late
        FROM prod
        WHERE carrier IS NOT NULL
        GROUP BY carrier
        HAVING COUNT(*) FILTER (WHERE total_charge IS NOT NULL AND total_charge <> 0) > 0
        ORDER BY vol DESC NULLS LAST
    """

    rows = await pool.fetch(sql, *p_params)
    total_vol = sum(int(r["vol"] or 0) for r in rows)
    out = []
    for r in rows:
        vol = int(r["vol"] or 0)
        otp_late = int(r["otp_late"] or 0)
        otd_late = int(r["otd_late"] or 0)
        out.append({
            "carrier":  r["carrier"],
            "vol":      vol,
            "pct_vol":  _safe_float((vol / total_vol * 100.0) if total_vol else 0.0),
            "otp_pct":  _safe_float((1.0 - otp_late / vol) * 100.0 if vol else 0.0),
            "otd_pct":  _safe_float((1.0 - otd_late / vol) * 100.0 if vol else 0.0),
        })
    out = out[:limit]

    return {
        "success": True,
        "data": out,
        "meta": {
            "window": {"start": s.isoformat(), "end": e.isoformat()},
            "totals": {"vol": total_vol, "carriers": len(rows)},
        },
    }
