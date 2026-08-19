"""DFW "repeat Out of Time" nightly digest — offline proof.

Runs entirely offline: it inspects the SQL the digest emits, drives the builder
through a stub pool, and exercises the auth gate directly. No DB, no network.

Why these are tests. This e-mail names individual employees and is read by
their managers, so every failure mode here is an accusation:

  * a `>` where `>=` belongs shifts the whole list by one person;
  * a day with no scheduled start (`expected IS NULL`) is UNSCOREABLE — folding
    it into the Out-of-Time count accuses someone the report holds no
    expectation for, and folding it into "on time" flatters everybody's rate.
    Neither shows up as an error;
  * the scope literal is what keeps this to Operations (DFW). Drift between it
    and the on-screen report would mail a list nobody can reproduce;
  * an empty result must be a readable ALL-CLEAR. n8n sends this
    unconditionally, so a clean fortnight and a broken query must not look
    alike — an empty body would be sent, silently, and read as good news;
  * the machine bearer must FAIL CLOSED. An unset REPORTS_CRON_SECRET that
    compared equal to an empty header would publish every DFW employee's
    attendance record to anyone who sent `Authorization: Bearer `.

Live cross-check (aivn_datalake_gold, window 2026-08-06..2026-08-19): 37 people
in DFW scope, 311 scored shifts, 7 people at >=4 Out of Time days — and FOUR
people at exactly 3, who must not appear. The boundary is not hypothetical.
"""

from __future__ import annotations

import inspect
import json
import re
from datetime import date, datetime

import pytest

from app.config import settings
from app.routers import dfw_access_doors_digest as digest_router
from app.routers import scoped_access_doors
from app.routers.hr_access_doors import (
    OUT_OF_TIME_DEFINITION,
    _NOT_ON_TIME_REF_PREDICATE,
    _ON_TIME_PREDICATE,
    _OUT_OF_TIME_PREDICATE,
)
from app.services import access_doors_delays_digest as svc
from app.services.access_doors_delays_digest import (
    DEFAULT_DAYS,
    DEFAULT_MIN_DAYS,
    MAX_ROWS,
    _build_sql,
    _shape_person,
    build_access_doors_delays_digest,
    resolve_window,
)
from app.services.access_doors_delays_digest_html import PAGE_WIDTH, _COLS

SQL = _build_sql()


def _squash(sql: str) -> str:
    return re.sub(r"\s+", " ", sql).strip()


FLAT = _squash(SQL)


# ---------------------------------------------------------------------------
# Stub pool
# ---------------------------------------------------------------------------


class _StubPool:
    """Records the SQL + params, returns a canned row."""

    def __init__(self, offenders: list[dict], **overrides):
        self.row = {
            "offenders": json.dumps(offenders),
            "scope_as_of": datetime(2026, 8, 19, 7, 12),
            "feed_as_of": datetime(2026, 8, 19, 9, 40),
            "people_in_scope": 37,
            "shifts_in_scope": 311,
            "out_of_time_shifts": 72,
            "on_time_shifts": 239,
            "unscored_shifts": 0,
            **overrides,
        }
        self.sql: str | None = None
        self.params: tuple = ()

    async def fetchrow(self, sql, *params):
        self.sql, self.params = sql, params
        return dict(self.row)


def _person(name: str, out_days: int, **kw) -> dict:
    """A `per_person` row shaped exactly as `json_agg` emits it."""
    base = {
        "full_name": name,
        "job_title": "Tracking and Tracing",
        "badged_days": max(out_days, 1),
        "out_of_time_days": out_days,
        "on_time_days": 0,
        "unscored_days": 0,
        "worst_check_minutes": -42,
        "avg_check_minutes": -20.0,
        "last_out_of_time_date": "2026-08-18",
    }
    base.update(kw)
    return base


# ---------------------------------------------------------------------------
# The ">3" threshold boundary
# ---------------------------------------------------------------------------


class TestThresholdBoundary:
    def test_the_default_floor_is_four_because_the_request_said_more_than_three(self):
        assert DEFAULT_MIN_DAYS == 4
        assert DEFAULT_DAYS == 14

    def test_the_filter_is_an_inclusive_floor_on_the_bound_parameter(self):
        assert "WHERE out_of_time_days >= $3" in FLAT

    @pytest.mark.parametrize(
        "out_days, expected",
        [(0, False), (2, False), (3, False), (4, True), (5, True), (9, True)],
    )
    def test_the_emitted_comparison_admits_four_and_rejects_three(
        self, out_days, expected
    ):
        """Reads the OPERATOR back out of the SQL and evaluates it.

        A plain substring assertion passes for `>` too, which would list the
        four people who sat at exactly 3 in the live window. This does not.
        """
        match = re.search(r"WHERE out_of_time_days\s*(>=|>|<=|<|=)\s*\$3", FLAT)
        assert match, "the offender filter changed shape — re-read this test"
        op = match.group(1)
        admitted = {
            ">=": out_days >= DEFAULT_MIN_DAYS,
            ">": out_days > DEFAULT_MIN_DAYS,
            "<=": out_days <= DEFAULT_MIN_DAYS,
            "<": out_days < DEFAULT_MIN_DAYS,
            "=": out_days == DEFAULT_MIN_DAYS,
        }[op]
        assert admitted is expected

    @pytest.mark.asyncio
    async def test_min_days_is_bound_as_a_parameter_not_inlined(self):
        pool = _StubPool([])
        await build_access_doors_delays_digest(pool, days=14, min_days=4)
        start, end, floor = pool.params
        assert floor == 4
        assert (end - start).days == 13, "14 inclusive days"
        assert isinstance(start, date) and isinstance(end, date)

    @pytest.mark.asyncio
    async def test_a_custom_floor_reaches_sql_unchanged(self):
        pool = _StubPool([])
        await build_access_doors_delays_digest(pool, days=30, min_days=7)
        start, end, floor = pool.params
        assert floor == 7
        assert (end - start).days == 29

    @pytest.mark.asyncio
    async def test_meta_states_the_rule_both_ways_round(self):
        """`min_days` is what SQL compares; `more_than` is how it was asked for.
        Printing only one of them is how an off-by-one survives review."""
        pool = _StubPool([])
        data = await build_access_doors_delays_digest(pool)
        assert data["meta"]["threshold"] == {
            "min_out_of_time_days": 4,
            "more_than": 3,
        }

    @pytest.mark.asyncio
    async def test_a_person_at_the_floor_is_rendered(self):
        pool = _StubPool([_person("Ivan Larrazolo", 4)])
        data = await build_access_doors_delays_digest(pool)
        assert data["meta"]["employees_over_threshold"] == 1
        assert "Ivan Larrazolo" in data["html"]
        assert "All clear" not in data["html"]


# ---------------------------------------------------------------------------
# `expected IS NULL` must be counted in NEITHER bucket
# ---------------------------------------------------------------------------


class TestUnscoredRowsAreExcluded:
    def test_every_out_of_time_count_carries_the_expected_guard(self):
        """Every `<= -1` in the emitted SQL must be the WHOLE named predicate.

        A bare `check_minutes <= -1` reads as a harmless simplification and
        behaves identically on the rows that HAVE a scheduled start — it only
        diverges the day someone COALESCEs the NULL, which is a change nobody
        would connect to this report.
        """
        occurrences = FLAT.count("<= -1")
        assert occurrences >= 4, "the Out-of-Time predicate vanished"
        assert FLAT.count(_squash(_OUT_OF_TIME_PREDICATE)) == occurrences

    def test_on_time_carries_the_same_guard(self):
        occurrences = FLAT.count(">= 0")
        assert occurrences >= 2, "the On-Time predicate vanished"
        assert FLAT.count(_squash(_ON_TIME_PREDICATE)) == occurrences

    def test_unscored_days_are_counted_separately_not_folded_into_on_time(self):
        assert _NOT_ON_TIME_REF_PREDICATE == "expected IS NULL"
        assert f"COUNT(*) FILTER (WHERE {_NOT_ON_TIME_REF_PREDICATE}) AS unscored_days" in FLAT

    def test_the_three_buckets_are_mutually_exclusive_and_named(self):
        for pred in (_ON_TIME_PREDICATE, _OUT_OF_TIME_PREDICATE):
            assert "expected IS NOT NULL" in _squash(pred)
        assert "<= -1" in _squash(_OUT_OF_TIME_PREDICATE)
        assert ">= 0" in _squash(_ON_TIME_PREDICATE)

    def test_worst_and_average_lateness_ignore_the_unscored_and_the_punctual(self):
        """An AVG over every day would report a punctual average for someone
        late half the week."""
        for agg in ("MIN(", "AVG("):
            idx = FLAT.index(agg + " TRUNC(EXTRACT(EPOCH")
            tail = FLAT[idx: idx + 260]
            assert "FILTER (WHERE (expected IS NOT NULL" in tail
            assert "<= -1" in tail

    def test_the_rate_denominator_drops_the_unscored_days(self):
        """10 badged days, 4 of them unscoreable, 4 Out of Time is 4/6, not
        4/10. Leaving the unscored days in the denominator quietly shrinks
        everybody's rate."""
        shaped = _shape_person(
            _person("X", 4, badged_days=10, unscored_days=4, on_time_days=2)
        )
        assert shaped["scored_days"] == 6
        assert shaped["out_of_time_pct"] == pytest.approx(4 / 6 * 100.0)
        assert shaped["badged_days"] == 10

    def test_a_person_with_no_scored_days_reports_a_dash_not_zero_percent(self):
        shaped = _shape_person(
            _person("X", 0, badged_days=3, unscored_days=3, on_time_days=0)
        )
        assert shaped["out_of_time_pct"] is None

    def test_lateness_is_flipped_to_positive_exactly_once(self):
        shaped = _shape_person(
            _person("X", 4, worst_check_minutes=-96, avg_check_minutes=-41.5)
        )
        assert shaped["worst_minutes_late"] == 96
        assert shaped["avg_minutes_late"] == 41.5


# ---------------------------------------------------------------------------
# Single-sourcing: the definition is imported, never re-typed
# ---------------------------------------------------------------------------


class TestOutOfTimeIsDefinedOnce:
    def test_the_digest_module_never_retypes_the_predicate(self):
        """A second copy of "Out of Time" is exactly how the portal and the n8n
        workflow drifted apart over the expected-arrival rules."""
        builder = inspect.getsource(svc._build_sql)
        assert "<= -1" not in builder, "the predicate was re-typed into the SQL"
        assert ">= 0" not in builder
        assert "expected IS NULL" not in builder
        assert "_OUT_OF_TIME_PREDICATE" in builder
        assert "_ON_TIME_PREDICATE" in builder
        assert "_NOT_ON_TIME_REF_PREDICATE" in builder

    def test_the_cte_chain_is_imported_from_the_report(self):
        src = inspect.getsource(svc)
        assert "from app.routers.hr_access_doors import" in src
        for name in ("_first_punch_cte", "_scored_cte", "_OUT_OF_TIME_PREDICATE"):
            assert name in src
        # Nothing may reconstruct the punch → arrival chain locally.
        assert "ROW_NUMBER() OVER" not in src

    def test_the_scoring_chain_is_the_reports_own(self):
        assert "PARTITION BY r.shift_date, r.ident" in FLAT
        assert "late_arrival_schedule" in FLAT
        assert "WHERE rn = 1" in FLAT
        assert "$1::date - 1" in FLAT and "$2::date + 1" in FLAT

    def test_the_plain_language_definition_lives_beside_the_sql(self):
        """A footnote that drifts from the SQL is worse than no footnote."""
        d = OUT_OF_TIME_DEFINITION.lower()
        assert "one minute" in d
        assert "no grace period" in d
        assert "not scored" in d


# ---------------------------------------------------------------------------
# DFW scope
# ---------------------------------------------------------------------------


class TestDfwScoping:
    def test_the_gate_is_the_literal_the_report_is_locked_to(self):
        assert scoped_access_doors.DFW_GATE_SQL == "AND dep = 'Operations (DFW)'"
        assert scoped_access_doors.DFW_SCOPE_LABEL == "Operations (DFW)"

    def test_the_on_screen_report_is_built_from_the_same_constant(self):
        """If someone re-inlines the literal into `build_scoped_access_doors_
        router`, the digest and the report can drift apart silently."""
        src = inspect.getsource(scoped_access_doors)
        block = src[src.index("dfw_router = build_scoped_access_doors_router"):]
        block = block[: block.index(")")]
        assert "gate_sql=DFW_GATE_SQL" in block
        assert "'Operations (DFW)'" not in block

    def test_the_digest_sql_applies_that_gate_once(self):
        assert FLAT.count(scoped_access_doors.DFW_GATE_SQL) == 1
        assert "WHERE 1=1 AND dep = 'Operations (DFW)'" in FLAT

    def test_no_other_scope_leaks_in(self):
        for other in ("dep = 'Admin'", "dep = 'Pricing'", "dep = 'Operations'"):
            assert other not in FLAT

    def test_every_aggregate_reads_the_gated_cte(self):
        """The totals in the footer must describe the SAME population as the
        table. A scalar reading `scored` instead of `scope` would print
        company-wide numbers under a DFW headline."""
        for frag in (
            "FROM scope GROUP BY nm",
            "(SELECT MAX(event_time) FROM scope)",
            "(SELECT COUNT(DISTINCT nm) FROM scope)",
            "(SELECT COUNT(*) FROM scope)",
        ):
            assert frag in FLAT
        # `scored` is referenced exactly once — by `scope` itself.
        assert FLAT.count("FROM scored") == 1

    @pytest.mark.asyncio
    async def test_the_scope_is_reported_in_meta_and_in_the_body(self):
        pool = _StubPool([_person("Ada", 5)])
        data = await build_access_doors_delays_digest(pool)
        assert data["meta"]["scope"] == "Operations (DFW)"
        assert data["meta"]["gate_sql"] == scoped_access_doors.DFW_GATE_SQL
        assert "Operations (DFW)" in data["html"]


# ---------------------------------------------------------------------------
# The all-clear case
# ---------------------------------------------------------------------------


class TestAllClear:
    @pytest.mark.asyncio
    async def test_nobody_over_the_threshold_still_renders_a_full_document(self):
        pool = _StubPool([])
        data = await build_access_doors_delays_digest(pool)
        html = data["html"]
        assert html.startswith("<!DOCTYPE html>")
        assert html.rstrip().endswith("</html>")
        assert len(html) > 1000
        assert "All clear" in html
        assert "more than 3 Out of Time days" in html

    @pytest.mark.asyncio
    async def test_the_subject_says_all_clear_rather_than_looking_broken(self):
        pool = _StubPool([])
        data = await build_access_doors_delays_digest(pool)
        assert "all clear" in data["subject"].lower()
        assert data["meta"]["employees_over_threshold"] == 0
        assert data["meta"]["employees"] == []

    @pytest.mark.asyncio
    async def test_the_all_clear_still_carries_the_scope_counters(self):
        """An all-clear with nobody badging in is a DEAD FEED, not good news.
        The counters are the only thing that tells those apart."""
        pool = _StubPool([])
        html = (await build_access_doors_delays_digest(pool))["html"]
        assert "37 employee(s) badged in" in html
        assert "311 shift(s)" in html

    @pytest.mark.asyncio
    async def test_an_empty_row_from_the_pool_does_not_raise(self):
        """A pool that returns nothing at all must still produce a sendable
        e-mail — the workflow has no branch for an exception."""

        class _NullPool:
            async def fetchrow(self, sql, *params):
                return None

        data = await build_access_doors_delays_digest(_NullPool())
        assert data["html"].startswith("<!DOCTYPE html>")
        assert "All clear" in data["html"]
        assert data["meta"]["totals"]["people_in_scope"] == 0

    @pytest.mark.asyncio
    async def test_the_definition_is_in_the_footer_of_both_states(self):
        for offenders in ([], [_person("Ada", 6)]):
            html = (await build_access_doors_delays_digest(_StubPool(offenders)))["html"]
            assert "one minute or more" in html
            assert "no grace period" in html.lower()


# ---------------------------------------------------------------------------
# Auth — machine bearer, fail closed
# ---------------------------------------------------------------------------


class TestBearerAuthFailsClosed:
    def test_an_unset_secret_rejects_every_bearer(self, monkeypatch):
        """The bug this pins: `if token == settings.REPORTS_CRON_SECRET` with
        both empty is TRUE, which would publish 37 people's attendance records
        to `Authorization: Bearer `."""
        monkeypatch.setattr(settings, "REPORTS_CRON_SECRET", "", raising=False)
        for header in ("Bearer ", "Bearer  ", "Bearer anything", "Bearer null", None):
            assert digest_router._is_cron_bearer(header) is False

    def test_an_unset_secret_is_not_bypassed_by_an_empty_string_header(
        self, monkeypatch
    ):
        monkeypatch.setattr(settings, "REPORTS_CRON_SECRET", "", raising=False)
        assert digest_router._is_cron_bearer("") is False

    def test_a_set_secret_admits_only_the_exact_token(self, monkeypatch):
        monkeypatch.setattr(settings, "REPORTS_CRON_SECRET", "s3cr3t", raising=False)
        assert digest_router._is_cron_bearer("Bearer s3cr3t") is True
        assert digest_router._is_cron_bearer("bearer s3cr3t") is True
        assert digest_router._is_cron_bearer("Bearer  s3cr3t ") is True
        assert digest_router._is_cron_bearer("Bearer s3cr3") is False
        assert digest_router._is_cron_bearer("Bearer s3cr3t2") is False
        assert digest_router._is_cron_bearer("Basic s3cr3t") is False
        assert digest_router._is_cron_bearer("s3cr3t") is False

    def test_the_proxy_secret_is_not_accepted(self, monkeypatch):
        """PROXY_SHARED_SECRET means "the identity in this header is
        trustworthy". Handing it to a third-party scheduler would let that
        scheduler self-assert roles:["admin"] on every endpoint in the app."""
        monkeypatch.setattr(settings, "REPORTS_CRON_SECRET", "", raising=False)
        monkeypatch.setattr(settings, "PROXY_SHARED_SECRET", "proxy-abc", raising=False)
        assert digest_router._is_cron_bearer("Bearer proxy-abc") is False
        src = inspect.getsource(digest_router)
        assert "PROXY_SHARED_SECRET" not in src.split('"""', 2)[2]

    @pytest.mark.asyncio
    async def test_no_authorization_header_is_401_not_a_free_pass(self, monkeypatch):
        from fastapi import HTTPException

        monkeypatch.setattr(settings, "REPORTS_CRON_SECRET", "", raising=False)
        check = digest_router._require_digest_access()
        with pytest.raises(HTTPException) as exc:
            await check(request=None, authorization=None, x_proxy_secret=None)
        assert exc.value.status_code == 401

    @pytest.mark.asyncio
    async def test_a_valid_bearer_returns_a_roleless_machine_identity(
        self, monkeypatch
    ):
        """It is not a portal user and must never be mistaken for one — an
        identity carrying roles would sail through any downstream role check."""
        monkeypatch.setattr(settings, "REPORTS_CRON_SECRET", "s3cr3t", raising=False)
        check = digest_router._require_digest_access()
        caller = await check(
            request=None, authorization="Bearer s3cr3t", x_proxy_secret=None
        )
        assert caller["roles"] == []
        assert caller["machine"] is True

    def test_the_human_fallback_gates_on_this_reports_own_key(self):
        assert digest_router.REPORT_KEY == "dfw-access-doors"
        src = inspect.getsource(digest_router._require_digest_access)
        assert "require_report_access(REPORT_KEY)" in src
        assert "await require_user(" in src


# ---------------------------------------------------------------------------
# Freshness, window, and the e-mail's Outlook safety
# ---------------------------------------------------------------------------


class TestFreshnessStamp:
    @pytest.mark.asyncio
    async def test_both_stamps_are_rendered(self):
        """They fail differently: `scope` stops advancing when DFW stops being
        scored, `feed` when the ZKTeco extraction itself dies."""
        html = (await build_access_doors_delays_digest(_StubPool([])))["html"]
        assert "Data as of Aug 19, 2026" in html
        assert "7:12 AM CST" in html
        assert "9:40 AM CST" in html

    @pytest.mark.asyncio
    async def test_the_stamps_are_in_meta_for_the_workflow_to_alarm_on(self):
        data = await build_access_doors_delays_digest(_StubPool([]))
        assert data["meta"]["data_as_of"] == {
            "scope_latest_badge_in": "2026-08-19T07:12:00",
            "feed_latest_punch": "2026-08-19T09:40:00",
        }

    @pytest.mark.asyncio
    async def test_a_missing_stamp_renders_a_dash_not_an_epoch(self):
        pool = _StubPool([], scope_as_of=None, feed_as_of=None)
        html = (await build_access_doors_delays_digest(pool))["html"]
        assert "1970" not in html
        assert "Data as of &mdash;" in html

    def test_the_window_ends_today_and_is_inclusive(self):
        from app.clock import cst_today

        start, end = resolve_window(14)
        assert end == cst_today()
        assert (end - start).days == 13


class TestOutlookSafety:
    @pytest.mark.asyncio
    async def test_the_page_fits_inside_the_outlook_content_box(self):
        """Outlook desktop (Word engine) ignores overflow-x and CLIPS the
        rightmost columns of an over-wide table instead of scrolling."""
        assert PAGE_WIDTH <= 956
        assert sum(w for _, _, w in _COLS) < PAGE_WIDTH

    @pytest.mark.asyncio
    async def test_no_rgb_and_no_flexbox_and_no_webfont(self):
        html = (await build_access_doors_delays_digest(_StubPool([_person("A", 4)])))["html"]
        assert "rgb(" not in html
        assert "display:flex" not in html
        assert "<link" not in html
        assert "@media" not in html

    @pytest.mark.asyncio
    async def test_every_cell_declares_the_font_stack(self):
        """Outlook resets font-family at every nested <table> boundary."""
        html = (await build_access_doors_delays_digest(_StubPool([_person("A", 4)])))["html"]
        cells = re.findall(r"<t[dh](?=[\s>])[^>]*>", html)
        assert cells
        missing = [c for c in cells if "font-family" not in c]
        assert not missing, missing[:3]

    @pytest.mark.asyncio
    async def test_the_table_is_laid_out_with_tables_not_divs(self):
        html = (await build_access_doors_delays_digest(_StubPool([_person("A", 4)])))["html"]
        assert 'cellpadding="0" cellspacing="0" border="0"' in html
        assert html.count("<table") == html.count("</table>")

    @pytest.mark.asyncio
    async def test_html_entities_in_headings_are_not_double_escaped(self):
        """`escape()` cannot tell an entity from a user string that looks like
        one, so a heading built with `&middot;` came out reading `&MIDDOT;`."""
        html = (await build_access_doors_delays_digest(_StubPool([])))["html"]
        assert "&amp;middot;" not in html
        assert "&amp;mdash;" not in html
        assert "Last 14 days &middot; more than 3 Out of Time days" in html

    @pytest.mark.asyncio
    async def test_a_name_with_html_in_it_is_escaped(self):
        pool = _StubPool([_person("<script>alert(1)</script>", 4)])
        html = (await build_access_doors_delays_digest(pool))["html"]
        assert "<script>" not in html
        assert "&lt;script&gt;" in html

    @pytest.mark.asyncio
    async def test_rows_are_capped_and_the_truncation_is_stated(self):
        pool = _StubPool([_person(f"P{i:03d}", 9) for i in range(MAX_ROWS + 5)])
        data = await build_access_doors_delays_digest(pool)
        assert data["meta"]["rows_truncated"] == 5
        assert data["meta"]["employees_over_threshold"] == MAX_ROWS
        assert "further employee(s) also exceeded" in data["html"]


# ---------------------------------------------------------------------------
# Response envelope + ordering
# ---------------------------------------------------------------------------


class TestEnvelopeAndOrdering:
    @pytest.mark.asyncio
    async def test_the_payload_has_the_same_four_keys_as_the_team_digest(self):
        data = await build_access_doors_delays_digest(_StubPool([]))
        assert set(data) == {"subject", "html", "generatedAt", "meta"}
        assert isinstance(data["subject"], str) and data["subject"]
        assert isinstance(data["generatedAt"], str)

    def test_sql_orders_by_out_of_time_days_then_name(self):
        assert "ORDER BY out_of_time_days DESC, full_name ASC" in FLAT
        assert (
            "json_agg(t ORDER BY t.out_of_time_days DESC, t.full_name ASC)" in FLAT
        )

    @pytest.mark.asyncio
    async def test_the_rendered_order_follows_the_payload_order(self):
        pool = _StubPool(
            [_person("Zoe", 8), _person("Ada", 8), _person("Bob", 4)]
        )
        html = (await build_access_doors_delays_digest(pool))["html"]
        assert html.index("Zoe") < html.index("Ada") < html.index("Bob")

    @pytest.mark.asyncio
    async def test_one_row_per_person_even_across_a_job_title_change(self):
        """Grouping by (name, title) would split a mid-window title change into
        two sub-threshold rows and drop the person from the e-mail entirely."""
        assert "GROUP BY nm" in FLAT
        assert "GROUP BY nm, jt" not in FLAT
        assert "MAX(jt)" in FLAT
