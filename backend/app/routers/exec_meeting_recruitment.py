"""Exec Meeting – Recruitment (Bruno PDF, 2026-08-17 — "BRUNO -- Recruitment").

Seven requests, sourced from two databases that the portal reads read-only:

  * ``recruit_unilink``            (role ``spaceqlik_recruit_ro``) — "Position",
    "FreshServiceTicket". The Jobs portal at jobs.unilinktransportation.com.
  * ``timeoff_at_unilink_portal``  (role ``spaceqlik_timeoff_ro``) — ``users``.

They are separate databases, so nothing is JOINed in SQL — each half is fetched
and merged in Python (§56).

SCOPE DECISIONS — these are deliberate. Do not "fix" them without re-reading this.

1. NEW HIRES come from time-off ``"hireDate"``, matching the Jobs portal's own
   Human Capital dashboard (its rule 17) so the two portals agree. **This is a
   stakeholder decision made with the trade-off on the table**, and it carries a
   known bias worth restating: the ``users`` table drops departed staff over
   time, so prior-year hire counts are undercounts that get worse with age.
   Measured 2026-08-17 against FreshService Onboarding tickets, same window:

       2024 -> 30 rows present vs 119 onboarded  (25% coverage)
       2025 -> 61 rows present vs  99 onboarded  (62% coverage)
       2026 -> 63 rows present vs  71 onboarded  (89% coverage)

   The year-over-year New-hires series therefore trends UP largely because
   coverage improves, not because hiring grew. ``/annual`` returns
   ``hire_coverage`` per year and the UI prints it as a caption so an exec
   reading the panel cannot mistake the artefact for a trend. If that caveat
   ever becomes unacceptable, switch to FS Onboarding tickets — symmetric with
   the Offboarding side already used below — and re-baseline both series.

2. EXITS come from FreshService Offboarding tickets, never time-off
   ``"leaveDate"``. Measured 2026-08-17: of 89 inactive employees, 45 (51%) have
   a NULL ``"leaveDate"``, and the column records ZERO 2026 exits. It is dead
   data. The Jobs portal reached the same conclusion independently.

3. PEOPLE FLOW (§03) is the one panel that needs a per-person hire AND exit date
   on the same row, so it uses time-off ``"leaveDate"`` — because there is NO
   reliable key joining a time-off person to an FS ticket (FS carries only a
   free-text ``subject`` and FreshService-internal requester ids; the Jobs repo's
   own matcher is a fuzzy name substring with a +/-15-day window that still had a
   not-found bucket). A fuzzy join here would print a wrong departure date next
   to a named, real employee — the most visible possible failure.
   Consequence, stated plainly: the exit markers in §03 do NOT tie to the
   Offboarding KPI in §02. They answer different questions and are labelled as
   such. Where a person is inactive but has no ``"leaveDate"``, the row is marked
   ``departed_exit_unknown`` and the timeline is NOT extended to today — a
   departure must never render as an active employee.

4. OPEN ROLES: "Open Vacancies" is SUM(GREATEST(0, vacancies - "hiredCount"))
   over ``status = 'ACTIVE'`` positions — a summed remainder, never a row count.
   It legitimately differs from the number of rows in §05 (measured: 9 vacancies
   across 8 roles), so both are returned together and rendered on one card; a
   KPI must never disagree with the detail beneath it (§16).

5. TURNOVER RATE appears in the mockup but not the written request. Its honest
   denominator is the headcount *during* the year, which the time-off table
   cannot reconstruct for past years (same survivorship bias as note 1). It is
   therefore returned ONLY for the current year, against today's active
   headcount, and ``None`` for prior years rather than a fabricated figure.

6. DEPARTMENT: three systems, three vocabularies. The per-source maps are copied
   verbatim from the Jobs portal so totals reconcile with it, then a thin
   canonicalisation folds label-only variants ("Executive Assistance" /
   "Executive Assistant", "Legal" / "QA & Legal", "HR" / "Human Resources",
   "Finances" / "Finance", "Corp Sales" / "Sales") so ONE filter can drive all
   panels. Folding changes labels only, never totals. Note the inherited lossy
   entry: FS "Carrier Procurement" maps to "Other", which discards an HR
   correction — kept deliberately so exit counts match the Jobs dashboard.
"""

from __future__ import annotations

import logging
from datetime import date, datetime, timedelta
from typing import Any, Optional

from fastapi import APIRouter, Depends, Query, Request

from app.clock import cst_today
from app.routers.deps import get_recruit_pool, get_timeoff_pool, require_report_access

logger = logging.getLogger(__name__)

router = APIRouter(
    tags=["exec-meeting-recruitment"],
    prefix="/custom/exec-meeting-recruitment",
)

REPORT_KEY = "exec-meeting-recruitment"
_access = require_report_access(REPORT_KEY)

# ---------------------------------------------------------------------------
# Exclusions — copied verbatim from the Jobs portal's src/lib/human-capital.ts
# so every figure here reconciles with its Human Capital dashboard.
# ---------------------------------------------------------------------------

# Lowercase on purpose: compared against LOWER(TRIM(department)).
EXCLUDED_TIMEOFF_DEPARTMENTS = [
    "seek",
    "oiltex",
    "presidency",
    "dfw presidency",
    "aviation",
]

# The generic admin account is not a real employee.
EXCLUDED_EMAILS = ["ithome@unilinkportal.com"]

# FS ticket subCategories that map to excluded departments.
EXCLUDED_FS_SUBCATEGORIES = ["Seek", "OilTex"]

# Time-off raw department -> display name. Splits Operations into CORP/DFW.
TIMEOFF_DEPT_DISPLAY = {
    "Operations (DFW)": "DFW OPERATIONS",
    "Operations": "CORP OPERATIONS",
}

# FS subCategory -> display name. Verbatim from the Jobs portal, including the
# lossy "Carrier Procurement" -> "Other" entry (see docstring note 6).
FS_TO_TIMEOFF_DEPT = {
    "DFW": "DFW OPERATIONS",
    "Admin": "Admin",
    "Executive": "Executive",
    "Legal": "Legal",
    "Finances": "Finance",
    "Sales": "Sales",
    "Operations": "CORP OPERATIONS",
    "HR": "Human Resources",
    "Pricing": "Pricing",
    "IT": "IT",
    "TIS": "IT",
    "Carrier Procurement": "Other",
    "OilTex": "Other",
    "Seek": "Other",
    "U-Capital": "Other",
}

# Label-only folds so a single filter drives all three sources. Keyed lowercase.
CANONICAL_DEPT = {
    "executive assistance": "Executive Assistant",
    "executive assistant": "Executive Assistant",
    "corp sales": "Sales",
    "sales": "Sales",
    "legal": "QA & Legal",
    "qa & legal": "QA & Legal",
    "hr": "Human Resources",
    "human resources": "Human Resources",
    "finances": "Finance",
    "finance": "Finance",
}

UNASSIGNED = "Unassigned"


def canonical_dept(name: Optional[str]) -> str:
    """Fold label-only variants onto one display name."""
    if not name or not name.strip():
        return UNASSIGNED
    cleaned = name.strip()
    return CANONICAL_DEPT.get(cleaned.lower(), cleaned)


def normalize_timeoff_dept(dept: Optional[str]) -> str:
    """Time-off raw department -> canonical display name."""
    if not dept or not dept.strip():
        return UNASSIGNED
    cleaned = dept.strip()
    return canonical_dept(TIMEOFF_DEPT_DISPLAY.get(cleaned, cleaned))


def resolve_fs_dept(override: Optional[str], sub_category: Optional[str]) -> str:
    """FS ticket -> canonical display name.

    ``departmentOverride`` always wins over ``subCategory`` (the Jobs portal's
    rule 43); HR sets it by hand and the cron sync never overwrites it. Override
    values carry real case drift ("Carrier procurement"), so the lookup is
    case-insensitive.
    """
    effective = (override or sub_category or "").strip()
    if not effective:
        return UNASSIGNED
    for key, mapped in FS_TO_TIMEOFF_DEPT.items():
        if key.lower() == effective.lower():
            return canonical_dept(mapped)
    return canonical_dept(effective)


def _is_excluded_display(name: str) -> bool:
    return name.strip().lower() in EXCLUDED_TIMEOFF_DEPARTMENTS


# ---------------------------------------------------------------------------
# Shared params. Sibling endpoints on one screen MUST declare the same params —
# FastAPI silently DROPS an undeclared query param, so one panel would scope
# while the panel beside it did not (§55).
# ---------------------------------------------------------------------------


def _common(department: Optional[str] = Query(None)):
    dept = (department or "").strip()
    return {"department": canonical_dept(dept) if dept and dept.lower() != "all" else None}


def _matches(dept_display: str, wanted: Optional[str]) -> bool:
    return wanted is None or dept_display == wanted


def _year_bounds(year: int) -> tuple[datetime, datetime]:
    return datetime(year, 1, 1), datetime(year + 1, 1, 1)


def _iso(value: Any) -> Optional[str]:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    return str(value)


# ---------------------------------------------------------------------------
# Time-off reads
# ---------------------------------------------------------------------------

_TIMEOFF_EXCLUDE = """
      AND email <> ALL($1::text[])
      AND (department IS NULL OR LOWER(TRIM(department)) <> ALL($2::text[]))
"""


async def active_headcount_by_department(pool) -> dict[str, int]:
    """Active headcount per canonical department — the ONE definition of
    "active employee" in this feature (§69).

    Both the KPI card and the monthly headcount snapshot read through here. If
    they ever diverge, the turnover denominator stops matching the headcount
    printed beside it, which is exactly the kind of disagreement §16 forbids.
    """
    rows = await pool.fetch(
        f"""
        SELECT department FROM users
         WHERE "isActive" = true {_TIMEOFF_EXCLUDE}
        """,
        EXCLUDED_EMAILS,
        EXCLUDED_TIMEOFF_DEPARTMENTS,
    )
    counts: dict[str, int] = {}
    for r in rows:
        dept = normalize_timeoff_dept(r["department"])
        counts[dept] = counts.get(dept, 0) + 1
    return counts


async def _active_employees(pool, wanted_dept: Optional[str]) -> int:
    """Request 3 — headcount of active employees, Jobs-portal definition."""
    counts = await active_headcount_by_department(pool)
    return sum(n for dept, n in counts.items() if _matches(dept, wanted_dept))


async def _new_hires(pool, year: int, wanted_dept: Optional[str]) -> int:
    """Request 5 — new hires in a calendar year, from time-off "hireDate"."""
    start, end = _year_bounds(year)
    rows = await pool.fetch(
        f"""
        SELECT department FROM users
         WHERE "hireDate" IS NOT NULL
           AND "hireDate" >= $3::timestamp
           AND "hireDate" <  $4::timestamp
           {_TIMEOFF_EXCLUDE}
        """,
        EXCLUDED_EMAILS,
        EXCLUDED_TIMEOFF_DEPARTMENTS,
        start,
        end,
    )
    return sum(
        1 for r in rows if _matches(normalize_timeoff_dept(r["department"]), wanted_dept)
    )


# ---------------------------------------------------------------------------
# recruit_unilink reads
# ---------------------------------------------------------------------------


async def _offboarding(pool, year: int, wanted_dept: Optional[str]) -> int:
    """Request 5 — exits in a calendar year, from FS Offboarding tickets."""
    start, end = _year_bounds(year)
    rows = await pool.fetch(
        """
        SELECT "departmentOverride", "subCategory"
          FROM "FreshServiceTicket"
         WHERE category = 'Offboarding'
           AND "hiddenFromReports" = false
           AND ("subCategory" IS NULL OR "subCategory" <> ALL($1::text[]))
           AND "ticketCreatedAt" >= $2::timestamp
           AND "ticketCreatedAt" <  $3::timestamp
        """,
        EXCLUDED_FS_SUBCATEGORIES,
        start,
        end,
    )
    return sum(
        1
        for r in rows
        if _matches(resolve_fs_dept(r["departmentOverride"], r["subCategory"]), wanted_dept)
    )


async def _open_positions(pool, wanted_dept: Optional[str]) -> list[dict]:
    """Requests 4 + 7 — ACTIVE positions. DRAFT/PAUSED/CLOSED are not open."""
    rows = await pool.fetch(
        """
        SELECT id, name, department, company, "createdAt", vacancies, "hiredCount"
          FROM "Position"
         WHERE status = 'ACTIVE'
         ORDER BY "createdAt" ASC
        """
    )
    today = cst_today()
    out: list[dict] = []
    for r in rows:
        dept = canonical_dept(r["department"])
        if _is_excluded_display(dept) or not _matches(dept, wanted_dept):
            continue
        created = r["createdAt"]
        created_date = created.date() if isinstance(created, datetime) else created
        out.append(
            {
                "id": r["id"],
                "name": (r["name"] or "").strip(),
                "department": dept,
                "company": (r["company"] or "").strip(),
                "opened_on": _iso(created),
                "days_open": max(0, (today - created_date).days),
                "vacancies": int(r["vacancies"] or 0),
                "hired_count": int(r["hiredCount"] or 0),
                "open_vacancies": max(0, int(r["vacancies"] or 0) - int(r["hiredCount"] or 0)),
            }
        )
    return out


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.get("/filters")
async def filters(
    request: Request,
    _user: dict = Depends(_access),
):
    """Request 2 — the Department filter's options.

    The union of all three vocabularies after canonicalisation, so a department
    that exists in only one source is still selectable there.
    """
    timeoff = get_timeoff_pool(request)
    recruit = get_recruit_pool(request)

    names: set[str] = set()

    for r in await timeoff.fetch(
        f"""SELECT DISTINCT department FROM users
             WHERE "isActive" = true {_TIMEOFF_EXCLUDE}""",
        EXCLUDED_EMAILS,
        EXCLUDED_TIMEOFF_DEPARTMENTS,
    ):
        names.add(normalize_timeoff_dept(r["department"]))

    for r in await recruit.fetch(
        """SELECT DISTINCT department FROM "Position" WHERE status = 'ACTIVE'"""
    ):
        names.add(canonical_dept(r["department"]))

    for r in await recruit.fetch(
        """SELECT DISTINCT "departmentOverride", "subCategory"
             FROM "FreshServiceTicket" WHERE category = 'Offboarding'"""
    ):
        names.add(resolve_fs_dept(r["departmentOverride"], r["subCategory"]))

    departments = sorted(
        n for n in names if n != UNASSIGNED and not _is_excluded_display(n)
    )

    current = cst_today().year
    return {
        "success": True,
        "data": {
            "departments": departments,
            "years": [current, current - 1, current - 2],
        },
    }


@router.get("/summary")
async def summary(
    request: Request,
    f: dict = Depends(_common),
    _user: dict = Depends(_access),
):
    """Requests 3 + 4 — the two headline KPIs."""
    positions = await _open_positions(get_recruit_pool(request), f["department"])
    active = await _active_employees(get_timeoff_pool(request), f["department"])

    open_vacancies = sum(p["open_vacancies"] for p in positions)
    avg_days = (
        round(sum(p["days_open"] for p in positions) / len(positions)) if positions else 0
    )
    return {
        "success": True,
        "data": {
            "active_employees": active,
            "open_roles": len(positions),
            "open_vacancies": open_vacancies,
            "avg_days_open": avg_days,
        },
    }


@router.get("/annual")
async def annual(
    request: Request,
    f: dict = Depends(_common),
    year: Optional[int] = Query(None),
    _user: dict = Depends(_access),
):
    """Request 5 — ANNUAL MOVEMENT: new hires vs offboarding for one year."""
    current = cst_today().year
    selected = year if year and current - 5 <= year <= current else current

    timeoff = get_timeoff_pool(request)
    recruit = get_recruit_pool(request)

    new_hires = await _new_hires(timeoff, selected, f["department"])
    offboarding = await _offboarding(recruit, selected, f["department"])

    # Turnover only where the denominator is REAL (docstring note 5).
    #
    # Current year -> today's active headcount, the same figure on the KPI card.
    # Past year    -> the mean of that year's recorded monthly snapshots, if we
    #                 were recording yet. Snapshots began 2026-08; for any year
    #                 before that there is nothing to average and this stays
    #                 None, so the UI prints "—" instead of a reconstructed
    #                 number. Never fall back to today's headcount for a past
    #                 year: the time-off table holds today's survivors, not that
    #                 year's staff, which would understate the denominator and
    #                 overstate turnover.
    from app.services.headcount_snapshot import average_headcount_for_year

    turnover_rate = None
    turnover_basis = None
    if selected == current:
        headcount = await _active_employees(timeoff, f["department"])
        if headcount:
            turnover_rate = offboarding / headcount
            turnover_basis = "exits this year / active headcount today"
    else:
        # Read app.state directly rather than via get_pool(): a missing hub pool
        # must degrade to "no turnover figure", not 503 the whole panel over an
        # optional enrichment (§56 fail soft).
        avg = await average_headcount_for_year(
            getattr(request.app.state, "pool", None), selected, f["department"]
        )
        if avg:
            turnover_rate = offboarding / avg
            turnover_basis = (
                "exits / average monthly headcount that year (recorded snapshots)"
            )

    return {
        "success": True,
        "data": {
            "year": selected,
            "new_hires": new_hires,
            "offboarding": offboarding,
            "turnover_rate": turnover_rate,
            "turnover_basis": turnover_basis,
            # Surfaced so the UI can caption the known undercount rather than
            # letting improving coverage read as a hiring trend (docstring 1).
            "hires_are_historical": selected < current,
        },
    }


@router.get("/people-flow")
async def people_flow(
    request: Request,
    f: dict = Depends(_common),
    range: Optional[str] = Query("12m"),
    start_date: Optional[date] = Query(None),
    end_date: Optional[date] = Query(None),
    _user: dict = Depends(_access),
):
    """Request 6 — one row per employee, hire date through departure date."""
    today = cst_today()
    if range == "custom" and start_date and end_date:
        window_start, window_end = start_date, end_date
    elif range == "all":
        window_start, window_end = date(2000, 1, 1), today
    elif range == "6m":
        window_start, window_end = today - timedelta(days=182), today
    else:
        window_start, window_end = today - timedelta(days=365), today

    if window_start > window_end:
        window_start, window_end = window_end, window_start

    rows = await get_timeoff_pool(request).fetch(
        f"""
        SELECT id, name, "firstName", "lastName", "jobTitle", department,
               "hireDate", "leaveDate", "isActive"
          FROM users
         WHERE "hireDate" IS NOT NULL
           AND "hireDate" >= $3::timestamp
           AND "hireDate" <  $4::timestamp
           {_TIMEOFF_EXCLUDE}
         ORDER BY "hireDate" DESC
         LIMIT 200
        """,
        EXCLUDED_EMAILS,
        EXCLUDED_TIMEOFF_DEPARTMENTS,
        datetime.combine(window_start, datetime.min.time()),
        datetime.combine(window_end + timedelta(days=1), datetime.min.time()),
    )

    people: list[dict] = []
    for r in rows:
        dept = normalize_timeoff_dept(r["department"])
        if not _matches(dept, f["department"]):
            continue

        name = (r["name"] or "").strip()
        if not name:
            name = f"{(r['firstName'] or '').strip()} {(r['lastName'] or '').strip()}".strip()

        active = bool(r["isActive"])
        leave = r["leaveDate"]
        if active:
            status = "active"
        elif leave is not None:
            status = "departed"
        else:
            # Inactive with no recorded exit date. Never extend this line to
            # today — that would render a departure as an active employee.
            status = "departed_exit_unknown"

        people.append(
            {
                "id": r["id"],
                "name": name or "(unnamed)",
                "job_title": (r["jobTitle"] or "").strip() or None,
                "department": dept,
                "hire_date": _iso(r["hireDate"]),
                "exit_date": _iso(leave),
                "status": status,
            }
        )

    return {
        "success": True,
        "data": {
            "rows": people,
            "window": {
                "from": window_start.isoformat(),
                "to": window_end.isoformat(),
            },
            "exit_source": "timeoff.leaveDate",
        },
        "meta": {"total": len(people)},
    }


@router.get("/open-roles")
async def open_roles(
    request: Request,
    f: dict = Depends(_common),
    _user: dict = Depends(_access),
):
    """Request 7 — OPEN CAPACITY: every active role with its age in days."""
    positions = await _open_positions(get_recruit_pool(request), f["department"])
    positions.sort(key=lambda p: p["days_open"], reverse=True)
    avg_days = (
        round(sum(p["days_open"] for p in positions) / len(positions)) if positions else 0
    )
    return {
        "success": True,
        "data": {
            "rows": positions,
            "open_roles": len(positions),
            "open_vacancies": sum(p["open_vacancies"] for p in positions),
            "avg_days_open": avg_days,
        },
        "meta": {"total": len(positions)},
    }


@router.get("/freshness")
async def freshness(
    request: Request,
    _user: dict = Depends(_access),
):
    """A page over synced tables needs a visible staleness signal, or a dead
    pipeline and a quiet week look identical (§54)."""
    recruit_latest = await get_recruit_pool(request).fetchval(
        """SELECT max("ticketCreatedAt") FROM "FreshServiceTicket" """
    )
    timeoff_latest = await get_timeoff_pool(request).fetchval(
        """SELECT max("updatedAt") FROM users"""
    )

    today = cst_today()
    stale_days = 14
    is_stale = False
    if recruit_latest is not None:
        latest = recruit_latest.date() if isinstance(recruit_latest, datetime) else recruit_latest
        is_stale = (today - latest).days > stale_days

    return {
        "success": True,
        "data": {
            "tickets": _iso(recruit_latest),
            "people": _iso(timeoff_latest),
            "is_stale": is_stale,
        },
    }
