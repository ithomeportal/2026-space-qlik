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

* absent from the roster + placeable  ⇒ INSERT, effective from the current
                                        CST month's first day
* already in the roster               ⇒ LEAVE ALONE (always) — and "in the
                                        roster" includes CLOSED rows, so a person
                                        HR removed is never re-inserted
* in the roster, and Time-off says they are INACTIVE ⇒ close the OPEN row at the
  previous month (they stay in the months they worked); a row that only began
  this month is deleted outright, exactly as HR's own DELETE does
* in the roster and unknown to Time-off ⇒ LEAVE ALONE (HR added them by hand)

Effective dating (2026-10-31): see `app/routers/bonus_roster_writes.py`.

Salary is display-only in the engine (`totalCompMxn = salary + bonus`; it enters
no payout), so new rows start on the corporate per-role defaults and HR edits
them in-app.
"""

from __future__ import annotations

import logging
from datetime import date

from app.booker_names import name_tokens
from app.clock import cst_today

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
    hits = _subset_hits(key, candidates)
    return hits[0] if len(hits) == 1 else None


def _subset_hits(key: frozenset, candidates: dict) -> list:
    return [v for k, v in candidates.items() if len(k & key) >= 2 and (k <= key or key <= k)]


def _already_known(key: frozenset, existing: dict) -> bool:
    """Is this person ALREADY a row (open or closed) under any spelling of their name?

    ⚠ Deliberately looser than `_resolve`: for "should we INSERT?" an ambiguous
    match must count as KNOWN, never as absent. Exact-key-only let the job add
    `Mauricio Mahuad Ortiz` beside HR's `Mauricio Mahuad` on 2026-10-08 — the
    same person twice, i.e. a second per-load payout.
    """
    return key in existing or bool(_subset_hits(key, existing))


def _note_similar(key: frozenset, existing: dict, name: str, out: list[str]) -> None:
    """Name a skip that matched only by subset, so HR can see it was not a typo."""
    if key not in existing:
        out.append(f"{name} ~ {', '.join(sorted(_subset_hits(key, existing)))}")


def _month_bounds(today: date) -> tuple[date, date]:
    """(first day of today's month, first day of the previous month)."""
    first = today.replace(day=1)
    prev = date(first.year - 1, 12, 1) if first.month == 1 else date(first.year, first.month - 1, 1)
    return first, prev


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


async def _existing(primary, table: str) -> tuple[dict, list[dict]]:
    """({name key: name} over EVERY row — open or closed —, the open rows)."""
    rows = await primary.fetch(
        f"SELECT id, employee_name, effective_from, effective_to FROM {table}"
    )
    known = {_key(r["employee_name"]): r["employee_name"] for r in rows}
    open_rows = [
        {"id": r["id"], "name": r["employee_name"], "from": r["effective_from"]}
        for r in rows
        if r["effective_to"] is None
    ]
    return known, open_rows


async def sync_dfw_bonus_roster(primary, timeoff_pool, gold_pool, today: date | None = None) -> dict:
    """Additive sync of `bonus_dfw_roster` + `bonus_dfw_afterhours`.

    Returns a report naming every insert, removal and person it could not place
    — a count alone cannot distinguish "nothing to do" from "matched nobody".
    ``today`` exists for tests; production uses the CST date.
    """
    if timeoff_pool is None or gold_pool is None:
        return {"skipped": "timeoff or gold pool unavailable"}

    month_first, prev_month_first = _month_bounds(today or cst_today())
    people = await _timeoff_people(timeoff_pool)
    postings = await _team_postings(gold_pool)

    existing_roster, open_roster = await _existing(primary, "bonus_dfw_roster")
    existing_after, open_after = await _existing(primary, "bonus_dfw_afterhours")

    added_team: list[str] = []
    added_after: list[str] = []
    low_confidence: list[str] = []
    unplaceable: list[str] = []
    removed: list[str] = []
    similar: list[str] = []  # skipped because a near-identical name is already a row

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
            if _already_known(key, existing_after):
                _note_similar(key, existing_after, person["name"], similar)
                continue
            sort = await primary.fetchval(
                "SELECT COALESCE(MAX(sort_order), -1) + 1 FROM bonus_dfw_afterhours"
            )
            await primary.execute(
                """
                INSERT INTO bonus_dfw_afterhours
                  (shift_group, employee_name, salary_mxn, receives_bonus, sort_order, effective_from)
                VALUES ($1, $2, $3, TRUE, $4, $5)
                """,
                group, person["name"], DEFAULT_AFTERHOURS_SALARY_MXN, sort, month_first,
            )
            existing_after[key] = person["name"]
            added_after.append(f"{person['name']} ({group})")
            continue

        role = ROLE_OVERRIDES.get("".join(name_tokens(person["name"]))) or JOB_TITLE_ROLE.get(title)
        if role is None:
            continue  # an unmapped title is a decision, never a default
        if _already_known(key, existing_roster):
            _note_similar(key, existing_roster, person["name"], similar)
            continue  # 🔴 HR owns this row — open OR closed

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
            INSERT INTO bonus_dfw_roster
              (team_id, employee_name, role, salary_mxn, sort_order, effective_from)
            VALUES ($1, $2, $3, $4, $5, $6)
            """,
            team_id, person["name"], role, DEFAULT_SALARY_MXN[role], sort, month_first,
        )
        existing_roster[key] = person["name"]
        added_team.append(f"{person['name']} -> {team} / {role}")

    # Leavers: only somebody Time-off KNOWS and marks inactive. A roster row
    # Time-off has never heard of was added by HR and is none of our business.
    # Only OPEN rows are touched; the months they worked keep them.
    for table, open_rows in (("bonus_dfw_roster", open_roster), ("bonus_dfw_afterhours", open_after)):
        for row in open_rows:
            key = _key(row["name"])
            src = by_key.get(key) or _resolve(key, by_key)
            if src is None or src["active"]:
                continue
            removed.append(await _close_leaver(primary, table, row, month_first, prev_month_first))

    report = {
        "added_team": added_team,
        "added_afterhours": added_after,
        "removed": removed,
        "low_confidence": low_confidence,
        "unplaceable": unplaceable,
        "skipped_similar_name": similar,
    }
    logger.info(
        "DFW bonus roster sync: +%d team, +%d afterhours, -%d leavers, "
        "%d low-confidence, %d unplaceable",
        len(added_team), len(added_after), len(removed),
        len(low_confidence), len(unplaceable),
    )
    for label, names in (("low-confidence placement", low_confidence),
                         ("could not place (no postings)", unplaceable),
                         ("not inserted — a similar name is already a row", similar)):
        if names:
            logger.warning("DFW bonus roster — %s: %s", label, "; ".join(names))
    return report


async def _close_leaver(primary, table: str, row: dict, month_first: date, prev_first: date) -> str:
    """Soft-close a leaver's open row at the previous month; delete one that began this month."""
    if row["from"] is not None and row["from"] >= month_first:
        await primary.execute(f"DELETE FROM {table} WHERE id = $1", row["id"])
        return f"{row['name']} ({table}, deleted — started this month)"
    await primary.execute(
        f"UPDATE {table} SET effective_to = $2 WHERE id = $1 AND effective_to IS NULL",
        row["id"], prev_first,
    )
    return f"{row['name']} ({table}, closed {prev_first.isoformat()})"
