"""SLQ error type + the cheap did-you-mean suggestion."""

from collections.abc import Iterable

from radd.exceptions import RaddError


class SlqError(RaddError):
    """Invalid SLQ. `position` is the character offset of the offending token
    (-> 422 `{detail, position}` via the items module exception handler)."""

    def __init__(self, message: str, position: int):
        self.position = position
        super().__init__(message)


def unknown_field(name: str, position: int, candidates: Iterable[str]) -> SlqError:
    suggestion = suggest(name, candidates)
    hint = f" — did you mean '{suggestion}'?" if suggestion else ""
    return SlqError(f"unknown field '{name}'{hint}", position)


def suggest(word: str, candidates: Iterable[str]) -> str | None:
    """One-edit-distance did-you-mean (Damerau: insert, delete, substitute, or
    transpose one character — so 'shwo' finds 'show'). First match alphabetically."""
    lowered = word.lower()
    matches = sorted(c for c in set(candidates) if _one_edit_away(lowered, c.lower()))
    return matches[0] if matches else None


def _one_edit_away(a: str, b: str) -> bool:
    if a == b:
        return True
    if abs(len(a) - len(b)) > 1:
        return False
    if len(a) == len(b):
        diffs = [i for i in range(len(a)) if a[i] != b[i]]
        if len(diffs) == 1:
            return True
        return (
            len(diffs) == 2
            and diffs[1] == diffs[0] + 1
            and a[diffs[0]] == b[diffs[1]]
            and a[diffs[1]] == b[diffs[0]]
        )
    shorter, longer = (a, b) if len(a) < len(b) else (b, a)
    return any(shorter == longer[:i] + longer[i + 1 :] for i in range(len(longer)))
