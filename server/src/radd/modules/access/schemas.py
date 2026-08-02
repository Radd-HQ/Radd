import uuid

from pydantic import BaseModel, ConfigDict, Field

from radd.apitypes import UtcDatetime

from .types import GrantSubject


class AccessGrantRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    resource_type: str
    resource_id: str
    subject_type: GrantSubject
    subject_id: uuid.UUID
    access: str
    project_id: uuid.UUID | None = None  # NULL = global (every scope)
    created_at: UtcDatetime


class AccessGrantCreate(BaseModel):
    """POST /grants — grant a subject an access on a resource, at global scope
    (empty project_ids) or to one/more projects (one grant row per project)."""

    resource_type: str = Field(min_length=1, max_length=40)
    resource_id: str = Field(min_length=1, max_length=100)
    subject_type: GrantSubject
    subject_id: uuid.UUID
    access: str = Field(min_length=1, max_length=20)
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
