"""The identity map and unmatched authors, per connection (RADD-1258).

Provider-neutral on purpose: Settings → Version control renders the same
section under a Forgejo, a GitHub and a GitLab connection, and this router does
not know which connector's table the `connection_id` lives in — the mapping is
keyed by (provider, connection id), which is all the reconcile needs.

Gated on the `vcsconn.*` atoms the connectors' own administration uses.
"""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from radd.db import get_session
from radd.modules.auth import authz
from radd.modules.auth import service as auth_service
from radd.modules.auth.deps import CurrentUser

from . import timemirror
from .schemas import ReplayResult, UnmatchedAuthorRead, UserLinkRead, UserLinkSet
from .types import VcsProvider

router = APIRouter(prefix="/vcs", tags=["vcs"])

Session = Annotated[AsyncSession, Depends(get_session)]


async def _reads(session: AsyncSession, links) -> list[UserLinkRead]:
    users = await auth_service.users_by_ids(session, {link.user_id for link in links})
    return [
        UserLinkRead(
            id=link.id,
            provider=VcsProvider(link.provider),
            connection_id=link.connection_id,
            external_username=link.external_username,
            user_id=link.user_id,
            user_name=users[link.user_id].name if link.user_id in users else "?",
            matched_by=link.matched_by,
            created_at=link.created_at,
        )
        for link in links
    ]


@router.get(
    "/{provider}/connections/{connection_id}/identities", response_model=list[UserLinkRead]
)
async def list_identities(
    provider: VcsProvider, connection_id: uuid.UUID, session: Session, user: CurrentUser
) -> list[UserLinkRead]:
    await authz.require(session, user, authz.Permission.GLOBAL_MANAGE)
    return await _reads(
        session,
        await timemirror.list_user_links(session, provider=provider, connection_id=connection_id),
    )


@router.put(
    "/{provider}/connections/{connection_id}/identities",
    response_model=UserLinkRead,
    status_code=201,
)
async def set_identity(
    provider: VcsProvider,
    connection_id: uuid.UUID,
    data: UserLinkSet,
    session: Session,
    user: CurrentUser,
) -> UserLinkRead:
    await authz.require(session, user, authz.Permission.VCSCONN_UPDATE)
    link = await timemirror.set_user_link(
        session,
        provider=provider,
        connection_id=connection_id,
        username=data.external_username,
        user_id=data.user_id,
        actor_id=user.id,
    )
    return (await _reads(session, [link]))[0]


@router.delete("/identities/{link_id}", status_code=204)
async def delete_identity(link_id: uuid.UUID, session: Session, user: CurrentUser) -> None:
    await authz.require(session, user, authz.Permission.VCSCONN_UPDATE)
    await timemirror.delete_user_link(session, link_id, actor_id=user.id)


@router.get(
    "/{provider}/connections/{connection_id}/unmatched", response_model=list[UnmatchedAuthorRead]
)
async def list_unmatched(
    provider: VcsProvider, connection_id: uuid.UUID, session: Session, user: CurrentUser
) -> list[UnmatchedAuthorRead]:
    """Provider accounts whose time entries are parked because no Radd user
    matched them. Derived from the parked rows — nothing to keep in sync."""
    await authz.require(session, user, authz.Permission.GLOBAL_MANAGE)
    return [
        UnmatchedAuthorRead(
            external_username=row.external_username,
            external_email=row.external_email,
            pending_entries=row.pending_entries,
            pending_seconds=row.pending_seconds,
            last_seen_at=row.last_seen_at,
        )
        for row in await timemirror.list_unmatched(
            session, provider=provider, connection_id=connection_id
        )
    ]


@router.post(
    "/{provider}/connections/{connection_id}/unmatched/replay", response_model=ReplayResult
)
async def map_and_replay(
    provider: VcsProvider,
    connection_id: uuid.UUID,
    data: UserLinkSet,
    session: Session,
    user: CurrentUser,
) -> ReplayResult:
    """Map the account AND turn its parked entries into worklogs, in one step —
    the action the unmatched list offers."""
    await authz.require(session, user, authz.Permission.VCSCONN_UPDATE)
    replayed = await timemirror.map_and_replay(
        session,
        provider=provider,
        connection_id=connection_id,
        username=data.external_username,
        user_id=data.user_id,
        actor_id=user.id,
    )
    return ReplayResult(replayed=replayed)
