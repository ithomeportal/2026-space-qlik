"""§143 — the live McLeod status guard on the Cover boards.

2026-11-02, Jaime Anaya: orders 0351520 / 0351578 were picked up in McLeod on
11-01 yet still showed as "covered" in Space. Since the DST fall-back of
11-01 the gold McLeod ETL misses a large share of order changes (its stamps
run +1 h), so v4 kept ``status='A'`` while McLeod — and the n8n live feed
``app_augment_n8n_data_ra_rt`` — already said ``P``.

Pinned here:
  * an order the live feed reports as P/D/V leaves /cover, /pending-to-cover
    and /cover-forecast — including /cover's §44 totals, which must describe
    exactly the rows the board renders;
  * the live lookup is an UNCORRELATED parameter (§135), keyed on TRIMMED v4
    keys (v4 pads, the live table does not — an untrimmed join matches 0);
  * FAIL SOFT: an unreadable live table leaves the boards exactly as before
    and says so (``live_status = 'unavailable'``);
  * the guard trusts the live ``order_status`` only — never "has a pickup
    arrival" (McLeod itself keeps 'A' on some arrived loads).
"""

from __future__ import annotations

import asyncio
import inspect
import types

import pytest

from app.routers.ops_portal_overview import _live_status as ls
from app.routers.ops_portal_overview import chart, orders
from app.routers.ops_portal_overview._scope import CORP_SCOPE, DFW_SCOPE


class _Pool:
    """Answers the live-status SELECT; records every statement."""

    def __init__(self, live_keys=None, live_error: Exception | None = None, rows=None):
        self.live_keys = live_keys or []
        self.live_error = live_error
        self.rows = rows or []
        self.calls: list[tuple[str, tuple]] = []

    async def fetch(self, sql, *params):
        self.calls.append((sql, params))
        if ls.LIVE_TABLE in sql:
            if self.live_error:
                raise self.live_error
            return [{"k": k} for k in self.live_keys]
        return self.rows


def _call(fn, pool, scope=CORP_SCOPE, **overrides):
    request = types.SimpleNamespace(
        app=types.SimpleNamespace(state=types.SimpleNamespace(savings_pool=pool)),
        state=types.SimpleNamespace(opp_scope=scope),
    )
    kwargs = {}
    for name, p in inspect.signature(fn).parameters.items():
        if name == "request":
            kwargs[name] = request
        elif name in ("_user", "user"):
            kwargs[name] = {}
        else:
            kwargs[name] = getattr(p.default, "default", p.default)
    kwargs.update(overrides)
    return asyncio.run(fn(**kwargs))


def _report_sql(pool) -> tuple[str, tuple]:
    calls = [c for c in pool.calls if ls.LIVE_TABLE not in c[0]]
    assert len(calls) == 1, calls
    return calls[0]


# ---------------------------------------------------------------- the helper

def test_live_sql_trusts_order_status_only():
    sql = ls.LIVE_MOVED_SQL
    assert "order_status" in sql
    assert "origin_actual_arrival" not in sql, "an arrival is not a status change"
    assert set(ls.MOVED_STATUSES) == {"P", "D", "V"}
    assert "is_deleted" in sql
    # Driven from v4's status-'A' keys into the live PK — never a full scan of
    # the upsert-bloated live table (4-8 s measured 2026-11-02).
    assert "v.status = ANY($2)" in sql
    assert "r.company_id = a.co AND r.id = a.id" in sql
    # The LATEST live row per order decides; the status filter runs after it.
    assert "r.updated_dt DESC NULLS LAST, r.movement_id DESC" in sql
    assert sql.index("DISTINCT ON (r.company_id, r.id)") < sql.index("l.order_status = ANY($3)")
    assert "TRIM(r.company_id) || '|' || TRIM(r.id)" in sql


def test_predicate_trims_the_padded_v4_keys_and_is_uncorrelated():
    pred = ls.live_moved_pred("br4", "$9")
    assert "TRIM(br4.company_id)" in pred and "TRIM(br4.id)" in pred
    assert "= ANY($9)" in pred
    assert "SELECT" not in pred.upper(), "§135: no per-row lookup in a scoping predicate"


def test_fetch_returns_none_when_the_feed_is_unreadable():
    pool = _Pool(live_error=RuntimeError("permission denied for table"))
    assert asyncio.run(ls.fetch_live_moved_keys(pool)) is None
    assert ls.live_status_label(None) == "unavailable"
    assert ls.live_status_label([]) == "ok"


def test_fetch_returns_the_keys():
    pool = _Pool(live_keys=["TMS|0351520", "TMS|0351578"])
    assert asyncio.run(ls.fetch_live_moved_keys(pool)) == ["TMS|0351520", "TMS|0351578"]


# ---------------------------------------------------------------- the boards

@pytest.mark.parametrize("scope", [CORP_SCOPE, DFW_SCOPE], ids=["corp", "dfw"])
def test_cover_drops_live_moved_rows_before_the_limit_and_from_totals(scope):
    pool = _Pool(live_keys=["TMS|0351520"])
    _call(orders.cover, pool, scope)
    sql, params = _report_sql(pool)
    assert ["TMS|0351520"] in [p for p in params if isinstance(p, list)]
    assert "WHERE NOT q.live_moved OR (q.n_all = 0 AND q.rn = 1)" in sql
    # The outer filter runs before the LIMIT, the window totals inside it:
    assert sql.index("WHERE NOT q.live_moved") < sql.rindex("LIMIT")
    # §44 / §16: every money total and the covered count exclude live-moved rows.
    for alias in ("n_covered", "t_revenue", "t_carrier_cost", "t_profit"):
        line = next(l for l in sql.splitlines() if f"AS {alias}" in l)
        assert "AND NOT" in line, f"{alias} must exclude live-moved rows"
    assert "AS n_live_moved" in sql


def test_cover_meta_reports_the_live_count():
    row = {
        "order_id": "0351600", "team_id": "TEAM1", "customer_name": "X", "carrier": "C",
        "driver_name": "", "carrier_phone": "", "orig_sched_early": None,
        "orig_sched_late": None, "orig_sched_arrive_late": None, "lane": "A - B",
        "revenue": 100, "carrier_cost": 80, "profit": 20, "live_moved": False, "rn": 1,
        "n_all": 3, "n_covered": 1, "n_live_moved": 2,
        "t_revenue": 100, "t_carrier_cost": 80, "t_profit": 20,
    }
    pool = _Pool(live_keys=["TMS|0351520", "TMS|0351578"], rows=[row])
    res = _call(orders.cover, pool)
    assert res["meta"]["live_moved"] == 2
    assert res["meta"]["live_status"] == "ok"
    assert res["meta"]["covered"] == 1


def test_cover_fails_soft_when_the_feed_is_unreadable():
    pool = _Pool(live_error=RuntimeError("permission denied"))
    res = _call(orders.cover, pool)
    _, params = _report_sql(pool)
    assert [] in [p for p in params if isinstance(p, list)], "empty set ⇒ nothing excluded"
    assert res["meta"]["live_status"] == "unavailable"


def _pending_row(order_id, live, n_live=1, n_open=1):
    return {
        "order_id": order_id, "team_id": "TEAM1", "customer_name": "X", "lane": "A - B",
        "revenue": 100, "orig_sched_early": None, "orig_sched_late": None,
        "time_to_cover_hours": None, "live_moved": live, "n_live_moved": n_live,
        "n_open": n_open, "rn": 1,
    }


def test_pending_to_cover_flags_counts_and_drops_live_moved():
    pool = _Pool(live_keys=["TMS|0351520"], rows=[_pending_row("0351600", False, n_live=2)])
    res = _call(orders.pending_to_cover, pool)
    sql, params = _report_sql(pool)
    assert ["TMS|0351520"] in [p for p in params if isinstance(p, list)]
    assert "AS n_live_moved" in sql
    assert "WHERE NOT q.live_moved OR (q.n_open = 0 AND q.rn = 1)" in sql
    assert sql.index("WHERE NOT q.live_moved") < sql.rindex("LIMIT")
    assert res["meta"]["live_moved"] == 2
    assert res["meta"]["live_status"] == "ok"
    assert [r["order_id"] for r in res["data"]] == ["0351600"]


def test_pending_all_hidden_sentinel_carries_the_count_but_is_not_rendered():
    pool = _Pool(live_keys=["TMS|0351520"], rows=[_pending_row("0351520", True, n_live=1, n_open=0)])
    res = _call(orders.pending_to_cover, pool)
    assert res["data"] == []
    assert res["meta"]["live_moved"] == 1


def test_cover_all_hidden_sentinel_is_not_rendered():
    row = {
        "order_id": "0351520", "team_id": "TEAM4", "customer_name": "X", "carrier": "C",
        "driver_name": "", "carrier_phone": "", "orig_sched_early": None,
        "orig_sched_late": None, "orig_sched_arrive_late": None, "lane": "A - B",
        "revenue": 100, "carrier_cost": 80, "profit": 20, "live_moved": True, "rn": 1,
        "n_all": 0, "n_covered": 0, "n_live_moved": 1,
        "t_revenue": 0, "t_carrier_cost": 0, "t_profit": 0,
    }
    res = _call(orders.cover, _Pool(live_keys=["TMS|0351520"], rows=[row]))
    assert res["data"] == []
    assert res["meta"]["live_moved"] == 1 and res["meta"]["covered"] == 0


def test_cover_forecast_excludes_live_moved():
    pool = _Pool(live_keys=["TMS|0351520"])
    res = _call(chart.cover_forecast, pool)
    sql, params = _report_sql(pool)
    assert "NOT (TRIM(br4.company_id) || '|' || TRIM(br4.id)) = ANY(" in sql
    assert ["TMS|0351520"] in [p for p in params if isinstance(p, list)]
    assert res["meta"]["live_status"] == "ok"
