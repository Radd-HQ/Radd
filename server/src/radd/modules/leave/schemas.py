import uuid
from datetime import date

from pydantic import BaseModel, Field


class LeaveCreate(BaseModel):
    """Personal leave names a user (defaults to the caller); a holiday names a
    team. Exactly one subject — the service validates."""

    user_id: uuid.UUID | None = None
    team_id: uuid.UUID | None = None
    label: str = Field(default="", max_length=200)
    start_date: date
    end_date: date


class LeaveRead(BaseModel):
    id: uuid.UUID
    user_id: uuid.UUID | None
    team_id: uuid.UUID | None
    team_name: str | None = None
    kind: str
    label: str
    start_date: date
    end_date: date
    created_by: uuid.UUID | None


class LeaveCalendarEntry(BaseModel):
    """One user's absence span inside a requested range — holidays arrive
    pre-expanded to team members, so consumers never join membership."""

    user_id: uuid.UUID
    kind: str
    label: str
    start_date: date
    end_date: date


class CurrentLeave(BaseModel):
    """Someone away TODAY — what the app-wide indicator renders from."""

    user_id: uuid.UUID
    kind: str
    label: str
    until: date
