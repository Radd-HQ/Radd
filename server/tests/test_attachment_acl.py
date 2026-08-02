"""Per-attachment ACL (spec 102, on the spec-92 grant framework).

Invariants: no grants = exactly the pre-102 behavior (parent-read opens the
file); any grant row restricts to matching subjects; the uploader and parent
writers always pass; listings FILTER unreadable rows and FLAG restricted ones;
grants are cleared with the row; and attachment content never reaches the
search index (filenames are not indexed — pinned so a future indexer change
must consciously route through the ACL).
"""

import io
import uuid

import pytest
from fastapi import UploadFile
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from radd.config import settings as config
from radd.modules.access import service as access_service
from radd.modules.access.types import Access, GrantSubject
from radd.modules.attachments import acl, hosts, service
from radd.modules.attachments.schemas import StorageHostCreate
from radd.modules.attachments.types import (
    AttachmentParentType,
    DeliveryMode,
    StorageHostType,
)
from radd.modules.auth.models import User
from radd.modules.auth.types import InstanceRole
from radd.modules.items import service as items_service
from radd.modules.items.schemas import ItemCreate
from radd.modules.projects import service as projects_service
from radd.modules.projects.schemas import ProjectCreate
from radd.modules.teams import service as teams_service
from radd.modules.teams.schemas import TeamCreate


@pytest.fixture
async def db():
    engine = create_async_engine(config.database_url)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as session:
        yield session
        await session.rollback()
    await engine.dispose()


async def _user(db, *, admin: bool = False) -> User:
    user = User(
        email=f"acl-{uuid.uuid4().hex[:8]}@example.com",
        name="ACL",
        instance_role=(InstanceRole.ADMIN if admin else InstanceRole.MEMBER).value,
    )
    db.add(user)
    await db.flush()
    return user


@pytest.fixture
async def setup(db, tmp_path):
    """(uploader-admin, plain member, item, attachment) on a tmp filesystem host."""
    admin = await _user(db, admin=True)
    member = await _user(db)
    await hosts.create_host(
        db,
        StorageHostCreate(
            name=f"fs-{uuid.uuid4().hex[:6]}",
            host_type=StorageHostType.FILESYSTEM,
            root_dir=str(tmp_path / "store"),
            delivery_mode=DeliveryMode.PROXY,
            is_default=True,
        ),
    )
    project = await projects_service.create_project(
        db, ProjectCreate(key=f"AC{uuid.uuid4().hex[:4].upper()}", name="ACL P")
    )
    item = await items_service.create_item(
        db, ItemCreate(project_id=project.id, title="secure files"), actor=admin
    )
    attachment = await service.save_upload(
        db,
        entity_type=AttachmentParentType.ITEM.value,
        entity_id=item.id,
        upload=UploadFile(file=io.BytesIO(b"secret"), filename="s.pdf", headers=None),
        actor_id=admin.id,
    )
    return admin, member, item, attachment


async def _grant(db, attachment_id, subject_type, subject_id):
    await access_service.add_grant(
        db,
        acl.ATTACHMENT_RESOURCE,
        str(attachment_id),
        subject_type=GrantSubject(subject_type),
        subject_id=subject_id,
        access=Access.READ.value,
    )


async def test_no_grants_means_open_to_parent_readers(db, setup):
    admin, member, item, attachment = setup
    assert await acl.attachment_readable(db, member, attachment) is True


async def test_a_user_grant_restricts_everyone_else(db, setup):
    admin, member, item, attachment = setup
    chosen = await _user(db)
    await _grant(db, attachment.id, GrantSubject.USER.value, chosen.id)
    assert await acl.attachment_readable(db, chosen, attachment) is True
    assert await acl.attachment_readable(db, member, attachment) is False
    # The uploader always passes their own file's gate.
    assert await acl.attachment_readable(db, admin, attachment) is True


async def test_a_team_grant_admits_members(db, setup):
    admin, member, item, attachment = setup
    team = await teams_service.create_team(db, TeamCreate(name=f"T-{uuid.uuid4().hex[:6]}"))
    await teams_service.add_team_member(db, team.id, member.id)
    await _grant(db, attachment.id, GrantSubject.TEAM.value, team.id)
    outsider = await _user(db)
    assert await acl.attachment_readable(db, member, attachment) is True
    assert await acl.attachment_readable(db, outsider, attachment) is False


async def test_listing_filters_unreadable_and_flags_restricted(db, setup):
    admin, member, item, attachment = setup
    open_one = await service.save_upload(
        db,
        entity_type=AttachmentParentType.ITEM.value,
        entity_id=item.id,
        upload=UploadFile(file=io.BytesIO(b"open"), filename="o.txt", headers=None),
        actor_id=admin.id,
    )
    chosen = await _user(db)
    await _grant(db, attachment.id, GrantSubject.USER.value, chosen.id)
    listed = await service.list_for_item(db, item.id)
    verdicts = await acl.readable_map(db, member, listed)
    assert verdicts[open_one.id] == (True, False)
    assert verdicts[attachment.id] == (False, True)
    # The chosen user sees both; the restricted one is flagged for the lock badge.
    chosen_verdicts = await acl.readable_map(db, chosen, listed)
    assert chosen_verdicts[attachment.id] == (True, True)


async def test_deleting_an_attachment_clears_its_grants(db, setup):
    admin, member, item, attachment = setup
    chosen = await _user(db)
    await _grant(db, attachment.id, GrantSubject.USER.value, chosen.id)
    await service.delete_attachment(db, attachment, actor_id=admin.id)
    remaining = await access_service.list_for_resource(
        db, acl.ATTACHMENT_RESOURCE, str(attachment.id)
    )
    assert remaining == []


async def test_attachment_events_never_touch_the_search_index(db, setup):
    """Filenames are not indexed — a restricted file's name must not leak
    through search. Pinned: if the indexer ever grows attachment handling, it
    must consciously route through the ACL."""
    admin, member, item, attachment = setup
    hits = await db.execute(
        text("SELECT count(*) FROM search_index WHERE title LIKE :n OR description LIKE :n"),
        {"n": "%s.pdf%"},
    )
    assert hits.scalar() == 0
    from radd.modules.search import indexer

    assert not hasattr(indexer, "attachment_bodies")  # no such seam exists today