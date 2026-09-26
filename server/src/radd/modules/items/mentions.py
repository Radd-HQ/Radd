"""Issue reference parsing — pure string work.

Two forms render as a chip (web/src/components/editor/chips.ts):
`#[TD-123](TD-123)` (the editor's `#` picker) and `[TD-123](/issues/TD-123)`
(a pasted link, or generated release notes). Every consumer — item `mentions`
links, a page's linked issues — parses through here so they agree.
"""

import re

# The parenthesised target is a canonical item key: a 1–10 char project key
# (letter-led alnum) + "-" + the per-project number.
_KEY = r"[A-Za-z][A-Za-z0-9]{0,9}-\d+"

#: The editor's own token.
ISSUE_MENTION_RE = re.compile(rf"#\[[^\]\n]{{0,200}}\]\((?P<key>{_KEY})\)")

#: The URL form: only LINK TARGETS (`](…)` or `href="…"`), never prose naming a
#: path. The host is deliberately unchecked — a strict base-URL match fails
#: silently the moment that setting is wrong; an unknown key is dropped anyway.
ISSUE_URL_RE = re.compile(
    rf"""(?:\]\(\s*|href\s*=\s*["'])(?:https?://[^/\s"')]+)?/issues/(?P<key>{_KEY})"""
)


def parse_issue_keys(text: str | None) -> set[str]:
    """Every distinct item key referenced in `text`, either form (case
    preserved, deduped)."""
    if not text:
        return set()
    return {
        match.group("key")
        for pattern in (ISSUE_MENTION_RE, ISSUE_URL_RE)
        for match in pattern.finditer(text)
    }
