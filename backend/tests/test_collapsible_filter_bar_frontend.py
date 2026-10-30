"""The collapsible sticky filter header (request 2026-10-30, mobile screenshots).

Directors on the Samsung Z Fold and the CEO/CFO on the iPhone Fold asked for the
report filter header to fold away: wrapped onto 4-6 rows and sticky, it held
~45-70% of a phone screen while scrolling. All 24 sticky bars now go through ONE
component, ``components/CollapsibleFilterBar.tsx``.

What these guards pin, none of which a build, lint or page load would catch:

1. **No hand-written sticky bar comes back.** A new report copied from an old
   one would reintroduce the tall, unfoldable bar on phones.
2. **It sticks at ``top-16``, not ``top-0``.** ``<Header/>`` is ``sticky top-0
   h-16 z-50``; a ``top-0`` bar slides its first 64px UNDER the header — the
   Ops Portal's Range row and the Executive portal's Division row were
   invisible in the screenshots. Nothing errors; a row just disappears.
3. **Collapsed children stay MOUNTED** (``hidden`` attribute), so filter
   widgets keep their local state.
4. **localStorage is guarded** — private mode throws, and a folded-bar memory
   must never crash a report.

No JS test runner exists in this repo; like the Favorites rail guards, these
read the TSX source.
"""

from __future__ import annotations

import pathlib
import re

FRONTEND = pathlib.Path(__file__).resolve().parents[2] / "frontend"
COMPONENT = FRONTEND / "components" / "CollapsibleFilterBar.tsx"
HEADER = FRONTEND / "components" / "Header.tsx"

# Every file that owned a sticky report filter bar on 2026-10-30.
USERS = [
    "app/reports/admin-cashflow/page.tsx",
    "app/reports/attrition-wow/AttritionWowContent.tsx",
    "app/reports/booker-performance-scorecard/page.tsx",
    "app/reports/carrier-risk/page.tsx",
    "app/reports/ceo-executive/page.tsx",
    "app/reports/dfw-losses/page.tsx",
    "app/reports/exec-meeting-recruitment/page.tsx",
    "app/reports/hd-spot/page.tsx",
    "app/reports/hr-access-doors/page.tsx",
    "app/reports/it-tickets-mgmt/page.tsx",
    "app/reports/kam-performance-dfw/page.tsx",
    "app/reports/losses-lanes/page.tsx",
    "app/reports/ops-margins/page.tsx",
    "app/reports/podium-dfw/page.tsx",
    "app/reports/production-spots-trends/page.tsx",
    "app/reports/rfp-performance/page.tsx",
    "app/reports/sales-attrition-to-ops/page.tsx",
    "app/reports/track-award-loads/page.tsx",
    "app/reports/voip-calls-logs/page.tsx",
    "app/reports/xray-corp-mng/page.tsx",
    "components/OpsPortalOverviewContent.tsx",
    "components/XrayDfwReportContent.tsx",
    "components/access-doors/ScopedAccessDoorsReport.tsx",
    "components/CustomerScoreContent.tsx",
]

# A page-level sticky BAR: a shadowed <div> pinned to the top. In-table column
# headers (thead, or the Lifespan timeline's header row inside its own scroll
# box) are sticky too but carry no shadow and are legitimately top-0.
STICKY_TOP_DIV = re.compile(
    r'<div\s+className="(?=[^"]*\bsticky\s+top-0\b)(?=[^"]*\bshadow-sm\b)[^"]*"'
)


def _tsx_files() -> list[pathlib.Path]:
    return [
        p
        for root in ("app", "components")
        for p in (FRONTEND / root).rglob("*.tsx")
        if "node_modules" not in p.parts
    ]


def test_every_former_sticky_bar_uses_the_component():
    for rel in USERS:
        src = (FRONTEND / rel).read_text()
        assert "<CollapsibleFilterBar" in src, rel
        assert 'from "@/components/CollapsibleFilterBar"' in src, rel
        assert src.count("<CollapsibleFilterBar") == src.count("</CollapsibleFilterBar>"), rel


def test_no_hand_written_sticky_top_bar_remains():
    offenders = [
        str(p.relative_to(FRONTEND))
        for p in _tsx_files()
        if p != COMPONENT and STICKY_TOP_DIV.search(p.read_text())
    ]
    assert offenders == [], f"use <CollapsibleFilterBar> instead: {offenders}"


def test_sticks_below_the_header_not_under_it():
    header = HEADER.read_text()
    assert re.search(r"sticky top-0 z-50 h-16", header), "header height changed — re-check top-16"
    src = COMPONENT.read_text()
    assert re.search(r"`sticky top-16 z-10 ", src)
    assert not re.search(r"className=\{`sticky top-0\b", src)


def test_collapsed_children_stay_mounted_and_toggle_is_accessible():
    src = COMPONENT.read_text()
    assert "hidden={collapsed}" in src
    assert "aria-expanded" in src and "aria-controls={contentId}" in src
    # The children must not sit behind a conditional that unmounts them.
    assert not re.search(r"collapsed\s*\?\s*null|!collapsed\s*&&\s*children|collapsed\s*&&", src)


def test_local_storage_is_guarded_and_read_after_mount():
    src = COMPONENT.read_text()
    accesses = re.findall(r"window\.localStorage\.\w+", src)
    assert accesses, "persistence was removed"
    for fn in ("readStored", "writeStored"):
        body = src.split(f"function {fn}", 1)[1].split("\n}\n", 1)[0]
        assert "try {" in body and "catch" in body, fn
    assert "useEffect(() => {\n    if (readStored(STORAGE_COLLAPSED)" in src
