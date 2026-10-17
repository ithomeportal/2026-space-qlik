"""Funnel Augie Activities — the guards for report #66 (2026-10-17).

Four layers, cheapest first (the `test_production_spots_trends.py` layout):

1. **emitted-SQL linters** over a recording stub pool,
2. **unit contracts** on the window arithmetic, the rates and the digest,
3. a **live PREPARE** that proves every statement variant parses, and
4. **live executed invariants** — the funnel partition and the day/range
   additivity, which no text assertion can reach.

Layers 3 and 4 are skipped unless `SAVINGS_DATABASE_URL` is set, which is the
expected offline state.

⚠ The guards marked *mutation-checked* were broken on purpose, watched going
red, and restored. Do not "simplify" them.
"""

from __future__ import annotations

import asyncio
import inspect
import os
import pathlib
import re
import types
from datetime import date, timedelta

import pytest
from fastapi import HTTPException

from app.routers import augie_funnel as m
from app.routers import augie_funnel_digest as dr
from app.services import augie_funnel_digest as dg
from app.services import augie_funnel_digest_html as dh

ROOT = pathlib.Path(__file__).resolve().parents[2]


# ---------------------------------------------------------------------------
# harness
# ---------------------------------------------------------------------------


class _Conn:
    def __init__(self, pool):
        self._pool = pool

    async def fetch(self, sql, *params):
        self._pool.sqls.append(sql)
        self._pool.params.append(params)
        return []

    async def fetchrow(self, sql, *params):
        self._pool.sqls.append(sql)
        self._pool.params.append(params)
        return None


class _Acquire:
    def __init__(self, pool):
        self._pool = pool

    async def __aenter__(self):
        return _Conn(self._pool)

    async def __aexit__(self, *exc):
        return False


class _StubPool:
    """⚠ Records the SQL. A stub pool cannot see a WHERE — these tests assert
    on the statement TEXT, which is exactly why layers 3 and 4 exist."""

    def __init__(self):
        self.sqls: list[str] = []
        self.params: list[tuple] = []

    def acquire(self):
        return _Acquire(self)


def _filters(**overrides):
    """Build the shared filter dict the way FastAPI would — calling `_common()`
    bare hands back `Query` objects, so every argument is passed."""
    call = dict(
        range="last30", start_date=None, end_date=None, unit=None, team=None,
        customer=None, carrier=None, q=None,
    )
    call.update(overrides)
    return m._common(**call)


def _drive(endpoint: str, f=None, **kwargs):
    pool = _StubPool()
    orig = m.get_datalake_gold_pool
    m.get_datalake_gold_pool = lambda request: pool
    try:
        fn = getattr(m, endpoint)
        if "f" in inspect.signature(fn).parameters:
            kwargs["f"] = f if f is not None else _filters()
        payload = asyncio.run(fn(request=types.SimpleNamespace(), _user={}, **kwargs))
    finally:
        m.get_datalake_gold_pool = orig
    return pool, payload


def _strip_comments(sql: str) -> str:
    return re.sub(r"--[^\n]*", "", sql)


def _funnel_sql(**overrides) -> str:
    return _strip_comments(m._funnel_cte(_filters(**overrides))[0])


def _all_sql() -> list[str]:
    """Every statement variant the router can emit, for the live PREPARE."""
    out: list[str] = []
    variants = [
        _filters(),
        _filters(unit=["CORP"], team=["TEAM1"], customer=["A, B INC"],
                 carrier=["X"], q="tql"),
    ]
    for f in variants:
        for ep, kw in (("summary", {}), ("trend", {"grain": "day"}),
                       ("trend", {"grain": "week"}), ("by_team", {}),
                       ("loads", {"node": "all", "sort": "pickup_desc"}),
                       ("loads", {"node": "multistop", "sort": "stage_asc"})):
            out += _drive(ep, f=f, **kw)[0].sqls
    out += _drive("filters")[0].sqls
    out += _drive("freshness")[0].sqls
    return out


# ---------------------------------------------------------------------------
# layer 1 — emitted SQL
# ---------------------------------------------------------------------------


def test_pickup_is_the_augie_dashboards_column_with_a_half_open_naive_bound():
    """`original_origin_sched_early` is what the Augie app's Pickup filter reads
    (queries.ts DATE_COLUMN) — the column that made 163 reconcile with Bruno's
    mock. It is naive CST, so NO `AT TIME ZONE`, and the upper bound is
    exclusive `< end + 1 day` (a `<=` on a date drops the last day after 00:00).
    *mutation-checked* (origin_sche_arrive_early, `<=`)."""
    sql = _funnel_sql()
    assert "a.original_origin_sched_early >= $1" in sql
    assert "a.original_origin_sched_early <  $2" in sql
    assert "origin_sche_arrive_early" not in sql
    assert "AT TIME ZONE" not in sql
    f = _filters(range="custom", start_date=date(2026, 10, 16), end_date=date(2026, 10, 16))
    params = m._funnel_cte(f)[1]
    assert params[:2] == [date(2026, 10, 16), date(2026, 10, 17)]


def test_tracked_means_SENT_to_augment_not_has_an_augie_status():
    """🔴 The mock's 113 was `augie_status IS NOT NULL`; only 62 were ever sent.
    Tracked must come from a SEND row in app_load_tracking, and has_status must
    stay a separate, merely-informative count. *mutation-checked*."""
    sql = _funnel_sql()
    assert "FROM public.app_load_tracking t" in sql
    assert "t.change_source IN ('automatic', 'backfill', 'manual', 'pod-cron')" in sql
    assert "(s.order_id IS NOT NULL)                         AS tracked" in sql
    assert re.search(r"COALESCE\(l\.augie_status, ''\) <> ''\)\s+AS has_status", sql)
    # the status must never decide `tracked`
    tracked_expr = sql[sql.index("AS has_status") - 400: sql.index("AS has_status")]
    assert "augie_status" not in tracked_expr.split("AS captured")[0]


def test_info_captured_is_the_daily_activity_reports_rule_verbatim():
    """One metric, one definition: the n8n Augie Daily Activity ETL §A2 counts
    `calls_info_captured` from exactly these three shapes. A drift here makes
    the two reports disagree under the same label. *mutation-checked*."""
    w = m._INFO_WEBHOOK
    assert "w.payload -> 'loadCarrierUpdate' ->> 'source' = 'PHONE'" in w
    assert "w.payload -> 'trackingEvent' ->> 'eventSource' = 'PHONE_EMAIL'" in w
    assert "w.webhook_type = 'stop-update'" in w
    # a PHONE comment is what Augment posts when a call captured NOTHING
    assert "comment" not in w
    assert "'comment'" in m._CONTACT_WEBHOOK


def test_captured_and_contacted_are_subsets_of_tracked():
    """The mock's 84% is "of the tracked"; a captured load that was never sent
    would print a capture rate above 100%."""
    sql = _funnel_sql()
    assert "(s.order_id IS NOT NULL AND COALESCE(k.info, false)) AS captured" in sql
    assert re.search(r"\(s\.order_id IS NOT NULL\s+AND \(COALESCE\(k\.info", sql)


def test_the_reasons_are_one_case_in_the_agreed_priority_order():
    """One CASE ⇒ exactly one reason per untracked load ⇒ the branch sums to
    the untracked total. Order agreed 2026-10-17. *mutation-checked*."""
    sql = _funnel_sql()
    case = sql[sql.index("CASE\n                     WHEN s.order_id IS NOT NULL THEN NULL"):]
    case = case[: case.index("AS reason")]
    order = [case.index(f"'{r}'") for r in m.REASONS]
    assert order == sorted(order)
    assert "WHEN s.order_id IS NOT NULL THEN NULL" in case


def test_multistop_carries_both_engine_rules_per_end():
    """Rule 12 (extra stops, per end, `> 0`, NULL = 0) AND rule 10 (more than
    one live movement). Testing a SUM of the ends, or `> 1`, is the bug
    extra-stops.ts was created to stop."""
    sql = _funnel_sql()
    assert "COALESCE(a.extra_stops_at_pickup, 0)::int   AS extra_pu" in sql
    assert "COALESCE(a.extra_stops_at_delivery, 0)::int AS extra_del" in sql
    assert "l.extra_pu > 0 OR l.extra_del > 0" in sql
    assert "l.movements > 1" in sql
    assert "count(DISTINCT a.movement_id) AS movements" in sql


def test_international_treats_a_null_country_as_non_us():
    sql = _funnel_sql()
    assert "COALESCE(l.origin_country, '') <> 'US'" in sql
    assert "COALESCE(l.destination_country, '') <> 'US'" in sql


def test_deleted_rows_are_excluded_from_every_scan_of_the_feed():
    sql = _funnel_sql()
    scans = sql.count("FROM public.app_augment_n8n_data_ra_rt a")
    assert scans == 3
    assert sql.count("NOT COALESCE(a.is_deleted, false)") == scans


def test_the_unit_is_one_pickup_per_order_per_day():
    """The day/range additivity (layer 4 proves it executes): GROUP BY order
    AND pickup day, attributes from the latest movement."""
    sql = _funnel_sql()
    assert "a.original_origin_sched_early::date    AS pickup_day" in sql
    assert re.search(r"GROUP BY 1, 2\s+\),\s+mv AS", sql)
    assert "ORDER BY BTRIM(a.id::text), a.updated_dt DESC NULLS LAST," in sql


def test_team_and_unit_compare_trimmed_values():
    """`team_id` is stored padded ('TEAM1   '); a bare compare matches 0 rows."""
    sql = _funnel_sql(unit=["DFW"], team=["TM1"])
    assert "COALESCE(BTRIM(a.team_id::text), '')       AS team" in sql
    assert "l.unit = ANY($3::text[])" in sql
    assert "l.team = ANY($4::text[])" in sql


def test_repeated_params_are_never_comma_split():
    f = _filters(customer=["ACME, INC", "  "], carrier=["J.B. HUNT, LLC"])
    assert f["customers"] == ["ACME, INC"]
    assert f["carriers"] == ["J.B. HUNT, LLC"]


def test_search_escapes_like_wildcards_and_is_bound_not_interpolated():
    cte, params = m._funnel_cte(_filters(q="50%_off"))
    assert "50%_off" not in cte
    assert params[-1] == "%50\\%\\_off%"


def test_every_endpoint_takes_the_shared_common_dependency():
    """§55: FastAPI silently drops an undeclared param — a sibling endpoint
    without `_common` would ignore the page's filters and look right."""
    for name in ("summary", "trend", "by_team", "loads"):
        sig = inspect.signature(getattr(m, name))
        assert sig.parameters["f"].default.dependency is m._common, name


def test_an_unknown_sort_node_unit_or_range_is_a_400_not_a_fallback():
    with pytest.raises(HTTPException) as e:
        _drive("loads", node="all", sort="nope")
    assert e.value.status_code == 400
    with pytest.raises(HTTPException):
        _drive("loads", node="nope", sort="pickup_desc")
    with pytest.raises(HTTPException):
        _filters(unit=["MX"])
    with pytest.raises(HTTPException):
        _filters(range="ytd")


def test_every_node_maps_to_a_where():
    for node in m.NODES:
        assert m._node_where(node)


# ---------------------------------------------------------------------------
# layer 2 — unit contracts
# ---------------------------------------------------------------------------


def _freeze(monkeypatch, today: date):
    monkeypatch.setattr(m, "cst_today", lambda: today)


def test_presets_resolve_to_cst_windows(monkeypatch):
    t = date(2026, 10, 17)
    _freeze(monkeypatch, t)
    r = lambda name: m._resolve_range(name, None, None)  # noqa: E731
    assert r("today") == (t, t)
    assert r(None) == (t, t)
    assert r("last7") == (t - timedelta(days=6), t)
    assert r("last30") == (t - timedelta(days=29), t)
    assert r("last90") == (t - timedelta(days=89), t)
    assert r("upcoming") == (t + timedelta(days=1), t + timedelta(days=14))


def test_a_reversed_custom_range_is_swapped_and_a_half_one_is_400(monkeypatch):
    _freeze(monkeypatch, date(2026, 10, 17))
    assert m._resolve_range("custom", date(2026, 10, 9), date(2026, 10, 2)) == (
        date(2026, 10, 2), date(2026, 10, 9))
    with pytest.raises(HTTPException):
        m._resolve_range("custom", date(2026, 10, 9), None)


def test_the_window_is_clamped_to_the_data_floor(monkeypatch):
    _freeze(monkeypatch, date(2026, 10, 17))
    lo, _ = m._resolve_range("custom", date(2025, 1, 1), date(2026, 10, 1))
    assert lo == m.DATA_FLOOR


def test_two_denominators_pickups_and_tracked():
    """tracked % is of PICKUPS; contacted / captured % are of TRACKED — the
    mock's "84% (out of 113 from augie tracking)". *mutation-checked*."""
    row = {"pickups": 164, "tracked": 62, "contacted": 53, "captured": 45,
           "has_status": 118, "canceled": 14, "international": 45,
           "multistop": 24, "not_covered": 13, "other": 6}
    p = m.funnel_payload(row)
    assert p["tracked_pct"] == 37.8
    assert p["captured_pct"] == 72.6
    assert p["contacted_pct"] == 85.5
    assert p["not_tracked"] == 102 == sum(row[r] for r in m.REASONS)
    assert p["reason_pct"]["international"] == 27.4


def test_an_empty_window_has_no_rates_not_zero_percent():
    p = m.funnel_payload(None)
    assert p["pickups"] == 0
    assert p["tracked_pct"] is None and p["captured_pct"] is None


def test_the_trend_is_dense():
    f = _filters(range="custom", start_date=date(2026, 10, 1), end_date=date(2026, 10, 14))
    _, payload = _drive("trend", f=f, grain="day")
    assert [p["bucket"] for p in payload["data"]][0] == "2026-10-01"
    assert len(payload["data"]) == 14
    _, payload = _drive("trend", f=f, grain="week")
    assert payload["data"][0]["bucket"] == "2026-09-28"  # the Monday


def test_freshness_fails_soft_and_reads_stale_on_error():
    """A dead feed must not 500 the page — but it must not read FRESH either."""
    class _Boom:
        def acquire(self):
            raise RuntimeError("down")

    orig = m.get_datalake_gold_pool
    m.get_datalake_gold_pool = lambda request: _Boom()
    try:
        out = asyncio.run(m.freshness(request=types.SimpleNamespace(), _user={}))
    finally:
        m.get_datalake_gold_pool = orig
    assert out["success"] and out["data"]["is_stale"] is True


# --- digest ---------------------------------------------------------------


def test_digest_periods_compare_like_for_like():
    d = date(2026, 10, 16)  # a Friday
    p = dg.periods(d)
    assert p["day"] == (d, d)
    assert p["last_week_day"] == (date(2026, 10, 9),) * 2
    assert p["last7"] == (date(2026, 10, 10), d)
    assert p["prior7"] == (date(2026, 10, 3), date(2026, 10, 9))
    assert p["mtd"] == (date(2026, 10, 1), d)
    assert p["prev_mtd"] == (date(2026, 9, 1), date(2026, 9, 16))
    assert p["trend"] == (date(2026, 10, 3), d)


def test_month_to_date_survives_a_shorter_previous_month():
    assert dg.periods(date(2026, 3, 31))["prev_mtd"] == (date(2026, 2, 1), date(2026, 2, 28))


def test_rates_compare_in_points_never_percent_of_percent():
    cur = {"pickups": 110, "tracked": 46, "captured": 30, "tracked_pct": 41.8, "captured_pct": 65.2}
    base = {"pickups": 100, "tracked": 38, "captured": 25, "tracked_pct": 38.0, "captured_pct": 65.8}
    c = dg.compare(cur, base)
    assert c["tracked_pts"] == 3.8
    assert c["captured_pts"] == -0.6
    assert c["pickups_pct"] == 10.0
    assert dg.compare(cur, {**base, "pickups": 0})["pickups_pct"] is None
    assert dg.compare({**cur, "tracked_pct": None}, base)["tracked_pts"] is None


def test_a_stale_feed_refuses_the_email():
    with pytest.raises(dg.DigestStaleError):
        dg.assert_feed_fresh({"is_stale": True, "loads_updated": None})
    dg.assert_feed_fresh({"is_stale": False})


def test_subject_names_the_closed_day_and_both_rates():
    s = dg.subject_for(date(2026, 10, 16), {"pickups": 164, "tracked_pct": 37.8,
                                            "captured_pct": 72.6})
    assert s == "Augie Funnel - Fri Oct 16, 2026 - 164 pickups, 38% tracked, 73% info captured"
    assert "n/a" in dg.subject_for(date(2026, 10, 16),
                                   {"pickups": 0, "tracked_pct": None, "captured_pct": None})


def _model():
    row = {"pickups": 10, "tracked": 4, "contacted": 3, "captured": 2, "has_status": 7,
           "canceled": 1, "international": 2, "multistop": 1, "not_covered": 1, "other": 1}
    s = m.funnel_payload(row)
    d = date(2026, 10, 16)
    summ = {k: s for k in ("day", "prev_day", "last_week_day", "last7", "prior7", "mtd",
                           "prev_mtd")}
    cmp_ = dg.compare(s, s)
    return {
        "day": d, "periods": dg.periods(d), "summary": summ,
        "units": {"CORP": s, "DFW": s},
        "vs_prev_day": cmp_, "vs_last_week_day": cmp_, "vs_prior7": cmp_, "vs_prev_mtd": cmp_,
        "trend": [{"bucket": (d - timedelta(days=i)).isoformat(), **s} for i in range(14)],
        "teams": [{"unit": "CORP", "team": "TEAM1", **s}, {"unit": "DFW", "team": None, **s},
                  {"unit": None, "team": "BD1", **s}],
        "freshness": {"loads_updated": "2026-10-17T06:55:00"},
        "report_url": dg.REPORT_URL,
    }


def test_the_email_carries_every_section_the_n8n_assert_checks():
    html = dh.render_html(_model())
    for heading in ("FUNNEL EFFICIENCY", "NOT IN AUGIE", "PERIOD COMPARISON",
                    "14-DAY TREND", "BY TEAM"):
        assert heading in html
    assert dg.REPORT_URL in html
    assert "Oct 17, 06:55 CST" in html


def test_the_email_survives_outlook_print():
    """Outlook PRINT/PDF drops every background: bars are █ TEXT, and every
    element carries the font inline (§21). *mutation-checked* (bgcolor bar)."""
    html = dh.render_html(_model())
    assert dh.BLOCK in html
    assert "bgcolor" not in html
    for el in re.findall(r"<(?:td|th|div|table)\b[^>]*>", html):
        assert "font-family:" in el, el[:80]


def test_the_digest_router_takes_no_scope_parameter():
    """§100: the e-mail is company-wide; there is nothing a caller can widen."""
    params = set(inspect.signature(dr.digest_email).parameters)
    assert params == {"request", "_caller"}


def test_the_digest_reads_the_reports_own_endpoints():
    src = inspect.getsource(dg)
    assert 'API_PREFIX = "/api/custom/augie-funnel"' in src
    assert "httpx.ASGITransport" in src


# --- the mirrors ----------------------------------------------------------


def test_the_report_key_is_the_same_string_in_every_place():
    from app.services.seed import CUSTOM_REPORTS

    assert m.REPORT_KEY == "augie-funnel"
    assert m.router.prefix == f"/custom/{m.REPORT_KEY}"
    assert dr.router.prefix == m.router.prefix
    seeded = [r for r in CUSTOM_REPORTS if r["key"] == m.REPORT_KEY]
    assert len(seeded) == 1
    assert seeded[0]["title"] == "Funnel Augie Activities"


def test_every_endpoint_is_gated_on_the_report_key():
    for route in m.router.routes:
        deps = [d.call for d in route.dependant.dependencies]
        assert any(
            getattr(d, "__qualname__", "").startswith("require_report_access")
            for d in deps
        ), f"{route.path} is ungated"
    deps = [d.call for d in dr.router.routes[0].dependant.dependencies]
    assert any(getattr(d, "__qualname__", "").startswith("require_digest_access")
               for d in deps)


def test_both_routers_are_registered():
    src = (ROOT / "backend/app/main.py").read_text()
    assert "app.include_router(augie_funnel.router" in src
    assert "app.include_router(augie_funnel_digest.router" in src


def test_the_title_has_a_report_icon_entry():
    icons = (ROOT / "frontend/components/ReportIcons.tsx").read_text()
    assert '"Funnel Augie Activities":' in icons


def test_the_sort_whitelist_matches_the_frontend():
    src = (ROOT / "frontend/lib/augie-funnel-api.ts").read_text()
    block = re.search(r"export type AugieFunnelSort =(.*?)\n\n", src, re.S)
    assert block, "could not find AugieFunnelSort in the api file"
    used = set(re.findall(r'"([a-z_]+(?:_asc|_desc))"', block.group(1)))
    assert used, "parsed no sort tokens — the guard would pass vacuously"
    assert used == set(m._SORTS)


def test_the_frontend_route_folder_matches_the_report_key():
    page = ROOT / f"frontend/app/reports/{m.REPORT_KEY}/page.tsx"
    assert page.exists(), f"missing {page}"
    assert f'reportKey="{m.REPORT_KEY}"' in page.read_text()


def test_the_cockpit_catalog_carries_the_report():
    from app.routers.ceo_cockpit import LINK_TILES, TILES

    keys = {t["key"] for t in LINK_TILES} | {t["key"] for t in TILES}
    assert m.REPORT_KEY in keys


# ---------------------------------------------------------------------------
# layers 3 & 4 — live
# ---------------------------------------------------------------------------

_GOLD = os.environ.get("SAVINGS_DATABASE_URL", "")
_skip_live = pytest.mark.skipif(not _GOLD, reason="SAVINGS_DATABASE_URL not set — offline run")


def _url() -> str:
    return re.sub(r"[?&]sslmode=\w+", "", _GOLD)


@_skip_live
def test_live_every_statement_variant_parses():
    """§81: text is not validity. PREPARE every variant."""
    statements = list(dict.fromkeys(_all_sql()))
    assert len(statements) >= 8, "the harness went vacuous"

    async def run():
        import asyncpg

        conn = await asyncpg.connect(_url(), ssl="require")
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

    bad = asyncio.run(run())
    assert not bad, "statements rejected by Postgres:\n" + "\n".join(bad)


@_skip_live
def test_live_the_funnel_partitions_and_days_sum_to_the_range():
    """The identities no stub can prove: pickups = tracked + Σ reasons;
    captured ≤ contacted ≤ tracked; the daily trend sums to the range KPI;
    the unit split and the team table sum to the total."""

    async def run():
        import asyncpg

        pool = await asyncpg.create_pool(_url(), ssl="require", min_size=1, max_size=2)
        orig = m.get_datalake_gold_pool
        m.get_datalake_gold_pool = lambda request: pool
        req = types.SimpleNamespace()
        try:
            hi = m.cst_today() - timedelta(days=1)
            lo = hi - timedelta(days=13)
            f = _filters(range="custom", start_date=lo, end_date=hi)
            s = (await m.summary(req, f=f, _user={}))["data"]
            tr = (await m.trend(req, grain="day", f=f, _user={}))["data"]
            teams = (await m.by_team(req, f=f, _user={}))["data"]
            units = [
                (await m.summary(req, f=_filters(range="custom", start_date=lo,
                                                 end_date=hi, unit=[u]), _user={}))["data"]
                for u in m.UNITS
            ]
            return s, tr, teams, units
        finally:
            m.get_datalake_gold_pool = orig
            await pool.close()

    s, tr, teams, units = asyncio.run(run())
    assert s["pickups"] > 0, "empty window — the assertions would pass vacuously"
    assert s["pickups"] == s["tracked"] + sum(s[r] for r in m.REASONS)
    assert s["captured"] <= s["contacted"] <= s["tracked"]
    for k in ("pickups", "tracked", "captured", *m.REASONS):
        assert sum(p[k] for p in tr) == s[k], k
        assert sum(t[k] for t in teams) == s[k], k
    # units are CORP + DFW; a blank-unit row is the only allowed residue
    blank = sum(t["pickups"] for t in teams if t["unit"] not in m.UNITS)
    assert sum(u["pickups"] for u in units) + blank == s["pickups"]


def test_the_node_whitelist_matches_the_frontend():
    """A node the page sends but the router lacks is a 400 rendered as a broken
    table; one the router has but the page lacks is unreachable."""
    src = (ROOT / "frontend/lib/augie-funnel-api.ts").read_text()
    block = re.search(r"export type AugieFunnelNode =(.*?)\n\n", src, re.S)
    assert block, "could not find AugieFunnelNode in the api file"
    used = set(re.findall(r'"([a-z_]+)"', block.group(1)))
    assert "AugieFunnelReason" in block.group(1)
    assert used | set(m.REASONS) == set(m.NODES)


def test_the_email_lists_reasons_in_the_cases_priority_order():
    """The section says "in this priority order" — it must BE the CASE's order,
    or a canceled international load reads as the wrong reason."""
    assert tuple(k for k, _, _ in dh.REASON_LABELS) == m.REASONS


def test_the_email_team_table_prints_an_unassigned_unit_row():
    """CORP + DFW come from unit-filtered summaries; a blank-unit load is in
    neither, so the table must print it or stop summing to the total."""
    html = dh.render_html(_model())
    assert "Unassigned unit" in html


def test_a_range_entirely_before_the_data_floor_is_a_400(monkeypatch):
    _freeze(monkeypatch, date(2026, 10, 17))
    with pytest.raises(HTTPException):
        m._resolve_range("custom", date(2026, 2, 1), date(2026, 2, 20))
