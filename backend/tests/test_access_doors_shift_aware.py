"""Shift-awareness proof for the Access Log Doors reports.

Runs entirely offline: it inspects the SQL the CTE builders emit, plus the
filter-fragment builder, without a DB or network.

Why this is a test. Before Aug 2026 the report defined "arrival" as the first
punch of the CALENDAR day and read expected-arrival times from a hardcoded CASE
in which every branch was an AM time. For anyone working nights that produced
two different wrong answers, neither of which looked like an error:

  * their morning EXIT badge was scored as a late arrival —
    "Ruben Aguilera | 06:30 AM | 7:12 AM | 42 min", for a man whose shift had
    just ended at 07:12;
  * a genuine on-time 18:39 arrival scored against 06:30 read as -729 minutes.

The daily email carried that to five recipients for months. Every assertion here
guards one of the pieces that fixes it. A regression would once again look like
data ("the night team is late again"), not like a bug, so it must fail loudly
here instead.
"""

from __future__ import annotations

import re

from app.routers.hr_access_doors import (
    _CHECK_MINUTES_EXPR,
    _first_punch_cte,
    _scored_cte,
)
from app.routers.scoped_access_doors import _build_filters_sql

FIRST = _first_punch_cte("$1", "$2")
SCORED = _scored_cte("$1", "$2")


def _squash(sql: str) -> str:
    return re.sub(r"\s+", " ", sql)


class TestOvernightAttribution:
    def test_shift_date_rolls_back_for_an_evening_start(self):
        """A punch before noon belonging to a >=12:00 shift is attributed to the
        PREVIOUS day — the evening the shift began."""
        sql = _squash(FIRST)
        assert "expected_time >= TIME '12:00'" in sql
        assert "event_time::time < TIME '12:00'" in sql
        assert "event_time::date - 1" in sql

    def test_rows_are_ranked_within_the_shift_not_the_calendar_day(self):
        sql = _squash(FIRST)
        assert "PARTITION BY r.shift_date, r.ident" in sql
        # The old form partitioned by the raw calendar date. If that ever comes
        # back, a night worker's morning exit becomes rn=1 again.
        assert "PARTITION BY z.event_date" not in sql

    def test_only_punches_near_the_expected_start_count_as_arrivals(self):
        """"No entry badge for this shift" must not be reported as lateness."""
        sql = _squash(FIRST)
        assert "INTERVAL '3 hours'" in sql
        assert "INTERVAL '6 hours'" in sql
        # Rows with no rule at all still flow through to the
        # "Not On Time Reference" bucket rather than being dropped.
        assert "r.expected_time IS NULL" in sql

    def test_scan_overshoots_the_window_so_a_shift_is_assembled_whole(self):
        sql = _squash(FIRST)
        assert "$1::date - 1" in sql
        assert "$2::date + 1" in sql

    def test_scored_narrows_back_to_the_requested_range(self):
        """The overscan above must not leak extra days into the output."""
        sql = _squash(SCORED)
        assert "event_date BETWEEN $1::date AND $2::date" in sql
        assert "WHERE rn = 1" in sql


class TestExpectedTimeComesFromTheRulesTable:
    def test_no_hardcoded_expected_times_remain(self):
        """The rules live in one place. A second hardcoded copy is what let the
        portal and the n8n workflow drift apart in the first place."""
        sql = _squash(FIRST)
        assert "late_arrival_schedule" in sql
        for literal in ("TIME '06:30'", "TIME '07:00'", "TIME '07:30'", "TIME '08:00'"):
            assert literal not in sql, f"hardcoded expected time reintroduced: {literal}"

    def test_email_outranks_every_other_key(self):
        """Scanner names and Entra job titles both drift; email does not."""
        sql = _squash(FIRST)
        assert "(s.email IS NOT NULL)::int * 1000" in sql
        assert "(s.full_name IS NOT NULL)::int * 100" in sql
        assert "(s.job_title IS NOT NULL)::int * 10" in sql


class TestCheckMinutes:
    def test_uses_a_true_timestamp_difference(self):
        """Clock arithmetic breaks across midnight: a 00:30 arrival against a
        19:30 expected computed as '19 hours early'."""
        sql = _squash(_CHECK_MINUTES_EXPR)
        assert "EXTRACT(EPOCH FROM (expected - event_time))" in sql
        assert "EXTRACT(HOUR FROM expected)" not in sql

    def test_sign_convention_is_unchanged(self):
        """expected - actual, so positive is early. The email prints abs()."""
        assert _squash(_CHECK_MINUTES_EXPR).index("expected") < _squash(
            _CHECK_MINUTES_EXPR
        ).index("event_time")


class TestTeamFilter:
    def test_team_is_exposed_and_parameterised(self):
        assert "AS team" in _squash(FIRST)
        assert "team" in _squash(SCORED)

    def test_team_label_covers_tm_and_team_prefixes(self):
        sql = _squash(FIRST)
        assert "'^TM[0-9]+$'" in sql
        assert "'^TEAM[0-9]+$'" in sql
        assert "'Unassigned'" in sql

    def test_roster_join_is_left_so_nobody_is_dropped(self):
        """Two DFW people have no row in the auth roster. An INNER join would
        silently remove them from every KPI."""
        sql = _squash(FIRST)
        assert "LEFT JOIN public.app_auth_users" in sql

    def test_filters_sql_binds_team_as_a_parameter(self):
        params: list = ["a", "b"]
        frag = _build_filters_sql(params, None, None, "Team 5")
        assert frag.strip() == "AND team = $3"
        assert params[-1] == "Team 5"

    def test_absent_team_adds_no_fragment(self):
        params: list = []
        assert _build_filters_sql(params, None, None, None) == ""
        assert params == []

    def test_team_composes_with_the_other_filters(self):
        params: list = ["s", "e"]
        frag = _build_filters_sql(params, "Ada", "Booker", "Team 2")
        assert frag == " AND nm = $3 AND jt = $4 AND team = $5"
        assert params[2:] == ["Ada", "Booker", "Team 2"]
