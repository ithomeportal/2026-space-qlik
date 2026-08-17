"""Exec Meeting – Recruitment: the guards that matter.

Three failure modes are worth pinning, because each one would be invisible on
screen and wrong in a way an exec would act on:

1. A departed employee with no recorded exit date rendering as an active one.
   51% of inactive time-off rows have a NULL "leaveDate", so this is the common
   case, not an edge case.
2. Turnover being published for a past year, where the denominator (headcount
   during that year) cannot be reconstructed and would have to be invented.
3. The department filter being applied to some panels but not others — the exact
   shape §55 warns about, where one card scopes and its neighbour does not.

These run offline against stub pools; no database is contacted.
"""

from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace

import pytest

from app.routers import exec_meeting_recruitment as emr


class _StubPool:
    """Returns a canned row list per query, matched on a substring of the SQL."""

    def __init__(self, responses: list[tuple[str, list]]):
        self.responses = responses
        self.seen: list[str] = []

    async def fetch(self, sql, *params):
        self.seen.append(sql)
        for needle, rows in self.responses:
            if needle in sql:
                return rows
        return []

    async def fetchval(self, sql, *params):
        self.seen.append(sql)
        return None


def _request(recruit=None, timeoff=None):
    state = SimpleNamespace(recruit_pool=recruit, timeoff_pool=timeoff)
    return SimpleNamespace(app=SimpleNamespace(state=state))


# ---------------------------------------------------------------------------
# 1. A departure must never render as an active employee
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_inactive_without_leave_date_is_not_active():
    timeoff = _StubPool(
        [
            (
                "FROM users",
                [
                    {
                        "id": "a",
                        "name": "Still Here",
                        "firstName": None,
                        "lastName": None,
                        "jobTitle": "Analyst",
                        "department": "Operations",
                        "hireDate": datetime(2026, 3, 1),
                        "leaveDate": None,
                        "isActive": True,
                    },
                    {
                        "id": "b",
                        "name": "Left No Date",
                        "firstName": None,
                        "lastName": None,
                        "jobTitle": "Booker",
                        "department": "Operations (DFW)",
                        "hireDate": datetime(2026, 4, 1),
                        "leaveDate": None,
                        "isActive": False,
                    },
                    {
                        "id": "c",
                        "name": "Left With Date",
                        "firstName": None,
                        "lastName": None,
                        "jobTitle": "Pricing Analyst",
                        "department": "Pricing",
                        "hireDate": datetime(2026, 2, 1),
                        "leaveDate": datetime(2026, 6, 1),
                        "isActive": False,
                    },
                ],
            )
        ]
    )

    res = await emr.people_flow(
        request=_request(timeoff=timeoff),
        f={"department": None},
        range="all",
        start_date=None,
        end_date=None,
        _user={},
    )
    by_name = {r["name"]: r for r in res["data"]["rows"]}

    assert by_name["Still Here"]["status"] == "active"
    assert by_name["Left With Date"]["status"] == "departed"
    assert by_name["Left With Date"]["exit_date"] == "2026-06-01"

    # The one that matters: inactive + no leaveDate is its own status, and it
    # carries no exit date to draw a marker from.
    assert by_name["Left No Date"]["status"] == "departed_exit_unknown"
    assert by_name["Left No Date"]["exit_date"] is None


# ---------------------------------------------------------------------------
# 2. Turnover is current-year only
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_turnover_is_none_for_past_years(monkeypatch):
    from datetime import date as _date

    monkeypatch.setattr(emr, "cst_today", lambda: _date(2026, 8, 17))

    timeoff = _StubPool([("FROM users", [{"department": "Operations"}] * 10)])
    recruit = _StubPool(
        [("FreshServiceTicket", [{"departmentOverride": None, "subCategory": "DFW"}] * 4)]
    )

    current = await emr.annual(
        request=_request(recruit=recruit, timeoff=timeoff),
        f={"department": None},
        year=2026,
        _user={},
    )
    assert current["data"]["turnover_rate"] == pytest.approx(4 / 10)
    assert current["data"]["hires_are_historical"] is False

    past = await emr.annual(
        request=_request(recruit=recruit, timeoff=timeoff),
        f={"department": None},
        year=2024,
        _user={},
    )
    assert past["data"]["turnover_rate"] is None
    assert past["data"]["turnover_basis"] is None
    # The UI keys its undercount caption off this flag.
    assert past["data"]["hires_are_historical"] is True


# ---------------------------------------------------------------------------
# 3. The department filter reaches every panel
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_department_filter_scopes_hires_and_exits_alike():
    timeoff = _StubPool(
        [
            (
                "FROM users",
                [
                    {"department": "Operations"},          # -> CORP OPERATIONS
                    {"department": "Operations (DFW)"},    # -> DFW OPERATIONS
                    {"department": "Pricing"},
                ],
            )
        ]
    )
    recruit = _StubPool(
        [
            (
                "FreshServiceTicket",
                [
                    {"departmentOverride": None, "subCategory": "Operations"},  # CORP
                    {"departmentOverride": None, "subCategory": "DFW"},         # DFW
                    {"departmentOverride": "DFW", "subCategory": "Operations"}, # override wins
                ],
            )
        ]
    )

    res = await emr.annual(
        request=_request(recruit=recruit, timeoff=timeoff),
        f={"department": "DFW OPERATIONS"},
        year=2026,
        _user={},
    )
    assert res["data"]["new_hires"] == 1
    # Two exits: the plain DFW ticket, plus the one whose override overrides an
    # Operations subCategory — departmentOverride always wins (Jobs rule 43).
    assert res["data"]["offboarding"] == 2


def test_department_override_wins_and_is_case_insensitive():
    assert emr.resolve_fs_dept("DFW", "Operations") == "DFW OPERATIONS"
    assert emr.resolve_fs_dept(None, "Operations") == "CORP OPERATIONS"
    # Real override values carry case drift ("Carrier procurement").
    assert emr.resolve_fs_dept("Carrier procurement", None) == emr.resolve_fs_dept(
        "Carrier Procurement", None
    )
    assert emr.resolve_fs_dept(None, None) == emr.UNASSIGNED


def test_label_variants_fold_onto_one_department():
    """One filter value must reach all three source vocabularies."""
    assert emr.canonical_dept("Executive Assistance") == emr.canonical_dept(
        "Executive Assistant"
    )
    assert emr.canonical_dept("HR") == "Human Resources"
    assert emr.canonical_dept("Finances") == "Finance"
    assert emr.normalize_timeoff_dept("Operations (DFW)") == "DFW OPERATIONS"
    assert emr.normalize_timeoff_dept("  ") == emr.UNASSIGNED


@pytest.mark.asyncio
async def test_open_vacancies_is_a_remainder_not_a_row_count():
    recruit = _StubPool(
        [
            (
                'FROM "Position"',
                [
                    {
                        "id": "p1",
                        "name": "Booker",
                        "department": "DFW OPERATIONS",
                        "company": "Unilink Transportation",
                        "createdAt": datetime(2026, 7, 6),
                        "vacancies": 2,
                        "hiredCount": 0,
                    },
                    {
                        "id": "p2",
                        "name": "CP & Compliance Manager",
                        "department": None,
                        "company": "Unilink Transportation",
                        "createdAt": datetime(2026, 6, 26),
                        "vacancies": 1,
                        "hiredCount": 1,  # fully filled -> contributes 0
                    },
                ],
            )
        ]
    )
    res = await emr.open_roles(
        request=_request(recruit=recruit), f={"department": None}, _user={}
    )
    assert res["data"]["open_roles"] == 2      # two rows are still ACTIVE
    assert res["data"]["open_vacancies"] == 2  # but only two seats remain open
