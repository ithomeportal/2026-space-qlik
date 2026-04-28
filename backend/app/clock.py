"""CST clock helpers.

Render runs containers in UTC (CST + 6h). Aiven Postgres sessions also default
to UTC. Our datalake (`aivn_datalake_gold`) stores timestamps already in CST,
so every "today / yesterday / week / month" boundary in this app must come
from a CST clock — otherwise during 18:00–23:59 CST we silently flip a day
early and label *today* as *yesterday*.

Use `cst_today()` everywhere instead of `date.today()`, and the SQL helper
`CST_NOW_DATE_SQL` instead of bare `CURRENT_DATE`.
"""

from __future__ import annotations

from datetime import date, datetime
from zoneinfo import ZoneInfo

CST = ZoneInfo("America/Chicago")  # auto-handles CST↔CDT transitions

# Inline SQL fragment that returns the current CST calendar date regardless of
# the Postgres session timezone.
CST_NOW_DATE_SQL = "(now() AT TIME ZONE 'America/Chicago')::date"


def cst_today() -> date:
    """Today's calendar date in America/Chicago."""
    return datetime.now(CST).date()


def cst_now() -> datetime:
    """Current wall-clock instant in America/Chicago (tz-aware)."""
    return datetime.now(CST)
