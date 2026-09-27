"""What a merge/pull request update may report as changed (RADD-1451) — the one
allowlist GitLab, GitHub and Forgejo parsing share. A host stamps a dozen
bookkeeping keys on every update (`head_pipeline_id`, `merge_status`,
`total_time_spent`, `updated_at`, …); none of them is something a person would
automate on, and a denylist of four names let the rest fire "updated" on every
pipeline. Only a `MrChangeField` reaches the event; an update that changed
nothing else fires nothing (`receiving.fire_ref_action`).

`diff_entries` writes the kernel diff (`{field, from, to}`, spec 123) with only
the sides the host actually sent — GitHub's `edited` gives the old value and the
pull request the new one; a push through the request hook may know neither
sha — rather than inventing an "old"/"new" placeholder for a missing side.
"""

from collections.abc import Iterable
from enum import StrEnum
from typing import Any

from radd.kernel import changes as kchanges


class MrChangeField(StrEnum):
    """The fields of a merge/pull request whose change fires "updated"."""

    TITLE = "title"
    DESCRIPTION = "description"
    LABELS = "labels"
    ASSIGNEES = "assignees"
    REVIEWERS = "reviewers"
    MILESTONE = "milestone"
    DRAFT = "draft"
    SOURCE_BRANCH = "source_branch"
    TARGET_BRANCH = "target_branch"
    #: New commits pushed to the request: old head sha -> new head sha, when the
    #: host says which (GitLab `oldrev`/`last_commit`, GitHub `before`/`after`).
    COMMITS = "commits"


class _Unsent:
    """The host did not send this side of a change (distinct from a value of None,
    which is a real "was empty")."""

    __slots__ = ()

    def __repr__(self) -> str:
        return "UNSENT"


UNSENT: Any = _Unsent()


def sent(value: Any) -> Any:
    """A host field as a diff side: an absent or empty value is UNSENT."""
    return UNSENT if value in (None, "") else value


def diff_entries(triples: Iterable[tuple[MrChangeField, Any, Any]]) -> list[dict[str, Any]]:
    """The kernel diff for an update, from `(field, old, new)` triples in which
    either side may be UNSENT. Both sides known: the kernel's own entry, dropped
    when equal. One side known: that side alone. Neither: the kernel's
    "it changed" entry (`hidden_change`), so a push with no shas still counts."""
    out: list[dict[str, Any]] = []
    for field_name, old, new in triples:
        name = MrChangeField(field_name).value
        if old is UNSENT and new is UNSENT:
            out.append(kchanges.hidden_change(name))
        elif old is UNSENT:
            out.append({"field": name, "to": kchanges.json_safe(new)})
        elif new is UNSENT:
            out.append({"field": name, "from": kchanges.json_safe(old)})
        else:
            entry = kchanges.change(name, old, new)
            if entry is not None:
                out.append(entry)
    return out
