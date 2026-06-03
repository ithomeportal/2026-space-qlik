"""Daily health check for the portal-owned ``mcleod_gld_scorecard_portal`` mirror.

Background
----------
The portal no longer reads the shared, Spark-loaded ``mcleod_gld_scorecard``
directly (it UPDATE-churns to 71x heap bloat — see SPEC-CODE-RULES §43). Instead
an n8n workflow ("Refresh mcleod_gld_scorecard_portal (poll-on-change)") keeps a
portal-owned ``TRUNCATE + INSERT SELECT *`` mirror in ``aivn_datalake_gold``, and
every scorecard report reads that mirror. Because the mirror is rebuilt by
TRUNCATE it **cannot bloat** — so the thing worth watching flipped from "is it
bloated?" to **"is it fresh?"** (i.e. is the n8n refresh still running?).

This job (daily, SELECT-only) alerts Diego when the mirror has fallen behind the
source — the source's `pg_stat` change counter has advanced but the mirror's
stored marker hasn't caught up within the grace window, or the mirror is empty /
missing. All probes are metadata / `pg_stat` reads (no scan of the bloated
source). Never raises — log-and-swallow.
"""

from __future__ import annotations

import logging
from typing import Any, Iterable

import resend

from app.clock import cst_today
from app.config import settings

logger = logging.getLogger("uvicorn.error")

MIRROR = "public.mcleod_gld_scorecard_portal"
META = "public.mcleod_gld_scorecard_portal_meta"
SOURCE = "mcleod_gld_scorecard"

# Source changed but mirror hasn't caught up within this window => n8n is stuck.
STALE_GRACE_HOURS = 3

FROM_ADDRESS = "UNILINK Space <noreply@unilinkportal.com>"
TO_RECIPIENTS: tuple[str, ...] = ("dfrodriguez@unilinktransportation.com",)

MONO_STACK = "ui-monospace, SFMono-Regular, 'SF Mono', Menlo, Consolas, monospace"


def _render_html(d: dict[str, Any], reason: str) -> str:
    return f"""\
<div style="font-family:-apple-system,Segoe UI,Roboto,sans-serif;color:#1a1a1a;max-width:640px;">
  <h2 style="margin:0 0 8px;">⚠ Scorecard mirror stale — <code>{MIRROR}</code></h2>
  <p style="margin:0 0 16px;color:#555;">{reason} The n8n workflow
    <b>"Refresh mcleod_gld_scorecard_portal (poll-on-change)"</b> may have failed or
    been deactivated — scorecard reports will show stale data until it resumes.</p>
  <table style="border-collapse:collapse;font-family:{MONO_STACK};font-size:13px;">
    <tr><td style="padding:4px 16px 4px 0;color:#555;">mirror rows</td><td style="padding:4px 0;font-weight:600;">{d.get('mirror_rows')}</td></tr>
    <tr><td style="padding:4px 16px 4px 0;color:#555;">mirror last refreshed</td><td style="padding:4px 0;">{d.get('refreshed_at')}</td></tr>
    <tr><td style="padding:4px 16px 4px 0;color:#555;">source changed since?</td><td style="padding:4px 0;">{d.get('source_advanced')}</td></tr>
    <tr><td style="padding:4px 16px 4px 0;color:#555;">source heap size (FYI)</td><td style="padding:4px 0;">{d.get('source_size')}</td></tr>
  </table>
  <p style="margin:16px 0 0;color:#888;font-size:12px;">
    Check the workflow at n8n.unlk-repos.com (Schedule → Ensure+probe → Source changed? → Truncate+reload).
    Checked {cst_today().isoformat()} CST.</p>
</div>"""


async def check_scorecard_mirror(
    pool,
    *,
    to: Iterable[str] = TO_RECIPIENTS,
) -> dict[str, Any]:
    """Alert if the mirror is missing/empty or has fallen behind the source.

    Returns a diagnostic dict (never raises) so the scheduler can log it.
    """
    if pool is None:
        logger.warning("check_scorecard_mirror: savings_pool is None; skipping")
        return {"checked": False, "reason": "no_pool"}

    try:
        async with pool.acquire() as conn:
            present = await conn.fetchval(f"SELECT to_regclass('{MIRROR}') IS NOT NULL")
            if not present:
                stats = {"mirror_rows": 0, "refreshed_at": None,
                         "source_advanced": "n/a", "source_size": None}
                return await _alert(to, stats,
                    "The mirror table does not exist yet (n8n has never run successfully).",
                    reason_code="mirror_missing")

            row = await conn.fetchrow(f"""
                SELECT
                  (SELECT count(*) FROM {MIRROR})                                        AS mirror_rows,
                  (SELECT refreshed_at FROM {META} WHERE id = 1)                          AS refreshed_at,
                  ( (SELECT n_tup_ins + n_tup_upd FROM pg_stat_user_tables WHERE relname = '{SOURCE}')
                      IS DISTINCT FROM (SELECT src_mods FROM {META} WHERE id = 1) )        AS source_advanced,
                  COALESCE((SELECT refreshed_at FROM {META} WHERE id = 1)
                             < now() - interval '{STALE_GRACE_HOURS} hours', true)         AS past_grace,
                  pg_size_pretty(pg_total_relation_size('{SOURCE}'::regclass))            AS source_size
            """)
    except Exception as e:
        logger.exception("check_scorecard_mirror: query failed: %s", e)
        return {"checked": False, "reason": "query_failed", "error": str(e)}

    stats = {
        "mirror_rows": row["mirror_rows"],
        "refreshed_at": row["refreshed_at"].isoformat() if row["refreshed_at"] else None,
        "source_advanced": row["source_advanced"],
        "source_size": row["source_size"],
    }

    stale = (
        row["mirror_rows"] == 0
        or row["refreshed_at"] is None
        or (row["source_advanced"] and row["past_grace"])
    )
    logger.info("check_scorecard_mirror: %s, stale=%s", stats, stale)

    if not stale:
        return {"checked": True, "stale": False, **stats}

    reason = ("Mirror is empty." if row["mirror_rows"] == 0
              else "Mirror has never been refreshed." if row["refreshed_at"] is None
              else f"Source changed but mirror hasn't refreshed in {STALE_GRACE_HOURS}h+.")
    return await _alert(to, stats, reason, reason_code="stale")


async def _alert(to, stats, reason, *, reason_code) -> dict[str, Any]:
    if not settings.RESEND_API_KEY:
        logger.warning("check_scorecard_mirror: stale but RESEND_API_KEY not set")
        return {"checked": True, "stale": True, "alerted": False,
                "reason": "no_resend_key", "detail": reason_code, **stats}
    to_list = [a for a in to if a]
    if not to_list:
        return {"checked": True, "stale": True, "alerted": False,
                "reason": "no_recipients", **stats}
    try:
        resend.api_key = settings.RESEND_API_KEY
        resend.Emails.send({
            "from": FROM_ADDRESS,
            "to": to_list,
            "subject": "[UNILINK Space] Scorecard mirror stale — refresh may be broken",
            "html": _render_html(stats, reason),
        })
        logger.info("check_scorecard_mirror: alert sent to %d recipient(s)", len(to_list))
        return {"checked": True, "stale": True, "alerted": True, "to": to_list, **stats}
    except Exception as e:
        logger.exception("check_scorecard_mirror: Resend send failed: %s", e)
        return {"checked": True, "stale": True, "alerted": False,
                "reason": "resend_failed", "error": str(e), **stats}
