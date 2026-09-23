import uuid
from datetime import date

from pydantic import BaseModel, ConfigDict, Field

from .types import CycleStatus
from radd.apitypes import UtcDatetime


class CycleCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    # RADD-1291: the home project; None = an instance cycle. A project's
    # managers may create cycles homed in it.
    project_id: uuid.UUID | None = None
    # Optional: omit both to create a DRAFT (staging) cycle; set both to schedule it.
    start_date: date | None = None
    end_date: date | None = None
    goal: str = ""
    # Recurring series (Jira-style): register the name's label ("PIPE - 120" → "PIPE",
    # or a bare "PIPE" numbered from `next_number`) so future drafts auto-provision.
    recurring: bool = False
    drafts_ahead: int = Field(default=1, ge=0, le=20)
    # Override the numbering start (an import may already sit at 120). Ignored when
    # the name itself carries a number; defaults to 1 for a bare label.
    next_number: int | None = Field(default=None, ge=1)
    # Cadence (both or neither): future cycles get real timelines — start on this
    # weekday (0=Monday … 6=Sunday), run duration_days, chained back-to-back.
    start_weekday: int | None = Field(default=None, ge=0, le=6)
    duration_days: int | None = Field(default=None, ge=1, le=90)
    # Spec 60 visibility: [] (default) = public; non-empty = those teams only.
    team_ids: list[uuid.UUID] = []


class CycleUpdate(BaseModel):
    # Omitted = unchanged; explicit null on a date CLEARS it (scheduled -> draft),
    # resolved via model_fields_set in the service. Name is required, so no clear.
    name: str | None = Field(default=None, min_length=1, max_length=200)
    start_date: date | None = None
    end_date: date | None = None
    goal: str | None = None
    # Spec 60 visibility: [] = public (everyone), non-empty = those teams only;
    # omitted/None = unchanged.
    team_ids: list[uuid.UUID] | None = None
    # RADD-1291: omitted = unchanged, explicit null = an instance cycle.
    project_id: uuid.UUID | None = None


class CycleRead(BaseModel):
    id: uuid.UUID
    name: str
    start_date: date | None
    end_date: date | None
    goal: str
    status: CycleStatus  # derived (see types.cycle_status); DRAFT when a date is unset
    completed_at: UtcDatetime | None = None  # set by the explicit "Complete cycle" action
    # Spec 60 visibility: [] = public; non-empty = visible to those teams only.
    team_ids: list[uuid.UUID] = []
    project_id: uuid.UUID | None = None  # RADD-1291: the home project, None = instance
    created_at: UtcDatetime
    updated_at: UtcDatetime


class CycleComplete(BaseModel):
    """POST /cycles/{id}/complete — the Jira "Complete sprint" flow: open (not
    done/canceled, not archived) items move to another cycle or the backlog."""

    move_open_to: uuid.UUID | None = None  # None = backlog (clear the items' cycle)
    start_next: bool = False  # give the target cycle dates starting today


class CycleCompleteResult(BaseModel):
    cycle: CycleRead  # now completed
    moved_count: int  # open items re-homed
    next_cycle: CycleRead | None  # the move target (started when start_next)
    provisioned: list[str]  # series draft names auto-created (drafts_ahead top-up)


class CycleSeriesRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    label: str
    drafts_ahead: int
    next_number: int
    start_weekday: int | None  # 0=Monday … 6=Sunday; None = unscheduled drafts
    duration_days: int | None


class CycleSeriesUpdate(BaseModel):
    # Omitted = unchanged; explicit null on the cadence fields CLEARS the schedule
    # (resolved via model_fields_set in the service).
    drafts_ahead: int | None = Field(default=None, ge=0, le=20)
    next_number: int | None = Field(default=None, ge=1)
    start_weekday: int | None = Field(default=None, ge=0, le=6)
    duration_days: int | None = Field(default=None, ge=1, le=90)


class CycleStats(BaseModel):
    """GET /cycles/{id}/stats — the cycle page's header metrics, honoring the same
    assignee/team filters the item list applies client-side."""

    total: int
    by_category: dict[str, int]  # StateCategory value → item count (archived excluded)
    estimate_seconds: int
    logged_seconds: int
    remaining_seconds: int  # Σ (estimate − logged) over estimated items; negative = over-logged
    estimate: str  # formatted ("2w 1d") with the global hours-per-day
    logged: str
    remaining: str
    # Story points (spec 70): always computed (cheap same-query sums; 0 when no
    # item carries points) — the UI decides whether to show them.
    points_total: float
    points_done: float  # points sitting in done-category states
