"""Issue types (spec 51): a per-project classification axis (Bug/Task/Story/…),
ORTHOGONAL to the epic/issue/subtask hierarchy (`ItemKind`). Rendered as a
colored chip; configurable per project; seeded with a sensible default set."""

from dataclasses import dataclass
from enum import StrEnum


@dataclass(frozen=True)
class DefaultType:
    name: str
    color: str  # "#rrggbb" — drives the chip background
    icon: str  # a lucide icon key the frontend maps (falls back to first letter)
    is_default: bool = False  # the type new items get when none is chosen


# Seeded into every new project. Colors/icons chosen to read as compact chips.
DEFAULT_TYPES: tuple[DefaultType, ...] = (
    DefaultType("Task", "#64748b", "square-check-big", is_default=True),
    DefaultType("Bug", "#ef4444", "bug"),
    DefaultType("Story", "#22c55e", "bookmark"),
    DefaultType("Feature", "#3b82f6", "sparkles"),
    DefaultType("Epic", "#a855f7", "gem"),
)


class TypeEvent(StrEnum):
    CREATED = "issue_type.created"
    UPDATED = "issue_type.updated"
    DELETED = "issue_type.deleted"


class TypeEntity(StrEnum):
    ISSUE_TYPE = "issue_type"
