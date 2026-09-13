"""Spec 121 §3 (RADD-1143): public / internal / restricted, and every surface agrees.

One project holding one issue of each level; six actors; list, count, search
and get must answer the same set for each. The matrix IS the specification:

| actor                                   | public | internal | restricted |
|-----------------------------------------|--------|----------|------------|
| the world (Anyone, `item.read@public`)  | yes    | no       | no         |
| a member (unqualified `item.read`)      | yes    | yes      | no         |
| the reporter of the restricted issue    | yes    | yes      | yes        |
| a project manager not on it             | yes    | yes      | no         |
| an instance admin                       | yes    | yes      | yes        |
| a `@own`-only reader who reported none  | yes*   | no       | no         |

* the project is public, so the world's `item.read@public` reaches every
  account too — an `@own` grant adds nothing on top for someone who reported
  nothing.
"""

import uuid

import httpx
import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from radd.config import settings as config
from radd.exceptions import ConflictError
from radd.modules.auth import grants, principals, roles, service as auth
from radd.modules.auth.models import Role, User
from radd.modules.auth.schemas import UserCreate
from radd.modules.auth.types import SESSION_COOKIE_NAME, BuiltinRoleKey, InstanceRole
from radd.modules.items import service as items
from radd.modules.items.enums import ItemVisibility
from radd.modules.items.schemas import ItemCreate, ItemUpdate
from radd.modules.projects import service as projects
from radd.modules.projects.schemas import ProjectCreate


@pytest.fixture
async def db():
    engine = create_async_engine(config.database_url)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as session:
        await roles.ensure_builtin_roles(session)
        await principals.ensure_principals(session)
        yield session
        await session.rollback()
    await engine.dispose()


async def _person(db, name: str, *, role: InstanceRole = InstanceRole.MEMBER) -> User:
    return await auth.create_user(
        db,
        UserCreate(
            email=f"{name}-{uuid.uuid4().hex[:8]}@people.example.com",
            name=name,
            password=f"pw-{uuid.uuid4().hex}",
            instance_role=role,
        ),
    )


async def _role(db, key: str, permissions: list[str]) -> Role:
    role = Role(key=f"{key}-{uuid.uuid4().hex[:6]}", name=key, permissions=permissions)
    db.add(role)
    await db.flush()
    return role


async def _grant(db, role_id, user_id, project):
    await grants.create_grant(db, role_id=role_id, user_id=user_id, project_id=project.id)


def _forget(db, *user_ids):
    for user_id in user_ids:
        db.info.pop(f"radd.project_permission_map:{user_id}", None)
        db.info.pop(f"radd.readable_projects:{user_id}", None)


@pytest.fixture
async def world(db):
    """The fixture the whole matrix runs against."""
    admin = await _person(db, "admin", role=InstanceRole.ADMIN)
    member = await _person(db, "member")
    reporter = await _person(db, "reporter")
    manager = await _person(db, "manager")
    own_only = await _person(db, "own-only")
    project = await projects.create_project(
        db, ProjectCreate(key=f"V{uuid.uuid4().hex[:6].upper()}", name="Visibility")
    )
    public_role = await roles.role_by_key(db, BuiltinRoleKey.PUBLIC.value)
    await _grant(db, public_role.id, principals.ANYONE_ID, project)
    reader = await _role(db, "reader", ["item.read", "item.create", "item.update"])
    own = await _role(db, "own", ["item.read@own"])
    manage = await _role(db, "manage", ["item.read", "project.manage"])
    await _grant(db, reader.id, member.id, project)
    await _grant(db, reader.id, reporter.id, project)
    await _grant(db, manage.id, manager.id, project)
    await _grant(db, own.id, own_only.id, project)
    rows = {}
    for level in ItemVisibility:
        created = await items.create_item(
            db,
            ItemCreate(project_id=project.id, title=f"{level.value} issue", visibility=level),
            reporter,
        )
        rows[level] = created
    anyone = await db.get(User, principals.ANYONE_ID)
    return {
        "project": project,
        "rows": rows,
        "actors": {
            "world": anyone,
            "member": member,
            "reporter": reporter,
            "manager": manager,
            "admin": admin,
            "own_only": own_only,
        },
    }


EXPECTED = {
    "world": {ItemVisibility.PUBLIC},
    "member": {ItemVisibility.PUBLIC, ItemVisibility.INTERNAL},
    "reporter": {ItemVisibility.PUBLIC, ItemVisibility.INTERNAL, ItemVisibility.RESTRICTED},
    "manager": {ItemVisibility.PUBLIC, ItemVisibility.INTERNAL},
    "admin": {ItemVisibility.PUBLIC, ItemVisibility.INTERNAL, ItemVisibility.RESTRICTED},
    "own_only": {ItemVisibility.PUBLIC},
}


@pytest.mark.parametrize("who", sorted(EXPECTED))
async def test_list_count_and_get_agree(db, world, who):
    from radd.modules.items.filters import ItemListFilters
    from radd.modules.items.service.scope import visible_ids_query
    from radd.exceptions import ForbiddenError, NotFoundError

    project, rows, actor = world["project"], world["rows"], world["actors"][who]
    expected = {rows[level].id for level in EXPECTED[who]}
    _forget(db, actor.id)

    listed = await items.list_items(
        db, actor=actor, filters=ItemListFilters(project_id=project.id), limit=50, offset=0
    )
    assert {i.id for i in listed} == expected, f"list for {who}"

    query, _ = await visible_ids_query(
        db, actor=actor, filters=ItemListFilters(project_id=project.id), q=None
    )
    ids = set((await db.execute(query)).scalars())
    assert ids == expected, f"ids/count for {who}"

    for level, read in rows.items():
        if level in EXPECTED[who]:
            assert (await items.get_item(db, read.id, actor)).id == read.id, f"get {level} for {who}"
        else:
            with pytest.raises((NotFoundError, ForbiddenError)):
                await items.get_item(db, read.id, actor)


async def test_search_index_agrees(db, world):
    """The mirror carries visibility; the guard compiles over it."""
    from sqlalchemy import select

    from radd.modules.events.models import Event
    from radd.modules.search import indexer, service as search
    from radd.modules.search.models import SearchIndexRow

    project, rows = world["project"], world["rows"]
    # The indexer is an outbox consumer; feed it the fixture's own item.created
    # events so the mirror carries what the payload says (visibility included).
    events = (
        await db.execute(
            select(Event).where(Event.entity_id.in_([str(r.id) for r in rows.values()]))
        )
    ).scalars()
    for event in events:
        await indexer._index_item(db, event)
    await indexer.sync_relation_columns(db)
    for who, levels in EXPECTED.items():
        actor = world["actors"][who]
        _forget(db, actor.id)
        clause = await search._relation_index_clause(db, actor)
        readable = await search.readable_project_ids(db, actor)
        if project.id not in readable:
            assert not levels, who
            continue
        stmt = select(SearchIndexRow.item_id).where(SearchIndexRow.project_id == project.id)
        if clause is not None:
            stmt = stmt.where(clause)
        found = set((await db.execute(stmt)).scalars())
        assert found == {rows[level].id for level in levels}, f"search for {who}"


async def test_default_visibility_follows_the_project_setting(db, world):
    from radd.modules.settings import service as settings_service
    from radd.modules.settings.types import SettingKey, SettingScope

    project, reporter = world["project"], world["actors"]["reporter"]
    await settings_service.set_value(
        db, SettingKey.ITEM_DEFAULT_VISIBILITY, SettingScope.PROJECT, project.id,
        ItemVisibility.RESTRICTED.value,
    )
    created = await items.create_item(db, ItemCreate(project_id=project.id, title="HR"), reporter)
    assert created.visibility is ItemVisibility.RESTRICTED
    explicit = await items.create_item(
        db, ItemCreate(project_id=project.id, title="Open", visibility=ItemVisibility.PUBLIC), reporter
    )
    assert explicit.visibility is ItemVisibility.PUBLIC


async def test_a_change_that_would_lock_you_out_is_refused(db, world):
    rows, member = world["rows"], world["actors"]["member"]
    public = rows[ItemVisibility.PUBLIC]
    with pytest.raises(ConflictError, match="hide this issue from you"):
        await items.update_item(db, public.id, ItemUpdate(visibility=ItemVisibility.RESTRICTED), member)
    # …but the reporter may, and the admin may on anyone's behalf.
    reporter, admin = world["actors"]["reporter"], world["actors"]["admin"]
    updated = await items.update_item(
        db, public.id, ItemUpdate(visibility=ItemVisibility.RESTRICTED), reporter
    )
    assert updated.visibility is ItemVisibility.RESTRICTED
    back = await items.update_item(db, public.id, ItemUpdate(visibility=ItemVisibility.INTERNAL), admin)
    assert back.visibility is ItemVisibility.INTERNAL


async def test_http_world_sees_public_rows_only(db, world):
    from radd.app import create_app
    from radd.db import get_session

    project, rows = world["project"], world["rows"]
    member = world["actors"]["member"]
    cookie = await auth.create_session(db, member)

    async def session_override():
        yield db

    app = create_app()
    app.dependency_overrides[get_session] = session_override
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        listed = await client.get("/api/v1/items", params={"project_id": str(project.id)})
        assert listed.status_code == 200, listed.text
        assert {i["id"] for i in listed.json()} == {str(rows[ItemVisibility.PUBLIC].id)}
        counted = await client.get("/api/v1/items/count", params={"project_id": str(project.id)})
        assert counted.json()["total"] == 1
        hidden = await client.get(f"/api/v1/items/{rows[ItemVisibility.INTERNAL].id}")
        assert hidden.status_code == 404
        filtered = await client.get(
            "/api/v1/items", params={"project_id": str(project.id), "q": "visibility = internal"}
        )
        assert filtered.status_code == 200 and filtered.json() == []
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test", cookies={SESSION_COOKIE_NAME: cookie}
    ) as client:
        listed = await client.get("/api/v1/items", params={"project_id": str(project.id)})
        assert {i["visibility"] for i in listed.json()} == {"public", "internal"}
