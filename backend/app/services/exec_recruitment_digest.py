"""Weekly "Recruitment Status" e-mail digest (data layer).

Requested 2026-10-12: a recruitment status report to Erick Mendoza (CEO) and
Daniela Nava (HR Director), Bcc dfrodriguez — now Monday + Thursday 16:00 CST and
also Christian Mendoza + Jaime Anaya (n8n holds the list) — built from
the Exec Meeting – Recruitment report plus the Jobs portal's /dashboard/reports
indicators, with a week-by-week count of screened / valid candidates.

Pulled by an external n8n workflow through
``GET /api/custom/exec-meeting-recruitment/digest-email`` — see
``app/routers/exec_recruitment_digest.py``. Rendering is in
``exec_recruitment_digest_html.py``.

Every number is read back from the report's OWN endpoints, in process via
``httpx.ASGITransport`` (the attrition / team_perf digest pattern), so the
e-mail is the page — one definition per metric:

  /summary, /open-roles, /freshness, /annual   (exec_meeting_recruitment.py)
  /pipeline?weeks=8                            (exec_meeting_recruitment_pipeline.py)

Refusals (503, never a partial or misleading e-mail):
  * the Jobs portal has written nothing for PIPELINE_STALE_DAYS — a dead app
    would otherwise print a quiet week of zeros;
  * the stage vocabulary drifted (``unknown_stages``) — a renamed stage would
    silently drop out of every milestone count.
The IT ROUTE ticket feed (onboarding / offboarding) is secondary: when it is
stale the e-mail still goes, with a visible banner over those two rows.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import date, timedelta
from typing import Any, Optional

import httpx

from app.clock import cst_now, cst_today
from app.config import settings
from app.services.exec_recruitment_digest_html import render_html

logger = logging.getLogger(__name__)

API_PREFIX = "/api/custom/exec-meeting-recruitment"
EXEC_REPORT_URL = "https://space.unilinkportal.com/reports/exec-meeting-recruitment"
JOBS_REPORTS_URL = "https://jobs.unilinktransportation.com/dashboard/reports"

WEEKS = 8
PIPELINE_STALE_DAYS = 7
TICKETS_STALE_DAYS = 7


class DigestSourceError(RuntimeError):
    """A report endpoint failed — never render a partial e-mail."""


class DigestStaleError(DigestSourceError):
    """The Jobs portal stopped writing, or its stage vocabulary drifted."""


# One build at a time: an n8n retry overlapping a slow first attempt (or an
# admin preview) would otherwise double the load on the recruit pool.
_BUILD_LOCK = asyncio.Lock()


def _internal_headers() -> dict[str, str]:
    # Admin bypasses require_report_access (deps.py) -> the same SQL users hit.
    auth = (
        'Bearer {"sub":"recruitment-digest","email":"recruitment-digest@internal",'
        '"name":"recruitment-digest","roles":["admin"]}'
    )
    headers = {"authorization": auth}
    if settings.PROXY_SHARED_SECRET:
        headers["x-proxy-secret"] = settings.PROXY_SHARED_SECRET
    return headers


async def _get_many(app, calls: list[tuple[str, dict]]) -> list[dict]:
    """GET report endpoints concurrently, in process. Any failure RAISES."""
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    async with httpx.AsyncClient(
        transport=transport, base_url="http://recruitment-digest.internal",
        timeout=90.0,
    ) as client:
        results = await asyncio.gather(
            *[client.get(f"{API_PREFIX}{path}", params=params,
                         headers=_internal_headers())
              for path, params in calls],
            return_exceptions=True,
        )
    out: list[dict] = []
    for (path, params), res in zip(calls, results):
        if isinstance(res, BaseException):
            raise DigestSourceError(f"{path} {params} raised {res!r}")
        if res.status_code != 200:
            raise DigestSourceError(f"{path} {params} returned {res.status_code}")
        payload = res.json()
        if not payload.get("success"):
            raise DigestSourceError(f"{path} {params} returned success=false")
        out.append(payload)
    return out


# ---------------------------------------------------------------------------
# Guards + derived figures (pure, unit-tested)
# ---------------------------------------------------------------------------


def _days_old(iso: Optional[str], today: date) -> Optional[int]:
    if not iso:
        return None
    return (today - date.fromisoformat(iso[:10])).days


def assert_pipeline_usable(meta: dict, today: date) -> None:
    age = _days_old(meta.get("pipeline_as_of"), today)
    if age is None or age > PIPELINE_STALE_DAYS:
        raise DigestStaleError(
            f"Jobs portal last wrote {meta.get('pipeline_as_of')} — "
            f"more than {PIPELINE_STALE_DAYS} days ago"
        )
    if meta.get("unknown_stages"):
        raise DigestStaleError(
            f"unknown pipeline stages {meta['unknown_stages']} — milestone "
            "counts would silently drop them; extend DEFAULT_STAGE_ORDER"
        )


def tickets_stale(tickets_as_of: Optional[str], today: date) -> bool:
    age = _days_old(tickets_as_of, today)
    return age is None or age > TICKETS_STALE_DAYS


def subject_for(lw_monday: date) -> str:
    lw_sunday = lw_monday + timedelta(days=6)
    week_no = lw_monday.isocalendar()[1]
    return (f"Recruitment Status - Week {week_no} "
            f"({lw_monday.strftime('%b')} {lw_monday.day} - "
            f"{lw_sunday.strftime('%b')} {lw_sunday.day}, {lw_sunday.year})")


def join_roles(open_roles: list[dict], pipeline_roles: list[dict]) -> list[dict]:
    """Open-capacity rows (oldest first) enriched with their live pipeline.

    Keyed on Position.id from both endpoints — a role with nobody in the
    pipeline still prints, with zeros, because "no candidates" is the finding.
    """
    by_id = {r["position_id"]: r for r in pipeline_roles}
    empty = {"in_pipeline": 0, "sourcing": 0, "screening": 0, "interviews": 0,
             "final": 0, "new_last_week": 0, "valid_last_week": 0,
             "rejected_screening_last_week": 0, "rejected_later_last_week": 0,
             "furthest_stage": None}
    return [{**r, **by_id.get(r["id"], empty)} for r in open_roles]


AGED_DAYS = 60
DIVISION_ORDER = ("CORP", "DFW")
_SUMMED = ("active_candidates", "new_apps_lw", "screened_lw", "valid_lw", "rejected_lw",
           "rejected_screening_lw", "hires_ytd", "fill_days_sum", "fill_days_n")


def _finish(row: dict, days: list[int]) -> dict:
    """Derived columns. Averages are recomputed from the parts — never an
    average of department averages (a 1-role department would weigh as much
    as a 10-role one)."""
    n = row["fill_days_n"]
    return {
        **row,
        "open_roles": len(days),
        "avg_days_open": round(sum(days) / len(days)) if days else None,
        "oldest_days": max(days) if days else None,
        "over_60": sum(1 for d in days if d > AGED_DAYS),
        "avg_days_to_fill_ytd": round(row["fill_days_sum"] / n) if n else None,
    }


def division_table(open_roles: list[dict], dept_stats: list[dict]) -> list[dict]:
    """Rows: per division a SUBTOTAL, then its departments; a final TOTAL.

    Open-role figures come from /open-roles (the Exec page's own definition);
    candidate/hire figures from /pipeline's by_department. A department with
    open roles but no stats row (or the reverse) still prints.
    """
    from app.routers.exec_meeting_recruitment_pipeline import division_of

    zero = {k: 0 for k in _SUMMED}
    depts: dict[str, dict] = {d["department"]: {**zero, **d} for d in dept_stats}
    days_by_dept: dict[str, list[int]] = {}
    vac_by_dept: dict[str, int] = {}
    for r in open_roles:
        dept = r["department"]
        depts.setdefault(dept, {**zero, "department": dept, "division": division_of(dept)})
        days_by_dept.setdefault(dept, []).append(int(r["days_open"]))
        vac_by_dept[dept] = vac_by_dept.get(dept, 0) + int(r.get("open_vacancies") or 0)

    def leaf(dept: str) -> dict:
        return {**_finish(depts[dept], days_by_dept.get(dept, [])),
                "open_vacancies": vac_by_dept.get(dept, 0), "level": "department",
                "label": dept}

    def rollup(label: str, names: list[str], level: str) -> dict:
        summed = {k: sum(depts[n][k] for n in names) for k in _SUMMED}
        days = [d for n in names for d in days_by_dept.get(n, [])]
        return {**_finish(summed, days), "level": level, "label": label,
                "division": label if level == "division" else None,
                "open_vacancies": sum(vac_by_dept.get(n, 0) for n in names)}

    rows: list[dict] = []
    for division in DIVISION_ORDER:
        names = sorted((n for n, d in depts.items() if d["division"] == division),
                       key=lambda n: (not n.endswith("OPERATIONS"), n))
        if not names:
            continue
        rows.append(rollup(division, names, "division"))
        if len(names) > 1:
            # Departments with an open role get their own row; the rest fold into
            # ONE row (5 of 10 CORP departments had none on 2026-10-12 — listing
            # each was noise). Their numbers still count in the subtotal above.
            with_roles = [n for n in names if days_by_dept.get(n)]
            idle = [n for n in names if not days_by_dept.get(n)]
            rows.extend(leaf(n) for n in with_roles)
            if idle:
                rows.append({**rollup(f"Other departments ({len(idle)}, no open role)",
                                      idle, "department"), "division": division})
    rows.append(rollup("TOTAL", list(depts), "total"))
    return rows


def division_comparison(rows: list[dict]) -> Optional[str]:
    """One plain sentence comparing CORP and DFW, or None if either is missing."""
    div = {r["label"]: r for r in rows if r["level"] == "division"}
    corp, dfw = div.get("CORP"), div.get("DFW")
    if not corp or not dfw or not corp["avg_days_open"] or not dfw["avg_days_open"]:
        return None
    slow, fast = (corp, dfw) if corp["avg_days_open"] >= dfw["avg_days_open"] else (dfw, corp)
    ratio = slow["avg_days_open"] / fast["avg_days_open"]
    pace = (f"{ratio:.1f}× longer" if ratio >= 1.1 else "about as long")
    return (f"{slow['label']} roles have been open {pace} than {fast['label']} roles on "
            f"average ({slow['avg_days_open']} vs {fast['avg_days_open']} days); "
            f"CORP has {corp['open_roles']} open roles / {corp['open_vacancies']} vacancies, "
            f"DFW {dfw['open_roles']} / {dfw['open_vacancies']}.")


# ---------------------------------------------------------------------------
# Build
# ---------------------------------------------------------------------------


async def build_recruitment_digest(app) -> dict[str, Any]:
    async with _BUILD_LOCK:
        return await _build(app)


async def _build(app) -> dict[str, Any]:
    summary, open_roles, fresh = await _get_many(app, [
        ("/summary", {}),
        ("/open-roles", {}),
        ("/freshness", {}),
    ])
    pipe, annual = await _get_many(app, [
        ("/pipeline", {"weeks": WEEKS}),
        ("/annual", {}),
    ])

    today = cst_today()
    p = pipe["data"]
    assert_pipeline_usable(p["meta"], today)
    if len(p["weeks"]) != WEEKS:
        raise DigestSourceError(f"/pipeline returned {len(p['weeks'])} weeks, wanted {WEEKS}")

    lw = p["weeks"][0]
    lw_monday = date.fromisoformat(lw["week_start"])
    subject = subject_for(lw_monday)
    tickets_as_of = fresh["data"].get("tickets")
    generated = cst_now()

    roles = join_roles(open_roles["data"]["rows"], p["roles"])
    divisions = division_table(open_roles["data"]["rows"], p.get("by_department", []))
    html = render_html(
        subject=subject,
        summary=summary["data"],
        weeks=p["weeks"],
        snapshot=p["snapshot"],
        roles=roles,
        hires_last_week=p["hires_last_week"],
        annual=annual["data"],
        pipeline_as_of=p["meta"]["pipeline_as_of"],
        tickets_as_of=tickets_as_of,
        people_as_of=fresh["data"].get("people"),
        tickets_are_stale=tickets_stale(tickets_as_of, today),
        generated=generated,
        exec_report_url=EXEC_REPORT_URL,
        jobs_reports_url=JOBS_REPORTS_URL,
        ticket_totals=p.get("ticket_totals"),
        divisions=divisions,
        division_note=division_comparison(divisions),
    )
    return {
        "subject": subject,
        "html": html,
        "generatedAt": generated.isoformat(),
        "meta": {
            "week_no": lw_monday.isocalendar()[1],
            "last_week": {"start": lw["week_start"], "end": lw["week_end"]},
            "weeks": len(p["weeks"]),
            "pipeline_as_of": p["meta"]["pipeline_as_of"],
            "tickets_as_of": tickets_as_of,
            "open_roles": summary["data"]["open_roles"],
            "open_vacancies": summary["data"]["open_vacancies"],
            "active_candidates": p["snapshot"]["active_candidates"],
            "ticket_totals": p.get("ticket_totals"),
            "last_week_counts": {k: v for k, v in lw.items()
                                 if k not in ("week_start", "week_end")},
        },
    }
