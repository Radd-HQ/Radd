import uuid

from pydantic import BaseModel, ConfigDict, Field
from radd.apitypes import UtcDatetime


class TeamCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    # Spec 87: defaults to the creator. An admin creating a team for someone else
    # names them here instead of creating-then-transferring.
    owner_id: uuid.UUID | None = None


class TeamUpdate(BaseModel):
    """PATCH /teams/{id}: rename. (RADD-829 retired the AD-link fields — the
    directory's truth is a Group, held as a MEMBER via /teams/{id}/groups.)"""

    name: str | None = Field(default=None, min_length=1, max_length=200)


class TeamRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    created_at: UtcDatetime
    # Spec 87: ownership + delegated management. `can_manage` / `can_delete` are
    # computed per-actor server-side so the client never re-derives the
    # owner/manager/atom union (the ViewRead precedent).
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


class TeamGroupAdd(BaseModel):
    """POST /teams/{id}/groups (RADD-829): the team gains a directory group as
    a member — its people (nesting included) count as team members."""

    group_id: uuid.UUID


class TeamMemberRead(BaseModel):
    user_id: uuid.UUID
    email: str
    name: str
    #: RADD-829: the group that carries this person, when their membership is
    #: reached through one (None = a direct user row).
    via_group: str | None = None


class TeamGroupRead(BaseModel):
    """A GROUP member of the team (RADD-829)."""

    group_id: uuid.UUID
    name: str
    dn: str
    directory_missing_since: UtcDatetime | None = None


