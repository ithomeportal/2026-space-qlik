"""Live McLeod order status — the guard that keeps Cover honest (§143).

Why this exists
---------------
The Cover / Pending-to-Cover boards and the Cover forecast decide "still open"
from ``mcleod_gld_budget_report_v4.status = 'A'``. On 2026-11-01 (DST
fall-back) the gold McLeod ETL stopped picking up a large share of order/stop
changes: its stamps run +1 h against McLeod's and v4 kept ``status='A'`` on
loads McLeod had already moved to ``P`` (picked up) — 55 of the 85 pickups of
11-02 (Jaime Anaya, 0351520 / 0351578). Nothing errors and ``max(updated_dt)``
stays fresh, so the board just keeps showing loads as "covered".

``app_augment_n8n_data_ra_rt`` (same gold DB, fed by the n8n McLeod webhook that
Augie uses — already read in production by ``augie_funnel`` and the PCA mails)
carries McLeod's own ``order_status`` minutes after the change. An order that
v4 calls ``A`` but McLeod already calls ``P`` / ``D`` / ``V`` is not open: it
leaves the Cover boards. Production stays on v4 (Diego, 2026-11-02) — the
boards only stop claiming such a load is still waiting.

Rules
-----
* We trust the live ``order_status`` ONLY — never "has a pickup arrival": live
  ``A`` + arrival exists in McLeod itself (66 rows), and v4 would show those as
  ``A`` after a correct sync too. Once the gold ETL re-syncs, v4 and the live
  feed agree and this guard removes nothing.
* The live table holds US (``TMS``) orders only; MX (``TMS3``) is unaffected.
* Keys are stored TRIMMED there while v4 pads them — the predicate TRIMs v4.
* The lookup starts from v4's status-'A' orders and probes the live PK — never
  a scan of the live table (4-8 s; it is upsert-bloated).
* FAIL SOFT: the live set is a separate SELECT; any error returns ``None`` and
  the boards render exactly as before (meta ``live_status = 'unavailable'``).
* The predicate is an uncorrelated ``= ANY($n)`` over a parameter, never a
  correlated per-row lookup (§135 — that made a scan serial, 11× slower).
"""

from __future__ import annotations

import logging

from app.datalake import pad_variants

from ._constants import CORP_COMPANIES

logger = logging.getLogger("uvicorn.error")

LIVE_TABLE = "public.app_augment_n8n_data_ra_rt"

# McLeod order statuses that mean "no longer open / waiting for pickup".
MOVED_STATUSES: tuple[str, ...] = ("P", "D", "V")

# Driven FROM the few hundred v4 status-'A' keys into the live table's PK
# (company_id, id, movement_id): ~0.2 s. A plain scan of the live table took
# 4-8 s on 2026-11-02 — n8n upserts it constantly (16% dead tuples) — and would
# run on every Cover request.
LIVE_MOVED_SQL = f"""
    SELECT l.k
    FROM (
        -- The LATEST live row per order (the PK carries movement_id): an older
        -- movement row left at P/D/V must not hide an order McLeod has open.
        SELECT DISTINCT ON (r.company_id, r.id)
               TRIM(r.company_id) || '|' || TRIM(r.id) AS k,
               TRIM(r.order_status) AS order_status
        FROM (
            SELECT DISTINCT TRIM(v.company_id) AS co, TRIM(v.id) AS id
            FROM public.mcleod_gld_budget_report_v4 v
            WHERE v.company_id = ANY($1) AND v.status = ANY($2)
        ) a
        JOIN {LIVE_TABLE} r ON r.company_id = a.co AND r.id = a.id
        WHERE NOT COALESCE(r.is_deleted, false)
        ORDER BY r.company_id, r.id, r.updated_dt DESC NULLS LAST, r.movement_id DESC
    ) l
    WHERE l.order_status = ANY($3)
"""


def live_key_expr(alias: str) -> str:
    """The v4 row's live-table key — ``'TMS|0351520'`` (v4 pads both parts)."""
    return f"(TRIM({alias}.company_id) || '|' || TRIM({alias}.id))"


def live_moved_pred(alias: str, placeholder: str) -> str:
    """TRUE when McLeod already moved the order past ``A`` per the live feed."""
    return f"{live_key_expr(alias)} = ANY({placeholder})"


async def fetch_live_moved_keys(pool) -> list[str] | None:
    """Keys of orders McLeod reports as P/D/V; ``None`` when the feed is unreachable."""
    try:
        rows = await pool.fetch(
            LIVE_MOVED_SQL,
            pad_variants(CORP_COMPANIES, width=4),
            pad_variants(("A",), width=1),
            list(MOVED_STATUSES),
        )
    except Exception:
        logger.exception("ops-portal live status: %s unreadable — Cover boards unguarded", LIVE_TABLE)
        return None
    return [r["k"] for r in rows]


def live_status_label(keys: list[str] | None) -> str:
    return "unavailable" if keys is None else "ok"
