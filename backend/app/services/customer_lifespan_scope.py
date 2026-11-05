"""Customer Lifespan — the report's filters: period, teams, customer, who owns an account.

Iris's deck 2026-11-03. Operator decision 2026-11-04: the Date filter filters
EVERYTHING. A customer with no load in the range is out of the report, and its
loads, revenue, profit and lifespan count only inside the range. Only facts about
the customer stay true: the first load (so "new" and the cohort year still mean
something) and the status, judged at the range END with the whole history up to it.

Who owns an account (deck p.12): Active / At risk → the TEAM in charge, the team of
the customer's latest v4 load. Lost → the OWNER of its open Pipedrive REACTIVATION
deal, matched on ID_McLeod, else ``PENDING TO ASSIGN``.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, replace
from datetime import date, timedelta

from app.services.customer_lifespan_core import Customer, Month, build_customers, flow_events

ALL_START = date(2000, 1, 1)
RANGES = ("last_365", "mtd", "last_month", "ytd", "custom", "all")
RANGE_LABELS = {"last_365": "Last 12 mo", "mtd": "MTD", "last_month": "Last month", "ytd": "YTD",
                "all": "All time"}
PENDING_LABEL = "PENDING TO ASSIGN"
NO_TEAM = "NO TEAM"       # never in v4: the workbook only knows CORP / DFW
OTHER_TEAM = "OTHER"      # v4 holds person codes and "N/A" in team_id
_REAL_TEAM = re.compile(r"^(TEAM[0-9A-Z-]*|BD\d+)$")

TEAMS_SQL = "SELECT customer_id, team_id FROM customer_lifespan_customer_team"
OWNERS_SQL = "SELECT customer_code, owner_name FROM customer_lifespan_deal_owner"
OWNERS_EVER_OK_SQL = """
SELECT EXISTS (SELECT 1 FROM customer_lifespan_refresh_log WHERE kind = 'owners' AND status = 'ok')
"""


@dataclass(frozen=True)
class Period:
    key: str
    start: date
    end: date

    @property
    def label(self) -> str:
        if self.key in RANGE_LABELS:
            return RANGE_LABELS[self.key]
        return f"{self.start:%b} {self.start.day}, {self.start.year} – {self.end:%b} {self.end.day}, {self.end.year}"


def resolve_period(key: str, start: date | None, end: date | None, as_of: date) -> Period:
    """Every named range anchors on the data's as-of date. Raises ``ValueError`` when invalid."""
    if key == "last_365":
        return Period(key, as_of - timedelta(days=364), as_of)
    if key == "mtd":
        return Period(key, as_of.replace(day=1), as_of)
    if key == "last_month":
        last = as_of.replace(day=1) - timedelta(days=1)
        return Period(key, last.replace(day=1), last)
    if key == "ytd":
        return Period(key, date(as_of.year, 1, 1), as_of)
    if key == "all":
        return Period(key, ALL_START, as_of)
    if key != "custom":
        raise ValueError(f"range must be one of {list(RANGES)}")
    if start is None or end is None:
        raise ValueError("a custom range needs start and end")
    if start > end:
        raise ValueError("start must not be after end")
    # A date input emits year 0001 while someone types; nothing before the floor exists.
    return Period(key, max(start, ALL_START), max(min(end, as_of), ALL_START))


def _year_back(d: date) -> date:
    return d.replace(year=d.year - 1, day=28) if (d.month, d.day) == (2, 29) else d.replace(year=d.year - 1)


def shift_year(p: Period) -> Period | None:
    """The same period last year; "all time" has none."""
    return None if p.key == "all" else Period(p.key, _year_back(p.start), _year_back(p.end))


def team_chip(team: str | None) -> str:
    """A v4 team → its filter chip. Whatever is not a team is grouped, never dropped."""
    if team is None:
        return NO_TEAM
    return team if _REAL_TEAM.match(team) else OTHER_TEAM


def _key(customer_id: str) -> str:
    return customer_id.strip().upper()


@dataclass(frozen=True)
class Assignments:
    """``owners`` is None when Pipedrive never answered: unknown is not "nobody assigned"."""

    teams: dict[str, str]
    owners: dict[str, str] | None

    def chip(self, customer_id: str) -> str:
        return team_chip(self.teams.get(customer_id))

    def of(self, customer_id: str, status: str) -> dict:
        chip = self.chip(customer_id)
        if status != "lost":
            return {"team": chip, "assigned_to": chip, "pending_assignment": False}
        if self.owners is None:
            return {"team": chip, "assigned_to": None, "pending_assignment": False}
        owner = self.owners.get(_key(customer_id))
        return {"team": chip, "assigned_to": owner or PENDING_LABEL, "pending_assignment": not owner}


def team_chips(rows: list[dict], division: str, a: Assignments) -> list[str]:
    """The chips this division really holds: a hardcoded list hides customers (2026-11-04)."""
    wanted = None if division == "all" else division.upper()
    ids = {r["customer_id"] for r in rows if wanted is None or r["division"] == wanted}
    chips = {a.chip(i) for i in ids}
    last = [c for c in (OTHER_TEAM, NO_TEAM) if c in chips]
    return sorted(chips - set(last)) + last


def filter_rows(rows: list[dict], a: Assignments, teams: list[str] | tuple[str, ...] | None,
                customer: str | None) -> list[dict]:
    """``teams`` None = no filter; a selection with no real chip (``[""]``) = nobody."""
    wanted = None if teams is None else set(teams) - {""}
    code = _key(customer) if customer else None
    return [r for r in rows
            if (wanted is None or a.chip(r["customer_id"]) in wanted)
            and (code is None or _key(r["customer_id"]) == code)]


def scope_customers(history: list[Month], in_period: list[Month], end: date, window: int) -> list[Customer]:
    """The customers with a load in the period.

    ``in_period`` decides the population and what is counted; ``history`` (every
    month up to ``end``) gives the true first load and the flow events.
    """
    full = {c.customer_id: c for c in build_customers(history, end, window)}
    start = min((m.first_ship for m in in_period), default=end)
    out = []
    for c in build_customers(in_period, end, window):
        f = full.get(c.customer_id)
        if f is None:       # a sync landed between the two cached reads; gone on the next one
            continue
        kept = replace(c, name=f.name, first_ship=f.first_ship, cohort_year=f.cohort_year, history=f.months)
        out.append(replace(kept, reactivations=len(flow_events(kept, window, start)[1])))
    return out
