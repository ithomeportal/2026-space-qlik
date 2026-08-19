"""Code-made report: Booker Performance Scorecard (Bruno PDF 2026-08-10).

Built on the same "Bookings" universe as ``Podium Set DFW``
(``routers/podium_dfw.py``): ``mcleod_gld_order_post_hist`` postings of type
``'C'`` / comment ``'Rate Conf Received'``, latest posting per order, joined to
``mcleod_gld_budget_report_v4`` for money + attributes, scoped to
``team_id = 'TEAM-DFW'`` and ``status <> 'V'``.

⚠ ONE DELIBERATE DIVERGENCE FROM PODIUM — "latest posting per order"
---------------------------------------------------------------------
Podium computes ``ROW_NUMBER() … rn = 1`` over a scan with **no upper bound**,
then filters to the selected window. So an order whose latest-ever Rate-Conf
posting falls *after* the window has its winning row outside the window and is
**dropped from that window entirely**. Measured 2026-08-10: 42 of July's 1,511
DFW orders (2.8%) disappear from Podium's July for this reason, and that number
keeps growing as orders get re-confirmed — a past month's figure silently
shrinks after the fact, and the booker loses credit for a load they did book.

This report instead ranks **within the window**: the winning posting is the
latest one *inside* ``[start, end]``. Every window is therefore self-contained
and stable over time.

Consequence to know: an order re-confirmed in a later month counts in BOTH
months, so **summing per-month windows double-counts those orders**. Use one
window, not a sum of windows.

For ``today`` / ``wtd`` / ``mtd`` the two definitions are provably identical —
no posting can exist after "now" — and parity with Podium on loads, profit and
margin is asserted by the replay. The divergence is confined to Custom ranges
over past periods. (Decision: Diego, 2026-08-10.)

What this report adds on top of Podium:

* **Server-side** Customer / Contract Type / Posted By multi-selects (Podium
  filters those client-side, which cannot scope a KPI).
* **OTP / OTD** per order, from ``mcleod_gld_scorecard_incidents_portal`` using
  the portal-canonical EDI fail-code lists (same lists as XRay CORP/DFW, Ops
  Portal Overview and the Bonus Calculator).
* **Broken Threshold** — a cross-database join against AP_module's
  ``loads_to_cover.thresh``.
* An **Action Plan** free-text box (per user) and a 10-week trend chart that
  deliberately ignores the date filter.

Data sources
------------
``aivn_datalake_gold`` via ``get_datalake_gold_pool`` (bookings + incidents) and
``unilink_portal_ap`` via ``get_ap_pool`` (thresholds). Both pools already exist
— no new env var.

⚠ **Two different databases, so the threshold join CANNOT be SQL.** Bookings are
in ``aivn_datalake_gold``; ``loads_to_cover`` lives in the AP_module app DB.
The merge happens in Python, keyed on ``TRIM(v4.id) == loads_to_cover
.mcleod_order_id`` (verified 2026-08-10: zero duplicate keys, ~61% of DFW
bookings carry a threshold).

Threshold semantics (verified against AP_module, 2026-08-10)
------------------------------------------------------------
``loads_to_cover.thresh`` is **hand-entered** in the Loads-to-Cover screen
(numeric(10,2), $100–$9,999, RBAC ``loads.thresh``) — there is no rate model and
no ETL behind it. A load only has a threshold if it passed through Loads to
Cover *and* somebody typed one. So ``broken_threshold`` is always reported
alongside ``threshold_orders`` (its true denominator); rendering the count on
its own would imply a coverage this data does not have.

⚠ The AP pool is **optional**. If ``AP_DATABASE_URL`` is unset — or the AP query
fails — thresholds come back ``None``, ``broken_threshold`` is ``None`` and the
UI renders an em-dash. The report must never 503 because a *secondary* source is
down; that is the ``§5``-style isolation the portal learned the hard way.

OTP / OTD semantics
-------------------
Portal-canonical: the incidents table records **failures**, so
``otp = 1 − late_orders / orders``. An order with no incident row counts as on
time, which matches every other report here — but it also means freshly booked
loads that have not been picked up yet read as on-time, so a ``Today`` window
will sit near 100%. Stated in the report note and in the UI tooltip rather than
silently "fixed" into a second, divergent definition.

KPI == detail (§16): the OTP/OTD KPIs are aggregated from the *same* per-order
booleans the table renders, so a KPI can never disagree with the rows below it.
"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field

from app.clock import cst_today
from app.datalake import pad_variants as _pad_variants
from app.routers.deps import (
    get_ap_pool,
    get_datalake_gold_pool,
    get_pool,
    require_report_access,
)

import logging

logger = logging.getLogger(__name__)

router = APIRouter(
    tags=["booker-performance-scorecard"],
    prefix="/custom/booker-performance-scorecard",
)

REPORT_KEY = "booker-performance-scorecard"

# --------------------------------------------------------------------------
# Scope — identical to Podium Set DFW so the two reports cannot disagree.
# --------------------------------------------------------------------------
YEAR_START = date(2026, 1, 1)
YEAR_END = date(2026, 12, 31)
BOOKER_TEAMS = ("TEAM-DFW",)

# Weeks shown by the trend chart (Bruno Request 6: "last 10 weeks").
TREND_WEEKS = 10

# Portal-canonical on-time EDI fail codes. Duplicated verbatim from
# xray_corp / xray_dfw / ops_portal_overview — a code-list edit must land in
# every copy or the reports silently disagree.
OTP_CODES = ("T4", "T3", "D1", "D2", "BO", "BE", "AL", "AI", "AH", "AF", "A5", "A2")
OTD_CODES = (
    "AL", "D2", "AZ", "AH", "BE", "D1", "A5", "AI", "AF", "A2", "A1", "AU", "U3",
)
PU_STOPS = ("PU", "SH")
DEL_STOPS = ("CO", "SO")

# Scenario tab (Bruno PDF 2026-08-18 R1/R2): three fixed what-if steps.
# A WHITELIST, not a free float: the tab exists to answer "what if we shaved a
# fixed amount off carrier pay", and the three buttons are the question asked.
# Accepting an arbitrary ?adjustment= would let a hand-crafted URL render a
# fictional scenario that screenshots exactly like the real report.
SCENARIO_STEPS = (15.0, 25.0, 50.0)
ALLOWED_ADJUSTMENTS = (0.0,) + SCENARIO_STEPS

# Table page size. KPIs and the Totals row are always full-universe (§44).
MAX_PAGE = 500


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------


def _iso(d) -> Optional[str]:
    if d is None:
        return None
    if isinstance(d, (datetime, date)):
        return d.isoformat()
    return str(d)


def _fl(v) -> Optional[float]:
    """asyncpg Numeric -> float, guarding NaN/Inf so JSON stays valid (§4)."""
    if v is None:
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    if f != f or f in (float("inf"), float("-inf")):
        return None
    return f


def _clamp(d: Optional[date], default: date) -> date:
    if d is None:
        return default
    if d < YEAR_START:
        return YEAR_START
    if d > YEAR_END:
        return YEAR_END
    return d


def _resolve_range(
    rng: Optional[str],
    start_date: Optional[date],
    end_date: Optional[date],
) -> tuple[date, date]:
    """Today / Week to date / Month to date / Custom (Bruno Request 2).

    Week is Monday-anchored, matching every other report in the portal.
    ``cst_today()`` — never ``date.today()``: Render and Aiven run UTC, so
    between 18:00 and 23:59 CST a naive clock labels today as yesterday (§2).
    """
    today = cst_today()
    today_clamped = max(YEAR_START, min(YEAR_END, today))
    if rng == "today":
        return today_clamped, today_clamped
    if rng == "wtd":
        monday = today_clamped - timedelta(days=today_clamped.weekday())
        return max(YEAR_START, monday), today_clamped
    if rng == "custom":
        s = _clamp(start_date, YEAR_START)
        e = _clamp(end_date, YEAR_END)
        if e < s:
            s, e = e, s
        return s, e
    # default: month to date
    return today_clamped.replace(day=1), today_clamped


def _parse_multi(raw: Optional[list[str]]) -> list[str]:
    """Repeated query params -> clean list.

    NEVER ``.split(",")`` — customer names legitimately contain commas
    ("CONAGRA FOODS PACKAGED FOODS, LLC") and comma-splitting silently renders
    the whole report empty with no error (§45).
    """
    if not raw:
        return []
    seen: set[str] = set()
    out: list[str] = []
    for v in raw:
        v = (v or "").strip()
        if v and v not in seen:
            seen.add(v)
            out.append(v)
    return out


def _base_sql(
    params: list,
    *,
    start: date,
    end: date,
    contract_types: list[str],
    customers: list[str],
    posted_by: list[str],
) -> str:
    """Build the shared ``WITH base AS (...)`` prelude and append its params.

    EVERY endpoint in this router builds its universe through this one helper,
    so the KPI cards, the table, the Totals row and the drill-through can never
    apply a different scope to the same question (§16).

    Returns the CTE text; the caller appends its own ``SELECT ... FROM base``.
    """
    params.append(_pad_variants(list(BOOKER_TEAMS), width=8))
    p_teams = len(params)
    params.append(datetime.combine(start, time.min))
    p_start = len(params)
    params.append(datetime.combine(end, time.max))
    p_end = len(params)

    # Optional filters. An empty selection means "no predicate", so the
    # picker's default state cannot narrow the universe.
    extra: list[str] = []
    if contract_types:
        params.append(contract_types)
        extra.append(f"br.contract_type_descr = ANY(${len(params)}::text[])")
    if customers:
        params.append(customers)
        extra.append(f"br.customer_name = ANY(${len(params)}::text[])")
    if posted_by:
        params.append(posted_by)
        # posted_by_name is compared TRIM-less against pre-trimmed UI values;
        # the column is free text (not indexed), so TRIM here costs nothing
        # sargability-wise and is the only way to match what the user picked.
        extra.append(f"TRIM(rp.posted_by_name) = ANY(${len(params)}::text[])")
    extra_sql = ("\n          AND " + "\n          AND ".join(extra)) if extra else ""

    params.append(_pad_variants(list(PU_STOPS), width=2))
    p_pu = len(params)
    params.append(_pad_variants(list(OTP_CODES), width=40))
    p_otp = len(params)
    params.append(_pad_variants(list(DEL_STOPS), width=2))
    p_del = len(params)
    params.append(_pad_variants(list(OTD_CODES), width=40))
    p_otd = len(params)

    return f"""
    rate_conf AS MATERIALIZED (
        SELECT
            TRIM(rp.id)              AS order_id,
            rp.posted_date           AS posted_date,
            TRIM(rp.posted_by_name)  AS posted_by,
            br.team                  AS team,
            br.customer_name         AS customer,
            br.contract_type_descr   AS contract_type,
            TRIM(br.company_id)      AS company_key,
            br.margin_amt::float     AS profit,
            br.total_charge::float   AS revenue,
            rp.rc_count              AS rc_count
        FROM (
            SELECT id, posted_date, posted_by_name,
                   -- Still EXACTLY ONE row per order, and still the latest
                   -- posting *inside* [start, end]: in-window rows sort first,
                   -- so rn = 1 lands on the newest of them whenever the order
                   -- has any. Paired with `in_window > 0` below, this
                   -- reproduces the previous windowed ROW_NUMBER exactly
                   -- (replayed against live gold 2026-08-19: 855 orders /
                   -- USD 132,673.00 profit, identical to the old shape).
                   -- NB: no '$' in these comments — a literal $1 in prose reads
                   -- as a placeholder to any tool that substitutes params.
                   --
                   -- ROW_NUMBER, never `posted_date = MAX(...)`: 14 orders
                   -- carry two Rate-Conf postings sharing one timestamp, and
                   -- matching on the value would emit both and double-count.
                   ROW_NUMBER() OVER (
                       PARTITION BY id
                       ORDER BY (posted_date >= ${p_start}::timestamp) DESC,
                                posted_date DESC
                   ) AS rn,
                   -- Bruno PDF 2026-08-19 — "RC" column + "Recoveries" KPI.
                   -- Rate-Conf postings on this order AS OF THE WINDOW END. For
                   -- today / WTD / MTD that is identical to all-time; for a past
                   -- Custom window it is STABLE — a re-confirmation next month
                   -- can never retroactively change a closed month, which is the
                   -- same self-contained-window guarantee the rn choice above
                   -- makes. Counting only inside the window instead would miss
                   -- every recovery that straddles a month boundary (measured
                   -- MTD 2026-08: 206 recoveries as-of vs 165 in-window).
                   COUNT(*) OVER (PARTITION BY id)::int AS rc_count,
                   COUNT(*) FILTER (WHERE posted_date >= ${p_start}::timestamp)
                            OVER (PARTITION BY id)::int AS in_window
            FROM public.mcleod_gld_order_post_hist
            WHERE TRIM(posted_type) = 'C'
              AND TRIM(comments)    = 'Rate Conf Received'
              -- ⚠ There is NO index to be sargable against here:
              -- mcleod_gld_order_post_hist (1.9M rows / 455 MB) carries only
              -- the (comment_id, company_id) PK, and TRIM(posted_type) /
              -- TRIM(comments) are unindexable expressions — every execution is
              -- a full sequential scan (~2-3s). The bound is still written
              -- un-cast (§43) so it stays sargable if an index on posted_date
              -- is ever added, but the real mitigation is running this CTE as
              -- FEW TIMES AS POSSIBLE: one pass per endpoint, folded in Python.
              --
              -- ⚠ The LOWER bound is deliberately absent: rc_count must see
              -- postings from BEFORE the window. All three window functions
              -- share `PARTITION BY id`, so they collapse into one WindowAgg
              -- over the SAME single scan — the count is free. Do NOT "fix"
              -- this by adding a second CTE that re-counts: a materialised
              -- two-pass variant was measured and timed out past 30s.
              AND posted_date <= ${p_end}::timestamp
        ) rp
        LEFT JOIN public.mcleod_gld_budget_report_v4 br
               ON TRIM(rp.id) = TRIM(br.id)
        WHERE rp.rn = 1
          -- Keeps the universe exactly as before: orders with at least one
          -- Rate-Conf posting inside the window. Without this the widened scan
          -- would drag in every order ever confirmed before `start`.
          AND rp.in_window > 0
          AND br.team_id = ANY(${p_teams}::text[])
          AND br.status <> 'V'{extra_sql}
    ),
    sc AS (
        -- Incidents are FAILURES. Restricted to the orders already in scope, so
        -- the scan never widens past the selected window.
        SELECT
            TRIM(i.id)         AS id_key,
            TRIM(i.company_id) AS company_key,
            COUNT(*) FILTER (
                WHERE i.stop_type = ANY(${p_pu}::text[])
                  AND i.edi_standard_code = ANY(${p_otp}::text[])
            ) AS otp_fail,
            COUNT(*) FILTER (
                WHERE i.stop_type = ANY(${p_del}::text[])
                  AND i.edi_standard_code = ANY(${p_otd}::text[])
            ) AS otd_fail
        FROM public.mcleod_gld_scorecard_incidents_portal i
        JOIN rate_conf rc
          ON TRIM(i.id) = rc.order_id
         AND TRIM(i.company_id) = rc.company_key
        GROUP BY 1, 2
    ),
    base AS (
        SELECT
            rc.*,
            -- Carrier Cost = Revenue − Profit (Bruno Request 3).
            CASE WHEN rc.revenue IS NULL OR rc.profit IS NULL
                 THEN NULL ELSE rc.revenue - rc.profit END AS carrier_cost,
            (COALESCE(sc.otp_fail, 0) = 0) AS otp_on_time,
            (COALESCE(sc.otd_fail, 0) = 0) AS otd_on_time
        FROM rate_conf rc
        LEFT JOIN sc
               ON sc.id_key = rc.order_id
              AND sc.company_key = rc.company_key
    )
    """


async def _thresholds(request: Request, order_ids: list[str]) -> Optional[dict[str, float]]:
    """order_id -> threshold, read from AP_module's ``loads_to_cover``.

    Returns ``None`` (not ``{}``) when the AP source is unavailable, so callers
    can tell "no threshold data at all" apart from "these orders have none" —
    the difference between rendering an em-dash and rendering a real zero.

    Never raises: a threshold is a *secondary* enrichment and must not be able
    to take the whole report down.
    """
    if not order_ids:
        return {}
    try:
        pool = get_ap_pool(request)
    except Exception:
        logger.warning("booker-scorecard: AP pool unavailable, thresholds omitted")
        return None
    try:
        rows = await pool.fetch(
            """
            SELECT mcleod_order_id, thresh
            FROM public.loads_to_cover
            WHERE mcleod_order_id = ANY($1::text[])
              AND thresh IS NOT NULL
            """,
            order_ids,
        )
    except Exception as e:  # pragma: no cover - defensive
        logger.warning(
            "booker-scorecard: threshold lookup failed (%s: %s)",
            type(e).__name__,
            e,
        )
        return None
    out: dict[str, float] = {}
    for r in rows:
        v = _fl(r["thresh"])
        if v is not None:
            out[r["mcleod_order_id"]] = v
    return out


def _recoveries(rows) -> int:
    """Orders that were rate-confirmed MORE THAN ONCE — the "Recoveries" KPI.

    Bruno PDF 2026-08-19 R1: "count the number of orders that have more than one
    'Rate Conf Received' comment". One order = one recovery no matter how many
    times it was re-confirmed (the observed maximum is 5), so this is a count of
    orders, never a sum of comments.

    ONE named definition, folded by BOTH ``/summary`` and ``/orders`` (§69), so
    the KPI card and the table's Totals row cannot drift apart — and both read
    the very same ``rc_count`` the RC column renders, which makes KPI == detail
    true by construction rather than by coincidence (§16).
    """
    return sum(1 for r in rows if (r["rc_count"] or 0) > 1)


def _threshold_stats(
    rows, thresholds: Optional[dict[str, float]]
) -> dict[str, Optional[float]]:
    """Every threshold-derived figure, from ONE pass over ONE row set.

    - ``broken_threshold``     orders where ``carrier_cost > thresh``
    - ``threshold_orders``     the honest denominator: orders having BOTH numbers
    - ``broken_threshold_pct`` broken / comparable, as a fraction
    - ``cost_saving``          Σ (thresh − carrier_cost) where cost is UNDER it
    - ``under_threshold``      how many orders contributed to that sum

    Deliberately one function rather than two (§69): "broken" and "saving" are
    the two sides of the same comparison, and computing them apart would let
    them disagree about which orders were comparable at all. An order sitting
    exactly ON its threshold is neither broken nor saving — it contributes 0.

    Every value is ``None`` when the AP source is down, so the UI can render an
    em-dash instead of a zero that reads as "nothing was over budget".
    """
    if thresholds is None:
        return {
            "broken_threshold": None,
            "threshold_orders": None,
            "broken_threshold_pct": None,
            "cost_saving": None,
            "under_threshold": None,
        }
    broken = 0
    comparable = 0
    under = 0
    saving = 0.0
    for r in rows:
        t = thresholds.get(r["order_id"])
        cc = _fl(r["carrier_cost"])
        if t is None or cc is None:
            continue
        comparable += 1
        if cc > t:
            broken += 1
        elif cc < t:
            under += 1
            saving += t - cc
    return {
        "broken_threshold": broken,
        "threshold_orders": comparable,
        # Computed HERE, not in the browser, so the KPI card and the table's
        # totals row cannot drift apart (§16/§69).
        "broken_threshold_pct": (broken / comparable) if comparable else None,
        "cost_saving": saving,
        "under_threshold": under,
    }


def _resolve_adjustment(value: Optional[float]) -> float:
    """Validate ?adjustment= against the whitelist. 0 means "no scenario"."""
    if value is None:
        return 0.0
    for allowed in ALLOWED_ADJUSTMENTS:
        if abs(value - allowed) < 1e-9:
            return allowed
    raise HTTPException(
        status_code=400,
        detail=(
            "adjustment must be one of "
            + ", ".join(str(int(a)) for a in ALLOWED_ADJUSTMENTS)
        ),
    )


def _apply_scenario(rows, adjustment: float):
    """Per-order what-if: profit +adjustment, carrier cost −adjustment.

    **Revenue is invariant by construction.** ``carrier_cost`` is derived as
    ``revenue − profit``, so adding the delta to one side and subtracting it
    from the other leaves revenue untouched — which is the whole point: this
    models negotiating carrier pay down, not charging the customer more.

    Returns the rows UNTOUCHED at adjustment 0, so the Scenario tab at zero and
    the Scorecard tab run byte-identical arithmetic rather than merely similar
    arithmetic (§69). Both Records and dicts support ``r["col"]``, so every
    caller downstream is indifferent to which it gets.

    A NULL stays NULL: an order McLeod has no margin for must not be handed a
    fabricated one just because a scenario was selected.
    """
    if not adjustment:
        return rows
    adjusted = []
    for r in rows:
        d = dict(r)
        profit = _fl(d.get("profit"))
        cost = _fl(d.get("carrier_cost"))
        d["profit"] = None if profit is None else profit + adjustment
        d["carrier_cost"] = None if cost is None else cost - adjustment
        adjusted.append(d)
    return adjusted


# --------------------------------------------------------------------------
# /filters — picker options for the selected window
# --------------------------------------------------------------------------


@router.get("/filters")
async def filters(
    request: Request,
    range: Optional[str] = Query("mtd"),
    start_date: Optional[date] = Query(None),
    end_date: Optional[date] = Query(None),
    _user: dict = Depends(require_report_access(REPORT_KEY)),
):
    """Distinct Customer / Contract Type / Posted By inside the date window.

    The multi-selects are deliberately NOT applied here — otherwise picking one
    customer would shrink the customer list to that single option.
    """
    pool = get_datalake_gold_pool(request)
    s, e = _resolve_range(range, start_date, end_date)

    params: list = []
    cte = _base_sql(
        params, start=s, end=e, contract_types=[], customers=[], posted_by=[]
    )
    rows = await pool.fetch(
        f"""
        WITH {cte}
        SELECT DISTINCT customer, contract_type, posted_by FROM base
        """,
        *params,
    )

    customers = sorted({r["customer"] for r in rows if r["customer"]})
    contract_types = sorted({r["contract_type"] for r in rows if r["contract_type"]})
    posters = sorted({r["posted_by"] for r in rows if r["posted_by"]})

    return {
        "success": True,
        "data": {
            "customers": customers,
            "contract_types": contract_types,
            "posted_by": posters,
            "year_start": YEAR_START.isoformat(),
            "year_end": YEAR_END.isoformat(),
            "window": {"start": s.isoformat(), "end": e.isoformat()},
        },
    }


# --------------------------------------------------------------------------
# /summary — the seven KPI cards (Bruno Request 3)
# --------------------------------------------------------------------------


@router.get("/summary")
async def summary(
    request: Request,
    range: Optional[str] = Query("mtd"),
    start_date: Optional[date] = Query(None),
    end_date: Optional[date] = Query(None),
    contract_type: Optional[list[str]] = Query(None),
    customer_name: Optional[list[str]] = Query(None),
    posted_by: Optional[list[str]] = Query(None),
    adjustment: Optional[float] = Query(None),
    _user: dict = Depends(require_report_access(REPORT_KEY)),
):
    """Full-universe KPIs for the selected scope.

    Every figure here is computed over the whole filtered set, never over the
    table's current page (§44). The OTP/OTD percentages are aggregated from the
    same per-order booleans ``/orders`` renders, so KPI == detail by
    construction (§16).
    """
    pool = get_datalake_gold_pool(request)
    s, e = _resolve_range(range, start_date, end_date)
    adj = _resolve_adjustment(adjustment)
    contracts = _parse_multi(contract_type)
    customers = _parse_multi(customer_name)
    posters = _parse_multi(posted_by)

    params: list = []
    cte = _base_sql(
        params,
        start=s,
        end=e,
        contract_types=contracts,
        customers=customers,
        posted_by=posters,
    )

    # ⚠ ONE scan, aggregated in Python — not SQL-aggregate + a second pass for
    # the threshold ids. `mcleod_gld_order_post_hist` is 1.9M rows / 455 MB with
    # NO index on posted_date (its only index is the (comment_id, company_id)
    # PK), and `TRIM(posted_type)`/`TRIM(comments)` are unindexable expressions,
    # so every execution of this CTE is a full sequential scan. Each extra
    # statement is another one, on a 0.5-CPU Render dyno, against the proxy's
    # 45s abort — which is never retried. The row set is small enough to fold in
    # Python (12.5k rows for a full-year window).
    rows = await pool.fetch(
        f"""
        WITH {cte}
        SELECT order_id, carrier_cost, profit, revenue, otp_on_time, otd_on_time,
               rc_count
        FROM base
        """,
        *params,
    )

    # Scenario what-if, applied ONCE here so every figure below — margin, avg
    # margin/load, broken threshold, cost saving — derives from the same
    # adjusted rows. At adjustment 0 this is the identity function.
    rows = _apply_scenario(rows, adj)

    orders = len(rows)
    profit = sum(_fl(r["profit"]) or 0.0 for r in rows)
    revenue = sum(_fl(r["revenue"]) or 0.0 for r in rows)
    otp_on_time = sum(1 for r in rows if r["otp_on_time"])
    otd_on_time = sum(1 for r in rows if r["otd_on_time"])

    thresholds = await _thresholds(request, [r["order_id"] for r in rows])
    stats = _threshold_stats(rows, thresholds)

    return {
        "success": True,
        "data": {
            "orders": orders,
            "profit": profit,
            "revenue": revenue,
            # Margin % = Σ profit / Σ revenue — a ratio of sums, never a mean
            # of per-order ratios.
            "margin_pct": (profit / revenue) if revenue else None,
            "avg_margin_per_load": (profit / orders) if orders else None,
            # broken_threshold / threshold_orders / broken_threshold_pct /
            # cost_saving / under_threshold — see _threshold_stats.
            **stats,
            "otp_pct": (otp_on_time / orders) if orders else None,
            "otd_pct": (otd_on_time / orders) if orders else None,
            # Unaffected by `adjustment` on purpose: a scenario shifts money
            # between profit and carrier cost, it does not un-post a rate conf.
            "recoveries": _recoveries(rows),
            "adjustment": adj,
            "window": {"start": s.isoformat(), "end": e.isoformat()},
        },
    }


# --------------------------------------------------------------------------
# /orders — the detail table (Bruno Request 4)
# --------------------------------------------------------------------------

_ORDERS_SORT: dict[str, str] = {
    "posted_desc": "posted_date DESC NULLS LAST",
    "posted_asc": "posted_date ASC NULLS LAST",
    "order_desc": "order_id DESC",
    "order_asc": "order_id ASC",
    "profit_desc": "profit DESC NULLS LAST",
    "profit_asc": "profit ASC NULLS LAST",
    "revenue_desc": "revenue DESC NULLS LAST",
    "revenue_asc": "revenue ASC NULLS LAST",
    "cost_desc": "carrier_cost DESC NULLS LAST",
    "cost_asc": "carrier_cost ASC NULLS LAST",
}


@router.get("/orders")
async def orders(
    request: Request,
    range: Optional[str] = Query("mtd"),
    start_date: Optional[date] = Query(None),
    end_date: Optional[date] = Query(None),
    contract_type: Optional[list[str]] = Query(None),
    customer_name: Optional[list[str]] = Query(None),
    posted_by: Optional[list[str]] = Query(None),
    sort: str = Query("posted_desc"),
    page: int = Query(1, ge=1),
    limit: int = Query(200, ge=1, le=MAX_PAGE),
    adjustment: Optional[float] = Query(None),
    _user: dict = Depends(require_report_access(REPORT_KEY)),
):
    """Paginated order rows + a full-universe Totals row.

    ⚠ ``totals`` is a **server-side aggregate over every matching order**, not a
    client-side reduce of the current page (§44) — a Totals row that only sums
    what you can see is a lie the moment the table paginates.
    """
    pool = get_datalake_gold_pool(request)
    s, e = _resolve_range(range, start_date, end_date)
    adj = _resolve_adjustment(adjustment)
    contracts = _parse_multi(contract_type)
    customers = _parse_multi(customer_name)
    posters = _parse_multi(posted_by)
    # Sorting stays in SQL even under a scenario: the adjustment is the SAME
    # constant on every order, and a constant shift is monotonic, so ordering by
    # the unadjusted profit / carrier_cost is identical to ordering by the
    # adjusted ones. Revenue is invariant. Re-sorting in Python would only be
    # able to sort the current page — i.e. wrongly.
    order_by = _ORDERS_SORT.get(sort, _ORDERS_SORT["posted_desc"])

    params: list = []
    cte = _base_sql(
        params,
        start=s,
        end=e,
        contract_types=contracts,
        customers=customers,
        posted_by=posters,
    )

    offset = (page - 1) * limit
    params.append(limit)
    p_limit = len(params)
    params.append(offset)
    p_offset = len(params)

    rows = await pool.fetch(
        f"""
        WITH {cte}
        SELECT order_id, team, customer, posted_by, posted_date,
               revenue, carrier_cost, profit, otp_on_time, otd_on_time,
               contract_type, rc_count
        FROM base
        ORDER BY {order_by}, order_id DESC
        LIMIT ${p_limit} OFFSET ${p_offset}
        """,
        *params,
    )

    # Full-universe pass — ONE scan serving both the Totals row and the
    # cross-database threshold merge (see /summary for why extra scans are
    # expensive here). `params[:-2]` drops LIMIT/OFFSET: they are appended
    # strictly after the CTE's params, so the slice is an exact prefix whose
    # length equals the highest placeholder the CTE text references.
    agg_params = params[:-2]
    all_rows = await pool.fetch(
        f"""
        WITH {cte}
        SELECT order_id, carrier_cost, profit, revenue, otp_on_time, otd_on_time,
               rc_count
        FROM base
        """,
        *agg_params,
    )

    # Same helper, same order, on BOTH row sets — the page the user reads and
    # the full universe the Totals row sums. Applying it to only one of them is
    # exactly how a totals row starts contradicting the rows above it (§16).
    rows = _apply_scenario(rows, adj)
    all_rows = _apply_scenario(all_rows, adj)

    total = len(all_rows)
    thresholds = await _thresholds(request, [r["order_id"] for r in all_rows])
    stats = _threshold_stats(all_rows, thresholds)

    out_rows = [
        {
            "order_id": r["order_id"],
            "team": r["team"],
            "customer": r["customer"],
            "posted_by": r["posted_by"],
            "posted_date": _iso(r["posted_date"]),
            "contract_type": r["contract_type"],
            "revenue": _fl(r["revenue"]),
            "carrier_cost": _fl(r["carrier_cost"]),
            "profit": _fl(r["profit"]),
            "otp_on_time": r["otp_on_time"],
            "otd_on_time": r["otd_on_time"],
            # "RC" (Bruno PDF 2026-08-19 R2) — Rate-Conf postings on this order
            # as of the window end. > 1 is what the Recoveries KPI counts.
            "rc_count": r["rc_count"],
            # None when the AP source is unavailable OR this order never had a
            # threshold typed — both render as an em-dash.
            "threshold": None if thresholds is None else thresholds.get(r["order_id"]),
        }
        for r in rows
    ]

    # Folded in Python from the single full-universe pass above. `_fl(...) or 0`
    # keeps a NaN `numeric` (Postgres allows 'NaN') from poisoning the sum and
    # turning a division into a TypeError → 500.
    revenue = sum(_fl(r["revenue"]) or 0.0 for r in all_rows)
    profit = sum(_fl(r["profit"]) or 0.0 for r in all_rows)
    carrier_cost = sum(_fl(r["carrier_cost"]) or 0.0 for r in all_rows)
    otp_on_time = sum(1 for r in all_rows if r["otp_on_time"])
    otd_on_time = sum(1 for r in all_rows if r["otd_on_time"])

    return {
        "success": True,
        "data": {
            "rows": out_rows,
            "totals": {
                "orders": total,
                "revenue": revenue,
                "carrier_cost": carrier_cost,
                "profit": profit,
                "margin_pct": (profit / revenue) if revenue else None,
                "otp_pct": (otp_on_time / total) if total else None,
                "otd_pct": (otd_on_time / total) if total else None,
                # Same helper, same full-universe rows as /summary (§69).
                "recoveries": _recoveries(all_rows),
                **stats,
            },
            "adjustment": adj,
            "thresholds_available": thresholds is not None,
            "window": {"start": s.isoformat(), "end": e.isoformat()},
        },
        "meta": {"total": total, "page": page, "limit": limit},
    }


# --------------------------------------------------------------------------
# /weekly — 10-week trend (Bruno Request 6)
# --------------------------------------------------------------------------


@router.get("/weekly")
async def weekly(
    request: Request,
    contract_type: Optional[list[str]] = Query(None),
    customer_name: Optional[list[str]] = Query(None),
    posted_by: Optional[list[str]] = Query(None),
    _user: dict = Depends(require_report_access(REPORT_KEY)),
):
    """Bars = # Orders, lines = OTP / OTD, by week, last 10 weeks.

    ⚠ Deliberately takes **no date parameters at all** (Bruno: "the chart should
    not be affected by the Date filter"). Declaring them and ignoring them would
    be the same trap as §55 in reverse — the window is fixed here, in the
    endpoint, so no caller can widen it by hand-crafting a URL.

    The other three filters DO apply: excluding the date filter was the stated
    exception, not a blanket opt-out.

    Weeks are Monday-anchored and every one of the last 10 is emitted, including
    weeks with zero bookings — a gap-free axis is what makes a trend readable.
    """
    pool = get_datalake_gold_pool(request)
    contracts = _parse_multi(contract_type)
    customers = _parse_multi(customer_name)
    posters = _parse_multi(posted_by)

    today = cst_today()
    this_monday = today - timedelta(days=today.weekday())
    first_monday = this_monday - timedelta(weeks=TREND_WEEKS - 1)
    # Clamped for the query, but the emitted axis always spans TREND_WEEKS.
    s = max(YEAR_START, first_monday)
    e = min(YEAR_END, today)

    params: list = []
    cte = _base_sql(
        params,
        start=s,
        end=e,
        contract_types=contracts,
        customers=customers,
        posted_by=posters,
    )
    rows = await pool.fetch(
        f"""
        WITH {cte}
        SELECT
            date_trunc('week', posted_date)::date AS week_start,
            COUNT(*)                              AS orders,
            COUNT(*) FILTER (WHERE otp_on_time)   AS otp_on_time,
            COUNT(*) FILTER (WHERE otd_on_time)   AS otd_on_time
        FROM base
        GROUP BY 1
        ORDER BY 1
        """,
        *params,
    )
    by_week = {r["week_start"]: r for r in rows}

    buckets = []
    for i in range(TREND_WEEKS):
        wk = first_monday + timedelta(weeks=i)
        r = by_week.get(wk)
        n = int(r["orders"]) if r else 0
        buckets.append(
            {
                "week_start": wk.isoformat(),
                "label": f"{wk.month}/{wk.day}",
                "orders": n,
                "otp_pct": (int(r["otp_on_time"]) / n) if r and n else None,
                "otd_pct": (int(r["otd_on_time"]) / n) if r and n else None,
            }
        )

    return {
        "success": True,
        "data": {
            "weeks": buckets,
            "window": {"start": first_monday.isoformat(), "end": today.isoformat()},
        },
    }


# --------------------------------------------------------------------------
# /note — the "Action Plan" box (Bruno Request 5)
# --------------------------------------------------------------------------


class ActionPlanUpsert(BaseModel):
    notes: str = Field(default="", max_length=5000)


@router.get("/note")
async def get_note(
    request: Request,
    user: dict = Depends(require_report_access(REPORT_KEY)),
):
    """This user's Action Plan. Per-user like every other notes box here —
    ``user_id`` is the primary key, so one row per person, never shared."""
    pool = get_pool(request)
    row = await pool.fetchrow(
        "SELECT notes, updated_at FROM booker_scorecard_notes WHERE user_id = $1",
        user["sub"],
    )
    return {
        "success": True,
        "data": {
            "notes": row["notes"] if row else "",
            "updated_at": _iso(row["updated_at"]) if row else None,
        },
    }


@router.put("/note")
async def put_note(
    body: ActionPlanUpsert,
    request: Request,
    user: dict = Depends(require_report_access(REPORT_KEY)),
):
    pool = get_pool(request)
    row = await pool.fetchrow(
        """
        INSERT INTO booker_scorecard_notes (user_id, notes)
        VALUES ($1, $2)
        ON CONFLICT (user_id)
        DO UPDATE SET notes = EXCLUDED.notes, updated_at = NOW()
        RETURNING notes, updated_at
        """,
        user["sub"],
        body.notes,
    )
    return {
        "success": True,
        "data": {"notes": row["notes"], "updated_at": _iso(row["updated_at"])},
    }


# --------------------------------------------------------------------------
# /freshness — visible "Data as of" (§54)
# --------------------------------------------------------------------------

_FRESHNESS_TTL = timedelta(seconds=60)
_freshness_cache: dict[str, object] = {"at": None, "payload": None}


@router.get("/freshness")
async def freshness(
    request: Request,
    _user: dict = Depends(require_report_access(REPORT_KEY)),
):
    """Reports the **stalest** of the three feeds behind this report.

    A page that renders 0 both for "no bookings" and "the pipeline is dead"
    hides an outage indefinitely — that is exactly how a 3-day silent failure
    went unnoticed once. The MAX() is scoped to a recent window so it rides an
    existing index (the ETL stamp columns are unindexed, §54) and the result is
    cached for 60s.
    """
    now = datetime.now()
    cached_at = _freshness_cache.get("at")
    if isinstance(cached_at, datetime) and now - cached_at < _FRESHNESS_TTL:
        return {"success": True, "data": _freshness_cache["payload"]}

    pool = get_datalake_gold_pool(request)
    row = await pool.fetchrow(
        """
        SELECT
          (SELECT MAX(posted_date) FROM public.mcleod_gld_order_post_hist
            WHERE posted_date >= (CURRENT_DATE - 7))                  AS bookings,
          (SELECT MAX(updated_dt) FROM public.mcleod_gld_budget_report_v4
            WHERE origin_actual_departure >= (CURRENT_DATE - 7))      AS production,
          (now() AT TIME ZONE 'America/Chicago')                      AS now_cst
        """
    )
    now_cst = row["now_cst"]

    sources = []
    for key, label in (("bookings", "Bookings"), ("production", "Production")):
        v = row[key]
        sources.append(
            {
                "key": key,
                "label": label,
                "updated_at": _iso(v),
                "age_minutes": _fl((now_cst - v).total_seconds() / 60.0) if v else None,
            }
        )

    # Thresholds live in another database — never let its absence 500 this.
    try:
        ap = get_ap_pool(request)
        # ⚠ AP_module is a Prisma app: `synced_at` is `timestamp WITHOUT time
        # zone` holding **UTC**, unlike the datalake which stores CST. Comparing
        # it raw against a CST clock reports a timestamp 5–6 hours in the future
        # and a negative age. Convert explicitly.
        v = await ap.fetchval(
            """
            SELECT (MAX(synced_at) AT TIME ZONE 'UTC') AT TIME ZONE 'America/Chicago'
            FROM public.loads_to_cover
            """
        )
        sources.append(
            {
                "key": "thresholds",
                "label": "Thresholds",
                "updated_at": _iso(v),
                "age_minutes": _fl((now_cst - v).total_seconds() / 60.0) if v else None,
            }
        )
    except Exception:
        sources.append(
            {
                "key": "thresholds",
                "label": "Thresholds",
                "updated_at": None,
                "age_minutes": None,
            }
        )

    # ⚠ A source with no timestamp is DEAD (the query returned NULL, or it
    # threw) — it is maximally stale, not "not applicable". Filtering it out of
    # the staleness calculation would turn the chip GREEN precisely when a feed
    # stops entirely: e.g. once `posted_date >= CURRENT_DATE - 7` goes empty on
    # day 8 of a bookings outage, the surviving fresh feed would be reported and
    # the outage detector would go quiet. That is the exact §54 failure this
    # panel exists to prevent.
    dead = [s["label"] for s in sources if s["updated_at"] is None]
    aged = [s for s in sources if s["age_minutes"] is not None]
    # Report the OLDEST feed, never MAX() across sources — one fresh feed must
    # not mask three dead ones.
    oldest = max(aged, key=lambda s: s["age_minutes"]) if aged else None
    payload = {
        "sources": sources,
        "as_of": oldest["updated_at"] if oldest else None,
        "age_minutes": oldest["age_minutes"] if oldest else None,
        # A dead feed always wins the "stalest" slot.
        "stalest": dead[0] if dead else (oldest["label"] if oldest else None),
        "unavailable": dead,
        "checked_at": _iso(now_cst),
    }
    _freshness_cache["at"] = now
    _freshness_cache["payload"] = payload
    return {"success": True, "data": payload}
