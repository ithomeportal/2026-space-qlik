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
shorter — and mails Diego when
that count exceeds ``THRESHOLD``. The Cover boards already hide such loads
(``ops_portal_overview/_live_status.py``); Production / Hold / DPC / the PCA
mails still read v4, so the ETL owner (Data / BI) must re-sync.

Never raises — log-and-swallow, exactly like ``revenue_code_monitor``.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable
from typing import Any

import resend

from app.clock import cst_today
from app.config import settings
from app.datalake import pad_variants, sql_str_list
from app.services.allowed_domains import partition_recipients

logger = logging.getLogger("uvicorn.error")

THRESHOLD = 5
GRACE_HOURS = 3
LOOKBACK_DAYS = 45
SAMPLE_IDS = 12
LIVE_TABLE = "public.app_augment_n8n_data_ra_rt"
# The live feed holds US (TMS) orders only.
COMPANIES = ("TMS",)
MOVED_STATUSES = ("P", "D", "V")

FROM_ADDRESS = "UNILINK Space <noreply@unilinkportal.com>"
TO_RECIPIENTS: tuple[str, ...] = ("dfrodriguez@unilinktransportation.com",)

MONO_STACK = "ui-monospace, SFMono-Regular, 'SF Mono', Menlo, Consolas, monospace"

_COMPANIES = sql_str_list(pad_variants(COMPANIES, width=4))
_STATUS_A = sql_str_list(pad_variants(("A",), width=1))
_MOVED = sql_str_list(MOVED_STATUSES)

# Uncorrelated hashed IN-set (§135); the live side is ~28k rows, v4 status='A'
# a few hundred — one small scan each, once a day.
LAG_SQL = f"""
    SELECT a.id, l.order_status, l.updated_dt AS live_updated
    FROM (
        -- One row per v4 order; grace = v4 has not touched the order for
        -- GRACE_HOURS (the live row is re-stamped constantly by GPS updates,
        -- so its own updated_dt cannot measure how long v4 has lagged).
        SELECT DISTINCT ON (TRIM(v.company_id), TRIM(v.id))
               TRIM(v.company_id) AS co, TRIM(v.id) AS id
        FROM public.mcleod_gld_budget_report_v4 v
        WHERE v.company_id IN {_COMPANIES}
          AND v.status IN {_STATUS_A}
          AND v.updated_dt < now() - interval '{GRACE_HOURS} hours'
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
          AND r.updated_dt >= now() - interval '{LOOKBACK_DAYS} days'
        ORDER BY r.company_id, r.id, r.updated_dt DESC NULLS LAST, r.movement_id DESC
    ) l ON l.co = a.co AND l.id = a.id
    WHERE l.order_status IN {_MOVED}
    ORDER BY l.updated_dt ASC
"""


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


def _render_html(problems: list[str], stats: dict[str, Any]) -> str:
    items = "".join(f"<li style='margin:0 0 6px;'>{p}</li>" for p in problems)
    return f"""\
<div style="font-family:-apple-system,Segoe UI,Roboto,sans-serif;color:#1a1a1a;max-width:640px;">
  <h2 style="margin:0 0 8px;">⚠ Gold McLeod mirror behind McLeod — order status</h2>
  <ul style="margin:0 0 16px;padding-left:18px;">{items}</ul>
  <p style="margin:0 0 16px;color:#555;">The Ops Portal Cover boards already hide these loads
    (live feed guard). Production, Hold, Division Payment and the PCA status mails still read
    v4, so picked-up loads are missing there until Data / BI re-syncs the McLeod → gold load.
    Freshness checks stay green: the tables keep updating, individual changes are skipped.</p>
  <table style="border-collapse:collapse;font-family:{MONO_STACK};font-size:13px;">
    <tr><td style="padding:4px 16px 4px 0;color:#555;">stuck orders</td><td style="padding:4px 0;font-weight:600;">{stats.get('stuck')}</td></tr>
    <tr><td style="padding:4px 16px 4px 0;color:#555;">threshold</td><td style="padding:4px 0;">{THRESHOLD}</td></tr>
  </table>
  <p style="margin:16px 0 0;color:#888;font-size:12px;">
    Owner of the McLeod → gold load: Data / BI. Rule: SPEC-CODE-RULES §143.
    Checked {cst_today().isoformat()} CST.</p>
</div>"""


async def check_mirror_status_lag(
    pool,
    *,
    to: Iterable[str] = TO_RECIPIENTS,
) -> dict[str, Any]:
    """Count v4 status-A orders McLeod already moved; alert over threshold. Never raises."""
    if pool is None:
        logger.warning("check_mirror_status_lag: savings_pool is None; skipping")
        return {"checked": False, "reason": "no_pool"}
    try:
        rows = await pool.fetch(LAG_SQL)
    except Exception as e:
        logger.exception("check_mirror_status_lag: query failed")
        return {"checked": False, "reason": "query_failed", "error": str(e)}

    stuck = [{"id": r["id"], "live_updated": r["live_updated"]} for r in rows]
    stats = {"stuck": len(stuck)}
    problems = assess(stuck)
    logger.info("check_mirror_status_lag: %s problems=%d", stats, len(problems))
    if not problems:
        return {"checked": True, "healthy": True, **stats}
    return await _alert(tuple(to), problems, stats)


async def _alert(to: tuple[str, ...], problems: list[str], stats: dict[str, Any]) -> dict[str, Any]:
    base = {"checked": True, "healthy": False, "problems": problems, **stats}
    if not settings.RESEND_API_KEY:
        logger.warning("check_mirror_status_lag: unhealthy but RESEND_API_KEY not set")
        return {**base, "alerted": False, "reason": "no_resend_key"}
    to_list, blocked = partition_recipients([a for a in to if a])
    if blocked:
        logger.error(
            "check_mirror_status_lag: dropped non-company recipients on: %s",
            ", ".join(blocked),
        )
    if not to_list:
        return {**base, "alerted": False, "reason": "no_recipients"}
    try:
        resend.api_key = settings.RESEND_API_KEY
        resend.Emails.send({
            "from": FROM_ADDRESS,
            "to": to_list,
            "subject": f"[UNILINK Space] Gold McLeod mirror behind — {stats['stuck']} orders still 'A'",
            "html": _render_html(problems, stats),
        })
        logger.info("check_mirror_status_lag: alert sent to %d recipient(s)", len(to_list))
        return {**base, "alerted": True, "to": to_list}
    except Exception as e:
        logger.exception("check_mirror_status_lag: Resend send failed")
        return {**base, "alerted": False, "reason": "resend_failed", "error": str(e)}
