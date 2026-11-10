"""PCA customer load-status e-mails (services/customer_status_email, 2026-10-20).

Layers:
  1. config  — the four reports, their hours and lanes exactly as the template
  2. cards   — bucket rules, the destination-clock 24 h cut, ETA/GPS freshness
  3. html    — sections, pills, escaping, Outlook-safe markup, signature
  4. sender  — test routing, send-once claim, failure surfaces as a raise
  5. wiring  — main.py registers the job, the DDL and the router
  6. live    — every statement PREPAREs against gold (skipped offline)

Guards on routing, the claim, the stale-ETA rule and the 24 h clock were
mutation-checked: reverting each one turns its test red.
"""
from __future__ import annotations

import asyncio
import os
import re
import types
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from app.services.customer_status_email import cards, config, data, html, sender

CST = ZoneInfo("America/Chicago")
NOW = datetime(2026, 10, 20, 12, 0, tzinfo=CST)
NAIVE_NOW = NOW.replace(tzinfo=None)
# Augie's new_eta / gps_updated_dt hold UTC digits (2026-11-04: 126 of 275 recent
# fixes were ahead of Central time, none ahead of UTC) — fixtures use real UTC.
NAIVE_UTC = NOW.astimezone(timezone.utc).replace(tzinfo=None)
MAIN = Path(__file__).resolve().parents[1] / "app" / "main.py"


def _order(**kw) -> dict:
    base = dict(
        id="0349842 ", company_id="TMS ", status="P", origin_city="WACO", origin_state="TX",
        dest_city="DONNA", dest_state="TX", po="C-1019-12", bol="206-1", trailer="26199",
        consignee="PCA DONNA", delivery_location="DONNA, TX",
        pu_sched_early=datetime(2026, 10, 20, 1), pu_sched_late=datetime(2026, 10, 20, 1),
        pu_in=datetime(2026, 10, 19, 16, 36), pu_out=datetime(2026, 10, 20, 8),
        del_sched_early=datetime(2026, 10, 20, 18), del_sched_late=datetime(2026, 10, 20, 18),
        del_in=None, del_out=None,
    )
    base.update(kw)
    return base


DONNA = config.REPORTS_BY_KEY["pca-donna"]
EL_PASO = config.REPORTS_BY_KEY["pca-el-paso"]
REYNOSA = config.REPORTS_BY_KEY["pca-reynosa"]


# ---------------------------------------------------------------------------
# 1. config
# ---------------------------------------------------------------------------

def test_every_template_destination_code_is_configured():
    expected = {
        "pca-donna": {"PCADDOTX"},
        "pca-laredo": {"ALDETLJA", "ASCMAPNX", "BOXUCANX", "CORRSAJA", "EMPASAN1", "ALTOSAJA",
                       "IECEMON1", "INNOSANX", "NEFAZAJA", "PARQTLJA",
                       "ALTATLJ1", "ALTAGUJA"},  # Ops 2026-10-20
        "pca-el-paso": {"ABMAJUCI", "DIGSJUCI", "NEFAJUCH", "TECNCHCI", "PCAEELTX"},
        "pca-reynosa": {"REYNOSA", "REGIRITM", "AGEBRETM", "WOORRETM"},
    }
    got = {r.key: {d.code for d in r.destinations} for r in config.REPORTS}
    assert got == expected


def test_send_hours_match_the_schedule_table():
    """schedules.png: DONNA sends at 3 PM, the other three at 4 PM."""
    assert DONNA.send_hours == (2, 7, 12, 15, 22)
    for key in ("pca-laredo", "pca-el-paso", "pca-reynosa"):
        assert config.REPORTS_BY_KEY[key].send_hours == (2, 7, 12, 16, 22)
    assert config.SEND_HOURS == (2, 7, 12, 15, 16, 22)
    assert [r.key for r in config.reports_due(15)] == ["pca-donna"]
    assert len(config.reports_due(16)) == 3 and len(config.reports_due(7)) == 4
    assert config.reports_due(13) == ()


def test_subjects_and_sender_match_the_template():
    assert [r.subject for r in config.REPORTS] == [
        "DONNA REPORT", "PCA / CTC REPORT - LAREDO", "PCA / CTC REPORT - EL PASO",
        "PCA / CTC REPORT - REYNOSA"]
    assert {r.send_from for r in config.REPORTS} == {"mvazquez@unilinktransportation.com"}


def test_a_name_match_beats_the_reynosa_city_rule():
    woori = config.match_destination(REYNOSA, " woori -  Bo Kwang Printing S.A. De C.V.", "REYNOSA, TM")
    other = config.match_destination(REYNOSA, "Some New Plant", "Reynosa, TM")
    assert woori.code == "WOORRETM" and other.code == "REYNOSA"
    assert config.match_destination(REYNOSA, "Regio Pak Planta Garcia 2", "GARCIA, NX") is None


def test_unlisted_consignees_stay_out():
    """Decision 2026-10-20: only the template's codes — no siblings added."""
    laredo = config.REPORTS_BY_KEY["pca-laredo"]
    for name, city in (("ALPI CORRUGADOS", "GUADALAJARA, JA"), ("IEC", "SAN NICOLAS, NX"),
                       ("Nefab Packaging Ciudad Juarez", "JUAREZ, CH")):
        assert config.match_destination(laredo, name, city) is None
        assert config.match_destination(EL_PASO, name, city) is None


# ---------------------------------------------------------------------------
# 2. cards
# ---------------------------------------------------------------------------

def _dest(report=DONNA):
    return report.destinations[0]


def test_buckets_by_status():
    assert cards.bucket_for(_order(status="P"), _dest(), NOW) == cards.IN_PROGRESS
    assert cards.bucket_for(_order(status="V"), _dest(), NOW) is None


def test_scheduled_is_today_or_earlier_never_future():
    today = _order(status="A", pu_sched_early=datetime(2026, 10, 20, 23, 59))
    earlier = _order(status="A", pu_sched_early=datetime(2026, 10, 18, 5))
    future = _order(status="A", pu_sched_early=datetime(2026, 10, 21, 0, 0))
    no_window = _order(status="A", pu_sched_early=None, pu_sched_late=None)
    assert cards.bucket_for(today, _dest(), NOW) == cards.SCHEDULED
    assert cards.bucket_for(earlier, _dest(), NOW) == cards.SCHEDULED
    assert cards.bucket_for(future, _dest(), NOW) is None
    assert cards.bucket_for(no_window, _dest(), NOW) == cards.SCHEDULED


def test_delivered_window_is_24h_on_the_destination_clock():
    inside = _order(status="D", del_out=NAIVE_NOW - timedelta(hours=23, minutes=50))
    outside = _order(status="D", del_out=NAIVE_NOW - timedelta(hours=24, minutes=10))
    assert cards.bucket_for(inside, _dest(), NOW) == cards.DELIVERED
    assert cards.bucket_for(outside, _dest(), NOW) is None
    # El Paso runs an hour behind Chicago: 24 h 30 min ago on the CST clock is
    # 23 h 30 min ago on the stop's own clock — still inside the window.
    juarez = EL_PASO.destinations[0]
    local = _order(status="D", del_out=NAIVE_NOW - timedelta(hours=24, minutes=30))
    assert cards.bucket_for(local, juarez, NOW) == cards.DELIVERED


def test_delivered_without_any_actual_is_not_shown():
    assert cards.bucket_for(_order(status="D", del_in=None, del_out=None), _dest(), NOW) is None


def test_on_time_uses_the_late_edge_inclusive():
    t = datetime(2026, 10, 20, 7)
    assert cards.on_time(t, t) is True
    assert cards.on_time(t + timedelta(minutes=1), t) is False
    assert cards.on_time(None, t) is None and cards.on_time(t, None) is None


def _details(eta, leg_city="DONNA", gps_at=NAIVE_UTC - timedelta(minutes=5)):
    return {
        "movements": {"0349842": [{"movement_id": "572650", "brokerage_status": "PROGRESS",
                                   "track_link": "https://MacroPoint-Lite.com/x"}]},
        "augie": {"0349842": [{"movement_id": "572650", "leg_dest_city": leg_city,
                               "leg_dest_state": "TX", "eta": eta, "geo_city": "CHRISTINE",
                               "geo_state": "TX", "gps_at": gps_at}]},
        "comments": {"0349842": {"comment": "In transit"}},
        "pods": {},
    }


def test_final_leg_eta_gives_hours_vs_appointment():
    c = cards.build_card(_order(), cards.IN_PROGRESS,
                         _details(datetime(2026, 10, 21, 1, 30)), NOW)  # 20:30 local
    assert c.hours_vs_appt == 2.5 and c.eta_place is None
    assert c.location == "CHRISTINE, TX" and c.status_label == "In transit"
    assert c.track_link and c.comment == "In transit"


def test_intermediate_leg_eta_is_labelled_and_has_no_pill():
    c = cards.build_card(_order(), cards.IN_PROGRESS,
                         _details(datetime(2026, 10, 20, 19), leg_city="LAREDO"), NOW)
    assert c.hours_vs_appt is None and c.eta_place == "LAREDO, TX"


def test_an_eta_already_past_is_dropped():
    """Measured 2026-10-20: yesterday's ETA on a load at the border read
    '53.3 Hours AHEAD'."""
    c = cards.build_card(_order(), cards.IN_PROGRESS,
                         _details(NAIVE_UTC - timedelta(hours=20)), NOW)
    assert c.eta is None and c.hours_vs_appt is None


def test_an_old_gps_fix_is_not_a_current_location():
    c = cards.build_card(_order(), cards.IN_PROGRESS,
                         _details(None, gps_at=NAIVE_UTC - timedelta(hours=30)), NOW)
    assert c.location is None


def test_active_leg_is_the_first_open_movement():
    moves = [{"movement_id": "572103", "brokerage_status": "BORDERXI"},
             {"movement_id": "572102", "brokerage_status": "DELIVER"}]
    assert cards._active_leg(moves)["movement_id"] == "572103"
    closed = [{"movement_id": "9", "brokerage_status": "DELIVER"}]
    assert cards._active_leg(closed)["movement_id"] == "9"


def test_assign_partitions_and_reports_unmatched_consignees():
    orders = [
        _order(),
        _order(id="0000001 ", status="A", pu_sched_early=datetime(2026, 10, 20, 5)),
        _order(id="0000002 ", consignee="Brand New Plant", delivery_location="MONTERREY, NX"),
        _order(id="0000003 ", origin_city="LAREDO"),  # not a Waco pickup
        _order(id="0000004 ", consignee="WOORI - Bo Kwang Printing S.A. De C.V.",
               delivery_location="REYNOSA, TM"),
    ]
    by_key, unmatched = cards.assign(orders, {}, NOW)
    assert by_key["pca-donna"].counts() == {"in_progress": 1, "scheduled": 1, "delivered": 0}
    assert by_key["pca-reynosa"].counts()["in_progress"] == 1
    assert unmatched == ["Brand New Plant"]


# ---------------------------------------------------------------------------
# 3. html
# ---------------------------------------------------------------------------

def _rc(**kw):
    card = cards.build_card(_order(**kw), cards.IN_PROGRESS,
                            _details(datetime(2026, 10, 20, 21, 30)), NOW)
    return cards.ReportCards(report=DONNA, in_progress=(card,), scheduled=(), delivered=())


def test_render_has_every_section_and_the_empty_text():
    out = html.render(_rc(), NOW)
    # Only in-progress has loads: the two empty sections are NOT shown at all.
    assert html.SECTION_IN_PROGRESS in out
    assert html.SECTION_SCHEDULED not in out and html.SECTION_DELIVERED not in out
    assert html.EMPTY_TEXT not in out
    assert "Thank you for the opportunity to support your business." in out
    assert "Magaly Vazquez" in out and "route.unilinkportal.com/report" in out


def test_customer_text_is_escaped():
    out = html.render(_rc(consignee="<script>x</script>"), NOW)
    assert "<script>x</script>" not in out and "&lt;script&gt;" in out


def test_hours_pill_wording():
    assert "3.5 Hours BEHIND" in html.hours_pill(3.5)
    assert "4.2 Hours AHEAD" in html.hours_pill(-4.2)
    assert "Ahead of schedule" in html.hours_pill(-54.2)
    assert html.hours_pill(None) == ""


def test_outlook_safe_markup():
    out = html.render(_rc(), NOW).split("<table border=\"0\" cellpadding=\"0\" cellspacing=\"0\" style=\"width:600px;\">")[0]
    assert "bgcolor" not in out
    for tag in re.findall(r"<(?:td|div|table|span)\b[^>]*>", out):
        assert "font-family:" in tag, tag


def test_test_banner_only_in_test_mode():
    test = sender.routing_for(DONNA, live=False)
    live = sender.routing_for(DONNA, live=True)
    assert "fhernandez@packagingcorp.com" in sender.test_banner(DONNA, test)
    assert sender.test_banner(DONNA, live) is None


# ---------------------------------------------------------------------------
# 4. sender
# ---------------------------------------------------------------------------

def test_default_routing_is_jaime_never_the_customer():
    r = sender.routing_for(DONNA, live=False)
    assert r.to == ("janaya@unilinktransportation.com",)
    assert r.cc == ("t1ops@unilinktransportation.com",)
    assert r.bcc == ("dfrodriguez@unilinktransportation.com",)
    assert not any("packagingcorp" in a for a in r.to + r.cc + r.bcc)


def test_live_flag_defaults_off():
    from app.config import Settings

    assert Settings.model_fields["CUSTOMER_STATUS_EMAIL_LIVE"].default is False
    assert Settings.model_fields["CUSTOMER_STATUS_EMAIL_ENABLED"].default is True


class _HubConn:
    def __init__(self, hub):
        self.hub = hub

    async def fetchval(self, sql, *params):
        # Mirrors CLAIM_SQL: insert, or re-claim ONLY a row whose status is 'failed'.
        key = (params[0], params[1])
        if key in self.hub.rows and self.hub.rows[key]["status"] != "failed":
            return None
        self.hub.rows[key] = {"status": "sending", "mode": params[2]}
        return params[0]

    async def execute(self, sql, *params):
        self.hub.rows[(params[0], params[1])].update(status=params[2], error=params[4])


class _Acq:
    def __init__(self, conn):
        self.conn = conn

    async def __aenter__(self):
        return self.conn

    async def __aexit__(self, *exc):
        return False


class _Hub:
    def __init__(self):
        self.rows: dict = {}

    def acquire(self):
        return _Acq(_HubConn(self))


def _app(hub):
    return types.SimpleNamespace(state=types.SimpleNamespace(pool=hub, savings_pool=object(),
                                                             ap_pool=None))


@pytest.fixture
def patched(monkeypatch):
    sent: list[dict] = []

    async def fake_build(app, now):
        one = cards.build_card(_order(), cards.IN_PROGRESS, {}, NOW)
        loaded = {r.key: cards.ReportCards(r, (one,), (), ()) for r in config.REPORTS}
        return loaded, []

    async def fake_send(**kw):
        sent.append(kw)
        return {"sent": True, "to": kw["to"]}

    monkeypatch.setattr(sender, "build_all", fake_build)
    monkeypatch.setattr(sender, "send_mail", fake_send)
    monkeypatch.setattr(sender.settings, "CUSTOMER_STATUS_EMAIL_LIVE", False)
    monkeypatch.setattr(sender.settings, "CUSTOMER_STATUS_EMAIL_ENABLED", True)
    return sent


def test_slot_sends_due_reports_once_to_test_routing(patched):
    hub = _Hub()
    at_four = datetime(2026, 10, 20, 16, 0, tzinfo=CST)
    result = asyncio.run(sender.run_slot(_app(hub), at_four))
    assert result["sent"] == ["pca-el-paso", "pca-laredo", "pca-reynosa"]
    assert len(patched) == 3
    assert all(m["to"] == ["janaya@unilinktransportation.com"] for m in patched)
    assert all(m["from_address"] == "mvazquez@unilinktransportation.com" for m in patched)
    assert {v["status"] for v in hub.rows.values()} == {"sent"}
    # The same slot again (restart, misfire replay, 2nd instance) sends nothing.
    again = asyncio.run(sender.run_slot(_app(hub), at_four))
    assert "already sent" in again["skipped"] and len(patched) == 3


def test_a_failed_report_is_logged_and_the_run_raises(patched, monkeypatch):
    async def flaky_send(**kw):
        if "LAREDO" in kw["subject"]:
            return {"sent": False, "reason": "graph_status_500"}
        patched.append(kw)
        return {"sent": True, "to": kw["to"]}

    monkeypatch.setattr(sender, "send_mail", flaky_send)
    hub = _Hub()
    with pytest.raises(sender.SlotRunError):
        asyncio.run(sender.run_slot(_app(hub), datetime(2026, 10, 20, 16, 0, tzinfo=CST)))
    assert len(patched) == 2  # the other two still went out
    assert hub.rows[("pca-laredo", "2026-10-20 16")]["status"] == "failed"


def test_a_stale_feed_fails_the_slot_without_mailing(patched, monkeypatch):
    async def stale(app, now):
        raise data.StaleFeedError("order feed last updated 2026-10-19 01:00 CST")

    monkeypatch.setattr(sender, "build_all", stale)
    hub = _Hub()
    with pytest.raises(sender.SlotRunError):
        asyncio.run(sender.run_slot(_app(hub), datetime(2026, 10, 20, 7, 0, tzinfo=CST)))
    assert patched == [] and {v["status"] for v in hub.rows.values()} == {"failed"}


def test_no_hub_pool_means_no_send(patched):
    with pytest.raises(sender.SlotRunError):
        asyncio.run(sender.run_slot(_app(None), datetime(2026, 10, 20, 7, 0, tzinfo=CST)))
    assert patched == []


def test_disabled_and_off_hours_send_nothing(patched, monkeypatch):
    assert "no report due" in asyncio.run(
        sender.run_slot(_app(_Hub()), datetime(2026, 10, 20, 13, 0, tzinfo=CST)))["skipped"]
    monkeypatch.setattr(sender.settings, "CUSTOMER_STATUS_EMAIL_ENABLED", False)
    assert asyncio.run(sender.run_slot(_app(_Hub()), datetime(2026, 10, 20, 7, 0, tzinfo=CST))) \
        == {"skipped": "disabled"}
    assert patched == []


def test_manual_send_is_always_test_routing_even_when_live(patched, monkeypatch):
    monkeypatch.setattr(sender.settings, "CUSTOMER_STATUS_EMAIL_LIVE", True)
    asyncio.run(sender.send_test_now(_app(_Hub()), "pca-donna"))
    assert patched[0]["to"] == ["janaya@unilinktransportation.com"]


def test_freshness_guard():
    with pytest.raises(data.StaleFeedError):
        data.assert_fresh(NAIVE_NOW - timedelta(hours=9), NOW)
    with pytest.raises(data.StaleFeedError):
        data.assert_fresh(None, NOW)
    data.assert_fresh(NAIVE_NOW - timedelta(hours=3), NOW)


def test_slot_key_is_cst_date_and_hour():
    assert sender.slot_key_for(datetime(2026, 10, 20, 2, 0, 31, tzinfo=CST)) == "2026-10-20 02"


# ---------------------------------------------------------------------------
# SQL text (a stub cannot see a WHERE — the live layer PREPAREs these)
# ---------------------------------------------------------------------------

def test_orders_sql_shape():
    sql = data.ORDERS_SQL
    assert "b.status IN ('A', 'P', 'D')" in sql  # void never read
    assert "v.id = b.id AND v.company_id = b.company_id" in sql
    assert "w.id = b.id AND w.company_id = b.company_id" in sql
    assert sql.count("> '2000-01-01'") == 10  # every McLeod timestamp sentinel-guarded
    assert "AS pu_eta" in sql and "AS del_eta" in sql
    assert "NULLIF(btrim(v.blnum), '')" in sql and "NULLIF(btrim(v.carrier_trailer), '')" in sql


def test_comment_types_exclude_internal_notes():
    assert "AUGCOMME" not in data.SAFE_COMMENT_TYPES
    assert "SVCINCD" not in data.SAFE_COMMENT_TYPES
    assert re.search(data.UNSAFE_COMMENT_PATTERN, "Voicemail, no answer from the driver", re.I)


# ---------------------------------------------------------------------------
# 5. wiring
# ---------------------------------------------------------------------------

def test_main_registers_job_roster_ddl_and_router():
    src = MAIN.read_text()
    assert 'id="customer_status_emails"' in src
    assert '"customer_status_emails":' in src  # EXPECTED_JOBS roster
    assert "customer_status_email.sender import LOG_DDL" in src
    assert "app.include_router(customer_status_email.router" in src


def test_router_rejects_an_unknown_report_key():
    from fastapi import HTTPException

    from app.routers import customer_status_email as r

    with pytest.raises(HTTPException) as exc:
        r._report_or_404("pca-everything")
    assert exc.value.status_code == 404


def test_router_requires_admin_or_cron(monkeypatch):
    from fastapi import HTTPException

    from app.routers import customer_status_email as r

    with pytest.raises(HTTPException) as exc:
        asyncio.run(r.require_admin_or_cron(authorization=None, x_proxy_secret=None))
    assert exc.value.status_code == 401
    monkeypatch.setattr(r.settings, "REPORTS_CRON_SECRET", "s3cret-value-for-test")
    who = asyncio.run(r.require_admin_or_cron(authorization="Bearer s3cret-value-for-test",
                                              x_proxy_secret=None))
    assert who["machine"] is True


# ---------------------------------------------------------------------------
# 6. live
# ---------------------------------------------------------------------------

_GOLD = os.environ.get("SAVINGS_DATABASE_URL", "")


@pytest.mark.skipif(not _GOLD, reason="SAVINGS_DATABASE_URL not set — offline run")
def test_live_every_gold_statement_parses():
    """§81: text is not validity. PREPARE what production runs."""
    statements = [data.ORDERS_SQL, data.FRESHNESS_SQL, data.MOVEMENTS_SQL, data.AUGIE_SQL,
                  data.COMMENTS_SQL, data.TRANSIT_SQL, data.STOP_EVENTS_SQL]

    async def run():
        import asyncpg

        conn = await asyncpg.connect(re.sub(r"[?&]sslmode=\w+", "", _GOLD), ssl="require")
        bad = []
        try:
            for sql in statements:
                try:
                    await conn.prepare(sql)
                except Exception as exc:  # noqa: BLE001 — report, do not mask
                    bad.append(f"{getattr(exc, 'sqlstate', '?')} {exc}"[:220])
        finally:
            await conn.close()
        return bad

    assert not asyncio.run(run())


# ---------------------------------------------------------------------------
# review fixes 2026-10-20
# ---------------------------------------------------------------------------

def test_a_failed_slot_is_retried_at_20_past_and_a_sent_one_is_not(patched, monkeypatch):
    calls = {"n": 0}

    async def flaky_once(**kw):
        if "LAREDO" in kw["subject"] and calls["n"] == 0:
            calls["n"] += 1
            return {"sent": False, "reason": "token_failed"}
        patched.append(kw)
        return {"sent": True, "to": kw["to"]}

    monkeypatch.setattr(sender, "send_mail", flaky_once)
    hub = _Hub()
    with pytest.raises(sender.SlotRunError):
        asyncio.run(sender.run_slot(_app(hub), datetime(2026, 10, 20, 16, 0, tzinfo=CST)))
    assert len(patched) == 2
    retry = asyncio.run(sender.run_slot(_app(hub), datetime(2026, 10, 20, 16, 20, tzinfo=CST)))
    assert retry["sent"] == ["pca-laredo"] and len(patched) == 3
    assert {v["status"] for v in hub.rows.values()} == {"sent"}


def test_claim_sql_retakes_only_failed_rows():
    sql = sender.CLAIM_SQL
    assert "WHERE l.status = 'failed'" in sql
    assert "status = 'sending' AND" not in sql  # a stuck 'sending' row is never retaken


def test_dst_spring_forward_03_00_firing_is_the_02_00_slot():
    assert sender.slot_hour(datetime(2027, 3, 14, 3, 0, tzinfo=CST)) == 2
    assert sender.slot_hour(datetime(2026, 10, 20, 7, 20, tzinfo=CST)) == 7
    assert sender.slot_hour(datetime(2026, 10, 20, 13, 0, tzinfo=CST)) == 13


def test_naive_clock_is_rejected(patched):
    with pytest.raises(ValueError):
        asyncio.run(sender.run_slot(_app(_Hub()), datetime(2026, 10, 20, 7, 0)))
    with pytest.raises(ValueError):
        cards.assign([], {}, datetime(2026, 10, 20, 7, 0))


def test_eta_is_moved_to_the_destination_clock():
    """Augie's new_eta is UTC; an El Paso appointment is Mountain time. ETA 15:00
    UTC = 09:00 MT against a 09:30 MT appointment is 0.5 h AHEAD, not behind."""
    order = _order(dest_city="EL PASO", del_sched_late=datetime(2026, 10, 20, 9, 30))
    det = _details(datetime(2026, 10, 20, 15, 0), leg_city="EL PASO")
    early = datetime(2026, 10, 20, 8, 0, tzinfo=CST)
    c = cards.build_card(order, cards.IN_PROGRESS, det, early, "America/Denver")
    assert c.eta == datetime(2026, 10, 20, 9, 0) and c.hours_vs_appt == -0.5


def test_only_http_links_are_rendered():
    assert html._link("javascript:alert(1)", "x") == html.DASH
    assert html._link("data:text/html,hi", "x") == html.DASH
    assert 'href="https://MacroPoint-Lite.com/a?b=1&amp;c=2"' in html._link(
        "https://MacroPoint-Lite.com/a?b=1&c=2", "x")


def test_freshness_ignores_future_rows():
    assert "localtimestamp + interval '1 hour'" in data.FRESHNESS_SQL


def test_retry_firing_is_registered_at_20_past():
    assert 'minute="0,20"' in MAIN.read_text()


# ---------------------------------------------------------------------------
# Customer E-mail Activity panel (request 2026-10-20, "activity panel")
# ---------------------------------------------------------------------------

ROOT = Path(__file__).resolve().parents[2]


def test_today_grid_marks_sent_failed_missed_and_upcoming():
    from app.routers.customer_status_email import today_grid

    rows = [
        {"report_key": "pca-donna", "slot_key": "2026-10-20 07", "status": "sent",
         "finished_at": "2026-10-20T07:00:05"},
        {"report_key": "pca-donna", "slot_key": "2026-10-20 12", "status": "failed",
         "finished_at": "2026-10-20T12:00:09"},
    ]
    at = datetime(2026, 10, 20, 12, 50, tzinfo=CST)
    donna = next(r for r in today_grid(rows, at, "2026-10-01T00:00:00") if r["key"] == "pca-donna")
    states = {s["hour"]: s["status"] for s in donna["slots"]}
    # 02:00 has no row 45+ min later ⇒ MISSED (the job never ran) — absence is not health.
    assert states == {2: "missed", 7: "sent", 12: "failed", 15: "upcoming", 22: "upcoming"}
    early = {s["hour"]: s["status"] for s in
             next(r for r in today_grid([], datetime(2026, 10, 20, 2, 30, tzinfo=CST),
                                        "2026-10-01T00:00:00")
                  if r["key"] == "pca-donna")["slots"]}
    assert early[2] == "upcoming"  # inside the grace (the :20 retry has not had its chance)
    # Go-live day: slots before the first-ever send were not missed — the job did not exist.
    golive = {s["hour"]: s["status"] for s in
              next(r for r in today_grid([], at, "2026-10-20T12:38:58")
                   if r["key"] == "pca-donna")["slots"]}
    assert golive[2] == golive[7] == golive[12] == "not_live" and golive[15] == "upcoming"


def test_activity_sql_reads_the_log_newest_first_in_cst():
    sql = sender.ACTIVITY_SQL
    assert "FROM customer_status_email_log" in sql and "ORDER BY claimed_at DESC" in sql
    assert "AT TIME ZONE 'America/Chicago'" in sql


def test_log_records_subject_recipients_and_loads():
    assert all(c in sender.LOG_DDL for c in ("subject", "recipients", "loads"))
    rc = cards.ReportCards(DONNA, (), (), ())
    rec = sender.sent_record(rc, sender.routing_for(DONNA, live=False), NOW)
    assert rec["recipients"]["to"] == ["janaya@unilinktransportation.com"]
    assert rec["subject"].startswith("DONNA REPORT") and set(rec["loads"]) == {
        "in_progress", "scheduled", "delivered"}


def test_panel_mirrors_seed_icon_route_and_gates():
    from app.routers import customer_status_email as r
    from app.services.seed import CUSTOM_REPORTS

    seeded = [x for x in CUSTOM_REPORTS if x["key"] == r.REPORT_KEY]
    assert len(seeded) == 1 and seeded[0]["title"] == "Customer E-mail Activity"
    assert r.router.prefix == f"/custom/{r.REPORT_KEY}"
    icons = (ROOT / "frontend/components/ReportIcons.tsx").read_text()
    assert '"Customer E-mail Activity":' in icons
    page = ROOT / f"frontend/app/reports/{r.REPORT_KEY}/page.tsx"
    assert f'reportKey="{r.REPORT_KEY}"' in page.read_text()
    for route in r.router.routes:
        names = [getattr(d.call, "__qualname__", "") for d in route.dependant.dependencies]
        if "POST" in route.methods:
            # Sending is ADMIN-only, never the report's TagRoles.
            assert any(n.startswith("require_admin_or_cron") for n in names), route.path
        else:
            assert any(n.startswith("require_digest_access") for n in names), route.path


def test_border_yard_comments_do_not_read_as_a_delivery():
    """User 2026-10-20: the US leg of a split load is closed at the customs yard —
    "Empty at consignee TRANCASA EL PASO" read like a delivery."""
    cc = cards.customer_comment
    assert cc("Empty at consignee TRANCASA EL PASO, EL PASO, TX at 10/15/26 1300.", "Nefab Juarez") == \
        "At TRANCASA EL PASO, EL PASO, TX for customs clearance since 10/15/2026 @ 01:00 PM."
    assert cc("Departed SouthWest Yard, EL PASO, TX at 10/17/26 1500.", "Digssa Packaging and Supply") == (
        "Cleared customs and departed SouthWest Yard, EL PASO, TX on 10/17/2026 @ 03:00 PM; "
        "continuing to final destination.")
    assert cc("Appointment confirmed at SouthWest Yard, EL PASO, TX for 10/19/26 0900 to 10/19/26 1800.",
              "Digssa Packaging and Supply") == (
        "Border crossing appointment confirmed at SouthWest Yard, EL PASO, TX: "
        "10/19/2026 @ 09:00 AM to 10/19/2026 @ 06:00 PM.")
    # The order's OWN consignee is not a yard — unchanged.
    own = "Appointment confirmed at PCA DONNA, DONNA, TX for 10/20/26 1800 to 10/20/26 1800."
    assert cc(own, "PCA DONNA") == own
    # Augie free text is untouched.
    text = "In transit in Austin, TX; ETA Donna 9:00 AM."
    assert cc(text, "PCA DONNA") == text
    assert cc(None, "PCA DONNA") is None


def test_a_report_with_no_loads_is_skipped_not_sent(patched, monkeypatch):
    """User 2026-10-20: "if one specific route don't have any info … don't show
    nothing and pass to the next"."""
    async def donna_empty(app, now):
        one = cards.build_card(_order(), cards.IN_PROGRESS, {}, NOW)
        return {r.key: cards.ReportCards(r, () if r.key == "pca-donna" else (one,), (), ())
                for r in config.REPORTS}, []

    monkeypatch.setattr(sender, "build_all", donna_empty)
    hub = _Hub()
    result = asyncio.run(sender.run_slot(_app(hub), datetime(2026, 10, 20, 7, 0, tzinfo=CST)))
    assert result["skipped"] == ["pca-donna"] and len(result["sent"]) == 3
    assert not any("DONNA" in m["subject"] for m in patched)
    assert hub.rows[("pca-donna", "2026-10-20 07")]["status"] == "skipped"
    # A skipped slot is final — the :20 firing does not retake it.
    asyncio.run(sender.run_slot(_app(hub), datetime(2026, 10, 20, 7, 20, tzinfo=CST)))
    assert len(patched) == 3


def test_manual_send_of_an_empty_report_sends_nothing(patched, monkeypatch):
    async def all_empty(app, now):
        return {r.key: cards.ReportCards(r, (), (), ()) for r in config.REPORTS}, []

    monkeypatch.setattr(sender, "build_all", all_empty)
    out = asyncio.run(sender.send_test_now(_app(_Hub()), "pca-donna"))
    assert out["skipped"] is True and patched == []


def test_preview_of_an_empty_report_says_it_is_skipped():
    out = html.render(cards.ReportCards(DONNA, (), (), ()), NOW)
    assert html.EMPTY_TEXT in out and html.SECTION_IN_PROGRESS not in out


# --- not-sent alert (:45 watch) --------------------------------------------

class _WatchHub(_Hub):
    def __init__(self, rows):
        super().__init__()
        self.slot_rows = rows

    def acquire(self):
        hub = self

        class C(_HubConn):
            async def fetch(self, sql, *params):
                return [r for r in hub.slot_rows if r["slot_key"] == params[0]]
        return _Acq(C(self))


def test_watch_alerts_on_failed_stuck_and_never_ran(patched):
    rows = [
        {"slot_key": "2026-10-20 16", "report_key": "pca-laredo", "status": "sent", "error": None},
        {"slot_key": "2026-10-20 16", "report_key": "pca-el-paso", "status": "skipped", "error": None},
        {"slot_key": "2026-10-20 16", "report_key": "pca-reynosa", "status": "failed",
         "error": "graph_status_500"},
    ]
    out = asyncio.run(sender.watch_slot(_app(_WatchHub(rows)),
                                        datetime(2026, 10, 20, 16, 45, tzinfo=CST)))
    assert out["alerted"] == ["pca-reynosa"]
    assert len(patched) == 1
    mail = patched[0]
    assert "NOT sent" in mail["subject"] and "2026-10-20 16" in mail["subject"]
    assert mail["to"] == ["dfrodriguez@unilinktransportation.com", "t1ops@unilinktransportation.com"]
    assert "graph_status_500" in mail["html_body"]
    # 15:00 is DONNA's slot; no row at all = the job never ran.
    out = asyncio.run(sender.watch_slot(_app(_WatchHub([])),
                                        datetime(2026, 10, 20, 15, 45, tzinfo=CST)))
    assert out["alerted"] == ["pca-donna"] and "never ran" in patched[1]["html_body"]


def test_watch_is_quiet_when_every_due_report_went_out(patched):
    rows = [{"slot_key": "2026-10-20 07", "report_key": r.key, "status": "sent", "error": None}
            for r in config.REPORTS]
    out = asyncio.run(sender.watch_slot(_app(_WatchHub(rows)),
                                        datetime(2026, 10, 20, 7, 45, tzinfo=CST)))
    assert "ok" in out and patched == []


def test_watch_raises_when_the_alert_itself_fails(patched, monkeypatch):
    async def down(**kw):
        return {"sent": False, "reason": "token_failed"}

    monkeypatch.setattr(sender, "send_mail", down)
    with pytest.raises(sender.SlotRunError):
        asyncio.run(sender.watch_slot(_app(_WatchHub([])), datetime(2026, 10, 20, 7, 45, tzinfo=CST)))


def test_watch_job_is_registered_at_45():
    src = MAIN.read_text()
    assert 'id="customer_status_email_watch"' in src and "minute=45" in src
    assert '"customer_status_email_watch":' in src


# --- tracking sources: TTControl share links + Augie pings -------------------

def test_ttcontrol_payload_keeps_only_https_links_and_converts_to_cst():
    payload = {"success": True, "data": {
        "0349555": {"shareLink": {"provider": "samsara", "url": "https://cloud.samsara.com/o/1/x"},
                    "position": {"place": "Matehuala, SLP", "atUtc": "2026-10-20T17:50:23Z",
                                 "source": "macropoint"}},
        "0349107": {"shareLink": {"provider": "x", "url": "javascript:alert(1)"}, "position": None},
    }}
    got = data.parse_ttcontrol(payload)
    assert got["0349555"]["share_link"].startswith("https://cloud.samsara.com/")
    assert got["0349555"]["at_cst"] == datetime(2026, 10, 20, 12, 50, 23)
    assert got["0349107"]["share_link"] is None and got["0349107"]["at_cst"] is None


def test_ttcontrol_without_a_secret_is_skipped(monkeypatch):
    called = []

    def no_network(*a, **k):  # the soft-fail except would swallow a raise — record instead
        called.append(1)
        raise RuntimeError("network")

    monkeypatch.setattr(data.settings, "TTCONTROL_TRACKING_SECRET", "")
    monkeypatch.setattr(data.httpx, "AsyncClient", no_network)
    assert asyncio.run(data.fetch_ttcontrol(["0349555"])) == {}
    assert called == [], "TTControl was called without a secret"


def test_freshest_location_wins_across_sources():
    det = _details(None, gps_at=NAIVE_UTC - timedelta(hours=3))
    det["pings"] = {"0349842": {"city": "Falfurrias", "state": "TX",
                                "at_cst": NAIVE_NOW - timedelta(hours=1)}}
    det["tt"] = {"0349842": {"share_link": "https://cloud.samsara.com/o/1/abc",
                             "place": "Edinburg, TX", "at_cst": NAIVE_NOW - timedelta(minutes=10)}}
    c = cards.build_card(_order(), cards.IN_PROGRESS, det, NOW)
    assert c.location == "Edinburg, TX"
    # A carrier share link beats the MacroPoint link.
    assert c.track_link == "https://cloud.samsara.com/o/1/abc"
    det["tt"]["0349842"]["at_cst"] = NAIVE_NOW - timedelta(hours=30)  # too old: ignored
    assert cards.build_card(_order(), cards.IN_PROGRESS, det, NOW).location == "Falfurrias, TX"


def test_ops_answer_2026_10_20_laredo_consignees():
    """Ops: ALTOSAJA = Empaques Cartones y Suministros; ALTATLJ1 (Tlajomulco) and
    ALTAGUJA (Guadalajara, load 0347649) are both Alta Transformacion — all in LAREDO."""
    laredo = config.REPORTS_BY_KEY["pca-laredo"]
    m = config.match_destination
    assert m(laredo, "Empaques Cartones y Suministros", "SAN PEDRO TLAQUEPAQUE, JA").code == "ALTOSAJA"
    assert m(laredo, "Empaques Cartones y Suministros", "TLAQUEPAQUE, JA").code == "ALTOSAJA"
    assert m(laredo, "ALTA TRANSFORMACIONES", "TLAJOMULCO DE ZUNIGA, JA").code == "ALTATLJ1"
    assert m(laredo, "Alta Transformacion", "GUADALAJARA, JA").code == "ALTAGUJA"


# ---------------------------------------------------------------------------
# 7. Column 3 — McLeod stop ETA (origin_eta / destin_eta, Ops request 2026-11-03)
# ---------------------------------------------------------------------------

NOV_NOW = datetime(2026, 11, 4, 15, 0, tzinfo=CST)  # CST again: UTC-6


def test_reported_load_c_1103_9_reads_5_3_hours_behind_not_11_3():
    """The 11/04 3 PM DONNA report: 'GPS 08:44 PM CST' in a 3 PM e-mail and
    '11.3 Hours BEHIND'. Both were UTC digits printed as CST."""
    order = _order(del_sched_late=datetime(2026, 11, 4, 13, 0))
    det = _details(datetime(2026, 11, 5, 0, 20), gps_at=datetime(2026, 11, 4, 20, 44))
    c = cards.build_card(order, cards.IN_PROGRESS, det, NOV_NOW)
    assert c.location_at == datetime(2026, 11, 4, 14, 44)
    assert c.eta == datetime(2026, 11, 4, 18, 20)
    assert c.hours_vs_appt == 5.3


def test_mcleod_stop_eta_wins_and_is_already_on_the_stop_clock():
    """Jaime 11/03: use the stop's ETA field. It is the stop's wall clock — no shift."""
    order = _order(dest_city="EL PASO", del_sched_late=datetime(2026, 10, 20, 13, 30),
                   del_eta=datetime(2026, 10, 20, 13, 0))
    det = _details(datetime(2026, 10, 21, 4, 0), leg_city="EL PASO")  # Augie disagrees
    c = cards.build_card(order, cards.IN_PROGRESS, det, NOW, "America/Denver")
    assert c.eta == datetime(2026, 10, 20, 13, 0) and c.hours_vs_appt == -0.5
    assert c.eta_place is None and c.eta_is_cst is False


def test_mcleod_eta_staleness_is_judged_on_the_stop_clock():
    # 12:00 CDT = 11:00 MT. 10:45 is 15 min past on the stop's clock: still shown.
    kept = _order(del_eta=datetime(2026, 10, 20, 10, 45))
    assert cards.build_card(kept, cards.IN_PROGRESS, {}, NOW, "America/Denver").eta == kept["del_eta"]
    # 10:15 is 45 min past there: stale, whatever the appointment says.
    gone = _order(del_eta=datetime(2026, 10, 20, 10, 15))
    assert cards.build_card(gone, cards.IN_PROGRESS, {}, NOW, "America/Denver").eta is None


def test_an_augie_eta_is_judged_stale_on_the_utc_clock():
    # 14:00 UTC is 3 h past at 17:00 UTC, though its digits are after 12:00 CDT.
    c = cards.build_card(_order(), cards.IN_PROGRESS, _details(datetime(2026, 10, 20, 14, 0)), NOW)
    assert c.eta is None


def test_a_stale_mcleod_eta_falls_back_to_augie():
    order = _order(del_eta=NAIVE_NOW - timedelta(hours=9))
    c = cards.build_card(order, cards.IN_PROGRESS, _details(datetime(2026, 10, 21, 1, 30)), NOW)
    assert c.eta == datetime(2026, 10, 20, 20, 30)


def test_a_future_dated_fix_never_wins():
    det = _details(None, gps_at=NAIVE_UTC - timedelta(hours=2))
    det["tt"] = {"0349842": {"place": "Nowhere, TX", "at_cst": NAIVE_NOW + timedelta(hours=1)}}
    c = cards.build_card(_order(), cards.IN_PROGRESS, det, NOW)
    assert c.location == "CHRISTINE, TX"


def test_arrived_at_the_consignee_replaces_any_eta():
    order = _order(del_in=datetime(2026, 10, 20, 9, 8), del_eta=datetime(2026, 10, 20, 20, 0))
    c = cards.build_card(order, cards.IN_PROGRESS, _details(datetime(2026, 10, 21, 1, 0)), NOW)
    assert c.eta is None and c.hours_vs_appt is None
    out = html.card_in_progress(c)
    assert "Arrived" in out and "10/20/2026" in out and "09:08 AM" in out
    assert "IN TRANSIT" not in out and "AT DESTINATION" not in out
    assert "ETA pending" not in out and "CHRISTINE" not in out
    assert c.location is None and c.location_at is None
    # The arrival keeps its pill; the pick-up is a dot since 2026-11-10.
    assert out.count("On-Time") == 2  # arrival pill + the pick-up dot's title
    assert out.count("&#9679; On-Time") == 1


def test_a_late_arrival_is_not_shown_in_green():
    order = _order(del_in=datetime(2026, 10, 20, 19, 0), pu_in=None, pu_out=None)
    out = html.card_in_progress(cards.build_card(order, cards.IN_PROGRESS, {}, NOW))
    assert "Late" in out and f"border:2px solid {html.BAD}" in out


def test_a_departure_without_an_arrival_still_means_arrived():
    order = _order(del_out=datetime(2026, 10, 20, 9, 30), del_eta=datetime(2026, 10, 20, 20, 0))
    c = cards.build_card(order, cards.IN_PROGRESS, {}, NOW)
    out = html.card_in_progress(c)
    assert c.eta is None and "Arrived" in out and "09:30 AM" in out
    assert "DEPARTED DESTINATION" not in out and "ETA to delivery" not in out


YARD = "Empty at consignee EC Logistics Inc., PHARR, TX at 11/03/26 0700."


def _yard_details(comment=YARD, gps_at=None):
    det = _details(None, gps_at=gps_at)
    det["comments"] = {"0349842": {"comment": comment}}
    return det


def test_a_yard_comment_fills_the_location_only_without_a_recent_fix():
    c = cards.build_card(_order(), cards.IN_PROGRESS, _yard_details(), NOW)
    assert c.location is None and c.last_reported == "EC Logistics Inc., PHARR, TX"
    assert "Last reported at EC Logistics Inc., PHARR, TX" in html.card_in_progress(c)
    fresh = _yard_details(gps_at=NAIVE_UTC - timedelta(hours=1))
    c = cards.build_card(_order(), cards.IN_PROGRESS, fresh, NOW)
    assert c.location == "CHRISTINE, TX" and c.last_reported is None


def test_last_reported_is_only_a_place_the_truck_is_still_at():
    for comment in ("Empty at consignee PCA DONNA, DONNA, TX at 11/03/26 0700.",  # its own consignee
                    "Departed EC Logistics Inc., PHARR, TX at 11/03/26 0700.",    # already left
                    "Appointment confirmed at EC Logistics Inc., PHARR, TX for "
                    "11/03/26 0700 to 11/03/26 0900.",                           # not there yet
                    "Empty at consignee Central Texas Corrugated, WACO, TX at 11/03/26 0700.",
                    "In transit in Austin, TX."):
        c = cards.build_card(_order(), cards.IN_PROGRESS, _yard_details(comment), NOW)
        assert c.last_reported is None, comment
    arrived = _order(del_in=datetime(2026, 10, 20, 9, 8))
    assert cards.build_card(arrived, cards.IN_PROGRESS, _yard_details(), NOW).last_reported is None


def test_the_waco_shipper_is_never_called_a_border_yard():
    """The 11/04 report: 'Border crossing appointment confirmed at Central Texas
    Corrugated, WACO, TX'. Waco is where the load starts."""
    cc = cards.customer_comment
    assert cc("Appointment confirmed at Central Texas Corrugated, WACO, TX for "
              "11/04/26 0300 to 11/04/26 0300.", "PCA DONNA") == (
        "Pickup appointment confirmed at Central Texas Corrugated, WACO, TX: "
        "11/04/2026 @ 03:00 AM to 11/04/2026 @ 03:00 AM.")
    assert cc("Departed Central Texas Corrugated, WACO, TX at 11/04/26 0300.", "PCA DONNA") == (
        "Departed Central Texas Corrugated, WACO, TX on 11/04/2026 @ 03:00 AM.")
    assert cc("Departed Central Texas Corrugated at 11/04/26 0300.", "PCA DONNA") == (
        "Departed Central Texas Corrugated on 11/04/2026 @ 03:00 AM.")  # no city


def test_loaded_comment_gets_the_report_date_format():
    assert cards.customer_comment("Loaded at the shipper Central Texas Corrugated at 11/04/26 0040.",
                                  "PCA DONNA") == (
        "Loaded at the shipper Central Texas Corrugated on 11/04/2026 @ 12:40 AM.")


def test_the_eta_is_large_and_carries_its_pill():
    """Jaime 11/03: 'que se vea grande y muy visual'."""
    order = _order(del_sched_late=datetime(2026, 10, 20, 13, 0), del_eta=datetime(2026, 10, 20, 18, 20))
    out = html.card_in_progress(cards.build_card(order, cards.IN_PROGRESS, {}, NOW))
    assert "ETA to delivery" in out and "font-size:20px;font-weight:700" in out
    assert "10/20/2026" in out and "06:20 PM" in out and "5.3 Hours BEHIND" in out


def test_no_eta_says_pending_and_never_labels_the_appointment_as_an_eta():
    out = html.card_in_progress(cards.build_card(_order(), cards.IN_PROGRESS, {}, NOW))
    assert "ETA pending" in out and "ETA to delivery" not in out
    assert out.count("Delivery appt.") == 2  # the block + column 4
    assert "Hours" not in out


def test_an_intermediate_leg_eta_stays_small_under_a_pending_block():
    det = _details(datetime(2026, 10, 20, 19, 0), leg_city="LAREDO")
    out = html.card_in_progress(cards.build_card(_order(), cards.IN_PROGRESS, det, NOW))
    assert "ETA pending" in out and "ETA to LAREDO, TX: 10/20/2026 @ 02:00 PM CST" in out


def test_pickup_eta_shows_only_before_the_truck_reaches_the_pickup():
    future = datetime(2026, 10, 20, 15, 0)
    waiting = _order(status="A", pu_in=None, pu_out=None, pu_eta=future)
    c = cards.build_card(waiting, cards.SCHEDULED, {}, NOW)
    assert c.pu_eta == future
    assert "ETA to pick up: 10/20/2026 @ 03:00 PM" in html.card_scheduled(c)
    stale = _order(status="A", pu_in=None, pu_out=None, pu_eta=NAIVE_NOW - timedelta(hours=3))
    assert cards.build_card(stale, cards.SCHEDULED, {}, NOW).pu_eta is None
    arrived = _order(pu_eta=future)
    assert cards.build_card(arrived, cards.IN_PROGRESS, {}, NOW).pu_eta is None
    unkeyed = _order(pu_in=None, pu_out=None, pu_eta=future)
    c = cards.build_card(unkeyed, cards.IN_PROGRESS, {}, NOW)
    assert "ETA to pick up: 10/20/2026 @ 03:00 PM" in html.card_in_progress(c)


def test_an_eta_equal_to_the_appointment_reads_on_schedule():
    assert "On schedule" in html.hours_pill(0.0) and "AHEAD" not in html.hours_pill(0.0)


def test_comments_posted_together_resolve_to_the_same_truthful_one():
    """McLeod batch-posts stop comments in one minute (22 of 43 loads, 2026-11-04) and
    DISTINCT ON picked at random, so the comment changed between sends with no news."""
    tied = [{"comment": "Appointment confirmed at EC Logistics, PHARR, TX for 11/02/26 0900 to 11/02/26 2000."},
            {"comment": "Loaded at the shipper Central Texas Corrugated at 10/31/26 1000."},
            {"comment": "Empty at consignee EC Logistics, PHARR, TX at 11/01/26 0700."},
            {"comment": "Departed ACG Global, LAREDO, TX at 10/31/26 2300."}]
    assert "Empty at consignee" in cards.newest_comment(tied)["comment"]
    assert "Empty at consignee" in cards.newest_comment(list(reversed(tied)))["comment"]
    # The truck left the yard after reaching it: the departure wins.
    left = [{"comment": "Empty at consignee EC Logistics, PHARR, TX at 11/01/26 0700."},
            {"comment": "Departed EC Logistics, PHARR, TX at 11/02/26 1600."}]
    assert "Departed" in cards.newest_comment(left)["comment"]
    # Free text outranks an appointment, an actual stop event outranks free text.
    appt = tied[0]
    free = {"comment": "A driver update from Austin, TX."}  # sorts before the appointment
    assert cards.newest_comment([appt, free]) == free
    assert cards.newest_comment([free, tied[1]]) == tied[1]
    # An impossible time is not a crash.
    bad = {"comment": "Departed EC Logistics, PHARR, TX at 13/45/26 2500."}
    assert cards.newest_comment([bad]) == bad


def test_comments_sql_keeps_every_comment_of_the_newest_minute():
    assert "DISTINCT ON" not in data.COMMENTS_SQL
    assert "rank() OVER (PARTITION BY h.id ORDER BY h.posted_date DESC)" in data.COMMENTS_SQL


# ---------------------------------------------------------------------------
# Customer feedback 2026-11-10 (n8n-report.pdf): the pick-up On-Time / Late pill
# becomes a small dot beside the pick-up time, and the brokerage-status word under
# Current Location is gone. Everything else — ARRIVED pill, delivered section,
# ETA hours pill — stays as it was ("everything else is fine").
# ---------------------------------------------------------------------------
STATUS_WORDS = ("IN PROGRESS", "IN TRANSIT", "AT CARRIER YARD", "AT CUSTOMS YARD",
                "CROSSING THE BORDER", "AT US YARD", "LOADED", "COVERED")


def _pu_cell(card) -> str:
    return html._times_in_progress(card)


def test_pickup_on_time_is_a_green_dot_beside_the_time_not_a_pill():
    c = cards.build_card(_order(), cards.IN_PROGRESS, {}, NOW)
    assert c.pu_on_time is True
    cell = _pu_cell(c)
    assert html.pill("On-Time", True) not in cell and "&#9888;" not in cell
    # The dot sits on the SAME line as the pick-up time, after it.
    line = re.search(r"<div [^>]*>10/19/2026 @ 04:36 PM(.*?)</div>", cell)
    assert line and html.DOT_GOOD in line.group(1) and "&#9679;" in line.group(1)
    assert 'title="On-Time"' in line.group(1)


def test_pickup_late_is_a_red_dot():
    c = cards.build_card(_order(pu_in=datetime(2026, 10, 20, 2)), cards.IN_PROGRESS, {}, NOW)
    assert c.pu_on_time is False
    cell = _pu_cell(c)
    assert "Late</span>" not in cell.replace('title="Late"', "")
    assert html.DOT_BAD in cell and 'title="Late"' in cell and html.DOT_GOOD not in cell


def test_no_pickup_actual_means_no_dot():
    c = cards.build_card(_order(pu_in=None, pu_out=None), cards.IN_PROGRESS, {}, NOW)
    cell = _pu_cell(c)
    assert "&#9679;" not in cell and "On-Time" not in cell and "Late" not in cell


def test_dot_survives_print_and_is_outlook_safe():
    """Print drops backgrounds: the dot is a coloured TEXT glyph, never a fill."""
    dot = html.status_dot(True)
    assert "background" not in dot and f"color:{html.DOT_GOOD}" in dot
    assert "font-family:" in dot
    assert html.status_dot(None) == ""


def test_brokerage_status_word_is_not_shown():
    for code in cards.STATUS_LABELS:
        details = {"movements": {"0349842": [{"movement_id": "1", "brokerage_status": code}]}}
        c = cards.build_card(_order(), cards.IN_PROGRESS, details, NOW)
        out = html.card_in_progress(c)
        for word in STATUS_WORDS:
            assert word not in out, (code, word)
    # No active leg at all used to print the fallback "IN PROGRESS".
    out = html.card_in_progress(cards.build_card(_order(), cards.IN_PROGRESS, {}, NOW))
    assert "IN PROGRESS" not in out


def test_status_label_still_feeds_the_ops_coverage_panel():
    c = cards.build_card(_order(), cards.IN_PROGRESS, _details(None), NOW)
    assert c.status_label == "In transit"
    rc = cards.ReportCards(report=DONNA, in_progress=(c,), scheduled=(), delivered=())
    assert cards.eta_coverage(rc)["missing"][0]["status"] == "In transit"


def test_delivered_and_arrived_pills_are_unchanged():
    d = _order(status="D", del_in=datetime(2026, 10, 20, 9), del_out=datetime(2026, 10, 20, 10))
    out = html.card_delivered(cards.build_card(d, cards.DELIVERED, {}, NOW))
    assert out.count(html.pill("On-Time", True)) == 2
    arrived = html.card_in_progress(cards.build_card(
        _order(del_in=datetime(2026, 10, 20, 19)), cards.IN_PROGRESS, {}, NOW))
    assert html.pill("Late", False) in arrived
