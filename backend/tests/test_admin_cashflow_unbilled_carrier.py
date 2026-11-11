"""Pins the Aging Updates round (PDF "space -- Aging Updates", 2026-11-11).

* "Delivered but not billed": Orig Sched Early OUT, Carrier Name IN.
* "Ready to bill but not billed": Orig Sched Early + Status OUT, Carrier Name IN.

The trap this file exists for: the cashflow mirror has no carrier column, so the
carrier is the first movement's ``payee_name``. ``mcleod_gld_cashflow.id`` is
UNPADDED while ``mcleod_gld_movement.order_id`` is blank-padded to 8 — the
obvious ``m.order_id = c.id`` matched 0 of 552 live rows and would have shipped a
column of dashes that looks like "no carrier assigned". Both spellings must be
matched on the movement side, and the indexed column must never be TRIMmed.
"""

from __future__ import annotations

from datetime import datetime

import pytest

from app.routers import admin_cashflow as ac


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
TS = datetime(2026, 11, 2, 9, 30)  # noqa: DTZ001 — gold timestamps are naive CST

DELIVERED_ROW = {
    "id": "0352397", "ship_date": TS, "dest_actual_arrival": TS,
    "customer_name": "ACME  ", "carrier_name": "ALLIANCE EXPRESS TRANSPORTATION LLC",
    "team_id": "TEAM1 ", "company_id": "TMS ", "total_charge": 1200,
    "days_since_delivery": 9, "total_count": 1, "total_revenue": 1200,
}
READY_ROW = {
    "id": "0351107", "ship_date": TS, "bol_recv_date": TS, "status": "D",
    "customer_name": "BETA", "carrier_name": None,
    "team_id": "TEAM1 ", "company_id": "TMS ", "total_charge": 800,
    "days_since_bol_recv": 4, "total_count": 1, "total_revenue": 800,
}


def _common(**kw):
    return dict(
        range="mtd", start_date=None, end_date=None, teams=None, companies=None,
        customer=None, customers=None, customer_mode="include", contract_type=None,
        order_q=None, customer_q=None, _user=USER, **kw,
    )


def _assert_carrier_join(sql: str) -> None:
    assert "mcleod_gld_movement" in sql
    assert "m.order_id IN (c.id, rpad(c.id, 8))" in sql
    assert "m.company_id = c.company_id" in sql
    assert "TRIM(m.order_id)" not in sql  # sargability: never TRIM the indexed side
    assert "ORDER BY m.movement_id ASC" in sql and "LIMIT 1" in sql


def test_both_padded_spellings_are_matched_in_one_shared_lateral() -> None:
    _assert_carrier_join(ac._CARRIER_LATERAL)


@pytest.mark.asyncio
async def test_delivered_table_has_carrier_and_no_orig_sched_early() -> None:
    pool = _StubPool([DELIVERED_ROW])
    out = await ac.delivered_not_billed(_req(pool), sort="carrier_asc", page=1, limit=25, **_common())
    _assert_carrier_join(pool.sql[0])
    assert "orig_orig_sched_early" not in pool.sql[0]
    assert "ORDER BY carrier_name ASC NULLS LAST" in pool.sql[0]
    row = out["data"][0]
    assert row["carrier_name"] == "ALLIANCE EXPRESS TRANSPORTATION LLC"
    assert "orig_sched_early" not in row


@pytest.mark.asyncio
async def test_ready_table_has_carrier_and_no_orig_sched_early() -> None:
    pool = _StubPool([READY_ROW])
    out = await ac.ready_not_billed(_req(pool), sort="carrier_desc", page=1, limit=25, **_common())
    _assert_carrier_join(pool.sql[0])
    assert "orig_orig_sched_early" not in pool.sql[0]
    assert "ORDER BY carrier_name DESC NULLS LAST" in pool.sql[0]
    row = out["data"][0]
    assert row["carrier_name"] is None  # 4/259 live rows have no movement payee
    assert "orig_sched_early" not in row


@pytest.mark.asyncio
async def test_delivered_csv_columns() -> None:
    pool = _StubPool([DELIVERED_ROW])
    resp = await ac.delivered_not_billed_csv(_req(pool), sort="delivered_asc", **_common())
    _assert_carrier_join(pool.sql[0])
    header, first = resp.body.decode().splitlines()[:2]
    assert header == (
        "Order,Company,Team,Customer,Carrier Name,Ship Date,Delivered,"
        "Days Since Delivery,Revenue (USD)"
    )
    assert "ALLIANCE EXPRESS TRANSPORTATION LLC" in first


@pytest.mark.asyncio
async def test_ready_csv_columns_drop_status_and_orig_sched_early() -> None:
    pool = _StubPool([READY_ROW])
    resp = await ac.ready_not_billed_csv(_req(pool), sort="ship_asc", **_common())
    _assert_carrier_join(pool.sql[0])
    header = resp.body.decode().splitlines()[0]
    assert header == (
        "Order,Company,Team,Customer,Carrier Name,Ship Date,BOL Recv,"
        "Days Since BOL Recv,Revenue (USD)"
    )


def test_carrier_sorts_are_whitelisted_on_both_tables() -> None:
    for sorts in (ac._DELIVERED_NOT_BILLED_SORTS, ac._READY_NOT_BILLED_SORTS):
        assert sorts["carrier_asc"] == "carrier_name ASC NULLS LAST"
        assert sorts["carrier_desc"] == "carrier_name DESC NULLS LAST"
