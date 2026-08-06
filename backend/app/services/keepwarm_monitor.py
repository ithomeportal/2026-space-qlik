"""Daily watchdog for the backend keep-warm pingers.

Background
----------
The backend runs on Render's free tier and sleeps after ~15 min idle, so two
independent pingers hit ``/api/health`` every 5 minutes:

* **primary**  — n8n workflow ``aF3wH6ZpvDFEPXA5`` on ``n8n.unlk-repos.com``
* **backstop** — ``spaceqlik-keepwarm.timer`` (systemd) on the SAME host, at the
  OS level so it survives n8n container restarts/upgrades

Neither reports its own health. The n8n workflow sets
``saveDataSuccessExecution: "none"`` and has no ``errorWorkflow``, so if it
silently stopped, **nothing in n8n would surface it** — the first symptom would
be users seeing blank reports (the same silent-outage shape as the Jul 2026
``/spots/report`` cron incident). This job closes that gap: ``/api/health``
stamps a row per pinger in ``keepwarm_pings``, and once a day we check that both
are still beating, then reset the 24h gap window.

Alerts only when something is wrong (quiet when healthy), SELECT + one UPDATE,
never raises — log-and-swallow, exactly like ``scorecard_mirror_monitor``.

Known blind spot (documented, not a bug): if **both** pingers die the dyno
sleeps, APScheduler stops with it, and this job cannot run. That failure mode is
self-announcing — users hit cold starts immediately. This watchdog exists for the
much quieter case where *one* pinger dies and the other masks it.
"""

from __future__ import annotations

import logging
from typing import Any, Iterable

import resend

from app.clock import cst_today
from app.config import settings
from app.services.allowed_domains import partition_recipients

logger = logging.getLogger("uvicorn.error")

# Both pingers fire every 5 min. 20 min = 4 missed ticks — tolerant of a Render
# deploy (which restarts the dyno and drops a couple of pings) but still tight
# enough to catch a real stall within a day.
STALE_MINUTES = 20

# Public IP of bi-unlk.itunilink.com, the always-on box that hosts BOTH pingers.
KEEPWARM_HOST_IP = "66.23.237.218"

SOURCE_N8N = "n8n"
SOURCE_SYSTEMD = "systemd"

SOURCE_LABELS = {
    SOURCE_N8N: "n8n workflow aF3wH6ZpvDFEPXA5 (PRIMARY)",
    SOURCE_SYSTEMD: "spaceqlik-keepwarm.timer (BACKSTOP)",
}

FROM_ADDRESS = "UNILINK Space <noreply@unilinkportal.com>"
TO_RECIPIENTS: tuple[str, ...] = ("dfrodriguez@unilinktransportation.com",)

MONO_STACK = "ui-monospace, SFMono-Regular, 'SF Mono', Menlo, Consolas, monospace"


def classify_keepwarm_source(
    user_agent: str | None, forwarded_for: str | None
) -> str | None:
    """Map an ``/api/health`` caller to a keep-warm source, or ``None`` to ignore.

    Only the two known pingers are recorded — browsers, the proxy and manual
    smoke tests are ignored so the table stays at exactly two rows.

    The systemd script sends an explicit ``spaceqlik-keepwarm/1`` UA, so it is
    matched first and unambiguously. n8n is matched on its ``n8n`` UA, with a
    **client-IP fallback**: both pingers share one host, so once the systemd UA
    has been excluded, anything else from that IP is n8n. That fallback is what
    keeps an n8n upgrade changing its User-Agent from silently looking like a
    dead primary and firing a false alarm.
    """
    ua = (user_agent or "").lower()
    if "spaceqlik-keepwarm" in ua:
        return SOURCE_SYSTEMD
    if "n8n" in ua:
        return SOURCE_N8N
    # X-Forwarded-For is a comma-separated chain; the client is the first hop.
    client_ip = (forwarded_for or "").split(",")[0].strip()
    if client_ip == KEEPWARM_HOST_IP:
        return SOURCE_N8N
    return None


def _fmt_gap(seconds: int | None) -> str:
    if not seconds:
        return "—"
    if seconds < 90:
        return f"{seconds}s"
    return f"{seconds // 60} min"


def _render_html(rows: list[dict[str, Any]], problems: list[str]) -> str:
    body = "".join(
        f"""<tr>
      <td style="padding:4px 16px 4px 0;color:#555;">{SOURCE_LABELS.get(r['source'], r['source'])}</td>
      <td style="padding:4px 16px 4px 0;font-weight:600;color:{'#b00020' if r['stale'] else '#1a7f37'};">
        {'STALLED' if r['stale'] else 'ok'}</td>
      <td style="padding:4px 16px 4px 0;">{r['age']}</td>
      <td style="padding:4px 0;">{_fmt_gap(r['max_gap_seconds'])}</td>
    </tr>"""
        for r in rows
    )
    issues = "".join(f"<li>{p}</li>" for p in problems)
    return f"""\
<div style="font-family:-apple-system,Segoe UI,Roboto,sans-serif;color:#1a1a1a;max-width:640px;">
  <h2 style="margin:0 0 8px;">⚠ Backend keep-warm degraded</h2>
  <p style="margin:0 0 16px;color:#555;">A keep-warm pinger for
    <code>two026-space-qlik-back.onrender.com</code> has stopped or is skipping beats.
    While at least one pinger survives users see no impact — but the redundancy is gone,
    so this needs fixing before the other one goes too.</p>
  <ul style="margin:0 0 16px;color:#b00020;">{issues}</ul>
  <table style="border-collapse:collapse;font-family:{MONO_STACK};font-size:13px;">
    <tr style="text-align:left;color:#888;">
      <th style="padding:0 16px 6px 0;">pinger</th><th style="padding:0 16px 6px 0;">state</th>
      <th style="padding:0 16px 6px 0;">last ping</th><th style="padding:0 0 6px;">worst gap /24h</th>
    </tr>
    {body}
  </table>
  <p style="margin:16px 0 0;color:#555;font-size:13px;">
    <b>n8n primary:</b> check workflow <code>aF3wH6ZpvDFEPXA5</code> is still <b>active</b> at
    n8n.unlk-repos.com. Its execution list is empty <i>by design</i> (successes aren't saved),
    so prove it from Render access logs, not from n8n.<br>
    <b>systemd backstop:</b> <code>ssh root@{KEEPWARM_HOST_IP}</code> then
    <code>systemctl list-timers spaceqlik-keepwarm.timer</code> and
    <code>journalctl -t spaceqlik-keepwarm</code>.</p>
  <p style="margin:12px 0 0;color:#888;font-size:12px;">
    Stale threshold {STALE_MINUTES} min ({STALE_MINUTES // 5} missed 5-min ticks).
    Checked {cst_today().isoformat()} CST. Detail: docs/SPEC-RELIABILITY.md §3a.</p>
</div>"""


async def check_keepwarm(
    pool,
    *,
    to: Iterable[str] = TO_RECIPIENTS,
) -> dict[str, Any]:
    """Alert if either keep-warm pinger has stalled. Returns a diagnostic dict."""
    if pool is None:
        logger.warning("check_keepwarm: pool is None; skipping")
        return {"checked": False, "reason": "no_pool"}

    try:
        async with pool.acquire() as conn:
            records = await conn.fetch(
                f"""
                SELECT source,
                       last_seen,
                       ping_count,
                       max_gap_seconds,
                       EXTRACT(EPOCH FROM (NOW() - last_seen))::int  AS age_seconds,
                       (last_seen < NOW() - interval '{STALE_MINUTES} minutes') AS stale,
                       EXTRACT(EPOCH FROM (NOW() - window_start))::int AS window_seconds
                  FROM keepwarm_pings
                """
            )
    except Exception as e:
        logger.exception("check_keepwarm: query failed: %s", e)
        return {"checked": False, "reason": "query_failed", "error": str(e)}

    seen = {r["source"]: r for r in records}

    # Nothing recorded yet => the ledger just shipped and no ping has landed.
    # Stay silent rather than alarm on our own rollout.
    if not seen:
        logger.info("check_keepwarm: no pings recorded yet; skipping")
        return {"checked": True, "degraded": False, "reason": "no_pings_yet"}

    # Only expect a source to be present once the ledger has been live long
    # enough for it to have pinged — otherwise a fresh deploy alerts on itself.
    ledger_mature = max(r["window_seconds"] or 0 for r in records) > 3600

    rows: list[dict[str, Any]] = []
    problems: list[str] = []

    for source in (SOURCE_N8N, SOURCE_SYSTEMD):
        label = SOURCE_LABELS[source]
        r = seen.get(source)
        if r is None:
            if ledger_mature:
                problems.append(f"{label} — <b>never seen</b>: no ping has ever been recorded.")
                rows.append({"source": source, "stale": True, "age": "never",
                             "max_gap_seconds": None})
            continue

        age_min = (r["age_seconds"] or 0) // 60
        rows.append({
            "source": source,
            "stale": r["stale"],
            "age": f"{age_min} min ago" if age_min else "just now",
            "max_gap_seconds": r["max_gap_seconds"],
        })
        if r["stale"]:
            problems.append(f"{label} — <b>stalled</b>: last ping {age_min} min ago.")
        elif (r["max_gap_seconds"] or 0) > STALE_MINUTES * 60:
            problems.append(
                f"{label} — beating now, but had a "
                f"<b>{_fmt_gap(r['max_gap_seconds'])} gap</b> in the last 24h."
            )

    stats = {
        "sources": {
            r["source"]: {
                "age_seconds": r["age_seconds"],
                "stale": r["stale"],
                "ping_count": r["ping_count"],
                "max_gap_seconds": r["max_gap_seconds"],
            }
            for r in records
        },
        "ledger_mature": ledger_mature,
    }
    logger.info("check_keepwarm: %s, problems=%d", stats, len(problems))

    # Reset the rolling gap window so tomorrow's report covers only the next 24h.
    try:
        await pool.execute(
            "UPDATE keepwarm_pings SET max_gap_seconds = 0, window_start = NOW()"
        )
    except Exception as e:  # noqa: BLE001 - reporting matters more than the reset
        logger.warning("check_keepwarm: window reset failed: %s", e)

    if not problems:
        return {"checked": True, "degraded": False, **stats}

    return await _alert(to, rows, problems, stats)


async def _alert(to, rows, problems, stats) -> dict[str, Any]:
    if not settings.RESEND_API_KEY:
        logger.warning("check_keepwarm: degraded but RESEND_API_KEY not set")
        return {"checked": True, "degraded": True, "alerted": False,
                "reason": "no_resend_key", "problems": problems, **stats}
    to_list, blocked = partition_recipients([a for a in to if a])
    if blocked:
        logger.error(
            "check_keepwarm: dropped non-company recipients on: %s", ", ".join(blocked)
        )
    if not to_list:
        return {"checked": True, "degraded": True, "alerted": False,
                "reason": "no_recipients", "problems": problems, **stats}
    try:
        resend.api_key = settings.RESEND_API_KEY
        resend.Emails.send({
            "from": FROM_ADDRESS,
            "to": to_list,
            "subject": "[UNILINK Space] Backend keep-warm degraded — a pinger has stalled",
            "html": _render_html(rows, problems),
        })
        logger.info("check_keepwarm: alert sent to %d recipient(s)", len(to_list))
        return {"checked": True, "degraded": True, "alerted": True,
                "to": to_list, "problems": problems, **stats}
    except Exception as e:
        logger.exception("check_keepwarm: Resend send failed: %s", e)
        return {"checked": True, "degraded": True, "alerted": False,
                "reason": "resend_failed", "error": str(e), "problems": problems, **stats}
