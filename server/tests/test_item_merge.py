"""RADD-1090 — merge: the target ends holding everything, the source is a
closed tombstone, and nothing is credited to the wrong person.

The first test is the RATCHET (spec 89's lesson, applied to items): every FK
column referencing work_items in the LIVE schema must be claimed by exactly
one disposition in service/merge.py. A module that adds an item-bearing
table and forgets the merge rule fails here, not in production.
"""

import uuid

import pytest
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from radd.config import settings
from radd.exceptions import ConflictError
from radd.modules.auth.models import User
from radd.modules.auth.types import InstanceRole
from radd.modules.comments import service as comments_service
from radd.modules.comments.schemas import CommentCreate
from radd.modules.items import service as items_service
from radd.modules.items.enums import ItemKind
from radd.modules.items.models import ItemLink, WorkItem
from radd.modules.items.schemas import ItemCreate, ItemLinkCreate
from radd.modules.items.service import merge as merge_mod
from radd.modules.projects import service as projects_service
from radd.modules.projects.schemas import ProjectCreate


@pytest.fixture
async def db():
    engine = create_async_engine(settings.database_url)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as session:
        yield session
        await session.rollback()
    await engine.dispose()


async def test_every_item_bearing_fk_has_a_merge_disposition(db):
    """The ratchet. A new FK to work_items must join _REPOINT, _KEEP, or the
    special item_links handling — silence is a failure."""
    rows = await db.execute(
        text(
            """
            SELECT tc.table_name, kcu.column_name
            FROM information_schema.table_constraints tc
            JOIN information_schema.key_column_usage kcu
              ON tc.constraint_name = kcu.constraint_name
            JOIN information_schema.constraint_column_usage ccu
              ON tc.constraint_name = ccu.constraint_name
            WHERE tc.constraint_type = 'FOREIGN KEY'
              AND ccu.table_name = 'work_items'
            """
        )
    )
    live = {(table, column) for table, column in rows}
    claimed = {(spec.table, spec.item_col) for spec in merge_mod._REPOINT}
    claimed |= merge_mod._KEEP
    claimed |= {("item_links", "source_item_id"), ("item_links", "target_item_id")}
    unclaimed = sorted(live - claimed)
    assert not unclaimed, (
        "These columns reference work_items but no merge disposition claims them "
        f"(add to _REPOINT or _KEEP in items/service/merge.py): {unclaimed}"
    )


async def _world(db):
    admin = User(
        email=f"mg-{uuid.uuid4().hex[:8]}@example.com",
        name="Merger",
        instance_role=InstanceRole.ADMIN.value,
    )
    db.add(admin)
    await db.flush()
    project = await projects_service.create_project(
        db, ProjectCreate(key=f"MG{uuid.uuid4().hex[:4].upper()}", name="Merge P"),
        actor_id=admin.id,
    )
    return admin, project


async def test_merge_moves_the_record_and_closes_the_source(db):
    admin, project = await _world(db)
    target = await items_service.create_item(
        db, ItemCreate(project_id=project.id, title="survivor", labels=["keep"]), actor=admin
    )
    source = await items_service.create_item(
        db,
        ItemCreate(project_id=project.id, title="duplicate", labels=["keep", "extra"]),
        actor=admin,
    )
    await items_service.create_item(
        db,
        ItemCreate(
            project_id=project.id, title="dup's step", kind=ItemKind.SUBTASK, parent_id=source.id
        ),
        actor=admin,
    )
    await comments_service.create_comment(
        db, source.id, CommentCreate(body="evidence"), actor=admin
    )
    third = await items_service.create_item(
        db, ItemCreate(project_id=project.id, title="blocked by dup"), actor=admin
    )
    await items_service.add_item_link(
        db, source.id, ItemLinkCreate(target_id=third.id, link_type="blocks"), actor=admin
    )

    merged = await items_service.merge_items(db, source.id, target.id, actor=admin)
    assert merged.id == target.id
    assert sorted(merged.labels) == ["extra", "keep"]  # union

    # comments repointed
    comments = await comments_service.list_comments(db, target.id, actor=admin)
    assert [c.body for c in comments] == ["evidence"]
    # children re-parented
    children = (
        (await db.execute(select(WorkItem).where(WorkItem.parent_id == target.id)))
        .scalars()
        .all()
    )
    assert [c.title for c in children] == ["dup's step"]
    # the outbound blocks link now originates from the target
    links = (
        (await db.execute(select(ItemLink).where(ItemLink.source_item_id == target.id)))
        .scalars()
        .all()
    )
    assert any(l.target_item_id == third.id and l.link_type == "blocks" for l in links)

    # tombstone: canceled category + duplicates link toward the survivor
    tomb = await items_service.get_item(db, source.id, actor=admin)
    assert tomb.state.category == "canceled"
    dup_link = await db.scalar(
        select(ItemLink).where(
            ItemLink.source_item_id == source.id,
            ItemLink.target_item_id == target.id,
            ItemLink.link_type == "duplicates",
        )
    )
    assert dup_link is not None


async def test_merge_preserves_worklog_authorship(db):
    from datetime import date

    from radd.modules.timelogging import enablement, service as timelogging
    from radd.modules.timelogging.schemas import WorklogCreate

    admin, project = await _world(db)
    await enablement.set_enabled(db, project.id, True)
    target = await items_service.create_item(
        db, ItemCreate(project_id=project.id, title="survivor"), actor=admin
    )
    source = await items_service.create_item(
        db, ItemCreate(project_id=project.id, title="duplicate"), actor=admin
    )
    log = await timelogging.create_worklog(
        db,
        source.id,
        WorklogCreate(time_spent="30m", note="real work"),
        author_id=admin.id,
        today=date.today(),
    )
    await items_service.merge_items(db, source.id, target.id, actor=admin)
    moved = await db.execute(
        text("SELECT item_id, author_id, time_spent_seconds FROM worklogs WHERE id = :id"),
        {"id": str(log.id)},
    )
    item_id, author_id, seconds = moved.one()
    assert str(item_id) == str(target.id)
    assert str(author_id) == str(admin.id)  # never re-credited
    assert seconds == 30 * 60


async def test_merge_refuses_kind_mismatch_and_self(db):
    admin, project = await _world(db)
    epic = await items_service.create_item(
        db, ItemCreate(project_id=project.id, title="epic", kind=ItemKind.EPIC), actor=admin
    )
    issue = await items_service.create_item(
        db, ItemCreate(project_id=project.id, title="issue"), actor=admin
    )
    with pytest.raises(ConflictError):
        await items_service.merge_items(db, epic.id, issue.id, actor=admin)
    with pytest.raises(ConflictError):
        await items_service.merge_items(db, issue.id, issue.id, actor=admin)


async def test_watchers_and_stars_dedupe_instead_of_colliding(db):
    admin, project = await _world(db)
    target = await items_service.create_item(
        db, ItemCreate(project_id=project.id, title="survivor"), actor=admin
    )
    source = await items_service.create_item(
        db, ItemCreate(project_id=project.id, title="duplicate"), actor=admin
    )
    for item in (source, target):
        await db.execute(
            text(
                "INSERT INTO item_watchers (item_id, user_id, created_at) "
                "VALUES (:i, :u, now()) ON CONFLICT DO NOTHING"
            ),
            {"i": str(item.id), "u": str(admin.id)},
        )
    await items_service.merge_items(db, source.id, target.id, actor=admin)
    count = await db.scalar(
        text("SELECT count(*) FROM item_watchers WHERE item_id = :i AND user_id = :u"),
        {"i": str(target.id), "u": str(admin.id)},
    )
    assert count == 1


@pytest.mark.parametrize("unrelated", ["source", "target"])
async def test_merge_checks_both_item_relations_before_moving_rows(db, unrelated):
    from radd.exceptions import ForbiddenError
    from radd.modules.auth.scopes import parse_scope

    admin, project = await _world(db)
    source = await items_service.create_item(db, ItemCreate(project_id=project.id, title="source"), actor=admin)
    target = await items_service.create_item(db, ItemCreate(project_id=project.id, title="target"), actor=admin)
    await comments_service.create_comment(db, source.id, CommentCreate(body="must stay"), actor=admin)
    row = await db.get(WorkItem, source.id if unrelated == "source" else target.id)
    row.reporter_id = None
    row.assignee_id = None
    await db.flush()
    admin.token_scope = parse_scope({"global": ["item.read", "item.update@own"]})
    with pytest.raises(ForbiddenError):
        await items_service.merge_items(db, source.id, target.id, actor=admin)
    admin.token_scope = None
    assert [c.body for c in await comments_service.list_comments(db, source.id, actor=admin)] == ["must stay"]
    assert await comments_service.list_comments(db, target.id, actor=admin) == []


async def test_late_merge_refusal_rolls_back_even_when_caller_catches_it(db, monkeypatch):
    from unittest.mock import AsyncMock
    from radd.exceptions import ForbiddenError

    admin, project = await _world(db)
    source = await items_service.create_item(db, ItemCreate(project_id=project.id, title="source"), actor=admin)
    target = await items_service.create_item(db, ItemCreate(project_id=project.id, title="target"), actor=admin)
    await comments_service.create_comment(db, source.id, CommentCreate(body="must stay"), actor=admin)
    monkeypatch.setattr(merge_mod.workflow, "check_transition", AsyncMock(side_effect=ForbiddenError("workflow refused")))
    with pytest.raises(ForbiddenError):
        await items_service.merge_items(db, source.id, target.id, actor=admin)
    # No explicit rollback here: continuing the caller's transaction is safe.
    assert [c.body for c in await comments_service.list_comments(db, source.id, actor=admin)] == ["must stay"]
    assert await comments_service.list_comments(db, target.id, actor=admin) == []
