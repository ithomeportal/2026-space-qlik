"""Bonus Calculator – DFW: nightly roster sync from the Time-off DB (05:00 CST).

Diego, 2026-09-02: *"all user and teams are from /BOT/time-off … you can sync
every day at 5am CST as well."*

⚠ **The Time-off DB has no team column and no salary.** It is authoritative for
*who works in DFW* (`users.department = 'Operations (DFW)'`, `isActive`), for
their **role** (`jobTitle`) and for their **shift** (`shiftType`). The TM1-TM4
split does not exist there, so it comes from the datalake — `mcleod_dfw_bookers_
rank`, which carries `posted_by_name` beside `team` and is rebuilt daily.

🔴 **ADDITIVE ONLY. This module never edits a row it did not create.**
An existing roster row is left exactly as it stands — team, role and salary all
untouched — because `bonus_dfw_roster` is HR's editable payroll table and a
nightly job that "corrects" it would silently revert every HR decision. Worse,
team membership here is *inferred from load postings*: a few loads booked for a
neighbouring team would move somebody between teams overnight and change their
pay, with nothing to show it happened. So:

* absent from the roster + placeable  ⇒ INSERT
* already in the roster               ⇒ LEAVE ALONE (always)
* in the roster, and Time-off says they are INACTIVE ⇒ remove (they left)
* in the roster and unknown to Time-off ⇒ LEAVE ALONE (HR added them by hand)

Salary is display-only in the engine (`totalCompMxn = salary + bonus`; it enters
no payout), so new rows start on the corporate per-role defaults and HR edits
them in-app.
"""

from __future__ import annotations

import logging
from typing import Iterable

from app.booker_names import name_tokens

logger = logging.getLogger(__name__)

TIMEOFF_DEPARTMENT = "Operations (DFW)"

# `jobTitle` -> bonus role. Titles absent from this map are not bonus-eligible
# roles and are skipped by name, never by a default: a new title must be an
# explicit decision, not silently paid as Tracking & Tracing.
JOB_TITLE_ROLE = {
    "Key Account Manager": "kam",
    "Booker": "freight_match",
    "Tracking and Tracing": "tracking_tracing",
    "Tracking and Tracking": "tracking_tracing",  # live typo in Time-off
}

# Titles that are DFW staff but not part of the team bonus (Bruno's module pays
# KAM / Freight-Match / Tracking&Tracing only).
NON_BONUS_TITLES = {
    "Director DFW",
    "DFW Admin Support",
    "Operations Intern",
    "Appointments Scheduler",
    "Accessorial & Operations Compliance Supervisor",
}

# `shiftType` -> Afterhours group. Shift beats title: a Booker on the WEEKEND
# rota is paid from the Afterhours card, not from a team.
AFTERHOURS_GROUP = {"NIGHT": "Night Shift", "WEEKEND": "Weekend Shift"}

# ⚠ Role overrides, keyed on the normalised name. Gyneth Dominguez carries the
# `DFW KAM3` TagRole in the portal while Time-off still lists her as `Booker`,
# and TM3 would otherwise have no KAM at all — the load-count bracket is the
# only rung DFW currently clears, so that is not cosmetic. Confirmed by Diego
# 2026-09-02. An override applies to the INSERT only; once the row exists HR
# owns it like any other.
ROLE_OVERRIDES = {"gynethdominguez": "kam"}

# Display-only (see the module docstring); mirrors `bonus_defaults.DEFAULT_ROSTER`.
DEFAULT_SALARY_MXN = {"kam": 42000, "freight_match": 25000, "tracking_tracing": 22000}
DEFAULT_AFTERHOURS_SALARY_MXN = 22000

# Trailing window used to decide a person's team. Long enough that a week of
# holiday cannot flip somebody, short enough to follow a real reassignment.
TEAM_WINDOW_DAYS = 90
# Below this share of a person's postings the placement is recorded as
# low-confidence: still placed (Diego 2026-09-02 — everyone should be paid), but
# named in the result so HR can correct it in HR Settings.
TEAM_CONFIDENCE_FLOOR = 0.90

DFW_TEAMS = ("TM1", "TM2", "TM3", "TM4")


def _key(name: str) -> frozenset:
    """Match key: the set of normalised name tokens.

    Deliberately a SET, not `booker_names.name_key`'s ordered join: Time-off
    stores full legal names (`Mauricio Mahuad Ortiz`, `Roberto Carlos Barcenas
    Rivera`) while McLeod records the short form (`MAURICIO MAHUAD`), so the two
    are never equal and one is a strict subset of the other. Normalisation
    itself is `booker_names.name_tokens` — the ONE definition (§69).
    """
    return frozenset(name_tokens(name))


def _resolve(key: frozenset, candidates: dict[frozenset, dict]) -> dict | None:
    """The one candidate whose name key matches, or None.

    Exact first, then subset in either direction — but only with at least two
    tokens in common, so a single shared surname (`Jessica Rodriguez` /
    `Evelyn Rodriguez`) can never match. ⚠ An ambiguous key that matches two
    people resolves to NOTHING rather than to the first: this decides who is
    paid, and a silent merge is the §83 failure.
    """
    if key in candidates:
        return candidates[key]
    hits = [v for k, v in candidates.items() if len(k & key) >= 2 and (k <= key or key <= k)]
    return hits[0] if len(hits) == 1 else None


async def _timeoff_people(timeoff_pool) -> list[dict]:
    rows = await timeoff_pool.fetch(
        """
        SELECT "name", "jobTitle", "shiftType", "isActive"
        FROM public.users
        WHERE "department" = $1 AND "name" IS NOT NULL
        """,
        TIMEOFF_DEPARTMENT,
    )
    return [
        {
            "name": r["name"].strip(),
            "job_title": (r["jobTitle"] or "").strip(),
            "shift": (str(r["shiftType"]) if r["shiftType"] else "DAY"),
            "active": bool(r["isActive"]),
        }
        for r in rows
    ]


async def _team_postings(gold_pool) -> dict[frozenset, dict[str, int]]:
    """{name key: {TMn: loads posted}} over the trailing window."""
    rows = await gold_pool.fetch(
        f"""
        SELECT posted_by_name, team, COUNT(*) AS n
        FROM public.mcleod_dfw_bookers_rank
        WHERE posted_date_only >= CURRENT_DATE - {TEAM_WINDOW_DAYS}
          AND team = ANY($1::text[])
          AND posted_by_name IS NOT NULL
        GROUP BY 1, 2
        """,
        list(DFW_TEAMS),
    )
    out: dict[frozenset, dict[str, int]] = {}
    for r in rows:
        out.setdefault(_key(r["posted_by_name"]), {})[r["team"]] = int(r["n"])
    return out


def _placement(counts: dict[str, int]) -> tuple[str, float]:
    total = sum(counts.values())
    team, n = max(counts.items(), key=lambda kv: (kv[1], kv[0]))
    return team, (n / total if total else 0.0)


async def sync_dfw_bonus_roster(primary, timeoff_pool, gold_pool) -> dict:
    """Additive sync of `bonus_dfw_roster` + `bonus_dfw_afterhours`.

    Returns a report naming every insert, removal and person it could not place
    — a count alone cannot distinguish "nothing to do" from "matched nobody".
    """
    if timeoff_pool is None or gold_pool is None:
        return {"skipped": "timeoff or gold pool unavailable"}

    people = await _timeoff_people(timeoff_pool)
    postings = await _team_postings(gold_pool)

    existing_roster = {
        _key(r["employee_name"]): r["employee_name"]
        for r in await primary.fetch("SELECT employee_name FROM bonus_dfw_roster")
    }
    existing_after = {
        _key(r["employee_name"]): r["employee_name"]
        for r in await primary.fetch("SELECT employee_name FROM bonus_dfw_afterhours")
    }

    added_team: list[str] = []
    added_after: list[str] = []
    low_confidence: list[str] = []
    unplaceable: list[str] = []
    removed: list[str] = []

    by_key = {_key(p["name"]): p for p in people}

    for person in people:
        if not person["active"]:
            continue
        key = _key(person["name"])
        title = person["job_title"]
        if title in NON_BONUS_TITLES:
            continue

        group = AFTERHOURS_GROUP.get(person["shift"])
        if group:
            if key in existing_after:
                continue
            sort = await primary.fetchval(
                "SELECT COALESCE(MAX(sort_order), -1) + 1 FROM bonus_dfw_afterhours"
            )
            await primary.execute(
                """
                INSERT INTO bonus_dfw_afterhours
                  (shift_group, employee_name, salary_mxn, receives_bonus, sort_order)
                VALUES ($1, $2, $3, TRUE, $4)
                """,
                group, person["name"], DEFAULT_AFTERHOURS_SALARY_MXN, sort,
            )
            existing_after[key] = person["name"]
            added_after.append(f"{person['name']} ({group})")
            continue

        role = ROLE_OVERRIDES.get("".join(name_tokens(person["name"]))) or JOB_TITLE_ROLE.get(title)
        if role is None:
            continue  # an unmapped title is a decision, never a default
        if key in existing_roster:
            continue  # 🔴 HR owns this row

        counts = postings.get(key) or _resolve(key, postings)
        if not counts:
            unplaceable.append(f"{person['name']} ({role})")
            continue
        team, confidence = _placement(counts)
        team_id = f"dfw-tm-{team[-1]}"
        if confidence < TEAM_CONFIDENCE_FLOOR:
            low_confidence.append(f"{person['name']} -> {team} ({confidence * 100:.0f}%)")

        sort = await primary.fetchval(
            "SELECT COALESCE(MAX(sort_order), -1) + 1 FROM bonus_dfw_roster WHERE team_id = $1",
            team_id,
        )
        await primary.execute(
            """
            INSERT INTO bonus_dfw_roster (team_id, employee_name, role, salary_mxn, sort_order)
            VALUES ($1, $2, $3, $4, $5)
            """,
            team_id, person["name"], role, DEFAULT_SALARY_MXN[role], sort,
        )
        existing_roster[key] = person["name"]
        added_team.append(f"{person['name']} -> {team} / {role}")

    # Leavers: only somebody Time-off KNOWS and marks inactive. A roster row
    # Time-off has never heard of was added by HR and is none of our business.
    for table, present in (("bonus_dfw_roster", existing_roster), ("bonus_dfw_afterhours", existing_after)):
        for key, stored_name in list(present.items()):
            src = by_key.get(key) or _resolve(key, by_key)
            if src is not None and not src["active"]:
                await primary.execute(
                    f"DELETE FROM {table} WHERE employee_name = $1", stored_name
                )
                removed.append(f"{stored_name} ({table})")

    report = {
        "added_team": added_team,
        "added_afterhours": added_after,
        "removed": removed,
        "low_confidence": low_confidence,
        "unplaceable": unplaceable,
    }
    logger.info(
        "DFW bonus roster sync: +%d team, +%d afterhours, -%d leavers, "
        "%d low-confidence, %d unplaceable",
        len(added_team), len(added_after), len(removed),
        len(low_confidence), len(unplaceable),
    )
    for label, names in (("low-confidence placement", low_confidence),
                         ("could not place (no postings)", unplaceable)):
        if names:
            logger.warning("DFW bonus roster — %s: %s", label, "; ".join(names))
    return report
