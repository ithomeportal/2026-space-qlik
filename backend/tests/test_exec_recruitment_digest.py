"""Weekly "Recruitment Status" e-mail + /pipeline — offline proof.

No DB, no network. What can go wrong SILENTLY here, and which test pins it:

  * the CST week boundary — Prisma stores naive UTC, so a Sunday-evening move
    (Oct 11 22:00 CDT = Oct 12 03:00 UTC) bucketed by its UTC date lands in the
    WRONG week; and the CDT→CST change shifts midnight by an hour;
  * the current, incomplete week leaking in as "last week" on a Monday;
  * a log row counted as an event — a candidate moved Screening → back →
    Screening is ONE screened candidate, in the week of the FIRST arrival;
  * a skipped stage — straight to HR Interview must still count as screened;
  * a renamed stage silently dropping out of every count (``unknown_stages``);
  * a dead Jobs portal printing a quiet week of zeros (stale -> 503);
  * an excluded department (Seek / OilTex / Presidency / Aviation) leaking in;
  * a role with NOBODY in the pipeline vanishing from the open-roles table;
  * a failed source endpoint becoming a partial e-mail (must be 502);
  * the machine bearer failing OPEN.
"""
from __future__ import annotations

import asyncio
import inspect
import re
from datetime import date, datetime

import pytest
from fastapi.testclient import TestClient

from app.config import settings
from app.routers import exec_meeting_recruitment_pipeline as pipe
from app.routers import exec_recruitment_digest as digest_router
from app.services import exec_recruitment_digest as svc
from app.services.exec_recruitment_digest_html import baseline, render_html

MON = date(2026, 10, 12)               # a Monday: the send day
MONDAYS = pipe.completed_weeks(MON, 8)  # latest first
STAGES = {f"s{order}": order for order in range(10)}  # stageId -> order


def utc(*a) -> datetime:
    return datetime(*a)  # naive UTC, as Prisma stores it


# ---------------------------------------------------------------------------
# Week windows
# ---------------------------------------------------------------------------


class TestWeeks:
    def test_monday_reports_the_week_that_ended_yesterday(self):
        assert MONDAYS[0] == date(2026, 10, 5)
        assert MONDAYS[-1] == date(2026, 8, 17)
        assert len(MONDAYS) == 8

    def test_sunday_does_not_report_its_own_incomplete_week(self):
        assert pipe.completed_weeks(date(2026, 10, 11), 1) == [date(2026, 9, 28)]

    def test_sunday_evening_cst_belongs_to_that_week_not_utc_monday(self):
        # Oct 11 22:00 CDT == Oct 12 03:00 UTC. UTC-date bucketing says week of Oct 12.
        assert pipe.week_of(utc(2026, 10, 12, 3, 0), MONDAYS) == 0
        # And Monday 00:30 CDT is already the NEXT (current) week -> outside.
        assert pipe.week_of(utc(2026, 10, 12, 5, 30), MONDAYS) is None

    def test_cst_midnight_follows_dst(self):
        assert pipe.cst_midnight_utc(date(2026, 10, 5)) == utc(2026, 10, 5, 5, 0)   # CDT
        assert pipe.cst_midnight_utc(date(2026, 11, 9)) == utc(2026, 11, 9, 6, 0)   # CST


# ---------------------------------------------------------------------------
# First arrival — transitions are a log, not events
# ---------------------------------------------------------------------------


class _Pool:
    def __init__(self, rows):
        self.rows = rows

    async def fetch(self, sql, *params):
        return self.rows


def _firsts(rows):
    return asyncio.run(pipe._first_arrivals(_Pool(rows), STAGES, utc(2026, 8, 17)))


def _tr(app, stage, at, position="p1"):
    return {"app": app, "stage": stage, "at": at, "position": position}


class TestFirstArrival:
    def test_a_bounce_counts_once_in_the_week_of_the_first_arrival(self):
        f = _firsts([
            _tr("a", "s3", utc(2026, 9, 30, 15)),   # screening, week of Sep 28
            _tr("a", "s1", utc(2026, 10, 6, 15)),   # sent back
            _tr("a", "s3", utc(2026, 10, 7, 15)),   # screening AGAIN, week of Oct 5
        ])
        assert len(f) == 1
        assert pipe.week_of(f[0]["screened"], MONDAYS) == 1
        assert f[0].get("valid") is None

    def test_skipping_screening_still_counts_as_screened(self):
        f = _firsts([_tr("b", "s4", utc(2026, 10, 6, 15))])
        assert pipe.week_of(f[0]["screened"], MONDAYS) == 0
        assert pipe.week_of(f[0]["valid"], MONDAYS) == 0

    def test_an_unknown_stage_counts_for_nothing(self):
        f = _firsts([_tr("c", "renamed-stage", utc(2026, 10, 6, 15))])
        assert f == []

    def test_unknown_stage_names_are_reported_only_when_in_use(self):
        class P:
            async def fetch(self, sql, *a):
                return [{"id": "x", "name": "Phone Screening", "in_use": True},
                        {"id": "y", "name": "Phone Screen (new)", "in_use": True},
                        {"id": "z", "name": "Old custom stage", "in_use": False}]

        orders, unknown = asyncio.run(pipe._stage_orders(P(), utc(2026, 8, 17)))
        assert orders == {"x": 3}
        assert unknown == ["Phone Screen (new)"]


# ---------------------------------------------------------------------------
# Aggregation
# ---------------------------------------------------------------------------


POSITIONS = {
    "p1": {"name": "Booker", "department": "DFW OPERATIONS", "status": "ACTIVE",
           "type": "STANDARD", "created_at": utc(2026, 9, 1)},
    "p2": {"name": "Empty Role", "department": "Finance", "status": "ACTIVE",
           "type": "EVERGREEN", "created_at": utc(2026, 8, 1)},
    "px": {"name": "Seek thing", "department": "Seek", "status": "ACTIVE",
           "type": "STANDARD", "created_at": utc(2026, 8, 1)},
    "pc": {"name": "Closed", "department": "IT", "status": "CLOSED",
           "type": "STANDARD", "created_at": utc(2026, 7, 1)},
}


def _app(i, pos, stage, status="IN_PROCESS", created=utc(2026, 10, 6, 15),
         updated=utc(2026, 10, 12, 15), hired=None, first="Ana", last="Ruiz"):
    return {"id": i, "positionId": pos, "stageId": stage, "status": status,
            "createdAt": created, "updatedAt": updated, "hiredAt": hired,
            "firstName": first, "paternalLastName": last}


def _build(apps, firsts=(), tickets=(), offers=None, dept=None):
    return pipe.build_pipeline(
        mondays=MONDAYS, positions=POSITIONS, stage_orders=STAGES,
        firsts=list(firsts), applications=apps, offers=offers or {},
        tickets=list(tickets), wanted_dept=dept, now_utc=utc(2026, 10, 12, 21),
    )


class TestTicketTotals:
    def test_window_and_ytd_stop_at_the_last_completed_sunday(self):
        tickets = [
            {"category": "Onboarding", "department": "IT", "at": utc(2026, 1, 1, 7)},     # Jan 1 CST
            {"category": "Onboarding", "department": "IT", "at": utc(2026, 1, 1, 5)},     # Dec 31 CST
            {"category": "Offboarding", "department": "IT", "at": utc(2026, 9, 1, 15)},   # in window
            {"category": "Offboarding", "department": "IT", "at": utc(2026, 10, 12, 3)},  # Sun Oct 11 CDT
            {"category": "Offboarding", "department": "IT", "at": utc(2026, 10, 12, 15)}, # today: excluded
            {"category": "Offboarding", "department": "Seek", "at": utc(2026, 9, 1, 15)}, # excluded dept
        ]
        t = pipe.ticket_totals(tickets, MONDAYS, None)
        assert t["window"] == {"onboarding": 0, "offboarding": 2}
        assert t["ytd"] == {"onboarding": 1, "offboarding": 2}
        assert (t["window_start"], t["window_end"]) == ("2026-08-17", "2026-10-11")

    def test_build_returns_totals(self):
        d = pipe.build_pipeline(mondays=MONDAYS, positions={}, stage_orders={}, firsts=[],
                                applications=[], offers={}, tickets=[], wanted_dept=None,
                                now_utc=utc(2026, 10, 12, 21))
        assert d["ticket_totals"]["ytd"] == {"onboarding": 0, "offboarding": 0}


def _rej(app, pos, stage, at, fallback=False):
    return {"app": app, "position": pos, "stage": stage, "at": at, "fallback": fallback}


class TestRejections:
    """HR 2026-10-12: rejections at the screening stages were missing."""

    def _b(self, rejections):
        return pipe.build_pipeline(
            mondays=MONDAYS, positions=POSITIONS, stage_orders=STAGES, firsts=[],
            applications=[], offers={}, tickets=[], wanted_dept=None,
            now_utc=utc(2026, 10, 12, 21), rejections=rejections)

    def test_grouped_by_the_stage_at_rejection(self):
        d = self._b([_rej("a", "p1", "s1", utc(2026, 10, 6, 15)),   # Candidates
                     _rej("b", "p1", "s3", utc(2026, 10, 7, 15)),   # Phone Screening
                     _rej("c", "p1", "s4", utc(2026, 10, 7, 15)),   # HR Interview
                     _rej("d", "p1", "s7", utc(2026, 10, 8, 15))])  # Send Offer
        w = d["weeks"][0]
        assert (w["rejected_screening"], w["rejected_interview"], w["rejected_final"],
                w["rejected_total"]) == (2, 1, 1, 4)

    def test_a_double_logged_rejection_counts_once_per_week(self):
        d = self._b([_rej("a", "p1", "s3", utc(2026, 10, 6, 15)),
                     _rej("a", "p1", "s3", utc(2026, 10, 6, 15, 1))])
        assert d["weeks"][0]["rejected_total"] == 1

    def test_re_rejection_in_another_week_counts_again(self):
        d = self._b([_rej("a", "p1", "s3", utc(2026, 9, 30, 15)),
                     _rej("a", "p1", "s3", utc(2026, 10, 6, 15))])
        assert d["weeks"][0]["rejected_total"] == 1 and d["weeks"][1]["rejected_total"] == 1

    def test_sunday_evening_rejection_is_last_week(self):
        d = self._b([_rej("a", "p1", "s2", utc(2026, 10, 12, 3))])   # Oct 11 22:00 CDT
        assert d["weeks"][0]["rejected_screening"] == 1

    def test_excluded_department_never_counts(self):
        d = self._b([_rej("a", "px", "s3", utc(2026, 10, 6, 15))])
        assert d["weeks"][0]["rejected_total"] == 0

    def test_roles_split_last_week_screening_vs_later(self):
        d = self._b([_rej("a", "p1", "s2", utc(2026, 10, 6, 15)),
                     _rej("b", "p1", "s5", utc(2026, 10, 6, 15)),
                     _rej("c", "p1", "s3", utc(2026, 9, 30, 15))])   # week before: not LW
        r = next(x for x in d["roles"] if x["position_id"] == "p1")
        assert (r["rejected_screening_last_week"], r["rejected_later_last_week"]) == (1, 1)

    def test_without_rejections_the_series_are_zero_not_missing(self):
        d = self._b(None)
        assert d["weeks"][0]["rejected_total"] == 0


def _stat(dept, division, **kw):
    base = {"department": dept, "division": division, "active_candidates": 0,
            "new_apps_lw": 0, "screened_lw": 0, "valid_lw": 0, "rejected_lw": 0,
            "rejected_screening_lw": 0, "hires_ytd": 0, "fill_days_sum": 0, "fill_days_n": 0}
    return {**base, **kw}


class TestDivisions:
    """2026-10-12: "indicators per division, how many positions open, days …
    and comparison between divisions"."""

    OPEN = [
        {"department": "CORP OPERATIONS", "days_open": 100, "open_vacancies": 1},
        {"department": "CORP OPERATIONS", "days_open": 20, "open_vacancies": 1},
        {"department": "IT", "days_open": 168, "open_vacancies": 2},
        {"department": "DFW OPERATIONS", "days_open": 30, "open_vacancies": 4},
    ]
    STATS = [
        _stat("CORP OPERATIONS", "CORP", active_candidates=10, hires_ytd=2,
              fill_days_sum=40, fill_days_n=2),
        _stat("Finance", "CORP", hires_ytd=1, fill_days_sum=100, fill_days_n=1),
        _stat("DFW OPERATIONS", "DFW", active_candidates=5, valid_lw=3),
    ]

    def rows(self):
        return {r["label"]: r for r in svc.division_table(self.OPEN, self.STATS)}

    def test_division_is_by_department_not_area(self):
        assert pipe.division_of("DFW OPERATIONS") == "DFW"
        assert pipe.division_of("IT") == "CORP"

    def test_average_days_open_is_over_roles_not_over_departments(self):
        corp = self.rows()["CORP"]
        assert corp["open_roles"] == 3
        assert corp["avg_days_open"] == round((100 + 20 + 168) / 3)   # not mean(60, 168)
        assert corp["oldest_days"] == 168 and corp["over_60"] == 2

    def test_days_to_fill_is_over_hires(self):
        assert self.rows()["CORP"]["avg_days_to_fill_ytd"] == round(140 / 3)

    def test_departments_without_open_roles_fold_into_one_row(self):
        r = self.rows()
        assert "Finance" not in r
        other = r["Other departments (1, no open role)"]
        assert other["hires_ytd"] == 1 and other["open_roles"] == 0
        assert r["IT"]["active_candidates"] == 0 and r["IT"]["open_roles"] == 1
        assert r["CORP"]["hires_ytd"] == 3          # folded rows still in the subtotal

    def test_single_department_division_has_no_duplicate_child_row(self):
        labels = [r["label"] for r in svc.division_table(self.OPEN, self.STATS)]
        assert labels.count("DFW OPERATIONS") == 0 and "DFW" in labels
        assert labels[-1] == "TOTAL"

    def test_total_adds_up(self):
        t = self.rows()["TOTAL"]
        assert (t["open_roles"], t["open_vacancies"], t["active_candidates"]) == (4, 8, 15)

    def test_comparison_sentence(self):
        note = svc.division_comparison(svc.division_table(self.OPEN, self.STATS))
        assert note.startswith("CORP roles have been open 3.2× longer than DFW")

    def test_no_comparison_when_a_division_is_missing(self):
        rows = svc.division_table(self.OPEN[:3], self.STATS[:2])
        assert svc.division_comparison(rows) is None


class TestBuild:
    def test_excluded_departments_never_count(self):
        d = _build([_app("1", "px", "s3"), _app("2", "p1", "s3")],
                   firsts=[{"position": "px", "screened": utc(2026, 10, 6, 15)}])
        assert d["weeks"][0]["new_applications"] == 1
        assert d["weeks"][0]["screened"] == 0
        assert d["snapshot"]["active_candidates"] == 1
        assert {r["position_id"] for r in d["roles"]} == {"p1", "p2"}

    def test_a_role_with_nobody_in_the_pipeline_still_prints(self):
        d = _build([_app("1", "p1", "s3")])
        empty = next(r for r in d["roles"] if r["position_id"] == "p2")
        assert empty["in_pipeline"] == 0 and empty["furthest_stage"] is None

    def test_closed_positions_are_not_open_roles_but_their_hires_count(self):
        d = _build([_app("h", "pc", "s9", status="HIRED", hired=utc(2026, 10, 7, 15))])
        assert all(r["position_id"] != "pc" for r in d["roles"])
        assert d["weeks"][0]["hires"] == 1
        assert d["hires_last_week"][0]["name"] == "Ana Ruiz"

    def test_stalled_reports_bench_separately(self):
        old = utc(2026, 9, 1)
        d = _build([_app("1", "p1", "s0", updated=old),      # parked on Bench
                    _app("2", "p1", "s4", updated=old),      # genuinely stuck
                    _app("3", "p1", "s4")])                  # moving
        assert d["snapshot"]["stalled"] == 2
        assert d["snapshot"]["stalled_excl_bench"] == 1

    def test_offer_stage_is_counted_from_the_pipeline_not_the_offer_table(self):
        d = _build([_app("1", "p1", "s6"), _app("2", "p1", "s7"), _app("3", "p1", "s5")])
        assert d["snapshot"]["at_offer_stage"] == 2
        assert d["snapshot"]["offers_recorded"] == 0

    def test_acceptance_rate_is_none_not_zero_when_nothing_decided(self):
        d = _build([_app("1", "p1", "s3")])
        assert d["snapshot"]["offer_acceptance"]["rate"] is None

    def test_tickets_bucket_by_cst_week_and_respect_exclusions(self):
        d = _build([], tickets=[
            {"category": "Offboarding", "department": "IT", "at": utc(2026, 10, 12, 3)},
            {"category": "Onboarding", "department": "Seek", "at": utc(2026, 10, 7)},
        ])
        assert d["weeks"][0]["offboarding_tickets"] == 1
        assert d["weeks"][0]["onboarding_tickets"] == 0

    def test_department_filter_scopes_every_series(self):
        d = _build([_app("1", "p1", "s3"), _app("2", "p2", "s3")], dept="Finance")
        assert d["weeks"][0]["new_applications"] == 1
        assert [r["position_id"] for r in d["roles"]] == ["p2"]


# ---------------------------------------------------------------------------
# Digest guards
# ---------------------------------------------------------------------------


class TestGuards:
    def test_a_silent_jobs_portal_is_refused(self):
        with pytest.raises(svc.DigestStaleError):
            svc.assert_pipeline_usable(
                {"pipeline_as_of": "2026-10-01T10:00-05:00", "unknown_stages": []}, MON)
        with pytest.raises(svc.DigestStaleError):
            svc.assert_pipeline_usable({"pipeline_as_of": None, "unknown_stages": []}, MON)

    def test_stage_drift_is_refused(self):
        with pytest.raises(svc.DigestStaleError):
            svc.assert_pipeline_usable(
                {"pipeline_as_of": "2026-10-12T10:00-05:00", "unknown_stages": ["X"]}, MON)

    def test_a_fresh_portal_passes(self):
        svc.assert_pipeline_usable(
            {"pipeline_as_of": "2026-10-12T10:00-05:00", "unknown_stages": []}, MON)

    def test_ticket_staleness(self):
        assert svc.tickets_stale("2026-10-08", MON) is False
        assert svc.tickets_stale("2026-10-01", MON) is True
        assert svc.tickets_stale(None, MON) is True

    def test_baseline_is_the_weeks_before_last_week(self):
        assert baseline([100, 1, 2, 3]) == 2
        assert baseline([5]) is None

    def test_subject(self):
        assert svc.subject_for(date(2026, 10, 5)) == \
            "Recruitment Status - Week 41 (Oct 5 - Oct 11, 2026)"

    def test_join_roles_keeps_order_and_fills_zeros(self):
        rows = svc.join_roles([{"id": "a", "days_open": 9}, {"id": "b", "days_open": 3}],
                              [{"position_id": "b", "in_pipeline": 4}])
        assert [r["id"] for r in rows] == ["a", "b"]
        assert rows[0]["in_pipeline"] == 0 and rows[1]["in_pipeline"] == 4


# ---------------------------------------------------------------------------
# Full build through the in-process endpoints (stubbed) + render
# ---------------------------------------------------------------------------


def _week(i, **kw):
    m = MONDAYS[i]
    base = {k: 0 for k, _, _ in __import__(
        "app.services.exec_recruitment_digest_html", fromlist=["WEEKLY_ROWS"]).WEEKLY_ROWS}
    return {"week_start": m.isoformat(),
            "week_end": date.fromordinal(m.toordinal() + 6).isoformat(), **base, **kw}


PAYLOADS = {
    "/summary": {"active_employees": 97, "open_roles": 1, "open_vacancies": 2, "avg_days_open": 70},
    "/open-roles": {"rows": [{"id": "p1", "name": "Booker <DFW>", "department": "DFW OPERATIONS",
                              "days_open": 70, "open_vacancies": 2}]},
    "/freshness": {"tickets": "2026-09-01", "people": "2026-10-12", "is_stale": True},
    "/annual": {"year": 2026, "new_hires": 72, "offboarding": 70, "turnover_rate": None,
                "turnover_basis": None},
    "/pipeline": {
        "weeks": [_week(i, valid=13 if i == 0 else 16) for i in range(8)],
        "snapshot": {"active_candidates": 3, "in_pipeline": 3, "by_stage": [],
                     "stalled": 2, "stalled_excl_bench": 1, "at_offer_stage": 0,
                     "offers_recorded": 0, "offers_pending": 0,
                     "offer_acceptance": {"accepted": 5, "rejected": 0, "rate": 1.0},
                     "time_to_fill": {"avg_days": 19, "evergreen_days": None,
                                      "standard_days": 18, "hires_measured": 5}},
        "roles": [], "hires_last_week": [],
        "by_department": [
            {"department": "DFW OPERATIONS", "division": "DFW", "active_candidates": 3,
             "new_apps_lw": 0, "screened_lw": 0, "valid_lw": 1, "rejected_lw": 0,
             "rejected_screening_lw": 0, "hires_ytd": 1, "fill_days_sum": 10, "fill_days_n": 1}],
        "ticket_totals": {"window_start": "2026-08-17", "window_end": "2026-10-11",
                          "year": 2026, "ytd_end": "2026-10-11",
                          "window": {"onboarding": 8, "offboarding": 11},
                          "ytd": {"onboarding": 12, "offboarding": 30}},
        "meta": {"pipeline_as_of": "2026-10-12T15:40-05:00", "unknown_stages": []},
    },
}


@pytest.fixture
def digest(monkeypatch):
    async def fake(app, calls):
        return [{"success": True, "data": PAYLOADS[path]} for path, _ in calls]

    monkeypatch.setattr(svc, "_get_many", fake)
    monkeypatch.setattr(svc, "cst_today", lambda: MON)
    monkeypatch.setattr(svc, "cst_now", lambda: datetime(2026, 10, 12, 16, 0))
    return asyncio.run(svc.build_recruitment_digest(app=None))


class TestDigest:
    def test_meta_is_what_the_n8n_assert_reads(self, digest):
        m = digest["meta"]
        assert m["week_no"] == 41
        assert m["last_week"] == {"start": "2026-10-05", "end": "2026-10-11"}
        assert m["weeks"] == 8 and m["open_roles"] == 1
        assert m["last_week_counts"]["valid"] == 13

    def test_every_section_the_workflow_asserts_is_present(self, digest):
        for section in ("WEEKLY PIPELINE", "ONBOARDING VS OFFBOARDING", "OPEN ROLES",
                        "HIRES LAST WEEK", "KEY INDICATORS"):
            assert section in digest["html"], section

    def test_stale_ticket_feed_shows_a_banner(self, digest):
        assert "ticket feed has no ticket since" in digest["html"]

    def test_names_are_escaped_and_none_is_a_dash(self, digest):
        assert "Booker &lt;DFW&gt;" in digest["html"]
        assert "Evergreen &mdash; d" in digest["html"]

    def test_flow_trend_has_a_row_per_week_and_a_total(self, digest):
        trend = digest["html"].split("ONBOARDING VS OFFBOARDING")[1].split("OPEN ROLES")[0]
        assert trend.count("<tr>") == 1 + 1 + 8 + 1  # totals headline + header + weeks + total
        assert "8 weeks" in trend

    def test_flow_bars_are_text_so_they_survive_print(self):
        from app.services.exec_recruitment_digest_html import BLOCK, FLOW_BAR_MAX_BLOCKS, _bar
        assert _bar(3, 3, "#000000", "left").count(BLOCK) == FLOW_BAR_MAX_BLOCKS
        assert _bar(1, 2, "#000000", "left").count(BLOCK) == FLOW_BAR_MAX_BLOCKS // 2
        assert BLOCK not in _bar(0, 2, "#000000", "left")
        assert "bgcolor" not in _bar(3, 3, "#000000", "left")

    def test_section_headings_do_not_rely_on_a_background(self, digest):
        from app.services.exec_recruitment_digest_html import _section
        assert "background-color" not in _section("X")

    def test_full_period_and_ytd_totals_head_the_trend(self, digest):
        trend = digest["html"].split("ONBOARDING VS OFFBOARDING")[1].split("OPEN ROLES")[0]
        assert "Full period" in trend and "2026 year to date" in trend
        assert "12 on" in trend and "30 off" in trend      # YTD from the fixture

    def test_division_block_is_rendered_under_the_tiles(self, digest):
        html = digest["html"]
        assert "BY DIVISION" in html
        assert html.index("BY DIVISION") < html.index("WEEKLY PIPELINE")

    def test_rejections_block_is_rendered(self, digest):
        assert "REJECTIONS &mdash; by the stage" in digest["html"]
        assert "Rejected · sourcing &amp; screening" in digest["html"]

    def test_offer_acceptance_and_definitions_are_removed(self, digest):
        assert "Offer acceptance" not in digest["html"]
        assert "DEFINITIONS" not in digest["html"]

    def test_every_text_element_declares_its_font(self, digest):
        for tag in re.findall(r"<(?:td|th|div|span|a)\b[^>]*>", digest["html"]):
            assert "font-family" in tag, tag

    def test_no_rgb_no_scripts(self, digest):
        assert "rgb(" not in digest["html"] and "<script" not in digest["html"]

    def test_week_count_mismatch_is_refused(self, monkeypatch):
        short = dict(PAYLOADS["/pipeline"], weeks=PAYLOADS["/pipeline"]["weeks"][:7])

        async def fake(app, calls):
            return [{"success": True, "data": short if p == "/pipeline" else PAYLOADS[p]}
                    for p, _ in calls]

        monkeypatch.setattr(svc, "_get_many", fake)
        monkeypatch.setattr(svc, "cst_today", lambda: MON)
        with pytest.raises(svc.DigestSourceError):
            asyncio.run(svc.build_recruitment_digest(app=None))


# ---------------------------------------------------------------------------
# HTTP: auth + failure modes
# ---------------------------------------------------------------------------


class TestHttp:
    def test_gates_on_this_reports_key(self):
        assert digest_router.REPORT_KEY == "exec-meeting-recruitment"
        assert "require_digest_access(REPORT_KEY)" in inspect.getsource(digest_router.digest_email)

    def test_no_header_is_401(self, monkeypatch):
        from app.main import app

        monkeypatch.setattr(settings, "REPORTS_CRON_SECRET", "s3cr3t", raising=False)
        res = TestClient(app).get("/api/custom/exec-meeting-recruitment/digest-email")
        assert res.status_code == 401

    def test_wrong_bearer_is_not_the_cron(self, monkeypatch):
        from app.main import app

        monkeypatch.setattr(settings, "REPORTS_CRON_SECRET", "s3cr3t", raising=False)
        res = TestClient(app).get("/api/custom/exec-meeting-recruitment/digest-email",
                                  headers={"Authorization": "Bearer nope"})
        assert res.status_code in (401, 403)

    @pytest.mark.parametrize("exc,code", [
        (svc.DigestSourceError("/summary returned 500"), 502),
        (svc.DigestStaleError("Jobs portal last wrote 2026-09-01"), 503),
    ])
    def test_failures_are_non_2xx(self, monkeypatch, exc, code):
        from app.main import app

        monkeypatch.setattr(settings, "REPORTS_CRON_SECRET", "s3cr3t", raising=False)

        async def boom(app):
            raise exc

        monkeypatch.setattr(digest_router, "build_recruitment_digest", boom)
        res = TestClient(app).get("/api/custom/exec-meeting-recruitment/digest-email",
                                  headers={"Authorization": "Bearer s3cr3t"})
        assert res.status_code == code

    def test_render_is_pure(self):
        assert "render_html" in inspect.getsource(svc._build)
        assert callable(render_html)
