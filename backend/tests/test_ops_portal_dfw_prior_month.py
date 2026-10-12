"""Ops Managers Portal – DFW: Actuals vs the same days of the previous month.

Bruno PDF "space -- Ops Portal DFW" (2026-10-12), Request 1: the Actuals table
gets All / Actuals / Variances. "All" shows the current value on top, the
previous month's value over the SAME days bottom-left (10-01..10-12 compares
with 09-01..09-12), the variance (current − previous) bottom-right and
current ÷ previous beside it.

What these pin:
  * the window arithmetic, incl. month-end → month-end and no YEAR_START clamp;
  * the previous leg counts the SAME population as the current one (same
    where-builder params, same Losses / Unbilled clauses — §96);
  * variance sign, previous-only customers, and a TOTAL that sums the rows;
  * an MTD window ALSO gets the previous month WHOLE (``*_prev_full``) — user
    2026-10-12: "what is missing to the end of the month" — same population;
  * DFW gets it pinned server-side, while CORP / CEO keep the exact payload
    they had (no previous statement, no ``*_prev`` keys).
"""

from __future__ import annotations

import asyncio
import importlib
import pathlib
import re
from datetime import date
from types import SimpleNamespace

import pytest

from app.routers import ops_portal_overview as opo
from app.routers import ops_portal_overview_ceo as ceo
from app.routers import ops_portal_overview_dfw as dfw
from app.routers.ops_portal_overview import _prior_month
from app.routers.ops_portal_overview._scope import CORP_SCOPE, DFW_SCOPE

# ⚠ Not `from … import actuals`: the package façade re-exports the FUNCTION
# `actuals`, which shadows the submodule of the same name.
actuals_mod = importlib.import_module("app.routers.ops_portal_overview.actuals")

FRONTEND = pathlib.Path(__file__).resolve().parents[2] / "frontend"
PREV_TAG = "/*prior-month-leg*/"


# ---------------------------------------------------------------------------
# The window
# ---------------------------------------------------------------------------


_FAR = date(2026, 12, 31)  # a "today" after every window below: no cap applies


@pytest.mark.parametrize(
    "start,end,today,want",
    [
        # Bruno's own example (MTD on 10-12).
        (date(2026, 10, 1), date(2026, 10, 12), date(2026, 10, 12), (date(2026, 9, 1), date(2026, 9, 12))),
        # "This Month" resolves to 10-01..10-31 — capped at today, it is still
        # the SAME days, not the whole of September (code review 2026-10-12).
        (date(2026, 10, 1), date(2026, 10, 31), date(2026, 10, 12), (date(2026, 9, 1), date(2026, 9, 12))),
        # "Yesterday" — a one-day window stays one day.
        (date(2026, 10, 11), date(2026, 10, 11), date(2026, 10, 12), (date(2026, 9, 11), date(2026, 9, 11))),
        # A one-day window ON a month-end is day-for-day: Sep 30 → Aug 30.
        (date(2026, 9, 30), date(2026, 9, 30), date(2026, 10, 1), (date(2026, 8, 30), date(2026, 8, 30))),
        # A partial window ending on a month-end is day-for-day too.
        (date(2026, 9, 15), date(2026, 9, 30), _FAR, (date(2026, 8, 15), date(2026, 8, 30))),
        # A WHOLE month compares with a whole month: Sep 1-30 → Aug 1-31.
        (date(2026, 9, 1), date(2026, 9, 30), _FAR, (date(2026, 8, 1), date(2026, 8, 31))),
        # A full 28-day February → the whole of January.
        (date(2026, 2, 1), date(2026, 2, 28), _FAR, (date(2026, 1, 1), date(2026, 1, 31))),
        # A day the previous month does not have clamps to its last day.
        (date(2026, 3, 1), date(2026, 3, 30), _FAR, (date(2026, 2, 1), date(2026, 2, 28))),
        # ⚠ NOT clamped to YEAR_START — v4 holds December 2025.
        (date(2026, 1, 1), date(2026, 1, 12), _FAR, (date(2025, 12, 1), date(2025, 12, 12))),
    ],
)
def test_prior_month_window(start: date, end: date, today: date, want: tuple[date, date]) -> None:
    assert _prior_month.prior_month_window(start, end, today) == want


@pytest.mark.parametrize(
    "start,end,today,want",
    [
        # MTD on 10-12 → the whole of September.
        (date(2026, 10, 1), date(2026, 10, 12), date(2026, 10, 12), (date(2026, 9, 1), date(2026, 9, 30))),
        # "This Month" (10-01..10-31) is MTD once capped at today.
        (date(2026, 10, 1), date(2026, 10, 31), date(2026, 10, 12), (date(2026, 9, 1), date(2026, 9, 30))),
        # March MTD → the whole 28-day February, never "Feb 1-30".
        (date(2026, 3, 1), date(2026, 3, 10), date(2026, 3, 10), (date(2026, 2, 1), date(2026, 2, 28))),
        # January MTD → December 2025 (no YEAR_START clamp).
        (date(2026, 1, 1), date(2026, 1, 12), date(2026, 1, 12), (date(2025, 12, 1), date(2025, 12, 31))),
        # Multi-month window ending mid-month → whole months behind it.
        (date(2026, 9, 1), date(2026, 10, 12), date(2026, 10, 12), (date(2026, 8, 1), date(2026, 9, 30))),
        # A whole month already compares whole months — no second leg.
        (date(2026, 9, 1), date(2026, 9, 30), _FAR, None),
        # The last day of the month: MTD IS the whole month.
        (date(2026, 10, 1), date(2026, 10, 31), date(2026, 10, 31), None),
        # A mid-month start has no month-end target.
        (date(2026, 10, 5), date(2026, 10, 12), date(2026, 10, 12), None),
        (date(2026, 10, 11), date(2026, 10, 11), date(2026, 10, 12), None),
    ],
)
def test_full_month_window(start: date, end: date, today: date, want) -> None:
    assert _prior_month.full_month_window(start, end, today) == want


# ---------------------------------------------------------------------------
# Harness — a pool that answers the two legs and records every statement
# ---------------------------------------------------------------------------

_CURRENT = [
    {"customer_name": "ALPHA", "vol": 10, "rev": 1000, "prof": 100, "otp_late": 0, "otd_late": 0},
    {"customer_name": "BRAVO", "vol": 5, "rev": 500, "prof": -50, "otp_late": 0, "otd_late": 0},
]
_PREVIOUS = [
    {"customer_name": "ALPHA", "vol": 20, "rev": 1500, "prof": 300},
    # Shipped last month, nothing this month — must still be a row.
    {"customer_name": "CHARLIE", "vol": 4, "rev": 400, "prof": 40},
]
_FULL = [  # the whole previous month — a superset of _PREVIOUS
    {"customer_name": "ALPHA", "vol": 50, "rev": 4000, "prof": 600},
    {"customer_name": "CHARLIE", "vol": 9, "rev": 900, "prof": 90},
    # Shipped only in Sep 13-30 — in neither of the other legs.
    {"customer_name": "DELTA", "vol": 3, "rev": 300, "prof": 30},
]
_FULL_END = date(2026, 9, 30)


class _Pool:
    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple]] = []

    async def fetch(self, sql, *params):
        self.calls.append((sql, params))
        if sql.startswith(PREV_TAG):
            return _FULL if params[-1] == _FULL_END else _PREVIOUS
        if "WITH otp AS" in sql:
            return _CURRENT
        return []

    async def fetchrow(self, sql, *params):
        self.calls.append((sql, params))
        return None


async def _no_projection(*_a, **_kw):
    return {"avg_vol_day": 0, "avg_prof_day": 0, "proj_volume": 0, "proj_profit": 0}


@pytest.fixture
def pool(monkeypatch):
    p = _Pool()
    monkeypatch.setattr(actuals_mod, "get_datalake_gold_pool", lambda request: p)
    monkeypatch.setattr(actuals_mod, "_team_projection_core", _no_projection)
    real = _prior_month.prior_month_sql
    monkeypatch.setattr(actuals_mod, "prior_month_sql", lambda *a: PREV_TAG + real(*a))
    return p


def _request(scope):
    state = SimpleNamespace()
    if scope is not CORP_SCOPE:
        state.opp_scope = scope
    return SimpleNamespace(state=state, app=SimpleNamespace(state=SimpleNamespace()),
                           query_params={})


_FILTERS = dict(
    team=None, range="custom", start_date=date(2026, 10, 1), end_date=date(2026, 10, 12),
    customer=None, load_type=None, lanes=None, exclude_lanes=None,
    carriers=None, exclude_carriers=None, sort="revenue_desc", limit=200,
    losses_only=False, unbilled_only=False,
)


def _dfw(**over):
    kw = {**_FILTERS, **over}
    return asyncio.run(dfw.actuals(request=_request(DFW_SCOPE), _user={}, **kw))


def _prev_calls(pool):
    """The same-days leg (the whole-month leg is ``_full_calls``)."""
    return [(s, p) for s, p in pool.calls if s.startswith(PREV_TAG) and p[-1] != _FULL_END]


def _full_calls(pool):
    return [(s, p) for s, p in pool.calls if s.startswith(PREV_TAG) and p[-1] == _FULL_END]


def _cur_calls(pool):
    return [(s, p) for s, p in pool.calls if "WITH otp AS" in s]


# ---------------------------------------------------------------------------
# DFW — the comparison leg
# ---------------------------------------------------------------------------


def test_dfw_queries_the_same_days_of_the_previous_month(pool) -> None:
    out = _dfw()
    (_, prev_params), = _prev_calls(pool)
    (_, cur_params), = _cur_calls(pool)
    assert cur_params[-2:] == (date(2026, 10, 1), date(2026, 10, 12))
    assert prev_params[-2:] == (date(2026, 9, 1), date(2026, 9, 12))
    assert out["meta"]["compare"] == {
        "basis": "prior_month", "start": "2026-09-01", "end": "2026-09-12",
        "full_start": "2026-09-01", "full_end": "2026-09-30",
    }
    (_, full_params), = _full_calls(pool)
    assert full_params[-2:] == (date(2026, 9, 1), _FULL_END)


def test_variance_is_current_minus_previous(pool) -> None:
    rows = {r["customer_name"]: r for r in _dfw()["data"]}
    a = rows["ALPHA"]
    assert (a["vol_prev"], a["vol_vs_prev"]) == (20, -10)
    assert (a["rev_prev"], a["rev_vs_prev"]) == (1500, -500)
    assert (a["prof_prev"], a["prof_vs_prev"]) == (300, -200)
    # Margin variance is in percentage POINTS: 10% − 20% = −10.
    assert a["margin_prev_pct"] == pytest.approx(20.0)
    assert a["margin_vs_prev_pct"] == pytest.approx(-10.0)
    # No previous activity ⇒ the whole current value is the variance.
    b = rows["BRAVO"]
    assert (b["vol_prev"], b["vol_vs_prev"], b["prof_vs_prev"]) == (0, 5, -50)


def test_a_previous_only_customer_is_a_row(pool) -> None:
    rows = {r["customer_name"]: r for r in _dfw()["data"]}
    c = rows["CHARLIE"]
    assert (c["vol"], c["vol_prev"], c["vol_vs_prev"]) == (0, 4, -4)
    assert (c["prof"], c["prof_vs_prev"]) == (0.0, -40)


def test_the_total_is_the_sum_of_the_rows(pool) -> None:
    out = _dfw()
    t, rows = out["meta"]["totals"], out["data"]
    for k in ("vol", "rev", "prof", "vol_prev", "rev_prev", "prof_prev",
              "vol_vs_prev", "rev_vs_prev", "prof_vs_prev"):
        assert t[k] == pytest.approx(sum(r[k] for r in rows)), k
    # The TOTAL margin is Σprofit ÷ Σrevenue, never a mean of row margins.
    assert t["margin_prev_pct"] == pytest.approx(340 / 1900 * 100)
    assert t["margin_vs_prev_pct"] == pytest.approx(50 / 1500 * 100 - 340 / 1900 * 100)
    # ALPHA, BRAVO, CHARLIE + DELTA (whole-month leg only).
    assert out["meta"]["total"] == 4


@pytest.mark.parametrize(
    "over,clause",
    [
        ({"losses_only": True}, "br4.margin_amt < 0"),
        ({"unbilled_only": True}, "br4.bill_date < '2000-01-01'::date"),
    ],
)
def test_both_legs_count_one_population(pool, over, clause) -> None:
    """§96: a filter on one leg only would compare two different load sets."""
    _dfw(carriers=["CARRIER X"], team="TM2", **over)
    (cur_sql, cur_params), = _cur_calls(pool)
    for leg in (_prev_calls(pool), _full_calls(pool)):
        (prev_sql, prev_params), = leg
        assert clause in prev_sql and clause in cur_sql
        # Same where-builder output: every bound filter value identical.
        assert prev_params[:-2] == cur_params[:-2]
        # Same COUNT definition as the current leg's `vol`.
        assert "total_charge IS NOT NULL AND br4.total_charge <> 0" in prev_sql


# ---------------------------------------------------------------------------
# MTD — the previous month WHOLE (user 2026-10-12)
# ---------------------------------------------------------------------------


def test_mtd_gap_to_the_whole_previous_month(pool) -> None:
    rows = {r["customer_name"]: r for r in _dfw()["data"]}
    a = rows["ALPHA"]
    # Current 10 / $1000 vs Sep whole 50 / $4000: 40 loads still missing.
    assert (a["vol_prev_full"], a["vol_vs_prev_full"]) == (50, -40)
    assert (a["rev_prev_full"], a["rev_vs_prev_full"]) == (4000, -3000)
    assert a["margin_prev_full_pct"] == pytest.approx(15.0)
    # Both legs live side by side on one row.
    assert (a["vol_prev"], a["vol_vs_prev"]) == (20, -10)
    # A customer with no Sep activity at all has zero in the full leg too.
    assert rows["BRAVO"]["vol_prev_full"] == 0


def test_a_full_month_only_customer_is_a_row_with_every_leg(pool) -> None:
    d = {r["customer_name"]: r for r in _dfw()["data"]}["DELTA"]
    assert (d["vol"], d["vol_prev"], d["vol_prev_full"], d["vol_vs_prev_full"]) == (0, 0, 3, -3)
    assert d["margin_vs_prev_pct"] == 0.0


def test_the_full_total_is_the_sum_of_the_rows(pool) -> None:
    out = _dfw()
    t, rows = out["meta"]["totals"], out["data"]
    for k in ("vol_prev_full", "rev_prev_full", "prof_prev_full",
              "vol_vs_prev_full", "rev_vs_prev_full", "prof_vs_prev_full",
              "vol_prev", "vol_vs_prev"):
        assert t[k] == pytest.approx(sum(r[k] for r in rows)), k
    assert t["margin_prev_full_pct"] == pytest.approx(720 / 5200 * 100)
    assert out["meta"]["total"] == 4


@pytest.mark.parametrize(
    "start,end",
    [(date(2026, 9, 1), date(2026, 9, 30)), (date(2026, 10, 5), date(2026, 10, 12))],
)
def test_no_full_leg_outside_mtd(pool, start, end) -> None:
    out = _dfw(start_date=start, end_date=end)
    assert len([c for c in pool.calls if c[0].startswith(PREV_TAG)]) == 1
    assert out["meta"]["compare"]["full_start"] is None
    assert not any("_prev_full" in k for r in out["data"] for k in r)
    assert not any("_prev_full" in k for k in out["meta"]["totals"])


# ---------------------------------------------------------------------------
# Everyone else keeps the budget payload, unchanged
# ---------------------------------------------------------------------------


def test_corp_and_ceo_emit_no_previous_leg(pool) -> None:
    kw = {k: v for k, v in _FILTERS.items()}
    corp = asyncio.run(opo.actuals(request=_request(CORP_SCOPE), teams=None,
                                   compare="budget", _user={}, **kw))
    for div_scope in (CORP_SCOPE, DFW_SCOPE):
        asyncio.run(ceo.actuals(request=_request(div_scope), teams=None,
                                compare="budget", _user={}, **kw))
    assert _prev_calls(pool) == []
    assert "compare" not in corp["meta"]
    assert not any(k.endswith("_prev") or "_vs_prev" in k
                   for r in corp["data"] for k in r)
    assert not any("_prev" in k for k in corp["meta"]["totals"])


def test_dfw_pins_the_comparison_server_side() -> None:
    """Not a client param on the DFW router: it is a property of the report."""
    import inspect

    assert "compare" not in inspect.signature(dfw.actuals).parameters
    src = inspect.getsource(dfw.actuals)
    assert 'compare="prior_month"' in src


def test_every_direct_caller_passes_compare_explicitly() -> None:
    """§40: a direct Python call never applies the Query() default."""
    import inspect

    from app.routers import ops_portal_overview_team as team

    for mod in (dfw, ceo, team):
        src = inspect.getsource(mod)
        for call in re.findall(r"opo\.actuals\((.*?)\n\s*\)", src, re.S):
            assert "compare=" in call, f"{mod.__name__} calls opo.actuals without compare"


# ---------------------------------------------------------------------------
# The page wiring (no JS test runner — read the TSX)
# ---------------------------------------------------------------------------


def test_only_the_dfw_page_turns_it_on() -> None:
    dfw_page = (FRONTEND / "app/reports/ops-managers-portal-dfw/page.tsx").read_text()
    ceo_page = (FRONTEND / "app/reports/ceo-executive-portal/page.tsx").read_text()
    assert 'actualsCompare="prior_month"' in dfw_page
    assert "actualsCompare" not in ceo_page


def test_the_pills_bruno_named() -> None:
    src = (FRONTEND / "app/reports/ops-portal-overview/ActualsCells.tsx").read_text()
    for label in ('"All"', '"Actuals"', '"Variances"'):
        assert label in src, label
