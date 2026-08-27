"""Ad-hoc read-only probe against aivn_datalake_gold.

Uses the application's own ``Settings`` loader for the connection, so no
credential is ever passed on the command line or echoed. Reads statements from
stdin, separated by a line containing only ``;;``.

    cd backend && python -m tools.gold_probe <<'SQL'
    SELECT 1
    SQL
"""

from __future__ import annotations

import asyncio
import datetime
import decimal
import json
import re
import sys

import asyncpg

from app.config import settings

MAX_ROWS = 300


def _dsn() -> str:
    url = settings.SAVINGS_DATABASE_URL
    if not url:
        raise SystemExit("SAVINGS_DATABASE_URL is not configured")
    # sslmode in the URL overrides the ssl= object and fails Aiven's chain.
    return re.sub(r"[?&]sslmode=[a-zA-Z-]+", "", url)


def _enc(o):
    if isinstance(o, decimal.Decimal):
        return float(o)
    if isinstance(o, (datetime.date, datetime.datetime)):
        return o.isoformat()
    return str(o)


async def main() -> None:
    conn = await asyncpg.connect(_dsn(), ssl="require", timeout=60)
    try:
        for stmt in (s for s in sys.stdin.read().split("\n;;\n") if s.strip()):
            print("### " + " ".join(stmt.split())[:150])
            try:
                rows = await conn.fetch(stmt)
            except Exception as exc:  # noqa: BLE001 — diagnostic tool
                print(f"!! {type(exc).__name__}: {exc}\n")
                continue
            for r in rows[:MAX_ROWS]:
                print(json.dumps(dict(r), default=_enc))
            extra = "" if len(rows) <= MAX_ROWS else f" (showing {MAX_ROWS})"
            print(f"-- {len(rows)} row(s){extra}\n")
    finally:
        await conn.close()


if __name__ == "__main__":
    asyncio.run(main())
