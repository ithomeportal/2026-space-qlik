"""Unit tests for the Microsoft Graph notification transport.

Every HTTP call goes through ``httpx.MockTransport`` — nothing reaches Microsoft.
What matters: the sendMail payload shape, 202 = sent, any other status is a
returned failure (with Graph's error code), a 429 is retried exactly once after
Retry-After, missing credentials fail loud, and the company-domain guard holds.
"""
from __future__ import annotations

import asyncio
import json

import httpx
import pytest

from app.services import msgraph_mailer as gm

TOKEN_URL_PART = "/oauth2/v2.0/token"
CREDS = {"tenant_id": "t-1", "client_id": "c-1", "client_secret": "s-1",
         "from_address": "ithome@unilinktransportation.com"}
OK_TO = ["dfrodriguez@unilinktransportation.com"]


class _Graph:
    """Scripted fake of login.microsoftonline.com + graph.microsoft.com."""

    def __init__(self, send_responses):
        self.send_responses = list(send_responses)
        self.sends: list[httpx.Request] = []
        self.tokens = 0

    def handler(self, request: httpx.Request) -> httpx.Response:
        if TOKEN_URL_PART in request.url.path:
            self.tokens += 1
            return httpx.Response(200, json={"access_token": "tok", "expires_in": 3600})
        self.sends.append(request)
        return self.send_responses.pop(0)


@pytest.fixture
def graph(monkeypatch):
    def install(*send_responses):
        g = _Graph(send_responses)
        transport = httpx.MockTransport(g.handler)
        monkeypatch.setattr(gm, "_http_client",
                            lambda timeout: httpx.AsyncClient(transport=transport))
        monkeypatch.setattr(gm, "_token_cache", {})
        sleeps: list[float] = []

        async def fake_sleep(s):
            sleeps.append(s)

        monkeypatch.setattr(gm, "_sleep", fake_sleep)
        g.sleeps = sleeps
        return g

    return install


def _send(**kw):
    args = {**CREDS, "to": OK_TO, "subject": "S", "html_body": "<p>x</p>", **kw}
    return asyncio.run(gm.send_mail(**args))


def test_202_is_sent_and_payload_has_graph_shape(graph):
    g = graph(httpx.Response(202))
    out = _send(cc=["oorozco@unilinktransportation.com"], bcc=["jaime@unilinkportal.com"])
    assert out["sent"] is True
    [req] = g.sends
    assert req.url.path == "/v1.0/users/ithome@unilinktransportation.com/sendMail"
    assert req.headers["authorization"] == "Bearer tok"
    body = json.loads(req.content)
    msg = body["message"]
    assert body["saveToSentItems"] is True
    assert msg["subject"] == "S"
    assert msg["body"] == {"contentType": "HTML", "content": "<p>x</p>"}
    assert msg["toRecipients"] == [{"emailAddress": {"address": OK_TO[0]}}]
    assert msg["ccRecipients"][0]["emailAddress"]["address"] == "oorozco@unilinktransportation.com"
    assert msg["bccRecipients"][0]["emailAddress"]["address"] == "jaime@unilinkportal.com"


def test_non_2xx_is_a_failure_with_graph_error_code(graph):
    graph(httpx.Response(403, json={"error": {"code": "ErrorAccessDenied", "message": "no"}}))
    out = _send()
    assert out["sent"] is False
    assert out["reason"] == "graph_status_403"
    assert out["code"] == "ErrorAccessDenied"


def test_429_is_retried_once_after_retry_after(graph):
    g = graph(httpx.Response(429, headers={"Retry-After": "7"}), httpx.Response(202))
    out = _send()
    assert out["sent"] is True
    assert len(g.sends) == 2 and g.sleeps == [7.0]


def test_429_twice_gives_up_after_one_retry(graph):
    g = graph(httpx.Response(429, headers={"Retry-After": "999"}),
              httpx.Response(429, headers={"Retry-After": "1"}))
    out = _send()
    assert out["sent"] is False and out["reason"] == "graph_status_429"
    assert len(g.sends) == 2
    assert g.sleeps == [gm.MAX_RETRY_AFTER_S]  # hostile header is capped


def test_missing_creds_fail_loud_without_any_http(graph, caplog):
    g = graph()
    out = _send(client_secret="")
    assert out["sent"] is False and out["reason"] == "missing_graph_config"
    assert g.tokens == 0 and g.sends == []
    assert any("missing" in r.getMessage().lower() for r in caplog.records)


def test_external_only_recipients_are_blocked_and_domain_logged(graph, caplog):
    g = graph()
    out = _send(to=["someone@gmail.com"])
    assert out["sent"] is False and out["reason"] == "recipient_domain_not_allowed"
    assert g.sends == []
    logged = " ".join(r.getMessage() for r in caplog.records)
    assert "gmail.com" in logged and "someone@" not in logged


def test_token_failure_is_returned_not_raised(monkeypatch):
    transport = httpx.MockTransport(lambda req: httpx.Response(401, text="bad secret"))
    monkeypatch.setattr(gm, "_http_client",
                        lambda timeout: httpx.AsyncClient(transport=transport))
    monkeypatch.setattr(gm, "_token_cache", {})
    out = _send()
    assert out["sent"] is False and out["reason"] == "token_failed"


def test_send_notification_uses_settings_creds(graph, monkeypatch):
    g = graph(httpx.Response(202))
    monkeypatch.setattr(gm.settings, "MS_TENANT_ID", "t")
    monkeypatch.setattr(gm.settings, "MS_CLIENT_ID", "c")
    monkeypatch.setattr(gm.settings, "MS_CLIENT_SECRET", "s")
    monkeypatch.setattr(gm.settings, "MS_SEND_FROM", "ithome@unilinkportal.com")
    assert gm.graph_configured() is True
    out = asyncio.run(gm.send_notification(to=OK_TO, subject="S", html_body="h"))
    assert out["sent"] is True
    assert g.sends[0].url.path == "/v1.0/users/ithome@unilinkportal.com/sendMail"


def test_send_notification_without_creds_is_not_sent(monkeypatch):
    monkeypatch.setattr(gm.settings, "MS_CLIENT_SECRET", "")
    assert gm.graph_configured() is False
    out = asyncio.run(gm.send_notification(to=OK_TO, subject="S", html_body="h"))
    assert out["sent"] is False and out["reason"] == "missing_graph_config"
