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
# DFW loads booked under a CORP team (Sergio Hidalgo, 2026-10-28)
# ---------------------------------------------------------------------------

# McLeod MX (company TMS3) books some DFW loads with ``team_id = 'TEAM3'`` but
# carries the DFW sub-team in ``v4.team`` / ``scorecard.team_dfw``. Every CORP
# report scoped on ``team_id`` alone counted them as CORP. Measured 2026-10-28:
# 19 v4 rows in 2026 (18 TMS3 'TM4' UNILINK TRANSPORTATION Monterrey→Tijuana,
# −$1,778 profit, on CORP T3's October; 1 TMS 'TM1' row) and 35 scorecard rows.
# Fixed in McLeod by hand more than once; it keeps coming back.
#
# The DFW sub-team marker is the deciding fact: on every genuine CORP row the
# column is '' (175k rows), and DFW's own rows always carry TM1..TM5. So a row
# is CORP only when it carries NO DFW marker, and a CORP-team row that does
# carry one is a DFW load. ⚠ Not "team <> ''": a future CORP sub-team value
# must not silently move rows to DFW — only the five DFW markers do.
#
# Case variants because McLeod is not case-clean ('tm4' on 2 rows); COALESCE
# so a NULL marker reads as "no marker" — ``NULL NOT IN (...)`` is NULL and
# would DELETE the row rather than keep it (§75).
DFW_SUB_TEAM_TAGS = ("TM1", "TM2", "TM3", "TM4", "TM5")
_DFW_TAG_VARIANTS = tuple(v for t in DFW_SUB_TEAM_TAGS for v in (t, t.lower()))

# REVENUE-CODE rule, 2026-10-29 (Katerine Meneses, McLeod; supersedes the
# marker as the deciding fact for McLeod MX). The MX customer UNILSATX is
# shared by both divisions under ONE salesperson (TEAM3); McLeod tells them
# apart by the order's revenue code: ``DFW`` → a DFW load, anything else → the
# salesperson's team. Diego: a ``DFW`` revenue-code load goes to DFW team TM4.
#
# v4 has no revenue code; ``mcleod_gld_cash_flow_dinfo.revenue_code_id`` has,
# keyed on the SAME padded (company_id, id) as v4 and the scorecard
# (upsert-only — no TRUNCATE lock). Measured 2026-10-29: MX (TMS3) has 60
# DFW-coded orders of ~3,300 coded ones; on every CORP-team MX row ever, code
# DFW ⇔ TM marker. An MX order dinfo has not mirrored yet (or with a blank
# code) falls back to the marker, so a fresh load does not sit in CORP.
#
# ⚠ MX only, and UNCORRELATED. A correlated per-row lookup is
# parallel-restricted in Postgres: it turned the whole scan serial (scorecard
# OTP CTE 0.67 s → 7.5 s, DFW XRay KPI 0.98 s → 11.3 s — and a reader over 10 s
# blocks the scorecard reload's TRUNCATE, which then fails on its
# lock_timeout). Two small hashed id sets keep the plan parallel. US McLeod
# (TMS) keeps the TM-marker rule: its code and marker agree on every CORP-team
# row but 3 old ones (TM marker, code DV: 0258326, 0274806, 0331196 — $2,342),
# which stay DFW as on 10-28.
DFW_REVENUE_CODE = "DFW"
DFW_REVENUE_SUB_TEAM = "TM4"
REVENUE_CODE_TABLE = "mcleod_gld_cash_flow_dinfo"
REVENUE_CODE_COMPANIES = ("TMS3",)


def _row_of(col: str) -> str:
    """The row reference (alias or table name) of a qualified marker column.

    The rule reads the row's ``company_id`` and ``id`` beside its marker; in a
    multi-table FROM an unqualified ``id`` is ambiguous or binds to another
    table, silently — so a bare marker is refused, never guessed.
    """
    row, dot, _ = col.rpartition(".")
    if not dot or not row:
        raise ValueError(f"DFW rule needs a qualified marker column, got {col!r}")
    return row


def _mx_ids(code_test: str) -> str:
    """Uncorrelated: the MX order ids whose revenue code passes ``code_test``."""
    companies = sql_str_list(pad_variants(REVENUE_CODE_COMPANIES, width=4))
    return (
        f"(SELECT rc_d.id FROM {REVENUE_CODE_TABLE} rc_d "
        f"WHERE rc_d.company_id IN {companies} AND {code_test})"
    )


def dfw_tagged(col: str) -> str:
    """The CORP-team row behind ``col`` is a DFW load (revenue-code rule on MX).

    ``col`` is the row's DFW sub-team marker, qualified: ``br4.team`` (v4) or
    ``sc.team_dfw`` (scorecard). An MX row: revenue code ``DFW`` → TRUE, any
    other code → FALSE, no code yet → its marker. Any other row: its TM1..TM5
    marker. Never NULL, so NOT is safe (§75).

    >>> dfw_tagged("br4.team")  # doctest: +NORMALIZE_WHITESPACE
    "(CASE WHEN br4.company_id IN ('TMS3') AND br4.id IN (SELECT rc_d.id FROM
    mcleod_gld_cash_flow_dinfo rc_d WHERE rc_d.company_id IN ('TMS3') AND
    TRIM(rc_d.revenue_code_id) = 'DFW') THEN TRUE WHEN br4.company_id IN ('TMS3')
    AND br4.id IN (SELECT rc_d.id FROM mcleod_gld_cash_flow_dinfo rc_d WHERE
    rc_d.company_id IN ('TMS3') AND NULLIF(TRIM(rc_d.revenue_code_id), '') IS NOT NULL)
    THEN FALSE ELSE COALESCE(br4.team, '') IN ('TM1', 'tm1', 'TM2', 'tm2', 'TM3',
    'tm3', 'TM4', 'tm4', 'TM5', 'tm5') END)"
    """
    row = _row_of(col)
    companies = sql_str_list(pad_variants(REVENUE_CODE_COMPANIES, width=4))
    mx = f"{row}.company_id IN {companies}"
    dfw_ids = _mx_ids(f"TRIM(rc_d.revenue_code_id) = '{DFW_REVENUE_CODE}'")
    coded_ids = _mx_ids("NULLIF(TRIM(rc_d.revenue_code_id), '') IS NOT NULL")
    return (
        f"(CASE WHEN {mx} AND {row}.id IN {dfw_ids} THEN TRUE "
        f"WHEN {mx} AND {row}.id IN {coded_ids} THEN FALSE "
        f"ELSE COALESCE({col}, '') IN {sql_str_list(_DFW_TAG_VARIANTS)} END)"
    )


def not_dfw_tagged(col: str) -> str:
    """The CORP side of ``dfw_tagged`` — AND it onto every CORP ``team_id`` predicate.

    >>> not_dfw_tagged("v4.team").startswith("NOT (CASE WHEN v4.company_id IN ('TMS3') AND v4.id IN (")
    True
    """
    return f"NOT {dfw_tagged(col)}"

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
