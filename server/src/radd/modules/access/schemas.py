import uuid

from pydantic import BaseModel, ConfigDict, Field

from radd.apitypes import UtcDatetime

from .types import GrantEffect, GrantSubject


class AccessGrantRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    resource_type: str
    resource_id: str
    subject_type: GrantSubject
    subject_id: uuid.UUID
    access: str
    #: RADD-819: allow (default) | deny — deny wins on ties, specificity first.
    effect: GrantEffect = GrantEffect.ALLOW
    project_id: uuid.UUID | None = None  # NULL = global (every scope)
    #: RADD-820: NULL = permanent; expired rows never load into resolution.
    expires_at: UtcDatetime | None = None
    granted_by: uuid.UUID | None = None
    created_at: UtcDatetime


class AccessGrantDirectoryRead(AccessGrantRead):
    subject_name: str | None = None
    project_key: str | None = None
    expired: bool = False


class AccessGrantCreate(BaseModel):
    """POST /grants — grant a subject an access on a resource, at global scope
    (empty project_ids) or to one/more projects (one grant row per project)."""

    resource_type: str = Field(min_length=1, max_length=40)
    resource_id: str = Field(min_length=1, max_length=100)
    subject_type: GrantSubject
    subject_id: uuid.UUID
    access: str = Field(min_length=1, max_length=20)
    effect: GrantEffect = GrantEffect.ALLOW
    #: RADD-820: optional expiry — temporary elevation that actually ends.
    expires_at: UtcDatetime | None = None
    project_ids: list[uuid.UUID] = Field(default_factory=list)


class ResourceSpecRead(BaseModel):
    """GET /grants/resources — what the reusable GrantsEditor needs to render a
    resource's grant model (which accesses, subjects, scoping)."""

    resource_type: str
    label: str
    accesses: list[str]
    subjects: list[GrantSubject]
    project_scoped: bool
    hierarchical: bool
    default_open: bool


class SharedGrantChange(BaseModel):
    """Change one saved level, or remove it with access=null, if still current.

    Subject, scope, effect and expiry are preserved on level edits. Expectations
    prevent a stale draft from silently overwriting a different grant policy.
    """

    id: uuid.UUID
    expected_access: str
    expected_effect: GrantEffect
    expected_expires_at: UtcDatetime | None
    access: str | None


class SharedGrantAdd(BaseModel):
    subject_type: GrantSubject
    subject_id: uuid.UUID
    access: str = Field(min_length=1, max_length=20)
    effect: GrantEffect = GrantEffect.ALLOW
    expires_at: UtcDatetime | None = None


class SharedGrantEdits(BaseModel):
    changes: list[SharedGrantChange] = Field(default_factory=list)
    additions: list[SharedGrantAdd] = Field(default_factory=list)
