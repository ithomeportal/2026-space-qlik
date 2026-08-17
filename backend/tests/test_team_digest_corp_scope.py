"""PERFORMANCE CORP — the four-team scope of the team-digest email.

The request (PDF 2026-08-17) asked for the "Performance for Team 4" email
duplicated with ``team_id = 'TEAM4'`` replaced by
``team_id IN ('TEAM1','TEAM2','TEAM3','TEAM4')``.

Three things about that are easy to get wrong and impossible to see in a
rendered email, so they are pinned here:

1. **Padding.** McLeod stores ``team_id`` unpadded in
   ``mcleod_gld_budget_report_v4`` ('TEAM1') but right-padded to varchar(8) in
   the scorecard tables ('TEAM1   '). The literal filter from the PDF matches
   ZERO scorecard rows — verified against aivn_datalake_gold on 2026-08-17:
   56,961 rows with the padded variants, 0 without. OTP/OTD would silently
   read 0.0%. Every team id must go through ``pad_variants``.

2. **CORP is not four teams.** ``CORP_TEAMS`` is TEAM1..TEAM5. Dropping the
   team filter entirely — the tempting one-line "fix" — silently adds TEAM5.

3. **Nothing may change for the existing per-team emails.** Four workflows are
   live against this code path, so single-team SQL must be byte-identical.
"""

from __future__ import annotations

import re
from types import SimpleNamespace

import pytest

from app.routers import ops_portal_overview as opo
from app.routers.ops_portal_overview import _parse_team_scope, _team_list
from app.services.team_perf_digest import DIGEST_CORP_TEAMS

USER = {"sub": "probe", "email": "probe@example.com", "roles": ["admin"]}

CORP_SCOPE = ["TEAM1", "TEAM2", "TEAM3", "TEAM4"]


class _RecordingPool:
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


def _request(pool):
    state = SimpleNamespace(savings_pool=pool, pool=pool)
    return SimpleNamespace(app=SimpleNamespace(state=state), headers={}, query_params={})


def _norm(sql: str) -> str:
    return re.sub(r"\s+", " ", sql).strip()


BASE = dict(
    customer=None, load_type=None, lanes=None,
    exclude_lanes=None, carriers=None, exclude_carriers=None,
)


async def _drive(endpoint, **kw):
    pool = _RecordingPool()
    try:
        await endpoint(request=_request(pool), _user=USER, **kw)
    except Exception:
        # The stub returns nothing; downstream arithmetic may raise. What is
        # asserted here is the SQL emitted before that point.
        pass
    return pool


# ---------------------------------------------------------------------------
# The scope parser
# ---------------------------------------------------------------------------


def test_a_bare_string_is_not_iterated_character_wise():
    """`['T','E','A','M','1']` would match nothing and raise no error."""
    assert _team_list("TEAM1") == ["TEAM1"]


def test_teams_overrides_team_and_is_upper_cased_and_trimmed():
    assert _parse_team_scope("TEAM4", " team1 , team2 ") == ["TEAM1", "TEAM2"]
    assert _parse_team_scope("TEAM4", None) == ["TEAM4"]
    assert _parse_team_scope(None, None) == []


def test_a_fastapi_query_default_object_is_treated_as_no_scope():
    """Several endpoints here are ALSO called as plain Python functions.

    ``ops_portal_overview_team.py`` calls /team-performance, /team-projection,
    /profit-tm-gauge and /actuals directly and does not pass ``teams``. Python
    then binds the literal ``Query(None)`` default, which is truthy and has no
    ``.split`` — a plain ``if teams:`` raises AttributeError on every per-team
    portal view while working perfectly over HTTP. Guard the type, not truth.
    """
    from fastapi import Query

    sentinel = Query(None)
    assert _parse_team_scope("TEAM4", sentinel) == ["TEAM4"]
    assert _parse_team_scope(sentinel, sentinel) == []


# ---------------------------------------------------------------------------
# Padding — the failure that returns 0 rows instead of an error
# ---------------------------------------------------------------------------


def test_every_team_in_a_multi_team_scope_gets_its_padded_twin():
    params: list = []
    opo._v4_scope_where("br4", CORP_SCOPE, None, None, params)
    team_param = params[-1]
    for team in CORP_SCOPE:
        assert team in team_param, f"{team} unpadded variant missing"
        assert f"{team}   " in team_param, (
            f"{team} padded variant missing — this filter would match ZERO "
            f"rows in mcleod_gld_scorecard_portal and silently zero OTP/OTD"
        )
    assert len(team_param) == 2 * len(CORP_SCOPE)


def test_the_scope_predicate_is_sargable_not_trim_wrapped():
    params: list = []
    where = opo._v4_scope_where("br4", CORP_SCOPE, None, None, params)
    assert "= ANY(" in where
    assert "TRIM(br4.team_id)" not in where, "TRIM() blocks the btree index"


# ---------------------------------------------------------------------------
# Nothing changes for the four live per-team emails
# ---------------------------------------------------------------------------


def test_single_team_scope_sql_is_byte_identical_before_and_after():
    """A str and a 1-element list must emit the same SQL AND the same params."""
    p_str: list = []
    w_str = opo._v4_scope_where("br4", "TEAM4", None, None, p_str)
    p_list: list = []
    w_list = opo._v4_scope_where("br4", ["TEAM4"], None, None, p_list)
    assert w_str == w_list
    assert p_str == p_list


def test_widening_the_scope_changes_only_the_bound_array_not_the_sql():
    p_one: list = []
    w_one = opo._v4_scope_where("br4", "TEAM4", None, None, p_one)
    p_four: list = []
    w_four = opo._v4_scope_where("br4", CORP_SCOPE, None, None, p_four)
    assert w_one == w_four, "the emitted SQL must not depend on scope width"
    assert len(p_one[-1]) == 2 and len(p_four[-1]) == 8


@pytest.mark.asyncio
async def test_team_performance_single_team_is_unaffected_by_the_new_param():
    """The four live per-team workflows must see exactly what they saw."""
    old = await _drive(opo.team_performance, range="mtd", start_date=None,
                       end_date=None, team="TEAM4", teams=None, **BASE)
    new = await _drive(opo.team_performance, range="mtd", start_date=None,
                       end_date=None, team=None, teams="TEAM4", **BASE)
    assert [(_norm(s), p) for s, p in old.calls] == [
        (_norm(s), p) for s, p in new.calls
    ]


# ---------------------------------------------------------------------------
# The CORP scope reaches the SQL, on every leg
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_team_performance_pushes_all_four_teams_into_every_query():
    pool = await _drive(opo.team_performance, range="mtd", start_date=None,
                        end_date=None, team=None,
                        teams="TEAM1,TEAM2,TEAM3,TEAM4", **BASE)
    assert pool.calls, "no SQL emitted"
    scoped = 0
    for _sql, params in pool.calls:
        arrays = [p for p in params if isinstance(p, list)]
        for arr in arrays:
            if "TEAM1" in arr and "TEAM4" in arr:
                scoped += 1
                break
    assert scoped == len(pool.calls), (
        f"only {scoped}/{len(pool.calls)} queries carry the four-team scope — "
        f"an unscoped leg would silently report all of CORP"
    )


@pytest.mark.asyncio
async def test_the_savings_leg_uses_unpadded_ids_because_the_cte_trims():
    """CUSTOMER_TEAM_CTE emits TRIMmed ids — padding there matches nothing."""
    pool = await _drive(opo.team_performance, range="mtd", start_date=None,
                        end_date=None, team=None,
                        teams="TEAM1,TEAM2,TEAM3,TEAM4", **BASE)
    sav = [(s, p) for s, p in pool.calls if "carriers_savings_results_report" in s]
    assert len(sav) == 1
    sql, params = sav[0]
    assert "ct.team_id = ANY(" in _norm(sql)
    arr = [p for p in params if isinstance(p, list)][-1]
    assert arr == CORP_SCOPE
    assert not any(t.endswith(" ") for t in arr), "ct.team_id is already TRIMmed"


class _FixedRowPool(_RecordingPool):
    """Returns real sums but ``team_count = 0``, forcing the fallback path.

    team_count comes back 0 whenever the scan finds no distinct team_id — the
    only situation in which the fallback is used at all.
    """

    ROW = {
        "vol_12": 1200, "rev_12": 0, "prof_12": 0,
        "vol_mtd": 0, "rev_mtd": 0, "prof_mtd": 0, "team_count": 0,
    }

    async def fetchrow(self, sql, *params):
        self.calls.append((sql, params))
        return dict(self.ROW)


@pytest.mark.asyncio
@pytest.mark.parametrize("scope", [CORP_SCOPE, ["TEAM4"]])
async def test_capacity_is_charged_per_team_in_scope(scope):
    """`1 if team else len(CORP_TEAMS)` gave 1 for ANY list — including four.

    Team Ut. is volume against 500 loads per team, so a four-team roll-up
    charged one team's capacity would report ~4x the real utilisation.
    """
    from app.routers.ops_portal_overview import _metrics

    proj = await _metrics._team_projection_core(
        _FixedRowPool(), team=scope, customer=None, load_type=None, lanes=None,
        exclude_lanes=None, carriers=None, exclude_carriers=None,
        today=__import__("datetime").date(2026, 8, 17),
    )
    expected_cap = 500.0 * len(scope)
    assert proj["proj_volume"] > 0, "fixture must produce volume to divide"
    assert proj["proj_team_ut"] == pytest.approx(
        proj["proj_volume"] / expected_cap * 100.0
    )


@pytest.mark.asyncio
async def test_four_teams_are_not_charged_one_teams_capacity():
    """Directly contrasts the two, so the regression cannot pass silently."""
    from app.routers.ops_portal_overview import _metrics

    async def ut(scope):
        proj = await _metrics._team_projection_core(
            _FixedRowPool(), team=scope, customer=None, load_type=None,
            lanes=None, exclude_lanes=None, carriers=None,
            exclude_carriers=None,
            today=__import__("datetime").date(2026, 8, 17),
        )
        return proj["proj_team_ut"]

    assert await ut(["TEAM4"]) == pytest.approx(4 * await ut(CORP_SCOPE))


# ---------------------------------------------------------------------------
# TEAM5
# ---------------------------------------------------------------------------


def test_the_digest_corp_scope_is_four_teams_not_corp_teams():
    """CORP_TEAMS carries TEAM5; the request named four teams.

    TEAM5 is dormant (last load 2026-04-30, $300 margin YTD 2026 against $4.2M
    for TEAM1-4), so substituting one for the other is invisible in the numbers
    today and would quietly widen the report the day TEAM5 revives.
    """
    assert DIGEST_CORP_TEAMS == ("TEAM1", "TEAM2", "TEAM3", "TEAM4")
    assert "TEAM5" in opo.CORP_TEAMS
    assert "TEAM5" not in DIGEST_CORP_TEAMS
    assert set(DIGEST_CORP_TEAMS) < set(opo.CORP_TEAMS)
