"""Podium Set DFW — PDF 2026-11-09 ("space -- DFW Podium Set Updates").

  R1  A date-basis toggle: the range filters origin_actual_departure (v4)
      instead of the Rate-Conf posting date. SAME population (Diego
      2026-11-09: "Rate Conf loads only"), only the date moves.
  R2  A "Status" filter on v4 status — server-side, so the KPIs follow (§96).
"""

from __future__ import annotations

import asyncio
import re
from datetime import datetime
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app.routers import podium_dfw as pd


def _build(**kw):
    args = {"basis": "rate_conf", "range_": "today", "start": None,
            "end": None, "status": []}
    args.update(kw)
    return pd.build_overview_sql(**args)


def _placeholders(sql: str) -> set[int]:
    return {int(n) for n in re.findall(r"\$(\d+)", sql)}


# -------------------------------------------------------------- basis=rate_conf

@pytest.mark.parametrize("range_", ["today", "wtd", "mtd"])
def test_rate_conf_default_keeps_original_params(range_):
    """Default basis is the original: [$1 teams, $2 NULL floor]."""
    cte, where, order_by, params = _build(range_=range_)
    assert params == [["TEAM-DFW"], None]
    assert where == pd._RANGE_FILTERS[range_]
    assert order_by.startswith("posted_date DESC")
    assert "LEAST(" in cte  # the posted_date scan floor stays


def test_rate_conf_custom_inclusive_end_of_day():
    _, where, _, params = _build(range_="custom", start="2026-10-01", end="2026-10-31")
    assert where == pd._CUSTOM_FILTER
    assert params[1] == datetime(2026, 10, 1)
    assert params[2] == datetime(2026, 10, 31, 23, 59, 59, 999999)


# -------------------------------------------------------------- basis=departure

@pytest.mark.parametrize("range_", ["today", "wtd", "mtd"])
def test_departure_presets_pass_no_unused_argument(range_):
    """asyncpg rejects an argument the SQL never references."""
    cte, where, order_by, params = _build(basis="departure", range_=range_)
    assert params == [["TEAM-DFW"]]
    assert _placeholders(cte) == {1}
    assert where == "TRUE"
    assert order_by.startswith("departed DESC")


def test_departure_does_not_use_the_posted_date_floor():
    """A departure's Rate Conf is posted up to 84 days earlier — the MTD-7d
    posted_date floor lost 22 of October's 1,523 loads."""
    cte, *_ = _build(basis="departure", range_="mtd")
    assert "LEAST(" not in cte
    assert not re.search(r"posted_date\s*>=", cte)
    assert "id IN (SELECT id FROM departed_ids)" in cte


def test_departure_custom_is_half_open_and_reordered():
    cte, _, _, params = _build(basis="departure", range_="custom",
                               start="2026-10-31", end="2026-10-01")
    assert params[1:] == [datetime(2026, 10, 1), datetime(2026, 11, 1)]
    assert "origin_actual_departure <  $3::timestamp" in cte


def test_departure_guards_the_1900_sentinel_in_both_scans():
    """Not-departed loads carry 1900-01-01, not NULL. A custom start of 1900
    must not sweep every undeparted load in."""
    cte, *_ = _build(basis="departure", range_="custom",
                     start="1900-01-01", end="1900-01-02")
    guards = re.findall(
        r"AND (?:br\.)?origin_actual_departure >= '2000-01-01'::timestamp", cte
    )
    assert len(guards) == 2  # departed_ids scan + the rate_conf WHERE


def test_departure_keeps_the_rate_conf_population():
    """Same population as rate_conf: Rate-Conf postings, DFW, never Void."""
    cte, *_ = _build(basis="departure", range_="mtd")
    assert "'Rate Conf Received'" in cte
    assert "rp.rn = 1" in cte
    assert cte.count("status <> 'V'") == 2
    assert cte.count("team_id = ANY($1::text[])") == 2


def test_departure_bounds_stay_naive():
    """§112: never a bare ::date before AT TIME ZONE; bounds are naive CST."""
    for lo, hi in pd._DEPARTURE_BOUNDS.values():
        assert "AT TIME ZONE" not in lo + hi


def test_departed_column_hides_the_sentinel():
    assert re.search(
        r"CASE WHEN br\.origin_actual_departure >= '2000-01-01'::timestamp\s+"
        r"THEN br\.origin_actual_departure END AS departed",
        pd._COLUMNS,
    )


# ---------------------------------------------------------------------- status

@pytest.mark.parametrize("basis", ["rate_conf", "departure"])
def test_status_is_a_server_side_predicate(basis):
    cte, _, _, params = _build(basis=basis, range_="mtd", status=["D", "P"])
    n = len(params)
    assert params[-1] == ["D", "P"]
    assert f"br.status = ANY(${n}::text[])" in cte
    assert _placeholders(cte) == set(range(1, n + 1))


def test_no_status_means_no_predicate():
    cte, *_ = _build(range_="mtd")
    assert "br.status = ANY(" not in cte


def test_parse_status_normalises_and_dedupes():
    assert pd._parse_status([" d", "P", "D"]) == ["D", "P"]
    assert pd._parse_status(None) == []


@pytest.mark.parametrize("bad", ["V", "X", "", "DP"])
def test_parse_status_rejects_void_and_unknown(bad):
    """Void is excluded for every user (Bruno 2026-07-07) — never selectable."""
    with pytest.raises(HTTPException) as exc:
        pd._parse_status([bad])
    assert exc.value.status_code == 400


@pytest.mark.parametrize("start,end", [(None, "2026-10-01"), ("2026-13-40", "2026-10-01")])
def test_custom_needs_two_real_dates(start, end):
    with pytest.raises(HTTPException) as exc:
        _build(basis="departure", range_="custom", start=start, end=end)
    assert exc.value.status_code == 400


# ------------------------------------------------------------ endpoint wiring

class _Pool:
    def __init__(self):
        self.calls: list[tuple[str, tuple]] = []

    async def fetchrow(self, sql, *args):
        self.calls.append((sql, args))
        return {"loads": 1, "profit": 10.0, "revenue": 100.0, "margin_pct": 0.1}

    async def fetch(self, sql, *args):
        self.calls.append((sql, args))
        return [{
            "team": "TM1", "order_id": "1", "posted_by": "X",
            "posted_date": datetime(2026, 10, 1, 9), "departed": None,
            "status": "A", "customer": "C", "origin": "O", "destination": "D",
            "carrier": None, "profit": 10.0, "revenue": 100.0, "margin_pct": 0.1,
            "contract_type": "Spot", "equipment_type": "Van", "company_id": "TMS",
        }]


def test_overview_returns_basis_status_and_new_row_fields():
    pool = _Pool()
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(savings_pool=pool)))
    out = asyncio.run(pd.overview(
        request, range="mtd", start=None, end=None,
        basis="departure", status=["p", "D"], _user={},
    ))
    data = out["data"]
    assert data["basis"] == "departure"
    assert data["status"] == ["P", "D"]
    assert data["rows"][0]["status"] == "A"
    assert data["rows"][0]["departed"] is None
    # KPI and rows queries share ONE population (same CTE, same args) — §96.
    (kpi_sql, kpi_args), (rows_sql, rows_args) = pool.calls
    assert kpi_args == rows_args
    assert kpi_sql.split("SELECT\n        COUNT")[0] == rows_sql.split("SELECT\n        team")[0]


# ------------------------------------------------------------- frontend wiring

from pathlib import Path  # noqa: E402

_FRONT = Path(__file__).resolve().parents[2] / "frontend"


def _read(rel: str) -> str:
    return (_FRONT / rel).read_text()


def test_frontend_sends_status_as_repeated_params_and_keys_on_qs():
    api = _read("lib/podium-dfw-api.ts")
    assert 'qs.append("status", s)' in api  # never comma-joined (§45)
    assert 'qs.set("basis", basis)' in api
    assert 'queryKey: ["podium-dfw", "overview", qs]' in api  # key covers qs


def test_frontend_never_offers_void():
    api = _read("lib/podium-dfw-api.ts")
    assert 'STATUS_OPTIONS: PodiumStatus[] = ["D", "P", "A"]' in api
    assert 'PodiumStatus = "D" | "P" | "A"' in api


def test_frontend_has_the_basis_switch_and_new_columns():
    page = _read("app/reports/podium-dfw/page.tsx")
    assert 'role="switch"' in page
    assert "usePodiumOverview(" in page and "basis,\n    statuses," in page
    assert 'columnKey="departed"' in page and 'columnKey="status"' in page
