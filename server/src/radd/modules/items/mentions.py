"""Issue `#`-mention parsing (spec 52 follow-up).

The rich editor emits an issue reference as `#[TD-123](TD-123)` — the target item's
canonical key sits inside the parens (mirroring the `@[Name](uuid)` user-mention token
in notify). We extract those keys from an item's text so the service can reconcile a
set of derived `mentions` backlinks. Pure string work — no DB, no I/O.
"""

import re

# The parenthesised target is a canonical item key: a 1–10 char project key
# (letter-led alnum) + "-" + the per-project number.
ISSUE_MENTION_RE = re.compile(r"#\[[^\]\n]{0,200}\]\((?P<key>[A-Za-z][A-Za-z0-9]{0,9}-\d+)\)")


def parse_issue_keys(text: str | None) -> set[str]:
    """Every distinct item key `#`-referenced in `text` (case preserved, deduped)."""
    if not text:
        return set()
    return {match.group("key") for match in ISSUE_MENTION_RE.finditer(text)}
