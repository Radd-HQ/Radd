"""Wire shapes for the Confluence importer (spec 117)."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from .types import (
    ConfluenceAuthMode,
    GroupAction,
    JiraLinkAction,
    LabelAction,
    MacroAction,
    MappingSection,
    ProblemKind,
    ScopeKind,
    SpaceAction,
    UnresolvedPrincipal,
    UserAction,
)

# --- connections --------------------------------------------------------------


class ConnectionCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    base_url: str = Field(min_length=1, max_length=500)
    auth_mode: ConfluenceAuthMode = ConfluenceAuthMode.PAT
    username: str = ""
    credential: str = ""
    verify_ssl: bool = True
    is_default: bool = False


class ConnectionUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=100)
    base_url: str | None = Field(default=None, min_length=1, max_length=500)
    auth_mode: ConfluenceAuthMode | None = None
    username: str | None = None
    #: Empty = keep the stored credential (the read shape is redacted).
    credential: str | None = None
    verify_ssl: bool | None = None
    is_default: bool | None = None


class ConnectionRead(BaseModel):
    """The credential is NEVER here — `has_credential` stands in for it."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    base_url: str
    auth_mode: ConfluenceAuthMode
    username: str
    has_credential: bool
    verify_ssl: bool
    is_default: bool
    source: str
    external_source: str


class ConnectionStatus(BaseModel):
    """Liveness. Readable with nothing configured — `configured: false` is an
    answer, not an error, so the settings page can render before setup."""

    configured: bool
    ok: bool = False
    detail: str = ""
    connection_id: uuid.UUID | None = None
    user: str = ""


class SpaceRead(BaseModel):
    key: str
    name: str
    id: str = ""
    description: str = ""


class PageNode(BaseModel):
    """One node of the remote tree, for the scope picker."""

    id: str
    title: str
    parent_id: str | None = None
    space_key: str = ""
    position: int = 0
    version: int = 1


# --- snapshots ----------------------------------------------------------------


class ScopeIn(BaseModel):
    kind: ScopeKind
    space_key: str = ""
    root_page_id: str = ""
    page_ids: list[str] = Field(default_factory=list)
    max_depth: int | None = Field(default=None, ge=1, le=20)


class SnapshotCreate(BaseModel):
    name: str = Field(default="", max_length=200)
    connection_id: uuid.UUID | None = None
    scope: ScopeIn
    #: Off by default and deliberately: a live page in a real corpus sits at
    #: version 206, and most migrations want the current wiki, not a decade of
    #: edits. Turning it on is one checkbox.
    include_history: bool = False
    history_limit: int | None = Field(default=None, ge=1)
    include_attachments: bool = True
    include_comments: bool = True


class ProblemRead(BaseModel):
    kind: ProblemKind
    message: str
    subject: str = ""
    detail: str = ""
    section: MappingSection | None = None
    mapping_key: str = ""


class SnapshotRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    connection_id: uuid.UUID | None
    scope: dict
    external_source: str
    base_url: str
    include_history: bool
    history_limit: int | None
    include_attachments: bool
    include_comments: bool
    stage: str
    counts: dict
    problems: list
    page_count: int
    byte_size: int
    started_at: datetime | None
    finished_at: datetime | None


# --- plan ---------------------------------------------------------------------


class SpaceMapping(BaseModel):
    """One Confluence space → a Radd space. `create` makes one; naming an existing
    `space_id` maps into it (which is also how a re-import lands correctly)."""

    key: str
    name: str = ""
    count: int = 0
    action: SpaceAction = SpaceAction.CREATE
    space_id: uuid.UUID | None = None
    target_name: str = ""


class MacroMapping(BaseModel):
    """One macro name, its real usage count, and what to do with it."""

    name: str
    count: int = 0
    action: MacroAction = MacroAction.UNSUPPORTED
    #: The `radd:<extension>` this becomes when the action is EXTENSION.
    extension: str = ""
    sample_page: str = ""
    reason: str = ""


class UserMapping(BaseModel):
    username: str
    display_name: str = ""
    email: str = ""
    count: int = 0
    action: UserAction = UserAction.MAP
    user_id: uuid.UUID | None = None


class GroupMapping(BaseModel):
    """A restriction principal.

    Identity by DN is the default and needs no row here — this table exists for
    the principals that do NOT resolve: a group predating the current directory, a
    deleted user, an instance whose AD was never connected.
    """

    name: str
    count: int = 0
    action: GroupAction = GroupAction.IDENTITY
    group_id: uuid.UUID | None = None
    team_id: uuid.UUID | None = None
    resolved_dn: str = ""


class LabelMapping(BaseModel):
    name: str
    count: int = 0
    action: LabelAction = LabelAction.CREATE
    target: str = ""


class JiraLinkMapping(BaseModel):
    """A Jira project key seen inside a `jira` macro → the Radd project spec 100
    imported it into. Unresolved keys degrade to an external link, never a stub."""

    project_key: str
    count: int = 0
    action: JiraLinkAction = JiraLinkAction.RESOLVE
    radd_project_key: str = ""


class PlanMappings(BaseModel):
    spaces: list[SpaceMapping] = Field(default_factory=list)
    macros: list[MacroMapping] = Field(default_factory=list)
    users: list[UserMapping] = Field(default_factory=list)
    groups: list[GroupMapping] = Field(default_factory=list)
    labels: list[LabelMapping] = Field(default_factory=list)
    jira_links: list[JiraLinkMapping] = Field(default_factory=list)


class PlanOptions(BaseModel):
    #: Notify/webhooks/automations skip the import; search and history do not.
    quiet: bool = True
    include_history: bool = False
    history_limit: int | None = None
    import_comments: bool = True
    import_attachments: bool = True
    import_restrictions: bool = True
    #: What to do with a restriction principal that does not resolve. FAIL is the
    #: default because importing a restricted page OPEN is a data leak.
    unresolved_principal: UnresolvedPrincipal = UnresolvedPrincipal.FAIL
    unresolved_group_id: uuid.UUID | None = None
    unresolved_team_id: uuid.UUID | None = None


class PlanCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    snapshot_id: uuid.UUID


class PlanUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    mappings: PlanMappings | None = None
    options: PlanOptions | None = None


class PlanProblem(BaseModel):
    section: MappingSection
    subject: str
    message: str


class PlanRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    snapshot_id: uuid.UUID
    mappings: dict
    options: dict
    provisioned_at: datetime | None


# --- runs ---------------------------------------------------------------------


class RunStart(BaseModel):
    plan_id: uuid.UUID
    dry_run: bool = False


class RunRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    plan_id: uuid.UUID | None
    snapshot_id: uuid.UUID | None
    kind: str
    dry_run: bool
    stage: str
    counts: dict
    problems: list
    report: dict
    started_at: datetime | None
    finished_at: datetime | None


class RollbackPreflight(BaseModel):
    total: int
    by_entity: dict[str, int]
    edited_since: int
