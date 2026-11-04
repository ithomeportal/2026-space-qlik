"""Pure classification: a fetched order → a report, a bucket and a display card.

No I/O here, so every rule is unit-tested without a database.

Buckets (template "TABLES ON THE EMAIL"; void/cancelled never reach here —
the SQL only reads A/P/D):
  IN PROGRESS  status P — picked up, not delivered.
  SCHEDULED    status A and the pickup window opens TODAY or earlier (CST,
               the Waco pickup's own clock) — "nothing from future".
  DELIVERED    status D and delivered within the last 24 hours, measured on
               the DESTINATION's clock: McLeod stores stop times as the stop's
               local wall time (El Paso/Juárez run an hour behind Chicago).
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Optional
from zoneinfo import ZoneInfo

from app.services.customer_status_email.config import (
    ORIGIN_CITY,
    ORIGIN_NAME,
    ORIGIN_STATE,
    ORIGIN_TZ,
    REPORTS,
    CustomerReport,
    Destination,
    match_destination,
    normalise,
)

IN_PROGRESS = "in_progress"
SCHEDULED = "scheduled"
DELIVERED = "delivered"
BUCKETS = (IN_PROGRESS, SCHEDULED, DELIVERED)

DELIVERED_WINDOW = timedelta(hours=24)
# A GPS fix older than this is not a "current location".
GPS_MAX_AGE = timedelta(hours=24)
# An ETA further past than this on a load not yet arrived is stale: it would sit in
# the headline block with a pill computed from a moment already gone.
ETA_STALE_GRACE = timedelta(minutes=30)
# A fix stamped later than this is bad data — it must not outrank a real one.
FUTURE_FIX_TOLERANCE = timedelta(minutes=10)

# McLeod brokerage_status of the ACTIVE leg → plain customer wording.
STATUS_LABELS = {
    "COVERED": "Covered", "LOADING": "Loading", "LOADED": "Loaded",
    "PROGRESS": "In transit", "BORDERXI": "Crossing the border",
    "CUSAGYRD": "At customs yard", "USYARD": "At US yard",
    "CARRIYAR": "At carrier yard", "DELIVER": "Delivered",
}
_CLOSED_LEGS = {"DELIVER", "VOID"}


@dataclass(frozen=True)
class Card:
    """Everything one load card shows. ``None`` renders as an em dash."""

    bucket: str
    order_id: str                       # trimmed McLeod order id
    po: Optional[str]
    trailer: Optional[str]
    bol: Optional[str]
    consignee: Optional[str]
    lane: str                           # "WACO, TX – DONNA, TX"
    pu_sched_early: Optional[datetime]
    pu_sched_late: Optional[datetime]
    pu_in: Optional[datetime]
    pu_out: Optional[datetime]
    del_sched_early: Optional[datetime]
    del_sched_late: Optional[datetime]
    del_in: Optional[datetime]
    del_out: Optional[datetime]
    pu_on_time: Optional[bool] = None
    del_on_time: Optional[bool] = None
    status_label: Optional[str] = None
    location: Optional[str] = None      # "CHRISTINE, TX"
    location_at: Optional[datetime] = None
    last_reported: Optional[str] = None  # the yard the load waits at, when no recent fix
    eta: Optional[datetime] = None      # final-stop ETA on the stop's clock, else leg ETA (CST)
    pu_eta: Optional[datetime] = None   # McLeod origin_eta, until the truck reaches the pickup
    eta_place: Optional[str] = None     # set when the ETA is to an intermediate leg
    eta_is_cst: bool = False            # intermediate-leg ETA stays on the CST clock
    hours_vs_appt: Optional[float] = None  # +behind / −ahead, final leg only
    comment: Optional[str] = None
    track_link: Optional[str] = None
    pod_link: Optional[str] = None
    has_pod: bool = False
    sort_key: datetime = field(default=datetime.max, compare=False)

    @property
    def arrived_at(self) -> Optional[datetime]:
        """When the truck reached the consignee; a departure alone also proves it."""
        return self.del_in or self.del_out


@dataclass(frozen=True)
class ReportCards:
    report: CustomerReport
    in_progress: tuple[Card, ...]
    scheduled: tuple[Card, ...]
    delivered: tuple[Card, ...]

    def is_empty(self) -> bool:
        return not (self.in_progress or self.scheduled or self.delivered)

    def counts(self) -> dict[str, int]:
        return {IN_PROGRESS: len(self.in_progress), SCHEDULED: len(self.scheduled),
                DELIVERED: len(self.delivered)}


def is_waco_pickup(order: dict) -> bool:
    return (normalise(order.get("origin_city")) == ORIGIN_CITY
            and normalise(order.get("origin_state")) == ORIGIN_STATE)


def bucket_for(order: dict, dest: Destination, now_cst: datetime) -> Optional[str]:
    """The section this order belongs to, or None when it is in none of them."""
    status = (order.get("status") or "").strip()
    if status == "P":
        return IN_PROGRESS
    if status == "A":
        opens = order.get("pu_sched_early") or order.get("pu_sched_late")
        today = now_cst.astimezone(ZoneInfo(ORIGIN_TZ)).date()
        # No window at all cannot be proven future — keep it visible.
        return SCHEDULED if opens is None or opens.date() <= today else None
    if status == "D":
        done = order.get("del_out") or order.get("del_in")
        if done is None:
            return None
        local_now = now_cst.astimezone(ZoneInfo(dest.tz)).replace(tzinfo=None)
        return DELIVERED if local_now - done <= DELIVERED_WINDOW else None
    return None


def on_time(actual: Optional[datetime], deadline: Optional[datetime]) -> Optional[bool]:
    """Arrived no later than the window's LATE edge; unknown when either is missing."""
    if actual is None or deadline is None:
        return None
    return actual <= deadline


# McLeod stop comments: "<verb> <PLACE, CITY, ST> at|for MM/DD/YY HHMM[ to MM/DD/YY HHMM]."
_MCLEOD_TS = r"(\d\d/\d\d/\d\d) (\d\d)(\d\d)"
_EMPTY_AT = re.compile(rf"^Empty at consignee (?P<place>.+?) at {_MCLEOD_TS}\.?$")
_STOP_PATTERNS = (
    # (regex, wording at a border yard, wording at the Waco shipper) — {place} is
    # the stop, {at} / {to} formatted times.
    (_EMPTY_AT,
     "At {place} for customs clearance since {at}.",
     "At {place} since {at}."),
    (re.compile(rf"^Departed (?P<place>.+?) at {_MCLEOD_TS}\.?$"),
     "Cleared customs and departed {place} on {at}; continuing to final destination.",
     "Departed {place} on {at}."),
    (re.compile(rf"^Appointment confirmed at (?P<place>.+?) for {_MCLEOD_TS} to "
                rf"(\d\d/\d\d/\d\d) (\d\d)(\d\d)\.?$"),
     "Border crossing appointment confirmed at {place}: {at} to {to}.",
     "Pickup appointment confirmed at {place}: {at} to {to}."),
    (re.compile(rf"^Loaded at the shipper (?P<place>.+?) at {_MCLEOD_TS}\.?$"),
     "Loaded at the shipper {place} on {at}.",
     "Loaded at the shipper {place} on {at}."),
)


def _fmt_mcleod(day: str, hh: str, mm: str) -> str:
    """'10/15/26', '13', '00' -> '10/15/2026 @ 01:00 PM'."""
    h = int(hh)
    return f"{day[:6]}20{day[6:]} @ {h % 12 or 12:02d}:{mm} {'AM' if h < 12 else 'PM'}"


def _is_own_consignee(place: str, consignee: Optional[str]) -> bool:
    final = normalise(consignee)
    return bool(final) and normalise(place).startswith(final)


def _is_origin(place: str) -> bool:
    """The Waco shipper — where the load starts, so never a border yard.

    McLeod comments name it with or without its city ("Loaded at the shipper
    Central Texas Corrugated at …").
    """
    name = normalise(place)
    return name.startswith(ORIGIN_NAME) or name.endswith(f"{ORIGIN_CITY}, {ORIGIN_STATE}")


def last_reported_place(comment: Optional[str], consignee: Optional[str]) -> Optional[str]:
    """The yard a load is waiting at, read from its newest stop comment.

    Only "Empty at consignee <yard>" places the truck there: "Departed" means it
    left and "Appointment confirmed" means it has not arrived yet.
    """
    m = _EMPTY_AT.match((comment or "").strip())
    if not m or _is_own_consignee(m.group("place"), consignee) or _is_origin(m.group("place")):
        return None
    return m.group("place")


def customer_comment(comment: Optional[str], consignee: Optional[str]) -> Optional[str]:
    """Reword a stop comment that names a BORDER TRANSFER YARD, not the consignee.

    Cross-border PCA loads are SPLIT: the US leg ends at a yard (EC Logistics
    Pharr, ACG Global / Alfredo Casso Laredo, SouthWest Yard El Paso, FEMA /
    Forza / Trancasa Nuevo Laredo), waits for customs clearance, then the
    Mexican leg continues. McLeod closes the US leg as delivered, so its comment
    reads "Empty at consignee TRANCASA EL PASO …" — accurate, but a customer
    reads it as a delivery (user, 2026-10-20). A comment that names the order's
    own consignee is left as is, and the Waco shipper is worded as a pickup: "not
    the consignee" alone called it a border yard (report of 2026-11-04).
    """
    if not comment:
        return comment
    for pattern, at_yard, at_origin in _STOP_PATTERNS:
        m = pattern.match(comment.strip())
        if not m:
            continue
        if _is_own_consignee(m.group("place"), consignee):
            return comment
        wording = at_origin if _is_origin(m.group("place")) else at_yard
        g = m.groups()
        to = _fmt_mcleod(*g[4:7]) if len(g) >= 7 else ""
        return wording.format(place=m.group("place"), at=_fmt_mcleod(*g[1:4]), to=to)
    return comment


def _active_leg(moves: list[dict]) -> Optional[dict]:
    ordered = sorted(moves, key=lambda m: _num(m.get("movement_id")))
    for m in ordered:
        if (m.get("brokerage_status") or "").strip() not in _CLOSED_LEGS:
            return m
    return ordered[-1] if ordered else None


def _num(value: object) -> int:
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return 0


def utc_to_local(value: datetime, tz: str) -> datetime:
    """Naive UTC digits → the same instant as naive wall time in ``tz``."""
    return value.replace(tzinfo=timezone.utc).astimezone(ZoneInfo(tz)).replace(tzinfo=None)


def _final_eta(eta_local: datetime, order: dict) -> dict:
    """An ETA to the final stop, with hours against the appointment when there is one."""
    deadline = order.get("del_sched_late")
    hours = {"hours_vs_appt": round((eta_local - deadline).total_seconds() / 3600, 1)} if deadline else {}
    return {"eta": eta_local, **hours}


def _tracking(order: dict, legs: list[dict], active: Optional[dict],
              now_cst: datetime, dest_tz: str) -> dict:
    """The ETA and ahead/behind: McLeod's final-stop ETA, else Augie (movement grain).

    McLeod's stop ETA (``destin_eta``,
    the field Ops chose 2026-11-03) is order-grain and on the stop's clock.

    ⚠ Two clocks: Augie's ``new_eta`` holds naive UTC digits (measured 2026-10-23 and
    2026-11-04; augie-app CLAUDE.md), while McLeod's times are the STOP's local
    clock. The ETA is converted to the destination's clock before it is subtracted
    or printed — printed as CST it read "11.3 Hours BEHIND" for a true 5.3.

    ⚠ On a cross-border load Augie's ETA is to the CURRENT leg's end (e.g. the
    Laredo yard), not the consignee — so hours ahead/behind is shown only when
    that leg ends in the order's destination city; otherwise the ETA is labelled
    with the leg's own destination and carries no pill.
    """
    mcleod_eta = order.get("del_eta")
    stop_now = now_cst.astimezone(ZoneInfo(dest_tz)).replace(tzinfo=None)
    if mcleod_eta and mcleod_eta >= stop_now - ETA_STALE_GRACE:
        return _final_eta(mcleod_eta, order)

    out: dict = {}
    utc_now = now_cst.astimezone(timezone.utc).replace(tzinfo=None)

    active_id = str((active or {}).get("movement_id") or "").strip()
    leg = next((lg for lg in legs if str(lg.get("movement_id") or "").strip() == active_id), None)
    # An ETA already in the past on a load still moving is stale, not news:
    # measured 2026-10-20, Augie kept yesterday's ETA on loads at the border
    # and the pill read "53.3 Hours AHEAD".
    if leg and leg.get("eta") and leg["eta"] >= utc_now - ETA_STALE_GRACE:
        if normalise(leg.get("leg_dest_city")) == normalise(order.get("dest_city")):
            return _final_eta(utc_to_local(leg["eta"], dest_tz), order)
        out["eta"] = utc_to_local(leg["eta"], ORIGIN_TZ)
        out["eta_is_cst"] = True
        out["eta_place"] = ", ".join(
            p for p in (leg.get("leg_dest_city"), leg.get("leg_dest_state")) if p)
    return out


def _pickup_eta(order: dict, now_cst: datetime) -> Optional[datetime]:
    """McLeod's ``origin_eta``, until the truck reaches the (Waco) pickup."""
    eta = order.get("pu_eta")
    if not eta or order.get("pu_in") or order.get("pu_out"):
        return None
    waco_now = now_cst.astimezone(ZoneInfo(ORIGIN_TZ)).replace(tzinfo=None)
    return eta if eta >= waco_now - ETA_STALE_GRACE else None


def best_location(candidates: list[tuple[Optional[str], Optional[datetime]]],
                  naive_now: datetime) -> dict:
    """The FRESHEST (place, CST time) among every source, if within GPS_MAX_AGE.

    Sources (2026-10-20): Augie GPS per leg, Augie phone/e-mail pings, and
    TTControl (carrier share-link polls + MacroPoint). Each covers different
    loads — share links mostly the Mexican leg Augie never sees. A future stamp is
    bad data: "freshest" would otherwise let it beat every real fix.
    """
    valid = [(place, at) for place, at in candidates
             if place and at and -FUTURE_FIX_TOLERANCE <= naive_now - at <= GPS_MAX_AGE]
    if not valid:
        return {}
    place, at = max(valid, key=lambda c: c[1])
    return {"location": place, "location_at": at}


def _location_candidates(legs: list[dict], ping: Optional[dict], tt: Optional[dict]) -> list:
    def join(*parts: Optional[str]) -> Optional[str]:
        text = ", ".join(p for p in parts if p)
        return text or None
    # Augie's gps_updated_dt holds UTC digits; everything here compares on the CST clock.
    cands = [(join(lg.get("geo_city"), lg.get("geo_state")),
              utc_to_local(lg["gps_at"], ORIGIN_TZ) if lg.get("gps_at") else None) for lg in legs]
    if ping:
        cands.append((join(ping.get("city"), ping.get("state")), ping.get("at_cst")))
    if tt:
        cands.append((tt.get("place"), tt.get("at_cst")))
    return cands


def build_card(order: dict, bucket: str, details: dict, now_cst: datetime,
               dest_tz: str = ORIGIN_TZ) -> Card:
    oid = order["id"].strip()
    moves = details.get("movements", {}).get(oid, [])
    active = _active_leg(moves)
    legs = details.get("augie", {}).get(oid, [])
    tt = details.get("tt", {}).get(oid) or {}
    tracking = {}
    arrived = bool(order.get("del_in") or order.get("del_out"))
    # A load at its consignee needs neither an ETA nor an earlier fix from the road.
    if bucket == IN_PROGRESS and not arrived:
        tracking = {
            **_tracking(order, legs, active, now_cst, dest_tz),
            **best_location(_location_candidates(legs, details.get("pings", {}).get(oid), tt),
                            now_cst.replace(tzinfo=None)),
        }
    # A carrier live-share link (the template's Samsara example) beats MacroPoint.
    link = tt.get("share_link") or (active or {}).get("track_link") or next(
        (m["track_link"] for m in sorted(moves, key=lambda m: -_num(m.get("movement_id")))
         if m.get("track_link")), None)
    comment = details.get("comments", {}).get(oid)
    raw_comment = (comment or {}).get("comment")
    if bucket == IN_PROGRESS and "location" not in tracking and not arrived:
        tracking = {**tracking,
                    "last_reported": last_reported_place(raw_comment, order.get("consignee"))}
    pod = details.get("pods", {}).get(oid) or {}
    status_code = ((active or {}).get("brokerage_status") or "").strip()
    sort_key = {
        IN_PROGRESS: order.get("del_sched_late"),
        SCHEDULED: order.get("pu_sched_early") or order.get("pu_sched_late"),
        DELIVERED: order.get("del_out") or order.get("del_in"),
    }[bucket] or datetime.max
    return Card(
        bucket=bucket,
        order_id=oid,
        po=order.get("po"),
        trailer=order.get("trailer"),
        bol=order.get("bol"),
        consignee=order.get("consignee"),
        lane=_lane(order),
        pu_sched_early=order.get("pu_sched_early"),
        pu_sched_late=order.get("pu_sched_late"),
        pu_in=order.get("pu_in"),
        pu_out=order.get("pu_out"),
        del_sched_early=order.get("del_sched_early"),
        del_sched_late=order.get("del_sched_late"),
        del_in=order.get("del_in"),
        del_out=order.get("del_out"),
        pu_on_time=on_time(order.get("pu_in"), order.get("pu_sched_late")),
        del_on_time=on_time(order.get("del_in"), order.get("del_sched_late")),
        status_label=STATUS_LABELS.get(status_code) if bucket == IN_PROGRESS else None,
        comment=customer_comment(raw_comment, order.get("consignee"))
        if bucket == IN_PROGRESS else None,
        pu_eta=_pickup_eta(order, now_cst) if bucket != DELIVERED else None,
        track_link=link if bucket == IN_PROGRESS else None,
        pod_link=pod.get("pod_file_url") if bucket == DELIVERED else None,
        has_pod=bool(pod.get("has_pod")) if bucket == DELIVERED else False,
        sort_key=sort_key,
        **tracking,
    )


def _lane(order: dict) -> str:
    def place(city: Optional[str], state: Optional[str]) -> str:
        return ", ".join(p for p in (city, state) if p)
    return (f"{place(order.get('origin_city'), order.get('origin_state'))} – "
            f"{place(order.get('dest_city'), order.get('dest_state'))}")


def assign(orders: list[dict], details: dict, now_cst: datetime) -> tuple[
        dict[str, ReportCards], list[str]]:
    """Partition every fetched order into its report and bucket.

    Returns the cards per report key, plus the consignee names of ACTIVE Waco
    loads that matched no report (logged by the sender, so a renamed consignee
    is noticed instead of silently disappearing from a customer's e-mail).
    """
    if now_cst.tzinfo is None:
        raise ValueError("now_cst must be timezone-aware (a naive value reads as UTC)")
    grouped: dict[str, dict[str, list[Card]]] = {
        r.key: {b: [] for b in BUCKETS} for r in REPORTS}
    unmatched: set[str] = set()
    for order in orders:
        if not is_waco_pickup(order):
            continue
        hit = False
        for report in REPORTS:
            dest = match_destination(report, order.get("consignee"), order.get("delivery_location"))
            if dest is None:
                continue
            hit = True
            bucket = bucket_for(order, dest, now_cst)
            if bucket:
                grouped[report.key][bucket].append(
                    build_card(order, bucket, details, now_cst, dest.tz))
            break
        if not hit and (order.get("status") or "").strip() in ("A", "P"):
            unmatched.add(order.get("consignee") or "(no consignee)")

    result = {}
    for report in REPORTS:
        g = grouped[report.key]
        result[report.key] = ReportCards(
            report=report,
            in_progress=tuple(sorted(g[IN_PROGRESS], key=lambda c: c.sort_key)),
            scheduled=tuple(sorted(g[SCHEDULED], key=lambda c: c.sort_key)),
            delivered=tuple(sorted(g[DELIVERED], key=lambda c: c.sort_key, reverse=True)),
        )
    return result, sorted(unmatched)
