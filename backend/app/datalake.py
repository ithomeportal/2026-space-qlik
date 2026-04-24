"""Shared helpers for querying aivn_datalake_gold McLeod tables.

Kept in one place so the sargable-padding pattern cannot drift between
custom-report routers. The 2026-04-24 "Only TEAM3 shows" bug happened
because three routers each copy-pasted their own `_pad_variants` with
a hardcoded 3-space pad, then the helper was used against varchar(4)
`company_id` (which pads to 'TMS ' — 1 space). Single source of truth
prevents the next drift.
"""

from __future__ import annotations


def pad_variants(values, *, width: int) -> list[str]:
    """Expand each value into (unpadded, right-padded-to-column-width) twins.

    McLeod source data in `aivn_datalake_gold.mcleod_gld_*` arrives
    inconsistently: some values unpadded (`'TEAM1'`), some right-padded to
    the declared varchar(N) width (`'TEAM1   '` for varchar(8), `'TMS '` for
    varchar(4)). The padding amount depends on the COLUMN width, not a
    constant — callers MUST pass the column's declared `character_maximum_
    length` as `width`.

    Using `col = ANY(pad_variants(values, width=N))` stays sargable (btree
    index on `col` is usable). Wrapping `col` in `TRIM()` blocks index use
    and forces a full table scan — don't do it. See CLAUDE.md "Sargability
    rule" for background.

    Widths for the common McLeod columns (source: information_schema):

    | Column                          | varchar(N) |
    |---------------------------------|------------|
    | team_id (v4, scorecard)         | 8          |
    | company_id (v4, scorecard, mov) | 4          |
    | status (v4, scorecard, mov)     | 1          |
    | stop_type (scorecard)           | 2          |
    | edi_standard_code (scorecard)   | 40         |
    | id (v4, scorecard)              | 8          |
    | id (movement)                   | 32         |

    >>> pad_variants(("TEAM1", "TEAM2"), width=8)
    ['TEAM1', 'TEAM1   ', 'TEAM2', 'TEAM2   ']
    >>> pad_variants(("TMS", "TMS3"), width=4)
    ['TMS', 'TMS ', 'TMS3']
    >>> pad_variants(("D", "P"), width=1)
    ['D', 'P']
    """
    seen: set[str] = set()
    out: list[str] = []
    for v in values:
        for cand in (v, v.ljust(width)):
            if cand not in seen:
                seen.add(cand)
                out.append(cand)
    return out
