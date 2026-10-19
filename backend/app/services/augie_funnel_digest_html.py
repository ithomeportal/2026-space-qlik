"""Daily "Augie Funnel" e-mail — HTML rendering only.

Sections (each heading is asserted by the n8n workflow, so a stale build or a
renamed heading cannot mail — rename one HERE and in
``/BOT/n8n-mcp/workflows/augie-funnel.assert.code.js`` together, the assert
first): see ``SECTIONS``.

Wording is plain language for ops readers (2026-10-19, user request: "Not in
Augie: 27 (79.4%) … is not clear"). The internal keys (tracked, captured,
not_covered …) are unchanged; only what a reader sees. The user manual
(``~/Pictures/Augie-Funnel-User-Manual.pdf``) uses these exact labels.

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

UP = "&#9650;"    # ▲
DOWN = "&#9660;"  # ▼

# The n8n assert checks every one of these is in the HTML.
SECTIONS = ("FROM PICKUP TO CARRIER UPDATE", "WHY LOADS WERE NOT SENT TO AUGIE",
            "HOW THIS COMPARES", "LAST 14 DAYS", "BY TEAM")

REASON_LABELS: tuple[tuple[str, str, str], ...] = (
    # ⚠ Same order as augie_funnel.REASONS — the CASE's priority (the section
    # note says so, and a test pins it).
    ("canceled", "Canceled",
     "The load was voided or canceled before it could be sent."),
    ("international", "Outside the US",
     "Picks up or delivers outside the US &mdash; Augie only handles US-to-US loads."),
    ("multistop", "Multi-stop or split load",
     "Has extra pickup/delivery stops, or moves in more than one leg."),
    ("not_covered", "No carrier assigned yet",
     "No carrier or driver on the load, so there is nobody for Augie to call."),
    ("other", "Other settings",
     ("Excluded by a customer/carrier setting, a blocking rule, Augie switched off, "
      "or timing.")),
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
    """Delta text + colour, as ▲/▼ + magnitude ("▲ 5.9 pts"). A RISE is good for
    every figure this e-mail compares (pickups, sent, updates and both rates)."""
    if v is None:
        return DASH, MUTED
    if round(v, 1) == 0:
        return "no change", FLAT
    mag = f"{abs(v):,.1f}{unit}" if unit else f"{abs(v):,.0f}"
    return f"{UP if v > 0 else DOWN} {mag}", GOOD if v > 0 else BAD


def _weekday(d: date) -> str:
    return d.strftime("%A")


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


def _funnel(day: dict, vs_week: dict, d: date) -> str:
    wk_t, wk_c = _signed(vs_week["tracked_pts"], " pts")
    cp_t, cp_c = _signed(vs_week["captured_pts"], " pts")
    last = f"vs last {_weekday(d)}"
    boxes = (
        _box("Loads picked up", _n(day["pickups"]),
             "every load with a pickup scheduled that day", BRAND)
        + _arrow()
        + _box("Sent to Augie", _n(day["tracked"]),
               f'{_p(day["tracked_pct"])} of loads picked up<br>'
               f'<span style="font-family:{FONT_STACK};color:{wk_c};">{wk_t}</span> {last}',
               TRACK)
        + _arrow()
        + _box("Carrier contacted", _n(day["contacted"]),
               f'{_p(day["contacted_pct"])} of loads sent to Augie', TRACK)
        + _arrow()
        + _box("Carrier gave an update", _n(day["captured"]),
               f'{_p(day["captured_pct"])} of loads sent to Augie<br>'
               f'<span style="font-family:{FONT_STACK};color:{cp_c};">{cp_t}</span> {last}',
               CAPTURE)
    )
    reconcile = (
        f'<div style="font-family:{FONT_STACK};font-size:12px;color:{INK};margin:8px 0 0 0;">'
        f'<b style="font-family:{FONT_STACK};">{_n(day["not_tracked"])} of '
        f'{_n(day["pickups"])} loads ({_p(day["not_tracked_pct"])}) were never sent to '
        f'Augie</b> &mdash; the reasons are below.</div>'
        f'<div style="font-family:{FONT_STACK};font-size:11px;color:{MUTED};margin:2px 0 0 0;">'
        f'The Augie app shows a status on {_n(day["has_status"])} loads, but only the '
        f'{_n(day["tracked"])} that Augment accepted count as sent. '
        f'&ldquo;pts&rdquo; = percentage points: 30% &rarr; 20% is &ldquo;{DOWN} 10.0 pts&rdquo;.'
        f'</div>')
    return (f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" '
            f'style="font-family:{FONT_STACK};"><tr>{boxes}</tr></table>{reconcile}')


def _reasons(day: dict, last_week: dict, d: date) -> str:
    peak = max([day[k] for k, _, _ in REASON_LABELS] + [1])
    body = ""
    for key, label, help_ in REASON_LABELS:
        diff = day[key] - last_week[key]
        text = ("same" if diff == 0
                else f"{UP if diff > 0 else DOWN} {abs(diff):,} {'more' if diff > 0 else 'fewer'}")
        # Fewer loads left out is the good direction here.
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
    head = (_th("Reason", "left") + _th("Loads") + _th("% of loads picked up")
            + _th("", "left") + _th(f"vs last {_weekday(d)}"))
    return _table(head, body)


def _comparison(m: dict) -> str:
    s, p = m["summary"], m["periods"]
    rows = (
        # (label, period, comparison, the NEWER period that comparison is of)
        ("Yesterday", "day", None, None),
        ("Day before", "prev_day", "vs_prev_day", "Yesterday"),
        (f"Last {_weekday(p['last_week_day'][0])}", "last_week_day", "vs_last_week_day",
         "Yesterday"),
        ("Last 7 days", "last7", None, None),
        ("The 7 days before", "prior7", "vs_prior7", "Last 7 days"),
        ("This month so far", "mtd", None, None),
        ("Same days last month", "prev_mtd", "vs_prev_mtd", "This month"),
    )
    body = ""
    for label, key, cmp_key, newer in rows:
        r = s[key]
        lo, hi = p[key]
        if cmp_key:
            c = m[cmp_key]
            t_txt, t_col = _signed(c["tracked_pts"], " pts")
            c_txt, c_col = _signed(c["captured_pts"], " pts")
            delta = (f'<b style="font-family:{FONT_STACK};">{newer}:</b> '
                     f'sent <span style="font-family:{FONT_STACK};color:{t_col};">{t_txt}</span>'
                     f'<br>update <span style="font-family:{FONT_STACK};color:{c_col};">'
                     f'{c_txt}</span>')
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
    head = (_th("Period", "left") + _th("Picked up") + _th("Sent to Augie") + _th("% sent")
            + _th("Updates") + _th("% with update") + _th("Change vs this row"))
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
    head = (_th("Pickup day", "left") + _th("Picked up") + _th("% sent")
            + _th("% with update") + _th("Loads (see colour key)", "left"))
    return _table(head, body)


def _legend() -> str:
    def key(colour: str, text: str) -> str:
        return (f'<span style="font-family:{FONT_STACK};color:{colour};font-size:11px;">'
                f'{BLOCK}{BLOCK}</span> {text}')
    return ("latest first &middot; colour key: "
            + key(CAPTURE, "carrier gave an update") + " &middot; "
            + key(TRACK, "sent to Augie, no update yet") + " &middot; "
            + key(MISS, "not sent to Augie"))


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
    head = (_th("Unit / team", "left") + _th("Picked up") + _th("Sent to Augie")
            + _th("% sent") + _th("% with update") + _th("Not sent"))
    return _table(head, body)


# ---------------------------------------------------------------------------
# Page
# ---------------------------------------------------------------------------


def render_html(m: dict[str, Any]) -> str:
    d: date = m["day"]
    s = m["summary"]
    day, last_week = s["day"], s["last_week_day"]
    title = (f'<div style="font-family:{FONT_STACK};font-size:20px;font-weight:700;'
             f'color:{BRAND};">Augie Funnel &mdash; {_weekday(d)}, {d.strftime("%b")} '
             f'{d.day}, {d.year}</div>'
             f'<div style="font-family:{FONT_STACK};font-size:12px;color:{MUTED};'
             f'margin:4px 0 0 0;">Every load with a pickup scheduled that day (CST, all units): '
             f'how many were sent to Augie, whether Augie reached the carrier and got an '
             f'update, and why the rest were never sent.</div>')

    def term(word: str, meaning: str) -> str:
        return f'<b style="font-family:{FONT_STACK};color:{INK};">{word}</b> = {meaning} '

    footer = (f'<div style="font-family:{FONT_STACK};font-size:11px;color:{MUTED};'
              f'margin:24px 0 0 0;border-top:1px solid {BORDER};padding-top:8px;'
              f'line-height:16px;">'
              + term("Sent to Augie", "Augment accepted the load for tracking.")
              + term("Carrier contacted", "Augie got through to the carrier: a completed call, "
                     "or the carrier answered by phone or e-mail.")
              + term("Carrier gave an update",
                     "the carrier gave Augie a location, status or stop update by phone or "
                     "e-mail (same rule as the Augie Daily Activity report).")
              + term("% sent", "share of loads picked up;")
              + "contacted and update % are shares of the loads sent to Augie. "
              + term(f"{UP} / {DOWN}", "higher / lower; green is better, red is worse.")
              + term("&mdash;", "nothing to measure (for example, no loads were sent).")
              + f'Data as of {_stamp(m["freshness"].get("loads_updated"))}. '
              f'<a href="{m["report_url"]}" style="font-family:{FONT_STACK};color:{LINK};">'
              f'Open the live report in Space</a> to see each load.</div>')
    body = (
        title
        + _section(SECTIONS[0], f"{_short(d)} &middot; all units")
        + _funnel(day, m["vs_last_week_day"], d)
        + _section(SECTIONS[1],
                   "each load is counted once, under the first reason that applies "
                   "(top to bottom)")
        + _reasons(day, last_week, d)
        + _section(SECTIONS[2],
                   "each comparison row says how the newer period (Yesterday, Last 7 days "
                   "or This month) did against it, in percentage points (pts)")
        + _comparison(m)
        + _section(SECTIONS[3], _legend())
        + _trend(m["trend"])
        + _section(SECTIONS[4], f"{_short(d)} &middot; &mdash; = no loads sent to Augie")
        + _teams(m["teams"], m["units"])
        + footer
    )
    return (f'<!DOCTYPE html><html><head><meta charset="utf-8"></head>'
            f'<body style="margin:0;padding:0;background:#FFFFFF;font-family:{FONT_STACK};">'
            f'<table role="presentation" width="{PAGE_WIDTH}" cellpadding="0" cellspacing="0" '
            f'style="font-family:{FONT_STACK};margin:0 auto;"><tr>'
            f'<td style="font-family:{FONT_STACK};padding:16px;">{body}</td></tr></table>'
            f'</body></html>')
