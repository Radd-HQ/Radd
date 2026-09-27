import uuid

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .types import SlaKind, SlaMetOn
from radd.apitypes import UtcDatetime
from radd.modules.items.enums import Priority
from radd.modules.reporting.schemas import ReportScope

# The batch endpoint caps one request at a page of list/board chips (spec 63).
SLA_BATCH_MAX_ITEMS = 200

# GET /sla-report's window, in ISO weeks (spec 63).
SLA_REPORT_DEFAULT_WEEKS = 12
SLA_REPORT_MAX_WEEKS = 26

BUSINESS_MINUTE_MAX = 24 * 60 - 1  # last valid minute-from-midnight (23:59)


class SlaWidgetConfig(BaseModel):
    """The `report_sla` dashboard widget's stored config (RADD-1462): the report's own
    scope — one project or every readable one — and its window, bounded like the
    endpoint's `weeks`. Dashboards validates a write against this; who may READ the
    project is the endpoint's question at render time."""

    project_id: uuid.UUID | None = None
    weeks: int = Field(default=SLA_REPORT_DEFAULT_WEEKS, ge=1, le=SLA_REPORT_MAX_WEEKS)


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
    # RADD-1043: issue-type filter ([] = all), same first-match semantics.
    issue_type_ids: list[uuid.UUID] = Field(default_factory=list)
    position: int = Field(default=0, ge=0)
    business_start_minute: int | None = Field(default=None, ge=0, le=BUSINESS_MINUTE_MAX)
    business_end_minute: int | None = Field(default=None, ge=0, le=BUSINESS_MINUTE_MAX)
    # Spec 69: sla.due_soon fires when remaining time drops to this (None = off).
    warning_minutes: int | None = Field(default=None, ge=1)
    # RADD-1299: applies only when the reporter is in one of these teams ([] = anyone).
    reporter_team_ids: list[uuid.UUID] = Field(default_factory=list)
    # RADD-1299: what satisfies each target, plus the states / teams its mode names.
    response_met_on: SlaMetOn = SlaMetOn.FIRST_REPLY
    response_state_ids: list[uuid.UUID] = Field(default_factory=list)
    response_team_ids: list[uuid.UUID] = Field(default_factory=list)
    resolution_met_on: SlaMetOn = SlaMetOn.DONE
    resolution_state_ids: list[uuid.UUID] = Field(default_factory=list)
    resolution_team_ids: list[uuid.UUID] = Field(default_factory=list)

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
    # Omitted = unchanged; `[]` clears the filter back to "every type".
    issue_type_ids: list[uuid.UUID] | None = None
    position: int | None = Field(default=None, ge=0)
    # Explicit null clears the window (model_fields_set idiom, like the targets).
    business_start_minute: int | None = Field(default=None, ge=0, le=BUSINESS_MINUTE_MAX)
    business_end_minute: int | None = Field(default=None, ge=0, le=BUSINESS_MINUTE_MAX)
    # Explicit null turns the pre-breach warning off (model_fields_set idiom).
    warning_minutes: int | None = Field(default=None, ge=1)
    # RADD-1299 — omitted = unchanged; `[]` clears a list.
    reporter_team_ids: list[uuid.UUID] | None = None
    response_met_on: SlaMetOn | None = None
    response_state_ids: list[uuid.UUID] | None = None
    response_team_ids: list[uuid.UUID] | None = None
    resolution_met_on: SlaMetOn | None = None
    resolution_state_ids: list[uuid.UUID] | None = None
    resolution_team_ids: list[uuid.UUID] | None = None


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
    issue_type_ids: list[uuid.UUID]
    position: int
    business_start_minute: int | None
    business_end_minute: int | None
    warning_minutes: int | None
    reporter_team_ids: list[uuid.UUID]
    response_met_on: SlaMetOn
    response_state_ids: list[uuid.UUID]
    response_team_ids: list[uuid.UUID]
    resolution_met_on: SlaMetOn
    resolution_state_ids: list[uuid.UUID]
    resolution_team_ids: list[uuid.UUID]
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


class SlaReportBucket(BaseModel):
    """Service-desk SLA outcomes for items CREATED in one ISO week (spec 63).

    Averages are wall-clock seconds from item creation to the engine's met
    stamps. The csat fields (spec 65) bucket by the week the RESPONSE arrived —
    responded_at, NOT the item-created week the SLA counters use — and stay
    empty (None / 0) while the csat plugin is not loaded (RADD-1386).
    """

    week: str  # the Monday of the ISO week (ISO date)
    items: int  # distinct items with SLA bookkeeping in the bucket
    response_met: int
    response_breached: int
    resolution_met: int
    resolution_breached: int
    breach_rate: float  # items with any breach / items (0 when items == 0)
    avg_response_seconds: float | None  # None = nothing met in the bucket
    avg_resolution_seconds: float | None
    csat_avg: float | None  # mean rating of responses landing in the week (spec 65)
    csat_count: int  # responses landing in the week


class SlaReport(BaseModel):
    buckets: list[SlaReportBucket]
    scope: ReportScope
