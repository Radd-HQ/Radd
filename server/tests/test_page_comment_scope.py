"""RADD-1428: a page comment's edit, delete and see-all gates resolve in the
page's SPACE, as its post gate has since RADD-791.

`_require_author_or` asked `authz.require(…, project=project)` — a page's
project is None, which is the GLOBAL scope — for the author's own
`comment.write` and for `project.manage` on someone else's comment, and
`reading.audience` tested `project.manage` for the reader who sees every row.
So a space-scoped author could post a page comment and then not edit it, and a
space's `page.manage` holder could neither edit, delete nor fully read the
discussion they were meant to run. The binding now resolves every comment atom
in its own scope (`CommentParent.require_in_scope`).

The Baseline is emptied throughout, so no floor can make an assertion pass for
the wrong reason (the test_space_scope rule).
"""

import uuid

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from radd.config import settings
from radd.exceptions import ForbiddenError
from radd.modules.auth import authz, grants, roles as roles_service
from radd.modules.auth.models import Role, User
from radd.modules.auth.schemas import RoleCreate
from radd.modules.auth.types import BuiltinRoleKey, InstanceRole, Permission
from radd.modules.comments import service as comments_service
from radd.modules.comments.schemas import CommentCreate, CommentUpdate
from radd.modules.comments.types import CommentParentType, CommentVisibility
from radd.modules.pages import service as pages_service, spaces
from radd.modules.pages.schemas import PageCreate, PageSpaceCreate

_SYSTEM_ACTOR = uuid.UUID("00000000-0000-0000-0000-0000000a7a70")
PAGE = CommentParentType.PAGE.value
#: The Baseline's own-comment delete grant (RADD-816), re-granted per space
#: here because the floor is emptied.
DELETE_OWN = f"{Permission.COMMENT_DELETE}@own"


@pytest.fixture
async def db():
    engine = create_async_engine(settings.database_url)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as session:
        baseline = (
            await session.execute(select(Role).where(Role.key == BuiltinRoleKey.BASELINE.value))
        ).scalar_one()
        baseline.permissions = []
        authz.forget_baseline(session)
        yield session
        await session.rollback()
    await engine.dispose()


async def _user(db, name: str, role: InstanceRole = InstanceRole.MEMBER) -> User:
    user = User(
        email=f"pcs-{uuid.uuid4().hex[:8]}@example.com",
        name=name,
        instance_role=role.value,
    )
    db.add(user)
    await db.flush()
    return user


async def _space(db, name: str):
    return await spaces.create_space(
        db, PageSpaceCreate(name=name, slug=f"{name.lower()}-{uuid.uuid4().hex[:6]}"), _SYSTEM_ACTOR
    )


async def _page(db, space):
    """Written by an admin: who authored the page is not what any test here asserts."""
    admin = await _user(db, "Admin", InstanceRole.ADMIN)
    return await pages_service.create_page(
        db, PageCreate(space_id=space.id, title="Runbook", body="body"), admin.id
    )


async def _grant_in(db, space, user: User, *permissions: str, name: str) -> None:
    role = await roles_service.create_role(
        db, RoleCreate(key=f"pcs-{uuid.uuid4().hex[:8]}", name=name, permissions=list(permissions))
    )
    await grants.create_grant(db, role.id, user_id=user.id, space_id=space.id)


WRITER = (str(Permission.PAGE_READ), str(Permission.COMMENT_WRITE), DELETE_OWN)
MANAGER = (
    str(Permission.PAGE_READ),
    str(Permission.COMMENT_WRITE),
    str(Permission.COMMENT_DELETE),
    str(Permission.PAGE_MANAGE),
)


@pytest.fixture
async def world(db):
    space = await _space(db, "Ops")
    page = await _page(db, space)
    author, peer, manager = await _user(db, "Author"), await _user(db, "Peer"), await _user(db, "Manager")
    await _grant_in(db, space, author, *WRITER, name="Space writer")
    await _grant_in(db, space, peer, *WRITER, name="Space writer")
    await _grant_in(db, space, manager, *MANAGER, name="Space manager")
    comment = await comments_service.create_comment(
        db, page.id, CommentCreate(body="first draft"), author, entity_type=PAGE
    )
    return db, space, page, author, peer, manager, comment


async def test_a_space_scoped_author_edits_their_own_page_comment(world):
    db, _s, _p, author, _peer, _manager, comment = world
    edited = await comments_service.update_comment(
        db, comment.id, CommentUpdate(body="second draft"), author
    )
    assert edited.body == "second draft"


async def test_a_space_manager_edits_and_deletes_someone_elses_comment(world):
    db, _s, page, _author, _peer, manager, comment = world
    edited = await comments_service.update_comment(
        db, comment.id, CommentUpdate(body="tidied by the space manager"), manager
    )
    assert edited.body == "tidied by the space manager"
    await comments_service.delete_comment(db, comment.id, manager)
    assert await comments_service.list_comments(db, page.id, manager, entity_type=PAGE) == []


async def test_a_peer_writer_may_neither_edit_nor_delete_it(world):
    db, _s, _p, _author, peer, _manager, comment = world
    with pytest.raises(ForbiddenError):
        await comments_service.update_comment(db, comment.id, CommentUpdate(body="mine now"), peer)
    with pytest.raises(ForbiddenError):
        await comments_service.delete_comment(db, comment.id, peer)


async def test_the_author_deletes_their_own_through_the_own_grant(world):
    db, _s, page, author, _peer, _manager, comment = world
    await comments_service.delete_comment(db, comment.id, author)
    assert await comments_service.list_comments(db, page.id, author, entity_type=PAGE) == []


async def test_a_manager_of_another_space_manages_nothing_here(world):
    """The boundary that makes the scope real: `page.manage` next door is not
    `page.manage` here — and certainly not the global atom it used to need."""
    db, _s, _p, _author, _peer, _manager, comment = world
    elsewhere = await _space(db, "Elsewhere")
    outsider = await _user(db, "Other space's manager")
    await _grant_in(db, elsewhere, outsider, *MANAGER, name="Space manager")
    with pytest.raises(ForbiddenError):
        await comments_service.update_comment(db, comment.id, CommentUpdate(body="no"), outsider)


async def test_a_space_manager_reads_every_row_of_the_discussion(db):
    """`reading.audience` answers None (no filter) for the PARENT's manager.
    A space manager without `comment.read_internal` still sees an internal
    page comment, exactly as a project manager sees an internal issue comment."""
    space = await _space(db, "Internal")
    page = await _page(db, space)
    insider = await _user(db, "Insider")
    manager = await _user(db, "Manager")
    reader = await _user(db, "Reader")
    await _grant_in(
        db, space, insider,
        str(Permission.PAGE_READ), str(Permission.COMMENT_WRITE), str(Permission.COMMENT_READ_INTERNAL),
        name="Insider",
    )
    await _grant_in(db, space, manager, str(Permission.PAGE_READ), str(Permission.PAGE_MANAGE), name="Manager")
    await _grant_in(db, space, reader, str(Permission.PAGE_READ), name="Reader")
    await comments_service.create_comment(
        db, page.id,
        CommentCreate(body="team-only note", visibility=CommentVisibility.INTERNAL),
        insider, entity_type=PAGE,
    )

    seen_by = lambda actor: comments_service.list_comments(db, page.id, actor, entity_type=PAGE)  # noqa: E731
    assert [c.body for c in await seen_by(manager)] == ["team-only note"]
    assert await seen_by(reader) == []
