"""Database seeding script.

Seeds roles, reports, users, and role-report mappings.
Run: python -m app.services.seed
"""

import asyncio
from uuid import UUID

import asyncpg

from app.config import settings

# 9 default roles
DEFAULT_ROLES = [
    ("admin", "Full access to all reports and admin console"),
    ("executive", "Access to all reports across divisions"),
    ("finance", "Finance and budget reports"),
    ("operations", "Operations, carrier, and scorecard reports"),
    ("sales", "Sales, attrition, and awards reports"),
    ("hr", "HR reports"),
    ("it", "IT, VoIP, and managed services reports"),
    ("dfw", "DFW division reports"),
    ("corp", "CORP division reports"),
]

# 20 production reports from SPEC-QLIK-INVENTORY
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
    {
        "qlik_app_id": "de4c1a28-5e6a-465d-a351-59f99950a5d4",
        "qlik_sheet_id": "f0dd9fa9-4898-4c14-a6bc-6db60357070f",
        "title": "Customer Scorecard",
        "description": "Customer performance metrics and scorecards",
        "category": "Operations",
        "tags": ["customer", "scorecard", "operations"],
        "owner_name": "Melany",
        "roles": ["executive", "operations"],
    },
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
    {
        "qlik_app_id": "4573ff42-c0b5-48ef-9945-20861b7a6f63",
        "qlik_sheet_id": "ZYDdxs",
        "title": "HR - Access Log Doors",
        "description": "Door access log analysis for HR and security",
        "category": "HR",
        "tags": ["access", "doors", "security"],
        "owner_name": "Melany",
        "roles": ["executive", "hr", "it"],
    },
    {
        "qlik_app_id": "3e30136b-050a-4f19-83ab-17a7d55a2fc3",
        "qlik_sheet_id": "NfAFQFz",
        "title": "Vonage VoIP Calls",
        "description": "VoIP call analytics and metrics via Vonage",
        "category": "IT",
        "tags": ["voip", "vonage", "calls", "telecom"],
        "owner_name": "Melany",
        "roles": ["executive", "it"],
    },
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


async def seed_all():
    pool = await asyncpg.create_pool(settings.DATABASE_URL, min_size=1, max_size=3)

    try:
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

        # Ensure unique constraint exists for idempotent seeding
        await pool.execute(
            """
            CREATE UNIQUE INDEX IF NOT EXISTS reports_qlik_app_id_key
            ON reports (qlik_app_id)
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

        # 2. Seed reports and role-report mappings
        for report in REPORTS:
            roles = report.get("roles", [])
            row = await pool.fetchrow(
                """
                INSERT INTO reports (qlik_app_id, qlik_sheet_id, title, description,
                                     category, tags, owner_name)
                VALUES ($1, $2, $3, $4, $5, $6, $7)
                ON CONFLICT (qlik_app_id) DO UPDATE SET
                  qlik_sheet_id = EXCLUDED.qlik_sheet_id,
                  title = EXCLUDED.title,
                  description = EXCLUDED.description,
                  category = EXCLUDED.category,
                  tags = EXCLUDED.tags,
                  owner_name = EXCLUDED.owner_name
                RETURNING id
                """,
                report["qlik_app_id"],
                report.get("qlik_sheet_id"),
                report["title"],
                report.get("description"),
                report.get("category"),
                report.get("tags", []),
                report.get("owner_name"),
            )

            if row:
                report_id = row["id"]
                for role_name in roles:
                    if role_name in role_ids:
                        await pool.execute(
                            """
                            INSERT INTO role_report_access (role_id, report_id)
                            VALUES ($1, $2) ON CONFLICT DO NOTHING
                            """,
                            role_ids[role_name],
                            report_id,
                        )

        # 3. Seed users from time-off DB (if available)
        if settings.TIMEOFF_DATABASE_URL:
            await _seed_users_from_timeoff(pool, role_ids)

        # 4. Assign admin + executive roles to admin users
        for admin_email in ADMIN_EMAILS:
            user_row = await pool.fetchrow(
                "SELECT id FROM users WHERE email = $1", admin_email
            )
            if user_row:
                for role_name in ("admin", "executive"):
                    if role_name in role_ids:
                        await pool.execute(
                            """
                            INSERT INTO user_roles (user_id, role_id)
                            VALUES ($1, $2) ON CONFLICT DO NOTHING
                            """,
                            user_row["id"],
                            role_ids[role_name],
                        )

    finally:
        await pool.close()


async def _seed_users_from_timeoff(pool, role_ids: dict[str, UUID]):
    """Seed users from the time-off system database."""
    timeoff_pool = await asyncpg.create_pool(
        settings.TIMEOFF_DATABASE_URL, min_size=1, max_size=2
    )

    try:
        employees = await timeoff_pool.fetch(
            """
            SELECT "email", "firstName", "lastName", "department",
                   "jobTitle", "companyName", "role", "roleLevel"
            FROM users
            WHERE "isActive" = true
            """
        )

        for emp in employees:
            email = emp["email"]
            if not email:
                continue

            name = f"{emp['firstName'] or ''} {emp['lastName'] or ''}".strip()

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
                emp.get("department"),
                emp.get("jobTitle"),
                emp.get("companyName"),
            )

            user_id = user_row["id"]
            dept = emp.get("department") or ""

            # Auto-assign roles based on department
            for keyword, role_name in DEPT_ROLE_MAP.items():
                if keyword.lower() in dept.lower() and role_name in role_ids:
                    await pool.execute(
                        """
                        INSERT INTO user_roles (user_id, role_id)
                        VALUES ($1, $2) ON CONFLICT DO NOTHING
                        """,
                        user_id,
                        role_ids[role_name],
                    )

            # Directors/Owners also get executive role
            role_level = emp.get("roleLevel") or ""
            if role_level.upper() in ("OWNER", "DIRECTOR") and "executive" in role_ids:
                await pool.execute(
                    """
                    INSERT INTO user_roles (user_id, role_id)
                    VALUES ($1, $2) ON CONFLICT DO NOTHING
                    """,
                    user_id,
                    role_ids["executive"],
                )

    finally:
        await timeoff_pool.close()


if __name__ == "__main__":
    asyncio.run(seed_all())
