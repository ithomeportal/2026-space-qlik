"""Test helper — blank out the DFW rule before a division-leak scan.

The division-leak guards (``test_ops_portal_scope``, ``test_ceo_executive_portal``,
``test_bonus_scope``) read emitted SQL and fail if the OTHER division's ids
appear in it. Since 2026-10-28 (Sergio Hidalgo: DFW loads booked under
TEAM3) every division predicate carries the DFW rule — since 2026-10-29 the
revenue-code rule (``app.datalake.dfw_tagged``) — which names both divisions
ON PURPOSE (its marker fallback lists TM1..TM5, the CORP-row test TEAM1..5):

  <tagged>  ``COALESCE((SELECT … revenue_code_id … ), x.team IN ('TM1', …), FALSE)``
  CORP      ``NOT <tagged>``
  DFW       ``(… OR (x.team_id IN ('TEAM1', …) AND <tagged>))``
  pills     ``CASE WHEN x.team_id IN ('TEAM1', …) AND <tagged> THEN 'TM4' …``
  ALL       ``CASE WHEN x.team_id IN ('TEAM1', …) AND <tagged> THEN 'TEAM-DFW' …``

Each guard strips EXACTLY these renderings and keeps scanning the rest, so
the purpose survives: a CORP id anywhere else in a DFW statement — a bound
param, a base predicate, a sub-team filter — still fails. The patterns are
rendered by the production helper itself, so a change to the rule's text
breaks the strip (and the guard goes red) instead of silently widening it.
"""

from __future__ import annotations

import re

from app.datalake import dfw_tagged
from app.routers.ops_portal_overview._scope import _CORP_TEAM_LIT

_ROW, _COL = "ROWREFXYZ", "COLREFXYZ"
# The helper's own rendering, with the row/column slots opened to any token.
_TAGGED_RE = (
    re.escape(dfw_tagged(f"{_ROW}.{_COL}"))
    .replace(re.escape(f"{_ROW}.{_COL}"), r"\S+")
    .replace(_ROW, r"\S+")
)

_INCLUDE = re.compile(r"\S+ IN " + re.escape(_CORP_TEAM_LIT) + " AND " + _TAGGED_RE)
_EXCLUDE = re.compile("NOT " + _TAGGED_RE)
_TAGGED = re.compile(_TAGGED_RE)


def strip_dfw_marker_rule(sql: str) -> str:
    """``sql`` with every rendering of the DFW rule replaced by a token."""
    sql = _INCLUDE.sub("<dfw-marked-corp-row>", sql)
    sql = _EXCLUDE.sub("<not-dfw-marked>", sql)
    return _TAGGED.sub("<dfw-tagged>", sql)
