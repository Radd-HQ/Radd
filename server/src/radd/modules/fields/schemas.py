import uuid
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator

from radd.apitypes import UtcDatetime

from .types import SELECT_TYPES, FieldDisplay, FieldSource, FieldType


class FieldDefinitionCreate(BaseModel):
    # Scope: empty = global; a non-empty list scopes the field to those projects
    # (spec 90 follow-up). `project_id` is a legacy single-scope alias folded into
    # `project_ids` — accept either, never both meaningfully.
    project_ids: list[uuid.UUID] = Field(default_factory=list)
    project_id: uuid.UUID | None = None
    key: str = Field(pattern=r"^[a-z][a-z0-9_]{0,49}$", description="Stable snake_case key")
    name: str = Field(min_length=1, max_length=200)
    type: FieldType
    required: bool = False
    options: list[str] | None = None
    indexed: bool = False
    ai_visible: bool = True
    source: FieldSource = FieldSource.USER
    display: FieldDisplay | None = None  # spec 52 — render hint (select/multi_select)
    # Seeded onto new items when the create payload omits this key. NULL = no default.
    default_value: Any | None = None

    @model_validator(mode="after")
    def _fold_legacy_scope(self) -> "FieldDefinitionCreate":
        # A caller passing the legacy single `project_id` gets it folded into the
        # list; an explicit `project_ids` wins. Dedupe, preserving order.
        if not self.project_ids and self.project_id is not None:
            self.project_ids = [self.project_id]
        self.project_ids = list(dict.fromkeys(self.project_ids))
        return self

    @model_validator(mode="after")
    def check_options(self) -> "FieldDefinitionCreate":
        if self.type in SELECT_TYPES:
            if not self.options:
                raise ValueError(f"{self.type} fields require non-empty options")
            if len(set(self.options)) != len(self.options):
                raise ValueError("options must be unique")
        elif self.options is not None:
            raise ValueError(f"{self.type} fields do not take options")
        if self.default_value is not None:
            from .validation import check_field_value

            problem = check_field_value(self.type, self.options, self.default_value)
            if problem:
                raise ValueError(f"default_value {problem}")
        return self


class FieldDefinitionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    # Empty = global; otherwise the projects this field is scoped to (spec 90 follow-up).
    project_ids: list[uuid.UUID] = Field(default_factory=list)
    key: str
    name: str
    type: FieldType
    required: bool
    options: list[str] | None
    indexed: bool
    ai_visible: bool
    source: FieldSource
    display: FieldDisplay | None  # spec 52
    default_value: Any | None  # seeded onto new items; NULL = no default
    # Spec 92: read/write grants live in access_grants (managed via /grants). `restricted`
    # = the field carries any grant, so some actors can't see/write it (badge hint).
    restricted: bool = False
    created_at: UtcDatetime


class FieldWritabilityRead(BaseModel):
    """Which fields the current user can't WRITE in a project (spec 92) — builtin field names +
    custom field keys. Per-(actor, project); lets the SPA disable those editors up front."""

    readonly_fields: list[str] = []


class FieldOptionsExtend(BaseModel):
    """POST /fields/{id}/options — ADD options to a select field (spec 100's
    additive-only seam, exposed for the settings UI in spec 107's cleanup).
    Removing/renaming stays impossible: items already store those values."""

    values: list[str] = Field(min_length=1)


class FieldDefinitionUpdate(BaseModel):
    """PATCH /fields/{id} — the safely-mutable attrs (spec 52). Key/type/options
    stay immutable; this edits presentation (name, render widget) and the default
    value seeded onto new items. `default_value` uses model_fields_set to tell an
    omitted field from an explicit null (which clears the default)."""

    name: str | None = Field(default=None, min_length=1, max_length=200)
    display: FieldDisplay | None = None
    default_value: Any | None = None
    # Scope expansion (spec 90 follow-up): omitted = unchanged; a list REPLACES the
    # field's scope ([] promotes it to global, non-empty scopes it to those projects).
    # Resolved via model_fields_set so an omitted list differs from an explicit [].
    project_ids: list[uuid.UUID] | None = None
