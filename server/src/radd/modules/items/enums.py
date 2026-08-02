from enum import StrEnum


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


class ItemLinkType(StrEnum):
    """The built-in link-type KEYS (spec 91: types are now data in the `linktypes`
    module, but these keys stay stable — code references them directly). Symmetry,
    directional names, and whether a type is manual now come from the catalog, not
    a frozenset here. MENTIONS is auto-derived from item text (spec 52)."""

    BLOCKS = "blocks"
    RELATES = "relates"
    DUPLICATES = "duplicates"
    MENTIONS = "mentions"


class BulkSkipReason(StrEnum):
    """Why one item was skipped by a bulk operation (spec 68) — the batch itself
    never fails for a single item."""

    NOT_FOUND = "not_found"
    FORBIDDEN = "forbidden"
    INVALID_TARGET = "invalid_target"  # project-scoped value not applicable to this item
    TRANSITION_BLOCKED = "transition_blocked"  # spec-61 guard failures
    ERROR = "error"


class ItemEvent(StrEnum):
    CREATED = "item.created"
    UPDATED = "item.updated"
    DELETED = "item.deleted"  # spec 38 — hard delete (audit rows remain)


class ItemEntity(StrEnum):
    ITEM = "item"
    LINK = "item_link"
