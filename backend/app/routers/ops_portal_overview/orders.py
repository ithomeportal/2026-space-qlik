"""By Order board — Production, Cover and Pending to Cover.

Part of the ``ops_portal_overview`` package (split 2026-08-14 — see SPEC-CUSTOM-REPORTS §28).
"""

from __future__ import annotations

import asyncio
from datetime import date
from typing import List, Optional

from fastapi import Depends, Query, Request

from app.datalake import pad_variants as _pad_variants
from app.routers.deps import get_datalake_gold_pool, require_report_access

from ._constants import CORP_COMPANIES, CORP_TEAMS, router
from ._dates import _resolve_range
from ._scope import scope_of
from ._sql import _sub_team_param, _ASSIGNED, _lane_expr, _scorecard_cte, _v4_scope_where
from ._metrics import _safe_float


# ---------------------------------------------------------------------------
# /by-order — Bruno R4 (2026-05-27) load-level Production table
# ---------------------------------------------------------------------------

_BY_ORDER_SORTS = {
    "order_asc":     "order_id ASC",
    "order_desc":    "order_id DESC",
    "team_asc":      "team_id ASC, order_id ASC",
    "team_desc":     "team_id DESC, order_id ASC",
    "departure_asc": "br4.origin_actual_departure ASC NULLS LAST",
    "departure_desc": "br4.origin_actual_departure DESC NULLS LAST",
    "customer_asc":  "customer_name ASC, order_id ASC",
    "customer_desc": "customer_name DESC, order_id ASC",
    "lane_asc":      "lane ASC, order_id ASC",
    "lane_desc":     "lane DESC, order_id ASC",
    # Bruno round (2026-07-01) R2: Carrier column (movement.payee_name).
    "carrier_asc":   "carrier ASC, order_id ASC",
    "carrier_desc":  "carrier DESC, order_id ASC",
    "revenue_asc":   "revenue ASC NULLS LAST",
    "revenue_desc":  "revenue DESC NULLS LAST",
    "profit_asc":    "profit ASC NULLS LAST",
    "profit_desc":   "profit DESC NULLS LAST",
    "margin_asc":    "margin ASC NULLS LAST",
    "margin_desc":   "margin DESC NULLS LAST",
    # Bruno R5 (2026-06-01): OTP/OTD/Transit columns (sort by SELECT alias).
    "otp_asc":       "otp_pct ASC, order_id ASC",
    "otp_desc":      "otp_pct DESC, order_id ASC",
    "otd_asc":       "otd_pct ASC, order_id ASC",
    "otd_desc":      "otd_pct DESC, order_id ASC",
    "transit_asc":   "transit_seconds ASC NULLS LAST",
    "transit_desc":  "transit_seconds DESC NULLS LAST",
}


@router.get("/by-order")
async def by_order(
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
    sort: str = Query("revenue_desc"),
    limit: int = Query(500, ge=1, le=2000),
    losses_only: bool = Query(False),
    unbilled_only: bool = Query(False),
    _user: dict = Depends(require_report_access("ops-portal-overview")),
):
    """Load-level Production table (one row per order).

    Columns per Bruno's R4 PDF:
      Order=id · Team=team_id · Departure=origin_actual_departure ·
      Customer=customer_name · Lane=origin_name - dest_name ·
      Revenue=total_charge · Profit=margin_amt · Margin=margin_amt/total_charge.

    Bruno R5 (2026-06-01) added:
      - OTP % / OTD %  → per-order on-time flag from mcleod_gld_scorecard
        (0 late stops → 100%, else 0%; same code list as the §5 panel).
      - Transit Time   → dest_actual_arrival − orig_actual_departure from
        public.mcleod_gld_customer_windows (joined on id; the PDF's
        "origin_actual_departure − dest_actual_arrival" is reversed — we
        compute arrival − departure so the duration is positive).
      - In-progress timer → for status 'P' loads with no arrival yet, the UI
        ticks now() − departed_at; the backend hands back ``departed_at`` and
        the ``in_progress`` flag.
      - "Losses" button → ``losses_only`` restricts to margin_amt < 0.

    Server-side sort on every column (the set is load-level, so a client-side
    sort of the fetched page could mis-rank). Totals are computed over the
    full filtered set in ``meta`` regardless of the limit slice.

    All window timestamps are emitted via ``to_char`` (text) to dodge the
    asyncpg date-decode overflow on any 5-digit-year McLeod typo
    (SPEC-CODE-RULES §4). The customer_windows join is a correlated LATERAL that
    MAXes the (sentinel-guarded) departure/arrival per id — backed by the
    functional index ``idx_customer_windows_id_upper`` on ``TRIM(UPPER(id))``
    (created 2026-06-02). The aggregate (not LIMIT 1) keeps the original
    MAX-of-non-sentinel semantics so a 1900 placeholder row never wins, and the
    single-row aggregate can't fan out the order list. Replaces the prior
    full-table pre-agg CTE that scanned all ~195k window rows every call
    (SPEC-CODE-RULES §42 chose that only because the index was missing).
    Sentinel 1900/1899 placeholder dates are guarded to NULL.
    """
    pool = get_datalake_gold_pool(request)
    scope = scope_of(request)
    s, e = _resolve_range(range, start_date, end_date)
    order_by = _BY_ORDER_SORTS.get(sort, _BY_ORDER_SORTS["revenue_desc"])
    losses_clause = " AND br4.margin_amt < 0" if losses_only else ""
    # Bruno (PDF 2026-07-13): "Unbilled" button → bill_date < sentinel.
    unbilled_clause = " AND br4.bill_date < '2000-01-01'::date" if unbilled_only else ""

    rows_params: list = []
    where_rows = _v4_scope_where("br4", team, customer, load_type, rows_params, lanes, exclude_lanes, carriers, exclude_carriers, scope=scope)
    rows_params.extend([s, e, limit])
    p_s = len(rows_params) - 2
    p_e = len(rows_params) - 1
    p_lim = len(rows_params)
    rows_sql = f"""
        WITH otp AS ({_scorecard_cte("otp", scope)}),
             otd AS ({_scorecard_cte("otd", scope)})
        SELECT
          TRIM(br4.id)        AS order_id,
          TRIM(br4.team_id)   AS team_id,
          TRIM(br4.status)    AS status,
          to_char(br4.origin_actual_departure, 'YYYY-MM-DD') AS departure,
          br4.customer_name   AS customer_name,
          COALESCE(TRIM(mov.payee_name), '') AS carrier,
          NULLIF(TRIM(COALESCE(br4.origin_name,'')) || ' - ' || TRIM(COALESCE(br4.dest_name,'')), ' - ') AS lane,
          COALESCE(br4.total_charge, 0)::numeric AS revenue,
          COALESCE(br4.margin_amt, 0)::numeric   AS profit,
          CASE WHEN br4.total_charge IS NOT NULL AND br4.total_charge <> 0
               THEN br4.margin_amt / br4.total_charge * 100.0 ELSE 0 END AS margin,
          CASE WHEN COALESCE(otp.scorecard_count_otp, 0) = 0 THEN 100.0 ELSE 0.0 END AS otp_pct,
          CASE WHEN COALESCE(otd.scorecard_count_otd, 0) = 0 THEN 100.0 ELSE 0.0 END AS otd_pct,
          to_char(win.dep_ts, 'YYYY-MM-DD"T"HH24:MI:SS') AS departed_at,
          to_char(win.arr_ts, 'YYYY-MM-DD"T"HH24:MI:SS') AS arrived_at,
          CASE WHEN win.dep_ts IS NOT NULL AND win.arr_ts IS NOT NULL AND win.arr_ts > win.dep_ts
               THEN EXTRACT(EPOCH FROM (win.arr_ts - win.dep_ts)) END AS transit_seconds,
          -- Bruno round (2026-07-01) R11: Bill checkmark + Days to Bill.
          (br4.bill_date > '2000-01-01'::date) AS billed,
          CASE
            WHEN win.dest_dep_ts IS NULL THEN NULL
            WHEN br4.bill_date > '2000-01-01'::date
                 THEN (br4.bill_date::date - win.dest_dep_ts::date)
            ELSE (CURRENT_DATE - win.dest_dep_ts::date)
          END AS days_to_bill,
          -- Bruno (PDF 2026-07-15) R14: POD Age — hours since delivery (dest
          -- arrival, falling back to dest departure). Frontend shows it only for
          -- orders lacking a POD; <24h green, >24h red. CST session → CST now.
          CASE WHEN COALESCE(win.arr_ts, win.dest_dep_ts) IS NOT NULL
               THEN EXTRACT(EPOCH FROM (CURRENT_TIMESTAMP - COALESCE(win.arr_ts, win.dest_dep_ts))) / 3600.0
          END AS pod_age_hours
        FROM public.mcleod_gld_budget_report_v4 br4
        LEFT JOIN otp ON TRIM(br4.id)=otp.id_key AND TRIM(br4.company_id)=otp.company_id_key
        LEFT JOIN otd ON TRIM(br4.id)=otd.id_key AND TRIM(br4.company_id)=otd.company_id_key
        LEFT JOIN LATERAL (
            SELECT MAX(CASE WHEN cw.orig_actual_departure > '2000-01-01' THEN cw.orig_actual_departure END) AS dep_ts,
                   MAX(CASE WHEN cw.dest_actual_arrival   > '2000-01-01' THEN cw.dest_actual_arrival   END) AS arr_ts,
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
        WHERE {where_rows}
          AND br4.origin_actual_departure >= ${p_s}
          AND br4.origin_actual_departure < (${p_e}::date + INTERVAL '1 day')
          {losses_clause}
          {unbilled_clause}
        ORDER BY {order_by}
        LIMIT ${p_lim}
    """

    tot_params: list = []
    where_tot = _v4_scope_where("br4", team, customer, load_type, tot_params, lanes, exclude_lanes, carriers, exclude_carriers, scope=scope)
    tot_params.extend([s, e])
    t_s = len(tot_params) - 1
    t_e = len(tot_params)
    tot_sql = f"""
        SELECT
          COUNT(*)                               AS n_orders,
          COALESCE(SUM(br4.total_charge), 0)::numeric AS rev,
          COALESCE(SUM(br4.margin_amt), 0)::numeric   AS prof
        FROM public.mcleod_gld_budget_report_v4 br4
        WHERE {where_tot}
          AND br4.origin_actual_departure >= ${t_s}
          AND br4.origin_actual_departure < (${t_e}::date + INTERVAL '1 day')
          {losses_clause}
          {unbilled_clause}
    """

    rows, tot_row = await asyncio.gather(
        pool.fetch(rows_sql, *rows_params),
        pool.fetchrow(tot_sql, *tot_params),
    )

    out = []
    for r in rows:
        departed_at = r["departed_at"]
        arrived_at = r["arrived_at"]
        status = (r["status"] or "").strip().upper()
        # In transit = open 'P' load that departed but hasn't arrived yet.
        in_progress = status == "P" and not arrived_at and bool(departed_at)
        ts = r["transit_seconds"]
        dtb = r["days_to_bill"]
        out.append({
            "order_id":      r["order_id"],
            "team_id":       r["team_id"],
            "status":        status,
            "departure":     r["departure"] or "",
            "customer_name": r["customer_name"] or "",
            "carrier":       r["carrier"] or "",
            "lane":          r["lane"] or "",
            "revenue":       _safe_float(r["revenue"]),
            "profit":        _safe_float(r["profit"]),
            "margin_pct":    _safe_float(r["margin"]),
            "otp_pct":       _safe_float(r["otp_pct"]),
            "otd_pct":       _safe_float(r["otd_pct"]),
            "departed_at":   departed_at,
            "arrived_at":    arrived_at,
            "transit_seconds": _safe_float(ts) if ts is not None else None,
            "in_progress":   in_progress,
            "billed":        bool(r["billed"]),
            "days_to_bill":  int(dtb) if dtb is not None else None,
            "pod_age_hours": _safe_float(r["pod_age_hours"]) if r["pod_age_hours"] is not None else None,
        })

    # Bruno (PDF 2026-07-13): POD indicator — tick orders that already have a
    # POD Tracker document. The POD Tracker lives in the AP_module DB
    # (unilink_portal_ap.pod_tracker_loads, has_pod flag) — a SEPARATE Postgres
    # server, so it can't be JOINed into the datalake query. Look the fetched
    # page's order ids up in one bounded extra query and set a boolean. Degrades
    # to pod=False (never 503s the whole table) if the AP pool is unavailable —
    # POD is a supplementary indicator, not core production data. NOTE: the
    # tracker is a synced D/P snapshot, so orders outside its sync scope read
    # False even if physically documented.
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
            # Intentional non-fatal degradation: a down/misconfigured AP DB
            # must not break the By Order table — fall back to pod=False.
            pod_set = set()
    for r in out:
        r["pod"] = bool(r["order_id"]) and r["order_id"].upper() in pod_set

    t_rev = _safe_float(tot_row["rev"]) if tot_row else 0.0
    t_prof = _safe_float(tot_row["prof"]) if tot_row else 0.0
    totals = {
        "n_orders": int(tot_row["n_orders"] or 0) if tot_row else 0,
        "revenue":  t_rev,
        "profit":   t_prof,
        "margin_pct": _safe_float((t_prof / t_rev * 100.0) if t_rev else 0.0),
    }

    return {
        "success": True,
        "data": out,
        "meta": {
            "window": {"start": s.isoformat(), "end": e.isoformat()},
            "total": totals["n_orders"],
            "returned": len(out),
            "limit": limit,
            "totals": totals,
        },
    }


# ---------------------------------------------------------------------------
# /pending-to-cover — Bruno (PDF 2026-07-15) R16: status='A' loads with no
# carrier assigned yet ("Pending to Cover" toggle in the By Order panel).
# ---------------------------------------------------------------------------


@router.get("/pending-to-cover")
async def pending_to_cover(
    request: Request,
    team: Optional[str] = Query(None),
    customer: Optional[str] = Query(None),
    lanes: Optional[List[str]] = Query(None),
    exclude_lanes: Optional[List[str]] = Query(None),
    limit: int = Query(500, ge=1, le=2000),
    _user: dict = Depends(require_report_access("ops-portal-overview")),
):
    """Orders that still need a carrier: ``status = 'A'`` AND no carrier assigned
    (first-movement ``payee_name`` empty), in the CORP universe.

    Columns (Bruno R16): Order=id · Team=team_id · Customer=customer_name
    (Bruno PDF 2026-07-30 R2, between Team and Orig Sched Early) · Orig Sched
    Early/Late from
    ``mcleod_gld_customer_windows`` (``orig_orig_sched_early`` / ``orig_orig_sched_late``,
    §42 correlated LATERAL on ``TRIM(UPPER(id))``, sentinel-guard >2000) · Lane ·
    Revenue=total_charge · Time to Cover = Orig Sched Late − now (hours remaining;
    frontend colours >48h green / 24-48h amber / <24h red). Not date-windowed —
    these are the currently-open uncovered loads; ordered by the soonest deadline.
    ``status='A'`` is outside the D/P universe of ``_v4_scope_where``, so scope is
    built inline here.
    """
    pool = get_datalake_gold_pool(request)
    scope = scope_of(request)

    teams_param = _pad_variants(scope.base_teams, width=8)
    companies_param = _pad_variants(CORP_COMPANIES, width=4)
    status_param = _pad_variants(("A",), width=1)
    params: list = [teams_param, companies_param, status_param]
    parts = [
        "br4.team_id    = ANY($1)",
        "br4.company_id = ANY($2)",
        "br4.status     = ANY($3)",
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
          TRIM(br4.id)      AS order_id,
          TRIM(br4.team_id) AS team_id,
          br4.customer_name AS customer_name,
          NULLIF(TRIM(COALESCE(br4.origin_name,'')) || ' - ' || TRIM(COALESCE(br4.dest_name,'')), ' - ') AS lane,
          COALESCE(br4.total_charge, 0)::numeric AS revenue,
          to_char(win.sched_early, 'YYYY-MM-DD"T"HH24:MI:SS') AS orig_sched_early,
          to_char(win.sched_late,  'YYYY-MM-DD"T"HH24:MI:SS') AS orig_sched_late,
          CASE WHEN win.sched_late IS NOT NULL
               THEN EXTRACT(EPOCH FROM (win.sched_late - CURRENT_TIMESTAMP)) / 3600.0
          END AS time_to_cover_hours
        FROM public.mcleod_gld_budget_report_v4 br4
        LEFT JOIN LATERAL (
            SELECT MAX(CASE WHEN cw.orig_orig_sched_early > '2000-01-01' THEN cw.orig_orig_sched_early END) AS sched_early,
                   MAX(CASE WHEN cw.orig_orig_sched_late  > '2000-01-01' THEN cw.orig_orig_sched_late  END) AS sched_late
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
          AND COALESCE(TRIM(mov.payee_name), '') = ''
        ORDER BY win.sched_late ASC NULLS LAST
        LIMIT ${p_lim}
    """

    rows = await pool.fetch(sql, *params)
    out = [
        {
            "order_id":            r["order_id"],
            "team_id":             r["team_id"],
            "customer_name":       r["customer_name"] or "",
            "lane":                r["lane"] or "",
            "revenue":             _safe_float(r["revenue"]),
            "orig_sched_early":    r["orig_sched_early"],
            "orig_sched_late":     r["orig_sched_late"],
            "time_to_cover_hours": _safe_float(r["time_to_cover_hours"]) if r["time_to_cover_hours"] is not None else None,
        }
        for r in rows
    ]
    return {"success": True, "data": out, "meta": {"returned": len(out), "limit": limit}}


@router.get("/cover")
async def cover(
    request: Request,
    team: Optional[str] = Query(None),
    customer: Optional[str] = Query(None),
    lanes: Optional[List[str]] = Query(None),
    exclude_lanes: Optional[List[str]] = Query(None),
    limit: int = Query(500, ge=1, le=2000),
    _user: dict = Depends(require_report_access("ops-portal-overview")),
):
    """All ``status = 'A'`` loads in the CORP universe — the open coverage board.

    Columns (Bruno PDF 2026-07-20 R1): Order=id · Team=team_id ·
    Customer=customer_name · Carrier · Carrier Phone · Orig Sched Early/Late ·
    Lane · Revenue=total_charge · Profit=margin_amt.

    Bruno (PDF 2026-07-30) R3 — the schedule pair is re-cut and the money block
    is widened:

    * ``orig_sched_late`` is sourced from ``cw.orig_orig_sched_late`` and is now
      labelled **"Orig Orig Late"** in the UI — the wire name is intentionally
      left alone (§34: no mid-flight rename), only the label moved.
    * NEW ``orig_sched_arrive_late`` (``cw.orig_sched_arrive_late``) carries the
      label **"Orig Sched Late"**. It is the better deadline field: populated on
      157/166 CORP status='A' rows (94.6%) vs 108/166 (65%) for
      ``orig_orig_sched_late`` — measured 2026-07-30. The board's ``ORDER BY``
      moves to it for the same reason; ordering on the sparser column pushed a
      third of the rows into a NULLS-LAST block.
    * NEW ``carrier_cost`` = ``total_carrier_pay``. Verified against the
      identity ``total_charge − margin_amt``: exact on 158/166 rows, max gap
      $1.00 (McLeod rounding), so this is the real cost field.
    * NEW ``margin_pct`` = profit / revenue × 100, computed here rather than
      read from ``br4.margin_prcnt`` so the column always agrees with the
      Revenue / Profit shown beside it (§16).
    * Orig Sched Early is dropped from the UI only — the wire field stays.

    Design notes (all verified against the datalake 2026-07-20):

    * **Not date-windowed**, exactly like /pending-to-cover. ``status='A'`` is a
      live open-orders board that drains as loads move to D/V — 121 rows in the
      CORP scope, essentially all in the current month, with only 1-5 stragglers
      in any prior month. Windowing it would return ~0 rows the moment the user
      picked "Last Month", which defeats the purpose of a coverage board.
    * **Carrier, driver name and phone all come from the first movement** (§5
      LATERAL LIMIT 1;
      ``movement`` fans out to max 5 rows per A-order). ``budget_report_v4`` has
      no carrier column at all. ``mcleod_gld_dispatchers.carrier_name`` was
      evaluated as a fallback and rejected: it adds only 4 of 121 carrier names
      (+3%) but its ``id`` is the *second* PK column
      (PK = movement_id, id, company_id), so neither ``TRIM(UPPER(d.id))`` nor a
      raw ``d.id =`` lookup is sargable — it would seq-scan 209k rows per order.
      Sourcing name and phone from the same row also guarantees they agree.
      A blank carrier here legitimately means "not covered yet".
    * **Driver name / phone (Bruno PDF 2026-08-12).** ``driver_name`` =
      ``override_driver_nm``; the "Carrier Phone" column now renders
      ``override_drvr_cell`` instead of ``carrier_phone``. Measured on the live
      112-covered-load board: carrier_phone 59/112, override_drvr_cell 26/112,
      override_driver_nm 28/112 — the swap is a deliberate net loss of ~40
      displayed numbers, requested explicitly. Verified that **no** covered
      order carries driver data only on a *later* movement, so the existing
      first-movement pin costs nothing. The ``company_id`` predicate is kept
      even though the request said "join on order_id": 6 covered orders' order_id
      exists under two company_ids, and dropping it would pick the wrong row.
      Both columns are free text in McLeod ("TBD", "x", "will advise" all
      occur), so the frontend must not assume a dialable number.
    * ``orig_orig_sched_early/late`` carry **1900-01-01 sentinels, not NULL**, so
      both are guarded ``> '2000-01-01'`` (§42 correlated LATERAL on
      ``TRIM(UPPER(id))``; customer_windows is clean order-grain, max 1 row/id).
    * ``status='A'`` sits outside the D/P universe of ``_v4_scope_where``, so the
      scope is built inline here — same as /pending-to-cover.
    """
    pool = get_datalake_gold_pool(request)
    scope = scope_of(request)

    teams_param = _pad_variants(scope.base_teams, width=8)
    companies_param = _pad_variants(CORP_COMPANIES, width=4)
    status_param = _pad_variants(("A",), width=1)
    params: list = [teams_param, companies_param, status_param]
    parts = [
        "br4.team_id    = ANY($1)",
        "br4.company_id = ANY($2)",
        "br4.status     = ANY($3)",
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
          TRIM(br4.id)      AS order_id,
          TRIM(br4.team_id) AS team_id,
          br4.customer_name AS customer_name,
          COALESCE(TRIM(mov.payee_name), '')         AS carrier,
          COALESCE(TRIM(mov.override_driver_nm), '')  AS driver_name,
          -- Bruno PDF 2026-08-12 R1: the phone shown on the Cover board is the
          -- DRIVER's cell (movement.override_drvr_cell), not movement.carrier_phone.
          -- The wire field keeps its old name because the on-screen column is
          -- still "Carrier Phone" — only the source column moved (§34 inverted).
          COALESCE(TRIM(mov.override_drvr_cell), '')  AS carrier_phone,
          to_char(win.sched_early, 'YYYY-MM-DD"T"HH24:MI:SS') AS orig_sched_early,
          to_char(win.sched_late,  'YYYY-MM-DD"T"HH24:MI:SS') AS orig_sched_late,
          to_char(win.arrive_late, 'YYYY-MM-DD"T"HH24:MI:SS') AS orig_sched_arrive_late,
          NULLIF(TRIM(COALESCE(br4.origin_name,'')) || ' - ' || TRIM(COALESCE(br4.dest_name,'')), ' - ') AS lane,
          COALESCE(br4.total_charge, 0)::numeric      AS revenue,
          COALESCE(br4.total_carrier_pay, 0)::numeric AS carrier_cost,
          COALESCE(br4.margin_amt, 0)::numeric        AS profit,
          -- §44 pinned-Totals + truncation signal. Window aggregates are
          -- evaluated after WHERE but BEFORE LIMIT, so these describe the FULL
          -- universe even when the row list is capped. The money totals are
          -- FILTERed to carrier-assigned rows because that is exactly the subset
          -- the Cover board renders (§16 KPI = detail).
          COUNT(*) OVER ()                                            AS n_all,
          COUNT(*) FILTER (WHERE {_ASSIGNED}) OVER ()                 AS n_covered,
          COALESCE(SUM(COALESCE(br4.total_charge,0))      FILTER (WHERE {_ASSIGNED}) OVER (), 0)::numeric AS t_revenue,
          COALESCE(SUM(COALESCE(br4.total_carrier_pay,0)) FILTER (WHERE {_ASSIGNED}) OVER (), 0)::numeric AS t_carrier_cost,
          COALESCE(SUM(COALESCE(br4.margin_amt,0))        FILTER (WHERE {_ASSIGNED}) OVER (), 0)::numeric AS t_profit
        FROM public.mcleod_gld_budget_report_v4 br4
        LEFT JOIN LATERAL (
            SELECT MAX(CASE WHEN cw.orig_orig_sched_early > '2000-01-01' THEN cw.orig_orig_sched_early END) AS sched_early,
                   MAX(CASE WHEN cw.orig_orig_sched_late  > '2000-01-01' THEN cw.orig_orig_sched_late  END) AS sched_late,
                   MAX(CASE WHEN cw.orig_sched_arrive_late > '2000-01-01' THEN cw.orig_sched_arrive_late END) AS arrive_late
            FROM public.mcleod_gld_customer_windows cw
            WHERE TRIM(UPPER(cw.id)) = TRIM(UPPER(br4.id))
        ) win ON TRUE
        LEFT JOIN LATERAL (
            SELECT m.payee_name, m.override_driver_nm, m.override_drvr_cell
            FROM public.mcleod_gld_movement m
            WHERE m.order_id = br4.id AND m.company_id = br4.company_id
            ORDER BY m.movement_id ASC
            LIMIT 1
        ) mov ON TRUE
        WHERE {where}
        ORDER BY win.arrive_late ASC NULLS LAST
        LIMIT ${p_lim}
    """

    rows = await pool.fetch(sql, *params)
    # §44: the pinned Totals row and the "showing N of M" caption both read the
    # server-side full-universe aggregate carried on every row, never a client
    # reduce() over the (possibly LIMIT-capped) list.
    n_all = int(rows[0]["n_all"]) if rows else 0
    n_covered = int(rows[0]["n_covered"]) if rows else 0
    t_revenue = _safe_float(rows[0]["t_revenue"]) if rows else 0.0
    t_profit = _safe_float(rows[0]["t_profit"]) if rows else 0.0
    totals = {
        "n_orders":     n_covered,
        "revenue":      t_revenue,
        "carrier_cost": _safe_float(rows[0]["t_carrier_cost"]) if rows else 0.0,
        "profit":       t_profit,
        "margin_pct":   (t_profit / t_revenue * 100.0) if t_revenue else 0.0,
    }
    out = []
    for r in rows:
        revenue = _safe_float(r["revenue"])
        profit = _safe_float(r["profit"])
        out.append({
            "order_id":               r["order_id"],
            "team_id":                r["team_id"],
            "customer_name":          r["customer_name"] or "",
            "carrier":                r["carrier"],
            "driver_name":            r["driver_name"],
            "carrier_phone":          r["carrier_phone"],
            "orig_sched_early":       r["orig_sched_early"],
            "orig_sched_late":        r["orig_sched_late"],
            "orig_sched_arrive_late": r["orig_sched_arrive_late"],
            "lane":                   r["lane"] or "",
            "revenue":                revenue,
            "carrier_cost":           _safe_float(r["carrier_cost"]),
            "profit":                 profit,
            "margin_pct":             (profit / revenue * 100.0) if revenue else 0.0,
        })
    return {
        "success": True,
        "data": out,
        "meta": {
            "returned": len(out),
            "limit": limit,
            # Full status='A' universe vs the carrier-assigned subset the board
            # renders. `returned < total` is the truncation signal the UI shows.
            "total": n_all,
            "covered": n_covered,
            "totals": totals,
        },
    }
