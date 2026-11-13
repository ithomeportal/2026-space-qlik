"""Bruce Kimbark receives NO report mail from Space (Jaime Anaya, 2026-11-13).

He left as CFO and is an external Financial Advisor from 2026-11-05: read-only in
every app (READ_ONLY_EMAILS), and — since 2026-11-13 — off every report too. The
first lockdown left the report CCs alone by decision, so the NOON summary kept
reaching him; this pins the second half.

The address may appear ONLY in the read-only guard (which refuses his writes).
Any other occurrence in app code is a recipient list, a mail, or a roster that
would hand him a report.
"""
from __future__ import annotations

from pathlib import Path

from app.services import losses_alerts

ADDRESS = "bkimbark@unilinktransportation.com"
APP = Path(__file__).resolve().parents[1] / "app"
ALLOWED = {APP / "routers" / "read_only_guard.py"}


def test_losses_lanes_email_does_not_go_to_bruce():
    everyone = (*losses_alerts.TO_RECIPIENTS, *losses_alerts.CC_RECIPIENTS,
                *losses_alerts.BCC_RECIPIENTS)
    assert ADDRESS not in {a.lower() for a in everyone}
    # the rest of the list is untouched
    assert losses_alerts.CC_RECIPIENTS == ("jennifer@unilinktransportation.com",)


def test_the_address_lives_only_in_the_read_only_guard():
    found = sorted(
        str(p.relative_to(APP)) for p in APP.rglob("*.py")
        if p not in ALLOWED and ADDRESS in p.read_text(encoding="utf-8").lower()
    )
    assert found == []


def test_the_scan_can_see_a_known_positive():
    # A negative is only trusted once the scan is shown to find a real hit.
    guard = APP / "routers" / "read_only_guard.py"
    assert ADDRESS in guard.read_text(encoding="utf-8").lower()
