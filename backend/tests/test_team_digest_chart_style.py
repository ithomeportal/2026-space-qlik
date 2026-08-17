"""The two trend charts on the "Performance" e-mails — style, pinned.

Request 2026-08-17 (`Pictures/n8n -- Email Performance CORP.pdf`): the bars on
both charts become UNFILLED outlines and both lines get new colours.

Three things make this worth a test rather than a look at the PNG:

1. **QuickChart fails silently.** A bad config returns HTTP 200 and an image
   that is simply missing whatever went wrong. There is no error to catch, so
   the config is checked here, before it is ever URL-encoded.

2. **"Unfilled" is three properties, not one.** Chart.js defaults bar
   ``borderWidth`` to 0, so a transparent bar with no explicit width renders as
   *nothing at all*; and ``borderSkipped`` defaults to ``"start"``, which leaves
   the bottom edge of the outline open. Both are asserted.

3. **Two of the three requested colours are unreadable as label text on white**
   — #ECC910 is 1.49:1 and #21BF6A is 2.41:1 against WCAG AA's 4.5:1. The bars
   and lines use the requested RGB values exactly; the data-label numbers use a
   darkened companion. That distinction is invisible in review and easy to
   "simplify" away later, so every label colour is re-measured below.

These tests decode the real QuickChart URL back into the config that was sent,
so they prove what the e-mail actually carries, not what a helper returned.
"""

from __future__ import annotations

import json
from datetime import date
from urllib.parse import parse_qs, urlparse

import pytest

from app.services.team_perf_digest_html import (
    BAR_BORDER_WIDTH,
    CHART_CUSTOMERS_MARGIN,
    CHART_LOADS_PROFIT,
    build_chart_urls,
)

# --- the request, restated as data ----------------------------------------
LOADS_BAR_OUTLINE = "#DC2626"      # rgb(220, 38, 38)  red
PROFIT_LINE = "#ECC910"            # rgb(236, 201, 16)
CUSTOMERS_BAR_OUTLINE = "#21BF6A"  # rgb(33, 191, 106)
MARGIN_LINE = "#14718A"            # rgb(20, 113, 138)

WHITE = "#FFFFFF"
WCAG_AA = 4.5


SERIES = [
    {
        "day": date(2026, 8, 3 + i),
        "loads": 40 + i,
        "profit": 15000 + 500 * i,
        "customers": 11 + i,
        "margin_pct": 13.5 + i / 2,
    }
    for i in range(14)
]


def _configs() -> dict[str, dict]:
    """Decode both chart URLs back into the configs QuickChart receives."""
    out = {}
    for key, url in build_chart_urls(SERIES).items():
        params = parse_qs(urlparse(url).query)
        out[key] = json.loads(params["c"][0])
    return out


def _datasets(config: dict) -> tuple[dict, dict]:
    """(bar dataset, line dataset) — order in the config is not relied on."""
    sets = config["data"]["datasets"]
    bar = next(d for d in sets if d["type"] == "bar")
    line = next(d for d in sets if d["type"] == "line")
    return bar, line


# --- WCAG ------------------------------------------------------------------


def _luminance(hex_color: str) -> float:
    raw = hex_color.lstrip("#")
    channels = [int(raw[i:i + 2], 16) / 255 for i in (0, 2, 4)]
    linear = [c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4
              for c in channels]
    r, g, b = linear
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def _contrast(fg: str, bg: str) -> float:
    a, b = _luminance(fg), _luminance(bg)
    lighter, darker = max(a, b), min(a, b)
    return (lighter + 0.05) / (darker + 0.05)


def test_contrast_helper_agrees_with_known_pairs():
    """Guard the guard: a broken ratio helper would pass every other test."""
    assert _contrast("#000000", WHITE) == pytest.approx(21.0, abs=0.01)
    assert _contrast(WHITE, WHITE) == pytest.approx(1.0, abs=0.01)


# --- Request 1: Loads & Profit ---------------------------------------------


def test_loads_bars_are_unfilled_with_a_red_outline():
    bar, _ = _datasets(_configs()["loads_profit"])

    assert bar["backgroundColor"] == "transparent"
    assert bar["borderColor"] == LOADS_BAR_OUTLINE
    # Chart.js defaults bar borderWidth to 0 — transparent + 0 = invisible.
    assert bar["borderWidth"] >= 1
    # Default "start" omits the base edge; False closes the outline.
    assert bar["borderSkipped"] is False


def test_profit_line_uses_the_requested_yellow():
    _, line = _datasets(_configs()["loads_profit"])
    assert line["borderColor"] == PROFIT_LINE
    assert line["backgroundColor"] == PROFIT_LINE


# --- Request 2: Customers & Margin % ---------------------------------------


def test_customers_bars_are_unfilled_with_a_green_outline():
    bar, _ = _datasets(_configs()["customers_margin"])

    assert bar["backgroundColor"] == "transparent"
    assert bar["borderColor"] == CUSTOMERS_BAR_OUTLINE
    assert bar["borderWidth"] >= 1
    assert bar["borderSkipped"] is False


def test_margin_line_uses_the_requested_teal():
    _, line = _datasets(_configs()["customers_margin"])
    assert line["borderColor"] == MARGIN_LINE
    assert line["backgroundColor"] == MARGIN_LINE


# --- The two charts are no longer the same picture -------------------------


def test_the_two_charts_no_longer_share_one_palette():
    """They were byte-identical in colour before this request. If a refactor
    re-merges the palettes, the second chart silently reverts to red+yellow."""
    loads_bar, loads_line = _datasets(_configs()["loads_profit"])
    cust_bar, cust_line = _datasets(_configs()["customers_margin"])

    assert loads_bar["borderColor"] != cust_bar["borderColor"]
    assert loads_line["borderColor"] != cust_line["borderColor"]


def test_no_dataset_still_carries_the_old_orange():
    """#F97316 was the line colour on BOTH charts before this request."""
    for config in _configs().values():
        assert "F97316" not in json.dumps(config).upper()


# --- The part that is easy to get wrong ------------------------------------


@pytest.mark.parametrize(
    "palette", [CHART_LOADS_PROFIT, CHART_CUSTOMERS_MARGIN],
    ids=["loads_profit", "customers_margin"],
)
def test_every_data_label_colour_is_readable_on_white(palette):
    """Bar labels sit above the bar on white; line labels sit on a white chip.

    #ECC910 (1.49:1) and #21BF6A (2.41:1) would both render numbers that are
    present in the PNG and unreadable in the e-mail.
    """
    for role in ("bar_label", "line_label"):
        ratio = _contrast(palette[role], WHITE)
        assert ratio >= WCAG_AA, (
            f"{role}={palette[role]} is {ratio:.2f}:1 on white, below "
            f"WCAG AA {WCAG_AA}:1 — use a darkened companion of the series "
            f"colour, not the series colour itself"
        )


def test_the_unreadable_series_colours_are_not_reused_as_label_text():
    """The specific regression: 'simplify' the palette by pointing the label at
    the series colour. Both of these are exactly the colours that fail."""
    assert _contrast(PROFIT_LINE, WHITE) < WCAG_AA          # 1.49:1
    assert _contrast(CUSTOMERS_BAR_OUTLINE, WHITE) < WCAG_AA  # 2.41:1

    assert CHART_LOADS_PROFIT["line_label"] != PROFIT_LINE
    assert CHART_CUSTOMERS_MARGIN["bar_label"] != CUSTOMERS_BAR_OUTLINE

    # ...and the one that genuinely is readable is used directly, so nobody
    # "fixes" it into a needless third colour.
    assert _contrast(MARGIN_LINE, WHITE) >= WCAG_AA           # 5.51:1
    assert CHART_CUSTOMERS_MARGIN["line_label"] == MARGIN_LINE


def test_line_label_chips_stay_opaque_white():
    """The chip is what makes the label readable where the line crosses a bar
    outline or a gridline. A transparent chip silently undoes the test above."""
    for config in _configs().values():
        _, line = _datasets(config)
        assert line["datalabels"]["backgroundColor"] == WHITE


# --- Unchanged by this request ---------------------------------------------


def test_configs_remain_fully_static():
    """No function-valued options: they survive json.dumps as strings and are
    dropped silently by QuickChart at HTTP 200 (the repo's oldest chart trap)."""
    for config in _configs().values():
        blob = json.dumps(config)
        assert "function" not in blob
        assert "=>" not in blob


def test_both_charts_still_plot_all_fourteen_days():
    for config in _configs().values():
        assert len(config["data"]["labels"]) == 14
        for dataset in config["data"]["datasets"]:
            assert len(dataset["data"]) == 14


def test_bar_border_width_constant_is_visible():
    assert BAR_BORDER_WIDTH >= 1
