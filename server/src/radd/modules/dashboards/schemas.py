import uuid
from typing import Annotated, Any, Literal

from pydantic import BaseModel, Field, model_validator

from radd.apitypes import UtcDatetime
from radd.modules.items.enums import ItemKind
from radd.modules.reporting.service import SLA_REPORT_MAX_WEEKS
from radd.modules.reporting.types import ReportInterval, ReportMeasure
from radd.modules.views.schemas import ShareGroupRef, ShareTeamRef, ShareUserRef

from .types import ShareLevel, WidgetType

# Grid thirds a widget may span (the /dashboards page is a 3-column CSS grid).
WIDGET_MIN_WIDTH = 1
WIDGET_MAX_WIDTH = 3
# slq_list renders a compact card — hard row cap (spec 75).
SLQ_LIST_MAX_LIMIT = 20
# Mirrors the /reports/velocity `last` bound.
VELOCITY_MAX_LAST = 50
DASHBOARD_MAX_SHARES = 50

_width_field = Field(default=1, ge=WIDGET_MIN_WIDTH, le=WIDGET_MAX_WIDTH)


# --- per-type widget configs (the JSONB payloads, shape-validated here; the
# --- references [project/cycle/view, SLQ compile] are checked in widgets.py) ---


class ReportProjectConfig(BaseModel):
    """report_throughput / report_cfd — {project_id, interval?}."""

    project_id: uuid.UUID
    interval: ReportInterval = ReportInterval.WEEK


class ReportTimeInStateConfig(BaseModel):
    """report_time_in_state — {project_id, kind?} (kind null = all kinds)."""

    project_id: uuid.UUID
    kind: ItemKind | None = None


class ReportVelocityConfig(BaseModel):
    """report_velocity — {last?, measure?} (spec 86: global scope, no input id)."""

    last: int = Field(default=5, ge=1, le=VELOCITY_MAX_LAST)
    measure: ReportMeasure = ReportMeasure.COUNT


class ReportBurnupConfig(BaseModel):
    """report_burnup — {cycle_id, measure?} (the cycle is PINNED, not picked)."""

    cycle_id: uuid.UUID
    measure: ReportMeasure = ReportMeasure.COUNT


class ReportSlaConfig(BaseModel):
    """report_sla — {project_id?, weeks?} (spec 86: global scope)."""

    project_id: uuid.UUID | None = None
    weeks: int = Field(default=12, ge=1, le=SLA_REPORT_MAX_WEEKS)


class SlqCountConfig(BaseModel):
    """slq_count — a big-number card over GET /items/count. '' = everything in
    scope; `label` is the number's caption (falls back to the widget title)."""

    project_id: uuid.UUID | None = None
    q: str = Field(default="", max_length=2000)
    label: str | None = Field(default=None, max_length=60)


class SlqListConfig(BaseModel):
    """slq_list — compact item rows over GET /items?q=&limit=."""

    project_id: uuid.UUID | None = None
    q: str = Field(default="", max_length=2000)
    limit: int = Field(default=10, ge=1, le=SLQ_LIST_MAX_LIMIT)


class ViewCountConfig(BaseModel):
    """view_count — a saved view's membership count via POST /views/counts.
    The view must be VISIBLE to the writer (409); per-VIEWER visibility still
    applies at render (an invisible view's count is simply omitted)."""

    view_id: uuid.UUID


# (widget_type) -> its config model — PATCH revalidates a stored widget's new
# config against this map (create goes through the discriminated union below).
WIDGET_CONFIG_MODELS: dict[WidgetType, type[BaseModel]] = {
    WidgetType.REPORT_THROUGHPUT: ReportProjectConfig,
    WidgetType.REPORT_CFD: ReportProjectConfig,
    WidgetType.REPORT_TIME_IN_STATE: ReportTimeInStateConfig,
    WidgetType.REPORT_VELOCITY: ReportVelocityConfig,
    WidgetType.REPORT_BURNUP: ReportBurnupConfig,
    WidgetType.REPORT_SLA: ReportSlaConfig,
    WidgetType.SLQ_COUNT: SlqCountConfig,
    WidgetType.SLQ_LIST: SlqListConfig,
    WidgetType.VIEW_COUNT: ViewCountConfig,
}


# --- widget create: a discriminated union on widget_type (the automations
# --- Action idiom) so an unknown type or a config of the wrong shape 422s ---


class _WidgetBase(BaseModel):
    """Fields every widget carries; `config` is typed per member below."""

    title: str | None = Field(default=None, max_length=200)
    width: int = _width_field
    position: int = Field(default=0, ge=0)


class ThroughputWidget(_WidgetBase):
    widget_type: Literal[WidgetType.REPORT_THROUGHPUT]
    config: ReportProjectConfig


class CfdWidget(_WidgetBase):
    widget_type: Literal[WidgetType.REPORT_CFD]
    config: ReportProjectConfig


class TimeInStateWidget(_WidgetBase):
    widget_type: Literal[WidgetType.REPORT_TIME_IN_STATE]
    config: ReportTimeInStateConfig


class VelocityWidget(_WidgetBase):
    widget_type: Literal[WidgetType.REPORT_VELOCITY]
    config: ReportVelocityConfig


class BurnupWidget(_WidgetBase):
    widget_type: Literal[WidgetType.REPORT_BURNUP]
    config: ReportBurnupConfig


class SlaWidget(_WidgetBase):
    widget_type: Literal[WidgetType.REPORT_SLA]
    config: ReportSlaConfig


class SlqCountWidget(_WidgetBase):
    widget_type: Literal[WidgetType.SLQ_COUNT]
    config: SlqCountConfig


class SlqListWidget(_WidgetBase):
    widget_type: Literal[WidgetType.SLQ_LIST]
    config: SlqListConfig


class ViewCountWidget(_WidgetBase):
    widget_type: Literal[WidgetType.VIEW_COUNT]
    config: ViewCountConfig


WidgetCreate = Annotated[
    ThroughputWidget
    | CfdWidget
    | TimeInStateWidget
    | VelocityWidget
    | BurnupWidget
    | SlaWidget
    | SlqCountWidget
    | SlqListWidget
    | ViewCountWidget,
    Field(discriminator="widget_type"),
]


class PluginWidget(_WidgetBase):
    """A plugin-contributed widget type (spec 94): `widget_type` is a key in
    `registries.widget_types` and `config` is a free-form dict the plugin owns +
    interprets. The discriminated union above can't carry a catch-all, so the
    create endpoint validates a non-builtin type against this instead."""

    widget_type: str
    config: dict[str, Any] = Field(default_factory=dict)


class WidgetUpdate(BaseModel):
    """PATCH a widget — omitted = unchanged; explicit null `title` clears the
    override (model_fields_set idiom). `config`, when present, revalidates
    against the widget's STORED type (shape 422 + references 409/422) —
    widget_type itself is immutable: remove + re-add to change kinds."""

    title: str | None = Field(default=None, max_length=200)
    width: int | None = Field(default=None, ge=WIDGET_MIN_WIDTH, le=WIDGET_MAX_WIDTH)
    position: int | None = Field(default=None, ge=0)
    config: dict[str, Any] | None = None


class WidgetRead(BaseModel):
    id: uuid.UUID
    # Builtin values read back as the enum; a plugin-contributed widget_type
    # (registries.widget_types) stays a raw string (spec 94).
    widget_type: WidgetType | str
    title: str | None
    width: int
    position: int
    config: dict[str, Any]


# --- dashboard CRUD + sharing (the spec-57 shapes, verbatim) ---


class DashboardShareEntry(BaseModel):
    """One sharing grant to write: exactly one of user_id/team_id/group_id
    (groups are grant subjects since RADD-832)."""

    user_id: uuid.UUID | None = None
    team_id: uuid.UUID | None = None
    group_id: uuid.UUID | None = None
    level: ShareLevel = ShareLevel.VIEWER

    @model_validator(mode="after")
    def _one_subject(self) -> "DashboardShareEntry":
        named = [x for x in (self.user_id, self.team_id, self.group_id) if x is not None]
        if len(named) != 1:
            raise ValueError("exactly one of user_id/team_id/group_id is required")
        return self


class DashboardSharingUpdate(BaseModel):
    """PUT /dashboards/{id}/sharing — the dashboard's PUBLIC access level
    (spec 92; owner/co-owner-gated). Per-subject shares are managed through the
    generic /grants API now, exactly as view shares are."""

    global_access: ShareLevel | None = None


class DashboardTransfer(BaseModel):
    """POST /dashboards/{id}/transfer — reassign `owner_id`. The previous owner
    is kept on as an editor grantee (no accidental lockout)."""

    user_id: uuid.UUID


class DashboardCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    description: str = Field(default="", max_length=2000)
    # Sharing at birth (spec 57 idiom): global_access needs dashboard.create.
    global_access: ShareLevel | None = None
    shares: list[DashboardShareEntry] = Field(default_factory=list, max_length=DASHBOARD_MAX_SHARES)
    position: int = Field(default=0, ge=0)


class DashboardUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=100)
    description: str | None = Field(default=None, max_length=2000)
    position: int | None = Field(default=None, ge=0)


class DashboardShareRead(BaseModel):
    id: uuid.UUID
    level: ShareLevel
    user: ShareUserRef | None = None
    team: ShareTeamRef | None = None
    group: ShareGroupRef | None = None


class DashboardRead(BaseModel):
    id: uuid.UUID
    name: str
    description: str
    owner_id: uuid.UUID | None
    owner: ShareUserRef | None = None
    global_access: ShareLevel | None = None
    shares: list[DashboardShareRead] = Field(default_factory=list)
    # Visible beyond the owner (server-wide or any grant).
    shared: bool
    # Per-ACTOR capabilities, computed server-side (the client never re-derives
    # team membership): edit = definition + widgets; manage = sharing + delete.
    can_edit: bool = False
    can_manage: bool = False
    position: int
    widgets: list[WidgetRead] = Field(default_factory=list)
    created_at: UtcDatetime
    updated_at: UtcDatetime
