"""Weekly "Atrition WOW -Week N" e-mail — offline proof.

No DB, no network: the report endpoints are stubbed at ``_get_many`` with the
numbers of the REQUEST PDF (week Sep 28 – Oct 4 2026), so these tests pin the
e-mail to what the business asked for, not to whatever the code happens to say.

What can go wrong silently here, and which test pins it:

  * banker's rounding — Python ``round(-0.5)`` is ``-0``, so PCA CHESTWICK
    (avg 3.5, LW 3) would drop off the below-average list the PDF shows;
  * a ``diff < 0`` threshold — admits KOHLER IMPO at −0.25, a row that prints
    as "-0" and is absent from the PDF;
  * customers at ZERO last week belong to "inactive", not "below average"
    (the PDF omits BALL from the table though its diff is the worst);
  * the inactive / reactivated basis is WEEK-OVER-WEEK (decision 2026-10-05);
    an "any load in 8 weeks" basis lists long-tail customers the PDF does not;
  * a failed source endpoint must be a 502, never a partial e-mail;
  * the machine bearer must FAIL CLOSED.
"""
from __future__ import annotations

import inspect
import re
from datetime import date, datetime

import pytest
from fastapi.testclient import TestClient

from app.config import settings
from app.routers import attrition_wow_digest as digest_router
from app.routers import digest_auth
from app.services import attrition_wow_digest as svc
from app.services.attrition_wow_digest import (
    below_average,
    customer_rows,
    highlight,
    inactive,
    previous_week_loads,
    reactivated,
    round_half_away,
    subject_for,
    week_list,
)

LW = date(2026, 9, 28)
WEEKS = week_list(LW)  # latest first


# ---------------------------------------------------------------------------
# Fixtures — the PDF's numbers
# ---------------------------------------------------------------------------


def _pivot(team: str, customer: str, values: list) -> list[dict]:
    """Long-form /pivot rows; ``None`` = no row that week (as the API omits it)."""
    return [
        {"week_start": WEEKS[i].isoformat(), "dim_key": customer, "team": team,
         "value": float(v)}
        for i, v in enumerate(values) if v is not None
    ]


CORP_PIVOT = (
    _pivot("TEAM3", "INTERNATIONAL PAPER C/O CTSI SAN ANTONIO",
           [9, 11, 11, 11, 4, 14, 13, 29, 18])
    + _pivot("TEAM4", "OCV MEXICO S DE RL DE CV",
             [5, 6, None, 3, 10, 6, 7, 18, 19])
    + _pivot("TEAM2", "PCA CHESTWICK, PA", [3, 2, 2, 3, 2, 2, 4, 5, 8])
    + _pivot("TEAM2", "PCA ASHLAND, OH", [7, 11, 4, 5, 8, 13, 10, 5, 7])
    + _pivot("TEAM1", "KOHLER IMPO", [2, 2, 2, 3, 2, 2, 3, 2, 2])
    + _pivot("TEAM4", "BALL CORPORATION", [None, 21, 15, 13, 14, 12, 11, 10, 10])
    + _pivot("TEAM2", "PCA HARRISONBURG", [None, 1, 3, 2, 3, 3, 2, 3, 2])
    # A row that EXISTS last week with 0 billed loads (zero-charge rows only):
    # diff is −0.5 → prints "-1", yet it is inactive, not below average.
    + _pivot("TEAM2", "PCA VERNON", [0, 2, 1, 1])
    + _pivot("TEAM2", "PCA BEDFORD", [3, None, 1, 2, None, 1, 2, 1, 1])
    + _pivot("TEAM2", "WESTROCK", [1])
    # Long-tail: shipped in the baseline, but not the week before LW → neither
    # inactive nor reactivated under the week-over-week rule.
    + _pivot("TEAM3", "INTERNATIONAL PAPER MEXICO COMPANY",
             [None, None, 5, 6, 7, 6, 5, 5, 4])
)

DFW_PIVOT = (
    _pivot("TEAM-DFW", "RXO", [11, 16, 17, 13, 19, 18, 33, 39, 27])
    + _pivot("TEAM-DFW", "RUAN TRANSPORT CORPORATION",
             [90, 89, 88, 100, 112, 94, 79, 103, 111])
    + _pivot("TEAM-DFW", "AZTECA MILLING", [None, None, None, 1])
)


def _metric(l8w_sum: float, l2w_sum: float, lw: float) -> dict:
    l8w, l2w = l8w_sum / 8, l2w_sum / 2

    def d(c, b):
        return {"diff": c - b, "pct": (c - b) / b if b else None}

    return {"l8w_avg": l8w, "lw": lw, "l2w_avg": l2w,
            "diff_lw_vs_l8w": d(lw, l8w), "diff_l2w_vs_l8w": d(l2w, l8w)}


def _ratio_metric(num: dict, den: dict) -> dict:
    out = {}
    for k in ("l8w_avg", "lw", "l2w_avg"):
        out[k] = num[k] / den[k] if den[k] else None

    def d(c, b):
        return {"diff": c - b, "pct": (c - b) / b if b else None}

    out["diff_lw_vs_l8w"] = d(out["lw"], out["l8w_avg"])
    out["diff_l2w_vs_l8w"] = d(out["l2w_avg"], out["l8w_avg"])
    return out


def _summary(loads, rev, profit, lanes, customers) -> dict:
    l, r, p = _metric(*loads), _metric(*rev), _metric(*profit)
    return {
        "windows": {
            "l8w": {"start": "2026-08-03", "end": "2026-09-27"},
            "lw": {"start": "2026-09-28", "end": "2026-10-04"},
            "l2w": {"start": "2026-09-21", "end": "2026-10-04"},
        },
        "active_lanes": lanes,
        "active_customers": customers,
        "loads": l, "revenue": r, "profit": p,
        "margin_pct": _ratio_metric(p, r),
        "profit_per_load": _ratio_metric(p, l),
    }


UNILINK = _summary(
    (670.5 * 8, 678.5 * 2, 690),
    (1_628_564 * 8, 1_741_236 * 2, 1_740_780),
    (228_208 * 8, 241_519 * 2, 222_348),
    {"l8w": 293.75, "lw": 301, "diff": 7.25, "pct": -0.0247},
    {"l8w": 38.625, "lw": 39, "diff": 0.375, "pct": -0.0097},
)
CORP = _summary(
    (348.25 * 8, 352 * 2, 356),
    (669_904 * 8, 691_405 * 2, 707_659),
    (112_077 * 8, 109_361 * 2, 117_664),
    {"l8w": 104.5, "lw": 100, "diff": -4.5, "pct": 0.0431},
    {"l8w": 30.625, "lw": 31, "diff": 0.375, "pct": -0.0122},
)
DFW = _summary(
    (322.25 * 8, 326.5 * 2, 334),
    (958_660 * 8, 1_049_832 * 2, 1_033_121),
    (116_131 * 8, 132_158 * 2, 104_684),
    {"l8w": 190.375, "lw": 203, "diff": 12.625, "pct": -0.0663},
    {"l8w": 8.0, "lw": 8, "diff": 0.0, "pct": 0.0},
)


def _fake_get_many(calls_seen: list):
    async def fake(app, calls):
        calls_seen.append(calls)
        out = []
        for path, params in calls:
            teams = params.get("teams")
            if path == "/summary":
                data = {None: UNILINK, "TEAM-DFW": DFW}.get(teams, CORP)
                out.append({"success": True, "data": data})
            elif path == "/freshness":
                out.append({"success": True, "data": {"last_load_date": "2026-10-04"}})
            elif path == "/pivot":
                out.append({"success": True,
                            "data": DFW_PIVOT if teams == "TEAM-DFW" else CORP_PIVOT})
            else:
                raise AssertionError(path)
        return out
    return fake


@pytest.fixture
def digest(monkeypatch):
    seen: list = []
    monkeypatch.setattr(svc, "_get_many", _fake_get_many(seen))
    monkeypatch.setattr(svc, "cst_now", lambda: datetime(2026, 10, 5, 8, 15))
    import asyncio
    data = asyncio.run(svc.build_attrition_wow_digest(app=None))
    return data, seen


def _rows(pivot):
    return customer_rows(pivot, LW)


# ---------------------------------------------------------------------------
# Rounding and the customer-list arithmetic (port of PivotsTab.tsx)
# ---------------------------------------------------------------------------


class TestRounding:
    def test_half_rounds_away_from_zero_like_intl_number_format(self):
        assert round_half_away(-0.5) == -1
        assert round_half_away(0.5) == 1
        assert round_half_away(2.5) == 3
        assert round_half_away(-4.875) == -5
        assert round_half_away(0.02905, 4) == 0.0291


class TestCustomerRows:
    def test_ref_is_mean_of_the_eight_weeks_before_lw_with_gaps_as_zero(self):
        ocv = {r["customer"]: r for r in _rows(CORP_PIVOT)}["OCV MEXICO S DE RL DE CV"]
        assert ocv["ref"] == pytest.approx((6 + 0 + 3 + 10 + 6 + 7 + 18 + 19) / 8)
        assert ocv["values"][2] is None  # a missing week is shown as a dash

    def test_diff2w_is_lw_minus_the_single_week_before(self):
        sa = {r["customer"]: r for r in _rows(CORP_PIVOT)}[
            "INTERNATIONAL PAPER C/O CTSI SAN ANTONIO"]
        assert sa["diff"] == pytest.approx(9 - 111 / 8)
        assert sa["diff2w"] == -2

    def test_nine_weeks_are_shown_latest_first(self):
        assert len(_rows(CORP_PIVOT)[0]["values"]) == 9


class TestBelowAverage:
    def test_matches_the_pdf_rows_and_order(self):
        names = [r["customer"] for r in below_average(_rows(CORP_PIVOT))]
        assert names == [
            "INTERNATIONAL PAPER C/O CTSI SAN ANTONIO",
            "OCV MEXICO S DE RL DE CV",
            "PCA ASHLAND, OH",
            "PCA CHESTWICK, PA",
        ]

    def test_minus_half_is_listed_bankers_rounding_would_drop_it(self):
        assert "PCA CHESTWICK, PA" in [
            r["customer"] for r in below_average(_rows(CORP_PIVOT))]

    def test_a_row_that_prints_minus_zero_is_not_listed(self):
        assert "KOHLER IMPO" not in [
            r["customer"] for r in below_average(_rows(CORP_PIVOT))]

    def test_zero_loads_last_week_is_inactive_not_below_average(self):
        names = [r["customer"] for r in below_average(_rows(CORP_PIVOT))]
        assert "BALL CORPORATION" not in names
        assert "INTERNATIONAL PAPER MEXICO COMPANY" not in names
        assert "PCA VERNON" not in names  # explicit 0 row, not a missing week

    def test_dfw(self):
        assert [r["customer"] for r in below_average(_rows(DFW_PIVOT))] == [
            "RXO", "RUAN TRANSPORT CORPORATION"]


class TestInactiveReactivated:
    def test_inactive_is_week_over_week(self):
        assert inactive(_rows(CORP_PIVOT)) == [
            "BALL CORPORATION", "PCA HARRISONBURG", "PCA VERNON"]

    def test_reactivated_is_week_over_week(self):
        assert reactivated(_rows(CORP_PIVOT)) == ["PCA BEDFORD", "WESTROCK"]

    def test_long_tail_is_neither(self):
        rows = _rows(CORP_PIVOT)
        assert "INTERNATIONAL PAPER MEXICO COMPANY" not in inactive(rows)
        assert "INTERNATIONAL PAPER MEXICO COMPANY" not in reactivated(rows)

    def test_dfw_has_none(self):
        rows = _rows(DFW_PIVOT)
        assert inactive(rows) == [] and reactivated(rows) == []


# ---------------------------------------------------------------------------
# Highlights prose and subject
# ---------------------------------------------------------------------------


class TestHighlights:
    def test_previous_week_is_derived_from_l2w(self):
        assert previous_week_loads(UNILINK) == 667
        assert previous_week_loads(CORP) == 348
        assert previous_week_loads(DFW) == 319

    def test_unilink_reads_like_the_pdf(self):
        assert highlight(UNILINK) == (
            "Loads improved WoW, increasing from 667 to 690, 2.91% above the "
            "8-week average. Revenue finished 6.89% above the 8-week average, "
            "Profit was 2.57% below, Margin was down 1.24pp, and Profit per "
            "load was down 5.32% at $322."
        )

    def test_dfw_numbers(self):
        text = highlight(DFW)
        assert "from 319 to 334" in text
        assert "Revenue finished 7.77% above" in text
        assert "Profit was 9.86% below" in text
        assert "Margin was down 1.98pp" in text
        assert "down 13.03% at $313" in text

    def test_corp_profit_up(self):
        text = highlight(CORP)
        # The PDF prints 4.99% from the unrounded L8W profit; this fixture can
        # only carry the PDF's rounded $112,077, which lands on 4.98%.
        assert re.search(r"Profit was 4\.9[89]% above", text)
        assert "Profit per load was up 2.70% at $331" in text

    def test_a_decline_is_worded_as_one(self):
        s = _summary((700 * 8, 1300, 600), (8, 2, 1), (8, 2, 1),
                     UNILINK["active_lanes"], UNILINK["active_customers"])
        assert highlight(s).startswith("Loads declined WoW, decreasing from 700 to 600")


class TestSubject:
    def test_iso_week_of_last_week_with_the_requested_spelling(self):
        assert subject_for(LW) == "Atrition WOW -Week 40"


# ---------------------------------------------------------------------------
# End-to-end builder (stubbed endpoints)
# ---------------------------------------------------------------------------


class TestBuilder:
    def test_envelope(self, digest):
        data, _ = digest
        assert data["subject"] == "Atrition WOW -Week 40"
        assert data["meta"]["week_no"] == 40
        assert data["meta"]["data_as_of"] == "2026-10-04"
        assert "newest load departure in the data: 2026-10-04" in data["html"]
        assert data["meta"]["windows"]["lw"] == {"start": "2026-09-28", "end": "2026-10-04"}
        assert data["meta"]["below_average"] == {"CORP": 4, "DFW": 2}
        assert data["meta"]["inactive"] == {"CORP": 3, "DFW": 0}
        assert len(data["html"]) > 5000

    def test_scopes_are_the_pages_and_batches_fit_the_pool(self, digest):
        _, seen = digest
        summary_calls, second = seen
        pivot_calls = [c for c in second if c[0] == "/pivot"]
        assert [c[0] for c in second] == ["/pivot", "/pivot", "/freshness"]
        assert [p.get("teams") for _, p in summary_calls] == [
            None, "TEAM1,TEAM2,TEAM3,TEAM4,TEAM5", "TEAM-DFW"]
        assert all(p["dim"] == "customer" and p["metric"] == "loads"
                   and p["weeks"] == 12 for _, p in pivot_calls)
        assert max(len(b) for b in seen) <= 3

    def test_html_shows_the_pdf_numbers(self, digest):
        html = digest[0]["html"]
        for needle in ("670.5", "$1,628,564", "+$112,672", "+6.92%", "-1.24pp",
                       "$322", "293.8", "-2.47%", "+4.31%", "Sep 28 &ndash; Oct 4",
                       "Aug 3 &ndash; Sep 27", "BALL CORPORATION, PCA HARRISONBURG, PCA VERNON.", "PCA BEDFORD, WESTROCK."):
            assert needle in html, needle

    def test_an_empty_list_renders_an_explicit_line(self, digest):
        assert "<b style=\"font-family:" in digest[0]["html"]
        assert "DFW</b>: &ndash;" in digest[0]["html"]

    def test_mismatched_windows_refuse_to_render(self, monkeypatch):
        import asyncio
        import copy

        bad = copy.deepcopy(DFW)
        bad["windows"]["lw"] = {"start": "2026-10-05", "end": "2026-10-11"}

        async def fake(app, calls):
            return [{"success": True, "data": bad if p.get("teams") == "TEAM-DFW"
                     else UNILINK} for _, p in calls]

        monkeypatch.setattr(svc, "_get_many", fake)
        with pytest.raises(svc.DigestSourceError):
            asyncio.run(svc.build_attrition_wow_digest(app=None))


class TestOutlookSafety:
    def test_every_text_element_declares_its_font(self, digest):
        html = digest[0]["html"]
        for tag in re.findall(r"<(?:td|th|div|span|a|b)\b[^>]*>", html):
            assert "font-family" in tag, tag

    def test_no_rgb_no_scripts_no_webfonts(self, digest):
        html = digest[0]["html"]
        assert "rgb(" not in html
        assert "<script" not in html and "<link" not in html


# ---------------------------------------------------------------------------
# Auth + failure mode
# ---------------------------------------------------------------------------


class TestAuth:
    def test_an_unset_secret_rejects_every_bearer(self, monkeypatch):
        monkeypatch.setattr(settings, "REPORTS_CRON_SECRET", "", raising=False)
        for header in ("Bearer ", "Bearer anything", "", None):
            assert digest_auth.is_cron_bearer(header) is False

    def test_a_set_secret_admits_only_the_exact_token(self, monkeypatch):
        monkeypatch.setattr(settings, "REPORTS_CRON_SECRET", "s3cr3t", raising=False)
        assert digest_auth.is_cron_bearer("Bearer s3cr3t") is True
        assert digest_auth.is_cron_bearer("Bearer s3cr3t2") is False
        assert digest_auth.is_cron_bearer("Basic s3cr3t") is False

    def test_the_proxy_secret_is_not_accepted(self):
        src = inspect.getsource(digest_auth)
        assert "settings.PROXY_SHARED_SECRET" not in src

    def test_the_endpoint_gates_on_this_reports_key(self):
        assert digest_router.REPORT_KEY == "attrition-wow"
        src = inspect.getsource(digest_router.digest_email)
        assert "require_digest_access(REPORT_KEY)" in src

    def test_http_no_header_is_401(self, monkeypatch):
        from app.main import app

        monkeypatch.setattr(settings, "REPORTS_CRON_SECRET", "s3cr3t", raising=False)
        res = TestClient(app).get("/api/custom/attrition-wow/digest-email")
        assert res.status_code == 401

    def test_http_bearer_ok_and_source_failure_is_502(self, monkeypatch):
        from app.main import app

        monkeypatch.setattr(settings, "REPORTS_CRON_SECRET", "s3cr3t", raising=False)

        async def boom(app):
            raise svc.DigestSourceError("/summary returned 500")

        monkeypatch.setattr(digest_router, "build_attrition_wow_digest", boom)
        res = TestClient(app).get(
            "/api/custom/attrition-wow/digest-email",
            headers={"Authorization": "Bearer s3cr3t"},
        )
        assert res.status_code == 502

        async def ok(app):
            return {"subject": "s", "html": "h", "generatedAt": "g", "meta": {}}

        monkeypatch.setattr(digest_router, "build_attrition_wow_digest", ok)
        res = TestClient(app).get(
            "/api/custom/attrition-wow/digest-email",
            headers={"Authorization": "Bearer s3cr3t"},
        )
        assert res.status_code == 200
        assert res.json() == {"success": True, "data": {
            "subject": "s", "html": "h", "generatedAt": "g", "meta": {}}}


# ---------------------------------------------------------------------------
# Review fixes (2026-10-05)
# ---------------------------------------------------------------------------


class TestStaleFeedIsRefused:
    """A stalled v4 renders low loads, an inflated inactive list and a long
    below-average list — indistinguishable from real attrition."""

    @pytest.mark.parametrize("as_of", [None, "2026-10-01", "2026-10-02"])
    def test_stale_or_missing_raises(self, as_of):
        with pytest.raises(svc.DigestStaleError):
            svc.assert_fresh(as_of, date(2026, 10, 4))

    @pytest.mark.parametrize("as_of", ["2026-10-03", "2026-10-04", "2026-10-05"])
    def test_fresh_passes(self, as_of):
        svc.assert_fresh(as_of, date(2026, 10, 4))

    def test_builder_refuses_a_thursday_feed(self, monkeypatch):
        import asyncio

        fake = _fake_get_many([])

        async def thursday(app, calls):
            out = await fake(app, calls)
            return [{"success": True, "data": {"last_load_date": "2026-10-01"}}
                    if c[0] == "/freshness" else o for c, o in zip(calls, out)]

        monkeypatch.setattr(svc, "_get_many", thursday)
        with pytest.raises(svc.DigestStaleError):
            asyncio.run(svc.build_attrition_wow_digest(app=None))

    def test_http_stale_is_503(self, monkeypatch):
        from app.main import app

        monkeypatch.setattr(settings, "REPORTS_CRON_SECRET", "s3cr3t", raising=False)

        async def stale(app):
            raise svc.DigestStaleError("newest 2026-10-01")

        monkeypatch.setattr(digest_router, "build_attrition_wow_digest", stale)
        res = TestClient(app).get("/api/custom/attrition-wow/digest-email",
                                  headers={"Authorization": "Bearer s3cr3t"})
        assert res.status_code == 503


class TestEscapingAndSigns:
    def test_customer_names_are_escaped(self):
        from app.services.attrition_wow_digest_html import _customer_table

        rows = below_average(_rows(_pivot("TEAM1", 'A&B <X> "Y"', [1, 5, 5, 5, 5, 5, 5, 5, 5])))
        html = _customer_table(rows, WEEKS[:9])
        assert "A&amp;B &lt;X&gt; &quot;Y&quot;" in html
        assert "<X>" not in html

    def test_nothing_prints_minus_zero(self):
        from app.services.attrition_wow_digest_html import _num, _pct

        assert _num(-0.4) == "0"
        assert _pct(-0.00001) == "0.00%"

    def test_non_ascii_bearer_is_rejected_not_a_500(self, monkeypatch):
        monkeypatch.setattr(settings, "REPORTS_CRON_SECRET", "s3cr3t", raising=False)
        assert digest_auth.is_cron_bearer("Bearer s3cr3té") is False

    def test_negative_profit_baseline_is_stated_in_dollars(self):
        s = _summary((8, 2, 1), (8, 2, 1), (-800, 2, 50),
                     UNILINK["active_lanes"], UNILINK["active_customers"])
        text = highlight(s)
        assert "Profit was $50 against an 8-week average of -$100" in text
        assert "% below" not in text.split("Profit was")[1].split(",")[0]

    def test_a_tiny_margin_change_is_worded_flat(self):
        import copy

        s = copy.deepcopy(UNILINK)
        s["margin_pct"]["diff_lw_vs_l8w"]["diff"] = 0.000001
        assert "Margin was flat 0.00pp" in highlight(s)


class TestSurvivesOutlookPrint:
    """Test send 2026-10-05, printed from Outlook: every fill vanished and the
    white scope titles became unreadable; TEAM-DFW wrapped onto two lines."""

    def test_every_filled_element_asks_to_print_its_colour(self, digest):
        html = digest[0]["html"]
        for tag in re.findall(r"<[^>]*background-color:[^>]*>", html):
            assert "print-color-adjust:exact" in tag, tag[:120]

    def test_team_dfw_cannot_wrap(self, digest):
        html = digest[0]["html"]
        assert "TEAM&#8209;DFW" in html
        assert re.search(r"<td [^>]*nowrap>TEAM&#8209;DFW</td>", html)
