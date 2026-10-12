"""Weekly "Recruitment Status" e-mail — HTML rendering only.

Sections (each heading is asserted by the n8n workflow):
  KPI tiles · WEEKLY PIPELINE (last 8 completed weeks, latest first, last week
  boxed, 7-week average and the delta) · ONBOARDING VS OFFBOARDING (full-period
  and YTD totals, then weekly bars) · OPEN ROLES (oldest first, live pipeline per
  role) · HIRES LAST WEEK · KEY INDICATORS · links.

Removed on request 2026-10-12: the Offer-acceptance row (the portal records no
formal offers, so it read 100% by construction) and the Definitions & Data
footer. ⚠ Outlook's PRINT / PDF drops every background — headings are coloured
text over a border rule and the trend bars are coloured █ text, never fills.

Outlook rules (SPEC-CODE-RULES §21): FONT_STACK inline on EVERY element, hex
colours only, tables for layout, no webfonts, print-color-adjust on fills.
``None`` renders as an em dash, never 0.
"""
from __future__ import annotations

from datetime import date, datetime
from html import escape
from typing import Optional

from app.services.team_perf_digest_html import FONT_STACK

PAGE_WIDTH = 960

INK = "#111827"
MUTED = "#6B7280"
BORDER = "#E5E7EB"
HEAD_BG = "#F3F4F6"
BRAND = "#0F2A4A"
GOOD = "#15803D"
BAD = "#DC2626"
FLAT = "#B45309"
LW_BG = "#ECFDF5"
LW_BOX = "#00B050"
WARN_BG = "#FEF3C7"
WARN_INK = "#92400E"
AGED_BG = "#FEE2E2"
LINK = "#2563EB"
DASH = "&mdash;"
PRINT_EXACT = "-webkit-print-color-adjust:exact;print-color-adjust:exact;"

AGED_DAYS = 60  # an open role older than this is flagged

# (key, label, help) — order is the funnel's order.
WEEKLY_ROWS: tuple[tuple[str, str, str], ...] = (
    ("new_applications", "New applications", "applications created that week"),
    ("screened", "Phone screened", "first reached Phone Screening or later"),
    ("valid", "Valid candidates", "passed screening: first reached HR Interview or later"),
    ("panel", "Panel interview", "first reached Panel Interview or later"),
    ("offer", "Offer stage", "first reached Send Offer or later"),
    ("hires", "Hires (accepted offer)", "Jobs portal HIRED, by hire date"),
    ("onboarding_tickets", "Onboarding tickets", "IT ROUTE onboarding tickets"),
    ("offboarding_tickets", "Exits (offboarding)", "IT ROUTE offboarding tickets"),
)
TICKET_ROWS = ("onboarding_tickets", "offboarding_tickets")
# Rows where a RISE is bad news (colour of the delta is a claim).
INVERTED_ROWS = ("offboarding_tickets",)


# ---------------------------------------------------------------------------
# Formatting
# ---------------------------------------------------------------------------


def baseline(values: list[int]) -> Optional[float]:
    """Mean of the weeks BEFORE last week (index 1..n-1, latest-first)."""
    prior = values[1:]
    return (sum(prior) / len(prior)) if prior else None


def _n(v) -> str:
    return DASH if v is None else f"{v:,.0f}"


def _pct(v: Optional[float]) -> str:
    return DASH if v is None else f"{v * 100:.1f}%"


def _short(d: date) -> str:
    return f"{d.strftime('%b')} {d.day}"


def _delta(v: Optional[float], invert: bool) -> tuple[str, str]:
    if v is None:
        return DASH, MUTED
    r = round(v)
    if r == 0:
        return "0", FLAT
    good, bad = (BAD, GOOD) if invert else (GOOD, BAD)
    return (f"+{r:,}" if r > 0 else f"{r:,}"), (good if r > 0 else bad)


def _ts(iso: Optional[str]) -> str:
    if not iso:
        return "no data"
    try:
        d = datetime.fromisoformat(iso)
    except ValueError:
        return escape(iso)
    if len(iso) <= 10:
        return f"{_short(d.date())}, {d.year}"
    return f"{_short(d.date())}, {d.year} {d.strftime('%H:%M')} CST"


# ---------------------------------------------------------------------------
# Elements — every one carries the font inline
# ---------------------------------------------------------------------------


def _td(content: str, *, align: str = "right", bg: str = "", color: str = INK,
        bold: bool = False, size: int = 12, extra: str = "") -> str:
    style = (f"font-family:{FONT_STACK};font-size:{size}px;color:{color};"
             f"text-align:{align};padding:6px 8px;border-bottom:1px solid {BORDER};"
             f"{'font-weight:700;' if bold else ''}"
             f"{f'background-color:{bg};{PRINT_EXACT}' if bg else ''}{extra}")
    attr = f' bgcolor="{bg}"' if bg else ""
    return f'<td style="{style}"{attr}>{content}</td>'


def _th(content: str, *, align: str = "right", bg: str = HEAD_BG, extra: str = "") -> str:
    style = (f"font-family:{FONT_STACK};font-size:10px;color:{MUTED};"
             f"text-transform:uppercase;letter-spacing:0.5px;font-weight:700;"
             f"text-align:{align};padding:6px 8px;border-bottom:1px solid {BORDER};"
             f"background-color:{bg};{PRINT_EXACT}{extra}")
    return f'<th style="{style}" bgcolor="{bg}">{content}</th>'


def _div(content: str, *, size: int = 13, color: str = INK, bold: bool = False,
         margin: str = "0 0 8px 0") -> str:
    return (f'<div style="font-family:{FONT_STACK};font-size:{size}px;color:{color};'
            f'line-height:1.5;margin:{margin};{"font-weight:700;" if bold else ""}">'
            f"{content}</div>")


def _section(title: str, note: str = "") -> str:
    # Dark TEXT over a coloured RULE, not white-on-fill: Outlook's print / PDF
    # drops every background, which turned the old navy bars into faint grey
    # headings (test print 2026-10-12, /Pictures/hr test.pdf). Borders print.
    bar = (f'<div style="font-family:{FONT_STACK};font-size:14px;font-weight:700;'
           f"color:{BRAND};border-bottom:3px solid {BRAND};padding:0 0 4px 0;"
           f'letter-spacing:1px;margin:26px 0 0 0;">{escape(title)}</div>')
    return bar + (_div(note, size=11, color=MUTED, margin="6px 0 6px 0") if note else "")


def _table(head: str, body: str) -> str:
    return (f'<table role="presentation" cellpadding="0" cellspacing="0" border="0" '
            f'width="100%" style="border-collapse:collapse;width:100%;">'
            f"<thead><tr>{head}</tr></thead><tbody>{body}</tbody></table>")


# ---------------------------------------------------------------------------
# Sections
# ---------------------------------------------------------------------------


def _tiles(summary: dict, snapshot: dict, last_week: dict) -> str:
    tiles = [
        ("Active employees", _n(summary.get("active_employees")), "time-off directory"),
        ("Open roles", _n(summary.get("open_roles")),
         f"{_n(summary.get('open_vacancies'))} open vacancies"),
        ("Active candidates", _n(snapshot.get("active_candidates")),
         f"{_n(snapshot.get('in_pipeline'))} in pipeline incl. applying"),
        ("Valid candidates LW", _n(last_week.get("valid")),
         f"{_n(last_week.get('screened'))} phone screened"),
        ("Hires LW", _n(last_week.get("hires")),
         f"{_n(snapshot.get('at_offer_stage'))} at approval / offer stage"),
        ("Stalled > 7 days", _n(snapshot.get("stalled_excl_bench")),
         f"outside Bench &middot; {_n(snapshot.get('stalled'))} incl. Bench"),
    ]
    cells = "".join(
        f'<td width="16%" valign="top" style="font-family:{FONT_STACK};padding:4px;">'
        f'<div style="font-family:{FONT_STACK};border:1px solid {BORDER};border-top:3px solid {BRAND};padding:10px;">'
        f'<div style="font-family:{FONT_STACK};font-size:10px;color:{MUTED};'
        f'text-transform:uppercase;letter-spacing:0.5px;font-weight:700;">{escape(label)}</div>'
        f'<div style="font-family:{FONT_STACK};font-size:24px;color:{INK};font-weight:700;'
        f'margin:4px 0 2px 0;">{value}</div>'
        f'<div style="font-family:{FONT_STACK};font-size:11px;color:{MUTED};">{sub}</div>'
        f"</div></td>"
        for label, value, sub in tiles
    )
    return (f'<table role="presentation" cellpadding="0" cellspacing="0" border="0" '
            f'width="100%" style="border-collapse:collapse;width:100%;"><tr>{cells}</tr></table>')


def _weekly(weeks: list[dict], tickets_are_stale: bool) -> str:
    head = _th("Week of", align="left") + "".join(
        _th(f"{'LAST WEEK<br>' if i == 0 else ''}{_short(date.fromisoformat(w['week_start']))}",
            bg=LW_BG if i == 0 else HEAD_BG,
            extra=f"border-left:2px solid {LW_BOX};border-right:2px solid {LW_BOX};" if i == 0 else "")
        for i, w in enumerate(weeks)
    ) + _th(f"Avg prior {len(weeks) - 1} wks") + _th("LW vs avg")
    body = ""
    for key, label, hint in WEEKLY_ROWS:
        values = [w[key] for w in weeks]
        stale = key in TICKET_ROWS and tickets_are_stale
        avg = baseline(values)
        text, colour = _delta(None if avg is None else values[0] - avg, key in INVERTED_ROWS)
        cells = "".join(
            _td(_n(v), bg=LW_BG if i == 0 else "", bold=i == 0,
                color=MUTED if stale else INK,
                extra=f"border-left:2px solid {LW_BOX};border-right:2px solid {LW_BOX};" if i == 0 else "")
            for i, v in enumerate(values)
        )
        label_html = (f"{escape(label)}"
                      f'<div style="font-family:{FONT_STACK};font-size:10px;color:{MUTED};">'
                      f"{escape(hint)}{' &middot; feed is stale' if stale else ''}</div>")
        body += ("<tr>" + _td(label_html, align="left", bold=True) + cells
                 + _td(DASH if avg is None else f"{avg:,.1f}", color=MUTED)
                 + _td(text, color=colour, bold=True) + "</tr>")
    return _table(head, body)


FLOW_BAR_MAX_BLOCKS = 20
BLOCK = "&#9608;"  # █ — a bar drawn in TEXT colour survives Outlook print/PDF


def _bar(n: int, peak: int, colour: str, align: str) -> str:
    """A bar of coloured block characters.

    The first version used filled table cells; Outlook's print / PDF dropped
    every background and the bars vanished entirely (2026-10-12). Text colour
    prints, so the bar is text.
    """
    if not n:
        return _td(DASH, align=align, color=MUTED, size=11, extra="width:260px;")
    blocks = max(1, round(FLOW_BAR_MAX_BLOCKS * n / peak)) if peak else 1
    return _td(BLOCK * blocks, align=align, color=colour, size=12,
               extra="width:260px;letter-spacing:-1px;white-space:nowrap;")


def _totals_headline(label: str, on: int, off: int) -> str:
    text, colour = _delta(on - off, False)
    return (f'<td width="50%" valign="top" style="font-family:{FONT_STACK};padding:4px;">'
            f'<div style="font-family:{FONT_STACK};border:1px solid {BORDER};'
            f'border-top:3px solid {BRAND};padding:10px;">'
            f'<div style="font-family:{FONT_STACK};font-size:10px;color:{MUTED};'
            f'text-transform:uppercase;letter-spacing:0.5px;font-weight:700;">{label}</div>'
            f'<div style="font-family:{FONT_STACK};font-size:22px;font-weight:700;color:{INK};'
            f'margin:4px 0 0 0;"><span style="font-family:{FONT_STACK};color:{GOOD};">'
            f'{_n(on)} on</span> <span style="font-family:{FONT_STACK};color:{MUTED};">vs</span> '
            f'<span style="font-family:{FONT_STACK};color:{BAD};">{_n(off)} off</span> '
            f'<span style="font-family:{FONT_STACK};font-size:14px;color:{colour};">'
            f"&nbsp;net {text}</span></div></div></td>")


def _flow_totals(totals: dict) -> str:
    """The full-period answer first: window total and YTD, on vs off."""
    if not totals:
        return ""
    ws, we = (date.fromisoformat(totals[k]) for k in ("window_start", "window_end"))
    cells = (_totals_headline(f"Full period &middot; {_short(ws)} &ndash; {_short(we)}",
                              totals["window"]["onboarding"], totals["window"]["offboarding"])
             + _totals_headline(f"{totals['year']} year to date &middot; to {_short(we)}",
                                totals["ytd"]["onboarding"], totals["ytd"]["offboarding"]))
    return (f'<table role="presentation" cellpadding="0" cellspacing="0" border="0" '
            f'width="100%" style="border-collapse:collapse;width:100%;margin:0 0 8px 0;">'
            f"<tr>{cells}</tr></table>")


def _flow_trend(weeks: list[dict], tickets_are_stale: bool, totals: dict) -> str:
    """ONBOARDING vs OFFBOARDING per week — the Jobs portal's "Exits vs New Hires"
    definition (IT ROUTE tickets), as mirrored bars with the weekly net."""
    on = [w["onboarding_tickets"] for w in weeks]
    off = [w["offboarding_tickets"] for w in weeks]
    peak = max(on + off + [0])
    head = (_th("Week of", align="left") + _th("Onboarding", align="right")
            + _th("", align="right") + _th("", align="left") + _th("Offboarding", align="left")
            + _th("Net"))
    body = ""
    for i, w in enumerate(weeks):
        net = on[i] - off[i]
        text, colour = _delta(net, False)
        lw = i == 0
        label = (("LAST WEEK &middot; " if lw else "")
                 + _short(date.fromisoformat(w["week_start"])))
        body += ("<tr>" + _td(label, align="left", bold=lw, bg=LW_BG if lw else "")
                 + _bar(on[i], peak, GOOD, "right")
                 + _td(_n(on[i]), bold=True, color=GOOD, extra="width:32px;")
                 + _td(_n(off[i]), align="left", bold=True, color=BAD, extra="width:32px;")
                 + _bar(off[i], peak, BAD, "left")
                 + _td(text, color=colour, bold=True) + "</tr>")
    t_on, t_off = sum(on), sum(off)
    text, colour = _delta(t_on - t_off, False)
    body += ("<tr>" + _td(f"{len(weeks)} weeks", align="left", bold=True, bg=HEAD_BG)
             + _td("", bg=HEAD_BG) + _td(_n(t_on), bold=True, color=GOOD, bg=HEAD_BG)
             + _td(_n(t_off), align="left", bold=True, color=BAD, bg=HEAD_BG)
             + _td("", bg=HEAD_BG) + _td(text, color=colour, bold=True, bg=HEAD_BG) + "</tr>")
    note = ""
    if tickets_are_stale:
        note = _div("&#9888; The ticket feed is stale — recent weeks may be incomplete.",
                    size=11, color=WARN_INK, margin="6px 0 0 0")
    return _flow_totals(totals) + _table(head, body) + note


def _roles(roles: list[dict]) -> str:
    if not roles:
        return _div("No ACTIVE positions on the Jobs portal.", color=MUTED)
    head = (_th("Role", align="left") + _th("Department", align="left") + _th("Days open")
            + _th("Open vac.") + _th("In pipeline") + _th("Sourcing") + _th("Screening")
            + _th("Interviews") + _th("Final / offer") + _th("New apps LW")
            + _th("Valid LW") + _th("Furthest stage", align="left"))
    body = ""
    for r in roles:
        aged = r["days_open"] > AGED_DAYS
        empty = r["in_pipeline"] == 0
        body += (
            "<tr>"
            + _td(escape(r["name"]), align="left", bold=True)
            + _td(escape(r["department"]), align="left", color=MUTED)
            + _td(_n(r["days_open"]), bg=AGED_BG if aged else "", bold=aged,
                  color=BAD if aged else INK)
            + _td(_n(r["open_vacancies"]))
            + _td(_n(r["in_pipeline"]), color=BAD if empty else INK, bold=empty)
            + _td(_n(r["sourcing"])) + _td(_n(r["screening"]))
            + _td(_n(r["interviews"])) + _td(_n(r["final"]))
            + _td(_n(r["new_last_week"])) + _td(_n(r["valid_last_week"]))
            + _td(escape(r["furthest_stage"] or "—"), align="left", color=MUTED)
            + "</tr>"
        )
    return _table(head, body)


def _hires(hires: list[dict]) -> str:
    if not hires:
        return _div("No hires recorded on the Jobs portal last week.", color=MUTED)
    head = _th("Hired on", align="left") + _th("Name", align="left") + \
        _th("Role", align="left") + _th("Department", align="left")
    body = "".join(
        "<tr>" + _td(_short(date.fromisoformat(h["hired_on"])), align="left")
        + _td(escape(h["name"]), align="left", bold=True)
        + _td(escape(h["position"]), align="left")
        + _td(escape(h["department"]), align="left", color=MUTED) + "</tr>"
        for h in hires
    )
    return _table(head, body)


def _indicators(snapshot: dict, annual: dict) -> str:
    ttf = snapshot["time_to_fill"]
    rows = [
        ("Average time to fill",
         f"{_n(ttf['avg_days'])} days",
         (f"Evergreen {_n(ttf['evergreen_days'])} d &middot; Standard {_n(ttf['standard_days'])} d "
          f"&middot; {_n(ttf['hires_measured'])} hires, all-time")),
        ("At approval / offer stage", _n(snapshot["at_offer_stage"]),
         "candidates now in CEO/VP Approval, Send Offer or Offer Accepted"),
        (f"New hires {annual.get('year')} YTD", _n(annual.get("new_hires")),
         "time-off directory hire dates"),
        (f"Exits {annual.get('year')} YTD", _n(annual.get("offboarding")),
         "IT ROUTE offboarding tickets"),
        ("Turnover YTD", _pct(annual.get("turnover_rate")),
         escape(annual.get("turnover_basis") or "not computable")),
    ]
    head = _th("Indicator", align="left") + _th("Value") + _th("Basis", align="left")
    body = "".join(
        "<tr>" + _td(escape(k), align="left", bold=True)
        + _td(v, bold=True, extra="white-space:nowrap;")
        + _td(b, align="left", color=MUTED, size=11) + "</tr>"
        for k, v, b in rows
    )
    return _table(head, body)


def _stage_line(snapshot: dict) -> str:
    parts = [f"{escape(s['stage'])} <b>{_n(s['count'])}</b>"
             for s in snapshot["by_stage"] if s["count"]]
    return _div("Candidates in pipeline now, by stage: " + (" &middot; ".join(parts) or DASH),
                size=12, color=INK, margin="8px 0 0 0")


# ---------------------------------------------------------------------------
# Document
# ---------------------------------------------------------------------------


def render_html(*, subject: str, summary: dict, weeks: list[dict], snapshot: dict,
                roles: list[dict], hires_last_week: list[dict], annual: dict,
                pipeline_as_of: Optional[str], tickets_as_of: Optional[str],
                people_as_of: Optional[str], tickets_are_stale: bool,
                generated: datetime, exec_report_url: str,
                jobs_reports_url: str, ticket_totals: Optional[dict] = None) -> str:
    lw = weeks[0]
    banner = ""
    if tickets_are_stale:
        banner = (f'<div style="font-family:{FONT_STACK};font-size:12px;color:{WARN_INK};'
                  f"background-color:{WARN_BG};{PRINT_EXACT}border-left:4px solid {WARN_INK};"
                  f"padding:8px 12px;margin:12px 0 0 0;\">"
                  f"&#9888; The IT ROUTE ticket feed has no ticket since {_ts(tickets_as_of)} — "
                  f"onboarding and exit counts below may be incomplete.</div>")
    aged = sum(1 for r in roles if r["days_open"] > AGED_DAYS)
    empty = sum(1 for r in roles if r["in_pipeline"] == 0)
    link = f"color:{LINK};font-family:{FONT_STACK};"

    parts = [
        (f'<div style="font-family:{FONT_STACK};font-size:20px;font-weight:700;color:{BRAND};">'
         f"{escape(subject)}</div>"),
        _div(f"Last week: {_short(date.fromisoformat(lw['week_start']))} &ndash; "
             f"{_short(date.fromisoformat(lw['week_end']))} (Monday&ndash;Sunday, CST) "
             f"&middot; generated {generated.strftime('%b')} {generated.day}, "
             f"{generated.strftime('%H:%M')} CST", size=12, color=MUTED, margin="2px 0 12px 0"),
        banner,
        _tiles(summary, snapshot, lw),
        _section(f"WEEKLY PIPELINE — LAST {len(weeks)} WEEKS",
                 "Each candidate counts once per milestone, in the week they FIRST reached it. "
                 "Latest week first; the delta compares last week with the average of the "
                 f"{len(weeks) - 1} weeks before it."),
        _weekly(weeks, tickets_are_stale),
        _stage_line(snapshot),
        _section("ONBOARDING VS OFFBOARDING — WEEKLY TREND",
                 "IT ROUTE onboarding and offboarding tickets per week (the Jobs portal's "
                 "Exits vs New Hires definition). Net = onboarding &minus; offboarding."),
        _flow_trend(weeks, tickets_are_stale, ticket_totals or {}),
        _section("OPEN ROLES",
                 f"{len(roles)} active roles, oldest first &middot; "
                 f"{aged} open more than {AGED_DAYS} days (red) &middot; "
                 f"{empty} with nobody in the pipeline. Pipeline columns are candidates "
                 "in process or applying, right now."),
        _roles(roles),
        _section("HIRES LAST WEEK"),
        _hires(hires_last_week),
        _section("KEY INDICATORS", "Same definitions as the Jobs portal's Reports &amp; "
                 "Analytics page; HIRED = accepted offer."),
        _indicators(snapshot, annual),
        _div(f'<a href="{jobs_reports_url}" style="{link}">Jobs portal &mdash; Reports &amp; '
             f'Analytics</a> &middot; <a href="{exec_report_url}" style="{link}">'
             f"Space &mdash; Exec Meeting &ndash; Recruitment</a>", size=12),
    ]
    return (
        f'<div style="font-family:{FONT_STACK};background-color:#FFFFFF;{PRINT_EXACT}padding:16px;">'
        f'<table role="presentation" cellpadding="0" cellspacing="0" border="0" '
        f'width="{PAGE_WIDTH}" style="border-collapse:collapse;max-width:{PAGE_WIDTH}px;">'
        f'<tr><td style="font-family:{FONT_STACK};">{"".join(parts)}</td></tr></table></div>'
    )
