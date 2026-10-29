"""Division membership for the multi-division McLeod reports (DFW rule).

DFW rule — see ``app.datalake.dfw_tagged`` for the measurement. McLeod MX
books DFW loads of a shared customer under a CORP ``team_id`` (``TEAM3``, the
salesperson); the order's revenue code ``DFW`` says they are DFW loads (rule
from McLeod, 2026-10-29; until then the TM4 sub-team marker decided, and it
still does for an order the revenue-code mirror has not reached). They land
in DFW team TM4.

Every report outside the ops-portal package scopes rows with
``{alias}.team_id = ANY($n)`` over a team list that is CORP-only, DFW-only or
both. ``team_membership_sql`` renders the ONE replacement predicate so the
reports cannot each grow their own spelling of the rule:

* list without ``TEAM-DFW`` (any CORP subset) →
  ``team_id = ANY($n) AND NOT <DFW rule>`` — the leak rows leave CORP;
* list with ``TEAM-DFW`` →
  ``(team_id = ANY($n) OR (team_id IN <CORP> AND <DFW rule>))`` — the
  leak rows join DFW, and a CORP+DFW list counts each row exactly once.

The predicate depends only on the team LIST, never on a division name, so a
caller that narrows "ALL" to ``TEAM3`` gets the CORP form automatically.
"""

from __future__ import annotations

from typing import Iterable

from app.datalake import (
    DFW_REVENUE_SUB_TEAM,
    dfw_tagged,
    not_dfw_tagged,
    pad_variants,
    sql_str_list,
)

CORP_TEAM_IDS = ("TEAM1", "TEAM2", "TEAM3", "TEAM4", "TEAM5")
DFW_TEAM_ID = "TEAM-DFW"


def _corp_team_lit(alias: str) -> str:
    # team_id is varchar(8), stored both padded and unpadded (pad_variants).
    return f"{alias}.team_id IN {sql_str_list(pad_variants(CORP_TEAM_IDS, width=8))}"


def team_membership_sql(
    alias: str,
    teams: Iterable[str],
    p_teams: int,
    marker_col: str = "team",
) -> str:
    """Membership predicate for ``teams`` bound as ``$p_teams``.

    ``marker_col`` is ``team`` on ``mcleod_gld_budget_report_v4`` and
    ``team_dfw`` on ``mcleod_gld_scorecard_incidents_portal``.

    >>> team_membership_sql("br4", ["TEAM3"], 1).startswith(
    ...     "br4.team_id    = ANY($1) AND NOT (CASE WHEN br4.company_id IN ('TMS3')")
    True
    >>> team_membership_sql("sc", ["TEAM-DFW"], 2, "team_dfw").startswith(
    ...     "(sc.team_id    = ANY($2) OR (sc.team_id IN ('TEAM1', 'TEAM1   ', ")
    True
    """
    marker = f"{alias}.{marker_col}"
    base = f"{alias}.team_id    = ANY(${p_teams})"
    if DFW_TEAM_ID not in {t.strip().upper() for t in teams}:
        return f"{base} AND {not_dfw_tagged(marker)}"
    return f"({base} OR ({_corp_team_lit(alias)} AND {dfw_tagged(marker)}))"


def team_label_sql(alias: str, marker_col: str = "team") -> str:
    """Team label for a mixed CORP+DFW view: DFW rows by sub-team, else team_id.

    A TEAM-DFW row is labelled by its own marker; a CORP-team row the
    revenue-code rule makes DFW is labelled ``TM4`` (Diego 2026-10-29), the
    same pill the DFW view files it under. ``alias`` is the row's alias or,
    for a FROM without one, its table name — never bare (``_row_of``).
    """
    marker = f"{alias}.{marker_col}"
    return (
        f"CASE WHEN TRIM({alias}.team_id) = '{DFW_TEAM_ID}' THEN TRIM({marker}) "
        f"WHEN {_corp_team_lit(alias)} AND {dfw_tagged(marker)} "
        f"THEN '{DFW_REVENUE_SUB_TEAM}' ELSE TRIM({alias}.team_id) END"
    )


def division_team_id_sql(alias: str, marker_col: str = "team") -> str:
    """The team_id a row BELONGS to — ``TEAM-DFW`` for a DFW CORP-team row.

    For by-team GROUP BYs and row tables over ``team_id``: without it a row
    that ``team_membership_sql`` let into the DFW view would still group (and
    display) as ``TEAM3``. ``alias`` as in ``team_label_sql``.
    """
    return (
        f"CASE WHEN {_corp_team_lit(alias)} AND {dfw_tagged(f'{alias}.{marker_col}')} "
        f"THEN '{DFW_TEAM_ID}' ELSE TRIM({alias}.team_id) END"
    )


def dfw_sub_team_sql(alias: str, marker_col: str = "team") -> str:
    """A DFW-view row's sub-team (pill): ``TM4`` for a DFW CORP-team row, else its marker.

    For DFW reports that filter or group on ``TRIM(<alias>.team)``: a CORP-team
    row the revenue-code rule lets in goes to TM4 whatever marker McLeod gave
    it (Diego 2026-10-29) — 0320800 says TM3 and 0337553 TM2 (measured
    2026-10-29). ``alias`` as in ``team_label_sql``.
    """
    return (
        f"CASE WHEN {_corp_team_lit(alias)} AND {dfw_tagged(f'{alias}.{marker_col}')} "
        f"THEN '{DFW_REVENUE_SUB_TEAM}' ELSE TRIM({alias}.{marker_col}) END"
    )
