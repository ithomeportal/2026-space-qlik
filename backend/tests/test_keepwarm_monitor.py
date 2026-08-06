"""Tests for the keep-warm source classifier.

``classify_keepwarm_source`` decides which pinger an ``/api/health`` call came
from. Getting it wrong is not cosmetic: mislabelling the n8n primary as
"unknown" makes the watchdog think the primary died and email a false alarm,
which is exactly the kind of noise this whole change set out to remove.
"""

from app.services.keepwarm_monitor import (
    KEEPWARM_HOST_IP,
    SOURCE_N8N,
    SOURCE_SYSTEMD,
    classify_keepwarm_source,
)


class TestClassifyKeepwarmSource:
    def test_systemd_backstop_matched_by_explicit_user_agent(self):
        assert (
            classify_keepwarm_source(
                "spaceqlik-keepwarm/1 (systemd; bi-unlk)", KEEPWARM_HOST_IP
            )
            == SOURCE_SYSTEMD
        )

    def test_n8n_matched_by_user_agent(self):
        assert classify_keepwarm_source("n8n", KEEPWARM_HOST_IP) == SOURCE_N8N

    def test_systemd_wins_over_n8n_when_both_substrings_present(self):
        # Both pingers share a host; the explicit backstop UA must be checked
        # first, or the backstop would be booked as the primary and mask its death.
        assert (
            classify_keepwarm_source("spaceqlik-keepwarm/1 via n8n-host", KEEPWARM_HOST_IP)
            == SOURCE_SYSTEMD
        )

    def test_n8n_falls_back_to_host_ip_when_user_agent_changes(self):
        # The false-alarm guard: an n8n upgrade that changes its UA must NOT read
        # as a dead primary. Anything from the keep-warm host that isn't the
        # systemd UA is n8n.
        assert (
            classify_keepwarm_source("axios/1.7.2", KEEPWARM_HOST_IP) == SOURCE_N8N
        )

    def test_forwarded_for_chain_uses_first_hop(self):
        assert (
            classify_keepwarm_source("axios/1.7.2", f"{KEEPWARM_HOST_IP}, 10.0.0.1, 172.16.0.9")
            == SOURCE_N8N
        )

    def test_forwarded_for_tolerates_whitespace(self):
        assert (
            classify_keepwarm_source("axios/1.7.2", f"  {KEEPWARM_HOST_IP} , 10.0.0.1")
            == SOURCE_N8N
        )

    def test_browser_from_other_ip_is_ignored(self):
        # Real users and the Vercel proxy hit /api/health too; recording them
        # would pollute the ledger and could mask a dead pinger.
        assert (
            classify_keepwarm_source(
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)", "203.0.113.7"
            )
            is None
        )

    def test_missing_headers_are_ignored(self):
        assert classify_keepwarm_source(None, None) is None

    def test_empty_headers_are_ignored(self):
        assert classify_keepwarm_source("", "") is None

    def test_user_agent_match_is_case_insensitive(self):
        assert classify_keepwarm_source("N8N/2.31.5", None) == SOURCE_N8N
        assert (
            classify_keepwarm_source("SpaceQlik-KeepWarm/1", None) == SOURCE_SYSTEMD
        )

    def test_similar_ip_does_not_match(self):
        assert classify_keepwarm_source("curl/8.5.0", "66.23.237.21") is None
        assert classify_keepwarm_source("curl/8.5.0", "166.23.237.218") is None
