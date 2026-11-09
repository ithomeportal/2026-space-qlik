"""Funnel Augie Activities — "Loads — Missing information".

Requested 2026-10-29 (Katerine Meneses for Christian Mendoza, "Augie funnel
report addition.pdf" p3-4): which loads, per pickup day, did NOT have their
information complete, and WHICH fields were missing on each.

The five McLeod fields are exactly the carrier/driver block of the Augie app's
own "Status Update" popup (``logs_null``, written by
``validate-payload-required-fields-augie.tsx`` → ``messagesFields``):

  Carrier Id missed               ``override_payee_id``
  Carrier Name missed             ``carrier_name``
  Carrier Dispatcher Email missed ``carrier_dispatcher_email``
  Driver Name missed              ``override_driver_nm``
  Driver Phone missed             ``override_drvr_cell``

⚠ They are computed from the mirror COLUMNS, never by parsing ``logs_null``:
that text is a snapshot of the last n8n upsert and older rows still carry
labels from earlier code versions ("No payee id found", "Carrier MC missed"…).
Missing = NULL or blank after trim — the app's ``validateEmptyFields`` rule.

Trailer is NOT in McLeod. Only Augment reports it (``carrier-update`` →
``loadCarrierUpdate.trailerNumber``), so it is checked ONLY on loads sent to
Augie; on the rest it is ``n/a`` (decided by the user 2026-11-09 — "missing"
on every unsent load would be noise).

Population = the funnel's ONE classified set (``_funnel_cte``: same filters,
same pickup unit, attributes from the order's latest movement — the Augie
app's DISTINCT ON), minus canceled loads (a voided load never gets a carrier).
Missing fields are independent of the reason a load was not sent to Augie.
"""

from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request

from app.routers.augie_funnel import (
    MAX_ROWS,
    REPORT_KEY,
    _common,
    _funnel_cte,
)
from app.routers.deps import get_datalake_gold_pool, require_report_access

logger = logging.getLogger(__name__)

router = APIRouter(tags=["augie-funnel"], prefix=f"/custom/{REPORT_KEY}")

# key → SQL "is missing" over the `classified` row. Order = display order.
# Every expression is a constant: the `field` param only ever SELECTS a key.
MISSING_FIELDS: dict[str, str] = {
    "carrier_id": "COALESCE(carrier_id, '') = ''",
    "carrier_name": "COALESCE(carrier_name, '') = ''",
    "dispatcher_email": "COALESCE(dispatcher_email, '') = ''",
    "driver_name": "COALESCE(driver_name, '') = ''",
    "driver_phone": "COALESCE(driver_phone, '') = ''",
    # Only judged on loads sent to Augie (see the module docstring).
    "trailer": "(tracked AND NOT has_trailer)",
}
TRAILER_ONLY_WHEN = "tracked"

# Canceled loads never get a carrier — they would list every field as missing.
_POPULATION = "COALESCE(reason, '') <> 'canceled'"


def _any_missing() -> str:
    return "(" + " OR ".join(MISSING_FIELDS.values()) + ")"


def missing_where(field: Optional[str]) -> str:
    """WHERE over `classified` for the table: one field, or any field."""
    if field in (None, "", "all"):
        return _any_missing()
    if field not in MISSING_FIELDS:
        raise HTTPException(400, f"unknown field {field!r}")
    return MISSING_FIELDS[field]


def field_status(row, key: str) -> str:
    """'missing' | 'available' | 'n/a' for one field of one load row."""
    if key == "trailer" and not row[TRAILER_ONLY_WHEN]:
        return "n/a"
    return "missing" if row[f"m_{key}"] else "available"


@router.get("/missing-info")
async def missing_info(
    request: Request,
    field: Optional[str] = Query(None),
    f: dict = Depends(_common),
    _user: dict = Depends(require_report_access(REPORT_KEY)),
):
    """Loads with one or more missing fields, newest pickup first.

    `meta.counts` = loads missing each field over the WHOLE filtered universe
    (never the capped page); `meta.checked` = loads examined; `meta.total` =
    rows matching `field` (capped at MAX_ROWS in `data`).
    """
    where = missing_where(field)
    cte, params = _funnel_cte(f)
    flags = ",\n".join(f"({expr}) AS m_{k}" for k, expr in MISSING_FIELDS.items())
    counts = ",\n".join(
        f"count(*) FILTER (WHERE m_{k}) AS n_{k}" for k in MISSING_FIELDS
    )
    sql = (
        cte
        + f"""
        , checked AS MATERIALIZED (
            SELECT c.*, {flags}
              FROM classified c
             WHERE {_POPULATION}
        ),
        agg AS (
            SELECT count(*) AS checked_n,
                   count(*) FILTER (WHERE {" OR ".join(f"m_{k}" for k in MISSING_FIELDS)})
                       AS any_n,
                   {counts}
              FROM checked
        ),
        picked AS (
            SELECT k.*, count(*) OVER () AS total
              FROM checked k
             WHERE {where}
        )
        SELECT p.order_id, p.unit, p.team, p.customer_name, p.carrier_name,
               p.pickup_day, p.tracked, p.reason, p.total,
               {", ".join(f"p.m_{k}" for k in MISSING_FIELDS)},
               a.*
          FROM agg a
          LEFT JOIN LATERAL (
                SELECT * FROM picked
                 ORDER BY pickup_day DESC, unit, team, order_id
                 LIMIT {MAX_ROWS}
          ) p ON TRUE
        """
    )
    pool = get_datalake_gold_pool(request)
    async with pool.acquire() as conn:
        rows = await conn.fetch(sql, *params)

    head = rows[0] if rows else None
    counts_out = {k: int(head[f"n_{k}"] or 0) if head else 0 for k in MISSING_FIELDS}
    data = [
        {
            "order_id": r["order_id"],
            "unit": r["unit"] or None,
            "team": r["team"] or None,
            "customer": r["customer_name"],
            "carrier": r["carrier_name"],
            "pickup_day": r["pickup_day"].isoformat(),
            "tracked": bool(r["tracked"]),
            "reason": r["reason"],
            "fields": {k: field_status(r, k) for k in MISSING_FIELDS},
        }
        for r in rows
        if r["order_id"] is not None
    ]
    total = int(rows[0]["total"]) if data else 0
    return {
        "success": True,
        "data": data,
        "meta": {
            "total": total,
            "truncated": total > len(data),
            "field": field or "all",
            "checked": int(head["checked_n"] or 0) if head else 0,
            "with_missing": int(head["any_n"] or 0) if head else 0,
            "counts": counts_out,
        },
    }
