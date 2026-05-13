"""Code-made report: DFW Podium Top.

Companion to ``Podium Set DFW`` (``routers/podium_dfw.py``). This report shows
ONLY the five top-3 leaderboards Bruno asked for in
``BRUNO -- DFW Podiums.pdf`` (round 2, 2026-05-05) — there is no date filter
and no booking detail table on this report:

  This Week (Mon-Sun, current week):
    - Top 3 Bookers by Profit  (Posted by, Profit, Loads)
    - Top 3 Bookers by Margin% (Posted by, Margin% = SumProfit/SumRevenue, Loads)
    - Top 3 Bookers by Loads   (Posted by, Loads)
  Today:
    - Top 3 Bookers by Loads   (Posted by, Loads)
    - Top 3 Bookers by Profit  (Posted by, Profit)

Same data contract as ``podium_dfw.py``: the rate-conf base CTE is identical
(``mcleod_gld_order_post_hist`` filtered ``posted_type='C'`` /
``comments='Rate Conf Received'`` joined to ``mcleod_gld_budget_report_v4``
on ``id``), scope ``team_id = ANY(_pad_variants('TEAM-DFW'))``.

date_trunc('week', CURRENT_DATE) is ISO Monday in Postgres → Mon-Sun is the
half-open ``[week_start, week_start + 7)`` window; the asyncpg pool pins
each session to ``America/Chicago`` (`main._set_cst_session`) so plain
``CURRENT_DATE`` is already CST.
"""

import json

from fastapi import APIRouter, Depends, Request

from app.datalake import pad_variants as _pad_variants
from app.routers.deps import get_datalake_gold_pool, require_report_access


PODIUM_TOP_TEAMS = ("TEAM-DFW",)


_RATE_CONF_CTE = """
rate_conf AS MATERIALIZED (
    SELECT
        TRIM(rp.id)                 AS order_id,
        rp.posted_date              AS posted_date,
        TRIM(rp.posted_by_name)     AS posted_by,
        br.team                     AS team,
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


router = APIRouter(tags=["dfw-podium-top"], prefix="/custom/dfw-podium-top")


@router.get("/podiums")
async def podiums(
    request: Request,
    _user: dict = Depends(require_report_access("dfw-podium-top")),
):
    pool = get_datalake_gold_pool(request)
    params = [_pad_variants(list(PODIUM_TOP_TEAMS), width=8)]

    sql = f"""
    WITH {_RATE_CONF_CTE},
    weekly AS (
        SELECT posted_by,
               COUNT(*)::int                            AS loads,
               COALESCE(SUM(profit), 0)::float          AS profit,
               COALESCE(SUM(revenue), 0)::float         AS revenue,
               CASE WHEN COALESCE(SUM(revenue), 0) > 0
                    THEN SUM(profit)::float / SUM(revenue)::float
                    ELSE NULL END                       AS margin_pct
        FROM rate_conf
        WHERE posted_date::date >= date_trunc('week', CURRENT_DATE)::date
          AND posted_date::date <  date_trunc('week', CURRENT_DATE)::date + 7
          AND posted_by IS NOT NULL AND posted_by <> ''
        GROUP BY posted_by
    ),
    -- Bruno R4 (2026-05-12): Today cards now expose BOTH loads + profit so
    -- each leaderboard row shows both numbers regardless of which metric was
    -- the primary sort.
    daily AS (
        SELECT posted_by,
               COUNT(*)::int                            AS loads,
               COALESCE(SUM(profit), 0)::float          AS profit
        FROM rate_conf
        WHERE posted_date::date = CURRENT_DATE
          AND posted_by IS NOT NULL AND posted_by <> ''
        GROUP BY posted_by
    ),
    -- Bruno R4 (2026-05-12): same daily aggregation broken out by team
    -- (TM1..TM4 within TEAM-DFW). Powers the per-team duplicate of the
    -- Today cards stacked below the overall ones.
    daily_by_team AS (
        SELECT TRIM(COALESCE(team, '')) AS team,
               posted_by,
               COUNT(*)::int                            AS loads,
               COALESCE(SUM(profit), 0)::float          AS profit
        FROM rate_conf
        WHERE posted_date::date = CURRENT_DATE
          AND posted_by IS NOT NULL AND posted_by <> ''
          AND TRIM(COALESCE(team, '')) <> ''
        GROUP BY TRIM(COALESCE(team, '')), posted_by
    )
    SELECT
        (SELECT COALESCE(json_agg(t ORDER BY t.profit DESC NULLS LAST), '[]'::json)
           FROM (SELECT posted_by, profit, loads FROM weekly
                 ORDER BY profit DESC NULLS LAST LIMIT 3) t)        AS week_top_profit,
        (SELECT COALESCE(json_agg(t ORDER BY t.margin_pct DESC NULLS LAST), '[]'::json)
           FROM (SELECT posted_by, margin_pct, loads, profit, revenue FROM weekly
                 WHERE revenue > 0
                 ORDER BY margin_pct DESC NULLS LAST LIMIT 3) t)    AS week_top_margin,
        (SELECT COALESCE(json_agg(t ORDER BY t.loads DESC), '[]'::json)
           FROM (SELECT posted_by, loads FROM weekly
                 ORDER BY loads DESC LIMIT 3) t)                    AS week_top_loads,
        (SELECT COALESCE(json_agg(t ORDER BY t.loads DESC), '[]'::json)
           FROM (SELECT posted_by, loads, profit FROM daily
                 ORDER BY loads DESC, profit DESC NULLS LAST LIMIT 3) t)
                                                                    AS today_top_loads,
        (SELECT COALESCE(json_agg(t ORDER BY t.profit DESC NULLS LAST), '[]'::json)
           FROM (SELECT posted_by, profit, loads FROM daily
                 ORDER BY profit DESC NULLS LAST, loads DESC LIMIT 3) t)
                                                                    AS today_top_profit,
        (SELECT COALESCE(
                  json_agg(
                    json_build_object(
                      'team', d.team,
                      'today_top_loads', (
                        SELECT COALESCE(json_agg(t ORDER BY t.loads DESC), '[]'::json)
                        FROM (SELECT posted_by, loads, profit
                              FROM daily_by_team d2
                              WHERE d2.team = d.team
                              ORDER BY loads DESC, profit DESC NULLS LAST LIMIT 3) t
                      ),
                      'today_top_profit', (
                        SELECT COALESCE(json_agg(t ORDER BY t.profit DESC NULLS LAST), '[]'::json)
                        FROM (SELECT posted_by, profit, loads
                              FROM daily_by_team d2
                              WHERE d2.team = d.team
                              ORDER BY profit DESC NULLS LAST, loads DESC LIMIT 3) t
                      )
                    )
                    ORDER BY d.team
                  ),
                  '[]'::json
                )
           FROM (SELECT DISTINCT team FROM daily_by_team) d)        AS by_team
    """

    row = await pool.fetchrow(sql, *params)

    def _parse(v):
        if v is None:
            return []
        if isinstance(v, str):
            return json.loads(v)
        return v

    return {
        "success": True,
        "data": {
            "week_top_profit":  _parse(row["week_top_profit"])  if row else [],
            "week_top_margin":  _parse(row["week_top_margin"])  if row else [],
            "week_top_loads":   _parse(row["week_top_loads"])   if row else [],
            "today_top_loads":  _parse(row["today_top_loads"])  if row else [],
            "today_top_profit": _parse(row["today_top_profit"]) if row else [],
            "by_team":          _parse(row["by_team"])          if row else [],
        },
    }
