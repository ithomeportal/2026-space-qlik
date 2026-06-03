"""Weekly heap-bloat watchdog for ``mcleod_gld_scorecard`` (aivn_datalake_gold).

Why this exists
---------------
On 2026-06-02 ``mcleod_gld_scorecard`` was found 71x heap-bloated (3,488 MB
heap for ~62 MB of live data, 0.45 tuples/page) — the McLeod->gold loader
DELETEs + reinserts, and a plain ``DELETE`` never returns free pages to the OS
so autovacuum can't shrink it. That made ``_scorecard_cte`` read ~430 MB of
mostly-empty pages TWICE per heavy Ops Portal Overview request. A one-off
``VACUUM (FULL, ANALYZE)`` brought it back to 62 MB, but the loader pattern is
unchanged so the bloat WILL creep back.

The fix (``VACUUM FULL`` / ``pg_repack``) needs the ``avnadmin`` master role and
an ACCESS EXCLUSIVE lock — neither is safe to automate from Render (the backend
holds a SELECT-only role per SPEC-CODE-RULES §8, and the lock must run
off-hours). So this job does the one thing the backend *can* do: **watch the
table size and email a human when it crosses the threshold**, so the off-hours
repack gets run before users feel it again.

SELECT-only: ``pg_total_relation_size`` / ``pg_class`` are readable by
``sa_dfrodriguez``; no DDL, no write. Never raises — log-and-swallow so a
transient datalake hiccup doesn't take down the next week's check.
"""

from __future__ import annotations

import logging
from typing import Any, Iterable

import resend

from app.clock import cst_today
from app.config import settings

logger = logging.getLogger("uvicorn.error")

TABLE = "public.mcleod_gld_scorecard"

# Healthy size is ~62 MB. Alert well before the 3.5 GB disaster but high enough
# that normal post-repack growth doesn't page anyone: ~8x healthy.
THRESHOLD_BYTES = 500 * 1024 * 1024  # 500 MB
# Healthy is ~17 tuples/page; a low value is the tell-tale bloat signature even
# if total size hasn't crossed the byte threshold yet (informational).
HEALTHY_TUPLES_PER_PAGE = 5.0

FROM_ADDRESS = "UNILINK Space <noreply@unilinkportal.com>"
TO_RECIPIENTS: tuple[str, ...] = ("dfrodriguez@unilinktransportation.com",)

MONO_STACK = (
    "ui-monospace, SFMono-Regular, 'SF Mono', Menlo, Consolas, monospace"
)


def _fmt_mb(num_bytes: int | None) -> str:
    if not num_bytes:
        return "n/a"
    return f"{num_bytes / 1024 / 1024:,.0f} MB"


def _render_html(stats: dict[str, Any]) -> str:
    repack_sql = (
        "VACUUM (FULL, ANALYZE) public.mcleod_gld_scorecard;  "
        "-- avnadmin, off-hours, ACCESS EXCLUSIVE lock"
    )
    return f"""\
<div style="font-family: -apple-system, Segoe UI, Roboto, sans-serif; color:#1a1a1a; max-width:640px;">
  <h2 style="margin:0 0 8px;">⚠ Datalake bloat: <code>mcleod_gld_scorecard</code></h2>
  <p style="margin:0 0 16px; color:#555;">
    The scorecard heap has bloated past {_fmt_mb(THRESHOLD_BYTES)}. It needs an
    off-hours repack (<code>avnadmin</code>) before Ops Portal Overview slows down
    again. Hand-off SQL: <code>docs/ops-portal-overview-indexes-avnadmin.sql</code>.
  </p>
  <table style="border-collapse:collapse; font-family:{MONO_STACK}; font-size:13px;">
    <tr><td style="padding:4px 16px 4px 0; color:#555;">Total size</td>
        <td style="padding:4px 0; font-weight:600;">{stats['total_pretty']}</td></tr>
    <tr><td style="padding:4px 16px 4px 0; color:#555;">Threshold</td>
        <td style="padding:4px 0;">{_fmt_mb(THRESHOLD_BYTES)}</td></tr>
    <tr><td style="padding:4px 16px 4px 0; color:#555;">tuples/page</td>
        <td style="padding:4px 0;">{stats['tuples_per_page']:.2f} (healthy ~17)</td></tr>
    <tr><td style="padding:4px 16px 4px 0; color:#555;">live rows</td>
        <td style="padding:4px 0;">{stats['reltuples']:,}</td></tr>
  </table>
  <p style="margin:16px 0 6px; color:#555;">Run off-hours as <code>avnadmin</code>:</p>
  <pre style="background:#f4f4f5; padding:12px; border-radius:6px; font-family:{MONO_STACK}; font-size:12px; overflow:auto;">{repack_sql}</pre>
  <p style="margin:12px 0 0; color:#888; font-size:12px;">
    Root cause: the McLeod-&gt;gold loader DELETEs + reinserts (never reclaims
    pages). Permanent fix is to switch that loader to TRUNCATE + reload.
    Checked {cst_today().isoformat()} CST.
  </p>
</div>"""


async def check_scorecard_bloat(
    pool,
    *,
    to: Iterable[str] = TO_RECIPIENTS,
) -> dict[str, Any]:
    """Measure the scorecard table and email if it has re-bloated.

    Returns a diagnostic dict (never raises) so the scheduler can log it.
    """
    if pool is None:
        logger.warning("check_scorecard_bloat: savings_pool is None; skipping")
        return {"checked": False, "reason": "no_pool"}

    try:
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                f"""
                SELECT pg_total_relation_size('{TABLE}'::regclass)        AS total_bytes,
                       pg_size_pretty(pg_total_relation_size('{TABLE}'::regclass)) AS total_pretty,
                       c.relpages,
                       c.reltuples::bigint                                AS reltuples
                  FROM pg_class c
                 WHERE c.oid = '{TABLE}'::regclass
                """
            )
    except Exception as e:
        logger.exception("check_scorecard_bloat: query failed: %s", e)
        return {"checked": False, "reason": "query_failed", "error": str(e)}

    if row is None:
        logger.warning("check_scorecard_bloat: table %s not found", TABLE)
        return {"checked": False, "reason": "table_missing"}

    total_bytes = int(row["total_bytes"] or 0)
    relpages = int(row["relpages"] or 0)
    reltuples = int(row["reltuples"] or 0)
    tuples_per_page = (reltuples / relpages) if relpages else 0.0

    stats = {
        "total_bytes": total_bytes,
        "total_pretty": row["total_pretty"],
        "relpages": relpages,
        "reltuples": reltuples,
        "tuples_per_page": tuples_per_page,
    }
    bloated = total_bytes > THRESHOLD_BYTES
    logger.info(
        "check_scorecard_bloat: %s, %.2f tuples/page, bloated=%s (threshold %s)",
        row["total_pretty"], tuples_per_page, bloated, _fmt_mb(THRESHOLD_BYTES),
    )

    if not bloated:
        return {"checked": True, "bloated": False, **stats}

    if not settings.RESEND_API_KEY:
        logger.warning("check_scorecard_bloat: bloated but RESEND_API_KEY not set")
        return {"checked": True, "bloated": True, "alerted": False,
                "reason": "no_resend_key", **stats}

    to_list = [addr for addr in to if addr]
    if not to_list:
        return {"checked": True, "bloated": True, "alerted": False,
                "reason": "no_recipients", **stats}

    try:
        resend.api_key = settings.RESEND_API_KEY
        resend.Emails.send({
            "from": FROM_ADDRESS,
            "to": to_list,
            "subject": (
                f"[UNILINK Space] Datalake bloat — mcleod_gld_scorecard at "
                f"{row['total_pretty']} (repack needed)"
            ),
            "html": _render_html(stats),
        })
        logger.info("check_scorecard_bloat: alert sent to %d recipient(s)", len(to_list))
        return {"checked": True, "bloated": True, "alerted": True,
                "to": to_list, **stats}
    except Exception as e:
        logger.exception("check_scorecard_bloat: Resend send failed: %s", e)
        return {"checked": True, "bloated": True, "alerted": False,
                "reason": "resend_failed", "error": str(e), **stats}
