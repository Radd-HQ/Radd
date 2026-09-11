"""RADD-1115: pagination must follow visibility, never truncate authority."""
import uuid
from datetime import datetime, timedelta

import httpx
import pytest
from sqlalchemy import event
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from radd.app import create_app
from radd.config import settings
from radd.exceptions import NotFoundError
from radd.modules.auth import authz, service as auth
from radd.modules.auth.models import User
from radd.modules.auth.scopes import parse_scope
from radd.modules.auth.types import Permission, SESSION_COOKIE_NAME
from radd.modules.projects import directory
from radd.modules.projects.models import Project


@pytest.fixture
async def world():
    engine = create_async_engine(settings.database_url)
    async with async_sessionmaker(engine, expire_on_commit=False)() as db:
        actor = User(email=f"directory-{uuid.uuid4()}@example.com", name="Reader", instance_role="admin")
        db.add(actor)
        # Hidden rows deliberately precede every allowed row. Equal timestamps
        # exercise the ID tie-break independently of insertion order.
        prefix = uuid.uuid4().hex[:4].upper()
        rows = [Project(id=uuid.uuid4(), key=f"D{prefix}{i:03}", name=f"Directory {i:03}",
                        created_at=datetime(2026, 1, 1) + timedelta(days=i // 10))
                for i in range(65)]
        db.add_all(rows)
        await db.flush()
        yield db, actor, rows, engine
        await db.rollback()
    await engine.dispose()


async def test_pages_filter_authority_before_limit_and_summary_is_complete(world):
    db, actor, rows, engine = world
    allowed = rows[10:]
    actor.token_scope = parse_scope({"projects": {str(row.id): ["item.read"] +
        (["item.create"] if row is rows[-1] else []) for row in allowed}})
    expected = sorted(allowed, key=lambda row: (row.created_at, row.id))
    seen = []
    for offset in range(0, 55, 20):
        page, total = await directory.page(db, actor, limit=20, offset=offset)
        assert total == 55
        assert len(page) <= 20
        seen.extend(row.id for row in page)
    assert seen == [row.id for row in expected]
    summary = await directory.summary(db, actor)
    assert summary.total == 55 and summary.related_count == 0
    assert set(summary.permissions) == {"item.read", "item.create"}
    create, total = await directory.page(db, actor, permission=Permission.ITEM_CREATE, limit=1)
    assert total == 1 and create[0].id == rows[-1].id
    for kwargs in ({"identifier": rows[0].id}, {"key": rows[0].key}):
        with pytest.raises(NotFoundError):
            await directory.by_identity(db, actor, **kwargs)
    direct = await directory.by_identity(db, actor, key=rows[-1].key.lower())
    assert direct.id == rows[-1].id and "item.create" in direct.permissions
    filtered, total = await directory.page(db, actor, q=rows[-1].key.lower(), limit=1)
    assert total == 1 and filtered[0].id == rows[-1].id
    # Literal SQL wildcard characters must not become an enumeration shortcut.
    filtered, total = await directory.page(db, actor, q="%_", limit=20)
    assert filtered == [] and total == 0


async def test_project_summary_does_not_load_every_project_body(world):
    db, actor, rows, engine = world
    statements = []
    def record(conn, cursor, statement, parameters, context, executemany):
        statements.append(statement)
    event.listen(engine.sync_engine, "before_cursor_execute", record)
    try:
        await directory.summary(db, actor)
    finally:
        event.remove(engine.sync_engine, "before_cursor_execute", record)
    project_reads = [sql for sql in statements if "FROM projects" in sql]
    assert project_reads
    assert all("projects.name" not in sql and "projects.next_number" not in sql for sql in project_reads)


async def test_http_page_contract_and_direct_resolution(world):
    db, actor, rows, engine = world
    cookie = await auth.create_session(db, actor)
    await db.commit()
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=create_app()), base_url="http://test",
                                cookies={SESSION_COOKIE_NAME: cookie}) as client:
        path = "/api/v1/projects"
        response = await client.get(path, params={"q": rows[0].key[:5], "limit": 50})
        assert response.status_code == 200
        assert len(response.json()) == 50 and response.headers["X-Total-Count"] == "65"
        rest = await client.get(path, params={"q": rows[0].key[:5], "limit": 50, "offset": 50})
        assert len(rest.json()) == 15
        assert not ({r["id"] for r in response.json()} & {r["id"] for r in rest.json()})
        summary = await client.get(path + "/summary")
        assert summary.status_code == 200 and summary.json()["total"] >= 65
        for suffix in (f"/{rows[-1].id}", f"/by-key/{rows[-1].key.lower()}"):
            direct = await client.get(path + suffix)
            assert direct.status_code == 200 and direct.json()["id"] == str(rows[-1].id)
        for params in ({"limit": 201}, {"limit": 0}, {"offset": -1}, {"permission": "bogus"}):
            assert (await client.get(path, params=params)).status_code == 422
        await client.post("/api/v1/auth/logout")
