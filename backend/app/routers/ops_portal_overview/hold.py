"""Ops Portal - Overview: the "Hold" board.

Bruno PDF 2026-08-19 R1 (original: ``on_hold='Y'``) · PDF 2026-08-20 R2 (this
version: the UNBILLED backlog).

Orders McLeod has not billed, that are not voided/pending-cover — a billing
worklist sitting below the By Order table. ``on_hold`` is still SHOWN (the
✓ column and the free-text reason), it is simply no longer the filter.

⚠ ``bill_date < 2000-01-01`` means "not billed", and it needs a floor
-------------------------------------------------------------------
``1900-01-01`` is McLeod's not-billed sentinel; there are no NULLs. Applied
bare, the PDF's filter matches **59,139 rows** table-wide against the 730 that
``on_hold='Y'`` matched — because **2021 is an ETL artifact**. Measured on live
gold 2026-08-21:

    year   sentinel bill_date / rows      %
    2020        178 /    178          100.0
    2021     58,371 / 58,718           99.4   <- the feed never wrote bill_date
    2022          5 / 47,849            0.0
    2023          2 / 44,031            0.0
    2024          4 / 43,552            0.0
    2025          4 / 38,655            0.0
    2026        563 / 23,303            2.4   <- the real backlog

So a bare filter buries the ~570 genuinely-unbilled orders under ~58,500
phantom 2021 ones. ``UNBILLED_FROM`` is the floor that excludes the artifact;
with it the board is 350 rows CORP / 221 DFW, split ~50/50 between status P and
D — which is exactly the split the PDF's own P/D branching assumes.

⚠ The exclusion is NOT silent: the endpoint returns ``meta.unbilled_from`` and
the UI prints it in the header chip. A worklist that quietly drops rows reads
as "covered everything" when it did not.

⚠ STILL NOT DATE-WINDOWED beyond that floor — and that is the point
-------------------------------------------------------------------
Holds and unbilled orders sit for *months*; the oldest open one measured on
2026-08-19 had been stuck 8 months. Applying the page's date window would have
shown 2 of the then-18 rows and silently hidden the very rows the board exists
to surface (§74). ``UNBILLED_FROM`` is a fixed data-quality floor, not the
page's window — it never moves when the user changes the date filter.

The "Date" column (PDF 2026-08-20 R2)
-------------------------------------
One column, two rules, both in days:

  * ``status = 'P'`` → ``dest_sched_late − today``. Negative = overdue.
    Measured range −234 … +13 days, mean −5.
  * ``status = 'D'`` → ``dest_actual_departure − origin_actual_departure``,
    i.e. transit days. Measured 0 … 33, mean 2.

⚠ The PDF writes the D rule as "Orig Actual Departure - Dest Actual Departure",
which is the same magnitude with the sign flipped (0 … −33). It is emitted
Dest−Orig so that BOTH branches read as days on one scale with "negative =
late"; a column that flips meaning between two rows of the same table is
unreadable. Flagged to Bruno 2026-08-21.

⚠ BOTH operands are sentinel-guarded, on BOTH branches. ``1900-01-01`` is used
instead of NULL here too: 110 of the 273 status='P' rows carry a sentinel
``dest_sched_late``, which unguarded renders as ≈ −46,000 days. Guarded, they
come back NULL and the UI shows "—" (§ calendar-sentinel guard).

⚠ "Dest Sched Late" is read from ``mcleod_gld_customer_windows``
(``dest_sched_arrive_late``), NOT ``mcleod_gld_orders_pu_del_windows``
(``dest_sched_late``). The names point the other way, but coverage does not:
on the status='P' rows that need it, customer_windows resolves **269 of 272**
against pu_del_windows' 164, and the two agree exactly where both are present.
customer_windows is also already joined here, so this needs no third table —
and ``orders_pu_del_windows`` is NOT unique on ``id`` (259,572 rows /
216,688 ids), so joining it would have fanned the board out.

Scope
-----
Division-scoped via ``_scope.py`` — CORP (``TEAM1..TEAM5``) on the main portal
and the four CORP-T clones, ``TEAM-DFW`` on the DFW portal, which is why the
12 DFW rows the CORP board excludes are not lost, just filed elsewhere.

⚠ Why this cannot reuse ``_v4_scope_where``
-------------------------------------------
That helper hard-codes ``status = ANY(OPEN_STATUSES)`` (``'D'``/``'P'``), while
the PDF asks for ``status NOT IN ('V','A')``. Today those are the SAME set —
v4 only ever contains D/V/A/P — but they are not the same *rule*, and a new
McLeod status code would silently drop out of one and not the other. The scope
is therefore built inline here, the way ``/cover`` builds its own ``status='A'``.

⚠ The team column is read through ``_team_id_col``, never ``_team_id_select``
-----------------------------------------------------------------------------
``_team_id_select`` returns a SELECT ITEM — under DFW that is
``br4.team AS team_id`` — so wrapping it renders ``TRIM(br4.team AS team_id)``,
which Postgres rejects with ``42601``. It shipped that way on 2026-08-21 and
took this board down on the DFW page for every one of the 14 sort keys, while
the five CORP portals ran the same line unharmed because there the helper
returns a bare column. ``_team_id_col`` is the expression-safe form (§81).

Sources
-------
``mcleod_gld_budget_report_v4`` (money, hold flags, bill date — refreshed every
15 min; **never `_v5`**, which is dead), ``mcleod_gld_customer_windows`` for the
delivery timestamps behind the Date column / POD Age / Days to Bill,
``mcleod_gld_movement`` for the carrier, and AP_module's ``pod_tracker_loads``
for the POD tick. The POD lookup degrades to "no POD" rather than 503ing the
board (§5).
"""

from __future__ import annotations

from typing import List, Optional

from fastapi import Depends, Query, Request

from app.datalake import pad_variants as _pad_variants
from app.routers.deps import get_datalake_gold_pool, require_report_access

from ._constants import CORP_COMPANIES, router
from ._scope import scope_of
from ._metrics import _safe_float
from ._sql import _lane_expr, _sub_team_param, _team_id_col

# Statuses the PDF excludes: 'V' voided, 'A' available/pending cover.
EXCLUDED_HOLD_STATUSES = ("V", "A")

# McLeod's not-billed sentinel. Compared against, never rendered.
BILL_SENTINEL = "2000-01-01"

# Floor for the unbilled worklist — see the module docstring. Orders ordered
# before this are excluded because the 2021 feed never wrote `bill_date` at all
# (99.4% sentinel that year vs ~0.0% in 2022-2025), not because they are billed.
# Surfaced to the UI as `meta.unbilled_from`; never silently applied.
UNBILLED_FROM = "2022-01-01"

# Column -> ORDER BY. Whitelisted: `sort` reaches SQL as text.
_HOLD_SORTS: dict[str, str] = {
    "order_asc": "TRIM(br4.id) ASC",
    "order_desc": "TRIM(br4.id) DESC",
    "team_asc": "team_id ASC",
    "team_desc": "team_id DESC",
    # Sorts the rendered Date column. It is an expression, not a stored
    # column, so the ORDER BY repeats it rather than referencing the alias —
    # a bare alias would be ambiguous against `bill_date`.
    "date_asc": "date_days ASC NULLS LAST",
    "date_desc": "date_days DESC NULLS LAST",
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
    sort: str = Query("date_asc"),
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
    scope = scope_of(request)
    order_by = _HOLD_SORTS.get(sort, _HOLD_SORTS["date_asc"])

    # Sargable padded variants — McLeod stores these both padded and unpadded,
    # and TRIM() on the column would block the index (see app/datalake.py).
    params: list = [
        _pad_variants(scope.base_teams, width=8),
        _pad_variants(CORP_COMPANIES, width=4),
        _pad_variants(EXCLUDED_HOLD_STATUSES, width=1),
    ]
    parts = [
        "br4.team_id    = ANY($1)",
        "br4.company_id = ANY($2)",
        # PDF: status NOT IN ('V','A'). `<> ALL` rather than `= ANY(D,P)` so a
        # future McLeod status stays visible instead of silently vanishing.
        "br4.status    <> ALL($3)",
        # PDF 2026-08-20 R2: the board is the UNBILLED backlog, not `on_hold`.
        # `on_hold` is still selected and rendered, just no longer a filter.
        f"br4.bill_date < '{BILL_SENTINEL}'::date",
        # The 2021 ETL-gap floor — see the module docstring. Reported as
        # meta.unbilled_from so the drop is visible, never silent.
        f"br4.ordered_date >= '{UNBILLED_FROM}'::date",
        "UPPER(COALESCE(br4.customer_name,'')) NOT LIKE '%OILTEX%'",
    ]
    if team:
        params.append(_sub_team_param(scope, [team]))
        parts.append(f"br4.{scope.v4_team_col} = ANY(${len(params)})")
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
          TRIM({_team_id_col('br4', scope)}) AS team_id,
          TRIM(br4.status)    AS status,
          -- PDF 2026-08-20 R2 — one column, two rules, both in DAYS:
          --   status 'P' -> dest_sched_late - today   (negative = overdue)
          --   status 'D' -> dest_actual_departure - origin_actual_departure
          --                 (transit days; the PDF writes the operands the
          --                  other way round — see the module docstring)
          -- Every operand is sentinel-guarded in the LATERAL / here: McLeod
          -- writes 1900-01-01 rather than NULL, and 110 of 273 status='P'
          -- rows carry one. Unguarded that renders as ~-46,000 days.
          CASE
            WHEN TRIM(br4.status) = 'P' AND win.dest_sched_late_ts IS NOT NULL
              THEN (win.dest_sched_late_ts::date - CURRENT_DATE)
            WHEN TRIM(br4.status) = 'D' AND win.dest_dep_ts IS NOT NULL
                 AND br4.origin_actual_departure > '{BILL_SENTINEL}'::date
              THEN (win.dest_dep_ts::date - br4.origin_actual_departure::date)
          END AS date_days,
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
          -- Was always TRUE while `on_hold='Y'` was the filter; since PDF
          -- 2026-08-20 R2 it is genuinely informative — it marks which of the
          -- unbilled orders are ALSO flagged on hold. Selected, never assumed.
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
            SELECT MAX(CASE WHEN cw.dest_actual_arrival    > '2000-01-01' THEN cw.dest_actual_arrival    END) AS arr_ts,
                   MAX(CASE WHEN cw.dest_actual_departure  > '2000-01-01' THEN cw.dest_actual_departure  END) AS dest_dep_ts,
                   -- "Dest Sched Late" for the R2 Date column. Read here and
                   -- not from mcleod_gld_orders_pu_del_windows.dest_sched_late:
                   -- on the status='P' rows that need it this resolves 269 of
                   -- 272 against that table's 164, the two agree where both
                   -- exist, and that table is not unique on `id` (259,572 rows
                   -- / 216,688 ids) so joining it would fan the board out.
                   MAX(CASE WHEN cw.dest_sched_arrive_late > '2000-01-01' THEN cw.dest_sched_arrive_late END) AS dest_sched_late_ts
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
            "date_days":     int(r["date_days"]) if r["date_days"] is not None else None,
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
            # The UI prints this in the header chip. A worklist that drops rows
            # must SAY it dropped them — silent truncation reads as "covered
            # everything" when it did not. See the module docstring.
            "unbilled_from": UNBILLED_FROM,
        },
    }
