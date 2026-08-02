import uuid

from pydantic import BaseModel, ConfigDict, Field
from radd.apitypes import UtcDatetime


from .types import MemberSource, TeamSource


class TeamCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    # Spec 87: defaults to the creator. An admin creating a team for someone else
    # names them here instead of creating-then-transferring.
    owner_id: uuid.UUID | None = None


class TeamUpdate(BaseModel):
    """PATCH /teams/{id} (spec 84): rename and/or set/clear the AD group link.
    Omitted = unchanged; explicit null clears the link."""

    name: str | None = Field(default=None, min_length=1, max_length=200)
    directory_group_dn: str | None = Field(default=None, max_length=1000)
    directory_group_name: str | None = Field(default=None, max_length=200)


class TeamRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    created_at: UtcDatetime
    # Spec 84: linked AD group (null = not linked); CN kept for display.
    directory_group_dn: str | None = None
    directory_group_name: str | None = None
    # Spec 87: membership ownership + delegated management. `can_manage` /
    # `can_delete` are computed per-actor server-side so the client never
    # re-derives the owner/manager/atom union (the ViewRead precedent).
    source: TeamSource = TeamSource.LOCAL
    # Spec 87: set when the linked AD group stopped resolving (null = healthy).
    # The team stays LOCKED — its people are kept and every sync removal is held,
    # but membership only re-opens when an admin unlinks. The server never infers
    # "unlink me" from a directory it may simply be failing to read correctly.
    directory_missing_since: UtcDatetime | None = None
    owner_id: uuid.UUID | None = None
    managers: list[uuid.UUID] = Field(default_factory=list)
    can_manage: bool = False
    can_delete: bool = False


class TeamManagersUpdate(BaseModel):
    """PUT /teams/{id}/managers — the full set of people who may administer this
    team, replaced atomically. Owner-gated."""

    user_ids: list[uuid.UUID] = Field(default_factory=list, max_length=50)


class TeamTransfer(BaseModel):
    """POST /teams/{id}/transfer — reassign the owner. The previous owner is kept
    on as a manager (no accidental lockout)."""

    user_id: uuid.UUID


class TeamMemberAdd(BaseModel):
    user_id: uuid.UUID


class TeamMemberRead(BaseModel):
    user_id: uuid.UUID
    email: str
    name: str
    source: MemberSource = MemberSource.MANUAL  # spec 84: directory rows are sync-owned


class ProjectTeamAttach(BaseModel):
    team_id: uuid.UUID
    role_id: uuid.UUID | None = None
    # Compat: a role KEY ("member", "triager", …) — used when role_id is
    # omitted; defaults to the builtin member role.
    role: str | None = Field(default=None, max_length=100)


class ProjectTeamUpdate(BaseModel):
    role_id: uuid.UUID


class ProjectTeamRead(BaseModel):
    project_id: uuid.UUID
    team_id: uuid.UUID
    role_id: uuid.UUID
    role: str  # the role's key, hydrated for display
