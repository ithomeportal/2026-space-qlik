"""Ops Portal Overview — "Team" (Team Monthly Performance) email digest.

Bruno round (2026-07-01) R9: deliver the on-page "Team" button data (the per-
team Team Monthly Performance table: Total + TEAM1..TEAM5) to
janaya@unilinktransportation.com twice daily (06:00 + 18:00 CST).

Sent via Microsoft Graph from the internal ithome@ mailbox (recipient is
internal, so this avoids the external-sender banner Resend/noreply@ would show).
The data is read in-process via ASGITransport against the exact
``/team-performance-by-team`` endpoint the UI uses, so the email always matches
the report (month-to-date scope, no filters — same as the panel's default).

Never raises — returns a diagnostic dict so the scheduler can log-and-swallow.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any, Optional

import httpx

from app.clock import cst_today
from app.config import settings
from app.services.msgraph_mailer import send_mail

logger = logging.getLogger(__name__)

DEFAULT_PORTAL_URL = "https://space.unilinkportal.com"

# Outlook resets font-family inside nested tables — declare inline on every td.
FONT_STACK = (
    "'Segoe UI',-apple-system,BlinkMacSystemFont,Arial,Helvetica,Verdana,sans-serif"
)
MONO_STACK = "Consolas,'SF Mono',Menlo,'Courier New',monospace"

# Row spec — mirrors TeamMonthlyModal.ROWS (label, field, kind). "kind" drives
# formatting: count | usd | usdSigned | pct | pctSigned | days | costXLoad.
_ROWS: tuple[tuple[str, str, str], ...] = (
    ("Customers",          "customers",   "count"),
    ("Lanes",              "lanes",       "count"),
    ("Volume",             "volume",      "count"),
    ("Revenue",            "revenue",     "usd"),
    ("Total Cost",         "total_cost",  "usd"),
    ("Profit",             "profit",      "usdSigned"),
    ("Margin P %",         "margin_pct",  "pctSigned"),
    ("Rev. x L.",          "rev_x_l",     "usd"),
    ("Prf. X L.",          "prof_x_l",    "usdSigned"),
    ("Cost x Load",        "cost_x_load", "costXLoad"),
    ("Team Ut.",           "team_ut",     "pct"),
    ("OTP.",               "otp_pct",     "pct"),
    ("Lates PU",           "lates_pu",    "count"),
    ("OTD.",               "otd_pct",     "pct"),
    ("Lates DEL.",         "lates_del",   "count"),
    ("Savings.",           "savings",     "usd"),
    ("Over Pay",           "over_pay",    "usdSigned"),
    ("Net Savings",        "net_savings", "usdSigned"),
    ("Loads w/ Loss.",     "loss_loads",  "count"),
    ("Profit Loss",        "profit_loss", "usdSigned"),
    # Bruno round (2026-07-01) R12 — below Profit Loss.
    ("AVG Days (Billed)",     "avg_days_billed",     "days"),
    ("AVG Days (Not Billed)", "avg_days_not_billed", "days"),
    ("% Del vs Bill",         "pct_del_bill",        "pct"),
    ("Cust. Attrition %",     "cust_attr_pct",       "pct"),
    ("Lane Attrition %",      "lane_attr_pct",       "pct"),
)


def _fmt(value: Any, kind: str) -> str:
    try:
        n = float(value or 0)
    except (TypeError, ValueError):
        n = 0.0
    if kind == "count":
        return f"{int(round(n)):,}"
    if kind in ("usd", "usdSigned"):
        return ("-" if n < 0 else "") + f"${abs(n):,.0f}"
    if kind in ("pct", "pctSigned"):
        return f"{n:.2f}%"
    if kind in ("days", "costXLoad"):
        return f"{n:,.1f}" if kind == "days" else ("-" if n < 0 else "") + f"${abs(n):,.0f}"
    return str(value)


def _cell_color(value: Any, kind: str) -> str:
    """Negatives red for the signed kinds; otherwise neutral dark."""
    try:
        n = float(value or 0)
    except (TypeError, ValueError):
        n = 0.0
    if kind in ("usdSigned", "pctSigned") and n < 0:
        return "#DC2626"
    return "#111827"


def _field_val(obj: dict, field: str) -> Any:
    if field == "cost_x_load":
        vol = float(obj.get("volume") or 0)
        return (float(obj.get("total_cost") or 0) / vol) if vol else 0.0
    return obj.get(field, 0)


def render_html(*, total: dict, teams: list[dict], today, portal_url: str) -> str:
    team_ids = [t.get("team_id", "") for t in teams]
    # Header row: METRIC | Total | TEAM1.. .
    head_cells = "".join(
        f'<th style="padding:8px 10px;text-align:right;font-family:{FONT_STACK};'
        f'font-size:10px;color:#1B3A5C;text-transform:uppercase;letter-spacing:0.04em;'
        f'font-weight:700;border-bottom:2px solid #E5E7EB;">{tid}</th>'
        for tid in (["Total"] + team_ids)
    )
    body_rows = []
    for label, field, kind in _ROWS:
        cells = []
        for obj in [total] + teams:
            v = _field_val(obj, field)
            cells.append(
                f'<td style="padding:6px 10px;text-align:right;font-family:{FONT_STACK};'
                f'font-size:12px;color:{_cell_color(v, kind)};font-variant-numeric:tabular-nums;'
                f'border-bottom:1px solid #F3F4F6;">{_fmt(v, kind)}</td>'
            )
        body_rows.append(
            f'<tr><td style="padding:6px 10px;font-family:{FONT_STACK};font-size:12px;'
            f'color:#374151;font-weight:600;border-bottom:1px solid #F3F4F6;">{label}</td>'
            + "".join(cells) + "</tr>"
        )
    rows_html = "".join(body_rows)
    return f"""\
<!DOCTYPE html><html><body style="margin:0;padding:0;background:#F3F4F6;">
  <table cellpadding="0" cellspacing="0" border="0" width="100%" style="background:#F3F4F6;font-family:{FONT_STACK};">
    <tr><td align="center" style="padding:20px;font-family:{FONT_STACK};">
      <table cellpadding="0" cellspacing="0" border="0" width="720" style="background:#FFFFFF;border:1px solid #E5E7EB;border-radius:8px;font-family:{FONT_STACK};">
        <tr><td style="background:#1B3A5C;padding:18px 24px;border-radius:8px 8px 0 0;font-family:{FONT_STACK};">
          <div style="font-family:{FONT_STACK};font-size:16px;font-weight:800;color:#FFFFFF;">Team Monthly Performance</div>
          <div style="font-family:{FONT_STACK};font-size:11px;color:#BFDBFE;margin-top:2px;">Ops Portal — CORP · Month-to-date · {today.isoformat()}</div>
        </td></tr>
        <tr><td style="padding:16px 20px;font-family:{FONT_STACK};">
          <table cellpadding="0" cellspacing="0" border="0" width="100%" style="border-collapse:collapse;font-family:{FONT_STACK};">
            <thead><tr>
              <th style="padding:8px 10px;text-align:left;font-family:{FONT_STACK};font-size:10px;color:#1B3A5C;text-transform:uppercase;letter-spacing:0.04em;font-weight:700;border-bottom:2px solid #E5E7EB;">Metric</th>
              {head_cells}
            </tr></thead>
            <tbody>{rows_html}</tbody>
          </table>
        </td></tr>
        <tr><td style="padding:0 20px 18px 20px;text-align:center;font-family:{FONT_STACK};">
          <a href="{portal_url}/reports/ops-portal-overview" style="display:inline-block;background:#1B3A5C;color:#FFFFFF;padding:10px 18px;border-radius:6px;text-decoration:none;font-family:{FONT_STACK};font-size:13px;font-weight:600;">Open Ops Portal →</a>
          <div style="font-family:{FONT_STACK};font-size:11px;color:#9CA3AF;margin-top:12px;">
            Source: <code style="font-family:{MONO_STACK};color:#111827;">ops-portal-overview / team-performance-by-team</code>
            · Sent {today.isoformat()} 06:00 &amp; 18:00 CST
          </div>
        </td></tr>
      </table>
    </td></tr>
  </table>
</body></html>"""


async def _fetch_team_data(app) -> Optional[dict]:
    """In-process call to the exact endpoint the "Team" button uses."""
    # Admin bypasses require_report_access (deps.py) → runs the same SQL users hit.
    auth = 'Bearer {"sub":"digest","email":"digest@internal","name":"digest","roles":["admin"]}'
    # In-process via ASGITransport, but require_user cannot tell that apart from a
    # network call — so the internal callers must carry the proxy secret too.
    headers = {"authorization": auth}
    if settings.PROXY_SHARED_SECRET:
        headers["x-proxy-secret"] = settings.PROXY_SHARED_SECRET
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    async with httpx.AsyncClient(
        transport=transport, base_url="http://digest.internal", timeout=60.0,
    ) as client:
        res = await client.get(
            "/api/custom/ops-portal-overview/team-performance-by-team",
            params={"range": "mtd"},
            headers=headers,
        )
    if res.status_code != 200:
        logger.warning("Ops team digest: endpoint returned %s", res.status_code)
        return None
    payload = res.json()
    return payload.get("data") if payload.get("success") else None


async def send_team_digest(
    app,
    *,
    to: list[str],
    cc: Optional[list[str]] = None,
    bcc: Optional[list[str]] = None,
    portal_url: str = DEFAULT_PORTAL_URL,
) -> dict[str, Any]:
    """Compute the Team Monthly Performance digest and dispatch via MS Graph.

    Never raises. Returns a diagnostic dict (sent / reason / error)."""
    if not (settings.MS_TENANT_ID and settings.MS_CLIENT_ID and settings.MS_CLIENT_SECRET):
        return {"sent": False, "reason": "missing_msgraph_config"}

    today = cst_today()
    try:
        data = await _fetch_team_data(app)
    except Exception as e:  # noqa: BLE001 — scheduler must never crash
        logger.exception("Ops team digest: fetch failed: %s", e)
        return {"sent": False, "reason": "fetch_failed", "error": str(e)}
    if not data:
        return {"sent": False, "reason": "no_data"}

    total = data.get("total") or {}
    teams = data.get("teams") or []
    html = render_html(total=total, teams=teams, today=today, portal_url=portal_url)

    profit_str = _fmt(total.get("profit"), "usdSigned")
    subject = (
        f"[UNILINK Space] Team Monthly Performance — {profit_str} Profit MTD "
        f"({today.isoformat()})"
    )
    return await send_mail(
        tenant_id=settings.MS_TENANT_ID,
        client_id=settings.MS_CLIENT_ID,
        client_secret=settings.MS_CLIENT_SECRET,
        from_address=settings.MS_SEND_FROM or "ithome@unilinktransportation.com",
        to=to,
        cc=cc,
        bcc=bcc,
        subject=subject,
        html_body=html,
    )
