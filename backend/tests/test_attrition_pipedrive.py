"""Attrition → Pipedrive reactivation deals (services/attrition_pipedrive, 2026-10-22).

Layers:
  1. config  — routing exactly as the request PDF (KAM, Sales, To/CC); TEAM5 skipped
  2. plan    — the 29–63 create window and the 90–96 reassign window, edges included
  3. mail    — the notice text verbatim, escaped
  4. client  — fail-closed resolution, McLeod-code match verified on the record,
               the token never in an error
  5. runner  — act once, adopt an existing deal, mail retry without a second
               write, one customer's failure isolated and the run still raising,
               dry run writes nothing, stale feed refused
  6. wiring  — main.py registers both jobs, the DDL and the router
  7. live    — every statement PREPAREs (gold + hub), skipped offline
"""
from __future__ import annotations

import asyncio
import os
import re
import types
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import httpx
import pytest

from app.services.attrition_pipedrive import candidates, mail, pipedrive, runner
from app.services.attrition_pipedrive import config as cfg
from app.services.attrition_pipedrive.candidates import Candidate
from app.services.attrition_pipedrive.pipedrive import Deal, Placement

CST = ZoneInfo("America/Chicago")
NOW = datetime(2026, 10, 23, 4, 0, tzinfo=CST)
TODAY = NOW.date()
MAIN = Path(__file__).resolve().parents[1] / "app" / "main.py"

USERS = {e: i for i, e in enumerate(cfg.REQUIRED_USER_EMAILS, start=100)}
NAMES = {
    USERS[cfg.JULIO.email]: "Julio Rodriguez", USERS[cfg.RUBEN.email]: "Ruben Rodriguez",
    USERS[cfg.MIGUEL.email]: "Miguel Millan", USERS[cfg.EDUARDO.email]: "Eduardo Valenzuela",
    USERS[cfg.PATRICIO.email]: "Patricio Villarreal", USERS[cfg.SERGIO.email]: "Sergio",
    USERS[cfg.MONICA.email]: "Monica Perez", USERS[cfg.CHRISTIAN.email]: "Christian Mendoza",
    999: "JAMES",
}
PLACEMENT = Placement(
    pipeline_id=5, stage_id=24, users=USERS, user_names=NAMES,
    deal_reactivation_key="react", deal_reactivation_option=152,
    deal_mcleod_key="dmc", org_mcleod_key="omc",
)


def _cand(team="TEAM1", customer="WESTROCK CORONA", days=29, ids=("WESTROCA",)) -> Candidate:
    return Candidate(team=team, customer=customer, last_load_date=TODAY - timedelta(days=days),
                     days_since=days, mcleod_ids=ids)


# ---------------------------------------------------------------------------
# 1. config
# ---------------------------------------------------------------------------

def test_routing_is_the_request_pdf():
    r = cfg.ROUTING
    assert set(r) == {"TEAM1", "TEAM2", "TEAM3", "TEAM4", "TEAM-DFW"}  # no TEAM5
    assert [r[t].kam.name for t in ("TEAM1", "TEAM2", "TEAM3", "TEAM4", "TEAM-DFW")] == [
        "Julio Rodriguez", "Ruben Rodriguez", "Sergio Hidalgo", "Monica Perez", "Christian Mendoza"]
    assert [r[t].sales.name for t in ("TEAM1", "TEAM2", "TEAM3", "TEAM4", "TEAM-DFW")] == [
        "Miguel Millan", "Miguel Millan", "Eduardo Valenzuela", "Eduardo Valenzuela",
        "Patricio Villarreal"]
    u = "@unilinktransportation.com"
    assert r["TEAM1"].notify_to == (f"miguel{u}", f"jrodriguez{u}", f"janaya{u}")
    assert r["TEAM2"].notify_to == (f"miguel{u}", f"lrodriguez{u}", f"janaya{u}")
    assert r["TEAM3"].notify_to == (f"evalenzuela{u}", f"shidalgo{u}", f"janaya{u}")
    assert r["TEAM4"].notify_to == (f"evalenzuela{u}", f"mperezn{u}", f"janaya{u}")
    assert r["TEAM-DFW"].notify_to == (f"pvillarreal{u}", f"ctorres{u}", f"christian{u}")
    for t in r.values():
        assert t.notify_cc == (f"emendoza{u}", f"andy{u}", f"iris{u}")


def test_every_recipient_is_a_company_domain():
    from app.services.allowed_domains import partition_recipients

    for t in cfg.ROUTING.values():
        allowed, blocked = partition_recipients(list(t.notify_to) + list(t.notify_cc))
        assert not blocked and len(allowed) == 6


# ---------------------------------------------------------------------------
# 2. plan
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("days,expected", [
    (28, None), (29, "create"), (63, "create"), (64, None), (89, None),
    (90, "reassign"), (96, "reassign"), (97, None), (248, None),
])
def test_action_windows(days, expected):
    assert runner.action_for(days) == expected


def test_plan_skips_teams_without_routing_visibly():
    due, skipped = runner.plan([_cand(), _cand(team="TEAM5", customer="SEEK EQUIPMENT RENTALS", days=47),
                                _cand(customer="OLD", days=150)])
    assert [(c.customer, k) for c, k in due] == [("WESTROCK CORONA", "create")]
    assert skipped == [{"team": "TEAM5", "customer": "SEEK EQUIPMENT RENTALS", "days_since": 47,
                        "action": "create"}]


# ---------------------------------------------------------------------------
# 3. mail
# ---------------------------------------------------------------------------

def test_notice_text_is_verbatim():
    assert mail.subject_for("PCA ATLANTA SPECIALTY PLANT", "Miguel Millan") == (
        "PCA ATLANTA SPECIALTY PLANT has been reassigned to Miguel Millan")
    text = re.sub(r"<[^>]+>", "", mail.body_for("PCA ATLANTA SPECIALTY PLANT", "Miguel Millan"))
    assert text == (
        "Team,"
        "The deal PCA ATLANTA SPECIALTY PLANT has reached 90 days without any loads and has been "
        "reassigned to Miguel Millan."
        "Miguel Millan, please meet with the KAM to gather all relevant information before "
        "reaching out to the customer."
        "Thank you,"
    )


def test_notice_escapes_names():
    assert "<script>" not in mail.body_for("<script>x</script>", "A & B")
    assert "A &amp; B" in mail.body_for("x", "A & B")


# ---------------------------------------------------------------------------
# 4. client
# ---------------------------------------------------------------------------

def _pd_app(routes: dict[tuple[str, str], object], calls: list):
    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path.split("/api/", 1)[1]
        calls.append((request.method, path, dict(request.url.params), request.content))
        data = routes.get((request.method, path))
        if callable(data):
            data = data(request)
        if data is None:
            return httpx.Response(404, json={"success": False, "error": "not found"})
        return httpx.Response(200, json={"success": True, "data": data})
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


def _resolve_routes(stage="Re-OnHold"):
    return {
        ("GET", "v1/pipelines"): [{"id": 1, "name": "DEALS"}, {"id": 5, "name": "REACTIVATION"}],
        ("GET", "v1/stages"): [{"id": 24, "name": stage}, {"id": 25, "name": "Re-Lead"}],
        ("GET", "v1/users"): [{"id": i, "name": NAMES.get(i, ""), "email": e, "active_flag": True}
                              for e, i in USERS.items()],
        ("GET", "v1/dealFields"): [
            {"key": "react", "name": "Is Deal Reactivation?",
             "options": [{"id": 152, "label": "Reactivation"}, {"id": 153, "label": "New Deal"}]},
            {"key": "dmc", "name": "ID_McLeod"},
        ],
        ("GET", "v1/organizationFields"): [{"key": "omc", "name": "ID_McLeod"}],
    }


def test_resolve_by_name():
    calls: list = []
    client = pipedrive.PipedriveClient("acme", "SECRET-TOKEN", _pd_app(_resolve_routes(), calls))
    p = asyncio.run(client.resolve())
    assert (p.pipeline_id, p.stage_id, p.deal_reactivation_option) == (5, 24, 152)
    assert p.users == USERS and p.org_mcleod_key == "omc"


def test_resolve_fails_closed_on_a_renamed_stage():
    client = pipedrive.PipedriveClient("acme", "t", _pd_app(_resolve_routes(stage="On Hold"), []))
    with pytest.raises(pipedrive.PipedriveConfigError, match="Re-OnHold"):
        asyncio.run(client.resolve())


def test_resolve_fails_closed_on_an_inactive_user():
    routes = _resolve_routes()
    routes[("GET", "v1/users")] = [u for u in routes[("GET", "v1/users")]
                                   if u["email"] != cfg.MIGUEL.email]
    client = pipedrive.PipedriveClient("acme", "t", _pd_app(routes, []))
    with pytest.raises(pipedrive.PipedriveConfigError, match="miguel@"):
        asyncio.run(client.resolve())


def test_error_never_carries_the_token():
    client = pipedrive.PipedriveClient("acme", "SECRET-TOKEN", _pd_app({}, []))
    with pytest.raises(pipedrive.PipedriveError) as exc:
        asyncio.run(client.resolve())
    assert "SECRET-TOKEN" not in str(exc.value)


def test_find_org_verifies_the_mcleod_code_then_falls_back_to_exact_name():
    def search(req):
        if req.url.params["fields"] == "custom_fields":
            return {"items": [{"item": {"id": 7, "name": "Other"}}]}
        return {"items": [{"item": {"id": 9, "name": "Westrock Corona."}},
                          {"item": {"id": 3, "name": "WestRock Corona"}},
                          {"item": {"id": 4, "name": "WestRock Corona Mill"}}]}
    routes = {("GET", "v2/organizations/search"): search,
              # the search hit's McLeod field is a DIFFERENT code → not a match
              ("GET", "v2/organizations/7"): {"id": 7, "custom_fields": {"omc": "WESTROCX"}}}
    client = pipedrive.PipedriveClient("acme", "t", _pd_app(routes, []))
    m = asyncio.run(client.find_org(PLACEMENT, "WESTROCK CORONA", ("WESTROCA",)))
    assert (m.org_id, m.how) == (3, "name")


def test_find_org_by_mcleod_code():
    routes = {("GET", "v2/organizations/search"): {"items": [{"item": {"id": 5103}}]},
              ("GET", "v2/organizations/5103"): {"id": 5103, "custom_fields": {"omc": "westroca"}}}
    client = pipedrive.PipedriveClient("acme", "t", _pd_app(routes, []))
    m = asyncio.run(client.find_org(PLACEMENT, "anything", ("WESTROCA",)))
    assert (m.org_id, m.how, m.mcleod_on_org) == (5103, "mcleod", "westroca")


def test_create_deal_sends_pipeline_stage_owner_and_fields():
    import json

    calls: list = []
    routes = {("POST", "v2/deals"): {"id": 77, "title": "WESTROCK CORONA", "owner_id": 101,
                                     "org_id": 3, "pipeline_id": 5, "status": "open"}}
    client = pipedrive.PipedriveClient("acme", "t", _pd_app(routes, calls))
    deal = asyncio.run(client.create_deal(PLACEMENT, title="WESTROCK CORONA", org_id=3,
                                          owner_id=101, mcleod_id="WESTROCA"))
    body = json.loads(calls[0][3])
    assert deal.id == 77
    assert body == {"title": "WESTROCK CORONA", "org_id": 3, "owner_id": 101, "pipeline_id": 5,
                    "stage_id": 24, "custom_fields": {"react": 152, "dmc": "WESTROCA"}}


# ---------------------------------------------------------------------------
# 5. runner
# ---------------------------------------------------------------------------

class _Hub:
    """The two log tables, enough to honour every statement the runner sends."""

    def __init__(self):
        self.rows: dict[tuple, dict] = {}
        self.runs: list[dict] = []

    async def fetchval(self, sql, *a):
        if sql == runner.RUN_START_SQL:
            self.runs.append({"run_date": a[0], "mode": a[1], "status": "running"})
            return len(self.runs)
        if sql == runner.CLAIM_SQL:
            key = a[:4]
            row = self.rows.get(key)
            if row and row["status"] not in ("failed", "held"):
                return None
            self.rows[key] = {"team": a[0], "customer": a[1], "last_load_date": a[2],
                              "action": a[3], "status": "running", "deal_id": None,
                              "deal_title": None}
            return a[3]
        raise AssertionError(sql)

    async def fetchrow(self, sql, *a):
        assert sql == runner.CLAIM_MAIL_SQL
        row = self.rows.get((*a, "reassign"))
        if not row or row["status"] != "mail_failed":
            return None
        row["status"] = "running"
        return row

    async def fetch(self, sql, *a):
        assert sql == runner.EXISTING_SQL
        return [dict(r) for r in self.rows.values() if r["last_load_date"] >= a[0]]

    async def execute(self, sql, *a):
        if sql == runner.RUN_FINISH_SQL:
            self.runs[a[0] - 1].update(status=a[1], error=a[3])
            return
        if sql == runner.STUCK_SQL:
            row = self.rows[a[:4]]
            row.update(org_id=a[4] or row.get("org_id"), deal_id=a[5] or row.get("deal_id"),
                       error=a[6])
            return
        assert sql == runner.FINISH_SQL
        row = self.rows[a[:4]]
        row.update(status=a[4])
        if a[5] is not None:
            row["org_id"] = a[5]
        if a[6] is not None:
            row["deal_id"] = a[6]
        if a[7] is not None:
            row["deal_title"] = a[7]


class _Gold:
    def __init__(self, cands: list[Candidate], as_of: datetime | None = None):
        self.cands, self.as_of = cands, as_of  # None = fresh relative to the run's clock
        self.now = NOW

    async def fetchval(self, sql, *a):
        assert sql == candidates.FRESHNESS_SQL
        return self.as_of or self.now.replace(tzinfo=None) - timedelta(minutes=20)

    async def fetch(self, sql, *a):
        return [{"team": c.team, "customer": c.customer, "last_load_date": c.last_load_date,
                 "mcleod_ids": list(c.mcleod_ids)} for c in self.cands]


class _FakePd:
    def __init__(self, orgs=None, open_deals=None, fail_on=(), write_error=None):
        self.orgs = dict(orgs or {})              # customer → org id
        self.open_deals = dict(open_deals or {})  # org id → Deal
        self.deals: dict[int, Deal] = {d.id: d for d in self.open_deals.values()}
        self.writes: list[tuple] = []
        self.fail_on = set(fail_on)
        self.write_error = write_error  # {"deal"|"owner": PipedriveError} raised AFTER/BEFORE the write
        self.searches = 0
        self.matches: dict = {}  # customer → OrgMatch override (similar / ambiguous)
        self._next = 1000

    async def resolve(self):
        return PLACEMENT

    async def aclose(self):
        pass

    async def find_org(self, p, customer, ids):
        if customer in self.fail_on:
            raise pipedrive.PipedriveError("boom", 500)
        self.searches += 1
        if customer in self.matches:
            return self.matches[customer]
        org = self.orgs.get(customer)
        return pipedrive.OrgMatch(org, "name" if org else "none")

    async def set_org_mcleod(self, p, org_id, code):
        self.writes.append(("mcleod", org_id, code))

    async def create_org(self, p, name, owner_id, mcleod_id):
        self._next += 1
        self.writes.append(("org", name, owner_id, mcleod_id))
        self.orgs[name] = self._next
        return self._next

    async def open_reactivation_deal(self, p, org_id):
        return self.open_deals.get(org_id)

    async def get_deal(self, deal_id):
        return self.deals.get(deal_id)

    async def create_deal(self, p, *, title, org_id, owner_id, mcleod_id):
        err = (self.write_error or {}).pop("deal", None)
        if err is not None and err.status and err.status < 500:
            raise err  # rejected: nothing written
        self._next += 1
        d = Deal(self._next, title, owner_id, org_id, 5, "open")
        self.writes.append(("deal", title, owner_id, org_id, mcleod_id))
        self.deals[d.id] = self.open_deals[org_id] = d
        if err is not None:
            raise err  # timeout / 5xx: written, but the caller cannot know
        return d

    async def set_owner(self, deal_id, owner_id):
        old = self.deals[deal_id]
        d = Deal(old.id, old.title, owner_id, old.org_id, 5, "open")
        self.writes.append(("owner", deal_id, owner_id))
        self.deals[deal_id] = self.open_deals[old.org_id] = d
        err = (self.write_error or {}).pop("owner", None)
        if err is not None:
            raise err
        return d


@pytest.fixture
def env(monkeypatch):
    sent: list[dict] = []
    state = types.SimpleNamespace(pd=_FakePd(), sent=sent, mail_ok=True)

    async def fake_send_mail(**kw):
        sent.append(kw)
        return {"sent": True} if state.mail_ok else {"sent": False, "reason": "token_failed"}

    monkeypatch.setattr(runner, "send_mail", fake_send_mail)
    monkeypatch.setattr(runner, "PipedriveClient", lambda *a, **k: state.pd)
    return state


def _app(hub, gold):
    return types.SimpleNamespace(state=types.SimpleNamespace(pool=hub, savings_pool=gold))


def _run(hub, gold, live=True, record=True, now=NOW):
    gold.now = now
    return asyncio.run(runner.run_daily(_app(hub, gold), live=live, record=record, now=now))


def test_create_makes_org_and_deal_owned_by_the_kam_once(env):
    hub, gold = _Hub(), _Gold([_cand(team="TEAM-DFW", customer="AZTECA MILLING RACKS", ids=("AZTEMIRA",))])
    res = _run(hub, gold)
    assert [o.status for o in res.outcomes] == ["created"]
    kam = USERS[cfg.CHRISTIAN.email]
    assert env.pd.writes == [("org", "AZTECA MILLING RACKS", kam, "AZTEMIRA"),
                             ("deal", "AZTECA MILLING RACKS", kam, 1001, "AZTEMIRA")]
    again = _run(hub, gold)
    assert [o.status for o in again.outcomes] == ["done_before"] and len(env.pd.writes) == 2
    assert [r["status"] for r in hub.runs] == ["ok", "ok"] and env.sent == []


def test_an_existing_open_reactivation_deal_is_adopted_not_duplicated(env):
    env.pd = _FakePd(orgs={"COPPEL SA DE CV": 5068},
                     open_deals={5068: Deal(9148, "Coppel SA de CV", 999, 5068, 5, "open")})
    res = _run(_Hub(), _Gold([_cand(team="TEAM2", customer="COPPEL SA DE CV", days=40)]))
    o = res.outcomes[0]
    assert (o.status, o.deal_id, o.owner) == ("adopted", 9148, "JAMES") and env.pd.writes == []


def test_reassign_moves_the_tracked_deal_to_sales_and_mails_the_team(env):
    hub = _Hub()
    c29 = _cand(team="TEAM2", customer="PCA ATLANTA SPECIALTY PLANT", days=29, ids=("PCAATLGA",))
    _run(hub, _Gold([c29]))
    deal_id = max(env.pd.deals)
    # same lapse (same last load), 61 days later
    res = _run(hub, _Gold([c29]), now=NOW + timedelta(days=61))
    assert res.outcomes[0].days_since == 90
    assert [o.status for o in res.outcomes] == ["reassigned"]
    assert env.pd.writes[-1] == ("owner", deal_id, USERS[cfg.MIGUEL.email])
    (m,) = env.sent
    assert m["subject"] == "PCA ATLANTA SPECIALTY PLANT has been reassigned to Miguel Millan"
    assert m["to"] == list(cfg.ROUTING["TEAM2"].notify_to)
    assert m["cc"] == list(cfg.ROUTING["TEAM2"].notify_cc)


def test_reassign_uses_a_hand_made_deal_and_keeps_its_title(env):
    env.pd = _FakePd(orgs={"PCA ATLANTA SPECIALTY PLANT": 5054},
                     open_deals={5054: Deal(9001, "PCA Atlanta Specialty", USERS[cfg.RUBEN.email],
                                            5054, 5, "open")})
    res = _run(_Hub(), _Gold([_cand(team="TEAM2", customer="PCA ATLANTA SPECIALTY PLANT", days=90)]))
    assert res.outcomes[0].status == "reassigned"
    assert env.pd.writes == [("owner", 9001, USERS[cfg.MIGUEL.email])]
    assert env.sent[0]["subject"] == "PCA Atlanta Specialty has been reassigned to Miguel Millan"


def test_a_deal_already_owned_by_sales_is_not_touched_or_mailed(env):
    env.pd = _FakePd(orgs={"X": 1}, open_deals={1: Deal(5, "X", USERS[cfg.EDUARDO.email], 1, 5, "open")})
    res = _run(_Hub(), _Gold([_cand(team="TEAM3", customer="X", days=91)]))
    assert res.outcomes[0].status == "already_sales" and env.pd.writes == [] and env.sent == []


def test_no_deal_at_90_days_creates_one_owned_by_sales(env):
    res = _run(_Hub(), _Gold([_cand(team="TEAM4", customer="NEW CO", days=92, ids=())]))
    assert res.outcomes[0].status == "reassigned"
    sales = USERS[cfg.EDUARDO.email]
    assert env.pd.writes == [("org", "NEW CO", sales, None), ("deal", "NEW CO", sales, 1001, None)]
    assert len(env.sent) == 1


def test_a_failed_notice_is_retried_without_a_second_owner_change(env):
    env.pd = _FakePd(orgs={"X": 1}, open_deals={1: Deal(5, "X", USERS[cfg.JULIO.email], 1, 5, "open")})
    env.mail_ok = False
    hub, gold = _Hub(), _Gold([_cand(team="TEAM1", customer="X", days=90)])
    with pytest.raises(runner.RunFailed):
        _run(hub, gold)
    assert hub.runs[-1]["status"] == "failed" and len(env.pd.writes) == 1
    env.mail_ok = True
    res = _run(hub, gold)
    assert [o.status for o in res.outcomes] == ["reassigned"]
    assert len(env.pd.writes) == 1 and len(env.sent) == 2


def test_one_customer_failing_does_not_stop_the_next_and_the_run_raises(env):
    env.pd = _FakePd(fail_on={"BAD"})
    hub = _Hub()
    with pytest.raises(runner.RunFailed) as exc:
        _run(hub, _Gold([_cand(customer="BAD"), _cand(customer="GOOD")]))
    statuses = {o.customer: o.status for o in exc.value.result.outcomes}
    assert statuses == {"BAD": "failed", "GOOD": "created"}
    # nothing was written for BAD → the next run retakes it
    env.pd.fail_on.clear()
    res = _run(hub, _Gold([_cand(customer="BAD"), _cand(customer="GOOD")]))
    assert {o.customer: o.status for o in res.outcomes} == {"BAD": "created", "GOOD": "done_before"}


def test_a_stuck_claim_is_reported_and_never_retaken(env):
    hub = _Hub()
    c = _cand()
    hub.rows[(c.team, c.customer, c.last_load_date, "create")] = {
        "team": c.team, "customer": c.customer, "last_load_date": c.last_load_date,
        "action": "create", "status": "running", "deal_id": None}
    with pytest.raises(runner.RunFailed, match="stuck"):
        _run(hub, _Gold([c]))
    assert env.pd.writes == []


def test_dry_run_writes_nothing(env):
    hub = _Hub()
    res = _run(hub, _Gold([_cand(), _cand(team="TEAM3", customer="Y", days=90)]), live=False,
               record=False)
    assert [o.status for o in res.outcomes] == ["would_create", "would_reassign"]
    assert env.pd.writes == [] and env.sent == [] and hub.rows == {} and hub.runs == []


def test_a_stale_feed_is_refused_before_pipedrive_is_touched(env):
    hub = _Hub()
    gold = _Gold([_cand()], as_of=NOW.replace(tzinfo=None) - timedelta(hours=7))
    with pytest.raises(candidates.StaleFeedError):
        _run(hub, gold)
    assert env.pd.writes == [] and hub.runs[-1]["status"] == "failed"


def test_nothing_due_never_calls_pipedrive(env, monkeypatch):
    monkeypatch.setattr(runner, "PipedriveClient", lambda *a, **k: pytest.fail("called"))
    res = _run(_Hub(), _Gold([_cand(days=10), _cand(customer="Z", days=150)]))
    assert res.outcomes == []


def test_claim_sql_retakes_only_failed_rows():
    assert "WHERE l.status IN ('failed', 'held')" in runner.CLAIM_SQL
    assert "'running'" not in runner.CLAIM_SQL.split("WHERE", 1)[1]  # a stuck row is never retaken
    assert "status = 'mail_failed'" in runner.CLAIM_MAIL_SQL


# ---------------------------------------------------------------------------
# 6. wiring
# ---------------------------------------------------------------------------

def test_main_registers_jobs_ddl_and_router():
    src = MAIN.read_text()
    for job in ("daily_attrition_pipedrive", "daily_attrition_pipedrive_watch"):
        assert f'id="{job}"' in src and f'"{job}":' in src  # add_job + EXPECTED_JOBS
    assert 'CronTrigger(hour=4, minute=0, timezone="America/Chicago")' in src
    assert "attrition_pipedrive.runner import LOG_DDL" in src
    assert "app.include_router(attrition_pipedrive.router" in src


def test_scheduled_wrapper_reraises():
    src = MAIN.read_text()
    body = src.split("async def _scheduled_attrition_pipedrive():", 1)[1].split("\nasync def ", 1)[0]
    assert "\n        raise\n" in body


def test_routes_are_admin_only_and_unreachable_by_the_assistant():
    from app.main import app
    from app.services import ai_chat_tools

    paths = {r.path for r in app.routes}
    assert {"/api/custom/attrition-pipedrive/preview", "/api/custom/attrition-pipedrive/run",
            "/api/custom/attrition-pipedrive/log"} <= paths
    assert "attrition-pipedrive" not in ai_chat_tools.CATALOG_KEYS
    assert "attrition-pipedrive" not in ai_chat_tools.REPORT_ROUTE_PREFIX.values()


def test_live_flag_defaults_off():
    from app.config import Settings

    assert Settings.model_fields["ATTRITION_PIPEDRIVE_LIVE"].default is False


# ---------------------------------------------------------------------------
# 7. live
# ---------------------------------------------------------------------------

_GOLD = os.environ.get("SAVINGS_DATABASE_URL", "")
_HUB = os.environ.get("DATABASE_URL", "")


def _connect(url):
    import asyncpg

    return asyncpg.connect(re.sub(r"[?&]sslmode=\w+", "", url), ssl="require")


@pytest.mark.skipif(not _GOLD, reason="SAVINGS_DATABASE_URL not set — offline run")
def test_live_gold_statements_parse():
    """§81: PREPARE exactly what production runs."""
    async def run():
        conn = await _connect(_GOLD)
        try:
            await conn.prepare(candidates.FRESHNESS_SQL)
            sql, _ = candidates.candidates_sql()
            await conn.prepare(sql)
        finally:
            await conn.close()
    asyncio.run(run())


@pytest.mark.skipif(not _HUB, reason="DATABASE_URL not set — offline run")
def test_live_hub_statements_parse_inside_a_rolled_back_ddl():
    async def run():
        conn = await _connect(_HUB)
        tx = conn.transaction()
        await tx.start()
        try:
            await conn.execute(runner.LOG_DDL)
            for sql in (runner.CLAIM_SQL, runner.CLAIM_MAIL_SQL, runner.FINISH_SQL, runner.STUCK_SQL,
                        runner.EXISTING_SQL, runner.RUN_START_SQL, runner.RUN_FINISH_SQL,
                        runner.LOG_SQL, runner.RUNS_SQL, runner.TODAY_RUNS_SQL):
                await conn.prepare(sql)
        finally:
            await tx.rollback()
            await conn.close()
    asyncio.run(run())


# ---------------------------------------------------------------------------
# review fixes 2026-10-22
# ---------------------------------------------------------------------------

def test_an_owner_change_that_times_out_is_stuck_never_silently_already_sales(env):
    """The PATCH landed but the response timed out. Retaking it would find the deal with
    Sales, record 'already_sales' and NEVER mail — so it must stay stuck, ids recorded."""
    env.pd = _FakePd(orgs={"X": 1}, open_deals={1: Deal(5, "X", USERS[cfg.JULIO.email], 1, 5, "open")},
                     write_error={"owner": pipedrive.PipedriveError("PATCH /v2/deals/5: ReadTimeout")})
    hub, gold = _Hub(), _Gold([_cand(team="TEAM1", customer="X", days=90)])
    with pytest.raises(runner.RunFailed, match="stuck"):
        _run(hub, gold)
    (row,) = hub.rows.values()
    assert row["status"] == "running" and row["deal_id"] == 5 and env.sent == []
    with pytest.raises(runner.RunFailed, match="stuck"):
        _run(hub, gold)  # never retaken
    assert len(env.pd.writes) == 1


def test_a_rejected_deal_after_a_new_org_reuses_that_org_on_the_retake(env):
    env.pd = _FakePd(write_error={"deal": pipedrive.PipedriveError("POST /v2/deals: HTTP 400", 400)})
    hub, gold = _Hub(), _Gold([_cand(customer="NEWCO", ids=("NEWCOTX",))])
    with pytest.raises(runner.RunFailed):
        _run(hub, gold)
    (row,) = hub.rows.values()
    assert row["status"] == "failed" and row["org_id"] == 1001
    env.pd.orgs.clear()  # search index has not caught up
    res = _run(hub, gold)
    assert res.outcomes[0].status == "created"
    assert [w[0] for w in env.pd.writes] == ["org", "deal"]  # ONE org, ever


def test_a_customer_on_two_teams_is_acted_on_once_under_its_latest_team(env):
    old = _cand(team="TEAM1", customer="DUAL CO", days=40)
    new = _cand(team="TEAM3", customer="Dual Co", days=30)
    due, _ = runner.plan([old, new])
    assert [(c.team, k) for c, k in due] == [("TEAM3", "create")]
    # moved teams and still trading under the new one → not lapsed at all
    due, _ = runner.plan([old, _cand(team="TEAM2", customer="DUAL CO", days=3)])
    assert due == []


def test_a_database_error_on_one_customer_does_not_stop_the_rest(env):
    class _Flaky(_Hub):
        async def fetchval(self, sql, *a):
            if sql == runner.CLAIM_SQL and a[1] == "BAD":
                raise ConnectionError("hub dropped")
            return await super().fetchval(sql, *a)

    with pytest.raises(runner.RunFailed) as exc:
        _run(_Flaky(), _Gold([_cand(customer="BAD"), _cand(customer="GOOD")]))
    assert {o.customer: o.status for o in exc.value.result.outcomes} == {"BAD": "error",
                                                                         "GOOD": "created"}


def test_a_pipedrive_error_in_the_preview_is_isolated_per_customer(env):
    env.pd = _FakePd(fail_on={"BAD"})
    with pytest.raises(runner.RunFailed) as exc:
        _run(_Hub(), _Gold([_cand(customer="BAD"), _cand(customer="GOOD")]), live=False, record=False)
    assert {o.customer: o.status for o in exc.value.result.outcomes} == {"BAD": "error",
                                                                         "GOOD": "would_create"}


def test_the_token_travels_in_a_header_never_the_url():
    calls: list = []
    seen: list = []

    def handler(request):
        seen.append((str(request.url), request.headers.get("x-api-token")))
        return httpx.Response(200, json={"success": True, "data": []})

    client = pipedrive.PipedriveClient(
        "acme", "SECRET-TOKEN", httpx.AsyncClient(transport=httpx.MockTransport(handler)))
    asyncio.run(client._request("GET", "v1", "pipelines"))
    assert seen == [("https://acme.pipedrive.com/api/v1/pipelines", "SECRET-TOKEN")]
    assert not calls


def test_a_429_is_retried_after_retry_after_then_succeeds(monkeypatch):
    waits: list = []

    async def no_sleep(sec):
        waits.append(sec)

    monkeypatch.setattr(pipedrive.asyncio, "sleep", no_sleep)
    hits = {"n": 0}

    def handler(request):
        hits["n"] += 1
        if hits["n"] <= 2:
            return httpx.Response(429, headers={"retry-after": "3"}, json={"success": False})
        return httpx.Response(200, json={"success": True, "data": {"items": []}})

    client = pipedrive.PipedriveClient("acme", "t", httpx.AsyncClient(transport=httpx.MockTransport(handler)))
    assert asyncio.run(client.find_org(PLACEMENT, "X", ())).how == "none"
    assert waits == [3.0, 3.0] and hits["n"] == 3


def test_a_persistent_429_surfaces_as_a_failure_after_bounded_retries(monkeypatch):
    async def no_sleep(sec):
        pass

    monkeypatch.setattr(pipedrive.asyncio, "sleep", no_sleep)
    calls = {"n": 0}

    def handler(request):
        calls["n"] += 1
        return httpx.Response(429, json={"success": False})

    client = pipedrive.PipedriveClient("acme", "t", httpx.AsyncClient(transport=httpx.MockTransport(handler)))
    with pytest.raises(pipedrive.PipedriveError) as exc:
        asyncio.run(client.find_org(PLACEMENT, "X", ()))
    assert exc.value.status == 429 and calls["n"] == pipedrive.RATE_LIMIT_RETRIES + 1


# ---------------------------------------------------------------------------
# similar organizations (operator rule 2026-10-22: attach to ONE similar, hold on several)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("a,b,similar", [
    ("AZTECA MILLING RACKS", "Azteca Milling", True),
    ("PCA PEARL MS", "PCA PEARL", True),
    ("MAGNOLIA BRUSH MFRS. LTD", "Magnolia Brush Manufacturers", True),
    ("INDUSTRIAS METALICAS LOZANO, S.A. DE C.V", "Industrias Metalicas Lozano", True),
    ("PCA AKRON", "PCA ATLANTA SPECIALTY PLANT", False),   # one shared token = a brand
    ("PCA DALLAS FULL LINE", "PCA Dallas Corrugated", False),
    ("SEEK", "Seek Equipment Rentals", False),            # < 2 significant tokens
])
def test_similar_names(a, b, similar):
    assert pipedrive.is_similar(a, b) is similar


def _search_client(similar_items, mcleod_by_id):
    def search(req):
        if req.url.params["exact_match"] == "true":
            return {"items": []}
        return {"items": [{"item": {"id": i, "name": n}} for i, n in similar_items]}
    routes = {("GET", "v2/organizations/search"): search}
    for oid, code in mcleod_by_id.items():
        routes[("GET", f"v2/organizations/{oid}")] = {"id": oid, "custom_fields": {"omc": code}}
    return pipedrive.PipedriveClient("acme", "t", _pd_app(routes, []))


def test_find_org_one_similar():
    client = _search_client([(1278, "Azteca Milling"), (7, "Azteca Foods")], {1278: None})
    m = asyncio.run(client.find_org(PLACEMENT, "AZTECA MILLING RACKS", ("AZTECAT1",)))
    assert (m.org_id, m.how, m.candidates) == (1278, "similar", ((1278, "Azteca Milling"),))


def test_find_org_several_similar_is_ambiguous():
    client = _search_client([(5359, "PCA PEARL"), (3096, "PCA Pearl")], {})
    m = asyncio.run(client.find_org(PLACEMENT, "PCA PEARL MS", ()))
    assert (m.org_id, m.how) == (None, "ambiguous") and len(m.candidates) == 2


def test_one_similar_org_gets_the_deal_and_its_empty_mcleod_code(env):
    env.pd.matches["AZTECA MILLING RACKS"] = pipedrive.OrgMatch(
        1278, "similar", ((1278, "Azteca Milling"),), None)
    res = _run(_Hub(), _Gold([_cand(team="TEAM-DFW", customer="AZTECA MILLING RACKS",
                                    ids=("AZTECAT1",))]))
    kam = USERS[cfg.CHRISTIAN.email]
    assert res.outcomes[0].status == "created" and "Azteca Milling" in res.outcomes[0].note
    assert env.pd.writes == [("mcleod", 1278, "AZTECAT1"),
                             ("deal", "AZTECA MILLING RACKS", kam, 1278, "AZTECAT1")]


def test_a_similar_org_with_its_own_mcleod_code_is_not_overwritten(env):
    env.pd.matches["X CO"] = pipedrive.OrgMatch(9, "similar", ((9, "X Co Inc"),), "OTHERCOD")
    _run(_Hub(), _Gold([_cand(customer="X CO", ids=("XCOTX",))]))
    assert [w[0] for w in env.pd.writes] == ["deal"]


def test_several_similar_orgs_hold_write_nothing_notify_and_retry(env, monkeypatch):
    alerts: list = []

    async def fake_alert(subject, detail):
        alerts.append((subject, detail))
        return {"sent": True}

    monkeypatch.setattr(runner, "send_alert", fake_alert)
    env.pd.matches["PCA PEARL MS"] = pipedrive.OrgMatch(
        None, "ambiguous", ((3096, "PCA Pearl"), (5359, "PCA PEARL")))
    hub, gold = _Hub(), _Gold([_cand(team="TEAM2", customer="PCA PEARL MS", ids=("PCAPEAMS",))])
    res = _run(hub, gold)  # not a failure
    assert res.outcomes[0].status == "held" and env.pd.writes == []
    (subject, detail), = alerts
    assert "PCA PEARL MS" in detail and "PCAPEAMS" in detail and "(5359)" in detail
    # a human sets ID_McLeod on 5359 → the next run matches by code and creates the deal
    env.pd.matches["PCA PEARL MS"] = pipedrive.OrgMatch(5359, "mcleod", (), "PCAPEAMS")
    res = _run(hub, gold)
    assert res.outcomes[0].status == "created" and env.pd.writes[-1][3] == 5359


def test_dry_run_reports_a_hold_without_mailing(env, monkeypatch):
    monkeypatch.setattr(runner, "send_alert", lambda *a: pytest.fail("mailed"))
    env.pd.matches["PCA PEARL MS"] = pipedrive.OrgMatch(None, "ambiguous", ((1, "a"), (2, "b")))
    res = _run(_Hub(), _Gold([_cand(team="TEAM2", customer="PCA PEARL MS")]), live=False, record=False)
    assert res.outcomes[0].status == "would_hold"
