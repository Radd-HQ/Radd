import uuid

from pydantic import BaseModel, ConfigDict

from .types import ScreenPlacement


class ScreenFieldRow(BaseModel):
    """One field's placement in a screen. `field` = a builtin token or `cf:<key>`."""

    model_config = ConfigDict(from_attributes=True)

    field: str
    placement: ScreenPlacement


class ScreenReplace(BaseModel):
    """PUT /screens — full-list replace of one scope's layout. An empty `fields`
    list clears the scope's screen (back to defaults)."""

    project_id: uuid.UUID
    issue_type_id: uuid.UUID | None = None  # NULL = the project default screen
    fields: list[ScreenFieldRow]


class ScreenRead(BaseModel):
    """A scope's stored screen (or an empty list when none is configured)."""

    project_id: uuid.UUID
    issue_type_id: uuid.UUID | None
    fields: list[ScreenFieldRow]


class EffectiveFieldRow(BaseModel):
    """One resolved placement in render order — what the issue view consumes.
    `custom` flags a `cf:<key>` field so the client renders it via the registry."""

    field: str
    placement: ScreenPlacement
    custom: bool


class EffectiveScreen(BaseModel):
    """The merged, ordered placement of every arrangeable field for an item's
    (project, issue-type) — config over defaults. `source` says where it came from."""

    project_id: uuid.UUID
    issue_type_id: uuid.UUID | None
    source: str  # "issue_type" | "project" | "default"
    fields: list[EffectiveFieldRow]
