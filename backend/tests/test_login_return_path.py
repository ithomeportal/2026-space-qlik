"""A signed-out reader who opens a report link lands on that report after login.

The destination travels in a URL anyone can craft, so the property that matters
most is that it can never leave this site. The same table drives the frontend's
``lib/login-return.ts`` (run by Node, no JS test runner in this repo) and the
backend's ``safe_return_path``, which builds the mailed "sign in directly" link.
"""

import json
import re
import shutil
import subprocess
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import pytest

from app.routers import auth_email as ae
from tests.test_auth_email import _FakeConn, _FakeRequest, sent  # noqa: F401

FRONTEND = Path(__file__).resolve().parents[2] / "frontend"

KEPT = [
    "/reports/attrition-wow",
    "/reports/attrition-wow?tab=pivots&dim=customer",
    "/reports/x?customer=A%20%26%20B",
    "/admin/reports",
    "/reports/login-report",
    "/apiary",
    "/reports/x?note=a/../b",
    "/reports/v1.2/x...y",
]
REFUSED = [
    None,
    "",
    "/",
    "reports/x",
    "https://evil.example/x",
    "HTTPS://evil.example",
    "//evil.example/x",
    "///evil.example",
    "/\\evil.example",
    "\\\\evil.example",
    "/\t/evil.example",
    "/\n/evil.example",
    "/reports/\r\nSet-Cookie:x",
    "/reports/\x7f",
    " /reports/x",
    "javascript:alert(1)",
    "/login",
    "/login?callbackUrl=/x",
    "/login/verify?email=a",
    "/api/auth/signout",
    "/api",
    "/api?x=1",
    "/x/../api/auth/signout",
    "/%2e%2e/api/proxy/x",
    "/%2E./api/proxy/x",
    "/.%2e/login",
    "/./login?callbackUrl=/x",
    "/.//evil.example",
    "/x/..",
    "/" + "a" * 1000,
    123,
]


@pytest.mark.parametrize("path", KEPT)
def test_backend_keeps_a_page_on_this_site(path):
    assert ae.safe_return_path(path) == path


@pytest.mark.parametrize("path", REFUSED)
def test_backend_refuses_anything_else(path):
    assert ae.safe_return_path(path) == "/"


def _run_frontend(script: str):
    node = shutil.which("node")
    if node is None:
        pytest.skip("node is not installed")
    module = (FRONTEND / "lib/login-return.ts").as_uri()
    source = f'const m = await import({json.dumps(module)});\n{script}'
    done = subprocess.run(
        [node, "--experimental-strip-types", "--no-warnings",
         "--input-type=module", "-e", source],
        capture_output=True, text=True, timeout=30, check=True,
    )
    return json.loads(done.stdout)


def test_frontend_agrees_with_the_table():
    cases = json.dumps(KEPT + REFUSED)
    out = _run_frontend(
        f"console.log(JSON.stringify({cases}.map((c) => m.safeReturnPath(c))))"
    )
    assert out == KEPT + ["/"] * len(REFUSED)


def test_frontend_builds_the_login_and_verify_urls():
    out = _run_frontend(
        """
        console.log(JSON.stringify([
          m.withReturnPath("/login", "/reports/x?tab=a&dim=b"),
          m.withReturnPath("/login/verify?email=a%40b.com", "/reports/x"),
          m.withReturnPath("/login", "/"),
        ]))
        """
    )
    assert out == [
        "/login?callbackUrl=%2Freports%2Fx%3Ftab%3Da%26dim%3Db",
        "/login/verify?email=a%40b.com&callbackUrl=%2Freports%2Fx",
        "/login",
    ]


def test_frontend_reads_the_browser_location():
    out = _run_frontend(
        """
        const at = (pathname, search) => { globalThis.window = { location: { pathname, search } } };
        at("/reports/x", "?tab=pivots&dim=customer");
        const report = m.loginUrlForCurrentPage();
        at("/login", "?callbackUrl=%2Freports%2Fx%3Fa%3D1");
        const back = m.returnPathFromLocation();
        at("/login", "?callbackUrl=https%3A%2F%2Fevil.example");
        const evil = m.returnPathFromLocation();
        delete globalThis.window;
        console.log(JSON.stringify([report, back, evil, m.loginUrlForCurrentPage()]));
        """
    )
    assert out == [
        "/login?callbackUrl=%2Freports%2Fx%3Ftab%3Dpivots%26dim%3Dcustomer",
        "/reports/x?a=1",
        "/",
        "/login",
    ]


# --------------------------------------------------------------------------
# The mailed "sign in directly" link
# --------------------------------------------------------------------------


async def _issue(sent_box, callback_url, monkeypatch):
    monkeypatch.setattr(ae.settings, "APP_BASE_URL", "https://space.example", raising=False)
    conn = _FakeConn()
    await ae.issue_email_code(
        ae.IssueRequest(email="someone@unilinktransportation.com", callback_url=callback_url),
        _FakeRequest(conn),
    )
    stored = next(e for e in conn.executed if "INSERT INTO email_codes" in e[0])[1][2]
    href = re.search(r'<a href="([^"]+)"', sent_box[0]["html"]).group(1)
    return stored, href


@pytest.mark.asyncio
async def test_the_mailed_link_carries_the_destination(sent, monkeypatch):  # noqa: F811
    path = "/reports/attrition-wow?tab=pivots&dim=customer"
    stored, href = await _issue(sent, path, monkeypatch)
    assert stored == path
    query = parse_qs(urlparse(href).query)
    assert query["callbackUrl"] == [path]
    assert query["email"] == ["someone@unilinktransportation.com"]
    assert len(query["code"][0]) == 8


@pytest.mark.asyncio
async def test_the_mailed_link_is_unchanged_without_a_destination(sent, monkeypatch):  # noqa: F811
    stored, href = await _issue(sent, "/", monkeypatch)
    assert stored == "/"
    assert "callbackUrl" not in href


@pytest.mark.asyncio
@pytest.mark.parametrize("hostile", [
    "https://evil.example/x",
    "//evil.example",
    '/x"><script>alert(1)</script>'.replace("/x", "//x"),
])
async def test_a_hostile_destination_reaches_neither_the_mail_nor_the_table(
    sent, monkeypatch, hostile,  # noqa: F811
):
    stored, href = await _issue(sent, hostile, monkeypatch)
    assert stored == "/"
    assert "callbackUrl" not in href
    assert "evil" not in sent[0]["html"] and "<script" not in sent[0]["html"]


@pytest.mark.asyncio
async def test_markup_in_an_on_site_path_cannot_break_out_of_the_href(sent, monkeypatch):  # noqa: F811
    _, href = await _issue(sent, '/reports/x"><img src=y>', monkeypatch)
    assert "<img" not in sent[0]["html"]
    assert parse_qs(urlparse(href).query)["callbackUrl"] == ['/reports/x"><img src=y>']


# --------------------------------------------------------------------------
# Every step of the path is wired (no JS runner: read the source)
# --------------------------------------------------------------------------


def _source(relative: str) -> str:
    return (FRONTEND / relative).read_text(encoding="utf-8")


@pytest.mark.parametrize("guard", ["components/ReportGuard.tsx", "components/RoleGuard.tsx"])
def test_the_guards_send_the_page_along(guard):
    src = _source(guard)
    assert "redirect(loginUrlForCurrentPage())" in src
    assert 'redirect("/login")' not in src


def test_the_login_page_passes_the_destination_on():
    src = _source("app/(auth)/login/page.tsx")
    assert "window.location.href = returnPathFromLocation()" in src
    assert "JSON.stringify({ email, callbackUrl: returnPath })" in src
    assert "withReturnPath(`/login/verify?email=${encodeURIComponent(email)}`, returnPath)" in src


def test_the_verify_page_lands_on_the_validated_destination():
    src = _source("app/(auth)/login/verify/page.tsx")
    assert 'safeReturnPath(searchParams.get("callbackUrl"))' in src
    assert 'window.location.href = "/"' not in src


def test_the_send_code_route_validates_before_the_backend():
    src = _source("app/api/auth/send-code/route.ts")
    assert "safeReturnPath(callbackUrl)" in src
