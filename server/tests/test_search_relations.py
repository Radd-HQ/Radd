"""search_index carries relation columns (RADD-841).

The prerequisite for relations reaching search (RADD-823/817): a
relation-scoped actor must be able to filter FTS results by reporter/
assignee/team without joining work_items per query. Three facts are pinned:
the indexer writes the columns from the event payload, an item.updated
re-index follows a change, and the bulk sweep repairs a repoint that never
emitted an item event (the user-merge shape).

Rolled-back transactions on the compose DB.
"""

import uuid
from types import SimpleNamespace

import pytest
from sqlalchemy import update
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from radd.config import settings as config
from radd.modules.auth import roles as auth_roles
from radd.modules.auth.models import User

# Side effect: the workflow module's project.created hook seeds default states.
from radd.modules import workflow as _workflow  # noqa: F401
from radd.modules.items import service as items
from radd.modules.items.models import WorkItem
from radd.modules.items.schemas import ItemCreate
from radd.modules.projects import service as projects_service
from radd.modules.projects.schemas import ProjectCreate
from radd.modules.search import indexer
from radd.modules.search.models import SearchIndexRow
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


@pytest.fixture
async def admin(db) -> User:
    user = User(
        email=f"sr-{uuid.uuid4().hex[:8]}@example.com", name="SR Admin", instance_role="admin"
    )
    db.add(user)
    await db.flush()
    await auth_roles.ensure_builtin_roles(db)
    return user


def _event(item, project, *, reporter=None, assignee=None, team=None):
    """The real payload shape: a full ItemRead dump carries NESTED refs."""
    return SimpleNamespace(
        entity_id=str(item.id),
        payload={
            "project_id": str(project.id),
            "key": item.key,
            "title": item.title,
            "description": "",
            "reporter": {"id": str(reporter)} if reporter else None,
            "assignee": {"id": str(assignee)} if assignee else None,
            "team": {"id": str(team)} if team else None,
        },
    )


async def test_index_writes_and_follows_the_relation_columns(db, admin):
    project = await projects_service.create_project(
        db, ProjectCreate(key=f"SR{uuid.uuid4().hex[:4].upper()}", name="S")
    )
    team = await teams_service.create_team(db, TeamCreate(name=f"SR {uuid.uuid4().hex[:6]}"))
    item = await items.create_item(
        db, ItemCreate(project_id=project.id, title="anchored"), admin
    )

    await indexer._index_item(
        db, _event(item, project, reporter=admin.id, assignee=admin.id, team=team.id)
    )
    row = await db.get(SearchIndexRow, item.id)
    assert row is not None
    assert row.reporter_id == admin.id
    assert row.assignee_id == admin.id
    assert row.team_id == team.id

    # An item.updated after unassign/re-route re-indexes the mirror.
    await indexer._index_item(db, _event(item, project, reporter=admin.id))
    await db.refresh(row)
    assert row.reporter_id == admin.id
    assert row.assignee_id is None
    assert row.team_id is None


async def test_partial_payload_never_nulls_a_good_mirror(db, admin):
    """A payload that does not SPEAK about a relation must not erase it — the
    RADD-840 oracle tests' minimal payloads are exactly this shape."""
    project = await projects_service.create_project(
        db, ProjectCreate(key=f"SP{uuid.uuid4().hex[:4].upper()}", name="S")
    )
    item = await items.create_item(
        db, ItemCreate(project_id=project.id, title="kept"), admin
    )
    await indexer._index_item(db, _event(item, project, reporter=admin.id))
    bare = SimpleNamespace(
        entity_id=str(item.id),
        payload={
            "project_id": str(project.id),
            "key": item.key,
            "title": item.title,
            "description": "",
        },
    )
    await indexer._index_item(db, bare)
    row = await db.get(SearchIndexRow, item.id)
    assert row is not None and row.reporter_id == admin.id


async def test_sweep_repairs_a_repoint_that_emitted_no_item_event(db, admin):
    """The user-merge shape: work_items.assignee_id rewritten in bulk SQL with
    no item.updated — the sweep re-mirrors from the owning table."""
    project = await projects_service.create_project(
        db, ProjectCreate(key=f"SW{uuid.uuid4().hex[:4].upper()}", name="S")
    )
    successor = User(
        email=f"sr-{uuid.uuid4().hex[:8]}@example.com", name="Successor", instance_role="member"
    )
    db.add(successor)
    await db.flush()
    item = await items.create_item(
        db, ItemCreate(project_id=project.id, title="merged", assignee_id=admin.id), admin
    )
    await indexer._index_item(db, _event(item, project, reporter=admin.id, assignee=admin.id))

    await db.execute(
        update(WorkItem).where(WorkItem.id == item.id).values(assignee_id=successor.id)
    )
    await indexer.sync_relation_columns(db)
    row = await db.get(SearchIndexRow, item.id)
    assert row is not None and row.assignee_id == successor.id
    assert row.reporter_id == admin.id
