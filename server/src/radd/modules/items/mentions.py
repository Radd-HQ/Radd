"""Issue reference parsing (spec 52 follow-up; both forms since RADD-943).

An issue can be referenced in text two ways, and the reader already renders both
as a chip (`web/src/components/editor/chips.ts`):

  - `#[TD-123](TD-123)` — what the editor's `#` picker emits (the target item's
    canonical key inside the parens, mirroring notify's `@[Name](uuid)` token).
  - `[TD-123](/issues/TD-123)` — what a reference written OUTSIDE the editor
    looks like: a pasted address-bar link, or the generated release notes, which
    use nothing else.

Both are extracted here so every consumer — the derived `mentions` links between
items, and a page's linked issues — agrees on what "this text mentions TD-123"
means. One answer, or the two drift.

Pure string work — no DB, no I/O.
"""

import re

# The parenthesised target is a canonical item key: a 1–10 char project key
# (letter-led alnum) + "-" + the per-project number.
_KEY = r"[A-Za-z][A-Za-z0-9]{0,9}-\d+"

#: The editor's own token.
ISSUE_MENTION_RE = re.compile(rf"#\[[^\]\n]{{0,200}}\]\((?P<key>{_KEY})\)")

#: The URL form. Only LINK TARGETS count — a markdown `](…)` or an `href="…"` —
#: never prose that happens to name a path, which is the rule pages.backlinks
#: already sets and for the same reason: quoting a URL is not linking to it.
#:
#: The host is deliberately unchecked. Rejecting absolute URLs that do not match
#: this instance's configured base would be stricter, and it would fail silently
#: and totally the moment that setting is wrong — the exact release-notes pages
#: this was built for carry the public origin. An unresolvable key is dropped
#: anyway, so the cost of being permissive is a foreign key that happens to also
#: exist here; the cost of being strict is the feature doing nothing.
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
