"""Move job (spec 102): copy -> verify -> repoint -> best-effort source delete.

Two tmp-dir filesystem hosts; the safety property under test: after any
outcome, every attachment row points at bytes that exist — an injected copy
failure leaves the row on the SOURCE (unrepointed, counted, reported), never
dangling. These tests COMMIT (the job runs with its own sessions), so they
clean up explicitly.
"""

import io
import uuid
from pathlib import Path

import pytest
from fastapi import UploadFile
from sqlalchemy import text

from radd.db import SessionLocal
from radd.exceptions import ConflictError
from radd.modules.attachments import clients, hosts, movejob, service
from radd.modules.attachments.schemas import StorageHostCreate
from radd.modules.attachments.types import (
    AttachmentParentType,
    DeliveryMode,
    MoveJobState,
    StorageHostType,
)
from radd.modules.auth.models import User
from radd.modules.auth.types import InstanceRole
from radd.modules.items import service as items_service
from radd.modules.items.schemas import ItemCreate
from radd.modules.projects import service as projects_service
from radd.modules.projects.schemas import ProjectCreate


@pytest.fixture
async def world(tmp_path):
    """Committed: admin, item, two hosts, three stored files. Torn down fully."""
    created: dict = {}
    async with SessionLocal() as db:
        admin = User(
            email=f"mv-{uuid.uuid4().hex[:8]}@example.com",
            name="Mover",
            instance_role=InstanceRole.ADMIN.value,
        )
        db.add(admin)
        await db.flush()
        source = await hosts.create_host(
            db,
            StorageHostCreate(
                name=f"src-{uuid.uuid4().hex[:6]}",
                host_type=StorageHostType.FILESYSTEM,
                root_dir=str(tmp_path / "src"),
                delivery_mode=DeliveryMode.PROXY,
                is_default=True,
            ),
        )
        target = await hosts.create_host(
            db,
            StorageHostCreate(
                name=f"dst-{uuid.uuid4().hex[:6]}",
                host_type=StorageHostType.FILESYSTEM,
                root_dir=str(tmp_path / "dst"),
                delivery_mode=DeliveryMode.PROXY,
            ),
        )
        project = await projects_service.create_project(
            db, ProjectCreate(key=f"MV{uuid.uuid4().hex[:4].upper()}", name="Move P")
        )
        item = await items_service.create_item(
            db, ItemCreate(project_id=project.id, title="movable"), actor=admin
        )
        attachments = []
        for index in range(3):
            attachments.append(
                await service.save_upload(
                    db,
                    entity_type=AttachmentParentType.ITEM.value,
                    entity_id=item.id,
                    upload=UploadFile(
                        file=io.BytesIO(f"payload-{index}".encode()),
                        filename=f"f{index}.bin",
                        headers=None,
                    ),
                    actor_id=admin.id,
                )
            )
        await db.commit()
        created = {
            "admin": admin,
            "source": source,
            "target": target,
            "project": project,
            "attachments": attachments,
        }
    yield created
    # Committed fixtures: remove what blocks other tests (move jobs, hosts and
    # their attachments); the randomized project/user rows are inert leftovers
    # in the throwaway test DB and cascade-guarded, so they stay.
    async with SessionLocal() as db:
        await db.execute(text("DELETE FROM attachment_move_jobs"))
        await db.execute(
            text("DELETE FROM attachments WHERE storage_host_id IN (:a, :b)").bindparams(
                a=created["source"].id, b=created["target"].id
            )
        )
        await db.execute(
            text("DELETE FROM storage_hosts WHERE id IN (:a, :b)").bindparams(
                a=created["source"].id, b=created["target"].id
            )
        )
        await db.commit()


async def test_move_repoints_rows_and_relocates_bytes(world):
    async with SessionLocal() as db:
        job = await movejob.create_job(
            db,
            source_host_id=world["source"].id,
            target_host_id=world["target"].id,
            actor_id=world["admin"].id,
        )
        await db.commit()
        job_id = job.id
        assert job.total == 3
    await movejob.execute(job_id)
    async with SessionLocal() as db:
        done = await movejob.get_job(db, job_id)
        assert done.state == MoveJobState.DONE.value
        assert (done.moved, done.failed) == (3, 0)
    for attachment in world["attachments"]:
        assert (Path(world["target"].root_dir) / attachment.storage_name).exists()
        assert not (Path(world["source"].root_dir) / attachment.storage_name).exists()
    async with SessionLocal() as db:
        stored = await service.get_attachment(db, world["attachments"][0].id)
        assert stored.storage_host_id == world["target"].id


async def test_injected_copy_failure_leaves_the_row_on_the_source(world, monkeypatch):
    victim = world["attachments"][1]
    original_save = clients.FilesystemClient.save

    async def sabotaged(self, storage_name, source, *, size, content_type):
        if storage_name == victim.storage_name:
            raise OSError("disk full")
        await original_save(self, storage_name, source, size=size, content_type=content_type)

    monkeypatch.setattr(clients.FilesystemClient, "save", sabotaged)
    async with SessionLocal() as db:
        job = await movejob.create_job(
            db,
            source_host_id=world["source"].id,
            target_host_id=world["target"].id,
            actor_id=world["admin"].id,
        )
        await db.commit()
        job_id = job.id
    await movejob.execute(job_id)
    async with SessionLocal() as db:
        done = await movejob.get_job(db, job_id)
        assert done.state == MoveJobState.DONE_WITH_FAILURES.value
        assert done.moved == 2 and done.failed == 1
        assert done.problems[0]["filename"] == victim.filename
        # The failed row still points at the SOURCE, whose bytes still exist.
        stored = await service.get_attachment(db, victim.id)
        assert stored.storage_host_id == world["source"].id
    assert (Path(world["source"].root_dir) / victim.storage_name).exists()


async def test_same_host_and_concurrent_jobs_are_refused(world):
    async with SessionLocal() as db:
        with pytest.raises(ConflictError):
            await movejob.create_job(
                db,
                source_host_id=world["source"].id,
                target_host_id=world["source"].id,
                actor_id=world["admin"].id,
            )
        await movejob.create_job(
            db,
            source_host_id=world["source"].id,
            target_host_id=world["target"].id,
            actor_id=world["admin"].id,
        )
        await db.commit()
        with pytest.raises(ConflictError):
            await movejob.create_job(
                db,
                source_host_id=world["source"].id,
                target_host_id=world["target"].id,
                actor_id=world["admin"].id,
            )
