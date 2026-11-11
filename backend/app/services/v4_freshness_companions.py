"""Which OTHER McLeod gold tables stopped with v4 / movement? (§143)

2026-11-11 15:40 the STOPPED mail named v4 + movement only, while every McLeod
gold table our reports read had stopped between 12:16 and 13:24 CST — the whole
load, not two tables. This sweep runs ONLY when a STOPPED mail is about to go
out (once per freeze): none of these tables index ``updated_dt``, so it is
~1 GB of sequential reads, capped at ``COMPANION_TIMEOUT_S``. It is evidence for
the reader, never the trigger — the trigger stays v4/movement + live stop events.

Classification, anchored on the newest last-write of the stale watched tables:
* stopped together — not written for ``fresh_s`` and last written no earlier
  than ``LOOKBACK`` before the anchor (it went quiet around the same time);
* still written    — written within ``fresh_s`` (a PARTIAL stop: say so);
* omitted          — quiet long before the freeze (a slow dimension table) or
  never written; it says nothing about this freeze.

Tables without an ``updated_dt`` (``order_post_hist``, ``edi_load_tender``)
cannot be measured and are not listed. Never raises — the caller sends the
alert either way.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

logger = logging.getLogger("uvicorn.error")

COMPANION_TIMEOUT_S = 20.0
LOOKBACK = timedelta(hours=3)


@dataclass(frozen=True)
class Companion:
    table: str
    col: str
    read_by: str


# Readers verified by grep of app/ on 2026-11-11 — keep in step when a report
# starts reading another gold table.
# customer_windows + orders_pu_del_windows moved to the monitor's WATCHED (v6,
# 11-11): they stayed frozen after v4 resumed, so they are alarms, not evidence.
COMPANIONS: tuple[Companion, ...] = (
    Companion("mcleod_gld_customer_view", "c_customer_view",
              "XRay DFW, HD Spot, PCA status mails"),
    Companion("mcleod_gld_dispatchers", "c_dispatchers",
              "Ops portals, KAM DFW, Carrier Risk"),
    Companion("mcleod_gld_cashflow", "c_cashflow", "Admin Aging Cashflow"),
    Companion("mcleod_gld_cash_flow_dinfo", "c_cash_flow_dinfo",
              "MX revenue code → DFW division split"),
    Companion("mcleod_gld_incidents_v3", "c_incidents_v3", "OPs Customer Score"),
)

COMPANION_SQL = "SELECT " + ", ".join(
    f"(SELECT max(updated_dt) FROM public.{comp.table}) AS {comp.col}" for comp in COMPANIONS
)


@dataclass(frozen=True)
class CompanionLag:
    table: str
    read_by: str
    last: datetime
    age_s: int


@dataclass(frozen=True)
class Sweep:
    stopped: list[CompanionLag]
    still_written: list[CompanionLag]
    failed: bool = False


FAILED = Sweep(stopped=[], still_written=[], failed=True)


def classify(row: Any, *, anchor: datetime, now: datetime, fresh_s: int) -> Sweep:
    """Split companions into stopped-with-the-load vs still written (pure)."""
    stopped: list[CompanionLag] = []
    written: list[CompanionLag] = []
    for comp in COMPANIONS:
        last = row[comp.col]
        if last is None:
            continue
        lag = CompanionLag(comp.table, comp.read_by, last, int((now - last).total_seconds()))
        if lag.age_s <= fresh_s:
            written.append(lag)
        elif last >= anchor - LOOKBACK:
            stopped.append(lag)
    return Sweep(stopped=sorted(stopped, key=lambda x: x.last), still_written=written)


async def sweep(pool, *, anchor: datetime | None, now: datetime, fresh_s: int) -> Sweep:
    """Read the companions' last writes once; FAILED on any error or timeout."""
    if anchor is None:
        return Sweep(stopped=[], still_written=[])
    try:
        row = await pool.fetchrow(COMPANION_SQL, timeout=COMPANION_TIMEOUT_S)
    except Exception:
        logger.exception("check_v4_freshness: companion sweep failed")
        return FAILED
    if row is None:
        return FAILED
    return classify(row, anchor=anchor, now=now, fresh_s=fresh_s)


def subject_suffix(result: Sweep) -> str:
    n = len(result.stopped)
    return f" (+ {n} more gold tables)" if n else ""


def section_html(result: Sweep, fmt, age_text) -> str:
    """The companion block of the STOPPED mail (``fmt``/``age_text`` from the monitor)."""
    note = "margin:8px 0 0;color:#555;font-size:13px;"
    if result.failed:
        return (f"<p style='{note}'>Other McLeod gold tables could not be checked "
                "(query failed or timed out) — assume the whole load is affected.</p>")
    parts = []
    if result.stopped:
        cell = "padding:4px 12px 4px 0;"
        head = "".join(f"<th style='{cell}text-align:left;color:#555;font-weight:500;'>{h}</th>"
                       for h in ("table", "last write (CST)", "silent for", "read by"))
        body = "".join(
            f"<tr><td style='{cell}'>{x.table}</td><td style='{cell}'>{fmt(x.last)}</td>"
            f"<td style='{cell}font-weight:600;'>{age_text(x.age_s)}</td>"
            f"<td style='{cell}font-family:-apple-system,Segoe UI,Roboto,sans-serif;'>{x.read_by}</td></tr>"
            for x in result.stopped
        )
        parts.append(
            "<p style='margin:16px 0 4px;'><b>Other McLeod gold tables stopped around the same "
            "time</b> — the reports beside them are frozen too:</p>"
            "<table style=\"border-collapse:collapse;font-family:ui-monospace,SFMono-Regular,"
            f"Menlo,Consolas,monospace;font-size:13px;\"><tr>{head}</tr>{body}</table>"
        )
    if result.still_written:
        names = ", ".join(f"{x.table} ({fmt(x.last)})" for x in result.still_written)
        parts.append(f"<p style='{note}'>Still being written (a partial stop): {names}.</p>")
    return "".join(parts)
