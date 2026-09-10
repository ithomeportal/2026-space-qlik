"""The in-report Favorites rail — access parity, per-user ordering, and the two
silent catalog bugs found alongside it (request 2026-09-09).

``<FavoritesSidebar/>`` renders on every ``/reports/*`` route and is fed by
``GET /user/favorites``. Three things can break it without anything erroring:

1. **The gate drifts from Home's.** ``list_reports`` filters favourites through
   ``role_report_access`` + ``user_roles``. If the rail's own query loses one of
   those joins it starts listing reports the user may no longer open — a 403 on
   click at best, a title leak at worst. So the gate is asserted line by line
   against ``list_reports``' own SQL rather than restated here.

2. **"Most used" quietly becomes "most used by the company".** The Home grid's
   ``view_count`` is a global 30-day count; the rail must count only
   ``al.user_id = $1``. Both produce a plausible, non-empty, correctly-typed
   ordering, so no data-driven assertion can tell them apart — ⚠ and a stub pool
   cannot see a ``WHERE`` at all. These guards therefore read the SQL text and
   are mutation-checked: deleting ``al.user_id`` from the subquery, or swapping
   in the 30-day window, must turn them red.

3. **The ``mobile`` flag REPLACES the desktop set.** ``useIsMobile()`` calls any
   viewport under 1920px mobile, and every seeded report carries
   ``is_mobile = FALSE`` — so ``COALESCE(r.is_mobile, FALSE) = $2`` returned
   *zero rows* on any laptop and Home rendered "0 reports · 14 apps" with no
   error. Fixed as a CLASS across all three statements (list, count, trending),
   and guarded here as a class: no statement may use the equality form again.

Offline: every test either reads source text or drives the endpoint with a fake
pool. Nothing here touches a database.
"""

from __future__ import annotations

import asyncio
import inspect
import pathlib
import re
from uuid import UUID, uuid4

import pytest

from app.routers import reports as reports_mod
from app.services.seed import CUSTOM_REPORTS

_FRONTEND = pathlib.Path(__file__).resolve().parents[2] / "frontend"


def _sql_of(func) -> str:
    """An endpoint's source with its DOCSTRING removed.

    ⚠ The docstring must go, or a guard passes on prose: these docstrings
    discuss the very joins the parity test looks for. And it must go by exact
    text — ``func.__doc__`` — not by stripping triple-quoted blocks, because the
    SQL itself is triple-quoted and a blunt stripper would empty the function
    and make every assertion below vacuously true.
    """
    src = inspect.getsource(func)
    doc = func.__doc__
    return src.replace(doc, "") if doc else src


# ── 1. the gate is Home's gate ───────────────────────────────────────────────

# Every line that makes `GET /reports` access-controlled. Copied from nothing —
# `test_gate_lines_are_actually_in_list_reports` proves each one is really there,
# so a refactor of `list_reports` cannot leave this list asserting a fiction.
_GATE_LINES = (
    "JOIN role_report_access rra ON rra.report_id = r.id",
    "JOIN user_roles ur ON ur.role_id = rra.role_id AND ur.user_id = $1",
    "WHERE r.is_active = TRUE",
)


@pytest.mark.parametrize("line", _GATE_LINES)
def test_gate_lines_are_actually_in_list_reports(line: str) -> None:
    """Pins the reference. Without this the parity test below is vacuous."""
    assert line in _sql_of(reports_mod.list_reports)


@pytest.mark.parametrize("line", _GATE_LINES)
def test_favorites_reuses_the_home_access_gate(line: str) -> None:
    assert line in _sql_of(reports_mod.list_user_favorites), (
        "the rail must be gated exactly like Home's Favorites filter — a report "
        "the user lost the TagRole for has to disappear from BOTH"
    )


def test_favorites_has_no_admin_bypass() -> None:
    """`GET /reports` has none either — the rail is a shortcut to what you can
    already see, not a second door."""
    src = _sql_of(reports_mod.list_user_favorites)
    assert "admin" not in src.split('"""')[2], "no role-name escape hatch in the query"


def test_favorites_reads_the_users_own_pins() -> None:
    src = _sql_of(reports_mod.list_user_favorites)
    assert "up.user_id = $1" in src
    assert "r.id = ANY(up.pinned_reports)" in src


# ── 2. "most used" is per-user ───────────────────────────────────────────────


def _access_log_subquery(src: str) -> str:
    """The correlated COUNT over access_log, whitespace-collapsed."""
    m = re.search(r"SELECT COUNT\(\*\) FROM access_log al(.*?)\), 0", src, re.S)
    assert m, "the use_count subquery moved — this guard is now blind"
    return " ".join(m.group(1).split())


def test_use_count_is_scoped_to_this_user() -> None:
    sub = _access_log_subquery(_sql_of(reports_mod.list_user_favorites))
    assert "al.user_id = $1" in sub, (
        "without this the rail orders every user's favourites by the COMPANY's "
        "habits — same shape, same types, never empty, always wrong"
    )


def test_use_count_is_all_time_not_a_rolling_window() -> None:
    sub = _access_log_subquery(_sql_of(reports_mod.list_user_favorites))
    assert "INTERVAL" not in sub, (
        "a window silently re-shuffles the rail for anyone back from leave"
    )


def test_home_grid_deliberately_stays_company_wide() -> None:
    """The two orderings are ALLOWED to disagree — this records that it is a
    decision, so nobody 'fixes' Home to match the rail."""
    src = _sql_of(reports_mod.list_reports)
    assert "INTERVAL '30 days'" in src
    assert "al.user_id" not in src


def test_favorites_orders_by_own_use_then_title() -> None:
    src = _sql_of(reports_mod.list_user_favorites)
    assert "ORDER BY use_count DESC, r.title" in src


# ── 3. `mobile` includes, never replaces ─────────────────────────────────────

_MOBILE_STATEMENTS = ("list_reports", "trending_reports", "list_user_favorites")


@pytest.mark.parametrize("name", _MOBILE_STATEMENTS)
def test_mobile_flag_never_replaces_the_desktop_set(name: str) -> None:
    src = _sql_of(getattr(reports_mod, name))
    assert not re.search(r"COALESCE\(r\.is_mobile, FALSE\) = \$\d", src), (
        "the equality form returns ZERO rows below 1920px — no report is ever "
        "seeded with is_mobile = TRUE"
    )
    assert "COALESCE(r.is_mobile, FALSE) = FALSE OR $" in src


# ── 4. the catalog is not truncated ──────────────────────────────────────────


def _limit_bound(func, param: str, kind: str) -> int:
    meta = inspect.signature(func).parameters[param].default.metadata
    for m in meta:
        if type(m).__name__ == kind:
            return getattr(m, kind.lower())
    raise AssertionError(f"{param} has no {kind} bound")


def test_reports_page_cap_fits_the_whole_catalog() -> None:
    """64 code-made reports against a cap of 50 meant Home silently dropped the
    tail. Tied to the real count so report #501 fails here, not in a screenshot."""
    cap = _limit_bound(reports_mod.list_reports, "limit", "Le")
    assert cap >= len(CUSTOM_REPORTS), (
        f"{len(CUSTOM_REPORTS)} reports exist and GET /reports caps at {cap}"
    )


def test_frontend_asks_for_the_whole_catalog() -> None:
    """A generous server cap is useless if the client still asks for 50."""
    api = (_FRONTEND / "lib" / "api.ts").read_text()
    m = re.search(r"REPORTS_PAGE_LIMIT\s*=\s*(\d+)", api)
    assert m, "frontend/lib/api.ts must declare REPORTS_PAGE_LIMIT"
    asked = int(m.group(1))
    assert asked >= len(CUSTOM_REPORTS), f"client asks for {asked} of {len(CUSTOM_REPORTS)}"
    assert asked <= _limit_bound(reports_mod.list_reports, "limit", "Le"), (
        "asking above the server cap is a 422, not a bigger page"
    )
    assert f"limit={asked}" in api or f'String({asked})' in api or "REPORTS_PAGE_LIMIT" in api


# ── 5. the endpoint, driven ──────────────────────────────────────────────────


class _FakePool:
    def __init__(self, rows: list[dict]) -> None:
        self.rows = rows
        self.params: tuple = ()

    async def fetch(self, _sql: str, *params):  # noqa: ANN002
        self.params = params
        return self.rows


class _FakeRequest:
    def __init__(self, pool: _FakePool) -> None:
        self.app = type("app", (), {"state": type("state", (), {"pool": pool})()})()


def _drive(rows: list[dict], monkeypatch: pytest.MonkeyPatch, mobile: bool = False):
    pool = _FakePool(rows)
    uid = uuid4()
    monkeypatch.setattr(reports_mod, "get_pool", lambda _request: pool)
    monkeypatch.setattr(reports_mod, "user_uuid", lambda _user: uid)
    out = asyncio.run(
        reports_mod.list_user_favorites(_FakeRequest(pool), {"sub": str(uid)}, mobile)
    )
    return out, pool, uid


def _row(title: str, key: str, uses: int) -> dict:
    return {
        "id": uuid4(),
        "title": title,
        "category": "Executive",
        "custom_path": f"/reports/{key}",
        "use_count": uses,
    }


def test_envelope_and_binding(monkeypatch: pytest.MonkeyPatch) -> None:
    rows = [_row("CEO Cockpit", "ceo-cockpit", 9)]
    out, pool, uid = _drive(rows, monkeypatch)
    assert out["success"] is True
    assert [r["custom_path"] for r in out["data"]] == ["/reports/ceo-cockpit"]
    assert pool.params == (uid, False), "user first, mobile second"


def test_mobile_flag_is_forwarded(monkeypatch: pytest.MonkeyPatch) -> None:
    _, pool, uid = _drive([], monkeypatch, mobile=True)
    assert pool.params == (uid, True)


def test_row_order_survives_the_endpoint(monkeypatch: pytest.MonkeyPatch) -> None:
    """The DB does the ordering; the endpoint must not re-sort or de-dupe it."""
    rows = [_row("Zulu", "z", 12), _row("Alpha", "a", 3)]
    out, _, _ = _drive(rows, monkeypatch)
    assert [r["title"] for r in out["data"]] == ["Zulu", "Alpha"]


def test_empty_favorites_is_an_empty_list_not_an_error(monkeypatch: pytest.MonkeyPatch) -> None:
    out, _, _ = _drive([], monkeypatch)
    assert out == {"success": True, "data": []}


# ── 6. the route is reachable ────────────────────────────────────────────────


def test_route_is_registered_under_user_favorites() -> None:
    paths = {r.path for r in reports_mod.router.routes}
    assert "/user/favorites" in paths


def test_custom_path_is_selected() -> None:
    """The rail links straight to `custom_path` for instant navigation — if the
    column stops being selected, every row 404s."""
    assert "r.custom_path" in _sql_of(reports_mod.list_user_favorites)


# ── 7. the statement actually parses ─────────────────────────────────────────


def _favorites_statement() -> str:
    src = _sql_of(reports_mod.list_user_favorites)
    m = re.search(r'"""(\s*SELECT DISTINCT.*?)"""', src, re.S)
    assert m, "could not locate the favourites SQL literal"
    return m.group(1)


@pytest.mark.skipif(
    not __import__("os").environ.get("DATABASE_URL"),
    reason="offline by default — set DATABASE_URL to PREPARE against the hub",
)
def test_live_statement_prepares() -> None:
    """⚠ Text assertions are satisfied by strings Postgres will reject.

    `SELECT DISTINCT … ORDER BY use_count` orders by an output alias while
    DISTINCT is in play — legal, but only just, and the 2026-08-24 DFW incident
    was four endpoints returning SQLSTATE 42601 past 433 green text assertions.
    So PREPARE it for real when a database is reachable.
    """
    import asyncpg  # noqa: PLC0415

    async def _prepare() -> None:
        conn = await asyncpg.connect(__import__("os").environ["DATABASE_URL"])
        try:
            await conn.prepare(_favorites_statement())
        finally:
            await conn.close()

    asyncio.run(_prepare())


# ── 8. the layout contract, guarded from the only side that has a runner ─────
#
# There is no JS test runner in this repo (`next lint` + `next build` are the
# frontend gates, and neither can see a layout regression). These read the TSX
# as text. Crude, but each one pins a failure that is INVISIBLE — the page still
# renders, still builds, still lints.


def _reports_layout() -> str:
    return (_FRONTEND / "app" / "reports" / "layout.tsx").read_text()


def test_rail_renders_from_the_reports_layout_only() -> None:
    """"This dashboard https://space.unilinkportal.com/ will stay as it is now."
    `/` does not pass through `app/reports/layout.tsx`, so mounting the rail
    anywhere else — the root layout especially — breaks that requirement."""
    assert "FavoritesSidebar" in _reports_layout()
    root = (_FRONTEND / "app" / "layout.tsx").read_text()
    home = (_FRONTEND / "app" / "page.tsx").read_text()
    assert "FavoritesSidebar" not in root
    assert "FavoritesSidebar" not in home


def test_content_column_keeps_min_w_0() -> None:
    """A flex item defaults to `min-width: auto`. Drop `min-w-0` and a report
    with a wide table stops scrolling its table and scrolls the whole PAGE
    sideways instead — on 65 routes, with no error anywhere."""
    assert "min-w-0 flex-1" in _reports_layout()


def test_reports_layout_never_becomes_a_scroll_container() -> None:
    """⚠ The moment this wrapper scrolls, it becomes the scroll container for
    the report inside it and the `sticky top-0` toolbars ~20 reports rely on
    stop resolving against the viewport. The rail scrolls itself instead."""
    layout = _reports_layout()
    body = layout.split("export default function")[1]
    assert "overflow" not in body, "no overflow on the reports layout wrapper"


def test_rail_owns_the_only_overflow_and_can_scroll() -> None:
    """"If the list of Favorites for some reason it's long, just aloud scroll
    down on that lateral left column.\""""
    rail = (_FRONTEND / "components" / "FavoritesSidebar.tsx").read_text()
    # ⚠ Count only what the browser sees. The comment block above the component
    # explains this very rule, and counting raw occurrences would let a second
    # real scroll container hide behind that prose.
    classnames = " ".join(re.findall(r'className=\{?"([^"]*)"', rail))
    assert classnames.count("overflow-y-auto") == 1, "exactly one scroll container"
    # `min-h-0` is what lets a flex child actually shrink enough to scroll —
    # without it the nav grows past the rail and the page scrolls instead.
    assert "min-h-0 flex-1 space-y-0.5 overflow-y-auto" in rail


def test_rail_offers_all_three_orders() -> None:
    """Default most-used, header click toggles alphabetical asc/desc."""
    rail = (_FRONTEND / "components" / "FavoritesSidebar.tsx").read_text()
    assert '["usage", "az", "za"]' in rail
    assert 'useState<SortMode>("usage")' in rail, "most-used is the DEFAULT"


def test_rail_logs_the_reports_it_navigates_to() -> None:
    """⚠ The rail links straight to `custom_path`, skipping the `/reports/[id]`
    redirect that is the ONLY writer of `access_log`. Without an explicit log
    call, a user who switches reports only via the rail stops generating usage
    entirely and the "most used" order it is sorted by silently freezes."""
    rail = (_FRONTEND / "components" / "FavoritesSidebar.tsx").read_text()
    assert "logReportAccess(report.id)" in rail
    api = (_FRONTEND / "lib" / "api.ts").read_text()
    assert "export function logReportAccess" in api
    assert "keepalive: true" in api, "must survive the navigation it triggers"


def test_starring_invalidates_the_rail() -> None:
    """Un-starring from a report page has to empty its row, not just Home's."""
    api = (_FRONTEND / "lib" / "api.ts").read_text()
    settled = api.split("onSettled: () => {")[1].split("},")[0]
    assert '["favorites"]' in settled
