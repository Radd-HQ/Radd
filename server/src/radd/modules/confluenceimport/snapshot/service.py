"""Snapshot lifecycle: create, require, cancel, delete (spec 117)."""

from __future__ import annotations

import asyncio
import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from radd.exceptions import ConflictError, NotFoundError

from .. import connections
from ..models import ConfluenceSnapshot
from ..schemas import SnapshotCreate
from ..types import (
    ConfluenceEntity,
    ScopeKind,
    SnapshotStage,
    TERMINAL_SNAPSHOT_STAGES,
)


async def get_snapshot(session: AsyncSession, snapshot_id: uuid.UUID) -> ConfluenceSnapshot:
    snapshot = await session.get(ConfluenceSnapshot, snapshot_id)
    if snapshot is None:
        raise NotFoundError(ConfluenceEntity.SNAPSHOT, snapshot_id)
    return snapshot


async def require_complete(
    session: AsyncSession, snapshot_id: uuid.UUID
) -> ConfluenceSnapshot:
    """Planning and running both need a FINISHED download. A half-downloaded cache
    would produce a plan whose counts are a fraction of the truth."""
    snapshot = await get_snapshot(session, snapshot_id)
    if SnapshotStage(snapshot.stage) is not SnapshotStage.DONE:
        raise ConflictError(
            ConfluenceEntity.SNAPSHOT,
            reason=f"this snapshot is {snapshot.stage}, not done",
        )
    return snapshot


async def create_snapshot(
    session: AsyncSession, data: SnapshotCreate, actor_id: uuid.UUID
) -> ConfluenceSnapshot:
    connection = await connections.require_connection(session, data.connection_id)
    scope = data.scope
    if scope.kind is ScopeKind.SPACE and not scope.space_key:
        raise ConflictError(ConfluenceEntity.SNAPSHOT, reason="a space scope needs a space key")
    if scope.kind is ScopeKind.SUBTREE and not scope.root_page_id:
        raise ConflictError(ConfluenceEntity.SNAPSHOT, reason="a subtree scope needs a root page")
    if scope.kind is ScopeKind.PAGES and not scope.page_ids:
        raise ConflictError(ConfluenceEntity.SNAPSHOT, reason="a page scope needs page ids")

    snapshot = ConfluenceSnapshot(
        connection_id=connection.id,
        actor_id=actor_id,
        name=data.name or _default_name(data),
        scope=scope.model_dump(mode="json"),
        # Recorded on the ROW: a run months later must know which instance a page
        # came from even if the connection has since been edited or deleted.
        external_source=connection.external_source,
        base_url=connection.base_url,
        include_history=data.include_history,
        history_limit=data.history_limit,
        include_attachments=data.include_attachments,
        include_comments=data.include_comments,
        stage=SnapshotStage.PENDING.value,
        counts={},
        problems=[],
        catalogs={},
    )
    session.add(snapshot)
    await session.flush()
    return snapshot


def _default_name(data: SnapshotCreate) -> str:
    scope = data.scope
    if scope.kind is ScopeKind.SPACE:
        return f"Space {scope.space_key}"
    if scope.kind is ScopeKind.SUBTREE:
        return f"Section {scope.root_page_id}"
    return f"{len(scope.page_ids)} page(s)"


async def request_cancel(session: AsyncSession, snapshot_id: uuid.UUID) -> ConfluenceSnapshot:
    """Cooperative: the running task re-reads `stage` between batches."""
    snapshot = await get_snapshot(session, snapshot_id)
    if SnapshotStage(snapshot.stage) in TERMINAL_SNAPSHOT_STAGES:
        return snapshot
    snapshot.stage = SnapshotStage.CANCELED.value
    await session.flush()
    return snapshot


async def delete_snapshot(session: AsyncSession, snapshot_id: uuid.UUID) -> None:
    """Deleting a cache reclaims its BYTES too — one rmtree of the package, which
    cannot half-succeed the way N object-store deletes can."""
    from . import package

    snapshot = await get_snapshot(session, snapshot_id)
    await asyncio.to_thread(package.remove, snapshot_id)
    await session.delete(snapshot)
    await session.flush()
