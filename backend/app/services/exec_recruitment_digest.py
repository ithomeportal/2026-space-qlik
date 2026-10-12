"""Weekly "Recruitment Status" e-mail digest (data layer).

Requested 2026-10-12: a recruitment status report to Erick Mendoza (CEO) and
Daniela Nava (HR Director), Bcc dfrodriguez, every Monday 16:00 CST, built from
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
             "furthest_stage": None}
    return [{**r, **by_id.get(r["id"], empty)} for r in open_roles]


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
