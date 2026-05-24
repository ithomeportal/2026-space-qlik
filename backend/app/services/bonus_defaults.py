"""Default Bonus Calculator roster / afterhours / FX — seeded once into analytics_hub.

Verbatim from Bruno's package ``DEFAULT_EMPLOYEE_TEMPLATE`` /
``DEFAULT_NIGHT_SHIFT_EMPLOYEES`` (confirmed Q4, 2026-05-24, including the
"Member 3/4" / "Member 2" placeholders HR will rename in-app later).

Team map (Q1): team-1..4 ⇄ TEAM1..TEAM4. TEAM5 has no roster → excluded.
Seeding is idempotent: rows are only inserted when the table is empty, so HR
edits are never overwritten on redeploy.
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

# Title-cased display name per team id; mcleod team_id is derived as TEAM<N>.
DEFAULT_TEAM_NAMES = {
    "team-1": "Team 1",
    "team-2": "Team 2",
    "team-3": "Team 3",
    "team-4": "Team 4",
}

DEFAULT_ROSTER = [
    # team_id,  name,                          role,               salary_mxn, sort
    ("team-1", "Julio Rodriguez", "kam", 42000, 0),
    ("team-1", "Jorge De Leon", "freight_match", 25000, 1),
    ("team-1", "Magaly Vazquez", "tracking_tracing", 22000, 2),
    ("team-2", "Ruben Rodriguez", "kam", 42000, 0),
    ("team-2", "Erick Rodriguez", "freight_match", 22000, 1),
    ("team-2", "Nydia Trejo", "tracking_tracing", 22000, 2),
    ("team-3", "Sergio Hidalgo", "kam", 42000, 0),
    ("team-3", "Eduardo Gonzalez", "freight_match", 25000, 1),
    ("team-3", "Jennifer Rdz", "tracking_tracing", 22000, 2),
    ("team-3", "Team 3 Tracking & Tracing 2", "tracking_tracing", 22000, 3),
    ("team-4", "Monica Perez", "kam", 42000, 0),
    ("team-4", "Team 4 Tracking & Tracing", "tracking_tracing", 0, 1),
]

DEFAULT_AFTERHOURS = [
    # group,           name,                       salary_mxn, receives_bonus, sort
    ("Night Shift", "German Quero", 22000, True, 0),
    ("Night Shift", "Alondra Estrada", 22000, True, 1),
    ("Night Shift", "Night Shift Member 3", 22000, True, 2),
    ("Night Shift", "Night Shift Member 4", 22000, True, 3),
    ("Weekend Shift", "Luis Torres", 38000, True, 4),
    ("Weekend Shift", "Weekend Shift Member 2", 38000, True, 5),
]

# HR board-pinned FX (Q3): per-period team FX + night FX. These are the default
# values; HR overrides them per period in-app. (Package sample used 17.37 / 16.89.)
DEFAULT_TEAM_FX_RATE = 17.37
DEFAULT_NIGHT_FX_RATE = 16.89


async def seed_bonus_data(pool) -> None:
    """Idempotent seed of roster + afterhours. Only inserts when each table is empty."""
    roster_count = await pool.fetchval("SELECT COUNT(*) FROM bonus_roster")
    if roster_count == 0:
        await pool.executemany(
            """
            INSERT INTO bonus_roster (team_id, employee_name, role, salary_mxn, sort_order)
            VALUES ($1, $2, $3, $4, $5)
            """,
            DEFAULT_ROSTER,
        )
        logger.info("Seeded %d default Bonus Calculator roster rows", len(DEFAULT_ROSTER))

    after_count = await pool.fetchval("SELECT COUNT(*) FROM bonus_afterhours")
    if after_count == 0:
        await pool.executemany(
            """
            INSERT INTO bonus_afterhours (shift_group, employee_name, salary_mxn, receives_bonus, sort_order)
            VALUES ($1, $2, $3, $4, $5)
            """,
            DEFAULT_AFTERHOURS,
        )
        logger.info("Seeded %d default Bonus Calculator afterhours rows", len(DEFAULT_AFTERHOURS))
