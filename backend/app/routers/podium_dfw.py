"""Code-made report: Podium Set DFW.

Portal-native replacement for the DFW leadership Qlik app
`0a0c7a49-3857-4bf4-af9e-ec8b3c9d7d87` ("Rate Conf Received" podium).
Same data contract as the n8n workflow ``nT6uAuy9qfkPr0lZ`` (DFW Loads to
Cover Daily Report) — see ``/BOT/n8n-mcp/docs/SPEC-dfw-loads-to-cover.md``.

The five top-3 leaderboards Bruno added in round 1 were split out into a
separate ``DFW Podium Top`` report (``routers/podium_top.py``) per round-2
feedback (BRUNO -- DFW Podiums.pdf, 2026-05-05) so the leaderboards never see
a date filter.

Data source: ``aivn_datalake_gold`` (shared pool via ``get_datalake_gold_pool``
-- no new env var).

Source tables:
  * ``public.mcleod_gld_order_post_hist``  filtered posted_type='C' and
    comments='Rate Conf Received', keep latest posting per order.
  * ``public.mcleod_gld_budget_report_v4`` left-joined on ``id`` for
    margin_amt, total_charge, customer_name, origin_name, dest_name,
    contract_type_descr, team_id.

Scope: ``team_id = ANY(pad_variants('TEAM-DFW'))`` -- sargable, never TRIM()
in the predicate (CLAUDE.md "Sargability rule").

Timezone: the datalake stores everything already in America/Chicago, and the
asyncpg pool pins every session to ``SET TIME ZONE 'America/Chicago'``
(`main._set_cst_session`), so plain ``CURRENT_DATE`` / ``date_trunc('week' |
'month', CURRENT_DATE)`` already resolve to CST — no per-query
``AT TIME ZONE`` conversion is needed.

Perf notes:
  * The base CTE is marked ``MATERIALIZED`` so the ROW_NUMBER() partition runs
    exactly once even though the overview endpoint computes KPIs AND rows.
  * ``posted_date >= month_start - INTERVAL '7 days'`` narrows the scan to a
    few days of order_post_hist — matches the n8n single-node design
    (~2 s total).
  * v4 LEFT JOIN on TRIM-less ``id`` (order ids are stored unpadded on both
    tables, so no pad_variants needed there).

v4 sparseness: v4 lags in-progress loads for the current month, so some of
today's rows may come back with ``profit=NULL`` / ``revenue=NULL``. We pass
them through (frontend renders an em-dash) -- matches the Qlik app behavior.
"""

from fastapi import APIRouter, Depends, HTTPException, Query, Request

from app.datalake import pad_variants as _pad_variants
from app.routers.deps import get_datalake_gold_pool, require_report_access

# --------------------------------------------------------------------------
# Scope
# --------------------------------------------------------------------------
PODIUM_TEAMS = ("TEAM-DFW",)


# --------------------------------------------------------------------------
# SQL fragment -- the Qlik-aligned base CTE (lifted from SPEC-dfw-loads-to-cover
# and made sargable). ``$1`` must be bound to _pad_variants(PODIUM_TEAMS).
# --------------------------------------------------------------------------
_RATE_CONF_CTE = """
rate_conf AS MATERIALIZED (
    SELECT
        TRIM(rp.id)                 AS order_id,
        rp.posted_date              AS posted_date,
        TRIM(rp.posted_by_name)     AS posted_by,
        br.team                     AS team,
        br.origin_name              AS origin,
        br.dest_name                AS destination,
        br.customer_name            AS customer,
        br.contract_type_descr      AS contract_type,
        -- descr when present ('Van', 'Flatbed'), else the trimmed code
        -- ('F48', 'FT') -- both columns are blank-padded / sometimes empty.
        -- SELECT-side TRIM only; never in WHERE/JOIN (sargability rule).
        COALESCE(
            NULLIF(TRIM(br.equipment_type_descr), ''),
            NULLIF(TRIM(br.equipment_type_id), '')
        )                           AS equipment_type,
        br.company_id               AS company_id,
        br.margin_amt::float        AS profit,
        br.total_charge::float      AS revenue,
        -- Carrier (first movement's payee_name). Canonical LEFT JOIN LATERAL
        -- first-match pattern (SPEC-CODE-RULES §5) also used by ops-portal /
        -- ceo-executive By-Order rows.
        NULLIF(TRIM(mov.payee_name), '') AS carrier
    FROM (
        SELECT id, posted_date, posted_by_name,
               ROW_NUMBER() OVER (PARTITION BY id ORDER BY posted_date DESC) AS rn
        FROM public.mcleod_gld_order_post_hist
        WHERE TRIM(posted_type) = 'C'
          AND TRIM(comments)    = 'Rate Conf Received'
          -- Scan floor: default month_start-7d for the presets, but drop lower
          -- when a custom start ($2) reaches further back. LEAST() ignores a
          -- NULL $2, so the presets keep their original tight window.
          AND posted_date >= LEAST(
              date_trunc('month', CURRENT_DATE) - INTERVAL '7 days',
              $2::timestamp
          )
    ) rp
    LEFT JOIN public.mcleod_gld_budget_report_v4 br
           ON TRIM(rp.id) = TRIM(br.id)
    LEFT JOIN LATERAL (
        SELECT m.payee_name
        FROM public.mcleod_gld_movement m
        WHERE m.order_id = br.id AND m.company_id = br.company_id
        ORDER BY m.movement_id ASC
        LIMIT 1
    ) mov ON TRUE
    WHERE rp.rn = 1
      AND br.team_id = ANY($1::text[])
      -- Exclude VOID (status 'V') loads for all users (Bruno 2026-07-07).
      -- status is an unpadded 1-char code (D/V/A/P) so no pad_variants /
      -- TRIM needed; the team_id predicate above already makes the v4 join
      -- effectively inner, so br.status is never NULL here.
      AND br.status <> 'V'
)
"""


# Map the UI range values to a SQL boolean that filters ``rate_conf.posted_date``.
# Pool sessions are pinned to America/Chicago, so CURRENT_DATE is CST.
_RANGE_FILTERS = {
    "today": "posted_date::date = CURRENT_DATE",
    "wtd":   "posted_date::date >= date_trunc('week', CURRENT_DATE)::date",
    "mtd":   "posted_date::date >= date_trunc('month', CURRENT_DATE)::date",
}

# Custom range: half-inclusive-both-ends on posted_date. ``$2`` = start at
# 00:00:00 (also the CTE scan floor), ``$3`` = end at 23:59:59.999999.
_CUSTOM_FILTER = "posted_date >= $2::timestamp AND posted_date <= $3::timestamp"

# YYYY-MM-DD (bare date only — the UI sends <input type="date"> values).
import re as _re  # noqa: E402
from datetime import datetime  # noqa: E402

_DATE_RE = _re.compile(r"^\d{4}-\d{2}-\d{2}$")


router = APIRouter(tags=["podium-dfw"], prefix="/custom/podium-dfw")


# --------------------------------------------------------------------------
# /overview  -- one round-trip: KPIs + table rows for the selected range.
# --------------------------------------------------------------------------
@router.get("/overview")
async def overview(
    request: Request,
    range: str = Query("today", pattern="^(today|wtd|mtd|custom)$"),
    start: str | None = Query(None, description="Custom range start date YYYY-MM-DD (inclusive, 00:00)"),
    end: str | None = Query(None, description="Custom range end date YYYY-MM-DD (inclusive, 23:59)"),
    _user: dict = Depends(require_report_access("podium-dfw")),
):
    """KPIs + row-level table for the Podium Set DFW report.

    Response shape:
      ``{ success, data: { range, kpis: {...}, rows: [...] } }``

    ``range=custom`` filters ``posted_date`` between ``start`` 00:00:00 and
    ``end`` 23:59:59.999999 (both inclusive). The presets pass ``$2=NULL`` so
    the CTE keeps its default month_start-7d scan floor.
    """
    pool = get_datalake_gold_pool(request)

    # v4.team_id is varchar(8); 'TEAM-DFW' fits without padding.
    params = [_pad_variants(list(PODIUM_TEAMS), width=8)]

    if range == "custom":
        if not (start and end and _DATE_RE.match(start) and _DATE_RE.match(end)):
            raise HTTPException(
                status_code=400,
                detail="range=custom requires start and end dates as YYYY-MM-DD.",
            )
        # The SQL binds $2/$3 to ::timestamp params; asyncpg requires real
        # datetime objects (a raw str raises DataError -> 500). The regex above
        # only checks shape, so parse here to reject impossible dates (e.g.
        # 2026-13-40) with a 400 instead of a second 500 class.
        try:
            start_dt = datetime.strptime(start, "%Y-%m-%d")  # 00:00:00
            end_dt = datetime.strptime(end, "%Y-%m-%d")
        except ValueError:
            raise HTTPException(
                status_code=400,
                detail="range=custom requires valid calendar dates as YYYY-MM-DD.",
            )
        # Be forgiving if the user inverts the two fields.
        if start_dt > end_dt:
            start_dt, end_dt = end_dt, start_dt
        where = _CUSTOM_FILTER
        params.append(start_dt)                                     # $2 -> CTE floor + lower bound (00:00:00)
        params.append(end_dt.replace(hour=23, minute=59,
                                     second=59, microsecond=999999))  # $3 -> upper bound (inclusive end-of-day)
    else:
        where = _RANGE_FILTERS[range]
        params.append(None)                             # $2 -> NULL, presets keep default floor

    kpi_sql = f"""
    WITH {_RATE_CONF_CTE}
    SELECT
        COUNT(*)                                              AS loads,
        COALESCE(SUM(profit), 0)::float                       AS profit,
        COALESCE(SUM(revenue), 0)::float                      AS revenue,
        CASE WHEN COALESCE(SUM(revenue), 0) > 0
             THEN SUM(profit)::float / SUM(revenue)::float
             ELSE NULL END                                    AS margin_pct
    FROM rate_conf
    WHERE {where}
    """

    rows_sql = f"""
    WITH {_RATE_CONF_CTE}
    SELECT
        team, order_id, posted_by, posted_date,
        customer, origin, destination, carrier,
        profit, revenue,
        CASE WHEN COALESCE(revenue, 0) > 0
             THEN profit / NULLIF(revenue, 0)
             ELSE NULL END                                    AS margin_pct,
        contract_type, equipment_type, company_id
    FROM rate_conf
    WHERE {where}
    ORDER BY posted_date DESC NULLS LAST,
             profit DESC     NULLS LAST,
             revenue DESC    NULLS LAST
    """

    kpi_row = await pool.fetchrow(kpi_sql, *params)
    rows_out = await pool.fetch(rows_sql, *params)

    kpis = dict(kpi_row) if kpi_row else {
        "loads": 0, "profit": 0.0, "revenue": 0.0, "margin_pct": None,
    }

    rows = [
        {
            "team":          r["team"],
            "order_id":      r["order_id"],
            "posted_by":     r["posted_by"],
            "posted_date":   r["posted_date"].isoformat() if r["posted_date"] else None,
            "customer":      r["customer"],
            "origin":        r["origin"],
            "destination":   r["destination"],
            "carrier":       r["carrier"],
            "profit":        r["profit"],
            "revenue":       r["revenue"],
            "margin_pct":    r["margin_pct"],
            "contract_type": r["contract_type"],
            "equipment_type": r["equipment_type"],
            "company_id":    r["company_id"],
        }
        for r in rows_out
    ]

    return {
        "success": True,
        "data": {
            "range": range,
            "kpis": kpis,
            "rows": rows,
        },
    }
