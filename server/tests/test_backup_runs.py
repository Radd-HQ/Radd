"""Backup runs as background jobs, and what their API says about time (RADD-1427).

The engine is replaced by a stub: these tests are about the run's lifecycle
around it — admission, the run row, the completion event — not about pg_dump.
"""

import asyncio
from contextlib import asynccontextmanager
from datetime import datetime
from types import SimpleNamespace

from sqlalchemy import select

from radd.backup.types import BackupEvent, RunStatus
from radd.kernel import admission
from radd.modules.backup import schemas, service
from radd.modules.events.models import Event

BACKUP_PLUGIN = "backup"


async def test_a_backup_is_admitted_under_its_plugin_and_records_its_event(db, admin, monkeypatch):
    """The job was a bare `asyncio.create_task`: unreferenced, and invisible to the
    plugin lifecycle, so disabling `backup` did not wait for a run in flight. It is
    spawned under its owner now. And the completion event, emitted with its type
    passed POSITIONALLY to a keyword-only `emit`, had raised a TypeError after every
    successful run, so `backup.created` never reached the audit log."""
    release = asyncio.Event()

    async def create_backup(**_kwargs):
        await release.wait()
        return SimpleNamespace(name="radd-stub.backup", size_bytes=42)

    @asynccontextmanager
    async def borrowed():
        yield db

    monkeypatch.setattr(service.core, "create_backup", create_backup)
    monkeypatch.setattr(service, "SessionLocal", borrowed)
    monkeypatch.setattr(db, "commit", db.flush)

    token = admission.owner.set(BACKUP_PLUGIN)
    try:
        run = await service.start_backup(db, actor=admin)
    finally:
        admission.owner.reset(token)
    assert admission.gate.counts.get(BACKUP_PLUGIN) == 1, "the run is not counted against its plugin"

    release.set()
    await asyncio.wait_for(admission.gate.drain(BACKUP_PLUGIN), timeout=5)
    await db.refresh(run)
    assert run.status == RunStatus.SUCCEEDED.value
    emitted = await db.scalar(
        select(Event).where(Event.event_type == BackupEvent.CREATED, Event.entity_id == str(run.id))
    )
    assert emitted is not None and emitted.payload["name"] == "radd-stub.backup"


def test_every_backup_time_leaves_as_utc():
    """Naive-UTC columns serialized without `Z` read as the browser's LOCAL time."""
    naive = datetime(2026, 9, 27, 12, 0)
    checked = []
    for model in (schemas.ScheduleRead, schemas.BackupRead, schemas.RunRead, schemas.StatusRead):
        for name, field in model.model_fields.items():
            if "datetime" not in str(field.annotation):
                continue
            wire = model.model_construct(**{name: naive}).model_dump(mode="json", include={name})
            assert wire[name] == "2026-09-27T12:00:00Z", f"{model.__name__}.{name}"
            checked.append(name)
    assert len(checked) == 6
