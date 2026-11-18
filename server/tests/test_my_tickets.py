"""RADD-1572: the "my tickets" list — what a person is likely to log time on.

The invariants other surfaces lean on: an issue the person only ACTED on is
found (through the event log, with no event type named here), a closed
assignment is not, and nothing outside what they can read is ever listed.
"""

import uuid
from datetime import timedelta

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from radd.clock import utcnow
from radd.config import settings as config
from radd.modules.auth import grants, principals, roles, service as auth
from radd.modules.auth.models import Role
from radd.modules.auth.schemas import UserCreate
from radd.modules.auth.types import InstanceRole
from radd.modules.comments import service as comments
from radd.modules.comments.schemas import CommentCreate
from radd.modules.items import service as items
from radd.modules.items.enums import Priority
from radd.modules.items.schemas import ItemCreate, ItemUpdate
from radd.modules.notify import service as notify
from radd.modules.projects import service as projects
from radd.modules.projects.schemas import ProjectCreate
from radd.modules.timelogging import mytickets
from radd.modules.timelogging.models import Worklog
from radd.modules.timelogging.types import TicketReason
from radd.modules.workflow import service as workflow
from radd.modules.workflow.types import StateCategory


@pytest.fixture
async def db():
    engine = create_async_engine(config.database_url)
    async with async_sessionmaker(engine, expire_on_commit=False)() as session:
        await roles.ensure_builtin_roles(session)
        await principals.ensure_builtin_accounts(session)
        yield session
        await session.rollback()
    await engine.dispose()


async def _person(db, name, role=InstanceRole.MEMBER):
    return await auth.create_user(
        db,
        UserCreate(
            email=f"{name}-{uuid.uuid4().hex[:8]}@people.example.com",
            name=name,
            password=f"pw-{uuid.uuid4().hex}",
            instance_role=role,
        ),
    )


async def _project(db, name):
    return await projects.create_project(
        db, ProjectCreate(key=f"M{uuid.uuid4().hex[:6].upper()}", name=name)
    )


async def test_assigned_logged_and_acted_on_are_listed_and_nothing_unreadable(db):
    admin = await _person(db, "admin", InstanceRole.ADMIN)
    person = await _person(db, "person")
    mine, hidden = await _project(db, "Mine"), await _project(db, "Hidden")
    reader = Role(
        key=f"reader-{uuid.uuid4().hex[:6]}",
        name="reader",
        permissions=["item.read", "item.update", "comment.write"],
    )
    db.add(reader)
    await db.flush()
    await grants.create_grant(db, role_id=reader.id, user_id=person.id, project_id=mine.id)

    def new(project, title, **more):
        return items.create_item(db, ItemCreate(project_id=project.id, title=title, **more), admin)

    assigned = await new(mine, "Assigned and open", assignee_id=person.id)
    closed = await new(mine, "Assigned and done", assignee_id=person.id)
    states = await workflow.list_states(db, mine.id)
    done = next(state for state in states if state.category == StateCategory.DONE.value)
    await items.update_item(db, closed.id, ItemUpdate(state_id=done.id), admin)
    commented = await new(mine, "Only commented on")
    await comments.create_comment(db, commented.id, CommentCreate(body="Looking at this"), person)
    booked = await new(mine, "Booked on last week")
    stale = await new(mine, "Booked on months ago")
    untouched = await new(mine, "Nothing to do with them")
    out_of_reach = await new(hidden, "Assigned, in a project they cannot read", assignee_id=person.id)
    today = utcnow().date()
    for item, day, seconds in (
        (booked, today - timedelta(days=3), 5400),
        (booked, today - timedelta(days=60), 1800),
        (stale, today - timedelta(days=60), 3600),
        (out_of_reach, today, 3600),
    ):
        db.add(Worklog(item_id=item.id, author_id=person.id, worked_on=day, time_spent_seconds=seconds))
    await db.flush()

    tickets = {ticket.id: ticket for ticket in await mytickets.my_tickets(db, person)}

    assert set(tickets) == {assigned.id, commented.id, booked.id}
    assert untouched.id not in tickets and out_of_reach.id not in tickets
    assert tickets[assigned.id].reasons == [TicketReason.ASSIGNED]
    assert tickets[commented.id].reasons == [TicketReason.ACTED]
    assert tickets[commented.id].activity == "Comment added"
    assert tickets[booked.id].reasons == [TicketReason.LOGGED]
    # Everything they ever logged on it, not only what the window holds.
    assert tickets[booked.id].my_seconds == 7200
    assert tickets[assigned.id].loggable is False  # time logging is off for the project
    assert tickets[assigned.id].key == f"{mine.key}-{assigned.number}"


async def test_planning_only_edits_and_watching_are_not_work_on_an_issue(db):
    """RADD-1578: triage must not bury what a person worked on."""
    admin = await _person(db, "admin", InstanceRole.ADMIN)
    project = await _project(db, "Triage")

    def new(title):
        return items.create_item(db, ItemCreate(project_id=project.id, title=title), admin)

    triaged = await new("Only re-prioritised and labelled")
    moved = await new("Moved to another state")
    both = await new("Re-prioritised and moved in one edit")
    watched = await new("Only watched")
    retitled = await new("Retitled")
    states = await workflow.list_states(db, project.id)
    done = next(state for state in states if state.category == StateCategory.DONE.value)
    # A second actor does the acting: `admin` only created the issues.
    actor = await _person(db, "triager", InstanceRole.ADMIN)
    await items.update_item(db, triaged.id, ItemUpdate(priority=Priority.HIGH), actor)
    await items.update_item(db, triaged.id, ItemUpdate(labels=["later"]), actor)
    await items.update_item(db, moved.id, ItemUpdate(state_id=done.id), actor)
    await items.update_item(db, both.id, ItemUpdate(priority=Priority.HIGH, state_id=done.id), actor)
    await items.update_item(db, retitled.id, ItemUpdate(title="Retitled, properly"), actor)
    await notify.watch(db, watched.id, actor.id)
    await db.flush()

    tickets = {ticket.id: ticket for ticket in await mytickets.my_tickets(db, actor)}

    assert set(tickets) == {moved.id, both.id, retitled.id}
    assert tickets[moved.id].reasons == [TicketReason.ACTED]
    # The premise: with nothing configured as quiet, all five ARE listed, so the
    # rule above is what removed the other two.
    before = config.timelog_my_tickets_quiet_fields, config.timelog_my_tickets_quiet_events
    config.timelog_my_tickets_quiet_fields, config.timelog_my_tickets_quiet_events = [], []
    try:
        everything = {ticket.id for ticket in await mytickets.my_tickets(db, actor)}
    finally:
        config.timelog_my_tickets_quiet_fields, config.timelog_my_tickets_quiet_events = before
    assert everything == {triaged.id, moved.id, both.id, watched.id, retitled.id}
