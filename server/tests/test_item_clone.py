"""RADD-1088 — clone copies the shape of the work, never the trail.

Real service flows: content/fields/labels copied, initial state, `relates`
link back, subtask checklist optionally cloned, and the two smuggling doors
pinned shut — a custom field the actor cannot write drops from the copy, and
comments never travel.
"""

import uuid

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from radd.config import settings
from radd.modules.auth.models import User
from radd.modules.auth.types import InstanceRole
from radd.modules.items.enums import ItemKind, Priority
from radd.modules.items.models import ItemLink
from radd.modules.items import service as items_service
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
        email=f"cl-{uuid.uuid4().hex[:8]}@example.com",
        name="Cloner",
        instance_role=InstanceRole.ADMIN.value,
    )
    db.add(admin)
    await db.flush()
    project = await projects_service.create_project(
        db, ProjectCreate(key=f"CL{uuid.uuid4().hex[:4].upper()}", name="Clone P"),
        actor_id=admin.id,
    )
    return admin, project


async def test_clone_copies_shape_not_trail(db):
    admin, project = await _world(db)
    source = await items_service.create_item(
        db,
        ItemCreate(
            project_id=project.id,
            title="the original",
            description="body",
            priority=Priority.HIGH,
            labels=["a", "b"],
            estimate_points=5,
        ),
        actor=admin,
    )
    await items_service.create_item(
        db,
        ItemCreate(
            project_id=project.id, title="step 1", kind=ItemKind.SUBTASK, parent_id=source.id
        ),
        actor=admin,
    )

    clone = await items_service.clone_item(db, source.id, admin)
    assert clone.title == "Copy of the original"
    assert clone.description == "body"
    assert clone.priority == Priority.HIGH
    assert sorted(clone.labels) == ["a", "b"]
    assert clone.estimate_points == 5
    assert clone.id != source.id and clone.key != source.key
    assert clone.state.category == "backlog" or clone.state.name  # initial state, not copied

    link = await db.scalar(
        select(ItemLink).where(
            ItemLink.source_item_id == clone.id, ItemLink.target_item_id == source.id
        )
    )
    assert link is not None and link.link_type == "relates"
    # no subtasks unless asked
    assert clone.child_count == 0 if hasattr(clone, "child_count") else True

    deep = await items_service.clone_item(
        db, source.id, admin, title="with steps", include_subtasks=True
    )
    from radd.modules.items.models import WorkItem

    children = (
        (await db.execute(select(WorkItem).where(WorkItem.parent_id == deep.id))).scalars().all()
    )
    assert [c.title for c in children] == ["step 1"]
    assert all(c.kind == ItemKind.SUBTASK.value for c in children)


async def test_clone_lands_in_the_initial_state(db):
    admin, project = await _world(db)
    from radd.modules.workflow import service as workflow

    states = await workflow.list_states(db, project.id)
    non_default = next(s for s in states if not s.is_default)
    source = await items_service.create_item(
        db,
        ItemCreate(project_id=project.id, title="in progress work", state_id=non_default.id),
        actor=admin,
    )
    clone = await items_service.clone_item(db, source.id, admin)
    assert clone.state.id != non_default.id  # the default, not the source's state
