"""RADD-844 — a participant is a second reporter.

The decision (2026-08-05): sharing an item with someone means they can OPEN it,
COMMENT on it, and get notified — nothing wider. Delivered as the `participant`
relation on the item resource plus the Baseline's `item.read@participant` +
`comment.write@participant` (and `comment.write@own`, so the FIRST reporter
holds the same discussion right). Pinned here:

  - a user with no standing in the project cannot see the item; sharing it
    with them makes exactly that item readable — in the row gate AND the list
    filter (the where-form composes into `relation_read_clause`),
  - a TEAM participant row covers its current members,
  - the shared-into user can comment but still cannot update,
  - self-leave is an IDENTITY operation: it works even when the floor was
    narrowed so the participant cannot read the item at all,
  - the notify recipient gate honours the relation (the async row gate).

DB-backed (rolled-back transactions on the compose DB).
"""

import uuid

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from radd.config import settings as config
from radd.exceptions import ForbiddenError, NotFoundError
from radd.modules import workflow  # noqa: F401 — registers the default-state hook
from radd.modules.auth import authz, roles as auth_roles
from radd.modules.auth.models import Role, User
from radd.modules.auth.types import BuiltinRoleKey, InstanceRole
from radd.modules.comments import service as comments_service
from radd.modules.comments.schemas import CommentCreate
from radd.modules.items import service as items
from radd.modules.items.filters import ItemListFilters
from radd.modules.items.models import WorkItem
from radd.modules.items.schemas import ItemCreate, ItemUpdate
from radd.modules.items.service import visibility
from radd.modules.participants import service as participants
from radd.modules.participants.schemas import ParticipantAdd
from radd.modules.projects import service as projects_service
from radd.modules.projects.schemas import ProjectCreate
from radd.modules.teams import service as teams_service
from radd.modules.teams.schemas import TeamCreate


@pytest.fixture
async def db():
    engine = create_async_engine(config.database_url)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as session:
        await auth_roles.ensure_builtin_roles(session)
        yield session
        await session.rollback()
    await engine.dispose()


@pytest.fixture
async def admin(db) -> User:
    user = User(
        email=f"pv-{uuid.uuid4().hex[:8]}@example.com",
        name="Admin",
        instance_role=InstanceRole.ADMIN.value,
    )
    db.add(user)
    await db.flush()
    return user


async def _outsider(db, name: str) -> User:
    """An active staff account holding ONLY the Baseline — no roles, no
    memberships, no standing anywhere."""
    user = User(
        email=f"pv-{uuid.uuid4().hex[:8]}@example.com",
        name=name,
        instance_role=InstanceRole.MEMBER.value,
    )
    db.add(user)
    await db.flush()
    return user


async def _fixture(db, admin):
    project = await projects_service.create_project(
        db, ProjectCreate(key=f"PV{uuid.uuid4().hex[:4].upper()}", name="P")
    )
    item = await items.create_item(
        db, ItemCreate(project_id=project.id, title="restricted ticket"), admin
    )
    return project, item


async def test_share_confers_read_on_that_item_only(db, admin):
    project, item = await _fixture(db, admin)
    other = await items.create_item(
        db, ItemCreate(project_id=project.id, title="not shared"), admin
    )
    outsider = await _outsider(db, "Outsider")

    with pytest.raises(NotFoundError):  # hidden, not forbidden (spec 57)
        await items.require_readable_item(db, item.id, outsider)

    await participants.add_participant(
        db, item.id, ParticipantAdd(user_id=outsider.id), admin
    )
    read_item, _, _ = await items.require_readable_item(db, item.id, outsider)
    assert read_item.id == item.id
    with pytest.raises(NotFoundError):  # the share reaches ONE item, not the project
        await items.require_readable_item(db, other.id, outsider)

    # The list filter agrees with the gate (where-form composes into the OR).
    listed = await items.list_items(
        db, actor=outsider, filters=ItemListFilters(project_id=project.id), limit=50, offset=0
    )
    assert {r.id for r in listed} == {item.id}


async def test_team_participant_covers_current_members(db, admin):
    project, item = await _fixture(db, admin)
    team = await teams_service.create_team(db, TeamCreate(name=f"PV {uuid.uuid4().hex[:6]}"))
    member = await _outsider(db, "Team Member")
    await teams_service.add_team_member(db, team.id, member.id)

    await participants.add_participant(db, item.id, ParticipantAdd(team_id=team.id), admin)
    read_item, _, _ = await items.require_readable_item(db, item.id, member)
    assert read_item.id == item.id


async def test_participant_comments_but_never_updates(db, admin):
    project, item = await _fixture(db, admin)
    outsider = await _outsider(db, "Second Reporter")
    await participants.add_participant(
        db, item.id, ParticipantAdd(user_id=outsider.id), admin
    )

    comment = await comments_service.create_comment(
        db, item.id, CommentCreate(body="following this"), outsider
    )
    assert comment.author.id == outsider.id
    with pytest.raises(ForbiddenError):
        await items.update_item(db, item.id, ItemUpdate(title="hijacked"), outsider)

    # The capabilities stamp tells the client the same story — and stays one
    # batched membership query, not one per row (RADD-844).
    listed = await items.list_items(
        db, actor=outsider, filters=ItemListFilters(project_id=project.id), limit=50, offset=0
    )
    row = (
        await db.execute(select(WorkItem).where(WorkItem.id == item.id))
    ).scalar_one()
    permissions = {project.id: await authz.effective_permissions(db, outsider, project=project)}
    stamped = await visibility.attach_capabilities(
        db, outsider, listed, {row.id: row}, permissions
    )
    caps = stamped[0].capabilities
    assert caps is not None and caps.can_comment and not caps.can_update


async def test_first_reporter_holds_the_same_discussion_right(db, admin):
    """comment.write@own: a staff reporter with no role in the project can
    reply on their own ticket — the gap the second-reporter floor closes for
    reporter number one."""
    project, _ = await _fixture(db, admin)
    reporter = await _outsider(db, "First Reporter")
    # Filed FOR them (the forms path): reporter override by a manager — the
    # outsider holds no item.create anywhere.
    item = await items.create_item(
        db,
        ItemCreate(project_id=project.id, title="my own ask", reporter_id=reporter.id),
        admin,
    )
    comment = await comments_service.create_comment(
        db, item.id, CommentCreate(body="any update?"), reporter
    )
    assert comment.author.id == reporter.id


async def test_non_participant_still_cannot_comment(db, admin):
    """The relation gate must bite: holding comment.write@participant via the
    Baseline confers nothing on an item that was never shared with you."""
    project, item = await _fixture(db, admin)
    stranger = await _outsider(db, "Stranger")
    with pytest.raises((ForbiddenError, NotFoundError)):
        await comments_service.create_comment(
            db, item.id, CommentCreate(body="drive-by"), stranger
        )


async def test_self_leave_is_an_identity_operation(db, admin):
    """Removing YOURSELF must not require being able to read the item: narrow
    the floor (an admin editing the Baseline) and the trapped participant can
    still leave to stop the notifications."""
    project, item = await _fixture(db, admin)
    outsider = await _outsider(db, "Trapped")
    row = await participants.add_participant(
        db, item.id, ParticipantAdd(user_id=outsider.id), admin
    )

    baseline = (
        await db.execute(select(Role).where(Role.key == BuiltinRoleKey.BASELINE.value))
    ).scalar_one()
    baseline.permissions = [
        p for p in baseline.permissions if p != "item.read@participant"
    ]
    await db.flush()
    db.info.pop("radd.baseline_permissions", None)

    with pytest.raises(NotFoundError):
        await items.require_readable_item(db, item.id, outsider)
    await participants.remove_participant(db, item.id, row.id, outsider)  # no raise
    remaining = await participants.list_participants(db, item.id, admin)
    assert all(u.id != outsider.id for u in remaining.users)


async def test_notify_row_gate_honours_the_relation(db, admin):
    """The recipient gate is the async row gate now: a relation-scoped reader
    whose relation lives in a membership table still receives delivery."""
    project, item = await _fixture(db, admin)
    outsider = await _outsider(db, "Recipient")
    row_item = (
        await db.execute(select(WorkItem).where(WorkItem.id == item.id))
    ).scalar_one()
    actor = await authz.relation_actor(db, outsider)
    relations = frozenset({"own", "participant"})
    assert not await authz.relation_holds_row_async(db, "item", relations, actor, row_item)
    await participants.add_participant(
        db, item.id, ParticipantAdd(user_id=outsider.id), admin
    )
    assert await authz.relation_holds_row_async(db, "item", relations, actor, row_item)
    # and the SYNC resolver fails closed rather than wide
    assert not authz.relation_holds_row("item", relations, actor, row_item)
