"""A calculated arrival for a load with no ETA, only where history proves it works.

Pure: no I/O, so every rule is unit-tested without a database. ``data.py`` reads the
history; ``cards.py`` decides whether the result is still in the future.

Estimate = anchor time + the lane's median transit, where the anchor is the last
thing McLeod says the truck did: left a border yard, else left the Waco pickup on a
load with no yard. Both are wall clocks, as is the delivery arrival, so the zone
difference of a lane is already inside its transit and no conversion is needed.

⚠ A truck that reached a yard and has not left it gets NO estimate: border waits run
for days and do not predict (measured 2026-11-04: ~32 h off from yard arrival, ~24 h
from the crossing appointment). Back-test results: docs/SPEC-CUSTOMER-STATUS-EMAIL.md.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from statistics import median
from typing import Iterable, Optional

from app.services.customer_status_email.cards import (
    DEPARTED,
    EMPTY_AT,
    is_origin,
    is_own_consignee,
    parse_mcleod_time,
)
from app.services.customer_status_email.config import normalise

# A lane needs this many recent deliveries before anyone trusts its median.
MIN_SAMPLES = 10
# Only the newest deliveries of a lane: routes, carriers and borders change.
WINDOW = 40
# 80% of the lane's recent trips must land this close to its median.
MAX_SPREAD_HOURS = 12.0
# Of the trips that passed through an anchor, this share must have had no later stop.
# Otherwise "no yard yet" would be read as "never a yard": a Reynosa load just leaving
# Waco would be compared only with the odd trip that logged no yard, and promise days early.
MIN_LAST_STOP_SHARE = 0.9

PICKUP = "pickup"
YARD = "yard"


@dataclass(frozen=True)
class StopEvent:
    left: bool  # True = departed the place, False = reached it
    place: str
    at: datetime


@dataclass(frozen=True)
class Anchor:
    kind: str
    place: str  # normalised yard name; "" for the pickup
    at: datetime


@dataclass(frozen=True)
class Lane:
    hours: float
    spread: float
    samples: int
    appt_error: Optional[float]  # how far the appointment alone is typically off
    last_stop_share: float = 1.0  # of trips through this anchor, those with no later stop


def parse_event(comment: Optional[str]) -> Optional[StopEvent]:
    """A McLeod stop comment → what the truck did, where and when; else None."""
    text = (comment or "").strip()
    for pattern, left in ((DEPARTED, True), (EMPTY_AT, False)):
        m = pattern.match(text)
        if m:
            at = parse_mcleod_time(*m.groups()[1:4])
            return StopEvent(left, m.group("place"), at) if at else None
    return None


def _yard_events(comments: Iterable[str], consignee: Optional[str],
                 before: Optional[datetime]) -> list[StopEvent]:
    return [e for e in map(parse_event, comments)
            if e and not is_origin(e.place) and not is_own_consignee(e.place, consignee)
            and (before is None or e.at < before)]


def anchor_for(pu_out: Optional[datetime], comments: Iterable[str], consignee: Optional[str],
               before: Optional[datetime] = None) -> Optional[Anchor]:
    """What the estimate counts from; None while the truck sits at a yard.

    ``before`` replays history: only what had happened by the delivery counts.
    """
    events = _yard_events(comments, consignee, before)
    if not events:
        return Anchor(PICKUP, "", pu_out) if pu_out else None
    # A batch can post both at one time; arrival then departure is the only real order.
    last = max(events, key=lambda e: (e.at, e.left))
    return Anchor(YARD, normalise(last.place), last.at) if last.left else None


def _lane_key(consignee: Optional[str], anchor: Anchor) -> tuple[str, str, str]:
    return (normalise(consignee), anchor.kind, anchor.place)


def _p80(values: list[float]) -> float:
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, int(0.8 * len(ordered)))]


def build_lanes(delivered: list[dict], comments: dict[str, list[str]]) -> dict[tuple, Lane]:
    """Lane statistics from delivered loads: id, consignee, pu_out, del_in, del_sched_late."""
    trips: dict[tuple, list[tuple[float, Optional[float]]]] = {}
    through: dict[tuple, int] = {}
    for row in sorted(delivered, key=lambda r: r["del_in"]):
        arrived = row["del_in"]
        said = comments.get(row["id"].strip(), ())
        consignee = row.get("consignee")
        places = {normalise(e.place) for e in _yard_events(said, consignee, arrived)}
        passed = [(normalise(consignee), PICKUP, "")] + [
            (normalise(consignee), YARD, place) for place in places]
        through = {**through, **{k: through.get(k, 0) + 1 for k in passed}}
        anchor = anchor_for(row.get("pu_out"), said, consignee, before=arrived)
        if anchor is None or arrived <= anchor.at:
            continue
        hours = (arrived - anchor.at).total_seconds() / 3600
        appt = row.get("del_sched_late")
        missed = abs((appt - arrived).total_seconds()) / 3600 if appt else None
        trips.setdefault(_lane_key(row.get("consignee"), anchor), []).append((hours, missed))

    lanes = {}
    for key, rows in trips.items():
        recent = rows[-WINDOW:]
        hours = [h for h, _ in recent]
        mid = median(hours)
        missed = [m for _, m in recent if m is not None]
        lanes[key] = Lane(mid, _p80([abs(h - mid) for h in hours]), len(hours),
                          median(missed) if missed else None, len(rows) / through[key])
    return lanes


def is_proven(lane: Optional[Lane]) -> bool:
    """Enough trips, close together, and closer than simply quoting the appointment."""
    if lane is None or lane.samples < MIN_SAMPLES or lane.spread > MAX_SPREAD_HOURS:
        return False
    if lane.last_stop_share < MIN_LAST_STOP_SHARE:
        return False
    return lane.appt_error is None or lane.spread <= lane.appt_error


def estimate_arrival(order: dict, comments: Iterable[str], lanes: dict[tuple, Lane]) -> Optional[datetime]:
    """The calculated arrival on the destination's wall clock, or None when not proven."""
    # Departure only, as in the history: a truck still at the dock has not started this trip.
    anchor = anchor_for(order.get("pu_out"), comments, order.get("consignee"))
    if anchor is None:
        return None
    lane = lanes.get(_lane_key(order.get("consignee"), anchor))
    return anchor.at + timedelta(hours=lane.hours) if is_proven(lane) else None
