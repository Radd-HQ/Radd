"""A page can be restricted individually, the way a field can (RADD-792).

The space decides the default (RADD-791); a page grant can only ever NARROW
within it. The rule that makes the space boundary real rather than advisory is
the one asserted last here: a page grant naming someone with no access to the
space grants them nothing at all.

The Baseline is emptied throughout — a floor holding `page.read` would make
every "cannot see it" assertion pass for the wrong reason.
"""

import uuid

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from radd.config import settings
from radd.modules.access import service as access_service
from radd.modules.access.types import Access, GrantSubject
from radd.modules.auth import authz, grants as role_grants, roles as roles_service
from radd.modules.auth.models import Role, User
from radd.modules.auth.schemas import RoleCreate
from radd.modules.auth.types import BuiltinRoleKey, InstanceRole, Permission
from radd.modules.pages import (
    page_access,
    search as pages_search,
    service as pages_service,
    spaces,
)
from radd.modules.pages.page_access import PAGE_RESOURCE
from radd.modules.pages.schemas import PageCreate, PageSpaceCreate

async def _admin(db) -> User:
    """A real row: `pages.created_by` has an FK, and who authored a page is not
    what any of these assert."""
    admin = User(
        email=f"adm-{uuid.uuid4().hex[:8]}@example.com",
        name="Admin",
        instance_role=InstanceRole.ADMIN.value,
    )
    db.add(admin)
    await db.flush()
    return admin


@pytest.fixture
async def db():
    engine = create_async_engine(settings.database_url)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as session:
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


async def _user(db, name="Member") -> User:
    user = User(
        email=f"pr-{uuid.uuid4().hex[:8]}@example.com",
        name=name,
        instance_role=InstanceRole.MEMBER.value,
    )
    db.add(user)
    await db.flush()
    return user


async def _space(db, actor, name="Handbook"):
    return await spaces.create_space(
        db,
        PageSpaceCreate(name=name, slug=f"{name.lower()}-{uuid.uuid4().hex[:6]}"),
        actor.id,
    )


async def _page(db, space, actor, title="Salary bands"):
    return await pages_service.create_page(
        db, PageCreate(space_id=space.id, title=title, body="numbers"), actor.id
    )


async def _grant_space_read(db, user, space, *extra):
    role = await roles_service.create_role(
        db,
        RoleCreate(
            key=f"pr-{uuid.uuid4().hex[:8]}",
            name="Space reader",
            permissions=[str(Permission.PAGE_READ), *(str(p) for p in extra)],
        ),
    )
    await role_grants.create_grant(db, role.id, user_id=user.id, space_id=space.id)


async def _restrict(db, page, actor, *, user_id=None, role_id=None):
    """Name somebody on the page — which closes it to everyone else."""
    return await access_service.add_grant(
        db,
        PAGE_RESOURCE,
        str(page.id),
        subject_type=GrantSubject.ROLE if role_id else GrantSubject.USER,
        subject_id=role_id or user_id,
        access=Access.READ.value,
        actor_id=actor.id,
    )


async def test_an_unrestricted_page_follows_its_space(db):
    admin = await _admin(db)
    space = await _space(db, admin)
    page = await _page(db, space, admin)
    reader = await _user(db)
    await _grant_space_read(db, reader, space)

    assert await page_access.page_access(db, reader, page)


async def test_a_restriction_closes_the_page_to_everyone_else(db):
    admin = await _admin(db)
    space = await _space(db, admin)
    page = await _page(db, space, admin)
    insider, outsider = await _user(db, "Insider"), await _user(db, "Outsider")
    for person in (insider, outsider):
        await _grant_space_read(db, person, space)

    # Both can read it while it is unrestricted...
    assert await page_access.page_access(db, insider, page)
    assert await page_access.page_access(db, outsider, page)

    await _restrict(db, page, admin, user_id=insider.id)

    # ...and naming one person closes it to the other.
    assert await page_access.page_access(db, insider, page)
    assert not await page_access.page_access(db, outsider, page)


async def test_a_page_grant_cannot_widen_past_the_space(db):
    """The rule that makes the space boundary real. Otherwise "restrict this
    page" would double as a way to hand out access to a space you were never
    given."""
    admin = await _admin(db)
    space = await _space(db, admin)
    page = await _page(db, space, admin)
    stranger = await _user(db, "Stranger")  # no space grant at all

    await _restrict(db, page, admin, user_id=stranger.id)

    assert not await page_access.page_access(db, stranger, page)


async def test_the_page_tree_drops_restricted_pages(db):
    admin = await _admin(db)
    space = await _space(db, admin)
    open_page = await _page(db, space, admin, title="Onboarding")
    closed_page = await _page(db, space, admin, title="Salary bands")
    insider, outsider = await _user(db, "Insider"), await _user(db, "Outsider")
    for person in (insider, outsider):
        await _grant_space_read(db, person, space)
    await _restrict(db, closed_page, admin, user_id=insider.id)

    outsider_tree = await pages_service.list_pages(db, space.id, actor=outsider)
    insider_tree = await pages_service.list_pages(db, space.id, actor=insider)

    assert {row.id for row in outsider_tree} == {open_page.id}
    assert {row.id for row in insider_tree} == {open_page.id, closed_page.id}


async def test_search_does_not_leak_a_restricted_title(db):
    """The title IS usually the sensitive part, so a hit defeats the restriction
    on its own."""
    admin = await _admin(db)
    space = await _space(db, admin)
    page = await _page(db, space, admin, title="Zorblatt compensation matrix")
    insider, outsider = await _user(db, "Insider"), await _user(db, "Outsider")
    for person in (insider, outsider):
        await _grant_space_read(db, person, space)
    await _restrict(db, page, admin, user_id=insider.id)

    hits = await pages_search.search_pages(db, "Zorblatt", limit=10)
    assert page.id in {hit.page_id for hit in hits}, "fixture: the page must be findable"

    for_outsider = await pages_service.drop_restricted_results(db, outsider, hits)
    for_insider = await pages_service.drop_restricted_results(db, insider, hits)
    assert page.id not in {hit.page_id for hit in for_outsider}
    assert page.id in {hit.page_id for hit in for_insider}


async def test_a_role_subject_grant_resolves_in_the_space(db):
    """A grant naming a ROLE means the people who hold that role HERE."""
    admin = await _admin(db)
    space = await _space(db, admin)
    page = await _page(db, space, admin)
    holder, other = await _user(db, "Holder"), await _user(db, "Other")
    for person in (holder, other):
        await _grant_space_read(db, person, space)

    hr_role = await roles_service.create_role(
        db,
        RoleCreate(
            key=f"hr-{uuid.uuid4().hex[:8]}", name="HR", permissions=[str(Permission.PAGE_READ)]
        ),
    )
    await role_grants.create_grant(db, hr_role.id, user_id=holder.id, space_id=space.id)
    await _restrict(db, page, admin, role_id=hr_role.id)

    assert await page_access.page_access(db, holder, page)
    assert not await page_access.page_access(db, other, page)


async def test_batched_and_single_answers_agree(db):
    """`readable_page_ids` is the batch behind every list surface; if it drifted
    from `page_access` the tree would disagree with what opening a page does."""
    admin = await _admin(db)
    space = await _space(db, admin)
    pages = [await _page(db, space, admin, title=f"P{i}") for i in range(4)]
    reader = await _user(db)
    await _grant_space_read(db, reader, space)
    await _restrict(db, pages[2], admin, user_id=admin.id)

    batched = await page_access.readable_page_ids(db, reader, pages)
    for page in pages:
        assert (page.id in batched) == await page_access.page_access(db, reader, page)
