"""Bonus Calculator — monthly History snapshots (Bruno 2026-05-28).

Each calendar month is frozen at its cutoff: the 6th of the FOLLOWING month at
23:59:59 CST. ``finalize_due_periods`` backfills any closed-and-due period not
yet stored, so it is idempotent and self-healing — it also captures months that
elapsed before this feature shipped. The stored figures never change after the
cutoff even if HR later edits the roster or FX (immutable history).

The History tab reads the snapshots plus the still-open current month computed
live (flagged "in progress").
"""

from __future__ import annotations

import logging
from datetime import datetime
from zoneinfo import ZoneInfo

from app.routers import bonus_calculator as bc

logger = logging.getLogger(__name__)

CST = ZoneInfo("America/Chicago")


def _cutoff_for(period_key: str) -> datetime:
    """The data cutoff for ``period_key`` (YYYY-MM): 6th of the next month 23:59:59 CST."""
    y, m = (int(x) for x in period_key.split("-"))
    ny, nm = (y + 1, 1) if m == 12 else (y, m + 1)
    return datetime(ny, nm, 6, 23, 59, 59, tzinfo=CST)


def _snapshot_rows(period_key: str, report: dict) -> list[tuple]:
    rows: list[tuple] = []
    for team in report.get("teams", []):
        profit = float(team.get("monthlyProfit", 0) or 0)
        bonus = float(team.get("teamBonusUsd", 0) or 0)
        pct = (bonus / profit * 100) if profit else None
        rows.append((period_key, team["id"], team["name"], profit, bonus, pct))
    return rows


async def finalize_due_periods(app, scope=None) -> dict:
    """Snapshot every closed-and-due period not yet in this scope's history.

    ⚠ ``scope`` selects BOTH the tables and the bracket ladders. It defaults to
    corporate, but the caller must pass DFW explicitly for the DFW calculator:
    the two share the `(period_key, team_id)` shape, so a single shared table
    would let one scope's snapshot make the scheduler skip the other's for that
    month entirely (the `already` short-circuit below).
    """
    scope = scope or bc.CORP_SCOPE
    gold = getattr(app.state, "savings_pool", None)
    primary = getattr(app.state, "pool", None)
    financial = getattr(app.state, "financial_pool", None)
    if gold is None or primary is None:
        return {"finalized": 0, "skipped": "pools unavailable"}

    now = datetime.now(CST)
    finalized = 0
    for period_key in bc._recent_period_keys(12):
        if _cutoff_for(period_key) > now:
            continue  # month still finalizing — leave it to the live "open" row
        already = await primary.fetchval(
            f"SELECT 1 FROM {scope.tbl_history} WHERE period_key = $1 LIMIT 1", period_key
        )
        if already:
            continue
        try:
            report = await bc.build_bonus_report_data(
                gold, primary, financial, period_key, scope
            )
        except Exception as exc:  # noqa: BLE001 — one bad period must not block others
            logger.warning("History finalize for %s failed: %s", period_key, exc)
            continue
        rows = _snapshot_rows(period_key, report)
        await primary.executemany(
            f"""
            INSERT INTO {scope.tbl_history}
              (period_key, team_id, team_name, profit_usd, total_bonus_usd, pct_bonus)
            VALUES ($1, $2, $3, $4, $5, $6)
            ON CONFLICT (period_key, team_id) DO NOTHING
            """,
            rows,
        )
        finalized += 1
        logger.info(
            "Finalized %s bonus history for %s (%d teams)", scope.key, period_key, len(rows)
        )
    return {"finalized": finalized, "scope": scope.key}


async def get_history(pool, scope=None) -> list[dict]:
    """All persisted snapshots for one scope, newest period first."""
    scope = scope or bc.CORP_SCOPE
    rows = await pool.fetch(
        f"""
        SELECT period_key, team_id, team_name, profit_usd, total_bonus_usd,
               pct_bonus, finalized_at
        FROM {scope.tbl_history}
        ORDER BY period_key DESC, team_id
        """
    )
    return [
        {
            "periodKey": r["period_key"],
            "teamId": r["team_id"],
            "teamName": r["team_name"],
            "profitUsd": float(r["profit_usd"] or 0),
            "totalBonusUsd": float(r["total_bonus_usd"] or 0),
            "pctBonus": float(r["pct_bonus"]) if r["pct_bonus"] is not None else None,
            "finalizedAt": r["finalized_at"].isoformat() if r["finalized_at"] else None,
        }
        for r in rows
    ]
