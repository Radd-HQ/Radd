"""Client-IP resolution (spec 102): the pure trusted-proxy XFF walk.

The security property under test: an UNTRUSTED peer can never influence the
resolved address via headers — X-Forwarded-For is only consulted when the
socket peer itself is a configured trusted proxy.
"""

from radd.clientip import parse_trusted, resolve_client_ip

TRUSTED = parse_trusted("10.0.0.0/8, 192.168.1.1")


def test_no_trust_configured_returns_the_peer():
    assert resolve_client_ip("203.0.113.9", "1.2.3.4", ()) == "203.0.113.9"


def test_untrusted_peer_spoofed_header_is_ignored():
    assert resolve_client_ip("203.0.113.9", "10.0.0.5, 1.2.3.4", TRUSTED) == "203.0.113.9"


def test_trusted_peer_takes_the_forwarded_client():
    assert resolve_client_ip("10.0.0.5", "198.51.100.7", TRUSTED) == "198.51.100.7"


def test_chain_walks_right_to_left_past_trusted_hops():
    # client -> LB (10.0.0.5) -> ingress (10.0.0.6): both ours, the client survives.
    header = "198.51.100.7, 10.0.0.5"
    assert resolve_client_ip("10.0.0.6", header, TRUSTED) == "198.51.100.7"


def test_client_prepended_garbage_does_not_bypass_the_walk():
    # A malicious client sent its own XFF ("1.2.3.4"); the proxy appended the
    # real peer. The walk stops at the first untrusted entry from the right —
    # the address the trusted proxy actually saw.
    header = "1.2.3.4, 198.51.100.7"
    assert resolve_client_ip("10.0.0.5", header, TRUSTED) == "198.51.100.7"


def test_all_trusted_chain_falls_back_to_leftmost():
    assert resolve_client_ip("10.0.0.5", "10.0.0.1, 10.0.0.2", TRUSTED) == "10.0.0.1"


def test_trusted_peer_without_header_is_itself_the_client():
    assert resolve_client_ip("10.0.0.5", None, TRUSTED) == "10.0.0.5"


def test_single_trusted_ip_entry_and_invalid_entries():
    trusted = parse_trusted("192.168.1.1, not-a-network, ")
    assert len(trusted) == 1  # the invalid entry is skipped, not fatal
    assert resolve_client_ip("192.168.1.1", "203.0.113.7", trusted) == "203.0.113.7"


def test_ipv6_support():
    trusted = parse_trusted("fd00::/8")
    assert resolve_client_ip("fd00::1", "2001:db8::9", trusted) == "2001:db8::9"


def test_garbage_hop_is_treated_as_untrusted_never_raises():
    # A malformed hop can't be trusted-matched, so the walk stops there; the
    # CIDR matcher downstream treats an unparseable address as no-match.
    assert resolve_client_ip("10.0.0.5", "garbage, 10.0.0.2", TRUSTED) == "garbage"
