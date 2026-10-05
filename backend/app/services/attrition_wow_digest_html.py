"""Attrition WoW weekly e-mail — HTML rendering only.

Mirrors the request PDF (2026-10-05): intro + LAST WEEK HIGHLIGHTS prose, then
per scope (UNILINK black / CORP red / DFW navy bar) the period chips, the Lane
and Customer Attrition cards and the metric table with the LAST WEEK block
boxed in green; then LAST WEEK ATTRITION — customers below their 8-week average
(CORP, DFW), inactive and reactivated customers.

Outlook rules (SPEC-CODE-RULES §21): FONT_STACK / MONO_STACK inline on EVERY
td / th / div / span / a, hex colours only, tables for layout, no webfonts.
``None`` renders as an em dash, never 0. Number formats are the page's
(``frontend/app/reports/attrition-wow/format.ts``).
"""
from __future__ import annotations

from datetime import date, datetime
from html import escape
from typing import Optional

from app.services.attrition_wow_digest import round_half_away
from app.services.team_perf_digest_html import FONT_STACK, MONO_STACK

PAGE_WIDTH = 1000

INK = "#111827"
MUTED = "#6B7280"
BORDER = "#E5E7EB"
CHIP_BG = "#F3F4F6"
GOOD = "#15803D"
BAD = "#DC2626"
FLAT = "#B45309"
L8W_BG = "#FEFCE8"
L2W_BG = "#EFF6FF"
LW_BG = "#ECFDF5"
LW_BOX = "#00B050"
CELL_GOOD_BG = "#DCFCE7"
CELL_BAD_BG = "#FEE2E2"
LINK = "#2563EB"

SCOPE_BAR = {"UNILINK": "#000000", "CORP": "#C00000", "DFW": "#002060"}
DASH = "&mdash;"

METRICS = (
    ("loads", "# Loads"),
    ("revenue", "$ Revenue"),
    ("profit", "$ Profit"),
    ("margin_pct", "% Margin"),
    ("profit_per_load", "$ Profit per Load"),
)


# ---------------------------------------------------------------------------
# Formatting (format.ts)
# ---------------------------------------------------------------------------


def _num(v: Optional[float], places: int = 0) -> str:
    if v is None:
        return DASH
    return f"{round_half_away(v, places):,.{places}f}"


def _usd(v: Optional[float]) -> str:
    if v is None:
        return DASH
    r = round_half_away(v)
    return f"-${abs(r):,.0f}" if r < 0 else f"${r:,.0f}"


def _pct(v: Optional[float]) -> str:
    return DASH if v is None else f"{round_half_away(v * 100, 2):,.2f}%"


def _signed(v: Optional[float], kind: str, invert: bool = False) -> tuple[str, str]:
    """(text, colour) — kind: count | usd | pct | pp.

    As format.ts ``fmtSigned*``: sign and colour follow the RAW value, the
    digits are rounded — so +0.4 customers reads "+0" in green, exactly 0 reads
    "0" in amber.
    """
    if v is None:
        return DASH, MUTED
    if kind in ("pct", "pp"):
        n = abs(round_half_away(v * 100, 2))
        body = f"{n:,.2f}%" if kind == "pct" else f"{n:.2f}pp"
    elif kind == "usd":
        body = f"${abs(round_half_away(v)):,.0f}"
    else:
        body = f"{abs(round_half_away(v)):,.0f}"
    sign = "+" if v > 0 else "-" if v < 0 else ""
    good, bad = (BAD, GOOD) if invert else (GOOD, BAD)
    colour = good if v > 0 else bad if v < 0 else FLAT
    return f"{sign}{body}", colour


def _short(d: date) -> str:
    return f"{d.strftime('%b')} {d.day}"


def _range(w: dict) -> str:
    return (f"{_short(date.fromisoformat(w['start']))} &ndash; "
            f"{_short(date.fromisoformat(w['end']))}")


# ---------------------------------------------------------------------------
# Cell helpers — every element carries the font inline
# ---------------------------------------------------------------------------


def _td(content: str, *, align: str = "left", bg: str = "", color: str = INK,
        mono: bool = False, bold: bool = False, size: int = 12,
        extra: str = "") -> str:
    font = MONO_STACK if mono else FONT_STACK
    style = (f"font-family:{font};font-size:{size}px;color:{color};"
             f"text-align:{align};padding:6px 8px;border-bottom:1px solid {BORDER};"
             f"{'font-weight:700;' if bold else ''}"
             f"{f'background-color:{bg};' if bg else ''}{extra}")
    attr = f' bgcolor="{bg}"' if bg else ""
    return f'<td style="{style}"{attr}>{content}</td>'


def _th(content: str, *, align: str = "right", bg: str = "", extra: str = "") -> str:
    style = (f"font-family:{FONT_STACK};font-size:10px;color:{MUTED};"
             f"text-transform:uppercase;letter-spacing:0.5px;font-weight:700;"
             f"text-align:{align};padding:6px 8px;border-bottom:1px solid {BORDER};"
             f"{f'background-color:{bg};' if bg else ''}{extra}")
    attr = f' bgcolor="{bg}"' if bg else ""
    return f'<th style="{style}"{attr}>{content}</th>'


def _p(content: str, *, size: int = 14, bold: bool = False, margin: str = "0 0 12px 0") -> str:
    return (f'<div style="font-family:{FONT_STACK};font-size:{size}px;color:{INK};'
            f'line-height:1.5;margin:{margin};{"font-weight:700;" if bold else ""}">'
            f"{content}</div>")


# ---------------------------------------------------------------------------
# Blocks
# ---------------------------------------------------------------------------


def _scope_bar(name: str) -> str:
    return (
        f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" '
        f'style="border-collapse:collapse;margin:28px 0 12px 0;"><tr>'
        f'<td bgcolor="{SCOPE_BAR[name]}" style="background-color:{SCOPE_BAR[name]};'
        f'font-family:{FONT_STACK};font-size:26px;font-weight:800;color:#FFFFFF;'
        f'padding:8px 12px;">{escape(name)}</td></tr></table>'
    )


def _chips(windows: dict) -> str:
    chip = (f'<span style="font-family:{FONT_STACK};font-size:11px;color:{INK};'
            f'background-color:{CHIP_BG};padding:3px 8px;margin-right:8px;'
            f'border-radius:10px;">')
    return (
        f'<div style="font-family:{FONT_STACK};font-size:11px;margin:0 0 10px 0;">'
        f'{chip}<b style="font-family:{FONT_STACK};">Last 8 Weeks:</b> {_range(windows["l8w"])}</span>'
        f'{chip}<b style="font-family:{FONT_STACK};">Last Week:</b> {_range(windows["lw"])}</span>'
        f'{chip}<b style="font-family:{FONT_STACK};">Last 2 Weeks:</b> {_range(windows["l2w"])}</span>'
        f"</div>"
    )


def _card(title: str, block: dict) -> str:
    d_txt, d_col = _signed(block.get("diff"), "count")
    p_txt, p_col = _signed(block.get("pct"), "pct", invert=True)
    cells = (
        ("L8W", _num(block.get("l8w"), 1), INK),
        ("LW", _num(block.get("lw")), INK),
        ("&Delta; (LW &minus; L8W)", d_txt, d_col),
        ("% &Delta;", p_txt, p_col),
    )
    tds = "".join(
        f'<td width="25%" style="font-family:{FONT_STACK};padding:6px 8px;'
        f'background-color:#F9FAFB;border:1px solid {BORDER};" bgcolor="#F9FAFB">'
        f'<div style="font-family:{FONT_STACK};font-size:9px;color:{MUTED};'
        f'text-transform:uppercase;">{label}</div>'
        f'<div style="font-family:{FONT_STACK};font-size:20px;font-weight:600;'
        f'color:{col};">{val}</div></td>'
        for label, val, col in cells
    )
    return (
        f'<td width="50%" valign="top" style="font-family:{FONT_STACK};padding:0 6px 0 0;">'
        f'<table role="presentation" width="100%" cellpadding="0" cellspacing="4" '
        f'style="border:1px solid {BORDER};border-radius:6px;">'
        f'<tr><td colspan="4" style="font-family:{FONT_STACK};font-size:11px;'
        f'font-weight:700;color:{MUTED};padding:6px 8px;">{title}</td></tr>'
        f"<tr>{tds}</tr></table></td>"
    )


_DELTA_KIND = {"loads": "count", "revenue": "usd", "profit": "usd",
               "margin_pct": "pp", "profit_per_load": "usd"}


def _fmt_metric(key: str, v: Optional[float], *, avg: bool) -> str:
    """Loads averages carry one decimal (COUNT1), LW loads none (COUNT)."""
    if key == "loads":
        return _num(v, 1) if avg else _num(v)
    if key == "margin_pct":
        return _pct(v)
    return _usd(v)


def _metric_table(data: dict) -> str:
    box_top = f"border-top:2px solid {LW_BOX};"
    box_bot = f"border-bottom:2px solid {LW_BOX};"
    left = f"border-left:2px solid {LW_BOX};"
    right = f"border-right:2px solid {LW_BOX};"
    head = (
        "<tr>"
        + _th("Metric", align="left")
        + _th("L8W Avg", bg=L8W_BG)
        + _th("L2W Avg", bg=L2W_BG)
        + _th("&Delta; (L2W vs L8W)", bg=L2W_BG)
        + _th("% (L2W vs L8W)", bg=L2W_BG)
        + _th("Last Week", bg=LW_BG, extra=box_top + left)
        + _th("&Delta; (LW vs L8W)", bg=LW_BG, extra=box_top)
        + _th("% (LW vs L8W)", bg=LW_BG, extra=box_top + right)
        + "</tr>"
    )
    rows = []
    last = len(METRICS) - 1
    for i, (key, label) in enumerate(METRICS):
        m = data[key]
        dkind = _DELTA_KIND[key]
        d2, d2c = _signed(m["diff_l2w_vs_l8w"]["diff"], dkind)
        p2, p2c = _signed(m["diff_l2w_vs_l8w"]["pct"], "pct")
        d1, d1c = _signed(m["diff_lw_vs_l8w"]["diff"], dkind)
        p1, p1c = _signed(m["diff_lw_vs_l8w"]["pct"], "pct")
        bot = box_bot if i == last else ""
        rows.append(
            "<tr>"
            + _td(label, bold=True, size=11)
            + _td(_fmt_metric(key, m["l8w_avg"], avg=True), align="right", bg=L8W_BG, mono=True)
            + _td(_fmt_metric(key, m["l2w_avg"], avg=True), align="right", bg=L2W_BG, mono=True)
            + _td(d2, align="right", bg=L2W_BG, mono=True, color=d2c)
            + _td(p2, align="right", bg=L2W_BG, mono=True, color=p2c)
            + _td(_fmt_metric(key, m["lw"], avg=False), align="right", bg=LW_BG, mono=True,
                  extra=left + bot)
            + _td(d1, align="right", bg=LW_BG, mono=True, color=d1c, extra=bot)
            + _td(p1, align="right", bg=LW_BG, mono=True, color=p1c,
                  extra=right + bot)
            + "</tr>"
        )
    return (
        f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" '
        f'style="border-collapse:collapse;border:1px solid {BORDER};margin-top:10px;">'
        f"{head}{''.join(rows)}</table>"
    )


def _scope_section(name: str, data: dict, windows: dict) -> str:
    return (
        _scope_bar(name)
        + _chips(windows)
        + '<table role="presentation" width="100%" cellpadding="0" cellspacing="0" '
        'style="border-collapse:collapse;"><tr>'
        + _card("LANE ATTRITION", data["active_lanes"])
        + _card("CUSTOMER ATTRITION", data["active_customers"])
        + "</tr></table>"
        + _metric_table(data)
    )


def _customer_table(rows: list[dict], weeks: list[date]) -> str:
    if not rows:
        return _p(
            f'<span style="font-family:{FONT_STACK};color:{MUTED};">'
            "No customer shipped below its 8-week average last week.</span>",
            size=13,
        )
    hl = f"border-left:2px solid {LW_BOX};border-right:2px solid {LW_BOX};"
    head = (
        "<tr>"
        + _th("Team", align="left")
        + _th("Customer", align="left")
        + _th("8-week avg")
        + _th("Difference LW &ndash; L8W", extra=hl + f"border-top:2px solid {LW_BOX};")
        + _th("Difference LW &ndash; L2W")
        + "".join(_th(_short(w)) for w in weeks)
        + "</tr>"
    )
    body = []
    last = len(rows) - 1
    for i, r in enumerate(rows):
        bot = f"border-bottom:2px solid {LW_BOX};" if i == last else ""
        cells = []
        for v in r["values"]:
            if v is None:
                cells.append(_td(DASH, align="right", mono=True, color=MUTED, size=11))
            elif v >= r["ref"]:
                cells.append(_td(_num(v), align="right", mono=True, size=11,
                                 bg=CELL_GOOD_BG, color=GOOD))
            else:
                cells.append(_td(_num(v), align="right", mono=True, size=11,
                                 bg=CELL_BAD_BG, color=BAD))
        body.append(
            "<tr>"
            + _td(escape(r["team"] or ""), size=11, color=MUTED,
                  extra="white-space:nowrap;")
            + _td(escape(r["customer"]), size=11, color=LINK)
            + _td(_num(r["ref"]), align="right", mono=True, bold=True, size=11)
            + _td(_num(r["diff"]), align="right", mono=True, size=11, color=BAD,
                  extra=hl + bot)
            + _td(_num(r["diff2w"]), align="right", mono=True, size=11,
                  color=BAD if (r["diff2w"] or 0) < 0 else INK)
            + "".join(cells)
            + "</tr>"
        )
    return (
        f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" '
        f'style="border-collapse:collapse;border:1px solid {BORDER};margin:4px 0 18px 0;">'
        f"{head}{''.join(body)}</table>"
    )


def _name_list(names: list[str]) -> str:
    return ", ".join(escape(n) for n in names) + "." if names else "&ndash;"


def _attrition_section(lists: dict, weeks: list[date]) -> str:
    bullet = lambda t: _p(f"&bull;&nbsp;&nbsp;{t}", bold=True, margin="18px 0 8px 0")  # noqa: E731
    out = [_scope_bar_plain("LAST WEEK ATTRITION:")]
    out.append(bullet("Customers below their 8-Week average load volume:"))
    for name in ("CORP", "DFW"):
        out.append(_p(f"{name}:", bold=True, margin="10px 0 6px 0"))
        out.append(_customer_table(lists[name]["below"], weeks))
    out.append(bullet("Inactive customers:"))
    out.append(_p("Shipped the week before last week, but no loads last week.",
                  size=12, margin="0 0 6px 0"))
    for name in ("CORP", "DFW"):
        out.append(_p(f"<b style=\"font-family:{FONT_STACK};\">{name}</b>: "
                      f"{_name_list(lists[name]['inactive'])}", margin="0 0 6px 18px"))
    out.append(bullet("Reactivated customers:"))
    out.append(_p("No loads the week before last week, shipped again last week.",
                  size=12, margin="0 0 6px 0"))
    for name in ("CORP", "DFW"):
        out.append(_p(f"<b style=\"font-family:{FONT_STACK};\">{name}</b>: "
                      f"{_name_list(lists[name]['reactivated'])}", margin="0 0 6px 18px"))
    return "".join(out)


def _scope_bar_plain(text: str) -> str:
    return _p(text, size=15, bold=True, margin="30px 0 6px 0")


# ---------------------------------------------------------------------------
# Document
# ---------------------------------------------------------------------------


def render_html(*, subject: str, week_no: int, windows: dict, scopes: dict,
                highlights: dict, lists: dict, weeks: list[date],
                generated: datetime, data_as_of: Optional[str],
                report_url: str) -> str:
    intro = _p(
        f"Please find below the Attrition WoW highlights for Week {week_no} "
        f"({_range(windows['lw'])}). Based on Link "
        f'<a href="{escape(report_url)}" style="font-family:{FONT_STACK};color:{LINK};">'
        f"{escape(report_url)}</a>"
    )
    hl = _p("LAST WEEK HIGHLIGHTS:", bold=True, margin="16px 0 10px 0") + "".join(
        _p(f'<b style="font-family:{FONT_STACK};">'
           f'{"UNILINK Overall Performance" if n == "UNILINK" else n}:</b> '
           f"{escape(highlights[n])}")
        for n in ("UNILINK", "CORP", "DFW")
    )
    sections = "".join(_scope_section(n, scopes[n], windows)
                       for n in ("UNILINK", "CORP", "DFW"))
    footer = _p(
        f"Generated {generated.strftime('%Y-%m-%d %H:%M')} Central Time from the Attrition "
        f"WoW report; newest load departure in the data: {escape(data_as_of or 'unknown')}. Weeks are Monday&ndash;Sunday; the 8-week baseline ends the "
        "day before last week starts. Loads count billed loads (total charge "
        "&ne; 0); revenue and profit include every load.",
        size=11, margin="28px 0 0 0",
    )
    return (
        "<!DOCTYPE html><html><head><meta charset=\"utf-8\">"
        f"<title>{escape(subject)}</title></head>"
        f'<body style="margin:0;padding:0;background-color:#FFFFFF;" bgcolor="#FFFFFF">'
        f'<table role="presentation" width="{PAGE_WIDTH}" cellpadding="0" cellspacing="0" '
        f'style="width:{PAGE_WIDTH}px;border-collapse:collapse;"><tr>'
        f'<td style="font-family:{FONT_STACK};padding:16px;color:{INK};">'
        f"{intro}{hl}{sections}{_attrition_section(lists, weeks)}{footer}"
        "</td></tr></table></body></html>"
    )
