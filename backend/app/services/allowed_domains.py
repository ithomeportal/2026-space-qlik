"""Company email domains — the only addresses this service may send mail to.

These are the Microsoft 365 tenant's *verified* domains (Graph ``GET /domains``).
Anything else — gmail, hotmail, a partner or vendor domain — is out.

WHY: every report this service mails is internal BI — RFP awarded revenue and
win/loss ratios, Losses Lanes weekly movers, Ops team performance. All of it is
addressed to named UNILINK staff in production. But two admin endpoints took
their recipients from **query parameters** with no validation at all, and the
Graph path sends fully DKIM-aligned first-party mail from
``ithome@unilinktransportation.com`` — so a wrong recipient there reads as
authentic to whoever receives it.

Guarding at the transport (``msgraph_mailer.send_mail`` and the Resend call
sites) means every current and future caller inherits the rule.

Override with ALLOWED_EMAIL_DOMAINS (comma-separated) when the tenant adds a
domain; updating this list is the durable fix.
"""
from __future__ import annotations

import os

ORG_EMAIL_DOMAINS: frozenset[str] = frozenset(
    {
        "hireinternational.com",
        "itunilink.com",
        "mencarllc.com",
        "mencarotr.com",
        "mspekt.com",
        "oiltex.com",
        "otxtransport.com",
        "otxtransportation.com",
        "prosperityenergyresources.com",
        "seekequipment.com",
        "u-capital.com",
        "unilinkcapital.com",
        "unilinkportal.com",
        "unilinktransportation.com",
        # Tenant routing domains — real and deliverable.
        "unilinktransportationsa.mail.onmicrosoft.com",
        "unilinktransportationsa.onmicrosoft.com",
    }
)


def _resolve() -> frozenset[str]:
    override = os.getenv("ALLOWED_EMAIL_DOMAINS", "").strip()
    if override:
        return frozenset(
            d.strip().lower().lstrip("@") for d in override.split(",") if d.strip()
        )
    return ORG_EMAIL_DOMAINS


def email_domain(value: str | None) -> str | None:
    """Lowercased domain part of an address, or ``None`` if it is not one."""
    if not value:
        return None
    _, _, domain = value.rpartition("@")
    domain = domain.strip().lower()
    return domain or None


def is_org_email(value: str | None) -> bool:
    """True when ``value`` is an address on a domain the organization owns."""
    domain = email_domain(value)
    return domain is not None and domain in _resolve()


def partition_recipients(addresses) -> tuple[list[str], list[str]]:
    """Split into (deliverable, rejected-domains).

    Returns *domains* for the rejected side so callers can log a useful reason
    without writing employee addresses into logs.
    """
    allowed: list[str] = []
    blocked: list[str] = []
    for a in addresses or []:
        if not a:
            continue
        if is_org_email(a):
            allowed.append(a)
        else:
            d = email_domain(a) or "(malformed)"
            if d not in blocked:
                blocked.append(d)
    return allowed, blocked
