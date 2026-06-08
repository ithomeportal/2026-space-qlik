"""Code-made report: Bonus Calculator (CEO + HR only).

Reproduces Bruno's HR-Headquarters bonus module (PDF + package, 2026-05-24),
fed by **live datalake** team metrics — the same source XRay CORP Mng reads —
instead of a sample workbook. See docs/SPEC-BONUS-CALCULATOR.md.

Data sources (all on SAVINGS_DATABASE_URL / get_datalake_gold_pool):
- public.mcleod_gld_budget_report_v4  (load-level loads/revenue/profit/margin)
- public.mcleod_gld_scorecard          (OTP/OTD -> pickup/delivery service %)

Editable HR data (analytics_hub / primary pool):
- bonus_roster, bonus_afterhours      (who is KAM/FM/T&T, salaries — Q4 seeded)
- bonus_settings                       (HR board-pinned team_fx + night_fx per period — Q3)
- bonus_period_lock                    (HR/Finance month approval — PDF best-practice)

fxRate is HR-board-pinned (Q3). The DOF/Banxico-FIX value from the optional
FINANCIAL_DATABASE_URL pool is exposed only as a *suggested* prefill.

Scope (Q1): bonus teams TEAM1..TEAM4 (team-1..4), same company/status/OILTEX
scope as xray-corp (reuses its scope + scorecard helpers so service % matches).
Period (Q2): 6th-of-month -> 6th-of-next-month; four 7-day weekly buckets from
the 6th, trailing remainder folded into Week 4.
"""

from __future__ import annotations

import asyncio
import logging
from calendar import month_name
from datetime import date
from typing import Optional

from fastapi import APIRouter, Body, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field

from app.clock import cst_today
from app.routers import xray_corp
from app.routers.deps import (
    get_datalake_gold_pool,
    get_pool,
    require_report_access,
)
from app.services.bonus_defaults import (
    DEFAULT_NIGHT_FX_RATE,
    DEFAULT_TEAM_FX_RATE,
    DEFAULT_TEAM_NAMES,
)
from app.services.bonus_engine import build_bonus_report

logger = logging.getLogger(__name__)

REPORT_KEY = "bonus-calculator"
BONUS_TEAMS = ("team-1", "team-2", "team-3", "team-4")  # Q1: TEAM5 excluded (no roster)
VALID_ROLES = ("kam", "freight_match", "tracking_tracing")

router = APIRouter(tags=["bonus-calculator"], prefix="/custom/bonus-calculator")


# ---------------------------------------------------------------------------
# Period / weekly-bucket helpers (Q2)
# ---------------------------------------------------------------------------


def _current_period_key() -> str:
    """The 'YYYY-MM' calendar month we default to today (CST).

    A month's data keeps updating until the cutoff on the 5th of the following
    month (Bruno, 2026-05-26), so before the 6th we still default to the prior
    month that is being finalized.
    """
    today = cst_today()
    if today.day >= 6:
        return f"{today.year:04d}-{today.month:02d}"
    py, pm = (today.year - 1, 12) if today.month == 1 else (today.year, today.month - 1)
    return f"{py:04d}-{pm:02d}"


def _parse_period(period: Optional[str]) -> tuple[int, int]:
    key = period or _current_period_key()
    try:
        y, m = key.split("-")
        return int(y), int(m)
    except (ValueError, AttributeError):
        raise HTTPException(status_code=422, detail="period must be 'YYYY-MM'")


def _month_weeks(y: int, m: int) -> list[tuple[str, date, date]]:
    """Monday→Sunday weeks belonging to calendar month (y, m).

    A week belongs to the month that contains its Monday, so the final week can
    spill into the next month (e.g. June Week 5 = 29 Jun-05 Jul) and the days
    before the month's first Monday belong to the prior month. This yields 4 or
    5 weeks per month (Bruno, 2026-05-26).
    """
    first = date(y, m, 1)
    offset = (7 - first.weekday()) % 7  # days to the first Monday on/after the 1st
    monday = date.fromordinal(first.toordinal() + offset)
    weeks: list[tuple[str, date, date]] = []
    while monday.month == m:
        sunday = date.fromordinal(monday.toordinal() + 6)
        label = (
            f"{monday.day:02d} {month_name[monday.month][:3]}-"
            f"{sunday.day:02d} {month_name[sunday.month][:3]}"
        )
        weeks.append((label, monday, sunday))
        monday = date.fromordinal(monday.toordinal() + 7)
    return weeks


def _period_bounds(period: Optional[str]):
    """Return (period_key, label, start, end_exclusive, buckets).

    ``start``/``end`` span the union of the month's Monday→Sunday weeks, so the
    datalake read window matches exactly what the weekly buckets cover.
    """
    y, m = _parse_period(period)
    buckets = _month_weeks(y, m)
    start = buckets[0][1]  # first Monday
    end = date.fromordinal(buckets[-1][2].toordinal() + 1)  # day after last Sunday (exclusive)
    label = f"{month_name[m]} {y}"
    return f"{y:04d}-{m:02d}", label, start, end, buckets


def _recent_period_keys(count: int = 12) -> list[str]:
    y, m = _parse_period(_current_period_key())
    out = []
    for _ in range(count):
        out.append(f"{y:04d}-{m:02d}")
        y, m = (y - 1, 12) if m == 1 else (y, m - 1)
    return out


# ---------------------------------------------------------------------------
# Datalake feed — per-team weekly metrics + period service %
# ---------------------------------------------------------------------------


async def _team_metrics(
    pool, team_no: int, start: date, end: date, buckets, month_start: date, month_end: date
) -> dict:
    """Per-team weekly loads/rev/profit (×N buckets) + period OTP/OTD AND the
    calendar-month cumulative loads/rev/profit/service for one team.

    Reuses xray-corp's scope + scorecard CTEs so service % matches that report.

    Two windows on the same scan (Bruno 2026-05-28):
      - period [start, end): the Mon→Sun weekly union — drives the bonus payout
        math (weekly buckets) and the weekly-period service %.
      - month [month_start, month_end): the calendar 1st→last day — drives the
        display KPIs (Loads/Profit/Margin/Service) which must be the month
        cumulative, NOT the sum of the weekly buckets.
    The read window is the union of both so month-edge days are fetched.
    """
    read_lo = min(start, month_start)
    read_hi = max(end, month_end)

    params: list = []
    where = xray_corp._scope_where("br4", f"TEAM{team_no}", None, params)
    params.append(read_lo)
    p_lo = len(params)
    params.append(read_hi)
    p_hi = len(params)
    params.append(start)
    p_start = len(params)
    params.append(end)
    p_end = len(params)
    params.append(month_start)
    p_ms = len(params)
    params.append(month_end)
    p_me = len(params)

    select_parts: list[str] = []
    for i, (_label, bstart, bend) in enumerate(buckets, start=1):
        params.append(bstart)
        ps = len(params)
        params.append(bend)
        pe = len(params)
        select_parts.append(
            f"COUNT(*) FILTER (WHERE dep_date BETWEEN ${ps} AND ${pe} "
            f"AND total_charge IS NOT NULL AND total_charge <> 0) AS w{i}_loads"
        )
        select_parts.append(
            f"COALESCE(SUM(total_charge) FILTER (WHERE dep_date BETWEEN ${ps} AND ${pe}), 0)::numeric AS w{i}_rev"
        )
        select_parts.append(
            f"COALESCE(SUM(margin_amt) FILTER (WHERE dep_date BETWEEN ${ps} AND ${pe}), 0)::numeric AS w{i}_prof"
        )
        # Per-week OTP/OTD exception counts so the Actual Data table can show a
        # distinct (pickup+delivery)/2 per week (Bruno 2026-05-28). Display only —
        # the payout still rides on the period/monthly service average below.
        select_parts.append(
            f"COALESCE(SUM(otp_cnt) FILTER (WHERE dep_date BETWEEN ${ps} AND ${pe}), 0) AS w{i}_otp"
        )
        select_parts.append(
            f"COALESCE(SUM(otd_cnt) FILTER (WHERE dep_date BETWEEN ${ps} AND ${pe}), 0) AS w{i}_otd"
        )

    # Period (weekly-union) totals — service that feeds the bonus math.
    period_filter = f"WHERE dep_date >= ${p_start} AND dep_date < ${p_end}"
    select_parts.append(
        f"COUNT(*) FILTER ({period_filter} AND total_charge IS NOT NULL AND total_charge <> 0) AS loads"
    )
    select_parts.append(f"COALESCE(SUM(otp_cnt) FILTER ({period_filter}), 0) AS otp_sum")
    select_parts.append(f"COALESCE(SUM(otd_cnt) FILTER ({period_filter}), 0) AS otd_sum")

    # Calendar-month cumulative — the display KPIs.
    month_filter = f"WHERE dep_date >= ${p_ms} AND dep_date < ${p_me}"
    select_parts.append(
        f"COUNT(*) FILTER ({month_filter} AND total_charge IS NOT NULL AND total_charge <> 0) AS m_loads"
    )
    select_parts.append(f"COALESCE(SUM(total_charge) FILTER ({month_filter}), 0)::numeric AS m_rev")
    select_parts.append(f"COALESCE(SUM(margin_amt) FILTER ({month_filter}), 0)::numeric AS m_prof")
    select_parts.append(f"COALESCE(SUM(otp_cnt) FILTER ({month_filter}), 0) AS m_otp")
    select_parts.append(f"COALESCE(SUM(otd_cnt) FILTER ({month_filter}), 0) AS m_otd")

    sql = f"""
        WITH otp AS ({xray_corp._scorecard_cte("otp")}),
             otd AS ({xray_corp._scorecard_cte("otd")}),
             prod AS (
                SELECT br4.id, br4.company_id, br4.total_charge, br4.margin_amt,
                       br4.origin_actual_departure::date AS dep_date,
                       COALESCE(otp.scorecard_count_otp, 0) AS otp_cnt,
                       COALESCE(otd.scorecard_count_otd, 0) AS otd_cnt
                FROM public.mcleod_gld_budget_report_v4 br4
                LEFT JOIN otp ON TRIM(br4.id)=otp.id_key AND TRIM(br4.company_id)=otp.company_id_key
                LEFT JOIN otd ON TRIM(br4.id)=otd.id_key AND TRIM(br4.company_id)=otd.company_id_key
                WHERE {where}
                  AND br4.origin_actual_departure::date >= ${p_lo}
                  AND br4.origin_actual_departure::date <  ${p_hi}
             )
        SELECT {", ".join(select_parts)}
        FROM prod
    """
    row = await pool.fetchrow(sql, *params)

    loads = int(row["loads"] or 0)
    otp_sum = int(row["otp_sum"] or 0)
    otd_sum = int(row["otd_sum"] or 0)
    pickup_pct = (1 - otp_sum / loads) * 100 if loads else 0.0
    delivery_pct = (1 - otd_sum / loads) * 100 if loads else 0.0

    # Calendar-month cumulative KPI figures.
    m_loads = int(row["m_loads"] or 0)
    m_rev = float(row["m_rev"] or 0)
    m_prof = float(row["m_prof"] or 0)
    m_otp = int(row["m_otp"] or 0)
    m_otd = int(row["m_otd"] or 0)
    m_pickup_pct = (1 - m_otp / m_loads) * 100 if m_loads else 0.0
    m_delivery_pct = (1 - m_otd / m_loads) * 100 if m_loads else 0.0

    weeks = []
    for i, (label, _bs, _be) in enumerate(buckets, start=1):
        rev = float(row[f"w{i}_rev"] or 0)
        prof = float(row[f"w{i}_prof"] or 0)
        wl = int(row[f"w{i}_loads"] or 0)
        # Per-week service %, same load-weighted basis as the period figure
        # (1 - exceptions/loads). Display only — payout uses the period average.
        w_otp = int(row[f"w{i}_otp"] or 0)
        w_otd = int(row[f"w{i}_otd"] or 0)
        w_pickup = (1 - w_otp / wl) * 100 if wl else 0.0
        w_delivery = (1 - w_otd / wl) * 100 if wl else 0.0
        weeks.append(
            {
                "label": label,
                "loads": wl,
                "revenue": rev,
                "grossProfit": prof,
                "marginPct": (prof / rev) if rev else 0.0,  # decimal; engine normalizes
                "serviceAveragePct": (w_pickup + w_delivery) / 2,  # percentage, display only
            }
        )

    return {
        "pickupServicePct": pickup_pct,
        "deliveryServicePct": delivery_pct,
        "weeks": weeks,
        # Calendar-month cumulative (display KPIs only — not the payout math).
        "monthlyLoads": m_loads,
        "monthlyRevenue": m_rev,
        "monthlyProfit": m_prof,
        "monthlyMarginPct": (m_prof / m_rev) if m_rev else 0.0,  # decimal
        "monthlyServicePct": (m_pickup_pct + m_delivery_pct) / 2,  # percentage
    }


async def _suggested_dof_fx(financial_pool, on_or_before: date) -> Optional[float]:
    """Best-effort DOF/Banxico-FIX USD->MXN rate from the optional financial pool.

    HR-pinned FX is authoritative (Q3); this only prefills the suggestion. Any
    schema/connection issue silently yields None so the report still renders.
    Takes the pool directly so it works outside a request (history finalize job).
    """
    if financial_pool is None:
        return None
    try:
        val = await financial_pool.fetchval(
            """
            SELECT COALESCE(inverse_rate, 1.0 / NULLIF(rate, 0))
            FROM exchange_rates
            WHERE currency_from = 'MXN' AND currency_to = 'USD' AND rate_date <= $1
            ORDER BY rate_date DESC
            LIMIT 1
            """,
            on_or_before,
        )
        return float(val) if val else None
    except Exception as exc:  # noqa: BLE001 — suggestion is best-effort
        logger.warning("DOF FX suggestion unavailable: %s", exc)
        return None


# ---------------------------------------------------------------------------
# Roster / settings reads
# ---------------------------------------------------------------------------


async def _load_roster(pool) -> dict[str, list[dict]]:
    rows = await pool.fetch(
        """
        SELECT id, team_id, employee_name, role, salary_mxn, sort_order
        FROM bonus_roster
        ORDER BY team_id, sort_order, employee_name
        """
    )
    grouped: dict[str, list[dict]] = {t: [] for t in BONUS_TEAMS}
    for r in rows:
        grouped.setdefault(r["team_id"], []).append(
            {
                "id": str(r["id"]),
                "name": r["employee_name"],
                "role": r["role"],
                "salaryMxn": float(r["salary_mxn"] or 0),
            }
        )
    return grouped


async def _load_afterhours(pool) -> list[dict]:
    rows = await pool.fetch(
        """
        SELECT id, shift_group, employee_name, salary_mxn, receives_bonus, sort_order
        FROM bonus_afterhours
        ORDER BY sort_order, employee_name
        """
    )
    return [
        {
            "id": str(r["id"]),
            "group": r["shift_group"],
            "name": r["employee_name"],
            "salaryMxn": float(r["salary_mxn"] or 0),
            "receivesBonus": bool(r["receives_bonus"]),
        }
        for r in rows
    ]


async def _load_settings(pool, period_key: str) -> dict:
    row = await pool.fetchrow(
        "SELECT team_fx, night_fx, updated_by, updated_at FROM bonus_settings WHERE period_key = $1",
        period_key,
    )
    if row is None:
        return {
            "teamFx": DEFAULT_TEAM_FX_RATE,
            "nightFx": DEFAULT_NIGHT_FX_RATE,
            "pinned": False,
            "updatedBy": None,
        }
    return {
        "teamFx": float(row["team_fx"]),
        "nightFx": float(row["night_fx"]),
        "pinned": True,
        "updatedBy": row["updated_by"],
        "updatedAt": row["updated_at"].isoformat() if row["updated_at"] else None,
    }


async def _load_lock(pool, period_key: str) -> dict:
    row = await pool.fetchrow(
        "SELECT status, approved_by, approved_at FROM bonus_period_lock WHERE period_key = $1",
        period_key,
    )
    if row is None:
        return {"status": "open", "approvedBy": None, "approvedAt": None}
    return {
        "status": row["status"],
        "approvedBy": row["approved_by"],
        "approvedAt": row["approved_at"].isoformat() if row["approved_at"] else None,
    }


# ---------------------------------------------------------------------------
# Endpoints — reads
# ---------------------------------------------------------------------------


@router.get("/filters")
async def filters(
    request: Request,
    _user: dict = Depends(require_report_access(REPORT_KEY)),
):
    """Selectable periods + team list + current period."""
    current = _current_period_key()
    periods = []
    for key in _recent_period_keys(12):
        y, m = (int(x) for x in key.split("-"))
        periods.append({"key": key, "label": f"{month_name[m]} {y}"})
    return {
        "success": True,
        "data": {
            "periods": periods,
            "currentPeriod": current,
            "teams": [{"id": t, "name": DEFAULT_TEAM_NAMES[t]} for t in BONUS_TEAMS],
        },
    }


async def build_bonus_report_data(gold, primary, financial, period: Optional[str]) -> dict:
    """Assemble the full calculated bonus report for one period from live datalake.

    Request-free (takes pools directly) so it is reused by both the ``/report``
    endpoint and the History finalize job (services/bonus_history.py).
    """
    period_key, label, start, end, buckets = _period_bounds(period)
    y, m = _parse_period(period)
    month_start = date(y, m, 1)
    month_end = date(y + 1, 1, 1) if m == 12 else date(y, m + 1, 1)

    roster, afterhours, settings, lock, suggested_fx = await asyncio.gather(
        _load_roster(primary),
        _load_afterhours(primary),
        _load_settings(primary, period_key),
        _load_lock(primary, period_key),
        _suggested_dof_fx(financial, start),
    )

    team_fx = settings["teamFx"]
    night_fx = settings["nightFx"]

    metrics = await asyncio.gather(
        *[
            _team_metrics(gold, int(t.split("-")[1]), start, end, buckets, month_start, month_end)
            for t in BONUS_TEAMS
        ]
    )

    teams_payload = []
    for team_id, mtr in zip(BONUS_TEAMS, metrics):
        teams_payload.append(
            {
                "id": team_id,
                "name": DEFAULT_TEAM_NAMES[team_id],
                "pickupServicePct": mtr["pickupServicePct"],
                "deliveryServicePct": mtr["deliveryServicePct"],
                # R8 (Bruno 2026-06-03): the calendar-month On time P&D — the same
                # number the team header SERVICE KPI shows — is now the engine's
                # ONE service basis (weekly display, T&T bracket, wildcard gate).
                # The period (weeks-union) pickup/delivery stay as fallback only.
                "monthlyServicePct": mtr["monthlyServicePct"],
                # R9 (Bruno 2026-06-08): the calendar-month profit (header PROFIT
                # KPI) is now the basis for the 130/150/170 brackets — the engine
                # keys the ladder off this, not the weekly-bucket sum (which misses
                # the 1st-3rd → silently underpaid the 170 bracket).
                "monthlyProfit": mtr["monthlyProfit"],
                "fxRate": team_fx,
                "weeks": mtr["weeks"],
                "employees": roster.get(team_id, []),
            }
        )

    night_employees = [
        {"group": e["group"], "name": e["name"], "salaryMxn": e["salaryMxn"], "receivesBonus": e["receivesBonus"]}
        for e in afterhours
    ]

    report_data = build_bonus_report(
        month=label,
        source="McLeod TMS — live datalake (aivn_datalake_gold)",
        mode="mcleod_tms",
        teams=teams_payload,
        night_shift_employees=night_employees,
        night_fx_rate=night_fx,
        last_sync_label=f"Live datalake · {cst_today().isoformat()}",
        status_label="Connected",
    )

    # Attach calendar-month cumulative KPIs (display only — payout math stays
    # weekly-bucket based). Bruno 2026-05-28: KPIs = 1st→last day, not Σ weeks.
    monthly_total_profit = 0.0
    for team_out, mtr in zip(report_data["teams"], metrics):
        team_out["monthlyLoads"] = mtr["monthlyLoads"]
        team_out["monthlyRevenue"] = mtr["monthlyRevenue"]
        team_out["monthlyProfit"] = mtr["monthlyProfit"]
        team_out["monthlyMarginPct"] = mtr["monthlyMarginPct"]
        team_out["monthlyServicePct"] = mtr["monthlyServicePct"]
        monthly_total_profit += mtr["monthlyProfit"]
    report_data["monthlyTotalProfit"] = monthly_total_profit

    report_data["period"] = {
        "key": period_key,
        "label": label,
        "start": start.isoformat(),
        "end": end.isoformat(),
        "weekLabels": [b[0] for b in buckets],
    }
    report_data["fx"] = {
        "teamFx": team_fx,
        "nightFx": night_fx,
        "pinned": settings["pinned"],
        "suggestedDofFx": suggested_fx,
        "updatedBy": settings.get("updatedBy"),
    }
    report_data["lock"] = lock
    return report_data


@router.get("/report")
async def report(
    request: Request,
    period: Optional[str] = Query(None, description="YYYY-MM (the month the 6th-period opens in)"),
    _user: dict = Depends(require_report_access(REPORT_KEY)),
):
    """Full calculated bonus report for one period, fed from live datalake."""
    report_data = await build_bonus_report_data(
        get_datalake_gold_pool(request),
        get_pool(request),
        getattr(request.app.state, "financial_pool", None),
        period,
    )
    return {"success": True, "data": report_data}


@router.get("/history")
async def history(
    request: Request,
    _user: dict = Depends(require_report_access(REPORT_KEY)),
):
    """Monthly History (Bruno 2026-05-28): immutable snapshots + the still-open
    current month computed live (flagged ``open``)."""
    # Lazy import — bonus_history imports this module (avoids a circular import).
    from app.services.bonus_history import get_history

    primary = get_pool(request)
    snapshots = await get_history(primary)
    for s in snapshots:
        y, m = (int(x) for x in s["periodKey"].split("-"))
        s["label"] = f"{month_name[m]} {y}"

    current = None
    current_key = _current_period_key()
    try:
        rep = await build_bonus_report_data(
            get_datalake_gold_pool(request),
            primary,
            getattr(request.app.state, "financial_pool", None),
            current_key,
        )
        rows = []
        for t in rep["teams"]:
            profit = float(t.get("monthlyProfit", 0) or 0)
            bonus = float(t.get("teamBonusUsd", 0) or 0)
            rows.append(
                {
                    "teamId": t["id"],
                    "teamName": t["name"],
                    "profitUsd": profit,
                    "totalBonusUsd": bonus,
                    "pctBonus": (bonus / profit * 100) if profit else None,
                }
            )
        current = {
            "periodKey": current_key,
            "label": rep["period"]["label"],
            "open": True,
            "rows": rows,
        }
    except Exception as exc:  # noqa: BLE001 — open-month preview is best-effort
        logger.warning("History current-period compute failed: %s", exc)

    return {"success": True, "data": {"snapshots": snapshots, "current": current}}


@router.get("/roster")
async def get_roster(
    request: Request,
    period: Optional[str] = Query(None),
    _user: dict = Depends(require_report_access(REPORT_KEY)),
):
    """Editable roster + afterhours + FX settings + lock for HR management."""
    primary = get_pool(request)
    period_key, label, start, _end, _buckets = _period_bounds(period)
    roster, afterhours, settings, lock, suggested_fx = await asyncio.gather(
        _load_roster(primary),
        _load_afterhours(primary),
        _load_settings(primary, period_key),
        _load_lock(primary, period_key),
        _suggested_dof_fx(getattr(request.app.state, "financial_pool", None), start),
    )
    return {
        "success": True,
        "data": {
            "teams": [{"id": t, "name": DEFAULT_TEAM_NAMES[t], "employees": roster.get(t, [])} for t in BONUS_TEAMS],
            "afterhours": afterhours,
            "settings": {**settings, "suggestedDofFx": suggested_fx},
            "lock": lock,
            "period": {"key": period_key, "label": label},
            "roles": list(VALID_ROLES),
        },
    }


# ---------------------------------------------------------------------------
# Endpoints — HR writes (gated by report access; shared HR data, not per-user)
# ---------------------------------------------------------------------------


class RosterRow(BaseModel):
    team_id: str
    name: str = Field(min_length=1, max_length=120)
    role: str
    salary_mxn: float = Field(ge=0, le=10_000_000)

    def validate_domain(self) -> None:
        if self.team_id not in BONUS_TEAMS:
            raise HTTPException(status_code=422, detail=f"team_id must be one of {BONUS_TEAMS}")
        if self.role not in VALID_ROLES:
            raise HTTPException(status_code=422, detail=f"role must be one of {VALID_ROLES}")


@router.post("/roster")
async def create_roster_row(
    request: Request,
    body: RosterRow,
    user: dict = Depends(require_report_access(REPORT_KEY)),
):
    body.validate_domain()
    primary = get_pool(request)
    next_sort = await primary.fetchval(
        "SELECT COALESCE(MAX(sort_order), -1) + 1 FROM bonus_roster WHERE team_id = $1", body.team_id
    )
    row = await primary.fetchrow(
        """
        INSERT INTO bonus_roster (team_id, employee_name, role, salary_mxn, sort_order)
        VALUES ($1, $2, $3, $4, $5)
        RETURNING id
        """,
        body.team_id,
        body.name.strip(),
        body.role,
        body.salary_mxn,
        next_sort,
    )
    return {"success": True, "data": {"id": str(row["id"])}}


@router.put("/roster/{row_id}")
async def update_roster_row(
    request: Request,
    row_id: str,
    body: RosterRow,
    user: dict = Depends(require_report_access(REPORT_KEY)),
):
    body.validate_domain()
    primary = get_pool(request)
    result = await primary.execute(
        """
        UPDATE bonus_roster
        SET team_id = $2, employee_name = $3, role = $4, salary_mxn = $5
        WHERE id = $1
        """,
        row_id,
        body.team_id,
        body.name.strip(),
        body.role,
        body.salary_mxn,
    )
    if result.endswith("0"):
        raise HTTPException(status_code=404, detail="Roster row not found")
    return {"success": True}


@router.delete("/roster/{row_id}")
async def delete_roster_row(
    request: Request,
    row_id: str,
    user: dict = Depends(require_report_access(REPORT_KEY)),
):
    primary = get_pool(request)
    result = await primary.execute("DELETE FROM bonus_roster WHERE id = $1", row_id)
    if result.endswith("0"):
        raise HTTPException(status_code=404, detail="Roster row not found")
    return {"success": True}


class AfterhoursRow(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    salary_mxn: float = Field(ge=0, le=10_000_000)
    receives_bonus: bool = True


@router.put("/afterhours/{row_id}")
async def update_afterhours_row(
    request: Request,
    row_id: str,
    body: AfterhoursRow,
    user: dict = Depends(require_report_access(REPORT_KEY)),
):
    primary = get_pool(request)
    result = await primary.execute(
        """
        UPDATE bonus_afterhours
        SET employee_name = $2, salary_mxn = $3, receives_bonus = $4
        WHERE id = $1
        """,
        row_id,
        body.name.strip(),
        body.salary_mxn,
        body.receives_bonus,
    )
    if result.endswith("0"):
        raise HTTPException(status_code=404, detail="Afterhours row not found")
    return {"success": True}


class FxSettings(BaseModel):
    period_key: str
    team_fx: float = Field(gt=0, le=1000)
    night_fx: float = Field(gt=0, le=1000)


@router.put("/settings")
async def put_settings(
    request: Request,
    body: FxSettings,
    user: dict = Depends(require_report_access(REPORT_KEY)),
):
    """HR pins the board-approved team FX + night FX for a period (Q3/Q5)."""
    _parse_period(body.period_key)  # validates format
    primary = get_pool(request)
    await primary.execute(
        """
        INSERT INTO bonus_settings (period_key, team_fx, night_fx, updated_by, updated_at)
        VALUES ($1, $2, $3, $4, NOW())
        ON CONFLICT (period_key) DO UPDATE
          SET team_fx = EXCLUDED.team_fx,
              night_fx = EXCLUDED.night_fx,
              updated_by = EXCLUDED.updated_by,
              updated_at = NOW()
        """,
        body.period_key,
        body.team_fx,
        body.night_fx,
        user.get("email") or user.get("name") or user.get("sub"),
    )
    return {"success": True}


class LockBody(BaseModel):
    period_key: str


@router.post("/lock")
async def lock_period(
    request: Request,
    body: LockBody,
    user: dict = Depends(require_report_access(REPORT_KEY)),
):
    """Lock a month as HR/Finance-approved (PDF best-practice)."""
    _parse_period(body.period_key)
    primary = get_pool(request)
    await primary.execute(
        """
        INSERT INTO bonus_period_lock (period_key, status, approved_by, approved_at)
        VALUES ($1, 'approved', $2, NOW())
        ON CONFLICT (period_key) DO UPDATE
          SET status = 'approved', approved_by = EXCLUDED.approved_by, approved_at = NOW()
        """,
        body.period_key,
        user.get("email") or user.get("name") or user.get("sub"),
    )
    return {"success": True}


@router.delete("/lock/{period_key}")
async def unlock_period(
    request: Request,
    period_key: str,
    user: dict = Depends(require_report_access(REPORT_KEY)),
):
    _parse_period(period_key)
    primary = get_pool(request)
    await primary.execute("DELETE FROM bonus_period_lock WHERE period_key = $1", period_key)
    return {"success": True}
