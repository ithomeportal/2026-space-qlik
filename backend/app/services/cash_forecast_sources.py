"""Collections Settlement Forecast — the readers (UNLK-Financial + gold).

Every UNLK-Financial statement reads a mirror table the Financial Portal's own
cash-flow pages read (same filters), through Space's read-only
``FINANCIAL_DATABASE_URL`` role ``spaceqlik_financial_ro``. Bruce's shipped
revenue comes from ``mcleod_gld_budget_report_v4`` (gold, ``SAVINGS_DATABASE_URL``).
Each source is read in its OWN ``try``: one dead feed must not blank the others,
and a failed read is ``None`` (unknown), never $0.

| source                  | table (DB)                              | Financial page            |
|-------------------------|-----------------------------------------|---------------------------|
| open AR + due week      | ar_customer_forecast (financial)        | AR Collections Weekly Rev.|
| avg days to pay         | ar_customer_directory (financial)       | AR Collections (DSO)      |
| cash collected          | cash_receipts (financial)               | Cash Receipts / Actual    |
| receipts last read      | sync_job_runs (financial)               | intraday reconcile audit  |
| carrier settlements     | payment_schedules (financial)           | Settlement Projections    |
| vendor AP               | ap_reports (financial)                  | Accounts Payable          |
| shipped revenue         | mcleod_gld_budget_report_v4 (gold)      | — (Bruce's sheet)         |

⚠ UNILINK US (TMS) only — Mexico has no forecast feed. The intercompany
customers and the AP vendor exclusion are the Financial Portal's own lists
(``ar_collections_repository._AR_EXCLUDED_CUSTOMERS``,
``core/ap_exclusions.AP_EXCLUDED_VENDORS``); keep them in step.
"""
from __future__ import annotations

import logging
from datetime import date, datetime, timedelta, timezone
from typing import Any, Optional

from app.clock import CST
from app.datalake import pad_variants
from app.services.cash_forecast import ArOrder, Dated, FinanceWeek, Shipped, Sources
from app.services.cash_forecast_bruce import BILL_LAG_DAYS, LOOKBACK_WEEKS, MAX_PAY_DAYS

logger = logging.getLogger(__name__)

COMPANY_ID = "TMS"
AR_EXCLUDED_CUSTOMERS = ("MENCART1", "MENCARTX", "SEEKEQTX", "UNILINNL", "UNILINTX", "OILTEXTX")
AP_EXCLUDED_VENDORS = ("ALLIE & OLLIE LLC",)
RECEIPTS_CHECK_JOB_ID = "reconcile_cash_receipts_intraday"
#: Receipts history read for the typical week and the accuracy tab.
RECEIPTS_WEEKS_BACK = 13
#: v4 statuses that ship: Delivered, in Progress (V = void is excluded).
SHIPPED_STATUSES = ("D", "P")


def _sql_list(values: tuple[str, ...]) -> str:
    return ", ".join("'" + v.replace("'", "''") + "'" for v in values)


_AR_EXCL = _sql_list(AR_EXCLUDED_CUSTOMERS)
_AP_EXCL = _sql_list(AP_EXCLUDED_VENDORS)

AR_ORDERS_SQL = """
    SELECT snapshot_date, TRIM(order_id) AS order_id, TRIM(customer_id) AS customer_id,
           customer_name, balance, bill_date, bill_due_days, customer_payment_date, week_n
      FROM ar_customer_forecast
     WHERE snapshot_date = (SELECT MAX(snapshot_date) FROM ar_customer_forecast
                             WHERE TRIM(company_id) = $1)
       AND TRIM(company_id) = $1
       AND balance > 0
       AND week_n IS NOT NULL
"""

# McLeod customer_info.average_pay_days, mirrored by UNLK-Financial.
DIRECTORY_SQL = """
    SELECT TRIM(customer_id) AS customer_id, MAX(average_pay_days) AS average_pay_days
      FROM ar_customer_directory
     WHERE TRIM(company_id) = $1 AND average_pay_days IS NOT NULL
     GROUP BY 1
"""

# Receipts are stored NEGATIVE (cash received); weeks are Saturday-anchored on $2.
RECEIPTS_WEEKLY_SQL = f"""
    SELECT ($2::date + (7 * FLOOR((gl_dist_date - $2::date) / 7.0))::int) AS week_start,
           -SUM(amount) AS collected,
           MAX(gl_dist_date) AS latest
      FROM cash_receipts
     WHERE TRIM(company_id) = $1
       AND gl_dist_date >= $2 AND gl_dist_date <= $3
       AND customer_code NOT IN ({_AR_EXCL})
     GROUP BY 1
"""

RECEIPTS_BY_ORDER_SQL = f"""
    SELECT TRIM(order_id) AS order_id, -SUM(amount) AS paid
      FROM cash_receipts
     WHERE TRIM(company_id) = $1
       AND gl_dist_date BETWEEN $2 AND $3
       AND customer_code NOT IN ({_AR_EXCL})
     GROUP BY 1
"""

RECEIPTS_CHECKED_SQL = """
    SELECT MAX(finished_at) AS checked FROM sync_job_runs WHERE job_id = $1 AND status = 'ok'
"""

_BUCKETS = ("current_week", "week1", "week2", "week3", "week4")
_PAY_COL = {"current_week": "current_total_pay", **{b: f"{b}_total_pay" for b in _BUCKETS[1:]}}
# `1900-01-01` means "not in this bucket" in the McLeod feed.
SETTLEMENTS_SQL = (
    "WITH s AS (SELECT * FROM payment_schedules "
    "WHERE snapshot_date = (SELECT MAX(snapshot_date) FROM payment_schedules)) "
    "SELECT pay_date, SUM(amount) AS amount, COUNT(DISTINCT payee_id) AS payees "
    "FROM ("
    + " UNION ALL ".join(
        f"SELECT {b}_date AS pay_date, {_PAY_COL[b]} AS amount, payee_id FROM s"
        for b in _BUCKETS
    )
    + ") b WHERE pay_date > DATE '1900-12-31' AND amount IS NOT NULL AND amount <> 0 "
    "GROUP BY pay_date ORDER BY pay_date"
)

SETTLEMENTS_FUTURE_SQL = """
    SELECT MAX(snapshot_date) AS snap, COALESCE(SUM(future_total_pay), 0) AS future
      FROM payment_schedules
     WHERE snapshot_date = (SELECT MAX(snapshot_date) FROM payment_schedules)
"""

AP_SQL = f"""
    SELECT due_date, SUM(COALESCE(balance_usd, balance)) AS amount, COUNT(*) AS items,
           MAX(snapshot_date) AS snap
      FROM ap_reports
     WHERE snapshot_date = (SELECT MAX(snapshot_date) FROM ap_reports)
       AND UPPER(TRIM(COALESCE(vendor_name, ''))) NOT IN ({_AP_EXCL})
     GROUP BY due_date
"""

# Bruce's "AR & AP Actuals": revenue per customer per base date. Sargable on
# the indexed origin_actual_departure; padded-key literals, never TRIM() in the
# WHERE. bill_date carries a 1900 sentinel until the load is invoiced (128
# loads measured 2026-10-27) — guarded, never subtracted.
SHIPPED_SQL = """
    SELECT TRIM(customer_id) AS customer_id, MAX(TRIM(customer_name)) AS customer_name,
           CASE WHEN bill_date >= DATE '2000-01-01' THEN bill_date::date
                ELSE origin_actual_departure::date + $5::int END AS base_date,
           SUM(total_charge) AS revenue
      FROM mcleod_gld_budget_report_v4
     WHERE origin_actual_departure >= $1
       AND company_id = ANY($2::text[])
       AND status = ANY($3::text[])
       AND NOT (customer_id = ANY($4::text[]))
       AND total_charge IS NOT NULL AND total_charge <> 0
     GROUP BY 1, 3
"""

SHIPPED_FRESH_SQL = "SELECT MAX(updated_dt) FROM mcleod_gld_budget_report_v4"

FINANCIAL_STATEMENTS = {
    "ar_orders": AR_ORDERS_SQL,
    "directory": DIRECTORY_SQL,
    "receipts_weekly": RECEIPTS_WEEKLY_SQL,
    "receipts_by_order": RECEIPTS_BY_ORDER_SQL,
    "receipts_checked": RECEIPTS_CHECKED_SQL,
    "settlements": SETTLEMENTS_SQL,
    "settlements_future": SETTLEMENTS_FUTURE_SQL,
    "ap": AP_SQL,
}
GOLD_STATEMENTS = {"shipped": SHIPPED_SQL, "shipped_fresh": SHIPPED_FRESH_SQL}


def _f(v: Any) -> float:
    return 0.0 if v is None else float(v)


def _ct(stamp: Optional[datetime], naive_is_utc: bool) -> Optional[str]:
    """A stamp as Chicago wall time ("2026-10-26 15:31 CT")."""
    if stamp is None:
        return None
    if stamp.tzinfo is None:
        if not naive_is_utc:  # gold is already CST (feedback_datalake_gold_already_cst)
            return stamp.strftime("%Y-%m-%d %H:%M CT")
        stamp = stamp.replace(tzinfo=timezone.utc)
    return stamp.astimezone(CST).strftime("%Y-%m-%d %H:%M CT")


def shipped_params(week: FinanceWeek) -> tuple:
    since = week.start - timedelta(weeks=LOOKBACK_WEEKS, days=MAX_PAY_DAYS)
    return (
        datetime.combine(since, datetime.min.time()),
        pad_variants([COMPANY_ID], width=4),
        pad_variants(list(SHIPPED_STATUSES), width=1),
        pad_variants(list(AR_EXCLUDED_CUSTOMERS), width=8),
        BILL_LAG_DAYS,
    )


async def _read_ar(pool, src: Sources) -> None:
    rows = await pool.fetch(AR_ORDERS_SQL, COMPANY_ID)
    src.ar_orders = [
        ArOrder(
            order_id=r["order_id"], customer_id=r["customer_id"] or "",
            customer_name=(r["customer_name"] or r["customer_id"] or "").strip(),
            balance=_f(r["balance"]), bill_date=r["bill_date"], terms_days=r["bill_due_days"],
            terms_date=r["customer_payment_date"], week_n=int(r["week_n"]),
        )
        for r in rows
    ]
    src.ar_snapshot = rows[0]["snapshot_date"] if rows else None
    if src.ar_snapshot is None:  # an empty snapshot is unknown, not "nothing owed"
        src.ar_orders = None
        raise RuntimeError("ar_customer_forecast has no TMS rows")


async def _read_directory(pool, src: Sources) -> None:
    rows = await pool.fetch(DIRECTORY_SQL, COMPANY_ID)
    src.pay_days = {r["customer_id"]: float(r["average_pay_days"]) for r in rows}


async def _read_receipts(pool, src: Sources) -> None:
    start = src.week.start - timedelta(weeks=RECEIPTS_WEEKS_BACK)
    weekly = await pool.fetch(RECEIPTS_WEEKLY_SQL, COMPANY_ID, start, src.week.end)
    by_order = await pool.fetch(RECEIPTS_BY_ORDER_SQL, COMPANY_ID, src.week.start, src.week.end)
    src.receipts_by_week = {r["week_start"]: _f(r["collected"]) for r in weekly}
    src.latest_receipt_date = max((r["latest"] for r in weekly if r["latest"]), default=None)
    src.paid_this_week = {r["order_id"]: _f(r["paid"]) for r in by_order}


async def _read_receipts_checked(pool, src: Sources) -> None:
    stamp = await pool.fetchval(RECEIPTS_CHECKED_SQL, RECEIPTS_CHECK_JOB_ID)
    src.receipts_checked_at = _ct(stamp, naive_is_utc=True)


async def _read_settlements(pool, src: Sources) -> None:
    rows = await pool.fetch(SETTLEMENTS_SQL)
    future = await pool.fetchrow(SETTLEMENTS_FUTURE_SQL)
    if not future or future["snap"] is None:
        raise RuntimeError("payment_schedules is empty")
    src.settlements = [Dated(when=r["pay_date"], amount=_f(r["amount"]), count=int(r["payees"]))
                       for r in rows]
    src.settlements_future = _f(future["future"])
    src.settlements_snapshot = future["snap"]


async def _read_ap(pool, src: Sources) -> None:
    rows = await pool.fetch(AP_SQL)
    src.ap = [Dated(when=r["due_date"], amount=_f(r["amount"]), count=int(r["items"])) for r in rows]
    src.ap_snapshot = max((r["snap"] for r in rows if r["snap"]), default=None)


async def _read_shipped(gold, src: Sources) -> None:
    if gold is None:
        raise RuntimeError("gold datalake pool not configured")
    rows = await gold.fetch(SHIPPED_SQL, *shipped_params(src.week))
    src.shipped = [
        Shipped(r["customer_id"] or "", (r["customer_name"] or "").strip(), r["base_date"], _f(r["revenue"]))
        for r in rows if r["base_date"] is not None
    ]
    src.shipped_fresh = _ct(await gold.fetchval(SHIPPED_FRESH_SQL), naive_is_utc=False)


FINANCIAL_READERS = (
    ("ar_forecast", _read_ar),
    ("pay_days", _read_directory),
    ("cash_receipts", _read_receipts),
    ("receipts_checked", _read_receipts_checked),
    ("settlements", _read_settlements),
    ("ap", _read_ap),
)


async def load_sources(financial_pool, gold_pool, week: FinanceWeek, today: date) -> Sources:
    """Read every source; a failed one stays ``None`` and is named in ``errors``."""
    src = Sources(week=week, today=today)
    readers = [(n, financial_pool, r) for n, r in FINANCIAL_READERS]
    readers.append(("shipped_revenue", gold_pool, _read_shipped))
    for name, pool, reader in readers:
        try:
            await reader(pool, src)
        except Exception as e:  # that source reads as unknown, never $0
            logger.warning("cash forecast: %s read failed: %s", name, e)
            src.errors.append(name)
    return src


def freshness(src: Sources) -> dict:
    """The "data as of" line for every source (cron-job-debug §10)."""
    def iso(d: Optional[date]) -> Optional[str]:
        return d.isoformat() if d else None

    return {
        "ar_snapshot_date": iso(src.ar_snapshot),
        "latest_receipt_gl_date": iso(src.latest_receipt_date),
        "receipts_checked_at": src.receipts_checked_at,
        "settlements_snapshot_date": iso(src.settlements_snapshot),
        "ap_snapshot_date": iso(src.ap_snapshot),
        "shipped_as_of": src.shipped_fresh,
        "failed_sources": list(src.errors),
        "now_ct": datetime.now(CST).strftime("%Y-%m-%d %H:%M CT"),
    }
