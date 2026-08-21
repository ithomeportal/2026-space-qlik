"""Division scope — which teams a portal covers, and which column names them.

Part of the ``ops_portal_overview`` package. Added 2026-08-21 for the DFW
portal (Bruno PDF "space -- Ops Portal DFW", Request 3).

Until now every endpoint in this package was CORP-only: the base predicate was
``team_id = ANY(CORP_TEAMS)`` and the "Team" column WAS ``team_id``. The DFW
portal keeps every metric and every panel but changes exactly two things:

  * the division is one ``team_id`` value, ``'TEAM-DFW'`` (16,034 orders YTD,
    the largest team in v4), instead of the five ``TEAM1..TEAM5`` values;
  * the team a row is attributed to lives in a DIFFERENT COLUMN — ``v4.team``
    ∈ {TM1..TM5} — because under DFW ``team_id`` is constant.

So a scope is (base division, sub-team column, sub-team values). Everything
else — companies, statuses, the OILTEX exclusion, dates, lanes, carriers and
every metric — is identical, which is why this is a parameter rather than a
second copy of the package (§7.1: 3rd copy ⇒ build a factory).

⚠ ``CORP_SCOPE`` is the default EVERYWHERE. Passing it must emit byte-identical
SQL to the pre-2026-08-21 code — that is asserted by
``tests/test_ops_portal_scope.py`` against a captured baseline, because the
five live CORP portals share these helpers and a drift here is silent.

⚠ Column widths differ and it matters for correctness, not just speed:
``team_id`` is ``varchar(8)`` and McLeod stores it BOTH padded and unpadded, so
it goes through ``pad_variants``. ``team`` and ``team_dfw`` are ``varchar(512)``
and are stored unpadded — but ``v4.team`` does carry mixed case ('tm4' on 2
rows, measured 2026-08-21), so those go through case variants instead. Getting
this wrong deletes rows rather than erroring (§75).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

from ._constants import CORP_TEAMS, DFW_SUB_TEAMS, DFW_TEAM


@dataclass(frozen=True)
class DivisionScope:
    """One division's team predicate and team-column naming.

    ``base_teams``   — the ``v4.team_id`` values that define the division.
    ``sub_teams``    — the values the UI shows in the "Team" column / pills.
    ``v4_team_col``  — the ``mcleod_gld_budget_report_v4`` column holding them.
    ``sc_team_col``  — the same dimension on the scorecard/incidents tables.
    ``padded_sub_teams`` — True when the sub-team column is a narrow, McLeod
                     right-padded ``varchar`` (``team_id``); False when it is a
                     wide unpadded one that needs case variants instead.
    ``has_budget``   — whether ``daily_production_budget_report`` carries rows
                     for this division. DFW: 0 of its 15 customers appear
                     there (measured 2026-08-21), so every budget panel would
                     render zeros — which is why Bruno's PDF removes them all.
    """

    key: str
    label: str
    base_teams: tuple[str, ...]
    sub_teams: tuple[str, ...]
    v4_team_col: str
    sc_team_col: str
    padded_sub_teams: bool
    has_budget: bool


CORP_SCOPE = DivisionScope(
    key="corp",
    label="CORP",
    base_teams=CORP_TEAMS,
    sub_teams=CORP_TEAMS,
    v4_team_col="team_id",
    sc_team_col="team_id",
    padded_sub_teams=True,
    has_budget=True,
)

DFW_SCOPE = DivisionScope(
    key="dfw",
    label="DFW",
    base_teams=(DFW_TEAM,),
    sub_teams=DFW_SUB_TEAMS,
    v4_team_col="team",
    sc_team_col="team_dfw",
    padded_sub_teams=False,
    has_budget=False,
)

SCOPES: dict[str, DivisionScope] = {s.key: s for s in (CORP_SCOPE, DFW_SCOPE)}


def case_variants(values: Sequence[str]) -> list[str]:
    """Upper+lower spellings of each value, de-duplicated, order preserved.

    For unpadded wide columns (``v4.team``), where McLeod's data is not
    case-clean: 'tm4' appears on 2 rows against 16,312 'TM4'. Emitting both
    spellings into the bound array keeps the predicate sargable — wrapping the
    column in ``UPPER()`` would not be (§ datalake TRIM sargability).
    """
    out: list[str] = []
    for v in values:
        for variant in (v.upper(), v.lower()):
            if variant not in out:
                out.append(variant)
    return out


def scope_of(request) -> DivisionScope:
    """The division scope for this request — ``CORP_SCOPE`` unless pinned.

    ``ops_portal_overview_dfw.py`` sets ``request.state.opp_scope`` before
    calling an endpoint function directly, exactly as the CORP team clones pin
    ``team=``. It is request-scoped state, never module state, so concurrent
    CORP and DFW requests cannot see each other's scope.

    Deliberately NOT a query parameter: a client-settable scope would let any
    DFW user widen themselves onto CORP data.
    """
    state = getattr(request, "state", None)
    return getattr(state, "opp_scope", CORP_SCOPE) if state is not None else CORP_SCOPE
