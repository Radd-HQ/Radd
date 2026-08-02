"""Hard-deleting a user, with their work reassigned (spec 89).

Spec 87 dropped the `user.delete` atom on the reasoning that accounts are only
ever deactivated or merged; spec 89 reinstates it. The invariants that matter:

  - nothing the person authored is lost — it lands on the named successor,
  - EXCEPT worklogs, which are discarded rather than moved, so nobody is
    credited with hours they did not work,
  - the row actually goes, which means every FK referencing it must have been
    dealt with first (13 columns would otherwise block, several more would
    silently dangle),
  - you cannot delete yourself, or orphan work by omitting a successor.

Rolled-back transactions on the compose DB.
"""

import uuid
from datetime import date

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from radd.config import settings
from radd.exceptions import ConflictError, NotFoundError
from radd.modules import workflow  # noqa: F401 — registers the default-state hook
from radd.modules.auth import service as auth_service
from radd.modules.auth.models import User
from radd.modules.auth.types import InstanceRole
from radd.modules.comments import service as comments_service
from radd.modules.comments.schemas import CommentCreate
from radd.modules.items import service as items_service
from radd.modules.items.schemas import ItemCreate
from radd.modules.projects import service as projects_service
from radd.modules.projects.schemas import ProjectCreate
from radd.modules.timelogging import enablement as timelog_enablement, service as timelog_service
from radd.modules.timelogging.schemas import WorklogCreate


@pytest.fixture
async def db():
    engine = create_async_engine(settings.database_url)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as session:
        yield session
        await session.rollback()
    await engine.dispose()


async def _user(db, label, *, role=InstanceRole.ADMIN, active=True) -> User:
    user = User(
        email=f"del-{label}-{uuid.uuid4().hex[:6]}@example.com",
        name=f"{label.title()} Person",
        instance_role=role.value,
        active=active,
    )
    db.add(user)
    await db.flush()
    return user


async def test_delete_reassigns_work_and_discards_worklogs(db):
    leaver = await _user(db, "leaver")
    successor = await _user(db, "successor")
    project = await projects_service.create_project(
        db, ProjectCreate(key=f"UD{uuid.uuid4().hex[:4].upper()}", name="P")
    )
    item = await items_service.create_item(
        db, ItemCreate(project_id=project.id, title="their issue"), leaver
    )
    await comments_service.create_comment(
        db, item.id, CommentCreate(body="their comment"), leaver
    )
    await timelog_enablement.set_enabled(db, project.id, True)  # per-project opt-in (spec 22)
    await timelog_service.create_worklog(
        db, item.id, WorklogCreate(time_spent="2h"), leaver.id, date.today()
    )

    summary = await auth_service.user_content_summary(db, leaver.id)
    assert summary["reported_items"] == 1 and summary["comments"] == 1
    assert summary["worklogs"] == 1 and summary["worklog_seconds"] == 2 * 3600

    await auth_service.delete_user(db, leaver.id, successor.id, actor=successor)

    # The account is really gone — not deactivated.
    with pytest.raises(NotFoundError):
        await auth_service.get_user(db, leaver.id)
    # Their authored work survives, now owned by the successor.
    reporter = await db.scalar(
        text("SELECT reporter_id FROM work_items WHERE id = :i"), {"i": item.id}
    )
    assert reporter == successor.id
    author = await db.scalar(
        text("SELECT author_id FROM comments WHERE item_id = :i"), {"i": item.id}
    )
    assert author == successor.id
    # …but their hours are gone, not credited to anyone.
    assert (await auth_service.user_content_summary(db, successor.id))["worklogs"] == 0
    assert await db.scalar(
        text("SELECT count(*) FROM worklogs WHERE item_id = :i"), {"i": item.id}
    ) == 0


async def test_successor_required_only_when_there_is_something_to_inherit(db):
    actor = await _user(db, "actor")
    empty = await _user(db, "empty")
    # Owns nothing: deleting needs no successor, so clearing out placeholder
    # accounts stays one click.
    await auth_service.delete_user(db, empty.id, None, actor=actor)
    with pytest.raises(NotFoundError):
        await auth_service.get_user(db, empty.id)

    owner = await _user(db, "owner")
    project = await projects_service.create_project(
        db, ProjectCreate(key=f"UE{uuid.uuid4().hex[:4].upper()}", name="P")
    )
    await items_service.create_item(db, ItemCreate(project_id=project.id, title="x"), owner)
    with pytest.raises(ConflictError, match="owns work"):
        await auth_service.delete_user(db, owner.id, None, actor=actor)


async def test_guards(db):
    actor = await _user(db, "self")
    other = await _user(db, "other")
    inactive = await _user(db, "inactive", active=False)

    with pytest.raises(ConflictError, match="your own account"):
        auth_service.ensure_deletable(actor, actor, None, False)
    with pytest.raises(ConflictError, match="cannot be the account"):
        auth_service.ensure_deletable(other, actor, other, True)
    with pytest.raises(ConflictError, match="deactivated"):
        auth_service.ensure_deletable(other, actor, inactive, True)
    # Fine: someone else, an active successor, work to hand over.
    auth_service.ensure_deletable(other, actor, actor, True)


async def test_owned_team_follows_the_successor(db):
    """teams.owner_id is ON DELETE SET NULL — without an explicit repoint the
    team would be silently orphaned instead of inherited."""
    from radd.modules.teams import service as teams_service
    from radd.modules.teams.schemas import TeamCreate

    leaver = await _user(db, "teamowner")
    successor = await _user(db, "heir")
    team = await teams_service.create_team(
        db, TeamCreate(name=f"UD-{uuid.uuid4().hex[:6]}"), actor_id=leaver.id
    )
    assert team.owner_id == leaver.id

    await auth_service.delete_user(db, leaver.id, successor.id, actor=successor)
    await db.refresh(team)
    assert team.owner_id == successor.id


async def test_every_blocking_reference_is_covered(db):
    """The delete must not depend on luck: every FK column that would refuse the
    delete has to appear in the repoint list. Asserted against the live schema so
    a new table referencing users can't quietly break deletion."""
    rows = await db.execute(
        text(
            """
            SELECT c.conrelid::regclass::text, a.attname
              FROM pg_constraint c
              JOIN unnest(c.conkey) k(attnum) ON true
              JOIN pg_attribute a ON a.attrelid = c.conrelid AND a.attnum = k.attnum
             WHERE c.contype = 'f' AND c.confrelid = 'users'::regclass
               AND c.confdeltype IN ('a', 'r')
            """
        )
    )
    blocking = {(t, c) for t, c in rows}
    handled = set(auth_service._MERGE_REPOINT) | {
        (t, c) for t, _e, c in auth_service._MERGE_DEDUPE
    } | {("worklogs", "author_id")}  # deleted outright
    assert blocking <= handled, f"unhandled blocking FK columns: {sorted(blocking - handled)}"
