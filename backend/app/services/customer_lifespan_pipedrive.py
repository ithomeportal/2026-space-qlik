"""Customer Lifespan — who works a lost account, read from Pipedrive (deck p.12).

Open deals of the REACTIVATION pipeline, matched to a customer on ``ID_McLeod``: the
deal's own field, else its organization's (measured 2026-11-04: they never disagree;
40 of 351 lost customers match). 🛑 READ ONLY: nothing here writes to the CRM. Not
matching on names is deliberate: "PCA Akron" and "PCA ASHLAND" differ by one word,
and a wrong owner is worse than ``PENDING TO ASSIGN``, which someone can fix by
filling ID_McLeod. Hourly, so an owner assigned this morning shows this morning.
"""
from __future__ import annotations

from app.services.customer_lifespan_store import (
    LOG_REFRESH_FAILED_SQL,
    LOG_REFRESH_OK_SQL,
    LOG_REFRESH_START_SQL,
)

MIN_STORED_FOR_EMPTY_GUARD = 20

COUNT_OWNERS_SQL = "SELECT COUNT(*) FROM customer_lifespan_deal_owner"
DELETE_OWNERS_SQL = "DELETE FROM customer_lifespan_deal_owner"
INSERT_OWNER_SQL = """
INSERT INTO customer_lifespan_deal_owner (customer_code, owner_name, deal_id, deal_title)
VALUES ($1, $2, $3, $4)
"""


def _code(value) -> str:
    return str(value or "").strip().upper()


def owner_records(deals: list[dict], org_codes: dict[int, str], users: dict[int, str]) -> list[tuple]:
    """(customer code, owner name, deal id, deal title), newest open deal per code. Pure.

    A deal without a code, or whose owner is not a known user, is left out: that
    customer stays PENDING rather than guessing.
    """
    best: dict[str, tuple] = {}
    for d in deals:
        code = _code(d.get("code")) or _code(org_codes.get(d.get("org_id")))
        owner = users.get(d.get("owner_id"))
        if not code or not owner:
            continue
        rank = (d.get("add_time") or "", d["id"])
        if code not in best or rank > best[code][0]:
            best[code] = (rank, owner, d["id"], d.get("title"))
    return sorted((code, v[1], v[2], v[3]) for code, v in best.items())


async def refresh_deal_owners(hub, client) -> int:
    """Replace the owner map in one transaction. RAISES on failure; the old map stays.

    Fetch-then-write: no hub connection is held across the Pipedrive calls
    (cron-job-debug §6). The run row is written first.
    """
    if hub is None:
        raise RuntimeError("customer lifespan owners: analytics_hub pool missing")
    log_id = await hub.fetchval(LOG_REFRESH_START_SQL, "owners")
    try:
        records = owner_records(*await client.read_reactivation_owners())
        stored = await hub.fetchval(COUNT_OWNERS_SQL) or 0
        if not records and stored >= MIN_STORED_FOR_EMPTY_GUARD:
            raise RuntimeError(f"Pipedrive returned no owners vs {stored} stored — refusing to empty")
        async with hub.acquire() as conn, conn.transaction():
            await conn.execute(DELETE_OWNERS_SQL)
            await conn.executemany(INSERT_OWNER_SQL, records)
        await hub.execute(LOG_REFRESH_OK_SQL, log_id, len(records))
        return len(records)
    except Exception as e:
        await hub.execute(LOG_REFRESH_FAILED_SQL, log_id, f"{type(e).__name__}: {e}"[:500])
        raise
