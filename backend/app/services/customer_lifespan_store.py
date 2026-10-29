"""Customer Lifespan (#69) — the portal-owned order table and its nightly sync.

Request 2026-10-29 ("2016-2026 Analysis.xlsx", Bruce): the gold datalake's
``mcleod_gld_budget_report_v4`` only starts 2020-12, the workbook goes back to
2016-01. So the report reads its OWN table in analytics_hub:

* ``source='excel'`` — the workbook's 363,028 movements collapsed to orders
  (ship date < ``CUTOVER``), loaded once by ``tools/load_customer_lifespan_excel.py``.
* ``source='v4'`` — every TMS order that departed on/after ``TAIL_START``,
  re-read from v4 every night (03:30 CST) and REPLACED in one transaction.
  ``ON CONFLICT DO NOTHING`` lets the Excel row win an overlap, so the v4 rows
  before ``CUTOVER`` are exactly the orders the extract MISSED at its cut date
  ("gap fills").

Each night the Excel's last two months (``TAIL_START`` → ``EXCEL_LAST_SHIP``) are
also re-checked order-by-order against v4 (matched / missing / voided since /
revenue drift) — the "nothing lost at the cut date" check the request asks for.
Measured 2026-10-29: 5,938 of 5,938 tail orders in v4, customer ids 100% equal,
revenue within $1 per order (v4 stores whole dollars).

Mapping (measured 2026-10-29, Jul–Aug 2026): Excel "Ship date" = v4
``origin_actual_departure`` (94% same day, rest ±1 day); Excel "Salesperson"
CORP = ``TEAM1-5``, TEAM-DFW = ``TEAM-DFW`` (+ the §134 DFW-marker rule); the
workbook is company ``TMS`` only (v4 ``TMS3`` is a different company).
"""
from __future__ import annotations

import json
import logging
from datetime import date, datetime, timedelta

from app.datalake import pad_variants
from app.division_marker import CORP_TEAM_IDS, DFW_TEAM_ID, division_team_id_sql

logger = logging.getLogger(__name__)

COMPANY_ID = "TMS "                     # analytics_hub key, as v4 stores it
CUTOVER = date(2026, 9, 1)              # Excel authoritative before, v4 from
EXCEL_LAST_SHIP = date(2026, 8, 31)     # the workbook's last ship date
TAIL_START = date(2026, 7, 1)           # Excel tail re-checked against v4 nightly
SHIP_SHIFT_MARGIN = timedelta(days=7)   # Excel vs v4 ship dates differ by ±1 day
SHIPPED_STATUSES = ("D", "P")           # delivered / in progress (Excel: Delivered/Progress)
MAX_SOURCE_AGE = timedelta(hours=48)    # older = v4 is frozen, refuse to sync
SHRINK_FLOOR = 0.5                      # a re-read under half the stored rows is refused

ORDERS_DDL = """
CREATE TABLE IF NOT EXISTS customer_lifespan_orders (
  company_id          TEXT          NOT NULL,
  order_id            TEXT          NOT NULL,
  ship_date           DATE          NOT NULL,
  customer_id         TEXT          NOT NULL,
  customer_name       TEXT,
  division            TEXT          NOT NULL,
  revenue             NUMERIC(14,2) NOT NULL DEFAULT 0,
  carrier_pay         NUMERIC(14,2) NOT NULL DEFAULT 0,
  margin              NUMERIC(14,2) NOT NULL DEFAULT 0,
  movements           INTEGER       NOT NULL DEFAULT 1,
  source              TEXT          NOT NULL,
  voided_in_datalake  BOOLEAN       NOT NULL DEFAULT FALSE,
  loaded_at           TIMESTAMPTZ   NOT NULL DEFAULT NOW(),
  PRIMARY KEY (company_id, order_id)
)
"""
ORDERS_INDEX_DDL = (
    "CREATE INDEX IF NOT EXISTS customer_lifespan_orders_customer_ship "
    "ON customer_lifespan_orders (customer_id, ship_date)"
)
SYNC_LOG_DDL = """
CREATE TABLE IF NOT EXISTS customer_lifespan_sync_log (
  id              BIGSERIAL    PRIMARY KEY,
  started_at      TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
  finished_at     TIMESTAMPTZ,
  status          TEXT         NOT NULL,
  v4_rows         INTEGER,
  stored_v4_rows  INTEGER,
  gap_fills       INTEGER,
  v4_last_write   TIMESTAMP,
  reconciliation  JSONB,
  error           TEXT
)
"""
DDL = (ORDERS_DDL, ORDERS_INDEX_DDL, SYNC_LOG_DDL)

# ---------------------------------------------------------------- gold (v4)

V4_FRESHNESS_SQL = "SELECT MAX(updated_dt) FROM mcleod_gld_budget_report_v4"

#: Every shipped TMS order since ``TAIL_START``. ``division_team`` applies the
#: §134 DFW-marker rule (a CORP team_id with team TM1-5 is a DFW load).
V4_ORDERS_SQL = f"""
SELECT TRIM(v4.id)                           AS order_id,
       v4.origin_actual_departure::date      AS ship_date,
       TRIM(v4.customer_id)                  AS customer_id,
       TRIM(v4.customer_name)                AS customer_name,
       {division_team_id_sql("v4")}          AS division_team,
       COALESCE(v4.total_charge, 0)          AS revenue,
       COALESCE(v4.total_carrier_pay, 0)     AS carrier_pay,
       COALESCE(v4.margin_amt, 0)            AS margin
  FROM mcleod_gld_budget_report_v4 v4
 WHERE v4.company_id = ANY($1::text[])
   AND v4.status = ANY($2::text[])
   AND v4.origin_actual_departure >= $3
   AND v4.customer_id IS NOT NULL
   AND TRIM(v4.customer_id) <> ''
"""

#: The Excel tail's orders as v4 holds them TODAY (any status, voids included).
V4_BY_ID_SQL = """
SELECT TRIM(v4.id)                       AS order_id,
       v4.status                         AS status,
       v4.origin_actual_departure::date  AS ship_date,
       COALESCE(v4.total_charge, 0)      AS revenue
  FROM mcleod_gld_budget_report_v4 v4
 WHERE v4.company_id = ANY($1::text[])
   AND v4.id = ANY($2::text[])
"""

# ---------------------------------------------------------------- analytics_hub

EXCEL_TAIL_SQL = """
SELECT order_id, ship_date, revenue
  FROM customer_lifespan_orders
 WHERE source = 'excel' AND ship_date >= $1
"""
COUNT_V4_SQL = "SELECT COUNT(*) FROM customer_lifespan_orders WHERE source = 'v4'"
DELETE_V4_SQL = "DELETE FROM customer_lifespan_orders WHERE source = 'v4'"
INSERT_V4_SQL = """
INSERT INTO customer_lifespan_orders
  (company_id, order_id, ship_date, customer_id, customer_name, division,
   revenue, carrier_pay, margin, movements, source)
VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, 1, 'v4')
ON CONFLICT (company_id, order_id) DO NOTHING
"""
GAP_FILLS_SQL = """
SELECT COUNT(*) FROM customer_lifespan_orders WHERE source = 'v4' AND ship_date < $1
"""
MARK_VOIDED_SQL = """
UPDATE customer_lifespan_orders
   SET voided_in_datalake = (order_id = ANY($2::text[]))
 WHERE source = 'excel' AND ship_date >= $1
   AND voided_in_datalake IS DISTINCT FROM (order_id = ANY($2::text[]))
"""
LOG_START_SQL = (
    "INSERT INTO customer_lifespan_sync_log (status) VALUES ('running') RETURNING id"
)
LOG_OK_SQL = """
UPDATE customer_lifespan_sync_log
   SET finished_at = NOW(), status = 'ok', v4_rows = $2, stored_v4_rows = $3,
       gap_fills = $4, v4_last_write = $5, reconciliation = $6::jsonb
 WHERE id = $1
"""
LOG_FAILED_SQL = """
UPDATE customer_lifespan_sync_log
   SET finished_at = NOW(), status = 'failed', error = $2
 WHERE id = $1
"""
LAST_OK_SYNC_SQL = """
SELECT finished_at FROM customer_lifespan_sync_log
 WHERE status = 'ok' ORDER BY finished_at DESC LIMIT 1
"""


def division_of(division_team: str | None) -> str:
    """v4 ``division_team`` → the report's division label.

    Only TEAM1-5 is CORP; anything else (a new team, NULL) is ``OTHER`` — shown
    under "All", never silently inside CORP (review 2026-10-29). Measured
    2026-10-29: TMS since 2026-07-01 holds only TEAM-DFW and TEAM1-5.
    """
    team = (division_team or "").strip()
    if team == DFW_TEAM_ID:
        return "DFW"
    return "CORP" if team in CORP_TEAM_IDS else "OTHER"


def v4_records(rows) -> list[tuple]:
    """v4 rows → ``INSERT_V4_SQL`` parameter tuples — pure, so a test can pin them."""
    return [
        (COMPANY_ID, r["order_id"], r["ship_date"], r["customer_id"], r["customer_name"],
         division_of(r["division_team"]), r["revenue"], r["carrier_pay"], r["margin"])
        for r in rows
    ]


def reconcile(excel_tail, v4_tail, v4_window) -> dict:
    """The Excel tail vs v4 today — pure. Every count is an ORDER count.

    ``excel_tail``: hub rows (order_id, ship_date, revenue) shipped ≥ TAIL_START − 7 d.
    ``v4_tail``: v4 rows for those ids. ``v4_window``: v4 orders since TAIL_START.
    """
    # Every Excel id read (from a week before TAIL_START) decides what is a gap:
    # an order the workbook shipped 06-30 and v4 departed 07-01 is NOT missing.
    excel_ids = {r["order_id"] for r in excel_tail}
    excel_tail = [r for r in excel_tail if r["ship_date"] >= TAIL_START]
    v4_by_id = {r["order_id"]: r for r in v4_tail}
    matched = [(e, v4_by_id[e["order_id"]]) for e in excel_tail
               if e["order_id"] in v4_by_id and v4_by_id[e["order_id"]]["status"] != "V"]
    voided = sorted(r["order_id"] for r in v4_tail if r["status"] == "V")
    missing = sorted({r["order_id"] for r in excel_tail} - set(v4_by_id))
    excel_rev = sum(float(e["revenue"]) for e, _ in matched)
    v4_rev = sum(float(v["revenue"]) for _, v in matched)
    gap = [r for r in v4_window
           if r["ship_date"] <= EXCEL_LAST_SHIP and r["order_id"] not in excel_ids]
    return {
        "window": [TAIL_START.isoformat(), EXCEL_LAST_SHIP.isoformat()],
        "excel_orders": len(excel_tail),
        "matched": len(matched),
        "missing_in_datalake": len(missing),
        "missing_sample": missing[:10],
        "voided_in_datalake": len(voided),
        "voided_ids": voided,           # all of them: MARK_VOIDED_SQL reads this list
        "excel_revenue": round(excel_rev, 2),
        "datalake_revenue": round(v4_rev, 2),
        "revenue_diff": round(v4_rev - excel_rev, 2),
        "orders_revenue_off_over_1usd": sum(
            1 for e, v in matched if abs(float(e["revenue"]) - float(v["revenue"])) > 1.0),
        "orders_ship_month_moved": sum(
            1 for e, v in matched
            if v["ship_date"] and (v["ship_date"].year, v["ship_date"].month)
            != (e["ship_date"].year, e["ship_date"].month)),
        "gap_fill_orders": len(gap),
        "gap_fill_revenue": round(sum(float(r["revenue"]) for r in gap), 2),
    }


async def _read_datalake(gold, hub, now_cst: datetime) -> tuple[list, dict, datetime]:
    last_write = await gold.fetchval(V4_FRESHNESS_SQL)
    if last_write is None or now_cst - last_write > MAX_SOURCE_AGE:
        raise RuntimeError(f"budget_report_v4 is stale (last write {last_write}) — sync refused")
    companies = pad_variants((COMPANY_ID.strip(),), width=4)
    rows = await gold.fetch(
        V4_ORDERS_SQL, companies, list(SHIPPED_STATUSES),
        datetime.combine(TAIL_START, datetime.min.time()),
    )
    excel_tail = await hub.fetch(EXCEL_TAIL_SQL, TAIL_START - SHIP_SHIFT_MARGIN)
    ids = pad_variants([r["order_id"] for r in excel_tail if r["ship_date"] >= TAIL_START], width=8)
    v4_tail = await gold.fetch(V4_BY_ID_SQL, companies, ids) if ids else []
    return rows, reconcile(excel_tail, v4_tail, rows), last_write


async def sync_from_datalake(hub, gold, now_cst: datetime) -> dict:
    """Replace the v4 rows, flag Excel orders voided since, log the run. RAISES on failure.

    Fetch-then-write: every gold read finishes before the hub transaction
    opens (cron-job-debug §6). The run row is written FIRST, so a crash leaves
    a ``running``/``failed`` row, never silence.
    """
    if hub is None or gold is None:
        raise RuntimeError("customer lifespan sync: analytics_hub or gold pool missing")
    log_id = await hub.fetchval(LOG_START_SQL)
    try:
        rows, recon, last_write = await _read_datalake(gold, hub, now_cst.replace(tzinfo=None))
        stored = await hub.fetchval(COUNT_V4_SQL) or 0
        if stored > 200 and len(rows) < stored * SHRINK_FLOOR:
            raise RuntimeError(f"v4 returned {len(rows)} orders vs {stored} stored — refusing to shrink")
        async with hub.acquire() as conn, conn.transaction():
            await conn.execute(DELETE_V4_SQL)
            await conn.executemany(INSERT_V4_SQL, v4_records(rows))
            await conn.execute(MARK_VOIDED_SQL, TAIL_START, recon["voided_ids"])
            kept = await conn.fetchval(COUNT_V4_SQL)
            gap_fills = await conn.fetchval(GAP_FILLS_SQL, CUTOVER)
        await hub.execute(LOG_OK_SQL, log_id, len(rows), kept, gap_fills, last_write, json.dumps(recon))
        return {"v4_rows": len(rows), "stored_v4_rows": kept, "gap_fills": gap_fills,
                "matched": recon["matched"], "excel_orders": recon["excel_orders"]}
    except Exception as e:
        await hub.execute(LOG_FAILED_SQL, log_id, f"{type(e).__name__}: {e}"[:500])
        raise


async def last_ok_sync(hub) -> datetime | None:
    return await hub.fetchval(LAST_OK_SYNC_SQL)
