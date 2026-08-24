"""Scope constants and the shared APIRouter for Ops Portal - Overview.

Part of the ``ops_portal_overview`` package (split 2026-08-14 — see SPEC-CUSTOM-REPORTS §28).
"""

from __future__ import annotations

from datetime import date

from fastapi import APIRouter

from app.datalake import sql_str_list


YEAR_START = date(2026, 1, 1)
YEAR_END = date(2026, 12, 31)

# CORP-only scope per the PDF (excludes TEAM-DFW).
CORP_TEAMS = ("TEAM1", "TEAM2", "TEAM3", "TEAM4", "TEAM5")
CORP_COMPANIES = ("TMS", "TMS3")
OPEN_STATUSES = ("D", "P")

# The DFW division (Bruno PDF 2026-08-21). One `team_id` value; the team a row
# belongs to lives in `v4.team` / `scorecard.team_dfw` instead — see _scope.py.
# TM5 is included per the PDF although it is nearly dormant (28 orders in 2026,
# none since 31-Jul); omitting it would delete those rows rather than show an
# empty pill (§75).
DFW_TEAM = "TEAM-DFW"
DFW_SUB_TEAMS = ("TM1", "TM2", "TM3", "TM4", "TM5")

# Mirrors xray_corp.OTP_CODES / OTD_CODES (Bruno's Qlik load script).
OTP_CODES = ("T4", "T3", "D1", "D2", "BO", "BE", "AL", "AI", "AH", "AF", "A5", "A2")
OTD_CODES = ("AL", "D2", "AZ", "AH", "BE", "D1", "A5", "AI", "AF", "A2", "A1", "AU", "U3")

# Per-customer canonical team — same pattern budget_followup uses (the team
# with the most loads in v4, alphabetical tiebreak), restricted to the division.
#
# ⚠ Under DFW the ranked column is `team` (TM1..TM5), because `team_id` is the
# constant 'TEAM-DFW' there and ranking it would map every customer to one
# bucket. The OUTPUT alias stays `team_id` so every `JOIN customer_team ct ON …
# ct.team_id` call site is unchanged (§69: one name, one definition).
#
# ⚠ The IN-list is rendered by `sql_str_list`, NOT by `{...!r}`. A Python tuple
# repr is not a SQL list: CORP's five ids happened to repr as valid SQL, but the
# DFW division is a SINGLE team_id and reprs as `('TEAM-DFW',)` — a trailing
# comma Postgres rejects with 42601. Every panel built on this CTE 500'd on the
# DFW page for three days while CORP, running the same line, stayed green (§81).
def customer_team_cte(scope=None) -> str:
    from ._scope import CORP_SCOPE

    sc = scope or CORP_SCOPE
    return f"""
customer_team AS (
    SELECT customer_name, team_id FROM (
        SELECT
            TRIM(customer_name) AS customer_name,
            TRIM({sc.v4_team_col})       AS team_id,
            ROW_NUMBER() OVER (
                PARTITION BY TRIM(customer_name)
                ORDER BY COUNT(*) DESC, TRIM({sc.v4_team_col})
            ) AS rn
        FROM public.mcleod_gld_budget_report_v4
        WHERE TRIM(team_id) IN {sql_str_list(sc.base_teams)}
        GROUP BY TRIM(customer_name), TRIM({sc.v4_team_col})
    ) ranked
    WHERE rn = 1
)
"""


# Back-compat: the CORP rendering, re-exported by the package façade and read
# by name from ops_team_perf_digest / services.team_perf_digest.
CUSTOMER_TEAM_CTE = customer_team_cte()

router = APIRouter(tags=["ops-portal-overview"], prefix="/custom/ops-portal-overview")
