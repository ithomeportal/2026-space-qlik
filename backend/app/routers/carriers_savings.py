"""Code-made report: eSavings from Carriers.

Reads from aivn_datalake_gold.carriers_savings_results_report (populated daily by the
'Carriers Savings Update - 4 AM CST' n8n workflow, PdZIaBQPGSLD4VWB).

The n8n workflow already uses the quarterly rolling base logic (as of 2026-04-06):
Q2 2026 months use the simple avg of Q1 2026 monthly avgs as the base, stored as
`base_month = 'Q1-2026'` in the report table. No on-the-fly recalculation needed.
"""

from datetime import date
from typing import Optional

from fastapi import APIRouter, Depends, Query, Request

from app.routers.deps import get_savings_pool, require_tag_role

# TagRoles that can view eSavings from Carriers (admin bypasses)
SAVINGS_ROLES = ("ceo", "executive", "procurement", "finance", "corp")

router = APIRouter(tags=["carriers-savings"], prefix="/custom/carriers-savings")


@router.get("/months")
async def list_months(
    request: Request,
    _user: dict = Depends(require_tag_role(*SAVINGS_ROLES)),
):
    """Distinct months available in the report table, newest first."""
    pool = get_savings_pool(request)
    rows = await pool.fetch(
        """
        SELECT DISTINCT month_date::text AS month_date,
                        type_month_description,
                        MAX(base_month) AS base_month
        FROM public.carriers_savings_results_report
        WHERE month_date IS NOT NULL
        GROUP BY month_date, type_month_description
        ORDER BY month_date DESC
        """
    )
    return {"success": True, "data": [dict(r) for r in rows]}


@router.get("/summary")
async def summary(
    request: Request,
    month: Optional[date] = Query(None, description="YYYY-MM-01"),
    customer_id: Optional[str] = Query(None),
    _user: dict = Depends(require_tag_role(*SAVINGS_ROLES)),
):
    """4 main KPIs for a given month: loads, savings, overpay, net variance.

    Mirrors the Qlik dashboard logic:
      - Total Savings  = SUM(variance WHERE variance > 0)
      - Total Overpay  = SUM(variance WHERE variance < 0)  (negative number)
      - Net Variance   = SUM(variance)
      - Volume (Loads) = SUM(number_monthly_loads)
    Plus lane-volume buckets (high-vol >=8, low-vol 1-7).
    """
    pool = get_savings_pool(request)

    target_month = await _resolve_month(pool, month)

    row = await pool.fetchrow(
        """
        WITH filtered AS (
          SELECT *
          FROM public.carriers_savings_results_report
          WHERE month_date = $1
            AND ($2::text IS NULL OR customer_id = $2)
        )
        SELECT
          COALESCE(SUM(number_monthly_loads), 0)              AS total_loads,
          COALESCE(SUM(cost_monthly_usd), 0)                  AS total_cost,
          COALESCE(SUM(CASE WHEN variance > 0 THEN variance END), 0) AS total_savings,
          COALESCE(SUM(CASE WHEN variance < 0 THEN variance END), 0) AS total_overpay,
          COALESCE(SUM(variance), 0)                          AS net_variance,
          COUNT(*) FILTER (WHERE number_monthly_loads >= 8)   AS high_vol_lanes,
          COUNT(*) FILTER (WHERE number_monthly_loads BETWEEN 1 AND 7) AS low_vol_lanes,
          COUNT(*) FILTER (WHERE number_monthly_loads >= 8
                             AND variance > 0)                AS high_vol_savings_lanes,
          COUNT(*) FILTER (WHERE number_monthly_loads BETWEEN 1 AND 7
                             AND variance > 0)                AS low_vol_savings_lanes,
          MAX(base_month)                                     AS base_month,
          AVG(NULLIF(base_lane, 0))                           AS avg_base_lane
        FROM filtered
        """,
        target_month,
        customer_id,
    )

    data = dict(row) if row else {}
    data["month_date"] = target_month.isoformat() if target_month else None
    return {"success": True, "data": data}


@router.get("/by-customer")
async def by_customer(
    request: Request,
    month: Optional[date] = Query(None),
    _user: dict = Depends(require_tag_role(*SAVINGS_ROLES)),
    limit: int = Query(50, ge=1, le=500),
):
    """Aggregate savings per customer for a given month, sorted by biggest savings first."""
    pool = get_savings_pool(request)
    target_month = await _resolve_month(pool, month)

    rows = await pool.fetch(
        """
        SELECT
          customer_id,
          customer_name,
          COUNT(*)                                         AS lane_count,
          SUM(number_monthly_loads)                        AS loads,
          SUM(cost_monthly_usd)                            AS cost,
          SUM(CASE WHEN variance > 0 THEN variance END)    AS savings,
          SUM(CASE WHEN variance < 0 THEN variance END)    AS overpay,
          SUM(variance)                                    AS net_variance
        FROM public.carriers_savings_results_report
        WHERE month_date = $1
        GROUP BY customer_id, customer_name
        HAVING SUM(number_monthly_loads) > 0
        ORDER BY SUM(variance) DESC NULLS LAST
        LIMIT $2
        """,
        target_month,
        limit,
    )
    return {
        "success": True,
        "data": [dict(r) for r in rows],
        "meta": {"month_date": target_month.isoformat() if target_month else None},
    }


@router.get("/lanes")
async def lanes(
    request: Request,
    month: Optional[date] = Query(None),
    customer_id: Optional[str] = Query(None),
    origin: Optional[str] = Query(None),
    dest: Optional[str] = Query(None),
    sort: str = Query("variance_desc"),
    page: int = Query(1, ge=1),
    limit: int = Query(100, ge=1, le=500),
    _user: dict = Depends(require_tag_role(*SAVINGS_ROLES)),
):
    """Detail rows — one row per lane for the selected month, with filters and paging."""
    pool = get_savings_pool(request)
    target_month = await _resolve_month(pool, month)

    sort_sql = {
        "variance_desc": "variance DESC NULLS LAST",
        "variance_asc": "variance ASC NULLS LAST",
        "loads_desc": "number_monthly_loads DESC",
        "cost_desc": "cost_monthly_usd DESC",
        "customer": "customer_name ASC",
    }.get(sort, "variance DESC NULLS LAST")

    offset = (page - 1) * limit

    where_parts = ["month_date = $1"]
    params: list = [target_month]
    if customer_id:
        params.append(customer_id)
        where_parts.append(f"customer_id = ${len(params)}")
    if origin:
        params.append(f"%{origin}%")
        where_parts.append(f"origin_name ILIKE ${len(params)}")
    if dest:
        params.append(f"%{dest}%")
        where_parts.append(f"dest_name ILIKE ${len(params)}")

    params_with_paging = params + [limit, offset]

    rows = await pool.fetch(
        f"""
        SELECT customer_id, customer_name, origin_name, dest_name,
               cost_monthly_usd, number_monthly_loads, avg_monthly_usd,
               variance, base_lane, base_month, type_month_description,
               month_date::text AS month_date
        FROM public.carriers_savings_results_report
        WHERE {' AND '.join(where_parts)}
        ORDER BY {sort_sql}
        LIMIT ${len(params) + 1} OFFSET ${len(params) + 2}
        """,
        *params_with_paging,
    )

    total = await pool.fetchval(
        f"""
        SELECT COUNT(*)
        FROM public.carriers_savings_results_report
        WHERE {' AND '.join(where_parts)}
        """,
        *params,
    )

    return {
        "success": True,
        "data": [dict(r) for r in rows],
        "meta": {
            "total": total,
            "page": page,
            "limit": limit,
            "month_date": target_month.isoformat() if target_month else None,
        },
    }


async def _resolve_month(pool, requested: Optional[date]) -> Optional[date]:
    """Return the requested month if it has data, otherwise the latest month with data."""
    if requested is not None:
        exists = await pool.fetchval(
            "SELECT 1 FROM public.carriers_savings_results_report WHERE month_date = $1 LIMIT 1",
            requested,
        )
        if exists:
            return requested
    return await pool.fetchval(
        "SELECT MAX(month_date) FROM public.carriers_savings_results_report"
    )
