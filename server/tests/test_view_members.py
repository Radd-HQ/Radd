"""Curated view membership (roadmap wave): the `view_members` pin table, its
idempotent add/remove service seam with spec-57 edit gating, and the `roadmap`
item-SLQ field the views module contributes through the plugin registry.

Like the other relational-field tests, the compiled subquery has to be
EXECUTED — a wrong predicate returns a plausible-looking set, not an error.
DB-backed; flushed, never committed — the session rolls back at teardown.
"""

import uuid

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from radd.config import settings
from radd.exceptions import NotFoundError
from radd.modules.auth.models import User
from radd.modules.auth.types import InstanceRole
from radd.modules.items import service as items_service
from radd.modules.items.models import WorkItem
from radd.modules.items.schemas import ItemCreate
from radd.modules.items.slq import compile_query, parse
from radd.modules.projects import service as projects_service
from radd.modules.projects.schemas import ProjectCreate
from radd.modules.views import service as views_service
from radd.modules.views.models import ViewMember
from radd.modules.views.schemas import ViewCreate
from radd.modules.views.types import ViewType


@pytest.fixture
async def db():
    engine = create_async_engine(settings.database_url)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as session:
        yield session
        await session.rollback()
    await engine.dispose()


async def _user(db, name: str, role: InstanceRole = InstanceRole.ADMIN) -> User:
    user = User(
        email=f"vm-{uuid.uuid4().hex[:8]}@example.com",
        name=name,
        instance_role=role.value,
    )
    db.add(user)
    await db.flush()
    return user


async def _run(db, query: str, actor: User) -> set[uuid.UUID]:
    """Compile the SLQ and execute it, returning the matching item ids."""
    compiled = await compile_query(
        db,
        parse(query),
        definitions_by_key={},
        current_user_id=actor.id,
    )
    stmt = select(WorkItem.id)
    if compiled.where is not None:
        stmt = stmt.where(compiled.where)
    return set((await db.execute(stmt)).scalars().all())


async def _roadmap_with_items(db, actor):
    project = await projects_service.create_project(
        db, ProjectCreate(key=f"VM{uuid.uuid4().hex[:4].upper()}", name="Curated")
    )
    view = await views_service.create_view(
        db,
        ViewCreate(
            project_id=project.id,
            name=f"Curated Roadmap {uuid.uuid4().hex[:6]}",
            view_type=ViewType.ROADMAP,
        ),
        actor=actor,
    )
    pinned = await items_service.create_item(
        db, ItemCreate(project_id=project.id, title="Pinned"), actor
    )
    loose = await items_service.create_item(
        db, ItemCreate(project_id=project.id, title="Loose"), actor
    )
    return view, pinned, loose


async def test_membership_roundtrip_and_slq_field(db):
    actor = await _user(db, "Owner")
    view, pinned, loose = await _roadmap_with_items(db, actor)

    await views_service.add_member(db, view.id, pinned.id, actor=actor)
    # Idempotent: a second pin is a no-op, not a conflict.
    await views_service.add_member(db, view.id, pinned.id, actor=actor)
    rows = (
        await db.execute(select(ViewMember).where(ViewMember.view_id == view.id))
    ).scalars().all()
    assert [row.item_id for row in rows] == [pinned.id]
    assert rows[0].added_by == actor.id

    # The registry-contributed field, all three value forms. Exact membership:
    # the loose item never matches.
    by_id = await _run(db, f'roadmap = "{view.id}"', actor)
    assert pinned.id in by_id and loose.id not in by_id
    by_name = await _run(db, f'roadmap = "{view.name}"', actor)
    assert pinned.id in by_name and loose.id not in by_name
    by_contains = await _run(db, f'roadmap ~ "{view.name[:20]}"', actor)
    assert pinned.id in by_contains
    negated = await _run(db, f'roadmap != "{view.id}"', actor)
    assert pinned.id not in negated and loose.id in negated

    await views_service.remove_member(db, view.id, pinned.id, actor=actor)
    await views_service.remove_member(db, view.id, pinned.id, actor=actor)  # idempotent
    assert await _run(db, f'roadmap = "{view.id}"', actor) == set()


async def test_add_member_gates_and_validates(db):
    actor = await _user(db, "Owner")
    view, pinned, _ = await _roadmap_with_items(db, actor)

    # Spec 57 privacy: a stranger can't SEE the un-shared view — 404, not 403.
    stranger = await _user(db, "Stranger", role=InstanceRole.MEMBER)
    with pytest.raises(NotFoundError):
        await views_service.add_member(db, view.id, pinned.id, actor=stranger)

    # The pinned item must exist.
    with pytest.raises(NotFoundError):
        await views_service.add_member(db, view.id, uuid.uuid4(), actor=actor)
