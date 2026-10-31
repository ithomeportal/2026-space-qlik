"""Bonus Calculator — effective-dated roster / afterhours writes (2026-10-31).

🔴 **Root cause this module fixes.** `bonus_roster` / `bonus_afterhours` (and the
DFW twins) had no period column. Every month's report read EVERY row, so a
person HR added in October also appeared in — and was paid in — every earlier
month the moment anyone reopened it; a hard DELETE made a leaver vanish from
months they had worked. "Locked · approved" was a label only: no write checked
it, so an approved month's payroll still moved under HR's feet.

**Decision (Diego, 2026-10-31):** a row carries `effective_from` / `effective_to`
(first-of-month DATEs; NULL from = since always, NULL to = still open). A write
belongs to the PERIOD HR Settings is open on — HR edits month M during M+1 — and
a write into a locked month is refused with HTTP 409. No report-JSON freeze.

Semantics, for period P (its first day):

* visible in P  ⇔ (from IS NULL OR from <= P) AND (to IS NULL OR to >= P)
* POST          ⇒ from = P                    (absent from every month before P)
* DELETE        ⇒ from >= P: hard delete      (it never existed earlier)
                  else:      to = P − 1 month (kept in earlier months, gone from P on)
* PUT           ⇒ visible before P: close the old row at P − 1 month and insert
                  the edited copy from P      (earlier months keep the old values)
                  else: update in place
* lock          ⇒ a roster/afterhours write at P carries into every LATER month,
                  so it is refused when P **or any later month** is approved.
                  An FX write touches P only, so only P's own lock refuses it.

The request models live here at MODULE level (FastAPI resolves body annotations
through a TypeAdapter; a class local to a function is an unresolvable ForwardRef
that 500s /openapi.json — see SPEC-BONUS-CALCULATOR R13). `bonus_calculator`
re-exports them.

⚠ Scope is duck-typed (`scope.tbl_roster`, …) to avoid a circular import with
`bonus_calculator`, which registers these endpoints on each scope's router.
"""

from __future__ import annotations

import re
from calendar import month_name
from datetime import date
from typing import Any, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field

from app.clock import cst_today
from app.routers.deps import get_pool

VALID_ROLES = ("kam", "freight_match", "tracking_tracing")
PERIOD_PATTERN = r"^\d{4}-(0[1-9]|1[0-2])$"
_PERIOD_RE = re.compile(PERIOD_PATTERN)


# ---------------------------------------------------------------------------
# Period helpers
# ---------------------------------------------------------------------------


def period_start(period_key: str) -> date:
    """First day of a 'YYYY-MM' period; 422 on anything else."""
    if not isinstance(period_key, str) or not _PERIOD_RE.match(period_key):
        raise HTTPException(status_code=422, detail="period must be 'YYYY-MM'")
    y, m = (int(x) for x in period_key.split("-"))
    return date(y, m, 1)


def previous_month(first: date) -> date:
    """First day of the month before ``first``."""
    return date(first.year - 1, 12, 1) if first.month == 1 else date(first.year, first.month - 1, 1)


def current_cst_period_key() -> str:
    """The calendar month today is in (CST) — the fallback write period."""
    t = cst_today()
    return f"{t.year:04d}-{t.month:02d}"


def resolve_write_period(period_key: Optional[str]) -> tuple[str, date]:
    """(key, first day) of the period a write belongs to."""
    key = period_key or current_cst_period_key()
    return key, period_start(key)


def period_label(period_key: str) -> str:
    y, m = (int(x) for x in period_key.split("-"))
    return f"{month_name[m]} {y}"


def visible_in(param: str) -> str:
    """SQL predicate: the row is a member of the month whose first day is ``param``."""
    return (
        f"(effective_from IS NULL OR effective_from <= {param})"
        f" AND (effective_to IS NULL OR effective_to >= {param})"
    )


# ---------------------------------------------------------------------------
# Lock guard
# ---------------------------------------------------------------------------


async def assert_period_writable(pool, scope: Any, period_key: str, *, carries_forward: bool) -> None:
    """409 when the write would change an approved month.

    ``carries_forward``: a roster/afterhours change at P is visible in every
    later month too, so any approved month >= P refuses it. FX is per-period.
    """
    op = ">=" if carries_forward else "="
    locked = await pool.fetchval(
        f"""
        SELECT MIN(period_key) FROM {scope.tbl_lock}
        WHERE status = 'approved' AND period_key {op} $1
        """,
        period_key,
    )
    if not locked:
        return
    detail = f"{period_label(locked)} is Locked · approved — unlock it to edit"
    if locked != period_key:
        detail += f" (a change made in {period_label(period_key)} carries into every later month)"
    raise HTTPException(status_code=409, detail=detail)


# ---------------------------------------------------------------------------
# Request models (MODULE level — see the module docstring)
# ---------------------------------------------------------------------------


class RosterRow(BaseModel):
    team_id: str
    name: str = Field(min_length=1, max_length=120)
    role: str
    salary_mxn: float = Field(ge=0, le=10_000_000)
    # The month HR Settings is open on. Absent ⇒ the current CST month.
    period_key: Optional[str] = Field(default=None, pattern=PERIOD_PATTERN)

    def validate_domain(self, scope: Any) -> None:
        """⚠ Validated against the CALLER'S scope, not a class-level list.

        A corporate team id POSTed to the DFW roster must be REJECTED, not
        stored — stored, it would be invisible (the report only reads
        `scope.teams`) rather than wrong, which is harder to notice. The scope
        is an argument because these models must live at MODULE level.
        """
        if self.team_id not in scope.teams:
            raise HTTPException(status_code=422, detail=f"team_id must be one of {scope.teams}")
        if self.role not in VALID_ROLES:
            raise HTTPException(status_code=422, detail=f"role must be one of {VALID_ROLES}")


class AfterhoursRow(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    salary_mxn: float = Field(ge=0, le=10_000_000)
    receives_bonus: bool = True
    period_key: Optional[str] = Field(default=None, pattern=PERIOD_PATTERN)


class AfterhoursCreate(AfterhoursRow):
    # Bruno Bonus R6 (PDF 2026-07-15): adding an Afterhours worker also needs the
    # shift group (the "Group" column, e.g. "Night Shift" / "Weekend Shift").
    shift_group: str = Field(min_length=1, max_length=60)


# ---------------------------------------------------------------------------
# Effective-dated primitives (shared by roster + afterhours)
# ---------------------------------------------------------------------------


async def _visible_row(conn, table: str, row_id: UUID, start: date):
    return await conn.fetchrow(
        f"SELECT * FROM {table} WHERE id = $1 AND {visible_in('$2')} FOR UPDATE",
        row_id,
        start,
    )


async def remove_in_period(pool, table: str, row_id: UUID, start: date) -> str:
    """Hard delete a row that starts in P; soft-close (to = P − 1) an older one.

    Returns "deleted" / "closed"; 404 when the row is not a member of P.
    """
    async with pool.acquire() as conn:
        async with conn.transaction():
            row = await _visible_row(conn, table, row_id, start)
            if row is None:
                raise HTTPException(status_code=404, detail="Row not found in this period")
            if row["effective_from"] is not None and row["effective_from"] >= start:
                await conn.execute(f"DELETE FROM {table} WHERE id = $1", row_id)
                return "deleted"
            await conn.execute(
                f"UPDATE {table} SET effective_to = $2 WHERE id = $1",
                row_id,
                previous_month(start),
            )
            return "closed"


async def edit_in_period(
    pool, table: str, row_id: UUID, start: date, edits: dict[str, Any]
) -> str:
    """Apply ``edits`` from P on, leaving every earlier month's values intact.

    A row already visible before P is split: the old row closes at P − 1 and a
    copy carrying the edits starts at P (keeping the old row's own end date).
    A row that starts at P is updated in place. Returns the id that now holds P.
    """
    cols = list(edits)
    async with pool.acquire() as conn:
        async with conn.transaction():
            row = await _visible_row(conn, table, row_id, start)
            if row is None:
                raise HTTPException(status_code=404, detail="Row not found in this period")
            if row["effective_from"] is not None and row["effective_from"] >= start:
                sets = ", ".join(f"{c} = ${i + 2}" for i, c in enumerate(cols))
                await conn.execute(
                    f"UPDATE {table} SET {sets} WHERE id = $1", row_id, *edits.values()
                )
                return str(row_id)
            old_to = row["effective_to"]  # the copy keeps the old row's own end
            merged = {**{k: row[k] for k in _copy_columns(table)}, **edits}
            await conn.execute(
                f"UPDATE {table} SET effective_to = $2 WHERE id = $1",
                row_id,
                previous_month(start),
            )
            names = list(merged)
            placeholders = ", ".join(f"${i + 1}" for i in range(len(names) + 2))
            new_id = await conn.fetchval(
                f"""
                INSERT INTO {table} ({", ".join(names)}, effective_from, effective_to)
                VALUES ({placeholders})
                RETURNING id
                """,
                *merged.values(),
                start,
                old_to,
            )
            return str(new_id)


def _copy_columns(table: str) -> tuple[str, ...]:
    """Columns a split copies over (everything HR-owned; never id/created_at)."""
    if "afterhours" in table:
        return ("shift_group", "employee_name", "salary_mxn", "receives_bonus", "sort_order")
    return ("team_id", "employee_name", "role", "salary_mxn", "sort_order")


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


def register_roster_writes(r: APIRouter, scope: Any, gate) -> None:
    """Attach the roster + afterhours write endpoints for one scope."""
    _register_roster(r, scope, gate)
    _register_afterhours(r, scope, gate)


def _register_roster(r: APIRouter, scope: Any, gate) -> None:
    @r.post("/roster")
    async def create_roster_row(request: Request, body: RosterRow, user: dict = Depends(gate)):
        body.validate_domain(scope)
        key, start = resolve_write_period(body.period_key)
        primary = get_pool(request)
        await assert_period_writable(primary, scope, key, carries_forward=True)
        next_sort = await primary.fetchval(
            f"SELECT COALESCE(MAX(sort_order), -1) + 1 FROM {scope.tbl_roster} WHERE team_id = $1",
            body.team_id,
        )
        row = await primary.fetchrow(
            f"""
            INSERT INTO {scope.tbl_roster}
              (team_id, employee_name, role, salary_mxn, sort_order, effective_from)
            VALUES ($1, $2, $3, $4, $5, $6)
            RETURNING id
            """,
            body.team_id, body.name.strip(), body.role, body.salary_mxn, next_sort, start,
        )
        return {"success": True, "data": {"id": str(row["id"])}}

    @r.put("/roster/{row_id}")
    async def update_roster_row(
        request: Request, row_id: UUID, body: RosterRow, user: dict = Depends(gate)
    ):
        body.validate_domain(scope)
        key, start = resolve_write_period(body.period_key)
        primary = get_pool(request)
        await assert_period_writable(primary, scope, key, carries_forward=True)
        edits = {
            "team_id": body.team_id,
            "employee_name": body.name.strip(),
            "role": body.role,
            "salary_mxn": body.salary_mxn,
        }
        new_id = await edit_in_period(primary, scope.tbl_roster, row_id, start, edits)
        return {"success": True, "data": {"id": new_id}}

    @r.delete("/roster/{row_id}")
    async def delete_roster_row(
        request: Request,
        row_id: UUID,
        period: Optional[str] = Query(None, pattern=PERIOD_PATTERN),
        user: dict = Depends(gate),
    ):
        key, start = resolve_write_period(period)
        primary = get_pool(request)
        await assert_period_writable(primary, scope, key, carries_forward=True)
        outcome = await remove_in_period(primary, scope.tbl_roster, row_id, start)
        return {"success": True, "data": {"outcome": outcome}}


def _register_afterhours(r: APIRouter, scope: Any, gate) -> None:
    @r.post("/afterhours")
    async def create_afterhours_row(
        request: Request, body: AfterhoursCreate, user: dict = Depends(gate)
    ):
        """Bruno Bonus R6 (2026-07-15): HR adds an Afterhours (Night/Weekend) worker."""
        key, start = resolve_write_period(body.period_key)
        primary = get_pool(request)
        await assert_period_writable(primary, scope, key, carries_forward=True)
        next_sort = await primary.fetchval(
            f"SELECT COALESCE(MAX(sort_order), -1) + 1 FROM {scope.tbl_afterhours}"
        )
        row = await primary.fetchrow(
            f"""
            INSERT INTO {scope.tbl_afterhours}
              (shift_group, employee_name, salary_mxn, receives_bonus, sort_order, effective_from)
            VALUES ($1, $2, $3, $4, $5, $6)
            RETURNING id
            """,
            body.shift_group.strip(), body.name.strip(), body.salary_mxn,
            body.receives_bonus, next_sort, start,
        )
        return {"success": True, "data": {"id": str(row["id"])}}

    @r.put("/afterhours/{row_id}")
    async def update_afterhours_row(
        request: Request, row_id: UUID, body: AfterhoursRow, user: dict = Depends(gate)
    ):
        key, start = resolve_write_period(body.period_key)
        primary = get_pool(request)
        await assert_period_writable(primary, scope, key, carries_forward=True)
        edits = {
            "employee_name": body.name.strip(),
            "salary_mxn": body.salary_mxn,
            "receives_bonus": body.receives_bonus,
        }
        new_id = await edit_in_period(primary, scope.tbl_afterhours, row_id, start, edits)
        return {"success": True, "data": {"id": new_id}}

    @r.delete("/afterhours/{row_id}")
    async def delete_afterhours_row(
        request: Request,
        row_id: UUID,
        period: Optional[str] = Query(None, pattern=PERIOD_PATTERN),
        user: dict = Depends(gate),
    ):
        """Bruno Bonus R7 (2026-07-15): HR removes an Afterhours (Night/Weekend) worker."""
        key, start = resolve_write_period(period)
        primary = get_pool(request)
        await assert_period_writable(primary, scope, key, carries_forward=True)
        outcome = await remove_in_period(primary, scope.tbl_afterhours, row_id, start)
        return {"success": True, "data": {"outcome": outcome}}
