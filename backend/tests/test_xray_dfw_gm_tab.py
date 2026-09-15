"""XRAY DFW — the GM tab (Bruno PDF 2026-09-15, "space - XRAY DFW Updates").

Five requests, all landing on `/all-orders`:

* **R1/R2** a "GM" tab rendering the Contract vs Spot "All Orders" table,
  pinned to `customer_name = 'GM C/O CTSI'`
* **R3** without the `total_charge <> 0` filter
* **R4** plus BOL (`blnum`) and PO (`po`) from `mcleod_gld_customer_view`,
  joined on `id` AND `company_id`
* **R5** ordered Order DESC, then PO DESC

The endpoint is SHARED with the Contract vs Spot tab and the four per-team
reports, so most of these tests are about what did NOT move.

Three layers, cheapest first, following `test_ops_portal_dfw_sql_valid.py`:
the emitted-SQL linters, the whitelist/shim unit contracts, and a live PREPARE
that is skipped unless `SAVINGS_DATABASE_URL` is set.
"""

from __future__ import annotations

import asyncio
import inspect
import os
import re
import types

import pytest
from fastapi import HTTPException

from app.routers import xray_dfw as x
from app.routers import xray_dfw_team as xt


class _StubPool:
    """⚠ Records the SQL. A stub pool cannot see a WHERE — these tests assert
    on the statement text, which is why the live PREPARE layer exists too."""

    def __init__(self):
        self.sqls: list[str] = []
        self.params: list[tuple] = []

    async def fetch(self, sql, *params):
        self.sqls.append(sql)
        self.params.append(params)
        return []

    async def fetchrow(self, sql, *params):
        self.sqls.append(sql)
        self.params.append(params)
        return {"total": 0, "revenue": 0, "profit": 0, "unbilled": 0}


def _drive(**overrides):
    """Drive `/all-orders` against a stub pool. Returns (pool, payload)."""
    pool = _StubPool()
    orig = x.get_datalake_gold_pool
    x.get_datalake_gold_pool = lambda request: pool
    try:
        request = types.SimpleNamespace(
            app=types.SimpleNamespace(state=types.SimpleNamespace())
        )
        call = dict(
            range="mtd", start_date=None, end_date=None, sub_teams=None,
            customers=None, lanes=None, contract_type=None, equipment=None,
            view=None, limit=500, page=1, sort="departure_desc",
            include_zero_charge=False, _user={},
        )
        call.update(overrides)
        resp = asyncio.run(x.all_orders(request=request, **call))
    finally:
        x.get_datalake_gold_pool = orig
    return pool, resp["data"]


def _strip_comments(sql: str) -> str:
    """Drop `-- ...` lines.

    ⚠ These statements now carry comments that QUOTE the predicates the tests
    assert about ("The rows `total_charge <> 0` used to hide"), so a raw
    substring check finds the explanation and calls it the code. Scan the
    executable text.
    """
    return "\n".join(
        line for line in sql.split("\n") if not line.strip().startswith("--")
    )


def _rows_sql(pool) -> str:
    return _strip_comments(pool.sqls[0])


def _totals_sql(pool) -> str:
    return _strip_comments(pool.sqls[1])


# --------------------------------------------------------------------------
# R3 — the total_charge filter, and what must NOT move
# --------------------------------------------------------------------------


def test_the_charge_filter_is_still_on_by_default():
    """⚠ The whole point of the default. Contract vs Spot and the four per-team
    reports read this same endpoint; a flipped default would silently add
    unbilled loads to five other tabs and drop their profit by ~70%."""
    pool, _ = _drive()
    for sql in (_rows_sql(pool), _totals_sql(pool)):
        # ⚠ COALESCE-wrapped: a bare `total_charge <> 0` is NULL for a NULL
        # charge and Postgres drops the row, so the two spellings agree on
        # today's data (0 NULL-charge rows in DFW 2026) and diverge the day one
        # appears. The explicit form is the one that says what it means.
        assert "COALESCE(br4.total_charge, 0) <> 0" in sql


def test_include_zero_charge_removes_it_from_BOTH_queries():
    """⚠ BOTH. The rows query and the Totals query carry independent WHERE
    clauses built from independent params lists — dropping the filter from one
    only would make the Totals row describe a different population from the
    rows above it (§16/§96)."""
    pool, _ = _drive(include_zero_charge=True)
    for sql in (_rows_sql(pool), _totals_sql(pool)):
        assert "total_charge <> 0" not in sql


def test_unbilled_is_counted_and_published():
    """The count that keeps the Totals profit legible as a billing lag rather
    than a collapse. Measured live 2026-09-15 for GM MTD: 147 orders, 58 of
    them unbilled, profit $56,462 against $192,837 with the filter on."""
    pool, data = _drive(include_zero_charge=True)
    assert (
        "COUNT(*) FILTER (WHERE COALESCE(br4.total_charge, 0) = 0) AS unbilled"
        in _totals_sql(pool)
    ), "the counter must count every row the filter admits, NULLs included"
    assert "unbilled" in data["totals"]


def test_unbilled_is_zero_when_the_filter_is_on():
    """Not a lie, a tautology: the WHERE removed those rows before the FILTER
    clause could count them. The UI only renders it when it asked for them."""
    _, data = _drive(include_zero_charge=False)
    assert data["totals"]["unbilled"] == 0


# --------------------------------------------------------------------------
# R4 — BOL / PO
# --------------------------------------------------------------------------


def test_customer_view_is_joined_on_BOTH_key_columns():
    """🔴 The fan-out guard.

    `(id, company_id)` is `mcleod_gld_customer_view`'s PRIMARY KEY, so joining
    on both cannot duplicate a v4 row. Joining on `id` ALONE — one column of a
    two-column key — is exactly what inflates money ~2.5% in `hd_spot.py`,
    whose docstring warns about this join in general terms.

    Verified on live gold 2026-09-15: 4,111 GM orders in scope → 4,111 joined
    rows, and the planner reports `Index Scan using
    mcleod_gld_customer_view_pkey ... rows=1`.
    """
    pool, _ = _drive()
    sql = _rows_sql(pool)
    join = re.search(
        r"LEFT JOIN public\.mcleod_gld_customer_view cv\s*\n\s*ON (.+?)\n",
        sql,
        re.S,
    )
    assert join, "the customer_view join is missing or reshaped"
    on = join.group(1)
    assert "cv.id = br4.id" in on
    assert "cv.company_id = br4.company_id" in on, (
        "joining on id alone fans out and inflates the Totals row"
    )


def test_bol_and_po_nullif_the_empty_string():
    """⚠ McLeod writes an EMPTY STRING, not NULL, when a load has no BOL/PO —
    202 blank `blnum` and 1,536 blank `po` across GM's 34,868 orders. Without
    NULLIF the cell renders '' as a silent gap instead of an em-dash, and any
    `IS NULL` check downstream reads 0."""
    pool, _ = _drive()
    sql = _rows_sql(pool)
    assert "NULLIF(TRIM(COALESCE(cv.blnum, '')), '') AS bol" in sql
    assert "NULLIF(TRIM(COALESCE(cv.po, '')), '')    AS po" in sql


def test_the_totals_query_does_not_join_customer_view():
    """It sums money and counts rows; BOL/PO are display-only. An extra join
    there would be 4,111 pointless index probes per request."""
    assert "customer_view" not in _totals_sql(_drive()[0])


# --------------------------------------------------------------------------
# R5 — the default order
# --------------------------------------------------------------------------


def test_default_sort_is_unchanged_for_every_other_tab():
    """Contract vs Spot's caption says "most recent departure first"."""
    pool, _ = _drive()
    assert "ORDER BY br4.origin_actual_departure DESC NULLS LAST" in _rows_sql(pool)


def test_gm_sort_is_order_then_po_descending():
    """Bruno R5. `br4.id` is zero-padded varchar(8) so its lexical DESC is its
    numeric DESC; `br4.id` is NOT unique in v4 (up to 2 rows per id), which is
    what makes the PO leg a real tiebreak rather than decoration."""
    pool, _ = _drive(sort="order_desc")
    assert "ORDER BY br4.id DESC, cv.po DESC NULLS LAST" in _rows_sql(pool)


def test_unknown_sort_is_a_400():
    """⚠ Not a fallback to the default. A token on one side of the wire only
    would otherwise render a table ordered by something else entirely, under a
    heading claiming the order the caller asked for, and nothing would fail."""
    with pytest.raises(HTTPException) as exc:
        _drive(sort="margin_desc")
    assert exc.value.status_code == 400
    assert "sort must be one of" in exc.value.detail


def test_every_sort_token_names_a_real_v4_column():
    """A typo'd column here is a 42703 the moment someone clicks that header."""
    known = {
        "br4.origin_actual_departure", "br4.id", "br4.total_charge",
        "br4.margin_amt", "br4.company_id", "cv.po",
    }
    for token, frag in x._ALL_ORDERS_SORT.items():
        for col in re.findall(r"\b(?:br4|cv)\.\w+", frag):
            assert col in known, f"{token} references unknown column {col}"


def test_only_the_order_sorts_reference_the_joined_table():
    """⚠ `cv.po` is only in scope because the rows query joins customer_view.
    The totals query does not — so a sort fragment naming `cv.` must never
    reach it. It does not today; this pins that it stays that way."""
    assert "cv." not in _totals_sql(_drive(sort="order_desc")[0])


# --------------------------------------------------------------------------
# §40 — the per-team shims must forward both new params
# --------------------------------------------------------------------------


@pytest.mark.parametrize("param", ["sort", "include_zero_charge"])
def test_team_shims_declare_and_forward_the_new_params(param):
    """⚠ A direct Python call never applies `Query()` defaults. An omitted
    param arrives as a raw `FieldInfo`, which is not a key in
    `_ALL_ORDERS_SORT` — turning every per-team All Orders request into a 400
    (§40)."""
    src = inspect.getsource(xt)
    shim = src[src.index('@r.get("/all-orders")') :]
    shim = shim[: shim.index('@r.get("/lane-analysis")')]
    assert f"{param}:" in shim, f"the shim does not DECLARE {param}"
    assert f"{param}={param}" in shim, f"the shim does not FORWARD {param}"


def test_team_shims_do_not_widen_the_population():
    """The four per-team reports must keep `include_zero_charge` defaulting to
    False, or Bruno's GM change silently reaches four other reports."""
    src = inspect.getsource(xt)
    assert "include_zero_charge: bool = Query(False)" in src


# --------------------------------------------------------------------------
# Sargability — the index this endpoint was rewritten to keep (§43)
# --------------------------------------------------------------------------


def test_the_date_bounds_stay_sargable():
    """⚠ A `::date` cast on `origin_actual_departure` defeats `idx_v4_dep` and
    turns this into a full seq scan — the original cause of the 500s Bruno
    reported on 2026-06-03. Verified 2026-09-15: the plan still reads
    `Index Scan using idx_v4_dep`."""
    sql = _rows_sql(_drive()[0])
    assert re.search(r"br4\.origin_actual_departure >= \$\d+", sql)
    assert not re.search(r"br4\.origin_actual_departure\s*::\s*date", sql)


# --------------------------------------------------------------------------
# Live PREPARE — parse + plan against real gold, no execution
# --------------------------------------------------------------------------


_GOLD = os.environ.get("SAVINGS_DATABASE_URL", "")


@pytest.mark.skipif(not _GOLD, reason="SAVINGS_DATABASE_URL not set — offline run")
def test_live_every_all_orders_variant_parses_against_gold() -> None:
    """Every (sort x include_zero_charge) combination the UI can produce.

    A text assertion is satisfied by a string Postgres will reject — this is
    the layer that proves the statement PARSES, including the new join and the
    conditionally-empty `{charge_filter}` slot.
    """
    import asyncpg

    url = re.sub(r"[?&]sslmode=\w+", "", _GOLD)

    statements = []
    for flag in (False, True):
        for sort in x._ALL_ORDERS_SORT:
            pool, _ = _drive(sort=sort, include_zero_charge=flag)
            for i, sql in enumerate(pool.sqls):
                statements.append((f"sort={sort} zero={flag} q{i}", sql))

    async def run():
        conn = await asyncpg.connect(url, ssl="require")
        await conn.execute("SET statement_timeout = '30s'")
        bad, seen = [], set()
        try:
            for label, sql in statements:
                if sql in seen:
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
    assert n >= 4, f"only {n} distinct statements — the harness went vacuous"
    assert not bad, "statements rejected by Postgres:\n" + "\n".join(bad)


# --------------------------------------------------------------------------
# Determinism under pagination, and the cross-wire contract
# --------------------------------------------------------------------------


def test_every_sort_fragment_ends_with_a_UNIQUE_tiebreak():
    """🔴 Without a total order, LIMIT/OFFSET pagination is not stable.

    Postgres promises nothing about the relative order of tying rows, so an
    unbroken tie at a page boundary can show one row on two pages and drop
    another — silently, and differently per request. GM is 4,111 orders over 9
    pages.

    `(id, company_id)` is unique on v4 (measured 2026-09-15: 281,951 rows =
    281,951 distinct pairs, over only 247,882 distinct ids), so ending every
    fragment with `br4.company_id DESC` leaves no tie anywhere.
    """
    for token, frag in x._ALL_ORDERS_SORT.items():
        assert frag.rstrip().endswith("br4.company_id DESC"), (
            f"{token} has no unique final tiebreak — pagination is unstable"
        )
        assert "br4.id" in frag, f"{token} omits the id leg of the unique key"


def test_company_id_is_on_the_wire_for_the_row_key():
    """⚠ `id` alone is not unique, and React mis-reconciles duplicate keys.
    The client keys rows on `id`+`company_id`, so the column must ship."""
    assert "TRIM(br4.company_id) AS company_id" in _rows_sql(_drive()[0])


_API_TS = (
    __import__("pathlib").Path(__file__).resolve().parents[2]
    / "frontend/lib/xray-dfw-api.ts"
)


def test_all_orders_sort_whitelist_matches_frontend():
    """The two lists are one contract — an unknown token is a 400, not a
    fallback. There is no JS test runner here, so the guard reads the TS
    (§107), exactly as the Booker table's twin guard does."""
    src = _API_TS.read_text()
    block = re.search(
        r"export type XrayDfwAllOrdersSort =(.*?)\n\n", src, re.S
    )
    assert block, "could not find XrayDfwAllOrdersSort in xray-dfw-api.ts"
    used = set(re.findall(r'"([a-z_]+(?:_asc|_desc))"', block.group(1)))
    assert used, "parsed no sort tokens — the guard would pass vacuously"
    assert used == set(x._ALL_ORDERS_SORT), (
        f"frontend-only: {sorted(used - set(x._ALL_ORDERS_SORT))} | "
        f"backend-only: {sorted(set(x._ALL_ORDERS_SORT) - used)}"
    )


@pytest.mark.skipif(not _GOLD, reason="SAVINGS_DATABASE_URL not set — offline run")
def test_live_the_gm_customer_name_still_resolves_to_rows() -> None:
    """⚠ `GM C/O CTSI` is an exact, case-sensitive match (`_scope_where` uses
    `TRIM(customer_name) = ANY($n)`). If McLeod renames or re-cases the
    account, the tab renders an EMPTY table with no error — which the Gm.tsx
    docstring itself says would read as "GM stopped shipping". Nothing else
    would catch that: the PREPARE layer only parses.
    """
    import asyncpg

    url = re.sub(r"[?&]sslmode=\w+", "", _GOLD)

    async def run():
        conn = await asyncpg.connect(url, ssl="require")
        try:
            return await conn.fetchval(
                """
                SELECT count(*) FROM public.mcleod_gld_budget_report_v4
                WHERE TRIM(customer_name) = $1
                  AND team_id = ANY($2::text[])
                """,
                "GM C/O CTSI",
                ["TEAM-DFW", "TEAM-DFW"],
            )
        finally:
            await conn.close()

    n = asyncio.run(run())
    assert n > 0, (
        "'GM C/O CTSI' matches no v4 rows — the GM tab is rendering empty. "
        "Check whether McLeod renamed the account."
    )
