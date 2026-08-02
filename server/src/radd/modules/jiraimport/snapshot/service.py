"""Snapshot lifecycle (spec 100) — list, read, size, and delete.

Deletion matters as much as creation here: a cached download is deliberately
large, so it has to be genuinely reclaimable in one click. Issue rows go by
`ON DELETE CASCADE`; attachment BLOBS live in the object store and are removed
explicitly, because a cascade cannot reach them.
"""

from __future__ import annotations

import logging
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from radd.exceptions import ConflictError, NotFoundError
from radd.modules.attachments import service as attachments_service

from ..models import JiraSnapshot
from ..types import TERMINAL_SNAPSHOT_STAGES, JiraEntity, SnapshotStage
from . import store

logger = logging.getLogger(__name__)


async def list_snapshots(session: AsyncSession) -> list[JiraSnapshot]:
    result = await session.execute(
        select(JiraSnapshot).order_by(JiraSnapshot.created_at.desc()).limit(100)
    )
    return list(result.scalars())


async def get_snapshot(session: AsyncSession, snapshot_id: uuid.UUID) -> JiraSnapshot:
    snapshot = await session.get(JiraSnapshot, snapshot_id)
    if snapshot is None:
        raise NotFoundError(JiraEntity.SNAPSHOT, snapshot_id)
    return snapshot


async def require_complete(session: AsyncSession, snapshot_id: uuid.UUID) -> JiraSnapshot:
    """A snapshot fit to plan or import from. A half-downloaded one would silently
    import a partial project, so it is refused rather than quietly accepted."""
    snapshot = await get_snapshot(session, snapshot_id)
    if SnapshotStage(snapshot.stage) is not SnapshotStage.DONE:
        raise ConflictError(
            JiraEntity.SNAPSHOT,
            reason=f"the download is {snapshot.stage}, not complete — wait for it or re-download",
        )
    return snapshot


async def delete_snapshot(session: AsyncSession, snapshot_id: uuid.UUID) -> None:
    """Erase a snapshot and everything it holds.

    Refused mid-download: deleting the rows a running job is writing would leave
    it inserting against a vanished parent. Cancel it first.
    """
    snapshot = await get_snapshot(session, snapshot_id)
    if SnapshotStage(snapshot.stage) not in TERMINAL_SNAPSHOT_STAGES:
        raise ConflictError(
            JiraEntity.SNAPSHOT,
            reason="the download is still running — cancel it before deleting",
        )
    # Blobs live outside the database, so the cascade cannot reach them. Remove
    # them first: an orphaned row is recoverable, an orphaned blob is invisible.
    for blob in await store.blobs(session, snapshot_id):
        try:
            await attachments_service.remove_blob(
                session, blob.storage_name, host_id=blob.storage_host_id
            )
        except Exception:  # noqa: BLE001 — a missing blob must not block the delete
            logger.warning("snapshot %s: could not remove blob %s", snapshot_id, blob.storage_name)
    await session.delete(snapshot)  # issues + blob rows cascade
    await session.flush()


async def refresh_size(session: AsyncSession, snapshot: JiraSnapshot) -> None:
    """Recompute the stored counts — called once a download finishes."""
    snapshot.issue_count = await store.count_issues(session, snapshot.id)
    snapshot.byte_size = await store.payload_bytes(session, snapshot.id) + sum(
        blob.size_bytes for blob in await store.blobs(session, snapshot.id)
    )


async def request_cancel(session: AsyncSession, snapshot_id: uuid.UUID) -> JiraSnapshot:
    """Ask a running download to stop.

    Cooperative rather than a task kill: the job checks the stage between pages,
    so it stops on a page boundary with everything already downloaded still
    consistent and still committed.
    """
    snapshot = await get_snapshot(session, snapshot_id)
    if SnapshotStage(snapshot.stage) in TERMINAL_SNAPSHOT_STAGES:
        return snapshot
    snapshot.stage = SnapshotStage.CANCELED.value
    await session.flush()
    return snapshot
