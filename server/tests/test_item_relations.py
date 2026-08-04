"""Items enforce relations (RADD-817): item.read@own / @team / item.update@own.

The Done-when scenario, executed: a role granting `item.read@own` scoped to
one project produces an account that sees exactly its own reported issues —
in the list, in the count, on a single read, through the child-surface seam,
and in search — and a write qualified `@own` refuses someone else's row.

The Baseline is EMPTIED per test (the RADD-773 pattern): it seeds `item.read`
unqualified, which is `@any` and would swamp every relation under test.

Rolled-back transactions on the compose DB.
"""

import uuid

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from radd.config import settings as config
from radd.exceptions import ForbiddenError, NotFoundError
from radd.modules.auth import authz, roles as auth_roles
from radd.modules.auth.models import ProjectMember, User
from radd.modules.auth.schemas import RoleCreate
from radd.modules.auth.types import BuiltinRoleKey

# Side effect: workflow's project.created hook seeds default states.
from radd.modules import workflow as _workflow  # noqa: F401
from radd.modules.items import bulk, service as items
from radd.modules.items.filters import ItemListFilters
from radd.modules.items.schemas import ItemCreate, ItemUpdate
from radd.modules.projects import service as projects_service
from radd.modules.projects.schemas import ProjectCreate
from radd.modules.search import indexer, service as search_service
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


async def _user(db, name, role="member") -> User:
    user = User(
        email=f"ir-{uuid.uuid4().hex[:8]}@example.com", name=name, instance_role=role
    )
    db.add(user)
    await db.flush()
    return user


async def _empty_baseline(db):
    await auth_roles.ensure_builtin_roles(db)
    baseline = await auth_roles.role_by_key(db, BuiltinRoleKey.BASELINE)
    baseline.permissions = []
    await db.flush()
    authz.forget_baseline(db)


async def _grant(db, user, project, atoms):
    role = await auth_roles.create_role(
        db, RoleCreate(key=f"ir{uuid.uuid4().hex[:6]}", name="R", permissions=atoms)
    )
    db.add(ProjectMember(project_id=project.id, user_id=user.id, role_id=role.id))
    await db.flush()


@pytest.fixture
async def scenario(db):
    """One project; admin seeds three issues: the restricted user's own, their
    team's, and a stranger's. Returns (project, restricted, admin, ids)."""
    admin = await _user(db, "IR Admin", role="admin")
    restricted = await _user(db, "Restricted")
    await _empty_baseline(db)
    project = await projects_service.create_project(
        db, ProjectCreate(key=f"IR{uuid.uuid4().hex[:4].upper()}", name="R")
    )
    team = await teams_service.create_team(db, TeamCreate(name=f"IR {uuid.uuid4().hex[:6]}"))
    await teams_service.add_team_member(db, team.id, restricted.id)
    own = await items.create_item(
        db,
        ItemCreate(project_id=project.id, title="mine alone", reporter_id=restricted.id),
        admin,
    )
    teams_item = await items.create_item(
        db, ItemCreate(project_id=project.id, title="the team queue", team_id=team.id), admin
    )
    other = await items.create_item(
        db, ItemCreate(project_id=project.id, title="somebody else entirely"), admin
    )
    return project, restricted, admin, {"own": own, "team": teams_item, "other": other}


async def _list_ids(db, actor, project):
    reads = await items.list_items(
        db,
        actor=actor,
        filters=ItemListFilters(project_id=project.id),
        limit=50,
        offset=0,
    )
    return {r.id for r in reads}


async def test_read_own_narrows_every_shared_surface(db, scenario):
    project, restricted, _admin, fixture = scenario
    await _grant(db, restricted, project, ["item.read@own"])

    # The list.
    assert await _list_ids(db, restricted, project) == {fixture["own"].id}
    # The count/ids builder (boards, bulk, MCP).
    ids = await bulk.list_item_ids(
        db, actor=restricted, filters=ItemListFilters(project_id=project.id), q=None
    )
    assert set(ids.ids) == {fixture["own"].id} and ids.total == 1
    # The single read: someone else's item 404s — existence stays private.
    read = await items.get_item(db, fixture["own"].id, restricted)
    assert read.title == "mine alone"
    with pytest.raises(NotFoundError):
        await items.get_item(db, fixture["other"].id, restricted)
    # The child-surface seam (comments/worklogs/history all resolve through it).
    with pytest.raises(NotFoundError):
        await items.require_readable_item(db, fixture["team"].id, restricted)


async def test_read_team_covers_own_by_the_chain(db, scenario):
    project, restricted, _admin, fixture = scenario
    await _grant(db, restricted, project, ["item.read@team"])
    # @team ⊃ @own (normative): the team's queue AND my own report — not the stranger's.
    assert await _list_ids(db, restricted, project) == {
        fixture["own"].id,
        fixture["team"].id,
    }


async def test_update_own_refuses_someone_elses_row(db, scenario):
    project, restricted, _admin, fixture = scenario
    await _grant(db, restricted, project, ["item.read", "item.update@own"])
    updated = await items.update_item(
        db, fixture["own"].id, ItemUpdate(title="mine, renamed"), restricted
    )
    assert updated.title == "mine, renamed"
    with pytest.raises(ForbiddenError):
        await items.update_item(
            db, fixture["other"].id, ItemUpdate(title="hijacked"), restricted
        )


async def test_search_inherits_the_relation_filter(db, scenario):
    """The RADD-841 mirror pays off: FTS answers only the rows the list would."""
    project, restricted, admin, fixture = scenario
    await _grant(db, restricted, project, ["item.read@own"])
    for name, item in fixture.items():
        await indexer._index_item(
            db,
            type(
                "E",
                (),
                {
                    "entity_id": str(item.id),
                    "payload": {
                        "project_id": str(project.id),
                        "key": item.key,
                        "title": item.title,
                        "description": "",
                        "reporter": {"id": str(item.reporter.id)} if item.reporter else None,
                        "assignee": None,
                        "team": {"id": str(item.team.id)} if item.team else None,
                    },
                },
            )(),
        )
    hits = await search_service.search(db, restricted, q="mine alone")
    assert {h.item_id for h in hits} == {fixture["own"].id}
    # The admin (@any) still sees everything.
    admin_hits = await search_service.search(db, admin, q="somebody else")
    assert fixture["other"].id in {h.item_id for h in admin_hits}


async def test_notify_delivery_gates_the_relation_per_recipient(db, scenario):
    project, restricted, _admin, fixture = scenario
    await _grant(db, restricted, project, ["item.read@own"])
    from radd.modules.items.models import WorkItem
    from radd.modules.notify.consumer import _allowed
    from radd.modules.notify.planner import PlannedNotification
    from radd.modules.notify.types import NotificationType

    own_row = await db.get(WorkItem, fixture["own"].id)
    other_row = await db.get(WorkItem, fixture["other"].id)
    planned = PlannedNotification(
        user_id=restricted.id, type=NotificationType.STATE_CHANGED, detail={}
    )
    assert await _allowed(db, planned, project, own_row)
    assert not await _allowed(db, planned, project, other_row)
