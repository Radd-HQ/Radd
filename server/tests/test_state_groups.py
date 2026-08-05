"""State groups (RADD-852) — the presentation tier over states.

Hussein's design call: arbitrary vocabulary with NO semantics — the state
keeps its fixed category, so nothing that reports/sweeps/guards reads can be
affected by a group. Pinned here: CRUD + the unique name, membership set and
cleared through StateUpdate's tri-state group_id, delete degrading members to
ungrouped (never blocking), and the view axis accepting the token.

Rolled-back transactions on the compose DB.
"""

import uuid

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from radd.config import settings as config
from radd.exceptions import ConflictError, NotFoundError
from radd.modules import workflow as _workflow  # noqa: F401  (project.created hook)
from radd.modules.projects import service as projects_service
from radd.modules.projects.schemas import ProjectCreate
from radd.modules.workflow import service as workflow
from radd.modules.workflow.schemas import StateCreate, StateGroupCreate, StateGroupUpdate, StateUpdate


@pytest.fixture
async def db():
    engine = create_async_engine(config.database_url)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as session:
        yield session
        await session.rollback()
    await engine.dispose()


async def test_group_crud_and_unique_name(db):
    run = uuid.uuid4().hex[:6]
    a = await workflow.create_state_group(db, StateGroupCreate(name=f"Blocked {run}"))
    b = await workflow.create_state_group(db, StateGroupCreate(name=f"Review {run}", color="#ff8800"))
    assert b.position == a.position + 1  # append semantics
    with pytest.raises(ConflictError):
        await workflow.create_state_group(db, StateGroupCreate(name=f"Blocked {run}"))
    renamed = await workflow.update_state_group(db, b.id, StateGroupUpdate(name=f"In review {run}"))
    assert renamed.name == f"In review {run}"
    with pytest.raises(ConflictError):
        await workflow.update_state_group(db, b.id, StateGroupUpdate(name=f"Blocked {run}"))
    cleared = await workflow.update_state_group(db, b.id, StateGroupUpdate(color=None))
    assert cleared.color is None


async def test_membership_and_delete_degrades(db):
    run = uuid.uuid4().hex[:4].upper()
    project = await projects_service.create_project(
        db, ProjectCreate(key=f"SG{run}", name="Groups")
    )
    states = await workflow.list_states(db, project.id)
    group = await workflow.create_state_group(
        db, StateGroupCreate(name=f"Active {run}")
    )
    # join through the tri-state group_id
    joined = await workflow.update_state(db, states[0].id, StateUpdate(group_id=group.id))
    assert joined.group_id == group.id
    # absent group_id leaves membership untouched
    renamed = await workflow.update_state(db, states[0].id, StateUpdate(name=f"WIP {run}"))
    assert renamed.group_id == group.id
    # explicit null LEAVES the group
    left = await workflow.update_state(db, states[0].id, StateUpdate(group_id=None))
    assert left.group_id is None
    # a stale picker 404s instead of writing a dangle
    with pytest.raises(NotFoundError):
        await workflow.update_state(db, states[0].id, StateUpdate(group_id=uuid.uuid4()))
    # delete degrades members to ungrouped, never blocks
    await workflow.update_state(db, states[1].id, StateUpdate(group_id=group.id))
    await workflow.delete_state_group(db, group.id)
    await db.flush()
    refreshed = await workflow.get_state(db, states[1].id)
    await db.refresh(refreshed)
    assert refreshed.group_id is None


def test_view_axis_accepts_the_token():
    from pydantic import ValidationError

    from radd.modules.views.schemas import ViewCreate
    from radd.modules.views.types import ViewType

    view = ViewCreate(name="g", view_type=ViewType.BOARD, group_by="state_group")
    assert view.group_by == "state_group"
    with pytest.raises(ValidationError):
        ViewCreate(name="g", view_type=ViewType.BOARD, group_by="state_flavour")


async def test_category_change_and_delete_with_successor(db):
    """RADD-853: the category is editable in place, and deletion takes a
    successor that inherits the state's items with per-item history."""
    import uuid as _uuid

    from radd.modules.auth.models import User
    from radd.modules.items import service as items_service
    from radd.modules.items.schemas import ItemCreate
    from radd.modules.workflow.types import StateCategory

    run = _uuid.uuid4().hex[:4].upper()
    admin = User(
        email=f"sd-{_uuid.uuid4().hex[:8]}@example.com", name="SD", instance_role="admin"
    )
    db.add(admin)
    await db.flush()
    project = await projects_service.create_project(
        db, ProjectCreate(key=f"SD{run}", name="Del")
    )
    doomed = await workflow.create_state(
        db, StateCreate(project_id=project.id, name=f"Doomed {run}", category=StateCategory.TODO)
    )
    # category editable in place
    changed = await workflow.update_state(
        db, doomed.id, StateUpdate(category=StateCategory.IN_PROGRESS)
    )
    assert changed.category == StateCategory.IN_PROGRESS.value

    item = await items_service.create_item(
        db, ItemCreate(project_id=project.id, title="survivor"), admin
    )
    moved = await items_service.update_item(
        db, item.id, __import__("radd.modules.items.schemas", fromlist=["ItemUpdate"]).ItemUpdate(state_id=doomed.id), admin
    )
    assert moved.state.id == doomed.id

    states = await workflow.list_states(db, project.id)
    successor = next(s for s in states if s.is_default)
    # in-use without a successor still refuses
    with pytest.raises(ConflictError):
        await workflow.delete_state(db, doomed.id, actor_id=admin.id)
    # self and cross-project successors refuse
    with pytest.raises(ConflictError):
        await workflow.delete_state(
            db, doomed.id, actor_id=admin.id, reassign_to=doomed.id, actor=admin
        )
    other_project = await projects_service.create_project(
        db, ProjectCreate(key=f"SE{run}", name="Other")
    )
    foreign = (await workflow.list_states(db, other_project.id))[0]
    with pytest.raises(ConflictError):
        await workflow.delete_state(
            db, doomed.id, actor_id=admin.id, reassign_to=foreign.id, actor=admin
        )
    # with a legal successor: items move, the state deletes
    await workflow.delete_state(
        db, doomed.id, actor_id=admin.id, reassign_to=successor.id, actor=admin
    )
    landed = await items_service.get_item(db, item.id, admin)
    assert landed.state.id == successor.id
    with pytest.raises(NotFoundError):
        await workflow.get_state(db, doomed.id)
