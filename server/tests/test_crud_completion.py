"""The delete/update paths spec 87 built for atoms that had no endpoint.

Only the guards are worth a test — they are the part that can silently destroy
data if they regress: a state delete must never relocate someone's work or strip
a project of its default landing state, and a label rename must not collide.
Rolled-back transactions on the compose DB.
"""

import uuid

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from radd.config import settings
from radd.exceptions import ConflictError, NotFoundError
from radd.modules.auth.models import User
from radd.modules.auth.types import InstanceRole
from radd.modules.items import service as items
from radd.modules.items.schemas import ItemCreate, ItemUpdate
from radd.modules.labels import service as labels
from radd.modules.labels.schemas import LabelCreate, LabelUpdate
from radd.modules.projects import service as projects_service
from radd.modules.projects.schemas import ProjectCreate
from radd.modules.workflow import service as workflow
from radd.modules.workflow.schemas import StateCreate
from radd.modules.workflow.types import StateCategory


@pytest.fixture
async def db():
    engine = create_async_engine(settings.database_url)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as session:
        yield session
        await session.rollback()
    await engine.dispose()


async def _actor(db) -> User:
    user = User(
        email=f"cc-{uuid.uuid4().hex[:8]}@example.com",
        name="Actor",
        instance_role=InstanceRole.ADMIN.value,
    )
    db.add(user)
    await db.flush()
    return user


async def test_state_delete_refuses_default_and_occupied_states(db):
    actor = await _actor(db)
    project = await projects_service.create_project(
        db, ProjectCreate(key=f"CC{uuid.uuid4().hex[:4].upper()}", name="P")
    )
    states = {s.name: s for s in await workflow.list_states(db, project.id)}

    # The default state is where every new item lands — deleting it is refused.
    assert states["Triage"].is_default
    with pytest.raises(ConflictError):
        await workflow.delete_state(db, states["Triage"].id, actor_id=actor.id)

    # A state holding work is refused too: deleting must never silently move items.
    spare = await workflow.create_state(
        db,
        StateCreate(project_id=project.id, name="Spare", category=StateCategory.IN_PROGRESS),
        actor_id=actor.id,
    )
    item = await items.create_item(db, ItemCreate(project_id=project.id, title="i"), actor)
    await items.update_item(db, item.id, ItemUpdate(state_id=spare.id), actor)
    with pytest.raises(ConflictError):
        await workflow.delete_state(db, spare.id, actor_id=actor.id)

    # Emptied, it goes.
    await items.update_item(db, item.id, ItemUpdate(state_id=states["Done"].id), actor)
    await workflow.delete_state(db, spare.id, actor_id=actor.id)
    with pytest.raises(NotFoundError):
        await workflow.get_state(db, spare.id)


async def test_label_rename_collision_and_delete(db):
    actor = await _actor(db)
    suffix = uuid.uuid4().hex[:6]
    first = await labels.create_label(db, LabelCreate(name=f"bug-{suffix}"), actor_id=actor.id)
    second = await labels.create_label(db, LabelCreate(name=f"chore-{suffix}"), actor_id=actor.id)

    with pytest.raises(ConflictError):
        await labels.update_label(db, second.id, LabelUpdate(name=first.name), actor_id=actor.id)

    renamed = await labels.update_label(
        db, second.id, LabelUpdate(name=f"task-{suffix}", color="#ff0000"), actor_id=actor.id
    )
    assert renamed.name == f"task-{suffix}" and renamed.color == "#ff0000"

    await labels.delete_label(db, second.id, actor_id=actor.id)
    with pytest.raises(NotFoundError):
        await labels.get_label(db, second.id)
