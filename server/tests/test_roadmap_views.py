"""Roadmap as a view type (spec 79): `ViewType.ROADMAP` is an ordinary saved
view — accepted on create/patch with axes stored-but-ignored (the
planning/queue precedent), seeded on project.created after Planning, and the
seed function is idempotent (the backfill migration reuses its predicate).
Rolled-back transactions on the compose DB."""

import uuid

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from radd.config import settings
from radd.modules.auth.models import User
from radd.modules.auth.types import InstanceRole
from radd.modules.views import defaults as views_defaults, service as views_service
from radd.modules.views.models import View
from radd.modules.views.schemas import ViewCreate, ViewUpdate
from radd.modules.views.types import ShareLevel, ViewType
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


async def _member(db, name) -> User:
    """An active user holds the global member floor (spec 86)."""
    user = User(
        email=f"rv-{uuid.uuid4().hex[:8]}@example.com",
        name=name,
        instance_role=InstanceRole.MEMBER.value,
    )
    db.add(user)
    await db.flush()
    return user


async def test_roadmap_view_type_accepted_on_create_and_patch(db):
    run = uuid.uuid4().hex[:8]
    member = await _member(db, "Planner")
    project = await projects_service.create_project(
        db, ProjectCreate(key=f"RV{run[:4].upper()}", name="Roadmaps")
    )

    # Create: project-scoped, with an axis + SLQ — axes stored but unused.
    created = await views_service.create_view(
        db,
        ViewCreate(
            project_id=project.id,
            name="Release roadmap",
            view_type=ViewType.ROADMAP,
            query="kind = epic",
            group_by="state",
        ),
        actor=member,
    )
    assert created.view_type == ViewType.ROADMAP  # ViewRead.view_type is now a str
    assert created.group_by == "state"  # stored-but-ignored, like planning/queue

    # All-projects roadmap (project_id NULL) is just as valid.
    spanning = await views_service.create_view(
        db,
        ViewCreate(name="Everything", view_type=ViewType.ROADMAP),
        actor=member,
    )
    assert spanning.project_id is None and spanning.view_type == ViewType.ROADMAP

    # Patch: an existing view can be retyped to (and from) roadmap.
    board = await views_service.create_view(
        db,
        ViewCreate(name="Was a board", view_type=ViewType.BOARD),
        actor=member,
    )
    retyped = await views_service.update_view(
        db, board.id, ViewUpdate(view_type=ViewType.ROADMAP), actor=member
    )
    assert retyped.view_type == ViewType.ROADMAP


async def test_project_seeds_roadmap_view_idempotently(db):
    run = uuid.uuid4().hex[:8]
    member = await _member(db, "Reader")
    project = await projects_service.create_project(
        db, ProjectCreate(key=f"RS{run[:4].upper()}", name="Seeded")
    )

    seeded = await views_service.list_views(db, actor=member, project_id=project.id)
    assert {(v.name, v.view_type) for v in seeded} == {
        ("Board", ViewType.BOARD),
        ("List", ViewType.LIST),
        ("Planning", ViewType.PLANNING),
        ("Roadmap", ViewType.ROADMAP),
    }
    roadmap = next(v for v in seeded if v.view_type == ViewType.ROADMAP)
    # Same shape as the other seeds: globally visible, owner NULL, empty query.
    assert roadmap.global_access is ShareLevel.VIEWER
    assert roadmap.owner_id is None and roadmap.query == "" and roadmap.group_by is None

    # Re-running the seed (the backfill predicate) never duplicates.
    await views_defaults.seed_project_views(db, project)
    count = await db.scalar(
        select(func.count())
        .select_from(View)
        .where(View.project_id == project.id, View.view_type == ViewType.ROADMAP.value)
    )
    assert count == 1
