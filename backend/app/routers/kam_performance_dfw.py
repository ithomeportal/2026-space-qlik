"""Code-made report: KAM Performance - DFW.

Per-KAM scratchpad layered on top of two existing reports:

* Tab 1 SCORECARDS    — local CRUD (kam_scorecards table). Bruno's spec is
                        metadata-only (no file blob): customer, scorecard
                        date, frequency, uploaded-by/timestamp.
* Tab 2 SERVICE       — frontend calls the existing ops-customer-score
                        endpoints with ``division=DFW``. KPI = current-week
                        OTP/OTD; sub-tabs OTP and OTD list service failures
                        (counted-first, not-counted-after) from
                        ``mcleod_gld_scorecard``.
* Tab 3 TOP 10 LANES  — frontend calls existing xray-dfw-mng endpoints
                        (``/kpis`` and ``/by-lane?limit=10``) with
                        ``range=custom`` Mon..today for this-week KPIs.
                        The free-text "What I will do to get more of these
                        loads" textbox lives in kam_top_lanes_notes.
* Tab 4 CUSTOMER DEV  — local CRUD (kam_customer_dev). Editable: contact
                        name, last-day-spoke (date), opportunity areas,
                        action plan.
* Tab 5 TEAM DEV      — local CRUD (kam_team_dev). Editable: team member,
                        last-day-1-on-1 (free text), specific area to
                        develop, action plan.

Per-user scope: every row carries ``user_id = user["sub"]``. List endpoints
filter on it; create/update/delete enforce ownership server-side, so even
if a row id leaks, another user can't read or mutate it.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field

from app.clock import cst_today
from app.datalake import pad_variants as _pad_variants
from app.routers.deps import (
    get_datalake_gold_pool,
    get_pool,
    require_report_access,
)


router = APIRouter(
    tags=["kam-performance-dfw"],
    prefix="/custom/kam-performance-dfw",
)

# DFW scope for the read-only datalake tabs (Worst 10 Lanes, Carrier Sales).
# Same sargable padded-variant pattern as losses-lanes / xray-dfw.
YEAR_START = date(2026, 1, 1)
YEAR_END = date(2026, 12, 31)
DFW_TEAMS = ("TEAM-DFW",)
DFW_SUB_TEAMS = ("TM1", "TM2", "TM3", "TM4")
COMPANIES = ("TMS", "TMS3")
OPEN_STATUSES = ("D", "P")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _iso(d) -> Optional[str]:
    if d is None:
        return None
    if isinstance(d, (datetime, date)):
        return d.isoformat()
    return str(d)


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
    """YTD / MTD / WTD (Mon-anchored) / Custom — the date filter Bruno R2
    added to the Service, Lanes and Carrier-Sales tabs. Default = MTD."""
    today = cst_today()
    today_clamped = max(YEAR_START, min(YEAR_END, today))
    if rng == "ytd":
        return YEAR_START, today_clamped
    if rng == "wtd":
        monday = today_clamped - timedelta(days=today_clamped.weekday())
        return max(YEAR_START, monday), today_clamped
    if rng == "custom":
        s = _clamp(start_date, YEAR_START)
        e = _clamp(end_date, YEAR_END)
        if e < s:
            s, e = e, s
        return s, e
    # default: month-to-date
    return today_clamped.replace(day=1), today_clamped


def _dfw_scope_where(alias: str, params: list) -> str:
    """DFW-only v4 scope (team_id='TEAM-DFW'), mirroring losses-lanes minus the
    multi-team selector. Excludes UNILINK + OILTEX like every other v4 report."""
    params.append(_pad_variants(list(DFW_TEAMS), width=8))
    p_teams = len(params)
    params.append(_pad_variants(list(COMPANIES), width=4))
    p_companies = len(params)
    params.append(_pad_variants(list(OPEN_STATUSES), width=1))
    p_status = len(params)
    return " AND ".join(
        [
            f"{alias}.team_id    = ANY(${p_teams})",
            f"{alias}.company_id = ANY(${p_companies})",
            f"{alias}.status     = ANY(${p_status})",
            f"UPPER(COALESCE({alias}.customer_name,'')) NOT LIKE '%UNILINK%'",
            f"UPPER(COALESCE({alias}.customer_name,'')) NOT LIKE '%OILTEX%'",
        ]
    )


def _parse_sub_teams(raw: Optional[str]) -> list[str]:
    """CSV of DFW sub-teams (Bruno KAM update: Team filter on Service / Worst
    Lanes / Carrier Sales). Only TM1..TM4 are honoured — anything else is
    dropped so a hand-crafted URL can't widen the scope. Matches ``v4.team``
    with TRIM equality (same sargable pattern as xray-dfw)."""
    if not raw:
        return []
    wanted = {t.strip().upper() for t in raw.split(",") if t.strip()}
    return [t for t in DFW_SUB_TEAMS if t in wanted]


# ---------------------------------------------------------------------------
# Tab 1 — SCORECARDS (metadata-only log)
# ---------------------------------------------------------------------------


class ScorecardCreate(BaseModel):
    customer: str = Field(..., min_length=1, max_length=200)
    scorecard_date: date
    scorecard_frequency: str = Field(..., min_length=1, max_length=40)


@router.get("/scorecards")
async def list_scorecards(
    request: Request,
    user: dict = Depends(require_report_access("kam-performance-dfw")),
):
    pool = get_pool(request)
    rows = await pool.fetch(
        """
        SELECT id, customer, scorecard_date, scorecard_frequency,
               uploaded_by_email, uploaded_by_name, created_at
        FROM kam_scorecards
        WHERE user_id = $1
        ORDER BY scorecard_date DESC, created_at DESC
        """,
        user["sub"],
    )
    return {
        "success": True,
        "data": [
            {
                "id": str(r["id"]),
                "customer": r["customer"],
                "scorecard_date": _iso(r["scorecard_date"]),
                "scorecard_frequency": r["scorecard_frequency"],
                "uploaded_by_email": r["uploaded_by_email"],
                "uploaded_by_name": r["uploaded_by_name"],
                "created_at": _iso(r["created_at"]),
            }
            for r in rows
        ],
    }


@router.post("/scorecards")
async def create_scorecard(
    body: ScorecardCreate,
    request: Request,
    user: dict = Depends(require_report_access("kam-performance-dfw")),
):
    pool = get_pool(request)
    row = await pool.fetchrow(
        """
        INSERT INTO kam_scorecards (
          user_id, customer, scorecard_date, scorecard_frequency,
          uploaded_by_email, uploaded_by_name
        )
        VALUES ($1, $2, $3, $4, $5, $6)
        RETURNING id, customer, scorecard_date, scorecard_frequency,
                  uploaded_by_email, uploaded_by_name, created_at
        """,
        user["sub"],
        body.customer.strip(),
        body.scorecard_date,
        body.scorecard_frequency.strip(),
        user.get("email"),
        user.get("name"),
    )
    return {
        "success": True,
        "data": {
            "id": str(row["id"]),
            "customer": row["customer"],
            "scorecard_date": _iso(row["scorecard_date"]),
            "scorecard_frequency": row["scorecard_frequency"],
            "uploaded_by_email": row["uploaded_by_email"],
            "uploaded_by_name": row["uploaded_by_name"],
            "created_at": _iso(row["created_at"]),
        },
    }


@router.delete("/scorecards/{row_id}")
async def delete_scorecard(
    row_id: UUID,
    request: Request,
    user: dict = Depends(require_report_access("kam-performance-dfw")),
):
    pool = get_pool(request)
    res = await pool.execute(
        "DELETE FROM kam_scorecards WHERE id = $1 AND user_id = $2",
        row_id,
        user["sub"],
    )
    # asyncpg returns "DELETE n" — bail if no rows matched (wrong user or missing).
    if res.endswith(" 0"):
        raise HTTPException(status_code=404, detail="Scorecard not found")
    return {"success": True, "data": {"deleted": True}}


# ---------------------------------------------------------------------------
# Tab 3 — Top-Lanes free-text note (one row per user)
# ---------------------------------------------------------------------------


class TopLanesNoteUpsert(BaseModel):
    notes: str = Field(default="", max_length=5000)


@router.get("/top-lanes-note")
async def get_top_lanes_note(
    request: Request,
    user: dict = Depends(require_report_access("kam-performance-dfw")),
):
    pool = get_pool(request)
    row = await pool.fetchrow(
        "SELECT notes, updated_at FROM kam_top_lanes_notes WHERE user_id = $1",
        user["sub"],
    )
    return {
        "success": True,
        "data": {
            "notes": row["notes"] if row else "",
            "updated_at": _iso(row["updated_at"]) if row else None,
        },
    }


@router.put("/top-lanes-note")
async def upsert_top_lanes_note(
    body: TopLanesNoteUpsert,
    request: Request,
    user: dict = Depends(require_report_access("kam-performance-dfw")),
):
    pool = get_pool(request)
    row = await pool.fetchrow(
        """
        INSERT INTO kam_top_lanes_notes (user_id, notes, updated_at)
        VALUES ($1, $2, NOW())
        ON CONFLICT (user_id) DO UPDATE
          SET notes = EXCLUDED.notes,
              updated_at = NOW()
        RETURNING notes, updated_at
        """,
        user["sub"],
        body.notes,
    )
    return {
        "success": True,
        "data": {
            "notes": row["notes"],
            "updated_at": _iso(row["updated_at"]),
        },
    }


# ---------------------------------------------------------------------------
# Tab 4 — CUSTOMER DEVELOPMENT
# ---------------------------------------------------------------------------


class CustomerDevUpsert(BaseModel):
    contact_name: str = Field(..., min_length=1, max_length=200)
    last_day_spoke: Optional[date] = None
    opportunity_areas: str = Field(default="", max_length=5000)
    action_plan: str = Field(default="", max_length=5000)


class CustomerDevPatch(BaseModel):
    contact_name: Optional[str] = Field(default=None, max_length=200)
    last_day_spoke: Optional[date] = None
    last_day_spoke_set: bool = False  # explicit null support
    opportunity_areas: Optional[str] = Field(default=None, max_length=5000)
    action_plan: Optional[str] = Field(default=None, max_length=5000)


@router.get("/customer-dev")
async def list_customer_dev(
    request: Request,
    user: dict = Depends(require_report_access("kam-performance-dfw")),
):
    pool = get_pool(request)
    rows = await pool.fetch(
        """
        SELECT id, contact_name, last_day_spoke, opportunity_areas,
               action_plan, created_at, updated_at
        FROM kam_customer_dev
        WHERE user_id = $1
        ORDER BY last_day_spoke DESC NULLS LAST, updated_at DESC
        """,
        user["sub"],
    )
    return {
        "success": True,
        "data": [
            {
                "id": str(r["id"]),
                "contact_name": r["contact_name"],
                "last_day_spoke": _iso(r["last_day_spoke"]),
                "opportunity_areas": r["opportunity_areas"] or "",
                "action_plan": r["action_plan"] or "",
                "created_at": _iso(r["created_at"]),
                "updated_at": _iso(r["updated_at"]),
            }
            for r in rows
        ],
    }


@router.post("/customer-dev")
async def create_customer_dev(
    body: CustomerDevUpsert,
    request: Request,
    user: dict = Depends(require_report_access("kam-performance-dfw")),
):
    pool = get_pool(request)
    row = await pool.fetchrow(
        """
        INSERT INTO kam_customer_dev (
          user_id, contact_name, last_day_spoke, opportunity_areas, action_plan
        )
        VALUES ($1, $2, $3, $4, $5)
        RETURNING id, contact_name, last_day_spoke, opportunity_areas,
                  action_plan, created_at, updated_at
        """,
        user["sub"],
        body.contact_name.strip(),
        body.last_day_spoke,
        body.opportunity_areas,
        body.action_plan,
    )
    return {
        "success": True,
        "data": {
            "id": str(row["id"]),
            "contact_name": row["contact_name"],
            "last_day_spoke": _iso(row["last_day_spoke"]),
            "opportunity_areas": row["opportunity_areas"] or "",
            "action_plan": row["action_plan"] or "",
            "created_at": _iso(row["created_at"]),
            "updated_at": _iso(row["updated_at"]),
        },
    }


@router.patch("/customer-dev/{row_id}")
async def update_customer_dev(
    row_id: UUID,
    body: CustomerDevPatch,
    request: Request,
    user: dict = Depends(require_report_access("kam-performance-dfw")),
):
    pool = get_pool(request)
    existing = await pool.fetchrow(
        "SELECT 1 FROM kam_customer_dev WHERE id = $1 AND user_id = $2",
        row_id,
        user["sub"],
    )
    if not existing:
        raise HTTPException(status_code=404, detail="Row not found")

    set_parts = []
    params: list = []
    if body.contact_name is not None:
        params.append(body.contact_name.strip())
        set_parts.append(f"contact_name = ${len(params)}")
    if body.last_day_spoke_set:
        params.append(body.last_day_spoke)
        set_parts.append(f"last_day_spoke = ${len(params)}")
    if body.opportunity_areas is not None:
        params.append(body.opportunity_areas)
        set_parts.append(f"opportunity_areas = ${len(params)}")
    if body.action_plan is not None:
        params.append(body.action_plan)
        set_parts.append(f"action_plan = ${len(params)}")

    if not set_parts:
        return {"success": True, "data": {"updated": False}}

    set_parts.append("updated_at = NOW()")
    params.extend([row_id, user["sub"]])
    p_id = len(params) - 1
    p_user = len(params)

    row = await pool.fetchrow(
        f"""
        UPDATE kam_customer_dev
        SET {", ".join(set_parts)}
        WHERE id = ${p_id} AND user_id = ${p_user}
        RETURNING id, contact_name, last_day_spoke, opportunity_areas,
                  action_plan, created_at, updated_at
        """,
        *params,
    )
    return {
        "success": True,
        "data": {
            "id": str(row["id"]),
            "contact_name": row["contact_name"],
            "last_day_spoke": _iso(row["last_day_spoke"]),
            "opportunity_areas": row["opportunity_areas"] or "",
            "action_plan": row["action_plan"] or "",
            "created_at": _iso(row["created_at"]),
            "updated_at": _iso(row["updated_at"]),
        },
    }


@router.delete("/customer-dev/{row_id}")
async def delete_customer_dev(
    row_id: UUID,
    request: Request,
    user: dict = Depends(require_report_access("kam-performance-dfw")),
):
    pool = get_pool(request)
    res = await pool.execute(
        "DELETE FROM kam_customer_dev WHERE id = $1 AND user_id = $2",
        row_id,
        user["sub"],
    )
    if res.endswith(" 0"):
        raise HTTPException(status_code=404, detail="Row not found")
    return {"success": True, "data": {"deleted": True}}


# ---------------------------------------------------------------------------
# Tab 5 — TEAM DEVELOPMENT
# ---------------------------------------------------------------------------


class TeamDevUpsert(BaseModel):
    team_member: str = Field(..., min_length=1, max_length=200)
    last_one_on_one: str = Field(default="", max_length=200)
    specific_area: str = Field(default="", max_length=5000)
    action_plan: str = Field(default="", max_length=5000)


class TeamDevPatch(BaseModel):
    team_member: Optional[str] = Field(default=None, max_length=200)
    last_one_on_one: Optional[str] = Field(default=None, max_length=200)
    specific_area: Optional[str] = Field(default=None, max_length=5000)
    action_plan: Optional[str] = Field(default=None, max_length=5000)


@router.get("/team-dev")
async def list_team_dev(
    request: Request,
    user: dict = Depends(require_report_access("kam-performance-dfw")),
):
    pool = get_pool(request)
    rows = await pool.fetch(
        """
        SELECT id, team_member, last_one_on_one, specific_area,
               action_plan, created_at, updated_at
        FROM kam_team_dev
        WHERE user_id = $1
        ORDER BY updated_at DESC
        """,
        user["sub"],
    )
    return {
        "success": True,
        "data": [
            {
                "id": str(r["id"]),
                "team_member": r["team_member"],
                "last_one_on_one": r["last_one_on_one"] or "",
                "specific_area": r["specific_area"] or "",
                "action_plan": r["action_plan"] or "",
                "created_at": _iso(r["created_at"]),
                "updated_at": _iso(r["updated_at"]),
            }
            for r in rows
        ],
    }


@router.post("/team-dev")
async def create_team_dev(
    body: TeamDevUpsert,
    request: Request,
    user: dict = Depends(require_report_access("kam-performance-dfw")),
):
    pool = get_pool(request)
    row = await pool.fetchrow(
        """
        INSERT INTO kam_team_dev (
          user_id, team_member, last_one_on_one, specific_area, action_plan
        )
        VALUES ($1, $2, $3, $4, $5)
        RETURNING id, team_member, last_one_on_one, specific_area,
                  action_plan, created_at, updated_at
        """,
        user["sub"],
        body.team_member.strip(),
        body.last_one_on_one,
        body.specific_area,
        body.action_plan,
    )
    return {
        "success": True,
        "data": {
            "id": str(row["id"]),
            "team_member": row["team_member"],
            "last_one_on_one": row["last_one_on_one"] or "",
            "specific_area": row["specific_area"] or "",
            "action_plan": row["action_plan"] or "",
            "created_at": _iso(row["created_at"]),
            "updated_at": _iso(row["updated_at"]),
        },
    }


@router.patch("/team-dev/{row_id}")
async def update_team_dev(
    row_id: UUID,
    body: TeamDevPatch,
    request: Request,
    user: dict = Depends(require_report_access("kam-performance-dfw")),
):
    pool = get_pool(request)
    existing = await pool.fetchrow(
        "SELECT 1 FROM kam_team_dev WHERE id = $1 AND user_id = $2",
        row_id,
        user["sub"],
    )
    if not existing:
        raise HTTPException(status_code=404, detail="Row not found")

    set_parts = []
    params: list = []
    if body.team_member is not None:
        params.append(body.team_member.strip())
        set_parts.append(f"team_member = ${len(params)}")
    if body.last_one_on_one is not None:
        params.append(body.last_one_on_one)
        set_parts.append(f"last_one_on_one = ${len(params)}")
    if body.specific_area is not None:
        params.append(body.specific_area)
        set_parts.append(f"specific_area = ${len(params)}")
    if body.action_plan is not None:
        params.append(body.action_plan)
        set_parts.append(f"action_plan = ${len(params)}")

    if not set_parts:
        return {"success": True, "data": {"updated": False}}

    set_parts.append("updated_at = NOW()")
    params.extend([row_id, user["sub"]])
    p_id = len(params) - 1
    p_user = len(params)

    row = await pool.fetchrow(
        f"""
        UPDATE kam_team_dev
        SET {", ".join(set_parts)}
        WHERE id = ${p_id} AND user_id = ${p_user}
        RETURNING id, team_member, last_one_on_one, specific_area,
                  action_plan, created_at, updated_at
        """,
        *params,
    )
    return {
        "success": True,
        "data": {
            "id": str(row["id"]),
            "team_member": row["team_member"],
            "last_one_on_one": row["last_one_on_one"] or "",
            "specific_area": row["specific_area"] or "",
            "action_plan": row["action_plan"] or "",
            "created_at": _iso(row["created_at"]),
            "updated_at": _iso(row["updated_at"]),
        },
    }


@router.delete("/team-dev/{row_id}")
async def delete_team_dev(
    row_id: UUID,
    request: Request,
    user: dict = Depends(require_report_access("kam-performance-dfw")),
):
    pool = get_pool(request)
    res = await pool.execute(
        "DELETE FROM kam_team_dev WHERE id = $1 AND user_id = $2",
        row_id,
        user["sub"],
    )
    if res.endswith(" 0"):
        raise HTTPException(status_code=404, detail="Row not found")
    return {"success": True, "data": {"deleted": True}}


# ---------------------------------------------------------------------------
# Tab 6 — WORST 10 LANES (Bruno R2)
#
# "Based on the Losses email" — the worst losing (customer, lane) pairs for
# DFW: neg-margin loads only (margin_amt < 0), same source/ranking as the
# daily Losses Lanes email. Metrics are computed over the neg-margin slice so
# the numbers tie out to the email. Expiration Date + Action Plan are
# per-user editable, keyed by (user_id, lane_key) so a KAM's notes persist
# even as the top-10 reshuffles week to week.
# ---------------------------------------------------------------------------


@router.get("/worst-lanes")
async def worst_lanes(
    request: Request,
    range: Optional[str] = Query("ytd"),
    start_date: Optional[date] = Query(None),
    end_date: Optional[date] = Query(None),
    limit: int = Query(10, ge=1, le=50),
    sub_teams: Optional[str] = Query(None),
    user: dict = Depends(require_report_access("kam-performance-dfw")),
):
    gold = get_datalake_gold_pool(request)
    s, e = _resolve_range(range, start_date, end_date)

    params: list = []
    where = _dfw_scope_where("b", params)
    sub_team_list = _parse_sub_teams(sub_teams)
    if sub_team_list:
        params.append(sub_team_list)
        where += f" AND TRIM(b.team) = ANY(${len(params)})"
    params.extend([s, e, limit])
    p_s, p_e, p_lim = len(params) - 2, len(params) - 1, len(params)

    lane_sql = (
        "NULLIF(TRIM(b.origin_city_name),'') || ', ' || "
        "NULLIF(TRIM(b.origin_state_id),'')  || ' - ' || "
        "NULLIF(TRIM(b.dest_city_name),'')   || ', ' || "
        "NULLIF(TRIM(b.dest_state_id),'')"
    )

    rows = await gold.fetch(
        f"""
        WITH base AS (
          SELECT
            TRIM(b.customer_name) AS customer,
            {lane_sql}            AS lane,
            b.total_charge,
            b.margin_amt
          FROM public.mcleod_gld_budget_report_v4 b
          WHERE {where}
            AND b.origin_actual_departure::date BETWEEN ${p_s} AND ${p_e}
            AND b.margin_amt < 0 AND b.total_charge <> 0
        )
        SELECT
          customer,
          lane,
          COUNT(*)                   AS loads,
          SUM(total_charge)::numeric AS revenue,
          SUM(margin_amt)::numeric   AS profit,
          CASE WHEN SUM(total_charge) <> 0
               THEN SUM(margin_amt)::numeric / SUM(total_charge)::numeric * 100
               ELSE NULL END         AS margin_pct
        FROM base
        WHERE customer IS NOT NULL AND lane IS NOT NULL
        GROUP BY customer, lane
        ORDER BY profit ASC
        LIMIT ${p_lim}
        """,
        *params,
    )

    # Pull this user's saved notes once and stitch them in by lane_key.
    notes = await get_pool(request).fetch(
        "SELECT lane_key, expiration_date, action_plan FROM kam_worst_lane_notes WHERE user_id = $1",
        user["sub"],
    )
    note_map = {
        n["lane_key"]: {
            "expiration_date": _iso(n["expiration_date"]),
            "action_plan": n["action_plan"] or "",
        }
        for n in notes
    }

    data = []
    for r in rows:
        lane_key = f"{r['customer']}::{r['lane']}"
        note = note_map.get(lane_key, {"expiration_date": None, "action_plan": ""})
        data.append(
            {
                "lane_key": lane_key,
                "customer": r["customer"],
                "lane": r["lane"],
                "loads": int(r["loads"] or 0),
                "revenue": float(r["revenue"] or 0),
                "profit": float(r["profit"] or 0),
                "margin_pct": float(r["margin_pct"]) if r["margin_pct"] is not None else None,
                "expiration_date": note["expiration_date"],
                "action_plan": note["action_plan"],
            }
        )
    return {
        "success": True,
        "data": data,
        "meta": {"window": {"start": s.isoformat(), "end": e.isoformat()}},
    }


class WorstLaneNoteUpsert(BaseModel):
    lane_key: str = Field(..., min_length=1, max_length=400)
    expiration_date: Optional[date] = None
    action_plan: str = Field(default="", max_length=5000)


@router.put("/worst-lane-notes")
async def upsert_worst_lane_note(
    body: WorstLaneNoteUpsert,
    request: Request,
    user: dict = Depends(require_report_access("kam-performance-dfw")),
):
    pool = get_pool(request)
    row = await pool.fetchrow(
        """
        INSERT INTO kam_worst_lane_notes (user_id, lane_key, expiration_date, action_plan, updated_at)
        VALUES ($1, $2, $3, $4, NOW())
        ON CONFLICT (user_id, lane_key) DO UPDATE
          SET expiration_date = EXCLUDED.expiration_date,
              action_plan     = EXCLUDED.action_plan,
              updated_at      = NOW()
        RETURNING lane_key, expiration_date, action_plan, updated_at
        """,
        user["sub"],
        body.lane_key,
        body.expiration_date,
        body.action_plan,
    )
    return {
        "success": True,
        "data": {
            "lane_key": row["lane_key"],
            "expiration_date": _iso(row["expiration_date"]),
            "action_plan": row["action_plan"] or "",
            "updated_at": _iso(row["updated_at"]),
        },
    }


# ---------------------------------------------------------------------------
# Tab 7 — CARRIER SALES (Bruno R2)
#
# Per-lane carrier intel for DFW: lane = origin_name - dest_name (from v4),
# the 3 most-recently-used distinct carriers, and avg(override_pay_amt) from
# the dispatchers table. dispatchers ⨝ v4 on (id, company_id) — the same join
# the carrier-risk report uses. Comments are per-user editable, keyed by
# (user_id, lane_key).
# ---------------------------------------------------------------------------


@router.get("/carrier-sales")
async def carrier_sales(
    request: Request,
    range: Optional[str] = Query("mtd"),
    start_date: Optional[date] = Query(None),
    end_date: Optional[date] = Query(None),
    limit: int = Query(100, ge=1, le=300),
    sub_teams: Optional[str] = Query(None),
    user: dict = Depends(require_report_access("kam-performance-dfw")),
):
    gold = get_datalake_gold_pool(request)
    s, e = _resolve_range(range, start_date, end_date)

    params: list = []
    # Scope predicates live on the dispatchers alias ``d``.
    params.append(_pad_variants(list(DFW_TEAMS), width=8))
    p_teams = len(params)
    # Optional DFW sub-team pill (Bruno KAM update) — filter on v4 ``b.team``.
    sub_team_list = _parse_sub_teams(sub_teams)
    sub_clause = ""
    if sub_team_list:
        params.append(sub_team_list)
        sub_clause = f"\n            AND TRIM(b.team) = ANY(${len(params)})"
    params.extend([s, e, limit])
    p_s, p_e, p_lim = len(params) - 2, len(params) - 1, len(params)

    rows = await gold.fetch(
        f"""
        WITH base AS (
          SELECT
            (TRIM(b.origin_name) || ' - ' || TRIM(b.dest_name)) AS lane,
            d.carrier_name,
            d.override_pay_amt,
            d.origin_actual_departure AS dep
          FROM public.mcleod_gld_dispatchers d
          JOIN public.mcleod_gld_budget_report_v4 b
            ON d.id = b.id AND d.company_id = b.company_id
          WHERE d.team_id = ANY(${p_teams})
            AND d.origin_actual_departure::date BETWEEN ${p_s} AND ${p_e}
            AND d.carrier_name <> 'DUMMY TRANSPORTATION'
            AND UPPER(COALESCE(d.customer_name,'')) NOT LIKE '%UNILINK%'
            AND UPPER(COALESCE(d.customer_name,'')) NOT LIKE '%OILTEX%'
            AND TRIM(COALESCE(b.origin_name,'')) <> ''
            AND TRIM(COALESCE(b.dest_name,'')) <> ''{sub_clause}
        ),
        carrier_latest AS (
          SELECT lane, carrier_name, MAX(dep) AS last_dep
          FROM base
          WHERE carrier_name IS NOT NULL AND TRIM(carrier_name) <> ''
          GROUP BY lane, carrier_name
        ),
        carrier_ranked AS (
          SELECT lane, carrier_name,
                 ROW_NUMBER() OVER (
                   PARTITION BY lane ORDER BY last_dep DESC NULLS LAST, carrier_name
                 ) AS rn
          FROM carrier_latest
        ),
        carriers_top3 AS (
          SELECT lane, string_agg(carrier_name, ', ' ORDER BY rn) AS carriers
          FROM carrier_ranked
          WHERE rn <= 3
          GROUP BY lane
        ),
        lane_agg AS (
          SELECT lane,
                 COUNT(*)                    AS movements,
                 AVG(override_pay_amt)::numeric AS avg_cost
          FROM base
          GROUP BY lane
        )
        SELECT la.lane, c.carriers, la.avg_cost, la.movements
        FROM lane_agg la
        LEFT JOIN carriers_top3 c USING (lane)
        ORDER BY la.movements DESC, la.lane
        LIMIT ${p_lim}
        """,
        *params,
    )

    comments = await get_pool(request).fetch(
        "SELECT lane_key, comments FROM kam_carrier_comments WHERE user_id = $1",
        user["sub"],
    )
    comment_map = {c["lane_key"]: (c["comments"] or "") for c in comments}

    data = [
        {
            "lane_key": r["lane"],
            "lane": r["lane"],
            "carriers": r["carriers"] or "—",
            "avg_cost": float(r["avg_cost"]) if r["avg_cost"] is not None else None,
            "movements": int(r["movements"] or 0),
            "comments": comment_map.get(r["lane"], ""),
        }
        for r in rows
    ]
    return {
        "success": True,
        "data": data,
        "meta": {"window": {"start": s.isoformat(), "end": e.isoformat()}},
    }


class CarrierCommentUpsert(BaseModel):
    lane_key: str = Field(..., min_length=1, max_length=400)
    comments: str = Field(default="", max_length=5000)


@router.put("/carrier-comments")
async def upsert_carrier_comment(
    body: CarrierCommentUpsert,
    request: Request,
    user: dict = Depends(require_report_access("kam-performance-dfw")),
):
    pool = get_pool(request)
    row = await pool.fetchrow(
        """
        INSERT INTO kam_carrier_comments (user_id, lane_key, comments, updated_at)
        VALUES ($1, $2, $3, NOW())
        ON CONFLICT (user_id, lane_key) DO UPDATE
          SET comments   = EXCLUDED.comments,
              updated_at = NOW()
        RETURNING lane_key, comments, updated_at
        """,
        user["sub"],
        body.lane_key,
        body.comments,
    )
    return {
        "success": True,
        "data": {
            "lane_key": row["lane_key"],
            "comments": row["comments"] or "",
            "updated_at": _iso(row["updated_at"]),
        },
    }
