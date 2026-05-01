"""Microsoft Graph mail sender (client-credentials, application permission).

Used by ``rfp_daily_digest`` to send the 5:30 PM CST RFP Performance digest
from ``ithome@unilinktransportation.com``. Avoids adding ``msal`` as a
dependency by talking to the OAuth2 token endpoint directly with the
existing ``httpx`` async client.

Required Azure AD app permissions
---------------------------------
- ``Mail.Send`` (Application) on Microsoft Graph, with admin consent.
  The same ``admin-ms-api`` app registration that powers the
  ``/BOT/admin-ms`` toolkit is reused — only the permission scope is new.

Required env vars
-----------------
- ``MS_TENANT_ID``      Azure AD tenant id (Unilink: ``3ec94f58-...``)
- ``MS_CLIENT_ID``      App-registration client id
- ``MS_CLIENT_SECRET``  App secret
- ``MS_SEND_FROM``      Sending mailbox (defaults to
                        ``ithome@unilinktransportation.com``)

Token caching
-------------
Tokens are cached in-process for ``expires_in - 60s``; a single Render
container fetches at most ~24 tokens/day. Thread-safe via ``asyncio.Lock``.
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any, Iterable, Optional

import httpx

logger = logging.getLogger(__name__)

GRAPH_SCOPE = "https://graph.microsoft.com/.default"
TOKEN_URL_TEMPLATE = "https://login.microsoftonline.com/{tenant}/oauth2/v2.0/token"
SENDMAIL_URL_TEMPLATE = "https://graph.microsoft.com/v1.0/users/{user}/sendMail"

_token_cache: dict[str, tuple[float, str]] = {}
_token_lock = asyncio.Lock()


class GraphMailError(RuntimeError):
    """Raised when token acquisition or sendMail fails."""


async def _get_token(tenant_id: str, client_id: str, client_secret: str) -> str:
    """Fetch (or reuse) a Graph access token via client-credentials flow."""
    cache_key = f"{tenant_id}|{client_id}"
    cached = _token_cache.get(cache_key)
    now = time.time()
    if cached and cached[0] > now:
        return cached[1]

    async with _token_lock:
        cached = _token_cache.get(cache_key)
        if cached and cached[0] > now:
            return cached[1]

        url = TOKEN_URL_TEMPLATE.format(tenant=tenant_id)
        data = {
            "grant_type": "client_credentials",
            "client_id": client_id,
            "client_secret": client_secret,
            "scope": GRAPH_SCOPE,
        }
        async with httpx.AsyncClient(timeout=20.0) as client:
            r = await client.post(url, data=data)
        if r.status_code != 200:
            raise GraphMailError(
                f"Token endpoint returned {r.status_code}: {r.text[:300]}"
            )
        body = r.json()
        token = body.get("access_token")
        expires_in = int(body.get("expires_in") or 3600)
        if not token:
            raise GraphMailError(f"Token endpoint payload missing access_token: {body}")
        _token_cache[cache_key] = (now + max(60, expires_in - 60), token)
        return token


def _to_recipients(addresses: Iterable[str]) -> list[dict[str, dict[str, str]]]:
    return [{"emailAddress": {"address": a}} for a in addresses if a]


async def send_mail(
    *,
    tenant_id: str,
    client_id: str,
    client_secret: str,
    from_address: str,
    to: Iterable[str],
    subject: str,
    html_body: str,
    cc: Optional[Iterable[str]] = None,
    bcc: Optional[Iterable[str]] = None,
    save_to_sent: bool = True,
) -> dict[str, Any]:
    """Send one HTML email via Microsoft Graph and return a diagnostic dict.

    Never raises on send failure — returns ``{"sent": False, "reason": ...}``
    so the caller (scheduler) can log without crashing the cron job.
    """
    to_list = [a for a in to if a]
    if not to_list:
        return {"sent": False, "reason": "no_to_recipients"}
    if not (tenant_id and client_id and client_secret and from_address):
        return {"sent": False, "reason": "missing_graph_config"}

    try:
        token = await _get_token(tenant_id, client_id, client_secret)
    except Exception as e:  # GraphMailError or network
        logger.exception("MS Graph token acquisition failed: %s", e)
        return {"sent": False, "reason": "token_failed", "error": str(e)}

    payload: dict[str, Any] = {
        "message": {
            "subject": subject,
            "body": {"contentType": "HTML", "content": html_body},
            "toRecipients": _to_recipients(to_list),
        },
        "saveToSentItems": bool(save_to_sent),
    }
    cc_list = [a for a in (cc or []) if a]
    bcc_list = [a for a in (bcc or []) if a]
    if cc_list:
        payload["message"]["ccRecipients"] = _to_recipients(cc_list)
    if bcc_list:
        payload["message"]["bccRecipients"] = _to_recipients(bcc_list)

    url = SENDMAIL_URL_TEMPLATE.format(user=from_address)
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            r = await client.post(url, headers=headers, json=payload)
    except Exception as e:
        logger.exception("MS Graph sendMail HTTP failed: %s", e)
        return {"sent": False, "reason": "http_failed", "error": str(e)}

    # Graph returns 202 Accepted on success
    if r.status_code in (200, 202):
        logger.info(
            "MS Graph sendMail OK from=%s to=%d cc=%d bcc=%d subject=%r",
            from_address, len(to_list), len(cc_list), len(bcc_list), subject,
        )
        return {
            "sent": True,
            "from": from_address,
            "to": to_list,
            "cc": cc_list,
            "bcc": bcc_list,
            "subject": subject,
        }

    body_preview = r.text[:500] if r.text else ""
    logger.error(
        "MS Graph sendMail failed: status=%s body=%s", r.status_code, body_preview
    )
    return {
        "sent": False,
        "reason": f"graph_status_{r.status_code}",
        "error": body_preview,
    }
