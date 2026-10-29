"""Daily health check for the revenue-code lookup behind the DFW rule.

Background
----------
Since 2026-10-29 (SPEC-CODE-RULES §135) every CORP/DFW division scope reads
``mcleod_gld_cash_flow_dinfo.revenue_code_id`` for McLeod MX (TMS3) orders:
code ``DFW`` → DFW team TM4, any other code → the salesperson's team, and an
order dinfo has not reached yet → the TM sub-team marker.

That fallback is what makes a frozen dinfo SILENT: nothing errors, MX orders
simply go back to the marker rule, and a DFW-coded load McLeod booked without
a TM# lands on a CORP team again — Sergio's report all over. This job (daily,
SELECT-only) alerts Diego when:

* ``frozen``   — v4 kept advancing more than ``FROZEN_HOURS`` past dinfo's last
  write (dinfo trails v4 by ~30 min in the day and both go quiet overnight /
  at weekends, measured 2026-10-29 — so compare against v4, never the clock);
* ``coverage`` — an MX order created 1–30 days ago has no dinfo row (0 on
  2026-10-29); the day-old floor leaves room for the normal sync lag.

Never raises — log-and-swallow, exactly like ``scorecard_mirror_monitor``.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable
from typing import Any

import resend

from app.clock import cst_today
from app.config import settings
from app.datalake import (
    REVENUE_CODE_COMPANIES,
    REVENUE_CODE_TABLE,
    pad_variants,
    sql_str_list,
)
from app.services.allowed_domains import partition_recipients

logger = logging.getLogger("uvicorn.error")

FROZEN_HOURS = 24
COVERAGE_MIN_AGE_DAYS = 1
COVERAGE_MAX_AGE_DAYS = 30
SAMPLE_IDS = 10

FROM_ADDRESS = "UNILINK Space <noreply@unilinkportal.com>"
TO_RECIPIENTS: tuple[str, ...] = ("dfrodriguez@unilinktransportation.com",)

MONO_STACK = "ui-monospace, SFMono-Regular, 'SF Mono', Menlo, Consolas, monospace"

_COMPANIES = sql_str_list(pad_variants(REVENUE_CODE_COMPANIES, width=4))

# `updated_dt` has no index on either table: two plain max() scans (~225k and
# ~290k rows) once a day. The coverage probe is PK lookups over a few MX rows.
PROBE_SQL = f"""
    SELECT
      (SELECT max(updated_dt) FROM public.mcleod_gld_budget_report_v4) AS v4_last,
      (SELECT max(updated_dt) FROM public.{REVENUE_CODE_TABLE})        AS dinfo_last
"""

MISSING_SQL = f"""
    SELECT TRIM(v.id) AS id
    FROM public.mcleod_gld_budget_report_v4 v
    WHERE v.company_id IN {_COMPANIES}
      AND v.created_dt <  now() - interval '{COVERAGE_MIN_AGE_DAYS} day'
      AND v.created_dt >= now() - interval '{COVERAGE_MAX_AGE_DAYS} days'
      AND NOT EXISTS (
            SELECT 1 FROM public.{REVENUE_CODE_TABLE} d
            WHERE d.company_id = v.company_id AND d.id = v.id)
    ORDER BY v.created_dt DESC
"""


def assess(v4_last, dinfo_last, missing_ids: list[str]) -> list[str]:
    """The problems found, as human sentences — empty when healthy."""
    problems: list[str] = []
    if dinfo_last is None:
        problems.append(f"{REVENUE_CODE_TABLE} is empty or has no updated_dt at all.")
    elif v4_last is not None:
        lag_h = (v4_last - dinfo_last).total_seconds() / 3600
        if lag_h > FROZEN_HOURS:
            problems.append(
                f"{REVENUE_CODE_TABLE} last written {dinfo_last:%Y-%m-%d %H:%M}, "
                f"{lag_h:.0f} h behind v4 ({v4_last:%Y-%m-%d %H:%M}) — looks frozen."
            )
    if missing_ids:
        problems.append(
            f"{len(missing_ids)} McLeod MX order(s) created {COVERAGE_MIN_AGE_DAYS}–"
            f"{COVERAGE_MAX_AGE_DAYS} days ago have no revenue code row "
            f"(e.g. {', '.join(missing_ids[:SAMPLE_IDS])})."
        )
    return problems


def _render_html(problems: list[str], stats: dict[str, Any]) -> str:
    items = "".join(f"<li style='margin:0 0 6px;'>{p}</li>" for p in problems)
    return f"""\
<div style="font-family:-apple-system,Segoe UI,Roboto,sans-serif;color:#1a1a1a;max-width:640px;">
  <h2 style="margin:0 0 8px;">⚠ Revenue-code lookup unhealthy — <code>{REVENUE_CODE_TABLE}</code></h2>
  <ul style="margin:0 0 16px;padding-left:18px;">{items}</ul>
  <p style="margin:0 0 16px;color:#555;">Every CORP/DFW report decides McLeod MX orders by this
    table's revenue code (DFW → DFW team TM4). While it is stale, MX orders it has not
    reached fall back to the TM sub-team marker — a DFW-coded load booked without a TM#
    shows on a CORP team again. Nothing errors; the reports keep loading.</p>
  <table style="border-collapse:collapse;font-family:{MONO_STACK};font-size:13px;">
    <tr><td style="padding:4px 16px 4px 0;color:#555;">v4 last write</td><td style="padding:4px 0;">{stats.get('v4_last')}</td></tr>
    <tr><td style="padding:4px 16px 4px 0;color:#555;">dinfo last write</td><td style="padding:4px 0;">{stats.get('dinfo_last')}</td></tr>
    <tr><td style="padding:4px 16px 4px 0;color:#555;">MX orders missing</td><td style="padding:4px 0;font-weight:600;">{stats.get('missing')}</td></tr>
  </table>
  <p style="margin:16px 0 0;color:#888;font-size:12px;">
    Owner of the McLeod → gold load: Data / BI. Rule: SPEC-CODE-RULES §135.
    Checked {cst_today().isoformat()} CST.</p>
</div>"""


async def check_revenue_code_lookup(
    pool,
    *,
    to: Iterable[str] = TO_RECIPIENTS,
) -> dict[str, Any]:
    """Probe dinfo freshness + MX coverage; alert when unhealthy. Never raises."""
    if pool is None:
        logger.warning("check_revenue_code_lookup: savings_pool is None; skipping")
        return {"checked": False, "reason": "no_pool"}
    try:
        async with pool.acquire() as conn:
            row = await conn.fetchrow(PROBE_SQL)
            missing = [r["id"] for r in await conn.fetch(MISSING_SQL)]
    except Exception as e:
        logger.exception("check_revenue_code_lookup: query failed")
        return {"checked": False, "reason": "query_failed", "error": str(e)}

    stats = {
        "v4_last": row["v4_last"].isoformat() if row["v4_last"] else None,
        "dinfo_last": row["dinfo_last"].isoformat() if row["dinfo_last"] else None,
        "missing": len(missing),
    }
    problems = assess(row["v4_last"], row["dinfo_last"], missing)
    logger.info("check_revenue_code_lookup: %s problems=%d", stats, len(problems))
    if not problems:
        return {"checked": True, "healthy": True, **stats}
    return await _alert(tuple(to), problems, stats)


async def _alert(to: tuple[str, ...], problems: list[str], stats: dict[str, Any]) -> dict[str, Any]:
    base = {"checked": True, "healthy": False, "problems": problems, **stats}
    if not settings.RESEND_API_KEY:
        logger.warning("check_revenue_code_lookup: unhealthy but RESEND_API_KEY not set")
        return {**base, "alerted": False, "reason": "no_resend_key"}
    to_list, blocked = partition_recipients([a for a in to if a])
    if blocked:
        logger.error(
            "check_revenue_code_lookup: dropped non-company recipients on: %s",
            ", ".join(blocked),
        )
    if not to_list:
        return {**base, "alerted": False, "reason": "no_recipients"}
    try:
        resend.api_key = settings.RESEND_API_KEY
        resend.Emails.send({
            "from": FROM_ADDRESS,
            "to": to_list,
            "subject": "[UNILINK Space] Revenue-code lookup stale — MX division rule falling back",
            "html": _render_html(problems, stats),
        })
        logger.info("check_revenue_code_lookup: alert sent to %d recipient(s)", len(to_list))
        return {**base, "alerted": True, "to": to_list}
    except Exception as e:
        logger.exception("check_revenue_code_lookup: Resend send failed")
        return {**base, "alerted": False, "reason": "resend_failed", "error": str(e)}
