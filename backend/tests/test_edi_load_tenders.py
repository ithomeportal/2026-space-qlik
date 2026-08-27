"""EDI Load Tenders — the traps this report was built around.

Source table ``mcleod_gld_edi_load_tender`` (Omar Orozco, 2026-08-26). Five
defects were live in the data on day one, and each one fails silently rather
than raising, so each gets a test that would have caught it:

  1. ``order_id`` is 7 chars, ``v4.id`` is a padded 8. A bare equality join
     matched **0 of 47,928** rows and a LEFT JOIN would have rendered all-NULL
     enrichment forever. Pinned by ``test_join_uses_rpad`` (offline) and
     ``test_live_join_matches_every_order`` (live).
  2. ``order_id`` is EMPTY STRING, never NULL — so ``IS NULL`` reads 0 and the
     "never created" KPI silently vanishes. ``test_never_created_uses_empty_string``.
  3. ``shipment_id`` is not unique, so row-grain counting inflates volume ~77%.
     ``test_headline_counts_are_shipment_grain``.
  4. ``status_desc`` / ``intercompany`` are ~100% constant and must never be
     used as an acceptance signal. ``test_no_acceptance_from_status_desc``.
  5. The vendor's stated invariant is violated by 46.6% of the rows it covers.
     ``test_live_invariant_violation_is_reported_not_assumed`` asserts the gap
     still exists, so the day the ETL is fixed this test fails and tells us to
     retire the exception board rather than leave a dead panel up.

The live half is skipped unless ``SAVINGS_DATABASE_URL`` is set, so the suite
stays offline by default.
"""

from __future__ import annotations

import ast
import asyncio
import inspect
import os
import re
import textwrap

import pytest

from app.routers import edi_load_tenders as edi


# --------------------------------------------------------------------------
# offline — the shape contracts
# --------------------------------------------------------------------------


def _code(obj=edi) -> str:
    """Source with every docstring stripped.

    ⚠ These assertions must read the CODE, not the prose. The module docstring
    documents each trap by quoting the wrong form of it verbatim
    (``order_id IS NULL``, ``br4.id = t.order_id``, ``width=32``), so a naive
    substring scan over ``inspect.getsource`` fails on the very documentation
    that exists to prevent the bug.
    """
    tree = ast.parse(textwrap.dedent(inspect.getsource(obj)))
    for node in ast.walk(tree):
        body = getattr(node, "body", None)
        if not isinstance(body, list) or not body:
            continue
        if not isinstance(node, (ast.Module, ast.FunctionDef,
                                 ast.AsyncFunctionDef, ast.ClassDef)):
            continue
        first = body[0]
        if (
            isinstance(first, ast.Expr)
            and isinstance(first.value, ast.Constant)
            and isinstance(first.value.value, str)
        ):
            body.pop(0)
            if not body:
                body.append(ast.Pass())
    return ast.unparse(tree)


def test_join_uses_rpad():
    """Every join to v4 must pad the tender's 7-char order_id to v4's 8.

    Targets the CLASS, not the line: any join written against `v4` that
    compares a bare `order_id` is the bug, whichever endpoint adds it next.
    """
    src = _code()
    bare = re.findall(r"\.id\s*=\s*(?!rpad)\w+\.order_id", src)
    assert not bare, f"unpadded join to v4.id: {bare}"
    # ast.unparse keeps the f-string placeholder unrendered, so assert the
    # call shape here and pin the width separately; the live test proves the
    # rendered value actually matches 100% of rows.
    assert "rpad(t.order_id, " in src
    assert edi.V4_ID_WIDTH == 8


def test_never_created_uses_empty_string():
    """`order_id IS NULL` is always false here — 0 NULLs, 17,823 empties."""
    src = _code()
    assert "order_id IS NULL" not in src, "order_id is never NULL, only ''"
    assert "order_id <> ''" in src


def test_headline_counts_are_shipment_grain():
    """The per-shipment CTE must group by shipment_id, and summary must read it."""
    cte = edi._per_shipment_cte("TRUE")
    assert "GROUP BY t.shipment_id" in cte
    summary_src = _code(edi.summary)
    assert "FROM per_shipment" in summary_src
    # `tender_messages` is the only row-grain number, and it is summed from the
    # CTE's own per-shipment tally rather than counted off the base table.
    assert "sum(tenders)" in summary_src


def test_no_acceptance_from_status_desc():
    """status_desc / intercompany are ~100% constant — never a funnel input."""
    src = _code()
    for dead in ("status_desc", "intercompany"):
        assert f"t.{dead}" not in src, f"{dead} carries no signal"


def test_reply_created_is_not_acceptance():
    """13,948 of reply_created='N' rows DO have an order — it is a 990 flag."""
    assert "reply_created" not in _code()


def test_scope_upper_bound_is_exclusive_next_day():
    """`received` is a timestamp; `<= end` drops everything after midnight."""
    where, params = edi._scope(
        {
            "start": edi.DATA_FLOOR,
            "end": edi.DATA_FLOOR,
            "customers": [],
            "purposes": [],
            "teams": [],
        }
    )
    assert "t.received < $2" in where
    assert (params[1] - params[0]).days == 1


def test_scope_pads_to_the_stored_width():
    """customer_id is varchar(8); the padded twin must be offered."""
    where, params = edi._scope(
        {
            "start": edi.DATA_FLOOR,
            "end": edi.DATA_FLOOR,
            "customers": ["RXOMI"],
            "purposes": [],
            "teams": [],
        }
    )
    assert "t.customer_id = ANY($3)" in where
    assert "RXOMI" in params[2] and "RXOMI   " in params[2]


def test_company_id_is_compared_column_to_column():
    """company_id declares varchar(32) but STORES the 4-char 'TMS '.

    pad_variants(width=32) would produce 'TMS' and 'TMS'+29 spaces and match
    neither. Comparing the two columns directly sidesteps the whole trap, so
    assert no literal width-32 padding ever appears.
    """
    src = _code()
    assert "b.company_id = t.company_id" in src or "b.company_id = s.company_id" in src
    assert "width=32" not in src


def test_actioned_rate_denominator_excludes_uncreated():
    """A cancel on a tender we never created needs no action."""
    # ast.unparse normalises double quotes to single — compare quote-agnostically.
    src = _code(edi.summary).replace("'", '"')
    assert 'AS cust_cancelled_created' in src
    assert 'data["cust_cancelled_created"]' in src


# --------------------------------------------------------------------------
# live — skipped unless the gold DSN is configured
# --------------------------------------------------------------------------

_GOLD = os.environ.get("SAVINGS_DATABASE_URL")
if not _GOLD:  # pragma: no cover - convenience for local runs
    try:
        from app.config import settings

        _GOLD = settings.SAVINGS_DATABASE_URL or None
    except Exception:
        _GOLD = None

_live = pytest.mark.skipif(
    not _GOLD, reason="SAVINGS_DATABASE_URL not set — offline run"
)


class _FakeApp:
    def __init__(self, pool):
        self.state = type("S", (), {"savings_pool": pool})()


class _FakeRequest:
    def __init__(self, pool):
        self.app = _FakeApp(pool)


async def _pool():
    import asyncpg

    dsn = re.sub(r"[?&]sslmode=[a-zA-Z-]+", "", _GOLD)
    return await asyncpg.create_pool(dsn, ssl="require", min_size=1, max_size=2)


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


@pytest.fixture(scope="module")
def gold():
    if not _GOLD:
        pytest.skip("offline")
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    pool = loop.run_until_complete(_pool())
    yield pool
    loop.run_until_complete(pool.close())


_FILTERS = {
    "start": edi.DATA_FLOOR,
    "end": __import__("datetime").date(2026, 12, 31),
    "customers": [],
    "purposes": [],
    "teams": [],
}


@_live
def test_live_every_endpoint_executes(gold):
    """Text is not validity — actually run each endpoint's SQL (§81)."""
    req = _FakeRequest(gold)
    loop = asyncio.get_event_loop()

    for coro in (
        edi.filters(req, _user={}),
        edi.summary(req, f=dict(_FILTERS), _user={}),
        edi.chart(req, grain="month", f=dict(_FILTERS), _user={}),
        edi.by_customer(req, f=dict(_FILTERS), _user={}),
        edi.exceptions(req, live_only=True, f=dict(_FILTERS), _user={}),
        edi.exceptions(req, live_only=False, f=dict(_FILTERS), _user={}),
        edi.table(req, f=dict(_FILTERS), _user={}),
        edi.freshness(req, _user={}),
    ):
        out = loop.run_until_complete(coro)
        assert out["success"] is True


@_live
@pytest.mark.parametrize("grain", ["day", "week", "month"])
def test_live_every_chart_grain_parses(gold, grain):
    """date_trunc is interpolated, so every enum value needs its own run."""
    req = _FakeRequest(gold)
    out = asyncio.get_event_loop().run_until_complete(
        edi.chart(req, grain=grain, f=dict(_FILTERS), _user={})
    )
    assert out["success"] is True


@_live
def test_live_join_matches_every_order(gold):
    """rpad() must match 100% of tenders that carry an order_id.

    A bare `br4.id = t.order_id` matched 0 of 47,928. If this drops below
    100% the key format changed upstream.
    """
    loop = asyncio.get_event_loop()

    async def _go():
        async with gold.acquire() as conn:
            return await conn.fetchrow(
                f"""
                SELECT count(*) AS with_order,
                       count(b.id) AS matched
                  FROM {edi.TABLE} t
                  LEFT JOIN {edi.V4} b
                         ON b.id = rpad(t.order_id, {edi.V4_ID_WIDTH})
                        AND b.company_id = t.company_id
                 WHERE t.order_id <> ''
                """
            )

    row = loop.run_until_complete(_go())
    assert row["with_order"] > 0
    assert row["matched"] == row["with_order"], "order_id key format changed"


@_live
def test_live_order_id_is_empty_string_never_null(gold):
    loop = asyncio.get_event_loop()

    async def _go():
        async with gold.acquire() as conn:
            return await conn.fetchrow(
                f"SELECT count(*) FILTER (WHERE order_id IS NULL) AS nulls,"
                f"       count(*) FILTER (WHERE order_id = '') AS empties"
                f"  FROM {edi.TABLE}"
            )

    row = loop.run_until_complete(_go())
    assert row["nulls"] == 0
    assert row["empties"] > 0


@_live
def test_live_shipment_id_is_not_unique(gold):
    """If this ever becomes unique the shipment-grain rollup is dead weight."""
    loop = asyncio.get_event_loop()

    async def _go():
        async with gold.acquire() as conn:
            return await conn.fetchrow(
                f"SELECT count(*) AS rows, count(DISTINCT shipment_id) AS ships"
                f"  FROM {edi.TABLE}"
            )

    row = loop.run_until_complete(_go())
    assert row["rows"] > row["ships"], "shipment_id became unique — revisit the grain"


@_live
def test_live_invariant_violation_is_reported_not_assumed(gold):
    """The vendor's stated rule does not hold; the exception board depends on it.

    `cancelled_order='Y'` AND order_id present ⇒ `order_cancelled='Y'` was
    violated by 1,596 rows on 2026-08-26. When Omar's ETL is corrected this
    test fails — that is the signal to retire /exceptions, not to loosen it.
    """
    loop = asyncio.get_event_loop()

    async def _go():
        async with gold.acquire() as conn:
            return await conn.fetchval(
                f"""
                SELECT count(*) FROM {edi.TABLE}
                 WHERE cancelled_order = 'Y'
                   AND order_id <> ''
                   AND coalesce(order_cancelled, '') <> 'Y'
                """
            )

    assert loop.run_until_complete(_go()) > 0


@_live
def test_live_purpose_cancel_equals_cancelled_order_flag(gold):
    """They are the same fact; if they diverge the KPI split needs rethinking."""
    loop = asyncio.get_event_loop()

    async def _go():
        async with gold.acquire() as conn:
            return await conn.fetchval(
                f"""
                SELECT count(*) FROM {edi.TABLE}
                 WHERE (purpose = 'CANCEL') <> (cancelled_order = 'Y')
                """
            )

    assert loop.run_until_complete(_go()) == 0
