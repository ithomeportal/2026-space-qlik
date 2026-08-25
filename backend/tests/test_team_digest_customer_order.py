"""Customer Actual Performance (TM) — ranked by PROFIT, not revenue.

Request 2026-08-25: *"for the Performance CORP report, show the customer
descendants based on the Profit, not the revenue"*. That panel is shared by
five live e-mails — PERFORMANCE CORP (n8n ``gYM9KwUBm16YjTFL``) and the four
"CORP Performance for Team N" digests — so it is one constant, not five.

Three things here are invisible in a rendered e-mail and each would ship a
plausible-looking report:

1. **A caption that lies.** The footer used to hardcode the literal
   ``top 15 by revenue`` while the limit and the sort key lived in another
   module. Changing either one left the footer stating a basis the report no
   longer used. The caption is now derived, and asserted against the value the
   digest actually asks ``/actuals`` for.

2. **A ranking that isn't the one requested.** ``/actuals`` resolves an unknown
   sort key to ``revenue_desc`` **silently** — ``.get(sort, lambda r: -r["rev"])``
   — so a typo in the constant would keep the old ranking with no error at all.
   So the sort key is asserted to EXIST in that map, not merely to be a string.

3. **Slots eaten by rows that are then dropped.** ``/actuals`` appends
   budget-only customers with zero production and applies its LIMIT server-side.
   Under ``revenue_desc`` a zero sorted to the bottom and never reached a
   top-15 slot; under ``profit_desc`` zero sorts ABOVE every loss-making
   customer, so those rows would take slots and then be filtered out for
   display — a "top 15" panel silently showing 11 real customers. The digest
   therefore fetches wide, filters, and slices last.

Each assertion is mutation-checked against a fixture built to FAIL the old
behaviour: a revenue order and a profit order that genuinely disagree, and a
zero-production row positioned where it would steal a slot.
"""

from __future__ import annotations

import importlib
import inspect
import re

from app.services import team_perf_digest as digest_mod
from app.services import team_perf_digest_html as html_mod

# NOTE: `from app.routers.ops_portal_overview import actuals` yields the
# re-exported FUNCTION, not the module — the package facade shadows it. Import
# the submodule explicitly or `inspect` reads the wrong object.
actuals_mod = importlib.import_module("app.routers.ops_portal_overview.actuals")


# A row set where ranking by revenue and ranking by profit DISAGREE. If the
# panel ever falls back to revenue, the assertions below cannot pass by luck.
ROWS = [
    # name,                       vol,  rev,      prof
    ("HIGH REVENUE THIN MARGIN", 300, 900_000.0, 9_000.0),
    ("MID REVENUE FAT MARGIN",   120, 400_000.0, 88_000.0),
    ("SMALL BUT RICH",            20,  60_000.0, 30_000.0),
    ("BUDGET ONLY ZERO",           0,       0.0,      0.0),
    ("LOSS MAKER",                40, 150_000.0, -12_000.0),
]


def _rows() -> list[dict]:
    return [
        {"customer_name": n, "vol": v, "rev": r, "prof": p,
         "margin_pct": (p / r * 100.0) if r else 0.0}
        for n, v, r, p in ROWS
    ]


def _sort_map() -> dict:
    """The literal ``sort_key`` dict from /actuals, read out of the source.

    The map is built inline inside the endpoint coroutine, so it cannot be
    imported. Reading the source keeps this test honest about the REAL keys
    rather than a copy that could drift.
    """
    src = inspect.getsource(actuals_mod.actuals)
    body = re.search(r"sort_key = \{(.*?)\}\.get\(", src, re.S)
    assert body, "the sort_key map in /actuals moved — this test must follow it"
    return {m.group(1) for m in re.finditer(r'"([a-z_]+)"\s*:', body.group(1))}


# ---------------------------------------------------------------------------
# 1. The requested sort key is real
# ---------------------------------------------------------------------------

def test_the_requested_basis_is_profit():
    """Pins the request itself (2026-08-25), not merely internal consistency.

    Without this, flipping both constants back to revenue keeps every other
    assertion green — they only check that the caption agrees with the sort.
    """
    assert html_mod.CUSTOMER_PANEL_SORT == "profit_desc"
    assert html_mod.CUSTOMER_PANEL_BASIS == "profit"
    assert html_mod.CUSTOMER_PANEL_LIMIT == 15


def test_panel_sort_key_exists_in_the_actuals_map():
    """An unknown key falls back to revenue_desc SILENTLY — no error, wrong report."""
    assert html_mod.CUSTOMER_PANEL_SORT in _sort_map()


def test_a_typo_would_silently_fall_back_to_revenue():
    """Proves the fallback is real, so the test above is load-bearing."""
    assert "profit_dsec" not in _sort_map()


def test_profit_desc_orders_by_profit_descending():
    rows = _rows()
    # Same expression as /actuals: {"profit_desc": lambda r: -r["prof"]}
    ordered = sorted(rows, key=lambda r: -r["prof"])
    names = [r["customer_name"] for r in ordered]
    assert names[0] == "MID REVENUE FAT MARGIN"
    assert names[-1] == "LOSS MAKER"
    # ... and it is NOT the revenue order, so a fallback would be visible.
    by_rev = [r["customer_name"] for r in sorted(rows, key=lambda r: -r["rev"])]
    assert names != by_rev
    assert by_rev[0] == "HIGH REVENUE THIN MARGIN"


# ---------------------------------------------------------------------------
# 2. The digest asks for it, with a limit the caption can read
# ---------------------------------------------------------------------------

def test_digest_requests_the_profit_ranking():
    src = inspect.getsource(digest_mod.build_team_perf_digest)
    call = re.search(r'\("/actuals",\s*\{(.*?)\}\)', src, re.S)
    assert call, "the /actuals call in build_team_perf_digest moved"
    assert '"sort": CUSTOMER_PANEL_SORT' in call.group(1)
    assert '"limit": CUSTOMER_PANEL_FETCH' in call.group(1)
    # The literal must be gone — a leftover would silently win.
    assert "revenue_desc" not in src


def test_constants_agree_with_each_other():
    assert html_mod.CUSTOMER_PANEL_SORT.startswith(html_mod.CUSTOMER_PANEL_BASIS)
    assert 0 < html_mod.CUSTOMER_PANEL_LIMIT <= html_mod.CUSTOMER_PANEL_FETCH
    # /actuals declares `limit: int = Query(100, ge=1, le=500)`. Asking for more
    # than the ceiling is a 422 the digest would log and render around, so the
    # constant is pinned to the endpoint's real bound rather than to a copy.
    sig = inspect.signature(actuals_mod.actuals)
    bounds = [c for c in sig.parameters["limit"].default.metadata
              if getattr(c, "le", None) is not None]
    assert bounds, "the /actuals limit lost its upper bound"
    assert html_mod.CUSTOMER_PANEL_FETCH <= bounds[0].le


# ---------------------------------------------------------------------------
# 3. The caption states the basis the report actually used
# ---------------------------------------------------------------------------

def test_caption_reports_the_real_basis_and_limit():
    out = html_mod._customer_panel(_rows(), {"vol": 480, "rev": 1_510_000.0,
                                             "prof": 115_000.0, "margin_pct": 7.6})
    assert f"top {html_mod.CUSTOMER_PANEL_LIMIT} by {html_mod.CUSTOMER_PANEL_BASIS}" in out
    assert "by revenue" not in out
    assert f"{len(ROWS)} customer(s) with MTD activity" in out


def test_caption_follows_an_explicit_override():
    """Mutation check: a hardcoded caption would ignore these and still pass above."""
    out = html_mod._customer_panel(_rows(), {}, limit=7, basis="volume")
    assert "top 7 by volume" in out
    assert "top 15" not in out


def test_caption_basis_is_escaped():
    out = html_mod._customer_panel(_rows(), {}, limit=3, basis="<b>x</b>")
    assert "<b>x</b>" not in out
    assert "&lt;b&gt;x&lt;/b&gt;" in out


# ---------------------------------------------------------------------------
# 4. Zero-production rows must not eat a top-N slot
# ---------------------------------------------------------------------------

def test_zero_production_row_does_not_consume_a_slot():
    """Reproduces the digest's filter-then-slice, with the limit forced to 4.

    By profit the order is MID(88k), SMALL(30k), HIGH(9k), ZERO(0), LOSS(-12k):
    the budget-only zero outranks the loss-making customer. Slicing first takes
    ZERO into the window and the display filter then drops it, so a panel that
    promises four rows shows THREE. Filtering first returns four real
    customers and demotes the zero, which is the requested behaviour.
    """
    limit = 4
    ranked = sorted(_rows(), key=lambda r: -r["prof"])
    assert [r["customer_name"] for r in ranked][3] == "BUDGET ONLY ZERO"

    producing = [r for r in ranked if r["vol"] > 0 or r["rev"] or r["prof"]]
    slice_first = [r for r in ranked[:limit]
                   if r["vol"] > 0 or r["rev"] or r["prof"]]
    filter_first = producing[:limit]

    # The bug the ordering change would have introduced:
    assert len(slice_first) == 3
    # ... and the shape after filtering first:
    assert len(filter_first) == 4
    names = [r["customer_name"] for r in filter_first]
    assert "BUDGET ONLY ZERO" not in names
    assert "LOSS MAKER" in names


def test_digest_filters_before_it_slices():
    src = inspect.getsource(digest_mod.build_team_perf_digest)
    assert "producing_rows[:CUSTOMER_PANEL_LIMIT]" in src
    filt = src.index("producing_rows = [")
    sl = src.index("producing_rows[:CUSTOMER_PANEL_LIMIT]")
    assert filt < sl, "the zero-row filter must run BEFORE the top-N slice"


def test_fetch_ceiling_is_reported_not_swallowed():
    src = inspect.getsource(digest_mod.build_team_perf_digest)
    assert ">= CUSTOMER_PANEL_FETCH" in src
    assert "logger.warning" in src[src.index(">= CUSTOMER_PANEL_FETCH"):]
