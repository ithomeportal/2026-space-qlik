"""Bonus Calculator – DFW roster sync from the Time-off DB (Diego 2026-09-02).

This job writes into a live PAYROLL table on a schedule, unattended. Three
properties, each of which fails silently rather than loudly:

  * **It never edits a row it did not create.** `bonus_dfw_roster` is HR's
    editable table and team membership here is *inferred from load postings*, so
    a job that "corrects" an existing row would revert HR's decisions and could
    move somebody between teams overnight — changing their pay with nothing on
    screen to show it happened.

  * **It is idempotent.** It runs every night against the same two sources; a
    second run must add nobody. A duplicate roster row is not a duplicate
    display, it is a second per-load payout for the same person.

  * **A name must resolve to exactly one person.** Time-off stores full legal
    names and McLeod the short form, so matching is subset-based — which is the
    §83 silent-merge shape unless an ambiguous key resolves to NOTHING.
"""

from __future__ import annotations

import asyncio
import inspect
from datetime import date

import pytest

from app.services import bonus_dfw_roster_sync as sync


# ---------------------------------------------------------------------------
# Stub pools
# ---------------------------------------------------------------------------


class _Row(dict):
    def __getitem__(self, k):  # asyncpg Records are bracket-accessed
        return dict.__getitem__(self, k)


class _SourcePool:
    """Answers the two read queries; records nothing."""

    def __init__(self, rows):
        self._rows = rows

    async def fetch(self, sql, *params):
        return self._rows


class _PrimaryPool:
    """An in-memory, effective-dated `bonus_dfw_roster` / `bonus_dfw_afterhours`."""

    def __init__(self, roster=None, afterhours=None):
        self._next_id = 0
        self.roster = [self._with_id(r) for r in (roster or [])]
        self.afterhours = [self._with_id(r) for r in (afterhours or [])]
        self.statements: list[str] = []

    def _with_id(self, row):
        self._next_id += 1
        return {"id": self._next_id, "effective_from": None, "effective_to": None, **row}

    def _rows(self, sql):
        return self.afterhours if "afterhours" in sql else self.roster

    async def fetch(self, sql, *params):
        return [_Row(r) for r in self._rows(sql)]

    async def fetchval(self, sql, *params):
        rows = self._rows(sql)
        if params:
            rows = [r for r in rows if r.get("team_id") == params[0]]
        return max([r.get("sort_order", 0) for r in rows], default=-1) + 1

    async def execute(self, sql, *params):
        self.statements.append(sql)
        verb = sql.strip().split()[0]
        target = self._rows(sql)
        if verb == "INSERT":
            if "afterhours" in sql:
                row = {"shift_group": params[0], "employee_name": params[1],
                       "salary_mxn": params[2], "sort_order": params[3], "effective_from": params[4]}
            else:
                row = {"team_id": params[0], "employee_name": params[1], "role": params[2],
                       "salary_mxn": params[3], "sort_order": params[4], "effective_from": params[5]}
            target.append(self._with_id(row))
        elif verb == "DELETE":
            target[:] = [r for r in target if r["id"] != params[0]]
        elif verb == "UPDATE":
            assert "SET effective_to = $2" in sql, f"the sync edited an HR column: {sql}"
            target[:] = [
                {**r, "effective_to": params[1]} if r["id"] == params[0] and r["effective_to"] is None else r
                for r in target
            ]
        return "OK"

    def visible(self, rows, first):
        return [
            r for r in rows
            if (r["effective_from"] is None or r["effective_from"] <= first)
            and (r["effective_to"] is None or r["effective_to"] >= first)
        ]


def _person(name, title, shift="DAY", active=True):
    return _Row({"name": name, "jobTitle": title, "shiftType": shift, "isActive": active})


def _posting(name, team, n):
    return _Row({"posted_by_name": name, "team": team, "n": n})


TODAY = date(2026, 11, 3)
NOV, OCT = date(2026, 11, 1), date(2026, 10, 1)


def _run(primary, people, postings, today=TODAY):
    return asyncio.run(
        sync.sync_dfw_bonus_roster(primary, _SourcePool(people), _SourcePool(postings), today=today)
    )


PEOPLE = [
    _person("Armando Calvillo", "Key Account Manager"),
    _person("Eugenio Miranda", "Booker"),
    _person("Mauricio Mahuad Ortiz", "Tracking and Tracking"),
    _person("Jairo Martinez", "Night Shift Leader", shift="NIGHT"),
    _person("Jennifer Alanis", "Director DFW"),
]
POSTINGS = [
    _posting("ARMANDO CALVILLO", "TM1", 620),
    _posting("EUGENIO MIRANDA", "TM1", 570),
    _posting("MAURICIO MAHUAD", "TM4", 25),
]


# ---------------------------------------------------------------------------


def test_it_places_people_and_skips_non_bonus_titles() -> None:
    p = _PrimaryPool()
    rep = _run(p, PEOPLE, POSTINGS)

    placed = {r["employee_name"]: (r["team_id"], r["role"]) for r in p.roster}
    assert placed == {
        "Armando Calvillo": ("dfw-tm-1", "kam"),
        "Eugenio Miranda": ("dfw-tm-1", "freight_match"),
        # ⚠ the short McLeod form still resolves the full legal name
        "Mauricio Mahuad Ortiz": ("dfw-tm-4", "tracking_tracing"),
    }
    # a NIGHT shift goes to Afterhours whatever the title says...
    assert [r["employee_name"] for r in p.afterhours] == ["Jairo Martinez"]
    assert p.afterhours[0]["shift_group"] == "Night Shift"
    # ...and Director DFW is not a bonus role at all.
    assert "Jennifer Alanis" not in placed
    assert rep["removed"] == []


def test_it_is_idempotent() -> None:
    """A second night must add nobody — a duplicate row is a second payout."""
    p = _PrimaryPool()
    _run(p, PEOPLE, POSTINGS)
    n_roster, n_after = len(p.roster), len(p.afterhours)

    rep = _run(p, PEOPLE, POSTINGS)
    assert rep["added_team"] == [] and rep["added_afterhours"] == []
    assert (len(p.roster), len(p.afterhours)) == (n_roster, n_after)


def test_it_never_edits_a_row_it_did_not_create() -> None:
    """🔴 HR's team, role and salary always win.

    Team membership is INFERRED from postings; a job that reconciled would move
    somebody between teams on a few stray loads and change their pay silently.
    """
    p = _PrimaryPool(roster=[{
        "team_id": "dfw-tm-3", "employee_name": "Armando Calvillo",
        "role": "tracking_tracing", "salary_mxn": 99999, "sort_order": 0,
    }])
    _run(p, PEOPLE, POSTINGS)

    rows = [r for r in p.roster if r["employee_name"] == "Armando Calvillo"]
    # ⚠ Exactly ONE row. Asserting only that the original still reads correctly
    # cannot tell "left alone" from "left alone, plus a duplicate on the team
    # the postings suggest" — and a duplicate is a second per-load payout.
    assert len(rows) == 1, f"the sync added a duplicate: {rows}"
    row = rows[0]
    assert (row["team_id"], row["role"], row["salary_mxn"]) == ("dfw-tm-3", "tracking_tracing", 99999)
    assert not any(s.strip().startswith("UPDATE") for s in p.statements), "the sync emitted an UPDATE"


def test_a_leaver_is_soft_closed_but_an_unknown_row_is_left_alone() -> None:
    """Only somebody Time-off KNOWS and marks inactive may be removed — and only
    from NOW on.

    A roster row Time-off has never heard of was added by HR — a contractor, a
    rename — and removing it would quietly stop paying them. A leaver is CLOSED
    at the previous month (2026-10-31 effective dating), never deleted: a hard
    DELETE erased them from the months they had already worked.
    """
    p = _PrimaryPool(roster=[
        {"team_id": "dfw-tm-1", "employee_name": "Armando Calvillo", "role": "kam",
         "salary_mxn": 42000, "sort_order": 0},
        {"team_id": "dfw-tm-1", "employee_name": "Someone HR Added", "role": "kam",
         "salary_mxn": 1, "sort_order": 1},
    ])
    people = [_person("Armando Calvillo", "Key Account Manager", active=False)] + PEOPLE[1:]
    rep = _run(p, people, POSTINGS)

    armando = [r for r in p.roster if r["employee_name"] == "Armando Calvillo"]
    assert len(armando) == 1, "a leaver's row was deleted instead of closed"
    assert armando[0]["effective_to"] == OCT
    nov = {r["employee_name"] for r in p.visible(p.roster, NOV)}
    oct_ = {r["employee_name"] for r in p.visible(p.roster, OCT)}
    assert "Armando Calvillo" not in nov, "an inactive employee is still paid this month"
    assert "Armando Calvillo" in oct_, "a leaver vanished from a month they worked"
    assert "Someone HR Added" in nov, "a row Time-off does not know was removed"
    assert any("Armando Calvillo" in x for x in rep["removed"])
    assert not any(s.strip().startswith("DELETE") for s in p.statements)

    # ...and a second night neither re-closes nor re-inserts them.
    rep2 = _run(p, people, POSTINGS)
    assert rep2["removed"] == [] and rep2["added_team"] == []
    assert len([r for r in p.roster if r["employee_name"] == "Armando Calvillo"]) == 1


def test_an_ambiguous_name_resolves_to_nobody() -> None:
    """§83: a silent merge is worse than a miss — it pays the wrong person."""
    candidates = {
        sync._key("Jorge Hernandez Ruiz"): {"a": 1},
        sync._key("Jorge Hernandez Lopez"): {"b": 2},
    }
    assert sync._resolve(sync._key("Jorge Hernandez"), candidates) is None
    # ...and one shared surname is never a match on its own.
    assert sync._resolve(sync._key("Evelyn Rodriguez"),
                         {sync._key("Jessica Rodriguez"): {"x": 1}}) is None
    # ...while a genuine subset still resolves.
    assert sync._resolve(sync._key("Mauricio Mahuad"),
                         {sync._key("Mauricio Mahuad Ortiz"): {"TM4": 9}}) == {"TM4": 9}


def test_an_unmapped_job_title_is_skipped_not_defaulted() -> None:
    """A new title must be a decision. Defaulting it pays somebody by accident."""
    p = _PrimaryPool()
    _run(p, [_person("Brand New Role", "Head of Something")],
         [_posting("BRAND NEW ROLE", "TM1", 50)])
    assert p.roster == [] and p.afterhours == []


def test_a_low_confidence_placement_is_reported_but_still_placed() -> None:
    """Diego 2026-09-02: everyone gets paid; HR corrects the doubtful ones."""
    p = _PrimaryPool()
    rep = _run(p, [_person("Split Person", "Booker")],
               [_posting("SPLIT PERSON", "TM4", 88), _posting("SPLIT PERSON", "TM2", 64)])
    assert [r["team_id"] for r in p.roster] == ["dfw-tm-4"]
    assert any("Split Person" in x and "58%" in x for x in rep["low_confidence"])


def test_someone_who_posts_nothing_is_parked_not_guessed() -> None:
    p = _PrimaryPool()
    rep = _run(p, [_person("Never Posts", "Tracking and Tracing")], POSTINGS)
    assert p.roster == []
    assert any("Never Posts" in x for x in rep["unplaceable"])


def test_it_degrades_instead_of_raising_when_a_pool_is_missing() -> None:
    """A missing optional pool must skip the job, not error the scheduler."""
    assert "skipped" in asyncio.run(sync.sync_dfw_bonus_roster(_PrimaryPool(), None, _SourcePool([])))
    assert "skipped" in asyncio.run(sync.sync_dfw_bonus_roster(_PrimaryPool(), _SourcePool([]), None))


def test_it_only_ever_touches_the_dfw_tables() -> None:
    """The corporate roster is a different division's live payroll."""
    src = inspect.getsource(sync)
    for corp in ("bonus_roster", "bonus_afterhours"):
        import re
        assert not re.search(rf"(?<![_a-z]){corp}\b", src), f"the DFW sync names {corp}"
    assert "bonus_dfw_roster" in src and "bonus_dfw_afterhours" in src


def test_the_job_is_on_the_scheduler_roster() -> None:
    """A job missing from EXPECTED_JOBS is a job nobody notices never ran."""
    main = inspect.getsource(__import__("app.main", fromlist=["main"]))
    assert '"daily_dfw_bonus_roster_sync"' in main
    assert "_scheduled_dfw_bonus_roster_sync" in main
    assert 'CronTrigger(hour=5, minute=0, timezone="America/Chicago")' in main
