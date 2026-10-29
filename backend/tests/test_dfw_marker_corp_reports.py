"""The DFW rule outside the ops-portal package (2026-10-28, revenue code 10-29).

McLeod MX books DFW loads of the shared customer UNILSATX under the CORP
salesperson ``team_id = 'TEAM3'`` (UNILINK TRANSPORTATION Monterrey→Tijuana,
−$1,778 on CORP T3's October). McLeod (Katerine Meneses, 10-29): the order's
revenue code decides — ``DFW`` → DFW, anything else → the salesperson's team;
Diego: those loads go to DFW team TM4. An order the revenue-code mirror has
not reached yet falls back to the TM1..TM5 marker. See ``app.datalake``.

Two kinds of guard:

* SEMANTIC — the rule's SQL is executed in sqlite over synthetic v4 rows and
  a synthetic ``mcleod_gld_cash_flow_dinfo``, so "CORP drops a DFW-code row,
  DFW gains it as TM4, a TM marker with code DV stays CORP, ALL counts each
  row once" is checked as behaviour, not as text;
* WIRING — each report's own scope helper is rendered and must carry the
  rule. Text checks use the production helpers' own renderings, so a change
  to the rule's spelling moves both sides together.
"""

from __future__ import annotations

import sqlite3

import pytest

from app import division_marker as dm
from app.datalake import REVENUE_CODE_TABLE, dfw_tagged, not_dfw_tagged

TEAMS_PAD = ("TEAM1", "TEAM3", "TEAM3   ", "TEAM-DFW")
_NO_DINFO = object()

# (id, company, team_id, team, revenue code) — `team` is the v4 DFW sub-team
# marker; _NO_DINFO = the order has no revenue-code row yet.
ROWS = [
    ("corp", "TMS3", "TEAM3", "", "DV"),              # a genuine CORP T3 MX load
    ("corp_padded", "TMS3", "TEAM3   ", "", "DV   "),
    ("corp_null", "TMS3", "TEAM3", None, _NO_DINFO),  # NULL marker, no code: CORP (§75)
    ("leak", "TMS3", "TEAM3", "TM4", "DFW  "),        # the reported McLeod MX load
    ("code_only", "TMS3", "TEAM3", "", "DFW"),        # MX: the revenue code alone decides
    ("us_tm3", "TMS", "TEAM3", "TM3", "DFW"),         # 0320800: code DFW, marker TM3
    ("mx_marker_dv", "TMS3", "TEAM3", "TM4", "DV"),   # MX: code DV beats the marker → CORP
    ("us_marker_dv", "TMS", "TEAM5", "TM2", "DV"),    # 0258326: US keeps the marker → DFW
    ("us_code_only", "TMS", "TEAM3", "", "DFW"),      # US: no marker → CORP (0 such rows ever)
    ("unsynced", "TMS3", "TEAM3", "tm4", _NO_DINFO),  # not mirrored yet: marker decides
    ("code_null", "TMS3", "TEAM3", "TM4", None),      # NULL code: marker decides
    ("dfw", "TMS", "TEAM-DFW", "TM4", "DFW"),
    ("dfw_blank", "TMS", "TEAM-DFW", "", "DFW"),
    ("dfw_dv", "TMS", "TEAM-DFW", "TM2", "DV"),       # TEAM-DFW stays DFW whatever its code
    ("other_team", "TMS", "TEAM1", "", "DV"),
    ("not_a_division", "TMS3", "TEAM-MX", "TM4", "DFW"),  # never admits a non-team
]


def _db() -> sqlite3.Connection:
    con = sqlite3.connect(":memory:")
    con.execute("CREATE TABLE br4 (id TEXT, company_id TEXT, team_id TEXT, team TEXT)")
    con.execute(f"CREATE TABLE {REVENUE_CODE_TABLE} (company_id TEXT, id TEXT, revenue_code_id TEXT)")
    for rid, company, team_id, team, code in ROWS:
        con.execute("INSERT INTO br4 VALUES (?, ?, ?, ?)", (rid, company, team_id, team))
        if code is not _NO_DINFO:
            con.execute(f"INSERT INTO {REVENUE_CODE_TABLE} VALUES (?, ?, ?)", (company, rid, code))
    return con


def _select(predicate: str, teams: list[str]) -> set[str]:
    """Run ``predicate`` (with ``= ANY($1)`` → IN) over ROWS in sqlite."""
    from app.datalake import pad_variants

    bound = ", ".join(f"'{t}'" for t in pad_variants(teams, width=8))
    sql = predicate.replace("= ANY($1)", f"IN ({bound})")
    return {r[0] for r in _db().execute(f"SELECT id FROM br4 WHERE {sql}")}


def _membership(teams: list[str]) -> set[str]:
    return _select(dm.team_membership_sql("br4", teams, 1), teams)


# ---------------------------------------------------------------------------
# Semantic
# ---------------------------------------------------------------------------

DFW_CORP_ROWS = {"leak", "code_only", "us_tm3", "us_marker_dv", "unsynced", "code_null"}


def test_corp_drops_the_dfw_code_rows_and_keeps_its_own() -> None:
    # The revenue code is McLeod MX's rule; US McLeod keeps the marker
    # (us_code_only: measured 0 such US rows ever).
    assert _membership(["TEAM3"]) == {
        "corp", "corp_padded", "corp_null", "mx_marker_dv", "us_code_only",
    }
    assert _membership(["TEAM5"]) == set()


def test_dfw_gains_the_dfw_code_corp_rows() -> None:
    assert _membership(["TEAM-DFW"]) == {"dfw", "dfw_blank", "dfw_dv"} | DFW_CORP_ROWS


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


def test_a_dfw_code_corp_row_is_team_dfw_and_pill_tm4() -> None:
    con = _db()
    team_of = dict(con.execute(f"SELECT id, {dm.division_team_id_sql('br4')} FROM br4"))
    label = dict(con.execute(f"SELECT id, {dm.team_label_sql('br4')} FROM br4"))
    pill = dict(con.execute(f"SELECT id, {dm.dfw_sub_team_sql('br4')} FROM br4"))
    for rid in DFW_CORP_ROWS:
        assert team_of[rid] == "TEAM-DFW", rid
        assert label[rid] == pill[rid] == "TM4", rid  # whatever the marker says
    assert team_of["corp"] == team_of["corp_null"] == "TEAM3"
    assert team_of["mx_marker_dv"] == "TEAM3" and label["mx_marker_dv"] == "TEAM3"
    assert label["dfw"] == "TM4" and label["dfw_dv"] == pill["dfw_dv"] == "TM2"
    assert label["corp_padded"] == "TEAM3"


def test_a_bare_marker_column_is_refused() -> None:
    # Inside the revenue-code subquery a bare `id` binds to the dinfo row and
    # the test is always TRUE — so a bare column must fail loudly.
    for bad in ("team", "team_dfw"):
        with pytest.raises(ValueError):
            dfw_tagged(bad)
    with pytest.raises(ValueError):
        dm.team_label_sql("")
    with pytest.raises(ValueError):
        dm.division_team_id_sql("")


def test_the_rule_is_uncorrelated_and_mx_only() -> None:
    # A correlated lookup is parallel-restricted: it turned whole scans
    # serial (DFW XRay KPI 0.98 s → 11.3 s) and a >10 s reader blocks the
    # scorecard reload's TRUNCATE. The id sets must not mention the row.
    sql = dfw_tagged("sc.team_dfw")
    for sub_q in sql.split("(SELECT ")[1:]:
        assert "sc." not in sub_q.split(")")[0], sub_q
    assert sql.count("sc.company_id IN ('TMS3')") == 2
    assert sql.endswith("END)") and "ELSE COALESCE(sc.team_dfw, '') IN (" in sql


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
    assert not_dfw_tagged("mcleod_gld_scorecard_incidents_portal.team_dfw") in m._scorecard_cte("otp")


def test_xray_dfw_scope_and_scorecard_take_the_marked_rows() -> None:
    from app.routers import xray_dfw as m

    assert INCL_V4 in m._scope_where("br4", [], [], [])
    sc = m._scorecard_cte("otd", ["TM4"])
    assert dfw_tagged("mcleod_gld_scorecard_incidents_portal.team_dfw") in sc
    # The sub-team pill reads TM4 for a DFW-code CORP row, not its marker.
    assert dm.dfw_sub_team_sql("mcleod_gld_scorecard_incidents_portal", "team_dfw") in sc


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
    assert dm.division_team_id_sql("mcleod_gld_budget_report_v4") in m.CUSTOMER_TEAM_CTE


def test_attrition_wow_team_filters_source_carries_the_rule() -> None:
    import inspect

    from app.routers import attrition_wow_team as m

    src = inspect.getsource(m)
    assert src.count('team_membership_sql("v4", (team,), 1)') == 2
