"""Code-made report: Division Payment Calculator (Bruno PDF 2026-08-13).

Computes the monthly payment owed to the A&O division:

    Net Payment = Profit − GL Deductions − Corporate Gain
    Corporate Gain = 25 % of Profit + Tariff
    Tariff = 25 %·(10 % of Revenue) − 25 %·Profit,  charged ONLY when margin < 10 %

⚠ THE TARIFF IS SUBTRACTED EXACTLY ONCE — it lives *inside* Corporate Gain.
The vendor's ``DEVELOPER_README.md`` documents ``profit − glDeductions −
penaltyFee − corporateGain``, which subtracts it twice. The prototype's own code
(``calculateMonthSummary``) subtracts it once; that is what the PDF's figures
reconcile to ($732,000 − $166,390 − $183,000 = $382,610 for July 2026), so the
code — not the README — is authoritative.

⚠ ONE COMPUTATION, TWO TABS. Every money figure on both the Dashboard and the
Calculator tab comes from :func:`compute_summary` here. The prototype computed
them separately and the two tabs disagreed by $1,575 on May 2026 ($290,030 vs
$291,605) — precisely the KPI-≠-detail failure §16 exists to prevent. The
frontend renders what this endpoint returns and derives no money of its own.

⚠ RECALCULATION SPLIT — see :data:`RECALC_AO_SHARE`. A recalculation's profit
delta splits 25 % to Corporate and 75 % to A&O. The prototype's Calculator page
*also* subtracted the 25 % from A&O's side, netting only 50 % of the delta; its
Dashboard netted the documented 75 %. We serve 75 %. If Finance rules that the
50 % behaviour was intentional, flip :data:`RECALC_AO_SHARE` to ``0.50`` — it is
the single place the rule is expressed.

Data sources (Bruno PDF 2026-10-05):

* **A&O inputs** — Revenue / Carrier Cost / Profit are ``SUM(total_charge /
  total_carrier_pay / margin_amt)`` over v4 ``TEAM-DFW`` for the month
  (``services/division_payment_v4.py``). An operator may override any of the
  three; the override lives in ``dpc_months.*_override`` (NULL = use v4) and the
  UI flags the month. Profit is ``SUM(margin_amt)`` — NOT revenue − cost; the two
  differ by a few dollars a month in v4 and the PDF names margin_amt.
* **GL deductions, archives, notes** — portal-owned ``dpc_*`` tables in
  ``analytics_hub``, created in ``main.py``'s lifespan. A&O's GL lines live in the
  accounting system, which no portal database can reach.
"""

from __future__ import annotations

import json
import logging
from decimal import Decimal
from typing import Any, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field, field_validator

from app.clock import cst_today
from app.routers.deps import get_pool, require_report_access
from app.services.division_payment_defaults import ensure_months_through
from app.services.division_payment_v4 import (
    MonthTotals,
    add_months,
    fetch_month_totals,
    month_index,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/custom/division-payment", tags=["division-payment"])

REPORT_KEY = "division-payment-calculator"
_access = require_report_access(REPORT_KEY)

# --- business constants ----------------------------------------------------
TARGET_MARGIN_PCT = Decimal("10")      # the margin A&O must hit to avoid a tariff
CORPORATE_SHARE = Decimal("0.25")      # Corporate's cut of profit
RECALC_CORP_SHARE = Decimal("0.25")    # Corporate's cut of a recalculation delta
RECALC_AO_SHARE = Decimal("0.75")      # A&O's cut of a recalculation delta

MONTH_ORDER = [
    "january", "february", "march", "april", "may", "june",
    "july", "august", "september", "october", "november", "december",
]

CATEGORY_LABELS = {
    "payroll": "Payroll & Personnel",
    "facilities": "Facilities & Parking",
    "subscriptions": "Dues & Subscriptions",
    "travel": "Travel & Transportation",
    "it": "IT & Technology",
    "other": "Other Expenses",
}
CATEGORY_COLORS = {
    "payroll": "#1e293b", "facilities": "#0f766e", "subscriptions": "#7c3aed",
    "travel": "#b8923a", "it": "#0369a1", "other": "#9f1239",
}


def _d(v: Any) -> Decimal:
    """Coerce anything asyncpg hands back (Decimal / float / None) to Decimal."""
    if v is None:
        return Decimal(0)
    return v if isinstance(v, Decimal) else Decimal(str(v))


def _money(v: Decimal) -> float:
    return float(round(v, 2))


def _pct(v: Decimal) -> float:
    return float(round(v, 4))


def _opt_money(v: Any) -> Optional[float]:
    return None if v is None else _money(_d(v))


# ---------------------------------------------------------------------------
# The one and only computation
# ---------------------------------------------------------------------------
def compute_summary(
    revenue: Any, carrier_cost: Any, profit: Any, gl_deductions: Any,
    frozen_tariff: Any = None,
) -> dict[str, Any]:
    """Return every derived money figure for one month.

    ``frozen_tariff`` pins the tariff to an approved archive's value instead of
    recomputing it — that is what makes a recalculation's delta split cleanly
    25/75. Recalculations never re-open the tariff even if the revised margin
    crosses the 10 % line; it was settled when the month was approved.
    """
    revenue, carrier_cost, profit = _d(revenue), _d(carrier_cost), _d(profit)
    gl = _d(gl_deductions)

    margin_pct = (profit / revenue * 100) if revenue > 0 else Decimal(0)
    target_profit = revenue * (TARGET_MARGIN_PCT / 100)
    target_fee = target_profit * CORPORATE_SHARE
    actual_fee = profit * CORPORATE_SHARE

    if frozen_tariff is not None:
        tariff = _d(frozen_tariff)
    elif margin_pct >= TARGET_MARGIN_PCT:
        tariff = Decimal(0)
    else:
        tariff = max(Decimal(0), target_fee - actual_fee)

    corporate_gain = actual_fee + tariff
    net_payment = profit - gl - corporate_gain

    return {
        "revenue": _money(revenue),
        "carrier_cost": _money(carrier_cost),
        "profit": _money(profit),
        "margin_pct": _pct(margin_pct),
        "meets_target": bool(margin_pct >= TARGET_MARGIN_PCT),
        "target_margin_pct": float(TARGET_MARGIN_PCT),
        # Tariff breakdown (PDF Dashboard Request 4) — the five KPI cards.
        "ten_pct_of_revenue": _money(target_profit),
        "target_fee": _money(target_fee),
        "actual_fee": _money(actual_fee),
        "difference": _money(target_fee - actual_fee),
        "gl_deductions": _money(gl),
        "penalty_fee": _money(tariff),
        "corporate_gain": _money(corporate_gain),
        "net_payment": _money(net_payment),
    }


def _gl_rollup(rows: list) -> tuple[Decimal, list[dict], list[dict]]:
    """Σ of included amounts, the per-category KPI strip, and the row list."""
    total = Decimal(0)
    by_cat: dict[str, dict] = {}
    out_rows: list[dict] = []

    for r in rows:
        amount = _d(r["amount"])
        cat = r["category"]
        if r["included"]:
            total += amount
        bucket = by_cat.setdefault(cat, {
            "category": cat,
            "label": CATEGORY_LABELS.get(cat, cat.title()),
            "color": CATEGORY_COLORS.get(cat, "#64748b"),
            "amount": Decimal(0), "row_count": 0, "included_count": 0,
        })
        bucket["row_count"] += 1
        if r["included"]:
            bucket["amount"] += amount
            bucket["included_count"] += 1
        out_rows.append({
            "id": str(r["id"]),
            "code": r["code"],
            "category": cat,
            "category_label": CATEGORY_LABELS.get(cat, cat.title()),
            "description": r["description"],
            "amount": _money(amount),
            "included": r["included"],
            "is_custom": r["is_custom"],
        })

    ordered = [by_cat[c] for c in CATEGORY_LABELS if c in by_cat]
    ordered += [v for k, v in by_cat.items() if k not in CATEGORY_LABELS]
    for b in ordered:
        b["amount"] = _money(b["amount"])
        b["all_included"] = b["included_count"] == b["row_count"]
    return total, ordered, out_rows


async def _month_row(pool, year: int, month: str):
    row = await pool.fetchrow(
        "SELECT * FROM dpc_months WHERE year = $1 AND month = $2", year, month
    )
    if not row:
        raise HTTPException(status_code=404, detail=f"No data for {month} {year}")
    return row


async def _gl_rows(pool, month_id) -> list:
    """Live GL rows — soft-deleted rows (``deleted_at``) never count."""
    return await pool.fetch(
        """
        SELECT id, code, category, description, amount, included, is_custom
        FROM dpc_gl_accounts WHERE month_id = $1 AND deleted_at IS NULL
        ORDER BY sort_order, created_at
        """,
        month_id,
    )


def _gold_pool(request: Request):
    """The datalake pool, or a 503 — never a page of $0 that reads as a quiet month."""
    pool = getattr(request.app.state, "savings_pool", None)
    if pool is None:
        raise HTTPException(status_code=503, detail="Datalake (gold) not configured")
    return pool


async def _v4_totals(request: Request, year: int, month: str, span: int = 0) -> dict:
    """v4 TEAM-DFW totals for ``(year, month)`` and the ``span`` months before it."""
    end = (year, month_index(month))
    start = add_months(*end, -span)
    try:
        return await fetch_month_totals(_gold_pool(request), start, end)
    except HTTPException:
        raise
    except Exception as e:  # noqa: BLE001 — surfaced as a 503, never as $0
        # Logged here, generic to the browser: a connection error names the host.
        logger.error("Division Payment v4 read failed: %s", e, exc_info=True)
        raise HTTPException(status_code=503, detail="Datalake unavailable") from e


def _effective(m, totals: MonthTotals) -> dict[str, Decimal]:
    """Override when set, else the v4 figure — per field, independently."""
    def pick(override, v4):
        return _d(override) if override is not None else v4

    return {
        "revenue": pick(m["revenue_override"], totals.revenue),
        "carrier_cost": pick(m["carrier_cost_override"], totals.carrier_cost),
        "profit": pick(m["profit_override"], totals.profit),
    }


def _is_overridden(m) -> bool:
    return any(
        m[k] is not None
        for k in ("revenue_override", "carrier_cost_override", "profit_override")
    )


async def _recalc_adjustment(pool, year: int, month: str) -> tuple[Decimal, Decimal, list[dict]]:
    """Recalcs carried INTO this month. Returns (Δ to A&O, Δ to Corporate, rows).

    ⚠ ``status`` is deliberately not filtered: a *pending* recalc is still shown
    in the month it lands on, matching the prototype. The status badge tells the
    operator whether it has been settled; it does not change the arithmetic.
    """
    rows = await pool.fetch(
        """
        SELECT recalc_key, month_label, applied_to_month, status, recalc_date,
               previously_recalculated, diff
        FROM dpc_recalcs
        WHERE applied_to_month = $1 AND year = $2
        ORDER BY recalc_date
        """,
        month, year,
    )
    ao = corp = Decimal(0)
    out = []
    for r in rows:
        diff = json.loads(r["diff"]) if isinstance(r["diff"], str) else r["diff"]
        d_profit = _d(diff.get("profit"))
        d_ao = d_profit * RECALC_AO_SHARE
        d_corp = d_profit * RECALC_CORP_SHARE
        ao += d_ao
        corp += d_corp
        out.append({
            "recalc_key": r["recalc_key"],
            "month_label": r["month_label"],
            "status": r["status"],
            "recalc_date": r["recalc_date"].isoformat() if r["recalc_date"] else None,
            "previously_recalculated": r["previously_recalculated"],
            "revenue_delta": _money(_d(diff.get("revenue"))),
            "cost_delta": _money(_d(diff.get("carrier_cost"))),
            "profit_delta": _money(d_profit),
            "corporate_delta": _money(d_corp),
            "ao_delta": _money(d_ao),
        })
    return ao, corp, out


# ---------------------------------------------------------------------------
# Read endpoints
# ---------------------------------------------------------------------------
@router.get("/periods")
async def periods(request: Request, user: dict = Depends(_access)):
    """Year filter + month/year filter options (PDF Dashboard Request 1)."""
    pool = get_pool(request)
    today = cst_today()
    await ensure_months_through(pool, today)
    rows = await pool.fetch(
        """
        SELECT year, month, month_label,
               (revenue_override IS NOT NULL OR carrier_cost_override IS NOT NULL
                OR profit_override IS NOT NULL) AS overridden
          FROM dpc_months
         ORDER BY year, array_position($1::text[], month)
        """,
        MONTH_ORDER,
    )
    approved = {
        f"{r['year']}-{r['month']}"
        for r in await pool.fetch("SELECT year, month FROM dpc_snapshots")
    }
    has_recalc = {
        f"{r['year']}-{r['applied_to_month']}"
        for r in await pool.fetch("SELECT year, applied_to_month FROM dpc_recalcs")
    }
    months = [{
        "year": r["year"], "month": r["month"], "month_label": r["month_label"],
        "approved": f"{r['year']}-{r['month']}" in approved,
        "has_recalc": f"{r['year']}-{r['month']}" in has_recalc,
        "overridden": r["overridden"],
    } for r in rows]
    years = sorted({m["year"] for m in months}, reverse=True)
    # Default to the month being PAID — the previous one — not the month in
    # progress, whose v4 total is still a partial month-to-date.
    py, pm = add_months(today.year, today.month, -1)
    default = next(
        ({"year": m["year"], "month": m["month"]} for m in months
         if m["year"] == py and m["month"] == MONTH_ORDER[pm - 1]),
        None,
    )
    return {"success": True, "data": {"years": years, "months": months, "default": default}}


@router.get("/summary")
async def summary(
    request: Request,
    year: int,
    month: str,
    user: dict = Depends(_access),
):
    """Everything both tabs render for one month. The single source of truth."""
    pool = get_pool(request)
    month = month.strip().lower()
    if month not in MONTH_ORDER:
        raise HTTPException(status_code=422, detail="Unknown month")

    await ensure_months_through(pool, cst_today())
    m = await _month_row(pool, year, month)
    rows = await _gl_rows(pool, m["id"])
    gl_total, categories, gl_rows = _gl_rollup(rows)

    # One v4 scan covers this month AND the previous one.
    totals = await _v4_totals(request, year, month, span=1)
    v4 = totals[(year, month_index(month))]
    eff = _effective(m, v4)

    base = compute_summary(eff["revenue"], eff["carrier_cost"], eff["profit"], gl_total)
    ao_adj, corp_adj, recalcs = await _recalc_adjustment(pool, year, month)

    # Prior month, for the Dashboard's "vs previous month" line. Compared on the
    # SAME basis (adjusted net vs adjusted net) so the delta is honest.
    prev = await _previous_net(pool, year, month, totals)

    net_adjusted = _d(base["net_payment"]) + ao_adj
    delta = net_adjusted - prev["net"] if prev else None

    approved = await pool.fetchrow(
        "SELECT snapshot_date, approved_at, approved_by FROM dpc_snapshots "
        "WHERE year = $1 AND month = $2",
        year, month,
    )

    return {"success": True, "data": {
        "year": year, "month": month, "month_label": m["month_label"],
        "inputs": {
            "revenue": _money(eff["revenue"]),
            "carrier_cost": _money(eff["carrier_cost"]),
            "profit": _money(eff["profit"]),
        },
        "datalake": {
            "revenue": _money(v4.revenue),
            "carrier_cost": _money(v4.carrier_cost),
            "profit": _money(v4.profit),
            "order_count": v4.order_count,
            "available": True,
        },
        "overrides": {
            "revenue": _opt_money(m["revenue_override"]),
            "carrier_cost": _opt_money(m["carrier_cost_override"]),
            "profit": _opt_money(m["profit_override"]),
            "updated_at": (
                m["override_updated_at"].isoformat() if m["override_updated_at"] else None
            ),
            "updated_by": m["override_updated_by"],
        },
        "overridden": _is_overridden(m),
        **base,
        "corporate_gain_total": _money(_d(base["corporate_gain"]) + corp_adj),
        "net_payment_adjusted": _money(net_adjusted),
        "recalc_ao_adjustment": _money(ao_adj),
        "recalc_corporate_adjustment": _money(corp_adj),
        "recalcs": recalcs,
        "previous": prev and {"month_label": prev["label"], "net_payment": _money(prev["net"])},
        "delta_vs_previous": _money(delta) if delta is not None else None,
        "delta_pct_vs_previous": (
            _pct(delta / prev["net"] * 100) if prev and prev["net"] != 0 and delta is not None
            else None
        ),
        "gl_accounts": gl_rows,
        "gl_categories": categories,
        "gl_included_count": sum(1 for r in gl_rows if r["included"]),
        "gl_row_count": len(gl_rows),
        "approved": bool(approved),
        "approved_at": approved["approved_at"].isoformat() if approved and approved["approved_at"] else None,
        "approved_by": approved["approved_by"] if approved else None,
    }}


async def _previous_net(pool, year: int, month: str, totals: dict) -> Optional[dict]:
    """The month immediately before ``(year, month)``, on the adjusted basis.

    ``totals`` must already hold the previous month's v4 figures — the caller
    fetched both months in one scan.
    """
    p_year, p_num = add_months(year, month_index(month), -1)
    p_month = MONTH_ORDER[p_num - 1]
    row = await pool.fetchrow(
        "SELECT * FROM dpc_months WHERE year = $1 AND month = $2", p_year, p_month
    )
    if not row:
        return None
    rows = await _gl_rows(pool, row["id"])
    gl_total, _, _ = _gl_rollup(rows)
    eff = _effective(row, totals[(p_year, p_num)])
    base = compute_summary(eff["revenue"], eff["carrier_cost"], eff["profit"], gl_total)
    ao_adj, _, _ = await _recalc_adjustment(pool, p_year, p_month)
    return {"label": row["month_label"], "net": _d(base["net_payment"]) + ao_adj}


@router.get("/archives")
async def archives(request: Request, user: dict = Depends(_access)):
    """Approved Archives — the baseline every recalculation compares against."""
    pool = get_pool(request)
    rows = await pool.fetch(
        """
        SELECT year, month, month_label, revenue, carrier_cost, profit, margin_pct,
               gl_deductions, penalty_fee, corporate_gain, net_payment,
               snapshot_date, approved_at, approved_by
        FROM dpc_snapshots s
        ORDER BY s.year DESC,
                 array_position($1::text[], s.month)
        """,
        MONTH_ORDER,
    )
    return {"success": True, "data": [{
        "year": r["year"], "month": r["month"], "month_label": r["month_label"],
        "revenue": _money(_d(r["revenue"])), "carrier_cost": _money(_d(r["carrier_cost"])),
        "profit": _money(_d(r["profit"])), "margin_pct": _pct(_d(r["margin_pct"])),
        "gl_deductions": _money(_d(r["gl_deductions"])),
        "penalty_fee": _money(_d(r["penalty_fee"])),
        "corporate_gain": _money(_d(r["corporate_gain"])),
        "net_payment": _money(_d(r["net_payment"])),
        "snapshot_date": r["snapshot_date"].isoformat() if r["snapshot_date"] else None,
        "approved_by": r["approved_by"],
    } for r in rows]}


@router.get("/recalcs")
async def recalcs(request: Request, user: dict = Depends(_access)):
    """Recalculation records with their audit loads (PDF Recalculations tab)."""
    pool = get_pool(request)
    rows = await pool.fetch(
        """
        SELECT recalc_key, year, month, month_label, applied_to_month,
               applied_to_month_label, recalc_date, status, previously_recalculated,
               prior_recalc_net_payment, snapshot, tms_update, diff, note
        FROM dpc_recalcs ORDER BY recalc_date
        """
    )
    loads = await pool.fetch(
        """
        SELECT recalc_key, load_number, client, change_type, change_description,
               original_revenue, updated_revenue, original_carrier_cost,
               updated_carrier_cost, revenue_delta, cost_delta, audit_date
        FROM dpc_audit_loads ORDER BY load_number
        """
    )
    by_key: dict[str, list] = {}
    for l in loads:
        by_key.setdefault(l["recalc_key"], []).append({
            "load_number": l["load_number"], "client": l["client"],
            "change_type": l["change_type"], "change_description": l["change_description"],
            "original_revenue": _money(_d(l["original_revenue"])),
            "updated_revenue": _money(_d(l["updated_revenue"])),
            "original_carrier_cost": _money(_d(l["original_carrier_cost"])),
            "updated_carrier_cost": _money(_d(l["updated_carrier_cost"])),
            "revenue_delta": _money(_d(l["revenue_delta"])),
            "cost_delta": _money(_d(l["cost_delta"])),
        })

    def _j(v):
        return json.loads(v) if isinstance(v, str) else v

    out = []
    for r in rows:
        diff = _j(r["diff"])
        out.append({
            "recalc_key": r["recalc_key"], "year": r["year"], "month": r["month"],
            "month_label": r["month_label"], "applied_to_month": r["applied_to_month"],
            "applied_to_month_label": r["applied_to_month_label"],
            "recalc_date": r["recalc_date"].isoformat() if r["recalc_date"] else None,
            "status": r["status"],
            "previously_recalculated": r["previously_recalculated"],
            "prior_recalc_net_payment": (
                _money(_d(r["prior_recalc_net_payment"]))
                if r["prior_recalc_net_payment"] is not None else None
            ),
            "snapshot": _j(r["snapshot"]), "tms_update": _j(r["tms_update"]), "diff": diff,
            "corporate_share": _money(_d(diff.get("profit")) * RECALC_CORP_SHARE),
            "ao_share": _money(_d(diff.get("profit")) * RECALC_AO_SHARE),
            "note": r["note"] or "",
            "loads": by_key.get(r["recalc_key"], []),
        })
    return {"success": True, "data": out}


# ---------------------------------------------------------------------------
# Mutations
# ---------------------------------------------------------------------------
class MonthOverrides(BaseModel):
    """Manual A&O values (Bruno PDF 2026-10-05 R3). ``null`` clears a field back
    to the v4 figure; a key that is not SENT is left as it is (``model_fields_set``)."""
    revenue: Optional[float] = Field(default=None, ge=0, le=1e12)
    carrier_cost: Optional[float] = Field(default=None, ge=0, le=1e12)
    profit: Optional[float] = Field(default=None, ge=-1e12, le=1e12)


def _known_category(v: str) -> str:
    v = v.strip().lower()
    if v not in CATEGORY_LABELS:
        raise ValueError("Unknown category")
    return v


class GLPatch(BaseModel):
    """Edit any field of ANY row, template or added (Bruno PDF 2026-10-05 R1)."""
    amount: Optional[float] = Field(default=None, ge=0, le=1e12)
    included: Optional[bool] = None
    code: Optional[str] = Field(default=None, max_length=40)
    description: Optional[str] = Field(default=None, min_length=1, max_length=300)
    category: Optional[str] = Field(default=None, min_length=1, max_length=40)

    @field_validator("category")
    @classmethod
    def _category(cls, v: Optional[str]) -> Optional[str]:
        return None if v is None else _known_category(v)

    @field_validator("description")
    @classmethod
    def _description(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return None
        if not v.strip():
            raise ValueError("Description is required")
        return v.strip()


class GLCreate(BaseModel):
    code: str = Field(default="", max_length=40)
    category: str = Field(min_length=1, max_length=40)
    description: str = Field(min_length=1, max_length=300)
    amount: float = Field(ge=0, le=1e12)

    @field_validator("category")
    @classmethod
    def _category(cls, v: str) -> str:
        return _known_category(v)


class CategoryToggle(BaseModel):
    category: str = Field(min_length=1, max_length=40)
    included: bool


_OVERRIDE_COLS = {
    "revenue": "revenue_override",
    "carrier_cost": "carrier_cost_override",
    "profit": "profit_override",
}


@router.put("/months/{year}/{month}/overrides")
async def save_overrides(
    year: int, month: str, body: MonthOverrides,
    request: Request, user: dict = Depends(_access),
):
    """Set or clear the manual A&O values (Bruno PDF 2026-10-05 R3).

    Replaces the old ``PUT /months/{y}/{m}``, which overwrote the inputs
    outright. A value here never touches the v4 figure — it sits beside it, so
    the UI can show both and "Reset to datalake" is a plain ``null``.
    """
    pool = get_pool(request)
    month = month.strip().lower()
    if month not in MONTH_ORDER:
        raise HTTPException(status_code=422, detail="Unknown month")
    fields = [f for f in ("revenue", "carrier_cost", "profit") if f in body.model_fields_set]
    if not fields:
        raise HTTPException(status_code=422, detail="Nothing to update")
    params: list[Any] = [year, month, user.get("email") or user.get("sub")]
    sets = []
    for f in fields:
        params.append(getattr(body, f))
        sets.append(f"{_OVERRIDE_COLS[f]} = ${len(params)}")
    updated = await pool.fetchval(
        f"UPDATE dpc_months SET {', '.join(sets)}, override_updated_by = $3, "
        f"override_updated_at = NOW(), updated_at = NOW() "
        f"WHERE year = $1 AND month = $2 RETURNING id",
        *params,
    )
    if not updated:
        raise HTTPException(status_code=404, detail=f"No data for {month} {year}")
    return {"success": True, "data": {"year": year, "month": month, "fields": fields}}


@router.post("/months/{year}/{month}/gl")
async def add_expense(
    year: int, month: str, body: GLCreate,
    request: Request, user: dict = Depends(_access),
):
    """PDF Calculator Request 5 — the "Add Expense" button."""
    pool = get_pool(request)
    m = await _month_row(pool, year, month.strip().lower())
    next_order = await pool.fetchval(
        "SELECT COALESCE(MAX(sort_order), 0) + 1 FROM dpc_gl_accounts WHERE month_id = $1",
        m["id"],
    )
    new_id = await pool.fetchval(
        """
        INSERT INTO dpc_gl_accounts
          (month_id, code, category, description, amount, included, is_custom, sort_order, created_by)
        VALUES ($1,$2,$3,$4,$5,TRUE,TRUE,$6,$7)
        RETURNING id
        """,
        m["id"], body.code.strip() or "—", body.category, body.description.strip(),
        body.amount, next_order, user.get("email") or user.get("sub"),
    )
    return {"success": True, "data": {"id": str(new_id)}}


@router.patch("/gl/{gl_id}")
async def patch_expense(
    gl_id: UUID, body: GLPatch, request: Request, user: dict = Depends(_access),
):
    """Edit any field of a row — template or added — or toggle Include.

    Column names come from this fixed tuple, never from the request; only the
    VALUES are bound.
    """
    changes = {
        col: getattr(body, col)
        for col in ("amount", "included", "code", "description", "category")
        if getattr(body, col) is not None
    }
    if not changes:
        raise HTTPException(status_code=422, detail="Nothing to update")
    if "code" in changes:
        changes["code"] = changes["code"].strip() or "—"
    pool = get_pool(request)
    sets, params = [], [gl_id]
    for col, value in changes.items():
        params.append(value)
        sets.append(f"{col} = ${len(params)}")
    updated = await pool.fetchval(
        f"UPDATE dpc_gl_accounts SET {', '.join(sets)}, updated_at = NOW() "
        f"WHERE id = $1 AND deleted_at IS NULL RETURNING id",
        *params,
    )
    if not updated:
        raise HTTPException(status_code=404, detail="GL account not found")
    return {"success": True, "data": {"id": str(gl_id)}}


@router.delete("/gl/{gl_id}")
async def delete_expense(gl_id: UUID, request: Request, user: dict = Depends(_access)):
    """Delete ANY row, template or added (Bruno PDF 2026-10-05 R1).

    ⚠ A SOFT delete. The startup seeder refills a month that has zero GL rows,
    so a hard delete of a month's last row would bring the whole template back
    on the next deploy. The row stays, stamped ``deleted_at``, and every read
    filters it out.
    """
    pool = get_pool(request)
    deleted = await pool.fetchval(
        "UPDATE dpc_gl_accounts SET deleted_at = NOW(), deleted_by = $2, updated_at = NOW() "
        "WHERE id = $1 AND deleted_at IS NULL RETURNING id",
        gl_id, user.get("email") or user.get("sub"),
    )
    if not deleted:
        raise HTTPException(status_code=404, detail="GL account not found")
    return {"success": True, "data": {"id": str(gl_id)}}


@router.post("/months/{year}/{month}/gl/category")
async def toggle_category(
    year: int, month: str, body: CategoryToggle,
    request: Request, user: dict = Depends(_access),
):
    """Include/exclude an entire GL category in one call."""
    pool = get_pool(request)
    m = await _month_row(pool, year, month.strip().lower())
    rows = await pool.fetch(
        "UPDATE dpc_gl_accounts SET included = $3, updated_at = NOW() "
        "WHERE month_id = $1 AND category = $2 AND deleted_at IS NULL RETURNING id",
        m["id"], body.category.strip().lower(), body.included,
    )
    return {"success": True, "data": {"updated": len(rows)}}


@router.post("/months/{year}/{month}/approve")
async def approve(year: int, month: str, request: Request, user: dict = Depends(_access)):
    """Freeze the month as an Approved Archive — the recalculation baseline.

    Re-approving overwrites the archive: the operator has explicitly re-run the
    month. Recalcs already written keep their own frozen snapshot, so a
    re-approval cannot retroactively move a settled differential.
    """
    pool = get_pool(request)
    month = month.strip().lower()
    m = await _month_row(pool, year, month)
    rows = await _gl_rows(pool, m["id"])
    gl_total, _, _ = _gl_rollup(rows)
    # Archive exactly what the Calculator shows: the override where one is set,
    # the live v4 figure otherwise.
    totals = await _v4_totals(request, year, month)
    eff = _effective(m, totals[(year, month_index(month))])
    s = compute_summary(eff["revenue"], eff["carrier_cost"], eff["profit"], gl_total)
    await pool.execute(
        """
        INSERT INTO dpc_snapshots
          (year, month, month_label, revenue, carrier_cost, profit, margin_pct,
           gl_deductions, penalty_fee, corporate_gain, net_payment, snapshot_date,
           approved_by, approved_at)
        VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,CURRENT_DATE,$12,NOW())
        ON CONFLICT (year, month) DO UPDATE SET
          revenue = EXCLUDED.revenue, carrier_cost = EXCLUDED.carrier_cost,
          profit = EXCLUDED.profit, margin_pct = EXCLUDED.margin_pct,
          gl_deductions = EXCLUDED.gl_deductions, penalty_fee = EXCLUDED.penalty_fee,
          corporate_gain = EXCLUDED.corporate_gain, net_payment = EXCLUDED.net_payment,
          snapshot_date = EXCLUDED.snapshot_date, approved_by = EXCLUDED.approved_by,
          approved_at = NOW()
        """,
        year, month, m["month_label"], s["revenue"], s["carrier_cost"], s["profit"],
        s["margin_pct"], s["gl_deductions"], s["penalty_fee"], s["corporate_gain"],
        s["net_payment"], user.get("email") or user.get("sub"),
    )
    return {"success": True, "data": s}


class RecalcNote(BaseModel):
    note: str = Field(default="", max_length=4000)


@router.put("/recalcs/{recalc_key}/note")
async def save_note(
    recalc_key: str, body: RecalcNote, request: Request, user: dict = Depends(_access),
):
    """Refacturación notes — free text against a recalculation record."""
    pool = get_pool(request)
    updated = await pool.fetchval(
        "UPDATE dpc_recalcs SET note = $2, note_updated_at = NOW(), note_updated_by = $3 "
        "WHERE recalc_key = $1 RETURNING recalc_key",
        recalc_key, body.note, user.get("email") or user.get("sub"),
    )
    if not updated:
        raise HTTPException(status_code=404, detail="Recalculation not found")
    return {"success": True, "data": {"recalc_key": recalc_key}}
