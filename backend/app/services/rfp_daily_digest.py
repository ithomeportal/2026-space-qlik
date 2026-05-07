"""Daily 5:30 PM CST RFP Performance email digest.

Composes a 2-column HTML email summarising the live "Performance for RFPs"
report at https://space.unilinkportal.com/reports/rfp-performance and
sends it via Microsoft Graph from ``ithome@unilinktransportation.com``.

Layout
------
- LEFT 50%  : 2 KPI cards (Awarded Revenue $ + Awarded Convertio Ratio %)
              with YTD-vs-LY, MTD-vs-LM and QTD-vs-LQ comparisons.
- RIGHT 50% : the "Convertio Ratio by Status Won and Lost" table —
              same 0.5%→5% sensitivity grid the user sees on the page.

Comparison windows (all apples-to-apples up to *today*):
- YTD : Jan 1 → today (current year)             vs Jan 1 → today−365d
- MTD : 1st-of-month → today                     vs 1st of last month → same day-of-month
- QTD : 1st-of-quarter → today                   vs 1st of last quarter → matching elapsed days

Data source
-----------
``automations_db.public.rfp_results_history`` (Aiven), produced by
n8n daily at 01:00 CST. Uses the same SQL building blocks as
``app.routers.rfp_performance`` so the digest can never drift from the
on-screen numbers.
"""

from __future__ import annotations

import asyncio
import logging
from calendar import monthrange
from datetime import date
from typing import Any

from app.clock import cst_today
from app.config import settings
from app.routers.rfp_performance import CLOSED_STATUSES
from app.services.msgraph_mailer import send_mail

logger = logging.getLogger(__name__)

DEFAULT_PORTAL_URL = "https://space.unilinkportal.com"

# Outlook-safe font stack. Order matters:
#   1. Segoe UI  -> Outlook 365 desktop on Windows (Erick, Jaime, Pricing team)
#   2. -apple-system / BlinkMacSystemFont -> SF Pro on macOS Outlook + Apple Mail
#   3. Arial / Helvetica / Verdana -> universal fallback for OWA, Gmail, Android
#   4. sans-serif -> last-resort generic
#
# Outlook resets font-family inside nested <table> boundaries, so this stack
# MUST be declared inline on every wrapper <table>/<td>, NOT only on <body>.
# Otherwise headings + KPI numbers fall back to Times New Roman (CEO feedback,
# 2026-05-06).
FONT_STACK = (
    "'Segoe UI',-apple-system,BlinkMacSystemFont,Arial,Helvetica,Verdana,sans-serif"
)
MONO_STACK = "Consolas,'SF Mono',Menlo,'Courier New',monospace"


# ---------------------------------------------------------------------------
# Period math
# ---------------------------------------------------------------------------


def _add_years(d: date, years: int) -> date:
    """Subtract ``years`` from ``d``, clamping Feb 29 to Feb 28 in non-leap."""
    try:
        return d.replace(year=d.year + years)
    except ValueError:
        # Feb 29 in a non-leap target year
        return d.replace(year=d.year + years, day=28)


def _last_day_of_month(year: int, month: int) -> int:
    return monthrange(year, month)[1]


def _shift_month(d: date, months: int) -> date:
    """Shift ``d`` by ``months``, clamping the day-of-month if the target month
    is shorter (e.g. Mar 31 - 1 month → Feb 28/29)."""
    total = d.month - 1 + months
    new_year = d.year + total // 12
    new_month = total % 12 + 1
    new_day = min(d.day, _last_day_of_month(new_year, new_month))
    return date(new_year, new_month, new_day)


def _quarter_start(d: date) -> date:
    q_start_month = ((d.month - 1) // 3) * 3 + 1
    return date(d.year, q_start_month, 1)


def _periods(today: date) -> dict[str, tuple[date, date]]:
    """Return the 6 (start, end_inclusive) windows used in the digest."""
    from datetime import timedelta

    # YTD: Jan 1 → today  vs  same range last year
    ytd_start = date(today.year, 1, 1)
    ytd_end = today
    ly_ytd_start = _add_years(ytd_start, -1)
    ly_ytd_end = _add_years(today, -1)

    # MTD: 1st of this month → today  vs  1st of LM → same day-of-month in LM
    mtd_start = date(today.year, today.month, 1)
    mtd_end = today
    lm_start = _shift_month(mtd_start, -1)
    lm_last = _last_day_of_month(lm_start.year, lm_start.month)
    lm_end = date(lm_start.year, lm_start.month, min(today.day, lm_last))

    # QTD: 1st of this quarter → today  vs  same elapsed-days into last quarter
    q_start = _quarter_start(today)
    q_end = today
    elapsed_days = (today - q_start).days
    last_q_start = _shift_month(q_start, -3)
    last_q_end = last_q_start + timedelta(days=elapsed_days)
    prev_q_last = q_start - timedelta(days=1)  # last day of the previous quarter
    if last_q_end > prev_q_last:
        last_q_end = prev_q_last

    return {
        "ytd": (ytd_start, ytd_end),
        "ytd_ly": (ly_ytd_start, ly_ytd_end),
        "mtd": (mtd_start, mtd_end),
        "lm": (lm_start, lm_end),
        "qtd": (q_start, q_end),
        "lq": (last_q_start, last_q_end),
    }


# ---------------------------------------------------------------------------
# SQL helpers — minimal queries instead of going through HTTP
# ---------------------------------------------------------------------------


_KPI_SQL = """
WITH base AS (
  SELECT *
  FROM rfp_results_history
  WHERE submitted_date >= $1
    AND submitted_date <  ($2::date + 1)
)
SELECT
  COALESCE(SUM(potential_revenue), 0)::numeric                                  AS grand_pot_rev,
  COALESCE(SUM(rfp_revenue) FILTER (WHERE status = 'Won'), 0)::numeric          AS won_awarded_revenue
FROM base
"""

_CONVERTIO_SQL = f"""
WITH base AS (
  SELECT *
  FROM rfp_results_history
  WHERE submitted_date >= date_trunc('year', CURRENT_DATE)
    AND submitted_date <  date_trunc('year', CURRENT_DATE) + INTERVAL '1 year'
),
totals AS (
  SELECT
    COALESCE(SUM(potential_revenue) FILTER (WHERE status = ANY($1)), 0)::numeric AS pot_rev_closed,
    COALESCE(SUM(rfp_revenue)       FILTER (WHERE status = 'Won'), 0)::numeric    AS revenue_awarded
  FROM base
),
ratios AS (
  SELECT generate_series(0.005, 0.05, 0.005)::numeric AS ratio
)
SELECT
  r.ratio,
  ROUND(t.pot_rev_closed * r.ratio, 0)::numeric                            AS revenue_awarded_at_ratio,
  ROUND(t.revenue_awarded - t.pot_rev_closed * r.ratio, 0)::numeric        AS actual_vs_conv_ratio,
  ROUND(t.pot_rev_closed * r.ratio * 0.15, 0)::numeric                     AS pot_rev_gp_15,
  t.pot_rev_closed,
  t.revenue_awarded
FROM ratios r CROSS JOIN totals t
ORDER BY r.ratio DESC
"""


async def _kpi_window(pool, start: date, end: date) -> dict[str, float]:
    row = await pool.fetchrow(_KPI_SQL, start, end)
    grand = float(row["grand_pot_rev"] or 0)
    awarded = float(row["won_awarded_revenue"] or 0)
    return {
        "awarded_revenue": awarded,
        "grand_pot_rev": grand,
        "awarded_convertio_ratio": (awarded / grand) if grand else None,
    }


async def _convertio_table(pool) -> dict[str, Any]:
    rows = await pool.fetch(_CONVERTIO_SQL, CLOSED_STATUSES)
    pot_rev_closed = float(rows[0]["pot_rev_closed"] or 0) if rows else 0.0
    revenue_awarded = float(rows[0]["revenue_awarded"] or 0) if rows else 0.0
    table = [
        {
            "ratio": float(r["ratio"]),
            "revenue_awarded_at_ratio": float(r["revenue_awarded_at_ratio"]),
            "actual_vs_conv_ratio": float(r["actual_vs_conv_ratio"]),
            "pot_rev_gp_15": float(r["pot_rev_gp_15"]),
        }
        for r in rows
    ]
    return {
        "pot_rev_closed": pot_rev_closed,
        "revenue_awarded": revenue_awarded,
        "rows": table,
    }


# ---------------------------------------------------------------------------
# Formatting
# ---------------------------------------------------------------------------


def _fmt_money(v: float | int | None) -> str:
    if v is None:
        return "—"
    try:
        n = float(v)
    except (TypeError, ValueError):
        return "—"
    sign = "-" if n < 0 else ""
    absn = abs(n)
    if absn >= 1_000_000_000:
        return f"{sign}${absn / 1_000_000_000:,.2f}B"
    if absn >= 1_000_000:
        return f"{sign}${absn / 1_000_000:,.2f}M"
    if absn >= 1_000:
        return f"{sign}${absn / 1_000:,.1f}K"
    return f"{sign}${absn:,.0f}"


def _fmt_pct(v: float | None, *, decimals: int = 2) -> str:
    if v is None:
        return "—"
    return f"{v * 100:.{decimals}f}%"


def _fmt_pct_change(curr: float | None, prev: float | None) -> tuple[str, str, str]:
    """Return (sign_arrow, formatted, tone).

    tone in {'green','red','neutral'} — green when curr beats prev for
    "more is better" KPIs (which is what the digest shows).
    """
    if curr is None or prev is None or prev == 0:
        return ("·", "—", "neutral")
    delta = (curr - prev) / abs(prev)
    if delta > 0:
        return ("▲", f"+{delta * 100:.1f}%", "green")
    if delta < 0:
        return ("▼", f"{delta * 100:.1f}%", "red")
    return ("·", "0.0%", "neutral")


def _fmt_pp_change(curr: float | None, prev: float | None) -> tuple[str, str, str]:
    """Difference in percentage points (for ratio KPIs)."""
    if curr is None or prev is None:
        return ("·", "—", "neutral")
    pp = (curr - prev) * 100
    if pp > 0:
        return ("▲", f"+{pp:.2f}pp", "green")
    if pp < 0:
        return ("▼", f"{pp:.2f}pp", "red")
    return ("·", "0.00pp", "neutral")


_TONE_BG = {"green": "#D1FAE5", "red": "#FEE2E2", "neutral": "#F3F4F6"}
_TONE_FG = {"green": "#065F46", "red": "#991B1B", "neutral": "#374151"}


# ---------------------------------------------------------------------------
# HTML rendering
# ---------------------------------------------------------------------------


def _delta_pill(arrow: str, text: str, tone: str, prev_label: str, prev_value: str) -> str:
    bg = _TONE_BG[tone]
    fg = _TONE_FG[tone]
    return f"""
    <tr>
      <td style="padding:6px 0;font-family:{FONT_STACK};font-size:12px;color:#374151;">
        <span style="display:inline-block;background:{bg};color:{fg};padding:2px 8px;border-radius:999px;font-family:{FONT_STACK};font-size:11px;font-weight:700;letter-spacing:0.02em;">{arrow} {text}</span>
        <span style="color:#6B7280;font-family:{FONT_STACK};font-size:11px;margin-left:8px;">vs {prev_label} · {prev_value}</span>
      </td>
    </tr>
    """


def _kpi_card_money(label: str, current: float, comparisons: list[tuple[str, float]]) -> str:
    """Money-valued KPI card (Awarded Revenue $).

    ``comparisons`` is a list of (prev_label, prev_value) pairs for YTD/LY,
    MTD/LM, QTD/LQ.
    """
    rows = []
    for prev_label, prev_value in comparisons:
        arrow, text, tone = _fmt_pct_change(current, prev_value)
        rows.append(_delta_pill(arrow, text, tone, prev_label, _fmt_money(prev_value)))
    return f"""
    <table cellpadding="0" cellspacing="0" border="0" width="100%" style="background:#FFFFFF;border:1px solid #E5E7EB;border-radius:8px;margin-bottom:16px;font-family:{FONT_STACK};">
      <tr><td style="padding:18px 20px;font-family:{FONT_STACK};">
        <div style="font-family:{FONT_STACK};font-size:10px;color:#6B7280;letter-spacing:0.1em;text-transform:uppercase;font-weight:700;">{label}</div>
        <div style="font-family:{FONT_STACK};font-size:30px;font-weight:800;color:#111827;line-height:1.1;margin-top:6px;letter-spacing:-0.01em;">{_fmt_money(current)}</div>
        <div style="font-family:{FONT_STACK};font-size:11px;color:#6B7280;margin-top:2px;">YTD ({date.today().year})</div>
        <table cellpadding="0" cellspacing="0" border="0" width="100%" style="margin-top:14px;border-top:1px solid #F3F4F6;font-family:{FONT_STACK};">
          {''.join(rows)}
        </table>
      </td></tr>
    </table>
    """


def _kpi_card_ratio(label: str, current: float | None, comparisons: list[tuple[str, float | None]]) -> str:
    """Ratio-valued KPI card (Awarded Convertio Ratio %)."""
    rows = []
    for prev_label, prev_value in comparisons:
        arrow, text, tone = _fmt_pp_change(current, prev_value)
        rows.append(_delta_pill(arrow, text, tone, prev_label, _fmt_pct(prev_value, decimals=2)))
    return f"""
    <table cellpadding="0" cellspacing="0" border="0" width="100%" style="background:#FFFFFF;border:1px solid #E5E7EB;border-radius:8px;margin-bottom:16px;font-family:{FONT_STACK};">
      <tr><td style="padding:18px 20px;font-family:{FONT_STACK};">
        <div style="font-family:{FONT_STACK};font-size:10px;color:#6B7280;letter-spacing:0.1em;text-transform:uppercase;font-weight:700;">{label}</div>
        <div style="font-family:{FONT_STACK};font-size:30px;font-weight:800;color:#111827;line-height:1.1;margin-top:6px;letter-spacing:-0.01em;">{_fmt_pct(current, decimals=2)}</div>
        <div style="font-family:{FONT_STACK};font-size:11px;color:#6B7280;margin-top:2px;">YTD ({date.today().year})</div>
        <table cellpadding="0" cellspacing="0" border="0" width="100%" style="margin-top:14px;border-top:1px solid #F3F4F6;font-family:{FONT_STACK};">
          {''.join(rows)}
        </table>
      </td></tr>
    </table>
    """


def _convertio_table_html(table: dict[str, Any]) -> str:
    rows_html = []
    for r in table["rows"]:
        delta = r["actual_vs_conv_ratio"]
        if delta > 0:
            bg, fg = "#DCFCE7", "#166534"
        elif delta < 0:
            bg, fg = "#FEE2E2", "#991B1B"
        else:
            bg, fg = "#FFFFFF", "#374151"
        rows_html.append(f"""
        <tr style="border-top:1px solid #F3F4F6;">
          <td style="padding:7px 10px;font-family:{FONT_STACK};font-size:12px;font-weight:600;color:#111827;font-variant-numeric:tabular-nums;">{r['ratio'] * 100:.2f}%</td>
          <td style="padding:7px 10px;text-align:right;font-family:{FONT_STACK};font-size:12px;color:#374151;font-variant-numeric:tabular-nums;">{_fmt_money(r['revenue_awarded_at_ratio'])}</td>
          <td style="padding:7px 10px;text-align:right;font-family:{FONT_STACK};font-size:12px;font-weight:700;background:{bg};color:{fg};font-variant-numeric:tabular-nums;">{_fmt_money(delta)}</td>
          <td style="padding:7px 10px;text-align:right;font-family:{FONT_STACK};font-size:12px;color:#374151;font-variant-numeric:tabular-nums;">{_fmt_money(r['pot_rev_gp_15'])}</td>
        </tr>
        """)
    return f"""
    <table cellpadding="0" cellspacing="0" border="0" width="100%" style="background:#FFFFFF;border:1px solid #E5E7EB;border-radius:8px;font-family:{FONT_STACK};">
      <tr><td style="padding:16px 18px 8px 18px;font-family:{FONT_STACK};">
        <div style="font-family:{FONT_STACK};font-size:13px;font-weight:700;color:#111827;">Convertio Ratio by Status Won and Lost</div>
        <div style="font-family:{FONT_STACK};font-size:11px;color:#6B7280;margin-top:4px;">
          Potential Revenue Closed: <strong style="font-family:{FONT_STACK};color:#111827;">{_fmt_money(table['pot_rev_closed'])}</strong>
          &nbsp;·&nbsp;
          Revenue Awarded: <strong style="font-family:{FONT_STACK};color:#111827;">{_fmt_money(table['revenue_awarded'])}</strong>
        </div>
      </td></tr>
      <tr><td style="padding:0 8px 12px 8px;">
        <table cellpadding="0" cellspacing="0" border="0" width="100%" style="border-collapse:collapse;font-family:{FONT_STACK};">
          <thead>
            <tr style="background:#ECFDF5;">
              <th style="padding:8px 10px;text-align:left;font-family:{FONT_STACK};font-size:10px;color:#065F46;text-transform:uppercase;letter-spacing:0.05em;font-weight:700;">Convertio Ratio</th>
              <th style="padding:8px 10px;text-align:right;font-family:{FONT_STACK};font-size:10px;color:#065F46;text-transform:uppercase;letter-spacing:0.05em;font-weight:700;">Revenue Awarded</th>
              <th style="padding:8px 10px;text-align:right;font-family:{FONT_STACK};font-size:10px;color:#065F46;text-transform:uppercase;letter-spacing:0.05em;font-weight:700;">Actual vs Conv. Ratio</th>
              <th style="padding:8px 10px;text-align:right;font-family:{FONT_STACK};font-size:10px;color:#065F46;text-transform:uppercase;letter-spacing:0.05em;font-weight:700;">Pot Rev GP 15%</th>
            </tr>
          </thead>
          <tbody>{''.join(rows_html)}</tbody>
        </table>
      </td></tr>
      <tr><td style="padding:0 18px 14px 18px;font-family:{FONT_STACK};font-size:10px;color:#9CA3AF;">
        Green = Actual outperforms ratio · Red = Actual underperforms · Current calendar year.
      </td></tr>
    </table>
    """


def render_html(
    *,
    today: date,
    kpi_ytd: dict[str, float],
    kpi_ly_ytd: dict[str, float],
    kpi_mtd: dict[str, float],
    kpi_lm: dict[str, float],
    kpi_qtd: dict[str, float],
    kpi_lq: dict[str, float],
    convertio: dict[str, Any],
    portal_url: str = DEFAULT_PORTAL_URL,
) -> str:
    """Pure function: dataset -> Outlook-safe HTML."""
    awarded_card = _kpi_card_money(
        "Awarded Revenue",
        kpi_ytd["awarded_revenue"],
        [
            ("LY (YTD)", kpi_ly_ytd["awarded_revenue"]),
            ("Last Month", kpi_lm["awarded_revenue"]),
            ("Last Quarter", kpi_lq["awarded_revenue"]),
        ],
    )
    ratio_card = _kpi_card_ratio(
        "Awarded Convertio Ratio",
        kpi_ytd["awarded_convertio_ratio"],
        [
            ("LY (YTD)", kpi_ly_ytd["awarded_convertio_ratio"]),
            ("Last Month", kpi_lm["awarded_convertio_ratio"]),
            ("Last Quarter", kpi_lq["awarded_convertio_ratio"]),
        ],
    )

    # MTD / QTD context strip below the cards
    context_strip = f"""
    <table cellpadding="0" cellspacing="0" border="0" width="100%" style="background:#F9FAFB;border:1px solid #E5E7EB;border-radius:8px;margin-bottom:16px;font-family:{FONT_STACK};">
      <tr><td style="padding:12px 16px;font-family:{FONT_STACK};">
        <div style="font-family:{FONT_STACK};font-size:10px;color:#6B7280;letter-spacing:0.08em;text-transform:uppercase;font-weight:700;">Period detail</div>
        <table cellpadding="0" cellspacing="0" border="0" width="100%" style="margin-top:6px;font-family:{FONT_STACK};font-size:11px;color:#374151;">
          <tr>
            <td style="padding:3px 0;font-family:{FONT_STACK};"><strong style="font-family:{FONT_STACK};color:#111827;">MTD</strong> · {_fmt_money(kpi_mtd['awarded_revenue'])} awarded · {_fmt_pct(kpi_mtd['awarded_convertio_ratio'])}</td>
          </tr>
          <tr>
            <td style="padding:3px 0;font-family:{FONT_STACK};"><strong style="font-family:{FONT_STACK};color:#111827;">QTD</strong> · {_fmt_money(kpi_qtd['awarded_revenue'])} awarded · {_fmt_pct(kpi_qtd['awarded_convertio_ratio'])}</td>
          </tr>
        </table>
      </td></tr>
    </table>
    """

    return f"""
    <!DOCTYPE html>
    <html><body style="margin:0;padding:0;background:#F3F4F6;font-family:{FONT_STACK};">
      <table cellpadding="0" cellspacing="0" border="0" width="100%" style="background:#F3F4F6;font-family:{FONT_STACK};">
        <tr><td align="center" style="padding:24px 12px;font-family:{FONT_STACK};">
          <table cellpadding="0" cellspacing="0" border="0" width="760" style="max-width:760px;background:#FFFFFF;border-radius:10px;overflow:hidden;border:1px solid #E5E7EB;font-family:{FONT_STACK};">
            <!-- Header -->
            <tr><td style="background:#1B3A5C;color:#FFFFFF;padding:22px 26px;font-family:{FONT_STACK};">
              <div style="font-family:{FONT_STACK};font-size:11px;letter-spacing:0.12em;text-transform:uppercase;opacity:0.75;">UNILINK Space · Daily Digest</div>
              <h1 style="margin:6px 0 4px 0;font-family:{FONT_STACK};font-size:22px;font-weight:700;letter-spacing:-0.01em;">Performance for RFPs</h1>
              <div style="font-family:{FONT_STACK};font-size:13px;opacity:0.85;">{today.strftime('%A, %B %d, %Y')} · 5:30 PM CST</div>
            </td></tr>

            <!-- Two-column body -->
            <tr><td style="padding:20px;background:#F9FAFB;font-family:{FONT_STACK};">
              <table cellpadding="0" cellspacing="0" border="0" width="100%" style="border-collapse:separate;font-family:{FONT_STACK};">
                <tr>
                  <!-- LEFT 50% — KPI cards -->
                  <td width="50%" valign="top" style="padding-right:10px;font-family:{FONT_STACK};">
                    {awarded_card}
                    {ratio_card}
                    {context_strip}
                  </td>
                  <!-- RIGHT 50% — Convertio Ratio table -->
                  <td width="50%" valign="top" style="padding-left:10px;font-family:{FONT_STACK};">
                    {_convertio_table_html(convertio)}
                  </td>
                </tr>
              </table>
            </td></tr>

            <!-- Footer -->
            <tr><td style="background:#FFFFFF;padding:16px 26px 22px 26px;border-top:1px solid #E5E7EB;text-align:center;font-family:{FONT_STACK};">
              <a href="{portal_url}/reports/rfp-performance" style="display:inline-block;background:#1B3A5C;color:#FFFFFF;padding:10px 18px;border-radius:6px;text-decoration:none;font-family:{FONT_STACK};font-size:13px;font-weight:600;">Open the full report →</a>
              <div style="font-family:{FONT_STACK};font-size:11px;color:#6B7280;margin-top:14px;">
                Source: <code style="font-family:{MONO_STACK};color:#111827;">automations_db.rfp_results_history</code>
                · ETL refresh 01:00 CST · Generated {today.isoformat()} 17:30 CST
              </div>
            </td></tr>
          </table>
        </td></tr>
      </table>
    </body></html>
    """


# ---------------------------------------------------------------------------
# Send entry point
# ---------------------------------------------------------------------------


async def send_daily_digest(
    automations_pool,
    *,
    to: list[str],
    cc: list[str] | None = None,
    bcc: list[str] | None = None,
    portal_url: str = DEFAULT_PORTAL_URL,
) -> dict[str, Any]:
    """Compute the digest and dispatch it via Microsoft Graph.

    Never raises. Returns a diagnostic dict (sent / reason / error) so the
    APScheduler job and the admin test endpoint can both log the result
    without taking down the worker.
    """
    if automations_pool is None:
        return {"sent": False, "reason": "no_automations_pool"}
    if not (settings.MS_TENANT_ID and settings.MS_CLIENT_ID and settings.MS_CLIENT_SECRET):
        return {"sent": False, "reason": "missing_msgraph_config"}

    today = cst_today()
    periods = _periods(today)

    try:
        kpi_ytd, kpi_ly_ytd, kpi_mtd, kpi_lm, kpi_qtd, kpi_lq, convertio = await asyncio.gather(
            _kpi_window(automations_pool, *periods["ytd"]),
            _kpi_window(automations_pool, *periods["ytd_ly"]),
            _kpi_window(automations_pool, *periods["mtd"]),
            _kpi_window(automations_pool, *periods["lm"]),
            _kpi_window(automations_pool, *periods["qtd"]),
            _kpi_window(automations_pool, *periods["lq"]),
            _convertio_table(automations_pool),
        )
    except Exception as e:
        logger.exception("RFP daily digest: query failed: %s", e)
        return {"sent": False, "reason": "query_failed", "error": str(e)}

    html = render_html(
        today=today,
        kpi_ytd=kpi_ytd,
        kpi_ly_ytd=kpi_ly_ytd,
        kpi_mtd=kpi_mtd,
        kpi_lm=kpi_lm,
        kpi_qtd=kpi_qtd,
        kpi_lq=kpi_lq,
        convertio=convertio,
        portal_url=portal_url,
    )

    awarded_str = _fmt_money(kpi_ytd["awarded_revenue"])
    ratio_str = _fmt_pct(kpi_ytd["awarded_convertio_ratio"])
    subject = (
        f"[UNILINK Space] RFP Performance — {awarded_str} YTD · "
        f"{ratio_str} Conv ({today.isoformat()})"
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
