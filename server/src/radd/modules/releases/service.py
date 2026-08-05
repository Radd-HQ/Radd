import uuid
from collections.abc import Iterable
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from radd.exceptions import ConflictError, NotFoundError
from radd.modules.events import service as events
from radd.modules.projects import service as projects_service

from .models import Release
from .schemas import ReleaseCreate, ReleaseUpdate
from .types import ReleaseEntity, ReleaseEvent, ReleaseStatus


def _now() -> datetime:
    """Naive UTC, matching the server-side `now()` used for created_at/updated_at."""
    return datetime.now(UTC).replace(tzinfo=None)


async def create_release(
    session: AsyncSession, data: ReleaseCreate, actor_id: uuid.UUID | None = None
) -> Release:
    await projects_service.get_project(session, data.project_id)
    if await resolve_release(session, data.project_id, data.version) is not None:
        raise ConflictError(ReleaseEntity.RELEASE, data.version)
    release = Release(
        project_id=data.project_id,
        name=data.name,
        version=data.version,
        status=data.status.value,
        released_at=_now() if data.status is ReleaseStatus.RELEASED else None,
        description=data.description,
    )
    session.add(release)
    await session.flush()
    await _emit(session, ReleaseEvent.CREATED, release, actor_id)
    return release


async def update_release(
    session: AsyncSession,
    release_id: uuid.UUID,
    data: ReleaseUpdate,
    actor_id: uuid.UUID | None = None,
) -> Release:
    release = await get_release(session, release_id)
    if data.name is not None:
        release.name = data.name
    if data.version is not None and data.version != release.version:
        clash = await resolve_release(session, release.project_id, data.version)
        if clash is not None and clash.id != release.id:
            raise ConflictError(ReleaseEntity.RELEASE, data.version)
        release.version = data.version
    if data.description is not None:
        release.description = data.description
    if data.status is not None and data.status.value != release.status:
        if data.status is ReleaseStatus.RELEASED:
            release.released_at = release.released_at or _now()
        else:  # back to planned: drop the timestamp so a later re-release re-stamps
            release.released_at = None
        release.status = data.status.value
    await session.flush()
    await _emit(session, ReleaseEvent.UPDATED, release, actor_id)
    return release


async def delete_release(
    session: AsyncSession, release_id: uuid.UUID, actor_id: uuid.UUID | None = None
) -> None:
    release = await get_release(session, release_id)
    # Items' release_id is nulled by the FK's ON DELETE SET NULL — no manual cleanup.
    await session.delete(release)
    await session.flush()
    await _emit(session, ReleaseEvent.DELETED, release, actor_id)


async def get_release(session: AsyncSession, release_id: uuid.UUID) -> Release:
    release = await session.get(Release, release_id)
    if release is None:
        raise NotFoundError(ReleaseEntity.RELEASE, release_id)
    return release


async def releases_by_ids(
    session: AsyncSession, ids: Iterable[uuid.UUID]
) -> dict[uuid.UUID, Release]:
    result = await session.execute(select(Release).where(Release.id.in_(set(ids))))
    return {release.id: release for release in result.scalars()}


async def resolve_release(
    session: AsyncSession, project_id: uuid.UUID, version: str
) -> Release | None:
    """Find a release by (project, version), or None — the find-or-none CI helper."""
    return await session.scalar(
        select(Release).where(Release.project_id == project_id, Release.version == version)
    )


def ids_by_versions(versions: list[str]):
    """Select of release ids matching these VERSIONS — the fragment seam the
    items SLQ `release` builtin composes into `WorkItem.release_id IN (…)`."""
    return select(Release.id).where(Release.version.in_(versions))


async def list_releases(session: AsyncSession, project_id: uuid.UUID) -> list[Release]:
    result = await session.execute(
        select(Release).where(Release.project_id == project_id).order_by(Release.version)
    )
    return list(result.scalars())


async def _emit(
    session: AsyncSession, event_type: ReleaseEvent, release: Release, actor_id: uuid.UUID | None
) -> None:
    project = await projects_service.get_project(session, release.project_id)
    await events.emit(
        session,
        event_type=event_type,
        entity_type=ReleaseEntity.RELEASE,
        entity_id=release.id,
        actor_id=actor_id,
        payload={"version": release.version, "name": release.name, "status": release.status},
    )
