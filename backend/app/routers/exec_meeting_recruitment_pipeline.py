"""Exec Meeting – Recruitment · PIPELINE — weekly funnel + live pipeline status.

Added 2026-10-12 for the weekly "Recruitment Status" e-mail (Erick Mendoza +
Daniela Nava, Mondays 16:00 CST via n8n). Own file so the 629-line report
router stays untouched; same prefix and the same report gate, so anyone who can
open Exec Meeting – Recruitment can open this.

    GET /api/custom/exec-meeting-recruitment/pipeline?weeks=8

Source: ``recruit_unilink`` (the Jobs portal at jobs.unilinktransportation.com),
role ``spaceqlik_recruit_ro`` — COLUMN-level grants on "Application", "Stage",
"StageTransition", "Offer", "Candidate" (2026-10-12). A missed grant is a 42501,
which this endpoint lets surface as a 500 rather than serve empty numbers.

DEFINITIONS — the Jobs portal's own (``src/app/(internal)/dashboard/reports/
page.tsx``), so the e-mail agrees with /dashboard/reports:

  * Active candidates   = Application.status IN_PROCESS (all positions).
  * In pipeline         = IN_PROCESS + APPLYING (the funnel's "active").
  * Stalled             = IN_PROCESS and updatedAt older than 7 days.
  * Hires               = status HIRED, bucketed by hiredAt (HIRED = accepted offer).
  * Offer acceptance    = HIRED apps / (HIRED apps + REJECTED offers), all-time.
  * Time to fill        = ceil(hiredAt − Position.createdAt) days, all-time mean.

WEEKLY FUNNEL — the part the portal does not have:

  A stage is reached when a StageTransition moves the application INTO it or any
  LATER stage. Each application counts ONCE per milestone, in the week of its
  FIRST arrival (MIN over all its transitions): a candidate bounced back and
  forth is one, not three (a log row is not an event — n8n CLAUDE.md), and a
  candidate who skips Phone Screening straight to HR Interview still counts as
  screened. Milestones are matched by stage NAME (every position carries a copy
  of the 10 default stages, measured 2026-10-12: 137 positions × 10 names, no
  custom names); a name outside DEFAULT_STAGE_ORDER is returned in
  ``unknown_stages`` so drift is visible instead of silently uncounted.

REJECTIONS (added 2026-10-12 after HR: "it doesn't include the candidates who
were rejected last week during the screening stages"): the schema has no
rejectedAt, but every single-application rejection — the application page AND
the Kanban card — writes ``ActivityLog`` (entity 'Application', entityId,
details.status 'REJECTED', createdAt). Measured: 1,736 such events since
2026-02-16, 1,725 within 2 min of the application's updatedAt, all in the same
week; every application rejected since 2026-08-17 has one. A rejection does not
move the stage, so the stage AT rejection = the toStage of the last transition at
or before it, else the first transition's fromStage, else the current stage.
The bulk path (``/api/applications/bulk``) logs one row with a COUNT and no ids
(used once, 2026-03-20, 3 rows) — a REJECTED application with NO rejection log
falls back to its updatedAt + current stage. Counted once per (application,
week): a reactivated-then-re-rejected candidate in another week counts again,
because that is a second rejection.

Weeks are Monday–Sunday America/Chicago and only COMPLETED weeks are returned.
Columns are Prisma ``timestamp(3)`` holding UTC, so bounds are computed in CST
and converted to naive UTC in Python — never a bare ``::date AT TIME ZONE``
(backend CLAUDE.md §112).
"""
from __future__ import annotations

import math
from datetime import date, datetime, timedelta, timezone
from typing import Any, Optional

from fastapi import APIRouter, Depends, Query, Request

from app.clock import CST, cst_now, cst_today
from app.routers.deps import get_recruit_pool
from app.routers.exec_meeting_recruitment import (
    EXCLUDED_FS_SUBCATEGORIES,
    REPORT_KEY,
    _access,
    _common,
    _is_excluded_display,
    _matches,
    canonical_dept,
    resolve_fs_dept,
)

router = APIRouter(
    tags=["exec-meeting-recruitment"],
    prefix="/custom/exec-meeting-recruitment",
)

# The 10 default stages, in order (Stage rows with isDefault, measured 2026-10-12).
DEFAULT_STAGE_ORDER: dict[str, int] = {
    "Bench": 0,
    "Candidates": 1,
    "Phone Sourcing": 2,
    "Phone Screening": 3,
    "HR Interview": 4,
    "Panel Interview": 5,
    "CEO/VP Approval for Hire": 6,
    "Send Offer": 7,
    "Offer Accepted": 8,
    "Hired": 9,
}

# Milestone -> first stage order that counts as reaching it.
MILESTONES: tuple[tuple[str, int], ...] = (
    ("screened", 3),   # reached Phone Screening or later
    ("valid", 4),      # passed screening: reached HR Interview or later
    ("panel", 5),      # reached Panel Interview or later
    ("offer", 7),      # reached Send Offer or later
)

# Per-role stage groups for the open-roles table (in-pipeline candidates only).
STAGE_GROUPS: tuple[tuple[str, tuple[int, ...]], ...] = (
    ("sourcing", (0, 1, 2)),
    ("screening", (3,)),
    ("interviews", (4, 5)),
    ("final", (6, 7, 8)),
)

# Rejections bucketed by the stage they happened at.
REJECTION_GROUPS: tuple[tuple[str, tuple[int, ...]], ...] = (
    ("rejected_screening", (0, 1, 2, 3)),   # Bench, Candidates, Phone Sourcing, Phone Screening
    ("rejected_interview", (4, 5)),         # HR Interview, Panel Interview
    ("rejected_final", (6, 7, 8, 9)),       # approval, offer, accepted, hired
)
SCREENING_ORDERS = REJECTION_GROUPS[0][1]

PENDING_OFFER_STATUSES = ("DRAFT", "PENDING_APPROVAL", "APPROVED", "SENT")
# CEO/VP Approval for Hire, Send Offer, Offer Accepted — the pipeline's offer
# stages. The Offer TABLE is nearly unused, so this is the honest "offers" count.
OFFER_STAGE_ORDERS = (6, 7, 8)
STALLED_DAYS = 7
MAX_WEEKS = 26


# ---------------------------------------------------------------------------
# Week windows
# ---------------------------------------------------------------------------


def completed_weeks(today: date, n: int) -> list[date]:
    """Mondays of the last ``n`` COMPLETED Mon–Sun weeks, latest first.

    On a Monday the current week has not completed, so index 0 is the week
    that ended yesterday.
    """
    this_monday = today - timedelta(days=today.weekday())
    return [this_monday - timedelta(weeks=i + 1) for i in range(n)]


def cst_midnight_utc(d: date) -> datetime:
    """CST/CDT midnight of ``d`` as the NAIVE UTC value Prisma stores."""
    local = datetime(d.year, d.month, d.day, tzinfo=CST)
    return local.astimezone(timezone.utc).replace(tzinfo=None)


def to_cst_date(ts: Optional[datetime]) -> Optional[date]:
    """Naive-UTC Prisma timestamp -> the America/Chicago calendar date."""
    if ts is None:
        return None
    return ts.replace(tzinfo=timezone.utc).astimezone(CST).date()


def week_of(ts: Optional[datetime], mondays: list[date]) -> Optional[int]:
    """Index into ``mondays`` (latest first) of the week holding ``ts``."""
    d = to_cst_date(ts)
    if d is None:
        return None
    monday = d - timedelta(days=d.weekday())
    try:
        return mondays.index(monday)
    except ValueError:
        return None


def _iso_ts(ts: Optional[datetime]) -> Optional[str]:
    if ts is None:
        return None
    return ts.replace(tzinfo=timezone.utc).astimezone(CST).isoformat(timespec="minutes")


# ---------------------------------------------------------------------------
# Reads
# ---------------------------------------------------------------------------


async def _positions(pool) -> dict[str, dict]:
    rows = await pool.fetch(
        """SELECT id, name, department, status, type, "createdAt" FROM "Position" """
    )
    return {
        r["id"]: {
            "name": (r["name"] or "").strip(),
            "department": canonical_dept(r["department"]),
            "status": r["status"],
            "type": r["type"],
            "created_at": r["createdAt"],
        }
        for r in rows
    }


async def _stage_orders(pool, since_utc: datetime) -> tuple[dict[str, int], list[str]]:
    """stageId -> canonical order, plus the stage names we cannot place.

    Only a stage that is IN USE is reported unknown — one a candidate is in now
    or moved into during the window. A stray custom stage on a long-closed
    position must not 503 the e-mail every Monday forever.
    """
    rows = await pool.fetch(
        """
        SELECT s.id, s.name,
               (s.id IN (SELECT "toStageId" FROM "StageTransition" WHERE "createdAt" >= $1)
                OR s.id IN (SELECT "stageId" FROM "Application"
                             WHERE status IN ('IN_PROCESS', 'APPLYING'))) AS in_use
          FROM "Stage" s
        """,
        since_utc,
    )
    orders: dict[str, int] = {}
    unknown: set[str] = set()
    for r in rows:
        name = (r["name"] or "").strip()
        if name in DEFAULT_STAGE_ORDER:
            orders[r["id"]] = DEFAULT_STAGE_ORDER[name]
        elif r["in_use"]:
            unknown.add(name or "(blank)")
    return orders, sorted(unknown)


async def _first_arrivals(pool, stage_orders: dict[str, int], since_utc: datetime) -> list[dict]:
    """Per application, the FIRST time it reached each milestone.

    Every transition is read (not just the window) because "first" is over the
    application's whole history: a candidate who reached screening in August and
    was moved again in October must not count again in October.
    """
    rows = await pool.fetch(
        """
        SELECT st."applicationId" AS app, st."toStageId" AS stage, st."createdAt" AS at,
               a."positionId" AS position
          FROM "StageTransition" st
          JOIN "Application" a ON a.id = st."applicationId"
         WHERE st."applicationId" IN (
                 SELECT "applicationId" FROM "StageTransition" WHERE "createdAt" >= $1
               )
        """,
        since_utc,
    )
    firsts: dict[str, dict] = {}
    for r in rows:
        order = stage_orders.get(r["stage"])
        if order is None:
            continue
        f = firsts.setdefault(r["app"], {"position": r["position"]})
        for key, threshold in MILESTONES:
            if order >= threshold and (f.get(key) is None or r["at"] < f[key]):
                f[key] = r["at"]
    return list(firsts.values())


async def _rejections(pool, since_utc: datetime) -> list[dict]:
    """Rejection EVENTS since ``since_utc`` with the stage they happened at."""
    rows = await pool.fetch(
        """
        WITH logged AS (
          SELECT DISTINCT "entityId" AS app, "createdAt" AS at
            FROM "ActivityLog"
           WHERE entity = 'Application' AND "entityId" IS NOT NULL
             AND details->>'status' = 'REJECTED' AND "createdAt" >= $1
        ),
        unlogged AS (   -- the bulk path writes no per-application row
          SELECT a.id AS app, a."updatedAt" AS at
            FROM "Application" a
           WHERE a.status = 'REJECTED' AND a."updatedAt" >= $1
             AND NOT EXISTS (
                   SELECT 1 FROM "ActivityLog" l
                    WHERE l.entity = 'Application' AND l."entityId" = a.id
                      AND l.details->>'status' = 'REJECTED')
        ),
        ev AS (
          SELECT app, at, false AS fallback FROM logged
          UNION ALL SELECT app, at, true FROM unlogged
        )
        SELECT ev.app, ev.at, ev.fallback, a."positionId" AS position,
               COALESCE(
                 (SELECT st."toStageId" FROM "StageTransition" st
                   WHERE st."applicationId" = ev.app AND st."createdAt" <= ev.at
                   ORDER BY st."createdAt" DESC LIMIT 1),
                 (SELECT st."fromStageId" FROM "StageTransition" st
                   WHERE st."applicationId" = ev.app
                   ORDER BY st."createdAt" ASC LIMIT 1),
                 a."stageId") AS stage
          FROM ev JOIN "Application" a ON a.id = ev.app
        """,
        since_utc,
    )
    return [dict(r) for r in rows]


async def _applications(pool) -> list[dict]:
    rows = await pool.fetch(
        """
        SELECT a.id, a."positionId", a."stageId", a.status::text AS status,
               a."createdAt", a."updatedAt", a."hiredAt",
               c."firstName", c."paternalLastName"
          FROM "Application" a
          JOIN "Candidate" c ON c.id = a."candidateId"
        """
    )
    return [dict(r) for r in rows]


async def _offer_counts(pool) -> dict[str, int]:
    rows = await pool.fetch(
        """SELECT status::text AS status, count(*) AS n FROM "Offer" GROUP BY 1"""
    )
    return {r["status"]: int(r["n"]) for r in rows}


async def _tickets(pool, since_utc: datetime) -> list[dict]:
    """IT ROUTE onboarding / offboarding tickets — the portal's Exits vs New Hires."""
    rows = await pool.fetch(
        """
        SELECT category, "departmentOverride", "subCategory", "ticketCreatedAt"
          FROM "FreshServiceTicket"
         WHERE category IN ('Onboarding', 'Offboarding')
           AND "hiddenFromReports" = false
           AND ("subCategory" IS NULL OR "subCategory" <> ALL($1::text[]))
           AND "ticketCreatedAt" >= $2
        """,
        EXCLUDED_FS_SUBCATEGORIES,
        since_utc,
    )
    return [
        {
            "category": r["category"],
            "department": resolve_fs_dept(r["departmentOverride"], r["subCategory"]),
            "at": r["ticketCreatedAt"],
        }
        for r in rows
    ]


# ---------------------------------------------------------------------------
# Pure aggregation (unit-tested without a database)
# ---------------------------------------------------------------------------


def _avg(xs: list[int]) -> Optional[int]:
    return round(sum(xs) / len(xs)) if xs else None


def build_pipeline(
    *,
    mondays: list[date],
    positions: dict[str, dict],
    stage_orders: dict[str, int],
    firsts: list[dict],
    applications: list[dict],
    offers: dict[str, int],
    tickets: list[dict],
    wanted_dept: Optional[str],
    now_utc: datetime,
    rejections: Optional[list[dict]] = None,
) -> dict[str, Any]:
    def in_scope(position_id: Optional[str]) -> bool:
        p = positions.get(position_id or "")
        if p is None:
            return False
        dept = p["department"]
        return not _is_excluded_display(dept) and _matches(dept, wanted_dept)

    apps = [a for a in applications if in_scope(a["positionId"])]
    n = len(mondays)
    series: dict[str, list[int]] = {
        k: [0] * n
        for k in ("new_applications", "screened", "valid", "panel", "offer",
                  "hires", "onboarding_tickets", "offboarding_tickets",
                  *(g for g, _ in REJECTION_GROUPS), "rejected_total")
    }

    for a in apps:
        i = week_of(a["createdAt"], mondays)
        if i is not None:
            series["new_applications"][i] += 1
        if a["status"] == "HIRED":
            i = week_of(a["hiredAt"], mondays)
            if i is not None:
                series["hires"][i] += 1

    for f in firsts:
        if not in_scope(f["position"]):
            continue
        for key, _ in MILESTONES:
            i = week_of(f.get(key), mondays)
            if i is not None:
                series[key][i] += 1

    # Once per (application, week) — a double-click or a log retry is one event.
    rejected_seen: set[tuple[str, int]] = set()
    rejected_lw_events: list[tuple[str, Optional[int]]] = []
    rejected_lw: dict[str, list[Optional[int]]] = {}
    for r in rejections or []:
        if not in_scope(r["position"]):
            continue
        i = week_of(r["at"], mondays)
        if i is None or (r["app"], i) in rejected_seen:
            continue
        rejected_seen.add((r["app"], i))
        order = stage_orders.get(r["stage"])
        if i == 0:
            rejected_lw_events.append((r["position"], order))
        series["rejected_total"][i] += 1
        for g, orders in REJECTION_GROUPS:
            if order in orders:
                series[g][i] += 1
        if i == 0:
            rejected_lw.setdefault(r["position"], []).append(order)

    for t in tickets:
        if _is_excluded_display(t["department"]) or not _matches(t["department"], wanted_dept):
            continue
        i = week_of(t["at"], mondays)
        if i is not None:
            key = "onboarding_tickets" if t["category"] == "Onboarding" else "offboarding_tickets"
            series[key][i] += 1

    weeks = [
        {
            "week_start": m.isoformat(),
            "week_end": (m + timedelta(days=6)).isoformat(),
            **{k: v[idx] for k, v in series.items()},
        }
        for idx, m in enumerate(mondays)
    ]

    # ---- live snapshot (Jobs-portal definitions) -------------------------
    stalled_cutoff = now_utc - timedelta(days=STALLED_DAYS)
    live = [a for a in apps if a["status"] in ("IN_PROCESS", "APPLYING")]
    by_stage = {name: 0 for name in DEFAULT_STAGE_ORDER}
    order_to_name = {v: k for k, v in DEFAULT_STAGE_ORDER.items()}
    for a in live:
        order = stage_orders.get(a["stageId"])
        if order is not None:
            by_stage[order_to_name[order]] += 1

    stalled = [
        a for a in apps
        if a["status"] == "IN_PROCESS" and a["updatedAt"] < stalled_cutoff
    ]
    hired = [a for a in apps if a["status"] == "HIRED"]
    hired_with_date = [a for a in hired if a["hiredAt"] is not None]
    rejected_offers = offers.get("REJECTED", 0)
    decided = len(hired_with_date) + rejected_offers

    ttf: dict[str, list[int]] = {"ALL": [], "EVERGREEN": [], "STANDARD": []}
    for a in hired:
        p = positions.get(a["positionId"])
        if a["hiredAt"] is None or p is None or p["created_at"] is None:
            continue
        days = max(0, math.ceil((a["hiredAt"] - p["created_at"]).total_seconds() / 86400))
        ttf["ALL"].append(days)
        if p["type"] in ttf:
            ttf[p["type"]].append(days)

    snapshot = {
        "active_candidates": sum(1 for a in apps if a["status"] == "IN_PROCESS"),
        "in_pipeline": len(live),
        "by_stage": [{"stage": k, "count": v} for k, v in by_stage.items()],
        # The portal's definition counts parked Bench candidates (≈ half of
        # it, measured 2026-10-12: 273 vs 144) — both are returned so the
        # e-mail can print the actionable one beside the portal's.
        "stalled": len(stalled),
        "stalled_excl_bench": sum(
            1 for a in stalled if stage_orders.get(a["stageId"]) != DEFAULT_STAGE_ORDER["Bench"]
        ),
        "at_offer_stage": sum(
            1 for a in live if stage_orders.get(a["stageId"]) in OFFER_STAGE_ORDERS
        ),
        # ⚠ The portal records almost no formal Offer rows (0 on 2026-10-12), so
        # "pending" and the acceptance rate's declines are structurally ~0.
        # offers_recorded lets the e-mail say so instead of printing 100%.
        "offers_recorded": sum(offers.values()),
        "offers_pending": sum(offers.get(s, 0) for s in PENDING_OFFER_STATUSES),
        "offer_acceptance": {
            "accepted": len(hired_with_date),
            "rejected": rejected_offers,
            "rate": (len(hired_with_date) / decided) if decided else None,
        },
        "time_to_fill": {
            "avg_days": _avg(ttf["ALL"]),
            "evergreen_days": _avg(ttf["EVERGREEN"]),
            "standard_days": _avg(ttf["STANDARD"]),
            "hires_measured": len(ttf["ALL"]),
        },
    }

    # ---- per open role ----------------------------------------------------
    lw = mondays[0] if mondays else None
    roles: dict[str, dict] = {}
    for pid, p in positions.items():
        if p["status"] != "ACTIVE" or not in_scope(pid):
            continue
        roles[pid] = {
            "position_id": pid,
            "in_pipeline": 0,
            **{g: 0 for g, _ in STAGE_GROUPS},
            "new_last_week": 0,
            "valid_last_week": 0,
            "rejected_screening_last_week": sum(
                1 for o in rejected_lw.get(pid, []) if o in SCREENING_ORDERS),
            "rejected_later_last_week": sum(
                1 for o in rejected_lw.get(pid, []) if o not in SCREENING_ORDERS),
            "furthest_stage": None,
        }
    furthest: dict[str, int] = {}
    for a in live:
        r = roles.get(a["positionId"])
        if r is None:
            continue
        r["in_pipeline"] += 1
        order = stage_orders.get(a["stageId"])
        for g, orders in STAGE_GROUPS:
            if order in orders:
                r[g] += 1
        if order is not None and order > furthest.get(a["positionId"], -1):
            furthest[a["positionId"]] = order
    for pid, order in furthest.items():
        roles[pid]["furthest_stage"] = order_to_name[order]
    if lw is not None:
        for a in apps:
            if a["positionId"] in roles and week_of(a["createdAt"], mondays) == 0:
                roles[a["positionId"]]["new_last_week"] += 1
        for f in firsts:
            if f["position"] in roles and week_of(f.get("valid"), mondays) == 0:
                roles[f["position"]]["valid_last_week"] += 1

    hires_last_week = sorted(
        (
            {
                "name": " ".join(
                    x for x in ((a["firstName"] or "").strip(),
                                (a["paternalLastName"] or "").strip()) if x
                ) or "(no name)",
                "position": positions[a["positionId"]]["name"],
                "department": positions[a["positionId"]]["department"],
                "hired_on": to_cst_date(a["hiredAt"]).isoformat(),
            }
            for a in hired_with_date
            if week_of(a["hiredAt"], mondays) == 0
        ),
        key=lambda h: h["hired_on"],
    )

    return {"weeks": weeks, "snapshot": snapshot, "roles": list(roles.values()),
            "hires_last_week": hires_last_week,
            "ticket_totals": ticket_totals(tickets, mondays, wanted_dept),
            "by_department": department_stats(
                apps=apps, positions=positions, firsts=firsts,
                rejected_lw_events=rejected_lw_events, mondays=mondays, in_scope=in_scope)}


def division_of(department: str) -> str:
    """CORP vs DFW by DEPARTMENT, never by Position.area — measured 2026-10-12, an
    ACTIVE "DFW OPERATIONS" role carries area 'Corporate', so area would file it
    under the wrong division."""
    return "DFW" if department == "DFW OPERATIONS" else "CORP"


def department_stats(*, apps: list[dict], positions: dict[str, dict], firsts: list[dict],
                     rejected_lw_events: list[tuple[str, Optional[int]]],
                     mondays: list[date], in_scope) -> list[dict]:
    """Per canonical department: candidates now, last-week activity, YTD hires and
    days to fill (hire date − position opened, the portal's time-to-fill), all
    over ALL in-scope positions of that department (not just the open ones).
    YTD runs Jan 1 → the last completed Sunday, like every other period here."""
    if not mondays:
        return []
    lw_end = mondays[0] + timedelta(days=6)
    year_start = date(lw_end.year, 1, 1)
    out: dict[str, dict] = {}

    def row(pid: str) -> dict:
        dept = positions[pid]["department"]
        return out.setdefault(dept, {
            "department": dept, "division": division_of(dept),
            "active_candidates": 0, "new_apps_lw": 0, "screened_lw": 0, "valid_lw": 0,
            "rejected_lw": 0, "rejected_screening_lw": 0,
            "hires_ytd": 0, "fill_days_sum": 0, "fill_days_n": 0,
        })

    for a in apps:
        r = row(a["positionId"])
        if a["status"] == "IN_PROCESS":
            r["active_candidates"] += 1
        if week_of(a["createdAt"], mondays) == 0:
            r["new_apps_lw"] += 1
        hired_on = to_cst_date(a["hiredAt"]) if a["status"] == "HIRED" else None
        if hired_on and year_start <= hired_on <= lw_end:
            r["hires_ytd"] += 1
            opened = positions[a["positionId"]]["created_at"]
            if opened is not None:
                r["fill_days_sum"] += max(0, math.ceil(
                    (a["hiredAt"] - opened).total_seconds() / 86400))
                r["fill_days_n"] += 1
    for f in firsts:
        if not in_scope(f["position"]):
            continue
        if week_of(f.get("screened"), mondays) == 0:
            row(f["position"])["screened_lw"] += 1
        if week_of(f.get("valid"), mondays) == 0:
            row(f["position"])["valid_lw"] += 1
    for pid, order in rejected_lw_events:
        r = row(pid)
        r["rejected_lw"] += 1
        if order in SCREENING_ORDERS:
            r["rejected_screening_lw"] += 1
    return sorted(out.values(), key=lambda r: (r["division"], r["department"]))


def ticket_totals(tickets: list[dict], mondays: list[date],
                  wanted_dept: Optional[str]) -> dict[str, Any]:
    """Onboarding vs offboarding over the WHOLE window and year-to-date.

    YTD runs Jan 1 → the last COMPLETED Sunday (the same end as the weekly
    table), never through today: a Monday-afternoon partial day would make the
    YTD disagree with the weeks printed above it.
    """
    if not mondays:
        return {}
    end = mondays[0] + timedelta(days=6)
    start = mondays[-1]
    year_start = date(end.year, 1, 1)
    out = {"window_start": start.isoformat(), "window_end": end.isoformat(),
           "year": end.year, "ytd_end": end.isoformat(),
           "window": {"onboarding": 0, "offboarding": 0},
           "ytd": {"onboarding": 0, "offboarding": 0}}
    for t in tickets:
        if _is_excluded_display(t["department"]) or not _matches(t["department"], wanted_dept):
            continue
        d = to_cst_date(t["at"])
        key = "onboarding" if t["category"] == "Onboarding" else "offboarding"
        if d is None or d > end:
            continue
        if d >= start:
            out["window"][key] += 1
        if d >= year_start:
            out["ytd"][key] += 1
    return out


# ---------------------------------------------------------------------------
# Endpoint
# ---------------------------------------------------------------------------


@router.get("/pipeline")
async def pipeline(
    request: Request,
    f: dict = Depends(_common),
    weeks: int = Query(8, ge=1, le=MAX_WEEKS),
    _user: dict = Depends(_access),
):
    """Weekly funnel for the last ``weeks`` completed weeks + live pipeline."""
    pool = get_recruit_pool(request)
    mondays = completed_weeks(cst_today(), weeks)
    since_utc = cst_midnight_utc(mondays[-1])

    positions = await _positions(pool)
    stage_orders, unknown = await _stage_orders(pool, since_utc)
    firsts = await _first_arrivals(pool, stage_orders, since_utc)
    rejections = await _rejections(pool, since_utc)
    applications = await _applications(pool)
    offers = await _offer_counts(pool)
    # From Jan 1 (or the window start, if earlier) so YTD totals come from the
    # same rows and filters as the weekly series.
    year_start = date(mondays[0].year, 1, 1)
    tickets = await _tickets(pool, cst_midnight_utc(min(year_start, mondays[-1])))

    data = build_pipeline(
        mondays=mondays,
        positions=positions,
        stage_orders=stage_orders,
        firsts=firsts,
        applications=applications,
        offers=offers,
        tickets=tickets,
        wanted_dept=f["department"],
        now_utc=cst_now().astimezone(timezone.utc).replace(tzinfo=None),
        rejections=rejections,
    )

    # Unfiltered freshness: the newest write ANYWHERE in the pipeline, so a dead
    # Jobs portal cannot read as a quiet week (datalake-table-health Step 3).
    as_of = await pool.fetchval(
        """SELECT greatest(
               (SELECT max("createdAt") FROM "StageTransition"),
               (SELECT max("updatedAt") FROM "Application"))"""
    )
    data["meta"] = {
        "report": REPORT_KEY,
        "weeks": weeks,
        "pipeline_as_of": _iso_ts(as_of),
        "unknown_stages": unknown,
        # Rejections with no per-application log (bulk path) — dated by updatedAt.
        "rejections_from_fallback": sum(1 for r in rejections if r["fallback"]),
    }
    return {"success": True, "data": data}
