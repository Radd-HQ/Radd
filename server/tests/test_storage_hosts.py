"""Storage host registry (spec 102) — the invariants Settings → Storage leans on.

Exactly one default (first host in becomes it; promotion clears the rest), a
host holding attachments cannot be deleted, an empty secret on update keeps the
stored one, and a filesystem host can never deliver presigned.

Tests are flushed, never committed; the session rolls back at teardown. The
fixture clears the host table inside the transaction because the first-in
default invariant needs a known-empty starting point.
"""

import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from radd.config import settings
from radd.exceptions import ConflictError
from radd.modules.attachments import hosts
from radd.modules.attachments.models import Attachment
from radd.modules.attachments.schemas import StorageHostCreate, StorageHostUpdate
from radd.modules.attachments.types import (
    AttachmentParentType,
    AttachmentState,
    DeliveryMode,
    StorageHostType,
)


@pytest.fixture
async def db():
    engine = create_async_engine(settings.database_url)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as session:
        # Known-empty tables (rolled back at teardown) — the default invariants
        # are statements about the whole table.
        await session.execute(text("DELETE FROM attachments"))
        await session.execute(text("DELETE FROM storage_hosts"))
        yield session
        await session.rollback()
    await engine.dispose()


def _s3(name: str = "", **overrides) -> StorageHostCreate:
    payload = {
        "name": name or f"host-{uuid.uuid4().hex[:8]}",
        "host_type": StorageHostType.S3,
        "endpoint": "s3.zone.example.com:3900",
        "access_key": "GK1",
        "secret_key": "secret-1",
        "bucket": "radd",
        "delivery_mode": DeliveryMode.PRESIGNED,
    }
    payload.update(overrides)
    return StorageHostCreate(**payload)


def _filesystem(name: str = "", **overrides) -> StorageHostCreate:
    payload = {
        "name": name or f"disk-{uuid.uuid4().hex[:8]}",
        "host_type": StorageHostType.FILESYSTEM,
        "root_dir": "/tmp/radd-test-attachments",
        "delivery_mode": DeliveryMode.PROXY,
    }
    payload.update(overrides)
    return StorageHostCreate(**payload)


async def _default_names(session) -> list[str]:
    session.expire_all()  # make_default clears siblings via UPDATE, behind the ORM's back
    return [host.name for host in await hosts.list_hosts(session) if host.is_default]


# --- the default invariant ----------------------------------------------------


async def test_first_host_in_becomes_the_default(db):
    first = await hosts.create_host(db, _s3("first"))
    assert first.is_default
    second = await hosts.create_host(db, _s3("second"))
    assert not second.is_default
    assert await _default_names(db) == ["first"]


async def test_exactly_one_default_survives_promotion(db):
    await hosts.create_host(db, _s3("a"))
    b = await hosts.create_host(db, _s3("b", is_default=True))
    assert await _default_names(db) == ["b"]
    await hosts.make_default(db, await hosts.get_host(db, b.id))
    assert await _default_names(db) == ["b"]  # idempotent, still exactly one


async def test_deleting_the_default_promotes_a_survivor(db):
    first = await hosts.create_host(db, _s3("first"))
    await hosts.create_host(db, _s3("second"))
    await hosts.delete_host(db, first.id)
    assert await _default_names(db) == ["second"]


# --- deletion guards ----------------------------------------------------------


async def test_delete_with_attachments_conflicts(db):
    host = await hosts.create_host(db, _s3())
    db.add(
        Attachment(
            entity_type=AttachmentParentType.ITEM.value,
            entity_id=uuid.uuid4(),
            filename="design.png",
            content_type="image/png",
            size_bytes=1,
            storage_name=uuid.uuid4().hex,
            storage_host_id=host.id,
            state=AttachmentState.STORED.value,
        )
    )
    await db.flush()
    with pytest.raises(ConflictError, match="move them first"):
        await hosts.delete_host(db, host.id)


# --- credential round-trip ----------------------------------------------------


async def test_update_with_empty_secret_keeps_the_stored_one(db):
    host = await hosts.create_host(db, _s3(secret_key="stored-secret"))
    await hosts.update_host(
        db, host.id, StorageHostUpdate(secret_key=hosts.UNCHANGED_CREDENTIAL, name="renamed")
    )
    assert host.secret_key == "stored-secret"
    assert host.name == "renamed"


# --- delivery-mode validation -------------------------------------------------


async def test_filesystem_host_rejects_presigned_delivery_on_create(db):
    with pytest.raises(ConflictError, match="proxy"):
        await hosts.create_host(db, _filesystem(delivery_mode=DeliveryMode.PRESIGNED))


async def test_filesystem_host_rejects_presigned_delivery_on_update(db):
    host = await hosts.create_host(db, _filesystem())
    with pytest.raises(ConflictError, match="proxy"):
        await hosts.update_host(
            db, host.id, StorageHostUpdate(delivery_mode=DeliveryMode.PRESIGNED)
        )
