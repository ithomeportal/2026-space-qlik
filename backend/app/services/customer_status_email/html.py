"""Outlook-safe HTML for the customer load-status e-mails.

Layout follows the template's "EJEMPLO" cards: LOAD ID# · CONSIGNEE / LANE ·
CURRENT LOCATION / ETA · PU & DEL TIMES, with a comment + tracking-link row
under each in-progress load and a LINK TO POD box on each delivered load.

Outlook rules (SPEC-CODE-RULES §21): FONT_STACK inline on EVERY element, hex
colours, tables for layout. ⚠ Outlook PRINT/PDF drops backgrounds, so every
pill and heading carries its meaning in TEXT colour + a border; the tint is
decoration only. ``None`` renders as an em dash. Customer text is escaped.
"""
from __future__ import annotations

from datetime import datetime
from html import escape
from typing import Optional
from urllib.parse import urlparse

from app.services.customer_status_email.cards import Card, ReportCards
from app.services.customer_status_email.signature import SIGNATURE_HTML
from app.services.team_perf_digest_html import FONT_STACK

PAGE_WIDTH = 860
NAVY = "#1F3A6E"
INK = "#111827"
MUTED = "#6B7280"
BORDER = "#D1D5DB"
GOOD, GOOD_BG = "#166534", "#DCFCE7"
BAD, BAD_BG = "#B91C1C", "#FEE2E2"
LINK = "#1D4ED8"
DASH = "&mdash;"

# (heading, colour) per section — the template's three coloured bars.
SECTION_IN_PROGRESS = "About your loads in progress, please find their most current status:"
SECTION_SCHEDULED = "We also have scheduled the following loads:"
SECTION_DELIVERED = "Finally, please see the loads we have delivered in the last 24 hrs."
SECTIONS = (SECTION_IN_PROGRESS, SECTION_SCHEDULED, SECTION_DELIVERED)
_SECTION_COLOURS = ("#1F6FB2", "#5B8DC9", "#2E9E44")

EMPTY_TEXT = "No loads at this time."
AHEAD_CAP_HOURS = 24


def _s(css: str = "") -> str:
    return f'style="font-family:{FONT_STACK};{css}"'


def _e(text: Optional[str]) -> str:
    return escape(text) if text else DASH


def fmt_dt(value: Optional[datetime]) -> str:
    """10/19/2026 @ 03:00 AM — the template's format."""
    return value.strftime("%m/%d/%Y @ %I:%M %p") if value else DASH


def _small(text: str, colour: str = MUTED) -> str:
    return f'<div {_s(f"font-size:11px;color:{colour};margin-top:2px;")}>{text}</div>'


def _big(text: str) -> str:
    return f'<div {_s(f"font-size:14px;color:{INK};")}>{text}</div>'


def _time(text: str) -> str:
    """One timestamp line that never wraps between date and time."""
    return f'<div {_s(f"font-size:13px;color:{INK};white-space:nowrap;")}>{text}</div>'


def _pill_line(pill_html: str) -> str:
    return f'<div {_s("margin-top:4px;")}>{pill_html}</div>' if pill_html else ""


def _head(text: str) -> str:
    css = (f"font-size:11px;font-weight:700;color:{NAVY};letter-spacing:0.3px;"
           "text-transform:uppercase;margin-bottom:4px;")
    return f'<div {_s(css)}>{text}</div>'


def pill(text: str, good: bool) -> str:
    fg, bg = (GOOD, GOOD_BG) if good else (BAD, BAD_BG)
    mark = "&#9679;" if good else "&#9888;"
    css = (f"font-size:11px;font-weight:600;color:{fg};background:{bg};"
           f"border:1px solid {fg};padding:1px 8px;white-space:nowrap;")
    return f'<span {_s(css)}>{mark} {text}</span>'


def on_time_pill(flag: Optional[bool]) -> str:
    if flag is None:
        return ""
    return pill("On-Time" if flag else "Late", flag)


def hours_pill(hours: Optional[float]) -> str:
    """Positive = the ETA is AFTER the appointment's late edge."""
    if hours is None:
        return ""
    if hours <= -AHEAD_CAP_HOURS:
        # Cross-border trucks reach Reynosa days before the plant's appointment
        # (measured 54-78 h); a number that large reads as an error.
        return pill("Ahead of schedule", True)
    if hours <= 0:
        return pill(f"{abs(hours):.1f} Hours AHEAD", True)
    return pill(f"{hours:.1f} Hours BEHIND", False)


def _cell(inner: str, width: str) -> str:
    return f'<td valign="top" width="{width}" {_s("padding:8px 10px;")}>{inner}</td>'


def _id_cell(card: Card, with_trailer: bool = True) -> str:
    rows = [_big(_e(card.po)), _small(f"UNILINK# {escape(card.order_id)}")]
    if with_trailer:
        rows.append(_small(f"Trailer # {_e(card.trailer)}"))
    return _head("Load ID#") + "".join(rows)


def _lane_cell(card: Card, with_bol: bool = True) -> str:
    rows = [_big(_e(card.consignee)), _small(escape(card.lane))]
    if with_bol:
        rows.append(_small(f"BOL # {_e(card.bol)}"))
    return _head("Consignee / Lane") + "".join(rows)


def _location_cell(card: Card) -> str:
    rows = [_big(_e(card.location))]
    if card.location_at:
        rows.append(_small(f"GPS {fmt_dt(card.location_at)} CST"))
    if card.eta:
        where = f" to {escape(card.eta_place)}" if card.eta_place else ""
        clock = " CST" if card.eta_is_cst else ""
        rows.append(_small(f"ETA{where}: {fmt_dt(card.eta)}{clock}", INK))
    status = escape(card.status_label or "In progress").upper()
    rows.append(f'<div {_s("margin-top:6px;")}>'
                f'<span {_s(f"font-size:11px;color:{INK};margin-right:6px;")}>{status}</span>'
                f'{hours_pill(card.hours_vs_appt)}</div>')
    return _head("Current Location / ETA") + "".join(rows)


def _times_in_progress(card: Card) -> str:
    pu = card.pu_in or card.pu_out
    rows = [_big(fmt_dt(pu)),
            _small(f"Sched. pick up {fmt_dt(card.pu_sched_late)}"),
            _pill_line(on_time_pill(card.pu_on_time)),
            _small("-----"),
            _small(f"Delivery appt. {fmt_dt(card.del_sched_late)}")]
    return _head("PU &amp; DEL Times") + "".join(rows)


def _times_scheduled(card: Card, which: str) -> str:
    if which == "pu":
        title, early, late = "Pick Up Schedule Times", card.pu_sched_early, card.pu_sched_late
    else:
        title, early, late = "Delivery Schedule Times", card.del_sched_early, card.del_sched_late
    return _head(title) + _big(fmt_dt(early)) + _big(fmt_dt(late))


def _times_actual(title: str, t_in, t_out, sched, flag) -> str:
    return (_head(title) + _time(f"IN: {fmt_dt(t_in)}") + _time(f"OUT: {fmt_dt(t_out)}")
            + _small(f"Sched. {fmt_dt(sched)}") + _pill_line(on_time_pill(flag)))


def _box(inner: str) -> str:
    css = f"border:1px solid {BORDER};padding:8px 10px;font-size:13px;color:{INK};"
    return f'<td valign="top" {_s(css)}>{inner}</td>'


def _link(url: Optional[str], label: str) -> str:
    # Only http(s): the URL is McLeod/AP free text, and the admin preview is
    # served as text/html on the portal origin — a javascript: link would run there.
    if not url or urlparse(url).scheme.lower() not in ("http", "https"):
        return DASH
    return f'<a href="{escape(url, quote=True)}" {_s(f"color:{LINK};")}>{label}</a>'


def card_in_progress(card: Card) -> str:
    top = (_cell(_id_cell(card), "20%") + _cell(_lane_cell(card), "27%")
           + _cell(_location_cell(card), "26%") + _cell(_times_in_progress(card), "27%"))
    comment = escape(card.comment) if card.comment else "No update yet."
    link_css = f"border:1px solid {BORDER};padding:8px 10px;font-size:12px;color:{INK};"
    bottom = (f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" '
              f'{_s("border-collapse:collapse;")}><tr>'
              f'{_box(comment)}'
              f'<td width="34%" valign="top" align="center" {_s(link_css)}>'
              f'<div {_s("font-weight:700;margin-bottom:2px;")}>TRACKING LINK:</div>'
              f'{_link(card.track_link, "Track this load")}</td></tr></table>')
    return _card(top, bottom)


def card_scheduled(card: Card) -> str:
    top = (_cell(_id_cell(card, with_trailer=False), "20%")
           + _cell(_lane_cell(card, with_bol=False), "30%")
           + _cell(_times_scheduled(card, "pu"), "25%")
           + _cell(_times_scheduled(card, "del"), "25%"))
    return _card(top)


def card_delivered(card: Card) -> str:
    pod_css = f"border:1px solid {BORDER};padding:8px 6px;font-size:12px;"
    pod = (_link(card.pod_link, "LINK TO POD") if card.pod_link
           else ("POD received" if card.has_pod else "POD pending"))
    top = (_cell(_id_cell(card), "16%") + _cell(_lane_cell(card), "20%")
           + _cell(_times_actual("Pick Up Actual Times", card.pu_in, card.pu_out,
                                 card.pu_sched_late, card.pu_on_time), "25%")
           + _cell(_times_actual("Delivery Actual Times", card.del_in, card.del_out,
                                 card.del_sched_late, card.del_on_time), "25%")
           + f'<td valign="middle" align="center" width="14%" {_s("padding:8px 10px;")}>'
             f'<div {_s(pod_css)}>{pod}</div></td>')
    return _card(top)


def _card(top: str, bottom: str = "") -> str:
    below = f'<tr><td colspan="5" {_s("padding:0 10px 8px 10px;")}>{bottom}</td></tr>' if bottom else ""
    css = f"border-collapse:collapse;border-bottom:1px solid {BORDER};margin-bottom:6px;"
    return (f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" '
            f'{_s(css)}><tr>{top}</tr>{below}</table>')


def _section(title: str, colour: str, cards: str) -> str:
    body = cards or f'<div {_s(f"font-size:13px;color:{MUTED};padding:8px 10px;")}>{EMPTY_TEXT}</div>'
    css = (f"margin:22px 0 8px 0;border-left:6px solid {colour};background:#F3F6FB;"
           f"padding:6px 10px;font-size:14px;font-weight:700;color:{colour};")
    return f'<div {_s(css)}>{escape(title)}</div>{body}'


def subject_for(rc: ReportCards, slot_at: datetime) -> str:
    return f"{rc.report.subject} - {slot_at.strftime('%m/%d/%Y %I:%M %p')} CST"


def render(rc: ReportCards, slot_at: datetime, test_banner: Optional[str] = None) -> str:
    p = f'<p {_s(f"font-size:14px;color:{INK};margin:0 0 12px 0;")}>'
    banner_css = "font-size:11px;color:#92400E;border:1px dashed #D97706;padding:6px 10px;margin-bottom:14px;"
    banner = f'<div {_s(banner_css)}>{escape(test_banner)}</div>' if test_banner else ""
    sections = (
        _section(SECTION_IN_PROGRESS, _SECTION_COLOURS[0],
                 "".join(card_in_progress(c) for c in rc.in_progress))
        + _section(SECTION_SCHEDULED, _SECTION_COLOURS[1],
                   "".join(card_scheduled(c) for c in rc.scheduled))
        + _section(SECTION_DELIVERED, _SECTION_COLOURS[2],
                   "".join(card_delivered(c) for c in rc.delivered))
    )
    as_of = (f'<div {_s(f"font-size:11px;color:{MUTED};margin-top:14px;")}>Status as of '
             f'{slot_at.strftime("%m/%d/%Y %I:%M %p")} CST. Times are local to each stop.</div>')
    return (
        f'<div {_s(f"max-width:{PAGE_WIDTH}px;color:{INK};")}>'
        f'{banner}'
        f'{p}Hello Team,</p>{p}I hope you\'re doing well.</p>'
        f'{p}Please see today\'s report for your review and don\'t hesitate to reach out if you '
        f'have any questions or if there\'s anything we can assist with.</p>'
        f'{sections}{as_of}'
        f'<p {_s(f"font-size:14px;color:{INK};margin:22px 0 14px 0;")}>'
        f'Thank you for the opportunity to support your business.</p>'
        f'{SIGNATURE_HTML}</div>'
    )
