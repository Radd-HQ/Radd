"""Survey lifecycle (spec 65): creation (sender), the public token read/submit,
and the item-scoped read behind the issue-rail chip. Both csat events are
emitted with entity_type=item (History feed) and actor_id=None (a requester has
no user; None also lets automation rules on them fire — the engine's loop guard
only skips the SYSTEM actor)."""

import secrets
import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from radd.exceptions import NotFoundError
from radd.modules.events import service as events
from radd.modules.items import service as items_service
from radd.modules.items.enums import ItemEntity
from radd.modules.projects import service as projects_service

from .models import CsatSurvey
from .schemas import PublicCsatRead, PublicCsatSubmit
from .types import PAYLOAD_COMMENT_EXCERPT_CHARS, CsatEntity, CsatEvent


def _utcnow() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


async def survey_for_item(session: AsyncSession, item_id: uuid.UUID) -> CsatSurvey | None:
    return await session.scalar(select(CsatSurvey).where(CsatSurvey.item_id == item_id))


async def survey_by_token(session: AsyncSession, token: str) -> CsatSurvey | None:
    return await session.scalar(select(CsatSurvey).where(CsatSurvey.token == token))


async def create_survey(
    session: AsyncSession,
    *,
    item_id: uuid.UUID,
    item_key: str,
) -> CsatSurvey:
    """Mint the item's one-and-only survey row + emit csat.requested in the same
    transaction (the sender commits both with its cursor, before sending)."""
    survey = CsatSurvey(
        item_id=item_id, token=secrets.token_urlsafe(32), sent_at=_utcnow()
    )
    session.add(survey)
    await session.flush()
    await events.emit(
        session,
        event_type=CsatEvent.REQUESTED,
        entity_type=ItemEntity.ITEM,
        entity_id=item_id,
        actor_id=None,
        payload={"item_id": str(item_id), "key": item_key},
    )
    return survey


async def _public_read(session: AsyncSession, survey: CsatSurvey) -> PublicCsatRead:
    item = await items_service.require_item(session, survey.item_id)
    project = await projects_service.get_project(session, item.project_id)
    return PublicCsatRead(
        item_key=f"{project.key}-{item.number}",
        item_title=item.title,
        rating=survey.rating,
        responded_at=survey.responded_at,
    )


async def public_survey(session: AsyncSession, token: str) -> PublicCsatRead:
    survey = await survey_by_token(session, token)
    if survey is None:
        raise NotFoundError(CsatEntity.SURVEY, token)
    return await _public_read(session, survey)


async def record_response(
    session: AsyncSession, token: str, data: PublicCsatSubmit
) -> PublicCsatRead:
    """Record (or revise — latest wins) the requester's answer. `responded_at`
    is stamped on the FIRST submit only; every submit emits csat.responded."""
    survey = await survey_by_token(session, token)
    if survey is None:
        raise NotFoundError(CsatEntity.SURVEY, token)
    survey.rating = data.rating
    survey.comment = data.comment
    if survey.responded_at is None:
        survey.responded_at = _utcnow()
    item = await items_service.require_item(session, survey.item_id)
    project = await projects_service.get_project(session, item.project_id)
    await events.emit(
        session,
        event_type=CsatEvent.RESPONDED,
        entity_type=ItemEntity.ITEM,
        entity_id=item.id,
        actor_id=None,  # the requester has no user account
        payload={
            "item_id": str(item.id),
            "key": f"{project.key}-{item.number}",
            "rating": data.rating,
            "comment": data.comment[:PAYLOAD_COMMENT_EXCERPT_CHARS],
        },
    )
    await session.flush()
    return await _public_read(session, survey)


async def responded_survey(session: AsyncSession, item_id: uuid.UUID) -> CsatSurvey:
    """The item's ANSWERED survey — NotFound both when no survey exists and when
    it is still unanswered (the rail chip is 404-quiet until a rating lands)."""
    survey = await survey_for_item(session, item_id)
    if survey is None or survey.responded_at is None or survey.rating is None:
        raise NotFoundError(CsatEntity.SURVEY, item_id)
    return survey
