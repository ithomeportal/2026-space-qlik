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
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from app.services.customer_status_email import cards, config, data, html, sender

CST = ZoneInfo("America/Chicago")
NOW = datetime(2026, 10, 20, 12, 0, tzinfo=CST)
NAIVE_NOW = NOW.replace(tzinfo=None)
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
                       "IECEMON1", "INNOSANX", "NEFAZAJA", "PARQTLJA"},
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


def _details(eta, leg_city="DONNA", gps_at=NAIVE_NOW - timedelta(minutes=5)):
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
                         _details(datetime(2026, 10, 20, 21, 30)), NOW)
    assert c.hours_vs_appt == 3.5 and c.eta_place is None
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
                         _details(NAIVE_NOW - timedelta(hours=20)), NOW)
    assert c.eta is None and c.hours_vs_appt is None


def test_an_old_gps_fix_is_not_a_current_location():
    c = cards.build_card(_order(), cards.IN_PROGRESS,
                         _details(None, gps_at=NAIVE_NOW - timedelta(hours=30)), NOW)
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
    for title in html.SECTIONS:
        assert title in out
    assert out.count(html.EMPTY_TEXT) == 2  # scheduled + delivered are empty
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
        empty = {r.key: cards.ReportCards(r, (), (), ()) for r in config.REPORTS}
        return empty, []

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
    assert sql.count("> '2000-01-01'") == 8  # every McLeod timestamp sentinel-guarded
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
                  data.COMMENTS_SQL]

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
    """Augie's new_eta is CST; an El Paso appointment is Mountain time. ETA 10:00
    CST = 09:00 MT against a 09:30 MT appointment is 0.5 h AHEAD, not behind."""
    order = _order(dest_city="EL PASO", del_sched_late=datetime(2026, 10, 20, 9, 30))
    det = _details(datetime(2026, 10, 20, 10, 0), leg_city="EL PASO")
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
    # Anything else (Augie free text, LOADSHIP at the shipper) is untouched.
    for text in ("In transit in Austin, TX; ETA Donna 9:00 AM.",
                 "Loaded at the shipper Central Texas Corrugated at 10/19/26 1335."):
        assert cc(text, "PCA DONNA") == text
    assert cc(None, "PCA DONNA") is None
