"""State categories as user-owned vocabulary rows (RADD-854) + the RADD-853
state lifecycle (delete-with-successor, in-place re-categorisation).

The consolidation's contract: `states.category` (the semantic enum every
report/sweep/guard reads) is DERIVED from the vocabulary row's `behaves_as`
at assignment time — so vocabulary is fully the operator's while the 21
semantic call sites never learn the tier exists. Pinned here: the derivation,
the builtin guards, the behaves_as ripple, delete refusals, the successor
flow, and the view-axis token (state_group must now REJECT).

Rolled-back transactions on the compose DB.
"""

import uuid

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from radd.config import settings as config
from radd.exceptions import ConflictError, NotFoundError
from radd.modules import workflow as _workflow  # noqa: F401  (project.created hook)
from radd.modules.auth.models import User
from radd.modules.items import service as items_service
from radd.modules.items.schemas import ItemCreate, ItemUpdate
from radd.modules.projects import service as projects_service
from radd.modules.projects.schemas import ProjectCreate
from radd.modules.workflow import service as workflow
from radd.modules.workflow.schemas import (
    StateCategoryCreate,
    StateCategoryUpdate,
    StateCreate,
    StateUpdate,
)
from radd.modules.workflow.types import StateCategory


@pytest.fixture
async def db():
    engine = create_async_engine(config.database_url)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as session:
        yield session
        await session.rollback()
    await engine.dispose()


async def _admin(db) -> User:
    admin = User(
        email=f"sc-{uuid.uuid4().hex[:8]}@example.com", name="SC", instance_role="admin"
    )
    db.add(admin)
    await db.flush()
    return admin


async def test_custom_category_derives_the_semantic_column(db):
    """The headline: "In Review" behaving as in-progress — a state assigned to
    it reads as in_progress to every semantic consumer, immediately."""
    run = uuid.uuid4().hex[:4].upper()
    project = await projects_service.create_project(
        db, ProjectCreate(key=f"SC{run}", name="Cat")
    )
    review = await workflow.create_state_category(
        db, StateCategoryCreate(name=f"In Review {run}", behaves_as=StateCategory.IN_PROGRESS)
    )
    assert review.is_builtin is False and review.behaves_as == StateCategory.IN_PROGRESS.value
    state = await workflow.create_state(
        db, StateCreate(project_id=project.id, name=f"Review {run}", category=review.key)
    )
    assert state.category == StateCategory.IN_PROGRESS.value  # derived
    assert state.category_key == review.key
    # re-classify to a builtin row by its key — old enum-shaped payloads work
    moved = await workflow.update_state(db, state.id, StateUpdate(category="done"))
    assert moved.category == StateCategory.DONE.value
    assert moved.category_key == "done"


async def test_behaves_as_ripple_and_builtin_guards(db):
    run = uuid.uuid4().hex[:4].upper()
    project = await projects_service.create_project(
        db, ProjectCreate(key=f"SR{run}", name="Ripple")
    )
    blocked = await workflow.create_state_category(
        db, StateCategoryCreate(name=f"Blocked {run}", behaves_as=StateCategory.TODO)
    )
    state = await workflow.create_state(
        db, StateCreate(project_id=project.id, name=f"Stuck {run}", category=blocked.key)
    )
    assert state.category == StateCategory.TODO.value
    # the ripple: flipping the row's behaviour re-derives its states
    await workflow.update_state_category(
        db, blocked.id, StateCategoryUpdate(behaves_as=StateCategory.IN_PROGRESS)
    )
    refreshed = await workflow.get_state(db, state.id)
    await db.refresh(refreshed)
    assert refreshed.category == StateCategory.IN_PROGRESS.value
    # builtins: behaviour frozen, undeletable
    todo = await workflow.get_state_category(db, "todo")
    with pytest.raises(ConflictError):
        await workflow.update_state_category(
            db, todo.id, StateCategoryUpdate(behaves_as=StateCategory.DONE)
        )
    with pytest.raises(ConflictError):
        await workflow.delete_state_category(db, todo.id)
    # builtins: NAME is the operator's ("Todo" -> "Ready")
    renamed = await workflow.update_state_category(
        db, todo.id, StateCategoryUpdate(name=f"Ready {run}")
    )
    assert renamed.name == f"Ready {run}" and renamed.key == "todo"
    # custom rows: delete refused while states reference them
    with pytest.raises(ConflictError):
        await workflow.delete_state_category(db, blocked.id)
    await workflow.update_state(db, state.id, StateUpdate(category="todo"))
    await workflow.delete_state_category(db, blocked.id)
    with pytest.raises(NotFoundError):
        await workflow.get_state_category(db, blocked.key)


async def test_duplicate_names_and_unknown_keys_refuse(db):
    run = uuid.uuid4().hex[:6]
    await workflow.create_state_category(
        db, StateCategoryCreate(name=f"Waiting {run}", behaves_as=StateCategory.TODO)
    )
    with pytest.raises(ConflictError):
        await workflow.create_state_category(
            db, StateCategoryCreate(name=f"Waiting {run}", behaves_as=StateCategory.DONE)
        )
    project = await projects_service.create_project(
        db, ProjectCreate(key=f"SU{uuid.uuid4().hex[:4].upper()}", name="Unknown")
    )
    with pytest.raises(NotFoundError):
        await workflow.create_state(
            db, StateCreate(project_id=project.id, name="ghost", category="no_such_key")
        )


async def test_delete_state_with_successor(db):
    """RADD-853 under the new tier: deletion takes a successor that inherits
    the items, with the refusal ladder intact."""
    run = uuid.uuid4().hex[:4].upper()
    admin = await _admin(db)
    project = await projects_service.create_project(
        db, ProjectCreate(key=f"SD{run}", name="Del")
    )
    doomed = await workflow.create_state(
        db, StateCreate(project_id=project.id, name=f"Doomed {run}", category="todo")
    )
    item = await items_service.create_item(
        db, ItemCreate(project_id=project.id, title="survivor"), admin
    )
    await items_service.update_item(db, item.id, ItemUpdate(state_id=doomed.id), admin)
    states = await workflow.list_states(db, project.id)
    successor = next(s for s in states if s.is_default)
    with pytest.raises(ConflictError):
        await workflow.delete_state(db, doomed.id, actor_id=admin.id)
    with pytest.raises(ConflictError):
        await workflow.delete_state(
            db, doomed.id, actor_id=admin.id, reassign_to=doomed.id, actor=admin
        )
    await workflow.delete_state(
        db, doomed.id, actor_id=admin.id, reassign_to=successor.id, actor=admin
    )
    landed = await items_service.get_item(db, item.id, admin)
    assert landed.state.id == successor.id


def test_view_axis_tokens():
    from pydantic import ValidationError

    from radd.modules.views.schemas import ViewCreate
    from radd.modules.views.types import ViewType

    ok = ViewCreate(name="c", view_type=ViewType.BOARD, group_by="state_category")
    assert ok.group_by == "state_category"
    # the folded tier is GONE — its token must reject (no silent zombie axis)
    with pytest.raises(ValidationError):
        ViewCreate(name="g", view_type=ViewType.BOARD, group_by="state_group")
