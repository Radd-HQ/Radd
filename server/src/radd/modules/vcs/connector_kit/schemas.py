"""Wire shapes for every connector's connections and repositories (RADD-1435): one
shape, so Settings → Version control renders every host through one component."""

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, create_model

from radd.apitypes import UtcDatetime


class ConnectionCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    base_url: str = Field(min_length=1, max_length=500)
    api_token: str = Field(default="", max_length=500)
    webhook_secret: str = Field(default="", max_length=200)
    active: bool = True
    verify_ssl: bool = True


def connection_create_for(title: str, default_base_url: str) -> type[ConnectionCreate]:
    """A host with a public default (github.com, gitlab.com) makes the base URL
    optional; one without (Forgejo) keeps it required."""
    if not default_base_url:
        return ConnectionCreate
    return create_model(
        f"{title}ConnectionCreate",
        __base__=ConnectionCreate,
        base_url=(str, Field(default=default_base_url, min_length=1, max_length=500)),
    )


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
    full_name: str = Field(min_length=1, max_length=300)  # owner/repo, group/subgroup/project
    project_id: uuid.UUID | None = None
    default_branch: str = Field(default="main", max_length=200)


class RepoUpdate(BaseModel):
    enabled: bool | None = None
    link_all_projects: bool | None = None
    # The model_fields_set idiom: omitted = unchanged, explicit null = clear the
    # mapping (`project_id`) or go back to the default (`time_category_id`).
    project_id: uuid.UUID | None = None
    default_branch: str | None = Field(default=None, max_length=200)
    time_category_id: uuid.UUID | None = None
    mirror_time: bool | None = None  # RADD-1321
    move_on_merge: bool | None = None  # RADD-1369
    publish_on_release: bool | None = None  # RADD-1369


class RepoRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    enabled: bool = True
    link_all_projects: bool = True
    id: uuid.UUID
    connection_id: uuid.UUID
    full_name: str
    project_id: uuid.UUID | None
    default_branch: str
    last_backfill_at: datetime | None
    time_category_id: uuid.UUID | None = None
    mirror_time: bool = False
    move_on_merge: bool = False
    publish_on_release: bool = False
    created_at: UtcDatetime


class ConnectionTest(BaseModel):
    """Result of calling the host's API with the stored token."""

    ok: bool
    version: str = ""  # what the host reported (a version, a login), or the API host
    detail: str = ""


class ConnectorRead(BaseModel):
    """One loaded connector's tab on Settings → Version control (`GET /vcs/connectors`)."""

    provider: str
    title: str
    description: str
    webhook_path: str
    name_placeholder: str
    base_url_placeholder: str
    default_base_url: str
    token_hint: str
    secret_hint: str
    change_noun: str
