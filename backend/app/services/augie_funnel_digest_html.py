"""Daily "Augie Funnel" e-mail — HTML rendering only.

Sections (each heading is asserted by the n8n workflow, so a stale build or a
renamed heading cannot mail): FUNNEL EFFICIENCY · NOT IN AUGIE · PERIOD
COMPARISON · 14-DAY TREND · BY TEAM.

Outlook rules (SPEC-CODE-RULES §21): FONT_STACK inline on EVERY element, hex
colours only, tables for layout, no webfonts. ⚠ Outlook's PRINT / PDF drops
every background — headings are coloured text over a border rule and the trend
bars are coloured █ text, never fills (SPEC-EXEC-MEETING-RECRUITMENT §8).
``None`` renders as an em dash, never 0.
"""
from __future__ import annotations

from datetime import date, datetime
from html import escape
from typing import Any, Optional

from app.services.team_perf_digest_html import FONT_STACK

PAGE_WIDTH = 900

INK = "#111827"
MUTED = "#6B7280"
BORDER = "#E5E7EB"
HEAD_BG = "#F3F4F6"
BRAND = "#0F2A4A"
GOOD = "#15803D"
BAD = "#DC2626"
FLAT = "#B45309"
TRACK = "#2563EB"
CAPTURE = "#15803D"
MISS = "#9CA3AF"
LINK = "#2563EB"
DASH = "&mdash;"

BLOCK = "&#9608;"  # █ — a bar drawn in TEXT colour survives Outlook print/PDF
BAR_MAX_BLOCKS = 24

REASON_LABELS: tuple[tuple[str, str, str], ...] = (
    # ⚠ Same order as augie_funnel.REASONS — the CASE's priority (the section
    # note says so, and a test pins it).
    ("canceled", "Canceled", "voided or canceled before Augie could track it"),
    ("international", "International", "an end outside the US — Augie only tracks US→US"),
    ("multistop", "Multistop", "extra stops at pickup/delivery, or several movements"),
    ("not_covered", "Not covered", "no carrier / driver assigned (cannot be tracked)"),
    ("other", "Other", "allow-list, blocking rules, switches or timing"),
)


# ---------------------------------------------------------------------------
# Formatting
# ---------------------------------------------------------------------------


def _n(v: Optional[float]) -> str:
    return DASH if v is None else f"{v:,.0f}"


def _p(v: Optional[float]) -> str:
    return DASH if v is None else f"{v:.1f}%"


def _short(d: date) -> str:
    return f"{d.strftime('%a')} {d.strftime('%b')} {d.day}"


def _span(lo: date, hi: date) -> str:
    if lo == hi:
        return _short(lo)
    return f"{lo.strftime('%b')} {lo.day} &ndash; {hi.strftime('%b')} {hi.day}"


def _stamp(iso: Optional[str]) -> str:
    """Naive CST ISO stamp -> "Oct 17, 10:48 CST"."""
    if not iso:
        return "unknown"
    try:
        t = datetime.fromisoformat(iso)
    except ValueError:
        return escape(iso)
    return f"{t.strftime('%b')} {t.day}, {t.strftime('%H:%M')} CST"


def _signed(v: Optional[float], unit: str = "") -> tuple[str, str]:
    """Delta text + colour. A RISE is good for every figure this e-mail compares
    (pickups, tracked, captured and both rates)."""
    if v is None:
        return DASH, MUTED
    if round(v, 1) == 0:
        return f"0{unit}", FLAT
    text = f"{v:+,.1f}{unit}" if unit else f"{v:+,.0f}"
    return text, GOOD if v > 0 else BAD


# ---------------------------------------------------------------------------
# Elements — every one carries the font inline
# ---------------------------------------------------------------------------


def _td(text: str, *, align: str = "right", bold: bool = False, color: str = INK,
        size: int = 12, extra: str = "") -> str:
    weight = "font-weight:700;" if bold else ""
    return (f'<td align="{align}" style="font-family:{FONT_STACK};font-size:{size}px;'
            f'color:{color};{weight}padding:6px 8px;border-bottom:1px solid {BORDER};'
            f'{extra}">{text}</td>')


def _th(text: str, align: str = "right") -> str:
    return (f'<th align="{align}" style="font-family:{FONT_STACK};font-size:10px;'
            f'color:{MUTED};text-transform:uppercase;letter-spacing:0.4px;'
            f'padding:6px 8px;border-bottom:2px solid {BORDER};background:{HEAD_BG};">'
            f'{text}</th>')


def _table(head: str, body: str) -> str:
    return (f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" '
            f'style="font-family:{FONT_STACK};border-collapse:collapse;">'
            f'<tr>{head}</tr>{body}</table>')


def _section(title: str, note: str = "") -> str:
    sub = (f'<div style="font-family:{FONT_STACK};font-size:11px;color:{MUTED};'
           f'margin:2px 0 0 0;">{note}</div>') if note else ""
    return (f'<div style="font-family:{FONT_STACK};margin:22px 0 8px 0;'
            f'border-bottom:2px solid {BRAND};padding-bottom:4px;">'
            f'<span style="font-family:{FONT_STACK};font-size:13px;font-weight:700;'
            f'color:{BRAND};letter-spacing:0.6px;">{title}</span>{sub}</div>')


def _bar(n: int, peak: int, colour: str) -> str:
    if not n:
        return f'<span style="font-family:{FONT_STACK};color:{MUTED};">{DASH}</span>'
    blocks = max(1, round(BAR_MAX_BLOCKS * n / peak)) if peak else 1
    return (f'<span style="font-family:{FONT_STACK};color:{colour};font-size:11px;'
            f'letter-spacing:-1px;white-space:nowrap;">{BLOCK * blocks}</span>')


def _box(label: str, value: str, sub: str, colour: str) -> str:
    return (f'<td valign="top" style="font-family:{FONT_STACK};padding:0;">'
            f'<div style="font-family:{FONT_STACK};border:1px solid {BORDER};'
            f'border-top:3px solid {colour};padding:10px 12px;">'
            f'<div style="font-family:{FONT_STACK};font-size:10px;color:{MUTED};'
            f'text-transform:uppercase;letter-spacing:0.5px;font-weight:700;">{label}</div>'
            f'<div style="font-family:{FONT_STACK};font-size:24px;font-weight:700;'
            f'color:{INK};margin:4px 0 2px 0;">{value}</div>'
            f'<div style="font-family:{FONT_STACK};font-size:11px;color:{MUTED};">{sub}</div>'
            f'</div></td>')


def _arrow() -> str:
    return (f'<td width="28" align="center" style="font-family:{FONT_STACK};'
            f'font-size:20px;color:{MUTED};">&rarr;</td>')


# ---------------------------------------------------------------------------
# Sections
# ---------------------------------------------------------------------------


def _funnel(day: dict, vs_week: dict) -> str:
    wk_t, wk_c = _signed(vs_week["tracked_pts"], " pts")
    cp_t, cp_c = _signed(vs_week["captured_pts"], " pts")
    boxes = (
        _box("Pickups", _n(day["pickups"]), "company-wide, by scheduled pickup", BRAND)
        + _arrow()
        + _box("Tracked by Augie", _n(day["tracked"]),
               f'{_p(day["tracked_pct"])} of pickups · '
               f'<span style="font-family:{FONT_STACK};color:{wk_c};">{wk_t}</span> vs last wk',
               TRACK)
        + _arrow()
        + _box("Contacted", _n(day["contacted"]),
               f'{_p(day["contacted_pct"])} of tracked', TRACK)
        + _arrow()
        + _box("Info captured", _n(day["captured"]),
               f'{_p(day["captured_pct"])} of tracked · '
               f'<span style="font-family:{FONT_STACK};color:{cp_c};">{cp_t}</span> vs last wk',
               CAPTURE)
    )
    reconcile = (
        f'<div style="font-family:{FONT_STACK};font-size:11px;color:{MUTED};margin:6px 0 0 0;">'
        f'Not in Augie: <b style="font-family:{FONT_STACK};color:{INK};">'
        f'{_n(day["not_tracked"])} ({_p(day["not_tracked_pct"])})</b>. '
        f'For reference, {_n(day["has_status"])} loads carry an Augie status in the app; '
        f'only those Augment accepted count as tracked.</div>')
    return (f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" '
            f'style="font-family:{FONT_STACK};"><tr>{boxes}</tr></table>{reconcile}')


def _reasons(day: dict, last_week: dict) -> str:
    peak = max([day[k] for k, _, _ in REASON_LABELS] + [1])
    body = ""
    for key, label, help_ in REASON_LABELS:
        diff = day[key] - last_week[key]
        text = DASH if diff == 0 else (f"+{diff:,}" if diff > 0 else f"{diff:,}")
        # Fewer untracked loads is the good direction here.
        colour = MUTED if diff == 0 else (BAD if diff > 0 else GOOD)
        body += ("<tr>"
                 + _td(f'<b style="font-family:{FONT_STACK};">{label}</b>'
                       f'<div style="font-family:{FONT_STACK};font-size:10px;color:{MUTED};">'
                       f'{help_}</div>', align="left")
                 + _td(_n(day[key]), bold=True)
                 + _td(_p(day["reason_pct"][key]), color=MUTED)
                 + _td(_bar(day[key], peak, MISS), align="left")
                 + _td(text, color=colour)
                 + "</tr>")
    head = (_th("Reason", "left") + _th("Loads") + _th("% of pickups")
            + _th("", "left") + _th("vs same day last wk"))
    return _table(head, body)


def _comparison(m: dict) -> str:
    s, p = m["summary"], m["periods"]
    rows = (
        ("Yesterday", "day", None),
        ("Day before", "prev_day", "vs_prev_day"),
        ("Same day last week", "last_week_day", "vs_last_week_day"),
        ("Last 7 days", "last7", None),
        ("Prior 7 days", "prior7", "vs_prior7"),
        ("Month to date", "mtd", None),
        ("Same days last month", "prev_mtd", "vs_prev_mtd"),
    )
    body = ""
    for label, key, cmp_key in rows:
        r = s[key]
        lo, hi = p[key]
        if cmp_key:
            c = m[cmp_key]
            t_txt, t_col = _signed(c["tracked_pts"], " pts")
            c_txt, c_col = _signed(c["captured_pts"], " pts")
            delta = (f'<span style="font-family:{FONT_STACK};color:{t_col};">{t_txt}</span> / '
                     f'<span style="font-family:{FONT_STACK};color:{c_col};">{c_txt}</span>')
            shade = ""
        else:
            delta = ""
            shade = "background:#F9FAFB;"
        body += ("<tr>"
                 + _td(f'<b style="font-family:{FONT_STACK};">{label}</b> '
                       f'<span style="font-family:{FONT_STACK};color:{MUTED};font-size:11px;">'
                       f'{_span(lo, hi)}</span>', align="left", extra=shade)
                 + _td(_n(r["pickups"]), extra=shade)
                 + _td(_n(r["tracked"]), extra=shade)
                 + _td(_p(r["tracked_pct"]), bold=True, color=TRACK, extra=shade)
                 + _td(_n(r["captured"]), extra=shade)
                 + _td(_p(r["captured_pct"]), bold=True, color=CAPTURE, extra=shade)
                 + _td(delta, size=11, extra=shade)
                 + "</tr>")
    head = (_th("Period", "left") + _th("Pickups") + _th("Tracked") + _th("Tracked %")
            + _th("Captured") + _th("Captured %") + _th("Δ tracked / captured"))
    return _table(head, body)


def _trend(points: list[dict]) -> str:
    peak = max([pt["pickups"] for pt in points] + [1])
    body = ""
    for pt in reversed(points):
        d = date.fromisoformat(pt["bucket"])
        bar = (_bar(pt["captured"], peak, CAPTURE)
               + _bar(pt["tracked"] - pt["captured"], peak, TRACK)
               + _bar(pt["pickups"] - pt["tracked"], peak, MISS)
               if pt["pickups"] else _bar(0, peak, MISS))
        body += ("<tr>"
                 + _td(_short(d), align="left")
                 + _td(_n(pt["pickups"]))
                 + _td(_p(pt["tracked_pct"]), color=TRACK, bold=True)
                 + _td(_p(pt["captured_pct"]), color=CAPTURE, bold=True)
                 + _td(bar, align="left")
                 + "</tr>")
    head = (_th("Pickup day", "left") + _th("Pickups") + _th("Tracked %")
            + _th("Captured %") + _th("captured · tracked · not in Augie", "left"))
    return _table(head, body)


def _teams(teams: list[dict], units: dict[str, dict]) -> str:
    body = ""
    for unit in ("CORP", "DFW"):
        u = units[unit]
        body += ("<tr>"
                 + _td(f"<b style=\"font-family:{FONT_STACK};\">{unit}</b>", align="left",
                       extra="background:#F9FAFB;")
                 + _td(_n(u["pickups"]), bold=True, extra="background:#F9FAFB;")
                 + _td(_n(u["tracked"]), bold=True, extra="background:#F9FAFB;")
                 + _td(_p(u["tracked_pct"]), bold=True, color=TRACK, extra="background:#F9FAFB;")
                 + _td(_p(u["captured_pct"]), bold=True, color=CAPTURE,
                       extra="background:#F9FAFB;")
                 + _td(_n(u["not_tracked"]), bold=True, extra="background:#F9FAFB;")
                 + "</tr>")
        for t in sorted((t for t in teams if t["unit"] == unit), key=lambda t: t["team"] or ""):
            body += ("<tr>"
                     + _td(f"&nbsp;&nbsp;{escape(t['team'] or 'no team')}", align="left")
                     + _td(_n(t["pickups"])) + _td(_n(t["tracked"]))
                     + _td(_p(t["tracked_pct"]), color=TRACK)
                     + _td(_p(t["captured_pct"]), color=CAPTURE)
                     + _td(_n(t["not_tracked"]))
                     + "</tr>")
    # Loads with a blank / unknown unit belong to neither summary above; print
    # them so the table still sums to FUNNEL EFFICIENCY's total.
    for t in (t for t in teams if t["unit"] not in ("CORP", "DFW")):
        body += ("<tr>"
                 + _td("<b style=\"font-family:" + FONT_STACK + ";\">Unassigned unit</b>"
                       + (f" · {escape(t['team'])}" if t["team"] else ""), align="left")
                 + _td(_n(t["pickups"])) + _td(_n(t["tracked"]))
                 + _td(_p(t["tracked_pct"]), color=TRACK)
                 + _td(_p(t["captured_pct"]), color=CAPTURE)
                 + _td(_n(t["not_tracked"]))
                 + "</tr>")
    head = (_th("Unit / team", "left") + _th("Pickups") + _th("Tracked") + _th("Tracked %")
            + _th("Captured %") + _th("Not in Augie"))
    return _table(head, body)


# ---------------------------------------------------------------------------
# Page
# ---------------------------------------------------------------------------


def render_html(m: dict[str, Any]) -> str:
    d: date = m["day"]
    s = m["summary"]
    day, last_week = s["day"], s["last_week_day"]
    title = (f'<div style="font-family:{FONT_STACK};font-size:20px;font-weight:700;'
             f'color:{BRAND};">Augie Funnel &mdash; close of {_short(d)}, {d.year}</div>'
             f'<div style="font-family:{FONT_STACK};font-size:12px;color:{MUTED};'
             f'margin:4px 0 0 0;">Every load picked up that day (scheduled pickup, CST), '
             f'how many Augie tracked, and why the rest never reached it.</div>')
    footer = (f'<div style="font-family:{FONT_STACK};font-size:11px;color:{MUTED};'
              f'margin:24px 0 0 0;border-top:1px solid {BORDER};padding-top:8px;">'
              f'<b style="font-family:{FONT_STACK};">Tracked</b> = accepted by Augment. '
              f'<b style="font-family:{FONT_STACK};">Info captured</b> = a tracked load that '
              f'sent a phone carrier update, a phone/e-mail tracking event or a stop update '
              f'(same rule as the Augie Daily Activity report). Contacted and captured % '
              f'are of tracked loads; everything else is of pickups. Loads feed as of '
              f'{_stamp(m["freshness"].get("loads_updated"))}. '
              f'<a href="{m["report_url"]}" style="font-family:{FONT_STACK};color:{LINK};">'
              f'Open the live report in Space</a></div>')
    body = (
        title
        + _section("FUNNEL EFFICIENCY", f"{_short(d)} · company-wide")
        + _funnel(day, m["vs_last_week_day"])
        + _section("NOT IN AUGIE", "one reason per load, in this priority order")
        + _reasons(day, last_week)
        + _section("PERIOD COMPARISON",
                   "Δ = change in tracked % / captured %, in percentage points")
        + _comparison(m)
        + _section("14-DAY TREND", "latest first")
        + _trend(m["trend"])
        + _section("BY TEAM", f"{_short(d)}")
        + _teams(m["teams"], m["units"])
        + footer
    )
    return (f'<!DOCTYPE html><html><head><meta charset="utf-8"></head>'
            f'<body style="margin:0;padding:0;background:#FFFFFF;font-family:{FONT_STACK};">'
            f'<table role="presentation" width="{PAGE_WIDTH}" cellpadding="0" cellspacing="0" '
            f'style="font-family:{FONT_STACK};margin:0 auto;"><tr>'
            f'<td style="font-family:{FONT_STACK};padding:16px;">{body}</td></tr></table>'
            f'</body></html>')
