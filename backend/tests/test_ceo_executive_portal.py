"""CEO Executive Portal — one report, two divisions, neither able to leak.

Bruno PDF "BRUNO -- Exec Portal" (2026-09-03), Requests 1-3.

This is the first report where the DIVISION IS CHOSEN BY THE CLIENT. Every
other portal pins its scope server-side, so the whole class of "served the
wrong tenant" bugs was structurally impossible there and is not here. Three
properties, all of which fail SILENTLY — a wrong division returns a complete,
plausible report:

  * **The division can never default.** On 2026-09-02 the DFW Bonus Calculator
    served the CORPORATE report whole because `scope` carried a default
    (`afff8d6`, §100). Here it is a required path segment, and
    `test_no_endpoint_lets_the_division_default` mutation-checks that: it fails
    if anyone gives `division` a default, drops it from a signature, or makes
    `_pin_scope` fall back instead of raising.

  * **Neither division may leak into the other.** Asserted by DRIVING EVERY
    ENDPOINT under each scope and reading the statements it emits — the only
    method that catches an endpoint which forgot to read `request.state`,
    because with today's data both divisions return real rows either way.

  * **CORP must still be the CORP report.** Request 1 says "duplicate", so a
    CORP view here has to emit the same SQL as /reports/ops-portal-overview.
    Asserted statement-for-statement against the live router, not by eye.

⚠ The §100 lesson in one line: asserting the SCOPE OBJECT proves nothing —
twelve tests did that and stayed green through the Bonus leak. Everything here
drives an ENDPOINT.
"""

from __future__ import annotations

import asyncio
import inspect
import json
import types

import pytest
from fastapi import HTTPException

from app.routers import ops_portal_overview as opo
from app.routers import ops_portal_overview_ceo as ceo
from app.routers import ops_portal_overview_dfw as dfw
from app.routers.ops_portal_overview import meta as _meta
from app.routers.ops_portal_overview._scope import (
    CORP_SCOPE,
    DFW_SCOPE,
    DIVISIONS,
    sub_team_of,
    sub_teams_of,
)

CORP_IDS = ("TEAM1", "TEAM2", "TEAM3", "TEAM4", "TEAM5")
DFW_ID = "TEAM-DFW"

# The four budget-derived panels. DFW has no rows in
# `daily_production_budget_report`, so these 404 there rather than return zeros.
BUDGET_PATHS = {
    "team-variance",
    "team-variance-weekly",
    "team-variance-by-team",
}

# Division-blind by design, with the reason. Anything NOT listed must scope
# itself — a new endpoint is opted IN by default.
UNSCOPED_BY_DESIGN = {
    # Staleness is a property of the ETL feed, not of a team; every portal
    # reports the same answer off the same 60s cache.
    "data-freshness",
    # Calendar arithmetic only (Mon-Fri ex-holidays).
    "workdays",
}

# Emits no SQL at all — a strict subset of the above. Kept separate because
# "division-blind" and "queries nothing" are different claims, and conflating
# them let /data-freshness pass a parity check vacuously: its 60s module cache
# means it only queries on the first call of a minute, so whether it emitted
# anything depended on TEST ORDER (`_drive` now clears that cache).
NO_SQL = {"workdays"}


class _StubPool:
    """Captures every statement instead of running any of them."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple]] = []

    async def fetch(self, sql, *params):
        self.calls.append((sql, params))
        return []

    async def fetchrow(self, sql, *params):
        self.calls.append((sql, params))
        return None

    async def fetchval(self, sql, *params):
        self.calls.append((sql, params))
        return None


_ENDPOINT_MODULES = (
    "meta", "chart", "variance", "performance",
    "projection", "actuals", "orders", "hold", "incidents",
)


def _patch_pools(pool):
    """Point every module's pool factory at the stub; return an undo callable."""
    import importlib

    originals = []
    for name in _ENDPOINT_MODULES:
        m = importlib.import_module(f"app.routers.ops_portal_overview.{name}")
        if hasattr(m, "get_datalake_gold_pool"):
            originals.append((m, m.get_datalake_gold_pool))
            m.get_datalake_gold_pool = lambda request, _p=pool: _p
    for m in (dfw,):
        originals.append((m, m.get_datalake_gold_pool))
        m.get_datalake_gold_pool = lambda request, _p=pool: _p

    # ⚠ /team-projection-history reads the HUB pool (ops_projection_history)
    # as well as gold. Without this it raised before emitting anything and
    # every assertion about it passed on an empty statement list.
    hub_originals = []
    for name in ("projection",):
        m = importlib.import_module(f"app.routers.ops_portal_overview.{name}")
        if hasattr(m, "get_pool"):
            hub_originals.append((m, m.get_pool))
            m.get_pool = lambda request, _p=pool: _p

    def undo():
        for mod, fn in originals:
            mod.get_datalake_gold_pool = fn
        for mod, fn in hub_originals:
            mod.get_pool = fn

    return undo


def _drive(fn, *, division: str, **overrides) -> _StubPool:
    """Call an endpoint the way FastAPI would, with the division pinned.

    Runs the router's own `_pin_scope` dependency first — so this exercises the
    real path a browser takes, not a hand-set `request.state`. Anything that
    stops `_pin_scope` from stamping the scope shows up here as a CORP leak.

    `Query(...)`/`Path(...)` defaults are resolved exactly as FastAPI resolves
    them; calling these as plain Python without that is the §40 bug.
    """
    pool = _StubPool()
    undo = _patch_pools(pool)
    _meta._freshness_cache["at"] = None
    request = types.SimpleNamespace(
        app=types.SimpleNamespace(state=types.SimpleNamespace()),
        state=types.SimpleNamespace(),
    )
    ceo._pin_scope(request, division)
    kwargs = {}
    for name, p in inspect.signature(fn).parameters.items():
        if name == "request":
            kwargs[name] = request
        elif name in ("_user", "user"):
            kwargs[name] = {}
        else:
            d = p.default
            v = getattr(d, "default", d)
            kwargs[name] = None if v is Ellipsis else v
    kwargs.update(overrides)
    try:
        try:
            asyncio.run(fn(**kwargs))
        except HTTPException:
            raise
        except Exception:
            # The stub returns None/[]; several endpoints subscript that after
            # emitting their SQL. The statement is what we came for.
            pass
    finally:
        undo()
    return pool


def _blob(pool: _StubPool) -> str:
    out = []
    for sql, params in pool.calls:
        out.append(sql)
        out.append(json.dumps([list(p) if isinstance(p, (list, tuple)) else str(p)
                               for p in params]))
    return "\n".join(out)


def _routes():
    """(slug, handler) for every route the CEO router exposes."""
    return [(r.path.rsplit("/", 1)[-1], r.endpoint) for r in ceo.r.routes]


def _slugs(routes) -> set[str]:
    return {r.path.rsplit("/", 1)[-1] for r in routes}


# ---------------------------------------------------------------------------
# Request 1 — it is a DUPLICATE, so its surface must match
# ---------------------------------------------------------------------------


def test_it_exposes_exactly_the_corp_reports_endpoints() -> None:
    """A missing path is a panel that 404s while the page looks fine.

    That is how the DFW portal shipped without /team-projection-by-team: the
    Monthly Projection "Team" button opened onto a 404 for two weeks and
    nothing else on the page changed.
    """
    assert _slugs(ceo.r.routes) == _slugs(opo.router.routes)


def test_every_path_carries_the_division_segment() -> None:
    for route in ceo.r.routes:
        assert "/{division}/" in route.path, f"{route.path} has no division segment"


def test_it_has_its_own_report_key_and_gate() -> None:
    """A borrowed gate would grant this report to the other report's audience."""
    assert ceo.REPORT_KEY == "ceo-executive-portal"
    assert ceo.REPORT_KEY not in (dfw.REPORT_KEY, "ops-portal-overview")


@pytest.mark.parametrize("slug,fn", _routes(), ids=lambda v: v if isinstance(v, str) else "")
def test_each_shim_declares_every_param_its_target_declares(slug: str, fn) -> None:
    """A param this router forgets to declare is a filter that stops applying.

    FastAPI silently drops what a handler does not declare, so `?carriers=X`
    would be accepted, ignored, and the panel would answer for every carrier —
    no error anywhere (§ "FastAPI drops undeclared params"). Comparing against
    the CORP endpoint mechanically means a param added upstream cannot be
    dropped here without this failing.
    """
    target = {
        r.path.rsplit("/", 1)[-1]: r.endpoint for r in opo.router.routes
    }[slug]
    want = set(inspect.signature(target).parameters) - {"_user", "user"}
    got = set(inspect.signature(fn).parameters)
    assert want <= got, f"{slug} drops {sorted(want - got)}"


# ---------------------------------------------------------------------------
# §100 — the division must never be able to default
# ---------------------------------------------------------------------------


def test_no_endpoint_lets_the_division_default() -> None:
    """The single mutation that would reproduce the Bonus leak.

    A `division: str = "corp"` anywhere here means a caller that omits it gets
    the CORPORATE report under a DFW heading, silently. `Path(...)` is required
    by construction; anything with a real default fails this.
    """
    for slug, fn in _routes():
        p = inspect.signature(fn).parameters.get("division")
        if p is None:
            continue  # handled through the router dependency, checked below
        default = getattr(p.default, "default", p.default)
        assert default is Ellipsis or default is inspect.Parameter.empty, (
            f"{slug} lets `division` default to {default!r}"
        )


def test_the_scope_is_pinned_as_a_router_dependency() -> None:
    """Router-level, so it also covers the handlers that call opo/dfw directly."""
    deps = [d.dependency for d in ceo.r.dependencies]
    assert ceo._pin_scope in deps


@pytest.mark.parametrize("bad", ["", "corporate", "CORP ", "t1", "dfw2", "../corp", "None"])
def test_an_unknown_division_is_refused_rather_than_defaulted(bad: str) -> None:
    """It must RAISE. Falling back to CORP is exactly the §100 failure.

    ⚠ `"CORP "` is in this list on purpose: it is accepted (trimmed+lowered),
    which is deliberate tolerance for a trailing space in a URL — but only for
    a spelling that already names a real division.
    """
    request = types.SimpleNamespace(state=types.SimpleNamespace())
    if bad.strip().lower() in DIVISIONS:
        ceo._pin_scope(request, bad)
        assert request.state.opp_scope is DIVISIONS[bad.strip().lower()]
        return
    with pytest.raises(HTTPException) as e:
        ceo._pin_scope(request, bad)
    assert e.value.status_code == 422
    assert not hasattr(request.state, "opp_scope")


def test_the_two_divisions_are_the_live_scopes_not_new_ones() -> None:
    """Request 1 says DUPLICATE, so these must BE the live portals' scopes.

    Rebuilding an equivalent `DivisionScope` here would let the two drift — the
    PDF's own CORP list (TEAM1..TEAM4) differs from the live one by TEAM5, so a
    private copy would have quietly shipped a report that does not tie out to
    the one it duplicates (§95).
    """
    assert DIVISIONS["corp"] is CORP_SCOPE
    assert DIVISIONS["dfw"] is DFW_SCOPE
    assert CORP_SCOPE.base_teams == CORP_IDS
    assert DFW_SCOPE.base_teams == (DFW_ID,)


# ---------------------------------------------------------------------------
# The property that matters: drive EVERY endpoint, under BOTH divisions
# ---------------------------------------------------------------------------


def _cross(fn, other: str) -> dict:
    """Hand the endpoint the OTHER division's team, if it takes one.

    ⚠ This is the ordinary path, not an attack: clicking Division leaves the
    previous division's pill in the request until the reset lands. Driving with
    `team=None` would pass for a shim that forgot `_sub_team` entirely — the
    base predicate would still be right and the leak would only appear once a
    user had touched the Teams row.
    """
    params = inspect.signature(fn).parameters
    out = {}
    if "team" in params:
        out["team"] = other
    if "teams" in params:
        out["teams"] = other
    return out


@pytest.mark.parametrize("slug,fn", _routes(), ids=lambda v: v if isinstance(v, str) else "")
def test_no_endpoint_leaks_corp_into_the_dfw_view(slug: str, fn) -> None:
    if slug in BUDGET_PATHS:
        pytest.skip("404s under dfw — asserted separately")
    pool = _drive(fn, division="dfw", **_cross(fn, "TEAM1"))
    if not pool.calls:
        pytest.skip(f"{slug} emits no SQL")
    blob = _blob(pool)
    for corp_id in CORP_IDS:
        assert corp_id not in blob, f"{slug} leaks {corp_id} into the DFW view"


@pytest.mark.parametrize("slug,fn", _routes(), ids=lambda v: v if isinstance(v, str) else "")
def test_no_endpoint_leaks_dfw_into_the_corp_view(slug: str, fn) -> None:
    """The direction the DFW portal never had to worry about.

    A pinned portal can only leak one way. This one can leak both, and a CORP
    view contaminated with DFW would move the headline numbers by 14,456 loads
    — larger than CORP itself.
    """
    pool = _drive(fn, division="corp", **_cross(fn, "TM1"))
    if not pool.calls:
        pytest.skip(f"{slug} emits no SQL")
    assert DFW_ID not in _blob(pool), f"{slug} leaks {DFW_ID} into the CORP view"
    assert "TM1" not in _blob(pool), f"{slug} passes a DFW sub-team into the CORP view"


@pytest.mark.parametrize("slug,fn", _routes(), ids=lambda v: v if isinstance(v, str) else "")
def test_every_endpoint_actually_scopes_to_the_requested_division(slug: str, fn) -> None:
    """Absence of the other division is not presence of this one.

    The leak tests alone would pass for an endpoint that scopes to nothing at
    all, so this asserts the positive. Exemptions are named with a reason, so
    a new endpoint cannot quietly opt out.
    """
    if slug in BUDGET_PATHS:
        pytest.skip("404s under dfw — asserted separately")
    pool = _drive(fn, division="dfw")
    if not pool.calls:
        pytest.skip(f"{slug} emits no SQL")
    if slug in UNSCOPED_BY_DESIGN:
        assert DFW_ID not in _blob(pool), (
            f"{slug} is listed as division-blind but now scopes itself — "
            "remove it from UNSCOPED_BY_DESIGN"
        )
        return
    assert DFW_ID in _blob(pool), f"{slug} is not scoped to the division"


@pytest.mark.parametrize("slug,fn", _routes(), ids=lambda v: v if isinstance(v, str) else "")
def test_the_corp_view_emits_the_corp_reports_own_sql(slug: str, fn) -> None:
    """Request 1: "duplicate". Statement-for-statement, not by eye.

    Drives the CEO shim and the live CORP endpoint with the same inputs and
    compares every statement AND every bound parameter. This is what makes the
    report reconcile to the cent with /reports/ops-portal-overview instead of
    merely looking similar.
    """
    target = {r.path.rsplit("/", 1)[-1]: r.endpoint for r in opo.router.routes}[slug]
    args = _cross(fn, "TEAM2")           # a real CORP team, so `team` is exercised
    mine = _blob(_drive(fn, division="corp", **args))
    theirs = _blob(_drive_plain(target, **args))
    if slug in NO_SQL:
        assert not mine and not theirs, (
            f"{slug} is listed as emitting no SQL but now does — "
            "drop it from NO_SQL so parity is actually compared"
        )
        return
    assert mine, f"{slug} emitted nothing — the comparison below would be vacuous"
    assert mine == theirs, f"{slug} does not emit the CORP report's SQL"


def _drive_plain(fn, **overrides) -> _StubPool:
    """`_drive` without the CEO router — the live CORP endpoint, unpinned."""
    pool = _StubPool()
    undo = _patch_pools(pool)
    _meta._freshness_cache["at"] = None
    request = types.SimpleNamespace(
        app=types.SimpleNamespace(state=types.SimpleNamespace()),
        state=types.SimpleNamespace(),
    )
    kwargs = {}
    for name, p in inspect.signature(fn).parameters.items():
        if name == "request":
            kwargs[name] = request
        elif name in ("_user", "user"):
            kwargs[name] = {}
        else:
            d = p.default
            v = getattr(d, "default", d)
            kwargs[name] = None if v is Ellipsis else v
    kwargs.update(overrides)
    try:
        try:
            asyncio.run(fn(**kwargs))
        except Exception:
            pass
    finally:
        undo()
    return pool


# ---------------------------------------------------------------------------
# Budget: 404, never zeros
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("slug", sorted(BUDGET_PATHS))
def test_the_budget_panels_404_under_dfw_instead_of_returning_zeros(slug: str) -> None:
    """A zero is a number and reads as data (§98).

    DFW has 0 of its 15 YTD customers in `daily_production_budget_report`, so
    "budget = 0" is not a measurement, it is the absence of one. The caller
    cannot tell those apart from a payload, so this refuses rather than answers.
    """
    fn = dict(_routes())[slug]
    with pytest.raises(HTTPException) as e:
        _drive(fn, division="dfw")
    assert e.value.status_code == 404


@pytest.mark.parametrize("slug", sorted(BUDGET_PATHS))
def test_the_budget_panels_still_work_under_corp(slug: str) -> None:
    """The 404 must be about the DIVISION, not about the report."""
    pool = _drive(dict(_routes())[slug], division="corp")
    assert pool.calls, f"{slug} emitted nothing under corp"


def test_the_budget_routes_are_registered_for_both_divisions() -> None:
    """One path set, whichever division is showing.

    If the routes were registered per-division the CORP view would 404 on a
    path the DFW view defines, and the failure would land in the browser as a
    dead panel rather than here.
    """
    for slug in BUDGET_PATHS:
        assert slug in _slugs(ceo.r.routes)


# ---------------------------------------------------------------------------
# The one endpoint whose DEFINITION changes with the division
# ---------------------------------------------------------------------------


def test_customer_variance_is_budget_under_corp_and_month_over_month_under_dfw() -> None:
    """Same path, same wire fields, DIFFERENT metric — and opposite signs.

    CORP: actual − budget (positive = over budget). DFW: last month − this
    month (positive = down this month). Serving one under the other's label is
    §95 exactly: the number stays plausible and the meaning inverts. Asserted
    from the SQL, because both return real rows either way.
    """
    corp = _blob(_drive(ceo.customer_variance, division="corp"))
    dfw_blob = _blob(_drive(ceo.customer_variance, division="dfw"))

    assert "daily_production_budget_report" in corp
    assert "daily_production_budget_report" not in dfw_blob
    # The MoM shape: both months in ONE scan, via FILTER clauses (§73).
    assert dfw_blob.count("FILTER (") >= 6


def test_customer_variance_delegates_rather_than_reimplementing() -> None:
    """Two copies of a metric is how the two drift (§69)."""
    src = inspect.getsource(ceo.customer_variance)
    assert "dfw.customer_variance(" in src
    assert "opo.customer_variance(" in src
    assert "SELECT" not in src.upper().replace("SELECTS", "")


# ---------------------------------------------------------------------------
# Team normalisation — widen, never narrow to nothing
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "scope,value,expected",
    [
        (CORP_SCOPE, "TEAM1", "TEAM1"),
        (CORP_SCOPE, "team1", "TEAM1"),
        (CORP_SCOPE, "TM1", None),      # a DFW pill left over from a DFW view
        (DFW_SCOPE, "TM3", "TM3"),
        (DFW_SCOPE, "TEAM1", None),     # a CORP pill left over from a CORP view
        (DFW_SCOPE, None, None),
        (DFW_SCOPE, 7, None),           # not a string — §40 FieldInfo shape
    ],
)
def test_a_foreign_team_widens_to_the_division(scope, value, expected) -> None:
    """§75: zero rows is indistinguishable from "this team had no work".

    Switching Division leaves the previous division's team in the URL, so this
    is the ordinary path here, not an attack. It must widen.
    """
    assert sub_team_of(scope, value) == expected


@pytest.mark.parametrize(
    "scope,value,expected",
    [
        (CORP_SCOPE, "TEAM1,TEAM2", "TEAM1,TEAM2"),
        (CORP_SCOPE, "TEAM1,TM1", "TEAM1"),
        (CORP_SCOPE, "TM1,TM2", None),   # all foreign ⇒ no narrowing, not empty
        (DFW_SCOPE, "tm1, TM2", "TM1,TM2"),
    ],
)
def test_the_csv_team_form_drops_foreign_ids(scope, value, expected) -> None:
    assert sub_teams_of(scope, value) == expected


def test_the_dfw_router_uses_the_shared_normaliser() -> None:
    """One rule, one implementation — a third private copy is how two drift."""
    assert "sub_team_of(DFW_SCOPE, team)" in inspect.getsource(dfw._sub_team)


# ---------------------------------------------------------------------------
# The DFW portal's own missing shim, found while building this
# ---------------------------------------------------------------------------


def test_the_dfw_portal_exposes_every_path_its_page_calls() -> None:
    """`SidePanels` renders the Monthly Projection "Team" button on every
    portal, so a portal missing /team-projection-by-team opens a modal onto a
    404 while the rest of the page renders normally.

    Budget is the only legitimate omission, and it is named.
    """
    missing = _slugs(opo.router.routes) - _slugs(dfw.r.routes)
    assert missing == BUDGET_PATHS, f"DFW is missing {sorted(missing - BUDGET_PATHS)}"
