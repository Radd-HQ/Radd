import uuid

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, model_validator

from radd.apitypes import UtcDatetime
from radd.modules.fields.types import FieldType

from .types import (
    BuiltinTarget,
    FieldAction,
    FieldScope,
    ImportStage,
    FieldBand,
    InferredType,
    JiraAuthMode,
    SnapshotStage,
)


class JiraConnectionStatus(BaseModel):
    """GET /jira/status — the wizard's connect step (spec 90)."""

    configured: bool  # at least one connection row exists
    ok: bool  # a live /myself call succeeded
    account: str = ""  # the service account Radd connected as
    auth_mode: str = "none"  # "pat" | "basic" | "none" — which credential is in force
    error: str = ""  # why the check failed, when ok is false
    connection_id: uuid.UUID | None = None  # which connection was checked
    connection_name: str = ""


# --- connections (spec 100) ---------------------------------------------------


class JiraConnectionBase(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    base_url: HttpUrl
    auth_mode: JiraAuthMode = JiraAuthMode.PAT
    username: str = Field(default="", max_length=200)  # basic auth only
    verify_ssl: bool = True
    is_default: bool = False

    @model_validator(mode="after")
    def _basic_auth_needs_a_username(self) -> "JiraConnectionBase":
        if self.auth_mode is JiraAuthMode.BASIC and not self.username:
            raise ValueError("basic auth needs a username")
        return self


class JiraConnectionCreate(JiraConnectionBase):
    credential: str = Field(min_length=1, max_length=500)  # PAT, or the basic password


class JiraConnectionUpdate(BaseModel):
    """PATCH — every field optional. An omitted or EMPTY `credential` keeps the
    stored one, so saving a form built from the redacted read shape is safe."""

    name: str | None = Field(default=None, min_length=1, max_length=100)
    base_url: HttpUrl | None = None
    auth_mode: JiraAuthMode | None = None
    username: str | None = Field(default=None, max_length=200)
    credential: str | None = Field(default=None, max_length=500)
    verify_ssl: bool | None = None
    is_default: bool | None = None


class JiraConnectionRead(BaseModel):
    """The credential is NEVER returned — only whether one is stored."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    base_url: str
    auth_mode: str
    username: str
    verify_ssl: bool
    is_default: bool
    source: str  # "env" (seeded at startup) | "user"
    has_credential: bool
    created_at: UtcDatetime


class JiraProjectRead(BaseModel):
    key: str
    name: str
    id: str
    project_type: str = ""


# --- snapshots (spec 100) -----------------------------------------------------


class SnapshotStart(BaseModel):
    """POST /jira/snapshots — download a JQL result set once, into the cache."""

    name: str = Field(default="", max_length=200)  # blank = named after the project
    jira_project_key: str = Field(min_length=1, max_length=100)
    jql: str = Field(min_length=1, max_length=5000)
    connection_id: uuid.UUID | None = None  # omitted = the default connection
    # Both multiply the download, so they are explicit opt-ins rather than defaults.
    include_attachments: bool = False
    include_history: bool = False


class ProblemRead(BaseModel):
    """One structured failure. The UI groups by (kind, message) and lists the
    affected subjects, instead of printing a truncated list of strings."""

    kind: str
    message: str
    subject: str = ""
    detail: str = ""
    # Where to go and fix it: the mapping tab, and the row within it.
    section: str = ""
    mapping_key: str = ""


class SnapshotRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    connection_id: uuid.UUID | None
    name: str
    jira_project_key: str
    jql: str
    include_attachments: bool
    include_history: bool
    stage: SnapshotStage
    counts: dict[str, int]
    problems: list[ProblemRead]
    issue_count: int
    byte_size: int
    started_at: UtcDatetime | None
    finished_at: UtcDatetime | None
    created_at: UtcDatetime


class JiraPreviewRequest(BaseModel):
    """POST /jira/preview — load a JQL slice to infer the schema (spec 90)."""

    jql: str = Field(min_length=1, max_length=5000)
    sample_size: int = Field(default=50, ge=1, le=200)
    connection_id: uuid.UUID | None = None  # omitted = the default connection
    # The picked Jira project — used to pull the full field OPTION SETS (the field
    # spec) so select values aren't limited to what the sample happened to use.
    project_key: str | None = Field(default=None, max_length=100)


class InferredFieldRead(BaseModel):
    jira_id: str
    name: str
    inferred_type: InferredType
    populated: int
    sample_count: int
    populate_rate: float
    is_builtin: bool
    distinct_count: int = 0
    dominant_ratio: float = 0.0  # 1.0 = one value everywhere (an org-wide default)
    # Spec 100: one ordered band replaces the old `likely_noise` boolean, which
    # could not express "unused" — so a field nothing fills in scored as ordinary
    # data and sat at the top of the grid. Everything outside `in_use` is collapsed
    # AND defaults to `ignore`; `band_reason` is shown so it can be overruled.
    band: FieldBand = FieldBand.IN_USE
    band_reason: str = ""
    schema_key: str = ""  # Jira's stable `schema.custom` type key
    samples: list[str] = Field(default_factory=list)
    distinct_values: list[str] | None = None


class JiraPreviewResponse(BaseModel):
    total: int  # full JQL match count (not just the sampled page)
    sampled: int  # how many issues the inference actually looked at
    fields: list[InferredFieldRead] = Field(default_factory=list)


# --- field mappings + import plans (spec 90, phase 2) ------------------------


class FieldMappingEntry(BaseModel):
    """One inbound Jira field's disposition (spec 90). `builtin`/`ignore` need no
    target; `map`/`create` require `target_key`; `create` also carries the new
    field's type/name/options."""

    jira_id: str = Field(min_length=1, max_length=100)
    jira_name: str = Field(default="", max_length=200)
    action: FieldAction
    target_key: str = Field(default="", max_length=50)
    create_type: FieldType | None = None
    # The DISPLAY LABEL for a created field (independent of the snake_case key).
    create_name: str = Field(default="", max_length=200)
    create_options: list[str] | None = None
    # CREATE action: whether the new field is global or scoped to the target project.
    create_scope: FieldScope = FieldScope.GLOBAL
    # NATIVE action only: which Radd feature the value feeds (team/watchers/…).
    builtin_target: BuiltinTarget | None = None
    # Optional per-VALUE translation (spec 90): Jira value → Radd value/entity name.
    # Meaning depends on the target — a team/state name to find-or-create, a
    # remapped select option, etc. Absent/partial = pass the value through.
    value_map: dict[str, str] = Field(default_factory=dict)
    # Evidence, carried so the mapping UI can group rows and say WHY one is
    # collapsed — the same "hidden and ignored unless used" rule the vocabulary
    # tables get from their `count`.
    band: FieldBand = FieldBand.IN_USE
    band_reason: str = ""
    populated: int = 0
    samples: list[str] = Field(default_factory=list)
    # MAP into a select whose option list predates this import: ADD the values it
    # is missing rather than dropping them. Additive only, and ledgered, so
    # rollback restores the original list.
    extend_options: bool = False
    # Every distinct value the snapshot holds for this field — what `extend_options`
    # would add, and what the dry run reports.
    observed_values: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _needs_target(self) -> "FieldMappingEntry":
        if self.action in (FieldAction.MAP, FieldAction.CREATE) and not self.target_key:
            raise ValueError(f"action '{self.action}' requires target_key")
        if self.action is FieldAction.NATIVE and self.builtin_target is None:
            raise ValueError("action 'native' requires builtin_target")
        return self


class ImportPlanCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    jira_project_key: str = Field(min_length=1, max_length=100)
    jql: str = Field(min_length=1, max_length=5000)
    radd_project_key: str = Field(pattern=r"^[A-Za-z][A-Za-z0-9]{0,19}$")
    radd_project_name: str = Field(min_length=1, max_length=200)
    field_mappings: list[FieldMappingEntry] = Field(default_factory=list, max_length=500)


class ImportPlanUpdate(BaseModel):
    """PATCH — omitted keys unchanged."""

    name: str | None = Field(default=None, min_length=1, max_length=200)
    jql: str | None = Field(default=None, min_length=1, max_length=5000)
    radd_project_key: str | None = Field(default=None, pattern=r"^[A-Za-z][A-Za-z0-9]{0,19}$")
    radd_project_name: str | None = Field(default=None, min_length=1, max_length=200)
    field_mappings: list[FieldMappingEntry] | None = None


class ImportPlanRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    jira_project_key: str
    jql: str
    radd_project_key: str
    radd_project_name: str
    field_mappings: list[FieldMappingEntry]
    created_at: UtcDatetime


class SuggestMappingsRequest(BaseModel):
    """POST /jira/plans/suggest — turn a preview's inferred schema into a
    pre-filled mapping grid, given the custom fields Radd already has."""

    fields: list[InferredFieldRead] = Field(min_length=1, max_length=500)


class MappingProblemRead(BaseModel):
    jira_id: str
    message: str


class ValidateMappingsResponse(BaseModel):
    ok: bool
    problems: list[MappingProblemRead] = Field(default_factory=list)


# --- import runs (spec 90, phase 3) ------------------------------------------


class ImportRunStart(BaseModel):
    """POST /jira/runs — kick off a background import from a saved plan."""

    plan_id: uuid.UUID


class ImportRunRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    plan_id: uuid.UUID | None
    jira_project_key: str
    jql: str
    radd_project_key: str
    radd_project_name: str
    # The snapshot of field mappings this run used — replayed by "Redo" so the
    # wizard can reopen on the mapping step with the same choices, editable.
    field_mappings: list[FieldMappingEntry] = Field(default_factory=list)
    stage: ImportStage
    counts: dict[str, int] = Field(default_factory=dict)
    errors: list[str] = Field(default_factory=list)
    started_at: UtcDatetime | None = None
    finished_at: UtcDatetime | None = None
    created_at: UtcDatetime
