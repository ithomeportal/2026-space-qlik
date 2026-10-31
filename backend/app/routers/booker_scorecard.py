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
from typing import Annotated, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field

from app.clock import CST, cst_now, cst_today
from app.booker_names import (
    matches_roster as _matches_roster,
    roster_keys as _roster_keys,
)
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


def _lower_bound(v: date) -> datetime:
    """A date means "from its first instant"; a datetime is used as given.

    ⚠ `datetime` IS a `date` subclass, so the isinstance order matters: testing
    `date` first would truncate the Rank tab's Friday 17:01 bound to midnight.
    """
    return v if isinstance(v, datetime) else datetime.combine(v, time.min)


def _upper_bound(v: date) -> datetime:
    """A date means "through its last instant" (inclusive, like before); a
    datetime is an INCLUSIVE upper bound used as given."""
    return v if isinstance(v, datetime) else datetime.combine(v, time.max)


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

    `start` / `end` are calendar dates for every endpoint except /rank, which
    passes naive-CST datetimes (Bruno PDF 2026-10-06: the booking week turns
    over at Friday 17:01). Both bounds are inclusive either way.

    Returns the CTE text; the caller appends its own ``SELECT ... FROM base``.
    """
    params.append(_pad_variants(list(BOOKER_TEAMS), width=8))
    p_teams = len(params)
    params.append(_lower_bound(start))
    p_start = len(params)
    params.append(_upper_bound(end))
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
            -- Bruno PDF 2026-10-28 R2 — Carrier Cost is McLeod's carrier pay,
            -- v4 `override_pay_amt` (one row per order), REPORT-WIDE. It used
            -- to be derived as Revenue − Profit; the two differ wherever the
            -- margin carries anything besides carrier pay. COALESCE to 0: an
            -- order with no carrier pay posted yet costs 0, not "unknown".
            COALESCE(br.override_pay_amt, 0)::float AS override_pay,
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
          AND br.status <> 'V'
          -- Bruno (PDF 2026-08-31 "Booker Performance Scorecard", Scorecard
          -- tab) R1/R2 — placeholder rates are not real bookings. R1: carrier
          -- cost of exactly 0. R2: the hard-coded rate pairs
          -- (revenue 150 / cost 150) and (revenue 250 / cost 150).
          -- Bruno PDF 2026-10-16 R1 adds a third: (revenue 200 / cost 150),
          -- i.e. Profit 50 — "delete these orders" from the KPIs, Rank and
          -- Scenario. McLeod is read-only to us, so "delete" = exclude HERE.
          --
          -- Applied HERE, inside the one CTE every endpoint builds its
          -- universe from, so the Orders page, its full-universe Totals pass,
          -- the KPI cards, the threshold merge, /filters and /weekly cannot end
          -- up with three different populations (§16, §96). Measured MTD
          -- 2026-08: 1,425 → 1,395 orders, profit $312,582 → $295,042.
          --
          -- ⚠ 2026-10-28: these exclusions STAY keyed on
          -- total_charge − margin_amt even though Carrier Cost is now
          -- override_pay_amt (see `override_pay` above). Bruno's placeholder
          -- pairs were identified on the old derived cost, and re-keying them
          -- would silently change WHICH orders are in the universe — the
          -- population is deliberately unchanged by the cost switch.
          --
          -- ⚠ Row-wise IS DISTINCT FROM, never `NOT (a = 150 AND b = 150)`:
          -- against a NULL total_charge the NOT form evaluates to NULL and the
          -- row is DELETED with no error. An order whose revenue has not been
          -- posted yet is real and stays in the universe — only an explicitly
          -- ZERO carrier cost is excluded. NULL is not 0 here.
          AND (br.total_charge - br.margin_amt) IS DISTINCT FROM 0::numeric
          AND (br.total_charge, br.total_charge - br.margin_amt)
                IS DISTINCT FROM (150::numeric, 150::numeric)
          AND (br.total_charge, br.total_charge - br.margin_amt)
                IS DISTINCT FROM (250::numeric, 150::numeric)
          AND (br.total_charge, br.total_charge - br.margin_amt)
                IS DISTINCT FROM (200::numeric, 150::numeric){extra_sql}
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
            -- Carrier Cost = v4 override_pay_amt (Bruno PDF 2026-10-28 R2;
            -- was Revenue − Profit, Bruno Request 3). The ONE column every
            -- consumer reads: Orders column + Totals, /summary threshold
            -- stats, per-row Saving/Overrun/Variance, Rank, Scenario, filters.
            rc.override_pay AS carrier_cost,
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
    - ``compliance_threshold_pct`` 1 − the above (Bruno 2026-08-31 R3), the
      figure the KPI card and the Rank tab now show; also a fraction
    - ``compliant_threshold``  comparable − broken, the COUNT that goes beside
      that percentage. Published here rather than subtracted at the call site
      so the count and the ratio can never span two populations (§96)
    - ``cost_saving``          Σ (thresh − carrier_cost) where cost is UNDER it
    - ``under_threshold``      how many orders contributed to that sum
    - ``cost_overrun``         Σ (thresh − carrier_cost) where cost is OVER it,
      so signed and ≤ 0 (Bruno PDF 2026-10-28 R3). Runs over exactly the
      ``broken_threshold`` orders — that count is the card's sub-line (§96) —
      and equals Σ `_row_cost_overrun` over the same rows, so the KPI card, the
      Totals cell and the column cannot disagree (§16/§69)
    - ``threshold_variance_pct`` 1 − Σ carrier_cost / Σ thresh over the SAME
      comparable population (Bruno PDF 2026-10-28 R4) — the totals-row twin of
      `_row_threshold_variance`. A weighted ratio, never an average of ratios:
      the mean of per-order percentages would let a $900 order outvote a $9,000
      one (§96)

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
            "compliance_threshold_pct": None,
            "compliant_threshold": None,
            "cost_saving": None,
            "under_threshold": None,
            "cost_overrun": None,
            "threshold_variance_pct": None,
        }
    broken = 0
    comparable = 0
    under = 0
    saving = 0.0
    overrun = 0.0
    cost_total = 0.0
    thresh_total = 0.0
    for r in rows:
        t = thresholds.get(r["order_id"])
        cc = _fl(r["carrier_cost"])
        if t is None or cc is None:
            continue
        comparable += 1
        cost_total += cc
        thresh_total += t
        if cc > t:
            broken += 1
            overrun += t - cc
        elif cc < t:
            under += 1
            saving += t - cc
    return {
        "broken_threshold": broken,
        "threshold_orders": comparable,
        # Computed HERE, not in the browser, so the KPI card and the table's
        # totals row cannot drift apart (§16/§69).
        "broken_threshold_pct": (broken / comparable) if comparable else None,
        # Bruno (PDF 2026-08-31, Scorecard tab) R3 — the card is now
        # "Compliance Threshold" = 1 − Broken Threshold. Derived from the SAME
        # two counters rather than recomputed, so the two can never disagree,
        # and kept a FRACTION like every other percentage on this wire —
        # `fmtPct` multiplies by 100 and handing it an already-scaled value
        # prints 100× wrong with no error (§95).
        #
        # ⚠ `broken_threshold` (the raw count) stays on the wire: the Orders
        # table still flags individual orders whose carrier cost exceeds their
        # threshold, which is a ROW fact and keeps its own wording.
        "compliance_threshold_pct": (1.0 - broken / comparable) if comparable else None,
        # The count the Rank tab prints beside that percentage. Derived from
        # the SAME two counters, so "9/12" and "75%" cannot come from two
        # different populations (§96). Orders sitting exactly ON their
        # threshold are compliant — they are not broken — which is why this is
        # `comparable - broken` and NOT `under_threshold` (that one is the
        # strictly-under population the Cost Saving sum runs over).
        # A raw count like `broken_threshold`, not a ratio: 0 comparable
        # orders is 0 compliant orders, while the RATIO above is undefined.
        "compliant_threshold": comparable - broken,
        "cost_saving": saving,
        "under_threshold": under,
        "cost_overrun": overrun,
        # Bruno PDF 2026-09-15 R2, redefined 2026-10-28 R4 — the Totals cell
        # under "Threshold Variance %": 1 − Σcost / Σthresh over the comparable
        # orders ONLY, i.e. the very population `cost_saving` and
        # `compliance_threshold_pct` run over, so the three cells in that
        # corner of the table describe one set of orders (§96).
        #
        # ⚠ `thresh_total` cannot be 0 while `comparable > 0` in practice
        # (AP_module constrains `thresh` to $100-$9,999) but the guard stays:
        # a future row with thresh = 0 would otherwise 500 the whole endpoint.
        "threshold_variance_pct": _variance_fraction(thresh_total, cost_total),
    }


def _variance_fraction(threshold: Optional[float], cost: Optional[float]) -> Optional[float]:
    """1 − cost / threshold, as a signed FRACTION — ONE definition (§69) shared
    by the per-row column and its Totals cell (Bruno PDF 2026-10-28 R4).

    Positive = came in UNDER the threshold (good, green), negative = OVER it
    (red). Compared at CENTS first: a cost equal to its threshold to the cent
    returns exactly 0.0 (yellow), so float noise like 999.9999999 cannot paint
    an on-threshold order green. A fraction because `fmtPct` multiplies by 100
    (§95). ``None`` when either side is missing or the threshold is 0 — a
    ZeroDivisionError here would 500 an endpoint that otherwise degrades
    gracefully through an AP outage.
    """
    if threshold is None or cost is None or threshold == 0:
        return None
    if round(cost, 2) == round(threshold, 2):
        return 0.0
    return 1.0 - cost / threshold


def _row_cost_saving(threshold: Optional[float], cost: Optional[float]) -> Optional[float]:
    """Per-order leg of the Cost Saving KPI (Bruno PDF 2026-09-15 R1).

    Returns the saving ONLY for an order that came in strictly UNDER its
    threshold; ``None`` for a broken order, an order sitting exactly ON its
    threshold, and an order with no threshold at all.

    That asymmetry is the point, not an oversight: summed over EVERY matching
    order this column reproduces `cost_saving` from `_threshold_stats` exactly,
    so the column and the KPI card cannot disagree (§16/§69). ⚠ Over one PAGE
    it sums to a fraction of the card, as any per-row leg of a full-universe
    aggregate does (§44) — that is not a mismatch to "fix". Handing broken
    orders a NEGATIVE saving would read as more information while quietly
    making the column stop adding up to the card above it. Decision: Diego,
    2026-09-15.

    "Broken" is still visible on the row — the Threshold cell goes amber — so
    nothing is hidden by the em-dash; it is carried by the column that already
    owned that fact.
    """
    if threshold is None or cost is None or cost >= threshold:
        return None
    return threshold - cost


def _row_cost_overrun(threshold: Optional[float], cost: Optional[float]) -> Optional[float]:
    """Threshold − Carrier Cost when NEGATIVE, else ``None`` (Bruno PDF 2026-10-16 R2).

    The mirror image of `_row_cost_saving`: an order that came in OVER its
    threshold carries the (negative) overrun, everything else — under, exactly
    on, or no threshold at all — renders "—". Kept negative on purpose: Bruno
    asked for "the calculated value", and the sign is what tells it apart from
    a saving at a glance. The two columns are disjoint, so on any row at most
    one of them is non-null.
    """
    if threshold is None or cost is None or cost <= threshold:
        return None
    return threshold - cost


def _row_threshold_variance(
    threshold: Optional[float], cost: Optional[float]
) -> Optional[float]:
    """1 − Carrier Cost / Threshold, as a signed FRACTION (Bruno PDF 2026-10-28 R4).

    🔴 Redefined 2026-10-28. It was Cost / Threshold (0.94 = good, 1.06 = over);
    it is now the distance from the threshold: T=1000, C=900 → +0.10 (under,
    green); C=1100 → −0.10 (over, red); C == T at cents → 0 (yellow). Higher
    now means BETTER — the `variance_*` sort tokens are unchanged, so
    `variance_desc` now leads with the best orders (nulls still last).

    See `_variance_fraction` for the cents comparison and the None rules.
    """
    return _variance_fraction(threshold, cost)


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

    **Revenue is never touched.** This models negotiating carrier pay down by
    the delta, not charging the customer more: every dollar taken off carrier
    pay lands in profit, so both move by the same amount in opposite
    directions. Since 2026-10-28 ``carrier_cost`` is v4 ``override_pay_amt``
    and no longer equals ``revenue − profit`` — the invariance used to hold by
    construction and now holds because revenue is simply not adjusted. The
    maths does not depend on that identity: the adjusted cost is still the
    order's own cost − delta, and threshold comparisons read that adjusted
    cost directly.

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
# Orders-table value filters (Bruno PDF 2026-10-12, Scenario tab: "Revenue =
# '200', Carrier Cost = '150', Profit = '50'" — per-column amount filters, the
# quoted figures being his example values).
# --------------------------------------------------------------------------

# op token -> predicate over (row value, filter value), both at CENTS. Rounding
# both sides is what lets "= 200" find a $200.00 order whose numeric came back
# as 199.99999999 after the scenario's float arithmetic.
_VALUE_OPS = {
    "eq": lambda v, x: v == x,
    "gte": lambda v, x: v >= x,
    "lte": lambda v, x: v <= x,
}
# Wire prefix -> row column. `cost` is the wire name for `carrier_cost`.
_VALUE_FILTER_COLUMNS = (("revenue", "revenue"), ("cost", "carrier_cost"), ("profit", "profit"))


def _value_filters(
    raw: dict[str, tuple[Optional[str], Optional[float]]],
) -> tuple[tuple[str, str, float], ...]:
    """Validate the per-column filters → ((column, op, cents_value), ...).

    A value with no op means "=" (the PDF's own wording); an op with no value
    is no filter. ⚠ An unknown op is a 400, not a silent no-filter: a table that
    ignores the operator the user picked still renders a plausible list.
    """
    out: list[tuple[str, str, float]] = []
    for wire, column in _VALUE_FILTER_COLUMNS:
        op, value = raw.get(wire, (None, None))
        if op is not None and op not in _VALUE_OPS:
            raise HTTPException(
                status_code=400,
                detail=f"{wire}_op must be one of: {', '.join(_VALUE_OPS)}",
            )
        if value is None:
            continue
        if _fl(value) is None:
            raise HTTPException(status_code=400, detail=f"{wire}_val must be a finite number")
        out.append((column, op or "eq", round(float(value), 2)))
    return tuple(out)


def _apply_value_filters(rows, filters: tuple[tuple[str, str, float], ...]):
    """Keep the rows matching EVERY filter. A NULL amount matches none — an
    order McLeod has no margin for is not "$0 profit". Runs AFTER
    `_apply_scenario`, so it filters the numbers the table is showing."""
    if not filters:
        return rows
    kept = []
    for r in rows:
        ok = True
        for column, op, target in filters:
            v = _fl(r[column])
            if v is None or not _VALUE_OPS[op](round(v, 2), target):
                ok = False
                break
        if ok:
            kept.append(r)
    return kept


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
            # cost_saving / under_threshold / cost_overrun — see _threshold_stats.
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

# Sort token -> (field on the emitted row, descending?).
#
# ⚠ These are PYTHON field names, not SQL fragments — and that is the whole
# point of Bruno's PDF 2026-09-15 R3 ("enable sorting for all columns").
# Four of the fifteen columns — Threshold, Cost Savings, Cost Overrun,
# Threshold Variance % — come from `loads_to_cover` in a DIFFERENT DATABASE and are
# merged in Python (see `_thresholds`), so they do not exist in the SQL result
# at all and `ORDER BY` cannot reach them. Sorting them page-locally would
# reorder 200 rows out of thousands while looking like it sorted everything.
#
# So the whole table now sorts in Python over the full-universe pass this
# endpoint was ALREADY making for its Totals row, and pagination follows the
# sort. That removes the second seq scan of the 1.9M-row
# `mcleod_gld_order_post_hist` rather than adding anything: the endpoint went
# from two scans to one. Measured ceiling on the in-memory set is 14,161 rows
# (every TEAM-DFW rate-conf order in 2026); the window is hard-clamped to one
# calendar year by `_clamp`, so it cannot grow without that constant moving.
_ORDERS_SORT: dict[str, tuple[str, bool]] = {
    "posted_desc": ("posted_date", True),
    "posted_asc": ("posted_date", False),
    "order_desc": ("order_id", True),
    "order_asc": ("order_id", False),
    "team_desc": ("team", True),
    "team_asc": ("team", False),
    "customer_desc": ("customer", True),
    "customer_asc": ("customer", False),
    "poster_desc": ("posted_by", True),
    "poster_asc": ("posted_by", False),
    "rc_desc": ("rc_count", True),
    "rc_asc": ("rc_count", False),
    "profit_desc": ("profit", True),
    "profit_asc": ("profit", False),
    "revenue_desc": ("revenue", True),
    "revenue_asc": ("revenue", False),
    "cost_desc": ("carrier_cost", True),
    "cost_asc": ("carrier_cost", False),
    "otp_desc": ("otp_on_time", True),
    "otp_asc": ("otp_on_time", False),
    "otd_desc": ("otd_on_time", True),
    "otd_asc": ("otd_on_time", False),
    "threshold_desc": ("threshold", True),
    "threshold_asc": ("threshold", False),
    "saving_desc": ("cost_saving", True),
    "saving_asc": ("cost_saving", False),
    "overrun_desc": ("cost_overrun", True),
    "overrun_asc": ("cost_overrun", False),
    "variance_desc": ("threshold_variance_pct", True),
    "variance_asc": ("threshold_variance_pct", False),
}


def _sort_orders(rows: list[dict], sort: str) -> list[dict]:
    """Order the full universe by one column, NULLS LAST in BOTH directions.

    ⚠ The nulls-last part is not decoration. The Rank tab shipped a
    ``?? POSITIVE_INFINITY`` sentinel whose own comment claimed it sorted nulls
    last both ways; it sorts them last ASCENDING and FIRST descending. Harmless
    while that column read "Broken Threshold", and actively wrong the day it was
    renamed to "Compliance Threshold" — every booker with no threshold coverage
    would have led a table headed "most compliant". Only ~61% of DFW bookings
    carry a threshold, so three of this table's columns are null on roughly two
    rows in five: a sentinel here would put the least-informative rows on top of
    the default descending view of each of them.

    Partitioning instead of sentinel-substituting also keeps the comparison
    type-clean — no float sentinel ever meets a date string or a bool.

    Ties break on ``order_id`` DESC, applied FIRST and relied on through
    Python's stable sort, exactly as the old SQL `ORDER BY {col}, order_id DESC`
    did — so a page boundary cannot shuffle between two requests that sort on a
    column with many equal values (every OTP/OTD sort is exactly that case: two
    distinct values across thousands of rows).
    """
    field, desc = _ORDERS_SORT[sort]
    present = [r for r in rows if r.get(field) is not None]
    missing = [r for r in rows if r.get(field) is None]
    for bucket in (present, missing):
        bucket.sort(key=lambda r: r["order_id"], reverse=True)
    present.sort(key=lambda r: r[field], reverse=desc)
    present.extend(missing)
    return present


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
    # Bruno PDF 2026-10-12 — Orders-table amount filters. ⚠ Annotated, not
    # `= Query(None)`: tests call this function directly, and a Query DEFAULT
    # would arrive as a truthy FieldInfo and read as a filter.
    revenue_op: Annotated[Optional[str], Query()] = None,
    revenue_val: Annotated[Optional[float], Query()] = None,
    cost_op: Annotated[Optional[str], Query()] = None,
    cost_val: Annotated[Optional[float], Query()] = None,
    profit_op: Annotated[Optional[str], Query()] = None,
    profit_val: Annotated[Optional[float], Query()] = None,
    _user: dict = Depends(require_report_access(REPORT_KEY)),
):
    """Paginated order rows + a full-universe Totals row.

    The value filters narrow the TABLE only — rows, ``meta.total`` and the
    Totals row all span the filtered set (§96); the KPI cards (/summary) never
    see them. ``meta.unfiltered_total`` carries the pre-filter count.

    ⚠ ``totals`` is a **server-side aggregate over every matching order**, not a
    client-side reduce of the current page (§44) — a Totals row that only sums
    what you can see is a lie the moment the table paginates.

    Since 2026-09-15 this runs ONE scan, not two: the full-universe pass the
    Totals row already required now carries the display columns too, and the
    page is a slice of it. See `_ORDERS_SORT` for why sorting had to leave SQL.
    """
    pool = get_datalake_gold_pool(request)
    s, e = _resolve_range(range, start_date, end_date)
    adj = _resolve_adjustment(adjustment)
    contracts = _parse_multi(contract_type)
    customers = _parse_multi(customer_name)
    posters = _parse_multi(posted_by)
    # ⚠ An unknown key is a 400, NOT a silent fall back to `posted_desc`.
    # The old `.get(sort, default)` meant a sort token that existed on only one
    # side of the wire still rendered a plausible table — the frontend would
    # paint its ▼ arrow on a column the server never sorted by, and nothing
    # anywhere would fail. `test_orders_sort_whitelist_matches_frontend` pins
    # the two lists together; this turns a drift into a visible error.
    if sort not in _ORDERS_SORT:
        raise HTTPException(
            status_code=400,
            detail=f"sort must be one of: {', '.join(sorted(_ORDERS_SORT))}",
        )
    value_filters = _value_filters({
        "revenue": (revenue_op, revenue_val),
        "cost": (cost_op, cost_val),
        "profit": (profit_op, profit_val),
    })

    params: list = []
    cte = _base_sql(
        params,
        start=s,
        end=e,
        contract_types=contracts,
        customers=customers,
        posted_by=posters,
    )

    # ONE scan, carrying every column the table renders. The ORDER BY / LIMIT /
    # OFFSET that used to live here are gone: the sort now spans columns this
    # query cannot see (see `_ORDERS_SORT`), so slicing before the sort would
    # paginate the wrong rows.
    all_rows = await pool.fetch(
        f"""
        WITH {cte}
        SELECT order_id, team, customer, posted_by, posted_date,
               revenue, carrier_cost, profit, otp_on_time, otd_on_time,
               contract_type, rc_count
        FROM base
        """,
        *params,
    )

    # Applied ONCE, to the single row set the page and the Totals row are both
    # derived from — so a totals row contradicting the rows above it is now
    # structurally impossible rather than merely tested for (§16).
    all_rows = _apply_scenario(all_rows, adj)
    unfiltered_total = len(all_rows)
    # After the scenario (filter what is SHOWN), before everything else — so the
    # page, `total` and the Totals row are one filtered population (§96).
    all_rows = _apply_value_filters(all_rows, value_filters)

    total = len(all_rows)
    thresholds = await _thresholds(request, [r["order_id"] for r in all_rows])

    enriched = [
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
        for r in all_rows
    ]
    # Bruno PDF 2026-09-15 R1/R2. Derived from the row's OWN threshold and
    # carrier cost — the same two numbers the Threshold cell already shows —
    # so the three threshold columns on a row cannot tell three stories. Under
    # a scenario `carrier_cost` is the ADJUSTED one, which is the whole reason
    # they are computed here and not in SQL.
    for row in enriched:
        row["cost_saving"] = _row_cost_saving(row["threshold"], row["carrier_cost"])
        row["cost_overrun"] = _row_cost_overrun(row["threshold"], row["carrier_cost"])
        row["threshold_variance_pct"] = _row_threshold_variance(
            row["threshold"], row["carrier_cost"]
        )

    stats = _threshold_stats(enriched, thresholds)

    # ⚠ `max(0, ...)`: FastAPI enforces `ge=1` on the wire, but this endpoint is
    # also called directly (shims, tests), and a NEGATIVE offset does not raise
    # here the way `OFFSET -1` would in Postgres — `rows[-200:0]` is simply
    # EMPTY. That reads as "no orders match", not as a bad page number.
    offset = max(0, (page - 1) * limit)
    out_rows = _sort_orders(enriched, sort)[offset : offset + limit]

    # Folded from `enriched` — the SAME list the page is sliced out of and the
    # same one `_threshold_stats` ran over, so every number in the Totals row
    # spans one population (§96). `or 0.0` keeps a NaN `numeric` (Postgres
    # allows 'NaN', `_fl` maps it to None) from poisoning the sum and turning a
    # division into a TypeError → 500.
    revenue = sum(r["revenue"] or 0.0 for r in enriched)
    profit = sum(r["profit"] or 0.0 for r in enriched)
    carrier_cost = sum(r["carrier_cost"] or 0.0 for r in enriched)
    otp_on_time = sum(1 for r in enriched if r["otp_on_time"])
    otd_on_time = sum(1 for r in enriched if r["otd_on_time"])

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
                "recoveries": _recoveries(enriched),
                # Includes `cost_overrun` — the SAME `_threshold_stats` figure
                # the /summary card shows (Bruno PDF 2026-10-28 R3), and equal
                # to Σ of the per-row column over `enriched` (§16/§69). None
                # when the threshold source is down, so the cell reads "—".
                **stats,
            },
            "adjustment": adj,
            "thresholds_available": thresholds is not None,
            "window": {"start": s.isoformat(), "end": e.isoformat()},
        },
        "meta": {
            "total": total,
            "unfiltered_total": unfiltered_total,
            "filtered": bool(value_filters),
            "page": page,
            "limit": limit,
        },
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


# --------------------------------------------------------------------------
# /rank — the "Rank" tab (Bruno PDF 2026-08-31, page 1)
# --------------------------------------------------------------------------

# Bruno's roster — 15 names on 2026-08-31, 16 since 2026-10-28 (+ Ali Cisneros). It is NOT the same list as podium_top.BOOKER_NAMES
# (they overlap on 10; each carries 4-5 the other does not), so the two stay
# separate — only the normalisation in app/booker_names.py is shared (§69).
#
# ⚠ Spellings reconciled against live `posted_by_name` on 2026-08-31, because
# three of Bruno's entries do not match McLeod byte-for-byte:
#     "Antares Montoya"   → ANTHARES MONTOYA
#     "Jonathan Hernande" → JONATHAN HERNANDEZ   (truncated in the PDF)
#     "Roberto Barcens"   → ROBERTO BARCENAS
# Matching therefore goes through `matches_roster`, never string equality.
#
# ⚠ Three entries have (almost) no bookings in the DFW Rate-Conf universe and
# are recorded here rather than quietly dropped:
#     Ruben Aguilar        — ZERO postings in all of 2026 (only a *Lorenzo*
#                            Aguilar exists in McLeod). Possibly a name error
#                            in the PDF; confirm before "fixing" the roster.
#     Daniel Galindo       — zero postings in 2026.
#     Cindy de los Santos  — exactly one posting, 2026-08-28.
# An absent name still costs nothing — it simply never produces a row.
#
# 🔴 CHANGED 2026-09-03 (Bruno R3, "only display Bookers"). This list used to
# ORDER the picker only, and the table ranked whoever had booked. It is now the
# **POPULATION of the Rank tab**: a name that is not here is not ranked, not
# counted in "of N" and not offered in the picker. Two consequences to hold on
# to before editing it:
#   * Adding a name ADMITS somebody to the league; removing one deletes their
#     history from every week the tab can show. There is no `is_booker` flag
#     anywhere in McLeod or the datalake (`mcleod_dfw_bookers_rank` carries no
#     role column) — this hand-kept list is the only definition that exists.
#   * Measured over the ranked week 22-28 Aug 2026: 26 names posted Rate Confs
#     for TEAM-DFW, 11 of them on this roster. The 15 dropped include ARMANDO
#     CALVILLO (37 loads — the week's #2 by volume, and rank 2 on the tab as it
#     stood), GYNETH DOMINGUEZ (24), KARLA TREVINO (21) and JIMENA VIVANCO (18)
#     — high-volume users who are not bookers. Calvillo is absent from
#     `podium_top.BOOKER_NAMES` too, which is the independent second opinion
#     that made dropping him safe.
# ⚠ Still NOT the podium roster (§99/§69): two different lists of people.
RANK_ROSTER: tuple[str, ...] = (
    "Eugenio Miranda",
    "Anthares Montoya",
    "Andres Sanmiguel",
    "Juan Reyna",
    "Jonathan Hernandez",
    "Jonathan Rodriguez",
    "Daniel Salazar",
    "Ximena Herrera",
    "Antonio Arizpe",
    "Roberto Barcenas",
    "Carlos Padilla",
    "Oscar Macias",
    "Ruben Aguilar",
    "Cindy de los Santos",
    "Daniel Galindo",
    # Bruno PDF 2026-10-28 R1 — posts as `ALI CISNEROS` (user acisneros);
    # normalised key `alicisneros` collides with no other roster entry.
    "Ali Cisneros",
)
_RANK_ROSTER_KEYS = _roster_keys(RANK_ROSTER)


# Bruno (PDF 2026-10-06) R1 — the Rank tab's week is the BOOKING WEEK:
# Friday 17:01 → the next Friday 17:00 (CST), and the tab now FOLLOWS a date
# filter whose default is the booking week that contains "now".
#
# ⚠ This REVERSES two earlier rules, both deliberately:
#   * 2026-09-03 R2 "Sat → Fri, whole days" — superseded by the 17:01 boundary.
#   * 2026-08-31 "never rank the in-progress week" — Bruno's default IS the
#     in-progress week now. The defect that rule prevented (a 1-day-old week
#     ranked against a full one gave +13-position swings) is handled instead by
#     comparing LIKE-FOR-LIKE: while the window is still open, the previous
#     window is clipped to the same elapsed time (Diego, 2026-10-06).
#
# ⚠ This tab ONLY. /summary's `wtd`, the 10-week /weekly trend and the
# Scorecard tab stay Mon-Sun calendar days — they are read beside other portal
# reports that use the ISO week (§95: one label, two metrics).
#
# Every bound here is a NAIVE CST datetime: `mcleod_gld_order_post_hist`
# .posted_date is stored naive in CST at minute precision (verified on live gold
# 2026-10-06 — the first posting after the boundary sits at exactly 17:01). So
# the half-open [Fri 17:01, next Fri 17:01) is precisely Bruno's "5:01 PM
# through 5:00 PM", with no minute lost or double-counted between two weeks.
_BOOKING_WEEK_WEEKDAY = 4  # Friday (Mon=0)
_BOOKING_WEEK_TURNOVER = time(17, 1)
_BOOKING_WEEK = timedelta(days=7)
_ONE_MINUTE = timedelta(minutes=1)

# Bruno 2026-10-06 R2 — "Rank Last Week" shows only bookers with at least this
# many bookings in the week. INCLUSIVE: measured on live gold for 25 Sep - 2 Oct,
# Eugenio Miranda sat at exactly 35.
RANK_LAST_WEEK_MIN_BOOKINGS = 35

# The Rank tab's own date presets. Resolved SERVER-side from the CST clock, so a
# viewer whose browser is in another timezone still gets Friday 17:01 Chicago.
RANK_PERIODS = ("week", "last", "mtd", "custom")

_YEAR_FIRST_INSTANT = datetime.combine(YEAR_START, time.min)
_YEAR_END_EXCLUSIVE = datetime.combine(YEAR_END + timedelta(days=1), time.min)


def _naive_cst(v: datetime) -> datetime:
    """A tz-aware value is converted to Chicago wall time; a naive one is
    already CST (the UI sends `YYYY-MM-DDTHH:MM`). Seconds are dropped — the
    column has minute precision and the bounds are minutes."""
    if v.tzinfo is not None:
        v = v.astimezone(CST).replace(tzinfo=None)
    return v.replace(second=0, microsecond=0)


def _booking_week(now: datetime) -> tuple[datetime, datetime]:
    """The booking week CONTAINING `now`, half-open: [Fri 17:01, Fri 17:01).

    Friday 17:00 still belongs to the week that is closing; 17:01 opens the
    next one. `now` is naive CST.
    """
    friday = now.date() - timedelta(days=(now.weekday() - _BOOKING_WEEK_WEEKDAY) % 7)
    start = datetime.combine(friday, _BOOKING_WEEK_TURNOVER)
    if start > now:
        start -= _BOOKING_WEEK
    return start, start + _BOOKING_WEEK


def _resolve_rank_window(
    period: Optional[str],
    start: Optional[datetime],
    end: Optional[datetime],
    now: datetime,
) -> tuple[datetime, datetime]:
    """The Rank tab's window as a half-open [start, end) of naive CST.

    `end` on the wire is the INCLUSIVE last minute — what a person types
    ("…5:00 PM") — and becomes exclusive here by adding one minute.
    """
    p = period or "week"
    if p not in RANK_PERIODS:
        raise HTTPException(
            status_code=400,
            detail="period must be one of " + ", ".join(RANK_PERIODS),
        )
    if p == "week":
        return _booking_week(now)
    if p == "last":
        cur_start, _ = _booking_week(now)
        return cur_start - _BOOKING_WEEK, cur_start
    if p == "mtd":
        first = datetime.combine(now.date().replace(day=1), time.min)
        return first, datetime.combine(now.date() + timedelta(days=1), time.min)
    # custom
    if start is None or end is None:
        raise HTTPException(
            status_code=400, detail="period=custom needs both start and end"
        )
    s = max(_YEAR_FIRST_INSTANT, _naive_cst(start))
    e = min(_YEAR_END_EXCLUSIVE, _naive_cst(end) + _ONE_MINUTE)
    if e <= s:
        raise HTTPException(status_code=400, detail="end must be after start")
    return s, e


def _comparison_window(
    start: datetime, end: datetime, now: datetime
) -> tuple[datetime, datetime]:
    """The window the movement arrows compare against: the equal-length window
    immediately before, CLIPPED to the same elapsed time while `[start, end)`
    is still open (Diego 2026-10-06, like-for-like).

    Tuesday 09:00 inside Fri 17:01 → Fri 17:01 compares against the previous
    Friday 17:01 → Tuesday 09:00, never the previous WHOLE week — 3½ days of
    bookings against 7 is the +13-position artefact of 2026-08-31.
    """
    length = end - start
    prev_start = start - length
    if start <= now < end:
        return prev_start, prev_start + (now - start)
    return prev_start, start


def _window_label(start: datetime, end: datetime) -> str:
    """"Fri Oct 02, 5:01 PM → Fri Oct 09, 5:00 PM" — the END printed is the last
    INCLUDED minute, the way Bruno writes it, not the exclusive bound."""
    last = end - _ONE_MINUTE

    def fmt(d: datetime) -> str:
        hour = d.hour % 12 or 12
        ampm = "AM" if d.hour < 12 else "PM"
        return f"{d:%a %b %d}, {hour}:{d.minute:02d} {ampm}"

    return f"{fmt(start)} → {fmt(last)}"


def _window_payload(start: datetime, end: datetime) -> dict:
    return {
        "start": start.isoformat(timespec="minutes"),
        # Inclusive last minute — the value the Custom inputs are prefilled with.
        "end": (end - _ONE_MINUTE).isoformat(timespec="minutes"),
        "label": _window_label(start, end),
    }


def _rank_rows(per_booker: dict[str, dict]) -> dict[str, int]:
    """booker -> competition rank (1,2,2,4) by bookings descending.

    Ties share a rank and consume the slots below them, so "rank 4 of 15" keeps
    meaning "three bookers are ahead of you". The name is the tiebreak only so
    the ordering is deterministic between two runs of the same data.
    """
    ordered = sorted(per_booker.items(), key=lambda kv: (-kv[1]["bookings"], kv[0]))
    ranks: dict[str, int] = {}
    last_n: Optional[int] = None
    last_rank = 0
    for i, (name, agg) in enumerate(ordered, start=1):
        if agg["bookings"] != last_n:
            last_rank = i
            last_n = agg["bookings"]
        ranks[name] = last_rank
    return ranks


def _cost_saving_desc_key(r: dict):
    """Cost Saving high → low, nulls LAST (no threshold coverage is not a
    saving of zero, and must not outrank one), then rank, then name."""
    saving = r["cost_saving"]
    return (saving is None, -(saving or 0.0), r["rank"] is None, r["rank"] or 0, r["booker"])


async def _rank_payload(
    request: Request,
    *,
    cur: tuple[datetime, datetime],
    prev: tuple[datetime, datetime],
    contracts: list[str],
    customers: list[str],
    posters: list[str],
    min_bookings: int = 0,
    sort_by_cost_saving: bool = False,
) -> dict:
    """The ranking shared by /rank and /rank/last-week.

    `cur` and `prev` are half-open naive-CST windows; `prev` ends at or before
    `cur` starts (it is clipped while `cur` is open, so there may be a gap).

    ⚠ ONE scan over [prev.start, cur.end), bucketed in Python. `_base_sql` is a
    full sequential scan of `mcleod_gld_order_post_hist` (1.9M rows, no usable
    index — §73), and over one window each order has exactly ONE winning
    posting (its latest), so it is credited to at most one bucket. Two separate
    scans would credit an order re-confirmed in both windows twice. A winning
    posting that falls in the clipping GAP belongs to neither bucket — the same
    "latest posting wins" rule the rest of the report applies.

    ⚠ The roster restriction runs on the row set of BOTH windows BEFORE ranking
    (Bruno 2026-09-03 R3, §104) — ranking first and hiding afterwards leaves
    gaps (1, 3, 4, 6 …) and an "of N" counting people the table refuses to
    show; restricting one window only compares two different leagues.

    ⚠ `posters` and `min_bookings` filter the DISPLAYED rows, never the
    ranking (§75): rank is a rule over the whole booker population, so a
    single-name selection must not read "rank 1 of 1", and the ≥35 cut must not
    renumber the bookers it keeps. `contracts` / `customers` DO narrow the
    population — they change which bookings exist at all.
    """
    pool = get_datalake_gold_pool(request)
    (cur_start, cur_end), (prev_start, prev_end) = cur, prev

    params: list = []
    cte = _base_sql(
        params,
        start=max(_YEAR_FIRST_INSTANT, prev_start),
        # `_base_sql` bounds are inclusive; the posted_date column has minute
        # precision, so "one microsecond before the exclusive end" is exact.
        end=min(_YEAR_END_EXCLUSIVE, cur_end) - timedelta(microseconds=1),
        contract_types=contracts,
        customers=customers,
        # NOT `posters` — see the docstring.
        posted_by=[],
    )
    rows = await pool.fetch(
        f"""
        WITH {cte}
        SELECT order_id, posted_by, posted_date, carrier_cost
        FROM base
        """,
        *params,
    )

    thresholds = await _thresholds(request, [r["order_id"] for r in rows])

    cur_rows: dict[str, list] = {}
    prev_rows: dict[str, list] = {}
    # Bruno 2026-09-03 R3 — bookers only. Matched through the shared normaliser
    # (§69), never string equality: three of the 15 roster spellings differ from
    # McLeod's byte-for-byte, and a strict compare would silently drop them.
    # The verdict is memoised per distinct spelling.
    is_booker: dict[str, bool] = {}
    for r in rows:
        name = (r["posted_by"] or "").strip()
        if not name:
            continue
        keep = is_booker.get(name)
        if keep is None:
            keep = _matches_roster(name, _RANK_ROSTER_KEYS)
            is_booker[name] = keep
        if not keep:
            continue
        pd = r["posted_date"]
        if pd is None:
            continue
        # A bare date (stub rows) counts as its first instant.
        when = _lower_bound(pd)
        if cur_start <= when < cur_end:
            bucket = cur_rows
        elif prev_start <= when < prev_end:
            bucket = prev_rows
        else:
            continue
        bucket.setdefault(name, []).append(r)

    cur_agg = {n: {"bookings": len(rs)} for n, rs in cur_rows.items()}
    prev_agg = {n: {"bookings": len(rs)} for n, rs in prev_rows.items()}
    cur_ranks = _rank_rows(cur_agg)
    prev_ranks = _rank_rows(prev_agg)

    # Every booker seen in EITHER window gets a row: someone who booked last
    # time and nothing now has fallen to the bottom, which is information. An
    # inner join would render that as a missing row instead of a red one (§91).
    all_names = sorted(set(cur_agg) | set(prev_agg))
    out = []
    for name in all_names:
        stats = _threshold_stats(cur_rows.get(name, []), thresholds)
        cur_rank = cur_ranks.get(name)
        prev_rank = prev_ranks.get(name)
        out.append({
            "booker": name,
            "rank": cur_rank,
            "prev_rank": prev_rank,
            # Positive = moved UP. None when the booker did not appear in the
            # comparison window — "new" is not "unchanged".
            "rank_delta": (prev_rank - cur_rank)
            if (cur_rank is not None and prev_rank is not None) else None,
            "bookings": cur_agg.get(name, {}).get("bookings", 0),
            "prev_bookings": prev_agg.get(name, {}).get("bookings", 0),
            # FORWARDED from `_threshold_stats`, never recomputed here: the
            # Scorecard tab's KPI card folds the very same helper (§69).
            "broken_threshold": stats["broken_threshold"],
            "threshold_orders": stats["threshold_orders"],
            "broken_threshold_pct": stats["broken_threshold_pct"],
            "compliance_threshold_pct": stats["compliance_threshold_pct"],
            "compliant_threshold": stats["compliant_threshold"],
            "cost_saving": stats["cost_saving"],
            "under_threshold": stats["under_threshold"],
        })
    if sort_by_cost_saving:
        out.sort(key=_cost_saving_desc_key)
    else:
        # Unranked bookers (none in the window) sort last, not first.
        out.sort(key=lambda r: (r["rank"] is None, r["rank"] or 0, r["booker"]))

    if min_bookings:
        out = [r for r in out if r["bookings"] >= min_bookings]
    if posters:
        wanted = {p.strip() for p in posters}
        out = [r for r in out if r["booker"] in wanted]

    # Picker options: the roster members who booked in either window. Not
    # narrowed by `min_bookings` — that is a display cut on one table.
    in_roster = list(all_names)

    return {
        "rows": out,
        "bookers": in_roster,
        "roster": in_roster,
        # The ranked population — the "of N" in "3 of N". Counted BEFORE the
        # display filters, so neither the picker nor the ≥35 cut renumbers the
        # league (§75).
        "total_bookers": len(cur_agg),
        "min_bookings": min_bookings,
        "week": _window_payload(cur_start, cur_end),
        "prev_week": _window_payload(prev_start, prev_end),
        # True while the window is still open and the comparison is clipped —
        # the UI says "vs the same point last week" instead of "vs last week".
        "like_for_like": prev_end < cur_start,
    }


@router.get("/rank")
async def rank(
    request: Request,
    period: Optional[str] = Query(None),
    start: Optional[datetime] = Query(None),
    end: Optional[datetime] = Query(None),
    contract_type: Optional[list[str]] = Query(None),
    customer_name: Optional[list[str]] = Query(None),
    posted_by: Optional[list[str]] = Query(None),
    _user: dict = Depends(require_report_access(REPORT_KEY)),
):
    """The Rank tab — Bruno PDF 2026-08-31, revised 2026-09-03 and 2026-10-06.

    Bookers (RANK_ROSTER only) ranked by # of Bookings inside the selected
    window, with the positions each moved against the comparison window, plus
    Compliance Threshold and Cost Saving over the same window.

    Bruno 2026-10-06 R1 — the tab now FOLLOWS a date filter:
      * `period=week` (default) — the booking week containing now,
        Fri 17:01 → Fri 17:00 CST.
      * `period=last` — the booking week before it.
      * `period=mtd` — the 1st of the month 00:00 → now.
      * `period=custom` — `start` / `end` as `YYYY-MM-DDTHH:MM`, naive = CST,
        `end` INCLUSIVE to the minute. Clamped to 2026.
    `start` / `end` are read for `custom` only; the presets are resolved here
    from the CST clock so a browser in another timezone cannot shift Friday.
    """
    now = _naive_cst(cst_now())
    cur = _resolve_rank_window(period, start, end, now)
    prev = _comparison_window(*cur, now)
    data = await _rank_payload(
        request,
        cur=cur,
        prev=prev,
        contracts=_parse_multi(contract_type),
        customers=_parse_multi(customer_name),
        posters=_parse_multi(posted_by),
    )
    return {"success": True, "data": data}


@router.get("/rank/last-week")
async def rank_last_week(
    request: Request,
    contract_type: Optional[list[str]] = Query(None),
    customer_name: Optional[list[str]] = Query(None),
    posted_by: Optional[list[str]] = Query(None),
    _user: dict = Depends(require_report_access(REPORT_KEY)),
):
    """"Rank Last Week" — Bruno PDF 2026-10-06 R2.

    A copy of the Rank table pinned to the PREVIOUS booking week (on Tue 6 Oct:
    Fri 25 Sep 17:01 → Fri 2 Oct 17:00), showing only bookers with
    ≥ RANK_LAST_WEEK_MIN_BOOKINGS bookings, sorted by Cost Saving high → low.

    ⚠ Declares NO date parameters at all, like /weekly: "not affected by the
    date filter" is enforced by the signature, so no hand-crafted URL can move
    it. The scope filters (customer, contract, booker) still apply, exactly as
    they always did on the Rank tab.

    Movement compares against the week before it — two COMPLETE weeks, so no
    clipping. `rank` is still the position by # of Bookings among every roster
    booker that week; the ≥35 cut and the Cost Saving order are display only.
    """
    now = _naive_cst(cst_now())
    cur_start, _ = _booking_week(now)
    cur = (cur_start - _BOOKING_WEEK, cur_start)
    prev = (cur[0] - _BOOKING_WEEK, cur[0])
    data = await _rank_payload(
        request,
        cur=cur,
        prev=prev,
        contracts=_parse_multi(contract_type),
        customers=_parse_multi(customer_name),
        posters=_parse_multi(posted_by),
        min_bookings=RANK_LAST_WEEK_MIN_BOOKINGS,
        sort_by_cost_saving=True,
    )
    return {"success": True, "data": data}
