"""Daily 7 AM CST email alert for Losses Lanes weekly movers.

Distribution (updated 2026-04-25):
    To:  Erick Mendoza (President & CEO), Christian Mendoza (Sr. VP DFW)
    CC:  Jennifer Alanis (Director DFW), Bruce Kimbark (CFO)
    BCC: Melany Salazar M., Diego F. Rodriguez

A single email is sent so CC recipients are visible to the To: line and
BCC recipients stay hidden. Previously this looped one send per address
to keep the To: line clean — that's no longer the right shape since
Erick/Christian need to see who else is on the thread.

Gracefully no-ops when:
    - ``settings.RESEND_API_KEY`` is empty (env var not set on Render)
    - ``app.state.savings_pool`` is unavailable (datalake down)

Scheduler wiring lives in ``app/main.py`` lifespan; this module exports
both the side-effecting ``send_weekly_movers_email`` entry point and
the pure ``render_html`` helper for easy unit testing.
"""

from __future__ import annotations

import logging
from datetime import date
from typing import Any, Iterable

import resend

from app.clock import cst_today
from app.config import settings
from app.routers.losses_lanes import compute_weekly_movers

logger = logging.getLogger(__name__)

TO_RECIPIENTS: tuple[str, ...] = (
    "emendoza@unilinktransportation.com",      # Erick Mendoza  — President & CEO
    "christian@unilinktransportation.com",     # Christian Mendoza — Sr. VP DFW Presidency
)
CC_RECIPIENTS: tuple[str, ...] = (
    "jennifer@unilinktransportation.com",      # Jennifer Alanis — Director DFW
    "bkimbark@unilinktransportation.com",      # Bruce Kimbark   — CFO Finance
)
BCC_RECIPIENTS: tuple[str, ...] = (
    "msalazarm@unilinktransportation.com",     # Melany Salazar M.
    "dfrodriguez@unilinktransportation.com",   # Diego F. Rodriguez
)

FROM_ADDRESS = "UNILINK Space <noreply@unilinkportal.com>"


# ---------------------------------------------------------------------------
# HTML rendering
# ---------------------------------------------------------------------------


def _fmt_usd(v: float | int | None) -> str:
    if v is None:
        return "—"
    try:
        n = float(v)
    except (TypeError, ValueError):
        return "—"
    sign = "-" if n < 0 else ""
    return f"{sign}${abs(n):,.0f}"


def _row_html(entry: dict[str, Any], kind: str) -> str:
    """Render one mover row. ``kind`` is 'new' | 'dropped' | 'moved'."""
    customer = entry.get("customer") or "—"
    lane = entry.get("lane") or "—"
    this_rank = entry.get("this_rank")
    last_rank = entry.get("last_rank")
    this_profit = entry.get("this_profit")
    last_profit = entry.get("last_profit")

    if kind == "new":
        badge = (
            f'<span style="background:#FEE2E2;color:#991B1B;padding:2px 8px;'
            f'border-radius:999px;font-size:11px;font-weight:600;">NEW · #{this_rank}</span>'
        )
    elif kind == "dropped":
        badge = (
            f'<span style="background:#D1FAE5;color:#065F46;padding:2px 8px;'
            f'border-radius:999px;font-size:11px;font-weight:600;">OUT · was #{last_rank}</span>'
        )
    else:
        delta = (last_rank or 0) - (this_rank or 0)
        bg, color = ("#FEE2E2", "#991B1B") if delta < 0 else ("#D1FAE5", "#065F46")
        arrow = "▼" if delta < 0 else "▲"
        badge = (
            f'<span style="background:{bg};color:{color};padding:2px 8px;'
            f'border-radius:999px;font-size:11px;font-weight:600;">'
            f"{arrow} #{last_rank} → #{this_rank}</span>"
        )

    return f"""
    <tr style="border-top:1px solid #F3F4F6;">
      <td style="padding:8px 10px;font-size:13px;color:#111827;vertical-align:top;">
        <div style="font-weight:600;">{customer}</div>
        <div style="color:#6B7280;font-size:12px;">{lane}</div>
      </td>
      <td style="padding:8px 10px;text-align:right;vertical-align:top;">
        {badge}
      </td>
      <td style="padding:8px 10px;text-align:right;font-size:12px;color:#B91C1C;font-weight:600;vertical-align:top;">
        {_fmt_usd(this_profit)}
      </td>
      <td style="padding:8px 10px;text-align:right;font-size:12px;color:#6B7280;vertical-align:top;">
        {_fmt_usd(last_profit)}
      </td>
    </tr>
    """


def _section(title: str, entries: Iterable[dict[str, Any]], kind: str, tone: str) -> str:
    entries = list(entries)
    color_map = {
        "red":     ("#FEE2E2", "#991B1B"),
        "green":   ("#D1FAE5", "#065F46"),
        "neutral": ("#F3F4F6", "#374151"),
    }
    bg, fg = color_map.get(tone, color_map["neutral"])
    body = (
        "".join(_row_html(e, kind) for e in entries)
        if entries
        else """
        <tr><td colspan="4" style="padding:16px;text-align:center;font-size:12px;color:#6B7280;">
          No changes in this category.
        </td></tr>
        """
    )
    return f"""
    <div style="margin-bottom:24px;border:1px solid #E5E7EB;border-radius:8px;overflow:hidden;">
      <div style="background:{bg};color:{fg};padding:8px 12px;font-size:11px;font-weight:700;letter-spacing:0.05em;text-transform:uppercase;">
        {title} <span style="font-weight:400;">({len(entries)})</span>
      </div>
      <table style="width:100%;border-collapse:collapse;background:#FFFFFF;">
        <thead>
          <tr style="background:#F9FAFB;">
            <th style="padding:6px 10px;text-align:left;font-size:10px;color:#6B7280;text-transform:uppercase;letter-spacing:0.05em;">Customer / Lane</th>
            <th style="padding:6px 10px;text-align:right;font-size:10px;color:#6B7280;text-transform:uppercase;letter-spacing:0.05em;">Rank change</th>
            <th style="padding:6px 10px;text-align:right;font-size:10px;color:#6B7280;text-transform:uppercase;letter-spacing:0.05em;">This week</th>
            <th style="padding:6px 10px;text-align:right;font-size:10px;color:#6B7280;text-transform:uppercase;letter-spacing:0.05em;">Last week</th>
          </tr>
        </thead>
        <tbody>{body}</tbody>
      </table>
    </div>
    """


def render_html(data: dict[str, Any], portal_url: str) -> str:
    """Pure function: payload dict -> email HTML string."""
    window = data.get("window", {})
    this_w = window.get("this_week", {})
    last_w = window.get("last_week", {})
    top_n = window.get("top_n", 10)
    today = cst_today().isoformat()

    return f"""
    <!DOCTYPE html>
    <html><body style="margin:0;padding:0;background:#F9FAFB;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;">
      <div style="max-width:720px;margin:0 auto;padding:24px;">
        <div style="background:#1B3A5C;color:#FFFFFF;padding:20px 24px;border-radius:8px 8px 0 0;">
          <div style="font-size:12px;letter-spacing:0.1em;text-transform:uppercase;opacity:0.7;">UNILINK Space · Daily Alert</div>
          <h1 style="margin:6px 0 4px 0;font-size:22px;font-weight:700;">Top Losses — Weekly Movers</h1>
          <div style="font-size:13px;opacity:0.85;">
            Top-{top_n} losing (customer, lane) pairs · week over week
          </div>
          <div style="font-size:12px;opacity:0.7;margin-top:6px;">
            This week: {this_w.get('start','?')} → {this_w.get('end','?')} · Last week: {last_w.get('start','?')} → {last_w.get('end','?')}
          </div>
        </div>
        <div style="background:#FFFFFF;padding:24px;border-radius:0 0 8px 8px;border:1px solid #E5E7EB;border-top:none;">
          {_section("New entries (worse this week)", data.get("new_entries", []), "new", "red")}
          {_section("Dropped out (better this week)", data.get("dropped", []), "dropped", "green")}
          {_section("Rank change (still in top)", data.get("moved", []), "moved", "neutral")}
          <div style="margin-top:24px;padding-top:16px;border-top:1px solid #E5E7EB;font-size:11px;color:#6B7280;text-align:center;">
            <a href="{portal_url}/reports/losses-lanes?tab=movers" style="color:#2563EB;text-decoration:none;font-weight:600;">Open the Losses Lanes report →</a>
            <div style="margin-top:8px;">Delivered {today} · Source: mcleod_gld_budget_report_v4 · Scope: TEAM1-5 + TEAM-DFW</div>
          </div>
        </div>
      </div>
    </body></html>
    """


# ---------------------------------------------------------------------------
# Send entry point
# ---------------------------------------------------------------------------


async def send_weekly_movers_email(
    pool,
    *,
    to: Iterable[str] = TO_RECIPIENTS,
    cc: Iterable[str] = CC_RECIPIENTS,
    bcc: Iterable[str] = BCC_RECIPIENTS,
    top_n: int = 10,
    portal_url: str = "https://space.unilinkportal.com",
) -> dict[str, Any]:
    """Compose & send the weekly-movers digest.

    Returns a diagnostic dict with status + counts so the scheduler can log
    it. Never raises; swallows and logs exceptions so a transient failure
    doesn't take down the next day's job.
    """
    if not settings.RESEND_API_KEY:
        logger.warning(
            "send_weekly_movers_email: RESEND_API_KEY not set; skipping send"
        )
        return {"sent": False, "reason": "no_resend_key"}

    if pool is None:
        logger.warning("send_weekly_movers_email: savings_pool is None; skipping")
        return {"sent": False, "reason": "no_pool"}

    try:
        data = await compute_weekly_movers(pool, top_n=top_n)
    except Exception as e:
        logger.exception("send_weekly_movers_email: query failed: %s", e)
        return {"sent": False, "reason": "query_failed", "error": str(e)}

    total_changes = (
        len(data["new_entries"]) + len(data["dropped"]) + len(data["moved"])
    )
    html = render_html(data, portal_url)

    subject = (
        f"[UNILINK Space] Losses Lanes — {len(data['new_entries'])} new, "
        f"{len(data['dropped'])} out, {len(data['moved'])} moved "
        f"(Top-{top_n}, {cst_today().isoformat()})"
    )

    resend.api_key = settings.RESEND_API_KEY
    to_list = list(to)
    cc_list = list(cc)
    bcc_list = list(bcc)

    if not to_list:
        logger.warning("send_weekly_movers_email: empty TO list; skipping send")
        return {"sent": False, "reason": "no_to_recipients"}

    try:
        # Single send: To: line shows Erick + Christian, CC line shows Jennifer
        # + Bruce, BCC stays hidden (Melany + Diego). Resend Python SDK accepts
        # `to`, `cc`, `bcc` as either string or list.
        payload: dict[str, Any] = {
            "from": FROM_ADDRESS,
            "to": to_list,
            "subject": subject,
            "html": html,
        }
        if cc_list:
            payload["cc"] = cc_list
        if bcc_list:
            payload["bcc"] = bcc_list
        resend.Emails.send(payload)
        logger.info(
            "send_weekly_movers_email: sent (to=%d cc=%d bcc=%d), %d total changes",
            len(to_list), len(cc_list), len(bcc_list), total_changes,
        )
        return {
            "sent": True,
            "to":  to_list,
            "cc":  cc_list,
            "bcc": bcc_list,
            "changes": {
                "new": len(data["new_entries"]),
                "dropped": len(data["dropped"]),
                "moved": len(data["moved"]),
            },
            "subject": subject,
        }
    except Exception as e:
        logger.exception("send_weekly_movers_email: Resend send failed: %s", e)
        return {"sent": False, "reason": "resend_failed", "error": str(e)}
