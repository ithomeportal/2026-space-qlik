"""Bonus Calculator scopes — corporate unchanged, DFW isolated.

Bruno PDF "space --Bonus HR" (2026-08-20), Request 3.

This module computes real payroll. Two properties, both of which fail silently
rather than loudly:

  * **Corporate payouts must not have moved.** The refactor turned five module
    globals into a `BonusConfig`; the default is the corporate one, and a
    full-report baseline over inputs that straddle every bracket edge asserts
    the arithmetic is identical to the byte.

  * **The two calculators must not share a row.** `bonus_settings` and
    `bonus_period_lock` are primary-keyed on `period_key` ALONE and both write
    with `ON CONFLICT (period_key) DO UPDATE`. Had the DFW report reused them,
    HR pinning a DFW FX rate for 2026-08 would have overwritten the CORPORATE
    FX rate for 2026-08 — changing corporate payroll from a DFW page, with no
    error raised anywhere and no audit trail beyond `updated_by`.

⚠ The DFW ladder is not merely "lower". It starts at 15% against corporate's
18.5% AND tops out at 120% against 130%, so `bracket_pct_at_or_below` — which
maps the wildcard into the margin ladder — resolves differently at the top.
That is asserted rather than assumed.
"""

from __future__ import annotations

import inspect
import json
import re

import pytest

from app.routers import bonus_calculator as bc
from app.services import bonus_engine as be


# ---------------------------------------------------------------------------
# A deterministic report over inputs that straddle every bracket edge
# ---------------------------------------------------------------------------


def _team(i: int, loads: int, margin: float, service: float, profit: float) -> dict:
    weeks = [
        {
            "label": f"W{w + 1}",
            "loads": loads + w * 7,
            "marginPct": margin + w * 0.004,
            "servicePct": service + w * 0.003,
            "profitUsd": profit / 4 + w * 900,
        }
        for w in range(4)
    ]
    return {
        "id": f"team-{i}",
        "name": f"Team {i}",
        "weeks": weeks,
        "monthlyProfit": profit,
        "monthlyServicePct": service,
        "fxRate": 17.37,
        "employees": [
            {"name": f"KAM {i}", "role": "kam", "salaryMxn": 30000 + i * 1000},
            {"name": f"FM {i}", "role": "freight_match", "salaryMxn": 22000 + i * 500},
            {"name": f"TT {i}", "role": "tracking_tracing", "salaryMxn": 19000 + i * 400},
        ],
    }


# Margins 0.140 / 0.185 / 0.205 / 0.232 sit on or beside an edge in BOTH
# ladders, so a swapped config cannot come out equal by luck.
TEAMS = [
    _team(1, 96, 0.140, 0.938, 128000),
    _team(2, 104, 0.185, 0.952, 151000),
    _team(3, 131, 0.205, 0.966, 172000),
    _team(4, 158, 0.232, 0.991, 205000),
]
NIGHT = [
    {"name": "Night A", "shiftGroup": "night", "salaryMxn": 21000, "receivesBonus": True},
    {"name": "Weekend B", "shiftGroup": "weekend", "salaryMxn": 18000, "receivesBonus": False},
]


def _report(**kw) -> dict:
    return be.build_bonus_report(
        month="2026-08",
        source="test",
        mode="mcleod_tms",
        teams=json.loads(json.dumps(TEAMS)),
        night_shift_employees=json.loads(json.dumps(NIGHT)),
        night_fx_rate=16.89,
        last_sync_label="t",
        status_label="draft",
        **kw,
    )


# Captured from the pre-refactor engine on 2026-08-21 over the inputs above.
# ⚠ Do NOT regenerate this from the current code to make a failure go away —
# that is the one edit that turns this test into a tautology. A change here is
# a change to somebody's pay and needs HR sign-off (SPEC-BONUS-CALCULATOR §7).
CORP_BASELINE_GRAND_USD = 22122.4
CORP_BASELINE_NIGHT_USD = 605.9200000000001


def test_the_default_config_is_corporate_everywhere() -> None:
    """The default is what keeps live payroll identical through the refactor."""
    for fn in (
        be.calculate_profit_bracket_bonuses,
        be.get_wildcard_bracket_index,
        be.get_wildcard_load_count,
        be.get_wildcard_margin_threshold,
        be.calculate_wildcard_bonus,
        be.calculate_team1_kam_bonus,
        be.calculate_team_bonus,
        be.build_bonus_report,
    ):
        assert inspect.signature(fn).parameters["cfg"].default is be.CORP_BONUS, fn.__name__


def test_corporate_payouts_are_unchanged_by_the_refactor() -> None:
    """Byte-for-byte against the captured pre-refactor totals."""
    rep = _report()
    assert rep["totals"]["grandBonusUsd"] == CORP_BASELINE_GRAND_USD
    assert rep["nightShift"]["totalBonusUsd"] == CORP_BASELINE_NIGHT_USD


def test_the_corporate_ladders_still_read_from_the_module_constants() -> None:
    """`criteria` on the wire and the SPEC both reference these by name."""
    rep = _report()
    assert rep["criteria"]["marginBrackets"] is be.MARGIN_BRACKETS
    assert rep["criteria"]["loadCountBrackets"] is be.LOAD_COUNT_BRACKETS
    assert rep["criteria"]["serviceBrackets"] is be.SERVICE_BRACKETS
    assert rep["criteria"]["payPerLoad"] is be.PAY_PER_LOAD


# ---------------------------------------------------------------------------
# The DFW ladder
# ---------------------------------------------------------------------------


def test_the_dfw_margin_ladder_matches_the_pdf_exactly() -> None:
    """15/16/17/18/19% -> 70/90/100/110/120%, in that order."""
    got = [(b["threshold"], b["bonusPct"]) for b in be.DFW_BONUS.margin_brackets]
    assert got == [
        (0.15, 0.7),
        (0.16, 0.9),
        (0.17, 1.0),
        (0.18, 1.1),
        (0.19, 1.2),
    ]


def test_only_the_margin_ladder_differs_from_corporate() -> None:
    """The PDF changes one table; the rest must be shared, not copied."""
    assert be.DFW_BONUS.load_count_brackets is be.CORP_BONUS.load_count_brackets
    assert be.DFW_BONUS.service_brackets is be.CORP_BONUS.service_brackets
    assert be.DFW_BONUS.pay_per_load is be.CORP_BONUS.pay_per_load
    assert be.DFW_BONUS.monthly_profit_brackets is be.CORP_BONUS.monthly_profit_brackets
    assert be.DFW_BONUS.margin_brackets is not be.CORP_BONUS.margin_brackets


def test_the_dfw_ladder_actually_changes_the_payout() -> None:
    """Guards against a config that is wired up but never read."""
    corp = _report()
    dfw = _report(cfg=be.DFW_BONUS)
    assert dfw["totals"]["grandBonusUsd"] != corp["totals"]["grandBonusUsd"]
    assert dfw["criteria"]["marginBrackets"] is be.DFW_MARGIN_BRACKETS


def test_the_wildcard_maps_into_each_ladders_own_top() -> None:
    """The ceiling differs (120% vs 130%), not just the thresholds.

    `bracket_pct_at_or_below` drops a target % to the next available rung of
    the role's ladder, so a wildcard that resolves to 130% corporate has no
    rung at all in DFW and must fall to 120% — a difference that only shows at
    the top of the range, where a threshold-only test would miss it.
    """
    assert be.bracket_pct_at_or_below(1.3, be.CORP_BONUS.margin_brackets) == 1.3
    assert be.bracket_pct_at_or_below(1.3, be.DFW_BONUS.margin_brackets) == 1.2
    # ...and the floor differs too: 0.16 clears DFW's second rung, nothing corp.
    assert be.get_bracket_bonus(0.16, be.DFW_BONUS.margin_brackets) == 0.9
    assert be.get_bracket_bonus(0.16, be.CORP_BONUS.margin_brackets) == 0.0


# ---------------------------------------------------------------------------
# 🔴 Table isolation — the failure that would edit corporate payroll
# ---------------------------------------------------------------------------


_TABLE_FIELDS = ("tbl_roster", "tbl_afterhours", "tbl_settings", "tbl_lock", "tbl_history")


def test_no_table_is_shared_between_the_two_calculators() -> None:
    """bonus_settings / bonus_period_lock are PK'd on period_key ALONE.

    Sharing either one means a DFW FX pin or month lock for 2026-08 overwrites
    the CORPORATE one for 2026-08 — `ON CONFLICT (period_key) DO UPDATE`, no
    error, no second row. This is the assertion that matters most in the file.
    """
    corp = {getattr(bc.CORP_SCOPE, f) for f in _TABLE_FIELDS}
    dfw = {getattr(bc.DFW_SCOPE, f) for f in _TABLE_FIELDS}
    assert corp & dfw == set(), f"shared tables: {sorted(corp & dfw)}"
    assert len(corp) == len(_TABLE_FIELDS)
    assert len(dfw) == len(_TABLE_FIELDS)


def test_the_scopes_differ_in_report_key_and_url() -> None:
    """A shared gate would grant DFW users the corporate calculator."""
    assert bc.CORP_SCOPE.report_key == "bonus-calculator"
    assert bc.DFW_SCOPE.report_key == "bonus-calculator-dfw"
    assert bc.CORP_SCOPE.url_prefix != bc.DFW_SCOPE.url_prefix
    assert bc.CORP_SCOPE.teams != bc.DFW_SCOPE.teams


def test_every_sql_statement_names_its_scopes_table() -> None:
    """No bare `bonus_roster` may survive anywhere past the scope definitions.

    A literal table name that escaped the refactor would make the DFW router
    read and WRITE the corporate roster while every other endpoint looked
    correct.
    """
    src = inspect.getsource(bc)
    body = src[src.index("async def _load_roster") :]
    # Only lines that actually address a table — a prose mention of
    # `services/bonus_history.py` in a docstring is not a query.
    sql_ref = re.compile(
        r"\b(?:FROM|INTO|UPDATE)\s+(bonus_(?:roster|afterhours|settings|period_lock|history))\b"
    )
    for line in body.split("\n"):
        m = sql_ref.search(line)
        if m:
            assert False, f"literal {m.group(1)} at: {line.strip()[:80]}"
    # ...and the scoped form must actually be present, so this cannot pass by
    # the statements having disappeared.
    assert body.count("{scope.tbl_") >= 10


def test_the_history_job_is_scoped_and_defaults_to_corporate() -> None:
    """One snapshot per scope; a shared table would suppress the second.

    `finalize_due_periods` short-circuits on "is this period already stored?",
    so with a shared history table whichever scope ran first would make the
    scheduler skip the other for that month entirely.
    """
    from app.services import bonus_history as bh

    for fn in (bh.finalize_due_periods, bh.get_history):
        assert "scope" in inspect.signature(fn).parameters, fn.__name__
    src = inspect.getsource(bh)
    assert "{scope.tbl_history}" in src
    assert "FROM bonus_history" not in src
    assert "INSERT INTO bonus_history\n" not in src


def test_both_routers_are_registered_and_gated_separately() -> None:
    assert len(bc.BONUS_ROUTERS) == 2
    corp_paths = {r.path for r in bc.router.routes}
    dfw_paths = {r.path for r in bc.dfw_router.routes}
    assert corp_paths & dfw_paths == set()
    assert len(corp_paths) == len(dfw_paths)


@pytest.mark.parametrize("scope_key", ["corp", "dfw"])
def test_a_roster_row_cannot_carry_the_other_scopes_team_id(scope_key: str) -> None:
    """`RosterRow` validates against the CALLER'S scope, not a fixed list.

    A corporate team id accepted into the DFW roster would be invisible (the
    report only reads `scope.teams`) rather than wrong — harder to notice than
    a rejection.
    """
    from fastapi import HTTPException

    scope = bc.BONUS_SCOPES[scope_key]
    other = bc.BONUS_SCOPES["dfw" if scope_key == "corp" else "corp"]
    assert set(scope.teams) & set(other.teams) == set()

    ok = bc.RosterRow(team_id=scope.teams[0], name="X", role="kam", salary_mxn=1)
    ok.validate_domain(scope)  # must not raise

    crossed = bc.RosterRow(team_id=other.teams[0], name="X", role="kam", salary_mxn=1)
    with pytest.raises(HTTPException) as exc:
        crossed.validate_domain(scope)
    assert exc.value.status_code == 422


def test_the_app_schema_still_builds() -> None:
    """⚠ /openapi.json and /docs 500 while every endpoint still answers.

    Caught in production, not by this suite: moving the Pydantic request models
    inside the router factory made them local-scope classes, and under
    `from __future__ import annotations` FastAPI resolves a body annotation
    through a TypeAdapter that cannot see them — `PydanticUserError: not fully
    defined`. The endpoints kept returning their normal 422, so nothing looked
    wrong from the outside.

    Any request model must therefore stay at MODULE level. This asserts the
    property rather than the placement, so it also covers the next one.
    """
    from app.main import app

    schema = app.openapi()
    assert "paths" in schema
    assert any("bonus-calculator-dfw" in p for p in schema["paths"])
    assert any("ops-portal-overview-dfw" in p for p in schema["paths"])


def test_dfw_reads_the_dfw_division_not_corp_teams() -> None:
    """team_id='TEAM-DFW' + team='TMn', the same split the Ops Portal makes."""
    params: list = []
    where = bc.DFW_SCOPE.scope_where("br4", "dfw-tm-3", params)
    flat = where + json.dumps([list(p) if isinstance(p, list) else str(p) for p in params])
    assert "TEAM-DFW" in flat
    assert "TM3" in flat
    for corp_id in ("TEAM1", "TEAM2", "TEAM3", "TEAM4", "TEAM5"):
        assert corp_id not in flat

    corp_params: list = []
    corp_where = bc.CORP_SCOPE.scope_where("br4", "team-3", corp_params)
    corp_flat = corp_where + json.dumps(
        [list(p) if isinstance(p, list) else str(p) for p in corp_params]
    )
    assert "TEAM3" in corp_flat
    assert "TEAM-DFW" not in corp_flat


# ---------------------------------------------------------------------------
# 🔴 The scope must reach the WIRE, not just exist on the scope object
# ---------------------------------------------------------------------------
#
# Everything above asserts properties of `BonusScope` and of `bonus_engine`.
# All of it passed while `/custom/bonus-calculator-dfw/report` served the
# CORPORATE report whole — CORP TEAM1-4 instead of TEAM-DFW, the corporate
# margin ladder, the corporate roster, night shift, FX and month lock — because
# `build_bonus_report_data` defaulted `scope` to corporate and the DFW router's
# `/report` and `/history` never passed it (Bruno PDF 2026-09-02).
#
# ⚠ Nothing errored. Every endpoint answered 200, and `/roster` (HR Settings)
# WAS correctly scoped, so the page contradicted its own settings dialog. The
# only assertion that could have caught it is one that drives the real endpoint
# and reads what it emits — so that is what these do.


class _ZeroRow:
    """A datalake row that answers 0 for every column the query aliased."""

    def __getitem__(self, key):  # noqa: D105
        return 0

    def get(self, key, default=None):  # noqa: D102
        return 0


class _StubPool:
    """Captures every statement instead of running any of them."""

    def __init__(self, row=None) -> None:
        self.calls: list[tuple[str, tuple]] = []
        self._row = row

    async def fetch(self, sql, *params):
        self.calls.append((sql, params))
        return []

    async def fetchrow(self, sql, *params):
        self.calls.append((sql, params))
        return self._row

    async def fetchval(self, sql, *params):
        self.calls.append((sql, params))
        return None

    def blob(self) -> str:
        out = []
        for sql, params in self.calls:
            out.append(sql)
            out.append(json.dumps([list(p) if isinstance(p, (list, tuple)) else str(p) for p in params]))
        return "\n".join(out)


def _endpoint(router, path: str):
    for route in router.routes:
        if route.path.endswith(path) and "GET" in getattr(route, "methods", ()):
            return route.endpoint
    raise AssertionError(f"no GET {path} on {router}")


def _drive(router, path: str, **overrides):
    """Call one endpoint of a bonus router against stub pools.

    Returns ``(payload, gold_pool, primary_pool)``. Mirrors what FastAPI does
    over HTTP: a `Query(...)` default object is replaced by its `.default`.
    """
    import asyncio
    import types

    gold = _StubPool(row=_ZeroRow())
    primary = _StubPool()
    orig_gold, orig_primary = bc.get_datalake_gold_pool, bc.get_pool
    bc.get_datalake_gold_pool = lambda request: gold
    bc.get_pool = lambda request: primary
    request = types.SimpleNamespace(app=types.SimpleNamespace(state=types.SimpleNamespace()))
    fn = _endpoint(router, path)
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
        payload = asyncio.run(fn(**kwargs))
    finally:
        bc.get_datalake_gold_pool, bc.get_pool = orig_gold, orig_primary
    return payload["data"], gold, primary


def test_no_scope_argument_may_carry_a_default() -> None:
    """The defect was a DEFAULT, not a typo — this is the guard for the class.

    A `scope=None` that falls back to corporate turns "the caller forgot" into
    "the caller silently got corporate". Required, it is a TypeError at import.
    """
    from app.services import bonus_history as bh

    for fn in (
        bc.build_bonus_report_data,
        bc._team_metrics,
        bc._load_roster,
        bc._load_afterhours,
        bc._load_settings,
        bc._load_lock,
        bh.finalize_due_periods,
        bh.get_history,
    ):
        p = inspect.signature(fn).parameters["scope"]
        assert p.default is inspect.Parameter.empty, f"{fn.__name__} defaults its scope"


def test_the_dfw_report_endpoint_serves_the_dfw_division() -> None:
    """Drive the real `/report` and read what it emitted."""
    data, gold, primary = _drive(bc.dfw_router, "/report")

    # ...the DFW ladder actually reaches the wire.
    assert data["criteria"]["marginBrackets"] is be.DFW_MARGIN_BRACKETS

    # ...the teams are DFW's, labelled the way the PDF asks.
    assert [t["id"] for t in data["teams"]] == list(bc.DFW_SCOPE.teams)
    assert [t["name"] for t in data["teams"]] == ["TM 1", "TM 2", "TM 3", "TM 4"]

    # ...the datalake read is TEAM-DFW, never a CORP team.
    g = gold.blob()
    assert "TEAM-DFW" in g
    for n in (1, 2, 3, 4):
        assert f"TM{n}" in g
    for corp_id in ("TEAM1", "TEAM2", "TEAM3", "TEAM4", "TEAM5"):
        assert corp_id not in g, f"DFW /report read CORP {corp_id}"

    # ...and roster / afterhours / FX / lock come from the DFW tables. The
    # corporate names are checked as whole words: `bonus_dfw_roster` contains
    # neither `bonus_roster` nor `bonus_afterhours` as a token.
    p = primary.blob()
    for tbl in ("bonus_dfw_roster", "bonus_dfw_afterhours", "bonus_dfw_settings", "bonus_dfw_period_lock"):
        assert tbl in p, f"DFW /report never read {tbl}"
    for tbl in ("bonus_roster", "bonus_afterhours", "bonus_settings", "bonus_period_lock"):
        assert not re.search(rf"(?<![_a-z]){tbl}\b", p), f"DFW /report read corporate {tbl}"


def test_the_corporate_report_endpoint_still_serves_corporate() -> None:
    """The other half of the same property — corporate must not have moved."""
    data, gold, primary = _drive(bc.router, "/report")

    assert data["criteria"]["marginBrackets"] is be.MARGIN_BRACKETS
    assert [t["id"] for t in data["teams"]] == list(bc.CORP_SCOPE.teams)
    assert [t["name"] for t in data["teams"]] == ["Team 1", "Team 2", "Team 3", "Team 4"]

    g = gold.blob()
    assert "TEAM-DFW" not in g
    assert "TEAM1" in g

    p = primary.blob()
    for tbl in ("bonus_roster", "bonus_afterhours", "bonus_settings", "bonus_period_lock"):
        assert re.search(rf"(?<![_a-z]){tbl}\b", p), f"corporate /report stopped reading {tbl}"
    assert "bonus_dfw_" not in p


def test_the_dfw_history_open_month_is_scoped_too() -> None:
    """`/history` computes the still-open month live — through the same call.

    It was the second unscoped call site, so the History tab's "in progress"
    row showed corporate teams beside DFW snapshots on the same screen.
    """
    data, gold, primary = _drive(bc.dfw_router, "/history")

    assert data["current"] is not None, "open-month preview swallowed an error"
    assert [r["teamName"] for r in data["current"]["rows"]] == ["TM 1", "TM 2", "TM 3", "TM 4"]
    assert [r["teamId"] for r in data["current"]["rows"]] == list(bc.DFW_SCOPE.teams)

    assert "TEAM-DFW" in gold.blob()
    assert "bonus_dfw_history" in primary.blob()


def test_the_dfw_team_label_carries_the_space() -> None:
    """Bruno PDF 2026-09-02: the container is "TM 1", not "TM1"."""
    assert list(bc.DFW_SCOPE.team_names.values()) == ["TM 1", "TM 2", "TM 3", "TM 4"]
    # ...while the SQL still keys off the McLeod value, which has no space.
    params: list = []
    flat = bc.DFW_SCOPE.scope_where("br4", "dfw-tm-1", params) + json.dumps(
        [list(p) if isinstance(p, list) else str(p) for p in params]
    )
    assert "TM1" in flat and "TM 1" not in flat
