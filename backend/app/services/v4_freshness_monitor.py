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

v6 (2026-11-11 16:30): the afternoon stop came back PARTLY — v4, movement and
cashflow wrote again ~16:00 while ``orders_pu_del_windows`` (Hold board) and
``customer_windows`` (DPC delivery month, Ops portals, PCA mails) stayed at
12:41 / 13:18. Watching v4 + movement alone would have called that "resumed".
Both are now WATCHED with the same evidence rule (each re-stamps on a McLeod
arrival: 41/41 and 37/41 orders measured 11-11), each freezes and resumes on
its own, and the resumed mail names whatever is still stopped. The alert memory
now lives in the hub DB (``v4_freshness_state``) so a deploy inside a freeze
neither repeats the STOPPED mail nor loses the resumed one.

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
from app.services import v4_freshness_state as state
from app.services.allowed_domains import partition_recipients
from app.services.msgraph_mailer import send_notification

logger = logging.getLogger("uvicorn.error")

# v4 refreshes every 15 min; 2 h of silence while McLeod records stops = stopped.
STALE_MINUTES = 120
MIN_EVENTS = 5

V4_TABLE = "public.mcleod_gld_budget_report_v4"
MOVEMENT_TABLE = "public.mcleod_gld_movement"
CUSTOMER_WINDOWS_TABLE = "public.mcleod_gld_customer_windows"
PU_DEL_WINDOWS_TABLE = "public.mcleod_gld_orders_pu_del_windows"
LIVE_TABLE = "public.app_augment_n8n_data_ra_rt"
# The live feed holds US (TMS) orders only, so both "last write" stamps are measured
# on TMS too — an MX-only trickle must not hide a stopped US load (review 11-11).
_TMS = sql_str_list(pad_variants(("TMS",), width=4))

TO_RECIPIENTS: tuple[str, ...] = ("dfrodriguez@unilinktransportation.com",)
# Owner of the McLeod → gold load (Data / BI) — Omar Orozco, as in §143 — and
# Daniela Castro (owner request 11-11). Both verified in Entra 2026-11-11.
CC_RECIPIENTS: tuple[str, ...] = (
    "oorozco@unilinktransportation.com",
    "dcastrog@unilinktransportation.com",
)
# While a freeze lasts, Data / BI is re-notified every REMIND_HOURS (owner 11-11).
REMIND_TO: tuple[str, ...] = ("oorozco@unilinktransportation.com",)
REMIND_HOURS = 6

STUCK_TIMEOUT_S = 30.0

MONO_STACK = "ui-monospace, SFMono-Regular, 'SF Mono', Menlo, Consolas, monospace"


@dataclass(frozen=True)
class Watched:
    name: str
    table: str
    last_col: str
    since_col: str
    read_by: str


# Every one is CHANGE-stamped and re-stamped when McLeod records a stop arrival,
# so "silent while ≥ MIN_EVENTS arrivals happened" means the load, not a quiet
# hour. Readers verified by grep of app/ 2026-11-11.
WATCHED: tuple[Watched, ...] = (
    Watched("v4", V4_TABLE, "v4_last", "events_since_v4",
            "Production, Division Payment, XRay, Podium, the Ops portals, PCA status mails"),
    Watched("movement", MOVEMENT_TABLE, "movement_last", "events_since_movement",
            "the Ops portals, XRay, Podium, Admin Aging, PCA status mails"),
    Watched("customer_windows", CUSTOMER_WINDOWS_TABLE, "customer_windows_last",
            "events_since_customer_windows",
            "Division Payment (delivery month), the Ops portals, PCA status mails"),
    Watched("pu_del_windows", PU_DEL_WINDOWS_TABLE, "pu_del_windows_last",
            "events_since_pu_del_windows", "the Ops portal Hold board"),
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
# customer_windows / pu_del_windows max() = 0.3–0.5 s each, unindexed (measured 11-11).
_LASTS = ",\n               ".join(
    f"(SELECT max(updated_dt) FROM {w.table} WHERE company_id IN {_TMS}) AS {w.last_col}"
    for w in WATCHED
)
_COUNTS = ",\n               ".join(
    f"count(DISTINCT r.id) FILTER (WHERE {_ARRIVED_AFTER.format(col=w.last_col)})::int"
    f" AS {w.since_col}"
    for w in WATCHED
)
_LEAST = ", ".join(f"COALESCE(t.{w.last_col}, '-infinity')" for w in WATCHED)
FRESHNESS_SQL = f"""
    WITH t AS MATERIALIZED (
        SELECT {_LASTS},
               (SELECT max(updated_dt) FROM {LIVE_TABLE})     AS live_last,
               {_CST_NOW} AS cst_now
    )
    SELECT t.*, {", ".join(f"c.{w.since_col}" for w in WATCHED)}
    FROM t
    -- ONE scan of the live table for every count (it is upsert-bloated).
    CROSS JOIN LATERAL (
        SELECT {_COUNTS}
        FROM {LIVE_TABLE} r
        WHERE r.updated_dt > LEAST({_LEAST}) - interval '1 hour'
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
    read_by: str = ""


@dataclass
class AlertMemory:
    """Last stamp already alerted, per table, and when the last STOPPED/reminder
    mail went out (CST) — fields replaced, never mutated in place."""

    stamps: dict[str, datetime | None] = field(default_factory=dict)
    sent_at: datetime | None = None


_MEMORY = AlertMemory()


@dataclass
class HubSync:
    """``dirty`` = the last save to the hub failed, so the hub row is OLDER than the
    in-process memory and must not be loaded over it (review 11-11: a working load
    + failing save re-sent the STOPPED mail every hour)."""

    dirty: bool = False


_SYNC = HubSync()


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
            out.append(TableLag(w.name, w.table, last, age, since, w.read_by))
    return out


def _fmt(ts: datetime | None) -> str:
    return "never" if ts is None else f"{ts:%Y-%m-%d %H:%M}"


def _table_html(lags: list[TableLag], live_last: datetime | None) -> str:
    cell = "padding:4px 12px 4px 0;"
    head = "".join(
        f"<th style='{cell}text-align:left;color:#555;font-weight:500;'>{h}</th>"
        for h in ("table", "last write (CST)", "silent for", "orders picked up / delivered since",
                  "read by")
    )
    body = "".join(
        f"<tr><td style='{cell}'>{t.table.removeprefix('public.')}</td><td style='{cell}'>{_fmt(t.last)}</td>"
        f"<td style='{cell}font-weight:600;'>{'—' if t.age_s is None else age_text(t.age_s)}</td>"
        f"<td style='{cell}'>{t.events_since}</td>"
        f"<td style='{cell}font-family:-apple-system,Segoe UI,Roboto,sans-serif;'>{t.read_by}</td></tr>"
        for t in lags
    )
    return (
        f"<table style=\"border-collapse:collapse;font-family:{MONO_STACK};font-size:13px;\">"
        f"<tr>{head}</tr>{body}</table>"
        f"<p style='margin:8px 0 0;color:#555;font-size:13px;'>Live McLeod feed (n8n) last row: "
        f"{_fmt(live_last)} CST.</p>"
    )


def _stopped_html(lags: list[TableLag], live_last: datetime | None,
                  others: companions.Sweep | None = None, reminder: bool = False) -> str:
    extra = "" if others is None else companions.section_html(others, _fmt, age_text)
    title = "⚠ Gold McLeod load STILL STOPPED" if reminder else "⚠ Gold McLeod load STOPPED"
    note = (f"<p style='margin:0 0 12px;font-weight:600;'>Reminder — sent every {REMIND_HOURS} h "
            "while the load stays stopped.</p>") if reminder else ""
    return f"""\
<div style="font-family:-apple-system,Segoe UI,Roboto,sans-serif;color:#1a1a1a;max-width:640px;">
  <h2 style="margin:0 0 8px;">{title}</h2>
  {note}
  <p style="margin:0 0 12px;">The McLeod → gold load has not written these tables for over
    {age_text(STALE_MINUTES * 60)}, while McLeod recorded pickups and deliveries after their last
    write (live n8n feed) — so this is the load, not a quiet hour. Every McLeod change since the
    last write is missing from them.</p>
  {_table_html(lags, live_last)}
  {extra}
  <p style="margin:16px 0 0;color:#555;">The reports over these tables show the last
    loaded state until Data / BI restarts the load; the Cover boards fall back to the live feed.
    Each table resumes on its own — the "resumed" mail names any that are still stopped.</p>
  <p style="margin:16px 0 0;color:#888;font-size:12px;">Checked hourly 06:00–22:00 CST;
    one mail per freeze, plus one when writes resume. Owner of the McLeod → gold load:
    Data / BI. Rule: SPEC-CODE-RULES §143.</p>
</div>"""


def _stuck_line(stuck: int | None) -> str:
    if stuck is None:
        return ("Orders v4 still shows as A after McLeod moved them could not be counted "
                "just now — the 06:25 status check lists them.")
    if stuck == 0:
        return "No order is stuck at A past the 3 h grace — nothing was left behind."
    return (f"<b>{stuck} orders</b> are still A in v4 although McLeod already moved them "
            "(past the 3 h grace) — the 06:25 status check lists them if they stay.")


async def _count_stuck(pool) -> int | None:
    """Orders v4 still calls A that McLeod moved — the 06:25 check's own SQL, once."""
    from app.services.mirror_status_lag_monitor import LAG_SQL  # imports this module

    try:
        return len(await pool.fetch(LAG_SQL, 0, timeout=STUCK_TIMEOUT_S))
    except Exception:
        logger.exception("check_v4_freshness: stuck-order count failed")
        return None


def _still_stopped_html(still: list[TableLag]) -> str:
    """A PARTIAL resume (11-11 16:00: v4 back, Hold board + delivery windows not)."""
    if not still:
        return ""
    items = "".join(
        f"<li><b>{t.table.removeprefix('public.')}</b> — last write {_fmt(t.last)} CST, "
        f"{t.events_since} orders picked up / delivered since; read by {t.read_by}</li>"
        for t in still
    )
    return ("<p style='margin:12px 0 4px;font-weight:600;'>⚠ Only a partial resume — still "
            f"stopped:</p><ul style='margin:0 0 12px;padding-left:18px;'>{items}</ul>")


def _resumed_html(names: list[str], row: Any, stuck: int | None = None,
                  still: list[TableLag] | None = None) -> str:
    lines = "".join(
        f"<li>{w.table.removeprefix('public.')} — last write {_fmt(row[w.last_col])} CST</li>"
        for w in WATCHED if w.name in names
    )
    title = "Gold McLeod load partly resumed" if still else "✓ Gold McLeod load resumed"
    return f"""\
<div style="font-family:-apple-system,Segoe UI,Roboto,sans-serif;color:#1a1a1a;max-width:640px;">
  <h2 style="margin:0 0 8px;">{title}</h2>
  <ul style="margin:0 0 12px;padding-left:18px;">{lines}</ul>
  {_still_stopped_html(still or [])}
  <p style="margin:0;color:#555;">{_stuck_line(stuck)}</p>
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
    remind_to: Iterable[str] = REMIND_TO,
    memory: AlertMemory | None = None,
    hub_pool=None,
    sync: HubSync | None = None,
) -> dict[str, Any]:
    """Alert once per freeze of a WATCHED table, remind every REMIND_HOURS while it
    lasts, mail when it resumes. The memory is read from / written to the hub
    (``hub_pool``) so it survives a deploy; ``memory`` is the in-process
    fallback. Never raises."""
    if pool is None:
        logger.warning("check_v4_freshness: savings_pool is None; skipping")
        return {"checked": False, "reason": "no_pool"}
    mem = _MEMORY if memory is None else memory
    hub = _SYNC if sync is None else sync
    loaded = None if hub.dirty else await state.load(hub_pool)
    if loaded is not None:
        mem.stamps, mem.sent_at = loaded
    before = (dict(mem.stamps), mem.sent_at)
    result = await _check(pool, mem, tuple(to), tuple(cc), tuple(remind_to))
    if hub_pool is not None and (hub.dirty or (mem.stamps, mem.sent_at) != before):
        hub.dirty = not await state.save(hub_pool, mem)
    return result


async def _check(pool, mem: AlertMemory, to: tuple[str, ...], cc: tuple[str, ...],
                 remind_to: tuple[str, ...]) -> dict[str, Any]:
    try:
        row = await pool.fetchrow(FRESHNESS_SQL)
    except Exception as e:
        logger.exception("check_v4_freshness: query failed")
        return {"checked": False, "reason": "query_failed", "error": str(e)}

    lags = stale_tables(row)
    stale_names = {t.name for t in lags}
    stats = {"stale": sorted(stale_names), "v4_last": _fmt(row["v4_last"]),
             "movement_last": _fmt(row["movement_last"])}
    logger.info("check_v4_freshness: %s", stats)

    resumed = await _maybe_resumed(pool, mem, row, lags, to, cc)
    stats = {**stats, "resumed": resumed}
    if not lags:
        return {"checked": True, "healthy": True, **stats}

    now = row["cst_now"]
    reminder = all(mem.stamps.get(t.name, "unset") == t.last for t in lags)
    if reminder and not _reminder_due(mem.sent_at, now):
        return {"checked": True, "healthy": False, "alerted": False,
                "reason": "already_alerted", **stats}
    if reminder:
        # Owner request 11-11: Data / BI is the addressee of a reminder.
        to, cc = tuple(remind_to), tuple(dict.fromkeys((*to, *cc)))
    result = await _send_stopped(pool, lags, row, to, cc, reminder)
    if not result.get("sent"):
        logger.error("check_v4_freshness: alert NOT sent (%s)", result.get("reason"))
        return {"checked": True, "healthy": False, "alerted": False,
                "reason": result.get("reason"), **stats}
    mem.stamps = {**mem.stamps, **{t.name: t.last for t in lags}}
    mem.sent_at = now
    logger.info("check_v4_freshness: %s sent (%s)", "reminder" if reminder else "alert",
                ", ".join(sorted(stale_names)))
    return {"checked": True, "healthy": False, "alerted": True, "reminder": reminder, **stats}


def _reminder_due(sent_at: datetime | None, now: datetime) -> bool:
    # sent_at None = remembered without a send time (restart semantics) → remind now.
    return sent_at is None or (now - sent_at).total_seconds() >= REMIND_HOURS * 3600


async def _send_stopped(pool, lags: list[TableLag], row: Any, to, cc,
                        reminder: bool) -> dict[str, Any]:
    worst = next((t for t in lags if t.name == "v4"), lags[0])
    silent = "never written" if worst.age_s is None else f"not written for {age_text(worst.age_s)}"
    # Evidence for the reader only, read once per mail (≈1 GB unindexed) — never the trigger.
    anchor = max((t.last for t in lags if t.last is not None), default=None)
    others = await companions.sweep(pool, anchor=anchor, now=row["cst_now"],
                                    fresh_s=STALE_MINUTES * 60)
    state = "STILL STOPPED" if reminder else "STOPPED"
    subject = (f"[UNILINK Space] Gold McLeod load {state} — {worst.name} {silent}"
               f"{companions.subject_suffix(others)}")
    return await _send(to, cc, subject,
                       _stopped_html(lags, row["live_last"], others, reminder=reminder))


async def _maybe_resumed(pool, mem: AlertMemory, row: Any, lags: list[TableLag],
                         to, cc) -> list[str]:
    """Resumed = the table WROTE since the alert and is no longer stale — never just
    "the live feed went quiet" while the table is still frozen. Per table: the
    ones still stale are named in the mail (a partial resume)."""
    stale_names = {t.name for t in lags}
    last_by_name = {w.name: row[w.last_col] for w in WATCHED}
    resumed = [n for n, stamp in mem.stamps.items()
               if n not in stale_names and last_by_name.get(n) != stamp
               and _is_fresh(last_by_name.get(n), row["cst_now"])]
    if not resumed:
        return resumed
    stuck = await _count_stuck(pool)
    partly = f" — still stopped: {', '.join(t.name for t in lags)}" if lags else ""
    result = await _send(to, cc, f"[UNILINK Space] Gold McLeod load {'partly ' if lags else ''}"
                         f"resumed — {', '.join(resumed)} written again{partly}",
                         _resumed_html(resumed, row, stuck, still=lags))
    if result.get("sent"):
        known = {t.name: t.last for t in lags if mem.stamps.get(t.name, "unset") == t.last}
        mem.stamps = {k: v for k, v in mem.stamps.items() if k not in resumed}
        if known:
            # The partial-resume mail named the tables still stopped: for those
            # ALREADY alerted it is their notice — no reminder in the same run. A
            # table stale for the FIRST time still gets its own STOPPED mail
            # (review 11-11: it must never be announced only as "resumed").
            mem.sent_at = row["cst_now"]
        if not mem.stamps:
            mem.sent_at = None
    else:
        logger.error("check_v4_freshness: resumed mail NOT sent (%s)", result.get("reason"))
    return resumed
