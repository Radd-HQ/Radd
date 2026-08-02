import uuid
from typing import Any

from pydantic import BaseModel, Field

from radd.apitypes import UtcDatetime
from radd.modules.auth.types import UserSource

from .types import ImportMatchKind, ImportResolution, ImportStatus


class LdapLoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1)


# --- spec 84: group search / import + directory-user import ------------------


class DirectoryGroupRead(BaseModel):
    cn: str
    dn: str
    description: str
    # DIRECT member-attribute length (cheap, for display) — the sync resolves
    # membership transitively, so nested members are counted only there.
    member_count: int


class DirectoryUserRead(BaseModel):
    username: str
    email: str
    name: str


class GroupImportRequest(BaseModel):
    group_dns: list[str] = Field(min_length=1, max_length=100)
    # True = unknown transitive members get spec-42 SSO-only accounts (a new
    # active user holds the global member floor); False = existing users only.
    provision_members: bool = False


class GroupImportResult(BaseModel):
    group_dn: str
    cn: str
    team_id: uuid.UUID | None
    created: bool  # a new team was created (vs linked/reused)
    members_added: int
    users_provisioned: int
    error: str | None = None


class ImportResolutionEntry(BaseModel):
    """One admin decision about one incoming directory user (spec 88).
    `target_user_id` names the existing account the choice applies to — required
    for overwrite/merge, ignored for create/skip."""

    email: str
    resolution: ImportResolution
    target_user_id: uuid.UUID | None = None


class DirectoryUserImportRequest(BaseModel):
    # The enumeration's dedupe key is the email — select-by-email round-trips it.
    emails: list[str] = Field(min_length=1, max_length=500)
    # Spec 88: per-person conflict decisions. An email with no entry keeps the
    # pre-88 behavior (create-or-link, existing accounts untouched), so the
    # endpoint stays backward compatible.
    resolutions: list[ImportResolutionEntry] = Field(default_factory=list, max_length=500)


class ExistingMatchRead(BaseModel):
    """An account the incoming directory user may already be (spec 88)."""

    user_id: uuid.UUID
    email: str
    name: str
    source: UserSource
    active: bool
    kind: ImportMatchKind


class ImportCandidateRead(BaseModel):
    """One row of the import preview (spec 88) — what would happen, and to whom."""

    username: str
    email: str
    name: str
    status: ImportStatus
    matches: list[ExistingMatchRead] = Field(default_factory=list)
    suggested: ImportResolution


class DirectoryUserImportResult(BaseModel):
    email: str
    user_id: uuid.UUID | None
    created: bool
    # Spec 88: what was actually done (skip reports `skip` and a null user_id).
    resolution: ImportResolution = ImportResolution.CREATE
    merged_user_id: uuid.UUID | None = None
    error: str | None = None


class DirectorySyncResult(BaseModel):
    """POST /teams/{id}/directory-sync — what the reconcile changed."""

    added: int
    removed: int


# --- spec 85: automatic user sync + sync status -------------------------------


class UserSyncResultRead(BaseModel):
    """POST /ldap/sync/users — what one sync pass did."""

    provisioned: int
    updated: int
    deactivated: int
    errors: list[str]


class DirectorySyncStateRead(BaseModel):
    """One `directory_sync_state` row (spec 85). `last_result` is the run's
    summary payload — user_sync: {provisioned, updated, deactivated, errors},
    group_sync: {teams, added, removed, errors}."""

    kind: str  # SyncKind
    last_run_at: UtcDatetime
    last_result: dict[str, Any]


class DirectorySyncStatusRead(BaseModel):
    """GET /ldap/sync-status — both sync rows (None = never ran)."""

    user_sync: DirectorySyncStateRead | None
    group_sync: DirectorySyncStateRead | None
