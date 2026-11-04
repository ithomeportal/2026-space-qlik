"""The calculated arrival and the ETA coverage panel (customer status e-mails)."""
from __future__ import annotations

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from app.services.customer_status_email import cards, config, data, estimate, html, sender

CST = ZoneInfo("America/Chicago")
NOW = datetime(2026, 11, 4, 12, 0, tzinfo=CST)
NAIVE_NOW = NOW.replace(tzinfo=None)
DONNA = config.REPORTS_BY_KEY["pca-donna"]
YARD = "EC Logistics, PHARR, TX"


def _trip(n, consignee="PCA DONNA", hours=10.0, appt_miss=6.0):
    start = datetime(2026, 9, 1) + timedelta(days=n)
    arrived = start + timedelta(hours=hours)
    return dict(id=f"{n:07d} ", consignee=consignee, pu_out=start, del_in=arrived,
                del_sched_late=arrived + timedelta(hours=appt_miss))


def _order(**kw):
    base = dict(id="0351802 ", company_id="TMS ", status="P", origin_city="WACO", origin_state="TX",
                dest_city="DONNA", dest_state="TX", po="C-1103-9", bol="1", trailer="1211",
                consignee="PCA DONNA", delivery_location="DONNA, TX",
                pu_sched_early=None, pu_sched_late=None, pu_in=datetime(2026, 11, 4, 8),
                pu_out=datetime(2026, 11, 4, 9), del_sched_early=None,
                del_sched_late=datetime(2026, 11, 4, 22), del_in=None, del_out=None)
    return {**base, **kw}


def _lanes(n=estimate.MIN_SAMPLES, **kw):
    return estimate.build_lanes([_trip(i, **kw) for i in range(n)], {})


# --- anchors ---------------------------------------------------------------

def test_a_load_with_no_yard_counts_from_the_pickup():
    a = estimate.anchor_for(datetime(2026, 11, 4, 9), [], "PCA DONNA")
    assert a.kind == estimate.PICKUP and a.at == datetime(2026, 11, 4, 9)


def test_a_truck_that_left_a_yard_counts_from_that_yard():
    a = estimate.anchor_for(datetime(2026, 11, 1), [
        f"Empty at consignee {YARD} at 11/02/26 0700.", f"Departed {YARD} at 11/03/26 0900."],
        "WOORI")
    assert a.kind == estimate.YARD and a.place == YARD.upper() and a.at == datetime(2026, 11, 3, 9)


def test_a_truck_waiting_at_a_yard_gets_no_anchor():
    """Border waits run for days and do not predict."""
    assert estimate.anchor_for(datetime(2026, 11, 1), [
        "Departed ACG Global, LAREDO, TX at 11/02/26 0700.",
        f"Empty at consignee {YARD} at 11/03/26 0900."], "WOORI") is None


def test_arrival_and_departure_stamped_alike_mean_it_left():
    assert estimate.anchor_for(None, [f"Departed {YARD} at 11/03/26 0900.",
                                      f"Empty at consignee {YARD} at 11/03/26 0900."],
                               "WOORI").kind == estimate.YARD


def test_the_shipper_and_the_consignee_are_not_yards():
    a = estimate.anchor_for(datetime(2026, 11, 1), [
        "Departed Central Texas Corrugated, WACO, TX at 11/02/26 0700.",
        "Empty at consignee WOORI, REYNOSA, TM at 11/03/26 0900."], "WOORI")
    assert a.kind == estimate.PICKUP


def test_replaying_history_ignores_what_happened_after_delivery():
    a = estimate.anchor_for(datetime(2026, 11, 1), [f"Departed {YARD} at 11/05/26 0900."],
                            "WOORI", before=datetime(2026, 11, 4))
    assert a.kind == estimate.PICKUP


def test_an_impossible_time_in_a_comment_is_ignored():
    assert estimate.parse_event(f"Departed {YARD} at 13/45/26 2500.") is None
    assert estimate.parse_event("In transit") is None and estimate.parse_event(None) is None


# --- the proof a lane must give ---------------------------------------------

def test_a_proven_lane_estimates_median_transit_from_the_anchor():
    assert estimate.estimate_arrival(_order(), [], _lanes()) == datetime(2026, 11, 4, 19)


def test_too_few_trips_is_not_proof():
    assert estimate.estimate_arrival(_order(), [], _lanes(estimate.MIN_SAMPLES - 1)) is None


def test_a_scattered_lane_is_not_proof():
    trips = [_trip(i, hours=10 if i % 2 else 80, appt_miss=500) for i in range(20)]
    assert estimate.estimate_arrival(_order(), [], estimate.build_lanes(trips, {})) is None


def test_a_lane_where_the_appointment_is_closer_is_not_proof():
    """Trucks that simply run to their appointment: quoting it is more accurate."""
    trips = [_trip(i, hours=10 + (i % 5), appt_miss=0.5) for i in range(20)]
    assert estimate.estimate_arrival(_order(), [], estimate.build_lanes(trips, {})) is None


def test_only_the_newest_trips_of_a_lane_count():
    old = [_trip(i, hours=50) for i in range(30)]
    new = [_trip(100 + i, hours=10) for i in range(estimate.WINDOW)]
    lane = next(iter(estimate.build_lanes(old + new, {}).values()))
    assert lane.hours == 10 and lane.samples == estimate.WINDOW


def test_a_yard_lane_learns_only_from_loads_that_left_that_yard():
    trips = [_trip(i, consignee="WOORI") for i in range(12)]
    left = {t["id"].strip(): [f"Departed {YARD} at {t['del_in'] - timedelta(hours=2):%m/%d/%y %H%M}."]
            for t in trips}
    lanes = estimate.build_lanes(trips, left)
    order = _order(consignee="WOORI", pu_out=datetime(2026, 11, 1))
    assert estimate.estimate_arrival(order, [f"Departed {YARD} at 11/04/26 0900."], lanes) == \
        datetime(2026, 11, 4, 11)
    assert estimate.estimate_arrival(order, ["Departed Other Yard, PHARR, TX at 11/04/26 0900."],
                                     lanes) is None


def _yard_comment(trip, yard=YARD, hours_before=2):
    return f"Departed {yard} at {trip['del_in'] - timedelta(hours=hours_before):%m/%d/%y %H%M}."


def test_no_yard_yet_is_not_read_as_never_a_yard():
    """30 WOORI trips via Pharr at 80 h, 10 with no yard logged at about 21 h. A load just
    leaving Waco must not be promised on those ten."""
    via = [_trip(i, consignee="WOORI", hours=80, appt_miss=30) for i in range(30)]
    bare = [_trip(100 + i, consignee="WOORI", hours=21, appt_miss=30) for i in range(10)]
    said = {t["id"].strip(): [_yard_comment(t)] for t in via}
    lanes = estimate.build_lanes(via + bare, said)
    assert estimate.estimate_arrival(_order(consignee="WOORI"), [], lanes) is None


def test_a_lane_that_almost_never_logs_a_yard_still_counts_from_the_pickup():
    bare = [_trip(i, hours=10) for i in range(19)]
    via = [_trip(100, hours=10)]
    lanes = estimate.build_lanes(bare + via, {via[0]["id"].strip(): [_yard_comment(via[0])]})
    assert estimate.estimate_arrival(_order(), [], lanes) == datetime(2026, 11, 4, 19)


def test_a_yard_that_usually_leads_to_another_yard_is_not_the_last_stop():
    trips = [_trip(i, consignee="WOORI", hours=60, appt_miss=30) for i in range(20)]
    said = {t["id"].strip(): [_yard_comment(t, "ACG Global, LAREDO, TX", 30),
                              _yard_comment(t, "Trancasa, NUEVO LAREDO, TM", 2)]
            for t in trips[:12]}
    said = {**said, **{t["id"].strip(): [_yard_comment(t, "ACG Global, LAREDO, TX", 2)]
                       for t in trips[12:]}}
    lanes = estimate.build_lanes(trips, said)
    order = _order(consignee="WOORI")
    assert estimate.estimate_arrival(order, ["Departed ACG Global, LAREDO, TX at 11/04/26 0900."],
                                     lanes) is None


def test_a_truck_still_at_the_dock_has_not_started_the_trip():
    assert estimate.estimate_arrival(_order(pu_out=None), [], _lanes()) is None


# --- the card ---------------------------------------------------------------

def _card(order=None, est=datetime(2026, 11, 4, 19), tz="America/Chicago"):
    return cards.build_card(order or _order(), cards.IN_PROGRESS,
                            {"estimates": {"0351802": est}}, NOW, tz)


def test_the_estimate_is_labelled_and_makes_no_lateness_claim():
    out = html.card_in_progress(_card())
    assert "Estimated arrival" in out and "not a confirmed ETA" in out and "07:00 PM" in out
    assert "ETA to delivery" not in out and "ETA pending" not in out and "Hours" not in out


def test_a_keyed_eta_beats_the_estimate():
    c = _card(_order(del_eta=datetime(2026, 11, 4, 20)))
    assert c.est_eta is None and c.eta_source == cards.MCLEOD


def test_an_estimate_gone_by_is_not_shown():
    assert _card(est=NAIVE_NOW - timedelta(minutes=5)).est_eta is None


def test_an_estimate_is_judged_on_the_destination_clock():
    # 12:00 CST = 11:00 Mountain, so 11:30 there is still ahead.
    assert _card(est=datetime(2026, 11, 4, 11, 30), tz="America/Denver").est_eta is not None


def test_an_arrived_load_shows_no_estimate():
    assert _card(_order(del_in=datetime(2026, 11, 4, 9))).est_eta is None


# --- coverage ---------------------------------------------------------------

def _rc(*orders, estimates=None):
    built = tuple(cards.build_card(o, cards.IN_PROGRESS, {"estimates": estimates or {}}, NOW)
                  for o in orders)
    return cards.ReportCards(DONNA, built, (), ())


def test_coverage_counts_keyed_etas_among_loads_still_on_their_way():
    rc = _rc(_order(id="0000001 ", del_eta=datetime(2026, 11, 4, 20)),
             _order(id="0000002 "),
             _order(id="0000003 ", del_in=datetime(2026, 11, 4, 9)),
             _order(id="0000004 ", del_out=datetime(2026, 11, 4, 9)))
    got = cards.eta_coverage(rc)
    assert (got["inProgress"], got["open"], got["keyed"]) == (4, 2, 1)
    assert [m["orderId"] for m in got["missing"]] == ["0000002"]
    assert rc.log_counts() == {"in_progress": 4, "scheduled": 0, "delivered": 0,
                               "eta_open": 2, "eta_keyed": 1}


def test_an_estimate_or_augie_eta_does_not_count_as_keyed():
    augie = {"movements": {"0000002": [{"movement_id": "1", "brokerage_status": "PROGRESS"}]},
             "augie": {"0000002": [{"movement_id": "1", "leg_dest_city": "DONNA",
                                    "eta": datetime(2026, 11, 5, 3)}]}}
    built = (cards.build_card(_order(id="0000001 "), cards.IN_PROGRESS,
                              {"estimates": {"0000001": datetime(2026, 11, 4, 19)}}, NOW),
             cards.build_card(_order(id="0000002 "), cards.IN_PROGRESS, augie, NOW))
    got = cards.eta_coverage(cards.ReportCards(DONNA, built, (), ()))
    assert got["keyed"] == 0 and got["estimated"] == 1 and got["augie"] == 1
    assert sorted(m["shownInstead"] for m in got["missing"]) == ["augie", "estimate"]


def test_a_passed_eta_tells_ops_it_needs_updating():
    passed = datetime(2026, 11, 3, 8)
    got = cards.eta_coverage(_rc(_order(del_eta=passed)))
    assert got["keyed"] == 0 and got["missing"][0]["etaPassed"] == passed.isoformat()


def test_no_customer_addresses_reach_the_coverage_payload():
    assert "@" not in str(cards.eta_coverage(_rc(_order())))


# --- wiring -----------------------------------------------------------------

def test_history_sql_is_guarded_and_never_reads_a_sentinel_arrival():
    assert "w.dest_actual_arrival > '2000-01-01'" in data.TRANSIT_SQL
    assert "b.status = 'D'" in data.TRANSIT_SQL
    assert "upper(btrim(b.origin_city_name)) = $3" in data.TRANSIT_SQL
    assert "upper(btrim(b.origin_state_id)) = $4" in data.TRANSIT_SQL
    assert "'Departed %'" in data.STOP_EVENTS_SQL and "'Empty at consignee %'" in data.STOP_EVENTS_SQL


def test_a_failed_history_read_means_no_estimates_not_a_failed_send():
    import asyncio

    class Broken:
        def acquire(self):
            raise RuntimeError("gold is down")

    got = asyncio.run(data.fetch_estimates(Broken(), [_order()], NOW))
    assert got == {}


def test_nothing_is_read_without_a_moving_load():
    import asyncio

    class NoCalls:
        def acquire(self):
            raise AssertionError("no read expected")

    assert asyncio.run(data.fetch_estimates(NoCalls(), [_order(status="A")], NOW)) == {}


def test_coverage_trend_excludes_manual_sends_and_older_rows():
    sql = sender.COVERAGE_TREND_SQL
    assert "mode <> 'manual'" in sql and "status = 'sent'" in sql and "counts ? 'eta_open'" in sql
    assert "report_key" in sql and "GROUP BY 1, 2" in sql  # the panel filters by report


def test_coverage_route_uses_the_report_read_gate():
    from app.routers import customer_status_email as r

    route = next(x for x in r.router.routes if x.path.endswith("/coverage"))
    assert route.methods == {"GET"}
    gates = [d.call for d in route.dependant.dependencies]
    assert r._read_gate in gates
