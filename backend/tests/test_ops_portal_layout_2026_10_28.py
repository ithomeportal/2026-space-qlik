"""Frontend guards for the Ops Portal layout change of 2026-10-28.

Business screenshot: three columns in row 1 (Monthly Performance | KPI chart |
Monthly Projection over Customer Monthly Variance), the two Service Incident
panels under the left + centre columns, then Budget Variance · Customer Losses ·
Over Pay · Margin distribution as one four-up row.

No JS test runner exists in this repo, so — like the other frontend guards —
these read the TSX source from Python.
"""

from __future__ import annotations

import pathlib
import re

_FRONTEND = pathlib.Path(__file__).resolve().parents[2] / "frontend"
_CONTENT = _FRONTEND / "components" / "OpsPortalOverviewContent.tsx"
_OPP = _FRONTEND / "app" / "reports" / "ops-portal-overview"
_GRID = _OPP / "OverviewPanelGrid.tsx"

PANEL_FILES = {
    "BudgetMonthlyVariancePanel.tsx": ("TeamBudgetVariance", 'title="Budget Monthly Variance"'),
    "CustomerMonthlyVariancePanel.tsx": ("CustomerVariance", 'title="Customer Monthly Variance"'),
    "CustomerMonthlyLossesPanel.tsx": ("CustomerLosses", 'title="Customer Monthly Losses"'),
    "OverPayPanel.tsx": ("CustomerOverPay", 'title="Over Pay"'),
    "MonthlyPerformancePanel.tsx": ("TeamPerformance", 'title="Monthly Performance"'),
    "MonthlyProjectionPanel.tsx": ("TeamProjection", 'title="Monthly Projection"'),
}


def _grid() -> str:
    return _GRID.read_text()


def _row1() -> str:
    """The JSX of the row-1 grid (which also holds row 2)."""
    src = _grid()
    start = src.index("<div className={ROW1_GRID_CLS}>")
    end = src.index("{/* Row 3")
    return src[start:end]


def _row3() -> str:
    src = _grid()
    start = src.index("{/* Row 3")
    end = src.index("</>", start)
    return src[start:end]


def _top_level_children(block: str) -> list[str]:
    """Split a `<div …>` block into its direct JSX children (depth-1 tags)."""
    body = block[block.index(">") + 1 :]
    children: list[str] = []
    depth = 0
    cur = ""
    for tok in re.split(r"(<[^<>]*?/>|</[A-Za-z][^<>]*>|<[A-Za-z][^<>]*>)", body, flags=re.S):
        if not tok:
            continue
        is_self = tok.startswith("<") and tok.endswith("/>") and not tok.startswith("</")
        is_close = tok.startswith("</")
        is_open = tok.startswith("<") and not is_self and not is_close
        if depth == 0 and (is_open or is_self):
            cur = tok
            if is_self:
                children.append(cur)
                cur = ""
            else:
                depth = 1
            continue
        if depth == 0 and is_close:
            break  # the closing tag of the row itself
        cur += tok
        if is_open:
            depth += 1
        elif is_close:
            depth -= 1
            if depth == 0:
                children.append(cur)
                cur = ""
    return children


# ---- mounting --------------------------------------------------------------


def test_every_portal_mounts_the_one_grid_with_every_prop() -> None:
    src = _CONTENT.read_text()
    assert src.count("<OverviewPanelGrid") == 1
    call = src.split("<OverviewPanelGrid", 1)[1].split("\n        />", 1)[0]
    for prop in (
        "filters={filters}",
        "<ComboChart filters={filters} loadType={loadType} setLoadType={setLoadType} hideBudget={hideBudget} />",
        "onPickCustomer={pickCustomer}",
        "onPickCarrier={pickCarrier}",
        "lockedTeam={lockedTeam}",
        "hideBudget={hideBudget}",
        "customerVarianceBasis={customerVarianceBasis}",
    ):
        assert prop in call, prop
    # The old two-column split and its components are gone from the page.
    assert "SidePanels" not in src
    assert "xl:grid-cols-[1.5fr_1fr]" not in src
    assert not (_OPP / "SidePanels.tsx").exists()


def test_grid_defaults_match_the_old_side_panels() -> None:
    """§77 — props default so the CORP portals need not pass them."""
    src = _grid()
    assert "hideBudget = false" in src
    assert 'customerVarianceBasis = "budget"' in src


# ---- row 1 + row 2 -----------------------------------------------------------


def test_row1_is_three_columns_with_the_chart_widest() -> None:
    src = _grid()
    m = re.search(r"xl:grid-cols-\[minmax\(0,([\d.]+)fr\)_minmax\(0,([\d.]+)fr\)_minmax\(0,([\d.]+)fr\)\]", src)
    assert m, "row 1 is not a three-column xl grid"
    left, centre, right = (float(x) for x in m.groups())
    assert centre > 2 * left and centre > 2 * right
    assert "xl:items-start" in src


def test_row1_order_is_performance_chart_then_projection_over_variance() -> None:
    kids = _top_level_children(_row1())
    assert len(kids) == 4, kids
    perf, chart, right, incidents = kids
    assert "<TeamPerformance " in perf
    assert "{chart}" in chart
    # Right column: Projection stacked over Customer Monthly Variance.
    assert right.index("<TeamProjection ") < right.index("<CustomerVariance")
    assert "space-y-4" in right
    # Row 2 sits in the same grid, spanning left + centre only.
    assert incidents.startswith("<ServiceIncidentTables")
    assert 'className="xl:col-span-2"' in incidents
    assert "col-span-3" not in _row1()


def test_every_row1_grid_child_has_min_w_0() -> None:
    """Grid items default to min-width:auto — one wide table scrolls the page."""
    kids = _top_level_children(_row1())
    for kid in kids[:3]:
        assert "min-w-0" in kid.split(">", 1)[0], kid[:80]
    sit = (_OPP / "ServiceIncidentTables.tsx").read_text()
    assert re.search(r"grid min-w-0 grid-cols-1 gap-4 lg:grid-cols-2 \[&>\*\]:min-w-0 \$\{className\}", sit)


def test_service_incident_panels_still_mount_once() -> None:
    sit = (_OPP / "ServiceIncidentTables.tsx").read_text()
    assert sit.count("<IncidentPanel ") == 1
    assert sit.count("<CarrierPanel ") == 1
    assert _grid().count("<ServiceIncidentTables") == 1


# ---- row 3 -------------------------------------------------------------------


def test_row3_is_budget_losses_overpay_margin() -> None:
    row = _row3()
    order = [
        row.index("<TeamBudgetVariance "),
        row.index("<CustomerLosses "),
        row.index("<CustomerOverPay "),
        row.index("<MarginDistribution "),
    ]
    assert order == sorted(order)
    assert "<MarginDistribution filters={filters} compact />" in row
    assert "[&>*]:min-w-0" in row


def test_hide_budget_drops_the_budget_panel_and_goes_three_up() -> None:
    row = _row3()
    assert '{!hideBudget && <TeamBudgetVariance filters={filters} lockedTeam={lockedTeam} />}' in row
    assert re.search(r'hideBudget \? "xl:grid-cols-3" : "xl:grid-cols-4"', row)
    # Mounted nowhere else.
    assert _grid().count("<TeamBudgetVariance ") == 1


def test_margin_distribution_compact_is_three_by_two() -> None:
    src = (_OPP / "MarginDistribution.tsx").read_text()
    assert "compact = false" in src
    assert 'grid grid-cols-3 gap-2 text-xs ${compact ? "" : "md:grid-cols-6"}' in src
    # Band + header totals are kept in both modes (not behind `compact`).
    assert "flex h-3 w-full overflow-hidden rounded-full" in src
    assert "orders · {fmtUsd(totalRevenue)} revenue" in src


# ---- the split ---------------------------------------------------------------


def test_each_panel_lives_in_its_own_file() -> None:
    for name, (component, title) in PANEL_FILES.items():
        src = (_OPP / name).read_text()
        assert f"export function {component}(" in src, name
        assert title in src, name


def test_no_new_panel_file_exceeds_800_lines() -> None:
    files = [*PANEL_FILES, "PanelShared.tsx", "OverviewPanelGrid.tsx"]
    for name in files:
        n = (_OPP / name).read_text().count("\n")
        assert n <= 800, f"{name}: {n} lines"
    assert _CONTENT.read_text().count("\n") <= 800


def test_the_toggles_and_drills_survived_the_move() -> None:
    perf = (_OPP / "MonthlyPerformancePanel.tsx").read_text()
    assert "<TeamWeeklyModal " in perf and "<TeamMonthlyModal " in perf
    assert "{!lockedTeam && (" in perf
    proj = (_OPP / "MonthlyProjectionPanel.tsx").read_text()
    for s in ("<ProjectionWeekModal ", "<ProjectionTeamModal ", "<ProjectionTrendModal ", "<ProjProfitTicker "):
        assert s in proj, s
    budget = (_OPP / "BudgetMonthlyVariancePanel.tsx").read_text()
    assert "<VarianceWeekModal " in budget and "<VarianceTeamModal " in budget
    for name in ("CustomerMonthlyVariancePanel.tsx", "CustomerMonthlyLossesPanel.tsx", "OverPayPanel.tsx"):
        assert "<CustomerNameCell name={r.customer_name} onPick={onPickCustomer} />" in (_OPP / name).read_text()
