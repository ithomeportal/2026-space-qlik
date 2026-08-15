"""Structural guards for the ``ops_portal_overview`` package (split 2026-08-14).

The 4,076-line module became a package of 12 focused modules plus a façade.
Two things can silently break after that split, and neither shows up as an
import error at boot:

1. **A route stops being registered.** Importing an endpoint module is what
   registers its routes on the shared ``router``; drop a line from
   ``__init__.py`` and the endpoint simply vanishes into a 404 that only the
   one panel using it ever notices.
2. **A re-export disappears.** ``ops_portal_overview_team.py``,
   ``ops_team_perf_digest.py`` and ``services/team_perf_digest.py`` all reach
   into this module for helpers by name. The team factory resolves them at
   *call* time via ``opo.<name>``, so a missing export is an AttributeError at
   runtime on a per-team report — not at import.

These tests read the CONSUMERS' source, so a newly-added reach-in is covered
automatically rather than needing this list to be maintained by hand.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

from app.routers import ops_portal_overview as opo

ROUTERS = Path(__file__).resolve().parents[1] / "app" / "routers"
PKG = ROUTERS / "ops_portal_overview"

# Every path the report served before the split. Hard-coded on purpose: this is
# the contract the frontend and the four per-team clones call.
EXPECTED_PATHS = {
    "/custom/ops-portal-overview/filters",
    "/custom/ops-portal-overview/workdays",
    "/custom/ops-portal-overview/combo",
    "/custom/ops-portal-overview/team-variance",
    "/custom/ops-portal-overview/customer-variance",
    "/custom/ops-portal-overview/customer-losses",
    "/custom/ops-portal-overview/customer-not-billed",
    "/custom/ops-portal-overview/team-performance",
    "/custom/ops-portal-overview/team-projection",
    "/custom/ops-portal-overview/profit-tm-gauge",
    "/custom/ops-portal-overview/actuals",
    "/custom/ops-portal-overview/actuals-by-lane",
    "/custom/ops-portal-overview/service",
    "/custom/ops-portal-overview/by-order",
    "/custom/ops-portal-overview/pending-to-cover",
    "/custom/ops-portal-overview/cover",
    "/custom/ops-portal-overview/cover-forecast",
    "/custom/ops-portal-overview/data-freshness",
    "/custom/ops-portal-overview/team-weekly-performance",
    "/custom/ops-portal-overview/team-performance-by-team",
    "/custom/ops-portal-overview/service-incident-by-customer",
    "/custom/ops-portal-overview/service-by-carrier",
    "/custom/ops-portal-overview/margin-distribution",
    "/custom/ops-portal-overview/team-variance-weekly",
    "/custom/ops-portal-overview/team-variance-by-team",
    "/custom/ops-portal-overview/team-projection-by-team",
    "/custom/ops-portal-overview/team-projection-weekly",
}


def test_every_route_is_registered_exactly_once():
    paths = [r.path for r in opo.router.routes]
    assert len(paths) == len(set(paths)), (
        "a route is registered twice — a module is imported from both "
        "__init__ and a sibling"
    )
    assert set(paths) == EXPECTED_PATHS, (
        f"missing={sorted(EXPECTED_PATHS - set(paths))} "
        f"unexpected={sorted(set(paths) - EXPECTED_PATHS)}"
    )


def test_facade_exports_everything_the_team_factory_reaches_for():
    """``ops_portal_overview_team.py`` resolves ``opo.<name>`` at CALL time."""
    src = (ROUTERS / "ops_portal_overview_team.py").read_text()
    names = sorted(set(re.findall(r"\bopo\.([A-Za-z_][A-Za-z0-9_]*)", src)))
    assert names, "probe went blind — the factory no longer uses the opo.* form"
    missing = [n for n in names if not hasattr(opo, n)]
    assert not missing, f"façade no longer exports: {missing}"


@pytest.mark.parametrize(
    "consumer",
    ["app/services/team_perf_digest.py", "app/routers/ops_team_perf_digest.py"],
)
def test_facade_exports_everything_sibling_modules_import(consumer):
    path = ROUTERS.parents[1] / consumer
    tree = ast.parse(path.read_text())
    wanted: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module == (
            "app.routers.ops_portal_overview"
        ):
            wanted += [a.name for a in node.names]
    assert wanted, f"{consumer} no longer imports from ops_portal_overview"
    missing = [n for n in wanted if not hasattr(opo, n)]
    assert not missing, f"{consumer} imports names the façade dropped: {missing}"


def test_no_module_exceeds_the_line_cap():
    """Project rule: files < 400 lines typical, 800 hard cap.

    The whole point of the split was to get under this; a module creeping back
    over 800 means it is time to split again, not to raise the number.
    """
    over = {
        p.name: len(p.read_text().splitlines())
        for p in PKG.glob("*.py")
        if len(p.read_text().splitlines()) > 800
    }
    assert not over, f"modules over the 800-line hard cap: {over}"


def test_submodules_import_standalone_without_cycles():
    """Each module must be importable on its own — a cycle would only surface
    depending on which module happened to be imported first."""
    import importlib

    for p in sorted(PKG.glob("*.py")):
        if p.stem == "__init__":
            continue
        importlib.import_module(f"app.routers.ops_portal_overview.{p.stem}")


def test_the_one_projection_definition_lives_in_exactly_one_module():
    """§69 — re-splitting must not let a second copy of the formula reappear."""
    hits = [
        p.name for p in PKG.glob("*.py")
        if "_PROJ_LOOKBACK_BUSINESS_DAYS =" in p.read_text()
    ]
    assert hits == ["_metrics.py"], f"projection constant defined in {hits}"
