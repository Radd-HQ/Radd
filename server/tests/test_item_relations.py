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
from radd.modules.auth.models import GlobalRoleGrant, User
from radd.modules.auth.schemas import RoleCreate
from radd.modules.auth.types import BuiltinRoleKey

# Side effect: workflow's project.created hook seeds default states.
from radd.modules import workflow as _workflow  # noqa: F401
from radd.modules.items import bulk, service as items
from radd.modules.items.filters import ItemListFilters
from radd.modules.items.enums import ItemKind
from radd.modules.items.schemas import ItemCreate, ItemLinkCreate, ItemUpdate
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
    db.add(GlobalRoleGrant(project_id=project.id, user_id=user.id, role_id=role.id))
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
                        # Nested under `item` (RADD-922) — one shape for every
                        # item-scoped event.
                        "item": {
                            "id": str(item.id),
                            "project": {
                                "id": str(project.id),
                                "key": project.key,
                                "name": project.name,
                            },
                            "key": item.key,
                            "title": item.title,
                            "description": "",
                            "reporter": (
                                {"id": str(item.reporter.id)} if item.reporter else None
                            ),
                            "assignee": None,
                            "team": {"id": str(item.team.id)} if item.team else None,
                        }
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


async def test_reads_carry_the_per_row_verdict(db, scenario):
    """RADD-842: writability is per-ROW under relations, and the reads say so
    up front — the spec-96 rule (disable, never edit-then-error) needs a
    per-item answer the project-level seam cannot give."""
    project, restricted, _admin, fixture = scenario
    await _grant(db, restricted, project, ["item.read", "item.update@own", "comment.write"])
    reads = {
        r.id: r
        for r in await items.list_items(
            db,
            actor=restricted,
            filters=ItemListFilters(project_id=project.id),
            limit=50,
            offset=0,
        )
    }
    own, other = reads[fixture["own"].id], reads[fixture["other"].id]
    assert own.capabilities is not None and own.capabilities.can_update
    assert other.capabilities is not None and not other.capabilities.can_update
    assert other.capabilities.can_comment  # comment.write is unqualified here
    detail = await items.get_item(db, fixture["other"].id, restricted)
    assert detail.capabilities is not None and not detail.capabilities.can_update
    renamed = await items.update_item(db, own.id, ItemUpdate(title="updated own issue"), restricted)
    assert renamed.capabilities == (await items.get_item(db, own.id, restricted)).capabilities
    handed_over = await items.update_item(
        db, own.id, ItemUpdate(reporter_id=_admin.id), restricted
    )
    assert handed_over.capabilities is not None
    assert not handed_over.capabilities.can_update
    assert handed_over.capabilities == (await items.get_item(db, own.id, restricted)).capabilities


async def test_hydration_refs_pass_the_relation_filter(db, scenario):
    """RADD-835: a hidden ROW in a readable project must not surface through
    the payload's cross-item references — the link far-end, the parent
    breadcrumb, the child count. The project filter alone let all three
    through (found by relation-sweep-proof.mjs, pinned here)."""
    project, restricted, admin, fixture = scenario
    await _grant(db, restricted, project, ["item.read@own"])

    # A dependency from the OWN row to a hidden one.
    await items.add_item_link(
        db, fixture["own"].id, ItemLinkCreate(target_id=fixture["other"].id, link_type="blocks"), admin
    )
    # A hidden epic whose child the restricted user reported.
    epic = await items.create_item(
        db, ItemCreate(project_id=project.id, kind=ItemKind.EPIC, title="secret initiative"), admin
    )
    child = await items.create_item(
        db,
        ItemCreate(
            project_id=project.id,
            parent_id=epic.id,
            title="my visible child",
            reporter_id=restricted.id,
        ),
        admin,
    )
    hidden_child = await items.create_item(
        db,
        ItemCreate(project_id=project.id, kind=ItemKind.SUBTASK, parent_id=fixture["own"].id, title="hidden sibling"),
        admin,
    )

    own_read = await items.get_item(db, fixture["own"].id, restricted)
    linked = [link.item.id for link in own_read.links.outgoing + own_read.links.incoming]
    assert fixture["other"].id not in linked
    # The hidden child never reaches the count either — counts must match rows.
    assert own_read.child_count == 0

    child_read = await items.get_item(db, child.id, restricted)
    assert child_read.parent is None  # the hidden epic's title stays hidden

    # The ADMIN still sees all three — the filter is the actor's, not global.
    admin_read = await items.get_item(db, fixture["own"].id, admin)
    assert fixture["other"].id in [
        link.item.id for link in admin_read.links.outgoing + admin_read.links.incoming
    ]
    assert admin_read.child_count == 1
    assert (await items.get_item(db, child.id, admin)).parent is not None
    assert hidden_child.id is not None  # anchors the fixture; the count above is its proof
