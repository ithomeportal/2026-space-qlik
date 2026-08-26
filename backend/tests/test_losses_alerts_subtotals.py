"""Losses Lanes "Top Losses — Weekly Movers" — the per-bucket subtotal row.

Request 2026-08-26 (`Pictures/n8n Losses Lanes report.txt`, and the CFO's reply
on the 26th): *"Can we add subtotals to this report in each bucket?"*

Adding a subtotal to this particular table is not the arithmetic exercise it
looks like, because **the two money columns are sparse and each bucket is sparse
in a different one**:

* *New entries*  — in the top-10 this week only, so ``last_profit`` is ``None``
  on every row and the "Last week" column is entirely em dashes.
* *Dropped out*  — in the top-10 last week only, so ``this_profit`` is ``None``.
* *Rank change*  — in both, so both columns are populated.

A subtotal that quietly summed the populated cells would sit directly beneath a
header reading "(7)" and, in the moved bucket on a mixed week, total fewer than
seven of them. Every reader would take it as a total over seven. So a column
states the count it covers whenever that differs from the bucket size, and a
column with nothing to add prints an em dash instead of a confident ``$0``.

That "$0 vs em dash" distinction is the one an optimisation would erase later,
which is why it is pinned here rather than left to a glance at the rendered
e-mail. This module was also the first test of any kind on this e-mail.
"""

from __future__ import annotations

import re

from app.services.losses_alerts import _section, render_html


def _cells(row_html: str) -> list[str]:
    """Visible text of each <td> in a row, tags and entities stripped."""
    return [
        re.sub(r"\s+", " ", re.sub(r"<[^>]*>", " ", td)).strip()
        for td in re.findall(r"<td[^>]*>(.*?)</td>", row_html, re.S)
    ]


def _rows(html: str) -> list[str]:
    """Body rows only.

    ⚠ Scoped to <tbody> deliberately: the section's <thead> is also a <tr>, so an
    unscoped search returns the column headings as row 0 — a row with no <td> at
    all, which fails every assertion below for the wrong reason.
    """
    body = re.search(r"<tbody>(.*?)</tbody>", html, re.S)
    assert body, "section rendered no <tbody>"
    return re.findall(r"<tr[^>]*>.*?</tr>", body.group(1), re.S)


def _subtotal_row(html: str) -> str:
    rows = _rows(html)
    assert rows, "section rendered no rows at all"
    return rows[0]


NEW = [
    {"customer": "CENTRATX", "lane": "WACO,TX,CHIHUAHUA,CI", "this_rank": 3, "last_rank": None,
     "this_profit": -575.0, "last_profit": None},
    {"customer": "HOMEDEGA", "lane": "GREENSBURG,IN,PITTSTON TOWNSHIP,PA", "this_rank": 4, "last_rank": None,
     "this_profit": -546.0, "last_profit": None},
    {"customer": "RUANTRIA", "lane": "GOLDSBORO,NC,LAKELAND,FL", "this_rank": 5, "last_rank": None,
     "this_profit": -331.0, "last_profit": None},
]

DROPPED = [
    {"customer": "RYDERMI", "lane": "MARION,IN,O FALLON,MO", "this_rank": None, "last_rank": 1,
     "this_profit": None, "last_profit": -3021.0},
    {"customer": "RYDERMI", "lane": "EL PASO,TX,WENTZVILLE,MO", "this_rank": None, "last_rank": 2,
     "this_profit": None, "last_profit": -2140.0},
]

MOVED = [
    {"customer": "RYDERMI", "lane": "COLOMA,MI,ARLINGTON,TX", "this_rank": 1, "last_rank": 3,
     "this_profit": -1458.0, "last_profit": -1896.0},
    {"customer": "RYDERMI", "lane": "BLYTHEWOOD,SC,FLINT,MI", "this_rank": 2, "last_rank": 5,
     "this_profit": -594.0, "last_profit": -1773.0},
]


# ---------------------------------------------------------------------------
# Placement
# ---------------------------------------------------------------------------
def test_subtotal_is_the_first_row_of_the_bucket() -> None:
    """"In the top of each section/bucket" — above the detail, not below it."""
    html = _section("Rank change (still in top)", MOVED, "moved", "neutral")
    assert "Subtotal" in _cells(_subtotal_row(html))[0]


def test_every_bucket_gets_one() -> None:
    for title, entries, kind, tone in (
        ("New entries", NEW, "new", "red"),
        ("Dropped out", DROPPED, "dropped", "green"),
        ("Rank change", MOVED, "moved", "neutral"),
    ):
        html = _section(title, entries, kind, tone)
        assert html.count("Subtotal") == 1, f"{title} has {html.count('Subtotal')} subtotal rows"


def test_empty_bucket_gets_no_subtotal() -> None:
    """A subtotal of nothing is noise; the empty-state row already says it."""
    html = _section("Rank change", [], "moved", "neutral")
    assert "Subtotal" not in html
    assert "No changes in this category" in html


# ---------------------------------------------------------------------------
# Arithmetic
# ---------------------------------------------------------------------------
def test_moved_bucket_totals_both_columns() -> None:
    cells = _cells(_subtotal_row(_section("Rank change", MOVED, "moved", "neutral")))
    # -1458 + -594 = -2052 ; -1896 + -1773 = -3669
    assert "-$2,052" in cells[2]
    assert "-$3,669" in cells[3]


def test_new_entries_totals_this_week_and_dashes_last_week() -> None:
    """⚠ The empty column must be an em dash, NEVER $0.

    Every row in this bucket is new, so there is no last-week figure to add.
    ``$0`` would assert these lanes lost nothing last week; the truth is that
    they were not in the top-10 at all. Those are different claims.
    """
    cells = _cells(_subtotal_row(_section("New entries", NEW, "new", "red")))
    assert "-$1,452" in cells[2]        # 575 + 546 + 331
    assert cells[3] == "—", cells[3]
    assert "$0" not in cells[3]


def test_dropped_bucket_dashes_this_week_and_totals_last_week() -> None:
    cells = _cells(_subtotal_row(_section("Dropped out", DROPPED, "dropped", "green")))
    assert cells[2] == "—", cells[2]
    assert "-$5,161" in cells[3]        # 3021 + 2140


# ---------------------------------------------------------------------------
# Honesty about coverage — the reason this file is long
# ---------------------------------------------------------------------------
def test_partial_column_states_how_many_rows_it_covers() -> None:
    """A mixed bucket must not total 2 of 3 rows under a header saying "(3)"."""
    mixed = MOVED + [
        {"customer": "ACME", "lane": "A,TX,B,TX", "this_rank": 9, "last_rank": 4,
         "this_profit": None, "last_profit": -100.0},
    ]
    html = _section("Rank change", mixed, "moved", "neutral")
    cells = _cells(_subtotal_row(html))
    assert "(3)" in html                      # the bucket header count
    assert "2 of 3" in cells[2], cells[2]     # this-week column covers 2 of them
    assert "3 of 3" not in cells[3]           # full column stays unqualified
    assert "-$3,769" in cells[3]              # 1896 + 1773 + 100


def test_full_column_is_not_cluttered_with_a_qualifier() -> None:
    cells = _cells(_subtotal_row(_section("Rank change", MOVED, "moved", "neutral")))
    assert "of 2" not in cells[2]
    assert "of 2" not in cells[3]


def test_pair_count_is_singular_for_one_row() -> None:
    cells = _cells(_subtotal_row(_section("New entries", NEW[:1], "new", "red")))
    assert "1 customer / lane pair" in cells[0]
    assert "pairs" not in cells[0]


# ---------------------------------------------------------------------------
# The subtotal must agree with the rows printed beneath it
# ---------------------------------------------------------------------------
def test_subtotal_equals_the_sum_of_the_rendered_detail_rows() -> None:
    """Recomputed from the rendered HTML, not from the input list.

    Summing the same list twice proves only that ``sum`` works. This reads the
    money back out of the detail rows the reader actually sees, so a formatting
    or filtering change between the two would surface here.
    """
    html = _section("Rank change", MOVED, "moved", "neutral")
    rows = _rows(html)
    subtotal, detail = rows[0], rows[1:]

    def money(text: str) -> float:
        if text.strip() in {"—", ""}:
            return 0.0
        return float(text.replace("$", "").replace(",", ""))

    for col in (2, 3):
        printed = money(_cells(subtotal)[col].split(" ")[0])
        summed = sum(money(_cells(r)[col]) for r in detail)
        assert abs(printed - summed) < 0.5, f"column {col}: {printed} vs {summed}"


def test_full_email_renders_with_subtotals_in_all_three_buckets() -> None:
    html = render_html(
        {
            "new_entries": NEW,
            "dropped": DROPPED,
            "moved": MOVED,
            "window": {
                "this_week": {"start": "2026-08-24", "end": "2026-08-30"},
                "last_week": {"start": "2026-08-17", "end": "2026-08-23"},
                "top_n": 10,
            },
        },
        "https://example.invalid/losses",
    )
    assert html.count("Subtotal") == 3
    # Nothing that already worked may have moved.
    assert "Top Losses" in html
    assert "New entries" in html and "Dropped out" in html and "Rank change" in html
