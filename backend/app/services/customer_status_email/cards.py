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
from datetime import datetime, timedelta
from typing import Optional
from zoneinfo import ZoneInfo

from app.services.customer_status_email.config import (
    ORIGIN_CITY,
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
ETA_STALE_GRACE = timedelta(hours=2)

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
    eta: Optional[datetime] = None
    eta_place: Optional[str] = None     # set when the ETA is to an intermediate leg
    eta_is_cst: bool = False            # intermediate-leg ETA stays on the CST clock
    hours_vs_appt: Optional[float] = None  # +behind / −ahead, final leg only
    comment: Optional[str] = None
    track_link: Optional[str] = None
    pod_link: Optional[str] = None
    has_pod: bool = False
    sort_key: datetime = field(default=datetime.max, compare=False)


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
_YARD_PATTERNS = (
    # (regex, customer wording) — {place} is the yard, {at} / {to} formatted times.
    (re.compile(rf"^Empty at consignee (?P<place>.+?) at {_MCLEOD_TS}\.?$"),
     "At {place} for customs clearance since {at}."),
    (re.compile(rf"^Departed (?P<place>.+?) at {_MCLEOD_TS}\.?$"),
     "Cleared customs and departed {place} on {at}; continuing to final destination."),
    (re.compile(rf"^Appointment confirmed at (?P<place>.+?) for {_MCLEOD_TS} to "
                rf"(\d\d/\d\d/\d\d) (\d\d)(\d\d)\.?$"),
     "Border crossing appointment confirmed at {place}: {at} to {to}."),
)


def _fmt_mcleod(day: str, hh: str, mm: str) -> str:
    """'10/15/26', '13', '00' -> '10/15/2026 @ 01:00 PM'."""
    h = int(hh)
    return f"{day[:6]}20{day[6:]} @ {h % 12 or 12:02d}:{mm} {'AM' if h < 12 else 'PM'}"


def customer_comment(comment: Optional[str], consignee: Optional[str]) -> Optional[str]:
    """Reword a stop comment that names a BORDER TRANSFER YARD, not the consignee.

    Cross-border PCA loads are SPLIT: the US leg ends at a yard (EC Logistics
    Pharr, ACG Global / Alfredo Casso Laredo, SouthWest Yard El Paso, FEMA /
    Forza / Trancasa Nuevo Laredo), waits for customs clearance, then the
    Mexican leg continues. McLeod closes the US leg as delivered, so its comment
    reads "Empty at consignee TRANCASA EL PASO …" — accurate, but a customer
    reads it as a delivery (user, 2026-10-20). A comment that names the order's
    own consignee is left as is.
    """
    if not comment:
        return comment
    final = normalise(consignee)
    for pattern, wording in _YARD_PATTERNS:
        m = pattern.match(comment.strip())
        if not m:
            continue
        if final and normalise(m.group("place")).startswith(final):
            return comment
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


def cst_to_local(value: datetime, tz: str) -> datetime:
    """A naive CST wall time → the same instant as naive wall time in ``tz``."""
    return value.replace(tzinfo=ZoneInfo(ORIGIN_TZ)).astimezone(ZoneInfo(tz)).replace(tzinfo=None)


def _tracking(order: dict, legs: list[dict], active: Optional[dict],
              now_cst: datetime, dest_tz: str) -> dict:
    """Last GPS city, ETA and ahead/behind from the Augie feed (movement grain).

    ⚠ Two clocks: Augie's ``new_eta`` / ``gps_updated_dt`` are naive CST (its own
    app compares them with NOW() in Chicago), while McLeod appointments are the
    STOP's local time. The ETA is converted to the destination's clock before it
    is subtracted or printed — else an El Paso load reads an hour late.

    ⚠ On a cross-border load Augie's ETA is to the CURRENT leg's end (e.g. the
    Laredo yard), not the consignee — so hours ahead/behind is shown only when
    that leg ends in the order's destination city; otherwise the ETA is labelled
    with the leg's own destination and carries no pill.
    """
    out: dict = {}
    naive_now = now_cst.replace(tzinfo=None)

    active_id = str((active or {}).get("movement_id") or "").strip()
    leg = next((lg for lg in legs if str(lg.get("movement_id") or "").strip() == active_id), None)
    # An ETA already in the past on a load still moving is stale, not news:
    # measured 2026-10-20, Augie kept yesterday's ETA on loads at the border
    # and the pill read "53.3 Hours AHEAD". The grace covers the stop's local
    # clock running up to an hour behind CST.
    if leg and leg.get("eta") and leg["eta"] >= naive_now - ETA_STALE_GRACE:
        final = normalise(leg.get("leg_dest_city")) == normalise(order.get("dest_city"))
        eta_local = cst_to_local(leg["eta"], dest_tz) if final else leg["eta"]
        out["eta"] = eta_local
        out["eta_is_cst"] = not final
        deadline = order.get("del_sched_late") if final else None
        if final and deadline:
            out["hours_vs_appt"] = round((eta_local - deadline).total_seconds() / 3600, 1)
        elif not final:
            out["eta_place"] = ", ".join(
                p for p in (leg.get("leg_dest_city"), leg.get("leg_dest_state")) if p)
    return out


def best_location(candidates: list[tuple[Optional[str], Optional[datetime]]],
                  naive_now: datetime) -> dict:
    """The FRESHEST (place, CST time) among every source, if within GPS_MAX_AGE.

    Sources (2026-10-20): Augie GPS per leg, Augie phone/e-mail pings, and
    TTControl (carrier share-link polls + MacroPoint). Each covers different
    loads — share links mostly the Mexican leg Augie never sees.
    """
    valid = [(place, at) for place, at in candidates
             if place and at and naive_now - at <= GPS_MAX_AGE]
    if not valid:
        return {}
    place, at = max(valid, key=lambda c: c[1])
    return {"location": place, "location_at": at}


def _location_candidates(legs: list[dict], ping: Optional[dict], tt: Optional[dict]) -> list:
    def join(*parts: Optional[str]) -> Optional[str]:
        text = ", ".join(p for p in parts if p)
        return text or None
    cands = [(join(lg.get("geo_city"), lg.get("geo_state")), lg.get("gps_at")) for lg in legs]
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
    if bucket == IN_PROGRESS:
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
        comment=customer_comment((comment or {}).get("comment"), order.get("consignee"))
        if bucket == IN_PROGRESS else None,
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
