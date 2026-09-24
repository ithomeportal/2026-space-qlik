"""Every live report must be recognisable by its icon alone.

Erick Mendoza (CEO), 2026-09-24, looking at the Favorites rail: "how do I change
the colour or the logos when the two boards have the same logo and the same
colour?" — "CEO Executive" and "CEO Executive Portal" were both a purple Crown.
A second pair ("OPS - Access Log Doors" / "Pricing - Access Log Doors") had the
same defect. Asked to "avoid this in general for all", so this is a guard, not
a one-off fix.

What makes an icon distinct is the triple (lucide icon, colour family, corner
tag). The tag counts ONLY because every surface that draws an icon draws its
tag — the Home tile always did; the Favorites rail did not until 2026-09-24
(``test_the_favorites_rail_renders_the_tag`` below keeps it that way).

There is no JS test runner in this repo, so the frontend half is read as text
from Python, like the sort-whitelist guard in test_production_spots_trends.py.
"""

from __future__ import annotations

import pathlib
import re
from collections import defaultdict

from app.services.seed import CUSTOM_REPORTS

FRONTEND = pathlib.Path(__file__).resolve().parents[2] / "frontend"

# `"Title": { icon: Name, family: "fam", tag: "T" },` — the key and the object
# may sit on two lines (the long "Carrier Procurement - …" key does).
_ENTRY = re.compile(
    r'"(?P<title>[^"]+)":\s*\{\s*icon:\s*(?P<icon>\w+),\s*family:\s*"(?P<family>\w+)"'
    r'(?:,\s*tag:\s*"(?P<tag>[^"]*)")?\s*\}',
)


def _report_map() -> dict[str, tuple[str, str, str]]:
    src = (FRONTEND / "components/ReportIcons.tsx").read_text()
    start = src.index("const REPORT_MAP")
    end = src.index("\n}\n", start)
    out: dict[str, tuple[str, str, str]] = {}
    for m in _ENTRY.finditer(src[start:end]):
        assert m["title"] not in out, f"duplicate REPORT_MAP key {m['title']!r}"
        out[m["title"]] = (m["icon"], m["family"], m["tag"] or "")
    return out


def _seeded_titles() -> list[str]:
    return [r["title"] for r in CUSTOM_REPORTS]


def test_the_parser_sees_the_whole_map() -> None:
    """A regex that silently stops matching would pass every test below."""
    rmap = _report_map()
    assert len(rmap) >= 60, f"parsed only {len(rmap)} REPORT_MAP entries"
    assert rmap["XRay DFW TM1"] == ("Activity", "dfw", "TM1")
    assert rmap["Carrier Procurement - Access Log Doors"] == ("DoorOpen", "procurement", "")


def test_every_seeded_report_has_an_explicit_icon() -> None:
    """An unmapped title falls through to ``inferFromTitle`` — keyword guessing
    that gives every "… Attrition …" the same UserMinus. The lookup is by exact
    TITLE (an en dash vs a hyphen is a miss), so this also catches a rename in
    seed.py that was not mirrored in ReportIcons.tsx."""
    rmap = _report_map()
    missing = [t for t in _seeded_titles() if t not in rmap]
    assert not missing, f"no REPORT_MAP entry for: {missing}"


def test_no_two_seeded_reports_share_an_icon() -> None:
    rmap = _report_map()
    by_look: dict[tuple[str, str, str], list[str]] = defaultdict(list)
    for title in _seeded_titles():
        if title in rmap:
            by_look[rmap[title]].append(title)
    clashes = {look: ts for look, ts in by_look.items() if len(ts) > 1}
    assert not clashes, (
        "reports that render identically (icon, family, tag) — give one a "
        f"different icon, family or tag: {clashes}"
    )


def test_the_executive_ops_portal_is_not_the_ceo_executive_crown() -> None:
    """The pair Erick reported, pinned by name."""
    rmap = _report_map()
    assert rmap["Executive OPS Portal"] != rmap["CEO Executive"]


def test_the_favorites_rail_renders_the_tag() -> None:
    """The uniqueness above counts the tag, so the rail must draw it — without
    it XRay DFW TM1..TM4 are four identical tiles in the collapsed rail."""
    src = (FRONTEND / "components/FavoritesSidebar.tsx").read_text()
    assert re.search(r"\{\s*icon:\s*Icon,[^}]*\btag\b[^}]*\}\s*=\s*getReportIcon", src)
    assert "{tag}" in src
