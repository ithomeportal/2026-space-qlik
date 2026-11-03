"""Daily check: does the gold McLeod mirror still follow McLeod's order status?

Background (§143)
-----------------
From the DST fall-back of 2026-11-01 the gold McLeod ETL missed a large share
of order/stop changes: its stamps ran +1 h against McLeod's and
``mcleod_gld_budget_report_v4`` kept ``status='A'`` on loads McLeod had already
moved to ``P`` (55 of the 85 pickups of 11-02). ``max(updated_dt)`` stayed
fresh, so every freshness check read healthy — Jaime Anaya found it by hand.

The n8n live feed ``app_augment_n8n_data_ra_rt`` (same DB) carries McLeod's own
``order_status`` minutes after a change. This job (daily, SELECT-only) counts
v4 ``status='A'`` orders that the live feed reports as P/D/V (its LATEST row)
and that v4 has not rewritten for ``GRACE_HOURS`` — normal ETL lag is far
shorter — and mails Diego + the Data / BI owner of the load when that count
exceeds ``THRESHOLD``. The Cover boards already hide such loads
(``ops_portal_overview/_live_status.py``); Production / Hold / DPC / the PCA
mails still read v4, so the ETL owner (Data / BI) must re-sync.

v2 (2026-11-03) — the mail is escalation EVIDENCE, not just a count:

* **Per-day table** — orders McLeod moved (latest live P/D/V) per EVENT day —
  pickup arrival for P, delivery arrival for D, ``updated_dt`` for V. Never the
  live ``updated_dt`` for P/D: n8n re-stamps the row after the move (213 of 276
  P rows on 11-03 carried a later day than their pickup). Columns: moved / still
  ``A`` in v4 past the grace / missing from v4.
* **Verdict** — over a ROLLING 24 h of events (at 06:25 "today" is a few
  overnight hours): "STILL SKIPPING" + the latest skipped change, vs "backlog
  only" (fixed, re-sync still owed). Re-sending the same count daily said neither.
* **v4 clock offset** — ``max(updated_dt)`` minus CST now. v4 refreshes every
  15 min, so a stamp in the FUTURE is the DST fingerprint (+1 h on 11-03).
* **Grace on real time** — v4's stamps ran +1 h, so ``updated_dt < now() - 3 h``
  really waited 4 h. The measured positive offset (clamped) is added back.

Never raises — log-and-swallow, exactly like ``revenue_code_monitor``. The
offset and per-day queries are optional extras: if they fail the alert still
goes out with the count alone.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable
from typing import Any

from app.clock import CST_NOW_DATE_SQL, cst_today
from app.datalake import pad_variants, sql_str_list
from app.services.allowed_domains import partition_recipients
from app.services.msgraph_mailer import send_notification

logger = logging.getLogger("uvicorn.error")

THRESHOLD = 5
GRACE_HOURS = 3
LOOKBACK_DAYS = 45
SAMPLE_IDS = 12
# Per-day evidence window, the verdict's rolling window, and the age an event
# needs before v4 "should" have it (v4 refreshes every 15 min; stop times are
# LOCAL to the stop, so an Eastern stop reads up to +1 h vs CST).
TREND_DAYS = 7
VERDICT_HOURS = 24
SETTLE_MINUTES = 90
# v4 stamps more than this far in the future = wrong clock, not ETL timing.
OFFSET_ALERT_SECONDS = 15 * 60
# Cap on the offset added back to the grace: the DST fingerprint is +60 min, so
# 90 min covers it while a garbage future stamp still leaves >= 90 min of grace.
MAX_OFFSET_SECONDS = 90 * 60
LIVE_TABLE = "public.app_augment_n8n_data_ra_rt"
V4_TABLE = "public.mcleod_gld_budget_report_v4"
# The live feed holds US (TMS) orders only.
COMPANIES = ("TMS",)
MOVED_STATUSES = ("P", "D", "V")

TO_RECIPIENTS: tuple[str, ...] = ("dfrodriguez@unilinktransportation.com",)
# Owner of the McLeod → gold load (Data / BI) — Omar Orozco, added 2026-11-03.
CC_RECIPIENTS: tuple[str, ...] = ("oorozco@unilinktransportation.com",)

MONO_STACK = "ui-monospace, SFMono-Regular, 'SF Mono', Menlo, Consolas, monospace"

_COMPANIES = sql_str_list(pad_variants(COMPANIES, width=4))
_STATUS_A = sql_str_list(pad_variants(("A",), width=1))
_MOVED = sql_str_list(MOVED_STATUSES)
_CST_NOW = "(now() AT TIME ZONE 'America/Chicago')"
# v4 untouched for GRACE_HOURS of real time; $1 = the clamped v4 clock offset.
_GRACE_BOUND = f"{_CST_NOW} - interval '{GRACE_HOURS} hours' + make_interval(secs => $1::int)"

# Naive CST stamps (gold) vs CST wall clock — session-timezone independent.
# Measured on the same companies the check reads.
OFFSET_SQL = f"""
    SELECT EXTRACT(EPOCH FROM (max(v.updated_dt) - {_CST_NOW}))::int AS offset_s
    FROM {V4_TABLE} v
    WHERE v.company_id IN {_COMPANIES}
"""

# Uncorrelated hashed IN-set (§135); the live side is ~28k rows, v4 status='A'
# a few hundred — one small scan each, once a day. $1 = the measured positive
# v4 clock offset in seconds (0 when unknown).
LAG_SQL = f"""
    SELECT a.id, l.order_status, l.updated_dt AS live_updated
    FROM (
        -- One row per v4 order; grace = v4 has not touched the order for
        -- GRACE_HOURS of REAL time (the live row is re-stamped constantly by
        -- GPS updates, so its own updated_dt cannot measure how long v4 lagged).
        SELECT DISTINCT ON (TRIM(v.company_id), TRIM(v.id))
               TRIM(v.company_id) AS co, TRIM(v.id) AS id
        FROM {V4_TABLE} v
        WHERE v.company_id IN {_COMPANIES}
          AND v.status IN {_STATUS_A}
          AND v.updated_dt < {_GRACE_BOUND}
        ORDER BY TRIM(v.company_id), TRIM(v.id)
    ) a
    JOIN (
        -- The LATEST live row per order — an older movement row left at P/D/V
        -- must not count an order McLeod has open.
        SELECT DISTINCT ON (r.company_id, r.id)
               TRIM(r.company_id) AS co, TRIM(r.id) AS id,
               TRIM(r.order_status) AS order_status, r.updated_dt
        FROM {LIVE_TABLE} r
        WHERE NOT COALESCE(r.is_deleted, false)
          AND r.updated_dt >= {_CST_NOW} - interval '{LOOKBACK_DAYS} days'
        ORDER BY r.company_id, r.id, r.updated_dt DESC NULLS LAST, r.movement_id DESC
    ) l ON l.co = a.co AND l.id = a.id
    WHERE l.order_status IN {_MOVED}
    ORDER BY l.updated_dt ASC
"""

# Per EVENT day of the latest live row (P → pickup arrival, D → delivery arrival,
# V → updated_dt): orders McLeod moved; how many v4 still calls A past the same
# grace LAG_SQL uses; how many v4 lacks. Plus the rolling-24 h verdict inputs.
# v4 is one row per order (verified 11-03); the live feed is TMS-only, trimmed.
# Once a day, ~3 s — one live-table scan is fine for a job, never per request.
DAILY_SQL = f"""
    WITH l AS (
        SELECT DISTINCT ON (r.company_id, r.id)
               TRIM(r.company_id) AS co, TRIM(r.id) AS id,
               TRIM(r.order_status) AS st,
               CASE TRIM(r.order_status)
                   WHEN 'P' THEN COALESCE(r.origin_actual_arrival, r.updated_dt)
                   WHEN 'D' THEN COALESCE(r.dest_actual_arrival, r.updated_dt)
                   ELSE r.updated_dt
               END AS event_dt
        FROM {LIVE_TABLE} r
        WHERE NOT COALESCE(r.is_deleted, false)
          AND r.updated_dt >= {CST_NOW_DATE_SQL} - {TREND_DAYS - 1}
        ORDER BY r.company_id, r.id, r.updated_dt DESC NULLS LAST, r.movement_id DESC
    ), v AS (
        SELECT DISTINCT ON (TRIM(v.company_id), TRIM(v.id))
               TRIM(v.company_id) AS co, TRIM(v.id) AS id, TRIM(v.status) AS st,
               v.updated_dt
        FROM {V4_TABLE} v
        WHERE v.company_id IN {_COMPANIES}
        ORDER BY TRIM(v.company_id), TRIM(v.id), v.updated_dt DESC NULLS LAST
    ), j AS (
        SELECT l.event_dt,
               (v.st = 'A' AND v.updated_dt < {_GRACE_BOUND}) AS stuck,
               (v.id IS NULL) AS missing,
               l.event_dt >= {_CST_NOW} - interval '{VERDICT_HOURS} hours' AS recent
        FROM l
        LEFT JOIN v ON v.co = l.co AND v.id = l.id
        WHERE l.st IN {_MOVED}
          AND l.event_dt >= {CST_NOW_DATE_SQL} - {TREND_DAYS - 1}
          AND l.event_dt < {_CST_NOW} - interval '{SETTLE_MINUTES} minutes'
    )
    SELECT event_dt::date AS day,
           count(*)::int                                   AS moved,
           count(*) FILTER (WHERE stuck)::int               AS still_a,
           count(*) FILTER (WHERE missing)::int             AS missing,
           count(*) FILTER (WHERE recent)::int              AS moved_recent,
           count(*) FILTER (WHERE recent AND stuck)::int    AS still_a_recent,
           max(event_dt) FILTER (WHERE stuck)               AS last_stuck
    FROM j
    GROUP BY 1
    ORDER BY 1
"""


def clamp_offset(offset_s: int | None) -> int:
    """The positive part of v4's clock offset, capped — added back to the grace."""
    if offset_s is None or offset_s <= 0:
        return 0
    return min(int(offset_s), MAX_OFFSET_SECONDS)


def verdict(daily: list[dict[str, Any]] | None) -> str | None:
    """Rolling-24 h verdict: still skipping vs backlog only — ``None`` when unmeasured."""
    if daily is None:
        return None
    moved = sum(d["moved_recent"] for d in daily)
    stuck = sum(d["still_a_recent"] for d in daily)
    if moved == 0:
        return f"No settled McLeod moves in the last {VERDICT_HOURS} h — cannot tell whether the ETL still skips."
    if stuck > 0:
        last = max(d["last_stuck"] for d in daily if d["last_stuck"] is not None)
        pct = round(100 * stuck / moved)
        return (
            f"STILL SKIPPING: {stuck} of {moved} orders McLeod moved in the last {VERDICT_HOURS} h "
            f"({pct}%) are still status A in v4 after {GRACE_HOURS} h — latest skipped change "
            f"{last:%m-%d %H:%M} (stop local time). The McLeod → gold load is broken now, not only behind."
        )
    return (
        f"Backlog only: all {moved} orders McLeod moved in the last {VERDICT_HOURS} h reached v4 — "
        f"the load looks fixed; the older orders below still need a re-sync."
    )


def assess(stuck: list[dict[str, Any]], threshold: int = THRESHOLD) -> list[str]:
    """The problems found, as human sentences — empty when healthy."""
    if len(stuck) <= threshold:
        return []
    ids = ", ".join(r["id"] for r in stuck[:SAMPLE_IDS])
    oldest = stuck[0]["live_updated"]
    message = (
        f"{len(stuck)} order(s) are still status A in mcleod_gld_budget_report_v4 although "
        f"McLeod reports them as P/D/V and v4 has not touched them for {GRACE_HOURS} h "
        f"(oldest live change {oldest:%Y-%m-%d %H:%M} CST). E.g. {ids}."
    )
    return [message]


def _offset_line(offset_s: int | None) -> str:
    if offset_s is None:
        return "unavailable"
    sign = "+" if offset_s >= 0 else "−"
    mins = abs(offset_s) // 60
    note = " ⚠ v4 stamps are in the FUTURE — clock / DST bug" if offset_s > OFFSET_ALERT_SECONDS else ""
    return f"{sign}{mins} min{note}"


def _daily_table(daily: list[dict[str, Any]] | None) -> str:
    if not daily:
        return ""
    cell = "padding:4px 12px 4px 0;"
    head = "".join(
        f"<th style='{cell}text-align:left;color:#555;font-weight:500;'>{h}</th>"
        for h in ("event day", "moved in McLeod", "still A in v4", "missing in v4")
    )
    body = "".join(
        f"<tr><td style='{cell}'>{d['day']:%a %m-%d}</td><td style='{cell}'>{d['moved']}</td>"
        f"<td style='{cell}font-weight:{600 if d['still_a'] else 400};'>{d['still_a']}</td>"
        f"<td style='{cell}'>{d['missing']}</td></tr>"
        for d in daily
    )
    return (
        f"<p style='margin:16px 0 4px;color:#555;'>Last {TREND_DAYS} days — orders whose latest "
        f"McLeod status is P/D/V, by pickup (P) / delivery (D) arrival day; still A = v4 untouched "
        f"{GRACE_HOURS} h:</p>"
        f"<table style=\"border-collapse:collapse;font-family:{MONO_STACK};font-size:13px;\">"
        f"<tr>{head}</tr>{body}</table>"
    )


def _render_html(problems: list[str], stats: dict[str, Any], daily, verdict_text) -> str:
    items = "".join(f"<li style='margin:0 0 6px;'>{p}</li>" for p in problems)
    verdict_html = (
        f"<p style='margin:0 0 12px;font-weight:600;'>{verdict_text}</p>" if verdict_text else ""
    )
    return f"""\
<div style="font-family:-apple-system,Segoe UI,Roboto,sans-serif;color:#1a1a1a;max-width:640px;">
  <h2 style="margin:0 0 8px;">⚠ Gold McLeod mirror behind McLeod — order status</h2>
  {verdict_html}
  <ul style="margin:0 0 16px;padding-left:18px;">{items}</ul>
  <p style="margin:0 0 16px;color:#555;">The Ops Portal Cover boards already hide these loads
    (live feed guard). Production, Hold, Division Payment and the PCA status mails still read
    v4, so picked-up loads are missing there until Data / BI re-syncs the McLeod → gold load.
    Freshness checks stay green: the tables keep updating, individual changes are skipped.</p>
  <table style="border-collapse:collapse;font-family:{MONO_STACK};font-size:13px;">
    <tr><td style="padding:4px 16px 4px 0;color:#555;">stuck orders</td><td style="padding:4px 0;font-weight:600;">{stats.get('stuck')}</td></tr>
    <tr><td style="padding:4px 16px 4px 0;color:#555;">threshold</td><td style="padding:4px 0;">{THRESHOLD}</td></tr>
    <tr><td style="padding:4px 16px 4px 0;color:#555;">v4 clock offset</td><td style="padding:4px 0;">{_offset_line(stats.get('v4_offset_s'))}</td></tr>
  </table>
  {_daily_table(daily)}
  <p style="margin:16px 0 0;color:#888;font-size:12px;">
    v4 clock offset = newest v4 updated_dt minus CST now; v4 refreshes every 15 min, so it
    should be 0 to −15 min. Owner of the McLeod → gold load: Data / BI. Rule: SPEC-CODE-RULES §143.
    Checked {cst_today().isoformat()} CST.</p>
</div>"""


async def _fetch_offset(pool) -> int | None:
    try:
        row = await pool.fetchrow(OFFSET_SQL)
    except Exception:
        logger.exception("check_mirror_status_lag: offset query failed (grace unadjusted)")
        return None
    return None if row is None or row["offset_s"] is None else int(row["offset_s"])


async def _fetch_daily(pool, offset_s: int | None) -> list[dict[str, Any]] | None:
    try:
        rows = await pool.fetch(DAILY_SQL, clamp_offset(offset_s))
    except Exception:
        logger.exception("check_mirror_status_lag: per-day query failed (mail without trend)")
        return None
    keys = ("day", "moved", "still_a", "missing", "moved_recent", "still_a_recent", "last_stuck")
    return [{k: r[k] for k in keys} for r in rows]


async def check_mirror_status_lag(
    pool,
    *,
    to: Iterable[str] = TO_RECIPIENTS,
    cc: Iterable[str] = CC_RECIPIENTS,
) -> dict[str, Any]:
    """Count v4 status-A orders McLeod already moved; alert over threshold. Never raises."""
    if pool is None:
        logger.warning("check_mirror_status_lag: savings_pool is None; skipping")
        return {"checked": False, "reason": "no_pool"}
    offset_s = await _fetch_offset(pool)
    try:
        rows = await pool.fetch(LAG_SQL, clamp_offset(offset_s))
    except Exception as e:
        logger.exception("check_mirror_status_lag: query failed")
        return {"checked": False, "reason": "query_failed", "error": str(e)}

    stuck = [{"id": r["id"], "live_updated": r["live_updated"]} for r in rows]
    stats = {"stuck": len(stuck), "v4_offset_s": offset_s}
    problems = assess(stuck)
    logger.info("check_mirror_status_lag: %s problems=%d", stats, len(problems))
    if not problems:
        return {"checked": True, "healthy": True, **stats}
    daily = await _fetch_daily(pool, offset_s)
    verdict_text = verdict(daily)
    html = _render_html(problems, stats, daily, verdict_text)
    return await _alert(tuple(to), tuple(cc), problems, stats, html, verdict_text)


async def _alert(
    to: tuple[str, ...],
    cc: tuple[str, ...],
    problems: list[str],
    stats: dict[str, Any],
    html: str,
    verdict_text: str | None,
) -> dict[str, Any]:
    base = {"checked": True, "healthy": False, "problems": problems, "verdict": verdict_text, **stats}
    to_list, blocked_to = partition_recipients([a for a in to if a])
    to_lower = {a.lower() for a in to_list}
    cc_list, blocked_cc = partition_recipients([a for a in cc if a and a.lower() not in to_lower])
    blocked = sorted(set(blocked_to) | set(blocked_cc))
    if blocked:
        logger.error(
            "check_mirror_status_lag: dropped non-company recipients on: %s",
            ", ".join(blocked),
        )
    if not to_list:
        return {**base, "alerted": False, "reason": "no_recipients"}
    # Notification → Microsoft Graph (Resend is login-OTP only). Never raises.
    result = await send_notification(
        to=to_list,
        cc=cc_list or None,
        subject=f"[UNILINK Space] Gold McLeod mirror behind — {stats['stuck']} orders still 'A'",
        html_body=html,
    )
    if not result.get("sent"):
        logger.error("check_mirror_status_lag: alert NOT sent (%s)", result.get("reason"))
        return {**base, "alerted": False, "reason": result.get("reason"),
                "error": result.get("error")}
    logger.info(
        "check_mirror_status_lag: alert sent to %d + cc %d recipient(s)",
        len(to_list), len(cc_list),
    )
    return {**base, "alerted": True, "to": to_list, "cc": cc_list}
