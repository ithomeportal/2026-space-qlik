"""Division Payment Calculator — the datalake half (Bruno PDF 2026-10-05).

Until this round the calculator's Revenue / Carrier Cost were typed in by hand
and the Recalculations tab replayed five vendor demo records. The PDF moves both
onto ``public.mcleod_gld_budget_report_v4`` (aivn_datalake_gold):

* **A&O inputs** — ``SUM(total_charge)``, ``SUM(total_carrier_pay)`` and
  ``SUM(margin_amt)`` over ``team_id = 'TEAM-DFW'`` for the selected month.
  The month is bucketed on ``origin_actual_departure``, the column the Ops
  Portal DFW and XRay DFW already use for revenue and profit (Diego 2026-10-05:
  bill_date differed by ~$340k on Sep-2026 and was not chosen).
* **Month close** — a month is finalised on the **10th of the following month**.
  On the first run after that cutoff every TEAM-DFW order of the month is frozen
  into ``dpc_cutoff_orders``; the Recalculations tab then lists the orders whose
  amounts moved afterwards. Tracking starts with September 2026 — earlier months
  closed before anything was recorded and cannot be reconstructed.

⚠ ``updated_dt`` on v4 is NOT a change signal. The ETL rewrites rows in bulk
(1,029 August rows carried a 2026-10-05 ``updated_dt`` on that day with no money
change), so "changed after the cutoff" can only be answered by diffing a stored
copy — which is exactly what the PDF asks for.

⚠ v4's key is ``(id, company_id)`` (its primary key). Every join and every diff
here keys on BOTH columns; ``company_id`` arrives space-padded (``'TMS '``) and
is stored and compared verbatim.

⚠ Population = ``team_id = 'TEAM-DFW'`` and nothing else, exactly as the PDF
writes it. Measured 2026-10-05 for Sep-2026: all 1,560 TEAM-DFW rows are company
``TMS``, none are UNILINK / OILTEX, and status is D (1,552) or P (8) — so the
Ops Portal's company/status/customer guards would not move a cent today. If
they ever diverge, parity is a DEFINITION question for Bruno (§95), not a fix.

⚠ The gold timestamps are already CST and NAIVE, so month bounds are bound as
naive ``datetime`` values — no ``AT TIME ZONE`` anywhere (§112).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Iterable, Optional

logger = logging.getLogger(__name__)

MONTH_ORDER = [
    "january", "february", "march", "april", "may", "june",
    "july", "august", "september", "october", "november", "december",
]

DFW_TEAM_ID = "TEAM-DFW"
CUTOFF_DAY = 10
# A snapshot with fewer orders than this share of the previous month's live
# count is refused (and retried next night): the ETL rewrites v4 in bulk, and a
# capture taken mid-rewrite would be frozen as the month's PERMANENT close.
MIN_CAPTURE_RATIO = Decimal("0.5")
# The first month whose cutoff snapshot exists (Bruno PDF 2026-10-05, p.3 R3).
TRACKING_START = (2026, 9)
# The first month the calculator lists — the portal's history starts here.
FIRST_MONTH = (2025, 1)

AMOUNT_COLS = ("total_charge", "total_carrier_pay", "margin_amt")

# ---------------------------------------------------------------------------
# SQL — module constants so the live replay executes the SAME text (never a
# hand-written mirror of it).
# ---------------------------------------------------------------------------
MONTH_TOTALS_SQL = """
SELECT EXTRACT(YEAR FROM br4.origin_actual_departure)::int  AS year,
       EXTRACT(MONTH FROM br4.origin_actual_departure)::int AS month_num,
       COALESCE(SUM(br4.total_charge), 0)      AS revenue,
       COALESCE(SUM(br4.total_carrier_pay), 0) AS carrier_cost,
       COALESCE(SUM(br4.margin_amt), 0)        AS profit,
       COUNT(*)                                AS order_count
  FROM public.mcleod_gld_budget_report_v4 br4
 WHERE br4.team_id = $1
   AND br4.origin_actual_departure >= $2
   AND br4.origin_actual_departure <  $3
 GROUP BY 1, 2
"""

MONTH_ORDERS_SQL = """
SELECT br4.id, br4.company_id, br4.customer_id, br4.customer_name,
       COALESCE(br4.total_charge, 0)      AS total_charge,
       COALESCE(br4.total_carrier_pay, 0) AS total_carrier_pay,
       COALESCE(br4.margin_amt, 0)        AS margin_amt
  FROM public.mcleod_gld_budget_report_v4 br4
 WHERE br4.team_id = $1
   AND br4.origin_actual_departure >= $2
   AND br4.origin_actual_departure <  $3
"""


# ---------------------------------------------------------------------------
# Calendar
# ---------------------------------------------------------------------------
def month_index(month: str) -> int:
    """1-based month number for a lowercase month name."""
    return MONTH_ORDER.index(month) + 1


def month_label(year: int, month_num: int) -> str:
    return f"{MONTH_ORDER[month_num - 1].title()} {year}"


def add_months(year: int, month_num: int, n: int) -> tuple[int, int]:
    total = year * 12 + (month_num - 1) + n
    return total // 12, total % 12 + 1


def month_bounds(year: int, month_num: int) -> tuple[datetime, datetime]:
    """Half-open naive bounds [1st 00:00, next 1st 00:00) — gold is naive CST."""
    ny, nm = add_months(year, month_num, 1)
    return datetime(year, month_num, 1), datetime(ny, nm, 1)


def cutoff_date(year: int, month_num: int) -> date:
    """The 10th of the following month — the day the month closes."""
    ny, nm = add_months(year, month_num, 1)
    return date(ny, nm, CUTOFF_DAY)


def is_closed(year: int, month_num: int, today: date) -> bool:
    """A month is final once its cutoff day has fully passed (from the 11th).

    "September is considered complete after the October 10 cutoff" — changes
    made ON the 10th still belong to the closing figures.
    """
    return today > cutoff_date(year, month_num)


def is_tracked_month(year: int, month_num: int) -> bool:
    return (year, month_num) >= TRACKING_START


def months_between(start: tuple[int, int], end: tuple[int, int]) -> list[tuple[int, int]]:
    """Inclusive list of (year, month_num) from ``start`` to ``end``."""
    out: list[tuple[int, int]] = []
    y, m = start
    while (y, m) <= end:
        out.append((y, m))
        y, m = add_months(y, m, 1)
    return out


def cutoff_status(year: int, month_num: int, today: date, has_snapshot: bool) -> str:
    """``open`` · ``before_tracking`` · ``snapshot_pending`` · ``tracked``."""
    if has_snapshot:
        return "tracked"
    if not is_closed(year, month_num, today):
        return "open"
    if not is_tracked_month(year, month_num):
        return "before_tracking"
    return "snapshot_pending"


def due_cutoff_months(today: date, captured: set[tuple[int, int]]) -> list[tuple[int, int]]:
    """Closed, tracked months that have no snapshot yet — what the job captures."""
    prev = add_months(today.year, today.month, -1)
    return [
        ym for ym in months_between(TRACKING_START, prev)
        if is_closed(*ym, today) and ym not in captured
    ]


# ---------------------------------------------------------------------------
# Reads
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class MonthTotals:
    revenue: Decimal
    carrier_cost: Decimal
    profit: Decimal
    order_count: int


ZERO_TOTALS = MonthTotals(Decimal(0), Decimal(0), Decimal(0), 0)


def _dec(v: Any) -> Decimal:
    if v is None:
        return Decimal(0)
    return v if isinstance(v, Decimal) else Decimal(str(v))


async def fetch_month_totals(
    gold, start: tuple[int, int], end: tuple[int, int],
) -> dict[tuple[int, int], MonthTotals]:
    """TEAM-DFW totals for every month in [start, end], zero-filled.

    One scan for the whole range (``idx_v4_dep`` on origin_actual_departure).
    A month with no orders is a real $0 month, not a missing one.
    """
    lo, _ = month_bounds(*start)
    _, hi = month_bounds(*end)
    rows = await gold.fetch(MONTH_TOTALS_SQL, DFW_TEAM_ID, lo, hi)
    out = {ym: ZERO_TOTALS for ym in months_between(start, end)}
    for r in rows:
        out[(r["year"], r["month_num"])] = MonthTotals(
            _dec(r["revenue"]), _dec(r["carrier_cost"]), _dec(r["profit"]),
            int(r["order_count"]),
        )
    return out


async def fetch_month_orders(gold, year: int, month_num: int) -> list:
    lo, hi = month_bounds(year, month_num)
    return await gold.fetch(MONTH_ORDERS_SQL, DFW_TEAM_ID, lo, hi)


# ---------------------------------------------------------------------------
# The diff — pure, so the "legs sum to the KPI" invariant is unit-testable
# ---------------------------------------------------------------------------
CENT = Decimal("0.01")


def _amounts(row) -> dict[str, Decimal]:
    """The three amounts, rounded to the cent.

    ⚠ v4 carries NUMERIC with 6 decimals; the snapshot stores NUMERIC(16,2).
    Comparing unrounded live values to stored cents would flag sub-cent noise
    as a "modified" order, so BOTH sides go through this one function.
    """
    return {c: _dec(row[c]).quantize(CENT) for c in AMOUNT_COLS}


def diff_orders(snapshot: Iterable, live: Iterable) -> dict[str, Any]:
    """Orders whose amounts differ between the cutoff snapshot and live v4.

    * ``modified`` — present on both sides, any of the three amounts moved;
    * ``added``    — in v4 now, absent at the cutoff (late-posted, or its
      departure date / team moved INTO this month after the close);
    * ``removed``  — frozen at the cutoff, gone from this month's v4 slice now.

    Unchanged orders contribute a zero delta, so ``totals`` equals live total −
    snapshot total exactly: the per-order legs SUM to the month's Δ.
    """
    snap = {(r["id"], r["company_id"]): r for r in snapshot}
    now = {(r["id"], r["company_id"]): r for r in live}
    changes: list[dict[str, Any]] = []
    totals = {c: Decimal(0) for c in AMOUNT_COLS}

    for key in sorted(set(snap) | set(now), key=lambda k: (str(k[0]), str(k[1]))):
        before = _amounts(snap[key]) if key in snap else None
        after = _amounts(now[key]) if key in now else None
        if before is not None and after is not None:
            if before == after:
                continue
            change_type = "modified"
        else:
            change_type = "added" if before is None else "removed"
        b = before or {c: Decimal(0) for c in AMOUNT_COLS}
        a = after or {c: Decimal(0) for c in AMOUNT_COLS}
        delta = {c: a[c] - b[c] for c in AMOUNT_COLS}
        for c in AMOUNT_COLS:
            totals[c] += delta[c]
        src = now.get(key) or snap[key]
        changes.append({
            "order_id": key[0],
            "company_id": key[1],
            "customer_name": src["customer_name"] or src["customer_id"] or "",
            "change_type": change_type,
            "before": before,
            "after": after,
            "delta": delta,
        })
    return {"changes": changes, "totals": totals}


# ---------------------------------------------------------------------------
# The cutoff capture — called by the scheduled job and by the startup catch-up
# ---------------------------------------------------------------------------
async def _captured_months(hub) -> set[tuple[int, int]]:
    rows = await hub.fetch("SELECT year, month FROM dpc_cutoffs")
    return {(r["year"], month_index(r["month"])) for r in rows}


async def capture_month(hub, gold, year: int, month_num: int, now: datetime) -> Optional[int]:
    """Freeze one month's TEAM-DFW orders. Returns the order count, or None if
    another run already captured it (the PK makes a double capture a no-op).

    Fetch-then-write: the gold read completes before the hub transaction opens,
    so no connection idles in a transaction across the network call.
    """
    orders = await fetch_month_orders(gold, year, month_num)
    prev = add_months(year, month_num, -1)
    prev_count = (await fetch_month_totals(gold, prev, prev))[prev].order_count
    if not orders or len(orders) < prev_count * MIN_CAPTURE_RATIO:
        raise RuntimeError(
            f"{month_label(year, month_num)}: {len(orders)} orders vs {prev_count} the month "
            f"before — v4 looks empty or mid-rewrite; refusing to freeze it as the close"
        )
    amounts = [_amounts(o) for o in orders]
    tot = {c: sum((a[c] for a in amounts), Decimal(0)) for c in AMOUNT_COLS}
    month = MONTH_ORDER[month_num - 1]
    async with hub.acquire() as conn:
        async with conn.transaction():
            inserted = await conn.fetchval(
                """
                INSERT INTO dpc_cutoffs
                  (year, month, month_label, cutoff_date, captured_at,
                   revenue, carrier_cost, profit, order_count)
                VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9)
                ON CONFLICT (year, month) DO NOTHING
                RETURNING year
                """,
                year, month, month_label(year, month_num), cutoff_date(year, month_num),
                now, tot["total_charge"], tot["total_carrier_pay"], tot["margin_amt"],
                len(orders),
            )
            if inserted is None:
                return None
            await conn.executemany(
                """
                INSERT INTO dpc_cutoff_orders
                  (year, month, order_id, company_id, customer_id, customer_name,
                   total_charge, total_carrier_pay, margin_amt)
                VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9)
                """,
                [
                    (year, month, o["id"], o["company_id"], o["customer_id"],
                     o["customer_name"], a["total_charge"], a["total_carrier_pay"],
                     a["margin_amt"])
                    for o, a in zip(orders, amounts)
                ],
            )
    return len(orders)


async def capture_due_cutoffs(hub, gold, today: date, now: datetime) -> dict[str, Any]:
    """Capture every closed, tracked month that has no snapshot yet.

    Catch-up by design: a missed night (deploy, cold dyno) is captured on the
    next run, and ``captured_at`` records how late it was.

    ⚠ Each month is isolated, and the run RAISES after the loop when any month
    failed — a per-item ``except: log; continue`` would record a run in which
    every month failed as a success (cron-job-debug §5).
    """
    if hub is None or gold is None:
        raise RuntimeError("Division Payment cutoff: hub or gold pool unavailable")
    due = due_cutoff_months(today, await _captured_months(hub))
    captured: dict[str, int] = {}
    failures: list[str] = []
    for year, month_num in due:
        label = month_label(year, month_num)
        try:
            n = await capture_month(hub, gold, year, month_num, now)
            if n is not None:
                captured[label] = n
                logger.info("Division Payment cutoff captured %s: %d orders", label, n)
        except Exception as e:  # noqa: BLE001 — isolated, re-raised below
            logger.error("Division Payment cutoff FAILED for %s: %s", label, e, exc_info=True)
            failures.append(f"{label}: {e}")
    if failures:
        raise RuntimeError(f"Division Payment cutoff failed for {'; '.join(failures)}")
    return {"due": len(due), "captured": captured}
