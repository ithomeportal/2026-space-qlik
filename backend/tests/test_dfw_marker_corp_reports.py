"""DFW-marker rule outside the ops-portal package (Sergio Hidalgo, 2026-10-28).

McLeod MX books some DFW loads under ``team_id = 'TEAM3'`` while the DFW
sub-team column says ``TM4`` (18 UNILINK TRANSPORTATION Monterrey→Tijuana
loads, −$1,778 on CORP T3's October). Every CORP report must drop them and
every DFW report that can take them must add them — see
``app.division_marker``.

Two kinds of guard:

* SEMANTIC — the rule's SQL is executed in sqlite over synthetic rows, so
  "CORP drops a marked row, DFW gains it, ALL counts it once, a NULL marker
  stays CORP" is checked as behaviour, not as text;
* WIRING — each report's own scope helper is rendered and must carry the
  rule. Text checks use the production helpers' own renderings, so a change
  to the rule's spelling moves both sides together.
"""

from __future__ import annotations

import sqlite3

import pytest

from app import division_marker as dm
from app.datalake import dfw_tagged, not_dfw_tagged

TEAMS_PAD = ("TEAM1", "TEAM3", "TEAM3   ", "TEAM-DFW")

# (id, team_id, team) — `team` is the v4 DFW sub-team column.
ROWS = [
    ("corp", "TEAM3", ""),          # a genuine CORP T3 load
    ("corp_padded", "TEAM3   ", ""),
    ("corp_null", "TEAM3", None),   # NULL marker must stay CORP (§75)
    ("leak", "TEAM3", "TM4"),       # the reported McLeod MX load
    ("leak_lower", "TEAM3", "tm4"),  # McLeod is not case-clean
    ("dfw", "TEAM-DFW", "TM4"),
    ("dfw_blank", "TEAM-DFW", ""),
    ("other_team", "TEAM1", ""),
    ("not_a_division", "TEAM-MX", "TM4"),  # a marker alone never admits a row
]


def _select(predicate: str, teams: list[str]) -> set[str]:
    """Run ``predicate`` (with ``= ANY($1)`` → IN) over ROWS in sqlite."""
    from app.datalake import pad_variants

    con = sqlite3.connect(":memory:")
    con.execute("CREATE TABLE br4 (id TEXT, team_id TEXT, team TEXT)")
    con.executemany("INSERT INTO br4 VALUES (?, ?, ?)", ROWS)
    bound = ", ".join(f"'{t}'" for t in pad_variants(teams, width=8))
    sql = predicate.replace("= ANY($1)", f"IN ({bound})")
    return {r[0] for r in con.execute(f"SELECT id FROM br4 WHERE {sql}")}


def _membership(teams: list[str]) -> set[str]:
    return _select(dm.team_membership_sql("br4", teams, 1), teams)


# ---------------------------------------------------------------------------
# Semantic
# ---------------------------------------------------------------------------


def test_corp_drops_the_dfw_marked_rows_and_keeps_its_own() -> None:
    assert _membership(["TEAM3"]) == {"corp", "corp_padded", "corp_null"}


def test_dfw_gains_the_dfw_marked_corp_rows() -> None:
    assert _membership(["TEAM-DFW"]) == {"dfw", "dfw_blank", "leak", "leak_lower"}


def test_a_both_division_list_counts_each_row_once_and_moves_nothing() -> None:
    teams = ["TEAM1", "TEAM2", "TEAM3", "TEAM4", "TEAM5", "TEAM-DFW"]
    corp = _membership(teams[:5])
    dfw = _membership(["TEAM-DFW"])
    both = _membership(teams)
    assert corp.isdisjoint(dfw)
    assert both == corp | dfw
    # ⚠ The CRM-writing attrition → Pipedrive job reads exactly this list:
    # its population must equal the plain team_id predicate's.
    assert both == _select("br4.team_id = ANY($1)", teams)


def test_the_row_team_and_label_follow_the_marker() -> None:
    con = sqlite3.connect(":memory:")
    con.execute("CREATE TABLE br4 (id TEXT, team_id TEXT, team TEXT)")
    con.executemany("INSERT INTO br4 VALUES (?, ?, ?)", ROWS)
    team_of = dict(con.execute(f"SELECT id, {dm.division_team_id_sql('br4')} FROM br4"))
    label = dict(con.execute(f"SELECT id, {dm.team_label_sql('br4')} FROM br4"))
    assert team_of["leak"] == team_of["leak_lower"] == "TEAM-DFW"
    assert team_of["corp"] == team_of["corp_null"] == "TEAM3"
    assert label["leak"] == "TM4" and label["dfw"] == "TM4"
    assert label["corp_padded"] == "TEAM3"


def test_bare_alias_renders_bare_columns() -> None:
    assert "team_id" in dm.team_label_sql("") and ".team" not in dm.team_label_sql("")
    assert ".team" not in dm.division_team_id_sql("")


# ---------------------------------------------------------------------------
# Wiring — every report's scope helper carries the rule
# ---------------------------------------------------------------------------

EXCL_V4 = not_dfw_tagged("br4.team")
INCL_V4 = dfw_tagged("br4.team")


def test_ops_customer_score_scorecard_scope() -> None:
    from app.routers import ops_customer_score as m

    corp = m._scope_where("sc", ["TEAM3"], ["TMS"], None, None, None, [])
    dfw = m._scope_where("sc", ["TEAM-DFW"], ["TMS"], None, None, None, [])
    assert not_dfw_tagged("sc.team_dfw") in corp
    assert dfw_tagged("sc.team_dfw") in dfw and "NOT IN" not in dfw
    assert dm.division_team_id_sql("sc", "team_dfw") == m._TEAM_OF_ROW


def test_xray_corp_scope_and_scorecard() -> None:
    from app.routers import xray_corp as m

    assert EXCL_V4 in m._scope_where("br4", "TEAM3", None, [])
    assert not_dfw_tagged("team_dfw") in m._scorecard_cte("otp")


def test_xray_dfw_scope_and_scorecard_take_the_marked_rows() -> None:
    from app.routers import xray_dfw as m

    assert INCL_V4 in m._scope_where("br4", [], [], [])
    assert dfw_tagged("team_dfw") in m._scorecard_cte("otd", ["TM4"])


@pytest.mark.parametrize("division,expect", [("CORP", EXCL_V4), ("DFW", INCL_V4)])
def test_ops_margins_and_direct_compare(division: str, expect: str) -> None:
    from app.routers import ops_margins as m

    teams, _ = m._resolve_division(division)
    assert expect in m._scope_where("br4", teams, ["TMS"], None, None, None, None, [])


def test_ceo_executive_team_pills() -> None:
    from app.routers import ceo_executive as m

    assert EXCL_V4 in m._scope_where("br4", None, None, [], division="CORP")
    assert INCL_V4 in m._scope_where("br4", None, None, [], division="DFW")
    # Under ALL a CORP pill must still drop the marked rows; a DFW pill gains them.
    assert EXCL_V4 in m._scope_where("br4", "TEAM3", None, [])
    assert INCL_V4 in m._scope_where("br4", "TM4", None, [])
    assert m._TEAM_LABEL_BR4 == dm.team_label_sql("br4")


def test_attrition_wow_scope_and_team_dim() -> None:
    from app.routers import attrition_wow as m

    assert EXCL_V4 in m._scope_where("br4", ["TEAM3"], None, None, None, [])
    assert INCL_V4 in m._scope_where("br4", ["TEAM-DFW"], None, None, None, [])
    assert INCL_V4 in m._team_dim("br4")


@pytest.mark.parametrize("mod", ["losses_lanes", "sales_attrition_to_ops"])
def test_v4_team_list_reports(mod: str) -> None:
    import importlib

    m = importlib.import_module(f"app.routers.{mod}")
    assert EXCL_V4 in m._scope_where("br4", ["TEAM3"], None, [])
    assert INCL_V4 in m._scope_where("br4", ["TEAM-DFW"], None, [])


def test_admin_cashflow_uses_team_dfw() -> None:
    from app.routers import admin_cashflow as m

    corp = m._scope_where("c", ["TEAM3"], ["TMS"], ("D",), None, None, [])
    dfw = m._scope_where("c", ["TEAM-DFW"], ["TMS"], ("D",), None, None, [])
    assert not_dfw_tagged("c.team_dfw") in corp
    assert dfw_tagged("c.team_dfw") in dfw


def test_dfw_only_reports_take_the_marked_rows() -> None:
    from app.routers import dfw_losses, kam_performance_dfw

    assert INCL_V4 in dfw_losses._scope_where("br4", [], [], [])
    assert dfw_tagged("b.team") in kam_performance_dfw._dfw_scope_where("b", [])


@pytest.mark.parametrize("mod", ["budget_followup", "carriers_savings"])
def test_customer_team_maps_vote_marked_rows_for_dfw(mod: str) -> None:
    import importlib

    m = importlib.import_module(f"app.routers.{mod}")
    assert dm.division_team_id_sql("") in m.CUSTOMER_TEAM_CTE


def test_attrition_wow_team_filters_source_carries_the_rule() -> None:
    import inspect

    from app.routers import attrition_wow_team as m

    src = inspect.getsource(m)
    assert src.count('team_membership_sql("v4", (team,), 1)') == 2
