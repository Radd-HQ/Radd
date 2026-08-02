"""Merging two accounts (spec 88/89) — the invariants, not the plumbing.

A merge asserts "these rows are the same person". The privileges that person
holds must therefore survive it, whichever row wins: folding an admin into a
member is the NORMAL direction when an AD import adopts someone's older local
account, and it silently demoted them until 2026-07-28. If that admin was the
only one, the instance was left with no way back in short of raw SQL.
"""

import uuid

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from radd.config import settings
from radd.modules.auth import service as auth
from radd.modules.auth.models import User
from radd.modules.auth.types import InstanceRole


@pytest.fixture
async def db():
    engine = create_async_engine(settings.database_url)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as session:
        yield session
        await session.rollback()
    await engine.dispose()


async def _user(db, *, role: InstanceRole, source: str = "local") -> User:
    user = User(
        email=f"merge-{uuid.uuid4().hex[:8]}@example.com",
        name="Merge Tester",
        instance_role=role.value,
        source=source,
        active=True,
    )
    db.add(user)
    await db.flush()
    return user


async def test_merging_an_admin_into_a_member_keeps_admin(db):
    """The reported case: a local admin folded into their AD-sourced member
    account. The person is still an admin afterwards."""
    admin = await _user(db, role=InstanceRole.ADMIN)
    directory = await _user(db, role=InstanceRole.MEMBER, source="ldap")

    await auth.merge_users(db, admin.id, directory.id)

    assert directory.instance_role == InstanceRole.ADMIN.value
    assert directory.active is True
    # The merged-away row is DELETED, not left as a dead duplicate.
    assert await auth.get_user_by_email(db, admin.email) is None


async def test_merging_a_member_into_an_admin_leaves_admin_alone(db):
    """The other direction must not change anything — no accidental promotion
    of the survivor beyond what the two accounts already held."""
    member = await _user(db, role=InstanceRole.MEMBER)
    admin = await _user(db, role=InstanceRole.ADMIN)

    await auth.merge_users(db, member.id, admin.id)

    assert admin.instance_role == InstanceRole.ADMIN.value
    assert admin.active is True


async def test_the_merged_away_account_is_deleted(db):
    """It owns nothing afterwards, so keeping it only clutters every picker."""
    source = await _user(db, role=InstanceRole.MEMBER)
    target = await _user(db, role=InstanceRole.MEMBER)
    source_id = source.id

    await auth.merge_users(db, source.id, target.id)

    assert await db.get(User, source_id) is None
    assert await db.get(User, target.id) is not None


async def test_merging_two_members_promotes_nobody(db):
    source = await _user(db, role=InstanceRole.MEMBER)
    target = await _user(db, role=InstanceRole.MEMBER)

    await auth.merge_users(db, source.id, target.id)

    assert target.instance_role == InstanceRole.MEMBER.value


async def test_worklogs_MOVE_to_the_survivor_rather_than_being_destroyed(db):
    """The line between merge and delete.

    `delete_user` DESTROYS worklogs, so nobody is credited with hours they did
    not work — right when work is reassigned to a DIFFERENT person. A merge says
    it is the same person, so the hours are theirs and must follow them. Getting
    this wrong silently drops time from every timesheet.
    """
    from datetime import date

    from radd.modules.timelogging import categories
    from radd.modules.timelogging.models import Worklog

    await categories.ensure_default_categories(db)
    category = (await categories.list_categories(db))[0]
    source = await _user(db, role=InstanceRole.MEMBER)
    target = await _user(db, role=InstanceRole.MEMBER)
    worklog = Worklog(
        # A general worklog (spec 59) — no project/item fixture needed. Its
        # category is its identity, which `ck_worklogs_scope` enforces.
        item_id=None,
        project_id=None,
        category_id=category.id,
        author_id=source.id,
        time_spent_seconds=3600,
        worked_on=date(2026, 7, 28),
    )
    db.add(worklog)
    await db.flush()

    await auth.merge_users(db, source.id, target.id)
    await db.refresh(worklog)

    assert worklog.author_id == target.id
    assert worklog.time_spent_seconds == 3600


async def test_a_user_cannot_be_merged_into_itself(db):
    user = await _user(db, role=InstanceRole.MEMBER)

    with pytest.raises(Exception):
        await auth.merge_users(db, user.id, user.id)
