"""Who may resolve a thread is a project's rule, per issue type (RADD-1283).

The invariant many surfaces depend on: `set_resolved` and the `can_resolve` a
read carries are the SAME answer, from `resolution.resolve_reach` — so a client
that shows the button exactly when `can_resolve` is true never offers a resolve
the server refuses, whichever rule the project chose.

DB-backed, flushed never committed. A scoped key stands in for a member without
project.manage (an admin whose scope lacks it holds exactly what that member does).
"""

import uuid

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from radd.config import settings as config
from radd.exceptions import ConflictError, ForbiddenError, NotFoundError
from radd.modules.auth.models import User
from radd.modules.auth.scopes import parse_scope
from radd.modules.comments import resolution, service
from radd.modules.comments.schemas import (
    CommentCreate, ThreadResolutionOverride as Override, ThreadResolutionPolicy as Policy,
)
from radd.modules.comments.types import CommentEvent, ThreadResolvers as R
from radd.modules.events.models import Event
from radd.modules.items import service as items
from radd.modules.items.schemas import ItemCreate
from radd.modules.itemtypes import service as itemtypes
from radd.modules.itemtypes.schemas import IssueTypeCreate
from radd.modules.projects import service as projects_service
from radd.modules.projects.schemas import ProjectCreate

MEMBER = ["item.read", "comment.write"]


@pytest.fixture
async def db():
    engine = create_async_engine(config.database_url)
    async with async_sessionmaker(engine, expire_on_commit=False)() as session:
        yield session
        await session.rollback()
    await engine.dispose()


async def _user(db, name: str, scope: list[str] | None = None) -> User:
    user = User(email=f"resolve-{uuid.uuid4().hex[:8]}@example.com", name=name, instance_role="admin")
    db.add(user)
    await db.flush()
    if scope is not None:
        user.token_scope = parse_scope({"global": scope})
    return user


@pytest.fixture
async def world(db):
    manager = await _user(db, "Manager")
    author = await _user(db, "Author", MEMBER)
    other = await _user(db, "Other", MEMBER)
    project = await projects_service.create_project(
        db, ProjectCreate(key=f"TR{uuid.uuid4().hex[:4].upper()}", name="Thread rules"))
    review = await itemtypes.create_type(db, IssueTypeCreate(
        project_id=project.id, name=f"Review {uuid.uuid4().hex[:4]}", color="#123456"))
    task = await itemtypes.create_type(db, IssueTypeCreate(
        project_id=project.id, name=f"Chore {uuid.uuid4().hex[:4]}", color="#654321"))

    async def thread(type_id, assignee=None):
        item = await items.create_item(db, ItemCreate(
            project_id=project.id, title="t", type_id=type_id, assignee_id=assignee), manager)
        return await service.create_comment(db, item.id, CommentCreate(body="Q?", is_thread=True), author)

    return manager, author, other, project, review, task, thread


async def _can(db, root, actor) -> bool:
    """What a READ tells this person — the flag the UI shows the button by."""
    page = await service.comment_page(db, root.entity_id, actor)
    return next(row for row in page.comments if row.id == root.id).can_resolve


async def _resolves(db, root, actor) -> bool:
    """What the SERVER lets this person do — and it must equal `_can`."""
    expected = await _can(db, root, actor)
    try:
        await service.set_resolved(db, root.id, actor, resolved=True)
        await service.set_resolved(db, root.id, actor, resolved=False)
        did = True
    except ForbiddenError:
        did = False
    assert did == expected, f"read said can_resolve={expected}, server said {did}"
    return did


async def test_default_is_the_author_and_managers(db, world):
    manager, author, other, _project, review, _task, thread = world
    root = await thread(review.id)
    assert await _resolves(db, root, author)
    assert await _resolves(db, root, manager)
    assert not await _resolves(db, root, other)


async def test_project_default_and_type_override_each_govern_their_issues(db, world):
    manager, author, other, project, review, task, thread = world
    await resolution.set_policy(db, project.id, Policy(
        default=R.ANYONE, overrides=[Override(issue_type_id=review.id, resolvers=R.MANAGERS)]), manager)
    chore, gated = await thread(task.id), await thread(review.id)
    # The project default reaches a type with no override…
    assert await _resolves(db, chore, other)
    # …and the override beats it: managers only, not even the thread's author.
    assert not await _resolves(db, gated, author)
    assert not await _resolves(db, gated, other)
    assert await _resolves(db, gated, manager)


async def test_assignee_rule_adds_the_assignee_to_the_author(db, world):
    manager, author, other, project, review, _task, thread = world
    await resolution.set_policy(db, project.id, Policy(default=R.ASSIGNEE), manager)
    root = await thread(review.id, assignee=other.id)
    assert await _resolves(db, root, other)
    assert await _resolves(db, root, author)
    bystander = await _user(db, "Bystander", MEMBER)
    assert not await _resolves(db, root, bystander)


async def test_losing_comment_write_loses_resolve_under_every_rule_but_managers(db, world):
    manager, author, _other, project, review, _task, thread = world
    await resolution.set_policy(db, project.id, Policy(default=R.ANYONE), manager)
    root = await thread(review.id)
    author.token_scope = parse_scope({"global": ["item.read"]})
    assert not await _resolves(db, root, author)


async def test_policy_rejects_foreign_or_duplicate_types_and_audits_changes(db, world):
    manager, _author, _other, project, review, _task, _thread = world
    elsewhere = await projects_service.create_project(
        db, ProjectCreate(key=f"TX{uuid.uuid4().hex[:4].upper()}", name="Elsewhere"))
    foreign = await itemtypes.create_type(db, IssueTypeCreate(
        project_id=elsewhere.id, name="Foreign", color="#abcdef"))
    with pytest.raises(NotFoundError):
        await resolution.set_policy(db, project.id, Policy(
            overrides=[Override(issue_type_id=foreign.id, resolvers=R.ANYONE)]), manager)
    with pytest.raises(ConflictError):
        await resolution.set_policy(db, project.id, Policy(overrides=[
            Override(issue_type_id=review.id, resolvers=R.ANYONE),
            Override(issue_type_id=review.id, resolvers=R.MANAGERS)]), manager)

    saved = await resolution.set_policy(db, project.id, Policy(
        default=R.ANYONE, overrides=[Override(issue_type_id=review.id, resolvers=R.MANAGERS)]), manager)
    assert saved.default is R.ANYONE and saved.overrides[0].resolvers is R.MANAGERS
    event = await db.scalar(select(Event).where(
        Event.event_type == CommentEvent.RESOLUTION_POLICY_UPDATED.value, Event.entity_id == str(project.id)))
    fields = {change["field"]: (change["from"], change["to"]) for change in event.payload["changes"]}
    assert fields == {"default": ("author", "anyone"), f"type:{review.name}": (None, "managers")}

    # Back to the default stores nothing: "no row" keeps meaning "never set".
    assert (await resolution.set_policy(db, project.id, Policy(), manager)) == Policy()
    assert await resolution._rules(db, project.id) == []
