"""Test helper — blank out the DFW-marker rule before a division-leak scan.

The division-leak guards (``test_ops_portal_scope``, ``test_ceo_executive_portal``,
``test_bonus_scope``) read emitted SQL and fail if the OTHER division's ids
appear in it. Since 2026-10-28 (Sergio Hidalgo: DFW loads booked under
TEAM3) every division predicate carries the DFW-marker rule, which names both
divisions ON PURPOSE:

  CORP  ``COALESCE(br4.team, '') NOT IN ('TM1', …)``           — names TM1..TM5
  DFW   ``(… OR (br4.team_id IN ('TEAM1', …) AND br4.team IN ('TM1', …)))``
                                                               — names TEAM1..TEAM5
  ALL   ``CASE WHEN br4.team IN ('TM1', …) THEN 'TEAM-DFW' …`` — names both

Each guard strips EXACTLY these renderings and keeps scanning the rest, so
the purpose survives: a CORP id anywhere else in a DFW statement — a bound
param, a base predicate, a sub-team filter — still fails. The patterns are
built from the production literals, so a change to the rule's text breaks
the strip (and the guard goes red) instead of silently widening it.
"""

from __future__ import annotations

import re

from app.datalake import _DFW_TAG_VARIANTS, sql_str_list
from app.routers.ops_portal_overview._scope import _CORP_TEAM_LIT

_TAG_LIT = sql_str_list(_DFW_TAG_VARIANTS)

_INCLUDE = re.compile(
    r"\S+ IN " + re.escape(_CORP_TEAM_LIT) + r" AND \S+ IN " + re.escape(_TAG_LIT)
)
_EXCLUDE = re.compile(r"COALESCE\(\S+, ''\) NOT IN " + re.escape(_TAG_LIT))
_RELABEL = re.compile(r"CASE WHEN \S+ IN " + re.escape(_TAG_LIT) + r" THEN 'TEAM-DFW'")


def strip_dfw_marker_rule(sql: str) -> str:
    """``sql`` with every rendering of the DFW-marker rule replaced by a token."""
    sql = _INCLUDE.sub("<dfw-marked-corp-row>", sql)
    sql = _EXCLUDE.sub("<not-dfw-marked>", sql)
    return _RELABEL.sub("<relabel-dfw-marked>", sql)
