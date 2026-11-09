"""Booker Performance Scorecard — Bruno PDF 2026-11-09 ("space -- Booker
Performance Scorecard"), Scorecard tab R1:

  Add ``is_tonu IN ('N', 'null')`` (v4) to every KPI, the 10-week chart and the
  Orders table; the Rank tab is built from the Scorecard, so it follows.

⚠ 'null' is SQL NULL, not the string: v4.is_tonu holds only 'N' (no order
after 2026-08-21), NULL (every order since) and 'Y'. A literal
``IN ('N','null')`` would keep no current order and the report would go EMPTY.
"""

from __future__ import annotations

import inspect
import re
from datetime import date

from app.routers import booker_scorecard as bs

_TONU_RE = re.compile(r"COALESCE\(\s*br\.is_tonu\s*,\s*'N'\s*\)\s*=\s*'N'")


def _cte() -> str:
    return bs._base_sql(
        [],
        start=date(2026, 11, 1),
        end=date(2026, 11, 9),
        contract_types=[],
        customers=[],
        posted_by=[],
    )


def test_tonu_predicate_is_in_the_rate_conf_cte():
    """Inside rate_conf — the ONE universe every endpoint (summary KPIs,
    weekly chart, orders + totals, filters, scenario, rank, rank/last-week,
    the public TV board) builds from."""
    cte = _cte()
    rate_conf = cte.split("sc AS (")[0]
    assert _TONU_RE.search(rate_conf), "TONU filter missing from rate_conf"


def test_tonu_predicate_holds_with_every_optional_filter():
    params: list = []
    cte = bs._base_sql(
        params,
        start=date(2026, 11, 1),
        end=date(2026, 11, 9),
        contract_types=["Spot"],
        customers=["ACME"],
        posted_by=["Jane Doe"],
    )
    assert _TONU_RE.search(cte.split("sc AS (")[0])


def test_null_means_sql_null_never_the_string():
    """The PDF's spelling, taken literally, empties the report."""
    src = inspect.getsource(bs)
    code = "\n".join(
        line for line in src.splitlines() if not line.strip().startswith("--")
    )
    assert not re.search(r"is_tonu\s+IN\s*\(", code, re.IGNORECASE)
    assert "'null'" not in code.replace("'null' in the PDF", "")


def test_tonu_predicate_lives_in_exactly_one_place():
    """A second copy would mean a second population (§16 / §96)."""
    assert len(_TONU_RE.findall(inspect.getsource(bs))) == 1


def test_every_universe_endpoint_builds_through_base_sql():
    """Rank follows the Scorecard only because it shares the helper."""
    for fn in (bs.filters, bs.summary, bs.orders, bs.weekly, bs._rank_payload):
        assert "_base_sql(" in inspect.getsource(fn), fn.__name__
