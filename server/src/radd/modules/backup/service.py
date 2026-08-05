"""Schedules, runs, and the wrappers that put core backups behind the API.

The heavy lifting is `radd.backup` (core, importable with no plugin registry);
this module owns only what the CLI does not need — the schedule rows, the run
rows that carry progress, and the events that land every action in the audit log.
"""

import asyncio
import logging
import uuid
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from radd import backup as core, maintenance
from radd.backup import postgres, service as core_service, store
from radd.config import settings
from radd.db import SessionLocal
from radd.exceptions import ConflictError, NotFoundError
from radd.modules.auth.models import User
from radd.modules.events import service as events
from radd.schedule import ScheduleKind, next_run

from .models import BackupRun, BackupSchedule
from .schemas import ScheduleCreate, ScheduleUpdate
from radd.clock import utcnow

logger = logging.getLogger(__name__)

#: Seeded on first boot — a backup system that must be configured protects the
#: installs that needed it least (spec 99 §5).
DEFAULT_SCHEDULE_NAME = "Nightly"
DEFAULT_SCHEDULE_CONFIG: dict[str, Any] = {"kind": ScheduleKind.DAILY.value, "time": "03:00", "weekdays": []}



# --- schedules ---


async def list_schedules(session: AsyncSession) -> list[BackupSchedule]:
    result = await session.execute(select(BackupSchedule).order_by(BackupSchedule.name))
    return list(result.scalars())


async def get_schedule(session: AsyncSession, schedule_id: uuid.UUID) -> BackupSchedule:
    schedule = await session.get(BackupSchedule, schedule_id)
    if schedule is None:
        raise NotFoundError(core.BackupEntity.SCHEDULE, schedule_id)
    return schedule


async def create_schedule(
    session: AsyncSession, data: ScheduleCreate, actor: User | None
) -> BackupSchedule:
    config = data.config.model_dump(exclude_none=True)
    schedule = BackupSchedule(
        name=data.name,
        enabled=data.enabled,
        config=config,
        include_attachments=data.include_attachments,
        keep_last=data.keep_last,
        keep_days=data.keep_days,
        next_run_at=next_run(config, utcnow(), settings.scheduler_tz) if data.enabled else None,
        created_by_id=actor.id if actor else None,
    )
    session.add(schedule)
    await session.flush()
    await events.emit(
        session,
        event_type=core.BackupEvent.SCHEDULE_CREATED,
        entity_type=core.BackupEntity.SCHEDULE,
        entity_id=schedule.id,
        actor_id=actor.id if actor else None,
        payload={"name": schedule.name},
    )
    return schedule


async def update_schedule(
    session: AsyncSession, schedule_id: uuid.UUID, data: ScheduleUpdate, actor: User
) -> BackupSchedule:
    schedule = await get_schedule(session, schedule_id)
    fields = data.model_dump(exclude_unset=True, exclude_none=True)
    if "config" in fields:
        fields["config"] = data.config.model_dump(exclude_none=True)  # type: ignore[union-attr]
    for key, value in fields.items():
        setattr(schedule, key, value)
    schedule.next_run_at = (
        next_run(schedule.config, utcnow(), settings.scheduler_tz) if schedule.enabled else None
    )
    await session.flush()
    await events.emit(
        session,
        event_type=core.BackupEvent.SCHEDULE_UPDATED,
        entity_type=core.BackupEntity.SCHEDULE,
        entity_id=schedule.id,
        actor_id=actor.id,
        payload={"name": schedule.name},
    )
    return schedule


async def delete_schedule(session: AsyncSession, schedule_id: uuid.UUID, actor: User) -> None:
    schedule = await get_schedule(session, schedule_id)
    name = schedule.name
    await session.delete(schedule)
    await session.flush()
    await events.emit(
        session,
        event_type=core.BackupEvent.SCHEDULE_DELETED,
        entity_type=core.BackupEntity.SCHEDULE,
        entity_id=schedule_id,
        actor_id=actor.id,
        payload={"name": name},
    )


async def ensure_default_schedule(session: AsyncSession) -> None:
    """Seed the nightly schedule once, on first boot.

    Idempotent by "are there any schedules at all": an operator who deletes every
    schedule meant it, and should not have one grow back."""
    if (await session.execute(select(BackupSchedule.id).limit(1))).first() is not None:
        return
    session.add(
        BackupSchedule(
            name=DEFAULT_SCHEDULE_NAME,
            enabled=True,
            config=DEFAULT_SCHEDULE_CONFIG,
            include_attachments=True,
            keep_last=settings.backup_retention_keep_last,
            next_run_at=next_run(DEFAULT_SCHEDULE_CONFIG, utcnow(), settings.scheduler_tz),
        )
    )
    await session.flush()
    logger.info("seeded the default nightly backup schedule (03:00, keep 7)")


# --- runs ---


async def list_runs(session: AsyncSession, limit: int = 20) -> list[BackupRun]:
    result = await session.execute(
        select(BackupRun).order_by(BackupRun.started_at.desc()).limit(limit)
    )
    return list(result.scalars())


async def get_run(session: AsyncSession, run_id: uuid.UUID) -> BackupRun:
    run = await session.get(BackupRun, run_id)
    if run is None:
        raise NotFoundError(core.BackupEntity.RUN, run_id)
    return run


async def _start_run(
    session: AsyncSession,
    *,
    kind: core.RunKind,
    actor: User | None,
    artifact_name: str | None = None,
    schedule_id: uuid.UUID | None = None,
) -> BackupRun:
    run = BackupRun(
        kind=kind.value,
        status=core.RunStatus.RUNNING.value,
        stage=core.RunStage.QUEUED.value,
        artifact_name=artifact_name,
        schedule_id=schedule_id,
        actor_id=actor.id if actor else None,
        started_at=utcnow(),
    )
    session.add(run)
    await session.flush()
    return run


async def mark_interrupted() -> None:
    """A process restart abandons in-flight asyncio tasks; a run left RUNNING is
    lying about being in progress. Called on startup."""
    async with SessionLocal() as session:
        await session.execute(
            update(BackupRun)
            .where(BackupRun.status == core.RunStatus.RUNNING.value)
            .values(
                status=core.RunStatus.FAILED.value,
                error="interrupted by a server restart",
                finished_at=utcnow(),
            )
        )
        await session.commit()


def _stage_writer(run_id: uuid.UUID):
    """Commit each stage on its own session so `GET /runs/{id}` sees live state."""

    def write(stage: core.RunStage) -> None:
        async def persist() -> None:
            async with SessionLocal() as session:
                await session.execute(
                    update(BackupRun).where(BackupRun.id == run_id).values(stage=stage.value)
                )
                await session.commit()

        asyncio.create_task(persist())  # noqa: RUF006 — fire and forget progress

    return write


async def _finish(run_id: uuid.UUID, *, error: str | None, name: str | None = None, size: int | None = None) -> None:
    async with SessionLocal() as session:
        await session.execute(
            update(BackupRun)
            .where(BackupRun.id == run_id)
            .values(
                status=(core.RunStatus.FAILED if error else core.RunStatus.SUCCEEDED).value,
                stage=core.RunStage.DONE.value,
                error=error,
                artifact_name=name,
                size_bytes=size,
                finished_at=utcnow(),
            )
        )
        await session.commit()


# --- the two operations ---


async def start_backup(
    session: AsyncSession,
    *,
    actor: User | None,
    include_attachments: bool | None = None,
    schedule: BackupSchedule | None = None,
) -> BackupRun:
    """Spawn a backup and return its run row immediately (the progress bar)."""
    run = await _start_run(
        session,
        kind=core.RunKind.BACKUP,
        actor=actor,
        schedule_id=schedule.id if schedule else None,
    )
    run_id, actor_id = run.id, (actor.id if actor else None)
    created_by = actor.email if actor else (f"schedule:{schedule.name}" if schedule else "system")
    schedule_id = str(schedule.id) if schedule else None
    keep_last = schedule.keep_last if schedule else None
    keep_days = schedule.keep_days if schedule else None

    async def execute() -> None:
        try:
            result = await core.create_backup(
                kind=core.BackupKind.SCHEDULED if schedule_id else core.BackupKind.MANUAL,
                include_attachments=include_attachments,
                created_by=created_by,
                schedule_id=schedule_id,
                on_stage=_stage_writer(run_id),
            )
        except Exception as exc:  # noqa: BLE001 — the run row carries the failure
            logger.exception("backup failed")
            await _finish(run_id, error=str(exc))
            await _record_schedule_result(schedule_id, error=str(exc))
            return
        if schedule_id:
            _stage_writer(run_id)(core.RunStage.PRUNING)
            await _prune(schedule_id, keep_last, keep_days)
        await _finish(run_id, error=None, name=result.name, size=result.size_bytes)
        await _record_schedule_result(schedule_id, error=None)
        async with SessionLocal() as emit_session:
            await events.emit(
                emit_session,
                core.BackupEvent.CREATED,
                entity_type=core.BackupEntity.BACKUP,
                entity_id=run_id,
                actor_id=actor_id,
                payload={"name": result.name, "bytes": result.size_bytes},
            )
            await emit_session.commit()

    asyncio.create_task(execute())  # noqa: RUF006 — tracked by the run row
    return run


async def _prune(schedule_id: str, keep_last: int | None, keep_days: int | None) -> None:
    doomed = core.prunable(
        core.listing(), schedule_id=schedule_id, keep_last=keep_last, keep_days=keep_days
    )
    for item in doomed:
        try:
            store.delete(item.name)
            logger.info("pruned %s (retention)", item.name)
        except OSError as exc:
            logger.warning("could not prune %s: %s", item.name, exc)


async def _record_schedule_result(schedule_id: str | None, *, error: str | None) -> None:
    if schedule_id is None:
        return
    async with SessionLocal() as session:
        await session.execute(
            update(BackupSchedule)
            .where(BackupSchedule.id == uuid.UUID(schedule_id))
            .values(
                last_run_at=utcnow(),
                last_status=(core.RunStatus.FAILED if error else core.RunStatus.SUCCEEDED).value,
                last_error=error,
            )
        )
        await session.commit()


async def start_restore(
    session: AsyncSession, name: str, *, actor: User, override_compatibility: bool
) -> BackupRun:
    """Spawn a restore. The API layer engages maintenance mode; the CLI does not
    need to, because nothing is serving when it runs."""
    stored = core.load(name)  # 404/422 before anything is touched
    verdict = core.compatibility(stored.manifest)
    if not verdict.restorable and not (verdict.needs_override and override_compatibility):
        raise ConflictError(core.BackupEntity.BACKUP, reason=verdict.reason or "incompatible backup")

    run = await _start_run(session, kind=core.RunKind.RESTORE, actor=actor, artifact_name=name)
    run_id, actor_id = run.id, actor.id

    async def execute() -> None:
        maintenance.engage(f"restoring {name}")
        try:
            await core.restore_backup(
                name,
                override_compatibility=override_compatibility,
                on_stage=_stage_writer(run_id),
            )
        except Exception as exc:  # noqa: BLE001
            logger.exception("restore failed")
            await _finish(run_id, error=str(exc), name=name)
            # Maintenance stays ENGAGED on failure: a half-restored Radd must not
            # serve traffic. An operator lifts it by restarting once satisfied.
            return
        # The run table is part of the database, so the restore just reverted it:
        # this run's own row is gone (it was created after the dump was taken) and
        # any run that was in flight AT DUMP TIME is back, still marked RUNNING.
        # `_finish` therefore updates 0 rows, and the honest completion signal for
        # a client is `maintenance: false` on /backups/status, not this run.
        await mark_interrupted()
        maintenance.release()
        await _finish(run_id, error=None, name=name)
        async with SessionLocal() as emit_session:
            await events.emit(
                emit_session,
                core.BackupEvent.RESTORED,
                entity_type=core.BackupEntity.BACKUP,
                entity_id=run_id,
                actor_id=actor_id,
                payload={"name": name},
            )
            await emit_session.commit()

    asyncio.create_task(execute())  # noqa: RUF006
    return run


# --- status ---


async def status(session: AsyncSession) -> dict[str, Any]:
    from radd.schema_version import SCHEMA_VERSION

    directory = core.directory_status()
    tools = await postgres.tool_status()
    key_id: str | None = None
    key_problem: str | None = None
    if settings.backup_encryption:
        try:
            key = core_service.active_key()
            key_id = key.key_id if key else None
        except core.BackupError as exc:
            key_problem = str(exc)
    upcoming = (
        await session.execute(
            select(BackupSchedule.next_run_at)
            .where(BackupSchedule.enabled.is_(True), BackupSchedule.next_run_at.isnot(None))
            .order_by(BackupSchedule.next_run_at)
            .limit(1)
        )
    ).scalar_one_or_none()
    return {
        "directory": directory.path,
        "directory_writable": directory.writable,
        "directory_problem": directory.problem,
        "free_bytes": directory.free_bytes,
        "pg_dump": {"path": tools.pg_dump.path, "version": tools.pg_dump.version},
        "pg_restore": {"path": tools.pg_restore.path, "version": tools.pg_restore.version},
        "tools_problem": tools.problem,
        "encryption_enabled": settings.backup_encryption,
        "key_id": key_id,
        "key_file": settings.backup_key_file,
        "key_problem": key_problem,
        "schema_version": SCHEMA_VERSION,
        "maintenance": maintenance.is_active(),
        "next_run_at": upcoming,
    }
