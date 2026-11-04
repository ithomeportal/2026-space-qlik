"""An EXTERNAL_CONSULTANT in Time-Off is active ("may log in") but is not staff.

`isActive` means login across the fleet, so it can no longer be read as "employee".
Every Time-Off read of this report shares `_TIMEOFF_EXCLUDE`, so the panels stay
in agreement (§16), and the monthly snapshot reads the same headcount (§69).
"""

from __future__ import annotations

import asyncio
import re

from app.routers import exec_meeting_recruitment as emr


class _Pool:
    """Applies the SQL's role predicate to rows, so dropping it fails a count."""

    def __init__(self, rows):
        self.rows = rows
        self.sql = []

    async def fetch(self, sql, *_args):
        self.sql.append(sql)
        excludes = re.search(r"role::text\s*(?:<>|IS DISTINCT FROM)\s*'EXTERNAL_CONSULTANT'", sql)
        return [
            r for r in self.rows if not (excludes and r.get("role") == "EXTERNAL_CONSULTANT")
        ]


ROWS = [
    {"department": "Finance", "role": "COWORKER"},
    {"department": "Finance", "role": "COWORKER"},
    {"department": "Finance", "role": "EXTERNAL_CONSULTANT"},
    {"department": "External Consultants", "role": "EXTERNAL_CONSULTANT"},
]


def test_consultant_is_not_in_the_headcount():
    counts = asyncio.run(emr.active_headcount_by_department(_Pool(ROWS)))
    assert counts == {"Finance": 2}


def test_the_exclusion_lives_in_the_shared_fragment():
    assert "EXTERNAL_CONSULTANT" in emr._TIMEOFF_EXCLUDE


def test_role_is_compared_as_text():
    # Compared as the enum, a label missing from a database would raise 22P02 and
    # take the whole report down instead of excluding nobody.
    assert "role::text" in emr._TIMEOFF_EXCLUDE
    assert re.search(r"(?<!::text)\brole\s*(=|<>)", emr._TIMEOFF_EXCLUDE) is None
