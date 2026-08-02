"""Search query-building core (spec 28).

Pure tests of the tsquery builder and key detection — the injection surface and
the routing rule the endpoint depends on. Index maintenance + ranking are
exercised live (the indexer replays the event backlog on an isolated DB).
"""

from radd.modules.search.service import build_tsquery, key_pattern, looks_like_key


def test_tsquery_prefix_stars_the_last_term():
    assert build_tsquery("render farm") == "'render' & 'farm':*"
    assert build_tsquery("render") == "'render':*"


def test_tsquery_strips_metacharacters():
    # tsquery operators in user input must never reach to_tsquery raw.
    assert build_tsquery("a & b | !c (d)") == "'a' & 'b' & 'c' & 'd':*"
    assert build_tsquery("!!! &&& |||") == ""
    assert build_tsquery("") == ""


def test_tsquery_keeps_dotted_and_dashed_tokens():
    assert build_tsquery("nuke-13.2 crash") == "'nuke-13.2' & 'crash':*"


def test_key_detection():
    assert looks_like_key("TD") is True
    assert looks_like_key("TD-") is True
    assert looks_like_key("TD-123") is True
    assert looks_like_key("td-9") is True  # matched case-insensitively via ILIKE
    assert looks_like_key("render farm") is False
    assert looks_like_key("TD-12x") is False
    assert looks_like_key("") is False


def test_key_pattern_routing():
    assert key_pattern("TD-12") == "TD-12%"  # key prefix
    assert key_pattern("123") == "%-123%"  # bare number → numeric part of any key
    assert key_pattern("render farm") is None  # words → FTS only
    assert key_pattern("12345678901") is None  # over-long number is not a key
