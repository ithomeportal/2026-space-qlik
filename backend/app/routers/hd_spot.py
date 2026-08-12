"""HD Spot — Home Depot spot performance (Bruno PDF 2026-08-12).

Portal version of the daily ``HD PERFORMANCE - SPOT`` email (n8n workflow
``P36cH2hbx71viRBW``, rev 9.1). That email is the numeric authority: it carries
71 regression assertions and three independent SQL reconciliations, so every
formula here is copied from it rather than re-derived. Where this file departs
from it, the departure is deliberate and documented below.

Two databases, no SQL join
--------------------------
* **Funnel** (Offered / Quoted / Awarded) — ``spot_report_condensed`` in
  ``modern_pricing_portal`` (pool: ``get_pricing_pool``).
* **Money** (Revenue / Carrier Cost / Profit + order status) —
  ``mcleod_gld_customer_view`` JOIN ``mcleod_gld_budget_report_v4`` in
  ``aivn_datalake_gold`` (pool: ``get_datalake_gold_pool``).

They are separate databases on one Aiven instance with no ``dblink``/``fdw``,
so the join happens **in Python** on ``spot.order_number = customer_view.blnum``
(§56). The money side fails **soft**: if the gold pool is down the funnel still
renders and the money columns come back ``None``, never ``{}`` and never a 503.

Scope decisions (verified against live data 2026-08-12)
-------------------------------------------------------
1. **The two frozen legacy imports are excluded.** The n8n spec claims
   ``legacy_hd`` "does NOT carry the customer name and so is still excluded".
   That is **false** — 36,134 ``legacy_hd`` rows do carry ``HOME DEPOT``. The
   email never noticed because its 45–61-day window stops well after
   ``legacy_hd`` ends (2026-04-09). This report has Last Month and Custom, so it
   *will* reach that data, and reaching it is actively harmful:
     * ``legacy_hd.volume`` is NULL on **all** 36,134 rows, so Offered/Quoted/
       Awarded (all ``SUM(volume)``) collapse to 0 — while its WON rows still
       join to McLeod and produce Revenue. A March range would render large
       Revenue against ~zero Offered.
     * ``legacy_hd.buy_rate`` is populated on only 1,237 of 36,134 rows, so
       "Quoted" is meaningless there.
     * ``legacy_hd`` and ``homedepot`` share **3,319 duplicate offer ids** in
       2026-02-10 → 2026-04-09, with different prices and statuses.
   The exclusion is written as a NOT-IN on the two frozen imports rather than an
   IN-list of live feeds, so a *new* live feed is included automatically instead
   of being silently dropped.
2. **The report floors at 2026-03-01** (``DATA_FLOOR``) — the first full month of
   the live ``homedepot`` feed. Earlier ranges would be truthfully but
   confusingly empty.
3. **Awarded is ``award_status = 'WON'`` only.** ``ACCEPT`` appeared in Aug 2026
   and now outnumbers WON 1,238 to 93, which looks alarming. It is not an award:
   the quoting portal defines it as "price submitted to THD, outcome pending",
   and empirically those orders do not become shipments — of 1,238 August ACCEPT
   orders only 2 (0.2%) match a McLeod ``blnum``, the same rate as LOST (0.3%),
   against 91.4% for WON. Always compare with ``UPPER()``: mixed-case
   ``award_status`` once turned $3.34M into $546K in the quoting portal.
4. **Quoted = ``buy_rate IS NOT NULL``**, per the email. The quoting portal's own
   ``/api/spots/report`` uses ``price > 0`` instead; the two differ ~3%. Both
   cannot be matched and the PDF names the email as its reference. Switching is
   a one-line change to ``_QUOTED_COND``.
5. **Equipment groups use ``ILIKE``, never ``IN``.** HD rows are ``DRY_VAN`` /
   ``FLATBED``; the ``lane_analysis`` feed carries a bare ``VAN``. An exact
   ``IN ('DRY_VAN','FLATBED')`` would silently drop the latter.
6. **The Status filter scopes only the money side.** Order status (V/A/D/P) lives
   on the matched McLeod row, which exists only for WON-and-booked orders — a
   lost quote has no status at all. So Status cannot scope Offered/Quoted/
   Awarded/Conversion or the chart, and deliberately does not.

Faithful reproductions of email quirks (do NOT "fix" — the two artifacts must
agree; both are footnoted in the UI)
-------------------------------------------------------------------------------
* ``Loads`` counts **all** matched budget rows while the three splits count
  ``contract_type_descr = 'SPOT'`` only, so ``Loads != Cancelled + Covered +
  Pending``. The CONTRACT-typed rows live in ``Loads`` alone.
* ``Loads*`` carry a ``total_charge <> 0`` guard; ``Revenue*``/``Profit*`` do
  not. The asymmetry is in the request verbatim.
* ``Profit Cancelled`` can equal ``Revenue Cancelled`` to the dollar — voided
  loads keep revenue but shed carrier pay, so cancelled margin is ~100%.

Other rules this file obeys
---------------------------
* Date bounds are bound as ``price_date >= ($n::date AT TIME ZONE 'America/
  Chicago')``, i.e. the conversion is applied to the **parameter**, never the
  column. ``(price_date AT TIME ZONE ...)::date >= x`` — what the email does —
  is a function on the indexed column and forces a seq scan: measured
  36.7 ms vs **2.5 ms** on the same window (§43/§49). It is also DST-correct,
  unlike a fixed -6h offset.
* Every rate is recomputed from its components, never averaged, and guarded
  ``den > 0`` rather than ``not den`` — a negative denominator is the real
  hazard here, since 29 of 286 budget rows carry a negative ``margin_amt`` and a
  single credit can push one bucket below zero (§8 of the email spec).
"""

from __future__ import annotations

import asyncio
import logging
from calendar import monthrange
from datetime import date, timedelta
from typing import Any, Optional

from fastapi import APIRouter, Depends, Query, Request

from app.clock import cst_today
from app.routers.deps import (
    get_datalake_gold_pool,
    get_pricing_pool,
    require_report_access,
)

logger = logging.getLogger(__name__)

router = APIRouter(tags=["hd-spot"], prefix="/custom/hd-spot")

REPORT_KEY = "hd-spot"

CUSTOMER = "HOME DEPOT"

# First full month of the live `homedepot` feed. Earlier data is the frozen
# `legacy_hd` import — see the module docstring.
DATA_FLOOR = date(2026, 3, 1)
YEAR_END = date(2026, 12, 31)

# Frozen one-time imports from express_module_prod. Excluded as a NOT-IN so a
# new *live* feed is picked up automatically rather than silently dropped.
FROZEN_SOURCES = ("legacy_hd", "legacy")

# "Quoted" per the email spec. The quoting portal uses `price > 0` (~3% apart).
_QUOTED_COND = "buy_rate IS NOT NULL"

EQUIP_GROUPS = ("VAN", "FLATBED")

# McLeod order status -> the three buckets the request names.
STATUS_LABELS = {
    "V": "cancelled",
    "A": "pending",
    "D": "covered",
    "P": "covered",
}
STATUS_OPTIONS = [
    {"value": "cancelled", "label": "Cancelled", "codes": ["V"]},
    {"value": "covered", "label": "Covered", "codes": ["D", "P"]},
    {"value": "pending", "label": "Pending to Cover", "codes": ["A"]},
]

MAX_ROWS = 2000


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------


def _clamp(d: Optional[date], default: date) -> date:
    if d is None:
        return default
    if d < DATA_FLOOR:
        return DATA_FLOOR
    if d > YEAR_END:
        return YEAR_END
    return d


def _month_bounds(d: date) -> tuple[date, date]:
    return d.replace(day=1), d.replace(day=monthrange(d.year, d.month)[1])


def _resolve_range(
    rng: Optional[str],
    start_date: Optional[date],
    end_date: Optional[date],
) -> tuple[date, date]:
    """Today / Yesterday / MTD / Last Month / Custom (Bruno Request 2).

    ``cst_today()`` — never ``date.today()``: Render and Aiven run UTC, so
    between 18:00 and 23:59 CST a naive clock labels today as yesterday (§2).
    MTD is the default, per the request.
    """
    today = cst_today()
    t = max(DATA_FLOOR, min(YEAR_END, today))
    if rng == "today":
        return t, t
    if rng == "yesterday":
        y = _clamp(t - timedelta(days=1), DATA_FLOOR)
        return y, y
    if rng == "last_month":
        first_this = t.replace(day=1)
        prev_start, prev_end = _month_bounds(first_this - timedelta(days=1))
        return _clamp(prev_start, DATA_FLOOR), _clamp(prev_end, YEAR_END)
    if rng == "custom":
        s = _clamp(start_date, DATA_FLOOR)
        e = _clamp(end_date, YEAR_END)
        if e < s:
            s, e = e, s
        return s, e
    # default: MTD (the request's default selection)
    return _clamp(t.replace(day=1), DATA_FLOOR), t


def _parse_multi(raw: Optional[list[str]]) -> list[str]:
    """Repeated query params -> clean list.

    NEVER ``.split(",")`` — repeated keys travel as repeated params and the
    proxy preserves them with ``.append()`` (§45).
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


def _equip_filter(params: list, groups: list[str]) -> str:
    """VAN / FLATBED group filter as ILIKE, never IN — see docstring note 5."""
    valid = [g for g in groups if g in EQUIP_GROUPS]
    if not valid or len(valid) == len(EQUIP_GROUPS):
        return ""
    ors = []
    for g in valid:
        params.append("%FLAT%" if g == "FLATBED" else "%VAN%")
        ors.append(f"equipment ILIKE ${len(params)}")
    return " AND (" + " OR ".join(ors) + ")"


def _spot_where(params: list, start: date, end: date, groups: list[str]) -> str:
    """Shared WHERE for every spot query — one helper so a drill can never
    apply a different scope than the KPI it was clicked from (§16)."""
    params.append(start)
    lo = f"${len(params)}"
    params.append(end)
    hi = f"${len(params)}"
    params.append(CUSTOMER)
    cust = f"${len(params)}"
    params.append(list(FROZEN_SOURCES))
    frozen = f"${len(params)}"
    return (
        f"WHERE express_module_customer_name = {cust} "
        # parameter-side AT TIME ZONE keeps idx_..._price_date usable AND is
        # DST-correct; end bound is exclusive-next-day so the last day is whole.
        f"AND price_date >= ({lo}::date AT TIME ZONE 'America/Chicago') "
        f"AND price_date <  (({hi}::date + INTERVAL '1 day') AT TIME ZONE 'America/Chicago') "
        f"AND (source IS NULL OR source <> ALL({frozen}::text[])) "
        f"AND (equipment ILIKE '%VAN%' OR equipment ILIKE '%FLAT%')"
        + _equip_filter(params, groups)
    )


_EQUIP_GROUP_SQL = (
    "CASE WHEN equipment ILIKE '%FLAT%' THEN 'FLATBED' ELSE 'VAN' END"
)
_CST_DATE_SQL = "(price_date AT TIME ZONE 'America/Chicago')::date"


def _rate(num: Optional[float], den: Optional[float]) -> Optional[float]:
    """Recompute a rate from components. ``den > 0``, never ``not den`` — a
    negative denominator would otherwise render a percentage in the millions."""
    if den is None or num is None or den <= 0:
        return None
    return float(num) / float(den)


def _f(v: Any) -> float:
    return float(v or 0)


# --------------------------------------------------------------------------
# data access
# --------------------------------------------------------------------------


async def _fetch_funnel(pool, start: date, end: date, groups: list[str]):
    """Per (equipment group, CST date) funnel aggregate, straight from SQL."""
    params: list = []
    where = _spot_where(params, start, end, groups)
    sql = f"""
        SELECT {_EQUIP_GROUP_SQL} AS equip_group,
               {_CST_DATE_SQL}    AS cst_date,
               SUM(COALESCE(volume, 0))                                    AS offered,
               SUM(COALESCE(volume, 0)) FILTER (WHERE {_QUOTED_COND})      AS quoted,
               SUM(COALESCE(volume, 0)) FILTER (WHERE UPPER(award_status) = 'WON') AS awarded
        FROM spot_report_condensed
        {where}
        GROUP BY 1, 2
        ORDER BY 2, 1
    """
    async with pool.acquire() as conn:
        return await conn.fetch(sql, *params)


async def _fetch_won_keys(pool, start: date, end: date, groups: list[str]):
    """WON rows only — the join keys for the money half.

    ``order_number ~ '^[0-9]+$'`` drops the space-separated multi-order strings
    the Lane Analysis feed can carry (up to 27 orders in one field). Those are
    McLeod order ids anyway, not the customer BOL reference that ``blnum``
    holds, so they would not join correctly even if split.
    """
    params: list = []
    where = _spot_where(params, start, end, groups)
    sql = f"""
        SELECT DISTINCT
               order_number,
               {_EQUIP_GROUP_SQL} AS equip_group,
               {_CST_DATE_SQL}    AS cst_date
        FROM spot_report_condensed
        {where}
          AND UPPER(award_status) = 'WON'
          AND order_number IS NOT NULL
          AND order_number ~ '^[0-9]+$'
        -- Deterministic: one order number can appear on two rows (re-posted on a
        -- later day, or quoted for both equipment groups). Without an explicit
        -- ORDER BY the "first mapping wins" tie-break below would depend on scan
        -- order, so the same window could report different Revenue run to run.
        ORDER BY 3, 2, 1
    """
    async with pool.acquire() as conn:
        return await conn.fetch(sql, *params)


async def _fetch_budget(pool, blnums: list[str]):
    """Deduped McLeod money rows for the given BOL numbers.

    ``budget.id`` is NOT unique (max 2 rows/id) and ``customer_view.id`` fans
    out too; a naive SUM inflates ~2.5%. Rank by ``total_charge DESC NULLS
    LAST`` and keep rn = 1, exactly as the email does.
    """
    if not blnums:
        return []
    sql = """
        WITH ranked AS (
          SELECT TRIM(cv.blnum) AS blnum,
                 b.total_charge, b.total_carrier_pay, b.margin_amt,
                 b.status, b.contract_type_descr,
                 row_number() OVER (
                   PARTITION BY TRIM(cv.blnum)
                   ORDER BY b.total_charge DESC NULLS LAST
                 ) AS rn
          FROM mcleod_gld_customer_view cv
          JOIN mcleod_gld_budget_report_v4 b ON b.id = cv.id
          WHERE cv.blnum IS NOT NULL
            AND TRIM(cv.blnum) <> ''
            AND TRIM(cv.blnum) = ANY($1::text[])
        )
        SELECT blnum, total_charge, total_carrier_pay, margin_amt,
               status, contract_type_descr
        FROM ranked WHERE rn = 1
    """
    async with pool.acquire() as conn:
        return await conn.fetch(sql, blnums)


def _blank_money() -> dict:
    return {
        "loads": 0,
        "loads_cancelled": 0,
        "loads_covered": 0,
        "loads_pending": 0,
        "revenue": 0.0,
        "revenue_cancelled": 0.0,
        "revenue_covered": 0.0,
        "revenue_pending": 0.0,
        "carrier_cost": 0.0,
        "carrier_cost_cancelled": 0.0,
        "carrier_cost_covered": 0.0,
        "carrier_cost_pending": 0.0,
        "profit": 0.0,
        "profit_cancelled": 0.0,
        "profit_covered": 0.0,
        "profit_pending": 0.0,
    }


def _accumulate_money(bucket: dict, row, status_filter: set[str]) -> None:
    """Fold one deduped budget row into a bucket.

    Carrier cost splits are accumulated as ``charge - margin`` per row rather
    than subtracted at render time: money is rounded to whole dollars for
    display, and subtracting two already-rounded figures can be a dollar off.
    Verified on live data that ``total_carrier_pay == total_charge -
    margin_amt`` to the cent on every row, so the two readings agree.
    """
    charge = _f(row["total_charge"])
    margin = _f(row["margin_amt"])
    carrier = charge - margin
    status = (row["status"] or "").strip().upper()[:1]
    label = STATUS_LABELS.get(status)
    is_spot = (row["contract_type_descr"] or "").strip().upper() == "SPOT"

    # The Status filter scopes only the money side (docstring note 6). It gates
    # the *base* figures; the per-status split columns always show every split,
    # otherwise a filtered view would render its own splits as zero.
    if status_filter and label not in status_filter:
        return

    # `Loads` has no contract-type filter; the splits are SPOT-only. That is why
    # Loads != Cancelled + Covered + Pending. Faithful to the email.
    if charge != 0:
        bucket["loads"] += 1
    bucket["revenue"] += charge
    bucket["profit"] += margin
    bucket["carrier_cost"] += carrier

    if is_spot and label:
        # Loads* carry the `total_charge <> 0` guard; Revenue*/Profit* do not.
        if charge != 0:
            bucket[f"loads_{label}"] += 1
        bucket[f"revenue_{label}"] += charge
        bucket[f"profit_{label}"] += margin
        bucket[f"carrier_cost_{label}"] += carrier


def _derive(b: dict) -> dict:
    """Attach the recomputed rates to a bucket."""
    out = dict(b)
    out["participation"] = _rate(b.get("quoted"), b.get("offered"))
    out["conversion"] = _rate(b.get("awarded"), b.get("quoted"))
    out["margin"] = _rate(b.get("profit"), b.get("revenue"))
    out["margin_covered"] = _rate(b.get("profit_covered"), b.get("revenue_covered"))
    out["margin_pending"] = _rate(b.get("profit_pending"), b.get("revenue_pending"))
    return out


async def _build(
    request: Request,
    start: date,
    end: date,
    groups: list[str],
    statuses: list[str],
) -> tuple[dict, list[dict], bool]:
    """Assemble the whole report. Returns (totals, rows, money_ok).

    ``money_ok`` is False when the gold side could not be reached — the funnel
    still renders and the money columns come back None. Failing soft matters
    here: a hard 503 would blank a report whose funnel half is perfectly fine.
    """
    pricing = get_pricing_pool(request)
    status_filter = {s for s in statuses if s in {"cancelled", "covered", "pending"}}

    funnel_rows, won_rows = await asyncio.gather(
        _fetch_funnel(pricing, start, end, groups),
        _fetch_won_keys(pricing, start, end, groups),
    )

    buckets: dict[tuple[str, date], dict] = {}

    def _bucket(key) -> dict:
        if key not in buckets:
            b = _blank_money()
            b.update({"offered": 0.0, "quoted": 0.0, "awarded": 0.0})
            buckets[key] = b
        return buckets[key]

    for r in funnel_rows:
        b = _bucket((r["equip_group"], r["cst_date"]))
        b["offered"] += _f(r["offered"])
        b["quoted"] += _f(r["quoted"])
        b["awarded"] += _f(r["awarded"])

    # --- money half (cross-DB merge in Python) -----------------------------
    money_ok = True
    # One order number can only belong to one bucket; verified duplicate-free
    # before trusting the join (a silent 2x on a load count is worse than a
    # redundant check).
    key_of: dict[str, tuple[str, date]] = {}
    dupes = 0
    for r in won_rows:
        on = (r["order_number"] or "").strip()
        if not on:
            continue
        k = (r["equip_group"], r["cst_date"])
        if on in key_of and key_of[on] != k:
            dupes += 1
            continue
        key_of[on] = k
    if dupes:
        logger.warning(
            "HD Spot: %d WON order numbers mapped to more than one bucket; "
            "first mapping kept",
            dupes,
        )

    matched = 0
    if key_of:
        try:
            gold = get_datalake_gold_pool(request)
            budget_rows = await _fetch_budget(gold, list(key_of.keys()))
            for br in budget_rows:
                k = key_of.get((br["blnum"] or "").strip())
                if k is None:
                    continue
                matched += 1
                _accumulate_money(_bucket(k), br, status_filter)
        except Exception as e:  # fail soft — never {} , never a 503
            logger.warning("HD Spot: money half unavailable (%s)", e)
            money_ok = False

    rows = [
        _derive({"equipment": k[0], "date": k[1].isoformat(), **v})
        for k, v in sorted(buckets.items(), key=lambda kv: (kv[0][1], kv[0][0]))
    ][:MAX_ROWS]

    # Totals are a server-side aggregate over the FULL universe, never a client
    # reduce of the visible page (§44).
    tot = _blank_money()
    tot.update({"offered": 0.0, "quoted": 0.0, "awarded": 0.0})
    for v in buckets.values():
        for k2, val in v.items():
            tot[k2] += val
    totals = _derive(tot)
    totals["won_orders"] = len(key_of)
    totals["won_orders_matched"] = matched
    # Ship the partial-join denominator on screen, not just in a log (§56).
    totals["match_rate"] = _rate(matched, len(key_of)) if key_of else None
    totals["money_ok"] = money_ok

    return totals, rows, money_ok


# --------------------------------------------------------------------------
# endpoints
# --------------------------------------------------------------------------
#
# Sibling endpoints on one screen MUST declare the same params — FastAPI
# silently DROPS an undeclared query param, so a card would scope while the
# chart beside it did not (§55).


def _common(
    range: Optional[str] = Query("mtd"),
    start_date: Optional[date] = Query(None),
    end_date: Optional[date] = Query(None),
    equipment: Optional[list[str]] = Query(None),
    status: Optional[list[str]] = Query(None),
):
    s, e = _resolve_range(range, start_date, end_date)
    return {
        "start": s,
        "end": e,
        "groups": _parse_multi(equipment),
        "statuses": _parse_multi(status),
    }


@router.get("/filters")
async def filters(
    _user: dict = Depends(require_report_access(REPORT_KEY)),
):
    return {
        "success": True,
        "data": {
            "equipment": list(EQUIP_GROUPS),
            "status": STATUS_OPTIONS,
            "data_floor": DATA_FLOOR.isoformat(),
            "year_end": YEAR_END.isoformat(),
        },
    }


@router.get("/summary")
async def summary(
    request: Request,
    f: dict = Depends(_common),
    _user: dict = Depends(require_report_access(REPORT_KEY)),
):
    """The eight KPI cards.

    Revenue/Profit/Margin are the **Covered** figures, per Request 3 — matching
    the email's rev-9 decision. The blended trio is a mirage: cancelled loads
    shed carrier pay so they book ~100% margin, and Pending-to-Cover has not
    been paid yet, so a blended margin is arithmetic over two buckets that
    structurally cannot carry carrier cost (57.9% blended vs 4.3% covered on the
    day the email switched).
    """
    totals, _rows, money_ok = await _build(
        request, f["start"], f["end"], f["groups"], f["statuses"]
    )
    return {
        "success": True,
        "data": {
            "offered": totals["offered"],
            "quoted": totals["quoted"],
            "participation": totals["participation"],
            "awarded": totals["awarded"],
            "conversion": totals["conversion"],
            "revenue_covered": totals["revenue_covered"] if money_ok else None,
            "profit_covered": totals["profit_covered"] if money_ok else None,
            "margin_covered": totals["margin_covered"] if money_ok else None,
            "money_ok": money_ok,
            "match_rate": totals["match_rate"],
            "won_orders": totals["won_orders"],
            "won_orders_matched": totals["won_orders_matched"],
            "start_date": f["start"].isoformat(),
            "end_date": f["end"].isoformat(),
        },
    }


@router.get("/chart")
async def chart(
    request: Request,
    f: dict = Depends(_common),
    _user: dict = Depends(require_report_access(REPORT_KEY)),
):
    """Awarded (bars) + Conversion Ratio (line) by day.

    Follows the date filter, per Request 4. Both equipment groups are summed
    per day; Conversion is recomputed from the day's own components, never
    averaged from the two groups' percentages.
    """
    _totals, rows, _ok = await _build(
        request, f["start"], f["end"], f["groups"], f["statuses"]
    )
    by_day: dict[str, dict] = {}
    for r in rows:
        d = by_day.setdefault(r["date"], {"awarded": 0.0, "quoted": 0.0})
        d["awarded"] += _f(r["awarded"])
        d["quoted"] += _f(r["quoted"])
    series = [
        {
            "date": d,
            "awarded": v["awarded"],
            "conversion": _rate(v["awarded"], v["quoted"]),
        }
        for d, v in sorted(by_day.items())
    ]
    return {"success": True, "data": series, "meta": {"total": len(series)}}


@router.get("/table")
async def table(
    request: Request,
    f: dict = Depends(_common),
    _user: dict = Depends(require_report_access(REPORT_KEY)),
):
    """One row per (Equipment, Date), plus a full-universe Totals row."""
    totals, rows, money_ok = await _build(
        request, f["start"], f["end"], f["groups"], f["statuses"]
    )
    return {
        "success": True,
        "data": {"rows": rows, "totals": totals, "money_ok": money_ok},
        "meta": {"total": len(rows)},
    }


@router.get("/freshness")
async def freshness(
    request: Request,
    _user: dict = Depends(require_report_access(REPORT_KEY)),
):
    """"Data as of" = the STALEST of the two feeds (§54).

    A feed with no timestamp is DEAD, not skippable. The spot cron runs every
    30 min, so >90 min without an update means two missed runs — that threshold
    is the only reason a 3-day outage of this pipeline became visible last time.
    """
    out: dict[str, Any] = {"spot": None, "gold": None, "spot_stale_minutes": None}
    try:
        pricing = get_pricing_pool(request)
        async with pricing.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT MAX(updated_at) AS ts,
                       EXTRACT(EPOCH FROM (now() - MAX(updated_at)))/60 AS mins
                FROM spot_report_condensed
                WHERE express_module_customer_name = $1
                  AND (source IS NULL OR source <> ALL($2::text[]))
                """,
                CUSTOMER,
                list(FROZEN_SOURCES),
            )
        out["spot"] = row["ts"].isoformat() if row and row["ts"] else None
        out["spot_stale_minutes"] = float(row["mins"]) if row and row["mins"] else None
    except Exception as e:
        logger.warning("HD Spot freshness (spot) failed: %s", e)
    try:
        gold = get_datalake_gold_pool(request)
        async with gold.acquire() as conn:
            ts = await conn.fetchval(
                "SELECT MAX(ordered_date) FROM mcleod_gld_budget_report_v4"
            )
        out["gold"] = ts.isoformat() if ts else None
    except Exception as e:
        logger.warning("HD Spot freshness (gold) failed: %s", e)

    mins = out.get("spot_stale_minutes")
    out["is_stale"] = bool(mins is not None and mins > 90)
    return {"success": True, "data": out}
