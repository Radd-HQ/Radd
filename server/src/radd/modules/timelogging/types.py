from enum import StrEnum


class WorklogEvent(StrEnum):
    CREATED = "worklog.created"
    UPDATED = "worklog.updated"
    DELETED = "worklog.deleted"


class TimelogEntity(StrEnum):
    """Entity-type tags on emitted events + the identifier in Not-Found/Conflict errors."""

    WORKLOG = "worklog"
    WORK_CATEGORY = "work_category"
    ITEM_ESTIMATE = "item_estimate"
    PROJECT_CONFIG = "project_timelogging"


# Default work categories seeded globally on startup (editable/archivable afterwards).
# Data, not behaviour — admins add their own; these are just a sensible starting set.
DEFAULT_WORK_CATEGORIES: tuple[str, ...] = (
    "Development",
    "Investigation",
    "Code Review",
    "Meeting",
    "Discussion",
    "Documentation",
    "Testing",
)
