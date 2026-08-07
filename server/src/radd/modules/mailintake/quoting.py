"""Stripping quoted reply history (RADD-956).

Best effort, and the word is load-bearing: there is no reliable marker for where
a reply ends and the quoted original begins. Every client invents its own, none
are required by any RFC, and localised clients translate theirs.

So the rule is **conservative**: strip only what is unambiguous, and never return
nothing. Over-stripping deletes the reply — the message the customer actually
sent — and that is a far worse failure than a comment carrying some quoted text.
`intake` keeps the full raw message regardless, so nothing here is unrecoverable.
"""

from __future__ import annotations

import re

#: "On <date>, <person> wrote:" and its common localisations, at line start.
#: Anchored and requiring the trailing colon, because the phrase appears inside
#: ordinary prose often enough to matter.
ATTRIBUTION_RE = re.compile(
    r"^\s*(?:"
    r"On\s.{0,200}?\swrote:"          # English (Gmail, Apple Mail, Thunderbird)
    r"|Le\s.{0,200}?\sa\s[ée]crit\s*:"  # French
    r"|Am\s.{0,200}?\sschrieb\s.{0,80}?:"  # German
    r"|El\s.{0,200}?\sescribi[oó]\s*:"  # Spanish
    r")\s*$",
    re.IGNORECASE,
)

#: Outlook and several corporate clients emit a separator block instead of an
#: attribution line. The header names vary by locale; the rule of five-plus
#: dashes or underscores followed by a From:/Sent: block is what is portable.
SEPARATOR_RE = re.compile(
    r"^\s*(?:[-_]{5,}\s*)?(?:Original Message|Forwarded message|"
    r"Ursprüngliche Nachricht|Message d'origine)\s*(?:[-_]{5,})?\s*$",
    re.IGNORECASE,
)

#: A run of dashes/underscores alone is NOT treated as a separator: it is also
#: how people write a signature delimiter and a horizontal rule in markdown.
#: `-- ` (dash dash space) IS the RFC 3676 signature marker, though.
SIGNATURE_RE = re.compile(r"^--\s*$")

#: A quoted line. One or more `>` after optional leading whitespace.
QUOTE_RE = re.compile(r"^\s*>")


def strip_quotes(body: str) -> str:
    """The reply, without the history under it.

    Cuts at the FIRST attribution line, separator block, or run of quoted lines,
    whichever comes first — and only if something survives. A message that is
    entirely quotation (someone replying inline, or forwarding with no comment)
    keeps its original text rather than becoming empty.
    """
    if not body:
        return body
    lines = body.splitlines()
    cut = _cut_index(lines)
    if cut is None:
        return body.strip()
    kept = "\n".join(lines[:cut]).strip()
    # Never return nothing. An inline reply, or a bare forward, is all quotation
    # by this test and its content is the only content there is.
    return kept or body.strip()


def _cut_index(lines: list[str]) -> int | None:
    quoted_run = 0
    for index, line in enumerate(lines):
        if ATTRIBUTION_RE.match(line) or SEPARATOR_RE.match(line):
            return index
        if SIGNATURE_RE.match(line):
            return index
        if QUOTE_RE.match(line):
            quoted_run += 1
            # Two consecutive quoted lines: a real quote block, not someone
            # using ">" for emphasis or pasting a shell prompt.
            if quoted_run >= 2:
                return index - (quoted_run - 1)
        elif line.strip():
            quoted_run = 0
    return None
