import uuid
from datetime import date, time

from pydantic import BaseModel, Field


class LeaveCreate(BaseModel):
    """Personal leave names a user (defaults to the caller); a holiday names a
    team. Exactly one subject — the service validates. Times (RADD-1481) are
    wall clock in `timezone`; an absent time covers the whole day at that end,
    and an absent zone resolves subject → actor → UTC."""

    user_id: uuid.UUID | None = None
    team_id: uuid.UUID | None = None
    label: str = Field(default="", max_length=200)
    start_date: date
    end_date: date
    start_time: time | None = None
    end_time: time | None = None
    timezone: str | None = Field(default=None, max_length=64)


class LeaveRead(BaseModel):
    id: uuid.UUID
    user_id: uuid.UUID | None
    user_name: str | None = None
    team_id: uuid.UUID | None
    team_name: str | None = None
    kind: str
    label: str
    start_date: date
    end_date: date
    start_time: time | None
    end_time: time | None
    timezone: str
    created_by: uuid.UUID | None


class LeaveCalendarEntry(BaseModel):
    """One user's absence span inside a requested range — holidays arrive
    pre-expanded to team members, so consumers never join membership."""

    user_id: uuid.UUID
    kind: str
    label: str
    start_date: date
    end_date: date
    start_time: time | None
    end_time: time | None
    timezone: str


class CurrentLeave(BaseModel):
    """Someone away NOW — what the app-wide indicator renders from. `until` is
    the last day; `until_time` narrows it to a wall-clock time in `timezone`."""

    user_id: uuid.UUID
    kind: str
    label: str
    until: date
    until_time: time | None
    timezone: str


class TeamLeaveRef(BaseModel):
    """A team the caller may record leave for (RADD-1481)."""

    id: uuid.UUID
    name: str


class TeamLeaveMember(BaseModel):
    id: uuid.UUID
    name: str
    timezone: str


class TeamLeaveRead(BaseModel):
    """A team's active members and their leave, for its stewards (RADD-1481)."""

    team_id: uuid.UUID
    team_name: str
    members: list[TeamLeaveMember]
    periods: list[LeaveRead]
