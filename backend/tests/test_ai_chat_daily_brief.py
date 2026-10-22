"""AI chat — the `daily_brief` tool and `"mode": "daily_brief"` (contract §5).

"How is the day looking?" every morning: one server-computed snapshot per CORP team
the asker can open (TEAM1..TEAM4 KAM portals + their Customer Score clones), read
IN-PROCESS from the teams' own endpoints so every number is the portal's. The model
is never called (scripted `create_message`); the team endpoints are tiny fakes mounted
next to the real ai-chat router, behind the real `require_user`.
"""

from __future__ import annotations

import json
import uuid
from types import SimpleNamespace
from typing import Annotated

import pytest
from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.testclient import TestClient

from app.routers import ai_chat, bot_identity
from app.routers.deps import require_user
from app.services import (
    ai_chat_agent,
    ai_chat_daily_brief,
    ai_chat_tools,
    bot_assertion,
)
from app.services.ai_chat_daily_brief import (
    DAILY_BRIEF_MAX_CHARS,
    build_team_snapshot,
    gap_vs_avg,
)

TODAY = "2026-10-22"
PROXY_SECRET = "proxy-secret-value-xyz"
User = Annotated[dict, Depends(require_user)]


def _identity(*roles):
    return {"sub": str(uuid.uuid4()), "email": "exec@unilinktransportation.com",
            "name": "Exec", "roles": list(roles)}


def _auth(identity):
    return {"Authorization": "Bearer " + json.dumps(identity), "X-Proxy-Secret": PROXY_SECRET}


def _catalog():
    rows = []
    for n in range(1, 5):
        grant = [f"corp-t{n}", "executive"]
        rows.append((f"corp-t{n}-ops-kam-portal", f"CORP T{n} - Ops KAM Portal", grant))
        rows.append((f"corp-t{n}-customer-score", f"CORP T{n} - Customer Score", grant))
    return rows


class _Pool:
    async def fetch(self, sql, *args):
        if "FROM reports r" in sql:
            return [{"custom_path": f"/reports/{k}", "title": t, "description": t, "roles": r}
                    for k, t, r in _catalog()]
        return []

    async def fetchrow(self, sql, *args):
        return None


def _portal_data(n):
    """Per-team fake payloads, shaped exactly like the real endpoints' `data`."""
    avg = {1: 1000.0, 2: 2000.0, 3: 1500.0, 4: 0.0}[n]
    return {
        "team-projection": {"avg_prof_day": avg, "avg_vol_day": 10.0, "pending_workdays": 7,
                            "proj_volume": 900.0, "proj_revenue": 1_200_000.0,
                            "proj_profit": 180_000.0, "proj_margin_pct": 15.0,
                            "mtd_volume": 400, "mtd_revenue": 500_000.0, "mtd_profit": 70_000.0,
                            "team_count": 1},
        "team-performance": {"volume": 410, "revenue": 510_000.0, "profit": 71_000.0,
                             "margin_pct": 13.92, "loss_loads": 12, "profit_loss": -4321.5,
                             "window": {"start": "2026-10-01", "end": TODAY}},
        "profit-tm-gauge": {"profit_mtd": 71_000.0, "profit_budget": 100_000.0,
                            "pct_of_budget": 71.0},
        "team-variance": {"volume_var": -20.0, "revenue_var": -30_000.0, "profit_var": -9_000.0,
                          "margin_var_pct": 30.0, "window": {"start": "2026-10-01", "end": TODAY}},
        "customer-losses": [{"customer_name": f"CUST {i}", "loss_loads": i, "loss_profit": -100.0 * i}
                            for i in range(1, 6)],
        "combo": {"today": TODAY, "buckets": [
            {"bucket_start": "2026-10-21", "profit": 5555.0},
            {"bucket_start": TODAY, "profit": 800.0 + n},
        ]},
        "cover-forecast": {"grain": "day", "buckets": [
            {"bucket_start": TODAY, "cover_vol": 3, "cover_rev": 9000.0, "cover_prof": 400.0},
            {"bucket_start": "2026-10-23", "cover_vol": 1, "cover_rev": 1.0, "cover_prof": 999.0},
        ]},
        "data-freshness": {"sources": [
            {"key": "production", "label": "Production", "updated_at": "2026-10-22T07:30:00",
             "age_minutes": 5.0},
            {"key": "budget", "label": "Budget", "updated_at": "2026-10-22T06:00:00",
             "age_minutes": 95.0},
        ], "as_of": "2026-10-22T06:00:00", "stalest": "Budget"},
    }


def _score_data(side):
    fail = 3 if side == "pu" else 5
    return {"kpi_month": {"orders": 100, "fail": fail, "pct_on_time": 100.0 - fail},
            "kpi_quarter": {"orders": 1, "fail": 0, "pct_on_time": 100.0},
            "rolling_12m": [{"bucket": "2026-01-01"}] * 12}


def _build_app(seen: list, broken_team: int | None = None):
    app = FastAPI()
    app.state.pool = _Pool()
    app.middleware("http")(bot_identity.bot_assertion_route_guard)
    app.include_router(ai_chat.router, prefix="/api")

    def _gate(user, key):
        roles = {r.lower() for r in user.get("roles") or []}
        grant = next(g for k, _t, g in _catalog() if k == key)
        if not roles & set(grant):
            raise HTTPException(status_code=403, detail="no access")

    for n in range(1, 5):
        data = _portal_data(n)
        for section, payload in data.items():
            def make(section=section, payload=payload, n=n):
                async def handler(request: Request, user: User):
                    seen.append({"path": request.url.path, "query": dict(request.query_params)})
                    _gate(user, f"corp-t{n}-ops-kam-portal")
                    if broken_team == n and section == "team-projection":
                        raise HTTPException(status_code=500, detail="boom")
                    return {"success": True, "data": payload}
                return handler
            app.get(f"/api/custom/ops-portal-overview-t{n}/{section}")(make())
        for side in ("pu", "del"):
            def make_score(side=side, n=n):
                async def handler(request: Request, user: User):
                    seen.append({"path": request.url.path, "query": dict(request.query_params)})
                    _gate(user, f"corp-t{n}-customer-score")
                    return {"success": True, "data": _score_data(side), "meta": {"cached": False}}
                return handler
            app.get(f"/api/custom/ops-customer-score-t{n}/{side}/pinned")(make_score())

        def make_score_fresh(n=n):
            async def handler(request: Request, user: User):
                _gate(user, f"corp-t{n}-customer-score")
                return {"success": True, "data": {"last_updated": "2026-10-22T05:00:00",
                                                  "last_pu": "2026-10-23T00:00:00"}}
            return handler
        app.get(f"/api/custom/ops-customer-score-t{n}/freshness")(make_score_fresh())
    return app


def _text(t):
    return SimpleNamespace(type="text", text=t)


def _tool(name, inp):
    return SimpleNamespace(type="tool_use", id=f"tu_{uuid.uuid4().hex[:8]}", name=name, input=inp)


def _resp(*blocks):
    stop = "tool_use" if any(b.type == "tool_use" for b in blocks) else "end_turn"
    return SimpleNamespace(content=list(blocks), stop_reason=stop, stop_details=None)


class _Script:
    def __init__(self, *responses):
        self.responses = list(responses)
        self.calls: list[dict] = []

    async def __call__(self, **kwargs):
        self.calls.append({**kwargs, "messages": list(kwargs["messages"])})
        return self.responses.pop(0)


@pytest.fixture(autouse=True)
def configured(monkeypatch):
    monkeypatch.setattr(ai_chat_tools.settings, "PROXY_SHARED_SECRET", PROXY_SECRET, raising=False)
    monkeypatch.setattr(ai_chat_tools.settings, "ANTHROPIC_API_KEY", "sk-ant-test", raising=False)
    monkeypatch.setattr(ai_chat_tools.settings, "SPACE_AI_MODEL", "", raising=False)
    monkeypatch.setattr(ai_chat_daily_brief, "cst_today", lambda: __import__("datetime").date(2026, 10, 22))
    monkeypatch.setattr(ai_chat_tools, "cst_today", lambda: __import__("datetime").date(2026, 10, 22))
    bot_assertion.reset_state()
    ai_chat_tools.invalidate_route_cache()
    yield
    bot_assertion.reset_state()


def _brief(identity, *, broken_team=None, seen=None, mode=None):
    """Run one /ask whose model calls daily_brief once; returns (tool payload, body, script)."""
    seen = [] if seen is None else seen
    client = TestClient(_build_app(seen, broken_team))
    script = _Script(_resp(_tool("daily_brief", {})), _resp(_text("brief")))
    ai_chat_agent.create_message = script  # restored by monkeypatch in callers
    body = {"message": "How is the day looking?"}
    if mode:
        body["mode"] = mode
    resp = client.post("/api/custom/ai-chat/ask", json=body, headers=_auth(identity))
    assert resp.status_code == 200, resp.text
    result = next(b for b in script.calls[1]["messages"][-1]["content"] if b.get("type") == "tool_result")
    return result, resp.json(), script


@pytest.fixture(autouse=True)
def _restore_seam(monkeypatch):
    monkeypatch.setattr(ai_chat_agent, "create_message", ai_chat_agent.create_message)


def _teams(result):
    return [t["team"] for t in json.loads(result["content"])["teams"]]


# ---------------------------------------------------------------- access


def test_tool_is_offered_to_every_question():
    assert "daily_brief" in ai_chat_tools.TOOL_NAMES
    tool = next(t for t in ai_chat_tools.TOOL_DEFINITIONS if t["name"] == "daily_brief")
    assert tool["input_schema"]["properties"] == {}


def test_a_corp_t3_user_gets_only_team3():
    seen: list = []
    result, body, _ = _brief(_identity("CORP-T3"), seen=seen)
    assert not result["is_error"]
    assert _teams(result) == ["TEAM3"]
    # The other teams' endpoints are never even called (catalog gate first).
    assert all("-t3/" in s["path"] for s in seen)
    assert {r["key"] for r in body["reports_used"]} == {"corp-t3-ops-kam-portal", "corp-t3-customer-score"}
    payload = json.loads(result["content"])
    assert [t["team"] for t in payload["teams_not_shown"]] == ["TEAM1", "TEAM2", "TEAM4"]
    assert all(set(t) == {"team", "reason"} for t in payload["teams_not_shown"])


def test_an_executive_gets_all_four_teams():
    result, body, _ = _brief(_identity("Executive"))
    assert _teams(result) == ["TEAM1", "TEAM2", "TEAM3", "TEAM4"]
    assert json.loads(result["content"])["teams_not_shown"] == []
    assert len(body["reports_used"]) == 8
    assert body["tools_used"] == ["daily_brief"]


def test_a_user_with_no_team_gets_no_numbers():
    result, body, _ = _brief(_identity("CORP"))
    payload = json.loads(result["content"])
    assert payload["teams"] == [] and len(payload["teams_not_shown"]) == 4
    assert body["reports_used"] == [] and body["data_as_of"] is None


def test_an_endpoint_403_omits_the_team_even_if_the_catalog_said_yes(monkeypatch):
    """The report's own gate is the second check — a 403 there never leaks numbers."""
    real = ai_chat_tools.ToolSession._accessible_reports

    async def everything(self):
        acc = await real(self)
        return {**acc, **{k: {"title": t, "description": t} for k, t, _ in _catalog()}}

    monkeypatch.setattr(ai_chat_tools.ToolSession, "_accessible_reports", everything)
    result, _body, _ = _brief(_identity("CORP-T2"))
    assert _teams(result) == ["TEAM2"]


# ---------------------------------------------------------------- numbers


def test_today_with_forecast_and_gap_are_computed_server_side():
    result, _body, _ = _brief(_identity("CORP-T3"))
    team = json.loads(result["content"])["teams"][0]
    assert team["today_profit"] == 803.0                     # today's /combo day bucket
    assert team["today_cover_forecast_profit"] == 400.0      # today's /cover-forecast cover_prof
    assert team["today_profit_with_forecast"] == 1203.0
    assert team["avg_prof_day"] == 1500.0
    assert team["gap_vs_avg_day"] == -297.0
    assert team["gap_pct"] == -19.8
    assert team["proj_profit"] == 180_000.0 and team["proj_margin_pct"] == 15.0
    assert team["pending_workdays"] == 7 and team["pct_of_budget"] == 71.0
    assert team["mtd"]["profit"] == 71_000.0 and team["mtd"]["margin_pct"] == 13.92
    assert team["variance_vs_budget"]["profit_var"] == -9_000.0
    assert team["top_losses"][0] == {"customer": "CUST 1", "loss_loads": 1, "loss_profit": -100.0}
    assert len(team["top_losses"]) == 5
    assert team["service"]["pickup"] == {"on_time_pct": 97.0, "late": 3, "orders": 100}
    assert team["service"]["delivery"]["late"] == 5


def test_daily_brief_reads_each_section_with_the_right_params():
    seen: list = []
    _brief(_identity("CORP-T3"), seen=seen)
    by_path = {s["path"].rsplit("ops-portal-overview-t3/", 1)[-1]: s["query"] for s in seen}
    assert by_path["combo"] == {"grain": "day"}
    assert by_path["cover-forecast"] == {"grain": "day"}
    assert by_path["customer-losses"]["limit"] == "5"


def test_avg_zero_makes_the_gap_pct_null():
    result, _body, _ = _brief(_identity("CORP-T4"))
    team = json.loads(result["content"])["teams"][0]
    assert team["avg_prof_day"] == 0.0
    assert team["gap_pct"] is None
    assert team["gap_vs_avg_day"] == team["today_profit_with_forecast"]


@pytest.mark.parametrize("avg", [None, 0, 0.0, -50.0])
def test_gap_pct_is_null_without_a_positive_average(avg):
    gap, pct = gap_vs_avg(100.0, avg)
    assert pct is None
    assert gap == (None if avg is None else 100.0 - avg)


def test_gap_is_null_when_today_is_unknown():
    assert gap_vs_avg(None, 1000.0) == (None, None)


def test_missing_today_bucket_is_null_not_zero():
    raw = {k: v for k, v in _portal_data(1).items()}
    raw["combo"] = {"today": TODAY, "buckets": [{"bucket_start": "2026-10-21", "profit": 1.0}]}
    raw["cover-forecast"] = {"buckets": []}
    snap = build_team_snapshot(1, raw, None)
    assert snap["today_profit"] is None
    assert snap["today_cover_forecast_profit"] == 0.0
    assert snap["today_profit_with_forecast"] is None and snap["gap_vs_avg_day"] is None


def test_one_team_failing_is_isolated():
    result, body, _ = _brief(_identity("Executive"), broken_team=2)
    teams = json.loads(result["content"])["teams"]
    assert [t["team"] for t in teams] == ["TEAM1", "TEAM2", "TEAM3", "TEAM4"]
    assert teams[1] == {"team": "TEAM2", "error": "unavailable"}
    assert "today_profit" in teams[0] and "today_profit" in teams[2]
    assert "corp-t2-ops-kam-portal" not in {r["key"] for r in body["reports_used"]}


def test_service_is_null_without_customer_score_access(monkeypatch):
    real = ai_chat_tools.ToolSession._accessible_reports

    async def without_score(self):
        return {k: v for k, v in (await real(self)).items() if "customer-score" not in k}

    monkeypatch.setattr(ai_chat_tools.ToolSession, "_accessible_reports", without_score)
    result, body, _ = _brief(_identity("CORP-T1"))
    team = json.loads(result["content"])["teams"][0]
    assert team["service"] is None
    assert {r["key"] for r in body["reports_used"]} == {"corp-t1-ops-kam-portal"}


def test_result_fits_its_own_cap_untruncated_for_four_teams():
    result, _body, _ = _brief(_identity("Executive"))
    assert "truncated" not in result["content"]
    assert len(result["content"]) < DAILY_BRIEF_MAX_CHARS // 2
    assert DAILY_BRIEF_MAX_CHARS == 16000 > ai_chat_tools.TOOL_RESULT_MAX_CHARS


def test_glossary_rides_in_the_result():
    result, _body, _ = _brief(_identity("CORP-T1"))
    glossary = json.loads(result["content"])["glossary"]
    assert "avg_prof_day" in glossary and "today_profit_with_forecast" in glossary


# ---------------------------------------------------------------- freshness


def test_data_as_of_is_the_oldest_source_across_the_brief():
    _result, body, _ = _brief(_identity("CORP-T1"))
    # portal: production 07:30, budget 06:00 · score: 05:00 (last_pu is an event, ignored)
    assert body["data_as_of"] == "2026-10-22T05:00:00"


def test_per_source_freshness_is_in_each_team():
    result, _body, _ = _brief(_identity("CORP-T1"))
    fresh = json.loads(result["content"])["teams"][0]["freshness"]
    assert fresh == {"Production": "2026-10-22T07:30:00", "Budget": "2026-10-22T06:00:00",
                     "Customer Score": "2026-10-22T05:00:00"}


# ---------------------------------------------------------------- mode


@pytest.mark.parametrize("mode", ["daily", "DAILY_BRIEF", "", 1, "summary"])
def test_unknown_mode_is_422(monkeypatch, mode):
    monkeypatch.setattr(ai_chat_agent, "create_message", _Script(_resp(_text("x"))))
    client = TestClient(_build_app([]))
    resp = client.post("/api/custom/ai-chat/ask", json={"message": "hi", "mode": mode},
                       headers=_auth(_identity("Executive")))
    assert resp.status_code == 422


def test_null_or_absent_mode_is_accepted(monkeypatch):
    client = TestClient(_build_app([]))
    for body in ({"message": "hi"}, {"message": "hi", "mode": None}):
        monkeypatch.setattr(ai_chat_agent, "create_message", _Script(_resp(_text("x"))))
        assert client.post("/api/custom/ai-chat/ask", json=body,
                           headers=_auth(_identity("Executive"))).status_code == 200


def test_daily_brief_mode_injects_the_prompt_block():
    _result, _body, script = _brief(_identity("Executive"), mode="daily_brief")
    system = script.calls[0]["system"]
    assert ai_chat_agent.DAILY_BRIEF_PROMPT in system
    assert "**Summary**" in ai_chat_agent.DAILY_BRIEF_PROMPT
    assert "daily_brief" in ai_chat_agent.DAILY_BRIEF_PROMPT
    # Every model call of the question carries it, the forced final one included.
    assert all(ai_chat_agent.DAILY_BRIEF_PROMPT in c["system"] for c in script.calls)


def test_normal_mode_has_no_brief_block_but_has_the_glossary():
    _result, _body, script = _brief(_identity("Executive"))
    system = script.calls[0]["system"]
    assert ai_chat_agent.DAILY_BRIEF_PROMPT not in system
    assert "avg_prof_day" in system and "proj_profit" in system
    assert "Today's profit with forecast" in system


# ---------------------------------------------------------------- wiring guards


def test_every_path_daily_brief_reads_is_a_live_get_route():
    """A drifted section name would silently make every team 'unavailable'."""
    from app.main import app

    routes = ai_chat_tools.get_route_table(app)
    for n in range(1, 5):
        for path in ai_chat_daily_brief.portal_paths(n) + ai_chat_daily_brief.score_paths(n):
            assert path in routes, path


def test_daily_brief_params_are_declared_by_the_live_routes():
    from app.main import app

    routes = ai_chat_tools.get_route_table(app)
    for path, params in ai_chat_daily_brief.declared_params(1):
        assert set(params) <= set(routes[path].params), path


# ---------------------------------------------------------------- scoreboard (bot card)


def test_response_carries_the_scoreboard_copied_from_the_snapshot():
    result, body, _ = _brief(_identity("Executive"), mode="daily_brief")
    board = body["brief"]
    snapshot = {t["team"]: t for t in json.loads(result["content"])["teams"]}
    assert [r["team"] for r in board["teams"]] == ["TEAM1", "TEAM2", "TEAM3", "TEAM4"]
    for row in board["teams"]:
        snap = snapshot[row["team"]]
        # Every number is the snapshot's own — the card never computes.
        for key in ("today_profit_with_forecast", "avg_prof_day", "gap_vs_avg_day", "gap_pct",
                    "pct_of_budget", "proj_profit", "proj_margin_pct"):
            assert row[key] == snap[key], (row["team"], key)
        assert row["loss_loads"] == snap["mtd"]["loss_loads"]
        assert row["profit_loss"] == snap["mtd"]["profit_loss"]
    assert board["not_shown"] == [] and board["unavailable"] == []


def test_scoreboard_respects_access_and_failures():
    _result, body, _ = _brief(_identity("CORP-T3"))
    assert [r["team"] for r in body["brief"]["teams"]] == ["TEAM3"]
    assert body["brief"]["not_shown"] == ["TEAM1", "TEAM2", "TEAM4"]
    _result, body, _ = _brief(_identity("Executive"), broken_team=2)
    assert "TEAM2" in body["brief"]["unavailable"]
    assert "TEAM2" not in [r["team"] for r in body["brief"]["teams"]]


def test_no_scoreboard_when_the_brief_tool_did_not_run(monkeypatch):
    monkeypatch.setattr(ai_chat_agent, "create_message", _Script(_resp(_text("x"))))
    client = TestClient(_build_app([]))
    resp = client.post("/api/custom/ai-chat/ask", json={"message": "hi"}, headers=_auth(_identity("Executive")))
    assert resp.json()["brief"] is None


def test_brief_prompt_puts_summary_first_and_bans_raw_field_names():
    p = ai_chat_agent.DAILY_BRIEF_PROMPT
    assert p.index("**Summary**") < p.index("### TEAMn")
    assert "snake_case" in p and "$" in p
    assert "Do not write a data-freshness line" in p
