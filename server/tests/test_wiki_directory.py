"""Wiki paging follows access; summaries and direct links do not depend on a window."""

import uuid
from datetime import timedelta

import httpx
import pytest
from sqlalchemy import event
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from radd.app import create_app
from radd.clock import utcnow
from radd.config import settings
from radd.db import get_session
from radd.modules.auth import roles, service as auth
from radd.modules.auth.models import GlobalRoleGrant, Role, User
from radd.modules.auth.schemas import TokenCreate
from radd.modules.auth.types import BuiltinRoleKey
from radd.modules.pages import directory, spaces as space_service
from radd.modules.pages.models import Page, PageSpace


@pytest.fixture
async def world():
    engine = create_async_engine(settings.database_url)
    async with async_sessionmaker(engine, expire_on_commit=False)() as db:
        prefix = uuid.uuid4().hex[:8]
        actor = User(name="Reader", email=prefix + "@test.invalid")
        baseline = await roles.role_by_key(db, BuiltinRoleKey.BASELINE)
        baseline.permissions = []
        reader = Role(key=prefix + "read", name="Reader", permissions=["page.read"])
        writer = Role(
            key=prefix + "write", name="Writer", permissions=["page.write", "comment.write"]
        )
        visible = [
            PageSpace(name=f"{prefix} visible {i:03}", slug=f"{prefix}-{i:03}", position=i)
            for i in range(126)
        ]
        hidden = [
            PageSpace(name=f"{prefix} hidden {i}", slug=f"{prefix}-hidden-{i}", position=-10 + i)
            for i in range(10)
        ]
        db.add_all([actor, reader, writer, *visible, *hidden])
        await db.flush()
        db.add_all(
            [
                GlobalRoleGrant(user_id=actor.id, role_id=reader.id, space_id=space.id)
                for space in visible
            ]
        )
        db.add(GlobalRoleGrant(user_id=actor.id, role_id=writer.id, space_id=visible[-1].id))
        db.add(
            GlobalRoleGrant(
                user_id=actor.id,
                role_id=reader.id,
                space_id=hidden[0].id,
                expires_at=utcnow() - timedelta(days=1),
            )
        )
        db.add_all(
            [
                Page(
                    space_id=space.id,
                    title="Live",
                    slug="live",
                    body="Large private body",
                    created_by=actor.id,
                    updated_by=actor.id,
                )
                for space in [visible[0], visible[-1], hidden[0]]
            ]
        )
        db.add(
            Page(
                space_id=visible[-1].id,
                title="Archived",
                slug="archived",
                body="",
                created_by=actor.id,
                updated_by=actor.id,
                archived_at=utcnow(),
            )
        )
        await db.flush()
        db.info.clear()
        yield db, actor, visible, hidden, engine, prefix
        await db.rollback()
    await engine.dispose()


async def test_wiki_windows_counts_summary_and_direct_identity(world):
    db, actor, visible, hidden, engine, prefix = world
    cookie = await auth.create_session(db, actor)

    async def override():
        yield db

    app = create_app()
    app.dependency_overrides[get_session] = override
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://test",
        cookies={"radd_session": cookie},
    ) as client:
        seen = []
        for offset, count in [(0, 50), (50, 50), (100, 26)]:
            r = await client.get("/api/v1/page-spaces", params={"limit": 50, "offset": offset})
            assert r.status_code == 200 and r.headers["x-total-count"] == "126", r.text
            assert len(r.json()) == count
            seen.extend(r.json())
        assert [row["id"] for row in seen] == [str(space.id) for space in visible]
        assert seen[0]["page_count"] == seen[-1]["page_count"] == 1
        assert all(row["page_count"] == 0 for row in seen[1:-1])
        assert (
            "page.write" not in seen[0]["permissions"] and "page.write" in seen[-1]["permissions"]
        )
        r = await client.get("/api/v1/page-spaces/summary")
        assert r.json() == {
            "total": 126,
            "permissions": ["comment.write", "page.read", "page.write"],
        }
        for identifier in (visible[-1].slug, str(visible[-1].id)):
            r = await client.get("/api/v1/page-spaces/by-identity/" + identifier)
            assert r.status_code == 200 and r.json() == seen[-1], r.text
        for identifier in (hidden[0].slug, str(hidden[0].id), "absent-space"):
            r = await client.get("/api/v1/page-spaces/by-identity/" + identifier)
            assert r.status_code == 404, r.text
        r = await client.get(
            "/api/v1/page-spaces", params={"q": " " + visible[-1].slug + " ", "limit": 50}
        )
        assert r.json() == [seen[-1]] and r.headers["x-total-count"] == "1"
        for q in (prefix + " hidden", "%_"):
            r = await client.get("/api/v1/page-spaces", params={"q": q, "limit": 50})
            assert r.json() == [] and r.headers["x-total-count"] == "0"
        # Existing integrations can still deliberately request the complete list.
        r = await client.get("/api/v1/page-spaces")
        assert r.json() == seen
        for params in ({"limit": 0}, {"limit": 201}, {"offset": -1}, {"q": "x" * 201}):
            assert (await client.get("/api/v1/page-spaces", params=params)).status_code == 422


async def test_summary_selects_only_authority_and_page_counts_only_hydrate_window(world):
    db, actor, visible, hidden, engine, prefix = world
    statements = []

    def record(conn, cursor, statement, parameters, context, executemany):
        statements.append((statement, parameters))

    event.listen(engine.sync_engine, "before_cursor_execute", record)
    try:
        result = await directory.summary(db, actor)
        assert result.total == 126
        assert statements
        assert all("FROM pages" not in sql for sql, _ in statements)
        assert all(
            "page_spaces.name" not in sql and "page_spaces.description" not in sql
            for sql, _ in statements
        )
        statements.clear()
        rows, total = await directory.page(db, actor, limit=50, offset=100)
        assert len(rows) == 26 and total == 126
        counts = [(sql, params) for sql, params in statements if "FROM pages" in sql]
        assert len(counts) == 1
        assert "pages.body" not in counts[0][0]
        assert set(counts[0][1].values()) == {space.id for space in visible[100:]}
    finally:
        event.remove(engine.sync_engine, "before_cursor_execute", record)


@pytest.mark.parametrize("kind", ["empty-admin-key", "read-admin-key", "requester"])
async def test_wiki_directory_uses_principal_scope_and_requester_floor(world, kind):
    db, actor, visible, hidden, engine, prefix = world
    actor.instance_role = "admin" if kind != "requester" else "member"
    if kind == "requester":
        actor.source = "email"
        baseline = await roles.role_by_key(db, BuiltinRoleKey.BASELINE)
        baseline.permissions = ["page.manage"]
        requester = await roles.role_by_key(db, BuiltinRoleKey.REQUESTER)
        requester.permissions = []
    await db.flush()
    db.info.clear()
    _, token = await auth.create_api_token(
        db,
        actor,
        TokenCreate(
            name="Scope",
            scopes={}
            if kind == "empty-admin-key"
            else {"global": ["page.read"]}
            if kind == "read-admin-key"
            else None,
        ),
    )

    async def override():
        yield db

    app = create_app()
    app.dependency_overrides[get_session] = override
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://test",
        headers={"Authorization": f"Bearer {token}"},
    ) as client:
        r = await client.get("/api/v1/page-spaces/summary")
        assert r.status_code == 200
        if kind == "empty-admin-key":
            assert r.json() == {"total": 0, "permissions": []}
        elif kind == "read-admin-key":
            assert r.json()["total"] >= 136 and r.json()["permissions"] == ["page.read"]
        else:
            assert r.json()["total"] == 126 and "page.manage" not in r.json()["permissions"]
        r = await client.get("/api/v1/page-spaces", params={"limit": 50, "q": prefix})
        assert len(r.json()) == (0 if kind == "empty-admin-key" else 50)
        r = await client.get("/api/v1/page-spaces/by-identity/" + visible[-1].slug)
        assert r.status_code == (404 if kind == "empty-admin-key" else 200)
        if kind == "read-admin-key":
            assert r.json()["permissions"] == ["page.read"]


async def test_space_identity_preserves_slug_first_resolution(world):
    db, actor, visible, hidden, engine, prefix = world
    # A UUID-looking slug is a legal slug and historically wins over an ID.
    visible[0].slug = str(visible[-1].id)
    await db.flush()
    assert (await space_service.by_slug_or_id(db, str(visible[-1].id))).id == visible[0].id
    assert (await directory.by_identity(db, actor, str(visible[-1].id))).id == visible[0].id
