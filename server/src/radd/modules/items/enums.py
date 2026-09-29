from enum import StrEnum

from radd.modules.workflow.types import StateCategory

#: Finished either way (completed or canceled): rollup "done", the open-item filters.
FINISHED_CATEGORIES = (StateCategory.DONE, StateCategory.CANCELED)


class Priority(StrEnum):
    LOW = "low"
    NORMAL = "normal"
    HIGH = "high"
    BLOCKER = "blocker"


class ItemKind(StrEnum):
    EPIC = "epic"
    ISSUE = "issue"
    SUBTASK = "subtask"


# kind -> the kind its parent must have. Epics have no parent; a subtask requires one.
# Strictly descending, so cycles are impossible by construction (max depth 3).
REQUIRED_PARENT_KIND: dict[ItemKind, ItemKind] = {
    ItemKind.ISSUE: ItemKind.EPIC,
    ItemKind.SUBTASK: ItemKind.ISSUE,
}


class ItemVisibility(StrEnum):
    """Who may read an issue, beyond holding `item.read` on its project (spec 121 §3).
    The vocabulary comments already use (`CommentVisibility`), one level wider.

    public     — anyone holding `item.read` on the project; the WORLD when the
                 project is public (the Public role holds `item.read@public`).
    internal   — members only: unqualified `item.read` holders. Hidden from the
                 world even in a public project.
    restricted — the people on it: reporter, assignee, participants (the
                 `item` row guard's `admits`), provided they hold `item.read`
                 in any form. Project managers do not bypass (D1); instance
                 admins do.
    """

    PUBLIC = "public"
    INTERNAL = "internal"
    RESTRICTED = "restricted"


class BulkSkipReason(StrEnum):
    """Why one item was skipped by a bulk operation (spec 68) — the batch itself
    never fails for a single item."""

    NOT_FOUND = "not_found"
    FORBIDDEN = "forbidden"
    INVALID_TARGET = "invalid_target"  # project-scoped value not applicable to this item
    TRANSITION_BLOCKED = "transition_blocked"  # spec-61 guard failures
    #: RADD-1492: a subtask moves with its issue, never on its own — selected
    #: without its parent (or after the parent's move was skipped), it stays.
    SUBTASK_FOLLOWS_PARENT = "subtask_follows_parent"
    ERROR = "error"


class ItemOrigin(StrEnum):
    """WHERE a new issue came from, on `item.created` (RADD-1320). Absent =
    a person in the app, the API or MCP. `automation` is derived from the
    automated marker; the rest are stated by the door that created it through
    `items.service.creating_from`."""

    EMAIL = "email"
    FORM = "form"
    PORTAL = "portal"
    ALERT = "alert"
    AUTOMATION = "automation"


class ItemEvent(StrEnum):
    CREATED = "item.created"
    UPDATED = "item.updated"
    DELETED = "item.deleted"  # spec 38 — hard delete (audit rows remain)


class ItemEntity(StrEnum):
    ITEM = "item"
    LINK = "item_link"
