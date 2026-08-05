"""Backup API (spec 99 §5) — instance admin only, every endpoint.

There is no weaker tier worth delegating: a *download* is full data exfiltration
(password hashes, TOTP seeds, API tokens) and an *upload* hands `pg_restore` a
file that executes SQL. The gate is the `jiraimport` shape.

Artifact names are validated as NAMES, never joined as paths. An invalid name and
a missing file both answer 404, which leaks nothing about the directory.
"""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy.ext.asyncio import AsyncSession

from radd import backup as core
from radd.backup import artifact as art, store
from radd.config import settings
from radd.db import get_session
from radd.exceptions import ConflictError, ForbiddenError, NotFoundError
from radd.modules.auth.deps import CurrentUser
from radd.modules.auth.models import User
from radd.modules.auth.types import InstanceRole

from . import service
from .models import BackupRun, BackupSchedule
from .schemas import (
    BackupCreateRequest,
    BackupRead,
    RestoreRequest,
    RunRead,
    ScheduleCreate,
    ScheduleRead,
    ScheduleUpdate,
    StatusRead,
)

router = APIRouter(prefix="/backups", tags=["backups"])

Session = Annotated[AsyncSession, Depends(get_session)]


def _require_instance_admin(actor: User) -> None:
    if InstanceRole(actor.instance_role) is not InstanceRole.ADMIN:
        raise ForbiddenError("backups require an instance admin")


def _as_backup(stored: core.StoredBackup) -> BackupRead:
    manifest = stored.manifest
    verdict = core.compatibility(manifest)
    return BackupRead(
        name=stored.name,
        size_bytes=stored.size_bytes,
        created_at=stored.created_at,
        kind=stored.kind,
        complete=stored.complete,
        encrypted=bool(manifest and manifest.encrypted),
        key_id=manifest.key_id if manifest else None,
        includes_attachments=bool(manifest and manifest.includes_attachments),
        schema_version=manifest.schema_version if manifest else None,
        radd_version=manifest.radd_version if manifest else None,
        created_by=manifest.created_by if manifest else None,
        restorable=stored.complete and verdict.restorable,
        problem=stored.problem or verdict.reason,
    )


def _as_run(run: BackupRun) -> RunRead:
    return RunRead(
        id=run.id,
        kind=run.kind,
        status=run.status,
        stage=run.stage,
        artifact_name=run.artifact_name,
        size_bytes=run.size_bytes,
        started_at=run.started_at,
        finished_at=run.finished_at,
        error=run.error,
    )


def _as_schedule(schedule: BackupSchedule) -> ScheduleRead:
    return ScheduleRead(
        id=schedule.id,
        name=schedule.name,
        enabled=schedule.enabled,
        config=schedule.config,
        include_attachments=schedule.include_attachments,
        keep_last=schedule.keep_last,
        keep_days=schedule.keep_days,
        next_run_at=schedule.next_run_at,
        last_run_at=schedule.last_run_at,
        last_status=schedule.last_status,
        last_error=schedule.last_error,
    )


def _resolve(name: str) -> core.StoredBackup:
    try:
        return store.load(name)
    except (art.ArtifactInvalid, FileNotFoundError) as exc:
        # An invalid name and a missing file are the same answer, and 404 leaks
        # nothing about what the directory does or does not contain.
        raise NotFoundError(core.BackupEntity.BACKUP, name) from exc


# --- status, list, create ---


@router.get("/status", response_model=StatusRead)
async def backup_status(session: Session, user: CurrentUser) -> StatusRead:
    """Directory, tools, key and next run — where a broken deploy shows up."""
    _require_instance_admin(user)
    return StatusRead(**await service.status(session))


@router.get("", response_model=list[BackupRead])
async def list_backups(user: CurrentUser) -> list[BackupRead]:
    """Read from DISK, not a table: a restore rewrites the database, so a table
    would roll its own inventory back with it (spec 99 §3)."""
    _require_instance_admin(user)
    return [_as_backup(item) for item in core.listing()]


@router.post("", response_model=RunRead, status_code=202)
async def create_backup(data: BackupCreateRequest, session: Session, user: CurrentUser) -> RunRead:
    _require_instance_admin(user)
    run = await service.start_backup(
        session, actor=user, include_attachments=data.include_attachments
    )
    return _as_run(run)


@router.get("/runs/{run_id}", response_model=RunRead)
async def get_run(run_id: uuid.UUID, session: Session, user: CurrentUser) -> RunRead:
    """Stays live during maintenance so a restore can be watched to completion."""
    _require_instance_admin(user)
    return _as_run(await service.get_run(session, run_id))


# --- schedules ---


@router.get("/schedules", response_model=list[ScheduleRead])
async def list_schedules(session: Session, user: CurrentUser) -> list[ScheduleRead]:
    _require_instance_admin(user)
    return [_as_schedule(item) for item in await service.list_schedules(session)]


@router.post("/schedules", response_model=ScheduleRead, status_code=201)
async def create_schedule(data: ScheduleCreate, session: Session, user: CurrentUser) -> ScheduleRead:
    _require_instance_admin(user)
    return _as_schedule(await service.create_schedule(session, data, user))


@router.patch("/schedules/{schedule_id}", response_model=ScheduleRead)
async def update_schedule(
    schedule_id: uuid.UUID, data: ScheduleUpdate, session: Session, user: CurrentUser
) -> ScheduleRead:
    _require_instance_admin(user)
    return _as_schedule(await service.update_schedule(session, schedule_id, data, user))


@router.delete("/schedules/{schedule_id}", status_code=204)
async def delete_schedule(schedule_id: uuid.UUID, session: Session, user: CurrentUser) -> None:
    _require_instance_admin(user)
    await service.delete_schedule(session, schedule_id, user)


# --- one artifact ---


@router.get("/{name}/download")
async def download_backup(name: str, user: CurrentUser) -> FileResponse:
    _require_instance_admin(user)
    stored = _resolve(name)
    return FileResponse(
        stored.path, media_type="application/octet-stream", filename=stored.name
    )


@router.delete("/{name}", status_code=204)
async def delete_backup(name: str, session: Session, user: CurrentUser) -> None:
    _require_instance_admin(user)
    _resolve(name)
    store.delete(name)
    from radd.modules.events import service as events

    await events.emit(
        session,
        event_type=core.BackupEvent.DELETED,
        entity_type=core.BackupEntity.BACKUP,
        entity_id=name,
        actor_id=user.id,
        payload={"name": name},
    )


@router.post("/upload", response_model=BackupRead, status_code=201)
async def upload_backup(file: UploadFile, session: Session, user: CurrentUser) -> BackupRead:
    """Stream to disk, then verify before it is allowed to sit among the backups.

    Untrusted input by definition: an artifact is a file that `pg_restore` will
    execute. It is written under a generated name (never the client's), parsed,
    and discarded unless its header is a valid manifest."""
    _require_instance_admin(user)
    directory = core.directory_status()
    if not directory.writable:
        raise ConflictError(core.BackupEntity.BACKUP, reason=directory.problem or "unwritable directory")

    name = art.new_artifact_name()
    target = store.ensure_dir() / name
    limit = settings.backup_max_upload_bytes
    written = 0
    try:
        with target.open("wb") as handle:
            while chunk := await file.read(1 << 20):
                written += len(chunk)
                if limit and written > limit:
                    raise ConflictError(
                        core.BackupEntity.BACKUP,
                        reason=f"upload exceeds the {limit} byte limit",
                    )
                handle.write(chunk)
        stored = store.load(name)
        if stored.manifest is None:
            raise ConflictError(
                core.BackupEntity.BACKUP, reason=stored.problem or "not a Radd backup artifact"
            )
        if not stored.complete:
            raise ConflictError(
                core.BackupEntity.BACKUP,
                reason="the uploaded artifact has no footer — it is incomplete",
            )
    except Exception:
        target.unlink(missing_ok=True)
        raise

    from radd.modules.events import service as events

    await events.emit(
        session,
        event_type=core.BackupEvent.UPLOADED,
        entity_type=core.BackupEntity.BACKUP,
        entity_id=name,
        actor_id=user.id,
        payload={"name": name, "bytes": written},
    )
    return _as_backup(stored)


@router.post("/{name}/restore", response_model=RunRead, status_code=202)
async def restore_backup(
    name: str, data: RestoreRequest, session: Session, user: CurrentUser
) -> RunRead:
    """Replace this instance's data. Confirmation must name the database — the
    same guard the CLI prompts for, so a mis-click cannot do this."""
    _require_instance_admin(user)
    _resolve(name)
    from radd.backup import postgres

    if data.confirm.strip() != postgres.database_name():
        raise ConflictError(
            core.BackupEntity.BACKUP,
            reason=f"confirmation must be the database name ({postgres.database_name()})",
        )
    run = await service.start_restore(
        session, name, actor=user, override_compatibility=data.override_compatibility
    )
    return _as_run(run)
