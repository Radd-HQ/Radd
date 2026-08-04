"""Group reads (RADD-829). Writes come only from the directory sync — a group
is never local, so there is no create/update/delete surface here. RADD-833
builds the admin screen over this list."""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from radd.db import get_session
from radd.modules.auth import authz
from radd.modules.auth.deps import CurrentUser

from . import service
from .schemas import GroupRead

router = APIRouter(prefix="/groups", tags=["groups"])

Session = Annotated[AsyncSession, Depends(get_session)]


class GroupReachRead(BaseModel):
    group_id: uuid.UUID
    user_count: int


@router.get("", response_model=list[GroupRead])
async def list_groups(session: Session, user: CurrentUser) -> list[GroupRead]:
    """Every mirrored directory group. Member-floor visibility, like teams —
    the team panel names group members to anyone who can see the team."""
    await authz.require_member(session, user)
    rows = await service.list_groups(session)
    counts = await service.direct_member_counts(session, [g.id for g in rows])
    return [
        GroupRead(
            id=group.id,
            dn=group.dn,
            name=group.name,
            directory_missing_since=group.directory_missing_since,
            direct_member_count=counts.get(group.id, 0),
        )
        for group in rows
    ]


@router.get("/{group_id}/reach", response_model=GroupReachRead)
async def group_reach(
    group_id: uuid.UUID, session: Session, user: CurrentUser
) -> GroupReachRead:
    """How many people a grant on this group resolves to, NESTING INCLUDED —
    the number the grant UI must show before a grant is saved (trap 8:
    transitive reach is large and invisible)."""
    await authz.require_member(session, user)
    group = await service.get_group(session, group_id)
    return GroupReachRead(
        group_id=group.id, user_count=len(await service.group_user_ids(session, group.id))
    )
