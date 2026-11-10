"""R21 (HR, Daniela Nava 2026-11-09) — the CORP wildcard $100k gate reads the
CALENDAR-MONTH profit, the number the team header PROFIT KPI shows.

The defect: October 2026, CORP Team 4 showed PROFIT $101,283 and SERVICE 98.15%
yet the wildcard said "—" and paid $0. The gate read the weekly-bucket sum
(Mon→Sun buckets Oct 5 → Nov 1 = $94,951), which leaves out Oct 1-4. HR's sheet:
Monica Perez (KAM) $250/week, Paula Gonzalez (Freight Match) $200/week.

R9 had already moved the 130/150/170 add-ons to the monthly figure; the wildcard
and the Team-1 KAM $150k gate were left on the bucket sum pending Bruno (never
answered). CIO decision 2026-11-09: CORP only — DFW keeps the bucket-sum gate
(DFW TM1 October would otherwise flip too; not asked for).
"""

from __future__ import annotations

import copy

import pytest

from app.services import bonus_engine as be

# The live October 2026 Team 4 shape (measured 2026-11-09 from the gold lake).
TEAM4_OCT_WEEKS = [
    # (loads, revenue, gross profit) — the bucket profits sum to $94,951 < $100k
    (31, 140_000.0, 23_600.0),
    (37, 160_000.0, 24_900.0),
    (44, 180_000.0, 24_700.0),
    (64, 177_000.0, 21_751.0),
]
TEAM4_MONTHLY_PROFIT = 101_283.0
TEAM4_SERVICE_PCT = 98.14814814814815


def _team(
    *,
    team_id: str = "team-4",
    monthly_profit: float | None = TEAM4_MONTHLY_PROFIT,
    weeks=TEAM4_OCT_WEEKS,
    service: float = TEAM4_SERVICE_PCT,
) -> dict:
    team = {
        "id": team_id,
        "name": "Team 4",
        "fxRate": 18.5,
        "monthlyServicePct": service,
        "weeks": [
            {"label": f"W{i + 1}", "loads": loads, "revenue": rev, "grossProfit": gp}
            for i, (loads, rev, gp) in enumerate(weeks)
        ],
        "employees": [
            {"name": "MONICA PEREZ", "role": "kam", "salaryMxn": 0},
            {"name": "PAULA GONZALEZ", "role": "freight_match", "salaryMxn": 0},
        ],
    }
    if monthly_profit is not None:
        team["monthlyProfit"] = monthly_profit
    return team


def _by_name(result: dict) -> dict:
    return {e["name"]: e for e in result["employees"]}


def test_the_fixture_reproduces_the_reported_gap() -> None:
    """Bucket sum under $100k, month over it — the exact October shape."""
    bucket = sum(gp for _, _, gp in TEAM4_OCT_WEEKS)
    assert bucket == pytest.approx(94_951.0)
    assert bucket < 100_000 < TEAM4_MONTHLY_PROFIT


def test_corp_team4_october_pays_hrs_wildcard() -> None:
    out = be.calculate_team_bonus(_team(), be.CORP_BONUS)
    assert out["wildcardEligible"] is True
    emp = _by_name(out)
    assert emp["MONICA PEREZ"]["weeklyUsd"] == [250.0, 250.0, 250.0, 250.0]
    assert emp["PAULA GONZALEZ"]["weeklyUsd"] == [200.0, 200.0, 200.0, 200.0]
    assert emp["MONICA PEREZ"]["bonusUsd"] == 1000.0
    assert emp["PAULA GONZALEZ"]["bonusUsd"] == 800.0
    assert emp["MONICA PEREZ"]["wildcardWeeklyUsd"] == 250.0
    assert out["teamBonusUsd"] == 1800.0


def test_corp_gate_reads_the_month_not_the_buckets_in_reverse_too() -> None:
    """Buckets over $100k but the month under it ⇒ NOT eligible (same basis both ways)."""
    weeks = [(31, 150_000.0, 30_000.0)] * 4  # bucket $120k
    out = be.calculate_team_bonus(
        _team(weeks=weeks, monthly_profit=99_000.0), be.CORP_BONUS
    )
    assert out["wildcardEligible"] is False
    assert out["teamBonusUsd"] == 0.0


def test_the_gate_stays_strictly_greater_than_100k() -> None:
    out = be.calculate_team_bonus(_team(monthly_profit=100_000.0), be.CORP_BONUS)
    assert out["wildcardEligible"] is False


def test_a_team_without_a_monthly_figure_falls_back_to_the_buckets() -> None:
    """Package fixtures carry no monthlyProfit — same fallback shape as R8/R9."""
    out = be.calculate_team_bonus(_team(monthly_profit=None), be.CORP_BONUS)
    assert out["wildcardEligible"] is False  # bucket $94,951


def test_dfw_keeps_the_bucket_sum_gate() -> None:
    """CIO 2026-11-09: CORP only. DFW TM1 Oct (month $103,468, buckets $97,871) stays ineligible."""
    out = be.calculate_team_bonus(_team(team_id="dfw-tm-1"), be.DFW_BONUS)
    assert out["wildcardEligible"] is False
    assert out["teamBonusUsd"] == 0.0


def test_each_config_declares_its_gate_basis_explicitly() -> None:
    assert be.CORP_BONUS.wildcard_gate_on_monthly_profit is True
    assert be.DFW_BONUS.wildcard_gate_on_monthly_profit is False


def test_team1_kam_150k_gate_reads_the_month_on_corp() -> None:
    """Same open R9 question, same answer: bucket $140k, month $155k ⇒ pays."""
    team = _team(
        team_id="team-1",
        monthly_profit=155_000.0,
        weeks=[(120, 200_000.0, 35_000.0)] * 4,
    )
    kam = _by_name(be.calculate_team_bonus(copy.deepcopy(team), be.CORP_BONUS))[
        "MONICA PEREZ"
    ]
    assert kam["kamBonusMxn"] == 14_400.0
    assert kam["kamBonusUsd"] == pytest.approx(14_400.0 / 18.5)

    team_low = _team(
        team_id="team-1",
        monthly_profit=149_000.0,
        weeks=[(120, 200_000.0, 40_000.0)] * 4,
    )
    kam_low = _by_name(be.calculate_team_bonus(team_low, be.CORP_BONUS))["MONICA PEREZ"]
    assert kam_low["kamBonusUsd"] == 0.0  # bucket $160k no longer pays on its own
