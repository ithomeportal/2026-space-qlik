"""Code-made report: DFW Podium Top (+ per-team variants TM1..TM4).

Companion to ``Podium Set DFW`` (``routers/podium_dfw.py``). Shows the
leaderboards Bruno asked for — no date filter, no booking-detail table:

  This Week (Mon-Sun, current week):
    - Best Profit This Week    (Posted by, Profit, Loads) — ALL bookers (R10)
    - Top 3 Bookers by Margin% (Posted by, Margin% = SumProfit/SumRevenue, Loads) — top 3
    - Best Loads This Week     (Posted by, Loads) — ALL bookers (R10)
  Today — ALL bookers (Bruno R6 removed the top-3 display limit):
    - Top Bookers by Loads     (Posted by, Loads, Profit)
    - Top Bookers by Profit    (Posted by, Profit, Loads)

Bruno R6 (2026-06-02, ``BRUNO -- DFW Podium Top Updates.pdf``):
  - R1–R4: removed the per-TM "TOP BOOKERS BY LOADS/PROFIT – TMx" cards
    (the old ``by_team`` payload + ``daily_by_team`` CTE are gone).
  - R6: the two Today cards no longer ``LIMIT 3`` — they list every booker.
  - R7: the report is duplicated into four server-locked per-team reports
    (``dfw-podium-top-tm1`` … ``-tm4``). Each calls the same query with
    ``team`` pinned to a single TM, so a TM1 user only ever sees TM1 rows.

R8 (2026-06-06): optional ``equipment`` query param — case-insensitive
*contains* match on the load's equipment type (v4 ``equipment_type_descr``
falling back to the trimmed ``equipment_type_id`` code). All five
leaderboards recompute over only the matching loads.

R10 (2026-06-10, ``BRUNO -- DFW Podium Top Updates.pdf``): the two This-Week
cards lose their ``LIMIT 3`` and are renamed — "TOP 3 Bookers by Profit" →
"Best Profit This Week", "TOP 3 Bookers by Loads" → "Best Loads This Week".
Margin% stays top-3. Ranks past 3 show a plain number (no medal).

Same data contract as ``podium_dfw.py``: the rate-conf base CTE is identical
(``mcleod_gld_order_post_hist`` filtered ``posted_type='C'`` /
``comments='Rate Conf Received'`` joined to ``mcleod_gld_budget_report_v4``
on ``id``), scope ``team_id = ANY(_pad_variants('TEAM-DFW'))``. The per-team
reports additionally filter ``rate_conf.team = 'TMn'``.

date_trunc('week', CURRENT_DATE) is ISO Monday in Postgres → Mon-Sun is the
half-open ``[week_start, week_start + 7)`` window; the asyncpg pool pins
each session to ``America/Chicago`` (`main._set_cst_session`) so plain
``CURRENT_DATE`` is already CST.
"""

import json
import re
from typing import Optional

from fastapi import APIRouter, Depends, Query, Request

from app.datalake import pad_variants as _pad_variants
from app.routers.deps import get_datalake_gold_pool, require_report_access


PODIUM_TOP_TEAMS = ("TEAM-DFW",)

# Bruno 2026-06-09 ("BRUNO -- DFW Podium Top Updates.pdf" R1): a "Bookers" /
# "All DFW" toggle, "Bookers" selected by default. The Bookers group is a
# fixed roster of named people; the leaderboards restrict to loads posted by
# anyone in it. "All DFW" drops the restriction (every poster on TEAM-DFW).
BOOKER_NAMES: tuple[str, ...] = (
    "Anthares Montoya",
    "Eugenio Miranda",
    "Juan Reyna",
    "Ximena Herrera",
    "Jonathan Rodriguez",
    "Jonathan Hernandez",
    "Daniel Salazar",
    "Antonio Arizpe",
    "Daniela Vita",
    "Andres Sanmiguel",
    "Antonia Bulnes",
    "Roberto Barcenas",
    "Maria Gonzalez",
)

# posted_by_name in McLeod can vary by case, accent, token order
# ("Montoya, Anthares" vs "Anthares Montoya") and compound surnames written
# with a space ("San Miguel"). We normalize both sides to lowercase, strip
# accents, then keep only [a-z], and require BOTH the first- and last-name
# tokens to appear as substrings. Requiring both tokens makes the
# "daniel" ⊂ "daniela" style overlap harmless (Daniel Salazar needs
# "salazar" too). If a roster member never surfaces on the live report it's
# a spelling/format mismatch we tune once we can see the real posted_by
# values — this is an iterative Bruno report.
_ACCENTS_FROM = "áàäâãåÁÀÄÂÃÅéèëêÉÈËÊíìïîÍÌÏÎóòöôõÓÒÖÔÕúùüûÚÙÜÛñÑçÇ"
_ACCENTS_TO = "a" * 12 + "e" * 8 + "i" * 8 + "o" * 10 + "u" * 8 + "n" * 2 + "c" * 2
assert len(_ACCENTS_FROM) == len(_ACCENTS_TO)

# SQL expression: posted_by → lowercase, unaccented, letters-only.
_NORM_POSTED_BY = (
    f"regexp_replace(lower(translate(posted_by, '{_ACCENTS_FROM}', '{_ACCENTS_TO}')),"
    " '[^a-z]', '', 'g')"
)


def _booker_token_pairs() -> list[tuple[str, str]]:
    """(first_token, last_token) lowercase letters-only for each booker."""
    pairs: list[tuple[str, str]] = []
    for name in BOOKER_NAMES:
        parts = [re.sub(r"[^a-z]", "", p.lower()) for p in name.split()]
        parts = [p for p in parts if p]
        if len(parts) >= 2:
            pairs.append((parts[0], parts[-1]))
    return pairs


_BOOKER_TOKEN_PAIRS = _booker_token_pairs()

# Bruno R7 (2026-06-02): per-team report config. ``(TM, role)`` — the role is
# the *initial* seed role; ``role_report_access`` (admin UI) is the source of
# truth thereafter. Mirrors the XRay DFW TM1..TM4 access pattern.
TEAM_CONFIGS: tuple[tuple[str, str], ...] = (
    ("TM1", "DFW-TM1"),
    ("TM2", "DFW-TM2"),
    ("TM3", "DFW-TM3"),
    ("TM4", "DFW-TM4"),
)


_RATE_CONF_CTE = """
rate_conf AS MATERIALIZED (
    SELECT
        TRIM(rp.id)                 AS order_id,
        rp.posted_date              AS posted_date,
        TRIM(rp.posted_by_name)     AS posted_by,
        br.team                     AS team,
        -- descr when present ('Van'), else trimmed code ('F48') -- both v4
        -- columns are blank-padded / sometimes empty. SELECT-side TRIM only.
        COALESCE(
            NULLIF(TRIM(br.equipment_type_descr), ''),
            NULLIF(TRIM(br.equipment_type_id), '')
        )                           AS equipment_type,
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


async def _fetch_podiums(
    request: Request,
    team: Optional[str] = None,
    equipment: str = "",
    group: str = "bookers",
) -> dict:
    """Run the leaderboard query, optionally locked to a single DFW sub-team.

    When ``team`` is given (``TM1``..``TM4``) every leaderboard is scoped to
    that sub-team via ``rate_conf.team = $n``. The weekly cards stay top-3
    (Bruno R5 "keep unchanged"); the Today cards return all bookers (R6).

    ``equipment`` (R8, 2026-06-06) is a case-insensitive *contains* match on
    ``rate_conf.equipment_type`` — every leaderboard recomputes over only the
    matching loads. Empty string = no filter. NULL-equipment loads never match
    a non-empty search (ILIKE on NULL is NULL).
    """
    pool = get_datalake_gold_pool(request)
    params: list = [_pad_variants(list(PODIUM_TOP_TEAMS), width=8)]

    # Optional filters — predicates are added in lockstep with their params so
    # the $n placeholders always line up (asyncpg numbering rule).
    extra_filter = ""
    if team:
        params.append(team)
        extra_filter += f"          AND TRIM(team) = ${len(params)}\n"
    if equipment.strip():
        params.append(equipment.strip())
        extra_filter += (
            f"          AND equipment_type ILIKE '%' || ${len(params)} || '%'\n"
        )
    # Bruno R1 (2026-06-09): restrict to the Bookers roster by default. Each
    # OR-clause requires both name tokens to appear in the normalized
    # posted_by. "all" drops the restriction (every DFW poster).
    if group != "all" and _BOOKER_TOKEN_PAIRS:
        clauses = []
        for first, last in _BOOKER_TOKEN_PAIRS:
            params.append(first)
            pf = len(params)
            params.append(last)
            pl = len(params)
            clauses.append(
                f"({_NORM_POSTED_BY} LIKE '%' || ${pf} || '%'"
                f" AND {_NORM_POSTED_BY} LIKE '%' || ${pl} || '%')"
            )
        extra_filter += "          AND (" + " OR ".join(clauses) + ")\n"

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
{extra_filter}        GROUP BY posted_by
    ),
    -- Today aggregation: both loads + profit on every row so each leaderboard
    -- shows both numbers regardless of which metric was the primary sort.
    daily AS (
        SELECT posted_by,
               COUNT(*)::int                            AS loads,
               COALESCE(SUM(profit), 0)::float          AS profit
        FROM rate_conf
        WHERE posted_date::date = CURRENT_DATE
          AND posted_by IS NOT NULL AND posted_by <> ''
{extra_filter}        GROUP BY posted_by
    )
    SELECT
        -- Bruno 2026-06-10: "Best Profit This Week" — no LIMIT, every booker.
        (SELECT COALESCE(json_agg(t ORDER BY t.profit DESC NULLS LAST), '[]'::json)
           FROM (SELECT posted_by, profit, loads FROM weekly
                 ORDER BY profit DESC NULLS LAST) t)                AS week_top_profit,
        -- Bruno 2026-06-15: "Top 3 Bookers by Margin" — internal filter, only
        -- bookers with more than 15 loads this week qualify (drops 1-load high-%
        -- outliers from the ranking).
        (SELECT COALESCE(json_agg(t ORDER BY t.margin_pct DESC NULLS LAST), '[]'::json)
           FROM (SELECT posted_by, margin_pct, loads, profit, revenue FROM weekly
                 WHERE revenue > 0 AND loads > 15
                 ORDER BY margin_pct DESC NULLS LAST LIMIT 3) t)    AS week_top_margin,
        -- Bruno 2026-06-10: "Best Loads This Week" — no LIMIT, every booker.
        (SELECT COALESCE(json_agg(t ORDER BY t.loads DESC), '[]'::json)
           FROM (SELECT posted_by, loads FROM weekly
                 ORDER BY loads DESC) t)                            AS week_top_loads,
        -- Bruno R6: no LIMIT — every booker today, ranked.
        (SELECT COALESCE(json_agg(t ORDER BY t.loads DESC, t.profit DESC NULLS LAST), '[]'::json)
           FROM (SELECT posted_by, loads, profit FROM daily) t)     AS today_top_loads,
        (SELECT COALESCE(json_agg(t ORDER BY t.profit DESC NULLS LAST, t.loads DESC), '[]'::json)
           FROM (SELECT posted_by, profit, loads FROM daily) t)     AS today_top_profit
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
            "locked_team":      team,
        },
    }


# --- Main report: all of TEAM-DFW ------------------------------------------
router = APIRouter(tags=["dfw-podium-top"], prefix="/custom/dfw-podium-top")


@router.get("/podiums")
async def podiums(
    request: Request,
    equipment: str = Query("", max_length=80),
    group: str = Query("bookers"),
    _user: dict = Depends(require_report_access("dfw-podium-top")),
):
    return await _fetch_podiums(request, team=None, equipment=equipment, group=group)


# --- Per-team reports: DFW Podium Top TM1..TM4 (Bruno R7) -------------------
def _make_team_router(tm: str, role: str) -> APIRouter:
    """Build one APIRouter for a single DFW sub-team, ``team`` server-locked.

    Role gate is DB-backed via ``require_report_access("dfw-podium-top-tmN")``
    so the role list is editable in ``/admin/reports`` without a redeploy.
    """
    slug = tm.lower()
    report_key = f"dfw-podium-top-{slug}"
    gate = require_report_access(report_key)
    r = APIRouter(tags=[report_key], prefix=f"/custom/{report_key}")

    @r.get("/podiums")
    async def podiums_team(
        request: Request,
        equipment: str = Query("", max_length=80),
        group: str = Query("bookers"),
        _user: dict = Depends(gate),
    ):
        return await _fetch_podiums(request, team=tm, equipment=equipment, group=group)

    return r


# Built at import time; included in main.py alongside the main router.
team_routers: tuple[APIRouter, ...] = tuple(
    _make_team_router(tm, role) for tm, role in TEAM_CONFIGS
)
