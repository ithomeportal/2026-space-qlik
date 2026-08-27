"""Every statement the Ops Portal emits must be VALID SQL — under both scopes.

Bruno PDF "BRUNO -- Ops Portal DFW" (2026-08-24): Team Monthly Performance and
the HOLD board both rendered "Failed to load" on
``/reports/ops-managers-portal-dfw``. Four endpoints were returning 500 with
``SQLSTATE 42601`` — a *syntax* error — from two independent defects, and both
were invisible on the five CORP portals running the very same lines:

  * ``hold.py`` wrapped ``_team_id_select()`` in ``TRIM()``. That helper appends
    ``AS team_id`` under any non-CORP scope, so DFW rendered
    ``TRIM(br4.team AS team_id)``. Under CORP it returns a bare column, so
    ``TRIM(br4.team_id)`` was fine. Broke ``/hold`` on ALL 14 sort keys.

  * ``customer_team_cte`` built its IN-list with ``{tuple!r}``. CORP's five ids
    repr as valid SQL by coincidence; the DFW division is ONE ``team_id`` and
    reprs as ``('TEAM-DFW',)`` — a trailing comma. Broke ``/team-performance``,
    ``/team-weekly-performance`` and ``/team-performance-by-team``.

⚠ Why 433 tests did not catch this
----------------------------------
``test_ops_portal_scope.py`` already drives every DFW endpoint and asserts on
the SQL it emits — which team id, which column, which table. It never asked
whether the statement *parses*. A text assertion is satisfied by a string that
Postgres will reject, so scope coverage read as correctness coverage.

Three layers, cheapest first:

  1. ``test_no_statement_*`` — an offline shape linter over every statement both
     scopes can emit. It targets the CLASS (a Python container repr in SQL; an
     alias inside a function call), not the two lines, so the next variant is
     caught too.
  2. ``test_sql_str_list_*`` / ``test_team_id_*`` — the unit contracts, incl.
     the byte-identity that proves CORP could not have moved.
  3. ``test_live_*`` — PREPAREs every emitted statement against real gold.
     Skipped unless ``SAVINGS_DATABASE_URL`` is set, so the suite stays offline.
"""

from __future__ import annotations

import asyncio
import importlib
import inspect
import os
import re
import types
from datetime import date

import pytest

from app.datalake import sql_str_list
from app.routers import ops_portal_overview as opo
from app.routers import ops_portal_overview_dfw as dfw
from app.routers.ops_portal_overview import _constants, _sql
from app.routers.ops_portal_overview import hold as hold_mod
from app.routers.ops_portal_overview._scope import CORP_SCOPE, DFW_SCOPE

_ENDPOINT_MODULES = (
    "meta", "chart", "variance", "performance",
    "projection", "actuals", "orders", "hold", "incidents",
)


# ---------------------------------------------------------------------------
# Harness — drive every endpoint over a parameter matrix and keep the SQL
# ---------------------------------------------------------------------------


class _StubPool:
    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple]] = []

    async def fetch(self, sql, *params):
        self.calls.append((sql, params))
        return []

    async def fetchrow(self, sql, *params):
        self.calls.append((sql, params))
        return None

    async def fetchval(self, sql, *params):
        self.calls.append((sql, params))
        return None


def _patch_pools(pool):
    """Point every pool accessor at the stub — gold AND the portal hub.

    ⚠ `get_pool` (analytics_hub) must be patched too. /team-projection-history
    resolves it FIRST, before emitting a single statement, and the real one
    raises HTTPException(503) on a stub request — so leaving it alone does not
    fail the test, it silently contributes ZERO statements to the corpus and
    the endpoint reads as covered when it is not.
    """
    originals = []
    mods = [importlib.import_module(f"app.routers.ops_portal_overview.{n}")
            for n in _ENDPOINT_MODULES] + [dfw]
    for m in mods:
        for attr, repl in (
            ("get_datalake_gold_pool", lambda request, _p=pool: _p),
            ("get_pool", lambda request, _p=pool: _p),
        ):
            if hasattr(m, attr):
                originals.append((m, attr, getattr(m, attr)))
                setattr(m, attr, repl)
    return lambda: [setattr(mod, attr, fn) for mod, attr, fn in originals]


def _axis(name: str, scope):
    """Values worth varying per parameter — each opens a different SQL branch."""
    sub = scope.sub_teams[0]
    return {
        "team": [sub],
        "customer": ["SOME CUSTOMER"],
        "lanes": [["A - B"]],
        "exclude_lanes": [["A - B"]],
        "carriers": [["CARRIER X"]],
        "exclude_carriers": [["CARRIER X"]],
        # every sort key: the DFW Hold board failed on all 14, so testing only
        # the default would have called the endpoint fixed at 1/14.
        "sort": list(hold_mod._HOLD_SORTS),
        "grain": ["week", "day"],
        "range": ["ytd", "custom"],
        "load_type": ["Contract", "Spot"],
        "mode": ["budget", "variance"],
        "metric": ["profit"],
    }.get(name, [])


def _statements(router, scope) -> list[tuple[str, str, tuple]]:
    """(label, sql, params) for every statement `router` can emit under `scope`."""
    pool = _StubPool()
    undo = _patch_pools(pool)
    out: list[tuple[str, str, tuple]] = []
    try:
        for route in router.routes:
            fn, sig = route.endpoint, inspect.signature(route.endpoint)
            base, varying = {}, {}
            for name, p in sig.parameters.items():
                if name in ("request", "_user", "user"):
                    continue
                d = p.default
                v = getattr(d, "default", d)
                if v is Ellipsis or repr(v).startswith("PydanticUndefined"):
                    v = None
                base[name] = v
                alt = [a for a in _axis(name, scope) if a != v]
                if alt:
                    varying[name] = alt
            combos = [{}] + [{k: v} for k, vals in varying.items() for v in vals]
            if varying:
                combos.append({k: vals[-1] for k, vals in varying.items()})
            for combo in combos:
                kwargs = dict(base)
                kwargs.update(combo)
                state = types.SimpleNamespace()
                if scope is not CORP_SCOPE:
                    state.opp_scope = scope
                kwargs["request"] = types.SimpleNamespace(
                    state=state,
                    app=types.SimpleNamespace(state=types.SimpleNamespace(ap_pool=None)),
                    query_params={},
                )
                for u in ("_user", "user"):
                    if u in sig.parameters:
                        kwargs[u] = {}
                seen = len(pool.calls)
                try:
                    asyncio.run(fn(**kwargs))
                except Exception:
                    # The stub returns None/[]; several endpoints subscript that
                    # after emitting their SQL. The statement is what we came for.
                    pass
                label = f"{route.path} {combo or 'defaults'}"
                out.extend((label, sql, params) for sql, params in pool.calls[seen:])
    finally:
        undo()
    return out


# ---------------------------------------------------------------------------
# The projection-history service statements
# ---------------------------------------------------------------------------
# These never pass through a route, so the endpoint harness above cannot see
# them — and they are the ones a replay bug hides in. Built here explicitly so
# they join both the offline linters (via ALL) and the live PREPARE below.


def _projection_history_statements() -> list[tuple[str, str, tuple]]:
    from app.services import projection_history as ph

    out: list[tuple[str, str, tuple]] = []
    for scope_key, team_key, scope, team_ids in ph.SNAPSHOT_SCOPES:
        params: list = []
        where = _sql._v4_scope_where(
            "br4", list(team_ids) or None, None, None, params,
            None, None, None, None, scope=scope,
        )
        n = len(params)
        label = f"projection_history[{scope_key}/{team_key}]"
        # Bound values are what asyncpg would send; PREPARE only needs the text
        # and the parameter COUNT to line up.
        dates = (date(2026, 1, 1), date(2026, 8, 24), date(2025, 11, 22))
        out.append((f"{label} replay",
                    ph._replay_sums_sql(where, n + 1, n + 2, n + 3),
                    tuple(params) + dates))
        out.append((f"{label} team_count",
                    ph._team_count_sql(where, scope), tuple(params)))
        out.append((f"{label} weekly",
                    ph._weekly_sql(where, n + 1, n + 2), tuple(params) + dates[:2]))
        out.append((f"{label} actuals",
                    ph._ACTUALS_SQL.format(where=where, p_start=n + 1, p_end=n + 2),
                    tuple(params) + dates[:2]))
    return out


def _all_statements() -> list[tuple[str, str, tuple]]:
    return (
        _statements(dfw.r, DFW_SCOPE)
        + _statements(opo.router, CORP_SCOPE)
        + _projection_history_statements()
    )


ALL = _all_statements()


def test_the_harness_actually_drives_both_portals() -> None:
    """A linter over an empty corpus passes vacuously — pin the corpus size."""
    assert len(ALL) > 400, f"only {len(ALL)} statements captured"
    labels = {lbl.split()[0] for lbl, _, _ in ALL}
    for path in ("/custom/ops-portal-overview-dfw/hold",
                 "/custom/ops-portal-overview-dfw/team-performance",
                 "/custom/ops-portal-overview-dfw/team-weekly-performance",
                 "/custom/ops-portal-overview-dfw/team-performance-by-team"):
        assert path in labels, f"{path} emitted no SQL — the four that broke must be covered"
    # The projection-history statements bypass the router entirely, so their
    # presence has to be asserted by name or a refactor could drop them
    # silently from the corpus.
    assert any(lbl.startswith("projection_history[corp/ALL]") for lbl, _, _ in ALL)
    assert any(lbl.startswith("projection_history[dfw/TM1]") for lbl, _, _ in ALL)


# ---------------------------------------------------------------------------
# Layer 1 — the shape linter
# ---------------------------------------------------------------------------

_LINE_COMMENT = re.compile(r"--[^\n]*")
_STRING = re.compile(r"'(?:[^']|'')*'")


def _strip(sql: str) -> str:
    """Drop comments and string literals so the scanners see SQL structure only."""
    return _STRING.sub("''", _LINE_COMMENT.sub("", sql))


_PY_REPR = (
    (re.compile(r",\s*\)"), "trailing comma before ')' — a Python 1-tuple repr"),
    (re.compile(r"\[|\]"), "'[' or ']' — a Python list repr reached the SQL"),
    (re.compile(r"FieldInfo|PydanticUndefined|<function|object at 0x"), "a Python object repr"),
    (re.compile(r"\bNone\b|\bTrue\b|\bFalse\b"), "a Python literal (use NULL / TRUE / FALSE)"),
)


def test_no_statement_carries_a_python_repr() -> None:
    """``f"IN {tuple!r}"`` only looks like a SQL list.

    ⚠ It is valid for 2+ values and invalid for exactly 1, so it ships green and
    breaks the first time a scope narrows to a single value — which is exactly
    how the DFW division took out three panels.
    """
    offenders = []
    for label, sql, _ in ALL:
        body = _strip(sql)
        for pattern, why in _PY_REPR:
            if pattern.search(body):
                offenders.append(f"{label}: {why}")
    assert not offenders, "\n".join(sorted(set(offenders))[:20])


# Words that legally precede "(" without being a function: CTE and derived-table
# introducers, set operators, predicates. `AS (`, `FROM (` and `JOIN LATERAL (`
# are the ones that actually appear here.
_NOT_A_FUNCTION = frozenset("""
    AS FROM IN ON AND OR NOT WHERE SELECT VALUES UNION EXCEPT INTERSECT ALL ANY
    SOME EXISTS OVER FILTER LATERAL BY WHEN THEN ELSE CASE END RETURNING USING
    DISTINCT WITH GROUP ORDER PARTITION HAVING LIMIT OFFSET INTO SET IS LIKE
    BETWEEN ROW INNER OUTER CROSS FULL NATURAL AT CAST TRY_CAST
""".split())


def _aliases_inside_a_call(sql: str) -> list[str]:
    """Function calls whose own argument list contains a bare ``AS`` alias.

    Three things are legal and must not be flagged:

      * ``CAST(x AS type)`` — the one form where ``AS`` belongs in a call;
      * a keyword before the paren — ``AS (``, ``FROM (``, ``JOIN LATERAL (``
        open a CTE or a derived table, not a call;
      * a subquery argument, where ``SELECT a AS b`` is ordinary.

    What is left is the defect: an expression-position helper that emitted an
    alias, e.g. ``TRIM(br4.team AS team_id)``.
    """
    body = _strip(sql)
    bad: list[str] = []
    for m in re.finditer(r"\b([A-Za-z_][A-Za-z0-9_]*)\s*\(", body):
        if m.group(1).upper() in _NOT_A_FUNCTION:
            continue
        depth, i, n = 0, m.end() - 1, len(body)
        while i < n:
            if body[i] == "(":
                depth += 1
            elif body[i] == ")":
                depth -= 1
                if depth == 0:
                    break
            i += 1
        inner = body[m.end():i]
        if re.search(r"\bSELECT\b", inner, re.I):
            continue          # a subquery argument, not an expression list
        top = inner
        while True:
            nxt = re.sub(r"\([^()]*\)", " ", top)
            if nxt == top:
                break
            top = nxt
        if re.search(r"\bAS\b", top, re.I):
            bad.append(f"{m.group(1)}({inner[:80]}…)")
    return bad


def test_no_statement_wraps_an_alias_in_a_function_call() -> None:
    """``TRIM(br4.team AS team_id)`` is 42601, and only DFW rendered it.

    A helper that returns a SELECT ITEM cannot be treated as an expression.
    """
    offenders = []
    for label, sql, _ in ALL:
        for hit in _aliases_inside_a_call(sql):
            offenders.append(f"{label.split()[0]}: {hit}")
    assert not offenders, "\n".join(sorted(set(offenders))[:20])


def test_the_linters_can_see_the_two_defects_they_exist_for() -> None:
    """Mutation check — a linter that cannot fail is decoration."""
    assert _aliases_inside_a_call("SELECT TRIM(br4.team AS team_id) AS team_id")
    assert not _aliases_inside_a_call("SELECT TRIM(br4.team) AS team_id")
    # CAST is the legal exemption and must not be flagged.
    assert not _aliases_inside_a_call("SELECT CAST(br4.x AS text) AS y")
    # ...nor a subquery, whose '(' follows no identifier.
    assert not _aliases_inside_a_call("SELECT * FROM (SELECT a AS b FROM t) q")

    trailing = re.compile(r",\s*\)")
    assert trailing.search("WHERE TRIM(team_id) IN ('TEAM-DFW',)")
    assert not trailing.search("WHERE TRIM(team_id) IN ('TEAM1', 'TEAM2')")


# ---------------------------------------------------------------------------
# Layer 2 — the unit contracts
# ---------------------------------------------------------------------------


def test_sql_str_list_is_byte_identical_to_repr_for_corp() -> None:
    """The proof that swapping the renderer could not have moved CORP.

    Five live portals share `customer_team_cte`; a textual drift there is
    silent — the numbers change and nothing errors.
    """
    assert sql_str_list(_constants.CORP_TEAMS) == repr(_constants.CORP_TEAMS)


def test_sql_str_list_renders_a_single_value_without_a_trailing_comma() -> None:
    assert sql_str_list(("TEAM-DFW",)) == "('TEAM-DFW')"
    assert repr(("TEAM-DFW",)) == "('TEAM-DFW',)", "the repr that broke it"
    assert sql_str_list(["A", "B"]) == "('A', 'B')"
    assert sql_str_list(["O'Hare"]) == "('O''Hare')", "quotes must be doubled"
    with pytest.raises(ValueError):
        sql_str_list([])  # `IN ()` is a syntax error; an empty scope is a bug


def test_the_customer_team_cte_renders_a_valid_in_list_under_both_scopes() -> None:
    corp = _constants.customer_team_cte(CORP_SCOPE)
    dfw_cte = _constants.customer_team_cte(DFW_SCOPE)
    assert "IN ('TEAM1', 'TEAM2', 'TEAM3', 'TEAM4', 'TEAM5')" in corp
    assert "IN ('TEAM-DFW')" in dfw_cte
    assert "'TEAM-DFW',)" not in dfw_cte
    # The back-compat constant must not drift from the CORP rendering.
    assert _constants.CUSTOMER_TEAM_CTE == corp


def test_team_id_col_is_a_bare_column_under_every_scope() -> None:
    """Safe to wrap — that is the whole distinction from `_team_id_select`."""
    assert _sql._team_id_col("br4", CORP_SCOPE) == "br4.team_id"
    assert _sql._team_id_col("br4", DFW_SCOPE) == "br4.team"
    for scope in (CORP_SCOPE, DFW_SCOPE):
        assert " AS " not in _sql._team_id_col("br4", scope)
    assert inspect.signature(_sql._team_id_col).parameters["scope"].default is CORP_SCOPE


def test_team_id_select_is_never_wrapped_in_a_call_anywhere_in_the_package() -> None:
    """Source scan — the mistake is one character of nesting away.

    ⚠ Reads the source rather than the output because a call site that is not
    exercised by a test would still ship broken.
    """
    import ast
    import pathlib

    pkg = pathlib.Path(_sql.__file__).parent
    offenders = []
    for path in sorted(pkg.glob("*.py")):
        src = path.read_text()
        # Docstrings quote the defect deliberately — exclude their line spans.
        tree = ast.parse(src)
        doc_lines: set[int] = set()
        for node in ast.walk(tree):
            if not isinstance(node, (ast.Module, ast.ClassDef,
                                     ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            body = node.body
            if not body or not isinstance(body[0], ast.Expr):
                continue
            first = body[0].value
            if isinstance(first, ast.Constant) and isinstance(first.value, str):
                doc_lines.update(range(body[0].lineno, (body[0].end_lineno or body[0].lineno) + 1))
        for n, line in enumerate(src.splitlines(), 1):
            if n in doc_lines or line.lstrip().startswith(("#", "--")):
                continue
            if re.search(r"[A-Za-z_]\w*\(\s*\{?_team_id_select\(", line):
                offenders.append(f"{path.name}:{n}: {line.strip()}")
    assert not offenders, (
        "_team_id_select() emits `AS team_id` under DFW and cannot be wrapped; "
        f"use _team_id_col() — {offenders}"
    )


def test_the_hold_board_trims_the_bare_team_column() -> None:
    """The regression itself, on the statement the browser actually causes."""
    for scope, expected in ((CORP_SCOPE, "TRIM(br4.team_id) AS team_id"),
                            (DFW_SCOPE, "TRIM(br4.team) AS team_id")):
        pool = _StubPool()
        undo = _patch_pools(pool)
        state = types.SimpleNamespace()
        if scope is not CORP_SCOPE:
            state.opp_scope = scope
        try:
            asyncio.run(hold_mod.hold_board(
                request=types.SimpleNamespace(
                    state=state,
                    app=types.SimpleNamespace(state=types.SimpleNamespace(ap_pool=None)),
                    query_params={}),
                team=None, customer=None, lanes=None, exclude_lanes=None,
                sort="date_asc", limit=500, _user={},
            ))
        finally:
            undo()
        sql = pool.calls[0][0]
        assert expected in sql
        assert "TRIM(br4.team AS team_id)" not in sql


# ---------------------------------------------------------------------------
# Layer 3 — replay against real gold (opt-in; the suite stays offline)
# ---------------------------------------------------------------------------

_GOLD = os.environ.get("SAVINGS_DATABASE_URL")


@pytest.mark.skipif(not _GOLD, reason="SAVINGS_DATABASE_URL not set — offline run")
def test_live_every_emitted_statement_parses_against_gold() -> None:
    """PREPARE (parse + plan, no execution, no writes) every statement.

    This is the harness that found both defects. It also catches what the
    offline linter cannot: a renamed column, a type mismatch, a dropped table.
    """
    import asyncpg

    url = re.sub(r"[?&]sslmode=\w+", "", _GOLD)

    # ⚠ Portal-OWNED tables live in analytics_hub, not gold, so PREPARE against
    # gold reports 42P01 for them — a false failure, not a defect. Skipping them
    # keeps this alarm meaningful: it went red on 2026-08-25 when
    # /team-projection-history shipped, and a permanently-red guard is a guard
    # nobody reads. Their SQL is covered by tests/test_projection_history.py.
    PORTAL_OWNED = ("ops_projection_history", "ops_weekly_actuals")

    async def run():
        conn = await asyncpg.connect(url, ssl="require")
        await conn.execute("SET statement_timeout = '30s'")
        bad = []
        seen = set()
        try:
            for label, sql, params in ALL:
                if sql in seen or any(t in sql for t in PORTAL_OWNED):
                    continue
                seen.add(sql)
                try:
                    await conn.prepare(sql)
                except Exception as exc:  # noqa: BLE001 — report, do not mask
                    bad.append(f"{label}: {getattr(exc, 'sqlstate', '?')} {exc}"[:220])
        finally:
            await conn.close()
        return bad, len(seen)

    bad, n = asyncio.run(run())
    assert n > 200, f"only {n} unique statements replayed"
    assert not bad, "\n".join(bad)
