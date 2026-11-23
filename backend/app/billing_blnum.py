"""The ONE ``blnum`` lookup from ``mcleod_gld_billing_blnum_comments``.

Requested 2026-11-23 (PDFs "space -- Aging Updates" + "space -- Ops Portal DFW")
for Admin Aging Cashflow's two unbilled tables and the Ops Portal Unbilled
board. Both routers build their SQL from :func:`billing_blnum_join`, so the
rules below live in one place.

What the table is (measured on live gold 2026-11-23)
----------------------------------------------------
McLeod's BILLING QUEUE: an order gets a row when it is transferred to billing
(ready to bill) and the row is deleted when the order is invoiced. So the
column is BLANK on every not-yet-ready row by nature — 0 of 143 delivered,
not-ready cashflow orders and 0 of 274 in-progress v4 orders match. That is
correct, not a broken join.

Its ``blnum`` is the order's BL (``customer_view.blnum``) in 354 / 363 rows; in
the rest it carries the billing clerk's note ('378-38826*spot',
'233403408*double tonu'). Shown verbatim — never normalised.

The traps
---------
* ``order_id`` is blank-PADDED to 8 ('0352397 '); ``mcleod_gld_cashflow.id`` is
  UNPADDED (§150). Both sides are rtrimmed inside an uncorrelated hash join,
  so either spelling matches. ``company_id`` likewise ('TMS ' padded to 4).
* It is a CHANGE LOG, not a snapshot: 371 of 467 rows were
  ``db_action='deletion'`` tombstones, 104 of them with no order at all, and
  an order can carry several rows. 121 tombstoned orders were still unbilled
  per cashflow, their BL equal to the order BL 97% of the time → owner
  decision 2026-11-23: show the LAST-KNOWN billing BL — a live ``upsert`` row
  first, else the newest tombstone. Blank BLs never win.
* No index on ``order_id`` (PK is ``(company_id, id)``, ``id`` = billing row
  id) — hence the dedupe-once join below, never a per-row LATERAL. If the
  change log grows into the hundreds of thousands, re-measure.
"""

from __future__ import annotations

import re

_IDENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*(\.[A-Za-z_][A-Za-z0-9_]*)?$")


def _ident(value: str) -> str:
    """Only plain (optionally alias-qualified) identifiers reach the SQL text."""
    if not isinstance(value, str) or not _IDENT.match(value):
        raise ValueError(f"not a SQL identifier: {value!r}")
    return value


def billing_blnum_join(order_col: str, company_col: str, alias: str = "bbl") -> str:
    """``LEFT JOIN`` exposing ``<alias>.blnum`` (NULL when the order has none).

    ``order_col`` / ``company_col`` are the outer query's order-id and
    company-id columns (e.g. ``c.id``, ``c.company_id``).

    ⚠ UNCORRELATED on purpose. The first cut was a LEFT JOIN LATERAL keyed
    ``b.order_id IN (c.id, rpad(c.id, 8))``: with no index on ``order_id`` it
    re-scanned the change log once per outer row and took the Unbilled board
    from ~0.7 s to ~3.2 s (measured live 2026-11-23). Deduping the small table
    ONCE and hash-joining on the rtrimmed key costs nothing and, because both
    sides are rtrimmed, matches padded and unpadded spellings alike.
    """
    o, co, a = _ident(order_col), _ident(company_col), _ident(alias)
    return f"""
      LEFT JOIN (
        SELECT DISTINCT ON (rtrim(b.company_id), rtrim(b.order_id))
               rtrim(b.company_id) AS company_key,
               rtrim(b.order_id)   AS order_key,
               btrim(b.blnum)      AS blnum
        FROM public.mcleod_gld_billing_blnum_comments b
        WHERE b.order_id IS NOT NULL
          AND NULLIF(btrim(b.blnum), '') IS NOT NULL
        ORDER BY rtrim(b.company_id), rtrim(b.order_id),
                 (b.db_action = 'upsert') DESC NULLS LAST,
                 b.last_execution DESC NULLS LAST,
                 b.updated_dt DESC NULLS LAST,
                 b.id DESC
      ) {a} ON {a}.order_key = rtrim({o}) AND {a}.company_key = rtrim({co})"""
