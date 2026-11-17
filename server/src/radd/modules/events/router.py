from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from radd.db import get_session

# Backward edge (events loads before auth): tolerated for router enforcement only —
# see docs/modules.md. deps/authz are import-light by design.
from radd.modules.auth import authz
from radd.modules.auth.deps import CurrentUser

from . import consumer as consumers, service
from .models import ConsumerFailure, Event
from .schemas import ConsumerFailureRead, EventRead, ReplayResult

router = APIRouter(prefix="/events", tags=["events"])


@router.get("", response_model=list[EventRead])
async def list_events(
    session: Annotated[AsyncSession, Depends(get_session)],
    user: CurrentUser,
    after: int = Query(0, ge=0, description="Return events with id greater than this offset"),
    limit: int = Query(100, ge=1, le=500),
) -> list[EventRead]:
    # Raw instance-wide payloads are for administrative integrations.
    # Project managers use the scoped, redacted audit endpoint.
    await authz.require(session, user, authz.Permission.GLOBAL_MANAGE)
    return [EventRead.model_validate(e) for e in await service.read_by_id_after(session, after, limit)]


# --- failed events (RADD-1538): what a consumer could not handle ---------------

Session = Annotated[AsyncSession, Depends(get_session)]


async def _reads(session: AsyncSession, failures: list[ConsumerFailure]) -> list[ConsumerFailureRead]:
    from sqlalchemy import select

    labels = {
        event_id: (event_type, label)
        for event_id, event_type, label in await session.execute(
            select(Event.id, Event.event_type, Event.entity_label).where(
                Event.id.in_([failure.event_id for failure in failures])
            )
        )
    }
    reads = []
    for failure in failures:
        read = ConsumerFailureRead.model_validate(failure)
        read.event_type, read.entity_label = labels.get(failure.event_id, (None, None))
        reads.append(read)
    return reads


async def _failure(session: AsyncSession, failure_id: int) -> ConsumerFailure:
    failure = await session.get(ConsumerFailure, failure_id)
    if failure is None:
        raise HTTPException(status_code=404, detail="no such failed event")
    return failure


@router.get("/failures", response_model=list[ConsumerFailureRead])
async def list_failures(
    session: Session,
    user: CurrentUser,
    consumer: str | None = None,
    status: consumers.FailureStatus | None = None,
    limit: int = Query(100, ge=1, le=500),
) -> list[ConsumerFailureRead]:
    """Events a consumer's handler raised on, newest first: `pending` ones are
    being retried, `dead` ones wait for someone to replay or discard them."""
    await authz.require(session, user, authz.Permission.GLOBAL_MANAGE)
    failures = await consumers.list_failures(session, consumer=consumer, status=status, limit=limit)
    return await _reads(session, failures)


@router.post("/failures/{failure_id}/replay", response_model=ReplayResult)
async def replay_failure(failure_id: int, session: Session, user: CurrentUser) -> ReplayResult:
    """Hand the event to its consumer again, now. A replay that fails again
    leaves the row, with the new error."""
    await authz.require(session, user, authz.Permission.GLOBAL_MANAGE)
    failure = await _failure(session, failure_id)
    try:
        delivered = await consumers.replay(session, failure)
    except consumers.ReplayUnavailable as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    if delivered:
        return ReplayResult(delivered=True)
    return ReplayResult(delivered=False, failure=(await _reads(session, [failure]))[0])


@router.delete("/failures/{failure_id}", status_code=204)
async def discard_failure(failure_id: int, session: Session, user: CurrentUser) -> None:
    """Give up on a failed event: its side effect will not happen."""
    await authz.require(session, user, authz.Permission.GLOBAL_MANAGE)
    await session.delete(await _failure(session, failure_id))
