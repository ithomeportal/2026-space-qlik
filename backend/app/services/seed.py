"""Database seeding script.

Seeds roles, reports, users, and role-report mappings.
Run: python -m app.services.seed
"""

import asyncio
from uuid import UUID

import asyncpg

from app.config import settings

# Default roles. Admins pre-existed with Title-Case names (CEO, Executive, CORP, …)
# so we seed Title-Case to avoid case-duplicate rows in the `roles` table.
# `admin` and `super_admin` are kept lowercase (singleton, no duplicates).
DEFAULT_ROLES = [
    ("admin", "Full access to all reports and admin console"),
    ("super_admin", "Admin with ability to edit report IDs and advanced settings"),
    ("CEO", "Chief Executive Officer"),
    ("Executive", "Access to all reports across divisions"),
    ("Procurement", "Procurement and carrier-sourcing reports"),
    ("Finance", "Finance and budget reports"),
    ("Operations", "Operations, carrier, and scorecard reports"),
    ("Sales", "Sales, attrition, and awards reports"),
    ("HR", "HR reports"),
    ("IT", "IT, VoIP, and managed services reports"),
    ("DFW", "DFW division reports"),
    ("CORP", "CORP division reports"),
    # Per-team CORP OPS KAM TagRoles (Bruno 2026-06-26) — gate each team's
    # private "CORP T# OPS Kam Portal" copy. Assigned to members manually.
    ("CORP-T1", "CORP Team 1 — OPS KAM (private team portal)"),
    ("CORP-T2", "CORP Team 2 — OPS KAM (private team portal)"),
    ("CORP-T3", "CORP Team 3 — OPS KAM (private team portal)"),
    ("CORP-T4", "CORP Team 4 — OPS KAM (private team portal)"),
    # Per-team DFW KAM TagRoles (Bruno PDF 2026-07-20) — grant view+edit on the
    # KAM Performance - DFW report. Assigned to members manually.
    ("DFW KAM1", "DFW KAM Team 1 — KAM Performance DFW (assigned manually)"),
    ("DFW KAM2", "DFW KAM Team 2 — KAM Performance DFW (assigned manually)"),
    ("DFW KAM3", "DFW KAM Team 3 — KAM Performance DFW (assigned manually)"),
    ("DFW KAM4", "DFW KAM Team 4 — KAM Performance DFW (assigned manually)"),
    # Per-team CORP KAM TagRoles. These already exist live (created via
    # /admin/roles) and gate the per-team Attrition WoW clones (Bruno
    # 2026-08-14). Listed here for parity only — DEFAULT_ROLES is seeded by
    # seed_all(), which main.py runs solely when role_report_access is empty,
    # so adding a name here does NOT create it on an existing deployment.
    ("CORP KAM1", "CORP Team 1 — KAM (private team reports, assigned manually)"),
    ("CORP KAM2", "CORP Team 2 — KAM (private team reports, assigned manually)"),
    ("CORP KAM3", "CORP Team 3 — KAM (private team reports, assigned manually)"),
    ("CORP KAM4", "CORP Team 4 — KAM (private team reports, assigned manually)"),
    # Individual manager TagRoles (Bruno 2026-07-06) — gate Bonus Calculator to
    # specific people, NOT whole divisions (HR=4 / Operations=52 too broad).
    # Assigned manually: HR Manager→Daniela Nava, OPs Manager→Jaime Anaya.
    ("HR Manager", "HR Manager — Bonus Calculator + HR reports (individual role, assigned manually)"),
    ("OPs Manager", "Operations Manager — Bonus Calculator (individual role, assigned manually)"),
]

# Code-made reports (not Qlik-embedded). Access granted via `roles` just like Qlik reports.
CUSTOM_REPORTS = [
    {
        "key": "esavings-carriers",  # stable identifier; becomes custom_path /reports/esavings-carriers
        "title": "eSavings from Carriers",
        "description": "Carrier savings vs baseline — loads, savings, overpay, net variance",
        "note": "Base: first-month-with-loads (Jul 2025–Mar 2026) · Q1-2026 avg (Apr–Dec 2026)",
        "category": "Operations",
        "tags": ["savings", "carrier", "procurement", "variance"],
        "owner_name": "Diego",
        "roles": ["CEO", "Executive", "Procurement", "Finance", "CORP"],
    },
    {
        "key": "budget-followup-2026",  # -> /reports/budget-followup-2026
        "title": "2026 Official Budget Follow Up",
        "description": "2026 actuals vs budget — loads, revenue, profit, margin by customer and team",
        "note": "Scope: full year 2026 · Teams TEAM1–TEAM5 · source: daily_production_budget_report",
        "category": "Operations",
        "tags": ["budget", "production", "actuals", "variance", "ops"],
        "owner_name": "Diego",
        "roles": ["CEO", "Executive", "Operations", "Finance", "CORP", "DFW"],
    },
    {
        "key": "xray-corp-mng",  # -> /reports/xray-corp-mng
        "title": "XRay CORP Mng",
        "description": "CORP management X-Ray — KPIs, teams, lanes, trends, risk and contract/spot split",
        "note": "Scope: TEAM1–TEAM5 · company TMS/TMS3 · excludes OILTEX · 6 tabs",
        "category": "Executive",
        "tags": ["corp", "x-ray", "management", "kpi", "otp", "otd", "lanes", "teams"],
        "owner_name": "Diego",
        "roles": ["CEO", "Executive", "CORP", "Operations", "Finance"],
    },
    {
        "key": "xray-dfw-mng",  # -> /reports/xray-dfw-mng
        "title": "XRay DFW Mng",
        "description": "DFW management X-Ray — KPIs, sub-teams TM1–TM4, lanes, trends, risk and contract/spot split",
        "note": "Scope: TEAM-DFW · sub-teams TM1–TM4 · company TMS/TMS3 · excludes UNILINK & OILTEX · Profit-TM from v4 directly · 6 tabs",
        "category": "Executive",
        "tags": ["dfw", "x-ray", "management", "kpi", "otp", "otd", "lanes", "teams"],
        "owner_name": "Diego",
        "roles": ["CEO", "Executive", "DFW", "Operations", "Finance"],
    },
    {
        "key": "xray-dfw-tm1",  # -> /reports/xray-dfw-tm1
        "title": "XRay DFW TM1",
        "description": "XRay DFW Mng locked to TM1 — KPIs, lanes, trends, risk and contract/spot split for TM1 only",
        "note": "Scope: TEAM-DFW + team=TM1 (server-locked) · same engine as XRay DFW Mng · access strictly DFW-TM1 + leadership",
        "category": "Executive",
        "tags": ["dfw", "tm1", "x-ray", "management", "kpi", "otp", "otd"],
        "owner_name": "Diego",
        "roles": ["DFW-TM1", "Executive"],
    },
    {
        "key": "xray-dfw-tm2",  # -> /reports/xray-dfw-tm2
        "title": "XRay DFW TM2",
        "description": "XRay DFW Mng locked to TM2 — KPIs, lanes, trends, risk and contract/spot split for TM2 only",
        "note": "Scope: TEAM-DFW + team=TM2 (server-locked) · same engine as XRay DFW Mng · access strictly DFW-TM2 + leadership",
        "category": "Executive",
        "tags": ["dfw", "tm2", "x-ray", "management", "kpi", "otp", "otd"],
        "owner_name": "Diego",
        "roles": ["DFW-TM2", "Executive"],
    },
    {
        "key": "xray-dfw-tm3",  # -> /reports/xray-dfw-tm3
        "title": "XRay DFW TM3",
        "description": "XRay DFW Mng locked to TM3 — KPIs, lanes, trends, risk and contract/spot split for TM3 only",
        "note": "Scope: TEAM-DFW + team=TM3 (server-locked) · same engine as XRay DFW Mng · access strictly DFW-TM3 + leadership",
        "category": "Executive",
        "tags": ["dfw", "tm3", "x-ray", "management", "kpi", "otp", "otd"],
        "owner_name": "Diego",
        "roles": ["DFW-TM3", "Executive"],
    },
    {
        "key": "xray-dfw-tm4",  # -> /reports/xray-dfw-tm4
        "title": "XRay DFW TM4",
        "description": "XRay DFW Mng locked to TM4 — KPIs, lanes, trends, risk and contract/spot split for TM4 only",
        "note": "Scope: TEAM-DFW + team=TM4 (server-locked) · same engine as XRay DFW Mng · access strictly DFW-TM4 + leadership",
        "category": "Executive",
        "tags": ["dfw", "tm4", "x-ray", "management", "kpi", "otp", "otd"],
        "owner_name": "Diego",
        "roles": ["DFW-TM4", "Executive"],
    },
    {
        "key": "ceo-executive",  # -> /reports/ceo-executive
        "title": "CEO Executive",
        "description": "Executive 6-tab view: KPIs, trends, customers, weekly, risk, orders",
        "note": "Scope: TEAM1–TEAM5 + TEAM-DFW · TMS/TMS3 · excludes OILTEX & UNILINK · admin + CEO only",
        "category": "Executive",
        "tags": ["ceo", "executive", "kpi", "customers", "lanes", "risk", "orders", "weekly"],
        "owner_name": "Diego",
        "roles": ["CEO"],
    },
    {
        "key": "ceo-cockpit",  # -> /reports/ceo-cockpit
        "title": "CEO Cockpit",
        "description": "Executive cockpit: one hero KPI per report, colour-coded, click a card to open the full report",
        "note": "Aggregates every report's headline KPI in-process · personalized by role · first-draft thresholds (tune in code)",
        "category": "Executive",
        "tags": ["ceo", "cockpit", "dashboard", "kpi", "executive", "overview", "summary"],
        "owner_name": "Diego",
        "roles": ["CEO", "Executive", "CORP", "DFW", "Finance", "Operations", "Sales"],
    },
    {
        "key": "hr-access-doors",  # -> /reports/hr-access-doors
        "title": "HR - Access Log Doors",
        "description": "Fingerprint check-in log with on-time vs late analysis per employee, team and day",
        "note": "First punch/day · expected arrival per dept+job_title · source: zk_gld_onlyfingerprint + timeoff_employee",
        "category": "HR",
        "tags": ["hr", "attendance", "fingerprint", "on-time", "late", "access", "door"],
        "owner_name": "Diego",
        "roles": ["CEO", "Executive", "HR", "IT"],
    },
    {
        "key": "dfw-access-doors",  # -> /reports/dfw-access-doors
        "title": "DFW - Access Log Doors",
        "description": "Fingerprint check-in log filtered to Operations (DFW) — on-time vs late by employee, job-title and day",
        "note": "Same engine as HR Access Log Doors but server-locked to Operations (DFW); by-job-title bar replaces by-department · source: zk_gld_onlyfingerprint + timeoff_employee",
        "category": "Operations",
        "tags": ["dfw", "attendance", "fingerprint", "on-time", "late", "access", "door"],
        "owner_name": "Diego",
        "roles": ["DFW", "DFW-Assistent", "DFW KAM", "Assitent OPs manager"],
    },
    {
        "key": "admin-access-doors",  # -> /reports/admin-access-doors
        "title": "Admin - Access Log Doors",
        "description": "Fingerprint check-in log filtered to the Admin department — on-time vs late by employee, job-title and day",
        "note": "Same engine as HR Access Log Doors but server-locked to dep='Admin'; by-job-title bar replaces by-department · source: zk_gld_onlyfingerprint + timeoff_employee",
        "category": "Admin",
        "tags": ["admin", "attendance", "fingerprint", "on-time", "late", "access", "door"],
        "owner_name": "Diego",
        "roles": ["AdminFinance"],
    },
    {
        "key": "ops-access-doors",  # -> /reports/ops-access-doors
        "title": "OPS - Access Log Doors",
        "description": "Fingerprint check-in log filtered to the Operations department — on-time vs late by employee, job-title and day",
        "note": "Same engine as HR Access Log Doors but server-locked to dep='Operations' (excludes Operations (DFW), which has its own report); by-job-title bar replaces by-department · source: zk_gld_onlyfingerprint + timeoff_employee",
        "category": "Operations",
        "tags": ["ops", "operations", "attendance", "fingerprint", "on-time", "late", "access", "door"],
        "owner_name": "Diego",
        "roles": ["CEO", "Executive", "Operations", "OPs Manager"],
    },
    {
        "key": "pricing-access-doors",  # -> /reports/pricing-access-doors
        "title": "Pricing - Access Log Doors",
        "description": "Fingerprint check-in log filtered to the Pricing department — on-time vs late by employee, job-title and day",
        "note": "Same engine as HR Access Log Doors but server-locked to dep='Pricing'; by-job-title bar replaces by-department · source: zk_gld_onlyfingerprint + timeoff_employee",
        "category": "Pricing",
        "tags": ["pricing", "attendance", "fingerprint", "on-time", "late", "access", "door"],
        "owner_name": "Diego",
        "roles": ["CEO", "Executive", "Pricing"],
    },
    {
        "key": "carrier-procurement-access-doors",  # -> /reports/carrier-procurement-access-doors
        "title": "Carrier Procurement - Access Log Doors",
        "description": "Fingerprint check-in log filtered to the Carrier Procurement team — on-time vs late by employee and day",
        "note": "Same engine as HR Access Log Doors but server-locked by JOB TITLE, not department: jt IN ('Carrier Procurement','Carrier Procurement Team Leader'). Both titles sit in dep='Operations', so this is a subset of OPS Access Log Doors · source: zk_gld_onlyfingerprint + timeoff_employee",
        "category": "Procurement",
        "tags": ["carrier", "procurement", "attendance", "fingerprint", "on-time", "late", "access", "door"],
        "owner_name": "Diego",
        "roles": ["CEO", "Executive", "Procurement"],
    },
    {
        "key": "podium-dfw",  # -> /reports/podium-dfw
        "title": "Podium Set DFW",
        "description": "Live DFW Rate-Conf Received podium: KPIs + today's bookings (Today / WTD / MTD)",
        "note": "TEAM-DFW only · Rate Conf Received latest/order · source: order_post_hist + budget_report_v4",
        "category": "Operations",
        "tags": ["dfw", "podium", "rate-conf", "loads", "profit", "revenue", "daily", "live"],
        "owner_name": "Diego",
        "roles": ["DFW"],
    },
    {
        "key": "booker-performance-scorecard",  # -> /reports/booker-performance-scorecard
        "title": "Booker Performance Scorecard",
        "description": "Per-booker scorecard over the DFW Bookings universe — #Orders, Profit, Margin %, Avg Margin/Load, Broken Threshold, OTP/OTD + 10-week trend",
        "note": (
            "TEAM-DFW only · same Rate-Conf-Received universe as Podium Set DFW · "
            "Carrier Cost = Revenue − Profit · Broken Threshold joins AP_module "
            "loads_to_cover.thresh (hand-entered, ~60% coverage — always read it "
            "against 'of N orders with a threshold') · OTP/OTD from "
            "scorecard_incidents_portal, orders not yet picked up count as on-time · "
            "the 10-week chart ignores the date filter by design"
        ),
        "category": "Operations",
        "tags": [
            "dfw", "booker", "scorecard", "rate-conf", "otp", "otd",
            "threshold", "margin", "profit", "weekly",
        ],
        "owner_name": "Diego",
        "roles": ["CEO", "Executive", "DFW", "Operations"],
    },
    {
        "key": "dfw-podium-top",  # -> /reports/dfw-podium-top
        "title": "DFW Podium Top",
        "description": "DFW Bookers leaderboards — This-Week TOP-3 Profit / Margin / Loads + full Today Loads / Profit lists",
        "note": "Companion to Podium Set DFW · no date filter · TEAM-DFW · This-Week top-3 + Today full list (Bruno R6) · source: order_post_hist + budget_report_v4 (same CTE as podium-dfw)",
        "category": "Operations",
        "tags": ["dfw", "podium", "top", "leaderboard", "rate-conf", "profit", "margin", "loads"],
        "owner_name": "Diego",
        "roles": ["DFW"],
    },
    # Bruno R7 (2026-06-02): per-team duplicates of DFW Podium Top, one report
    # per DFW sub-team, server-locked to that TM (mirrors XRay DFW TM1..TM4).
    {
        "key": "dfw-podium-top-tm1",  # -> /reports/dfw-podium-top-tm1
        "title": "DFW Podium Top TM1",
        "description": "DFW Podium Top locked to TM1 — This-Week TOP-3 Profit / Margin / Loads + full Today Loads / Profit lists for TM1 only",
        "note": "Scope: TEAM-DFW + team=TM1 (server-locked) · same query as DFW Podium Top · access strictly DFW-TM1 + leadership",
        "category": "Operations",
        "tags": ["dfw", "tm1", "podium", "top", "leaderboard", "rate-conf", "profit", "margin", "loads"],
        "owner_name": "Diego",
        "roles": ["DFW-TM1", "Executive"],
    },
    {
        "key": "dfw-podium-top-tm2",  # -> /reports/dfw-podium-top-tm2
        "title": "DFW Podium Top TM2",
        "description": "DFW Podium Top locked to TM2 — This-Week TOP-3 Profit / Margin / Loads + full Today Loads / Profit lists for TM2 only",
        "note": "Scope: TEAM-DFW + team=TM2 (server-locked) · same query as DFW Podium Top · access strictly DFW-TM2 + leadership",
        "category": "Operations",
        "tags": ["dfw", "tm2", "podium", "top", "leaderboard", "rate-conf", "profit", "margin", "loads"],
        "owner_name": "Diego",
        "roles": ["DFW-TM2", "Executive"],
    },
    {
        "key": "dfw-podium-top-tm3",  # -> /reports/dfw-podium-top-tm3
        "title": "DFW Podium Top TM3",
        "description": "DFW Podium Top locked to TM3 — This-Week TOP-3 Profit / Margin / Loads + full Today Loads / Profit lists for TM3 only",
        "note": "Scope: TEAM-DFW + team=TM3 (server-locked) · same query as DFW Podium Top · access strictly DFW-TM3 + leadership",
        "category": "Operations",
        "tags": ["dfw", "tm3", "podium", "top", "leaderboard", "rate-conf", "profit", "margin", "loads"],
        "owner_name": "Diego",
        "roles": ["DFW-TM3", "Executive"],
    },
    {
        "key": "dfw-podium-top-tm4",  # -> /reports/dfw-podium-top-tm4
        "title": "DFW Podium Top TM4",
        "description": "DFW Podium Top locked to TM4 — This-Week TOP-3 Profit / Margin / Loads + full Today Loads / Profit lists for TM4 only",
        "note": "Scope: TEAM-DFW + team=TM4 (server-locked) · same query as DFW Podium Top · access strictly DFW-TM4 + leadership",
        "category": "Operations",
        "tags": ["dfw", "tm4", "podium", "top", "leaderboard", "rate-conf", "profit", "margin", "loads"],
        "owner_name": "Diego",
        "roles": ["DFW-TM4", "Executive"],
    },
    {
        "key": "losses-lanes",  # -> /reports/losses-lanes
        "title": "Top Losses Lanes",
        "description": "Worst-margin lanes & customers: leak by lane, 15/18/20% target-profit gap, order detail",
        "note": "Scope: TEAM1–TEAM5 + TEAM-DFW · TMS/TMS3 · excludes UNILINK & OILTEX · source: mcleod_gld_budget_report_v4",
        "category": "Executive",
        "tags": ["losses", "margin", "lanes", "customers", "leak", "budget", "profit"],
        "owner_name": "admin",
        "roles": ["CEO", "Executive", "CORP", "DFW", "Operations", "Finance"],
    },
    {
        "key": "hd-spot",  # -> /reports/hd-spot  (Bruno PDF 2026-08-12)
        "title": "HD Spot",
        "description": "Home Depot spot performance — Offered / Quoted / Participation / Awarded / Conversion plus covered revenue, profit and margin by equipment and day",
        "note": (
            "Portal version of the daily 'HD PERFORMANCE - SPOT' email (n8n "
            "P36cH2hbx71viRBW) — same formulas, so the numbers agree · funnel from "
            "modern_pricing_portal.spot_report_condensed (customer HOME DEPOT), money "
            "from mcleod_gld_customer_view + budget_report_v4, merged in Python on "
            "order_number = blnum · Awarded = award_status 'WON' only (ACCEPT is a "
            "pending price, not a win) · Quoted = buy_rate IS NOT NULL · excludes the "
            "frozen legacy_hd/legacy imports (volume is NULL there), so data starts "
            "2026-03-01 · Revenue/Profit/Margin KPIs are the COVERED basis; blended "
            "margin is inflated by cancelled loads (~100%) and unpaid pending ones · "
            "Loads has no contract-type filter while the splits are SPOT-only, so "
            "Loads != Cancelled + Covered + Pending · Status filter scopes the money "
            "columns only (a lost quote has no order status)"
        ),
        "category": "Operations",
        "tags": [
            "home depot", "hd", "spot", "pricing", "quoting", "offered", "quoted",
            "awarded", "conversion", "participation", "margin", "funnel",
        ],
        "owner_name": "Diego",
        "roles": ["CEO", "Executive", "Procurement", "Sales", "Operations"],
    },
    {
        "key": "edi-load-tenders",  # -> /reports/edi-load-tenders  (Omar Orozco 2026-08-26)
        "title": "EDI Load Tenders",
        "description": "EDI 204 load tenders: received, turned into an order, never created, cancelled by the customer vs cancelled by us — plus the orders a customer cancelled that are still live in McLeod",
        "note": (
            "Source: mcleod_gld_edi_load_tender (re-ingested ~every 10 min) - the "
            "first source that can see a tender we NEVER created an order for; "
            "those shipments have no budget_report_v4 row at all - KPIs are counted "
            "at SHIPMENT grain, not row grain: one shipment carries an ORIGINAL, any "
            "number of CHANGEs and a CANCEL (up to 80 observed), so counting rows "
            "inflates volume ~77% - order_id is EMPTY STRING never NULL, and is 7 "
            "chars against v4.id's padded 8, so the join needs rpad(order_id, 8) "
            "(a bare equality matches 0 of 47,928) - status_desc and intercompany "
            "are both ~100% 'ACCEPTED' and carry no signal; acceptance is derived "
            "from order_id <> '' - purpose='CANCEL' is the same fact as "
            "cancelled_order='Y'; only order_cancelled ('we actioned it') adds "
            "information - rate/total_charge are null-or-zero on 49% of rows, so "
            "money on the exception board comes from v4.total_charge"
        ),
        "category": "Operations",
        "tags": [
            "edi", "204", "load tender", "tender", "cancellation", "cancelled",
            "shipment", "acceptance", "customer", "mcleod",
        ],
        "owner_name": "Diego",
        "roles": ["CEO", "Executive", "CORP", "DFW", "Operations", "Procurement"],
    },
    {
        "key": "dfw-losses",  # -> /reports/dfw-losses  (Bruno PDF 2026-07-20)
        "title": "DFW Losses",
        "description": "DFW loss loads: daily loads / amount lost / loss-per-load, one column per DFW customer, plus biggest-offender lanes",
        "note": "Scope: TEAM-DFW only · TMS/TMS3 · excludes UNILINK & OILTEX · Loads = count(total_charge<>0); Amount Lost = SUM(margin_amt) WHERE margin_amt<0 · source: mcleod_gld_budget_report_v4",
        "category": "Operations",
        "tags": ["dfw", "losses", "margin", "customers", "lanes", "budget", "profit"],
        "owner_name": "admin",
        "roles": ["CEO", "Executive", "DFW", "Operations", "Finance"],
    },
    {
        "key": "ops-margins",  # -> /reports/ops-margins
        "title": "OPs Margins",
        "description": "Best & worst margin lanes/customers · negative-load detail · margin trend & distribution",
        "note": "Scope: TEAM1–TEAM5 + TEAM-DFW · TMS/TMS3 · excludes UNILINK & OILTEX · cascading filters (Division/Team/Customer/Company/Origin/Destination) · source: mcleod_gld_budget_report_v4 (+ mcleod_gld_movement for carrier name)",
        "category": "Operations",
        "tags": ["margin", "ops", "lanes", "customers", "losses", "best", "worst", "concentration"],
        "owner_name": "admin",
        "roles": ["CEO", "Executive", "CORP", "DFW", "Operations", "Finance"],
    },
    {
        "key": "ops-direct-compare",  # -> /reports/ops-direct-compare
        "title": "OPs Direct Compare",
        "description": "Side-by-side period comparison: KPIs, customer & lane diff tables, 12-month trend, this-year+last-year orders",
        "note": "Two independent panels (data1 vs data2) · per-panel Date/Division/Team filters · scope TEAM1–TEAM5 + TEAM-DFW · TMS/TMS3 · excludes UNILINK & OILTEX · source: mcleod_gld_budget_report_v4 · replaces Bruno's Qlik 4a8e2ffd-…",
        "category": "Operations",
        "tags": ["compare", "ops", "margin", "period", "diff", "customers", "lanes", "trend"],
        "owner_name": "admin",
        "roles": ["CEO", "Executive", "CORP", "DFW", "Operations", "Finance"],
    },
    # Per-team private copies of OPs Direct Compare (Bruno 2026-06-26). Same
    # engine, server-locked to division=CORP + one team. Reuse the CORP-T#
    # TagRoles (one role unlocks a team's whole private suite); assigned manually.
    {
        "key": "corp-t1-direct-compare",  # -> /reports/corp-t1-direct-compare
        "title": "CORP T1 Direct Compare",
        "description": "OPs Direct Compare locked to TEAM1 — period-vs-period KPIs, customer & lane diff tables, 12-month trend, orders for TEAM1 only",
        "note": "Scope: division=CORP + team_id=TEAM1 (server-locked) · same engine as OPs Direct Compare · access strictly CORP-T1 + leadership · Bruno 2026-06-26",
        "category": "Operations",
        "tags": ["compare", "ops", "corp", "team1", "t1", "diff", "period"],
        "owner_name": "Diego",
        "roles": ["CORP-T1", "Executive"],
    },
    {
        "key": "corp-t2-direct-compare",  # -> /reports/corp-t2-direct-compare
        "title": "CORP T2 Direct Compare",
        "description": "OPs Direct Compare locked to TEAM2 — period-vs-period KPIs, customer & lane diff tables, 12-month trend, orders for TEAM2 only",
        "note": "Scope: division=CORP + team_id=TEAM2 (server-locked) · same engine as OPs Direct Compare · access strictly CORP-T2 + leadership · Bruno 2026-06-26",
        "category": "Operations",
        "tags": ["compare", "ops", "corp", "team2", "t2", "diff", "period"],
        "owner_name": "Diego",
        "roles": ["CORP-T2", "Executive"],
    },
    {
        "key": "corp-t3-direct-compare",  # -> /reports/corp-t3-direct-compare
        "title": "CORP T3 Direct Compare",
        "description": "OPs Direct Compare locked to TEAM3 — period-vs-period KPIs, customer & lane diff tables, 12-month trend, orders for TEAM3 only",
        "note": "Scope: division=CORP + team_id=TEAM3 (server-locked) · same engine as OPs Direct Compare · access strictly CORP-T3 + leadership · Bruno 2026-06-26",
        "category": "Operations",
        "tags": ["compare", "ops", "corp", "team3", "t3", "diff", "period"],
        "owner_name": "Diego",
        "roles": ["CORP-T3", "Executive"],
    },
    {
        "key": "corp-t4-direct-compare",  # -> /reports/corp-t4-direct-compare
        "title": "CORP T4 Direct Compare",
        "description": "OPs Direct Compare locked to TEAM4 — period-vs-period KPIs, customer & lane diff tables, 12-month trend, orders for TEAM4 only",
        "note": "Scope: division=CORP + team_id=TEAM4 (server-locked) · same engine as OPs Direct Compare · access strictly CORP-T4 + leadership · Bruno 2026-06-26",
        "category": "Operations",
        "tags": ["compare", "ops", "corp", "team4", "t4", "diff", "period"],
        "owner_name": "Diego",
        "roles": ["CORP-T4", "Executive"],
    },
    {
        "key": "ops-customer-score",  # -> /reports/ops-customer-score
        "title": "OPs Customer Score",
        "description": "Customer service quality: PU/DEL on-time, by team/customer/delay code, rolling 12m/10w trends, Our-Fault vs Not-Our-Fault detail",
        "note": "Scope: TEAM1–TEAM5 + TEAM-DFW · TMS/TMS3 · status D/P · source: mcleod_gld_scorecard · replaces Bruno's Qlik de4c1a28-…",
        "category": "Operations",
        "tags": ["scorecard", "ops", "service-fail", "on-time", "customer", "carrier", "pickup", "delivery"],
        "owner_name": "admin",
        "roles": ["CEO", "Executive", "CORP", "DFW", "Operations", "Finance"],
    },
    # Per-team private copies of OPs Customer Score (Bruno 2026-06-26). Same
    # engine, server-locked to division=CORP + one team. Reuse the CORP-T#
    # TagRoles; assigned manually.
    {
        "key": "corp-t1-customer-score",  # -> /reports/corp-t1-customer-score
        "title": "CORP T1 Customer Scorecard",
        "description": "OPs Customer Score locked to TEAM1 — PU/DEL on-time by customer/delay code, rolling trends, Our-Fault vs Not-Our-Fault detail for TEAM1 only",
        "note": "Scope: division=CORP + team_id=TEAM1 (server-locked) · same engine as OPs Customer Score · access strictly CORP-T1 + leadership · Bruno 2026-06-26",
        "category": "Operations",
        "tags": ["scorecard", "ops", "corp", "team1", "t1", "service-fail", "on-time"],
        "owner_name": "Diego",
        "roles": ["CORP-T1", "Executive"],
    },
    {
        "key": "corp-t2-customer-score",  # -> /reports/corp-t2-customer-score
        "title": "CORP T2 Customer Scorecard",
        "description": "OPs Customer Score locked to TEAM2 — PU/DEL on-time by customer/delay code, rolling trends, Our-Fault vs Not-Our-Fault detail for TEAM2 only",
        "note": "Scope: division=CORP + team_id=TEAM2 (server-locked) · same engine as OPs Customer Score · access strictly CORP-T2 + leadership · Bruno 2026-06-26",
        "category": "Operations",
        "tags": ["scorecard", "ops", "corp", "team2", "t2", "service-fail", "on-time"],
        "owner_name": "Diego",
        "roles": ["CORP-T2", "Executive"],
    },
    {
        "key": "corp-t3-customer-score",  # -> /reports/corp-t3-customer-score
        "title": "CORP T3 Customer Scorecard",
        "description": "OPs Customer Score locked to TEAM3 — PU/DEL on-time by customer/delay code, rolling trends, Our-Fault vs Not-Our-Fault detail for TEAM3 only",
        "note": "Scope: division=CORP + team_id=TEAM3 (server-locked) · same engine as OPs Customer Score · access strictly CORP-T3 + leadership · Bruno 2026-06-26",
        "category": "Operations",
        "tags": ["scorecard", "ops", "corp", "team3", "t3", "service-fail", "on-time"],
        "owner_name": "Diego",
        "roles": ["CORP-T3", "Executive"],
    },
    {
        "key": "corp-t4-customer-score",  # -> /reports/corp-t4-customer-score
        "title": "CORP T4 Customer Scorecard",
        "description": "OPs Customer Score locked to TEAM4 — PU/DEL on-time by customer/delay code, rolling trends, Our-Fault vs Not-Our-Fault detail for TEAM4 only",
        "note": "Scope: division=CORP + team_id=TEAM4 (server-locked) · same engine as OPs Customer Score · access strictly CORP-T4 + leadership · Bruno 2026-06-26",
        "category": "Operations",
        "tags": ["scorecard", "ops", "corp", "team4", "t4", "service-fail", "on-time"],
        "owner_name": "Diego",
        "roles": ["CORP-T4", "Executive"],
    },
    {
        "key": "sales-attrition-to-ops",  # -> /reports/sales-attrition-to-ops
        "title": "Sales- Attrition to OPs",
        "description": "Customer attrition signal: last-load date, days-since, 13-month #loads/$profit/%margin trend, 8-week sparkline per customer",
        "note": "Scope: TEAM1–TEAM5 + TEAM-DFW · TMS/TMS3 · status D/P · excludes UNILINK & OILTEX · source: mcleod_gld_budget_report_v4 · replaces Bruno's Qlik 9b669acd-…",
        "category": "Sales",
        "tags": ["attrition", "sales", "customers", "days", "margin", "profit", "loads", "sparkline"],
        "owner_name": "admin",
        "roles": ["CEO", "Executive", "Sales", "CORP", "DFW", "Operations", "Finance"],
    },
    {
        "key": "attrition-wow",  # -> /reports/attrition-wow
        "title": "Attrition WoW",
        "description": "Week-over-week attrition: active lanes/customers, reactive customers, WoW $Var, 15-week trends",
        "note": "Scope: TEAM1–TEAM5 + TEAM-DFW · TMS/TMS3 · excludes UNILINK & OILTEX · ISO Mon-Sun weeks · current week excluded · source: mcleod_gld_budget_report_v4",
        "category": "Executive",
        "tags": ["attrition", "wow", "weekly", "reactive", "lanes", "customers", "trends", "variance"],
        "owner_name": "admin",
        "roles": ["CEO", "Executive", "Sales", "CORP", "DFW", "Operations", "Finance"],
    },
    # Per-CORP-team scope-locked clones of Attrition WoW (Bruno 2026-08-14).
    # Server-locked to team_id=TEAMn in attrition_wow_team.py — the UI team
    # pills are replaced by a static badge, and a crafted ?teams= cannot widen
    # the scope. ⚠ `roles` only applies on the boot that first creates the row
    # (xmax = 0); after that /admin/reports is the sole authority (§15).
    {
        "key": "corp-t1-attrition-wow",  # -> /reports/corp-t1-attrition-wow
        "title": "CORP T1 Attrition WoW",
        "description": "Attrition WoW locked to TEAM1 — active lanes/customers, reactive customers, WoW $Var, 15-week trends for TEAM1 only",
        "note": "Scope: team_id=TEAM1 (server-locked) · same engine as Attrition WoW · no RUAN/sub-team view · Bruno 2026-08-14",
        "category": "Executive",
        "tags": ["attrition", "wow", "corp", "team1", "t1", "kam", "weekly"],
        "owner_name": "Diego",
        "roles": ["CORP KAM1", "Executive"],
    },
    {
        "key": "corp-t2-attrition-wow",  # -> /reports/corp-t2-attrition-wow
        "title": "CORP T2 Attrition WoW",
        "description": "Attrition WoW locked to TEAM2 — active lanes/customers, reactive customers, WoW $Var, 15-week trends for TEAM2 only",
        "note": "Scope: team_id=TEAM2 (server-locked) · same engine as Attrition WoW · no RUAN/sub-team view · Bruno 2026-08-14",
        "category": "Executive",
        "tags": ["attrition", "wow", "corp", "team2", "t2", "kam", "weekly"],
        "owner_name": "Diego",
        "roles": ["CORP KAM2", "Executive"],
    },
    {
        "key": "corp-t3-attrition-wow",  # -> /reports/corp-t3-attrition-wow
        "title": "CORP T3 Attrition WoW",
        "description": "Attrition WoW locked to TEAM3 — active lanes/customers, reactive customers, WoW $Var, 15-week trends for TEAM3 only",
        "note": "Scope: team_id=TEAM3 (server-locked) · same engine as Attrition WoW · no RUAN/sub-team view · Bruno 2026-08-14",
        "category": "Executive",
        "tags": ["attrition", "wow", "corp", "team3", "t3", "kam", "weekly"],
        "owner_name": "Diego",
        "roles": ["CORP KAM3", "Executive"],
    },
    {
        "key": "corp-t4-attrition-wow",  # -> /reports/corp-t4-attrition-wow
        "title": "CORP T4 Attrition WoW",
        "description": "Attrition WoW locked to TEAM4 — active lanes/customers, reactive customers, WoW $Var, 15-week trends for TEAM4 only",
        "note": "Scope: team_id=TEAM4 (server-locked) · same engine as Attrition WoW · no RUAN/sub-team view · Bruno 2026-08-14",
        "category": "Executive",
        "tags": ["attrition", "wow", "corp", "team4", "t4", "kam", "weekly"],
        "owner_name": "Diego",
        "roles": ["CORP KAM4", "Executive"],
    },
    {
        "key": "track-award-loads",  # -> /reports/track-award-loads
        "title": "Track Award Loads",
        "description": "Primary-award lane performance: awarded vs actual loads, profit, carrier cost — by Division / Customer / Award / Lane",
        "note": "Source: contract_performance_analysis (automations_db) — n8n daily 02:25 · award_status=PRIMARY · latest snapshot only · replaces Bruno's Qlik 949cafc8-… (legacy unilink.us tenant)",
        "category": "Sales",
        "tags": [
            "awards", "primary", "lanes", "profit", "carrier-cost",
            "tracker", "rfp", "contract", "performance",
        ],
        "owner_name": "admin",
        "roles": [
            "CEO", "Executive", "Sales", "Procurement",
            "Operations", "Finance", "CORP", "DFW",
        ],
    },
    {
        "key": "rfp-performance",  # -> /reports/rfp-performance
        "title": "Performance for RFPs",
        "description": "RFP submission, conversion, awarded volume & revenue tracker — Open / Closed / Lost / Won blocks, sensitivity table, last-12-mo combos, by-customer pivots",
        "note": "Source: rfp_results_history (automations_db) — n8n daily 01:00 CST · default Date filter = YTD · convertio-ratio / 12-mo combo / potential-by-month tables ignore the Date filter · replaces Bruno's Qlik 6df25048-…",
        "category": "Sales",
        "tags": [
            "rfp", "performance", "tracker", "conversion", "awarded",
            "potential-revenue", "won", "lost", "ratio", "lanes",
        ],
        "owner_name": "admin",
        "roles": [
            "CEO", "Executive", "Sales", "Procurement",
            "CORP", "DFW", "Operations", "Finance",
        ],
    },
    {
        "key": "voip-calls-logs",  # -> /reports/voip-calls-logs
        "title": "VoIP Calls Logs",
        "description": "Vonage VoIP call logs — KPIs, direction mix, daily trend, hour-of-day, DOW × hour heatmap, top users, paginated detail",
        "note": "Default WTD (with Today / Last 7d / MTD / Last Month / YTD / Custom presets) · floor 2025-01-01 · free-text search across user/extension/phone/details · source: vonage_gld_by_user · replaces Qlik 3e30136b-… · available to everyone",
        "category": "IT",
        "tags": ["voip", "vonage", "calls", "telecom", "logs", "duration", "direction", "users"],
        "owner_name": "admin",
        # All canonical TagRoles → visible to every user. Admins always bypass.
        "roles": [
            "CEO", "Executive", "Procurement", "Finance",
            "Operations", "Sales", "HR", "IT", "DFW", "CORP",
        ],
    },
    {
        "key": "carrier-risk",  # -> /reports/carrier-risk
        "title": "Risk Asss for Carriers",
        "description": "Carrier risk assessment — # carriers per lane, top-carrier share, HHI concentration, price dispersion, single-carrier lane flags",
        "note": "Source: mcleod_gld_dispatchers ⨝ mcleod_gld_budget_report_v4 · carrier_cost = override_pay_amt + driver_extra_pay (NOT total_carrier_pay) · scope TEAM1–TEAM5 + TEAM-DFW · TMS/TMS3 · status D,P · excludes UNILINK & OILTEX · replaces Qlik d7b9deb0-… (legacy unilink.us)",
        "category": "Operations",
        "tags": [
            "carrier", "risk", "concentration", "hhi", "lanes",
            "procurement", "single-carrier", "top-share",
        ],
        "owner_name": "admin",
        "roles": [
            "CEO", "Executive", "Procurement",
            "CORP", "DFW", "Operations", "Finance",
        ],
    },
    {
        "key": "it-tickets-mgmt",  # -> /reports/it-tickets-mgmt
        "title": "IT Tickets Mgmt",
        "description": "FreshService IT tickets — Service Request / Incident KPIs, status & priority mix, agent assignments, pending/closed details",
        "note": "Type tabs (Service Request / Incident) · default Last 30d (Today / WTD / Last 7d / MTD / Last Month / YTD / Custom) · excludes Onboarding/Offboarding/Cancelled/Test (IT) · status code 6→In Progress, 8→Waiting for user response · agents joined via ResponderId (Bruno's PDF JOIN was on Id=Id which matches 0 rows — corrected) · source: fresh_services_unlk.\"Tickets\" + \"Agents\" (Spark ETL) · replaces Qlik 86da731f-… · available to everyone",
        "category": "IT",
        "tags": [
            "it", "service-desk", "incidents", "tickets", "freshservice",
            "agents", "categories", "priority", "sla",
        ],
        "owner_name": "admin",
        # All canonical TagRoles → visible to every user. Admins always bypass.
        "roles": [
            "CEO", "Executive", "Procurement", "Finance",
            "Operations", "Sales", "HR", "IT", "DFW", "CORP",
        ],
    },
    {
        "key": "ops-portal-overview",  # -> /reports/ops-portal-overview
        "title": "Ops Portal - Overview",
        "description": "Single-page Ops landing: Production+Budget+Savings merged — KPI combo, Team Budget Variance, Customer Variance, Customer Losses, Team Performance, Team Projection + per-customer Actuals",
        "note": "Round 1 (2026-05-10) · CORP scope (excludes TEAM-DFW) · TEAM1-5 + Customer typeahead filters · merges xray-corp-mng (Production), budget-followup-2026 (Budget) and esavings-carriers (Savings) · combo chart + Projected-TM ignore Date filter · sources: mcleod_gld_budget_report_v4 + mcleod_gld_scorecard + daily_production_budget_report + carriers_savings_results_report (all on aivn_datalake_gold)",
        "category": "Operations",
        "tags": [
            "ops", "overview", "landing", "kpi", "combo",
            "budget", "production", "savings", "variance",
            "projection", "loss", "actuals",
        ],
        "owner_name": "admin",
        "roles": ["CEO", "Executive", "CORP", "Operations"],
    },
    # The DFW DIVISION copy of Ops Portal Overview (Bruno PDF 2026-08-20).
    # Not a scope-LOCKED clone like the four CORP-T entries below: it covers
    # the whole DFW division, with TM1..TM5 as its team dimension (they live in
    # `v4.team`, since `team_id` is the constant 'TEAM-DFW' there).
    # ⚠ `title` must stay byte-identical to the REPORT_MAP key in
    # ReportIcons.tsx — the icon lookup is by title, not by key. The dash is an
    # EN DASH (–), matching the PDF.
    {
        "key": "ops-managers-portal-dfw",  # -> /reports/ops-managers-portal-dfw
        "title": "Ops Managers Portal – DFW",
        "description": "Ops Portal Overview for the DFW division — KPI combo, customer month-over-month variance, losses, performance, projection, actuals, by-lane, by-order and the unbilled board, with TM1–TM5 as the team dimension",
        "note": "Scope: team_id=TEAM-DFW (server-pinned); team column = v4.team (TM1–TM5) · same engine as Ops Portal - Overview · NO budget panels: 0 of DFW's 15 YTD customers exist in daily_production_budget_report, so BDGT, Team Budget Monthly Variance and the All/Budget/Variance-per-Cell modes are removed and Customer Monthly Variance is last-month minus this-month · Bruno 2026-08-20",
        "category": "Operations",
        "tags": ["ops", "overview", "dfw", "tm1", "tm2", "tm3", "tm4", "kpi", "division"],
        "owner_name": "Diego",
        # Seed roles apply only on FIRST creation (xmax=0); live access is
        # managed in /admin/reports. Mirrors the DFW grants on XRay DFW Mng.
        "roles": ["DFW", "Executive", "CEO", "Operations"],
    },
    # Per-team private copies of Ops Portal Overview (Bruno 2026-06-26, PDF
    # Request 1). Same engine as ops-portal-overview but server-locked to one
    # CORP team so a team's KAMs can't see other teams' work or customers.
    {
        "key": "corp-t1-ops-kam-portal",  # -> /reports/corp-t1-ops-kam-portal
        "title": "CORP T1 OPS Kam Portal",
        "description": "Ops Portal Overview locked to TEAM1 — KPI combo, variances, losses, performance, projection, actuals, by-lane and by-order for TEAM1 only",
        "note": "Scope: team_id=TEAM1 (server-locked) · same engine as Ops Portal - Overview · access strictly CORP-T1 + leadership · Bruno 2026-06-26",
        "category": "Operations",
        "tags": ["ops", "overview", "corp", "team1", "t1", "kam", "kpi"],
        "owner_name": "Diego",
        "roles": ["CORP-T1", "Executive"],
    },
    {
        "key": "corp-t2-ops-kam-portal",  # -> /reports/corp-t2-ops-kam-portal
        "title": "CORP T2 OPS Kam Portal",
        "description": "Ops Portal Overview locked to TEAM2 — KPI combo, variances, losses, performance, projection, actuals, by-lane and by-order for TEAM2 only",
        "note": "Scope: team_id=TEAM2 (server-locked) · same engine as Ops Portal - Overview · access strictly CORP-T2 + leadership · Bruno 2026-06-26",
        "category": "Operations",
        "tags": ["ops", "overview", "corp", "team2", "t2", "kam", "kpi"],
        "owner_name": "Diego",
        "roles": ["CORP-T2", "Executive"],
    },
    {
        "key": "corp-t3-ops-kam-portal",  # -> /reports/corp-t3-ops-kam-portal
        "title": "CORP T3 OPS Kam Portal",
        "description": "Ops Portal Overview locked to TEAM3 — KPI combo, variances, losses, performance, projection, actuals, by-lane and by-order for TEAM3 only",
        "note": "Scope: team_id=TEAM3 (server-locked) · same engine as Ops Portal - Overview · access strictly CORP-T3 + leadership · Bruno 2026-06-26",
        "category": "Operations",
        "tags": ["ops", "overview", "corp", "team3", "t3", "kam", "kpi"],
        "owner_name": "Diego",
        "roles": ["CORP-T3", "Executive"],
    },
    {
        "key": "corp-t4-ops-kam-portal",  # -> /reports/corp-t4-ops-kam-portal
        "title": "CORP T4 OPS Kam Portal",
        "description": "Ops Portal Overview locked to TEAM4 — KPI combo, variances, losses, performance, projection, actuals, by-lane and by-order for TEAM4 only",
        "note": "Scope: team_id=TEAM4 (server-locked) · same engine as Ops Portal - Overview · access strictly CORP-T4 + leadership · Bruno 2026-06-26",
        "category": "Operations",
        "tags": ["ops", "overview", "corp", "team4", "t4", "kam", "kpi"],
        "owner_name": "Diego",
        "roles": ["CORP-T4", "Executive"],
    },
    {
        "key": "kam-performance-dfw",  # -> /reports/kam-performance-dfw
        "title": "KAM Performance - DFW",
        "description": "Per-KAM scratchpad: scorecard log, current-week service KPIs (OTP/OTD from ops-customer-score), top-10 lanes (xray-dfw-mng), customer development and team development tables",
        "note": "Per-user editable rows in kam_scorecards / kam_customer_dev / kam_team_dev / kam_top_lanes_notes · Tab 1 metadata-only (no file blob) · Tab 2 calls ops-customer-score with division=DFW · Tab 3 calls xray-dfw-mng /by-lane limit=10 · scope: TEAM-DFW",
        "category": "Sales",
        "tags": [
            "kam", "dfw", "scorecard", "service", "otp", "otd",
            "lanes", "customer-development", "team-development",
        ],
        "owner_name": "Diego",
        # DFW KAM1–4 added Bruno PDF 2026-07-20 (view+edit). NB: seed roles apply
        # only on first creation (xmax=0) — the live grant on this existing report
        # is applied directly to role_report_access; this list documents intent
        # and seeds any fresh environment.
        "roles": ["CEO", "Executive", "DFW", "Operations", "Sales",
                  "DFW KAM1", "DFW KAM2", "DFW KAM3", "DFW KAM4"],
    },
    # DFW copy of the Bonus Calculator (Bruno PDF "space --Bonus HR",
    # 2026-08-20). Same engine and same rules; only the MARGIN ladder differs
    # (15/16/17/18/19% -> 70/90/100/110/120%) and it computes over TEAM-DFW's
    # TM1-TM4 instead of TEAM1-TEAM4.
    # ⚠ Its roster/afterhours/FX/lock/history live in SEPARATE `bonus_dfw_*`
    # tables — bonus_settings and bonus_period_lock are PK'd on period_key
    # alone, so sharing them would let this report overwrite corporate payroll.
    # ⚠ The roster starts EMPTY: HR must add DFW employees and salaries before
    # this report shows a payout.
    {
        "key": "bonus-calculator-dfw",  # -> /reports/bonus-calculator-dfw
        "title": "Bonus Calculator – DFW",
        "description": "DFW operations bonus payouts by team & employee — KAM/Freight-Match/Tracking&Tracing brackets, wildcard, monthly profit add-ons and Afterhours averaging, on the DFW margin ladder (15/16/17/18/19%)",
        "note": "CEO + HR Manager + OPs Manager only (mirrors the corporate calculator) · scope team_id=TEAM-DFW, sub-teams TM1-TM4 · MARGIN bracket 15%/70 · 16%/90 · 17%/100 · 18%/110 · 19%/120 (corporate is 18.5/20/21/22/23 -> 70/100/110/120/130) · load, service and profit ladders and the $2.00/$1.60 per-load rates are UNCHANGED · own bonus_dfw_* tables · Bruno 2026-08-20",
        "category": "Executive",
        "tags": ["bonus", "hr", "payroll", "dfw", "kam", "freight-match", "tracking-tracing", "wildcard"],
        "owner_name": "Diego",
        # Seed roles apply only on FIRST creation (xmax=0); live access is
        # managed in /admin/reports. Mirrors the corporate calculator's grant.
        "roles": ["CEO", "HR Manager", "OPs Manager"],
    },
    {
        "key": "bonus-calculator",  # -> /reports/bonus-calculator
        "title": "Bonus Calculator",
        "description": "Corporate operations bonus payouts by team & employee — KAM/Freight-Match/Tracking&Tracing brackets, wildcard, monthly profit add-ons, Team-1 KAM and Afterhours averaging",
        "note": "CEO + HR Manager + OPs Manager only (Bruno 2026-07-06: individual roles, NOT whole HR/Operations divisions) · 6th->6th period · live datalake (mcleod_gld_budget_report_v4 + scorecard, same as xray-corp-mng) · HR board-pinned FX (team + night) · HR-editable roster/afterhours · month-lock approval · scope TEAM1–TEAM4 · port of Bruno's HR-Headquarters bonus module (2026-05-24)",
        "category": "Executive",
        "tags": ["bonus", "hr", "payroll", "kam", "freight-match", "tracking-tracing", "wildcard", "corporate"],
        "owner_name": "Diego",
        # Seed roles apply only on FIRST creation (xmax=0); live access is managed
        # in /admin/reports. Kept in sync w/ 2026-07-06 grant: CEO + the 2 manager roles.
        "roles": ["CEO", "HR Manager", "OPs Manager"],
    },
    {
        "key": "division-payment-calculator",  # -> /reports/division-payment-calculator
        "title": "Division Payment Calculator",
        "description": "Monthly payment owed to the A&O division — profit, GL deductions, tariff, corporate gain and net payment, with approved archives and TMS recalculations",
        "note": "Portal-owned data (dpc_* tables), NOT a datalake report: A&O's GL lines live in the accounting system and the PDF specifies Revenue / Carrier Cost as operator inputs · Net Payment = Profit − GL Deductions − Corporate Gain · Corporate Gain = 25% of profit + tariff · tariff charged only when margin < 10%, and it sits INSIDE corporate gain (subtracted once, not twice) · a recalculation's profit delta splits 25% Corporate / 75% A&O with the tariff frozen from the approved archive · 3 tabs (Dashboard / Calculator / Recalculations) · seeded with 2026 Jan–Jul + 2025 Jan–Dec (Bruno PDF 2026-08-13)",
        "category": "Finance",
        "tags": [
            "division", "payment", "a&o", "gl", "deductions", "tariff",
            "corporate-gain", "recalculation", "refacturacion", "finance",
        ],
        "owner_name": "Diego",
        # Seed roles apply only on FIRST creation (xmax=0) — §15. Live access is
        # managed at /admin/reports. Financial payout detail: exec + finance only.
        "roles": ["CEO", "Executive", "Finance"],
    },
    {
        "key": "admin-cashflow",  # -> /reports/admin-cashflow
        "title": "Admin Aging Cashflow",
        "description": "A/R cashflow discipline — delivery-vs-bill / BOL-vs-bill / carrier-invoice-vs-bill aging, delivered-not-billed and ready-not-billed inventory",
        "note": "Source: mcleod_gld_cashflow (Spark ETL, no n8n) · scope TEAM1–TEAM5 + TEAM-DFW · TMS/TMS3 · status D,P · default MTD (Today / WTD / Last 7d / MTD / Last Month / YTD / Custom) · 12-week sparklines on the 3 % KPIs · aging-buckets chart + top-delayed-customers leaderboard · banner when delivered+ready unbilled > $3M · real calendar-day diff (a::date - b::date), not Qlik's day() function · replaces Bruno's legacy Admin CashFlow Qlik dashboard",
        "category": "Finance",
        "tags": [
            "cashflow", "aging", "billing", "ar", "discipline",
            "unbilled", "delivery", "bol", "invoice", "admin",
        ],
        "owner_name": "admin",
        "roles": [
            "CEO", "Executive", "Finance",
            "CORP", "DFW", "Operations",
            "AdminFinance",
        ],
    },
    {
        "key": "reports-index",  # -> /reports/reports-index
        "title": "Reports Index",
        "description": "Leadership directory of every report — name, summary + main KPIs + intended audience, and links to the report plus related reports",
        "note": "Read-only catalog · full active catalog (all reports, not viewer-filtered) · audience = each report's assigned TagRoles · KPIs + related links curated in lib/reports-index-api.ts · access: CEO + Executive",
        "category": "Executive",
        "tags": ["index", "directory", "catalog", "reports", "leadership", "guide", "toc"],
        "owner_name": "Diego",
        "roles": ["CEO", "Executive"],
    },
    {
        "key": "carrier-sms-score",  # -> /reports/carrier-sms-score
        "title": "Carrier SMS Score",
        "description": "Carrier safety roster — name, location, Vehicle/Driver Out-of-Service rates vs national average, the 5 FMCSA BASIC measures, and the final MyCarrierPortal (MCP) risk verdict, all sortable/searchable with CSV export",
        "note": "Source: unilink_portal_ap.carriers ⨝ fmcsa_sms_data (LEFT JOIN on dot_number) · first portal report on the AP_module DB (AP_DATABASE_URL, 5th external pool) · default active carriers only · Nat'l OOS avg Vehicle 23.2% / Driver 6.4% · BASIC amber ≥50, red ≥75 · 'Flagged only' = above either OOS avg or any BASIC ≥75 · header-click sort + search + server-streamed CSV (full filter) + row-select CSV · mirrors the AP app's /dashboard/admin/carriers Safety + MCP cards",
        "category": "Procurement",
        "tags": [
            "carrier", "sms", "safety", "fmcsa", "basic", "oos",
            "out-of-service", "mcp", "risk", "compliance", "procurement",
        ],
        "owner_name": "admin",
        # Managers only — CEO + Executive (admins always bypass). Set per Diego
        # 2026-05-29. NOTE: seed only ADDS roles (ON CONFLICT DO NOTHING); the
        # first deploy seeded a wider set, so the live narrowing was done in the
        # admin UI (/admin/reports) — the single source of truth.
        "roles": ["CEO", "Executive"],
    },
    {
        "key": "exec-meeting-recruitment",  # -> /reports/exec-meeting-recruitment
        "title": "Exec Meeting – Recruitment",
        "description": "Recruitment pack for the exec meeting — active headcount and open vacancies, year-by-year new hires vs offboarding, a per-employee hire-to-exit timeline, and every open role with its age",
        "note": "Two read-only sources, merged in Python (separate DBs, no join): timeoff_at_unilink_portal.users (role spaceqlik_timeoff_ro) for headcount / new hires / people flow, and recruit_unilink \"Position\" + \"FreshServiceTicket\" (role spaceqlik_recruit_ro) for open roles and exits · New hires = time-off \"hireDate\", matching the Jobs portal's Human Capital dashboard, and prior years are UNDERCOUNTS because departed staff age out of that table (2024 25% / 2025 62% / 2026 89% coverage vs FS Onboarding, measured 2026-08-17) — the panel captions this · Exits = FS Offboarding tickets, never time-off \"leaveDate\" (51% of inactive rows have it NULL and it records zero 2026 exits) · §03 People Flow is the one panel using \"leaveDate\", because no reliable key joins a person to an FS ticket, so its exit markers deliberately do NOT tie to the §02 Offboarding KPI · Open Vacancies = SUM(GREATEST(0, vacancies - hiredCount)) over ACTIVE positions, so it exceeds the row count in §05 by design · turnover shown for the current year only (past-year headcount is not reconstructable) · Bruno PDF 2026-08-17",
        "category": "HR",
        "tags": [
            "recruitment", "hr", "headcount", "hiring", "new-hires",
            "offboarding", "turnover", "open-roles", "vacancies",
            "people-flow", "exec", "timeline",
        ],
        "owner_name": "Diego",
        # Seed roles apply only on FIRST creation (xmax=0) — §15; after that
        # /admin/reports is the sole authority. Set per Diego 2026-08-17:
        # HR division + Daniela's individual HR Manager role + CEO.
        "roles": ["HR", "HR Manager", "CEO"],
    },
]

# (Qlik desktop/mobile report seed lists removed 2026-05-28 — Qlik fully
# decommissioned; the portal now serves only code-made CUSTOM_REPORTS.)

# Admin users get admin + executive roles
ADMIN_EMAILS = [
    "dfrodriguez@unilinktransportation.com",
    "kmeneses@unilinktransportation.com",
    "msalazarm@unilinktransportation.com",
    "dcastrog@unilinktransportation.com",
]

# Department → role mapping for auto-assignment
DEPT_ROLE_MAP = {
    "Sales": "sales",
    "Finance": "finance",
    "Accounting": "finance",
    "HR": "hr",
    "Human": "hr",
    "IT": "it",
    "Tech": "it",
    "Operations": "operations",
    "Ops": "operations",
}


async def dedupe_roles(pool) -> list[dict]:
    """Merge case-insensitive duplicate rows in `roles` into a single canonical row.

    Keeps Title-Case over lowercase (the Title-Case row was created first by admins
    via /admin/roles; the lowercase duplicates came from an earlier seed pass).
    Re-assigns every `user_roles` and `role_report_access` reference from the loser
    onto the keeper before deleting the loser row.

    Returns a list of {kept, removed} records for auditing.
    """
    dupes = await pool.fetch(
        """
        SELECT LOWER(name) AS lname
        FROM roles
        GROUP BY LOWER(name)
        HAVING COUNT(*) > 1
        """
    )
    merged = []
    for d in dupes:
        variants = await pool.fetch(
            """
            SELECT id, name
            FROM roles
            WHERE LOWER(name) = $1
            ORDER BY (name != LOWER(name)) DESC, name ASC
            """,
            d["lname"],
        )
        # variants[0] is the keeper (Title-Case sorts first)
        keeper = variants[0]
        for loser in variants[1:]:
            await pool.execute(
                """
                INSERT INTO role_report_access (role_id, report_id)
                SELECT $1, report_id FROM role_report_access WHERE role_id = $2
                ON CONFLICT DO NOTHING
                """,
                keeper["id"],
                loser["id"],
            )
            await pool.execute(
                """
                INSERT INTO user_roles (user_id, role_id)
                SELECT user_id, $1 FROM user_roles WHERE role_id = $2
                ON CONFLICT DO NOTHING
                """,
                keeper["id"],
                loser["id"],
            )
            # app_role_access too (if the app grants the role)
            await pool.execute(
                """
                INSERT INTO app_role_access (role_id, app_id)
                SELECT $1, app_id FROM app_role_access WHERE role_id = $2
                ON CONFLICT DO NOTHING
                """,
                keeper["id"],
                loser["id"],
            )
            # Drop loser refs, then loser row. ON DELETE CASCADE would also work
            # but being explicit avoids surprises if constraints change.
            await pool.execute(
                "DELETE FROM role_report_access WHERE role_id = $1", loser["id"]
            )
            await pool.execute(
                "DELETE FROM user_roles WHERE role_id = $1", loser["id"]
            )
            await pool.execute(
                "DELETE FROM app_role_access WHERE role_id = $1", loser["id"]
            )
            await pool.execute("DELETE FROM roles WHERE id = $1", loser["id"])
            merged.append({"kept": keeper["name"], "removed": loser["name"]})
    return merged


async def seed_custom_reports(pool) -> int:
    """Insert/update every row in ``CUSTOM_REPORTS`` against the shared pool.

    Runs on every backend startup so new code-made reports added to the
    ``CUSTOM_REPORTS`` list ship automatically — the original ``seed_all``
    only fires when ``role_report_access`` is empty, which means new
    custom reports never made it into the DB on subsequent deploys.

    The INSERT uses ``ON CONFLICT (custom_path) DO UPDATE`` so this is
    safe to call on every boot — existing rows get title/description/
    tags/category refreshed, missing rows get created.

    Role mappings are seeded **only the first time a report is created**
    (detected via ``xmax = 0`` on the RETURNING row). Once a report exists,
    the admin UI (/admin/reports) is the single source of truth for its
    TagRole access — seed never re-adds a role on subsequent deploys. This
    is what stops manually-removed grants (e.g. a report taken out of the
    "CEO" TagRole) from silently reappearing on the next deploy. A brand-new
    report still ships with its seed-declared roles on the boot that creates
    it; remove a role from the seed list to keep it out from day one.

    Returns the number of CUSTOM_REPORTS entries processed (for logs).
    """
    # Make sure the schema pieces we need exist. These are no-ops on a
    # fully-migrated DB but keep this function runnable standalone.
    await pool.execute(
        "ALTER TABLE reports ADD COLUMN IF NOT EXISTS report_type TEXT DEFAULT 'qlik'"
    )
    await pool.execute(
        "ALTER TABLE reports ADD COLUMN IF NOT EXISTS custom_path TEXT"
    )
    await pool.execute(
        "ALTER TABLE reports ALTER COLUMN qlik_app_id DROP NOT NULL"
    )
    await pool.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS reports_custom_path_key
        ON reports (custom_path)
        WHERE custom_path IS NOT NULL
        """
    )

    # Build a case-insensitive lookup of existing roles so we can map
    # role names from CUSTOM_REPORTS regardless of their casing in DB.
    role_rows = await pool.fetch("SELECT id, name FROM roles")
    role_ids_ci = {r["name"].lower(): r["id"] for r in role_rows}

    for custom in CUSTOM_REPORTS:
        custom_path = f"/reports/{custom['key']}"
        row = await pool.fetchrow(
            """
            INSERT INTO reports (title, description, note, category, tags,
                                 owner_name, is_mobile, report_type, custom_path)
            VALUES ($1, $2, $3, $4, $5, $6, FALSE, 'custom', $7)
            ON CONFLICT (custom_path) WHERE custom_path IS NOT NULL DO UPDATE SET
              title = EXCLUDED.title,
              description = EXCLUDED.description,
              note = EXCLUDED.note,
              category = EXCLUDED.category,
              tags = EXCLUDED.tags,
              owner_name = EXCLUDED.owner_name,
              report_type = 'custom'
            RETURNING id, (xmax = 0) AS inserted
            """,
            custom["title"],
            custom.get("description"),
            custom.get("note"),
            custom.get("category"),
            custom.get("tags", []),
            custom.get("owner_name"),
            custom_path,
        )
        # Seed roles ONLY on the boot that first creates the report. For an
        # already-existing report, the admin UI owns TagRole access — never
        # re-add a seed role (that would revert manual removals every deploy).
        if row and row["inserted"]:
            for role_name in custom.get("roles", []):
                role_id = role_ids_ci.get(role_name.lower())
                if role_id:
                    await pool.execute(
                        """
                        INSERT INTO role_report_access (role_id, report_id)
                        VALUES ($1, $2) ON CONFLICT DO NOTHING
                        """,
                        role_id,
                        row["id"],
                    )
    return len(CUSTOM_REPORTS)


async def seed_all():
    pool = await asyncpg.create_pool(settings.DATABASE_URL, min_size=1, max_size=3)

    try:
        # 0a. Merge any case-duplicate roles before we touch role_report_access
        await dedupe_roles(pool)

        # Make sure custom_path exists before we try to index it
        await pool.execute(
            "ALTER TABLE reports ADD COLUMN IF NOT EXISTS report_type TEXT DEFAULT 'qlik'"
        )
        await pool.execute(
            "ALTER TABLE reports ADD COLUMN IF NOT EXISTS custom_path TEXT"
        )
        await pool.execute(
            "ALTER TABLE reports ALTER COLUMN qlik_app_id DROP NOT NULL"
        )
        await pool.execute(
            """
            CREATE UNIQUE INDEX IF NOT EXISTS reports_custom_path_key
            ON reports (custom_path)
            WHERE custom_path IS NOT NULL
            """
        )

        # Add is_mobile column if it doesn't exist
        await pool.execute(
            """
            ALTER TABLE reports ADD COLUMN IF NOT EXISTS is_mobile BOOLEAN DEFAULT FALSE
            """
        )

        # Create apps table if it doesn't exist
        await pool.execute(
            """
            CREATE TABLE IF NOT EXISTS apps (
              id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
              title       TEXT NOT NULL,
              url         TEXT NOT NULL,
              description TEXT,
              is_active   BOOLEAN DEFAULT TRUE,
              created_at  TIMESTAMPTZ DEFAULT NOW(),
              updated_at  TIMESTAMPTZ DEFAULT NOW()
            )
            """
        )

        # Create app_role_access junction table if it doesn't exist
        await pool.execute(
            """
            CREATE TABLE IF NOT EXISTS app_role_access (
              role_id  UUID REFERENCES roles(id) ON DELETE CASCADE,
              app_id   UUID REFERENCES apps(id) ON DELETE CASCADE,
              PRIMARY KEY (role_id, app_id)
            )
            """
        )

        # 1. Seed roles
        role_ids = {}
        for name, description in DEFAULT_ROLES:
            row = await pool.fetchrow(
                """
                INSERT INTO roles (name, description)
                VALUES ($1, $2)
                ON CONFLICT (name) DO UPDATE SET description = $2
                RETURNING id
                """,
                name,
                description,
            )
            role_ids[name] = row["id"]

        # Case-insensitive role lookup — CUSTOM_REPORTS use lowercase role keys
        # (e.g. "executive", "dfw") while role_ids stores Title-Case names.
        role_ids_ci = {k.lower(): v for k, v in role_ids.items()}

        # 2. Seed code-made (custom) reports. Keyed by custom_path so they're idempotent.
        for custom in CUSTOM_REPORTS:
            custom_path = f"/reports/{custom['key']}"
            row = await pool.fetchrow(
                """
                INSERT INTO reports (title, description, note, category, tags,
                                     owner_name, is_mobile, report_type, custom_path)
                VALUES ($1, $2, $3, $4, $5, $6, FALSE, 'custom', $7)
                ON CONFLICT (custom_path) WHERE custom_path IS NOT NULL DO UPDATE SET
                  title = EXCLUDED.title,
                  description = EXCLUDED.description,
                  note = EXCLUDED.note,
                  category = EXCLUDED.category,
                  tags = EXCLUDED.tags,
                  owner_name = EXCLUDED.owner_name,
                  report_type = 'custom'
                RETURNING id
                """,
                custom["title"],
                custom.get("description"),
                custom.get("note"),
                custom.get("category"),
                custom.get("tags", []),
                custom.get("owner_name"),
                custom_path,
            )
            if row:
                for role_name in custom.get("roles", []):
                    role_id = role_ids_ci.get(role_name.lower())
                    if role_id:
                        await pool.execute(
                            """
                            INSERT INTO role_report_access (role_id, report_id)
                            VALUES ($1, $2) ON CONFLICT DO NOTHING
                            """,
                            role_id,
                            row["id"],
                        )

        # 3. Seed users from time-off DB (if available)
        if settings.TIMEOFF_DATABASE_URL:
            await _seed_users_from_timeoff(pool, role_ids_ci)

        # 4. Assign admin + executive roles to admin users
        for admin_email in ADMIN_EMAILS:
            user_row = await pool.fetchrow(
                "SELECT id FROM users WHERE email = $1", admin_email
            )
            if user_row:
                for role_name in ("admin", "executive"):
                    role_id = role_ids_ci.get(role_name)
                    if role_id:
                        await pool.execute(
                            """
                            INSERT INTO user_roles (user_id, role_id)
                            VALUES ($1, $2) ON CONFLICT DO NOTHING
                            """,
                            user_row["id"],
                            role_id,
                        )

    finally:
        await pool.close()


async def _seed_users_from_timeoff(pool, role_ids_ci: dict[str, UUID]):
    """Seed users from the time-off system database. `role_ids_ci` is a
    case-insensitive dict (lowercased keys) so lookups work regardless of
    whether a role was created lowercase or Title-Case."""
    timeoff_pool = await asyncpg.create_pool(
        settings.TIMEOFF_DATABASE_URL, min_size=1, max_size=2
    )

    try:
        employees = await timeoff_pool.fetch(
            """
            SELECT "email", "name", "firstName", "lastName", "department",
                   "jobTitle", "companyName", "role", "roleLevel"
            FROM users
            WHERE "isActive" = true
            """
        )

        for emp in employees:
            email = emp["email"]
            if not email:
                continue

            # Prefer "name" field; fall back to firstName + lastName
            full_name = emp["name"] or ""
            if not full_name.strip():
                first = emp["firstName"] or ""
                last = emp["lastName"] or ""
                full_name = f"{first} {last}"
            name = full_name.strip()

            user_row = await pool.fetchrow(
                """
                INSERT INTO users (email, name, department, job_title, company)
                VALUES ($1, $2, $3, $4, $5)
                ON CONFLICT (email) DO UPDATE SET
                  name = $2, department = $3, job_title = $4, company = $5
                RETURNING id
                """,
                email.lower(),
                name,
                emp["department"],
                emp["jobTitle"],
                emp["companyName"],
            )

            user_id = user_row["id"]
            dept = emp["department"] or ""

            # Auto-assign roles based on department (case-insensitive lookup)
            for keyword, role_name in DEPT_ROLE_MAP.items():
                role_id = role_ids_ci.get(role_name.lower())
                if keyword.lower() in dept.lower() and role_id:
                    await pool.execute(
                        """
                        INSERT INTO user_roles (user_id, role_id)
                        VALUES ($1, $2) ON CONFLICT DO NOTHING
                        """,
                        user_id,
                        role_id,
                    )

            # Directors/Owners also get executive role
            role_level = emp["roleLevel"] or ""
            exec_id = role_ids_ci.get("executive")
            if role_level.upper() in ("OWNER", "DIRECTOR") and exec_id:
                await pool.execute(
                    """
                    INSERT INTO user_roles (user_id, role_id)
                    VALUES ($1, $2) ON CONFLICT DO NOTHING
                    """,
                    user_id,
                    exec_id,
                )

    finally:
        await timeoff_pool.close()


if __name__ == "__main__":
    asyncio.run(seed_all())
