"""Ops Portal Overview — "Performance for Team N" digest (HTML + charts).

Rendering only: every value handed in is already computed and guarded by
``app/services/team_perf_digest.py``. ``None`` always renders as an em dash —
never ``0`` — so a missing denominator can't be mistaken for a real zero.

Outlook 365 desktop resets ``font-family`` at every nested ``<table>``
boundary, so FONT_STACK / MONO_STACK are declared inline on EVERY td / th /
div / span / a (SPEC-CODE-RULES §21). Never add a webfont ``<link>`` —
Outlook strips it.

Charts are QuickChart ``<img>`` URLs: e-mail clients cannot run JS, so a
canvas/Chart.js block would render as a blank box. The configs are 100%
STATIC — no function-valued options at all, which sidesteps the
quote-free-placeholder-token trap entirely (a function option smuggled
through ``json.dumps`` fails SILENTLY with HTTP 200 and no labels). Values are
pre-rounded in Python so no ``formatter`` callback is needed.
"""
from __future__ import annotations

import json
from html import escape
from typing import Any
from urllib.parse import quote

# Outlook resets font-family inside nested tables — declare inline on every td.
FONT_STACK = (
    "'Segoe UI',-apple-system,BlinkMacSystemFont,Arial,Helvetica,Verdana,sans-serif"
)
MONO_STACK = "Consolas,'SF Mono',Menlo,'Courier New',monospace"

NAVY = "#1B3A5C"
GREEN = "#16A34A"
GREEN_BG = "#DCFCE7"
GREEN_TX = "#166534"
RED = "#DC2626"
RED_BG = "#FEE2E2"
RED_TX = "#991B1B"
GREY = "#6B7280"
GREY_BG = "#F3F4F6"
INK = "#111827"
BORDER = "#E5E7EB"

DASH = "&mdash;"

# Customer Actual Performance (TM) panel — how many customers are listed and on
# what basis. Request 2026-08-25: rank by PROFIT, not revenue. The caption used
# to hardcode the literal "top 15 by revenue" while the limit lived in
# team_perf_digest.py, so changing one silently made the other lie; both now
# read these, and a test asserts the rendered caption against the value actually
# requested. `_SORT` is the /actuals sort key, not prose — see
# routers/ops_portal_overview/actuals.py::sort_key.
CUSTOMER_PANEL_LIMIT = 15
# /actuals applies its sort and its LIMIT server-side, and it appends
# budget-only customers with zero production. Under `revenue_desc` those
# rows sorted to the very bottom and never reached a top-15 slot; under
# `profit_desc` a zero sorts ABOVE every loss-making customer, so they would
# occupy slots and then be dropped by the display filter — silently showing
# fewer than 15 real customers. So we fetch wide, filter, THEN slice.
CUSTOMER_PANEL_FETCH = 500  # == the /actuals `limit` ceiling (ge=1, le=500)
CUSTOMER_PANEL_SORT = "profit_desc"
CUSTOMER_PANEL_BASIS = "profit"

QUICKCHART = "https://quickchart.io/chart"

# ---------------------------------------------------------------------------
# Chart palettes — one per trend chart (request 2026-08-17)
# ---------------------------------------------------------------------------
# The bars are UNFILLED: ``backgroundColor`` is transparent and the shape is
# carried entirely by ``borderColor``. Two Chart.js defaults make that a
# three-property change, not a one-property one:
#
#   * bar ``borderWidth`` defaults to **0** — a transparent bar with no border
#     width is an INVISIBLE bar, and QuickChart renders it happily at HTTP 200;
#   * bar ``borderSkipped`` defaults to ``"start"``, which omits the base edge
#     and leaves the outline open at the bottom. ``False`` closes all four.
#
# ⚠ The data-label colours are deliberately NOT the series colours. The label
# numbers sit on white (bar labels above the bar, line labels on a white chip),
# and two of the three requested colours fail WCAG AA badly as text on white —
# measured, not guessed:
#
#   | as label text on #FFFFFF        | ratio   |
#   |---------------------------------|---------|
#   | #ECC910 Profit line             | 1.49:1  ✗ -> #6B5800 (6.86:1)
#   | #21BF6A Customers outline       | 2.41:1  ✗ -> GREEN_TX #166534 (7.12:1)
#   | #14718A Margin line             | 5.51:1  ✓ used as-is
#
# So the bars and lines get the exact RGB values that were asked for, and only
# the small numbers use a darkened companion of the same hue. Taking the
# request literally here would render labels that are technically present and
# practically invisible. ``tests/test_team_digest_chart_style.py`` re-computes
# every ratio, so a future palette edit cannot quietly undo this.
BAR_BORDER_WIDTH = 2

CHART_LOADS_PROFIT = {
    "bar_border": RED,                  # rgb(220,38,38) — same red, now an outline
    "bar_label": RED_TX,
    "line": "#ECC910",                  # rgb(236,201,16)
    "line_label": "#6B5800",
    "line_chip_border": "#FDE68A",
}

CHART_CUSTOMERS_MARGIN = {
    "bar_border": "#21BF6A",            # rgb(33,191,106)
    "bar_label": GREEN_TX,
    "line": "#14718A",                  # rgb(20,113,138)
    "line_label": "#14718A",
    "line_chip_border": "#A5D4E2",
}


# ---------------------------------------------------------------------------
# Formatting — None is always an em dash, never 0
# ---------------------------------------------------------------------------


def _fmt(value: Any, kind: str) -> str:
    """usd | usdSigned | pct | pctSigned | pp | count. ``None`` → em dash."""
    if value is None:
        return DASH
    try:
        n = float(value)
    except (TypeError, ValueError):
        return DASH
    if n != n or n in (float("inf"), float("-inf")):
        return DASH
    if kind == "count":
        return f"{int(round(n)):,}"
    if kind == "usd":
        return ("-" if n < 0 else "") + f"${abs(n):,.0f}"
    if kind == "usdSigned":
        return ("-" if n < 0 else "+") + f"${abs(n):,.0f}"
    if kind == "pct":
        return f"{n:,.1f}%"
    if kind == "pctSigned":
        return ("-" if n < 0 else "+") + f"{abs(n):,.1f}%"
    if kind == "pp":
        return ("-" if n < 0 else "+") + f"{abs(n):,.1f} pp"
    return str(value)


def _cell_color(value: Any, kind: str) -> str:
    """Negatives red for the signed kinds; otherwise neutral dark."""
    if value is None:
        return GREY
    try:
        n = float(value)
    except (TypeError, ValueError):
        return GREY
    if kind in ("usdSigned", "pctSigned", "pp") and n < 0:
        return RED
    return INK


def _td(content: str, *, style: str = "") -> str:
    return f'<td style="font-family:{FONT_STACK};{style}">{content}</td>'


# ---------------------------------------------------------------------------
# Pills
# ---------------------------------------------------------------------------


def _pill_html(pill: dict) -> str:
    """One trend row: label on the left, green ▲ / red ▼ chip on the right."""
    delta = pill.get("delta")
    unit = pill.get("unit", "%")
    kind = "pp" if unit == "pp" else "pctSigned"
    if delta is None:
        bg, tx, arrow = GREY_BG, GREY, ""
        text = DASH
    else:
        up = delta >= 0
        bg, tx = (GREEN_BG, GREEN_TX) if up else (RED_BG, RED_TX)
        arrow = "&#9650; " if up else "&#9660; "
        text = _fmt(delta, kind)
    basis = pill.get("basis")
    basis_txt = ""
    if basis is not None:
        basis_txt = (
            f' <span style="font-family:{FONT_STACK};font-size:10px;color:{GREY};">'
            f'({_fmt(basis, pill.get("basis_kind", "usd"))} {escape(pill.get("basis_label", ""))})</span>'
        )
    return (
        '<tr>'
        + _td(
            f'{escape(pill.get("label", ""))}{basis_txt}',
            style=f"font-size:11px;color:{GREY};padding:3px 0;",
        )
        + _td(
            f'<span style="font-family:{FONT_STACK};display:inline-block;background:{bg};'
            f'color:{tx};font-size:11px;font-weight:700;padding:2px 8px;border-radius:10px;'
            f'white-space:nowrap;">{arrow}{text}</span>',
            style="text-align:right;padding:3px 0;white-space:nowrap;",
        )
        + '</tr>'
    )


def _pills_table(pills: list[dict]) -> str:
    rows = "".join(_pill_html(p) for p in pills)
    return (
        f'<table cellpadding="0" cellspacing="0" border="0" width="100%" '
        f'style="border-collapse:collapse;font-family:{FONT_STACK};margin-top:8px;">'
        f"{rows}</table>"
    )


# ---------------------------------------------------------------------------
# Cards
# ---------------------------------------------------------------------------


def _card_shell(inner: str) -> str:
    return (
        f'<table cellpadding="0" cellspacing="0" border="0" width="100%" '
        f'style="background:#FFFFFF;border:1px solid {BORDER};border-radius:8px;'
        f'border-collapse:separate;font-family:{FONT_STACK};">'
        f'<tr><td style="font-family:{FONT_STACK};padding:12px 14px;">{inner}</td></tr>'
        f"</table>"
    )


def _card_title(text: str) -> str:
    return (
        f'<div style="font-family:{FONT_STACK};font-size:10px;font-weight:700;'
        f'color:{NAVY};text-transform:uppercase;letter-spacing:0.06em;">{escape(text)}</div>'
    )


def _big(text: str, *, color: str = INK, size: int = 28) -> str:
    return (
        f'<span style="font-family:{FONT_STACK};font-size:{size}px;font-weight:800;'
        f'color:{color};line-height:1.1;">{text}</span>'
    )


def _caption(text: str) -> str:
    return (
        f'<div style="font-family:{FONT_STACK};font-size:11px;color:{GREY};'
        f'margin-top:2px;">{escape(text)}</div>'
    )


def _card_profit(card: dict) -> str:
    profit = card["profit"]
    inner = (
        _card_title("Actual Profit (MTD)")
        + f'<div style="font-family:{FONT_STACK};margin-top:6px;">'
        + _big(_fmt(profit, "usd"), color=(RED if (profit or 0) < 0 else INK))
        + f'<span style="font-family:{FONT_STACK};font-size:12px;color:{GREY};'
          f'margin-left:10px;">Margin&nbsp;'
        + f'<strong style="font-family:{FONT_STACK};color:{INK};">'
        + _fmt(card["margin_pct"], "pct")
        + "</strong></span></div>"
        + _caption(card["caption"])
        + _pills_table(card["pills"])
    )
    return _card_shell(inner)


def _card_budget(card: dict) -> str:
    ach = card["ytd_achievement_pct"]
    color = INK if ach is None else (GREEN if ach >= 100 else RED)
    inner = (
        _card_title("Profit Budget Performance (TM)")
        + f'<div style="font-family:{FONT_STACK};margin-top:6px;">'
        + _big(_fmt(ach, "pct"), color=color)
        + f'<span style="font-family:{FONT_STACK};font-size:12px;color:{GREY};'
          f'margin-left:10px;">of budget</span></div>'
        + _caption(card["caption"])
        + _pills_table(card["pills"])
    )
    return _card_shell(inner)


def _card_rate(card: dict) -> str:
    inner = (
        _card_title(card["title"])
        + f'<div style="font-family:{FONT_STACK};margin-top:6px;">'
        + _big(_fmt(card["value"], "pct"), size=24)
        + "</div>"
        + _pills_table([card["pill"]])
    )
    return _card_shell(inner)


def _card_projection(card: dict) -> str:
    if not card["has_budget"]:
        chip_bg, chip_tx, chip_txt = GREY_BG, GREY, "No budget"
    elif card["on_track"]:
        chip_bg, chip_tx, chip_txt = GREEN_BG, GREEN_TX, "On track"
    else:
        chip_bg, chip_tx, chip_txt = RED_BG, RED_TX, "Behind"
    inner = (
        _card_title("Projected Profit Performance (TM)")
        + f'<div style="font-family:{FONT_STACK};margin-top:6px;">'
        + _big(_fmt(card["proj_profit"], "usd"))
        + f'<span style="font-family:{FONT_STACK};display:inline-block;background:{chip_bg};'
          f'color:{chip_tx};font-size:11px;font-weight:700;padding:3px 10px;'
          f'border-radius:10px;margin-left:10px;vertical-align:middle;">{chip_txt}</span>'
          "</div>"
        + _caption(
            f"Projected month-end vs monthly budget "
            f"{_plain(_fmt(card['month_budget'], 'usd'))} "
            f"({_plain(_fmt(card['achievement_pct'], 'pct'))} of budget)"
        )
    )
    return _card_shell(inner)


def _plain(s: str) -> str:
    """Un-escape the entities _fmt emits so _caption's escape() is a no-op."""
    return s.replace(DASH, "—")


# ---------------------------------------------------------------------------
# Customer table
# ---------------------------------------------------------------------------


_CUST_COLS = (
    ("Customer", "left"),
    ("Volume", "right"),
    ("Revenue", "right"),
    ("Profit", "right"),
    ("Margin", "right"),
)


def _cust_head() -> str:
    return "".join(
        f'<th style="font-family:{FONT_STACK};padding:6px 8px;text-align:{align};'
        f'font-size:9px;color:{NAVY};text-transform:uppercase;letter-spacing:0.04em;'
        f'font-weight:700;border-bottom:2px solid {BORDER};">{label}</th>'
        for label, align in _CUST_COLS
    )


def _cust_row(
    name: str, vol: Any, rev: Any, prof: Any, margin: Any, *, bold: bool = False
) -> str:
    weight = "700" if bold else "400"
    bg = "background:#F9FAFB;" if bold else ""
    cells = [
        f'<td style="font-family:{FONT_STACK};{bg}padding:5px 8px;font-size:11px;'
        f'color:{INK};font-weight:{weight};border-bottom:1px solid {GREY_BG};">'
        f"{escape(str(name))}</td>"
    ]
    for value, kind in ((vol, "count"), (rev, "usd"), (prof, "usdSigned"), (margin, "pct")):
        cells.append(
            f'<td style="font-family:{FONT_STACK};{bg}padding:5px 8px;text-align:right;'
            f'font-size:11px;color:{_cell_color(value, kind)};font-weight:{weight};'
            f'font-variant-numeric:tabular-nums;border-bottom:1px solid {GREY_BG};">'
            f"{_fmt(value, kind)}</td>"
        )
    return "<tr>" + "".join(cells) + "</tr>"


def _customer_panel(
    rows: list[dict],
    totals: dict,
    *,
    total_scope: str = "team",
    limit: int = CUSTOMER_PANEL_LIMIT,
    basis: str = CUSTOMER_PANEL_BASIS,
) -> str:
    body = [
        _cust_row(
            "TOTAL",
            totals.get("vol"),
            totals.get("rev"),
            totals.get("prof"),
            totals.get("margin_pct"),
            bold=True,
        )
    ] if totals else []
    for r in rows:
        body.append(
            _cust_row(
                r.get("customer_name") or "(unknown)",
                r.get("vol"),
                r.get("rev"),
                r.get("prof"),
                r.get("margin_pct"),
            )
        )
    if not body:
        body.append(
            f'<tr><td colspan="5" style="font-family:{FONT_STACK};padding:12px;'
            f'font-size:11px;color:{GREY};text-align:center;">No customer activity</td></tr>'
        )
    inner = (
        _card_title("Customer Actual Performance (TM)")
        + f'<table cellpadding="0" cellspacing="0" border="0" width="100%" '
          f'style="border-collapse:collapse;font-family:{FONT_STACK};margin-top:8px;">'
        + f"<thead><tr>{_cust_head()}</tr></thead><tbody>"
        + "".join(body)
        + "</tbody></table>"
        + f'<div style="font-family:{FONT_STACK};font-size:10px;color:{GREY};'
          f'margin-top:6px;">{len(rows)} customer(s) with MTD activity '
          f'&middot; top {limit} by {escape(basis)} &middot; TOTAL is the full '
          f'{total_scope}, not the listed rows</div>'
    )
    return _card_shell(inner)


# ---------------------------------------------------------------------------
# QuickChart — static configs only (no function-valued options)
# ---------------------------------------------------------------------------


def _chart_url(config: dict, *, width: int = 820, height: int = 300) -> str:
    payload = json.dumps(config, separators=(",", ":"))
    return (
        f"{QUICKCHART}?v=4&bkg=%23ffffff&devicePixelRatio=2"
        f"&w={width}&h={height}&c={quote(payload, safe='')}"
    )


def _dual_axis_config(
    labels: list[str],
    bar_label: str,
    bar_data: list,
    line_label: str,
    line_data: list,
    *,
    bar_axis_title: str,
    line_axis_title: str,
    palette: dict,
) -> dict:
    """Unfilled outlined bars + a line, both with data labels ON.

    ``palette`` is one of the CHART_* dicts above — the colours are per-chart,
    everything else on this config is shared.

    Everything static: ``datalabels`` gets no ``formatter``/``display``
    callback (a function option would be JSON-escaped and silently dropped),
    so the numbers are pre-rounded by the caller.
    """
    return {
        "type": "bar",
        "data": {
            "labels": labels,
            "datasets": [
                {
                    "type": "bar",
                    "label": bar_label,
                    "data": bar_data,
                    # Unfilled: the outline IS the bar. See the palette note —
                    # borderWidth and borderSkipped are both load-bearing.
                    "backgroundColor": "transparent",
                    "borderColor": palette["bar_border"],
                    "borderWidth": BAR_BORDER_WIDTH,
                    "borderSkipped": False,
                    "yAxisID": "y",
                    "order": 2,
                    "datalabels": {
                        "anchor": "end", "align": "end", "offset": 2,
                        "color": palette["bar_label"],
                        "font": {"size": 9, "weight": "bold"},
                    },
                },
                {
                    "type": "line",
                    "label": line_label,
                    "data": line_data,
                    "borderColor": palette["line"],
                    "backgroundColor": palette["line"],
                    "borderWidth": 2,
                    "pointRadius": 3,
                    "fill": False,
                    "tension": 0.25,
                    "yAxisID": "y1",
                    "order": 1,
                    # White chip behind the label: the line crosses the bars
                    # and the y gridlines, so a bare label sits on whatever
                    # happens to be underneath it. Unfilling the bars reduced
                    # that collision but did not remove it — the chip stays,
                    # and its text uses the palette's dark companion, never the
                    # line colour (verified on the rendered PNG — always look
                    # at the image).
                    "datalabels": {
                        "anchor": "end", "align": "top", "offset": 4,
                        "color": palette["line_label"],
                        "backgroundColor": "#FFFFFF",
                        "borderColor": palette["line_chip_border"],
                        "borderWidth": 1,
                        "borderRadius": 3,
                        "padding": {"top": 1, "bottom": 1, "left": 3, "right": 3},
                        "font": {"size": 9, "weight": "bold"},
                    },
                },
            ],
        },
        "options": {
            "layout": {"padding": {"top": 22, "right": 8, "left": 4}},
            "plugins": {
                "legend": {
                    "position": "top",
                    "labels": {"boxWidth": 12, "font": {"size": 11}},
                },
                "datalabels": {"display": True},
            },
            "scales": {
                "x": {"ticks": {"font": {"size": 10}}, "grid": {"display": False}},
                # ``grace`` adds headroom ABOVE the largest value on each axis.
                # The legend is drawn inside the canvas (position:"top"), so a
                # series that peaks at the axis maximum puts its data-label chip
                # straight through the legend text — seen on TEAM4, where "39.7"
                # overprinted "Margin %". layout.padding cannot fix this: it pads
                # above the legend, not between the legend and the plot. Pushing
                # the peak down is the same fix the HD SPOT chart uses.
                "y": {
                    "position": "left", "beginAtZero": True, "grace": "12%",
                    "title": {"display": True, "text": bar_axis_title,
                              "font": {"size": 10}},
                    "ticks": {"font": {"size": 10}},
                },
                "y1": {
                    "position": "right", "beginAtZero": True, "grace": "12%",
                    "title": {"display": True, "text": line_axis_title,
                              "font": {"size": 10}},
                    "ticks": {"font": {"size": 10}},
                    "grid": {"drawOnChartArea": False},
                },
            },
        },
    }


def build_chart_urls(series: list[dict]) -> dict[str, str]:
    labels = [d["day"].strftime("%m/%d") for d in series]
    loads = [d["loads"] for d in series]
    profit = [round(d["profit"]) for d in series]
    customers = [d["customers"] for d in series]
    margin = [None if d["margin_pct"] is None else round(d["margin_pct"], 1)
              for d in series]
    return {
        "loads_profit": _chart_url(_dual_axis_config(
            labels, "Loads", loads, "Profit ($)", profit,
            bar_axis_title="Loads", line_axis_title="Profit ($)",
            palette=CHART_LOADS_PROFIT,
        )),
        "customers_margin": _chart_url(_dual_axis_config(
            labels, "Customers", customers, "Margin %", margin,
            bar_axis_title="Customers", line_axis_title="Margin %",
            palette=CHART_CUSTOMERS_MARGIN,
        )),
    }


def _chart_block(title: str, url: str) -> str:
    return (
        f'<table cellpadding="0" cellspacing="0" border="0" width="100%" '
        f'style="background:#FFFFFF;border:1px solid {BORDER};border-radius:8px;'
        f'border-collapse:separate;font-family:{FONT_STACK};margin-top:12px;">'
        f'<tr><td style="font-family:{FONT_STACK};padding:12px 14px;">'
        + _card_title(title)
        + f'<div style="font-family:{FONT_STACK};margin-top:8px;">'
          f'<img src="{escape(url, quote=True)}" width="820" alt="{escape(title)}" '
          f'style="display:block;width:100%;max-width:820px;height:auto;border:0;" /></div>'
        f"</td></tr></table>"
    )


# ---------------------------------------------------------------------------
# Page
# ---------------------------------------------------------------------------


def _sent_stamp(now) -> str:
    """``Thursday, July 09, 2026 · 5:30 PM CST`` (literal CST, per the spec)."""
    hour12 = now.hour % 12 or 12
    ampm = "AM" if now.hour < 12 else "PM"
    return f"{now.strftime('%A, %B %d, %Y')} &middot; {hour12}:{now.minute:02d} {ampm} CST"


def render_html(
    *,
    scope_title: str,
    scope_footer: str,
    scope_is_multi_team: bool,
    now,
    card1: dict,
    card2: dict,
    card3: dict,
    card4: dict,
    card5: dict,
    customer_rows: list[dict],
    customer_totals: dict,
    customer_limit: int = CUSTOMER_PANEL_LIMIT,
    customer_basis: str = CUSTOMER_PANEL_BASIS,
    series: list[dict],
) -> tuple[str, dict[str, str]]:
    charts = build_chart_urls(series)

    left = (
        _card_profit(card1)
        + '<div style="height:12px;line-height:12px;">&nbsp;</div>'
        + _card_budget(card2)
        + '<div style="height:12px;line-height:12px;">&nbsp;</div>'
        + f'<table cellpadding="0" cellspacing="0" border="0" width="100%" '
          f'style="border-collapse:collapse;font-family:{FONT_STACK};"><tr>'
        + f'<td width="49%" valign="top" style="font-family:{FONT_STACK};">'
        + _card_rate(card3)
        + f'</td><td width="2%" style="font-family:{FONT_STACK};">&nbsp;</td>'
        + f'<td width="49%" valign="top" style="font-family:{FONT_STACK};">'
        + _card_rate(card4)
        + "</td></tr></table>"
        + '<div style="height:12px;line-height:12px;">&nbsp;</div>'
        + _card_projection(card5)
    )
    right = _customer_panel(
        customer_rows,
        customer_totals,
        total_scope="CORP scope" if scope_is_multi_team else "team",
        limit=customer_limit,
        basis=customer_basis,
    )

    return (
        f"""\
<!DOCTYPE html><html><body style="margin:0;padding:0;background:{GREY_BG};">
  <table cellpadding="0" cellspacing="0" border="0" width="100%" style="background:{GREY_BG};font-family:{FONT_STACK};">
    <tr><td align="center" style="padding:20px;font-family:{FONT_STACK};">
      <table cellpadding="0" cellspacing="0" border="0" width="880" style="width:880px;max-width:100%;font-family:{FONT_STACK};">
        <tr><td style="background:{NAVY};padding:18px 22px;border-radius:8px 8px 0 0;font-family:{FONT_STACK};">
          <div style="font-family:{FONT_STACK};font-size:19px;font-weight:800;color:#FFFFFF;">{escape(scope_title)}</div>
          <div style="font-family:{FONT_STACK};font-size:11px;color:#BFDBFE;margin-top:3px;">{_sent_stamp(now)}</div>
        </td></tr>
        <tr><td style="background:#FFFFFF;padding:16px;border:1px solid {BORDER};border-top:0;border-radius:0 0 8px 8px;font-family:{FONT_STACK};">
          <table cellpadding="0" cellspacing="0" border="0" width="100%" style="border-collapse:collapse;font-family:{FONT_STACK};">
            <tr>
              <td width="55%" valign="top" style="font-family:{FONT_STACK};padding-right:8px;">{left}</td>
              <td width="45%" valign="top" style="font-family:{FONT_STACK};padding-left:8px;">{right}</td>
            </tr>
          </table>
          {_chart_block("Loads & Profit — last 14 days", charts["loads_profit"])}
          {_chart_block("Customers & Margin % — last 14 days", charts["customers_margin"])}
          <div style="font-family:{FONT_STACK};font-size:10px;color:{GREY};margin-top:14px;text-align:center;">
            Source: <code style="font-family:{MONO_STACK};color:{INK};">ops-portal-overview</code>
            &middot; scope {escape(scope_footer)} &middot; rates are recomputed from their components; deltas marked
            <strong style="font-family:{FONT_STACK};">pp</strong> are percentage points &middot; {DASH} = no baseline
          </div>
        </td></tr>
      </table>
    </td></tr>
  </table>
</body></html>""",
        charts,
    )
