"""Wire shapes for GitHub connections and repositories (RADD-1129)."""

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from radd.apitypes import UtcDatetime

from .types import GITHUB_COM


class ConnectionCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    base_url: str = Field(default=GITHUB_COM, min_length=1, max_length=500)
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
    # Credentials are never returned; the UI needs to know only whether they exist.
    has_token: bool
    has_secret: bool
    repo_count: int
    created_at: UtcDatetime


class RepoCreate(BaseModel):
    connection_id: uuid.UUID
    full_name: str = Field(min_length=1, max_length=300)  # owner/repo
    project_id: uuid.UUID | None = None
    default_branch: str = Field(default="main", max_length=200)


class RepoUpdate(BaseModel):
    # `project_id` uses the model_fields_set idiom: omitted = unchanged, explicit
    # null = clear the mapping.
    project_id: uuid.UUID | None = None
    default_branch: str | None = Field(default=None, max_length=200)
    # RADD-1258 — same idiom: omitted = unchanged, explicit null = back to the default.
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
    version: str = ""  # "user <login>" for an authenticated test, the API host otherwise
    detail: str = ""
