"""RADD-839 — cross-project read leaks (spec-115 review §2, N1–N4).

An actor entitled to ONE project must not see another project's issue keys or
titles through the side doors: the timesheet, item-payload hydration
(links/parent/epic/child counts), SLQ autocomplete (item keys, project keys,
both dialects), or epic rollups. All query-level fixes; each assertion failed
on the pre-fix code.

The Baseline is emptied per test session (the seeded row grants item.read
globally, which would make every member read everything — the scoped-member
proof does the same).

DB-backed; flushed, never committed.
"""

import uuid
from datetime import date

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from radd.config import settings as config
from radd.modules.auth import roles as auth_roles
from radd.modules.auth.models import ProjectMember, User
from radd.modules.auth.types import BuiltinRoleKey, InstanceRole
from radd.modules.items import rollup, service as items
from radd.modules.items.schemas import ItemCreate, ItemLinkCreate
from radd.modules.items.enums import ItemKind
from radd.modules.items.slq.suggest import suggest
from radd.modules.timelogging import enablement, service as timelogging, timesheet
from radd.modules.timelogging.schemas import WorklogCreate
from radd.modules.timelogging.slq.suggest import suggest_worklog
from radd.modules.projects import service as projects_service
from radd.modules.projects.schemas import ProjectCreate


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
        email=f"leak-{uuid.uuid4().hex[:8]}@example.com",
        name="Admin",
        instance_role=InstanceRole.ADMIN.value,
    )
    db.add(user)
    await db.flush()
    return user


async def _empty_baseline(db):
    """The seeded Baseline grants item.read globally; empty it so membership is
    what a project grant says (the RADD-773 model these leaks matter under)."""
    await auth_roles.ensure_builtin_roles(db)
    baseline = await auth_roles.role_by_key(db, BuiltinRoleKey.BASELINE)
    baseline.permissions = []
    await db.flush()


@pytest.fixture
async def world(db, admin):
    """Two projects; `member` may read only A. B holds an epic whose child sits
    in A, an item linked from A, and a logged worklog."""
    await _empty_baseline(db)
    project_a = await projects_service.create_project(
        db, ProjectCreate(key=f"LA{uuid.uuid4().hex[:4].upper()}", name="Readable")
    )
    project_b = await projects_service.create_project(
        db, ProjectCreate(key=f"LB{uuid.uuid4().hex[:4].upper()}", name="Hidden")
    )
    member = User(
        email=f"leak-m-{uuid.uuid4().hex[:8]}@example.com",
        name="Member",
        instance_role=InstanceRole.MEMBER.value,
    )
    db.add(member)
    await db.flush()
    member_role = await auth_roles.role_by_key(db, BuiltinRoleKey.MEMBER)
    db.add(ProjectMember(project_id=project_a.id, user_id=member.id, role_id=member_role.id))
    await db.flush()

    epic_b = await items.create_item(
        db,
        ItemCreate(project_id=project_b.id, title="secret epic", kind=ItemKind.EPIC),
        admin,
    )
    item_b = await items.create_item(
        db, ItemCreate(project_id=project_b.id, title="secret issue"), admin
    )
    # A's item hangs under B's epic and links to B's issue (spec 80: the
    # hierarchy and links span projects).
    item_a = await items.create_item(
        db,
        ItemCreate(project_id=project_a.id, title="visible issue", parent_id=epic_b.id),
        admin,
    )
    await items.add_item_link(
        db, item_a.id, ItemLinkCreate(target_id=item_b.id, link_type="relates"), admin
    )
    # B's epic also has a B-child, so a rollup over it would count across projects.
    await items.create_item(
        db, ItemCreate(project_id=project_b.id, title="secret child", parent_id=epic_b.id), admin
    )
    return {
        "a": project_a,
        "b": project_b,
        "member": member,
        "item_a": item_a,
        "item_b": item_b,
        "epic_b": epic_b,
    }


# --- N1: the timesheet ----------------------------------------------------------


async def test_timesheet_filters_to_readable_projects(db, admin, world):
    today = date(2026, 8, 3)
    await enablement.set_enabled(db, world["a"].id, True)
    await enablement.set_enabled(db, world["b"].id, True)
    await timelogging.create_worklog(
        db, world["item_a"].id, WorklogCreate(time_spent="1h", worked_on=today), admin.id, today
    )
    await timelogging.create_worklog(
        db, world["item_b"].id, WorklogCreate(time_spent="2h", worked_on=today), admin.id, today
    )
    sheet = await timesheet.build(db, today, today, actor=world["member"])
    keys = {entry.item.key for entry in sheet.entries if entry.item}
    assert any(key.startswith(world["a"].key) for key in keys)
    assert not any(key.startswith(world["b"].key) for key in keys)
    assert sheet.total_seconds == 3600

    admin_sheet = await timesheet.build(db, today, today, actor=admin)
    assert admin_sheet.total_seconds == 3600 + 7200


async def test_timesheet_hides_unreadable_epic_ref(db, admin, world):
    today = date(2026, 8, 3)
    await enablement.set_enabled(db, world["a"].id, True)
    # item_a's nearest epic is B's epic — its key/title must not ride the entry.
    await timelogging.create_worklog(
        db, world["item_a"].id, WorklogCreate(time_spent="30m", worked_on=today), admin.id, today
    )
    sheet = await timesheet.build(db, today, today, actor=world["member"])
    entry = next(e for e in sheet.entries if e.item)
    assert entry.epic is None
    admin_sheet = await timesheet.build(db, today, today, actor=admin)
    admin_entry = next(e for e in admin_sheet.entries if e.item)
    assert admin_entry.epic is not None


# --- N2: hydration --------------------------------------------------------------


async def test_item_payload_hides_unreadable_refs(db, admin, world):
    member_read = await items.get_item(db, world["item_a"].id, world["member"])
    assert member_read.parent is None  # B's epic
    assert member_read.epic is None
    assert member_read.links.outgoing == [] and member_read.links.incoming == []

    admin_read = await items.get_item(db, world["item_a"].id, admin)
    assert admin_read.parent is not None and admin_read.parent.id == world["epic_b"].id
    assert admin_read.epic is not None
    assert any(link.item.id == world["item_b"].id for link in admin_read.links.outgoing)


async def test_child_counts_exclude_unreadable_children(db, admin, world):
    # Give A's item a child in B: the member's child_count must not include it.
    await items.create_item(
        db,
        ItemCreate(
            project_id=world["b"].id,
            title="secret subtask",
            kind=ItemKind.SUBTASK,
            parent_id=world["item_a"].id,
        ),
        admin,
    )
    member_read = await items.get_item(db, world["item_a"].id, world["member"])
    assert member_read.child_count == 0
    admin_read = await items.get_item(db, world["item_a"].id, admin)
    assert admin_read.child_count == 1


# --- N3: SLQ autocomplete (both dialects) ----------------------------------------


async def test_item_key_autocomplete_filters_readability(db, world):
    response = await suggest(
        db, actor=world["member"], project_id=None, q="key = ", cursor=None
    )
    values = {s.value for s in response.suggestions}
    assert any(v.startswith(world["a"].key) for v in values)
    assert not any(v.startswith(world["b"].key) for v in values)


async def test_project_key_autocomplete_filters_readability(db, world):
    response = await suggest(
        db, actor=world["member"], project_id=None, q="project = ", cursor=None
    )
    values = {s.value for s in response.suggestions}
    assert world["a"].key in values
    assert world["b"].key not in values


async def test_worklog_dialect_delegation_filters_readability(db, world):
    response = await suggest_worklog(db, actor=world["member"], q="issue = ", cursor=None)
    values = {s.value for s in response.suggestions}
    assert not any(v.startswith(world["b"].key) for v in values)

    response = await suggest_worklog(db, actor=world["member"], q="project = ", cursor=None)
    values = {s.value for s in response.suggestions}
    assert world["a"].key in values
    assert world["b"].key not in values


# --- N4: rollup descendants -------------------------------------------------------


async def test_rollup_frontier_stays_in_readable_projects(db, admin, world):
    # An epic in A with one child in A and one in B.
    epic_a = await items.create_item(
        db, ItemCreate(project_id=world["a"].id, title="epic a", kind=ItemKind.EPIC), admin
    )
    await items.create_item(
        db, ItemCreate(project_id=world["a"].id, title="child a", parent_id=epic_a.id), admin
    )
    await items.create_item(
        db, ItemCreate(project_id=world["b"].id, title="child b", parent_id=epic_a.id), admin
    )
    member_rollup = await rollup.rollup_items(db, world["member"], [epic_a.id])
    assert member_rollup[epic_a.id].total == 1
    admin_rollup = await rollup.rollup_items(db, admin, [epic_a.id])
    assert admin_rollup[epic_a.id].total == 2
