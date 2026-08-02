import uuid

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .types import SlaKind
from radd.apitypes import UtcDatetime
from radd.modules.items.enums import Priority

# The batch endpoint caps one request at a page of list/board chips (spec 63).
SLA_BATCH_MAX_ITEMS = 200

BUSINESS_MINUTE_MAX = 24 * 60 - 1  # last valid minute-from-midnight (23:59)


class PolicyCreate(BaseModel):
    # Spec 67: policies are project-level. PolicyUpdate cannot move a policy to
    # another project.
    project_id: uuid.UUID
    name: str = Field(min_length=1, max_length=200)
    enabled: bool = True
    response_minutes: int | None = Field(default=None, ge=1)
    resolution_minutes: int | None = Field(default=None, ge=1)
    pause_state_names: list[str] = Field(default_factory=list)
    # Count only the instance work week (spec 35) — weekends pause the clock.
    work_week_only: bool = False
    # Spec 63: priority filter ([] = all) + first-match order + business hours.
    priorities: list[Priority] = Field(default_factory=list)
    position: int = Field(default=0, ge=0)
    business_start_minute: int | None = Field(default=None, ge=0, le=BUSINESS_MINUTE_MAX)
    business_end_minute: int | None = Field(default=None, ge=0, le=BUSINESS_MINUTE_MAX)
    # Spec 69: sla.due_soon fires when remaining time drops to this (None = off).
    warning_minutes: int | None = Field(default=None, ge=1)

    @model_validator(mode="after")
    def _at_least_one_target(self) -> "PolicyCreate":
        if self.response_minutes is None and self.resolution_minutes is None:
            raise ValueError("a policy needs a response and/or resolution target")
        return self


class PolicyUpdate(BaseModel):
    # Omitted = unchanged; explicit null clears a target (model_fields_set idiom).
    name: str | None = Field(default=None, min_length=1, max_length=200)
    enabled: bool | None = None
    response_minutes: int | None = Field(default=None, ge=1)
    resolution_minutes: int | None = Field(default=None, ge=1)
    pause_state_names: list[str] | None = None
    work_week_only: bool | None = None
    priorities: list[Priority] | None = None
    position: int | None = Field(default=None, ge=0)
    # Explicit null clears the window (model_fields_set idiom, like the targets).
    business_start_minute: int | None = Field(default=None, ge=0, le=BUSINESS_MINUTE_MAX)
    business_end_minute: int | None = Field(default=None, ge=0, le=BUSINESS_MINUTE_MAX)
    # Explicit null turns the pre-breach warning off (model_fields_set idiom).
    warning_minutes: int | None = Field(default=None, ge=1)


class PolicyRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    project_id: uuid.UUID
    name: str
    enabled: bool
    response_minutes: int | None
    resolution_minutes: int | None
    pause_state_names: list[str]
    work_week_only: bool
    priorities: list[Priority]
    position: int
    business_start_minute: int | None
    business_end_minute: int | None
    warning_minutes: int | None
    created_at: UtcDatetime
    updated_at: UtcDatetime


class TimerRead(BaseModel):
    kind: SlaKind
    target_minutes: int
    due_at: UtcDatetime | None
    met_at: UtcDatetime | None
    breached: bool
    paused: bool
    remaining_seconds: float | None


class ItemSlaEntry(BaseModel):
    policy_id: uuid.UUID
    policy_name: str
    timers: list[TimerRead]


class ItemSlaRead(BaseModel):
    entries: list[ItemSlaEntry]


class SlaBatchRequest(BaseModel):
    """Item ids a list/board page wants SLA chips for (spec 63)."""

    item_ids: list[uuid.UUID] = Field(max_length=SLA_BATCH_MAX_ITEMS)


class BatchTimerRead(BaseModel):
    """One timer of an item's matched policy — the list/board chip payload."""

    policy_name: str
    kind: SlaKind
    due_at: UtcDatetime | None
    met_at: UtcDatetime | None
    breached: bool
    paused: bool
    remaining_seconds: float | None
