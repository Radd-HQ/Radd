import uuid
from datetime import date

from pydantic import BaseModel, Field
from radd.apitypes import UtcDatetime


# --- small embedded refs (hydrated names, so the UI needs no extra lookups) ---


class UserRef(BaseModel):
    id: uuid.UUID
    name: str


class CategoryRef(BaseModel):
    id: uuid.UUID
    name: str


class ItemRef(BaseModel):
    id: uuid.UUID
    key: str  # TD-1234
    title: str
    project_key: str


# --- per-project enablement ---


class ProjectTimeLoggingRead(BaseModel):
    project_id: uuid.UUID
    enabled: bool


class ProjectTimeLoggingUpdate(BaseModel):
    enabled: bool


# --- work categories ---


class WorkCategoryCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100)


class WorkCategoryUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=100)
    archived: bool | None = None


class WorkCategoryRead(BaseModel):
    id: uuid.UUID
    name: str
    position: int
    archived: bool


# --- worklogs ---


class WorklogCreate(BaseModel):
    # Jira-style duration text (`2h 30m`); the server parses it (source of truth).
    time_spent: str = Field(min_length=1)
    worked_on: date | None = None  # defaults to today at the router boundary
    category_id: uuid.UUID | None = None
    note: str = Field(default="", max_length=2000)
    # Attribute the entry to someone other than the caller (imports preserving the
    # original Jira author). Honored only for callers with project.manage; ignored
    # otherwise. None = the acting user, as before.
    author_id: uuid.UUID | None = None
    # Import-only: the original log timestamp (naive UTC). project.manage-gated.
    created_at: UtcDatetime | None = None


class WorklogUpdate(BaseModel):
    # Omitted = unchanged; explicit null on category_id clears it (model_fields_set idiom).
    time_spent: str | None = Field(default=None, min_length=1)
    worked_on: date | None = None
    category_id: uuid.UUID | None = None
    note: str | None = Field(default=None, max_length=2000)


class WorklogRead(BaseModel):
    id: uuid.UUID
    # Spec 59: None = an itemless (general) entry anchored to an optional project.
    item_id: uuid.UUID | None
    project_id: uuid.UUID | None = None
    author: UserRef
    category: CategoryRef | None
    worked_on: date
    time_spent_seconds: int
    time_spent: str  # formatted (e.g. "1h 30m")
    note: str
    created_at: UtcDatetime
    updated_at: UtcDatetime


class GeneralWorklogCreate(BaseModel):
    """POST /worklogs (spec 59): log time with NO issue — meetings/admin/general.
    Anchored to an optional project; a category is REQUIRED (it's the entry's
    identity in every timesheet view)."""

    project_id: uuid.UUID | None = None
    category_id: uuid.UUID
    time_spent: str = Field(min_length=1)
    worked_on: date | None = None
    note: str = Field(default="", max_length=2000)


# --- estimate + per-item summary ---


# Backend cap on one POST /items/timelog/batch request (spec 78).
TIMELOG_BATCH_MAX_ITEMS = 200


class TimelogBatchRequest(BaseModel):
    """Item ids the roadmap wants estimate/logged seconds for (spec 78 —
    auto-schedule durations); sla/batch shape, schema-capped."""

    item_ids: list[uuid.UUID] = Field(max_length=TIMELOG_BATCH_MAX_ITEMS)


class ItemTimeBatchEntry(BaseModel):
    """One item's raw seconds in the batch response — None/0 = no estimate/logs."""

    estimate_seconds: int | None = None
    logged_seconds: int = 0


class EstimateSet(BaseModel):
    estimate: str = Field(min_length=1)  # duration text


class ItemTimeSummary(BaseModel):
    item_id: uuid.UUID
    enabled: bool  # is time logging enabled on the item's project?
    original_estimate_seconds: int | None
    original_estimate: str | None
    logged_seconds: int
    logged: str
    remaining_seconds: int | None  # estimate − logged (may be negative = overlogged)
    remaining: str | None
    entries: list[WorklogRead]


# --- timesheet (aggregation for the weekly/daily/monthly report) ---


class TimesheetEntry(BaseModel):
    id: uuid.UUID
    worked_on: date
    time_spent_seconds: int
    user: UserRef
    # Spec 59: None = an itemless (general) entry — `category` is its identity
    # and `project_key` its optional project anchor.
    item: ItemRef | None
    #: The epic `item` belongs to (spec 22 follow-up) — the client groups by it.
    #: `item` itself when the time was logged onto an epic; None for general
    #: worklogs and for issues outside any epic.
    epic: ItemRef | None = None
    project_key: str | None = None
    category: CategoryRef | None
    note: str


class Timesheet(BaseModel):
    start: date
    end: date
    total_seconds: int
    entries: list[TimesheetEntry]
    # Outlier-flag config, resolved from the settings cascade so
    # the client never hardcodes thresholds; `work_days` gates under-logging
    # flags to actual working days ("mon".."sun").
    day_min_hours: int = 6
    day_max_hours: int = 10
    work_days: list[str] = []
