"""One-time loader: the "2016-2026" sheet of Bruce's workbook → customer_lifespan_orders.

Customer Lifespan (#69, request 2026-10-29). The sheet has one row per
MOVEMENT (363,028 rows, 284,511 orders); the report stores one row per ORDER,
so movements are summed per order here (``collapse_movements``). Only the
first 40 columns are data — the rest are the workbook's helper formulas.

Idempotent: every ``source='excel'`` row is replaced in ONE transaction, and an
order the nightly v4 sync stored as a gap fill is taken over by its Excel row.
Uses the application's ``Settings`` for ``DATABASE_URL`` — no credential on the
command line. The table must already exist (the app's startup DDL creates it,
so the app role owns it): deploy first, load second.

    cd backend && python -m tools.load_customer_lifespan_excel "/path/2016-2026 Analysis.xlsx"
    cd backend && python -m tools.load_customer_lifespan_excel export.csv --dry-run

A ``.xlsx`` needs ``python-calamine`` (local only, not in requirements.txt);
a ``.csv`` export of the "2016-2026" sheet needs nothing.
"""
from __future__ import annotations

import argparse
import asyncio
import csv
import re
import sys
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from datetime import date, datetime

import asyncpg

from app.config import settings
from app.services.customer_lifespan_store import COMPANY_ID, CUTOVER

SHEET = "2016-2026"
REQUIRED = ("Order", "Ship date", "Customer", "Salesperson", "Total revenue",
            "Carrier total pay", "Margin $")


@dataclass(frozen=True)
class Order:
    order_id: str
    ship_date: date
    customer_id: str
    customer_name: str
    division: str
    revenue: float
    carrier_pay: float
    margin: float
    movements: int

    def record(self) -> tuple:
        return (COMPANY_ID, self.order_id, self.ship_date, self.customer_id, self.customer_name,
                self.division, round(self.revenue, 2), round(self.carrier_pay, 2),
                round(self.margin, 2), self.movements, "excel")


def _num(v) -> float:
    if v in (None, ""):
        return 0.0
    return float(v)


def _day(v) -> date:
    if isinstance(v, datetime):
        return v.date()
    if isinstance(v, date):
        return v
    return date.fromisoformat(str(v)[:10])


def split_customer(value: str) -> tuple[str, str]:
    """``"RUANTRIA - Ruan Transport Corporation"`` → (id, name)."""
    cid, _, name = str(value).partition(" - ")
    return cid.strip(), (name.strip() or cid.strip())


def division_of(salesperson: str) -> str:
    """Workbook "Salesperson": TEAM-DFW → DFW; CORP and blank (TEAM5 / Oiltex) → CORP."""
    return "DFW" if str(salesperson).strip().upper() == "TEAM-DFW" else "CORP"


def collapse_movements(rows: Iterable[dict]) -> list[Order]:
    """Movement rows → one ``Order`` each: sums, earliest ship date, row count."""
    acc: dict[str, Order] = {}
    for r in rows:
        oid = str(r["Order"]).strip()
        if not oid:
            continue
        cid, name = split_customer(r["Customer"])
        cur = Order(oid, _day(r["Ship date"]), cid, name, division_of(r["Salesperson"]),
                    _num(r["Total revenue"]), _num(r["Carrier total pay"]), _num(r["Margin $"]), 1)
        prev = acc.get(oid)
        if prev is not None:
            cur = Order(oid, min(prev.ship_date, cur.ship_date), prev.customer_id,
                        prev.customer_name, prev.division, prev.revenue + cur.revenue,
                        prev.carrier_pay + cur.carrier_pay, prev.margin + cur.margin,
                        prev.movements + 1)
        acc[oid] = cur
    return list(acc.values())


def _dicts(header: list, rows: Iterable[list]) -> Iterator[dict]:
    cols = [str(h).strip() for h in header[:40]]
    missing = [c for c in REQUIRED if c not in cols]
    if missing:
        raise SystemExit(f"not the '{SHEET}' sheet — missing columns {missing}")
    for row in rows:
        yield dict(zip(cols, row[:40]))


def read_rows(path: str) -> Iterator[dict]:
    if path.lower().endswith(".csv"):
        with open(path, newline="", encoding="utf-8-sig") as f:
            reader = csv.reader(f)
            yield from _dicts(next(reader), reader)
        return
    try:
        from python_calamine import CalamineWorkbook
    except ImportError as exc:
        raise SystemExit("reading .xlsx needs python-calamine — or pass a .csv export") from exc
    data = CalamineWorkbook.from_path(path).get_sheet_by_name(SHEET).to_python()
    yield from _dicts(data[0], data[1:])


STAGE_SQL = """
CREATE TEMP TABLE excel_stage (LIKE customer_lifespan_orders INCLUDING DEFAULTS) ON COMMIT DROP
"""
STAGE_COLUMNS = ("company_id", "order_id", "ship_date", "customer_id", "customer_name",
                 "division", "revenue", "carrier_pay", "margin", "movements", "source")
DELETE_EXCEL_SQL = "DELETE FROM customer_lifespan_orders WHERE source = 'excel'"
UPSERT_SQL = f"""
INSERT INTO customer_lifespan_orders ({", ".join(STAGE_COLUMNS)})
SELECT {", ".join(STAGE_COLUMNS)} FROM excel_stage
ON CONFLICT (company_id, order_id) DO UPDATE SET
  {", ".join(f"{c} = EXCLUDED.{c}" for c in STAGE_COLUMNS[2:])},
  voided_in_datalake = FALSE, loaded_at = NOW()
"""


async def load(orders: list[Order]) -> int:
    url = re.sub(r"[?&]sslmode=[a-zA-Z-]+", "", settings.DATABASE_URL)
    conn = await asyncpg.connect(url, ssl="require", timeout=60)
    try:
        async with conn.transaction():
            await conn.execute(STAGE_SQL)
            await conn.copy_records_to_table("excel_stage", records=[o.record() for o in orders],
                                             columns=list(STAGE_COLUMNS))
            await conn.execute(DELETE_EXCEL_SQL)
            await conn.execute(UPSERT_SQL)
            return await conn.fetchval(
                "SELECT COUNT(*) FROM customer_lifespan_orders WHERE source = 'excel'")
    finally:
        await conn.close()


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("path")
    ap.add_argument("--dry-run", action="store_true", help="collapse and report, write nothing")
    args = ap.parse_args()
    orders = [o for o in collapse_movements(read_rows(args.path)) if o.ship_date < CUTOVER]
    movements = sum(o.movements for o in orders)
    print(f"{movements:,} movements → {len(orders):,} orders, "
          f"{len({o.customer_id for o in orders})} customers, "
          f"ship {min(o.ship_date for o in orders)} → {max(o.ship_date for o in orders)}, "
          f"revenue ${sum(o.revenue for o in orders):,.2f}")
    if args.dry_run:
        return
    stored = asyncio.run(load(orders))
    print(f"stored {stored:,} excel orders")
    if stored != len(orders):
        sys.exit(f"expected {len(orders):,} rows, table holds {stored:,}")


if __name__ == "__main__":
    main()
