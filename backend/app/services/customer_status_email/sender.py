"""Scheduled send of the customer load-status e-mails.

``run_slot`` is the APScheduler job body (fires at every hour in SEND_HOURS,
CST). Each due report is CLAIMED in ``customer_status_email_log`` before it is
built, so a container restart, a misfire replay or a second instance can never
mail the same report twice for one slot.

Failure semantics (cron-job-debug §5): each report is isolated, its outcome is
written to the log, and the run RAISES at the end if any report failed — a
per-item ``except: continue`` that returns normally is recorded as success.
A stale order feed fails the slot instead of mailing yesterday's status.

🛑 Routing: unless ``settings.CUSTOMER_STATUS_EMAIL_LIVE`` is set, every e-mail
goes to the TEST recipients in ``config`` (request 2026-10-20). Manual sends
from the admin endpoint ALWAYS use test routing. Live routing to
@packagingcorp.com would also be refused by the company-domain guard in
``msgraph_mailer`` today — going live needs that exemption decided first
(docs/SPEC-EMAIL-DOMAIN-POLICY.md).
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Optional

from app.clock import cst_now
from app.config import settings
from app.services.customer_status_email import cards as cards_mod
from app.services.customer_status_email import data
from app.services.customer_status_email.config import (
    REPORTS_BY_KEY,
    TEST_BCC,
    TEST_CC,
    SEND_HOURS,
    TEST_TO,
    CustomerReport,
    reports_due,
)
from app.services.customer_status_email.html import render, subject_for
from app.services.msgraph_mailer import send_mail

logger = logging.getLogger(__name__)

LOG_DDL = """
CREATE TABLE IF NOT EXISTS customer_status_email_log (
  report_key  TEXT        NOT NULL,
  slot_key    TEXT        NOT NULL,
  mode        TEXT        NOT NULL,
  status      TEXT        NOT NULL,
  counts      JSONB,
  subject     TEXT,
  recipients  JSONB,
  loads       JSONB,
  error       TEXT,
  claimed_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  finished_at TIMESTAMPTZ,
  PRIMARY KEY (report_key, slot_key)
)
"""

# A FAILED slot may be re-claimed (the :20 retry firing, or a manual re-run):
# 'failed' is only ever written when nothing was mailed (send_mail returned
# sent=False, or the build raised). A row stuck at 'sending' is NOT retaken —
# the mail may have left before the process died, and a duplicate to a
# customer is worse than a missing one.
CLAIM_SQL = """
INSERT INTO customer_status_email_log AS l (report_key, slot_key, mode, status)
VALUES ($1, $2, $3, 'sending')
ON CONFLICT (report_key, slot_key) DO UPDATE
  SET status = 'sending', mode = EXCLUDED.mode, error = NULL,
      claimed_at = NOW(), finished_at = NULL
  WHERE l.status = 'failed'
RETURNING report_key
"""

FINISH_SQL = """
UPDATE customer_status_email_log
SET status = $3, counts = $4::jsonb, error = $5, finished_at = NOW(),
    subject = $6, recipients = $7::jsonb, loads = $8::jsonb
WHERE report_key = $1 AND slot_key = $2
"""

# The Customer E-mail Activity panel reads this (routers/customer_status_email.py).
ACTIVITY_SQL = """
SELECT report_key, slot_key, mode, status, counts, subject, recipients, loads, error,
       to_char(claimed_at  AT TIME ZONE 'America/Chicago', 'YYYY-MM-DD"T"HH24:MI:SS') AS claimed_at,
       to_char(finished_at AT TIME ZONE 'America/Chicago', 'YYYY-MM-DD"T"HH24:MI:SS') AS finished_at
FROM customer_status_email_log
WHERE claimed_at >= NOW() - make_interval(days => $1)
  AND ($2::text IS NULL OR report_key = $2)
ORDER BY claimed_at DESC
LIMIT 1000
"""


class SlotRunError(RuntimeError):
    """At least one report of the slot failed; details are in the log table."""


@dataclass(frozen=True)
class Routing:
    to: tuple[str, ...]
    cc: tuple[str, ...]
    bcc: tuple[str, ...]
    mode: str  # "test" | "live"


def routing_for(report: CustomerReport, *, live: bool) -> Routing:
    if live:
        return Routing(to=report.to, cc=report.cc, bcc=(), mode="live")
    return Routing(to=TEST_TO, cc=TEST_CC, bcc=TEST_BCC, mode="test")


def test_banner(report: CustomerReport, routing: Routing) -> Optional[str]:
    if routing.mode != "test":
        return None
    return ("TEST — in production this e-mail goes to: " + ", ".join(report.to)
            + f" (CC {', '.join(report.cc)}). Sent to {', '.join(routing.to)} for review.")


def slot_hour(now_cst: datetime) -> int:
    """The send hour this firing belongs to.

    The trigger only fires at send hours, so a firing at a NON-send hour whose
    previous hour IS one is the DST spring-forward case: 02:00 CST does not
    exist that day and APScheduler fires at 03:00 — it is still the 02:00 slot.
    """
    hour = now_cst.hour
    # Chicago's spring-forward gap is always 02:00-03:00; nothing else remaps.
    if hour == 3 and 3 not in SEND_HOURS and 2 in SEND_HOURS:
        return 2
    return hour


def slot_key_for(now_cst: datetime) -> str:
    """One key per CST date + send hour — a DST repeat of 01:xx cannot double-send."""
    return f"{now_cst:%Y-%m-%d} {slot_hour(now_cst):02d}"


async def build_all(app: Any, now_cst: datetime) -> tuple[dict, list[str]]:
    """Read the datalake once and return the cards of all four reports."""
    gold = getattr(app.state, "savings_pool", None)
    if gold is None:
        raise RuntimeError("datalake gold pool (SAVINGS_DATABASE_URL) not configured")
    data.assert_fresh(await data.fetch_freshness(gold), now_cst)
    orders = await data.fetch_orders(gold, now_cst)
    details = await data.fetch_details(gold, getattr(app.state, "ap_pool", None), orders, now_cst)
    return cards_mod.assign(orders, details, now_cst)


def sent_record(rc: cards_mod.ReportCards, routing: Routing, slot_at: datetime) -> dict:
    """What the activity panel shows for one send: subject, recipients, load ids."""
    return {
        "subject": subject_for(rc, slot_at),
        "recipients": {"from": rc.report.send_from, "to": list(routing.to),
                       "cc": list(routing.cc), "bcc": list(routing.bcc)},
        "loads": {"in_progress": [c.order_id for c in rc.in_progress],
                  "scheduled": [c.order_id for c in rc.scheduled],
                  "delivered": [c.order_id for c in rc.delivered]},
    }


async def deliver(rc: cards_mod.ReportCards, routing: Routing, slot_at: datetime) -> dict:
    report = rc.report
    html = render(rc, slot_at, test_banner(report, routing))
    result = await send_mail(
        tenant_id=settings.MS_TENANT_ID,
        client_id=settings.MS_CLIENT_ID,
        client_secret=settings.MS_CLIENT_SECRET,
        from_address=report.send_from,
        to=list(routing.to),
        cc=list(routing.cc),
        bcc=list(routing.bcc),
        subject=subject_for(rc, slot_at),
        html_body=html,
    )
    if not result.get("sent"):
        raise RuntimeError(f"send failed: {result.get('reason')} {result.get('error', '')}".strip())
    return result


async def run_slot(app: Any, now_cst: Optional[datetime] = None) -> dict:
    """Send every report due this CST hour, once. Raises if any of them failed."""
    if not settings.CUSTOMER_STATUS_EMAIL_ENABLED:
        logger.warning("customer status emails disabled (CUSTOMER_STATUS_EMAIL_ENABLED=false)")
        return {"skipped": "disabled"}
    now_cst = now_cst or cst_now()
    if now_cst.tzinfo is None:
        raise ValueError("now_cst must be timezone-aware")
    due = reports_due(slot_hour(now_cst))
    if not due:
        return {"skipped": f"no report due at {now_cst.hour:02d}:00"}
    hub = getattr(app.state, "pool", None)
    if hub is None:
        # Without the log there is no send-once guarantee — refuse rather than risk duplicates.
        raise SlotRunError("analytics_hub pool unavailable; send-once log unusable")

    live = bool(settings.CUSTOMER_STATUS_EMAIL_LIVE)
    slot = slot_key_for(now_cst)
    mode = "live" if live else "test"
    claimed: list[CustomerReport] = []
    async with hub.acquire() as conn:
        for report in due:
            if await conn.fetchval(CLAIM_SQL, report.key, slot, mode):
                claimed.append(report)
    if not claimed:
        return {"skipped": f"slot {slot} already sent"}

    outcome: dict[str, str] = {}
    try:
        by_key, unmatched = await build_all(app, now_cst)
    except Exception as exc:
        await _finish_all(hub, claimed, slot, "failed", None, f"build: {exc}")
        logger.error("customer status emails %s: build failed: %s", slot, exc, exc_info=True)
        raise SlotRunError(f"slot {slot}: build failed: {exc}") from exc
    if unmatched:
        logger.warning("customer status emails: active CENTRATX/Waco consignees in no report: %s",
                       "; ".join(unmatched))

    for report in claimed:
        rc = by_key[report.key]
        routing = routing_for(report, live=live)
        record = sent_record(rc, routing, now_cst)
        try:
            await deliver(rc, routing, now_cst)
            await _finish(hub, report.key, slot, "sent", rc.counts(), None, record)
            outcome[report.key] = "sent"
        except Exception as exc:  # noqa: BLE001 — isolate; re-raised below
            logger.error("customer status email %s %s failed: %s", report.key, slot, exc)
            await _finish(hub, report.key, slot, "failed", rc.counts(), str(exc)[:500], record)
            outcome[report.key] = f"failed: {exc}"

    failed = {k: v for k, v in outcome.items() if v != "sent"}
    if failed:
        raise SlotRunError(f"slot {slot}: {len(failed)} report(s) failed: {failed}")
    return {"slot": slot, "mode": mode, "sent": sorted(outcome)}


async def send_test_now(app: Any, report_key: str) -> dict:
    """Admin 'send test now': ALWAYS test routing, logged as a manual slot."""
    report = REPORTS_BY_KEY[report_key]
    now_cst = cst_now()
    by_key, _ = await build_all(app, now_cst)
    rc = by_key[report.key]
    routing = routing_for(report, live=False)
    result = await deliver(rc, routing, now_cst)
    hub = getattr(app.state, "pool", None)
    if hub is not None:
        # The mail has LEFT — a log failure must not turn into a 500 that
        # invites the admin to send it again.
        slot = f"manual {now_cst.isoformat(timespec='seconds')}"
        try:
            async with hub.acquire() as conn:
                await conn.fetchval(CLAIM_SQL, report.key, slot, "manual")
            await _finish(hub, report.key, slot, "sent", rc.counts(), None,
                          sent_record(rc, routing, now_cst))
        except Exception as exc:  # noqa: BLE001
            logger.error("customer status email manual-send log failed: %s", exc)
    return {"report": report.key, "counts": rc.counts(), "to": list(result.get("to", []))}


async def _finish(hub: Any, key: str, slot: str, status: str,
                  counts: Optional[dict], error: Optional[str],
                  record: Optional[dict] = None) -> None:
    record = record or {}
    try:
        async with hub.acquire() as conn:
            await conn.execute(
                FINISH_SQL, key, slot, status,
                json.dumps(counts) if counts is not None else None, error,
                record.get("subject"),
                json.dumps(record["recipients"]) if "recipients" in record else None,
                json.dumps(record["loads"]) if "loads" in record else None,
            )
    except Exception as exc:  # noqa: BLE001 — the send outcome is already logged
        logger.error("customer status email log update failed (%s %s): %s", key, slot, exc)


async def _finish_all(hub: Any, reports: list[CustomerReport], slot: str, status: str,
                      counts: Optional[dict], error: Optional[str]) -> None:
    for report in reports:
        await _finish(hub, report.key, slot, status, counts, error)
