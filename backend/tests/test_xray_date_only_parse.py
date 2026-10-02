"""XRay CORP / DFW chart buckets must be parsed as LOCAL dates (§116).

The API sends buckets as ``date.isoformat()`` — "YYYY-MM-DD". ``new Date(that)``
is UTC midnight, i.e. the previous day in CST: every Trends / Contract-Spot /
Risk axis label read one day early, and Trends' "current month" average put the
1st of each month in the previous month (on Jan 1, in the previous YEAR).
Fixed 2026-10-01 with ``lib/local-date.ts``'s ``parseLocalDate``.

No JS test runner (frontend/CLAUDE.md) — these guards read the TSX.
"""

from __future__ import annotations

import os
import re

import pytest

_FE = os.path.join(os.path.dirname(__file__), "..", "..", "frontend")

_TABS = [
    f"app/reports/{report}/tabs/{tab}.tsx"
    for report in ("xray-corp-mng", "xray-dfw-mng")
    for tab in ("Trends", "ContractSpot", "Risk")
]

# A Date built straight from an API string: new Date(s) / new Date(bucket) /
# new Date(d.bucket). `new Date()` (now) and `new Date(y, m, d)` are fine.
_RAW_PARSE = re.compile(r"new Date\(\s*(?:s|bucket|\w+\.bucket)\s*\)")


def _read(rel: str) -> str:
    with open(os.path.join(_FE, rel), encoding="utf-8") as fh:
        return fh.read()


@pytest.mark.parametrize("rel", _TABS)
def test_no_tab_parses_a_bucket_string_with_new_date(rel):
    src = _read(rel)
    assert not _RAW_PARSE.search(src), f"{rel}: date-only bucket parsed as UTC (§116)"
    assert 'import { parseLocalDate } from "@/lib/local-date"' in src


def test_the_helper_builds_a_local_date_from_the_parts():
    """The whole fix is this branch — `new Date(y, m - 1, d)` is LOCAL midnight."""
    src = _read("lib/local-date.ts")
    assert r"/^(\d{4})-(\d{2})-(\d{2})$/" in src
    assert "new Date(Number(m[1]), Number(m[2]) - 1, Number(m[3]))" in src
