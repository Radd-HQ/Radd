"""Request participants (spec 72): the reporter identity gate, self-leave, LIVE
team fan-out through the notify recipient union, auto-watch on direct add, and
subject validation.

DB-backed (compose Postgres) — flushed, never committed; the session rolls back
at teardown, so rows never persist.
"""

import uuid

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from radd.config import settings as config
from radd.exceptions import ConflictError, ForbiddenError
from radd.modules.auth import roles as auth_roles
from radd.modules.auth.schemas import RoleCreate
from radd.modules.auth.models import GlobalRoleGrant, User
from radd.modules.auth.types import InstanceRole, Permission
from radd.modules.items import service as items
from radd.modules.items.schemas import ItemCreate
from radd.modules.notify import (
    consumer as notify_consumer,
    planner,
    service as notify_service,
)
from radd.modules.notify.types import NotificationType
from radd.modules.participants import service as participants
from radd.modules.participants.schemas import ParticipantAdd
from radd.modules.teams import service as teams_service
from radd.modules.teams.schemas import TeamCreate
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
async def actor(db) -> User:
    user = User(
        email=f"prt-{uuid.uuid4().hex[:8]}@example.com",
        name="Participant Tester",
        instance_role=InstanceRole.ADMIN.value,
    )
    db.add(user)
    await db.flush()
    return user


async def _member(db, name: str) -> User:
    """A plain active user: the global member floor grants item.read but NOT
    item.update (spec 86)."""
    user = User(
        email=f"prt-{uuid.uuid4().hex[:8]}@example.com",
        name=name,
        instance_role=InstanceRole.MEMBER.value,
    )
    db.add(user)
    await db.flush()
    return user


async def _project(db):
    return await projects_service.create_project(
        db,
        ProjectCreate(key=f"PR{uuid.uuid4().hex[:4].upper()}", name="P"),
    )


async def _team(db):
    return await teams_service.create_team(
        db, TeamCreate(name=f"Desk {uuid.uuid4().hex[:6]}")
    )


# --- (a) the reporter identity gate + self-leave ---


async def test_reporter_without_item_update_manages_participants(db, actor):
    project = await _project(db)
    reporter = await _member(db, "Reporter")
    colleague = await _member(db, "Colleague")
    bystander = await _member(db, "Bystander")
    team = await _team(db)
    item = await items.create_item(
        db, ItemCreate(project_id=project.id, title="i", reporter_id=reporter.id), actor
    )

    # The reporter holds only the member floor (no item.update) — IDENTITY, not
    # permission, unlocks sharing their own ticket (the point of spec 72).
    added_team = await participants.add_participant(
        db, item.id, ParticipantAdd(team_id=team.id), reporter
    )
    assert added_team.team is not None and added_team.team.id == team.id
    added_user = await participants.add_participant(
        db, item.id, ParticipantAdd(user_id=colleague.id), reporter
    )
    assert added_user.user is not None and added_user.user.id == colleague.id

    # A member who can SEE the item but holds no item.update cannot add or
    # remove. (Since RADD-825 the floor no longer reads everything — without
    # this grant the bystander gets the hidden-item NotFound before the write
    # check, which is the right answer for a stranger but not this test's.)
    role = await auth_roles.create_role(
        db,
        RoleCreate(
            key=f"pt{uuid.uuid4().hex[:6]}", name="Reader",
            permissions=[Permission.ITEM_READ],
        ),
    )
    db.add(GlobalRoleGrant(project_id=project.id, user_id=bystander.id, role_id=role.id))
    # The colleague needs read too for the self-leave leg below — being a
    # participant does NOT itself confer item visibility (RADD-844 tracks
    # whether it should become a relation).
    db.add(GlobalRoleGrant(project_id=project.id, user_id=colleague.id, role_id=role.id))
    await db.flush()
    with pytest.raises(ForbiddenError):
        await participants.add_participant(
            db, item.id, ParticipantAdd(user_id=bystander.id), bystander
        )
    with pytest.raises(ForbiddenError):
        await participants.remove_participant(db, item.id, added_team.id, bystander)

    read = await participants.list_participants(db, item.id, reporter)
    assert read.can_manage is True
    assert [team_ref.id for team_ref in read.teams] == [team.id]
    assert [user_ref.id for user_ref in read.users] == [colleague.id]
    assert (await participants.list_participants(db, item.id, bystander)).can_manage is False

    # Self-leave: a direct USER participant may always remove themself.
    await participants.remove_participant(db, item.id, added_user.id, colleague)
    read = await participants.list_participants(db, item.id, reporter)
    assert read.users == [] and len(read.rows) == 1


# --- (b) notify fan-out: LIVE team membership + auto-watch ---


async def test_team_fan_out_is_live_and_direct_users_auto_watch(db, actor):
    project = await _project(db)
    reporter = await _member(db, "Reporter")
    stayer = await _member(db, "Stayer")
    leaver = await _member(db, "Leaver")
    direct = await _member(db, "Direct")
    team = await _team(db)
    await teams_service.add_team_member(db, team.id, stayer.id)
    await teams_service.add_team_member(db, team.id, leaver.id)
    item = await items.create_item(
        db, ItemCreate(project_id=project.id, title="i", reporter_id=reporter.id), actor
    )

    await participants.add_participant(db, item.id, ParticipantAdd(team_id=team.id), reporter)
    await participants.add_participant(db, item.id, ParticipantAdd(user_id=direct.id), reporter)

    # Direct user participant → item_watchers row on add (one fan-out mechanism).
    assert await notify_service.is_watching(db, item.id, direct.id)
    # Team participants are NOT individually watched — membership resolves live.
    assert not await notify_service.is_watching(db, item.id, stayer.id)

    # A comment.created plan built through the consumer's recipient union
    # (watchers ∪ participant-team CURRENT members) reaches both team members.
    recipients = await notify_consumer.recipient_ids(db, item.id)
    assert {stayer.id, leaver.id, direct.id} <= recipients
    plan = planner.plan_comment_created(
        {"excerpt": "hi", "visibility": "public"}, actor.id, recipients, frozenset()
    )
    types = {planned.user_id: planned.type for planned in plan.notifications}
    assert types[stayer.id] is NotificationType.COMMENTED
    assert types[leaver.id] is NotificationType.COMMENTED

    # Leaving the team stops delivery WITHOUT cleanup rows (spec 72 §3).
    await teams_service.remove_team_member(db, team.id, leaver.id)
    recipients = await notify_consumer.recipient_ids(db, item.id)
    assert leaver.id not in recipients and stayer.id in recipients
    plan = planner.plan_comment_created(
        {"excerpt": "again", "visibility": "public"}, actor.id, recipients, frozenset()
    )
    assert leaver.id not in {planned.user_id for planned in plan.notifications}


# --- (c) subject validation: unknown/inactive subject + dupes (409) ---


async def test_subject_validation_and_dupes_conflict(db, actor):
    project = await _project(db)
    reporter = await _member(db, "Reporter")
    colleague = await _member(db, "Colleague")
    inactive = User(
        email=f"prt-out-{uuid.uuid4().hex[:8]}@example.com",
        name="Inactive",
        instance_role=InstanceRole.MEMBER.value,
        active=False,
    )
    db.add(inactive)
    await db.flush()
    item = await items.create_item(
        db, ItemCreate(project_id=project.id, title="i", reporter_id=reporter.id), actor
    )

    # A non-existent team / an inactive user → 409 (spec 86: any ACTIVE user and
    # any existing team is a valid subject — scope is global).
    with pytest.raises(ConflictError):
        await participants.add_participant(
            db, item.id, ParticipantAdd(team_id=uuid.uuid4()), reporter
        )
    with pytest.raises(ConflictError):
        await participants.add_participant(
            db, item.id, ParticipantAdd(user_id=inactive.id), reporter
        )

    # Duplicates → 409 (both subject kinds).
    await participants.add_participant(
        db, item.id, ParticipantAdd(user_id=colleague.id), reporter
    )
    with pytest.raises(ConflictError):
        await participants.add_participant(
            db, item.id, ParticipantAdd(user_id=colleague.id), reporter
        )
    team = await _team(db)
    await participants.add_participant(db, item.id, ParticipantAdd(team_id=team.id), reporter)
    with pytest.raises(ConflictError):
        await participants.add_participant(
            db, item.id, ParticipantAdd(team_id=team.id), reporter
        )
