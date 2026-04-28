"""Code-made report: Podium Set DFW.

Portal-native replacement for the DFW leadership Qlik app
`0a0c7a49-3857-4bf4-af9e-ec8b3c9d7d87` ("Rate Conf Received" podium).
Same data contract as the n8n workflow ``nT6uAuy9qfkPr0lZ`` (DFW Loads to
Cover Daily Report) — see ``/BOT/n8n-mcp/docs/SPEC-dfw-loads-to-cover.md``.

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

from typing import Optional

from fastapi import APIRouter, Depends, Query, Request

from app.datalake import pad_variants as _pad_variants
from app.routers.deps import get_datalake_gold_pool, require_tag_role

# --------------------------------------------------------------------------
# Access control: admin bypasses automatically (require_tag_role handles it).
# --------------------------------------------------------------------------
PODIUM_ROLES = ("DFW",)

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
        br.company_id               AS company_id,
        br.margin_amt::float        AS profit,
        br.total_charge::float      AS revenue
    FROM (
        SELECT id, posted_date, posted_by_name,
               ROW_NUMBER() OVER (PARTITION BY id ORDER BY posted_date DESC) AS rn
        FROM public.mcleod_gld_order_post_hist
        WHERE TRIM(posted_type) = 'C'
          AND TRIM(comments)    = 'Rate Conf Received'
          AND posted_date >= date_trunc('month', CURRENT_DATE) - INTERVAL '7 days'
    ) rp
    LEFT JOIN public.mcleod_gld_budget_report_v4 br
           ON TRIM(rp.id) = TRIM(br.id)
    WHERE rp.rn = 1
      AND br.team_id = ANY($1::text[])
)
"""


# Map the UI range values to a SQL boolean that filters ``rate_conf.posted_date``.
# Pool sessions are pinned to America/Chicago, so CURRENT_DATE is CST.
_RANGE_FILTERS = {
    "today": "posted_date::date = CURRENT_DATE",
    "wtd":   "posted_date::date >= date_trunc('week', CURRENT_DATE)::date",
    "mtd":   "posted_date::date >= date_trunc('month', CURRENT_DATE)::date",
}


router = APIRouter(tags=["podium-dfw"], prefix="/custom/podium-dfw")


# --------------------------------------------------------------------------
# /overview  -- one round-trip: KPIs + table rows for the selected range.
# --------------------------------------------------------------------------
@router.get("/overview")
async def overview(
    request: Request,
    range: str = Query("today", pattern="^(today|wtd|mtd)$"),
    _user: dict = Depends(require_tag_role(*PODIUM_ROLES)),
):
    """KPIs + row-level table for the Podium Set DFW report.

    Response shape:
      ``{ success, data: { range, kpis: {...}, rows: [...] } }``
    """
    pool = get_datalake_gold_pool(request)
    where = _RANGE_FILTERS[range]

    # v4.team_id is varchar(8); 'TEAM-DFW' fits without padding.
    params = [_pad_variants(list(PODIUM_TEAMS), width=8)]

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
        customer, origin, destination,
        profit, revenue,
        CASE WHEN COALESCE(revenue, 0) > 0
             THEN profit / NULLIF(revenue, 0)
             ELSE NULL END                                    AS margin_pct,
        contract_type, company_id
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
            "profit":        r["profit"],
            "revenue":       r["revenue"],
            "margin_pct":    r["margin_pct"],
            "contract_type": r["contract_type"],
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
