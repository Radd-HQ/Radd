import uuid
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
    """Values applied to the item a submission creates. Names (state/label/cycle/release)
    resolve at submit; an unknown assignee is rejected on write."""

    model_config = ConfigDict(from_attributes=True, extra="forbid")

    kind: ItemKind | None = None
    state_name: str | None = None
    priority: Priority | None = None
    labels: list[str] = Field(default_factory=list)
    assignee_email: str | None = None
    cycle_name: str | None = None
    release_version: str | None = None


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
    # Spec 62: toggle the tokened no-login submit path (token minted on first enable).
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
    allow_public: bool
    public_token: str | None
    # Portal shares (spec 73) — populated on the form.manage surfaces (list/
    # update/sharing) for the builder; empty on the plain submit render.
    shares: list[FormShareRead] = Field(default_factory=list)
    created_at: UtcDatetime
    updated_at: UtcDatetime


class FormSubmit(BaseModel):
    """A public-shaped submission: a title plus the exposed fields' values."""

    title: str = Field(min_length=1, max_length=500)
    description: str = ""  # ignored unless the form's description area is enabled
    values: dict[str, Any] = Field(default_factory=dict)


# --- public, unauthenticated path (spec 62) ---


class PublicFormField(BaseModel):
    """One exposed field with the definition bits the submit widgets need —
    a deliberately trimmed FieldDefinitionRead (no ids/grants leak publicly)."""

    field_key: str
    label: str  # label_override else the definition name
    help: str | None
    required: bool  # the form's own override
    type: str  # FieldType wire value
    options: list[str] | None
    display: str | None  # FieldDisplay wire value (render hint)
    default_value: Any | None


class PublicFormRead(BaseModel):
    """GET /public/forms/{token} — the render payload (FormRead's public face):
    fields carry their definitions inline since the registry isn't reachable
    without a login."""

    name: str
    description: str
    title_prompt: str
    description_enabled: bool
    description_prompt: str
    description_required: bool
    fields: list[PublicFormField]


class PublicFormSubmit(BaseModel):
    """POST /public/forms/{token}: the FormSubmit shape plus who is asking.
    The email is trusted (no verification loop, v1) — matching an active user
    makes them the reporter, anything else becomes the item's mail contact."""

    title: str = Field(min_length=1, max_length=500)
    description: str = ""
    values: dict[str, Any] = Field(default_factory=dict)
    email: str = Field(min_length=3, max_length=320, pattern=r"^[^@\s]+@[^@\s]+$")
    name: str = Field(default="", max_length=200)


class PublicSubmitResult(BaseModel):
    """What an anonymous submitter learns: the created issue key, nothing more."""

    key: str
    title: str


class PublicDeflectDoc(BaseModel):
    """One public-KB hit under the public form's title input (spec 74) —
    mirrors the authed deflect docs shape (search/schemas.DeflectDoc) so the
    SPA panel can reuse its rendering. Defined here, not imported: forms must
    not depend on the search module."""

    id: uuid.UUID  # page id
    space_id: uuid.UUID
    title: str
    space_name: str


class PublicDeflectResponse(BaseModel):
    """GET /public/forms/{token}/deflect — docs ONLY: resolved issues stay
    internal; only public wiki pages deflect anonymous visitors."""

    docs: list[PublicDeflectDoc]


# --- requester portal (spec 73) ---


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
    """One request the actor filed, as a requester may see it (RADD-785).

    Deliberately narrow. A requester is scoped by their RELATIONSHIP to the row
    (`reporter_id`), not by `item.read`, so this must not become a back door
    into an issue's contents: no description, no comments, no assignee, no
    labels, no custom fields. What is here is what "where has my request got to"
    needs — its key, its title, and the state it is in.
    """

    key: str
    title: str
    state: str
    #: Workflow category (todo/in_progress/done/canceled) — enough to render
    #: progress without exposing the project's state vocabulary as a filter.
    state_category: str
    project: PortalProjectRef
    created_at: UtcDatetime
    updated_at: UtcDatetime


class PortalFormRead(PublicFormRead):
    """GET /portal/forms/{id} — the spec-62 public trimming plus the ids an
    AUTHED page needs: the form id and the project ref (header chip + the KB
    deflection panel's project scope)."""

    id: uuid.UUID
    project: PortalProjectRef
