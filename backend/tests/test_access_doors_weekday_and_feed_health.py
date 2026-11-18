"""Access Log Doors — weekday start times + door-data health (2026-11-18).

Offline: inspects emitted SQL, unit-tests the feed classifier, and drives the
new endpoint through FastAPI with a stub pool.

Origin (Infrastructure, Katerine Meneses, on the 11-17 night e-mail):
  "Alan llega súper temprano ... el reporte le toma la huella que hay alrededor
   de las 10 y no la primera del día. Lo mismo para Antonio. Los sábados que
   llega a las 8am el reporte busca la huella cercana a las 6pm."
Two causes, measured:
  1. The 2ND FLOOR reader (~270 punches/weekday) and SITE MTY stopped reaching
     the datalake on 11-16 (last 11:28 / 08:58 Monterrey); 11-17 has no record
     at all before 10:22. 3F Door kept syncing, so no freshness signal moved.
  2. One start time per person for every weekday: Antonio works nights 18:00
     but a DAY shift on Saturdays, so 11-14 scored a 15:24 badge against 18:00.
"""

from __future__ import annotations

import pathlib
import re

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.routers import access_doors_feed_health as fh
from app.routers import deps as deps_mod
from app.routers import hr_access_doors, scoped_access_doors
from app.routers.hr_access_doors import _first_punch_cte
from app.services import access_doors_delays_digest

FIRST = re.sub(r"\s+", " ", _first_punch_cte("$1", "$2"))


def _squash(sql: str) -> str:
    return re.sub(r"\s+", " ", sql)


# ---------------------------------------------------------------------------
# C — weekday start times
# ---------------------------------------------------------------------------


class TestWeekdayRules:
    def test_the_weekday_table_is_consulted_for_today_and_for_yesterday(self):
        """`ex_today` = a shift starting on the punch date; `ex_prev` = one that
        began the evening before. Both must read the weekday table."""
        assert FIRST.count("public.late_arrival_schedule_weekday") == 2
        assert "wt.weekday = EXTRACT(dow FROM s.event_time::date)::int" in FIRST
        assert "wp.weekday = EXTRACT(dow FROM s.event_time::date - 1)::int" in FIRST
        assert "COALESCE(wt.expected_time, s.base_time) AS ex_today" in FIRST
        assert "COALESCE(wp.expected_time, s.base_time) AS ex_prev" in FIRST

    def test_weekday_rows_are_keyed_on_email_only_and_active(self):
        for alias in ("wt", "wp"):
            assert f"LEFT JOIN public.late_arrival_schedule_weekday {alias} ON {alias}.active" in FIRST
            assert f"lower(btrim({alias}.email)) = s.em" in FIRST

    def test_weekday_lookup_is_an_uncorrelated_join_not_a_subplan(self):
        """A per-punch correlated subquery serialises the scan (§134)."""
        assert "FROM public.late_arrival_schedule_weekday" not in FIRST

    def test_backdating_and_the_scored_start_use_one_predicate(self):
        """Shift date and its expected start come from the SAME test, so a
        back-dated punch is always scored against the shift it was moved onto."""
        pred = _squash(hr_access_doors._BACKDATE_PREDICATE).strip()
        assert FIRST.count(pred) == 2
        assert f"CASE WHEN {pred} THEN a.event_time::date - 1" in FIRST
        assert f"CASE WHEN {pred} THEN a.ex_prev ELSE a.ex_today END AS expected_time" in FIRST

    def test_the_window_and_score_read_the_chosen_start(self):
        assert "w.shift_date + w.expected_time - INTERVAL '3 hours'" in FIRST
        assert "r.shift_date + r.expected_time END AS expected" in FIRST

    def test_base_rule_lookup_is_unchanged_and_renamed_base_time(self):
        assert "FROM public.late_arrival_schedule s" in FIRST
        assert "AS base_time" in FIRST
        # The old single-rule column must not be read before the weekday step.
        assert "SELECT p.*," in FIRST and "AS expected_time FROM punches p" not in FIRST

    def test_every_consumer_inherits_the_weekday_rules(self):
        """Scoped clones and the DFW digest build on the same CTE."""
        assert "late_arrival_schedule_weekday" in access_doors_delays_digest._build_sql()
        src = pathlib.Path(scoped_access_doors.__file__).read_text(encoding="utf-8")
        assert "_first_punch_cte" in src and "late_arrival_schedule s" not in src


# ---------------------------------------------------------------------------
# B — door-data health classifier
# ---------------------------------------------------------------------------


def _rows(counts: dict[str, list[int]], last: str | None = "2026-11-16T11:28:06") -> list[dict]:
    """counts[reader] = [k0, k1, k2, k3, k4]; a 0 is emitted as NO row, exactly
    like the SQL GROUP BY does for a silent reader."""
    out = []
    for reader, ns in counts.items():
        for k, n in enumerate(ns):
            if n:
                out.append({"reader": reader, "k": k, "n": n, "last_event_cst": last})
    return out


# Measured 2026-11-17 (Tue, full day) vs the 4 previous Tuesdays.
NOV_17 = {
    "2ND FLOOR": [0, 270, 237, 276, 259],
    "3F Door": [25, 51, 31, 40, 36],
    "IT ROOM": [14, 22, 15, 18, 18],
    "SITE MTY": [0, 14, 1, 12, 1],
}


class TestClassifier:
    def test_nov_17_flags_the_dead_main_entrance_and_the_building(self):
        h = fh.classify_door_feed(_rows(NOV_17))
        assert h.down == ("2ND FLOOR",)
        assert h.building_degraded and h.degraded
        second = next(r for r in h.readers if r.reader == "2ND FLOOR")
        assert second.today == 0 and second.baseline == 264.5

    def test_a_reader_silent_all_day_still_appears(self):
        """No row on the date must read as 0, not as 'reader absent'."""
        h = fh.classify_door_feed(_rows(NOV_17))
        assert "2ND FLOOR" in {r.reader for r in h.readers}

    def test_a_normally_quiet_reader_can_never_trip(self):
        """SITE MTY (median 6.5) at 0 is noise, not an outage."""
        h = fh.classify_door_feed(_rows(NOV_17))
        site = next(r for r in h.readers if r.reader == "SITE MTY")
        assert not site.down

    def test_a_normal_weekday_is_clean(self):
        normal = {"2ND FLOOR": [269, 270, 237, 276, 259], "3F Door": [44, 51, 31, 40, 36]}
        assert not fh.classify_door_feed(_rows(normal)).degraded

    def test_a_holiday_level_dip_is_not_an_outage(self):
        """2026-09-16 (Mexican Independence Day): 182 vs ~280 — not flagged."""
        holiday = {"2ND FLOOR": [182, 275, 295, 285, 279], "3F Door": [18, 49, 46, 58, 53]}
        assert not fh.classify_door_feed(_rows(holiday)).degraded

    def test_weekends_never_trip_on_low_volume(self):
        weekend = {"2ND FLOOR": [0, 11, 5, 6, 8], "3F Door": [0, 11, 8, 5, 3]}
        assert not fh.classify_door_feed(_rows(weekend)).degraded

    @pytest.mark.parametrize(
        "today,baseline,down",
        [(3, 15, True), (4, 15, False), (0, 14, False), (66, 264.5, True), (67, 264.5, False)],
    )
    def test_reader_threshold_edges(self, today, baseline, down):
        assert fh.classify_reader(today, baseline) is down

    @pytest.mark.parametrize(
        "today,baseline,deg", [(11, 30, True), (12, 30, False), (0, 29, False)]
    )
    def test_building_threshold_edges(self, today, baseline, deg):
        assert fh.classify_building(today, baseline) is deg

    def test_median_resists_one_bad_baseline_week(self):
        """A past outage in the baseline must not lower the normal enough to hide a new one."""
        h = fh.classify_door_feed(_rows({"2ND FLOOR": [0, 270, 0, 276, 259]}))
        assert h.down == ("2ND FLOOR",)

    def test_payload_shape(self):
        from datetime import date, time

        h = fh.classify_door_feed(_rows(NOV_17))
        p = fh.feed_health_payload(date(2026, 11, 17), h, time(23, 59, 59))
        assert p["date"] == "2026-11-17" and p["cutoff"] == "23:59:59"
        assert p["down"] == ["2ND FLOOR"] and p["degraded"] is True
        assert {"reader", "today", "baseline", "last_event", "down"} <= set(p["readers"][0])


class TestFeedSql:
    SQL = _squash(fh.FEED_HEALTH_SQL)

    def test_exit_button_is_excluded_everywhere(self):
        assert self.SQL.count("verify_mode_no IS DISTINCT FROM 200") == 2

    def test_counts_are_bounded_on_event_date(self):
        assert "z.event_date IN (SELECT d FROM days)" in self.SQL
        assert "z.event_date BETWEEN $1::date - 28 AND $1::date" in self.SQL

    def test_baseline_is_same_weekday_and_same_cutoff(self):
        assert f"generate_series(0, {fh.BASELINE_WEEKS})" in self.SQL
        assert "($1::date - 7 * k)::date" in self.SQL
        assert "z.event_time::time <= cut.t" in self.SQL

    def test_cutoff_is_monterrey_now_only_for_today(self):
        assert "(now() AT TIME ZONE 'America/Monterrey')::time" in self.SQL
        assert "TIME '23:59:59.999999'" in self.SQL

    def test_last_record_is_displayed_in_cst(self):
        assert "AT TIME ZONE 'America/Monterrey' AT TIME ZONE 'America/Chicago'" in self.SQL


# ---------------------------------------------------------------------------
# B — the route on every Access Doors report, behind its own gate
# ---------------------------------------------------------------------------

ROUTERS = {
    "hr-access-doors": hr_access_doors.router,
    "dfw-access-doors": scoped_access_doors.dfw_router,
    "admin-access-doors": scoped_access_doors.admin_router,
    "ops-access-doors": scoped_access_doors.ops_router,
    "pricing-access-doors": scoped_access_doors.pricing_router,
    "carrier-procurement-access-doors": scoped_access_doors.carrier_procurement_router,
}


class _StubPool:
    def __init__(self, rows: list[dict]) -> None:
        self.rows = rows
        self.calls: list[tuple[str, tuple]] = []

    async def fetch(self, sql, *params):
        self.calls.append((sql, params))
        return self.rows


@pytest.mark.parametrize("key", sorted(ROUTERS))
def test_every_report_serves_door_feed_health(monkeypatch, key):
    from datetime import date

    rows = [{**r, "cutoff": "23:59:59.999999"} for r in _rows(NOV_17)]
    pool = _StubPool(rows)
    monkeypatch.setattr(fh, "get_datalake_gold_pool", lambda request: pool)
    app = FastAPI()
    app.include_router(ROUTERS[key], prefix="/api")
    app.dependency_overrides[deps_mod.require_user] = lambda: {"sub": "t", "roles": ["admin"]}
    client = TestClient(app)
    r = client.get(f"/api/custom/{key}/door-feed-health", params={"date": "2026-11-17"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["success"] is True
    assert body["data"]["down"] == ["2ND FLOOR"]
    assert pool.calls and pool.calls[0][1] == (date(2026, 11, 17),)


@pytest.mark.parametrize("key", sorted(ROUTERS))
def test_door_feed_health_is_behind_the_reports_own_gate(key):
    """The route must carry the same `require_report_access(<key>)` guard as the report."""
    def gate_keys(path_suffix: str) -> set:
        route = next(r for r in ROUTERS[key].routes if r.path.endswith(path_suffix))
        keys: set = set()
        for dep in route.dependant.dependencies:
            for cell in dep.call.__closure__ or ():
                val = cell.cell_contents
                if isinstance(val, tuple) and val and all(isinstance(v, str) for v in val):
                    keys.add(val)
        return keys

    assert gate_keys("/door-feed-health") == gate_keys("/kpis") == {(key,)}, (
        f"{key}: door-feed-health is not behind the report's own gate"
    )


def test_door_feed_health_names_no_person():
    """Reader names and counts only — why it is safe on every scoped clone."""
    sql = _squash(fh.FEED_HEALTH_SQL)
    for col in ("full_name", "email", "timeoff_employee"):
        assert col not in sql


def test_section_is_decided_for_the_ai_assistant():
    from app.services.ai_chat_tools import SECTION_ALLOWLIST

    assert "door-feed-health" in SECTION_ALLOWLIST


def test_both_frontends_render_the_banner():
    """No JS test runner (§107) — guard the wiring from here."""
    root = pathlib.Path(__file__).resolve().parents[2] / "frontend"
    hr = (root / "app/reports/hr-access-doors/page.tsx").read_text(encoding="utf-8")
    scoped = (root / "components/access-doors/ScopedAccessDoorsReport.tsx").read_text(encoding="utf-8")
    assert '<DoorFeedHealthBanner reportKey="hr-access-doors" date={endDate} />' in hr
    assert "<DoorFeedHealthBanner reportKey={slug} date={endDate} />" in scoped
    lib = (root / "lib/door-feed-health.ts").read_text(encoding="utf-8")
    assert "queryKey: [reportKey, \"door-feed-health\", date]" in lib
    assert "new Date(" not in lib
