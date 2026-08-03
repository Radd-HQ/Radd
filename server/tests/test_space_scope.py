"""A wiki space is a grant scope, the way a project is (RADD-791).

Before this, every `page.*` atom was checked at GLOBAL scope, because a page had
no scope to be checked against. Two consequences, both under test here:

  - Per-space access was inexpressible. "Let the render team read the render
    space" had no way to be said.
  - Page COMMENTING was dead for the people it exists for. The comments binding
    resolved `comment.write` with `project=None`, and `comment.write` is a
    project-scoped atom, so a project-scoped grant never reached it. The gate
    looked correct and behaved like a refusal for everyone but an admin.

The Baseline is emptied throughout, because a floor holding `page.read` would
make every assertion below pass for the wrong reason — the exact vacuous-pass
this whole wave exists to remove.
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
from radd.modules.comments.schemas import CommentCreate
from radd.modules.comments.types import CommentParentType
from radd.modules.pages import access as pages_access, service as pages_service, spaces
from radd.modules.pages.schemas import PageCreate, PageSpaceCreate
from radd.modules.teams import service as teams_service
from radd.modules.teams.schemas import TeamCreate


#: Spaces are created by an admin in every scenario here; who created them is
#: not what any of these assert.
_SYSTEM_ACTOR = uuid.UUID("00000000-0000-0000-0000-0000000a7a70")


@pytest.fixture
async def db():
    engine = create_async_engine(settings.database_url)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as session:
        # Fail closed, so nothing below can pass on a permissive floor.
        baseline = (
            await session.execute(
                select(Role).where(Role.key == BuiltinRoleKey.BASELINE.value)
            )
        ).scalar_one()
        baseline.permissions = []
        authz.forget_baseline(session)
        yield session
        await session.rollback()
    await engine.dispose()


async def _user(db, name="Reader") -> User:
    user = User(
        email=f"space-{uuid.uuid4().hex[:8]}@example.com",
        name=name,
        instance_role=InstanceRole.MEMBER.value,
    )
    db.add(user)
    await db.flush()
    return user


async def _space(db, name: str):
    slug = "".join(c if c.isalnum() else "-" for c in name.lower())
    return await spaces.create_space(
        db, PageSpaceCreate(name=name, slug=f"{slug}-{uuid.uuid4().hex[:6]}"), _SYSTEM_ACTOR
    )


async def _page(db, space, actor, title="A page"):
    return await pages_service.create_page(
        db, PageCreate(space_id=space.id, title=title, body="body"), actor.id
    )


async def _role(db, *permissions, name="Space role"):
    return await roles_service.create_role(
        db,
        RoleCreate(
            key=f"sp-{uuid.uuid4().hex[:8]}",
            name=name,
            permissions=[str(p) for p in permissions],
        ),
    )


async def test_a_space_grant_reaches_its_space_and_no_other(db):
    render = await _space(db, "Render")
    pipeline = await _space(db, "Pipeline")
    user = await _user(db)
    role = await _role(db, Permission.PAGE_READ)

    assert Permission.PAGE_READ not in await pages_access.space_permissions(db, user, render.id)

    await grants.create_grant(db, role.id, user_id=user.id, space_id=render.id)

    assert Permission.PAGE_READ in await pages_access.space_permissions(db, user, render.id)
    # The boundary is the point: a grant on one space says nothing about another.
    assert Permission.PAGE_READ not in await pages_access.space_permissions(
        db, user, pipeline.id
    )
    assert set(await pages_access.readable_spaces(db, user)) == {render.id}


async def test_read_only_and_writable_spaces_are_different_grants(db):
    """"Read-only space" falls out of ordinary roles — no new vocabulary."""
    space = await _space(db, "Handbook")
    reader, editor = await _user(db, "Reader"), await _user(db, "Editor")
    read_role = await _role(db, Permission.PAGE_READ, name="Space reader")
    write_role = await _role(db, Permission.PAGE_READ, Permission.PAGE_WRITE, name="Space editor")

    await grants.create_grant(db, read_role.id, user_id=reader.id, space_id=space.id)
    await grants.create_grant(db, write_role.id, user_id=editor.id, space_id=space.id)

    reader_held = await pages_access.space_permissions(db, reader, space.id)
    editor_held = await pages_access.space_permissions(db, editor, space.id)
    assert Permission.PAGE_READ in reader_held
    assert Permission.PAGE_WRITE not in reader_held
    assert Permission.PAGE_WRITE in editor_held


async def test_a_space_grant_reaches_a_team(db):
    """Grants are subject-agnostic: the team path is the same path."""
    space = await _space(db, "Team space")
    user = await _user(db)
    team = await teams_service.create_team(db, TeamCreate(name=f"T{uuid.uuid4().hex[:6]}"))
    await teams_service.add_team_member(db, team.id, user.id)
    role = await _role(db, Permission.PAGE_READ)

    await grants.create_grant(db, role.id, team_id=team.id, space_id=space.id)

    assert Permission.PAGE_READ in await pages_access.space_permissions(db, user, space.id)


async def test_a_commenter_can_comment_on_a_page_in_their_space(db):
    """The bug this scope exists to fix. `comment.write` is project-scoped, so
    resolving it globally meant a scoped grant never reached a page — page
    discussion was refused for everyone but an admin."""
    space = await _space(db, "Discussable")
    author = await _user(db, "Author")
    page = await _page(db, space, author)
    role = await _role(db, Permission.PAGE_READ, Permission.COMMENT_WRITE)
    await grants.create_grant(db, role.id, user_id=author.id, space_id=space.id)

    comment = await comments_service.create_comment(
        db,
        page.id,
        CommentCreate(body="I disagree, and here is why"),
        author,
        entity_type=CommentParentType.PAGE.value,
    )
    assert comment.id is not None


async def test_commenting_needs_the_grant(db):
    """...and the fix is not a hole: no grant, no comment."""
    space = await _space(db, "Closed")
    admin = User(
        email=f"adm-{uuid.uuid4().hex[:8]}@example.com",
        name="Admin",
        instance_role=InstanceRole.ADMIN.value,
    )
    db.add(admin)
    await db.flush()
    page = await _page(db, space, admin)
    outsider = await _user(db, "Outsider")

    with pytest.raises(ForbiddenError):
        await comments_service.create_comment(
            db,
            page.id,
            CommentCreate(body="let me in"),
            outsider,
            entity_type=CommentParentType.PAGE.value,
        )


async def test_an_unscoped_grant_still_applies_everywhere(db):
    """A grant with no scope is instance-wide, unchanged — the wiki-wide role an
    admin hands to a technical writer still covers every space."""
    render = await _space(db, "Render")
    pipeline = await _space(db, "Pipeline")
    user = await _user(db)
    role = await _role(db, Permission.PAGE_READ, Permission.PAGE_WRITE)

    await grants.create_grant(db, role.id, user_id=user.id)

    for space in (render, pipeline):
        held = await pages_access.space_permissions(db, user, space.id)
        assert Permission.PAGE_WRITE in held
    assert set(await pages_access.readable_spaces(db, user)) == {render.id, pipeline.id}


async def test_a_grant_carries_at_most_one_scope(db):
    """Project AND space would be an unanswerable question, so it is refused at
    the seam rather than stored and resolved by guesswork."""
    from radd.exceptions import ConflictError
    from radd.modules.projects import service as projects_service
    from radd.modules.projects.schemas import ProjectCreate

    space = await _space(db, "Both")
    project = await projects_service.create_project(
        db, ProjectCreate(key=f"BO{uuid.uuid4().hex[:4].upper()}", name="Both")
    )
    user = await _user(db)
    role = await _role(db, Permission.PAGE_READ)

    with pytest.raises(ConflictError):
        await grants.create_grant(
            db, role.id, user_id=user.id, project_id=project.id, space_id=space.id
        )


async def test_batched_space_permissions_match_the_single_lookup(db):
    """`permissions_by_space` is an optimisation, so it has to agree with the
    thing it optimises — a batch that drifts from `effective_permissions` would
    show a wiki nav that disagrees with what opening the space does."""
    spaces_made = [await _space(db, f"S{i}") for i in range(3)]
    user = await _user(db)
    role = await _role(db, Permission.PAGE_READ, Permission.PAGE_WRITE)
    await grants.create_grant(db, role.id, user_id=user.id, space_id=spaces_made[1].id)

    batched = await pages_access.permissions_by_space(
        db, user, [s.id for s in spaces_made]
    )
    for space in spaces_made:
        assert batched[space.id] == await pages_access.space_permissions(db, user, space.id)
