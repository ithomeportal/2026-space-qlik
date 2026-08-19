"""Ops Portal - Overview: the "Hold" board (Bruno PDF 2026-08-19 R1).

Loads McLeod has flagged ``on_hold = 'Y'`` that are not voided/pending-cover —
a billing-blocker worklist sitting below the By Order table.

⚠ NOT DATE-WINDOWED — and that is the point
-------------------------------------------
Measured on live gold 2026-08-19, ``on_hold='Y' AND status NOT IN ('V','A')``
matches **18 rows in the entire table**, with departures spanning 2025-12-13 →
2026-08-18. Holds sit for *months*: the oldest open one had been stuck 8 months.
Applying the page's date window would have shown 2 of them and silently hidden
the very rows the board exists to surface — the stale ones. So the board reads
the whole table and is refreshed by the page's other filters only.

That also matches the PDF, which lists exactly two filters and no date range,
and it matches the sibling ``/cover`` and ``/pending-to-cover`` boards in the
same panel, which are likewise live rather than windowed.

Scope (decision: Diego, 2026-08-19)
-----------------------------------
CORP only — ``CORP_TEAMS`` / ``CORP_COMPANIES`` / no OILTEX — exactly like every
other panel on this page. This is a real narrowing: **12 of the 18 hold rows are
TEAM-DFW**, which ``_constants.py`` deliberately excludes from this report, so
the board shows 4 rows today. Showing them would have put a non-CORP team on a
CORP portal and made the Team filter lie.

⚠ Why this cannot reuse ``_v4_scope_where``
-------------------------------------------
That helper hard-codes ``status = ANY(OPEN_STATUSES)`` (``'D'``/``'P'``), while
the PDF asks for ``status NOT IN ('V','A')``. Today those are the SAME set —
v4 only ever contains D/V/A/P — but they are not the same *rule*, and a new
McLeod status code would silently drop out of one and not the other. The scope
is therefore built inline here, the way ``/cover`` builds its own ``status='A'``.

Sources
-------
``mcleod_gld_budget_report_v4`` (money, hold flags, bill date — refreshed every
15 min; **never `_v5`**, which is dead), ``mcleod_gld_customer_windows`` for the
delivery timestamps behind POD Age / Days to Bill, ``mcleod_gld_movement`` for
the carrier, and AP_module's ``pod_tracker_loads`` for the POD tick. The POD
lookup degrades to "no POD" rather than 503ing the board (§5).
"""

from __future__ import annotations

from typing import List, Optional

from fastapi import Depends, Query, Request

from app.datalake import pad_variants as _pad_variants
from app.routers.deps import get_datalake_gold_pool, require_report_access

from ._constants import CORP_COMPANIES, CORP_TEAMS, router
from ._metrics import _safe_float
from ._sql import _lane_expr

# Statuses the PDF excludes: 'V' voided, 'A' available/pending cover.
EXCLUDED_HOLD_STATUSES = ("V", "A")

# Column -> ORDER BY. Whitelisted: `sort` reaches SQL as text.
_HOLD_SORTS: dict[str, str] = {
    "order_asc": "TRIM(br4.id) ASC",
    "order_desc": "TRIM(br4.id) DESC",
    "team_asc": "TRIM(br4.team_id) ASC",
    "team_desc": "TRIM(br4.team_id) DESC",
    "departure_asc": "br4.origin_actual_departure ASC NULLS LAST",
    "departure_desc": "br4.origin_actual_departure DESC NULLS LAST",
    "revenue_asc": "COALESCE(br4.total_charge,0) ASC",
    "revenue_desc": "COALESCE(br4.total_charge,0) DESC",
    "carrier_cost_asc": "COALESCE(br4.total_carrier_pay,0) ASC",
    "carrier_cost_desc": "COALESCE(br4.total_carrier_pay,0) DESC",
    "profit_asc": "COALESCE(br4.margin_amt,0) ASC",
    "profit_desc": "COALESCE(br4.margin_amt,0) DESC",
    "hold_reason_asc": "TRIM(COALESCE(br4.hold_reason,'')) ASC",
    "hold_reason_desc": "TRIM(COALESCE(br4.hold_reason,'')) DESC",
}


@router.get("/hold")
async def hold_board(  # NOT `hold`: `from .hold import hold` in the package
                       # __init__ would rebind the submodule attribute to this
                       # function, so `import ...hold as m` would hand back a
                       # function instead of the module.

    request: Request,
    team: Optional[str] = Query(None),
    customer: Optional[str] = Query(None),
    lanes: Optional[List[str]] = Query(None),
    exclude_lanes: Optional[List[str]] = Query(None),
    sort: str = Query("departure_desc"),
    limit: int = Query(500, ge=1, le=2000),
    _user: dict = Depends(require_report_access("ops-portal-overview")),
):
    """Orders on hold — the whole table, narrowed only by the page's filters.

    Deliberately takes the SAME scope params as ``/cover`` and no date params,
    so the frontend can serialise it with ``scopeQs``: a query string that
    carries fields the endpoint ignores is exactly how this package previously
    collapsed two different requests onto one cache entry.
    """
    pool = get_datalake_gold_pool(request)
    order_by = _HOLD_SORTS.get(sort, _HOLD_SORTS["departure_desc"])

    # Sargable padded variants — McLeod stores these both padded and unpadded,
    # and TRIM() on the column would block the index (see app/datalake.py).
    params: list = [
        _pad_variants(CORP_TEAMS, width=8),
        _pad_variants(CORP_COMPANIES, width=4),
        _pad_variants(("Y",), width=1),
        _pad_variants(EXCLUDED_HOLD_STATUSES, width=1),
    ]
    parts = [
        "br4.team_id    = ANY($1)",
        "br4.company_id = ANY($2)",
        "br4.on_hold    = ANY($3)",
        # PDF: status NOT IN ('V','A'). `<> ALL` rather than `= ANY(D,P)` so a
        # future McLeod status stays visible instead of silently vanishing.
        "br4.status    <> ALL($4)",
        "UPPER(COALESCE(br4.customer_name,'')) NOT LIKE '%OILTEX%'",
    ]
    if team:
        params.append(_pad_variants([team], width=8))
        parts.append(f"br4.team_id = ANY(${len(params)})")
    if customer:
        params.append(customer)
        parts.append(f"br4.customer_name = ${len(params)}")
    if lanes:
        params.append(lanes)
        parts.append(f"{_lane_expr('br4')} = ANY(${len(params)})")
    if exclude_lanes:
        params.append(exclude_lanes)
        parts.append(f"{_lane_expr('br4')} <> ALL(${len(params)})")
    where = " AND ".join(parts)

    params.append(limit)
    p_lim = len(params)

    sql = f"""
        SELECT
          TRIM(br4.id)        AS order_id,
          TRIM(br4.team_id)   AS team_id,
          TRIM(br4.status)    AS status,
          to_char(br4.origin_actual_departure, 'YYYY-MM-DD') AS departure,
          br4.customer_name   AS customer_name,
          COALESCE(TRIM(mov.payee_name), '') AS carrier,
          NULLIF(TRIM(COALESCE(br4.origin_name,'')) || ' - ' || TRIM(COALESCE(br4.dest_name,'')), ' - ') AS lane,
          COALESCE(br4.total_charge, 0)::numeric      AS revenue,
          -- Carrier Cost is total_carrier_pay, matching the Cover board. NOT
          -- revenue - profit: on this board margin_amt is frequently negative
          -- (claims), and the two definitions would disagree on exactly the
          -- rows people are looking at (§69).
          COALESCE(br4.total_carrier_pay, 0)::numeric AS carrier_cost,
          COALESCE(br4.margin_amt, 0)::numeric        AS profit,
          CASE WHEN br4.total_charge IS NOT NULL AND br4.total_charge <> 0
               THEN br4.margin_amt / br4.total_charge * 100.0 ELSE 0 END AS margin,
          -- Always TRUE given the WHERE, but selected so the column renders off
          -- the DATA rather than off an assumption about the filter.
          (TRIM(COALESCE(br4.on_hold,'')) = 'Y') AS on_hold,
          -- Free text, varchar(20), mixed case in the wild ('CLAIM', 'accident',
          -- 'compesation'). Passed through verbatim — normalising it would edit
          -- what the ops team typed.
          TRIM(COALESCE(br4.hold_reason, '')) AS hold_reason,
          -- 1900-01-01 is McLeod's "not billed" sentinel, not a real date.
          CASE WHEN br4.bill_date > '2000-01-01'::date
               THEN to_char(br4.bill_date, 'YYYY-MM-DD') END AS bill_date,
          (br4.bill_date > '2000-01-01'::date) AS billed,
          CASE
            WHEN win.dest_dep_ts IS NULL THEN NULL
            WHEN br4.bill_date > '2000-01-01'::date
                 THEN (br4.bill_date::date - win.dest_dep_ts::date)
            ELSE (CURRENT_DATE - win.dest_dep_ts::date)
          END AS days_to_bill,
          CASE WHEN COALESCE(win.arr_ts, win.dest_dep_ts) IS NOT NULL
               THEN EXTRACT(EPOCH FROM (CURRENT_TIMESTAMP - COALESCE(win.arr_ts, win.dest_dep_ts))) / 3600.0
          END AS pod_age_hours,
          -- §44: window aggregates run after WHERE but BEFORE LIMIT, so the
          -- pinned Totals row describes the FULL universe even when capped.
          COUNT(*) OVER ()                                                  AS n_all,
          COALESCE(SUM(COALESCE(br4.total_charge,0))      OVER (), 0)::numeric AS t_revenue,
          COALESCE(SUM(COALESCE(br4.total_carrier_pay,0)) OVER (), 0)::numeric AS t_carrier_cost,
          COALESCE(SUM(COALESCE(br4.margin_amt,0))        OVER (), 0)::numeric AS t_profit
        FROM public.mcleod_gld_budget_report_v4 br4
        LEFT JOIN LATERAL (
            SELECT MAX(CASE WHEN cw.dest_actual_arrival   > '2000-01-01' THEN cw.dest_actual_arrival   END) AS arr_ts,
                   MAX(CASE WHEN cw.dest_actual_departure > '2000-01-01' THEN cw.dest_actual_departure END) AS dest_dep_ts
            FROM public.mcleod_gld_customer_windows cw
            WHERE TRIM(UPPER(cw.id)) = TRIM(UPPER(br4.id))
        ) win ON TRUE
        LEFT JOIN LATERAL (
            SELECT m.payee_name
            FROM public.mcleod_gld_movement m
            WHERE m.order_id = br4.id AND m.company_id = br4.company_id
            ORDER BY m.movement_id ASC
            LIMIT 1
        ) mov ON TRUE
        WHERE {where}
        ORDER BY {order_by}
        LIMIT ${p_lim}
    """

    rows = await pool.fetch(sql, *params)

    out = []
    for r in rows:
        dtb = r["days_to_bill"]
        out.append({
            "order_id":      r["order_id"],
            "team_id":       r["team_id"],
            "status":        (r["status"] or "").strip().upper(),
            "departure":     r["departure"] or "",
            "customer_name": r["customer_name"] or "",
            "carrier":       r["carrier"] or "",
            "lane":          r["lane"] or "",
            "revenue":       _safe_float(r["revenue"]),
            "carrier_cost":  _safe_float(r["carrier_cost"]),
            "profit":        _safe_float(r["profit"]),
            "margin_pct":    _safe_float(r["margin"]),
            "on_hold":       bool(r["on_hold"]),
            "hold_reason":   r["hold_reason"] or "",
            "billed":        bool(r["billed"]),
            # None (not "") when unbilled, so the UI renders an em-dash rather
            # than McLeod's 1900-01-01 sentinel.
            "bill_date":     r["bill_date"],
            "days_to_bill":  int(dtb) if dtb is not None else None,
            "pod_age_hours": _safe_float(r["pod_age_hours"]) if r["pod_age_hours"] is not None else None,
        })

    # POD tick — AP_module's pod_tracker_loads, a SEPARATE Postgres server, so
    # it cannot be JOINed. Degrades to pod=False rather than taking the board
    # down: POD is a supplementary indicator, not core production data.
    pod_set: set[str] = set()
    order_ids = [r["order_id"] for r in out if r["order_id"]]
    ap_pool = getattr(request.app.state, "ap_pool", None)
    if ap_pool is not None and order_ids:
        try:
            pod_rows = await ap_pool.fetch(
                """
                SELECT UPPER(TRIM(mcleod_order_id)) AS oid
                FROM pod_tracker_loads
                WHERE has_pod = TRUE
                  AND UPPER(TRIM(mcleod_order_id)) = ANY($1::text[])
                """,
                [o.upper() for o in order_ids],
            )
            pod_set = {r["oid"] for r in pod_rows}
        except Exception:
            pod_set = set()
    for r in out:
        r["pod"] = bool(r["order_id"]) and r["order_id"].upper() in pod_set

    n_all = int(rows[0]["n_all"]) if rows else 0
    t_revenue = _safe_float(rows[0]["t_revenue"]) if rows else 0.0
    t_profit = _safe_float(rows[0]["t_profit"]) if rows else 0.0
    totals = {
        "n_orders":     n_all,
        "revenue":      t_revenue,
        "carrier_cost": _safe_float(rows[0]["t_carrier_cost"]) if rows else 0.0,
        "profit":       t_profit,
        "margin_pct":   _safe_float((t_profit / t_revenue * 100.0) if t_revenue else 0.0),
    }

    return {
        "success": True,
        "data": out,
        "meta": {
            "total": n_all,
            "returned": len(out),
            "limit": limit,
            "totals": totals,
        },
    }
