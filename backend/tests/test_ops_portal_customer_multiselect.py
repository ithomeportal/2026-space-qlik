"""Bruno PDF 2026-10-16 R2 — the ops-portal Customer filter is a MULTI-select.

All 7 portals (CORP, T1-T4, DFW, Executive OPS) share one filter object, so
``customer`` is now ``Optional[List[str]]`` on every endpoint of the family and
every customer predicate renders ``= ANY($n)`` over ONE bound list.

What these tests pin:

1. a 2-name list renders ``= ANY($n)`` and binds the list verbatim — names
   contain commas, so a split anywhere would scope to fragments;
2. ``None`` / ``[]`` / ``[""]`` mean "All" — no customer predicate at all,
   never "match nothing";
3. every wrapper (T1-T4 clones, the DFW division copy, the Executive OPS
   dispatcher under corp / dfw / all) forwards the list UNCHANGED down to SQL
   — a wrapper that dropped or stringified it would silently unfilter (§40);
4. the frontend serialises ``customer`` with repeated ``append`` keys, never
   ``set`` or a comma-join (§45).
"""

from __future__ import annotations

import asyncio
import inspect
import pathlib
import re
import types

import pytest

import test_ceo_executive_portal as base
from app.routers import ops_portal_overview as opo
from app.routers import ops_portal_overview_ceo as ceo
from app.routers import ops_portal_overview_dfw as dfw
from app.routers import ops_portal_overview_team as team_mod
from app.routers.ops_portal_overview import _sql
from app.routers.ops_portal_overview._scope import DFW_SCOPE

PICK = ["ACME, INC.", "KOHLER CO MONTERREY"]
_CUST_COL = re.compile(r'(customer_name|"Customer Name") = ANY\(\$(\d+)\)')


# ---------------------------------------------------------------------------
# 1 + 2 — the shared predicate
# ---------------------------------------------------------------------------


def test_a_multi_customer_list_renders_any_and_binds_the_list() -> None:
    params: list = []
    where = _sql._v4_scope_where("br4", None, PICK, None, params)
    m = re.search(r"br4\.customer_name = ANY\(\$(\d+)\)", where)
    assert m, where
    assert params[int(m.group(1)) - 1] == PICK


@pytest.mark.parametrize("empty", [None, [], [""], ["", "   "], ()])
def test_an_empty_selection_emits_no_customer_predicate(empty) -> None:
    params: list = []
    where = _sql._v4_scope_where("br4", None, empty, None, params)
    assert "customer_name = " not in where
    # Only the 3 division arrays are bound — nothing for the customer.
    assert len(params) == 3


def test_the_normaliser_keeps_names_verbatim_and_drops_blanks() -> None:
    assert _sql._customer_list(None) is None
    assert _sql._customer_list([]) is None
    assert _sql._customer_list(["", " "]) is None
    # A bare string is ONE name, not its characters.
    assert _sql._customer_list("ACME, INC.") == ["ACME, INC."]
    # Order kept, duplicates collapsed, no trimming of a real name.
    assert _sql._customer_list(["B", "", "A", "B"]) == ["B", "A"]
    # The truthy Query(None) default a plain-Python caller binds = no filter.
    assert _sql._customer_list(inspect.signature(opo.actuals).parameters["customer"].default) is None


def test_every_leg_of_the_package_goes_through_the_shared_helper() -> None:
    """A leg that kept ``customer_name = $n`` would bind a LIST to a scalar."""
    pkg = pathlib.Path(_sql.__file__).parent
    for f in pkg.glob("*.py"):
        src = f.read_text()
        assert not re.search(r"append\(customer\)", src), f"{f.name} binds customer raw"
        assert not re.search(r'[Cc]ustomer[ _]?[Nn]ame"? = \$\{', src), f"{f.name}: scalar customer match"


def test_the_history_strip_treats_a_blank_selection_as_unfiltered() -> None:
    src = inspect.getsource(opo.team_projection_history)
    assert "_customer_list(customer)" in src


# ---------------------------------------------------------------------------
# 3 — wrappers forward the list unchanged
# ---------------------------------------------------------------------------


def _bound_customer_lists(pool) -> list:
    out = []
    for sql, params in pool.calls:
        for m in _CUST_COL.finditer(sql):
            out.append(params[int(m.group(2)) - 1])
    return out


def _drive_plain(fn, scope=None, **overrides):
    """Drive a CORP-team / DFW wrapper as FastAPI would (no division segment)."""
    pool = base._StubPool()
    undo = base._patch_pools(pool)
    base._meta._freshness_cache["at"] = None
    state = types.SimpleNamespace()
    if scope is not None:
        state.opp_scope = scope
    request = types.SimpleNamespace(
        app=types.SimpleNamespace(state=types.SimpleNamespace()), state=state,
    )
    kwargs = {}
    for name, p in inspect.signature(fn).parameters.items():
        if name == "request":
            kwargs[name] = request
        elif name in ("_user", "user"):
            kwargs[name] = {}
        else:
            v = getattr(p.default, "default", p.default)
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


def _customer_routes(router):
    return [
        (r.path.rsplit("/", 1)[-1], r.endpoint)
        for r in router.routes
        if "customer" in inspect.signature(r.endpoint).parameters
    ]


def _assert_forwarded(label: str, pool) -> None:
    bound = _bound_customer_lists(pool)
    assert bound, f"{label}: no customer predicate reached the SQL"
    assert all(b == PICK for b in bound), f"{label}: bound {bound!r}, expected {PICK!r}"


@pytest.mark.parametrize("slug,fn", _customer_routes(team_mod.team_routers[0]),
                         ids=lambda v: v if isinstance(v, str) else "")
def test_the_team_clone_forwards_the_list(slug: str, fn) -> None:
    _assert_forwarded(f"team/{slug}", _drive_plain(fn, customer=list(PICK)))


@pytest.mark.parametrize("slug,fn", _customer_routes(dfw.r),
                         ids=lambda v: v if isinstance(v, str) else "")
def test_the_dfw_copy_forwards_the_list(slug: str, fn) -> None:
    _assert_forwarded(f"dfw/{slug}", _drive_plain(fn, scope=DFW_SCOPE, customer=list(PICK)))


@pytest.mark.parametrize("division", ["corp", "dfw", "all"])
@pytest.mark.parametrize("slug,fn", _customer_routes(ceo.r),
                         ids=lambda v: v if isinstance(v, str) else "")
def test_the_executive_dispatcher_forwards_the_list(slug: str, fn, division: str) -> None:
    if division != "corp" and slug in base.BUDGET_PATHS:
        pytest.skip(f"{slug} is budget-only — 404s under {division}")
    _assert_forwarded(f"ceo/{division}/{slug}",
                      base._drive(fn, division=division, customer=list(PICK)))


# ---------------------------------------------------------------------------
# 4 — the frontend wire format
# ---------------------------------------------------------------------------

_API_TS = (pathlib.Path(__file__).resolve().parents[2]
           / "frontend" / "lib" / "ops-portal-overview-api.ts")


def test_the_frontend_appends_one_customer_key_per_name() -> None:
    src = _API_TS.read_text()
    assert re.search(r"""\.append\(\s*["']customer["']""", src), \
        "customer must go out as repeated keys via .append"
    assert not re.search(r"""\.set\(\s*["']customer["']""", src), \
        ".set('customer', …) keeps only ONE name"
    assert not re.search(r"customers?\??\.join\(", src), \
        "never comma-join customers — names contain commas"
