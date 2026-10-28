"""DFW loads booked under a CORP team — the Ops Portal family (2026-10-28).

Sergio Hidalgo (KAM, CORP T3): orders 0007543-45, UNILINK TRANSPORTATION
Monterrey→Tijuana, sit in McLeod MX (TMS3) with ``team_id = 'TEAM3'`` but
``team = 'TM4'`` — DFW loads, −$1,778 on CORP T3's October. Fixed in McLeod by
hand before; it keeps coming back. The rule (``app.datalake.not_dfw_tagged``):

  CORP  excludes a CORP-team row carrying a DFW sub-team marker;
  DFW   includes it (it lands in its TM pill);
  ALL   keeps it and relabels it TEAM-DFW — so CORP + DFW = ALL row for row.

The leak guards in ``test_ops_portal_scope`` / ``test_ceo_executive_portal``
prove nothing crosses; these prove the rule is actually PRESENT in every
statement that scopes v4 or the scorecard — a statement that forgets it is the
exact bug, and it still passes every leak scan.
"""

from __future__ import annotations

import re

import pytest
import test_ops_portal_scope as base
from dfw_marker_sql import strip_dfw_marker_rule

from app.datalake import dfw_tagged, not_dfw_tagged
from app.routers import ops_portal_overview as opo
from app.routers import ops_portal_overview_dfw as dfw
from app.routers import ops_portal_overview_team as team_clones
from app.routers.ops_portal_overview import _constants, _sql
from app.routers.ops_portal_overview._scope import (
    ALL_SCOPE,
    CORP_SCOPE,
    DFW_SCOPE,
    division_member_sql,
    sub_team_expr,
)

_SCOPED_TABLES = ("mcleod_gld_budget_report_v4", "mcleod_gld_scorecard_incidents_portal")
_TEAM_PRED = re.compile(r"team_id\)?\s+(=|IN)\s")


def _scoping_statements(pool) -> list[str]:
    """Statements that read v4/scorecard AND narrow on ``team_id``."""
    return [
        sql for sql, _ in pool.calls
        if any(t in sql for t in _SCOPED_TABLES) and _TEAM_PRED.search(sql)
    ]


def _routes(router):
    return [(r.path, r.endpoint) for r in router.routes]


# ---------------------------------------------------------------------------
# The helpers
# ---------------------------------------------------------------------------


def test_the_marker_rule_is_null_safe_and_case_insensitive() -> None:
    # NULL NOT IN (...) is NULL → the row would be DELETED, not kept (§75).
    assert not_dfw_tagged("br4.team").startswith("COALESCE(br4.team, '')")
    # McLeod carries 'tm4' on 2 rows.
    assert "'tm4'" in not_dfw_tagged("x") and "'tm4'" in dfw_tagged("x")
    # Only the five DFW markers move a row — not "any non-blank team".
    assert "<> ''" not in not_dfw_tagged("x")


def test_each_division_renders_its_side_of_the_rule() -> None:
    corp = division_member_sql(CORP_SCOPE, "br4", "$1")
    assert corp == f"br4.team_id    = ANY($1) AND {not_dfw_tagged('br4.team')}"

    dfw_sql = division_member_sql(DFW_SCOPE, "br4", "$1")
    assert dfw_sql.startswith("(br4.team_id    = ANY($1) OR (br4.team_id IN (")
    assert dfw_sql.endswith(f"AND {dfw_tagged('br4.team')}))")
    # The CORP list carries padded twins (scorecard stores 'TEAM3   ').
    assert "'TEAM3   '" in dfw_sql

    assert division_member_sql(ALL_SCOPE, "br4", "$1") == "br4.team_id    = ANY($1)"


def test_all_relabels_marked_rows_and_the_divisions_do_not() -> None:
    assert sub_team_expr(CORP_SCOPE, "br4", "team_id") == "br4.team_id"
    assert sub_team_expr(DFW_SCOPE, "br4", "team") == "br4.team"
    rel = sub_team_expr(ALL_SCOPE, "br4", "team_id")
    assert rel == f"(CASE WHEN {dfw_tagged('br4.team')} THEN 'TEAM-DFW' ELSE br4.team_id END)"
    # An expression must keep its alias as a SELECT item, or it comes out "case".
    assert _sql._team_id_select("br4", ALL_SCOPE) == f"{rel} AS team_id"
    assert _sql._team_id_select("br4", CORP_SCOPE) == "br4.team_id"


def test_the_v4_scope_where_carries_the_rule_under_every_division() -> None:
    for scope, token in (
        (CORP_SCOPE, "<not-dfw-marked>"),
        (DFW_SCOPE, "<dfw-marked-corp-row>"),
    ):
        where = _sql._v4_scope_where("br4", None, None, None, [], scope=scope)
        assert token in strip_dfw_marker_rule(where), scope.key


def test_the_scorecard_cte_reads_the_scorecard_marker_column() -> None:
    corp = _sql._scorecard_cte("otp", CORP_SCOPE)
    assert not_dfw_tagged("team_dfw") in corp
    dfw_cte = _sql._scorecard_cte("otd", DFW_SCOPE)
    assert dfw_tagged("team_dfw") in dfw_cte


def test_the_customer_team_map_follows_the_rule() -> None:
    assert not_dfw_tagged("team") in _constants.customer_team_cte(CORP_SCOPE)
    assert dfw_tagged("team") in _constants.customer_team_cte(DFW_SCOPE)


# ---------------------------------------------------------------------------
# Drive EVERY endpoint: each scoping statement must carry the rule
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("path,fn", _routes(opo.router), ids=lambda v: v if isinstance(v, str) else "")
def test_every_corp_statement_excludes_dfw_marked_rows(path: str, fn) -> None:
    pool = base._drive(fn, scope=CORP_SCOPE)
    stmts = _scoping_statements(pool)
    if not stmts:
        pytest.skip(f"{path} scopes no v4/scorecard statement")
    for sql in stmts:
        assert "<not-dfw-marked>" in strip_dfw_marker_rule(sql), (
            f"{path} scopes CORP on team_id without the DFW-marker rule:\n{sql[:400]}"
        )


@pytest.mark.parametrize("path,fn", _routes(dfw.r), ids=lambda v: v if isinstance(v, str) else "")
def test_every_dfw_statement_includes_dfw_marked_corp_rows(path: str, fn) -> None:
    pool = base._drive(fn, scope=DFW_SCOPE)
    stmts = _scoping_statements(pool)
    if not stmts:
        pytest.skip(f"{path} scopes no v4/scorecard statement")
    for sql in stmts:
        assert "<dfw-marked-corp-row>" in strip_dfw_marker_rule(sql), (
            f"{path} scopes DFW on team_id without the DFW-marker rule:\n{sql[:400]}"
        )


def test_the_corp_t3_portal_pickers_exclude_dfw_marked_rows(monkeypatch) -> None:
    """The per-team clone (the page Sergio reads) hand-writes its /filters."""
    router = team_clones._make_team_router("TEAM3", "t3", "CORP-T3")
    filters = dict(_routes(router))[f"{router.prefix}/filters"]
    pool = base._StubPool()
    monkeypatch.setattr(team_clones, "get_datalake_gold_pool", lambda request: pool)
    base._drive(filters)
    stmts = [sql for sql, _ in pool.calls]
    assert len(stmts) == 3
    for sql in stmts:
        assert "<not-dfw-marked>" in strip_dfw_marker_rule(sql), sql[:300]
