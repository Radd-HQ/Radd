"""Spec 121 §5 (RADD-1147): a public wiki space is the Public role granted to Anyone.

Spec 74's parallel model (`page_spaces.public` + `/public/pages`) is gone. The
world reads a public space through the ORDINARY page routes and resolvers:

- the switch writes/removes one space-scoped grant, and `PageSpaceRead.public`
  is derived from it;
- Anyone lists exactly the public spaces, reads their pages, and 404s on a
  private space's pages — through the same directory and page guards an
  account uses;
- page search for Anyone is scoped to the public spaces;
- flipping the switch off removes the read immediately (no cache).
"""

import uuid

import httpx
import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from radd.config import settings
from radd.exceptions import NotFoundError
from radd.modules.auth import principals, public_access, roles, service as auth
from radd.modules.auth.models import User
from radd.modules.auth.schemas import UserCreate
from radd.modules.auth.types import SESSION_COOKIE_NAME, InstanceRole
from radd.modules.pages import (
    access as pages_access,
    directory as spaces_directory,
    search as pages_search,
    service as docs_service,
    spaces as docs_spaces,
)
from radd.modules.pages.models import PageSpace
from radd.modules.pages.schemas import PageCreate, PageSpaceCreate


@pytest.fixture
async def db():
    engine = create_async_engine(settings.database_url)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as session:
        await roles.ensure_builtin_roles(session)
        await principals.ensure_principals(session)
        yield session
        await session.rollback()
    await engine.dispose()


@pytest.fixture
async def admin(db) -> User:
    return await auth.create_user(
        db,
        UserCreate(
            email=f"kb-{uuid.uuid4().hex[:8]}@example.com",
            name="Public KB Admin",
            password=f"pw-{uuid.uuid4().hex}",
            instance_role=InstanceRole.ADMIN,
        ),
    )


async def _space(db, admin, *, public: bool, name: str) -> PageSpace:
    space = await docs_spaces.create_space(
        db, PageSpaceCreate(name=f"{name} {uuid.uuid4().hex[:6]}"), admin.id
    )
    if public:
        await public_access.set_space_public(db, space.id, public=True, actor_id=admin.id)
    return space


async def _page(db, admin, space, title: str, body: str = "", parent_id=None):
    return await docs_service.create_page(
        db, PageCreate(space_id=space.id, parent_id=parent_id, title=title, body=body), admin.id
    )


def _forget(db, user_id):
    for key in list(db.info):
        if key.startswith("radd."):
            db.info.pop(key)


async def _anyone(db) -> User:
    return await db.get(User, principals.ANYONE_ID)


async def test_the_switch_is_a_grant_and_the_read_is_derived(db, admin):
    space = await _space(db, admin, public=False, name="Handbook")
    assert (await docs_spaces.read_spaces(db, [space]))[0].public is False
    await public_access.set_space_public(db, space.id, public=True, actor_id=admin.id)
    assert (await public_access.spaces_public(db, [space.id]))[space.id] is True
    assert (await docs_spaces.read_spaces(db, [space]))[0].public is True
    await public_access.set_space_public(db, space.id, public=False, actor_id=admin.id)
    assert (await docs_spaces.read_spaces(db, [space]))[0].public is False


async def test_anyone_reads_exactly_the_public_spaces(db, admin):
    public_space = await _space(db, admin, public=True, name="Handbook")
    private_space = await _space(db, admin, public=False, name="Internal")
    anyone = await _anyone(db)
    _forget(db, anyone.id)
    readable = await pages_access.readable_spaces(db, anyone)
    assert public_space.id in readable and private_space.id not in readable
    listed, _total = await spaces_directory.page(db, anyone)
    ids = {row.id for row in listed}
    assert public_space.id in ids and private_space.id not in ids
    with pytest.raises(NotFoundError):
        await spaces_directory.by_identity(db, anyone, str(private_space.id))
    assert (await spaces_directory.by_identity(db, anyone, str(public_space.id))).public is True


async def test_search_for_anyone_is_scoped_to_public_spaces(db, admin):
    term = f"zebra{uuid.uuid4().hex[:6]}"
    public_space = await _space(db, admin, public=True, name="Handbook")
    private_space = await _space(db, admin, public=False, name="Internal")
    public_page = await _page(db, admin, public_space, f"Guide to {term}", "answers")
    await _page(db, admin, private_space, f"Secret {term}", "hidden")
    anyone = await _anyone(db)
    _forget(db, anyone.id)
    readable = set(await pages_access.readable_spaces(db, anyone))
    hits = await pages_search.search_pages(db, term, space_ids=readable)
    assert {hit.page_id for hit in hits} == {public_page.id}


async def test_http_the_world_reads_a_public_space_and_not_a_private_one(db, admin):
    from radd.app import create_app
    from radd.db import get_session

    public_space = await _space(db, admin, public=True, name="Handbook")
    private_space = await _space(db, admin, public=False, name="Internal")
    shown = await _page(db, admin, public_space, "Welcome", "hello world")
    hidden = await _page(db, admin, private_space, "Plans", "not for you")
    admin_cookie = await auth.create_session(db, admin)

    async def session_override():
        yield db

    app = create_app()
    app.dependency_overrides[get_session] = session_override
    transport = httpx.ASGITransport(app=app)
    _forget(db, principals.ANYONE_ID)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        spaces = await client.get("/api/v1/page-spaces")
        assert spaces.status_code == 200, spaces.text
        assert {s["id"] for s in spaces.json()} == {str(public_space.id)}
        assert spaces.json()[0]["public"] is True
        page = await client.get(f"/api/v1/pages/{shown.id}")
        assert page.status_code == 200 and page.json()["body"] == "hello world"
        by_path = await client.get(f"/api/v1/pages/by-path/{public_space.slug}/{shown.slug}")
        assert by_path.status_code == 200
        # The ordinary page guard refuses like it refuses an account without
        # page.read there (403 on the page, 404 on the directory lookup) —
        # existence-hiding for pages is the wiki's own pre-existing contract.
        assert (await client.get(f"/api/v1/pages/{hidden.id}")).status_code in (403, 404)
        assert (await client.get(f"/api/v1/page-spaces/{private_space.id}/pages")).status_code in (403, 404)
        # No parallel surface any more.
        assert (await client.get("/api/v1/public/pages/spaces")).status_code == 404

    # Flip it off through the API as the admin; the world loses it at once.
    async with httpx.AsyncClient(
        transport=transport, base_url="http://test", cookies={SESSION_COOKIE_NAME: admin_cookie}
    ) as client:
        closed = await client.put(
            f"/api/v1/page-spaces/{public_space.id}/public-access", json={"public": False}
        )
        assert closed.status_code == 200 and closed.json()["public"] is False
    _forget(db, principals.ANYONE_ID)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        assert (await client.get(f"/api/v1/pages/{shown.id}")).status_code in (403, 404)
