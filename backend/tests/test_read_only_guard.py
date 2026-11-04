"""READ_ONLY_EMAILS: a named external user may view Space and write nothing.

Pinned here (through the real `app`, so a router added later is covered too):
- every non-safe route refuses his session with 403 before any handler runs;
- the match is lower-cased and trimmed;
- a normal user, and a read by him, are untouched;
- login and the read-only AI question stay open, and only those;
- identity comes from the proxy-proved header only: without the proxy secret the
  header proves nothing, and require_user answers 401 as before.

No DB: routes reached through `app` fail validation first, or read a fake pool.
"""

from __future__ import annotations

import asyncio
import json

import pytest
from fastapi import Request
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient

from app.config import settings
from app.main import app
from app.routers import read_only_guard
from app.routers.read_only_guard import READ_ONLY_EMAILS, READ_ONLY_EXEMPT_WRITES

SECRET = "proxy-secret-for-tests"
HIS_EMAIL = "bkimbark@unilinktransportation.com"
HIS_ID = "5ea68aac-51a9-4c8c-921c-33cfdf4b2618"
OTHER_ID = "11111111-2222-3333-4444-555555555555"
SAFE = {"GET", "HEAD", "OPTIONS"}
PROBE_NOTE = "/api/custom/booker-performance-scorecard/note"
# {} is a VALID body on this route (it would save an empty note); a list never is.
INVALID_BODY: list = []


class _FakePool:
    async def fetchrow(self, *_a, **_k):
        return None


def _bearer(email: str, sub: str = HIS_ID, roles: list[str] | None = None) -> str:
    return "Bearer " + json.dumps(
        {"sub": sub, "email": email, "roles": roles if roles is not None else []}
    )


def _headers(email: str = HIS_EMAIL, **kw) -> dict[str, str]:
    return {"Authorization": _bearer(email, **kw), "X-Proxy-Secret": SECRET}


@pytest.fixture()
def client(monkeypatch):
    monkeypatch.setattr(settings, "PROXY_SHARED_SECRET", SECRET)
    monkeypatch.setattr(app.state, "pool", _FakePool(), raising=False)
    # No `with`: lifespan would open real pools and start the scheduler.
    return TestClient(app, raise_server_exceptions=False)


def _write_routes() -> list[tuple[str, str]]:
    found = []
    for route in app.routes:
        if isinstance(route, APIRoute):
            found += [(m, route.path) for m in route.methods if m not in SAFE]
    return sorted(found)


def _is_guard_refusal(res) -> bool:
    return res.status_code == 403 and res.json().get("code") == read_only_guard.REFUSAL_CODE


def test_the_list_holds_exactly_this_one_normalised_address():
    assert READ_ONLY_EMAILS == frozenset({HIS_EMAIL})


def test_route_inventory_is_real():
    # A guard test over an empty list passes forever.
    routes = _write_routes()
    assert len(routes) > 60
    assert ("PUT", "/api/custom/bonus-calculator/settings") in routes
    assert ("POST", "/api/custom/bonus-calculator-dfw/lock") in routes
    assert ("PATCH", "/api/user/preferences") in routes
    assert ("POST", "/api/admin/seed") in routes


def _guard_decision(method: str, path: str) -> tuple[bool, int | None]:
    """Run ONLY the guard. Returns (reached the app, refusal status).

    🛑 Never sweep every write route through the real `app`: backend/.env is the
    production database, so a route the guard let through would really execute.
    """

    async def scenario():
        reached = []

        async def call_next(_request):
            reached.append(True)

        headers = _headers(roles=["admin"])
        request = Request(
            {
                "type": "http",
                "method": method,
                "path": path,
                "query_string": b"",
                "headers": [(k.lower().encode(), v.encode()) for k, v in headers.items()],
            }
        )
        response = await read_only_guard.read_only_guard(request, call_next)
        return bool(reached), getattr(response, "status_code", None)

    return asyncio.run(scenario())


def test_the_guard_is_mounted_on_the_app():
    mounted = [m.kwargs.get("dispatch") for m in app.user_middleware]
    assert read_only_guard.read_only_guard in mounted


def test_every_write_route_refuses_him_before_its_handler(client):
    not_refused = [
        (method, path)
        for method, path in _write_routes()
        if path not in READ_ONLY_EXEMPT_WRITES and _guard_decision(method, path) != (False, 403)
    ]
    assert not_refused == []


def test_refusal_is_clear_json_and_names_read_only(client):
    res = client.put(PROBE_NOTE, headers=_headers(), json={})
    assert res.status_code == 403
    body = res.json()
    assert body["success"] is False
    assert "read-only" in body["error"].lower()
    assert res.headers["content-type"].startswith("application/json")


@pytest.mark.parametrize(
    "email", [HIS_EMAIL.upper(), f"  {HIS_EMAIL}\t", "BKimbark@UnilinkTransportation.com "]
)
def test_match_is_lower_cased_and_trimmed(client, email):
    assert _is_guard_refusal(client.put(PROBE_NOTE, headers=_headers(email), json={}))


def test_normal_user_reaches_the_route_as_before(client):
    # Admin passes the report gate, then the empty body fails validation: 422 is
    # proof the guard let it through without any handler writing anything.
    res = client.put(
        PROBE_NOTE,
        headers=_headers("someone@unilinktransportation.com", sub=OTHER_ID, roles=["admin"]),
        json=INVALID_BODY,
    )
    assert res.status_code == 422


def test_a_similar_address_is_not_him(client):
    res = client.put(
        PROBE_NOTE,
        headers=_headers("xbkimbark@unilinktransportation.com", sub=OTHER_ID, roles=["admin"]),
        json=INVALID_BODY,
    )
    assert res.status_code == 422


def test_he_can_still_read(client):
    res = client.get("/api/user/preferences", headers=_headers())
    assert res.status_code == 200
    assert res.json()["success"] is True


def test_exemptions_are_login_and_the_ai_question_only():
    assert READ_ONLY_EXEMPT_WRITES == frozenset(
        {
            "/api/custom/auth/email-code/issue",
            "/api/custom/auth/email-code/verify",
            "/api/custom/ai-chat/ask",
        }
    )
    routes = {p for _m, p in _write_routes()}
    assert READ_ONLY_EXEMPT_WRITES <= routes  # a renamed route must fail here


@pytest.mark.parametrize("path", sorted(READ_ONLY_EXEMPT_WRITES))
def test_exempt_routes_pass_the_guard_with_his_session(client, path):
    res = client.post(path, headers=_headers(), json={})
    assert not _is_guard_refusal(res)
    assert res.status_code == 422


def test_login_has_no_session_and_is_not_refused(client):
    res = client.post(
        "/api/custom/auth/email-code/verify",
        headers={"X-Proxy-Secret": SECRET},
        json={"email": HIS_EMAIL},
    )
    assert not _is_guard_refusal(res)


def test_his_email_in_the_body_or_a_custom_header_means_nothing(client):
    # The identity is the proxy's Authorization header, nothing the client adds.
    res = client.put(
        PROBE_NOTE,
        headers={
            **_headers("someone@unilinktransportation.com", sub=OTHER_ID, roles=["admin"]),
            "X-User-Email": HIS_EMAIL,
        },
        content=json.dumps(INVALID_BODY),
    )
    assert res.status_code == 422


@pytest.mark.parametrize("secret", [None, "wrong"])
def test_without_the_proxy_secret_the_header_proves_nothing(client, secret):
    headers = {"Authorization": _bearer(HIS_EMAIL)}
    if secret:
        headers["X-Proxy-Secret"] = secret
    res = client.put(PROBE_NOTE, headers=headers, json={})
    assert res.status_code == 401  # require_user's answer, unchanged


@pytest.mark.parametrize(
    "auth",
    ["Bearer not-json", "Bearer [1,2]", 'Bearer {"sub":"x","email":7}', "Basic abc"],
)
def test_malformed_identity_never_crashes_the_guard(client, auth):
    assert read_only_guard.request_email(auth) is None or isinstance(
        read_only_guard.request_email(auth), str
    )
    res = client.request(
        "PATCH", "/api/user/preferences", headers={"Authorization": auth, "X-Proxy-Secret": SECRET}, json={}
    )
    assert not _is_guard_refusal(res)
