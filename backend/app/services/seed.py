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
        "roles": ["DFW-TM1", "CEO", "Executive"],
    },
    {
        "key": "xray-dfw-tm2",  # -> /reports/xray-dfw-tm2
        "title": "XRay DFW TM2",
        "description": "XRay DFW Mng locked to TM2 — KPIs, lanes, trends, risk and contract/spot split for TM2 only",
        "note": "Scope: TEAM-DFW + team=TM2 (server-locked) · same engine as XRay DFW Mng · access strictly DFW-TM2 + leadership",
        "category": "Executive",
        "tags": ["dfw", "tm2", "x-ray", "management", "kpi", "otp", "otd"],
        "owner_name": "Diego",
        "roles": ["DFW-TM2", "CEO", "Executive"],
    },
    {
        "key": "xray-dfw-tm3",  # -> /reports/xray-dfw-tm3
        "title": "XRay DFW TM3",
        "description": "XRay DFW Mng locked to TM3 — KPIs, lanes, trends, risk and contract/spot split for TM3 only",
        "note": "Scope: TEAM-DFW + team=TM3 (server-locked) · same engine as XRay DFW Mng · access strictly DFW-TM3 + leadership",
        "category": "Executive",
        "tags": ["dfw", "tm3", "x-ray", "management", "kpi", "otp", "otd"],
        "owner_name": "Diego",
        "roles": ["DFW-TM3", "CEO", "Executive"],
    },
    {
        "key": "xray-dfw-tm4",  # -> /reports/xray-dfw-tm4
        "title": "XRay DFW TM4",
        "description": "XRay DFW Mng locked to TM4 — KPIs, lanes, trends, risk and contract/spot split for TM4 only",
        "note": "Scope: TEAM-DFW + team=TM4 (server-locked) · same engine as XRay DFW Mng · access strictly DFW-TM4 + leadership",
        "category": "Executive",
        "tags": ["dfw", "tm4", "x-ray", "management", "kpi", "otp", "otd"],
        "owner_name": "Diego",
        "roles": ["DFW-TM4", "CEO", "Executive"],
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
        "key": "dfw-podium-top",  # -> /reports/dfw-podium-top
        "title": "DFW Podium Top",
        "description": "DFW Top-3 Bookers leaderboards — This-Week Profit / Margin / Loads + Today Loads / Profit",
        "note": "Companion to Podium Set DFW · no date filter · top-3 only · TEAM-DFW · source: order_post_hist + budget_report_v4 (same CTE as podium-dfw)",
        "category": "Operations",
        "tags": ["dfw", "podium", "top", "leaderboard", "rate-conf", "profit", "margin", "loads"],
        "owner_name": "Diego",
        "roles": ["DFW"],
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
        "roles": ["CEO", "Executive", "DFW", "Operations", "Sales"],
    },
    {
        "key": "bonus-calculator",  # -> /reports/bonus-calculator
        "title": "Bonus Calculator",
        "description": "Corporate operations bonus payouts by team & employee — KAM/Freight-Match/Tracking&Tracing brackets, wildcard, monthly profit add-ons, Team-1 KAM and Afterhours averaging",
        "note": "CEO + HR only · 6th->6th period · live datalake (mcleod_gld_budget_report_v4 + scorecard, same as xray-corp-mng) · HR board-pinned FX (team + night) · HR-editable roster/afterhours · month-lock approval · scope TEAM1–TEAM4 · port of Bruno's HR-Headquarters bonus module (2026-05-24)",
        "category": "Executive",
        "tags": ["bonus", "hr", "payroll", "kam", "freight-match", "tracking-tracing", "wildcard", "corporate"],
        "owner_name": "Diego",
        "roles": ["CEO", "HR"],
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
        "roles": [
            "CEO", "Executive", "Procurement",
            "Operations", "CORP", "DFW",
        ],
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
    tags/category refreshed, missing rows get created. Role mappings are
    inserted with ``ON CONFLICT DO NOTHING``, which preserves any
    admin-assigned overrides while ensuring at least the seed-declared
    roles can see the report.

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
