"""RADD-1296 — tick a GFM task-list checkbox inside stored markdown.

A core util beside `mailrender`: pure (no session, no module import), used by
the three surfaces whose bodies carry checklists — item descriptions, comments,
wiki pages — so a reader can tick a box without opening the editor.

The client says WHICH box (its index among the task items it rendered, in
document order), the state it wants, and the exact body it rendered. The
rewrite refuses — never guesses — when:

- the stored body is no longer the one the client rendered (someone edited it
  meanwhile; ticking box N of a different document could tick the wrong line);
- box N is not in the opposite state (the client's renderer and this scanner
  disagree about which marker is N — edge-case markdown; better a refusal
  than a flipped line the person never saw).

Only the one marker changes — the rest of the body is byte-for-byte what was
stored. Re-serialising the document would reformat it, and every tick would
then land in the page history as a rewrite.
"""

import re

from pydantic import BaseModel, Field

# A list item's leading marker, then `[ ]`/`[x]`/`[X]`, then whitespace or EOL.
# Blockquote prefixes (`> `) may precede it, as GFM allows task lists there.
_TASK = re.compile(r"^((?:[ \t]*>[ \t]?)*[ \t]*(?:[-*+]|\d{1,9}[.)])[ \t]+)\[([ xX])\](?=[ \t\r]|$)")
_FENCE = re.compile(r"^[ \t]*(?:>[ \t]?)*[ \t]*(`{3,}|~{3,})")


class TaskToggleConflict(Exception):
    """The body changed, or box N is not where the reader saw it."""


class TaskToggle(BaseModel):
    """The request body every `…/tasks` endpoint takes."""

    index: int = Field(ge=0, le=10_000)
    checked: bool
    # The body the reader rendered — the optimistic lock. Items and comments
    # carry no version column, so the text itself is the precondition.
    expected_body: str = Field(max_length=2_000_000)


def task_states(markdown: str) -> list[bool]:
    """Every task marker's state, in document order (fenced code skipped)."""
    return [checked for _line, _start, checked in _markers(markdown)]


def toggle(current_body: str, request: TaskToggle) -> str:
    """The body with task `index` set to `checked` — or TaskToggleConflict."""
    if current_body != request.expected_body:
        raise TaskToggleConflict("this was edited since you opened it — reload and try again")
    markers = _markers(current_body)
    if not 0 <= request.index < len(markers):
        raise TaskToggleConflict("that checkbox is not in the text any more")
    line_no, bracket_at, checked = markers[request.index]
    if checked == request.checked:
        raise TaskToggleConflict("that checkbox could not be matched — edit the text to change it")
    lines = current_body.split("\n")
    line = lines[line_no]
    mark = "x" if request.checked else " "
    lines[line_no] = line[: bracket_at + 1] + mark + line[bracket_at + 2 :]
    return "\n".join(lines)


def _markers(markdown: str) -> list[tuple[int, int, bool]]:
    """(line number, offset of `[`, checked) for each task marker."""
    found: list[tuple[int, int, bool]] = []
    fence: str | None = None
    for number, line in enumerate(markdown.split("\n")):
        opening = _FENCE.match(line)
        if fence is not None:
            if opening and opening.group(1)[0] == fence[0] and len(opening.group(1)) >= len(fence):
                fence = None
            continue
        if opening:
            fence = opening.group(1)
            continue
        match = _TASK.match(line)
        if match:
            found.append((number, len(match.group(1)), match.group(2) != " "))
    return found
