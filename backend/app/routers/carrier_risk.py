"""Code-made report: Carrier Risk Assessment.

Mirrors Bruno's PDF spec ("BRUNO - Carrier Risk Assessment") which was a
Qlik app on the legacy ``unilink.us`` tenant (app id ``d7b9deb0-…``,
not embeddable from the portal tenant — same situation as Track Award
Loads / RFP Performance / HR Access Doors). Drives a 4-pill filter
(Date, Lane, Customer, Team) over the dispatchers query:

    SELECT d.*, b.total_charge, b.margin_amt, ...
    FROM   mcleod_gld_dispatchers d
    LEFT JOIN mcleod_gld_budget_report_v4 b
           ON d.id = b.id AND d.company_id = b.company_id
    WHERE  d.team_id     IN (TEAM1..TEAM5, TEAM-DFW)
      AND  d.company_id  IN (TMS, TMS3)
      AND  d.status      IN (D, P)
      AND  d.carrier_name <> 'DUMMY TRANSPORTATION'
      AND  (d.override_pay_amt + d.driver_extra_pay) <> 0

`carrier_cost` is NOT a column in the dispatchers table — Bruno's Qlik
load script computes it as ``override_pay_amt + driver_extra_pay``.
Verified on 2026-04-28 by matching Bruno's $1,372 grand-total avg
exactly (avg of override_pay_amt + driver_extra_pay over the 150,481
in-scope rows = $1,372.45). ``b.total_carrier_pay`` averages $1,485 —
do not use it. The v4 LEFT JOIN is only needed for the order-level
Details panel (Revenue / Profit / % Margin); the Lane / Carrier+Lane
panels read dispatchers alone, which is faster.

This is the **first portal report to read mcleod_gld_dispatchers**, so
mind the column widths: team_id varchar(8), company_id varchar(4),
status varchar(1) (same widths as v4). Always use the padded-variants
pattern; never TRIM() in WHERE/JOIN.

Concentration metrics on the by-Lane panel (added on top of Bruno's
flat # Carrier / Avg Carrier Cost):

* ``top1_share``  — share of moves handled by the dominant carrier
* ``hhi``         — Herfindahl-Hirschman index (0–10000) of carrier
                    shares; >2500 = highly concentrated
* ``cv_cost``     — coefficient of variation of per-carrier avg cost
                    on the lane (low = no negotiation room)
* ``risk_band``   — red if (n_carrier=1 AND n_mov>=5),
                    amber if (top1_share>=0.7 AND n_mov>=10),
                    green otherwise
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, Query, Request

from app.clock import cst_today
from app.datalake import pad_variants as _pad_variants
from app.routers.deps import get_datalake_gold_pool, require_tag_role

CARRIER_RISK_ROLES = (
    "CEO",
    "Executive",
    "Procurement",
    "CORP",
    "DFW",
    "Operations",
    "Finance",
)

# Soft year floor — dispatchers data goes back to 2014, but realistically
# nobody is running carrier-risk reports on 5-year-old data. Ignore noise
# rows like the lone 1900-01-01 outlier we found while probing.
YEAR_FLOOR = date(2024, 1, 1)

ALL_TEAMS = ("TEAM1", "TEAM2", "TEAM3", "TEAM4", "TEAM5", "TEAM-DFW")
COMPANIES = ("TMS", "TMS3")
OPEN_STATUSES = ("D", "P")

router = APIRouter(tags=["carrier-risk"], prefix="/custom/carrier-risk")


# ---------------------------------------------------------------------------
# Date / filter helpers
# ---------------------------------------------------------------------------


def _today_clamped() -> date:
    today = cst_today()
    return max(YEAR_FLOOR, today)


def _month_bounds(today: date) -> tuple[date, date, date, date]:
    m_start = today.replace(day=1)
    if m_start.month == 12:
        m_end = m_start.replace(year=m_start.year + 1, month=1) - timedelta(days=1)
    else:
        m_end = m_start.replace(month=m_start.month + 1) - timedelta(days=1)
    lm_end = m_start - timedelta(days=1)
    lm_start = lm_end.replace(day=1)
    return m_start, m_end, lm_start, lm_end


def _clamp(d: Optional[date], default: date) -> date:
    if d is None:
        return default
    if d < YEAR_FLOOR:
        return YEAR_FLOOR
    today = _today_clamped()
    if d > today:
        return today
    return d


def _resolve_range(
    rng: Optional[str],
    start_date: Optional[date],
    end_date: Optional[date],
) -> tuple[date, date]:
    """Expand the preset range selector into a concrete [start, end] pair."""
    today = _today_clamped()
    m_start, _m_end, lm_start, lm_end = _month_bounds(today)
    if rng == "last_month":
        return _clamp(lm_start, lm_start), _clamp(lm_end, lm_end)
    if rng == "last_3m":
        return _clamp(today - timedelta(days=90), today - timedelta(days=90)), today
    if rng in ("ytd", "this_year"):
        ys = date(today.year, 1, 1)
        return _clamp(ys, ys), today
    if rng == "custom":
        s = _clamp(start_date, m_start)
        e = _clamp(end_date, today)
        if e < s:
            s, e = e, s
        return s, e
    # default: MTD (1st of month → today)
    return _clamp(m_start, m_start), today


def _parse_teams(teams: Optional[str]) -> list[str]:
    if not teams:
        return list(ALL_TEAMS)
    wanted = [t.strip() for t in teams.split(",") if t.strip()]
    allowed = {t for t in ALL_TEAMS}
    return [t for t in wanted if t in allowed] or list(ALL_TEAMS)


# Lane label expression — kept identical to Bruno's:
#   concat(trim(origin_city),', ',trim(origin_state),' - ',trim(dest_city),', ',trim(dest_state))
# Wrapping origin_city_name in TRIM() inside SELECT is fine; the sargability
# rule is about WHERE/JOIN, not output columns.
LANE_EXPR = (
    "TRIM({a}.origin_city_name) || ',' || TRIM({a}.origin_state_id) || ' - ' || "
    "TRIM({a}.dest_city_name) || ',' || TRIM({a}.dest_state_id)"
)


def _scope_where(
    alias: str,
    teams: list[str],
    customer: Optional[str],
    lane: Optional[str],
    params: list,
) -> str:
    """Build the shared WHERE fragment for the dispatchers table.

    Padded-variant ``= ANY($N)`` predicates keep btree indexes usable.
    Customer / lane filters are exact-match (not LIKE) for speed; the
    UI feeds them from the /facets endpoint so values are canonical.
    """
    params.append(_pad_variants(teams, width=8))
    p_teams = len(params)
    params.append(_pad_variants(COMPANIES, width=4))
    p_companies = len(params)
    params.append(_pad_variants(OPEN_STATUSES, width=1))
    p_status = len(params)

    parts = [
        f"{alias}.team_id    = ANY(${p_teams})",
        f"{alias}.company_id = ANY(${p_companies})",
        f"{alias}.status     = ANY(${p_status})",
        f"{alias}.carrier_name <> 'DUMMY TRANSPORTATION'",
        f"({alias}.override_pay_amt + {alias}.driver_extra_pay) <> 0",
        f"UPPER(COALESCE({alias}.customer_name,'')) NOT LIKE '%UNILINK%'",
        f"UPPER(COALESCE({alias}.customer_name,'')) NOT LIKE '%OILTEX%'",
        f"{alias}.origin_actual_departure IS NOT NULL",
    ]
    if customer:
        params.append(customer)
        parts.append(f"{alias}.customer_name = ${len(params)}")
    if lane:
        params.append(lane)
        parts.append(f"({LANE_EXPR.format(a=alias)}) = ${len(params)}")
    return " AND ".join(parts)


# ---------------------------------------------------------------------------
# Facets — distinct teams + customers + (top) lanes for filter dropdowns
# ---------------------------------------------------------------------------


@router.get("/facets")
async def facets(
    request: Request,
    _user: dict = Depends(require_tag_role(*CARRIER_RISK_ROLES)),
):
    """Distinct customers + top lanes (by movement count, last 12 months)."""
    pool = get_datalake_gold_pool(request)
    today = _today_clamped()
    one_year_ago = today - timedelta(days=365)

    customers_rows = await pool.fetch(
        """
        SELECT DISTINCT TRIM(customer_name) AS customer_name
        FROM   public.mcleod_gld_dispatchers
        WHERE  team_id     = ANY($1)
          AND  company_id  = ANY($2)
          AND  status      = ANY($3)
          AND  carrier_name <> 'DUMMY TRANSPORTATION'
          AND  (override_pay_amt + driver_extra_pay) <> 0
          AND  UPPER(COALESCE(customer_name,'')) NOT LIKE '%UNILINK%'
          AND  UPPER(COALESCE(customer_name,'')) NOT LIKE '%OILTEX%'
          AND  customer_name IS NOT NULL
          AND  TRIM(customer_name) <> ''
          AND  origin_actual_departure >= $4
        ORDER BY customer_name
        """,
        _pad_variants(ALL_TEAMS, width=8),
        _pad_variants(COMPANIES, width=4),
        _pad_variants(OPEN_STATUSES, width=1),
        one_year_ago,
    )

    return {
        "success": True,
        "data": {
            "teams": list(ALL_TEAMS),
            "customers": [r["customer_name"] for r in customers_rows if r["customer_name"]],
            "year_floor": YEAR_FLOOR.isoformat(),
            "today": today.isoformat(),
        },
    }


# ---------------------------------------------------------------------------
# KPIs — top of the report
# ---------------------------------------------------------------------------


@router.get("/kpis")
async def kpis(
    request: Request,
    range: Optional[str] = Query("mtd"),
    start_date: Optional[date] = Query(None),
    end_date: Optional[date] = Query(None),
    teams: Optional[str] = Query(None),
    customer: Optional[str] = Query(None),
    lane: Optional[str] = Query(None),
    _user: dict = Depends(require_tag_role(*CARRIER_RISK_ROLES)),
):
    pool = get_datalake_gold_pool(request)
    s, e = _resolve_range(range, start_date, end_date)
    team_list = _parse_teams(teams)

    params: list = []
    where = _scope_where("d", team_list, customer, lane, params)
    params.extend([s, e])
    p_s, p_e = len(params) - 1, len(params)
    date_fragment = (
        f"d.origin_actual_departure >= ${p_s} "
        f"AND d.origin_actual_departure < (${p_e}::date + 1)"
    )

    sql = f"""
    WITH base AS (
      SELECT
        {LANE_EXPR.format(a="d")} AS lane,
        d.carrier_name,
        (d.override_pay_amt + d.driver_extra_pay)::numeric AS carrier_cost,
        b.total_charge,
        b.margin_amt
      FROM public.mcleod_gld_dispatchers d
      LEFT JOIN public.mcleod_gld_budget_report_v4 b
        ON d.id = b.id AND d.company_id = b.company_id
      WHERE {where} AND {date_fragment}
    ),
    per_lane_carrier AS (
      SELECT lane, carrier_name, COUNT(*) AS mov
      FROM base
      WHERE lane IS NOT NULL
      GROUP BY lane, carrier_name
    ),
    lane_totals AS (
      SELECT lane,
             SUM(mov)               AS n_mov,
             COUNT(*)               AS n_carrier,
             MAX(mov)::numeric / NULLIF(SUM(mov),0) AS top1_share
      FROM per_lane_carrier
      GROUP BY lane
    )
    SELECT
      (SELECT COUNT(*) FROM base)                                   AS movements,
      (SELECT COUNT(DISTINCT carrier_name) FROM base)               AS distinct_carriers,
      (SELECT COUNT(*) FROM lane_totals)                            AS distinct_lanes,
      (SELECT AVG(carrier_cost) FROM base)::numeric                 AS avg_carrier_cost,
      (SELECT COALESCE(SUM(total_charge),0) FROM base)::numeric     AS revenue,
      (SELECT COALESCE(SUM(margin_amt),0)  FROM base)::numeric      AS profit,
      (SELECT
         CASE WHEN COALESCE(SUM(total_charge),0) > 0
              THEN SUM(margin_amt)::numeric / SUM(total_charge)::numeric
              ELSE NULL END
       FROM base)                                                   AS margin_pct,
      (SELECT
         CASE WHEN COUNT(*) > 0
              THEN COUNT(*) FILTER (WHERE n_carrier = 1)::numeric
                 / COUNT(*)::numeric
              ELSE NULL END
       FROM lane_totals)                                            AS single_carrier_lane_pct,
      (SELECT
         CASE WHEN COALESCE(SUM(n_mov),0) > 0
              THEN SUM(n_mov) FILTER (WHERE n_carrier = 1)::numeric
                 / SUM(n_mov)::numeric
              ELSE NULL END
       FROM lane_totals)                                            AS single_carrier_volume_pct
    """

    row = await pool.fetchrow(sql, *params)

    return {
        "success": True,
        "data": {
            "movements": int(row["movements"] or 0),
            "distinct_carriers": int(row["distinct_carriers"] or 0),
            "distinct_lanes": int(row["distinct_lanes"] or 0),
            "avg_carrier_cost": float(row["avg_carrier_cost"]) if row["avg_carrier_cost"] is not None else 0.0,
            "revenue": float(row["revenue"] or 0),
            "profit": float(row["profit"] or 0),
            "margin_pct": float(row["margin_pct"]) * 100.0 if row["margin_pct"] is not None else None,
            "single_carrier_lane_pct": float(row["single_carrier_lane_pct"]) * 100.0
                if row["single_carrier_lane_pct"] is not None else None,
            "single_carrier_volume_pct": float(row["single_carrier_volume_pct"]) * 100.0
                if row["single_carrier_volume_pct"] is not None else None,
            "window": {"start": s.isoformat(), "end": e.isoformat()},
            "teams_applied": team_list,
        },
    }


# ---------------------------------------------------------------------------
# By Lane — # Carrier / # Mov / Avg Carrier Cost + concentration risk
# ---------------------------------------------------------------------------

_LANE_SORTS = {
    "n_mov_desc": "n_mov DESC NULLS LAST",
    "n_mov_asc": "n_mov ASC NULLS LAST",
    "n_carrier_desc": "n_carrier DESC NULLS LAST",
    "n_carrier_asc": "n_carrier ASC NULLS LAST",
    "avg_cost_desc": "avg_cost DESC NULLS LAST",
    "avg_cost_asc": "avg_cost ASC NULLS LAST",
    "top1_share_desc": "top1_share DESC NULLS LAST",
    "hhi_desc": "hhi DESC NULLS LAST",
    "margin_pct_asc": "margin_pct ASC NULLS LAST",
    "margin_pct_desc": "margin_pct DESC NULLS LAST",
    "lane_asc": "lane ASC",
}


@router.get("/by-lane")
async def by_lane(
    request: Request,
    range: Optional[str] = Query("mtd"),
    start_date: Optional[date] = Query(None),
    end_date: Optional[date] = Query(None),
    teams: Optional[str] = Query(None),
    customer: Optional[str] = Query(None),
    sort: str = Query("n_mov_desc"),
    page: int = Query(1, ge=1),
    limit: int = Query(50, ge=1, le=500),
    _user: dict = Depends(require_tag_role(*CARRIER_RISK_ROLES)),
):
    pool = get_datalake_gold_pool(request)
    s, e = _resolve_range(range, start_date, end_date)
    team_list = _parse_teams(teams)
    offset = (page - 1) * limit
    order_by = _LANE_SORTS.get(sort, "n_mov DESC NULLS LAST")

    params: list = []
    where = _scope_where("d", team_list, customer, None, params)
    params.extend([s, e])
    p_s, p_e = len(params) - 1, len(params)
    date_fragment = (
        f"d.origin_actual_departure >= ${p_s} "
        f"AND d.origin_actual_departure < (${p_e}::date + 1)"
    )
    params.extend([limit, offset])
    p_lim, p_off = len(params) - 1, len(params)

    sql = f"""
    WITH base AS (
      SELECT
        {LANE_EXPR.format(a="d")} AS lane,
        d.carrier_name,
        (d.override_pay_amt + d.driver_extra_pay)::numeric AS carrier_cost,
        b.total_charge,
        b.margin_amt
      FROM public.mcleod_gld_dispatchers d
      LEFT JOIN public.mcleod_gld_budget_report_v4 b
        ON d.id = b.id AND d.company_id = b.company_id
      WHERE {where} AND {date_fragment}
    ),
    per_carrier AS (
      SELECT
        lane,
        carrier_name,
        COUNT(*)                                         AS mov,
        SUM(carrier_cost)                                AS cost_sum,
        SUM(total_charge)                                AS rev_sum,
        SUM(margin_amt)                                  AS prof_sum
      FROM base
      WHERE lane IS NOT NULL
      GROUP BY lane, carrier_name
    ),
    lane_totals AS (
      SELECT lane, SUM(mov) AS n_mov, COUNT(*) AS n_carrier
      FROM per_carrier
      GROUP BY lane
    ),
    agg AS (
      SELECT
        lt.lane,
        lt.n_mov,
        lt.n_carrier,
        SUM(pc.cost_sum)::numeric / NULLIF(lt.n_mov,0)              AS avg_cost,
        MAX(pc.mov)::numeric        / NULLIF(lt.n_mov,0)            AS top1_share,
        SUM( (pc.mov::numeric / NULLIF(lt.n_mov,0) * 100) ^ 2 )     AS hhi,
        AVG(pc.cost_sum / NULLIF(pc.mov,0))::numeric                AS mean_carrier_cost,
        STDDEV_POP(pc.cost_sum / NULLIF(pc.mov,0))                  AS sd_carrier_cost,
        SUM(pc.rev_sum)::numeric                                    AS revenue,
        SUM(pc.prof_sum)::numeric                                   AS profit,
        CASE WHEN SUM(pc.rev_sum) IS NOT NULL AND SUM(pc.rev_sum) <> 0
             THEN SUM(pc.prof_sum)::numeric / SUM(pc.rev_sum)::numeric
             ELSE NULL END                                          AS margin_pct
      FROM per_carrier pc
      JOIN lane_totals lt USING (lane)
      GROUP BY lt.lane, lt.n_mov, lt.n_carrier
    )
    SELECT
      lane,
      n_mov,
      n_carrier,
      avg_cost,
      top1_share,
      hhi,
      CASE WHEN mean_carrier_cost IS NOT NULL AND mean_carrier_cost > 0
           THEN sd_carrier_cost / mean_carrier_cost
           ELSE NULL END AS cv_cost,
      margin_pct,
      revenue,
      profit,
      COUNT(*) OVER() AS total_count
    FROM agg
    ORDER BY {order_by}
    LIMIT ${p_lim} OFFSET ${p_off}
    """

    rows = await pool.fetch(sql, *params)
    total = int(rows[0]["total_count"]) if rows else 0

    def _band(n_carrier: int, n_mov: int, top1_share: Optional[float]) -> str:
        if n_carrier == 1 and n_mov >= 5:
            return "red"
        if top1_share is not None and top1_share >= 0.7 and n_mov >= 10:
            return "amber"
        return "green"

    data = []
    for r in rows:
        n_mov = int(r["n_mov"] or 0)
        n_carrier = int(r["n_carrier"] or 0)
        top1 = float(r["top1_share"]) if r["top1_share"] is not None else None
        margin = float(r["margin_pct"]) * 100.0 if r["margin_pct"] is not None else None
        data.append({
            "lane": r["lane"],
            "n_mov": n_mov,
            "n_carrier": n_carrier,
            "avg_cost": float(r["avg_cost"]) if r["avg_cost"] is not None else 0.0,
            "top1_share": top1,
            "hhi": float(r["hhi"]) if r["hhi"] is not None else None,
            "cv_cost": float(r["cv_cost"]) if r["cv_cost"] is not None else None,
            "margin_pct": margin,
            "revenue": float(r["revenue"] or 0),
            "profit": float(r["profit"] or 0),
            "risk_band": _band(n_carrier, n_mov, top1),
        })

    return {
        "success": True,
        "data": data,
        "meta": {"total": total, "page": page, "limit": limit},
    }


# ---------------------------------------------------------------------------
# By Carrier and Lane — flat pivot (carrier_name × lane × # Mov × Avg Cost)
# ---------------------------------------------------------------------------

_CARRIER_LANE_SORTS = {
    "mov_desc": "mov DESC",
    "mov_asc": "mov ASC",
    "avg_cost_desc": "avg_cost DESC NULLS LAST",
    "avg_cost_asc": "avg_cost ASC NULLS LAST",
    "carrier_asc": "carrier_name ASC, lane ASC",
    "lane_asc": "lane ASC, carrier_name ASC",
}


@router.get("/by-carrier-lane")
async def by_carrier_lane(
    request: Request,
    range: Optional[str] = Query("mtd"),
    start_date: Optional[date] = Query(None),
    end_date: Optional[date] = Query(None),
    teams: Optional[str] = Query(None),
    customer: Optional[str] = Query(None),
    lane: Optional[str] = Query(None),
    carrier: Optional[str] = Query(None),
    sort: str = Query("mov_desc"),
    page: int = Query(1, ge=1),
    limit: int = Query(50, ge=1, le=500),
    _user: dict = Depends(require_tag_role(*CARRIER_RISK_ROLES)),
):
    pool = get_datalake_gold_pool(request)
    s, e = _resolve_range(range, start_date, end_date)
    team_list = _parse_teams(teams)
    offset = (page - 1) * limit
    order_by = _CARRIER_LANE_SORTS.get(sort, "mov DESC")

    params: list = []
    where = _scope_where("d", team_list, customer, lane, params)
    params.extend([s, e])
    p_s, p_e = len(params) - 1, len(params)
    date_fragment = (
        f"d.origin_actual_departure >= ${p_s} "
        f"AND d.origin_actual_departure < (${p_e}::date + 1)"
    )
    if carrier:
        params.append(carrier)
        carrier_fragment = f"AND d.carrier_name = ${len(params)}"
    else:
        carrier_fragment = ""
    params.extend([limit, offset])
    p_lim, p_off = len(params) - 1, len(params)

    sql = f"""
    WITH base AS (
      SELECT
        d.carrier_name,
        {LANE_EXPR.format(a="d")} AS lane,
        (d.override_pay_amt + d.driver_extra_pay)::numeric AS carrier_cost
      FROM public.mcleod_gld_dispatchers d
      WHERE {where} AND {date_fragment} {carrier_fragment}
    )
    SELECT
      carrier_name,
      lane,
      COUNT(*)                                                AS mov,
      AVG(carrier_cost)::numeric                              AS avg_cost,
      COUNT(*) OVER()                                          AS total_count
    FROM base
    WHERE lane IS NOT NULL AND carrier_name IS NOT NULL
    GROUP BY carrier_name, lane
    ORDER BY {order_by}
    LIMIT ${p_lim} OFFSET ${p_off}
    """

    rows = await pool.fetch(sql, *params)
    total = int(rows[0]["total_count"]) if rows else 0
    data = [
        {
            "carrier_name": r["carrier_name"],
            "lane": r["lane"],
            "mov": int(r["mov"] or 0),
            "avg_cost": float(r["avg_cost"]) if r["avg_cost"] is not None else 0.0,
        }
        for r in rows
    ]
    return {
        "success": True,
        "data": data,
        "meta": {"total": total, "page": page, "limit": limit},
    }


# ---------------------------------------------------------------------------
# Order-level Details — joined to v4 for Revenue / Profit / % Margin
# ---------------------------------------------------------------------------

_DETAILS_SORTS = {
    "departure_desc": "actual_departure DESC NULLS LAST",
    "departure_asc": "actual_departure ASC NULLS LAST",
    "revenue_desc": "revenue DESC NULLS LAST",
    "revenue_asc": "revenue ASC NULLS LAST",
    "profit_desc": "profit DESC NULLS LAST",
    "profit_asc": "profit ASC NULLS LAST",
    "margin_desc": "margin_pct DESC NULLS LAST",
    "margin_asc": "margin_pct ASC NULLS LAST",
}


@router.get("/details")
async def details(
    request: Request,
    range: Optional[str] = Query("mtd"),
    start_date: Optional[date] = Query(None),
    end_date: Optional[date] = Query(None),
    teams: Optional[str] = Query(None),
    customer: Optional[str] = Query(None),
    lane: Optional[str] = Query(None),
    carrier: Optional[str] = Query(None),
    sort: str = Query("departure_desc"),
    page: int = Query(1, ge=1),
    limit: int = Query(100, ge=1, le=500),
    _user: dict = Depends(require_tag_role(*CARRIER_RISK_ROLES)),
):
    pool = get_datalake_gold_pool(request)
    s, e = _resolve_range(range, start_date, end_date)
    team_list = _parse_teams(teams)
    offset = (page - 1) * limit
    order_by = _DETAILS_SORTS.get(sort, "actual_departure DESC NULLS LAST")

    params: list = []
    where = _scope_where("d", team_list, customer, lane, params)
    params.extend([s, e])
    p_s, p_e = len(params) - 1, len(params)
    date_fragment = (
        f"d.origin_actual_departure >= ${p_s} "
        f"AND d.origin_actual_departure < (${p_e}::date + 1)"
    )
    if carrier:
        params.append(carrier)
        carrier_fragment = f"AND d.carrier_name = ${len(params)}"
    else:
        carrier_fragment = ""
    params.extend([limit, offset])
    p_lim, p_off = len(params) - 1, len(params)

    sql = f"""
    SELECT
      TRIM(d.id)                                               AS id,
      d.origin_actual_departure                                AS actual_departure,
      TRIM(d.customer_name)                                    AS customer,
      TRIM(d.carrier_name)                                     AS carrier_name,
      {LANE_EXPR.format(a="d")}                                AS lane,
      b.total_charge::numeric                                  AS revenue,
      b.margin_amt::numeric                                    AS profit,
      CASE WHEN b.total_charge IS NOT NULL AND b.total_charge <> 0
           THEN b.margin_amt::numeric / b.total_charge::numeric
           ELSE NULL END                                       AS margin_pct,
      COUNT(*) OVER()                                           AS total_count
    FROM public.mcleod_gld_dispatchers d
    LEFT JOIN public.mcleod_gld_budget_report_v4 b
      ON d.id = b.id AND d.company_id = b.company_id
    WHERE {where} AND {date_fragment} {carrier_fragment}
    ORDER BY {order_by}
    LIMIT ${p_lim} OFFSET ${p_off}
    """

    rows = await pool.fetch(sql, *params)
    total = int(rows[0]["total_count"]) if rows else 0
    data = [
        {
            "id": r["id"],
            "actual_departure": r["actual_departure"].isoformat() if r["actual_departure"] else None,
            "customer": r["customer"],
            "carrier_name": r["carrier_name"],
            "lane": r["lane"],
            "revenue": float(r["revenue"]) if r["revenue"] is not None else None,
            "profit": float(r["profit"]) if r["profit"] is not None else None,
            "margin_pct": float(r["margin_pct"]) * 100.0 if r["margin_pct"] is not None else None,
        }
        for r in rows
    ]
    return {
        "success": True,
        "data": data,
        "meta": {"total": total, "page": page, "limit": limit},
    }


# ---------------------------------------------------------------------------
# Lane carrier-count trend (last 8 ISO Mon-Sun weeks, current excluded)
# ---------------------------------------------------------------------------


@router.get("/lane-trend")
async def lane_trend(
    request: Request,
    lane: str = Query(..., min_length=1),
    teams: Optional[str] = Query(None),
    customer: Optional[str] = Query(None),
    _user: dict = Depends(require_tag_role(*CARRIER_RISK_ROLES)),
):
    """Distinct-carrier count and movement count per ISO week (Mon-Sun)
    over the last 8 completed weeks for one lane. Powers the sparkline
    on the by-Lane row click-out."""
    pool = get_datalake_gold_pool(request)
    today = _today_clamped()
    # ISO week starting Monday — current week excluded
    iso_weekday = today.isoweekday()  # Mon=1..Sun=7
    this_mon = today - timedelta(days=iso_weekday - 1)
    end_excl = this_mon  # current Monday excluded
    start = end_excl - timedelta(weeks=8)

    team_list = _parse_teams(teams)
    params: list = []
    where = _scope_where("d", team_list, customer, lane, params)
    params.extend([start, end_excl])
    p_s, p_e = len(params) - 1, len(params)

    sql = f"""
    SELECT
      date_trunc('week', d.origin_actual_departure)::date        AS week_start,
      COUNT(*)                                                    AS mov,
      COUNT(DISTINCT d.carrier_name)                              AS n_carrier,
      AVG(d.override_pay_amt + d.driver_extra_pay)::numeric       AS avg_cost
    FROM public.mcleod_gld_dispatchers d
    WHERE {where}
      AND d.origin_actual_departure >= ${p_s}
      AND d.origin_actual_departure <  ${p_e}
    GROUP BY 1
    ORDER BY 1
    """
    rows = await pool.fetch(sql, *params)
    by_week = {r["week_start"]: r for r in rows}

    out = []
    for i in range(8):
        ws = start + timedelta(weeks=i)
        r = by_week.get(ws)
        out.append({
            "week_start": ws.isoformat(),
            "mov": int(r["mov"]) if r else 0,
            "n_carrier": int(r["n_carrier"]) if r else 0,
            "avg_cost": float(r["avg_cost"]) if r and r["avg_cost"] is not None else 0.0,
        })

    return {"success": True, "data": out}
