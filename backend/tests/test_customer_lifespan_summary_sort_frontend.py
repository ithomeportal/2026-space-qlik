"""Customer Lifespan Summary: sortable headers + red negatives (Iris, deck 2026-11-05).

What these guards pin, none of which a build, lint or page load would catch:

1. **Every column of every Summary table sorts**, and its ``key`` is a REAL field of
   its row type. ``useSortable`` treats a missing field as "empty", so a typo gives a
   header that looks sortable and does nothing.
2. **The server's order is declared where it matches a column.** At Risk arrives by
   Profit descending and Declining by Change ascending; without a declared default the
   first click on those headers re-applies the order already on screen and looks dead.
3. **Sort labels stay readable.** ``SortableTh`` colours the active label dark navy, invisible
   on this dark blue header.
4. **``NO TEAM`` sorts with the blanks.** It renders as a dash, so ordered as text it
   would sit among the N's.
5. **Negatives are red by VALUE, in every place the deck marks**, including the
   drawer's facts, monthly table and chart tooltip.

No JS test runner exists in this repo; like the Favorites rail guards, these read the
TSX source. Sorting and colours in the real browser were checked with Playwright:
docs/SPEC-CUSTOMER-LIFESPAN.md section 12.
"""

from __future__ import annotations

import pathlib
import re

import pytest

FRONTEND = pathlib.Path(__file__).resolve().parents[2] / "frontend"
REPORT = FRONTEND / "app" / "reports" / "customer-lifespan"
SUMMARY = (REPORT / "SummaryPanel.tsx").read_text(encoding="utf-8")
DRAWER = (REPORT / "CustomerDrawer.tsx").read_text(encoding="utf-8")
UI = (REPORT / "ui.tsx").read_text(encoding="utf-8")
API = (FRONTEND / "lib" / "customer-lifespan-api.ts").read_text(encoding="utf-8")

EXPECTED_LABELS = {
    "AT_RISK_COLUMNS": ["Age", "Days since last load", "Profit last 90 days"],
    "DECLINING_COLUMNS": ["Avg. loads / mo", "Loads last 30 days", "Change #", "Change %"],
    "FIRST_YEAR_COLUMNS": ["Age", "Days since last load", "Status"],
    "LOST_COLUMNS": ["Days since last load", "Last load date"],
    "RECOVERED_COLUMNS": ["Days since last load", "Status"],
}


def interface_fields(name: str) -> set[str]:
    body = re.search(rf"export interface {name}\b[^{{]*\{{(.*?)\n\}}", API, re.S)
    assert body, f"interface {name} not found"
    return set(re.findall(r"^\s*(\w+)\??:", body.group(1), re.M))


def column_block(name: str) -> str:
    match = re.search(rf"const {name}\b.*?=\s*\[(.*?)^\]", SUMMARY, re.S | re.M)
    assert match, f"{name} is not a module-level column list"
    return match.group(1)


def strip_comments(source: str) -> str:
    return re.sub(r"/\*.*?\*/|//[^\n]*", "", source, flags=re.S)


@pytest.mark.parametrize("name,labels", EXPECTED_LABELS.items())
def test_every_column_has_a_sort_key_on_its_row_type(name: str, labels: list[str]) -> None:
    block = column_block(name)
    assert "CUSTOMER_COLUMN" in block and "ASSIGNED_COLUMN" in block
    declining = name == "DECLINING_COLUMNS"
    fields = interface_fields("DecliningRow" if declining else "BoardRow")
    if name == "AT_RISK_COLUMNS":
        fields = fields | {"profit_90d"}
    pairs = re.findall(r'key:\s*"(\w+)",\s*label:\s*"([^"]+)"', block)
    assert [label for _, label in pairs] == labels
    for key, label in pairs:
        assert key in fields, f"{label}: {key} is not a field of the row"


def test_shared_columns_sort_on_real_fields() -> None:
    assert re.search(r'CUSTOMER_COLUMN[^=]*=\s*\{\s*key:\s*"name"', SUMMARY)
    assert re.search(r'ASSIGNED_COLUMN[^=]*=\s*\{\s*key:\s*"assigned_to"', SUMMARY)


def test_all_five_tables_use_the_sorted_rows_and_their_columns() -> None:
    assert "useSortable(" in SUMMARY
    assert "useSortable(sortable," in SUMMARY, "sort the NO TEAM-mapped rows, not the raw ones"
    assert "sorted.map(" in SUMMARY, "the body must render the sorted rows"
    assert not re.search(r"\brows\.map\(\(r\) => \(\s*<tr", SUMMARY), "body renders unsorted rows"
    for name in EXPECTED_LABELS:
        assert f"columns={{{name}}}" in SUMMARY


def test_server_order_is_declared_so_the_first_click_is_never_dead() -> None:
    assert re.search(r'useSortable\(sortable,\s*defaultSort\?\.key \?\? null,\s*defaultSort\?\.dir', SUMMARY), "the default must reach the hook"
    assert re.search(r'columns=\{AT_RISK_COLUMNS\}[^/]*?defaultSort=\{\{\s*key:\s*"profit_90d",\s*dir:\s*"desc"', SUMMARY, re.S)
    assert re.search(r'columns=\{DECLINING_COLUMNS\}[^/]*?defaultSort=\{\{\s*key:\s*"change",\s*dir:\s*"asc"', SUMMARY, re.S)


def test_a_drop_sorts_worst_first_and_text_sorts_a_to_z() -> None:
    assert re.search(r'key:\s*"change",[^\n]*firstDir:\s*"asc"', SUMMARY)
    assert re.search(r'key:\s*"change_pct",[^\n]*firstDir:\s*"asc"', SUMMARY)
    assert re.search(r'c\.firstDir\s*\?\?\s*\(c\.left \? "asc" : "desc"\)', SUMMARY)


def test_header_is_a_button_announcing_its_sort_and_stays_white() -> None:
    assert "aria-sort=" in SUMMARY
    assert "onClick={() => sort.toggleSort(column.key)}" in SUMMARY, "a header that does not sort"
    assert '<button' in SUMMARY and 'type="button"' in SUMMARY
    assert "ArrowUpDown" in SUMMARY, "an unsorted column must show that it can be sorted"
    assert "SortableTh" not in strip_comments(SUMMARY), "SortableTh paints the active label navy on navy"


def test_header_arrow_does_not_widen_the_column() -> None:
    header = strip_comments(SUMMARY)
    header = header[header.index("function SortHeader"):header.index("function BoardTable")]
    assert "inline-flex" not in header, "a flex row adds the arrow to each column's minimum width"
    assert re.search(r'<Icon[^>]*className=\{`[^`]*\binline\b', header)


def test_no_team_sorts_with_the_blanks() -> None:
    assert re.search(r'assigned_to === "NO TEAM"\s*\?\s*\{\s*\.\.\.r,\s*assigned_to:\s*null\s*\}', SUMMARY)


def test_negative_helper_is_by_value_and_null_safe() -> None:
    helper = re.search(r"export const negativeClass[^\n]*\n?[^\n]*", UI)
    assert helper, "ui.tsx must export negativeClass"
    text = helper.group(0)
    assert "< 0" in text and "#DC2626" in text
    assert "!= null" in text, "a blank is not a negative"


@pytest.mark.parametrize("field", ["r.profit_90d", "r.change", "pct"])
def test_summary_negatives_are_red(field: str) -> None:
    code = strip_comments(SUMMARY)
    assert f"negativeClass({field})" in code


def test_change_pct_is_no_longer_red_unconditionally() -> None:
    assert 'className="text-[#DC2626]">{signed(' not in SUMMARY


@pytest.mark.parametrize(
    "label,field",
    [("Profit", "c.margin"), ("Margin %", "c.margin_pct"), ("Avg. monthly Profit", "c.avg_monthly_margin")],
)
def test_drawer_facts_are_red_when_negative(label: str, field: str) -> None:
    assert re.search(rf'<Fact label="{re.escape(label)}"[^>]*negativeIf=\{{{re.escape(field)}\}}', DRAWER), f"{label} fact"
    fact = DRAWER[DRAWER.index("function Fact"):DRAWER.index("function tooltipValue")]
    assert "negativeClass(negativeIf)" in fact, "the prop must reach the class"


def test_drawer_monthly_table_marks_both_profit_and_margin_pct() -> None:
    assert "negativeClass(p.margin)" in DRAWER
    assert "negativeClass(p.margin_pct)" in DRAWER


def test_drawer_tooltip_marks_the_value_and_keeps_a_blank_blank() -> None:
    code = strip_comments(DRAWER)
    start = code.index("<Tooltip")
    assert "tooltipValue(v, name)" in code[start:code.index("<Legend", start)]
    helper = code[code.index("function tooltipValue"):code.index("export function CustomerDrawer")]
    assert "negativeClass(n)" in helper
    assert "v == null ? null : Number(v)" in helper, "Number(null) would print 0.0%"
    assert "fmtPct(n)" in helper and "fmtUsd(n)" in helper
