"""Bulk attachment moves between hosts (spec 102 §move): copy -> verify ->
repoint -> best-effort source delete, per file.

The ordering is the safety property: a row is only repointed AFTER the target
copy verified (size always; etag best-effort — multipart etags aren't content
hashes), so a crash at any point leaves every row pointing at real bytes. A
failed source delete is a logged orphan on the SOURCE, never a job failure —
the row already points at verified bytes. Runs as an in-process task (the
jiraimport/backup idiom) with its own sessions and small commit batches so
progress is live.
"""

import asyncio
import io
import logging
import uuid
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from radd.db import SessionLocal
from radd.exceptions import ConflictError, NotFoundError

from . import hosts
from .clients import client_for
from .models import Attachment, AttachmentMoveJob
from .types import AttachmentEntity, MoveJobState

logger = logging.getLogger(__name__)

COMMIT_EVERY = 25  # files per transaction — live progress without a huge txn
_CONCURRENCY = 4  # parallel copies within a batch
_PROBLEM_CAP = 50  # enough to act on; the log has the rest


async def create_job(
    session: AsyncSession,
    *,
    source_host_id: uuid.UUID,
    target_host_id: uuid.UUID,
    actor_id: uuid.UUID,
) -> AttachmentMoveJob:
    if source_host_id == target_host_id:
        raise ConflictError(AttachmentEntity.MOVE_JOB, reason="source and target are the same host")
    await hosts.get_host(session, source_host_id)
    await hosts.get_host(session, target_host_id)
    running = await session.execute(
        select(AttachmentMoveJob.id).where(
            AttachmentMoveJob.state.in_((MoveJobState.PENDING.value, MoveJobState.RUNNING.value))
        )
    )
    if running.first() is not None:
        raise ConflictError(
            AttachmentEntity.MOVE_JOB, reason="another move is already running — wait for it"
        )
    total = (
        await session.execute(
            select(Attachment.id).where(Attachment.storage_host_id == source_host_id)
        )
    ).scalars()
    job = AttachmentMoveJob(
        source_host_id=source_host_id,
        target_host_id=target_host_id,
        total=len(list(total)),
        created_by=actor_id,
    )
    session.add(job)
    await session.flush()
    return job


async def get_job(session: AsyncSession, job_id: uuid.UUID) -> AttachmentMoveJob:
    job = await session.get(AttachmentMoveJob, job_id)
    if job is None:
        raise NotFoundError(AttachmentEntity.MOVE_JOB, job_id)
    return job


async def list_jobs(session: AsyncSession) -> list[AttachmentMoveJob]:
    result = await session.execute(
        select(AttachmentMoveJob).order_by(AttachmentMoveJob.created_at.desc()).limit(20)
    )
    return list(result.scalars())


def start(job_id: uuid.UUID) -> None:
    asyncio.create_task(execute(job_id))  # noqa: RUF006 — tracked by the job row


async def execute(job_id: uuid.UUID) -> None:
    try:
        await _execute(job_id)
    except Exception:
        logger.exception("move job %s crashed", job_id)
        async with SessionLocal() as session:
            job = await session.get(AttachmentMoveJob, job_id)
            if job is not None:
                job.state = MoveJobState.FAILED.value
                job.finished_at = datetime.now(timezone.utc).replace(tzinfo=None)
                await session.commit()


async def _execute(job_id: uuid.UUID) -> None:
    async with SessionLocal() as session:
        job = await get_job(session, job_id)
        source = await hosts.get_host(session, job.source_host_id)
        target = await hosts.get_host(session, job.target_host_id)
        job.state = MoveJobState.RUNNING.value
        job.started_at = datetime.now(timezone.utc).replace(tzinfo=None)
        await session.commit()

    source_client, target_client = client_for(source), client_for(target)
    semaphore = asyncio.Semaphore(_CONCURRENCY)
    failed_ids: set[uuid.UUID] = set()  # each file fails at most once per job

    while True:
        async with SessionLocal() as session:
            query = (
                select(Attachment)
                .where(Attachment.storage_host_id == source.id)
                .order_by(Attachment.created_at)
                .limit(COMMIT_EVERY)
            )
            if failed_ids:
                query = query.where(Attachment.id.not_in(failed_ids))
            batch = list((await session.execute(query)).scalars())
            if not batch:
                break
            results = await asyncio.gather(
                *(
                    _move_one(semaphore, source_client, target_client, attachment)
                    for attachment in batch
                )
            )
            job = await get_job(session, job_id)
            for attachment, error in zip(batch, results):
                if error is None:
                    attachment.storage_host_id = target.id
                    job.moved += 1
                else:
                    failed_ids.add(attachment.id)
                    job.failed += 1
                    if len(job.problems) < _PROBLEM_CAP:
                        job.problems = job.problems + [
                            {
                                "attachment_id": str(attachment.id),
                                "filename": attachment.filename,
                                "detail": error,
                            }
                        ]
            await session.commit()

    async with SessionLocal() as session:
        job = await get_job(session, job_id)
        remaining = (
            await session.execute(
                select(Attachment.id).where(Attachment.storage_host_id == source.id).limit(1)
            )
        ).first()
        if job.failed == 0 and remaining is None:
            job.state = MoveJobState.DONE.value
        else:
            job.state = MoveJobState.DONE_WITH_FAILURES.value
        job.finished_at = datetime.now(timezone.utc).replace(tzinfo=None)
        await session.commit()
    logger.info("move job %s finished: %s", job_id, job.state)


async def _move_one(
    semaphore: asyncio.Semaphore, source_client, target_client, attachment: Attachment
) -> str | None:
    """Copy + verify one attachment; the caller repoints the row. Returns the
    failure detail, or None on success."""
    async with semaphore:
        try:
            data = await source_client.read(attachment.storage_name)
            await target_client.save(
                attachment.storage_name,
                io.BytesIO(data),
                size=len(data),
                content_type=attachment.content_type,
            )
            stat = await target_client.stat(attachment.storage_name)
            if stat.size_bytes != attachment.size_bytes:
                return (
                    f"size mismatch after copy ({stat.size_bytes} != {attachment.size_bytes})"
                )
        except Exception as exc:  # noqa: BLE001 — per-file failure, job continues
            return str(exc)
        try:
            await source_client.remove(attachment.storage_name)
        except Exception:  # noqa: BLE001
            logger.warning(
                "move: source delete failed for %s (orphan on source)", attachment.storage_name
            )
        return None
