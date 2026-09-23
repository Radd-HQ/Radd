"""RADD-1297 — a link to one comment lands on that comment.

`through` widens the newest window just far enough to include an old comment;
`locate` names the thread a reply belongs to and answers a comment the reader
cannot see exactly like one that does not exist; notifications carry the
comment, and their links land on it.
"""

import uuid
from datetime import datetime, timedelta

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from radd import mailrender
from radd.config import settings
from radd.exceptions import NotFoundError
from radd.modules.auth.models import User
from radd.modules.comments import service
from radd.modules.comments.models import Comment
from radd.modules.items import service as items
from radd.modules.items.schemas import ItemCreate
from radd.modules.notify import lines, planner
from radd.modules.notify.models import Notification
from radd.modules.notify.types import NotificationType
from radd.modules.projects import service as projects
from radd.modules.projects.schemas import ProjectCreate


@pytest.fixture
async def world():
    engine = create_async_engine(settings.database_url)
    async with async_sessionmaker(engine, expire_on_commit=False)() as db:
        admin = User(email=f"cl-{uuid.uuid4().hex[:8]}@example.com", name="Admin", instance_role="admin")
        stranger = User(email=f"cl-{uuid.uuid4().hex[:8]}@example.com", name="Stranger", instance_role="member")
        db.add_all([admin, stranger])
        await db.flush()
        project = await projects.create_project(
            db, ProjectCreate(key=f"CL{uuid.uuid4().hex[:4].upper()}", name="Links"), actor_id=admin.id
        )
        item = await items.create_item(db, ItemCreate(project_id=project.id, title="Long thread"), actor=admin)
        start = datetime(2026, 1, 1)
        rows = []
        for i in range(130):
            row = Comment(entity_type="item", entity_id=item.id, author_id=admin.id, body=f"c{i}",
                          visibility="public", created_at=start + timedelta(minutes=i),
                          updated_at=start + timedelta(minutes=i))
            db.add(row)
            rows.append(row)
        await db.flush()
        yield db, admin, stranger, item, rows
        await db.rollback()
    await engine.dispose()


async def test_through_widens_the_window_to_an_old_comment(world):
    db, admin, _stranger, item, rows = world
    plain = await service.comment_page(db, item.id, admin, limit=50)
    assert rows[4].id not in {c.id for c in plain.comments}  # 126th newest: not in view

    linked = await service.comment_page(db, item.id, admin, limit=50, through=rows[4].id)
    ids = [c.id for c in linked.comments]
    assert ids[0] == rows[4].id  # exactly far enough: the linked one is the oldest shown
    assert len(ids) == 126 and linked.older_cursor  # and the older four are still pageable


async def test_through_a_comment_elsewhere_changes_nothing(world):
    db, admin, _stranger, item, _rows = world
    other = await items.create_item(db, ItemCreate(project_id=item.project_id, title="Other"), actor=admin)
    foreign = Comment(entity_type="item", entity_id=other.id, author_id=admin.id, body="x", visibility="public")
    db.add(foreign)
    await db.flush()
    page = await service.comment_page(db, item.id, admin, limit=50, through=foreign.id)
    assert len(page.comments) == 50


async def test_locate_names_a_replys_thread_and_hides_the_unreadable(world):
    db, admin, stranger, item, rows = world
    reply = Comment(entity_type="item", entity_id=item.id, author_id=admin.id, body="reply",
                    visibility="public", parent_comment_id=rows[10].id)
    db.add(reply)
    await db.flush()
    where = await service.locate(db, reply.id, admin)
    assert (where.root_id, where.entity_id, where.anchored) == (rows[10].id, item.id, False)

    # A stranger holds no read on the project: the same 404 as a comment that never existed.
    with pytest.raises(NotFoundError):
        await service.locate(db, reply.id, stranger)
    with pytest.raises(NotFoundError):
        await service.locate(db, uuid.uuid4(), admin)


def test_notifications_carry_the_comment_and_link_to_it():
    plan = planner.plan_comment_created(
        {"excerpt": "hi"}, uuid.uuid4(), planner.Audience(), frozenset({uuid.uuid4()}), comment_id="c-1"
    )
    assert plan.notifications and all(n.detail.get("comment_id") == "c-1" for n in plan.notifications)

    issue = Notification(type=NotificationType.COMMENTED.value,
                         payload={"item_key": "TD-1", "item_title": "T", "comment_id": "c-1"})
    assert lines.entry(issue, {}).url.endswith("/issues/TD-1?comment=c-1")
    page = Notification(type=NotificationType.COMMENTED.value,
                        payload={"page_number": 42, "title": "Runbook", "comment_id": "c-2"})
    assert lines.entry(page, {}).url.endswith("/pages?pageId=42&comment=c-2")
    assert mailrender.ItemMail(key="TD-1", title="T", base_url="https://x", comment="c-1").url == (
        "https://x/issues/TD-1?comment=c-1"
    )
