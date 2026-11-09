"""Funnel Augie Activities — voicemail % and "Loads — Missing information".

Requested 2026-10-29 (Katerine Meneses for Christian Mendoza, built 2026-11-09):
1. % voicemail per team (page + daily e-mail),
2. which loads miss which carrier/driver fields.

Same layering as `test_augie_funnel.py`: emitted-SQL linters over a stub pool,
unit contracts, then a live PREPARE + live invariants (skipped offline).
*mutation-checked* guards were broken on purpose and watched going red.
"""

from __future__ import annotations

import asyncio
import inspect
import os
import pathlib
import re
import types
from datetime import date

import pytest
from fastapi import HTTPException

from app.routers import augie_funnel as m
from app.routers import augie_funnel_missing as mi
from app.services import augie_funnel_digest_html as dh

from tests.test_augie_funnel import _StubPool, _filters, _funnel_sql, _model, _strip_comments

ROOT = pathlib.Path(__file__).resolve().parents[2]


def _drive_missing(f=None, **kwargs):
    kwargs.setdefault("field", None)  # bare call: the default is a Query object
    pool = _StubPool()
    orig = mi.get_datalake_gold_pool
    mi.get_datalake_gold_pool = lambda request: pool
    try:
        payload = asyncio.run(
            mi.missing_info(request=types.SimpleNamespace(), _user={},
                            f=f if f is not None else _filters(), **kwargs)
        )
    finally:
        mi.get_datalake_gold_pool = orig
    return pool, payload


def _missing_sql(**kwargs) -> str:
    return _strip_comments(_drive_missing(**kwargs)[0].sqls[0])


# ---------------------------------------------------------------------------
# voicemail
# ---------------------------------------------------------------------------


def test_a_call_is_a_completed_call_event_and_voicemail_is_its_call_status():
    """One `completed-call` = one finished call (Augment fires it for every call);
    `call-recording` fires only when there is a recording, so counting it would
    under-count line failures. Voicemail = `callStatus = 'VOICEMAIL'`, the bucket
    of the workbook's "Reached voicemail". *mutation-checked* (call-recording,
    outcome = REACHED_AUTOMATED_VOICEMAIL)."""
    sql = _funnel_sql()
    assert "count(*) FILTER (WHERE w.webhook_type = 'completed-call')      AS calls" in sql
    assert ("count(*) FILTER (WHERE (w.webhook_type = 'completed-call'"
            " AND w.payload -> 'data' ->> 'callStatus' = 'VOICEMAIL')) AS voicemail") in sql
    assert "REACHED_AUTOMATED_VOICEMAIL" not in sql
    assert "callId" not in sql, "callId is NULL before 2026-10-21 — count rows"


def test_voicemail_is_a_share_of_CALLS_not_of_loads():
    """The third denominator. *mutation-checked* (pickups, tracked)."""
    row = {"pickups": 100, "tracked": 50, "contacted": 40, "captured": 30, "has_status": 60,
           "canceled": 10, "international": 10, "multistop": 10, "not_covered": 10,
           "other": 10, "calls": 400, "voicemail": 160}
    p = m.funnel_payload(row)
    assert p["voicemail_pct"] == 40.0
    assert p["calls"] == 400 and p["voicemail"] == 160
    assert m.funnel_payload({**row, "calls": 0, "voicemail": 0})["voicemail_pct"] is None


def test_every_aggregate_sums_calls_over_the_same_population():
    """Summary, trend and by-team all read `_COUNTS_SQL` over `classified` — the
    voicemail figures must ride in it so they span the funnel's ONE population (§96)."""
    assert "COALESCE(sum(calls), 0)" in m._COUNTS_SQL
    assert "COALESCE(sum(voicemail), 0)" in m._COUNTS_SQL
    assert {"calls", "voicemail"} <= set(m._COUNT_KEYS)


def test_the_email_team_table_prints_voicemail_percent():
    html = dh.render_html(_model())
    assert ">Voicemail %<" in html
    assert "calls reached voicemail" in html
    # one more header than before, and every body row keeps the same width
    head = html[html.index("Unit / team"):]
    head = head[: head.index("</tr>")]
    assert head.count("<th") == 6


# ---------------------------------------------------------------------------
# missing information
# ---------------------------------------------------------------------------


def test_the_five_mcleod_fields_are_the_augie_apps_popup_columns():
    """The Augie app's `messagesFields`: override_payee_id, carrier_name,
    carrier_dispatcher_email, override_driver_nm, override_drvr_cell. Read from
    the COLUMNS, never by parsing `logs_null` (stale labels). *mutation-checked*."""
    sql = _funnel_sql()
    for col, alias in (
        ("override_payee_id", "carrier_id"),
        ("carrier_name", "carrier_name"),
        ("carrier_dispatcher_email", "dispatcher_email"),
        ("override_driver_nm", "driver_name"),
        ("override_drvr_cell", "driver_phone"),
    ):
        assert re.search(rf"BTRIM\(a\.{col}(::text)?\)\s+AS {alias}", sql), col
    assert "logs_null" not in _missing_sql()
    assert list(mi.MISSING_FIELDS) == [
        "carrier_id", "carrier_name", "dispatcher_email", "driver_name", "driver_phone",
        "trailer",
    ]


def test_blank_counts_as_missing_like_the_apps_validate_empty_fields():
    for key in ("carrier_id", "carrier_name", "dispatcher_email", "driver_name",
                "driver_phone"):
        assert mi.MISSING_FIELDS[key] == f"COALESCE({key}, '') = ''"


def test_trailer_comes_from_augment_and_is_judged_only_on_sent_loads():
    """Trailer is not in McLeod; only a `carrier-update.trailerNumber` carries it.
    On a load never sent to Augie it is n/a (user, 2026-11-09). *mutation-checked*."""
    sql = _funnel_sql()
    assert ("bool_or((w.webhook_type = 'carrier-update' AND COALESCE(BTRIM(w.payload -> "
            "'loadCarrierUpdate' ->> 'trailerNumber'), '') <> ''))") in sql
    assert mi.MISSING_FIELDS["trailer"] == "(tracked AND NOT has_trailer)"
    unsent = {"tracked": False, "m_trailer": False, "m_driver_name": True}
    assert mi.field_status(unsent, "trailer") == "n/a"
    assert mi.field_status(unsent, "driver_name") == "missing"
    sent = {"tracked": True, "m_trailer": True}
    assert mi.field_status(sent, "trailer") == "missing"
    assert mi.field_status({"tracked": True, "m_trailer": False}, "trailer") == "available"


def test_canceled_loads_are_left_out():
    sql = _missing_sql()
    assert "WHERE COALESCE(reason, '') <> 'canceled'" in sql


def test_counts_cover_the_whole_universe_not_the_capped_page():
    """`meta.counts` must come from `checked` (every load), never from the
    LIMITed page. *mutation-checked*."""
    sql = _missing_sql(field="driver_phone")
    agg = sql[sql.index("agg AS"): sql.index("picked AS")]
    assert "FROM checked" in agg and "LIMIT" not in agg
    picked = sql[sql.index("picked AS"):]
    assert f"LIMIT {m.MAX_ROWS}" in picked
    assert "WHERE COALESCE(driver_phone, '') = ''" in picked


def test_an_unknown_field_is_a_400_and_all_means_any_field():
    with pytest.raises(HTTPException):
        mi.missing_where("trailer; DROP TABLE x")
    anyw = mi.missing_where("all")
    assert anyw == mi.missing_where(None) == mi.missing_where("")
    for expr in mi.MISSING_FIELDS.values():
        assert expr in anyw


def test_the_endpoint_shares_the_funnels_filters_and_gate():
    params = inspect.signature(mi.missing_info).parameters
    assert params["f"].default.dependency is m._common
    deps = [d.call for d in mi.router.routes[0].dependant.dependencies]
    assert any(getattr(d, "__qualname__", "").startswith("require_report_access")
               for d in deps)
    assert mi.router.prefix == f"/custom/{m.REPORT_KEY}"
    src = (ROOT / "backend/app/main.py").read_text()
    assert "app.include_router(augie_funnel_missing.router" in src


def test_the_ai_assistant_section_is_decided():
    from app.services.ai_chat_tools import SECTION_ALLOWLIST

    assert "missing-info" in SECTION_ALLOWLIST


def test_the_field_keys_match_the_frontend():
    src = (ROOT / "frontend/lib/augie-funnel-api.ts").read_text()
    block = re.search(r"export type AugieMissingField =(.*?)\n\n", src, re.S)
    assert block, "could not find AugieMissingField in the api file"
    used = re.findall(r'"([a-z_]+)"', block.group(1))
    assert used == list(mi.MISSING_FIELDS)


def test_the_wire_never_carries_the_values():
    """Flags only — no phone numbers or e-mail addresses leave the backend
    (the AI assistant can read this section)."""
    _, payload = _drive_missing()
    assert payload["data"] == [] and payload["meta"]["checked"] == 0
    sql = _missing_sql()
    select = sql[sql.rindex("SELECT p.order_id"):]
    for col in ("driver_phone", "dispatcher_email", "driver_name"):
        assert f"p.{col}" not in select


# ---------------------------------------------------------------------------
# live
# ---------------------------------------------------------------------------

_GOLD = os.environ.get("SAVINGS_DATABASE_URL", "")
_skip_live = pytest.mark.skipif(not _GOLD, reason="SAVINGS_DATABASE_URL not set — offline run")


def _url() -> str:
    return re.sub(r"[?&]sslmode=\w+", "", _GOLD)


class _LivePool:
    def __init__(self, conn):
        self._conn = conn

    def acquire(self):
        conn = self._conn

        class _Ctx:
            async def __aenter__(self):
                return conn

            async def __aexit__(self, *exc):
                return False

        return _Ctx()


@_skip_live
def test_live_missing_info_parses_and_its_counts_reconcile():
    f = _filters(range="custom", start_date=date(2026, 11, 2), end_date=date(2026, 11, 8))

    async def run():
        import asyncpg

        conn = await asyncpg.connect(_url(), ssl="require")
        orig = mi.get_datalake_gold_pool
        mi.get_datalake_gold_pool = lambda request: _LivePool(conn)
        try:
            out = {}
            for field in ("all", *mi.MISSING_FIELDS):
                out[field] = await mi.missing_info(
                    request=None, field=field, f=f, _user={})
            cte, params = m._funnel_cte(f)
            summary = await conn.fetch(cte + f"SELECT {m._COUNTS_SQL} FROM classified",
                                       *params)
            return out, summary
        finally:
            mi.get_datalake_gold_pool = orig
            await conn.close()

    out, summary = asyncio.run(run())
    meta = out["all"]["meta"]
    assert 0 < meta["with_missing"] <= meta["checked"]
    assert meta["total"] == meta["with_missing"]
    for k in mi.MISSING_FIELDS:
        assert out[k]["meta"]["total"] == meta["counts"][k] <= meta["with_missing"]
        assert all(r["fields"][k] == "missing" for r in out[k]["data"])
    assert all(r["tracked"] for r in out["trailer"]["data"])
    s = m.funnel_payload(summary[0])
    assert 0 < s["voicemail"] <= s["calls"]
    assert 20 <= s["voicemail_pct"] <= 70, "voicemail rate far outside the workbook's ~40%"
