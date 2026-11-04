"""Sales- Attrition to OPs: old customers must stay findable.

Reported 2026-11-04: nine customers with 2022-2024 revenue could not be found.
Three independent causes, each pinned here so it cannot quietly come back:

1. The team scope listed only today's teams, so a customer under BD1-3,
   TEAM-OCA or TEAM6 was hidden under every date range (83 customers, $8.84M in
   2022-2024; TEAM6 adds $5.9M in 2021).
2. The Customer box listed only the last 400 days, even under a Custom range.
3. The report carried no customer code, so searching by code found nobody.

Runs offline: a stub pool records the SQL and params the handlers send.
"""

from __future__ import annotations

import asyncio
import re
from datetime import date, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.clock import cst_today
from app.routers import sales_attrition_to_ops as saop

FRONTEND = Path(__file__).resolve().parents[2] / "frontend"
PAGE = FRONTEND / "app/reports/sales-attrition-to-ops/page.tsx"
API = FRONTEND / "lib/sales-attrition-to-ops-api.ts"

HISTORICAL = {"BD1", "BD2", "BD3", "TEAM-OCA", "TEAM6"}
CURRENT = {"TEAM1", "TEAM2", "TEAM3", "TEAM4", "TEAM5", "TEAM-DFW"}
# Non-sales or person-style codes, measured at about $55K in total. Left out on purpose.
NOT_TEAMS = {"N/A", "ADMIN", "CHRMEN", "JMCGHEE", "CAROD", "CARODR"}


class StubPool:
    def __init__(self, rows: list[dict]) -> None:
        self.rows = rows
        self.sql = ""
        self.params: tuple = ()

    async def fetch(self, sql: str, *params):
        self.sql = sql
        self.params = params
        return self.rows


@pytest.fixture
def use_pool(monkeypatch):
    def install(rows: list[dict]) -> StubPool:
        pool = StubPool(rows)
        monkeypatch.setattr(saop, "get_datalake_gold_pool", lambda _request: pool)
        return pool

    return install


def call_filters(**kwargs) -> dict:
    args = {"range": "last_365", "start_date": None, "end_date": None}
    return asyncio.run(saop.filters(SimpleNamespace(), **{**args, **kwargs}, _user={}))


def call_details() -> dict:
    return asyncio.run(
        saop.details(
            SimpleNamespace(),
            range="custom",
            start_date=date(2022, 1, 1),
            end_date=date(2024, 12, 31),
            teams=None,
            customer=None,
            bucket=None,
            sort="days_desc",
            page=1,
            limit=100,
            _user={},
        )
    )


# --- 1. Team scope ----------------------------------------------------------


def test_scope_holds_current_and_historical_teams_only() -> None:
    assert set(saop.ALL_TEAMS) == CURRENT | HISTORICAL
    assert not set(saop.ALL_TEAMS) & NOT_TEAMS


def test_historical_teams_are_on_by_default_and_can_be_picked_alone() -> None:
    assert HISTORICAL <= set(saop._parse_teams(None))
    assert saop._parse_teams("BD1") == ["BD1"]
    # An unknown code is still refused rather than widening the scope.
    assert saop._parse_teams("ADMIN") == list(saop.ALL_TEAMS)


def test_frontend_team_list_mirrors_the_backend() -> None:
    block = re.search(r"const ALL_TEAMS = \[(.*?)\] as const", PAGE.read_text(), re.DOTALL)
    assert block is not None
    assert re.findall(r'"([^"]+)"', block.group(1)) == list(saop.ALL_TEAMS)


# --- 2. Customer box follows the date range ---------------------------------


def test_custom_range_lists_customers_from_exactly_that_range(use_pool) -> None:
    pool = use_pool([])
    call_filters(range="custom", start_date=date(2022, 1, 1), end_date=date(2024, 12, 31))
    assert date(2022, 1, 1) in pool.params
    # Half-open upper bound: the last selected day must be fully included.
    assert date(2025, 1, 1) in pool.params


def test_custom_range_with_swapped_dates_still_lists_customers(use_pool) -> None:
    pool = use_pool([])
    call_filters(range="custom", start_date=date(2024, 12, 31), end_date=date(2022, 1, 1))
    assert date(2022, 1, 1) in pool.params
    assert date(2025, 1, 1) in pool.params


@pytest.mark.parametrize("preset", ["last_365", "mtd", "last_month", "ytd"])
def test_presets_keep_the_13_month_list(use_pool, preset: str) -> None:
    # The trend strip ignores the Date filter and spans 13 months, so a preset
    # must not narrow who can be picked for it.
    pool = use_pool([])
    call_filters(range=preset)
    assert cst_today() - timedelta(days=saop.WINDOW_FLOOR_DAYS) in pool.params
    assert None in pool.params


def test_customer_list_covers_the_historical_teams(use_pool) -> None:
    pool = use_pool([])
    call_filters()
    variants = pool.params[0]
    assert {"BD1", "BD2", "BD3", "TEAM-OCA", "TEAM6"} <= set(variants)


# --- 3. Customer codes ------------------------------------------------------


def test_filters_return_each_customers_codes(use_pool) -> None:
    pool = use_pool([{"customer_name": "AISIN MEXICANA", "codes": ["AISICINL", "AISINMMX"]}])
    data = call_filters()["data"]
    assert "customer_id" in pool.sql
    assert data["customer_options"] == [
        {"name": "AISIN MEXICANA", "codes": ["AISICINL", "AISINMMX"]}
    ]
    assert data["customers"] == ["AISIN MEXICANA"]


def test_filters_tolerate_a_customer_with_no_code(use_pool) -> None:
    use_pool([{"customer_name": "NO CODE LTD", "codes": None}])
    assert call_filters()["data"]["customer_options"] == [{"name": "NO CODE LTD", "codes": []}]


def test_details_rows_carry_codes(use_pool) -> None:
    pool = use_pool(
        [
            {
                "customer": "EMBOTELLADORAS NOVAMEX",
                "codes": ["EMBOJUMX"],
                "team": "TEAM1",
                "loads": 49,
                "revenue": 92855,
                "profit": 1,
                "margin_pct": None,
                "last_load_date": date(2023, 9, 27),
                "days_since": 459,
                "sparkline": [],
                "customers_total": 1,
                "loads_total": 49,
                "revenue_total": 92855,
                "profit_total": 1,
                "margin_total": None,
                "rows_after_bucket": 1,
            }
        ]
    )
    data = call_details()["data"]
    assert "customer_id" in pool.sql
    assert data["rows"][0]["codes"] == ["EMBOJUMX"]


def test_rows_stay_grouped_by_customer_name(use_pool) -> None:
    # Grouping by code would change row counts. Codes are displayed, not grouped on.
    pool = use_pool([])
    call_details()
    assert re.search(r"FROM filtered\s+GROUP BY customer\s", pool.sql)


# --- Frontend wiring (no JS test runner here; guards read the source) -------


def test_customer_list_request_follows_the_custom_dates() -> None:
    src = API.read_text()
    hook = src[src.index("export function useSaopFilters") :]
    hook = hook[: hook.index("export function useSaopDetails")]
    assert "start_date" in hook and "end_date" in hook
    # The dates must be in the cache key or a new range keeps serving the old list.
    assert re.search(r"queryKey:\s*\[[^\]]*startDate[^\]]*endDate", hook, re.DOTALL)


def test_page_searches_and_shows_codes() -> None:
    src = PAGE.read_text()
    assert "useSaopFilters(range, startDate, endDate)" in src
    assert "customer_options" in src
    assert re.search(r"\.codes\.some\(", src), "Customer box must match on code"
    assert "row.codes" in src, "table must show the code"
    # The table gained a column: spanning rows must still cover all of it.
    assert "colSpan={9}" not in src and "colSpan={10}" in src
