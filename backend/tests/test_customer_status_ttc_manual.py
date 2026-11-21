"""TTControl ``manualUpdate`` in the PCA/CTC customer e-mail (owner decision 2026-11-20).

TTControl's ``/api/share/customer-tracking`` now also returns the newest update an ops
user typed: ``{location, comment, etaUtc, enteredAtUtc} | null``. It feeds:
  • the ETA chain: McLeod ``destin_eta`` > TTC manual ETA > Augie ``new_eta`` > estimate;
  • ``best_location`` as one more candidate stamped ``enteredAtUtc``.
The ETA-coverage headline still counts only McLeod-keyed ETAs.
docs/SPEC-CUSTOMER-STATUS-EMAIL.md §5e.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from app.services.customer_status_email import cards, config, data, html

CST = ZoneInfo("America/Chicago")
NOW = datetime(2026, 10, 20, 12, 0, tzinfo=CST)          # 17:00 UTC
NAIVE_NOW = NOW.replace(tzinfo=None)
NAIVE_UTC = NOW.astimezone(timezone.utc).replace(tzinfo=None)
OID = "0349842"
DONNA = config.REPORTS_BY_KEY["pca-donna"]


def _order(**kw) -> dict:
    base = dict(
        id=f"{OID} ", company_id="TMS ", status="P", origin_city="WACO", origin_state="TX",
        dest_city="DONNA", dest_state="TX", po="C-1019-12", bol="206-1", trailer="26199",
        consignee="PCA DONNA", delivery_location="DONNA, TX",
        pu_sched_early=datetime(2026, 10, 20, 1), pu_sched_late=datetime(2026, 10, 20, 1),
        pu_in=datetime(2026, 10, 19, 16, 36), pu_out=datetime(2026, 10, 20, 8),
        del_sched_early=datetime(2026, 10, 20, 18), del_sched_late=datetime(2026, 10, 20, 18),
        del_in=None, del_out=None,
    )
    base.update(kw)
    return base


def _manual(eta_utc=datetime(2026, 10, 20, 23, 0), entered_cst=NAIVE_NOW - timedelta(minutes=20),
            location="Heth, AR", comment="Driver at fuel stop") -> dict:
    return {"location": location, "comment": comment, "eta_utc": eta_utc,
            "entered_cst": entered_cst}


def _details(manual=None, augie_eta=None, gps_at=None, estimate=None) -> dict:
    return {
        "movements": {OID: [{"movement_id": "572650", "brokerage_status": "PROGRESS"}]},
        "augie": {OID: [{"movement_id": "572650", "leg_dest_city": "DONNA",
                         "leg_dest_state": "TX", "eta": augie_eta, "geo_city": "CHRISTINE",
                         "geo_state": "TX", "gps_at": gps_at}]},
        "comments": {},
        "pods": {},
        "tt": {OID: {"share_link": None, "place": None, "at_cst": None, "manual": manual}},
        "estimates": {OID: estimate} if estimate else {},
    }


def _card(order=None, det=None, tz=config.ORIGIN_TZ):
    return cards.build_card(order or _order(), cards.IN_PROGRESS, det or _details(), NOW, tz)


# --- parse -------------------------------------------------------------------

def _payload(manual, include_key=True) -> dict:
    row = {"shareLink": None, "position": None}
    if include_key:
        row["manualUpdate"] = manual
    return {"success": True, "data": {OID: row}}


def test_a_valid_manual_update_is_parsed_and_moved_to_cst():
    got = data.parse_ttcontrol(_payload({
        "location": "  Heth,   AR ", "comment": " Driver at fuel stop\n",
        "etaUtc": "2026-11-16T10:00:00Z", "enteredAtUtc": "2026-11-15T23:30:00+00:00"}))
    m = got[OID]["manual"]
    assert m == {"location": "Heth, AR", "comment": "Driver at fuel stop",
                 "eta_utc": datetime(2026, 11, 16, 10, 0),
                 "entered_cst": datetime(2026, 11, 15, 17, 30)}  # CST = UTC-6


def test_an_older_response_without_the_key_still_parses():
    got = data.parse_ttcontrol(_payload(None, include_key=False))
    assert got[OID]["manual"] is None and got[OID]["share_link"] is None
    assert data.parse_ttcontrol(_payload(None))[OID]["manual"] is None


def test_malformed_manual_updates_are_dropped_never_raise():
    good = {"location": "Heth, AR", "etaUtc": "2026-11-16T10:00:00Z",
            "enteredAtUtc": "2026-11-15T23:30:00Z"}
    for bad in ("text", 7, [good],
                {**good, "location": ""}, {**good, "location": "   "}, {**good, "location": 5},
                {**good, "enteredAtUtc": None}, {**good, "enteredAtUtc": "yesterday"},
                {**good, "enteredAtUtc": "2026-11-15T23:30:00"},          # no offset
                {**good, "enteredAtUtc": "2026-11-15T17:30:00-06:00"}):   # not UTC
        assert data.parse_ttcontrol(_payload(bad))[OID]["manual"] is None, bad


def test_a_bad_eta_drops_only_the_eta_and_text_is_capped():
    got = data.parse_ttcontrol(_payload({
        "location": "X" * 500, "comment": "c" * 900, "etaUtc": "2026-11-16 10:00",
        "enteredAtUtc": "2026-11-15T23:30:00Z"}))[OID]["manual"]
    assert got["eta_utc"] is None
    assert len(got["location"]) == data.MANUAL_LOCATION_MAX == 120
    assert len(got["comment"]) == data.MANUAL_COMMENT_MAX == 300
    no_comment = data.parse_ttcontrol(_payload({
        "location": "Heth, AR", "comment": None, "etaUtc": None,
        "enteredAtUtc": "2026-11-15T23:30:00Z"}))[OID]["manual"]
    assert no_comment["comment"] is None and no_comment["eta_utc"] is None


# --- ETA precedence: McLeod > TTC > Augie > estimate -------------------------

def test_mcleod_keyed_eta_beats_the_ttc_eta():
    c = _card(_order(del_eta=datetime(2026, 10, 20, 16, 0)), _details(_manual()))
    assert c.eta_source == cards.MCLEOD and c.eta == datetime(2026, 10, 20, 16, 0)


def test_ttc_eta_beats_augie_and_is_moved_to_the_stop_clock():
    # 23:00 UTC = 18:00 CDT at Donna = the appointment ⇒ "On schedule".
    c = _card(det=_details(_manual(), augie_eta=datetime(2026, 10, 21, 1, 30)))
    assert c.eta_source == cards.TTC
    assert c.eta == datetime(2026, 10, 20, 18, 0) and c.hours_vs_appt == 0.0
    assert c.eta_place is None and c.eta_is_cst is False


def test_ttc_eta_uses_the_destination_clock_not_cst():
    c = _card(_order(dest_city="EL PASO", del_sched_late=datetime(2026, 10, 20, 16, 0)),
              _details(_manual()), "America/Denver")
    assert c.eta == datetime(2026, 10, 20, 17, 0) and c.hours_vs_appt == 1.0


def test_a_stale_mcleod_eta_falls_to_ttc_and_keeps_eta_passed():
    passed = NAIVE_NOW - timedelta(hours=3)
    c = _card(_order(del_eta=passed), _details(_manual()))
    assert c.eta_source == cards.TTC and c.eta_passed == passed


def test_a_stale_ttc_eta_is_skipped_for_augie():
    # 16:00 UTC is an hour past at 17:00 UTC.
    det = _details(_manual(eta_utc=NAIVE_UTC - timedelta(hours=1)),
                   augie_eta=datetime(2026, 10, 21, 1, 30))
    c = _card(det=det)
    assert c.eta_source == cards.AUGIE and c.eta == datetime(2026, 10, 20, 20, 30)


def test_ttc_eta_within_the_grace_is_still_shown():
    c = _card(det=_details(_manual(eta_utc=NAIVE_UTC - timedelta(minutes=15))))
    assert c.eta_source == cards.TTC


def test_ttc_eta_suppresses_the_estimate_and_a_stale_one_lets_it_back():
    est = datetime(2026, 10, 20, 19, 0)
    assert _card(det=_details(_manual(), estimate=est)).est_eta is None
    c = _card(det=_details(_manual(eta_utc=NAIVE_UTC - timedelta(hours=2)), estimate=est))
    assert c.eta_source is None and c.est_eta == est


def test_ttc_eta_renders_like_any_delivery_eta_without_naming_ttcontrol():
    out = html.card_in_progress(_card(det=_details(_manual())))
    assert "ETA to delivery" in out and "10/20/2026" in out
    assert "ttcontrol" not in out.lower() and "ttc" not in out.lower()


# --- coverage ----------------------------------------------------------------

def test_coverage_does_not_count_a_ttc_eta_as_keyed():
    keyed = _card(_order(del_eta=datetime(2026, 10, 20, 16, 0)), _details(_manual()))
    ttc = _card(det=_details(_manual()))
    rc = cards.ReportCards(report=DONNA, in_progress=(keyed, ttc), scheduled=(), delivered=())
    cov = cards.eta_coverage(rc)
    assert cov["open"] == 2 and cov["keyed"] == 1 and cov["ttc"] == 1
    assert [m["shownInstead"] for m in cov["missing"]] == ["ttc"]
    assert rc.log_counts()["eta_keyed"] == 1


# --- location ----------------------------------------------------------------

def test_a_fresher_manual_location_beats_an_older_gps_fix():
    c = _card(det=_details(_manual(), gps_at=NAIVE_UTC - timedelta(hours=2)))
    assert c.location == "Heth, AR" and c.location_at == NAIVE_NOW - timedelta(minutes=20)


def test_a_fresher_gps_fix_beats_the_manual_location():
    c = _card(det=_details(_manual(entered_cst=NAIVE_NOW - timedelta(hours=3)),
                           gps_at=NAIVE_UTC - timedelta(minutes=5)))
    assert c.location == "CHRISTINE, TX"


def test_a_manual_location_older_than_24h_or_future_dated_is_ignored():
    old = _card(det=_details(_manual(entered_cst=NAIVE_NOW - timedelta(hours=30), eta_utc=None)))
    assert old.location is None
    future = _card(det=_details(_manual(entered_cst=NAIVE_NOW + timedelta(hours=1), eta_utc=None)))
    assert future.location is None


def test_the_manual_comment_is_not_shown_to_the_customer():
    """Ops free text has no customer-safe allow-list (§6) — not used as the card comment."""
    c = _card(det=_details(_manual(comment="Driver not answering, sleeping")))
    assert c.comment is None
