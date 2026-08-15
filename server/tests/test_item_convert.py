"""RADD-1089 — kind conversion: every direction either fits the hierarchy or
refuses naming exactly what blocks it."""

import uuid

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from radd.config import settings
from radd.exceptions import ConflictError
from radd.modules.auth.models import User
from radd.modules.auth.types import InstanceRole
from radd.modules.items import service as items_service
from radd.modules.items.enums import ItemKind
from radd.modules.items.schemas import ItemCreate
from radd.modules.projects import service as projects_service
from radd.modules.projects.schemas import ProjectCreate


@pytest.fixture
async def db():
    engine = create_async_engine(settings.database_url)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as session:
        yield session
        await session.rollback()
    await engine.dispose()


async def _world(db):
    admin = User(
        email=f"cv-{uuid.uuid4().hex[:8]}@example.com",
        name="Converter",
        instance_role=InstanceRole.ADMIN.value,
    )
    db.add(admin)
    await db.flush()
    project = await projects_service.create_project(
        db, ProjectCreate(key=f"CV{uuid.uuid4().hex[:4].upper()}", name="Convert P"),
        actor_id=admin.id,
    )
    return admin, project


async def _item(db, admin, project, **kwargs):
    return await items_service.create_item(
        db, ItemCreate(project_id=project.id, title=kwargs.pop("title", "x"), **kwargs),
        actor=admin,
    )


async def test_issue_to_epic_and_back(db):
    admin, project = await _world(db)
    issue = await _item(db, admin, project, title="grows up")
    epic = await items_service.convert_item_kind(db, issue.id, admin, kind=ItemKind.EPIC)
    assert epic.kind == ItemKind.EPIC
    back = await items_service.convert_item_kind(db, issue.id, admin, kind=ItemKind.ISSUE)
    assert back.kind == ItemKind.ISSUE


async def test_epic_with_children_refuses_naming_them(db):
    admin, project = await _world(db)
    epic = await _item(db, admin, project, title="container", kind=ItemKind.EPIC)
    await _item(db, admin, project, title="child", parent_id=epic.id)
    with pytest.raises(ConflictError) as err:
        await items_service.convert_item_kind(db, epic.id, admin, kind=ItemKind.ISSUE)
    assert "1 child issue" in str(err.value)


async def test_issue_with_subtasks_cannot_become_epic_or_subtask(db):
    admin, project = await _world(db)
    issue = await _item(db, admin, project, title="has steps")
    await _item(db, admin, project, title="step", kind=ItemKind.SUBTASK, parent_id=issue.id)
    with pytest.raises(ConflictError) as err:
        await items_service.convert_item_kind(db, issue.id, admin, kind=ItemKind.EPIC)
    assert "1 subtask" in str(err.value)
    other = await _item(db, admin, project, title="target parent")
    with pytest.raises(ConflictError):
        await items_service.convert_item_kind(
            db, issue.id, admin, kind=ItemKind.SUBTASK, parent_id=other.id
        )


async def test_subtask_to_issue_detaches_its_incompatible_parent(db):
    admin, project = await _world(db)
    issue = await _item(db, admin, project, title="parent")
    sub = await _item(db, admin, project, title="step", kind=ItemKind.SUBTASK, parent_id=issue.id)
    promoted = await items_service.convert_item_kind(db, sub.id, admin, kind=ItemKind.ISSUE)
    assert promoted.kind == ItemKind.ISSUE
    assert promoted.parent is None  # an issue can't stay under an issue — recorded detach


async def test_issue_to_subtask_requires_a_parent_issue(db):
    admin, project = await _world(db)
    lone = await _item(db, admin, project, title="lone")
    with pytest.raises(ConflictError):
        await items_service.convert_item_kind(db, lone.id, admin, kind=ItemKind.SUBTASK)
    parent = await _item(db, admin, project, title="host")
    sub = await items_service.convert_item_kind(
        db, lone.id, admin, kind=ItemKind.SUBTASK, parent_id=parent.id
    )
    assert sub.kind == ItemKind.SUBTASK
    assert sub.parent is not None and sub.parent.id == parent.id


async def test_explicit_null_parent_on_subtask_refuses(db):
    """A subtask needs a parent — passing null must refuse, not create an orphan."""
    admin, project = await _world(db)
    epic = await _item(db, admin, project, title="epic", kind=ItemKind.EPIC)
    issue = await _item(db, admin, project, title="in epic", parent_id=epic.id)
    with pytest.raises(ConflictError):
        await items_service.convert_item_kind(
            db, issue.id, admin, kind=ItemKind.SUBTASK, parent_id=None
        )


async def test_noop_conversion_is_a_conflict(db):
    admin, project = await _world(db)
    issue = await _item(db, admin, project, title="same")
    with pytest.raises(ConflictError):
        await items_service.convert_item_kind(db, issue.id, admin, kind=ItemKind.ISSUE)
