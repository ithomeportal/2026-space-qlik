"""Frontend guards for Bruno "Ops Portal Updates" 2026-10-16 (R3/R4/R5).

No JS test runner exists in this repo, so — like the other frontend guards —
these read the TSX/TS source from Python.
"""

from __future__ import annotations

import pathlib
import re

_FRONTEND = pathlib.Path(__file__).resolve().parents[2] / "frontend"
_CONTENT = _FRONTEND / "components" / "OpsPortalOverviewContent.tsx"
_CEO = _FRONTEND / "app" / "reports" / "ceo-executive-portal" / "page.tsx"
_OPP = _FRONTEND / "app" / "reports" / "ops-portal-overview"
_API = _FRONTEND / "lib" / "ops-portal-overview-api.ts"

FUEL = "https://pricing.unilinkportal.com/admin/us-national-fuel"


def _list_body(src: str, name: str) -> str:
    m = re.search(rf"const {name}: readonly GoToLink\[\] = \[(.*?)\n\]", src, re.S)
    assert m, f"{name} not found"
    return m.group(1)


# ---- R5 — US National Fuel in the Go-to row --------------------------------


def test_us_national_fuel_is_defined_once_with_the_external_href() -> None:
    src = _CONTENT.read_text()
    assert src.count(FUEL) == 1
    assert re.search(r'label: "US National Fuel",\s*href: "' + re.escape(FUEL) + '"', src)


def test_it_is_on_both_the_corp_and_the_dfw_lists() -> None:
    assert "US_NATIONAL_FUEL_LINK" in _list_body(_CONTENT.read_text(), "CORP_GO_TO_LINKS")
    assert "US_NATIONAL_FUEL_LINK" in _list_body(_CEO.read_text(), "DFW_GO_TO_LINKS")


def test_the_all_division_list_is_deduped_by_href() -> None:
    """ALL concatenates CORP + DFW, which now share a link; `key={href}` collides."""
    src = _CEO.read_text()
    assert re.search(
        r"all: dedupeGoToLinks\(\[\.\.\.CORP_GO_TO_LINKS, \.\.\.DFW_GO_TO_LINKS\]\)", src
    )
    content = _CONTENT.read_text()
    assert "export function dedupeGoToLinks" in content
    # The renderer dedupes too, so any caller-supplied list is safe.
    assert "dedupeGoToLinks(goToLinks ?? CORP_GO_TO_LINKS)" in content


def test_external_hrefs_render_as_a_plain_anchor_in_a_new_tab() -> None:
    src = _CONTENT.read_text()
    m = re.search(r"isExternalHref\(href\) \? \((.*?)\) : \(", src, re.S)
    assert m, "the Go-to renderer does not branch on external hrefs"
    anchor = m.group(1)
    assert anchor.lstrip().startswith("<a ")
    assert 'target="_blank"' in anchor and 'rel="noopener noreferrer"' in anchor


# ---- R4 — Over Pay replaces Not Billed --------------------------------------


def test_not_billed_is_gone_from_the_frontend() -> None:
    # SidePanels.tsx was split into one file per panel (layout 2026-10-28).
    for path in (*_OPP.glob("*Panel*.tsx"), _API):
        src = path.read_text()
        assert "customer-not-billed" not in src
        assert "NotBilled" not in src


def test_the_over_pay_panel_calls_the_new_endpoint_and_drills() -> None:
    api = _API.read_text()
    assert "/customer-overpay${qs(f)}" in api
    # Mounted by the overview grid (layout 2026-10-28), defined in its own file.
    grid = (_OPP / "OverviewPanelGrid.tsx").read_text()
    assert "<CustomerOverPay filters={filters} onPickCustomer={onPickCustomer} />" in grid
    panel = (_OPP / "OverPayPanel.tsx").read_text()
    assert 'title="Over Pay"' in panel
    assert "meta?.totals as OppCustomerOverPayTotals" in panel


# ---- R3 — PickUp / Delivery toggle -----------------------------------------


def test_incidents_are_one_panel_with_a_pickup_delivery_toggle() -> None:
    src = (_OPP / "ServiceIncidentTables.tsx").read_text()
    assert '{ key: "pu", label: "PickUp"' in src
    assert '{ key: "del", label: "Delivery"' in src
    assert 'useState<StopType>("pu")' in src  # default PickUp
    # Exactly one incident panel mounted ⇒ only the selected stop_type fetches.
    assert src.count("<IncidentPanel ") == 1
    assert src.count("useOppServiceIncident(filters, stopType)") == 1
    assert "<CarrierPanel " in src
