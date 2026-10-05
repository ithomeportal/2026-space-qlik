"""Seed data for the Division Payment Calculator (Bruno PDF 2026-08-13).

The report has no datalake feed: A&O's GL deduction lines (payroll, parking,
subscriptions…) live in the accounting system, not in any database this portal
can reach, and the PDF specifies Revenue / Carrier Cost as **input fields**.
So this is a calculator with server-side persistence — closest sibling is the
Bonus Calculator (``bonus_defaults.py``), which this module mirrors.

The payload in ``division_payment_seed.json`` was transcribed from the vendor
prototype's ``client/src/lib/glAccounts.ts`` (19 months: 2026 Jan-Jul + 2025
Jan-Dec, ~370 GL rows, 5 recalculations, 9 audit loads). Four data defects in
the prototype were corrected on the way in — see ``docs/SPEC-DIVISION-PAYMENT.md``:

  1. ``rec-mar.snapshot.glDeductions`` carried **May's** total ($142,120 instead
     of $65,530), rendering March as a −$47,120 loss instead of a +$29,470
     profit. Every recalc snapshot is now derived from that month's own GL rows.
  2. Audit loads reconciled with none of the five recalcs, and ``rec-feb``'s were
     sign-inverted. Per-load splits now sum exactly to the recalc's delta, and
     ``rec-jan-2`` gained the load detail it was missing.
  3. ``snapshotDate`` generated invalid dates (``2026-13-15`` … ``2026-19-15``)
     and stamped 2025 months with 2026. Archives now use the 15th of the
     following month, in the correct year.
  4. No money figure is hand-typed any more: snapshots, TMS updates and diffs
     are all computed with the same arithmetic the router serves at runtime, so
     every seeded recalc lands on exactly 25 % / 75 %.

⚠ **Every GL amount in the payload is 0.00** (Bruno PDF 2026-08-24 R1). The
prototype shipped its own figures on all 366 rows; they were demo data, not
A&O's accounting, and the round that made the Amount cell editable made the
sheet start blank instead. Revenue / carrier cost / profit are untouched — only
``gl_accounts[*].amount``. The already-seeded months were zeroed by a one-off
UPDATE at the same time, because the GL block below only fires for a month that
has NO rows: re-seeding cannot reach a live month, by design.

⚠ Every INSERT is ``ON CONFLICT DO NOTHING``, **never DO UPDATE**. Seeding runs
on every startup (see ``main.py`` lifespan); a ``DO UPDATE`` would silently
revert the user's include/exclude toggles, edited amounts and custom expense
rows on each deploy.
"""

from __future__ import annotations

import json
import logging
from datetime import date
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)

_SEED_PATH = Path(__file__).with_name("division_payment_seed.json")


def load_seed() -> dict[str, Any]:
    """Read the seed payload off disk. Cheap enough to not bother caching."""
    return json.loads(_SEED_PATH.read_text(encoding="utf-8"))


def _date(value: Optional[str]) -> Optional[date]:
    """Bind a real ``date`` to a DATE column, never the ISO string (§4).

    asyncpg does no implicit coercion: passing ``'2026-02-15'`` raises
    ``DataError: 'str' object has no attribute 'toordinal'``. Because this whole
    seed is wrapped in a ``try/except`` at the call site, that would not have
    crashed startup — it would have logged one warning and left the report with
    no data at all.
    """
    return date.fromisoformat(value) if value else None


async def seed_division_payment(pool) -> int:
    """Idempotently seed months and GL rows.

    Returns the number of month rows the portal knows about afterwards. Safe to
    call on every startup: existing rows are left exactly as the user left them.
    """
    data = load_seed()
    months: list[dict] = data["months"]
    gl_by_month: dict[str, list[dict]] = data["gl_accounts"]

    async with pool.acquire() as conn:
        async with conn.transaction():
            for m in months:
                await conn.execute(
                    """
                    INSERT INTO dpc_months
                      (year, month, month_label, revenue, carrier_cost, profit, sort_order)
                    VALUES ($1,$2,$3,$4,$5,$6,$7)
                    ON CONFLICT (year, month) DO NOTHING
                    """,
                    m["year"], m["month"], m["month_label"],
                    m["revenue"], m["carrier_cost"], m["profit"], m["sort_order"],
                )

            # GL rows hang off the month row. Seed only when the month has no
            # rows at all — a month the user has edited (rows deleted, custom
            # rows added) must not have the template pushed back into it.
            # ⚠ The COUNT deliberately includes soft-deleted rows: since Bruno
            # PDF 2026-10-05 every row is deletable, and a month whose rows were
            # ALL deleted would otherwise be refilled on the next deploy.
            for m in months:
                key = f"{m['year']}-{m['month']}"
                month_id = await conn.fetchval(
                    "SELECT id FROM dpc_months WHERE year = $1 AND month = $2",
                    m["year"], m["month"],
                )
                existing = await conn.fetchval(
                    "SELECT COUNT(*) FROM dpc_gl_accounts WHERE month_id = $1", month_id
                )
                if existing:
                    continue
                for row in gl_by_month.get(key, []):
                    await conn.execute(
                        """
                        INSERT INTO dpc_gl_accounts
                          (month_id, code, category, description, amount, included, sort_order)
                        VALUES ($1,$2,$3,$4,$5,$6,$7)
                        """,
                        month_id, row["code"], row["category"], row["description"],
                        row["amount"], row["included"], row["sort_order"],
                    )

            # Approved archives are NOT seeded (2026-10-05, Diego: "it's a
            # production site"). The 17 prototype archives were invented figures
            # shown as "the original approved calculations that were paid", and
            # they marked 17 months approved that nobody approved. Deleted from
            # the live DB the same day (approved_by = 'seed'); only the JSON keeps
            # them, as fixtures for the arithmetic tests. ⚠ Re-adding this loop
            # would RE-CREATE them on the next deploy — ON CONFLICT DO NOTHING
            # re-inserts a deleted row.

            # The five vendor demo recalculations (rec-jan … rec-apr, rec-jan-2)
            # are NOT seeded any more (Bruno PDF 2026-10-05, Recalculations R1-R3):
            # they were the prototype's invented records, they silently moved the
            # Feb-May 2026 net payments, and the tab now lists real post-cutoff
            # order changes from v4 instead. Kept in the JSON only as fixtures for
            # the 25/75 arithmetic tests.

    total = await pool.fetchval("SELECT COUNT(*) FROM dpc_months")
    logger.info(f"Division Payment Calculator seeded — {total} months on file")
    return total


async def ensure_months_through(pool, today: date) -> int:
    """Create every missing month row from Jan 2025 through ``today``'s month.

    Bruno PDF 2026-10-05 R2: the Month filter stopped at July 2026 because the
    month rows only ever came from the seed. Called by ``/periods`` and
    ``/summary`` so a month rollover needs no deploy. Normally one SELECT.

    A new month inherits the GL sheet of the most recent earlier month that has
    one — same codes, categories, descriptions and Include flags — at **$0.00**
    (the sheet starts blank, PDF 2026-08-24 R1). Soft-deleted rows are not
    carried. ``ON CONFLICT DO NOTHING … RETURNING`` means only the request that
    actually created the month copies the sheet, so two concurrent requests
    cannot double it.
    """
    from app.services.division_payment_v4 import (
        FIRST_MONTH, MONTH_ORDER, month_label, months_between,
    )

    wanted = months_between(FIRST_MONTH, (today.year, today.month))
    have = {
        (r["year"], r["month"])
        for r in await pool.fetch("SELECT year, month FROM dpc_months")
    }
    missing = [(y, m) for y, m in wanted if (y, MONTH_ORDER[m - 1]) not in have]
    if not missing:
        return 0

    created = 0
    async with pool.acquire() as conn:
        async with conn.transaction():
            for y, m in missing:
                month = MONTH_ORDER[m - 1]
                new_id = await conn.fetchval(
                    """
                    INSERT INTO dpc_months (year, month, month_label, sort_order)
                    VALUES ($1, $2, $3, $4)
                    ON CONFLICT (year, month) DO NOTHING
                    RETURNING id
                    """,
                    y, month, month_label(y, m), y * 100 + m,
                )
                if new_id is None:
                    continue
                created += 1
                source = await conn.fetchval(
                    """
                    SELECT dm.id
                      FROM dpc_months dm
                     WHERE (dm.year * 100 + array_position($1::text[], dm.month)) < $2
                       AND EXISTS (SELECT 1 FROM dpc_gl_accounts g
                                    WHERE g.month_id = dm.id AND g.deleted_at IS NULL)
                     ORDER BY dm.year DESC, array_position($1::text[], dm.month) DESC
                     LIMIT 1
                    """,
                    MONTH_ORDER, y * 100 + m,
                )
                if source is None:
                    continue
                await conn.execute(
                    """
                    INSERT INTO dpc_gl_accounts
                      (month_id, code, category, description, amount, included,
                       is_custom, sort_order, created_by)
                    SELECT $1, code, category, description, 0, included,
                           is_custom, sort_order, 'month-rollover'
                      FROM dpc_gl_accounts
                     WHERE month_id = $2 AND deleted_at IS NULL
                    """,
                    new_id, source,
                )
    if created:
        logger.info("Division Payment: created %d new month(s) through %s", created, today)
    return created
