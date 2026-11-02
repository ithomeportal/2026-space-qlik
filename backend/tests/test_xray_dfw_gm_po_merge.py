"""XRAY DFW GM tab — merge orders sharing a PO (Bruno PDF 2026-11-02, GM R1).

`/all-orders?collapse_dup_po=true` keeps ONE row per 8-digit PO group: the
order whose BOL's first 8 characters match the PO's, carrying the group's
summed revenue/profit. See `app/xray_po_merge.py` for the measured decisions.

Layers: statement-text contracts (offline), the clone forwarding (§40), then a
live PREPARE and a live replay of the PDF's own example, skipped unless
`SAVINGS_DATABASE_URL` is set.
"""

from __future__ import annotations

import asyncio
import inspect
import os
import re
import types

import pytest

from app import xray_po_merge as pm
from app.routers import xray_dfw as x
from app.routers import xray_dfw_team as xt
from tests.test_xray_dfw_gm_tab import _strip_comments, _StubPool

GM = "GM C/O CTSI"


class _MergeStub(_StubPool):
    async def fetchrow(self, sql, *params):
        self.sqls.append(sql)
        self.params.append(params)
        return {"total": 0, "revenue": 0, "profit": 0, "unbilled": 0,
                "orders": 0, "merged_pos": 0}


def _drive(pool=None, **overrides):
    pool = pool or _MergeStub()
    orig = x.get_datalake_gold_pool
    x.get_datalake_gold_pool = lambda request: pool
    try:
        request = types.SimpleNamespace(
            app=types.SimpleNamespace(state=types.SimpleNamespace())
        )
        call = dict(
            range="mtd", start_date=None, end_date=None, sub_teams=None,
            customers=GM, lanes=None, contract_type=None, equipment=None,
            view=None, limit=500, page=1, sort="order_desc",
            include_zero_charge=True, collapse_dup_po=True, _user={},
        )
        call.update(overrides)
        resp = asyncio.run(x.all_orders(request=request, **call))
    finally:
        x.get_datalake_gold_pool = orig
    return pool, resp["data"]


def _max_placeholder(sql: str) -> int:
    return max(int(n) for n in re.findall(r"\$(\d+)", sql))


# --------------------------------------------------------------------------
# The default is untouched
# --------------------------------------------------------------------------


def test_flag_off_emits_no_merge_sql():
    """Contract vs Spot and the 4 TM clones read this endpoint with the flag
    off — their statements must not even mention the merge."""
    pool, _ = _drive(collapse_dup_po=False)
    for sql in pool.sqls:
        assert "grp_po" not in sql and "rn = 1" not in sql


def test_team_clones_forward_an_explicit_false():
    """🔴 §40: a direct Python call never applies Query() defaults, so an
    omitted `collapse_dup_po` arrives as a FieldInfo — which is TRUTHY and
    would switch the merge ON for every TM clone's All Orders table."""
    src = inspect.getsource(xt)
    assert "collapse_dup_po=False" in src


# --------------------------------------------------------------------------
# The merge contract
# --------------------------------------------------------------------------


def test_merged_sort_tokens_match_the_whitelist():
    assert set(pm.MERGED_SORT) == set(x._ALL_ORDERS_SORT)


def test_every_merged_sort_ends_with_a_unique_tiebreak():
    """Same rule as the unmerged table: (id, company_id) is unique in v4, so
    LIMIT/OFFSET paging over merged rows is total."""
    for token, frag in pm.MERGED_SORT.items():
        assert frag.endswith("r.company_id DESC"), token
        assert "r.id" in frag, token


def test_money_sorts_order_by_the_COMBINED_value_shown():
    for token in ("revenue_desc", "revenue_asc"):
        assert "r.grp_revenue" in pm.MERGED_SORT[token]
    for token in ("profit_desc", "profit_asc"):
        assert "r.grp_profit" in pm.MERGED_SORT[token]


def test_both_queries_keep_one_row_per_group_in_the_window():
    """Rows and Totals must span ONE population (§16/§96) — both filter the
    kept order (`rn = 1`) by its own departure."""
    pool, _ = _drive()
    assert len(pool.sqls) == 2
    for sql in pool.sqls:
        body = _strip_comments(sql)
        assert "r.rn = 1 AND r.departure >= $" in body
        assert "WITH base AS" in body


def test_only_8_digit_pos_group_and_bol_compares_its_prefix():
    body = _strip_comments(_drive()[0].sqls[0])
    assert "b.po ~ '^[0-9]{8}'" in body
    assert "LEFT(b.bol, 8) = LEFT(b.po, 8)" in body


def test_groups_never_span_two_customers():
    body = _strip_comments(_drive()[0].sqls[0])
    assert "PARTITION BY k.customer, COALESCE(k.grp_po" in body


def test_a_po_spread_wider_than_the_partner_window_is_not_merged():
    """Review 2026-11-02: otherwise YTD would merge a reused PO (Feb + Sep)
    that two monthly views keep apart — the group would depend on the range."""
    body = _strip_comments(_drive()[0].sqls[0])
    assert f"<= INTERVAL '{pm.PARTNER_DAYS} days'" in body


def test_partner_window_is_widened_both_sides():
    body = _strip_comments(_drive()[0].sqls[0])
    assert f"::date - {pm.PARTNER_DAYS})" in body
    assert f"::date + {pm.PARTNER_DAYS + 1})" in body


def test_placeholders_match_params():
    """Each statement's highest $n must equal its own params count."""
    pool, _ = _drive()
    for sql, params in zip(pool.sqls, pool.params):
        assert _max_placeholder(sql) == len(params)


def test_charge_filter_still_applies_to_members():
    pool, _ = _drive(include_zero_charge=False)
    for sql in pool.sqls:
        assert "COALESCE(br4.total_charge, 0) <> 0" in _strip_comments(sql)


def test_totals_publish_orders_and_merged_pos():
    _, data = _drive()
    for key in ("loads", "orders", "merged_pos", "unbilled", "revenue", "profit"):
        assert key in data["totals"]


# --------------------------------------------------------------------------
# Live — PREPARE every variant, then replay the PDF's own example
# --------------------------------------------------------------------------

_GOLD = os.environ.get("SAVINGS_DATABASE_URL", "")


def _url() -> str:
    return re.sub(r"[?&]sslmode=\w+", "", _GOLD)


@pytest.mark.skipif(not _GOLD, reason="SAVINGS_DATABASE_URL not set — offline run")
def test_live_every_merged_variant_parses_against_gold() -> None:
    import asyncpg

    statements = []
    for flag in (False, True):
        for sort in pm.MERGED_SORT:
            pool, _ = _drive(sort=sort, include_zero_charge=flag)
            statements.extend(pool.sqls)

    async def run():
        conn = await asyncpg.connect(_url(), ssl="require")
        bad = []
        try:
            for sql in set(statements):
                try:
                    await conn.prepare(sql)
                except Exception as exc:  # noqa: BLE001 — report, do not mask
                    bad.append(f"{getattr(exc, 'sqlstate', '?')} {exc}"[:220])
        finally:
            await conn.close()
        return bad

    bad = asyncio.run(run())
    assert not bad, "\n".join(bad)


class _LivePool:
    def __init__(self, pool):
        self._pool = pool

    async def fetch(self, sql, *params):
        return await self._pool.fetch(sql, *params)

    async def fetchrow(self, sql, *params):
        return await self._pool.fetchrow(sql, *params)


@pytest.mark.skipif(not _GOLD, reason="SAVINGS_DATABASE_URL not set — offline run")
def test_live_the_pdf_example_collapses_to_order_0350189() -> None:
    """The PDF: 0350189 (BOL 55374191, $3,714 / $2,014) and 0350156 (BOL
    55375236, $0 / −$1,700) share PO `55374191 / 55375236`. Only 0350189 shows,
    carrying both orders' money. Amounts are asserted as the SUM of the members
    (not literals) so a later billing of the return leg does not break this."""
    from datetime import date

    import asyncpg

    async def run():
        pool = await asyncpg.create_pool(
            _url(), ssl="require", min_size=1, max_size=2,
            server_settings={"statement_timeout": "8000"},
        )
        try:
            # asyncio.run inside _drive cannot nest — call the handler directly.
            request = types.SimpleNamespace(
                app=types.SimpleNamespace(state=types.SimpleNamespace())
            )
            orig = x.get_datalake_gold_pool
            x.get_datalake_gold_pool = lambda r: _LivePool(pool)
            try:
                return await x.all_orders(
                    request=request, range="custom", start_date=date(2026, 10, 30),
                    end_date=date(2026, 11, 2), sub_teams=None, customers=GM,
                    lanes=None, contract_type=None, equipment=None, view=None,
                    limit=2000, page=1, sort="order_desc",
                    include_zero_charge=True, collapse_dup_po=True, _user={},
                )
            finally:
                x.get_datalake_gold_pool = orig
        finally:
            await pool.close()

    data = asyncio.run(run())["data"]
    ids = [r["id"].strip() for r in data["rows"]]
    assert "0350189" in ids
    assert "0350156" not in ids, "the partner leg must be merged away"
    row = next(r for r in data["rows"] if r["id"].strip() == "0350189")
    assert row["dup_po_count"] == 2
    members = row["merged_orders"]
    assert {m["id"] for m in members} == {"0350189", "0350156"}
    assert float(row["revenue"]) == pytest.approx(sum(float(m["revenue"] or 0) for m in members))
    assert float(row["profit"]) == pytest.approx(sum(float(m["profit"] or 0) for m in members))
    # Totals = sum of the rows on screen (one page holds them all here).
    assert data["totals"]["loads"] == len(data["rows"])
    assert float(data["totals"]["profit"]) == pytest.approx(
        sum(float(r["profit"]) for r in data["rows"])
    )


# --------------------------------------------------------------------------
# Frontend contracts (no JS runner — read the TS, §107)
# --------------------------------------------------------------------------

_FE = __import__("pathlib").Path(__file__).resolve().parents[2] / "frontend"


def test_only_the_gm_tab_asks_for_the_merge():
    gm = (_FE / "app/reports/xray-dfw-mng/tabs/Gm.tsx").read_text()
    cs = (_FE / "app/reports/xray-dfw-mng/tabs/ContractSpot.tsx").read_text()
    assert re.search(r"^\s*collapseDupPo\s*$", gm, re.MULTILINE)
    assert "collapseDupPo" not in cs


def test_the_query_key_covers_the_merge_flag():
    """A key that misses a query-string input serves another tab's cache."""
    api = (_FE / "lib/xray-dfw-api.ts").read_text()
    assert '"all-orders", f, page, sort, includeZeroCharge, collapseDupPo]' in api
    assert "collapse_dup_po=true" in api


def test_dfw_profit_goal_values():
    """Bruno PDF 2026-11-02 Overview R1: All = $500,000, a TM = $100,000.
    ⚠ The TM clones send no subTeams — Overview must receive `lockedTeam`."""
    goal = (_FE / "lib/xray-dfw-goal.ts").read_text()
    assert "DFW_PROFIT_GOAL_ALL = 500_000" in goal
    assert "DFW_PROFIT_GOAL_PER_TEAM = 100_000" in goal
    assert "if (opts.lockedTeam) return DFW_PROFIT_GOAL_PER_TEAM" in goal
    content = (_FE / "components/XrayDfwReportContent.tsx").read_text()
    assert "lockedTeam={lockedTeam}" in content
    overview = (_FE / "app/reports/xray-dfw-mng/tabs/Overview.tsx").read_text()
    assert "55000" not in overview and "dfwProfitGoal(" in overview
