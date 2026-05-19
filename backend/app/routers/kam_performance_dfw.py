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

from datetime import date, datetime
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from app.routers.deps import get_pool, require_report_access


router = APIRouter(
    tags=["kam-performance-dfw"],
    prefix="/custom/kam-performance-dfw",
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _iso(d) -> Optional[str]:
    if d is None:
        return None
    if isinstance(d, (datetime, date)):
        return d.isoformat()
    return str(d)


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
