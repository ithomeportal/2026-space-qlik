"""The gold-freshness watchdog's alert memory, kept in the hub DB (§143 v6).

2026-11-11: the memory lived in the process only. The 16:05 deploy wiped it in
the middle of a freeze, ingestion resumed ~16:00, and the 16:40 run — healthy,
remembering nothing — never sent the "resumed" mail the 15:50 alert promised.
Every deploy inside a freeze also repeated the STOPPED mail. One row in
``gold_freshness_alert_state`` survives deploys.

Fail soft both ways: a failed load falls back to the in-process copy (the old
behaviour), a failed save is logged and the in-process copy still holds — the
monitor's ``HubSync.dirty`` stops the next run loading the older hub row over it
until a save succeeds. The watchdog never stops alerting because the hub is unwell.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import Any, Protocol

logger = logging.getLogger("uvicorn.error")

STATE_KEY = "v4_freshness"
STATE_TIMEOUT_S = 10.0

STATE_DDL = """
CREATE TABLE IF NOT EXISTS gold_freshness_alert_state (
  watch_key   TEXT         PRIMARY KEY,
  stamps      JSONB        NOT NULL,
  sent_at     TIMESTAMP,
  updated_at  TIMESTAMPTZ  NOT NULL DEFAULT NOW()
)
"""

_LOAD_SQL = "SELECT stamps, sent_at FROM gold_freshness_alert_state WHERE watch_key = $1"
_SAVE_SQL = """
INSERT INTO gold_freshness_alert_state (watch_key, stamps, sent_at, updated_at)
VALUES ($1, $2::jsonb, $3, NOW())
ON CONFLICT (watch_key) DO UPDATE
   SET stamps = EXCLUDED.stamps, sent_at = EXCLUDED.sent_at, updated_at = NOW()
"""


class Memory(Protocol):
    stamps: dict[str, datetime | None]
    sent_at: datetime | None


def encode_stamps(stamps: dict[str, datetime | None]) -> str:
    """{name: naive-CST ISO | None} — None = the table was never written."""
    return json.dumps({k: None if v is None else v.isoformat() for k, v in stamps.items()},
                      sort_keys=True)


def decode_stamps(raw: Any) -> dict[str, datetime | None]:
    data = json.loads(raw) if isinstance(raw, str) else dict(raw or {})
    return {str(k): None if v is None else datetime.fromisoformat(v) for k, v in data.items()}


async def load(hub_pool) -> tuple[dict[str, datetime | None], datetime | None] | None:
    """(stamps, sent_at) from the hub; ({}, None) when no row; None on failure."""
    if hub_pool is None:
        return None
    try:
        row = await hub_pool.fetchrow(_LOAD_SQL, STATE_KEY, timeout=STATE_TIMEOUT_S)
    except Exception:
        logger.exception("check_v4_freshness: alert state load failed (in-process memory)")
        return None
    if row is None:
        return {}, None
    try:
        return decode_stamps(row["stamps"]), row["sent_at"]
    except (TypeError, ValueError):
        logger.exception("check_v4_freshness: alert state unreadable (in-process memory)")
        return None


async def save(hub_pool, memory: Memory) -> bool:
    """Persist the memory; False (logged) on failure — never raises."""
    if hub_pool is None:
        return False
    try:
        await hub_pool.execute(_SAVE_SQL, STATE_KEY, encode_stamps(memory.stamps),
                               memory.sent_at, timeout=STATE_TIMEOUT_S)
    except Exception:
        logger.exception("check_v4_freshness: alert state save failed")
        return False
    return True
