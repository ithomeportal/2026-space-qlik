"""Test double for ``msgraph_mailer.send_notification``.

Records each send as the dict shape the watchdog tests assert on
(``to`` / ``subject`` / ``html`` / optional ``cc`` / ``bcc``) and returns the
configured result, so no test ever reaches Microsoft Graph.
"""
from __future__ import annotations

from typing import Any


def capture(calls: list[dict], result: dict[str, Any] | None = None):
    async def fake(*, to, subject, html_body, cc=None, bcc=None):
        msg: dict[str, Any] = {"to": list(to), "subject": subject, "html": html_body}
        if cc:
            msg["cc"] = list(cc)
        if bcc:
            msg["bcc"] = list(bcc)
        calls.append(msg)
        return result if result is not None else {"sent": True}

    return fake
