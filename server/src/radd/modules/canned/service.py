import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from radd.exceptions import NotFoundError
from radd.modules.auth import service as auth_service
from radd.modules.auth.models import User
from radd.modules.events import service as events
from radd.modules.items.models import WorkItem
from radd.modules.projects.models import Project

from .models import CannedResponse
from .schemas import CannedResponseCreate, CannedResponseUpdate
from .types import CannedEntity, CannedEvent, CannedToken


async def _emit(
    session: AsyncSession,
    event_type: CannedEvent,
    response: CannedResponse,
    actor_id: uuid.UUID,
) -> None:
    await events.emit(
        session,
        event_type=event_type,
        entity_type=CannedEntity.CANNED_RESPONSE,
        entity_id=response.id,
        actor_id=actor_id,
        payload={"title": response.title},
    )


async def create_response(
    session: AsyncSession, data: CannedResponseCreate, actor_id: uuid.UUID
) -> CannedResponse:
    response = CannedResponse(
        title=data.title,
        body=data.body,
        position=data.position,
    )
    session.add(response)
    await session.flush()
    await _emit(session, CannedEvent.CREATED, response, actor_id)
    return response


async def get_response(session: AsyncSession, response_id: uuid.UUID) -> CannedResponse:
    response = await session.get(CannedResponse, response_id)
    if response is None:
        raise NotFoundError(CannedEntity.CANNED_RESPONSE, response_id)
    return response


async def list_responses(session: AsyncSession) -> list[CannedResponse]:
    result = await session.execute(
        select(CannedResponse).order_by(CannedResponse.position, CannedResponse.title)
    )
    return list(result.scalars())


async def update_response(
    session: AsyncSession,
    response_id: uuid.UUID,
    data: CannedResponseUpdate,
    actor_id: uuid.UUID,
) -> CannedResponse:
    response = await get_response(session, response_id)
    if data.title is not None:
        response.title = data.title
    if data.body is not None:
        response.body = data.body
    if data.position is not None:
        response.position = data.position
    await session.flush()
    await _emit(session, CannedEvent.UPDATED, response, actor_id)
    return response


async def render_context(
    session: AsyncSession, item: WorkItem, project: Project, *, me: User
) -> dict[str, str]:
    """Resolved values for the fixed `CannedToken` set (spec 66). Unset users
    resolve to "" so the pure renderer leaves their tokens verbatim."""
    users = await auth_service.users_by_ids(
        session, [uid for uid in (item.reporter_id, item.assignee_id) if uid is not None]
    )
    reporter = users.get(item.reporter_id) if item.reporter_id else None
    assignee = users.get(item.assignee_id) if item.assignee_id else None
    return {
        CannedToken.ITEM_KEY: f"{project.key}-{item.number}",
        CannedToken.ITEM_TITLE: item.title,
        CannedToken.REPORTER_NAME: reporter.name if reporter else "",
        CannedToken.REPORTER_EMAIL: reporter.email if reporter else "",
        CannedToken.ASSIGNEE_NAME: assignee.name if assignee else "",
        CannedToken.ME_NAME: me.name,
    }


async def delete_response(
    session: AsyncSession, response_id: uuid.UUID, actor_id: uuid.UUID
) -> None:
    response = await get_response(session, response_id)
    await session.delete(response)
    await session.flush()
    await _emit(session, CannedEvent.DELETED, response, actor_id)
