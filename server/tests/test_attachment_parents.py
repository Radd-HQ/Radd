"""Polymorphic attachment parents (spec 102): items and wiki pages own files.

The invariants: parent bindings gate every touch (item perms are project-scoped,
doc perms are the global atoms), `item_id` survives as a property + event field
for item parents (pre-102 API/notify compat), bytes actually land on and leave
the host, and an unknown parent type is a clean 404.

DB-backed; flushed, never committed — the session rolls back at teardown.
"""

import io
import uuid
from pathlib import Path

import pytest
from fastapi import UploadFile
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from radd.config import settings as config
from radd.exceptions import ForbiddenError, NotFoundError
from radd.modules.attachments import hosts, parents, service
from radd.modules.attachments.schemas import StorageHostCreate
from radd.modules.attachments.types import (
    AttachmentParentType,
    DeliveryMode,
    StorageHostType,
)
from radd.modules.auth import roles as auth_roles
from radd.modules.auth.models import Role, User
from radd.modules.auth.schemas import RoleUpdate
from radd.modules.auth.types import BuiltinRoleKey, InstanceRole, Permission
from radd.modules.pages import service as docs_service, spaces as docs_spaces
from radd.modules.pages.schemas import PageCreate, PageSpaceCreate
from radd.modules.items import service as items_service
from radd.modules.items.schemas import ItemCreate
from radd.modules.projects import service as projects_service
from radd.modules.projects.schemas import ProjectCreate


@pytest.fixture
async def db():
    engine = create_async_engine(config.database_url)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as session:
        yield session
        await session.rollback()
    await engine.dispose()


@pytest.fixture
async def admin(db) -> User:
    user = User(
        email=f"att-{uuid.uuid4().hex[:8]}@example.com",
        name="Attach Admin",
        instance_role=InstanceRole.ADMIN.value,
    )
    db.add(user)
    await db.flush()
    return user


@pytest.fixture
async def member(db) -> User:
    user = User(email=f"plain-{uuid.uuid4().hex[:8]}@example.com", name="Plain Member")
    db.add(user)
    await db.flush()
    return user


@pytest.fixture
async def host(db, tmp_path):
    return await hosts.create_host(
        db,
        StorageHostCreate(
            name=f"fs-{uuid.uuid4().hex[:6]}",
            host_type=StorageHostType.FILESYSTEM,
            root_dir=str(tmp_path / "store"),
            delivery_mode=DeliveryMode.PROXY,
            is_default=True,
        ),
    )


def _upload(name: str = "shot.png", data: bytes = b"png-bytes") -> UploadFile:
    return UploadFile(file=io.BytesIO(data), filename=name, headers=None)


async def _item(db, admin):
    project = await projects_service.create_project(
        db, ProjectCreate(key=f"AT{uuid.uuid4().hex[:4].upper()}", name="Attach P")
    )
    item = await items_service.create_item(
        db, ItemCreate(project_id=project.id, title="holds files"), actor=admin
    )
    return project, item


async def _page(db, admin):
    space = await docs_spaces.create_space(
        db, PageSpaceCreate(name=f"Space {uuid.uuid4().hex[:6]}"), actor_id=admin.id
    )
    return await docs_service.create_page(
        db, PageCreate(space_id=space.id, title="Runbook"), actor_id=admin.id
    )


async def test_item_parent_round_trip_with_bytes_on_disk(db, admin, host, tmp_path):
    _, item = await _item(db, admin)
    attachment = await service.save_upload(
        db,
        entity_type=AttachmentParentType.ITEM.value,
        entity_id=item.id,
        upload=_upload(),
        actor_id=admin.id,
    )
    assert attachment.item_id == item.id  # the back-compat property
    assert attachment.storage_host_id == host.id
    stored = Path(host.root_dir) / attachment.storage_name
    assert stored.read_bytes() == b"png-bytes"

    listed = await service.list_for_item(db, item.id)
    assert [a.id for a in listed] == [attachment.id]
    # The generic listing agrees with the legacy wrapper.
    generic = await service.list_for_entity(db, AttachmentParentType.ITEM.value, item.id)
    assert [a.id for a in generic] == [attachment.id]

    await service.delete_attachment(db, attachment, actor_id=admin.id)
    assert not stored.exists()  # bytes go with the row


async def test_page_parent_has_no_item_id(db, admin, host):
    page = await _page(db, admin)
    attachment = await service.save_upload(
        db,
        entity_type=AttachmentParentType.PAGE.value,
        entity_id=page.id,
        upload=_upload("diagram.png"),
        actor_id=admin.id,
    )
    assert attachment.item_id is None
    listed = await service.list_for_entity(db, AttachmentParentType.PAGE.value, page.id)
    assert [a.id for a in listed] == [attachment.id]
    # Wiki files never appear in an item listing.
    assert await service.list_for_item(db, page.id) == []


async def _grant_globally(db, user, permission):
    """Give every active user an atom by widening the Baseline role (RADD-773).

    Deliberately the production path — `update_role` — rather than poking the
    row: it is what an admin does in Settings, and it exercises the memo
    invalidation that makes the change visible inside the same request.
    """
    del user  # baseline applies to everyone; the parameter documents the intent
    from sqlalchemy import select

    role = (
        await db.execute(select(Role).where(Role.key == BuiltinRoleKey.BASELINE.value))
    ).scalar_one()
    await auth_roles.update_role(
        db, role.id, RoleUpdate(permissions=[*role.permissions, permission.value])
    )


async def test_doc_binding_enforces_the_global_doc_atoms(db, admin, member, host):
    page = await _page(db, admin)
    binding = parents.binding_for(AttachmentParentType.PAGE.value)
    # RADD-773 reversed what this used to assert. `page.write` was free for
    # every active user (spec 43, "a read-only wiki is useless") via a hardcoded
    # global set — which is how a member granted nothing anywhere could edit any
    # page on the instance, with no screen saying so. It is an ordinary grant
    # now: absent by default, present when the Baseline role or any granted role
    # carries it. This test is the one place in the suite that behaviour change
    # is visible, which is the right number.
    with pytest.raises(ForbiddenError):
        await binding.require_write(db, member, page.id)
    await _grant_globally(db, member, Permission.PAGE_WRITE)
    await binding.require_write(db, member, page.id)
    # page.manage (delete anyone's file) is still a separate, admin-tier atom.
    with pytest.raises(ForbiddenError):
        await binding.require_admin(db, member, page.id)
    await binding.require_admin(db, admin, page.id)
    # A vanished page 404s before any permission verdict.
    with pytest.raises(NotFoundError):
        await binding.require_read(db, admin, uuid.uuid4())


async def test_unknown_parent_type_is_a_clean_404(db):
    with pytest.raises(NotFoundError):
        parents.binding_for("comment")


async def test_item_binding_project_id_feeds_routing_context(db, admin, host):
    project, item = await _item(db, admin)
    binding = parents.binding_for(AttachmentParentType.ITEM.value)
    assert await binding.project_id_of(db, item.id) == project.id
    doc_binding = parents.binding_for(AttachmentParentType.PAGE.value)
    page = await _page(db, admin)
    assert await doc_binding.project_id_of(db, page.id) is None


# --- RADD-744: the GC's parent map comes from the registry --------------------


def test_every_attachment_parent_declares_how_it_dies():
    """The polymorphic parent has no FK, so `gc.py` is what removes the rows AND
    THE BYTES. It used to decide from a hardcoded dict, which meant a parent
    registered by a PLUGIN — the seam this registry exists for — got no cleanup,
    and its files stayed on a storage host forever with nothing pointing at
    them. A binding with no delete event now fails the build instead."""
    import radd.modules.pages  # noqa: F401 — registers the `page` binding
    from radd.modules.attachments.parents import bindings

    registered = bindings()
    assert registered, "no attachment parents registered at all"
    for binding in registered:
        assert binding.deleted_event, f"{binding.entity_type} declares no delete event"
        assert binding.deleted_event.endswith(".deleted")


def test_registering_a_parent_registers_its_cleanup():
    """RADD-745: the two are ONE act, so a plugin cannot register a parent and
    leave its bytes on a storage host forever."""
    import radd.modules.pages  # noqa: F401
    from radd.kernel.registry import registries
    from radd.modules.attachments.parents import bindings

    names = {c.name for c in registries.cascades}
    for binding in bindings():
        assert f"attachments:{binding.entity_type}" in names
