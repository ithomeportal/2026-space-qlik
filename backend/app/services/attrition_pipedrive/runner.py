"""Plan and execute the day's reactivation actions.

One ACTION per (team, customer, last_load_date, kind). ``last_load_date`` keys
the lapse: a customer that comes back and lapses again is a new episode and gets
a new deal; the same lapse is never acted on twice.

Send-once discipline (same as customer_status_email):
* an action is CLAIMED atomically before any Pipedrive write;
* ``failed`` is written only when nothing was written — the next run retakes it;
* ``mail_failed`` = the owner changed but the notice did not leave — the next
  run retries the MAIL only;
* a row stuck at ``running`` is never retaken (Pipedrive may have been written
  before the process died) — it is reported as a failure until a human clears it;
* a write whose outcome is UNKNOWN (timeout, 5xx) leaves the row ``running``
  with the ids it was writing — never ``failed``: a retake would find the deal
  already with Sales and report ``already_sales`` without ever mailing.
  Only a definite 4xx rejection of the in-flight write is ``failed``;
* an org created before a failure is stored on the row and reused on the retake
  (search is eventually consistent — a re-search can miss it and duplicate it);
* no exact org but exactly ONE similar one → the deal goes there and the org gets
  ``ID_McLeod`` (only if empty) — operator rule 2026-10-22. Several similar →
  ``held`` (nothing written, retaken every run) and listed in one notice to
  ``ATTRITION_PIPEDRIVE_ALERT_TO`` so a human sets ``ID_McLeod`` on the right org.

Each customer is isolated in its own try; the RUN raises after every customer
was attempted when any failed (cron-job-debug §4/§5), so APScheduler and the
run log record a failure, and the alert goes out.

``live=False`` runs the same plan READ-ONLY: Pipedrive reads, no claims, no
writes, no mail — the admin preview and the LIVE=false schedule.
"""
from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass, field
from datetime import date, datetime
from typing import Any, Optional

from app.clock import cst_now
from app.config import settings
from app.services.attrition_pipedrive import config as cfg
from app.services.attrition_pipedrive.candidates import (
    Candidate,
    assert_fresh,
    fetch_candidates,
)
from app.services.attrition_pipedrive.mail import body_for, subject_for
from app.services.attrition_pipedrive.pipedrive import (
    Deal,
    OrgMatch,
    PipedriveClient,
    PipedriveError,
    Placement,
    normalize_name,
)
from app.services.msgraph_mailer import send_mail

logger = logging.getLogger(__name__)

CREATE, REASSIGN = "create", "reassign"

LOG_DDL = """
CREATE TABLE IF NOT EXISTS attrition_pipedrive_log (
  team           TEXT        NOT NULL,
  customer       TEXT        NOT NULL,
  last_load_date DATE        NOT NULL,
  action         TEXT        NOT NULL,
  status         TEXT        NOT NULL,
  days_since     INT,
  org_id         BIGINT,
  deal_id        BIGINT,
  deal_title     TEXT,
  owner_from     BIGINT,
  owner_to       BIGINT,
  note           TEXT,
  error          TEXT,
  claimed_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  finished_at    TIMESTAMPTZ,
  PRIMARY KEY (team, customer, last_load_date, action)
);
CREATE TABLE IF NOT EXISTS attrition_pipedrive_runs (
  id          BIGSERIAL   PRIMARY KEY,
  run_date    DATE        NOT NULL,
  mode        TEXT        NOT NULL,
  status      TEXT        NOT NULL,
  counts      JSONB,
  error       TEXT,
  started_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  finished_at TIMESTAMPTZ
)
"""

# Retakes only a row on which nothing was written.
CLAIM_SQL = """
INSERT INTO attrition_pipedrive_log AS l
  (team, customer, last_load_date, action, status, days_since)
VALUES ($1, $2, $3, $4, 'running', $5)
ON CONFLICT (team, customer, last_load_date, action) DO UPDATE
  SET status = 'running', error = NULL, days_since = EXCLUDED.days_since,
      claimed_at = NOW(), finished_at = NULL
  WHERE l.status IN ('failed', 'held')
RETURNING action
"""

# The owner already changed; only the notice is retried.
CLAIM_MAIL_SQL = """
UPDATE attrition_pipedrive_log
   SET status = 'running', error = NULL, claimed_at = NOW(), finished_at = NULL
 WHERE team = $1 AND customer = $2 AND last_load_date = $3 AND action = 'reassign'
   AND status = 'mail_failed'
RETURNING deal_id, deal_title, owner_to
"""

FINISH_SQL = """
UPDATE attrition_pipedrive_log
   SET status = $5, org_id = COALESCE($6, org_id), deal_id = COALESCE($7, deal_id),
       deal_title = COALESCE($8, deal_title), owner_from = COALESCE($9, owner_from),
       owner_to = COALESCE($10, owner_to), note = $11, error = $12, finished_at = NOW()
 WHERE team = $1 AND customer = $2 AND last_load_date = $3 AND action = $4
"""

# Leaves the row 'running' (never retaken) but records what was being written.
STUCK_SQL = """
UPDATE attrition_pipedrive_log
   SET org_id = COALESCE($5, org_id), deal_id = COALESCE($6, deal_id), error = $7
 WHERE team = $1 AND customer = $2 AND last_load_date = $3 AND action = $4
"""

EXISTING_SQL = """
SELECT team, customer, last_load_date, action, status, deal_id, org_id
  FROM attrition_pipedrive_log
 WHERE last_load_date >= $1
"""

RUN_START_SQL = """
INSERT INTO attrition_pipedrive_runs (run_date, mode, status) VALUES ($1, $2, 'running')
RETURNING id
"""
RUN_FINISH_SQL = """
UPDATE attrition_pipedrive_runs SET status = $2, counts = $3::jsonb, error = $4, finished_at = NOW()
 WHERE id = $1
"""

LOG_SQL = """
SELECT team, customer, last_load_date, action, status, days_since, org_id, deal_id,
       deal_title, owner_from, owner_to, note, error, claimed_at, finished_at
  FROM attrition_pipedrive_log
 WHERE claimed_at >= NOW() - make_interval(days => $1)
 ORDER BY claimed_at DESC
"""
RUNS_SQL = """
SELECT id, run_date, mode, status, counts, error, started_at, finished_at
  FROM attrition_pipedrive_runs
 WHERE started_at >= NOW() - make_interval(days => $1)
 ORDER BY started_at DESC
"""
TODAY_RUNS_SQL = "SELECT status FROM attrition_pipedrive_runs WHERE run_date = $1"


class OrgHeld(Exception):
    """Several similar organizations — a human must pick one (set its ID_McLeod)."""

    def __init__(self, candidates: tuple[tuple[int, str], ...]):
        super().__init__("several similar organizations")
        self.candidates = candidates


class RunFailed(RuntimeError):
    """At least one customer failed (the others were committed)."""

    def __init__(self, message: str, result: "RunResult"):
        super().__init__(message)
        self.result = result


@dataclass
class Outcome:
    team: str
    customer: str
    action: str
    days_since: int
    last_load_date: str
    status: str
    deal_id: Optional[int] = None
    deal_title: Optional[str] = None
    org_id: Optional[int] = None
    owner: Optional[str] = None
    owner_from_id: Optional[int] = None
    note: str = ""
    error: Optional[str] = None
    # True while a Pipedrive WRITE is in flight — an exception then is ambiguous.
    write_in_flight: bool = False


@dataclass
class RunResult:
    mode: str
    today: str
    feed_as_of: Optional[str]
    outcomes: list[Outcome] = field(default_factory=list)
    skipped_teams: list[dict] = field(default_factory=list)

    def counts(self) -> dict[str, int]:
        out: dict[str, int] = {}
        for o in self.outcomes:
            out[f"{o.action}:{o.status}"] = out.get(f"{o.action}:{o.status}", 0) + 1
        if self.skipped_teams:
            out["skipped_no_routing"] = len(self.skipped_teams)
        return out

    @property
    def failures(self) -> list[Outcome]:
        return [o for o in self.outcomes if o.status in ("failed", "mail_failed", "stuck", "error")]

    def as_dict(self) -> dict[str, Any]:
        return {
            "mode": self.mode, "today": self.today, "feed_as_of": self.feed_as_of,
            "counts": self.counts(), "outcomes": [asdict(o) for o in self.outcomes],
            "skipped_teams": self.skipped_teams,
        }


# ---------------------------------------------------------------------------
# planning (pure)
# ---------------------------------------------------------------------------

def action_for(days: int) -> Optional[str]:
    if cfg.CREATE_MIN_DAYS <= days <= cfg.CREATE_MAX_DAYS:
        return CREATE
    if cfg.REASSIGN_MIN_DAYS <= days <= cfg.REASSIGN_MAX_DAYS:
        return REASSIGN
    return None


def latest_per_customer(cands: list[Candidate]) -> list[Candidate]:
    """One row per customer NAME: the team of its most recent load.

    The tab lists a customer once per team. A customer on two teams would
    otherwise get two deals (or be moved and mailed twice), and one that MOVED
    teams would look lapsed under the old team while trading under the new one.
    """
    best: dict[str, Candidate] = {}
    for c in sorted(cands, key=lambda x: (x.team, x.customer)):
        k = normalize_name(c.customer)
        if k not in best or c.last_load_date > best[k].last_load_date:
            best[k] = c
    return sorted(best.values(), key=lambda x: (x.team, x.customer))


def plan(cands: list[Candidate]) -> tuple[list[tuple[Candidate, str]], list[dict]]:
    """(candidate, action) pairs due today + the due customers no team routing covers."""
    due, skipped = [], []
    for c in latest_per_customer(cands):
        kind = action_for(c.days_since)
        if kind is None:
            continue
        if c.team not in cfg.ROUTING:
            skipped.append({"team": c.team, "customer": c.customer, "days_since": c.days_since,
                            "action": kind})
            continue
        due.append((c, kind))
    return due, skipped


def _key(team: str, customer: str, last: date, action: str) -> tuple:
    return (team, customer, last, action)


# ---------------------------------------------------------------------------
# execution
# ---------------------------------------------------------------------------

class _Ctx:
    def __init__(self, app, hub, pd: PipedriveClient, p: Placement, live: bool,
                 existing: dict[tuple, dict]):
        self.app, self.hub, self.pd, self.p, self.live = app, hub, pd, p, live
        self.existing = existing

    def name(self, user_id: Optional[int]) -> Optional[str]:
        return self.p.user_names.get(user_id) if user_id is not None else None


def _describe(m: OrgMatch) -> str:
    return ", ".join(f"'{n}' ({i})" for i, n in m.candidates)


async def _resolve_org(ctx: _Ctx, c: Candidate, o: Outcome) -> tuple[Optional[int], str]:
    """An existing org for the customer, or (None, '') when nothing similar exists.

    Raises OrgHeld when several similar orgs exist. On a ONE-similar match, writes
    ``ID_McLeod`` onto the org when it has none, so the next run matches by code.
    """
    prior = _prior_org(ctx, c, o.action)
    if prior is not None:
        return prior, ""
    m = await ctx.pd.find_org(ctx.p, c.customer, c.mcleod_ids)
    if m.how == "ambiguous":
        raise OrgHeld(m.candidates)
    if m.how != "similar":
        return m.org_id, ""
    code = c.mcleod_ids[0] if c.mcleod_ids else None
    note = f"matched similar org {_describe(m)}"
    if code and not m.mcleod_on_org:
        if not ctx.live:
            return m.org_id, f"{note}; would set ID_McLeod {code}"
        o.org_id, o.write_in_flight = m.org_id, True
        await ctx.pd.set_org_mcleod(ctx.p, m.org_id, code)
        o.write_in_flight = False
        note += f"; ID_McLeod {code} set"
    return m.org_id, note


def _held_note(c: Candidate, h: OrgHeld) -> str:
    code = c.mcleod_ids[0] if c.mcleod_ids else "none"
    return (f"McLeod {code}; several similar orgs: "
            f"{_describe(OrgMatch(None, 'ambiguous', h.candidates))}")


def _prior_org(ctx: _Ctx, c: Candidate, kind: str) -> Optional[int]:
    for k in (kind, CREATE):
        row = ctx.existing.get(_key(c.team, c.customer, c.last_load_date, k))
        if row and row.get("org_id"):
            return int(row["org_id"])
    return None


async def _org_for(ctx: _Ctx, c: Candidate, o: Outcome, owner_id: int) -> tuple[Optional[int], str]:
    org_id, note = await _resolve_org(ctx, c, o)
    if org_id is not None:
        return org_id, note
    if not ctx.live:
        return None, "would create organization"
    first = c.mcleod_ids[0] if c.mcleod_ids else None
    o.write_in_flight = True
    org_id = await ctx.pd.create_org(ctx.p, c.customer, owner_id, first)
    o.write_in_flight, o.org_id = False, org_id
    return org_id, "organization created"


async def _do_create(ctx: _Ctx, c: Candidate, o: Outcome) -> None:
    route = cfg.ROUTING[c.team]
    kam_id = ctx.p.users[route.kam.email]
    org_id, note = await _org_for(ctx, c, o, kam_id)
    o.org_id = org_id
    existing = await ctx.pd.open_reactivation_deal(ctx.p, org_id) if org_id else None
    if existing is not None:
        o.status, o.deal_id, o.deal_title = "adopted", existing.id, existing.title
        o.owner = ctx.name(existing.owner_id)
        o.note = "open REACTIVATION deal already exists — kept as is"
        return
    if not ctx.live:
        o.status, o.owner, o.deal_title = "would_create", route.kam.name, c.customer
        o.note = note
        return
    o.write_in_flight = True
    deal = await ctx.pd.create_deal(
        ctx.p, title=c.customer, org_id=org_id, owner_id=kam_id,
        mcleod_id=c.mcleod_ids[0] if c.mcleod_ids else None,
    )
    o.write_in_flight = False
    o.status, o.deal_id, o.deal_title, o.owner = "created", deal.id, deal.title, route.kam.name
    o.note = note


async def _deal_to_reassign(ctx: _Ctx, c: Candidate) -> tuple[Optional[Deal], Optional[int]]:
    tracked = ctx.existing.get(_key(c.team, c.customer, c.last_load_date, CREATE))
    if tracked and tracked.get("deal_id"):
        deal = await ctx.pd.get_deal(int(tracked["deal_id"]))
        if deal and deal.status == "open" and deal.pipeline_id == ctx.p.pipeline_id:
            return deal, deal.org_id
    org_id = _prior_org(ctx, c, REASSIGN)
    if org_id is None:
        m = await ctx.pd.find_org(ctx.p, c.customer, c.mcleod_ids)
        if m.how == "ambiguous":
            raise OrgHeld(m.candidates)
        org_id = m.org_id
    deal = await ctx.pd.open_reactivation_deal(ctx.p, org_id) if org_id else None
    return deal, org_id


async def _send_notice(c: Candidate, deal_title: str) -> dict:
    route = cfg.ROUTING[c.team]
    return await send_mail(
        tenant_id=settings.MS_TENANT_ID, client_id=settings.MS_CLIENT_ID,
        client_secret=settings.MS_CLIENT_SECRET, from_address=settings.MS_SEND_FROM,
        to=list(route.notify_to), cc=list(route.notify_cc),
        subject=subject_for(deal_title, route.sales.name),
        html_body=body_for(deal_title, route.sales.name),
    )


async def _do_reassign(ctx: _Ctx, c: Candidate, o: Outcome) -> None:
    route = cfg.ROUTING[c.team]
    sales_id = ctx.p.users[route.sales.email]
    deal, org_id = await _deal_to_reassign(ctx, c)
    o.org_id = org_id
    if deal is not None and deal.owner_id == sales_id:
        o.status, o.deal_id, o.deal_title, o.owner = "already_sales", deal.id, deal.title, route.sales.name
        o.note = "deal already owned by Sales — no change, no e-mail"
        return
    if not ctx.live:
        o.status, o.owner = "would_reassign", route.sales.name
        o.deal_id, o.deal_title = (deal.id, deal.title) if deal else (None, c.customer)
        o.note = (f"owner {ctx.name(deal.owner_id)} → {route.sales.name}; e-mail"
                  if deal else "no open deal — would create one owned by Sales; e-mail")
        return
    if deal is None:
        org_id, note = await _org_for(ctx, c, o, sales_id)
        o.org_id, o.write_in_flight = org_id, True
        deal = await ctx.pd.create_deal(
            ctx.p, title=c.customer, org_id=org_id, owner_id=sales_id,
            mcleod_id=c.mcleod_ids[0] if c.mcleod_ids else None,
        )
        o.note = "; ".join(x for x in (note, "deal created for Sales") if x)
    else:
        from_name = ctx.name(deal.owner_id)
        o.owner_from_id, o.deal_id, o.deal_title = deal.owner_id, deal.id, deal.title
        o.write_in_flight = True
        deal = await ctx.pd.set_owner(deal.id, sales_id)
        o.note = f"owner {from_name} → {route.sales.name}"
    o.write_in_flight = False
    o.deal_id, o.deal_title, o.owner = deal.id, deal.title, route.sales.name
    sent = await _send_notice(c, deal.title)
    o.status = "reassigned" if sent.get("sent") else "mail_failed"
    if not sent.get("sent"):
        o.error = f"notice not sent: {sent.get('reason')}"


async def _retry_mail(ctx: _Ctx, c: Candidate, o: Outcome) -> bool:
    """A reassignment whose notice failed: re-send the notice only. True if handled."""
    row = await ctx.hub.fetchrow(CLAIM_MAIL_SQL, c.team, c.customer, c.last_load_date)
    if row is None:
        return False
    o.deal_id, o.deal_title = row["deal_id"], row["deal_title"]
    o.owner = cfg.ROUTING[c.team].sales.name
    sent = await _send_notice(c, row["deal_title"] or c.customer)
    o.status = "reassigned" if sent.get("sent") else "mail_failed"
    o.note = "notice re-sent"
    o.error = None if sent.get("sent") else f"notice not sent: {sent.get('reason')}"
    return True


async def _finish(ctx: _Ctx, c: Candidate, o: Outcome) -> None:
    owner_to = ctx.p.users.get(
        (cfg.ROUTING[c.team].sales if o.action == REASSIGN else cfg.ROUTING[c.team].kam).email
    ) if o.status in ("created", "reassigned", "mail_failed") else None
    await ctx.hub.execute(
        FINISH_SQL, c.team, c.customer, c.last_load_date, o.action, o.status,
        o.org_id, o.deal_id, o.deal_title, o.owner_from_id, owner_to, o.note or None, o.error,
    )


async def _act(ctx: _Ctx, c: Candidate, kind: str) -> Outcome:
    o = Outcome(team=c.team, customer=c.customer, action=kind, days_since=c.days_since,
                last_load_date=c.last_load_date.isoformat(), status="pending")
    prior = ctx.existing.get(_key(c.team, c.customer, c.last_load_date, kind))
    if prior and prior["status"] == "running":
        o.status, o.error = "stuck", "claimed earlier and never finished — check Pipedrive, then clear the row"
        return o
    if prior and prior["status"] not in ("failed", "mail_failed", "held"):
        o.status, o.deal_id = "done_before", prior.get("deal_id")
        return o
    if not ctx.live:
        try:
            await (_do_create if kind == CREATE else _do_reassign)(ctx, c, o)
        except OrgHeld as h:
            o.status, o.note = "would_hold", _held_note(c, h)
        return o
    if prior and prior["status"] == "mail_failed":
        if await _retry_mail(ctx, c, o):
            await _finish(ctx, c, o)
        return o
    if await ctx.hub.fetchval(CLAIM_SQL, c.team, c.customer, c.last_load_date, kind,
                              c.days_since) is None:
        o.status = "done_before"
        return o
    try:
        await (_do_create if kind == CREATE else _do_reassign)(ctx, c, o)
    except OrgHeld as h:
        o.status, o.note = "held", _held_note(c, h)
    except Exception as e:  # noqa: BLE001 — isolate the customer; the run raises later
        o.error = f"{type(e).__name__}: {e}"[:500]
        logger.error("attrition→pipedrive %s %s/%s failed: %s", kind, c.team, c.customer, o.error)
        if o.write_in_flight and not _definitely_rejected(e):
            # Outcome unknown: keep 'running' (never retaken), record what was being written.
            o.status = "stuck"
            await ctx.hub.execute(STUCK_SQL, c.team, c.customer, c.last_load_date, kind,
                                  o.org_id, o.deal_id, o.error)
            return o
        o.status = "failed"
    await _finish(ctx, c, o)
    return o


def _definitely_rejected(e: Exception) -> bool:
    """A 4xx means Pipedrive refused the write — nothing was written by that call."""
    return isinstance(e, PipedriveError) and e.status is not None and 400 <= e.status < 500


async def run_daily(app, *, live: bool, record: bool = True,
                    now: Optional[datetime] = None) -> RunResult:
    """The 04:00 CST job (and, with ``live=False, record=False``, the admin preview)."""
    now = now or cst_now()
    today = now.date()
    mode = "live" if live else "dry_run"
    hub, gold = app.state.pool, app.state.savings_pool
    run_id = await hub.fetchval(RUN_START_SQL, today, mode) if record else None
    result = RunResult(mode=mode, today=today.isoformat(), feed_as_of=None)
    pd: Optional[PipedriveClient] = None
    try:
        result.feed_as_of = (await assert_fresh(gold, now)).isoformat()
        due, result.skipped_teams = plan(await fetch_candidates(gold, today))
        if due:
            floor = min(c.last_load_date for c, _ in due)
            existing = {
                _key(r["team"], r["customer"], r["last_load_date"], r["action"]): dict(r)
                for r in await hub.fetch(EXISTING_SQL, floor)
            }
            pd = PipedriveClient(settings.PIPEDRIVE_DOMAIN, settings.PIPEDRIVE_API_TOKEN)
            ctx = _Ctx(app, hub, pd, await pd.resolve(), live, existing)
            for c, kind in due:
                try:
                    result.outcomes.append(await _act(ctx, c, kind))
                except Exception as e:  # noqa: BLE001 — a DB/read error on one customer
                    logger.error("attrition→pipedrive %s %s/%s errored: %s", kind, c.team,
                                 c.customer, e, exc_info=True)
                    result.outcomes.append(Outcome(
                        team=c.team, customer=c.customer, action=kind, days_since=c.days_since,
                        last_load_date=c.last_load_date.isoformat(), status="error",
                        error=f"{type(e).__name__}: {e}"[:500],
                    ))
    except Exception as e:
        if run_id is not None:
            await hub.execute(RUN_FINISH_SQL, run_id, "failed", json.dumps(result.counts()),
                              f"{type(e).__name__}: {e}"[:1000])
        raise
    finally:
        if pd is not None:
            await pd.aclose()
    held = [o for o in result.outcomes if o.status == "held"]
    if held and live and record:
        try:
            sent = await send_alert(
                f"Attrition → Pipedrive: {len(held)} customer(s) need an organization picked",
                " | ".join(f"{o.team} {o.customer} — {o.note}" for o in held)
                + " — set ID_McLeod on the right Pipedrive org; the next 04:00 run creates the deal.",
            )
            if not sent.get("sent"):
                logger.error("held-customers notice not sent: %s", sent.get("reason"))
        except Exception as e:  # noqa: BLE001 — the notice must not fail the run
            logger.error("held-customers notice failed: %s", e)
    failures = result.failures
    if run_id is not None:
        await hub.execute(
            RUN_FINISH_SQL, run_id, "failed" if failures else ("ok" if live else "dry_run"),
            json.dumps(result.counts()),
            "; ".join(f"{o.team}/{o.customer}: {o.error}" for o in failures)[:1000] or None,
        )
    if failures:
        raise RunFailed(
            f"{len(failures)} of {len(result.outcomes)} actions failed: "
            + "; ".join(f"{o.action} {o.team}/{o.customer} [{o.status}] {o.error}" for o in failures),
            result,
        )
    return result


# ---------------------------------------------------------------------------
# alerting
# ---------------------------------------------------------------------------

def _alert_to() -> list[str]:
    return [a.strip() for a in settings.ATTRITION_PIPEDRIVE_ALERT_TO.split(",") if a.strip()]


async def send_alert(subject: str, detail: str) -> dict:
    from html import escape

    return await send_mail(
        tenant_id=settings.MS_TENANT_ID, client_id=settings.MS_CLIENT_ID,
        client_secret=settings.MS_CLIENT_SECRET, from_address=settings.MS_SEND_FROM,
        to=_alert_to(), subject=subject,
        html_body=f"<p>{escape(detail)}</p><p>Log: GET /api/custom/attrition-pipedrive/log</p>",
    )


async def watch_today(app, now: Optional[datetime] = None) -> dict:
    """At 05:00 CST: alert if today's 04:00 run never finished (or never ran)."""
    now = now or cst_now()
    statuses = [r["status"] for r in await app.state.pool.fetch(TODAY_RUNS_SQL, now.date())]
    if any(s in ("ok", "dry_run", "failed") for s in statuses):
        return {"ok": True, "statuses": statuses}
    detail = (f"No finished Attrition → Pipedrive run for {now.date()} "
              f"(runs today: {statuses or 'none'}). The 04:00 CST job did not complete.")
    sent = await send_alert("⚠ Attrition → Pipedrive did not run today", detail)
    if not sent.get("sent"):
        raise RuntimeError(f"watch alert not sent: {sent.get('reason')}")
    return {"ok": False, "statuses": statuses, "alerted": True}
