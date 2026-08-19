"""DFW - Access Log Doors delays digest (HTML).

Rendering only: every value handed in is already computed and guarded by
``app/services/access_doors_delays_digest.py``. ``None`` always renders as an
em dash, never ``0`` — "no late days to average" and "late by zero minutes"
are different facts.

Outlook 365 desktop resets ``font-family`` at every nested ``<table>``
boundary, so FONT_STACK is declared inline on EVERY td / th / div / span
(SPEC-CODE-RULES §21). The palette and the stamp format are IMPORTED from
``team_perf_digest_html`` rather than re-declared, so the two pulled digests
stay visibly the same product.

Layout constraints (learned the hard way, see MEMORY "Email table columns are
expensive"): Outlook desktop uses the Word engine and ignores
``overflow-x:auto`` — a table wider than the ~956px content box CLIPS its
rightmost columns instead of scrolling. The page table is 880px and the data
table has SEVEN columns; the last-occurrence date rides as a sub-line under the
employee name rather than becoming an eighth. No flexbox, no ``rgb()``, no
webfont link.
"""
from __future__ import annotations

from datetime import date, datetime
from html import escape
from typing import Any, Optional

from app.services.team_perf_digest_html import (
    BORDER,
    DASH,
    FONT_STACK,
    GREEN_BG,
    GREEN_TX,
    GREY,
    GREY_BG,
    INK,
    MONO_STACK,
    NAVY,
    RED,
    RED_BG,
    RED_TX,
    _sent_stamp,
)

# Amber: the "over the threshold but not the worst" band in the count column.
AMBER_BG = "#FEF3C7"
AMBER_TX = "#92400E"

# Column layout. Width in px; the sum (820) plus cell padding sits inside the
# 880px page table, which itself is inside the ~956px Outlook content box.
_COLS: tuple[tuple[str, str, int], ...] = (
    ("Employee", "left", 200),
    ("Job title", "left", 170),
    ("Out of Time days", "right", 90),
    ("Days badged in", "right", 85),
    ("Out of Time rate", "right", 90),
    ("Worst late", "right", 90),
    ("Avg late", "right", 95),
)

PAGE_WIDTH = 880


# ---------------------------------------------------------------------------
# Formatting — None is always an em dash, never 0
# ---------------------------------------------------------------------------


def _num(value: Any) -> Optional[float]:
    if value is None:
        return None
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    if out != out or out in (float("inf"), float("-inf")):
        return None
    return out


def _fmt_count(value: Any) -> str:
    n = _num(value)
    return DASH if n is None else f"{int(round(n)):,}"


def _fmt_pct(value: Any) -> str:
    n = _num(value)
    return DASH if n is None else f"{n:,.1f}%"


def _fmt_minutes(value: Any) -> str:
    """Minutes late, already positive. ``90`` -> ``1h 30m``; ``7`` -> ``7 min``."""
    n = _num(value)
    if n is None:
        return DASH
    total = int(round(n))
    if total < 60:
        return f"{total} min"
    return f"{total // 60}h {total % 60:02d}m"


def _fmt_date(value: Any) -> str:
    """``2026-08-18`` -> ``Aug 18``. Accepts a date or the ISO string json_agg
    emits — the offender rows come back through ``json_agg``, the scalars do
    not, and both land here."""
    if value is None:
        return DASH
    if isinstance(value, str):
        try:
            value = date.fromisoformat(value[:10])
        except ValueError:
            return escape(value)
    if isinstance(value, (datetime, date)):
        return value.strftime("%b %d")
    return escape(str(value))


def _fmt_ts(value: Any) -> str:
    """``Aug 19, 2026 · 7:12 AM CST``. The datalake stores CST already, so the
    instant is printed as-is with a literal CST suffix — never converted."""
    if value is None:
        return DASH
    if isinstance(value, str):
        try:
            value = datetime.fromisoformat(value)
        except ValueError:
            return escape(value)
    if not isinstance(value, datetime):
        return escape(str(value))
    hour12 = value.hour % 12 or 12
    ampm = "AM" if value.hour < 12 else "PM"
    return f"{value.strftime('%b %d, %Y')} &middot; {hour12}:{value.minute:02d} {ampm} CST"


def _fmt_window(start: date, end: date) -> str:
    return f"{start.strftime('%b %d, %Y')} &ndash; {end.strftime('%b %d, %Y')}"


# ---------------------------------------------------------------------------
# Pieces
# ---------------------------------------------------------------------------


def _panel(inner: str, *, border: str = BORDER, bg: str = "#FFFFFF") -> str:
    return (
        f'<table cellpadding="0" cellspacing="0" border="0" width="100%" '
        f'style="background:{bg};border:1px solid {border};border-radius:8px;'
        f'border-collapse:separate;font-family:{FONT_STACK};">'
        f'<tr><td style="font-family:{FONT_STACK};padding:14px 16px;">{inner}</td></tr>'
        f"</table>"
    )


def _panel_title(text: str, *, raw: bool = False) -> str:
    """``raw=True`` when the caller has already built safe HTML.

    Without the flag an ``&middot;`` in the caller's string comes out as the
    literal text ``&MIDDOT;`` in the rendered heading — escape() has no way to
    tell an entity apart from a user string that merely looks like one, so the
    decision has to be made at the call site.
    """
    body = text if raw else escape(text)
    return (
        f'<div style="font-family:{FONT_STACK};font-size:10px;font-weight:700;'
        f'color:{NAVY};text-transform:uppercase;letter-spacing:0.06em;">'
        f"{body}</div>"
    )


def _stat(label: str, value: str, *, color: str = INK) -> str:
    """One cell of the summary strip: big number over a small grey label."""
    return (
        f'<td valign="top" style="font-family:{FONT_STACK};padding:0 10px 0 0;">'
        f'<div style="font-family:{FONT_STACK};font-size:22px;font-weight:800;'
        f'color:{color};line-height:1.1;">{value}</div>'
        f'<div style="font-family:{FONT_STACK};font-size:10px;color:{GREY};'
        f'margin-top:3px;text-transform:uppercase;letter-spacing:0.04em;">'
        f"{escape(label)}</div></td>"
    )


def _summary_strip(people: list[dict], totals: dict, min_days: int, days: int) -> str:
    count = len(people)
    return _panel(
        _panel_title(
            f"Last {days} days &middot; more than {min_days - 1} Out of Time days",
            raw=True,
        )
        + f'<table cellpadding="0" cellspacing="0" border="0" width="100%" '
          f'style="border-collapse:collapse;font-family:{FONT_STACK};margin-top:10px;"><tr>'
        + _stat(
            "Employees over threshold",
            _fmt_count(count),
            color=RED if count else GREEN_TX,
        )
        + _stat("People badging in", _fmt_count(totals.get("people_in_scope")))
        + _stat("Out of Time days (all)", _fmt_count(totals.get("out_of_time_shifts")))
        + _stat("On Time days (all)", _fmt_count(totals.get("on_time_shifts")))
        + _stat("Out of Time rate", _fmt_pct(totals.get("out_of_time_pct")))
        + "</tr></table>"
    )


def _head_row() -> str:
    return "".join(
        f'<th width="{width}" style="font-family:{FONT_STACK};padding:7px 8px;'
        f'text-align:{align};font-size:9px;color:{NAVY};text-transform:uppercase;'
        f'letter-spacing:0.04em;font-weight:700;border-bottom:2px solid {BORDER};">'
        f"{escape(label)}</th>"
        for label, align, width in _COLS
    )


def _count_chip(days_late: int, worst_in_table: int) -> str:
    """Red for the worst offender band, amber for the rest. Both chips carry
    dark text on a light fill — a dark fill with white text fails contrast for
    roughly half of any palette, so the fill stays light and is never guessed."""
    bg, tx = (RED_BG, RED_TX) if days_late >= max(worst_in_table, 1) else (AMBER_BG, AMBER_TX)
    return (
        f'<span style="font-family:{FONT_STACK};display:inline-block;background:{bg};'
        f'color:{tx};font-size:12px;font-weight:800;padding:2px 9px;border-radius:10px;'
        f'white-space:nowrap;">{days_late}</span>'
    )


def _body_row(person: dict, worst_in_table: int) -> str:
    name = escape(str(person.get("full_name") or "(unknown)"))
    last = person.get("last_out_of_time_date")
    sub = (
        f'<div style="font-family:{FONT_STACK};font-size:10px;color:{GREY};'
        f'margin-top:2px;">Most recent: {_fmt_date(last)}</div>'
        if last else ""
    )
    cell = (
        f'font-family:{FONT_STACK};padding:7px 8px;font-size:11px;'
        f'border-bottom:1px solid {GREY_BG};font-variant-numeric:tabular-nums;'
    )
    return (
        "<tr>"
        f'<td style="{cell}color:{INK};font-weight:700;">{name}{sub}</td>'
        f'<td style="{cell}color:{GREY};">'
        f'{escape(str(person.get("job_title") or "—"))}</td>'
        f'<td style="{cell}text-align:right;">'
        f'{_count_chip(int(person.get("out_of_time_days") or 0), worst_in_table)}</td>'
        f'<td style="{cell}text-align:right;color:{INK};">'
        f'{_fmt_count(person.get("badged_days"))}</td>'
        f'<td style="{cell}text-align:right;color:{INK};">'
        f'{_fmt_pct(person.get("out_of_time_pct"))}</td>'
        f'<td style="{cell}text-align:right;color:{RED};font-weight:600;">'
        f'{_fmt_minutes(person.get("worst_minutes_late"))}</td>'
        f'<td style="{cell}text-align:right;color:{INK};">'
        f'{_fmt_minutes(person.get("avg_minutes_late"))}</td>'
        "</tr>"
    )


def _all_clear(min_days: int, days: int, scope_label: str, totals: dict) -> str:
    """The empty case is a SENTENCE, never an empty table.

    An n8n workflow mails this unconditionally, so a clean fortnight and a
    broken query must not look alike. The scope counters below the headline are
    what tells them apart: an all-clear with 0 people badging in is not good
    news, it is a dead feed."""
    return _panel(
        f'<div style="font-family:{FONT_STACK};font-size:16px;font-weight:800;'
        f'color:{GREEN_TX};">All clear</div>'
        f'<div style="font-family:{FONT_STACK};font-size:12px;color:{INK};'
        f'margin-top:6px;line-height:1.5;">'
        f"Nobody in {escape(scope_label)} recorded more than {min_days - 1} "
        f"Out of Time days in the last {days} days."
        "</div>"
        f'<div style="font-family:{FONT_STACK};font-size:11px;color:{GREY};'
        f'margin-top:8px;">'
        f'{_fmt_count(totals.get("people_in_scope"))} employee(s) badged in over '
        f'{_fmt_count(totals.get("shifts_in_scope"))} shift(s) in the window '
        f'&middot; {_fmt_count(totals.get("out_of_time_shifts"))} Out of Time day(s) '
        f"in total, none of them concentrated on one person above the threshold."
        "</div>",
        border=GREEN_TX,
        bg=GREEN_BG,
    )


def _table_panel(people: list[dict], truncated: int, min_days: int) -> str:
    worst = max((int(p.get("out_of_time_days") or 0) for p in people), default=0)
    note = ""
    if truncated:
        note = (
            f'<div style="font-family:{FONT_STACK};font-size:10px;color:{RED};'
            f'margin-top:6px;font-weight:700;">Showing the top {len(people)} '
            f"&mdash; {truncated} further employee(s) also exceeded the "
            f"threshold and are listed in the API payload.</div>"
        )
    return _panel(
        _panel_title(
            f"Employees with {min_days} or more Out of Time days"
        )
        + f'<table cellpadding="0" cellspacing="0" border="0" width="100%" '
          f'style="border-collapse:collapse;font-family:{FONT_STACK};margin-top:10px;">'
        + f"<thead><tr>{_head_row()}</tr></thead><tbody>"
        + "".join(_body_row(p, worst) for p in people)
        + "</tbody></table>"
        + note
    )


def _freshness(scope_as_of: Any, feed_as_of: Any, start: date, end: date) -> str:
    """The mandatory stale-data signal.

    TWO stamps, because they fail differently: `scope_as_of` stops advancing
    when DFW stops being scored, `feed_as_of` stops advancing when the ZKTeco
    extraction itself dies. One number cannot tell those apart."""
    return (
        f'<div style="font-family:{FONT_STACK};font-size:11px;color:{INK};'
        f'background:{GREY_BG};border:1px solid {BORDER};border-radius:6px;'
        f'padding:8px 12px;margin-top:12px;">'
        f'<strong style="font-family:{FONT_STACK};">Data as of '
        f"{_fmt_ts(scope_as_of)}</strong>"
        f'<span style="font-family:{FONT_STACK};color:{GREY};"> &mdash; latest '
        f"badge-in scored in this scope. Latest badge event of any kind in the "
        f"window: {_fmt_ts(feed_as_of)}. Window {_fmt_window(start, end)} "
        f"(CST, inclusive).</span></div>"
    )


def _footer(definition: str, scope_label: str, min_days: int, days: int) -> str:
    return (
        f'<div style="font-family:{FONT_STACK};font-size:10px;color:{GREY};'
        f'margin-top:14px;line-height:1.6;">'
        f'<strong style="font-family:{FONT_STACK};color:{INK};">'
        f"What &ldquo;Out of Time&rdquo; means: </strong>{escape(definition)}"
        "<br />"
        f'<strong style="font-family:{FONT_STACK};color:{INK};">Who is listed: '
        f"</strong>everyone in "
        f'<code style="font-family:{MONO_STACK};color:{INK};">{escape(scope_label)}</code>'
        f" with {min_days} or more Out of Time days in the last {days} calendar "
        f"days (rolling, ending today). &ldquo;Days badged in&rdquo; counts shifts "
        f"with a recorded arrival; the rate is over scored days only. "
        f"&ldquo;Worst&rdquo; and &ldquo;Avg late&rdquo; are measured across that "
        f"person&rsquo;s Out of Time days only. {DASH} = not applicable."
        "<br />"
        f'Source: <code style="font-family:{MONO_STACK};color:{INK};">'
        f"dfw-access-doors</code> &middot; same scoring and same scope as the "
        f"on-screen report &mdash; open it to see the underlying punches."
        "</div>"
    )


# ---------------------------------------------------------------------------
# Page
# ---------------------------------------------------------------------------


def render_html(
    *,
    scope_label: str,
    now,
    start: date,
    end: date,
    days: int,
    min_days: int,
    people: list[dict],
    totals: dict,
    truncated: int,
    scope_as_of: Any,
    feed_as_of: Any,
    definition: str,
) -> str:
    """Full e-mail body. Always returns a complete, sendable document."""
    body = (
        _table_panel(people, truncated, min_days)
        if people
        else _all_clear(min_days, days, scope_label, totals)
    )
    title = "DFW Access Doors &mdash; repeat Out of Time"

    return f"""\
<!DOCTYPE html><html><body style="margin:0;padding:0;background:{GREY_BG};">
  <table cellpadding="0" cellspacing="0" border="0" width="100%" style="background:{GREY_BG};font-family:{FONT_STACK};">
    <tr><td align="center" style="padding:20px;font-family:{FONT_STACK};">
      <table cellpadding="0" cellspacing="0" border="0" width="{PAGE_WIDTH}" style="width:{PAGE_WIDTH}px;max-width:100%;font-family:{FONT_STACK};">
        <tr><td style="background:{NAVY};padding:18px 22px;border-radius:8px 8px 0 0;font-family:{FONT_STACK};">
          <div style="font-family:{FONT_STACK};font-size:19px;font-weight:800;color:#FFFFFF;">{title}</div>
          <div style="font-family:{FONT_STACK};font-size:11px;color:#BFDBFE;margin-top:3px;">{_sent_stamp(now)} &middot; {escape(scope_label)}</div>
        </td></tr>
        <tr><td style="background:#FFFFFF;padding:16px;border:1px solid {BORDER};border-top:0;border-radius:0 0 8px 8px;font-family:{FONT_STACK};">
          {_summary_strip(people, totals, min_days, days)}
          <div style="height:12px;line-height:12px;">&nbsp;</div>
          {body}
          {_freshness(scope_as_of, feed_as_of, start, end)}
          {_footer(definition, scope_label, min_days, days)}
        </td></tr>
      </table>
    </td></tr>
  </table>
</body></html>"""
