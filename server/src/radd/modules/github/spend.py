"""The `/spend` comment convention for GitHub pull requests (RADD-1261). Pure.

GitHub has no time tracking — no field, no API, no quick action — so a
developer types the entry into a PR comment and the connector reads it:

    /spend 1h30
    /spend 45m 2026-09-18
    /spend 2h 2026-09-18 pairing on the migration
    /spend 1h RADD-412 review          ← log to RADD-412, not the PR's issue
    /unspend                           ← remove this author's entries on the PR

One comment may hold several `/spend` lines; each becomes one entry keyed by
the comment id and the line's position, so editing the comment updates the
same rows and deleting it removes them. Durations are the same grammar Radd
accepts everywhere (`1h30`, `1.5h`, `90m`, `1d` with the instance's hours per
day) — parsed by the caller through the timelogging seam, so this module only
carries the text apart.
"""

import re
from dataclasses import dataclass
from datetime import date

# `/spend <duration> [YYYY-MM-DD] [KEY] [note…]` on its own line.
SPEND_RE = re.compile(r"^\s*/spend\s+(?P<duration>\S+)(?P<rest>.*)$", re.IGNORECASE | re.MULTILINE)
UNSPEND_RE = re.compile(r"^\s*/unspend\s*$", re.IGNORECASE | re.MULTILINE)
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
KEY_RE = re.compile(r"^[A-Za-z][A-Za-z0-9]{0,9}-\d+$")


@dataclass(frozen=True)
class SpendCommand:
    #: 0-based position among the comment's /spend lines — part of the entry id.
    position: int
    duration_text: str
    spent_on: date | None  # None = the comment's date
    key_override: str | None
    note: str


def parse_spend(body: str) -> list[SpendCommand]:
    commands: list[SpendCommand] = []
    for position, match in enumerate(SPEND_RE.finditer(body or "")):
        words = match.group("rest").split()
        spent_on: date | None = None
        key: str | None = None
        if words and DATE_RE.match(words[0]):
            try:
                spent_on = date.fromisoformat(words.pop(0))
            except ValueError:
                spent_on = None
        if words and KEY_RE.match(words[0]):
            key = words.pop(0).upper()
        commands.append(
            SpendCommand(
                position=position,
                duration_text=match.group("duration"),
                spent_on=spent_on,
                key_override=key,
                note=" ".join(words).strip(),
            )
        )
    return commands


def is_unspend(body: str) -> bool:
    return bool(UNSPEND_RE.search(body or ""))


def comment_entry_id(repo_name: str, comment_id: int | str, position: int) -> str:
    """`comment:<owner/repo>:<comment id>:<n>` — the comment's own id keeps an
    edit on the same rows; the position separates several lines in one comment."""
    return f"comment:{repo_name.strip().lower()}:{comment_id}:{position}"


def comment_prefix(repo_name: str, comment_id: int | str) -> str:
    return f"comment:{repo_name.strip().lower()}:{comment_id}:"
