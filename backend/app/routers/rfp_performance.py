"""Code-made report: Performance for RFPs.

Replaces Bruno's Qlik app ``6df25048-2917-43e9-a944-a48cc355fdb4``
(sheet ``4e66056a-50c4-4f07-881c-c047395eedf2``, "RFP Performance
Tracker"). Same source data, just rendered server-side from the gold
copy that already lives in our Aiven cluster.

Source
------
``public.rfp_results_history`` in ``automations_db`` (Aiven). The
table is rebuilt daily at 01:00 CST by n8n workflow
``RFP Results History ETL — Daily 1am CST`` (id ``Pgpg097swOFyjFT9``),
which extracts from the Pricing Portal source DB
(``modern_pricing_portal``) and TRUNCATE+INSERTs ~1–2k rows here.
The ETL already filters out test customer ``id=59`` and inactive
RFPs, and pulls the latest active round per RFP only.

Timezone
--------
``submitted_date`` and the other timestamp columns are already stored
in CST (matches the rest of the datalake). The ``automations_pool`` is
initialised with ``SET TIME ZONE 'America/Chicago'`` in ``main.py``
lifespan, so bare ``CURRENT_DATE`` / ``date_trunc`` expressions resolve
to CST without any per-query ``AT TIME ZONE`` rewriting.

Endpoints
---------
- ``GET /filter-options``           — distinct values for 6 filter pills + date bounds
- ``GET /summary``                  — Potential-Rev + Open/Closed/Lost/Won blocks
- ``GET /convertio-ratio``          — sensitivity table (current calendar year)
- ``GET /trend-12m``                — Volume + Revenue Awarded combo data (last 12 mo)
- ``GET /potential-by-month``       — full-history monthly (Pot Closed + Rev Awarded)
- ``GET /summary-by-tab``           — by Operations / Sales / Division tabs
- ``GET /summary-by-customer``      — RFP Summary by Customer table
- ``GET /summary-by-customer-detail`` — Customer × YearMonth × Type detail
- ``GET /details``                  — row-level RFP Details (paginated)
- ``GET /freshness``                — diagnostic: as-of timestamp + row count

Endpoints flagged in the PDF as "must not be affected by the Date
filter" (``convertio-ratio``, ``trend-12m``, ``potential-by-month``)
ignore ``date_from`` / ``date_to`` and use the current-year /
data-relative-12-months / full-history scope respectively. They still
honour the other 5 filter pills.

Performance
-----------
Table is small (~1–2k rows) so most aggregations run in <50 ms even
without indexes. Recommended indexes (require ``avnadmin`` so they
must be created out-of-band in pgAdmin)::

    CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_rfp_submitted_date
      ON rfp_results_history (submitted_date);
    CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_rfp_status_submitted
      ON rfp_results_history (status, submitted_date);
    CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_rfp_customer_name
      ON rfp_results_history (customer_name);

Each filtered endpoint result is wrapped in a 60-second per-key TTL
cache; the three "ignore date filter" endpoints cache for 10 minutes
since the data only changes once per day.
"""

from __future__ import annotations

import asyncio
import math
import time
from datetime import date
from typing import Any, Optional

from fastapi import APIRouter, Depends, Query, Request, Response

from app.clock import cst_today
from app.routers.deps import get_automations_pool, require_report_access


def _safe_float(value: Any, default: float = 0.0) -> float:
    """Coerce a Postgres NUMERIC/INT to float, mapping NaN/±Inf to ``default``.

    The Pricing Portal upstream (``rfp_results_history``) lets users key raw
    numbers, so a NUMERIC column can occasionally carry ``Decimal('NaN')`` or
    ``Decimal('Infinity')``. Both cast cleanly to Python floats but crash the
    JSON encoder downstream (``ValueError: Out of range float values``). Same
    defensive pattern as the ``effective_end_date`` year clamp — assume the
    upstream produces garbage and harden every per-row conversion.
    """
    if value is None:
        return default
    try:
        f = float(value)
    except (TypeError, ValueError):
        return default
    if math.isnan(f) or math.isinf(f):
        return default
    return f


def _safe_ratio(num: Any, den: Any) -> Optional[float]:
    """``num/den`` with NaN/Inf/zero guards, returning ``None`` for invalid."""
    n = _safe_float(num, default=float("nan"))
    d = _safe_float(den, default=float("nan"))
    if math.isnan(n) or math.isnan(d) or d == 0:
        return None
    r = n / d
    if math.isnan(r) or math.isinf(r):
        return None
    return r

router = APIRouter(
    tags=["rfp-performance"],
    prefix="/custom/rfp-performance",
)


# ---------------------------------------------------------------------------
# Status buckets (single source of truth)
# ---------------------------------------------------------------------------

# Open = anything other than Won/Lost. Bruno's PDF lists both spellings
# of "Quoting Round 2/3" (with and without the space) — keeping both is
# defensive in case the upstream master_categories row gets re-cased.
OPEN_STATUSES = [
    "Pending Final Round Feedback",
    "Round 1 submitted",
    "Round 2 submitted",
    "Round 3 submitted",
    "Quoting Round 1",
    "Quoting Round 2",
    "Quoting Round 3",
    "QuotingRound2",
    "QuotingRound3",
    "Pending Bid to open",
]
CLOSED_STATUSES = ["Won", "Lost"]


# ---------------------------------------------------------------------------
# Filter helper
# ---------------------------------------------------------------------------


def _parse_csv(value: Optional[str]) -> list[str]:
    if not value:
        return []
    return [v.strip() for v in value.split(",") if v.strip()]


def _ytd_default() -> tuple[date, date]:
    """Default date range: Jan 1 of current year through today (CST)."""
    today = cst_today()
    return date(today.year, 1, 1), today


def _apply_filters(
    date_from: Optional[date],
    date_to: Optional[date],
    division: list[str],
    department: list[str],
    business_type: list[str],
    customer: list[str],
    type_quotation: list[str],
    status: list[str],
    params: list,
    *,
    apply_date: bool = True,
) -> str:
    """Append filter args to ``params`` and return the WHERE fragment.

    Operates against the table directly (no alias) so it composes both
    inside CTEs and top-level. Half-open date predicate keeps the
    planner sargable on ``submitted_date``.
    """
    parts: list[str] = ["TRUE"]
    if apply_date:
        if date_from is not None:
            params.append(date_from)
            parts.append(f"submitted_date >= ${len(params)}")
        if date_to is not None:
            params.append(date_to)
            parts.append(f"submitted_date < (${len(params)}::date + 1)")
    if division:
        params.append(division)
        parts.append(f"division = ANY(${len(params)})")
    if department:
        params.append(department)
        parts.append(f"department = ANY(${len(params)})")
    if business_type:
        params.append(business_type)
        parts.append(f"opportunity = ANY(${len(params)})")
    if customer:
        params.append(customer)
        parts.append(f"customer_name = ANY(${len(params)})")
    if type_quotation:
        params.append(type_quotation)
        parts.append(f"type_quotation = ANY(${len(params)})")
    if status:
        params.append(status)
        parts.append(f"status = ANY(${len(params)})")
    return " AND ".join(parts)


# ---------------------------------------------------------------------------
# Tiny TTL cache (per worker, no extra deps)
# ---------------------------------------------------------------------------

_FILTERED_TTL = 60.0  # filter-respecting endpoints
_STATIC_TTL = 600.0   # ignore-date endpoints (data only changes daily)
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


def _cache_set(key: str, value: Any, ttl: float = _FILTERED_TTL) -> None:
    _cache[key] = (time.time() + ttl, value)


def _cache_key(*parts: Any) -> str:
    return "|".join(str(p) for p in parts)


# ---------------------------------------------------------------------------
# Common query parameters
# ---------------------------------------------------------------------------


def _common_params(
    date_from: Optional[str] = Query(None),
    date_to: Optional[str] = Query(None),
    division: Optional[str] = Query(None),
    department: Optional[str] = Query(None),
    business_type: Optional[str] = Query(None),
    customer: Optional[str] = Query(None),
    type_quotation: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
):
    df = date.fromisoformat(date_from) if date_from else None
    dt = date.fromisoformat(date_to) if date_to else None
    if df is None and dt is None:
        df, dt = _ytd_default()
    return {
        "date_from": df,
        "date_to": dt,
        "division": _parse_csv(division),
        "department": _parse_csv(department),
        "business_type": _parse_csv(business_type),
        "customer": _parse_csv(customer),
        "type_quotation": _parse_csv(type_quotation),
        "status": _parse_csv(status),
    }


def _filter_signature(f: dict, *, apply_date: bool = True) -> str:
    parts = []
    if apply_date:
        parts.extend([str(f["date_from"]), str(f["date_to"])])
    for key in ("division", "department", "business_type", "customer", "type_quotation", "status"):
        parts.append(",".join(sorted(f[key])))
    return "|".join(parts)


# ---------------------------------------------------------------------------
# /filter-options
# ---------------------------------------------------------------------------


@router.get("/filter-options")
async def filter_options(
    request: Request,
    response: Response,
    _user: dict = Depends(require_report_access("rfp-performance")),
):
    """Distinct values for the 6 filter pills + the table's submitted_date bounds."""
    cached = _cache_get("filter-options")
    if cached is not None:
        response.headers["Cache-Control"] = "private, max-age=600"
        return cached

    pool = get_automations_pool(request)
    row = await pool.fetchrow(
        """
        SELECT
          ARRAY(SELECT DISTINCT division        FROM rfp_results_history
                WHERE division        IS NOT NULL AND division        <> '' ORDER BY 1) AS divisions,
          ARRAY(SELECT DISTINCT department      FROM rfp_results_history
                WHERE department      IS NOT NULL AND department      <> '' ORDER BY 1) AS departments,
          ARRAY(SELECT DISTINCT opportunity     FROM rfp_results_history
                WHERE opportunity     IS NOT NULL AND opportunity     <> '' ORDER BY 1) AS business_types,
          ARRAY(SELECT DISTINCT customer_name   FROM rfp_results_history
                WHERE customer_name   IS NOT NULL AND customer_name   <> '' ORDER BY 1) AS customers,
          ARRAY(SELECT DISTINCT type_quotation  FROM rfp_results_history
                WHERE type_quotation  IS NOT NULL AND type_quotation  <> '' ORDER BY 1) AS types,
          ARRAY(SELECT DISTINCT status          FROM rfp_results_history
                WHERE status          IS NOT NULL AND status          <> '' ORDER BY 1) AS statuses,
          -- Emit MIN/MAX as text with a sane-year clamp, same defensive
          -- pattern as ``/details``. A single 5-digit-year typo in
          -- ``submitted_date`` would otherwise crash asyncpg decoding the
          -- aggregate result and take down the whole page (filter-options
          -- is the first request the page fires).
          (SELECT to_char(MIN(submitted_date), 'YYYY-MM-DD')
             FROM rfp_results_history
             WHERE submitted_date IS NOT NULL
               AND EXTRACT(YEAR FROM submitted_date) BETWEEN 1900 AND 2200) AS min_date,
          (SELECT to_char(MAX(submitted_date), 'YYYY-MM-DD')
             FROM rfp_results_history
             WHERE submitted_date IS NOT NULL
               AND EXTRACT(YEAR FROM submitted_date) BETWEEN 1900 AND 2200) AS max_date,
          (SELECT MAX(etl_loaded_at) FROM rfp_results_history)         AS as_of
        """,
    )
    payload = {
        "success": True,
        "data": {
            "divisions": list(row["divisions"]) if row else [],
            "departments": list(row["departments"]) if row else [],
            "business_types": list(row["business_types"]) if row else [],
            "customers": list(row["customers"]) if row else [],
            "types": list(row["types"]) if row else [],
            "statuses": list(row["statuses"]) if row else [],
            "min_date": row["min_date"] if row and row["min_date"] else None,
            "max_date": row["max_date"] if row and row["max_date"] else None,
            "as_of": row["as_of"].isoformat() if row and row["as_of"] else None,
        },
    }
    _cache_set("filter-options", payload, ttl=_STATIC_TTL)
    response.headers["Cache-Control"] = "private, max-age=600"
    return payload


# ---------------------------------------------------------------------------
# /summary  — Potential Revenue grand total + 4 status blocks
# ---------------------------------------------------------------------------


@router.get("/summary")
async def summary(
    request: Request,
    response: Response,
    f: dict = Depends(_common_params),
    _user: dict = Depends(require_report_access("rfp-performance")),
):
    """All KPI numbers for the page header in one round-trip.

    Returns:
      - ``grand_total_pot_rev``: Sum(potential_revenue) over the
        filter-bar selection (used as denominator for ``% Potential Rev``
        across all four status blocks)
      - ``open`` / ``closed`` / ``lost`` / ``won`` blocks: each contains
        the metric set per the PDF (RFPs, Offer Lanes, Lane Quoted,
        Lane Participation %, Total Offer Load Count, Load Count Quoted,
        Volume Participation %, Potential Revenue, % Potential Rev). The
        ``won`` block additionally carries Lane Awarded, Lane Awarded
        Ratio %, Load Awarded, Load Awarded Ratio %, Awarded Revenue and
        Awarded Convertio Ratio.
    """
    key = _cache_key("summary", _filter_signature(f))
    cached = _cache_get(key)
    if cached is not None:
        response.headers["Cache-Control"] = "private, max-age=60"
        return cached

    pool = get_automations_pool(request)
    params: list = []
    where = _apply_filters(
        f["date_from"], f["date_to"], f["division"], f["department"],
        f["business_type"], f["customer"], f["type_quotation"], f["status"],
        params,
    )
    params.append(OPEN_STATUSES)
    open_idx = len(params)
    params.append(CLOSED_STATUSES)
    closed_idx = len(params)

    sql = f"""
    WITH base AS (
      SELECT * FROM rfp_results_history WHERE {where}
    )
    SELECT
      COALESCE(SUM(potential_revenue), 0)::numeric AS grand_total_pot_rev,

      -- ---------- OPEN block ----------
      COUNT(DISTINCT rfp_id) FILTER (WHERE status = ANY(${open_idx}))            AS open_rfps,
      COALESCE(SUM(no_lanes)        FILTER (WHERE status = ANY(${open_idx})), 0)::numeric AS open_offer_lanes,
      COALESCE(SUM(lanes_quoted)    FILTER (WHERE status = ANY(${open_idx})), 0)::numeric AS open_lane_quoted,
      COALESCE(SUM(no_loads)        FILTER (WHERE status = ANY(${open_idx})), 0)::numeric AS open_total_offer_loads,
      COALESCE(SUM(volume_quoted)   FILTER (WHERE status = ANY(${open_idx})), 0)::numeric AS open_load_count_quoted,
      COALESCE(SUM(potential_revenue) FILTER (WHERE status = ANY(${open_idx})), 0)::numeric AS open_pot_rev,

      -- ---------- CLOSED block (Won + Lost) ----------
      COUNT(DISTINCT rfp_id) FILTER (WHERE status = ANY(${closed_idx}))           AS closed_rfps,
      COALESCE(SUM(no_lanes)        FILTER (WHERE status = ANY(${closed_idx})), 0)::numeric AS closed_offer_lanes,
      COALESCE(SUM(lanes_quoted)    FILTER (WHERE status = ANY(${closed_idx})), 0)::numeric AS closed_lane_quoted,
      COALESCE(SUM(no_loads)        FILTER (WHERE status = ANY(${closed_idx})), 0)::numeric AS closed_total_offer_loads,
      COALESCE(SUM(volume_quoted)   FILTER (WHERE status = ANY(${closed_idx})), 0)::numeric AS closed_load_count_quoted,
      COALESCE(SUM(potential_revenue) FILTER (WHERE status = ANY(${closed_idx})), 0)::numeric AS closed_pot_rev,

      -- ---------- LOST block ----------
      COUNT(DISTINCT rfp_id) FILTER (WHERE status = 'Lost')                       AS lost_rfps,
      COALESCE(SUM(no_lanes)        FILTER (WHERE status = 'Lost'), 0)::numeric  AS lost_offer_lanes,
      COALESCE(SUM(lanes_quoted)    FILTER (WHERE status = 'Lost'), 0)::numeric  AS lost_lane_quoted,
      COALESCE(SUM(no_loads)        FILTER (WHERE status = 'Lost'), 0)::numeric  AS lost_total_offer_loads,
      COALESCE(SUM(volume_quoted)   FILTER (WHERE status = 'Lost'), 0)::numeric  AS lost_load_count_quoted,
      COALESCE(SUM(potential_revenue) FILTER (WHERE status = 'Lost'), 0)::numeric AS lost_pot_rev,

      -- ---------- WON block ----------
      COUNT(DISTINCT rfp_id) FILTER (WHERE status = 'Won')                        AS won_rfps,
      COALESCE(SUM(no_lanes)        FILTER (WHERE status = 'Won'), 0)::numeric   AS won_offer_lanes,
      COALESCE(SUM(lanes_quoted)    FILTER (WHERE status = 'Won'), 0)::numeric   AS won_lane_quoted,
      COALESCE(SUM(no_loads)        FILTER (WHERE status = 'Won'), 0)::numeric   AS won_total_offer_loads,
      COALESCE(SUM(volume_quoted)   FILTER (WHERE status = 'Won'), 0)::numeric   AS won_load_count_quoted,
      COALESCE(SUM(potential_revenue) FILTER (WHERE status = 'Won'), 0)::numeric AS won_pot_rev,
      -- Won-only awarded metrics
      COALESCE(SUM(awarded_lanes)   FILTER (WHERE status = 'Won'), 0)::numeric   AS won_lane_awarded,
      COALESCE(SUM(rfp_volume)      FILTER (WHERE status = 'Won'), 0)::numeric   AS won_load_awarded,
      COALESCE(SUM(rfp_revenue)     FILTER (WHERE status = 'Won'), 0)::numeric   AS won_awarded_revenue
    FROM base
    """
    row = await pool.fetchrow(sql, *params)

    def _ratio(num, den):
        n = float(num or 0)
        d = float(den or 0)
        return (n / d) if d else None

    grand = float(row["grand_total_pot_rev"] or 0)

    def _block(prefix: str) -> dict:
        rfps = int(row[f"{prefix}_rfps"] or 0)
        offer_lanes = float(row[f"{prefix}_offer_lanes"] or 0)
        lane_quoted = float(row[f"{prefix}_lane_quoted"] or 0)
        total_loads = float(row[f"{prefix}_total_offer_loads"] or 0)
        load_quoted = float(row[f"{prefix}_load_count_quoted"] or 0)
        pot_rev = float(row[f"{prefix}_pot_rev"] or 0)
        return {
            "rfps": rfps,
            "offer_lanes": offer_lanes,
            "lane_quoted": lane_quoted,
            "lane_participation_pct": _ratio(lane_quoted, offer_lanes),
            "total_offer_loads": total_loads,
            "load_count_quoted": load_quoted,
            "volume_participation_pct": _ratio(load_quoted, total_loads),
            "potential_revenue": pot_rev,
            "pct_potential_rev": _ratio(pot_rev, grand),
        }

    open_block = _block("open")
    closed_block = _block("closed")
    lost_block = _block("lost")
    won_block = _block("won")

    # Won-only awarded extras (not present on Open/Closed/Lost)
    won_lane_awarded = float(row["won_lane_awarded"] or 0)
    won_load_awarded = float(row["won_load_awarded"] or 0)
    won_awarded_revenue = float(row["won_awarded_revenue"] or 0)
    won_block.update({
        "lane_awarded": won_lane_awarded,
        "lane_awarded_ratio_pct": _ratio(won_lane_awarded, won_block["offer_lanes"]),
        "load_awarded": won_load_awarded,
        "load_awarded_ratio_pct": _ratio(won_load_awarded, won_block["total_offer_loads"]),
        "awarded_revenue": won_awarded_revenue,
        # PDF: numerator Won, denominator grand-total potential_revenue (not Won-scoped)
        "awarded_convertio_ratio": _ratio(won_awarded_revenue, grand),
    })

    payload = {
        "success": True,
        "data": {
            "grand_total_pot_rev": grand,
            "open": open_block,
            "closed": closed_block,
            "lost": lost_block,
            "won": won_block,
        },
    }
    _cache_set(key, payload)
    response.headers["Cache-Control"] = "private, max-age=60"
    return payload


# ---------------------------------------------------------------------------
# /business-type-summary — Bruno round-2 (2026-05-13)
# Potential Revenue + Awarded Conv Ratio for All / New / Existing customer
# Containers 2 + 3 ignore the user's business_type filter pill.
# ---------------------------------------------------------------------------


@router.get("/business-type-summary")
async def business_type_summary(
    request: Request,
    response: Response,
    f: dict = Depends(_common_params),
    _user: dict = Depends(require_report_access("rfp-performance")),
):
    """3 KPI containers next to the Potential Revenue banner.

    Each container reports:
      - ``potential_revenue``: SUM(potential_revenue) in scope.
      - ``awarded_conv_ratio``: SUM(rfp_revenue WHERE status='Won')
        divided by the same potential_revenue (mirrors the "Won" block's
        Awarded Convertio Ratio).

    Bucket scopes:
      - **all**: honors every filter (same as the Potential Revenue banner).
      - **new**: forces ``opportunity = 'New'``; ignores the user's
        ``business_type`` filter pill.
      - **existing**: forces ``opportunity = 'Existing customer'``;
        ignores the user's ``business_type`` filter pill.
    """
    key = _cache_key("business-type-summary", _filter_signature(f))
    cached = _cache_get(key)
    if cached is not None:
        response.headers["Cache-Control"] = "private, max-age=60"
        return cached

    pool = get_automations_pool(request)

    async def _bucket(business_type_override: Optional[list[str]]) -> dict:
        params: list = []
        # When override is set, IGNORE the user's business_type filter pill.
        bt_filter = (
            business_type_override
            if business_type_override is not None
            else f["business_type"]
        )
        where = _apply_filters(
            f["date_from"], f["date_to"],
            f["division"], f["department"],
            bt_filter,
            f["customer"], f["type_quotation"], f["status"],
            params,
        )
        row = await pool.fetchrow(
            f"""
            SELECT
              COALESCE(SUM(potential_revenue), 0)::numeric            AS pot_rev,
              COALESCE(SUM(rfp_revenue) FILTER (WHERE status='Won'), 0)::numeric AS rev_won
            FROM rfp_results_history
            WHERE {where}
            """,
            *params,
        )
        pot = float(row["pot_rev"] or 0)
        won = float(row["rev_won"] or 0)
        return {
            "potential_revenue": pot,
            "awarded_conv_ratio": (won / pot) if pot else None,
        }

    all_b, new_b, existing_b = await asyncio.gather(
        _bucket(None),
        _bucket(["New"]),
        _bucket(["Existing customer"]),
    )

    payload = {
        "success": True,
        "data": {
            "all": all_b,
            "new": new_b,
            "existing": existing_b,
        },
    }
    _cache_set(key, payload)
    response.headers["Cache-Control"] = "private, max-age=60"
    return payload


# ---------------------------------------------------------------------------
# /convertio-ratio — sensitivity table, current calendar year, ignore date filter
# ---------------------------------------------------------------------------


@router.get("/convertio-ratio")
async def convertio_ratio(
    request: Request,
    response: Response,
    f: dict = Depends(_common_params),
    _user: dict = Depends(require_report_access("rfp-performance")),
):
    """The 0.5%→5% sensitivity table.

    Always scoped to the current calendar year (Jan 1 → Dec 31 of
    ``CURRENT_DATE``'s year), regardless of the user's date filter —
    matches Bruno's hardcoded 2026 range in the legacy Qlik query, but
    auto-rolls forward on Jan 1.
    """
    key = _cache_key("convertio-ratio", _filter_signature(f, apply_date=False))
    cached = _cache_get(key)
    if cached is not None:
        response.headers["Cache-Control"] = "private, max-age=600"
        return cached

    pool = get_automations_pool(request)
    params: list = []
    # Force date scope to current calendar year, ignoring user's date_from/date_to
    where = _apply_filters(
        None, None,
        f["division"], f["department"], f["business_type"],
        f["customer"], f["type_quotation"], f["status"],
        params, apply_date=False,
    )
    params.append(CLOSED_STATUSES)
    closed_idx = len(params)

    sql = f"""
    WITH base AS (
      SELECT * FROM rfp_results_history
      WHERE {where}
        AND submitted_date >= date_trunc('year', CURRENT_DATE)
        AND submitted_date <  date_trunc('year', CURRENT_DATE) + INTERVAL '1 year'
    ),
    totals AS (
      SELECT
        COALESCE(SUM(potential_revenue) FILTER (WHERE status = ANY(${closed_idx})), 0)::numeric AS pot_rev_closed,
        COALESCE(SUM(rfp_revenue)       FILTER (WHERE status = 'Won'), 0)::numeric              AS revenue_awarded
      FROM base
    ),
    ratios AS (
      SELECT generate_series(0.005, 0.05, 0.005)::numeric AS ratio
    )
    SELECT
      r.ratio,
      ROUND(t.pot_rev_closed * r.ratio, 0)::numeric                            AS revenue_awarded_at_ratio,
      ROUND(t.revenue_awarded - t.pot_rev_closed * r.ratio, 0)::numeric        AS actual_vs_conv_ratio,
      ROUND(t.pot_rev_closed * r.ratio * 0.15, 0)::numeric                     AS pot_rev_gp_15,
      t.pot_rev_closed,
      t.revenue_awarded
    FROM ratios r CROSS JOIN totals t
    ORDER BY r.ratio DESC
    """
    rows = await pool.fetch(sql, *params)

    pot_rev_closed = float(rows[0]["pot_rev_closed"] or 0) if rows else 0
    revenue_awarded = float(rows[0]["revenue_awarded"] or 0) if rows else 0
    table = [
        {
            "ratio": float(r["ratio"]),
            "revenue_awarded_at_ratio": float(r["revenue_awarded_at_ratio"]),
            "actual_vs_conv_ratio": float(r["actual_vs_conv_ratio"]),
            "pot_rev_gp_15": float(r["pot_rev_gp_15"]),
        }
        for r in rows
    ]
    payload = {
        "success": True,
        "data": {
            "pot_rev_closed": pot_rev_closed,
            "revenue_awarded": revenue_awarded,
            "rows": table,
        },
    }
    _cache_set(key, payload, ttl=_STATIC_TTL)
    response.headers["Cache-Control"] = "private, max-age=600"
    return payload


# ---------------------------------------------------------------------------
# /trend-12m — combo charts (last 12 months, ignore date filter)
# ---------------------------------------------------------------------------


@router.get("/trend-12m")
async def trend_12m(
    request: Request,
    response: Response,
    f: dict = Depends(_common_params),
    _user: dict = Depends(require_report_access("rfp-performance")),
):
    """YTD monthly Volume+Revenue Awarded vs Convertio ratios.

    Bruno round-2 (2026-05-13): switched from "rolling last 12 months
    anchored at MAX(submitted_date)" to "Year-To-Date only", still
    ignoring the user's Date filter. Endpoint name is preserved so the
    React Query cache key stays stable across the deploy.
    """
    key = _cache_key("trend-12m-ytd", _filter_signature(f, apply_date=False))
    cached = _cache_get(key)
    if cached is not None:
        response.headers["Cache-Control"] = "private, max-age=600"
        return cached

    pool = get_automations_pool(request)
    today = cst_today()
    year_start = date(today.year, 1, 1)
    params: list = []
    where = _apply_filters(
        None, None,
        f["division"], f["department"], f["business_type"],
        f["customer"], f["type_quotation"], f["status"],
        params, apply_date=False,
    )
    params.append(year_start)
    p_ys = len(params)
    params.append(today)
    p_today = len(params)

    sql = f"""
    WITH base AS (
      SELECT * FROM rfp_results_history WHERE {where} AND submitted_date IS NOT NULL
    ),
    months AS (
      SELECT
        date_trunc('month', submitted_date)::date AS ym,
        COALESCE(SUM(rfp_volume)       FILTER (WHERE status = 'Won'), 0)::numeric AS volume_won,
        COALESCE(SUM(no_loads), 0)::numeric                                       AS no_loads_total,
        COALESCE(SUM(rfp_revenue)      FILTER (WHERE status = 'Won'), 0)::numeric AS revenue_won,
        COALESCE(SUM(potential_revenue), 0)::numeric                              AS pot_rev_total
      FROM base
      WHERE submitted_date >= ${p_ys}
        AND submitted_date <  (${p_today}::date + 1)
      GROUP BY 1
    )
    SELECT * FROM months ORDER BY ym
    """
    rows = await pool.fetch(sql, *params)

    out = []
    for r in rows:
        volume_won = float(r["volume_won"] or 0)
        no_loads = float(r["no_loads_total"] or 0)
        revenue_won = float(r["revenue_won"] or 0)
        pot_rev = float(r["pot_rev_total"] or 0)
        out.append({
            "ym": r["ym"].isoformat(),
            "volume_won": volume_won,
            "volume_conv_ratio": (volume_won / no_loads) if no_loads else None,
            "revenue_won": revenue_won,
            "revenue_conv_ratio": (revenue_won / pot_rev) if pot_rev else None,
        })

    payload = {"success": True, "data": {"rows": out}}
    _cache_set(key, payload, ttl=_STATIC_TTL)
    response.headers["Cache-Control"] = "private, max-age=600"
    return payload


# ---------------------------------------------------------------------------
# /potential-by-month — full history monthly table, ignore date filter
# ---------------------------------------------------------------------------


@router.get("/potential-by-month")
async def potential_by_month(
    request: Request,
    response: Response,
    f: dict = Depends(_common_params),
    _user: dict = Depends(require_report_access("rfp-performance")),
):
    """Full-history monthly Potential Closed + Revenue Awarded."""
    key = _cache_key("potential-by-month", _filter_signature(f, apply_date=False))
    cached = _cache_get(key)
    if cached is not None:
        response.headers["Cache-Control"] = "private, max-age=600"
        return cached

    pool = get_automations_pool(request)
    params: list = []
    where = _apply_filters(
        None, None,
        f["division"], f["department"], f["business_type"],
        f["customer"], f["type_quotation"], f["status"],
        params, apply_date=False,
    )
    params.append(CLOSED_STATUSES)
    closed_idx = len(params)

    sql = f"""
    SELECT
      date_trunc('month', submitted_date)::date AS ym,
      COALESCE(SUM(potential_revenue) FILTER (WHERE status = ANY(${closed_idx})), 0)::numeric AS potential_closed,
      COALESCE(SUM(rfp_revenue)       FILTER (WHERE status = 'Won'), 0)::numeric              AS revenue_awarded
    FROM rfp_results_history
    WHERE {where} AND submitted_date IS NOT NULL
    GROUP BY 1
    ORDER BY 1 DESC
    """
    rows = await pool.fetch(sql, *params)

    out = [
        {
            "ym": r["ym"].isoformat(),
            "potential_closed": float(r["potential_closed"] or 0),
            "revenue_awarded": float(r["revenue_awarded"] or 0),
        }
        for r in rows
    ]
    payload = {"success": True, "data": {"rows": out}}
    _cache_set(key, payload, ttl=_STATIC_TTL)
    response.headers["Cache-Control"] = "private, max-age=600"
    return payload


# ---------------------------------------------------------------------------
# /summary-by-tab — by Operations / Sales / Division
# ---------------------------------------------------------------------------


@router.get("/summary-by-tab")
async def summary_by_tab(
    request: Request,
    response: Response,
    tab: str = Query("division"),
    f: dict = Depends(_common_params),
    _user: dict = Depends(require_report_access("rfp-performance")),
):
    """Summary table tabbed by Operations / Sales / Division.

    Conv = Awarded / Potential W/O (where W/O = lost potential).
    Bruno's quirky definition; preserved verbatim from the PDF.
    """
    if tab not in ("operations", "sales", "division"):
        tab = "division"

    key = _cache_key("summary-by-tab", tab, _filter_signature(f))
    cached = _cache_get(key)
    if cached is not None:
        response.headers["Cache-Control"] = "private, max-age=60"
        return cached

    pool = get_automations_pool(request)
    params: list = []
    where = _apply_filters(
        f["date_from"], f["date_to"], f["division"], f["department"],
        f["business_type"], f["customer"], f["type_quotation"], f["status"],
        params,
    )

    if tab == "operations":
        dept_filter = "department = 'Operations'"
    elif tab == "sales":
        dept_filter = "department = 'Sales'"
    else:
        dept_filter = "TRUE"

    sql = f"""
    WITH base AS (
      SELECT * FROM rfp_results_history
      WHERE {where} AND {dept_filter}
    )
    SELECT
      COALESCE(NULLIF(division, ''), '—')                                       AS division,
      COALESCE(SUM(potential_revenue), 0)::numeric                              AS potential_revenue,
      COALESCE(SUM(potential_revenue) FILTER (WHERE status = 'Lost'), 0)::numeric AS potential_wo,
      COALESCE(SUM(rfp_revenue), 0)::numeric                                    AS awarded
    FROM base
    GROUP BY 1
    ORDER BY 1
    """
    rows = await pool.fetch(sql, *params)

    out_rows = []
    tot_pot = tot_wo = tot_aw = 0.0
    for r in rows:
        pot = float(r["potential_revenue"] or 0)
        wo = float(r["potential_wo"] or 0)
        aw = float(r["awarded"] or 0)
        tot_pot += pot
        tot_wo += wo
        tot_aw += aw
        out_rows.append({
            "division": r["division"],
            "potential_revenue": pot,
            "potential_wo": wo,
            "awarded": aw,
            "conv": (aw / wo) if wo else None,
        })
    totals = {
        "potential_revenue": tot_pot,
        "potential_wo": tot_wo,
        "awarded": tot_aw,
        "conv": (tot_aw / tot_wo) if tot_wo else None,
    }

    payload = {"success": True, "data": {"rows": out_rows, "totals": totals}}
    _cache_set(key, payload)
    response.headers["Cache-Control"] = "private, max-age=60"
    return payload


# ---------------------------------------------------------------------------
# /summary-by-customer — RFP Summary by Customer
# ---------------------------------------------------------------------------


@router.get("/summary-by-customer")
async def summary_by_customer(
    request: Request,
    response: Response,
    f: dict = Depends(_common_params),
    _user: dict = Depends(require_report_access("rfp-performance")),
):
    """Customer-level summary table (10 metric columns)."""
    key = _cache_key("summary-by-customer", _filter_signature(f))
    cached = _cache_get(key)
    if cached is not None:
        response.headers["Cache-Control"] = "private, max-age=60"
        return cached

    pool = get_automations_pool(request)
    params: list = []
    where = _apply_filters(
        f["date_from"], f["date_to"], f["division"], f["department"],
        f["business_type"], f["customer"], f["type_quotation"], f["status"],
        params,
    )

    sql = f"""
    SELECT
      COALESCE(NULLIF(customer_name, ''), '—')              AS customer,
      COUNT(DISTINCT rfp_name)::int                         AS bids,
      COALESCE(SUM(no_lanes), 0)::numeric                   AS total_lanes,
      COALESCE(SUM(lanes_quoted), 0)::numeric               AS lanes_quoted,
      COALESCE(SUM(no_loads), 0)::numeric                   AS total_volume,
      COALESCE(SUM(volume_quoted), 0)::numeric              AS volume_quoted,
      COALESCE(SUM(potential_revenue), 0)::numeric          AS potential_revenue,
      COALESCE(SUM(rfp_revenue), 0)::numeric                AS awarded_revenue
    FROM rfp_results_history
    WHERE {where}
    GROUP BY 1
    HAVING COUNT(*) > 0
    ORDER BY potential_revenue DESC
    """
    rows = await pool.fetch(sql, *params)

    out = []
    for r in rows:
        total_lanes = float(r["total_lanes"] or 0)
        lanes_quoted = float(r["lanes_quoted"] or 0)
        total_vol = float(r["total_volume"] or 0)
        vol_quoted = float(r["volume_quoted"] or 0)
        pot_rev = float(r["potential_revenue"] or 0)
        awarded = float(r["awarded_revenue"] or 0)
        out.append({
            "customer": r["customer"],
            "bids": int(r["bids"] or 0),
            "total_lanes": total_lanes,
            "lanes_quoted": lanes_quoted,
            "lanes_ratio_pct": (lanes_quoted / total_lanes) if total_lanes else None,
            "total_volume": total_vol,
            "volume_quoted": vol_quoted,
            "volume_ratio_pct": (vol_quoted / total_vol) if total_vol else None,
            "potential_revenue": pot_rev,
            "awarded_revenue": awarded,
            "awarded_conv_ratio_pct": (awarded / pot_rev) if pot_rev else None,
        })
    payload = {"success": True, "data": {"rows": out}}
    _cache_set(key, payload)
    response.headers["Cache-Control"] = "private, max-age=60"
    return payload


# ---------------------------------------------------------------------------
# /summary-by-customer-detail — Customer × YearMonth × Type
# ---------------------------------------------------------------------------


@router.get("/summary-by-customer-detail")
async def summary_by_customer_detail(
    request: Request,
    response: Response,
    f: dict = Depends(_common_params),
    _user: dict = Depends(require_report_access("rfp-performance")),
):
    """Customer × YearMonth × type_quotation pivot (14 metric columns)."""
    key = _cache_key("summary-by-customer-detail", _filter_signature(f))
    cached = _cache_get(key)
    if cached is not None:
        response.headers["Cache-Control"] = "private, max-age=60"
        return cached

    pool = get_automations_pool(request)
    params: list = []
    where = _apply_filters(
        f["date_from"], f["date_to"], f["division"], f["department"],
        f["business_type"], f["customer"], f["type_quotation"], f["status"],
        params,
    )

    sql = f"""
    SELECT
      COALESCE(NULLIF(customer_name, ''), '—')   AS customer,
      date_trunc('month', submitted_date)::date  AS ym,
      COALESCE(NULLIF(type_quotation, ''), '—')  AS type_quotation,
      COALESCE(SUM(no_lanes), 0)::numeric        AS total_lanes,
      COALESCE(SUM(lanes_quoted), 0)::numeric    AS lanes_quoted,
      COALESCE(SUM(awarded_lanes), 0)::numeric   AS lanes_awarded,
      COALESCE(SUM(no_loads), 0)::numeric        AS total_volume,
      COALESCE(SUM(volume_quoted), 0)::numeric   AS volume_quoted,
      COALESCE(SUM(rfp_volume), 0)::numeric      AS loads_awarded,
      COALESCE(SUM(potential_revenue), 0)::numeric AS potential_revenue,
      COALESCE(SUM(rfp_revenue), 0)::numeric     AS rev_awarded
    FROM rfp_results_history
    WHERE {where}
    GROUP BY 1, 2, 3
    ORDER BY potential_revenue DESC, customer
    LIMIT 5000
    """
    rows = await pool.fetch(sql, *params)

    out = []
    for r in rows:
        total_lanes = float(r["total_lanes"] or 0)
        lanes_quoted = float(r["lanes_quoted"] or 0)
        lanes_awarded = float(r["lanes_awarded"] or 0)
        total_vol = float(r["total_volume"] or 0)
        vol_quoted = float(r["volume_quoted"] or 0)
        loads_awarded = float(r["loads_awarded"] or 0)
        pot_rev = float(r["potential_revenue"] or 0)
        rev_aw = float(r["rev_awarded"] or 0)
        out.append({
            "customer": r["customer"],
            "ym": r["ym"].isoformat() if r["ym"] else None,
            "type_quotation": r["type_quotation"],
            "total_lanes": total_lanes,
            "lanes_quoted": lanes_quoted,
            "lane_part_pct": (lanes_quoted / total_lanes) if total_lanes else None,
            "lanes_awarded": lanes_awarded,
            "lanes_conv_rat_pct": (lanes_awarded / lanes_quoted) if lanes_quoted else None,
            "total_volume": total_vol,
            "volume_quoted": vol_quoted,
            "volume_part_pct": (vol_quoted / total_vol) if total_vol else None,
            "loads_awarded": loads_awarded,
            "loads_conv_rat_pct": (loads_awarded / vol_quoted) if vol_quoted else None,
            "potential_revenue": pot_rev,
            "rev_awarded": rev_aw,
            "rev_conv_ratio_pct": (rev_aw / pot_rev) if pot_rev else None,
        })
    payload = {"success": True, "data": {"rows": out}}
    _cache_set(key, payload)
    response.headers["Cache-Control"] = "private, max-age=60"
    return payload


# ---------------------------------------------------------------------------
# /details — row-level RFP table
# ---------------------------------------------------------------------------


@router.get("/details")
async def details(
    request: Request,
    response: Response,
    page: int = Query(1, ge=1),
    page_size: int = Query(100, ge=10, le=500),
    sort: str = Query("submitted_desc"),
    f: dict = Depends(_common_params),
    _user: dict = Depends(require_report_access("rfp-performance")),
):
    """Row-level RFP Details, paginated."""
    pool = get_automations_pool(request)
    params: list = []
    where = _apply_filters(
        f["date_from"], f["date_to"], f["division"], f["department"],
        f["business_type"], f["customer"], f["type_quotation"], f["status"],
        params,
    )

    order_by = {
        "submitted_desc": "submitted_date DESC NULLS LAST, rfp_id DESC",
        "submitted_asc":  "submitted_date ASC  NULLS LAST, rfp_id ASC",
        "potential_desc": "potential_revenue DESC NULLS LAST",
        "potential_asc":  "potential_revenue ASC  NULLS LAST",
        "awarded_desc":   "rfp_revenue DESC NULLS LAST",
        "awarded_asc":    "rfp_revenue ASC  NULLS LAST",
        "rfp_desc":       "rfp_id DESC",
        "rfp_asc":        "rfp_id ASC",
    }.get(sort, "submitted_date DESC NULLS LAST, rfp_id DESC")

    offset = (page - 1) * page_size
    params.append(page_size)
    limit_idx = len(params)
    params.append(offset)
    offset_idx = len(params)

    sql = f"""
    WITH base AS (
      SELECT * FROM rfp_results_history WHERE {where}
    ),
    counted AS (
      SELECT COUNT(*) AS total FROM base
    )
    SELECT
      rfp_id,
      to_char(rfp_created_at, 'Month')                        AS month,
      EXTRACT(YEAR FROM rfp_created_at)::int                  AS year,
      customer_name,
      division,
      type_quotation,
      no_lanes,
      lanes_quoted,
      awarded_lanes,
      no_loads,
      volume_quoted,
      rfp_volume,
      potential_revenue,
      rfp_revenue,
      status,
      rfp_created_by,
      -- Same year-clamp treatment as ``end_date`` below. Pricing Portal
      -- lets users key raw date strings; bad values surface as out-of-range
      -- timestamps that crash asyncpg's date_decode mid-iteration on this
      -- per-row endpoint. ``filter-options``' MIN/MAX aggregates skip the
      -- bad row so the static cache never sees the failure — only the
      -- materialized ``/details`` page does. Emit as text so the protocol
      -- never tries to decode a bad date. (Bug surfaced 2026-05-07 on the
      -- /details endpoint after the prior ``effective_end_date`` clamp in
      -- commit ``af4af8a`` proved insufficient — additional column was
      -- vulnerable to the same class of typo.)
      CASE
        WHEN submitted_date IS NULL THEN NULL
        WHEN EXTRACT(YEAR FROM submitted_date) BETWEEN 1900 AND 2200
          THEN to_char(submitted_date, 'YYYY-MM-DD')
        ELSE NULL
      END AS submitted_date,
      -- Pricing-Portal data-entry typos have produced 5-digit years
      -- ('32027-03-10', '20226-04-24') in `effective_end_date`. asyncpg's
      -- date_decode then raises `ValueError: year out of range`. Clamp to
      -- a sane window and emit as text so the protocol never tries to
      -- decode a bad date. Two rows known affected (rfp_id=738, 815).
      CASE
        WHEN effective_end_date IS NULL THEN NULL
        WHEN EXTRACT(YEAR FROM effective_end_date) BETWEEN 1900 AND 2200
          THEN to_char(effective_end_date, 'YYYY-MM-DD')
        ELSE NULL
      END AS end_date,
      (SELECT total FROM counted) AS total_count
    FROM base
    ORDER BY {order_by}
    LIMIT ${limit_idx} OFFSET ${offset_idx}
    """
    rows = await pool.fetch(sql, *params)

    total = int(rows[0]["total_count"]) if rows else 0
    # All numeric fields go through ``_safe_float`` / ``_safe_ratio`` to absorb
    # NaN/Inf values that the Pricing Portal can plant in NUMERIC columns —
    # ``float(Decimal('NaN'))`` succeeds but the JSON encoder raises later,
    # which would surface as a per-row 500 indistinguishable from a date typo.
    out = [
        {
            "rfp_id": int(r["rfp_id"]) if r["rfp_id"] is not None else None,
            "month": (r["month"] or "").strip(),
            "year": r["year"],
            "customer": r["customer_name"],
            "division": r["division"],
            "type_quotation": r["type_quotation"],
            "total_lanes": _safe_float(r["no_lanes"]),
            "lanes_quoted": _safe_float(r["lanes_quoted"]),
            "lane_participation_pct": _safe_ratio(r["lanes_quoted"], r["no_lanes"]),
            "lanes_awarded": _safe_float(r["awarded_lanes"]),
            "total_volume": _safe_float(r["no_loads"]),
            "volume_quoted": _safe_float(r["volume_quoted"]),
            "volume_participation_pct": _safe_ratio(r["volume_quoted"], r["no_loads"]),
            "loads_awarded": _safe_float(r["rfp_volume"]),
            "potential_revenue": _safe_float(r["potential_revenue"]),
            "revenue_awarded": _safe_float(r["rfp_revenue"]),
            "status": r["status"],
            "sales_executive": r["rfp_created_by"],
            # submitted_date and end_date are both clamped to text via SQL
            # CASE (see the SELECT above); just pass through the string.
            "submitted_date": r["submitted_date"],
            "end_date": r["end_date"],
        }
        for r in rows
    ]

    return {
        "success": True,
        "data": {"rows": out},
        "meta": {"total": total, "page": page, "page_size": page_size},
    }


# ---------------------------------------------------------------------------
# /freshness — diagnostic
# ---------------------------------------------------------------------------


@router.get("/freshness")
async def freshness(
    request: Request,
    _user: dict = Depends(require_report_access("rfp-performance")),
):
    pool = get_automations_pool(request)
    row = await pool.fetchrow(
        """
        SELECT MAX(etl_loaded_at) AS as_of,
               COUNT(*)            AS rows_total,
               MIN(submitted_date)::date AS min_date,
               MAX(submitted_date)::date AS max_date
        FROM rfp_results_history
        """
    )
    return {
        "success": True,
        "data": {
            "as_of": row["as_of"].isoformat() if row and row["as_of"] else None,
            "rows": int(row["rows_total"] or 0) if row else 0,
            "min_date": row["min_date"].isoformat() if row and row["min_date"] else None,
            "max_date": row["max_date"].isoformat() if row and row["max_date"] else None,
            "checked_at": cst_today().isoformat(),
        },
    }
