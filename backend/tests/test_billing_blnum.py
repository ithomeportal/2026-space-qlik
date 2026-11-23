"""Pins the BL # column (PDFs "space -- Aging Updates" + "space -- Ops Portal DFW",
2026-11-23): ``blnum`` from ``mcleod_gld_billing_blnum_comments`` on
Admin Aging Cashflow's two unbilled tables (+ CSVs) and the Ops Portal Unbilled
board (shared by all 11 ops portals).

The traps, each measured on live gold 2026-11-23:

* ``order_id`` is blank-PADDED to 8 there ('0352397 ') while
  ``mcleod_gld_cashflow.id`` is UNPADDED — the §150 trap again. Match both
  spellings; a plain ``=`` matches nothing on the cashflow side.
* The table is a change log: 371 of 467 rows are ``db_action='deletion'``
  tombstones. 121 of them belong to orders cashflow still shows unbilled, and
  their BL equals the order BL 97% of the time → owner decision: show the
  LAST-KNOWN billing BL (live upsert row first, else the newest tombstone).
* Only orders in the billing queue (ready to bill) have a row at all — the
  column is BLANK on not-yet-ready rows by design, not broken.
"""

from __future__ import annotations

import asyncio
import types
from datetime import datetime

import pytest

from app import billing_blnum as bb
from app.routers import admin_cashflow as ac
from app.routers.ops_portal_overview import hold as hold_mod


# --------------------------------------------------------------------------
# The shared join
# --------------------------------------------------------------------------

def test_join_matches_both_padded_spellings() -> None:
    sql = bb.billing_blnum_join("c.id", "c.company_id")
    assert "public.mcleod_gld_billing_blnum_comments" in sql
    # both sides rtrimmed: '0352397' (cashflow) meets '0352397 ' (billing)
    assert "ON bbl.order_key = rtrim(c.id) AND bbl.company_key = rtrim(c.company_id)" in sql
    assert "rtrim(b.order_id)   AS order_key" in sql


def test_join_is_uncorrelated_not_a_per_row_lateral() -> None:
    # A LATERAL re-scanned the unindexed change log per outer row: the Unbilled
    # board went 0.7 s -> 3.2 s live (2026-11-23). Pin the dedupe-once shape.
    sql = bb.billing_blnum_join("br4.id", "br4.company_id")
    assert "LATERAL" not in sql.upper()
    assert "br4" not in sql[: sql.index(") bbl ON")]  # outer columns only in ON


def test_join_prefers_live_row_then_newest_tombstone() -> None:
    sql = bb.billing_blnum_join("c.id", "c.company_id")
    # one row per order …
    assert "DISTINCT ON (rtrim(b.company_id), rtrim(b.order_id))" in sql
    # … deletion rows are NOT filtered out (owner decision: last-known BL) …
    assert "db_action = 'deletion'" not in sql
    assert "db_action <> 'deletion'" not in sql
    # … but a live upsert outranks them, then recency, then a stable key
    order = sql[sql.index("ORDER BY"):]
    assert order.index("db_action = 'upsert'") < order.index("last_execution DESC")
    assert order.index("last_execution DESC") < order.index("updated_dt DESC")
    assert "b.id DESC" in order
    # blank BLs and order-less tombstones never win
    assert "NULLIF(btrim(b.blnum), '') IS NOT NULL" in sql
    assert "b.order_id IS NOT NULL" in sql


def test_join_alias_is_configurable() -> None:
    sql = bb.billing_blnum_join("br4.id", "br4.company_id", alias="xbl")
    assert ") xbl ON xbl.order_key = rtrim(br4.id)" in sql


@pytest.mark.parametrize("bad", ["c.id; DROP TABLE x", "c id", "1=1", ""])
def test_join_rejects_non_identifier_input(bad: str) -> None:
    with pytest.raises(ValueError):
        bb.billing_blnum_join(bad, "c.company_id")
    with pytest.raises(ValueError):
        bb.billing_blnum_join("c.id", "c.company_id", alias=bad or "a b")


# --------------------------------------------------------------------------
# Admin Aging Cashflow — both tables + CSVs
# --------------------------------------------------------------------------

class _StubPool:
    def __init__(self, rows=None):
        self.sql: list[str] = []
        self._rows = rows or []

    async def fetch(self, sql, *params):
        self.sql.append(sql)
        return self._rows

    async def fetchrow(self, sql, *params):
        self.sql.append(sql)
        return {"s": 0}


class _Req:
    class app:
        class state:
            savings_pool = None


def _req(pool):
    _Req.app.state.savings_pool = pool
    return _Req


USER = {"sub": "t", "email": "t@local", "roles": ["admin"]}
TS = datetime(2026, 11, 20, 9, 30)  # noqa: DTZ001 — gold timestamps are naive CST

DELIVERED_ROW = {
    "id": "0352397", "ship_date": TS, "dest_actual_arrival": TS,
    "customer_name": "ACME", "carrier_name": "ALLIANCE EXPRESS", "blnum": "378-38826*spot",
    "team_id": "TEAM1 ", "company_id": "TMS ", "total_charge": 1200,
    "days_since_delivery": 3, "total_count": 1, "total_revenue": 1200,
}
READY_ROW = {
    "id": "0351107", "ship_date": TS, "bol_recv_date": TS, "status": "D",
    "customer_name": "BETA", "carrier_name": None, "blnum": None,
    "team_id": "TEAM1 ", "company_id": "TMS ", "total_charge": 800,
    "days_since_bol_recv": 4, "total_count": 1, "total_revenue": 800,
}


def _common(**kw):
    return dict(
        range="mtd", start_date=None, end_date=None, teams=None, companies=None,
        customer=None, customers=None, customer_mode="include", contract_type=None,
        order_q=None, customer_q=None, _user=USER, **kw,
    )


def _assert_cashflow_join(sql: str) -> None:
    assert "mcleod_gld_billing_blnum_comments" in sql
    assert "bbl.order_key = rtrim(c.id)" in sql


@pytest.mark.asyncio
async def test_delivered_table_carries_blnum_and_sorts_on_it() -> None:
    pool = _StubPool([DELIVERED_ROW])
    out = await ac.delivered_not_billed(_req(pool), sort="blnum_asc", page=1, limit=25, **_common())
    _assert_cashflow_join(pool.sql[0])
    assert "ORDER BY blnum ASC NULLS LAST" in pool.sql[0]
    assert out["data"][0]["blnum"] == "378-38826*spot"  # clerk note kept verbatim


@pytest.mark.asyncio
async def test_ready_table_carries_blnum_none_when_absent() -> None:
    pool = _StubPool([READY_ROW])
    out = await ac.ready_not_billed(_req(pool), sort="blnum_desc", page=1, limit=25, **_common())
    _assert_cashflow_join(pool.sql[0])
    assert "ORDER BY blnum DESC NULLS LAST" in pool.sql[0]
    assert out["data"][0]["blnum"] is None  # None, not "", so the UI shows an em-dash


def test_blnum_sorts_are_whitelisted_on_both_tables() -> None:
    for sorts in (ac._DELIVERED_NOT_BILLED_SORTS, ac._READY_NOT_BILLED_SORTS):
        assert sorts["blnum_asc"] == "blnum ASC NULLS LAST"
        assert sorts["blnum_desc"] == "blnum DESC NULLS LAST"


@pytest.mark.asyncio
async def test_delivered_csv_has_bl_column() -> None:
    pool = _StubPool([DELIVERED_ROW])
    resp = await ac.delivered_not_billed_csv(_req(pool), sort="delivered_asc", **_common())
    _assert_cashflow_join(pool.sql[0])
    header, first = resp.body.decode().splitlines()[:2]
    assert header == (
        "Order,BL #,Company,Team,Customer,Carrier Name,Ship Date,Delivered,"
        "Days Since Delivery,Revenue (USD)"
    )
    assert first.startswith("0352397,378-38826*spot,")


@pytest.mark.asyncio
async def test_ready_csv_has_bl_column() -> None:
    pool = _StubPool([READY_ROW])
    resp = await ac.ready_not_billed_csv(_req(pool), sort="ship_asc", **_common())
    _assert_cashflow_join(pool.sql[0])
    header, first = resp.body.decode().splitlines()[:2]
    assert header == (
        "Order,BL #,Company,Team,Customer,Carrier Name,Ship Date,BOL Recv,"
        "Days Since BOL Recv,Revenue (USD)"
    )
    assert first.startswith("0351107,,")  # absent BL = empty cell, never "None"


# --------------------------------------------------------------------------
# Ops Portal Unbilled board (/hold) — all 11 portals
# --------------------------------------------------------------------------

class _HoldPool:
    def __init__(self, rows=None) -> None:
        self.sql: str | None = None
        self._rows = rows or []

    async def fetch(self, sql, *params):
        self.sql = sql
        return self._rows


def _run_hold(rows=None, **kwargs):
    pool = _HoldPool(rows)
    original = hold_mod.get_datalake_gold_pool
    hold_mod.get_datalake_gold_pool = lambda request: pool
    try:
        request = types.SimpleNamespace(
            app=types.SimpleNamespace(state=types.SimpleNamespace())
        )
        params = dict(
            request=request, team=None, customer=None, lanes=None,
            exclude_lanes=None, sort="delay_asc", limit=500, _user={},
        )
        params.update(kwargs)
        resp = asyncio.run(hold_mod.hold_board(**params))
    finally:
        hold_mod.get_datalake_gold_pool = original
    return pool, resp


def test_hold_board_selects_blnum_through_the_shared_join() -> None:
    pool, _ = _run_hold()
    assert "mcleod_gld_billing_blnum_comments" in pool.sql
    assert "bbl.order_key = rtrim(br4.id)" in pool.sql
    assert "bbl.blnum" in pool.sql


def test_hold_board_blnum_sorts() -> None:
    assert hold_mod._HOLD_SORTS["blnum_asc"] == "bbl.blnum ASC NULLS LAST"
    assert hold_mod._HOLD_SORTS["blnum_desc"] == "bbl.blnum DESC NULLS LAST"
    pool, _ = _run_hold(sort="blnum_desc")
    assert "ORDER BY bbl.blnum DESC NULLS LAST" in pool.sql


def _hold_row(**over):
    row = {
        "order_id": "0352397", "team_id": "TM1", "status": "D", "departure": None,
        "delay_days": None, "sched_dest_late": None, "actual_delivery": None,
        "customer_name": "ACME", "carrier": "", "lane": "", "revenue": 1, "carrier_cost": 0,
        "profit": 1, "margin": 100, "on_hold": False, "hold_reason": "", "bill_date": None,
        "billed": False, "days_to_bill": None, "pod_age_hours": None, "blnum": None,
        "n_all": 1, "t_revenue": 1, "t_carrier_cost": 0, "t_profit": 1,
    }
    row.update(over)
    return row


def test_hold_board_emits_blnum_or_none() -> None:
    _, resp = _run_hold(rows=[_hold_row(blnum="233403408*double tonu"), _hold_row(order_id="0352398")])
    assert resp["data"][0]["blnum"] == "233403408*double tonu"
    assert resp["data"][1]["blnum"] is None


# --------------------------------------------------------------------------
# CSV formula injection — BL # is clerk-typed free text
# --------------------------------------------------------------------------

@pytest.mark.parametrize("value", ["=HYPERLINK(\"x\")", "+1+1", "-2+3", "@SUM(A1)", "\t=1", "\r=1"])
def test_csv_cells_that_start_a_formula_are_neutralised(value: str) -> None:
    resp = ac._csv_response("x.csv", ["BL #"], [[value]])
    cell = resp.body.decode().splitlines()[1]
    assert cell.lstrip('"').startswith("'"), cell


def test_csv_leaves_ordinary_cells_and_numbers_alone() -> None:
    resp = ac._csv_response("x.csv", ["a", "b", "c"], [["378-38826*spot", -12.5, ""]])
    assert resp.body.decode().splitlines()[1] == "378-38826*spot,-12.5,"
