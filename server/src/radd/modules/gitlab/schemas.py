"""Wire shapes for GitLab connections and projects (RADD-1253) — the same shape
as the Forgejo and GitHub connectors, so Settings → Version control renders all
three through one component."""

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from radd.apitypes import UtcDatetime

from .types import GITLAB_COM


class ConnectionCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    base_url: str = Field(default=GITLAB_COM, min_length=1, max_length=500)
    api_token: str = Field(default="", max_length=500)
    webhook_secret: str = Field(default="", max_length=200)
    active: bool = True
    verify_ssl: bool = True


class ConnectionUpdate(BaseModel):
    """Omitted = unchanged. An EMPTY credential keeps the stored one — the
    ai_providers convention, so a form round-trip never blanks a secret."""

    name: str | None = Field(default=None, min_length=1, max_length=100)
    base_url: str | None = Field(default=None, min_length=1, max_length=500)
    api_token: str | None = Field(default=None, max_length=500)
    webhook_secret: str | None = Field(default=None, max_length=200)
    active: bool | None = None
    verify_ssl: bool | None = None


class ConnectionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    base_url: str
    active: bool
    verify_ssl: bool
    has_token: bool
    has_secret: bool
    repo_count: int
    created_at: UtcDatetime


class RepoCreate(BaseModel):
    connection_id: uuid.UUID
    full_name: str = Field(min_length=1, max_length=300)  # group/subgroup/project
    project_id: uuid.UUID | None = None
    default_branch: str = Field(default="main", max_length=200)


class RepoUpdate(BaseModel):
    # model_fields_set idiom: omitted = unchanged, explicit null = clear.
    project_id: uuid.UUID | None = None
    default_branch: str | None = Field(default=None, max_length=200)
    time_category_id: uuid.UUID | None = None


class RepoRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    connection_id: uuid.UUID
    full_name: str
    project_id: uuid.UUID | None
    default_branch: str
    last_backfill_at: datetime | None
    time_category_id: uuid.UUID | None = None
    created_at: UtcDatetime


class ConnectionTest(BaseModel):
    """Result of calling the host's API with the stored token."""

    ok: bool
    version: str = ""  # the GitLab version for an authenticated test, the API host otherwise
    detail: str = ""
