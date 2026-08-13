"""Login-code endpoints: the properties that must hold, or people cannot log in.

These stub the pool and the mail transport. What they pin is the behaviour that
is easy to regress and expensive to discover in production: the code never being
stored in plaintext, a code being single-use, wrong/expired being
indistinguishable, and the tenant-domain guard refusing before anything is
written or sent.
"""

import hashlib
from datetime import datetime, timezone

import pytest

from app.routers import auth_email as ae


class _FakeConn:
    def __init__(self, *, delete_returns=None, user_row=None, roles=()):
        self.executed: list[tuple] = []
        self._delete_returns = delete_returns
        self._user_row = user_row or {
            "id": "11111111-1111-1111-1111-111111111111",
            "email": "someone@unilinktransportation.com",
            "name": "Someone",
            "department": "IT",
            "company": "UNILINK",
            "is_active": True,
        }
        self._roles = [{"name": r} for r in roles]

    async def execute(self, sql, *args):
        self.executed.append((sql, args))

    async def fetchrow(self, sql, *args):
        self.executed.append((sql, args))
        if "DELETE FROM email_codes" in sql:
            return self._delete_returns
        if "INSERT INTO users" in sql or "FROM users" in sql:
            return self._user_row
        return None

    async def fetch(self, sql, *args):
        self.executed.append((sql, args))
        return self._roles

    def transaction(self):
        return self

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_a):
        return False


class _FakePool:
    def __init__(self, conn):
        self._conn = conn

    def acquire(self):
        return self._conn


class _FakeRequest:
    def __init__(self, conn):
        pool = _FakePool(conn)
        self.app = type("_A", (), {"state": type("_S", (), {"pool": pool})()})()


@pytest.fixture
def sent(monkeypatch):
    """Capture outbound mail instead of sending it."""
    box: list[dict] = []

    class _Emails:
        @staticmethod
        def send(payload):
            box.append(payload)

    fake = type("_R", (), {"api_key": None, "Emails": _Emails})
    monkeypatch.setitem(__import__("sys").modules, "resend", fake)
    monkeypatch.setattr(ae.settings, "RESEND_API_KEY", "re_test_key", raising=False)
    return box


# --------------------------------------------------------------------------
# issue
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_issue_stores_a_hash_never_the_code(sent):
    conn = _FakeConn()
    await ae.issue_email_code(
        ae.IssueRequest(email="Someone@unilinktransportation.com"), _FakeRequest(conn)
    )

    insert = [e for e in conn.executed if "INSERT INTO email_codes" in e[0]]
    assert len(insert) == 1
    stored = insert[0][1][1]

    mailed = sent[0]["subject"].split(": ")[1]
    assert stored != mailed, "the code itself must never reach the database"
    assert stored == hashlib.sha256(mailed.encode()).hexdigest()
    assert len(stored) == 64


@pytest.mark.asyncio
async def test_issue_lowercases_the_email_so_verify_can_match(sent):
    conn = _FakeConn()
    await ae.issue_email_code(
        ae.IssueRequest(email="MiXeD@unilinktransportation.com"), _FakeRequest(conn)
    )
    assert sent[0]["to"] == "mixed@unilinktransportation.com"
    insert = [e for e in conn.executed if "INSERT INTO email_codes" in e[0]][0]
    assert insert[1][0] == "mixed@unilinktransportation.com"


@pytest.mark.asyncio
async def test_issued_code_is_eight_digits(sent):
    await ae.issue_email_code(
        ae.IssueRequest(email="someone@unilinktransportation.com"),
        _FakeRequest(_FakeConn()),
    )
    code = sent[0]["subject"].split(": ")[1]
    assert len(code) == 8 and code.isdigit()


@pytest.mark.asyncio
async def test_issue_replaces_any_previous_code(sent):
    conn = _FakeConn()
    await ae.issue_email_code(
        ae.IssueRequest(email="someone@unilinktransportation.com"), _FakeRequest(conn)
    )
    assert any("DELETE FROM email_codes" in e[0] for e in conn.executed), (
        "a stale code left behind means two live codes for one address"
    )


@pytest.mark.asyncio
async def test_issue_refuses_a_non_tenant_domain_before_writing_or_sending(sent):
    conn = _FakeConn()
    with pytest.raises(Exception) as exc:
        await ae.issue_email_code(
            ae.IssueRequest(email="attacker@gmail.com"), _FakeRequest(conn)
        )
    assert getattr(exc.value, "status_code", None) == 403
    assert conn.executed == [], "nothing may be written for a refused domain"
    assert sent == [], "nothing may be sent for a refused domain"


@pytest.mark.asyncio
async def test_issue_fails_loudly_without_a_mail_key(monkeypatch):
    monkeypatch.setattr(ae.settings, "RESEND_API_KEY", "", raising=False)
    conn = _FakeConn()
    with pytest.raises(Exception) as exc:
        await ae.issue_email_code(
            ae.IssueRequest(email="someone@unilinktransportation.com"),
            _FakeRequest(conn),
        )
    # 503, not a silent success: "code sent" with no mail is unfixable by the user.
    assert getattr(exc.value, "status_code", None) == 503
    assert conn.executed == []


# --------------------------------------------------------------------------
# verify
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_verify_matches_on_the_hash_and_returns_the_user():
    conn = _FakeConn(delete_returns={"callback_url": "/reports"}, roles=("CEO", "IT"))
    out = await ae.verify_email_code(
        ae.VerifyRequest(email="someone@unilinktransportation.com", code="12345678"),
        _FakeRequest(conn),
    )

    delete = [e for e in conn.executed if "DELETE FROM email_codes" in e[0]][0]
    assert delete[1][1] == hashlib.sha256(b"12345678").hexdigest()
    assert out["data"]["user"]["roles"] == ["CEO", "IT"]
    assert out["data"]["callback_url"] == "/reports"


@pytest.mark.asyncio
async def test_verify_is_single_use_by_construction():
    """Redemption must be an atomic DELETE … RETURNING, not SELECT-then-DELETE:
    two concurrent requests with the same code must not both win.
    """
    conn = _FakeConn(delete_returns={"callback_url": "/"})
    await ae.verify_email_code(
        ae.VerifyRequest(email="someone@unilinktransportation.com", code="12345678"),
        _FakeRequest(conn),
    )
    sql = [e[0] for e in conn.executed if "email_codes" in e[0]][0]
    assert "DELETE" in sql and "RETURNING" in sql
    assert "SELECT" not in sql.split("RETURNING")[0]


@pytest.mark.asyncio
async def test_verify_only_accepts_an_unexpired_code():
    conn = _FakeConn(delete_returns={"callback_url": "/"})
    await ae.verify_email_code(
        ae.VerifyRequest(email="someone@unilinktransportation.com", code="12345678"),
        _FakeRequest(conn),
    )
    sql = [e[0] for e in conn.executed if "email_codes" in e[0]][0]
    assert "expires > now()" in sql, "an expired code must not be redeemable"


@pytest.mark.asyncio
async def test_wrong_and_expired_are_the_same_401():
    """Distinguishing them tells a prober whether an address has a live code."""
    conn = _FakeConn(delete_returns=None)  # no row matched: wrong OR expired
    with pytest.raises(Exception) as exc:
        await ae.verify_email_code(
            ae.VerifyRequest(email="someone@unilinktransportation.com", code="00000000"),
            _FakeRequest(conn),
        )
    assert getattr(exc.value, "status_code", None) == 401
    assert exc.value.detail == "Invalid or expired code"


@pytest.mark.asyncio
async def test_verify_refuses_a_non_tenant_domain():
    conn = _FakeConn(delete_returns={"callback_url": "/"})
    with pytest.raises(Exception) as exc:
        await ae.verify_email_code(
            ae.VerifyRequest(email="attacker@gmail.com", code="12345678"),
            _FakeRequest(conn),
        )
    assert getattr(exc.value, "status_code", None) == 403
    assert conn.executed == []


@pytest.mark.asyncio
async def test_verify_does_not_overwrite_sync_owned_profile_fields():
    """The daily user sync owns name/department/company. If login started writing
    them, every sign-in would clobber the synced values with whatever NextAuth
    happened to have.
    """
    conn = _FakeConn(delete_returns={"callback_url": "/"})
    await ae.verify_email_code(
        ae.VerifyRequest(email="someone@unilinktransportation.com", code="12345678"),
        _FakeRequest(conn),
    )
    upsert = [e[0] for e in conn.executed if "INSERT INTO users" in e[0]][0]
    # Only the SET clause counts — these columns legitimately appear in
    # RETURNING, which reads them rather than writing them.
    set_clause = upsert.split("DO UPDATE")[1].split("RETURNING")[0]
    for owned in ("name", "department", "company"):
        assert owned not in set_clause, f"login must not write users.{owned}"
    # And the insert must not seed them either.
    insert_cols = upsert.split("VALUES")[0]
    for owned in ("name", "department", "company"):
        assert owned not in insert_cols, f"login must not insert users.{owned}"


# --------------------------------------------------------------------------
# hashing helper
# --------------------------------------------------------------------------


def test_hash_is_stable_and_not_reversible_by_length():
    assert ae._hash_code("00000001") == ae._hash_code("00000001")
    assert ae._hash_code("00000001") != ae._hash_code("00000002")
    assert len(ae._hash_code("12345678")) == 64


def test_new_code_is_always_eight_digits_including_leading_zeros():
    # A naive int→str would emit a 6-digit string for small draws and the user
    # would type a code that can never match.
    for _ in range(500):
        c = ae._new_code()
        assert len(c) == 8 and c.isdigit()
