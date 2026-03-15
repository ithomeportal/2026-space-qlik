"""Sync users from the time-off people management database.

Runs daily at 2am CST to keep the analytics hub user list in sync:
- Upserts active employees (name, email, department, job_title, company)
- Deactivates users no longer active in the time-off system
- Does NOT auto-assign TagRoles — admins assign TagRoles manually
"""

import logging

import asyncpg

from app.config import settings

logger = logging.getLogger(__name__)

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
                   "jobTitle", "companyName"
            FROM users
            WHERE "isActive" = true
            """
        )

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
            full_name = emp["name"] or ""
            if not full_name.strip():
                first = emp["firstName"] or ""
                last = emp["lastName"] or ""
                full_name = f"{first} {last}"
            name = full_name.strip()
            department = emp["department"]
            job_title = emp["jobTitle"]
            company = emp["companyName"]

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

            if result["is_new"]:
                new_users += 1
            synced += 1

        # Keep admin users with admin role
        role_row = await pool.fetchrow(
            "SELECT id FROM roles WHERE name = 'admin'"
        )
        if role_row:
            admin_role_id = role_row["id"]
            for admin_email in ADMIN_EMAILS:
                user_row = await pool.fetchrow(
                    "SELECT id FROM users WHERE email = $1", admin_email
                )
                if user_row:
                    await pool.execute(
                        """
                        INSERT INTO user_roles (user_id, role_id)
                        VALUES ($1, $2) ON CONFLICT DO NOTHING
                        """,
                        user_row["id"],
                        admin_role_id,
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
