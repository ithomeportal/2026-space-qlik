"""Hourly check: is the McLeod → gold load still WRITING v4 and movement? (§143)

Background
----------
On 2026-11-11 ``mcleod_gld_budget_report_v4`` stopped at 23:20 CST and
``mcleod_gld_movement`` at 22:28, while the n8n live feed
``app_augment_n8n_data_ra_rt`` kept moving (245 orders changed by 07:38).
Nothing watched v4's freshness: the only v4 check was the 06:25 status-lag mail
(``mirror_status_lag_monitor``), which reads once a day and called the freeze
"still skipping". Production, Hold, Division Payment, the PCA status mails and
the Ops portals all read v4.

This job (hourly 06:00–22:00 CST, SELECT-only) alerts Diego + CC the Data / BI
owner when a watched table has not been written for ``STALE_MINUTES`` **and**
McLeod recorded at least ``MIN_EVENTS`` pickups/deliveries after its last write
(live ``origin_/dest_actual_arrival``). Both tables are CHANGE-stamped, not
re-stamped every refresh, so silence alone is normal on a quiet night — real
stop events the table never received are not. Never the live ``updated_dt``:
n8n re-stamps a row on every GPS ping. Stop times are LOCAL to the stop (an
Eastern stop reads up to +1 h vs CST), so the count can run slightly high —
the 2 h window absorbs it. One mail per freeze (keyed on the table's last
stamp), one "resumed" mail when the table is written AND fresh again. The memory
is in-process (one uvicorn worker): a restart during a freeze repeats the STOPPED
mail once, and a restart that falls inside a freeze loses its "resumed" mail —
the 06:25 status check still reports any backlog. Never loses a freeze: the next
run re-detects it. ⚠ Not watched 22:40–06:40 (the 06:25 check covers the
night). ⚠ A FUTURE-stamped table (the 11-01 DST fingerprint) delays detection by
its skew — the 06:25 mail flags future stamps.

Never raises — log-and-swallow, like every watchdog in this package.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from app.datalake import pad_variants, sql_str_list
from app.services import v4_freshness_companions as companions
from app.services.allowed_domains import partition_recipients
from app.services.msgraph_mailer import send_notification

logger = logging.getLogger("uvicorn.error")

# v4 refreshes every 15 min; 2 h of silence while McLeod records stops = stopped.
STALE_MINUTES = 120
MIN_EVENTS = 5

V4_TABLE = "public.mcleod_gld_budget_report_v4"
MOVEMENT_TABLE = "public.mcleod_gld_movement"
LIVE_TABLE = "public.app_augment_n8n_data_ra_rt"
# The live feed holds US (TMS) orders only, so both "last write" stamps are measured
# on TMS too — an MX-only trickle must not hide a stopped US load (review 11-11).
_TMS = sql_str_list(pad_variants(("TMS",), width=4))

TO_RECIPIENTS: tuple[str, ...] = ("dfrodriguez@unilinktransportation.com",)
# Owner of the McLeod → gold load (Data / BI) — Omar Orozco, as in §143.
CC_RECIPIENTS: tuple[str, ...] = ("oorozco@unilinktransportation.com",)

MONO_STACK = "ui-monospace, SFMono-Regular, 'SF Mono', Menlo, Consolas, monospace"


@dataclass(frozen=True)
class Watched:
    name: str
    table: str
    last_col: str
    since_col: str


WATCHED: tuple[Watched, ...] = (
    Watched("v4", V4_TABLE, "v4_last", "events_since_v4"),
    Watched("movement", MOVEMENT_TABLE, "movement_last", "events_since_movement"),
)

# Gold stamps are naive CST, the live feed too; compared against the CST wall
# clock so the session timezone never matters. The counts are ORDERS with a
# pickup/delivery arrival after the table's last write, deleted rows excluded;
# the ``updated_dt`` bound only prunes the scan (−1 h: arrivals are stop-LOCAL).
# One scan of the live table per run — fine hourly, never per request.
_CST_NOW = "(now() AT TIME ZONE 'America/Chicago')"
_ARRIVED_AFTER = (
    "(r.origin_actual_arrival > COALESCE(t.{col}, '-infinity')"
    " OR r.dest_actual_arrival > COALESCE(t.{col}, '-infinity'))"
)
# MATERIALIZED: inlined, the planner re-ran each max() per reference — the
# movement max is an unindexed ~900 MB seq read (14 s measured 11-11, ~2 s now).
FRESHNESS_SQL = f"""
    WITH t AS MATERIALIZED (
        SELECT (SELECT max(updated_dt) FROM {V4_TABLE} WHERE company_id IN {_TMS}) AS v4_last,
               (SELECT max(updated_dt) FROM {MOVEMENT_TABLE} WHERE company_id IN {_TMS}) AS movement_last,
               (SELECT max(updated_dt) FROM {LIVE_TABLE})     AS live_last,
               {_CST_NOW} AS cst_now
    )
    SELECT t.*, c.events_since_v4, c.events_since_movement
    FROM t
    -- ONE scan of the live table for both counts (it is upsert-bloated).
    CROSS JOIN LATERAL (
        SELECT count(DISTINCT r.id) FILTER (
                   WHERE {_ARRIVED_AFTER.format(col="v4_last")})::int       AS events_since_v4,
               count(DISTINCT r.id) FILTER (
                   WHERE {_ARRIVED_AFTER.format(col="movement_last")})::int AS events_since_movement
        FROM {LIVE_TABLE} r
        WHERE r.updated_dt > LEAST(COALESCE(t.v4_last, '-infinity'),
                                   COALESCE(t.movement_last, '-infinity')) - interval '1 hour'
          AND NOT COALESCE(r.is_deleted, false)
    ) c
"""


@dataclass(frozen=True)
class TableLag:
    name: str
    table: str
    last: datetime | None
    age_s: int | None
    events_since: int


@dataclass
class AlertMemory:
    """Last stamp already alerted, per table — replaced, never mutated in place."""

    stamps: dict[str, datetime | None] = field(default_factory=dict)


_MEMORY = AlertMemory()


def age_text(secs: int) -> str:
    """95 min · 8 h 18 min · 2 d 1 h."""
    mins = secs // 60
    if mins < 120:
        return f"{mins} min"
    hours, rest = divmod(mins, 60)
    if hours < 48:
        return f"{hours} h {rest} min" if rest else f"{hours} h"
    days, hrs = divmod(hours, 24)
    return f"{days} d {hrs} h"


def _is_fresh(last: datetime | None, now: datetime) -> bool:
    """Written within STALE_MINUTES — one stray batch after a freeze is not a resume."""
    return last is not None and (now - last).total_seconds() <= STALE_MINUTES * 60


def stale_tables(row: Any) -> list[TableLag]:
    """Watched tables silent past ``STALE_MINUTES`` while McLeod recorded stops."""
    now = row["cst_now"]
    out = []
    for w in WATCHED:
        last = row[w.last_col]
        since = int(row[w.since_col] or 0)
        age = None if last is None else int((now - last).total_seconds())
        silent = age is None or age > STALE_MINUTES * 60
        if silent and since >= MIN_EVENTS:
            out.append(TableLag(w.name, w.table, last, age, since))
    return out


def _fmt(ts: datetime | None) -> str:
    return "never" if ts is None else f"{ts:%Y-%m-%d %H:%M}"


def _table_html(lags: list[TableLag], live_last: datetime | None) -> str:
    cell = "padding:4px 12px 4px 0;"
    head = "".join(
        f"<th style='{cell}text-align:left;color:#555;font-weight:500;'>{h}</th>"
        for h in ("table", "last write (CST)", "silent for", "orders picked up / delivered since")
    )
    body = "".join(
        f"<tr><td style='{cell}'>{t.table.removeprefix('public.')}</td><td style='{cell}'>{_fmt(t.last)}</td>"
        f"<td style='{cell}font-weight:600;'>{'—' if t.age_s is None else age_text(t.age_s)}</td>"
        f"<td style='{cell}'>{t.events_since}</td></tr>"
        for t in lags
    )
    return (
        f"<table style=\"border-collapse:collapse;font-family:{MONO_STACK};font-size:13px;\">"
        f"<tr>{head}</tr>{body}</table>"
        f"<p style='margin:8px 0 0;color:#555;font-size:13px;'>Live McLeod feed (n8n) last row: "
        f"{_fmt(live_last)} CST.</p>"
    )


def _stopped_html(lags: list[TableLag], live_last: datetime | None,
                  others: companions.Sweep | None = None) -> str:
    extra = "" if others is None else companions.section_html(others, _fmt, age_text)
    return f"""\
<div style="font-family:-apple-system,Segoe UI,Roboto,sans-serif;color:#1a1a1a;max-width:640px;">
  <h2 style="margin:0 0 8px;">⚠ Gold McLeod load STOPPED</h2>
  <p style="margin:0 0 12px;">The McLeod → gold load has not written these tables for over
    {age_text(STALE_MINUTES * 60)}, while McLeod recorded pickups and deliveries after their last
    write (live n8n feed) — so this is the load, not a quiet hour. Every McLeod change since the
    last write is missing from them.</p>
  {_table_html(lags, live_last)}
  {extra}
  <p style="margin:16px 0 0;color:#555;">Reports over these tables (Production, Hold,
    Division Payment, XRay, Podium, the Ops portals and the PCA status mails) show the last
    loaded state until Data / BI restarts the load; the Cover boards fall back to the live feed.</p>
  <p style="margin:16px 0 0;color:#888;font-size:12px;">Checked hourly 06:00–22:00 CST;
    one mail per freeze, plus one when writes resume. Owner of the McLeod → gold load:
    Data / BI. Rule: SPEC-CODE-RULES §143.</p>
</div>"""


def _resumed_html(names: list[str], row: Any) -> str:
    lines = "".join(
        f"<li>{w.table.removeprefix('public.')} — last write {_fmt(row[w.last_col])} CST</li>"
        for w in WATCHED if w.name in names
    )
    return f"""\
<div style="font-family:-apple-system,Segoe UI,Roboto,sans-serif;color:#1a1a1a;max-width:640px;">
  <h2 style="margin:0 0 8px;">✓ Gold McLeod load resumed</h2>
  <ul style="margin:0 0 12px;padding-left:18px;">{lines}</ul>
  <p style="margin:0;color:#555;">Changes made while it was stopped may still be missing —
    the 06:25 status check lists any order v4 still shows as A after McLeod moved it.</p>
</div>"""


async def _send(to, cc, subject: str, html: str) -> dict[str, Any]:
    to_list, blocked_to = partition_recipients([a for a in to if a])
    to_lower = {a.lower() for a in to_list}
    cc_list, blocked_cc = partition_recipients([a for a in cc if a and a.lower() not in to_lower])
    blocked = sorted(set(blocked_to) | set(blocked_cc))
    if blocked:
        logger.error("check_v4_freshness: dropped non-company recipients on: %s", ", ".join(blocked))
    if not to_list:
        return {"sent": False, "reason": "no_recipients"}
    # Notification → Microsoft Graph (Resend is login-OTP only). Never raises.
    return await send_notification(to=to_list, cc=cc_list or None, subject=subject, html_body=html)


async def check_v4_freshness(
    pool,
    *,
    to: Iterable[str] = TO_RECIPIENTS,
    cc: Iterable[str] = CC_RECIPIENTS,
    memory: AlertMemory | None = None,
) -> dict[str, Any]:
    """Alert once per freeze of v4 / movement; mail when it resumes. Never raises."""
    if pool is None:
        logger.warning("check_v4_freshness: savings_pool is None; skipping")
        return {"checked": False, "reason": "no_pool"}
    mem = _MEMORY if memory is None else memory
    try:
        row = await pool.fetchrow(FRESHNESS_SQL)
    except Exception as e:
        logger.exception("check_v4_freshness: query failed")
        return {"checked": False, "reason": "query_failed", "error": str(e)}

    to, cc = tuple(to), tuple(cc)
    lags = stale_tables(row)
    stale_names = {t.name for t in lags}
    stats = {"stale": sorted(stale_names), "v4_last": _fmt(row["v4_last"]),
             "movement_last": _fmt(row["movement_last"])}
    logger.info("check_v4_freshness: %s", stats)

    # Resumed = the table WROTE since the alert and is no longer stale — never just
    # "the live feed went quiet" while the table is still frozen.
    last_by_name = {w.name: row[w.last_col] for w in WATCHED}
    resumed = [n for n, stamp in mem.stamps.items()
               if n not in stale_names and last_by_name.get(n) != stamp
               and _is_fresh(last_by_name.get(n), row["cst_now"])]
    if resumed:
        result = await _send(to, cc, "[UNILINK Space] Gold McLeod load resumed — "
                             f"{', '.join(resumed)} written again", _resumed_html(resumed, row))
        if result.get("sent"):
            mem.stamps = {k: v for k, v in mem.stamps.items() if k not in resumed}
        else:
            logger.error("check_v4_freshness: resumed mail NOT sent (%s)", result.get("reason"))
    if not lags:
        return {"checked": True, "healthy": True, "resumed": resumed, **stats}

    if all(mem.stamps.get(t.name, "unset") == t.last for t in lags):
        return {"checked": True, "healthy": False, "alerted": False,
                "reason": "already_alerted", **stats}
    worst = next((t for t in lags if t.name == "v4"), lags[0])
    silent = "never written" if worst.age_s is None else f"not written for {age_text(worst.age_s)}"
    # Evidence for the reader only, read once per freeze (≈1 GB unindexed) — never the trigger.
    anchor = max((t.last for t in lags if t.last is not None), default=None)
    others = await companions.sweep(pool, anchor=anchor, now=row["cst_now"],
                                    fresh_s=STALE_MINUTES * 60)
    subject = (f"[UNILINK Space] Gold McLeod load STOPPED — {worst.name} {silent}"
               f"{companions.subject_suffix(others)}")
    result = await _send(to, cc, subject, _stopped_html(lags, row["live_last"], others))
    if not result.get("sent"):
        logger.error("check_v4_freshness: alert NOT sent (%s)", result.get("reason"))
        return {"checked": True, "healthy": False, "alerted": False,
                "reason": result.get("reason"), **stats}
    mem.stamps = {**mem.stamps, **{t.name: t.last for t in lags}}
    logger.info("check_v4_freshness: alert sent (%s)", ", ".join(sorted(stale_names)))
    return {"checked": True, "healthy": False, "alerted": True, **stats}
