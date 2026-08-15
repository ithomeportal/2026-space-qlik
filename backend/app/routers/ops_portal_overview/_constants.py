"""Scope constants and the shared APIRouter for Ops Portal - Overview.

Part of the ``ops_portal_overview`` package (split 2026-08-14 — see SPEC-CUSTOM-REPORTS §28).
"""

from __future__ import annotations

from datetime import date

from fastapi import APIRouter


YEAR_START = date(2026, 1, 1)
YEAR_END = date(2026, 12, 31)

# CORP-only scope per the PDF (excludes TEAM-DFW).
CORP_TEAMS = ("TEAM1", "TEAM2", "TEAM3", "TEAM4", "TEAM5")
CORP_COMPANIES = ("TMS", "TMS3")
OPEN_STATUSES = ("D", "P")

# Mirrors xray_corp.OTP_CODES / OTD_CODES (Bruno's Qlik load script).
OTP_CODES = ("T4", "T3", "D1", "D2", "BO", "BE", "AL", "AI", "AH", "AF", "A5", "A2")
OTD_CODES = ("AL", "D2", "AZ", "AH", "BE", "D1", "A5", "AI", "AF", "A2", "A1", "AU", "U3")

# Per-customer canonical team — same pattern budget_followup uses (the team
# with the most loads in v4, alphabetical tiebreak), restricted to CORP teams.
CUSTOMER_TEAM_CTE = f"""
customer_team AS (
    SELECT customer_name, team_id FROM (
        SELECT
            TRIM(customer_name) AS customer_name,
            TRIM(team_id)       AS team_id,
            ROW_NUMBER() OVER (
                PARTITION BY TRIM(customer_name)
                ORDER BY COUNT(*) DESC, TRIM(team_id)
            ) AS rn
        FROM public.mcleod_gld_budget_report_v4
        WHERE TRIM(team_id) IN {CORP_TEAMS!r}
        GROUP BY TRIM(customer_name), TRIM(team_id)
    ) ranked
    WHERE rn = 1
)
"""

router = APIRouter(tags=["ops-portal-overview"], prefix="/custom/ops-portal-overview")
