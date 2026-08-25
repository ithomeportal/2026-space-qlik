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
    """Idempotently seed months, GL rows, approved archives, recalcs and loads.

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

            for s in data["snapshots"]:
                await conn.execute(
                    """
                    INSERT INTO dpc_snapshots
                      (year, month, month_label, revenue, carrier_cost, profit, margin_pct,
                       gl_deductions, penalty_fee, corporate_gain, net_payment,
                       snapshot_date, approved_by)
                    VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13)
                    ON CONFLICT (year, month) DO NOTHING
                    """,
                    s["year"], s["month"], s["month_label"], s["revenue"], s["carrier_cost"],
                    s["profit"], s["margin_pct"], s["gl_deductions"], s["penalty_fee"],
                    s["corporate_gain"], s["net_payment"], _date(s["snapshot_date"]), "seed",
                )

            for r in data["recalcs"]:
                await conn.execute(
                    """
                    INSERT INTO dpc_recalcs
                      (recalc_key, year, month, month_label, applied_to_month,
                       applied_to_month_label, recalc_date, status, previously_recalculated,
                       prior_recalc_net_payment, snapshot, tms_update, diff)
                    VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13)
                    ON CONFLICT (recalc_key) DO NOTHING
                    """,
                    r["recalc_key"], r["year"], r["month"], r["month_label"],
                    r["applied_to_month"], r["applied_to_month_label"], _date(r["recalc_date"]),
                    r["status"], r["previously_recalculated"], r["prior_recalc_net_payment"],
                    json.dumps(r["snapshot"]), json.dumps(r["tms_update"]), json.dumps(r["diff"]),
                )

            for a in data["audit_loads"]:
                await conn.execute(
                    """
                    INSERT INTO dpc_audit_loads
                      (recalc_key, load_number, client, change_type, change_description,
                       original_revenue, updated_revenue, original_carrier_cost,
                       updated_carrier_cost, revenue_delta, cost_delta, audit_date)
                    VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12)
                    ON CONFLICT (recalc_key, load_number) DO NOTHING
                    """,
                    a["recalc_key"], a["load_number"], a["client"], a["change_type"],
                    a["change_description"], a["original_revenue"], a["updated_revenue"],
                    a["original_carrier_cost"], a["updated_carrier_cost"],
                    a["revenue_delta"], a["cost_delta"], _date(a["audit_date"]),
                )

    total = await pool.fetchval("SELECT COUNT(*) FROM dpc_months")
    logger.info(f"Division Payment Calculator seeded — {total} months on file")
    return total
