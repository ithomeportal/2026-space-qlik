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


def sql_str_list(values) -> str:
    """Render string constants as a SQL parenthesised list: ``('A', 'B')``.

    ⚠ This exists because ``f"... IN {some_tuple!r}"`` is NOT a SQL list — it is
    a Python repr that only *looks* like one. A one-element tuple reprs with a
    trailing comma, ``('TEAM-DFW',)``, which Postgres rejects with
    ``42601 syntax error at or near ")"``.

    The trap is that the bug is invisible until a scope happens to have exactly
    one value. Rendering CORP's five team ids gave valid SQL for months; the DFW
    division added on 2026-08-21 is a single ``team_id``, and every statement
    built on the ``customer_team`` CTE started 500ing on that page alone — while
    CORP, sharing the same code, stayed green. See SPEC-CODE-RULES §81.

    Output is byte-identical to ``repr(tuple_of_str)`` for two or more values,
    so swapping this in cannot move an existing rendering:

    >>> sql_str_list(("TEAM1", "TEAM2", "TEAM3", "TEAM4", "TEAM5"))
    "('TEAM1', 'TEAM2', 'TEAM3', 'TEAM4', 'TEAM5')"
    >>> sql_str_list(("TEAM-DFW",))
    "('TEAM-DFW')"

    For code-owned constants only — quotes are doubled, but a bound ``$n``
    parameter is still the right answer for anything a user can influence.
    """
    vals = list(values)
    if not vals:
        raise ValueError("sql_str_list() needs at least one value: "
                         "`IN ()` is a syntax error, and an empty scope is a bug")
    return "(" + ", ".join("'" + str(v).replace("'", "''") + "'" for v in vals) + ")"


# ---------------------------------------------------------------------------
# Budget mirror → team map (Bruno PDFs 2026-08-27, Ops Portal + Budget Updates)
# ---------------------------------------------------------------------------

# `daily_production_budget_report."Customer Name"` carries a McLeod-id prefix on
# some rows that the v4 customer name does not have. Measured 2026-08-27 against
# live gold, three names match this pattern and two of them have NO exact twin in
# v4, so the INNER JOIN every budget panel used dropped them without erroring:
#
#   KELLQUMX - KELLOGG COMPANY MEXICO            → v4 'KELLOGG COMPANY MEXICO'  (TEAM4)
#   STARCOMX - STARCORR DE MEXICO S DE RL DE CV  → v4 'STARCORR DE MEXICO …'    (TEAM3)
#
# Cost while it was live: −14.07 loads / −$58,940.28 / −$6,899.76 in Aug-2026 and
# −107.97 loads / −$391,540 / −$49,091 across 2026 — which is exactly why Budget
# Follow Up read 1,417.96 against the table's true 1,432.03.
BUDGET_NAME_PREFIX_RE = "^[A-Z0-9]{2,12} - "

_BUDGET_TEAM_CTE = """
budget_team AS (
    SELECT
        n.customer_name,
        COALESCE(t_exact.@COL@, t_stripped.@COL@) AS @COL@,
        -- The v4 name this budget name resolves to, or NULL when neither the
        -- exact nor the stripped lookup hits. Published so a panel that must
        -- pair a budget row with a PRODUCTION row can join on one definition
        -- instead of re-deriving the strip (§69). ⚠ It is still a LOOKUP KEY:
        -- never display it in place of `customer_name`, and never GROUP a
        -- FULL OUTER JOIN on it without aggregating the budget side FIRST —
        -- two budget names can resolve to one v4 name and the join would then
        -- emit the production row once per budget row (§83).
        COALESCE(t_exact.customer_name, t_stripped.customer_name) AS v4_customer_name
    FROM (
        SELECT DISTINCT TRIM("Customer Name") AS customer_name
        FROM public.daily_production_budget_report
        WHERE "Customer Name" IS NOT NULL
    ) n
    LEFT JOIN @SRC@ t_exact
           ON t_exact.customer_name = n.customer_name
    LEFT JOIN @SRC@ t_stripped
           ON t_exact.customer_name IS NULL
          AND t_stripped.customer_name =
              regexp_replace(n.customer_name, '@RE@', '')
)
"""


def budget_team_cte(source_cte: str = "customer_team", team_col: str = "team_id") -> str:
    """One budget-customer → team row per name in the budget mirror.

    Renders a CTE named ``budget_team`` that resolves ``source_cte`` (the
    per-customer canonical team map built from ``mcleod_gld_budget_report_v4``)
    by exact name first, then — only where the exact name did not match — by the
    name with its ``MCLEODID - `` prefix stripped.

    ⚠ The strip is a LOOKUP KEY ONLY. The customer name a panel groups by and
    displays is never rewritten, because two different budget customers can
    strip to the same v4 name (``STARCOMX - STARCORR …`` and the separate
    ``STARCORR …`` row under mcleod_id ``STARTETX`` both do). Rewriting the
    output key instead would merge them and double-count actuals — §83.

    ⚠ Join it with LEFT JOIN, never JOIN. A name that resolves to no team must
    still reach an unfiltered total; only an explicit ``ct.<team_col> = …``
    predicate may exclude it. Measured 2026-08-27: 0 budget rows dated in 2026
    fail to resolve, and ``test_budget_team_map.py`` pins that.

    ``team_col`` follows the upstream map's output column — ``team_id`` for the
    ops-portal / budget-followup / x-ray maps, ``division_team`` for the CEO
    Executive one.
    """
    return (
        _BUDGET_TEAM_CTE
        .replace("@SRC@", source_cte)
        .replace("@COL@", team_col)
        .replace("@RE@", BUDGET_NAME_PREFIX_RE)
    )
