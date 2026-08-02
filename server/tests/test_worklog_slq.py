"""Worklog SLQ (spec 98) — the timesheet's dialect.

Rooted at the worklog, so it can express the two things an item-rooted query
never could: general worklogs (`issue IS EMPTY`, spec 59 — no item to return)
and the author≠assignee case (`author = me AND issue.assignee != me`).

Executed against real rows, not asserted on SQL strings: a wrong predicate in
query compilation returns a plausible set rather than an error.
"""

import uuid
from datetime import date

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from radd.config import settings
from radd.modules.auth.models import User
from radd.modules.auth.types import InstanceRole
from radd.modules.items import service as items_service
from radd.modules.items.enums import ItemKind
from radd.modules.items.schemas import ItemCreate
from radd.modules.items.slq import SlqError
from radd.modules.projects import service as projects_service
from radd.modules.projects.schemas import ProjectCreate
from radd.modules.timelogging import categories
from radd.modules.timelogging.models import Worklog
from radd.modules.timelogging.slq import compile_worklog_query, parse


@pytest.fixture
async def db():
    engine = create_async_engine(settings.database_url)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as session:
        yield session
        await session.rollback()
    await engine.dispose()


async def _user(db, name: str) -> User:
    user = User(
        email=f"wslq-{uuid.uuid4().hex[:8]}@example.com",
        name=name,
        instance_role=InstanceRole.ADMIN.value,
    )
    db.add(user)
    await db.flush()
    return user


async def _run(db, query: str, actor: User) -> set[uuid.UUID]:
    compiled = await compile_worklog_query(db, parse(query), current_user_id=actor.id)
    stmt = select(Worklog.id)
    if compiled.where is not None:
        stmt = stmt.where(compiled.where)
    return set((await db.execute(stmt)).scalars().all())


async def _fixture(db, actor, other):
    """One project, two issues (assigned to `other`), and three worklogs:
    item-linked by actor, item-linked by other, and a general one by actor."""
    project = await projects_service.create_project(
        db, ProjectCreate(key=f"WQ{uuid.uuid4().hex[:4].upper()}", name="Worklog SLQ")
    )
    issue = await items_service.create_item(
        db, ItemCreate(project_id=project.id, title="Assigned elsewhere", assignee_id=other.id), actor
    )
    await categories.ensure_default_categories(db)
    category = (await categories.list_categories(db))[0]

    mine = Worklog(
        item_id=issue.id,
        project_id=project.id,
        author_id=actor.id,
        time_spent_seconds=3600,
        worked_on=date(2026, 7, 22),
        note="rendered the turntable",
    )
    theirs = Worklog(
        item_id=issue.id,
        project_id=project.id,
        author_id=other.id,
        time_spent_seconds=1800,
        worked_on=date(2026, 7, 10),
    )
    general = Worklog(
        item_id=None,
        project_id=None,
        author_id=actor.id,
        category_id=category.id,
        time_spent_seconds=7200,
        worked_on=date(2026, 7, 23),
    )
    db.add_all([mine, theirs, general])
    await db.flush()
    return project, issue, category, mine, theirs, general


async def test_general_worklogs_are_reachable_only_from_this_dialect(db):
    """`issue IS EMPTY` is the whole reason the timesheet needs a worklog root:
    an item query returns items, and a general worklog has no item to return."""
    actor = await _user(db, "Alice Timesheet")
    other = await _user(db, "Bob Assignee")
    _, _, category, mine, theirs, general = await _fixture(db, actor, other)

    assert await _run(db, "issue IS EMPTY", actor) == {general.id}
    assert await _run(db, "issue IS NOT EMPTY", actor) == {mine.id, theirs.id}
    assert await _run(db, f'category = "{category.name}" AND issue IS EMPTY', actor) == {general.id}


async def test_author_is_independent_of_the_issue_assignee(db):
    """The case that motivated the dialect: worklog author and issue assignee
    are different people, so they must be separately queryable."""
    actor = await _user(db, "Alice Timesheet")
    other = await _user(db, "Bob Assignee")
    _, _, _, mine, theirs, general = await _fixture(db, actor, other)

    assert await _run(db, "author = me", actor) == {mine.id, general.id}
    # My hours on somebody else's issue — one query, two entities.
    assert await _run(db, "author = me AND issue.assignee != me", actor) == {mine.id}
    assert await _run(db, f'author = "{other.email}"', actor) == {theirs.id}


async def test_issue_dotted_fields_delegate_to_the_item_dialect(db):
    """`issue.<field>` is compiled by the ITEM compiler, so the whole item field
    surface works here without this module restating any of it."""
    actor = await _user(db, "Alice Timesheet")
    other = await _user(db, "Bob Assignee")
    project, issue, _, mine, theirs, general = await _fixture(db, actor, other)

    # A builtin item field, reached through the delegation.
    assert await _run(db, f'issue.project = {project.key}', actor) == {mine.id, theirs.id}
    assert await _run(db, f'issue.assignee = "{other.email}"', actor) == {mine.id, theirs.id}
    # Composes with worklog-own fields, and general rows never match an
    # issue-scoped predicate.
    assert await _run(db, f'issue.assignee = "{other.email}" AND author = me', actor) == {mine.id}
    assert general.id not in await _run(db, f"issue.project = {project.key}", actor)


async def test_delegated_epic_filter_agrees_with_group_by_epic(db):
    """`issue.epic = KEY` must select the same hours the timesheet files under
    that epic — including time logged straight ONTO the epic, which is where the
    strict-ancestor reading of `epic` used to disagree with `epics_for_items`."""
    actor = await _user(db, "Alice Timesheet")
    project = await projects_service.create_project(
        db, ProjectCreate(key=f"WE{uuid.uuid4().hex[:4].upper()}", name="Worklog epic")
    )
    epic = await items_service.create_item(
        db, ItemCreate(project_id=project.id, title="Epic", kind=ItemKind.EPIC), actor
    )
    child = await items_service.create_item(
        db, ItemCreate(project_id=project.id, title="Child", parent_id=epic.id), actor
    )
    on_epic, on_child = (
        Worklog(
            item_id=item.id,
            project_id=project.id,
            author_id=actor.id,
            time_spent_seconds=3600,
            worked_on=date(2026, 7, 22),
        )
        for item in (epic, child)
    )
    db.add_all([on_epic, on_child])
    await db.flush()
    epic_key = (await items_service.get_item(db, epic.id, actor)).key

    assert await _run(db, f"issue.epic = {epic_key}", actor) == {on_epic.id, on_child.id}
    assert await _run(db, "issue.epic.category != done", actor) == {on_epic.id, on_child.id}
    # And the grouping seam the timesheet uses reports the same attribution.
    epics = await items_service.epics_for_items(db, [epic.id, child.id])
    assert {ref.key for ref in epics.values()} == {epic_key}


async def test_worklog_own_scalar_fields(db):
    actor = await _user(db, "Alice Timesheet")
    other = await _user(db, "Bob Assignee")
    _, _, _, mine, theirs, general = await _fixture(db, actor, other)

    # Durations use the same language the log-work form accepts.
    assert await _run(db, "time > 1h", actor) == {general.id}
    assert await _run(db, "time >= 1h", actor) == {mine.id, general.id}
    assert await _run(db, "worked_on >= 2026-07-22", actor) == {mine.id, general.id}
    assert await _run(db, "note ~ turntable", actor) == {mine.id}


async def test_unknown_fields_report_a_position(db):
    actor = await _user(db, "Alice Timesheet")
    with pytest.raises(SlqError):
        await _run(db, "nonsense = 1", actor)
    # An unknown field BEHIND the delegation is the item dialect's error, but it
    # must still point at where the user typed rather than into a rewritten AST.
    with pytest.raises(SlqError):
        await _run(db, "issue.nonsense = 1", actor)
