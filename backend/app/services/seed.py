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
        "roles": ["CEO", "Executive", "CORP", "DFW", "Operations", "Finance"],
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
]

# 19 desktop + 12 mobile reports
REPORTS = [
    {
        "qlik_app_id": "e4d975eb-e8ca-4727-8a9a-50db58907ef7",
        "qlik_sheet_id": "238b3a1a-ca98-4c67-92ca-826e3c5b67ab",
        "title": "Executive Report",
        "description": "All-teams KPIs: revenue, loads, profit, margin",
        "category": "Executive",
        "tags": ["revenue", "profit", "margin", "loads", "kpi"],
        "owner_name": "Melany",
        "roles": ["executive", "dfw", "corp"],
    },
    {
        "qlik_app_id": "4a8e2ffd-b049-4853-b716-195d568aaf11",
        "qlik_sheet_id": "ab318e19-d514-4134-b809-5f0a808a97db",
        "title": "DIRECT COMPARE",
        "description": "Side-by-side comparison of divisions and time periods",
        "category": "Executive",
        "tags": ["comparison", "divisions", "analysis"],
        "owner_name": "Melany",
        "roles": ["executive", "dfw", "corp"],
    },
    {
        "qlik_app_id": "7d9b7063-a626-4a8e-b45c-adf8d70cd8e8",
        "qlik_sheet_id": "5af93eec-2371-42d8-9b47-6e2403cdc3db",
        "title": "DFW Executive Report",
        "description": "DFW division executive KPIs and performance metrics",
        "category": "Executive",
        "tags": ["dfw", "kpi", "executive"],
        "owner_name": "Melany",
        "roles": ["executive", "dfw"],
    },
    {
        "qlik_app_id": "9c709f27-30ec-4fb2-bd21-8a2db49426ac",
        "qlik_sheet_id": "0ced6dcb-1cd8-4843-a3c7-68a364e46aac",
        "title": "DFW X-RAY",
        "description": "Detailed DFW division drill-down analysis",
        "category": "Executive",
        "tags": ["dfw", "x-ray", "analysis"],
        "owner_name": "Melany",
        "roles": ["executive", "dfw"],
    },
    {
        "qlik_app_id": "4b45853f-057b-4710-a4b8-38a98856cd5e",
        "qlik_sheet_id": "d5d95d43-0cd4-4553-acb8-96a79f5ac1f5",
        "title": "CORP X-RAY",
        "description": "Detailed CORP division drill-down analysis",
        "category": "Executive",
        "tags": ["corp", "x-ray", "analysis"],
        "owner_name": "Melany",
        "roles": ["executive", "corp"],
    },
    {
        "qlik_app_id": "45fbe2ad-ef79-40a3-89ff-37ca6ddf64fb",
        "qlik_sheet_id": "b6711d0b-be56-4f2d-8c0c-35fff13480d9",
        "title": "Budget Follow-up",
        "description": "Budget tracking and follow-up across departments",
        "category": "Finance",
        "tags": ["budget", "finance", "tracking"],
        "owner_name": "Melany",
        "roles": ["executive", "finance"],
    },
    {
        "qlik_app_id": "3abf5bb5-557a-437c-8813-ba128eb83f9b",
        "qlik_sheet_id": "gNtJ",
        "title": "Budget - Sales",
        "description": "Sales team budget performance and variance analysis",
        "category": "Finance",
        "tags": ["budget", "sales", "variance"],
        "owner_name": "Melany",
        "roles": ["executive", "finance", "sales"],
    },
    # NOTE: "Customer Scorecard" (app de4c1a28-…) was migrated to a code-made
    # report on 2026-04-26. See CUSTOM_REPORTS (key=ops-customer-score) and the
    # one-time row-flip in main.py lifespan. Do not re-add it here.
    {
        "qlik_app_id": "a12b7dea-9226-40a8-b0ef-ba8e8d9087b8",
        "qlik_sheet_id": "e332c952-ad92-4625-b2b6-eec3347cd8ba",
        "title": "Carrier Savings Dashboard",
        "description": "Carrier procurement savings and cost analysis",
        "category": "Operations",
        "tags": ["carrier", "savings", "procurement"],
        "owner_name": "Melany",
        "roles": ["executive", "operations"],
    },
    {
        "qlik_app_id": "9ba464ca-b42f-43bd-86cc-fbda730f881b",
        "qlik_sheet_id": "MygcmP",
        "title": "Available",
        "description": "Available capacity and operations overview",
        "category": "Operations",
        "tags": ["available", "capacity", "operations"],
        "owner_name": "Melany",
        "roles": ["executive", "operations"],
    },
    # Customer Attrition Detail (0857253a-9c3d-4c37-b02f-2ef5faf25705) removed:
    # app has 0 sheets in Qlik Cloud — nothing to embed
    {
        "qlik_app_id": "b4f70f83-36b8-4426-a9b3-ca26f25b55f4",
        "qlik_sheet_id": "5a52424c-91e5-4df4-a7a9-e5fe95895435",
        "title": "Spot Details by Express Module",
        "description": "Spot rate details and express module analysis",
        "category": "Operations",
        "tags": ["spot", "pricing", "express"],
        "owner_name": "Melany",
        "roles": ["executive", "operations"],
    },
    {
        "qlik_app_id": "6df25048-2917-43e9-a944-a48cc355fdb4",
        "qlik_sheet_id": "Kpmpkd",
        "title": "RFP Performance Tracker",
        "description": "RFP tracking and performance metrics",
        "category": "Operations",
        "tags": ["rfp", "performance", "tracking"],
        "owner_name": "Melany",
        "roles": ["executive", "operations"],
    },
    {
        "qlik_app_id": "9b669acd-bf18-4467-9dbc-adeaec537670",
        "qlik_sheet_id": "XPfek",
        "title": "Attrition to Sales",
        "description": "Customer attrition impact on sales performance",
        "category": "Sales",
        "tags": ["attrition", "sales", "customer"],
        "owner_name": "Melany",
        "roles": ["executive", "sales"],
    },
    {
        "qlik_app_id": "4e326aa5-3d7a-4802-a792-56e28a35fdd6",
        "qlik_sheet_id": "0a1d1a73-bd89-41a5-b105-5b965788a023",
        "title": "Attrition Week-Over-Week",
        "description": "Weekly attrition trend comparisons",
        "category": "Sales",
        "tags": ["attrition", "weekly", "trends"],
        "owner_name": "Melany",
        "roles": ["executive", "sales"],
    },
    {
        "qlik_app_id": "949cafc8-cd79-4058-a528-cd4b330d9298",
        "qlik_sheet_id": "fae4a96e-3ed3-447a-abda-be899d0d0dab",
        "title": "Awards Tracker",
        "description": "Sales awards and recognition tracking",
        "category": "Sales",
        "tags": ["awards", "sales", "recognition"],
        "owner_name": "Melany",
        "roles": ["executive", "sales"],
    },
    {
        "qlik_app_id": "c51e72d7-ca8a-497a-a48e-7b185b90cca3",
        "qlik_sheet_id": "mjGJk",
        "title": "HR - IT Report",
        "description": "HR and IT workforce metrics and reporting",
        "category": "HR",
        "tags": ["hr", "it", "workforce"],
        "owner_name": "Melany",
        "roles": ["executive", "hr"],
    },
    # NOTE: "HR - Access Log Doors" was migrated to a code-made report on
    # 2026-04-24. See CUSTOM_REPORTS (key=hr-access-doors) and the one-time
    # row-flip in main.py lifespan. Do not re-add it here.
    # NOTE: "Vonage VoIP Calls" (app 3e30136b-…) was migrated to a code-made
    # report on 2026-04-26. See CUSTOM_REPORTS (key=voip-calls-logs) and the
    # one-time row-flip in main.py lifespan. Do not re-add it here.
    {
        "qlik_app_id": "86da731f-577f-45d3-9d40-c416649a4937",
        "qlik_sheet_id": "RqXzx",
        "title": "IT Managed Services",
        "description": "IT service desk incidents and service requests",
        "category": "IT",
        "tags": ["it", "service-desk", "incidents", "tickets"],
        "owner_name": "Melany",
        "roles": ["executive", "it"],
    },
]

# 12 mobile (Mob) reports — same roles as desktop counterparts
MOBILE_REPORTS = [
    {
        "qlik_app_id": "a942067d-32e7-4805-b1f1-36764bcf578a",
        "qlik_sheet_id": "78180b73-c0c5-4af9-923c-2f9aea37791d",
        "title": "(Mob) Executive",
        "description": "Executive KPIs optimized for mobile",
        "category": "Executive",
        "tags": ["executive", "mobile", "kpi"],
        "owner_name": "Melany",
        "roles": ["executive", "dfw", "corp"],
        "is_mobile": True,
    },
    {
        "qlik_app_id": "aa25d6c1-c18f-49a7-8ae3-2cdc8a5d7a3a",
        "qlik_sheet_id": "8552203b-070e-40d3-8bd4-ed90e869f91b",
        "title": "(Mob) DIRECT COMPARE",
        "description": "Division comparison optimized for mobile",
        "category": "Executive",
        "tags": ["comparison", "mobile"],
        "owner_name": "Melany",
        "roles": ["executive", "dfw", "corp"],
        "is_mobile": True,
    },
    {
        "qlik_app_id": "56d883e0-69b0-4500-ae16-2745e374760f",
        "qlik_sheet_id": "a4cdb08f-9340-424b-97e2-1efd9b01204f",
        "title": "(Mob) Budget Follow-up",
        "description": "Budget tracking optimized for mobile",
        "category": "Finance",
        "tags": ["budget", "finance", "mobile"],
        "owner_name": "Melany",
        "roles": ["executive", "finance"],
        "is_mobile": True,
    },
    {
        "qlik_app_id": "6e7a2f51-6d5a-464a-871b-42a395fa872f",
        "qlik_sheet_id": "755f3da5-80b6-449d-8899-a2c892e9a5e2",
        "title": "(Mob) Customer Scorecard",
        "description": "Customer scorecard optimized for mobile",
        "category": "Operations",
        "tags": ["customer", "scorecard", "mobile"],
        "owner_name": "Melany",
        "roles": ["executive", "operations"],
        "is_mobile": True,
    },
    {
        "qlik_app_id": "10b0a4a6-593f-429d-98e9-f7379603ca8e",
        "qlik_sheet_id": "7c5b0cfd-57be-4dd1-b298-aa06d074f75e",
        "title": "(Mob) Carrier Savings Dashboard",
        "description": "Carrier savings optimized for mobile",
        "category": "Operations",
        "tags": ["carrier", "savings", "mobile"],
        "owner_name": "Melany",
        "roles": ["executive", "operations"],
        "is_mobile": True,
    },
    {
        "qlik_app_id": "6339df0f-7487-4737-9ac6-7b45a7e8bf93",
        "qlik_sheet_id": "5af43aac-6bd4-4875-a43d-8d18d054a05c",
        "title": "(Mob) Spot Details by Express Module",
        "description": "Spot details optimized for mobile",
        "category": "Operations",
        "tags": ["spot", "pricing", "mobile"],
        "owner_name": "Melany",
        "roles": ["executive", "operations"],
        "is_mobile": True,
    },
    {
        "qlik_app_id": "069e3865-d19e-442b-82ff-7a89ef6cb704",
        "qlik_sheet_id": "MygcmP",
        "title": "(Mob) Available",
        "description": "Available capacity optimized for mobile",
        "category": "Operations",
        "tags": ["available", "capacity", "mobile"],
        "owner_name": "Melany",
        "roles": ["executive", "operations"],
        "is_mobile": True,
    },
    {
        "qlik_app_id": "651f789a-f9a4-44ad-9ce3-301a1a3dc2ef",
        "qlik_sheet_id": "fae4a96e-3ed3-447a-abda-be899d0d0dab",
        "title": "(Mob) Awards Tracker",
        "description": "Awards tracking optimized for mobile",
        "category": "Sales",
        "tags": ["awards", "sales", "mobile"],
        "owner_name": "Melany",
        "roles": ["executive", "sales"],
        "is_mobile": True,
    },
    {
        "qlik_app_id": "b2faa2ec-a923-4f27-9b18-0fd5cebd962c",
        "qlik_sheet_id": "0ff273bb-7aa2-40a1-898d-6cdb7d64f2a5",
        "title": "(Mob) Attrition Week-Over-Week",
        "description": "Weekly attrition trends optimized for mobile",
        "category": "Sales",
        "tags": ["attrition", "weekly", "mobile"],
        "owner_name": "Melany",
        "roles": ["executive", "sales"],
        "is_mobile": True,
    },
    # NOTE: "(Mob) HR - Access Log Doors" removed 2026-04-24 — the code-made
    # desktop page at /reports/hr-access-doors is responsive (scrolls on
    # mobile), so no separate mobile tile is needed.
    # NOTE: "(Mob) Vonage VoIP Calls" (app 9e477387-…) removed 2026-04-26 —
    # the desktop code-made report at /reports/voip-calls-logs handles all
    # call-log lookups; no separate mobile tile is needed (page renders a
    # <1280px desktop banner like OPs Margins / OPs Direct Compare).
    {
        "qlik_app_id": "b45e95b3-15f0-4cd8-8fa6-bb968917d9d2",
        "qlik_sheet_id": "8aae69c7-d3be-4759-91aa-4f31960f2155",
        "title": "(Mob) IT Managed Services",
        "description": "IT service desk optimized for mobile",
        "category": "IT",
        "tags": ["it", "service-desk", "mobile"],
        "owner_name": "Melany",
        "roles": ["executive", "it"],
        "is_mobile": True,
    },
]
# (Mob) Attrition to Sales (a9457bc4) skipped: 0 sheets in Qlik

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

        # 0. Remove duplicate reports (keep oldest by created_at)
        await pool.execute(
            """
            DELETE FROM reports r
            WHERE r.id NOT IN (
              SELECT DISTINCT ON (qlik_app_id) id
              FROM reports
              ORDER BY qlik_app_id, created_at ASC
            )
            """
        )

        # Ensure unique constraints exist for idempotent seeding
        await pool.execute(
            """
            CREATE UNIQUE INDEX IF NOT EXISTS reports_qlik_app_id_key
            ON reports (qlik_app_id)
            WHERE qlik_app_id IS NOT NULL
            """
        )
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

        # Case-insensitive lookup — existing REPORTS dicts still use lowercase keys
        # (e.g. "executive", "dfw") while role_ids now stores Title-Case keys.
        role_ids_ci = {k.lower(): v for k, v in role_ids.items()}

        # 2. Seed reports and role-report mappings (desktop + mobile)
        all_reports = REPORTS + MOBILE_REPORTS
        for report in all_reports:
            roles = report.get("roles", [])
            is_mobile = report.get("is_mobile", False)
            row = await pool.fetchrow(
                """
                INSERT INTO reports (qlik_app_id, qlik_sheet_id, title, description,
                                     category, tags, owner_name, is_mobile)
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
                ON CONFLICT (qlik_app_id) DO UPDATE SET
                  qlik_sheet_id = EXCLUDED.qlik_sheet_id,
                  title = EXCLUDED.title,
                  description = EXCLUDED.description,
                  category = EXCLUDED.category,
                  tags = EXCLUDED.tags,
                  owner_name = EXCLUDED.owner_name,
                  is_mobile = EXCLUDED.is_mobile
                RETURNING id
                """,
                report["qlik_app_id"],
                report.get("qlik_sheet_id"),
                report["title"],
                report.get("description"),
                report.get("category"),
                report.get("tags", []),
                report.get("owner_name"),
                is_mobile,
            )

            if row:
                report_id = row["id"]
                for role_name in roles:
                    role_id = role_ids_ci.get(role_name.lower())
                    if role_id:
                        await pool.execute(
                            """
                            INSERT INTO role_report_access (role_id, report_id)
                            VALUES ($1, $2) ON CONFLICT DO NOTHING
                            """,
                            role_id,
                            report_id,
                        )

        # 2b. Seed code-made (custom) reports. Keyed by custom_path so they're idempotent.
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
