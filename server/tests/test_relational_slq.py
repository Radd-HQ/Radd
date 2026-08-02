"""Relational item-SLQ fields: `logged_by` (timelogging) and `commented_by`
(comments).

Both are contributed through the plugin SLQ-field registry rather than hardcoded
in items, so items keeps no knowledge of worklogs or comments. What matters here
is that the compiled subquery actually SELECTS THE RIGHT ITEMS — a wrong
predicate in query compilation returns a plausible-looking set rather than an
error, so this is the kind of thing that has to be executed, not eyeballed.
"""

import uuid
from datetime import date

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from radd.config import settings
from radd.modules.auth.models import User
from radd.modules.auth.types import InstanceRole
from radd.modules.comments.models import Comment
from radd.modules.items import service as items_service
from radd.modules.items.models import WorkItem
from radd.modules.items.schemas import ItemCreate
from radd.modules.items.slq import compile_query, parse
from radd.modules.projects import service as projects_service
from radd.modules.projects.schemas import ProjectCreate
from radd.modules.timelogging import categories
from radd.modules.timelogging.models import Worklog


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
        email=f"rslq-{uuid.uuid4().hex[:8]}@example.com",
        name=name,
        instance_role=InstanceRole.ADMIN.value,
    )
    db.add(user)
    await db.flush()
    return user


async def _run(db, query: str, actor: User) -> set[uuid.UUID]:
    """Compile the SLQ and execute it, returning the matching item ids."""
    compiled = await compile_query(
        db,
        parse(query),
        definitions_by_key={},
        current_user_id=actor.id,
    )
    stmt = select(WorkItem.id)
    if compiled.where is not None:
        stmt = stmt.where(compiled.where)
    return set((await db.execute(stmt)).scalars().all())


async def _two_items(db, actor):
    """Two items through the real service — WorkItem has no `key` column (it is
    derived) and needs a seeded state, so hand-built rows would not survive."""
    project = await projects_service.create_project(
        db, ProjectCreate(key=f"RQ{uuid.uuid4().hex[:4].upper()}", name="Relational SLQ")
    )
    first = await items_service.create_item(
        db, ItemCreate(project_id=project.id, title="Has activity"), actor
    )
    second = await items_service.create_item(
        db, ItemCreate(project_id=project.id, title="Untouched"), actor
    )
    return first, second


async def test_logged_by_matches_only_items_with_that_authors_worklog(db):
    alice = await _user(db, "Alice Logger")
    bob = await _user(db, "Bob Other")
    logged, untouched = await _two_items(db, alice)

    db.add(
        Worklog(
            item_id=logged.id,
            author_id=alice.id,
            time_spent_seconds=3600,
            worked_on=date(2026, 7, 22),
        )
    )
    await db.flush()

    assert await _run(db, "logged_by = me", alice) == {logged.id}
    # `me` is per-actor: the same query run by Bob matches nothing of Alice's.
    assert logged.id not in await _run(db, "logged_by = me", bob)
    # By email and by a substring of the name.
    assert await _run(db, f'logged_by = "{alice.email}"', bob) == {logged.id}
    assert logged.id in await _run(db, "logged_by ~ Logger", bob)
    # Negation is applied by the engine, not the resolver.
    negated = await _run(db, "logged_by != me", alice)
    assert untouched.id in negated and logged.id not in negated


async def test_itemless_worklogs_never_match_logged_by(db):
    """Spec 59 rows have no item, so they cannot name one — the correct answer,
    and the reason the resolver filters `item_id IS NOT NULL` explicitly."""
    alice = await _user(db, "Alice Itemless")
    _, _ = await _two_items(db, alice)
    # ck_worklogs_scope: an itemless row must carry a category, so this is what
    # a real general worklog looks like.
    await categories.ensure_default_categories(db)
    category = (await categories.list_categories(db))[0]
    db.add(
        Worklog(
            item_id=None,
            category_id=category.id,
            author_id=alice.id,
            time_spent_seconds=1800,
            worked_on=date(2026, 7, 22),
        )
    )
    await db.flush()
    assert await _run(db, "logged_by = me", alice) == set()


async def test_commented_by_matches_the_commented_item(db):
    alice = await _user(db, "Alice Commenter")
    bob = await _user(db, "Bob Silent")
    commented, quiet = await _two_items(db, alice)

    db.add(Comment(item_id=commented.id, author_id=alice.id, body="looks good"))
    await db.flush()

    assert await _run(db, "commented_by = me", alice) == {commented.id}
    assert await _run(db, f'commented_by = "{alice.email}"', bob) == {commented.id}
    negated = await _run(db, "commented_by != me", alice)
    assert quiet.id in negated and commented.id not in negated


async def test_relational_fields_compose_with_builtins_and_each_other(db):
    """The whole point of contributing them to the ITEM dialect: they AND with
    builtin fields and with one another like any other term."""
    alice = await _user(db, "Alice Both")
    both, only_logged = await _two_items(db, alice)

    db.add(
        Worklog(
            item_id=both.id,
            author_id=alice.id,
            time_spent_seconds=600,
            worked_on=date(2026, 7, 22),
        )
    )
    db.add(
        Worklog(
            item_id=only_logged.id,
            author_id=alice.id,
            time_spent_seconds=600,
            worked_on=date(2026, 7, 22),
        )
    )
    db.add(Comment(item_id=both.id, author_id=alice.id, body="reviewed"))
    await db.flush()

    assert await _run(db, "logged_by = me AND commented_by = me", alice) == {both.id}
    assert await _run(db, "logged_by = me AND commented_by != me", alice) == {only_logged.id}
