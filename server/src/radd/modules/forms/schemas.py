import uuid
from datetime import date
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator

from radd.modules.items.enums import ItemKind, Priority
from radd.apitypes import UtcDatetime


class FormField(BaseModel):
    """One field the form exposes, referencing a registry field by key."""

    model_config = ConfigDict(from_attributes=True)

    field_key: str = Field(pattern=r"^[a-z][a-z0-9_]{0,49}$")
    label_override: str | None = Field(default=None, max_length=200)
    help: str | None = Field(default=None, max_length=1000)
    required: bool = False  # may be True even if the registry field is optional


class FormDefaults(BaseModel):
    """Values applied to the item a submission creates (RADD-801), addressed by
    NAME and resolved at submit so a renamed state does not break the form; an
    unknown assignee is refused on write. `DEFAULTS_COVERAGE` accounts for every
    `ItemCreate` field and `tests/test_form_defaults.py` fails on a new one, so
    a form cannot silently miss an item attribute again.
    """

    model_config = ConfigDict(from_attributes=True, extra="forbid")

    kind: ItemKind | None = None  # epic | issue | subtask — the hierarchy ladder
    type_name: str | None = None  # spec 51 — Bug / Feature / …, a DIFFERENT axis
    state_name: str | None = None
    priority: Priority | None = None
    labels: list[str] = Field(default_factory=list)
    assignee_email: str | None = None
    cycle_name: str | None = None
    release_version: str | None = None
    start_date: date | None = None
    target_date: date | None = None
    flagged: bool = False
    estimate_points: float | None = Field(default=None, ge=0, le=999)


#: `ItemCreate` field -> the `FormDefaults` key that carries it, or None plus the
#: reason it is deliberately not form-settable. The reasons are the point: the
#: original list had no way to tell a decision from an oversight, which is how
#: three of them accumulated.
DEFAULTS_COVERAGE: dict[str, tuple[str | None, str]] = {
    "title": (None, "the submitter writes it"),
    "description": (None, "the submitter writes it"),
    "project_id": (None, "the form belongs to one project"),
    "custom_fields": (None, "the form's exposed fields carry these"),
    # Spec 121: a submission takes the project's `item_default_visibility`;
    # who may read the resulting issue is the project's policy, not the form's.
    "visibility": (None, "the project's default visibility applies"),
    "kind": ("kind", ""),
    "type_id": ("type_name", ""),
    "state_id": ("state_name", ""),
    "priority": ("priority", ""),
    "labels": ("labels", ""),
    "assignee_id": ("assignee_email", ""),
    "cycle_id": ("cycle_name", ""),
    "release_id": ("release_version", ""),
    "start_date": ("start_date", ""),
    "target_date": ("target_date", ""),
    "flagged": ("flagged", ""),
    "estimate_points": ("estimate_points", ""),
    "parent_id": (None, "a specific item, not a project-level choice"),
    "team_id": (
        None,
        "the SUBMITTER picks it per request (RADD-798), not the form author",
    ),
    "reporter_id": (None, "decided by the submit path — the person filing"),
    "number": (None, "import-only, project.manage-gated"),
    "created_at": (None, "import-only, project.manage-gated"),
    "updated_at": (None, "import-only, project.manage-gated"),
}


class FormCreate(BaseModel):
    project_id: uuid.UUID
    name: str = Field(min_length=1, max_length=200)
    description: str = ""
    enabled: bool = True
    fields: list[FormField] = Field(default_factory=list)
    defaults: FormDefaults = Field(default_factory=FormDefaults)
    title_prompt: str = Field(default="Summary", min_length=1, max_length=200)
    # The item-description area on the submit page (on by default).
    description_enabled: bool = True
    description_prompt: str = Field(default="Description", min_length=1, max_length=200)
    description_required: bool = False
    #: RADD-798 — offer a team picker on the submit page (off by default).
    team_picker_enabled: bool = False


class FormUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = None
    enabled: bool | None = None
    fields: list[FormField] | None = None  # full replacement when provided
    defaults: FormDefaults | None = None  # full replacement when provided
    title_prompt: str | None = Field(default=None, min_length=1, max_length=200)
    description_enabled: bool | None = None
    description_prompt: str | None = Field(default=None, min_length=1, max_length=200)
    description_required: bool | None = None
    team_picker_enabled: bool | None = None
    # Portal visibility: every signed-in user may see and submit (spec 73).
    allow_public: bool | None = None


class FormShareEntry(BaseModel):
    """One portal share subject (spec 73) — exactly one of user_id/team_id (422)."""

    user_id: uuid.UUID | None = None
    team_id: uuid.UUID | None = None

    @model_validator(mode="after")
    def _one_subject(self) -> "FormShareEntry":
        if (self.user_id is None) == (self.team_id is None):
            raise ValueError("exactly one of user_id/team_id is required")
        return self


class FormSharingUpdate(BaseModel):
    """PUT /forms/{id}/sharing — the FULL share list, replaced wholesale (spec 73)."""

    shares: list[FormShareEntry] = Field(default_factory=list)


class FormShareRead(BaseModel):
    """One persisted grant row (`FormRead.shares`, manage surfaces only). The
    builder hydrates subject names from its own users/teams queries."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    user_id: uuid.UUID | None
    team_id: uuid.UUID | None
    created_at: UtcDatetime


class FormShareDirectoryRead(FormShareRead):
    subject_name: str | None = None
    active: bool | None = None


class FormValidationContext(BaseModel):
    """Whether intake validation governs submissions through this form (spec 119).

    Rides on the form's own render payload rather than sending the portal to
    `GET /items/validate/context`, because a portal visitor's right to be here is
    the SHARE — they may hold no `item.create` anywhere, and an endpoint gated on
    that atom would 403 exactly the people this form exists for.
    """

    governed: bool = False
    #: `"advisory"` | `"required"`, or null when nothing governs. A plain string:
    #: `forms` does not import an optional module's enum to describe a fact that
    #: module computed.
    mode: str | None = None


class FormRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    project_id: uuid.UUID
    name: str
    description: str
    enabled: bool
    fields: list[FormField]
    defaults: FormDefaults
    title_prompt: str
    description_enabled: bool
    description_prompt: str
    description_required: bool
    team_picker_enabled: bool
    allow_public: bool
    # Portal shares (spec 73) — populated on the form.manage surfaces (list/
    # update/sharing) for the builder; empty on the plain submit render.
    shares: list[FormShareRead] = Field(default_factory=list)
    #: Spec 119 context, filled on the SUBMIT render only; null = "not asked".
    validation: FormValidationContext | None = None
    created_at: UtcDatetime
    updated_at: UtcDatetime


class FormSubmit(BaseModel):
    """A submission: a title plus the exposed fields' values."""

    title: str = Field(min_length=1, max_length=500)
    description: str = ""  # ignored unless the form's description area is enabled
    values: dict[str, Any] = Field(default_factory=dict)
    team_id: uuid.UUID | None = None  # RADD-798: share with one of MY teams (re-checked)
    #: RADD-800: staged attachments this submission CLAIMS (named, so other tabs keep theirs).
    attachment_ids: list[uuid.UUID] = Field(default_factory=list)
    #: Spec 119: "pass" (default) or "always" (create anyway; 409 where a check is
    #: required). A plain string — forms does not import automations' enum.
    commit: str = "pass"


# --- portal render and submit shapes (the trimmed public face of a form) ---


class PublicFormField(BaseModel):
    """One exposed field with the definition bits the submit widgets need — a
    deliberately trimmed FieldDefinitionRead (no ids or grants)."""

    field_key: str
    label: str  # label_override else the definition name
    help: str | None
    required: bool  # the form's own override
    type: str  # FieldType wire value
    options: list[str] | None
    display: str | None  # FieldDisplay wire value (render hint)
    default_value: Any | None


class PublicFormRead(BaseModel):
    """The trimmed render payload: field definitions inlined (no registry access)."""

    name: str
    description: str
    title_prompt: str
    description_enabled: bool
    description_prompt: str
    description_required: bool
    fields: list[PublicFormField]


class PublicSubmitResult(BaseModel):
    """What a submitter learns: the created issue's key and title."""

    key: str
    title: str


class PortalProjectRef(BaseModel):
    """The project chrome a portal visitor sees — id/key/name, nothing more."""

    id: uuid.UUID
    key: str
    name: str


class PortalFormCard(BaseModel):
    """One directory card: no tokens, no field config (trimmed by design)."""

    id: uuid.UUID
    name: str
    description: str


class PortalGroup(BaseModel):
    """GET /portal/forms — eligible forms grouped by project."""

    project: PortalProjectRef
    forms: list[PortalFormCard]


class PortalRequestRead(BaseModel):
    """One request as its requester may see it (RADD-785): key, title, where it is
    — never a back door into the issue's contents."""

    key: str
    title: str
    state: str
    #: Workflow category (todo/in_progress/done/canceled) — enough to render
    #: progress without exposing the project's state vocabulary as a filter.
    state_category: str
    project: PortalProjectRef
    #: RADD-797 — the status a requester actually needs. Each of these is inside
    #: the relationship boundary above: a NAME from the member-floor people
    #: directory, a version string, and two numbers derived from PUBLIC comments.
    assignee: str | None = None  # None = unassigned, which is itself an answer
    release: str | None = None  # the version that shipped it
    #: RADD-798 — the team it was shared with, and the key the surfaces group by.
    team: str | None = None
    team_id: uuid.UUID | None = None
    #: PUBLIC comments only. A count over the unfiltered set would leak that
    #: internal discussion exists and how much of it there is.
    comment_count: int = 0
    #: The last PUBLIC comment was not the reporter's — "someone answered you".
    #: The single reason a requester has to come back to this list.
    awaiting_requester: bool = False
    created_at: UtcDatetime
    updated_at: UtcDatetime


class PortalRequestComment(BaseModel):
    email_signature: str | None = None
    """One PUBLIC comment on a request, as a requester may see it."""

    id: uuid.UUID
    author: str  # name only — the directory shape (RADD-769)
    author_is_me: bool
    body: str
    created_at: UtcDatetime


class PortalRequestDetail(PortalRequestRead):
    email_signature: str | None = None
    """One request opened (RADD-796): the row, plus what you came to read.

    Everything omitted is omitted deliberately — no labels, no custom fields, no
    worklogs, no history, and no internal comments. A requester is admitted by
    relationship, and the relationship entitles them to their own conversation,
    not to the project's working notes.
    """

    description: str = ""
    comments: list[PortalRequestComment] = Field(default_factory=list)


class PortalRequestReply(BaseModel):
    """A requester's reply. Visibility is not a field: it is forced public at the
    seam, so this cannot be a way to write into the internal thread."""

    body: str = Field(min_length=1, max_length=20_000)


class PortalTeamOption(BaseModel):
    """A team the SUBMITTER belongs to — the only teams a picker may offer."""

    id: uuid.UUID
    name: str


class PortalFormRead(PublicFormRead):
    """GET /portal/forms/{id}: the trimmed form plus the ids an authed page needs."""

    id: uuid.UUID
    project: PortalProjectRef
    #: RADD-798 — the teams THIS submitter may share with. Empty when the form
    #: has no picker, or when the person belongs to no team; either way the
    #: client renders nothing, and the server re-checks whatever comes back.
    teams: list[PortalTeamOption] = Field(default_factory=list)
    #: Spec 119 — what the submit button should say and whether "submit anyway"
    #: is on offer.
    validation: FormValidationContext = Field(default_factory=FormValidationContext)
