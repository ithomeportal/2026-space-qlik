"""Who owns what, as data — verbatim from ``space Attrition - Follow up.pdf``.

People are identified to Pipedrive by their LOGIN E-MAIL (resolved to a user id
live, fail closed), never by a hardcoded id or a display name — "Sergio" is the
Pipedrive display name of Sergio Hidalgo.

TEAM5 has no KAM in the request: its customers are SKIPPED (logged), never
routed to a guess (operator decision 2026-10-22).
"""
from __future__ import annotations

from dataclasses import dataclass

# The Reactive tab's "5 to 9 Weeks" table is 29–63 days. A customer is acted on
# while it sits in that table, so a missed run is caught up the next day.
CREATE_MIN_DAYS = 29
CREATE_MAX_DAYS = 63
# 90 days → Sales. Only NEW crossings (90–96) are acted on: at go-live 18
# customers were already past 90 and the operator chose not to touch that
# backlog (2026-10-22). The 7-day span covers missed runs.
REASSIGN_MIN_DAYS = 90
REASSIGN_MAX_DAYS = 96
# The read window only has to reach the oldest last-load we act on.
READ_WINDOW_DAYS = REASSIGN_MAX_DAYS + 30

PIPELINE_NAME = "REACTIVATION"
STAGE_NAME = "Re-OnHold"
DEAL_FIELD_REACTIVATION = "Is Deal Reactivation?"
DEAL_FIELD_REACTIVATION_OPTION = "Reactivation"
FIELD_MCLEOD = "ID_McLeod"  # on both deals and organizations

# v4 is rewritten every 15 minutes. Older than this at 04:00 = a frozen feed,
# and every customer would drift toward 29/90 days on its own — refuse to act.
MAX_FEED_AGE_HOURS = 6

CC_ALWAYS: tuple[str, ...] = (
    "emendoza@unilinktransportation.com",
    "andy@unilinktransportation.com",
    "iris@unilinktransportation.com",
)


@dataclass(frozen=True)
class Person:
    name: str
    email: str


@dataclass(frozen=True)
class TeamRouting:
    team: str
    kam: Person
    sales: Person
    notify_to: tuple[str, ...]
    notify_cc: tuple[str, ...] = CC_ALWAYS


JULIO = Person("Julio Rodriguez", "jrodriguez@unilinktransportation.com")
RUBEN = Person("Ruben Rodriguez", "lrodriguez@unilinktransportation.com")
SERGIO = Person("Sergio Hidalgo", "shidalgo@unilinktransportation.com")
MONICA = Person("Monica Perez", "mperezn@unilinktransportation.com")
CHRISTIAN = Person("Christian Mendoza", "christian@unilinktransportation.com")
MIGUEL = Person("Miguel Millan", "miguel@unilinktransportation.com")
EDUARDO = Person("Eduardo Valenzuela", "evalenzuela@unilinktransportation.com")
PATRICIO = Person("Patricio Villarreal", "pvillarreal@unilinktransportation.com")
JANAYA = "janaya@unilinktransportation.com"

ROUTING: dict[str, TeamRouting] = {
    r.team: r
    for r in (
        TeamRouting("TEAM1", JULIO, MIGUEL, (MIGUEL.email, JULIO.email, JANAYA)),
        TeamRouting("TEAM2", RUBEN, MIGUEL, (MIGUEL.email, RUBEN.email, JANAYA)),
        TeamRouting("TEAM3", SERGIO, EDUARDO, (EDUARDO.email, SERGIO.email, JANAYA)),
        TeamRouting("TEAM4", MONICA, EDUARDO, (EDUARDO.email, MONICA.email, JANAYA)),
        TeamRouting(
            "TEAM-DFW", CHRISTIAN, PATRICIO,
            (PATRICIO.email, "ctorres@unilinktransportation.com", CHRISTIAN.email),
        ),
    )
}

# Every login the job must resolve before it touches anything.
REQUIRED_USER_EMAILS: tuple[str, ...] = tuple(sorted(
    {r.kam.email for r in ROUTING.values()} | {r.sales.email for r in ROUTING.values()}
))
