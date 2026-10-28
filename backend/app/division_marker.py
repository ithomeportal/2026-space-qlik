"""Division membership for the multi-division McLeod reports (DFW-marker rule).

DFW-marker rule, 2026-10-28 — see ``app.datalake.not_dfw_tagged`` for the
measurement. McLeod MX books some DFW loads under a CORP ``team_id``
(``TEAM3``) while the DFW sub-team column (``v4.team`` /
``scorecard.team_dfw``) says ``TM4``. Those rows are DFW loads.

Every report outside the ops-portal package scopes rows with
``{alias}.team_id = ANY($n)`` over a team list that is CORP-only, DFW-only or
both. ``team_membership_sql`` renders the ONE replacement predicate so the
reports cannot each grow their own spelling of the rule:

* list without ``TEAM-DFW`` (any CORP subset) →
  ``team_id = ANY($n) AND <no DFW marker>`` — the leak rows leave CORP;
* list with ``TEAM-DFW`` →
  ``(team_id = ANY($n) OR (team_id IN <CORP> AND <DFW marker>))`` — the
  leak rows join DFW, and a CORP+DFW list counts each row exactly once.

The predicate depends only on the team LIST, never on a division name, so a
caller that narrows "ALL" to ``TEAM3`` gets the CORP form automatically.
"""

from __future__ import annotations

from typing import Iterable

from app.datalake import dfw_tagged, not_dfw_tagged, pad_variants, sql_str_list

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

    >>> team_membership_sql("br4", ["TEAM3"], 1)
    "br4.team_id    = ANY($1) AND COALESCE(br4.team, '') NOT IN ('TM1', 'tm1', 'TM2', 'tm2', 'TM3', 'tm3', 'TM4', 'tm4', 'TM5', 'tm5')"
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

    A CORP-team row carrying a DFW marker is labelled by its marker (``TM4``),
    the same pill the DFW view files it under. ``alias=""`` renders bare
    column names, for a FROM without an alias.
    """
    pre = f"{alias}." if alias else ""
    marker = f"{pre}{marker_col}"
    return (
        f"CASE WHEN TRIM({pre}team_id) = '{DFW_TEAM_ID}' OR {dfw_tagged(marker)} "
        f"THEN TRIM({marker}) ELSE TRIM({pre}team_id) END"
    )


def division_team_id_sql(alias: str, marker_col: str = "team") -> str:
    """The team_id a row BELONGS to — ``TEAM-DFW`` for a DFW-marked CORP row.

    For by-team GROUP BYs and row tables over ``team_id``: without it a leak
    row that ``team_membership_sql`` let into the DFW view would still group
    (and display) as ``TEAM3``. ``alias=""`` renders bare column names.
    """
    pre = f"{alias}." if alias else ""
    return (
        f"CASE WHEN {dfw_tagged(f'{pre}{marker_col}')} "
        f"THEN '{DFW_TEAM_ID}' ELSE TRIM({pre}team_id) END"
    )
