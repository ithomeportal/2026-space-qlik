"""Booker Performance Scorecard — Bruno PDF 2026-09-03 (Rank tab only).

R1  "Broken Threshold" becomes "Compliance Threshold" = 1 − broken, on the Rank
    tab too. The Scorecard tab's KPI card was renamed on 2026-08-31; the Rank
    tab, shipped the same day, kept Bruno's original wording and was flagged
    rather than silently harmonised. He has now asked for it.
R2  The Rank tab's week runs SATURDAY → FRIDAY. This tab only.
R3  The Rank tab shows BOOKERS ONLY — `RANK_ROSTER`, his own 15-name list.

Measured on live gold before shipping (TEAM-DFW, the ranked week 22-28 Aug
2026 — the endpoint itself was replayed, not a paraphrase of its SQL):

    26 names posted Rate Confs that week; 11 are on the roster. Across BOTH
    weeks the tab renders 12 rows (Carlos Padilla booked only 15-21 Aug).
    Dropped, in volume order: ARMANDO CALVILLO 37, GYNETH DOMINGUEZ 24,
    KARLA TREVINO 21, JIMENA VIVANCO 18, RICARDO MENDEZ 8, ALI CISNEROS 5,
    EDUARDO AVILA 5, EVELYN RODRIGUEZ 5, JORGE HERRERA 5, JORGE HERNANDEZ 4,
    KRAUFEERG DERFLINGHER 4, JENNIFER ALANIS 3, JAIRO MARTINEZ 1,
    JESSICA RODRIGUEZ 1, MAURICIO MAHUAD 1.
    Calvillo was the week's #2 by volume, and rank 2 on the tab as it stood.
    He is absent from `podium_top.BOOKER_NAMES` as well,
    which is the independent second opinion that made dropping him safe.
    Sat-Fri vs Mon-Sun moves the totals slightly (Eugenio Miranda 45 → 44).

⚠ Three assertions here are about a POPULATION, not a value. Every individual
number in a wrongly-scoped table is still correct — that is the §100 failure
mode — so they assert who is in the row set and what "of N" counts, and they
are mutation-checked against the obvious wrong implementations:

  * restricting AFTER ranking      → ranks come out 1, 3, 4, 6 with gaps
  * restricting the CURRENT week only → last week's league is a different one,
    so every `rank_delta` compares two different populations
  * restricting via the `posted_by` predicate in SQL → §75, re-ranks a
    one-person universe while every row-level assertion still passes
"""

from __future__ import annotations

import inspect
import re
from datetime import date, datetime, timedelta

from app.routers import booker_scorecard as bs

from test_booker_scorecard_bruno_2026_08_31 import _RANK, _drive


_SOURCE = inspect.getsource(bs)

# Monday. Under Sat-Fri the pair is 15-21 Aug (prev) and 22-28 Aug (current) —
# the same two windows the live measurement in the docstring was taken over.
PINNED = date(2026, 8, 31)


def _row(order_id, name, when, carrier_cost=500.0):
    return {"order_id": order_id, "carrier_cost": carrier_cost,
            "posted_by": name, "posted_date": when}


# ==========================================================================
# R2 — the week is Saturday → Friday  (⚠ SUPERSEDED 2026-10-06)
# ==========================================================================
#
# Bruno's 2026-10-06 PDF replaced the Sat-Fri calendar week with the BOOKING
# WEEK (Fri 17:01 → Fri 17:00) and made the in-progress week the default. The
# guards that lived here — the boundary, "only the Rank tab moved", "never
# rank the in-progress week" — are rewritten against the new rule in
# test_booker_scorecard_bruno_2026_10_06.py rather than kept green against a
# helper that no longer exists. The R1/R3 assertions below still hold; their
# rank calls pin the 22-28 Aug window as a custom range (`_RANK`).


# ==========================================================================
# R3 — bookers only
# ==========================================================================


def _mixed_rows():
    """Roster and non-roster bookers, in both weeks.

    ARMANDO CALVILLO outbooks everyone, exactly as he does live: if the
    restriction is missing he takes rank 1 and the assertions below cannot be
    read as passing by accident.
    """
    rows = []
    n = 0
    for name, cur, prev in (
        ("ARMANDO CALVILLO", 9, 9),      # not a booker — the live rank 2
        ("GYNETH DOMINGUEZ", 6, 6),      # not a booker
        ("EUGENIO MIRANDA", 5, 5),
        ("DANIEL SALAZAR", 3, 3),
        ("JUAN REYNA", 1, 1),
    ):
        for _ in range(cur):
            n += 1
            rows.append(_row(f"C{n}", name, datetime(2026, 8, 25, 9, 0)))
        for _ in range(prev):
            n += 1
            rows.append(_row(f"P{n}", name, datetime(2026, 8, 18, 9, 0)))
    return rows


def test_a_non_booker_gets_no_row():
    _, resp = _drive(bs.rank, rows=_mixed_rows(), today=PINNED, **_RANK)
    names = {r["booker"] for r in resp["data"]["rows"]}
    assert names == {"EUGENIO MIRANDA", "DANIEL SALAZAR", "JUAN REYNA"}
    assert "ARMANDO CALVILLO" not in names


def test_the_restriction_runs_before_ranking_so_ranks_have_no_gaps():
    """⚠ THE assertion of this round. Hiding the rows afterwards leaves the
    ranks computed over the full population: 1, 3, 4, 6 … with the winners
    missing, under an "of N" counting people the table refuses to show. Every
    individual number would still be correct."""
    _, resp = _drive(bs.rank, rows=_mixed_rows(), today=PINNED, **_RANK)
    rows = resp["data"]["rows"]
    assert [r["rank"] for r in rows] == [1, 2, 3]
    assert [r["booker"] for r in rows] == [
        "EUGENIO MIRANDA", "DANIEL SALAZAR", "JUAN REYNA",
    ]
    # "of N" counts the league, not the window's whole cast.
    assert resp["data"]["total_bookers"] == 3


def test_the_restriction_applies_to_the_previous_week_too():
    """⚠ Restricting only the current week leaves `prev_rank` computed over a
    DIFFERENT population, so every arrow compares two different leagues — and
    every one of them still renders plausibly. Here the non-roster pair sit
    above Eugenio last week: unrestricted, his previous rank is 3 and the tab
    would claim he climbed two places for doing exactly the same work."""
    _, resp = _drive(bs.rank, rows=_mixed_rows(), today=PINNED, **_RANK)
    top = resp["data"]["rows"][0]
    assert top["booker"] == "EUGENIO MIRANDA"
    assert top["prev_rank"] == 1
    assert top["rank_delta"] == 0, "the two weeks ranked different populations"


def test_the_picker_only_offers_names_the_table_can_show():
    """A picker listing somebody the table refuses to render is a control that
    empties its own table."""
    _, resp = _drive(bs.rank, rows=_mixed_rows(), today=PINNED, **_RANK)
    data = resp["data"]
    assert "ARMANDO CALVILLO" not in data["bookers"]
    assert set(data["bookers"]) == {r["booker"] for r in data["rows"]}
    assert data["bookers"] == data["roster"]


def test_the_roster_restriction_is_not_pushed_into_the_sql():
    """§75 — the same trap `posted_by` fell into. A stub pool returns the same
    rows whatever the statement says, so a roster predicate pushed into
    `_base_sql` would pass every assertion above while re-ranking a filtered
    universe in production. Read the emitted SQL instead.

    The second half proves the scan can see a known positive (§91).
    """
    pool, _ = _drive(bs.rank, rows=_mixed_rows(), today=PINNED, **_RANK)
    rank_sql = "\n".join(pool.sqls)
    assert "TRIM(rp.posted_by_name) = ANY(" not in rank_sql
    for name in bs.RANK_ROSTER:
        assert name.upper() not in rank_sql.upper(), name

    pool2, _ = _drive(bs.summary, range="mtd", start_date=None, end_date=None,
                      contract_type=None, customer_name=None,
                      posted_by=["EUGENIO MIRANDA"], adjustment=0.0)
    assert "TRIM(rp.posted_by_name) = ANY(" in "\n".join(pool2.sqls), (
        "the scan cannot see the predicate at all — the check above is vacuous"
    )


def test_the_roster_match_survives_mcleods_spellings():
    """⚠ The restriction goes through the shared normaliser, never string
    equality: three of Bruno's 15 spellings differ from McLeod's, and a strict
    compare would drop those people from their own report."""
    rows = [
        _row("A", "ANDRES SAN MIGUEL", datetime(2026, 8, 25, 9, 0)),
        _row("B", "Montoya, Anthares", datetime(2026, 8, 25, 9, 0)),
        _row("C", "eugenio miranda", datetime(2026, 8, 25, 9, 0)),
    ]
    _, resp = _drive(bs.rank, rows=rows, today=PINNED, **_RANK)
    assert len(resp["data"]["rows"]) == 3
    # ⚠ Normalisation is a MATCH KEY, never a display value — the table shows
    # what McLeod actually recorded.
    assert {r["booker"] for r in resp["data"]["rows"]} == {
        "ANDRES SAN MIGUEL", "Montoya, Anthares", "eugenio miranda",
    }


def test_the_roster_is_still_not_the_podium_roster():
    """§69/§99 — now that the roster is a POPULATION and not just a picker
    order, merging the two lists would rewrite who each report is about."""
    from app.routers.podium_top import BOOKER_NAMES

    assert set(bs.RANK_ROSTER) != set(BOOKER_NAMES)
    assert len(bs.RANK_ROSTER) == 15
    # The name the round deliberately drops is on neither list.
    from app.booker_names import matches_roster, roster_keys

    for keys in (roster_keys(bs.RANK_ROSTER), roster_keys(BOOKER_NAMES)):
        assert not matches_roster("ARMANDO CALVILLO", keys)


# ==========================================================================
# R1 — Compliance Threshold on the Rank tab
# ==========================================================================


def test_the_rank_row_carries_compliance_not_just_broken():
    rows = [
        _row("A", "EUGENIO MIRANDA", datetime(2026, 8, 25, 9, 0), 900.0),
        _row("B", "EUGENIO MIRANDA", datetime(2026, 8, 25, 9, 0), 1100.0),
        _row("C", "EUGENIO MIRANDA", datetime(2026, 8, 25, 9, 0), 1200.0),
        _row("D", "EUGENIO MIRANDA", datetime(2026, 8, 25, 9, 0), 700.0),
    ]
    thresholds = {"A": 1000.0, "B": 1000.0, "C": 1000.0, "D": 1000.0}
    _, resp = _drive(bs.rank, rows=rows, today=PINNED,
                     thresholds=thresholds, **_RANK)
    row = resp["data"]["rows"][0]
    assert row["threshold_orders"] == 4
    assert row["broken_threshold"] == 2
    assert row["compliance_threshold_pct"] == 0.5
    assert row["compliance_threshold_pct"] == 1.0 - row["broken_threshold_pct"]
    # ⚠ A FRACTION. fmtPct multiplies by 100 and an already-scaled value prints
    # 100x wrong with no error (§95).
    assert 0.0 <= row["compliance_threshold_pct"] <= 1.0


def test_the_count_and_the_percentage_span_one_population():
    """§96 — the cell prints "N/M" beside a percentage. `compliant_threshold`
    is `threshold_orders − broken_threshold`, computed off the same two
    counters, so the pair can never describe two different populations.

    ⚠ NOT `under_threshold`: an order sitting exactly ON its threshold is
    compliant but contributes nothing to Cost Saving, so the strictly-under
    count would print 2/4 beside 75%.
    """
    rows = [
        _row("A", "EUGENIO MIRANDA", datetime(2026, 8, 25, 9, 0), 900.0),
        _row("B", "EUGENIO MIRANDA", datetime(2026, 8, 25, 9, 0), 1000.0),
        _row("C", "EUGENIO MIRANDA", datetime(2026, 8, 25, 9, 0), 1000.0),
        _row("D", "EUGENIO MIRANDA", datetime(2026, 8, 25, 9, 0), 1200.0),
    ]
    thresholds = dict.fromkeys("ABCD", 1000.0)
    st = bs._threshold_stats(rows, thresholds)
    assert st["threshold_orders"] == 4
    assert st["broken_threshold"] == 1
    assert st["compliant_threshold"] == 3
    assert st["under_threshold"] == 1, "the ON-threshold orders are not 'under'"
    assert st["compliant_threshold"] / st["threshold_orders"] == (
        st["compliance_threshold_pct"]
    )


def test_compliance_stays_none_on_the_rank_row_when_ap_is_down():
    """None, never 0.0 — a 0% compliance row is an alarm, and an outage must
    not raise one."""
    rows = [_row("A", "EUGENIO MIRANDA", datetime(2026, 8, 25, 9, 0))]
    # `None`, not `{}` — the AP source being DOWN is a different answer from it
    # knowing nothing about these orders.
    _, resp = _drive(bs.rank, rows=rows, today=PINNED, thresholds=None, **_RANK)
    row = resp["data"]["rows"][0]
    assert row["bookings"] == 1, "the ranking must survive an AP outage"
    for key in ("compliance_threshold_pct", "compliant_threshold",
                "broken_threshold", "cost_saving"):
        assert row[key] is None, key


def test_the_ui_renders_compliance_and_never_broken_on_this_tab():
    """⚠ The two are 1 − each other, so the wrong field renders entirely
    plausibly and inverts every verdict on the tab — there is no error and no
    out-of-range value to catch it. Read the component.

    Whole-file scan with `re.S`: the JSX for one cell spans several lines, so a
    line-based check reports clean while the wrong field is bound (§96).
    """
    tsx = (
        bs.__file__.rsplit("/backend/", 1)[0]
        + "/frontend/app/reports/booker-performance-scorecard/RankTable.tsx"
    )
    with open(tsx, encoding="utf-8") as fh:
        src = fh.read()

    assert 'label="Compliance Threshold"' in src
    assert 'label="Broken Threshold"' not in src
    # The rendered value and its sub-count both come from the compliance pair.
    assert re.search(r"fmtPct\(r\.compliance_threshold_pct\)", src)
    assert re.search(r"fmtCount\(r\.compliant_threshold\)", src)
    assert "fmtPct(r.broken_threshold_pct)" not in src
    # `broken_threshold` survives only as the AP-outage sentinel, which is a
    # presence check and not a rendered number.
    assert src.count("r.broken_threshold") == 1

    # The caption states the window and the population — a table that silently
    # disagrees with the filter bar above it reads as a bug.
    # Since 2026-10-06 the window is the booking week, stated to the minute.
    assert "Fri 5:01 PM" in src and "Sat–Fri" not in src and "Mon–Sun" not in src
    assert "Bookers only" in src or "bookers only" in src
