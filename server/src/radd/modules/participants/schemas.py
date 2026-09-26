import uuid

from pydantic import BaseModel, model_validator

from radd.apitypes import UtcDatetime
from radd.modules.items.schemas import TeamRef, UserRef


class ParticipantAdd(BaseModel):
    """POST /items/{id}/participants — exactly one of user_id/team_id (422)."""

    user_id: uuid.UUID | None = None
    team_id: uuid.UUID | None = None

    @model_validator(mode="after")
    def _one_subject(self) -> "ParticipantAdd":
        if (self.user_id is None) == (self.team_id is None):
            raise ValueError("exactly one of user_id/team_id is required")
        return self


class ParticipantRow(BaseModel):
    """One grant row, hydrated — the id addresses DELETE .../{participant_id}."""

    id: uuid.UUID
    user: UserRef | None
    team: TeamRef | None
    added_by: UserRef | None
    created_at: UtcDatetime


class ItemParticipantsRead(BaseModel):
    """`GET /items/{id}/participants`: flat `users`/`teams` for display, `rows`
    with grant ids for removal, and `can_manage` computed per actor
    (participant.manage on this row); anyone may remove themself."""

    users: list[UserRef]
    teams: list[TeamRef]
    rows: list[ParticipantRow]
    can_manage: bool
