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

Date basis (Podium PDF 2026-11-09 R1): ``basis=rate_conf`` (default, the
original) windows on the latest Rate-Conf ``posted_date``; ``basis=departure``
windows on v4 ``origin_actual_departure``. The POPULATION is the same in both
— DFW orders with a Rate-Conf posting, never Void (Diego 2026-11-09: "Rate
Conf loads only") — only the date that filters it moves. ⚠ Departure mode
cannot reuse the posted_date scan floor: an October departure's Rate Conf was
posted up to 84 days earlier (22 of 1,523 lost under the MTD floor), so it
drives from the v4 departure window and looks the postings up by id.
⚠ A load not yet departed carries the 1900-01-01 SENTINEL, not NULL — it is
guarded explicitly (a custom start of 1900 would otherwise sweep it in) and
rendered as NULL in the ``departed`` column.

Status (R2): ``status=`` repeatable, allowlisted to D / P / A. Void stays out
for every user (Bruno 2026-07-07) and is not offered. Applied server-side so
the KPI cards span the same population as the rows (§96).

v4 sparseness: v4 lags in-progress loads for the current month, so some of
today's rows may come back with ``profit=NULL`` / ``revenue=NULL``. We pass
them through (frontend renders an em-dash) -- matches the Qlik app behavior.
"""

import re as _re
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query, Request

from app.datalake import pad_variants as _pad_variants
from app.routers.deps import get_datalake_gold_pool, require_report_access

# --------------------------------------------------------------------------
# Scope
# --------------------------------------------------------------------------
PODIUM_TEAMS = ("TEAM-DFW",)

# Status allowlist (R2 2026-11-09). 'V' is excluded for everyone, so never offered.
STATUS_OPTIONS = ("D", "P", "A")

# v4 stores "not departed yet" as 1900-01-01, not NULL (measured 2026-11-09:
# every A row and all but one V row). Any departure before this FLOOR is that
# sentinel — the floor sits well above it so a near-sentinel value is caught too.
_DEPARTED_FLOOR = "'2000-01-01'::timestamp"

# Columns shared by both bases. ``br`` = v4, ``mov`` = first movement.
_COLUMNS = f"""
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
        br.status                   AS status,
        CASE WHEN br.origin_actual_departure >= {_DEPARTED_FLOOR}
             THEN br.origin_actual_departure END AS departed,
        br.margin_amt::float        AS profit,
        br.total_charge::float      AS revenue,
        -- Carrier (first movement's payee_name). Canonical LEFT JOIN LATERAL
        -- first-match pattern (SPEC-CODE-RULES §5) also used by ops-portal /
        -- ceo-executive By-Order rows.
        NULLIF(TRIM(mov.payee_name), '') AS carrier
"""

_CARRIER_LATERAL = """
    LEFT JOIN LATERAL (
        SELECT m.payee_name
        FROM public.mcleod_gld_movement m
        WHERE m.order_id = br.id AND m.company_id = br.company_id
        ORDER BY m.movement_id ASC
        LIMIT 1
    ) mov ON TRUE
"""

_RC_POSTINGS = """
        FROM public.mcleod_gld_order_post_hist
        WHERE TRIM(posted_type) = 'C'
          AND TRIM(comments)    = 'Rate Conf Received'
"""


def _rate_conf_cte(status_sql: str) -> str:
    """basis=rate_conf — the Qlik-aligned base CTE (lifted from
    SPEC-dfw-loads-to-cover, made sargable). ``$1`` = pad_variants(teams),
    ``$2`` = custom start or NULL (scan floor)."""
    return f"""
rate_conf AS MATERIALIZED (
    SELECT
        TRIM(rp.id)                 AS order_id,
        rp.posted_date              AS posted_date,
        TRIM(rp.posted_by_name)     AS posted_by,
        {_COLUMNS}
    FROM (
        SELECT id, posted_date, posted_by_name,
               ROW_NUMBER() OVER (PARTITION BY id ORDER BY posted_date DESC) AS rn
        {_RC_POSTINGS}
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
    {_CARRIER_LATERAL}
    WHERE rp.rn = 1
      AND br.team_id = ANY($1::text[])
      -- Exclude VOID (status 'V') loads for all users (Bruno 2026-07-07).
      -- status is an unpadded 1-char code (D/V/A/P) so no pad_variants /
      -- TRIM needed; the team_id predicate above already makes the v4 join
      -- effectively inner, so br.status is never NULL here.
      AND br.status <> 'V'{status_sql}
)
"""


def _departure_window(col: str, lo: str, hi: str) -> str:
    """Half-open ``[lo, hi)`` plus the explicit 1900-sentinel guard."""
    return (
        f"{col} >= {lo}\n"
        f"      AND {col} <  {hi}\n"
        f"      AND {col} >= {_DEPARTED_FLOOR}"
    )


def _departure_cte(lo: str, hi: str, status_sql: str) -> str:
    """basis=departure — same population, windowed on v4
    ``origin_actual_departure`` in ``[lo, hi)``. Drives FROM the v4 window and
    looks each order's latest Rate-Conf posting up by id, so a posting made
    weeks before departure is never cut by a posted_date floor."""
    return f"""
departed_ids AS MATERIALIZED (
    SELECT id
    FROM public.mcleod_gld_budget_report_v4
    WHERE team_id = ANY($1::text[])
      AND status <> 'V'
      AND {_departure_window("origin_actual_departure", lo, hi)}
),
rate_conf AS MATERIALIZED (
    SELECT
        TRIM(br.id)                 AS order_id,
        rp.posted_date              AS posted_date,
        TRIM(rp.posted_by_name)     AS posted_by,
        {_COLUMNS}
    FROM (
        SELECT id, posted_date, posted_by_name,
               ROW_NUMBER() OVER (PARTITION BY id ORDER BY posted_date DESC) AS rn
        {_RC_POSTINGS}
          AND id IN (SELECT id FROM departed_ids)
    ) rp
    JOIN public.mcleod_gld_budget_report_v4 br
      ON TRIM(rp.id) = TRIM(br.id)
    {_CARRIER_LATERAL}
    WHERE rp.rn = 1
      AND br.team_id = ANY($1::text[])
      AND br.status <> 'V'
      AND {_departure_window("br.origin_actual_departure", lo, hi)}{status_sql}
)
"""


# basis=rate_conf: map the UI range values to a SQL boolean on ``posted_date``.
# Pool sessions are pinned to America/Chicago, so CURRENT_DATE is CST.
_RANGE_FILTERS = {
    "today": "posted_date::date = CURRENT_DATE",
    "wtd":   "posted_date::date >= date_trunc('week', CURRENT_DATE)::date",
    "mtd":   "posted_date::date >= date_trunc('month', CURRENT_DATE)::date",
}

# Custom range: inclusive both ends on posted_date. ``$2`` = start at
# 00:00:00 (also the CTE scan floor), ``$3`` = end at 23:59:59.999999.
_CUSTOM_FILTER = "posted_date >= $2::timestamp AND posted_date <= $3::timestamp"

# basis=departure: half-open [lo, hi) on a naive-CST timestamp column.
# ``::date::timestamp`` keeps every bound naive (never a timestamptz, §112).
_DEPARTURE_BOUNDS = {
    "today": ("CURRENT_DATE::timestamp", "(CURRENT_DATE + 1)::timestamp"),
    "wtd":   ("date_trunc('week', CURRENT_DATE)::date::timestamp",
              "(CURRENT_DATE + 1)::timestamp"),
    "mtd":   ("date_trunc('month', CURRENT_DATE)::date::timestamp",
              "(CURRENT_DATE + 1)::timestamp"),
    "custom": ("$2::timestamp", "$3::timestamp"),
}

# YYYY-MM-DD (bare date only — the UI sends <input type="date"> values).
_DATE_RE = _re.compile(r"^\d{4}-\d{2}-\d{2}$")


def _parse_custom(start: str | None, end: str | None) -> tuple[datetime, datetime]:
    """Both dates, as datetimes at 00:00, in order. 400 on anything else —
    asyncpg needs real datetimes (a raw str raises DataError -> 500)."""
    if not (start and end and _DATE_RE.match(start) and _DATE_RE.match(end)):
        raise HTTPException(
            status_code=400,
            detail="range=custom requires start and end dates as YYYY-MM-DD.",
        )
    try:
        start_dt = datetime.strptime(start, "%Y-%m-%d")
        end_dt = datetime.strptime(end, "%Y-%m-%d")
    except ValueError:
        raise HTTPException(
            status_code=400,
            detail="range=custom requires valid calendar dates as YYYY-MM-DD.",
        )
    # Be forgiving if the user inverts the two fields.
    return (end_dt, start_dt) if start_dt > end_dt else (start_dt, end_dt)


def _parse_status(raw: list[str] | None) -> list[str]:
    """Allowlisted, de-duplicated, order-stable. Empty = no predicate."""
    picked: list[str] = []
    for value in raw or []:
        code = value.strip().upper()
        if code not in STATUS_OPTIONS:
            raise HTTPException(
                status_code=400,
                detail=f"status must be one of {', '.join(STATUS_OPTIONS)}.",
            )
        if code not in picked:
            picked.append(code)
    return picked


def build_overview_sql(
    *,
    basis: str,
    range_: str,
    start: str | None,
    end: str | None,
    status: list[str],
) -> tuple[str, str, str, list]:
    """Return ``(cte, where, order_by, params)`` for the overview queries.

    Placeholders are numbered as they are appended, so a mode that does not
    reference ``$2`` never passes it (asyncpg rejects unused arguments).
    """
    params: list = [_pad_variants(list(PODIUM_TEAMS), width=8)]  # $1

    custom = _parse_custom(start, end) if range_ == "custom" else None

    if basis == "departure":
        if custom:
            params.append(custom[0])                       # $2 lo (00:00)
            params.append(custom[1] + timedelta(days=1))   # $3 hi (exclusive)
        lo, hi = _DEPARTURE_BOUNDS[range_]
        status_sql = _status_sql(params, status)
        return (
            _departure_cte(lo, hi, status_sql),
            "TRUE",
            "departed DESC NULLS LAST",
            params,
        )

    if custom:
        params.append(custom[0])                                       # $2
        params.append(custom[1].replace(hour=23, minute=59,
                                        second=59, microsecond=999999))  # $3
        where = _CUSTOM_FILTER
    else:
        params.append(None)  # $2 -> NULL, presets keep the default scan floor
        where = _RANGE_FILTERS[range_]
    status_sql = _status_sql(params, status)
    return _rate_conf_cte(status_sql), where, "posted_date DESC NULLS LAST", params


def _status_sql(params: list, status: list[str]) -> str:
    if not status:
        return ""
    params.append(status)
    return f"\n      AND br.status = ANY(${len(params)}::text[])"


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
    basis: str = Query("rate_conf", pattern="^(rate_conf|departure)$",
                       description="Date the range filters: Rate-Conf posting or origin actual departure"),
    status: list[str] | None = Query(None, description="Repeatable v4 status code: D, P, A"),
    _user: dict = Depends(require_report_access("podium-dfw")),
):
    """KPIs + row-level table for the Podium Set DFW report.

    Response shape:
      ``{ success, data: { range, basis, status, kpis: {...}, rows: [...] } }``
    """
    picked = _parse_status(status)
    cte, where, order_by, params = build_overview_sql(
        basis=basis, range_=range, start=start, end=end, status=picked,
    )
    pool = get_datalake_gold_pool(request)

    kpi_sql = f"""
    WITH {cte}
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
    WITH {cte}
    SELECT
        team, order_id, posted_by, posted_date, departed, status,
        customer, origin, destination, carrier,
        profit, revenue,
        CASE WHEN COALESCE(revenue, 0) > 0
             THEN profit / NULLIF(revenue, 0)
             ELSE NULL END                                    AS margin_pct,
        contract_type, equipment_type, company_id
    FROM rate_conf
    WHERE {where}
    ORDER BY {order_by},
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
            "departed":      r["departed"].isoformat() if r["departed"] else None,
            "status":        r["status"],
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
            "basis": basis,
            "status": picked,
            "kpis": kpis,
            "rows": rows,
        },
    }
