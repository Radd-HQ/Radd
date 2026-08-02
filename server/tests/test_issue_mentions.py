"""Issue `#`-mention parsing (spec 52) — the pure grammar behind derived backlinks."""

from radd.modules.items.mentions import parse_issue_keys


def test_extracts_keys_from_editor_tokens():
    text = "Blocked by #[TD-12](TD-12) and relates to #[OPS-3](OPS-3)."
    assert parse_issue_keys(text) == {"TD-12", "OPS-3"}


def test_dedupes_repeated_mentions():
    assert parse_issue_keys("#[TD-1](TD-1) again #[TD-1](TD-1)") == {"TD-1"}


def test_ignores_plain_text_and_markdown_links():
    # A bare "TD-12", a hashtag, and an ordinary markdown link are not mentions.
    text = "See TD-12 or #general or [the docs](https://x.example/TD-9)."
    assert parse_issue_keys(text) == set()


def test_empty_and_none():
    assert parse_issue_keys("") == set()
    assert parse_issue_keys(None) == set()


def test_key_shape_is_enforced():
    # Lowercase-led / too-long project keys and non-numeric suffixes don't match.
    assert parse_issue_keys("#[x](toolongkey12-1) #[y](TD-abc) #[z](-5)") == set()
