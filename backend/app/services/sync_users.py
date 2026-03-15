"""Sync users from the time-off people management database.

Runs daily at 2am CST to keep the analytics hub user list in sync:
- Upserts active employees (name, email, department, job_title, company)
- Deactivates users no longer active in the time-off system
- Auto-assigns roles based on department keywords
- Promotes OWNER/DIRECTOR level employees to executive role
"""

import logging
from uuid import UUID

import asyncpg

from app.config import settings

logger = logging.getLogger(__name__)

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

ADMIN_EMAILS = [
    "dfrodriguez@unilinktransportation.com",
    "kmeneses@unilinktransportation.com",
    "msalazarm@unilinktransportation.com",
    "dcastrog@unilinktransportation.com",
]


async def sync_users() -> dict:
    """Sync users from time-off DB into analytics hub.

    Returns a summary dict with counts of synced, deactivated, and new users.
    """
    if not settings.TIMEOFF_DATABASE_URL:
        logger.warning("TIMEOFF_DATABASE_URL not set, skipping user sync")
        return {"error": "TIMEOFF_DATABASE_URL not configured"}

    if not settings.DATABASE_URL:
        logger.warning("DATABASE_URL not set, skipping user sync")
        return {"error": "DATABASE_URL not configured"}

    pool = await asyncpg.create_pool(settings.DATABASE_URL, min_size=1, max_size=3)
    timeoff_pool = await asyncpg.create_pool(
        settings.TIMEOFF_DATABASE_URL, min_size=1, max_size=2
    )

    try:
        # Ensure is_active column exists on users table
        await pool.execute(
            "ALTER TABLE users ADD COLUMN IF NOT EXISTS is_active BOOLEAN DEFAULT TRUE"
        )

        # Fetch all active employees from time-off system
        employees = await timeoff_pool.fetch(
            """
            SELECT "email", "name", "firstName", "lastName", "department",
                   "jobTitle", "companyName", "role", "roleLevel"
            FROM users
            WHERE "isActive" = true
            """
        )

        # Load role IDs from analytics hub
        role_rows = await pool.fetch("SELECT id, name FROM roles")
        role_ids: dict[str, UUID] = {r["name"]: r["id"] for r in role_rows}

        active_emails: set[str] = set()
        synced = 0
        new_users = 0

        for emp in employees:
            email = emp["email"]
            if not email:
                continue

            email = email.lower().strip()
            active_emails.add(email)

            # Prefer "name" field; fall back to firstName + lastName
            name = (emp.get("name") or "").strip()
            if not name:
                name = f"{emp['firstName'] or ''} {emp['lastName'] or ''}".strip()
            department = emp.get("department")
            job_title = emp.get("jobTitle")
            company = emp.get("companyName")

            # Upsert user — also reactivate if previously deactivated
            result = await pool.fetchrow(
                """
                INSERT INTO users (email, name, department, job_title, company, is_active)
                VALUES ($1, $2, $3, $4, $5, TRUE)
                ON CONFLICT (email) DO UPDATE SET
                  name = $2, department = $3, job_title = $4, company = $5,
                  is_active = TRUE
                RETURNING id, (xmax = 0) AS is_new
                """,
                email,
                name,
                department,
                job_title,
                company,
            )

            user_id = result["id"]
            if result["is_new"]:
                new_users += 1
            synced += 1

            # Auto-assign roles based on department
            dept = department or ""
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

            # Directors/Owners get executive role
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

        # Assign admin + executive roles to admin users
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

        # Deactivate users no longer active in time-off system
        deactivated_result = await pool.execute(
            """
            UPDATE users SET is_active = FALSE
            WHERE is_active = TRUE
              AND email != ALL($1::text[])
            """,
            list(active_emails),
        )
        # asyncpg execute returns "UPDATE N" string
        deactivated = int(deactivated_result.split()[-1])

        summary = {
            "synced": synced,
            "new_users": new_users,
            "deactivated": deactivated,
            "total_active_in_timeoff": len(active_emails),
        }
        logger.info(f"User sync complete: {summary}")
        return summary

    finally:
        await timeoff_pool.close()
        await pool.close()
