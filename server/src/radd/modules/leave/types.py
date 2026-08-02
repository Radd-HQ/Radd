from enum import StrEnum


class LeaveKind(StrEnum):
    """Personal leave (a user's absence) vs a team holiday (regional public
    holiday applying to every member of a team)."""

    LEAVE = "leave"
    HOLIDAY = "holiday"


class LeaveEvent(StrEnum):
    CREATED = "leave.created"
    DELETED = "leave.deleted"


class LeaveEntity(StrEnum):
    LEAVE = "leave"
