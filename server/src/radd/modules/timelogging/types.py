from enum import StrEnum


class WorklogEvent(StrEnum):
    CREATED = "worklog.created"
    UPDATED = "worklog.updated"
    DELETED = "worklog.deleted"
    # RADD-1102: estimate set/cleared — what makes another client's board
    # refresh; the SPA's `item_estimate` realtime mapping existed for a year
    # with no event that could reach it.
    ESTIMATE_CHANGED = "worklog.estimate_changed"
    # Spec 123: configuration writes, audited with a diff; not triggers.
    CATEGORY_CREATED = "work_category.created"
    CATEGORY_UPDATED = "work_category.updated"
    #: entity = the PROJECT; `changes` = enabled old → new.
    PROJECT_TIMELOGGING_CHANGED = "project.timelogging_changed"


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
